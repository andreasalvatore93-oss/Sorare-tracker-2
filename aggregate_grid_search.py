"""
Aggregate Grid Search

Legge i file mls_fwd_all/grid_search_full/<slug>_grid.json (uno per
giocatore, generati da test_mls_fwd_all.py) e calcola, per ogni combinazione
di parametri, il MAE MEDIO e la copertura media ATTRAVERSO TUTTI i giocatori
-- non la combinazione migliore per un singolo giocatore, ma quella che
generalizza meglio sull'insieme.

La combinazione con il punteggio composito medio piu' basso (stesso criterio
usato per-giocatore: MAE + 0.3*|copertura-68%|) diventa il candidato per i
parametri FISSI del modello finale (fine grid search continuo, un solo set
di parametri usato sempre).

Uso: eseguito DOPO un run completo di test_mls_fwd_all.py (via git pull della
cartella mls_fwd_all/grid_search_full/), localmente o in un job GitHub
Actions dedicato.
"""
import os
import json
import glob
from collections import defaultdict

GRID_DIR = os.path.join('mls_fwd_all', 'grid_search_full')


def load_all_grids():
    """Ritorna {label: [{mae, pct_dentro_range, composite_score, ...}, ...]}
    con una entry per giocatore per ogni combinazione (label) trovata."""
    per_label = defaultdict(list)
    files = glob.glob(os.path.join(GRID_DIR, '*_grid.json'))
    if not files:
        print(f"Nessun file trovato in {GRID_DIR}/ -- esegui prima un run completo di test_mls_fwd_all.py")
        return per_label, 0

    n_players = 0
    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            grid = json.load(f)
        if not grid:
            continue
        n_players += 1
        for combo in grid:
            if combo.get('mae') is None:
                continue
            per_label[combo['label']].append(combo)

    return per_label, n_players


def aggregate(per_label, n_players):
    """Per ogni label, calcola MAE medio e copertura media SOLO sulle
    combinazioni presenti per un numero minimo di giocatori (per non far
    vincere una combinazione forte su 1-2 giocatori per puro caso)."""
    min_players_required = max(3, int(n_players * 0.5))  # almeno meta' dei giocatori disponibili
    results = []
    for label, entries in per_label.items():
        if len(entries) < min_players_required:
            continue
        maes = [e['mae'] for e in entries]
        coverages = [e['pct_dentro_range'] for e in entries if e['pct_dentro_range'] is not None]
        avg_mae = sum(maes) / len(maes)
        avg_coverage = sum(coverages) / len(coverages) if coverages else None
        coverage_penalty = abs((avg_coverage or 0) - 68.0) * 0.3
        composite = avg_mae + coverage_penalty
        results.append({
            'label': label,
            'n_giocatori': len(entries),
            'mae_medio': avg_mae,
            'copertura_media': avg_coverage,
            'composite_score_medio': composite,
            'half_life': entries[0]['half_life'],
            'range_multiplier': entries[0]['range_multiplier'],
            'opponent_sensitivity': entries[0]['opponent_sensitivity'],
            'trend_intensity': entries[0]['trend_intensity'],
        })

    results.sort(key=lambda r: r['composite_score_medio'])
    return results


def main():
    per_label, n_players = load_all_grids()
    if not per_label:
        return

    print(f"Giocatori con grid search disponibile: {n_players}")
    results = aggregate(per_label, n_players)

    if not results:
        print("Nessuna combinazione presente per un numero sufficiente di giocatori.")
        return

    print(f"\n{'#':>3} {'half_life':>9} {'range_x':>8} {'opp_sens':>9} {'trend_int':>10} "
          f"{'MAE medio':>10} {'copertura%':>11} {'n_gioc':>7}  etichetta")
    for i, r in enumerate(results[:20], 1):
        print(f"{i:>3} {r['half_life']:>9} {r['range_multiplier']:>8} "
              f"{r['opponent_sensitivity']:>9} {r['trend_intensity']:>10} "
              f"{r['mae_medio']:>10.2f} {r['copertura_media']:>10.1f}% {r['n_giocatori']:>7}  {r['label']}")

    best = results[0]
    print(f"\n=== COMBINAZIONE VINCENTE AGGREGATA ===")
    print(f"half_life={best['half_life']}, range_multiplier={best['range_multiplier']}, "
          f"opponent_sensitivity={best['opponent_sensitivity']}, "
          f"trend_intensity={best['trend_intensity']}")
    print(f"MAE medio: {best['mae_medio']:.2f} | copertura media: {best['copertura_media']:.1f}% "
          f"| basato su {best['n_giocatori']} giocatori")

    out_path = os.path.join('mls_fwd_all', 'combinazione_vincente_aggregata.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(best, f, ensure_ascii=False, indent=2)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
