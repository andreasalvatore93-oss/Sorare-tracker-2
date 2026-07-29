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
import tempfile
from collections import defaultdict

# Cache su DISCO temporaneo (29/07 sera, fix reale di performance): ogni
# predict e' un PROCESSO SEPARATO per giocatore (TARGET_SLUG), quindi la
# cache in memoria sotto (_CACHE/_DEF_POSS_CACHE/_DEF_PEN_AREA_CACHE, "una
# volta per processo") si azzera per ogni giocatore -- un job predict con
# 15 giocatori dello stesso ruolo/lega rifà la scansione COMPLETA della
# cartella cache (200+ file per le leghe piu' vecchie) 15 volte, invece di
# 1. FWD è il piu' colpito (scansiona DUE cartelle invece di una: goals_
# conceded via _build_series_for_league + poss_lost_ctrl via _build_def_
# poss_lost_series), diventato il collo di bottiglia della run (verificato
# su run reali: FWD resta l'unico ruolo non finito anche con lo sharding).
# Il file vive in /tmp (ephemero per il runner GitHub Actions, MAI
# committato) -- valido solo per la durata di QUESTO job/run, si azzera da
# solo al prossimo run (nuovo runner = nuovo /tmp). Nessun rischio di dato
# stantio tra run diverse, nessuna modifica ai VALORI calcolati.
_DISK_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'opponent_strength_cache')


def _disk_cache_path(kind, league):
    os.makedirs(_DISK_CACHE_DIR, exist_ok=True)
    return os.path.join(_DISK_CACHE_DIR, f'{kind}_{league}.json')


def _series_to_json(series):
    """dict[team] -> [(datetime, float), ...]  =>  JSON-serializzabile."""
    return {t: [[dt.isoformat(), v] for dt, v in vals] for t, vals in series.items()}


def _series_from_json(data):
    out = defaultdict(list)
    for t, vals in data.items():
        out[t] = [(datetime.datetime.fromisoformat(dt), v) for dt, v in vals]
    return out


def _load_disk_cache(kind, league):
    path = _disk_cache_path(kind, league)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_disk_cache(kind, league, data):
    path = _disk_cache_path(kind, league)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except OSError:
        pass

N_GAMES_DEFAULT = 10
# GK/DEF AGGIORNATI (29/07): retest post-retuning half_life/trend_intensity
# di oggi, walk-forward su tutte le leghe -- GK 1.0->0.7 (-0.04% MAE), DEF
# 1.0->0.8 (-0.01% MAE), minimi interni puliti. MID lasciato a 0.7 (guadagno
# indistinguibile dal rumore, 0.0001 di MAE). FWD gia' ottimale a 1.0.
SENSITIVITY_BY_ROLE = {'gk': 0.7, 'def': 0.8, 'mid': 0.7, 'fwd': 1.0}
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

    _disk = _load_disk_cache('series', league)
    if _disk is not None:
        result = (_series_from_json(_disk['conceded']), _series_from_json(_disk['scored']))
        _CACHE[league] = result
        return result

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
    _save_disk_cache('series', league, {'conceded': _series_to_json(conceded),
                                         'scored': _series_to_json(scored)})
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


FWD_OFFENSIVE_STATS = ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                       'pen_area_entries', 'won_contest')
# Validato (29/07, formazione_mls/diagnostics/validate_cross_role_combos.py,
# gruppo fwd_vs_def): granulare "offensivo" di un FWD condizionato sul
# poss_lost_ctrl medio (ultime 10 partite) dei DIFENSORI avversari -- un
# avversario che perde palla spesso in fase difensiva espone di piu' l'FWD.
# Minimo pulito a curva a campana, sensibilita'=3.0, -0.38% MAE (1928 punti
# di test). Media/std FISSE dal backtest (stesso principio di
# GLOBAL_MEAN_CONCEDED sopra).
GLOBAL_MEAN_DEF_POSS_LOST = 9.97
GLOBAL_STD_DEF_POSS_LOST = 4.48
FWD_OFFENSE_SENSITIVITY = 3.0

_DEF_POSS_CACHE = {}


