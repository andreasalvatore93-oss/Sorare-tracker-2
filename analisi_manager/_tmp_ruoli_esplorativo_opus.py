# -*- coding: utf-8 -*-
"""ESPLORATIVO RUOLI (12/08/2026, Opus esecutore) -- NON committare, NON produzione.

Stessa scomposizione fatta sul portiere, applicata a DEF/MID/FWD. Zero rete:
legge solo le cache dettaglio gia' in repo e l'aggregato binario2.

Tre blocchi:
  A. ogni pezzo contro il suo bersaglio, per ruolo (walk-forward, IC a grappolo)
  B. UNA manopola: il peso del pezzo decisivo. grezzo = w*level + granulare
     (produzione: w = 1 per tutti e quattro i ruoli -- verificato in
     test_gk.py:1610, test_def.py:1433, test_mid.py:1307, test_mls_fwd_all.py:2042).
     Fuori campione: meta' dei giocatori per stimare, meta' mai vista per
     giudicare. Il MAE e' misurato DOPO aver rifatto la retta di calibrazione
     sulla meta' di stima, cosi' giudica l'ordinamento e non lo spostamento
     di scala.
  C. salute della calibrazione per ruolo sull'archivio (CALIB_PER_RUOLO):
     scarto medio e pendenza vera, con IC a grappolo per giocatore.

Lancio: python analisi_manager/_tmp_ruoli_esplorativo_opus.py   (~4 minuti)
"""
import os, sys, json, glob, math, random, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))
import test_gk as G

random.seed(9)
MINH = 6


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def ic(rows, ka, kb, giri=600):
    byc = collections.defaultdict(list)
    for r in rows:
        byc[r['slug']].append(r)
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


def leggi(path):
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
        out.append(dict(date=gm['date'][:10], score=float(sc), lvl=float(lvl),
                        gran=float(sc) - float(lvl), pos=pos, neg=neg))
    out.sort(key=lambda r: r['date'])
    return out


def costruisci(ruolo):
    rows = []
    for cdir in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*_%s_all' % ruolo, '.cache')):
        for f in glob.glob(os.path.join(cdir, '*_detail_cache.json')):
            ms = leggi(f)
            if len(ms) <= MINH:
                continue
            slug = os.path.basename(f).replace('_detail_cache.json', '')
            for i in range(MINH, len(ms)):
                stt, tg = ms[:i], ms[i]
                w = G.exponential_weights(len(stt), G.HALF_LIFE_GAMES)
                lp = G.weighted_mean([m['pos'] for m in stt], w)
                ln = G.weighted_mean([m['neg'] for m in stt], w)
                rows.append(dict(slug=slug, data=tg['date'],
                                 lvl_att=G.expected_level_from_rates(lp, ln),
                                 gran_att=G.weighted_mean([m['gran'] for m in stt], w),
                                 lvl_re=tg['lvl'], gran_re=tg['gran'], tot_re=tg['score']))
    for r in rows:
        r['tot_att'] = r['lvl_att'] + r['gran_att']
    return rows


DATI = {ruolo: costruisci(ruolo) for ruolo in ('gk', 'def', 'mid', 'fwd')}

print('=== A. OGNI PEZZO CONTRO IL SUO BERSAGLIO (walk-forward, IC a grappolo) ===')
print('  ruolo  n punti  giocatori | decisivo->decisivo      granulare->granulare    totale->totale')
for ruolo, rows in DATI.items():
    a = corr([r['lvl_att'] for r in rows], [r['lvl_re'] for r in rows])
    b = corr([r['gran_att'] for r in rows], [r['gran_re'] for r in rows])
    c = corr([r['tot_att'] for r in rows], [r['tot_re'] for r in rows])
    la, ha = ic(rows, 'lvl_att', 'lvl_re')
    lb, hb = ic(rows, 'gran_att', 'gran_re')
    lc, hc = ic(rows, 'tot_att', 'tot_re')
    print('  %-5s %7d %9d | %+.4f [%+.3f,%+.3f]  %+.4f [%+.3f,%+.3f]  %+.4f [%+.3f,%+.3f]'
          % (ruolo.upper(), len(rows), len(set(r['slug'] for r in rows)), a, la, ha, b, lb, hb, c, lc, hc))

print('\n=== B. UNA MANOPOLA: il peso del pezzo decisivo (produzione w=1) ===')


