"""
opponent_strength.py -- Aggiustamento forza avversario su level_score_atteso
(29/07, richiesta esplicita utente).

Sostituisce il vecchio 'fattore_forza_avversario' (basato su
domesticLeagueRanking, scoperto contaminato: e' un attributo CORRENTE della
squadra lato Sorare, non un valore storico ancorato alla data della
partita -- vedi RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md). Qui si usa
invece un dato genuinamente storico e immutabile: i gol subiti/fatti da una
squadra in una partita GIA' GIOCATA, presi da 'goals_conceded' nel
detailedScore (stessa riga per ogni giocatore che ha giocato quella
partita).

Validato con backtest walk-forward rigoroso (formazione_mls/diagnostics/
validate_opponent_conceded_level*.py), media ultime 10 partite
dell'avversario, sensibilita' per ruolo:
  FWD: sens=1.0 (gol SUBITI dall'avversario)  -> -0.58% MAE
  MID: sens=0.7 (gol SUBITI dall'avversario)  -> -0.29% MAE
  DEF: sens=1.0 (gol SUBITI dall'avversario)  -> -0.27% MAE
  GK:  sens=1.0 (gol FATTI dall'avversario, segno invertito) -> -0.59% MAE
Altri segnali testati e SCARTATI (nessun miglioramento reale): trend
corta/lunga avversario, volume offensivo, rigori vinti, possesso (proxy
poss_lost_ctrl) -- vedi gli stessi diagnostics per il dettaglio.

Nessuna query nuova: lo storico si ricostruisce dalle cache GK+DEF+MID gia'
scaricate (stesso identico dato, stesso meccanismo del backtest -- copertura
tipica 72-93%). Se il dato manca per l'avversario di turno, nessun
aggiustamento (fallback sicuro, comportamento INVARIATO in quel caso).
"""
import os
import glob
import json
import datetime
from collections import defaultdict

N_GAMES_DEFAULT = 10
SENSITIVITY_BY_ROLE = {'gk': 1.0, 'def': 1.0, 'mid': 0.7, 'fwd': 1.0}
# Media/std GLOBALI FISSE (29/07), prese dal backtest di validazione pooled
# su 16 campionati (formazione_mls/diagnostics/validate_opponent_conceded_
# level_allroles.py): la sensibilita' sopra e' stata calibrata usando
# QUESTA normalizzazione, non una per-lega -- ricalcolarla per singola lega
# ad ogni run cambierebbe lo z-score e invaliderebbe la sensibilita' gia'
# validata. Fisse invece che ricalcolate ad ogni run: piu' stabili (non
# oscillano se cambia la cache disponibile) e zero costo aggiuntivo.
GLOBAL_MEAN_CONCEDED = 1.29
GLOBAL_STD_CONCEDED = 1.17
# segno: +1 = usa gol SUBITI dall'avversario (piu' concede -> piu' probabile
# un evento decisivo positivo per il nostro giocatore); -1 = usa gol FATTI
# dall'avversario con effetto invertito (GK: piu' forte l'attacco avversario
# -> MENO probabile il clean sheet).
SIGN_BY_ROLE = {'gk': -1, 'def': 1, 'mid': 1, 'fwd': 1}

_CACHE = {}  # league -> (conceded_series, scored_series, global_mean, global_std), calcolato una volta per run


