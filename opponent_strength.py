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
# FWD RIVISTO (30/07, richiesta esplicita utente dopo un caso reale sospetto
# -- Rafael Navarro, moltiplicatore 1.95 contro Austin che aveva subito 2.4
# gol/partita nelle ultime 10, quasi il doppio della media di lega): con un
# pool di calibrazione molto piu' grande/pulito di fine luglio, FWD=1.0 e'
# oggi PEGGIORE di nessun aggiustamento (+0.10% MAE walk-forward reale,
# formazione_mls/diagnostics/validate_opponent_conceded_level.py) -- il
# -0.58% che giustificava 1.0 il 29/07 non si e' riconfermato. Nuovo ottimo
# 0.3-0.5 (guadagno comunque marginale, -0.05%), preso il centro 0.4.
# GK/DEF/MID confermati nello stesso ritest (differenze nel rumore, <0.05%).
SENSITIVITY_BY_ROLE = {'gk': 0.7, 'def': 0.8, 'mid': 0.7, 'fwd': 0.4}
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
    GLOBAL_MEAN_CONCEDED/GLOBAL_STD_CONCEDED (fisse, dal backtest).

    league=None (03/08): serie GLOBALE, tutte le leghe insieme -- vedi
    _series_for_lookup per il perche'."""
    if league in _CACHE:
        return _CACHE[league]

    _disk = _load_disk_cache('series', league or '_globale')
    if _disk is not None:
        result = (_series_from_json(_disk['conceded']), _series_from_json(_disk['scored']))
        _CACHE[league] = result
        return result

    # ORDINE DEI FILE (04/08): i glob qui sotto sono `sorted()` per una ragione
    # precisa. glob.glob torna l'ordine del filesystem, che cambia fra Windows e
    # il runner Linux; l'ordine cambia quello delle somme in virgola mobile,
    # opponent_is_strong e' una soglia BOOLEANA e basta un epsilon per far
    # ribaltare qualche partita da "avversario forte" a "debole". Risultato
    # misurato: MAE del banco DEF che tremola di 0,003 e correlazione di 0,0008
    # fra i due ambienti, a parita' di campione (25.738 righe, 263 giornate).
    # Non toglierlo: e' l'unica cosa che rende confrontabili i numeri di due
    # sessioni diverse.
    seen = set()
    conceded = defaultdict(list)
    scored = defaultdict(list)
    if league is None:
        patterns = [f'formazione_*/output/*_{r}_all/.cache' for r in ('gk', 'def', 'mid')]
    else:
        patterns = [
            f'formazione_{league}/output/{league}_gk_all/.cache',
            f'formazione_{league}/output/{league}_def_all/.cache',
            f'formazione_{league}/output/{league}_mid_all/.cache',
        ]
    for cache_dir in patterns:
        for fpath in sorted(glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))):
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
    _save_disk_cache('series', league or '_globale',
                     {'conceded': _series_to_json(conceded),
                      'scored': _series_to_json(scored)})
    return result


# Numero minimo di partite storiche dell'avversario perche' l'aggiustamento
# venga applicato. Sotto questa soglia: nessun aggiustamento (fallback sicuro).
MIN_PARTITE_AVVERSARIO = 3


def _serie_avversario(league, opponent_team_slug, sign, cutoff_dt):
    """Storico dell'avversario, con RIPIEGO GLOBALE (03/08, bug reale).

    Le serie erano indicizzate per lega e costruite scansionando SOLO
    'formazione_<lega>/output/...', quindi un avversario di un'altra lega non
    esisteva e l'aggiustamento non veniva applicato. Non e' un caso di
    scuola: le partite MLS di questi giorni sono di Leagues Cup contro
    squadre di Liga MX, i cui dati stanno in formazione_messico e non
    venivano mai letti. Dentro lo stesso pool alcuni giocatori ricevevano
    l'aggiustamento e altri no -- che sporca la CLASSIFICA (quello che serve
    per scegliere chi schierare) piu' di quanto sposti la MAE.

    Ora: prima la lega del giocatore (comportamento invariato quando il dato
    c'e'), poi la serie globale su tutte le leghe. La scansione globale costa
    ~1.3s una volta per run (1247 file di cache, 22k partite) ed e' su disco
    temporaneo come le altre."""
    conceded, scored = _build_series_for_league(league)
    serie = (scored if sign < 0 else conceded).get(opponent_team_slug, [])
    past = [v for dt, v in serie if dt < cutoff_dt]
    if len(past) >= MIN_PARTITE_AVVERSARIO:
        return past
    conceded_g, scored_g = _build_series_for_league(None)
    serie_g = (scored_g if sign < 0 else conceded_g).get(opponent_team_slug, [])
    past_g = [v for dt, v in serie_g if dt < cutoff_dt]
    return past_g if len(past_g) > len(past) else past


