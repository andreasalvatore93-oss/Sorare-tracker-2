import json
import os
import time
import datetime
import threading

import requests
import websocket  # pip install websocket-client
from playwright.sync_api import sync_playwright

# FIX 20/07 (tentativo dopo 6 ipotesi esaurite su unknown_fingerprint): usiamo curl_cffi
# al posto di requests per le chiamate GraphQL sensibili -- curl_cffi imita fedelmente
# l'impronta TLS/JA3 di Chrome, mentre requests ha una firma TLS riconoscibile come
# "libreria Python", indipendentemente dagli header HTTP che mandiamo (che sono gia'
# corretti, verificato). Molti sistemi anti-bot controllano l'impronta TLS a livello di
# handshake, non solo gli header applicativi -- ipotesi non ancora testata. Fallback
# automatico a requests normale se curl_cffi non e' installato (nessuna regressione se
# l'ipotesi risultasse sbagliata o la libreria non installabile).
try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# =====================================================================================
# AUTOBUY SORARE -- FASE 1 (SOLO DIAGNOSTICA, NESSUN ACQUISTO REALE)
# =====================================================================================
# Script SEPARATO da track.py, con workflow GitHub Actions dedicato (autobuy.yml), per non
# creare confusione tra i due bot.
#
# Obiettivo finale (fase 2, non ancora implementata): comprare in automatico SOLO carte In
# Season in una fascia di prezzo stretta, quando il margine sul secondo prezzo attuale e'
# abbastanza ampio da essere "senza dubbio" un affare -- a differenza di track.py, qui NON
# guardiamo affatto il floor storico, il calo % nel tempo, le vendite recenti ne' il
# "mercato sottile": l'unico confronto e' istantaneo, tra il prezzo minimo attuale e il
# secondo prezzo minimo attuale, entrambi sullo stesso bucket in_season.
#
# FASE 1 (questa versione): il bot NON compra nulla. Quando troverebbe un caso che
# rispetta tutti i criteri, manda una notifica Telegram che dice "lo avrei acquistato",
# cosi' l'utente puo' controllare a mano se il bot ha ragione prima di passare
# all'acquisto reale automatizzato (fase 2, richiede la firma Starkware delle mutation
# GraphQL di acquisto -- vedi note a parte, non ancora implementato).
#
# Esecuzione: SEMPRE manuale (workflow_dispatch), non su un cron continuo come track.py.
# Il bot ascolta finche' non trova il PRIMO caso che avrebbe acquistato, manda la notifica
# e si ferma (si riavvia a mano). Se scade il tempo di ascolto senza nessun caso valido,
# si ferma comunque e basta.
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    """FIX 20/07 (confermato dall'utente con screenshot: il CSRF token cambia ad
    OGNI refresh della pagina, per design -- un valore statico in SORARE_CSRF
    diventa obsoleto quasi subito e causa 401 'You should log in'). Il cookie
    stesso contiene un campo 'csrftoken=...' che coincide esattamente con
    l'header x-csrf-token mandato nella stessa richiesta -- lo estraiamo da li'
    ogni volta che il cookie viene aggiornato, invece di tenere un secret CSRF
    separato che scade subito. Fallback su SORARE_CSRF se il cookie non lo contiene."""
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# --- FASE 2 (automazione completa, 19/07) ---
# Interruttore attivato via input workflow AUTOBUY_LIVE_MODE (env var, default "no" ->
# fase 1, solo diagnostica come sempre). Se valorizzato a "si", il bot COMPRA DAVVERO
# quando trova un caso valido: firma la mutation con la password del wallet (secret
# SORARE_WALLET_PASSWORD) e chiama AcceptOfferMutation. Fail-safe assoluto in ogni punto
# del flusso: qualunque errore (prenotazione, chiave cifrata, firma, accept) ferma SOLO
# quel tentativo, notifica l'errore esatto, non fa mai retry ne' tentativi alternativi.
AUTOBUY_LIVE_MODE = os.environ.get('AUTOBUY_LIVE_MODE', 'no').strip().lower() in ('1', 'true', 'yes', 'si')
SORARE_WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')
# FIX 20/07 (dodicesima ipotesi): header device_fingerprint visto in una richiesta
# reale del browser -- MAI inviato finora dal bot, diverso dal fingerprint restituito
# da prepareAcceptOffer (quello e' fisso/di operazione, questo sembra di device/sessione)
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessa blacklist manager di track.py (venditori solo ETH o esplicitamente esclusi
# dall'utente) -- non ha senso valutare/comprare da questi annunci.
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}

# Giocatori da IGNORARE completamente in questo bot (workaround manuale al posto del
# controllo coverageStatus, che non e' utilizzabile via GraphQL -- vedi note progetto).
# Lista letta da un file DEDICATO a questo bot (sorare_autobuy_blacklist.txt, nella root
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


BLACKLIST_FILE_PATH = os.environ.get('BLACKLIST_FILE_PATH', 'sorare_autobuy_blacklist.txt')
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
# giocatori ma su un file SEPARATO (sorare_autobuy_manager_blacklist.txt, nella root del
# repo, un manager_slug per riga) -- non lo stesso file dei giocatori, per tenere le due
# liste distinte e leggibili. Non tocca in alcun modo BLACKLISTED_SELLER_SLUGS (quella
# hardcoded, storica, condivisa con track.py) ne' track.py/crafted_card_scanner.py: file
# e lista completamente separati, validi SOLO per autobuy_sorare.py. Configurabile anche
# via env var BLACKLISTED_MANAGER_SLUGS (slug separati da virgola, per un'aggiunta rapida
# da workflow), che si SOMMA al contenuto del file senza sostituirlo -- e viene anche
# scritta/committata sul file per restare attiva nelle run future (stesso meccanismo gia'
# usato per blacklisted_player_slugs, vedi step dedicato in autobuy.yml).
MANAGER_BLACKLIST_FILE_PATH = os.environ.get(
    'MANAGER_BLACKLIST_FILE_PATH', 'sorare_autobuy_manager_blacklist.txt')
