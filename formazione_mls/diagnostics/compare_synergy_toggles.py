"""
Confronta le 6 formazioni In Season (MLS e K League separatamente) con
ciascuna delle 3 sinergie attive (ANTI_SYNERGY_PENALTY, POSITIVE_SYNERGY_
BONUS, STACK_GUARD_PENALTY) disattivata UNA ALLA VOLTA, tutto in locale sui
dati gia' su disco (nessuna query, nessuna run GitHub) (29/07, richiesta
esplicita utente). Stampa anche la composizione completa (non solo il
totale) sia della baseline sia dello scenario migliore trovato.

Nota: SAME_TEAM_SYNERGY_BONUS_BY_PAIR non e' incluso perche' gia' disattivato
per In Season (variance_mode=False), quindi non c'e' nulla da disattivare li'.

Uso: python formazione_mls/diagnostics/compare_synergy_toggles.py [mls|kleague|all]
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

TIPO_BY_LEAGUE = {'mls': 'MLS_IN_SEASON', 'kleague': 'KLEAGUE_IN_SEASON'}
LABEL_BY_LEAGUE = {'mls': 'MLS', 'kleague': 'K League'}


def generate_for_league(league, overrides):
    """Rigenera da zero (pool pulito) le 6 formazioni In Season per la lega
    indicata, con gli override di sinergia passati. Ritorna la lista di
    risultati (dict con 'formazione': [(slot,row,ctype), ...])."""
    os.environ['ONLY_LEAGUES'] = league
    os.environ['IN_SEASON'] = f"mls:{6 if league=='mls' else 0},kleague:{6 if league=='kleague' else 0}"

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
        card_pool = bff.CardPool(merged_counts, names=player_names)
        tipo = TIPO_BY_LEAGUE[league]
        results = g.generate_lineups_for_type(tipo, 6, role_data, pools, card_pool)
    finally:
        for name, val in saved.items():
            setattr(bff, name, val)
    return results, card_pool


def totals_of(results):
    return [sum(row['atteso'] for _, row, _ in r['formazione']) for r in results if 'error' not in r]


def print_lineups(label, results, card_pool):
    print(f"\n### {label} ###")
    for idx, r in enumerate(results, 1):
        if 'error' in r:
            print(f"  #{idx}: ERRORE - {r['error']}")
            continue
        tot = sum(row['atteso'] for _, row, _ in r['formazione'])
        parts = []
        for slot, row, ctype in r['formazione']:
            nome = card_pool.display_name(row['slug'])
            parts.append(f"{slot}:{nome}({row['atteso']})")
        print(f"  #{idx} [{tot} pt]: " + " | ".join(parts))


SCENARIOS = [
    ("BASELINE (tutto attivo)", {}),
    ("Senza ANTI_SYNERGY_PENALTY", {'ANTI_SYNERGY_PENALTY': 0}),
    ("Senza POSITIVE_SYNERGY_BONUS", {'POSITIVE_SYNERGY_BONUS': 0}),
    ("Senza STACK_GUARD_PENALTY", {'STACK_GUARD_PENALTY': 0}),
    ("Senza NESSUNA sinergia", {'ANTI_SYNERGY_PENALTY': 0, 'POSITIVE_SYNERGY_BONUS': 0, 'STACK_GUARD_PENALTY': 0}),
]


def run_league(league):
    print(f"\n{'='*78}\nLEGA: {LABEL_BY_LEAGUE[league]}\n{'='*78}")
    all_scenarios = []
    baseline_results, baseline_pool = None, None
    for label, overrides in SCENARIOS:
        results, card_pool = generate_for_league(league, overrides)
        totals = totals_of(results)
        print(f"{label:<30} totali: {totals}  SOMMA: {sum(totals)}")
        all_scenarios.append((label, sum(totals), results, card_pool))
        if not overrides:
            baseline_results, baseline_pool = results, card_pool

    best = max(all_scenarios, key=lambda t: t[1])
    print(f"\nMIGLIORE: {best[0]} (SOMMA {best[1]}, baseline {all_scenarios[0][1]}, "
          f"delta {best[1]-all_scenarios[0][1]:+d})")

    print_lineups(f"{LABEL_BY_LEAGUE[league]} -- BASELINE (attuale)", baseline_results, baseline_pool)
    if best[0] != "BASELINE (tutto attivo)":
        print_lineups(f"{LABEL_BY_LEAGUE[league]} -- MIGLIORE ({best[0]})", best[2], best[3])
    else:
        print("(la baseline e' gia' la migliore, nessuna lineup alternativa da mostrare)")


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    leagues = ['mls', 'kleague'] if target == 'all' else [target]
    for lg in leagues:
        run_league(lg)
