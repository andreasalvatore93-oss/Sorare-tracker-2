"""
Validate GK TREND_INTENSITY (26/07, quarta sessione)

Ultimo pezzo della formula GK mai testato con backtest walk-forward rigoroso.
HALF_LIFE_GAMES e fattore_casa_trasferta sono gia' stati confermati validi
(formazione_mls/diagnostics/validate_halflife_venue.py). fattore_forza_avversario
e Stadio D sono gia' stati rimossi per GK in questa sessione. Resta da verificare
se TREND_INTENSITY=0.7 (valore in produzione per GK) e' ancora ottimale ora che
la formula e' piu' semplice, e se c'e' interazione con half_life.

Riusa load_players/mae_for_params da validate_halflife_venue.py (stesso identico
dataset e metodologia, per fedelta' con i risultati gia' ottenuti).

Uso: python formazione_mls/diagnostics/validate_gk_trend.py
"""
import os
import sys
import importlib
import statistics

sys.path.insert(0, os.getcwd())

from formazione_mls.diagnostics.validate_halflife_venue import (
    load_players, mae_for_params, MIN_HISTORY,
)

TREND_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5]
HALF_LIFE_GRID = [6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]


def main():
    mod = importlib.import_module('formazione_mls.predict.test_gk')
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HL_ATTUALE = mod.HALF_LIFE_GAMES
    TI_ATTUALE = mod.TREND_INTENSITY

    players = load_players('gk')
    if not players:
        print("GK: nessun dato utilizzabile")
        return
    n_test = sum(len(p['scores']) - MIN_HISTORY for p in players)
    print(f"GK ({len(players)} giocatori, {n_test} punti test) -- attuale: half_life={HL_ATTUALE}, trend_intensity={TI_ATTUALE}\n")

    def mae(hl, ti):
        m, _ = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                               compute_trend_factor, hl, ti, True)
        return m

    mae_attuale = mae(HL_ATTUALE, TI_ATTUALE)
    print(f"Baseline (attuale): MAE={mae_attuale:.3f}\n")

    print("Grid TREND_INTENSITY (half_life attuale fisso):")
    best_ti, best_mae_ti = None, None
    for ti in TREND_GRID:
        m = mae(HL_ATTUALE, ti)
        flag = " <== ATTUALE" if ti == TI_ATTUALE else ""
        best_flag = ""
        if best_mae_ti is None or m < best_mae_ti:
            best_ti, best_mae_ti = ti, m
            best_flag = " <== MIGLIORE FINORA"
        print(f"  trend_intensity={ti:4.1f}  MAE={m:.3f}{flag}{best_flag}")
    pct = (best_mae_ti - mae_attuale) / mae_attuale * 100
    print(f"MIGLIORE trend_intensity: {best_ti} (MAE={best_mae_ti:.3f}, {pct:+.2f}% vs attuale)\n")

    print("Grid congiunta half_life x trend_intensity (ricerca ottimo globale):")
    best_combo, best_mae_combo = None, None
    for hl in HALF_LIFE_GRID:
        for ti in TREND_GRID:
            m = mae(hl, ti)
            if best_mae_combo is None or m < best_mae_combo:
                best_combo, best_mae_combo = (hl, ti), m
    pct_combo = (best_mae_combo - mae_attuale) / mae_attuale * 100
    print(f"MIGLIORE combo: half_life={best_combo[0]}, trend_intensity={best_combo[1]} "
          f"(MAE={best_mae_combo:.3f}, {pct_combo:+.2f}% vs attuale)")

    print("\nTest trend OFF (trend_intensity=0, cioe' fattore_trend sempre 1.0) vs attuale:")
    mae_off = mae(HL_ATTUALE, 0.0)
    pct_off = (mae_off - mae_attuale) / mae_attuale * 100
    print(f"  trend OFF: MAE={mae_off:.3f} ({pct_off:+.2f}% vs attuale)")


if __name__ == '__main__':
    main()
