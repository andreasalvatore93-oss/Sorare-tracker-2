"""PASSO 5b: effetto a valle su GW3 con le soglie ricalcolate coi PREMI VERI
(p27_premi_veri_soglie.py). Stesso pattern di p24/p26: override IN MEMORIA,
mai scritto nel file."""
import os
import sys
import collections

os.environ.setdefault('GAMEWEEK', '3')
sys.path.insert(0, 'generatore_formazioni')
import build_formazione_globale as bfg


def costruisci_pool_fresco():
    role_data, role_counts, player_names = bfg.load_league_role_data()
    role_data = bfg.filter_by_window(role_data)
    pools = bfg.build_quality_pools(role_data)
    merged_counts = {}
    for role in bfg.ROLES:
        acc = {}
        for lg in bfg.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged_counts[role] = acc
    card_pool = bfg.bff.CardPool(merged_counts, names=player_names)
    return role_data, pools, card_pool


tipi = [t for t in bfg.PRIORITY_ORDER if bfg._is_arena_type(t)]

print('--- baseline (soglie di produzione, invariate) ---')
role_data, pools, card_pool = costruisci_pool_fresco()
scelte_base = bfg.genera_arene_efficienti(tipi, 50, role_data, pools, card_pool)
mix_base = collections.Counter(r['tipo'] for r in scelte_base)
print(f'n arene: {len(scelte_base)}  mix: {dict(mix_base)}')

NUOVI_PAREGGIO = {'ARENA_ALLSTARS_260': 264.5, 'ARENA_ALLSTARS_220': 247.1,
                  'ARENA_ALLSTARS_UNCAPPED': 279.6}
NUOVI_GUADAGNO = {'ARENA_ALLSTARS_260': 6.96, 'ARENA_ALLSTARS_220': 5.11,
                  'ARENA_ALLSTARS_UNCAPPED': 5.88}

orig_p = dict(bfg.PAREGGIO_ARENA)
orig_g = dict(bfg.GUADAGNO_PER_PUNTO)
bfg.PAREGGIO_ARENA.update(NUOVI_PAREGGIO)
bfg.GUADAGNO_PER_PUNTO.update(NUOVI_GUADAGNO)
try:
    role_data2, pools2, card_pool2 = costruisci_pool_fresco()
    scelte_nuovo = bfg.genera_arene_efficienti(tipi, 50, role_data2, pools2, card_pool2)
finally:
    bfg.PAREGGIO_ARENA.clear(); bfg.PAREGGIO_ARENA.update(orig_p)
    bfg.GUADAGNO_PER_PUNTO.clear(); bfg.GUADAGNO_PER_PUNTO.update(orig_g)

mix_nuovo = collections.Counter(r['tipo'] for r in scelte_nuovo)
print('\n--- CON SOGLIE PREMI VERI (§11 handoff) ---')
print(f'n arene: {len(scelte_nuovo)}  mix: {dict(mix_nuovo)}')
for r in scelte_nuovo:
    print(' ', r['tipo'], 'atteso', round(r.get('atteso', 0), 1))
