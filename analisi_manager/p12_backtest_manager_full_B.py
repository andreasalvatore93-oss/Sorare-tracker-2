"""Sez.26 -- VERIFICA UNICA su gruppo B, candidata dichiarata PRIMA di
guardare: Cap 260, delta punti per arena (G-A), bootstrap cluster-manager.
Riusa esattamente le stesse funzioni di p12_backtest_manager_full.py
(elabora_coppia, costruisci_pool, COMP_TO_BUILD, ARENE_AMMESSE_TIPO),
zero modifiche al metodo, solo il gruppo di manager cambia.
"""
import os, sys, io, json, glob, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import analizza_gw as AG
import p12_backtest_manager_grade as M
import p12_backtest_manager_full as F

GRUPPO_B = ['bxl-spartak', 'fins49', 'milkyfresht',
           'qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d', 'spillo678']


def main():
    idx_grade, _ = M.carica_indice_grade_esteso()
    idx_grade_per_slug = collections.defaultdict(dict)
    for (slug, data), grade in idx_grade.items():
        idx_grade_per_slug[slug][data] = grade
    lega_di = AG.indice_lega()

    fixtures = sorted({os.path.basename(f)[len('formazioni_'):-len('.json')]
                       for f in glob.glob('analisi_manager/dati/formazioni_football-*.json')})

    print(f'GRUPPO B (verifica unica): {GRUPPO_B}')
    risultati = []
    for man in GRUPPO_B:
        mf = f'dati_globali/manager_{man}.json'
        if not os.path.exists(mf):
            continue
        d = json.load(open(mf, encoding='utf-8'))
        giornate = d.get('giornate') or {}
        for gw in fixtures:
            giornate_gw = giornate.get(gw)
            if not giornate_gw:
                continue
            r = F.elabora_coppia(man, gw, giornate_gw, lega_di, idx_grade_per_slug)
            if r:
                risultati.append(r)

    print(f'coppie (manager,GW) valide gruppo B: {len(risultati)}')
    with open('analisi_manager/p12_backtest_manager_full_B_out.json', 'w', encoding='utf-8') as fh:
        json.dump({'gruppo_b': GRUPPO_B, 'risultati_B': risultati}, fh, ensure_ascii=False, indent=1)
    print('salvato analisi_manager/p12_backtest_manager_full_B_out.json')


if __name__ == '__main__':
    main()
