"""taratura_formazioni_sintetiche — la soglia d'ingresso, tarata come si deve.

IL PROBLEMA. La soglia oltre la quale conviene pagare l'ingresso di un'arena e'
il numero su cui l'utente vuole agganciare gli acquisti di carte: un punto
sposta la scelta fra un giocatore e un altro. Due strade davano risposte
diverse:

  * dalle 306 formazioni vere del backtest: **269.1**, ma con un intervallo al
    90% fra 258.8 e 273.9 -- quindici punti, inutilizzabile
  * dalla taratura per singolo giocatore (69.151 coppie): **276.3**, molto piu'
    precisa ma **ignora il capitano**, che moltiplica per 1.2 uno dei cinque e
    sposta sia il previsto sia il realizzato

LA SOLUZIONE. Costruire formazioni SINTETICHE dalle coppie per giocatore: si
prendono cinque giocatori che hanno giocato lo stesso giorno, si nomina
capitano quello col punteggio previsto piu' alto (come fa il generatore), e si
sommano previsto e realizzato applicando il x1.2. Si ottengono decine di
migliaia di formazioni con la struttura giusta, invece di 306.

Le formazioni sintetiche non sono formazioni vere -- non rispettano il cap L10
ne' i vincoli di ruolo -- ma per TARARE la relazione fra previsto e realizzato
questo non serve: serve solo che la struttura del punteggio sia la stessa.

Uso:  python taratura_formazioni_sintetiche.py
      python taratura_formazioni_sintetiche.py --n 40000
"""
import argparse
import collections
import json
import math
import random
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

COPPIE = 'dati_globali/taratura_coppie.json'
CAPITANO = 0.2   # +20% in arena (l'unico bonus che esiste)
RUOLI_TIPICI = ['Goalkeeper', 'Defender', 'Midfielder', 'Forward', 'Midfielder']


def costruisci(coppie, quante, seme=5):
    """Formazioni sintetiche: cinque giocatori della stessa data."""
    per_data = collections.defaultdict(list)
    for c in coppie:
        per_data[c['data']].append(c)
    date = [d for d, v in per_data.items() if len(v) >= 5]
    rnd = random.Random(seme)
    out = []
    for _ in range(quante):
        d = date[rnd.randrange(len(date))]
        cinque = rnd.sample(per_data[d], 5)
        # capitano al previsto piu' alto, come fa il generatore
        cap = max(range(5), key=lambda i: cinque[i]['previsto'])
        prev = sum(x['previsto'] for x in cinque) + CAPITANO * cinque[cap]['previsto']
        reale = sum(x['reale'] for x in cinque) + CAPITANO * cinque[cap]['reale']
        out.append((prev, reale))
    return out, len(date)


def retta(X, Y):
    mx, my = statistics.mean(X), statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    return a, b, statistics.pstdev([y - (a + b * x) for x, y in zip(X, Y)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=40000)
    ap.add_argument('--json', default='dati_globali/taratura_formazione.json')
    args = ap.parse_args()

    coppie = json.load(open(COPPIE, encoding='utf-8'))
    print(f'{len(coppie)} coppie giocatore/partita in archivio')
    form, n_date = costruisci(coppie, args.n)
    X = [p for p, _ in form]
    Y = [r for _, r in form]
    a, b, sd = retta(X, Y)
    print(f'{len(form)} formazioni sintetiche su {n_date} giornate\n')
    print('=== TARATURA DELLA FORMAZIONE (capitano incluso)')
    print(f'  realizzato = {a:.2f} + {b:.3f} x previsto')
    print(f'  dispersione residua: {sd:.2f} punti')
    print(f'  bias medio: {statistics.mean(x - y for x, y in zip(X, Y)):+.2f}')

    # incertezza della retta: bootstrap
    rnd = random.Random(9)
    par = []
    for _ in range(60):
        idx = [rnd.randrange(len(form)) for _ in range(len(form))]
        par.append(retta([X[i] for i in idx], [Y[i] for i in idx]))
    print(f'\n  incertezza (bootstrap): intercetta ±{statistics.pstdev([p[0] for p in par]):.2f}, '
          f'pendenza ±{statistics.pstdev([p[1] for p in par]):.4f}')

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump({'n_formazioni': len(form), 'intercetta': a, 'pendenza': b,
                   'dispersione': sd}, fh, indent=1)
    print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
