"""Sez.25 -- stessa base dati di sez.24 (analisi_manager/
p12_backtest_manager_full_out.json, gia' con copertura grade 678/678),
ma unita' di misura corretta: l'ARENA singola, non la coppia (manager,GW)
sommata. Il bootstrap di sez.24 raggruppava per coppia, ma dentro una
coppia il numero di arene varia moltissimo (da 1 a molte), quindi la somma
per coppia pesa i manager/GW con piu' arene in modo sproporzionato e
allarga l'IC95 senza che sia il segnale a muoversi.
Bootstrap CLUSTER per MANAGER (non per arena, non per coppia): si
ricampionano i manager con reinserimento, e per ogni manager ricampionato
si prendono TUTTE le sue arene -- le arene dello stesso manager non sono
indipendenti (stesso pool/mazzo), quindi non vanno ricampionate una per
una."""
import json, random, collections

random.seed(20260806)

d = json.load(open('analisi_manager/p12_backtest_manager_full_out.json', encoding='utf-8'))
righe = []
for r in d['risultati_A']:
    man = r['manager']
    for s, ea, eg in zip(r['slots'], r['esito_A'], r['esito_G']):
        righe.append({'manager': man, 'tipo': s['tipo'], 'A': ea['punti'], 'G': eg['punti']})

print(f'n arene totali: {len(righe)}')

by_manager = collections.defaultdict(list)
for r in righe:
    by_manager[r['manager']].append(r)
manager_list = sorted(by_manager)
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
    diffs = bootstrap_cluster_manager(sottoinsieme)
    n_mgr = len(set(r['manager'] for r in sottoinsieme))
    if diffs is None:
        print(f'{nome}: n_arene={n} n_manager={n_mgr} delta_medio={d_medio:+.3f}  '
              f'bootstrap non calcolabile (<2 manager)')
        return
    lo, hi = diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]
    pos = sum(1 for x in diffs if x > 0) / len(diffs)
    print(f'{nome}: n_arene={n} n_manager={n_mgr} delta_medio_per_arena={d_medio:+.3f}  '
          f'IC95=[{lo:+.3f},{hi:+.3f}]  positivo={100*pos:.1f}%')


print('\n=== TUTTE LE ARENE (choice-set del modello: Cap260/Cap220/Uncapped/Beginner) ===')
riporta('TUTTE', righe)

print('\n=== DISAGGREGATO PER TIPO ARENA ===')
for tipo in ('Cap 260', 'Cap 220', 'Uncapped', 'Beginner'):
    sub = [r for r in righe if r['tipo'] == tipo]
    riporta(tipo, sub)
