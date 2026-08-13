"""scarica_cache_backtest — riempie i buchi di cache che bloccano il backtest arene.

Il backtest (backtest_arene.py) rigioca le formazioni arena dell'utente con il
modello, ma puo' farlo solo dove ha in cache lo storico di TUTTE E CINQUE le
carte. Con il 89% dei giocatori coperti, le formazioni complete sono solo il
55% -- basta che manchi un giocatore su cinque.

Questo script trova i giocatori che mancano (o il cui storico non arriva
abbastanza indietro nel tempo) e ne scarica game log + dettagli granulari in
una cartella dedicata, che backtest_arene_cache legge insieme alle altre.

Non tocca nessuna cache di produzione: scrive solo in
`dati_globali/backtest_arene_cache/`.

    python scarica_cache_backtest.py --elenco     # dice cosa manca, senza rete
    python scarica_cache_backtest.py              # scarica
    python scarica_cache_backtest.py --max 20     # solo i primi 20 (prova)

Autenticazione via SORARE_COOKIE (60 query/min invece di 20).
"""
import os
import sys
import json
import io
import glob
import time
import argparse
import datetime
import collections

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, 'formazione_mls', 'predict'))
sys.path.insert(0, _ROOT)

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import test_def

DEST = os.path.join(_ROOT, 'dati_globali', 'backtest_arene_cache')
DEST_DETTAGLI = os.path.join(DEST, '.cache')
DEST_GAMELOG = os.path.join(DEST, '.game_log_cache')

# Quante partite chiedere per giocatore: l'archivio arene parte da luglio 2025
# e il modello guarda fino a 365 giorni indietro, quindi servono circa due
# stagioni di storico, non le 50 partite della finestra di produzione.
PARTITE_DA_CHIEDERE = 100
# Il dettaglio granulare si scarica solo per le partite che possono davvero
# finire in una finestra storica: quelle giocate (non DID_NOT_PLAY) con
# minutaggio pieno.
MAX_DETTAGLI_PER_GIOCATORE = 80


def _carica(percorso):
    with io.open(percorso, encoding='utf-8') as fh:
        return json.load(fh)


def cosa_manca():
    """(slug -> ruolo) dei giocatori che bloccano almeno una formazione."""
    cache = C.CacheLocale()
    disponibili = cache.slug_disponibili()
    form = _carica('dati_globali/arene_formazioni.json')['formazioni']
    arene = _carica('dati_globali/arene_storico.json')['arene']
    fine = {}
    for a in arene:
        prec = fine.get(a['fixture'])
        fine[a['fixture']] = a['fine'] if prec is None else min(prec, a['fine'])

    mancanti = {}
    blocchi = collections.Counter()
    finestre = {}  # slug -> (prima giornata che lo richiede, ultima)
    for v in form.values():
        fd = P._dt(fine.get(v['fixture']))
        if fd is None:
            continue
        for g in v['giocatori']:
            slug = g['slug']
            serve = (slug not in disponibili
                     or P.partita_target(cache, slug, fd) is None)
            if not serve:
                continue
            mancanti.setdefault(slug, g['ruolo'])
            blocchi[slug] += 1
            prima, ultima = finestre.get(slug, (fd, fd))
            finestre[slug] = (min(prima, fd), max(ultima, fd))
    return mancanti, blocchi, finestre


_MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
         'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def _fine_da_slug(fx):
    """Ultimo giorno della giornata, letto dallo slug. Stessa regola di
    estrai_archivio_manager.fine_fixture (non lo importo: quel modulo si
    tira dietro ricostruisci_manager e build_formazione_globale, qui
    servirebbero solo per sei righe di calendario).

    Ritorna un datetime NAIVE a fine giornata: partita_target confronta con
    le date dei game log, che P._dt restituisce come datetime senza fuso
    (backtest_arene_previsioni.py:51-57). Una `date` qui fa esplodere il
    confronto.
    """
    toks = fx.split('-')[1:]
    try:
        anno = int(toks[-1])
        toks = toks[:-1]
        i = [j for j, t in enumerate(toks) if t in _MESI][-1]
        return datetime.datetime(anno, _MESI[toks[i]], int(toks[i - 1]),
                                 23, 59, 59)
    except Exception:
        return None


