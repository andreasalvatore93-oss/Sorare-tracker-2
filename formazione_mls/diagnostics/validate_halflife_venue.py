"""
Validate Half-Life + Venue Factor (26/07, terza sessione)

Backtest walk-forward rigoroso per rivedere DUE pezzi della formula
storica con lo stesso rigore appena usato per scoprire che
fattore_forza_avversario peggiorava il MAE (formazione_mls/diagnostics/
validate_team_defense_strength.py). Motivazione: HALF_LIFE_GAMES e
RANGE_MULTIPLIER furono calibrati a suo tempo con un grid search che
includeva ANCORA fattore_forza_avversario nella formula testata -- rimosso
quel fattore, l'half-life "vincente" trovato allora potrebbe non essere
piu' ottimale (potrebbe aver compensato per il rumore che quel fattore
introduceva). Testiamo quindi, con la formula ORA in produzione
(media_pesata * fattore_casa_trasferta * fattore_trend, senza avversario):

1. Un grid su HALF_LIFE_GAMES per ciascun ruolo, per vedere se il valore
   attuale (GK=9.0, DEF=12.0, MID=12.0, FWD=9.0) resta il migliore o se
   n'e' emerso uno diverso ora che l'avversario e' stato rimosso.
2. Se fattore_casa_trasferta (il fattore venue, calcolato su
   compute_split_factor) migliora o peggiora il MAE rispetto a non
   applicarlo affatto -- stesso test "on/off" gia' fatto per l'avversario.

Uso: python formazione_mls/diagnostics/validate_halflife_venue.py
"""
import os
import sys
import json
import glob
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
HALF_LIFE_GRID = [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0, 30.0, 40.0, 50.0, 70.0, 100.0, 150.0]

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_players(ruolo):
    """Ritorna lista di dict {scores, is_home_flags} per giocatore, gia'
    filtrati per storico minimo -- riusato per tutti i test di questo script
    (niente da ri-scannerizzare per ogni combinazione di parametri)."""
    # TUTTE le leghe (29/07, regola esplicita utente: piu' dati = piu'
    # accuratezza, ogni test va fatto su tutte le 28 leghe, non solo MLS/
    # Korea -- prima limitato a formazione_mls/output/mls_{ruolo}_calibration).
    patterns = [f'formazione_*/output/*_{ruolo}_calibration/.cache',
                f'formazione_*/output/*_{ruolo}_all/.cache']
    files = []
    seen = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath not in seen:
                    seen.add(fpath)
                    files.append(fpath)
    players = []
    for fpath in files:
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if len(entries) < MIN_HISTORY + 3:
            continue
        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue
        scores, is_home_flags = [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            scores.append(e.get('score') or 0.0)
            is_home_flags.append(is_home)
        if len(scores) < MIN_HISTORY + 3:
            continue
        players.append({'scores': scores, 'is_home_flags': is_home_flags})
    return players


def mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                    compute_trend_factor, half_life, trend_intensity, use_venue):
    errori = []
    for p in players:
        scores, is_home_flags = p['scores'], p['is_home_flags']
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            weights = exponential_weights(i, half_life)
            media = weighted_mean(hist_scores, weights)
            if use_venue:
                fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            else:
                fattore_ct = 1.0
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=trend_intensity)
            pred = media * fattore_ct * fattore_trend
            errori.append(scores[i] - pred)
    return statistics.mean(abs(e) for e in errori), len(errori)


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HALF_LIFE_GAMES_ATTUALE = mod.HALF_LIFE_GAMES
    TREND_INTENSITY = mod.TREND_INTENSITY

    players = load_players(ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return

    print(f"\n{'='*78}\n{ruolo.upper()} ({len(players)} giocatori) -- half_life attuale={HALF_LIFE_GAMES_ATTUALE}\n{'='*78}")

    # --- Test 1: venue ON (attuale) vs OFF, con half_life ATTUALE ---
    mae_venue_on, n = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                                      compute_trend_factor, HALF_LIFE_GAMES_ATTUALE, TREND_INTENSITY, True)
    mae_venue_off, _ = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                                       compute_trend_factor, HALF_LIFE_GAMES_ATTUALE, TREND_INTENSITY, False)
    pct_venue = (mae_venue_off - mae_venue_on) / mae_venue_on * 100
    print(f"  fattore_casa_trasferta ON:  MAE={mae_venue_on:.3f} ({n} punti test)")
    print(f"  fattore_casa_trasferta OFF: MAE={mae_venue_off:.3f}  (variazione se tolto: {pct_venue:+.2f}%)")

    # --- Test 2: grid su half_life, con venue ON (qualunque esito del test 1, testiamo comunque entrambi) ---
    print(f"\n  Grid half_life (venue ON):")
    best_hl_on, best_mae_on = None, None
    for hl in HALF_LIFE_GRID:
        mae, _ = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                                 compute_trend_factor, hl, TREND_INTENSITY, True)
        flag = " <== ATTUALE" if hl == HALF_LIFE_GAMES_ATTUALE else ""
        best_flag = ""
        if best_mae_on is None or mae < best_mae_on:
            best_hl_on, best_mae_on = hl, mae
            best_flag = " <== MIGLIORE FINORA"
        print(f"    half_life={hl:5.1f}  MAE={mae:.3f}{flag}{best_flag}")
    pct_best_on = (best_mae_on - mae_venue_on) / mae_venue_on * 100
    print(f"  MIGLIOR half_life (venue ON): {best_hl_on} (MAE={best_mae_on:.3f}, {pct_best_on:+.2f}% vs attuale)")

    print(f"\n  Grid half_life (venue OFF):")
    best_hl_off, best_mae_off = None, None
    for hl in HALF_LIFE_GRID:
        mae, _ = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                                 compute_trend_factor, hl, TREND_INTENSITY, False)
        best_flag = ""
        if best_mae_off is None or mae < best_mae_off:
            best_hl_off, best_mae_off = hl, mae
            best_flag = " <== MIGLIORE FINORA"
        print(f"    half_life={hl:5.1f}  MAE={mae:.3f}{best_flag}")
    pct_best_off = (best_mae_off - mae_venue_on) / mae_venue_on * 100
    print(f"  MIGLIOR half_life (venue OFF): {best_hl_off} (MAE={best_mae_off:.3f}, {pct_best_off:+.2f}% vs attuale con venue ON)")


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        run_role(ruolo)


if __name__ == '__main__':
    main()
