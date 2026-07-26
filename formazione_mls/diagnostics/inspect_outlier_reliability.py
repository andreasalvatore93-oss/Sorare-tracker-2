"""
Inspect Outlier Reliability (26/07/2026)

Diagnostico locale (nessuna query API, legge solo le cache
.cache/*_detail_cache.json gia' scaricate dai run di calibrazione) per
quantificare il problema "outlier/hot-streak" del backlog: quanto e' diffuso
il pattern per cui la media pesata di un giocatore viene "trainata" da 1-2
partite isolate ad alto punteggio, invece che da una prestazione costante?

Caso motivante (sessione 26/07, formazione reale): Antino Lopez (DEF) gioca
solo il 25% delle ultime 40 partite storiche, ma con 2 picchi isolati (86/81)
finiva capitano a 86pt nel vecchio modello -- piu' sovrappesato di quanto
"meriti" un giocatore con cosi' poche presenze. Carles Gil (MID, presenze
quasi 100%, media stabile 67-70) e' l'opposto: affidabile ma senza picchi.

Metrica usata (nessun dato aggiuntivo richiesto, solo la sequenza di score
gia' in cache per giocatore):
- n_games: numero di partite con score disponibile in cache (proxy di
  "presenze" -- e' un career count, non un rapporto su partite disponibili
  della squadra, che richiederebbe il calendario squadra non scaricato qui).
- media, deviazione standard, coefficiente di variazione (std/media).
- top1_share / top2_share: di quanto scende la media del giocatore se si
  esclude la sua partita migliore (top1) o le sue 2 partite migliori (top2)
  -- es. top2_share=20% vuol dire che le 2 partite migliori "valgono" il 20%
  della media totale, il resto delle partite pesa relativamente meno.
- Un giocatore viene marcato ad alto rischio "outlier-driven" se ha POCHE
  presenze (n_games sotto una soglia) E la sua media dipende molto dalle 1-2
  partite migliori (top2_share sopra una soglia) -- esattamente il pattern
  Antino Lopez.

Uso: RUOLO=def python formazione_mls/diagnostics/inspect_outlier_reliability.py
Legge da formazione_mls/output/mls_<ruolo>_calibration/.cache/*_detail_cache.json
(le stesse cache gia' committate dai run di calibrazione allargata, campione
molto piu' ampio dei soli posseduti).

Env facoltativi:
  MIN_GAMES_LOW=8       sotto questa soglia n_games e' considerato "poche presenze"
  TOP2_SHARE_HIGH=0.18  sopra questa soglia la media e' considerata "trainata" dai picchi
"""
import os
import json
import glob
import statistics

RUOLO = os.environ.get('RUOLO', 'def').strip().lower()
CACHE_DIR = f'formazione_mls/output/mls_{RUOLO}_calibration/.cache'

MIN_GAMES_LOW = int(os.environ.get('MIN_GAMES_LOW', '8'))
TOP2_SHARE_HIGH = float(os.environ.get('TOP2_SHARE_HIGH', '0.18'))


