"""
Tool_formazione_mls_fwd_all (test TUTTI gli attaccanti MLS in_season posseduti)

Estende test_multi_fwd.py: invece di una lista statica di 7 giocatori, legge
la lista COMPLETA degli attaccanti MLS in_season posseduti (~42 giocatori,
generata da mls_fwd_discovery.py) da mls_fwd_discovery/player_slugs.json.
Fallback su una lista statica ridotta se il file non esiste (es. esecuzione
manuale senza aver ancora girato la discovery).

Formula REALE in produzione (RISCRITTA P1/passaggio 2, B19: la vecchia
versione elencava fattore_forza_avversario nel prodotto, mai applicato
davvero -- verificato per data-flow + test A/A OPPONENT_SENSITIVITY=1e9 ->
score_atteso invariato). Vedi compute_score_atteso_fwd:
  grezzo = level_score_atteso(eventi decisivi x opponent_lambda_mult)
           + media_granulari_pesata * fattore_trend_granulare
           + fwd_offense_granular_delta (granulare offensivo x poss.persi avv.)
  grezzo_corretto = shrinkage(grezzo, prior dinamico da presence_rate)
  risultato = grezzo_corretto * fattore_casa_trasferta
              + Stadio D (delta venue su passaggio)
  range_confidenza = +/- dev_std_pesata * RANGE_MULTIPLIER

RARE_EVENTS_STATS (eventi rari) RIMOSSO il 26/07 dai gruppi granulari
diagnostici: pesava 0.1% sul movimento del punteggio su 915 partite reali
(inspect_granular_weights.py) -- rumore puro, nessun segnale perso.

FIX Finding 3 (25/07, audit logica): fattore_casa_trasferta era calcolato sul
punteggio TOTALE della partita, che pero' include gia' dentro di se' l'intero
contributo di falli/duelli/passaggio/ecc. -- risultando in un doppio
conteggio dell'effetto venue (una volta globale, una volta per ogni gruppo
granulare). Ora fattore_casa_trasferta si calcola SOLO sul RESIDUO (score
totale meno la somma di tutti i gruppi granulari tracciati), cosi' l'effetto
venue viene applicato esattamente una volta per ogni punto di score, mai due.

NUOVO in questa versione (25/07, richiesta esplicita utente):
- PARAMETRI FISSATI: grid search cross-player completato su 14 giocatori,
  combinazione vincente individuata (MAE medio 18.13, copertura media
  68.93% — praticamente perfetta). Il grid search NON gira piu' ad ogni
  esecuzione: i parametri sono ora costanti fisse. VALORI CORRENTI (B16, P7
  passaggio 2: questa riga diceva ancora TREND_INTENSITY=0.7, stantio da
  mesi) HALF_LIFE_GAMES=6.0, RANGE_MULTIPLIER=1.15, TREND_INTENSITY=0.0
  (spento, vedi costante sotto per la misura che l'ha azzerato).
  OPPONENT_SENSITIVITY=29.0 resta solo per la funzione diagnostica legacy
  rigorous_backtest (non tocca score_atteso), con un solo backtest rigoroso
  (non piu' 72 combinazioni) per calcolare MAE/copertura di riferimento per
  il singolo giocatore — molto piu' veloce.
- Output riepilogo: "CONSIGLIO ATTACCANTI" ordinato per score atteso
  decrescente, formato compatto "N) slug: X pt attesi (low-high)" — projected
  score come numero secco arrotondato + range, non piu' tabella dettagliata.
- Lista giocatori letta dinamicamente da mls_fwd_discovery/player_slugs.json
  (generata dal job 'discover' in .yml prima di questo job).

Filtro secco su starterOddsBasisPoints della partita target — se <
MIN_STARTER_ODDS (70%), il giocatore viene ESCLUSO dall'analisi (non solo
pesato come moltiplicatore graduale in P(gioca)).
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
# cartella, additivo/diagnostico -- vedi formazione_francia2/predict/
# live_prediction_log.py per motivazione e dettagli. sys.path[0] e' gia'
# la cartella di questo script quando lanciato come `python
# formazione_francia2/predict/test_mls_fwd_all.py`, quindi l'import diretto
# funziona a prescindere dalla cwd.
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
# GLOBALE (tutti gli attaccanti MLS di qualita', non solo posseduti) invece
# di quella dei posseduti, e riesegue il grid search COMPLETO (72
# combinazioni) invece del singolo backtest sui parametri gia' fissati --
# usato SOLO per la ricalibrazione one-shot su piu' dati, mai in produzione.
CALIBRATION_MODE = os.environ.get('CALIBRATION_MODE', 'no').strip().lower() in ('1', 'true', 'si', 'yes')

DISCOVERY_FILE = os.path.join(
    'formazione_francia2/output/francia2_fwd_discovery_global' if CALIBRATION_MODE else 'formazione_francia2/output/francia2_fwd_discovery',
    'player_slugs.json')

# Fallback statico SOLO se mls_fwd_discovery/player_slugs.json non esiste
# ancora (es. primo run senza aver girato il job discover, o esecuzione
# manuale locale). In condizioni normali la lista vera arriva dal file.
_FALLBACK_PLAYER_SLUGS = [
    'prince-osei-owusu',
    'anders-dreyer',
    'zavier-gozo',
    'ahoueke-denkey',
    'heung-min-son',
    'jesus-ferreira',
    'kristoffer-velde',
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
HALF_LIFE_GAMES = 6.0  # AGGIORNATO (03/08): 25.0 -> 6.0. Rimisurato con taratura_halflife_trend.py, che chiama compute_score_atteso_fwd (la funzione vera) invece della formula moltiplicativa del vecchio grid -- 885 attaccanti, 18.992 punti walk-forward. Il minimo di SOLO MAE sta a 1.5 (-1.07%), ma li' la correlazione previsto/realizzato scende da 0.250 a 0.220 e la selezione dei primi cinque da 27.6% a 24.5% del divario caso-oracolo: e' il modello che impara a predire tutti vicino alla mediana, ottimo sul MAE e inutile per SCEGLIERE. A 6.0 migliorano entrambe le cose: MAE 14.735 (-0.50%), correlazione 0.250 (invariata), selezione 28.2% (+0.6 pt), ed e' il massimo della selezione su tutta la griglia 4-25. Regge fuori campione (meta' giocatori contro l'altra meta'). Storia del valore precedente sotto.  # AGGIORNATO (29/07): retuning post-fix opponent_lambda_mult/Stadio D/goals_conceded cap, backtest walk-forward su TUTTE le 28 leghe (360 giocatori) -- ginocchio rendimento decrescente a 25 (MAE -0.32% circa vs 12.0), grid esteso fino a 150 senza vero minimo interno.
RANGE_MULTIPLIER = 1.15  # AGGIORNATO (30/07, richiesta esplicita utente): centrato sulla copertura reale target ~68% (validate_range_multiplier_coverage.py, 539 giocatori/5798 punti test: 1.4 dava 80.3% di copertura, troppo largo; 1.15 ~68%, interpolato tra 1.10=64.5% e 1.20=70.5%). Solo cosmetico -- non tocca score_atteso/selezione, cambia solo l'ampiezza del range mostrato.
OPPONENT_SENSITIVITY = 29.0  # FISSATO (25/07): idem
SPLIT_FACTOR_SCALE_PER_STD = 0.05  # NUOVO (25/07, audit logica): sensibilita' dei fattori granulari, in %/deviazione standard storica del gruppo (sostituisce la vecchia scala fissa 1%/punto)
TREND_INTENSITY = 0.0  # AZZERATO (03/08) dopo il fix delle finestre sovrapposte in compute_trend_factor. Rimisurato sulla formula vera: il MAE peggiora in modo MONOTONO al crescere del trend su tutti e quattro i ruoli, anche ora che lo stimatore misura ultime 5 contro le 5 PRECEDENTI invece che contro le ultime 10. Non era la finestra sbagliata a rendere inutile il trend: la forma recente, in questo modello, non aggiunge niente sopra la media pesata. GK e DEF erano gia' a 0.0 per la stessa ragione, arrivandoci per altra strada. Storia del valore precedente sotto.  # DIMEZZATO 0.3 -> 0.15 (03/08) INSIEME al fix delle finestre sovrapposte in compute_trend_factor: lo stimatore ora misura ultime 5 contro 5 PRECEDENTI invece che ultime 5 contro ultime 10, e con finestre disgiunte la stessa forma produce un delta circa doppio (con a=ultime5 e b=precedenti5, (a-b)/b invece di (a-b)/(a+b)). Dimezzare l'intensita' lascia la MAGNITUDINE del trend dov'era oggi mentre il SEGNALE diventa quello giusto -- cioe' il fix non introduce da solo un cambio di comportamento non tarato. DA RITARARE con un grid search dedicato dopo il fix delle partite senza dettaglio (mask_weights), che oggi inquina proprio questa misura. Valore precedente: 0.3  # AGGIORNATO (29/07): backtest walk-forward su tutte le leghe post-retuning half_life, MAE -0.73% -- applicato SOLO MLS/Korea per richiesta esplicita utente, altre 26 leghe restano a 1.0 (backlog)
# FISSATO (27/07, tema backlog "outlier/hot-streak" — caso Antino Lopez, DEF a
# bassa titolarita' con picchi isolati sovrastimati dalla media pesata):
# backtest walk-forward rigoroso su tutti i ruoli (formazione_francia2/diagnostics/
# validate_outlier_shrinkage.py) mostra che tirare la media pesata esponenziale
# verso la media di ruolo (Empirical Bayes, pseudo-count SHRINK_K_OUTLIER_FWD)
# migliora il MAE reale SOLO per FWD in modo solido: -2.9% proprio sul
# segmento a rischio n<8 partite storiche (quello che ha motivato il tema),
# con il segmento n>=8 sostanzialmente invariato (+0.09% a k=7, dentro il
# rumore) — a differenza di DEF/MID dove il guadagno principale cade sul
# segmento SBAGLIATO (n>=8) o e' sotto soglia di rumore (<1%), vedi
# validate_outlier_shrinkage_tiered.py per il dettaglio DEF/MID. k=5 scelto
# (non il k=7 leggermente migliore sul solo n<8) per coerenza con lo
# shrink_k=5.0 gia' in produzione in media_condizionata() (Stadio D,
# level_score) — stesso ordine di grandezza, stessa idea di "partite fittizie"
# di prior, decisione presa una volta sola per tutte le correzioni di questo
# tipo. MEDIA_RUOLO_FWD_PRIOR = media grezza di tutti gli score FWD nel pool
# esteso a 10 campionati (MLS, K League, Brasile, Croazia, Portogallo,
# Austria, Scozia, Belgio, Olanda, Spagna), ricalibrata sessione 27/07 con
# formazione_francia2/diagnostics/validate_outlier_shrinkage.py (variabile
# media_ruolo) -- costante strutturale, non ricalcolata a runtime (stessa
# semplificazione accettata per gli altri "FISSATO" sopra). SHRINK_K_OUTLIER_FWD
# resta 5.0 (differenza vs k=4 vista trascurabile, nessun cambio li').
SHRINK_K_OUTLIER_FWD = 15.0  # AGGIORNATO (03/08): 5.0 -> 15.0. Rimisurato DOPO il fix delle partite senza dettaglio, ed e' proprio quel fix a spostare l'ottimo: prima il grezzo era gonfiato (il punteggio intero finiva nel granulare), quindi tirarlo verso il prior sembrava dannoso e la taratura sceglieva poco shrinkage. Col grezzo corretto conviene tirare di piu'. Misurato su 18.992 punti walk-forward, 885 attaccanti: MAE 14.092 -> 14.049 (-0.31%), correlazione previsto/realizzato 0.250 -> 0.257, selezione dei primi cinque 28.2% -> 28.4%. Tutte e tre le misure si muovono nello stesso verso, che e' la condizione per applicare. Storia del valore precedente sotto.  # AGGIORNATO (29/07, modello unico GLOBALE su 25 leghe pooled): backtest walk-forward su ~1700 punti di test, MAE -0.49% -- la vecchia esclusione "peggiora fuori MLS" non e' risultata riproducibile col volume di dati attuale (vedi RIASSUNTO sez.29), stesso valore ora su TUTTE le leghe
MEDIA_RUOLO_FWD_PRIOR = 53.74  # AGGIORNATO (29/07): media grezza pool 25 leghe (solo diagnostico, la produzione usa il prior dinamico da presence_rate)
MIN_MINUTES_PLAYED = 60  # partite giocate sotto questa soglia (subentri) escluse dalla finestra
MIN_STARTER_ODDS = 0.0  # DISATTIVATO (28/07, richiesta esplicita utente): era un secondo filtro starter-odds fisso al 70%, indipendente e non collegato alla soglia scelta in discovery_fixture.py -- anche con starter_odds_min=0 nel workflow, questo continuava a scartare in silenzio chi era sotto 70%. discovery_fixture.py applica gia' il filtro configurabile a monte, questo era ridondante.
SKIP_GRANULAR_DETAIL = False  # RIPRISTINATO (24/07): con la strategia GitHub Actions matrix, ogni giocatore gira in un job/processo SEPARATO con budget di complessita' fresco — il problema di saturazione cumulativa (che colpiva il 2o+ giocatore in un unico processo) non si presenta piu'. I fattori granulari (falli/duelli/passaggio/ecc.) sono quindi di nuovo calcolati per ogni giocatore.

OUTPUT_DIR = 'formazione_francia2/output/francia2_fwd_calibration' if CALIBRATION_MODE else 'formazione_francia2/output/francia2_fwd_all'
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
_CIRCUIT_BREAKER_PATH = '/tmp/sorare_cloudfront_block_francia2_fwd.marker'

# Flag "non ritentare" (29/07, fix reale: molti retry da 60s sprecati su
# giocatori con storico REALMENTE insufficiente -- es. panchinari con quasi
# solo DID_NOT_PLAY -- che non cambia riprovando la stessa query pochi
# secondi dopo. Il loop di retry in main() lo controlla per uscire subito
# invece di aspettare fino a 60s per un fallimento STRUTTURALE (non
# transitorio come un 403/timeout, dove riprovare puo' davvero aiutare).
_STRUCTURAL_INSUFFICIENCY = False


def _circuit_breaker_tripped():
    return os.path.exists(_CIRCUIT_BREAKER_PATH)


def _trip_circuit_breaker(reason):
    if not _circuit_breaker_tripped():
        try:
            with open(_CIRCUIT_BREAKER_PATH, 'w', encoding='utf-8') as f:
                f.write(reason)
        except OSError:
            pass

COOKIES = os.environ.get('SORARE_COOKIE', '')
# 12/08: alza il tetto di rate/complessita' sull'account, si aggiunge al cookie.
APIKEY = os.environ.get('SORARE_APIKEY', '')

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
    print(f"[{ts}] [test_fwd] {msg}")


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
# PACING DI PARTENZA CONFIGURABILE (12/08/2026). Il valore storico 0,2s e'
# giusto per UN processo, ma la fase predict gira su 20 runner in parallelo e
# il limite di Sorare e' d'ACCOUNT: 20 runner a 0,2s vogliono dire fino a 100
# query al secondo verso un account che, misurato, ne regge circa 9. Il primo
# 429 e' quindi garantito, e costa 194-247 secondi di Retry-After -- molto piu'
# di quanto si risparmi correndo.
# Misura che ha portato qui (run 31594791690, dopo i fix sulle query): la fase
# predict fa 2499 query, ne prende 20 col 429 e butta 4728 secondi ad
# aspettare, cioe' il 65% del tempo della fase. Il tasso di 429 per query e'
# rimasto lo stesso di quando le query erano 6857: non e' il volume a farli
# scattare, e' la raffica.
# Default INVARIATO (0,2s): fuori dal workflow -- bot, scouting, run locali --
# non cambia niente. Nel workflow si alza con SORARE_PACING_MIN.
MIN_QUERY_INTERVAL_SECONDS = float(os.environ.get('SORARE_PACING_MIN', '0.2'))
# Il tetto resta 4 volte la partenza, cosi' l'adattamento dopo un 429 ha
# ancora spazio per rallentare (0,2 -> 0,8 col default; 1,0 -> 4,0 nel
# workflow).
MAX_QUERY_INTERVAL_SECONDS = max(0.8, MIN_QUERY_INTERVAL_SECONDS * 4)
_PACING_FILE = os.path.join(
    os.environ.get('RUNNER_TEMP') or tempfile.gettempdir(), 'sorare_pacing.txt')


# STATO DEL PACING CONDIVISO FRA I PROCESSI (12/08/2026, difetto REALE).
# Il file conteneva solo l'intervallo; il MOMENTO dell'ultima query stava in
# una variabile di processo. Ma nella fase predict OGNI GIOCATORE E' UN
# PROCESSO NUOVO (il workflow lancia `python test_*.py` una volta per slug),
# quindi quella variabile ripartiva da zero e la PRIMA query di ogni processo
# non aspettava mai. Con ~1,3 query per giocatore -- dopo i fix sulle cache --
# il freno non entrava praticamente mai in funzione: alzare l'intervallo da
# 0,2s a 1,0s non ha cambiato niente (run 31596309760), e la conclusione
# sbagliata che se ne stava per trarre era "i 429 non dipendono dalla
# velocita'". Non era stata provata: il freno era staccato.
# Ora nel file stanno DUE numeri, "intervallo ultimo_timestamp", e il momento
# dell'ultima query attraversa i processi. Nessuna corsa fra processi: dentro
# uno shard i giocatori sono elaborati in sequenza dal ciclo bash, un processo
# alla volta.
def _pacing_stato():
    try:
        with open(_PACING_FILE, encoding='utf-8') as f:
            parti = f.read().split()
        intervallo = float(parti[0])
        ultimo = float(parti[1]) if len(parti) > 1 else 0.0
    except (OSError, ValueError, IndexError):
        return MIN_QUERY_INTERVAL_SECONDS, 0.0
    return (min(MAX_QUERY_INTERVAL_SECONDS,
                max(MIN_QUERY_INTERVAL_SECONDS, intervallo)), ultimo)


def _scrivi_pacing(intervallo, ultimo):
    try:
        with open(_PACING_FILE, 'w', encoding='utf-8') as f:
            f.write(f'{intervallo} {ultimo}')
    except OSError:
        pass


def _pacing_corrente():
    return _pacing_stato()[0]


def _rallenta_pacing():
    """Alza la pausa (e la rende visibile ai processi successivi dello stesso
    runner). Chiamata solo quando Sorare risponde 429."""
    intervallo, ultimo = _pacing_stato()
    nuovo = min(MAX_QUERY_INTERVAL_SECONDS, intervallo * 2)
    _scrivi_pacing(nuovo, ultimo)
    return nuovo


def _throttle_query():
    intervallo, ultimo = _pacing_stato()
    ora = time.time()
    if ultimo:
        manca = intervallo - (ora - ultimo)
        # 'manca > intervallo' vuol dire orologio andato indietro o file di
        # un'altra run: si ignora invece di dormire un tempo assurdo.
        if 0 < manca <= intervallo:
            time.sleep(manca)
    _scrivi_pacing(intervallo, time.time())


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
    if APIKEY:
        headers['APIKEY'] = APIKEY

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


# DETTAGLIO IN BATCH (12/08/2026, misurato sulla run 31585784239: il
# dettaglio granulare era il 57% delle query della fase predict -- 127 query
# su 222 in uno shard tipico -- e si chiedeva UNA PARTITA PER VOLTA).
#
# so5.playerGameScore accetta gli alias, quindi piu' partite stanno nella
# stessa richiesta. Il tetto e' la complessita': SONDATO sull'API vera
# (query pubblica, nessun cookie) il 12/08/2026 --
#   8 partite  -> "complexity of 505, which exceeds max complexity of 500"
#  10 partite  -> "complexity of 631"
# cioe' 63,1 di complessita' a partita, zero base: il massimo teorico e' 7.
# Qui se ne chiedono 6 (379) per lasciare margine, con la stessa logica del
# commento su PAGINA_GAME_LOG: una richiesta rifiutata costa molto piu' di
# una richiesta in piu'.
#
# Con l'APIKEY (mai arrivata, vedi il backlog) il tetto sarebbe 30000, cioe'
# 475 partite per richiesta: se un giorno arriva, e' qui che si alza.
BATCH_DETTAGLIO = 6

_BLOCCO_DETTAGLIO = """
    d%(i)d: playerGameScore(id: $id%(i)d) {
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
    }"""


def _query_dettaglio_batch(n):
    firma = ', '.join(f'$id{i}: ID!' for i in range(n))
    corpo = ''.join(_BLOCCO_DETTAGLIO % {'i': i} for i in range(n))
    return f'query PlayerGameScoreDetailBatch({firma}) {{\n  so5 {{{corpo}\n  }}\n}}'


def precarica_dettagli_batch(nodi, cache):
    """Riempie la cache dei dettagli per le partite FINAL che non ci sono
    ancora, 6 alla volta. Non ritorna niente: chi chiama continua a passare
    da fetch_game_detail, che a quel punto trova tutto in cache.

    Progettata perche' il caso peggiore sia ESATTAMENTE il comportamento di
    prima: se la richiesta in batch fallisce (errore, 429 con retry esauriti,
    campo rifiutato) non si scrive niente in cache e le partite vengono
    chieste una per una dal ciclo di sempre. Nessuna partita non-FINAL entra
    qui: quelle cambiano ancora e vanno sempre richieste fresche."""
    mancanti = []
    for node in nodi:
        if node.get('scoreStatus') != 'FINAL':
            continue
        sid = node['id'].replace('So5Score:', '')
        if sid not in cache:
            mancanti.append(sid)
    if not mancanti:
        return
    presi = 0
    for i in range(0, len(mancanti), BATCH_DETTAGLIO):
        lotto = mancanti[i:i + BATCH_DETTAGLIO]
        variabili = {f'id{j}': sid for j, sid in enumerate(lotto)}
        data = graphql_query(_query_dettaglio_batch(len(lotto)), variabili,
                             operation_name="PlayerGameScoreDetailBatch")
        if not data or data.get('errors'):
            log(f"  [FASE 3/4] batch dettaglio da {len(lotto)} rifiutato "
                f"({str((data or {}).get('errors'))[:160]}): le partite di "
                f"questo lotto verranno chieste una per una.")
            continue
        nodi_ris = ((data.get('data') or {}).get('so5') or {})
        for j, sid in enumerate(lotto):
            ris = nodi_ris.get(f'd{j}')
            if ris and ris.get('id'):
                cache[sid] = ris
                presi += 1
    if presi:
        log(f"  [FASE 3/4] dettaglio in batch: {presi} partite in "
            f"{(len(mancanti) + BATCH_DETTAGLIO - 1) // BATCH_DETTAGLIO} "
            f"richieste invece di {len(mancanti)}.")


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
# CACHE INCREMENTALE DEL GAME LOG (25/07, retrofit dal ruolo difensore dove
# e' stata introdotta per prima). Cache separata da quella dei DETTAGLI
# granulari (fetch_game_detail sopra, gia' esistente) — questa e' per il
# game log BASE (score, data, status, minutaggio, teams), non il
# detailedScore. Una volta che una partita e' FINAL viene salvata su disco e
# non richiede piu' una query completa nelle run successive.
# ---------------------------------------------------------------------------

GAME_LOG_CACHE_DIR = os.path.join(OUTPUT_DIR, '.game_log_cache')
GAME_LOG_REFRESH_COUNT = 2  # ABBASSATO (25/07): tool usato con cadenza settimanale (1 partita MLS/settimana per squadra), 2 basta a coprire l'ultima giornata + margine, riduce ulteriormente le query rispetto a 5


def load_game_log_cache(player_slug):
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


# STORIA COMPLETA -- metadati a fianco della cache (12/08/2026, spreco REALE
# misurato sulla run 31585784239, fase predict).
#
# Il criterio per decidere se ri-scaricare il game log era "ho meno di
# WINDOW_SIZE (30) partite FINAL in cache?". Per un giocatore che di partite
# in tutta la sua carriera Sorare ne ha 21 (giovane, campionato appena
# aperto, lega piccola) quella condizione NON e' MAI soddisfatta: ogni run
# ri-paginava le sue 60 partite richieste in 6 query, per sempre, pur avendo
# gia' in cache tutto quello che Sorare possiede.
# Misurato su quella run: 523 giocatori su 1151 (45%) cadevano qui, e la
# fase predict ha fatto 6831 query totali con 45 risposte 429 -- 6193
# secondi di sola attesa Retry-After, il 60% del tempo della fase.
#
# Qui si segna, in un file a fianco alla cache, che per quel giocatore la
# paginazione e' arrivata alla FINE della storia (hasNextPage falso, non un
# errore a meta'). Alla run dopo basta una pagina sola per intercettare le
# partite nuove, invece di sei.
#
# File SEPARATO di proposito (<slug>_gamelog.meta.json, non una chiave dentro
# il JSON della cache): la cache game-log e' condivisa e ci leggono dentro il
# generatore, lo scouting e analisi_manager iterando su cache.values() come se
# fossero tutte partite -- una chiave di metadati la' dentro diventerebbe una
# partita fantasma. Il suffisso non finisce per '_gamelog.json', quindi i
# conteggi dei file in cache non cambiano.
def _game_log_meta_path(cache_file):
    return cache_file[:-len('.json')] + '.meta.json'


def load_game_log_meta(cache_file):
    p = _game_log_meta_path(cache_file)
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_game_log_meta(cache_file, meta):
    try:
        with open(_game_log_meta_path(cache_file), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, sort_keys=True)
    except OSError:
        pass


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
FINE_STORIA_RAGGIUNTA = False  # vedi fetch_game_scores/load_game_log_meta
PAGINAZIONE_INTERROTTA = False  # paginazione finita male (errore, o tetto
                                # di pagine): quello che abbiamo in mano
                                # potrebbe essere meta' storia, quindi non
                                # si puo' concludere niente sulla cache

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
    global FINE_STORIA_RAGGIUNTA, PAGINAZIONE_INTERROTTA
    # Azzerati PRIMA di qualunque uscita: se lo si azzerasse solo sul ramo
    # paginato, un giocatore risolto con una pagina sola erediterebbe il flag
    # del giocatore precedente dello stesso shard e verrebbe marcato "storia
    # completa" a torto (trovato con un test locale, non in produzione).
    FINE_STORIA_RAGGIUNTA = False
    PAGINAZIONE_INTERROTTA = False
    if fetch_count <= PAGINA_GAME_LOG:
        # Pagina singola: nessun pageInfo, quindi non si puo' concludere
        # niente sulla fine della storia -- il flag resta False.
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
            # Interrotta a meta' (429 con retry esauriti, errore GraphQL): di
            # questo giocatore abbiamo forse meta' storia. Nessuna conclusione
            # sulla cache puo' essere tratta da un giro andato cosi'.
            PAGINAZIONE_INTERROTTA = True
            break
        if base is None:
            base = data
        conn = player.get('allPlayerGameScores') or {}
        nuovi = conn.get('nodes') or []
        nodi += nuovi
        info = conn.get('pageInfo') or {}
        after = info.get('endCursor')
        if not nuovi or not info.get('hasNextPage') or not after:
            # Fine PULITA della storia: Sorare dice che non c'e' altro. Solo
            # da qui si puo' concludere "ho tutto" -- le altre uscite del
            # loop (errore a meta', tetto di 12 pagine, quota richiesta
            # raggiunta) NON lo dimostrano e lasciano il flag a False.
            FINE_STORIA_RAGGIUNTA = True
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
    Vedi test_def.py per la documentazione completa della strategia."""
    cache, cache_file = load_game_log_cache(slug)
    meta = load_game_log_meta(cache_file)
    n_cached_final = sum(1 for v in cache.values() if v.get('scoreStatus') == 'FINAL')

    log(f"[FASE 1/4] Cache game log per {slug}: {len(cache)} partite in cache "
        f"({n_cached_final} FINAL).")

    if n_cached_final >= target_window_size:
        fetch_count = GAME_LOG_REFRESH_COUNT
        log(f"[FASE 1/4] Cache sufficiente ({n_cached_final} >= {target_window_size}), "
            f"refresh leggero: richiesta solo ultime {fetch_count} partite.")
    else:
        fetch_count = max(target_window_size * 2, 30)
        log(f"[FASE 1/4] Cache insufficiente ({n_cached_final} < {target_window_size}), "
            f"fetch ampio: richiesta ultime {fetch_count} partite (fallback non-incrementale).")

    # STORIA COMPLETA (vedi il commento su load_game_log_meta): se in una run
    # precedente la paginazione era arrivata alla fine della storia di questo
    # giocatore, e da allora la cache non e' stata svuotata, non ha senso
    # richiedere di nuovo 60 partite in 6 pagine -- Sorare non ne ha altre.
    # Una pagina sola basta a intercettare le partite nuove (al massimo
    # PAGINA_GAME_LOG in una settimana, cioe' molte piu' di quante se ne
    # giochino). Se quella pagina rivelasse piu' storia del previsto, il
    # flag viene tolto qui sotto e la run successiva torna al fetch ampio.
    if fetch_count > PAGINA_GAME_LOG \
            and (meta.get('storia_completa') or meta.get('ampio_inutile')) \
            and len(cache) >= (meta.get('partite_note') or 0) > 0:
        fetch_count = PAGINA_GAME_LOG
        log(f"[FASE 1/4] Storia gia' nota in cache ({len(cache)} partite, "
            f"meno di {target_window_size} perche' il giocatore non ne ha di piu'): "
            f"una sola pagina di controllo invece di {max(target_window_size * 2, 30)}.")

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

    updated_count = 0
    partite_mai_viste = 0   # id assenti dalla cache: vedi 'ampio_inutile' sotto
    for node in fetched_past:
        node_id = node.get('id')
        if not node_id:
            continue
        was_final_before = cache.get(node_id, {}).get('scoreStatus') == 'FINAL'
        if node_id not in cache:
            partite_mai_viste += 1
        cache[node_id] = node
        if not was_final_before:
            updated_count += 1

    save_game_log_cache(cache, cache_file)
    # Aggiorna il marcatore di storia completa (vedi load_game_log_meta).
    if FINE_STORIA_RAGGIUNTA:
        if not meta.get('storia_completa') or meta.get('partite_note') != len(cache):
            meta['storia_completa'] = True
            meta['partite_note'] = len(cache)
            save_game_log_meta(cache_file, meta)
    elif fetch_count > PAGINA_GAME_LOG and partite_mai_viste == 0 \
            and not PAGINAZIONE_INTERROTTA:
        # AMPIO INUTILE (12/08/2026, secondo giro). Caso NON coperto dal
        # marcatore sopra: il giocatore ha PIU' partite di quante se ne
        # chiedono (60) ma meno di WINDOW_SIZE in stato FINAL -- tipico di chi
        # resta spesso in panchina. La paginazione non arriva mai alla fine
        # della storia (hasNextPage resta vero), quindi 'storia_completa' non
        # scatta e il fetch ampio si ripete a ogni run riportando esattamente
        # le stesse partite. Misurato sulla run 31593062806: 528 giocatori col
        # fetch ampio, solo 148 marcati storia completa -- gli altri 380 sono
        # questo caso.
        # Qui si registra il fatto nudo: l'ultimo fetch ampio non ha portato
        # NESSUNA PARTITA MAI VISTA, quindi rifarlo non serve. La risposta era
        # valida (le risposte fallite escono prima), quindi zero id nuovi vuol
        # dire davvero zero novita'.
        # Si guardano gli ID MAI VISTI, non updated_count: quello conta i nodi
        # che non erano gia' FINAL, e per un panchinaro le sue 48 partite da
        # DID_NOT_PLAY risultano "aggiornate" a ogni run pur essendo identiche
        # (trovato con il test locale, prima del commit).
        # I cambi di stato recenti (REVIEWING -> FINAL) non si perdono: la
        # pagina di controllo copre le 10 partite piu' recenti, che sono
        # esattamente quelle che possono ancora cambiare.
        # E si controlla PAGINAZIONE_INTERROTTA: senza, due run tagliate a
        # meta' nello stesso punto (429) darebbero "zero partite nuove" e
        # marcherebbero come completa una storia di cui abbiamo solo la prima
        # meta' -- troncamento silenzioso e permanente. Trovato col test
        # locale, scenario 3.
        if not meta.get('ampio_inutile') or meta.get('partite_note') != len(cache):
            meta['ampio_inutile'] = True
            meta['partite_note'] = len(cache)
            save_game_log_meta(cache_file, meta)
    elif (meta.get('storia_completa') or meta.get('ampio_inutile')) \
            and len(cache) > (meta.get('partite_note') or 0):
        # La pagina di controllo ha portato partite nuove e la storia
        # potrebbe non essere piu' quella nota: si ricontrolla per intero
        # alla prossima run invece di fidarsi del marcatore.
        meta.pop('storia_completa', None)
        meta.pop('ampio_inutile', None)
        meta.pop('partite_note', None)
        save_game_log_meta(cache_file, meta)
    log(f"[FASE 1/4] Cache aggiornata: {updated_count} partite nuove/aggiornate, "
        f"{len(cache)} totali in cache ora.")

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


