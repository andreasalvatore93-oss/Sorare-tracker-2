"""QUOTA_MINIMA: la perdita estiva colpisce anche leghe SENZA preseason (13/08/2026).

Segue p33 (broad-based sui tipi arena). Testa l'ipotesi non provata di Opus
("mercato/precampionato rende gli attesi di confine troppo ottimisti
d'estate"): se fosse quello il meccanismo, le leghe che NON hanno una pausa
estiva/mercato in corso (MLS, K League -- giocano tutta l'estate, nessuna
preseason a luglio-agosto) non dovrebbero mostrare l'effetto.

Lega dedotta dal CAPITANO della formazione (proxy: le arene all-star possono
mischiare leghe diverse nella stessa formazione, quindi non e' la lega
dell'intera formazione, solo un'indicazione). Nessuna query di rete: usa
analizza_gw.indice_lega() sulla cache gia' in repo.

Uso: python analisi_manager/p34_quota_minima_per_lega.py
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
import analizza_gw as AG

TEST_START = datetime.datetime(2026, 7, 20)


def fascia_confine(rows, q_lo=0.0, q_hi=0.15):
    out = []
    for r in rows:
        soglia_lo = r['soglia'] + r['costo'] * q_lo / r['guad']
        soglia_hi = r['soglia'] + r['costo'] * q_hi / r['guad']
        if (r['atteso_G'] >= soglia_lo) != (r['atteso_G'] >= soglia_hi):
            out.append(r)
    return out


def main():
    lega_di = AG.indice_lega()
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
            r2['lega_capitano'] = lega_di.get(r2['capitano']) or 'sconosciuta'
            righe.append(r2)

    test = [r for r in righe if r['dt'] >= TEST_START]
    confine = fascia_confine(test)
    print(f'n confine test: {len(confine)}')

    per_lega = collections.defaultdict(list)
    for r in confine:
        per_lega[r['lega_capitano']].append(r['gain_reale_se_entra'])
    print()
    print('--- per lega del capitano (proxy, non la lega dell\'intera formazione) ---')
    for lega, gains in sorted(per_lega.items(), key=lambda x: -len(x[1])):
        media = sum(gains) / len(gains)
        print(f'  {lega:20s} n={len(gains):3d}  media={media:+7.1f}')

    print()
    print('LETTURA: MLS e K League NON hanno preseason/mercato a luglio-agosto')
    print('(giocano tutta l\'estate). Se fossero negative anche loro, l\'ipotesi')
    print('"mercato estivo" e\' indebolita (l\'effetto non e\' solo da preseason).')
    mls = per_lega.get('mls', [])
    kleague = per_lega.get('kleague', [])
    if mls:
        print(f'  mls:     n={len(mls)}  media={sum(mls)/len(mls):+.1f}')
    if kleague:
        print(f'  kleague: n={len(kleague)}  media={sum(kleague)/len(kleague):+.1f}')


if __name__ == '__main__':
    main()
