"""Test NUOVO (31/07, richiesta esplicita utente): rivalutare l'impatto del
"clean sheet del portiere" -- nello specifico, se la forza offensiva del
prossimo avversario (gol fatti storici, stesso segnale gia' usato per
opponent_lambda_multiplier) dovrebbe condizionare anche gli eventi
NEGATIVI del portiere (NEGATIVE_DECISIVE_STAT, prevalentemente legato ai
gol subiti), non solo quelli positivi come oggi.

**Gap reale trovato leggendo compute_score_atteso_gk (test_gk.py:1283-1284)**:
`lambda_pos_dec` viene GIA' moltiplicato per `opponent_lambda_mult`
(sensibilita' produzione 0.7, segno -1: avversario piu' offensivo abbassa
gli eventi positivi del portiere). `lambda_neg_dec` invece NON riceve
NESSUN aggiustamento per l'avversario -- resta la media storica pura, a
prescindere da quanto sia forte in attacco il prossimo avversario.
Intuitivamente un avversario che segna molto dovrebbe alzare gli eventi
NEGATIVI (gol subiti) tanto quanto abbassa quelli positivi (clean sheet/
parate) -- oggi il modello cattura solo meta' dell'effetto.

Metodo: stesso segnale reale gia' validato per lambda_pos (gol fatti
storici dal prossimo avversario, ultime 10 partite, z-score vs media
globale) applicato SUL LATO NEG con un moltiplicatore di segno OPPOSTO
(+1 invece di -1): avversario piu' forte in attacco -> piu' eventi
negativi attesi. Grid di sensibilita' sul lato NEG (0.0 = comportamento
attuale, invariato), lato POS SEMPRE fissato alla sensibilita' di
produzione (0.7, invariata) per isolare l'effetto della sola nuova
modifica. Formula IDENTICA a compute_score_atteso_gk (stesso shrink_k=30,
prior 48.81, fattore casa/trasferta shrink_k=20) tranne il nuovo
moltiplicatore neg, cosi' il punto sens_neg=0.0 riproduce ESATTAMENTE la
produzione attuale (baseline vera, non un proxy).

Uso: python formazione_mls/diagnostics/validate_gk_neg_opponent_adjustment.py
"""
import os
import sys
import glob
import json
import math
import statistics
import datetime
import importlib.util
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
N_GAMES = 10
POS_SENSITIVITY = 0.7  # produzione, INVARIATA
NEG_SENS_GRID = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0]


