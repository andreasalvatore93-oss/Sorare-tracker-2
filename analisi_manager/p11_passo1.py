# -*- coding: utf-8 -*-
"""P11 passo 1 - forma e calibrazione della stima P(reale>=75 | ruolo, atteso).
Coppie rigenerate col modello di PRODUZIONE (GK_TEAM_CS_WEIGHT=22/35)."""
import os, sys, io, json, glob, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import p11_boom as PB
from collections import defaultdict, Counter

SP = os.path.dirname(os.path.abspath(__file__))
os.chdir(r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2')

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

coppie = PB.carica_coppie(os.path.join(SP, 'p11_coppie_prod.json'))
p('COPPIE (rigenerate 05/08 con GK_TEAM_CS_WEIGHT=22/35): n=%d' % len(coppie))
p('  intervallo date: %s .. %s' % (min(c['data'] for c in coppie), max(c['data'] for c in coppie)))
p('  confronto: dati_globali/taratura_coppie.json in repo = 75.474 coppie (GK weight 0.5, 04/08)')
p('')

# ------------------------------------------------------- forma e adeguatezza
p('=== FORMA: logit P(boom) = a + b * atteso_grezzo, un fit per RUOLO ===')
mod = PB.ModelloBoom(coppie)
p('%-5s %8s %8s %10s %10s %8s %8s' % ('ruolo', 'n', 'boom%', 'a', 'b', 'AUC', 'Brier'))
for r in ('GK', 'DEF', 'MID', 'FWD'):
    righe = [c for c in coppie if c['_cod'] == r]
    y = [1 if c['reale'] >= PB.BOOM else 0 for c in righe]
    ph = [mod.p(r, c['previsto']) for c in righe]
    w = mod.w[r]
    p('%-5s %8d %7.2f%% %10.4f %10.5f %8.3f %8.5f'
      % (r, len(righe), 100 * mod.base[r], w[0], w[1], PB.auc(ph, y), PB.brier(ph, y)))

p('\n--- adeguatezza della forma: decili di atteso, tasso empirico vs logistica ---')
for r in ('GK', 'DEF', 'MID', 'FWD'):
    righe = sorted([c for c in coppie if c['_cod'] == r], key=lambda c: c['previsto'])
    p('  %s (n=%d)' % (r, len(righe)))
    p('    decile  n     atteso medio   boom oss.   boom logistica')
    for k in range(10):
        sl = righe[k * len(righe) // 10:(k + 1) * len(righe) // 10]
        if not sl: continue
        am = sum(c['previsto'] for c in sl) / len(sl)
        bo = sum(1 for c in sl if c['reale'] >= PB.BOOM) / len(sl)
        bp = sum(mod.p(r, c['previsto']) for c in sl) / len(sl)
        p('    %2d    %5d    %7.2f       %6.2f%%      %6.2f%%' % (k + 1, len(sl), am, 100 * bo, 100 * bp))

p('\n--- calibrazione affine (logit(y) su logit(p_stimata)): ben calibrata = (0, 1) ---')
for r in ('GK', 'DEF', 'MID', 'FWD'):
    righe = [c for c in coppie if c['_cod'] == r]
    y = [1 if c['reale'] >= PB.BOOM else 0 for c in righe]
    ph = [mod.p(r, c['previsto']) for c in righe]
    a, b = PB.calibrazione_affine(ph, y)
    p('  %-4s intercetta %+.4f  pendenza %.4f' % (r, a, b))

# ---------------------------------------------- validazione fuori campione
p('\n--- validazione TEMPORALE (fit sul primo 70%% delle date, test sul restante) ---')
cs = sorted(coppie, key=lambda c: c['data'])
k = int(0.7 * len(cs))
tr, te = cs[:k], cs[k:]
m2 = PB.ModelloBoom(tr)
p('  train n=%d (fino a %s)   test n=%d (da %s)' % (len(tr), tr[-1]['data'], len(te), te[0]['data']))
for r in ('GK', 'DEF', 'MID', 'FWD'):
    righe = [c for c in te if c['_cod'] == r]
    if len(righe) < 50: continue
    y = [1 if c['reale'] >= PB.BOOM else 0 for c in righe]
    ph = [m2.p(r, c['previsto']) for c in righe]
    a, b = PB.calibrazione_affine(ph, y)
    p('  %-4s n=%5d  boom oss %5.2f%%  p media %5.2f%%  AUC %.3f  calib (%+.3f, %.3f)'
      % (r, len(righe), 100 * sum(y) / len(y), 100 * sum(ph) / len(ph), PB.auc(ph, y), a, b))

# ------------------------------- cross-check sul dataset manager (442 arene)
p('\n--- cross-check sul dataset ARENE MANAGER (analisi_manager/dati, altro pool) ---')
uniq = {}
forms = []
for fn in sorted(glob.glob('analisi_manager/dati/formazioni_*.json')):
    gw = os.path.basename(fn)[len('formazioni_'):-len('.json')]
    for f in json.load(open(fn, encoding='utf-8')):
        f['gw'] = gw; forms.append(f)
        for c in f['carte']:
            uniq.setdefault((gw, c['slug']), dict(c, gw=gw))
uc = [c for c in uniq.values() if c.get('atteso') is not None]
p('  carte uniche (gw,slug) con atteso: %d   (report PATTERN_ARENE: 1215 tutte / n con atteso)' % len(uc))
y = [1 if c['reale'] >= PB.BOOM else 0 for c in uc]
ph = [mod.p(PB.CODICE[c['ruolo']], c['atteso']) for c in uc]
p('  boom osservato %.2f%%   p media stimata %.2f%%   AUC %.3f   Brier %.5f'
  % (100 * sum(y) / len(y), 100 * sum(ph) / len(ph), PB.auc(ph, y), PB.brier(ph, y)))
a, b = PB.calibrazione_affine(ph, y)
p('  calibrazione affine: intercetta %+.4f  pendenza %.4f' % (a, b))
p('  per ruolo:')
for r in ('GK', 'DEF', 'MID', 'FWD'):
    s = [c for c in uc if PB.CODICE[c['ruolo']] == r]
    if len(s) < 30: continue
    ys = [1 if c['reale'] >= PB.BOOM else 0 for c in s]
    ps = [mod.p(r, c['atteso']) for c in s]
    p('    %-4s n=%4d  boom oss %5.2f%%  p media %5.2f%%  AUC %.3f'
      % (r, len(s), 100 * sum(ys) / len(ys), 100 * sum(ps) / len(ps), PB.auc(ps, ys)))

# --------------------------- PASSO 2 (completamento): indipendenza CONDIZIONATA
p('\n=== PASSO 2b — indipendenza CONDIZIONATA a p_i (residui) ===')
p('  Il phi grezzo dentro formazione e\' gonfiato dall\'eterogeneita\' dei p_i')
p('  (formazioni forti vs deboli). Qui si correla il RESIDUO (boom_i - p_i).')

def pearson(x, y_):
    n = len(x)
    if n < 3: return float('nan')
    mx = sum(x) / n; my = sum(y_) / n
    sx = sum((a - mx) ** 2 for a in x); sy = sum((b - my) ** 2 for b in y_)
    if sx == 0 or sy == 0: return float('nan')
    return sum((a - mx) * (b - my) for a, b in zip(x, y_)) / math.sqrt(sx * sy)

seen = set(); pr = []
for f in forms:
    cs = [c for c in f['carte'] if c.get('atteso') is not None]
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            kk = (f['gw'],) + tuple(sorted((cs[i]['slug'], cs[j]['slug'])))
            if kk in seen: continue
            seen.add(kk)
            a1 = (1 if cs[i]['reale'] >= PB.BOOM else 0) - mod.p(PB.CODICE[cs[i]['ruolo']], cs[i]['atteso'])
            a2 = (1 if cs[j]['reale'] >= PB.BOOM else 0) - mod.p(PB.CODICE[cs[j]['ruolo']], cs[j]['atteso'])
            pr.append((a1, a2))
A = [x[0] for x in pr]; Bv = [x[1] for x in pr]
rho = pearson(A + Bv, Bv + A)
rnd = random.Random(7); vals = []
for _ in range(2000):
    s = [pr[rnd.randrange(len(pr))] for _ in range(len(pr))]
    aa = [x[0] for x in s]; bb = [x[1] for x in s]
    v = pearson(aa + bb, bb + aa)
    if v == v: vals.append(v)
vals.sort()
p('  corr(residuo_i, residuo_j) coppie DENTRO formazione: n=%d  rho=%+.4f  IC95 [%+.4f,%+.4f]'
  % (len(pr), rho, vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]))

# distribuzione del n. di boom per formazione: osservata vs Poisson-binomiale
p('\n  distribuzione n. boom per formazione: osservata vs Poisson-binomiale sui p_i')
oss = Counter(); att = [0.0] * 7; nf = 0
for f in forms:
    cs = [c for c in f['carte'] if c.get('atteso') is not None]
    if len(cs) != 5: continue
    nf += 1
    oss[sum(1 for c in cs if c['reale'] >= PB.BOOM)] += 1
    dist = [1.0]
    for c in cs:
        pi = mod.p(PB.CODICE[c['ruolo']], c['atteso'])
        nd = [0.0] * (len(dist) + 1)
        for kk, v in enumerate(dist):
            nd[kk] += v * (1 - pi); nd[kk + 1] += v * pi
        dist = nd
    for kk, v in enumerate(dist):
        att[kk] += v
p('  formazioni con 5 carte predette: %d' % nf)
p('    k   osservato   atteso (Poisson-binomiale)')
chi = 0.0
for kk in range(6):
    if att[kk] > 0: chi += (oss.get(kk, 0) - att[kk]) ** 2 / att[kk]
    p('    %d   %6d      %8.1f' % (kk, oss.get(kk, 0), att[kk]))
p('    chi2 = %.2f' % chi)
p('    P(>=1 boom): osservata %.4f   modello %.4f'
  % (sum(v for kk, v in oss.items() if kk >= 1) / nf, 1 - att[0] / nf))

open(os.path.join(SP, 'p11_passo1_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
