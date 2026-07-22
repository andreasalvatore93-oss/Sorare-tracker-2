import json
import os
import re
import time
import datetime
import threading
import subprocess
import queue
import collections

import requests
from playwright.sync_api import sync_playwright

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# =====================================================================================
# BOT SUPREMO ASTE (21/07, RISCRITTO 21/07 v3) -- sniper per le aste inglesi di Sorare.
# =====================================================================================
# FIX 21/07 v3 (richiesta esplicita utente): rimosso il WebSocket in tempo reale --
# il bot ora funziona SOLO a scansioni GraphQL, organizzate in un ciclo continuo a 3
# fasi (vedi run_tracking_cycle piu' sotto). Quando trova un'asta che soddisfa i
# criteri, piazza DAVVERO un bid (se AUCTION_LIVE_MODE='si') usando la mutation
# ufficiale documentata da Sorare stessa (github.com/sorare/api): prepareBid -> firma
# -> bid (mutation tokenBid). Stessa infrastruttura di firma gia' pronta e testata nel
# bot buyer (bot_supremo.py): processo Node persistente per la firma, cache
# exchange_rate_id, sessione HTTP persistente, throttle GraphQL, browser Playwright
# per le chiamate critiche (anti-fingerprint).
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
# FIX 22/07 (richiesta esplicita utente, primi test con bid REALI: "cosi' anche se ci
# sono problemi non perdo molti soldi"): default abbassato da 20 a 10 EUR.
MAX_BID_PER_AUCTION_EUR = float(os.environ.get('MAX_BID_PER_AUCTION_EUR', '10'))

# FIX 21/07 (richiesta esplicita utente, "voglio ascoltare anche aste a 0 bid gia'
# aperte, aperture in tempo reale, e le aste in scadenza"): due fonti di aste che
# alimenta lo STESSO motore di valutazione (evaluate_auction).
# FIX 21/07 v5 (richiesta esplicita utente, "trova un modo per non perderti nessuna
# asta rilevante, senza appesantire, senza troppe notifiche"): rimosso il tetto di
# valutazione dalle fasi NUOVE e ZEROBID -- sono le due fasi che garantiscono la
# COPERTURA completa della whitelist, un tetto li' significava accumulare un arretrato
# che poteva far perdere aste vere (bid altrui nel frattempo, o scadenza prima del
# turno). SCADENZA_TOP_N resta invece un tetto voluto SOLO per la fase SCADENZA, che e'
# un "ultima chance" per le aste piu' urgenti, non il meccanismo di copertura primario.
# Per evitare il "delirio di notifiche" anche quando MOLTE aste sono appetibili insieme,
# le notifiche Telegram non partono piu' una per asta: si accorpano in UN SOLO messaggio
# per fase (vedi flush_phase_alerts), quindi al massimo 3 messaggi per ciclo completo,
# indipendentemente da quante occasioni vengono trovate.
#   FASE 1 "NUOVE": scan completo whitelist, valuta TUTTE le aste con id MAI visto
#     prima in questa run -- cattura le aperture appena immesse sul mercato, nessuna
#     esclusa.
#   pausa CYCLE_PAUSE_SECONDS
#   FASE 2 "ZEROBID": stessa scansione completa, valuta TUTTE le aste con bidsCount==0
#     (nuove o vecchie che siano, non solo quelle appena viste in FASE 1).
#   pausa CYCLE_PAUSE_SECONDS
#   FASE 3 "SCADENZA": stessa scansione completa, ordinata per scadenza piu' vicina,
#     valutate solo le prime SCADENZA_TOP_N (default 5) -- qui il tetto e' voluto.
#   pausa CYCLE_PAUSE_SECONDS
#   ricomincia da FASE 1. E' del tutto normale (e atteso) che le stesse aste in
#   scadenza ricompaiano identiche a fine ciclo in FASE 3 -- la dedup (vedi
#   process_incoming_auction) impedisce comunque una doppia notifica quando
#   currentPrice/minNextBid sono identici a un evento gia' notificato.
CYCLE_PHASE_SECONDS = float(os.environ.get('CYCLE_PHASE_SECONDS', '20'))
CYCLE_PAUSE_SECONDS = float(os.environ.get('CYCLE_PAUSE_SECONDS', '20'))
SCADENZA_TOP_N = int(os.environ.get('SCADENZA_TOP_N', '5'))

