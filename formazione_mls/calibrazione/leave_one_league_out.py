#!/usr/bin/env python3
"""
leave_one_league_out.py

Test di GENERALIZZAZIONE dei parametri del modello (27/07).

Per ogni campionato L con dati sufficienti:
  1. calibra (aggregate) sul pool di TUTTI gli altri campionati (train = tutti tranne L);
  2. prende la combinazione vincente sul train;
  3. misura il MAE di QUELLA combinazione sui giocatori di L (validation, lega mai vista).

Se la combinazione vincente e' stabile fold-dopo-fold e il MAE di validation e' vicino
a quello di train, i parametri generalizzano (non stanno sovradattando il pool). Se invece
il vincitore cambia molto o il MAE di validation esplode, il segnale e' ancora debole.

Uso:  RUOLO=<gk|def|mid|fwd> python formazione_mls/calibrazione/leave_one_league_out.py
"""
from __future__ import annotations
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aggregate_grid_search import (  # noqa: E402
    load_players_for, aggregate, CAMPIONATI_NOTI, RUOLO, MIN_TEST_GAMES,
)

MIN_PLAYERS_FOLD = int(os.environ.get('MIN_PLAYERS_FOLD', '3'))  # leghe con meno giocatori non fanno da validation


def per_label_from(players):
    per_label = defaultdict(list)
    for p in players:
        for combo in p['combos']:
            per_label[combo['label']].append(combo)
    return per_label


def weighted_mae_for_label(players, label):
    entries = [c for p in players for c in p['combos'] if c['label'] == label]
    if not entries:
        return None, 0
    w = sum(e['n_test'] for e in entries)
    mae = sum(e['mae'] * e['n_test'] for e in entries) / w
    return mae, w


def main():
    # carica una volta i giocatori per ogni campionato
    by_league = {}
    for c in CAMPIONATI_NOTI:
        players, _ = load_players_for(c)
        if players:
            by_league[c] = players

    leghe = sorted(by_league.keys())
    tot = sum(len(v) for v in by_league.values())
    print(f"Ruolo: {RUOLO} | campionati con dati: {len(leghe)} | giocatori totali: {tot}\n")

    print(f"{'lega esclusa':>14} {'n_val':>6}  {'combo vincente sul TRAIN (tutti tranne la lega)':<48} "
          f"{'MAE train':>10} {'MAE val':>9} {'delta':>7}")
    print("-" * 100)

    folds = []
    for L in leghe:
        train = [p for c, ps in by_league.items() if c != L for p in ps]
        val = by_league[L]
        if len(val) < MIN_PLAYERS_FOLD:
            print(f"{L:>14} {len(val):>6}  (pochi giocatori, salta come validation)")
            continue
        results = aggregate(per_label_from(train), len(train))
        if not results:
            continue
        best = results[0]
        train_mae = best['mae_medio']
        val_mae, _ = weighted_mae_for_label(val, best['label'])
        delta = (val_mae - train_mae) if val_mae is not None else float('nan')
        folds.append({'lega': L, 'label': best['label'], 'train_mae': train_mae,
                      'val_mae': val_mae, 'delta': delta, 'n_val': len(val)})
        vm = f"{val_mae:.2f}" if val_mae is not None else "n/d"
        print(f"{L:>14} {len(val):>6}  {best['label']:<48} {train_mae:>10.2f} {vm:>9} {delta:>+7.2f}")

    if not folds:
        print("\nNessun fold valido.")
        return

    # stabilita' del vincitore + generalizzazione
    from collections import Counter
    winners = Counter(f['label'] for f in folds)
    deltas = [f['delta'] for f in folds if f['val_mae'] is not None]
    print("\n=== SINTESI ===")
    print(f"Combinazione vincente sul train, per quante leghe escluse esce identica:")
    for label, n in winners.most_common():
        print(f"  {n}/{len(folds)}  {label}")
    if deltas:
        avg_delta = sum(deltas) / len(deltas)
        worst = max(folds, key=lambda f: (f['delta'] if f['val_mae'] is not None else -1))
        print(f"\nDelta MAE (validation - train) medio: {avg_delta:+.2f}")
        print(f"  (>0 = la lega esclusa e' piu' difficile della media; vicino a 0 = generalizza bene)")
        print(f"Fold peggiore: {worst['lega']} delta {worst['delta']:+.2f} "
              f"(MAE val {worst['val_mae']:.2f} vs train {worst['train_mae']:.2f})")


if __name__ == '__main__':
    main()