def cosa_manca_archivio():
    """Come cosa_manca(), ma i bersagli vengono da archivio_ufficiale/.

    PERCHE' ESISTE (13/08/2026): cosa_manca() legge
    dati_globali/arene_formazioni.json, che e' il vecchio backtest di solo
    crowss -- 844 slug, tutti gia' in cache. Da quando l'archivio e'
    multi-manager quel file non descrive piu' il lavoro da fare: con 65
    manager i giocatori distinti sono migliaia, e lo script rispondeva
    "0 da scaricare" mentre ne mancavano 1820. Trovato da Sonnet leggendo
    il codice invece della docstring.

    Il criterio per dire "manca" e' lo STESSO di cosa_manca(): o lo slug non
    e' in cache, o la cache non arriva abbastanza indietro da avere una
    partita-target per quella giornata.
    """
    cache = C.CacheLocale()
    disponibili = cache.slug_disponibili()
    mancanti, blocchi, finestre = {}, collections.Counter(), {}
    modello = os.path.join(_ROOT, 'archivio_ufficiale', 'manager_*', '**',
                           '*_arene_limited.json')
    for percorso in glob.glob(modello, recursive=True):
        fx = os.path.basename(percorso).replace('_arene_limited.json', '')
        fd = _fine_da_slug(fx)
        if fd is None:
            continue
        try:
            dati = _carica(percorso)
        except Exception:
            continue
        righe = dati['righe'] if isinstance(dati, dict) else dati
        for riga in righe:
            for carta in (riga.get('carte') or []):
                slug = carta.get('slug')
                if not slug:
                    continue
                serve = (slug not in disponibili
                         or P.partita_target(cache, slug, fd) is None)
                if not serve:
                    continue
                mancanti.setdefault(slug, carta.get('ruolo'))
                blocchi[slug] += 1
                prima, ultima = finestre.get(slug, (fd, fd))
                finestre[slug] = (min(prima, fd), max(ultima, fd))
    return mancanti, blocchi, finestre


def _dt(iso):
    return P._dt(iso)


