"""BRIEF_SONNET_GRADE_ARENE_2026-08-08.txt §8bis.1 -- i tre file di grade
che nessuna funzione di produzione legge (storico_grade_Forward_ampio_
20260806.json, storico_grade_Goalkeeper_20260806.json, i 5 grade_snapshot_
*football-4-7-aug-2026*): sono scarti consapevoli o raccolte dimenticate?

Metodo (opzione b del brief, la piu' economica: nessuna query di rete):
sulle coppie (slug, data) presenti SIA nel file non letto SIA nell'indice
di produzione (`carica_indice_grade_esteso`), i grade coincidono? Se si',
il file e' buono e va aggiunto; se divergono in modo non sporadico, e'
dubbio e non va usato.

Nessuna modifica alla produzione, nessuna query di rete.
"""
import os
import sys
import io
import json
import glob
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M


def registra(idx, slug, dt, grade):
    gn = S21.GRADE_NUM.get(grade)
    if gn is None or not dt or not slug:
        return
    idx.setdefault(slug, []).append((dt[:10], gn))


def carica_flat(path):
    idx = collections.defaultdict(list)
    for r in json.load(open(path, encoding='utf-8')):
        registra(idx, r.get('slug'), r.get('game_date'), r.get('grade'))
    return idx


def carica_snapshot():
    idx = collections.defaultdict(list)
    n_righe = 0
    for fp in glob.glob('analisi_manager/dati/grade_snapshot_*'):
        d = json.load(open(fp, encoding='utf-8'))
        n_righe += len(d)
        for r in d:
            registra(idx, r.get('slug'), r.get('game_date'), r.get('grade'))
    return idx, n_righe


def confronta(nome, idx_non_letto, idx_prod):
    n_comuni = coincidono = 0
    divergenze = []
    for slug, entries in idx_non_letto.items():
        prod_entries = idx_prod.get(slug)
        if not prod_entries:
            continue
        prod_map = dict(prod_entries)
        viste = set()
        for dt, gn in entries:
            if dt in viste:
                continue
            viste.add(dt)
            if dt in prod_map:
                n_comuni += 1
                if prod_map[dt] == gn:
                    coincidono += 1
                else:
                    divergenze.append([slug, dt, prod_map[dt], gn])
    print(f'{nome}: coppie in comune={n_comuni}  coincidono={coincidono}  divergono={len(divergenze)}')
    for x in divergenze[:15]:
        print('   ', x)
    return {'n_comuni': n_comuni, 'coincidono': coincidono, 'divergenze': divergenze}


def main():
    idx_prod, _ = M.carica_indice_grade_esteso()
    print(f'indice di produzione: {len(idx_prod)} slug distinti')

    fwd_ampio = carica_flat('analisi_manager/dati/storico_grade_Forward_ampio_20260806.json')
    gk = carica_flat('analisi_manager/dati/storico_grade_Goalkeeper_20260806.json')
    snap, n_snap_righe = carica_snapshot()

    print(f'\nForward_ampio: {len(fwd_ampio)} slug distinti')
    print(f'Goalkeeper:    {len(gk)} slug distinti')
    print(f'grade_snapshot (5 file): {len(snap)} slug distinti, {n_snap_righe} righe totali')

    esito = {}
    for nome, idx_non_letto in (('Forward_ampio', fwd_ampio), ('Goalkeeper', gk), ('grade_snapshot', snap)):
        fuori = [s for s in idx_non_letto if s not in idx_prod]
        print(f'\n{nome}: {len(fuori)}/{len(idx_non_letto)} slug fuori dall\'indice di produzione')
        esito[nome] = {'n_slug': len(idx_non_letto), 'fuori_indice': len(fuori)}
        esito[nome]['confronto'] = confronta(nome, idx_non_letto, idx_prod)

    mancanti = json.load(open('analisi_manager/p20_grade_arene_slug_mancanti_produzione.json', encoding='utf-8'))['slug']
    coperti_fwd = set(s for s in mancanti if s in fwd_ampio)
    coperti_gk = set(s for s in mancanti if s in gk)
    coperti_unione = coperti_fwd | coperti_gk
    restanti = sorted(set(mancanti) - coperti_unione)
    print(f'\nSUL PERIMETRO ARENE ({len(mancanti)} mancanti dall\'indice di produzione):')
    print(f'  coperti da Forward_ampio: {len(coperti_fwd)}')
    print(f'  coperti da Goalkeeper:    {len(coperti_gk)}')
    print(f'  coperti dall\'unione (file affidabili, grade_snapshot ESCLUSO): {len(coperti_unione)}')
    print(f'  DA SCARICARE DAVVERO: {len(restanti)}')

    with open('analisi_manager/p20_grade_arene_slug_da_scaricare_169.json', 'w', encoding='utf-8') as fh:
        json.dump({'n': len(restanti), 'slug': restanti}, fh, ensure_ascii=False, indent=1)

    esito['perimetro'] = {'mancanti_produzione': len(mancanti), 'coperti_fwd_ampio': len(coperti_fwd),
                           'coperti_goalkeeper': len(coperti_gk), 'coperti_unione': len(coperti_unione),
                           'da_scaricare': len(restanti)}
    with open('analisi_manager/p20_grade_arene_cross_validation_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_grade_arene_cross_validation_out.json')
    print('salvato analisi_manager/p20_grade_arene_slug_da_scaricare_169.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
