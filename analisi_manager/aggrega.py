# -*- coding: utf-8 -*-
"""aggrega — unisce tutte le GW analizzate (dati/righe_<gw>.json) e cerca i
pattern STABILI: pool complessivo, per ruolo, e soprattutto PERSISTENZA per
manager (stesso segno del residuo su GW indipendenti = sharp vero, asse F).

Scrive analisi_manager/AGGREGATO.md. Uso: python analisi_manager/aggrega.py
"""
import glob
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATI = os.path.join(ROOT, 'analisi_manager', 'dati')


def media(x):
    return sum(x) / len(x) if x else None


def corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = media(x), media(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def blocco(rr):
    err = [r['reale'] - r['atteso'] for r in rr]
    a = [r['atteso'] for r in rr]
    re_ = [r['reale'] for r in rr]
    return {'n': len(rr), 'bias': media(err),
            'mae': media([abs(e) for e in err]), 'corr': corr(a, re_)}


def main():
    files = sorted(glob.glob(os.path.join(DATI, 'righe_*.json')))
    if not files:
        print('nessun dati/righe_*.json'); return 1
    per_gw = {}
    for f in files:
        gw = os.path.basename(f)[len('righe_'):-len('.json')]
        rows = json.load(open(f, encoding='utf-8'))
        for r in rows:
            r['_gw'] = gw
        per_gw[gw] = rows
    tutte = [r for rows in per_gw.values() for r in rows]

    out = ['# Aggregato cross-GW — filone smart-money', '',
           f"GW incluse: {len(per_gw)} ({', '.join(sorted(per_gw))}).",
           f"Osservazioni totali: {len(tutte)}."]

    s = blocco(tutte)
    out.append(f"\n## Pool complessivo\n")
    out.append(f"- Residuo medio (bias) = **{s['bias']:+.2f}**  (n {s['n']}, "
               f"MAE {s['mae']:.1f}, corr {s['corr']:+.3f}).")

    # per ruolo pooled
    out.append(f"\n## Per ruolo (pool)\n")
    out.append("| ruolo | n | bias | corr |\n|---|--:|--:|--:|")
    byr = {}
    for r in tutte:
        byr.setdefault(r['ruolo'], []).append(r)
    for ru, rr in sorted(byr.items(), key=lambda kv: -len(kv[1])):
        b = blocco(rr)
        out.append(f"| {ru} | {b['n']} | {b['bias']:+.1f} | "
                   f"{b['corr'] if b['corr'] is None else round(b['corr'],2)} |")

    # PERSISTENZA per manager: bias per (manager, gw)
    out.append(f"\n## Persistenza per manager (asse F — il test smart-money)\n")
    out.append("Bias per GW; 'segno stabile' = stesso verso su tutte le GW con "
               "n>=10. Un manager con bias positivo persistente è uno sharp vero.\n")
    gws = sorted(per_gw)
    out.append("| manager | " + " | ".join(gws) + " | pool_n | pool_bias | segno |")
    out.append("|---|" + "--:|" * (len(gws) + 3))
    man_gw = {}
    for r in tutte:
        man_gw.setdefault(r['manager'], {}).setdefault(r['_gw'], []).append(r)
    for man in sorted(man_gw, key=lambda m: -sum(len(v) for v in man_gw[m].values())):
        cells = []
        segni = []
        for gw in gws:
            rr = man_gw[man].get(gw, [])
            if len(rr) >= 10:
                b = media([r['reale'] - r['atteso'] for r in rr])
                cells.append(f"{b:+.1f}({len(rr)})")
                segni.append(1 if b > 0 else -1)
            elif rr:
                cells.append(f"·({len(rr)})")
            else:
                cells.append('-')
        allrows = [r for gw in gws for r in man_gw[man].get(gw, [])]
        pb = media([r['reale'] - r['atteso'] for r in allrows])
        stabile = ('+' if all(x > 0 for x in segni) else
                   '-' if all(x < 0 for x in segni) else 'misto') if len(segni) >= 2 else '?'
        out.append(f"| {man} | " + " | ".join(cells) +
                   f" | {len(allrows)} | {pb:+.1f} | {stabile} |")

    # consenso pooled: giocatori scelti da piu' manager nella stessa GW
    out.append(f"\n## Consenso (pool, per numero di manager nella stessa GW)\n")
    out.append("| n manager | n giocatori | bias |\n|---|--:|--:|")
    cons = {}
    key = {}
    for r in tutte:
        key.setdefault((r['_gw'], r['slug']), set()).add(r['manager'])
    # per ogni (gw,slug) prendi una riga rappresentativa + il conteggio manager
    rep = {}
    for r in tutte:
        rep.setdefault((r['_gw'], r['slug']), r)
    byn = {}
    for k, rrep in rep.items():
        n_man = len(key[k])
        byn.setdefault(n_man, []).append(rrep)
    for n_man in sorted(byn):
        b = blocco(byn[n_man])
        out.append(f"| {n_man} | {b['n']} | {b['bias']:+.1f} |")

    open(os.path.join(ROOT, 'analisi_manager', 'AGGREGATO.md'), 'w',
         encoding='utf-8').write('\n'.join(out) + '\n')
    print('\n'.join(out))
    print('\n[salvato] analisi_manager/AGGREGATO.md')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
