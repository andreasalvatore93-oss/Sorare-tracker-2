"""Refit di CALIB_PER_RUOLO su dati reali dei manager (13/08/2026).

Priorita' #1 di docs/handoff/HANDOFF_ORCHESTRATORE_NUOVO_2026-08-13.txt:
le costanti attuali sottostimano i ruoli di movimento di ~2,4 punti/carta.

Campione: archivio_ufficiale/aggregato/binario2_pool_rows.json (le carte
REALMENTE possedute dai manager, non un pool generico), dedup per
(slug, fixture) per non contare due volte lo stesso giocatore-partita
posseduto da piu' manager.

atteso_raw (pre-calibrazione) NON e' salvato su disco: si recupera invertendo
calibra() con le costanti ATTUALI di produzione (_cal = a + b*atteso_raw,
arrotondato a 1 decimale) invece di richiamare P.score_atteso() (stessa
cache, stesso risultato, zero query di rete -- REGOLA SUPREMA risparmio
token).

Split PRIMA di guardare i numeri: le 22 fixture ordinate per data, le prime
11 (apr-giu 2026) train, le ultime 11 (giu-ago 2026) test. Cronologico, non
casuale: coerente con l'uso reale (si calibra su storia, si applica al
futuro).

Uso: python analisi_manager/p27_refit_calib_per_ruolo.py
"""
import os
import sys
import json
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p24_binario2_ga as G
import generatore_formazioni.build_formazione_globale as BFG

CALIB_ATTUALE = BFG.CALIB_PER_RUOLO
POOL_PATH = os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_pool_rows.json')


def carica_dedup():
    rows = json.load(open(POOL_PATH, encoding='utf-8'))
    visti = {}
    for r in rows:
        k = (r['slug'], r['fixture'])
        if k not in visti:
            visti[k] = r
    return list(visti.values())


def recupera_atteso_raw(row):
    a, b = CALIB_ATTUALE[row['codice']]
    return (row['_cal'] - a) / b


def split_train_test(rows):
    fixtures = sorted(set(r['fixture'] for r in rows), key=G.fine_giornata_da_slug)
    meta = len(fixtures) // 2
    train_fx = set(fixtures[:meta])
    test_fx = set(fixtures[meta:])
    train = [r for r in rows if r['fixture'] in train_fx]
    test = [r for r in rows if r['fixture'] in test_fx]
    return train, test, fixtures[:meta], fixtures[meta:]


def ols(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sxy / sxx
    a = my - b * mx
    return a, b


def correlazione(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float('nan')
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def mae(pred, ys):
    return sum(abs(p - y) for p, y in zip(pred, ys)) / len(ys)


def lift_top_decile(atteso, reale):
    """Punteggio medio reale del decile con atteso piu' alto vs media generale."""
    n = len(atteso)
    idx = sorted(range(n), key=lambda i: -atteso[i])
    k = max(1, n // 10)
    top = [reale[i] for i in idx[:k]]
    return sum(top) / len(top) - sum(reale) / n


def main():
    rows = carica_dedup()
    for r in rows:
        r['atteso_raw'] = recupera_atteso_raw(r)

    train, test, fx_train, fx_test = split_train_test(rows)
    print(f'fixture train ({len(fx_train)}): {fx_train[0]} .. {fx_train[-1]}')
    print(f'fixture test  ({len(fx_test)}): {fx_test[0]} .. {fx_test[-1]}')
    print(f'righe totali dedup: {len(rows)}  train: {len(train)}  test: {len(test)}')
    print()

    per_ruolo_train = collections.defaultdict(list)
    per_ruolo_test = collections.defaultdict(list)
    for r in train:
        per_ruolo_train[r['codice']].append(r)
    for r in test:
        per_ruolo_test[r['codice']].append(r)

    print(f"{'ruolo':5} {'n_tr':>5} {'n_te':>5}  {'a_vecchia':>9} {'b_vecchia':>9}  {'a_nuova':>9} {'b_nuova':>9}  "
          f"{'corr_vecchia':>12} {'corr_nuova':>10}  {'mae_vecchia':>11} {'mae_nuova':>10}  "
          f"{'lift_vecchia':>12} {'lift_nuova':>11}")
    risultati = {}
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        tr = per_ruolo_train[ruolo]
        te = per_ruolo_test[ruolo]
        xs_tr = [r['atteso_raw'] for r in tr]
        ys_tr = [r['reale'] for r in tr]
        a_new, b_new = ols(xs_tr, ys_tr)
        a_old, b_old = CALIB_ATTUALE[ruolo]

        xs_te = [r['atteso_raw'] for r in te]
        ys_te = [r['reale'] for r in te]
        pred_old = [a_old + b_old * x for x in xs_te]
        pred_new = [a_new + b_new * x for x in xs_te]

        corr_old = correlazione(pred_old, ys_te)
        corr_new = correlazione(pred_new, ys_te)
        mae_old = mae(pred_old, ys_te)
        mae_new = mae(pred_new, ys_te)
        lift_old = lift_top_decile(pred_old, ys_te)
        lift_new = lift_top_decile(pred_new, ys_te)

        risultati[ruolo] = dict(a_old=a_old, b_old=b_old, a_new=a_new, b_new=b_new,
                                 corr_old=corr_old, corr_new=corr_new,
                                 mae_old=mae_old, mae_new=mae_new,
                                 lift_old=lift_old, lift_new=lift_new,
                                 n_train=len(tr), n_test=len(te))

        print(f'{ruolo:5} {len(tr):5} {len(te):5}  {a_old:9.2f} {b_old:9.3f}  {a_new:9.2f} {b_new:9.3f}  '
              f'{corr_old:12.3f} {corr_new:10.3f}  {mae_old:11.2f} {mae_new:10.2f}  '
              f'{lift_old:12.2f} {lift_new:11.2f}')

    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'refit_calib_per_ruolo_2026-08-13.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(risultati, f, indent=2, ensure_ascii=False)
    print()
    print('salvato:', out_path)


if __name__ == '__main__':
    main()
