"""
Inspect Granular Weights (26/07/2026)

Diagnostico locale (nessuna query API, legge solo le cache .cache/*_detail_cache.json
gia' scaricate dai run di calibrazione) per rispondere alla domanda: "quanto pesa
davvero ogni categoria granulare sul punteggio totale di una partita, per un
ruolo?" -- invece di leggere schermate Sorare a mano partita per partita.

Scoperta motivante (26/07, analizzando a mano il caso Andre Blake): il campo
'level_score' (category=UNKNOWN nel detailedScore) spesso vale l'80-95% del
punteggio totale di un portiere, ma non e' incluso in NESSUNO dei 7 gruppi
granulari tracciati in test_gk.py (FOULS/POSSESSION/OFFENSIVE/PASSING/
RARE_EVENTS/GOALS_CONCEDED/GOALKEEPING) -- finisce sempre nel "residuo".
Questo script verifica se il pattern e' sistematico (su TUTTE le partite in
cache) o solo un caso isolato, e quanto pesano gli altri gruppi TRA LORO.

NOTA IMPORTANTE (26/07, segnalata dall'utente): 'level_score' NON e' un
valore continuo puramente legato alla prestazione -- ha una base FISSA di
35 assegnata a qualunque giocatore che scenda in campo anche un solo
secondo (poi sale, es. ~60 per un portiere con clean sheet, secondo il
commento gia' presente in test_gk.py). Questo significa che il peso
41-63% misurato qui sotto e' gonfiato da questa componente fissa di
partecipazione, che NON e' predicibile ne' condizionabile (o quasi) da
venue/avversario -- la vera leva predittiva sfruttabile su level_score e'
piu' piccola della percentuale grezza, probabilmente riconducibile a poche
soglie discrete (ha giocato / clean sheet o simili), non un continuo. Da
tenere presente prima di investire tempo nel modellarlo: verificare prima
quanto della VARIANZA di level_score (non solo la sua magnitudine media)
e' davvero spiegabile da fattori conosciuti, sottraendo la base fissa.

Uso: RUOLO=gk python formazione_mls/diagnostics/inspect_granular_weights.py
Legge da formazione_mls/output/mls_<ruolo>_calibration/.cache/*_detail_cache.json
(committati nel repo dai run di calibrazione -- nessun nuovo dato scaricato).

NOTA: i gruppi qui sotto sono una COPIA dei tuple GROUP_NAME = (...) definiti in
test_<ruolo>.py -- se quei file cambiano, aggiornare anche qui (duplicazione
accettata per non importare uno script pesante con effetti collaterali a
livello di modulo solo per leggere 4 costanti).
"""
import os
import json
import glob
from collections import defaultdict

RUOLO = os.environ.get('RUOLO', 'gk').strip().lower()
CACHE_DIR = f'formazione_mls/output/mls_{RUOLO}_calibration/.cache'

# 27/07 (sessione estensione campionati): esteso da MLS-only a tutti i
# campionati con cache disponibile -- stesso principio delle altre analisi
# estese in questa sessione (measure_teammate_correlation.py/
# validate_level_score_event_rate.py). CACHE_DIR sopra resta per
# retrocompatibilita' (RUOLO singolo, uso diretto), CACHE_DIRS sotto e'
# usato da main() per l'analisi multi-campionato.
LEAGUE_CACHE_TPL = {
    'mls': 'formazione_mls/output/mls_{ruolo}_calibration/.cache',
    'kleague': 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache',
    'brasile': 'formazione_brasile/output/brasile_{ruolo}_all/.cache',
    'croazia': 'formazione_croazia/output/croazia_{ruolo}_all/.cache',
    'portogallo': 'formazione_portogallo/output/portogallo_{ruolo}_all/.cache',
    'austria': 'formazione_austria/output/austria_{ruolo}_all/.cache',
    'scozia': 'formazione_scozia/output/scozia_{ruolo}_all/.cache',
    'belgio': 'formazione_belgio/output/belgio_{ruolo}_all/.cache',
    'olanda': 'formazione_olanda/output/olanda_{ruolo}_all/.cache',
    'spagna': 'formazione_spagna/output/spagna_{ruolo}_all/.cache',
}

# Gruppi per ruolo, copiati da test_<ruolo>.py (26/07/2026).
GROUPS_BY_ROLE = {
    'gk': {
        'Falli': ('fouls',),
        'Possesso': ('poss_lost_ctrl',),
        'Efficacia offensiva': ('ontarget_scoring_att', 'big_chance_missed'),
        'Passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls', 'missed_pass'),
        'Eventi rari': ('penalty_won', 'penalty_conceded', 'own_goals', 'error_lead_to_goal'),
        'Gol subiti': ('goals_conceded',),
        'Goalkeeping (8 voci)': ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save',
                                  'dive_catch', 'cross_not_claimed', 'six_second_violation',
                                  'gk_smother', 'accurate_keeper_sweeper'),
    },
    'def': {
        'Falli': ('fouls',),
        'Duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'Efficacia offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'Passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls', 'long_pass_own_to_opp_success'),
        'Eventi rari': ('penalty_won', 'penalty_conceded', 'own_goals', 'error_lead_to_goal'),
        'Difesa/eventi rarissimi': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                                     'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
        'Azioni difensive': ('won_tackle', 'blocked_cross', 'outfielder_block'),
        'Gol subiti': ('goals_conceded',),
        'Clean sheet/disimpegni': ('clean_sheet_60', 'effective_clearance'),
    },
    'mid': {
        'Falli': ('fouls', 'was_fouled'),
        'Duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'Efficacia offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'Passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                       'accurate_long_balls'),
        'Eventi rari': ('penalty_won', 'penalty_conceded', 'own_goals', 'error_lead_to_goal'),
        'Difesa/eventi rarissimi': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                                     'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
        'Azioni difensive': ('won_tackle', 'blocked_cross', 'outfielder_block'),
        'Gol subiti': ('goals_conceded',),
    },
    'fwd': {
        'Falli': ('fouls', 'was_fouled'),
        'Duelli': ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won'),
        'Efficacia offensiva': ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                                 'pen_area_entries', 'won_contest'),
        'Passaggio': ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist'),
        'Eventi rari': ('penalty_won', 'penalty_conceded', 'own_goals', 'error_lead_to_goal'),
        'Difesa/eventi rarissimi': ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                                     'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won'),
    },
}

