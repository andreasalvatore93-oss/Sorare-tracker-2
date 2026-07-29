"""
Validate Outlier Shrinkage (26/07, quarta sessione)

Backtest walk-forward rigoroso per rispondere alla domanda del backlog
"outlier/hot-streak": applicare uno SHRINKAGE (Empirical Bayes / James-Stein)
alla media pesata esponenziale del giocatore -- tirandola verso la media
"di ruolo" in proporzione inversa al numero di partite storiche disponibili
-- riduce il MAE reale, in particolare per i giocatori a basso storico?

Motivazione (26/07, discussione con l'utente, dopo
formazione_mls/diagnostics/inspect_outlier_reliability.py): un giocatore con
poche presenze storiche e 1-2 punteggi isolati molto alti (caso reale
Antino Lopez, DEF: 25% presenze, picchi 86/81) puo' risultare sovrastimato
dalla media pesata rispetto a un giocatore con presenze costanti e media
stabile (caso Carles Gil, MID). La diagnostica ha misurato il fenomeno come
reale e non trascurabile (19.7% DEF, 24.1% GK, 16.9% FWD, 7.1% MID del pool
con "poche presenze (<8 partite in cache) E media fortemente trainata dalle
2 partite migliori (>=18% del valore medio)"), ma con correlazione DEBOLE o
nulla tra n_games e quanto la media dipende dai picchi -- quindi non e' un
continuo pulito, sono due segnali abbastanza indipendenti. Da qui l'idea di
uno shrinkage esplicito verso una media di riferimento, calibrato su un
parametro k (pseudo-count) invece di una regola ad-hoc sui picchi.

Formula testata:
    media_corretta = (n / (n + k)) * media_pesata_giocatore
                      + (k / (n + k)) * media_ruolo
dove n = numero di partite storiche disponibili al punto di test (lo stesso
n usato oggi in min_history/lunghezza storico nel backtest) e k e' il
pseudo-count di shrinkage, testato su una griglia. k=0 equivale alla
baseline attuale (nessuno shrinkage, comportamento invariato).

"media_ruolo" (il prior strutturale): media semplice (non pesata) di TUTTI
gli score storici di TUTTI i giocatori del ruolo raccolti nel pool di
calibrazione, calcolata UNA VOLTA SOLA all'inizio sull'intero dataset
disponibile -- NON per-partita, NON ricalcolata nel loop walk-forward.
Questa e' un'approssimazione volutamente semplificata (non e' "vero" prior
temporale che cresce partita per partita): rappresenta il valore "normale"
del ruolo nel campione di calibrazione attuale, non introduce lookahead
sul GIOCATORE di test (il suo score futuro scores[i] non entra mai nel
calcolo della sua stessa predizione), ma il prior stesso e' calcolato sul
pool intero (inclusi score "futuri" di altri giocatori/di quello stesso
giocatore oltre i). Documentato esplicitamente qui perche' e' una scelta
di semplificazione accettata: il prior di ruolo e' una costante strutturale
lenta da stimare, non un dato che varia nel tempo in questo esperimento.

Lo shrinkage si applica SOLO al pezzo "media storica pesata" -- il resto
della formula (fattore_casa_trasferta, fattore_trend) resta IDENTICO a
oggi e viene applicato DOPO, moltiplicando la media corretta:
    pred = media_corretta * fattore_ct * fattore_trend
(fattore_forza_avversario e' gia' stato rimosso in produzione per tutti i
ruoli, vedi validate_team_defense_strength.py -- non reintrodotto qui).

Oltre al MAE aggregato, lo script segmenta i punti di test in n < 8 (i casi
"a rischio" identificati da inspect_outlier_reliability.py) vs n >= 8, per
verificare l'ipotesi che lo shrinkage aiuti soprattutto (o solo) il
sottogruppo a basso n, senza peggiorare quello con molte presenze.

NESSUNA nuova query API: solo le cache di calibrazione gia' su disco.
Nessuna modifica ai file di produzione (test_<ruolo>.py) -- SOLO diagnostica.

Uso: python formazione_mls/diagnostics/validate_outlier_shrinkage.py
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
ROLES = ('gk', 'def', 'mid', 'fwd')

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

K_GRID = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30]

# 27/07 (sessione estensione campionati): esteso da MLS-only a tutti i
# campionati con cache disponibile, stesso principio delle altre analisi
# estese in questa sessione.
# 29/07 (richiesta esplicita utente: "modello unico globale, non per lega"):
# sostituita la lista fissa (era ferma a 10 leghe) con auto-discovery dal
# filesystem, stesso pattern di measure_range_reliability._discover_leagues
# -- include automaticamente le 25 leghe extra create in questa sessione
# (turchia, germania, francia, ecc.), esclusa resto_mondo (copia
# disallineata nota, mai messa al passo col resto del modello).
def _discover_league_cache_tpl():
    tpl = {}
    for gk_dir in sorted(glob.glob(os.path.join('formazione_*', 'output', '*_gk_all'))):
        champ_dir = os.path.basename(os.path.dirname(os.path.dirname(gk_dir)))
        league = champ_dir[len('formazione_'):]
        if league == 'resto_mondo':
            continue
        tpl[league] = f'formazione_{league}/output/{league}_{{ruolo}}_all/.cache'
    if 'mls' in tpl:
        tpl['mls'] = 'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    if 'kleague' in tpl:
        tpl['kleague'] = 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache'
    return tpl


LEAGUE_CACHE_TPL = _discover_league_cache_tpl()


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def load_role_pool(ruolo):
    """Carica per il ruolo dato, da tutte le cache di calibrazione, la lista
    di (scores, is_home_flags) per giocatore -- ordinata cronologicamente,
    solo partite FINAL con score numerico valido. Stesso filtro MIN_HISTORY+3
    usato in validate_team_defense_strength.py (serve storico sufficiente
    per avere almeno qualche punto di test walk-forward per giocatore)."""
    files = []
    for tpl in LEAGUE_CACHE_TPL.values():
        files.extend(glob.glob(os.path.join(tpl.format(ruolo=ruolo), '*_detail_cache.json')))
    players = []

    for fpath in files:
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('score') is not None
                   and e.get('scoreStatus') == 'FINAL']
        if len(entries) < MIN_HISTORY + 3:
            continue

        # Determina la squadra del giocatore per euristica maggioranza (stesso
        # approccio di validate_team_defense_strength.py), serve solo per il
        # flag casa/trasferta.
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
            rows.append((dt, float(e['score']), is_home))
        rows.sort(key=lambda r: r[0])
        if len(rows) < MIN_HISTORY + 3:
            continue

        scores = [r[1] for r in rows]
        is_home_flags = [r[2] for r in rows]
        players.append({'scores': scores, 'is_home_flags': is_home_flags})

    return players


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

    # Prior strutturale del ruolo: media semplice (non pesata) di TUTTI gli
    # score storici di TUTTI i giocatori del pool -- calcolata UNA VOLTA SOLA,
    # non per-partita (vedi motivazione nel docstring in testa allo script).
    all_scores = [s for p in players for s in p['scores']]
    media_ruolo = statistics.mean(all_scores)

    n_players_used = len(players)

    # Per ogni punto di test: (reale, media_pesata, fattore_ct, fattore_trend, n)
    # cosi' possiamo provare tutta la griglia di k senza rifare il loop.
    test_points = []

    for p in players:
        scores = p['scores']
        is_home_flags = p['is_home_flags']
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

            reale = scores[i]
            test_points.append((reale, media, fattore_ct, fattore_trend, n))

    n_test_points = len(test_points)
    print(f"\n=== {ruolo.upper()} ({n_players_used} giocatori, {n_test_points} punti di test) ===")
    print(f"  media_ruolo (prior, {len(all_scores)} score nel pool): {media_ruolo:.2f}")

    n_low = sum(1 for *_, n in test_points if n < MIN_GAMES_LOW)
    n_high = n_test_points - n_low
    print(f"  Segmento n<{MIN_GAMES_LOW}: {n_low} punti di test | n>={MIN_GAMES_LOW}: {n_high} punti di test")

    mae_baseline = None
    best_k, best_mae = None, None
    best_k_low, best_mae_low = None, None
    risultati = []

    for k in K_GRID:
        errori = []
        errori_low = []
        errori_high = []
        for reale, media, fattore_ct, fattore_trend, n in test_points:
            if k == 0:
                media_corretta = media
            else:
                media_corretta = (n / (n + k)) * media + (k / (n + k)) * media_ruolo
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
            mae_baseline = mae
            mae_baseline_low = mae_low
            mae_baseline_high = mae_high

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

    # Segnala esplicitamente se il k migliore sul totale peggiora il segmento n>=8.
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