BLACKLISTED_AUTOBUY_MANAGER_SLUGS = _load_slug_list_file(
    MANAGER_BLACKLIST_FILE_PATH, 'blacklist manager')
_extra_blacklisted_managers = os.environ.get('BLACKLISTED_MANAGER_SLUGS', '')
if _extra_blacklisted_managers.strip():
    BLACKLISTED_AUTOBUY_MANAGER_SLUGS |= {
        s.strip().lower() for s in _extra_blacklisted_managers.split(',') if s.strip()
    }

# --- Parametri regolabili (fase di test, vedi autobuy.yml per gli input del workflow) ---
# Fascia di prezzo dell'ANNUNCIO che scatena la valutazione: default 1-5EUR, ma regolabile
# fino a un tetto piu' alto (es. 20EUR) durante i test.
AUTOBUY_MIN_PRICE_EUR = float(os.environ.get('AUTOBUY_MIN_PRICE_EUR', '1'))
AUTOBUY_MAX_PRICE_EUR = float(os.environ.get('AUTOBUY_MAX_PRICE_EUR', '30'))

# Margine minimo richiesto tra il prezzo minimo attuale e il secondo prezzo minimo attuale
# (stesso bucket in_season), es. 0.15 = 15%.
AUTOBUY_MARGIN_FRACTION = float(os.environ.get('AUTOBUY_MARGIN_FRACTION', '0.20'))

# Per quanti secondi restare in ascolto ad ogni esecuzione, se non si verifica prima un caso
# valido (il bot si ferma comunque al primo caso trovato).
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '18000'))
LISTEN_SECONDS = min(18000, LISTEN_SECONDS)  # tetto massimo 5h, indipendentemente dall'input

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
AUTOBUY_TARGET_MATCHES = int(os.environ.get('AUTOBUY_TARGET_MATCHES', '5'))
AUTOBUY_TARGET_MATCHES = max(1, min(10, AUTOBUY_TARGET_MATCHES))

# Diagnostica: se attiva, logga info aggiuntive sul confronto in_season/classic per ogni
# giocatore valutato (lega rilevata, quanti annunci classic trovati, ecc.) -- utile solo
# per verificare che la nuova logica scatti davvero come previsto, di default spenta.
AUTOBUY_DIAGNOSTIC = os.environ.get('AUTOBUY_DIAGNOSTIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')

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
PURCHASE_LOG_PATH = os.environ.get('PURCHASE_LOG_PATH', 'autobuy_purchases.json')
PLAYER_COOLDOWN_HOURS = 24


def _load_purchase_log():
    """Ritorna {player_slug: iso_timestamp_ultimo_acquisto}. File mancante o corrotto ->
    dizionario vuoto (fail-safe: non blocchiamo mai gli acquisti solo perche' il file di
    log non si legge)."""
    try:
        with open(PURCHASE_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"[purchase log] errore lettura {PURCHASE_LOG_PATH}, ignorato: {e}")
        return {}


def _save_purchase_log(log_data):
    try:
        with open(PURCHASE_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"[purchase log] errore scrittura {PURCHASE_LOG_PATH}: {e}")


def is_player_in_cooldown(player_slug):
    """True se player_slug e' stato acquistato meno di PLAYER_COOLDOWN_HOURS fa."""
    purchase_log = _load_purchase_log()
    last_purchase_iso = purchase_log.get(player_slug)
    if not last_purchase_iso:
        return False
    try:
        last_purchase = datetime.datetime.fromisoformat(last_purchase_iso)
    except ValueError:
        return False
    elapsed_hours = (datetime.datetime.now(datetime.timezone.utc) - last_purchase).total_seconds() / 3600
    return elapsed_hours < PLAYER_COOLDOWN_HOURS


def record_player_purchase(player_slug):
    """Da chiamare SOLO dopo un acquisto REALMENTE completato (fase 2, non ancora attiva
    in questo script -- funzione pronta per quando si collega l'automazione completa)."""
    purchase_log = _load_purchase_log()
    purchase_log[player_slug] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_purchase_log(purchase_log)
    log(f"[purchase log] registrato acquisto di {player_slug}, cooldown {PLAYER_COOLDOWN_HOURS}h")


# --- Cache "mercato troppo sottile" (richiesta esplicita utente, 19/07) ---
# Ottimizzazione velocita': se un giocatore e' gia' stato scartato dal controllo
# liquidita' (count_recent_transactions, vedi piu' sotto), rifare la stessa query
# GraphQL ogni volta che ricompare e' inutile -- il numero di transazioni recenti non
# cambia abbastanza in fretta da giustificare una riverifica immediata. Cache separata dal
# purchase log (scopo diverso: qui non e' un acquisto, e' solo un giocatore da ri-provare
# piu' avanti), persistita su file JSON per lo stesso motivo del purchase log (il
# workflow riparte da zero ad ogni esecuzione). Se la finestra scade, il giocatore torna
# ad essere valutato normalmente (nuova query, nuovo esito possibile).
THIN_MARKET_CACHE_PATH = os.environ.get('THIN_MARKET_CACHE_PATH', 'autobuy_thin_market_cache.json')
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


# FIX 20/07 (decima ipotesi, dopo che tutte le altre 9 sono fallite su unknown_fingerprint):
# usare un vero browser Chrome headless (Playwright) per le tre chiamate GraphQL
# CRITICHE dell'acquisto (prepareAcceptOffer, fetchEncryptedPrivateKey, acceptOffer),
# invece di curl_cffi. Il resto del bot (ricerca carte, prezzi, liquidita') continua a
# usare curl_cffi via graphql_query() come prima, senza modifiche.
_playwright_instance = None
_playwright_browser = None
_playwright_page = None


