"""
test_mid (test centrocampista MLS — prototipo, clone adattato di test_mls_fwd_all.py)

Prima versione per il ruolo CENTROCAMPISTA. Stessa infrastruttura/formula degli
attaccanti (query GraphQL, backtest rigoroso, parametri fissati), MA con i
gruppi granulari ADATTATI: il detailedScore di un Midfielder e' un superset di
quello di un Forward (nessuno stat manca), con 5 stat IN PIU' verificati dal
vivo (Mohamed Farsi, score 59.9, ricostruzione esatta):
  - won_tackle, blocked_cross, outfielder_block (categoria DEFENDING)
  - accurate_long_balls (categoria PASSING)
  - goals_conceded (categoria GENERAL, negativo)

Formula (identica nella struttura, gruppi granulari ampliati):
  score_atteso = P(gioca) x media_pesata_esponenziale(N partite)
                 x fattore_casa_trasferta x fattore_forza_avversario
                 x fattore_falli x fattore_duelli x fattore_offensivo
                 x fattore_eventi_rari x fattore_passaggio x fattore_difesa_rari
                 x fattore_azioni_difensive x fattore_trend
  range_confidenza = +/- dev_std_pesata * RANGE_MULTIPLIER

PARAMETRI: riusati gli stessi valori FISSATI per gli attaccanti come punto di
partenza (HALF_LIFE_GAMES=12.0, RANGE_MULTIPLIER=1.4, OPPONENT_SENSITIVITY=29.0,
TREND_INTENSITY=0.7) — da ricalibrare con un grid search dedicato ai
centrocampisti quando avremo piu' giocatori di test.

Giocatore di test: Marcel Hartel (Midfielder, slug marcel-hartel — molti dati disponibili).

Filtro secco su starterOddsBasisPoints della partita target — se <
MIN_STARTER_ODDS (70%), il giocatore viene ESCLUSO dall'analisi.
"""
import os
import json
import math
import time
import datetime
import requests

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/graphql'

DISCOVERY_FILE = os.path.join('mls_mid_discovery', 'player_slugs.json')

# Fallback statico SOLO se mls_mid_discovery/player_slugs.json non esiste
# ancora (nessuna discovery centrocampisti ancora fatta): singolo giocatore
# di test, Mohamed Farsi.
_FALLBACK_PLAYER_SLUGS = [
    'marcel-hartel',
]


def load_player_slugs():
    if os.path.exists(DISCOVERY_FILE):
        try:
            with open(DISCOVERY_FILE, 'r', encoding='utf-8') as f:
                slugs = json.load(f)
            if slugs:
                return slugs
        except (json.JSONDecodeError, OSError):
            pass
    return list(_FALLBACK_PLAYER_SLUGS)


PLAYER_SLUGS = load_player_slugs()

WINDOW_SIZE = 15  # ridotta per il test multi-giocatore (meno chiamate per giocatore, budget complessita' API limitato)
HALF_LIFE_GAMES = 12.0  # FISSATO (25/07): combinazione vincente aggregata cross-player (14 giocatori, MAE medio 18.13, copertura media 68.93%)
RANGE_MULTIPLIER = 1.4  # FISSATO (25/07): idem — nota: il valore vincente e' 1.4, non 1.6 come nel tentativo precedente; la copertura ideale viene dalla combinazione GIUSTA di tutti i parametri insieme, non dal range preso da solo
OPPONENT_SENSITIVITY = 29.0  # FISSATO (25/07): idem
TREND_INTENSITY = 0.7  # FISSATO (25/07): idem — trend leggermente attenuato rispetto al comportamento originale (1.0)
MIN_MINUTES_PLAYED = 60  # partite giocate sotto questa soglia (subentri) escluse dalla finestra
MIN_STARTER_ODDS = 0.70  # NUOVO: sotto questa soglia di probabilita' di titolarita', il giocatore e' ESCLUSO dall'analisi (non schierabile secondo l'utente)
SKIP_GRANULAR_DETAIL = False  # RIPRISTINATO (24/07): con la strategia GitHub Actions matrix, ogni giocatore gira in un job/processo SEPARATO con budget di complessita' fresco — il problema di saturazione cumulativa (che colpiva il 2o+ giocatore in un unico processo) non si presenta piu'. I fattori granulari (falli/duelli/passaggio/ecc.) sono quindi di nuovo calcolati per ogni giocatore.

OUTPUT_DIR = 'mls_mid_all'
CACHE_DIR = os.path.join(OUTPUT_DIR, '.cache')

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


DEBUG_DIR = os.path.join(OUTPUT_DIR, '.debug')
_query_counter = [0]


def _dump_debug(label, payload, resp=None, error=None):
    """Salva su disco un dump completo di ogni chiamata GraphQL (richiesta +
    risposta, o errore) per diagnostica. File numerati in ordine di chiamata."""
    if not os.path.exists(DEBUG_DIR):
        os.makedirs(DEBUG_DIR)
    _query_counter[0] += 1
    ts = datetime.datetime.utcnow().strftime('%H%M%S_%f')
    fname = os.path.join(DEBUG_DIR, f'{_query_counter[0]:03d}_{label}_{ts}.txt')
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(f"=== RICHIESTA ({label}) ===\n")
        f.write(f"operationName: {payload.get('operationName')}\n")
        f.write(f"variables: {json.dumps(payload.get('variables', {}), ensure_ascii=False)}\n")
        f.write(f"query:\n{payload.get('query', '')}\n")
        f.write("\n=== RISPOSTA ===\n")
        if resp is not None:
            f.write(f"status_code: {resp.status_code}\n")
            f.write(f"headers: {dict(resp.headers)}\n")
            f.write(f"body (integrale):\n{resp.text}\n")
        if error is not None:
            f.write(f"eccezione: {error!r}\n")
    return fname


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [test_mid] {msg}")


MIN_QUERY_INTERVAL_SECONDS = 0.5  # pausa minima tra chiamate GraphQL consecutive, per non concentrare troppe richieste ravvicinate
_last_query_ts = [0.0]


def _throttle_query():
    elapsed = time.time() - _last_query_ts[0]
    if elapsed < MIN_QUERY_INTERVAL_SECONDS:
        time.sleep(MIN_QUERY_INTERVAL_SECONDS - elapsed)
    _last_query_ts[0] = time.time()


def graphql_query(query, variables=None, operation_name=None):
    """Esegue una query GraphQL contro l'API Sorare, con retry/backoff su 429.
    Diagnostica COMPLETA: ogni chiamata (richiesta + risposta integrale, o
    eccezione) viene salvata su disco in test_owusu/.debug/, indipendentemente
    dall'esito, per poter analizzare in dettaglio eventuali errori 4xx/5xx."""
    _throttle_query()
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if COOKIES:
        headers['Cookie'] = COOKIES

    payload = {'query': query, 'variables': variables or {}}
    if operation_name:
        payload['operationName'] = operation_name

    label = operation_name or 'query'
    log(f"[GraphQL] -> {label} | variables={json.dumps(variables or {}, ensure_ascii=False)}")

    backoff = 1.0
    for attempt in range(5):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            debug_file = _dump_debug(label, payload, resp=resp)

            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                sleep_s = float(retry_after) if retry_after else backoff
                log(f"[GraphQL 429] {label} tentativo {attempt+1}/5, attesa {sleep_s:.1f}s "
                    f"(dump: {debug_file})")
                time.sleep(sleep_s)
                backoff *= 2
                continue

            if resp.status_code >= 400:
                log(f"[GraphQL ERRORE] {label} HTTP {resp.status_code} | dump completo: {debug_file}")
                log(f"[GraphQL ERRORE] {label} body (primi 1500 char): {resp.text[:1500]}")
                return {}

            data = resp.json()
            if data.get('errors'):
                error_msgs = json.dumps(data['errors'], ensure_ascii=False)
                # L'errore "exceeds max complexity" NON viene ritentato qui dentro
                # (per evitare un doppio livello di retry: questo retry interno,
                # 5 tentativi con backoff fino a 93s, sommato al retry esterno nel
                # loop principale di main() portava a tempi totali di 4-5+ minuti
                # per un singolo giocatore fallito). Fallisce subito, il retry
                # esterno nel loop principale decide se e quando ritentare l'intero
                # giocatore, con un unico tetto di attesa chiaro e controllabile.
                if 'exceeds max complexity' in error_msgs or 'complexity' in error_msgs.lower():
                    log(f"[GraphQL COMPLEXITY LIMIT] {label} -> {error_msgs[:300]} "
                        f"(nessun retry interno, gestito dal loop esterno) | dump: {debug_file}")
                    return data
                log(f"[GraphQL ERRORE-APPLICATIVO] {label} -> {error_msgs[:1500]} "
                    f"| dump completo: {debug_file}")
            else:
                log(f"[GraphQL OK] {label} risposta ricevuta correttamente.")
            return data

        except Exception as e:
            debug_file = _dump_debug(label, payload, error=e)
            log(f"[GraphQL ECCEZIONE] {label} tentativo {attempt+1}/5: {e!r} | dump: {debug_file}")
            time.sleep(backoff)
            backoff *= 2

    log(f"[GraphQL FALLITO] {label} - esauriti i tentativi.")
    return {}


