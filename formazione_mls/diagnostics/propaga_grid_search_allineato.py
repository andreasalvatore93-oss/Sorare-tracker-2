"""Propaga alle altre leghe il cablaggio del grid search ALLINEATO (31/07).

Contesto (audit del 31/07): la calibrazione girava sulla vecchia formula
moltiplicativa invece che su compute_score_atteso_<ruolo>, cioe' su un
modello distante il 7% di MAE da quello che schiera davvero. Su MLS e'
stato corretto per tutti e 4 i ruoli; qui si propaga alle altre leghe.

SCOPE (limite noto, dichiarato): si propaga solo DEF, l'unico ruolo dove
tutte le leghe hanno GIA' sia la funzione condivisa compute_score_atteso_def
sia rigorous_backtest_prod_def/run_grid_search_prod_def -- manca solo il
cablaggio in CALIBRATION_MODE. Per GK e MID la funzione condivisa esiste
SOLO su MLS (debito noto, le altre 27 leghe hanno la formula inline
duplicata): propagare li' richiede prima l'estrazione della funzione
condivisa, refactor separato. FWD ha le funzioni ovunque ma non ha gli
array opponent_team_slugs_hist/game_dates_hist, che vanno aggiunti prima.

Il nome della lega viene passato correttamente a opponent_strength (ogni
file usa il proprio, non 'mls').

Uso: python formazione_mls/diagnostics/propaga_grid_search_allineato.py [--dry-run]
"""
import os
import re
import sys
import glob

DRY = '--dry-run' in sys.argv

VECCHIA_CHIAMATA = re.compile(
    r'( *)log\("CALIBRATION_MODE attivo: esecuzione grid search completo \(72 combinazioni\)\.\.\."\)\n'
    r'( *)grid_results = run_grid_search\(scores, is_home_flags, opponent_rankings, min_history=6,\n'
    r'(?:.*\n)*?.*residual_values=residual_values\)\n')


def nuova_chiamata(indent, lega):
    return (
        f'{indent}# ALLINEATO (31/07, audit): prima girava run_grid_search, cioe\' la\n'
        f'{indent}# vecchia formula moltiplicativa (media pesata x fattore casa x\n'
        f'{indent}# fattore ranking avversario x trend), senza level_score da tassi\n'
        f'{indent}# Poisson, senza shrinkage verso il prior di ruolo e col fattore\n'
        f'{indent}# ranking che dalla produzione era stato rimosso il 26/07 --\n'
        f'{indent}# si calibrava un modello diverso da quello che schiera.\n'
        f'{indent}log(f"CALIBRATION_MODE attivo: grid search ALLINEATO "\n'
        f'{indent}    f"{{len(GRID_SEARCH_COMBINATIONS_PROD)}} combinazioni)...")\n'
        f'{indent}grid_results = run_grid_search_prod_def(\n'
        f'{indent}    scores, is_home_flags, opponent_rankings,\n'
        f'{indent}    residual_values, granulari_values,\n'
        f'{indent}    pos_decisive_values, neg_decisive_values,\n'
        f'{indent}    goals_conceded_values, passing_values, clean_sheet_values,\n'
        f'{indent}    min_history=6,\n'
        f'{indent}    opponent_team_slugs_hist=opponent_team_slugs_hist,\n'
        f'{indent}    game_dates_hist=game_dates_hist, league={lega!r},\n'
        f'{indent}    presence_rate=presence_rate)\n')


PATCH_PRESENCE = [
    # (cerca, sostituisci) -- aggiungono presence_rate alla catena backtest/grid,
    # come gia' fatto a mano su MLS.
    ("                               opponent_team_slugs_hist=None, game_dates_hist=None, league='mls'):",
     "                               opponent_team_slugs_hist=None, game_dates_hist=None, league='mls',\n"
     "                               presence_rate=None):"),
    ("            next_game_date=game_dates_hist[i] if game_dates_hist else None,\n            league=league)",
     "            next_game_date=game_dates_hist[i] if game_dates_hist else None,\n"
     "            presence_rate=presence_rate,\n            league=league)"),
    ("                             min_history=6,\n                             opponent_team_slugs_hist=None, game_dates_hist=None, league='mls'):",
     "                             min_history=6,\n"
     "                             opponent_team_slugs_hist=None, game_dates_hist=None, league='mls',\n"
     "                             presence_rate=None):"),
    ("            opponent_team_slugs_hist=opponent_team_slugs_hist,\n            game_dates_hist=game_dates_hist, league=league)\n        bt.update(",
     "            opponent_team_slugs_hist=opponent_team_slugs_hist,\n"
     "            game_dates_hist=game_dates_hist, league=league,\n"
     "            presence_rate=presence_rate)\n        bt.update("),
]


def main():
    fatti, saltati = [], []
    for path in sorted(glob.glob('formazione_*/predict/test_def.py')):
        lega = path.split('formazione_', 1)[1].split(os.sep)[0].split('/')[0]
        if lega in ('mls', 'resto_mondo'):
            saltati.append((lega, 'gia\' fatto a mano' if lega == 'mls' else 'pipeline legacy esclusa'))
            continue
        testo = open(path, encoding='utf-8').read()
        if 'run_grid_search_prod_def(' not in testo:
            saltati.append((lega, 'run_grid_search_prod_def assente'))
            continue
        if 'grid_results = run_grid_search_prod_def' in testo:
            saltati.append((lega, 'gia\' cablato'))
            continue
        originale = testo
        for cerca, sost in PATCH_PRESENCE:
            if cerca in testo:
                testo = testo.replace(cerca, sost, 1)
        m = VECCHIA_CHIAMATA.search(testo)
        if not m:
            saltati.append((lega, 'call site non riconosciuto'))
            continue
        testo = testo[:m.start()] + nuova_chiamata(m.group(1), lega) + testo[m.end():]
        if testo == originale:
            saltati.append((lega, 'nessun cambiamento'))
            continue
        if not DRY:
            open(path, 'w', encoding='utf-8').write(testo)
        fatti.append(lega)

    print(f"{'[DRY RUN] ' if DRY else ''}Cablati: {len(fatti)}")
    print('  ' + ', '.join(fatti))
    print(f"\nSaltati: {len(saltati)}")
    for lega, motivo in saltati:
        print(f"  {lega}: {motivo}")


if __name__ == '__main__':
    main()
