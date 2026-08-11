"""TEST CARTA -- il grade porta informazione? (11/08/2026, proposto da Opus)

Vedi docs/handoff/RISPOSTA_OPUS_STATO_GVSA_ROUND4_2026-08-11.txt sez. 5.2.

A livello di FORMAZIONE (5 carte sommate) il segnale del grade non si vede
(errore standard troppo grande, ~0.354 su beta): gli aggiustamenti delle 5
carte si annullano a vicenda e il rumore no. Qui si rifa' la stessa
regressione a livello di CARTA SINGOLA, su tutte le righe del pool
(archivio_ufficiale/aggregato/binario2_pool_rows.json, scritto da
p24_binario2_ga.py, zero query nuove).

Regressione: (reale - atteso_senza_grade) = alpha + beta * aggiustamento_grade + errore
  aggiustamento_grade = atteso_con_grade - atteso_senza_grade = sd_gruppo * z_grade

beta=1 -> il grade e' applicato col peso giusto in produzione.
beta=0 -> il grade e' rumore, nessuna informazione.
beta<0 -> il grade peggiora la previsione.

Errori standard: OLS classico (assume righe indipendenti, ottimistico: lo
stesso giocatore compare piu' volte nella stessa giornata se piu' manager
lo schierano) + cluster-robust su slug (un giocatore ripetuto in piu'
fixture/manager non e' un'osservazione indipendente in piu') + cluster-
robust su fixture (tutte le carte della stessa giornata condividono lo
stesso errore di modello per quella giornata). Implementato a mano,
numpy/pandas non installati in questo ambiente.

Uso: python analisi_manager/p25_test_carta_grade.py
"""
import os
import sys
import io
import json
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_pool_rows.json')


def ols_intercetta(xs, ys):
    """OLS y = a + b*x, ritorna (a, b, residui, Sxx_raw, Sx, det, bread)."""
    n = len(xs)
    Sx = sum(xs)
    Sxx_raw = sum(x * x for x in xs)
    xbar = Sx / n
    ybar = sum(ys) / n
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    sxx = sum((x - xbar) ** 2 for x in xs)
    b = sxy / sxx
    a = ybar - b * xbar
    residui = [y - a - b * x for x, y in zip(xs, ys)]
    det = n * Sxx_raw - Sx * Sx
    # bread = (X'X)^-1, 2x2: [[Sxx_raw, -Sx], [-Sx, n]] / det
    bread = ((Sxx_raw / det, -Sx / det), (-Sx / det, n / det))
    return a, b, residui, sxx, bread


def se_classico(residui, sxx, n):
    sse = sum(r ** 2 for r in residui)
    sigma2 = sse / (n - 2)
    return (sigma2 / sxx) ** 0.5


def se_cluster(xs, residui, cluster_id, bread, n, k=2):
    """Sandwich cluster-robust (CR1), matrice 2x2 completa, nessuna scorciatoia.

    meat = sum_g (X_g' e_g)(X_g' e_g)'  con X_g = [1, x_i] per riga.
    Var(beta_hat) = bread . meat . bread ; si estrae [1][1] (varianza di b).
    Correzione small-sample G/(G-1) * (n-1)/(n-k), standard (Stata-style).
    """
    gruppi = collections.defaultdict(list)
    for i, cid in enumerate(cluster_id):
        gruppi[cid].append(i)
    meat = [[0.0, 0.0], [0.0, 0.0]]
    for _cid, idx in gruppi.items():
        s0 = sum(residui[i] for i in idx)
        s1 = sum(xs[i] * residui[i] for i in idx)
        meat[0][0] += s0 * s0
        meat[0][1] += s0 * s1
        meat[1][0] += s1 * s0
        meat[1][1] += s1 * s1
    # Var = bread @ meat @ bread (2x2 matmul a mano)
    tmp = [[sum(bread[i][k2] * meat[k2][j] for k2 in range(2)) for j in range(2)]
           for i in range(2)]
    var = [[sum(tmp[i][k2] * bread[j][k2] for k2 in range(2)) for j in range(2)]
           for i in range(2)]
    G = len(gruppi)
    corr = (G / (G - 1)) * ((n - 1) / (n - k)) if G > 1 else 1.0
    var_b = corr * var[1][1]
    return var_b ** 0.5, G


