"""Quanto vale la regola d'ingresso, in funzione di quanto sbaglia la previsione.

Il tetto e' noto: saltando col senno di poi gli ingressi sotto la soglia si
passa da +9.800 a +54.700 essenze, cioe' +44.900. Ma quel calcolo conosce il
punteggio realizzato, e il modello no: al momento di schierare ha una
previsione con un errore.

Qui si simula la decisione come sarebbe stata davvero: al posto del punteggio
vero si usa "punteggio vero + rumore", si decide di entrare o no in base a
quello, e poi si incassa il risultato VERO. Ripetuto per diversi livelli di
errore, dice quale precisione serve perche' la regola convenga -- e sotto quale
soglia di precisione conviene invece lasciar perdere.

E' la domanda che decide se agganciare il modello al generatore: con un ROI
gia' positivo (+13.3% fatto a mano) l'onere della prova sta dal lato del
modello.

Uso:  python quanto_serve_precisione.py
"""
import json
import random
import statistics

ARCHIVIO = 'dati_globali/arene_storico.json'
COSTI = {'cap 260': 300, 'Uncapped': 300, 'Beginner': 100}
SOGLIE = {'cap 260': 282.9, 'Uncapped': 305.5, 'Beginner': 281.9}
N_PROVE = 400


def main():
    arene = json.load(open(ARCHIVIO, encoding='utf-8'))['arene']
    righe = [r for r in arene if r['tipo'] in SOGLIE
             and r.get('mio_score') is not None]

    base = sum((r.get('premio_essenze') or 0) - COSTI[r['tipo']] for r in righe)
    tetto = sum((r.get('premio_essenze') or 0) - COSTI[r['tipo']] for r in righe
                if r['mio_score'] >= SOGLIE[r['tipo']])

    print(f'{len(righe)} ingressi | saldo com\'e\' andata {base:+} essenze')
    print(f'tetto col senno di poi {tetto:+} (guadagno {tetto - base:+})\n')

    print(f"{'errore':>7} {'entrate':>8} {'saldo':>9} {'guadagno':>9} {'del tetto':>10}")
    rnd = random.Random(11)
    for sigma in (0, 10, 15, 20, 25, 30, 40, 50, 60):
        saldi, entrate = [], []
        for _ in range(N_PROVE if sigma else 1):
            tot = n = 0
            for r in righe:
                previsto = r['mio_score'] + (rnd.gauss(0, sigma) if sigma else 0)
                if previsto >= SOGLIE[r['tipo']]:
                    tot += (r.get('premio_essenze') or 0) - COSTI[r['tipo']]
                    n += 1
            saldi.append(tot)
            entrate.append(n)
        s = statistics.mean(saldi)
        quota = (s - base) / (tetto - base) * 100 if tetto != base else 0
        print(f'{sigma:>7} {statistics.mean(entrate):>8.0f} {s:>+9.0f} '
              f'{s - base:>+9.0f} {quota:>9.0f}%')

    print()
    print("Come si legge: 'errore' e' di quanto la previsione di una formazione")
    print('sbaglia il punteggio vero, in punti. A errore zero si prende tutto il')
    print("tetto; man mano che cresce si entra in arene sbagliate e si saltano")
    print('quelle buone. Il numero che conta e\' l\'ultima colonna: quanta parte')
    print('del guadagno disponibile resta in mano.')


if __name__ == '__main__':
    main()
