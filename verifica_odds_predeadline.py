"""verifica_odds_predeadline — le starter odds del game log sono leakage?

LA DOMANDA. `screening_segnali.py` trova le starter odds come segnale piu'
forte sul residuo dentro-giocatore (+0.163), ma le prende da
`anyPlayerGameStats.footballPlayingStatusOdds.starterOddsBasisPoints` DENTRO
il game log, che si scarica DOPO la partita: l'85,4% dei valori e' 0% o 100% e
coincide col titolare effettivo nel 98,8% dei casi. Se Sorare aggiorna quel
campo all'uscita delle formazioni ufficiali (che escono DOPO la deadline), il
segnale non e' utilizzabile al momento in cui si schiera.

IL CONFRONTO. Dal 31/07 `discovery_fixture.py` PERSISTE le odds prese prima
della deadline dentro `formazione_*/output/*_discovery/player_card_counts.json`
(chiave `starter_odds`). Quel file viene sovrascritto a ogni run, quindi la
data dello scarico e' la data di modifica del file. Qui si confronta, sulle
stesse righe, il valore pre-deadline con quello post-partita del game log.

LIMITE DEL CAMPIONE, da tenere presente leggendo i numeri: la discovery salva
solo i giocatori SOPRA la soglia MIN_ODDS (0.80 di default), quindi il lato
pre-deadline e' troncato in alto per costruzione. Serve a rispondere "il campo
cambia fra prima e dopo?", non a stimare la distribuzione vera delle odds.

Nessuna query API: solo file gia' su disco.

Uso:  python verifica_odds_predeadline.py
"""
import collections
import datetime
import glob
import json
import os
import re
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import backtest_arene_cache

CONTEGGI = os.path.join(ROOT, 'formazione_*', 'output', '*_discovery',
                        'player_card_counts.json')
# seconda fonte, molto piu' ricca: i report di previsione. Ogni blocco riporta
# "P(gioca): X% (fonte: starterOddsBasisPoints (NNNN))" e la data della
# prossima partita. Quelle odds arrivano da `anyFutureGames`, che il predittore
# NON cacha (test_def.py riga 648): sono il valore vivo al momento del run.
PREVISIONI = os.path.join(ROOT, 'formazione_*', 'output', '*', 'prediction_*.txt')
# oltre questa distanza fra scarico e calcio d'inizio non si puo' piu' dire
# che le odds si riferissero a QUELLA partita
GIORNI_MAX = 10


def scarichi():
    """[(slug, odds_pre, momento_scarico, file)] da tutti i discovery su disco."""
    fuori = []
    for path in glob.glob(CONTEGGI):
        try:
            with open(path, encoding='utf-8') as fh:
                dati = json.load(fh)
        except Exception:
            continue
        quando = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        for slug, voce in (dati or {}).items():
            if isinstance(voce, dict) and voce.get('starter_odds') is not None:
                fuori.append((slug, float(voce['starter_odds']), quando, path))
    return fuori


_BLOCCO = re.compile(r'# GIOCATORE: (\S+)')
_ODDS = re.compile(r'P\(gioca\): [\d.]+% \(fonte: starterOddsBasisPoints \((\d+)\)\)')
_GENERATO = re.compile(r'Generato: (\d{4}-\d{2}-\d{2}T[\d:.]+)')
_PROSSIMA = re.compile(r'--- PROSSIMA PARTITA ---\s*\nData: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2})')