# ---------------------------------------------------------------------------
# QUERY 4 equivalente: game log completo (allPlayerGameScores + anyFutureGames)
# ---------------------------------------------------------------------------
ALL_GAME_SCORES_QUERY = """
query AllPlayerGameScores($slug: String!, $first: Int!) {
  anyPlayer(slug: $slug) {
    allPlayerGameScores(first: $first) {
      nodes {
        id
        score
        scoreStatus
        positionTyped
        anyGame {
          id
          date
          statusTyped
          homeTeam { ... on Club { slug name code domesticLeagueRanking } }
          awayTeam { ... on Club { slug name code domesticLeagueRanking } }
          competition { slug }
        }
        anyPlayerGameStats {
          ... on PlayerGameStats {
            fieldStatus
            gameStarted
            minsPlayed
            yellowCard
            footballPlayingStatusOdds { starterOddsBasisPoints reliability }
          }
        }
      }
    }
    anyFutureGames(first: 5) {
      nodes {
        id
        date
        playerGameScore(playerSlug: $slug) {
          id
          positionTyped
          projectedScore
          anyGame {
            id
            date
            homeTeam { ... on Club { slug name code domesticLeagueRanking } }
            awayTeam { ... on Club { slug name code domesticLeagueRanking } }
            competition { slug }
          }
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints reliability }
            }
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# QUERY 5 equivalente: dettaglio punto-per-punto di una partita (per score-id)
# ---------------------------------------------------------------------------
GAME_SCORE_DETAIL_QUERY = """
query PlayerGameScoreDetail($id: ID!) {
  so5 {
    playerGameScore(id: $id) {
      id
      score
      scoreStatus
      position
      anyGame {
        date
        statusTyped
        homeTeam {
          ... on Club {
            slug name code domesticLeagueRanking domesticLeagueRankingRatioRange
          }
        }
        awayTeam {
          ... on Club {
            slug name code domesticLeagueRanking domesticLeagueRankingRatioRange
          }
        }
        competition { slug }
      }
      detailedScore { category stat statValue totalScore }
    }
  }
}
"""


def fetch_game_log(slug, first=50):
    """Recupera game log storico + prossime partite programmate per il giocatore."""
    log(f"[FASE 1/4] Recupero game log per {slug} (richiesta ultime {first})...")
    data = graphql_query(ALL_GAME_SCORES_QUERY, {"slug": slug, "first": first},
                          operation_name="AllPlayerGameScores")

    if not data:
        log("[FASE 1/4] FALLITA: graphql_query ha restituito risposta vuota/nulla "
            "(vedi log ERRORE sopra e i dump in .debug/ per il dettaglio HTTP).")
        return [], []

    if data.get('errors'):
        log(f"[FASE 1/4] FALLITA: la query ha risposto ma con errori applicativi GraphQL: "
            f"{json.dumps(data['errors'], ensure_ascii=False)}")
        return [], []

    if 'data' not in data:
        log(f"[FASE 1/4] SOSPETTO: risposta senza chiave 'data'. Contenuto completo: "
            f"{json.dumps(data, ensure_ascii=False)[:1500]}")
        return [], []

    player = data.get('data', {}).get('anyPlayer')
    if player is None:
        log(f"[FASE 1/4] FALLITA: 'anyPlayer' e' null nella risposta (slug '{slug}' non trovato "
            f"o campo diverso da quello atteso). Risposta data completa: "
            f"{json.dumps(data.get('data', {}), ensure_ascii=False)[:1500]}")
        return [], []

    past = (player.get('allPlayerGameScores', {}) or {}).get('nodes', []) or []
    future = (player.get('anyFutureGames', {}) or {}).get('nodes', []) or []
    log(f"[FASE 1/4] OK: trovate {len(past)} partite passate, {len(future)} future.")
    if not past:
        log(f"[FASE 1/4] ATTENZIONE: 'allPlayerGameScores.nodes' e' vuoto. "
            f"Struttura ricevuta per anyPlayer: {json.dumps(player, ensure_ascii=False)[:1500]}")
    return past, future


def load_cache(player_slug):
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    cache_file = os.path.join(CACHE_DIR, f'{player_slug}_detail_cache.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            try:
                return json.load(f), cache_file
            except json.JSONDecodeError:
                return {}, cache_file
    return {}, cache_file


def save_cache(cache, cache_file):
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def fetch_game_detail(score_id, cache, is_final):
    """Recupera il dettaglio granulare (detailedScore) di UNA partita.
    Usa la cache su disco per le partite gia' FINAL (non cambiano piu');
    le partite non-FINAL (REVIEWING/PENDING) vengono sempre riscaricate."""
    if is_final and score_id in cache:
        return cache[score_id]

    log(f"  -> Scarico dettaglio partita {score_id} (cache {'assente' if is_final else 'non applicabile, stato non finale'})...")
    data = graphql_query(GAME_SCORE_DETAIL_QUERY, {"id": score_id},
                          operation_name="PlayerGameScoreDetail")
    if data.get('errors'):
        log(f"  Errore dettaglio partita {score_id}: {data['errors']}")
        return None

    result = data.get('data', {}).get('so5', {}).get('playerGameScore')
    if result and is_final:
        cache[score_id] = result
    return result


# ---------------------------------------------------------------------------
# Logica di calcolo
# ---------------------------------------------------------------------------

def exponential_weights(n, half_life):
    """Genera n pesi con decadimento esponenziale: l'ultimo elemento (indice n-1,
    la partita piu' recente) ha peso massimo, il primo (piu' vecchio) il minimo.
    Il peso si dimezza ogni 'half_life' posizioni indietro."""
    decay = math.log(2) / half_life
    # indice 0 = partita piu' vecchia della finestra, n-1 = piu' recente
    weights = [math.exp(-decay * (n - 1 - i)) for i in range(n)]
    return weights


def weighted_mean(values, weights):
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_w


def weighted_stddev(values, weights, mean):
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total_w
    return math.sqrt(variance)


def trimmed_weighted_stddev(values, weights):
    """Deviazione standard pesata calcolata ESCLUDENDO il valore minimo e massimo
    della serie (trimmed statistics) — riduce l'influenza di 1-2 partite outlier
    estreme sul range di confidenza, senza alterare la media pesata principale
    (che resta calcolata su tutti i dati, inclusi gli estremi, per non falsare
    la stima centrale). Richiede almeno 5 valori per avere senso statistico;
    sotto quella soglia ritorna None (il chiamante fara' fallback alla versione
    non trimmed)."""
    if len(values) < 5:
        return None
    idx_min = values.index(min(values))
    idx_max = values.index(max(values))
    if idx_min == idx_max:
        return None
    keep_idx = [i for i in range(len(values)) if i not in (idx_min, idx_max)]
    trimmed_values = [values[i] for i in keep_idx]
    trimmed_weights = [weights[i] for i in keep_idx]
    trimmed_mean = weighted_mean(trimmed_values, trimmed_weights)
    return weighted_stddev(trimmed_values, trimmed_weights, trimmed_mean)


def team_ranking_from_game(game, player_team_slug):
    """Estrae ranking squadra giocatore e ranking avversario da un blocco anyGame
    (funziona sia per partite passate che future, stessa struttura)."""
    home = game.get('homeTeam') or {}
    away = game.get('awayTeam') or {}
    if home.get('slug') == player_team_slug:
        return home.get('domesticLeagueRanking'), away.get('domesticLeagueRanking'), True
    elif away.get('slug') == player_team_slug:
        return away.get('domesticLeagueRanking'), home.get('domesticLeagueRanking'), False
    return None, None, None


# Stat da sommare per ciascun gruppo granulare (nomi come appaiono in detailedScore).
# Sono fattori SEPARATI (non un indice unico), come richiesto: ognuno produce il
# proprio fattore casa/trasferta indipendente. Raggruppati per CATEGORIA SORARE
# (stesse categorie mostrate nella UI Sorare: Generale/Difesa/Possesso/Passaggio/
# In attacco), come da richiesta esplicita dell'utente.
FOULS_STATS = ('fouls', 'was_fouled')
DUELS_STATS = ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won')
OFFENSIVE_STATS = ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                    'pen_area_entries', 'won_contest')
# Categoria "Passaggio" Sorare: stat frequenti, nessun cap necessario.
# accurate_long_balls AGGIUNTO per il centrocampista (non presente/non
# rilevante nel gruppo attaccanti, verificato dal vivo su Mohamed Farsi).
PASSING_STATS = ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                  'accurate_long_balls')
# Eventi rari con peso enorme quando accadono ma situazionali/random: sommati nel
# totale ma il loro contributo e' limitato da un cap assoluto (in punti Sorare)
# per non far esplodere la stima su un singolo evento fortuito.
RARE_EVENTS_STATS = ('penalty_won', 'penalty_conceded', 'own_goals', 'error_lead_to_goal')
RARE_EVENTS_CAP = 10.0  # punti massimi (positivi o negativi) che questo gruppo puo' contribuire
# Categoria "Difesa" Sorare + altri eventi rarissimi: achievement compositi
# (double/triple) e azioni difensive eccezionali, quasi sempre 0.
DEFENSE_RARE_STATS = ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                       'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won')
DEFENSE_RARE_CAP = 10.0
# NUOVO gruppo SOLO centrocampista: azioni difensive "normali" (non rare/achievement),
# frequenti ogni partita per un mediano/centrocampista, assenti/marginali per un Forward.
DEFENSIVE_ACTIONS_STATS = ('won_tackle', 'blocked_cross', 'outfielder_block')
# NUOVO gruppo SOLO centrocampista: gol subiti dalla propria squadra mentre in campo
# (negativo, come per un difensore/portiere). Cappato per non far esplodere la stima
# su una goleada subita.
GOALS_CONCEDED_STATS = ('goals_conceded',)
GOALS_CONCEDED_CAP = 10.0


def extract_group_score(detail, stat_names):
    """Somma il totalScore di detailedScore per le stat indicate. Ritorna 0.0 se
    il dettaglio non e' disponibile (fallback sicuro, non altera il fattore)."""
    if not detail:
        return 0.0
    total = 0.0
    for entry in (detail.get('detailedScore') or []):
        if entry.get('stat') in stat_names:
            total += entry.get('totalScore', 0.0) or 0.0
    return total


