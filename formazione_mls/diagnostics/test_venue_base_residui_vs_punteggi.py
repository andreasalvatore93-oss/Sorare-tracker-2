"""DEBITO 3 (31/07, audit): il fattore casa/trasferta usa una base diversa
a seconda del ruolo, e nessun commento dichiara la scelta come deliberata.

  - GK  -> calcolato inline sui punteggi PIENI (`scores`)
  - DEF/MID/FWD -> compute_split_factor sui RESIDUI (`residual_values`,
    cioe' il punteggio meno tutti i gruppi granulari tracciati)

La logica dei residui avrebbe senso per evitare un doppio conteggio con
Stadio D (che condiziona per venue alcuni gruppi granulari). Ma il conto non
torna: FWD esclude dal fattore venue fouls/duels/offensive/passing/
defense_rare, mentre Stadio D gli ricondiziona SOLO il passaggio -- quindi la
dipendenza dal venue di tutto il resto non viene modellata da nessuna parte.

Test pulito: dentro `compute_score_atteso_*`, `residual_values` e' usato
ESCLUSIVAMENTE per il fattore venue (verificato leggendo le tre funzioni).
Quindi basta chiamare la funzione REALE due volte, una passando i residui
(produzione) e una passando gli score pieni nello stesso slot, e confrontare
la MAE walk-forward. Nessuna reimplementazione: se il risultato cambia, e'
solo per la base del fattore venue.

Uso: python formazione_mls/diagnostics/test_venue_base_residui_vs_punteggi.py [def|mid|fwd]
"""
import os
import sys
import statistics
import importlib.util

sys.path.insert(0, os.getcwd())

_spec = importlib.util.spec_from_file_location(
    'recal', 'formazione_mls/diagnostics/recalibra_mid_fwd_formula_allineata.py')
_R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_R)

MIN_HISTORY = 6


def valuta(ruolo, mod, dataset, usa_score_pieni):
    errori = []
    for lega, righe, pr in dataset:
        n = len(righe)
        for i in range(MIN_HISTORY, n):
            h = righe[:i]
            base_venue = ([r['score'] for r in h] if usa_score_pieni
                          else [r['res'] for r in h])
            comune = dict(
                scores=[r['score'] for r in h], is_home_flags=[r['is_home'] for r in h],
                residual_values=base_venue, granulari_values=[r['gran'] for r in h],
                pos_decisive_values=[r['pos'] for r in h],
                neg_decisive_values=[r['neg'] for r in h],
                target_is_home=righe[i]['is_home'], p_gioca=1.0,
                presence_rate=pr, league=lega,
            )
            if ruolo == 'mid':
                pred = mod.compute_score_atteso_mid(
                    opponent_rankings=[None] * i,
                    offensive_values=[r['off'] for r in h],
                    passing_values=[r['pas'] for r in h],
                    goals_conceded_values=[r['gc'] for r in h],
                    target_opp_rank=None,
                    opponent_team_slugs=[r['opp'] for r in h],
                    game_dates=[r['dt'] for r in h],
                    target_opponent_team_slug=righe[i]['opp'],
                    target_cutoff_dt=righe[i]['dt'],
                    **comune)
            else:
                pred = mod.compute_score_atteso_fwd(
                    passing_values=[r['pas'] for r in h],
                    offensive_values=[r['off'] for r in h],
                    next_opponent_team_slug=righe[i]['opp'],
                    next_game_date=righe[i]['dt'],
                    **comune)
            errori.append(abs(righe[i]['score'] - pred))
    return statistics.mean(errori), len(errori)


def main():
    ruoli = sys.argv[1:] or ['mid', 'fwd']
    for ruolo in ruoli:
        mod = _R.imp(f'test_{ruolo}_lib', _R.MODULI[ruolo])
        print(f"\n{'=' * 74}\nRUOLO {ruolo.upper()} — base del fattore casa/trasferta\n{'=' * 74}")
        dataset = _R.carica(ruolo, mod)
        print(f"Giocatori: {len(dataset)}")
        mae_res, n = valuta(ruolo, mod, dataset, usa_score_pieni=False)
        mae_full, _ = valuta(ruolo, mod, dataset, usa_score_pieni=True)
        print(f"  residui (PRODUZIONE OGGI): MAE {mae_res:.4f}")
        print(f"  punteggi pieni (come GK):  MAE {mae_full:.4f}")
        delta = (mae_full - mae_res) / mae_res * 100
        if abs(delta) < 0.05:
            verdetto = "equivalenti (differenza sotto lo 0.05%, non azionabile)"
        elif delta < 0:
            verdetto = f"i PUNTEGGI PIENI sarebbero migliori ({delta:+.2f}%)"
        else:
            verdetto = f"i residui (attuale) sono migliori ({delta:+.2f}%)"
        print(f"  -> {verdetto}   [{n} punti di test]")


if __name__ == '__main__':
    main()
