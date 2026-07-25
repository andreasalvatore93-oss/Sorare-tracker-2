"""
Aggregate Grid Search

Legge i file formazione_mls/output/mls_<ruolo>_calibration/grid_search/
<slug>_grid.json (uno per giocatore, generati dai test_*.py in
CALIBRATION_MODE) e calcola, per ogni combinazione di parametri, il MAE
MEDIO e la copertura media ATTRAVERSO TUTTI i giocatori -- non la
combinazione migliore per un singolo giocatore, ma quella che generalizza
meglio sull'insieme.

La combinazione con il punteggio composito medio piu' basso (stesso criterio
usato per-giocatore: MAE + 0.3*|copertura-68%|) diventa il candidato per i
parametri FISSI del modello finale (fine grid search continuo, un solo set
di parametri usato sempre).

PARAMETRIZZATO PER RUOLO (25/07, grid search allargato multi-ruolo): il
ruolo si sceglie con la variabile d'ambiente RUOLO (gk/def/mid/fwd, default
fwd per compatibilita' con l'uso storico di questo script).

PESATURA PER NUMERO DI PARTITE DI BACKTEST (26/07): analizzando il caso FWD
si e' scoperto che l'effetto dei fattori granulari per singolo giocatore va
da -5 a +5 di MAE, ma la media aggregata si cancella quasi a zero -- gran
parte di questa varianza estrema e' rumore statistico da giocatori con
pochissime partite di backtest disponibili (mediana 7, alcuni con solo 1-3).
Un giocatore con 1 sola partita testata contribuisce all'aggregato con lo
stesso peso di uno con 9 partite, pur essendo il suo MAE l'errore di un
singolo evento anziché una media stabile. Fix: (1) i giocatori con meno di
MIN_TEST_GAMES partite di backtest sono ESCLUSI dall'aggregazione (troppo
rumorosi per contribuire in modo affidabile); (2) tra i rimasti, MAE e
copertura sono medie PESATE per n_test (un giocatore con piu' partite pesa
di piu' nella media, invece di un peso identico a parita' di giocatore).
n_test e' costante tra le combinazioni di uno stesso giocatore (stessa
finestra storica per ogni combo), letto dal campo 'n_test' del grid.json se
presente (run nuovi), altrimenti recuperato per compatibilita' dal file
prediction_<slug>_*.txt corrispondente (run vecchi, GK/DEF/MID/FWD del primo
giro 25-26/07, generati prima di questo fix), riga "Partite testate: N".

Uso: eseguito DOPO uno o piu' run a batch di test_<ruolo>.py in
CALIBRATION_MODE (i risultati si accumulano nella cartella grid_search/ ad
ogni batch, quindi puo' essere rilanciato in qualsiasi momento per vedere lo
stato aggregato parziale), localmente o in un job GitHub Actions dedicato.
"""
import os
import re
import json
import glob
from collections import defaultdict

RUOLO = os.environ.get('RUOLO', 'fwd').strip().lower()
MIN_TEST_GAMES = int(os.environ.get('MIN_TEST_GAMES', '3'))
CALIBRATION_DIR = f'formazione_mls/output/mls_{RUOLO}_calibration'
GRID_DIR = os.path.join(CALIBRATION_DIR, 'grid_search')

_PARTITE_TESTATE_RE = re.compile(r'Partite testate:\s*(\d+)')


