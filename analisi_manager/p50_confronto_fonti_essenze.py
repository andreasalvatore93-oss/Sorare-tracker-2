# -*- coding: utf-8 -*-
"""Confronto APPAIATO fra le due fonti di sd_atteso a livello ESSENZE
(Binario 2) -- controllo mancante segnalato da Opus esecutore il 12/08/2026.

p49_grade_essenze_sd_produzione.py misura (produzione 0,462 ricentrata) vs
baseline = +7.761; il numero della fonte vecchia (archivio 0,75 ricentrata)
= +4.260 viene da una RUN DIVERSA. Confrontare due IC di run diverse non
decide niente: la regola del repo ("Cosa deve riprodursi: il delta, non il
valore assoluto", CLAUDE.md) chiede il delta APPAIATO fra le due varianti,
misurato nello stesso run sullo stesso campione.

Qui: stesso pool_rows, tre bracci (baseline lega_ruolo, archivio 0,75
ricentrata, produzione 0,462 ricentrata), stesso bootstrap cluster
manager-fixture. Il numero che decide e' l'ultimo: produzione - archivio.

Uso: python analisi_manager/p50_confronto_fonti_essenze.py
Nessuna query di rete, nessuna modifica alla produzione.
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


def gioca(pre_ok, modo, tab_sd=None, fattore=1.0, ricentra=False):
    varianti = []
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if modo == 'lega_ruolo':
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        else:
            S21.applica_gruppi_grade(rows, modo='storica_completa',
                                     tabella_sd_storica=tab_sd, fattore_storico=fattore)
        varianti.append((pre, rows))
    if ricentra:
        tutte = [r for _p, rows in varianti for r in rows]
        media_agg = sum(r['_combinato'] - r['_cal'] for r in tutte) / len(tutte)
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media_agg, 2)
    out = {}
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def boot(a, b, n_boot=5000, seed=20260812):
    chiavi = sorted(set(a) & set(b))
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        camp = [chiavi[rnd.randrange(len(chiavi))] for _i in range(len(chiavi))]
        ds.append(sum(b[k] for k in camp) - sum(a[k] for k in camp))
    ds.sort()
    n = len(ds)
    return {'n_gw': len(chiavi), 'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n}


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

    tab_arch = S21.costruisci_tabella_sd_atteso([r for pre in pre_ok for r in pre['pool_rows']])
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        tab_prod = S21.costruisci_tabella_sd_atteso(json.load(f))

    tot_base = gioca(pre_ok, 'lega_ruolo')
    tot_arch = gioca(pre_ok, 'storica_completa', tab_arch, 0.75, ricentra=True)
    tot_prod = gioca(pre_ok, 'storica_completa', tab_prod, 0.462, ricentra=True)

    print(f'\nG baseline  : {sum(tot_base.values()):+.0f}')
    print(f'G archivio  : {sum(tot_arch.values()):+.0f}')
    print(f'G produzione: {sum(tot_prod.values()):+.0f}')
    for nome, a, b in (('archivio 0,75 rc  vs baseline', tot_base, tot_arch),
                       ('produzione 0,462 rc vs baseline', tot_base, tot_prod),
                       ('>>> produzione vs archivio (APPAIATO, il numero che decide)', tot_arch, tot_prod)):
        r = boot(a, b)
        print(f'\n=== {nome} ===')
        print(f"  n GW-manager: {r['n_gw']}   delta: {r['delta']:+.0f}  "
              f"IC95%=[{r['lo']:+.0f};{r['hi']:+.0f}]  positivo {r['pct']*100:.1f}%")

    out = os.path.join('analisi_manager', 'dati', 'confronto_fonti_essenze_2026-08-12.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({k: {'|'.join(kk): vv for kk, vv in v.items()}
                   for k, v in (('baseline', tot_base), ('archivio', tot_arch), ('produzione', tot_prod))},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio: {out}')


if __name__ == '__main__':
    main()
