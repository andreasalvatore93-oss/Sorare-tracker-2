# -*- coding: utf-8 -*-
"""FILONE INTRALEGA -- passo 2: il cancello economico (zero query).

Domanda secca: la forza del reparto AVVERSARIO, misurata in voti Sorare e
normalizzata DENTRO la lega, ha una relazione col voto del giocatore? E quella
relazione e' piu' forte di quella che si ottiene normalizzando sul MONDO,
com'e' fatta oggi la produzione (GLOBAL_MEAN_CONCEDED, opponent_strength.py:319)?

Se la relazione e' piatta, il filone si chiude qui senza spendere altro.
Se c'e', NON basta: il passo 3 dovra' misurarla sul RESIDUO della produzione
(reale - atteso) con gli aggiustamenti avversario ACCESI -- misurare un pezzo
da solo, fuori dalla formula in cui deve vivere, e' l'errore che aveva fatto
accendere FWD_OFFENSE_SENSITIVITY nel 2026 per poi doverla spegnere.

DUE ACCOPPIAMENTI (richiesta dell'utente, stesso dataset quindi costo zero):
  attacco di A  vs  difesa di B   -> effetto sul voto degli ATTACCANTI di A
  difesa di A   vs  attacco di B  -> effetto sul voto dei DIFENSORI di A

CONTROLLI OBBLIGATORI:
- solo titolari (>=60 min): un entrato all'85' non misura niente;
- si toglie l'effetto della PROPRIA squadra (correlazione parziale): senza,
  si attribuisce all'avversario la forza del proprio reparto;
- errore standard a GRAPPOLO per partita: gli attaccanti della stessa squadra
  nella stessa partita non sono osservazioni indipendenti (trappola §8.15).

Uso: python analisi_manager/p34_intralega_gate.py
"""
import os
import json
import math
import argparse
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
MIN_PARTITE_SERIE = 5      # sotto, la media del reparto avversario e' rumore


def media(v):
    return sum(v) / len(v) if v else 0.0


def sd(v):
    if len(v) < 2:
        return 0.0
    m = media(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def correlazione(x, y):
    if len(x) < 3:
        return 0.0
    mx, my, sx, sy = media(x), media(y), sd(x), sd(y)
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / ((len(x) - 1) * sx * sy)


def residuo_su(y, x):
    """y depurato della sua parte spiegata linearmente da x (per la
    correlazione parziale)."""
    mx, my, sx = media(x), media(y), sd(x)
    if sx == 0:
        return list(y)
    b = correlazione(x, y) * sd(y) / sx
    return [(b_ - my) - b * (a - mx) for a, b_ in zip(x, y)]


def err_std_grappolo(x, y, gruppi):
    """Errore standard della correlazione con osservazioni raggruppate per
    partita: si ricampionano i GRUPPI, non le righe (200 giri)."""
    import random
    rng = random.Random(20260813)
    per_gruppo = defaultdict(list)
    for i, g in enumerate(gruppi):
        per_gruppo[g].append(i)
    chiavi = list(per_gruppo)
    if len(chiavi) < 20:
        return None
    stime = []
    for _ in range(200):
        idx = []
        for _ in range(len(chiavi)):
            idx.extend(per_gruppo[chiavi[rng.randrange(len(chiavi))]])
        stime.append(correlazione([x[i] for i in idx], [y[i] for i in idx]))
    return sd(stime)


def z_per_gruppo(righe, campo, chiave):
    """z del campo calcolato dentro il gruppo indicato (lega -> intralega,
    oppure costante -> mondiale)."""
    valori = defaultdict(list)
    for r in righe:
        valori[chiave(r)].append(r[campo])
    stat = {k: (media(v), sd(v)) for k, v in valori.items()}
    out = []
    for r in righe:
        m, s = stat[chiave(r)]
        out.append(0.0 if s == 0 else (r[campo] - m) / s)
    return out


def prova(righe_tutte, ruolo, campo_avv, campo_mio, n, etichetta):
    righe = [r for r in righe_tutte
             if r['ruolo'] == ruolo
             and r['minuti'] is not None and r['minuti'] >= 60
             and r.get(f'{campo_avv}_{n}') is not None
             and r.get(f'{campo_avv}_{n}_n', 0) >= MIN_PARTITE_SERIE
             and r.get(f'{campo_mio}_{n}') is not None]
    if len(righe) < 200:
        print(f"  {etichetta} (ultime {n}): campione troppo piccolo ({len(righe)})")
        return
    for r in righe:
        r['_avv'] = r[f'{campo_avv}_{n}']
        r['_mio'] = r[f'{campo_mio}_{n}']
    voti = [r['voto'] for r in righe]
    gruppi = [(r['data'], r['squadra'], r['avversario']) for r in righe]

    z_lega = z_per_gruppo(righe, '_avv', lambda r: r['lega'])
    z_mondo = z_per_gruppo(righe, '_avv', lambda r: '_tutti')
    z_mio_lega = z_per_gruppo(righe, '_mio', lambda r: r['lega'])

    c_lega = correlazione(z_lega, voti)
    c_mondo = correlazione(z_mondo, voti)
    # parziale: tolgo dal voto e dall'avversario la parte spiegata dal MIO
    # reparto, poi correlo i due residui
    v_res = residuo_su(voti, z_mio_lega)
    a_res = residuo_su(z_lega, z_mio_lega)
    c_parz = correlazione(a_res, v_res)
    es = err_std_grappolo(z_lega, voti, gruppi)

    print(f"  {etichetta} (ultime {n}): n={len(righe)}  "
          f"partite distinte={len(set(gruppi))}")
    print(f"      normalizzato INTRALEGA : {c_lega:+.4f}"
          + (f"   (errore standard a grappolo {es:.4f})" if es else ""))
    print(f"      normalizzato MONDIALE  : {c_mondo:+.4f}   "
          f"(come fa oggi la produzione)")
    print(f"      intralega, tolta la forza del PROPRIO reparto: {c_parz:+.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dati', default=os.path.join(_HERE, 'dati', 'intralega_righe.json'))
    args = ap.parse_args()
    with open(args.dati, encoding='utf-8') as fh:
        righe = json.load(fh)['righe']
    print(f"righe totali nel dataset: {len(righe)}\n")

    print("ACCOPPIAMENTO 1 -- attaccanti di A contro la DIFESA di B")
    print("  (atteso: difesa avversaria forte -> l'attaccante rende meno, "
          "quindi segno NEGATIVO)")
    for n in (5, 10):
        prova(righe, 'fwd', 'dif_avv', 'att_mia', n, 'FWD vs difesa avversaria')

    print("\nACCOPPIAMENTO 2 -- difensori di A contro l'ATTACCO di B")
    print("  (atteso: attacco avversario forte -> il difensore rende meno, "
          "quindi segno NEGATIVO)")
    for n in (5, 10):
        prova(righe, 'def', 'att_avv', 'dif_mia', n, 'DEF vs attacco avversario')


if __name__ == '__main__':
    main()