def ols(rows, f):
    xs = [f(r) for r in rows]
    ys = [r['tot_re'] for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - b * mx, b


for ruolo in ('def', 'mid', 'fwd', 'gk'):
    rows = DATI[ruolo]
    slugs = sorted(set(r['slug'] for r in rows))
    random.shuffle(slugs)
    meta = set(slugs[:len(slugs) // 2])
    FIT = [r for r in rows if r['slug'] in meta]
    TEST = [r for r in rows if r['slug'] not in meta]
    perdata = collections.defaultdict(list)
    for r in TEST:
        perdata[r['data']].append(r)
    pools = {}
    for d, gr in perdata.items():
        g = gr[:]
        random.shuffle(g)
        pl = [g[i:i + 3] for i in range(0, len(g) - 2, 3)]
        if pl:
            pools[d] = pl
    tutte = [p for v in pools.values() for p in v]
    print('  --- %s: %d punti fuori campione, %d giocatori, %d pool disgiunti'
          % (ruolo.upper(), len(TEST), len(slugs) - len(meta), len(tutte)))
    print('     w      corr       MAE(ricalibrato)  selezione(3)')
    fs = {}
    for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.3):
        f = (lambda w: lambda r: w * r['lvl_att'] + r['gran_att'])(w)
        a, b = ols(FIT, f)
        c = corr([f(r) for r in TEST], [r['tot_re'] for r in TEST])
        mae = sum(abs(a + b * f(r) - r['tot_re']) for r in TEST) / len(TEST)
        sel = sum(max(p, key=f)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in tutte) / len(tutte)
        fs[w] = (f, sel)
        print('     %-5s  %+.4f   %.2f             %+.2f%s' % (w, c, mae, sel, '   <- produzione' if w == 1.0 else ''))
    date = list(pools)
    f1 = fs[1.0][0]
    for w in (0.0, 0.4):
        f = fs[w][0]
        ds = []
        for _ in range(500):
            pp = []
            for _ in range(len(date)):
                pp += pools[random.choice(date)]
            ds.append(sum(max(p, key=f)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in pp) / len(pp)
                      - sum(max(p, key=f1)['tot_re'] - sum(x['tot_re'] for x in p) / 3 for p in pp) / len(pp))
        ds.sort()
        print('     delta selezione w=%s contro w=1: %+.2f punti IC95 [%+.2f, %+.2f] %s'
              % (w, fs[w][1] - fs[1.0][1], ds[12], ds[487],
                 'esclude zero' if ds[12] > 0 or ds[487] < 0 else 'include zero'))

print('\n=== C. SALUTE DI CALIB_PER_RUOLO sull archivio (dedup + IC a grappolo) ===')
d = json.load(open(os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_pool_rows.json'), encoding='utf-8'))
print('  ruolo | scarto medio (atteso-reale) IC95      | pendenza vera di reale su atteso (ideale 1,00)')
for cod in ('GK', 'DEF', 'MID', 'FWD'):
    r = [x for x in d if x['codice'] == cod and x.get('_cal') is not None]
    g = collections.defaultdict(list)
    for x in r:
        g[(x['slug'], x['fixture'])].append(x)
    byp = collections.defaultdict(list)
    for k, v in g.items():
        byp[k[0]].append((sum(z['_cal'] for z in v) / len(v), v[0]['reale']))

    def stima(pairs):
        a = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        mx, my = sum(a) / len(a), sum(y) / len(y)
        sxx = sum((x - mx) ** 2 for x in a)
        return (sum((x - mx) * (t - my) for x, t in zip(a, y)) / sxx if sxx else 0.0), mx - my

    allr = [t for v in byp.values() for t in v]
    b0, bias0 = stima(allr)
    slugs = list(byp)
    bs, bi = [], []
    for _ in range(800):
        s = []
        for _ in range(len(slugs)):
            s += byp[random.choice(slugs)]
        v, w = stima(s)
        bs.append(v)
        bi.append(w)
    bs.sort()
    bi.sort()
    print('  %-4s  | %+.2f punti [%+.2f, %+.2f] %-12s | %.2f [%.2f, %.2f]'
          % (cod, bias0, bi[20], bi[779], '(esclude zero)' if bi[779] < 0 or bi[20] > 0 else '(include zero)',
             b0, bs[20], bs[779]))
