"""
Validate Environmental Opponent Sensitivity (26/07, quarta sessione)

Domanda: la calibrazione separata di K League ha mostrato che per il ruolo DEF
il coefficiente ottimo di OPPONENT_SENSITIVITY e' 20.0 (15 giocatori/114
partite pesate), mentre TUTTI gli altri 7 ruoli/campionati calibrati oggi
(inclusi MID/FWD/GK di entrambi i campionati e DEF MLS) convergono su 29.0 --
vedi combinazione_vincente_aggregata.json nelle rispettive cartelle di
calibrazione. L'utente ha ipotizzato un motivo di contesto: il campionato
coreano ha difese piu' forti e meno gol, quindi la variabilita' "da
aggiustare per avversario" e' strutturalmente piu' bassa li'.

Principio guida (esplicito dell'utente): il modello resta SEMPRE UNO SOLO,
globale -- niente costanti per-campionato scelte a mano. Qui si testa se un
fattore AMBIENTALE misurabile (varianza dello score storico osservato nel
pool rilevante) possa spiegare automaticamente la differenza, permettendo a
un singolo OPPONENT_SENSITIVITY_BASE di adattarsi da solo a qualsiasi
campionato (incluso un quinto futuro mai visto).

PREMESSA IMPORTANTE (verificata nel codice prima di procedere): OPPONENT_SENSITIVITY
NON e' oggi usato nella formula REALE di score_atteso in produzione (vedi
test_def.py riga ~1319: score_atteso = p_gioca * media_pesata *
fattore_casa_trasferta * fattore_trend -- fattore_forza_avversario, l'unico
consumatore di OPPONENT_SENSITIVITY, e' stato rimosso da questa formula il
26/07, commit c7a4b831a, dopo che validate_team_defense_strength.py ha
mostrato che PEGGIORAVA il MAE reale). OPPONENT_SENSITIVITY oggi sopravvive
SOLO dentro rigorous_backtest()/run_grid_search() (diagnostica di calibrazione,
mostrata in output ma non usata per scegliere/ordinare i giocatori) e nel
dict `result` a scopo di visualizzazione. Questo script e i suoi risultati
sono quindi un esercizio esplorativo: utili per capire SE valga la pena
reintrodurre un fattore avversario ambientale in futuro, non un intervento
su codice di produzione.

Metodo:
1. Caratterizzazione ambientale: per ogni (campionato, ruolo) scansiona le
   cache di calibrazione gia' su disco e calcola media/dev.std dello score
   totale, media/dev.std/frequenza-clean-sheet dei gol subiti di squadra
   (stat 'goals_conceded', valore raw statValue, deduplicato per
   squadra/avversario/data come in validate_team_defense_strength.py).
2. Due formule concrete per un opponent_sensitivity "ambientale" che sostituisce
   la costante fissa, entrambe walk-forward (nessun lookahead):
   - Formula A (locale al giocatore): opp_sens_eff = BASE * (dev_std_pesata
     dello storico del giocatore fino a quel punto / dev_std di riferimento,
     quest'ultima fissata una volta sola dal pool MLS DEF, il campionato/ruolo
     di riferimento gia' calibrato su 29.0 con campione ampio).
   - Formula B (ambientale/campionato): opp_sens_eff = BASE * (dev.std dei gol
     subiti di squadra osservati nel campionato fino a quella data / dev.std
     di riferimento, stessa normalizzazione MLS). Cattura direttamente
     l'ipotesi "difese piu' forti = meno variabilita' = meno da aggiustare".
3. Backtest walk-forward rigoroso (stesso pattern di validate_team_defense_
   strength.py, funzioni reali importate via importlib dai moduli test_<ruolo>.py
   di produzione) confronta MAE: (a) OPPONENT_SENSITIVITY fisso=29.0 applicato
   nella stessa formula moltiplicativa storica di fattore_forza_avversario,
   (b) Formula A, (c) Formula B -- su DEF (dove e' emerso il problema, MLS e
   K League) e su MID come ruolo di controllo (dove oggi 29.0 vince ovunque,
   per verificare che l'ambientale non peggiori li' dove gia' funziona).

NESSUNA nuova query API: tutto dalle cache di calibrazione gia' su disco
(formazione_mls/output/mls_<ruolo>_calibration/.cache/ e
formazione_kleague/output/kleague_<ruolo>_calibration/.cache/).

Uso: python formazione_mls/diagnostics/validate_environmental_opponent_sensitivity.py
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
BASE_SENSITIVITY = 29.0

MODULE_BY_LEAGUE_ROLE = {
    ('mls', 'def'): 'formazione_mls.predict.test_def',
    ('mls', 'mid'): 'formazione_mls.predict.test_mid',
    ('kleague', 'def'): 'formazione_kleague.predict.test_def',
    ('kleague', 'mid'): 'formazione_kleague.predict.test_mid',
}

CACHE_DIR_BY_LEAGUE_ROLE = {
    ('mls', 'def'): 'formazione_mls/output/mls_def_calibration/.cache',
    ('mls', 'mid'): 'formazione_mls/output/mls_mid_calibration/.cache',
    ('kleague', 'def'): 'formazione_kleague/output/kleague_def_calibration/.cache',
    ('kleague', 'mid'): 'formazione_kleague/output/kleague_mid_calibration/.cache',
}

# Per la caratterizzazione ambientale (gol subiti di squadra) scansiono anche
# GK+MID di ciascun campionato quando disponibili, come in
# validate_team_defense_strength.py -- qui mi limito a DEF+MID (i due ruoli
# di questo studio) perche' e' gia' sufficiente a ricostruire una serie per
# squadra ragionevolmente popolata.
TEAM_DATA_ROLES_BY_LEAGUE = {
    'mls': ['def', 'mid', 'gk'],
    'kleague': ['def', 'mid', 'gk'],
}
CACHE_DIR_TEMPLATE = {
    'mls': 'formazione_mls/output/mls_{ruolo}_calibration/.cache',
    'kleague': 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache',
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


# ---------------------------------------------------------------------------
# STEP 1: caratterizzazione ambientale
# ---------------------------------------------------------------------------

def build_team_conceded_series(league):
    """Come in validate_team_defense_strength.py, ma parametrizzato per
    campionato. Ritorna dict team_slug -> [(datetime, gol_subiti_raw), ...]
    ordinata cronologicamente, deduplicata per (squadra, avversario, data)."""
    seen = set()
    series = defaultdict(list)

    for ruolo in TEAM_DATA_ROLES_BY_LEAGUE[league]:
        cache_dir = CACHE_DIR_TEMPLATE[league].format(ruolo=ruolo)
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


def characterize_environment():
    """Stampa e ritorna media/std dello score totale e dei gol subiti di
    squadra, per campionato e ruolo (DEF+MID), a scopo puramente descrittivo
    (nessun uso nel backtest walk-forward, solo diagnostica)."""
    print("=" * 78)
    print("STEP 1: caratterizzazione ambientale MLS vs K League")
    print("=" * 78)

    results = {}
    for league in ('mls', 'kleague'):
        team_series = build_team_conceded_series(league)
        all_conceded = [gc for series in team_series.values() for _, gc in series]
        clean_sheets = sum(1 for v in all_conceded if v == 0)
        mean_conceded = statistics.mean(all_conceded) if all_conceded else None
        std_conceded = statistics.pstdev(all_conceded) if len(all_conceded) > 1 else None
        pct_clean_sheet = (clean_sheets / len(all_conceded) * 100) if all_conceded else None

        print(f"\n--- {league.upper()} (gol subiti di squadra, {len(all_conceded)} partite-squadra "
              f"ricostruite da {len(team_series)} squadre) ---")
        print(f"  Media gol subiti/partita:  {mean_conceded:.3f}" if mean_conceded is not None else "  n/d")
        print(f"  Dev.std gol subiti:        {std_conceded:.3f}" if std_conceded is not None else "  n/d")
        print(f"  Frequenza clean sheet:     {pct_clean_sheet:.1f}%" if pct_clean_sheet is not None else "  n/d")

        results[league] = {
            'mean_conceded': mean_conceded, 'std_conceded': std_conceded,
            'pct_clean_sheet': pct_clean_sheet, 'team_series': team_series,
        }

        for ruolo in ('def', 'mid'):
            cache_dir = CACHE_DIR_BY_LEAGUE_ROLE[(league, ruolo)]
            files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
            scores = []
            for fpath in files:
                with open(fpath, encoding='utf-8') as f:
                    cache = json.load(f)
                if not cache:
                    continue
                for e in cache.values():
                    if e.get('anyGame') and e.get('score') is not None:
                        scores.append(e['score'])
            mean_s = statistics.mean(scores) if scores else None
            std_s = statistics.pstdev(scores) if len(scores) > 1 else None
            print(f"  [{ruolo.upper()}] score totale: n={len(scores)}  media={mean_s:.2f}  "
                  f"dev.std={std_s:.2f}" if scores else f"  [{ruolo.upper()}] nessun dato")
            results[(league, ruolo)] = {'mean_score': mean_s, 'std_score': std_s, 'n': len(scores)}

    if results['mls']['std_conceded'] and results['kleague']['std_conceded']:
        ratio = results['kleague']['std_conceded'] / results['mls']['std_conceded']
        print(f"\n  Rapporto std_conceded K League / MLS: {ratio:.3f} "
              f"({'K League ha ambiente meno variabile' if ratio < 1 else 'K League ha ambiente PIU variabile'})")
    return results


# ---------------------------------------------------------------------------
# STEP 2+3: backtest walk-forward, fisso vs formule ambientali
# ---------------------------------------------------------------------------

def weighted_avg_conceded_before(series_for_team, cutoff_dt, half_life_games=10, max_games=15):
    if not series_for_team:
        return None
    past = [gc for dt, gc in series_for_team if dt < cutoff_dt]
    if not past:
        return None
    past = past[-max_games:]
    n = len(past)
    weights = [0.5 ** (i / half_life_games) for i in range(n)]
    weights.reverse()
    total_w = sum(weights)
    return sum(v * w for v, w in zip(past, weights)) / total_w


def league_conceded_std_before(team_series, cutoff_dt):
    """Dev.std (population) dei gol subiti osservati nell'INTERO campionato
    fino a cutoff_dt (finestra crescente walk-forward, nessun lookahead --
    usa solo partite con data < cutoff_dt, indipendentemente dalla squadra)."""
    vals = [gc for series in team_series.values() for dt, gc in series if dt < cutoff_dt]
    if len(vals) < 10:
        return None
    return statistics.pstdev(vals)


def run_role_backtest(league, ruolo, team_series, reference_std_player, reference_std_league):
    """Backtest walk-forward: confronta fisso (29.0) vs Formula A (locale
    giocatore) vs Formula B (ambientale campionato), sulla STESSA formula
    moltiplicativa storica di fattore_forza_avversario (quella rimossa da
    score_atteso in produzione, qui riattivata solo per questo esperimento
    diagnostico)."""
    mod = importlib.import_module(MODULE_BY_LEAGUE_ROLE[(league, ruolo)])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    weighted_stddev = mod.weighted_stddev
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    TREND_INTENSITY = mod.TREND_INTENSITY

    cache_dir = CACHE_DIR_BY_LEAGUE_ROLE[(league, ruolo)]
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))

    errori_fisso, errori_a, errori_b, errori_noadjust = [], [], [], []
    n_players_used = 0
    n_test_points = 0

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
            dev_std_pesata = weighted_stddev(hist_scores, weights, media)
            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)
            base_pred = media * fattore_ct * fattore_trend
            reale = scores[i]
            errori_noadjust.append(reale - base_pred)

            valid_ranks = [r for r in hist_opp if r is not None]
            avg_opp_hist = sum(valid_ranks) / len(valid_ranks) if valid_ranks else None
            target_opp_rank = opp_ranks[i]
            if not (avg_opp_hist and target_opp_rank):
                # nessun dato di ranking disponibile: fattore neutro per tutte
                # e tre le varianti (stesso comportamento della produzione)
                errori_fisso.append(reale - base_pred)
                errori_a.append(reale - base_pred)
                errori_b.append(reale - base_pred)
                n_test_points += 1
                continue

            rank_delta = target_opp_rank - avg_opp_hist

            # --- (a) fisso 29.0 ---
            sens_fisso = BASE_SENSITIVITY
            fattore_fisso = max(0.5, min(1.5, 1.0 + rank_delta / sens_fisso))
            errori_fisso.append(reale - base_pred * fattore_fisso)

            # --- (b) Formula A: locale al giocatore (dev_std_pesata storico / riferimento) ---
            if dev_std_pesata and dev_std_pesata > 0 and reference_std_player:
                sens_a = BASE_SENSITIVITY * (dev_std_pesata / reference_std_player)
                sens_a = max(5.0, min(100.0, sens_a))  # guard-rail contro divisioni degeneri
            else:
                sens_a = BASE_SENSITIVITY
            fattore_a = max(0.5, min(1.5, 1.0 + rank_delta / sens_a))
            errori_a.append(reale - base_pred * fattore_a)

            # --- (c) Formula B: ambientale/campionato (std gol subiti a livello lega, walk-forward) ---
            local_league_std = league_conceded_std_before(team_series, dates[i])
            if local_league_std and local_league_std > 0 and reference_std_league:
                sens_b = BASE_SENSITIVITY * (local_league_std / reference_std_league)
                sens_b = max(5.0, min(100.0, sens_b))
            else:
                sens_b = BASE_SENSITIVITY
            fattore_b = max(0.5, min(1.5, 1.0 + rank_delta / sens_b))
            errori_b.append(reale - base_pred * fattore_b)

            n_test_points += 1

    if not errori_fisso:
        print(f"{league.upper()}/{ruolo.upper()}: nessun dato utilizzabile")
        return None

    mae_fisso = statistics.mean(abs(e) for e in errori_fisso)
    mae_a = statistics.mean(abs(e) for e in errori_a)
    mae_b = statistics.mean(abs(e) for e in errori_b)
    mae_noadjust = statistics.mean(abs(e) for e in errori_noadjust)
    pct_a = (mae_a - mae_fisso) / mae_fisso * 100
    pct_b = (mae_b - mae_fisso) / mae_fisso * 100
    pct_noadjust = (mae_noadjust - mae_fisso) / mae_fisso * 100

    print(f"\n=== {league.upper()}/{ruolo.upper()} ({n_players_used} giocatori, {n_test_points} punti test) ===")
    print(f"  MAE fisso (opp_sens=29.0):              {mae_fisso:.3f}")
    print(f"  MAE Formula A (locale giocatore):        {mae_a:.3f}  ({pct_a:+.2f}%)")
    print(f"  MAE Formula B (ambientale campionato):   {mae_b:.3f}  ({pct_b:+.2f}%)")
    print(f"  MAE senza aggiustamento (fattore=1.0, produzione attuale): {mae_noadjust:.3f}  ({pct_noadjust:+.2f}%)")
    return {'league': league, 'ruolo': ruolo, 'n_players': n_players_used, 'n_test': n_test_points,
            'mae_fisso': mae_fisso, 'mae_a': mae_a, 'mae_b': mae_b, 'pct_a': pct_a, 'pct_b': pct_b,
            'mae_noadjust': mae_noadjust, 'pct_noadjust': pct_noadjust}


def main():
    env = characterize_environment()

    # Riferimento fisso: MLS DEF, il pool piu' ampio gia' calibrato su 29.0.
    reference_std_player = None
    ref_mod = importlib.import_module(MODULE_BY_LEAGUE_ROLE[('mls', 'def')])
    ref_files = glob.glob(os.path.join(CACHE_DIR_BY_LEAGUE_ROLE[('mls', 'def')], '*_detail_cache.json'))
    ref_stds = []
    for fpath in ref_files:
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('score') is not None]
        if len(entries) < MIN_HISTORY + 3:
            continue
        scores_all = [e['score'] for e in entries]
        w_all = ref_mod.exponential_weights(len(scores_all), ref_mod.HALF_LIFE_GAMES)
        m_all = ref_mod.weighted_mean(scores_all, w_all)
        s_all = ref_mod.weighted_stddev(scores_all, w_all, m_all)
        if s_all:
            ref_stds.append(s_all)
    reference_std_player = statistics.mean(ref_stds) if ref_stds else None
    reference_std_league = env['mls']['std_conceded']

    print("\n" + "=" * 78)
    print(f"Riferimenti (MLS DEF, pool di calibrazione): "
          f"dev_std_pesata media giocatore={reference_std_player:.3f}  "
          f"dev_std gol-subiti campionato={reference_std_league:.3f}")
    print("=" * 78)

    print("\n" + "=" * 78)
    print("STEP 2+3: backtest walk-forward, fisso vs ambientale")
    print("=" * 78)

    all_results = []
    for league in ('mls', 'kleague'):
        team_series = env[league]['team_series']
        for ruolo in ('def', 'mid'):
            res = run_role_backtest(league, ruolo, team_series, reference_std_player, reference_std_league)
            if res:
                all_results.append(res)

    print("\n" + "=" * 78)
    print("RIEPILOGO")
    print("=" * 78)
    for r in all_results:
        print(f"  {r['league'].upper()}/{r['ruolo'].upper()}: fisso={r['mae_fisso']:.3f}  "
              f"A={r['mae_a']:.3f} ({r['pct_a']:+.2f}%)  B={r['mae_b']:.3f} ({r['pct_b']:+.2f}%)  "
              f"noadjust={r['mae_noadjust']:.3f} ({r['pct_noadjust']:+.2f}%)  [n_test={r['n_test']}]")


if __name__ == '__main__':
    main()
