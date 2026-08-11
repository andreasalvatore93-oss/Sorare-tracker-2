# -*- coding: utf-8 -*-
"""(b) Ritara fattore_storico DOPO tutti i fix di oggi (12/08/2026):
  - tabella VOTO dalla popolazione di produzione (p53, non piu' l'archivio
    dati_globali/manager_*.json -- quella aveva un'origine diversa dal
    problema del voto, vedi §8bis-bis "Il +1,02 del voto": non si usa piu').
  - tabella sd_atteso dalla popolazione di produzione (p47).
  - fix (i): celle (lega,codice) con n<2 rimosse, fallback su livello ruolo.
  - NIENTE ricentraggio per ruolo qui (quello misurato sul backtest era un
    cerotto per un artefatto del backtest -- filtro DNP che seleziona le
    date "buone" per ogni giocatore, non trasferibile in produzione, vedi
    Opus). Si misura solo quanto vale la spinta cieca con la tabella nuova,
    per vedere se e' davvero piccola (~0,2-0,3pt attesi, non piu' 1,4).

Stesso identico test di p48 (braccio 4, corr+pendenza OLS, bootstrap
cluster manager-fixture), solo con le tabelle sostituite.

Uso: python analisi_manager/p54_grade_carta_refit_v2.py
"""
import os
import sys
import io
import json
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p24_binario2_ga as B2

GRADE_SCALE_PRODUZIONE = os.path.join('analisi_manager', 'dati', 'grade_scala_produzione_2026-08-12.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati', 'sd_atteso_produzione_righe.json')


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / (sxx * syy) ** 0.5


def ols_slope(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def bootstrap_stat(righe, campo_x, stat_fn, n_boot=3000, seed=51):
    by_gw = collections.defaultdict(list)
    for r in righe:
        by_gw[(r['manager'], r['fixture'])].append(r)
    chiavi = list(by_gw.keys())
    rnd = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        camp = []
        for _i in range(len(chiavi)):
            k = chiavi[rnd.randrange(len(chiavi))]
            camp.extend(by_gw[k])
        xs = [r[campo_x] for r in camp]
        ys = [r['residuo'] for r in camp]
        v = stat_fn(xs, ys)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return None
    n = len(vals)
    return {'n_boot': n, 'stima': stat_fn([r[campo_x] for r in righe], [r['residuo'] for r in righe]),
            'lo': vals[int(0.025 * n)], 'hi': vals[int(0.975 * n)],
            'pct_positivo': sum(1 for v in vals if v > 0) / n}


def main():
    fixtures = B2.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print(f'fixture processate: {len(pre_ok)} (su {len(fixtures)})')

    with open(GRADE_SCALE_PRODUZIONE, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    print(f'tabella VOTO: {GRADE_SCALE_PRODUZIONE}')

    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_produzione = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_produzione)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_produzione)
    celle_tolte = [k for k, n in conteggio.items() if n < 2 and k in tab_sd['lega_ruolo']]
    for k in celle_tolte:
        del tab_sd['lega_ruolo'][k]
    print(f'tabella sd_atteso PRODUZIONE: n={len(righe_produzione)}, celle n<2 tolte: {len(celle_tolte)}')

    righe = []
    for pre in pre_ok:
        rows = pre['pool_rows']
        for r in rows:
            scala = S21.bfg._scala_storica_per(r['lega'], r['codice'])
            gm, gsd, _liv = scala if scala else (0.0, 0.0, None)
            z = (r['_grade'] - gm) / gsd if (r.get('_grade') is not None and gsd > 0) else 0.0
            r['_agg'] = S21._sd_atteso_storico(tab_sd, r['lega'], r['codice']) * z

        for r in rows:
            if r.get('_grade') is None or r.get('_cal') is None or r.get('reale') is None:
                continue
            righe.append({'manager': pre['manager'], 'fixture': pre['fixture'],
                          'codice': r['codice'], 'residuo': r['reale'] - r['_cal'], 'agg': r['_agg']})

    print(f'\nrighe con grade noto: {len(righe)}')
    corr_boot = bootstrap_stat(righe, 'agg', pearson)
    slope_boot = bootstrap_stat(righe, 'agg', ols_slope)
    print(f'corr(aggiustamento, residuo) = {corr_boot["stima"]:+.4f}  '
          f'IC95%=[{corr_boot["lo"]:+.4f};{corr_boot["hi"]:+.4f}]  {corr_boot["pct_positivo"]*100:.1f}%')
    print(f'pendenza OLS = {slope_boot["stima"]:+.4f}  '
          f'IC95%=[{slope_boot["lo"]:+.4f};{slope_boot["hi"]:+.4f}]  {slope_boot["pct_positivo"]*100:.1f}%')
    print(f'-> FATTORE_STORICO ritarato (v2): {slope_boot["stima"]:.3f}')

    media_agg = sum(r['agg'] for r in righe) / len(righe)
    print(f'\nmedia aggiustamento (fattore=1, spinta cieca) sul campione backtest: {media_agg:+.4f}')
    per_ruolo = collections.defaultdict(list)
    for r in righe:
        per_ruolo[r['codice']].append(r['agg'])
    for cod in sorted(per_ruolo):
        v = per_ruolo[cod]
        print(f'  {cod:4s} media_agg={sum(v)/len(v):+.4f}  n={len(v)}')


if __name__ == '__main__':
    main()
