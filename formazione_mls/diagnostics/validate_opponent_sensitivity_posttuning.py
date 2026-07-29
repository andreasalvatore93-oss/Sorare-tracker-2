"""
Validate Opponent Sensitivity per ruolo, DOPO il retuning 29/07 di
HALF_LIFE_GAMES/TREND_INTENSITY per DEF/MID/FWD (vedi commenti "AGGIORNATO
29/07" in formazione_mls/predict/test_gk.py, test_def.py, test_mid.py,
test_mls_fwd_all.py).

Motivazione: SENSITIVITY_BY_ROLE in opponent_strength.py (gk=1.0, def=1.0,
mid=0.7, fwd=1.0) e' stata calibrata PRIMA del retuning odierno di
half_life/trend_intensity. Un half_life diverso cambia lambda_pos/lambda_neg
storici (quanto "reattivo" e' il modello alla forma recente), quindi la
sensibilita' ottimale al segnale avversario potrebbe non essere piu' la
stessa. Questo script ririfa lo stesso identico backtest walk-forward di
validate_opponent_conceded_level_allroles.py / validate_opponent_conceded_
level.py ma:
  1. importa HALF_LIFE_GAMES/TREND_INTENSITY direttamente dai moduli
     test_gk.py/test_def.py/test_mid.py/test_mls_fwd_all.py (nessun valore
     hardcodato -- se cambiano di nuovo in futuro, questo script li segue).
  2. applica un trend granulare semplificato (breve/lungo half_life=5/10,
     pesato per TREND_INTENSITY) sullo stesso principio della produzione,
     cosi' lambda_pos/lambda_neg riflettono davvero l'assetto di oggi.
  3. usa la normalizzazione GLOBAL_MEAN_CONCEDED=1.29/GLOBAL_STD_CONCEDED=1.17
     GIA' FISSATA in produzione (opponent_strength.py) -- stessa base di
     confronto della sensibilita' attuale, cosi' il delta di MAE e'
     imputabile SOLO al cambio di half_life/trend, non alla normalizzazione.
  4. gira su TUTTE le leghe disponibili (glob 'formazione_*/...'), non solo
     MLS -- regola esplicita utente (29/07): "tutti i test fatti vanno fatti
     su tutte le leghe".

Uso: python formazione_mls/diagnostics/validate_opponent_sensitivity_posttuning.py
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

# Costanti AGGIORNATE 29/07, importate direttamente dai moduli di produzione
# (nessun valore hardcodato -- se vengono ritoccati di nuovo, questo test li
# segue automaticamente).
from formazione_mls.predict.test_gk import HALF_LIFE_GAMES as HL_GK, TREND_INTENSITY as TI_GK
from formazione_mls.predict.test_def import HALF_LIFE_GAMES as HL_DEF, TREND_INTENSITY as TI_DEF
from formazione_mls.predict.test_mid import HALF_LIFE_GAMES as HL_MID, TREND_INTENSITY as TI_MID
from formazione_mls.predict.test_mls_fwd_all import HALF_LIFE_GAMES as HL_FWD, TREND_INTENSITY as TI_FWD

MIN_HISTORY = 8  # >= trend lungo (10) + margine
N_OPTIONS = (3, 5, 7, 10, 15)
SENSITIVITY_GRID = [0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0]
SHRINK_K = 5.0
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6

# Sensibilita' ATTUALMENTE in produzione (opponent_strength.py), per il
# confronto finale.
CURRENT_SENSITIVITY = {'gk': 1.0, 'def': 1.0, 'mid': 0.7, 'fwd': 1.0}

# Normalizzazione FISSA gia' in produzione (opponent_strength.py) -- stessa
# base usata per calibrare CURRENT_SENSITIVITY, cosi' il confronto isola
# l'effetto del nuovo half_life/trend.
GLOBAL_MEAN_CONCEDED = 1.29
GLOBAL_STD_CONCEDED = 1.17

ROLE_PRIOR = {'mid': 53.4, 'def': 51.2, 'gk': 47.1, 'fwd': 53.02}
ROLE_SIGN = {'mid': 1, 'def': 1, 'gk': -1, 'fwd': 1}
ROLE_HALF_LIFE = {'gk': HL_GK, 'def': HL_DEF, 'mid': HL_MID, 'fwd': HL_FWD}
ROLE_TREND_INTENSITY = {'gk': TI_GK, 'def': TI_DEF, 'mid': TI_MID, 'fwd': TI_FWD}
TREND_HL_SHORT = 5.0
TREND_HL_LONG = 10.0


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


def build_team_conceded_and_scored_series():
    """Ritorna (conceded_series, scored_series): team_slug -> [(dt, valore), ...].
    Scan su TUTTE le leghe (formazione_*), non solo MLS."""
    seen = set()
    conceded = defaultdict(list)
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
                    conceded[team_slug].append((dt, gc))
                    scored[opp_slug].append((dt, gc))
    for d in (conceded, scored):
        for t in d:
            d[t].sort(key=lambda x: x[0])
    return conceded, scored


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    return sum(past) / len(past)


def load_role_players(role):
    """Scan TUTTE le leghe (formazione_*), non solo MLS."""
    players = []
    patterns = [f'formazione_*/output/*_{role}_all/.cache', f'formazione_*/output/*_{role}_calibration/.cache']
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


def trend_adjusted_lambda(hist_vals, half_life_long, trend_intensity):
    """Stesso principio della produzione: media pesata a half_life lungo
    (quella "ufficiale" del ruolo, oggi AGGIORNATA) combinata con un fattore
    di trend breve/lungo (5/10) pesato per TREND_INTENSITY. Se
    trend_intensity=0 (es. DEF oggi) il trend e' semplicemente disattivato,
    coerente con la produzione."""
    n = len(hist_vals)
    base = wmean(hist_vals, exp_weights(n, half_life_long))
    if trend_intensity <= 0 or n < 4:
        return base
    w_short = exp_weights(n, TREND_HL_SHORT)
    w_long = exp_weights(n, TREND_HL_LONG)
    m_short = wmean(hist_vals, w_short)
    m_long = wmean(hist_vals, w_long)
    trend = m_short - m_long
    return max(0.0, base + trend_intensity * trend)


def run_role(role, conceded_series, scored_series):
    prior = ROLE_PRIOR[role]
    sign = ROLE_SIGN[role]
    half_life = ROLE_HALF_LIFE[role]
    trend_intensity = ROLE_TREND_INTENSITY[role]
    signal_series = scored_series if sign < 0 else conceded_series
    label = "gol FATTI dall'avversario (segno invertito)" if sign < 0 else "gol SUBITI dall'avversario"

    print(f"\n{'='*86}\n{role.upper()} -- segnale: {label} | "
          f"HALF_LIFE_GAMES={half_life} TREND_INTENSITY={trend_intensity} (costanti di oggi, importate)\n{'='*86}")
    players = load_role_players(role)
    print(f"Giocatori {role.upper()} utilizzabili (tutte le leghe): {len(players)}")
    if not players:
        return None

    results_base_subset = defaultdict(list)
    results_adj = defaultdict(list)
    n_test_points = 0
    n_signal_available = 0

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            pos_vals = [r['pos_dec'] for r in hist]
            neg_vals = [r['neg_dec'] for r in hist]
            gran_vals = [r['granulare'] for r in hist]
            lambda_pos = trend_adjusted_lambda(pos_vals, half_life, trend_intensity)
            lambda_neg = trend_adjusted_lambda(neg_vals, half_life, trend_intensity)
            granulare_hist = wmean(gran_vals, exp_weights(i, half_life))
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
            found_any = False
            base_pair = (reale, pred_base)
            for n_games in N_OPTIONS:
                avg_val = avg_before(series_opp, cutoff, n_games)
                if avg_val is None:
                    continue
                found_any = True
                z = (avg_val - GLOBAL_MEAN_CONCEDED) / GLOBAL_STD_CONCEDED if GLOBAL_STD_CONCEDED > 0 else 0.0
                z_signed = sign * z
                for sens in SENSITIVITY_GRID:
                    lambda_pos_adj = max(0.0, lambda_pos * (1 + sens * z_signed))
                    level_adj = expected_level_from_rates(lambda_pos_adj, lambda_neg)
                    grezzo_adj = level_adj + granulare_hist
                    corretto_adj = (i / (i + SHRINK_K)) * grezzo_adj + (SHRINK_K / (i + SHRINK_K)) * prior
                    pred_adj = corretto_adj * venue_factor
                    results_adj[(n_games, sens)].append((reale, pred_adj))
                results_base_subset[n_games].append(base_pair)
            if found_any:
                n_signal_available += 1

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    print(f"Punti di test totali: {n_test_points} | con dato disponibile: "
          f"{n_signal_available} ({n_signal_available/n_test_points*100:.0f}%)")

    role_best = None  # (n_games, best_sens, best_mae, mae_base, mae_at_current_sens)
    for n_games in N_OPTIONS:
        subset = results_base_subset[n_games]
        if not subset:
            continue
        mae_base = mae(subset)
        print(f"\n--- ultime {n_games} partite (n={len(subset)}) -- MAE baseline (sens=0): {mae_base:.3f} ---")
        best_sens, best_mae = None, None
        mae_at_current = None
        for sens in SENSITIVITY_GRID:
            pairs = results_adj[(n_games, sens)]
            if not pairs:
                continue
            m = mae(pairs)
            pct = (m - mae_base) / mae_base * 100
            flag = ''
            if best_mae is None or m < best_mae:
                best_sens, best_mae = sens, m
                flag = ' <== MIGLIORE FINORA'
            if abs(sens - CURRENT_SENSITIVITY[role]) < 1e-9:
                mae_at_current = m
                flag += ' [SENSIBILITA'' ATTUALE PRODUZIONE]'
            print(f"  sensibilita'={sens:.1f}  MAE={m:.3f} ({pct:+.2f}%){flag}")
        pct_best = (best_mae - mae_base) / mae_base * 100
        print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}% vs baseline)")
        if role_best is None or best_mae < role_best[2]:
            role_best = (n_games, best_sens, best_mae, mae_base, mae_at_current)

    return role_best


def main():
    print("Ricostruzione serie storiche gol subiti/fatti per squadra (TUTTE le leghe)...")
    conceded, scored = build_team_conceded_and_scored_series()
    print(f"Squadre ricostruite: {len(conceded)}")

    summary = {}
    for role in ('gk', 'def', 'mid', 'fwd'):
        result = run_role(role, conceded, scored)
        if result:
            summary[role] = result

    print(f"\n{'='*86}\nRIEPILOGO FINALE (sensibilita' attuale vs migliore trovata, dopo retuning half_life/trend)\n{'='*86}")
    for role, (n_games, best_sens, best_mae, mae_base, mae_at_current) in summary.items():
        cur = CURRENT_SENSITIVITY[role]
        if mae_at_current is not None:
            delta_pct = (best_mae - mae_at_current) / mae_at_current * 100
            print(f"{role.upper():4s}: attuale sens={cur:.1f} (MAE={mae_at_current:.3f}) -> "
                  f"migliore sens={best_sens:.1f} (MAE={best_mae:.3f}, N={n_games})  "
                  f"delta={delta_pct:+.2f}%")
        else:
            print(f"{role.upper():4s}: attuale sens={cur:.1f} (non nel grid di N={n_games}) -> "
                  f"migliore sens={best_sens:.1f} (MAE={best_mae:.3f}, N={n_games}) vs baseline sens=0 "
                  f"(MAE={mae_base:.3f})")


if __name__ == '__main__':
    main()
