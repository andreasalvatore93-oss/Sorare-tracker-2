"""
Validate Stadio D MAE (26/07, notte/mattina)

Backtest walk-forward rigoroso (nessun lookahead: ogni predizione usa SOLO le
partite precedenti) su dati REALI dalle cache di calibrazione, per rispondere
alla domanda: le correzioni Stadio D (condizionamento venue/avversario sulle
sotto-categorie granulari + level_score) RIDUCONO davvero l'errore medio
(MAE), o sono solo "statisticamente giustificate in aggregato" senza reale
beneficio predittivo per singolo giocatore?

Riusa le funzioni di produzione VERE (exponential_weights, weighted_mean,
compute_split_factor, compute_trend_factor, media_condizionata) importate
direttamente dai moduli formazione_mls.predict.test_<ruolo>, per garantire
fedelta' assoluta con la formula realmente in uso (nessuna reimplementazione
parallela che potrebbe divergere in modo sottile da cosa gira davvero).

Per ogni giocatore in cache, per ogni indice i da min_history in poi:
- baseline = media_pesata(scores[:i]) * fattore_casa_trasferta(residuo[:i])
             * fattore_forza_avversario(rank[:i]) * fattore_trend(scores[:i])
  (P(gioca) fissato a 100%, sappiamo gia' che ha giocato -- stesso principio
  di rigorous_backtest() gia' esistente in produzione)
- stadio_d_delta = somma dei delta media_condizionata() per ogni sotto-
  categoria condizionata in produzione per quel ruolo, usando SOLO
  values[:i]/weights[:i] (mai dati futuri)
- errore_baseline = reale - baseline
- errore_stadio_d = reale - (baseline + stadio_d_delta)

Uso: RUOLO=mid python formazione_mls/diagnostics/validate_stadio_d_mae.py
     RUOLO=all python formazione_mls/diagnostics/validate_stadio_d_mae.py
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
RUOLO_ARG = os.environ.get('RUOLO', 'all').strip().lower()

# Gruppi granulari TRACCIATI per ruolo (copia esatta delle costanti GROUP_NAME
# in test_<ruolo>.py -- servono per calcolare il "residuo" usato dal fattore
# casa/trasferta, esattamente come fa la produzione: residuo = punteggio
# totale - somma di TUTTI questi gruppi, level_score resta nel residuo).
GRANULAR_GROUPS_BY_ROLE = {
    'gk': {
        'falli': ('fouls',),
        'possesso': ('poss_lost_ctrl',),
        'efficacia_offensiva': ('ontarget_scoring_att', 'big_chance_missed'),
        'passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls', 'missed_pass'),
        'gol_subiti': ('goals_conceded',),
        'goalkeeping': ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save',
                         'dive_catch', 'cross_not_claimed', 'six_second_violation',
                         'gk_smother', 'accurate_keeper_sweeper'),
    },
    'def': {
        'falli': ('fouls',),
        'duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'efficacia_offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls', 'long_pass_own_to_opp_success'),
        'difesa_rari': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                         'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
        'azioni_difensive': ('won_tackle', 'blocked_cross', 'outfielder_block'),
        'gol_subiti': ('goals_conceded',),
        'clean_sheet': ('clean_sheet_60', 'effective_clearance'),
    },
    'mid': {
        'falli': ('fouls', 'was_fouled'),
        'duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'efficacia_offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls'),
        'difesa_rari': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                         'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
        'azioni_difensive': ('won_tackle', 'blocked_cross', 'outfielder_block'),
        'gol_subiti': ('goals_conceded',),
    },
    'fwd': {
        'falli': ('fouls', 'was_fouled'),
        'duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'efficacia_offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist'),
        'difesa_rari': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                         'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
    },
}

# Quali sotto-categorie condiziona lo Stadio D in produzione OGGI, per ruolo,
# e per quale/i condizione/i (venue e/o avversario). 'level_score' e' un caso
# a parte (non e' uno dei gruppi granulari sopra).
STADIO_D_BY_ROLE = {
    'gk': {
        'level_score': ('avversario',),
        'gol_subiti': ('venue', 'avversario'),
        'possesso': ('venue',),
        'goalkeeping': ('venue',),
    },
    'def': {
        'gol_subiti': ('venue', 'avversario'),
        'passaggio': ('venue', 'avversario'),
        'clean_sheet': ('venue', 'avversario'),
    },
    'mid': {
        'level_score': ('venue',),
        'efficacia_offensiva': ('venue', 'avversario'),
        'passaggio': ('venue', 'avversario'),
        'gol_subiti': ('venue', 'avversario'),
    },
    'fwd': {
        'passaggio': ('venue',),
    },
}

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_player_series(entries, team_slug, groups):
    """Ritorna dict di liste parallele (stesso ordine cronologico dei nodi in
    cache) per un giocatore: score totale, is_home, opp_rank, level_score,
    e una lista per ciascun gruppo granulare tracciato per il ruolo."""
    scores, is_home_flags, opp_ranks, level_scores = [], [], [], []
    group_values = {g: [] for g in groups}

    for e in entries:
        g = e['anyGame']
        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
        if home.get('slug') == team_slug:
            is_home, opp_rank = True, away.get('domesticLeagueRanking')
        elif away.get('slug') == team_slug:
            is_home, opp_rank = False, home.get('domesticLeagueRanking')
        else:
            continue

        level_score_v = 0.0
        per_group = {gname: 0.0 for gname in groups}
        for stat_row in e['detailedScore']:
            stat = stat_row.get('stat')
            val = stat_row.get('totalScore', 0.0) or 0.0
            if stat == 'level_score':
                level_score_v += val
                continue
            for gname, stats in groups.items():
                if stat in stats:
                    per_group[gname] += val
                    break

        scores.append(e.get('score') or 0.0)
        is_home_flags.append(is_home)
        opp_ranks.append(opp_rank)
        level_scores.append(level_score_v)
        for gname in groups:
            group_values[gname].append(per_group[gname])

    return scores, is_home_flags, opp_ranks, level_scores, group_values


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    media_condizionata = mod.media_condizionata
    HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
    OPPONENT_SENSITIVITY = mod.OPPONENT_SENSITIVITY
    TREND_INTENSITY = mod.TREND_INTENSITY

    groups = GRANULAR_GROUPS_BY_ROLE[ruolo]
    stadio_d = STADIO_D_BY_ROLE[ruolo]

    cache_dir = f'formazione_mls/output/mls_{ruolo}_calibration/.cache'
    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))

    errori_baseline = []
    errori_stadio_d = []
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

        scores, is_home_flags, opp_ranks, level_scores, group_values = load_player_series(
            entries, team_slug, groups)
        n = len(scores)
        if n < MIN_HISTORY + 3:
            continue
        n_players_used += 1

        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            hist_opp = opp_ranks[:i]
            weights = exponential_weights(i, HALF_LIFE_GAMES)

            covered_total_hist = [
                sum(group_values[gname][j] for gname in groups) for j in range(i)
            ]
            residual_hist = [hist_scores[j] - covered_total_hist[j] for j in range(i)]

            media = weighted_mean(hist_scores, weights)
            target_is_home = is_home_flags[i]
            fattore_ct = compute_split_factor(residual_hist, hist_home, target_is_home)

            valid_ranks = [r for r in hist_opp if r is not None]
            avg_opp_hist = sum(valid_ranks) / len(valid_ranks) if valid_ranks else None
            target_opp_rank = opp_ranks[i]
            fattore_fa = 1.0
            if avg_opp_hist and target_opp_rank:
                delta = (target_opp_rank - avg_opp_hist) / OPPONENT_SENSITIVITY
                fattore_fa = max(0.5, min(1.5, 1.0 + delta))

            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

            baseline_pred = media * fattore_ct * fattore_fa * fattore_trend
            reale = scores[i]
            errore_baseline = reale - baseline_pred

            next_forte = (target_opp_rank < avg_opp_hist) if (
                target_opp_rank is not None and avg_opp_hist is not None) else None
            opponent_forte_flags_hist = [
                (r < avg_opp_hist) if (r is not None and avg_opp_hist is not None) else None
                for r in hist_opp
            ]

            stadio_d_delta = 0.0
            for subgroup_name, conditions in stadio_d.items():
                if subgroup_name == 'level_score':
                    values_hist = level_scores[:i]
                else:
                    values_hist = group_values[subgroup_name][:i]
                fallback = weighted_mean(values_hist, weights)
                if 'venue' in conditions:
                    cond = media_condizionata(values_hist, weights, hist_home, target_is_home, fallback)
                    stadio_d_delta += cond - fallback
                if 'avversario' in conditions:
                    cond = media_condizionata(values_hist, weights, opponent_forte_flags_hist, next_forte, fallback)
                    stadio_d_delta += cond - fallback

            pred_con_stadio_d = baseline_pred + stadio_d_delta
            errore_stadio_d = reale - pred_con_stadio_d

            errori_baseline.append(errore_baseline)
            errori_stadio_d.append(errore_stadio_d)
            n_test_points += 1

    if not errori_baseline:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return

    mae_baseline = statistics.mean(abs(e) for e in errori_baseline)
    mae_stadio_d = statistics.mean(abs(e) for e in errori_stadio_d)
    n_migliora = sum(1 for eb, ed in zip(errori_baseline, errori_stadio_d) if abs(ed) < abs(eb))
    n_peggiora = sum(1 for eb, ed in zip(errori_baseline, errori_stadio_d) if abs(ed) > abs(eb))
    n_uguale = n_test_points - n_migliora - n_peggiora
    pct_change = (mae_stadio_d - mae_baseline) / mae_baseline * 100

    print(f"\n=== {ruolo.upper()} ({n_players_used} giocatori, {n_test_points} punti di test walk-forward) ===")
    print(f"  MAE baseline (senza Stadio D):     {mae_baseline:.3f}")
    print(f"  MAE con Stadio D:                  {mae_stadio_d:.3f}")
    print(f"  Variazione: {pct_change:+.2f}%  {'MIGLIORA' if pct_change < 0 else 'PEGGIORA' if pct_change > 0 else 'INVARIATO'}")
    print(f"  Partite dove Stadio D migliora la predizione: {n_migliora} ({n_migliora/n_test_points*100:.1f}%)")
    print(f"  Partite dove Stadio D peggiora la predizione: {n_peggiora} ({n_peggiora/n_test_points*100:.1f}%)")
    print(f"  Partite invariate (delta=0, dato mancante):   {n_uguale} ({n_uguale/n_test_points*100:.1f}%)")


def main():
    ruoli = ('gk', 'def', 'mid', 'fwd') if RUOLO_ARG == 'all' else (RUOLO_ARG,)
    for ruolo in ruoli:
        run_role(ruolo)


if __name__ == '__main__':
    main()