def main():
    righe = json.load(open(PATH, encoding='utf-8'))
    print(f'righe carta totali nel pool: {len(righe)}')

    xs, ys, slugs, fixtures = [], [], [], []
    for r in righe:
        if r.get('_cal') is None or r.get('reale') is None or r.get('_combinato') is None:
            continue
        aggiustamento = r['_combinato'] - r['_cal']
        residuo = r['reale'] - r['_cal']
        xs.append(aggiustamento)
        ys.append(residuo)
        slugs.append(r['slug'])
        fixtures.append(r['fixture'])
    n = len(xs)
    n_con_grade = sum(1 for r in righe if r.get('_grade') is not None)
    coppie_uniche = len(set(zip(slugs, fixtures)))
    print(f'righe con _cal/reale/_combinato validi: {n}  ({n_con_grade} con grade attivo, '
          f'{100 * n_con_grade / n:.1f}%)')
    print(f'coppie (slug, fixture) distinte: {coppie_uniche}  '
          f'(ridondanza {n / coppie_uniche:.2f}x -- stesso giocatore in piu\' manager/mazzi)')

    a, b, residui, sxx, bread = ols_intercetta(xs, ys)
    se0 = se_classico(residui, sxx, n)
    se_slug, g_slug = se_cluster(xs, residui, slugs, bread, n)
    se_fix, g_fix = se_cluster(xs, residui, fixtures, bread, n)

    print()
    print('=' * 78)
    print('REGRESSIONE: (reale - atteso_senza_grade) = a + b * aggiustamento_grade')
    print('=' * 78)
    print(f'  n = {n}   intercetta a = {a:+.3f}   beta b = {b:+.3f}')
    print(f'  SE classico (righe indipendenti, ottimistico): {se0:.3f}   t = {b / se0:+.2f}')
    print(f'  SE cluster su slug ({g_slug} cluster):          {se_slug:.3f}   t = {b / se_slug:+.2f}')
    print(f'  SE cluster su fixture ({g_fix} cluster):        {se_fix:.3f}   t = {b / se_fix:+.2f}')
    print()
    print('  Lettura: b=1 -> grade pesato giusto. b=0 -> grade e\' rumore.')
    print('  |t| >= ~2 con lo SE piu\' prudente (il piu\' grande dei tre sopra) = decidibile.')

    # Lift di selezione: dentro ogni pool (manager, fixture), il top-K per _combinato
    # fa meglio (media 'reale' piu' alta) del top-K per _cal?
    per_pool = collections.defaultdict(list)
    for r in righe:
        if r.get('_cal') is None or r.get('reale') is None or r.get('_combinato') is None:
            continue
        per_pool[(r['manager'], r['fixture'])].append(r)

    for K in (5, 10):
        tot_a, tot_g, n_pool_usati = 0.0, 0.0, 0
        cnt_a, cnt_g = 0, 0
        for _key, rows in per_pool.items():
            if len(rows) < K:
                continue
            n_pool_usati += 1
            top_a = sorted(rows, key=lambda r: -r['_cal'])[:K]
            top_g = sorted(rows, key=lambda r: -r['_combinato'])[:K]
            tot_a += sum(r['reale'] for r in top_a)
            tot_g += sum(r['reale'] for r in top_g)
            cnt_a += len(top_a)
            cnt_g += len(top_g)
        print()
        print(f'  LIFT top-{K} per pool (manager,fixture) con almeno {K} carte '
              f'({n_pool_usati} pool usati):')
        print(f'    media reale top-{K} ordinando per _cal (A):        {tot_a / cnt_a:.2f}')
        print(f'    media reale top-{K} ordinando per _combinato (G):  {tot_g / cnt_g:.2f}')
        print(f'    differenza (G-A): {(tot_g / cnt_g) - (tot_a / cnt_a):+.3f} punti/carta')


if __name__ == '__main__':
    main()
