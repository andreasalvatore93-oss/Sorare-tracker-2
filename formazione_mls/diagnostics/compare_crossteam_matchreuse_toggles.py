"""
Test A/B su CROSS_TEAM_PENALTY_BY_PAIR e MATCH_REUSE_PENALTY (build_formazione_finale.py),
mai testati finora (a differenza di ANTI_SYNERGY_PENALTY/POSITIVE_SYNERGY_BONUS/
STACK_GUARD_PENALTY, gia' testati in compare_synergy_toggles_allleagues.py).

- CROSS_TEAM_PENALTY_BY_PAIR: dict -> per disattivarlo, .clear() (stessa infrastruttura
  di SAME_TEAM_SYNERGY_BONUS_BY_PAIR, non si puo' fare override per-nome con setattr
  perche' il codice muta il dict in-place, quindi va svuotato e ripristinato).
- MATCH_REUSE_PENALTY: scalare -> per disattivarlo, settato a 0 (come le altre 3
  gia' testate).

Nessuna modifica al codice di produzione: solo diagnostica locale, sui dati gia' su disco.

Uso: python formazione_mls/diagnostics/compare_crossteam_matchreuse_toggles.py [lega|all]
"""
import os
import sys
import importlib

os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '0')
os.environ.setdefault('ARENA_ALLSTARS_220', '0')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '0')
os.environ.setdefault('ALLSTARS', '0')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

import build_formazione_globale as g0  # solo per leggere ARENA_LEAGUES/arena_type
ARENA_ONLY_LEAGUES = [lg for lg in g0.ARENA_LEAGUES if lg not in ('mls', 'kleague')]

LABEL_BY_LEAGUE = dict(g0.ARENA_LEAGUE_LABELS)

SCENARIOS = [
    ("BASELINE (tutto attivo)", None),
    ("Senza CROSS_TEAM_PENALTY_BY_PAIR", 'cross_team'),
    ("Senza MATCH_REUSE_PENALTY", 'match_reuse'),
]


def generate_for_league(league, mode, n=6):
    """Rigenera da zero le n formazioni per la lega indicata. Per mls/kleague
    usa il tipo In Season, per le altre il tipo Arena dedicata."""
    os.environ['ONLY_LEAGUES'] = league
    is_in_season = league in ('mls', 'kleague')
    if is_in_season:
        os.environ['IN_SEASON'] = f"mls:{n if league=='mls' else 0},kleague:{n if league=='kleague' else 0}"
        os.environ['ARENA_DEDICATA'] = ''
    else:
        os.environ['IN_SEASON'] = 'mls:0,kleague:0'
        os.environ['ARENA_DEDICATA'] = f"{league}:{n}"

    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff

    saved_dict = None
    saved_scalar = None
    if mode == 'cross_team':
        saved_dict = dict(bff.CROSS_TEAM_PENALTY_BY_PAIR)
        bff.CROSS_TEAM_PENALTY_BY_PAIR.clear()
    elif mode == 'match_reuse':
        saved_scalar = bff.MATCH_REUSE_PENALTY
        bff.MATCH_REUSE_PENALTY = 0

    try:
        role_data, role_counts, player_names = g.load_league_role_data()
        role_data = g.filter_by_window(role_data)
        pools = g.build_quality_pools(role_data)
        merged_counts = {}
        for role in g.ROLES:
            acc = {}
            for lg in g.LEAGUES:
                acc.update(role_counts.get(lg, {}).get(role, {}))
            merged_counts[role] = acc
        card_pool = g.bff.CardPool(merged_counts, names=player_names)
        tipo = 'MLS_IN_SEASON' if league == 'mls' else ('KLEAGUE_IN_SEASON' if league == 'kleague' else g.arena_type(league))
        results = g.generate_lineups_for_type(tipo, n, role_data, pools, card_pool)
    finally:
        if mode == 'cross_team':
            bff.CROSS_TEAM_PENALTY_BY_PAIR.clear()
            bff.CROSS_TEAM_PENALTY_BY_PAIR.update(saved_dict)
        elif mode == 'match_reuse':
            bff.MATCH_REUSE_PENALTY = saved_scalar
    return results, card_pool


def totals_of(results):
    return [sum(row['atteso'] for _, row, _ in r['formazione']) for r in results if 'error' not in r]


def run_league(league, n=6):
    label = LABEL_BY_LEAGUE.get(league, league)
    print(f"\n{'='*78}\nLEGA: {label} ({league})\n{'='*78}")

    all_scenarios = []
    for scen_label, mode in SCENARIOS:
        try:
            results, card_pool = generate_for_league(league, mode, n=n)
        except Exception as e:
            print(f"  ERRORE generazione ({scen_label}): {e}")
            continue
        n_ok = sum(1 for r in results if 'error' not in r)
        if n_ok == 0:
            print(f"  SALTATA: nessuna formazione generabile (dati/candidati insufficienti per {label})")
            return None, 0
        totals = totals_of(results)
        print(f"{scen_label:<34} n_ok={n_ok} totali: {totals}  SOMMA: {sum(totals)}")
        all_scenarios.append((scen_label, sum(totals), n_ok))

    if not all_scenarios:
        return None, 0

    n_ok_baseline = all_scenarios[0][2]
    baseline = all_scenarios[0][1]
    row = {'lega': label, 'n_ok': n_ok_baseline, 'baseline': baseline}
    for scen_label, tot, n_ok in all_scenarios[1:]:
        row[scen_label] = tot - baseline
    return row, n_ok_baseline


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    leagues = ['mls', 'kleague'] + ARENA_ONLY_LEAGUES if target == 'all' else [target]

    summary = []
    skipped = []
    for lg in leagues:
        row, n_ok = run_league(lg)
        if row is None:
            skipped.append(lg)
        else:
            summary.append(row)

    print(f"\n\n{'='*78}\nRIEPILOGO (delta vs baseline, positivo = guadagno)\n{'='*78}")
    for row in summary:
        print(row)
    if skipped:
        print(f"\nLeghe saltate (dati/candidati insufficienti): {skipped}")

    print("\nNote: MATCH_REUSE_PENALTY ha effetto solo quando n_ok >= 2 (piu' formazioni")
    print("che possono condividere lo stesso match reale). Leghe con n_ok<2 riportate sopra")
    print("ma il delta per MATCH_REUSE_PENALTY li' e' strutturalmente atteso a 0.")
