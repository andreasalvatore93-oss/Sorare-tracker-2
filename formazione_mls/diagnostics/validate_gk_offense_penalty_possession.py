"""
Validate GK: volume offensivo avversario (su granulare), rigori vinti
avversario ultime 10, possesso avversario (proxy poss_lost_ctrl) (29/07).

Tre segnali NON sovrapposti fra loro ne' col segnale gia' validato (media
gol fatti/subiti avversario ultime 10 -> level_score_atteso):
1. Volume offensivo avversario (OFFENSIVE_STATS) -> granulare aggregato
   (componente diversa da level_score, additiva non moltiplicativa sullo
   stesso pezzo).
2. penalty_won avversario ultime 10 -> lambda_neg (penalty_conceded e'
   NEGATIVE_DECISIVE_STAT per il portiere, stat diversa da goals_conceded).
3. poss_lost_ctrl avversario (proxy possesso, valore BASSO = avversario
   tiene palla meglio) -> lambda_pos, stessa direzione concettuale del
   volume offensivo ma misurata su una stat diversa (duelli/possesso).

Uso: python formazione_mls/diagnostics/validate_gk_offense_penalty_possession.py
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
MEDIA_RUOLO_GK_PRIOR = 48.81
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6
SENSITIVITY_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0]
N_GAMES = 10
OFFENSIVE_STATS = ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                    'pen_area_entries', 'won_contest')


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


def build_opponent_series():
    """team_slug -> [(dt, offensive_vol, penalty_won, poss_lost_ctrl), ...]
    Media PER APPARIZIONE-GIOCATORE in quella partita (non somma team, non
    abbiamo garanzia di aver cachato tutti gli 11 -- la media e' piu' stabile
    al variare della copertura)."""
    per_team_date = defaultdict(list)  # (team,date) -> list of (off, pen, poss)
    patterns = ['formazione_*/output/*_fwd_all/.cache', 'formazione_*/output/*_mid_all/.cache',
                'formazione_*/output/*_def_all/.cache', 'formazione_*/output/*_fwd_calibration/.cache',
                'formazione_*/output/*_mid_calibration/.cache', 'formazione_*/output/*_def_calibration/.cache']
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
                    if not (home.get('slug') == team_slug or away.get('slug') == team_slug):
                        continue
                    dt = parse_date(g)
                    if dt is None:
                        continue
                    off = pen = poss = 0.0
                    for row in e['detailedScore']:
                        stat = row.get('stat')
                        if stat in OFFENSIVE_STATS:
                            off += row.get('totalScore', 0.0) or 0.0
                        elif stat == 'penalty_won':
                            pen += row.get('statValue', 0.0) or 0.0
                        elif stat == 'poss_lost_ctrl':
                            poss += row.get('statValue', 0.0) or 0.0
                    per_team_date[(team_slug, dt)].append((off, pen, poss))

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        n = len(vals)
        off_avg = sum(v[0] for v in vals) / n
        pen_avg = sum(v[1] for v in vals) / n
        poss_avg = sum(v[2] for v in vals) / n
        series[team].append((dt, off_avg, pen_avg, poss_avg))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    return series


def avg_before(series_for_team, cutoff_dt, n_games, idx):
    if not series_for_team:
        return None
    past = [tup[idx] for tup in series_for_team if tup[0] < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def load_gk_players():
    players = []
    patterns = ['formazione_*/output/*_gk_all/.cache', 'formazione_*/output/*_gk_calibration/.cache']
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


def main():
    print("Ricostruzione serie avversario (volume offensivo, rigori vinti, possesso)...")
    opp_series = build_opponent_series()
    all_off = [v[1] for s in opp_series.values() for v in s]
    all_pen = [v[2] for s in opp_series.values() for v in s]
    all_poss = [v[3] for s in opp_series.values() for v in s]
    gm_off, gs_off = statistics.mean(all_off), statistics.pstdev(all_off)
    gm_pen, gs_pen = statistics.mean(all_pen), statistics.pstdev(all_pen)
    gm_poss, gs_poss = statistics.mean(all_poss), statistics.pstdev(all_poss)
    print(f"Volume offensivo: media={gm_off:.2f} std={gs_off:.2f}")
    print(f"Rigori vinti: media={gm_pen:.3f} std={gs_pen:.3f}")
    print(f"Poss_lost_ctrl: media={gm_poss:.2f} std={gs_poss:.2f}")

    players = load_gk_players()
    print(f"\nPortieri utilizzabili: {len(players)}\n")

    results_base = defaultdict(list)  # segnale -> [(reale,pred_base)]  (sottoinsiemi diversi per copertura dato)
    results_off = defaultdict(list)
    results_pen = defaultdict(list)
    results_poss = defaultdict(list)

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, 6.0)
            lambda_pos = wmean([r['pos_dec'] for r in hist], weights)
            lambda_neg = wmean([r['neg_dec'] for r in hist], weights)
            granulare_hist = wmean([r['granulare'] for r in hist], weights)
            home_vals = [r['score'] for r in hist if r['is_home'] is True]
            away_vals = [r['score'] for r in hist if r['is_home'] is False]
            overall = sum(r['score'] for r in hist) / len(hist)
            target_is_home = rows[i]['is_home']
            ctx_vals = home_vals if target_is_home else away_vals
            venue_factor = 1.0
            if ctx_vals and overall:
                venue_factor = max(0.85, min(1.15, (sum(ctx_vals) / len(ctx_vals)) / overall))
            reale = scores[i]

            def pred_from(level, gran_delta=0.0):
                grezzo = level + granulare_hist + gran_delta
                corretto = (i / (i + SHRINK_K)) * grezzo + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_GK_PRIOR
                return corretto * venue_factor

            level_base = expected_level_from_rates(lambda_pos, lambda_neg)
            pred_base = pred_from(level_base)

            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = opp_series.get(opp_slug, [])

            # --- 1. Volume offensivo -> delta additivo sul granulare ---
            off_avg = avg_before(series_opp, cutoff, N_GAMES, 1)
            if off_avg is not None:
                z = (off_avg - gm_off) / gs_off if gs_off else 0.0
                results_base['off'].append((reale, pred_base))
                for sens in SENSITIVITY_GRID:
                    delta = sens * z * abs(granulare_hist) * 0.3  # scala ragionevole: max +-30% del granulare storico a z=1,sens=1
                    results_off[sens].append((reale, pred_from(level_base, gran_delta=delta)))

            # --- 2. Rigori vinti avversario -> lambda_neg ---
            pen_avg = avg_before(series_opp, cutoff, N_GAMES, 2)
            if pen_avg is not None:
                z = (pen_avg - gm_pen) / gs_pen if gs_pen else 0.0
                results_base['pen'].append((reale, pred_base))
                for sens in SENSITIVITY_GRID:
                    lambda_neg_adj = max(0.0, lambda_neg * (1 + sens * z))
                    level_adj = expected_level_from_rates(lambda_pos, lambda_neg_adj)
                    results_pen[sens].append((reale, pred_from(level_adj)))

            # --- 3. Possesso (poss_lost_ctrl avversario, BASSO = avversario tiene palla meglio) ---
            poss_avg = avg_before(series_opp, cutoff, N_GAMES, 3)
            if poss_avg is not None:
                z = (poss_avg - gm_poss) / gs_poss if gs_poss else 0.0
                # z alto = avversario perde palla spesso (ci lascia meno pressione) -> lambda_pos su, quindi
                # usiamo -z: avversario con poss_lost_ctrl BASSO (tiene palla bene) abbassa lambda_pos.
                results_base['poss'].append((reale, pred_base))
                for sens in SENSITIVITY_GRID:
                    lambda_pos_adj = max(0.0, lambda_pos * (1 - sens * (-z)))
                    level_adj = expected_level_from_rates(lambda_pos_adj, lambda_neg)
                    results_poss[sens].append((reale, pred_from(level_adj)))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    for label, results, base_key in (
        ("VOLUME OFFENSIVO (granulare)", results_off, 'off'),
        ("RIGORI VINTI ultime 10 (lambda_neg)", results_pen, 'pen'),
        ("POSSESSO proxy poss_lost_ctrl (lambda_pos)", results_poss, 'poss'),
    ):
        base_pairs = results_base[base_key]
        if not base_pairs:
            print(f"\n{label}: nessun dato disponibile")
            continue
        mae_base = mae(base_pairs)
        print(f"\n=== {label} === (n={len(base_pairs)}, MAE baseline={mae_base:.3f})")
        best_sens, best_mae = None, None
        for sens in SENSITIVITY_GRID:
            pairs = results[sens]
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
    main()
