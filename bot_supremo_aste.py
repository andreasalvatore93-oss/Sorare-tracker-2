import json
import os
import random
import re
import time
import datetime
import threading
import subprocess
import queue
import collections

import requests
import websocket  # pip install websocket-client
from playwright.sync_api import sync_playwright

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# =====================================================================================
# BOT SUPREMO ASTE (21/07) -- sniper per le aste inglesi di Sorare.
# =====================================================================================
# Ascolta l'evento websocket tokenAuctionWasUpdated (stesso canale gia' validato dal
# notificatore aste esistente, auctions_ws_listener.py), ma a differenza di quello NON si
# limita a notificare: quando trova un'asta che soddisfa i criteri, piazza DAVVERO un bid
# (se AUCTION_LIVE_MODE='si') usando la mutation ufficiale documentata da Sorare stessa
# (github.com/sorare/api): prepareBid -> firma -> bid (mutation tokenBid). Stessa
# infrastruttura di firma gia' pronta e testata nel bot buyer (bot_supremo.py): processo
# Node persistente per la firma, cache exchange_rate_id, sessione HTTP persistente,
# throttle GraphQL, browser Playwright per le chiamate critiche (anti-fingerprint).
#
# Riferimento prezzo ("minimo di mercato") per decidere quanto offrire:
#   riferimento = min(minimo LIVE di vendita diretta in_season, prezzo dell'ultima asta
#                      CONCLUSA per quel giocatore SOLO se conclusa nelle ultime 24h)
#   tra i due disponibili -- se nessuno dei due e' disponibile, l'asta viene scartata.
# Bid = tetto pieno (riferimento * (1 - sconto), default sconto 25%), MAI un rilancio
# automatico: bid secco, se il minNextBid attuale e' gia' sopra il nostro tetto si scarta
# senza biddare. Su Sorare il bid e' un vero e proprio "proxy bid" (stile eBay): puntare
# 100 su un'asta ferma a 20 significa pagare il minimo necessario per restare in testa FINO
# a 100, non pagare 100 secchi -- quindi biddare il tetto pieno e' sicuro ed e' la scelta
# esplicita dell'utente (21/07).
#
# Le aste Sorare valgono SOLO per carte Limited in_season (le classic non vengono mai
# messe all'asta, confermato dall'utente) -- nessun filtro rarita'/stagione aggiuntivo
# necessario oltre a quello implicito.
#
# Whitelist campionati (file esterno campionati_aste_whitelist.json): si bidda SOLO sui
# campionati elencati li' dentro (default: MLS e K League). Whitelist statica, nessuna
# scadenza automatica -- resta com'e' finche' l'utente non la modifica a mano.
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    """Il CSRF token cambia ad ogni refresh pagina -- estratto dal cookie stesso
    (campo csrftoken=...) invece di un secret statico che scadrebbe subito. Identico
    al bot buyer."""
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('AUCTION_TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('AUCTION_TELEGRAM_CHAT_ID', '').strip()

AUCTION_LIVE_MODE = os.environ.get('AUCTION_LIVE_MODE', 'no').strip().lower() in ('1', 'true', 'yes', 'si')
SORARE_WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# OTTIMIZZAZIONE VELOCITA' (stessa identica ottimizzazione validata nel bot buyer):
# Session persistente invece di post() a livello di modulo -- la connessione TCP/TLS
# resta aperta e viene riusata tra una chiamata e l'altra invece di rinegoziare
# l'handshake ad ogni singola query GraphQL.
if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


# =====================================================================================
# LISTA NERA ASTE -- file separato e indipendente da quello del bot buyer (richiesta
# esplicita utente 21/07: "il bot aste e' indipendente, usa solo il suo file separato").
# Stesso identico formato/meccanismo del file del buyer (sezioni '## tipo', righe
# 'slug,durata_leggibile'), solo con due sole sezioni: blacklist manuale giocatori e
# cooldown bid (12h di default, un bid reale per giocatore al massimo ogni tot ore).
# =====================================================================================
LISTA_NERA_ASTE_PATH = os.environ.get('LISTA_NERA_ASTE_PATH', 'sorare_lista_nera_aste.txt')
_LISTA_NERA_ASTE_TIPI_VALIDI = ('giocatore', 'cooldown_bid')
_LISTA_NERA_ASTE_ORDINE_SEZIONI = ('giocatore', 'cooldown_bid')
_LISTA_NERA_ASTE_INTESTAZIONI = {
    'giocatore': (
        "GIOCATORI BLACKLISTATI -- niente bid su questi giocatori, in nessun caso."
    ),
    'cooldown_bid': (
        "COOLDOWN BID -- giocatori su cui abbiamo gia' piazzato un bid reale: ignorati "
        "per il tempo indicato, per non biddare piu' di una volta sullo stesso "
        "giocatore troppo ravvicinatamente."
    ),
}

PLAYER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('PLAYER_BLACKLIST_DEFAULT_DAYS', '3'))
AUCTION_COOLDOWN_HOURS = float(os.environ.get('AUCTION_COOLDOWN_HOURS', '12'))
AUCTION_COOLDOWN_DAYS = AUCTION_COOLDOWN_HOURS / 24


def _durata_a_leggibile(delta_secondi):
    """Converte un numero di secondi in una stringa leggibile in italiano -- identica
    alla funzione gemella nel bot buyer, per coerenza tra i due file."""
    if delta_secondi <= 0:
        return "scaduto"
    giorni = delta_secondi / 86400
    if giorni >= 1:
        giorni_interi = max(1, round(giorni))
        return f"{giorni_interi} giorno" if giorni_interi == 1 else f"{giorni_interi} giorni"
    ore = delta_secondi / 3600
    if ore >= 1:
        ore_intere = max(1, round(ore))
        return f"{ore_intere} ora" if ore_intere == 1 else f"{ore_intere} ore"
    minuti = max(1, round(delta_secondi / 60))
    return f"{minuti} minuto" if minuti == 1 else f"{minuti} minuti"


def _leggibile_a_secondi(testo):
    """Converte una stringa italiana ('7 giorni', '12 ore', '30 minuti') in secondi.
    Accetta anche forme abbreviate (7g, 12h, 30m). Identica alla funzione gemella nel
    bot buyer."""
    testo = testo.strip().lower()
    parts = testo.split()
    if len(parts) == 2:
        numero_str, unita = parts
    elif len(parts) == 1 and len(testo) > 1 and testo[-1] in ('g', 'h', 'm'):
        numero_str, unita = testo[:-1], testo[-1]
    else:
        return None
    try:
        numero = float(numero_str)
    except ValueError:
        return None
    if unita.startswith('giorn') or unita == 'g':
        return numero * 86400
    if unita.startswith('or') or unita == 'h':
        return numero * 3600
    if unita.startswith('minut') or unita == 'm':
        return numero * 60
    return None


def _lista_nera_aste_leggi_righe():
    righe = []
    try:
        with open(LISTA_NERA_ASTE_PATH, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        return righe
    ora = datetime.datetime.now(datetime.timezone.utc)
    tipo_corrente = None
    for n, raw in enumerate(raw_lines, start=1):
        raw = raw.rstrip('\n')
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith('## '):
            candidato = stripped[3:].strip().lower()
            if candidato in _LISTA_NERA_ASTE_TIPI_VALIDI:
                tipo_corrente = candidato
            continue
        if stripped.startswith('#'):
            continue
        if tipo_corrente is None:
            log(f"[lista nera aste] riga {n} fuori da qualunque sezione, ignorata: {raw!r}")
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if len(parts) != 2:
            log(f"[lista nera aste] riga {n} malformata (attesi 2 campi slug,durata), ignorata: {raw!r}")
            continue
        slug, durata_str = parts
        slug = slug.lower()
        secondi = _leggibile_a_secondi(durata_str)
        if secondi is None:
            log(f"[lista nera aste] riga {n} durata non riconosciuta ('{durata_str}'), ignorata: {raw!r}")
            continue
        righe.append({'tipo': tipo_corrente, 'slug': slug, 'scadenza': ora + datetime.timedelta(seconds=secondi)})
    return righe


def _lista_nera_aste_scrivi_righe(righe):
    ora = datetime.datetime.now(datetime.timezone.utc)
    dedup = {}
    for r in righe:
        if r['scadenza'] <= ora:
            continue
        chiave = (r['tipo'], r['slug'])
        if chiave not in dedup or r['scadenza'] > dedup[chiave]['scadenza']:
            dedup[chiave] = r
    per_tipo = {t: [] for t in _LISTA_NERA_ASTE_TIPI_VALIDI}
    for r in dedup.values():
        per_tipo[r['tipo']].append(r)

    with open(LISTA_NERA_ASTE_PATH, 'w', encoding='utf-8') as f:
        f.write("# LISTA NERA DEL BOT SUPREMO ASTE\n")
        f.write("# Ogni riga: slug,durata (es. 'kang-in-lee,10 ore'). La durata e' il tempo\n")
        f.write("# rimanente, aggiornato automaticamente ogni volta che il bot riscrive questo\n")
        f.write("# file -- puoi modificarla a mano in qualunque momento (es. '3 ore', '10 giorni',\n")
        f.write("# '30 minuti') per accorciare o allungare il blocco. Per rimuovere un blocco,\n")
        f.write("# cancella semplicemente la riga.\n")
        f.write("# NOTA: file indipendente dalla lista nera del bot buyer (sorare_lista_nera.txt)\n")
        f.write("# -- questo bot non la legge e non ci scrive.\n\n")
        for tipo in _LISTA_NERA_ASTE_ORDINE_SEZIONI:
            righe_tipo = sorted(per_tipo[tipo], key=lambda r: r['slug'])
            f.write(f"## {tipo}\n")
            f.write(f"# {_LISTA_NERA_ASTE_INTESTAZIONI[tipo]}\n")
            if not righe_tipo:
                f.write("# (vuoto)\n")
            for r in righe_tipo:
                delta = (r['scadenza'] - ora).total_seconds()
                f.write(f"{r['slug']},{_durata_a_leggibile(delta)}\n")
            f.write("\n")


def _lista_nera_aste_upsert(tipo, slug, giorni_da_ora):
    slug = slug.lower()
    righe = _lista_nera_aste_leggi_righe()
    scadenza = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=giorni_da_ora)
    trovata = False
    for r in righe:
        if r['tipo'] == tipo and r['slug'] == slug:
            r['scadenza'] = scadenza
            trovata = True
            break
    if not trovata:
        righe.append({'tipo': tipo, 'slug': slug, 'scadenza': scadenza})
    _lista_nera_aste_scrivi_righe(righe)


