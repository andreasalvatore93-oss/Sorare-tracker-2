"""PASSO 2 (BRIEF_SONNET_APPLICA_SOGLIE_2026-08-09 §4): costruisce
dati_globali/arene_storico_full_v3.json = arene_storico_full_v2.json
(rigenerato con dedup fixato, vedi p25_archivio_v2.py) + i premi VERI per
posizione di dati_globali/premi_arene_2026-08-08.json (1.677 arene, jackpot
inclusi, letti da rewardsConfig), agganciati per slug.

Ogni riga dell'archivio v2 che ha un corrispondente in premi_arene prende un
campo in piu', 'premi_veri_per_posizione' (lista [pos, premio], stesso
formato della fonte). Le righe senza corrispondenza (es. le 673 del vecchio
p11_pool prima del download premi, o 'arena division'/'arena uncapped' non
scaricate) restano come in v2, senza quel campo: consiglio_arena.py deve
continuare a funzionare su di loro come oggi (fallback a premio_osservato()
dall'archivio).

NON sovrascrive v2. SOLO MISURA/PREPARAZIONE, nessun file di produzione
toccato.
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def main():
    v2 = json.load(open('dati_globali/arene_storico_full_v2.json', encoding='utf-8'))
    premi = json.load(open('dati_globali/premi_arene_2026-08-08.json', encoding='utf-8'))

    premi_per_slug = {a['slug']: a['premi_per_posizione'] for a in premi['arene']}

    n_agganciate = 0
    finale = []
    for r in v2['arene']:
        r = dict(r)
        pp = premi_per_slug.get(r['slug'])
        if pp is not None:
            r['premi_veri_per_posizione'] = pp
            n_agganciate += 1
        finale.append(r)

    print(f"arene v2: {len(v2['arene'])}, con premi veri agganciati: {n_agganciate}")

    out = {'aggiornato': 'p28_archivio_v3.py: arene_storico_full_v2.json (dedup fixato) '
                          '+ premi_arene_2026-08-08.json (premi veri rewardsConfig, jackpot inclusi) '
                          'agganciati per slug in premi_veri_per_posizione',
           'arene': finale}
    json.dump(out, open('dati_globali/arene_storico_full_v3.json', 'w', encoding='utf-8'),
               ensure_ascii=False, indent=1)
    print("scritto dati_globali/arene_storico_full_v3.json")


if __name__ == '__main__':
    main()
