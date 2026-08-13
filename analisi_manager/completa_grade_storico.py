# -*- coding: utf-8 -*-
"""Riempimento dell'indice grade condiviso con la rotta PROFONDA (13/08/2026).

PERCHE' ESISTE, in due righe: `completa_grade_mancante.py` usa
`playerGameScores(last: 15)`, e quel 15 e' un TETTO DEL SERVER (verificato:
chiedendo 50/100/200 torna sempre 15, senza errore -- e `first`/`before` non
esistono, nessun cursore). Quindi su una giornata di febbraio 2026 quella
rotta non arriva piu': misurato il 13/08 sulla GW55, copriva 215 giocatori
su 825 (26%).

Questa usa `allPlayerGameScores(first: N)` -- lo STESSO campo che il predict
gia' interroga per la cache game-log, che accetta `projection { grade }` e
non ha quel tetto: 50 partite per giocatore, fino ad agosto 2025 (misurato:
Altimira 50/50 con grade dal 22-08-2025; il grade non esiste prima di
~agosto 2025, verificato anche per partita: giugno 2025 = 0%, settembre
2025 = 100%).

Scrive nello STESSO file persistente che legge l'indice condiviso
(`analisi_manager/dati/storico_grade_crowss_completamento.json`), con lo
stesso dedup su (slug, game_date): e' incrementale e va a beneficio di ogni
consumer (p12/p13/p23/p24...), non solo di chi lo lancia.

Verificato che le due rotte danno LO STESSO voto: 71 righe confrontabili,
71 identiche.

Credenziali: SORARE_COOKIE + SORARE_CSRF (obbligatorie).
Chiavi: SORARE_APIKEY, SORARE_APIKEY_2, SORARE_APIKEY_3 (facoltative, ma
alzano il tetto da 60 a 200 richieste/min ciascuna -- si sommano). La prima
NON si chiama _1, vedi CLAUDE.md.

Uso:
  # dagli slug presenti in una o piu' giornate dell'archivio ufficiale
  python analisi_manager/completa_grade_storico.py --fixture football-20-24-feb-2026
  python analisi_manager/completa_grade_storico.py --fixture-tutte
  # oppure slug espliciti
  python analisi_manager/completa_grade_storico.py --slug pippo-baudo altro-slug
Opzioni: --solo-mancanti (default: salta chi ha gia' una riga nella
finestra della fixture), --thread N (default 6), --partite N (default 50).
"""
import os
import sys
import io
import json
import glob
import time
import argparse
import threading
import collections
import concurrent.futures as cf

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'discovery'))

import mls_def_discovery_global as g  # noqa: E402

COOKIE = os.environ.get('SORARE_COOKIE', '')
CSRF = os.environ.get('SORARE_CSRF', '')
CHIAVI = [k for k in (os.environ.get('SORARE_APIKEY', ''),
                      os.environ.get('SORARE_APIKEY_2', ''),
                      os.environ.get('SORARE_APIKEY_3', '')) if k]

PATH_INDICE = os.path.join('analisi_manager', 'dati',
                           'storico_grade_crowss_completamento.json')

QUERY = """
query AllScoresGrade($slug: String!, $first: Int!) {
  anyPlayer(slug: $slug) {
    allPlayerGameScores(first: $first) {
      nodes {
        anyGame { date }
        projection { grade }
      }
    }
  }
}
"""

_lock = threading.Lock()
_giro = collections.Counter()

# FRENO DI RITMO (aggiunto 13/08/2026 dopo un 429 persistente su 3810 slug).
# Il tetto Sorare non e' una velocita' istantanea ma un CREDITO che si
# ricarica: 825 richieste di fila passano senza un 429 (misurato), 3810 lo
# esauriscono e da li' in poi risponde 429 a tutto, con Retry-After da 150 a
# 290 secondi. Abbassare i thread NON basta -- i thread regolano quante
# richieste sono in volo insieme, non quante ne parti al minuto. Serve un
# tetto sul RITMO SOSTENUTO, che e' questo.
LIMITE_RPM = int(os.environ.get('GRADE_RPM', '450'))   # con 3 chiavi il tetto
                                                       # documentato e' 600/min
