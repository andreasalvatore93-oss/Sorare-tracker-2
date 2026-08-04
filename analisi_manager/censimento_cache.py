# -*- coding: utf-8 -*-
"""censimento_cache — quanti giocatori (gamelog) ci sono in cache PER LEGA.

Serve a stanare le leghe INERTI: pipeline presente (formazione_<lega>/ +
LEAGUE_DIR) ma cache quasi vuota -> "coperta" non vuol dire "popolata" (regola
CLAUDE.md). Conta i *_gamelog.json sotto ogni formazione_*/ con os.walk (NON
glob('**'), che non scende nelle cartelle nascoste .game_log_cache).

Uso: python analisi_manager/censimento_cache.py [--soglia 100]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def conta():
    from collections import Counter
    c = Counter()
    dirs = [d for d in os.listdir(ROOT) if d.startswith('formazione_')]
    for d in dirs:
        lega = d[len('formazione_'):]
        c[lega] = 0  # anche le leghe a 0 devono comparire
        for r, _, fs in os.walk(os.path.join(ROOT, d)):
            for f in fs:
                if f.endswith('_gamelog.json'):
                    c[lega] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--soglia', type=int, default=100,
                    help='sotto questa soglia la lega e\' segnalata INERTE')
    args = ap.parse_args()
    c = conta()
    tot = sum(c.values())
    print(f"TOTALE gamelog: {tot} su {len(c)} leghe con cartella")
    print(f"\nPOPOLATE (>= {args.soglia}):")
    for lega, n in c.most_common():
        if n >= args.soglia:
            print(f"  {n:5}  {lega}")
    print(f"\nINERTI (< {args.soglia}) -- pipeline presente ma cache scarsa/vuota:")
    for lega, n in sorted(c.items(), key=lambda x: x[1]):
        if n < args.soglia:
            print(f"  {n:5}  {lega}")


if __name__ == '__main__':
    main()
