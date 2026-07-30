"""
test_gk (test portiere MLS — prototipo, clone adattato da test_def.py)

Quarto ruolo: PORTIERE. Il piu' diverso strutturalmente dagli altri tre.
Confermato su 2 detailedScore reali (Hugo Lloris, Matt Turner) + screenshot
UI: il set del portiere e' un SOTTOINSIEME ridotto rispetto agli altri
ruoli, con le 8 voci GOALKEEPING finalmente valorizzate (erano sempre
scartate/a 0 per gli altri ruoli).

DIFFERENZE STRUTTURALI CHIAVE rispetto agli altri ruoli:
- NESSUNA categoria DEFENDING (a differenza di difensore/centrocampista)
- NESSUN gruppo POSSESSION_STATS (duel_won/duel_lost/interception_won/poss_won
  ASSENTI — solo poss_lost_ctrl esiste nella categoria POSSESSION)
- PASSING_STATS ridotto: niente long_pass_own_to_opp_success (quello era
  solo del difensore)
- was_fouled ASSENTE (come nel difensore, confermato da UI)
- penalty_save ESCLUSO dalla formula su richiesta esplicita utente: vale
  +25 standalone o +10 extra se combinato con clean sheet, ma e' un evento
  troppo raro per giustificare la complessita' di modellarlo
- **clean_sheet_60 ha SEMPRE totalScore=0 come riga nel detailedScore** — il
  bonus (+25 circa) e' incorporato nel level_score stesso (~35 normale,
  ~60 con clean sheet nei primi 60'). Questo e' l'aspetto PIU' IMPORTANTE
  da modellare correttamente: va rilevato dalla DIFFERENZA nel level_score
  storico (o dal flag clean_sheet_60==1 nel dettaglio) e trattato come
  fattore/bonus separato nella formula, NON tramite il normale
  extract_group_score sui gruppi granulari (che leggerebbe sempre 0).

Formula IN PRODUZIONE (FIX 25/07: i fattori granulari sono stati rimossi
dallo score_atteso -- la calibrazione che ha fissato i parametri li
escludeva gia' (use_granular_factors=False, peggioravano il MAE per questo
ruolo), ma la produzione li applicava comunque prima di questo fix. Restano
calcolati e mostrati in output SOLO a scopo diagnostico):
  score_atteso = P(gioca) x media_pesata_esponenziale(N partite)
                 x fattore_casa_trasferta x fattore_forza_avversario
                 x fattore_trend
                 [+ bonus_clean_sheet gia' incorporato nella media pesata, vedi sotto]
  range_confidenza = +/- dev_std_pesata * RANGE_MULTIPLIER

PARAMETRI: riusati gli stessi valori dei difensori come punto di partenza
(HALF_LIFE_GAMES=9.0, RANGE_MULTIPLIER=1.2, OPPONENT_SENSITIVITY=29.0,
TREND_INTENSITY=1.3) — da ricalibrare con un grid search dedicato ai
portieri quando avremo piu' giocatori di test.

Cache incrementale del game log integrata (stessa logica di
centrocampisti/difensori/attaccanti).

Giocatore di test: Hugo Lloris (Goalkeeper, slug hugo-lloris).

Filtro secco su starterOddsBasisPoints della partita target — se <
MIN_STARTER_ODDS (70%), il giocatore viene ESCLUSO dall'analisi.
"""
import os
import sys
import json
import math
import time
import tempfile
import datetime
import requests

# NUOVO (26/07, monitoraggio MAE live): modulo condiviso nella stessa
# cartella, additivo/diagnostico -- vedi formazione_kleague/predict/
# live_prediction_log.py per motivazione e dettagli. sys.path[0] e' gia'
# la cartella di questo script quando lanciato come `python
# formazione_kleague/predict/test_gk.py`, quindi l'import diretto funziona a
# prescindere dalla cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_prediction_log import log_live_prediction
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import opponent_strength

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/graphql'

# CALIBRATION_MODE (25/07, grid search allargato): se attivo, legge la lista
# GLOBALE (tutti i portieri MLS di qualita', non solo posseduti) invece di
# quella dei posseduti, e riesegue il grid search COMPLETO (72 combinazioni)
# invece del singolo backtest sui parametri gia' fissati -- usato SOLO per
# la ricalibrazione one-shot su piu' dati, mai in produzione.
CALIBRATION_MODE = os.environ.get('CALIBRATION_MODE', 'no').strip().lower() in ('1', 'true', 'si', 'yes')

DISCOVERY_FILE = os.path.join(
    'formazione_kleague/output/kleague_gk_discovery_global' if CALIBRATION_MODE else 'formazione_kleague/output/kleague_gk_discovery',
    'player_slugs.json')

