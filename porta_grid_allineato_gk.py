"""Porta il grid search ALLINEATO per GK dalle leghe In Season alle big5.

Contesto (01/08): su mls/kleague la calibrazione GK gira dal 31/07 sulla
formula REALE di produzione (compute_score_atteso_gk -> rigorous_backtest_
prod_gk). Sulle altre leghe gira ancora la vecchia `run_grid_search`, cioe'
una formula moltiplicativa diversa da quella che schiera: niente level_score
da tassi Poisson, niente shrinkage verso il prior di ruolo, e col fattore
ranking avversario che dalla produzione era stato RIMOSSO il 26/07. Distanza
misurata su MLS: 16.97 contro 15.757 di MAE, il 7%. Calibrare li' vuol dire
tarare le manopole su un modello che non e' quello in produzione.

Cosa fa questo script, per ogni lega target:
  1. copia da formazione_mls/predict/test_gk.py le costanti e le 4 funzioni
     del percorso allineato (nessuna riscrittura a mano: e' lo stesso codice,
     verificato identico riga per riga alla logica gia' inline nel file di
     destinazione);
  2. raccoglie in build_prediction lo slug avversario e la data di ogni
     partita storica -- senza, il backtest non potrebbe applicare
     opponent_lambda_mult e resterebbe disallineato (stesso pattern gia' in
     test_def.py dal 29/07);
  3. sposta il ramo CALIBRATION_MODE dal vecchio run_grid_search al nuovo
     run_grid_search_prod_gk.

NON tocca build_prediction nel calcolo dello score: la produzione resta
esattamente quella di prima (come su MLS, dove il blocco inline convive con
la funzione estratta). L'unica cosa che cambia e' cosa misura la
calibrazione.
"""
import re
import sys

SRC = 'formazione_mls/predict/test_gk.py'
LEGHE = ('francia', 'inghilterra', 'italia', 'belgio', 'spagna', 'germania')


def _estrai_def(src, nome):
    """Ritorna il sorgente della funzione top-level `nome` (fino al prossimo
    top-level)."""
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
        "# Portato da formazione_mls/predict/test_gk.py (audit 31/07). Serve SOLO\n"
        "# alla calibrazione: build_prediction resta invariata, la produzione non\n"
        "# cambia di una virgola. Prima di questo blocco CALIBRATION_MODE girava\n"
        "# la vecchia run_grid_search, cioe' una formula distante il 7% di MAE da\n"
        "# quella che schiera davvero -- si calibrava un modello diverso.\n",
        _estrai_costante(src, 'SPLIT_SHRINK_K_GK'),
        _estrai_costante(src, 'SHRINK_K_OUTLIER_GK'),
        _estrai_costante(src, 'MEDIA_RUOLO_GK_PRIOR'),
        '\n\n',
        _estrai_def(src, 'venue_factor_gk'), '\n',
        _estrai_def(src, 'compute_score_atteso_gk'), '\n',
        _estrai_def(src, 'rigorous_backtest_prod_gk'), '\n',
        _estrai_def(src, '_build_grid_combinations_prod'), '\n',
        'GRID_SEARCH_COMBINATIONS_PROD = _build_grid_combinations_prod()\n', '\n\n',
        _estrai_def(src, 'run_grid_search_prod_gk'), '\n',
    ]
    return ''.join(parti).replace("league='mls'", f"league='{lega}'")


ANCORA_BLOCCO = 'def _build_grid_combinations():'

RACCOLTA_INIT_OLD = "    own_rankings = []\n"
RACCOLTA_INIT_NEW = (
    "    own_rankings = []\n"
    "    opponent_team_slugs_hist = []  # (01/08) per il grid search allineato, vedi sotto\n"
    "    game_dates_hist = []\n"
)

RACCOLTA_APPEND_OLD = "        own_rankings.append(own_rank)\n"
RACCOLTA_APPEND_NEW = (
    "        own_rankings.append(own_rank)\n"
    "        # Slug/data dell'avversario per ogni partita storica (01/08): senza\n"
    "        # questi il grid search ALLINEATO non potrebbe applicare\n"
    "        # opponent_lambda_mult e resterebbe a misurare una formula diversa\n"
    "        # da quella di produzione. Stesso pattern gia' in test_def.py.\n"
    "        _g_home, _g_away = game.get('homeTeam') or {}, game.get('awayTeam') or {}\n"
    "        if _g_home.get('slug') == player_team_slug:\n"
    "            opponent_team_slugs_hist.append(_g_away.get('slug'))\n"
    "        elif _g_away.get('slug') == player_team_slug:\n"
    "            opponent_team_slugs_hist.append(_g_home.get('slug'))\n"
    "        else:\n"
    "            opponent_team_slugs_hist.append(None)\n"
    "        game_dates_hist.append(_game_dt(node))\n"
)

CHIAMATA_OLD = '''        log("CALIBRATION_MODE attivo: esecuzione grid search completo (72 combinazioni)...")
        grid_results = run_grid_search(scores, is_home_flags, opponent_rankings, min_history=6,
                                        possession_values=possession_values,
                                        passing_values=passing_values,
                                        goalkeeping_values=goalkeeping_values,
                                        goals_conceded_values=goals_conceded_values)
'''


def CHIAMATA_NEW(lega):
    return f'''        # ALLINEATO (01/08): prima girava run_grid_search, cioe' la vecchia
        # formula moltiplicativa, distante il 7% di MAE da quella reale.
        log(f"CALIBRATION_MODE attivo: grid search ALLINEATO "
            f"({{len(GRID_SEARCH_COMBINATIONS_PROD)}} combinazioni)...")
        grid_results = run_grid_search_prod_gk(
            scores, is_home_flags, granulari_values,
            pos_decisive_values, neg_decisive_values, min_history=6,
            opponent_team_slugs_hist=opponent_team_slugs_hist,
            game_dates_hist=game_dates_hist,
            presence_rate=presence_rate, league='{lega}')
'''


def porta(lega):
    path = f'formazione_{lega}/predict/test_gk.py'
    s = open(path, encoding='utf-8', newline='').read()
    crlf = '\r\n' in s
    if crlf:
        s = s.replace('\r\n', '\n')

    if 'run_grid_search_prod_gk' in s:
        print(f'{lega}: gia\' portato, salto.')
        return

    def sostituisci_una(testo, vecchio, nuovo, cosa):
        if testo.count(vecchio) != 1:
            raise SystemExit(f"{lega}: ancora '{cosa}' trovata {testo.count(vecchio)} volte, mi fermo.")
        return testo.replace(vecchio, nuovo, 1)

    s = sostituisci_una(s, ANCORA_BLOCCO, costruisci_blocco(lega) + '\n' + ANCORA_BLOCCO, 'blocco')
    s = sostituisci_una(s, RACCOLTA_INIT_OLD, RACCOLTA_INIT_NEW, 'init liste')
    s = sostituisci_una(s, RACCOLTA_APPEND_OLD, RACCOLTA_APPEND_NEW, 'append liste')
    s = sostituisci_una(s, CHIAMATA_OLD, CHIAMATA_NEW(lega), 'chiamata calibrazione')

    if crlf:
        s = s.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(s)
    print(f'{lega}: portato.')


if __name__ == '__main__':
    for lega in (sys.argv[1:] or LEGHE):
        porta(lega)
