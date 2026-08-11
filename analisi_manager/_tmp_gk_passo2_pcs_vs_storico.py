# -*- coding: utf-8 -*-
"""PASSO 2 (12/08/2026, orchestratore) -- test decisivo proposto da Opus:
corr(pcs_squadra, level_reale) vs corr(level_atteso_storico, level_reale).
Stesso campione indipendente e stessa metodologia (dedup per costruzione:
walk-forward per portiere, IC a grappolo) di analisi_manager/_tmp_gk_diagnosi_opus.py,
esteso con squadra/avversario per calcolare pcs via backtest_arene_previsioni._pcs_squadra.
Zero rete, zero modifica alla produzione."""
import os, sys, json, glob, math, random, collections, datetime

ROOT = os.path.abspath('.')
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))
sys.path.insert(0, ROOT)
import test_gk as G
import backtest_arene_previsioni as P

random.seed(12)
MINH = 6


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def ic_grappolo(rows, ka, kb, kcluster, giri=1000):
    byc = collections.defaultdict(list)
    for r in rows:
        byc[r[kcluster]].append(r)
    cl = list(byc)
    out = []
    for _ in range(giri):
        s = []
        for _ in range(len(cl)):
            s += byc[random.choice(cl)]
        v = corr([r[ka] for r in s], [r[kb] for r in s])
        if v is not None:
            out.append(v)
    out.sort()
    return out[int(.025 * len(out))], out[int(.975 * len(out))]


def leggi_dettaglio(path):
    try:
        dd = json.load(open(path, encoding='utf-8'))
    except Exception:
        return []
    out = []
    for v in dd.values():
        ds = v.get('detailedScore') or []
        if not ds or v.get('scoreStatus') != 'FINAL':
            continue
        gm = v.get('anyGame') or {}
        if not gm.get('date'):
            continue
        pos = neg = 0.0
        lvl = None
        for e in ds:
            c, s, sv = e.get('category'), e.get('stat'), e.get('statValue') or 0.0
            if c == 'POSITIVE_DECISIVE_STAT':
                pos += sv
            elif c == 'NEGATIVE_DECISIVE_STAT':
                neg += sv
            elif s == 'level_score':
                lvl = e.get('totalScore') or 0.0
        sc = v.get('score')
        if lvl is None or sc is None:
            continue
        home = (gm.get('homeTeam') or {}).get('slug')
        away = (gm.get('awayTeam') or {}).get('slug')
        out.append(dict(date=gm['date'][:10], score=float(sc), lvl=float(lvl),
                        gran=float(sc) - float(lvl), pos=pos, neg=neg,
                        home=home, away=away))
    out.sort(key=lambda r: r['date'])
    return out


print('Carico le cache dettaglio GK (stesse di Opus)...')
PLAYERS = {}
for cdir in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*_gk_all', '.cache')):
    lega = cdir.split(os.sep)[-4].replace('formazione_', '')
    for f in glob.glob(os.path.join(cdir, '*_detail_cache.json')):
        ms = leggi_dettaglio(f)
        if ms:
            PLAYERS[(lega, os.path.basename(f).replace('_detail_cache.json', ''))] = ms
print('  %d portieri caricati\n' % len(PLAYERS))


def squadra_da_storico(recenti):
    conteggi = {}
    for m in recenti:
        for t in (m['home'], m['away']):
            if t:
                conteggi[t] = conteggi.get(t, 0) + 1
    return max(conteggi, key=conteggi.get) if conteggi else None


rows = []
n_pcs_none = 0
for (lega, slug), ms in PLAYERS.items():
    if len(ms) <= MINH:
        continue
    for i in range(MINH, len(ms)):
        st, tg = ms[:i], ms[i]
        w = G.exponential_weights(len(st), G.HALF_LIFE_GAMES)
        lp = G.weighted_mean([m['pos'] for m in st], w)
        ln = G.weighted_mean([m['neg'] for m in st], w)
        la = G.expected_level_from_rates(lp, ln)

        recenti = st[-5:] if len(st) >= 5 else st
        squadra = squadra_da_storico(recenti)
        home, away = tg['home'], tg['away']
        if not squadra or not home or not away or squadra not in (home, away):
            continue
        opp = away if squadra == home else home
        casa = (squadra == home)
        try:
            cutoff = datetime.datetime.strptime(tg['date'], '%Y-%m-%d')
        except ValueError:
            continue
        ctx = {'squadra': squadra, 'opp_slug': opp, 'cutoff': cutoff, 'casa': casa}
        pcs = P._pcs_squadra(ctx)
        if pcs is None:
            n_pcs_none += 1
            continue
        rows.append(dict(slug=slug, lega=lega, lvl_att=la, lvl_re=tg['lvl'], pcs=pcs))

print('n righe con pcs valido:', len(rows), ' (scartate per pcs None:', n_pcs_none, ')')
print('n portieri distinti:', len(set(r['slug'] for r in rows)))
print()

for a, b in (('lvl_att', 'lvl_re'), ('pcs', 'lvl_re')):
    lo, hi = ic_grappolo(rows, a, b, 'slug')
    print('corr(%-8s, %-7s) = %+.4f  IC95 a grappolo per portiere [%+.4f, %+.4f]  n=%d'
          % (a, b, corr([r[a] for r in rows], [r[b] for r in rows]), lo, hi, len(rows)))

# combinazione semplice: media dei due z-standardizzati, per vedere se battono il singolo
import statistics as st
def z(xs):
    m = sum(xs)/len(xs); s = st.pstdev(xs) or 1.0
    return [(x-m)/s for x in xs]
za = z([r['lvl_att'] for r in rows])
zp = z([r['pcs'] for r in rows])
comb = [(a+p)/2 for a, p in zip(za, zp)]
rows_c = [dict(slug=r['slug'], comb=c, lvl_re=r['lvl_re']) for r, c in zip(rows, comb)]
lo, hi = ic_grappolo(rows_c, 'comb', 'lvl_re', 'slug')
print('corr(media(z_lvl_att,z_pcs), lvl_re) = %+.4f  IC95 [%+.4f, %+.4f]'
      % (corr([r['comb'] for r in rows_c], [r['lvl_re'] for r in rows_c]), lo, hi))

print('\ndump 8 casi:')
for r in rows[::max(1, len(rows)//8)][:8]:
    print('  %-22s lvl_att=%.2f pcs=%.3f lvl_re=%.1f' % (r['slug'][:22], r['lvl_att'], r['pcs'], r['lvl_re']))
