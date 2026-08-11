# -*- coding: utf-8 -*-
"""PASSO 2quater (12/08/2026, Opus esecutore) -- NON committare.

UNA sola manopola, nella forma ESATTA della produzione:
    atteso = tot_att + k * (pcs - 0,28)
con k = team_cs_weight * GK_TEAM_CS_POINTS (oggi 0,629*35 = 22,0).

Serve a due cose:
 1. far vedere che i tre criteri del progetto (correlazione, MAE, lift) qui
    NON si muovono nello stesso verso: la correlazione sale monotona con k,
    il MAE peggiora monotono, il lift non distingue niente. Regola del
    progetto -> nessun cambio.
 2. misurare quanto e' instabile la metrica di selezione a questa numerosita':
    stesso modello, stessi dati, cambia solo come si formano i pool.

Richiede analisi_manager/dati/_tmp_gk_passo2bis_rows.json (da
_tmp_gk_passo2bis_opus.py). Fuori campione: stessa meta' di portieri mai
vista del passo 2ter.
"""
import os, json, math, random, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, 'analisi_manager', 'dati', '_tmp_gk_passo2bis_rows.json')))
random.seed(21)
slugs = sorted(set(r['slug'] for r in R))
random.shuffle(slugs)
meta = set(slugs[:len(slugs) // 2])
TEST = [r for r in R if r['slug'] not in meta]


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


perdata = collections.defaultdict(list)
for r in TEST:
    perdata[r['data']].append(r)
pools = {}
for data, gr in perdata.items():
    g = gr[:]
    random.shuffle(g)
    pl = [g[i:i + 3] for i in range(0, len(g) - 2, 3)]
    if pl:
        pools[data] = pl
tutte = [p for v in pools.values() for p in v]
print('fuori campione: %d punti, %d portieri | pool disgiunti %d su %d date\n'
      % (len(TEST), len(set(r['slug'] for r in TEST)), len(tutte), len(pools)))

print('  k      corr        MAE     scarto   selezione(3 GK)')
res = {}
for k in (0, 5, 11, 13.5, 22, 33, 44, 66):
    f = (lambda k: lambda r: r['tot_att'] + k * (r['pcs'] - 0.28))(k)
    v = corr([f(r) for r in TEST], [r['tot_re'] for r in TEST])
    mae = sum(abs(f(r) - r['tot_re']) for r in TEST) / len(TEST)
    bias = sum(f(r) - r['tot_re'] for r in TEST) / len(TEST)
    sel = sum(max(p, key=f)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in tutte) / len(tutte)
    res[k] = (f, v, mae, sel)
    print('  %-5s  %+.4f   %.2f   %+.2f    %+.2f punti%s' % (k, v, mae, bias, sel, '   <- oggi' if k == 22 else ''))

print('\ndelta appaiato di SELEZIONE contro k=22 (produzione), IC95 a grappolo per data:')
date = list(pools)
f22 = res[22][0]
for k in (0, 11, 13.5, 33, 44):
    f = res[k][0]
    ds = []
    for _ in range(800):
        pp = []
        for _ in range(len(date)):
            pp += pools[random.choice(date)]
        a = sum(max(p, key=f)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in pp) / len(pp)
        b = sum(max(p, key=f22)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in pp) / len(pp)
        ds.append(a - b)
    ds.sort()
    print('  k=%-5s %+.2f punti  IC95 [%+.2f, %+.2f]  %s'
          % (k, res[k][3] - res[22][3], ds[20], ds[779],
             'esclude zero' if ds[20] > 0 or ds[779] < 0 else 'include zero'))

print('\n=== quanto vale la metrica di selezione a questa numerosita ===')
vals = []
for s in range(100):
    rnd = random.Random(s)
    pl = []
    for data, gr in perdata.items():
        g = gr[:]
        rnd.shuffle(g)
        pl += [g[i:i + 3] for i in range(0, len(g) - 2, 3)]
    vals.append(sum(max(p, key=f22)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in pl) / len(pl))
print('  stesso modello (k=22), stessi dati, cambia SOLO come si formano i pool:')
print('  100 formazioni -> da %+.2f a %+.2f punti, media %+.2f, sd %.2f' % (min(vals), max(vals), st.mean(vals), st.pstdev(vals)))
print('  -> a 387 pool questa metrica non distingue niente sotto il punto. Non e un giudice.')