def scarica(slug, pausa, finestra=None):
    """Game log + dettagli granulari di un giocatore, salvati in DEST.

    `finestra` = (prima giornata, ultima giornata) in cui questo giocatore
    serve davvero. Il dettaglio granulare si scarica SOLO per le partite che
    possono finire in una di quelle finestre storiche (fino a 365 giorni prima
    della prima, e non oltre l'ultima): senza questo filtro si scaricherebbero
    circa 80 partite a testa, quasi tutte inutili."""
    file_gamelog = os.path.join(DEST_GAMELOG, f'{slug}_gamelog.json')
    file_dettagli = os.path.join(DEST_DETTAGLI, f'{slug}_detail_cache.json')

    # fetch_game_scores pagina la richiesta: una singola query con first=100
    # sfonda il tetto di complessita' GraphQL (500 senza APIKEY, trappola
    # 48.D.5) -- verificato sul campo, risponde "complexity of 2932".
    risposta = test_def.fetch_game_scores(slug, PARTITE_DA_CHIEDERE)
    giocatore = (((risposta or {}).get('data') or {}).get('anyPlayer')) or {}
    passate = (giocatore.get('allPlayerGameScores') or {}).get('nodes') or []
    if not passate:
        return 0, 0

    gamelog = {}
    for nodo in passate:
        if nodo.get('id'):
            gamelog[nodo['id']] = nodo
    with io.open(file_gamelog, 'w', encoding='utf-8') as fh:
        json.dump(gamelog, fh, ensure_ascii=False)

    dettagli = {}
    if os.path.exists(file_dettagli):
        try:
            dettagli = _carica(file_dettagli)
        except Exception:
            dettagli = {}

    # dalle piu' recenti: sono quelle che pesano di piu' in ogni finestra
    candidate = [n for n in passate
                 if n.get('scoreStatus') in ('FINAL', 'REVIEWING')
                 and ((n.get('anyPlayerGameStats') or {}).get('minsPlayed') or 0)
                 >= test_def.MIN_MINUTES_PLAYED]
    if finestra:
        prima, ultima = finestra
        limite = prima - datetime.timedelta(days=P.MAX_HISTORY_DAYS)
        candidate = [n for n in candidate
                     if limite <= (_dt((n.get('anyGame') or {}).get('date')) or limite) <= ultima]
    candidate.sort(key=lambda n: (n.get('anyGame') or {}).get('date') or '', reverse=True)

    da_scaricare = candidate[:MAX_DETTAGLI_PER_GIOCATORE]

    # DETTAGLI IN BATCH (13/08/2026). Prima si chiedeva UNA query per partita:
    # misurato su 20 giocatori, 41,7 dettagli a testa e 35 secondi a
    # giocatore, cioe' 21 ore per i 2219 dell'archivio. `test_def` ha gia' la
    # strada buona -- `precarica_dettagli_batch` chiede 30 partite in una
    # richiesta sola con l'APIKEY (6 senza) -- ma questo script non l'ha mai
    # chiamata. Riempie `dettagli`, e il ciclo qui sotto salta da solo tutto
    # quello che ci trova dentro.
    # SICURA PER COSTRUZIONE: tratta solo le partite FINAL (le altre cambiano
    # ancora e vanno chieste fresche), e se il batch viene rifiutato non
    # scrive niente -- il ciclo di sempre le richiede una per una. Il caso
    # peggiore e' esattamente il comportamento di prima.
    prima_del_batch = len(dettagli)
    try:
        test_def.precarica_dettagli_batch(da_scaricare, dettagli)
    except Exception as exc:
        print(f"  batch dettagli non riuscito ({exc}): si prosegue una per una")
    nuovi = len(dettagli) - prima_del_batch

    for nodo in da_scaricare:
        score_id = nodo['id'].replace('So5Score:', '')
        if score_id in dettagli:
            continue
        time.sleep(pausa)
        dettaglio = test_def.fetch_game_detail(score_id, dettagli, is_final=False)
        if dettaglio is not None:
            dettagli[score_id] = dettaglio
            nuovi += 1

    with io.open(file_dettagli, 'w', encoding='utf-8') as fh:
        json.dump(dettagli, fh, ensure_ascii=False)
    return len(gamelog), nuovi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--elenco', action='store_true', help='dice cosa manca e si ferma')
    ap.add_argument('--max', type=int, default=0, help='limita il numero di giocatori')
    # 60 query/min autenticati -> 1.0s e' esattamente al limite, 1.2 sta sotto
    # (trappola 48.D.5 del riassunto). Anonimo: 20/min, servono 3.2s.
    ap.add_argument('--pausa', type=float, default=None)
    ap.add_argument('--da-archivio', action='store_true', dest='da_archivio',
                    help='prende i bersagli da archivio_ufficiale/ invece che '
                         'dal vecchio dati_globali/arene_formazioni.json '
                         '(844 slug del solo crowss). Default INVARIATO.')
    args = ap.parse_args()

    autenticato = bool(os.environ.get('SORARE_COOKIE', '').strip())
    # La pausa di default resta 1.2s, tarata sui 60/min del solo cookie. CON
    # LE APIKEY il tetto e' 600/min e si puo' scendere a ~0.15 passando
    # --pausa: non lo cambio di default perche' chi lancia senza chiavi
    # verrebbe bannato.
    pausa = args.pausa if args.pausa is not None else (1.2 if autenticato else 3.2)

    mancanti, blocchi, finestre = (cosa_manca_archivio() if args.da_archivio
                                   else cosa_manca())
    ordinati = sorted(mancanti, key=lambda s: -blocchi[s])
    print(f"Giocatori da scaricare: {len(ordinati)} "
          f"(bloccano {sum(blocchi.values())} presenze in formazione)")
    print(f"Autenticato: {autenticato} — pausa {pausa}s fra query")
    if args.elenco:
        for s in ordinati[:40]:
            prima, ultima = finestre[s]
            print(f"  {blocchi[s]:3d} formazioni  {s:42s} "
                  f"{prima:%Y-%m-%d} -> {ultima:%Y-%m-%d}")
        return

    os.makedirs(DEST_DETTAGLI, exist_ok=True)
    os.makedirs(DEST_GAMELOG, exist_ok=True)
    if args.max:
        ordinati = ordinati[:args.max]

    inizio = time.time()
    tot_dett = 0
    for i, slug in enumerate(ordinati, 1):
        try:
            n_log, n_dett = scarica(slug, pausa, finestre.get(slug))
        except Exception as exc:
            print(f"[{i}/{len(ordinati)}] {slug}: ERRORE {exc}")
            continue
        tot_dett += n_dett
        print(f"[{i}/{len(ordinati)}] {slug}: {n_log} partite, {n_dett} dettagli nuovi "
              f"(totali {tot_dett}, {int(time.time()-inizio)}s)")
        time.sleep(pausa)

    print(f"\nFatto in {int(time.time()-inizio)}s. Dettagli scaricati: {tot_dett}.")
    print("Ora rilanciare: python backtest_arene.py")


if __name__ == '__main__':
    main()
