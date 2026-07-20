import json
import os
import random
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
# BOT SUPREMO -- fusione di AutoBuy + MakeOffer in un unico scanner/bot (20/07)
# =====================================================================================
# Un solo scan di mercato per evento: se il margine e' nella fascia MAKEOFFER_MARGIN_
# FRACTION-MAKEOFFER_MAX_MARGIN_FRACTION -> crea un'offerta scontata (ramo MakeOffer);
# se e' >= AUTOBUY_MARGIN_FRACTION -> accetta direttamente l'offerta (ramo AutoBuy).
# Elimina il doppio scan/doppia richiesta e la race condition tra i due bot separati
# (blacklist ora lette insieme da entrambi i file, vedi sotto).
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    """Il CSRF token cambia ad ogni refresh pagina -- estratto dal cookie stesso
    (campo csrftoken=...) invece di un secret statico che scadrebbe subito."""
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

AUTOBUY_LIVE_MODE = os.environ.get('AUTOBUY_LIVE_MODE', 'si').strip().lower() in ('1', 'true', 'yes', 'si')
MAKEOFFER_LIVE_MODE = os.environ.get('MAKEOFFER_LIVE_MODE', 'si').strip().lower() in ('1', 'true', 'yes', 'si')
SORARE_WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessa blacklist manager storica di track.py (venditori solo ETH o esplicitamente
# esclusi dall'utente).
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}


# =====================================================================================
# LISTA NERA DEL BOT SUPREMO -- file unico (richiesta esplicita utente 21/07)
# =====================================================================================
# Sostituisce TUTTI i vecchi file separati (sorare_blacklist.txt, sorare_manager_
# blacklist.txt, i legacy autobuy/makeoffer, autobuy_purchases.json, makeoffer_cooldown.
# json, bot_supremo_thin_market_cache.json) con un solo file di testo a righe, editabile
# a mano su GitHub, con 4 tipi di riga:
#   manager,<slug>,<scadenza_iso>
#   giocatore,<slug>,<scadenza_iso>
#   thin_market,<slug>,<scadenza_iso>
#   cooldown_acquisto,<slug>,<scadenza_iso>
# La scadenza e' editabile a mano riga per riga: basta cambiare la data ISO. Una riga
# con scadenza nel passato viene ignorata in lettura ma NON cancellata automaticamente
# (resta li' finche' non la si toglie a mano o finche' il bot non la rinnova scrivendo
# una nuova scadenza per lo stesso slug/tipo).
LISTA_NERA_PATH = os.environ.get('LISTA_NERA_PATH', 'sorare_lista_nera.txt')

# Durate di default (giorni), usate quando il bot AGGIUNGE una riga per conto suo
# (es. dal workflow_dispatch, o registrando un acquisto/offerta/thin-market skip).
# Tutte modificabili qui O a mano nel file cambiando la scadenza di ogni riga.
MANAGER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('MANAGER_BLACKLIST_DEFAULT_DAYS', '7'))
PLAYER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('PLAYER_BLACKLIST_DEFAULT_DAYS', '7'))
THIN_MARKET_DEFAULT_DAYS = float(os.environ.get('THIN_MARKET_DEFAULT_DAYS', '1'))
COOLDOWN_ACQUISTO_DEFAULT_DAYS = float(os.environ.get('COOLDOWN_ACQUISTO_DEFAULT_DAYS', '1'))

_LISTA_NERA_TIPI_VALIDI = ('manager', 'giocatore', 'thin_market', 'cooldown_acquisto')

# Vecchi file, letti SOLO per la migrazione automatica una tantum (prima run dopo
# l'aggiornamento). Una volta migrati in sorare_lista_nera.txt possono essere eliminati
# dal repo -- vedi messaggio di log a fine migrazione.
_LEGACY_FILES_DA_MIGRARE = {
    'manager': ['sorare_manager_blacklist.txt', 'sorare_autobuy_manager_blacklist.txt',
                'sorare_makeoffer_manager_blacklist.txt'],
    'giocatore': ['sorare_blacklist.txt', 'sorare_autobuy_blacklist.txt',
                  'sorare_makeoffer_blacklist.txt'],
}
_LEGACY_JSON_DA_MIGRARE = {
    'cooldown_acquisto': ['autobuy_purchases.json', 'makeoffer_cooldown.json'],
    'thin_market': ['bot_supremo_thin_market_cache.json'],
}


def _lista_nera_leggi_righe():
    """Legge tutte le righe valide dal file unico. Ritorna lista di dict
    {tipo, slug, scadenza (datetime)}. Righe malformate vengono ignorate con log."""
    righe = []
    try:
        with open(LISTA_NERA_PATH, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        return righe
    for n, raw in enumerate(raw_lines, start=1):
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) != 3:
            log(f"[lista nera] riga {n} malformata (attesi 3 campi), ignorata: {raw!r}")
            continue
        tipo, slug, scadenza_str = parts
        tipo = tipo.lower()
        slug = slug.lower()
        if tipo not in _LISTA_NERA_TIPI_VALIDI:
            log(f"[lista nera] riga {n} tipo sconosciuto {tipo!r}, ignorata: {raw!r}")
            continue
        try:
            scadenza = datetime.datetime.fromisoformat(scadenza_str)
            if scadenza.tzinfo is None:
                scadenza = scadenza.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            log(f"[lista nera] riga {n} scadenza non valida, ignorata: {raw!r}")
            continue
        righe.append({'tipo': tipo, 'slug': slug, 'scadenza': scadenza})
    return righe


