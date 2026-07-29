"""
Validate DEF: tackle vinto vs possesso perso avversari, intercettazione
riuscita vs passaggio mancato avversari (29/07, richiesta esplicita utente).

Stessa metodologia di validate_def_duels_opponent.py (duello vinto vs
duel_lost, scartato: -0.07%). Due segnali distinti testati qui:
1. won_tackle (DEF) condizionato su poss_lost_ctrl medio di FWD+MID avversari.
2. interception_won (DEF) condizionato su missed_pass medio di FWD+MID avversari.

Uso: python formazione_mls/diagnostics/validate_def_tackle_intercept_opponent.py
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

MIN_HISTORY = 6
SHRINK_K = 5.0
MEDIA_RUOLO_DEF_PRIOR = 51.2
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6
SENSITIVITY_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0]
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


def build_opponent_series(stat_name):
    per_team_date = defaultdict(list)
    patterns = ['formazione_*/output/*_fwd_all/.cache', 'formazione_*/output/*_mid_all/.cache',
                'formazione_*/output/*_fwd_calibration/.cache', 'formazione_*/output/*_mid_calibration/.cache']
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
                        if row.get('stat') == stat_name:
                            val += row.get('statValue', 0.0) or 0.0
                    per_team_date[(team_slug, dt)].append(val)

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        series[team].append((dt, sum(vals) / len(vals)))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    return series


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [v for dt, v in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def load_def_players(own_stat_names):
    players = []
    patterns = ['formazione_*/output/*_def_all/.cache', 'formazione_*/output/*_def_calibration/.cache']
    seen_files = set()
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
                            own_v += row.get('totalScore', 0.0) or 0.0
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


def run_test(label, own_stat_names, opp_stat_name):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    opp_series = build_opponent_series(opp_stat_name)
    all_vals = [v for s in opp_series.values() for _, v in s]
    gm, gs = statistics.mean(all_vals), statistics.pstdev(all_vals)
    print(f"Media globale {opp_stat_name}/apparizione avversario: {gm:.2f}  std: {gs:.2f}")

    players = load_def_players(own_stat_names)
    print(f"Difensori utilizzabili: {len(players)}")

    results_adj = defaultdict(list)

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, 9.0)
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
                corretto = (i / (i + SHRINK_K)) * grezzo + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_DEF_PRIOR
                return corretto * venue_factor

            reale = scores[i]
            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = opp_series.get(opp_slug, [])
            avg_val = avg_before(series_opp, cutoff, N_GAMES)
            if avg_val is None:
                continue
            z = (avg_val - gm) / gs if gs else 0.0
            for sens in SENSITIVITY_GRID:
                delta = sens * z * abs(own_hist) * 0.3 if own_hist else 0.0
                results_adj[sens].append((reale, pred_from(gran_delta=delta)))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    baseline_pairs = results_adj[0.0]
    if not baseline_pairs:
        print("Nessun dato disponibile")
        return
    mae_base = mae(baseline_pairs)
    print(f"Punti di test: {len(baseline_pairs)}  MAE baseline: {mae_base:.3f}")
    best_sens, best_mae = None, None
    for sens in SENSITIVITY_GRID:
        pairs = results_adj[sens]
        if not pairs:
            continue
        m = mae(pairs)
        pct = (m - mae_base) / mae_base * 100
        flag = ''
        if best_mae is None or m < best_mae:
            best_sens, best_mae = sens, m
            flag = ' <== MIGLIORE FINORA'
        print(f"  sensibilita'={sens:.1f}  MAE={m:.3f} ({pct:+.2f}%){flag}")
    pct_best = (best_mae - mae_base) / mae_base * 100
    print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}%)")


if __name__ == '__main__':
    run_test("EFFICACIA DIFENSIVA AGGREGATA (won_tackle+blocked_cross+outfielder_block+interception_won) vs OCCASIONI CREATE (big_chance_created) avversari",
              ('won_tackle', 'blocked_cross', 'outfielder_block', 'interception_won'), 'big_chance_created')
