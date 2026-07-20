import json
import os
import time
import datetime
import threading

import requests
import websocket  # pip install websocket-client
from playwright.sync_api import sync_playwright

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# =====================================================================================
# MAKEOFFER SORARE -- BOT OFFERTE AUTOMATICHE (gemello di autobuy_sorare.py)
# =====================================================================================
# Stessa identica logica di RICERCA di autobuy_sorare.py (stessi filtri: prezzo,
# CHECK_CLASSIC, MLS/K-League esclusi da in_season, liquidita' minima, blacklist
# giocatori/manager DEDICATE a questo bot) -- ma invece di ACCETTARE l'offerta esistente
# al prezzo minimo trovato, CREA un'offerta diretta al venditore ad un prezzo
# ULTERIORMENTE scontato (OFFER_DISCOUNT_FRACTION) rispetto al minimo, con durata
# configurabile (OFFER_DURATION_DAYS, 1-7 giorni).
#
# MAKEOFFER_LIVE_MODE (default "no"): se "si", il bot invia DAVVERO l'offerta (stesso
# principio fail-safe di autobuy_sorare.py -- qualunque errore ferma solo quel
# tentativo, mai retry). Riusa lo stesso script sorare-sign/decrypt_and_sign.js.
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    """FIX 20/07 (scoperta dal debug di autobuy_sorare.py): il CSRF token di Sorare
    cambia ad OGNI refresh della pagina, per design -- un valore statico in SORARE_CSRF
    diventa obsoleto quasi subito e causa 401 'You should log in'. Il cookie stesso
    contiene un campo 'csrftoken=...' che coincide esattamente con l'header
    x-csrf-token mandato nella stessa richiesta -- lo estraiamo da li' ogni volta che
    il cookie viene aggiornato, invece di tenere un secret CSRF separato che scade
    subito. Fallback su SORARE_CSRF se il cookie non lo contiene."""
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
# FIX 20/07: header device_fingerprint visto in una richiesta reale del browser --
# diverso dal fingerprint restituito da prepareOffer/prepareAcceptOffer (quello e'
# fisso/di operazione, questo e' di device/sessione).
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# --- FASE 2 (automazione completa, 19/07) ---
# Interruttore attivato via input workflow MAKEOFFER_LIVE_MODE (env var, default "no" ->
# fase 1, solo diagnostica come sempre). Se valorizzato a "si", il bot COMPRA DAVVERO
# quando trova un caso valido: firma la mutation con la password del wallet (secret
# SORARE_WALLET_PASSWORD) e chiama AcceptOfferMutation. Fail-safe assoluto in ogni punto
# del flusso: qualunque errore (prenotazione, chiave cifrata, firma, accept) ferma SOLO
# quel tentativo, notifica l'errore esatto, non fa mai retry ne' tentativi alternativi.
MAKEOFFER_LIVE_MODE = os.environ.get('MAKEOFFER_LIVE_MODE', 'no').strip().lower() in ('1', 'true', 'yes', 'si')
SORARE_WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessa blacklist manager di track.py (venditori solo ETH o esplicitamente esclusi
# dall'utente) -- non ha senso valutare/comprare da questi annunci.
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}

# Giocatori da IGNORARE completamente in questo bot (workaround manuale al posto del
# controllo coverageStatus, che non e' utilizzabile via GraphQL -- vedi note progetto).
# Lista letta da un file DEDICATO a questo bot (sorare_makeoffer_blacklist.txt, nella root
# del repo, un player_slug per riga, righe vuote o che iniziano con '#' ignorate) --
# scelto cosi' (invece che hardcoded nel .py) per poterla vedere/editare direttamente su
# GitHub, senza dover lanciare il workflow ne' modificare il codice Python. File separato
# da qualunque blacklist usata da track.py/crafted_card_scanner.py: tocca SOLO questo
# bot. L'utente aggiunge una riga con lo slug del giocatore preso dall'URL della pagina
# giocatore, es. https://sorare.com/it/football/players/aoto-nanamure -> riga
# 'aoto-nanamure'. Qualsiasi evento su un giocatore in questa lista viene scartato PRIMA
# di qualunque altro controllo (prezzo, margine, ecc.), quindi non genera mai una
# notifica ne' una prenotazione. Resta anche configurabile via env var
# BLACKLISTED_PLAYER_SLUGS (slug separati da virgola, utile per un'aggiunta rapida da
# workflow senza toccare il file), che si SOMMA al contenuto del file senza sostituirlo.
def _load_slug_list_file(file_path, label):
    """Legge file_path riga per riga (un slug per riga, righe vuote o che iniziano con
    '#' ignorate). File mancante o illeggibile -> set vuoto (fail-safe: un file
    assente/corrotto non deve bloccare l'esecuzione del bot). Funzione generica, usata
    sia per la blacklist giocatori sia per quella manager."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return set()
    except Exception as e:
        log(f"[{label}] errore lettura {file_path}, ignorato: {e}")
        return set()
    slugs = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        slugs.add(line.lower())
    return slugs


BLACKLIST_FILE_PATH = os.environ.get('BLACKLIST_FILE_PATH', 'sorare_makeoffer_blacklist.txt')
BLACKLISTED_PLAYER_SLUGS = _load_slug_list_file(BLACKLIST_FILE_PATH, 'blacklist giocatori')
_extra_blacklisted_players = os.environ.get('BLACKLISTED_PLAYER_SLUGS', '')
if _extra_blacklisted_players.strip():
    BLACKLISTED_PLAYER_SLUGS |= {
        s.strip().lower() for s in _extra_blacklisted_players.split(',') if s.strip()
    }

# Manager da NON ACQUISTARE MAI in questo bot (richiesta esplicita utente, 19/07:
# "voglio poter blacklistare in generale gli annunci di alcuni manager, valido solo e
# soltanto per questo bot" -- poi precisato: "nel calcolo del margine devono contare, se
# l'affare e' una loro carta in vendita deve ignorarla"). Stesso comportamento della
# blacklist storica BLACKLISTED_SELLER_SLUGS: i loro annunci CONTANO nel calcolo del vero
# minimo/secondo prezzo (get_bucket_prices non li filtra), ma se il vero minimo risulta
# essere un loro annuncio, il caso viene scartato invece di essere acquistato (vedi
# controllo su true_min_seller_slug in evaluate_event). Stesso pattern della blacklist
# giocatori ma su un file SEPARATO (sorare_makeoffer_manager_blacklist.txt, nella root del
# repo, un manager_slug per riga) -- non lo stesso file dei giocatori, per tenere le due
# liste distinte e leggibili. Non tocca in alcun modo BLACKLISTED_SELLER_SLUGS (quella
# hardcoded, storica, condivisa con track.py) ne' track.py/crafted_card_scanner.py: file
# e lista completamente separati, validi SOLO per autobuy_sorare.py. Configurabile anche
# via env var BLACKLISTED_MANAGER_SLUGS (slug separati da virgola, per un'aggiunta rapida
# da workflow), che si SOMMA al contenuto del file senza sostituirlo -- e viene anche
# scritta/committata sul file per restare attiva nelle run future (stesso meccanismo gia'
# usato per blacklisted_player_slugs, vedi step dedicato in autobuy.yml).
MANAGER_BLACKLIST_FILE_PATH = os.environ.get(
    'MANAGER_BLACKLIST_FILE_PATH', 'sorare_makeoffer_manager_blacklist.txt')
BLACKLISTED_MAKEOFFER_MANAGER_SLUGS = _load_slug_list_file(
    MANAGER_BLACKLIST_FILE_PATH, 'blacklist manager')
_extra_blacklisted_managers = os.environ.get('BLACKLISTED_MANAGER_SLUGS', '')
if _extra_blacklisted_managers.strip():
    BLACKLISTED_MAKEOFFER_MANAGER_SLUGS |= {
        s.strip().lower() for s in _extra_blacklisted_managers.split(',') if s.strip()
    }

# --- Parametri regolabili (fase di test, vedi autobuy.yml per gli input del workflow) ---
# Fascia di prezzo dell'ANNUNCIO che scatena la valutazione: default 1-5EUR, ma regolabile
# fino a un tetto piu' alto (es. 20EUR) durante i test.
MAKEOFFER_MIN_PRICE_EUR = float(os.environ.get('MAKEOFFER_MIN_PRICE_EUR', '1'))
MAKEOFFER_MAX_PRICE_EUR = float(os.environ.get('MAKEOFFER_MAX_PRICE_EUR', '30'))

# Margine minimo richiesto tra il prezzo minimo attuale e il secondo prezzo minimo attuale
# (stesso bucket in_season), es. 0.15 = 15%.
MAKEOFFER_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MARGIN_FRACTION', '0.20'))

# Per quanti secondi restare in ascolto ad ogni esecuzione, se non si verifica prima un caso
# valido (il bot si ferma comunque al primo caso trovato).
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '3000'))
LISTEN_SECONDS = min(3600, LISTEN_SECONDS)  # tetto massimo 1h, indipendentemente dall'input

# FIX 19/07 (richiesta esplicita utente): per QUESTI 2 campionati il confronto in_season
# resta quello attuale (SOLO in_season, nessun classic unito) -- per tutti gli altri
# campionati (J League inclusa, tolta dall'esclusione su decisione dell'utente) il classic
# viene invece trattato come "un ulteriore in_season" nel calcolo del vero minimo/secondo
# prezzo. Slug confermati dal vivo tramite diagnostica [diagnostica lega]: MLS='mlspa',
# K League='k-league-1'.
EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1'}

# Quanti casi "lo avrei acquistato" notificare prima di fermarsi definitivamente (1-10).
# Utile per la fase di test manuale: si lascia girare finche' non arrivano N notifiche,
# senza dover riavviare il workflow a mano ogni volta.
MAKEOFFER_TARGET_MATCHES = int(os.environ.get('MAKEOFFER_TARGET_MATCHES', '5'))
MAKEOFFER_TARGET_MATCHES = max(1, min(10, MAKEOFFER_TARGET_MATCHES))

# Diagnostica: se attiva, logga info aggiuntive sul confronto in_season/classic per ogni
# giocatore valutato (lega rilevata, quanti annunci classic trovati, ecc.) -- utile solo
# per verificare che la nuova logica scatti davvero come previsto, di default spenta.
MAKEOFFER_DIAGNOSTIC = os.environ.get('MAKEOFFER_DIAGNOSTIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')

# Modalita' aggiuntiva (richiesta esplicita utente, 19/07): se attiva, il bot valuta
# ANCHE gli annunci CLASSIC (non solo in_season come nella modalita' base), per TUTTI i
# campionati senza eccezioni (a differenza della logica in_season, qui MLS/K League non
# sono esclusi -- e' un controllo separato e piu' semplice). Per un annuncio classic, il
# confronto e' contro il minimo ASSOLUTO tra classic+in_season uniti (un unico mercato,
# stesso criterio gia' usato per in_season quando la lega non e' esclusa) -- se
# l'annuncio classic risulta il minimo assoluto con margine sufficiente sul secondo,
# notifica. Di default spenta per non cambiare il comportamento esistente durante i test
# in corso.
CHECK_CLASSIC = os.environ.get('CHECK_CLASSIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')

# --- Protezione "no ri-acquisto stesso giocatore entro 24h" (per fase 2, automazione
# completa) ---
# Motivazione (richiesta esplicita utente, 19/07): se un giocatore si infortuna e il
# mercato viene inondato di annunci in svendita dello stesso giocatore, senza questa
# protezione il bot potrebbe comprare piu' carte dello stesso giocatore di fila -- non
# desiderato. Il registro e' persistito su file JSON (non solo in memoria) perche' ogni
# esecuzione del workflow GitHub Actions parte da zero: senza un file, la protezione
# varrebbe solo all'interno della singola run e non tra run diverse a distanza di ore.
# Il file va committato/aggiornato nel repo (vedi step dedicato in autobuy.yml) perche'
# la protezione funzioni davvero tra esecuzioni successive.
OFFER_LOG_PATH = os.environ.get('OFFER_LOG_PATH', 'makeoffer_cooldown.json')
PLAYER_OFFER_COOLDOWN_HOURS = 24


def _load_offer_log():
    """Ritorna {player_slug: iso_timestamp_ultimo_acquisto}. File mancante o corrotto ->
    dizionario vuoto (fail-safe: non blocchiamo mai gli acquisti solo perche' il file di
    log non si legge)."""
    try:
        with open(OFFER_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"[purchase log] errore lettura {OFFER_LOG_PATH}, ignorato: {e}")
        return {}


def _save_offer_log(log_data):
    try:
        with open(OFFER_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"[purchase log] errore scrittura {OFFER_LOG_PATH}: {e}")


def is_player_in_offer_cooldown(player_slug):
    """True se player_slug e' stato acquistato meno di PLAYER_OFFER_COOLDOWN_HOURS fa."""
    purchase_log = _load_offer_log()
    last_purchase_iso = purchase_log.get(player_slug)
    if not last_purchase_iso:
        return False
    try:
        last_purchase = datetime.datetime.fromisoformat(last_purchase_iso)
    except ValueError:
        return False
    elapsed_hours = (datetime.datetime.now(datetime.timezone.utc) - last_purchase).total_seconds() / 3600
    return elapsed_hours < PLAYER_OFFER_COOLDOWN_HOURS