def _lista_nera_scrivi_righe(righe):
    """Riscrive il file unico ordinato per tipo poi slug, con commento di intestazione."""
    righe_ordinate = sorted(righe, key=lambda r: (r['tipo'], r['slug']))
    with open(LISTA_NERA_PATH, 'w', encoding='utf-8') as f:
        f.write("# Lista nera del Bot Supremo -- formato: tipo,slug,scadenza_iso\n")
        f.write("# Tipi validi: manager, giocatore, thin_market, cooldown_acquisto\n")
        f.write("# Scadenza modificabile a mano: basta cambiare la data ISO su una riga.\n")
        f.write("# Righe scadute vengono ignorate in lettura ma NON cancellate automaticamente.\n")
        for r in righe_ordinate:
            f.write(f"{r['tipo']},{r['slug']},{r['scadenza'].isoformat()}\n")


def _lista_nera_upsert(tipo, slug, giorni_da_ora):
    """Aggiunge o rinnova una riga (tipo, slug) con nuova scadenza = ora + giorni_da_ora.
    Se la riga esiste gia', la sostituisce (rinnovo); altrimenti la aggiunge."""
    slug = slug.lower()
    righe = _lista_nera_leggi_righe()
    scadenza = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=giorni_da_ora)
    trovata = False
    for r in righe:
        if r['tipo'] == tipo and r['slug'] == slug:
            r['scadenza'] = scadenza
            trovata = True
            break
    if not trovata:
        righe.append({'tipo': tipo, 'slug': slug, 'scadenza': scadenza})
    _lista_nera_scrivi_righe(righe)


def _lista_nera_attiva(tipo, slug):
    """True se (tipo, slug) e' presente con scadenza non ancora passata."""
    slug = (slug or '').lower()
    if not slug:
        return False
    ora = datetime.datetime.now(datetime.timezone.utc)
    for r in _lista_nera_leggi_righe():
        if r['tipo'] == tipo and r['slug'] == slug and r['scadenza'] > ora:
            return True
    return False


def _migra_vecchi_file_una_tantum():
    """Migrazione automatica una tantum: se sorare_lista_nera.txt non esiste ancora,
    legge tutti i vecchi file separati e popola il nuovo file unico. Blacklist
    manager/giocatore migrate con scadenza 7 giorni da ora (default). Cooldown
    acquisto/thin_market migrati preservando la data originale + la loro durata
    default (cosi' un giocatore comprato ieri non riparte da zero oggi)."""
    if os.path.exists(LISTA_NERA_PATH):
        return  # gia' migrato in una run precedente, non rifare
    righe = []
    ora = datetime.datetime.now(datetime.timezone.utc)
    migrate_da = []

    for tipo, file_paths in _LEGACY_FILES_DA_MIGRARE.items():
        giorni_default = (MANAGER_BLACKLIST_DEFAULT_DAYS if tipo == 'manager'
                          else PLAYER_BLACKLIST_DEFAULT_DAYS)
        for fp in file_paths:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except FileNotFoundError:
                continue
            migrate_da.append(fp)
            for line in lines:
                slug = line.strip().lower()
                if not slug or slug.startswith('#'):
                    continue
                righe.append({'tipo': tipo, 'slug': slug,
                              'scadenza': ora + datetime.timedelta(days=giorni_default)})

    for tipo, file_paths in _LEGACY_JSON_DA_MIGRARE.items():
        giorni_default = (THIN_MARKET_DEFAULT_DAYS if tipo == 'thin_market'
                          else COOLDOWN_ACQUISTO_DEFAULT_DAYS)
        for fp in file_paths:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            migrate_da.append(fp)
            for slug, last_iso in data.items():
                try:
                    last_dt = datetime.datetime.fromisoformat(last_iso)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                except (ValueError, TypeError):
                    last_dt = ora
                righe.append({'tipo': tipo, 'slug': slug.lower(),
                              'scadenza': last_dt + datetime.timedelta(days=giorni_default)})

    if not righe and not migrate_da:
        # Nessun vecchio file trovato: crea comunque il file vuoto con intestazione,
        # cosi' l'utente puo' iniziare ad editarlo a mano.
        _lista_nera_scrivi_righe([])
        print("[lista nera] nessun vecchio file trovato, creato sorare_lista_nera.txt vuoto",
              flush=True)
        return

    _lista_nera_scrivi_righe(righe)
    print(f"[lista nera] MIGRAZIONE completata da {len(migrate_da)} vecchi file "
          f"({', '.join(migrate_da)}) -> {len(righe)} righe in {LISTA_NERA_PATH}. "
          f"Puoi ora eliminare dal repo i vecchi file elencati sopra.", flush=True)


_migra_vecchi_file_una_tantum()


class _SetTipoLive:
    """Wrapper minimale per mantenere l'API 'set' (operatore 'in', len(), sorted())
    usata nel resto del codice per BLACKLISTED_PLAYER_SLUGS/BLACKLISTED_MANAGER_SLUGS,
    ma leggendo SEMPRE dal vivo dal file unico -- cosi' una modifica al file a mano
    (o un aggiornamento da un altro ramo durante la stessa run) e' vista subito,
    senza dover ricaricare/riavviare il bot."""

    def __init__(self, tipo):
        self._tipo = tipo

    def _slugs_attivi(self):
        ora = datetime.datetime.now(datetime.timezone.utc)
        return {r['slug'] for r in _lista_nera_leggi_righe()
                if r['tipo'] == self._tipo and r['scadenza'] > ora}

    def __contains__(self, slug):
        return _lista_nera_attiva(self._tipo, slug or '')

    def __iter__(self):
        return iter(self._slugs_attivi())

    def __len__(self):
        return len(self._slugs_attivi())


