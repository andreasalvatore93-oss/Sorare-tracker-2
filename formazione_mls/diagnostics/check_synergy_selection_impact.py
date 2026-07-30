"""Test veloce (30/07 sera, sessione quasi finita, budget token limitato):
prima di investire in un Monte Carlo end-to-end, verifica il prerequisito
minimo -- la sinergia same-team (SAME_TEAM_SYNERGY_BONUS_BY_PAIR, Arena/
All Stars) CAMBIA REALMENTE quali giocatori vengono scelti nelle
formazioni prodotte oggi, o e' quasi sempre dominata dalla differenza di
punteggio grezzo (nudge troppo piccolo per contare mai)? Se non cambia mai
nulla, il rischio segnalato ("il MILP ignora la sinergia") e' teorico, non
pratico, e non serve nessun Monte Carlo ulteriore.

Uso: python formazione_mls/diagnostics/check_synergy_selection_impact.py
"""
import os
import sys
import importlib

os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '4')
os.environ.setdefault('ARENA_ALLSTARS_220', '0')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '0')
os.environ.setdefault('ALLSTARS', '4')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('IN_SEASON', 'mls:0,kleague:0')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))


def run_full(disable_synergy):
    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff
    saved = dict(bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR)
    if disable_synergy:
        bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR = {}
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
        results = {}
        for tipo, count in (('ARENA_ALLSTARS_260', 4), ('ALLSTARS', 4)):
            card_pool = bff.CardPool(merged_counts, names=player_names)
            results[tipo] = g.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
        return results
    finally:
        bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR = saved


def slugs_of(results):
    out = {}
    for tipo, formazioni in results.items():
        out[tipo] = []
        for r in formazioni:
            if 'error' in r:
                out[tipo].append(None)
                continue
            out[tipo].append(frozenset(row['slug'] for _, row, _ in r['formazione']))
    return out


def main():
    print("Genero con sinergia ATTIVA (baseline produzione)...")
    baseline = slugs_of(run_full(disable_synergy=False))
    print("Genero con sinergia DISATTIVATA (SAME_TEAM_SYNERGY_BONUS_BY_PAIR = {})...")
    no_synergy = slugs_of(run_full(disable_synergy=True))

    any_diff = False
    for tipo in baseline:
        print(f"\n### {tipo} ###")
        for idx, (a, b) in enumerate(zip(baseline[tipo], no_synergy[tipo]), 1):
            if a is None or b is None:
                print(f"  #{idx}: una delle due varianti non generata, skip")
                continue
            if a == b:
                print(f"  #{idx}: IDENTICA (sinergia ininfluente su questa formazione)")
            else:
                any_diff = True
                print(f"  #{idx}: DIVERSA -- baseline={sorted(a)}")
                print(f"          senza sinergia={sorted(b)}")

    print("\n" + "=" * 70)
    if any_diff:
        print("La sinergia CAMBIA la selezione in almeno una formazione: il rischio "
              "segnalato (MILP che ignora la sinergia) e' concreto, vale la pena "
              "misurare l'impatto reale su P(superare soglia) con un Monte Carlo mirato.")
    else:
        print("La sinergia NON cambia MAI la selezione in questo run: il nudge e' "
              "sempre dominato dalla differenza di punteggio grezzo -- il rischio "
              "segnalato era teorico, non pratico, per questo specifico snapshot di dati.")


if __name__ == '__main__':
    main()
