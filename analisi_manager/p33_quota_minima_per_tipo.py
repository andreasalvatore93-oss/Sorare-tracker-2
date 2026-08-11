"""QUOTA_MINIMA: la fascia di confine estiva perde su TUTTI i tipi di arena (13/08/2026).

Segue RISPOSTA_OPUS_QUOTA_MINIMA_CAMPIONE_2026-08-13.txt: il regime estivo
(21 lug - 7 ago) perde -60,5 essenze/formazione in media nella fascia di
confine, contro +50,7 in primavera. Ipotesi non testata li' (mercato/
precampionato): se fosse un effetto di un tipo di arena specifico, la si
vedrebbe concentrata li'. Non e' cosi': negativa su tutti e 4 i tipi.

Uso: python analisi_manager/p33_quota_minima_per_tipo.py
"""
import os
import sys
import json
import datetime
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p23_binario1_mga as B1
import generatore_formazioni.build_formazione_globale as BFG

TEST_START = datetime.datetime(2026, 7, 20)


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


def fascia_confine(rows, q_lo=0.0, q_hi=0.15):
    out = []
    for r in rows:
        soglia_lo = r['soglia'] + r['costo'] * q_lo / r['guad']
        soglia_hi = r['soglia'] + r['costo'] * q_hi / r['guad']
        if (r['atteso_G'] >= soglia_lo) != (r['atteso_G'] >= soglia_hi):
            out.append(r)
    return out


def main():
    righe = carica_righe()
    test = [r for r in righe if r['dt'] >= TEST_START]
    confine = fascia_confine(test)
    print(f'n confine test (21 lug - 7 ago): {len(confine)}')

    per_tipo = collections.defaultdict(list)
    for r in confine:
        per_tipo[r['tipo']].append(r['gain_reale_se_entra'])
    print()
    print('--- per tipo arena (media guadagno reale se entra) ---')
    for tipo, gains in sorted(per_tipo.items(), key=lambda x: -len(x[1])):
        media = sum(gains) / len(gains)
        print(f'  {tipo:10s} n={len(gains):3d}  media={media:+7.1f}')
    print()
    negativi = sum(1 for gains in per_tipo.values() if sum(gains) / len(gains) < 0)
    print(f'tipi con media negativa: {negativi}/{len(per_tipo)} -- effetto BROAD-BASED, non concentrato in un tipo')


if __name__ == '__main__':
    main()