def _n_test_from_prediction_file(slug):
    """Fallback per i grid.json vecchi (senza campo 'n_test'): legge il numero
    di partite testate dal file prediction_<slug>_*.txt corrispondente, stessa
    cartella di calibrazione. Ritorna None se non trovato/non leggibile."""
    candidates = glob.glob(os.path.join(CALIBRATION_DIR, f'prediction_{slug}_*.txt'))
    if not candidates:
        return None
    with open(candidates[0], 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    m = _PARTITE_TESTATE_RE.search(text)
    return int(m.group(1)) if m else None


def load_all_grids():
    """Ritorna ({label: [{mae, pct_dentro_range, n_test, ...}, ...]}, n_players,
    n_players_esclusi_per_pochi_test) -- una entry per giocatore per ogni
    combinazione (label) trovata, SOLO per i giocatori con n_test sufficiente."""
    per_label = defaultdict(list)
    files = glob.glob(os.path.join(GRID_DIR, '*_grid.json'))
    if not files:
        print(f"Nessun file trovato in {GRID_DIR}/ -- esegui prima un run completo di test_{RUOLO}.py")
        return per_label, 0, 0

    n_players = 0
    n_excluded = 0
    for fpath in files:
        slug = os.path.basename(fpath)[:-len('_grid.json')]
        with open(fpath, 'r', encoding='utf-8') as f:
            grid = json.load(f)
        if not grid:
            continue

        # n_test e' identico per ogni combo dello stesso giocatore (stessa
        # finestra storica) -- lo si legge dal primo elemento che lo abbia.
        n_test = next((c.get('n_test') for c in grid if c.get('n_test') is not None), None)
        if n_test is None:
            n_test = _n_test_from_prediction_file(slug)

        if n_test is None:
            # Nessun modo di sapere quante partite -- non lo scartiamo per
            # non perdere dati, ma non puo' essere pesato: trattato come peso 1.
            n_test = 1
        elif n_test < MIN_TEST_GAMES:
            n_excluded += 1
            continue

        n_players += 1
        for combo in grid:
            if combo.get('mae') is None:
                continue
            entry = dict(combo)
            entry['n_test'] = n_test
            per_label[combo['label']].append(entry)

    return per_label, n_players, n_excluded


def aggregate(per_label, n_players):
    """Per ogni label, calcola MAE medio e copertura media (PESATI per n_test)
    SOLO sulle combinazioni presenti per un numero minimo di giocatori (per
    non far vincere una combinazione forte su 1-2 giocatori per puro caso)."""
    min_players_required = max(3, int(n_players * 0.5))  # almeno meta' dei giocatori disponibili
    results = []
    for label, entries in per_label.items():
        if len(entries) < min_players_required:
            continue
        total_weight = sum(e['n_test'] for e in entries)
        avg_mae = sum(e['mae'] * e['n_test'] for e in entries) / total_weight
        coverage_entries = [e for e in entries if e['pct_dentro_range'] is not None]
        if coverage_entries:
            cov_weight = sum(e['n_test'] for e in coverage_entries)
            avg_coverage = sum(e['pct_dentro_range'] * e['n_test'] for e in coverage_entries) / cov_weight
        else:
            avg_coverage = None
        coverage_penalty = abs((avg_coverage or 0) - 68.0) * 0.3
        composite = avg_mae + coverage_penalty
        results.append({
            'label': label,
            'n_giocatori': len(entries),
            'n_partite_totali_pesate': total_weight,
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
    per_label, n_players, n_excluded = load_all_grids()
    if not per_label:
        return

    print(f"Giocatori con grid search disponibile e >= {MIN_TEST_GAMES} partite di backtest: {n_players}")
    if n_excluded:
        print(f"Giocatori ESCLUSI per meno di {MIN_TEST_GAMES} partite di backtest (troppo rumorosi): {n_excluded}")
    results = aggregate(per_label, n_players)

    if not results:
        print("Nessuna combinazione presente per un numero sufficiente di giocatori.")
        return

    print(f"\n{'#':>3} {'half_life':>9} {'range_x':>8} {'opp_sens':>9} {'trend_int':>10} "
          f"{'MAE medio':>10} {'copertura%':>11} {'n_gioc':>7} {'n_partite_w':>12}  etichetta")
    for i, r in enumerate(results[:20], 1):
        print(f"{i:>3} {r['half_life']:>9} {r['range_multiplier']:>8} "
              f"{r['opponent_sensitivity']:>9} {r['trend_intensity']:>10} "
              f"{r['mae_medio']:>10.2f} {r['copertura_media']:>10.1f}% {r['n_giocatori']:>7} "
              f"{r['n_partite_totali_pesate']:>12}  {r['label']}")

    best = results[0]
    print(f"\n=== COMBINAZIONE VINCENTE AGGREGATA (pesata per n_test, min {MIN_TEST_GAMES} partite) ===")
    print(f"half_life={best['half_life']}, range_multiplier={best['range_multiplier']}, "
          f"opponent_sensitivity={best['opponent_sensitivity']}, "
          f"trend_intensity={best['trend_intensity']}")
    print(f"MAE medio: {best['mae_medio']:.2f} | copertura media: {best['copertura_media']:.1f}% "
          f"| basato su {best['n_giocatori']} giocatori ({best['n_partite_totali_pesate']} partite totali)")

    out_path = os.path.join(CALIBRATION_DIR, 'combinazione_vincente_aggregata.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(best, f, ensure_ascii=False, indent=2)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