def mask_weights(weights, detail_ok_flags):
    """Pesi con le partite SENZA detailedScore azzerate (03/08, bug reale).

    Quando il dettaglio granulare di una partita non e' disponibile,
    extract_level_score() ritorna 0.0 -- che non vuol dire "livello zero", vuol
    dire "non lo so". Il codice pero' lo trattava come un valore vero, quindi
    'granulare = score - level_score' diventava il PUNTEGGIO INTERO della
    partita, e sopra ci veniva comunque riaggiunto il livello base 35 stimato
    da expected_level_from_rates(0, 0). Errore sempre nello stesso verso, cioe'
    sovrastima pura.

    Misurato sulle cache reali (mls+italia, 4 ruoli): il 3.3% delle partite
    dentro la finestra usata e' senza dettaglio, e questo colpiva 221
    giocatori con una sovrastima mediana di +2.2 punti, +5.8 al p90, +19.6 nel
    caso peggiore.

    Soluzione: la partita resta nello storico per tutto cio' che si legge dal
    game log (punteggio, casa/trasferta, avversario, data), ma pesa zero in
    tutto cio' che richiede il detailedScore. Se NESSUNA partita ha il
    dettaglio si ricade sui pesi pieni: meglio la vecchia stima imprecisa che
    una divisione per zero."""
    if not detail_ok_flags:
        return list(weights)
    masked = [w if ok else 0.0 for w, ok in zip(weights, detail_ok_flags)]
    return masked if sum(masked) > 0 else list(weights)


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
    cache -- vedi formazione_francia2/diagnostics/inspect_decisive_event_conditioning.py
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
# proprio fattore casa/trasferta indipendente. Raggruppati per CATEGORIA SORARE
# (stesse categorie mostrate nella UI Sorare: Generale/Difesa/Possesso/Passaggio/
# In attacco), come da richiesta esplicita dell'utente.
FOULS_STATS = ('fouls', 'was_fouled')
DUELS_STATS = ('duel_won', 'duel_lost', 'poss_lost_ctrl', 'interception_won')
OFFENSIVE_STATS = ('ontarget_scoring_att', 'big_chance_created', 'big_chance_missed',
                    'pen_area_entries', 'won_contest')