def _peso_campione(n, n_games):
    """Quanto fidarsi di una media calcolata su n partite invece che su
    n_games (03/08, fix logico).

    Prima la media dell'avversario veniva normalizzata con GLOBAL_STD_CONCEDED
    e usata tale e quale, che si fosse calcolata su 3 partite o su 10: una
    squadra con 3 partite in cache riceveva la stessa correzione piena di una
    con 10, pur essendo la sua media molto piu' rumorosa. Ora il peso cresce
    col campione e vale 1.0 a campione pieno -- quindi a n_games partite il
    comportamento e' IDENTICO a prima (le sensibilita' validate restano
    valide), e viene attenuato solo dove il dato e' effettivamente sottile.

    NOTA (perche' non si divide per l'errore standard): dividere per
    GLOBAL_STD/sqrt(n) sarebbe la statistica di significativita', non
    l'ampiezza dell'effetto, e cambierebbe la scala di ~3x invalidando tutte
    le sensibilita' gia' validate per ruolo."""
    if n <= 0 or n_games <= 0:
        return 0.0
    return min(1.0, n / float(n_games))


def opponent_lambda_multiplier(league, role, opponent_team_slug, cutoff_dt,
                               n_games=N_GAMES_DEFAULT, sensitivity=None):
    """Ritorna il moltiplicatore da applicare a lambda_pos (ruoli con
    sign=+1) o lambda_neg... in realta' SEMPRE a lambda_pos (per costruzione
    del test, vedi SIGN_BY_ROLE: anche per GK il segno negativo si applica a
    lambda_pos, rendendolo piu' basso quando l'avversario segna tanto) --
    1.0 se il dato non e' disponibile (fallback sicuro, nessun aggiustamento).
    role: 'gk'|'def'|'mid'|'fwd' (minuscolo).

    `sensitivity` (04/08, BRIEF taratura_sensitivity): sovrascrive
    SENSITIVITY_BY_ROLE[role] per la taratura, senza editare il file a ogni
    giro. None (default) = comportamento INVARIATO, legge dal dizionario.
    sens<=0 ritorna 1.0 SUBITO (nessun'altra strada, nessun fallback: e' un
    vero spegnimento, non come il caso Stadio D/DEF del 04/08 -- verificato
    in HANDOFF_taratura_sensitivity_2026-08-04)."""
    if not opponent_team_slug or cutoff_dt is None:
        return 1.0
    role = role.lower()
    sign = SIGN_BY_ROLE.get(role, 1)
    sens = sensitivity if sensitivity is not None else SENSITIVITY_BY_ROLE.get(role, 0.0)
    if sens <= 0:
        return 1.0

    past = _serie_avversario(league, opponent_team_slug, sign, cutoff_dt)
    if len(past) < MIN_PARTITE_AVVERSARIO:
        return 1.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_CONCEDED) / GLOBAL_STD_CONCEDED
    z_signed = sign * z * _peso_campione(len(past), n_games)
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
# SPENTO (03/08, 3.0 -> 0.0). Stessa storia del pen-area del portiere.
# Rimisurato su 18.992 previsioni di attaccante walk-forward:
#
#     sensibilita      MAE     corr   selezione
#         0.0       14.038   0.259     28.9%
#         1.5       14.040   0.259     27.5%
#         3.0       14.044   0.257     27.5%   <- era in produzione
#         6.0       14.048   0.256     27.6%
#
# Monotono: piu' se ne mette, peggio va, su tutte e tre le misure. Il -0.38% di
# MAE che lo aveva giustificato veniva da un banco che teneva SPENTI gli
# aggiustamenti avversario, quindi misurava il pezzo isolato invece che dentro
# la formula in cui doveva vivere.
FWD_OFFENSE_SENSITIVITY = 0.0

_DEF_POSS_CACHE = {}


def _build_def_poss_lost_series(league):
    """league=None -> serie GLOBALE su tutte le leghe (03/08), stesso ripiego
    di _serie_avversario: l'avversario di coppa non sta nella cartella della
    lega del giocatore."""
    if league in _DEF_POSS_CACHE:
        return _DEF_POSS_CACHE[league]
    _disk = _load_disk_cache('poss_lost', league or '_globale')
    if _disk is not None:
        series = _series_from_json(_disk)
        _DEF_POSS_CACHE[league] = series
        return series
    per_team_date = defaultdict(list)
    cache_dir = ('formazione_*/output/*_def_all/.cache' if league is None
                 else f'formazione_{league}/output/{league}_def_all/.cache')
    for fpath in sorted(glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))):
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
    _save_disk_cache('poss_lost', league or '_globale', _series_to_json(series))
    return series


