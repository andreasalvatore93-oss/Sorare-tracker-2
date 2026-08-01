"""Sei formazioni In Season: concentrare i migliori o spalmare?

In Season e' gratis, max 6 formazioni da 5, e ogni formazione insegue lo STESSO
gradino (340/360/400/420/460 -- si sale uno alla volta, superarlo non vale nulla
in piu'). Ogni formazione porta premio per conto suo, quindi il totale da
massimizzare e' la SOMMA delle probabilita' di superare il gradino.

La domanda: dato un numero fisso di carte, conviene fare 2-3 formazioni forti e
il resto deboli, oppure 6 formazioni equivalenti?

La risposta dipende da dove sta il gradino. Sotto la soglia P(superare) cresce
in modo CONVESSO col punteggio atteso: concentrare paga. Sopra la soglia
diventa concava: spalmare paga. Qui si misura su dati veri invece di fidarsi
della teoria.

Uso:  python formazione_mls/diagnostics/allocazione_in_season.py
      GRADINO=400 N_FORMAZIONI=6
"""
import collections
import glob
import json
import os
import random
import statistics

GRADINO = float(os.environ.get('GRADINO', '400'))
K = int(os.environ.get('N_FORMAZIONI', '6'))
SLOT = 5
N_TRIALS = int(os.environ.get('N_TRIALS', '4000'))
# bonus medi realmente applicati (XP/collezione + capitano) misurati sulle
# formazioni reali dell'utente: base 291 -> 363 totale, cioe' circa +25%
MOLTIPLICATORE = float(os.environ.get('MOLTIPLICATORE', '1.25'))


def carica():
    per_slug = collections.defaultdict(list)
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict) or v.get('scoreStatus') != 'FINAL':
                continue
            data = ((v.get('anyGame') or {}).get('date') or '')[:10]
            if data and v.get('score') is not None:
                per_slug[slug].append((data, v['score']))
    stat, per_data = {}, collections.defaultdict(list)
    for s, v in per_slug.items():
        if len(v) < 10:
            continue
        stat[s] = (statistics.mean(x[1] for x in v), dict(v))
        for d, _sc in v:
            per_data[d].append(s)
    return stat, per_data


def main():
    stat, per_data = carica()
    n_carte = K * SLOT
    date = [d for d, v in per_data.items() if len(v) >= n_carte]
    print(f'{len(stat)} giocatori, {len(date)} giornate | {K} formazioni da {SLOT} '
          f'= {n_carte} carte | gradino {GRADINO:.0f}')

    random.seed(23)
    conteggi = {'concentrata': 0, 'distribuita': 0}
    totali = {'concentrata': [], 'distribuita': []}
    for _ in range(N_TRIALS):
        d = random.choice(date)
        rosa = random.sample(per_data[d], n_carte)
        rosa.sort(key=lambda s: -stat[s][0])

        conc = [rosa[i * SLOT:(i + 1) * SLOT] for i in range(K)]
        dist = [[] for _ in range(K)]
        for i, s in enumerate(rosa):
            j = i % K
            if (i // K) % 2:
                j = K - 1 - j
            dist[j].append(s)

        for nome, gruppi in (('concentrata', conc), ('distribuita', dist)):
            for f in gruppi:
                tot = sum(stat[s][1][d] for s in f) * MOLTIPLICATORE
                totali[nome].append(tot)
                if tot >= GRADINO:
                    conteggi[nome] += 1

    print()
    for nome in ('concentrata', 'distribuita'):
        media = statistics.mean(totali[nome])
        quota = conteggi[nome] / N_TRIALS
        print(f'  {nome:12s} media formazione {media:6.1f} | '
              f'formazioni a premio per giornata: {quota:.2f} su {K}')
    delta = conteggi['concentrata'] - conteggi['distribuita']
    print(f'\n  -> ' + ('CONCENTRARE' if delta > 0 else 'DISTRIBUIRE') +
          f' ({abs(delta) / N_TRIALS:.2f} formazioni a premio in piu\' per giornata)')


if __name__ == '__main__':
    main()