def record_player_offer(player_slug):
    """Da chiamare SOLO dopo un acquisto REALMENTE completato (fase 2, non ancora attiva
    in questo script -- funzione pronta per quando si collega l'automazione completa)."""
    purchase_log = _load_offer_log()
    purchase_log[player_slug] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_offer_log(purchase_log)
    log(f"[purchase log] registrato acquisto di {player_slug}, cooldown {PLAYER_OFFER_COOLDOWN_HOURS}h")


# --- Cache "mercato troppo sottile" (richiesta esplicita utente, 19/07) ---
# Ottimizzazione velocita': se un giocatore e' gia' stato scartato dal controllo
# liquidita' (count_recent_transactions, vedi piu' sotto), rifare la stessa query
# GraphQL ogni volta che ricompare e' inutile -- il numero di transazioni recenti non
# cambia abbastanza in fretta da giustificare una riverifica immediata. Cache separata dal
# purchase log (scopo diverso: qui non e' un acquisto, e' solo un giocatore da ri-provare
# piu' avanti), persistita su file JSON per lo stesso motivo del purchase log (il
# workflow riparte da zero ad ogni esecuzione). Se la finestra scade, il giocatore torna
# ad essere valutato normalmente (nuova query, nuovo esito possibile).
THIN_MARKET_CACHE_PATH = os.environ.get('THIN_MARKET_CACHE_PATH', 'makeoffer_thin_market_cache.json')
THIN_MARKET_SKIP_DAYS = int(os.environ.get('THIN_MARKET_SKIP_DAYS', '3'))


def _load_thin_market_cache():
    """Ritorna {player_slug: iso_timestamp_ultimo_scarto}. File mancante o corrotto ->
    dizionario vuoto (fail-safe: un file assente/corrotto non deve mai bloccare una
    valutazione, al massimo si rifa' la query GraphQL di troppo)."""
    try:
        with open(THIN_MARKET_CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"[liquidita' cache] errore lettura {THIN_MARKET_CACHE_PATH}, ignorato: {e}")
        return {}


def _save_thin_market_cache(cache_data):
    try:
        with open(THIN_MARKET_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"[liquidita' cache] errore scrittura {THIN_MARKET_CACHE_PATH}: {e}")


def is_player_in_thin_market_cache(player_slug):
    """True se player_slug e' stato scartato per mercato troppo sottile negli ultimi
    THIN_MARKET_SKIP_DAYS giorni -- in tal caso saltiamo del tutto count_recent_
    transactions (nessuna query GraphQL), velocizzando l'analisi sui casi ripetuti."""
    cache = _load_thin_market_cache()
    last_skip_iso = cache.get(player_slug)
    if not last_skip_iso:
        return False
    try:
        last_skip = datetime.datetime.fromisoformat(last_skip_iso)
    except ValueError:
        return False
    elapsed_days = (datetime.datetime.now(datetime.timezone.utc) - last_skip).total_seconds() / 86400
    return elapsed_days < THIN_MARKET_SKIP_DAYS


def record_thin_market_skip(player_slug):
    """Registra che player_slug e' stato scartato per mercato troppo sottile ORA, cosi'
    i prossimi eventi su di lui (entro THIN_MARKET_SKIP_DAYS giorni) saltano subito senza
    rifare la query GraphQL."""
    cache = _load_thin_market_cache()
    cache[player_slug] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_thin_market_cache(cache)

_FIAT_RATE_CACHE = {}


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def get_usd_eur_rate():
    if 'usd' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['usd']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 0.92
    _FIAT_RATE_CACHE['usd'] = rate
    return rate


def get_gbp_eur_rate():
    if 'gbp' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['gbp']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=GBP&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 1.17
    _FIAT_RATE_CACHE['gbp'] = rate
    return rate


def get_sol_eur_rate():
    if 'sol' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['sol']
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur",
            timeout=5
        )
        rate = float(r.json()['solana']['eur'])
    except Exception:
        rate = 150.0
    _FIAT_RATE_CACHE['sol'] = rate
    return rate


