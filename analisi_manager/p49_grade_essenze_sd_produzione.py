# -*- coding: utf-8 -*-
"""Livello ESSENZE (Binario 2) del filone gruppo grade esteso alla
giornata, RIFATTO con la tabella sd_atteso di PRODUZIONE (p47) e il
fattore_storico RITARATO su quella fonte (misurato oggi in
p48_grade_carta_sd_produzione.py: pendenza OLS = 0,462, non 0,75).

Tre varianti, stesso pool_rows di partenza (deep copy per non
interferire), stesso bootstrap appaiato cluster manager-fixture -- stessa
ricetta di p46/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §18.2:
  baseline        : GRADE_GROUP_MODE='lega_ruolo' (produzione oggi)
  storica_prod    : 'storica_completa', sd_atteso da produzione (consigli),
                     fattore_storico=0.462 (ritarato oggi), NON ricentrata
  storica_prod_rc : uguale, MA con recentraggio esplicito a media zero
                     (Opus §18.6: "il grade serve a ordinare, non a
                     decidere quante arene si giocano" -- si sottrae la
                     media dell'aggiustamento sull'intero campione prima
                     di somigliarlo a _cal)

Uso: python analisi_manager/p49_grade_essenze_sd_produzione.py
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
FATTORE_REFIT = 0.462


def gioca_variante(pre_ok, tab_sd, fattore, ricentra):
    """Ritorna {(manager,fixture): tot_G} per la variante storica_completa
    con questi parametri, su una COPIA dei pool_rows (non tocca pre_ok)."""
    varianti = []
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        S21.applica_gruppi_grade(rows, modo='storica_completa',
                                 tabella_sd_storica=tab_sd, fattore_storico=fattore)
        varianti.append((pre, rows))

    if ricentra:
        tutte = [r for _pre, rows in varianti for r in rows]
        media_agg = sum(r['_combinato'] - r['_cal'] for r in tutte) / len(tutte)
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media_agg, 2)

    out = {}
    for pre, rows in varianti:
        fake_pre = {'manager': pre['manager'], 'fixture': pre['fixture'],
                    'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                    'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake_pre)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def gioca_baseline(pre_ok):
    out = {}
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        fake_pre = {'manager': pre['manager'], 'fixture': pre['fixture'],
                    'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                    'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake_pre)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def bootstrap_delta(chiavi_valori_a, chiavi_valori_b, n_boot=5000, seed=20260812):
    chiavi = sorted(set(chiavi_valori_a) & set(chiavi_valori_b))
    rnd = random.Random(seed)
    diffs_totali = []
    for _ in range(n_boot):
        camp = [chiavi[rnd.randrange(len(chiavi))] for _i in range(len(chiavi))]
        tot_a = sum(chiavi_valori_a[k] for k in camp)
        tot_b = sum(chiavi_valori_b[k] for k in camp)
        diffs_totali.append(tot_b - tot_a)
    diffs_totali.sort()
    n = len(diffs_totali)
    delta_puntuale = sum(chiavi_valori_b[k] - chiavi_valori_a[k] for k in chiavi)
    return {'n_gw': len(chiavi), 'delta': delta_puntuale,
            'lo': diffs_totali[int(0.025 * n)], 'hi': diffs_totali[int(0.975 * n)],
            'pct_positivo': sum(1 for d in diffs_totali if d > 0) / n}


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

    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_produzione = json.load(f)
    tab_sd_prod = S21.costruisci_tabella_sd_atteso(righe_produzione)
    print(f'tabella sd_atteso PRODUZIONE: n={len(righe_produzione)}, '
          f'globale sd={tab_sd_prod["globale"][1]:.2f}, fattore_refit={FATTORE_REFIT}')

    tot_baseline = gioca_baseline(pre_ok)
    tot_prod = gioca_variante(pre_ok, tab_sd_prod, FATTORE_REFIT, ricentra=False)
    tot_prod_rc = gioca_variante(pre_ok, tab_sd_prod, FATTORE_REFIT, ricentra=True)

    print(f'\nG totale baseline (lega_ruolo):            {sum(tot_baseline.values()):+.0f}  '
          f'({len(tot_baseline)} GW-manager)')
    print(f'G totale storica_prod (non ricentrata):     {sum(tot_prod.values()):+.0f}')
    print(f'G totale storica_prod_rc (ricentrata):      {sum(tot_prod_rc.values()):+.0f}')

    for nome, variante in (('storica_prod (non ricentrata) vs baseline', tot_prod),
                           ('storica_prod_rc (ricentrata) vs baseline', tot_prod_rc)):
        boot = bootstrap_delta(tot_baseline, variante)
        print(f'\n=== {nome} ===')
        print(f'  n GW-manager appaiate: {boot["n_gw"]}')
        print(f'  delta: {boot["delta"]:+.0f}  IC95%=[{boot["lo"]:+.0f};{boot["hi"]:+.0f}]  '
              f'positivo {boot["pct_positivo"]*100:.1f}%')

    out_path = os.path.join('analisi_manager', 'dati', 'grade_essenze_sd_produzione_2026-08-12.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'tot_baseline': {'|'.join(k): v for k, v in tot_baseline.items()},
                   'tot_prod': {'|'.join(k): v for k, v in tot_prod.items()},
                   'tot_prod_rc': {'|'.join(k): v for k, v in tot_prod_rc.items()}},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
