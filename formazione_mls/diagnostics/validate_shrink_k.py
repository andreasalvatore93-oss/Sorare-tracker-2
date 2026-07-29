"""
Validate Shrink_K post-retuning half_life/trend (29/07, quarta sessione)

Le costanti SHRINK_K_OUTLIER_{GK,DEF,MID,FWD} (shrinkage Empirical Bayes
verso il prior di ruolo, corretto = (n/(n+K))*grezzo + (K/(n+K))*prior)
sono state fissate PRIMA del retuning di oggi di HALF_LIFE_GAMES/
TREND_INTENSITY per DEF/MID/FWD (vedi test_def.py/test_mid.py/
test_mls_fwd_all.py, commenti "AGGIORNATO 29/07"). Con media pesata e
trend diversi, il valore ottimale di K potrebbe essere cambiato.

Metodologia: stesso walk-forward di validate_halflife_venue.py (MIN_HISTORY,
exponential_weights/weighted_mean, TUTTE le leghe via glob), ma qui il
"pred" e' la media pesata grezza CORRETTA per shrinkage verso il prior di
ruolo (senza fattore venue/trend, per isolare l'effetto di K -- lo shrinkage
in produzione si applica al "grezzo_nuovo" gia' post trend/venue, ma qui
testiamo K in isolamento sullo stesso principio, coerente con l'approccio
usato per half_life che isolava un solo parametro alla volta).

half_life e trend_intensity sono importati dai moduli di produzione (NON
hardcodati) cosi' il test riflette i valori AGGIORNATI di oggi.

Uso: python formazione_mls/diagnostics/validate_shrink_k.py
"""
import os
import sys
import json
import glob
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

# Grid base [2,3,5,7,10,15,20,30] esteso per includere i valori attuali
# (GK=5.0, DEF=15.0, MID=10.0, FWD=5.0 sono gia' dentro il range base) e i
# loro vicini, piu' un'estensione verso l'alto per verificare convergenza
# asintotica se il minimo cade sul bordo superiore, e verso il basso (1.0)
# per vedere se il minimo e' monotono verso 0 (segnale di rischio overfitting
# su storici corti, da segnalare non da applicare ciecamente).
SHRINK_K_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0,
                 12.0, 15.0, 18.0, 20.0, 25.0, 30.0, 40.0, 50.0, 70.0, 100.0]


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_players(ruolo):
    """TUTTE le leghe (regola esplicita utente 29/07: ogni test va fatto su
    tutte le leghe disponibili, non solo MLS/Korea)."""
    patterns = [f'formazione_*/output/*_{ruolo}_calibration/.cache',
                f'formazione_*/output/*_{ruolo}_all/.cache']
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
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if len(entries) < MIN_HISTORY + 3:
            continue
        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue
        scores, is_home_flags = [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            scores.append(e.get('score') or 0.0)
            is_home_flags.append(is_home)
        if len(scores) < MIN_HISTORY + 3:
            continue
        players.append({'scores': scores, 'is_home_flags': is_home_flags})
    return players


def mae_for_shrink_k(players, exponential_weights, weighted_mean, half_life,
                      shrink_k, media_ruolo_prior):
    errori = []
    for p in players:
        scores = p['scores']
        n_tot = len(scores)
        for i in range(MIN_HISTORY, n_tot):
            hist_scores = scores[:i]
            weights = exponential_weights(i, half_life)
            media = weighted_mean(hist_scores, weights)
            n = len(hist_scores)
            corretto = (n / (n + shrink_k)) * media + (shrink_k / (n + shrink_k)) * media_ruolo_prior
            errori.append(scores[i] - corretto)
    return statistics.mean(abs(e) for e in errori), len(errori)


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    shrink_k_attr = f'SHRINK_K_OUTLIER_{ruolo.upper()}'
    prior_attr = f'MEDIA_RUOLO_{ruolo.upper()}_PRIOR'
    SHRINK_K_ATTUALE = getattr(mod, shrink_k_attr)
    MEDIA_RUOLO_PRIOR = getattr(mod, prior_attr)

    players = load_players(ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return None

    print(f"\n{'='*78}\n{ruolo.upper()} ({len(players)} giocatori) -- "
          f"half_life={HALF_LIFE_GAMES}, shrink_k attuale={SHRINK_K_ATTUALE}, "
          f"prior={MEDIA_RUOLO_PRIOR}\n{'='*78}")

    grid = sorted(set(SHRINK_K_GRID + [SHRINK_K_ATTUALE]))

    mae_attuale, n = mae_for_shrink_k(players, exponential_weights, weighted_mean,
                                       HALF_LIFE_GAMES, SHRINK_K_ATTUALE, MEDIA_RUOLO_PRIOR)
    print(f"  shrink_k attuale={SHRINK_K_ATTUALE}: MAE={mae_attuale:.4f} ({n} punti test)")

    print(f"\n  Grid shrink_k:")
    best_k, best_mae = None, None
    results = []
    for k in grid:
        mae, _ = mae_for_shrink_k(players, exponential_weights, weighted_mean,
                                   HALF_LIFE_GAMES, k, MEDIA_RUOLO_PRIOR)
        results.append((k, mae))
        flag = " <== ATTUALE" if k == SHRINK_K_ATTUALE else ""
        best_flag = ""
        if best_mae is None or mae < best_mae:
            best_k, best_mae = k, mae
            best_flag = " <== MIGLIORE FINORA"
        pct = (mae - mae_attuale) / mae_attuale * 100
        print(f"    shrink_k={k:6.1f}  MAE={mae:.4f}  ({pct:+.3f}% vs attuale){flag}{best_flag}")

    pct_best = (best_mae - mae_attuale) / mae_attuale * 100
    print(f"\n  MIGLIOR shrink_k: {best_k} (MAE={best_mae:.4f}, {pct_best:+.3f}% vs attuale={SHRINK_K_ATTUALE})")

    # Verifica se il minimo e' sul bordo (monotono) del grid testato
    ks_sorted = [k for k, _ in sorted(results)]
    if best_k == ks_sorted[0]:
        print(f"  ATTENZIONE: minimo sul BORDO INFERIORE del grid ({best_k}) -- "
              f"possibile convergenza monotona verso K piccoli/zero, rischio "
              f"overfitting su storici corti/rumorosi. Verificare andamento vicino a K=1.")
    elif best_k == ks_sorted[-1]:
        print(f"  ATTENZIONE: minimo sul BORDO SUPERIORE del grid ({best_k}) -- "
              f"possibile convergenza asintotica verso shrinkage forte/nessuna "
              f"fiducia nello storico individuale, andrebbe esteso oltre {best_k}.")

    return {
        'ruolo': ruolo,
        'attuale': SHRINK_K_ATTUALE,
        'mae_attuale': mae_attuale,
        'migliore': best_k,
        'mae_migliore': best_mae,
        'pct': pct_best,
        'bordo_inf': best_k == ks_sorted[0],
        'bordo_sup': best_k == ks_sorted[-1],
    }


def main():
    summary = []
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        r = run_role(ruolo)
        if r:
            summary.append(r)

    print(f"\n{'='*78}\nRIEPILOGO\n{'='*78}")
    for r in summary:
        print(f"  {r['ruolo'].upper()}: attuale K={r['attuale']} (MAE={r['mae_attuale']:.4f}) "
              f"-> migliore K={r['migliore']} (MAE={r['mae_migliore']:.4f}, {r['pct']:+.3f}%)"
              f"{'  [BORDO INF]' if r['bordo_inf'] else ''}{'  [BORDO SUP]' if r['bordo_sup'] else ''}")


if __name__ == '__main__':
    main()
