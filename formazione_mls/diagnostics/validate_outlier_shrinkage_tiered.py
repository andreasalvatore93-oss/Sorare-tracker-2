"""
Validate Outlier Shrinkage TIERED per titolarita' (26/07, quinta sessione)

Variante di validate_outlier_shrinkage.py: la baseline (prior unico = media
grezza dell'intero pool di ruolo) migliora il MAE per FWD, e' rumore per MID
e per DEF -- il ruolo con piu' casi outlier (19.7% del pool, vedi
inspect_outlier_reliability.py) -- il guadagno finisce sul segmento sbagliato
(n>=8, non sui casi a rischio n<8 che avevano motivato il problema).

Ipotesi da verificare: il prior unico e' troppo grezzo perche' mischia
titolari e riserve strutturali, che hanno livelli di score tipicamente
diversi -- "tirare" un giocatore verso la media di TUTTI (titolari+riserve
insieme) e' impreciso. Qui si condiziona il prior sulla fascia di titolarita'
del giocatore, usando un segnale gia' presente nelle stesse cache di
calibrazione (NESSUNA nuova query API): il campo `mins_played`
(category GENERAL) dentro `detailedScore` di ogni partita.

Costruzione del prior condizionato (NO lookahead):
1. Fascia di titolarita' di UN giocatore ad UN dato punto di test i e'
   assegnata usando SOLO la media dei minuti giocati nelle sue partite
   storiche fino a i (scores[:i], stesso principio no-lookahead del resto
   del backtest) -- MAI l'intera storia futura del giocatore.
2. I punti di cutoff (soglie in minuti) che separano le fasce sono invece
   una costante STRUTTURALE del pool di ruolo, analoga a media_ruolo nello
   script originale: calcolati UNA VOLTA SOLA sulla distribuzione dei minuti
   medi "a fine carriera" (tutte le partite in cache) di tutti i giocatori
   del pool, con >=9 partite (stessa soglia MIN_HISTORY+3 usata per il pool).
   Non sono "lookahead sul giocatore di test" nello stesso senso in cui non
   lo era media_ruolo: sono un parametro strutturale del pool, stimato una
   volta, non un dato che varia nel loop walk-forward.
3. Il prior per la fascia T e' la media grezza (non pesata) di TUTTI gli
   score del pool che appartengono a partite classificate in quella fascia.
   La classificazione di OGNI partita (non solo dei punti di test) usa la
   media minuti del GIOCATORE calcolata sulle SUE partite precedenti (stesso
   principio walk-forward del punto 1) -- quindi anche il prior per fascia,
   pur essendo una costante strutturale calcolata una volta sola sull'intero
   pool (stessa semplificazione accettata per media_ruolo nello script
   originale), e' costruito da classificazioni individuali che non guardano
   mai al futuro del singolo giocatore.

Numero di fasce: 3 (terzili globali sulla distribuzione dei minuti medi a
fine carriera) per il ruolo DEF -- la distribuzione osservata (85 giocatori
con >=9 partite, range minuti medi 64-92) si divide in modo abbastanza
regolare in tre gruppi di ~28-29 giocatori ciascuno (soglie ~85.8 e ~89.0
minuti); 2 fasce sarebbero state troppo grossolane data la scarsa dispersione
(quasi tutto il pool e' fra 80 e 92 minuti medi), 3 fasce permettono comunque
di isolare i casi limite (rotazione pura, minuti bassi) senza svuotare i
gruppi.

Stessa griglia di k, stesso MIN_HISTORY, stesso split n<8 vs n>=8 dello
script originale -- eseguito SOLO per DEF (gli altri ruoli gia' testati),
con un controllo rapido opzionale su MID.

NESSUNA nuova query API: solo le cache di calibrazione gia' su disco.
Nessuna modifica ai file di produzione (test_<ruolo>.py) -- SOLO diagnostica.

Uso: python formazione_mls/diagnostics/validate_outlier_shrinkage_tiered.py
"""
import os
import sys
import json
import glob
import statistics
import importlib
import datetime
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
MIN_GAMES_LOW = 8  # stessa soglia "poche presenze" di inspect_outlier_reliability.py
MIN_GAMES_POOL = MIN_HISTORY + 3  # stessa soglia usata per costruire il pool
N_TIERS = 3  # terzili globali dei minuti medi a fine carriera

ROLES = ('def', 'mid')  # DEF principale, MID come controllo rapido opzionale

MODULE_BY_ROLE = {
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
}

K_GRID = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30]


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def extract_mins_played(entry):
    """Legge mins_played (category GENERAL) da detailedScore di una partita.
    Ritorna None se assente (gestito a valle con fallback)."""
    for st in entry.get('detailedScore') or []:
        if st.get('stat') == 'mins_played':
            v = st.get('statValue')
            return float(v) if v is not None else None
    return None


