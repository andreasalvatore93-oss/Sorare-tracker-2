"""
Isolamento (29/07, verifica richiesta): stesso identico backtest di
validate_opponent_conceded_level_allroles.py (MID/DEF/GK) + FWD, ma con
i pattern di glob che ESCLUDONO esplicitamente formazione_mls e
formazione_kleague, per capire il guadagno MAE% sulle SOLE altre 26 leghe,
usando le sensibilita' e la normalizzazione GIA' IN PRODUZIONE
(opponent_strength.py, SENSITIVITY_BY_ROLE / GLOBAL_MEAN_CONCEDED /
GLOBAL_STD_CONCEDED), invece di rifare il grid-search.

Uso: python formazione_mls/diagnostics/validate_opponent_conceded_level_isolated_otherleagues.py
"""
import os
import sys
import json
import glob
import math
import statistics
import datetime
from collections import defaultdict

sys.path.insert(0, os.getcwd())

EXCLUDE_DIRS = {'formazione_mls', 'formazione_kleague'}

MIN_HISTORY = 6
N_GAMES = 10
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6
SHRINK_K = 5.0

ROLE_PRIOR = {'mid': 53.4, 'def': 51.2, 'gk': 47.1, 'fwd': 53.02}
ROLE_SIGN = {'mid': 1, 'def': 1, 'gk': -1, 'fwd': 1}
# Sensibilita' GIA' IN PRODUZIONE (opponent_strength.py, 29/07)
ROLE_SENS = {'gk': 0.7, 'def': 0.8, 'mid': 0.7, 'fwd': 1.0}
# Media/std FISSE gia' in produzione (stesse costanti di opponent_strength.py)
GLOBAL_MEAN_CONCEDED = 1.29
GLOBAL_STD_CONCEDED = 1.17


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def exp_weights(n, half_life):
    decay = math.log(2) / half_life
    return [math.exp(-decay * (n - 1 - i)) for i in range(n)]


def wmean(values, weights):
    tw = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / tw if tw else 0.0


def netto_to_level(netto):
    k = max(-2, min(5, round(netto)))
    return LEVEL_TABLE[k]


def poisson_pmf_truncated(lam, k_max):
    if lam <= 0:
        probs = [0.0] * (k_max + 1)
        probs[0] = 1.0
        return probs
    probs, cum = [], 0.0
    for k in range(k_max):
        p = math.exp(-lam) * (lam ** k) / math.factorial(k)
        probs.append(p)
        cum += p
    probs.append(max(0.0, 1.0 - cum))
    return probs


def expected_level_from_rates(lambda_pos, lambda_neg):
    probs_pos = poisson_pmf_truncated(lambda_pos, POISSON_K_MAX)
    probs_neg = poisson_pmf_truncated(lambda_neg, POISSON_K_MAX)
    expected = 0.0
    for i, pp in enumerate(probs_pos):
        if pp == 0.0:
            continue
        for j, pn in enumerate(probs_neg):
            if pn == 0.0:
                continue
            expected += pp * pn * netto_to_level(i - j)
    return expected


def player_team_slug(games):
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def other_league_dirs():
    dirs = []
    for d in glob.glob('formazione_*'):
        base = os.path.basename(d)
        if base in EXCLUDE_DIRS:
            continue
        dirs.append(base)
    return dirs


def build_team_conceded_and_scored_series(league_dirs):
    seen = set()
    conceded = defaultdict(list)
    scored = defaultdict(list)
    patterns = []
    for ld in league_dirs:
        for role in ('gk', 'def', 'mid'):
            patterns.append(f'{ld}/output/*_{role}_all/.cache')
            patterns.append(f'{ld}/output/*_{role}_calibration/.cache')
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                try:
                    with open(fpath, encoding='utf-8') as f:
                        cache = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                if not cache:
                    continue
                entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
                if not entries:
                    continue
                games = [e['anyGame'] for e in entries]
                team_slug = player_team_slug(games)
                if not team_slug:
                    continue
                for e in entries:
                    g = e['anyGame']
                    home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                    if home.get('slug') == team_slug:
                        opp_slug = away.get('slug')
                    elif away.get('slug') == team_slug:
                        opp_slug = home.get('slug')
                    else:
                        continue
                    dt = parse_date(g)
                    if dt is None or not opp_slug:
                        continue
                    key = (team_slug, opp_slug, dt.isoformat())
                    if key in seen:
                        continue
                    seen.add(key)
                    gc = None
                    for row in e['detailedScore']:
                        if row.get('stat') == 'goals_conceded':
                            gc = row.get('statValue', 0.0) or 0.0
                            break
                    if gc is None:
                        continue
                    conceded[team_slug].append((dt, gc))
                    scored[opp_slug].append((dt, gc))
    for d in (conceded, scored):
        for t in d:
            d[t].sort(key=lambda x: x[0])
    return conceded, scored


