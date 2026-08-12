"""Script temporaneo (non di produzione): rigenera pool_rows con atteso_raw incluso.
Non tocca archivio_ufficiale/aggregato/binario2_pool_rows.json.
"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))
os.chdir(ROOT)

import p24_binario2_ga as B
import analizza_gw as AG
import p12_backtest_formazione_grade as S21

lega_di = AG.indice_lega()
idx_grade, _ = S21.carica_indice_grade()

fixtures = B.elenca_fixture()
out_rows = []
for manager, fx, path in fixtures:
    righe = B.carica_formazioni(path)
    pool, escluse = B.costruisci_pool_carte(righe)
    if not pool:
        continue
    fine_giornata = B.fine_giornata_da_slug(fx)
    primo_kickoff = B.trova_primo_kickoff(pool, fine_giornata)
    if primo_kickoff is None:
        continue
    pool_rows, scarti = B.prepara_pool_rows(pool, primo_kickoff, fine_giornata, idx_grade, lega_di)
    for r in pool_rows:
        if r['codice'] != 'GK':
            continue
        out_rows.append({'manager': manager, 'fixture': fx, 'slug': r['slug'], 'nome': r['nome'],
                          'codice': r['codice'], 'atteso_raw': r['atteso_raw'], '_cal': r['_cal'],
                          'reale': r['reale']})

out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'gk_atteso_raw_2026-08-12.json')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as fh:
    json.dump(out_rows, fh, ensure_ascii=False, indent=1)
print('n GK righe:', len(out_rows))
print('scritto in', out_path)
