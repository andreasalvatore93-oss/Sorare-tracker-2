"""correlazione_avversari — la correlazione fra AVVERSARI nella stessa partita,
mai misurata. taratura_giocatore.py misura solo quella fra COMPAGNI di squadra
(rho_compagni) e con quella sola arriva a un errore di formazione da 5 di 45.7
punti, contro i 49.4 osservati sulle formazioni vere del backtest: 3.7 punti di
divario. Se una squadra prende 3 gol, i suoi giocatori sbagliano insieme (gia'
misurato) MA anche i giocatori della squadra avversaria sbagliano insieme in
modo correlato (mai misurato) - segno atteso positivo, non negativo: una
partita con piu' gol del previsto alza il punteggio di attacco/centrocampo su
ENTRAMBE le squadre.

Riusa dati_globali/taratura_coppie.json gia' salvato da taratura_giocatore.py
(evita i ~30 minuti di ricalcolo delle previsioni walk-forward).

Uso: python correlazione_avversari.py
     python correlazione_avversari.py --json out.json
"""
import argparse
import collections
import json
import math
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def retta(X, Y):
    n = len(X)
    mx = statistics.mean(X)
    my = statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(X, Y)]
    return a, b, statistics.pstdev(res)


def correlazione(coppie_res, etichetta):
    if len(coppie_res) <= 50:
        print(f'\n  {etichetta}: troppo pochi per misurare ({len(coppie_res)} coppie)')
        return 0.0
    A = [x for x, _ in coppie_res]
    B = [y for _, y in coppie_res]
    ma, mb = statistics.mean(A), statistics.mean(B)
    cov = sum((x - ma) * (y - mb) for x, y in zip(A, B)) / len(A)
    sa, sb = statistics.pstdev(A), statistics.pstdev(B)
    rho = cov / (sa * sb) if sa and sb else 0.0
    print(f'\n=== {etichetta} ({len(coppie_res)} coppie)')
    print(f'  rho = {rho:+.3f}')
    return rho


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()

    with open('dati_globali/taratura_coppie.json', encoding='utf-8') as fh:
        coppie = json.load(fh)
    print(f'{len(coppie)} coppie previsto/reale caricate da cache')

    X = [c['previsto'] for c in coppie]
    Y = [c['reale'] for c in coppie]
    a, b, sd = retta(X, Y)
    print(f'errore del singolo giocatore: {sd:.2f} punti')

    # residui raggruppati per (partita, squadra): stesso identico calcolo di
    # taratura_giocatore.py, serve per pescare coppie da squadre DIVERSE
    per_partita = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in coppie:
        if c.get('squadra') and c.get('partita'):
            res = c['reale'] - (a + b * c['previsto'])
            per_partita[c['partita']][c['squadra']].append(res)

    coppie_compagni = []
    coppie_avversari = []
    for squadre in per_partita.values():
        nomi = list(squadre.keys())
        if len(nomi) < 1:
            continue
        # compagni: stessa squadra
        for v in squadre.values():
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    coppie_compagni.append((v[i], v[j]))
        # avversari: squadre diverse nella stessa partita (solo 2 squadre attese)
        for i in range(len(nomi)):
            for j in range(i + 1, len(nomi)):
                for x in squadre[nomi[i]]:
                    for y in squadre[nomi[j]]:
                        coppie_avversari.append((x, y))

    rho_compagni = correlazione(coppie_compagni, 'CORRELAZIONE FRA COMPAGNI (verifica)')
    rho_avversari = correlazione(coppie_avversari, 'CORRELAZIONE FRA AVVERSARI')

    # errore di una formazione da 5: caso peggiore/plausibile in cui i 5 sono
    # tutti sconosciuti fra loro tranne coppie casuali di compagni/avversari.
    # Qui misuriamo solo l'effetto MEDIO su una formazione di 5 giocatori presi
    # a caso nello storico (n_compagni e n_avversari attesi in una formazione
    # reale non sono 1: dipendono da quante coppie condividono partita, che e'
    # raro con 5 carte su migliaia di giocatori/partite disponibili).
    n = 5
    indip = sd * math.sqrt(n)
    solo_compagni = sd * math.sqrt(n + n * (n - 1) * max(rho_compagni, 0.0))
    con_avversari = sd * math.sqrt(n + n * (n - 1) * max(rho_compagni, 0.0)
                                    + n * (n - 1) * rho_avversari)
    print(f'\n=== ERRORE DI UNA FORMAZIONE DA 5 (stesso peso a ogni coppia)')
    print(f'  indipendenti:                      {indip:.1f}')
    print(f'  solo correlazione compagni:         {solo_compagni:.1f}  (era 45.7)')
    print(f'  compagni + avversari:               {con_avversari:.1f}  (osservato: 49.4)')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'rho_compagni': rho_compagni, 'rho_avversari': rho_avversari,
                       'errore_formazione_compagni': solo_compagni,
                       'errore_formazione_compagni_avversari': con_avversari},
                       fh, indent=1)
        print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
