"""
Grid 2D (half_life x trend_intensity) per DEF/MID/FWD, tutte le leghe (29/07).

Motivazione: oggi abbiamo ritarato half_life e trend_intensity SEPARATAMENTE
(mai in combinazione) -- validate_halflife_venue.py ha trovato il miglior
half_life tenendo fisso il vecchio trend_intensity, poi
validate_trend_intensity_generic.py ha trovato il miglior trend_intensity
tenendo fisso il NUOVO half_life. Possibile interazione tra i due parametri
mai testata: questo script fa la grid 2D completa e confronta il minimo
globale con i valori attualmente in produzione.

Riusa load_players/mae_for_params/MODULE_BY_ROLE da validate_halflife_venue.py
(stesso dataset walk-forward, tutte le leghe via glob).

Uso: python formazione_mls/diagnostics/validate_halflife_trend_grid2d.py [def|mid|fwd|all]
"""
import os
import sys
import importlib

sys.path.insert(0, os.getcwd())

from formazione_mls.diagnostics.validate_halflife_venue import (
    load_players, mae_for_params, MODULE_BY_ROLE,
)

HL_GRID_BY_ROLE = {
    'def': [15.0, 20.0, 25.0, 30.0],
    'mid': [20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0, 90.0],
    'fwd': [20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0, 90.0],
}
TI_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]


def run_role(role):
    mod = importlib.import_module(MODULE_BY_ROLE[role])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HL_PROD = mod.HALF_LIFE_GAMES
    TI_PROD = getattr(mod, 'TREND_INTENSITY', 0.0)

    players = load_players(role)
    if not players:
        print(f"{role.upper()}: nessun dato utilizzabile")
        return None

    def mae(hl, ti):
        m, _ = mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                               compute_trend_factor, hl, ti, True)
        return m

    mae_prod = mae(HL_PROD, TI_PROD)

    print(f"\n{'='*90}\n{role.upper()} ({len(players)} giocatori, tutte le leghe) -- "
          f"PRODUZIONE: half_life={HL_PROD}, trend_intensity={TI_PROD}, MAE={mae_prod:.4f}\n{'='*90}")

    hl_grid = HL_GRID_BY_ROLE[role]
    header = "hl \\ ti  " + "  ".join(f"{ti:6.1f}" for ti in TI_GRID)
    print(header)

    best = None  # (mae, hl, ti)
    grid_results = {}
    for hl in hl_grid:
        row = []
        for ti in TI_GRID:
            m = mae(hl, ti)
            grid_results[(hl, ti)] = m
            row.append(m)
            if best is None or m < best[0]:
                best = (m, hl, ti)
        print(f"{hl:6.1f}   " + "  ".join(f"{m:6.3f}" for m in row))

    best_mae, best_hl, best_ti = best
    pct = (best_mae - mae_prod) / mae_prod * 100
    is_prod = (best_hl == HL_PROD and best_ti == TI_PROD)
    print(f"\nMIGLIORE GRID 2D: half_life={best_hl}, trend_intensity={best_ti}  "
          f"MAE={best_mae:.4f}  ({pct:+.3f}% vs produzione)")
    if is_prod:
        print("  ==> coincide con la combinazione GIA' in produzione: nessuna interazione significativa trovata.")
    else:
        print("  ==> DIVERSA dalla combinazione in produzione.")

    return {
        'role': role,
        'prod': (HL_PROD, TI_PROD, mae_prod),
        'best': (best_hl, best_ti, best_mae),
        'pct': pct,
        'is_prod': is_prod,
    }


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else 'all'
    roles = ['def', 'mid', 'fwd'] if arg == 'all' else [arg]
    results = []
    for role in roles:
        r = run_role(role)
        if r:
            results.append(r)

    print(f"\n\n{'#'*90}\nRIEPILOGO FINALE\n{'#'*90}")
    for r in results:
        hl_p, ti_p, mae_p = r['prod']
        hl_b, ti_b, mae_b = r['best']
        status = "COINCIDE (nessun guadagno)" if r['is_prod'] else f"DIVERSA ({r['pct']:+.3f}%)"
        print(f"{r['role'].upper()}: produzione (hl={hl_p}, ti={ti_p}, MAE={mae_p:.4f}) "
              f"vs grid2D migliore (hl={hl_b}, ti={ti_b}, MAE={mae_b:.4f}) -- {status}")


if __name__ == '__main__':
    main()
