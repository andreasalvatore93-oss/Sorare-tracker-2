"""RECENCY vs STORIA LUNGA per il segnale attacco-avversario/GK.

Contestazione dell'utente: usare una media storica a 3 anni per "quanto segna
l'avversario" e' una follia (le squadre ruotano 3-4-5 giocatori a stagione).
Vuole una FINESTRA CORTA: media dei gol fatti dall'avversario nelle sue ultime
N partite (N fino a 20), e vedere se batte la storia lunga.

SCOPE (dichiarato, corretto dall'utente in chat 11/08): NON solo le 266
formazioni del manager crowss, ma l'AGGREGATO di binario 2 (29 manager, le
arene estratte da aprile a oggi) -- lo stesso universo GK su cui girano i test
G-vs-A. Campione = le righe GK di correlazioni_compagni 'arricchite' (899),
squadra/avversario/data/reale gia' risolti.

LETTURA del segnale (dichiarata): (a) att_finestra = media gol FATTI
dall'avversario nelle sue N partite precedenti. Testo anche (b) dif_finestra =
gol SUBITI dalla mia squadra nelle sue N precedenti, e il combinato.

Confronto ONESTO: ogni finestra e la storia lunga si misurano sullo STESSO
sottocampione (righe dove anche N=20 e' calcolabile), altrimenti n diversi
falsano il confronto. Riporto anche ogni N sul suo campione massimo.

Nessuna query di rete (gol gia' estratti). Nessuna modifica alla produzione.
Uso: python analisi_manager/p45_gk_recency_aggregato.py
"""
import os
import sys
import io
import json
import glob
import math
import bisect
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

CORR = 'analisi_manager/dati/correlazioni_compagni_2026-08-13.json'
GOL_FILES = sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2025-26_*.json')) + \
            sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2023_25_*.json'))