def load_role_pool(ruolo):
    """Come validate_outlier_shrinkage.py, ma cattura in piu' i minuti
    giocati (mins_played) per ogni partita, allineati a scores/is_home_flags
    nello stesso ordine cronologico."""
    cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    players = []

    for fpath in files:
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('score') is not None
                   and e.get('scoreStatus') == 'FINAL']
        if len(entries) < MIN_GAMES_POOL:
            continue

        team_counts = defaultdict(int)
        for e in entries:
            g = e['anyGame']
            for side in ('homeTeam', 'awayTeam'):
                slug = (g.get(side) or {}).get('slug')
                if slug:
                    team_counts[slug] += 1
        team_slug = max(team_counts, key=team_counts.get) if team_counts else None
        if not team_slug:
            continue

        rows = []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            dt = parse_date(g)
            if dt is None:
                continue
            mins = extract_mins_played(e)
            rows.append((dt, float(e['score']), is_home, mins))
        rows.sort(key=lambda r: r[0])
        if len(rows) < MIN_GAMES_POOL:
            continue

        scores = [r[1] for r in rows]
        is_home_flags = [r[2] for r in rows]
        mins_list = [r[3] for r in rows]
        players.append({'scores': scores, 'is_home_flags': is_home_flags, 'mins': mins_list})

    return players


def compute_tier_cutoffs(players, n_tiers):
    """Costante strutturale (calcolata una volta sola, come media_ruolo
    nello script originale): terzili (o quantili per n_tiers) della media
    minuti "a fine carriera" (tutte le partite in cache) di ogni giocatore
    del pool con storico sufficiente. Ritorna la lista di cutoff (n_tiers-1
    soglie) in minuti."""
    avgs = []
    for p in players:
        valid_mins = [m for m in p['mins'] if m is not None]
        if valid_mins:
            avgs.append(statistics.mean(valid_mins))
    avgs.sort()
    n = len(avgs)
    cutoffs = []
    for t in range(1, n_tiers):
        q = t / n_tiers
        idx = min(int(q * n), n - 1)
        cutoffs.append(avgs[idx])
    return cutoffs


def assign_tier(avg_mins, cutoffs):
    """Assegna la fascia (0 = minuti piu' bassi/riserva ... n_tiers-1 =
    minuti piu' alti/titolare) dato un valore di minuti medi e i cutoff
    strutturali. Se avg_mins e' None (nessun dato minuti disponibile fino a
    quel punto), ritorna la fascia centrale come fallback neutro."""
    if avg_mins is None:
        return len(cutoffs) // 2
    tier = 0
    for c in cutoffs:
        if avg_mins >= c:
            tier += 1
        else:
            break
    return tier


