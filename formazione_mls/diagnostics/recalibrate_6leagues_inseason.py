"""
Recalibrate 6 Leagues In Season (27/07 notte, richiesta esplicita utente)

Domanda: ora che abbiamo dati (cache gia' su disco, nessuna nuova query) per
6 campionati invece di 2 (MLS+K League storici + Portogallo/Austria/Scozia/
Croazia aggiunti stasera), i parametri UFFICIALI di produzione
(half_life/range_multiplier/opponent_sensitivity/trend_intensity/granulari)
per ogni ruolo sono ancora quelli che minimizzano il MAE? Stessa metodologia
usata per calibrare il modello attuale (grid search cross-player pesato per
n_test, MIN_TEST_GAMES=3, stesso approccio di aggregate_grid_search.py), ma
in locale (nessun workflow GitHub, nessuna nuova query) su TUTTE le cache
gia' presenti (calibration per MLS/K League, produzione "_all" per i 4
nuovi -- stessi identici dati, solo generati da un run normale invece che
da CALIBRATION_MODE). Focus dichiarato dall'utente: competizioni IN SEASON
(stima del punteggio del singolo giocatore in valore atteso puro, non le
sinergie/varianza di Arena gia' indagate stasera).

A differenza degli altri diagnostici di stasera (che usavano i parametri
GIA' ufficiali per confrontare gruppi), qui si esegue il vero
`run_grid_search` di ciascun `test_<ruolo>.py` (72 combinazioni) per ogni
giocatore cachato, usando gli STESSI opponent_rankings reali
(domesticLeagueRanking dell'avversario, letto dalla cache -- non None come
negli altri diagnostici di stasera, che avevano gia' escluso l'opponent
factor a monte) cosi' da poter valutare anche quel parametro come nella
calibrazione originale.

Uso: python formazione_mls/diagnostics/recalibrate_6leagues_inseason.py
"""
import os
import sys
import glob
import json
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
MIN_TEST_GAMES = 3

ROLE_MODULES = {
    'gk': 'test_gk', 'def': 'test_def', 'mid': 'test_mid', 'fwd': 'test_mls_fwd_all',
}

LEAGUES = {
    'mls': ('formazione_mls.predict.{mod}', 'formazione_mls/output/mls_{ruolo}_calibration/.cache'),
    'kleague': ('formazione_kleague.predict.{mod}', 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache'),
    'portogallo': ('formazione_portogallo.predict.{mod}', 'formazione_portogallo/output/portogallo_{ruolo}_all/.cache'),
    'austria': ('formazione_austria.predict.{mod}', 'formazione_austria/output/austria_{ruolo}_all/.cache'),
    'scozia': ('formazione_scozia.predict.{mod}', 'formazione_scozia/output/scozia_{ruolo}_all/.cache'),
    'croazia': ('formazione_croazia.predict.{mod}', 'formazione_croazia/output/croazia_{ruolo}_all/.cache'),
}

# Parametri UFFICIALI attuali di produzione (per confronto diretto).
CURRENT_PROD = {
    'gk': dict(half_life=9.0, range_multiplier=1.6, opponent_sensitivity=29.0, trend_intensity=0.7, granular=False),
    'def': dict(half_life=12.0, range_multiplier=1.2, opponent_sensitivity=29.0, trend_intensity=0.7, granular=False),
    'mid': dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, trend_intensity=0.7, granular=False),
    'fwd': dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, trend_intensity=0.7, granular=False),
}


def player_team_and_flags_ranks(entries):
    team_counts = defaultdict(int)
    for e in entries:
        g = e['anyGame']
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    if not team_counts:
        return None, None, None
    team_slug = max(team_counts, key=team_counts.get)
    flags, ranks = [], []
    for e in entries:
        g = e['anyGame']
        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
        if home.get('slug') == team_slug:
            flags.append(True)
            ranks.append(away.get('domesticLeagueRanking'))
        elif away.get('slug') == team_slug:
            flags.append(False)
            ranks.append(home.get('domesticLeagueRanking'))
        else:
            flags.append(None)
            ranks.append(None)
    return team_slug, flags, ranks