def compute_split_factor(values, is_home_flags, target_is_home):
    """Dato un elenco di valori granulari (uno per partita, gia' sommati per un
    gruppo di stat) e i relativi flag casa/trasferta, calcola il fattore
    casa/trasferta per QUEL gruppo, con la stessa logica del fattore principale:
    media_contesto_target / media_generale. Fattore neutro (1.0) se non ci sono
    abbastanza dati in un contesto o se la media generale e' zero/negativa."""
    home_vals = [v for v, h in zip(values, is_home_flags) if h is True]
    away_vals = [v for v, h in zip(values, is_home_flags) if h is False]
    all_vals = values

    if not all_vals:
        return 1.0

    overall_avg = sum(all_vals) / len(all_vals)
    home_avg = sum(home_vals) / len(home_vals) if home_vals else overall_avg
    away_avg = sum(away_vals) / len(away_vals) if away_vals else overall_avg

    context_avg = home_avg if target_is_home else away_avg

    # I valori granulari possono essere negativi (es. falli) o vicini a zero,
    # quindi non possiamo dividere direttamente come per lo score totale (sempre
    # positivo). Convertiamo in un DELTA rispetto alla media generale, poi lo
    # trasformiamo in un moltiplicatore centrato su 1.0 con un fattore di scala
    # conservativo (ogni punto di delta sposta il moltiplicatore di 0.01 = 1%).
    delta = context_avg - overall_avg
    fattore = 1.0 + (delta * 0.01)
    return max(0.7, min(1.3, fattore))  # limitato per evitare correzioni estreme


def compute_trend_factor(scores, short_window=5, long_window=10, trend_intensity=1.0):
    """Confronta la media delle ultime 'short_window' partite con la media delle
    ultime 'long_window' partite (stesso pool gia' filtrato per competizione e
    minutaggio) per rilevare un trend di forma (in crescita o in calo). Ritorna
    un fattore moltiplicativo centrato su 1.0: se le partite piu' recenti hanno
    una media piu' alta della finestra piu' ampia, il fattore e' > 1 (forma in
    crescita), viceversa < 1. Scala conservativa e limitata (max +-20%), per non
    lasciare che poche partite recenti dominino la predizione.
    Richiede almeno 'long_window' partite; ritorna 1.0 (neutro) altrimenti.

    NUOVO (25/07): trend_intensity scala il DELTA (ratio - 1.0) prima del
    clamp finale, per rendere il trend parametrizzabile nel grid search
    invece di un comportamento fisso — es. trend_intensity=0.7 attenua il
    trend, 1.3 lo amplifica, 1.0 = comportamento originale invariato."""
    if len(scores) < long_window:
        return 1.0, None, None

    recent_short = scores[-short_window:]
    recent_long = scores[-long_window:]

    avg_short = sum(recent_short) / len(recent_short)
    avg_long = sum(recent_long) / len(recent_long)

    if avg_long == 0:
        return 1.0, avg_short, avg_long

    ratio = avg_short / avg_long
    scaled_ratio = 1.0 + (ratio - 1.0) * trend_intensity
    fattore = max(0.8, min(1.2, scaled_ratio))
    return fattore, avg_short, avg_long


