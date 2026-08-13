# -*- coding: utf-8 -*-
"""LE ARENE "MARGINALI" CONVIENE GIOCARLE? (13/08/2026)

DUE DOMANDE DELL'UTENTE, che si rispondono con la stessa tabella:
 1) il generatore etichetta come MARGINALE ogni arena il cui guadagno atteso
    sta fra zero e il 10% del costo d'ingresso (_etichetta_arena in
    build_formazione_globale.py: "meglio All Stars da 7 o Under 23"). Lui le
    genera tutte e poi sceglie a mano, e quell'etichetta lo spinge a
    saltarle. Ma vale davvero la pena saltarle?
 2) da un test vecchio era emerso che piu' e' alto l'atteso in essenze, piu'
    conviene entrare -- cioe' la prima arena della lista efficiente e' anche
    quella con piu' probabilita' di andare a premio. Da riverificare.

COME. Per ogni arena REALMENTE giocata nell'archivio si calcola il guadagno
ATTESO in essenze con la formula di produzione
    (atteso - PAREGGIO_ARENA[tipo]) * GUADAGNO_PER_PUNTO[tipo]
usando l'atteso del modello di PRODUZIONE (voto acceso, gruppo nativo
lega_ruolo) e il walk-forward stretto del backtest. Poi si raggruppa per
fascia e si guarda cosa e' successo DAVVERO: netto medio incassato e quante
volte si e' andati a premio.

Non e' una simulazione: le arene sono quelle giocate, i premi quelli veri.
L'unica cosa stimata e' l'atteso, che e' esattamente cio' che l'utente vede
nel report quando decide.

Uso: python analisi_manager/p61_fasce_marginali.py
     python analisi_manager/p61_fasce_marginali.py --manager crowss
"""
import os
import sys
import io
import random
import argparse
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p23_binario1_mga as B1  # noqa: E402


def guadagno_atteso(riga_per_carta, formazione):
    """Essenze attese sopra il pareggio, con la formula di produzione."""
    carte = formazione['carte']
    rows = [riga_per_carta.get(c.get('carta')) for c in carte]
    if any(r is None for r in rows):
        return None, None, None
    cap = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
    atteso = sum(r['_combinato'] for r in rows)
    if cap is not None:
        atteso += 0.2 * rows[cap]['_combinato']
    tipo = B1.TIPO_TO_BFG[formazione['tipo']]
    soglia = S21.bfg.PAREGGIO_ARENA.get(tipo)
    if soglia is None:
        return None, None, None
    costo = S21.bfg.COSTO_INGRESSO.get(tipo, 300)
    guad = (atteso - soglia) * S21.bfg.GUADAGNO_PER_PUNTO.get(tipo, 7.9)
    return guad, costo, tipo


def fascia(guad, costo):
    """Le stesse soglie che usa l'etichetta di produzione, piu' fini sopra."""
    q = guad / costo if costo else 0.0
    if q < -0.25:
        return '0. sotto pareggio (forte)'
    if q < 0:
        return '1. sotto pareggio (poco)'
    if q < 0.10:
        return '2. MARGINALE (0-10%)'
    if q < 0.25:
        return '3. schiera (10-25%)'
    if q < 0.50:
        return '4. schiera (25-50%)'
    if q < 1.00:
        return '5. schiera (50-100%)'
    return '6. schiera (oltre 100%)'


def boot_media(valori, n_boot=3000, seed=20260813):
    if not valori:
        return 0.0, 0.0
    rnd = random.Random(seed)
    n = len(valori)
    medie = []
    for _ in range(n_boot):
        medie.append(sum(valori[rnd.randrange(n)] for _i in range(n)) / n)
    medie.sort()
    return medie[int(0.025 * n_boot)], medie[int(0.975 * n_boot)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', action='append', default=[])
    args = ap.parse_args()

    fixtures = B1.elenca_fixture()
    if args.manager:
        fixtures = [f for f in fixtures if f[0] in set(args.manager)]
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    per_fascia = collections.defaultdict(list)   # fascia -> [(netto, podio)]
    per_tipo = collections.defaultdict(lambda: collections.defaultdict(list))
    saltate = 0
    for manager, fx, path in fixtures:
        pre = B1.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        S21.applica_gruppi_grade(pre['pool_rows'], modo='lega_ruolo')
        riga_per_carta = {r['carta']: r for r in pre['pool_rows']}
        for form in pre['pulite']:
            guad, costo, tipo = guadagno_atteso(riga_per_carta, form)
            if guad is None:
                saltate += 1
                continue
            netto = form['premio_netto']
            podio = 1 if (form.get('rank') or 99) <= 3 else 0
            f = fascia(guad, costo)
            per_fascia[f].append((netto, podio))
            per_tipo[tipo][f].append(netto)

    tot = sum(len(v) for v in per_fascia.values())
    print('=' * 96)
    print('ARENE REALMENTE GIOCATE: %d valutate (%d saltate per carte senza atteso)'
          % (tot, saltate))
    print('atteso = modello di PRODUZIONE (voto acceso); netto e premi = VERI')
    print('=' * 96)
    print('%-28s %7s %12s %14s %10s' %
          ('fascia di guadagno atteso', 'arene', 'netto medio', 'IC95 media', 'a premio'))
    for f in sorted(per_fascia):
        righe = per_fascia[f]
        netti = [x[0] for x in righe]
        media = sum(netti) / len(netti)
        lo, hi = boot_media(netti)
        podio = 100.0 * sum(x[1] for x in righe) / len(righe)
        print('%-28s %7d %12.1f %14s %9.1f%%'
              % (f, len(righe), media, '[%+.0f;%+.0f]' % (lo, hi), podio))

    print()
    print('LA DOMANDA 1 -- le MARGINALI conviene giocarle?')
    m = per_fascia.get('2. MARGINALE (0-10%)', [])
    if m:
        netti = [x[0] for x in m]
        media = sum(netti) / len(netti)
        lo, hi = boot_media(netti)
        print('  %d arene, netto medio %+.1f essenze, IC95 [%+.0f;%+.0f]'
              % (len(m), media, lo, hi))
        if lo > 0:
            print('  -> CONVIENE: il netto medio e\' positivo e l\'intervallo'
                  ' esclude lo zero.')
        elif hi < 0:
            print('  -> NON conviene: il netto medio e\' negativo, intervallo'
                  ' sotto lo zero.')
        else:
            print('  -> INDECIDIBILE su questo campione: l\'intervallo contiene'
                  ' lo zero.')

    print()
    print('LA DOMANDA 2 -- piu\' alto l\'atteso, piu\' si va a premio?')
    ordinate = [f for f in sorted(per_fascia) if not f.startswith('0.')]
    prec = None
    monotona = True
    for f in ordinate:
        righe = per_fascia[f]
        p = 100.0 * sum(x[1] for x in righe) / len(righe)
        if prec is not None and p < prec - 1.0:
            monotona = False
        prec = p
    print('  la percentuale a premio %s al crescere dell\'atteso'
          % ('SALE in modo monotono' if monotona else 'NON sale in modo monotono'))
    print('  (tolleranza 1 punto percentuale; le fasce sotto il pareggio sono escluse)')


if __name__ == '__main__':
    main()