# FIX 22/07 v6 (caso reale: FASE NUOVE senza tetto puo' valutare migliaia di aste in una
# sola volta, un flush solo a fine fase avrebbe ritardato la notifica di minuti): le
# occasioni DIAGNOSTICHE restano accorpate in un solo messaggio, ma vengono comunque
# spedite ogni ALERT_FLUSH_INTERVAL_SECONDS anche a META' fase, non solo alla fine.
ALERT_FLUSH_INTERVAL_SECONDS = float(os.environ.get('ALERT_FLUSH_INTERVAL_SECONDS', '30'))


# Ritardo prima della riverifica live pre-bid (il backend di Sorare a volte non e'
# ancora "consistente" se riletto a distanza di meno di un secondo dalla scansione che
# ha segnalato l'occasione).
AUCTION_RECHECK_DELAY_SECONDS = float(os.environ.get('AUCTION_RECHECK_DELAY_SECONDS', '3'))

# --- Stop automatico su fondi insufficienti (stesso principio del bot buyer): un bid
# reale fallito per mancanza di fondi rende inutile continuare, ogni tentativo
# successivo fallirebbe uguale -- ci si ferma subito invece di continuare a vuoto.
INSUFFICIENT_FUNDS_STOP = [False]

# FIX 22/07 (richiesta esplicita utente, primi test con bid REALI su aste vere: "max 1
# asta su cui biddare per run... andiamo per tentativi"): tetto al numero di TENTATIVI
# di bid reale (non di valutazioni diagnostiche) per l'intera durata della run -- una
# volta raggiunto, il bot continua a girare e a valutare/notificare in diagnostica come
# sempre, ma non tenta piu' nessun bid reale aggiuntivo. Contatore incrementato subito
# PRIMA di chiamare execute_live_bid (quindi conta i TENTATIVI, non solo i successi --
# un tentativo fallito consuma comunque il tetto, e' comunque un test completato).
MAX_BIDS_PER_RUN = int(os.environ.get('MAX_BIDS_PER_RUN', '1'))
BIDS_ATTEMPTED_THIS_RUN = [0]
_bids_attempted_lock = threading.Lock()


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