def rigorous_backtest(scores, is_home_flags, opponent_rankings, min_history=6,
                       half_life=None, range_multiplier=1.0, opponent_sensitivity=29.0,
                       fouls_values=None, duels_values=None, offensive_values=None,
                       rare_events_values=None, passing_values=None, defense_rare_values=None,
                       defensive_actions_values=None, goals_conceded_values=None,
                       use_granular_factors=False, use_trend=False, trend_intensity=1.0):
    """Backtest rigoroso: per ogni partita a partire da 'min_history' partite di
    storico disponibile, ricalcola l'INTERA formula (media pesata esponenziale +
    fattore casa/trasferta + fattore forza avversario [+ fattori granulari se
    use_granular_factors=True]) usando SOLO i dati precedenti a quella partita,
    poi confronta con lo score reale ottenuto.
    P(gioca) e' fissato a 100% (sappiamo gia' che ha giocato, essendo storico).

    Parametri variabili (per grid search):
    - half_life: partite per il dimezzamento del peso esponenziale (default HALF_LIFE_GAMES)
    - range_multiplier: moltiplicatore applicato alla deviazione standard pesata
      per ottenere il range di confidenza (1.0 = deviazione standard pura)
    - opponent_sensitivity: costante di normalizzazione per il fattore forza
      avversario (piu' bassa = il ranking avversario pesa di piu' sul risultato)
    - use_granular_factors: se True, include anche falli/duelli/efficacia
      offensiva/eventi rari nel calcolo (richiede i relativi array)

    Ritorna una lista di dict con dettaglio per ogni partita testata + statistiche
    aggregate (MAE, % di volte in cui il reale rientra nel range di confidenza)."""
    if half_life is None:
        half_life = HALF_LIFE_GAMES

    rows = []
    n = len(scores)

    for i in range(min_history, n):
        hist_scores = scores[:i]
        hist_home_flags = is_home_flags[:i]
        hist_opp_ranks = opponent_rankings[:i]

        m = len(hist_scores)
        w = exponential_weights(m, half_life)
        media = weighted_mean(hist_scores, w)
        dev_std = weighted_stddev(hist_scores, w, media)

        # fattore casa/trasferta calcolato SOLO sullo storico precedente
        h_scores = [s for s, h in zip(hist_scores, hist_home_flags) if h is True]
        a_scores = [s for s, h in zip(hist_scores, hist_home_flags) if h is False]
        h_avg = sum(h_scores) / len(h_scores) if h_scores else media
        a_avg = sum(a_scores) / len(a_scores) if a_scores else media
        overall_avg = (h_avg + a_avg) / 2 if (h_scores and a_scores) else media

        target_is_home = is_home_flags[i]
        fattore_ct = 1.0
        if overall_avg > 0:
            fattore_ct = (h_avg / overall_avg) if target_is_home else (a_avg / overall_avg)

        # fattore forza avversario calcolato SOLO sullo storico precedente
        valid_ranks = [r for r in hist_opp_ranks if r is not None]
        avg_rank_hist = sum(valid_ranks) / len(valid_ranks) if valid_ranks else None
        target_opp_rank = opponent_rankings[i]

        fattore_fa = 1.0
        if avg_rank_hist and target_opp_rank:
            delta = (target_opp_rank - avg_rank_hist) / opponent_sensitivity
            fattore_fa = max(0.5, min(1.5, 1.0 + delta))

        fattore_granulare_totale = 1.0
        if use_granular_factors:
            for values in (fouls_values, duels_values, offensive_values, rare_events_values,
                           passing_values, defense_rare_values, defensive_actions_values,
                           goals_conceded_values):
                if values is not None:
                    hist_values = values[:i]
                    f = compute_split_factor(hist_values, hist_home_flags, target_is_home)
                    fattore_granulare_totale *= f

        fattore_trend_bt = 1.0
        if use_trend:
            fattore_trend_bt, _, _ = compute_trend_factor(hist_scores, short_window=5, long_window=10,
                                                            trend_intensity=trend_intensity)

        predetto = 1.0 * media * fattore_ct * fattore_fa * fattore_granulare_totale * fattore_trend_bt
        reale = scores[i]
        errore = reale - predetto
        range_conf = dev_std * range_multiplier
        dentro_range = abs(errore) <= range_conf if range_conf > 0 else None

        rows.append({
            'indice': i,
            'partite_storico_usate': m,
            'predetto': predetto,
            'reale': reale,
            'errore': errore,
            'range_conf': range_conf,
            'dentro_range': dentro_range,
        })

    if not rows:
        return {'rows': [], 'mae': None, 'pct_dentro_range': None,
                'half_life': half_life, 'range_multiplier': range_multiplier,
                'opponent_sensitivity': opponent_sensitivity,
                'trend_intensity': trend_intensity}

    mae = sum(abs(r['errore']) for r in rows) / len(rows)
    valid_range_checks = [r['dentro_range'] for r in rows if r['dentro_range'] is not None]
    pct_dentro_range = (sum(valid_range_checks) / len(valid_range_checks) * 100) if valid_range_checks else None

    return {'rows': rows, 'mae': mae, 'pct_dentro_range': pct_dentro_range,
            'half_life': half_life, 'range_multiplier': range_multiplier,
            'opponent_sensitivity': opponent_sensitivity,
            'trend_intensity': trend_intensity}


# Combinazioni di parametri da testare nel grid search. Ogni tupla e':
# (half_life, range_multiplier, opponent_sensitivity, use_granular_factors,
#  use_trend, trend_intensity, etichetta)
#
# GRIGLIA RIDOTTA E MIRATA (25/07, richiesta esplicita utente): analizzando i
# risultati del test su 7 giocatori, le combinazioni migliori ricorrevano
# quasi sempre in una zona ristretta (half_life 9-12, range_mult 1.2-1.4,
# opp_sens 20-29) — le altre combinazioni (half_life 4/6.5, range_mult 1.0)
# non vincevano quasi mai. Ridotta da 48 a questa zona mirata PIU' la nuova
# dimensione trend_intensity, per restare comunque a un numero di
# combinazioni gestibile pur avendo aggiunto una variabile in piu'.
def _build_grid_combinations():
    half_lives = [9.0, 12.0]
    range_mults = [1.2, 1.4, 1.6]  # 1.6 aggiunto: range di default alzato per la copertura
    opp_sens_values = [20.0, 29.0]
    trend_intensities = [0.7, 1.0, 1.3]  # NUOVO: trend attenuato / originale / amplificato
    combos = []
    for hl in half_lives:
        for rm in range_mults:
            for os_ in opp_sens_values:
                for gran in (False, True):
                    for ti in trend_intensities:
                        label_parts = [f"hl={hl}", f"range={rm}x", f"opp_sens={os_}",
                                       f"trend_int={ti}"]
                        if gran:
                            label_parts.append("granulari")
                        combos.append((hl, rm, os_, gran, True, ti, "+".join(label_parts)))
    return combos


GRID_SEARCH_COMBINATIONS = _build_grid_combinations()


def run_grid_search(scores, is_home_flags, opponent_rankings, min_history=6,
                     fouls_values=None, duels_values=None, offensive_values=None,
                     rare_events_values=None, passing_values=None, defense_rare_values=None):
    """Esegue il backtest rigoroso con tutte le combinazioni di parametri in
    GRID_SEARCH_COMBINATIONS e ritorna i risultati ordinati per MAE crescente
    (il migliore per primo). Il 'punteggio' finale usato per il ranking bilancia
    MAE (peggio se alto) e distanza dalla copertura ideale del range (~68%)."""
    results = []
    for half_life, range_mult, opp_sens, use_granular, use_trend, trend_intensity, label in GRID_SEARCH_COMBINATIONS:
        bt = rigorous_backtest(scores, is_home_flags, opponent_rankings,
                                min_history=min_history, half_life=half_life,
                                range_multiplier=range_mult, opponent_sensitivity=opp_sens,
                                fouls_values=fouls_values, duels_values=duels_values,
                                offensive_values=offensive_values,
                                rare_events_values=rare_events_values,
                                passing_values=passing_values,
                                defense_rare_values=defense_rare_values,
                                use_granular_factors=use_granular,
                                use_trend=use_trend,
                                trend_intensity=trend_intensity)
        bt['label'] = label
        if bt['mae'] is not None:
            # Punteggio composito: MAE conta come errore diretto; la distanza dalla
            # copertura ideale (68%, corrispondente a +-1 dev std in una normale)
            # viene sommata con un peso minore, per non premiare range assurdamente
            # larghi che coprirebbero tutto ma sarebbero inutili in pratica.
            coverage_penalty = abs((bt['pct_dentro_range'] or 0) - 68.0) * 0.3
            bt['composite_score'] = bt['mae'] + coverage_penalty
        else:
            bt['composite_score'] = float('inf')
        results.append(bt)

    results.sort(key=lambda r: r['composite_score'])
    return results


