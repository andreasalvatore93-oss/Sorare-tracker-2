# -*- coding: utf-8 -*-
"""FILONE INTRALEGA -- passo 2b: DUE TERMOMETRI PER LA STESSA COSA (zero query).

La produzione misura la forza dell'avversario in GOL (gol subiti dall'avversario
nelle ultime 10, `opponent_strength.opponent_lambda_multiplier`). L'idea
dell'utente la misura in VOTI SORARE dei difensori/attaccanti veri di quella
squadra. Sono due termometri per la stessa febbre, e non erano mai stati
confrontati.

Tre domande, in ordine:
  1. quale dei due correla di piu' col voto realizzato?
  2. il termometro nuovo aggiunge qualcosa SOPRA quello vecchio? (correlazione
     parziale: il pezzo di voto che i gol non spiegano gia')
  3. e viceversa, per non farsi ingannare dal caso in cui siano intercambiabili.

La serie dei gol NON e' ricostruita a mano: si chiama
`opponent_strength._build_series_for_league(None)`, cioe' ESATTAMENTE la
funzione che gira in produzione, cosi' il confronto e' col termometro vero e
non con una mia riscrittura che gli somiglia.

Uso (dalla radice del repo): python analisi_manager/p35_intralega_termometri.py
"""
import os
import sys
import json
import math
import argparse
import datetime
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)          # _build_series_for_league usa glob relativi

import opponent_strength as ops
from p34_intralega_gate import (media, sd, correlazione, residuo_su,
                                err_std_grappolo, MIN_PARTITE_SERIE)

N_GARE = 10             # la stessa finestra della produzione (N_GAMES_DEFAULT)


def serie_gol():
    """(conceded, scored) per squadra, dalla funzione di produzione."""
    conceded, scored = ops._build_series_for_league(None)
    print(f"serie gol dalla produzione: {len(conceded)} squadre con 'subiti', "
          f"{len(scored)} con 'fatti'")
    return conceded, scored


def media_asof_gol(serie, squadra, data_iso, n):
    limite = datetime.datetime.fromisoformat(data_iso + 'T00:00:00')
    passate = [v for dt, v in serie.get(squadra, []) if dt < limite]
    if len(passate) < MIN_PARTITE_SERIE:
        return None
    ultime = passate[-n:]
    return sum(ultime) / len(ultime)


def z(valori):
    m, s = media(valori), sd(valori)
    return [0.0 if s == 0 else (v - m) / s for v in valori]


def confronta(righe, ruolo, campo_voti, serie, etichetta_gol, atteso_segno):
    """campo_voti: la media-voto del reparto avversario gia' nel dataset.
    serie: la serie di gol dell'avversario (conceded o scored)."""
    sel = []
    for r in righe:
        if r['ruolo'] != ruolo:
            continue
        if r['minuti'] is None or r['minuti'] < 60:
            continue
        v_avv = r.get(f'{campo_voti}_{N_GARE}')
        if v_avv is None or r.get(f'{campo_voti}_{N_GARE}_n', 0) < MIN_PARTITE_SERIE:
            continue
        g_avv = media_asof_gol(serie, r['avversario'], r['data'], N_GARE)
        if g_avv is None:
            continue
        sel.append((r, v_avv, g_avv))
    if len(sel) < 200:
        print(f"  campione insufficiente: {len(sel)}")
        return

    voti = [r['voto'] for r, _v, _g in sel]
    gruppi = [(r['data'], r['squadra'], r['avversario']) for r, _v, _g in sel]
    zv = z([v for _r, v, _g in sel])      # termometro NUOVO (voti Sorare)
    zg = z([g for _r, _v, g in sel])      # termometro VECCHIO (gol)

    c_voti = correlazione(zv, voti)
    c_gol = correlazione(zg, voti)
    # il nuovo sopra il vecchio, e viceversa
    parz_nuovo = correlazione(residuo_su(zv, zg), residuo_su(voti, zg))
    parz_vecchio = correlazione(residuo_su(zg, zv), residuo_su(voti, zv))
    es_v = err_std_grappolo(zv, voti, gruppi)
    es_g = err_std_grappolo(zg, voti, gruppi)
    fra_loro = correlazione(zv, zg)

    print(f"  n={len(sel)}  partite distinte={len(set(gruppi))}  "
          f"(segno atteso: {atteso_segno})")
    print(f"      VOTI Sorare del reparto avversario : {c_voti:+.4f}"
          + (f"  (es {es_v:.4f})" if es_v else ""))
    print(f"      GOL ({etichetta_gol}), come la produzione: {c_gol:+.4f}"
          + (f"  (es {es_g:.4f})" if es_g else ""))
    print(f"      quanto si somigliano i due termometri: {fra_loro:+.4f}")
    print(f"      VOTI sopra i GOL (parziale)  : {parz_nuovo:+.4f}   <-- "
          f"e' questo che decide se aggiungere qualcosa")
    print(f"      GOL sopra i VOTI (parziale)  : {parz_vecchio:+.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dati', default=os.path.join(_HERE, 'dati', 'intralega_righe.json'))
    args = ap.parse_args()
    with open(args.dati, encoding='utf-8') as fh:
        righe = json.load(fh)['righe']
    conceded, scored = serie_gol()

    print("\nATTACCANTI di A -- quanto e' permeabile la difesa di B")
    print("  gol SUBITI da B (il termometro della produzione per il FWD) "
          "contro i VOTI dei difensori di B")
    confronta(righe, 'fwd', 'dif_avv', conceded, 'subiti da B', 'gol + / voti -')

    print("\nDIFENSORI di A -- quanto e' pericoloso l'attacco di B")
    print("  gol FATTI da B contro i VOTI degli attaccanti di B")
    confronta(righe, 'def', 'att_avv', scored, 'fatti da B', 'entrambi -')


if __name__ == '__main__':
    main()