def load_role_players(role, league_dirs):
    players = []
    seen_files = set()
    for ld in league_dirs:
        patterns = [f'{ld}/output/*_{role}_all/.cache', f'{ld}/output/*_{role}_calibration/.cache']
        for pattern in patterns:
            for cache_dir in glob.glob(pattern):
                for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                    if fpath in seen_files:
                        continue
                    seen_files.add(fpath)
                    try:
                        with open(fpath, encoding='utf-8') as f:
                            cache = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        continue
                    entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
                    if len(entries) < MIN_HISTORY + 3:
                        continue
                    games = [e['anyGame'] for e in entries]
                    team_slug = player_team_slug(games)
                    if not team_slug:
                        continue
                    rows = []
                    for e in entries:
                        g = e['anyGame']
                        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                        if home.get('slug') == team_slug:
                            is_home, opp_slug = True, away.get('slug')
                        elif away.get('slug') == team_slug:
                            is_home, opp_slug = False, home.get('slug')
                        else:
                            continue
                        dt = parse_date(g)
                        if dt is None:
                            continue
                        pos_sum = neg_sum = 0.0
                        for row in e['detailedScore']:
                            cat = row.get('category')
                            val = row.get('statValue') or 0.0
                            if cat == 'POSITIVE_DECISIVE_STAT':
                                pos_sum += val
                            elif cat == 'NEGATIVE_DECISIVE_STAT':
                                neg_sum += val
                        level_v = 0.0
                        for row in e['detailedScore']:
                            if row.get('stat') == 'level_score':
                                level_v = row.get('totalScore', 0.0) or 0.0
                                break
                        score = e.get('score') or 0.0
                        rows.append({'date': dt, 'is_home': is_home, 'opp_slug': opp_slug,
                                     'pos_dec': pos_sum, 'neg_dec': neg_sum,
                                     'granulare': score - level_v, 'score': score})
                    rows.sort(key=lambda r: r['date'])
                    if len(rows) < MIN_HISTORY + 3:
                        continue
                    players.append(rows)
    return players


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def run_role(role, conceded_series, scored_series, league_dirs):
    prior = ROLE_PRIOR[role]
    sign = ROLE_SIGN[role]
    sens = ROLE_SENS[role]
    signal_series = scored_series if sign < 0 else conceded_series
    label = "gol FATTI dall'avversario (segno invertito)" if sign < 0 else "gol SUBITI dall'avversario"

    print(f"\n{'='*78}\n{role.upper()} -- segnale: {label} -- sens PRODUZIONE={sens}\n{'='*78}")
    players = load_role_players(role, league_dirs)
    print(f"Giocatori {role.upper()} utilizzabili (leghe isolate): {len(players)}")
    if not players:
        return

    n_test_points = 0
    n_signal_available = 0
    base_pairs = []
    adj_pairs = []

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, 12.0)
            lambda_pos = wmean([r['pos_dec'] for r in hist], weights)
            lambda_neg = wmean([r['neg_dec'] for r in hist], weights)
            granulare_hist = wmean([r['granulare'] for r in hist], weights)
            level_base = expected_level_from_rates(lambda_pos, lambda_neg)
            grezzo_base = level_base + granulare_hist
            corretto_base = (i / (i + SHRINK_K)) * grezzo_base + (SHRINK_K / (i + SHRINK_K)) * prior
            home_vals = [r['score'] for r in hist if r['is_home'] is True]
            away_vals = [r['score'] for r in hist if r['is_home'] is False]
            overall = sum(r['score'] for r in hist) / len(hist)
            target_is_home = rows[i]['is_home']
            ctx_vals = home_vals if target_is_home else away_vals
            venue_factor = 1.0
            if ctx_vals and overall:
                venue_factor = max(0.85, min(1.15, (sum(ctx_vals) / len(ctx_vals)) / overall))
            pred_base = corretto_base * venue_factor
            reale = scores[i]
            n_test_points += 1

            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = signal_series.get(opp_slug, [])
            avg_val = avg_before(series_opp, cutoff, N_GAMES)
            if avg_val is None:
                continue
            n_signal_available += 1
            z = (avg_val - GLOBAL_MEAN_CONCEDED) / GLOBAL_STD_CONCEDED
            z_signed = sign * z
            lambda_pos_adj = max(0.0, lambda_pos * (1 + sens * z_signed))
            level_adj = expected_level_from_rates(lambda_pos_adj, lambda_neg)
            grezzo_adj = level_adj + granulare_hist
            corretto_adj = (i / (i + SHRINK_K)) * grezzo_adj + (SHRINK_K / (i + SHRINK_K)) * prior
            pred_adj = corretto_adj * venue_factor

            base_pairs.append((reale, pred_base))
            adj_pairs.append((reale, pred_adj))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    print(f"Punti di test totali: {n_test_points} | con dato disponibile: "
          f"{n_signal_available} ({n_signal_available/n_test_points*100:.0f}%)" if n_test_points else "n=0")
    if not base_pairs:
        print("Nessun punto con dato avversario disponibile.")
        return
    mae_base = mae(base_pairs)
    mae_adj = mae(adj_pairs)
    pct = (mae_adj - mae_base) / mae_base * 100
    print(f"n={len(base_pairs)}  MAE base={mae_base:.4f}  MAE adj(sens={sens})={mae_adj:.4f}  ({pct:+.3f}%)")


def main():
    league_dirs = other_league_dirs()
    print(f"Leghe isolate (esclude MLS/K League): {len(league_dirs)}")
    print(", ".join(sorted(league_dirs)))
    print("Ricostruzione serie storiche gol subiti/fatti per squadra (isolato)...")
    conceded, scored = build_team_conceded_and_scored_series(league_dirs)
    print(f"Squadre ricostruite: {len(conceded)}")
    for role in ('fwd', 'mid', 'def', 'gk'):
        run_role(role, conceded, scored, league_dirs)


if __name__ == '__main__':
    main()
