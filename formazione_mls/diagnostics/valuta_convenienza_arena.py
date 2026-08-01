"""Conviene pagare 300 essenze per entrare in un'arena?

REGOLE (dall'utente): ogni arena ha 10 partecipanti, si gioca contro altre 9
persone (non contro il banco). Costo d'ingresso 300 essenze. Premi: 1o 1300,
2o 900, 3o 500. Chi arriva dal 4o in giu' prende zero.

Da giocatore MEDIO il conto e' gia' negativo: (1300+900+500)/10 = 270 contro
300 di costo, cioe' -30 a partita. L'arena non e' un gioco a somma zero fra i
partecipanti: il banco trattiene il 10%.

Quindi la domanda vera non e' "quanto devo fare" ma "quanto devo essere
MIGLIORE degli altri nove" perche' il valore atteso torni positivo.

METODO. Gli avversari sono altri manager, quindi la distribuzione dei loro
punteggi si approssima con quella delle formazioni reali ricostruite dai dati
(stessa procedura di misura_allocazione_formazioni). Si simula: 9 avversari
pescati da quella distribuzione, io con un vantaggio medio di X punti, e si
contano i piazzamenti.

Uso:  python formazione_mls/diagnostics/valuta_convenienza_arena.py
"""
import collections
import glob
import json
import os
import random
import statistics

COSTO = float(os.environ.get('COSTO', '300'))
PREMI = [float(x) for x in os.environ.get('PREMI', '1300,900,500').split(',')]
PARTECIPANTI = int(os.environ.get('PARTECIPANTI', '10'))
SLOT = 5
N_TRIALS = int(os.environ.get('N_TRIALS', '30000'))


def carica():
    per_data = collections.defaultdict(list)
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
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
                per_data[data].append(v['score'])
    return {k: v for k, v in per_data.items() if len(v) >= 40}


def main():
    per_data = carica()
    date = sorted(per_data)
    random.seed(13)

    # distribuzione dei totali di una formazione da 5 "media di mercato"
    totali = []
    for _ in range(20000):
        d = random.choice(date)
        totali.append(sum(random.sample(per_data[d], SLOT)))
    media = statistics.mean(totali)
    print(f'formazione media di mercato: {media:.1f} pt '
          f'(dev.std {statistics.pstdev(totali):.1f}, {len(date)} giornate)')
    print(f'arena: {PARTECIPANTI} partecipanti, costo {COSTO:.0f}, '
          f'premi {"/".join(str(int(p)) for p in PREMI)}\n')

    print(f'{"vantaggio":>10} {"1o":>7} {"2o":>7} {"3o":>7} {"a premio":>9} '
          f'{"valore atteso":>14}')
    soglia = None
    for vantaggio in range(0, 61, 5):
        p = [0, 0, 0]
        for _ in range(N_TRIALS):
            d = random.choice(date)
            io = sum(random.sample(per_data[d], SLOT)) + vantaggio
            rivali = [sum(random.sample(per_data[d], SLOT))
                      for _ in range(PARTECIPANTI - 1)]
            pos = sum(1 for r in rivali if r > io)
            if pos < 3:
                p[pos] += 1
        pr = [x / N_TRIALS for x in p]
        ev = sum(q * v for q, v in zip(pr, PREMI)) - COSTO
        if soglia is None and ev > 0:
            soglia = vantaggio
        print(f'{vantaggio:>9}+ {pr[0]:6.1%} {pr[1]:6.1%} {pr[2]:6.1%} '
              f'{sum(pr):8.1%} {ev:+13.0f}')

    print()
    if soglia is None:
        print('  Nessun vantaggio fino a +60 rende positiva l\'arena.')
    else:
        print(f'  PAREGGIO intorno a +{soglia} pt sopra la formazione media '
              f'({media + soglia:.0f} pt attesi).')


if __name__ == '__main__':
    main()