def get_browser_page():
    """Apre un browser Chrome invisibile (headless) con i cookie di sessione
    gia' pronti, cosi' sembra un utente vero gia' loggato. Riusa lo stesso
    browser per tutta la run (non lo riapre ogni volta).
    FIX 20/07 (undicesima ipotesi, dopo che Playwright puro non ha risolto
    unknown_fingerprint): oltre a sembrare un browser vero, proviamo a fargli
    NAVIGARE un po' prima della chiamata critica -- non solo la home, ma
    anche una pagina di mercato reale, con piccole pause. Ipotesi: un
    eventuale fingerprint di device/sessione generato da JS potrebbe
    richiedere che il browser abbia gia' 'vissuto' un minimo di navigazione
    reale (localStorage/IndexedDB popolati) prima che il server lo consideri
    legittimo."""
    global _playwright_instance, _playwright_browser, _playwright_page
    if _playwright_page is not None:
        return _playwright_page

    _playwright_instance = sync_playwright().start()
    _playwright_browser = _playwright_instance.chromium.launch(headless=True)
    context = _playwright_browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
    )

    # Inietta i cookie di Sorare (stessa stringa che usiamo gia' in COOKIES)
    # trasformandoli nel formato che Playwright vuole (lista di dict)
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
        log(f"[playwright] iniettati {len(cookie_pairs)} cookie nel context "
            f"(diagnostica: {[c['name'] for c in cookie_pairs][:5]}...)")
    else:
        log("[playwright] ATTENZIONE: nessun cookie iniettato (COOKIES vuoto o malformato)")

    page = context.new_page()

    # Navigazione "riscaldamento" (undicesima ipotesi): home -> pausa -> pagina
    # di mercato reale -> pausa, prima di essere pronti per la chiamata critica.
    # FIX 20/07: networkidle andava SEMPRE in timeout (30s) su GitHub Actions --
    # probabilmente risorse di terze parti (analytics/tracking) che non
    # completano mai il caricamento in un ambiente headless/datacenter.
    # Passato a domcontentloaded, molto piu' affidabile e comunque sufficiente
    # per far eseguire eventuali script di fingerprinting nella pagina.
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
    """Chiude il browser alla fine (importante per non lasciare processi
    appesi e sprecare tempo del workflow GitHub Actions)."""
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
    """Fa una chiamata GraphQL usando fetch() DENTRO un vero browser Chrome
    (non con curl_cffi/requests) -- cosi' la richiesta esce con l'impronta
    autentica del browser (TLS, JS engine, eventuali controlli antibot lato
    client), impossibile da imitare fino in fondo con librerie Python.
    Usata SOLO per le tre chiamate critiche dell'acquisto (prepareAcceptOffer,
    fetchEncryptedPrivateKey, acceptOffer) -- ipotesi 20/07 per unknown_fingerprint."""
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
    """Versione semplificata (stessa base di track.py) del client GraphQL con backoff sui
    429 -- niente rilevamento "ban a tempo fisso" qui, il volume di query di questo bot e'
    molto piu' basso (esecuzioni brevi, manuali).
    FIX 20/07 (ipotesi unknown_fingerprint): aggiunti header custom mancanti, confermati
    dal vivo ispezionando una richiesta reale di PrepareAcceptOfferMutation dal browser
    (sorare-client, sorare-version, sorare-build, sec-fetch-*, accept-language, origin,
    referer) -- il bot prima mandava SOLO Content-Type/Cookie/x-csrf-token/User-Agent,
    mancavano tutti questi header che identificano la richiesta come proveniente da un
    client Web legittimo. sorare-version/sorare-build sono valori specifici di un
    deployment del sito (cambiano ad ogni release) -- usiamo gli ultimi visti dal vivo
    come default ragionevole, ma potrebbero invecchiare: se il problema persiste,
    andrebbero riletti da una richiesta fresca del browser."""
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
    if AUTOBUY_DIAGNOSTIC and buckets['classic']:
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


CARD_COVERAGE_QUERY = """
query CardCoverageQuery($slug: String!) {
  anyCard(slug: $slug) {
    slug
    coverageStatus
    openForGameStatsCompetitions {
      slug
    }
  }
}
"""


def get_card_coverage_status(card_slug):
    """FIX 19/07 (caso Aoto Nanamure, poi Benji Michel): coverageStatus non esiste
    sull'interfaccia AnyCardInterface usata da LIVE_OFFERS_QUERY/SUBSCRIPTION_QUERY (vedi
    errore GraphQL osservato dal vivo), ma ESISTE sul tipo concreto Card raggiunto tramite
    la query root anyCard(slug: ...) -- confermato ispezionando la risposta reale della
    pagina carta (query interna del sito). anyCard(slug:...) ritorna pero' il tipo
    dell'INTERFACCIA (AnyCardInterface), quindi il campo va richiesto tramite un inline
    fragment esplicito "... on Card { coverageStatus }" e non come campo diretto -- senza
    il fragment, GraphQL cerca coverageStatus sull'interfaccia stessa e fallisce sempre
    (bug osservato dal vivo, caso Benji Michel, 19/07). Per non rischiare di rompere di
    nuovo la subscription, questa query viene chiamata SOLO qui, come controllo aggiuntivo
    mirato sulla carta candidata, DOPO che il bot ha gia' trovato un margine valido -- non
    nel flusso critico del listener. Ritorna la stringa coverageStatus (es. 'FULL',
    'NOT_COVERED') o None se la query fallisce per qualunque motivo (in quel caso, per
    sicurezza, NON blocchiamo l'acquisto solo per questo controllo: vedi chiamata in
    evaluate_event)."""
    try:
        data = graphql_query(CARD_COVERAGE_QUERY, {"slug": card_slug})
        if data.get('errors'):
            log(f"[coverage check] errore per {card_slug}: {data['errors']}")
            return None
        card = (data.get('data') or {}).get('anyCard') or {}
        return card.get('coverageStatus')
    except Exception as e:
        log(f"[coverage check] eccezione per {card_slug}: {e}")
        return None


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