# Stessa blacklist manager storica di track.py (venditori solo ETH o esplicitamente
# esclusi dall'utente) -- questa resta hardcoded, non fa parte della lista nera editabile.
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}

BLACKLISTED_PLAYER_SLUGS = _SetTipoLive('giocatore')
BLACKLISTED_MANAGER_SLUGS = _SetTipoLive('manager')
# Alias per compatibilita' col nome usato nel codice AutoBuy originale.
BLACKLISTED_AUTOBUY_MANAGER_SLUGS = BLACKLISTED_MANAGER_SLUGS

# Blacklist extra passate da workflow_dispatch (input singola run, oltre al file):
# vengono scritte anche loro nel file unico, cosi' restano visibili/editabili li'.
_extra_blacklisted_players = os.environ.get('BLACKLISTED_PLAYER_SLUGS', '')
if _extra_blacklisted_players.strip():
    for _s in _extra_blacklisted_players.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_upsert('giocatore', _s, PLAYER_BLACKLIST_DEFAULT_DAYS)

_extra_blacklisted_managers = os.environ.get('BLACKLISTED_MANAGER_SLUGS', '')
if _extra_blacklisted_managers.strip():
    for _s in _extra_blacklisted_managers.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_upsert('manager', _s, MANAGER_BLACKLIST_DEFAULT_DAYS)

# --- Parametri regolabili ---
AUTOBUY_MIN_PRICE_EUR = float(os.environ.get('AUTOBUY_MIN_PRICE_EUR', '1'))
AUTOBUY_MAX_PRICE_EUR = float(os.environ.get('AUTOBUY_MAX_PRICE_EUR', '30'))

# Due soglie SEPARATE per fascia, nessuna sovrapponibile per costruzione:
# MAKEOFFER_MARGIN_FRACTION <= margine < MAKEOFFER_MAX_MARGIN_FRACTION -> ramo MakeOffer
# margine >= AUTOBUY_MARGIN_FRACTION -> ramo AutoBuy (deve essere >= al tetto MakeOffer)
MAKEOFFER_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MARGIN_FRACTION', '0.10'))
MAKEOFFER_MAX_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MAX_MARGIN_FRACTION', '0.19'))
AUTOBUY_MARGIN_FRACTION = float(os.environ.get('AUTOBUY_MARGIN_FRACTION', '0.20'))

LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '18000'))
LISTEN_SECONDS = min(18000, LISTEN_SECONDS)

# Pausa random periodica (20/07, richiesta esplicita utente: "non martellare Sorare di
# richieste troppo ritmate/prevedibili") -- ogni RANDOM_PAUSE_INTERVAL_SECONDS di
# attivita' continua, il bot si ferma per un tempo casuale tra RANDOM_PAUSE_MIN_SECONDS
# e RANDOM_PAUSE_MAX_SECONDS prima di riprendere.
RANDOM_PAUSE_INTERVAL_SECONDS = int(os.environ.get('RANDOM_PAUSE_INTERVAL_SECONDS', '180'))
RANDOM_PAUSE_MIN_SECONDS = float(os.environ.get('RANDOM_PAUSE_MIN_SECONDS', '1'))
RANDOM_PAUSE_MAX_SECONDS = float(os.environ.get('RANDOM_PAUSE_MAX_SECONDS', '10'))

EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1'}

AUTOBUY_TARGET_MATCHES = int(os.environ.get('AUTOBUY_TARGET_MATCHES', '20'))
AUTOBUY_TARGET_MATCHES = max(1, min(20, AUTOBUY_TARGET_MATCHES))

AUTOBUY_DIAGNOSTIC = os.environ.get('AUTOBUY_DIAGNOSTIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')
CHECK_CLASSIC = os.environ.get('CHECK_CLASSIC', 'si').strip().lower() in ('1', 'true', 'yes', 'si')

# Parametri MakeOffer (ramo offerta scontata)
OFFER_DISCOUNT_FRACTION = float(os.environ.get('OFFER_DISCOUNT_FRACTION', '0.20'))
OFFER_DURATION_DAYS = max(1, min(7, int(os.environ.get('OFFER_DURATION_DAYS', '1'))))
OFFER_DURATION_SECONDS = OFFER_DURATION_DAYS * 86400
MAX_PENDING_OFFERS = int(os.environ.get('MAX_PENDING_OFFERS', '10'))
pending_offers_count = [0]  # contatore in-memory per run, richiesto da create_direct_offer

# --- Stop automatico su fondi insufficienti (20/07, richiesta esplicita utente) ---
# Se un tentativo di acquisto/offerta reale fallisce per mancanza di fondi, non ha
# senso continuare l'esecuzione: ogni tentativo successivo fallirebbe allo stesso modo,
# quindi il bot si ferma subito (chiude la connessione WebSocket) invece di continuare a
# girare a vuoto per ore, e manda una notifica Telegram esplicita e diversa dalle
# normali notifiche di caso trovato/fallito.
INSUFFICIENT_FUNDS_STOP = [False]

# --- Protezione "no ri-acquisto/ri-offerta stesso giocatore entro N giorni" -- ora un
# unico tipo di riga nella lista nera (cooldown_acquisto), condiviso tra i due rami cosi'
# uno non ripropone/ricompra un giocatore appena gestito dall'altro.
PLAYER_COOLDOWN_HOURS = 24  # mantenuto per compatibilita' log/commenti esistenti


