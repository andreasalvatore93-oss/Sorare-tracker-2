"""
Validate Level Score Decomposition (26/07, quinta sessione)

Domanda: prevedere lo score totale scomponendolo in due serie previste
SEPARATAMENTE (ciascuna con il proprio half_life/trend_intensity) batte la
media pesata unica sul totale che usiamo oggi in produzione?

- level_score_atteso: media esp. pesata sulla serie storica di 'level_score'
  (riga a se' nel detailedScore, category=UNKNOWN, gia' presente per-partita
  nelle cache -- nessuna nuova query, nessuna ricostruzione dalla formula
  del conteggio netto).
- granulare_atteso: stessa cosa su (score_totale - level_score) per partita.
- predetto = level_score_atteso + granulare_atteso.

Motivazione: level_score ha una base fissa (35) piu' eventi discreti
(clean sheet, gol, ecc: vedi inspect_granular_weights.py) -- puo' avere
persistenza diversa dal granulare, che e' un accumulo di tante stat piccole
e continue. Se la formula attuale (unico half_life per il totale) media
insieme due dinamiche diverse, scomporle con parametri propri puo' abbassare
il MAE.

Metodologia: walk-forward, stesso schema di validate_halflife_venue.py
(MIN_HISTORY=6, exponential_weights/weighted_mean importati dai moduli
test_<ruolo>.py reali). fattore_casa_trasferta e fattore_trend applicati
identici a oggi (venue sul totale gia' confermato valido, non lo tocchiamo
qui) per isolare l'effetto della sola decomposizione level/granulare.

Uso: python formazione_mls/diagnostics/validate_level_score_decomposition.py
"""
import os
import sys
import json
import glob
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
HALF_LIFE_GRID = [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 14.0, 16.0, 20.0, 25.0, 30.0]
TREND_GRID = [0.0, 0.3, 0.5, 0.7, 0.9, 1.1, 1.5]

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def extract_level_score(detailed_score):
    for row in detailed_score or []:
        if row.get('stat') == 'level_score':
            return row.get('totalScore') or 0.0
    return 0.0


def load_players(ruolo):
    cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    players = []
    for fpath in files:
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if len(entries) < MIN_HISTORY + 3:
            continue
        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue
        scores, level_scores, is_home_flags = [], [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            total = e.get('score') or 0.0
            lvl = extract_level_score(e.get('detailedScore'))
            scores.append(total)
            level_scores.append(lvl)
            is_home_flags.append(is_home)
        if len(scores) < MIN_HISTORY + 3:
            continue
        players.append({'scores': scores, 'level_scores': level_scores, 'is_home_flags': is_home_flags})
    return players


def mae_baseline(players, exponential_weights, weighted_mean, compute_split_factor,
                  compute_trend_factor, half_life, trend_intensity):
    """Approccio attuale in produzione: media pesata sul totale."""
    errori = []
    for p in players:
        scores, is_home_flags = p['scores'], p['is_home_flags']
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            weights = exponential_weights(i, half_life)
            media = weighted_mean(hist_scores, weights)
            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=trend_intensity)
            pred = media * fattore_ct * fattore_trend
            errori.append(scores[i] - pred)
    return statistics.mean(abs(e) for e in errori), len(errori)


def mae_decomposed(players, exponential_weights, weighted_mean, compute_split_factor,
                    compute_trend_factor, hl_level, ti_level, hl_gran, ti_gran):
    """level_score_atteso + granulare_atteso, ciascuno con parametri propri.
    fattore_casa_trasferta applicato una sola volta al totale predetto (non
    duplicato sui due pezzi), stesso schema/venue gia' in produzione."""
    errori = []
    for p in players:
        scores, level_scores, is_home_flags = p['scores'], p['level_scores'], p['is_home_flags']
        gran_scores = [s - l for s, l in zip(scores, level_scores)]
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            hist_level = level_scores[:i]
            hist_gran = gran_scores[:i]

            w_level = exponential_weights(i, hl_level)
            level_atteso = weighted_mean(hist_level, w_level)
            trend_level, _, _ = compute_trend_factor(
                hist_level, short_window=5, long_window=10, trend_intensity=ti_level)

            w_gran = exponential_weights(i, hl_gran)
            gran_atteso = weighted_mean(hist_gran, w_gran)
            trend_gran, _, _ = compute_trend_factor(
                hist_gran, short_window=5, long_window=10, trend_intensity=ti_gran)

            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            pred = (level_atteso * trend_level + gran_atteso * trend_gran) * fattore_ct
            errori.append(scores[i] - pred)
    return statistics.mean(abs(e) for e in errori), len(errori)


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HL_ATTUALE = mod.HALF_LIFE_GAMES
    TI_ATTUALE = mod.TREND_INTENSITY

    players = load_players(ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return
    n_test = sum(len(p['scores']) - MIN_HISTORY for p in players)
    print(f"\n{'='*78}\n{ruolo.upper()} ({len(players)} giocatori, {n_test} punti test) "
          f"-- attuale: half_life={HL_ATTUALE}, trend_intensity={TI_ATTUALE}\n{'='*78}")

    mae_base, n = mae_baseline(players, exponential_weights, weighted_mean, compute_split_factor,
                                compute_trend_factor, HL_ATTUALE, TI_ATTUALE)
    print(f"  Baseline (media pesata sul totale, attuale): MAE={mae_base:.3f} ({n} punti test)")

    # Grid search: parametri level_score e granulare indipendenti, entrambi
    # sulla stessa griglia, per trovare la combo migliore per ruolo.
    best_combo, best_mae = None, None
    for hl_l in HALF_LIFE_GRID:
        for ti_l in TREND_GRID:
            for hl_g in HALF_LIFE_GRID:
                for ti_g in TREND_GRID:
                    m, _ = mae_decomposed(players, exponential_weights, weighted_mean,
                                           compute_split_factor, compute_trend_factor,
                                           hl_l, ti_l, hl_g, ti_g)
                    if best_mae is None or m < best_mae:
                        best_combo, best_mae = (hl_l, ti_l, hl_g, ti_g), m

    pct = (best_mae - mae_base) / mae_base * 100
    print(f"  MIGLIOR decomposto: half_life_level={best_combo[0]}, trend_level={best_combo[1]}, "
          f"half_life_gran={best_combo[2]}, trend_gran={best_combo[3]}")
    print(f"    MAE={best_mae:.3f}  ({pct:+.2f}% vs baseline)")

    # Anche: decomposto ma con stessi parametri attuali su entrambi i pezzi
    # (isola l'effetto puro della separazione additiva, senza ri-tarare nulla).
    mae_same, _ = mae_decomposed(players, exponential_weights, weighted_mean, compute_split_factor,
                                  compute_trend_factor, HL_ATTUALE, TI_ATTUALE, HL_ATTUALE, TI_ATTUALE)
    pct_same = (mae_same - mae_base) / mae_base * 100
    print(f"  Decomposto con parametri ATTUALI invariati su entrambi i pezzi: "
          f"MAE={mae_same:.3f} ({pct_same:+.2f}% vs baseline)")


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        run_role(ruolo)


if __name__ == '__main__':
    main()