NS = [5, 8, 10, 12, 15, 20]
MIN_STORICO = 4          # per la storia lunga (come p44)


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def boot_corr(rows, fsig, B=2000, seed=45):
    g = collections.defaultdict(list)
    for r in rows:
        g[(r['squadra'], r['fixture'])].append(r)
    ch = list(g)
    rnd = random.Random(seed)
    out = []
    for _ in range(B):
        camp = []
        for _ in range(len(ch)):
            camp.extend(g[ch[rnd.randrange(len(ch))]])
        c = pearson([fsig(x) for x in camp], [x['reale'] for x in camp])
        if c is not None:
            out.append(c)
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def main():
    # --- storico gol per squadra, ordinato per data ---
    storia = collections.defaultdict(list)   # squadra -> [(data, subiti, fatti)]
    n_part = 0
    for gf in GOL_FILES:
        for g in json.load(open(gf, encoding='utf-8')).values():
            h, a, d = g.get('home'), g.get('away'), g.get('date')
            hg, ag = g.get('home_goals'), g.get('away_goals')
            if hg is None or ag is None or not h or not a or not d:
                continue
            storia[h].append((d, ag, hg))
            storia[a].append((d, hg, ag))
            n_part += 1
    for v in storia.values():
        v.sort()
    print(f'file gol: {GOL_FILES}')
    print(f'partite unite: {n_part}  squadre con storico: {len(storia)}')

    def prec(squadra, data):
        st = storia.get(squadra, [])
        return st[:bisect.bisect_left(st, (data,))]

    def finestra(squadra, data, n, campo):
        """Media di campo (1=subiti, 2=fatti) sulle ULTIME n partite prima di data."""
        p = prec(squadra, data)
        if len(p) < n:
            return None
        ult = p[-n:]
        return sum(r[campo] for r in ult) / n

    def storia_lunga(squadra, data, campo):
        p = prec(squadra, data)
        if len(p) < MIN_STORICO:
            return None
        return sum(r[campo] for r in p) / len(p)

    # --- campione GK aggregato ---
    d = json.load(open(CORR, encoding='utf-8'))
    gk = [a for a in d['arricchite'] if a.get('ruolo') == 'GK']
    print(f'\nrighe GK aggregato (correlazioni "arricchite"): {len(gk)}')

    # arricchisco ogni riga con tutte le finestre + storia lunga
    righe = []
    for a in gk:
        sq, avv, data = a.get('squadra'), a.get('avversario'), a.get('data')
        if not (sq and avv and data):
            continue
        r = dict(a)
        r['att_lunga'] = storia_lunga(avv, data, 2)
        r['dif_lunga'] = storia_lunga(sq, data, 1)
        for n in NS:
            r[f'att_{n}'] = finestra(avv, data, n, 2)
            r[f'dif_{n}'] = finestra(sq, data, n, 2 if False else 1)  # 1 = subiti
        righe.append(r)

    # --- dump leggibile: 10 righe con le ultime 10 partite dell'avversario ---
    print('\n=== DUMP 10 RIGHE (finestra N=10 sull\'attacco avversario) ===')
    mostrate = 0
    for r in righe:
        if r.get('att_10') is None:
            continue
        avv, data = r['avversario'], r['data']
        ult = prec(avv, data)[-10:]
        gol_list = ', '.join(f'{dt[5:]}:{fat}' for dt, _sub, fat in ult)
        print(f'  {r["slug"][:22]:22s} sq={r["squadra"][:20]:20s} avv={avv[:20]:20s} {data} '
              f'reale={r["reale"]:5.1f} att10={r["att_10"]:.2f}')
        print(f'      ultime 10 (gol fatti avv): {gol_list}')
        mostrate += 1
        if mostrate >= 10:
            break

    seg_att = lambda campo: (lambda r: -r[campo] if r.get(campo) is not None else None)
    seg_dif = lambda campo: (lambda r: -r[campo] if r.get(campo) is not None else None)

    def blocco(titolo, campi):
        print(f'\n=== {titolo} ===')
        print(f'  (segnale invertito: piu\' l\'avversario segna, peggio rende il GK)')
        for etichetta, campo in campi:
            sub = [r for r in righe if r.get(campo) is not None]
            if len(sub) < 100:
                print(f'  {etichetta:26s} n={len(sub):4d}  SOTTO 100, non riportato')
                continue
            c = pearson([-r[campo] for r in sub], [r['reale'] for r in sub])
            lo, hi = boot_corr(sub, lambda x, cc=campo: -x[cc])
            print(f'  {etichetta:26s} n={len(sub):4d}  corr {c:+.3f} [{lo:+.3f},{hi:+.3f}]')

    # (a) attacco avversario: ogni N sul suo campione massimo + storia lunga
    blocco('LETTURA (a) ATTACCO AVVERSARIO -- ogni N sul suo n massimo',
           [(f'ultime {n} partite', f'att_{n}') for n in NS] +
           [('storia lunga (tutta)', 'att_lunga')])

    # confronto ONESTO: stesso sottocampione (dove att_20 e att_lunga esistono)
    common = [r for r in righe if r.get('att_20') is not None and r.get('att_lunga') is not None]
    print(f'\n=== CONFRONTO ONESTO (a): STESSO SOTTOCAMPIONE, n={len(common)} ===')
    print('  (righe dove anche la finestra N=20 e la storia lunga sono calcolabili)')
    if len(common) >= 100:
        for etichetta, campo in [(f'ultime {n}', f'att_{n}') for n in NS] + [('storia lunga', 'att_lunga')]:
            c = pearson([-r[campo] for r in common], [r['reale'] for r in common])
            lo, hi = boot_corr(common, lambda x, cc=campo: -x[cc])
            print(f'  {etichetta:26s} corr {c:+.3f} [{lo:+.3f},{hi:+.3f}]')
    else:
        print('  sottocampione sotto 100, non decide.')

    # (b) difesa propria su finestra corta
    blocco('LETTURA (b) DIFESA PROPRIA (gol subiti) -- ogni N sul suo n massimo',
           [(f'ultime {n} partite', f'dif_{n}') for n in NS] +
           [('storia lunga (tutta)', 'dif_lunga')])

    # (b) combinato media ranghi att+dif su finestra media (N=10) sul sottocampione comune
    cb = [r for r in righe if r.get('att_10') is not None and r.get('dif_10') is not None]
    print(f'\n=== LETTURA (b) COMBINATO att10+dif10 (media ranghi), n={len(cb)} ===')
    if len(cb) >= 100:
        for nome, key in (('att10', 'att_10'), ('dif10', 'dif_10')):
            ordinati = sorted(cb, key=lambda r: -r[key])
            for i, r in enumerate(ordinati):
                r.setdefault('_rk', {})[nome] = i / len(cb)
        f_comb = lambda r: r['_rk']['att10'] + r['_rk']['dif10']
        c = pearson([f_comb(r) for r in cb], [r['reale'] for r in cb])
        lo, hi = boot_corr(cb, f_comb)
        c_att = pearson([-r['att_10'] for r in cb], [r['reale'] for r in cb])
        print(f'  att10 da solo (stesso n)   corr {c_att:+.3f}')
        print(f'  att10 + dif10 (ranghi)     corr {c:+.3f} [{lo:+.3f},{hi:+.3f}]')
    else:
        print('  sotto 100, non riportato')

    out = 'analisi_manager/dati/gk_recency_aggregato_2026-08-11.json'
    json.dump([{k: v for k, v in r.items() if k != '_rk'} for r in righe],
              open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
