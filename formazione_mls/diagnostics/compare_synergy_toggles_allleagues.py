"""
Estensione di compare_synergy_toggles.py (29/07) a TUTTE le leghe con un tipo
di formazione dedicato disponibile in build_formazione_globale.py:
- MLS/K League: tipo In Season (come lo script originale)
- Le altre leghe di ARENA_LEAGUES (belgio, olanda, turchia, portogallo,
  spagna, germania, francia, croazia, scozia): tipo Arena dedicata
  (arena_type(lg), via env ARENA_DEDICATA), unico tipo "single-league" che
  esiste per loro (non hanno In Season, vedi FORMATION_SHAPES).
Nessuna modifica al codice di produzione: solo diagnostica locale, sui dati
gia' su disco.

Uso: python formazione_mls/diagnostics/compare_synergy_toggles_allleagues.py [lega|all]
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
    ("BASELINE (tutto attivo)", {}),
    ("Senza ANTI_SYNERGY_PENALTY", {'ANTI_SYNERGY_PENALTY': 0}),
    ("Senza POSITIVE_SYNERGY_BONUS", {'POSITIVE_SYNERGY_BONUS': 0}),
    ("Senza STACK_GUARD_PENALTY", {'STACK_GUARD_PENALTY': 0}),
]


def generate_for_league(league, overrides, n=6):
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
    saved = {}
    for name, val in overrides.items():
        saved[name] = getattr(bff, name)
        setattr(bff, name, val)
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
        for name, val in saved.items():
            setattr(bff, name, val)
    return results, card_pool


def totals_of(results):
    return [sum(row['atteso'] for _, row, _ in r['formazione']) for r in results if 'error' not in r]


def run_league(league):
    label = LABEL_BY_LEAGUE.get(league, league)
    print(f"\n{'='*78}\nLEGA: {label} ({league})\n{'='*78}")
    try:
        role_data0, role_counts0, _ = None, None, None
    except Exception:
        pass

    all_scenarios = []
    n_valid = None
    for scen_label, overrides in SCENARIOS:
        try:
            results, card_pool = generate_for_league(league, overrides)
        except Exception as e:
            print(f"  ERRORE generazione ({scen_label}): {e}")
            continue
        n_ok = sum(1 for r in results if 'error' not in r)
        if n_ok == 0:
            print(f"  SALTATA: nessuna formazione generabile (dati/candidati insufficienti per {label})")
            return None
        totals = totals_of(results)
        print(f"{scen_label:<30} n_ok={n_ok} totali: {totals}  SOMMA: {sum(totals)}")
        all_scenarios.append((scen_label, sum(totals), n_ok))

    if not all_scenarios:
        return None

    baseline = all_scenarios[0][1]
    row = {'lega': label, 'baseline': baseline}
    for scen_label, tot, n_ok in all_scenarios[1:]:
        row[scen_label] = tot - baseline
    return row


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    leagues = ['mls', 'kleague'] + ARENA_ONLY_LEAGUES if target == 'all' else [target]

    summary = []
    skipped = []
    for lg in leagues:
        row = run_league(lg)
        if row is None:
            skipped.append(lg)
        else:
            summary.append(row)

    print(f"\n\n{'='*78}\nRIEPILOGO (delta vs baseline, positivo = guadagno)\n{'='*78}")
    for row in summary:
        print(row)
    if skipped:
        print(f"\nLeghe saltate (dati/candidati insufficienti): {skipped}")