# Fallback statico SOLO se kleague_gk_discovery/player_slugs.json non esiste
# ancora (nessuna discovery portieri ancora fatta): singolo giocatore
# di test, Mohamed Farsi.
_FALLBACK_PLAYER_SLUGS = [
    'hugo-lloris',
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

WINDOW_SIZE = 30  # AMPLIATO (29/07) da 15 a 30 su richiesta esplicita dell'utente, dopo il caso Daniel De Sousa Brito -- mantenuto lo stesso half_life per ruolo, l'allargamento serve a dare piu' contesto storico alla media pesata
HALF_LIFE_GAMES = 6.0  # AGGIORNATO (29/07): ridotto da 12.0 a 6.0 SOLO per GK, su richiesta esplicita dell'utente dopo un caso reale (Daniel De Sousa Brito, media pesata 46.6 vs media reale ultime 11 partite 41.2 -- il modello si aspettava un punteggio del 29% sopra lo standard recente senza nessun segnale di miglioramento). Verificato con backtest rigoroso pooled su 66 portieri/538 partite (16 campionati): l'intera griglia half_life 4-30 sta in una forbice di MAE dell'1.4%, quindi accorciarlo non peggiora sensibilmente l'accuratezza aggregata mentre risolve l'incoerenza logica sui casi con un tratto di forma alta ormai superato nella finestra storica.
RANGE_MULTIPLIER = 1.4  # AGGIORNATO (ricalibrazione su 10 campionati, sessione 27/07): range_multiplier 1.6->1.4, MAE 18.30 vs 18.32 (-0.1%, scarto minimo ma applicato su richiesta esplicita dell'utente, stesso principio gia' seguito per altri parametri in questo progetto).
OPPONENT_SENSITIVITY = 29.0  # AGGIORNATO (26/07): grid search allargato K League su 3 portieri qualificati (>=3 partite test, campione MOLTO piccolo -- MAE 17.47 vs 17.6x circa con 20.0). Applicato per coerenza con MLS GK (stesso fix, stesso giorno) e con opp_sens=29.0 confermato su TUTTI gli altri ruoli K League (MID/FWD gia' a 29.0) tranne DEF (vedi nota separata, segnale opposto non applicato).
SPLIT_FACTOR_SCALE_PER_STD = 0.05  # NUOVO (25/07, audit logica): sensibilita' dei fattori granulari, in %/deviazione standard storica del gruppo (sostituisce la vecchia scala fissa 1%/punto)
TREND_INTENSITY = 0.7  # FISSATO (25/07): idem
MIN_MINUTES_PLAYED = 60  # partite giocate sotto questa soglia (subentri) escluse dalla finestra
MIN_STARTER_ODDS = 0.0  # DISATTIVATO (28/07, richiesta esplicita utente): era un secondo filtro starter-odds fisso al 70%, indipendente e non collegato alla soglia scelta in discovery_fixture.py -- anche con starter_odds_min=0 nel workflow, questo continuava a scartare in silenzio chi era sotto 70%. discovery_fixture.py applica gia' il filtro configurabile a monte, questo era ridondante.
SKIP_GRANULAR_DETAIL = False  # RIPRISTINATO (24/07): con la strategia GitHub Actions matrix, ogni giocatore gira in un job/processo SEPARATO con budget di complessita' fresco — il problema di saturazione cumulativa (che colpiva il 2o+ giocatore in un unico processo) non si presenta piu'. I fattori granulari (falli/duelli/passaggio/ecc.) sono quindi di nuovo calcolati per ogni giocatore.

OUTPUT_DIR = 'formazione_kleague/output/kleague_gk_calibration' if CALIBRATION_MODE else 'formazione_kleague/output/kleague_gk_all'
CACHE_DIR = os.path.join(OUTPUT_DIR, '.cache')

# Circuit breaker per blocco CloudFront (29/07, fix reale: una run e' passata
# da ~4 a 22 minuti perche' CloudFront ha bloccato TUTTE le chiamate di uno
# shard con HTTP 403 "Request blocked" -- non un errore per-giocatore, un
# blocco a livello di IP/sessione che non si risolve MAI ritentando lo
# STESSO giocatore. Ogni giocatore di quello shard bruciava comunque i 3
# tentativi (~60s) prima di arrendersi, perche' ogni giocatore e' un
# PROCESSO SEPARATO (vedi TARGET_SLUG nel workflow) senza stato condiviso.
# Il marker vive in /tmp (non nel repo, non committato) -- sopravvive tra i
# processi separati della STESSA job (stesso runner) ma non tra run diverse
# (runner nuovo ogni volta). Appena la PRIMA chiamata rileva la firma
# CloudFront, i tentativi successivi per QUALSIASI giocatore restante in
# questa job diventano un singolo tentativo secco, senza attesa.
_CIRCUIT_BREAKER_PATH = '/tmp/sorare_cloudfront_block_kleague_gk.marker'


def _circuit_breaker_tripped():
    return os.path.exists(_CIRCUIT_BREAKER_PATH)


def _trip_circuit_breaker(reason):
    if not _circuit_breaker_tripped():
        try:
            with open(_CIRCUIT_BREAKER_PATH, 'w', encoding='utf-8') as f:
                f.write(reason)
        except OSError:
            pass

# Flag "non ritentare" (29/07, fix reale: molti retry da 60s sprecati su
# giocatori con storico REALMENTE insufficiente -- es. panchinari con quasi
# solo DID_NOT_PLAY -- che non cambia riprovando la stessa query pochi
# secondi dopo. Il loop di retry in main() lo controlla per uscire subito
# invece di aspettare fino a 60s per un fallimento STRUTTURALE (non
# transitorio come un 403/timeout, dove riprovare puo' davvero aiutare).
_STRUCTURAL_INSUFFICIENCY = False

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
    print(f"[{ts}] [test_gk] {msg}")


# Pacing ADATTIVO delle chiamate GraphQL (29/07 notte, misurato sui log della
# run 30501219037): ogni giocatore e' un PROCESSO separato e fa ~4,6 chiamate
# GraphQL, quindi con la pausa FISSA di 0,5s se ne andavano ~2,3s per giocatore
# di sola attesa autoimposta -- su 865 giocatori, ~2000 secondi dei ~5400 di
# lavoro totale della fase predict, cioe' la voce di costo piu' grande rimasta.
# Nello stesso log: UN solo 429 su 106 chiamate, quindi il margine c'era.
#
# Ora la pausa PARTE bassa e si alza da sola al primo 429, con lo stato
# condiviso su file tra i processi dello stesso runner (ogni giocatore e' un
# processo nuovo: senza condividerlo, ognuno ripartirebbe dal valore basso e
# l'adattamento non servirebbe a niente). Se Sorare protesta la pipeline
# rallenta da sola fino al valore prudente di prima, invece di accumulare
# errori: il caso peggiore e' il comportamento precedente, non uno peggiore.
MIN_QUERY_INTERVAL_SECONDS = 0.2  # pausa di PARTENZA tra chiamate consecutive
MAX_QUERY_INTERVAL_SECONDS = 0.8  # tetto, raggiunto dopo alcuni 429
_PACING_FILE = os.path.join(
    os.environ.get('RUNNER_TEMP') or tempfile.gettempdir(), 'sorare_pacing.txt')
_last_query_ts = [0.0]


def _pacing_corrente():
    try:
        with open(_PACING_FILE, encoding='utf-8') as f:
            return min(MAX_QUERY_INTERVAL_SECONDS,
                       max(MIN_QUERY_INTERVAL_SECONDS, float(f.read().strip())))
    except (OSError, ValueError):
        return MIN_QUERY_INTERVAL_SECONDS


def _rallenta_pacing():
    """Alza la pausa (e la rende visibile ai processi successivi dello stesso
    runner). Chiamata solo quando Sorare risponde 429."""
    nuovo = min(MAX_QUERY_INTERVAL_SECONDS, _pacing_corrente() * 2)
    try:
        with open(_PACING_FILE, 'w', encoding='utf-8') as f:
            f.write(f'{nuovo}')
    except OSError:
        pass
    return nuovo


def _throttle_query():
    intervallo = _pacing_corrente()
    elapsed = time.time() - _last_query_ts[0]
    if elapsed < intervallo:
        time.sleep(intervallo - elapsed)
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
                _nuovo_pacing = _rallenta_pacing()
                log(f"[GraphQL 429] {label} tentativo {attempt+1}/5, attesa {sleep_s:.1f}s "
                    f"(pacing alzato a {_nuovo_pacing:.2f}s) (dump: {debug_file})")
                time.sleep(sleep_s)
                backoff *= 2
                continue

            if resp.status_code >= 400:
                log(f"[GraphQL ERRORE] {label} HTTP {resp.status_code} | dump completo: {debug_file}")
                log(f"[GraphQL ERRORE] {label} body (primi 1500 char): {resp.text[:1500]}")
                if resp.status_code == 403 and ('cloudfront' in resp.text.lower() or 'request blocked' in resp.text.lower()):
                    if not _circuit_breaker_tripped():
                        log(f"[CIRCUIT BREAKER] Blocco CloudFront rilevato (HTTP 403, 'Request blocked') -- "
                            f"non e' un errore per-giocatore, e' un blocco IP/sessione che ritentare non risolve. "
                            f"Disattivo i retry con attesa per il resto di questa job.")
                    _trip_circuit_breaker(f"HTTP 403 CloudFront su {label}")
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
    activeClub { slug }
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
# CACHE INCREMENTALE DEL GAME LOG (NUOVO, 25/07, richiesta esplicita utente:
# integrata di default fin dal primo script portieri, per essere testata
# gia' durante la calibrazione dei parametri).
#
# Problema risolto: fetch_game_log() riscaricava SEMPRE tutte le `first`
# partite storiche (fino a 30) ad ogni run, anche quelle gia' viste e con
# status FINAL (che non cambia mai piu'). Con la cache, una volta che una
# partita e' FINAL viene salvata su disco e non richiede piu' una nuova
# query completa per essere recuperata nelle run successive — si scarica
# sempre un lotto RIDOTTO di partite recenti (GAME_LOG_REFRESH_COUNT) per
# scoprire eventuali novita', e si integra col resto gia' in cache.
#
# Cache separata da quella dei DETTAGLI granulari (fetch_game_detail sopra,
# gia' esistente) — questa e' per il game log BASE (score, data, status,
# minutaggio, teams), non il detailedScore.
# ---------------------------------------------------------------------------

GAME_LOG_CACHE_DIR = os.path.join(OUTPUT_DIR, '.game_log_cache')
GAME_LOG_REFRESH_COUNT = 2  # ABBASSATO (25/07): tool usato con cadenza settimanale (1 partita MLS/settimana per squadra), 2 basta a coprire l'ultima giornata + margine, riduce ulteriormente le query rispetto a 5


def load_game_log_cache(player_slug):
    """Carica la cache del game log per un giocatore: dict {game_score_id: node}.
    Nodi con scoreStatus FINAL restano validi indefinitamente; nodi con altri
    stati (REVIEWING, DID_NOT_PLAY nella finestra corrente, ecc.) vengono
    comunque tenuti ma verranno sovrascritti se ririscaricati."""
    if not os.path.exists(GAME_LOG_CACHE_DIR):
        os.makedirs(GAME_LOG_CACHE_DIR)
    cache_file = os.path.join(GAME_LOG_CACHE_DIR, f'{player_slug}_gamelog.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            try:
                return json.load(f), cache_file
            except json.JSONDecodeError:
                return {}, cache_file
    return {}, cache_file


def save_game_log_cache(cache, cache_file):
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# Paginazione del game log (29/07 notte, bug REALE trovato sui dump .debug/
# committati). La query allPlayerGameScores ha una complessita' di ~28 per
# partita richiesta piu' ~130 di base, contro un tetto di complessita' 500 per
# le chiamate senza APIKEY: misurato, first=30 -> "complexity of 970, which
# exceeds max complexity of 500", first=60 -> 1812. Con WINDOW_SIZE=30 il
# "fetch ampio" sotto chiede 60 partite, quindi NON E' MAI RIUSCITO -- per
# nessun giocatore, in nessuna run. Due conseguenze reali, entrambe osservate:
#   - i giocatori con cache insufficiente restavano senza storico, e da qui i
#     file ERRORE_<slug>.txt (UnboundLocalError su presence_rate) e la loro
#     assenza dai consigli;
#   - ogni tentativo bruciava il retry esterno da 10+20+40s, ~70s a giocatore
#     di tempo puro buttato: era la voce di costo dominante della fase predict.
# Qui la stessa finestra viene chiesta in pagine abbastanza piccole da stare
# sotto il tetto. I dati raccolti sono gli stessi (stesse partite, stesso
# ordine dall'API), solo divisi in piu' round-trip.
PAGINA_GAME_LOG = 10  # 130 + 28*10 = ~410, con margine sotto il tetto
                      # di 500 (il pageInfo aggiunto costa qualcosa a
                      # sua volta: una pagina rifiutata costa molto piu'
                      # di una pagina in piu')

ALL_GAME_SCORES_QUERY_PAGINATO = ALL_GAME_SCORES_QUERY.replace(
    'query AllPlayerGameScores($slug: String!, $first: Int!) {',
    'query AllPlayerGameScores($slug: String!, $first: Int!, $after: String) {',
).replace(
    'allPlayerGameScores(first: $first) {',
    'allPlayerGameScores(first: $first, after: $after) {\n      pageInfo { hasNextPage endCursor }',
)


def fetch_game_scores(slug, fetch_count):
    """Come graphql_query(ALL_GAME_SCORES_QUERY, ...) ma chiede le partite in
    pagine sotto il tetto di complessita'. Ritorna la STESSA struttura della
    chiamata singola, cosi' il codice a valle non cambia di una riga.

    Se la prima pagina fallisce (es. l'API non accettasse after/pageInfo) si
    ripiega sulla chiamata singola di prima: il caso peggiore possibile e'
    esattamente il comportamento di oggi, non uno peggiore."""
    if fetch_count <= PAGINA_GAME_LOG:
        return graphql_query(ALL_GAME_SCORES_QUERY,
                             {"slug": slug, "first": fetch_count},
                             operation_name="AllPlayerGameScores")
    base, nodi, after, pagine = None, [], None, 0
    while len(nodi) < fetch_count and pagine < 12:
        quante = min(PAGINA_GAME_LOG, fetch_count - len(nodi))
        data = graphql_query(ALL_GAME_SCORES_QUERY_PAGINATO,
                             {"slug": slug, "first": quante, "after": after},
                             operation_name="AllPlayerGameScores")
        pagine += 1
        player = ((data or {}).get('data') or {}).get('anyPlayer')
        if not data or data.get('errors') or player is None:
            if base is None:
                log("[FASE 1/4] Paginazione non utilizzabile, ripiego sulla "
                    f"chiamata singola da {fetch_count} partite.")
                return graphql_query(ALL_GAME_SCORES_QUERY,
                                     {"slug": slug, "first": fetch_count},
                                     operation_name="AllPlayerGameScores")
            break
        if base is None:
            base = data
        conn = player.get('allPlayerGameScores') or {}
        nuovi = conn.get('nodes') or []
        nodi += nuovi
        info = conn.get('pageInfo') or {}
        after = info.get('endCursor')
        if not nuovi or not info.get('hasNextPage') or not after:
            break
    if base is None:
        return None
    log(f"[FASE 1/4] Game log paginato: {len(nodi)} partite in {pagine} "
        f"pagine da max {PAGINA_GAME_LOG} (richieste {fetch_count}).")
    base['data']['anyPlayer']['allPlayerGameScores']['nodes'] = nodi
    return base


def fetch_game_log_incremental(slug, target_window_size):
    """Versione incrementale di fetch_game_log: usa una cache su disco per
    evitare di riscaricare partite storiche gia' note e concluse (FINAL).

    Strategia:
    1. Carica la cache esistente (se c'e').
    2. Chiama SEMPRE allPlayerGameScores, ma con un `first` ridotto
       (GAME_LOG_REFRESH_COUNT, non target_window_size) — sufficiente a
       scoprire partite nuove dall'ultimo run e ad aggiornare lo stato di
       partite non ancora FINAL l'ultima volta (es. REVIEWING -> FINAL).
    3. Se la cache non ha abbastanza partite per riempire la finestra
       richiesta (`target_window_size`), fa un fallback ad una query con
       `first` piu' ampio (comportamento non-incrementale, come prima) —
       tipicamente solo al PRIMO run per un giocatore, quando la cache e'
       vuota o troppo piccola.
    4. Aggiorna la cache con i nodi nuovi/aggiornati e la salva su disco.
    5. Ritorna (past_nodes, future_nodes) esattamente come fetch_game_log,
       ordinati dal piu' recente al piu' vecchio (stesso ordine dell'API).

    Le partite future (anyFutureGames) NON vengono cachate — cambiano ad ogni
    giornata e sono gia' una chiamata leggera (first=5)."""
    cache, cache_file = load_game_log_cache(slug)
    n_cached_final = sum(1 for v in cache.values() if v.get('scoreStatus') == 'FINAL')

    log(f"[FASE 1/4] Cache game log per {slug}: {len(cache)} partite in cache "
        f"({n_cached_final} FINAL).")

    if n_cached_final >= target_window_size:
        # Cache sufficiente: refresh leggero (solo le ultime N partite, per
        # scoprire novita' e aggiornare eventuali status non ancora FINAL).
        fetch_count = GAME_LOG_REFRESH_COUNT
        log(f"[FASE 1/4] Cache sufficiente ({n_cached_final} >= {target_window_size}), "
            f"refresh leggero: richiesta solo ultime {fetch_count} partite.")
    else:
        # Cache insufficiente (primo run, o giocatore con poco storico
        # ancora cachato): fallback a un fetch piu' ampio, come il
        # comportamento originale non-incrementale.
        fetch_count = max(target_window_size * 2, 30)  # margine per DID_NOT_PLAY/minutaggio basso
        log(f"[FASE 1/4] Cache insufficiente ({n_cached_final} < {target_window_size}), "
            f"fetch ampio: richiesta ultime {fetch_count} partite (fallback non-incrementale).")

    data = fetch_game_scores(slug, fetch_count)

    if not data or data.get('errors') or 'data' not in data:
        log("[FASE 1/4] ATTENZIONE: query fallita o con errori — uso SOLO la cache esistente "
            "come fallback (se presente).")
        past_from_cache = sorted(cache.values(), key=lambda n: (n.get('anyGame') or {}).get('date', ''),
                                  reverse=True)
        return past_from_cache, [], None

    player = data.get('data', {}).get('anyPlayer')
    if player is None:
        log(f"[FASE 1/4] FALLITA: 'anyPlayer' e' null per slug '{slug}'.")
        past_from_cache = sorted(cache.values(), key=lambda n: (n.get('anyGame') or {}).get('date', ''),
                                  reverse=True)
        return past_from_cache, [], None

    # NUOVO (29/07, bug reale: giocatore trasferito con storico ancora dominato
    # dalla squadra vecchia -- vedi RIASSUNTO): activeClub e' SEMPRE live (stesso
    # campo gia' verificato in uso in discovery_fixture.py), zero query aggiuntive.
    # Usato sotto SOLO per la squadra nella PROSSIMA partita (dove serve il dato
    # attuale, non storico) -- il fattore casa/trasferta storico resta invariato.
    active_club_slug = ((player.get('activeClub') or {}).get('slug'))

    fetched_past = (player.get('allPlayerGameScores', {}) or {}).get('nodes', []) or []
    future = (player.get('anyFutureGames', {}) or {}).get('nodes', []) or []

    # Merge: aggiorna/aggiunge alla cache ogni nodo appena scaricato. Un nodo
    # gia' in cache con status FINAL viene comunque sovrascritto se ririscaricato
    # (harmless: i dati FINAL non cambiano, quindi il nuovo valore e' identico),
    # ma questo evita la complessita' di dover fare un controllo caso per caso.
    updated_count = 0
    for node in fetched_past:
        node_id = node.get('id')
        if not node_id:
            continue
        was_final_before = cache.get(node_id, {}).get('scoreStatus') == 'FINAL'
        cache[node_id] = node
        if not was_final_before:
            updated_count += 1

    save_game_log_cache(cache, cache_file)
    log(f"[FASE 1/4] Cache aggiornata: {updated_count} partite nuove/aggiornate, "
        f"{len(cache)} totali in cache ora.")

    # Ricostruisce la lista "past" completa leggendo dalla cache (non solo
    # dalla risposta appena ricevuta, che potrebbe essere un lotto ridotto),
    # ordinata dal piu' recente al piu' vecchio come l'API originale.
    past_from_cache = sorted(cache.values(), key=lambda n: (n.get('anyGame') or {}).get('date', ''),
                              reverse=True)

    log(f"[FASE 1/4] OK: {len(past_from_cache)} partite passate (da cache+fetch), "
        f"{len(future)} future.")
    return past_from_cache, future, active_club_slug


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


def weighted_percentile(values, weights, percentile):
    """Percentile PESATO (0-100) sulla serie storica di punteggi -- NUOVO
    (26/07, Stadio B tema level_score): a differenza di media+deviazione
    standard (che assume una distribuzione a campana), il percentile si
    adatta alla FORMA reale della distribuzione, incluse quelle bimodali
    (es. un giocatore con un evento decisivo raro che sposta bruscamente il
    punteggio in un secondo "grappolo" di valori piu' alti -- vedi
    docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md sezione 11 per il
    contesto su level_score). Metodo: ordina i valori, trova il primo valore
    la cui somma cumulativa dei pesi raggiunge la percentuale richiesta
    (nearest-rank pesato, nessuna interpolazione -- sufficiente per finestre
    piccole come le nostre, max ~15 partite). Solo diagnostico per ora, non
    entra in range_conf/score_atteso."""
    if not values:
        return None
    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        return pairs[len(pairs) // 2][0]
    target = percentile / 100.0 * total_weight
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= target:
            return value
    return pairs[-1][0]


def media_condizionata(values, weights, condition_flags, target_condition, fallback_mean, shrink_k=5.0):
    """Stadio D (26/07, tema level_score/correlazione venue-avversario, DECISO
    CON L'UTENTE dopo verifica statistica su migliaia di partite reali in
    cache -- vedi formazione_mls/diagnostics/inspect_decisive_event_conditioning.py
    e docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md): ricalcola la media
    pesata SOLO sul sottoinsieme storico del giocatore che condivide la
    stessa condizione (casa/trasferta, o avversario piu' forte/debole della
    sua media personale) della prossima partita, invece di usare la media
    generica che mischia tutti i contesti insieme.

    SHRINKAGE verso fallback_mean (la media generale non condizionata) quando
    il bucket ha poche partite -- un giocatore ha solo ~10-15 partite di
    storico, quindi un bucket puo' avere anche solo 2-3 partite: senza
    shrinkage il rumore campionario dominerebbe. shrink_k rappresenta
    "partite fittizie" di prior verso la media generale (bucket_mean pesa
    n_bucket/(n_bucket+shrink_k), fallback_mean pesa il resto) -- piu' alto
    shrink_k, piu' prudente la correzione su campioni piccoli.

    Ritorna fallback_mean invariato se manca la condizione target o il
    bucket e' vuoto (nessuna correzione applicata, comportamento invariato)."""
    if target_condition is None:
        return fallback_mean
    bucket_vals, bucket_weights = [], []
    for val, w, flag in zip(values, weights, condition_flags):
        if flag is None:
            continue
        if flag == target_condition:
            bucket_vals.append(val)
            bucket_weights.append(w)
    if not bucket_vals:
        return fallback_mean
    bucket_mean = weighted_mean(bucket_vals, bucket_weights)
    n_bucket = len(bucket_vals)
    return (n_bucket * bucket_mean + shrink_k * fallback_mean) / (n_bucket + shrink_k)


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
# proprio fattore casa/trasferta indipendente. Raggruppati per CATEGORIA SORARE.
# NOTA PORTIERE: struttura RIDOTTA rispetto agli altri ruoli — confermato su
# 2 detailedScore reali (Hugo Lloris, Matt Turner) + screenshot UI.
# was_fouled ASSENTE (come il difensore). NESSUN POSSESSION_STATS (duel_won/
# duel_lost/interception_won/poss_won assenti — solo poss_lost_ctrl esiste).
# NESSUNA categoria DEFENDING (quindi niente GOALKEEPING_STATS/
# DEFENSIVE_ACTIONS_STATS come nel difensore/centrocampista).
# RIMOSSI (26/07, diagnostico inspect_granular_weights.py su 268 partite
# reali/29 portieri): FOULS_STATS, OFFENSIVE_STATS, RARE_EVENTS_STATS
# pesavano 0.0% sul movimento totale del punteggio -- rumore puro, nessun
# segnale perso rimuovendoli. Erano gia' solo diagnostici (mai in
# score_atteso), quindi la rimozione non cambia il comportamento reale del
# modello, solo pulisce codice/output.
# Nota: "duelli" per il portiere si riduce a un solo campo (possesso perso),
# non un vero "duello" come per gli altri ruoli — mantenuto come gruppo a
# se stante per coerenza di posizione nella formula, ma con un solo campo.
POSSESSION_STATS = ('poss_lost_ctrl',)
# Categoria "Passaggio": RIDOTTA rispetto al difensore — manca
# long_pass_own_to_opp_success (quella era specifica del difensore).
PASSING_STATS = ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist',
                  'accurate_long_balls', 'missed_pass')
# Gol subiti dalla propria squadra mentre in campo (negativo). Il piu'
# rilevante di tutti i gruppi granulari per un portiere.
GOALS_CONCEDED_STATS = ('goals_conceded',)
GOALS_CONCEDED_CAP = 10.0
# NUOVO gruppo SOLO PORTIERE: le 8 voci GOALKEEPING, finalmente valorizzate
# (per tutti gli altri ruoli erano scartate perche' sempre a 0). Nessun cap:
# sono il cuore del punteggio di un portiere, non eventi rari da limitare.
GOALKEEPING_STATS = ('saves', 'saved_ibox', 'good_high_claim', 'punches', 'dive_save',
                      'dive_catch', 'cross_not_claimed', 'six_second_violation',
                      'gk_smother', 'accurate_keeper_sweeper')

# ---------------------------------------------------------------------------
# GESTIONE SPECIALE: bonus clean sheet (25/07)
# clean_sheet_60 ha SEMPRE totalScore=0 come riga nel detailedScore per il
# portiere (a differenza del difensore, dove vale 10pt reali) — il bonus
# (~25 punti) e' incorporato nel level_score stesso: ~35 se ha subito gol
# nei primi 60', ~60 se ha mantenuto la porta inviolata. NON puo' quindi
# essere estratto con extract_group_score come gli altri gruppi (leggerebbe
# sempre 0) — va rilevato dal campo clean_sheet_60.statValue (1.0/0.0) nel
# detailedScore, che RIMANE un flag valido anche se il suo totalScore e' 0.
# ---------------------------------------------------------------------------

def extract_clean_sheet_flag(detail):
    """Ritorna 1.0 se clean_sheet_60 risulta statValue=1 nel detailedScore
    (porta inviolata nei primi 60'), 0.0 altrimenti. Usa statValue (non
    totalScore, che per il portiere e' sempre 0 — il bonus e' nel level_score)."""
    if not detail:
        return 0.0
    for entry in (detail.get('detailedScore') or []):
        if entry.get('stat') == 'clean_sheet_60':
            return float(entry.get('statValue') or 0.0)
    return 0.0



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


def extract_level_score(detail):
    """Estrae il valore della riga 'level_score' (category=UNKNOWN nel
    detailedScore) -- il "Punteggio decisivo" mostrato nella UI Sorare.
    NUOVO (26/07, Stadio A tema level_score): funzione deterministica del
    conteggio netto di eventi decisivi (positivi meno negativi, floor a 35
    base) validata su dati reali, vedi docs/RIASSUNTO_EVOLUZIONE_MODELLO_
    PREDITTIVO.md sezione 11. Ritorna 0.0 se il dettaglio non e' disponibile
    (fallback sicuro)."""
    if not detail:
        return 0.0
    for entry in (detail.get('detailedScore') or []):
        if entry.get('stat') == 'level_score':
            return entry.get('totalScore', 0.0) or 0.0
    return 0.0


# --- level_score ATTESO da tasso di eventi decisivi (27/07 notte) -- sostituisce
# il vecchio approccio "level_score implicito nella media generica" con una stima
# esplicita basata sulla regola netto->livello VALIDATA su casi reali Sorare.
# Pattern identico a formazione_mls/predict/test_gk.py (vedi commenti li'
# per la spiegazione estesa). NESSUNA ri-taratura di half_life/trend per questo
# campionato -- solo la formula di score_atteso cambia.
LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
LEVEL_SCORE_POISSON_K_MAX = 6  # troncamento Poisson: massa residua accumulata sull'ultimo bin


def netto_to_level(netto):
    k = max(-2, min(5, round(netto)))
    return LEVEL_TABLE[k]


def extract_decisive_rates(detail):
    """Somma statValue delle righe POSITIVE_DECISIVE_STAT / NEGATIVE_DECISIVE_STAT
    (gol/assist/cartellini/errori-a-gol/ecc.) -- il "conteggio netto" di eventi
    decisivi da cui deriva level_score secondo la tabella validata sopra."""
    pos_sum, neg_sum = 0.0, 0.0
    for entry in (detail.get('detailedScore') if detail else None) or []:
        cat = entry.get('category')
        val = entry.get('statValue') or 0.0
        if cat == 'POSITIVE_DECISIVE_STAT':
            pos_sum += val
        elif cat == 'NEGATIVE_DECISIVE_STAT':
            neg_sum += val
    return pos_sum, neg_sum


def _poisson_pmf_truncated(lam, k_max):
    if lam <= 0:
        probs = [0.0] * (k_max + 1)
        probs[0] = 1.0
        return probs
    probs = []
    cum = 0.0
    for k in range(k_max):
        p = math.exp(-lam) * (lam ** k) / math.factorial(k)
        probs.append(p)
        cum += p
    probs.append(max(0.0, 1.0 - cum))
    return probs


def expected_level_from_rates(lambda_pos, lambda_neg):
    """Valore atteso di level_score modellando eventi positivi/negativi come
    Poisson(lambda) indipendenti, convolti per ottenere P(netto=k)."""
    probs_pos = _poisson_pmf_truncated(lambda_pos, LEVEL_SCORE_POISSON_K_MAX)
    probs_neg = _poisson_pmf_truncated(lambda_neg, LEVEL_SCORE_POISSON_K_MAX)
    expected = 0.0
    for i, pp in enumerate(probs_pos):
        if pp == 0.0:
            continue
        for j, pn in enumerate(probs_neg):
            if pn == 0.0:
                continue
            expected += pp * pn * netto_to_level(i - j)
    return expected


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
    context_vals = home_vals if target_is_home else away_vals

    # FIX (25/07, audit logica): il delta viene normalizzato per la deviazione
    # standard STORICA del gruppo stesso, invece di una scala fissa "1%/punto"
    # identica per ogni gruppo -- che rendeva i gruppi a bassa magnitudine
    # (es. RARE_EVENTS_STATS cappato +-10pt) sostanzialmente inerti (~1.00
    # sempre) e i gruppi ad alta magnitudine (es. GOALKEEPING_STATS, decine di
    # punti/partita) sproporzionatamente sensibili. Con la normalizzazione,
    # ogni gruppo/ruolo ha sensibilita' comparabile: un giocatore che devia
    # sistematicamente (es. un difensore con molti piu' falli in trasferta)
    # ottiene un fattore che si muove davvero, il rumore statistico attorno
    # alla media resta vicino a 1.0.
    variance = sum((v - overall_avg) ** 2 for v in all_vals) / len(all_vals)
    std_dev = variance ** 0.5
    delta = context_avg - overall_avg
    delta_normalizzato = (delta / std_dev) if std_dev > 0 else 0.0
    # Shrinkage per campione piccolo (28/07, richiesta esplicita utente, caso
    # reale Collodi: fattore casa/trasferta di 1.319 calcolato su 3-4 partite
    # per bucket, rumore spacciato per segnale). Con pochi dati nel bucket
    # (casa O trasferta, quello effettivamente usato per il target) il
    # fattore viene tirato verso il neutro 1.0, proporzionalmente al numero
    # di partite in quel bucket -- stesso principio Empirical Bayes dello
    # shrinkage verso il prior di ruolo, applicato qui alla deviazione invece
    # che al livello assoluto.
    SPLIT_SHRINK_K = 5.0
    n_context = len(context_vals)
    shrink = n_context / (n_context + SPLIT_SHRINK_K)
    fattore = 1.0 + (delta_normalizzato * SPLIT_FACTOR_SCALE_PER_STD * shrink)
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
                       possession_values=None,
                       passing_values=None, goalkeeping_values=None, goals_conceded_values=None,
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
            for values in (possession_values,
                           passing_values, goalkeeping_values, goals_conceded_values):
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
                     possession_values=None,
                     passing_values=None, goalkeeping_values=None, goals_conceded_values=None):
    """Esegue il backtest rigoroso con tutte le combinazioni di parametri in
    GRID_SEARCH_COMBINATIONS e ritorna i risultati ordinati per MAE crescente
    (il migliore per primo). Il 'punteggio' finale usato per il ranking bilancia
    MAE (peggio se alto) e distanza dalla copertura ideale del range (~68%)."""
    results = []
    for half_life, range_mult, opp_sens, use_granular, use_trend, trend_intensity, label in GRID_SEARCH_COMBINATIONS:
        bt = rigorous_backtest(scores, is_home_flags, opponent_rankings,
                                min_history=min_history, half_life=half_life,
                                range_multiplier=range_mult, opponent_sensitivity=opp_sens,
                                possession_values=possession_values,
                                passing_values=passing_values,
                                goalkeeping_values=goalkeeping_values,
                                goals_conceded_values=goals_conceded_values,
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
    global _STRUCTURAL_INSUFFICIENCY
    _STRUCTURAL_INSUFFICIENCY = False
    log("[FASE 1/4] Avvio recupero game log...")
    past_games, future_games, live_team_slug = fetch_game_log_incremental(player_slug, target_window_size=WINDOW_SIZE)
    # Finestra temporale massima per lo storico (28/07, richiesta esplicita
    # utente dopo un caso reale: Alejandro Alvarado Jr aveva 1 sola partita
    # "piena" utilizzabile su 27 esaminate, alcune vecchie di oltre un anno --
    # un giocatore che rientra da un lungo infortunio/stop non deve essere
    # valutato su partite troppo vecchie che non riflettono piu' il suo stato
    # attuale). Partite piu' vecchie di MAX_HISTORY_DAYS vengono scartate
    # PRIMA di ogni altro filtro, come se non esistessero. Date non
    # interpretabili restano incluse (permissivo, mai un'esclusione su dato
    # mancante).
    MAX_HISTORY_DAYS = 365
    _cutoff_storico = datetime.datetime.utcnow() - datetime.timedelta(days=MAX_HISTORY_DAYS)

    def _game_dt(node):
        d = (node.get('anyGame') or {}).get('date')
        if not d:
            return None
        try:
            return datetime.datetime.fromisoformat(d.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return None

    past_games = [n for n in past_games if (_game_dt(n) or _cutoff_storico) >= _cutoff_storico]
    if not past_games:
        log("[FASE 1/4] INTERROTTO: nessuna partita passata trovata, impossibile procedere oltre.")
        _STRUCTURAL_INSUFFICIENCY = True
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
    MIN_SAME_COMPETITION = 20
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

    # Soglia minima partite PIENE (28/07, stesso caso Alvarado sopra): con meno
    # di MIN_USABLE_GAMES partite da >= MIN_MINUTES_PLAYED minuti nella
    # finestra di MAX_HISTORY_DAYS giorni, il dato e' troppo poco per fidarsi
    # (un singolo risultato fuori scala diventerebbe l'intera "media"). Sotto
    # soglia il giocatore e' trattato come DATI INSUFFICIENTI, stesso status
    # gia' usato altrove per storico troppo corto -- non una nuova categoria.
    MIN_USABLE_GAMES = 3
    if len(usable) < MIN_USABLE_GAMES:
        log(f"[FASE 2/4] INTERROTTO: solo {len(usable)} partita/e con status FINAL/REVIEWING "
            f"e minutaggio >= {MIN_MINUTES_PLAYED}' negli ultimi {MAX_HISTORY_DAYS} giorni "
            f"(< soglia minima {MIN_USABLE_GAMES}), su {total_considered} esaminate "
            f"({dnp_count} DID_NOT_PLAY, {low_minutes_count} sotto soglia minutaggio, "
            f"altri status: {other_status_count}).")
        _STRUCTURAL_INSUFFICIENCY = True
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
    # FIX (28/07, bug reale trovato durante l'audit): la maggioranza andava
    # calcolata sull'INTERA finestra storica (fino a 15 partite, ora fino a
    # 12 mesi) -- un giocatore trasferito a meta' finestra rischiava di
    # essere attribuito alla squadra VECCHIA se aveva piu' partite li',
    # sbagliando casa/trasferta, sinergie e avversario. Il commento originale
    # diceva gia' "dalla partita piu' recente" ma il codice non lo faceva
    # (last_game veniva assegnata e mai usata). Ora la maggioranza si calcola
    # SOLO sulle ultime 5 partite (o tutte se meno di 5) -- serve ancora un
    # piccolo gruppo per disambiguare casa/trasferta dello stesso avversario,
    # ma la squadra vecchia (games piu' vecchi di 5 partite) non puo' piu'
    # vincere sulla nuova.
    _recent_window = usable[-5:] if len(usable) >= 5 else usable
    team_counts = {}
    for node in _recent_window:
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
    possession_values = []
    passing_values = []
    goalkeeping_values = []
    goals_conceded_values = []
    clean_sheet_flag_values = []  # 1.0/0.0 per partita: porta inviolata nei primi 60' (vedi extract_clean_sheet_flag)
    level_score_values = []  # NUOVO (26/07, Stadio A): "Punteggio decisivo" per partita
    granulari_values = []  # NUOVO (26/07, Stadio A): resto del punteggio (= score - level_score)
    pos_decisive_values = []  # NUOVO (27/07 notte): conteggio eventi POSITIVE_DECISIVE_STAT per partita
    neg_decisive_values = []  # NUOVO (27/07 notte): conteggio eventi NEGATIVE_DECISIVE_STAT per partita

    for node, detail in zip(usable, details):
        game_score = node.get('score', 0.0)
        scores.append(game_score)
        game = node['anyGame']
        own_rank, opp_rank, is_home = team_ranking_from_game(game, player_team_slug)
        # fallback: se il ranking non e' nel game log base, prova dal dettaglio granulare
        if opp_rank is None and detail:
            own_rank, opp_rank, is_home = team_ranking_from_game(detail['anyGame'], player_team_slug)
        is_home_flags.append(is_home)
        opponent_rankings.append(opp_rank)
        own_rankings.append(own_rank)

        possession_values.append(extract_group_score(detail, POSSESSION_STATS))
        passing_values.append(extract_group_score(detail, PASSING_STATS))
        goalkeeping_values.append(extract_group_score(detail, GOALKEEPING_STATS))  # nessun cap: e' il cuore del punteggio portiere
        goals_conceded_raw = extract_group_score(detail, GOALS_CONCEDED_STATS)
        # RIMOSSO CAP (29/07, bug reale confermato dall'utente su piu' partite MLS+K League,
        # GK/DEF/MID: -5/-4/-2 a gol rispettivamente, LINEARE fino a 6-7 gol subiti in un
        # solo game -- nessun tetto osservato nei dati reali Sorare, il vecchio cap a +-10
        # troncava artificialmente le partite con tante reti subite).
        goals_conceded_values.append(goals_conceded_raw)
        clean_sheet_flag_values.append(extract_clean_sheet_flag(detail))
        level_score_v = extract_level_score(detail)
        level_score_values.append(level_score_v)
        granulari_values.append(game_score - level_score_v)
        pos_dec_v, neg_dec_v = extract_decisive_rates(detail)
        pos_decisive_values.append(pos_dec_v)
        neg_decisive_values.append(neg_dec_v)

    n = len(scores)
    weights = exponential_weights(n, HALF_LIFE_GAMES)

    media_pesata = weighted_mean(scores, weights)
    dev_std_pesata = weighted_stddev(scores, weights, media_pesata)
    dev_std_trimmed = trimmed_weighted_stddev(scores, weights)

    # --- Stadio A (26/07, tema level_score): media pesata separata per
    # level_score ("Punteggio decisivo") e resto ("Punteggio complessivo") --
    # solo diagnostico per ora, non entra ancora in score_atteso. La somma
    # delle due deve coincidere con media_pesata (stesso half-life, stessa
    # scomposizione additiva score=level_score+granulari verificata su dati
    # reali) -- eventuali scarti sono dovuti al floor (level_score>=60 puo'
    # rendere la scomposizione per-partita non lineare, la media resta valida).
    media_level_score_pesata = weighted_mean(level_score_values, weights)
    media_granulari_pesata = weighted_mean(granulari_values, weights)

    # --- Stadio B (26/07, tema level_score): range di confidenza a
    # percentili pesati sullo storico REALE, in alternativa a media+deviazione
    # standard -- si adatta alla bimodalita' reale della distribuzione invece
    # di assumere una campana. Usato dallo Stadio C sotto per costruire il
    # range di confidenza finale.
    p16_score = weighted_percentile(scores, weights, 16)
    p84_score = weighted_percentile(scores, weights, 84)

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
    # NUOVO (29/07, fix bug reale trasferimento/team stantio): per la partita
    # TARGET usiamo activeClub (live) come squadra "attuale" se disponibile,
    # invece della maggioranza storica (player_team_slug) -- quest'ultima puo'
    # essere sbagliata dopo un trasferimento recente. Se activeClub manca o non
    # corrisponde a nessuna delle due squadre della partita target, ripiega sulla
    # vecchia logica (nessuna regressione).
    _next_home_team = next_game.get('homeTeam') or {}
    _next_away_team = next_game.get('awayTeam') or {}
    current_team_slug = player_team_slug
    if live_team_slug and live_team_slug in (_next_home_team.get('slug'), _next_away_team.get('slug')):
        current_team_slug = live_team_slug

    next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(next_game, current_team_slug)

    # NUOVO (26/07, tema correlazione GK-DEF/anti-sinergia): slug (non nome)
    # della squadra avversaria della prossima partita -- dato di calendario,
    # gia' noto con largo anticipo (a differenza delle starter odds). Serve a
    # build_formazione_finale.py per evitare di schierare insieme un portiere
    # e un giocatore di movimento le cui squadre si affrontano.
    if _next_home_team.get('slug') == current_team_slug:
        next_opponent_team_slug = _next_away_team.get('slug')
    elif _next_away_team.get('slug') == current_team_slug:
        next_opponent_team_slug = _next_home_team.get('slug')
    else:
        next_opponent_team_slug = None

    # se il ranking non e' nel blocco base, scarichiamo il dettaglio (funziona anche per future)
    if next_opp_rank is None:
        next_score_id = next_node['id'].replace('So5Score:', '')
        next_detail = fetch_game_detail(next_score_id, cache, is_final=False)
        if next_detail:
            next_own_rank, next_opp_rank, next_is_home = team_ranking_from_game(
                next_detail['anyGame'], player_team_slug)

    # Shrinkage per campione piccolo (28/07, richiesta esplicita utente, caso
    # reale Collodi: 1.319 calcolato su 3-4 partite per bucket casa/trasferta,
    # rumore spacciato per segnale). Il fattore viene tirato verso il neutro
    # 1.0 proporzionalmente al numero di partite nel bucket usato.
    SPLIT_SHRINK_K_GK = 5.0
    fattore_casa_trasferta = 1.0
    if overall_avg_for_factor > 0:
        if next_is_home:
            _raw_fattore = home_avg / overall_avg_for_factor
            _n_bucket = len(home_scores)
        else:
            _raw_fattore = away_avg / overall_avg_for_factor
            _n_bucket = len(away_scores)
        _shrink_gk = _n_bucket / (_n_bucket + SPLIT_SHRINK_K_GK)
        fattore_casa_trasferta = 1.0 + _shrink_gk * (_raw_fattore - 1.0)

    # --- Fattori granulari SEPARATI (26/07: falli/efficacia offensiva/eventi
    # rari rimossi, pesavano 0.0% su 268 partite reali -- vedi
    # inspect_granular_weights.py) ---
    # Ognuno e' un fattore casa/trasferta indipendente, calcolato sui dati REALI
    # del detailedScore delle 14 partite (non stime).
    fattore_possesso = compute_split_factor(possession_values, is_home_flags, next_is_home)
    fattore_passaggio = compute_split_factor(passing_values, is_home_flags, next_is_home)
    fattore_goalkeeping = compute_split_factor(goalkeeping_values, is_home_flags, next_is_home)
    fattore_gol_subiti = compute_split_factor(goals_conceded_values, is_home_flags, next_is_home)

    # --- Bonus clean sheet (25/07, gestione SPECIALE per il portiere) ---
    # Non e' un fattore moltiplicativo granulare come gli altri (il totalScore
    # di clean_sheet_60 e' sempre 0 nel detailedScore, il bonus reale e'
    # incorporato nel level_score). Calcoliamo invece la FREQUENZA storica di
    # clean sheet (quante volte su N partite ha mantenuto la porta inviolata
    # nei primi 60') e la usiamo per stimare un BONUS ADDITIVO atteso: se il
    # giocatore fa clean sheet il 40% delle volte, ci aspettiamo in media
    # +0.40 * BONUS_CLEAN_SHEET_POINTS punti extra sul level_score rispetto
    # alla media pesata (che gia' include implicitamente la frequenza storica
    # di clean sheet passata, ma qui la applichiamo esplicitamente al prossimo
    # match per trasparenza diagnostica — il valore e' comunque gia' presente
    # nella media_pesata, quindi bonus_clean_sheet_atteso NON viene sommato
    # una seconda volta allo score_atteso, resta solo informativo in output).
    BONUS_CLEAN_SHEET_POINTS = 25.0  # osservato: level_score ~60 con clean sheet vs ~35 senza, delta ~25
    clean_sheet_rate = sum(clean_sheet_flag_values) / len(clean_sheet_flag_values) if clean_sheet_flag_values else 0.0
    bonus_clean_sheet_atteso = clean_sheet_rate * BONUS_CLEAN_SHEET_POINTS  # solo diagnostico, vedi nota sopra

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
    # presence_rate (28/07, propagato da formazione_mls): calcolata SEMPRE,
    # non solo come fallback di p_gioca -- serve al prior dinamico dello
    # shrinkage verso il prior di ruolo (vedi sotto, blocco
    # MEDIA_RUOLO_GK_PRIOR), che deve sapere se il giocatore e' un titolare
    # o una riserva a prescindere da starterOdds disponibili o meno per la
    # prossima partita specifica.
    presence_rate = len(usable) / total_considered if total_considered else 1.0
    next_odds = ((next_node.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
    starter_odds = next_odds.get('starterOddsBasisPoints')
    if starter_odds is not None:
        p_gioca = starter_odds / 10000.0
        p_source = f"starterOddsBasisPoints ({starter_odds})"
    else:
        p_gioca = presence_rate
        p_source = f"tasso di presenza storico ({len(usable)}/{total_considered})"

    # --- Fattore trend (ultime 5 vs ultime 10, stesso pool gia' filtrato) ---
    fattore_trend, trend_avg_short, trend_avg_long = compute_trend_factor(
        scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

    # FIX (25/07): i fattori granulari NON entrano piu' nello score_atteso di
    # produzione. La calibrazione che ha fissato i parametri sopra (grid
    # search su 12 portieri) ha scelto la combinazione vincente SENZA
    # fattori granulari (use_granular_factors=False in rigorous_backtest,
    # vedi commento su TREND_INTENSITY), perche' peggioravano sempre il
    # risultato per questo ruolo. Prima di questo fix la produzione li
    # includeva comunque, per cui il MAE/copertura mostrati (calcolati sul
    # backtest senza granulari) non descrivevano la formula realmente usata.
    # I fattori restano calcolati sopra e nel result dict solo a scopo
    # diagnostico/di visualizzazione nell'output.
    # RIMOSSO da score_atteso il 26/07 (terza sessione), DECISO CON L'UTENTE
    # dopo backtest walk-forward rigoroso (formazione_mls/diagnostics/
    # validate_team_defense_strength.py): fattore_forza_avversario (ranking
    # di campionato) PEGGIORA il MAE reale -- rimuoverlo del tutto batte sia
    # il ranking attuale sia una metrica alternativa piu' specifica (gol
    # subiti storici dall'avversario, testata con grid search sul
    # coefficiente di sensibilita'): -4.02% rimuovendolo vs -6.08% con gol
    # subiti a sensibilita' quasi nulla per GK (unico ruolo dove
    # l'alternativa batte la rimozione totale, per margine minimo che non
    # giustifica la nuova infrastruttura di query team-level richiesta in
    # produzione -- vedi commento sotto). Stesso risultato di Stadio D:
    # con soli 10-15 partite di storico per giocatore, condizionare per
    # avversario (con QUALSIASI metrica) aggiunge piu' rumore che segnale.
    # Il fattore resta calcolato sopra e nel result dict solo a scopo
    # diagnostico/di visualizzazione nell'output.
    # --- level_score ATTESO da tasso di eventi (27/07 notte): vedi
    # formazione_mls/predict/test_def.py per la spiegazione estesa. Il trend
    # si applica SOLO al pezzo granulare (il livello non ha un trend proprio,
    # e' basato su un tasso di eventi gia' pesato esponenzialmente).
    # opponent_lambda_mult (29/07, vedi opponent_strength.py): gol fatti dal prossimo avversario nelle ultime 10 partite (dato storico reale, non il domesticLeagueRanking contaminato). Validato: -0.59% MAE.
    _opp_lambda_mult = opponent_strength.opponent_lambda_multiplier(
        'kleague', 'gk', next_opponent_team_slug, datetime.datetime.utcnow())
    # Bonus AGGIUNTIVO (29/07, si affianca al bonus goalkeeping esistente,
    # non lo sostituisce -- vedi opponent_strength.gk_def_pen_area_multiplier):
    # isola le pen_area_entries dei SOLI difensori avversari (da corner/palle
    # inattive), separato dal segnale FWD+MID gia' in produzione. Validato
    # -0.13% MAE (formazione_mls/diagnostics/validate_cross_role_combos.py,
    # gruppo gk_vs_def_only).
    _opp_lambda_mult *= opponent_strength.gk_def_pen_area_multiplier(
        'kleague', next_opponent_team_slug, datetime.datetime.utcnow())
    lambda_pos_dec = weighted_mean(pos_decisive_values, weights) * _opp_lambda_mult
    lambda_neg_dec = weighted_mean(neg_decisive_values, weights)
    level_score_atteso = expected_level_from_rates(lambda_pos_dec, lambda_neg_dec)
    fattore_trend_granulare, _trend_gran_short, _trend_gran_long = compute_trend_factor(
        granulari_values, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)
    # Shrinkage verso il prior di ruolo (28/07, stesso principio EmpiricalBayes
    # di DEF/FWD, mai avuto da GK -- caso reale: Michael Collodi, 8 partite,
    # preferito a Takaoka per un fattore casa/trasferta enorme su 3-4 partite
    # per bucket). k=5 scelto con backtest walk-forward reale (selection_quality).
    SHRINK_K_OUTLIER_GK = 30.0  # AGGIORNATO (29/07, modello unico GLOBALE su 25 leghe pooled): backtest walk-forward su ~7500 punti di test conferma k=30 pulito su entrambi i segmenti n<8/n>=8 (-5.36%/-9.28%/-4.31%), il vecchio timore "overfitting al bordo griglia" non regge piu' con questo volume di dati -- stesso valore ora su TUTTE le leghe incluso MLS/Korea
    MEDIA_RUOLO_GK_PRIOR = 48.81
    # Prior di ruolo DINAMICO (28/07, propagato da formazione_mls: bug reale
    # trovato dall'utente, giocatori di riserva veri con P(gioca) storico
    # basso venivano tirati dallo shrinkage verso la media di TUTTI i
    # giocatori, dominata dai titolari, gonfiando artificialmente il
    # punteggio di chi gioca poco. Misurato sui dati reali, n=115 portieri,
    # corr presenza/punteggio +0.245: chi gioca poco rende MENO anche quando
    # gioca, non solo per varianza campionaria. Prior = intercetta + pendenza
    # * presenza storica (regressione reale), non piu' un numero fisso
    # uguale per titolari e riserve).
    media_ruolo_prior = MEDIA_RUOLO_GK_PRIOR
    if presence_rate is not None:
        media_ruolo_prior = max(0.0, 45.41 + 4.36 * presence_rate)
    _grezzo_gk = level_score_atteso + media_granulari_pesata * fattore_trend_granulare
    _grezzo_gk_corretto = (
        (n / (n + SHRINK_K_OUTLIER_GK)) * _grezzo_gk
        + (SHRINK_K_OUTLIER_GK / (n + SHRINK_K_OUTLIER_GK)) * media_ruolo_prior
    )
    score_atteso = _grezzo_gk_corretto * fattore_casa_trasferta

    # --- Stadio D (26/07, tema level_score/correlazione venue-avversario) --
    # RIMOSSO da score_atteso il 26/07 (mattina), DECISO CON L'UTENTE dopo
    # backtest walk-forward rigoroso su dati reali (formazione_mls/diagnostics/
    # validate_stadio_d_mae.py): le correlazioni aggregate erano statisticamente
    # solide (z fino a -3.49 per Gol subiti), ma applicate per-giocatore con
    # shrinkage PEGGIORAVANO il MAE reale del +4.21% (129 punti di test walk-
    # forward, 15 portieri) -- 59% delle partite predette peggio, non meglio.
    # L'effetto e' probabilmente reale a livello di popolazione ma troppo
    # "diluito" per essere sfruttato con soli ~10-15 partite di storico per
    # portiere: lo shrinkage non basta a compensare il rumore campionario
    # individuale. Confermato solo per GK (unico ruolo dove il backtest ha
    # mostrato un peggioramento netto, non solo rumore) -- DEF/MID/FWD
    # restano invariati (variazione MAE sostanzialmente nulla, ne' beneficio
    # ne' danno misurato). Calcolo lasciato SOLO diagnostico in output,
    # NON piu' applicato a score_atteso.
    opponent_forte_flags = [
        (r < avg_opp_rank_hist) if (r is not None and avg_opp_rank_hist is not None) else None
        for r in opponent_rankings
    ]
    next_forte = (next_opp_rank < avg_opp_rank_hist) if (
        next_opp_rank is not None and avg_opp_rank_hist is not None) else None
    media_level_score_condizionata = media_condizionata(
        level_score_values, weights, opponent_forte_flags, next_forte, media_level_score_pesata)
    delta_condizionamento_avversario = media_level_score_condizionata - media_level_score_pesata

    media_gol_subiti_condizionata_venue = media_condizionata(
        goals_conceded_values, weights, is_home_flags, next_is_home, weighted_mean(goals_conceded_values, weights))
    media_gol_subiti_condizionata_avversario = media_condizionata(
        goals_conceded_values, weights, opponent_forte_flags, next_forte, weighted_mean(goals_conceded_values, weights))
    media_possesso_condizionata_venue = media_condizionata(
        possession_values, weights, is_home_flags, next_is_home, weighted_mean(possession_values, weights))
    media_goalkeeping_condizionata_venue = media_condizionata(
        goalkeeping_values, weights, is_home_flags, next_is_home, weighted_mean(goalkeeping_values, weights))

    delta_gol_subiti_venue = media_gol_subiti_condizionata_venue - weighted_mean(goals_conceded_values, weights)
    delta_gol_subiti_avversario = media_gol_subiti_condizionata_avversario - weighted_mean(goals_conceded_values, weights)
    delta_possesso_venue = media_possesso_condizionata_venue - weighted_mean(possession_values, weights)
    delta_goalkeeping_venue = media_goalkeeping_condizionata_venue - weighted_mean(goalkeeping_values, weights)
    # NOTA: nessuno dei delta sopra viene piu' sommato a score_atteso (vedi motivazione).

    # --- Stadio C (26/07, tema level_score, DECISO CON L'UTENTE dopo analisi
    # comparativa su 180 casi reali di produzione): range di confidenza finale
    # = FORMA del range a percentili pesati (Stadio B, si adatta a distribuzioni
    # reali non a campana) RI-CENTRATA sullo score_atteso corretto per
    # avversario/trend. Il vecchio range simmetrico (media+dev.std.pesata*
    # moltiplicatore) applicava una larghezza NON aggiustata a un centro GIA'
    # aggiustato, producendo un estremo inferiore < 0 (score impossibile, il
    # minimo reale e' 0) in circa 1/3 dei casi reali analizzati. Qui si prende
    # la distanza osservata media_pesata->p16 (risp. p84->media_pesata) e la
    # si trasla sul nuovo centro score_atteso, poi si clippa a un minimo di 0.
    if p16_score is not None and p84_score is not None:
        range_low = max(0.0, score_atteso - (media_pesata - p16_score))
        range_high = score_atteso + (p84_score - media_pesata)
    else:
        _range_conf_fallback = dev_std_pesata * RANGE_MULTIPLIER
        range_low = max(0.0, score_atteso - _range_conf_fallback)
        range_high = score_atteso + _range_conf_fallback

    # --- Backtest SEMPLICE: riapplica solo la componente media "a ritroso" sull'ultima partita nota ---
    last_real = usable[-1]
    last_real_score = last_real.get('score')
    backtest_prev = usable[:-1]
    backtest_scores = scores[:-1]
    backtest_weights = exponential_weights(len(backtest_scores), HALF_LIFE_GAMES) if backtest_scores else []
    backtest_media = weighted_mean(backtest_scores, backtest_weights) if backtest_scores else None


    # --- Backtest RIGOROSO sui parametri FISSATI (25/07, uso reale/produzione) ---
    # Grid search di calibrazione GIA' concluso (12 portieri posseduti con dati
    # sufficienti, MAE medio 21.03, copertura 63.3% — combinazione vincente SENZA
    # fattori granulari, che peggioravano sempre il risultato per questo ruolo).
    # Non serve piu' rieseguire 72 combinazioni ad ogni giocatore in produzione —
    # un solo backtest sui parametri fissati, molto piu' veloce.
    if CALIBRATION_MODE:
        # Grid search allargato (25/07): riesegue tutte le combinazioni su
        # tutti i portieri MLS di qualita' (non solo i posseduti), per
        # ricalibrare i parametri su un campione molto piu' ampio.
        log("CALIBRATION_MODE attivo: esecuzione grid search completo (72 combinazioni)...")
        grid_results = run_grid_search(scores, is_home_flags, opponent_rankings, min_history=6,
                                        possession_values=possession_values,
                                        passing_values=passing_values,
                                        goalkeeping_values=goalkeeping_values,
                                        goals_conceded_values=goals_conceded_values)
        rigorous_bt = grid_results[0] if grid_results else None
    else:
        log("Esecuzione backtest rigoroso sui parametri fissati...")
        rigorous_bt = rigorous_backtest(scores, is_home_flags, opponent_rankings, min_history=6,
                                         half_life=HALF_LIFE_GAMES, range_multiplier=RANGE_MULTIPLIER,
                                         opponent_sensitivity=OPPONENT_SENSITIVITY,
                                         possession_values=possession_values,
                                         passing_values=passing_values,
                                         goalkeeping_values=goalkeeping_values,
                                         goals_conceded_values=goals_conceded_values,
                                         use_granular_factors=False, use_trend=True,
                                         trend_intensity=TREND_INTENSITY)
        rigorous_bt['label'] = (f"hl={HALF_LIFE_GAMES}+range={RANGE_MULTIPLIER}x+"
                                f"opp_sens={OPPONENT_SENSITIVITY}+trend_int={TREND_INTENSITY} (FISSATA 12 posseduti)")
        if rigorous_bt['mae'] is not None:
            log(f"Backtest completato: MAE={rigorous_bt['mae']:.2f}, "
                f"copertura={rigorous_bt['pct_dentro_range']:.1f}%")
        else:
            log("Backtest: dati insufficienti (serve più storico).")
        grid_results = [rigorous_bt]  # lista con un solo elemento, per compatibilita' col resto del codice

    result = {
        'player_slug': player_slug,
        'player_team_slug': current_team_slug,
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
        'media_level_score_pesata': media_level_score_pesata,
        'level_score_atteso': level_score_atteso,
        'fattore_trend_granulare': fattore_trend_granulare,
        'media_granulari_pesata': media_granulari_pesata,
        'media_level_score_condizionata': media_level_score_condizionata,
        'delta_condizionamento_avversario': delta_condizionamento_avversario,
        'delta_gol_subiti_venue': delta_gol_subiti_venue,
        'delta_gol_subiti_avversario': delta_gol_subiti_avversario,
        'delta_possesso_venue': delta_possesso_venue,
        'delta_goalkeeping_venue': delta_goalkeeping_venue,
        'p16_score': p16_score,
        'p84_score': p84_score,
        'home_avg': home_avg,
        'away_avg': away_avg,
        'fattore_casa_trasferta': fattore_casa_trasferta,
        'avg_opp_rank_hist': avg_opp_rank_hist,
        'next_opp_rank': next_opp_rank,
        'next_own_rank': next_own_rank,
        'next_opponent_team_slug': next_opponent_team_slug,
        'next_is_home': next_is_home,
        'fattore_forza_avversario': fattore_forza_avversario,
        'fattore_possesso': fattore_possesso,
        'fattore_passaggio': fattore_passaggio,
        'fattore_goalkeeping': fattore_goalkeeping,
        'fattore_gol_subiti': fattore_gol_subiti,
        'clean_sheet_rate': clean_sheet_rate,
        'bonus_clean_sheet_atteso': bonus_clean_sheet_atteso,
        'fattore_trend': fattore_trend,
        'trend_avg_short': trend_avg_short,
        'trend_avg_long': trend_avg_long,
        'p_gioca': p_gioca,
        'p_source': p_source,
        'score_atteso': score_atteso,
        'range_low': range_low,
        'range_high': range_high,
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
    lines.append(f"  di cui Punteggio decisivo (level_score) medio: {result['media_level_score_pesata']:.2f} "
                 f"| Punteggio complessivo (granulari) medio: {result['media_granulari_pesata']:.2f} "
                 f"(Stadio A, solo diagnostico -- non applicato a score_atteso)")
    lines.append(f"  Punteggio decisivo condizionato per forza prossimo avversario: "
                 f"{result['media_level_score_condizionata']:.2f} (delta {result['delta_condizionamento_avversario']:+.2f} "
                 f"vs media generica, Stadio D -- SOLO DIAGNOSTICO, rimosso da score_atteso il 26/07 "
                 f"dopo backtest walk-forward: peggiorava il MAE reale del +4.21%)")
    lines.append(f"  Gol subiti condizionato: delta venue {result['delta_gol_subiti_venue']:+.2f}, "
                 f"delta avversario {result['delta_gol_subiti_avversario']:+.2f} | Possesso condizionato per venue: "
                 f"delta {result['delta_possesso_venue']:+.2f} | Goalkeeping condizionato per venue: "
                 f"delta {result['delta_goalkeeping_venue']:+.2f} "
                 f"(Stadio D approfondimento -- SOLO DIAGNOSTICO, rimosso da score_atteso il 26/07)")
    lines.append(f"Deviazione standard pesata: {result['dev_std_pesata']:.2f}")
    if result['p16_score'] is not None and result['p84_score'] is not None:
        lines.append(f"  Range a percentili pesati (16-84, si adatta a distribuzioni non a campana): "
                     f"{result['p16_score']:.1f} - {result['p84_score']:.1f} "
                     f"(Stadio B -- forma usata dallo Stadio C per il range di confidenza finale)")
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
    lines.append("NOTA: i fattori granulari seguenti sono SOLO DIAGNOSTICI, NON entrano nello "
                 "score atteso (calibrazione 25/07: peggioravano il MAE per il portiere). "
                 "Falli/efficacia offensiva/eventi rari rimossi il 26/07 (peso 0.0% su 268 "
                 "partite reali, vedi inspect_granular_weights.py).")
    lines.append(f"Fattore possesso (casa/trasferta, da dati reali, non applicato): {result['fattore_possesso']:.3f}")
    lines.append(f"Fattore passaggio (accurate_pass/final_third/att_assist, non applicato): {result['fattore_passaggio']:.3f}")
    lines.append(f"Fattore goalkeeping (saves/saved_ibox/good_high_claim/ecc., 8 voci, non applicato): {result['fattore_goalkeeping']:.3f}")
    lines.append(f"Fattore gol subiti (goals_conceded, con cap, non applicato): {result['fattore_gol_subiti']:.3f}")
    lines.append(f"Tasso storico clean sheet (porta inviolata nei primi 60'): {result['clean_sheet_rate']:.1%} "
                 f"(bonus atteso incorporato nella media pesata: ~{result['bonus_clean_sheet_atteso']:.1f}pt)")
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
    lines.append(f"Score atteso: {result['score_atteso']:.1f} "
                 f"(range {result['range_low']:.1f} - {result['range_high']:.1f}, "
                 f"Stadio C: percentili pesati ri-centrati sull'avversario/trend)")

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
    lines.append("--- PARAMETRI DI PARTENZA (riusati dagli attaccanti, in fase di ricalibrazione) ---")
    lines.append(f"half_life={HALF_LIFE_GAMES}, range_mult={RANGE_MULTIPLIER}, "
                 f"opp_sens={OPPONENT_SENSITIVITY}, trend_int={TREND_INTENSITY} (usati per la predizione sopra)")
    lines.append("Il grid search COMPLETO (72 combinazioni) gira per questo giocatore e i risultati "
                 "vengono salvati su disco per l'aggregazione cross-player nel job 'aggregate' — "
                 "i parametri sopra restano quelli di partenza finche' l'aggregazione non ne fissa di nuovi.")

    lines.append("")
    lines.append("--- BACKTEST RIGOROSO (migliore combinazione dal grid search) ---")
    rbt = result.get('rigorous_backtest') or {}
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
                     "Questa e' la MIGLIORE combinazione trovata dal grid search per QUESTO "
                     "giocatore — la combinazione vincente definitiva emergera' dall'aggregazione "
                     "cross-player nel job 'aggregate'.")
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
        breaker_active = _circuit_breaker_tripped()
        if idx > 1 and not breaker_active:
            pause_s = 2.0  # pausa base tra giocatori (29/07, ridotta da 10s: zero 429 osservati anche a parallelismo molto piu' alto in discovery, vedi RIASSUNTO sez. 30)
            log(f"Pausa di {pause_s}s prima del prossimo giocatore...")
            time.sleep(pause_s)

        log(f"\n{'='*70}\n[{idx}/{len(slugs_to_process)}] Elaborazione giocatore: {slug}\n{'='*70}")

        # Retry progressivo se il primo tentativo fallisce (es. per il limite di
        # complessita' dell'API): 10s, poi 20s, poi 40s di attesa tra i tentativi,
        # fino a un totale cumulativo di attesa di circa 60s, poi si desiste e si
        # passa comunque al giocatore successivo (senza bloccare l'intero test).
        # Circuit breaker (29/07): con un blocco CloudFront gia' rilevato su un
        # giocatore precedente in questa job, ritentare e' inutile -- un solo
        # tentativo secco, zero attesa, si passa subito al prossimo.
        result = None
        last_exception = None
        retry_delays = [] if breaker_active else [10.0, 20.0, 40.0]
        attempt = 0
        cumulative_wait = 0.0
        if breaker_active:
            log(f"[{slug}] Circuit breaker attivo (blocco CloudFront gia' rilevato in questa job) "
                f"-- salto i retry con attesa, un solo tentativo secco.")

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
            if _STRUCTURAL_INSUFFICIENCY:
                log(f"[{slug}] Fallimento STRUTTURALE (storico realmente insufficiente, "
                    f"non transitorio) -- nessun retry, non cambierebbe nulla.")
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

        # NUOVO (26/07, monitoraggio MAE live): logga la predizione appena
        # generata (pending) per poterne verificare l'accuratezza reale una
        # volta giocata la partita -- vedi live_prediction_log.py. No-op in
        # CALIBRATION_MODE (gestito internamente alla funzione), zero
        # chiamate API aggiuntive, nessun impatto su score_atteso.
        log_live_prediction(OUTPUT_DIR, CALIBRATION_MODE, 'gk', result)

        all_sections.append(f"\n{'#'*70}\n# GIOCATORE: {slug}\n{'#'*70}\n" + output_text)
        summary_rows.append((slug, 'OK', result.get('score_atteso'), result.get('range_low'),
                              result.get('range_high'), result.get('target_competition', ''),
                              result.get('player_team_slug'), result.get('next_opponent_team_slug')))
        log(f"[{slug}] OK: score atteso {result.get('score_atteso'):.1f} "
            f"(range {result.get('range_low'):.1f} - {result.get('range_high'):.1f})")

        # Salvataggio grid_results per QUESTO giocatore, su disco, per il job
        # 'aggregate' separato che calcolera' la combinazione vincente cross-player
        # (stessa strategia usata per gli attaccanti).
        grid_dir = os.path.join(OUTPUT_DIR, 'grid_search')
        if not os.path.exists(grid_dir):
            os.makedirs(grid_dir)
        grid_export = [
            {'label': r['label'], 'half_life': r['half_life'], 'range_multiplier': r['range_multiplier'],
             'opponent_sensitivity': r['opponent_sensitivity'], 'trend_intensity': r['trend_intensity'],
             'mae': r['mae'], 'pct_dentro_range': r['pct_dentro_range'],
             'n_test': len(r.get('rows') or [])}
            for r in (result.get('grid_results') or []) if r.get('mae') is not None
        ]
        grid_path = os.path.join(grid_dir, f'{slug}_grid.json')
        with open(grid_path, 'w', encoding='utf-8') as f:
            json.dump(grid_export, f, ensure_ascii=False, indent=2)

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
    summary_lines.append("CONSIGLIO PORTIERI — ORDINATO PER PROJECTED SCORE")
    summary_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    summary_lines.append(f"Parametri fissi per tutti: half_life={HALF_LIFE_GAMES}, "
                         f"range_mult={RANGE_MULTIPLIER}, min_starter_odds={MIN_STARTER_ODDS:.0%}")
    summary_lines.append("=" * 70)
    for idx, (slug, status, atteso, range_low, range_high, note, team_slug, opp_slug) in enumerate(ok_rows, 1):
        low = round(range_low)
        high = round(range_high)
        summary_lines.append(f"{idx}) {slug}: {round(atteso)} pt attesi ({low}-{high})")
        # NUOVO (26/07, tema correlazione GK-DEF): riga parseable con squadra/
        # avversario, letta da build_consiglio_gk.py per portarla fino a
        # build_formazione_finale.py (evitare di schierare insieme portiere
        # e giocatore di movimento le cui squadre si affrontano).
        summary_lines.append(f"   SQUADRA: {team_slug or 'N/D'} | AVVERSARIO: {opp_slug or 'N/D'}")
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
