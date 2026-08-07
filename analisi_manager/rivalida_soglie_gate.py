"""PASSO 1 -- cancello metodologico (brief BRIEF_SONNET_SOGLIE_ARENA_2026-08-07).

Domanda: pescare 9 avversari INDIPENDENTI da una distribuzione di punteggi
da' lo stesso pareggio che pescare un campo vero (i 9 punteggi di una singola
arena, presi insieme)? Se si', si puo' costruire il pool grande dai manager
(dove il campo completo quasi mai si conosce) senza distorcere le soglie.

Usa SOLO dati_globali/arene_storico.json (le uniche arene di cui conosciamo
il campo VERO per intero: 153/160 hanno tutti e 10 i punteggi). Confronto
appaiato sullo STESSO sottoinsieme di dati, cosi' l'unica variabile che
cambia e' il metodo di pesca, non il campione.
"""
import json
import random
import statistics
import sys

sys.path.insert(0, '.')
from consiglio_arena import incasso_medio, REGOLE, premi_osservati

ARCHIVIO = 'dati_globali/arene_storico.json'


def carica_campi_veri(tipo_target):
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    campi = []
    for r in d['arene']:
        if r['tipo'] != tipo_target:
            continue
        punteggi = list(r.get('punteggi') or [])
        mio = r.get('mio_score')
        if mio is not None and mio in punteggi:
            punteggi.remove(mio)
        if len(punteggi) < 8:
            continue
        campi.append(punteggi)
    return campi


def pareggio_grouped(campi, costo, premi, tipo, sigma=0, seme=7):
    """Metodo ATTUALE: ogni prova pesca UN'ARENA intera (i 9 insieme)."""
    basso, alto = 150.0, 450.0
    for _ in range(24):
        meta = (basso + alto) / 2
        if incasso_medio(meta, campi, premi, sigma=sigma, tipo=tipo, seme=seme) < costo:
            basso = meta
        else:
            alto = meta
    return (basso + alto) / 2


def pareggio_indipendente(pool, costo, premi, tipo, sigma=0, prove=20000, seme=7):
    """Metodo NUOVO: ogni prova pesca 9 punteggi INDIPENDENTI dal pool piatto."""
    global _PREMI_OSS
    from consiglio_arena import _PREMI_OSS as _ignore  # noqa
    import consiglio_arena as ca
    if ca._PREMI_OSS is None:
        ca._PREMI_OSS = premi_osservati()

    def incasso(atteso, rnd):
        totale = 0
        for _ in range(prove):
            mio = rnd.gauss(atteso, sigma) if sigma else atteso
            nove = [pool[rnd.randrange(len(pool))] for _ in range(9)]
            posizione = 1 + sum(1 for x in nove if x > mio)
            if posizione > 3:
                continue
            visti = ca._PREMI_OSS.get((tipo, posizione))
            if visti:
                totale += visti[rnd.randrange(len(visti))]
            else:
                totale += premi[posizione - 1]
        return totale / prove

    basso, alto = 150.0, 450.0
    for _ in range(24):
        meta = (basso + alto) / 2
        rnd = random.Random(seme)
        if incasso(meta, rnd) < costo:
            basso = meta
        else:
            alto = meta
    return (basso + alto) / 2


def rumore_mc(campi, costo, premi, tipo, metodo, sigma=0, n_semi=5):
    """Ripete il calcolo del pareggio con semi diversi per stimare il rumore
    Monte Carlo del metodo (quanto oscilla il numero a parita' di dati)."""
    valori = []
    for seme in range(n_semi):
        random.seed(seme + 100)
        if metodo == 'grouped':
            v = pareggio_grouped(campi, costo, premi, tipo, sigma=sigma, seme=seme + 100)
        else:
            v = pareggio_indipendente(campi, costo, premi, tipo, sigma=sigma, seme=seme + 100)
        valori.append(v)
    return valori


if __name__ == '__main__':
    tipo = 'cap 260'
    regole = REGOLE[tipo]
    campi = carica_campi_veri(tipo)
    pool = [x for arena in campi for x in arena]
    print(f'{tipo}: {len(campi)} arene col campo vero (>=8/9 punteggi noti), '
          f'{len(pool)} punteggi nel pool piatto')

    g = pareggio_grouped(campi, regole['costo'], regole['premi'], tipo)
    ind = pareggio_indipendente(pool, regole['costo'], regole['premi'], tipo)
    print(f'metodo ATTUALE (campo vero, grouped):     pareggio = {g:.1f}')
    print(f'metodo NUOVO   (9 pescati indipendenti):  pareggio = {ind:.1f}')
    print(f'scarto = {ind - g:+.1f}')

    rg = rumore_mc(campi, regole['costo'], regole['premi'], tipo, 'grouped')
    ri = rumore_mc(pool, regole['costo'], regole['premi'], tipo, 'independent')
    print(f'rumore MC grouped (5 semi): {rg} -> sd={statistics.pstdev(rg):.2f}')
    print(f'rumore MC indip.  (5 semi): {ri} -> sd={statistics.pstdev(ri):.2f}')