# NOTA (21/07, RIVISTA 22/07 confrontando col bot buyer): mutation basata sulla
# documentazione ufficiale Sorare (github.com/sorare/api). FIX 22/07 (richiesta
# esplicita utente, "proviamo a configurare sfruttando quel codice"): il campo era
# 'fiatAmount', MAI validato dal vivo -- confrontando con le DUE mutation dello stesso
# tipo (MangopayWalletTransferAuthorizationRequest) gia' CONFERMATE dal vivo nel bot
# buyer (PrepareAcceptOfferMutation e PrepareOfferMutation, entrambe con acquisti/offerte
# reali riusciti), il campo si chiama SEMPRE 'amount', mai 'fiatAmount' -- corretto qui
# per coerenza. Resta comunque da confermare con un primo bid reale: se il nome fosse
# ancora sbagliato, il primo errore GraphQL in AUCTION_LIVE_MODE lo dira' chiaramente.
PREPARE_BID_MUTATION = """
mutation PrepareBid($input: prepareBidInput!) {
  prepareBid(input: $input) {
    authorizations {
      fingerprint
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


def build_card_link(player_slug, card_slug, serial_number=None):
    """FIX 21/07, REVISIONATO 21/07 dopo nuovo caso reale (Ryan Porteous): l'euristica
    "+1 sempre" (basata su 3 casi osservati dove il serial nello slug era sempre uno in
    meno di quello vero) NON regge in generale -- su Porteous lo scarto era di 2, non di
    1, a conferma che affidarsi al pattern dello slug e' intrinsecamente inaffidabile.

    Fix definitivo: la query ora richiede anche il campo serialNumber (Int), verificato
    dal self-check di avvio (validate_auction_schema, sulla query liveAuctions) --
    quando disponibile e' quello il valore giusto da usare per costruire il link, il
    numero di serie non va piu' indovinato dallo slug in nessun modo.

    Fallback (solo se per qualche motivo serial_number non arriva, es. errore API): usa
    lo slug cosi' com'e', SENZA alcuna correzione euristica -- meglio un link
    potenzialmente col serial originale (a volte sbagliato di un numero non prevedibile)
    che uno "corretto" con un'euristica ormai nota per essere inaffidabile."""
    corrected_slug = card_slug
    if serial_number is not None:
        m = re.search(r'^(.*-)(\d+)$', card_slug)
        if m:
            prefix, _old_serial = m.groups()
            corrected_slug = f"{prefix}{int(serial_number)}"
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
        if AUCTION_DIAGNOSTIC:
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
            # FIX 21/07 v5 (richiesta esplicita utente, "il log e' troppo pesante"):
            # questo errore e' FREQUENTE e NORMALE (tanti giocatori, specie in leghe di
            # nicchia, non hanno alcuna transazione registrata) -- non blocca nulla, il
            # bot ricade sul minimo live. Log spostato dietro AUCTION_DIAGNOSTIC.
            if AUCTION_DIAGNOSTIC:
                log(f"[ultima asta] errore GraphQL per {player_slug}: {data['errors']}")
            return None
        nodes = ((data.get('data') or {}).get('tokens') or {}).get('tokenPrices') or []
    except Exception as e:
        if AUCTION_DIAGNOSTIC:
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
    """Self-check di avvio (stesso principio gia' validato nel bot buyer): prova le
    query di riferimento PRIMA di iniziare il ciclo di tracking, cosi' un problema di
    schema si scopre in pochi secondi invece che dopo ore di ascolto a vuoto.
    FIX 22/07 (richiesta esplicita utente, "quella cosa di mbappe e' fastidiosa e
    inutile"): rimosso il probe su LAST_TRANSACTIONS_QUERY con kylian-mbappe -- dava
    SEMPRE "Player not found" (probabile causa: quella query ha bisogno di un
    giocatore con transazioni reali di tipo TokenAuction, Mbappe' probabilmente non ne
    ha mai avute), generando un falso allarme (log + notifica Telegram) ad OGNI singolo
    avvio nonostante la query funzioni perfettamente sui giocatori veri -- confermato
    dal vivo in produzione, dove 'ultima asta conclusa' viene trovata correttamente per
    decine di giocatori whitelist ogni run. Non era comunque mai bloccante."""
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
        # FIX 21/07 v3 (WebSocket rimosso): questa query ora e' l'UNICA fonte di dati
        # per tutte e 3 le fasi del ciclo (NUOVE/ZEROBID/SCADENZA) -- un suo fallimento
        # non e' piu' un avviso, blocca l'avvio (prima poteva contare sul WS come
        # fallback, ora non piu').
        msg = (f"[SELF-CHECK FALLITO] Query liveAuctions (usata da TUTTE le fasi del "
               f"ciclo di tracking, include bidsCount) fallisce: {data3['errors']}. "
               f"Senza questa query il bot non ha alcuna fonte di dati -- blocco l'avvio.")
        log(msg)
        send_telegram_msg(f"BOT SUPREMO ASTE -- ERRORE ALL'AVVIO\n\n{msg}")
        ok = False
    else:
        log("[self-check] Query liveAuctions (usata da tutte e 3 le fasi del ciclo, "
            "bidsCount incluso) validata.")

    return ok


# =====================================================================================
# Query per lo scan periodico (usate da tutte e 3 le fasi del ciclo di tracking) --
# arricchite con inSeasonEligible e domesticLeague (serve alla whitelist campionati) e
# serialNumber (serve al link carta corretto, vedi build_card_link).
# =====================================================================================
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
          serialNumber
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


LIVE_AUCTIONS_MAX_PAGES = int(os.environ.get('LIVE_AUCTIONS_MAX_PAGES', '200'))