def _serie_squadra_con_ripiego(costruttore, league, team_slug, cutoff_dt):
    """Storico di squadra con ripiego sulla serie globale -- stessa logica di
    _serie_avversario, per le serie costruite dai soli difensori."""
    serie = costruttore(league).get(team_slug, [])
    past = [v for dt, v in serie if dt < cutoff_dt]
    if len(past) >= MIN_PARTITE_AVVERSARIO:
        return past
    serie_g = costruttore(None).get(team_slug, [])
    past_g = [v for dt, v in serie_g if dt < cutoff_dt]
    return past_g if len(past_g) > len(past) else past


# Tetto al delta offensivo FWD (03/08, fix logico). Senza tetto il delta e'
# proporzionale al granulare offensivo del giocatore stesso: misurato sulle
# cache reali andava da -9.0 a +14.8 punti, per un aggiustamento validato a
# -0.38% di MAE. Un contributo di quella scala non e' una correzione, e' una
# seconda previsione. +-3 punti e' l'ordine di grandezza coerente con gli
# altri aggiustamenti additivi del modello (Stadio D).
FWD_OFFENSE_DELTA_CAP = 3.0


def fwd_offense_granular_delta(league, opponent_team_slug, cutoff_dt, own_offensive_hist, n_games=N_GAMES_DEFAULT):
    """Delta ADDITIVO (non moltiplicativo) da sommare al grezzo dello
    score_atteso FWD -- vedi commento sopra FWD_OFFENSIVE_STATS. Ritorna 0.0
    se il dato non e' disponibile (fallback sicuro).

    FIX (03/08): era 'abs(own_offensive_hist)'. Con il valore assoluto, un
    attaccante col granulare offensivo NEGATIVO (il ~3% del pool: media
    pesata fino a -0.68) riceveva la correzione con lo stesso segno di uno
    positivo, cioe' un bonus proporzionale a quanto e' scarso. Ora si usa il
    valore con segno: se il giocatore non produce in fase offensiva, un
    avversario che perde palla in difesa non gli regala niente.
    Aggiunto anche il tetto FWD_OFFENSE_DELTA_CAP e il peso per campione."""
    if not opponent_team_slug or cutoff_dt is None or own_offensive_hist is None:
        return 0.0
    past = _serie_squadra_con_ripiego(_build_def_poss_lost_series, league,
                                      opponent_team_slug, cutoff_dt)
    if len(past) < MIN_PARTITE_AVVERSARIO:
        return 0.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_DEF_POSS_LOST) / GLOBAL_STD_DEF_POSS_LOST
    delta = (FWD_OFFENSE_SENSITIVITY * z * own_offensive_hist * 0.3
             * _peso_campione(len(past), n_games))
    return max(-FWD_OFFENSE_DELTA_CAP, min(FWD_OFFENSE_DELTA_CAP, delta))


GLOBAL_MEAN_DEF_PEN_AREA = 1.9428
GLOBAL_STD_DEF_PEN_AREA = 2.2335
# SPENTO (03/08, 0.5 -> 0.0). Rimisurato col banco che ora accende davvero gli
# aggiustamenti avversario, su 6.019 previsioni di portiere walk-forward, e
# provato in combinazione con la sensibilita' del ruolo:
#
#     sens   pen_area     MAE     corr   selezione
#     0.7      0.5     15.961   0.043      4.9%   <- era in produzione
#     0.7      0.0     15.960   0.045      6.4%
#     1.0      0.0     15.958   0.047      6.0%
#
# Spegnerlo migliora tutte e tre le misure. Ha senso: la validazione che lo
# aveva introdotto (-0.13% di MAE) misurava un delta additivo sul granulare di
# parate, mentre in produzione era finito a moltiplicare lambda_pos col segno
# rovesciato -- quindi quel -0.13% non ha mai descritto cio' che girava. Rimesso
# nella forma giusta, il segnale non c'e'. La formula resta al suo posto e
# riaccenderla e' cambiare questo numero, se una misura futura dira' altro.
GK_PEN_AREA_SENSITIVITY = 0.0
# Tetto al delta, stesso ordine di grandezza di FWD_OFFENSE_DELTA_CAP: il
# granulare GOALKEEPING vale in mediana 13.7 punti a partita (misurato su 4
# leghe), quindi senza tetto 0.5*z*13.7*0.3 arriverebbe a +-4 punti.
GK_PEN_AREA_DELTA_CAP = 3.0

_DEF_PEN_AREA_CACHE = {}


