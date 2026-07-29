"""
Validate Opponent Trend + H2H -> level_score_atteso, GK (29/07)

Estensione NON sovrapposta del test gia' validato (validate_opponent_conceded_
level_allroles.py: media gol fatti/subiti ultime 10 partite avversario,
GK -0.59% MAE). Due segnali aggiuntivi testati SEPARATAMENTE (mai sommati
tra loro ne' applicati insieme all'aggiustamento sulla media nello stesso
punto -- si escludono a vicenda per costruzione, non sovrapposizione):

1. TREND: differenza fra media CORTA (3 partite) e LUNGA (10 partite) dei gol
   fatti dall'avversario -- cattura lo SLANCIO recente (in crescita/calo),
   dimensione diversa dal livello medio gia' testato.
2. H2H: se la coppia squadra-avversario si e' gia' affrontata almeno 2 volte
   nello storico disponibile, usa la media gol fatti SOLO in quegli scontri
   diretti al posto della media generica (sostituzione, non somma) --
   cattura dinamiche di stile/matchup specifiche.

Stesso rigore walk-forward di sempre. Uso:
python formazione_mls/diagnostics/validate_opponent_trend_h2h_gk.py
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
MIN_H2H_GAMES = 2


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


def build_scored_series_and_h2h():
    """scored[team] = [(dt, gol_fatti, opponent_slug), ...] -- serve sia per
    la media/trend generici sia per ricostruire l'H2H (filtrando per
    opponent_slug specifico)."""
    seen = set()
    scored = defaultdict(list)
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
                    # gc = gol subiti da team_slug in questa partita = gol
                    # FATTI da opp_slug -- registriamo dal punto di vista di
                    # CHI SEGNA (opp_slug), che e' quello che ci interessa qui.
                    scored[opp_slug].append((dt, gc, team_slug))
    for t in scored:
        scored[t].sort(key=lambda x: x[0])
    return scored


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


def series_before(series_for_opp, cutoff_dt, n_games, only_team=None):
    past = [(dt, gc) for dt, gc, t in series_for_opp if dt < cutoff_dt and (only_team is None or t == only_team)]
    if len(past) < (MIN_H2H_GAMES if only_team else 3):
        return None
    past = past[-n_games:] if n_games else past
    return [gc for _, gc in past]


def main():
    print("Ricostruzione serie gol fatti per squadra (con avversario specifico, per H2H)...")
    scored = build_scored_series_and_h2h()
    all_vals = [gc for s in scored.values() for _, gc, _ in s]
    global_mean = statistics.mean(all_vals)
    global_std = statistics.pstdev(all_vals)
    print(f"Media globale: {global_mean:.2f}  std: {global_std:.2f}")

    print("Caricamento cache GK...")
    players = load_gk_players()
    print(f"Portieri utilizzabili: {len(players)}\n")

    results_base = []       # media generica ultime 10 (baseline gia' validato)
    results_trend = defaultdict(list)   # sens -> [(reale, pred)]
    results_h2h = []        # sostituzione con media H2H quando disponibile (>=2 scontri)
    n_h2h_points = 0

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

            def score_from_lambda(lp):
                level = expected_level_from_rates(lp, lambda_neg)
                grezzo = level + granulare_hist
                corretto = (i / (i + SHRINK_K)) * grezzo + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_GK_PRIOR
                return corretto * venue_factor

            reale = scores[i]
            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            team_slug = None  # non serve qui, gia' incapsulato in rows implicitamente

            # --- baseline: nessun aggiustamento ---
            pred_base = score_from_lambda(lambda_pos)
            results_base.append((reale, pred_base))

            series_opp = scored.get(opp_slug, [])

            # --- TREND: media corta (3) - media lunga (10) ---
            short = series_before(series_opp, cutoff, 3)
            long_ = series_before(series_opp, cutoff, 10)
            if short and long_:
                trend_delta = (sum(short) / len(short)) - (sum(long_) / len(long_))
                z_trend = trend_delta / global_std if global_std else 0.0
                for sens in SENSITIVITY_GRID:
                    lp_adj = max(0.0, lambda_pos * (1 - sens * z_trend))
                    results_trend[sens].append((reale, score_from_lambda(lp_adj)))

            # H2H rimandato a un secondo giro (serve tracciare esplicitamente
            # la squadra propria in ogni riga per filtrare gli scontri
            # diretti -- non ancora fatto in questa versione dello script).

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    mae_base = mae(results_base)
    print(f"Punti di test: {len(results_base)}")
    print(f"MAE baseline (nessun aggiustamento): {mae_base:.3f}\n")

    print("--- TREND (corta 3 vs lunga 10 partite avversario) ---")
    best_sens, best_mae = None, None
    for sens in SENSITIVITY_GRID:
        pairs = results_trend[sens]
        if not pairs:
            continue
        m = mae(pairs)
        pct = (m - mae_base) / mae_base * 100
        flag = ''
        if best_mae is None or m < best_mae:
            best_sens, best_mae = sens, m
            flag = ' <== MIGLIORE FINORA'
        print(f"  sensibilita'={sens:.1f}  MAE={m:.3f} ({pct:+.2f}%, n={len(pairs)}){flag}")
    if best_mae is not None:
        pct_best = (best_mae - mae_base) / mae_base * 100
        print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}%)")


if __name__ == '__main__':
    main()
