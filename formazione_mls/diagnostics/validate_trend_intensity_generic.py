"""
Validate TREND_INTENSITY (slancio/momentum PROPRIO, non dell'avversario) per
DEF/MID/FWD, TUTTE LE LEGHE (29/07, richiesta esplicita utente: stesso test
gia' fatto solo per GK -- validate_gk_trend.py, bocciato li' -- mai riprovato
per gli altri ruoli). Riusa load_players/mae_for_params da
validate_halflife_venue.py (gia' esteso a tutte le leghe), quindi stesso
identico dataset walk-forward.

Uso: python formazione_mls/diagnostics/validate_trend_intensity_generic.py [def|mid|fwd]
"""
import os
import sys
import importlib

sys.path.insert(0, os.getcwd())

from formazione_mls.diagnostics.validate_halflife_venue import (
    load_players, mae_for_params, MIN_HISTORY, MODULE_BY_ROLE,
)

TREND_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5]


def main():
    role = sys.argv[1] if len(sys.argv) > 1 else 'def'
    mod = importlib.import_module(MODULE_BY_ROLE[role])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HL_ATTUALE = mod.HALF_LIFE_GAMES
    TI_ATTUALE = getattr(mod, 'TREND_INTENSITY', 0.0)

    players = load_players(role)
    if not players:
        print(f"{role.upper()}: nessun dato utilizzabile")
        return
    n_test = sum(len(p['scores']) - MIN_HISTORY for p in players)
    print(f"{role.upper()} ({len(players)} giocatori, {n_test} punti test, tutte le leghe) -- "
          f"attuale: half_life={HL_ATTUALE}, trend_intensity={TI_ATTUALE}\n")

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
        pct = (m - mae_attuale) / mae_attuale * 100
        print(f"  trend_intensity={ti:.1f}  MAE={m:.3f} ({pct:+.2f}%){flag}{best_flag}")
    pct_best = (best_mae_ti - mae_attuale) / mae_attuale * 100
    print(f"\nMIGLIORE: trend_intensity={best_ti} (MAE={best_mae_ti:.3f}, {pct_best:+.2f}%)")


if __name__ == '__main__':
    main()
