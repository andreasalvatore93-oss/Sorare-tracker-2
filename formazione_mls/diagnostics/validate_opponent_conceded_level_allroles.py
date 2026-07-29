"""
Validate Opponent Conceded/Scored -> level_score_atteso, MID/DEF/GK (29/07)

Estensione di validate_opponent_conceded_level.py (gia' fatto per FWD, -0.58%
MAE con gol subiti dall'avversario ultime 10 partite, sensibilita' 1.0) agli
altri tre ruoli. Segnale diverso per ruolo:

- MID, DEF: stessa logica di FWD -- avversario che CONCEDE tanto aumenta la
  probabilita' di un evento decisivo positivo (gol/assist). Per DEF questo e'
  coerente con la sez. 11 del RIASSUNTO: il salto di level_score a 60 per un
  difensore correla molto di piu' con l'aver SEGNATO che col clean sheet.
- GK: logica INVERSA -- non conta quanto concede il PROPRIO avversario (un
  portiere non segna), conta quanto SEGNA l'avversario (piu' forte in attacco
  = meno probabile il clean sheet, l'evento decisivo positivo principale per
  un GK). Serie "gol fatti dall'avversario" ricavata dagli STESSI dati gia'
  raccolti (i gol subiti di una squadra IN UNA PARTITA sono, per definizione,
  i gol fatti dall'avversario in quella stessa partita -- nessuna nuova
  scansione, solo la stessa tupla letta al contrario).

Uso: python formazione_mls/diagnostics/validate_opponent_conceded_level_allroles.py
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
N_OPTIONS = (5, 10)
SENSITIVITY_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0]
SHRINK_K = 5.0
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
POISSON_K_MAX = 6

# Prior di ruolo per lo shrinkage (stesse costanti gia' in produzione nei
# rispettivi test_<ruolo>.py -- MEDIA_RUOLO_X_PRIOR).
ROLE_PRIOR = {'mid': 53.4, 'def': 51.2, 'gk': 47.1}
# Segno del segnale per ruolo: +1 = usa gol SUBITI dall'avversario (MID/DEF,
# piu' concede -> piu' probabile un evento decisivo per il nostro giocatore),
# -1 = usa gol FATTI dall'avversario con segno invertito (GK, piu' forte
# l'attacco avversario -> MENO probabile il clean sheet).
ROLE_SIGN = {'mid': 1, 'def': 1, 'gk': -1}


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
    Un solo scan: ogni tupla (team, opponent, data, gc) alimenta SIA i gol
    subiti da 'team' SIA i gol fatti da 'opponent' in quella stessa partita."""
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


def run_role(role, conceded_series, scored_series):
    prior = ROLE_PRIOR[role]
    sign = ROLE_SIGN[role]
    signal_series = scored_series if sign < 0 else conceded_series
    label = "gol FATTI dall'avversario (segno invertito)" if sign < 0 else "gol SUBITI dall'avversario"

    print(f"\n{'='*78}\n{role.upper()} -- segnale: {label}\n{'='*78}")
    players = load_role_players(role)
    print(f"Giocatori {role.upper()} utilizzabili: {len(players)}")
    if not players:
        return

    all_signal = [v for series in signal_series.values() for _, v in series]
    global_mean = statistics.mean(all_signal) if all_signal else 1.0
    global_std = statistics.pstdev(all_signal) if len(all_signal) > 1 else 1.0

    results_base_subset = defaultdict(list)
    results_adj = defaultdict(list)
    n_test_points = 0
    n_signal_available = 0

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
            found_any = False
            base_pair = (reale, pred_base)
            for n_games in N_OPTIONS:
                avg_val = avg_before(series_opp, cutoff, n_games)
                if avg_val is None:
                    continue
                found_any = True
                z = (avg_val - global_mean) / global_std if global_std > 0 else 0.0
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

    for n_games in N_OPTIONS:
        subset = results_base_subset[n_games]
        if not subset:
            continue
        mae_base = mae(subset)
        print(f"\n--- ultime {n_games} partite (n={len(subset)}) -- MAE baseline: {mae_base:.3f} ---")
        best_sens, best_mae = None, None
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
            print(f"  sensibilita'={sens:.1f}  MAE={m:.3f} ({pct:+.2f}%){flag}")
        pct_best = (best_mae - mae_base) / mae_base * 100
        print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}%)")


def main():
    print("Ricostruzione serie storiche gol subiti/fatti per squadra...")
    conceded, scored = build_team_conceded_and_scored_series()
    print(f"Squadre ricostruite: {len(conceded)}")
    for role in ('mid', 'def', 'gk'):
        run_role(role, conceded, scored)


if __name__ == '__main__':
    main()
