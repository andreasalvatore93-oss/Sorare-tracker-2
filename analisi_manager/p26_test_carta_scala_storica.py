"""TEST CARTA v2 -- stesso test di p25, ma con la SCALA DEL GRADE della
produzione invece di quella (rotta) del backtest (11/08/2026).

Vedi docs/handoff/RISPOSTA_OPUS_ESITO_TESTCARTA_DNP_2026-08-11.txt sez. 2a.
Opus ha verificato che p25 usa la media/sd del grade calcolate DENTRO il
pool della singola formazione (manager, giornata, lega, ruolo): quel
gruppo ha mediana 1 carta (media 1,8), quindi il 54,2% delle righe ha
aggiustamento esattamente zero -- e' un metro di misura pessimo,
sistematicamente attenua qualunque beta si stia stimando.

La produzione con GRADE_SCALE=storica (gia' scritta e verificata l'08/08,
mai spenta di default) risolve lo stesso problema leggendo media/sd del
grade da una tabella storica multi-giornata per lega/ruolo
(generatore_formazioni/dati/grade_scala_storica.json, 70 lega/ruolo + 4
fallback per ruolo + 1 globale, 20.955 osservazioni). La dispersione degli
ATTESI (sd_atteso) resta quella del gruppo locale, come in produzione:
cambia SOLO la scala con cui si legge il grade lettera->numero->z.

Rifa' la regressione di p25 (reale - atteso_A) su questo aggiustamento
alternativo, zero query nuove: tutto gia' in
archivio_ufficiale/aggregato/binario2_pool_rows.json.

Uso: python analisi_manager/p26_test_carta_scala_storica.py
"""
import os
import sys
import io
import json
import glob
import collections
import random

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))
import p25_test_carta_grade as P25  # riusa ols_intercetta/se_classico/se_cluster, validati con test A/A

POOL_PATH = os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_pool_rows.json')
SCALA_PATH = os.path.join(ROOT, 'generatore_formazioni', 'dati', 'grade_scala_storica.json')
GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}


def carica_scala_storica():
    d = json.load(open(SCALA_PATH, encoding='utf-8'))
    return d


def scala_per(tabella, lega, codice):
    """Replica ESATTA di _scala_storica_per in build_formazione_globale.py:
    fallback lega+ruolo -> ruolo -> globale. Ritorna (mean, sd, livello)."""
    voce = tabella.get('per_lega_ruolo', {}).get(f'{lega}|{codice}')
    if voce:
        return voce['mean'], voce['sd'], 'lega_ruolo'
    voce = tabella.get('per_ruolo', {}).get(codice)
    if voce:
        return voce['mean'], voce['sd'], 'ruolo'
    voce = tabella.get('globale')
    if voce:
        return voce['mean'], voce['sd'], 'globale'
    return None


def sd_atteso_per_gruppo(righe):
    """Replica zscore_gruppo (p12) sui _cal, per (manager,fixture,lega,codice)."""
    per_gruppo = collections.defaultdict(list)
    for i, r in enumerate(righe):
        per_gruppo[(r['manager'], r['fixture'], r['lega'], r['codice'])].append(i)
    sd_atteso = [0.0] * len(righe)
    for _key, idx in per_gruppo.items():
        vals = [righe[i]['_cal'] for i in idx]
        n = len(vals)
        if n < 2:
            continue
        m = sum(vals) / n
        sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
        for i in idx:
            sd_atteso[i] = sd
    return sd_atteso, per_gruppo


def calcola_aggiustamenti(righe, tabella, grade_num_per_riga):
    sd_atteso, per_gruppo = sd_atteso_per_gruppo(righe)
    livelli = collections.Counter()
    aggiustamenti = [0.0] * len(righe)
    for i, r in enumerate(righe):
        gn = grade_num_per_riga[i]
        if gn is None:
            continue
        scala = scala_per(tabella, r['lega'], r['codice'])
        if scala is None:
            continue
        gm, gsd, livello = scala
        livelli[livello] += 1
        if gsd <= 0:
            continue
        z = (gn - gm) / gsd
        aggiustamenti[i] = sd_atteso[i] * z
    return aggiustamenti, livelli, per_gruppo