def _parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        # .replace(tzinfo=None): i chiamanti confrontano con
        # datetime.datetime.utcnow() (naive) -- stesso pattern gia' usato
        # altrove nel repo (es. _game_dt in build_prediction). Senza questo,
        # il confronto aware-vs-naive solleva TypeError (bug reale trovato
        # in fase di test, mai arrivato in produzione).
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _player_team_slug(games):
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def _build_series_for_league(league):
    """Ricostruisce (conceded, scored) per la lega indicata, scansionando le
    cache GK+DEF+MID gia' su disco (produzione '_all'). Cachato in memoria
    per la durata del processo (chiamato una volta per giocatore/run, non
    per partita). Media/std per la normalizzazione NON sono qui -- vedi
    GLOBAL_MEAN_CONCEDED/GLOBAL_STD_CONCEDED (fisse, dal backtest)."""
    if league in _CACHE:
        return _CACHE[league]

    seen = set()
    conceded = defaultdict(list)
    scored = defaultdict(list)
    patterns = [
        f'formazione_{league}/output/{league}_gk_all/.cache',
        f'formazione_{league}/output/{league}_def_all/.cache',
        f'formazione_{league}/output/{league}_mid_all/.cache',
    ]
    for cache_dir in patterns:
        for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
            try:
                with open(fpath, encoding='utf-8') as f:
                    cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not cache:
                continue
            entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
            if not entries:
                continue
            team_slug = _player_team_slug([e['anyGame'] for e in entries])
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
                dt = _parse_date(g)
                if dt is None or not opp_slug:
                    continue
                key = (team_slug, opp_slug, dt.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                gc = None
                for row in e['detailedScore']:
                    if row.get('stat') == 'goals_conceded':
                        gc = row.get('statValue', 0.0) or 0.0
                        break
                if gc is None:
                    continue
                conceded[team_slug].append((dt, gc))
                scored[opp_slug].append((dt, gc))
    for d in (conceded, scored):
        for t in d:
            d[t].sort(key=lambda x: x[0])

    result = (conceded, scored)
    _CACHE[league] = result
    return result


def opponent_lambda_multiplier(league, role, opponent_team_slug, cutoff_dt, n_games=N_GAMES_DEFAULT):
    """Ritorna il moltiplicatore da applicare a lambda_pos (ruoli con
    sign=+1) o lambda_neg... in realta' SEMPRE a lambda_pos (per costruzione
    del test, vedi SIGN_BY_ROLE: anche per GK il segno negativo si applica a
    lambda_pos, rendendolo piu' basso quando l'avversario segna tanto) --
    1.0 se il dato non e' disponibile (fallback sicuro, nessun aggiustamento).
    role: 'gk'|'def'|'mid'|'fwd' (minuscolo)."""
    if not opponent_team_slug or cutoff_dt is None:
        return 1.0
    role = role.lower()
    sign = SIGN_BY_ROLE.get(role, 1)
    sens = SENSITIVITY_BY_ROLE.get(role, 0.0)
    if sens <= 0:
        return 1.0

    conceded, scored = _build_series_for_league(league)
    series = scored if sign < 0 else conceded
    series_opp = series.get(opponent_team_slug, [])
    past = [gc for dt, gc in series_opp if dt < cutoff_dt]
    if len(past) < 3:
        return 1.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_CONCEDED) / GLOBAL_STD_CONCEDED
    z_signed = sign * z
    return max(0.0, 1 + sens * z_signed)


def opponent_is_strong(league, opponent_team_slug, cutoff_dt, n_games=N_GAMES_DEFAULT):
    """Booleano 'avversario forte' basato sui gol REALI FATTI dall'avversario
    (ultime n_games partite prima di cutoff_dt) -- sostituisce (29/07,
    richiesta esplicita utente) il vecchio 'opponent_forte_flags' di Stadio D
    in DEF/MID, che confrontava domesticLeagueRanking (contaminato) con la
    media storica dei ranking affrontati. Qui: avversario 'forte' = il suo
    attacco segna piu' della media di lega (GLOBAL_MEAN_CONCEDED, la stessa
    costante usata per l'aggiustamento su lambda_pos_dec) -- coerente col
    fatto che il pezzo di formula condizionato (gol_subiti/clean_sheet/
    passaggio del NOSTRO giocatore) e' una questione difensiva, quindi conta
    la forza offensiva di chi abbiamo davanti, non un ranking generico.
    None se il dato non e' disponibile (stesso fallback permissivo di prima:
    media_condizionata tratta i punti None come non classificabili)."""
    if not opponent_team_slug or cutoff_dt is None:
        return None
    _, scored = _build_series_for_league(league)
    series_opp = scored.get(opponent_team_slug, [])
    past = [gc for dt, gc in series_opp if dt < cutoff_dt]
    if len(past) < 3:
        return None
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    return avg_val > GLOBAL_MEAN_CONCEDED
