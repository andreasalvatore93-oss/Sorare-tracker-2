"""
Validate RANGE_MULTIPLIER via % copertura (29/07, richiesta esplicita utente).

RANGE_MULTIPLIER (in formazione_mls/predict/test_gk.py, test_def.py, test_mid.py,
test_mls_fwd_all.py -- e equivalenti K League) moltiplica la deviazione standard
pesata dello storico per produrre l'ampiezza del range di confidenza low/high
mostrato intorno allo score_atteso (vedi rigorous_backtest_prod_<ruolo>, che
richiama compute_score_atteso_<ruolo> -- la STESSA funzione della predizione
reale -- e poi range_conf = dev_std_pesata * range_multiplier). NON influisce
sul MAE della predizione puntuale (predetto non dipende da range_multiplier),
quindi non e' testabile con quella metrica. La metrica giusta e' la "%
COPERTURA": quante volte, nel backtest walk-forward, il reale cade dentro
[predetto-range_conf, predetto+range_conf]. Un buon range ha copertura vicina
a un target ragionevole (~70-85%): ne' troppo stretto (copertura bassa, range
inutile) ne' troppo largo (copertura ~99% ma range enorme, inutile anche
quello).

Per ciascun ruolo GK/DEF/MID/FWD, questo script:
1. Legge RANGE_MULTIPLIER ATTUALE dal modulo di produzione corrispondente
   (importato, non hardcodato).
2. Per un grid di range_multiplier, chiama rigorous_backtest_prod_<ruolo> (la
   funzione di produzione, walk-forward, stessa formula esatta usata in
   build_prediction) e misura: % copertura + ampiezza media del range
   (high-low = 2 * dev_std_pesata * range_multiplier).
3. Riporta entrambe le metriche per ogni valore del grid -- NESSUN "vincitore"
   automatico, il compromesso copertura/larghezza lo sceglie l'utente.

Dataset: TUTTE le leghe (29/07, regola esplicita utente: ogni test va fatto
su tutte le leghe, non solo MLS/K League), via glob
'formazione_*/output/*_<ruolo>_all/.cache' + '_calibration/.cache' -- stessa
infrastruttura di formazione_mls/diagnostics/validate_halflife_venue.py.

Uso: python formazione_mls/diagnostics/validate_range_multiplier_coverage.py
"""
import os
import sys
import json
import glob
import datetime
import importlib
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