# Categoria "Passaggio" Sorare: stat frequenti, nessun cap necessario.
PASSING_STATS = ('accurate_pass', 'successful_final_third_passes', 'adjusted_total_att_assist')
# Categoria "Difesa" Sorare + altri eventi rarissimi: achievement compositi
# (double/triple) e azioni difensive eccezionali per un Forward, quasi sempre 0.
DEFENSE_RARE_STATS = ('double_double', 'triple_double', 'triple_triple', 'last_man_tackle',
                       'clearance_off_line', 'error_lead_to_shot', 'assist_penalty_won')
DEFENSE_RARE_CAP = 10.0


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


# --- level_score ATTESO da tasso di eventi decisivi (27/07 notte, sezione 22
# del riassunto) -- vedi formazione_francia2/predict/test_def.py per la stessa
# implementazione commentata per esteso. Rivalidato su 6 campionati: -0.78% MAE.
# B20 (P7, passaggio 2): aggiunto il gradino -3:0, mancante -- confermato
# da due screenshot Sorare indipendenti (portiere e difensore, 04/08): la
# barra del punteggio decisivo mostra i marker -3 -2 -1 0 1 2 3 4 5 sopra i
# valori 0 5 15 35 60 70 80 90 100. Il floor del clamp scende da -2 a -3.
LEVEL_TABLE = {-3: 0, -2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}
LEVEL_SCORE_POISSON_K_MAX = 6


