# -*- coding: utf-8 -*-
"""PASSO 2bis, analisi (12/08/2026, Opus esecutore) -- NON committare.

Legge analisi_manager/dati/_tmp_gk_passo2bis_rows.json (prodotto da
_tmp_gk_passo2bis_opus.py) e risponde alle domande che il test dell'orchestratore
non copriva:
  1. pcs predice il LIVELLO, ma in produzione il portiere si sceglie sul
     punteggio TOTALE. Il granulare (parate) va nel verso opposto?
  2. correlazione PARZIALE dello storico al netto di pcs (la statistica giusta
     per "aggiunge qualcosa sopra pcs?", che la griglia di pesi approssima)
  3. IC a grappolo per SQUADRA, non solo per portiere (pcs e' una variabile di
     squadra: portieri diversi della stessa squadra non sono indipendenti)
  4. quanto dell'effetto e' fra-lega e fra-squadra e quanto resta dentro
  5. pcs e' una probabilita' calibrata? (serve per mapparla a punti senza fudge)
  6. modello candidato completo sulla scala vera dei punti: MAE e correlazione
     contro quello di oggi
"""
import os, json, math, random, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
random.seed(12)
R = json.load(open(os.path.join(ROOT, 'analisi_manager', 'dati', '_tmp_gk_passo2bis_rows.json')))
print('n=%d | portieri %d | squadre %d | leghe %d\n'
      % (len(R), len(set(r['slug'] for r in R)), len(set(r['squadra'] for r in R)),
         len(set(r['lega'] for r in R))))


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def ic(rows, fa, fb, kcl, giri=800):
    byc = collections.defaultdict(list)
    for r in rows:
        byc[r[kcl]].append(r)
    cl = list(byc)
    out = []
    for _ in range(giri):
        s = []
        for _ in range(len(cl)):
            s += byc[random.choice(cl)]
        v = corr([fa(r) for r in s], [fb(r) for r in s])
        if v is not None:
            out.append(v)
    out.sort()
    return out[int(.025 * len(out))], out[int(.975 * len(out))]


def riga(lab, fa, fb, kcl='slug'):
    v = corr([fa(r) for r in R], [fb(r) for r in R])
    lo, hi = ic(R, fa, fb, kcl)
    print('  %-46s %+.4f  IC95(%s) [%+.4f, %+.4f]' % (lab, v, kcl, lo, hi))


g = lambda k: (lambda r: r[k])

print('=== 1. IL BERSAGLIO GIUSTO E IL TOTALE, NON IL LIVELLO ===')
riga('corr(pcs      , level_reale)', g('pcs'), g('lvl_re'))
riga('corr(pcs      , granulare_reale)', g('pcs'), g('gran_re'))
riga('corr(pcs      , PUNTEGGIO TOTALE reale)', g('pcs'), g('tot_re'))
riga('corr(lvl_att  , PUNTEGGIO TOTALE reale)', g('lvl_att'), g('tot_re'))
riga('corr(tot_att  , PUNTEGGIO TOTALE reale)  [modello oggi]', g('tot_att'), g('tot_re'))
riga('corr(pcs      , parate reali)', g('pcs'), g('saves_re'))
riga('corr(pcs      , gol subiti reali)', g('pcs'), g('gc_re'))
print()

print('=== 2. LO STORICO AGGIUNGE QUALCOSA SOPRA pcs? (correlazione parziale) ===')


