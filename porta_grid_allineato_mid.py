"""Porta il grid search ALLINEATO per MID dalle leghe In Season alle big5.

Gemello di porta_grid_allineato_gk.py, stesso motivo (vedi il docstring
la'): sulle leghe diverse da mls/kleague la calibrazione MID girava ancora
la vecchia `run_grid_search`, cioe' una formula diversa da quella di
produzione.

Piu' semplice del caso GK: opponent_team_slugs_hist/game_dates_hist esistono
gia' in build_prediction dal 29/07 (servono a Stadio D), quindi qui basta
aggiungere il blocco di funzioni e spostare il ramo CALIBRATION_MODE.

build_prediction non viene toccata: la produzione resta identica.
"""
import re
import sys

SRC = 'formazione_mls/predict/test_mid.py'
LEGHE = ('francia', 'inghilterra', 'italia', 'belgio', 'spagna', 'germania')


def _estrai_def(src, nome):
    m = re.search(rf'^def {re.escape(nome)}\(.*?(?=^\S)', src, re.S | re.M)
    if not m:
        raise SystemExit(f"funzione {nome} non trovata in {SRC}")
    return m.group(0).rstrip() + '\n'


def _estrai_costante(src, nome):
    m = re.search(rf'^{re.escape(nome)} = .*$', src, re.M)
    if not m:
        raise SystemExit(f"costante {nome} non trovata in {SRC}")
    return m.group(0) + '\n'


def costruisci_blocco(lega):
    src = open(SRC, encoding='utf-8').read()
    parti = [
        "# --- Percorso di calibrazione ALLINEATO ALLA PRODUZIONE (01/08) ---\n"
        "# Portato da formazione_mls/predict/test_mid.py. Serve SOLO alla\n"
        "# calibrazione: build_prediction resta invariata, la produzione non\n"
        "# cambia. Prima CALIBRATION_MODE girava la vecchia run_grid_search,\n"
        "# cioe' una formula diversa da quella che schiera davvero.\n",
        _estrai_costante(src, 'SHRINK_K_OUTLIER_MID'),
        _estrai_costante(src, 'MEDIA_RUOLO_MID_PRIOR'),
        '\n\n',
        _estrai_def(src, 'compute_score_atteso_mid'), '\n',
        _estrai_def(src, 'rigorous_backtest_prod_mid'), '\n',
        _estrai_def(src, '_build_grid_combinations_prod'), '\n',
        'GRID_SEARCH_COMBINATIONS_PROD = _build_grid_combinations_prod()\n', '\n\n',
        _estrai_def(src, 'run_grid_search_prod_mid'), '\n',
    ]
    return ''.join(parti).replace("league='mls'", f"league='{lega}'")


ANCORA_BLOCCO = 'def _build_grid_combinations():'

CHIAMATA_OLD = '''        log("CALIBRATION_MODE attivo: esecuzione grid search completo (72 combinazioni)...")
        grid_results = run_grid_search(scores, is_home_flags, opponent_rankings, min_history=6,
                                        fouls_values=fouls_values, duels_values=duels_values,
                                        offensive_values=offensive_values,
                                        passing_values=passing_values,
                                        defense_rare_values=defense_rare_values,
                                        defensive_actions_values=defensive_actions_values,
                                        goals_conceded_values=goals_conceded_values,
                                        residual_values=residual_values)
'''


def CHIAMATA_NEW(lega):
    return f'''        # ALLINEATO (01/08): prima girava run_grid_search, cioe' la vecchia
        # formula, diversa da quella reale di produzione.
        log(f"CALIBRATION_MODE attivo: grid search ALLINEATO "
            f"({{len(GRID_SEARCH_COMBINATIONS_PROD)}} combinazioni)...")
        grid_results = run_grid_search_prod_mid(
            scores, is_home_flags, opponent_rankings,
            residual_values, granulari_values,
            pos_decisive_values, neg_decisive_values,
            offensive_values, passing_values, goals_conceded_values,
            min_history=6,
            opponent_team_slugs_hist=opponent_team_slugs_hist,
            game_dates_hist=game_dates_hist,
            presence_rate=presence_rate, league='{lega}')
'''


def porta(lega):
    path = f'formazione_{lega}/predict/test_mid.py'
    s = open(path, encoding='utf-8', newline='').read()
    crlf = '\r\n' in s
    if crlf:
        s = s.replace('\r\n', '\n')

    if 'run_grid_search_prod_mid' in s:
        print(f"{lega}: gia' portato, salto.")
        return

    for cosa, vecchio in (('blocco', ANCORA_BLOCCO), ('chiamata', CHIAMATA_OLD)):
        if s.count(vecchio) != 1:
            raise SystemExit(f"{lega}: ancora '{cosa}' trovata {s.count(vecchio)} volte, mi fermo.")

    s = s.replace(ANCORA_BLOCCO, costruisci_blocco(lega) + '\n' + ANCORA_BLOCCO, 1)
    s = s.replace(CHIAMATA_OLD, CHIAMATA_NEW(lega), 1)

    if crlf:
        s = s.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(s)
    print(f'{lega}: portato.')


if __name__ == '__main__':
    for lega in (sys.argv[1:] or LEGHE):
        porta(lega)