def _build_def_pen_area_series(league):
    """league=None -> serie GLOBALE su tutte le leghe (03/08), vedi
    _serie_avversario.

    Ricostruisce, per squadra, le pen_area_entries medie a partita dei
    SOLI DIFENSORI (isolato da FWD+MID gia' usati dal bonus goalkeeping
    esistente -- validato con formazione_mls/diagnostics/
    validate_cross_role_combos.py, gruppo gk_vs_def_only, -0.13% MAE:
    difensori avversari che salgono spesso in area su corner/palle inattive
    espongono di piu' il portiere)."""
    if league in _DEF_PEN_AREA_CACHE:
        return _DEF_PEN_AREA_CACHE[league]
    _disk = _load_disk_cache('pen_area', league or '_globale')
    if _disk is not None:
        series = _series_from_json(_disk)
        _DEF_PEN_AREA_CACHE[league] = series
        return series
    per_team_date = defaultdict(list)
    cache_dir = ('formazione_*/output/*_def_all/.cache' if league is None
                 else f'formazione_{league}/output/{league}_def_all/.cache')
    for fpath in sorted(glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))):
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
    _save_disk_cache('pen_area', league or '_globale', _series_to_json(series))
    return series


def gk_def_pen_area_granular_delta(league, opponent_team_slug, cutoff_dt,
                                   own_goalkeeping_hist, n_games=N_GAMES_DEFAULT):
    """Delta ADDITIVO sul granulare del portiere, in base alle
    pen_area_entries dei DIFENSORI avversari: chi sale spesso in area su
    corner e palle inattive costringe il portiere a piu' interventi, quindi
    piu' punti nella categoria GOALKEEPING (parate, uscite, respinte).
    0.0 se il dato non e' disponibile (fallback sicuro).

    RISCRITTO (03/08). Prima era 'gk_def_pen_area_multiplier', un
    moltiplicatore '1 + 0.5*z' applicato a lambda_pos del portiere. Erano
    due errori sovrapposti:

    1. COMPONENTE SBAGLIATA. La validazione che lo giustificava (-0.13% MAE,
       validate_cross_role_combos.py, gruppo gk_vs_def_only) misurava un
       delta ADDITIVO sul granulare GOALKEEPING del portiere
       ('sens * z * own_hist * 0.3', dove own_hist e' il granulare di parate
       del portiere stesso). In produzione era finito invece a moltiplicare
       lambda_pos, che e' tutta un'altra cosa: il tasso di eventi decisivi.
       Misurata una cosa, applicata un'altra.

    2. SEGNO. lambda_pos del portiere e' dominato da clean_sheet_60
       (verificato sui detailedScore reali: le POSITIVE_DECISIVE_STAT del GK
       sono clean_sheet_60, penalty_save, clearance_off_line, goals,
       goal_assist). Piu' l'avversario arriva in area, MENO clean sheet: il
       moltiplicatore '1 + 0.5*z' alzava lambda_pos proprio quando andava
       abbassato, contro il proprio commento ("espongono di piu' il
       portiere") e contro il gemello SIGN_BY_ROLE['gk'] = -1, costruito
       sullo stesso concetto e moltiplicato nello stesso punto. La griglia
       di sensibilita' della validazione era [0.0 ... 2.0], solo non
       negativa: il segno non era mai stato messo alla prova.
       Effetto misurato sulle cache reali prima del fix: moltiplicatore da
       0.63 a 1.57 su lambda_pos, cioe' +-35-57% nel verso sbagliato.

    Ora la forma e' quella validata: additiva, sul granulare, segno positivo
    (piu' pressione avversaria -> piu' lavoro per il portiere -> piu' punti
    di parata), mentre il rischio sul clean sheet resta gestito dove gli
    compete, da opponent_lambda_multiplier con SIGN_BY_ROLE['gk'] = -1."""
    if not opponent_team_slug or cutoff_dt is None or own_goalkeeping_hist is None:
        return 0.0
    past = _serie_squadra_con_ripiego(_build_def_pen_area_series, league,
                                      opponent_team_slug, cutoff_dt)
    if len(past) < MIN_PARTITE_AVVERSARIO:
        return 0.0
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    z = (avg_val - GLOBAL_MEAN_DEF_PEN_AREA) / GLOBAL_STD_DEF_PEN_AREA
    delta = (GK_PEN_AREA_SENSITIVITY * z * own_goalkeeping_hist * 0.3
             * _peso_campione(len(past), n_games))
    return max(-GK_PEN_AREA_DELTA_CAP, min(GK_PEN_AREA_DELTA_CAP, delta))


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
    past = _serie_avversario(league, opponent_team_slug, -1, cutoff_dt)
    if len(past) < MIN_PARTITE_AVVERSARIO:
        return None
    past = past[-n_games:]
    avg_val = sum(past) / len(past)
    return avg_val > GLOBAL_MEAN_CONCEDED