_partenze = collections.deque()


def _aspetta_il_turno():
    """Non parte piu' di LIMITE_RPM richieste in una finestra di 60 secondi."""
    while True:
        with _lock:
            ora = time.time()
            while _partenze and ora - _partenze[0] > 60.0:
                _partenze.popleft()
            if len(_partenze) < LIMITE_RPM:
                _partenze.append(ora)
                return
            attesa = 60.0 - (ora - _partenze[0]) + 0.05
        time.sleep(max(0.05, attesa))


def _headers():
    h = {'Content-Type': 'application/json', 'Accept': 'application/json',
         'Cookie': COOKIE, 'X-CSRF-Token': CSRF}
    if CHIAVI:
        # rotazione tonda: i tetti delle chiavi sono indipendenti e si
        # sommano (CLAUDE.md), quindi si alterna a ogni richiesta
        with _lock:
            i = _giro['n'] % len(CHIAVI)
            _giro['n'] += 1
        h['APIKEY'] = CHIAVI[i]
    return h


def righe_di(slug, partite):
    """Ritorna (righe, errore). righe = [{'slug','game_date','grade'}]."""
    if not COOKIE or not CSRF:
        return None, 'no_credenziali'
    payload = {'query': QUERY, 'variables': {'slug': slug, 'first': partite}}
    for tentativo in range(6):
        _aspetta_il_turno()
        try:
            r = g._http_session.post(g.GRAPHQL_URL, json=payload,
                                     headers=_headers(), timeout=30)
        except Exception as e:
            if tentativo == 5:
                return None, f'rete: {e}'
            time.sleep(1 + tentativo * 2)
            continue
        if r.status_code == 429:
            # SI RISPETTA Retry-After. Prima qui c'era una pausa fissa di
            # 5 e poi 15 secondi: contro un credito esaurito che vuole 150-290
            # secondi non serve a niente, e dopo 3 tentativi lo script si
            # arrendeva dichiarando "429 persistente" un problema che era solo
            # un'attesa troppo corta. Errore trovato il 13/08 su un lotto da
            # 3810 slug.
            attesa = 60.0
            try:
                attesa = float(r.headers.get('Retry-After') or 60.0)
            except ValueError:
                pass
            attesa = min(attesa, 300.0) + 1.0
            with _lock:
                _partenze.clear()   # il credito e' finito: si riparte da zero
            print(f'  429 su {slug}: aspetto {attesa:.0f}s '
                  f'(tentativo {tentativo + 1}/6)', flush=True)
            time.sleep(attesa)
            continue
        if r.status_code != 200:
            return None, f'HTTP {r.status_code}: {r.text[:120]}'
        d = r.json()
        if d.get('errors'):
            return None, 'GraphQL: ' + json.dumps(d['errors'][:1], ensure_ascii=False)[:180]
        ap = (d.get('data') or {}).get('anyPlayer')
        if ap is None:
            return None, 'anyPlayer_null'
        out = []
        for n in ((ap.get('allPlayerGameScores') or {}).get('nodes') or []):
            grade = (n.get('projection') or {}).get('grade')
            data = (n.get('anyGame') or {}).get('date')
            if grade and data:
                out.append({'slug': slug, 'game_date': data, 'grade': grade})
        return out, None
    return None, '429_persistente'


def slug_da_fixture(fixture):
    """Tutti gli slug carta presenti in quella giornata dell'archivio."""
    slugs = set()
    modello = os.path.join('archivio_ufficiale', 'manager_*', '**',
                           f'{fixture}_arene_limited.json')
    for f in glob.glob(modello, recursive=True):
        with open(f, encoding='utf-8') as fh:
            d = json.load(fh)
        for riga in (d['righe'] if isinstance(d, dict) else d):
            for c in (riga.get('carte') or []):
                if c.get('slug'):
                    slugs.add(c['slug'])
    return slugs