GROUPS = GROUPS_BY_ROLE.get(RUOLO)
if GROUPS is None:
    raise SystemExit(f"Gruppi non definiti per il ruolo '{RUOLO}' in questo script "
                      f"(disponibili: {', '.join(GROUPS_BY_ROLE)}).")

ALL_TRACKED_STATS = {s for stats in GROUPS.values() for s in stats}


def analyze_game(detailed_score):
    """Ritorna, per una singola partita, il valore ASSOLUTO di ogni riga dello
    stat sommato per gruppo/level_score/non-tracciato -- sommare valori
    assoluti a livello di singola statistica (non di gruppo netto) evita che
    due stat con segno opposto nello stesso gruppo si cancellino a vicenda
    prima di misurarne il peso, ed e' l'unico modo per far tornare la somma
    dei sotto-pesi con il totale (denominatore comune, sommato UNA volta)."""
    per_group_abs = defaultdict(float)
    level_score_abs = 0.0
    other_untracked_abs = 0.0
    denominator = 0.0

    for row in detailed_score:
        stat = row.get('stat')
        val = abs(row.get('totalScore', 0.0) or 0.0)
        denominator += val
        if stat == 'level_score':
            level_score_abs += val
            continue
        matched = False
        for group_name, stats in GROUPS.items():
            if stat in stats:
                per_group_abs[group_name] += val
                matched = True
                break
        if not matched:
            other_untracked_abs += val

    return {'per_group_abs': dict(per_group_abs), 'level_score_abs': level_score_abs,
            'altro_non_tracciato_abs': other_untracked_abs, 'denominatore': denominator}


def main():
    files = []
    for tpl in LEAGUE_CACHE_TPL.values():
        cache_dir = tpl.format(ruolo=RUOLO)
        files.extend(glob.glob(os.path.join(cache_dir, '*_detail_cache.json')))
    if not files:
        print(f"Nessuna cache trovata per ruolo '{RUOLO}' in nessun campionato noto.")
        return

    n_players = 0
    n_games = 0
    sum_denominator = 0.0
    sum_level_score = 0.0
    sum_untracked_other = 0.0
    sum_per_group = defaultdict(float)
    level_score_share_per_game = []

    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        n_players += 1
        for entry in cache.values():
            detail = entry.get('detailedScore')
            if not detail:
                continue
            n_games += 1
            r = analyze_game(detail)
            if r['denominatore'] == 0:
                continue

            sum_denominator += r['denominatore']
            sum_level_score += r['level_score_abs']
            sum_untracked_other += r['altro_non_tracciato_abs']
            for g, v in r['per_group_abs'].items():
                sum_per_group[g] += v

            level_score_share_per_game.append(r['level_score_abs'] / r['denominatore'])

    print(f"Ruolo: {RUOLO} | Giocatori con cache: {n_players} | Partite analizzate: {n_games}")
    sum_tracked = sum(sum_per_group.values())
    print(f"\n=== QUOTA MEDIA SUL MOVIMENTO ASSOLUTO TOTALE DEL PUNTEGGIO (somma = 100%) ===")
    print(f"level_score (NON tracciato da nessun gruppo granulare): "
          f"{sum_level_score / sum_denominator * 100:5.1f}%")
    print(f"Somma dei 7 gruppi granulari tracciati:                 "
          f"{sum_tracked / sum_denominator * 100:5.1f}%")
    if sum_untracked_other > 0:
        print(f"Altro non tracciato (fuori da level_score e gruppi):    "
              f"{sum_untracked_other / sum_denominator * 100:5.1f}%")

    print(f"\n=== DETTAGLIO DEI 7 GRUPPI GRANULARI (quota sul totale generale, non solo sulla loro fetta) ===")
    for g in sorted(sum_per_group, key=lambda k: -sum_per_group[k]):
        print(f"{g:25s} {sum_per_group[g] / sum_denominator * 100:5.1f}%")

    if level_score_share_per_game:
        import statistics
        print(f"\nQuota di level_score per singola partita: media {statistics.mean(level_score_share_per_game)*100:.1f}%, "
              f"mediana {statistics.median(level_score_share_per_game)*100:.1f}%, "
              f"min {min(level_score_share_per_game)*100:.1f}%, max {max(level_score_share_per_game)*100:.1f}%")


if __name__ == '__main__':
    main()
