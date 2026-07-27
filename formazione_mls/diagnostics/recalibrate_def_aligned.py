"""Ricalibrazione DEF con il backtest ALLINEATO alla produzione (27/07, punto
26.D.3 handoff).

Gira run_grid_search_prod_def (che internamente usa compute_score_atteso_def,
la STESSA funzione della predizione reale) su tutti i difensori gia' presenti
nelle detail_cache dei 20 campionati -- nessuna chiamata di rete -- e aggrega
esattamente come formazione_mls/calibrazione/aggregate_grid_search.py: media
PESATA per n_test, composite = MAE + 0.1 * |copertura - 68|.

I MAE che escono da qui sono i primi che misurano DAVVERO il modello che
schiera le formazioni (il vecchio grid ottimizzava una formula moltiplicativa
divergente, vedi sezione 26.B del RIASSUNTO).
"""
import glob
import os
import sys
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'formazione_mls', 'predict'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('SORARE_COOKIE', 'x')

import test_def as T
from nonregression_score_atteso_def import arrays_from_cache

MIN_TEST_GAMES = int(os.environ.get('MIN_TEST_GAMES', '3'))
COVERAGE_WEIGHT = 0.1
MIN_HISTORY = 6


def main():
    pattern = os.path.join(REPO, 'formazione_*', 'output', '*_def_all', '.cache',
                           '*_detail_cache.json')
    files = sorted(glob.glob(pattern))
    per_label = defaultdict(list)
    per_campionato = defaultdict(int)
    n_players = n_excluded = 0

    for f in files:
        d = arrays_from_cache(f)
        if not d:
            continue
        n_test = len(d['scores']) - MIN_HISTORY
        if n_test < MIN_TEST_GAMES:
            n_excluded += 1
            continue
        grid = T.run_grid_search_prod_def(
            d['scores'], d['is_home'], d['opp_rank'], d['resid'], d['gran'],
            d['pos'], d['neg'], d['gc'], d['pas'], d['cs'], min_history=MIN_HISTORY)
        champ = f.replace('\\', '/').split('/formazione_')[1].split('/')[0]
        per_campionato[champ] += 1
        n_players += 1
        for r in grid:
            if r['mae'] is None:
                continue
            per_label[r['label']].append(r)

    if not per_label:
        print('Nessun dato utilizzabile.')
        return

    rows = []
    for label, entries in per_label.items():
        w = sum(e['n_test'] for e in entries)
        avg_mae = sum(e['mae'] * e['n_test'] for e in entries) / w
        cov = [e for e in entries if e['pct_dentro_range'] is not None]
        if cov:
            cw = sum(e['n_test'] for e in cov)
            avg_cov = sum(e['pct_dentro_range'] * e['n_test'] for e in cov) / cw
        else:
            avg_cov = None
        composite = avg_mae + abs((avg_cov or 0) - 68.0) * COVERAGE_WEIGHT
        rows.append((composite, avg_mae, avg_cov, len(entries), label))
    rows.sort()

    print(f"Difensori usati: {n_players} (esclusi per n_test<{MIN_TEST_GAMES}: {n_excluded})")
    print(f"Campionati: {len(per_campionato)} -> " +
          ', '.join(f'{k}:{v}' for k, v in sorted(per_campionato.items())))
    print(f"\nProduzione attuale: half_life={T.HALF_LIFE_GAMES} "
          f"trend_intensity={T.TREND_INTENSITY} range_mult={T.RANGE_MULTIPLIER}\n")
    print(f"{'#':>3} {'composite':>10} {'MAE':>7} {'cover%':>7}  label")
    for i, (comp, mae, cov, npl, label) in enumerate(rows, 1):
        print(f"{i:>3} {comp:>10.3f} {mae:>7.3f} "
              f"{(cov if cov is not None else float('nan')):>7.1f}  {label}")


if __name__ == '__main__':
    main()
