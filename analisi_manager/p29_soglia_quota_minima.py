"""QUOTA_MINIMA (soglia d'ingresso arena in essenze): grid search fuori campione (13/08/2026).

Priorita' #3 di docs/handoff/HANDOFF_ORCHESTRATORE_NUOVO_2026-08-13.txt.

Dati: archivio_ufficiale/aggregato/binario1_out.json -> per_gw -> risultati
(gia' prodotto da p23_binario1_mga.py). Guadagno per formazione stimato sul
PUNTEGGIO REALE (punteggio_totale), non su premio_netto (lotteria che
nasconde il segnale, vedi handoff): gain = (punteggio_totale - PAREGGIO_ARENA)
* GUADAGNO_PER_PUNTO, la stessa formula lineare calibrata gia' in produzione
(_etichetta_arena in build_formazione_globale.py), solo applicata al reale
invece che all'atteso.

Split cronologico deciso PRIMA di guardare i numeri (stesso taglio usato per
CALIB_PER_RUOLO e DEF oggi, corretto su indicazione dell'utente: arene ricche
apr-inizio giugno, mondiali di mezzo, arene ricche riprendono fine luglio):
train = fixture fino al 2026-06-11, test = fixture dal 2026-07-21.

Uso: python analisi_manager/p29_soglia_quota_minima.py
"""
import os
import sys
import json
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p23_binario1_mga as B1
import generatore_formazioni.build_formazione_globale as BFG

TRAIN_END = datetime.datetime(2026, 6, 12)
TEST_START = datetime.datetime(2026, 7, 20)
GRIGLIA = [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30]


def carica_righe():
    d = json.load(open(os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario1_out.json'),
                       encoding='utf-8'))
    righe = []
    for gw in d['per_gw']:
        dt = B1.fine_giornata_da_slug(gw['fixture'])
        for r in gw['risultati']:
            if r.get('punteggio_totale') is None:
                continue
            r2 = dict(r)
            r2['dt'] = dt
            tipo_bfg = B1.TIPO_TO_BFG[r2['tipo']]
            r2['soglia'] = BFG.PAREGGIO_ARENA[tipo_bfg]
            r2['costo'] = BFG.COSTO_INGRESSO[tipo_bfg]
            r2['guad'] = BFG.GUADAGNO_PER_PUNTO[tipo_bfg]
            r2['gain_reale_se_entra'] = (r2['punteggio_totale'] - r2['soglia']) * r2['guad']
            righe.append(r2)
    return righe


def valuta(rows, q):
    tot, n_entra = 0.0, 0
    for r in rows:
        soglia_dec = r['soglia'] + r['costo'] * q / r['guad']
        if r['atteso_G'] >= soglia_dec:
            tot += r['gain_reale_se_entra']
            n_entra += 1
    return tot, n_entra


def main():
    righe = carica_righe()
    train = [r for r in righe if r['dt'] <= TRAIN_END]
    test = [r for r in righe if r['dt'] >= TEST_START]
    print(f'n train: {len(train)}  n test: {len(test)}')
    print()
    print(f"{'q':>6} {'train_tot':>10} {'train_n':>8} {'test_tot':>10} {'test_n':>8}")
    risultati = []
    for q in GRIGLIA:
        tt, nt = valuta(train, q)
        te, ne = valuta(test, q)
        risultati.append({'q': q, 'train_tot': tt, 'train_n': nt, 'test_tot': te, 'test_n': ne})
        print(f'{q:6.2f} {tt:10.0f} {nt:8d} {te:10.0f} {ne:8d}')

    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'quota_minima_grid_2026-08-13.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(risultati, f, indent=2, ensure_ascii=False)
    print()
    print('salvato:', out_path)


if __name__ == '__main__':
    main()