def collect_role(ruolo):
    """Per ogni giocatore cachato (tutte le leghe), esegue run_grid_search e
    ritorna lista di (n_test, best_row_dict) per ogni combinazione testata
    -- serve tutta la classifica per giocatore, non solo il vincitore, per
    poter aggregare per combinazione attraverso i giocatori (stesso
    approccio di aggregate_grid_search.py)."""
    per_player_results = []  # list of (n_test, {label: bt_dict})

    for league, (mod_tpl, cache_tpl) in LEAGUES.items():
        mod_name = mod_tpl.format(mod=ROLE_MODULES[ruolo])
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        run_grid_search = mod.run_grid_search
        cache_dir = cache_tpl.format(ruolo=ruolo)
        files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))

        for fpath in files:
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
            if not cache:
                continue
            entries = [e for e in cache.values() if e.get('anyGame') and e.get('scoreStatus') == 'FINAL']
            if len(entries) < MIN_HISTORY + MIN_TEST_GAMES:
                continue
            entries.sort(key=lambda e: e['anyGame'].get('date') or '')
            scores = [e.get('score') or 0.0 for e in entries]
            team_slug, flags, ranks = player_team_and_flags_ranks(entries)
            if team_slug is None or any(f is None for f in flags):
                continue

            results = run_grid_search(scores, flags, ranks, min_history=MIN_HISTORY)
            by_label = {r['label']: r for r in results if r.get('mae') is not None}
            if not by_label:
                continue
            any_row = next(iter(by_label.values()))
            n_test = len(any_row['rows'])
            if n_test < MIN_TEST_GAMES:
                continue
            per_player_results.append((n_test, by_label))

    return per_player_results


def aggregate(per_player_results):
    """Media pesata per n_test di MAE/copertura per ogni combinazione
    (label), attraverso i giocatori che l'hanno testata -- stesso principio
    di aggregate_grid_search.py."""
    sums = defaultdict(lambda: [0.0, 0.0, 0])  # label -> [mae*n_sum, cov*n_sum, n_sum]
    example = {}
    for n_test, by_label in per_player_results:
        for label, bt in by_label.items():
            s = sums[label]
            s[0] += bt['mae'] * n_test
            s[1] += (bt['pct_dentro_range'] or 0.0) * n_test
            s[2] += n_test
            example[label] = bt

    agg = []
    for label, (mae_sum, cov_sum, n_sum) in sums.items():
        if n_sum <= 0:
            continue
        mae = mae_sum / n_sum
        cov = cov_sum / n_sum
        bt = example[label]
        agg.append(dict(label=label, mae=mae, coverage=cov, n_weighted=n_sum,
                         half_life=bt['half_life'], range_multiplier=bt['range_multiplier'],
                         opponent_sensitivity=bt['opponent_sensitivity'], trend_intensity=bt['trend_intensity'],
                         granular='con granulari' in label.lower() or 'granular' in label.lower()))
    agg.sort(key=lambda a: a['mae'])
    return agg


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        print(f"\n{'='*70}\n{ruolo.upper()}\n{'='*70}")
        per_player = collect_role(ruolo)
        n_players = len(per_player)
        print(f"Giocatori con grid search e >= {MIN_TEST_GAMES} partite test: {n_players}")
        if n_players < 5:
            print("Campione troppo piccolo, salto l'aggregazione.")
            continue
        agg = aggregate(per_player)
        winner = agg[0]
        prod = CURRENT_PROD[ruolo]
        print(f"Vincitore aggregato: {winner['label']} -- MAE={winner['mae']:.2f} "
              f"copertura={winner['coverage']:.1f}% (n pesato={winner['n_weighted']:.0f})")
        print(f"  half_life={winner['half_life']} range={winner['range_multiplier']} "
              f"opp_sens={winner['opponent_sensitivity']} trend={winner['trend_intensity']}")
        print(f"Produzione attuale: half_life={prod['half_life']} range={prod['range_multiplier']} "
              f"opp_sens={prod['opponent_sensitivity']} trend={prod['trend_intensity']} "
              f"granulari={'SI' if prod['granular'] else 'NO'}")
        # MAE della combinazione ufficiale attuale, per confronto diretto
        matches = [a for a in agg if abs(a['half_life'] - prod['half_life']) < 0.01
                   and abs(a['range_multiplier'] - prod['range_multiplier']) < 0.01
                   and abs(a['opponent_sensitivity'] - prod['opponent_sensitivity']) < 0.01
                   and abs(a['trend_intensity'] - prod['trend_intensity']) < 0.01]
        if matches:
            cur = matches[0]
            delta_pct = (cur['mae'] - winner['mae']) / winner['mae'] * 100 if winner['mae'] else 0
            print(f"  MAE produzione attuale: {cur['mae']:.2f} (+{delta_pct:.1f}% peggio del vincitore)"
                  if cur['mae'] > winner['mae'] else f"  MAE produzione attuale: {cur['mae']:.2f} (= vincitore)")
        else:
            print("  (combinazione produzione attuale non trovata esattamente nella griglia -- normale se "
                  "differisce anche di poco da un valore testato)")
        print("\nTop 5 combinazioni:")
        for a in agg[:5]:
            print(f"  {a['label']:<70} MAE={a['mae']:.2f} cov={a['coverage']:.1f}% n={a['n_weighted']:.0f}")


if __name__ == '__main__':
    main()
