"""Validate un TETTO massimo su opponent_lambda_multiplier (30/07, richiesta
esplicita utente, caso reale Rafael Navarro vs Austin: Austin ha subito una
media di 2.4 gol/partita nelle ultime 10 contro una media di lega di 1.29,
z=+0.95, che con sensibilita' FWD=1.0 produce un moltiplicatore di 1.95 --
quasi il doppio del tasso di eventi positivi, SENZA alcun tetto massimo nella
formula attuale (opponent_strength.py: max(0.0, 1+sens*z), solo un pavimento).

Il grid search del 29/07 (validate_opponent_conceded_level.py) aveva scelto
sensibilita'=1.0 SENZA mai testare un tetto -- la sensibilita' ottima puo'
essere corretta "in media" ma la formula lineare senza tetto puo' essere
troppo aggressiva nelle code (z vicino o oltre 1 deviazione standard, come
in questo caso). Qui si tiene FISSA la sensibilita' di produzione (1.0,
N=10 partite) e si testa SOLO l'aggiunta di un tetto massimo al
moltiplicatore, walk-forward su dati reali, stesso metodo di sempre.

Uso: python formazione_mls/diagnostics/validate_opponent_lambda_cap.py
"""
import os
import sys
import glob
import json
import math
import statistics
import datetime
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
N_GAMES = 10          # produzione: N_GAMES_DEFAULT in opponent_strength.py
SENSITIVITY = 1.0     # produzione: SENSITIVITY_BY_ROLE['fwd']
CAP_GRID = [None, 1.0, 1.01, 1.02, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.0, 2.5]  # None = nessun tetto (produzione attuale); 1.0 = feature di fatto disattivata

MEDIA_RUOLO_FWD_PRIOR = 53.02
SHRINK_K = 5.0
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6


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


def build_team_conceded_series():
    seen = set()
    series = defaultdict(list)
    patterns = ['formazione_*/output/*_gk_all/.cache', 'formazione_*/output/*_def_all/.cache',
                'formazione_*/output/*_mid_all/.cache', 'formazione_*/output/*_gk_calibration/.cache',
                'formazione_*/output/*_def_calibration/.cache', 'formazione_*/output/*_mid_calibration/.cache']
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
                    series[team_slug].append((dt, gc))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    return series


def avg_conceded_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def load_fwd_players():
    players = []
    patterns = ['formazione_*/output/*_fwd_all/.cache', 'formazione_*/output/*_fwd_calibration/.cache']
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
    print("Ricostruzione serie storiche gol-subiti per squadra...")
    team_conceded = build_team_conceded_series()
    all_conceded = [gc for series in team_conceded.values() for _, gc in series]
    global_mean = statistics.mean(all_conceded) if all_conceded else 1.0
    global_std = statistics.pstdev(all_conceded) if len(all_conceded) > 1 else 1.0
    print(f"Media globale gol subiti/partita: {global_mean:.2f} (std {global_std:.2f})")

    players = load_fwd_players()
    print(f"Giocatori FWD utilizzabili: {len(players)}\n")

    results_by_cap = defaultdict(list)
    z_extremes = []  # (z, cap_would_matter)
    n_test_points = 0
    n_available = 0

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, 12.0)
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
            n_test_points += 1

            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = team_conceded.get(opp_slug, [])
            avg_conc = avg_conceded_before(series_opp, cutoff, N_GAMES)
            if avg_conc is None:
                continue
            n_available += 1
            z = (avg_conc - global_mean) / global_std if global_std > 0 else 0.0
            mult_uncapped = max(0.0, 1 + SENSITIVITY * z)
            z_extremes.append(mult_uncapped)

            for cap in CAP_GRID:
                mult = mult_uncapped if cap is None else min(mult_uncapped, cap)
                lambda_pos_adj = lambda_pos * mult
                level_adj = expected_level_from_rates(lambda_pos_adj, lambda_neg)
                grezzo_adj = level_adj + granulare_hist
                corretto_adj = (i / (i + SHRINK_K)) * grezzo_adj + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_FWD_PRIOR
                pred_adj = corretto_adj * venue_factor
                results_by_cap[cap].append((reale, pred_adj))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    print(f"Punti di test totali: {n_test_points} | con dato disponibile: {n_available} "
          f"({n_available/n_test_points*100:.0f}%)\n")
    print(f"Distribuzione moltiplicatore SENZA tetto: min={min(z_extremes):.2f} "
          f"p90={sorted(z_extremes)[int(len(z_extremes)*0.9)]:.2f} "
          f"p99={sorted(z_extremes)[int(len(z_extremes)*0.99)]:.2f} max={max(z_extremes):.2f}\n")

    mae_uncapped = mae(results_by_cap[None])
    print(f"{'tetto':<10} {'MAE':>8} {'vs uncapped':>14} {'n casi toccati dal tetto':>26}")
    print(f"{'nessuno':<10} {mae_uncapped:>8.3f} {'--':>14} {'--':>26}")
    for cap in CAP_GRID:
        if cap is None:
            continue
        m = mae(results_by_cap[cap])
        pct = (m - mae_uncapped) / mae_uncapped * 100
        n_toccati = sum(1 for x in z_extremes if x > cap)
        flag = ' <== MIGLIORA' if m < mae_uncapped else ''
        print(f"{cap:<10} {m:>8.3f} {pct:>+13.2f}% {n_toccati:>26}{flag}")


if __name__ == '__main__':
    main()
