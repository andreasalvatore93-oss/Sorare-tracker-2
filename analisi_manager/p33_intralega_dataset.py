# -*- coding: utf-8 -*-
"""FILONE INTRALEGA -- passo 1: il dataset (zero query, solo cache in repo).

DOMANDA DEL FILONE (utente, 13/08/2026): dentro UNO STESSO campionato, il voto
degli attaccanti della squadra A contro la difesa della squadra B nelle ultime
5/10 partite dice qualcosa che il modello non sa gia'? E lo specchio: i
difensori di A contro l'attacco di B.

PERCHE' "INTRALEGA" NON E' UN DETTAGLIO. La produzione un condizionamento
sull'avversario ce l'ha gia' (`opponent_strength.opponent_lambda_multiplier`,
gol subiti dell'avversario nelle ultime 10), MA lo normalizza su una media
MONDIALE (GLOBAL_MEAN_CONCEDED/GLOBAL_STD_CONCEDED, righe 319-321): in un
campionato dove tutti prendono gol, tutte le squadre risultano deboli insieme
e le differenze DENTRO la lega si schiacciano. Qui si misura tutto contro la
media della LEGA di quell'anno, che e' il buco vero.

COSA PRODUCE: una riga per (giocatore, partita) con gia' attaccate le due
serie della squadra e dell'avversario calcolate AS-OF, cioe' solo sulle
partite PRECEDENTI a quella (mai la partita stessa: sarebbe leakage puro).

TRE COSE CHE VANNO FATTE BENE, o il dataset non vale niente:
1. WALK-FORWARD. Ogni media di squadra usa solo partite con data STRETTAMENTE
   precedente al kickoff della riga. Nessuna media "di stagione".
2. UNA RIGA PER (giocatore, partita). Lo stesso incontro compare nel game log
   di tutti i giocatori che l'hanno giocato: le medie di SQUADRA si calcolano
   deduplicando per (squadra, avversario, data), altrimenti una squadra con
   piu' giocatori in cache pesa di piu' di una con pochi (e' la trappola §8.15
   del riassunto, gia' costata un "Portogallo +19,8 a 6,4 sigma" che era un
   solo giocatore contato otto volte).
3. SOLO CHI HA GIOCATO DAVVERO. Le medie di reparto si costruiscono sui
   titolari (>=60 minuti): un panchinaro entrato 5 minuti prende ~35 punti di
   level score e sporca la media del reparto verso il basso, senza dire niente
   sulla forza del reparto.

Uso:  python analisi_manager/p33_intralega_dataset.py [--giorni 540]
Scrive: analisi_manager/dati/intralega_righe.json
"""
import os
import sys
import json
import glob
import argparse
import datetime
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)

from discovery_fixture import LEAGUE_DIR   # comp slug -> cartella del repo

# Stesso alias del badge "nuovo campionato" (build_formazione_globale.py): la
# J1 100 Year Vision e' la stessa lega della J1, con una cartella propria.
ALIAS_LEGA = {'giappone100': 'giappone'}

MIN_MINUTI_TITOLARE = 60      # sotto, non e' una prestazione da reparto
RUOLI = ('Goalkeeper', 'Defender', 'Midfielder', 'Forward')
RUOLO_BREVE = {'Goalkeeper': 'gk', 'Defender': 'def',
               'Midfielder': 'mid', 'Forward': 'fwd'}


def lega(nome):
    return ALIAS_LEGA.get(nome, nome)


