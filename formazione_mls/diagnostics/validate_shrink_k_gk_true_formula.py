"""
Verifica shrink_K per GK con la formula VERA di produzione (29/07, sessione
di controllo). Un agente precedente ha testato una grid 2D (half_life,
shrink_K) usando una formula SEMPLIFICATA (shrinkage della sola media pesata
esponenziale verso un prior STATICO) diversa da quella reale usata in
produzione (compute_score_atteso_gk in formazione_mls/predict/test_gk.py),
che invece:
  1. calcola level_score_atteso da expected_level_from_rates(lambda_pos_dec,
     lambda_neg_dec) (tasso di eventi decisivi, non media grezza dello score),
  2. aggiunge il pezzo granulare (score - level_score) pesato per un fattore
     di trend,
  3. applica lo shrinkage empirico-bayes SUL TOTALE (level+granulare) verso
     un prior che in PRODUZIONE LIVE e' dinamico (funzione della presence_rate
     del giocatore) ma che nel backtest/calibrazione -- per esplicita scelta
     gia' presente nel codice di produzione, vedi commento in
     compute_score_atteso_gk: "presence_rate=None (calibrazione/backtest,
     nessun concetto di storico totale esaminato disponibile) ricade sul
     prior fisso originale" -- resta il prior STATICO MEDIA_RUOLO_GK_PRIOR
     (48.81), perche' la cache diagnostica non conserva le partite
     DID_NOT_PLAY/sotto soglia minutaggio necessarie per calcolare un vero
     presence_rate storico.
  4. applica infine il fattore casa/trasferta con shrinkage separato
     (SPLIT_SHRINK_K_GK, invariato, non e' l'oggetto di questo test).

Questo script replica ESATTAMENTE questa formula (chiamando direttamente
compute_score_atteso_gk di test_gk.py, non una riscrittura) in un backtest
walk-forward su TUTTE le leghe disponibili (stessa fonte dati/struttura di
validate_halflife_venue.py), con half_life=6.0 FISSO (gia' deciso il 29/07,
non e' oggetto di questo test) e una grid su shrink_k in
[3, 5, 7, 10, 15, 20, 30, 50] (5.0 e' l'attuale SHRINK_K_OUTLIER_GK).

Calcola il MAE aggregato su tutti i portieri E separatamente sul sottogruppo
dei portieri a piu' alta varianza storica (i piu' a rischio di "bug Daniel").

Uso: python formazione_mls/diagnostics/validate_shrink_k_gk_true_formula.py
"""
import os
import sys
import json
import glob
import statistics
import importlib

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
HALF_LIFE_FIXED = 6.0
SHRINK_K_GRID = [3, 5, 7, 10, 15, 20, 30, 50]
N_HIGH_VARIANCE = 15  # dimensione del sottogruppo "tipo Daniel" (10-20 richiesti)

mod = importlib.import_module('formazione_mls.predict.test_gk')
exponential_weights = mod.exponential_weights
weighted_mean = mod.weighted_mean
weighted_stddev = mod.weighted_stddev
compute_score_atteso_gk = mod.compute_score_atteso_gk
extract_level_score = mod.extract_level_score
extract_decisive_rates = mod.extract_decisive_rates
SHRINK_K_OUTLIER_GK_ATTUALE = mod.SHRINK_K_OUTLIER_GK
MEDIA_RUOLO_GK_PRIOR = mod.MEDIA_RUOLO_GK_PRIOR
TREND_INTENSITY = mod.TREND_INTENSITY