def placebo(righe, grade_num_per_riga, tabella, per_gruppo, n_perm=200, seme=11):
    """Rimescola i grade DENTRO ogni gruppo (manager,fixture,lega,codice),
    come ha fatto Opus: se il beta vero venisse dalla costruzione (gruppi,
    sd) invece che dal grade, sopravvivrebbe al rimescolamento."""
    rnd = random.Random(seme)
    betas = []
    n = len(righe)
    sd_atteso, _ = sd_atteso_per_gruppo(righe)
    ys = [righe[i]['reale'] - righe[i]['_cal'] for i in range(n)]
    for _ in range(n_perm):
        gn_shuffled = list(grade_num_per_riga)
        for _key, idx in per_gruppo.items():
            if len(idx) < 2:
                continue
            vals = [gn_shuffled[i] for i in idx]
            rnd.shuffle(vals)
            for i, v in zip(idx, vals):
                gn_shuffled[i] = v
        agg = [0.0] * n
        for i in range(n):
            gn = gn_shuffled[i]
            if gn is None:
                continue
            scala = scala_per(tabella, righe[i]['lega'], righe[i]['codice'])
            if scala is None:
                continue
            gm, gsd, _liv = scala
            if gsd <= 0:
                continue
            agg[i] = sd_atteso[i] * (gn - gm) / gsd
        _a, b, _res, _sxx, _bread = P25.ols_intercetta(agg, ys)
        betas.append(b)
    return betas


def regressione_dentro_gruppo(xs, ys, cluster_id, per_gruppo):
    """Regressione a effetti fissi di gruppo (RISPOSTA_OPUS_SCALA_STORICA
    sez. 3): toglie a ogni riga la media del suo gruppo (manager, fixture,
    lega, codice) sia da x che da y, poi regressione PASSANTE PER L'ORIGINE
    sui residui demeanizzati (la media del gruppo, per costruzione, non
    porta piu' informazione). Isola lo scarto DENTRO il gruppo dal livello
    FRA i gruppi -- il placebo (che rimescola solo dentro gruppo) puo'
    toccare solo questa parte, quindi qui deve tornare centrato a zero.
    """
    n = len(xs)
    xt = [0.0] * n
    yt = [0.0] * n
    for _key, idx in per_gruppo.items():
        mx = sum(xs[i] for i in idx) / len(idx)
        my = sum(ys[i] for i in idx) / len(idx)
        for i in idx:
            xt[i] = xs[i] - mx
            yt[i] = ys[i] - my
    sxx = sum(x * x for x in xt)
    sxy = sum(x * y for x, y in zip(xt, yt))
    b = sxy / sxx
    residui = [y - b * x for x, y in zip(xt, yt)]
    n_gruppi = len(per_gruppo)
    dof = n - n_gruppi - 1
    sse = sum(r ** 2 for r in residui)
    se_classico = (sse / dof / sxx) ** 0.5 if dof > 0 else float('nan')

    gruppi_cluster = collections.defaultdict(list)
    for i, cid in enumerate(cluster_id):
        gruppi_cluster[cid].append(i)
    meat = 0.0
    for _cid, idx in gruppi_cluster.items():
        s = sum(xt[i] * residui[i] for i in idx)
        meat += s * s
    G = len(gruppi_cluster)
    corr = (G / (G - 1)) * ((n - 1) / dof) if G > 1 and dof > 0 else 1.0
    se_cluster = (corr * meat / (sxx ** 2)) ** 0.5

    n_non_banali = sum(1 for x in xt if x != 0.0)
    return b, se_classico, se_cluster, n_non_banali, n_gruppi


def placebo_dentro_gruppo(righe, grade_num_per_riga, tabella, per_gruppo, n_perm=200, seme=13):
    rnd = random.Random(seme)
    n = len(righe)
    sd_atteso, _ = sd_atteso_per_gruppo(righe)
    ys = [righe[i]['reale'] - righe[i]['_cal'] for i in range(n)]
    betas = []
    for _ in range(n_perm):
        gn_shuffled = list(grade_num_per_riga)
        for _key, idx in per_gruppo.items():
            if len(idx) < 2:
                continue
            vals = [gn_shuffled[i] for i in idx]
            rnd.shuffle(vals)
            for i, v in zip(idx, vals):
                gn_shuffled[i] = v
        agg = [0.0] * n
        for i in range(n):
            gn = gn_shuffled[i]
            if gn is None:
                continue
            scala = scala_per(tabella, righe[i]['lega'], righe[i]['codice'])
            if scala is None:
                continue
            gm, gsd, _liv = scala
            if gsd <= 0:
                continue
            agg[i] = sd_atteso[i] * (gn - gm) / gsd
        b, _se0, _sec, _nnb, _ng = regressione_dentro_gruppo(agg, ys, [None] * n, per_gruppo)
        betas.append(b)
    return betas