def netto_to_level(netto):
    k = max(-3, min(5, round(netto)))
    return LEVEL_TABLE[k]


def extract_decisive_rates(detail):
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


def compute_split_factor(values, is_home_flags, target_is_home, weights=None):
    """Dato un elenco di valori granulari (uno per partita, gia' sommati per un
    gruppo di stat) e i relativi flag casa/trasferta, calcola il fattore
    casa/trasferta per QUEL gruppo, con la stessa logica del fattore principale:
    media_contesto_target / media_generale. Fattore neutro (1.0) se non ci sono
    abbastanza dati in un contesto o se la media generale e' zero/negativa.

    FIX 1 (03/08, condizione ignota): 'context_avg = home_avg if
    target_is_home else away_avg' mandava sul bucket TRASFERTA anche quando
    target_is_home era None, cioe' quando la squadra del giocatore non e'
    riconosciuta nella partita target -- un'ipotesi silenziosa, non una
    misura. Sulle cache reali il venue non e' riconosciuto nel 9.0% delle
    partite storiche (5.955 esaminate). Ora la condizione ignota da' 1.0,
    coerente con media_condizionata() che gia' faceva la cosa giusta.

    FIX 2 (03/08, pesi): le medie erano PIATTE, mentre tutto il resto del
    modello e' a decadimento esponenziale. Il fattore casa/trasferta dava
    quindi lo stesso peso a una partita di dodici mesi fa e a quella di
    domenica scorsa, e poi moltiplicava una media pesata. Ora usa gli stessi
    pesi del resto della formula; passando i pesi mascherati (mask_weights)
    esclude anche le partite senza dettaglio granulare."""
    if not values:
        return 1.0
    if target_is_home is None:
        return 1.0

    if weights is None:
        weights = [1.0] * len(values)
    total_w = sum(weights)
    if total_w <= 0:
        return 1.0

    overall_avg = weighted_mean(values, weights)
    context_pairs = [(v, w) for v, w, h in zip(values, weights, is_home_flags)
                     if h is not None and bool(h) == bool(target_is_home)]
    context_vals = [v for v, _ in context_pairs]
    if not context_vals:
        return 1.0
    context_avg = weighted_mean(context_vals, [w for _, w in context_pairs])

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
    variance = sum(w * (v - overall_avg) ** 2 for v, w in zip(values, weights)) / total_w
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
    SPLIT_SHRINK_K = 20.0  # ALZATO 5.0->20.0 (30/07): validato con backtest walk-forward, migliora la MAE su tutti i ruoli
    n_context = len(context_vals)
    shrink = n_context / (n_context + SPLIT_SHRINK_K)
    fattore = 1.0 + (delta_normalizzato * SPLIT_FACTOR_SCALE_PER_STD * shrink)
    return max(0.7, min(1.3, fattore))  # limitato per evitare correzioni estreme


def compute_trend_factor(scores, short_window=5, long_window=10, trend_intensity=1.0,
                          weights=None):
    """Confronta la media delle ultime 'short_window' partite con quella delle
    'short_window' partite PRECEDENTI (stesso pool gia' filtrato per
    competizione e minutaggio) per rilevare un trend di forma. Ritorna un
    fattore moltiplicativo centrato su 1.0: se le partite piu' recenti rendono
    piu' di quelle di prima il fattore e' > 1 (forma in crescita), viceversa
    < 1. Scala conservativa e limitata (max +-20%), per non lasciare che poche
    partite recenti dominino la predizione.
    Richiede almeno 'long_window' partite; ritorna 1.0 (neutro) altrimenti.

    FIX (03/08, finestre sovrapposte): il confronto era ultime 5 contro
    ultime 10, ma le 5 sono DENTRO le 10 -- il numeratore era un
    sottoinsieme del denominatore, quindi il rapporto risultava
    strutturalmente compresso (circa la meta' del segnale vero: con
    a = ultime 5 e b = 5 precedenti, si misurava (a-b)/(a+b) invece di
    (a-b)/b). Un giocatore passato da 40 a 60 di media dava 1.20 invece di
    1.50. Non stupisce che la taratura avesse spinto TREND_INTENSITY a 0.0
    su GK e DEF: lo stimatore era rotto, e l'intensita' ottima di uno
    stimatore rotto e' zero. Ora le due finestre sono disgiunte.

    FIX (03/08, pesi): le due medie erano piatte, sopra una media principale
    gia' pesata esponenzialmente. Ora accettano gli stessi pesi del resto
    della formula (e, se mascherati, escludono le partite senza dettaglio).

    NUOVO (25/07): trend_intensity scala il DELTA (ratio - 1.0) prima del
    clamp finale, per rendere il trend parametrizzabile nel grid search
    invece di un comportamento fisso — es. trend_intensity=0.7 attenua il
    trend, 1.3 lo amplifica."""
    if len(scores) < long_window:
        return 1.0, None, None

    recent_short = scores[-short_window:]
    precedenti = scores[-long_window:-short_window]
    if not precedenti:
        return 1.0, None, None

    if weights is not None and len(weights) == len(scores):
        w_short = weights[-short_window:]
        w_prec = weights[-long_window:-short_window]
    else:
        w_short = [1.0] * len(recent_short)
        w_prec = [1.0] * len(precedenti)

    avg_short = weighted_mean(recent_short, w_short)
    avg_prec = weighted_mean(precedenti, w_prec)

    if avg_prec == 0:
        return 1.0, avg_short, avg_prec

    ratio = avg_short / avg_prec
    scaled_ratio = 1.0 + (ratio - 1.0) * trend_intensity
    fattore = max(0.8, min(1.2, scaled_ratio))
    return fattore, avg_short, avg_prec


def rigorous_backtest(scores, is_home_flags, opponent_rankings, min_history=6,
                       half_life=None, range_multiplier=1.0, opponent_sensitivity=29.0,
                       fouls_values=None, duels_values=None, offensive_values=None,
                       passing_values=None, defense_rare_values=None,
                       residual_values=None,
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

        # fattore casa/trasferta (FIX Finding 3, 25/07): calcolato SOLO sul
        # RESIDUO (punteggio non coperto da nessun gruppo granulare), non piu'
        # sul punteggio totale grezzo -- altrimenti l'effetto casa/trasferta
        # sarebbe contato una volta qui E di nuovo dentro ogni gruppo
        # granulare che lo attraversa (doppio conteggio). Usando lo stesso
        # compute_split_factor del resto dei gruppi sul solo residuo, l'intero
        # punteggio viene aggiustato per venue esattamente una volta per punto.
        target_is_home = is_home_flags[i]
        fattore_ct = 1.0
        if residual_values is not None:
            fattore_ct = compute_split_factor(residual_values[:i], hist_home_flags, target_is_home)

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
            for values in (fouls_values, duels_values, offensive_values,
                           passing_values, defense_rare_values):
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
    # ALLARGATA (30/07): la griglia era ferma a [9.0, 12.0], residuo di una
    # versione precedente -- non includeva nemmeno i valori REALMENTE in
    # produzione oggi (GK=6.0, DEF=20.0, MID/FWD=25.0, trovati con una ricerca
    # piu' ampia mai riportata in questa griglia), rendendo il "vincitore" del
    # grid search non comparabile alla produzione vera. Ora include tutti i
    # valori di produzione attuali come candidati.
    half_lives = [6.0, 9.0, 12.0, 15.0, 20.0, 25.0, 30.0]
    range_mults = [1.2, 1.4, 1.6]  # 1.6 aggiunto: range di default alzato per la copertura
    opp_sens_values = [20.0, 29.0]
    # ALLARGATA (30/07): includeva solo [0.7, 1.0, 1.3], non i valori reali di
    # produzione (DEF=0.0, MID=0.2, FWD=0.3, GK=0.7 gia' incluso).
    trend_intensities = [0.0, 0.2, 0.3, 0.7, 1.0, 1.3]
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
                     passing_values=None, defense_rare_values=None,
                     residual_values=None):
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
                                passing_values=passing_values,
                                defense_rare_values=defense_rare_values,
                                residual_values=residual_values,
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


