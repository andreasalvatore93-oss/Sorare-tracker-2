"""
Analyze Captain Bias Outfield (04/08, richiesta esplicita utente)

Seguito diretto di analyze_gk_captain_value.py: l'utente e' gia' convinto di
escludere il portiere dalla scelta capitano (non solo penalizzarlo col
margine GK_CAPTAIN_MARGIN=6.7). La domanda ora riguarda i 4 slot rimanenti:
oggi pick_captain() sceglie fra DEF/MID/FWD solo per atteso grezzo piu' alto,
senza nessuna correzione di ruolo (build_formazione_finale.py:1493-1496).

Se, come per il portiere, uno dei tre ruoli sovra/sottostima sistematicamente
il reale rispetto agli altri due nella fascia che conta per la scelta
capitano (atteso >= 55), capitanare "il piu' alto in assoluto" penalizza
sempre lo stesso ruolo -- serve un margine o una correzione, come gia' fatto
per il portiere.

NESSUNA nuova query: riusa integralmente la raccolta dati di
analyze_gk_captain_value.py (stessi CONFIGS, stessi parametri UFFICIALI di
produzione, stesse cache di calibrazione gia' su disco) e aggiunge solo la
rottura per ruolo della sezione "zona capitano" (che li' confronta solo
GK vs OUTFIELD lumped insieme).

Uso: python formazione_mls/diagnostics/analyze_captain_bias_outfield.py
"""
import os
import sys
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import formazione_mls.diagnostics.analyze_gk_captain_value as base

ZONA_CAPITANO_MIN_ATTESO = 55


def main():
    print("Raccolta coppie (predetto, reale) per ruolo/lega con i parametri UFFICIALI di produzione...")
    print("(stessa raccolta di analyze_gk_captain_value.py, nessuna nuova query)\n")

    by_role_detail = defaultdict(list)  # 'GK'/'DEF'/'MID'/'FWD' -> [(predetto, reale), ...]
    for league, ruolo, module_name, cache_dir, params in base.CONFIGS:
        pairs = base.collect_pairs(league, ruolo, module_name, cache_dir, params)
        by_role_detail[ruolo].extend(pairs)

    print(f"\n=== ZONA CAPITANO (atteso >= {ZONA_CAPITANO_MIN_ATTESO}), DEF vs MID vs FWD separati ===")
    print("(la stessa fascia usata per misurare il gap GK-vs-movimento che ha")
    print(" prodotto GK_CAPTAIN_MARGIN=6.7 -- qui si guarda SOLO dentro il movimento)\n")

    zona = {}
    for ruolo in ('DEF', 'MID', 'FWD'):
        pairs = [(p, r) for p, r in by_role_detail[ruolo] if p >= ZONA_CAPITANO_MIN_ATTESO]
        if not pairs:
            print(f"  {ruolo}: nessun dato in questa fascia")
            continue
        mp = statistics.mean(p for p, r in pairs)
        mr = statistics.mean(r for p, r in pairs)
        bias = mr - mp
        mae = statistics.mean(abs(r - p) for p, r in pairs)
        stats = base.downside_stats(pairs)
        freq, avg_gap, n = stats if stats else (None, None, len(pairs))
        zona[ruolo] = {'n': len(pairs), 'atteso_medio': mp, 'reale_medio': mr, 'bias': bias,
                       'mae': mae, 'freq_crollo': freq, 'gap_medio_crollo': avg_gap}
        crollo_str = f"freq crollo={freq:.1%} (gap medio {avg_gap:.1f})" if freq is not None else "freq crollo=n/d"
        print(f"  {ruolo:<5} n={len(pairs):>5}  atteso medio={mp:6.1f}  reale medio={mr:6.1f}  "
              f"bias={bias:+6.2f}  MAE={mae:5.2f}  {crollo_str}")

    print("\n=== GAP A COPPIE fra i tre ruoli (bias_A - bias_B) ===")
    print("(per confronto: il gap GK-vs-movimento che ha prodotto GK_CAPTAIN_MARGIN era +6.69pt)\n")
    ruoli_presenti = [r for r in ('DEF', 'MID', 'FWD') if r in zona]
    for i, a in enumerate(ruoli_presenti):
        for b in ruoli_presenti[i + 1:]:
            gap = zona[a]['bias'] - zona[b]['bias']
            print(f"  {a} vs {b}: {gap:+.2f} pt")

    print("\n=== Per riferimento: bias overall (tutte le fasce), stesso output di analyze_gk_captain_value.py ===")
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        pairs = by_role_detail[ruolo]
        if not pairs:
            continue
        bias = statistics.mean(r - p for p, r in pairs)
        mae = statistics.mean(abs(r - p) for p, r in pairs)
        print(f"  {ruolo:<5} n={len(pairs):>6}  bias={bias:+.2f} pt  MAE={mae:.2f} pt")


if __name__ == '__main__':
    main()
