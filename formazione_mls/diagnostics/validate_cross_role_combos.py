"""
Validate cross-role granulare-proprio vs granulare-avversario, esteso a
MID/FWD/GK (29/07, richiesta esplicita utente: "prova tutte le combinazioni
sensate mid vs dif/att/cent avversario, poi att vs dif/cent avversario, poi
le combinazioni rimaste per portiere").

Framework generico: run_combo(own_role, own_stat_names, opp_roles,
opp_stat_names, invert_sign, own_is_statvalue) -- stessa metodologia
walk-forward di tutti gli altri test di questa serie (media ultime 10
partite avversario, grid di sensibilita', MAE su un pezzo additivo del
punteggio). opp_roles e' una LISTA di ruoli (es. ['def'] o ['def','mid'])
le cui cache vengono scansionate per costruire la serie storica
dell'avversario (aggregata per squadra+data, media per apparizione).

Uso: python formazione_mls/diagnostics/validate_cross_role_combos.py
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
MEDIA_RUOLO_PRIOR = {'gk': 48.81, 'def': 51.2, 'mid': 53.4, 'fwd': 53.02}
HALF_LIFE = {'gk': 6.0, 'def': 9.0, 'mid': 12.0, 'fwd': 12.0}
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


_OPP_CACHE = {}


def build_opponent_series(opp_roles, stat_names):
    key = (tuple(sorted(opp_roles)), tuple(sorted(stat_names)))
    if key in _OPP_CACHE:
        return _OPP_CACHE[key]
    per_team_date = defaultdict(list)
    patterns = []
    for r in opp_roles:
        patterns.append(f'formazione_*/output/*_{r}_all/.cache')
        patterns.append(f'formazione_*/output/*_{r}_calibration/.cache')
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


_OWN_CACHE = {}


def load_own_players(own_role, own_stat_names, own_is_statvalue):
    key = (own_role, tuple(sorted(own_stat_names)), own_is_statvalue)
    if key in _OWN_CACHE:
        return _OWN_CACHE[key]
    players = []
    patterns = [f'formazione_*/output/*_{own_role}_all/.cache', f'formazione_*/output/*_{own_role}_calibration/.cache']
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
    _OWN_CACHE[key] = players
    return players


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [v for dt, v in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def run_combo(label, own_role, own_stat_names, opp_roles, opp_stat_names,
              own_is_statvalue=False, invert_sign=False):
    print(f"\n{'='*74}\n{label}\n{'='*74}")
    opp_series = build_opponent_series(opp_roles, opp_stat_names)
    all_vals = [v for s in opp_series.values() for _, v in s]
    if not all_vals:
        print("NESSUN DATO per lo stat avversario (nome sbagliato/non tracciato)")
        return
    gm, gs = statistics.mean(all_vals), statistics.pstdev(all_vals)
    if gs == 0:
        print("Deviazione standard zero, salto")
        return

    players = load_own_players(own_role, own_stat_names, own_is_statvalue)
    if not players:
        print(f"Nessun giocatore {own_role} utilizzabile")
        return

    half_life = HALF_LIFE[own_role]
    prior = MEDIA_RUOLO_PRIOR[own_role]
    sign = -1 if invert_sign else 1
    results_adj = defaultdict(list)

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
    best_sens, best_mae = None, None
    for sens in SENSITIVITY_GRID:
        pairs = results_adj[sens]
        if not pairs:
            continue
        m = mae(pairs)
        if best_mae is None or m < best_mae:
            best_sens, best_mae = sens, m
    pct_best = (best_mae - mae_base) / mae_base * 100
    print(f"n={len(baseline_pairs)}  MAE base={mae_base:.3f}  MIGLIORE: sens={best_sens} "
          f"(MAE={best_mae:.3f}, {pct_best:+.2f}%)")


if __name__ == '__main__':
    combo = sys.argv[1] if len(sys.argv) > 1 else 'all'

    MID_VS_DEF = [
        ("MID.offensivo vs DEF.duel_lost avversario", 'mid', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'), ['def'], ('duel_lost',)),
        ("MID.offensivo vs DEF.poss_lost_ctrl avversario", 'mid', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'), ['def'], ('poss_lost_ctrl',)),
        ("MID.passaggio vs DEF.duel_lost avversario", 'mid', ('accurate_pass', 'successful_final_third_passes'), ['def'], ('duel_lost',)),
    ]
    MID_VS_FWD = [
        ("MID.duel_won vs FWD.duel_lost avversario", 'mid', ('duel_won',), ['fwd'], ('duel_lost',)),
        ("MID.interception_won vs FWD.missed_pass avversario", 'mid', ('interception_won',), ['fwd'], ('missed_pass',)),
        ("MID.won_tackle vs FWD.won_contest avversario", 'mid', ('won_tackle',), ['fwd'], ('won_contest',)),
    ]
    MID_VS_MID = [
        ("MID.duel_won vs MID.duel_lost avversario", 'mid', ('duel_won',), ['mid'], ('duel_lost',)),
        ("MID.passaggio vs MID.duel_won avversario (pressing, invertito)", 'mid', ('accurate_pass', 'successful_final_third_passes'), ['mid'], ('duel_won',), False, True),
        ("MID.offensivo vs MID.poss_lost_ctrl avversario", 'mid', ('ontarget_scoring_att', 'big_chance_created'), ['mid'], ('poss_lost_ctrl',)),
    ]
    FWD_VS_DEF = [
        ("FWD.offensivo vs DEF.duel_lost avversario", 'fwd', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'), ['def'], ('duel_lost',)),
        ("FWD.offensivo vs DEF.poss_lost_ctrl avversario", 'fwd', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'), ['def'], ('poss_lost_ctrl',)),
        ("FWD.won_contest vs DEF.duel_lost avversario", 'fwd', ('won_contest',), ['def'], ('duel_lost',)),
    ]
    FWD_VS_MID = [
        ("FWD.offensivo vs MID.duel_lost avversario", 'fwd', ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed', 'pen_area_entries', 'won_contest'), ['mid'], ('duel_lost',)),
        ("FWD.passaggio vs MID.duel_won avversario (pressing, invertito)", 'fwd', ('accurate_pass',), ['mid'], ('duel_won',), False, True),
    ]
    GK_REMAINING = [
        ("GK.goalkeeping vs OPP.pen_area_entries (FWD+MID)", 'gk', ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save', 'dive_catch', 'cross_not_claimed', 'six_second_violation', 'gk_smother', 'accurate_keeper_sweeper'), ['fwd', 'mid'], ('pen_area_entries',)),
        ("GK.poss_lost_ctrl vs OPP.duel_won (pressing, FWD+MID, invertito)", 'gk', ('poss_lost_ctrl',), ['fwd', 'mid'], ('duel_won',), True, True),
        ("GK.passaggio vs OPP.duel_won (pressing, FWD+MID, invertito)", 'gk', ('accurate_pass', 'successful_final_third_passes'), ['fwd', 'mid'], ('duel_won',), False, True),
    ]
    # 29/07, richiesta esplicita utente: due combinazioni mai provate --
    # DEF vs GK avversario (mai condizionato sul portiere, solo su FWD/MID/DEF)
    # e GK vs SOLO-DEF avversario isolato (prima solo FWD+MID pooled).
    DEF_VS_GK = [
        ("DEF.aerial/duel vs GK.alte uscite avversario", 'def', ('duel_won', 'aerial_won', 'clean_sheet'), ['gk'], ('good_high_claim', 'punches')),
        ("DEF.difensivo vs GK.goalkeeping avversario (scarso portiere -> piu' occasioni)", 'def', ('interception_won', 'won_tackle', 'clearance_off_line', 'blocked_shot'), ['gk'], ('saves', 'saved_ibox'), False, True),
    ]
    GK_VS_DEF_ONLY = [
        ("GK.goalkeeping vs DEF.duel_lost avversario (solo DEF, isolato)", 'gk', ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save', 'dive_catch'), ['def'], ('duel_lost',)),
        ("GK.goalkeeping vs DEF.pen_area_entries avversario (solo DEF, isolato)", 'gk', ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save', 'dive_catch'), ['def'], ('pen_area_entries',)),
    ]

    groups = {
        'mid_vs_def': MID_VS_DEF, 'mid_vs_fwd': MID_VS_FWD, 'mid_vs_mid': MID_VS_MID,
        'fwd_vs_def': FWD_VS_DEF, 'fwd_vs_mid': FWD_VS_MID, 'gk_remaining': GK_REMAINING,
        'def_vs_gk': DEF_VS_GK, 'gk_vs_def_only': GK_VS_DEF_ONLY,
    }

    to_run = groups.keys() if combo == 'all' else [combo]
    for gname in to_run:
        print(f"\n\n########## GRUPPO: {gname} ##########")
        for args in groups[gname]:
            run_combo(*args)