def running_avg_mins(mins_hist):
    """Media dei minuti giocati sulle partite storiche disponibili fino al
    punto di test (no lookahead). Ignora i valori None. None se non c'e'
    nessun dato utile."""
    valid = [m for m in mins_hist if m is not None]
    if not valid:
        return None
    return statistics.mean(valid)


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    TREND_INTENSITY = mod.TREND_INTENSITY

    players = load_role_pool(ruolo)
    if not players:
        print(f"\n=== {ruolo.upper()}: nessun dato utilizzabile ===")
        return

    n_players_used = len(players)

    # --- Cutoff strutturali di titolarita' (costante, calcolata una volta) ---
    cutoffs = compute_tier_cutoffs(players, N_TIERS)
    print(f"\n=== {ruolo.upper()} ({n_players_used} giocatori) ===")
    print(f"  Cutoff fasce titolarita' (minuti medi, {N_TIERS} fasce): "
          f"{', '.join(f'{c:.1f}' for c in cutoffs)}")

    # --- Prior condizionato per fascia: classifica OGNI partita del pool
    # usando la media minuti del GIOCATORE sulle partite PRECEDENTI (no
    # lookahead sul singolo giocatore), poi media grezza degli score per
    # fascia. Calcolato una volta sola sull'intero pool (stessa
    # semplificazione strutturale di media_ruolo nello script originale). ---
    scores_by_tier = defaultdict(list)
    n_players_by_tier_final = defaultdict(int)  # solo per il report finale (fascia "di carriera")

    for p in players:
        scores = p['scores']
        mins_list = p['mins']
        n_tot = len(scores)
        for j in range(1, n_tot):  # j=0 scartato: nessuno storico per classificarlo
            avg_mins_hist = running_avg_mins(mins_list[:j])
            tier = assign_tier(avg_mins_hist, cutoffs)
            scores_by_tier[tier].append(scores[j])
        # fascia "di carriera" (tutta la storia) solo per il report descrittivo
        avg_mins_full = running_avg_mins(mins_list)
        n_players_by_tier_final[assign_tier(avg_mins_full, cutoffs)] += 1

    media_by_tier = {t: statistics.mean(v) for t, v in scores_by_tier.items() if v}
    print("  Prior per fascia (media grezza score, n giocatori 'di carriera' in fascia):")
    for t in range(N_TIERS):
        n_p = n_players_by_tier_final.get(t, 0)
        n_s = len(scores_by_tier.get(t, []))
        media = media_by_tier.get(t)
        media_str = f"{media:.2f}" if media is not None else "N/A"
        label = ['riserva/rotazione', 'intermedia', 'titolare'][t] if N_TIERS == 3 else str(t)
        print(f"    fascia {t} ({label}): prior={media_str}  ({n_s} score nel pool, {n_p} giocatori 'di carriera')")

    # Fallback globale (media di ruolo, come nello script originale) per il
    # raro caso in cui una fascia risultasse vuota nel prior per-fascia.
    media_ruolo_globale = statistics.mean(s for p in players for s in p['scores'])

    # --- Punti di test walk-forward (come script originale, + fascia locale) ---
    test_points = []
    for p in players:
        scores = p['scores']
        is_home_flags = p['is_home_flags']
        mins_list = p['mins']
        n_tot = len(scores)

        for i in range(MIN_HISTORY, n_tot):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            n = len(hist_scores)

            weights = exponential_weights(n, HALF_LIFE_GAMES)
            media = weighted_mean(hist_scores, weights)
            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

            avg_mins_hist = running_avg_mins(mins_list[:i])
            tier = assign_tier(avg_mins_hist, cutoffs)
            prior_tier = media_by_tier.get(tier, media_ruolo_globale)

            reale = scores[i]
            test_points.append((reale, media, fattore_ct, fattore_trend, n, prior_tier))

    n_test_points = len(test_points)
    print(f"\n  {n_test_points} punti di test walk-forward")

    n_low = sum(1 for *_, n, _ in test_points if n < MIN_GAMES_LOW)
    n_high = n_test_points - n_low
    print(f"  Segmento n<{MIN_GAMES_LOW}: {n_low} punti di test | n>={MIN_GAMES_LOW}: {n_high} punti di test")

    mae_baseline = mae_baseline_low = mae_baseline_high = None
    best_k, best_mae = None, None
    best_k_low, best_mae_low = None, None
    risultati = []

    for k in K_GRID:
        errori, errori_low, errori_high = [], [], []
        for reale, media, fattore_ct, fattore_trend, n, prior_tier in test_points:
            if k == 0:
                media_corretta = media
            else:
                media_corretta = (n / (n + k)) * media + (k / (n + k)) * prior_tier
            pred = media_corretta * fattore_ct * fattore_trend
            errore = abs(reale - pred)
            errori.append(errore)
            if n < MIN_GAMES_LOW:
                errori_low.append(errore)
            else:
                errori_high.append(errore)

        mae = statistics.mean(errori)
        mae_low = statistics.mean(errori_low) if errori_low else None
        mae_high = statistics.mean(errori_high) if errori_high else None

        if k == 0:
            mae_baseline, mae_baseline_low, mae_baseline_high = mae, mae_low, mae_high

        risultati.append((k, mae, mae_low, mae_high))

        if best_mae is None or mae < best_mae:
            best_k, best_mae = k, mae
        if mae_low is not None and (best_mae_low is None or mae_low < best_mae_low):
            best_k_low, best_mae_low = k, mae_low

    print(f"\n  {'k':>4s}  {'MAE tot':>8s}  {'var%':>7s}  {'MAE n<8':>8s}  {'var%':>7s}  {'MAE n>=8':>9s}  {'var%':>7s}")
    for k, mae, mae_low, mae_high in risultati:
        pct = (mae - mae_baseline) / mae_baseline * 100
        pct_low = (mae_low - mae_baseline_low) / mae_baseline_low * 100 if mae_low is not None and mae_baseline_low else 0.0
        pct_high = (mae_high - mae_baseline_high) / mae_baseline_high * 100 if mae_high is not None and mae_baseline_high else 0.0
        flag = " <== MIGLIORE (tot)" if k == best_k else ""
        print(f"  {k:4d}  {mae:8.3f}  {pct:+6.2f}%  {mae_low:8.3f}  {pct_low:+6.2f}%  {mae_high:9.3f}  {pct_high:+6.2f}%{flag}")

    pct_best = (best_mae - mae_baseline) / mae_baseline * 100
    print(f"\n  MIGLIOR k (MAE totale): {best_k} (MAE={best_mae:.3f}, {pct_best:+.2f}% vs baseline k=0)")
    if best_k_low is not None:
        pct_best_low = (best_mae_low - mae_baseline_low) / mae_baseline_low * 100 if mae_baseline_low else 0.0
        print(f"  MIGLIOR k (solo segmento n<{MIN_GAMES_LOW}): {best_k_low} (MAE={best_mae_low:.3f}, {pct_best_low:+.2f}% vs baseline)")

    mae_high_at_best_k = next(mh for k, _, _, mh in risultati if k == best_k)
    if mae_baseline_high and mae_high_at_best_k is not None:
        pct_high_at_best = (mae_high_at_best_k - mae_baseline_high) / mae_baseline_high * 100
        if pct_high_at_best > 0.5:
            print(f"  ATTENZIONE: al k={best_k} il segmento n>={MIN_GAMES_LOW} peggiora di "
                  f"{pct_high_at_best:+.2f}% -- lo shrinkage potrebbe essere troppo aggressivo "
                  f"o il k scelto sbagliato per questo ruolo.")

    return best_k, best_mae, mae_baseline


def main():
    for ruolo in ROLES:
        run_role(ruolo)


if __name__ == '__main__':
    main()