def main():
    righe = json.load(open(POOL_PATH, encoding='utf-8'))
    righe = [r for r in righe if r.get('_cal') is not None and r.get('reale') is not None]
    tabella = carica_scala_storica()
    # '_grade' nel dump e' gia' NUMERICO (grade_in_finestra ritorna grade_num,
    # non la lettera -- GRADE_NUM qui sopra serve solo da documentazione/
    # riferimento, non va applicato una seconda volta).
    grade_num_per_riga = [r.get('_grade') for r in righe]
    n_con_grade = sum(1 for g in grade_num_per_riga if g is not None)
    print(f'righe carta valide: {len(righe)}  ({n_con_grade} con grade, '
          f'{100 * n_con_grade / len(righe):.1f}%)')

    aggiustamenti, livelli, per_gruppo = calcola_aggiustamenti(righe, tabella, grade_num_per_riga)
    print(f'livello scala usato: {dict(livelli)}')
    n_zero = sum(1 for a in aggiustamenti if a == 0.0)
    print(f'righe con aggiustamento esattamente zero: {n_zero} '
          f'({100 * n_zero / len(righe):.1f}%)  -- era 54.2% con la scala di gruppo (p25)')

    xs = aggiustamenti
    ys = [r['reale'] - r['_cal'] for r in righe]
    slugs = [r['slug'] for r in righe]
    fixtures = [r['fixture'] for r in righe]

    a, b, residui, sxx, bread = P25.ols_intercetta(xs, ys)
    se0 = P25.se_classico(residui, sxx, len(xs))
    se_slug, g_slug = P25.se_cluster(xs, residui, slugs, bread, len(xs))
    se_fix, g_fix = P25.se_cluster(xs, residui, fixtures, bread, len(xs))

    print()
    print('=' * 78)
    print('REGRESSIONE (scala storica): (reale - atteso_A) = a + b * aggiustamento_storica')
    print('=' * 78)
    print(f'  n = {len(xs)}   a = {a:+.3f}   b = {b:+.3f}')
    print(f'  SE classico:                       {se0:.3f}   t = {b / se0:+.2f}')
    print(f'  SE cluster su slug ({g_slug} gruppi):    {se_slug:.3f}   t = {b / se_slug:+.2f}')
    print(f'  SE cluster su fixture ({g_fix} gruppi):  {se_fix:.3f}   t = {b / se_fix:+.2f}')

    print()
    print('PLACEBO (200 rimescolamenti dei grade dentro ogni gruppo manager/fixture/lega/ruolo):')
    betas_placebo = placebo(righe, grade_num_per_riga, tabella, per_gruppo, n_perm=200)
    media_p = sum(betas_placebo) / len(betas_placebo)
    oltre = sum(1 for bp in betas_placebo if bp >= b)
    ordina = sorted(betas_placebo)
    lo = ordina[int(0.05 * len(ordina))]
    hi = ordina[int(0.95 * len(ordina)) - 1]
    print(f'  beta vero = {b:+.3f}')
    print(f'  beta placebo: media {media_p:+.3f}, IC90 [{lo:+.3f}, {hi:+.3f}]')
    print(f'  permutazioni che arrivano a {b:+.3f}: {oltre}/200  ->  p = {oltre / 200:.3f}')
    print('  NOTA (RISPOSTA_OPUS_SCALA_STORICA sez.2): questo placebo non e\' centrato')
    print('  a zero -- rimescolare DENTRO gruppo tocca solo lo scarto dentro-gruppo')
    print('  (48,7% della varianza), non la media di gruppo. La stima pulita e il suo')
    print('  placebo (centrato a zero) sono qui sotto.')

    print()
    print('=' * 78)
    print('STIMA DENTRO-GRUPPO (effetti fissi di gruppo, la stima pulita)')
    print('=' * 78)
    b_dg, se0_dg, sec_dg, n_nb, n_gr = regressione_dentro_gruppo(xs, ys, fixtures, per_gruppo)
    print(f'  beta dentro-gruppo = {b_dg:+.3f}  ({n_gr} gruppi assorbiti, '
          f'{n_nb} righe con scarto dentro-gruppo non nullo)')
    print(f'  SE classico:              {se0_dg:.3f}   t = {b_dg / se0_dg:+.2f}')
    print(f'  SE cluster su fixture:    {sec_dg:.3f}   t = {b_dg / sec_dg:+.2f}')

    betas_dg = placebo_dentro_gruppo(righe, grade_num_per_riga, tabella, per_gruppo, n_perm=200)
    media_dg = sum(betas_dg) / len(betas_dg)
    oltre_dg = sum(1 for bp in betas_dg if bp >= b_dg)
    ordina_dg = sorted(betas_dg)
    lo_dg = ordina_dg[int(0.05 * len(ordina_dg))]
    hi_dg = ordina_dg[int(0.95 * len(ordina_dg)) - 1]
    print(f'  placebo (200 rimescolamenti): media {media_dg:+.3f} (deve essere ~0), '
          f'IC90 [{lo_dg:+.3f}, {hi_dg:+.3f}]')
    print(f'  permutazioni che arrivano a {b_dg:+.3f}: {oltre_dg}/200  ->  p = {oltre_dg / 200:.3f}')


if __name__ == '__main__':
    main()