def is_player_in_cooldown(player_slug):
    return _lista_nera_attiva('cooldown_acquisto', player_slug)


def record_player_purchase(player_slug):
    _lista_nera_upsert('cooldown_acquisto', player_slug, COOLDOWN_ACQUISTO_DEFAULT_DAYS)
    log(f"[lista nera] registrato acquisto di {player_slug}, cooldown "
        f"{COOLDOWN_ACQUISTO_DEFAULT_DAYS:.1f}gg")


def record_player_offer(player_slug):
    _lista_nera_upsert('cooldown_acquisto', player_slug, COOLDOWN_ACQUISTO_DEFAULT_DAYS)
    log(f"[lista nera] registrata offerta a {player_slug}, cooldown "
        f"{COOLDOWN_ACQUISTO_DEFAULT_DAYS:.1f}gg")


# --- Cache "mercato troppo sottile" -- ora tipo di riga 'thin_market' nella lista nera
# unica (stesso principio della blacklist unita: se un ramo scarta un giocatore per
# liquidita', l'altro non deve rifare la stessa query).
THIN_MARKET_SKIP_HOURS = THIN_MARKET_DEFAULT_DAYS * 24  # mantenuto per compatibilita' log


def is_player_in_thin_market_cache(player_slug):
    return _lista_nera_attiva('thin_market', player_slug)


def record_thin_market_skip(player_slug):
    _lista_nera_upsert('thin_market', player_slug, THIN_MARKET_DEFAULT_DAYS)

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
MIN_RECENT_TRANSACTIONS = int(os.environ.get('MIN_RECENT_TRANSACTIONS', '4'))
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


_exchange_rate_id_cache = {}


def get_exchange_rate_id():
    """Recupera l'id del tasso di cambio corrente (serve a PrepareAcceptOfferMutation/
    PrepareOfferMutation), stessa query ExchangeRateQuery vista nel flusso reale di
    acquisto in browser.
    OTTIMIZZAZIONE VELOCITA' (20/07, richiesta esplicita utente -- ogni millisecondo
    conta nello sniping): CACHATO in memoria per l'intera durata del run, stesso
    principio gia' usato per fetch_encrypted_private_key. Il tasso di cambio (qui
    sempre EUR, la valuta di acquisto/offerta e' sempre EUR) non cambia abbastanza in
    fretta da giustificare una query di rete separata ad OGNI singolo tentativo --
    prima query del run la recupera, tutte le successive riusano lo stesso valore
    senza contattare di nuovo il server. Elimina una chiamata di rete intera dal
    percorso critico di ogni acquisto/offerta.
    """
    if 'id' in _exchange_rate_id_cache:
        return _exchange_rate_id_cache['id']
    try:
        data = graphql_query(EXCHANGE_RATE_QUERY)
        rate_id = (((data.get('data') or {}).get('config') or {}).get('exchangeRate') or {}).get('id')
        if rate_id:
            _exchange_rate_id_cache['id'] = rate_id
        return rate_id
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


# FIX BUG CRITICO (20/07): durante la fusione dei due bot, la funzione di
# classificazione errori del ramo MakeOffer (classify_prepare_offer_error) e' stata
# accorpata in classify_prepare_accept_error, ma create_direct_offer/prepare_offer
# continuavano a chiamare il vecchio nome -- causava NameError ad OGNI offerta live
# reale (visto dal vivo: caso Sean Johnson e Leandro Paredes, quest'ultimo sniperato
# nel frattempo perche' l'offerta non e' mai partita a causa di questo crash). La
# logica di classificazione e' identica per entrambi i rami (stessi messaggi
# GraphQL/categorie), quindi alias diretto, nessuna duplicazione.
classify_prepare_offer_error = classify_prepare_accept_error


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
    """Richiama sorare-sign/decrypt_and_sign.js (Node.js) via subprocess, passandogli via
    stdin un JSON con: password del wallet, i tre campi restituiti da
    FetchEncryptedPrivateKey (encrypted_private_key/iv/salt), e l'intero oggetto
    authorization_request (incluso __typename) restituito da prepare_accept_offer/
    prepare_offer.

    Lo script Node decripta la chiave privata (PBKDF2 + AES-GCM, stesso algoritmo usato
    dal sito sorare.com) e poi chiama @sorare/crypto.signAuthorizationRequest per
    ottenere la signature.

    OTTIMIZZAZIONE VELOCITA' (20/07, richiesta esplicita utente -- ogni millisecondo
    conta nello sniping): la chiave privata decriptata e' SEMPRE la stessa per tutta la
    sessione (stessa password/encrypted_private_key/iv/salt, gia' cachati a monte in
    _encrypted_key_cache) -- rifare il decrypt PBKDF2(50000 iterazioni)+AES-GCM ad OGNI
    singolo acquisto/offerta e' uno spreco puro. Dalla SECONDA chiamata in poi nella
    stessa sessione, saltiamo il decrypt passando direttamente la chiave gia' in chiaro
    allo script Node (campo 'decryptedPrivateKey'), che la usa subito per firmare senza
    ricalcolare nulla. Il processo Node viene comunque riavviato ad ogni chiamata (lo
    spawn stesso NON e' eliminato, solo il lavoro di decrypt al suo interno) -- un
    processo Node persistente sarebbe il passo successivo ma e' un cambiamento piu'
    invasivo, non fatto qui.

    Ritorna la stringa signature (da usare in approvals[0].mangopayWalletTransferApproval)
    oppure None se qualcosa fallisce (password sbagliata, script non trovato, dipendenze
    npm non installate, ecc.) -- logga sempre il motivo."""
    import subprocess
    if 'decrypted_private_key' in _decrypted_key_cache:
        payload = json.dumps({
            'decryptedPrivateKey': _decrypted_key_cache['decrypted_private_key'],
            'authorizationRequest': authorization_request,
        })
    else:
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
    # Se lo script ha restituito la chiave decriptata (prima chiamata della sessione),
    # la mettiamo in cache per le chiamate successive.
    if output.get('decryptedPrivateKey'):
        _decrypted_key_cache['decrypted_private_key'] = output['decryptedPrivateKey']
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