def residui(rows, ky, kx):
    xs = [r[kx] for r in rows]
    ys = [r[ky] for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return [y - (my + b * (x - mx)) for x, y in zip(xs, ys)]


for tgt in ('lvl_re', 'tot_re'):
    ry = residui(R, tgt, 'pcs')
    rx = residui(R, 'lvl_att', 'pcs')
    for i, r in enumerate(R):
        r['_ry'], r['_rx'] = ry[i], rx[i]
    riga('parziale(lvl_att, %s | pcs)' % tgt, g('_rx'), g('_ry'))
print()

print('=== 3. STESSI NUMERI MA A GRAPPOLO PER SQUADRA (pcs e di squadra) ===')
riga('corr(pcs, level_reale)', g('pcs'), g('lvl_re'), 'squadra')
riga('corr(pcs, tot_reale)', g('pcs'), g('tot_re'), 'squadra')
riga('corr(pcs, level_reale)', g('pcs'), g('lvl_re'), 'lega')
riga('corr(pcs, tot_reale)', g('pcs'), g('tot_re'), 'lega')
print()

print('=== 4. QUANTO E FRA-LEGA / FRA-SQUADRA E QUANTO RESTA DENTRO ===')
for liv in ('lega', 'squadra'):
    m = collections.defaultdict(list)
    for r in R:
        m[r[liv]].append(r)
    med = {k: (sum(x['pcs'] for x in v) / len(v), sum(x['lvl_re'] for x in v) / len(v),
               sum(x['tot_re'] for x in v) / len(v)) for k, v in m.items()}
    dp = [r['pcs'] - med[r[liv]][0] for r in R]
    dl = [r['lvl_re'] - med[r[liv]][1] for r in R]
    dt = [r['tot_re'] - med[r[liv]][2] for r in R]
    quota = 1 - (st.pvariance(dp) / st.pvariance([r['pcs'] for r in R]))
    print('  dentro-%-8s corr(pcs,lvl_re)=%+.4f  corr(pcs,tot_re)=%+.4f   (%.0f%% della varianza di pcs e FRA %s)'
          % (liv, corr(dp, dl), corr(dp, dt), 100 * quota, liv))
print('  NB il dentro-squadra e sporcato dal demeaning (stesso bias meccanico gia visto): leggilo come limite inferiore.')
print()

print('=== 5. pcs E UNA PROBABILITA CALIBRATA? (serve per mapparla a punti) ===')
S = sorted(R, key=lambda r: r['pcs'])
k = len(S) // 6
print('  fascia pcs        n     pcs medio   clean sheet veri   level medio')
for i in range(6):
    b = S[i * k:(i + 1) * k] if i < 5 else S[5 * k:]
    cs = sum(1 for r in b if r['lvl_re'] >= 60) / len(b)
    print('  %.3f-%.3f  %4d   %.3f       %.3f              %.1f'
          % (b[0]['pcs'], b[-1]['pcs'], len(b), sum(r['pcs'] for r in b) / len(b), cs,
             sum(r['lvl_re'] for r in b) / len(b)))
tot_cs = sum(1 for r in R if r['lvl_re'] >= 60) / len(R)
print('  clean sheet veri complessivi %.3f contro pcs medio %.3f  -> scarto %+.3f'
      % (tot_cs, sum(r['pcs'] for r in R) / len(R), tot_cs - sum(r['pcs'] for r in R) / len(R)))
print()

print('=== 6. MODELLO CANDIDATO SULLA SCALA VERA DEI PUNTI (corr + MAE insieme) ===')
lam_neg_med = 0.05
for lab, f in (
    ('OGGI      lvl_att(storico) + gran_att', lambda r: r['tot_att']),
    ('CANDIDATO pcs->level       + gran_att', lambda r: (r['pcs'] * 60 + (1 - r['pcs']) * 35) * (1 - lam_neg_med) + lam_neg_med * 30 + r['gran_att']),
    ('MISTO     0,85 pcs + 0,15 storico     ', lambda r: 0.85 * ((r['pcs'] * 60 + (1 - r['pcs']) * 35) * (1 - lam_neg_med) + lam_neg_med * 30) + 0.15 * r['lvl_att'] + r['gran_att']),
    ('SOLO pcs  (senza granulare)           ', lambda r: r['pcs'] * 60 + (1 - r['pcs']) * 35),
):
    v = corr([f(r) for r in R], [r['tot_re'] for r in R])
    mae = sum(abs(f(r) - r['tot_re']) for r in R) / len(R)
    bias = sum(f(r) - r['tot_re'] for r in R) / len(R)
    lo, hi = ic(R, f, g('tot_re'), 'slug')
    print('  %-38s corr %+.4f [%+.4f,%+.4f] | MAE %.2f | scarto medio %+.2f'
          % (lab, v, lo, hi, mae, bias))
print()

print('=== 6bis. DELTA nello STESSO run (e questo che decide, non i valori assoluti) ===')
f_old = lambda r: r['tot_att']
f_new = lambda r: (r['pcs'] * 60 + (1 - r['pcs']) * 35) * 0.95 + 0.05 * 30 + r['gran_att']
byc = collections.defaultdict(list)
for r in R:
    byc[r['slug']].append(r)
cl = list(byc)
dd = []
for _ in range(800):
    s = []
    for _ in range(len(cl)):
        s += byc[random.choice(cl)]
    a = corr([f_new(r) for r in s], [r['tot_re'] for r in s])
    b = corr([f_old(r) for r in s], [r['tot_re'] for r in s])
    if a is not None and b is not None:
        dd.append(a - b)
dd.sort()
print('  delta corr (candidato - oggi) = %+.4f  IC95 a grappolo [%+.4f, %+.4f]  -> %s'
      % (corr([f_new(r) for r in R], [r['tot_re'] for r in R]) - corr([f_old(r) for r in R], [r['tot_re'] for r in R]),
         dd[int(.025 * len(dd))], dd[int(.975 * len(dd))],
         'ESCLUDE lo zero' if dd[int(.025 * len(dd))] > 0 else 'include lo zero'))

print()
print('=== 7. SIMULAZIONE DI SCELTA: pool finti di 3 portieri della stessa giornata ===')
perdata = collections.defaultdict(list)
for r in R:
    perdata[r['data']].append(r)
random.seed(5)
gua_new = []
gua_old = []
for data, gr in perdata.items():
    if len(gr) < 3:
        continue
    for _ in range(20):
        pool = random.sample(gr, 3)
        media = sum(x['tot_re'] for x in pool) / 3
        gua_new.append(max(pool, key=f_new)['tot_re'] - media)
        gua_old.append(max(pool, key=f_old)['tot_re'] - media)


def mt(v):
    m = sum(v) / len(v)
    s = st.pstdev(v) / math.sqrt(len(v))
    return m, m / s if s else 0.0


mn, tn = mt(gua_new)
mo, to = mt(gua_old)
print('  pool simulati: %d (3 portieri veri della stessa data)' % len(gua_new))
print('  guadagno sul caso, modello OGGI      %+.2f punti (t=%+.1f)' % (mo, to))
print('  guadagno sul caso, modello CANDIDATO %+.2f punti (t=%+.1f)' % (mn, tn))
print('  NB: i pool sono simulati fra portieri di leghe diverse, non sono i pool veri dei manager.')
