"""
Isolamento (29/07, verifica richiesta): stesso backtest di
validate_cross_role_combos.py per i due combo GIA' IN PRODUZIONE
(opponent_strength.py):
  - fwd_offense_granular_delta  (FWD.offensivo vs DEF.poss_lost_ctrl avversario, sens=3.0)
  - gk_def_pen_area_multiplier  (GK.goalkeeping vs DEF.pen_area_entries avversario, sens=0.5)
ma con i pattern di glob che ESCLUDONO esplicitamente formazione_mls e
formazione_kleague, per capire il guadagno MAE% sulle SOLE altre 26 leghe.
Sensibilita' FISSE a quella gia' in produzione (non re-grid-search).

Uso: python formazione_mls/diagnostics/validate_cross_role_combos_isolated_otherleagues.py
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
SHRINK_K = 5.0
MEDIA_RUOLO_PRIOR = {'gk': 48.81, 'def': 51.2, 'mid': 53.4, 'fwd': 53.02}
HALF_LIFE = {'gk': 6.0, 'def': 9.0, 'mid': 12.0, 'fwd': 12.0}
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6
N_GAMES = 10


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
    return [os.path.basename(d) for d in glob.glob('formazione_*') if os.path.basename(d) not in EXCLUDE_DIRS]


def build_opponent_series(league_dirs, opp_roles, stat_names):
    per_team_date = defaultdict(list)
    patterns = []
    for ld in league_dirs:
        for r in opp_roles:
            patterns.append(f'{ld}/output/*_{r}_all/.cache')
            patterns.append(f'{ld}/output/*_{r}_calibration/.cache')
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
                team_slug = player_team_slug([e['anyGame'] for e in entries])
                if not team_slug:
                    continue
                for e in entries:
                    g = e['anyGame']
                    home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                    if not (home.get('slug') == team_slug or away.get('slug') == team_slug):
                        continue
                    dt = parse_date(g)
                    if dt is None:
                        continue
                    val = 0.0
                    for row in e['detailedScore']:
                        if row.get('stat') in stat_names:
                            val += row.get('statValue', 0.0) or 0.0
                    per_team_date[(team_slug, dt)].append(val)

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        series[team].append((dt, sum(vals) / len(vals)))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    return series


def load_own_players(league_dirs, own_role, own_stat_names, own_is_statvalue):
    players = []
    seen_files = set()
    for ld in league_dirs:
        patterns = [f'{ld}/output/*_{own_role}_all/.cache', f'{ld}/output/*_{own_role}_calibration/.cache']
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
                        pos_sum = neg_sum = own_v = 0.0
                        for row in e['detailedScore']:
                            cat = row.get('category')
                            val = row.get('statValue') or 0.0
                            if cat == 'POSITIVE_DECISIVE_STAT':
                                pos_sum += val
                            elif cat == 'NEGATIVE_DECISIVE_STAT':
                                neg_sum += val
                            if row.get('stat') in own_stat_names:
                                own_v += (row.get('statValue', 0.0) or 0.0) if own_is_statvalue else (row.get('totalScore', 0.0) or 0.0)
                        level_v = 0.0
                        for row in e['detailedScore']:
                            if row.get('stat') == 'level_score':
                                level_v = row.get('totalScore', 0.0) or 0.0
                                break
                        score = e.get('score') or 0.0
                        rows.append({'date': dt, 'is_home': is_home, 'opp_slug': opp_slug,
                                     'pos_dec': pos_sum, 'neg_dec': neg_sum,
                                     'granulare': score - level_v, 'own_v': own_v, 'score': score})
                    rows.sort(key=lambda r: r['date'])
                    if len(rows) < MIN_HISTORY + 3:
                        continue
                    players.append(rows)
    return players


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [v for dt, v in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def run_combo(label, league_dirs, own_role, own_stat_names, opp_roles, opp_stat_names,
              sens_production, own_is_statvalue=False, invert_sign=False):
    print(f"\n{'='*74}\n{label} -- sens PRODUZIONE={sens_production}\n{'='*74}")
    opp_series = build_opponent_series(league_dirs, opp_roles, opp_stat_names)
    all_vals = [v for s in opp_series.values() for _, v in s]
    if not all_vals:
        print("NESSUN DATO per lo stat avversario")
        return
    gm, gs = statistics.mean(all_vals), statistics.pstdev(all_vals)
    print(f"(mean/std ISOLATI ricalcolati su queste leghe: {gm:.4f}/{gs:.4f})")
    if gs == 0:
        print("Deviazione standard zero, salto")
        return

    players = load_own_players(league_dirs, own_role, own_stat_names, own_is_statvalue)
    print(f"Giocatori {own_role} utilizzabili (leghe isolate): {len(players)}")
    if not players:
        print(f"Nessun giocatore {own_role} utilizzabile")
        return

    half_life = HALF_LIFE[own_role]
    prior = MEDIA_RUOLO_PRIOR[own_role]
    sign = -1 if invert_sign else 1
    base_pairs = []
    adj_pairs = []

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, half_life)
            lambda_pos = wmean([r['pos_dec'] for r in hist], weights)
            lambda_neg = wmean([r['neg_dec'] for r in hist], weights)
            granulare_hist = wmean([r['granulare'] for r in hist], weights)
            own_hist = wmean([r['own_v'] for r in hist], weights)
            home_vals = [r['score'] for r in hist if r['is_home'] is True]
            away_vals = [r['score'] for r in hist if r['is_home'] is False]
            overall = sum(r['score'] for r in hist) / len(hist)
            target_is_home = rows[i]['is_home']
            ctx_vals = home_vals if target_is_home else away_vals
            venue_factor = 1.0
            if ctx_vals and overall:
                venue_factor = max(0.85, min(1.15, (sum(ctx_vals) / len(ctx_vals)) / overall))

            def pred_from(gran_delta=0.0):
                level = expected_level_from_rates(lambda_pos, lambda_neg)
                grezzo = level + granulare_hist + gran_delta
                corretto = (i / (i + SHRINK_K)) * grezzo + (SHRINK_K / (i + SHRINK_K)) * prior
                return corretto * venue_factor

            reale = scores[i]
            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = opp_series.get(opp_slug, [])
            avg_val = avg_before(series_opp, cutoff, N_GAMES)
            if avg_val is None:
                continue
            z = sign * (avg_val - gm) / gs
            delta = sens_production * z * abs(own_hist) * 0.3 if own_hist else 0.0
            base_pairs.append((reale, pred_from(gran_delta=0.0)))
            adj_pairs.append((reale, pred_from(gran_delta=delta)))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    if not base_pairs:
        print("Nessun dato disponibile")
        return
    mae_base = mae(base_pairs)
    mae_adj = mae(adj_pairs)
    pct = (mae_adj - mae_base) / mae_base * 100
    print(f"n={len(base_pairs)}  MAE base={mae_base:.4f}  MAE adj(sens={sens_production})={mae_adj:.4f}  ({pct:+.3f}%)")


if __name__ == '__main__':
    league_dirs = other_league_dirs()
    print(f"Leghe isolate (esclude MLS/K League): {len(league_dirs)}")
    print(", ".join(sorted(league_dirs)))

    # #3: fwd_offense_granular_delta (gia' in produzione, sens=3.0)
    run_combo(
        "FWD.offensivo vs DEF.poss_lost_ctrl avversario", league_dirs,
        'fwd', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'),
        ['def'], ('poss_lost_ctrl',), sens_production=3.0
    )

    # #4: gk_def_pen_area_multiplier (nuovo oggi, sens=0.5) -- gruppo gk_vs_def_only
    run_combo(
        "GK.goalkeeping vs DEF.pen_area_entries avversario (solo DEF, isolato)", league_dirs,
        'gk', ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save', 'dive_catch'),
        ['def'], ('pen_area_entries',), sens_production=0.5
    )
