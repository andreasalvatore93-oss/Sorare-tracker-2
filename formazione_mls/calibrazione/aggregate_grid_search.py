"""
Aggregate Grid Search

Legge i file formazione_mls/output/mls_<ruolo>_calibration/grid_search/
<slug>_grid.json (uno per giocatore, generati dai test_*.py in
CALIBRATION_MODE) e calcola, per ogni combinazione di parametri, il MAE
MEDIO e la copertura media ATTRAVERSO TUTTI i giocatori -- non la
combinazione migliore per un singolo giocatore, ma quella che generalizza
meglio sull'insieme.

La combinazione con il punteggio composito medio piu' basso (stesso criterio
usato per-giocatore: MAE + 0.1*|copertura-68%|) diventa il candidato per i
parametri FISSI del modello finale (fine grid search continuo, un solo set
di parametri usato sempre).

PESO PENALITA' COPERTURA ABBASSATO 0.3 -> 0.1 (27/07, revisione composite
score): il target 68% ha fondamento teorico (copertura attesa a +-1 dev std
in una normale, vedi RANGE_MULTIPLIER/p16/p84 in test_*.py), ma il peso 0.3
non era mai stato calibrato -- era stato scelto ad occhio. Verificato con i
dati di calibrazione globale gia' su disco (65-84 giocatori/ruolo): con peso
0.3 il composite score sceglieva per MID una combinazione con MAE +2.72%
peggiore del vero minimo MAE (hl=12.0/range=1.4/trend=1.3+granulari invece
di hl=12.0/range=1.2/trend=0.7 SENZA granulari, gia' identificato a mano in
docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md come "il vincitore vero" e
gia' i parametri di produzione attuali). Con peso 0.1 il composite score
coincide col vincitore per MAE puro su tutti e 4 i ruoli (mid/def/fwd/gk,
perdita 0.00% ovunque contro dati attuali), pur restando utile come
tie-breaker quando piu' combinazioni hanno MAE davvero equivalente (es. FWD
a peso 0 sceglierebbe un tris di combinazioni a pari MAE con copertura
61.2%, contro 69.5% scelto a peso 0.1). Range di pesi validato [0.08, 0.10];
0.1 lascia margine. Vedi analisi in cronologia sessione 27/07.

PARAMETRIZZATO PER RUOLO (25/07, grid search allargato multi-ruolo): il
ruolo si sceglie con la variabile d'ambiente RUOLO (gk/def/mid/fwd, default
fwd per compatibilita' con l'uso storico di questo script).

PARAMETRIZZATO PER CAMPIONATO (26/07, supporto K League): il campionato si
sceglie con la variabile d'ambiente CAMPIONATO (mls/kleague, default mls
per compatibilita' con l'uso storico -- tutti gli usi esistenti/documentati
continuano a funzionare identici senza settare nulla). Sceglie solo il
prefisso della cartella di output (formazione_<campionato>/output/
<campionato>_<ruolo>_calibration/), la logica di aggregazione e' identica.

MODALITA' GLOBALE (26/07, seconda revisione -- richiesta esplicita
dell'utente): "il modello sara' sempre uno solo, globale, i vari campionati
servono solo ad accumulare dati". Con GLOBALE=1 lo script IGNORA CAMPIONATO
e combina i giocatori qualificati di TUTTI i campionati noti (oggi mls e
kleague) in un unico pool per l'aggregazione -- una sola combinazione
vincente per ruolo, pesata per n_test ESATTAMENTE come al solito, senza
distinzione di provenienza (un giocatore K League con 10 partite pesa
quanto uno MLS con 10 partite). L'output va in una cartella dedicata
(calibrazione_globale/output/<ruolo>_calibration/), separata dalle cartelle
per-campionato (che restano utili come viste diagnostiche/di confronto, non
piu' come fonte dei parametri di produzione). Uso:
  RUOLO=def GLOBALE=1 python formazione_mls/calibrazione/aggregate_grid_search.py

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
CAMPIONATO = os.environ.get('CAMPIONATO', 'mls').strip().lower()
GLOBALE = os.environ.get('GLOBALE', 'no').strip().lower() in ('1', 'true', 'si', 'yes')
CAMPIONATI_NOTI = (
    'mls', 'kleague', 'brasile', 'croazia', 'portogallo', 'austria',
    'scozia', 'belgio', 'olanda', 'spagna',
    # 27/07 (sera): aggiunti i campionati con pipeline+calibrazione creati oggi.
    # Quelli senza storico ancora (stagione non iniziata) contribuiscono 0 grid,
    # innocuo: load_players_for trova semplicemente 0 file e li salta.
    'turchia', 'francia', 'francia2', 'germania', 'germania2',
    'giappone', 'giappone100', 'italia', 'inghilterra', 'inghilterra2',
)  # estendere qui quando si aggiunge un nuovo campionato (27/07: aggiunti gli 8
# campionati con infrastruttura di calibrazione allargata appena creata,
# grid_search_calibrazione_<lega>.yml, pool limitato ai soli posseduti per
# assenza di discovery globale su questi campionati)
MIN_TEST_GAMES = int(os.environ.get('MIN_TEST_GAMES', '3'))

CALIBRATION_DIR = f'formazione_{CAMPIONATO}/output/{CAMPIONATO}_{RUOLO}_calibration'  # solo per modalita' singolo-campionato

_PARTITE_TESTATE_RE = re.compile(r'Partite testate:\s*(\d+)')


def _calibration_dir_for(campionato):
    return f'formazione_{campionato}/output/{campionato}_{RUOLO}_calibration'


def _n_test_from_prediction_file(calibration_dir, slug):
    """Fallback per i grid.json vecchi (senza campo 'n_test'): legge il numero
    di partite testate dal file prediction_<slug>_*.txt corrispondente, stessa
    cartella di calibrazione. Ritorna None se non trovato/non leggibile."""
    candidates = glob.glob(os.path.join(calibration_dir, f'prediction_{slug}_*.txt'))
    if not candidates:
        return None
    with open(candidates[0], 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    m = _PARTITE_TESTATE_RE.search(text)
    return int(m.group(1)) if m else None


def load_players_for(campionato):
    """Ritorna (players, n_excluded) per UN campionato specifico -- stessa
    struttura di load_players() di prima, ma parametrizzata invece di usare
    le costanti globali CALIBRATION_DIR/GRID_DIR (necessario per poter
    caricare piu' campionati nella stessa run, modalita' GLOBALE)."""
    calibration_dir = _calibration_dir_for(campionato)
    grid_dir = os.path.join(calibration_dir, 'grid_search')
    files = glob.glob(os.path.join(grid_dir, '*_grid.json'))
    if not files:
        return [], 0

    players = []
    n_excluded = 0
    for fpath in files:
        slug = os.path.basename(fpath)[:-len('_grid.json')]
        with open(fpath, 'r', encoding='utf-8') as f:
            grid = json.load(f)
        if not grid:
            continue

        n_test = next((c.get('n_test') for c in grid if c.get('n_test') is not None), None)
        if n_test is None:
            n_test = _n_test_from_prediction_file(calibration_dir, slug)

        if n_test is None:
            n_test = 1
        elif n_test < MIN_TEST_GAMES:
            n_excluded += 1
            continue

        combos = [dict(c, n_test=n_test) for c in grid if c.get('mae') is not None]
        if combos:
            players.append({'slug': slug, 'campionato': campionato, 'n_test': n_test, 'combos': combos})

    return players, n_excluded


def load_players():
    """Ritorna (players, n_excluded, per_campionato_counts) -- se GLOBALE e'
    attivo, combina i giocatori qualificati di TUTTI i CAMPIONATI_NOTI in un
    unico pool (un giocatore K League pesa esattamente come uno MLS con lo
    stesso n_test); altrimenti solo il CAMPIONATO scelto (comportamento
    storico). per_campionato_counts e' un dict {campionato: n_giocatori} per
    trasparenza nell'output, anche in modalita' singola."""
    if not GLOBALE:
        players, n_excluded = load_players_for(CAMPIONATO)
        return players, n_excluded, {CAMPIONATO: len(players)}

    all_players = []
    total_excluded = 0
    per_campionato = {}
    for campionato in CAMPIONATI_NOTI:
        players, n_excluded = load_players_for(campionato)
        per_campionato[campionato] = len(players)
        total_excluded += n_excluded
        all_players.extend(players)

    # DEDUP CROSS-CAMPIONATO (30/07, fix bug reale: un giocatore trasferito
    # tra due leghe tracciate -- es. Pep Biel, MLS+Germania -- compariva in
    # ENTRAMBE le cartelle di calibrazione con lo STESSO storico partite
    # (game log per-giocatore, non per-lega), quindi pesava DUE VOLTE nel
    # pool GLOBALE, sfalsando l'aggregazione verso i giocatori doppi. A
    # parita' di slug si tiene solo l'entry con n_test piu' alto (piu'
    # partite di backtest = piu' affidabile); le altre vengono scartate.
    by_slug = {}
    n_dedup_dropped = 0
    for p in all_players:
        existing = by_slug.get(p['slug'])
        if existing is None:
            by_slug[p['slug']] = p
        elif p['n_test'] > existing['n_test']:
            by_slug[p['slug']] = p
            n_dedup_dropped += 1
        else:
            n_dedup_dropped += 1
    if n_dedup_dropped:
        print(f"[dedup cross-campionato] {n_dedup_dropped} entry duplicate scartate "
              f"(stesso giocatore tracciato in piu' di una lega, tenuta solo la versione "
              f"con n_test piu' alto).")
    return list(by_slug.values()), total_excluded, per_campionato


def load_all_grids():
    """Ritorna ({label: [{mae, pct_dentro_range, n_test, ...}, ...]}, n_players,
    n_players_esclusi_per_pochi_test, per_campionato_counts) -- una entry per
    giocatore per ogni combinazione (label) trovata, SOLO per i giocatori con
    n_test sufficiente."""
    players, n_excluded, per_campionato = load_players()
    per_label = defaultdict(list)
    for player in players:
        for combo in player['combos']:
            per_label[combo['label']].append(combo)
    return per_label, len(players), n_excluded, per_campionato


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
        coverage_penalty = abs((avg_coverage or 0) - 68.0) * 0.1  # peso abbassato 0.3->0.1 il 27/07, vedi docstring
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
    per_label, n_players, n_excluded, per_campionato = load_all_grids()
    if not per_label:
        if GLOBALE:
            print("Nessun dato trovato in nessun campionato -- esegui prima i batch di calibrazione.")
        else:
            grid_dir = os.path.join(_calibration_dir_for(CAMPIONATO), 'grid_search')
            print(f"Nessun file trovato in {grid_dir}/ -- esegui prima un run completo di test_{RUOLO}.py")
        return

    if GLOBALE:
        breakdown = ", ".join(f"{c}={n}" for c, n in per_campionato.items())
        print(f"Modalita' GLOBALE: giocatori qualificati per campionato -- {breakdown}")
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
    granulari_str = "CON granulari" if "+granulari" in best['label'] else "SENZA granulari"
    print(f"\n=== COMBINAZIONE VINCENTE AGGREGATA (pesata per n_test, min {MIN_TEST_GAMES} partite) ===")
    print(f"half_life={best['half_life']}, range_multiplier={best['range_multiplier']}, "
          f"opponent_sensitivity={best['opponent_sensitivity']}, "
          f"trend_intensity={best['trend_intensity']}, {granulari_str}")
    print(f"MAE medio: {best['mae_medio']:.2f} | copertura media: {best['copertura_media']:.1f}% "
          f"| basato su {best['n_giocatori']} giocatori ({best['n_partite_totali_pesate']} partite totali)")

    if GLOBALE:
        out_dir = f'calibrazione_globale/output/{RUOLO}_calibration'
    else:
        out_dir = CALIBRATION_DIR
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    out_path = os.path.join(out_dir, 'combinazione_vincente_aggregata.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dict(best, per_campionato=per_campionato), f, ensure_ascii=False, indent=2)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