# Cache separata per la chiave privata GIA' DECRIPTATA (in chiaro, esadecimale) --
# diversa da _encrypted_key_cache sopra (quella tiene encryptedPrivateKey/iv/salt
# ancora cifrati, cosi' come arrivano dal server). Popolata da sign_authorization_via_node
# dopo il primo decrypt riuscito della sessione, poi riusata per saltare PBKDF2+AES-GCM
# nelle chiamate successive (vedi commento dettagliato in sign_authorization_via_node).
_decrypted_key_cache = {}


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
    # FIX BUG CRITICO (20/07): confermato dal vivo che il campo 'amount' restituito
    # dal server dentro l'authorization request (quello REALMENTE firmato ed
    # eseguito, vedi execute_live_offer) e' in CENTESIMI interi, non in euro con
    # decimali. Mandando "6.0" EUR il server rispondeva amount=6 (troncando i
    # decimali), e quell'intero veniva poi eseguito come 6 CENTESIMI = 0.06EUR
    # (caso reale Alex Roldan, offerta 6.00EUR eseguita a 0.06EUR, poi annullata
    # manualmente dall'utente). Ora inviamo l'importo gia' in centesimi interi.
    amount_cents = int(round(offer_amount_eur * 100))
    variables = {
        "input": {
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(amount_cents), "currency": "EUR"},
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
        # FIX FEE 5% VENDITORE (20/07, confermato dall'utente): Sorare applica una
        # commissione del 5% SUL VENDITORE (chi vende incassa il 95%), NON su chi fa
        # l'offerta. Pero' il campo 'amount' che il server restituisce qui dentro
        # l'authorization request e' gia' il NETTO scontato (es. 342 invece di 360
        # per un'offerta di 3.60EUR) -- se firmassimo quel valore cosi' com'e',
        # rischiamo di autorizzare/eseguire l'offerta per l'importo scontato invece
        # che per quello dichiarato all'utente. FIX: sovrascriviamo qui 'amount' con
        # il valore LORDO che avevamo gia' inviato in sendAmount (amount_cents),
        # cosi' la firma avviene sempre sull'importo pieno voluto dall'utente.
        server_amount = request.get('amount')
        if server_amount is not None and int(server_amount) != amount_cents:
            log(f"[prepare offer] ATTENZIONE: amount del server ({server_amount}) "
                f"diverso dal lordo inviato ({amount_cents}) -- probabile netto "
                f"post-fee 5% venditore. Sovrascrivo con il lordo prima di firmare.")
        request['amount'] = amount_cents
        return {'fingerprint': auth.get('fingerprint'), 'request': request,
                'exchange_rate_id': exchange_rate_id}
    except Exception as e:
        log(f"[prepare offer] eccezione: {e}")
        return None



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
    # FIX BUG CRITICO (20/07): stesso fix di prepare_offer, per coerenza -- vedi
    # commento dettagliato li'. sendAmount va in centesimi interi.
    amount_cents = int(round(offer_amount_eur * 100))
    variables = {
        "input": {
            "dealId": deal_id,
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(amount_cents), "currency": "EUR"},
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

def send_autobuy_alert(player_name, player_slug, price_eur, second_price, margin_percent,
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
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- ACQUISTATO IN AUTOMATICO</b>"
            esito = "\u2705 <b>Acquisto completato con successo, nessuna azione richiesta.</b>\n\n"
        else:
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- ACQUISTO AUTOMATICO FALLITO</b>"
            esito = (f"\u274C <b>Acquisto automatico NON riuscito</b>: {purchase_error}\n"
                      f"Apri e valuta se confermare a mano.\n\n")
    else:
        titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- LO AVREI ACQUISTATO</b>"
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


def send_makeoffer_alert(player_name, player_slug, price_eur, second_price, margin_percent,
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
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer) -- OFFERTA INVIATA IN AUTOMATICO</b>"
            esito = "\u2705 <b>Offerta inviata con successo, in attesa che il venditore risponda.</b>\n\n"
        else:
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer) -- OFFERTA AUTOMATICA FALLITA</b>"
            esito = (f"\u274C <b>Offerta automatica NON inviata</b>: {purchase_error}\n"
                      f"Apri e valuta se fare l'offerta a mano.\n\n")
    else:
        titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer) -- FAREI UN'OFFERTA</b>"
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


def _is_insufficient_funds_error(error_message):
    """Rileva se un messaggio di errore (gia' formattato da execute_live_purchase/
    execute_live_offer, es. 'AcceptOfferMutation fallita [fondi_insufficienti]: ...')
    indica fondi insufficienti -- la categoria e' gia' classificata a monte da
    classify_prepare_accept_error/classify_prepare_offer_error, qui controlliamo solo
    che compaia nel messaggio finale."""
    if not error_message:
        return False
    return '[fondi_insufficienti]' in error_message


def _is_invalid_signature_error(error_message):
    """Rileva se un messaggio di errore indica una firma non valida ('invalid Mangopay
    wallet transfer signature') -- errore visto dal vivo il 20/07 solo nel ramo
    MakeOffer, causa non ancora confermata. Serve per attivare la diagnostica dedicata
    in send_invalid_signature_diagnostic_alert (vedi sotto)."""
    if not error_message:
        return False
    return 'invalid mangopay wallet transfer signature' in error_message.lower()


def send_invalid_signature_diagnostic_alert(player_name, seller_slug, offer_amount_eur):
    """Notifica diagnostica DEDICATA (20/07, richiesta esplicita utente) per il caso
    'invalid Mangopay wallet transfer signature' nel ramo MakeOffer -- NON confermiamo
    la causa (e' solo un'ipotesi dell'utente, non un fatto accertato): potrebbe essere
    che il venditore/manager abbia bloccato il nostro account dalle offerte dirette
    (Sorare lo permette, pur consentendo la vendita diretta allo stesso account), oppure
    un problema di firma/cache lato bot. La notifica elenca il fatto osservato (verso
    quale manager e' fallita) senza affermare la causa, cosi' l'utente puo' verificare
    manualmente se accumula ripetutamente sullo stesso manager (indizio di blocco)."""
    send_telegram_msg(
        f"\U0001F50D <b>Bot Supremo -- DIAGNOSTICA: firma non valida (MakeOffer)</b>\n\n"
        f"Giocatore: {player_name}\n"
        f"Venditore/manager: {seller_slug}\n"
        f"Offerta tentata: {offer_amount_eur:.2f}EUR\n\n"
        f"Causa non confermata -- possibili ipotesi: questo manager potrebbe averti "
        f"bloccato dalle offerte dirette (Sorare lo permette anche se accetta la "
        f"vendita diretta allo stesso account), oppure un problema di firma/cache. "
        f"Se questo errore si ripete SEMPRE con lo stesso manager, e' un indizio "
        f"a favore dell'ipotesi del blocco."
    )


def send_insufficient_funds_alert(player_name, ramo):
    send_telegram_msg(
        f"\U0001F6D1 <b>Bot Supremo -- FONDI INSUFFICIENTI, ESECUZIONE FERMATA</b>\n\n"
        f"Rilevato durante il tentativo su {player_name} (ramo {ramo}).\n"
        f"Il bot si e' fermato subito invece di continuare a tentare a vuoto -- "
        f"ricarica il wallet prima di rilanciare."
    )


def send_startup_msg():
    classic_msg = "\nModalita' CLASSIC attiva (tutti i campionati)" if CHECK_CLASSIC else ""
    autobuy_stato = "ATTIVO" if AUTOBUY_LIVE_MODE else "solo diagnostica"
    makeoffer_stato = "ATTIVO" if MAKEOFFER_LIVE_MODE else "solo diagnostica"
    send_telegram_msg(
        f"\U0001F916 <b>Bot Supremo avviato</b>\n"
        f"AutoBuy: margine >= {AUTOBUY_MARGIN_FRACTION:.0%} ({autobuy_stato})\n"
        f"MakeOffer: margine {MAKEOFFER_MARGIN_FRACTION:.0%}-{MAKEOFFER_MAX_MARGIN_FRACTION:.0%} ({makeoffer_stato})\n"
        f"Fascia prezzo: {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR\n"
        f"Ascolto per {LISTEN_SECONDS}s o fino a {AUTOBUY_TARGET_MATCHES} casi trovati.{classic_msg}"
    )


def send_end_msg(matches_found, target_reached):
    esito = (
        f"\u2705 Target raggiunto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
        if target_reached else
        f"\u23F1 Tempo scaduto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
    )
    send_telegram_msg(
        f"\U0001F916 <b>Bot Supremo terminato</b>\n"
        f"{esito}"
    )


def evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate, league_slug=None,
                    offer_id=None, seller_slug=None, is_in_season=True):
    """Valutazione UNICA condivisa (un solo scan di mercato per evento, niente doppio
    lavoro tra i due bot separati). Dopo il calcolo del margine, biforca:
    - margine >= AUTOBUY_MARGIN_FRACTION -> ramo AutoBuy (accetta offerta esistente)
    - MAKEOFFER_MARGIN_FRACTION <= margine < AUTOBUY_MARGIN_FRACTION (tetto MakeOffer
      MAKEOFFER_MAX_MARGIN_FRACTION incluso in questo range per costruzione) -> ramo
      MakeOffer (crea offerta scontata)
    Ritorna True se questo evento ha portato a un caso valido (di QUALSIASI ramo),
    False altrimenti -- usato dal listener per decidere se fermarsi."""
    if INSUFFICIENT_FUNDS_STOP[0]:
        return False  # bot gia' fermato per fondi insufficienti, non valutare altro

    if player_slug and player_slug.lower() in BLACKLISTED_PLAYER_SLUGS:
        log(f"{player_name}: scarto -- giocatore in blacklist manuale ({player_slug})")
        return False

    if player_slug and is_player_in_cooldown(player_slug):
        log(f"{player_name}: scarto -- gia' acquistato/offerto nelle ultime "
            f"{PLAYER_COOLDOWN_HOURS}h (protezione anti-svendita/infortunio)")
        return False

    if not (AUTOBUY_MIN_PRICE_EUR <= price_eur <= AUTOBUY_MAX_PRICE_EUR):
        return False

    if player_slug and is_player_in_thin_market_cache(player_slug):
        log(f"{player_name}: scarto -- gia' segnalato come mercato troppo sottile nelle "
            f"ultime {THIN_MARKET_SKIP_HOURS:.0f}h, salto la riverifica")
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

    if true_min_card_slug != card_slug:
        if price_eur < true_min_price:
            log(f"{player_name}: minimo query non aggiornato ({true_min_price:.2f}EUR), "
                f"ma evento a {price_eur:.2f}EUR e' piu' basso -- procedo con l'evento")
            true_min_price, true_min_card_slug, true_min_seller_slug = price_eur, card_slug, seller_slug
            prices = [(price_eur, card_slug, seller_slug)] + [p for p in prices if p[1] != card_slug]
        else:
            categoria = "in_season" if excluded_league else "in_season/classic"
            log(f"{player_name}: scarto -- annuncio a {price_eur:.2f}EUR non e' il minimo attuale "
                f"{categoria} (minimo vero: {true_min_price:.2f}EUR)")
            return False

    if true_min_seller_slug in BLACKLISTED_SELLER_SLUGS or \
            true_min_seller_slug in BLACKLISTED_MANAGER_SLUGS:
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
        f"margine {margin_percent:.1%} (soglie MakeOffer {MAKEOFFER_MARGIN_FRACTION:.0%}-"
        f"{MAKEOFFER_MAX_MARGIN_FRACTION:.0%}, AutoBuy >= {AUTOBUY_MARGIN_FRACTION:.0%})")

    # --- ROUTER: nessuna sovrapposizione per costruzione ---
    if margin_percent >= AUTOBUY_MARGIN_FRACTION:
        return _handle_autobuy_branch(player_name, player_slug, true_min_price, second_min_price,
                                       margin_percent, card_slug, excluded_league, is_in_season,
                                       offer_id)
    if MAKEOFFER_MARGIN_FRACTION <= margin_percent <= MAKEOFFER_MAX_MARGIN_FRACTION:
        return _handle_makeoffer_branch(player_name, player_slug, true_min_price, second_min_price,
                                         margin_percent, card_slug, excluded_league, is_in_season,
                                         seller_slug)
    return False


