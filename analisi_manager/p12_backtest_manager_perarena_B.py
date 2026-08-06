"""Sez.26 -- stesso metodo di p12_backtest_manager_perarena.py (arena
singola, bootstrap cluster-manager), applicato a p12_backtest_manager_
full_B_out.json. Cap 260 e' la candidata UNICA dichiarata: gli altri tipi
sono riportati solo come diagnostica, non decidono."""
import json, random, collections

random.seed(20260806)

d = json.load(open('analisi_manager/p12_backtest_manager_full_B_out.json', encoding='utf-8'))
righe = []
for r in d['risultati_B']:
    man = r['manager']
    for s, ea, eg in zip(r['slots'], r['esito_A'], r['esito_G']):
        righe.append({'manager': man, 'tipo': s['tipo'], 'A': ea['punti'], 'G': eg['punti']})

print(f'n arene totali (gruppo B): {len(righe)}')
manager_list = sorted(set(r['manager'] for r in righe))
print(f'n manager: {len(manager_list)} -- {manager_list}')


def bootstrap_cluster_manager(righe_sub, n_boot=4000):
    by_m = collections.defaultdict(list)
    for r in righe_sub:
        by_m[r['manager']].append(r)
    mgrs = list(by_m)
    n = len(mgrs)
    if n < 2:
        return None
    rnd = random.Random(20260806)
    diffs = []
    for _ in range(n_boot):
        num, den = 0.0, 0
        for _ in range(n):
            m = mgrs[rnd.randrange(n)]
            for r in by_m[m]:
                num += r['G'] - r['A']
                den += 1
        if den:
            diffs.append(num / den)
    diffs.sort()
    return diffs


def riporta(nome, sottoinsieme):
    if not sottoinsieme:
        print(f'{nome}: 0 arene, salto')
        return
    n = len(sottoinsieme)
    d_medio = sum(r['G'] - r['A'] for r in sottoinsieme) / n
    by_m = collections.defaultdict(list)
    for r in sottoinsieme:
        by_m[r['manager']].append(r)
    segno_concorde = 0
    for m, rr in by_m.items():
        dm = sum(x['G'] - x['A'] for x in rr)
        if dm > 0:
            segno_concorde += 1
    diffs = bootstrap_cluster_manager(sottoinsieme)
    n_mgr = len(by_m)
    if diffs is None:
        print(f'{nome}: n_arene={n} n_manager={n_mgr} delta_medio={d_medio:+.3f}  '
              f'bootstrap non calcolabile (<2 manager)  segno_concorde={segno_concorde}/{n_mgr}')
        return
    lo, hi = diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]
    pos = sum(1 for x in diffs if x > 0) / len(diffs)
    print(f'{nome}: n_arene={n} n_manager={n_mgr} delta_medio_per_arena={d_medio:+.3f}  '
          f'IC95=[{lo:+.3f},{hi:+.3f}]  positivo={100*pos:.1f}%  '
          f'manager con delta totale G-A concorde(positivo)={segno_concorde}/{n_mgr}')


print('\n=== CANDIDATA UNICA: CAP 260 ===')
riporta('Cap 260', [r for r in righe if r['tipo'] == 'Cap 260'])

print('\n=== DIAGNOSTICA (NON decide), altri tipi ===')
for tipo in ('Cap 220', 'Uncapped', 'Beginner'):
    riporta(tipo, [r for r in righe if r['tipo'] == tipo])
