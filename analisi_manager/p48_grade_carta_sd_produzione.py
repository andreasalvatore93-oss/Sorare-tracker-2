# -*- coding: utf-8 -*-
"""Braccio 4 (storica_completa) del test a livello di CARTA, RIFATTO con la
tabella sd_atteso di PRODUZIONE (consiglio_*.txt, p47) invece che con
l'archivio backtest (29 manager, biased -- vedi p46_grade_group_carta.py).

Filone gruppo grade esteso alla giornata, priorita' 2 (11/08/2026). Fonte
decisa da Opus il 12/08 (docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md
§8bis-bis "Fonte per sd_atteso"). Ricetta esatta (recentraggio media zero,
pendenza OLS come metro di taglia) da Opus, docs/handoff/RISPOSTA_OPUS_
CORRELAZIONI_2026-08-13.txt §17.5 e §18.2/18.6.

Riporta, sullo STESSO campione di card (righe con grade+cal+reale noti):
  - corr(aggiustamento, residuo) con la tabella VECCHIA (archivio) come
    controllo di replica (deve tornare vicino al valore gia' misurato,
    altrimenti questo script ha un bug -- non e' la domanda del filone)
  - corr(aggiustamento, residuo) con la tabella NUOVA (produzione)
  - pendenza OLS residuo~aggiustamento per entrambe (fattore_storico da
    applicare = 1/pendenza misurata, o piu' semplice: la pendenza STESSA
    e' il fattore che rende taglia=1, si applica direttamente)
  - media dell'aggiustamento (fattore=1) sul campione: la "spinta cieca"
    che il ricentraggio deve togliere

Uso: python analisi_manager/p48_grade_carta_sd_produzione.py
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

GRADE_SCALE_PATH = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')
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

    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)

    tutte_le_righe_grezze = [r for pre in pre_ok for r in pre['pool_rows']]
    tab_sd_archivio = S21.costruisci_tabella_sd_atteso(tutte_le_righe_grezze)
    print(f'tabella sd_atteso ARCHIVIO: n={len(tutte_le_righe_grezze)}, '
          f'globale sd={tab_sd_archivio["globale"][1]:.2f}')

    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_produzione = json.load(f)
    tab_sd_prod = S21.costruisci_tabella_sd_atteso(righe_produzione)
    print(f'tabella sd_atteso PRODUZIONE (consigli): n={len(righe_produzione)}, '
          f'globale sd={tab_sd_prod["globale"][1]:.2f}')

    righe = []
    for pre in pre_ok:
        rows = pre['pool_rows']
        for r in rows:
            scala = S21.bfg._scala_storica_per(r['lega'], r['codice'])
            gm, gsd, _liv = scala if scala else (0.0, 0.0, None)
            z = (r['_grade'] - gm) / gsd if (r.get('_grade') is not None and gsd > 0) else 0.0
            r['_agg_archivio'] = S21._sd_atteso_storico(tab_sd_archivio, r['lega'], r['codice']) * z
            r['_agg_produzione'] = S21._sd_atteso_storico(tab_sd_prod, r['lega'], r['codice']) * z

        for r in rows:
            if r.get('_grade') is None or r.get('_cal') is None or r.get('reale') is None:
                continue
            righe.append({
                'manager': pre['manager'], 'fixture': pre['fixture'], 'slug': r['slug'],
                'lega': r['lega'], 'codice': r['codice'],
                'residuo': r['reale'] - r['_cal'],
                'agg_archivio': r['_agg_archivio'], 'agg_produzione': r['_agg_produzione'],
            })

    print(f'\nrighe con grade noto (base del test): {len(righe)}')

    for nome_campo, etichetta in (('agg_archivio', 'ARCHIVIO (fonte vecchia, controllo replica)'),
                                   ('agg_produzione', 'PRODUZIONE (consigli, fonte nuova)')):
        xs = [r[nome_campo] for r in righe]
        media_agg = sum(xs) / len(xs)
        corr_boot = bootstrap_stat(righe, nome_campo, pearson)
        slope_boot = bootstrap_stat(righe, nome_campo, ols_slope)
        print(f'\n=== {etichetta} ===')
        print(f'  media aggiustamento (fattore=1, spinta cieca se != 0): {media_agg:+.4f}')
        print(f'  corr(aggiustamento, residuo) = {corr_boot["stima"]:+.4f}  '
              f'IC95%=[{corr_boot["lo"]:+.4f};{corr_boot["hi"]:+.4f}]  '
              f'positivo {corr_boot["pct_positivo"]*100:.1f}%')
        print(f'  pendenza OLS (residuo~aggiustamento) = {slope_boot["stima"]:+.4f}  '
              f'IC95%=[{slope_boot["lo"]:+.4f};{slope_boot["hi"]:+.4f}]  '
              f'positivo {slope_boot["pct_positivo"]*100:.1f}%')
        print(f'  -> fattore_storico da usare (pendenza, taglia=1): {slope_boot["stima"]:.3f}')

    out_path = os.path.join('analisi_manager', 'dati', 'grade_carta_sd_produzione_2026-08-12.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'n_righe': len(righe), 'righe': righe}, fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