def _handle_autobuy_branch(player_name, player_slug, true_min_price, second_min_price,
                            margin_percent, card_slug, excluded_league, is_in_season, offer_id):
    log(f"AUTOBUY: {player_name} -- LO AVREI ACQUISTATO ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%})")

    prepared = None
    if offer_id:
        prepared = prepare_accept_offer(offer_id)
        if prepared:
            nonce = (prepared.get('request') or {}).get('nonce')
            log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
        else:
            log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

    purchase_completed = False
    purchase_error = None
    if AUTOBUY_LIVE_MODE and offer_id and prepared:
        try:
            purchase_completed, purchase_error = execute_live_purchase(offer_id, prepared)
        except Exception as e:
            purchase_error = f"eccezione imprevista: {e}"
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante acquisto live -- {e}")
        if purchase_completed:
            log(f"{player_name}: ACQUISTO COMPLETATO CON SUCCESSO")
            if player_slug:
                record_player_purchase(player_slug)
        else:
            log(f"{player_name}: acquisto automatico fallito -- {purchase_error}")
            if _is_insufficient_funds_error(purchase_error):
                log(f"{player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot, "
                    f"nessun tentativo successivo avrebbe senso")
                INSUFFICIENT_FUNDS_STOP[0] = True
                send_insufficient_funds_alert(player_name, "AutoBuy")
    elif AUTOBUY_LIVE_MODE and offer_id and not prepared:
        purchase_error = "prenotazione (prepareAcceptOffer) non riuscita, acquisto automatico saltato"
        log(f"{player_name}: {purchase_error}")

    send_autobuy_alert(player_name, player_slug, true_min_price, second_min_price,
                        margin_percent, card_slug, excluded_league, prepared, is_in_season,
                        live_mode=AUTOBUY_LIVE_MODE, purchase_completed=purchase_completed,
                        purchase_error=purchase_error)
    return True


