"""Fascia di confine QUOTA_MINIMA: la perdita estiva e' la carta che non gioca.

Contesto. p29 aveva trovato che train (apr-11 giu) e test (21 lug-7 ago)
preferiscono valori opposti di QUOTA_MINIMA; p30 aveva mostrato che il
confronto si gioca tutto sulla FASCIA DI CONFINE (le formazioni il cui
destino cambia fra due valori di q) e che i due periodi si contraddicono a
3,2 errori standard. Questo script trova il perche'.

Tre misure, in ordine:
  1. residuo per CARTA (reale meno atteso) per periodo: serve a escludere che
     il modello preveda peggio i giocatori in estate. Non lo fa.
  2. tasso di carte a 0 (panchinati) per periodo e dentro/fuori la fascia.
  3. guadagno della fascia di confine scomposto per presenza di carte a 0:
     e' li' che il segno si ribalta, non fra i periodi.

Nessuna query di rete, nessuna modifica alla produzione.
Uso: python analisi_manager/p35_banda_dnp.py
"""
import os
import sys
import io
import json
import glob
import math
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p23_binario1_mga as B1
import generatore_formazioni.build_formazione_globale as BFG

TRAIN_END = datetime.datetime(2026, 6, 12)
TEST_START = datetime.datetime(2026, 7, 20)
Q_ALTO = 0.15   # la fascia e' [soglia, soglia + costo*Q_ALTO/guadagno)

MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def data_fixture(fx):
    p = fx.split('-')
    anno = int(p[-1])
    mesi = [(i, MESI[t]) for i, t in enumerate(p) if t in MESI]
    m = mesi[-1][1]
    g = 1
    for i in range(mesi[-1][0] - 1, -1, -1):
        if p[i].isdigit() and len(p[i]) <= 2:
            g = int(p[i]); break
    return datetime.datetime(anno, m, g)


def periodo(dt):
    if dt <= TRAIN_END:
        return 'TRAIN'
    if dt >= TEST_START:
        return 'TEST'
    return None


def stat(v):
    n = len(v)
    if n < 2:
        return n, (v[0] if v else float('nan')), float('nan')
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return n, m, sd / math.sqrt(n)


# ---------------------------------------------------------------- 1. carte
def misura_carte():
    rows = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json',
                          encoding='utf-8'))
    print('=== 1. RESIDUO PER CARTA (reale - atteso calibrato) ===')
    print('    esclude che il modello preveda peggio i giocatori in estate')
    for nome in ('TRAIN', 'TEST'):
        rs = [r for r in rows if periodo(data_fixture(r['fixture'])) == nome]
        rs.sort(key=lambda r: r['_cal'])
        n, m, se = stat([r['reale'] - r['_cal'] for r in rs])
        q = len(rs) // 4
        nb, mb, seb = stat([r['reale'] - r['_cal'] for r in rs[:q]])
        print(f'  {nome:5s} n={n:5d}  residuo {m:+5.2f} (err.std {se:.2f})   '
              f'quarto piu basso di atteso: n={nb} residuo {mb:+5.2f} (err.std {seb:.2f})')
    print()


# ------------------------------------------------------- 2-3. formazioni
def indicizza_formazioni_grezze():
    """(tipo, punteggio_totale arrotondato, capitano) -> formazioni grezze."""
    idx = {}
    for path in glob.glob('archivio_ufficiale/manager_*/**/*.json', recursive=True):
        try:
            righe = B1.carica_formazioni(path)
        except Exception:
            continue
        if not isinstance(righe, list):
            continue
        for r in righe:
            if not isinstance(r, dict) or 'carte' not in r:
                continue
            tot = r.get('punteggio_totale')
            cap = next((c.get('slug') for c in r['carte'] if c.get('capitano')), None)
            k = (r.get('tipo'), None if tot is None else round(tot, 2), cap)
            idx.setdefault(k, []).append(r)
    return idx


def misura_formazioni():
    idx = indicizza_formazioni_grezze()
    d = json.load(open('archivio_ufficiale/aggregato/binario1_out.json', encoding='utf-8'))
    conta = collections.defaultdict(lambda: [0, 0, 0])   # n, con>=1 zero, zeri totali
    gain = collections.defaultdict(list)
    non_appaiate = 0
    for gw in d['per_gw']:
        per = periodo(B1.fine_giornata_da_slug(gw['fixture']))
        if per is None:
            continue
        for r in gw['risultati']:
            if r.get('punteggio_totale') is None:
                continue
            t = B1.TIPO_TO_BFG[r['tipo']]
            soglia = BFG.PAREGGIO_ARENA[t]
            costo = BFG.COSTO_INGRESSO[t]
            guad = BFG.GUADAGNO_PER_PUNTO[t]
            in_banda = soglia <= r['atteso_G'] < soglia + costo * Q_ALTO / guad
            cand = idx.get((r['tipo'], round(r['punteggio_totale'], 2), r.get('capitano')))
            if not cand:
                non_appaiate += 1
                continue
            # stima PRUDENTE: se piu' formazioni collidono sulla chiave, il minimo
            zeri = min(sum(1 for c in f['carte'] if (c.get('punteggio') or 0.0) == 0.0)
                       for f in cand)
            for et in [per] + ([per + ' fascia'] if in_banda else []):
                conta[et][0] += 1
                conta[et][1] += 1 if zeri else 0
                conta[et][2] += zeri
            if in_banda:
                gain[(per, 'con carta a 0' if zeri else 'senza carte a 0')].append(
                    (r['punteggio_totale'] - soglia) * guad)

    print('=== 2. QUANTE FORMAZIONI HANNO UNA CARTA A 0 ===')
    print(f'    (righe non appaiate con le formazioni grezze: {non_appaiate})')
    for et in ('TRAIN', 'TRAIN fascia', 'TEST', 'TEST fascia'):
        n, f, z = conta[et]
        if n:
            print(f'  {et:14s} formazioni={n:5d}  con >=1 carta a 0: {f:4d} ({f/n:5.1%})'
                  f'   carte a 0 per formazione: {z/n:.3f}')
    print()

    print('=== 3. GUADAGNO DELLA FASCIA DI CONFINE, SCOMPOSTO ===')
    for per in ('TRAIN', 'TEST'):
        tot = []
        for k in ('senza carte a 0', 'con carta a 0'):
            v = gain[(per, k)]
            tot += v
            n, m, se = stat(v)
            print(f'  {per:5s} {k:16s} n={n:4d}  media {m:+8.1f} essenze  err.std {se:5.1f}')
        n, m, se = stat(tot)
        print(f'  {per:5s} {"TOTALE":16s} n={n:4d}  media {m:+8.1f} essenze  err.std {se:5.1f}')


if __name__ == '__main__':
    misura_carte()
    misura_formazioni()
