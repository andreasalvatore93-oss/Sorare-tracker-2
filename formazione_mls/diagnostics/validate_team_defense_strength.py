"""
Validate Team Defense Strength (26/07, terza sessione)

Backtest walk-forward rigoroso per rispondere alla domanda: sostituire il
ranking di campionato generico (usato oggi da fattore_forza_avversario per
tutti e 4 i ruoli) con una metrica SPECIFICA -- la media pesata dei gol
subiti storici dall'avversario -- riduce il MAE reale?

Motivazione (26/07, discussione con l'utente): il ranking di campionato
mischia forza offensiva e difensiva in un unico numero. Per un attaccante
quello che conta davvero e' quanto concede l'avversario (non quanto e'
"forte" in generale); per portiere/difensore/centrocampista il ragionamento
e' analogo (avversario che concede poco = piu' probabile un buon
punteggio decisivo, coerente con quanto gia' trovato nella diagnostica
Stadio D di stanotte).

NESSUNA nuova query API: il dato e' gia' nelle cache di calibrazione. Il
"gol subiti" e' un fatto DI SQUADRA -- in una data partita tutti i
giocatori della stessa squadra (qualunque ruolo) hanno lo stesso identico
valore statValue di 'goals_conceded' per quella partita. Scansionando le
cache di GK+DEF+MID (che tracciano questo stat) di TUTTI i giocatori
disponibili, ricostruiamo una serie storica (data, gol_subiti) per ogni
squadra che compare almeno una volta tra i giocatori cachati -- senza
bisogno di scaricare nulla di nuovo dall'API Sorare.

RISULTATO (26/07, deciso con l'utente): il confronto a 3 vie (ranking
attuale vs nessun aggiustamento avversario vs gol-subiti) ha mostrato che
RIMUOVERE del tutto l'aggiustamento per forza avversario batte sia il
ranking sia i gol subiti per DEF/MID/FWD (-6.65%/-9.20%/-9.26% MAE);
solo per GK i gol subiti (sensibilita' quasi nulla) fanno leggermente
meglio della rimozione totale (-6.08% vs -4.02%), ma la differenza non
giustifica la nuova infrastruttura di query team-level che servirebbe in
produzione (qui il dato viene dalle cache di CALIBRAZIONE, che in
produzione non esistono per il giocatore/avversario di turno). Decisione:
fattore_forza_avversario rimosso da score_atteso in produzione per tutti
e 4 i ruoli (MLS+K League) -- vedi test_<ruolo>.py. Il tema gol-subiti in
produzione resta backlog per quando servira' una query team-level dedicata.

Metodo:
1. Scansiona le cache di calibrazione GK+DEF+MID, estrae per ogni
   partita: squadra del giocatore (euristica maggioranza gia' usata
   altrove), avversario, DATA, gol subiti (statValue di goals_conceded).
2. Deduplica per (squadra, avversario, data) -- piu' compagni di squadra
   cachati nella stessa partita danno lo stesso valore, contarlo una
   volta sola.
3. Costruisce una serie cronologica per squadra: [(data, gol_subiti), ...].
4. Per il backtest walk-forward (stesso approccio di
   validate_stadio_d_mae.py): per ogni partita di test in cache (di
   qualunque ruolo), calcola la media pesata (stesso half-life del ruolo)
   dei gol subiti STORICI dell'avversario, usando SOLO partite di quella
   squadra con DATA precedente alla partita di test (nessun lookahead).
5. Confronta tre formule alternative di fattore_forza_avversario (ranking
   attuale, nessun aggiustamento, gol subiti con grid search sul
   coefficiente di sensibilita') e misura il MAE risultante con ciascuna.

Uso: python formazione_mls/diagnostics/validate_team_defense_strength.py
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
ROLES_FOR_TEAM_DATA = ('gk', 'def', 'mid')  # tracciano goals_conceded
ROLES_FOR_BACKTEST = ('gk', 'def', 'mid', 'fwd')  # testiamo su tutti e 4

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def build_team_conceded_series():
    """Ritorna dict team_slug -> lista ordinata cronologicamente di
    (datetime, gol_subiti), deduplicata per (team, opponent, data)."""
    seen = set()
    series = defaultdict(list)

    for ruolo in ROLES_FOR_TEAM_DATA:
        cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
        files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
        for fpath in files:
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
            if not cache:
                continue
            entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
            if not entries:
                continue
            games = [e['anyGame'] for e in entries]
            team_slug = player_team_slug(games)
            if not team_slug:
                continue

            for e in entries:
                g = e['anyGame']
                home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                if home.get('slug') == team_slug:
                    opp_slug = away.get('slug')
                elif away.get('slug') == team_slug:
                    opp_slug = home.get('slug')
                else:
                    continue
                dt = parse_date(g)
                if dt is None or not opp_slug:
                    continue
                key = (team_slug, opp_slug, dt.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                goals_conceded = None
                for stat_row in e['detailedScore']:
                    if stat_row.get('stat') == 'goals_conceded':
                        goals_conceded = stat_row.get('statValue', 0.0) or 0.0
                        break
                if goals_conceded is None:
                    continue
                series[team_slug].append((dt, goals_conceded))

    for team_slug in series:
        series[team_slug].sort(key=lambda t: t[0])

    return series


def weighted_avg_conceded_before(series_for_team, cutoff_dt, half_life_games=10, max_games=15):
    """Media pesata (half-life sul CONTEGGIO di partite, non sui giorni) dei
    gol subiti dalla squadra nelle partite precedenti a cutoff_dt. None se
    non ci sono partite utilizzabili (squadra mai vista prima di quella
    data, o mai cachata)."""
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if not past:
        return None
    past = past[-max_games:]
    n = len(past)
    weights = [0.5 ** (i / half_life_games) for i in range(n)]
    weights.reverse()  # piu' peso alle piu' recenti (ultime della lista)
    total_w = sum(weights)
    return sum(v * w for v, w in zip(past, weights)) / total_w


SENSITIVITY_GRID = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40]


def run_role(ruolo, team_conceded_series):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    OPPONENT_SENSITIVITY = mod.OPPONENT_SENSITIVITY
    TREND_INTENSITY = mod.TREND_INTENSITY

    cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))

    errori_ranking = []
    # Per ogni punto di test: (reale, base_pred_senza_fa, z_conceded_o_None, fattore_fa_ranking)
    # base_pred_senza_fa = media * fattore_ct * fattore_trend, cosi' possiamo
    # provare tutti i coefficienti della griglia senza rifare la scansione cache.
    test_points = []
    n_players_used = 0
    n_test_points = 0
    n_conceded_available = 0

    # Distribuzione globale dei gol subiti (per normalizzare il delta come
    # fa compute_split_factor, invece di una scala arbitraria).
    all_conceded_values = [gc for series in team_conceded_series.values() for _, gc in series]
    global_std_conceded = statistics.pstdev(all_conceded_values) if len(all_conceded_values) > 1 else 1.0
    global_mean_conceded = statistics.mean(all_conceded_values) if all_conceded_values else 1.0

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

        scores, is_home_flags, opp_ranks, opp_slugs, dates = [], [], [], [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home, opp_rank, opp_slug = True, away.get('domesticLeagueRanking'), away.get('slug')
            elif away.get('slug') == team_slug:
                is_home, opp_rank, opp_slug = False, home.get('domesticLeagueRanking'), home.get('slug')
            else:
                continue
            dt = parse_date(g)
            scores.append(e.get('score') or 0.0)
            is_home_flags.append(is_home)
            opp_ranks.append(opp_rank)
            opp_slugs.append(opp_slug)
            dates.append(dt)

        n = len(scores)
        if n < MIN_HISTORY + 3:
            continue
        n_players_used += 1

        for i in range(MIN_HISTORY, n):
            if dates[i] is None:
                continue
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            hist_opp = opp_ranks[:i]
            weights = exponential_weights(i, HALF_LIFE_GAMES)

            media = weighted_mean(hist_scores, weights)
            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

            # --- Fattore forza avversario ATTUALE (ranking) ---
            valid_ranks = [r for r in hist_opp if r is not None]
            avg_opp_hist = sum(valid_ranks) / len(valid_ranks) if valid_ranks else None
            target_opp_rank = opp_ranks[i]
            fattore_fa_ranking = 1.0
            if avg_opp_hist and target_opp_rank:
                delta = (target_opp_rank - avg_opp_hist) / OPPONENT_SENSITIVITY
                fattore_fa_ranking = max(0.5, min(1.5, 1.0 + delta))

            pred_ranking = media * fattore_ct * fattore_fa_ranking * fattore_trend
            reale = scores[i]
            errori_ranking.append(reale - pred_ranking)

            # --- Fattore forza avversario NUOVO (gol subiti storici) ---
            target_opp_slug = opp_slugs[i]
            series_for_opp = team_conceded_series.get(target_opp_slug, [])
            avg_conceded = weighted_avg_conceded_before(series_for_opp, dates[i])
            z = None
            if avg_conceded is not None:
                n_conceded_available += 1
                z = (avg_conceded - global_mean_conceded) / global_std_conceded if global_std_conceded > 0 else 0.0

            base_pred = media * fattore_ct * fattore_trend
            test_points.append((reale, base_pred, z, fattore_fa_ranking))
            n_test_points += 1

    if not errori_ranking:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return

    mae_ranking = statistics.mean(abs(e) for e in errori_ranking)
    pct_coverage = n_conceded_available / n_test_points * 100

    print(f"\n=== {ruolo.upper()} ({n_players_used} giocatori, {n_test_points} punti di test) ===")
    print(f"  Copertura dato gol-subiti-avversario: {n_conceded_available}/{n_test_points} ({pct_coverage:.0f}%)")
    print(f"  MAE con ranking (attuale):     {mae_ranking:.3f}")

    # Confronto extra: nessun aggiustamento avversario AFFATTO (fattore_fa=1.0
    # sempre, non solo quando manca il dato gol-subiti).
    errori_noadjust = [reale - base_pred * 1.0 for reale, base_pred, _, _ in test_points]
    mae_noadjust = statistics.mean(abs(e) for e in errori_noadjust)
    pct_noadjust = (mae_noadjust - mae_ranking) / mae_ranking * 100
    print(f"  MAE senza aggiustamento avversario (fattore=1.0 sempre): {mae_noadjust:.3f} ({pct_noadjust:+.2f}%)")

    best_sens, best_mae = None, None
    for sens in SENSITIVITY_GRID:
        errori = []
        for reale, base_pred, z, fattore_fa_ranking in test_points:
            if z is not None:
                fattore_fa = max(0.5, min(1.5, 1.0 + z * sens))
            else:
                fattore_fa = fattore_fa_ranking
            errori.append(reale - base_pred * fattore_fa)
        mae = statistics.mean(abs(e) for e in errori)
        pct_change = (mae - mae_ranking) / mae_ranking * 100
        flag = " <== MIGLIORE" if best_mae is None or mae < best_mae else ""
        print(f"    sensibilita'={sens:.2f}  MAE={mae:.3f}  variazione={pct_change:+.2f}%{flag}")
        if best_mae is None or mae < best_mae:
            best_sens, best_mae = sens, mae

    pct_change_best = (best_mae - mae_ranking) / mae_ranking * 100
    print(f"  MIGLIOR coefficiente gol-subiti: {best_sens:.2f} (MAE={best_mae:.3f}, {pct_change_best:+.2f}% vs ranking)")
    return best_sens, best_mae, mae_ranking, mae_noadjust


def main():
    print("Ricostruzione serie storiche gol-subiti per squadra dalle cache GK+DEF+MID...")
    team_conceded_series = build_team_conceded_series()
    print(f"Squadre ricostruite: {len(team_conceded_series)}")
    for ruolo in ROLES_FOR_BACKTEST:
        run_role(ruolo, team_conceded_series)


if __name__ == '__main__':
    main()