def _data(iso):
    if not iso or len(iso) < 10:
        return None
    try:
        return datetime.date(int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    except ValueError:
        return None


def leggi_cache(giorni):
    """Tutte le partite di tutti i giocatori in cache, una riga per
    (giocatore, partita). Ritorna la lista grezza."""
    limite = datetime.date.today() - datetime.timedelta(days=giorni)
    righe, visti_file = [], 0
    for cache_dir in sorted(glob.glob(os.path.join(
            ROOT, 'formazione_*', 'output', '*_all', '.game_log_cache'))):
        for fpath in sorted(glob.glob(os.path.join(cache_dir, '*_gamelog.json'))):
            slug = os.path.basename(fpath)[:-len('_gamelog.json')]
            try:
                with open(fpath, encoding='utf-8') as fh:
                    log = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            visti_file += 1
            partite = [r for r in log.values() if r.get('anyGame')]
            if not partite:
                continue
            # squadra del giocatore: la piu' ricorrente fra home e away di
            # tutte le sue partite (stesso metodo di
            # opponent_strength._player_team_slug, non reinventato)
            conta = defaultdict(int)
            for r in partite:
                for lato in ('homeTeam', 'awayTeam'):
                    s = ((r['anyGame'].get(lato) or {}).get('slug'))
                    if s:
                        conta[s] += 1
            if not conta:
                continue
            mia = max(conta, key=conta.get)
            for r in partite:
                g = r['anyGame']
                d = _data(g.get('date'))
                if d is None or d < limite:
                    continue
                if g.get('statusTyped') != 'played':
                    continue
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if mia == casa:
                    avv, in_casa = fuori, True
                elif mia == fuori:
                    avv, in_casa = casa, False
                else:
                    continue          # partita di un'altra squadra (trasferito)
                comp = ((g.get('competition') or {}).get('slug')) or ''
                cart = LEAGUE_DIR.get(comp)
                if cart is None:
                    continue          # coppa/continentale: fuori dall'intralega
                stat = r.get('anyPlayerGameStats') or {}
                minuti = stat.get('minsPlayed')
                ruolo = RUOLO_BREVE.get(r.get('positionTyped'))
                if ruolo is None or r.get('score') is None:
                    continue
                righe.append({
                    'slug': slug, 'data': d.isoformat(), 'lega': lega(cart),
                    'squadra': mia, 'avversario': avv, 'casa': in_casa,
                    'ruolo': ruolo, 'voto': float(r['score']),
                    'minuti': minuti if isinstance(minuti, int) else None,
                })
    return righe, visti_file


def serie_reparto(righe):
    """(lega, squadra, ruolo) -> lista ordinata di (data, voto_medio_reparto).

    UNA VOCE PER PARTITA, non per giocatore: si fa prima la media dei titolari
    di quel reparto in quella partita, poi si mette in serie. Cosi' una squadra
    con 5 difensori in cache non pesa piu' di una che ne ha 2."""
    per_partita = defaultdict(list)
    for r in righe:
        if r['minuti'] is None or r['minuti'] < MIN_MINUTI_TITOLARE:
            continue
        per_partita[(r['lega'], r['squadra'], r['ruolo'], r['data'])].append(r['voto'])
    serie = defaultdict(list)
    for (lg, sq, ruolo, data), voti in per_partita.items():
        serie[(lg, sq, ruolo)].append((data, sum(voti) / len(voti), len(voti)))
    for k in serie:
        serie[k].sort()
    return serie


def media_asof(serie, chiave, data, n):
    """Media delle ultime n partite STRETTAMENTE precedenti a `data`.
    Ritorna (media, quante) oppure (None, 0)."""
    storico = [v for d, v, _q in serie.get(chiave, []) if d < data]
    if not storico:
        return None, 0
    ultime = storico[-n:]
    return sum(ultime) / len(ultime), len(ultime)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--giorni', type=int, default=540,
                    help='quanto storico leggere (default 540)')
    ap.add_argument('--out', default=os.path.join(_HERE, 'dati', 'intralega_righe.json'))
    ap.add_argument('--out-serie', default=os.path.join(_HERE, 'dati', 'intralega_serie.json'),
                    help='le sole serie di reparto (piccole, versionate): le '
                         'legge il segnale in intralega_segnale.py')
    args = ap.parse_args()

    righe, n_file = leggi_cache(args.giorni)
    print(f"file di cache letti: {n_file} | righe (giocatore,partita) di "
          f"campionato: {len(righe)}")
    leghe = defaultdict(int)
    for r in righe:
        leghe[r['lega']] += 1
    print(f"leghe coperte: {len(leghe)} | prime 8: "
          f"{sorted(leghe.items(), key=lambda kv: -kv[1])[:8]}")

    serie = serie_reparto(righe)
    print(f"serie di reparto (lega,squadra,ruolo): {len(serie)}")

    # Le SOLE serie, in un file piccolo e versionabile: e' l'unica cosa che
    # serve al segnale in produzione/backtest (il dataset da 57 MB resta
    # fuori da git e si rigenera con questo stesso script).
    compatta = {f'{lg}|{sq}|{ruolo}': [[d, round(v, 3)] for d, v, _q in val]
                for (lg, sq, ruolo), val in serie.items()}
    with open(args.out_serie, 'w', encoding='utf-8') as fh:
        json.dump({'costruito': datetime.date.today().isoformat(),
                   'min_minuti': MIN_MINUTI_TITOLARE, 'serie': compatta},
                  fh, ensure_ascii=False)
    print(f"scritto: {args.out_serie}")

    # Aggancio delle due serie AS-OF a ogni riga. 'att_avv'/'dif_avv' sono la
    # forza del reparto AVVERSARIO prima della partita; 'att_mia'/'dif_mia'
    # quella del proprio, che serve da controllo (senza, si rischia di
    # attribuire all'avversario la forza della propria squadra).
    fuori = 0
    for r in righe:
        for etichetta, sq, ruolo in (
                ('att_avv', r['avversario'], 'fwd'), ('dif_avv', r['avversario'], 'def'),
                ('att_mia', r['squadra'], 'fwd'), ('dif_mia', r['squadra'], 'def')):
            for n in (5, 10):
                m, q = media_asof(serie, (r['lega'], sq, ruolo), r['data'], n)
                r[f'{etichetta}_{n}'] = None if m is None else round(m, 3)
                r[f'{etichetta}_{n}_n'] = q
        if r['dif_avv_5'] is None:
            fuori += 1

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'costruito': datetime.date.today().isoformat(),
                   'giorni': args.giorni, 'min_minuti': MIN_MINUTI_TITOLARE,
                   'righe': righe}, fh, ensure_ascii=False)
    print(f"righe senza storico difensivo dell'avversario (nessun confronto "
          f"possibile, resteranno non corrette): {fuori} "
          f"({100.0 * fuori / max(1, len(righe)):.1f}%)")
    print(f"scritto: {args.out}")


if __name__ == '__main__':
    main()