def scarichi_da_previsioni():
    """[(slug, odds_pre, momento_run, kickoff)] dai report prediction_*.txt.

    Si tiene solo cio' che e' stato generato PRIMA del calcio d'inizio: un run
    fatto a partita iniziata leggerebbe un valore gia' aggiornato e non
    direbbe niente sul leakage."""
    fuori = []
    for path in glob.glob(PREVISIONI):
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                testo = fh.read()
        except Exception:
            continue
        pezzi = _BLOCCO.split(testo)
        # split lascia [testa, slug1, corpo1, slug2, corpo2, ...]
        for i in range(1, len(pezzi) - 1, 2):
            slug, corpo = pezzi[i], pezzi[i + 1]
            m_odds = _ODDS.search(corpo)
            m_gen = _GENERATO.search(corpo)
            m_next = _PROSSIMA.search(corpo)
            if not (m_odds and m_gen and m_next):
                continue
            try:
                gen = datetime.datetime.fromisoformat(m_gen.group(1))
                kick = datetime.datetime.fromisoformat(m_next.group(1))
            except ValueError:
                continue
            if gen >= kick:
                continue
            fuori.append((slug, int(m_odds.group(1)) / 10000.0, gen, kick))
    return fuori


def _data(nodo):
    iso = ((nodo.get('anyGame') or {}).get('date') or '')
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _odds_nodo(nodo):
    stat = nodo.get('anyPlayerGameStats') or {}
    bp = (stat.get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
    return (float(bp) / 10000.0 if bp is not None else None), stat.get('gameStarted')


def main():
    righe = scarichi()
    prev = scarichi_da_previsioni()
    if not righe and not prev:
        print('nessuna odds pre-deadline persistita su disco: niente da confrontare')
        return 1
    giorni = collections.Counter(q.date().isoformat() for _, _, q, _ in righe + prev)
    print('=' * 88)
    print('STARTER ODDS: PRE-DEADLINE (discovery + report) CONTRO POST-PARTITA (game log)')
    print('=' * 88)
    print(f'{len(righe)} righe da player_card_counts.json '
          f'({len(set(p for _, _, _, p in righe))} file di discovery)')
    print(f'{len(prev)} righe da prediction_*.txt, generate prima del calcio d inizio')
    print('giorni: ' + ', '.join(f'{g} ({n})' for g, n in sorted(giorni.items())))

    # la distribuzione del lato pre-deadline si guarda su TUTTE le righe, anche
    # quelle la cui partita non e' ancora stata giocata: e' il confronto che
    # pesa di piu' contro l'85,4% di valori estremi del game log
    tutte = [o for _, o, _, _ in righe + prev]
    est_tutte = sum(1 for o in tutte if o <= 0.001 or o >= 0.999) / len(tutte)
    dist = collections.Counter(round(o, 2) for o in tutte)
    print(f'\ndistribuzione delle {len(tutte)} odds PRE-DEADLINE '
          f'(estremi 0% o 100%: {est_tutte:.1%})')
    print('    ' + '  '.join(f'{v:.2f}:{q}' for v, q in sorted(dist.items())))

    cache = backtest_arene_cache.CacheLocale()
    confronti = {}          # (slug, id_partita) -> (pre, post, started, quando, kickoff)
    senza_partita = senza_post = 0
    for slug, pre, quando, _ in righe:
        nodi = [n for n in cache.gamelog(slug) if _data(n) is not None]
        # la partita a cui si riferiscono quelle odds e' la prima DOPO lo
        # scarico: la discovery gira prima della deadline, per la giornata
        # imminente
        futuri = [n for n in nodi if _data(n) >= quando]
        futuri.sort(key=_data)
        nodo = futuri[0] if futuri else None
        if nodo is None or (_data(nodo) - quando).days > GIORNI_MAX:
            senza_partita += 1
            continue
        post, started = _odds_nodo(nodo)
        if post is None:
            senza_post += 1
            continue
        chiave = (slug, (nodo.get('anyGame') or {}).get('id'))
        vecchio = confronti.get(chiave)
        # a parita' di partita tiene lo scarico PIU' VICINO al calcio d'inizio
        if vecchio is None or quando > vecchio[3]:
            confronti[chiave] = (pre, post, started, quando, _data(nodo))

    # i report sanno gia' a QUALE partita si riferiscono: si aggancia per data
    non_giocata = 0
    for slug, pre, gen, kick in prev:
        nodo = None
        for n in cache.gamelog(slug):
            d = _data(n)
            if d is not None and d.date() == kick.date():
                nodo = n
                break
        if nodo is None:
            non_giocata += 1
            continue
        post, started = _odds_nodo(nodo)
        if post is None:
            senza_post += 1
            continue
        chiave = (slug, (nodo.get('anyGame') or {}).get('id'))
        vecchio = confronti.get(chiave)
        if vecchio is None or gen > vecchio[3]:
            confronti[chiave] = (pre, post, started, gen, _data(nodo))

    print(f'\nrighe scartate: {senza_partita} senza partita entro {GIORNI_MAX} giorni '
          f'dallo scarico, {non_giocata} con la partita non ancora in cache, '
          f'{senza_post} senza odds nel game log')
    if not confronti:
        print('nessuna riga confrontabile')
        return 1

    v = list(confronti.values())
    n = len(v)
    uguali = sum(1 for pre, post, *_ in v if abs(pre - post) < 1e-9)
    entro5 = sum(1 for pre, post, *_ in v if abs(pre - post) <= 0.05)
    entro10 = sum(1 for pre, post, *_ in v if abs(pre - post) <= 0.10)
    saliti = sum(1 for pre, post, *_ in v if post > pre + 1e-9)
    scesi = sum(1 for pre, post, *_ in v if post < pre - 1e-9)
    est_pre = sum(1 for pre, _, *_ in v if pre <= 0.001 or pre >= 0.999) / n
    est_post = sum(1 for _, post, *_ in v if post <= 0.001 or post >= 0.999) / n

    print(f'\nCONFRONTO SU {n} COPPIE (giocatore, partita)')
    print(f'  identiche                      {uguali:>6}  {uguali / n:6.1%}')
    print(f'  entro 5 punti percentuali      {entro5:>6}  {entro5 / n:6.1%}')
    print(f'  entro 10 punti percentuali     {entro10:>6}  {entro10 / n:6.1%}')
    print(f'  post PIU ALTE della pre        {saliti:>6}  {saliti / n:6.1%}')
    print(f'  post PIU BASSE della pre       {scesi:>6}  {scesi / n:6.1%}')
    print(f'\n  valori estremi (0% o 100%)   pre-deadline {est_pre:6.1%}   '
          f'post-partita {est_post:6.1%}')

    print('\n  distribuzione (pre -> post), le 12 transizioni piu frequenti')
    tab = collections.Counter((round(pre, 2), round(post, 2)) for pre, post, *_ in v)
    for (a, b), q in tab.most_common(12):
        print(f'    {a:5.2f} -> {b:5.2f}   {q:>5}  {q / n:5.1%}')

    con_flag = [(pre, post, st) for pre, post, st, *_ in v if st is not None]
    if con_flag:
        c_post = sum(1 for _, post, st in con_flag if (post >= 0.5) == (st == 1)) / len(con_flag)
        c_pre = sum(1 for pre, _, st in con_flag if (pre >= 0.5) == (st == 1)) / len(con_flag)
        print(f'\n  coincidenza con la titolarita effettiva ({len(con_flag)} righe con il flag):')
        print(f'    post-partita {c_post:6.1%}   pre-deadline {c_pre:6.1%}')

    fuori = os.path.join('dati_globali', 'verifica_odds_predeadline.json')
    with open(os.path.join(ROOT, fuori), 'w', encoding='utf-8') as fh:
        json.dump({'n_righe_pre': len(righe), 'n_confronti': n,
                   'giorni_scarico': dict(giorni),
                   'estremi_pre_tutte': est_tutte,
                   'distribuzione_pre_tutte': {str(k): q for k, q in sorted(dist.items())},
                   'identiche': uguali / n, 'entro_5pp': entro5 / n,
                   'entro_10pp': entro10 / n, 'post_piu_alte': saliti / n,
                   'post_piu_basse': scesi / n,
                   'estremi_pre': est_pre, 'estremi_post': est_post,
                   'transizioni': [{'pre': a, 'post': b, 'n': q}
                                   for (a, b), q in tab.most_common()]},
                  fh, ensure_ascii=False, indent=1)
    print(f'\nsalvato in {fuori}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
