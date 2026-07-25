"""
Bootstrap Stability Check (26/07/2026)

Verifica quanto e' STATISTICAMENTE SOLIDA la combinazione vincente trovata
da aggregate_grid_search.py, invece di fidarsi ciecamente di un singolo
numero calcolato su un solo campione di giocatori.

Metodo: ricampiona con sostituzione (bootstrap classico) i giocatori
qualificati N_BOOTSTRAP volte (stessa dimensione campione originale ad ogni
ricampionamento), rifà l'aggregazione pesata per n_test su ogni campione
ricampionato, e registra:
1. Quante volte ciascuna combinazione VINCE sul totale dei ricampionamenti
   (bootstrap win-rate) -- se la combinazione vincente originale vince anche
   la stragrande maggioranza dei ricampionamenti, la scelta e' solida; se
   vince solo una minoranza, la "vittoria" nell'aggregazione originale era
   in gran parte un caso di campione, non un segnale robusto.
2. Un intervallo di confidenza (percentile 2.5%-97.5%) sul MAE della
   combinazione vincente ORIGINALE attraverso i ricampionamenti -- utile
   soprattutto quando due combinazioni sono molto vicine (differenza di
   MAE < 0.2, come visto spesso nei grid search di oggi): se gli intervalli
   si sovrappongono ampiamente, la differenza e' dentro il rumore.

Uso: RUOLO=<ruolo> N_BOOTSTRAP=1000 python formazione_mls/calibrazione/bootstrap_stability.py
Richiede gli stessi dati di aggregate_grid_search.py (grid_search/*_grid.json
gia' scaricati su disco, git pull prima se serve). Puro calcolo locale,
nessun nuovo run GitHub necessario. Deterministico (SEED fisso di default),
per poter confrontare risultati tra esecuzioni diverse.
"""
import os
import random
from collections import defaultdict, Counter

from aggregate_grid_search import load_players, aggregate, RUOLO, MIN_TEST_GAMES

N_BOOTSTRAP = int(os.environ.get('N_BOOTSTRAP', '1000'))
SEED = int(os.environ.get('SEED', '42'))


def resample_and_aggregate(players, rng):
    """Ricampiona i giocatori CON sostituzione (stessa dimensione del
    campione originale) e rifa' l'aggregazione pesata per n_test su questo
    campione. Le ripetizioni di uno stesso giocatore (bootstrap classico)
    contribuiscono piu' volte al peso E al conteggio 'n_giocatori' per la
    soglia di copertura minima -- comportamento bootstrap standard."""
    sample = [players[rng.randrange(len(players))] for _ in range(len(players))]
    return aggregate(_per_label(sample), len(sample))


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _per_label(players):
    per_label = defaultdict(list)
    for player in players:
        for combo in player['combos']:
            per_label[combo['label']].append(combo)
    return per_label


def main():
    players, n_excluded = load_players()
    if not players:
        return

    print(f"Ruolo: {RUOLO} | Giocatori qualificati (>= {MIN_TEST_GAMES} partite di backtest): "
          f"{len(players)} (esclusi: {n_excluded})")

    original_results = aggregate(_per_label(players), len(players))
    if not original_results:
        print("Nessuna combinazione presente per un numero sufficiente di giocatori nel campione originale.")
        return

    original_winner = original_results[0]['label']
    print(f"\nCombinazione vincente sul campione ORIGINALE: {original_winner}")
    print(f"MAE originale: {original_results[0]['mae_medio']:.2f} | "
          f"copertura: {original_results[0]['copertura_media']:.1f}%")

    rng = random.Random(SEED)
    win_counter = Counter()
    original_winner_maes = []
    original_winner_seen = 0

    for _ in range(N_BOOTSTRAP):
        results = resample_and_aggregate(players, rng)
        if not results:
            continue
        win_counter[results[0]['label']] += 1
        for r in results:
            if r['label'] == original_winner:
                original_winner_maes.append(r['mae_medio'])
                original_winner_seen += 1
                break

    print(f"\n=== BOOTSTRAP WIN-RATE (top 10 su {N_BOOTSTRAP} ricampionamenti) ===")
    for label, count in win_counter.most_common(10):
        marker = "  <-- VINCITORE ORIGINALE" if label == original_winner else ""
        print(f"{count / N_BOOTSTRAP * 100:5.1f}%  ({count:4d}/{N_BOOTSTRAP})  {label}{marker}")

    original_win_rate = win_counter.get(original_winner, 0) / N_BOOTSTRAP * 100
    print(f"\nLa combinazione vincente originale ('{original_winner}') vince il "
          f"{original_win_rate:.1f}% dei ricampionamenti bootstrap.")
    if original_win_rate >= 60:
        print("-> Scelta STATISTICAMENTE SOLIDA: vince la maggioranza netta dei ricampionamenti.")
    elif original_win_rate >= 30:
        print("-> Scelta INCERTA: vince spesso ma non domina -- probabilmente equivalente ad "
              "altre 1-2 combinazioni entro il rumore statistico, non una vittoria netta.")
    else:
        print("-> Scelta DEBOLE: la vittoria sul campione originale sembra in gran parte un caso "
              "di campionamento, non un segnale robusto -- da NON considerare definitiva.")

    if original_winner_maes:
        original_winner_maes.sort()
        lo = percentile(original_winner_maes, 2.5)
        hi = percentile(original_winner_maes, 97.5)
        print(f"\nMAE della combinazione vincente originale, intervallo di confidenza bootstrap "
              f"95% (presente in {original_winner_seen}/{N_BOOTSTRAP} ricampionamenti): "
              f"[{lo:.2f} - {hi:.2f}]")
        print("Se il MAE di un'altra combinazione candidata rientra in questo intervallo, la "
              "differenza rispetto alla vincente non e' statisticamente significativa.")


if __name__ == '__main__':
    main()
