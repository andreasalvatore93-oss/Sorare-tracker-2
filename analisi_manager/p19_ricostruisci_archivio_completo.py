"""PASSO 1 (BRIEF_SONNET_SOGLIE_DEFINITIVE): ricostruisce archivio completo
delle 673 arene da analisi_manager/p11_pool.json nel formato che
consiglio_arena.py si aspetta. NON sovrascrive arene_storico.json.
"""
import json

d = json.load(open('analisi_manager/p11_pool.json', encoding='utf-8'))

arene = []
scartate = 0
for fx, v in d.items():
    for a in v.get('slot', []):
        punteggi = a.get('punteggi') or []
        if len(punteggi) < 5:
            scartate += 1
            continue
        arene.append({
            'fixture': fx,
            'slug': a['slug'],
            'tipo': a['tipo'],
            'costo': a.get('costo'),
            'partecipanti': a.get('partecipanti'),
            'punteggi': punteggi,
            'mio_score': a.get('mio_score'),
            'mio_rank': a.get('mio_rank'),
            'premio_essenze': a.get('premio_essenze'),
            'rank_premiato': a.get('rank_premiato'),
        })

out = {'aggiornato': 'ricostruito da p11_pool.json (673 arene, BRIEF_SONNET_SOGLIE_DEFINITIVE 08/08/2026)',
       'arene': arene}
json.dump(out, open('dati_globali/arene_storico_full.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('scritte', len(arene), 'scartate (meno di 5 punteggi)', scartate)

import collections
tipi = collections.Counter(a['tipo'] for a in arene)
print(tipi)
con_premio = sum(1 for a in arene if a.get('rank_premiato') and a.get('premio_essenze'))
print('con premio osservato', con_premio)
per_tipo_premio = collections.Counter(a['tipo'] for a in arene if a.get('rank_premiato') and a.get('premio_essenze'))
print(per_tipo_premio)