def build_prediction(player_slug):
    log("[FASE 1/4] Avvio recupero game log...")
    past_games, future_games = fetch_game_log(player_slug, first=30)
    if not past_games:
        log("[FASE 1/4] INTERROTTO: nessuna partita passata trovata, impossibile procedere oltre.")
        return None
    if not future_games:
        log("[FASE 1/4] ATTENZIONE: nessuna partita futura trovata (anyFutureGames vuoto). "
            "Si procedera' comunque con la storia, ma la predizione finale fallira' "
            "in assenza di un target su cui applicare i fattori.")
        target_competition = None
    else:
        target_game = future_games[0]['playerGameScore']['anyGame']
        target_competition = (target_game.get('competition') or {}).get('slug')
        log(f"[FASE 1/4] Competizione della partita target: {target_competition or 'N/D'}")

        # --- FILTRO SECCO starterOdds (NUOVO): sotto MIN_STARTER_ODDS, il giocatore
        # e' escluso dall'analisi. Controllato qui, PRIMA di scaricare il dettaglio
        # granulare delle 30 partite, per non sprecare query su giocatori scartati.
        target_odds = ((future_games[0]['playerGameScore'].get('anyPlayerGameStats') or {})
                       .get('footballPlayingStatusOdds') or {})
        target_starter_odds_bp = target_odds.get('starterOddsBasisPoints')
        if target_starter_odds_bp is not None:
            target_starter_odds_frac = target_starter_odds_bp / 10000.0
            if target_starter_odds_frac < MIN_STARTER_ODDS:
                log(f"[FASE 1/4] ESCLUSO: starterOdds {target_starter_odds_frac:.0%} "
                    f"sotto la soglia minima {MIN_STARTER_ODDS:.0%} — giocatore non affidabile "
                    f"per essere schierato, analisi interrotta.")
                return {'excluded': True, 'player_slug': player_slug,
                        'exclusion_reason': f"starterOdds {target_starter_odds_frac:.0%} < {MIN_STARTER_ODDS:.0%}"}
        else:
            log("[FASE 1/4] ATTENZIONE: starterOddsBasisPoints non disponibile per la partita "
                "target — impossibile verificare il filtro soglia, si procede comunque "
                "(P(gioca) fara' fallback sul tasso di presenza storico).")

    cache, cache_file = load_cache(player_slug)
    log(f"[FASE 2/4] Cache dettagli caricata da {cache_file} ({len(cache)} voci gia' presenti).")

    # Filtro TIPO COMPETIZIONE: se conosciamo la competizione della partita target,
    # teniamo prima solo le partite storiche della STESSA competizione (le altre
    # rappresentano un contesto diverso — MLS vs Leagues Cup vs nazionale hanno
    # dinamiche di punteggio strutturalmente diverse). Se questo filtro lascia
    # troppo poche partite (meno di min_history), si fa fallback su tutte le
    # competizioni per non restare senza dati.
    MIN_SAME_COMPETITION = 6
    if target_competition:
        same_comp_games = [
            n for n in past_games
            if (n.get('anyGame', {}).get('competition') or {}).get('slug') == target_competition
        ]
        if len(same_comp_games) >= MIN_SAME_COMPETITION:
            log(f"[FASE 2/4] Filtro competizione applicato: {len(same_comp_games)} partite "
                f"'{target_competition}' su {len(past_games)} totali (>= soglia minima "
                f"{MIN_SAME_COMPETITION}, si procede filtrate).")
            past_games = same_comp_games
        else:
            log(f"[FASE 2/4] Filtro competizione NON applicato: solo {len(same_comp_games)} "
                f"partite '{target_competition}' trovate (< soglia minima {MIN_SAME_COMPETITION}) "
                f"— si usa lo storico completo multi-competizione come fallback.")

    # Filtra le partite con punteggio "utilizzabile" (esclude DID_NOT_PLAY E le
    # partite giocate sotto la soglia minima di minutaggio, trattate allo stesso
    # modo: escluse dalla media ma contate nel tasso di presenza storico, perche'
    # rappresentano comunque una circostanza in cui il giocatore non sarebbe
    # stato schierato dall'inizio).
    usable = []
    dnp_count = 0
    low_minutes_count = 0
    total_considered = 0
    other_status_count = {}

    for node in past_games:
        status = node.get('scoreStatus')
        total_considered += 1
        if status == 'DID_NOT_PLAY':
            dnp_count += 1
            continue
        if status in ('FINAL', 'REVIEWING'):
            mins = ((node.get('anyPlayerGameStats') or {}).get('minsPlayed'))
            if mins is not None and mins < MIN_MINUTES_PLAYED:
                low_minutes_count += 1
                continue
            usable.append(node)
        else:
            other_status_count[status] = other_status_count.get(status, 0) + 1
        if len(usable) >= WINDOW_SIZE:
            break

    if not usable:
        log(f"[FASE 2/4] INTERROTTO: nessuna partita con status FINAL/REVIEWING e minutaggio "
            f">= {MIN_MINUTES_PLAYED}' trovata su {total_considered} esaminate "
            f"({dnp_count} DID_NOT_PLAY, {low_minutes_count} sotto soglia minutaggio, "
            f"altri status: {other_status_count}).")
        return None

    # Ordine cronologico: allPlayerGameScores arriva dal piu' recente al piu' vecchio,
    # quindi invertiamo per avere indice 0 = piu' vecchia, ultimo = piu' recente
    usable = list(reversed(usable))

    log(f"[FASE 2/4] OK: finestra di {len(usable)} partite utilizzabili "
        f"(su {total_considered} esaminate, {dnp_count} DID_NOT_PLAY escluse, "
        f"{low_minutes_count} escluse per minutaggio < {MIN_MINUTES_PLAYED}', "
        f"altri status incontrati: {other_status_count or 'nessuno'}).")

    # Scarica il dettaglio granulare per ogni partita della finestra (con cache),
    # OPPURE la salta del tutto se SKIP_GRANULAR_DETAIL e' attivo (per ridurre
    # drasticamente il numero di chiamate GraphQL per giocatore e non saturare
    # il budget di complessita' cumulativo dell'API in questo test multi-giocatore).
    if SKIP_GRANULAR_DETAIL:
        log(f"[FASE 3/4] SALTATA (SKIP_GRANULAR_DETAIL attivo): nessuna chiamata "
            f"dettaglio granulare, i fattori granulari resteranno neutri (1.0) "
            f"per questo test comparativo.")
        details = [None] * len(usable)
    else:
        log(f"[FASE 3/4] Recupero dettaglio granulare per {len(usable)} partite (con cache)...")
        details = []
        detail_failures = 0
        for node in usable:
            score_id = node['id'].replace('So5Score:', '')
            is_final = node.get('scoreStatus') == 'FINAL'
            detail = fetch_game_detail(score_id, cache, is_final)
            if detail is None:
                detail_failures += 1
            details.append(detail)

        save_cache(cache, cache_file)
        log(f"[FASE 3/4] OK: dettaglio recuperato per {len(usable) - detail_failures}/{len(usable)} partite "
            f"({detail_failures} falliti, la formula procedera' comunque usando solo score+contesto base per quelle).")

    # Determina la squadra del giocatore dalla partita piu' recente
    player_team_slug = None
    last_game = usable[-1]['anyGame']
    # Deduciamo la squadra del giocatore guardando quale delle due non cambia
    # tra le varie partite: usiamo l'euristica "squadra che compare in tutte le
    # partite casalinghe e in trasferta piu' di frequente" sui dati raccolti.
    team_counts = {}
    for node in usable:
        g = node['anyGame']
        for side in ('homeTeam', 'awayTeam'):
            t = (g.get(side) or {}).get('slug')
            if t:
                team_counts[t] = team_counts.get(t, 0) + 1
    if team_counts:
        player_team_slug = max(team_counts, key=team_counts.get)

    # Costruisce la serie di score utilizzabili + contesto casa/trasferta + ranking avversario
    scores = []
    is_home_flags = []
    opponent_rankings = []
    own_rankings = []
    fouls_values = []
    duels_values = []
    offensive_values = []
    passing_values = []
    rare_events_values = []
    defense_rare_values = []
    defensive_actions_values = []
    goals_conceded_values = []

    for node, detail in zip(usable, details):
        scores.append(node.get('score', 0.0))
        game = node['anyGame']
        own_rank, opp_rank, is_home = team_ranking_from_game(game, player_team_slug)
        # fallback: se il ranking non e' nel game log base, prova dal dettaglio granulare
        if opp_rank is None and detail:
            own_rank, opp_rank, is_home = team_ranking_from_game(detail['anyGame'], player_team_slug)
        is_home_flags.append(is_home)
        opponent_rankings.append(opp_rank)
        own_rankings.append(own_rank)

        fouls_values.append(extract_group_score(detail, FOULS_STATS))
        duels_values.append(extract_group_score(detail, DUELS_STATS))
        offensive_values.append(extract_group_score(detail, OFFENSIVE_STATS))
        passing_values.append(extract_group_score(detail, PASSING_STATS))
        rare_raw = extract_group_score(detail, RARE_EVENTS_STATS)
        rare_events_values.append(max(-RARE_EVENTS_CAP, min(RARE_EVENTS_CAP, rare_raw)))
        defense_raw = extract_group_score(detail, DEFENSE_RARE_STATS)
        defense_rare_values.append(max(-DEFENSE_RARE_CAP, min(DEFENSE_RARE_CAP, defense_raw)))
        defensive_actions_values.append(extract_group_score(detail, DEFENSIVE_ACTIONS_STATS))
        goals_conceded_raw = extract_group_score(detail, GOALS_CONCEDED_STATS)
        goals_conceded_values.append(max(-GOALS_CONCEDED_CAP, min(GOALS_CONCEDED_CAP, goals_conceded_raw)))

    n = len(scores)
    weights = exponential_weights(n, HALF_LIFE_GAMES)

    media_pesata = weighted_mean(scores, weights)
    dev_std_pesata = weighted_stddev(scores, weights, media_pesata)
    dev_std_trimmed = trimmed_weighted_stddev(scores, weights)

    # --- Fattore casa/trasferta (score totale, gia' esistente) ---
    home_scores = [s for s, h in zip(scores, is_home_flags) if h is True]
    away_scores = [s for s, h in zip(scores, is_home_flags) if h is False]
    home_avg = sum(home_scores) / len(home_scores) if home_scores else media_pesata
    away_avg = sum(away_scores) / len(away_scores) if away_scores else media_pesata
    overall_avg_for_factor = (home_avg + away_avg) / 2 if (home_scores and away_scores) else media_pesata

    # --- Prossima partita: contesto target ---
    log("[FASE 4/4] Calcolo fattori e predizione finale sulla prossima partita target...")
    if not future_games:
        log("[FASE 4/4] INTERROTTO: nessuna partita futura trovata (anyFutureGames vuoto), "
            "impossibile calcolare una predizione senza un target.")
        return None
    next_node = future_games[0]['playerGameScore']
    next_game = next_node['anyGame']
    log(f"[FASE 4/4] Partita target: {(next_game.get('date') or '')[:16]} - "
        f"{(next_game.get('homeTeam') or {}).get('name', '?')} vs "
        f"{(next_game.get('awayTeam') or {}).get('name', '?')}")
    next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(next_game, player_team_slug)

    # se il ranking non e' nel blocco base, scarichiamo il dettaglio (funziona anche per future)
    if next_opp_rank is None:
        next_score_id = next_node['id'].replace('So5Score:', '')
        next_detail = fetch_game_detail(next_score_id, cache, is_final=False)
        if next_detail:
            next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(
                next_detail['anyGame'], player_team_slug)

    fattore_casa_trasferta = 1.0
    if overall_avg_for_factor > 0:
        if next_is_home:
            fattore_casa_trasferta = home_avg / overall_avg_for_factor
        else:
            fattore_casa_trasferta = away_avg / overall_avg_for_factor

    # --- Fattori granulari SEPARATI: falli, duelli, efficacia offensiva ---
    # Ognuno e' un fattore casa/trasferta indipendente, calcolato sui dati REALI
    # del detailedScore delle 14 partite (non stime). Gli eventi rari (rigori,
    # autogol, errori-a-gol) sono gia' stati cappati in fase di estrazione.
    fattore_falli = compute_split_factor(fouls_values, is_home_flags, next_is_home)
    fattore_duelli = compute_split_factor(duels_values, is_home_flags, next_is_home)
    fattore_offensivo = compute_split_factor(offensive_values, is_home_flags, next_is_home)
    fattore_eventi_rari = compute_split_factor(rare_events_values, is_home_flags, next_is_home)
    fattore_passaggio = compute_split_factor(passing_values, is_home_flags, next_is_home)
    fattore_difesa_rari = compute_split_factor(defense_rare_values, is_home_flags, next_is_home)
    fattore_azioni_difensive = compute_split_factor(defensive_actions_values, is_home_flags, next_is_home)
    fattore_gol_subiti = compute_split_factor(goals_conceded_values, is_home_flags, next_is_home)

    # --- Fattore forza avversario (lineare sul ranking assoluto) ---
    # Ranking medio delle 14 partite (tra gli avversari con dato disponibile)
    valid_opp_ranks = [r for r in opponent_rankings if r is not None]
    avg_opp_rank_hist = sum(valid_opp_ranks) / len(valid_opp_ranks) if valid_opp_ranks else None

    fattore_forza_avversario = 1.0
    if avg_opp_rank_hist and next_opp_rank:
        # rank piu' basso = squadra piu' forte. Se il prossimo avversario ha un
        # rank piu' basso (piu' forte) della media storica affrontata, penalizza.
        delta = (next_opp_rank - avg_opp_rank_hist) / OPPONENT_SENSITIVITY
        fattore_forza_avversario = max(0.5, min(1.5, 1.0 + delta))

    # --- P(gioca) ---
    p_gioca = None
    p_source = None
    next_odds = ((next_node.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
    starter_odds = next_odds.get('starterOddsBasisPoints')
    if starter_odds is not None:
        p_gioca = starter_odds / 10000.0
        p_source = f"starterOddsBasisPoints ({starter_odds})"
    else:
        presence_rate = len(usable) / total_considered if total_considered else 1.0
        p_gioca = presence_rate
        p_source = f"tasso di presenza storico ({len(usable)}/{total_considered})"

    # --- Fattore trend (ultime 5 vs ultime 10, stesso pool gia' filtrato) ---
    fattore_trend, trend_avg_short, trend_avg_long = compute_trend_factor(
        scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

    score_atteso = (p_gioca * media_pesata * fattore_casa_trasferta * fattore_forza_avversario
                    * fattore_falli * fattore_duelli * fattore_offensivo * fattore_eventi_rari
                    * fattore_passaggio * fattore_difesa_rari * fattore_azioni_difensive
                    * fattore_gol_subiti * fattore_trend)
    range_conf = dev_std_pesata * RANGE_MULTIPLIER  # moltiplicatore aggiornato dal grid search (24/07)

    # --- Backtest SEMPLICE: riapplica solo la componente media "a ritroso" sull'ultima partita nota ---
    last_real = usable[-1]
    last_real_score = last_real.get('score')
    backtest_prev = usable[:-1]
    backtest_scores = scores[:-1]
    backtest_weights = exponential_weights(len(backtest_scores), HALF_LIFE_GAMES) if backtest_scores else []
    backtest_media = weighted_mean(backtest_scores, backtest_weights) if backtest_scores else None

    # --- Backtest RIGOROSO sui parametri FISSATI (25/07) ---
    # Il grid search cross-player ha gia' individuato la combinazione vincente
    # (vedi costanti HALF_LIFE_GAMES/RANGE_MULTIPLIER/OPPONENT_SENSITIVITY/
    # TREND_INTENSITY sopra). Non serve piu' rieseguire 72 combinazioni ad ogni
    # giocatore ad ogni run — un solo backtest sui parametri fissati, molto
    # piu' veloce, mantenendo comunque MAE/copertura come indicatore di
    # affidabilita' per QUESTO specifico giocatore.
    log("Esecuzione backtest rigoroso sui parametri fissati...")
    rigorous_bt = rigorous_backtest(scores, is_home_flags, opponent_rankings, min_history=6,
                                     half_life=HALF_LIFE_GAMES, range_multiplier=RANGE_MULTIPLIER,
                                     opponent_sensitivity=OPPONENT_SENSITIVITY,
                                     fouls_values=fouls_values, duels_values=duels_values,
                                     offensive_values=offensive_values,
                                     rare_events_values=rare_events_values,
                                     passing_values=passing_values,
                                     defense_rare_values=defense_rare_values,
                                     defensive_actions_values=defensive_actions_values,
                                     goals_conceded_values=goals_conceded_values,
                                     use_granular_factors=True, use_trend=True,
                                     trend_intensity=TREND_INTENSITY)
    rigorous_bt['label'] = (f"hl={HALF_LIFE_GAMES}+range={RANGE_MULTIPLIER}x+"
                            f"opp_sens={OPPONENT_SENSITIVITY}+trend_int={TREND_INTENSITY} (FISSATA)")
    if rigorous_bt['mae'] is not None:
        log(f"Backtest completato: MAE={rigorous_bt['mae']:.2f}, "
            f"copertura={rigorous_bt['pct_dentro_range']:.1f}%")
    else:
        log("Backtest: dati insufficienti (serve più storico).")
    grid_results = [rigorous_bt]  # lista con un solo elemento, per compatibilita' col resto del codice

    result = {
        'player_slug': player_slug,
        'player_team_slug': player_team_slug,
        'window_size_used': n,
        'total_considered': total_considered,
        'dnp_excluded': dnp_count,
        'low_minutes_excluded': low_minutes_count,
        'target_competition': target_competition,
        'scores_used': scores,
        'weights_used': weights,
        'media_pesata': media_pesata,
        'dev_std_pesata': dev_std_pesata,
        'dev_std_trimmed': dev_std_trimmed,
        'home_avg': home_avg,
        'away_avg': away_avg,
        'fattore_casa_trasferta': fattore_casa_trasferta,
        'avg_opp_rank_hist': avg_opp_rank_hist,
        'next_opp_rank': next_opp_rank,
        'next_own_rank': next_own_rank,
        'next_is_home': next_is_home,
        'fattore_forza_avversario': fattore_forza_avversario,
        'fattore_falli': fattore_falli,
        'fattore_duelli': fattore_duelli,
        'fattore_offensivo': fattore_offensivo,
        'fattore_eventi_rari': fattore_eventi_rari,
        'fattore_passaggio': fattore_passaggio,
        'fattore_difesa_rari': fattore_difesa_rari,
        'fattore_azioni_difensive': fattore_azioni_difensive,
        'fattore_gol_subiti': fattore_gol_subiti,
        'fattore_trend': fattore_trend,
        'trend_avg_short': trend_avg_short,
        'trend_avg_long': trend_avg_long,
        'p_gioca': p_gioca,
        'p_source': p_source,
        'score_atteso': score_atteso,
        'range_conf': range_conf,
        'next_game': next_game,
        'backtest_last_real_score': last_real_score,
        'backtest_media_pesata_precedente': backtest_media,
        'rigorous_backtest': rigorous_bt,
        'grid_results': grid_results,
        'usable_nodes': usable,
    }
    return result


def format_output(result):
    lines = []
    lines.append("=" * 70)
    lines.append(f"TOOL_FORMAZIONE_OWUSU - Prototipo v1")
    lines.append(f"Giocatore: {result['player_slug']} (squadra: {result['player_team_slug']})")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("=" * 70)

    lines.append("")
    lines.append("--- FINESTRA DI ANALISI ---")
    lines.append(f"Partite considerate: {result['total_considered']}")
    lines.append(f"Escluse (DID_NOT_PLAY): {result['dnp_excluded']}")
    lines.append(f"Escluse (minutaggio < {MIN_MINUTES_PLAYED}', subentri): {result['low_minutes_excluded']}")
    lines.append(f"Competizione partita target: {result['target_competition'] or 'N/D'} "
                 f"(finestra filtrata per stessa competizione quando ci sono abbastanza dati)")
    lines.append(f"Partite usate nella media (dalla piu' vecchia alla piu' recente):")
    for node, s, w in zip(result['usable_nodes'], result['scores_used'], result['weights_used']):
        g = node['anyGame']
        date = (g.get('date') or '')[:10]
        home = (g.get('homeTeam') or {}).get('code', '?')
        away = (g.get('awayTeam') or {}).get('code', '?')
        comp = (g.get('competition') or {}).get('slug', '?')
        lines.append(f"  {date} | {home} vs {away} | {comp} | score={s:.1f} | peso={w:.3f}")

    lines.append("")
    lines.append("--- CALCOLO FATTORI ---")
    lines.append(f"Media pesata esponenziale (half-life {HALF_LIFE_GAMES} partite): {result['media_pesata']:.2f}")
    lines.append(f"Deviazione standard pesata: {result['dev_std_pesata']:.2f}")
    if result['dev_std_trimmed'] is not None:
        lines.append(f"Deviazione standard pesata TRIMMED (esclusi min/max della finestra): "
                     f"{result['dev_std_trimmed']:.2f} (differenza: "
                     f"{result['dev_std_pesata'] - result['dev_std_trimmed']:+.2f})")
    else:
        lines.append("Deviazione standard trimmed: N/D (servono almeno 5 partite distinte)")
    lines.append(f"Media score in casa: {result['home_avg']:.2f} | Media score fuori casa: {result['away_avg']:.2f}")
    lines.append(f"Fattore casa/trasferta applicato: {result['fattore_casa_trasferta']:.3f} "
                 f"({'CASA' if result['next_is_home'] else 'TRASFERTA'} nella prossima partita)")
    opp_rank_hist_str = f"{result['avg_opp_rank_hist']:.1f}" if result['avg_opp_rank_hist'] else "N/D"
    lines.append(f"Ranking medio avversari affrontati (storico): {opp_rank_hist_str}")
    lines.append(f"Ranking prossimo avversario: {result['next_opp_rank']}")
    lines.append(f"Fattore forza avversario applicato: {result['fattore_forza_avversario']:.3f}")
    lines.append(f"Fattore falli (casa/trasferta, da dati reali): {result['fattore_falli']:.3f}")
    lines.append(f"Fattore duelli (casa/trasferta, da dati reali): {result['fattore_duelli']:.3f}")
    lines.append(f"Fattore efficacia offensiva (casa/trasferta, da dati reali): {result['fattore_offensivo']:.3f}")
    lines.append(f"Fattore eventi rari (rigori/autogol/errori, con cap): {result['fattore_eventi_rari']:.3f}")
    lines.append(f"Fattore passaggio (accurate_pass/final_third/att_assist): {result['fattore_passaggio']:.3f}")
    lines.append(f"Fattore difesa/eventi rarissimi (double-double, tackle, ecc., con cap): {result['fattore_difesa_rari']:.3f}")
    lines.append(f"Fattore azioni difensive (won_tackle/blocked_cross/outfielder_block): {result['fattore_azioni_difensive']:.3f}")
    lines.append(f"Fattore gol subiti (goals_conceded, con cap): {result['fattore_gol_subiti']:.3f}")
    if result['trend_avg_short'] is not None:
        lines.append(f"Fattore trend (media ultime 5: {result['trend_avg_short']:.1f} vs "
                     f"media ultime 10: {result['trend_avg_long']:.1f}): {result['fattore_trend']:.3f}")
    else:
        lines.append("Fattore trend: N/D (servono almeno 10 partite nella finestra)")
    lines.append(f"P(gioca): {result['p_gioca']:.2%} (fonte: {result['p_source']})")

    lines.append("")
    lines.append("--- PROSSIMA PARTITA ---")
    ng = result['next_game']
    lines.append(f"Data: {(ng.get('date') or '')[:16]}")
    lines.append(f"Casa: {(ng.get('homeTeam') or {}).get('name', '?')} | "
                 f"Trasferta: {(ng.get('awayTeam') or {}).get('name', '?')}")
    lines.append(f"Competizione: {(ng.get('competition') or {}).get('slug', '?')}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PREDIZIONE")
    lines.append("=" * 70)
    lines.append(f"Score atteso: {result['score_atteso']:.1f} +/- {result['range_conf']:.1f}")
    lines.append(f"  (range: {result['score_atteso'] - result['range_conf']:.1f} - "
                 f"{result['score_atteso'] + result['range_conf']:.1f})")

    lines.append("")
    lines.append("--- BACKTEST SEMPLICE (verifica su ultima partita reale nota) ---")
    if result['backtest_media_pesata_precedente'] is not None:
        lines.append(f"Media pesata calcolata SENZA l'ultima partita: "
                     f"{result['backtest_media_pesata_precedente']:.2f}")
        lines.append(f"Punteggio REALE ottenuto in quella partita: "
                     f"{result['backtest_last_real_score']:.1f}")
        errore = result['backtest_last_real_score'] - result['backtest_media_pesata_precedente']
        lines.append(f"Errore (reale - predetto, solo componente media, senza fattori "
                     f"casa/trasferta/avversario applicati a ritroso): {errore:+.1f}")
        lines.append("NOTA: questo backtest confronta solo la componente 'media pesata' con "
                     "il punteggio reale, senza applicare P(gioca)/fattore avversario/casa-trasferta "
                     "storici a quella specifica partita passata. Vedi sezione successiva per il "
                     "backtest rigoroso che applica l'intera formula.")
    else:
        lines.append("Dati insufficienti per il backtest.")

    lines.append("")
    lines.append("--- PARAMETRI DEL MODELLO (fissati, 25/07) ---")
    lines.append(f"half_life={HALF_LIFE_GAMES}, range_mult={RANGE_MULTIPLIER}, "
                 f"opp_sens={OPPONENT_SENSITIVITY}, trend_int={TREND_INTENSITY}")
    lines.append("Combinazione scelta tramite grid search aggregato su 14 giocatori "
                 "(MAE medio 18.13, copertura media 68.93%). Il grid search non gira piu' "
                 "ad ogni esecuzione: questi valori sono ora costanti nel codice.")

    lines.append("")
    lines.append("--- BACKTEST RIGOROSO (migliore combinazione dal grid search) ---")
    rbt = result.get('rigorous_backtest', {})
    rbt_rows = rbt.get('rows', [])
    if rbt_rows:
        lines.append(f"Combinazione usata: '{rbt.get('label', '?')}' "
                     f"(half_life={rbt.get('half_life')}, range_mult={rbt.get('range_multiplier')}, "
                     f"opp_sens={rbt.get('opponent_sensitivity')}, trend_int={rbt.get('trend_intensity')})")
        lines.append(f"Partite testate: {len(rbt_rows)} (min. 6 partite di storico richieste per ognuna)")
        lines.append(f"P(gioca) fissato a 100% per ogni test (sappiamo gia' che ha giocato, essendo storico)")
        lines.append("")
        lines.append(f"{'idx':>4} {'storico':>8} {'predetto':>9} {'reale':>7} {'errore':>8} {'range':>7} {'in_range':>9}")
        for r in rbt_rows:
            in_range_str = ('SI' if r['dentro_range'] else 'NO') if r['dentro_range'] is not None else 'N/D'
            lines.append(f"{r['indice']:>4} {r['partite_storico_usate']:>8} {r['predetto']:>9.1f} "
                         f"{r['reale']:>7.1f} {r['errore']:>+8.1f} {r['range_conf']:>7.1f} {in_range_str:>9}")
        lines.append("")
        lines.append(f"MAE (errore assoluto medio): {rbt['mae']:.2f}")
        if rbt['pct_dentro_range'] is not None:
            lines.append(f"% di volte in cui il punteggio reale rientra nel range di confidenza "
                         f"predetto: {rbt['pct_dentro_range']:.1f}%")
        lines.append("")
        lines.append("NOTA: questo e' il backtest rigoroso vero e proprio — per ogni partita "
                     "storica, la formula COMPLETA (media pesata + fattore casa/trasferta + "
                     "fattore forza avversario) viene ricalcolata usando SOLO i dati disponibili "
                     "PRIMA di quella partita, poi confrontata con lo score reale ottenuto. "
                     "I parametri sono FISSATI (25/07) tramite grid search aggregato su 14 "
                     "giocatori — non variano piu' da esecuzione a esecuzione.")
    else:
        lines.append("Dati insufficienti per il backtest rigoroso (serve più storico, minimo 6+1 partite).")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    # Se TARGET_SLUG e' impostata (uso in job matrix separati, uno per giocatore,
    # cosi' ognuno riparte con un budget di complessita' API fresco), elabora
    # SOLO quel giocatore. Altrimenti usa la lista completa PLAYER_SLUGS.
    target_slug = os.environ.get('TARGET_SLUG', '').strip()
    slugs_to_process = [target_slug] if target_slug else PLAYER_SLUGS

    log("Avvio test centrocampista/i MLS in_season Tool_formazione (prototipo)...")
    mode_str = f"modalita job singolo: {target_slug}" if target_slug else "lista completa"
    log(f"Config: {len(slugs_to_process)} giocatori da processare ({mode_str}), "
        f"WINDOW_SIZE={WINDOW_SIZE} HALF_LIFE_GAMES={HALF_LIFE_GAMES} "
        f"RANGE_MULTIPLIER={RANGE_MULTIPLIER} MIN_STARTER_ODDS={MIN_STARTER_ODDS:.0%}")
    log(f"SORARE_COOKIE presente: {bool(COOKIES)} (lunghezza: {len(COOKIES)})")
    log(f"curl_cffi disponibile: {_HAS_CURL_CFFI}")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    all_sections = []
    summary_rows = []

    for idx, slug in enumerate(slugs_to_process, 1):
        if idx > 1:
            pause_s = 10.0  # pausa base tra giocatori
            log(f"Pausa di {pause_s}s prima del prossimo giocatore...")
            time.sleep(pause_s)

        log(f"\n{'='*70}\n[{idx}/{len(slugs_to_process)}] Elaborazione giocatore: {slug}\n{'='*70}")

        # Retry progressivo se il primo tentativo fallisce (es. per il limite di
        # complessita' dell'API): 10s, poi 20s, poi 40s di attesa tra i tentativi,
        # fino a un totale cumulativo di attesa di circa 60s, poi si desiste e si
        # passa comunque al giocatore successivo (senza bloccare l'intero test).
        result = None
        last_exception = None
        retry_delays = [10.0, 20.0, 40.0]
        attempt = 0
        cumulative_wait = 0.0

        while True:
            attempt += 1
            try:
                result = build_prediction(slug)
                last_exception = None
            except Exception:
                import traceback
                last_exception = traceback.format_exc()
                result = None

            # Successo (anche se escluso per starterOdds, quello NON e' un fallimento
            # tecnico e non va ritentato) o eccezione irrecuperabile: esci dal ciclo.
            if result is not None or attempt > len(retry_delays):
                break

            delay = retry_delays[attempt - 1]
            if cumulative_wait + delay > 60.0:
                log(f"[{slug}] Tetto di attesa cumulativa (~60s) raggiunto, "
                    f"nessun altro tentativo.")
                break

            log(f"[{slug}] Tentativo {attempt} fallito (risultato vuoto/eccezione), "
                f"riprovo tra {delay:.0f}s (attesa cumulativa finora: {cumulative_wait:.0f}s)...")
            time.sleep(delay)
            cumulative_wait += delay

        if last_exception:
            log(f"[ECCEZIONE FATALE per {slug}] Vedi traceback completo sotto:")
            print(last_exception)
            err_path = os.path.join(OUTPUT_DIR, f'ERRORE_{slug}_{datetime.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")}.txt')
            with open(err_path, 'w', encoding='utf-8') as f:
                f.write(last_exception)
            log(f"Traceback salvato in: {err_path}")
            summary_rows.append((slug, 'ERRORE', None, None, str(last_exception).splitlines()[-1][:60]))
            all_sections.append(f"\n{'#'*70}\n# {slug}: ERRORE (vedi log/traceback)\n{'#'*70}\n")
            continue

        if result is None:
            log(f"[{slug}] Impossibile generare la predizione (dati insufficienti dopo {attempt} tentativi).")
            summary_rows.append((slug, 'DATI INSUFFICIENTI', None, None, f'{attempt} tentativi'))
            all_sections.append(f"\n{'#'*70}\n# {slug}: DATI INSUFFICIENTI (dopo {attempt} tentativi)\n{'#'*70}\n")
            continue

        if result.get('excluded'):
            log(f"[{slug}] ESCLUSO: {result.get('exclusion_reason')}")
            summary_rows.append((slug, 'ESCLUSO', None, None, result.get('exclusion_reason', '')))
            all_sections.append(f"\n{'#'*70}\n# {slug}: ESCLUSO — {result.get('exclusion_reason')}\n{'#'*70}\n")
            continue

        output_text = format_output(result)
        all_sections.append(f"\n{'#'*70}\n# GIOCATORE: {slug}\n{'#'*70}\n" + output_text)
        summary_rows.append((slug, 'OK', result.get('score_atteso'), result.get('range_conf'),
                              result.get('target_competition', '')))
        log(f"[{slug}] OK: score atteso {result.get('score_atteso'):.1f} +/- {result.get('range_conf'):.1f}")

    # --- Riepilogo comparativo in cima al file ---
    # NUOVO (25/07): tiering ordinato per score atteso decrescente, con
    # "projected score" in formato compatto (arrotondato + range) invece del
    # semplice atteso/range separati — numero secco e leggibile a colpo
    # d'occhio, come richiesto dall'utente.
    ok_rows = [r for r in summary_rows if r[1] == 'OK']
    other_rows = [r for r in summary_rows if r[1] != 'OK']
    ok_rows.sort(key=lambda r: r[2] if r[2] is not None else -1, reverse=True)

    summary_lines = []
    summary_lines.append("=" * 70)
    summary_lines.append("CONSIGLIO CENTROCAMPISTI — ORDINATO PER PROJECTED SCORE")
    summary_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    summary_lines.append(f"Parametri fissi per tutti: half_life={HALF_LIFE_GAMES}, "
                         f"range_mult={RANGE_MULTIPLIER}, min_starter_odds={MIN_STARTER_ODDS:.0%}")
    summary_lines.append("=" * 70)
    for idx, (slug, status, atteso, rng, note) in enumerate(ok_rows, 1):
        low = round(atteso - rng)
        high = round(atteso + rng)
        summary_lines.append(f"{idx}) {slug}: {round(atteso)} pt attesi ({low}-{high})")
    if other_rows:
        summary_lines.append("")
        summary_lines.append("--- Esclusi / non disponibili ---")
        for slug, status, atteso, rng, note in other_rows:
            summary_lines.append(f"{slug}: {status} — {note}")
    summary_lines.append("=" * 70)

    final_text = "\n".join(summary_lines) + "\n" + "\n".join(all_sections)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    file_suffix = target_slug if target_slug else 'all'
    out_path = os.path.join(OUTPUT_DIR, f'prediction_{file_suffix}_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(final_text)

    log(f"\nOutput completo scritto in: {out_path}")
    log(f"Dump diagnostici di tutte le chiamate GraphQL salvati in: {DEBUG_DIR}/")
    print("\n" + "\n".join(summary_lines))
    print(f"\n[Dettaglio completo di ogni giocatore salvato nel file: {out_path}]")


if __name__ == '__main__':
    main()
