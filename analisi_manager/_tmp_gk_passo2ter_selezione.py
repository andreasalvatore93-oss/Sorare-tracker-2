# -*- coding: utf-8 -*-
"""PASSO 2ter (12/08/2026, Opus esecutore) -- NON committare.

Tre buchi lasciati aperti dal passo 2bis:
  A. il confronto "oggi" non era la produzione: la produzione il blend pcs
     CE L'HA GIA' (team_cs_weight*GK_TEAM_CS_POINTS*(pcs-baseline) = 22*(pcs-0,28)).
     Il paragone giusto e' contro QUELLO, non contro la formula senza blend.
  B. pcs e' sovradisperso (misurato: si allarga circa il doppio della realta'),
     quindi mapparlo a punti 1:1 esagera. Qui si stima la pendenza vera FUORI
     CAMPIONE (meta' dei portieri per stimare, meta' mai vista per giudicare).
  C. il test di selezione del 2bis ricampionava gli stessi pool 20 volte:
     la t era gonfiata. Qui pool disgiunti + bootstrap a grappolo per DATA,
     e soprattutto il DELTA APPAIATO (stessi pool, due modelli).
"""
import os, json, math, random, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, 'analisi_manager', 'dati', '_tmp_gk_passo2bis_rows.json')))
random.seed(21)


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def ols(rows, ky, kx):
    xs = [r[kx] for r in rows]
    ys = [r[ky] for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - b * mx, b


# --- B. pendenza vera di pcs, stimata FUORI CAMPIONE -------------------------
slugs = sorted(set(r['slug'] for r in R))
random.shuffle(slugs)
meta = set(slugs[:len(slugs) // 2])
FIT = [r for r in R if r['slug'] in meta]
TEST = [r for r in R if r['slug'] not in meta]
a_fit, b_fit = ols(FIT, 'lvl_re', 'pcs')
print('=== B. mappatura pcs -> punti di livello, stimata su META dei portieri ===')
print('  stima (n=%d, %d portieri): level = %.2f + %.2f * pcs' % (len(FIT), len(meta), a_fit, b_fit))
print('  la mappa "ingenua" pcs*60+(1-pcs)*35 ha pendenza 25,0 -> quella vera e %.0f%% di quella'
      % (100 * b_fit / 25.0))
print('  (cioe: pcs si allarga circa il doppio di quanto si allarghi la realta, va ristretto)')
print('  giudizio d\'ora in poi SOLO sui %d punti / %d portieri mai visti\n' % (len(TEST), len(slugs) - len(meta)))

MOD = {
    'A. produzione oggi (storico + blend 22*(pcs-0,28))': lambda r: r['tot_att'] + 22.0 * (r['pcs'] - 0.28),
    'B. produzione senza blend (solo storico)          ': lambda r: r['tot_att'],
    'C. pcs al posto dello storico, mappa ingenua      ': lambda r: r['pcs'] * 60 + (1 - r['pcs']) * 35 + r['gran_att'],
    'D. pcs al posto dello storico, mappa ristretta    ': lambda r: a_fit + b_fit * r['pcs'] + r['gran_att'],
    'E. D + storico come prior debole (0,15)           ': lambda r: 0.85 * (a_fit + b_fit * r['pcs']) + 0.15 * r['lvl_att'] + r['gran_att'],
}

print('=== 1. CORRELAZIONE E MAE SUL PUNTEGGIO TOTALE (solo portieri mai visti) ===')
for lab, f in MOD.items():
    v = corr([f(r) for r in TEST], [r['tot_re'] for r in TEST])
    mae = sum(abs(f(r) - r['tot_re']) for r in TEST) / len(TEST)
    print('  %s corr %+.4f | MAE %.2f | scarto medio %+.2f'
          % (lab, v, mae, sum(f(r) - r['tot_re'] for r in TEST) / len(TEST)))

print()
print('=== 2. DELTA contro la PRODUZIONE VERA, IC a grappolo per portiere ===')
byc = collections.defaultdict(list)
for r in TEST:
    byc[r['slug']].append(r)
cl = list(byc)
base = MOD['A. produzione oggi (storico + blend 22*(pcs-0,28))']
for lab, f in MOD.items():
    if f is base:
        continue
    d0 = corr([f(r) for r in TEST], [r['tot_re'] for r in TEST]) - corr([base(r) for r in TEST], [r['tot_re'] for r in TEST])
    ds = []
    for _ in range(800):
        s = []
        for _ in range(len(cl)):
            s += byc[random.choice(cl)]
        ds.append(corr([f(r) for r in s], [r['tot_re'] for r in s]) - corr([base(r) for r in s], [r['tot_re'] for r in s]))
    ds.sort()
    lo, hi = ds[20], ds[779]
    print('  %s delta corr %+.4f  IC95 [%+.4f, %+.4f]  %s'
          % (lab, d0, lo, hi, 'esclude zero' if lo > 0 or hi < 0 else 'include zero'))

print()
print('=== 3. SELEZIONE: pool DISGIUNTI di 3 portieri veri della stessa data ===')
print('    (delta appaiato: stessi pool per tutti i modelli, IC a grappolo per DATA)')
perdata = collections.defaultdict(list)
for r in TEST:
    perdata[r['data']].append(r)
pools_per_data = collections.defaultdict(list)
for data, gr in perdata.items():
    gr = gr[:]
    random.shuffle(gr)
    for i in range(0, len(gr) - 2, 3):
        pools_per_data[data].append(gr[i:i + 3])
tutte = [p for v in pools_per_data.values() for p in v]
print('  pool disgiunti: %d (su %d date)' % (len(tutte), len(pools_per_data)))


def guadagno(pools, f):
    return [max(p, key=f)['tot_re'] - sum(x['tot_re'] for x in p) / len(p) for p in pools]


ris = {lab: sum(guadagno(tutte, f)) / len(tutte) for lab, f in MOD.items()}
for lab in MOD:
    print('  %s guadagno sul caso %+.2f punti' % (lab, ris[lab]))
date = list(pools_per_data)
print()
print('  delta appaiato contro la produzione vera (A):')
for lab, f in MOD.items():
    if lab.startswith('A.'):
        continue
    d0 = ris[lab] - ris['A. produzione oggi (storico + blend 22*(pcs-0,28))']
    ds = []
    for _ in range(800):
        pp = []
        for _ in range(len(date)):
            pp += pools_per_data[random.choice(date)]
        if not pp:
            continue
        ds.append(sum(guadagno(pp, f)) / len(pp) - sum(guadagno(pp, base)) / len(pp))
    ds.sort()
    lo, hi = ds[int(.025 * len(ds))], ds[int(.975 * len(ds))]
    print('    %s %+.2f punti  IC95 [%+.2f, %+.2f]  %s'
          % (lab, d0, lo, hi, 'esclude zero' if lo > 0 or hi < 0 else 'INCLUDE ZERO'))