def fixture_in_archivio():
    fx = set()
    for f in glob.glob(os.path.join('archivio_ufficiale', 'manager_*', '**',
                                    '*_arene_limited.json'), recursive=True):
        fx.add(os.path.basename(f).replace('_arene_limited.json', ''))
    return sorted(fx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', action='append', default=[])
    ap.add_argument('--fixture-tutte', action='store_true')
    ap.add_argument('--slug', nargs='*', default=[])
    ap.add_argument('--thread', type=int, default=6)
    ap.add_argument('--partite', type=int, default=50)
    ap.add_argument('--solo-mancanti', action='store_true', default=True)
    ap.add_argument('--tutti', dest='solo_mancanti', action='store_false',
                    help='riquery anche chi ha gia' + " righe (per aggiornare)")
    args = ap.parse_args()

    fixture = list(args.fixture)
    if args.fixture_tutte:
        fixture = fixture_in_archivio()

    bersagli = set(args.slug)
    for fx in fixture:
        bersagli |= slug_da_fixture(fx)
    if not bersagli:
        print('nessuno slug da interrogare: passa --fixture, --fixture-tutte o --slug')
        return

    with open(PATH_INDICE, encoding='utf-8') as fh:
        esistenti = json.load(fh)
    chiavi = {(r['slug'], r['game_date']) for r in esistenti}
    gia_noti = collections.Counter(r['slug'] for r in esistenti)

    da_fare = sorted(bersagli)
    saltati = 0
    if args.solo_mancanti:
        # si salta solo chi ha gia' >= partite righe: la rotta profonda
        # aggiunge storico anche a chi e' gia' nell'indice per altre date
        prima = len(da_fare)
        da_fare = [s for s in da_fare if gia_noti[s] < args.partite]
        saltati = prima - len(da_fare)

    print('slug bersaglio: %d  |  gia completi, saltati: %d  |  da interrogare: %d'
          % (len(bersagli), saltati, len(da_fare)))
    print('chiavi APIKEY attive: %d  |  thread: %d  |  partite per giocatore: %d'
          % (len(CHIAVI), args.thread, args.partite))
    if not da_fare:
        return

    t0 = time.time()
    nuove = []
    falliti = {}
    fatti = 0
    salvate = 0

    def salva():
        """Scrittura atomica: prima su un file accanto, poi si rinomina. Se il
        processo muore a meta' scrittura, l'indice vecchio resta intero."""
        tmp = PATH_INDICE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(esistenti + nuove, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, PATH_INDICE)

    with cf.ThreadPoolExecutor(max_workers=args.thread) as ex:
        futuri = {ex.submit(righe_di, s, args.partite): s for s in da_fare}
        for fut in cf.as_completed(futuri):
            s = futuri[fut]
            fatti += 1
            righe, err = fut.result()
            if err:
                falliti[s] = err
            else:
                for r in righe:
                    k = (r['slug'], r['game_date'])
                    if k not in chiavi:
                        chiavi.add(k)
                        nuove.append(r)
            # CHECKPOINT (13/08/2026): prima si salvava SOLO alla fine, quindi
            # un run interrotto -- o killato perche' sembrava impantanato --
            # buttava via tutto il lavoro gia' fatto. Ora l'indice cresce per
            # gradi: si puo' fermare e ripartire, e il salto dei gia' completi
            # fa ripartire da dove si era arrivati.
            if fatti % 200 == 0:
                salva()
                salvate = len(nuove)
                print('  ... %d/%d giocatori, %d righe nuove (salvate), %.0fs'
                      % (fatti, len(da_fare), len(nuove), time.time() - t0),
                      flush=True)
            elif fatti % 50 == 0:
                print('  ... %d/%d giocatori, %d righe nuove, %.0fs'
                      % (fatti, len(da_fare), len(nuove), time.time() - t0),
                      flush=True)

    salva()
    del salvate
    esistenti = esistenti + nuove

    print()
    print('righe NUOVE aggiunte: %d   (indice: %d -> %d)'
          % (len(nuove), len(esistenti) - len(nuove), len(esistenti)))
    print('giocatori falliti: %d' % len(falliti))
    for s, e in list(falliti.items())[:10]:
        print('   %-34s %s' % (s, e))
    print('tempo: %.0fs  (%.1f giocatori/s)'
          % (time.time() - t0, len(da_fare) / max(0.001, time.time() - t0)))


if __name__ == '__main__':
    main()
