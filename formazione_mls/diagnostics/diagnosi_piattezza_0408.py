"""
Diagnosi "piattezza del modello" (04/08/2026).

Nasce dall'osservazione utente: le formazioni generate sembrano tutte
identiche, gli attesi stanno tutti in una banda stretta (GK 47-52, altri
50-60), nessuna differenziazione. Domanda: e' un difetto del modello o la
verita' del dato?

Risposta (vedi HANDOFF_UNIFICATO §5 "Piattezza = verita'"): e' la verita'.
Il modello ORDINA (lift reale +11 pt, boom 22.9% vs 9.9%) ma la varianza
predicibile del voto di singola partita e' ~3%; il resto e' rumore. Non c'e'
modo onesto di allargare i numeri.

Tutto locale, nessun rerun del modello:
- parte A/B/C: usa dati_globali/errore_storico.json (2690 coppie atteso/reale)
- parte D: walk-forward sulle serie storiche dentro i prediction_*.txt (87k oss)

Lancio:  python formazione_mls/diagnostics/diagnosi_piattezza_0408.py
"""
import json, sys, math, glob, random, re
from statistics import mean, pstdev
from datetime import date
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ERR = 'dati_globali/errore_storico.json'


def pear(a, b):
    n = len(a); ma, mb = mean(a), mean(b)
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    return num / (da * db) if da * db else 0.0


def rank(xs):
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs); i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[idx[k]] = avg
        i = j + 1
    return r


def spear(a, b):
    return pear(rank(a), rank(b))


def ols(x, y):
    n = len(x); mx, my = mean(x), mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    b = sxy / sxx if sxx else 0.0
    return my - b * mx, b


def parte_abc():
    d = json.load(open(ERR, encoding='utf-8'))
    roles = {'TUTTI': d}
    for r in d:
        roles.setdefault(r['ruolo'], []).append(r)

    print('=== A. GATE: ordinamento previsto->realizzato ===')
    print(f"{'ruolo':11}{'n':>6}{'sp(att)':>9}{'sp(l10)':>9}{'std_att':>9}"
          f"{'std_real':>10}{'compr':>7}")
    for ro, rows in roles.items():
        m = [(x['atteso'], x['reale'], x['l10']) for x in rows if x['l10'] is not None]
        a = [z[0] for z in m]; r = [z[1] for z in m]; l = [z[2] for z in m]
        sda, sdr = pstdev(a), pstdev(r)
        print(f'{ro:11}{len(m):>6}{spear(a, r):>9.3f}{spear(l, r):>9.3f}'
              f'{sda:>9.2f}{sdr:>10.2f}{sda / sdr:>7.2f}')

    print('\n=== B. LIFT DI SELEZIONE + BOOM per quintile di atteso ===')
    for ro, rows in roles.items():
        rs = sorted(rows, key=lambda x: x['atteso']); n = len(rs); q = n // 5
        lo, hi = rs[:q], rs[-q:]
        print(f'{ro:11} Q1->reale={mean(x["reale"] for x in lo):5.1f} '
              f'(boom {sum(x["reale"]>75 for x in lo)/q*100:4.1f}% '
              f'flop {sum(x["reale"]<25 for x in lo)/q*100:4.1f}%)   '
              f'Q5->reale={mean(x["reale"] for x in hi):5.1f} '
              f'(boom {sum(x["reale"]>75 for x in hi)/q*100:4.1f}% '
              f'flop {sum(x["reale"]<25 for x in hi)/q*100:4.1f}%)')

    print('\n=== C. CALIBRAZIONE reale=a+b*atteso (b<1 => gia sovra-disperso) ===')
    for ro, rows in roles.items():
        a = [x['atteso'] for x in rows]; r = [x['reale'] for x in rows]
        ia, ib = ols(a, r)
        print(f'{ro:11} a={ia:7.2f}  b={ib:5.2f}')

    print('\n=== C2. CORRELAZIONE residui compagni stessa squadra / stessa partita ===')
    gteam = defaultdict(list); gmatch = defaultdict(list)
    for x in d:
        res = x['reale'] - x['atteso']
        gteam[(x['giornata'], x['squadra'])].append(res)
        gmatch[(x['giornata'], frozenset([x['squadra'], x.get('opp_slug')]))].append(res)
    for lab, g in [('stessa-SQUADRA', gteam), ('stessa-PARTITA', gmatch)]:
        pa, pb = [], []
        for res in g.values():
            for i in range(len(res)):
                for j in range(i + 1, len(res)):
                    pa.append(res[i]); pb.append(res[j])
        print(f'  {lab:15} coppie={len(pa):5}  corr={pear(pa, pb):+.3f}')


def parte_d():
    print('\n=== D. Il RANGE per-giocatore e calibrato? (walk-forward locale) ===')
    files = glob.glob('formazione_*/output/*/prediction_*.txt')
    random.seed(1); random.shuffle(files); files = files[:8000]
    hl_re = re.compile(r'half_life=([0-9.]+)')
    ln_re = re.compile(r'^\s*(\d{4}-\d{2}-\d{2})\s*\|.*\|\s*score=([0-9.]+)\s*\|\s*peso')
    role_of = {'gk': 'GK', 'def': 'DEF', 'mid': 'MID', 'fwd': 'FWD'}
    rows = []
    for fp in files:
        try:
            t = open(fp, encoding='utf-8').read()
        except Exception:
            continue
        m = hl_re.search(t)
        if not m:
            continue
        hl = float(m.group(1)); ru = '?'
        for s in fp.replace('\\', '/').split('/'):
            for k, v in role_of.items():
                if s.endswith('_' + k + '_all') or s.endswith('_' + k):
                    ru = v
        hist = []
        for ln in t.splitlines():
            mm = ln_re.match(ln)
            if mm:
                y, mo, dd = map(int, mm.group(1).split('-'))
                hist.append((date(y, mo, dd), float(mm.group(2))))
        if len(hist) < 8:
            continue
        hist.sort()
        for ti in range(5, len(hist)):
            td, ts = hist[ti]
            ws = [0.5 ** ((td - dj).days / hl) for dj, _ in hist[:ti]]
            sc = [sj for _, sj in hist[:ti]]
            W = sum(ws)
            if W <= 0:
                continue
            mu = sum(w * s for w, s in zip(ws, sc)) / W
            var = sum(w * (s - mu) ** 2 for w, s in zip(ws, sc)) / W
            rows.append((math.sqrt(var), abs(ts - mu), 1 if ts > 75 else 0, ru))
    print('  n osservazioni:', len(rows))

    def rep(sub, lab):
        if len(sub) < 200:
            print(f'  {lab}: n={len(sub)} (poche)'); return
        ss = sorted(sub, key=lambda r: r[0]); q = len(ss) // 5
        lo, hi = ss[:q], ss[-q:]
        print(f'  {lab:6} n={len(sub):6} | Q1 pred_std~{mean(r[0] for r in lo):4.1f} '
              f'|err|={mean(r[1] for r in lo):5.1f} boom={mean(r[2] for r in lo)*100:4.1f}%'
              f'  || Q5 pred_std~{mean(r[0] for r in hi):4.1f} '
              f'|err|={mean(r[1] for r in hi):5.1f} boom={mean(r[2] for r in hi)*100:4.1f}%')

    rep(rows, 'TUTTI')
    for R in ['GK', 'DEF', 'MID', 'FWD']:
        rep([r for r in rows if r[3] == R], R)


if __name__ == '__main__':
    parte_abc()
    parte_d()