def _lista_nera_aste_attiva(tipo, slug):
    slug = (slug or '').lower()
    if not slug:
        return False
    ora = datetime.datetime.now(datetime.timezone.utc)
    for r in _lista_nera_aste_leggi_righe():
        if r['tipo'] == tipo and r['slug'] == slug and r['scadenza'] > ora:
            return True
    return False


class _SetTipoLiveAste:
    """Stesso wrapper del bot buyer: legge sempre dal vivo dal file, cosi' una modifica
    a mano (o un aggiornamento da un altro processo) e' vista subito."""

    def __init__(self, tipo):
        self._tipo = tipo

    def _slugs_attivi(self):
        ora = datetime.datetime.now(datetime.timezone.utc)
        return {r['slug'] for r in _lista_nera_aste_leggi_righe()
                if r['tipo'] == self._tipo and r['scadenza'] > ora}

    def __contains__(self, slug):
        return _lista_nera_aste_attiva(self._tipo, slug or '')

    def __iter__(self):
        return iter(self._slugs_attivi())

    def __len__(self):
        return len(self._slugs_attivi())


BLACKLISTED_PLAYER_SLUGS_ASTE = _SetTipoLiveAste('giocatore')

_extra_blacklisted_players = os.environ.get('BLACKLISTED_PLAYER_SLUGS', '')
if _extra_blacklisted_players.strip():
    for _s in _extra_blacklisted_players.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_aste_upsert('giocatore', _s, PLAYER_BLACKLIST_DEFAULT_DAYS)


def is_player_in_bid_cooldown(player_slug):
    return _lista_nera_aste_attiva('cooldown_bid', player_slug)


def record_player_bid(player_slug):
    _lista_nera_aste_upsert('cooldown_bid', player_slug, AUCTION_COOLDOWN_DAYS)
    log(f"[lista nera aste] registrato bid reale su {player_slug}, cooldown {AUCTION_COOLDOWN_HOURS:.0f}h")


# =====================================================================================
# WHITELIST CAMPIONATI -- file esterno campionati_aste_whitelist.json. Si bidda SOLO sui
# campionati elencati (whitelist statica, nessuna scadenza automatica -- richiesta
# esplicita utente 21/07). Se il campionato di un'asta e' sconosciuto/mancante, l'asta
# viene esclusa (comportamento di sicurezza -- in pratica capita raramente, dato che
# Sorare mette all'asta solo carte di giocatori con una squadra attiva).
# =====================================================================================
LEAGUE_WHITELIST_PATH = os.environ.get('LEAGUE_WHITELIST_PATH', 'campionati_aste_whitelist.json')


def load_league_whitelist():
    try:
        with open(LEAGUE_WHITELIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        leagues = data.get('leagues') or []
        slugs = {l['slug'].strip().lower() for l in leagues if l.get('slug')}
        if not slugs:
            log(f"[whitelist campionati] ATTENZIONE: '{LEAGUE_WHITELIST_PATH}' letto ma nessuno "
                f"slug valido trovato -- NESSUNA asta verra' considerata finche' non lo sistemi.")
        return slugs
    except FileNotFoundError:
        log(f"[whitelist campionati] ATTENZIONE: file '{LEAGUE_WHITELIST_PATH}' non trovato -- "
            f"NESSUNA asta verra' considerata finche' non lo crei.")
        return set()
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[whitelist campionati] ATTENZIONE: '{LEAGUE_WHITELIST_PATH}' malformato ({e}) -- "
            f"NESSUNA asta verra' considerata finche' non lo sistemi.")
        return set()


LEAGUE_WHITELIST_SLUGS = load_league_whitelist()


# --- Parametri regolabili ---
AUCTION_DISCOUNT_FRACTION = float(os.environ.get('AUCTION_DISCOUNT_FRACTION', '0.27'))
LAST_AUCTION_REFERENCE_WINDOW_HOURS = float(os.environ.get('LAST_AUCTION_REFERENCE_WINDOW_HOURS', '24'))
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '18000'))
LISTEN_SECONDS = min(18000, LISTEN_SECONDS)
AUCTION_DIAGNOSTIC = os.environ.get('AUCTION_DIAGNOSTIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')

# FIX 21/07 (richiesta esplicita utente, test mirato): quando attivo, SOLO le aste con
# currentPrice == minNextBid (nessun bid mai piazzato) vengono valutate -- tutte le altre
# scartate silenziosamente PRIMA di qualunque log/query, cosi' nei log resta solo il
# segnale che interessa per capire se/quando il bot intercetta aste a 0 bid. Si applica
# a tutte e 3 le fonti (WS/SAFETY/ENDING-SOON) tramite process_incoming_auction. Non
# tocca whitelist/cooldown/calcolo bid, che restano identici per le aste che passano
# questo filtro.
TEST_ONLY_ZERO_BID = os.environ.get('TEST_ONLY_ZERO_BID', 'no').strip().lower() in ('1', 'true', 'yes', 'si')

# FIX 21/07 (richiesta esplicita utente): tetto massimo assoluto che il bot puo' mai
# offrire su UNA SINGOLA asta, indipendentemente da quanto alto risulti il calcolo
# (riferimento * (1-sconto)). Protezione contro riferimenti di mercato anomali (es. un
# singolo annuncio fuori mercato che alza il "minimo live" per errore/manipolazione).
MAX_BID_PER_AUCTION_EUR = float(os.environ.get('MAX_BID_PER_AUCTION_EUR', '20'))

# FIX 21/07 (richiesta esplicita utente, "voglio ascoltare anche aste a 0 bid gia'
# aperte, aperture in tempo reale, e le aste in scadenza"): tre fonti di aste che
# alimentano lo STESSO motore di valutazione (evaluate_auction) --
#  1) WebSocket tokenAuctionWasUpdated (gia' esistente) -- tempo reale, ma scatta solo
#     sui CAMBIAMENTI di un'asta (nuovo bid, o -- da verificare dal vivo, vedi log
#     [WS-POSSIBILE-APERTURA] -- apertura).
#  2) Safety poll: UNA volta sola all'avvio, TUTTE le aste live disponibili su Sorare
#     (paginato, vedi fetch_live_auctions_page) -- cattura le aste gia' aperte con 0
#     bid prima che il bot si mettesse in ascolto.
#  3) Ending-soon poll: ogni ENDING_SOON_POLL_INTERVAL_SECONDS secondi per tutta la
#     durata dell'ascolto, scandaglia di nuovo TUTTE le aste live disponibili (FIX 21/07,
#     richiesta esplicita utente: prima si fermava a 50 aste globali, e aste whitelist
#     valide come Evander/Carles Gil restavano invisibili perche' fuori da quella finestra
#     ristretta), filtrata SUBITO per whitelist campionati e poi ordinata per scadenza
#     piu' vicina, tenendo le prime ENDING_SOON_MAX_RESULTS.
ENDING_SOON_POLL_INTERVAL_SECONDS = float(os.environ.get('ENDING_SOON_POLL_INTERVAL_SECONDS', '120'))
ENDING_SOON_MAX_RESULTS = int(os.environ.get('ENDING_SOON_MAX_RESULTS', '40'))

# Ritardo prima della riverifica live pre-bid (stesso principio/stesso default del
# vecchio notificatore aste: il backend di Sorare a volte non e' ancora "consistente"
# se riletto a distanza di meno di un secondo dall'evento WS che l'ha segnalato).
AUCTION_RECHECK_DELAY_SECONDS = float(os.environ.get('AUCTION_RECHECK_DELAY_SECONDS', '3'))

# Stessa pausa random periodica "anti-martellamento" gia' presente nel bot buyer.
RANDOM_PAUSE_INTERVAL_SECONDS = int(os.environ.get('RANDOM_PAUSE_INTERVAL_SECONDS', '180'))
RANDOM_PAUSE_MIN_SECONDS = float(os.environ.get('RANDOM_PAUSE_MIN_SECONDS', '1'))
RANDOM_PAUSE_MAX_SECONDS = float(os.environ.get('RANDOM_PAUSE_MAX_SECONDS', '10'))

# --- Stop automatico su fondi insufficienti (stesso principio del bot buyer): un bid
# reale fallito per mancanza di fondi rende inutile continuare, ogni tentativo
# successivo fallirebbe uguale -- ci si ferma subito invece di continuare a vuoto.
INSUFFICIENT_FUNDS_STOP = [False]


