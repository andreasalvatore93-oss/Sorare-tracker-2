# -*- coding: utf-8 -*-
"""P11 passo 2 - riverifica indipendenza del boom fra le 5 carte di una
formazione, + verifica della premessa del brief (boom -> podio).
Dataset: analisi_manager/dati/formazioni_*.json (442 formazioni, 8 GW).
Pure python."""
import json, glob, os, math, random, sys, io
_QUI = os.path.dirname(os.path.abspath(__file__))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import defaultdict, Counter

BOOM = 75.0
os.chdir(r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2')

forms = []
for fn in sorted(glob.glob('analisi_manager/dati/formazioni_*.json')):
    gw = os.path.basename(fn)[len('formazioni_'):-len('.json')]
    for f in json.load(open(fn, encoding='utf-8')):
        f['gw'] = gw
        forms.append(f)

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

p('formazioni: %d   card-slot: %d' % (len(forms), sum(len(f['carte']) for f in forms)))
comp = Counter(f['competizione'] for f in forms)
p('per competizione:', dict(comp))

# ---------------------------------------------------------------- premessa
p('\n=== PREMESSA DEL BRIEF: n. carte >=75 -> podio (rank<=3) ===')
tab = defaultdict(lambda: [0, 0])
tab_c260 = defaultdict(lambda: [0, 0])
for f in forms:
    nb = sum(1 for c in f['carte'] if c['reale'] >= BOOM)
    tab[nb][0] += 1
    tab[nb][1] += 1 if f['rank'] <= 3 else 0
    if f['competizione'] == 'Cap 260':
        tab_c260[nb][0] += 1
        tab_c260[nb][1] += 1 if f['rank'] <= 3 else 0
p('  tutte le competizioni:')
for k in sorted(tab):
    n, s = tab[k]
    p('    carte>=75 = %d : n=%3d  podio %5.1f%%' % (k, n, 100.0 * s / n))
p('  solo Cap 260:')
for k in sorted(tab_c260):
    n, s = tab_c260[k]
    p('    carte>=75 = %d : n=%3d  podio %5.1f%%' % (k, n, 100.0 * s / n))

# ---------------------------------------------------------- indipendenza
def pearson(x, y):
    n = len(x)
    if n < 3: return float('nan')
    mx = sum(x) / n; my = sum(y) / n
    sx = sum((a - mx) ** 2 for a in x); sy = sum((b - my) ** 2 for b in y)
    if sx == 0 or sy == 0: return float('nan')
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sx * sy)

def phi(pairs):
    a = [x[0] for x in pairs]; b = [x[1] for x in pairs]
    return pearson(a + b, b + a)

def boot_phi(pairs, B=2000, seed=1):
    rnd = random.Random(seed)
    n = len(pairs); vals = []
    for _ in range(B):
        s = [pairs[rnd.randrange(n)] for _ in range(n)]
        v = phi(s)
        if v == v: vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]

p('\n=== PASSO 2 — INDIPENDENZA DEL BOOM ===')

# (a) coppie DENTRO la stessa formazione (e' cio' che serve a P(>=1 boom))
#     de-dup: una carta-partita (gw,slug) puo' comparire in piu' formazioni
#     di manager diversi -> le coppie si contano una volta sola per
#     (gw, slug_i, slug_j).
seen = set(); pairs_form = []
for f in forms:
    cs = f['carte']
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            k = (f['gw'],) + tuple(sorted((cs[i]['slug'], cs[j]['slug'])))
            if k in seen: continue
            seen.add(k)
            pairs_form.append((1 if cs[i]['reale'] >= BOOM else 0,
                               1 if cs[j]['reale'] >= BOOM else 0))
lo, hi = boot_phi(pairs_form)
p('(a) coppie DENTRO formazione, de-dup (gw,slug_i,slug_j): n=%d  phi=%+.4f  IC95 [%+.4f,%+.4f]'
  % (len(pairs_form), phi(pairs_form), lo, hi))

# (b) coppie stesso team stessa GW (replica del numero +0.012 del riassunto)
uniq = {}
for f in forms:
    for c in f['carte']:
        uniq.setdefault((f['gw'], c['slug']), dict(c, gw=f['gw']))
uc = list(uniq.values())
byteam = defaultdict(list)
for c in uc: byteam[(c['gw'], c['squadra'])].append(c)
pairs_team = []
for k, cs in byteam.items():
    if len(cs) < 2: continue
    bs = [1 if c['reale'] >= BOOM else 0 for c in cs]
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            pairs_team.append((bs[i], bs[j]))
lo, hi = boot_phi(pairs_team)
p('(b) coppie STESSO team/GW: n=%d  phi=%+.4f  IC95 [%+.4f,%+.4f]  (riassunto: +0.012)'
  % (len(pairs_team), phi(pairs_team), lo, hi))

# (c) controllo: coppie stessa GW, squadre diverse
rnd = random.Random(0)
bygw = defaultdict(list)
for c in uc: bygw[c['gw']].append(c)
pairs_ctrl = []
for gw, cs in bygw.items():
    cand = [(cs[i], cs[j]) for i in range(len(cs)) for j in range(i + 1, len(cs))
            if cs[i]['squadra'] != cs[j]['squadra']]
    rnd.shuffle(cand)
    for a, b in cand[:1500]:
        pairs_ctrl.append((1 if a['reale'] >= BOOM else 0, 1 if b['reale'] >= BOOM else 0))
p('(c) controllo stessa GW squadre diverse: n=%d  phi=%+.4f' % (len(pairs_ctrl), phi(pairs_ctrl)))

# (d) distribuzione osservata del n. di boom per formazione vs binomiale
#     con p = tasso marginale (test diretto dell'indipendenza a 5 carte)
nb_obs = Counter(sum(1 for c in f['carte'] if c['reale'] >= BOOM) for f in forms)
pm = sum(1 for f in forms for c in f['carte'] if c['reale'] >= BOOM) / sum(len(f['carte']) for f in forms)
p('\n(d) distribuzione del n. di boom per formazione (5 carte), p marginale=%.4f' % pm)
p('    k   osservato   atteso-se-indipendenti')
chi = 0.0
for k in range(0, 6):
    att = len(forms) * math.comb(5, k) * pm ** k * (1 - pm) ** (5 - k)
    obs = nb_obs.get(k, 0)
    if att > 0: chi += (obs - att) ** 2 / att
    p('    %d   %6d      %8.1f' % (k, obs, att))
p('    chi2 (4 gdl, p stimata) = %.2f' % chi)
p('    P(>=1 boom) osservata %.4f  vs  1-(1-p)^5 = %.4f'
  % (sum(v for k, v in nb_obs.items() if k >= 1) / len(forms), 1 - (1 - pm) ** 5))

open(os.path.join(_QUI, 'p11_passo2_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
