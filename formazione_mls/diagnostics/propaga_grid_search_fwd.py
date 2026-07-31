#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Propaga a tutte le leghe (tranne formazione_mls e formazione_resto_mondo)
la correzione del grid search FWD gia' applicata in
formazione_mls/predict/test_mls_fwd_all.py il 31/07 (audit): il
CALIBRATION_MODE girava su run_grid_search(), cioe' la vecchia formula
moltiplicativa, invece che sulla funzione condivisa di produzione
(compute_score_atteso_fwd via rigorous_backtest_prod_fwd/run_grid_search_prod_fwd).

CONTESTO IMPORTANTE (scoperto durante la scrittura di questo script): le
altre leghe erano gia' indietro rispetto a MLS PRIMA di questo fix, non solo
sul punto specifico del 31/07. In tutte le leghe (tranne MLS) la funzione
`rigorous_backtest_prod_fwd` non aveva ancora i parametri
`opponent_team_slugs_hist`/`league`/`offensive_values` che in MLS erano gia'
presenti da una propagazione precedente (30/07, vedi backlog
project_backlog_fwd_shared_function_solo_mls). Questo script quindi non fa
un patch incrementale di 5 piccole modifiche come inizialmente ipotizzato,
ma sostituisce l'intera funzione `rigorous_backtest_prod_fwd` (dalla riga
`def rigorous_backtest_prod_fwd` fino alla riga precedente `def
build_prediction`) con il testo attuale di MLS per quella stessa porzione
(che include gia' sia la propagazione del 30/07 sia il fix del 31/07),
adattando solo `league='mls'` -> `league='<lega>'` nei due punti dove serve
(default parametro di `rigorous_backtest_prod_fwd`/`run_grid_search_prod_fwd`
e call site dentro CALIBRATION_MODE). Le altre 4 modifiche (own_rankings,
loop di riempimento, call site) sono invece patch testuali puntuali perche'
il resto del file nelle altre leghe era gia' allineato a MLS pre-fix.

LIMITI: lo script si basa su ancore testuali esatte trovate nel file MLS di
riferimento (letto a runtime da questo stesso script, quindi va rilanciato
se MLS cambia ancora). Se un file lega non contiene le ancore attese, viene
SALTATO con un messaggio esplicito (mai una patch parziale silenziosa). Il
ramo `else:` (pipeline non-CALIBRATION) non viene mai toccato.

Uso:
    python formazione_mls/diagnostics/propaga_grid_search_fwd.py --dry-run
    python formazione_mls/diagnostics/propaga_grid_search_fwd.py
"""
import argparse
import glob
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
MLS_FILE = os.path.join(REPO_ROOT, 'formazione_mls', 'predict', 'test_mls_fwd_all.py')
EXCLUDED_LEAGUES = {'mls', 'resto_mondo'}


def league_slug_from_dir(dirpath):
    base = os.path.basename(dirpath)
    assert base.startswith('formazione_')
    return base[len('formazione_'):]


def extract_mls_block(mls_text):
    """Estrae da MLS il blocco 'def rigorous_backtest_prod_fwd' fino a (escluso)
    'def build_prediction', da usare come sostituzione per le altre leghe."""
    start_marker = "def rigorous_backtest_prod_fwd(scores, is_home_flags,"
    end_marker = "\ndef build_prediction(player_slug):"
    start = mls_text.index(start_marker)
    end = mls_text.index(end_marker, start)
    return mls_text[start:end]


def extract_own_rankings_addition(mls_text):
    """Estrae dal build_prediction di MLS il blocco delle due nuove liste
    dichiarate subito dopo `own_rankings = []`."""
    anchor = "    own_rankings = []\n"
    idx = mls_text.index(anchor)
    after = mls_text[idx + len(anchor):]
    # Le due righe nuove finiscono prima di 'fouls_values = []'
    end = after.index("    fouls_values = []")
    addition = after[:end]
    assert 'opponent_team_slugs_hist = []' in addition
    assert 'game_dates_hist = []' in addition
    return addition


def extract_loop_addition(mls_text):
    """Estrae dal loop di MLS il blocco di riempimento delle due liste,
    inserito subito dopo `own_rankings.append(own_rank)`."""
    anchor = "        own_rankings.append(own_rank)\n"
    idx = mls_text.index(anchor)
    after = mls_text[idx + len(anchor):]
    end = after.index("        fouls_v = extract_group_score(detail, FOULS_STATS)")
    addition = after[:end]
    assert 'opponent_team_slugs_hist.append' in addition
    assert 'game_dates_hist.append(_game_dt(node))' in addition
    return addition


def extract_calibration_block(mls_text):
    """Estrae il blocco `if CALIBRATION_MODE: ... rigorous_bt = grid_results[0]
    if grid_results else None` di MLS (call site nuovo), per sostituire quello
    vecchio (basato su run_grid_search) nelle altre leghe."""
    start_anchor = "    if CALIBRATION_MODE:\n"
    idx = mls_text.index(start_anchor)
    end_anchor = "        rigorous_bt = grid_results[0] if grid_results else None\n"
    end_idx = mls_text.index(end_anchor, idx) + len(end_anchor)
    block = mls_text[idx:end_idx]
    assert 'run_grid_search_prod_fwd(' in block
    return block


OLD_CALIBRATION_BLOCK = '''    if CALIBRATION_MODE:
        log("CALIBRATION_MODE attivo: esecuzione grid search completo (72 combinazioni)...")
        grid_results = run_grid_search(scores, is_home_flags, opponent_rankings, min_history=6,
                                        fouls_values=fouls_values, duels_values=duels_values,
                                        offensive_values=offensive_values,
                                        passing_values=passing_values,
                                        defense_rare_values=defense_rare_values,
                                        residual_values=residual_values)
        rigorous_bt = grid_results[0] if grid_results else None
'''


def process_file(path, league, mls_block, own_rankings_addition, loop_addition,
                  new_calibration_block_template, dry_run):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    original_text = text
    problems = []

    # --- 1/2/3/4: sostituisci l'intera funzione rigorous_backtest_prod_fwd
    # (comprende i 3 nuovi elementi di modulo: _build_grid_combinations_prod,
    # GRID_SEARCH_COMBINATIONS_PROD, run_grid_search_prod_fwd) ---
    start_marker = "def rigorous_backtest_prod_fwd(scores, is_home_flags,"
    end_marker = "\ndef build_prediction(player_slug):"
    if start_marker not in text:
        problems.append("manca 'def rigorous_backtest_prod_fwd(scores, is_home_flags,'")
    if end_marker not in text:
        problems.append("manca 'def build_prediction(player_slug):'")
    if problems:
        return False, problems

    start = text.index(start_marker)
    end = text.index(end_marker, start)
    old_block = text[start:end]

    league_block = mls_block.replace("league='mls'", "league='%s'" % league)
    if old_block != league_block:
        text = text[:start] + league_block + text[end:]

    # --- own_rankings = [] -> aggiungi le due liste nuove ---
    anchor = "    own_rankings = []\n"
    if anchor not in text:
        problems.append("manca l'ancora 'own_rankings = []'")
    else:
        if 'opponent_team_slugs_hist = []' not in text:
            text = text.replace(anchor, anchor + own_rankings_addition, 1)

    # --- own_rankings.append(own_rank) -> aggiungi il blocco di riempimento ---
    loop_anchor = "        own_rankings.append(own_rank)\n"
    if loop_anchor not in text:
        problems.append("manca l'ancora 'own_rankings.append(own_rank)'")
    else:
        if 'opponent_team_slugs_hist.append' not in text.split(loop_anchor, 1)[1][:1000]:
            text = text.replace(loop_anchor, loop_anchor + loop_addition, 1)

    # --- 5: call site dentro CALIBRATION_MODE ---
    if OLD_CALIBRATION_BLOCK in text:
        new_block = new_calibration_block_template.replace("league='mls'", "league='%s'" % league)
        text = text.replace(OLD_CALIBRATION_BLOCK, new_block, 1)
    elif 'run_grid_search_prod_fwd(' in text:
        pass  # gia' applicato (idempotenza)
    else:
        problems.append("non trovato ne' il vecchio blocco CALIBRATION_MODE atteso ne' run_grid_search_prod_fwd gia' presente")

    if problems:
        return False, problems

    if text == original_text:
        return True, ["nessuna modifica necessaria (gia' allineato)"]

    if not dry_run:
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)

    return True, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with open(MLS_FILE, 'r', encoding='utf-8') as f:
        mls_text = f.read()

    mls_block = extract_mls_block(mls_text)
    own_rankings_addition = extract_own_rankings_addition(mls_text)
    loop_addition = extract_loop_addition(mls_text)
    calibration_block = extract_calibration_block(mls_text)

    targets = sorted(glob.glob(os.path.join(REPO_ROOT, 'formazione_*', 'predict', 'test_mls_fwd_all.py')))

    n_ok = 0
    n_skip = 0
    for path in targets:
        league_dir = os.path.dirname(os.path.dirname(path))
        league = league_slug_from_dir(league_dir)
        if league in EXCLUDED_LEAGUES:
            print("SKIP  (escluso di proposito) formazione_%s" % league)
            continue
        ok, problems = process_file(path, league, mls_block, own_rankings_addition,
                                     loop_addition, calibration_block, args.dry_run)
        if ok:
            n_ok += 1
            tag = "DRY-OK" if args.dry_run else "OK"
            extra = (" (%s)" % "; ".join(problems)) if problems else ""
            print("%-7s formazione_%s%s" % (tag, league, extra))
        else:
            n_skip += 1
            print("FAIL  formazione_%s: %s" % (league, "; ".join(problems)))

    print()
    print("Totale: %d ok, %d falliti/saltati (esclusi mls/resto_mondo)" % (n_ok, n_skip))
    if n_skip:
        sys.exit(1)


if __name__ == '__main__':
    main()