def _import(name, rel_path):
    spec = importlib.util.spec_from_file_location(name, rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gk = _import('test_gk_lib', 'formazione_mls/predict/test_gk.py')

HALF_LIFE_GAMES = gk.HALF_LIFE_GAMES
TREND_INTENSITY = gk.TREND_INTENSITY
SHRINK_K_OUTLIER_GK = gk.SHRINK_K_OUTLIER_GK
MEDIA_RUOLO_GK_PRIOR = gk.MEDIA_RUOLO_GK_PRIOR
SPLIT_SHRINK_K_GK = 20.0  # stesso valore hardcoded dentro compute_score_atteso_gk


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def build_team_scored_series():
    """Gol FATTI storici per squadra (stesso identico segnale gia' usato
    da opponent_lambda_multiplier per il lato pos), ricostruiti dalla cache
    locale gia' su disco -- nessuna query."""
    seen = set()
    scored = defaultdict(list)
    for pattern in ('formazione_*/output/*_gk_all/.cache', 'formazione_*/output/*_def_all/.cache',
                     'formazione_*/output/*_mid_all/.cache', 'formazione_*/output/*_gk_calibration/.cache',
                     'formazione_*/output/*_def_calibration/.cache', 'formazione_*/output/*_mid_calibration/.cache'):
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                try:
                    with open(fpath, encoding='utf-8') as f:
                        cache = json.load(f)
                except (json.JSONDecodeError, OSError):
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
                    scored[opp_slug].append((dt, gc))  # gol SUBITI dalla squadra osservata = gol FATTI dall'avversario
    for t in scored:
        scored[t].sort(key=lambda x: x[0])
    return scored


def avg_before(series_for_team, cutoff_dt, n_games):
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if len(past) < 3:
        return None
    return sum(past[-n_games:]) / len(past[-n_games:])


def load_gk_players():
    players = []
    seen_files = set()
    for pattern in ('formazione_*/output/*_gk_all/.cache', 'formazione_*/output/*_gk_calibration/.cache'):
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


def predict(rows, i, neg_sens, mult_pos, mult_neg):
    hist = rows[:i]
    weights = gk.exponential_weights(i, HALF_LIFE_GAMES)
    lambda_pos = gk.weighted_mean([r['pos_dec'] for r in hist], weights) * mult_pos
    lambda_neg = gk.weighted_mean([r['neg_dec'] for r in hist], weights) * mult_neg
    media_granulari = gk.weighted_mean([r['granulare'] for r in hist], weights)
    level_score = gk.expected_level_from_rates(lambda_pos, lambda_neg)
    fattore_trend, _s, _l = gk.compute_trend_factor(
        [r['granulare'] for r in hist], short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)
    grezzo = level_score + media_granulari * fattore_trend
    grezzo_corretto = ((i / (i + SHRINK_K_OUTLIER_GK)) * grezzo
                        + (SHRINK_K_OUTLIER_GK / (i + SHRINK_K_OUTLIER_GK)) * MEDIA_RUOLO_GK_PRIOR)

    home_scores = [r['score'] for r in hist if r['is_home'] is True]
    away_scores = [r['score'] for r in hist if r['is_home'] is False]
    overall = (sum(home_scores) / len(home_scores) + sum(away_scores) / len(away_scores)) / 2 \
        if (home_scores and away_scores) else gk.weighted_mean([r['score'] for r in hist], weights)
    target_is_home = rows[i]['is_home']
    fattore_venue = 1.0
    if overall > 0:
        if target_is_home:
            raw = (sum(home_scores) / len(home_scores)) / overall if home_scores else 1.0
            n_bucket = len(home_scores)
        else:
            raw = (sum(away_scores) / len(away_scores)) / overall if away_scores else 1.0
            n_bucket = len(away_scores)
        shrink = n_bucket / (n_bucket + SPLIT_SHRINK_K_GK)
        fattore_venue = 1.0 + shrink * (raw - 1.0)
    return grezzo_corretto * fattore_venue


def main():
    print("Ricostruzione serie storiche gol fatti per squadra (stesso segnale di opponent_lambda_multiplier)...")
    scored_series = build_team_scored_series()
    all_vals = [v for series in scored_series.values() for _, v in series]
    global_mean = statistics.mean(all_vals) if all_vals else 1.0
    global_std = statistics.pstdev(all_vals) if len(all_vals) > 1 else 1.0
    print(f"Media globale gol fatti/partita: {global_mean:.2f} (std {global_std:.2f})")

    players = load_gk_players()
    print(f"Portieri utilizzabili: {len(players)}\n")

    results_by_sens = defaultdict(list)
    n_test = n_avail = 0

    for rows in players:
        n = len(rows)
        for i in range(MIN_HISTORY, n):
            n_test += 1
            opp_slug = rows[i]['opp_slug']
            cutoff = rows[i]['date']
            avg_val = avg_before(scored_series.get(opp_slug, []), cutoff, N_GAMES)
            if avg_val is None:
                continue
            n_avail += 1
            z = (avg_val - global_mean) / global_std if global_std > 0 else 0.0
            mult_pos = max(0.0, 1 - POS_SENSITIVITY * z)  # segno -1, produzione invariata
            reale = rows[i]['score']
            for sens in NEG_SENS_GRID:
                mult_neg = max(0.0, 1 + sens * z)  # segno +1, NUOVA ipotesi
                pred = predict(rows, i, sens, mult_pos, mult_neg)
                results_by_sens[sens].append((reale, pred))

    print(f"Punti di test totali: {n_test} | con dato avversario disponibile: {n_avail} "
          f"({n_avail/n_test*100:.0f}%)\n")

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    baseline_mae = mae(results_by_sens[0.0])
    print(f"{'sens_neg':<10} {'MAE':>8} {'vs produzione attuale':>24}")
    print(f"{'0.0 (oggi)':<10} {baseline_mae:>8.3f} {'--':>24}")
    for sens in NEG_SENS_GRID:
        if sens == 0.0:
            continue
        m = mae(results_by_sens[sens])
        pct = (m - baseline_mae) / baseline_mae * 100
        flag = ' <== MIGLIORA' if m < baseline_mae else ''
        print(f"{sens:<10} {m:>8.3f} {pct:>+23.2f}%{flag}")


if __name__ == '__main__':
    main()
