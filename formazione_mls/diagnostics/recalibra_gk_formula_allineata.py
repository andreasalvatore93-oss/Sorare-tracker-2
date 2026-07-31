"""Ricalibrazione GK sulla formula ALLINEATA alla produzione (31/07).

Perche': il grid search che gira in CALIBRATION_MODE per GK usa
`rigorous_backtest` -- la vecchia formula moltiplicativa (media pesata x
fattore casa x fattore avversario x trend), che NON ha level_score da tassi
Poisson, NON ha shrinkage verso il prior di ruolo, NON ha shrinkage venue e
usa il fattore_forza_avversario da ranking, rimosso dalla produzione il
26/07 perche' peggiorava il MAE. Misurato: 16.970 di MAE contro 15.757
della formula vera, il 7% di distanza. Quindi half_life/trend/range per il
portiere sono stati scelti ottimizzando un modello che non e' quello che
schiera.

Qui si rifa' il grid search chiamando `compute_score_atteso_gk`, cioe' la
STESSA funzione della predizione reale, su tutti i portieri in cache, e si
confronta il vincitore con i valori oggi in produzione.

Uso: python formazione_mls/diagnostics/recalibra_gk_formula_allineata.py
"""
import os
import sys
import statistics
import importlib.util

sys.path.insert(0, os.getcwd())

_spec = importlib.util.spec_from_file_location(
    'aud_gk', 'formazione_mls/diagnostics/audit_backtest_vs_produzione_gk.py')
_aud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aud)
gk = _aud.gk

MIN_HISTORY = 6
HALF_LIVES = (4.0, 6.0, 9.0, 12.0, 15.0, 20.0, 25.0, 30.0)
TREND_INTENSITIES = (0.0, 0.2, 0.3, 0.7, 1.0, 1.3)
RANGE_MULTS = (1.0, 1.1, 1.15, 1.2, 1.3, 1.4)


def main():
    print("Carico portieri dalla cache...")
    players = _aud.load_players()
    print(f"Portieri: {len(players)}\n")

    # Pre-estrazione: per ogni giocatore, le liste che servono alla formula.
    dataset = []
    for lega, slug, rows, pr in players:
        dataset.append((
            [r['score'] for r in rows],
            [r['is_home'] for r in rows],
            [r['gran'] for r in rows],
            [r['pos'] for r in rows],
            [r['neg'] for r in rows],
            pr,
        ))

    risultati = []
    for hl in HALF_LIVES:
        for ti in TREND_INTENSITIES:
            errori = []
            devstd_rel = []
            for scores, homes, gran, pos, neg, pr in dataset:
                n = len(scores)
                w_cache = {}
                for i in range(MIN_HISTORY, n):
                    pred = gk.compute_score_atteso_gk(
                        scores[:i], homes[:i], gran[:i], pos[:i], neg[:i],
                        target_is_home=homes[i], half_life=hl, trend_intensity=ti,
                        presence_rate=pr)
                    err = scores[i] - pred
                    errori.append(err)
                    if i not in w_cache:
                        w_cache[i] = gk.exponential_weights(i, hl)
                    w = w_cache[i]
                    sd = gk.weighted_stddev(scores[:i], w, gk.weighted_mean(scores[:i], w))
                    devstd_rel.append(sd)
            mae = statistics.mean(abs(e) for e in errori)
            for rm in RANGE_MULTS:
                cop = sum(1 for e, sd in zip(errori, devstd_rel)
                          if sd > 0 and abs(e) <= sd * rm) / len(errori) * 100
                composite = mae + abs(cop - 68.0) * 0.3
                risultati.append((composite, mae, cop, hl, ti, rm))

    risultati.sort()
    print(f"{'#':>3} {'composite':>10} {'MAE':>8} {'copertura':>10} {'half_life':>10} "
          f"{'trend':>7} {'range':>7}")
    for idx, (c, mae, cop, hl, ti, rm) in enumerate(risultati[:15], 1):
        print(f"{idx:>3} {c:>10.3f} {mae:>8.3f} {cop:>9.1f}% {hl:>10} {ti:>7} {rm:>7}")

    attuale = [r for r in risultati
               if r[3] == gk.HALF_LIFE_GAMES and r[4] == gk.TREND_INTENSITY and r[5] == 1.15]
    if attuale:
        c, mae, cop, hl, ti, rm = attuale[0]
        pos_att = risultati.index(attuale[0]) + 1
        best = risultati[0]
        print(f"\nPRODUZIONE OGGI: half_life={hl}, trend={ti}, range={rm}")
        print(f"  composite {c:.3f} (MAE {mae:.3f}, copertura {cop:.1f}%) "
              f"-> posizione {pos_att} su {len(risultati)}")
        print(f"VINCITORE:       half_life={best[3]}, trend={best[4]}, range={best[5]}")
        print(f"  composite {best[0]:.3f} (MAE {best[1]:.3f}, copertura {best[2]:.1f}%)")
        print(f"\nGuadagno potenziale in MAE: {(best[1] - mae) / mae * 100:+.2f}%")


if __name__ == '__main__':
    main()
