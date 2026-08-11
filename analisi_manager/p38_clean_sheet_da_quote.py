"""Clean sheet del portiere: e' prevedibile con le quote 1X2 GIA' IN CACHE?

Seguito del filone correlazioni (RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt).
Trovato oggi: il punteggio del portiere e' quasi tutto clean sheet (72,4 con,
37,9 senza, nel 29,3% dei casi) e l'atteso di produzione e' identico nei due
casi (48,8 / 48,7): il modello prevede il clean sheet a zero.

Prima di chiedere qualunque estrazione: le quote 1X2 storiche sono GIA' in
repo, dati_globali/odds_1x2_index.json (7.184 partite, 19/11/2025-07/08/2026),
lette in produzione da backtest_arene_previsioni._p_own_opp_odds. Zero rete.

Nessuna modifica alla produzione. Solo misura.
Uso: python analisi_manager/p38_clean_sheet_da_quote.py
"""
import os
import sys
import io
import json
import math
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CS_SOGLIA = 60.0     # level_score GK: 35 senza clean sheet, 60 con (gia' in repo)


def carica_quote():
    return json.load(open(os.path.join('dati_globali', 'odds_1x2_index.json'),
                          encoding='utf-8'))


def quote_per(idx, squadra, avversario, data):
    riga = idx.get('|'.join(sorted([squadra, avversario]) + [data]))
    if riga is None:
        return None
    if riga['home'] == squadra:
        p_own, p_opp = riga['p_home'], riga['p_away']
    elif riga['away'] == squadra:
        p_own, p_opp = riga['p_away'], riga['p_home']
    else:
        return None
    return p_own, p_opp, 1.0 - p_own - p_opp


def auc(coppie):
    """P(segnale piu' alto per un caso positivo che per uno negativo). 0,5 = caso."""
    pos = [p for y, p in coppie if y]
    neg = [p for y, p in coppie if not y]
    if not pos or not neg:
        return None
    pos.sort(); neg.sort()
    import bisect
    tot = 0.0
    for a in pos:
        tot += bisect.bisect_left(neg, a) + 0.5 * (bisect.bisect_right(neg, a) - bisect.bisect_left(neg, a))
    return tot / (len(pos) * len(neg))


def boot_auc(coppie, cluster, B=1000, seed=20260813):
    rnd = random.Random(seed)
    g = collections.defaultdict(list)
    for c, k in zip(coppie, cluster):
        g[k].append(c)
    ch = list(g)
    out = []
    for _ in range(B):
        camp = []
        for _ in range(len(ch)):
            camp.extend(g[ch[rnd.randrange(len(ch))]])
        a = auc(camp)
        if a is not None:
            out.append(a)
    if not out:
        return None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def spear(coppie):
    n = len(coppie)
    def rank(vals):
        order = sorted(range(n), key=lambda i: vals[i]); rk = [0]*n; i = 0
        while i < n:
            j = i
            while j+1 < n and vals[order[j+1]] == vals[order[i]]: j += 1
            avg = (i+j)/2 + 1
            for t in range(i, j+1): rk[order[t]] = avg
            i = j+1
        return rk
    a = rank([c[0] for c in coppie]); b = rank([c[1] for c in coppie])
    ma = sum(a)/n; mb = sum(b)/n
    sab = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    saa = sum((x-ma)**2 for x in a); sbb = sum((y-mb)**2 for y in b)
    return sab/math.sqrt(saa*sbb) if saa and sbb else None


def main():
    idx = carica_quote()
    date = [k.split('|')[-1] for k in idx]
    print(f'quote 1X2 gia in repo: {len(idx)} partite, dal {min(date)} al {max(date)}')

    d = json.load(open('analisi_manager/dati/correlazioni_compagni_2026-08-13.json',
                       encoding='utf-8'))
    gk = [a for a in d['arricchite'] if a['ruolo'] == 'GK']
    print(f'portieri (giocatore, giornata) nel campione: {len(gk)}')

    righe = []
    for a in gk:
        q = quote_per(idx, a['squadra'], a['avversario'], a['data'])
        if q is None:
            continue
        p_own, p_opp, p_draw = q
        righe.append(dict(a, p_own=p_own, p_opp=p_opp, p_draw=p_draw,
                          cs=a['reale'] >= CS_SOGLIA))
    print(f'  con quote disponibili: {len(righe)} ({len(righe)/max(len(gk),1):.1%})')
    if len(righe) < 50:
        print('  campione insufficiente, mi fermo')
        return
    print(f'  quota di clean sheet nel campione: '
          f'{sum(r["cs"] for r in righe)/len(righe):.1%}')

    cluster = [(r['squadra'], r['fixture']) for r in righe]
    print()
    print('=== 1. QUANTO BENE SI PREVEDE IL CLEAN SHEET (AUC, 0,50 = a caso) ===')
    segnali = [
        ('atteso di produzione (oggi)', lambda r: r['atteso']),
        ('p vittoria propria', lambda r: r['p_own']),
        ('p vittoria avversario (invertita)', lambda r: -r['p_opp']),
        ('p_own meno p_opp (favorito)', lambda r: r['p_own'] - r['p_opp']),
        ('p_own + p_draw (non perdere)', lambda r: r['p_own'] + r['p_draw']),
        ('giocare in casa', lambda r: 1.0 if r['in_casa'] else 0.0),
    ]
    for nome, f in segnali:
        cop = [(r['cs'], f(r)) for r in righe]
        a = auc(cop)
        ic = boot_auc(cop, cluster)
        s = f'IC95% [{ic[0]:.3f}, {ic[1]:.3f}]' if ic else 'IC n/d'
        print(f'  {nome:36s} AUC {a:.3f}  {s}')

    print()
    print('=== 2. E ORDINA IL PUNTEGGIO DEL PORTIERE? (Spearman col reale) ===')
    for nome, f in segnali:
        r_ = spear([(f(x), x['reale']) for x in righe])
        print(f'  {nome:36s} Spearman {r_:+.3f}')

    print()
    print('=== 3. LIFT DI SELEZIONE: quinto migliore contro quinto peggiore ===')
    print('    (punteggio reale medio del portiere, n per quintile)')
    for nome, f in segnali:
        rs = sorted(righe, key=f)
        q = len(rs)//5
        bot = sum(x['reale'] for x in rs[:q])/q
        top = sum(x['reale'] for x in rs[-q:])/q
        print(f'  {nome:36s} basso {bot:5.1f}  alto {top:5.1f}  delta {top-bot:+6.2f}  (n {q} per lato)')

    print()
    print('=== 4. IL CLEAN SHEET PER FASCIA DI QUOTA (controllo di sanita) ===')
    rs = sorted(righe, key=lambda r: r['p_own'] - r['p_opp'])
    n = len(rs); q = n//5
    for i in range(5):
        p = rs[i*q:(i+1)*q] if i < 4 else rs[4*q:]
        print(f'  quinto {i+1}: favorito medio {sum(x["p_own"]-x["p_opp"] for x in p)/len(p):+.3f}  '
              f'clean sheet {sum(x["cs"] for x in p)/len(p):5.1%}  '
              f'punteggio GK medio {sum(x["reale"] for x in p)/len(p):5.1f}  n={len(p)}')

    out = 'analisi_manager/dati/clean_sheet_quote_2026-08-13.json'
    json.dump(righe, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