def fetch_live_auctions_page(n):
    """RINOMINATA in sostanza -- ora pagina attraverso TUTTE le aste live disponibili
    (richiesta esplicita utente 21/07, dopo aver scoperto che Evander e Carles Gil,
    entrambe aste whitelist a 0 bid su giocatori di valore, non venivano mai viste
    perche' non rientravano nella finestra delle 50 aste piu' recenti su TUTTO Sorare,
    non filtrate per lega). Stessa tecnica di paginazione a cursore gia' validata su
    liveSingleSaleOffers (fetch_all_live_offers) -- prima pagina before=None, poi si
    avanza con pageInfo.startCursor finche' hasPreviousPage e' vero o si raggiunge
    LIVE_AUCTIONS_MAX_PAGES (tetto di sicurezza per non restare bloccati se il totale
    di aste live crescesse enormemente).
    FIX 21/07 v3 (caso reale osservato: mercato con 2000+ aste live su TUTTO Sorare, il
    vecchio tetto di 40 pagine/2000 aste veniva raggiunto ARTIFICIALMENTE -- non era la
    fine naturale della paginazione, quindi aste whitelist oltre quella soglia
    restavano invisibili): tetto alzato a 200 pagine (10000 aste), e il log ora dice
    ESPLICITAMENTE se lo stop e' dovuto al tetto (possibile dato incompleto) o alla
    fine naturale della paginazione (dato completo).
    'n' resta il nome storico del parametro ma ora e' la dimensione di OGNI pagina
    (sempre 50), non piu' il totale massimo recuperato."""
    all_nodes = []
    cursor = None
    pages_fetched = 0
    hit_page_cap = True
    for _ in range(LIVE_AUCTIONS_MAX_PAGES):
        try:
            data = graphql_query(LIVE_AUCTIONS_QUERY, {"n": n, "cursor": cursor})
        except Exception as e:
            log(f"[liveAuctions] eccezione pagina {pages_fetched + 1}: {e}")
            hit_page_cap = False
            break
        if data.get('errors'):
            log(f"[liveAuctions] errore pagina {pages_fetched + 1}: {data['errors']}")
            hit_page_cap = False
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {})
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        pages_fetched += 1
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            hit_page_cap = False
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            hit_page_cap = False
            break
    if hit_page_cap:
        log(f"[liveAuctions] ATTENZIONE -- tetto di {LIVE_AUCTIONS_MAX_PAGES} pagine "
            f"raggiunto ({len(all_nodes)} aste), la paginazione NON era finita: possibili "
            f"aste oltre questo punto non incluse in questa scansione. Se capita spesso, "
            f"alzare LIVE_AUCTIONS_MAX_PAGES.")
    else:
        log(f"[liveAuctions] {pages_fetched} pagine scansionate, {len(all_nodes)} aste "
            f"totali (paginazione completata)")
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
    """Stato condiviso tra le 3 fasi del ciclo di tracking (FIX 21/07 v3: ora un ciclo
    sequenziale in un solo thread, il lock resta comunque per sicurezza) -- seen_events
    per la dedup notifiche, known_auction_ids per riconoscere le aste "nuove" in FASE 1,
    stats per i contatori, pending_alerts per accumulare le occasioni DIAGNOSTICHE
    trovate (i bid REALI notificano subito, mai accorpati -- vedi evaluate_auction),
    last_flush_ts per il flush periodico (FIX 22/07 v6, caso reale osservato: con FASE
    NUOVE senza tetto e migliaia di aste candidate, un flush solo a fine fase poteva
    ritardare la notifica di minuti -- ora si flush anche a intervalli, non solo a
    fine fase)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seen_events = set()
        self.known_auction_ids = set()
        self.stats = {}
        self.pending_alerts = []
        self.last_flush_ts = time.monotonic()


def process_incoming_auction(auction, eth_rate, state, source):
    """Punto di ingresso UNICO per tutte e 3 le fasi del ciclo (NUOVE/ZEROBID/SCADENZA)
    -- dedup condivisa, log di rilevamento, poi delega a evaluate_auction. Cosi' la
    logica di dedup/valutazione resta scritta una volta sola.

    FIX 21/07 v3 (richiesta esplicita utente: "non notificare mai due volte la stessa
    asta, solo se prezzo/minNextBid sono identici a un evento gia' notificato"): dedup
    key = (auction_id, currentPrice, minNextBid) -- SENZA endDate (a differenza della
    versione precedente), cosi' un'asta che ricompare identica in una fase successiva
    o in un ciclo successivo (es. le stesse aste in scadenza a fine ciclo) viene
    riconosciuta come gia' vista e non rielaborata ne' rinotificata. Se invece
    currentPrice o minNextBid cambiano (nuovo bid altrui nel frattempo), la chiave e'
    diversa e l'asta viene rivalutata/rinotificata normalmente -- e' un'informazione
    nuova, non un duplicato."""
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
    dedup_key = (auction_id, auction.get('currentPrice'), auction.get('minNextBid'))
    with state.lock:
        if dedup_key in state.seen_events:
            if AUCTION_DIAGNOSTIC:
                log(f"[{source}] [GIA-VISTA] id={auction_id}, prezzo/minNextBid invariati "
                    f"rispetto a un evento gia' notificato -- skip, nessuna doppia notifica")
            return
        state.seen_events.add(dedup_key)
        state.known_auction_ids.add(auction_id)
        state.stats[f'source_{source.lower()}'] = state.stats.get(f'source_{source.lower()}', 0) + 1

    # FIX 21/07 v5 (richiesta esplicita utente, "il log e' troppo pesante, troppe
    # scritte"): questo log per-asta ora e' SOLO in diagnostica (era sempre attivo dalla
    # v2) -- di default il ciclo mostra solo il riepilogo di fase e le vere occasioni
    # trovate, non piu' una riga per ogni singola asta scandagliata.
    if AUCTION_DIAGNOSTIC:
        cards = auction.get('anyCards') or []
        candidates = [(c.get('anyPlayer', {}).get('slug'), c.get('anyPlayer', {}).get('displayName'),
                       c.get('slug'), c.get('serialNumber'))
                      for c in cards if c.get('anyPlayer', {}).get('slug') and c.get('slug')]
        if candidates:
            p_slug, p_name, c_slug, c_serial = candidates[0]
            detect_link = build_card_link(p_slug, c_slug, c_serial)
            ambiguo = f" [ATTENZIONE: {len(candidates)} carte candidate, uso la prima]" if len(candidates) > 1 else ""
            log(f"[{source}] [RILEVATA] {p_name or p_slug}, bidsCount={auction.get('bidsCount')}, "
                f"currentPrice={auction.get('currentPrice')}, minNextBid={auction.get('minNextBid')}, "
                f"endDate={auction.get('endDate')}, link={detect_link}{ambiguo}")

    try:
        evaluate_auction(auction, eth_rate, state, source=source)
    except Exception as e:
        log(f"[{source}] Errore nel processare un'asta: {e}")


def _fetch_whitelisted_live_auctions():
    """Scansione completa (paginata) di TUTTE le aste live disponibili, filtrata SUBITO
    per whitelist campionati -- base comune per tutte e 3 le fasi del ciclo."""
    page = fetch_live_auctions_page(50)
    whitelisted = [a for a in page if (_auction_league_slug(a) in LEAGUE_WHITELIST_SLUGS)]
    return page, whitelisted


def run_new_auctions_phase(eth_rate, state):
    """FASE 1 "NUOVE" (FIX 21/07 v5, richiesta esplicita utente: "non perdersi nessuna
    asta rilevante"): scan completo whitelist, valuta TUTTE le aste con id MAI visto
    prima in questa run -- nessun tetto, cattura ogni apertura appena immessa sul
    mercato, senza accumulare arretrato. Le notifiche diagnostiche vengono accorpate,
    ma spedite anche a meta' fase (vedi maybe_flush_alerts), non solo alla fine."""
    page, whitelisted = _fetch_whitelisted_live_auctions()
    nuove = [a for a in whitelisted if (a.get('id') or '') not in state.known_auction_ids]
    log(f"[NUOVE] {len(page)} aste totali, {len(whitelisted)} in whitelist, "
        f"{len(nuove)} mai viste prima -- valuto tutte")
    for auction in nuove:
        process_incoming_auction(auction, eth_rate, state, source='NUOVE')
        maybe_flush_alerts('NUOVE', state)
    flush_phase_alerts('NUOVE', state)


def run_zero_bid_phase(eth_rate, state):
    """FASE 2 "ZEROBID" (FIX 21/07 v5): scan completo whitelist, valuta TUTTE le aste
    con bidsCount==0 -- nuove o vecchie che siano, nessun tetto (stesso motivo di FASE
    1: non perdere occasioni). Notifiche diagnostiche accorpate, con flush anche a
    meta' fase."""
    page, whitelisted = _fetch_whitelisted_live_auctions()
    zero_bid = [a for a in whitelisted if a.get('bidsCount') == 0]
    log(f"[ZEROBID] {len(page)} aste totali, {len(whitelisted)} in whitelist, "
        f"{len(zero_bid)} a 0 bid -- valuto tutte")
    for auction in zero_bid:
        process_incoming_auction(auction, eth_rate, state, source='ZEROBID')
        maybe_flush_alerts('ZEROBID', state)
    flush_phase_alerts('ZEROBID', state)


def run_ending_soon_phase(eth_rate, state):
    """FASE 3 "SCADENZA" (FIX 21/07 v5): unica fase che resta CAPPATA (SCADENZA_TOP_N,
    default 5) -- a differenza di NUOVE/ZEROBID, qui il tetto e' voluto: e' un
    ulteriore "ultima chance" per le aste piu' urgenti, non il meccanismo primario di
    copertura (quello lo fanno NUOVE+ZEROBID, entrambe senza tetto). E' normale/atteso
    che le stesse aste ricompaiano identiche da un ciclo all'altro se nessuno ha
    rilanciato -- la dedup in process_incoming_auction evita la doppia notifica."""
    _, whitelisted = _fetch_whitelisted_live_auctions()
    whitelisted.sort(key=lambda a: (_seconds_until_end(a.get('endDate')) is None,
                                     _seconds_until_end(a.get('endDate'))))
    selected = whitelisted[:SCADENZA_TOP_N]
    log(f"[SCADENZA] {len(whitelisted)} in whitelist, valuto le {len(selected)} piu' "
        f"vicine alla scadenza...")
    for auction in selected:
        process_incoming_auction(auction, eth_rate, state, source='SCADENZA')
        maybe_flush_alerts('SCADENZA', state)
    flush_phase_alerts('SCADENZA', state)


def _run_timed_phase(phase_name, phase_fn, eth_rate, state):
    """Esegue UNA scansione della fase (FIX 21/07 v3, richiesta esplicita utente: "una
    scansione sola, poi aspetta fino a fine dei 20s"), poi ritorna quanti secondi
    restano per completare la finestra CYCLE_PHASE_SECONDS -- il chiamante attende
    quel resto prima di passare alla pausa tra le fasi."""
    start = time.monotonic()
    try:
        phase_fn(eth_rate, state)
    except Exception as e:
        log(f"[{phase_name}] errore nella scansione: {e}")
    elapsed = time.monotonic() - start
    remaining = CYCLE_PHASE_SECONDS - elapsed
    if remaining <= 0:
        log(f"[{phase_name}] scansione durata {elapsed:.1f}s (>= finestra di "
            f"{CYCLE_PHASE_SECONDS:.0f}s) -- nessuna attesa aggiuntiva")
        return 0.0
    return remaining


def run_tracking_cycle(eth_rate, state, stop_event):
    """FIX 21/07 v3 (richiesta esplicita utente, WebSocket rimosso): ciclo continuo a
    TRE fasi -- NUOVE -> pausa -> ZEROBID -> pausa -> SCADENZA -> pausa -> ricomincia
    da NUOVE, per tutta la durata dell'ascolto."""
    fasi = (
        ('NUOVE', run_new_auctions_phase),
        ('ZEROBID', run_zero_bid_phase),
        ('SCADENZA', run_ending_soon_phase),
    )
    while not stop_event.is_set():
        for phase_name, phase_fn in fasi:
            remaining = _run_timed_phase(phase_name, phase_fn, eth_rate, state)
            if INSUFFICIENT_FUNDS_STOP[0]:
                log("STOP: fondi insufficienti rilevati, fermo il ciclo di tracking")
                stop_event.set()
                break
            if remaining > 0 and stop_event.wait(remaining):
                break
            if stop_event.wait(CYCLE_PAUSE_SECONDS):
                break
        else:
            continue
        break
    log("[ciclo tracking] terminato.")


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
        f"Max bid reali per questa run: {MAX_BIDS_PER_RUN}\n"
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
                    seconds_left=None, card_serial_number=None):
    """FIX 21/07 v5 (richiesta esplicita utente, "senza troppe notifiche"): NON invia
    piu' il messaggio Telegram direttamente -- ritorna il testo composto, che il
    chiamante accoda a state.pending_alerts. L'invio vero avviene UNA volta a fine
    fase, in flush_phase_alerts, accorpando tutte le occasioni trovate in quella fase
    in un solo messaggio."""
    link = build_card_link(player_slug, card_slug, card_serial_number)
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
    return '\n'.join(righe)


def flush_phase_alerts(phase_name, state):
    """FIX 21/07 v5: invia UN SOLO messaggio Telegram con TUTTE le occasioni accumulate
    in state.pending_alerts durante questa fase, poi svuota la lista. Se la fase non ha
    trovato nulla, non manda nessun messaggio (silenzio, non spam)."""
    if not state.pending_alerts:
        return
    n = len(state.pending_alerts)
    parola = "occasione trovata" if n == 1 else "occasioni trovate"
    intestazione = f"\U0001F4CB <b>FASE {phase_name}</b> -- {n} {parola}"
    corpo = '\n\n\u2500\u2500\u2500\u2500\u2500\n\n'.join(state.pending_alerts)
    send_telegram_msg(f"{intestazione}\n\n{corpo}")
    state.pending_alerts.clear()
    state.last_flush_ts = time.monotonic()


def maybe_flush_alerts(phase_name, state):
    """FIX 22/07 v6 (richiesta esplicita utente, dopo un caso reale di notifica mai
    arrivata in tempo utile): da chiamare dopo OGNI singola asta valutata dentro il
    ciclo di una fase, non solo alla fine -- se sono passati almeno
    ALERT_FLUSH_INTERVAL_SECONDS dall'ultimo invio E c'e' almeno un'occasione in coda,
    manda subito quello che c'e' invece di aspettare la fine dell'intera fase (che con
    FASE NUOVE/ZEROBID senza tetto puo' richiedere minuti su migliaia di aste)."""
    if not state.pending_alerts:
        return
    if time.monotonic() - state.last_flush_ts >= ALERT_FLUSH_INTERVAL_SECONDS:
        flush_phase_alerts(phase_name, state)


def send_insufficient_funds_alert(player_name):
    send_telegram_msg(
        f"\U0001F6D1 <b>BOT SUPREMO ASTE -- FONDI INSUFFICIENTI</b>\n"
        f"Rilevato durante il bid su {player_name}. Bot fermato: nessun tentativo "
        f"successivo avrebbe senso."
    )


def evaluate_auction(auction, eth_rate, state, source='WS'):
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

    stats = state.stats  # alias, resto della funzione invariato

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
    card_serial_number = match.get('serialNumber')
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
        # FIX 21/07 v5 (richiesta esplicita utente, "il log e' troppo pesante"): questo
        # e' lo scarto PIU' FREQUENTE in assoluto (la maggior parte delle aste non e'
        # abbastanza sotto prezzo) -- di default nessun log per-asta, solo il contatore
        # aggregato (visibile nel riepilogo di fine run). Il dettaglio resta disponibile
        # con AUCTION_DIAGNOSTIC=si.
        if AUCTION_DIAGNOSTIC:
            log(f"[{source}] {player_name}: scarto -- tetto insufficiente, "
                f"link={build_card_link(player_slug, card_slug, card_serial_number)}")
        stats['skip_tetto_insufficiente'] = stats.get('skip_tetto_insufficiente', 0) + 1
        return False

    log(f"[{source}] {player_name}: riferimento {reference_price:.2f}EUR ({reference_source}), "
        f"tetto bid {bid_ceiling:.2f}EUR (max per asta {MAX_BID_PER_AUCTION_EUR:.2f}EUR), "
        f"minNextBid attuale {min_next_bid_eur:.2f}EUR, "
        f"link={build_card_link(player_slug, card_slug, card_serial_number)}")

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
        alert_text = send_bid_alert(player_name, player_slug, card_slug, reference_price, reference_source,
                                     bid_ceiling, min_next_bid_eur, live_mode=False, seconds_left=seconds_left,
                                     card_serial_number=card_serial_number)
        state.pending_alerts.append(alert_text)
        stats['bid_simulated'] = stats.get('bid_simulated', 0) + 1
        return True

    # FIX 22/07 (richiesta esplicita utente, primi test con soldi veri: "max 1 asta su
    # cui biddare per run"): controllo veloce PRIMA della riverifica live, solo per
    # risparmiare i 3s di attesa + una chiamata GraphQL se il tetto e' gia' pieno --
    # l'incremento vero (che "consuma" il tetto) avviene piu' sotto, subito prima del
    # vero tentativo di bid, cosi' una riverifica fallita (asta chiusa, prezzo salito)
    # NON spreca l'unico tentativo consentito.
    if BIDS_ATTEMPTED_THIS_RUN[0] >= MAX_BIDS_PER_RUN:
        log(f"[{source}] {player_name}: scarto -- tetto MAX_BIDS_PER_RUN "
            f"({MAX_BIDS_PER_RUN}) gia' raggiunto in questa run, nessun altro bid "
            f"reale verra' tentato (continua comunque a valutare/notificare in "
            f"diagnostica)")
        stats['skip_max_bids_run'] = stats.get('skip_max_bids_run', 0) + 1
        return False

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

    # Ultimo controllo (piu' un'ulteriore riserva atomica) subito prima del vero
    # tentativo -- questo e' il punto che "consuma" il tetto MAX_BIDS_PER_RUN.
    with _bids_attempted_lock:
        if BIDS_ATTEMPTED_THIS_RUN[0] >= MAX_BIDS_PER_RUN:
            log(f"[{source}] {player_name}: scarto -- tetto MAX_BIDS_PER_RUN raggiunto "
                f"nel frattempo, non tento il bid")
            stats['skip_max_bids_run'] = stats.get('skip_max_bids_run', 0) + 1
            return False
        BIDS_ATTEMPTED_THIS_RUN[0] += 1
        log(f"[{source}] {player_name}: tentativo di bid reale {BIDS_ATTEMPTED_THIS_RUN[0]}/"
            f"{MAX_BIDS_PER_RUN} per questa run")

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

    # FIX 22/07 v6 (richiesta esplicita utente, caso reale: notifica di un bid VERO
    # arrivata tardi/mai perche' accodata dietro migliaia di altre valutazioni della
    # stessa fase): i risultati di bid REALE non vengono piu' accorpati in nessun modo
    # -- partono SUBITO come messaggio Telegram a se stante. Zero rischio di "flood"
    # qui: sono al massimo MAX_BIDS_PER_RUN per l'intera run (default 1).
    alert_text = send_bid_alert(player_name, player_slug, card_slug, reference_price, reference_source,
                                 bid_ceiling, min_next_bid_eur, live_mode=True,
                                 bid_completed=bid_completed, bid_error=bid_error, seconds_left=seconds_left,
                                 card_serial_number=card_serial_number)
    send_telegram_msg(alert_text)
    return bool(bid_completed)


def run_listener(eth_rate):
    state = _SharedListenerState()
    stats = state.stats  # stesso dict, solo un alias piu' corto per il resto della funzione

    # Il timer ferma il ciclo dopo LISTEN_SECONDS, esattamente come faceva prima con la
    # chiusura del WebSocket.
    stop_event = threading.Event()
    timer = threading.Timer(LISTEN_SECONDS, stop_event.set)
    timer.daemon = True
    timer.start()

    try:
        run_tracking_cycle(eth_rate, state, stop_event)
    finally:
        timer.cancel()

    log(f"Ciclo terminato. Eventi processati: {stats.get('processed', 0)}")
    total_bid = stats.get('bid_placed', 0) + stats.get('bid_simulated', 0)
    skip_keys = sorted(k for k in stats if k.startswith('skip_'))
    breakdown = ', '.join(f"{k[5:]}={stats[k]}" for k in skip_keys) or "nessuno"
    source_keys = sorted(k for k in stats if k.startswith('source_'))
    source_breakdown = ', '.join(f"{k[7:]}={stats[k]}" for k in source_keys) or "nessuno"
    log(f"[riepilogo] bid {'reali' if AUCTION_LIVE_MODE else 'simulati'}: {total_bid}, "
        f"bid falliti: {stats.get('bid_failed', 0)}, scarti: {breakdown}")
    log(f"[riepilogo] aste valutate per fase: {source_breakdown}")
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
    log(f"Tetto massimo BID REALI per questa run: {MAX_BIDS_PER_RUN} "
        f"(oltre questo, solo diagnostica -- nessun altro bid reale)")
    log(f"Ciclo di tracking (WebSocket rimosso, solo scansioni GraphQL): "
        f"FASE NUOVE ({CYCLE_PHASE_SECONDS:.0f}s, valuta TUTTE) -> "
        f"pausa {CYCLE_PAUSE_SECONDS:.0f}s -> "
        f"FASE ZEROBID ({CYCLE_PHASE_SECONDS:.0f}s, valuta TUTTE) -> "
        f"pausa {CYCLE_PAUSE_SECONDS:.0f}s -> "
        f"FASE SCADENZA ({CYCLE_PHASE_SECONDS:.0f}s, top {SCADENZA_TOP_N}) -> "
        f"pausa {CYCLE_PAUSE_SECONDS:.0f}s -> ricomincia. Notifiche Telegram accorpate "
        f"in UN messaggio per fase (mai una a testa).")
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