def compute_score_atteso_fwd(scores, is_home_flags,
                             residual_values, granulari_values,
                             pos_decisive_values, neg_decisive_values,
                             passing_values,
                             target_is_home, p_gioca=1.0,
                             half_life=None, trend_intensity=None,
                             shrink_k=SHRINK_K_OUTLIER_FWD,
                             media_ruolo_prior=MEDIA_RUOLO_FWD_PRIOR,
                             use_stadio_d=True,
                             presence_rate=None, opponent_lambda_mult=None,
                             next_opponent_team_slug=None, next_game_date=None, league='francia2',
                             offensive_values=None, detail_ok_flags=None):
    """FUNZIONE CONDIVISA (27/07, punto 26.D.4): calcola lo `score_atteso` FWD di
    PRODUZIONE, da usare SIA in build_prediction SIA nel backtest di calibrazione,
    cosi' le due non possono divergere. Gemella di compute_score_atteso_def in
    test_def.py, ma la formula FWD e' DIVERSA:
    - shrinkage con SHRINK_K_OUTLIER_FWD / MEDIA_RUOLO_FWD_PRIOR (5.0 / 53.02);
    - Stadio D molto piu' snello: la SOLA correzione "Passaggio" condizionata per
      venue (nessun condizionamento per forza avversario, che per FWD e' risultato
      rumore su tutte le sotto-categorie).
    Non serve opponent_rankings: per FWD non entra in nessun pezzo dello score.

    Tutti gli array sono lo STORICO (stessa lunghezza n, ordine cronologico);
    target_is_home e' la partita da predire. p_gioca=1.0 nel backtest.

    FIX (30/07, stesso bug reale di compute_score_atteso_def): opponent_lambda_mult
    mancava del tutto qui (mai applicato in backtest/calibrazione, sempre neutro),
    pur essendo gia' applicato in build_prediction dal 29/07. Se non passato
    esplicitamente, calcolato da next_opponent_team_slug quando disponibile;
    altrimenti 1.0 = nessun effetto (comportamento INVARIATO per vecchi chiamanti).
    Stessa cosa per offensive_values/fwd_offense_granular_delta (validato 29/07,
    checklist punto 19): assente qui, presente solo nell'inline di build_prediction --
    applicato ora solo se offensive_values e next_opponent_team_slug sono forniti."""
    if half_life is None:
        half_life = HALF_LIFE_GAMES
    if trend_intensity is None:
        trend_intensity = TREND_INTENSITY

    n = len(scores)
    weights = exponential_weights(n, half_life)
    # Pesi per tutto cio' che viene dal detailedScore: le partite senza
    # dettaglio pesano zero invece di entrare con level_score=0 (03/08, vedi
    # mask_weights).
    weights_det = mask_weights(weights, detail_ok_flags)

    media_granulari_pesata = weighted_mean(granulari_values, weights_det)
    if opponent_lambda_mult is None:
        if next_opponent_team_slug:
            opponent_lambda_mult = opponent_strength.opponent_lambda_multiplier(
                league, 'fwd', next_opponent_team_slug, next_game_date or datetime.datetime.utcnow())
        else:
            opponent_lambda_mult = 1.0
    lambda_pos_dec = weighted_mean(pos_decisive_values, weights_det) * opponent_lambda_mult
    lambda_neg_dec = weighted_mean(neg_decisive_values, weights_det)
    level_score_atteso = expected_level_from_rates(lambda_pos_dec, lambda_neg_dec)
    fattore_trend_granulare, _s, _l = compute_trend_factor(
        granulari_values, short_window=5, long_window=10, trend_intensity=trend_intensity,
        weights=weights_det)
    # Ricalibrato 30/07 (n=418, pool post-fix anyPlayers->activePlayers,
    # decisione utente via popup): era 47.44 + 6.62 * presence_rate.
    if presence_rate is not None:
        media_ruolo_prior = max(0.0, 47.44 + 6.62 * presence_rate)
    grezzo_nuovo = level_score_atteso + media_granulari_pesata * fattore_trend_granulare
    if offensive_values is not None and next_opponent_team_slug:
        _offensive_hist = weighted_mean(offensive_values, weights_det)
        grezzo_nuovo += opponent_strength.fwd_offense_granular_delta(
            league, next_opponent_team_slug, next_game_date or datetime.datetime.utcnow(), _offensive_hist)
    grezzo_nuovo_corretto = (
        (n / (n + shrink_k)) * grezzo_nuovo
        + (shrink_k / (n + shrink_k)) * media_ruolo_prior
    )
    fattore_casa_trasferta = compute_split_factor(residual_values, is_home_flags,
                                                  target_is_home, weights_det)
    # RIMOSSO p_gioca da score_atteso (28/07, richiesta esplicita utente): la
    # probabilita' di scendere in campo non deve deprimere il punteggio
    # proiettato di un giocatore -- score_atteso e' "quanto rende SE gioca",
    # non un valore atteso ponderato per l'incertezza sulla presenza (che va
    # gestita altrove, es. il filtro secco starterOdds/MIN_STARTER_ODDS a
    # monte, non come moltiplicatore continuo che penalizza chi ha uno
    # storico di assenze irrilevanti, es. amichevoli/nazionale).
    score_atteso = grezzo_nuovo_corretto * fattore_casa_trasferta

    # --- Stadio D (FWD): sola correzione "Passaggio" condizionata per venue ---
    if not use_stadio_d:
        return score_atteso
    fallback_passaggio = weighted_mean(passing_values, weights_det)
    media_passaggio_condizionata_venue = media_condizionata(
        passing_values, weights_det, is_home_flags, target_is_home, fallback_passaggio)
    score_atteso += (media_passaggio_condizionata_venue - fallback_passaggio)
    return score_atteso


def rigorous_backtest_prod_fwd(scores, is_home_flags,
                               residual_values, granulari_values,
                               pos_decisive_values, neg_decisive_values,
                               passing_values,
                               min_history=6, half_life=None, trend_intensity=None,
                               range_multiplier=1.0,
                               opponent_team_slugs_hist=None, league='francia2',
                               offensive_values=None,
                               game_dates_hist=None, presence_rate=None,
                               detail_ok_flags=None):
    """Backtest walk-forward ALLINEATO ALLA PRODUZIONE per FWD: ad ogni partita
    richiama compute_score_atteso_fwd() -- la STESSA funzione della predizione
    reale -- sul solo storico precedente. Stessa struttura di ritorno del vecchio
    rigorous_backtest, per restare compatibile con aggregate_grid_search.py.

    game_dates_hist/presence_rate (31/07, audit): senza la data non si puo'
    ancorare l'aggiustamento avversario alla partita giusta, e senza
    presence_rate lo shrinkage usa il prior FISSO invece di quello dinamico
    -- due divergenze residue dalla produzione anche in questa versione che
    si dichiarava "allineata"."""
    if half_life is None:
        half_life = HALF_LIFE_GAMES
    if trend_intensity is None:
        trend_intensity = TREND_INTENSITY

    rows = []
    n = len(scores)
    for i in range(min_history, n):
        predetto = compute_score_atteso_fwd(
            scores[:i], is_home_flags[:i], residual_values[:i], granulari_values[:i],
            pos_decisive_values[:i], neg_decisive_values[:i], passing_values[:i],
            target_is_home=is_home_flags[i], p_gioca=1.0,
            half_life=half_life, trend_intensity=trend_intensity,
            next_opponent_team_slug=opponent_team_slugs_hist[i] if opponent_team_slugs_hist else None,
            next_game_date=game_dates_hist[i] if game_dates_hist else None,
            presence_rate=presence_rate,
            league=league,
            offensive_values=offensive_values[:i] if offensive_values else None,
            detail_ok_flags=detail_ok_flags[:i] if detail_ok_flags else None)
        reale = scores[i]
        w = exponential_weights(i, half_life)
        dev_std = weighted_stddev(scores[:i], w, weighted_mean(scores[:i], w))
        range_conf = dev_std * range_multiplier
        dentro_range = abs(reale - predetto) <= range_conf if range_conf > 0 else None
        rows.append({'i': i, 'indice': i, 'partite_storico_usate': i,
                     'predetto': predetto, 'reale': reale,
                     'errore': reale - predetto, 'range_conf': range_conf,
                     'dentro_range': dentro_range})

    if not rows:
        return {'rows': [], 'mae': None, 'pct_dentro_range': None, 'n_test': 0}
    errori = [abs(r['errore']) for r in rows]
    mae = sum(errori) / len(errori)
    coperti = [r['dentro_range'] for r in rows if r['dentro_range'] is not None]
    pct = (sum(1 for c in coperti if c) / len(coperti) * 100.0) if coperti else None
    return {'rows': rows, 'mae': mae, 'pct_dentro_range': pct, 'n_test': len(rows)}


def _build_grid_combinations_prod():
    """Griglia per il grid search ALLINEATO. Include SEMPRE i valori reali di
    produzione (hl=25.0, ti=0.3, rm=1.15), altrimenti il vincitore non
    sarebbe confrontabile con cio' che gira davvero."""
    combos = []
    for hl in (6.0, 9.0, 12.0, 15.0, 20.0, 25.0, 30.0):
        for ti in (0.0, 0.2, 0.3, 0.7, 1.0, 1.3):
            for rm in (1.0, 1.1, 1.15, 1.2, 1.4):
                combos.append((hl, ti, rm, f"hl={hl}+trend_int={ti}+range={rm}x"))
    return combos


GRID_SEARCH_COMBINATIONS_PROD = _build_grid_combinations_prod()


def run_grid_search_prod_fwd(scores, is_home_flags,
                             residual_values, granulari_values,
                             pos_decisive_values, neg_decisive_values,
                             passing_values, min_history=6,
                             opponent_team_slugs_hist=None, game_dates_hist=None,
                             presence_rate=None, league='francia2',
                             offensive_values=None, detail_ok_flags=None):
    """Grid search ALLINEATO per FWD (31/07, audit): gira
    rigorous_backtest_prod_fwd -- che internamente chiama
    compute_score_atteso_fwd, la STESSA funzione della predizione reale --
    invece della vecchia run_grid_search, che usava la formula
    moltiplicativa senza level_score/shrinkage/opponent_lambda e col
    fattore ranking avversario rimosso dalla produzione il 26/07.
    Vedi il gemello run_grid_search_prod_gk in test_gk.py per il contesto
    completo della scoperta."""
    results = []
    for half_life, trend_intensity, range_mult, label in GRID_SEARCH_COMBINATIONS_PROD:
        bt = rigorous_backtest_prod_fwd(
            scores, is_home_flags, residual_values, granulari_values,
            pos_decisive_values, neg_decisive_values, passing_values,
            min_history=min_history, half_life=half_life,
            trend_intensity=trend_intensity, range_multiplier=range_mult,
            opponent_team_slugs_hist=opponent_team_slugs_hist,
            game_dates_hist=game_dates_hist,
            presence_rate=presence_rate, league=league,
            offensive_values=offensive_values,
            detail_ok_flags=detail_ok_flags)
        bt.update({'label': label, 'half_life': half_life,
                   'range_multiplier': range_mult, 'trend_intensity': trend_intensity,
                   'opponent_sensitivity': None})
        if bt['mae'] is not None:
            coverage_penalty = abs((bt['pct_dentro_range'] or 0) - 68.0) * 0.3
            bt['composite_score'] = bt['mae'] + coverage_penalty
        else:
            bt['composite_score'] = float('inf')
        results.append(bt)
    results.sort(key=lambda r: r['composite_score'])
    return results


def salva_grid_results(slug, result):
    """Scrive <slug>_grid.json per il job 'aggregate' separato.

    FUNZIONE UNICA (01/08): la chiamano sia il percorso normale sia quello di
    sola calibrazione (nessuna partita futura). Prima era un blocco inline;
    duplicarlo avrebbe significato due copie che possono divergere in
    silenzio, l'errore gia' visto altrove nel progetto."""
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
    return len(grid_export)



_CLUB_NOTI = None


def club_da_sorare(player_slug):
    """Club ATTUALE secondo Sorare (activeClub), persistito dalla discovery.
    La squadra dedotta dalle ultime partite sbaglia su chi si e' appena
    trasferito e non ha ancora esordito. None -> resta la deduzione."""
    global _CLUB_NOTI
    if _CLUB_NOTI is None:
        _CLUB_NOTI = {}
        path = os.path.join(os.path.dirname(DISCOVERY_FILE), 'player_card_counts.json')
        try:
            with open(path, encoding='utf-8') as f:
                for slug, voce in (json.load(f) or {}).items():
                    if isinstance(voce, dict) and voce.get('club'):
                        _CLUB_NOTI[slug] = voce['club']
        except Exception:
            pass
    return _CLUB_NOTI.get(player_slug)


def _prossima_partita_vera(future_games):
    """Fra le partite future, sceglie quella giusta quando una giornata sta per
    chiudersi mentre escono gia' le odds di quella successiva (10/08/2026,
    caso reale Matt Freese/GK, lo stesso principio vale per ogni ruolo: club
    con una partita di un'altra competizione ancora da giocare prima della
    vera giornata target -- lo script prendeva sempre future_games[0], cioe'
    la piu' vicina, sbagliando target).

    Regola (idea dell'utente): le starter odds di una partita successiva non
    escono MAI insieme a quelle della partita immediatamente precedente,
    tranne nella finestra in cui la precedente sta per concludersi. Quindi:
    se >=2 partite future hanno GIA' le odds pubblicate insieme, si schiera
    sempre sull'ULTIMA con odds, mai sulla prima. Altrimenti (il caso
    normale: solo la piu' vicina ha odds, o nessuna le ha ancora)
    comportamento INVARIATO -- resta la prima partita futura, stesso ordine
    di sempre. Non tocca nessun'altra logica: riordina solo la lista cosi'
    che future_games[0] sia gia' quella giusta ovunque venga letto.

    Ritorna (future_games_riordinata, ambiguo) -- 'ambiguo' e' True quando
    la scelta e' stata fatta su un caso limite: chi consuma la predizione
    (generatore, scouting) lo scrive come AVVISO non bloccante in HTML,
    perche' un caso mai visto prima potrebbe rompere l'euristica (10/08/2026,
    richiesta esplicita dell'utente: "sicurezza estrema")."""
    con_odds = []
    for n in future_games:
        odds = (((n.get('playerGameScore') or {}).get('anyPlayerGameStats') or {})
                .get('footballPlayingStatusOdds') or {})
        if odds.get('starterOddsBasisPoints') is not None:
            con_odds.append(n)
    if len(con_odds) >= 2 and con_odds[-1] is not future_games[0]:
        scelta = con_odds[-1]
        return [scelta] + [n for n in future_games if n is not scelta], True
    return future_games, False