def player_team_slug(games):
    from collections import defaultdict
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_gk_players():
    """Carica lo storico GK da tutte le leghe disponibili (cache diagnostica
    *_detail_cache.json, gia' popolata dai run reali), ricavando per ogni
    partita utilizzabile: score, is_home, granulare (score - level_score),
    pos_decisive/neg_decisive (dagli eventi DECISIVE_STAT nel detailedScore
    cachato) -- esattamente gli input richiesti da compute_score_atteso_gk."""
    patterns = ['formazione_*/output/*_gk_calibration/.cache',
                'formazione_*/output/*_gk_all/.cache']
    files = []
    seen = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath not in seen:
                    seen.add(fpath)
                    files.append(fpath)

    players = []
    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if len(entries) < MIN_HISTORY + 3:
            continue

        # ordina cronologicamente (dal piu' vecchio al piu' recente) sulla data
        def _date_key(e):
            return (e.get('anyGame') or {}).get('date') or ''
        entries.sort(key=_date_key)

        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue

        scores, is_home_flags = [], []
        granulari_values, pos_decisive_values, neg_decisive_values = [], [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            score = e.get('score') or 0.0
            level_score = extract_level_score(e)
            pos_dec, neg_dec = extract_decisive_rates(e)
            scores.append(score)
            is_home_flags.append(is_home)
            granulari_values.append(score - level_score)
            pos_decisive_values.append(pos_dec)
            neg_decisive_values.append(neg_dec)

        if len(scores) < MIN_HISTORY + 3:
            continue
        players.append({
            'file': fpath,
            'scores': scores,
            'is_home_flags': is_home_flags,
            'granulari_values': granulari_values,
            'pos_decisive_values': pos_decisive_values,
            'neg_decisive_values': neg_decisive_values,
        })
    return players


def rigorous_backtest_true_formula(player, half_life, shrink_k):
    """Backtest walk-forward che richiama LA STESSA FUNZIONE DI PRODUZIONE
    (compute_score_atteso_gk), variando solo shrink_k. presence_rate=None
    (fallback al prior statico), esattamente come fa gia'
    rigorous_backtest_prod_gk in produzione per calibrazione/backtest."""
    scores = player['scores']
    is_home_flags = player['is_home_flags']
    granulari_values = player['granulari_values']
    pos_decisive_values = player['pos_decisive_values']
    neg_decisive_values = player['neg_decisive_values']
    n = len(scores)
    errori = []
    for i in range(MIN_HISTORY, n):
        predetto = compute_score_atteso_gk(
            scores[:i], is_home_flags[:i], granulari_values[:i],
            pos_decisive_values[:i], neg_decisive_values[:i],
            target_is_home=is_home_flags[i], p_gioca=1.0,
            half_life=half_life, trend_intensity=TREND_INTENSITY,
            shrink_k=shrink_k, media_ruolo_prior=MEDIA_RUOLO_GK_PRIOR,
            presence_rate=None)
        reale = scores[i]
        errori.append(abs(reale - predetto))
    return errori


def main():
    print("Caricamento storico GK (tutte le leghe disponibili, cache diagnostica reale)...")
    players = load_gk_players()
    print(f"Portieri utilizzabili: {len(players)}")
    if not players:
        print("Nessun dato disponibile, interrompo.")
        return

    # Sottogruppo alta varianza: dev std pesata (half_life fisso=6.0) sull'INTERO
    # storico disponibile di ciascun portiere (stessa metrica di "instabilita'"
    # usata concettualmente per il caso Daniel De Sousa Brito).
    for p in players:
        w = exponential_weights(len(p['scores']), HALF_LIFE_FIXED)
        m = weighted_mean(p['scores'], w)
        p['dev_std'] = weighted_stddev(p['scores'], w, m)

    players_sorted = sorted(players, key=lambda p: p['dev_std'], reverse=True)
    high_var_players = players_sorted[:N_HIGH_VARIANCE]
    print(f"\nSottogruppo alta varianza (top {N_HIGH_VARIANCE} per dev_std pesata):")
    for p in high_var_players:
        name = os.path.basename(p['file']).replace('_detail_cache.json', '')
        print(f"  {name:45s} dev_std={p['dev_std']:.2f}  n_partite={len(p['scores'])}")

    print(f"\nGrid shrink_k (half_life={HALF_LIFE_FIXED} fisso, attuale shrink_k="
          f"{SHRINK_K_OUTLIER_GK_ATTUALE}):\n")
    header = f"{'shrink_k':>10} | {'MAE aggregato':>14} | {'MAE alta varianza':>18} | note"
    print(header)
    print('-' * len(header))

    results = []
    for shrink_k in SHRINK_K_GRID:
        errori_tutti = []
        errori_alta_var = []
        for p in players:
            errori = rigorous_backtest_true_formula(p, HALF_LIFE_FIXED, shrink_k)
            errori_tutti.extend(errori)
            if p in high_var_players:
                errori_alta_var.extend(errori)
        mae_tutti = statistics.mean(errori_tutti) if errori_tutti else None
        mae_alta_var = statistics.mean(errori_alta_var) if errori_alta_var else None
        flag = " <== ATTUALE" if shrink_k == SHRINK_K_OUTLIER_GK_ATTUALE else ""
        results.append({'shrink_k': shrink_k, 'mae_tutti': mae_tutti, 'mae_alta_var': mae_alta_var})
        print(f"{shrink_k:>10} | {mae_tutti:>14.3f} | {mae_alta_var:>18.3f} |{flag}")

    baseline = next(r for r in results if r['shrink_k'] == SHRINK_K_OUTLIER_GK_ATTUALE)
    print(f"\nBaseline (shrink_k={SHRINK_K_OUTLIER_GK_ATTUALE}): "
          f"MAE aggregato={baseline['mae_tutti']:.3f}, MAE alta varianza={baseline['mae_alta_var']:.3f}\n")

    print(f"{'shrink_k':>10} | {'var. MAE aggregato':>20} | {'var. MAE alta varianza':>24}")
    for r in results:
        d_tutti = (r['mae_tutti'] - baseline['mae_tutti']) / baseline['mae_tutti'] * 100
        d_hv = (r['mae_alta_var'] - baseline['mae_alta_var']) / baseline['mae_alta_var'] * 100
        print(f"{r['shrink_k']:>10} | {d_tutti:>+19.2f}% | {d_hv:>+23.2f}%")

    best_overall = min(results, key=lambda r: r['mae_tutti'])
    best_hv = min(results, key=lambda r: r['mae_alta_var'])
    print(f"\nMigliore per MAE aggregato: shrink_k={best_overall['shrink_k']} (MAE={best_overall['mae_tutti']:.3f})")
    print(f"Migliore per MAE alta varianza: shrink_k={best_hv['shrink_k']} (MAE={best_hv['mae_alta_var']:.3f})")


if __name__ == '__main__':
    main()
