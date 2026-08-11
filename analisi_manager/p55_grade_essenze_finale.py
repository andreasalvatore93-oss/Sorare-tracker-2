# -*- coding: utf-8 -*-
"""(c) Il braccio unico pre-registrato, ricetta finale del 12/08/2026:
  - tabella VOTO: p53 (popolazione consigli, non l'archivio manager).
  - tabella sd_atteso: p47 (popolazione consigli) + fix (i) celle n<2.
  - fattore_storico: 0,482 (ritarato oggi in p54 su questa ricetta).
  - ricentraggio: GLOBALE (una costante sola, come l'originale di Opus
    §18.2) -- NON per ruolo: le costanti per ruolo misurate sul backtest
    (p51) correggevano un artefatto del backtest stesso (selezione DNP,
    vedi §8bis-bis "Il +1,02 del voto") e Opus ha detto di non spedirle.

Caveat onesto (Opus, testuale): il pool di backtest e' filtrato
sull'esito (tiene solo le giornate in cui il giocatore ha giocato), quindi
QUALUNQUE numero di guadagno che esce da questo test e' distorto in un
senso non misurato. Il placebo (p52) resta la prova che conta: il segnale
e' vero, la TAGLIA no.

Uso: python analisi_manager/p55_grade_essenze_finale.py
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
FATTORE = 0.482


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
        print(f'  media aggiustamento tolta (ricentraggio globale): {media_agg:+.4f}')
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

    with open(GRADE_SCALE_PRODUZIONE, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_prod)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_prod)
    for k, n in conteggio.items():
        if n < 2 and k in tab_sd['lega_ruolo']:
            del tab_sd['lega_ruolo'][k]

    tot_base = gioca(pre_ok, 'lega_ruolo')
    print('ricetta finale (voto+sd produzione, fattore 0.482, ricentraggio globale):')
    tot_finale = gioca(pre_ok, 'storica_completa', tab_sd, FATTORE, ricentra=True)

    print(f'\nG baseline: {sum(tot_base.values()):+.0f}')
    print(f'G finale  : {sum(tot_finale.values()):+.0f}')
    r = boot(tot_base, tot_finale)
    print(f'\ndelta: {r["delta"]:+.0f}  IC95%=[{r["lo"]:+.0f};{r["hi"]:+.0f}]  positivo {r["pct"]*100:.1f}%  n={r["n_gw"]}')

    out = os.path.join('analisi_manager', 'dati', 'grade_essenze_finale_2026-08-12.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({k: {'|'.join(kk): vv for kk, vv in v.items()}
                   for k, v in (('baseline', tot_base), ('finale', tot_finale))},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio: {out}')


if __name__ == '__main__':
    main()