def _build_def_poss_lost_series(league):
    if league in _DEF_POSS_CACHE:
        return _DEF_POSS_CACHE[league]
    _disk = _load_disk_cache('poss_lost', league)
    if _disk is not None:
        series = _series_from_json(_disk)
        _DEF_POSS_CACHE[league] = series
        return series
    per_team_date = defaultdict(list)
    cache_dir = f'formazione_{league}/output/{league}_def_all/.cache'
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
            if not (home.get('slug') == team_slug or away.get('slug') == team_slug):
                continue
            dt = _parse_date(g)
            if dt is None:
                continue
            val = 0.0
            for row in e['detailedScore']:
                if row.get('stat') == 'poss_lost_ctrl':
                    val += row.get('statValue', 0.0) or 0.0
            per_team_date[(team_slug, dt)].append(val)

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        series[team].append((dt, sum(vals) / len(vals)))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    _DEF_POSS_CACHE[league] = series
    _save_disk_cache('poss_lost', league, _series_to_json(series))
    return series


def fwd_offense_granular_delta(league, opponent_team_slug, cutoff_dt, own_offensive_hist, n_games=N_GAMES_DEFAULT):
    """Delta ADDITIVO (non moltiplicativo) da sommare al grezzo dello
    score_atteso FWD -- vedi commento sopra FWD_OFFENSIVE_STATS. Ritorna 0.0
    se il dato non e' disponibile (fallback sicuro)."""
    if not opponent_team_slug or cutoff_dt is None or not own_offensive_hist:
        return 0.0
    series = _build_def_poss_lost_series(league)
    series_opp = series.get(opponent_team_slug, [])
    past = [v for dt, v in series_opp if dt < cutoff_dt]
    if len(past) < 3:
        return 0.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_DEF_POSS_LOST) / GLOBAL_STD_DEF_POSS_LOST
    return FWD_OFFENSE_SENSITIVITY * z * abs(own_offensive_hist) * 0.3


GLOBAL_MEAN_DEF_PEN_AREA = 1.9428
GLOBAL_STD_DEF_PEN_AREA = 2.2335
GK_PEN_AREA_SENSITIVITY = 0.5

_DEF_PEN_AREA_CACHE = {}


def _build_def_pen_area_series(league):
    """Ricostruisce, per squadra, le pen_area_entries medie a partita dei
    SOLI DIFENSORI (isolato da FWD+MID gia' usati dal bonus goalkeeping
    esistente -- validato con formazione_mls/diagnostics/
    validate_cross_role_combos.py, gruppo gk_vs_def_only, -0.13% MAE:
    difensori avversari che salgono spesso in area su corner/palle inattive
    espongono di piu' il portiere)."""
    if league in _DEF_PEN_AREA_CACHE:
        return _DEF_PEN_AREA_CACHE[league]
    _disk = _load_disk_cache('pen_area', league)
    if _disk is not None:
        series = _series_from_json(_disk)
        _DEF_PEN_AREA_CACHE[league] = series
        return series
    per_team_date = defaultdict(list)
    cache_dir = f'formazione_{league}/output/{league}_def_all/.cache'
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
            if not (home.get('slug') == team_slug or away.get('slug') == team_slug):
                continue
            dt = _parse_date(g)
            if dt is None:
                continue
            val = 0.0
            for row in e['detailedScore']:
                if row.get('stat') == 'pen_area_entries':
                    val += row.get('statValue', 0.0) or 0.0
            per_team_date[(team_slug, dt)].append(val)

    series = defaultdict(list)
    for (team, dt), vals in per_team_date.items():
        series[team].append((dt, sum(vals) / len(vals)))
    for t in series:
        series[t].sort(key=lambda x: x[0])
    _DEF_PEN_AREA_CACHE[league] = series
    _save_disk_cache('pen_area', league, _series_to_json(series))
    return series


def gk_def_pen_area_multiplier(league, opponent_team_slug, cutoff_dt, n_games=N_GAMES_DEFAULT):
    """Moltiplicatore aggiuntivo (si affianca a opponent_lambda_multiplier
    GK esistente, non lo sostituisce) da applicare a lambda_pos del
    portiere, basato solo sulle pen_area_entries dei DIFENSORI avversari.
    1.0 (nessun effetto) se il dato non e' disponibile."""
    if not opponent_team_slug or cutoff_dt is None:
        return 1.0
    series = _build_def_pen_area_series(league)
    series_opp = series.get(opponent_team_slug, [])
    past = [v for dt, v in series_opp if dt < cutoff_dt]
    if len(past) < 3:
        return 1.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_DEF_PEN_AREA) / GLOBAL_STD_DEF_PEN_AREA
    return max(0.0, 1 + GK_PEN_AREA_SENSITIVITY * z)


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
