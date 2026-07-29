"""
Validate DEF: tutte le combinazioni sensate granulare-proprio vs
granulare-avversario (FWD+MID) ancora non testate (29/07, richiesta
esplicita utente "prova tutte le combinazioni sensate").

Gia' testate altrove (tutte bocciate/trascurabili):
- duel_won vs duel_lost avversario: -0.07%
- won_tackle vs poss_lost_ctrl avversario: 0.00%
- interception_won vs missed_pass avversario: -0.06%
- efficacia difensiva aggregata vs big_chance_created avversario: 0.00%

Testate qui (6 nuove combinazioni):
A. duel_won vs won_contest avversario (chi salta l'uomo spesso ruba duelli)
B. interception_won vs accurate_pass avversario (avversario preciso = meno intercetti)
C. won_tackle vs pen_area_entries avversario (avversario entra spesso in area = piu' tackle)
D. falli commessi (DEF) vs won_contest avversario (dribbling forza falli)
E. goals_conceded (DEF, granulare proprio) vs ontarget_scoring_att avversario (tiri in porta, non gol)
F. passaggio (DEF) vs duel_won avversario (pressing alto = passaggio peggiore)

Stessa metodologia walk-forward di tutti gli altri test di questa serie.
Uso: python formazione_mls/diagnostics/validate_def_all_combos.py
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

FOULS_STATS = ('foul_committed',)  # verificato sotto se il nome esiste davvero


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


_OPP_CACHE = {}


def build_opponent_series(stat_names):
    key = tuple(sorted(stat_names))
    if key in _OPP_CACHE:
        return _OPP_CACHE[key]
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
                        if row.get('stat') in stat_names:
                            val += row.get('statValue', 0.0) or 0.0
                    per_team_date[(team_slug, dt)].append(val)

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        series[team].append((dt, sum(vals) / len(vals)))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    _OPP_CACHE[key] = series
    return series


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [v for dt, v in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


_DEF_CACHE = {}


def load_def_players(own_stat_names, own_is_statvalue=False):
    key = (tuple(sorted(own_stat_names)), own_is_statvalue)
    if key in _DEF_CACHE:
        return _DEF_CACHE[key]
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
    _DEF_CACHE[key] = players
    return players


def run_test(label, own_stat_names, opp_stat_names, own_is_statvalue=False, invert_sign=False):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    opp_series = build_opponent_series(opp_stat_names)
    all_vals = [v for s in opp_series.values() for _, v in s]
    if not all_vals:
        print("NESSUN DATO per lo stat avversario (nome sbagliato/non tracciato)")
        return
    gm, gs = statistics.mean(all_vals), statistics.pstdev(all_vals)
    print(f"Media globale avversario: {gm:.3f}  std: {gs:.3f}")

    players = load_def_players(own_stat_names, own_is_statvalue)

    results_adj = defaultdict(list)
    sign = -1 if invert_sign else 1

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
            z = sign * (avg_val - gm) / gs if gs else 0.0
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
        if best_mae is None or m < best_mae:
            best_sens, best_mae = sens, m
    pct_best = (best_mae - mae_base) / mae_base * 100
    print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}%)")


if __name__ == '__main__':
    run_test("A. duel_won (DEF) vs won_contest avversario",
              ('duel_won',), ('won_contest',))
    run_test("B. interception_won (DEF) vs accurate_pass avversario (segno invertito: piu' passa bene, meno intercetti)",
              ('interception_won',), ('accurate_pass',), invert_sign=True)
    run_test("C. won_tackle (DEF) vs pen_area_entries avversario",
              ('won_tackle',), ('pen_area_entries',))
    run_test("D. falli commessi (DEF, foul_committed) vs won_contest avversario",
              ('fouls',), ('won_contest',), own_is_statvalue=True)
    run_test("E. goals_conceded granulare (DEF) vs ontarget_scoring_att avversario (tiri in porta, non gol)",
              ('goals_conceded',), ('ontarget_scoring_att',), own_is_statvalue=True)
    run_test("F. passaggio (DEF, accurate_pass) vs duel_won avversario (pressing alto = passaggio peggiore, segno invertito)",
              ('accurate_pass', 'successful_final_third_passes'), ('duel_won',), invert_sign=True)
