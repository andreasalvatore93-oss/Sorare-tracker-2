"""
Analyze Captain Bias By League (04/08, seguito capitano DEF/MID/FWD)

Il bias di ruolo (zona capitano, atteso>=55: DEF -8.37/MID -6.00/FWD -7.37,
gap DEF-vs-MID -2.37pt) e' gia' stato bocciato in policy su 513 formazioni
(lift ~0). Prima di riprovarlo su un campione piu' grande, domanda aperta nel
RIASSUNTO_2026-08-04.md: il gap e' stabile su tutte le leghe o trainato da
poche? Se e' incoerente lega per lega, nessun campione piu' grande lo
salvera' (media di segnali che si cancellano a vicenda).

NESSUNA nuova query: riusa integralmente CONFIGS/collect_pairs di
analyze_gk_captain_value.py (stesse cache, stessi parametri ufficiali),
raggruppando per lega invece che aggregando su tutte le 53.

Uso: python formazione_mls/diagnostics/analyze_captain_bias_by_league.py
"""
import os
import sys
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import formazione_mls.diagnostics.analyze_gk_captain_value as base

ZONA_CAPITANO_MIN_ATTESO = 55
MIN_N_PER_LEGA = 40  # sotto questa soglia il bias per lega e' troppo rumoroso


def main():
    print("Raccolta coppie (predetto, reale) per lega/ruolo, zona capitano (atteso>=55)...\n")

    # (league, ruolo) -> [(predetto, reale), ...]
    by_league_role = defaultdict(list)
    for league, ruolo, module_name, cache_dir, params in base.CONFIGS:
        if ruolo == 'GK':
            continue
        pairs = base.collect_pairs(league, ruolo, module_name, cache_dir, params)
        zona = [(p, r) for p, r in pairs if p >= ZONA_CAPITANO_MIN_ATTESO]
        by_league_role[(league, ruolo)].extend(zona)

    leghe = sorted(set(league for league, _ruolo in by_league_role))

    print(f"\n=== Bias per ruolo, SPACCATO PER LEGA (zona capitano, atteso>={ZONA_CAPITANO_MIN_ATTESO}) ===")
    print(f"(leghe con n<{MIN_N_PER_LEGA} in un ruolo saltate per quel ruolo, troppo rumorose)\n")

    righe = []  # (league, def_bias, mid_bias, fwd_bias, gap_def_mid, n_min)
    for league in leghe:
        bias = {}
        ns = {}
        for ruolo in ('DEF', 'MID', 'FWD'):
            pairs = by_league_role.get((league, ruolo), [])
            ns[ruolo] = len(pairs)
            if len(pairs) < MIN_N_PER_LEGA:
                bias[ruolo] = None
                continue
            bias[ruolo] = statistics.mean(r - p for p, r in pairs)
        print(f"  {league:<12} n(DEF/MID/FWD)={ns['DEF']:>4}/{ns['MID']:>4}/{ns['FWD']:>4}  "
              f"bias DEF={_fmt(bias['DEF'])}  MID={_fmt(bias['MID'])}  FWD={_fmt(bias['FWD'])}")
        if bias['DEF'] is not None and bias['MID'] is not None:
            righe.append((league, bias['DEF'], bias['MID'], bias['FWD'],
                          bias['DEF'] - bias['MID'], min(ns['DEF'], ns['MID'])))

    print(f"\n=== Gap DEF-vs-MID per lega (per confronto: gap aggregato su 53 leghe = -2.37pt) ===\n")
    stesso_segno = 0
    for league, def_b, mid_b, fwd_b, gap, n in righe:
        segno = "stesso segno (DEF peggio)" if gap < 0 else "SEGNO OPPOSTO (DEF meglio)"
        if gap < 0:
            stesso_segno += 1
        print(f"  {league:<12} gap DEF-MID={gap:+6.2f}  n_min={n:>4}  {segno}")

    print(f"\n{stesso_segno}/{len(righe)} leghe con lo stesso segno (DEF peggio di MID) del bias aggregato.")
    if righe:
        gaps = [g for _l, _d, _m, _f, g, _n in righe]
        print(f"Gap medio (non pesato per n): {statistics.mean(gaps):+.2f}pt  "
              f"dev.std tra leghe: {statistics.pstdev(gaps):.2f}pt")
        # quota di leghe grandi (n>=200) e loro coerenza
        grandi = [(l, g, n) for l, _d, _m, _f, g, n in righe if n >= 200]
        if grandi:
            stesso_grandi = sum(1 for _l, g, _n in grandi if g < 0)
            print(f"Tra le {len(grandi)} leghe con n_min>=200: {stesso_grandi}/{len(grandi)} stesso segno.")


def _fmt(v):
    return f"{v:+6.2f}" if v is not None else "  n/d "


if __name__ == '__main__':
    main()