def eur_price_from_amounts(amounts, eth_rate):
    """Identica alla versione in track.py: legge il prezzo di un annuncio in qualunque
    valuta Sorare accetti (EUR/ETH/USD/GBP/SOL) e lo converte sempre in EUR."""
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            return None
    if amounts.get('usdCents') is not None:
        try:
            return amounts['usdCents'] / 100 * get_usd_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('gbpCents') is not None:
        try:
            return amounts['gbpCents'] / 100 * get_gbp_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('lamport') is not None:
        try:
            return float(amounts['lamport']) / 1e9 * get_sol_eur_rate()
        except (TypeError, ValueError):
            return None
    return None


GRAPHQL_MIN_INTERVAL_SECONDS = 0.35
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        wait = GRAPHQL_MIN_INTERVAL_SECONDS - (now - _graphql_last_call_ts[0])
        if wait > 0:
            time.sleep(wait)
        _graphql_last_call_ts[0] = time.time()


# FIX 20/07 (allineamento con la nuova architettura autobuy_sorare.py, dopo aver
# risolto unknown_fingerprint): le chiamate CRITICHE (prepareOffer,
# fetchEncryptedPrivateKey, createDirectOffer) passano da un vero browser Chromium
# headless (Playwright), non da requests/curl_cffi -- stesso identico meccanismo gia'
# confermato funzionante e testato con successo in autobuy_sorare.py (primo acquisto
# reale completato il 20/07). Tutto il resto del bot (ricerca carte, prezzi,
# liquidita') resta su graphql_query()/curl_cffi, invariato.
_playwright_instance = None
_playwright_browser = None
_playwright_page = None


def get_browser_page():
    """Apre un browser Chrome invisibile (headless) con i cookie di sessione gia'
    pronti. Riusa lo stesso browser per tutta la run (non lo riapre ogni volta).
    Identica a quella di autobuy_sorare.py: inietta i cookie, fa una navigazione di
    riscaldamento (home + pagina di mercato, domcontentloaded) prima di essere pronta
    per le chiamate critiche."""
    global _playwright_instance, _playwright_browser, _playwright_page
    if _playwright_page is not None:
        return _playwright_page

    _playwright_instance = sync_playwright().start()
    _playwright_browser = _playwright_instance.chromium.launch(headless=True)
    context = _playwright_browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
    )

    cookie_pairs = []
    if COOKIES:
        for pair in COOKIES.split(';'):
            pair = pair.strip()
            if '=' not in pair:
                continue
            name, value = pair.split('=', 1)
            cookie_pairs.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': '.sorare.com',
                'path': '/',
            })
    if cookie_pairs:
        context.add_cookies(cookie_pairs)
        log(f"[playwright] iniettati {len(cookie_pairs)} cookie nel context")
    else:
        log("[playwright] ATTENZIONE: nessun cookie iniettato (COOKIES vuoto o malformato)")

    page = context.new_page()

    try:
        log("[playwright] navigazione di riscaldamento: home page...")
        page.goto('https://sorare.com/', wait_until='domcontentloaded', timeout=20000)
        time.sleep(3)
        log("[playwright] navigazione di riscaldamento: pagina di mercato...")
        page.goto('https://sorare.com/football/market', wait_until='domcontentloaded', timeout=20000)
        time.sleep(3)
    except Exception as e:
        log(f"[playwright] navigazione di riscaldamento fallita parzialmente (non bloccante): {e}")

    _playwright_page = page
    return page


def close_browser():
    """Chiude il browser alla fine (importante per non lasciare processi appesi e
    sprecare tempo del workflow GitHub Actions)."""
    global _playwright_instance, _playwright_browser, _playwright_page
    try:
        if _playwright_browser:
            _playwright_browser.close()
        if _playwright_instance:
            _playwright_instance.stop()
    except Exception as e:
        log(f"[playwright] errore chiudendo il browser: {e}")
    _playwright_instance = None
    _playwright_browser = None
    _playwright_page = None


def graphql_query_via_browser(query, variables=None, timeout_ms=20000):
    """Fa una chiamata GraphQL usando fetch() DENTRO un vero browser Chrome -- stesso
    meccanismo di autobuy_sorare.py, usato per le tre chiamate critiche dell'offerta
    (prepareOffer, fetchEncryptedPrivateKey, createDirectOffer)."""
    page = get_browser_page()
    payload = {"query": query, "variables": variables or {}}

    js_code = """
    async ([url, payload, csrfToken, deviceFingerprint]) => {
        try {
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'x-csrf-token': csrfToken,
            };
            if (deviceFingerprint) {
                headers['device_fingerprint'] = deviceFingerprint;
            }
            const resp = await fetch(url, {
                method: 'POST',
                headers: headers,
                credentials: 'include',
                body: JSON.stringify(payload),
            });
            const text = await resp.text();
            return { status: resp.status, body: text };
        } catch (e) {
            return { status: 0, body: JSON.stringify({error: String(e)}) };
        }
    }
    """

    try:
        result = page.evaluate(
            js_code,
            [GRAPHQL_URL, payload, CSRF_TOKEN, SORARE_DEVICE_FINGERPRINT],
        )
        body_text = result.get('body', '')
        return json.loads(body_text)
    except Exception as e:
        log(f"[playwright graphql] eccezione: {e}")
        return {"errors": [{"message": f"playwright_exception: {e}"}]}