BASE_GRID = [0.5, 0.7, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def iter_cache_files(ruolo):
    patterns = [f'formazione_*/output/*_{ruolo}_calibration/.cache',
                f'formazione_*/output/*_{ruolo}_all/.cache']
    seen = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath not in seen:
                    seen.add(fpath)
                    yield fpath


def load_players_gk(mod):
    """Ritorna liste di dict {scores, is_home_flags, granulari, pos_dec, neg_dec}
    per giocatore, con TUTTI i campi che servono a compute_score_atteso_gk."""
    extract_level_score = mod.extract_level_score
    extract_decisive_rates = mod.extract_decisive_rates
    players = []
    for fpath in iter_cache_files('gk'):
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
            score = e.get('score') or 0.0
            level_v = extract_level_score(e)
            pos_v, neg_v = extract_decisive_rates(e)
            rows.append({'date': dt, 'score': score, 'is_home': is_home,
                         'granulare': score - level_v, 'pos_dec': pos_v, 'neg_dec': neg_v})
        rows.sort(key=lambda r: r['date'])
        if len(rows) < MIN_HISTORY + 3:
            continue
        players.append(rows)
    return players


def load_players_def_mid_fwd(mod, ruolo):
    """Ritorna liste di dict per giocatore con tutti i campi che servono a
    compute_score_atteso_def/mid/fwd (residual/granulari/pos-neg
    decisivi/goals_conceded/passing[/clean_sheet solo DEF]/opponent_rankings
    [non FWD]) -- stessa scomposizione ESATTA usata in build_prediction."""
    extract_group_score = mod.extract_group_score
    extract_level_score = mod.extract_level_score
    extract_decisive_rates = mod.extract_decisive_rates
    team_ranking_from_game = mod.team_ranking_from_game
    FOULS_STATS = mod.FOULS_STATS
    DUELS_STATS = mod.DUELS_STATS
    OFFENSIVE_STATS = mod.OFFENSIVE_STATS
    PASSING_STATS = mod.PASSING_STATS
    DEFENSE_RARE_STATS = mod.DEFENSE_RARE_STATS
    DEFENSE_RARE_CAP = mod.DEFENSE_RARE_CAP
    GOALS_CONCEDED_STATS = getattr(mod, 'GOALS_CONCEDED_STATS', None)
    DEFENSIVE_ACTIONS_STATS = getattr(mod, 'DEFENSIVE_ACTIONS_STATS', None)
    CLEAN_SHEET_STATS = getattr(mod, 'CLEAN_SHEET_STATS', None)

    players = []
    for fpath in iter_cache_files(ruolo):
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
        rows = []
        for e in entries:
            g = e['anyGame']
            dt = parse_date(g)
            if dt is None:
                continue
            own_rank, opp_rank, is_home = team_ranking_from_game(g, team_slug)
            if is_home is None:
                continue
            score = e.get('score') or 0.0

            fouls_v = extract_group_score(e, FOULS_STATS)
            duels_v = extract_group_score(e, DUELS_STATS)
            offensive_v = extract_group_score(e, OFFENSIVE_STATS)
            passing_v = extract_group_score(e, PASSING_STATS)
            defense_raw = extract_group_score(e, DEFENSE_RARE_STATS)
            goals_conceded_raw = (extract_group_score(e, GOALS_CONCEDED_STATS)
                                   if GOALS_CONCEDED_STATS else 0.0)
            defensive_actions_v = (extract_group_score(e, DEFENSIVE_ACTIONS_STATS)
                                    if DEFENSIVE_ACTIONS_STATS else 0.0)
            clean_sheet_v = (extract_group_score(e, CLEAN_SHEET_STATS)
                              if CLEAN_SHEET_STATS else 0.0)
            defense_rare_capped = max(-DEFENSE_RARE_CAP, min(DEFENSE_RARE_CAP, defense_raw))

            level_v = extract_level_score(e)
            pos_v, neg_v = extract_decisive_rates(e)

            # Residuo = punteggio totale meno tutti i gruppi granulari tracciati
            # dal modulo di quel ruolo -- REPLICA ESATTA di build_prediction
            # (DEF include clean_sheet+defensive_actions, MID include
            # defensive_actions ma non clean_sheet, FWD non include nessuno
            # dei due -- vedi rispettivamente test_def.py/test_mid.py/
            # test_mls_fwd_all.py, sezione costruzione residual_values).
            if ruolo == 'def':
                covered_total = (fouls_v + duels_v + offensive_v + passing_v
                                 + defense_raw + defensive_actions_v + goals_conceded_raw + clean_sheet_v)
            elif ruolo == 'mid':
                covered_total = (fouls_v + duels_v + offensive_v + passing_v
                                 + defense_raw + defensive_actions_v + goals_conceded_raw)
            else:  # fwd
                covered_total = fouls_v + duels_v + offensive_v + passing_v + defense_raw
            residual_v = score - covered_total

            rows.append({
                'date': dt, 'score': score, 'is_home': is_home, 'opp_rank': opp_rank,
                'residual': residual_v, 'granulare': score - level_v,
                'pos_dec': pos_v, 'neg_dec': neg_v,
                'goals_conceded': goals_conceded_raw, 'passing': passing_v,
                'clean_sheet': clean_sheet_v,
            })
        rows.sort(key=lambda r: r['date'])
        if len(rows) < MIN_HISTORY + 3:
            continue
        players.append(rows)
    return players


def run_role_gk(ruolo='gk'):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    RANGE_MULTIPLIER_ATTUALE = mod.RANGE_MULTIPLIER
    rigorous_backtest_prod_gk = mod.rigorous_backtest_prod_gk

    players = load_players_gk(mod)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return

    grid = sorted(set(BASE_GRID) | {round(RANGE_MULTIPLIER_ATTUALE, 3)})
    print(f"\n{'='*82}\nGK ({len(players)} giocatori) -- RANGE_MULTIPLIER attuale={RANGE_MULTIPLIER_ATTUALE}\n{'='*82}")
    for rm in grid:
        pct_list, width_list, n_test = [], [], 0
        for rows in players:
            scores = [r['score'] for r in rows]
            is_home_flags = [r['is_home'] for r in rows]
            granulari = [r['granulare'] for r in rows]
            pos_dec = [r['pos_dec'] for r in rows]
            neg_dec = [r['neg_dec'] for r in rows]
            bt = rigorous_backtest_prod_gk(scores, is_home_flags, granulari, pos_dec, neg_dec,
                                            min_history=MIN_HISTORY, range_multiplier=rm)
            for r in bt['rows']:
                if r['dentro_range'] is not None:
                    pct_list.append(1.0 if r['dentro_range'] else 0.0)
                w = mod.weighted_stddev(scores[:r['i']],
                                         mod.exponential_weights(r['i'], mod.HALF_LIFE_GAMES),
                                         mod.weighted_mean(scores[:r['i']], mod.exponential_weights(r['i'], mod.HALF_LIFE_GAMES)))
                width_list.append(2 * w * rm)
                n_test += 1
        flag = " <== ATTUALE" if abs(rm - RANGE_MULTIPLIER_ATTUALE) < 1e-9 else ""
        pct = statistics.mean(pct_list) * 100 if pct_list else float('nan')
        width = statistics.mean(width_list) if width_list else float('nan')
        print(f"  range_multiplier={rm:4.2f}  copertura={pct:5.1f}%  ampiezza_media={width:6.2f}  "
              f"({n_test} punti test){flag}")


def run_role_def_mid_fwd(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    RANGE_MULTIPLIER_ATTUALE = mod.RANGE_MULTIPLIER
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    weighted_stddev = mod.weighted_stddev
    weighted_mean = mod.weighted_mean
    exponential_weights = mod.exponential_weights

    players = load_players_def_mid_fwd(mod, ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return

    if ruolo == 'def':
        bt_fn = mod.rigorous_backtest_prod_def

        def call_bt(rows, rm):
            scores = [r['score'] for r in rows]
            is_home_flags = [r['is_home'] for r in rows]
            opp_ranks = [r['opp_rank'] for r in rows]
            residual = [r['residual'] for r in rows]
            granulari = [r['granulare'] for r in rows]
            pos_dec = [r['pos_dec'] for r in rows]
            neg_dec = [r['neg_dec'] for r in rows]
            goals_conceded = [r['goals_conceded'] for r in rows]
            passing = [r['passing'] for r in rows]
            clean_sheet = [r['clean_sheet'] for r in rows]
            bt = bt_fn(scores, is_home_flags, opp_ranks, residual, granulari,
                       pos_dec, neg_dec, goals_conceded, passing, clean_sheet,
                       min_history=MIN_HISTORY, range_multiplier=rm)
            return bt, scores
    elif ruolo == 'mid':
        bt_fn = mod.rigorous_backtest_prod_mid

        def call_bt(rows, rm):
            scores = [r['score'] for r in rows]
            is_home_flags = [r['is_home'] for r in rows]
            opp_ranks = [r['opp_rank'] for r in rows]
            residual = [r['residual'] for r in rows]
            granulari = [r['granulare'] for r in rows]
            pos_dec = [r['pos_dec'] for r in rows]
            neg_dec = [r['neg_dec'] for r in rows]
            goals_conceded = [r['goals_conceded'] for r in rows]
            passing = [r['passing'] for r in rows]
            # NOTA: nel dataset diagnostico l'unico gruppo "offensivo" tracciato
            # separatamente e' extract_group_score(OFFENSIVE_STATS), qui non
            # ricostruito a parte (usiamo lo stesso campo 'passing' anche come
            # proxy offensive_values) -- la differenza incide SOLO sullo
            # Stadio D (una piccola correzione additiva condizionata a venue/
            # avversario), NON sulla formula del range di confidenza
            # (dev_std_pesata sui punteggi totali, che e' quello che questo
            # script misura -- invariata).
            bt = bt_fn(scores, is_home_flags, opp_ranks, residual, granulari,
                       pos_dec, neg_dec, passing, passing, goals_conceded,
                       min_history=MIN_HISTORY, range_multiplier=rm)
            return bt, scores
    else:  # fwd
        bt_fn = mod.rigorous_backtest_prod_fwd

        def call_bt(rows, rm):
            scores = [r['score'] for r in rows]
            is_home_flags = [r['is_home'] for r in rows]
            residual = [r['residual'] for r in rows]
            granulari = [r['granulare'] for r in rows]
            pos_dec = [r['pos_dec'] for r in rows]
            neg_dec = [r['neg_dec'] for r in rows]
            passing = [r['passing'] for r in rows]
            bt = bt_fn(scores, is_home_flags, residual, granulari, pos_dec, neg_dec, passing,
                       min_history=MIN_HISTORY, range_multiplier=rm)
            return bt, scores

    grid = sorted(set(BASE_GRID) | {round(RANGE_MULTIPLIER_ATTUALE, 3)})
    print(f"\n{'='*82}\n{ruolo.upper()} ({len(players)} giocatori) -- RANGE_MULTIPLIER attuale={RANGE_MULTIPLIER_ATTUALE}\n{'='*82}")
    for rm in grid:
        pct_list, width_list, n_test = [], [], 0
        for rows in players:
            bt, scores = call_bt(rows, rm)
            for r in bt['rows']:
                if r['dentro_range'] is not None:
                    pct_list.append(1.0 if r['dentro_range'] else 0.0)
                w = weighted_stddev(scores[:r['i']],
                                     exponential_weights(r['i'], HALF_LIFE_GAMES),
                                     weighted_mean(scores[:r['i']], exponential_weights(r['i'], HALF_LIFE_GAMES)))
                width_list.append(2 * w * rm)
                n_test += 1
        flag = " <== ATTUALE" if abs(rm - RANGE_MULTIPLIER_ATTUALE) < 1e-9 else ""
        pct = statistics.mean(pct_list) * 100 if pct_list else float('nan')
        width = statistics.mean(width_list) if width_list else float('nan')
        print(f"  range_multiplier={rm:4.2f}  copertura={pct:5.1f}%  ampiezza_media={width:6.2f}  "
              f"({n_test} punti test){flag}")


def main():
    run_role_gk('gk')
    run_role_def_mid_fwd('def')
    run_role_def_mid_fwd('mid')
    run_role_def_mid_fwd('fwd')


if __name__ == '__main__':
    main()
