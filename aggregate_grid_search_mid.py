"""
aggregate_grid_search_mid.py

Aggrega i risultati del grid search (72 combinazioni) salvati da test_mid.py
per ogni centrocampista (mls_mid_all/grid_search/<slug>_grid.json), calcola
per ogni combinazione di parametri il MAE medio e la copertura media su TUTTI
i giocatori disponibili, e individua la combinazione vincente cross-player
(stessa logica gia' usata per fissare i parametri degli attaccanti).

Punteggio composito per combinazione = MAE_medio + 0.3 * |copertura_media - 68|

Output: mls_mid_all/grid_search/aggregato_<timestamp>.txt con la classifica
completa delle combinazioni ordinate per punteggio composito crescente (la
migliore per prima), piu' il dettaglio dei valori dei 4 parametri vincenti
da riportare come costanti fisse in test_mid.py.
"""
import os
import json
import glob
import datetime
from collections import defaultdict

OUTPUT_DIR = 'mls_mid_all'
GRID_DIR = os.path.join(OUTPUT_DIR, 'grid_search')


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [aggregate_grid_search_mid] {msg}")


def main():
    grid_files = sorted(glob.glob(os.path.join(GRID_DIR, '*_grid.json')))
    log(f"Trovati {len(grid_files)} file grid_search da aggregare.")

    if not grid_files:
        log("Nessun file trovato, interrompo.")
        return

    # Raggruppa per label (combinazione di parametri) attraverso tutti i giocatori
    by_label = defaultdict(list)
    players_found = []

    for gf in grid_files:
        slug = os.path.basename(gf).replace('_grid.json', '')
        with open(gf, 'r', encoding='utf-8') as f:
            try:
                rows = json.load(f)
            except json.JSONDecodeError:
                log(f"[{slug}] file JSON non valido, saltato.")
                continue
        if not rows:
            log(f"[{slug}] nessun risultato grid valido, saltato.")
            continue
        players_found.append(slug)
        for r in rows:
            by_label[r['label']].append(r)

    log(f"Giocatori con dati validi: {len(players_found)} -> {players_found}")

    aggregated = []
    for label, rows in by_label.items():
        maes = [r['mae'] for r in rows if r.get('mae') is not None]
        coverages = [r['pct_dentro_range'] for r in rows if r.get('pct_dentro_range') is not None]
        if not maes:
            continue
        mae_medio = sum(maes) / len(maes)
        coverage_medio = sum(coverages) / len(coverages) if coverages else None
        coverage_penalty = abs((coverage_medio or 0) - 68.0) * 0.3
        composite = mae_medio + coverage_penalty
        sample = rows[0]
        aggregated.append({
            'label': label,
            'half_life': sample['half_life'],
            'range_multiplier': sample['range_multiplier'],
            'opponent_sensitivity': sample['opponent_sensitivity'],
            'trend_intensity': sample['trend_intensity'],
            'mae_medio': mae_medio,
            'coverage_medio': coverage_medio,
            'composite': composite,
            'n_giocatori': len(maes),
        })

    aggregated.sort(key=lambda x: x['composite'])

    lines = []
    lines.append("=" * 70)
    lines.append("GRID SEARCH CROSS-PLAYER CENTROCAMPISTI — CLASSIFICA COMBINAZIONI")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append(f"Giocatori aggregati: {len(players_found)} -> {', '.join(players_found)}")
    lines.append("=" * 70)
    lines.append("")

    if aggregated:
        best = aggregated[0]
        lines.append("COMBINAZIONE VINCENTE:")
        lines.append(f"  half_life={best['half_life']}, range_multiplier={best['range_multiplier']}, "
                      f"opponent_sensitivity={best['opponent_sensitivity']}, "
                      f"trend_intensity={best['trend_intensity']}")
        lines.append(f"  MAE medio: {best['mae_medio']:.2f} | Copertura media: "
                      f"{best['coverage_medio']:.1f}% | Punteggio composito: {best['composite']:.2f}")
        lines.append(f"  Basato su {best['n_giocatori']} giocatori")
        lines.append("")
        lines.append("-" * 70)
        lines.append("CLASSIFICA COMPLETA (migliore -> peggiore):")
        lines.append("-" * 70)
        for idx, a in enumerate(aggregated, 1):
            cov_str = f"{a['coverage_medio']:.1f}%" if a['coverage_medio'] is not None else "N/D"
            lines.append(f"{idx:>3}) {a['label']:<55} MAE={a['mae_medio']:>6.2f} "
                         f"cov={cov_str:>7} composito={a['composite']:>6.2f} (n={a['n_giocatori']})")
    else:
        lines.append("Nessuna combinazione con dati sufficienti per l'aggregazione.")

    lines.append("=" * 70)
    final_text = "\n".join(lines)

    if not os.path.exists(GRID_DIR):
        os.makedirs(GRID_DIR)
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join(GRID_DIR, f'aggregato_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(final_text)

    log(f"Aggregazione scritta in: {out_path}")
    print("\n" + final_text)


if __name__ == '__main__':
    main()
