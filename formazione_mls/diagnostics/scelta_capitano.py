"""Il capitano va scelto per punteggio atteso o per esplosivita'?

Il capitano prende +50% (In Season/All Stars) o +20% (Arena), quindi moltiplica
anche la sua VARIANZA per lo stesso fattore. Oggi si sceglie chi ha il
punteggio atteso piu' alto. Ma se l'obiettivo e' superare una soglia alta, il
capitano giusto potrebbe essere il piu' volatile, non il piu' alto.

Tre strategie a confronto, sulla stessa formazione:
  ATTESO      capitano = punteggio atteso piu' alto (comportamento attuale)
  VOLATILE    capitano = dispersione storica piu' alta
  MISTO       capitano = atteso + 0.5 * dispersione

Si misura P(superare soglia) a soglie crescenti, su giornate reali.

Uso:  python formazione_mls/diagnostics/scelta_capitano.py
      BONUS=0.5   (0.2 per le arene)
"""
import collections
import glob
import json
import os
import random
import statistics

BONUS = float(os.environ.get('BONUS', '0.5'))
SLOT = 5
N_TRIALS = int(os.environ.get('N_TRIALS', '20000'))


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
        p = [x[1] for x in v]
        stat[s] = (statistics.mean(p), statistics.pstdev(p), dict(v))
        for d, _sc in v:
            per_data[d].append(s)
    return stat, per_data


def main():
    stat, per_data = carica()
    date = [d for d, v in per_data.items() if len(v) >= SLOT * 3]
    print(f'{len(stat)} giocatori, {len(date)} giornate | bonus capitano +{BONUS:.0%}')

    random.seed(21)
    tot = {'atteso': [], 'volatile': [], 'misto': []}
    for _ in range(N_TRIALS):
        d = random.choice(date)
        squadra = random.sample(per_data[d], SLOT)
        reali = {s: stat[s][2][d] for s in squadra}
        base = sum(reali.values())
        cap = {
            'atteso': max(squadra, key=lambda s: stat[s][0]),
            'volatile': max(squadra, key=lambda s: stat[s][1]),
            'misto': max(squadra, key=lambda s: stat[s][0] + 0.5 * stat[s][1]),
        }
        for k, c in cap.items():
            tot[k].append(base + reali[c] * BONUS)

    rif = sorted(tot['atteso'])
    print(f'\n{"strategia":>10} {"media":>8} ' +
          ' '.join(f'{"P>"+str(int(rif[int(q*len(rif))-1])):>9}' for q in (0.5, 0.75, 0.9, 0.95)))
    for k, v in tot.items():
        riga = []
        for q in (0.5, 0.75, 0.9, 0.95):
            s = rif[int(q * len(rif)) - 1]
            riga.append(sum(1 for x in v if x > s) / len(v) * 100)
        print(f'{k:>10} {statistics.mean(v):8.1f} ' +
              ' '.join(f'{x:8.1f}%' for x in riga))


if __name__ == '__main__':
    main()