def load_player_scores(fpath):
    """Ritorna la lista (ordinata per data) di score reali del giocatore,
    dalla stessa cache usata in produzione/calibrazione -- solo partite con
    scoreStatus FINAL e uno score numerico valido."""
    with open(fpath, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    games = []
    for entry in cache.values():
        score = entry.get('score')
        game = entry.get('anyGame') or {}
        date = game.get('date')
        if score is None or not date:
            continue
        if entry.get('scoreStatus') != 'FINAL':
            continue
        games.append((date, float(score)))
    games.sort(key=lambda g: g[0])
    return [s for _, s in games]


def player_stats(scores):
    n = len(scores)
    if n == 0:
        return None
    mean = statistics.mean(scores)
    std = statistics.pstdev(scores) if n > 1 else 0.0
    cv = std / mean if mean else 0.0

    sorted_desc = sorted(scores, reverse=True)
    rest1 = scores_without_top(scores, sorted_desc[:1])
    rest2 = scores_without_top(scores, sorted_desc[:2])
    mean_wo_top1 = statistics.mean(rest1) if rest1 else mean
    mean_wo_top2 = statistics.mean(rest2) if rest2 else mean
    top1_share = (mean - mean_wo_top1) / mean if mean else 0.0
    top2_share = (mean - mean_wo_top2) / mean if mean else 0.0

    return {
        'n_games': n, 'mean': mean, 'std': std, 'cv': cv,
        'top1_share': top1_share, 'top2_share': top2_share,
        'best_score': sorted_desc[0], 'worst_score': sorted_desc[-1],
    }


def scores_without_top(scores, top_values):
    """Rimuove UNA occorrenza per ciascun valore in top_values (non tutte le
    occorrenze di quel punteggio, nel caso raro di pareggi esatti)."""
    remaining = list(scores)
    for v in top_values:
        remaining.remove(v)
    return remaining


def main():
    files = glob.glob(os.path.join(CACHE_DIR, '*_detail_cache.json'))
    if not files:
        print(f"Nessuna cache trovata in {CACHE_DIR}/")
        return

    rows = []
    for fpath in files:
        slug = os.path.basename(fpath).replace('_detail_cache.json', '')
        scores = load_player_scores(fpath)
        stats = player_stats(scores)
        if stats is None:
            continue
        stats['slug'] = slug
        rows.append(stats)

    if not rows:
        print("Nessun giocatore con score validi in cache.")
        return

    print(f"Ruolo: {RUOLO} | Giocatori analizzati: {len(rows)} "
          f"(cache di calibrazione, campione allargato)\n")

    # --- Distribuzione generale ---
    n_games_list = [r['n_games'] for r in rows]
    top2_list = [r['top2_share'] for r in rows]
    cv_list = [r['cv'] for r in rows]
    print("=== DISTRIBUZIONE GENERALE ===")
    print(f"n_games:    media {statistics.mean(n_games_list):.1f}, "
          f"mediana {statistics.median(n_games_list):.1f}, "
          f"min {min(n_games_list)}, max {max(n_games_list)}")
    print(f"top2_share: media {statistics.mean(top2_list)*100:.1f}%, "
          f"mediana {statistics.median(top2_list)*100:.1f}%, "
          f"max {max(top2_list)*100:.1f}%")
    print(f"coeff. variazione (std/media): media {statistics.mean(cv_list)*100:.1f}%, "
          f"mediana {statistics.median(cv_list)*100:.1f}%")

    # --- Correlazione n_games vs top2_share (attesa: negativa -- meno
    # presenze, piu' la media dipende dai picchi) ---
    if len(rows) > 2:
        try:
            corr = statistics.correlation(n_games_list, top2_list)
            print(f"\nCorrelazione n_games <-> top2_share: {corr:.3f} "
                  f"(negativa attesa: meno presenze = media piu' trainata dai picchi)")
        except statistics.StatisticsError:
            pass

    # --- Pattern "Antino Lopez": poche presenze + media trainata dai picchi ---
    at_risk = [r for r in rows if r['n_games'] < MIN_GAMES_LOW and r['top2_share'] >= TOP2_SHARE_HIGH]
    at_risk.sort(key=lambda r: -r['top2_share'])
    print(f"\n=== GIOCATORI 'AD ALTO RISCHIO OUTLIER' "
          f"(n_games < {MIN_GAMES_LOW} E top2_share >= {TOP2_SHARE_HIGH:.0%}) ===")
    print(f"Totale: {len(at_risk)} / {len(rows)} ({len(at_risk)/len(rows)*100:.1f}% del pool)\n")
    for r in at_risk[:20]:
        print(f"{r['slug']:35s} n_games={r['n_games']:3d}  media={r['mean']:5.1f}  "
              f"top2_share={r['top2_share']*100:5.1f}%  best={r['best_score']:5.1f}  worst={r['worst_score']:5.1f}")
    if len(at_risk) > 20:
        print(f"... e altri {len(at_risk) - 20}")

    # --- Controparte: alta affidabilita' (molte presenze, poco dipendenti dai picchi) ---
    reliable = [r for r in rows if r['n_games'] >= MIN_GAMES_LOW and r['top2_share'] < TOP2_SHARE_HIGH]
    print(f"\n=== GIOCATORI 'AFFIDABILI' (n_games >= {MIN_GAMES_LOW} E top2_share < {TOP2_SHARE_HIGH:.0%}) ===")
    print(f"Totale: {len(reliable)} / {len(rows)} ({len(reliable)/len(rows)*100:.1f}% del pool)")

    # --- Top 10 per top2_share assoluto, indipendentemente da n_games (per vedere se
    # capita anche a giocatori con tante presenze, non solo a chi ne ha poche) ---
    by_top2 = sorted(rows, key=lambda r: -r['top2_share'])[:10]
    print(f"\n=== TOP 10 PER top2_share (a prescindere da n_games) ===")
    for r in by_top2:
        flag = " <-- pochi n_games" if r['n_games'] < MIN_GAMES_LOW else ""
        print(f"{r['slug']:35s} n_games={r['n_games']:3d}  media={r['mean']:5.1f}  "
              f"top2_share={r['top2_share']*100:5.1f}%{flag}")


if __name__ == '__main__':
    main()