def build_prediction(player_slug):
    global _STRUCTURAL_INSUFFICIENCY
    _STRUCTURAL_INSUFFICIENCY = False
    log("[FASE 1/4] Avvio recupero game log...")
    past_games, future_games, live_team_slug = fetch_game_log_incremental(player_slug, target_window_size=WINDOW_SIZE)
    future_games, _fixture_ambigua = _prossima_partita_vera(future_games)
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
        # Pre-carico in BATCH le FINAL che mancano (vedi
        # precarica_dettagli_batch): il ciclo sotto resta identico e le
        # trova gia' in cache. Se il batch fallisce, il ciclo le chiede una
        # per una esattamente come prima.
        precarica_dettagli_batch(usable, cache)
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
    # FIX (29/07, bug reale trovato dall'utente: Messi mostrava SQUADRA/
    # AVVERSARIO "N/D" e Griezmann risultava di colpo "Atletico Madrid"):
    # la finestra delle ultime 5 partite poteva essere dominata da
    # competizioni non-mlspa (global-cup, amichevoli, nazionale) che hanno
    # homeTeam/awayTeam VUOTI o riferiti a un contesto diverso (club in
    # prestito, nazionale) -- la maggioranza finiva su nessuna squadra o
    # sulla squadra SBAGLIATA. Ora si preferiscono le partite della STESSA
    # competizione della partita target (le uniche rappresentative della
    # squadra MLS attuale); si ripiega sulla finestra multi-competizione
    # SOLO se il giocatore non ha alcuna partita nella competizione target
    # nello storico (permissivo, mai un'esclusione).
    _same_comp_usable = ([n for n in usable
                           if (n['anyGame'].get('competition') or {}).get('slug') == target_competition]
                          if target_competition else [])
    _team_source = _same_comp_usable if _same_comp_usable else usable
    _recent_window = _team_source[-5:] if len(_team_source) >= 5 else _team_source
    team_counts = {}
    for node in _recent_window:
        g = node['anyGame']
        for side in ('homeTeam', 'awayTeam'):
            t = (g.get(side) or {}).get('slug')
            if t:
                team_counts[t] = team_counts.get(t, 0) + 1
    if team_counts:
        player_team_slug = max(team_counts, key=team_counts.get)
    _club_sorare = club_da_sorare(player_slug)
    if _club_sorare and _club_sorare != player_team_slug:
        log(f"[squadra] dedotta dalle partite: {player_team_slug} -> "
            f"corretta con activeClub Sorare: {_club_sorare}")
        player_team_slug = _club_sorare

    # Costruisce la serie di score utilizzabili + contesto casa/trasferta + ranking avversario
    scores = []
    is_home_flags = []
    opponent_rankings = []
    own_rankings = []
    opponent_team_slugs_hist = []  # NUOVO (31/07, audit): per il grid search allineato, vedi sotto
    game_dates_hist = []
    fouls_values = []
    duels_values = []
    offensive_values = []
    passing_values = []
    defense_rare_values = []
    residual_values = []  # NUOVO (FIX Finding 3, 25/07): punteggio totale meno tutti i gruppi granulari tracciati (vedi compute_split_factor/fattore_casa_trasferta piu' sotto)
    level_score_values = []  # NUOVO (26/07, Stadio A): "Punteggio decisivo" per partita
    granulari_values = []  # NUOVO (26/07, Stadio A): resto del punteggio (= score - level_score)
    pos_decisive_values = []  # NUOVO (27/07 notte): conteggio eventi POSITIVE_DECISIVE_STAT per partita
    neg_decisive_values = []  # NUOVO (27/07 notte): conteggio eventi NEGATIVE_DECISIVE_STAT per partita
    detail_ok_flags = []  # NUOVO (03/08): la partita ha davvero il detailedScore? Vedi mask_weights

    for node, detail in zip(usable, details):
        game_score = node.get('score', 0.0)
        scores.append(game_score)
        # Il dettaglio c'e' davvero? (03/08) Se manca, tutti i valori derivati
        # sotto sono segnaposto e la partita dovra' pesare zero -- vedi
        # mask_weights per il perche' trattarli come dati veri sovrastimava.
        detail_ok_flags.append(bool(detail and detail.get('detailedScore')))
        game = node['anyGame']
        own_rank, opp_rank, is_home = team_ranking_from_game(game, player_team_slug)
        # fallback: se il ranking non e' nel game log base, prova dal dettaglio granulare
        if opp_rank is None and detail:
            own_rank, opp_rank, is_home = team_ranking_from_game(detail['anyGame'], player_team_slug)
        is_home_flags.append(is_home)
        opponent_rankings.append(opp_rank)
        own_rankings.append(own_rank)
        # Slug/data dell'avversario per ogni partita storica (31/07, audit):
        # servono al grid search ALLINEATO (run_grid_search_prod_fwd), che
        # altrimenti non potrebbe applicare l'aggiustamento avversario e
        # resterebbe a misurare una formula diversa dalla produzione.
        # Stesso pattern gia' in uso in test_def.py dal 29/07.
        _g_home, _g_away = game.get('homeTeam') or {}, game.get('awayTeam') or {}
        if _g_home.get('slug') == player_team_slug:
            opponent_team_slugs_hist.append(_g_away.get('slug'))
        elif _g_away.get('slug') == player_team_slug:
            opponent_team_slugs_hist.append(_g_home.get('slug'))
        else:
            opponent_team_slugs_hist.append(None)
        game_dates_hist.append(_game_dt(node))

        fouls_v = extract_group_score(detail, FOULS_STATS)
        duels_v = extract_group_score(detail, DUELS_STATS)
        offensive_v = extract_group_score(detail, OFFENSIVE_STATS)
        passing_v = extract_group_score(detail, PASSING_STATS)
        defense_raw = extract_group_score(detail, DEFENSE_RARE_STATS)

        fouls_values.append(fouls_v)
        duels_values.append(duels_v)
        offensive_values.append(offensive_v)
        passing_values.append(passing_v)
        defense_rare_values.append(max(-DEFENSE_RARE_CAP, min(DEFENSE_RARE_CAP, defense_raw)))
        level_score_v = extract_level_score(detail)
        level_score_values.append(level_score_v)
        granulari_values.append(game_score - level_score_v)
        pos_dec_v, neg_dec_v = extract_decisive_rates(detail)
        pos_decisive_values.append(pos_dec_v)
        neg_decisive_values.append(neg_dec_v)

        # Residuo = tutto cio' che NON e' in nessun gruppo granulare tracciato
        # sopra (usiamo i valori REALI non cappati per i gruppi con cap, cosi'
        # il residuo resta coerente con il punteggio reale della partita).
        covered_total = fouls_v + duels_v + offensive_v + passing_v + defense_raw
        residual_values.append(game_score - covered_total)

    n = len(scores)
    weights = exponential_weights(n, HALF_LIFE_GAMES)
    # Pesi per le grandezze che vengono dal detailedScore (03/08, vedi
    # mask_weights). 'weights' resta quello pieno per punteggio/range, che dal
    # dettaglio non dipendono.
    weights_det = mask_weights(weights, detail_ok_flags)
    _n_senza_dettaglio = sum(1 for ok in detail_ok_flags if not ok)
    if _n_senza_dettaglio:
        log(f"[FASE 4/4] {_n_senza_dettaglio}/{n} partite senza detailedScore: "
            f"escluse (peso 0) da level_score/granulare/eventi decisivi, "
            f"restano nel punteggio e nel contesto casa/trasferta.")

    media_pesata = weighted_mean(scores, weights)
    dev_std_pesata = weighted_stddev(scores, weights, media_pesata)
    dev_std_trimmed = trimmed_weighted_stddev(scores, weights)

    # --- Shrinkage outlier/hot-streak (27/07, vedi SHRINK_K_OUTLIER_FWD sopra
    # per il backtest che lo giustifica): tira media_pesata verso il prior di
    # ruolo in proporzione inversa a n (partite storiche disponibili) --
    # riduce il peso di picchi isolati su giocatori a basso storico (n<8),
    # senza toccare la versione raw usata per range di confidenza/dev.std
    # (media_pesata resta invariata li' — lo shrinkage si applica SOLO al
    # pezzo che entra in score_atteso, stessa scelta della diagnostica).
    media_pesata_corretta = (
        (n / (n + SHRINK_K_OUTLIER_FWD)) * media_pesata
        + (SHRINK_K_OUTLIER_FWD / (n + SHRINK_K_OUTLIER_FWD)) * MEDIA_RUOLO_FWD_PRIOR
    )  # NOTA (27/07 notte): resta solo diagnostico -- score_atteso ora applica
    # lo STESSO shrinkage al grezzo level_score_atteso+granulare_atteso (vedi sotto),
    # non piu' a media_pesata direttamente.

    # --- Stadio A (26/07, tema level_score): media pesata separata per
    # level_score ("Punteggio decisivo") e resto ("Punteggio complessivo") --
    # solo diagnostico per ora, non entra ancora in score_atteso.
    media_level_score_pesata = weighted_mean(level_score_values, weights_det)
    media_granulari_pesata = weighted_mean(granulari_values, weights_det)

    # --- Stadio B (26/07, tema level_score): range di confidenza a
    # percentili pesati sullo storico REALE, in alternativa a media+deviazione
    # standard -- si adatta alla bimodalita' reale della distribuzione invece
    # di assumere una campana. Usato dallo Stadio C sotto per costruire il
    # range di confidenza finale.
    p16_score = weighted_percentile(scores, weights, 16)
    p84_score = weighted_percentile(scores, weights, 84)

    # --- Medie casa/trasferta (solo descrittive, per l'output) ---
    home_scores = [s for s, h in zip(scores, is_home_flags) if h is True]
    away_scores = [s for s, h in zip(scores, is_home_flags) if h is False]
    home_avg = sum(home_scores) / len(home_scores) if home_scores else media_pesata
    away_avg = sum(away_scores) / len(away_scores) if away_scores else media_pesata

    # --- Prossima partita: contesto target ---
    log("[FASE 4/4] Calcolo fattori e predizione finale sulla prossima partita target...")
    # CALIBRAZIONE FUORI STAGIONE (01/08): il grid search e' un backtest
    # sullo STORICO e non ha bisogno di una partita futura. Il controllo
    # qui sotto protegge la PREDIZIONE, che senza avversario non si puo'
    # calcolare; senza questo ramo, con i campionati fermi ogni giocatore
    # usciva a mani vuote pur avendo storico completo (run italia/gk del
    # 01/08: 34 job verdi, zero dati raccolti).
    if CALIBRATION_MODE and not future_games:
        presence_rate = len(usable) / total_considered if total_considered else 1.0
        log(f"CALIBRATION_MODE senza partita futura: grid search ALLINEATO "
            f"sullo storico ({len(GRID_SEARCH_COMBINATIONS_PROD)} combinazioni)...")
        grid_results = run_grid_search_prod_fwd(
            scores, is_home_flags, residual_values, granulari_values,
            pos_decisive_values, neg_decisive_values, passing_values,
            min_history=6,
            opponent_team_slugs_hist=opponent_team_slugs_hist,
            game_dates_hist=game_dates_hist,
            presence_rate=presence_rate, league='francia2',
            offensive_values=offensive_values,
            detail_ok_flags=detail_ok_flags)
        return {'solo_calibrazione': True, 'grid_results': grid_results}

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

    # FIX (Finding 3, 25/07): fattore casa/trasferta calcolato sul RESIDUO
    # (punteggio non coperto da nessun gruppo granulare), non piu' sul
    # punteggio totale -- evita di contare l'effetto venue una volta qui e
    # di nuovo dentro ogni fattore granulare sottostante.
    fattore_casa_trasferta = compute_split_factor(residual_values, is_home_flags,
                                                  next_is_home, weights_det)

    # --- Fattori granulari SEPARATI: falli, duelli, efficacia offensiva ---
    # Ognuno e' un fattore casa/trasferta indipendente, calcolato sui dati REALI
    # del detailedScore delle 14 partite (non stime). Gli eventi rari (rigori,
    # autogol, errori-a-gol) sono gia' stati cappati in fase di estrazione.
    fattore_falli = compute_split_factor(fouls_values, is_home_flags, next_is_home, weights_det)
    fattore_duelli = compute_split_factor(duels_values, is_home_flags, next_is_home, weights_det)
    fattore_offensivo = compute_split_factor(offensive_values, is_home_flags, next_is_home, weights_det)
    fattore_passaggio = compute_split_factor(passing_values, is_home_flags, next_is_home, weights_det)
    fattore_difesa_rari = compute_split_factor(defense_rare_values, is_home_flags, next_is_home, weights_det)

    # Ranking medio delle 14 partite (tra gli avversari con dato disponibile).
    # Resta per il fallback di Stadio D e per il log diagnostico. RIMOSSO
    # (P1, passaggio 2, B19): fattore_forza_avversario, calcolato da questo
    # ranking e mai usato in score_atteso (data-flow + test A/A
    # OPPONENT_SENSITIVITY=1e9 -> score_atteso invariato bit-per-bit).
    valid_opp_ranks = [r for r in opponent_rankings if r is not None]
    avg_opp_rank_hist = sum(valid_opp_ranks) / len(valid_opp_ranks) if valid_opp_ranks else None

    # --- P(gioca) ---
    p_gioca = None
    p_source = None
    next_odds = ((next_node.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
    starter_odds = next_odds.get('starterOddsBasisPoints')
    presence_rate = len(usable) / total_considered if total_considered else 1.0
    if starter_odds is not None:
        p_gioca = starter_odds / 10000.0
        p_source = f"starterOddsBasisPoints ({starter_odds})"
    else:
        p_gioca = presence_rate
        p_source = f"tasso di presenza storico ({len(usable)}/{total_considered})"

    # --- Fattore trend (ultime 5 vs ultime 10, stesso pool gia' filtrato) ---
    fattore_trend, trend_avg_short, trend_avg_long = compute_trend_factor(
        scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

    # FISSATO (26/07): granulari rimossi dallo score_atteso reale, come gia'
    # fatto per GK -- calibrazione allargata pesata per n_test (37 attaccanti,
    # min 3 partite di backtest) indica che senza granulari generalizza
    # leggermente meglio (MAE 17.33 vs 17.58 con). I fattori restano calcolati
    # sopra e nel result dict solo a scopo diagnostico/di visualizzazione
    # nell'output. Confermato dall'utente dopo confronto A/B su formazioni
    # reali.
    # RIMOSSO da score_atteso il 26/07 (terza sessione), DECISO CON L'UTENTE
    # dopo backtest walk-forward rigoroso (formazione_francia2/diagnostics/
    # validate_team_defense_strength.py): fattore_forza_avversario (ranking
    # di campionato) PEGGIORA il MAE reale -- rimuoverlo del tutto batte sia
    # il ranking attuale sia una metrica alternativa piu' specifica (gol
    # subiti storici dall'avversario, testata con grid search sul
    # coefficiente di sensibilita'): -9.26% rimuovendolo vs -5.91% con gol
    # subiti (miglior sensibilita' trovata). Stesso risultato di Stadio D:
    # con soli 10-15 partite di storico per giocatore, condizionare per
    # avversario (con QUALSIASI metrica) aggiunge piu' rumore che segnale.
    # Il fattore resta calcolato sopra e nel result dict solo a scopo
    # diagnostico/di visualizzazione nell'output.
    # --- level_score ATTESO da tasso di eventi (27/07 notte, sezione 22):
    # vedi test_def.py per la spiegazione estesa. Rivalidato su 6 campionati: -0.78% MAE.
    # Lo shrinkage outlier/hot-streak (SHRINK_K_OUTLIER_FWD, gia' in produzione
    # per FWD) si applica ora al grezzo (level_score_atteso + granulare_atteso)
    # invece che a media_pesata direttamente -- stesso principio (tirare verso
    # il prior di ruolo su storico corto), applicato al nuovo pezzo pre-venue.
    # opponent_lambda_mult (29/07, vedi opponent_strength.py): gol subiti dal
    # prossimo avversario nelle ultime 10 partite (dato storico reale, non
    # il domesticLeagueRanking contaminato). Validato: -0.58% MAE.
    _next_game_dt = None
    try:
        _next_game_dt = datetime.datetime.fromisoformat(
            (next_game.get('date') or '').replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, AttributeError):
        _next_game_dt = None
    _opp_cutoff = _next_game_dt or datetime.datetime.utcnow()
    _opp_lambda_mult = opponent_strength.opponent_lambda_multiplier(
        'francia2', 'fwd', next_opponent_team_slug, _opp_cutoff)
    lambda_pos_dec = weighted_mean(pos_decisive_values, weights_det) * _opp_lambda_mult
    lambda_neg_dec = weighted_mean(neg_decisive_values, weights_det)
    level_score_atteso = expected_level_from_rates(lambda_pos_dec, lambda_neg_dec)
    fattore_trend_granulare, _trend_gran_short, _trend_gran_long = compute_trend_factor(
        granulari_values, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY,
        weights=weights_det)
    _media_ruolo_prior_dinamico = max(0.0, 47.44 + 6.62 * presence_rate)
    # NUOVO (29/07, vedi opponent_strength.py, gruppo fwd_vs_def validato):
    # delta ADDITIVO sul granulare "offensivo" in base al poss_lost_ctrl medio
    # dei difensori avversari (ultime 10 partite) -- avversario che perde
    # palla spesso in fase difensiva espone di piu' l'attaccante. Validato
    # con backtest walk-forward: -0.38% MAE, minimo pulito a sensibilita'=3.0.
    _offensive_hist = weighted_mean(offensive_values, weights_det)
    _fwd_offense_delta = opponent_strength.fwd_offense_granular_delta(
        'mls', next_opponent_team_slug, _opp_cutoff, _offensive_hist)
    grezzo_nuovo = (level_score_atteso + media_granulari_pesata * fattore_trend_granulare
                    + _fwd_offense_delta)
    grezzo_nuovo_corretto = (
        (n / (n + SHRINK_K_OUTLIER_FWD)) * grezzo_nuovo
        + (SHRINK_K_OUTLIER_FWD / (n + SHRINK_K_OUTLIER_FWD)) * _media_ruolo_prior_dinamico
    )
    # RIMOSSO p_gioca da score_atteso (28/07, richiesta esplicita utente):
    # vedi commento esteso nella gemella compute_score_atteso_fwd sopra.
    score_atteso = grezzo_nuovo_corretto * fattore_casa_trasferta

    # --- SCORE DI ORDINAMENTO (28/07, sezione 27.C del RIASSUNTO, estesa a FWD
    # dopo misurazione dedicata): stesso principio gia' in produzione per DEF
    # -- lo shrinkage minimizza il MAE del singolo punteggio ma comprime le
    # differenze fra giocatori (il segnale che serve per SCEGLIERE chi
    # schierare), quindi distorce la classifica del consiglio. Misurato con
    # formazione_francia2/diagnostics/selection_quality.py (variante FWD, 74
    # giornate reali/15 campionati): shrink_k=5 (produzione) cattura il 19.9%
    # del lift caso->oracolo, shrink_k=0 il 22.8% (+0.48 pt/giornata) --
    # stessa direzione e ordine di grandezza del beneficio gia' confermato su
    # DEF. Stessa funzione condivisa, unico parametro cambiato: shrink_k=0.
    score_ordinamento = compute_score_atteso_fwd(
        scores, is_home_flags, residual_values, granulari_values,
        pos_decisive_values, neg_decisive_values, passing_values,
        target_is_home=next_is_home, p_gioca=p_gioca, shrink_k=0.0,
        next_opponent_team_slug=next_opponent_team_slug, next_game_date=_opp_cutoff,
        league='francia2', offensive_values=offensive_values,
        detail_ok_flags=detail_ok_flags)

    # --- Stadio D, approfondimento (26/07, notte, DECISO CON L'UTENTE mentre
    # dormiva -- "testare level_score/granulare piu' a fondo per tutti i
    # ruoli"): la versione precedente condizionava il granulare AGGREGATO
    # per venue (z=+2.68, l'unico segnale solido per FWD). Scomponendolo
    # nelle sue sotto-categorie, il segnale e' concentrato (e piu' forte)
    # nella sola "Passaggio" (z=+3.39, casa 5.05 vs trasferta 4.17) --
    # Duelli/Falli/Efficacia offensiva/Difesa rarissimi restano sotto
    # soglia, non condizionati. Nessun segnale per avversario su nessuna
    # sotto-categoria (tutti |z|<2, rumore su questo campione). SOSTITUISCE
    # (non si somma a) la conditioning sull'aggregato del commit precedente.
    # Correzione ADDITIVA (non moltiplicativa, per non toccare/ricalibrare
    # fattore_casa_trasferta gia' validato sul MAE), stessa logica di
    # shrinkage delle altre correzioni Stadio D.
    media_passaggio_condizionata_venue = media_condizionata(
        passing_values, weights_det, is_home_flags, next_is_home,
        weighted_mean(passing_values, weights_det))
    delta_passaggio_venue = media_passaggio_condizionata_venue - weighted_mean(passing_values, weights_det)
    score_atteso += delta_passaggio_venue

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

    # --- Backtest RIGOROSO sui parametri FISSATI (25/07) ---
    # Il grid search cross-player ha gia' individuato la combinazione vincente
    # (vedi costanti HALF_LIFE_GAMES/RANGE_MULTIPLIER/OPPONENT_SENSITIVITY/
    # TREND_INTENSITY sopra). Non serve piu' rieseguire 72 combinazioni ad ogni
    # giocatore ad ogni run — un solo backtest sui parametri fissati, molto
    # piu' veloce, mantenendo comunque MAE/copertura come indicatore di
    # affidabilita' per QUESTO specifico giocatore.
    if CALIBRATION_MODE:
        # ALLINEATO (31/07, audit): prima girava run_grid_search, cioe' la
        # vecchia formula moltiplicativa -- si calibrava un modello diverso
        # da quello che schiera. Vedi run_grid_search_prod_fwd sopra.
        log(f"CALIBRATION_MODE attivo: grid search ALLINEATO "
            f"({len(GRID_SEARCH_COMBINATIONS_PROD)} combinazioni)...")
        grid_results = run_grid_search_prod_fwd(
            scores, is_home_flags, residual_values, granulari_values,
            pos_decisive_values, neg_decisive_values, passing_values,
            min_history=6,
            opponent_team_slugs_hist=opponent_team_slugs_hist,
            game_dates_hist=game_dates_hist,
            presence_rate=presence_rate, league='francia2',
            offensive_values=offensive_values,
            detail_ok_flags=detail_ok_flags)
        rigorous_bt = grid_results[0] if grid_results else None
    else:
        log("Esecuzione backtest rigoroso sui parametri fissati...")
        rigorous_bt = rigorous_backtest(scores, is_home_flags, opponent_rankings, min_history=6,
                                         half_life=HALF_LIFE_GAMES, range_multiplier=RANGE_MULTIPLIER,
                                         opponent_sensitivity=OPPONENT_SENSITIVITY,
                                         fouls_values=fouls_values, duels_values=duels_values,
                                         offensive_values=offensive_values,
                                         passing_values=passing_values,
                                         defense_rare_values=defense_rare_values,
                                         residual_values=residual_values,
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
        'player_team_slug': current_team_slug,
        'window_size_used': n,
        'total_considered': total_considered,
        'dnp_excluded': dnp_count,
        'low_minutes_excluded': low_minutes_count,
        'target_competition': target_competition,
        'scores_used': scores,
        'weights_used': weights,
        'media_pesata': media_pesata,
        'media_pesata_corretta': media_pesata_corretta,
        'dev_std_pesata': dev_std_pesata,
        'dev_std_trimmed': dev_std_trimmed,
        'media_level_score_pesata': media_level_score_pesata,
        'level_score_atteso': level_score_atteso,
        'fattore_trend_granulare': fattore_trend_granulare,
        'grezzo_nuovo_corretto': grezzo_nuovo_corretto,
        'media_granulari_pesata': media_granulari_pesata,
        'media_passaggio_condizionata_venue': media_passaggio_condizionata_venue,
        'delta_passaggio_venue': delta_passaggio_venue,
        'p16_score': p16_score,
        'p84_score': p84_score,
        'home_avg': home_avg,
        'away_avg': away_avg,
        'fattore_casa_trasferta': fattore_casa_trasferta,
        'avg_opp_rank_hist': avg_opp_rank_hist,
        'next_opp_rank': next_opp_rank,
        'next_opponent_team_slug': next_opponent_team_slug,
        'next_own_rank': next_own_rank,
        'next_is_home': next_is_home,
        'opp_lambda_mult': _opp_lambda_mult,
        'fwd_offense_delta': _fwd_offense_delta,
        'fattore_falli': fattore_falli,
        'fattore_duelli': fattore_duelli,
        'fattore_offensivo': fattore_offensivo,
        'fattore_passaggio': fattore_passaggio,
        'fattore_difesa_rari': fattore_difesa_rari,
        'fattore_trend': fattore_trend,
        'trend_avg_short': trend_avg_short,
        'trend_avg_long': trend_avg_long,
        'p_gioca': p_gioca,
        'p_source': p_source,
        'score_atteso': score_atteso,
        'score_ordinamento': score_ordinamento,
        'range_low': range_low,
        'range_high': range_high,
        'next_game': next_game,
        'fixture_ambigua': _fixture_ambigua,
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
    lines.append(f"  Corretta per shrinkage outlier/hot-streak (k={SHRINK_K_OUTLIER_FWD}, prior ruolo "
                 f"{MEDIA_RUOLO_FWD_PRIOR}, n={result['window_size_used']}): "
                 f"{result['media_pesata_corretta']:.2f} (usata in score_atteso, vedi SHRINK_K_OUTLIER_FWD)")
    lines.append(f"  di cui Punteggio decisivo (level_score) medio: {result['media_level_score_pesata']:.2f} "
                 f"| Punteggio complessivo (granulari) medio: {result['media_granulari_pesata']:.2f} "
                 f"(Stadio A: questa componente E' APPLICATA a score_atteso, moltiplicata per il fattore trend granulare -- vedi compute_score_atteso_*)")
    lines.append(f"  Passaggio condizionato per venue: {result['media_passaggio_condizionata_venue']:.2f} "
                 f"(delta {result['delta_passaggio_venue']:+.2f}) "
                 f"(Stadio D approfondimento -- APPLICATO a score_atteso, scalato per P(gioca); level_score, "
                 f"forza avversario e le altre sotto-categorie granulari NON condizionati, nessun segnale "
                 f"abbastanza solido per FWD)")
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
    # AVV_FACTOR (03/08, fix output ingannevole): questa riga e' quella che
    # build_consiglio.py porta fino al report come 'AVV_FACTOR', cioe' l'unico
    # numero sull'avversario che arriva sotto gli occhi. Mostra il
    # moltiplicatore davvero in uso (opponent_lambda_multiplier sui gol
    # subiti reali dall'avversario) e il delta additivo sul granulare
    # offensivo. RIMOSSO P1/B19 il vecchio fattore_forza_avversario su
    # domesticLeagueRanking, mai applicato.
    lines.append(f"Fattore forza avversario applicato: {result['opp_lambda_mult']:.3f} "
                 f"(gol subiti reali dell'avversario, ultime 10; delta granulare "
                 f"offensivo {result['fwd_offense_delta']:+.2f} pt)")
    lines.append(f"Fattore falli (casa/trasferta, da dati reali): {result['fattore_falli']:.3f}")
    lines.append(f"Fattore duelli (casa/trasferta, da dati reali): {result['fattore_duelli']:.3f}")
    lines.append(f"Fattore efficacia offensiva (casa/trasferta, da dati reali): {result['fattore_offensivo']:.3f}")
    lines.append(f"Fattore passaggio (accurate_pass/final_third/att_assist): {result['fattore_passaggio']:.3f}")
    lines.append(f"Fattore difesa/eventi rarissimi (double-double, tackle, ecc., con cap): {result['fattore_difesa_rari']:.3f}")
    if result['trend_avg_short'] is not None:
        lines.append(f"Fattore trend (media ultime 5: {result['trend_avg_short']:.1f} vs "
                     f"media 5 PRECEDENTI: {result['trend_avg_long']:.1f}): {result['fattore_trend']:.3f}")
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
    if result.get('fixture_ambigua'):
        lines.append("ATTENZIONE FIXTURE AMBIGUA: due partite future avevano GIA' le "
                     "starter odds pubblicate insieme -- scelta quella piu' tardiva "
                     "(caso limite mai visto prima del 10/08/2026, verificare a mano).")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PREDIZIONE")
    lines.append("=" * 70)
    lines.append(f"Score atteso: {result['score_atteso']:.1f} "
                 f"(range {result['range_low']:.1f} - {result['range_high']:.1f}, "
                 f"Stadio C: percentili pesati ri-centrati sull'avversario/trend)")
    if result.get('score_ordinamento') is not None:
        lines.append(f"Score di ordinamento (senza shrinkage, usato SOLO per la "
                     f"DIAGNOSTICO, non usato per la classifica: il generatore ordina per 'sort_score'/'atteso' dal revert del 30/07): {result['score_ordinamento']:.1f}")

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

    log("Avvio test TUTTI attaccanti MLS in_season Tool_formazione...")
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

        # Sola calibrazione (01/08): il giocatore ha storico ma nessuna partita
        # futura (fuori stagione). C'e' un grid search da salvare e nessuna
        # predizione da mettere a report.
        if result.get('solo_calibrazione'):
            n_comb = salva_grid_results(slug, result)
            log(f"[{slug}] SOLO CALIBRAZIONE: {n_comb} combinazioni salvate "
                f"(nessuna partita futura, grid search fatto sullo storico).")
            summary_rows.append((slug, 'SOLO CALIBRAZIONE', None, None,
                                 'nessuna partita futura'))
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
        log_live_prediction(OUTPUT_DIR, CALIBRATION_MODE, 'fwd', result)

        all_sections.append(f"\n{'#'*70}\n# GIOCATORE: {slug}\n{'#'*70}\n" + output_text)
        summary_rows.append((slug, 'OK', result.get('score_atteso'), result.get('range_low'),
                              result.get('range_high'), result.get('target_competition', ''),
                              result.get('player_team_slug'), result.get('next_opponent_team_slug'),
                              result.get('score_ordinamento'), result.get('fixture_ambigua', False)))
        log(f"[{slug}] OK: score atteso {result.get('score_atteso'):.1f} "
            f"(range {result.get('range_low'):.1f} - {result.get('range_high'):.1f})")

        # Salvataggio grid_results per QUESTO giocatore, su disco, per il job
        # 'aggregate' separato che calcolera' la combinazione vincente cross-player
        # (stessa strategia usata per gli altri ruoli).
        salva_grid_results(slug, result)

    # --- Riepilogo comparativo in cima al file ---
    # NUOVO (25/07): tiering ordinato per score atteso decrescente, con
    # "projected score" in formato compatto (arrotondato + range) invece del
    # semplice atteso/range separati — numero secco e leggibile a colpo
    # d'occhio, come richiesto dall'utente.
    ok_rows = [r for r in summary_rows if r[1] == 'OK']
    other_rows = [r for r in summary_rows if r[1] != 'OK']
    # ORDINAMENTO (28/07, sezione 27.C, estesa da DEF a FWD dopo misurazione
    # dedicata -- vedi commento su score_ordinamento in compute_score_atteso_fwd):
    # si ordina per score_ordinamento (senza shrinkage), non per score_atteso.
    # Il numero MOSTRATO resta score_atteso. Fallback su score_atteso se assente
    # (file generati prima di questo fix).
    ok_rows.sort(key=lambda r: (r[8] if len(r) > 8 and r[8] is not None
                                else (r[2] if r[2] is not None else -1)), reverse=True)

    summary_lines = []
    summary_lines.append("=" * 70)
    summary_lines.append("CONSIGLIO ATTACCANTI — ordinato per score di ordinamento (senza shrinkage; il generatore poi riordina per punteggio calibrato)")
    summary_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    summary_lines.append(f"Parametri fissi per tutti: half_life={HALF_LIFE_GAMES}, "
                         f"range_mult={RANGE_MULTIPLIER}, min_starter_odds={MIN_STARTER_ODDS:.0%}")
    summary_lines.append("=" * 70)
    for idx, (slug, status, atteso, range_low, range_high, note, team_slug, opp_slug,
              ordinamento, fixture_ambigua) in enumerate(ok_rows, 1):
        low = round(range_low)
        high = round(range_high)
        summary_lines.append(f"{idx}) {slug}: {round(atteso)} pt attesi ({low}-{high})")
        # NUOVO (27/07, sezione 27.C): score usato per ORDINARE (senza
        # shrinkage), distinto dai "pt attesi" mostrati sopra. Riga parseable
        # letta da build_consiglio.py; se manca, a valle si ordina sui
        # pt attesi come prima.
        if ordinamento is not None:
            summary_lines.append(f"   ORDINAMENTO: {ordinamento:.2f}")
        # NUOVO (26/07, tema correlazione GK-DEF): riga parseable con squadra/
        # avversario, letta da build_consiglio.py per portarla fino a
        # build_formazione_finale.py (evitare di schierare insieme portiere
        # e giocatore di movimento le cui squadre si affrontano).
        summary_lines.append(f"   SQUADRA: {team_slug or 'N/D'} | AVVERSARIO: {opp_slug or 'N/D'}")
        if fixture_ambigua:
            summary_lines.append("   AMBIGUO_FIXTURE: si")
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
    # Pulizia automatica (30/07, richiesta esplicita utente): tiene solo l'ultimo
    # prediction_*.txt per slug/OUTPUT_DIR -- build_consiglio_* legge solo il piu'
    # recente, i precedenti erano peso morto (37k file/166MB nel repo, mai riletti).
    _pred_prefix = f'prediction_{file_suffix}_'
    for _pred_fn in os.listdir(OUTPUT_DIR):
        if (_pred_fn.startswith(_pred_prefix) and _pred_fn.endswith('.txt')
                and _pred_fn != os.path.basename(out_path)):
            try:
                os.remove(os.path.join(OUTPUT_DIR, _pred_fn))
            except OSError:
                pass

    log(f"\nOutput completo scritto in: {out_path}")
    log(f"Dump diagnostici di tutte le chiamate GraphQL salvati in: {DEBUG_DIR}/")
    print("\n" + "\n".join(summary_lines))
    print(f"\n[Dettaglio completo di ogni giocatore salvato nel file: {out_path}]")


if __name__ == '__main__':
    main()
