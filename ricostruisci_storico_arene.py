"""Ricostruisce lo storico completo delle arene, giornata per giornata.

traccia_arene.py legge una giornata; questo lo ripete su tutte quelle concluse
e accumula. Serve per tarare il consigliere d'ingresso: la MEDIANA della singola
arena e' il campo da battere, e su una giornata sola non si tara niente.

Riprende da dove si era fermato: le giornate gia' presenti in
dati_globali/arene_storico.json non vengono riscaricate, quindi il lavoro si
puo' interrompere e rilanciare senza perdere nulla.

Uso:  DA=2025-08-01 python ricostruisci_storico_arene.py
"""
import datetime
import json
import os
import statistics
import sys

import traccia_arene as t

OUT = t.OUT
DA = os.environ.get('DA', '2025-08-01')


def giornate_concluse():
    """Slug delle giornate gia' chiuse, dalla piu' vecchia, a partire da DA."""
    query = """query($after: String) {
      so5 { so5Fixtures(first: 50, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes { slug endDate } } } }"""
    tutte, cur = [], None
    for _ in range(30):
        d = t.graphql(query, {'after': cur})
        if d.get('errors'):
            print('errore elenco giornate:', json.dumps(d['errors'])[:160])
            break
        c = d['data']['so5']['so5Fixtures']
        tutte += c['nodes']
        if not c['pageInfo']['hasNextPage']:
            break
        cur = c['pageInfo']['endCursor']
    oggi = datetime.datetime.now(datetime.timezone.utc).isoformat()
    fuori = [x for x in tutte
             if x['endDate'] and DA <= x['endDate'][:10] and x['endDate'] < oggi]
    fuori.sort(key=lambda x: x['endDate'])
    return [x['slug'] for x in fuori]


def main():
    fatte, raccolta = set(), []
    if os.path.exists(OUT):
        vecchio = json.load(open(OUT, encoding='utf-8'))
        raccolta = vecchio.get('arene') or []
        for r in raccolta:
            # le righe salvate prima che esistesse il campo non ce l'hanno:
            # la mediana si ricava dai punteggi, che ci sono sempre
            if r.get('mediana') is None and r.get('punteggi'):
                r['mediana'] = statistics.median(r['punteggi'])
        # anche le giornate senza nessuna arena vanno segnate come viste, se no
        # ad ogni rilancio si riscaricano tutte da capo (un'ora buttata)
        fatte = set(vecchio.get('giornate_viste') or [])
        fatte |= {r['fixture'] for r in raccolta}
        # Ricostruendo in piu' riprese la stessa giornata puo' finire in
        # archivio due volte, e i duplicati gonfiano i totali (75 righe su 673
        # la prima volta). Una sola riga per (giornata, arena): quella e'
        # l'identita' vera di un ingresso.
        uniche = {}
        for r in raccolta:
            uniche[(r['fixture'], r['slug'])] = r
        if len(uniche) != len(raccolta):
            print(f'rimossi {len(raccolta) - len(uniche)} duplicati')
        raccolta = list(uniche.values())

    io = os.environ.get('NICKNAME', 'Crowss').strip().lower()
    slugs = giornate_concluse()
    da_fare = [s for s in slugs if s not in fatte]
    print(f'{len(slugs)} giornate concluse dal {DA} | '
          f'{len(fatte)} gia\' viste | {len(da_fare)} da scaricare')

    for i, fx in enumerate(da_fare, 1):
        arene, fine, premi = t.arene_della_giornata(fx)
        nuove = 0
        for slug, nome, costo, contender in arene:
            nodi = t.classifica(slug)
            if not nodi:
                continue
            punteggi = sorted((n['score'] for n in nodi), reverse=True)
            mia = next((n for n in nodi
                        if (n.get('user') or {}).get('nickname', '').lower() == io), None)
            rank_premio, essenze = premi.get(slug, (None, 0))
            raccolta.append({
                'fixture': fx, 'fine': fine, 'slug': slug, 'tipo': nome,
                'contender_slug': contender,
                'costo': costo, 'partecipanti': len(nodi),
                'mediana': statistics.median(punteggi),
                'primo': punteggi[0],
                'terzo': punteggi[2] if len(punteggi) > 2 else None,
                'premio_essenze': essenze, 'rank_premiato': rank_premio,
                'punteggi': punteggi,
                'mio_rank': mia.get('ranking') if mia else None,
                'mio_score': mia.get('score') if mia else None})
            nuove += 1
        print(f'[{i}/{len(da_fare)}] {fx} -> {nuove} arene')
        fatte.add(fx)
        # si salva ad ogni giornata: un'interruzione non butta via il lavoro
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'aggiornato': datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
                'giornate_viste': sorted(fatte),
                'arene': raccolta}, f, ensure_ascii=False, indent=1)

    print(f'\n{len(raccolta)} arene in archivio')
    if not raccolta:
        return
    per_tipo = {}
    for r in raccolta:
        per_tipo.setdefault(r['tipo'], []).append(r)
    print('\n=== MEDIANA DEL CAMPO PER TIPO (il numero da battere)')
    for tipo, v in sorted(per_tipo.items()):
        med = [r['mediana'] for r in v if r.get('mediana') is not None]
        if not med:
            continue
        print(f'  {tipo:10s} {len(v):>4} arene | mediana tipica {statistics.median(med):6.1f} '
              f'| min {min(med):6.1f} | max {max(med):6.1f}')


if __name__ == '__main__':
    sys.exit(main())
