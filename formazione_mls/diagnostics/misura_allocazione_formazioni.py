"""Con le stesse carte, meglio poche formazioni forti o tante mediocri?

Il premio grosso scatta quando ALMENO UNA formazione supera il target. Non
conta quanto e' forte la migliore in media: conta la probabilita' che almeno
una sfondi. Sono obiettivi diversi e possono suggerire allocazioni opposte.

Le carte sono un vincolo: ogni carta sta in una formazione sola, quindi K
formazioni da 5 consumano 5K carte. Con le arene illimitate il tetto non e' il
numero di ingressi ma la rosa.

Due strategie a confronto, a parita' di carte:
  CONCENTRATA  i 5 migliori nella prima, i 5 dopo nella seconda, e cosi' via
               (e' quello che fa oggi il generatore: greedy in fila)
  DISTRIBUITA  serpentina, cosi' ogni formazione riceve un mix di alti e bassi

Il punteggio realizzato non e' simulato a caso: si campiona una GIORNATA vera e
si usano i punteggi reali di quei giocatori, cosi' le correlazioni fra compagni
restano quelle osservate.

Uso:  python formazione_mls/diagnostics/misura_allocazione_formazioni.py
      K_FORMAZIONI=6  TARGET_PCT=90
"""
import collections
import glob
import json
import os
import random
import statistics

K = int(os.environ.get('K_FORMAZIONI', '6'))
SLOT = 5
N_TRIALS = int(os.environ.get('N_TRIALS', '4000'))
TARGET_PCT = float(os.environ.get('TARGET_PCT', '90'))


def carica():
    """data -> [(slug, score)] di quella giornata."""
    per_data = collections.defaultdict(list)
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
                per_data[data].append((slug, v['score']))
    return {k: v for k, v in per_data.items() if len(v) >= K * SLOT}


def medie_storiche(per_data):
    tot = collections.defaultdict(list)
    for _d, righe in per_data.items():
        for slug, sc in righe:
            tot[slug].append(sc)
    return {s: statistics.mean(v) for s, v in tot.items() if len(v) >= 5}


def allocazioni(ordinati):
    """(concentrata, distribuita) come liste di K formazioni da SLOT indici."""
    conc = [ordinati[i * SLOT:(i + 1) * SLOT] for i in range(K)]
    dist = [[] for _ in range(K)]
    giro = 0
    for i, x in enumerate(ordinati[:K * SLOT]):
        j = i % K
        if giro % 2:
            j = K - 1 - j
        dist[j].append(x)
        if (i + 1) % K == 0:
            giro += 1
    return conc, dist


def main():
    per_data = carica()
    medie = medie_storiche(per_data)
    date = sorted(per_data)
    print(f'giornate utilizzabili: {len(date)} | K={K} formazioni da {SLOT}')

    random.seed(9)
    tot_conc, tot_dist = [], []
    best_conc, best_dist = [], []
    for _ in range(N_TRIALS):
        data = random.choice(date)
        righe = [(s, sc) for s, sc in per_data[data] if s in medie]
        if len(righe) < K * SLOT:
            continue
        # "carte possedute": un campione casuale di giocatori di quella giornata
        rosa = random.sample(righe, K * SLOT)
        # ordinati per punteggio ATTESO (media storica), non per il reale
        rosa.sort(key=lambda x: -medie[x[0]])
        conc, dist = allocazioni(rosa)
        tc = [sum(sc for _s, sc in f) for f in conc]
        td = [sum(sc for _s, sc in f) for f in dist]
        tot_conc.append(tc)
        tot_dist.append(td)
        best_conc.append(max(tc))
        best_dist.append(max(td))

    if not best_conc:
        print('dati insufficienti')
        return
    rif = sorted(best_dist)
    target = rif[int(TARGET_PCT / 100 * len(rif)) - 1]
    pc = sum(1 for x in best_conc if x > target) / len(best_conc) * 100
    pd = sum(1 for x in best_dist if x > target) / len(best_dist) * 100
    print(f'\n  target = {target:.0f} pt (il {TARGET_PCT:.0f}mo percentile della migliore)')
    print(f'  CONCENTRATA: almeno una sopra target nel {pc:5.1f}% dei casi   '
          f'(migliore media {statistics.mean(best_conc):.1f})')
    print(f'  DISTRIBUITA: almeno una sopra target nel {pd:5.1f}% dei casi   '
          f'(migliore media {statistics.mean(best_dist):.1f})')
    print('  -> ' + ('CONCENTRARE' if pc > pd else 'DISTRIBUIRE') +
          f' (differenza {abs(pc-pd):.1f} punti percentuali)')


if __name__ == '__main__':
    main()
