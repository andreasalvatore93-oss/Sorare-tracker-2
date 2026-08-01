"""Le starterOdds dicono la verita'? Calibrazione reale per lega.

Confronta le odds storicizzate da discovery_fixture (dati_globali/storico_odds/)
con quello che e' poi successo davvero, letto dai detail cache: un giocatore ha
"giocato da titolare" se risulta con almeno MIN_MINUTI minuti in quella
giornata.

Serve perche' oggi un 70% viene trattato uguale ovunque, ma il fornitore delle
odds e' terzo e puo' essere tarato male dove il mercato e' piccolo (K League).
Se sulla K League il 70% vale in realta' l'88%, la soglia si puo' abbassare
senza correre piu' rischi.

Uso:  python misura_calibrazione_odds.py
"""
import collections
import glob
import json
import os

MIN_MINUTI = float(os.environ.get('MIN_MINUTI', '60'))
FASCE = [(0.0, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]


def minuti_per_giocatore():
    """(slug, data) -> minuti giocati, dai detail cache."""
    out = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict):
                continue
            g = v.get('anyGame') or {}
            data = (g.get('date') or '')[:10]
            if not data:
                continue
            mins = 0.0
            for riga in (v.get('detailedScore') or []):
                if riga.get('stat') == 'mins_played':
                    mins = riga.get('statValue') or 0.0
            out[(slug, data)] = mins
    return out


def main():
    file_odds = sorted(glob.glob('dati_globali/storico_odds/*.json'))
    if not file_odds:
        print('Nessuna odds storicizzata ancora: serve almeno una run di '
              'discovery_fixture dopo il 01/08.')
        return
    minuti = minuti_per_giocatore()

    per_lega = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for f in file_odds:
        try:
            dati = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for lega, ruoli in (dati or {}).items():
            for _ruolo, righe in (ruoli or {}).items():
                for slug, odds in (righe or {}).items():
                    esiti = [m for (s, _d), m in minuti.items() if s == slug]
                    if not esiti:
                        continue
                    titolare = max(esiti) >= MIN_MINUTI
                    for lo, hi in FASCE:
                        if lo <= odds < hi:
                            per_lega[lega][(lo, hi)][0] += 1
                            per_lega[lega][(lo, hi)][1] += 1 if titolare else 0
                            break

    if not per_lega:
        print('Odds storicizzate presenti ma nessun esito ancora osservabile.')
        return
    for lega in sorted(per_lega):
        print(f'\n=== {lega}')
        for (lo, hi), (n, ok) in sorted(per_lega[lega].items()):
            if n < 5:
                continue
            print(f'  odds {lo:.0%}-{hi:.0%}: dichiarato ~{(lo+hi)/2:.0%}, '
                  f'reale {ok/n:.0%}  (n={n})')


if __name__ == '__main__':
    main()
