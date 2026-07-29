"""
Validate Opponent Conceded -> level_score_atteso (29/07)

Test pulito del fattore forza avversario, stavolta con un dato genuinamente
storico (gol subiti dall'avversario, presi da detailedScore di partite gia'
giocate -- immutabile) invece di domesticLeagueRanking (scoperto contaminato:
e' un attributo CORRENTE della squadra, non ancorato al tempo, vedi
RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md).

Ipotesi (richiesta esplicita utente): un avversario che concede molti gol
dovrebbe aumentare la probabilita' di un evento decisivo positivo per un FWD
(piu' occasioni, piu' gol) -- quindi il posto giusto per l'aggiustamento e'
lambda_pos (tasso di eventi decisivi positivi) dentro expected_level_from_rates,
non un fattore moltiplicativo su tutto lo score_atteso (opzione 2 del menu
proposto in chat, non le opzioni 1/3).

Metodo (stesso rigore walk-forward usato ovunque in questo repo):
1. Ricostruisce la serie storica (data, gol_subiti) per OGNI squadra, da
   TUTTE le cache GK+DEF+MID di TUTTE le leghe (nessuna nuova query -- il dato
   e' gia' su disco).
2. Per ogni FWD in cache, per ogni sua partita di test: calcola lambda_pos/neg
   storici (media pesata pre-partita, half_life=12 come in produzione),
   calcola la media gol subiti dal prossimo avversario nelle sue N partite
   PRECEDENTI a quella data (niente lookahead), converte in z-score.
3. Confronta MAE: baseline (nessun aggiustamento, produzione attuale) vs
   lambda_pos_adjusted = lambda_pos * (1 + sensitivita * z), grid su
   sensitivita' e su N (5/10 partite).

Uso: python formazione_mls/diagnostics/validate_opponent_conceded_level.py
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
    """team_slug -> lista ordinata cronologicamente di (datetime, gol_subiti),
    deduplicata per (team, opponent, data). Scansiona TUTTE le cache
    GK/DEF/MID di TUTTE le leghe (produzione '_all' + calibrazione)."""
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
    """Ritorna lista di dict con scores/is_home/pos_dec/neg_dec/opponent_slug/
    date/residual/granulari per ogni giocatore FWD, pooled su tutte le leghe."""
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
    print("Ricostruzione serie storiche gol-subiti per squadra (GK+DEF+MID, tutte le leghe)...")
    team_conceded = build_team_conceded_series()
    print(f"Squadre ricostruite: {len(team_conceded)}")
    all_conceded = [gc for series in team_conceded.values() for _, gc in series]
    global_mean = statistics.mean(all_conceded) if all_conceded else 1.0
    global_std = statistics.pstdev(all_conceded) if len(all_conceded) > 1 else 1.0
    print(f"Media globale gol subiti/partita: {global_mean:.2f} (std {global_std:.2f})")

    print("\nCaricamento cache FWD (produzione + calibrazione, tutte le leghe)...")
    players = load_fwd_players()
    print(f"Giocatori FWD utilizzabili: {len(players)}")

    # Per ogni combinazione (n_games, sensitivita'), accumula errori
    # baseline vs adjusted sullo STESSO insieme di punti di test.
    results_base = []
    results_base_subset = defaultdict(list)  # n_games -> [(reale, pred_base), ...] STESSO sottoinsieme di results_adj
    results_adj = defaultdict(list)  # (n_games, sens) -> [(reale, pred), ...]
    n_test_points = 0
    n_conceded_available = 0

    for rows in players:
        n = len(rows)
        scores = [r['score'] for r in rows]
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            weights = exp_weights(i, 12.0)
            lambda_pos = wmean([r['pos_dec'] for r in hist], weights)
            lambda_neg = wmean([r['neg_dec'] for r in hist], weights)
            granulare_hist = wmean([r['granulare'] for r in hist], weights)
            # trend granulare (stesso principio della produzione, half_life
            # separato corto/lungo 5/10 sui valori grezzi, no intensity qui
            # per semplicita' del test -- non e' l'oggetto della verifica).
            level_base = expected_level_from_rates(lambda_pos, lambda_neg)
            grezzo_base = level_base + granulare_hist
            corretto_base = (i / (i + SHRINK_K)) * grezzo_base + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_FWD_PRIOR
            # venue (compute_split_factor semplificato: media contesto / media generale)
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
            results_base.append((reale, pred_base))
            n_test_points += 1

            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            series_opp = team_conceded.get(opp_slug, [])
            found_any = False
            base_pair_this_point = (reale, pred_base)
            for n_games in N_OPTIONS:
                avg_conc = avg_conceded_before(series_opp, cutoff, n_games)
                if avg_conc is None:
                    continue
                found_any = True
                z = (avg_conc - global_mean) / global_std if global_std > 0 else 0.0
                for sens in SENSITIVITY_GRID:
                    lambda_pos_adj = max(0.0, lambda_pos * (1 + sens * z))
                    level_adj = expected_level_from_rates(lambda_pos_adj, lambda_neg)
                    grezzo_adj = level_adj + granulare_hist
                    corretto_adj = (i / (i + SHRINK_K)) * grezzo_adj + (SHRINK_K / (i + SHRINK_K)) * MEDIA_RUOLO_FWD_PRIOR
                    pred_adj = corretto_adj * venue_factor
                    results_adj[(n_games, sens)].append((reale, pred_adj))
                results_base_subset[n_games].append(base_pair_this_point)
            if found_any:
                n_conceded_available += 1

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    mae_base = mae(results_base)
    print(f"\nPunti di test totali: {n_test_points}")
    print(f"Con dato gol-subiti-avversario disponibile: {n_conceded_available} "
          f"({n_conceded_available/n_test_points*100:.0f}%)")
    print(f"MAE baseline (produzione attuale, nessun aggiustamento): {mae_base:.3f}")
    print()
    for n_games in N_OPTIONS:
        mae_base_subset = mae(results_base_subset[n_games])
        print(f"--- ultime {n_games} partite dell'avversario (n={len(results_base_subset[n_games])}) ---")
        print(f"  MAE baseline SULLO STESSO sottoinsieme (confronto equo): {mae_base_subset:.3f}")
        best_sens, best_mae = None, None
        for sens in SENSITIVITY_GRID:
            pairs = results_adj[(n_games, sens)]
            if not pairs:
                continue
            m = mae(pairs)
            pct = (m - mae_base_subset) / mae_base_subset * 100
            flag = ''
            if best_mae is None or m < best_mae:
                best_sens, best_mae = sens, m
                flag = ' <== MIGLIORE FINORA'
            print(f"  sensibilita'={sens:.1f}  MAE={m:.3f} ({pct:+.2f}% vs baseline, n={len(pairs)}){flag}")
        pct_best = (best_mae - mae_base_subset) / mae_base_subset * 100
        print(f"  MIGLIORE: sensibilita'={best_sens} (MAE={best_mae:.3f}, {pct_best:+.2f}% vs baseline)")
        print()


if __name__ == '__main__':
    main()