EXCHANGE_RATE_QUERY = """
query ExchangeRateQuery {
  config {
    exchangeRate { id }
  }
}
"""


def get_exchange_rate_id():
    """Recupera l'id del tasso di cambio corrente (serve a PrepareAcceptOfferMutation),
    stessa query ExchangeRateQuery vista nel flusso reale di acquisto in browser."""
    try:
        data = graphql_query(EXCHANGE_RATE_QUERY)
        return (((data.get('data') or {}).get('config') or {}).get('exchangeRate') or {}).get('id')
    except Exception as e:
        log(f"[prepare accept] errore lettura tasso di cambio: {e}")
        return None


PREPARE_ACCEPT_OFFER_MUTATION = """
mutation PrepareAcceptOfferMutation($input: prepareAcceptOfferInput!) {
  prepareAcceptOffer(input: $input) {
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
    primaryOffer { id }
  }
}
"""


def classify_prepare_accept_error(root_errors, payload_errors):
    """Classifica gli errori di PrepareAcceptOfferMutation/AcceptOfferMutation in categorie
    note, per poter loggare/notificare in modo chiaro E per dare a fase 2 (automazione
    completa) un segnale univoco su cosa e' successo. Finche' non osserviamo dal vivo i
    messaggi esatti per fondi insufficienti / valuta non supportata / offerta scaduta,
    questa funzione e' VOLUTAMENTE conservativa: qualunque errore non riconosciuto finisce
    in 'sconosciuto', mai in una categoria che potrebbe indurre un retry o un tentativo
    alternativo automatico. Principio fisso per fase 2: ogni categoria = STOP, mai retry.
    Ritorna (category, raw_errors) dove category e' una delle stringhe:
    'fondi_insufficienti', 'valuta_non_supportata', 'offerta_non_disponibile',
    'nessun_errore', 'sconosciuto'."""
    all_errors = list(root_errors or []) + list(payload_errors or [])
    if not all_errors:
        return 'nessun_errore', all_errors

    combined_text = ' '.join(
        str(e.get('message', '')) + ' ' + str(e.get('extensions', {}).get('code', ''))
        for e in all_errors if isinstance(e, dict)
    ).lower()

    # Parole chiave PROVVISORIE (da confermare/affinare al primo caso reale osservato) --
    # non togliamo mai un errore dalla categoria 'sconosciuto' solo per somiglianza vaga.
    if any(kw in combined_text for kw in
           ('insufficient', 'not_enough', 'balance', 'fondi', 'saldo')):
        return 'fondi_insufficienti', all_errors
    if any(kw in combined_text for kw in
           ('currency', 'payment_method', 'unsupported', 'valuta')):
        return 'valuta_non_supportata', all_errors
    if any(kw in combined_text for kw in
           ('not_found', 'expired', 'already', 'sold', 'unavailable', 'not_available')):
        return 'offerta_non_disponibile', all_errors

    return 'sconosciuto', all_errors


