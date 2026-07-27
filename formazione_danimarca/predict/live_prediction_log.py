"""
Live prediction log (26/07) -- monitoraggio MAE live per i 4 ruoli Superliga (Danimarca).

Modulo condiviso, importato da test_gk.py / test_def.py / test_mid.py /
test_mls_fwd_all.py. Puramente ADDITIVO: nessuna chiamata API aggiuntiva
(riusa solo dati gia' presenti nel `result` calcolato in produzione),
nessuna modifica alla formula di score_atteso, nessun impatto misurabile
sul runtime del job (una singola lettura+scrittura di un file JSON piccolo
per giocatore).

Motivazione: finora il modello viene validato SOLO con backtest walk-forward
su dati storici in cache (formazione_danimarca/diagnostics/validate_*.py). Non
c'e' nessun tracciamento di quanto le predizioni REALI di produzione (quelle
scritte nei file .txt in danimarca_<ruolo>_all/) si rivelino accurate una volta
giocata la partita. Questo modulo scrive, per ogni predizione generata IN
PRODUZIONE (mai in CALIBRATION_MODE -- quelle run non sono "live"), una
entry "pending" in prediction_log.json. Lo script separato
formazione_danimarca/diagnostics/resolve_live_predictions.py si occupa in seguito
di verificare (leggendo la cache gia' presente, zero chiamate API) se la
partita e' stata giocata, e in caso affermativo di calcolare l'errore reale
e spostare l'entry in prediction_log_resolved.json.

Uso (da ciascuno dei 4 script predict, SOLO se non CALIBRATION_MODE):

    from formazione_danimarca.predict.live_prediction_log import log_live_prediction
    log_live_prediction(OUTPUT_DIR, CALIBRATION_MODE, 'gk', result)
"""
import os
import json
import datetime


PREDICTION_LOG_FILENAME = 'prediction_log.json'


def _load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        # File corrotto o illeggibile: non blocchiamo mai la produzione per
        # via del logging diagnostico -- ripartiamo da un log vuoto.
        return {}


def log_live_prediction(output_dir, calibration_mode, role, result):
    """Scrive/aggiorna (UPSERT) una entry 'pending' nel prediction_log.json
    del ruolo, con la predizione appena generata per la prossima partita del
    giocatore. No-op in CALIBRATION_MODE (quelle run non sono predizioni
    live) e no-op se mancano i dati minimi necessari (next_game/score_atteso).

    Non solleva mai eccezioni verso il chiamante: un problema nel logging
    diagnostico non deve mai far fallire la generazione della predizione di
    produzione.
    """
    if calibration_mode:
        return
    try:
        next_game = result.get('next_game') or {}
        slug = result.get('player_slug')
        game_date = next_game.get('date')
        score_atteso = result.get('score_atteso')
        if not slug or not game_date or score_atteso is None:
            return

        home_team = next_game.get('homeTeam') or {}
        away_team = next_game.get('awayTeam') or {}

        key = f"{slug}|{game_date}"
        log_path = os.path.join(output_dir, PREDICTION_LOG_FILENAME)

        log_data = _load_json(log_path)
        log_data[key] = {
            'player_slug': slug,
            'role': role,
            'game_date': game_date,
            'home_team_slug': home_team.get('slug'),
            'home_team_name': home_team.get('name'),
            'away_team_slug': away_team.get('slug'),
            'away_team_name': away_team.get('name'),
            'score_atteso': score_atteso,
            'generated_at': datetime.datetime.utcnow().isoformat() + 'Z',
        }

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Diagnostica additiva: mai propagare un errore qui, la predizione
        # di produzione e' gia' stata calcolata e scritta correttamente.
        pass
