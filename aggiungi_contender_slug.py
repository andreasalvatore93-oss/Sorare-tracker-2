"""Riempie lo slug della formazione nelle arene gia' in archivio.

L'archivio e' stato scaricato prima che servisse: senza quello slug non si
puo' rileggere la formazione schierata, e senza le formazioni non si misura
quanto ci prende il modello. Non e' ricostruibile a tavolino (contiene un
UUID), ma basta rileggere l'INDICE delle giornate -- una query per giornata,
non una per arena.

Uso (su Actions, servono i segreti):  python aggiungi_contender_slug.py
"""
import json
import sys

import traccia_arene as t

OUT = t.OUT


def main():
    d = json.load(open(OUT, encoding='utf-8'))
    arene = d['arene']
    manca = [r for r in arene if not r.get('contender_slug')]
    giornate = sorted({r['fixture'] for r in manca})
    print(f'{len(arene)} arene | {len(manca)} senza slug | {len(giornate)} giornate')

    chi = t.graphql('{ currentUser { nickname } }', {})
    if not ((chi.get('data') or {}).get('currentUser') or {}).get('nickname'):
        print('NON AUTENTICATO: l\'indice richiede il login.')
        return 2

    per_slug = {}
    for i, fx in enumerate(giornate, 1):
        arene_fx, _fine, _premi = t.arene_della_giornata(fx)
        for slug, _nome, _costo, contender in arene_fx:
            if contender:
                per_slug[(fx, slug)] = contender
        if i % 10 == 0 or i == len(giornate):
            print(f'[{i}/{len(giornate)}] {fx}')

    riempite = 0
    for r in arene:
        if r.get('contender_slug'):
            continue
        c = per_slug.get((r['fixture'], r['slug']))
        if c:
            r['contender_slug'] = c
            riempite += 1

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f'\nriempite {riempite} su {len(manca)}')
    if riempite < len(manca):
        print('Le mancanti sono arene la cui formazione Sorare non espone piu\'.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