def prepare_accept_offer(offer_id):
    """FASE 2 (prima meta'): 'prenota'/valida l'offerta lato server chiamando la stessa
    PrepareAcceptOfferMutation usata dal sito quando l'utente clicca 'Acquista', PRIMA
    ancora che l'utente clicchi -- riduce la finestra in cui un altro manager potrebbe
    comprare la carta nel frattempo. NON firma nulla (nessuna chiave privata coinvolta):
    restituisce solo l'operationHash/nonce che servirebbero alla firma, dati utili da
    includere nella notifica per velocizzare la conferma manuale. Ritorna il dict
    'authorizations[0].request' (o None se la chiamata fallisce) -- il click finale
    dell'utente sul sito resta INVARIATO e necessario (fase 2 = opzione "conferma manuale",
    vedi nota progetto)."""
    exchange_rate_id = get_exchange_rate_id()
    if not exchange_rate_id:
        log("[prepare accept] exchange_rate_id non ottenuto, impossibile procedere")
        return None
    log(f"[prepare accept] exchange_rate_id={exchange_rate_id}")
    variables = {
        "input": {
            "offerId": offer_id,
            "attemptReference": None,
            "settlementInfo": {
                "currency": "EUR",
                "exchangeRateId": exchange_rate_id,
                "paymentMethod": "WALLET",
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        }
    }
    try:
        data = graphql_query_via_browser(PREPARE_ACCEPT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('prepareAcceptOffer') or {}
        payload_errors = payload.get('errors') or []

        if root_errors or payload_errors:
            category, all_errors = classify_prepare_accept_error(root_errors, payload_errors)
            log(f"[prepare accept] fallita, categoria='{category}', errori={all_errors}")
            return None

        log(f"[prepare accept] risposta grezza: {json.dumps(data)[:1500]}")
        primary_offer = payload.get('primaryOffer') or {}
        log(f"[prepare accept] primaryOffer={primary_offer}")
        auths = payload.get('authorizations') or []
        if not auths:
            log("[prepare accept] nessuna authorization restituita, categoria='sconosciuto'")
            return None
        # Restituiamo fingerprint + request (con __typename incluso) -- servono ENTRAMBI a
        # sign_authorization_via_node/signAuthorizationRequest quando si attivera' la firma
        # automatica (opzione 1, non ancora collegata a nulla qui). Oggi 'fingerprint' non
        # viene ancora usato da nessuna parte del bot.
        auth = auths[0]
        request = dict(auth.get('request') or {})
        request['__typename'] = 'MangopayWalletTransferAuthorizationRequest'
        # FIX 19/07 (velocizzazione sniping): esponiamo anche exchange_rate_id gia'
        # ottenuto qui, cosi' execute_live_purchase puo' riusarlo invece di rifare la
        # stessa query GraphQL una seconda volta -- ogni millisecondo conta nello sniping.
        # FIX 20/07 (nuovo tentativo unknown_fingerprint): espongo anche l'id completo
        # dell'authorization ("TokenService::Core::MangopayWalletTransferAuthorization:
        # UUID"), diverso dal fingerprint (che e' sempre lo stesso valore fisso in ogni
        # test, confermato anche nel caso riuscito -- probabilmente identifica il TIPO
        # di authorization, non l'istanza specifica). L'id invece cambia sempre, ad ogni
        # chiamata -- e' l'ipotesi piu' plausibile di identificatore reale da correlare
        # con fetchEncryptedPrivateKey.
        return {'fingerprint': auth.get('fingerprint'), 'request': request,
                'exchange_rate_id': exchange_rate_id, 'authorization_id': auth.get('id')}
    except Exception as e:
        log(f"[prepare accept] eccezione: {e}")
        return None


def sign_authorization_via_node(password, encrypted_private_key, iv, salt, authorization_request):
    """FASE 2 SECONDA META' (opzione 1, NON ANCORA ATTIVATA da nessuna parte del bot --
    questa funzione esiste ma non e' chiamata in evaluate_event/main; e' il "cablaggio
    pronto" per quando si decidera' di passare all'acquisto davvero automatico).

    Richiama sorare-sign/decrypt_and_sign.js (Node.js) via subprocess, passandogli via
    stdin un JSON con: password del wallet, i tre campi restituiti da
    FetchEncryptedPrivateKey (encrypted_private_key/iv/salt), e l'intero oggetto
    authorization_request (incluso __typename) restituito da prepare_accept_offer.

    Lo script Node decripta la chiave privata (PBKDF2 + AES-GCM, stesso algoritmo usato
    dal sito sorare.com) e poi chiama @sorare/crypto.signAuthorizationRequest per
    ottenere la signature -- funzione ufficiale confermata nel repo pubblico
    github.com/sorare/api/examples/authorizations.js.

    Ritorna la stringa signature (da usare in approvals[0].mangopayWalletTransferApproval)
    oppure None se qualcosa fallisce (password sbagliata, script non trovato, dipendenze
    npm non installate, ecc.) -- logga sempre il motivo."""
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

# FIX 20/07 (nuovo tentativo, dopo che cache+header non hanno risolto unknown_fingerprint):
# proviamo a passare l'id completo dell'authorization (o il fingerprint) come possibile
# parametro atteso da fetchEncryptedPrivateKey -- finora chiamata sempre con input
# completamente vuoto. Se il campo non esiste nello schema, GraphQL rispondera' con un
# errore esplicito del tipo "Field 'xxx' is not defined" (stesso pattern gia' visto con
# coverageStatus), in tal caso ripieghiamo silenziosamente sulla chiamata con input vuoto
# (comportamento precedente, per non introdurre una regressione se l'ipotesi e' sbagliata).
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

# FIX 20/07 (scoperta chiave, confermata dal vivo su un acquisto reale completato con
# successo): il flusso REALE del browser va DIRETTAMENTE da PrepareAcceptOfferMutation
# ad AcceptOfferMutation -- fetchEncryptedPrivateKey non compare MAI nel network
# catturato durante un acquisto vero, nemmeno subito dopo aver inserito la password nel
# popup "Sblocca il tuo wallet" (0 richieste GraphQL in quel momento). La chiave e'
# quindi probabilmente decriptata/tenuta in memoria LOCALE dal browser per tutta la
# sessione, non richiesta al server ad ogni singolo acquisto. Il bot invece la
# richiamava ad ogni tentativo -- comportamento anomalo rispetto al pattern reale,
# sospettato causa di "unknown_fingerprint". Fix: cache in-memory a livello di modulo,
# la chiave viene recuperata dal server SOLO alla prima chiamata della sessione/run,
# poi riusata per tutti gli acquisti successivi.
_encrypted_key_cache = {}


def fetch_encrypted_private_key(authorization_id=None, fingerprint=None, offer_id=None):
    """Recupera encryptedPrivateKey/iv/salt tramite la mutation FetchEncryptedPrivateKey
    (nome/struttura CONFERMATI dal vivo il 19/07 catturando via DevTools la vera
    richiesta che il sito manda durante un'offerta reale -- NON e' una query su
    currentUser.sorarePrivateKey, quella torna sempre null). Ritorna il dict
    {encryptedPrivateKey, iv, salt} o None se fallisce per qualunque motivo.
    CACHATA in memoria (vedi nota sopra): la query GraphQL viene fatta solo la prima
    volta per l'intera esecuzione del bot, le chiamate successive riusano lo stesso
    risultato senza contattare di nuovo il server.
    FIX 20/07 (nona ipotesi -- body-based scartato in precedenza, schema rifiuta
    authorizationId/fingerprint/offerId come campi dell'input): proviamo stavolta a
    passare fingerprint/authorizationId come HEADER HTTP della richiesta invece che nel
    body GraphQL -- variante concettualmente diversa, mai testata finora."""
    if 'key_data' in _encrypted_key_cache:
        return _encrypted_key_cache['key_data']

    extra_headers = {}
    if fingerprint:
        extra_headers['fingerprint'] = fingerprint
        extra_headers['Fingerprint'] = fingerprint
        extra_headers['x-fingerprint'] = fingerprint
    if authorization_id:
        extra_headers['authorization-id'] = authorization_id

    try:
        data = graphql_query_via_browser(FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION, {"input": {}})
        if data.get('errors'):
            log(f"[chiave cifrata] errore GraphQL: {data['errors']}")
            log(f"[chiave cifrata] risposta grezza completa (diagnostica): {json.dumps(data)}")
            return None
        payload = (data.get('data') or {}).get('fetchEncryptedPrivateKey') or {}
        payload_errors = payload.get('errors') or []
        if payload_errors:
            log(f"[chiave cifrata] errore payload: {payload_errors}")
            log(f"[chiave cifrata] risposta grezza completa (diagnostica): {json.dumps(data)}")
            return None
        key_data = payload.get('sorarePrivateKey')
        if not key_data:
            log("[chiave cifrata] sorarePrivateKey assente nella risposta")
            return None
        log("[chiave cifrata] recuperata dal server e messa in cache per il resto della run "
            "(non verra' richiesta di nuovo finche' il bot non riparte)")
        _encrypted_key_cache['key_data'] = key_data
        return key_data
    except Exception as e:
        log(f"[chiave cifrata] eccezione: {e}")
        return None


ACCEPT_OFFER_MUTATION = """
mutation AcceptOfferMutation($input: acceptOfferInput!) {
  acceptOffer(input: $input) {
    errors { message }
  }
}
"""


def accept_offer(offer_id, fingerprint, nonce, signature, exchange_rate_id):
    """Ultimo passo del flusso di acquisto reale: completa DAVVERO l'operazione.
    Fail-safe assoluto -- qualunque errore ritorna (False, categoria, messaggio_errore),
    MAI un'eccezione non gestita, MAI un retry automatico. La categoria riusa
    classify_prepare_accept_error (stessa logica gia' usata per prepare_accept_offer:
    fondi_insufficienti/valuta_non_supportata/offerta_non_disponibile/sconosciuto) cosi'
    l'utente capisce SUBITO dal log/notifica il tipo di problema, senza dover decifrare
    il messaggio GraphQL grezzo."""
    variables = {
        "input": {
            "offerId": offer_id,
            "migrationData": None,
            "approvals": [{
                "fingerprint": fingerprint,
                "mangopayWalletTransferApproval": {
                    "nonce": nonce,
                    "signature": signature,
                },
            }],
            "settlementInfo": {
                "currency": "EUR",
                "exchangeRateId": exchange_rate_id,
                "paymentMethod": "WALLET",
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        },
    }
    try:
        data = graphql_query_via_browser(ACCEPT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('acceptOffer') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_prepare_accept_error(root_errors, payload_errors)
            log(f"[accept offer] fallita, categoria='{category}', errori={all_errors}")
            return False, category, str(all_errors)
        # FIX 20/07: il campo 'offer' non esiste piu' nello schema acceptOfferPayload
        # (errore "Field 'offer' doesn't exist" osservato dal vivo) -- probabilmente
        # Sorare ha cambiato la struttura del payload di risposta. Senza introspection
        # disponibile (disabilitata su Sorare) non possiamo vedere il nome esatto del
        # campo sostitutivo -- determiniamo il successo SOLO dall'assenza di errori
        # (root_errors/payload_errors), gia' verificata sopra.
        log("[accept offer] successo (nessun errore restituito dal server)")
        return True, None, None
    except Exception as e:
        log(f"[accept offer] eccezione: {e}")
        return False, 'eccezione', str(e)


def execute_live_purchase(offer_id, prepared):
    """Orchestrazione FASE 2 completa (automazione totale, attiva SOLO se
    AUTOBUY_LIVE_MODE e' 'si'): chiave cifrata -> firma -> accept. Fail-safe assoluto:
    ritorna (True, None) se l'acquisto e' andato a buon fine, (False, motivo_esatto)
    altrimenti -- MAI retry, MAI tentativi alternativi, un solo tentativo secco. Ogni
    step logga il proprio esito (successo o fallimento) per poter capire SUBITO dai log
    quale step specifico e' fallito, senza dover dedurlo dal messaggio finale.
    IMPORTANTE (20/07): fetch_encrypted_private_key() va chiamata SOLO ora, DOPO che
    prepare_accept_offer() e' gia' stata completata con successo (vedi nota in
    evaluate_event) -- un tentativo di parallelizzare le due chiamate ha causato
    "unknown_fingerprint" in 3 test su 3 dal vivo, il fingerprint deve esistere
    lato server prima che questa chiamata possa risolversi."""
    log(f"[acquisto live] avvio -- offer_id={offer_id}")

    if not SORARE_WALLET_PASSWORD:
        log("[acquisto live] STOP: SORARE_WALLET_PASSWORD non impostata")
        return False, "SORARE_WALLET_PASSWORD non impostata"

    fingerprint = prepared.get('fingerprint')
    request = prepared.get('request') or {}
    nonce = request.get('nonce')
    authorization_id = prepared.get('authorization_id')

    key_data = fetch_encrypted_private_key(
        authorization_id=authorization_id, fingerprint=fingerprint, offer_id=offer_id)
    if not key_data:
        log("[acquisto live] STOP: chiave cifrata non recuperata (vedi log [chiave cifrata] sopra)")
        return False, "impossibile recuperare la chiave cifrata (fetchEncryptedPrivateKey)"
    log("[acquisto live] step 1/3 OK: chiave cifrata recuperata")

    signature = sign_authorization_via_node(
        SORARE_WALLET_PASSWORD,
        key_data.get('encryptedPrivateKey'),
        key_data.get('iv'),
        key_data.get('salt'),
        request,
    )
    if not signature:
        log("[acquisto live] STOP: firma fallita (vedi log [firma Node] sopra per il dettaglio esatto)")
        return False, "firma fallita (vedi log [firma Node] per il dettaglio esatto)"
    log("[acquisto live] step 2/3 OK: firma generata")

    # FIX 19/07 (velocizzazione sniping): riusiamo l'exchange_rate_id gia' ottenuto da
    # prepare_accept_offer invece di rifare la stessa query GraphQL una seconda volta --
    # una chiamata di rete in meno nel percorso critico dell'acquisto.
    exchange_rate_id = prepared.get('exchange_rate_id')
    if not exchange_rate_id:
        log("[acquisto live] STOP: exchange_rate_id non disponibile da prepared")
        return False, "exchange_rate_id non disponibile"

    success, category, error = accept_offer(offer_id, fingerprint, nonce, signature, exchange_rate_id)
    if not success:
        log(f"[acquisto live] STOP: step 3/3 fallito, categoria='{category}'")
        return False, f"AcceptOfferMutation fallita [{category}]: {error}"
    log("[acquisto live] step 3/3 OK: acquisto completato")
    return True, None


def send_would_have_bought_alert(player_name, player_slug, price_eur, second_price, margin_percent,
                                  card_slug, excluded_league, prepared=None, is_in_season=True,
                                  live_mode=False, purchase_completed=False, purchase_error=None):
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
    if live_mode:
        if purchase_completed:
            titolo = "\U0001F916\U0001F4B0 <b>AutoBuy Sorare -- ACQUISTATO IN AUTOMATICO</b>"
            esito = "\u2705 <b>Acquisto completato con successo, nessuna azione richiesta.</b>\n\n"
        else:
            titolo = "\U0001F916\U0001F4B0 <b>AutoBuy Sorare -- ACQUISTO AUTOMATICO FALLITO</b>"
            esito = (f"\u274C <b>Acquisto automatico NON riuscito</b>: {purchase_error}\n"
                      f"Apri e valuta se confermare a mano.\n\n")
    else:
        titolo = "\U0001F916\U0001F4B0 <b>AutoBuy Sorare -- LO AVREI ACQUISTATO</b>"
        esito = "\u26A0\uFE0F Fase di test: nessun acquisto reale eseguito, controlla a mano.\n\n"
    msg_text = (
        f"{titolo}\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: {categoria}\n"
        f"Prezzo minimo attuale: {price_eur:.2f}EUR\n"
        f"Secondo prezzo attuale: {second_price:.2f}EUR (margine {margin_percent:.1%}, "
        f"soglia richiesta {AUTOBUY_MARGIN_FRACTION:.0%})\n\n"
        f"{prenotazione}"
        f"{esito}"
        f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
    )
    send_telegram_msg(msg_text)


def send_startup_msg():
    classic_msg = "\nModalita' CLASSIC attiva (tutti i campionati)" if CHECK_CLASSIC else ""
    intestazione = (
        "\U0001F916\u26A0\uFE0F <b>AutoBuy Sorare avviato -- ACQUISTO REALE AUTOMATICO ATTIVO</b>\n"
        if AUTOBUY_LIVE_MODE else
        "\U0001F916 <b>AutoBuy Sorare avviato</b> (solo diagnostica, nessun acquisto reale)\n"
    )
    send_telegram_msg(
        f"{intestazione}"
        f"Fascia prezzo: {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR\n"
        f"Margine richiesto: {AUTOBUY_MARGIN_FRACTION:.0%}\n"
        f"Ascolto per {LISTEN_SECONDS}s o fino al primo caso valido.{classic_msg}"
    )


def send_end_msg(matches_found, target_reached):
    esito = (
        f"\u2705 Target raggiunto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
        if target_reached else
        f"\u23F1 Tempo scaduto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
    )
    send_telegram_msg(
        f"\U0001F916 <b>AutoBuy Sorare terminato</b>\n"
        f"{esito}"
    )


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

    if player_slug and is_player_in_cooldown(player_slug):
        log(f"{player_name}: scarto -- gia' acquistato nelle ultime {PLAYER_COOLDOWN_HOURS}h "
            f"(protezione anti-svendita/infortunio, vedi autobuy_purchases.json)")
        return False

    if not (AUTOBUY_MIN_PRICE_EUR <= price_eur <= AUTOBUY_MAX_PRICE_EUR):
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
        if AUTOBUY_DIAGNOSTIC:
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
        if AUTOBUY_DIAGNOSTIC:
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
    # BLACKLISTED_AUTOBUY_MANAGER_SLUGS solo per questo bot) CONTANO nel confronto prezzi
    # (vedi get_bucket_prices/fetch_all_live_offers, nessuna delle due liste li filtra
    # li'), ma non compriamo mai da loro. Se il vero minimo attuale risulta essere
    # proprio un annuncio di uno di questi venditori, scartiamo il caso -- anche se
    # sembrerebbe "il miglior prezzo", non e' comprabile secondo le regole dell'utente.
    if true_min_seller_slug in BLACKLISTED_SELLER_SLUGS or \
            true_min_seller_slug in BLACKLISTED_AUTOBUY_MANAGER_SLUGS:
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
        f"margine {margin_percent:.1%} (soglia {AUTOBUY_MARGIN_FRACTION:.0%})")

    if margin_percent < AUTOBUY_MARGIN_FRACTION:
        return False

    log(f"AUTOBUY: {player_name} -- LO AVREI ACQUISTATO ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%})")

    # FIX 19/07 (velocizzazione sniping, richiesta esplicita utente): il coverage check
    # (get_card_coverage_status) e' stato RIMOSSO da qui -- fallisce SEMPRE con lo stesso
    # errore GraphQL ("Field 'coverageStatus' doesn't exist on type 'AnyCardInterface'",
    # mai risolto, vedi note progetto), quindi era una query di rete completamente
    # inutile che rallentava ogni singolo caso senza mai dare un risultato utile. La
    # workaround per il coverage resta la blacklist manuale giocatori (BLACKLISTED_
    # PLAYER_SLUGS), controllata all'inizio di questa funzione, PRIMA di spendere
    # qualunque query di rete -- unico meccanismo attivo per questo problema.

    # FIX 20/07 (REGRESSIONE TROVATA E CORRETTA): il tentativo precedente di
    # parallelizzare prepare_accept_offer() e fetch_encrypted_private_key() per
    # velocizzare l'acquisto ha introdotto un bug reale -- 3 casi su 3 in test dal vivo
    # hanno dato "unknown_fingerprint" con il log dell'errore che compariva PRIMA ancora
    # che la risposta di prepare_accept_offer fosse arrivata/loggata. fetchEncryptedPrivateKey
    # non riceve alcun fingerprint come parametro (chiamata con input vuoto), quindi
    # l'unica spiegazione coerente e' che il fingerprint debba esistere ED essere
    # REGISTRATO lato server PRIMA che la chiamata a fetchEncryptedPrivateKey possa
    # risolversi correttamente -- la sequenzialita' non era pigrizia del codice
    # originale, era un requisito reale del flusso. RIPRISTINATA la sequenza originale
    # (prima prepare, poi fetch, sempre in questo ordine, mai in parallelo).
    prepared = None
    if offer_id:
        prepared = prepare_accept_offer(offer_id)

        if prepared:
            nonce = (prepared.get('request') or {}).get('nonce')
            log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
        else:
            log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

    # FASE 2 (automazione completa): se attiva e la prenotazione e' riuscita, prova a
    # completare DAVVERO l'acquisto. Fail-safe assoluto: qualunque errore ferma solo
    # questo tentativo, notifica l'errore esatto, NON fa mai retry.
    purchase_completed = False
    purchase_error = None
    if AUTOBUY_LIVE_MODE and offer_id and prepared:
        try:
            purchase_completed, purchase_error = execute_live_purchase(
                offer_id, prepared)
        except Exception as e:
            # Ultima rete di sicurezza: qualunque eccezione imprevista qui (bug non
            # anticipato in uno degli step) NON deve far crashare l'intero bot ne'
            # lasciare lo stato incerto senza notifica -- si logga e si notifica come
            # fallimento, esattamente come ogni altro errore gestito.
            purchase_error = f"eccezione imprevista: {e}"
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante acquisto live -- {e}")
        if purchase_completed:
            log(f"{player_name}: ACQUISTO COMPLETATO CON SUCCESSO")
            if player_slug:
                record_player_purchase(player_slug)
        else:
            log(f"{player_name}: acquisto automatico fallito -- {purchase_error}")
    elif AUTOBUY_LIVE_MODE and offer_id and not prepared:
        purchase_error = "prenotazione (prepareAcceptOffer) non riuscita, acquisto automatico saltato"
        log(f"{player_name}: {purchase_error}")

    send_would_have_bought_alert(player_name, player_slug, true_min_price, second_min_price,
                                  margin_percent, card_slug, excluded_league, prepared, is_in_season,
                                  live_mode=AUTOBUY_LIVE_MODE, purchase_completed=purchase_completed,
                                  purchase_error=purchase_error)
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
        if seller_slug in BLACKLISTED_AUTOBUY_MANAGER_SLUGS:
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
                log(f"Casi trovati finora: {stats['matches_found']}/{AUTOBUY_TARGET_MATCHES}")
                if stats["matches_found"] >= AUTOBUY_TARGET_MATCHES:
                    ws.close()

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: "
            f"{stats['received']}, carte in season elaborate: {stats['processed']}, "
            f"casi validi trovati: {stats['matches_found']}/{AUTOBUY_TARGET_MATCHES}")

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
    modalita = "\u26A0\uFE0F ACQUISTO REALE AUTOMATICO ATTIVO \u26A0\uFE0F" if AUTOBUY_LIVE_MODE else "solo diagnostica, nessun acquisto reale"
    log(f"AutoBuy Sorare -- MODALITA': {modalita}")
    log(f"[network] curl_cffi (impronta TLS Chrome) {'ATTIVO' if _HAS_CURL_CFFI else 'NON DISPONIBILE, uso requests standard'}")
    csrf_source = "estratto dal cookie (csrftoken=...)" if _extract_csrf_from_cookie(COOKIES) else "da secret SORARE_CSRF (fallback)"
    log(f"[auth] CSRF token in uso: {csrf_source}, valore: {(CSRF_TOKEN or '')[:20]}...")
    log(f"Fascia prezzo {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR, "
        f"margine richiesto {AUTOBUY_MARGIN_FRACTION:.0%}, target casi da trovare: "
        f"{AUTOBUY_TARGET_MATCHES}")
    log(f"Giocatori in blacklist manuale ({len(BLACKLISTED_PLAYER_SLUGS)}): "
        f"{sorted(BLACKLISTED_PLAYER_SLUGS)}")
    log(f"Manager in blacklist AutoBuy ({len(BLACKLISTED_AUTOBUY_MANAGER_SLUGS)}): "
        f"{sorted(BLACKLISTED_AUTOBUY_MANAGER_SLUGS)}")
    send_startup_msg()
    try:
        matches_found = run_listener(eth_rate)
        target_reached = matches_found >= AUTOBUY_TARGET_MATCHES
        send_end_msg(matches_found, target_reached)
        if target_reached:
            log(f"Target raggiunto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati e "
                f"notificati -- esecuzione terminata.")
        else:
            log(f"Tempo di ascolto scaduto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi "
                f"trovati -- esecuzione terminata.")
    finally:
        close_browser()


if __name__ == "__main__":
    main()