# =====================================================================================
# GraphQL: throttle, sessione persistente, browser Playwright per le chiamate critiche
# (prepareBid/bid) -- infrastruttura IDENTICA a quella gia' validata nel bot buyer.
# =====================================================================================
GRAPHQL_MIN_INTERVAL_SECONDS = 0.35
_graphql_last_call_ts = [0.0]
_graphql_throttle_lock = threading.Lock()


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        wait = GRAPHQL_MIN_INTERVAL_SECONDS - (now - _graphql_last_call_ts[0])
        if wait > 0:
            time.sleep(wait)
        _graphql_last_call_ts[0] = time.time()


def graphql_query(query, variables=None, max_retries=3, extra_headers=None):
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
        r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            wait_seconds = min((2 ** attempt) * 2, 8.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


_playwright_instance = None
_playwright_browser = None
_playwright_page = None


def get_browser_page():
    """Apre un browser Chrome invisibile con i cookie di sessione gia' pronti -- stessa
    identica funzione del bot buyer (impronta browser vera per le chiamate critiche)."""
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
                'name': name.strip(), 'value': value.strip(),
                'domain': '.sorare.com', 'path': '/',
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


def graphql_query_via_browser(query, variables=None):
    """Chiamata GraphQL fatta DENTRO un vero browser Chrome (fetch()) invece che con
    curl_cffi/requests -- stessa tecnica del bot buyer, usata SOLO per le chiamate
    critiche del bid (prepareBid, bid) per l'impronta anti-fingerprint."""
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
        result = page.evaluate(js_code, [GRAPHQL_URL, payload, CSRF_TOKEN, SORARE_DEVICE_FINGERPRINT])
        body_text = result.get('body', '')
        return json.loads(body_text)
    except Exception as e:
        log(f"[playwright graphql] eccezione: {e}")
        return {"errors": [{"message": f"playwright_exception: {e}"}]}


# =====================================================================================
# Processo Node persistente per la firma -- infrastruttura IDENTICA a quella del bot
# buyer (stesso sorare-sign/decrypt_and_sign.js, stesso protocollo a righe NDJSON).
# =====================================================================================
_node_process = None
_node_process_lock = threading.Lock()
_node_stdout_queue = None
_node_stderr_tail = collections.deque(maxlen=20)
_decrypted_key_cache = {}
_encrypted_key_cache = {}
_exchange_rate_id_cache = {}


def _node_stdout_reader(proc, q):
    try:
        for line in proc.stdout:
            q.put(line)
    except Exception:
        pass
    q.put(None)


def _node_stderr_reader(proc, tail):
    try:
        for line in proc.stderr:
            tail.append(line.rstrip('\n'))
    except Exception:
        pass


def _ensure_node_sign_process():
    global _node_process, _node_stdout_queue
    if _node_process is not None and _node_process.poll() is None:
        return _node_process
    if _node_process is not None:
        log(f"[firma Node] il processo persistente precedente non e' piu' attivo "
            f"(codice uscita {_node_process.poll()}), lo riavvio -- ultime righe stderr: "
            f"{list(_node_stderr_tail)}")
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sorare-sign', 'decrypt_and_sign.js')
    log("[firma Node] avvio processo Node persistente per la firma...")
    proc = subprocess.Popen(
        ['node', script_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    q = queue.Queue()
    threading.Thread(target=_node_stdout_reader, args=(proc, q), daemon=True).start()
    threading.Thread(target=_node_stderr_reader, args=(proc, _node_stderr_tail), daemon=True).start()
    _node_process = proc
    _node_stdout_queue = q
    return proc


def close_node_sign_process():
    global _node_process
    with _node_process_lock:
        if _node_process is not None:
            try:
                if _node_process.poll() is None:
                    _node_process.stdin.close()
                    _node_process.wait(timeout=5)
            except Exception as e:
                log(f"[firma Node] errore chiudendo il processo persistente: {e}")
                try:
                    _node_process.kill()
                except Exception:
                    pass
            _node_process = None


def sign_authorization_via_node(password, encrypted_private_key, iv, salt, authorization_request):
    """Firma UNA authorization request tramite il processo Node persistente. Identica
    al bot buyer -- vedi commenti li' per il dettaglio del protocollo/ottimizzazioni."""
    global _node_process
    if 'decrypted_private_key' in _decrypted_key_cache:
        payload = {
            'decryptedPrivateKey': _decrypted_key_cache['decrypted_private_key'],
            'authorizationRequest': authorization_request,
        }
    else:
        payload = {
            'password': password, 'encryptedPrivateKey': encrypted_private_key,
            'iv': iv, 'salt': salt, 'authorizationRequest': authorization_request,
        }
    line = json.dumps(payload)

    with _node_process_lock:
        try:
            proc = _ensure_node_sign_process()
            q = _node_stdout_queue
            proc.stdin.write(line + '\n')
            proc.stdin.flush()
        except Exception as e:
            log(f"[firma Node] eccezione scrivendo la richiesta: {e}")
            try:
                if _node_process is not None:
                    _node_process.kill()
            except Exception:
                pass
            _node_process = None
            return None

        try:
            raw = q.get(timeout=30)
        except queue.Empty:
            log("[firma Node] timeout (30s) in attesa della risposta")
            try:
                proc.kill()
            except Exception:
                pass
            _node_process = None
            return None

        if raw is None:
            log(f"[firma Node] il processo e' terminato mentre aspettavo la risposta "
                f"(ultime righe stderr: {list(_node_stderr_tail)})")
            _node_process = None
            return None

    try:
        output = json.loads(raw.strip())
    except json.JSONDecodeError:
        log(f"[firma Node] risposta non JSON valida: {raw!r}")
        return None
    if 'error' in output:
        log(f"[firma Node] errore riportato dallo script: {output['error']}")
        return None
    if output.get('decryptedPrivateKey'):
        _decrypted_key_cache['decrypted_private_key'] = output['decryptedPrivateKey']
    return output.get('signature')


def sign_all_authorizations(authorizations):
    """Firma OGNI authorization request restituita da prepareBid (di solito una sola,
    come per prepareAcceptOffer nel bot buyer, ma la documentazione ufficiale Sorare
    mostra buildApprovals mappare su un ARRAY -- gestiamo quindi N authorization, non
    diamo per scontato che sia sempre esattamente una). Ritorna la lista di dict
    {fingerprint, signature} pronta per il campo 'approvals' della mutation bid, oppure
    None se anche una sola firma fallisce (fail-safe: un bid con firme parziali non
    avrebbe senso, meglio non tentarlo)."""
    key_data = fetch_encrypted_private_key()
    if not key_data:
        log("[firma bid] STOP: chiave cifrata non recuperata")
        return None
    approvals = []
    for auth in authorizations:
        fingerprint = auth.get('fingerprint')
        request = dict(auth.get('request') or {})
        request['__typename'] = 'MangopayWalletTransferAuthorizationRequest'
        signature = sign_authorization_via_node(
            SORARE_WALLET_PASSWORD, key_data.get('encryptedPrivateKey'),
            key_data.get('iv'), key_data.get('salt'), request,
        )
        if not signature:
            log(f"[firma bid] STOP: firma fallita per authorization fingerprint={fingerprint}")
            return None
        approvals.append({
            'fingerprint': fingerprint,
            'mangopayWalletTransferApproval': {
                'nonce': request.get('nonce'), 'signature': signature,
            },
        })
    return approvals


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
    """Identica al bot buyer -- cachata in memoria per l'intera run."""
    if 'key_data' in _encrypted_key_cache:
        return _encrypted_key_cache['key_data']
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
        log("[chiave cifrata] recuperata dal server e messa in cache per il resto della run")
        _encrypted_key_cache['key_data'] = key_data
        return key_data
    except Exception as e:
        log(f"[chiave cifrata] eccezione: {e}")
        return None


EXCHANGE_RATE_QUERY = """
query ExchangeRateQuery {
  config {
    exchangeRate { id }
  }
}
"""


def get_exchange_rate_id():
    """Identica al bot buyer -- cachata in memoria per l'intera run."""
    if 'id' in _exchange_rate_id_cache:
        return _exchange_rate_id_cache['id']
    try:
        data = graphql_query(EXCHANGE_RATE_QUERY)
        rate_id = (((data.get('data') or {}).get('config') or {}).get('exchangeRate') or {}).get('id')
        if rate_id:
            _exchange_rate_id_cache['id'] = rate_id
        return rate_id
    except Exception as e:
        log(f"[exchange rate] errore: {e}")
        return None


def classify_bid_error(root_errors, payload_errors):
    """Classifica gli errori di prepareBid/bid in categorie note -- stessa filosofia
    identica a classify_prepare_accept_error nel bot buyer: ogni categoria = STOP, mai
    retry automatico (un bid, una volta sola, mai ritirabile)."""
    all_errors = list(root_errors or []) + list(payload_errors or [])
    if not all_errors:
        return 'nessun_errore', all_errors
    combined_text = ' '.join(
        str(e.get('message', '')) + ' ' + str(e.get('extensions', {}).get('code', ''))
        for e in all_errors if isinstance(e, dict)
    ).lower()
    if any(kw in combined_text for kw in
           ('insufficient', 'not_enough', 'balance', 'fondi', 'saldo')):
        return 'fondi_insufficienti', all_errors
    if any(kw in combined_text for kw in
           ('currency', 'payment_method', 'unsupported', 'valuta')):
        return 'valuta_non_supportata', all_errors
    if any(kw in combined_text for kw in
           ('not_found', 'expired', 'already', 'closed', 'cancelled', 'unavailable', 'not_available')):
        return 'asta_non_disponibile', all_errors
    if any(kw in combined_text for kw in ('outbid', 'too_low', 'min_next_bid', 'higher')):
        return 'bid_troppo_basso', all_errors
    return 'sconosciuto', all_errors


def _is_insufficient_funds_error(error_message):
    if not error_message:
        return False
    return 'fondi_insufficienti' in str(error_message).lower()


# NOTA (21/07): mutation confermate dalla documentazione ufficiale Sorare
# (github.com/sorare/api, sezione "Bidding on auction") -- non sono state scoperte per
# tentativi, sono quelle documentate. Restano comunque da VALIDARE dal vivo in modalita'
# diagnostica prima del primo bid reale, come qualunque altra integrazione con un'API
# che non espone introspection: se qualcosa non torna (nome di campo cambiato,
# struttura leggermente diversa), il primo errore GraphQL incontrato in AUCTION_LIVE_MODE
# lo dira' chiaramente nei log, e va corretto qui.
PREPARE_BID_MUTATION = """
mutation PrepareBid($input: prepareBidInput!) {
  prepareBid(input: $input) {
    authorizations {
      fingerprint
      request {
        ... on MangopayWalletTransferAuthorizationRequest {
          currency
          fiatAmount
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

# FIX 21/07 (confermato con una cattura REALE e RIUSCITA di una BidWithWalletMutation
# dal vivo, mandata dall'utente): il campo root della mutation e' "bid", NON "tokenBid"
# come avevo scritto prima -- e' l'opposto di quello che avevo assunto per analogia con
# acceptOffer/prepareAcceptOffer. Il payload restituisce "tokenBid { id }" (con
# quest'ordine dei nomi, si', e' un po' confusionario ma e' quello confermato dal vivo).
BID_MUTATION = """
mutation BidWithWalletMutation($input: bidInput!) {
  bid(input: $input) {
    tokenBid { id }
    errors { message }
  }
}
"""


def prepare_bid(auction_id, amount_cents, exchange_rate_id):
    """FASE 1: prepara il bid lato server (PrepareBid), ottiene le authorization da
    firmare. Stesso schema a due fasi di prepare_accept_offer nel bot buyer.
    NOTA: 'amount' nella documentazione ufficiale Sorare e' un intero in WEI per gli
    esempi ETH, ma per i pagamenti in EUR/WALLET (stessa valuta usata ovunque nel bot
    buyer, confermato dall'utente per le aste) il pattern osservato in prepareAcceptOffer/
    prepareOffer e' sempre un intero in CENTESIMI di EUR -- qui amount_cents e' gia'
    l'intero in centesimi, coerente con quel pattern (CONFERMATO dal vivo il 21/07: una
    cattura reale di BidWithWalletMutation mostra esattamente amount="2476" per un bid
    di 24.76EUR).
    FIX 21/07 (v2, stessa cattura reale): settlementInfo nella mutation vera include
    ANCHE platform e useAvailableCredits, non solo currency/paymentMethod/exchangeRateId
    -- stessi due campi gia' usati in prepare_accept_offer/prepare_offer nel bot buyer,
    mancavano qui."""
    variables = {
        "input": {
            "auctionId": auction_id,
            "amount": str(amount_cents),
            "settlementInfo": {
                "currency": "EUR",
                "paymentMethod": "WALLET",
                "exchangeRateId": exchange_rate_id,
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        }
    }
    try:
        data = graphql_query_via_browser(PREPARE_BID_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('prepareBid') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_bid_error(root_errors, payload_errors)
            log(f"[prepare bid] fallita, categoria='{category}', errori={all_errors}")
            return None, category
        auths = payload.get('authorizations') or []
        if not auths:
            log("[prepare bid] nessuna authorization restituita")
            return None, 'sconosciuto'
        return auths, None
    except Exception as e:
        log(f"[prepare bid] eccezione: {e}")
        return None, 'sconosciuto'


def execute_bid(auction_id, amount_cents, exchange_rate_id, approvals):
    """FASE 2: chiama davvero la mutation bid con le approvals firmate. Fail-safe
    assoluto -- un solo tentativo, mai retry (un bid non e' ritirabile).
    FIX 21/07 (cattura reale di un bid vero e riuscito): niente clientMutationId
    nell'input reale osservato -- rimosso (non presente nella richiesta reale che ha
    funzionato). settlementInfo con platform/useAvailableCredits, stesso fix di
    prepare_bid sopra."""
    variables = {
        "input": {
            "approvals": approvals,
            "auctionId": auction_id,
            "amount": str(amount_cents),
            "settlementInfo": {
                "currency": "EUR",
                "paymentMethod": "WALLET",
                "exchangeRateId": exchange_rate_id,
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        }
    }
    try:
        data = graphql_query_via_browser(BID_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('bid') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_bid_error(root_errors, payload_errors)
            log(f"[bid] fallito, categoria='{category}', errori={all_errors}")
            return False, category, str(all_errors)
        bid_id = (payload.get('tokenBid') or {}).get('id')
        log(f"[bid] successo, bid id={bid_id}")
        return True, None, None
    except Exception as e:
        log(f"[bid] eccezione: {e}")
        return False, 'eccezione', str(e)


def execute_live_bid(auction_id, amount_eur):
    """Orchestrazione completa (attiva SOLO se AUCTION_LIVE_MODE='si'): exchange rate
    -> prepareBid -> firma di tutte le authorization -> bid. Fail-safe assoluto, un
    solo tentativo secco -- un bid non e' ritirabile."""
    log(f"[bid live] avvio -- auction_id={auction_id}, importo={amount_eur:.2f}EUR")
    if not SORARE_WALLET_PASSWORD:
        log("[bid live] STOP: SORARE_WALLET_PASSWORD non impostata")
        return False, "SORARE_WALLET_PASSWORD non impostata"

    exchange_rate_id = get_exchange_rate_id()
    if not exchange_rate_id:
        log("[bid live] STOP: exchange_rate_id non disponibile")
        return False, "exchange_rate_id non disponibile"

    amount_cents = int(round(amount_eur * 100))

    authorizations, prepare_category = prepare_bid(auction_id, amount_cents, exchange_rate_id)
    if not authorizations:
        return False, f"prepareBid fallita [{prepare_category}]"
    log(f"[bid live] step 1/3 OK: prepareBid ha restituito {len(authorizations)} "
        f"authorization da firmare")

    approvals = sign_all_authorizations(authorizations)
    if not approvals:
        return False, "firma fallita (vedi log [firma bid]/[firma Node] per il dettaglio)"
    log(f"[bid live] step 2/3 OK: {len(approvals)} authorization firmate")

    success, category, error = execute_bid(auction_id, amount_cents, exchange_rate_id, approvals)
    if not success:
        return False, f"bid mutation fallita [{category}]: {error}"
    log("[bid live] step 3/3 OK: bid piazzato con successo")
    return True, None


# =====================================================================================
# Prezzi -- multi-valuta (EUR/ETH/USD/GBP/SOL), identico al bot buyer/al notificatore
# aste esistente.
# =====================================================================================
_FIAT_RATE_CACHE = {}


def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5)
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
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur", timeout=5)
        rate = float(r.json()['solana']['eur'])
    except Exception:
        rate = 150.0
    _FIAT_RATE_CACHE['sol'] = rate
    return rate


def wei_to_eur(wei_value, eth_rate):
    if wei_value is None:
        return None
    try:
        return float(wei_value) / 1e18 * eth_rate
    except (TypeError, ValueError):
        return None


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        return wei_to_eur(amounts['wei'], eth_rate)
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


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log(f"Errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
            # FIX (caso reale: testo dinamico con '<'/'>' non previsti, es. "asta conclusa
            # <24h", ha rotto il parsing HTML e fatto fallire l'intero invio): se l'errore
            # e' proprio di parsing entita', ritento UNA volta senza parse_mode, cosi' il
            # messaggio arriva comunque (senza grassetto) invece di andare perso del tutto.
            if r.status_code == 400 and 'parse entities' in r.text.lower():
                payload_plain = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
                r2 = requests.post(url, json=payload_plain, timeout=10)
                if not r2.ok:
                    log(f"Errore invio Telegram (ritento senza HTML, HTTP {r2.status_code}): {r2.text[:500]}")
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


def build_card_link(player_slug, card_slug):
    """FIX 21/07 (pattern osservato su 3 casi reali dall'utente: Lorenzo Dellavalle
    -287/-288, Damario McIntosh -222/-223, e un terzo caso -- in tutti e tre anyCards
    restituiva il serial SBAGLIATO, sempre esattamente uno in meno di quello realmente
    in asta): il seriale finale dello slug carta viene incrementato di 1 di default per
    generare il link. Se il pattern smette di valere (link +1 che non esiste/404), va
    rivalutato -- non e' un campo GraphQL verificato, e' un'euristica su dati osservati."""
    corrected_slug = card_slug
    m = re.search(r'^(.*-)(\d+)$', card_slug)
    if m:
        prefix, serial = m.groups()
        corrected_slug = f"{prefix}{int(serial) + 1}"
    return f"https://sorare.com/it/football/players/{player_slug}?card={corrected_slug}"


# =====================================================================================
# Riferimento di mercato: minimo LIVE di vendita diretta in_season + ultima asta
# conclusa nelle ultime 24h (se piu' bassa, vince lei). Vedi note di design in cima al
# file.
# =====================================================================================
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } }
        senderSide {
          anyCards {
            rarityTyped
            sport
            inSeasonEligible
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
    all_nodes = []
    cursor = None
    for _ in range(MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[annunci live] errore per {player_slug}: {data['errors']}")
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


def get_live_min_direct_sale_in_season(player_slug, eth_rate):
    """Minimo REALE attualmente in vendita diretta, SOLO carte Limited in_season
    (inSeasonEligible=True) -- riferimento di mercato per il calcolo del bid. Ritorna
    None se non c'e' nessun annuncio in vendita diretta in_season per quel giocatore."""
    try:
        nodes = fetch_all_live_offers(player_slug)
        prices = []
        for node in nodes:
            if node.get('status') != 'opened':
                continue
            cards = (node.get('senderSide') or {}).get('anyCards') or []
            match = False
            for c in cards:
                if c.get('rarityTyped') != 'limited':
                    continue
                if c.get('sport') != 'FOOTBALL':
                    continue
                if not c.get('inSeasonEligible'):
                    continue
                match = True
                break
            if not match:
                continue
            price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
            if price is None:
                continue
            prices.append(price)
        if not prices:
            return None
        return min(prices)
    except Exception as e:
        log(f"[vendita diretta live] eccezione per {player_slug}: {e}")
        return None


# NOTA IMPORTANTE (21/07): query costruita unendo due varianti gia' viste funzionare
# separatamente altrove (tokens.tokenPrices con deal.__typename nel bot buyer, per
# distinguere un'asta conclusa da altre transazioni; amounts+date nel vecchio
# notificatore aste, per il prezzo). Non e' stata ancora verificata dal vivo con
# ENTRAMBI i gruppi di campi insieme nella stessa chiamata -- se il server la rifiuta,
# il primo errore GraphQL nei log lo dira' chiaramente (vedi validate_auction_schema
# piu' sotto, che la testa gia' all'avvio prima di iniziare ad ascoltare). Le aste
# valgono solo per carte Limited in_season (confermato dall'utente: "per le classic non
# esistono aste"), quindi ogni transazione di tipo TokenAuction qui e' automaticamente
# in_season -- nessun filtro stagione aggiuntivo necessario.
LAST_TRANSACTIONS_QUERY = """
query LastTransactionsQuery($p: String!) {
  tokens {
    tokenPrices(playerSlug: $p, rarity: limited) {
      date
      amounts { eurCents wei usdCents gbpCents lamport }
      deal {
        __typename
      }
    }
  }
}
"""


def get_last_concluded_auction_price(player_slug, eth_rate):
    """Prezzo dell'ultima asta CONCLUSA per questo giocatore, SOLO se conclusa entro
    LAST_AUCTION_REFERENCE_WINDOW_HOURS (default 24h) -- altrimenti None (riferimento
    troppo vecchio, ignorato, richiesta esplicita utente 21/07)."""
    try:
        data = graphql_query(LAST_TRANSACTIONS_QUERY, {"p": player_slug})
        if data.get('errors'):
            log(f"[ultima asta] errore GraphQL per {player_slug}: {data['errors']}")
            return None
        nodes = ((data.get('data') or {}).get('tokens') or {}).get('tokenPrices') or []
    except Exception as e:
        log(f"[ultima asta] eccezione per {player_slug}: {e}")
        return None

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=LAST_AUCTION_REFERENCE_WINDOW_HOURS)
    best_date = None
    best_price = None
    for n in nodes:
        deal = n.get('deal') or {}
        if deal.get('__typename') != 'TokenAuction':
            continue
        date_str = n.get('date') or ''
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        if dt < cutoff:
            continue
        if best_date is None or dt > best_date:
            price = eur_price_from_amounts(n.get('amounts'), eth_rate)
            if price is not None:
                best_date = dt
                best_price = price
    return best_price


def validate_auction_schema():
    """Self-check di avvio (stesso principio gia' validato nel bot buyer): prova le due
    query di riferimento (annunci live in_season + ultime transazioni con deal+amounts)
    su un giocatore reale PRIMA di aprire il websocket, cosi' un problema di schema si
    scopre in pochi secondi invece che dopo ore di ascolto a vuoto."""
    probe_slug = "kylian-mbappe"
    ok = True

    data = graphql_query(LIVE_OFFERS_QUERY, {"slug": probe_slug, "n": 1, "cursor": None})
    if data.get('errors'):
        msg = (f"[SELF-CHECK FALLITO] Query annunci live (inSeasonEligible) fallisce su "
               f"{probe_slug}: {data['errors']}")
        log(msg)
        send_telegram_msg(f"BOT SUPREMO ASTE -- ERRORE ALL'AVVIO\n\n{msg}")
        ok = False
    else:
        log("[self-check] Query annunci live (vendita diretta in_season) validata.")

    data3 = graphql_query(LIVE_AUCTIONS_QUERY, {"n": 1})
    if data3.get('errors'):
        msg = (f"[SELF-CHECK FALLITO] Query liveAuctions (usata da safety poll ed "
               f"ending-soon poll, include bidsCount) fallisce: {data3['errors']}. Il bot "
               f"potra' comunque contare sul solo WebSocket in tempo reale -- niente "
               f"cattura delle aste gia' aperte a 0 bid ne' scansione periodica delle "
               f"aste in scadenza.")
        log(msg)
        send_telegram_msg(f"BOT SUPREMO ASTE -- AVVISO ALL'AVVIO\n\n{msg}")
    else:
        log("[self-check] Query liveAuctions (safety poll + ending-soon poll, "
            "bidsCount incluso) validata.")

    data2 = graphql_query(LAST_TRANSACTIONS_QUERY, {"p": probe_slug})
    if data2.get('errors'):
        msg = (f"[SELF-CHECK FALLITO] Query ultime transazioni (deal.__typename + amounts "
               f"insieme) fallisce su {probe_slug}: {data2['errors']}. Il riferimento "
               f"'ultima asta conclusa nelle 24h' NON funzionera' finche' non si sistema "
               f"questa query -- il bot puo' comunque continuare usando SOLO il minimo "
               f"live come riferimento, ma e' meno preciso di quanto pensato.")
        log(msg)
        send_telegram_msg(f"BOT SUPREMO ASTE -- AVVISO ALL'AVVIO\n\n{msg}")
        # NON blocchiamo l'avvio per questo -- il minimo live da solo resta un
        # riferimento valido, solo meno completo. Il blocco vero scatta solo se
        # ANCHE gli annunci live falliscono (vedi sopra).
    else:
        log("[self-check] Query ultime transazioni (asta conclusa + prezzo) validata.")

    return ok


# =====================================================================================
# Ascolto WebSocket -- stesso canale/stesso schema di sottoscrizione del notificatore
# aste esistente, arricchito con inSeasonEligible e domesticLeague (serve alla whitelist
# campionati, non presente nella query originale).
# =====================================================================================
SUBSCRIPTION_QUERY = """
subscription OnTokenAuctionUpdated {
  tokenAuctionWasUpdated {
    id
    currentPrice
    minNextBid
    endDate
    open
    cancelled
    bidsCount
    anyCards {
      slug
      rarityTyped
      sport
      inSeasonEligible
      anyPlayer {
        slug
        displayName
        activeClub { domesticLeague { slug } }
      }
    }
  }
}
"""

AUCTION_BY_ID_QUERY = """
query GetAuctionById($id: String!) {
  tokens {
    auction(id: $id) {
      id
      currentPrice
      minNextBid
      endDate
      open
      cancelled
    }
  }
}
"""

# Stessa forma esatta di SUBSCRIPTION_QUERY sopra (stessi campi che evaluate_auction si
# aspetta), solo su liveAuctions invece che sull'evento websocket -- cosi' un'asta presa
# da un poll e un'asta presa dal WS sono indistinguibili per evaluate_auction.
LIVE_AUCTIONS_QUERY = """
query ListLiveAuctions($n: Int!, $cursor: String) {
  tokens {
    liveAuctions(last: $n, before: $cursor) {
      pageInfo { hasPreviousPage startCursor }
      nodes {
        id
        currentPrice
        minNextBid
        endDate
        open
        cancelled
        bidsCount
        anyCards {
          slug
          rarityTyped
          sport
          inSeasonEligible
          anyPlayer {
            slug
            displayName
            activeClub { domesticLeague { slug } }
          }
        }
      }
    }
  }
}
"""


LIVE_AUCTIONS_MAX_PAGES = int(os.environ.get('LIVE_AUCTIONS_MAX_PAGES', '40'))


def fetch_live_auctions_page(n):
    """RINOMINATA in sostanza -- ora pagina attraverso TUTTE le aste live disponibili
    (richiesta esplicita utente 21/07, dopo aver scoperto che Evander e Carles Gil,
    entrambe aste whitelist a 0 bid su giocatori di valore, non venivano mai viste
    perche' non rientravano nella finestra delle 50 aste piu' recenti su TUTTO Sorare,
    non filtrate per lega). Stessa tecnica di paginazione a cursore gia' validata su
    liveSingleSaleOffers (fetch_all_live_offers) -- prima pagina before=None, poi si
    avanza con pageInfo.startCursor finche' hasPreviousPage e' vero o si raggiunge
    LIVE_AUCTIONS_MAX_PAGES (tetto di sicurezza per non restare bloccati se il totale
    di aste live crescesse enormemente -- 40 pagine x 50 = 2000 aste, ben oltre il
    totale osservato finora su Sorare).
    'n' resta il nome storico del parametro ma ora e' la dimensione di OGNI pagina
    (sempre 50), non piu' il totale massimo recuperato."""
    all_nodes = []
    cursor = None
    pages_fetched = 0
    for _ in range(LIVE_AUCTIONS_MAX_PAGES):
        try:
            data = graphql_query(LIVE_AUCTIONS_QUERY, {"n": n, "cursor": cursor})
        except Exception as e:
            log(f"[liveAuctions] eccezione pagina {pages_fetched + 1}: {e}")
            break
        if data.get('errors'):
            log(f"[liveAuctions] errore pagina {pages_fetched + 1}: {data['errors']}")
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {})
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        pages_fetched += 1
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    log(f"[liveAuctions] {pages_fetched} pagine scansionate, {len(all_nodes)} aste totali")
    return all_nodes


def _seconds_until_end(end_date_str):
    if not end_date_str:
        return None
    try:
        end_dt = datetime.datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        return (end_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        return None


def _auction_league_slug(auction):
    """Stessa identica estrazione lega gia' usata dentro evaluate_auction -- fattorizzata
    qui per poter filtrare whitelist PRIMA di passare le aste a evaluate_auction (richiesta
    esplicita utente: filtro whitelist applicato subito, non dopo)."""
    cards = auction.get('anyCards') or []
    for c in cards:
        if c.get('rarityTyped') != 'limited' or c.get('sport') != 'FOOTBALL' or not c.get('inSeasonEligible'):
            continue
        player = c.get('anyPlayer') or {}
        return ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug', '').lower()
    return None


class _SharedListenerState:
    """Stato condiviso tra il thread WS (on_message, eseguito nel thread che chiama
    ws.run_forever) e il thread di background dell'ending-soon poll -- un solo lock per
    tutte le strutture condivise (seen_events per la dedup, known_auction_ids per il log
    diagnostico apertura asta, stats per i contatori)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seen_events = set()
        self.known_auction_ids = set()
        self.stats = {}


def process_incoming_auction(auction, eth_rate, state, source):
    """Punto di ingresso UNICO per tutte e 3 le fonti (WS/SAFETY/ENDING-SOON) -- dedup
    condivisa, log diagnostico apertura asta, poi delega a evaluate_auction. Cosi' la
    logica di dedup/valutazione resta scritta una volta sola."""
    if TEST_ONLY_ZERO_BID:
        # FIX 21/07 (richiesta esplicita utente, dopo cattura reale dal frontend Sorare):
        # bidsCount e' il campo ESATTO che Sorare stesso usa per indicare "zero offerte"
        # (confermato dal vivo: bidsCount=0 su Evander/Carles Gil, entrambe aste
        # autentiche a 0 bid; bidsCount=3 su un'asta con bid reali, GU SUNG YUN).
        # Sostituisce l'euristica precedente (currentPrice==minNextBid) che era solo un
        # segnale indiretto -- bidsCount e' il dato diretto, quando disponibile.
        bids_count = auction.get('bidsCount')
        if bids_count is not None:
            if bids_count != 0:
                return  # asta con bid reali gia' presenti -- scartata, modalita' test
        else:
            # Fallback se bidsCount non e' arrivato per qualche motivo (es. self-check
            # fallito su questo campo) -- torna all'euristica precedente invece di non
            # filtrare nulla.
            current_price = auction.get('currentPrice')
            min_next_bid = auction.get('minNextBid')
            if current_price is None or min_next_bid is None or current_price != min_next_bid:
                return

    auction_id = auction.get('id') or ''
    dedup_key = (auction_id, auction.get('currentPrice'), auction.get('minNextBid'), auction.get('endDate'))
    with state.lock:
        if dedup_key in state.seen_events:
            return
        state.seen_events.add(dedup_key)
        is_first_sighting = auction_id not in state.known_auction_ids
        state.known_auction_ids.add(auction_id)
        state.stats[f'source_{source.lower()}'] = state.stats.get(f'source_{source.lower()}', 0) + 1

    # NOTA (21/07, richiesta esplicita utente): NON abbiamo ancora la conferma dal vivo
    # che l'evento WS scatti anche all'APERTURA di un'asta (finora visto scattare solo
    # sui bid). Questo log NON e' una conferma -- e' un segnale da controllare a mano:
    # se un id arriva per la prima volta via WS (mai visto dal safety poll ne' da poll
    # precedenti), o e' un'asta appena aperta, o e' un'asta sfuggita al safety poll per
    # altri motivi. Solo un controllo manuale (guardando Sorare nello stesso momento)
    # puo' confermare quale dei due casi sia.
    if source == 'WS' and is_first_sighting and AUCTION_DIAGNOSTIC:
        cards = auction.get('anyCards') or []
        candidates = [(c.get('anyPlayer', {}).get('slug'), c.get('slug')) for c in cards
                      if c.get('anyPlayer', {}).get('slug') and c.get('slug')]
        link_hint = ""
        if len(candidates) > 1:
            slugs = ', '.join(c_slug for _, c_slug in candidates)
            link_hint = f", ATTENZIONE link ambiguo ({len(candidates)} carte candidate: {slugs})"
        if candidates:
            p_slug, c_slug = candidates[0]
            link_hint += f", link={build_card_link(p_slug, c_slug)}"
        log(f"[WS-POSSIBILE-APERTURA] primo avvistamento in questa run, id={auction_id}, "
            f"currentPrice={auction.get('currentPrice')}, minNextBid={auction.get('minNextBid')}, "
            f"endDate={auction.get('endDate')}{link_hint} -- verifica a mano se corrisponde a "
            f"un'asta appena aperta su Sorare in questo momento")

    try:
        evaluate_auction(auction, eth_rate, state.stats, source=source)
    except Exception as e:
        log(f"[{source}] Errore nel processare un'asta: {e}")


def run_safety_poll(eth_rate, state):
    """Scansione UNA TANTUM prima di aprire il WS: cattura le aste gia' aperte (incluse
    quelle a 0 bid) prima dell'avvio del bot. FIX 21/07 (richiesta esplicita utente,
    caso reale Evander/Carles Gil mai rilevati): ora scandaglia TUTTE le aste live
    disponibili (paginato), non solo le 50 piu' recenti su tutto Sorare."""
    log("[SAFETY] scansione di avvio: controllo TUTTE le aste live disponibili...")
    auctions = fetch_live_auctions_page(50)
    log(f"[SAFETY] {len(auctions)} aste trovate, valutazione in corso...")
    for auction in auctions:
        process_incoming_auction(auction, eth_rate, state, source='SAFETY')
    log("[SAFETY] scansione di avvio completata.")


def run_ending_soon_loop(eth_rate, state, stop_event):
    """Thread di background: ogni ENDING_SOON_POLL_INTERVAL_SECONDS, scandaglia TUTTE
    le aste live disponibili (paginato -- stesso fix del safety poll), filtro whitelist
    SUBITO, poi le ENDING_SOON_MAX_RESULTS piu' vicine alla scadenza vengono valutate."""
    while not stop_event.wait(ENDING_SOON_POLL_INTERVAL_SECONDS):
        try:
            page = fetch_live_auctions_page(50)
            whitelisted = [a for a in page if (_auction_league_slug(a) in LEAGUE_WHITELIST_SLUGS)]
            whitelisted.sort(key=lambda a: (_seconds_until_end(a.get('endDate')) is None,
                                             _seconds_until_end(a.get('endDate'))))
            selected = whitelisted[:ENDING_SOON_MAX_RESULTS]
            log(f"[ENDING-SOON] {len(page)} aste totali scandagliate, {len(whitelisted)} in whitelist, "
                f"valuto le {len(selected)} piu' vicine alla scadenza...")
            for auction in selected:
                process_incoming_auction(auction, eth_rate, state, source='ENDING-SOON')
        except Exception as e:
            log(f"[ENDING-SOON] errore nel ciclo di scansione: {e}")
    log("[ENDING-SOON] ciclo di scansione terminato.")


def get_auction_live_state(auction_id):
    """Rilegge lo stato REALE e aggiornato di un'asta -- usata come riverifica di
    sicurezza subito prima di un bid reale (un bid non e' ritirabile). Identica in
    spirito alla funzione gemella nel notificatore aste esistente."""
    bare_id = auction_id.split(':', 1)[1] if ':' in auction_id else auction_id
    try:
        data = graphql_query(AUCTION_BY_ID_QUERY, {"id": bare_id})
        if data.get('errors'):
            log(f"[riverifica live asta] errore GraphQL per {auction_id}: {data['errors']}")
            return None
        auction_data = ((data.get('data') or {}).get('tokens') or {}).get('auction')
        return auction_data
    except Exception as e:
        log(f"[riverifica live asta] eccezione per {auction_id}: {e}")
        return None


def send_startup_msg():
    modalita = "BID REALI ATTIVI" if AUCTION_LIVE_MODE else "solo diagnostica (nessun bid reale)"
    leagues = ', '.join(sorted(LEAGUE_WHITELIST_SLUGS)) or "NESSUNO (whitelist vuota!)"
    send_telegram_msg(
        f"\U0001F3C6 <b>Bot Supremo Aste avviato</b>\n"
        f"Modalita': {modalita}\n"
        f"Sconto target: {AUCTION_DISCOUNT_FRACTION:.0%} sotto il minimo di mercato\n"
        f"Tetto massimo per asta: {MAX_BID_PER_AUCTION_EUR:.2f}EUR\n"
        f"Campionati inclusi: {leagues}\n"
        f"Cooldown per giocatore: {AUCTION_COOLDOWN_HOURS:.0f}h\n"
        f"Ascolto fino a {LISTEN_SECONDS}s"
    )


def send_end_msg(stats):
    total_bid = stats.get('bid_placed', 0) + stats.get('bid_simulated', 0)
    skip_keys = sorted(k for k in stats if k.startswith('skip_'))
    breakdown = ', '.join(f"{k[5:]}={stats[k]}" for k in skip_keys) or "nessuno"
    send_telegram_msg(
        f"\U0001F3C1 <b>Bot Supremo Aste terminato</b>\n"
        f"Eventi processati: {stats.get('processed', 0)}\n"
        f"Bid {'reali' if AUCTION_LIVE_MODE else 'simulati'}: {total_bid}\n"
        f"Scarti: {breakdown}"
    )


def send_bid_alert(player_name, player_slug, card_slug, reference_price, reference_source,
                    bid_ceiling, min_next_bid, live_mode, bid_completed=None, bid_error=None,
                    seconds_left=None):
    link = build_card_link(player_slug, card_slug)
    intestazione = "\U0001F3AF <b>ASTA -- BID PIAZZATO</b>" if (live_mode and bid_completed) else \
        ("\u274C <b>ASTA -- BID FALLITO</b>" if (live_mode and bid_completed is False) else
         "\U0001F4CB <b>ASTA -- AVREI BIDDATO (diagnostica)</b>")
    righe = [
        intestazione,
        f"\U0001F464 {player_name}",
        f"\U0001F4B0 Riferimento mercato: {reference_price:.2f}EUR ({reference_source})",
        f"\U0001F3AF Tetto bid: {bid_ceiling:.2f}EUR ({AUCTION_DISCOUNT_FRACTION:.0%} sotto)",
        f"\U0001F4CA minNextBid attuale: {min_next_bid:.2f}EUR",
    ]
    if seconds_left is not None:
        ore = seconds_left / 3600
        righe.append(f"\u23F0 Tempo residuo asta: {ore:.1f}h")
    if live_mode and bid_completed is False:
        righe.append(f"Motivo: {bid_error}")
    righe.append(link)
    send_telegram_msg('\n'.join(righe))


def send_insufficient_funds_alert(player_name):
    send_telegram_msg(
        f"\U0001F6D1 <b>BOT SUPREMO ASTE -- FONDI INSUFFICIENTI</b>\n"
        f"Rilevato durante il bid su {player_name}. Bot fermato: nessun tentativo "
        f"successivo avrebbe senso."
    )


def evaluate_auction(auction, eth_rate, stats, source='WS'):
    """Valutazione completa di un'asta: filtri -> riferimento di mercato -> calcolo bid
    -> (diagnostica o bid reale). Ritorna True se e' stato un caso valido (bid piazzato
    o simulato), False se scartata per qualunque motivo.
    'source' indica solo da dove e' arrivata l'asta (WS/SAFETY/ENDING-SOON) -- usato per
    taggare i log, nessun impatto sulla logica di valutazione (richiesta esplicita utente:
    stesso motore per tutte e 3 le fonti)."""

    def vlog(message):
        """Log verboso per-fase, SOLO se AUCTION_DIAGNOSTIC e' attivo (richiesta esplicita
        utente, fase di test) -- su file di log, mai su Telegram (che resta minimale)."""
        if AUCTION_DIAGNOSTIC:
            log(f"[{source}] [diagnostica] {message}")

    if INSUFFICIENT_FUNDS_STOP[0]:
        return False

    auction_id = auction.get('id') or ''
    if not auction_id.startswith('EnglishAuction:'):
        return False

    cards = auction.get('anyCards') or []
    qualifying = []
    for c in cards:
        if c.get('rarityTyped') != 'limited':
            continue
        if c.get('sport') != 'FOOTBALL':
            continue
        if not c.get('inSeasonEligible'):
            continue  # le aste valgono solo per in_season -- carta classic, ignorata
        qualifying.append(c)
    if not qualifying:
        return False
    match = qualifying[0]

    # FIX 21/07 (caso reale, Lorenzo Dellavalle: anyCards conteneva DUE carte limited
    # in_season -287 e -288, il codice prendeva sempre la prima -- link mostrato NON
    # corrispondeva alla carta realmente in asta). NOTA: da questa modifica il link viene
    # generato con serial+1 (vedi build_card_link) basandosi sul pattern osservato su 3
    # casi reali -- non e' un campo GraphQL verificato, quindi il warning resta comunque
    # utile per un controllo manuale finche' il pattern non e' confermato su piu' casi.
    if len(qualifying) > 1:
        all_slugs = ', '.join(c.get('slug', '?') for c in qualifying)
        log(f"[{source}] ATTENZIONE -- {len(qualifying)} carte candidate per questa asta "
            f"(anyCards ambiguo): {all_slugs}. Uso la prima ({match.get('slug')}) con "
            f"correzione +1 sul link (euristica, non campo verificato) -- verificare a "
            f"mano finche' il pattern non e' confermato su piu' casi.")

    card_slug = match.get('slug')
    player = match.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
    if not player_slug:
        return False

    if not league_slug or league_slug.lower() not in LEAGUE_WHITELIST_SLUGS:
        stats['skip_campionato'] = stats.get('skip_campionato', 0) + 1
        return False

    vlog(f"{player_name}: campionato '{league_slug}' in whitelist, proseguo")

    if player_slug in BLACKLISTED_PLAYER_SLUGS_ASTE:
        log(f"[{source}] {player_name}: scarto -- giocatore in blacklist manuale ({player_slug})")
        stats['skip_blacklist'] = stats.get('skip_blacklist', 0) + 1
        return False

    if is_player_in_bid_cooldown(player_slug):
        log(f"[{source}] {player_name}: scarto -- gia' biddato nelle ultime "
            f"{AUCTION_COOLDOWN_HOURS:.0f}h")
        stats['skip_cooldown'] = stats.get('skip_cooldown', 0) + 1
        return False

    stats['processed'] = stats.get('processed', 0) + 1

    vlog(f"{player_name}: verifica del minimo di vendita diretta live in corso...")
    live_min = get_live_min_direct_sale_in_season(player_slug, eth_rate)
    vlog(f"{player_name}: minimo vendita diretta live = "
         f"{'%.2fEUR' % live_min if live_min is not None else 'nessuno trovato'}")

    vlog(f"{player_name}: verifica ultima asta conclusa (finestra "
         f"{LAST_AUCTION_REFERENCE_WINDOW_HOURS:.0f}h) in corso...")
    last_auction = get_last_concluded_auction_price(player_slug, eth_rate)
    vlog(f"{player_name}: ultima asta conclusa recente = "
         f"{'%.2fEUR' % last_auction if last_auction is not None else 'nessuna trovata'}")

    candidati = [(p, s) for p, s in
                 ((live_min, 'minimo live vendita diretta'), (last_auction, 'ultima asta conclusa entro 24h'))
                 if p is not None]
    if not candidati:
        log(f"[{source}] {player_name}: scarto -- nessun riferimento di mercato "
            f"disponibile (ne' vendita diretta live ne' asta conclusa nelle ultime "
            f"{LAST_AUCTION_REFERENCE_WINDOW_HOURS:.0f}h)")
        stats['skip_nessun_riferimento'] = stats.get('skip_nessun_riferimento', 0) + 1
        return False

    reference_price, reference_source = min(candidati, key=lambda t: t[0])
    if len(candidati) == 2:
        log(f"[{source}] {player_name}: riferimenti trovati -- live={live_min:.2f}EUR, "
            f"ultima asta={last_auction:.2f}EUR -- uso il piu' basso ({reference_source})")

    vlog(f"{player_name}: calcolo tetto bid -- riferimento {reference_price:.2f}EUR, "
         f"sconto {AUCTION_DISCOUNT_FRACTION:.0%}")
    bid_ceiling_calcolato = reference_price * (1 - AUCTION_DISCOUNT_FRACTION)
    bid_ceiling = min(bid_ceiling_calcolato, MAX_BID_PER_AUCTION_EUR)
    if bid_ceiling < bid_ceiling_calcolato:
        vlog(f"{player_name}: tetto calcolato {bid_ceiling_calcolato:.2f}EUR limitato al "
             f"massimo per asta di {MAX_BID_PER_AUCTION_EUR:.2f}EUR")

    min_next_bid_wei = auction.get('minNextBid')
    min_next_bid_eur = wei_to_eur(min_next_bid_wei, eth_rate)
    if min_next_bid_eur is None:
        log(f"[{source}] {player_name}: scarto -- minNextBid non leggibile")
        stats['skip_minnextbid_illeggibile'] = stats.get('skip_minnextbid_illeggibile', 0) + 1
        return False

    if bid_ceiling < min_next_bid_eur:
        # Richiesta esplicita utente (fase "tutte le aste" dopo il filtro 0-bid): per le
        # aste scartate per tetto insufficiente, log ridotto al solo link -- niente
        # righe di dettaglio (riferimento/tetto/minNextBid), per rendere il log leggibile
        # con volumi alti. Le aste che INVECE superano il tetto (occasioni vere) restano
        # con il log completo come prima, invariato.
        log(f"[{source}] {player_name}: link={build_card_link(player_slug, card_slug)}")
        stats['skip_tetto_insufficiente'] = stats.get('skip_tetto_insufficiente', 0) + 1
        return False

    log(f"[{source}] {player_name}: riferimento {reference_price:.2f}EUR ({reference_source}), "
        f"tetto bid {bid_ceiling:.2f}EUR (max per asta {MAX_BID_PER_AUCTION_EUR:.2f}EUR), "
        f"minNextBid attuale {min_next_bid_eur:.2f}EUR, link={build_card_link(player_slug, card_slug)}")

    seconds_left = None
    end_date = auction.get('endDate')
    if end_date:
        try:
            end_dt = datetime.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            seconds_left = (end_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        except (ValueError, TypeError):
            pass

    if not AUCTION_LIVE_MODE:
        log(f"[{source}] {player_name}: [DIAGNOSTICA] avrei biddato {bid_ceiling:.2f}EUR "
            f"su questa asta")
        send_bid_alert(player_name, player_slug, card_slug, reference_price, reference_source,
                        bid_ceiling, min_next_bid_eur, live_mode=False, seconds_left=seconds_left)
        stats['bid_simulated'] = stats.get('bid_simulated', 0) + 1
        return True

    # --- Modalita' live: riverifica di sicurezza prima del bid reale (non ritirabile) ---
    time.sleep(AUCTION_RECHECK_DELAY_SECONDS)
    fresh = get_auction_live_state(auction_id)
    if fresh is None:
        log(f"[{source}] {player_name}: scarto -- riverifica live fallita o asta non piu' "
            f"trovata, non biddo su dati non confermati")
        stats['skip_riverifica_fallita'] = stats.get('skip_riverifica_fallita', 0) + 1
        return False
    if not fresh.get('open') or fresh.get('cancelled'):
        log(f"[{source}] {player_name}: scarto -- asta non piu' aperta alla riverifica")
        stats['skip_asta_chiusa'] = stats.get('skip_asta_chiusa', 0) + 1
        return False
    fresh_min_next_bid_eur = wei_to_eur(fresh.get('minNextBid'), eth_rate)
    if fresh_min_next_bid_eur is not None and fresh_min_next_bid_eur > bid_ceiling:
        log(f"[{source}] {player_name}: scarto -- minNextBid salito sopra il tetto durante "
            f"la riverifica ({fresh_min_next_bid_eur:.2f}EUR > {bid_ceiling:.2f}EUR)")
        stats['skip_superato_in_riverifica'] = stats.get('skip_superato_in_riverifica', 0) + 1
        return False

    bid_completed, bid_error = execute_live_bid(auction_id, bid_ceiling)
    if bid_completed:
        log(f"[{source}] {player_name}: BID PIAZZATO CON SUCCESSO ({bid_ceiling:.2f}EUR)")
        record_player_bid(player_slug)
        stats['bid_placed'] = stats.get('bid_placed', 0) + 1
    else:
        log(f"[{source}] {player_name}: bid reale fallito -- {bid_error}")
        if _is_insufficient_funds_error(bid_error):
            log(f"[{source}] {player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot")
            INSUFFICIENT_FUNDS_STOP[0] = True
            send_insufficient_funds_alert(player_name)
        stats['bid_failed'] = stats.get('bid_failed', 0) + 1

    send_bid_alert(player_name, player_slug, card_slug, reference_price, reference_source,
                    bid_ceiling, min_next_bid_eur, live_mode=True,
                    bid_completed=bid_completed, bid_error=bid_error, seconds_left=seconds_left)
    return bool(bid_completed)


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY, "variables": {},
        "operationName": "OnTokenAuctionUpdated", "action": "execute",
    }
    state = _SharedListenerState()
    stats = state.stats  # stesso dict, solo un alias piu' corto per il resto della funzione

    # Safety poll -- una volta sola, PRIMA di aprire il WS (richiesta esplicita utente:
    # intercettare anche le aste gia' aperte a 0 bid prima dell'avvio).
    run_safety_poll(eth_rate, state)

    # Ending-soon poll -- in un thread separato, gira per tutta la durata dell'ascolto
    # (richiesta esplicita utente: rivalutare periodicamente le aste whitelist piu'
    # vicine alla scadenza, per non perdere quelle ferme che non generano eventi WS).
    ending_soon_stop = threading.Event()
    ending_soon_thread = threading.Thread(
        target=run_ending_soon_loop, args=(eth_rate, state, ending_soon_stop), daemon=True)
    ending_soon_thread.start()

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
            "command": "message", "identifier": identifier,
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

        try:
            auction = (payload.get('result', {}).get('data', {}) or {}).get('tokenAuctionWasUpdated')
            if not auction:
                return
            process_incoming_auction(auction, eth_rate, state, source='WS')
            maybe_random_pause()
            if INSUFFICIENT_FUNDS_STOP[0]:
                log("STOP: fondi insufficienti rilevati, chiudo la connessione")
                ws.close()
                return
        except Exception as e:
            log(f"[ERRORE in on_message] eccezione non gestita durante la valutazione "
                f"di un evento, la salto e continuo ad ascoltare: {e}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi processati: "
            f"{stats.get('processed', 0)}")
        total_bid = stats.get('bid_placed', 0) + stats.get('bid_simulated', 0)
        skip_keys = sorted(k for k in stats if k.startswith('skip_'))
        breakdown = ', '.join(f"{k[5:]}={stats[k]}" for k in skip_keys) or "nessuno"
        source_keys = sorted(k for k in stats if k.startswith('source_'))
        source_breakdown = ', '.join(f"{k[7:]}={stats[k]}" for k in source_keys) or "nessuno"
        log(f"[riepilogo] bid {'reali' if AUCTION_LIVE_MODE else 'simulati'}: {total_bid}, "
            f"bid falliti: {stats.get('bid_failed', 0)}, scarti: {breakdown}")
        log(f"[riepilogo] aste valutate per fonte: {source_breakdown}")

    ws = websocket.WebSocketApp(
        WS_URL, header=[f"Cookie: {COOKIES}"] if COOKIES else [],
        on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close,
    )
    timer = threading.Timer(LISTEN_SECONDS, ws.close)
    timer.daemon = True
    timer.start()
    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()
    ending_soon_stop.set()
    ending_soon_thread.join(timeout=5)
    return stats


def main():
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    modalita = "BID REALI ATTIVI" if AUCTION_LIVE_MODE else "solo diagnostica (nessun bid reale)"
    log(f"Bot Supremo Aste -- {modalita}")
    log(f"[network] curl_cffi (impronta TLS Chrome) "
        f"{'ATTIVO' if _HAS_CURL_CFFI else 'NON DISPONIBILE, uso requests standard'}")
    log(f"Sconto target: {AUCTION_DISCOUNT_FRACTION:.0%} sotto il riferimento di mercato")
    log(f"Finestra riferimento 'ultima asta conclusa': "
        f"{LAST_AUCTION_REFERENCE_WINDOW_HOURS:.0f}h")
    log(f"Cooldown per giocatore: {AUCTION_COOLDOWN_HOURS:.0f}h")
    log(f"Tetto massimo per asta: {MAX_BID_PER_AUCTION_EUR:.2f}EUR")
    log("Safety poll all'avvio: TUTTE le aste live disponibili (paginato)")
    log(f"Ending-soon poll: ogni {ENDING_SOON_POLL_INTERVAL_SECONDS:.0f}s su TUTTE le aste "
        f"live disponibili, max {ENDING_SOON_MAX_RESULTS} valutate")
    log(f"Log verbosi per-fase (AUCTION_DIAGNOSTIC): "
        f"{'ATTIVI' if AUCTION_DIAGNOSTIC else 'spenti'}")
    log(f"Modalita' TEST solo aste a 0 bid (TEST_ONLY_ZERO_BID): "
        f"{'ATTIVA -- tutte le altre aste vengono scartate silenziosamente' if TEST_ONLY_ZERO_BID else 'spenta'}")
    log(f"Campionati inclusi nella whitelist ({len(LEAGUE_WHITELIST_SLUGS)}): "
        f"{sorted(LEAGUE_WHITELIST_SLUGS)}")
    log(f"Giocatori in blacklist ({len(BLACKLISTED_PLAYER_SLUGS_ASTE)}): "
        f"{sorted(BLACKLISTED_PLAYER_SLUGS_ASTE)}")

    if not LEAGUE_WHITELIST_SLUGS:
        log("STOP: whitelist campionati vuota o illeggibile -- nessuna asta verrebbe mai "
            "considerata, non ha senso avviare l'ascolto. Controlla "
            f"{LEAGUE_WHITELIST_PATH}.")
        send_telegram_msg(
            "BOT SUPREMO ASTE -- STOP: whitelist campionati vuota o illeggibile, "
            f"controlla {LEAGUE_WHITELIST_PATH}.")
        return

    if AUCTION_LIVE_MODE:
        log("[playwright] pre-apertura browser all'avvio (ottimizzazione velocita')...")
        get_browser_page()
        log("[playwright] browser pronto e riscaldato")
        log("[precarico velocita'] recupero anticipato exchange_rate_id e chiave "
            "cifrata del wallet...")
        pre_rate_id = get_exchange_rate_id()
        if pre_rate_id:
            log(f"[precarico velocita'] exchange_rate_id gia' in cache: {pre_rate_id}")
        else:
            log("[precarico velocita'] ATTENZIONE: precarico exchange_rate_id fallito, "
                "verra' ritentato al primo bid reale")
        if SORARE_WALLET_PASSWORD:
            pre_key = fetch_encrypted_private_key()
            if pre_key:
                log("[precarico velocita'] chiave cifrata del wallet gia' in cache")
            else:
                log("[precarico velocita'] ATTENZIONE: precarico chiave cifrata fallito, "
                    "verra' ritentato al primo bid reale")
            with _node_process_lock:
                _ensure_node_sign_process()
            log("[precarico velocita'] processo Node persistente per la firma avviato")
        else:
            log("[precarico velocita'] SORARE_WALLET_PASSWORD non impostata -- ATTENZIONE: "
                "AUCTION_LIVE_MODE e' attivo ma nessun bid reale sara' possibile senza "
                "password wallet")

    if not validate_auction_schema():
        log("STOP: self-check dello schema GraphQL fallito sulla query essenziale "
            "(annunci live in_season) -- esco senza avviare l'ascolto.")
        return

    send_startup_msg()
    try:
        stats = run_listener(eth_rate)
        send_end_msg(stats)
        log("Ascolto terminato.")
    finally:
        close_browser()
        close_node_sign_process()


if __name__ == "__main__":
    main()