def graphql_query(query, variables=None, max_retries=3, extra_headers=None):
    """Client GraphQL con curl_cffi (impronta TLS Chrome) + header custom, stessa base
    di autobuy_sorare.py -- usato per TUTTE le query non critiche (ricerca carte,
    prezzi, liquidita', assetId carta, ecc.)."""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get(
            'SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if SORARE_DEVICE_FINGERPRINT:
        headers['device_fingerprint'] = SORARE_DEVICE_FINGERPRINT
    if extra_headers and isinstance(extra_headers, dict):
        headers.update(extra_headers)
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        _graphql_throttle()
        if _HAS_CURL_CFFI:
            r = curl_requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15,
                                    impersonate="chrome")
        else:
            r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            wait_seconds = min((2 ** attempt) * 2, 8.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        sender { ... on User { slug } }
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            sportSeason { name }
            inSeasonEligible
            anyPlayer { activeClub { domesticLeague { slug } } }
          }
        }
      }
    }
  }
}
"""

PAGE_SIZE = 50
MAX_PAGES = 20


def fetch_all_live_offers(player_slug):
    """Identica alla versione in track.py: pagina TUTTI gli annunci live di un giocatore
    (il server tronca a ~50 per richiesta). FIX 19/07 (richiesta esplicita utente, caso
    Julien Celestine): i venditori blacklistati (es. Clem777) NON vengono piu' esclusi qui
    -- le loro carte contano comunque per il vero minimo/secondo prezzo di mercato, altrimenti
    il margine calcolato risulta gonfiato (visto dal vivo: un annuncio intermedio di Clem777
    veniva "saltato", facendo sembrare il margine piu' alto di quanto fosse in realta').
    L'esclusione dei blacklistati resta, ma solo al momento di DECIDERE se acquistare (vedi
    evaluate_event): se il vero minimo risulta di un venditore blacklistato, il bot scarta il
    caso invece di comprare da lui."""
    all_nodes = []
    cursor = None
    for _ in range(MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[paginazione annunci live] errore per {player_slug}: {data['errors']}")
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes


def get_bucket_prices(player_slug, eth_rate):
    """Legge TUTTI gli annunci live in_season/classic del giocatore in un solo fetch, come
    get_bucket_prices in track.py. Restituisce {'in_season': [(prezzo, card_slug, seller_slug), ...],
    'classic': [(prezzo, card_slug, seller_slug), ...]}, entrambe ordinate per prezzo crescente.
    seller_slug incluso (FIX 19/07) per poter distinguere, a valle, se il vero minimo e' di un
    venditore blacklistato -- vedi nota in fetch_all_live_offers ed evaluate_event."""
    nodes = fetch_all_live_offers(player_slug)
    raw = {'in_season': [], 'classic': []}
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta, non una vendita in denaro
        seller_slug = ((node.get('sender') or {}).get('slug') or '').lower()
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited':
                continue
            if c.get('sport') != 'FOOTBALL':
                continue
            match = c
            break
        if not match:
            continue
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            continue
        bucket = 'in_season' if match.get('inSeasonEligible') else 'classic'
        raw[bucket].append((price, match.get('slug'), seller_slug))
    for key in ('in_season', 'classic'):
        raw[key].sort(key=lambda p: p[0])
    return raw


def is_asia_americas_excluded_league(league_slug):
    """I 2 campionati (MLS, K League) per cui il confronto con il classic va escluso --
    restano solo con la logica in_season pura gia' in produzione. J League ESCLUSA da questo
    filtro su decisione dell'utente (19/07): per J League vale la logica normale in_season+
    classic come tutti gli altri campionati. Vedi nota nell'area di memoria del progetto:
    motivazione non tecnica, richiesta esplicita dell'utente. Se league_slug e' None/
    sconosciuto (es. giocatore attualmente senza squadra), NON viene considerato escluso --
    si applica comunque in_season+classic, comportamento di default corretto e verificato."""
    return league_slug in EXCLUDED_LEAGUE_SLUGS


def get_in_season_prices(player_slug, eth_rate, league_slug):
    """Restituisce (prices_da_confrontare, is_excluded_league) dove prices_da_confrontare
    e' una lista (prezzo, card_slug) ordinata crescente:
    - Per MLS/K League/J League (is_excluded_league=True): SOLO in_season, comportamento
      identico a prima del confronto con classic (nessuna modifica di logica per questi 3).
    - Per tutti gli altri campionati: in_season + classic UNITI in un'unica lista ordinata,
      trattando il classic come "un ulteriore annuncio in_season" ai fini del vero minimo/
      secondo prezzo -- criterio esplicito richiesto dall'utente."""
    buckets = get_bucket_prices(player_slug, eth_rate)
    excluded = is_asia_americas_excluded_league(league_slug)
    if excluded:
        return buckets['in_season'], True
    combined = buckets['in_season'] + buckets['classic']
    combined.sort(key=lambda p: p[0])
    if MAKEOFFER_DIAGNOSTIC and buckets['classic']:
        log(f"[diagnostica lega] player={player_slug} league_slug={league_slug!r} -- "
            f"unito in_season ({len(buckets['in_season'])} annunci) con classic "
            f"({len(buckets['classic'])} annunci) per il confronto sul vero minimo")
    return combined, False


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log(f"Errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


def build_card_link(player_slug, card_slug):
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    return f"{base_link}?card={card_slug}" if card_slug else base_link


# --- Protezione "liquidita' minima del giocatore" (richiesta esplicita utente, 19/07) ---
# Motivazione: se un giocatore ha pochissime transazioni recenti, un annuncio "affare" puo'
# essere frutto di un evento anomalo (es. infortunio, con manager che svendono a raffica le
# poche carte rimaste) piuttosto che un vero errore di prezzo su un mercato liquido -- meglio
# ignorare il caso piuttosto che rischiare di comprare su un mercato cosi' sottile. Query
# riusata da track.py (funzione fetch_player_recent_direct_buys, gia' confermata funzionante
# dal vivo): tokens.tokenPrices(playerSlug, rarity: limited) con deal.type -- a differenza di
# track.py (che filtra SOLO deal.type == 'SINGLE_SALE_OFFER' per isolare lo sniping), qui
# contiamo QUALSIASI transazione (deal.type presente, qualunque valore: SINGLE_SALE_OFFER,
# SINGLE_BUY_OFFER, DIRECT_OFFER, aste, ecc. -- richiesta esplicita "di qualunque tipo incluso
# le aste, offerta diretta, scambio"), perche' qui l'obiettivo e' misurare la liquidita'
# generale del giocatore, non isolare un tipo di transazione specifico.
RECENT_TRANSACTIONS_QUERY = """
query RecentTransactionsQuery($p: String!) {
  tokens {
    tokenPrices(playerSlug: $p, rarity: limited) {
      date
      deal {
        __typename
        ... on TokenOffer {
          type
        }
      }
    }
  }
}
"""

# Doppio layer di protezione liquidita' (richiesta esplicita utente, 19/07): la finestra
# breve (7gg) da sola potrebbe far passare un giocatore con un breve picco isolato di
# transazioni ma comunque poco liquido nel complesso -- aggiunta una seconda soglia su
# una finestra piu' lunga (30gg) come controllo incrociato. ENTRAMBE le condizioni devono
# essere soddisfatte perche' il giocatore passi (basta che UNA delle due fallisca per
# scartare il caso).
MIN_RECENT_TRANSACTIONS = int(os.environ.get('MIN_RECENT_TRANSACTIONS', '3'))
RECENT_TRANSACTIONS_WINDOW_DAYS = int(os.environ.get('RECENT_TRANSACTIONS_WINDOW_DAYS', '7'))
MIN_TRANSACTIONS_30D = int(os.environ.get('MIN_TRANSACTIONS_30D', '5'))
TRANSACTIONS_WINDOW_30D_DAYS = int(os.environ.get('TRANSACTIONS_WINDOW_30D_DAYS', '30'))


def count_recent_transactions(player_slug):
    """Ritorna una tupla (count_7d, count_30d): numero di transazioni (di qualunque tipo --
    vendita diretta, offerta diretta, asta, ecc.) di player_slug rispettivamente negli
    ultimi RECENT_TRANSACTIONS_WINDOW_DAYS e TRANSACTIONS_WINDOW_30D_DAYS giorni (in
    un'unica query/passata sui dati, TRANSACTIONS_WINDOW_30D_DAYS include sempre l'altra
    finestra essendo piu' lunga). Ritorna (None, None) se la query fallisce per qualunque
    motivo. Fail-safe: se la query fallisce, il chiamante NON deve bloccare l'acquisto
    solo per questo (stessa filosofia di get_card_coverage_status) -- vedi commento nella
    chiamata in evaluate_event."""
    try:
        data = graphql_query(RECENT_TRANSACTIONS_QUERY, {"p": player_slug})
        if data.get('errors'):
            log(f"[liquidita'] errore GraphQL per {player_slug}: {data['errors']}")
            return None, None
        nodes = ((data.get('data') or {}).get('tokens') or {}).get('tokenPrices') or []
    except Exception as e:
        log(f"[liquidita'] eccezione per {player_slug}: {e}")
        return None, None

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_short = now - datetime.timedelta(days=RECENT_TRANSACTIONS_WINDOW_DAYS)
    cutoff_long = now - datetime.timedelta(days=TRANSACTIONS_WINDOW_30D_DAYS)
    count_short = 0
    count_long = 0
    for n in nodes:
        deal = n.get('deal') or {}
        # FIX 19/07 (caso reale, errore GraphQL osservato dal vivo): sia TokenAuction che
        # TokenPrimaryOffer NON hanno un campo 'type' (solo TokenOffer ce l'ha) -- entrambi
        # sono comunque transazioni valide da contare, li riconosciamo dal __typename
        # invece che dal campo 'type' (assente in entrambi i casi).
        deal_typename = deal.get('__typename')
        is_countable = bool(deal.get('type')) or deal_typename in ('TokenAuction', 'TokenPrimaryOffer')
        if not is_countable:
            continue  # nodo senza tipo riconoscibile, non contabile con certezza
        date_str = n.get('date') or ''
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        if dt >= cutoff_long:
            count_long += 1
            if dt >= cutoff_short:
                count_short += 1
    return count_short, count_long


# --- Prezzo dell'offerta: sconto ulteriore rispetto al minimo trovato ---
# Richiesta esplicita utente (19/07): il bot ascolta come AutoBuy (stesso identico
# criterio "trovato un margine valido sul minimo attuale"), ma invece di comprare al
# prezzo minimo trovato, propone un'offerta ULTERIORMENTE scontata rispetto a quel
# minimo, con una percentuale di sconto separata e configurabile (non lo stesso
# MAKEOFFER_MARGIN_FRACTION usato per decidere se il caso e' valido -- quello resta il
# filtro di ricerca, questo e' quanto scontare in piu' sull'offerta stessa).
OFFER_DISCOUNT_FRACTION = float(os.environ.get('OFFER_DISCOUNT_FRACTION', '0.10'))

# Durata dell'offerta in giorni (Sorare accetta solo valori interi 1-7, vedi campo
# 'duration' in secondi nella mutation CreateDirectOfferMutation -- 1 giorno = 86400s).
OFFER_DURATION_DAYS = int(os.environ.get('OFFER_DURATION_DAYS', '1'))
OFFER_DURATION_DAYS = max(1, min(7, OFFER_DURATION_DAYS))
OFFER_DURATION_SECONDS = OFFER_DURATION_DAYS * 86400

# Tetto massimo di offerte PENDENTI (non ancora accettate/rifiutate/scadute)
# contemporaneamente, per non riempire l'account di offerte aperte senza controllo.
MAX_PENDING_OFFERS = int(os.environ.get('MAX_PENDING_OFFERS', '10'))


EXCHANGE_RATE_QUERY = """
query ExchangeRateQuery {
  config {
    exchangeRate { id }
  }
}
"""


def get_exchange_rate_id():
    """Recupera l'id del tasso di cambio corrente (serve a PrepareOfferMutation), stessa
    query ExchangeRateQuery vista nel flusso reale di offerta in browser."""
    try:
        data = graphql_query(EXCHANGE_RATE_QUERY)
        return (((data.get('data') or {}).get('config') or {}).get('exchangeRate') or {}).get('id')
    except Exception as e:
        log(f"[prepare offer] errore lettura tasso di cambio: {e}")
        return None


def classify_prepare_offer_error(root_errors, payload_errors):
    """Stessa filosofia di classify_prepare_accept_error in autobuy_sorare.py: mai una
    categoria che potrebbe indurre un retry automatico, qualunque errore non riconosciuto
    finisce in 'sconosciuto'. Categorie note per PrepareOfferMutation/
    CreateDirectOfferMutation: 'valuta_non_supportata' (venditore non accetta EUR --
    richiesta esplicita utente: "se venditore non accetta euro... skippare"),
    'offerta_gia_esistente' (offerta pendente gia' presente sulla stessa carta),
    'offerta_non_disponibile' (carta venduta/rimossa nel frattempo), 'sconosciuto'."""
    all_errors = list(root_errors or []) + list(payload_errors or [])
    if not all_errors:
        return 'nessun_errore', all_errors

    combined_text = ' '.join(
        str(e.get('message', '')) + ' ' + str(e.get('extensions', {}).get('code', ''))
        for e in all_errors if isinstance(e, dict)
    ).lower()

    if any(kw in combined_text for kw in
           ('currency', 'settlement', 'unsupported', 'valuta')):
        return 'valuta_non_supportata', all_errors
    if any(kw in combined_text for kw in
           ('already', 'existing', 'duplicate', 'pending')):
        return 'offerta_gia_esistente', all_errors
    if any(kw in combined_text for kw in
           ('not_found', 'expired', 'sold', 'unavailable', 'not_available')):
        return 'offerta_non_disponibile', all_errors

    return 'sconosciuto', all_errors


PREPARE_OFFER_MUTATION = """
mutation PrepareOfferMutation($input: prepareOfferInput!) {
  prepareOffer(input: $input) {
    authorizations {
      fingerprint
      id
      request {
        ... on MangopayWalletTransferAuthorizationRequest {
          currency
          amount
          mangopayWalletId
          nonce
          operationHash
        }
      }
    }
    errors { message }
  }
}
"""


def prepare_offer(card_asset_id, receiver_slug, offer_amount_eur):
    """Prenota/valida la creazione di un'offerta diretta lato server -- mutation
    confermata dal vivo (19/07, catturata via DevTools mentre l'utente faceva un'offerta
    reale su una carta di test). NON invia ancora l'offerta: restituisce
    {fingerprint, request, exchange_rate_id} da usare per firmare e poi chiamare
    create_direct_offer. card_asset_id e' l'assetId ESADECIMALE della carta (campo
    'assetId' della carta, es. "0x0400...", NON lo slug) -- confermato nel payload reale
    catturato (receiveAssetIds contiene l'assetId, non lo slug)."""
    exchange_rate_id = get_exchange_rate_id()
    if not exchange_rate_id:
        log("[prepare offer] exchange_rate_id non ottenuto, impossibile procedere")
        return None
    variables = {
        "input": {
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(round(offer_amount_eur, 2)), "currency": "EUR"},
            "receiveAmount": {"amount": "0", "currency": "EUR"},
            "settlementCurrencies": ["EUR"],
        }
    }
    try:
        data = graphql_query_via_browser(PREPARE_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('prepareOffer') or {}
        payload_errors = payload.get('errors') or []

        if root_errors or payload_errors:
            category, all_errors = classify_prepare_offer_error(root_errors, payload_errors)
            log(f"[prepare offer] fallita, categoria='{category}', errori={all_errors}")
            return None

        auths = payload.get('authorizations') or []
        if not auths:
            log("[prepare offer] nessuna authorization restituita")
            return None
        auth = auths[0]
        request = dict(auth.get('request') or {})
        request['__typename'] = 'MangopayWalletTransferAuthorizationRequest'
        return {'fingerprint': auth.get('fingerprint'), 'request': request,
                'exchange_rate_id': exchange_rate_id}
    except Exception as e:
        log(f"[prepare offer] eccezione: {e}")
        return None


FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION = """
mutation FetchEncryptedPrivateKey($input: fetchEncryptedPrivateKeyInput!) {
  fetchEncryptedPrivateKey(input: $input) {
    errors { message }
    sorarePrivateKey {
      encryptedPrivateKey
      iv
      salt
    }
  }
}
"""


def fetch_encrypted_private_key():
    """Recupera encryptedPrivateKey/iv/salt tramite la mutation FetchEncryptedPrivateKey
    (nome/struttura confermati dal vivo il 19/07, stesso meccanismo gia' usato e testato
    in autobuy_sorare.py). Ritorna il dict {encryptedPrivateKey, iv, salt} o None."""
    try:
        data = graphql_query_via_browser(FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION, {"input": {}})
        if data.get('errors'):
            log(f"[chiave cifrata] errore GraphQL: {data['errors']}")
            return None
        payload = (data.get('data') or {}).get('fetchEncryptedPrivateKey') or {}
        payload_errors = payload.get('errors') or []
        if payload_errors:
            log(f"[chiave cifrata] errore payload: {payload_errors}")
            return None
        key_data = payload.get('sorarePrivateKey')
        if not key_data:
            log("[chiave cifrata] sorarePrivateKey assente nella risposta")
            return None
        return key_data
    except Exception as e:
        log(f"[chiave cifrata] eccezione: {e}")
        return None


def sign_authorization_via_node(password, encrypted_private_key, iv, salt, authorization_request):
    """Identica alla funzione gia' scritta/testata in autobuy_sorare.py -- chiama
    sorare-sign/decrypt_and_sign.js via subprocess. Stesso script Node condiviso tra i
    due bot (nessuna duplicazione, la cartella sorare-sign/ resta unica nel repo)."""
    import subprocess
    payload = json.dumps({
        'password': password,
        'encryptedPrivateKey': encrypted_private_key,
        'iv': iv,
        'salt': salt,
        'authorizationRequest': authorization_request,
    })
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sorare-sign', 'decrypt_and_sign.js')
    try:
        result = subprocess.run(
            ['node', script_path],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        log(f"[firma Node] eccezione lanciando node: {e}")
        return None
    if result.returncode != 0:
        log(f"[firma Node] script terminato con errore (codice {result.returncode}): {result.stderr.strip()}")
        return None
    try:
        output = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        log(f"[firma Node] output non JSON valido: {result.stdout!r}")
        return None
    if 'error' in output:
        log(f"[firma Node] errore riportato dallo script: {output['error']}")
        return None
    return output.get('signature')


CREATE_DIRECT_OFFER_MUTATION = """
mutation CreateDirectOfferMutation($input: createDirectOfferInput!) {
  createDirectOffer(input: $input) {
    errors { message }
    tokenOffer {
      id
      senderSide {
        amounts { eurCents }
      }
    }
  }
}
"""


import uuid


def generate_deal_id():
    """dealId CONFERMATO (20/07, verifica dal vivo) essere un UUID v4 generato
    CLIENT-SIDE (dal browser), NON restituito da PrepareOfferMutation (verificato che
    la risposta contiene solo authorizations+errors, mai un dealId). Lunghezza del
    dealId reale osservato (39 cifre decimali) coincide esattamente con un UUID v4
    convertito in intero. Lo stesso valore generato qui va riusato IDENTICO sia nella
    prepare (se mai richiesto in futuro) sia nella create_direct_offer finale."""
    return str(uuid.uuid4().int)


def create_direct_offer(card_asset_id, receiver_slug, offer_amount_eur, fingerprint, nonce, signature, deal_id):
    """Ultimo passo: invia DAVVERO l'offerta diretta al venditore -- mutation confermata
    dal vivo (19/07, caso reale David Alaba/satonio, offerta di test inviata con
    successo). Fail-safe assoluto: qualunque errore ritorna (False, categoria, msg), MAI
    un'eccezione non gestita, MAI un retry automatico."""
    variables = {
        "input": {
            "dealId": deal_id,
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(round(offer_amount_eur, 2)), "currency": "EUR"},
            "duration": OFFER_DURATION_SECONDS,
            "migrationData": None,
            "approvals": [{
                "fingerprint": fingerprint,
                "mangopayWalletTransferApproval": {
                    "nonce": nonce,
                    "signature": signature,
                },
            }],
        }
    }
    try:
        data = graphql_query_via_browser(CREATE_DIRECT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('createDirectOffer') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_prepare_offer_error(root_errors, payload_errors)
            log(f"[create offer] fallita, categoria='{category}', errori={all_errors}")
            return False, category, str(all_errors)
        token_offer = payload.get('tokenOffer')
        if not token_offer:
            # FIX 20/07 (prudenza, stesso pattern gia' visto su acceptOffer -- il
            # campo 'offer' e' scomparso dallo schema di acceptOfferPayload, quindi e'
            # plausibile che anche 'tokenOffer' possa mancare qui senza che sia un
            # vero fallimento): se NON ci sono errori, trattiamo comunque come
            # successo, solo con un log di avviso.
            log(f"[create offer] risposta senza 'tokenOffer' ma NESSUN errore -- "
                f"probabile successo (schema Sorare potrebbe non restituire piu' "
                f"questo campo, vedi caso analogo 'offer' in acceptOffer): "
                f"{json.dumps(data)[:500]}")
            return True, None, None
        log(f"[create offer] successo, offer id={token_offer.get('id')}")
        return True, None, None
    except Exception as e:
        log(f"[create offer] eccezione: {e}")
        return False, 'eccezione', str(e)


def execute_live_offer(card_asset_id, receiver_slug, offer_amount_eur, prepared):
    """Orchestrazione completa (attiva SOLO se MAKEOFFER_LIVE_MODE e' 'si'): chiave
    cifrata -> firma -> create_direct_offer. Fail-safe assoluto: MAI retry, un solo
    tentativo secco. Logga ogni step con OK/STOP esplicito."""
    log(f"[offerta live] avvio -- carta={card_asset_id}, venditore={receiver_slug}, "
        f"offerta={offer_amount_eur:.2f}EUR")

    if not SORARE_WALLET_PASSWORD:
        log("[offerta live] STOP: SORARE_WALLET_PASSWORD non impostata")
        return False, "SORARE_WALLET_PASSWORD non impostata"

    key_data = fetch_encrypted_private_key()
    if not key_data:
        log("[offerta live] STOP: chiave cifrata non recuperata (vedi log [chiave cifrata] sopra)")
        return False, "impossibile recuperare la chiave cifrata (fetchEncryptedPrivateKey)"
    log("[offerta live] step 1/3 OK: chiave cifrata recuperata")

    fingerprint = prepared.get('fingerprint')
    request = prepared.get('request') or {}
    nonce = request.get('nonce')

    signature = sign_authorization_via_node(
        SORARE_WALLET_PASSWORD,
        key_data.get('encryptedPrivateKey'),
        key_data.get('iv'),
        key_data.get('salt'),
        request,
    )
    if not signature:
        log("[offerta live] STOP: firma fallita (vedi log [firma Node] sopra per il dettaglio esatto)")
        return False, "firma fallita (vedi log [firma Node] per il dettaglio esatto)"
    log("[offerta live] step 2/3 OK: firma generata")

    deal_id = generate_deal_id()
    success, category, error = create_direct_offer(
        card_asset_id, receiver_slug, offer_amount_eur, fingerprint, nonce, signature, deal_id)
    if not success:
        log(f"[offerta live] STOP: step 3/3 fallito, categoria='{category}'")
        return False, f"CreateDirectOfferMutation fallita [{category}]: {error}"
    log("[offerta live] step 3/3 OK: offerta inviata")
    return True, None


def send_would_have_bought_alert(player_name, player_slug, price_eur, second_price, margin_percent,
                                  card_slug, excluded_league, prepared=None, is_in_season=True,
                                  live_mode=False, purchase_completed=False, purchase_error=None,
                                  offer_amount_eur=None):
    link = build_card_link(player_slug, card_slug)
    if not is_in_season:
        categoria = "CLASSIC (modalita' check_classic, confronto su tutti i campionati)"
    else:
        categoria = "In Season" if excluded_league else "In Season + Classic (confronto unito)"
    prenotazione = (
        "\u2705 Offerta prenotata lato server (piu' veloce da confermare)\n"
        if prepared else
        "\u26A0\uFE0F Prenotazione lato server non riuscita, apri e conferma normalmente\n"
    )
    offer_line = f"Offerta calcolata: {offer_amount_eur:.2f}EUR\n" if offer_amount_eur is not None else ""
    if live_mode:
        if purchase_completed:
            titolo = "\U0001F916\U0001F4B0 <b>MakeOffer Sorare -- OFFERTA INVIATA IN AUTOMATICO</b>"
            esito = "\u2705 <b>Offerta inviata con successo, in attesa che il venditore risponda.</b>\n\n"
        else:
            titolo = "\U0001F916\U0001F4B0 <b>MakeOffer Sorare -- OFFERTA AUTOMATICA FALLITA</b>"
            esito = (f"\u274C <b>Offerta automatica NON inviata</b>: {purchase_error}\n"
                      f"Apri e valuta se fare l'offerta a mano.\n\n")
    else:
        titolo = "\U0001F916\U0001F4B0 <b>MakeOffer Sorare -- FAREI UN'OFFERTA</b>"
        esito = "\u26A0\uFE0F Fase di test: nessuna offerta reale inviata, controlla a mano.\n\n"
    msg_text = (
        f"{titolo}\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: {categoria}\n"
        f"Prezzo minimo attuale: {price_eur:.2f}EUR\n"
        f"Secondo prezzo attuale: {second_price:.2f}EUR (margine {margin_percent:.1%}, "
        f"soglia richiesta {MAKEOFFER_MARGIN_FRACTION:.0%})\n"
        f"{offer_line}\n"
        f"{prenotazione}"
        f"{esito}"
        f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
    )
    send_telegram_msg(msg_text)


def send_startup_msg():
    classic_msg = "\nModalita' CLASSIC attiva (tutti i campionati)" if CHECK_CLASSIC else ""
    intestazione = (
        "\U0001F916\u26A0\uFE0F <b>MakeOffer Sorare avviato -- OFFERTE REALI AUTOMATICHE ATTIVE</b>\n"
        if MAKEOFFER_LIVE_MODE else
        "\U0001F916 <b>MakeOffer Sorare avviato</b> (solo diagnostica, nessun acquisto reale)\n"
    )
    send_telegram_msg(
        f"{intestazione}"
        f"Fascia prezzo: {MAKEOFFER_MIN_PRICE_EUR:.2f}-{MAKEOFFER_MAX_PRICE_EUR:.2f}EUR\n"
        f"Margine richiesto: {MAKEOFFER_MARGIN_FRACTION:.0%}\n"
        f"Ascolto per {LISTEN_SECONDS}s o fino al primo caso valido.{classic_msg}"
    )


def send_end_msg(matches_found, target_reached):
    esito = (
        f"\u2705 Target raggiunto: {matches_found}/{MAKEOFFER_TARGET_MATCHES} casi trovati"
        if target_reached else
        f"\u23F1 Tempo scaduto: {matches_found}/{MAKEOFFER_TARGET_MATCHES} casi trovati"
    )
    send_telegram_msg(
        f"\U0001F916 <b>MakeOffer Sorare terminato</b>\n"
        f"{esito}"
    )


# Contatore in-memory per run (richiesta esplicita utente: tetto massimo offerte
# pendenti create in questa esecuzione, vedi MAX_PENDING_OFFERS sopra e controllo in
# evaluate_event). Lista di un elemento per essere mutabile per riferimento tra
# funzioni senza dover passare 'global' esplicitamente ovunque.
pending_offers_count = [0]


CARD_OFFER_DETAILS_QUERY = """
query CardOfferDetailsQuery($slug: String!) {
  anyCard(slug: $slug) {
    slug
    assetId
    liveSingleBuyOffers {
      id
      sender { ... on User { slug } }
    }
    liveSingleSaleOffer {
      settlementCurrencies
    }
  }
}
"""


def get_card_offer_details(card_slug):
    """Recupera assetId (necessario per creare l'offerta), le eventuali offerte
    pendenti gia' presenti su questa carta (liveSingleBuyOffers, per lo skip "gia' ho
    un'offerta pendente" richiesto esplicitamente dall'utente), e le valute accettate
    dal venditore (settlementCurrencies, per lo skip "se non accetta EUR" richiesto
    esplicitamente). Fail-safe: se la query fallisce, ritorna None e il chiamante deve
    SALTARE il caso (senza assetId non si puo' fare l'offerta comunque)."""
    try:
        data = graphql_query(CARD_OFFER_DETAILS_QUERY, {"slug": card_slug})
        if data.get('errors'):
            log(f"[dettagli carta] errore per {card_slug}: {data['errors']}")
            return None
        card = (data.get('data') or {}).get('anyCard')
        if not card:
            return None
        return card
    except Exception as e:
        log(f"[dettagli carta] eccezione per {card_slug}: {e}")
        return None


def evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate, league_slug=None,
                    offer_id=None, seller_slug=None, is_in_season=True):
    """Ritorna True se questo evento ha portato a un caso valido (avrebbe acquistato),
    False altrimenti -- usato dal listener per decidere se fermarsi.
    is_in_season=False + CHECK_CLASSIC attivo: modalita' aggiuntiva (19/07) che valuta
    annunci CLASSIC per TUTTI i campionati senza eccezioni, confrontando contro il minimo
    ASSOLUTO tra classic+in_season uniti (niente distinzione di lega esclusa, quella
    logica resta solo per gli annunci in_season -- vedi get_in_season_prices)."""
    if player_slug and player_slug.lower() in BLACKLISTED_PLAYER_SLUGS:
        log(f"{player_name}: scarto -- giocatore in blacklist manuale ({player_slug})")
        return False

    if player_slug and is_player_in_offer_cooldown(player_slug):
        log(f"{player_name}: scarto -- gia' acquistato nelle ultime {PLAYER_OFFER_COOLDOWN_HOURS}h "
            f"(protezione anti-svendita/infortunio, vedi makeoffer_cooldown.json)")
        return False

    if not (MAKEOFFER_MIN_PRICE_EUR <= price_eur <= MAKEOFFER_MAX_PRICE_EUR):
        return False

    # Protezione liquidita' minima (richiesta esplicita utente, 19/07): scarta il
    # giocatore se ha meno di MIN_RECENT_TRANSACTIONS transazioni (di qualunque tipo)
    # negli ultimi RECENT_TRANSACTIONS_WINDOW_DAYS giorni -- un mercato troppo sottile
    # rende rischioso fidarsi di un margine che sembra un affare. Se la query fallisce
    # (None), NON blocchiamo l'acquisto solo per questo.
    # FIX 19/07 (ottimizzazione velocita' sniping, richiesta esplicita utente, analisi log
    # reale): riportato QUI, prima del calcolo prezzi -- il caso piu' comune di scarto nei
    # log e' "non e' il minimo attuale" (spesso il vero minimo e' molto piu' basso
    # dell'annuncio dell'evento, es. evento 1.29EUR con vero minimo 0.33EUR), quindi
    # calcolare prima il vero minimo (query pesante, spesso su decine di annunci) solo per
    # scoprire poi che il caso viene scartato per liquidita' e' comunque uno spreco. La
    # query di liquidita' e' tipicamente piu' leggera/rapida ed e' un buon filtro
    # discriminante iniziale -- verificarla per prima riduce il lavoro sui casi che
    # verrebbero comunque scartati.
    if player_slug and is_player_in_thin_market_cache(player_slug):
        log(f"{player_name}: scarto -- gia' segnalato come mercato troppo sottile negli "
            f"ultimi {THIN_MARKET_SKIP_DAYS} giorni, salto la riverifica")
        return False

    count_7d, count_30d = count_recent_transactions(player_slug)
    if count_7d is not None and count_7d < MIN_RECENT_TRANSACTIONS:
        log(f"{player_name}: scarto -- solo {count_7d} transazioni negli ultimi "
            f"{RECENT_TRANSACTIONS_WINDOW_DAYS} giorni (minimo richiesto "
            f"{MIN_RECENT_TRANSACTIONS}), mercato troppo sottile")
        if player_slug:
            record_thin_market_skip(player_slug)
        return False
    if count_30d is not None and count_30d < MIN_TRANSACTIONS_30D:
        log(f"{player_name}: scarto -- solo {count_30d} transazioni negli ultimi "
            f"{TRANSACTIONS_WINDOW_30D_DAYS} giorni (minimo richiesto "
            f"{MIN_TRANSACTIONS_30D}), mercato troppo sottile")
        if player_slug:
            record_thin_market_skip(player_slug)
        return False

    if is_in_season:
        prices, excluded_league = get_in_season_prices(player_slug, eth_rate, league_slug)
        if MAKEOFFER_DIAGNOSTIC:
            modalita = "SOLO in_season (lega esclusa)" if excluded_league else "in_season + classic uniti"
            log(f"[diagnostica lega] {player_name}: league_slug={league_slug!r} -> {modalita}, "
                f"{len(prices)} annunci totali nel confronto")
    else:
        # Annuncio CLASSIC con CHECK_CLASSIC attivo: minimo assoluto tra i due bucket,
        # SEMPRE, per qualunque campionato -- nessuna eccezione MLS/K League qui.
        buckets = get_bucket_prices(player_slug, eth_rate)
        prices = buckets['in_season'] + buckets['classic']
        prices.sort(key=lambda p: p[0])
        excluded_league = False
        if MAKEOFFER_DIAGNOSTIC:
            log(f"[check classic] {player_name}: {len(prices)} annunci totali "
                f"(in_season {len(buckets['in_season'])} + classic {len(buckets['classic'])})")
    if not prices:
        return False

    true_min_price, true_min_card_slug, true_min_seller_slug = prices[0]

    # Il prezzo dell'evento potrebbe non essere il minimo reale attuale (altri annunci gia'
    # piu' economici sullo stesso giocatore) -- criterio esplicito: valutiamo solo se la
    # carta appena spuntata E' il minimo attuale sul mercato in_season (o in_season+classic
    # unito, a seconda della lega -- vedi get_in_season_prices).
    if true_min_card_slug != card_slug:
        if price_eur < true_min_price:
            # Fallback (no retry, no attese -- critico per lo sniping): l'evento WebSocket
            # e' piu' fresco della query di rilettura prezzi, che puo' non aver ancora
            # propagato l'ultimo annuncio. Se il prezzo dell'evento e' comunque il piu'
            # basso in assoluto, ci fidiamo dell'evento invece di scartare.
            log(f"{player_name}: minimo query non aggiornato ({true_min_price:.2f}EUR), "
                f"ma evento a {price_eur:.2f}EUR e' piu' basso -- procedo con l'evento")
            true_min_price, true_min_card_slug, true_min_seller_slug = price_eur, card_slug, seller_slug
            prices = [(price_eur, card_slug, seller_slug)] + [p for p in prices if p[1] != card_slug]
        else:
            categoria = "in_season" if excluded_league else "in_season/classic"
            log(f"{player_name}: scarto -- annuncio a {price_eur:.2f}EUR non e' il minimo attuale "
                f"{categoria} (minimo vero: {true_min_price:.2f}EUR)")
            return False

    # FIX 19/07 (caso Julien Celestine, poi esteso alla blacklist manager AutoBuy):
    # i venditori blacklistati (sia BLACKLISTED_SELLER_SLUGS storica sia
    # BLACKLISTED_MAKEOFFER_MANAGER_SLUGS solo per questo bot) CONTANO nel confronto prezzi
    # (vedi get_bucket_prices/fetch_all_live_offers, nessuna delle due liste li filtra
    # li'), ma non compriamo mai da loro. Se il vero minimo attuale risulta essere
    # proprio un annuncio di uno di questi venditori, scartiamo il caso -- anche se
    # sembrerebbe "il miglior prezzo", non e' comprabile secondo le regole dell'utente.
    if true_min_seller_slug in BLACKLISTED_SELLER_SLUGS or \
            true_min_seller_slug in BLACKLISTED_MAKEOFFER_MANAGER_SLUGS:
        log(f"{player_name}: scarto -- il minimo attuale ({true_min_price:.2f}EUR) e' di un "
            f"venditore blacklistato ({true_min_seller_slug}), non acquistabile")
        return False

    if len(prices) < 2:
        log(f"{player_name}: scarto -- nessun secondo annuncio per confrontare il margine")
        return False

    second_min_price, _, _ = prices[1]
    if second_min_price <= 0:
        return False

    margin_percent = (second_min_price - true_min_price) / second_min_price
    log(f"{player_name}: minimo {true_min_price:.2f}EUR, secondo {second_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%} (soglia {MAKEOFFER_MARGIN_FRACTION:.0%})")

    if margin_percent < MAKEOFFER_MARGIN_FRACTION:
        return False

    log(f"MAKEOFFER: {player_name} -- TROVATO AFFARE ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%}) -- valuto se fare un'offerta")

    # Recupero dettagli carta: assetId (necessario per l'offerta), offerte pendenti
    # gia' esistenti su questa carta, valute accettate dal venditore.
    card_details = get_card_offer_details(card_slug)
    if not card_details:
        log(f"{player_name}: scarto -- impossibile recuperare i dettagli della carta "
            f"({card_slug}), niente assetId disponibile")
        return False

    card_asset_id = card_details.get('assetId')
    if not card_asset_id:
        log(f"{player_name}: scarto -- assetId assente per {card_slug}")
        return False

    # Skip se offerta gia' pendente su questa carta (richiesta esplicita utente:
    # "ignora e non fare una seconda offerta finche' la prima non si risolve").
    existing_offers = card_details.get('liveSingleBuyOffers') or []
    if existing_offers:
        log(f"{player_name}: scarto -- offerta gia' pendente su questa carta "
            f"({len(existing_offers)} offerta/e attiva/e), non ne faccio una seconda")
        return False

    # Skip se il venditore non accetta EUR (richiesta esplicita utente: "offerte solo
    # in euro, se venditore non accetta euro... skippare"). E' raro (prezzo fisso per
    # alcune carte) ma va controllato.
    sale_offer = card_details.get('liveSingleSaleOffer') or {}
    settlement_currencies = sale_offer.get('settlementCurrencies') or []
    if settlement_currencies and 'EUR' not in settlement_currencies:
        log(f"{player_name}: scarto -- venditore non accetta EUR "
            f"(valute accettate: {settlement_currencies})")
        return False

    # Tetto massimo offerte pendenti totali (richiesta esplicita utente, configurabile).
    # Nota: questo conta le offerte fatte DA NOI in questa sessione/run -- non esiste
    # un modo semplice per contare TUTTE le offerte pendenti dell'account via una query
    # dedicata gia' nota, quindi usiamo un contatore in-memory per run (vedi run_listener).
    if pending_offers_count[0] >= MAX_PENDING_OFFERS:
        log(f"{player_name}: scarto -- gia' raggiunto il tetto di {MAX_PENDING_OFFERS} "
            f"offerte pendenti in questa esecuzione")
        return False

    # Prezzo dell'offerta: sconto ULTERIORE rispetto al minimo trovato (richiesta
    # esplicita utente: "se trova un affare con 10% di margine, fare offerta per un
    # ulteriore margine di 10% in meno").
    offer_amount_eur = round(true_min_price * (1 - OFFER_DISCOUNT_FRACTION), 2)
    if offer_amount_eur <= 0:
        log(f"{player_name}: scarto -- offerta calcolata non positiva ({offer_amount_eur}EUR)")
        return False

    log(f"{player_name}: offerta calcolata: {offer_amount_eur:.2f}EUR "
        f"(minimo {true_min_price:.2f}EUR - sconto {OFFER_DISCOUNT_FRACTION:.0%}), "
        f"durata {OFFER_DURATION_DAYS} giorni")

    # Prenotazione (prepare_offer) PRIMA di notificare, stesso principio gia' usato in
    # autobuy_sorare.py -- riduce la finestra di rischio, non fa side-effect sul saldo.
    prepared = None
    prepared = prepare_offer(card_asset_id, seller_slug, offer_amount_eur)
    if prepared:
        nonce = (prepared.get('request') or {}).get('nonce')
        log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
    else:
        log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

    # Automazione completa: se attiva e la prenotazione e' riuscita, prova a inviare
    # DAVVERO l'offerta. Fail-safe assoluto: qualunque errore ferma solo questo
    # tentativo, notifica l'errore esatto, NON fa mai retry.
    offer_sent = False
    offer_error = None
    if MAKEOFFER_LIVE_MODE and prepared:
        try:
            offer_sent, offer_error = execute_live_offer(
                card_asset_id, seller_slug, offer_amount_eur, prepared)
        except Exception as e:
            offer_error = f"eccezione imprevista: {e}"
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante offerta live -- {e}")
        if offer_sent:
            log(f"{player_name}: OFFERTA INVIATA CON SUCCESSO")
            pending_offers_count[0] += 1
            if player_slug:
                record_player_offer(player_slug)
        else:
            log(f"{player_name}: offerta automatica fallita -- {offer_error}")
    elif MAKEOFFER_LIVE_MODE and not prepared:
        offer_error = "prenotazione (prepareOffer) non riuscita, offerta automatica saltata"
        log(f"{player_name}: {offer_error}")

    send_would_have_bought_alert(player_name, player_slug, true_min_price, second_min_price,
                                  margin_percent, card_slug, excluded_league, prepared, is_in_season,
                                  live_mode=MAKEOFFER_LIVE_MODE, purchase_completed=offer_sent,
                                  purchase_error=offer_error, offer_amount_eur=offer_amount_eur)
    return True


SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    sender { ... on User { slug } }
    senderSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards {
        slug
        rarityTyped
        sport
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
        sportSeason { name }
        inSeasonEligible
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards { slug }
    }
  }
}
"""


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "matches_found": 0}
    seen_offer_status = set()

    def on_open(ws):
        log("Connesso al canale eventi Sorare, sottoscrizione in corso...")
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({
            "command": "message",
            "identifier": identifier,
            "data": json.dumps(subscription_payload),
        }))

    def on_message(ws, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        msg_type = message.get('type')
        if msg_type in ('welcome', 'ping'):
            return
        if msg_type == 'confirm_subscription':
            log("Sottoscrizione confermata, in ascolto...")
            return
        if msg_type == 'reject_subscription':
            log(f"ERRORE: sottoscrizione rifiutata: {message}")
            return

        payload = message.get('message')
        if not payload:
            return
        if payload.get('errors'):
            log(f"ERRORE GraphQL nella subscription: {payload['errors']}")
            return

        stats["received"] += 1
        offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
        if not offer:
            return

        offer_id = offer.get('id') or ''
        if not offer_id.startswith('SingleSaleOffer:'):
            return

        offer_status = offer.get('status')
        dedup_key = (offer_id, offer_status)
        if dedup_key in seen_offer_status:
            return
        seen_offer_status.add(dedup_key)

        if offer_status != 'opened':
            return

        seller_slug = ((offer.get('sender') or {}).get('slug') or '').lower()
        if seller_slug in BLACKLISTED_SELLER_SLUGS:
            return
        if seller_slug in BLACKLISTED_MAKEOFFER_MANAGER_SLUGS:
            return  # blacklist manager SOLO per questo bot -- stesso comportamento di
            # BLACKLISTED_SELLER_SLUGS: qui evitiamo solo di scatenare una valutazione
            # QUANDO E' PROPRIO LUI a pubblicare l'annuncio-trigger; il suo prezzo conta
            # comunque nel calcolo del vero minimo/margine tramite get_bucket_prices
            # (query separata, non filtra questi slug) -- l'esclusione vera dall'ACQUISTO
            # avviene in evaluate_event, vedi controllo su true_min_seller_slug piu' sotto.

        sender_side = offer.get('senderSide') or {}
        receiver_side = offer.get('receiverSide') or {}
        if receiver_side.get('anyCards'):
            return  # scambio carta-per-carta

        price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
        if price_eur is None:
            return

        sender_cards = sender_side.get('anyCards') or []
        if len(sender_cards) > 1:
            return  # bundle multi-carta, prezzo per-carta non ricavabile

        for card in sender_cards:
            if card.get('rarityTyped') != 'limited':
                continue
            if card.get('sport') != 'FOOTBALL':
                continue
            is_in_season = bool(card.get('inSeasonEligible'))
            if not is_in_season and not CHECK_CLASSIC:
                continue  # modalita' base: SOLO in season

            player = card.get('anyPlayer') or {}
            player_slug = player.get('slug')
            player_name = player.get('displayName', player_slug)
            card_slug = card.get('slug')
            league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
            if not player_slug:
                continue

            stats["processed"] += 1
            found = evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate,
                                    league_slug, offer_id, seller_slug, is_in_season)
            if found:
                stats["matches_found"] += 1
                log(f"Casi trovati finora: {stats['matches_found']}/{MAKEOFFER_TARGET_MATCHES}")
                if stats["matches_found"] >= MAKEOFFER_TARGET_MATCHES:
                    ws.close()

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: "
            f"{stats['received']}, carte in season elaborate: {stats['processed']}, "
            f"casi validi trovati: {stats['matches_found']}/{MAKEOFFER_TARGET_MATCHES}")

    ws = websocket.WebSocketApp(
        WS_URL,
        header=[f"Cookie: {COOKIES}"] if COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    timer = threading.Timer(LISTEN_SECONDS, ws.close)
    timer.daemon = True
    timer.start()

    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()

    return stats["matches_found"]


def main():
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    modalita = "\u26A0\uFE0F OFFERTE REALI AUTOMATICHE ATTIVE \u26A0\uFE0F" if MAKEOFFER_LIVE_MODE else "solo diagnostica, nessun acquisto reale"
    log(f"MakeOffer Sorare -- MODALITA': {modalita}")
    log(f"Fascia prezzo {MAKEOFFER_MIN_PRICE_EUR:.2f}-{MAKEOFFER_MAX_PRICE_EUR:.2f}EUR, "
        f"margine richiesto {MAKEOFFER_MARGIN_FRACTION:.0%}, target casi da trovare: "
        f"{MAKEOFFER_TARGET_MATCHES}")
    log(f"Giocatori in blacklist manuale ({len(BLACKLISTED_PLAYER_SLUGS)}): "
        f"{sorted(BLACKLISTED_PLAYER_SLUGS)}")
    log(f"Manager in blacklist AutoBuy ({len(BLACKLISTED_MAKEOFFER_MANAGER_SLUGS)}): "
        f"{sorted(BLACKLISTED_MAKEOFFER_MANAGER_SLUGS)}")
    send_startup_msg()
    try:
        matches_found = run_listener(eth_rate)
        target_reached = matches_found >= MAKEOFFER_TARGET_MATCHES
        send_end_msg(matches_found, target_reached)
        if target_reached:
            log(f"Target raggiunto: {matches_found}/{MAKEOFFER_TARGET_MATCHES} casi trovati e "
                f"notificati -- esecuzione terminata.")
        else:
            log(f"Tempo di ascolto scaduto: {matches_found}/{MAKEOFFER_TARGET_MATCHES} casi "
                f"trovati -- esecuzione terminata.")
    finally:
        close_browser()


if __name__ == "__main__":
    main()