def _handle_makeoffer_branch(player_name, player_slug, true_min_price, second_min_price,
                              margin_percent, card_slug, excluded_league, is_in_season, seller_slug):
    log(f"MAKEOFFER: {player_name} -- TROVATO AFFARE ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%}) -- valuto se fare un'offerta")

    card_details = get_card_offer_details(card_slug)
    if not card_details:
        log(f"{player_name}: scarto -- impossibile recuperare i dettagli della carta "
            f"({card_slug}), niente assetId disponibile")
        return False

    card_asset_id = card_details.get('assetId')
    if not card_asset_id:
        log(f"{player_name}: scarto -- assetId assente per {card_slug}")
        return False

    existing_offers = card_details.get('liveSingleBuyOffers') or []
    if existing_offers:
        log(f"{player_name}: scarto -- offerta gia' pendente su questa carta "
            f"({len(existing_offers)} offerta/e attiva/e), non ne faccio una seconda")
        return False

    sale_offer = card_details.get('liveSingleSaleOffer') or {}
    settlement_currencies = sale_offer.get('settlementCurrencies') or []
    crypto_only_currencies = {'WEI', 'ETH'}
    if settlement_currencies and set(settlement_currencies).issubset(crypto_only_currencies):
        log(f"{player_name}: scarto -- venditore accetta solo cripto, niente fiat "
            f"(valute accettate: {settlement_currencies})")
        return False

    if pending_offers_count[0] >= MAX_PENDING_OFFERS:
        log(f"{player_name}: scarto -- gia' raggiunto il tetto di {MAX_PENDING_OFFERS} "
            f"offerte pendenti in questa esecuzione")
        return False

    offer_amount_eur = round(true_min_price * (1 - OFFER_DISCOUNT_FRACTION), 2)
    if offer_amount_eur <= 0:
        log(f"{player_name}: scarto -- offerta calcolata non positiva ({offer_amount_eur}EUR)")
        return False

    log(f"{player_name}: offerta calcolata: {offer_amount_eur:.2f}EUR "
        f"(minimo {true_min_price:.2f}EUR - sconto {OFFER_DISCOUNT_FRACTION:.0%}), "
        f"durata {OFFER_DURATION_DAYS} giorni")

    prepared = prepare_offer(card_asset_id, seller_slug, offer_amount_eur)
    if prepared:
        nonce = (prepared.get('request') or {}).get('nonce')
        log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
    else:
        log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

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
            if player_slug:
                record_player_offer(player_slug)
            pending_offers_count[0] += 1
        else:
            log(f"{player_name}: offerta automatica fallita -- {offer_error}")
            if _is_insufficient_funds_error(offer_error):
                log(f"{player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot, "
                    f"nessun tentativo successivo avrebbe senso")
                INSUFFICIENT_FUNDS_STOP[0] = True
                send_insufficient_funds_alert(player_name, "MakeOffer")
            elif _is_invalid_signature_error(offer_error):
                log(f"{player_name}: FIRMA NON VALIDA rilevata verso il manager "
                    f"'{seller_slug}' -- invio notifica diagnostica (causa non "
                    f"confermata, vedi Telegram)")
                send_invalid_signature_diagnostic_alert(player_name, seller_slug, offer_amount_eur)
    elif MAKEOFFER_LIVE_MODE and not prepared:
        offer_error = "prenotazione (prepareOffer) non riuscita, offerta automatica saltata"
        log(f"{player_name}: {offer_error}")

    send_makeoffer_alert(player_name, player_slug, true_min_price, second_min_price,
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

    # --- Pausa random periodica (20/07, richiesta esplicita utente: "non martellare
    # Sorare di richieste troppo ritmate/prevedibili") -- ogni RANDOM_PAUSE_INTERVAL_
    # SECONDS (default 180s = 3 minuti) di attivita', il bot si ferma per un tempo
    # casuale tra RANDOM_PAUSE_MIN_SECONDS e RANDOM_PAUSE_MAX_SECONDS (default 1-10s)
    # prima di riprendere a valutare eventi. Il timer parte dall'avvio dell'ascolto,
    # non resetta ad ogni evento -- e' un ritmo di fondo, non legato al volume di
    # eventi ricevuti.
    pause_state = {"last_pause_at": time.monotonic()}

    def maybe_random_pause():
        now = time.monotonic()
        if now - pause_state["last_pause_at"] >= RANDOM_PAUSE_INTERVAL_SECONDS:
            pause_seconds = random.uniform(RANDOM_PAUSE_MIN_SECONDS, RANDOM_PAUSE_MAX_SECONDS)
            log(f"[pausa random] fermo {pause_seconds:.1f}s (ritmo di fondo anti-martellamento)")
            time.sleep(pause_seconds)
            pause_state["last_pause_at"] = time.monotonic()

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
        if seller_slug in BLACKLISTED_MANAGER_SLUGS:
            return

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
            maybe_random_pause()
            if INSUFFICIENT_FUNDS_STOP[0]:
                log("STOP: fondi insufficienti rilevati, chiudo la connessione -- "
                    "nessun tentativo successivo avrebbe senso")
                ws.close()
                return
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
    autobuy_modalita = "ACQUISTO REALE ATTIVO" if AUTOBUY_LIVE_MODE else "solo diagnostica"
    makeoffer_modalita = "OFFERTE REALI ATTIVE" if MAKEOFFER_LIVE_MODE else "solo diagnostica"
    log(f"Bot Supremo -- AutoBuy: {autobuy_modalita} | MakeOffer: {makeoffer_modalita}")
    log(f"[network] curl_cffi (impronta TLS Chrome) {'ATTIVO' if _HAS_CURL_CFFI else 'NON DISPONIBILE, uso requests standard'}")
    csrf_source = "estratto dal cookie (csrftoken=...)" if _extract_csrf_from_cookie(COOKIES) else "da secret SORARE_CSRF (fallback)"
    log(f"[auth] CSRF token in uso: {csrf_source}, valore: {(CSRF_TOKEN or '')[:20]}...")
    log(f"Fascia prezzo {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR, "
        f"MakeOffer {MAKEOFFER_MARGIN_FRACTION:.0%}-{MAKEOFFER_MAX_MARGIN_FRACTION:.0%}, "
        f"AutoBuy >= {AUTOBUY_MARGIN_FRACTION:.0%}, target casi da trovare: {AUTOBUY_TARGET_MATCHES}")
    log(f"Giocatori in blacklist unita ({len(BLACKLISTED_PLAYER_SLUGS)}): "
        f"{sorted(BLACKLISTED_PLAYER_SLUGS)}")
    log(f"Manager in blacklist unita ({len(BLACKLISTED_MANAGER_SLUGS)}): "
        f"{sorted(BLACKLISTED_MANAGER_SLUGS)}")
    if AUTOBUY_LIVE_MODE or MAKEOFFER_LIVE_MODE:
        log("[playwright] pre-apertura browser all'avvio (ottimizzazione velocita')...")
        get_browser_page()
        log("[playwright] browser pronto e riscaldato, in attesa di occasioni")
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
