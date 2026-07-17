import os
import re
import json
import time
import threading
import sqlite3
import statistics
import datetime
import requests
import websocket  # pip install websocket-client

# Listener in tempo reale per le aste (sostituisce/affianca il polling di auctions.py).
# Costruito dopo aver confermato via diagnostica che:
#  1) la subscription WebSocket tokenAuctionWasUpdated esiste davvero e funziona
#     (diagnostic_auction_ws.py)
#  2) puo' essere arricchita con anyCards e restituisce DIRETTAMENTE slug/giocatore/
#     rarita'/sport/stagione della carta in asta, senza bisogno di nessuna query REST
#     separata per evento (diagnostico_4_dati_carta_asta.py)
#  3) Sorare manda a volte lo stesso evento due o tre volte identico sullo stesso
#     WebSocket -- gestito qui con una deduplica per (id, currentPrice, minNextBid, endDate)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('AUCTION_TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('AUCTION_TELEGRAM_CHAT_ID', '').strip()

# ATTENZIONE: leghe diverse usano formati diversi per "stagione corrente" -- le leghe europee
# usano "2025-26" (a cavallo di due anni), la MLS (e leghe a calendario solare) usano solo
# l'anno, es. "2026". Confrontare solo con CURRENT_SEASON lasciava fuori la MLS: la sua carta
# In Season vera veniva scambiata per "classic" e mescolata col resto (caso Roman Bürki: 2.95EUR
# rilevato contro 12.35EUR reali -- il 12.35 era proprio la sua carta In Season "2026" scambiata
# per classic). Le stampe Classic di anni diversi invece hanno prezzi tra loro simili (verificato
# con dati reali: tutte tra 2.70 e 5.50EUR per Bürki) -- sono equivalenti per i manager, quindi
# qui basta il bucket in_season/classic, purche' il riconoscimento di "in season" copra entrambi
# i formati.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')
CURRENT_SEASON_ALT = os.environ.get('CURRENT_SEASON_ALT', '2026')  # formato MLS/calendario solare
# FIX 16/07 (caso Sebastian Berhalter, giocatore MLS): dagli screenshot reali mandati
# dall'utente, le carte Limited attualmente scambiate/in asta per Berhalter (MLS) sono
# etichettate sportSeason.name="2026-27", non "2026" come atteso dal vecchio fix Burki.
# Sorare sembra aver unificato l'etichetta di stagione corrente su "2026-27" anche per le
# leghe a calendario solare (probabile cambio stagione, siamo a meta' luglio). Aggiunta come
# terza label riconosciuta accanto alle due precedenti, senza rimuovere quelle vecchie (nel
# dubbio meglio riconoscerne di piu' che di meno per il bucket in_season).
CURRENT_SEASON_EU_NEW = os.environ.get('CURRENT_SEASON_EU_NEW', '2026-27')
CURRENT_SEASON_LABELS = {CURRENT_SEASON, CURRENT_SEASON_ALT, CURRENT_SEASON_EU_NEW}
BID_DISCOUNT = float(os.environ.get('BID_DISCOUNT', '0.20'))  # 20% fisso sul riferimento (mediana) -- abbassato da 25% il 16/07 per far passare piu' aste ai primi filtri
RECENT_PRICES_COUNT = int(os.environ.get('RECENT_PRICES_COUNT', '3'))
# FIX 16/07 (caso Walker Zimmerman): niente piu' notifiche con margine stimato ~0 --
# richiesto un margine minimo di 1EUR rispetto alla vendita diretta minima per notificare.
# Se il margine non e' calcolabile (nessun direct_sale_price trovato, live ne' in cache),
# per sicurezza NON si notifica: senza un riferimento di vendita diretta non possiamo
# confermare che valga davvero la pena rilanciare invece di comprare subito.
MIN_MARGIN_EUR = float(os.environ.get('MIN_MARGIN_EUR', '1.5'))  # usato solo come fallback
# quando direct_sale_price non e' disponibile per calcolare uno scaglione -- vedi
# required_margin_eur() piu' sotto per il caso normale.

# FIX 17/07 (richiesta esplicita dell'utente, "troppo stringente coi parametri... forse per
# questo poche notifiche"): MIN_MARGIN_EUR fisso a 1.5EUR era uguale per una carta da 2EUR e
# una da 50EUR -- su una carta da 2EUR equivale a pretendere uno sconto reale del 75% per
# notificare, quasi impossibile, mentre su una da 50EUR e' solo il 3%. Stesso approccio a
# scaglioni GIA' calibrato su tanti casi reali in track.py (MARGIN_TIERS/
# required_margin_fraction, tracker classico), qui riadattato alle aste: la percentuale
# minima di margine richiesta scende progressivamente al salire del prezzo di riferimento
# (vendita diretta), invece di un euro fisso identico per tutte le fasce.
# FIX 17/07 (v3, richiesta esplicita dell'utente, "alza scaglione anche li minimo setta 1
# euro" -- dopo il caso YAGO): lo scaglione 3-5EUR (12%) lasciava passare margini troppo
# risicati nello stesso run (Yazan Al Arab 0.48EUR richiesti 0.46, Kim Ryun-Seong 0.45
# richiesti 0.44, Choi Jun 0.92 -- tutti appena sopra la vecchia soglia percentuale). Per
# questa fascia il margine minimo richiesto diventa un euro FISSO invece che percentuale --
# stesso concetto del floor assoluto gia' usato oltre i 60EUR, solo qui esplicito e piu' alto
# in proporzione perche' su carte cosi' economiche il rischio di rumore statistico e' piu'
# alto. Ogni scaglione ora e' una funzione (prezzo di riferimento -> margine richiesto)
# invece di una singola percentuale, per poter mescolare scaglioni percentuali e fissi nella
# stessa tabella senza rami speciali nel codice.
# FIX 17/07 (v4, caso reale MUGOSA, richiesta esplicita dell'utente "margine di 0.48 e'
# troppo basso per notificare"): vendita diretta 2.89EUR, margine stimato 0.48EUR passava
# la vecchia soglia (0.15 -> 0.43EUR richiesti) per un pelo. Primo tentativo con percentuale
# al 20% (0.58EUR richiesti) giudicato ancora insufficiente dall'utente ("aumenta a 0.80 per
# casi mugosa") -- stesso concetto dello scaglione 3-5EUR: margine minimo FISSO invece che
# percentuale, per non lasciare troppo margine di rumore statistico sulle carte piu' economiche.
AUCTION_MARGIN_TIERS = [
    (3, lambda p: 0.80),
    (5, lambda p: 1.0),
    # FIX 17/07 (v2, caso reale YAGO, richiesta esplicita dell'utente): vendita diretta 7.24EUR,
    # margine stimato 0.80EUR passava la soglia (0.10 -> 0.72EUR richiesti) ma l'utente lo
    # giudica troppo risicato per notificare -- serviva almeno 1.20EUR. 0.10 -> 0.17 (7.24*0.17
    # = 1.23EUR, sopra la soglia voluta dall'utente per questo caso preciso).
    (10, lambda p: p * 0.17),
    (20, lambda p: p * 0.08),
    (40, lambda p: p * 0.06),
    (60, lambda p: p * 0.05),
]


# FIX 17/07 (v4, richiesta esplicita dell'utente, "sistema salto ai bordi"): calibrare ogni
# scaglione singolarmente su un caso reale (Choi Jun/Yazan/Kim Ryun-Seong -> floor 1.0EUR
# fisso, YAGO -> 17% invece di 10%) aveva un effetto collaterale non voluto: appena sopra un
# confine tra scaglioni il margine richiesto poteva SCENDERE invece di salire (es. 4.99EUR ->
# 1.00EUR richiesti, ma 5.00EUR -> solo 0.85EUR; 9.99EUR -> 1.70EUR, ma 10.00EUR -> solo
# 0.80EUR) -- una carta leggermente PIU' cara diventava piu' facile da notificare di una
# leggermente piu' economica, il contrario del buon senso. Calcoliamo per ogni scaglione un
# "floor d'ingresso" pari al massimo valore mai richiesto dagli scaglioni precedenti al loro
# stesso bordo superiore, e lo applichiamo come minimo garantito -- il margine richiesto ora
# non scende mai attraversando un confine, resta piatto finche' la percentuale del nuovo
# scaglione non lo supera naturalmente, poi riprende a crescere.
def _compute_tier_entry_floors():
    floors = []
    running_floor = 0.0
    for upper_bound, compute in AUCTION_MARGIN_TIERS:
        floors.append(running_floor)
        value_at_top = compute(upper_bound)
        running_floor = max(running_floor, value_at_top)
    return floors, running_floor


_AUCTION_MARGIN_ENTRY_FLOORS, _AUCTION_MARGIN_FINAL_FLOOR = _compute_tier_entry_floors()


def required_margin_eur(reference_price):
    """Margine minimo in EUR richiesto per notificare, a scaglioni in base al prezzo di
    riferimento (direct_sale_price) -- stesso spirito di required_margin_fraction in
    track.py. Sotto ogni soglia si applica la funzione di quello scaglione (percentuale o
    euro fisso, vedi AUCTION_MARGIN_TIERS), mai sotto il floor d'ingresso di quello scaglione
    (garantisce che il margine richiesto sia sempre non-decrescente al salire del prezzo,
    niente piu' salti in giu' ai bordi). Oltre l'ultima soglia (60EUR) o se il riferimento non
    e' disponibile, si torna al vecchio margine assoluto fisso MIN_MARGIN_EUR (mai comunque
    sotto il floor finale accumulato)."""
    if reference_price is None or reference_price <= 0:
        return MIN_MARGIN_EUR
    for i, (upper_bound, compute) in enumerate(AUCTION_MARGIN_TIERS):
        if reference_price < upper_bound:
            return max(compute(reference_price), _AUCTION_MARGIN_ENTRY_FLOORS[i])
    return max(MIN_MARGIN_EUR, _AUCTION_MARGIN_FINAL_FLOOR)


# FIX 17/07 (richiesta esplicita dell'utente, caso concreto "asta 1EUR senza offerte, ultime 3
# vendite 2.00/1.50/2.50EUR, ma nessuna vendita diretta live" -- stesso principio gia' collaudato
# oggi per il fallback storico di ZenLock quando manca il comparabile live): senza questo, il
# margine non era MAI calcolabile quando get_live_min_direct_sale/get_current_min_direct_sale non
# trovavano nulla (direct_sale_price=None -> margin_estimate=None -> scarto automatico), anche
# quando la storia recente mostrava chiaramente un affare. Non e' un prezzo GARANTITO disponibile
# adesso (a differenza di direct_sale_price vero, e' solo l'ultima vendita osservata), quindi
# richiediamo un margine estra oltre al normale scaglione -- moltiplicatore invece di un valore
# fisso, cosi' scala correttamente con il prezzo di riferimento come gli altri scaglioni.
AUCTION_HISTORICAL_FALLBACK_MARGIN_MULTIPLIER = float(
    os.environ.get('AUCTION_HISTORICAL_FALLBACK_MARGIN_MULTIPLIER', '1.5'))

# FIX 17/07 (stessa richiesta, secondo punto): last_price era un tetto RIGIDO su
# recommended_ceiling (vedi piu' sotto) -- un singolo dato (l'ultima vendita) puo' essere
# rumoroso quanto un intero mercato, e capitare basso per puro caso blocca la raccomandazione
# a prescindere da quanto la mediana (gia' scontata del 20%) suggerirebbe di poter offrire.
# Tolleranza che ammorbidisce il tetto senza eliminarlo (resta comunque ancorato all'ultima
# vendita vera, protezione originale del caso Tverskov, solo meno rigida).
AUCTION_LAST_PRICE_TOLERANCE = float(os.environ.get('AUCTION_LAST_PRICE_TOLERANCE', '0.15'))

# Ritardo prima della riverifica live pre-notifica: nei log di produzione del 16/07 la
# riverifica risultava "asta non piu' aperta" per QUASI OGNI asta valutata (7/7 in un run,
# 4/4 nell'altro) -- troppo improbabile che fossero tutte gia' davvero concluse a ~1 secondo
# dall'evento WebSocket che le segnalava come appena aggiornate. Sospetto piu' probabile:
# race condition di lettura-dopo-scrittura sul backend di Sorare (l'asta appena creata/
# aggiornata non e' ancora "consistente" su tutti i sistemi quando la rileggiamo cosi'
# in fretta). Un breve ritardo prima della query da' tempo al backend di allinearsi.
AUCTION_RECHECK_DELAY_SECONDS = float(os.environ.get('AUCTION_RECHECK_DELAY_SECONDS', '3'))

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# FIX 16/07 (caso Albert Rusnak 528/1000): il WS push manda ogni evento UNA volta sola a
# chi e' connesso in quel preciso istante -- Sorare non fa replay per chi si riconnette
# dopo. Ogni esecuzione ascolta solo LISTEN_SECONDS su un ciclo di ~2 minuti (vedi sopra):
# un rilancio che arriva nel buco tra due esecuzioni e' perso per sempre, anche se
# l'asta resta valida secondo i nostri criteri (caso reale: offerta a 12EUR su un'asta con
# tetto ben piu' alto, mai vista dal bot). Per questo, prima di aprire il WS, si fa UNA
# scansione di sicurezza delle aste live piu' recenti sul mercato (query gia' validata dal
# vecchio auctions.py) e si valuta ciascuna con la stessa identica process_auction --
# stesso file auctions.db, stessa tabella notified_auctions, stesso commit di fine run:
# nessun rischio di duplicati o conflitti con un bot separato, e' lo stesso processo.
NUM_SAFETY_POLL_AUCTIONS = int(os.environ.get('NUM_SAFETY_POLL_AUCTIONS', '50'))

# Per quanti secondi restare in ascolto ad ogni esecuzione. Il cron su cronhub per le aste
# e' attualmente ogni 2 minuti (120s): teniamo un margine per l'avvio di GitHub Actions e
# l'handshake WebSocket, cosi' due esecuzioni consecutive si "toccano" quasi senza buchi,
# stesso ragionamento gia' fatto per LISTEN_SECONDS in track.py.
LISTEN_SECONDS = int(os.environ.get('AUCTION_LISTEN_SECONDS', '110'))

SUBSCRIPTION_QUERY = """
subscription OnTokenAuctionUpdated {
  tokenAuctionWasUpdated {
    id
    currentPrice
    minNextBid
    endDate
    anyCards {
      slug
      rarityTyped
      sport
      anyPlayer { slug displayName }
      sportSeason { name }
    }
  }
}
"""


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


# FIX 17/07 (richiesta esplicita dell'utente, "mai capitato prima, ora con le aste 429"): stesso
# fix gemello applicato oggi a track.py -- con tre tracker attivi in concorrenza (classico,
# ZenLock, aste) il carico cumulativo verso Sorare a volte supera il rate limit (HTTP 429), mai
# controllato esplicitamente finora. Rileva il 429 e ritenta con backoff invece di trattarlo
# come un generico errore/dato vuoto (probabile causa reale dell'apparente crollo dei "prezzi
# recenti trovati" osservato in un run precedente, non necessariamente il filtro stagione).
#
# FIX 17/07 (v2, stesso giorno, caso gemello Egil Selvik su zenlock_model_tracker.py): un
# Retry-After lungo (osservato 15s) fatto rispettare alla lettera dentro il thread del listener
# WebSocket ha fatto scadere il ping/pong (ping_timeout 10s) e chiuso la connessione. Tetto
# massimo all'attesa: meglio rinunciare prima e lasciar fallire la singola query.
#
# FIX 17/07 (v3, gemello del fix in track.py -- il ping/pong e' scaduto di nuovo con lo stesso
# identico sintomo nonostante il cap a 8s): il cap limita solo il singolo tentativo, ma con fino
# a 3 retry consecutivi nella stessa chiamata sincrona il blocco cumulativo puo' arrivare a 24s+,
# ben oltre il ping_timeout di 10s. Il fix vero e' dare piu' margine al ping stesso (vedi
# run_forever piu' sotto), non stringere ulteriormente un backoff che comunque non risolverebbe
# un rate limit reale piu' lungo.
GRAPHQL_RETRY_MAX_WAIT_SECONDS = 8.0

# FIX 17/07 (v4, gemello del fix in track.py -- log ZenLock mostra ping/pong scaduto ANCORA per
# blocco cumulativo su piu' carte consecutive, e Retry-After che decresce linearmente col tempo
# reale trascorso, tipico di un ban a tempo fisso e non di un rate limit che si rinnova). Contro
# un ban del genere i retry brevi sono inutili e bloccano solo il thread della WS piu' a lungo.
GRAPHQL_RETRY_AFTER_BAN_THRESHOLD_SECONDS = 15.0


def graphql_query(query, variables=None, max_retries=3):
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            retry_after = r.headers.get('Retry-After')
            raw_retry_after_seconds = None
            try:
                raw_retry_after_seconds = float(retry_after) if retry_after else None
            except ValueError:
                raw_retry_after_seconds = None
            if attempt == 0:
                body_snippet = (r.text or '')[:200].replace('\n', ' ')
                log(f"[rate limit] dettaglio risposta 429 -- headers rilevanti: "
                    f"Retry-After={retry_after!r}, corpo: {body_snippet!r}")
            if (raw_retry_after_seconds is not None
                    and raw_retry_after_seconds > GRAPHQL_RETRY_AFTER_BAN_THRESHOLD_SECONDS):
                log(f"[rate limit] Retry-After={raw_retry_after_seconds:.0f}s troppo lungo "
                    f"(soglia {GRAPHQL_RETRY_AFTER_BAN_THRESHOLD_SECONDS:.0f}s), probabile ban a "
                    f"tempo fisso -- rinuncio subito senza ritentare")
                return {"errors": [{"message": "rate_limited_ban_detected"}]}
            wait_seconds = raw_retry_after_seconds if raw_retry_after_seconds is not None else (2 ** attempt) * 2
            wait_seconds = min(wait_seconds, GRAPHQL_RETRY_MAX_WAIT_SECONDS)
            log(f"[rate limit] HTTP 429 da Sorare (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s prima di ritentare...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    log(f"[rate limit] HTTP 429 persistente dopo {max_retries} tentativi, rinuncio a questa query")
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def wei_to_eur(wei_value, eth_rate):
    if wei_value is None:
        return None
    try:
        return float(wei_value) / 1e18 * eth_rate
    except (TypeError, ValueError):
        return None


# FIX 17/07 (richiesta esplicita dell'utente, dopo la scoperta dello stesso bug in track.py):
# gli annunci di vendita diretta usati qui come riferimento (get_live_min_direct_sale,
# get_recent_public_prices) possono essere denominati in USD/GBP oltre che EUR/ETH, esattamente
# come nel tracker principale -- MonetaryAmount espone eurCents/wei/usdCents/gbpCents e prima
# leggevamo solo i primi due, perdendo silenziosamente ~1/5 degli annunci reali (stessa scala
# osservata su track.py). Stesso fix, stessa fonte cambio (frankfurter.app, nessuna API key).
_FIAT_RATE_CACHE = {}


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


# FIX 17/07 (stesso fix gemello di track.py -- caso "none" RISOLTO su petar-musa: una QUINTA
# valuta mai richiesta, Solana, campo amounts.lamport, 1 SOL = 1e9 lamport). Stesso pattern di
# get_usd_eur_rate/get_gbp_eur_rate ma coingecko invece di frankfurter (crypto, non fiat).
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


# Stesso contatore diagnostico gia' aggiunto oggi a track.py -- quanto pesano davvero le
# valute USD/GBP/Solana nei riferimenti di vendita diretta che le aste usano per calcolare il
# tetto consigliato/margine stimato.
_CURRENCY_BRANCH_STATS = {'eurCents': 0, 'wei': 0, 'usdCents': 0, 'gbpCents': 0, 'lamport': 0, 'none': 0}


def get_currency_branch_stats():
    return dict(_CURRENCY_BRANCH_STATS)


def reset_currency_branch_stats():
    for k in _CURRENCY_BRANCH_STATS:
        _CURRENCY_BRANCH_STATS[k] = 0


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


# --- Database (stesso auctions.db/notified_auctions gia' usato dal polling: condivisibile
#     anche se in futuro girassero entrambi in parallelo durante una transizione) ---
def init_db():
    conn = sqlite3.connect('auctions.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notified_auctions (
            auction_id TEXT PRIMARY KEY,
            notified_at TEXT
        )
    ''')
    # Log strutturato di OGNI decisione (notifica o scarto) su un'asta valutata, gemello di
    # quello aggiunto in track.py: serve a costruire nel tempo un tasso misurabile di falsi
    # positivi/negativi invece di doversi fidare solo dei messaggi Telegram gia' mandati.
    conn.execute('''
        CREATE TABLE IF NOT EXISTS decisions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            auction_id TEXT,
            player_slug TEXT,
            player_name TEXT,
            season_type TEXT,
            current_price REAL,
            min_next_bid REAL,
            median_reference REAL,
            recommended_ceiling REAL,
            direct_sale_price REAL,
            margin_estimate REAL,
            decision TEXT,
            reasons TEXT
        )
    ''')
    # FIX 17/07 (richiesta esplicita dell'utente, "log molto pesante... scartare le aste gia'
    # analizzate"): la scansione di sicurezza rivaluta da zero le stesse ~50 aste live ad OGNI
    # esecuzione (ogni ~4 minuti via cron esterno), anche quelle il cui prezzo/offerta minima
    # non sono cambiati di una virgola dall'esecuzione precedente -- rifare mediana/tetto/
    # riverifica live (con tanto di sleep) su un'asta identica produce lo stesso identico
    # risultato di 4 minuti fa, quindi e' lavoro (e log) genuinamente inutile. Salviamo
    # l'ultimo prezzo/offerta minima visti per ogni asta: se al prossimo giro sono identici,
    # saltiamo subito senza rifare l'analisi. Se invece qualcosa e' cambiato (nuova offerta,
    # asta salita) la rivalutiamo normalmente -- e' informazione nuova, non piu' inutile.
    conn.execute('''
        CREATE TABLE IF NOT EXISTS evaluated_auctions (
            auction_id TEXT PRIMARY KEY,
            current_price REAL,
            min_next_bid REAL,
            evaluated_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


def log_decision(auction_id, player_slug, player_name, season_type, decision,
                  current_price=None, min_next_bid=None, median_reference=None,
                  recommended_ceiling=None, direct_sale_price=None, margin_estimate=None,
                  reasons=None):
    """Registra una riga per ogni decisione presa su un'asta (notificata o scartata, e perche').
    Stessa idea del log_decision di track.py, tabella gemella in auctions.db."""
    conn = sqlite3.connect('auctions.db')
    conn.execute(
        '''INSERT INTO decisions_log
           (ts, auction_id, player_slug, player_name, season_type, current_price, min_next_bid,
            median_reference, recommended_ceiling, direct_sale_price, margin_estimate, decision, reasons)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (datetime.datetime.now().isoformat(), auction_id, player_slug, player_name, season_type,
         current_price, min_next_bid, median_reference, recommended_ceiling, direct_sale_price,
         margin_estimate, decision, ', '.join(reasons) if reasons else None)
    )
    conn.commit()
    conn.close()


def already_notified(auction_id):
    conn = sqlite3.connect('auctions.db')
    row = conn.execute("SELECT 1 FROM notified_auctions WHERE auction_id=?", (auction_id,)).fetchone()
    conn.close()
    return row is not None


def mark_notified(auction_id):
    conn = sqlite3.connect('auctions.db')
    conn.execute(
        "INSERT OR REPLACE INTO notified_auctions (auction_id, notified_at) VALUES (?, ?)",
        (auction_id, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_last_eval_snapshot(auction_id):
    """Ultimo (current_price, min_next_bid) con cui questa asta e' stata valutata per intero,
    o None se non l'abbiamo mai vista. Vedi nota su evaluated_auctions in init_db."""
    conn = sqlite3.connect('auctions.db')
    row = conn.execute(
        "SELECT current_price, min_next_bid FROM evaluated_auctions WHERE auction_id=?",
        (auction_id,)
    ).fetchone()
    conn.close()
    return row


def save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur):
    conn = sqlite3.connect('auctions.db')
    conn.execute(
        "INSERT OR REPLACE INTO evaluated_auctions (auction_id, current_price, min_next_bid, evaluated_at) "
        "VALUES (?, ?, ?, ?)",
        (auction_id, current_price_eur, min_next_bid_eur, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def _floats_equal(a, b, tol=0.005):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < tol


def get_current_min_direct_sale(player_slug, season_type='in_season'):
    """Fallback SOLO se la verifica live (get_live_min_direct_sale) fallisce: legge la
    cache locale di track.py. NOTA: prima di questo fix cercava sempre e solo
    season_name='in_season', quindi per qualunque carta classificata 'classic' (es. leghe
    come la MLS che etichettano la stagione come '2026' invece di '2025-26') tornava
    sempre None, anche se track.py aveva gia' un riferimento salvato -- bug confermato
    sui casi Jordan Knight e Cooper Flax (entrambi MLS)."""
    try:
        conn = sqlite3.connect('tracker.db')
        row = conn.execute(
            "SELECT floor_price_eur FROM floors WHERE player_slug=? AND season_name=?",
            (player_slug, season_type)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log(f"Impossibile leggere tracker.db ({e}), procedo senza riferimento di vendita diretta")
        return None


# --- Verifica LIVE del prezzo minimo di vendita diretta (stessa query e stessa logica
#     gia' validata in track.py), da preferire sempre alla sola cache locale: quest'ultima
#     puo' essere vuota (cold start) o nella categoria stagione sbagliata. Casi reali che
#     hanno mostrato il problema: Jordan Knight e Cooper Flax, entrambi MLS, entrambi con
#     annunci diretti piu' economici dell'asta segnalata ma invisibili alla cache. ---
# NOTA IMPORTANTE (scoperta in diagnostica): il server tronca SEMPRE le risposte a un
# massimo di ~50 nodi per richiesta, indipendentemente dal valore chiesto in "last" (anche
# chiedendo last:300 tornavano solo 50 nodi) -- ecco perche' alzare il numero non risolveva
# davvero i casi Jonas Urbig/Justin Bijlow. Confermato pero' che la paginazione a cursore
# FUNZIONA (pageInfo.hasPreviousPage + argomento "before"): scorrendo le pagine precedenti
# si recuperano TUTTI gli annunci. Vedi fetch_all_live_offers().
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } }
        senderSide {
          anyCards {
            rarityTyped
            sport
            sportSeason { name }
          }
        }
      }
    }
  }
}
"""

PAGE_SIZE = 50  # il vero massimo per richiesta imposto dal server, confermato in diagnostica
MAX_PAGES = 20  # tetto di sicurezza (fino a 1000 annunci totali)


# FIX 17/07 (richiesta esplicita dell'utente, "i due tracker girano insieme" + log reale con
# ban 429 a meta' scansione di sicurezza): stesso identico fix gia' applicato oggi a track.py
# (get_bucket_prices/get_recent_sale_history) per zenlock/tracker classico -- durante la
# scansione di sicurezza (fino a 50 aste per run) piu' aste dello stesso giocatore (piu' carte
# in vendita) o eventi WS ravvicinati facevano ripartire da zero fetch_all_live_offers/
# get_recent_public_prices per lo stesso player_slug piu' volte nella stessa esecuzione --
# volume di query evitabile che si somma a quello degli altri tracker attivi in concorrenza.
# Cache in-memory con TTL breve (il mercato non cambia cosi' in fretta da rendere un dato di
# pochi secondi fa inutile): niente impatto su correttezza, solo meno richieste ripetute.
_LIVE_OFFERS_CACHE = {}
_RECENT_PUBLIC_PRICES_CACHE = {}
_CACHE_TTL_SECONDS = 30.0
_CACHE_MISS = object()


def _cache_get(cache_dict, key):
    entry = cache_dict.get(key, _CACHE_MISS)
    if entry is _CACHE_MISS:
        return _CACHE_MISS
    ts, value = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        return _CACHE_MISS
    return value


def _cache_set(cache_dict, key, value):
    cache_dict[key] = (time.time(), value)


def fetch_all_live_offers(player_slug):
    """Scorre TUTTE le pagine di annunci live per un giocatore usando la paginazione a
    cursore confermata funzionante (before/startCursor), invece di fidarsi di un singolo
    "last: N" che il server tronca comunque a ~50 per richiesta."""
    cached = _cache_get(_LIVE_OFFERS_CACHE, player_slug)
    if cached is not _CACHE_MISS:
        return cached
    all_nodes = []
    cursor = None
    had_error = False
    for _ in range(MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[paginazione annunci live] errore per {player_slug}: {data['errors']}")
            had_error = True
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
    # Cache-ato SOLO se completata senza errori -- un fallimento a meta' paginazione (es. rate
    # limit) non va ricordato come "questi sono TUTTI gli annunci" per 30s, altrimenti un
    # elenco parziale/vuoto per colpa di un 429 sembrerebbe "nessun annuncio live" invece che
    # "non siamo riusciti a chiederlo".
    if not had_error:
        _cache_set(_LIVE_OFFERS_CACHE, player_slug, all_nodes)
    return all_nodes


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        _CURRENCY_BRANCH_STATS['none'] += 1
        return None
    if amounts.get('eurCents') is not None:
        _CURRENCY_BRANCH_STATS['eurCents'] += 1
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        price = wei_to_eur(amounts['wei'], eth_rate)
        if price is None:
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['wei'] += 1
        return price
    if amounts.get('usdCents') is not None:
        try:
            price = amounts['usdCents'] / 100 * get_usd_eur_rate()
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['usdCents'] += 1
        return price
    if amounts.get('gbpCents') is not None:
        try:
            price = amounts['gbpCents'] / 100 * get_gbp_eur_rate()
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['gbpCents'] += 1
        return price
    if amounts.get('lamport') is not None:
        try:
            price = float(amounts['lamport']) / 1e9 * get_sol_eur_rate()
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['lamport'] += 1
        return price
    _CURRENCY_BRANCH_STATS['none'] += 1
    return None


def get_live_min_direct_sale(player_slug, target_season_type, eth_rate):
    """Prezzo minimo REALE attualmente in vendita diretta nella stessa categoria in_season/
    classic della carta in asta. NOTA: confermato con dati reali (mercato di Roman Bürki) che
    le stampe Classic di anni diversi hanno prezzi tra loro simili (tutte 2.70-5.50EUR
    indipendentemente dall'anno) -- sono equivalenti per i manager, quindi il bucket generico
    va bene. Il vero bug (2.95EUR rilevato contro 12.35EUR reali) non era il bucket generico in
    se', ma il fatto che la carta In Season vera di Bürki (stagione MLS "2026") veniva
    classificata come "classic" perche' il confronto guardava solo il formato europeo "2025-26"
    -- risolto riconoscendo entrambi i formati in CURRENT_SEASON_LABELS."""
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
                node_season = (c.get('sportSeason') or {}).get('name', 'unknown')
                node_season_type = 'in_season' if node_season in CURRENT_SEASON_LABELS else 'classic'
                if node_season_type != target_season_type:
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
        log(f"[verifica live vendita diretta] eccezione per {player_slug}: {e}")
        return None


def parse_season_year(season_name):
    if not season_name:
        return None
    match = re.search(r'\d{4}', season_name)
    return int(match.group()) if match else None


# --- Countdown scadenza asta: aggiunto dopo il caso Luca Bombino, dove l'alert linkava
#     un'asta (da un'infornata di nuove carte con vita brevissima) gia' terminata al
#     momento del click -- Sorare in quel caso non mostra un messaggio "asta scaduta", torna
#     silenziosamente alla scheda generica della carta, che sembra un link rotto. Mostrare
#     subito quanto tempo resta nel messaggio Telegram fa capire all'utente se ha ancora
#     tempo per agire o se conviene lasciar perdere. ---
def seconds_until_end(end_date_str):
    if not end_date_str:
        return None
    try:
        end_dt = datetime.datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        return (end_dt - now_dt).total_seconds()
    except (ValueError, TypeError):
        return None


def format_time_remaining(seconds):
    if seconds is None:
        return "n/d"
    if seconds <= 0:
        return "gia' scaduta"
    total_minutes = int(seconds // 60)
    secs = int(seconds % 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    # Oltre un'ora, mostrare solo minuti diventa illeggibile (es. "1011 min 13s" invece di
    # "16h 51min") -- sopra i 60 minuti passiamo a ore+minuti, sotto restiamo su minuti+secondi.
    if hours >= 1:
        return f"{hours}h {minutes}min"
    if minutes >= 1:
        return f"{minutes} min {secs}s"
    return f"{secs}s"


# Sotto questa soglia di secondi residui, il countdown viene evidenziato come urgente:
# tempo tipico che serve a leggere la notifica, aprire il link e caricare la pagina.
URGENT_TIME_THRESHOLD_SECONDS = 120


# FIX 17/07 (TEST, richiesta esplicita dell'utente dopo l'indagine "troppe poche notifiche"):
# su un run reale, 24/30 (80%) delle aste football/limited valutate venivano scartate per
# "nessun prezzo precedente trovato" -- troppo per essere scarsita' di dati normale. Sospetto:
# il filtro "season" qui sotto (derivato con un regex dal nome stagione della carta, MAI
# validato contro lo schema reale -- introspection disabilitata da Sorare) non corrisponde al
# valore che il server si aspetta davvero, azzerando il risultato per la maggior parte dei
# giocatori. La query equivalente gia' provata in track.py (get_recent_sale_history,
# tokens.tokenPrices) NON filtra mai per stagione ed e' quella che ha funzionato per tutta la
# sessione. Contatore per misurare quanto aiuta davvero il fallback.
_SEASON_FILTER_STATS = {'with_season_ok': 0, 'fallback_no_season_ok': 0, 'both_empty': 0}


def get_season_filter_stats():
    return dict(_SEASON_FILTER_STATS)


def reset_season_filter_stats():
    for k in _SEASON_FILTER_STATS:
        _SEASON_FILTER_STATS[k] = 0


def get_recent_public_prices(player_slug, season_year, eth_rate, last_n=RECENT_PRICES_COUNT):
    cache_key = (player_slug, season_year, last_n)
    cached = _cache_get(_RECENT_PUBLIC_PRICES_CACHE, cache_key)
    if cached is not _CACHE_MISS:
        return cached

    # FIX 17/07 (richiesta esplicita dell'utente, caso Seo Jin-Su -- mediana notificata 4.34EUR
    # non tornava con le ultime 3 vendite "pubbliche" viste nello storico reale, 3.68/4.34/4.10):
    # includePrivateSales era false, escludeva le "Offerta diretta" (vendite negoziate). Stessa
    # scelta gia' fatta esplicitamente dall'utente per il tracker classico (RECENT_SALE_GATE in
    # track.py: "se altre 3 persone prima di me l'hanno gia' avuto a un prezzo piu' basso, non e'
    # un affare, anche se sembra un calo" -- ogni vendita reale conta come segnale, negoziata o
    # no). Stessa filosofia qui: includePrivateSales true, piu' dati invece di escluderne un tipo.
    query = """
    query RecentPrices($slug: String!, $rarity: Rarity!, $season: Int, $lastN: Int!) {
      anyPlayer(slug: $slug) {
        tokenPrices(rarity: $rarity, season: $season, last: $lastN, includePrivateSales: true) {
          nodes {
            amounts { eurCents wei usdCents gbpCents lamport }
          }
        }
      }
    }
    """

    # FIX 17/07 (richiesta esplicita dell'utente, "scettico sul funzionamento" -- log reale con
    # un ban 429 a meta' scansione: 12 giocatori di fila finiti su "nessun prezzo precedente
    # trovato" nello stesso identico secondo): _run() trattava QUALSIASI errore GraphQL (incluso
    # un ban rate-limit) esattamente come "il giocatore non ha vendite recenti" -- restituendo
    # [] in entrambi i casi, indistinguibili. Falso: durante quel ban i comparabili NON sono mai
    # stati davvero interrogati con successo, quindi non sappiamo se il giocatore ha vendite o
    # no. Ora _run() ritorna anche un flag "errored" cosi' il chiamante puo' distinguere una
    # genuina assenza di dati (stabile, ok da cachare) da un fallimento transitorio di query
    # (da NON cachare come "asta invariata", va ritentata al prossimo giro).
    def _run(season_arg):
        variables = {"slug": player_slug, "rarity": "limited", "lastN": last_n}
        if season_arg is not None:
            variables["season"] = season_arg
        data = graphql_query(query, variables)
        if data.get('errors'):
            return [], True
        nodes = (((data.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}).get('nodes') or []
        prices = []
        for node in nodes:
            # FIX 17/07: prima leggeva solo eurCents/wei a mano qui -- ora passa da
            # eur_price_from_amounts, stessa funzione usata ovunque nel file, cosi' beneficia
            # automaticamente anche del fix usdCents/gbpCents (e del contatore diagnostico).
            p = eur_price_from_amounts(node.get('amounts'), eth_rate)
            if p is not None:
                prices.append(p)
        return prices, False

    # Cache-ato SOLO se la query e' andata a buon fine (errored=False) -- un fallimento di rete/
    # rate limit non deve essere ricordato come "risultato vero" per 30s, va ritentato al
    # prossimo utilizzo (stesso motivo del fix gemello su save_eval_snapshot piu' sopra).
    def _finish(prices, errored):
        if not errored:
            _cache_set(_RECENT_PUBLIC_PRICES_CACHE, cache_key, (prices, errored))
        return prices, errored

    try:
        prices, errored = _run(season_year)
        if prices:
            _SEASON_FILTER_STATS['with_season_ok'] += 1
            return _finish(prices, errored)
        if season_year is None:
            _SEASON_FILTER_STATS['both_empty'] += 1
            return _finish(prices, errored)
        # RISCHIO NOTO: senza filtro stagione possiamo mescolare vendite classic/in_season dello
        # stesso giocatore (stesso limite gia' documentato per tokens.tokenPrices in track.py) --
        # ma le aste sono sempre in_season, quindi un riferimento "sporco" e' comunque meglio di
        # uno zero strutturale che ci fa saltare l'asta a prescindere.
        fallback_prices, fb_errored = _run(None)
        if fallback_prices:
            _SEASON_FILTER_STATS['fallback_no_season_ok'] += 1
            return _finish(fallback_prices, fb_errored)
        _SEASON_FILTER_STATS['both_empty'] += 1
        return _finish([], (errored or fb_errored))
    except Exception as e:
        log(f"Errore nel recuperare i prezzi recenti per {player_slug}: {e}")
        return [], True


# --- Riverifica live pre-notifica: query tokens.liveAuctions, la STESSA gia' usata e
# confermata funzionante dal vecchio bot a polling (auctions.py), qui filtrata per giocatore.
# RISOLTO IL 16/07: query corretta per riverificare una singola asta, trovata catturando
# le richieste GraphQL della pagina web di Sorare stessa (Chrome DevTools, operazione
# "BidPaymentFlowQuery" usata dalla modale "Fai offerta"). Il campo giusto e'
# tokens.auction(id: <uuid NUDO, senza il prefisso "EnglishAuction:">), che restituisce
# direttamente currentPrice/minNextBid/endDate/open/cancelled/bidsCount per QUELLA asta --
# niente piu' bisogno di scorrere liste di aste live per giocatore o globali. Validata sia
# come persisted query (operationId del sito) sia come query ad-hoc scritta a mano (piu'
# robusta, non dipende da un hash legato alla build del frontend Sorare).
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
      bidsCount
    }
  }
}
"""


def get_auction_live_state(auction_id):
    """Rilegge lo stato REALE e aggiornato di una singola asta dato il suo id (formato
    'EnglishAuction:<uuid>'). Ritorna una tupla (dati, query_fallita):
    - (dict con current_price_eur/min_next_bid_eur/end_date/open/cancelled, False) se la
      query ha funzionato e l'asta esiste.
    - (None, False) se la query ha funzionato ma l'asta non esiste piu' (rimossa/scaduta da
      tempo): in quel caso meglio non notificare che notificare su dati vecchi.
    - (None, True) se la query stessa e' fallita (errore di rete o GraphQL inatteso): in
      quel caso non possiamo dire nulla sull'asta, il chiamante decide come comportarsi."""
    bare_id = auction_id.split(':', 1)[1] if ':' in auction_id else auction_id
    try:
        data = graphql_query(AUCTION_BY_ID_QUERY, {"id": bare_id})
        if data.get('errors'):
            log(f"[riverifica live asta] errore GraphQL per {auction_id}: {data['errors']}")
            return None, True
        auction_data = ((data.get('data') or {}).get('tokens') or {}).get('auction')
        if auction_data is None:
            return None, False
        return auction_data, False
    except Exception as e:
        log(f"[riverifica live asta] eccezione per {auction_id}: {e}")
        return None, True


LIVE_AUCTIONS_QUERY = """
query ListLiveAuctions($n: Int!) {
  tokens {
    liveAuctions(last: $n) {
      nodes {
        id
        currentPrice
        minNextBid
        endDate
        anyCards {
          slug
          rarityTyped
          sport
          anyPlayer { slug displayName }
          sportSeason { name }
        }
      }
    }
  }
}
"""


# FIX 17/07 (backlog, richiesta esplicita dell'utente "se tracciassimo anche le 50 piu' vicine
# alla scadenza?"): liveAuctions(last: N) prende le N aste piu' RECENTI (per creazione, stesso
# principio di "last" usato ovunque in questo codebase, es. fetch_all_live_offers) -- un'asta
# aperta da tempo, ferma (nessuna nuova offerta, quindi nessun evento tokenAuctionWasUpdated,
# che scatta solo sui CAMBIAMENTI) e vicina alla scadenza puo' scivolare fuori da questa finestra
# ed essere invisibile sia al WS che alla scansione di sicurezza -- proprio le aste ferme e vicine
# alla chiusura sono pero' le piu' interessanti per uno snipe (nessun altro le sta piu'
# guardando). Proviamo per tentativi (introspection disabilitata, stesso approccio usato in tutta
# la sessione per i campi/argomenti scoperti finora) se liveAuctions supporta un ordinamento per
# data di scadenza invece che solo "piu' recenti per creazione".
def discover_auctions_end_date_sort():
    candidates = [
        ("orderBy: END_DATE_ASC",
         "query D($n: Int!) { tokens { liveAuctions(last: $n, orderBy: END_DATE_ASC) { nodes { id endDate } } } }"),
        ("sort: END_DATE_ASC",
         "query D($n: Int!) { tokens { liveAuctions(last: $n, sort: END_DATE_ASC) { nodes { id endDate } } } }"),
        ("sortBy: END_DATE_ASC",
         "query D($n: Int!) { tokens { liveAuctions(last: $n, sortBy: END_DATE_ASC) { nodes { id endDate } } } }"),
        ("orderBy: endDate_ASC",
         "query D($n: Int!) { tokens { liveAuctions(last: $n, orderBy: endDate_ASC) { nodes { id endDate } } } }"),
        ("endingSoon: true",
         "query D($n: Int!) { tokens { liveAuctions(last: $n, endingSoon: true) { nodes { id endDate } } } }"),
        ("first: N (senza last, per vedere se cambia l'ordine di default)",
         "query D($n: Int!) { tokens { liveAuctions(first: $n) { nodes { id endDate } } } }"),
    ]
    for label, query in candidates:
        try:
            data = graphql_query(query, {"n": 5})
            if data.get('errors'):
                log(f"[diagnostica ordinamento aste] {label}: errore -- {data['errors']}")
            else:
                log(f"[diagnostica ordinamento aste] {label}: SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica ordinamento aste] {label}: eccezione -- {e}")
    log("[diagnostica ordinamento aste] tentativi completati.")


# FIX 17/07 (seguito a discover_auctions_end_date_sort, che ha escluso un ordinamento
# server-side per data di scadenza): se non si puo' ordinare per endDate, l'unica via per
# raggiungere le aste ferme-vicine-alla-scadenza e' allargare il campione oltre le 50 aste
# attuali e ordinare client-side. liveAuctions(last: N) tronca comunque a ~50 nodi per
# richiesta (stesso comportamento gia' confermato su liveSingleSaleOffers, vedi
# fetch_all_live_offers) -- questo diagnostico verifica se la STESSA identica paginazione a
# cursore (pageInfo.hasPreviousPage + argomento "before") funziona anche su liveAuctions,
# che e' una connection diversa (globale, non filtrata per player) e quindi non e' detto
# supporti gli stessi argomenti solo perche' liveSingleSaleOffers li supporta.
def discover_auctions_pagination():
    query = """
    query D($n: Int!, $cursor: String) {
      tokens {
        liveAuctions(last: $n, before: $cursor) {
          totalCount
          pageInfo { hasPreviousPage startCursor }
          nodes { id endDate }
        }
      }
    }
    """
    try:
        data = graphql_query(query, {"n": 5, "cursor": None})
        if data.get('errors'):
            log(f"[diagnostica paginazione aste] before/pageInfo: errore -- {data['errors']}")
            log("[diagnostica paginazione aste] tentativi completati.")
            return
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {})
        log(f"[diagnostica paginazione aste] before/pageInfo: SUCCESSO -- totalCount={conn.get('totalCount')} "
            f"pageInfo={conn.get('pageInfo')} nodes={conn.get('nodes')}")
        page_info = conn.get('pageInfo') or {}
        cursor = page_info.get('startCursor')
        if page_info.get('hasPreviousPage') and cursor:
            data2 = graphql_query(query, {"n": 5, "cursor": cursor})
            if data2.get('errors'):
                log(f"[diagnostica paginazione aste] seconda pagina (before={cursor}): errore -- {data2['errors']}")
            else:
                conn2 = (((data2.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {})
                log(f"[diagnostica paginazione aste] seconda pagina: SUCCESSO -- pageInfo={conn2.get('pageInfo')} "
                    f"nodes={conn2.get('nodes')}")
        else:
            log("[diagnostica paginazione aste] hasPreviousPage=False o startCursor assente, "
                "niente seconda pagina da testare con questo campione piccolo (n=5).")
    except Exception as e:
        log(f"[diagnostica paginazione aste] eccezione -- {e}")
    log("[diagnostica paginazione aste] tentativi completati.")


# FIX 17/07 (seguito a discover_auctions_pagination, confermata funzionante: before/cursor +
# totalCount=1048 aste live sul mercato contro le 50 coperte oggi da run_safety_poll). Seconda
# scansione di sicurezza complementare: run_safety_poll prende le 50 aste piu' RECENTI per
# creazione (last: N), questa pagina un campione piu' ampio e filtra CLIENT-SIDE per endDate
# (nessun ordinamento server-side esiste, vedi discover_auctions_end_date_sort) per raggiungere
# le aste FERME (nessuna nuova offerta -> nessun evento WS) ma vicine alla scadenza, che sono
# proprio quelle a rischio di scivolare fuori dalla finestra delle 50 piu' recenti restando
# invisibili fino alla chiusura. Testata a mano il 17/07 (run reale: 500 aste scansionate in
# 10 pagine, 54 in scadenza entro 6h, tutte valutate correttamente, nessun errore/rate-limit,
# ~23s di overhead) -- richiesta esplicita dell'utente di lasciarla ON di default da subito nel
# cron esterno (non piu' solo opt-in via workflow_dispatch). Il costo delle rivalutazioni ripetute
# resta comunque basso: process_auction scarta subito (already_notified/skip_unchanged_since_
# last_eval, cache SQLite persistente tra run) le aste gia' viste e invariate, senza rifare le
# query pesanti (storico vendite, prezzo diretto, riverifica live) -- stesso identico
# meccanismo gia' usato per run_safety_poll/WS, nessuna logica nuova serviva per questo.
AUCTION_ENDING_SOON_ENABLED = bool(os.environ.get('AUCTION_ENDING_SOON_ENABLED', 'si').strip())
AUCTION_ENDING_SOON_MAX_PAGES = int(os.environ.get('AUCTION_ENDING_SOON_MAX_PAGES', '10'))
AUCTION_ENDING_SOON_WINDOW_HOURS = float(os.environ.get('AUCTION_ENDING_SOON_WINDOW_HOURS', '6'))

LIVE_AUCTIONS_PAGINATED_QUERY = """
query ListLiveAuctionsPaginated($n: Int!, $cursor: String) {
  tokens {
    liveAuctions(last: $n, before: $cursor) {
      pageInfo { hasPreviousPage startCursor }
      nodes {
        id
        currentPrice
        minNextBid
        endDate
        anyCards {
          slug
          rarityTyped
          sport
          anyPlayer { slug displayName }
          sportSeason { name }
        }
      }
    }
  }
}
"""


def get_ending_soon_auctions(max_pages, window_hours):
    """Pagina fino a max_pages pagine da 50 aste (before/startCursor, meccanismo confermato in
    discover_auctions_pagination), poi filtra client-side quelle con endDate entro le prossime
    window_hours ore usando seconds_until_end (stessa funzione gia' usata per il countdown nei
    messaggi Telegram, cosi' la definizione di "quanto manca" resta unica in tutto il file)."""
    all_nodes = []
    cursor = None
    pages_fetched = 0
    for _ in range(max_pages):
        try:
            data = graphql_query(LIVE_AUCTIONS_PAGINATED_QUERY, {"n": 50, "cursor": cursor})
        except Exception as e:
            log(f"[scansione ending-soon] eccezione pagina {pages_fetched + 1}: {e}")
            break
        if data.get('errors'):
            log(f"[scansione ending-soon] errore pagina {pages_fetched + 1}: {data['errors']}")
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
    window_seconds = window_hours * 3600
    ending_soon = []
    for node in all_nodes:
        remaining = seconds_until_end(node.get('endDate'))
        if remaining is not None and 0 < remaining <= window_seconds:
            ending_soon.append(node)
    log(f"[scansione ending-soon] {pages_fetched} pagine scansionate ({len(all_nodes)} aste totali), "
        f"{len(ending_soon)} in scadenza entro {window_hours}h")
    return ending_soon


def run_ending_soon_poll(eth_rate, stats):
    """Seconda scansione di sicurezza (vedi commento sopra get_ending_soon_auctions). Le aste
    gia' viste da run_safety_poll o dal WS vengono ri-processate anche qui, ma
    handle_auction_event/skip_unchanged_since_last_eval le scarta subito se invariate dall'ultima
    valutazione -- nessun rischio di doppia notifica, solo query GraphQL extra."""
    log(f"Scansione ending-soon: fino a {AUCTION_ENDING_SOON_MAX_PAGES} pagine, finestra "
        f"{AUCTION_ENDING_SOON_WINDOW_HOURS}h...")
    auctions = get_ending_soon_auctions(AUCTION_ENDING_SOON_MAX_PAGES, AUCTION_ENDING_SOON_WINDOW_HOURS)
    log(f"Scansione ending-soon: {len(auctions)} aste in scadenza trovate, valutazione in corso...")
    for auction in auctions:
        try:
            handle_auction_event(auction, eth_rate, stats)
        except Exception as e:
            log(f"Errore nel processare un'asta durante la scansione ending-soon: {e}")
    log("Scansione ending-soon completata.")


def get_live_auctions(n):
    """Le N aste live piu' recenti su tutto il mercato (query identica a quella gia'
    validata dal vecchio auctions.py). NOTA: n=50 e' gia' al limite di troncamento noto
    lato server per query di lista simili (vedi fetch_all_live_offers) -- non paginata per
    ora; se in futuro servisse superare 50 andra' verificato se questa connection supporta
    pageInfo/before come le altre (da fare quando si puo' controllare live)."""
    try:
        data = graphql_query(LIVE_AUCTIONS_QUERY, {"n": n})
        if data.get('errors'):
            log(f"[scansione sicurezza] errore nella query liveAuctions: {data['errors']}")
            return []
        nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {}).get('nodes') or []
        return nodes
    except Exception as e:
        log(f"[scansione sicurezza] eccezione nel recuperare le aste live: {e}")
        return []


def run_safety_poll(eth_rate, stats):
    """Scansione una tantum a inizio esecuzione, prima di aprire il WS -- recupera le aste
    che il WS potrebbe aver perso nel buco tra la fine dell'esecuzione precedente e
    l'inizio di questa (vedi nota su NUM_SAFETY_POLL_AUCTIONS piu' in alto)."""
    log(f"Scansione di sicurezza: controllo le {NUM_SAFETY_POLL_AUCTIONS} aste live piu' recenti...")
    auctions = get_live_auctions(NUM_SAFETY_POLL_AUCTIONS)
    log(f"Scansione di sicurezza: {len(auctions)} aste trovate, valutazione in corso...")
    for auction in auctions:
        try:
            handle_auction_event(auction, eth_rate, stats)
        except Exception as e:
            log(f"Errore nel processare un'asta durante la scansione di sicurezza: {e}")
    log("Scansione di sicurezza completata.")


# --- Logica di valutazione di un'asta, identica a quella gia' validata in auctions.py:
#     l'evento WS (con anyCards incluso) ha la STESSA forma di un nodo liveAuctions, quindi
#     questa funzione e' riutilizzabile cosi' com'e'. ---
# FIX 17/07 (richiesta esplicita dell'utente, "troppe poche notifiche, qualcosa non torna"):
# aggiunto un contatore diagnostico per ogni motivo di scarto -- prima l'unico modo per capire
# perche' un'asta non veniva notificata era scorrere i log riga per riga o interrogare
# decisions_log su auctions.db. Stesso schema gia' usato oggi per track.py/zenlock_model_
# tracker.py: un dict condiviso, incrementato ad ogni punto di uscita, stampato in un unico
# riepilogo a fine esecuzione.
def bump(stats, key):
    stats[key] = stats.get(key, 0) + 1


def process_auction(auction, eth_rate, stats):
    auction_id = auction.get('id')
    current_price_eur = wei_to_eur(auction.get('currentPrice'), eth_rate)
    if auction_id is None or current_price_eur is None:
        bump(stats, 'skip_no_price_data')
        return

    if already_notified(auction_id):
        bump(stats, 'skip_already_notified')
        return

    min_next_bid_raw = auction.get('minNextBid')
    min_next_bid_eur = wei_to_eur(min_next_bid_raw, eth_rate)

    # FIX 17/07 (richiesta esplicita dell'utente, "log molto pesante, scarta le aste gia'
    # analizzate... se e' inutile e' inutile, non serve un controllo in due run diverse"): se
    # questa identica asta e' gia' stata valutata per intero con lo STESSO prezzo attuale e la
    # STESSA offerta minima, rifare tutta l'analisi (storico vendite, tetto, riverifica live con
    # sleep) produrrebbe esattamente lo stesso risultato di prima -- lavoro e log inutili.
    # Saltiamo silenziosamente (solo un contatore, niente riga di log per asta) e continuiamo
    # solo se qualcosa e' davvero cambiato (nuova offerta, asta salita) da quando l'ha vista
    # l'esecuzione precedente.
    last_snapshot = get_last_eval_snapshot(auction_id)
    if last_snapshot is not None:
        last_price, last_min_bid = last_snapshot
        if _floats_equal(last_price, current_price_eur) and _floats_equal(last_min_bid, min_next_bid_eur):
            bump(stats, 'skip_unchanged_since_last_eval')
            return
    # Valori "di ingresso" (prima della riverifica live piu' sotto, che puo' riassegnare
    # current_price_eur/min_next_bid_eur a valori leggermente diversi/piu' precisi): lo snapshot
    # va sempre salvato/confrontato su QUESTI, altrimenti il confronto "invariata dall'ultimo
    # giro" fatto in cima a questa funzione (che legge sempre i valori grezzi dell'evento/poll,
    # mai quelli della riverifica) non troverebbe mai una corrispondenza -- vanificando la cache.
    entry_current_price_eur = current_price_eur
    entry_min_next_bid_eur = min_next_bid_eur

    # NOTA: il salvataggio dello snapshot NON avviene qui in blocco -- vedi FIX piu' sotto
    # (get_recent_public_prices/skip_recent_prices_query_failed): un'asta va marcata come "vista
    # a questo prezzo" solo quando l'abbiamo valutata DAVVERO fino in fondo con dati validi, mai
    # quando un fallimento di rete/rate-limit ci ha impedito di concludere -- altrimenti la
    # cache "invariata" la nasconderebbe per sempre anche dopo che il rate limit e' passato.

    cards = auction.get('anyCards') or []
    target_card = None
    for c in cards:
        if c.get('rarityTyped') != 'limited':
            continue
        if c.get('sport') != 'FOOTBALL':
            continue
        target_card = c
        break

    if not target_card:
        bump(stats, 'skip_no_limited_football_card')
        save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur)
        return

    # Stampa sempre id asta E slug carta, per ogni asta valutata -- cosi' e' facile prenderne
    # una reale dai log per test/diagnostica, senza dover aprire auctions.db (es.
    # diagnostic_live_auction_lookup.py).
    log(f"[asta] valutazione evento id={auction_id} card_slug={target_card.get('slug')}")

    player = target_card.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    if not player_slug:
        bump(stats, 'skip_no_player_slug')
        return

    season_name = (target_card.get('sportSeason') or {}).get('name', 'unknown')
    # FIX 16/07 (caso Sebastian Berhalter): le aste inglesi di Sorare sono SEMPRE e SOLO
    # per carte in_season -- non esistono aste per carte classic. Prima qui si derivava
    # season_type confrontando season_name con CURRENT_SEASON_LABELS, ma quell'etichetta
    # va aggiornata ad ogni cambio stagione (es. "2025-26" -> "2026-27") e nel frattempo
    # classificava erroneamente come "classic" carte che erano gia' in_season a tutti gli
    # effetti (caso reale: Berhalter, auction id 212, season_type finito a 'classic' ->
    # direct_sale_price preso dal mercato classic (6.70EUR) invece che in_season (23.80EUR
    # reali), tetto consigliato crollato e rilancio da 16.91EUR scartato per errore). Per
    # le aste il bucket e' sempre in_season, punto: niente piu' classificazione da
    # season_name.
    season_type = 'in_season'

    season_year = parse_season_year(season_name)
    recent_prices, recent_prices_errored = get_recent_public_prices(player_slug, season_year, eth_rate)
    if not recent_prices:
        if recent_prices_errored:
            # Fallimento di query (es. rate limit 429), NON un'assenza genuina di vendite -- non
            # sappiamo davvero se il giocatore ha comparabili o no. Contatore separato per non
            # confonderlo con skip_no_recent_prices genuino, e NIENTE salvataggio snapshot: va
            # ritentato al prossimo giro, non marcato come "gia' visto, niente di nuovo".
            log(f"{player_name}: query prezzi recenti fallita (probabile rate limit), salto "
                f"per questo giro senza marcare l'asta come vista")
            log_decision(auction_id, player_slug, player_name, season_type, "skip_recent_prices_query_failed",
                         current_price=current_price_eur, min_next_bid=min_next_bid_eur)
            bump(stats, 'skip_recent_prices_query_failed')
            return
        log(f"{player_name}: nessun prezzo precedente trovato, salto")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_no_recent_prices",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur)
        bump(stats, 'skip_no_recent_prices')
        save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur)
        return

    last_price = recent_prices[-1]
    if current_price_eur >= last_price:
        log(f"{player_name}: asta attuale ({current_price_eur:.2f}EUR) non sotto l'ultimo prezzo "
            f"({last_price:.2f}EUR), salto")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_not_below_last_price",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur)
        bump(stats, 'skip_not_below_last_price')
        save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur)
        return

    # Verifica LIVE del prezzo minimo di vendita diretta -- confronto per bucket in_season/
    # classic (vedi nota nella docstring di get_live_min_direct_sale).
    direct_sale_price = get_live_min_direct_sale(player_slug, season_type, eth_rate)
    if direct_sale_price is None:
        # Fallback alla cache locale di track.py, che pero' usa solo il bucket generico
        # in_season/classic (non la stagione esatta) -- meno preciso, usato solo se la
        # query live fallisce.
        direct_sale_price = get_current_min_direct_sale(player_slug, season_type)

    # FIX 17/07: se anche il fallback in cache non trova nulla, usiamo l'ultima vendita REALE
    # recente (last_price, gia' calcolato sopra) come riferimento di riserva invece di
    # arrenderci del tutto -- vedi nota su AUCTION_HISTORICAL_FALLBACK_MARGIN_MULTIPLIER.
    is_historical_reference = False
    if direct_sale_price is None:
        direct_sale_price = last_price
        is_historical_reference = True

    # FIX 16/07: prima direct_sale_price veniva infilato dentro la mediana insieme ai
    # prezzi di vendite recenti -- con pochi valori recenti alti, la mediana lo diluiva e
    # il tetto consigliato finale poteva finire SOPRA il prezzo di vendita diretta (casi
    # reali: Griezmann tetto 26.89EUR vs diretta 13.0EUR, margine -13.89; Brais Mendez
    # tetto 5.30EUR vs diretta 4.0EUR, margine -1.30). Non ha senso raccomandare di
    # rilanciare in asta oltre il prezzo a cui si puo' comprare SUBITO una carta
    # equivalente in vendita diretta. Ora la mediana riflette solo le vendite recenti, e
    # direct_sale_price fa da tetto massimo esplicito.
    median_reference = statistics.median(recent_prices)
    recommended_ceiling = median_reference * (1 - BID_DISCOUNT)
    if direct_sale_price is not None and direct_sale_price < recommended_ceiling:
        recommended_ceiling = direct_sale_price

    # FIX 16/07 (caso Jeppe Tverskov): la mediana usa fino a RECENT_PRICES_COUNT vendite
    # recenti insieme, quindi puo' restare piu' alta della vendita PIU' recente in assoluto
    # se quella e' scesa rispetto alle precedenti (caso reale: ultima vendita 8.70EUR 37
    # minuti fa, ma mediana 11.40EUR presa insieme a due vendite piu' vecchie e piu' care ->
    # tetto consigliato 9.12EUR, SOPRA l'ultima vendita vera). Non ha senso consigliare di
    # offrire molto piu' di quanto sia costata l'ultima carta equivalente venduta.
    # FIX 17/07 (richiesta esplicita dell'utente, "troppo stringente... poche notifiche"):
    # last_price come tetto RIGIDO (senza tolleranza) rendeva la raccomandazione ostaggio di
    # un singolo dato -- rumoroso quanto un intero mercato preso da solo. Ammorbidito con
    # AUCTION_LAST_PRICE_TOLERANCE: il tetto resta ancorato all'ultima vendita vera (protezione
    # originale del caso Tverskov), ma con un po' di margine invece di essere assoluto.
    last_price_ceiling = last_price * (1 + AUCTION_LAST_PRICE_TOLERANCE)
    if last_price_ceiling < recommended_ceiling:
        recommended_ceiling = last_price_ceiling

    # Riverifica live subito prima di decidere se notificare: l'evento che ha innescato
    # questo controllo potrebbe essere vecchio (caso Marco Reus: evento con currentPrice=
    # 2.17EUR e ~11h rimanenti, notificato quando l'asta era GIA' a 10.24EUR con solo ~4h
    # rimanenti). RISOLTO IL 16/07 con la query tokens.auction(id: ...) (vedi
    # get_auction_live_state) trovata catturando le richieste GraphQL della pagina web di
    # Sorare: legge lo stato REALE di QUESTA specifica asta, niente piu' stopgap.
    time.sleep(AUCTION_RECHECK_DELAY_SECONDS)
    fresh, query_failed = get_auction_live_state(auction_id)
    if query_failed:
        log(f"{player_name}: riverifica live fallita per errore di rete/query, "
            f"non notifico per sicurezza (evita di agire su dati potenzialmente vecchi)")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_recheck_query_failed",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        bump(stats, 'skip_recheck_query_failed')
        return
    if fresh is None:
        log(f"{player_name}: l'asta non esiste piu' alla riverifica live "
            f"(conclusa/rimossa nel frattempo), non notifico")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_could_not_reverify_live",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        bump(stats, 'skip_could_not_reverify_live')
        save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur)
        return
    if fresh.get('cancelled') or not fresh.get('open'):
        debug_price = wei_to_eur(fresh.get('currentPrice'), eth_rate)
        log(f"{player_name}: asta non piu' aperta alla riverifica live (open={fresh.get('open')}, "
            f"cancelled={fresh.get('cancelled')}), non notifico -- dati grezzi ricevuti: "
            f"currentPrice={debug_price if debug_price is not None else fresh.get('currentPrice')}EUR, "
            f"endDate={fresh.get('endDate')}, bidsCount={fresh.get('bidsCount')}")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_auction_no_longer_open",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        bump(stats, 'skip_auction_no_longer_open')
        save_eval_snapshot(auction_id, current_price_eur, min_next_bid_eur)
        return

    fresh_current_price_eur = wei_to_eur(fresh.get('currentPrice'), eth_rate)
    fresh_min_next_bid_eur = wei_to_eur(fresh.get('minNextBid'), eth_rate)
    if fresh_current_price_eur is None:
        log(f"{player_name}: dati di prezzo mancanti alla riverifica live, non notifico per sicurezza")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_recheck_missing_price",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        bump(stats, 'skip_recheck_missing_price')
        return
    if abs(fresh_current_price_eur - current_price_eur) > 0.01:
        log(f"{player_name}: prezzo aggiornato alla riverifica live ({current_price_eur:.2f}EUR "
            f"dell'evento -> {fresh_current_price_eur:.2f}EUR reale)")
    current_price_eur = fresh_current_price_eur
    min_next_bid_eur = fresh_min_next_bid_eur
    auction = dict(auction, endDate=fresh.get('endDate'))

    # FIX 17/07 (richiesta esplicita dell'utente, "vada vada" -- dopo aver verificato che
    # skip_min_bid_exceeds_ceiling da solo scartava 21 aste su 55 in un run, PRIMA che il
    # controllo sul margine (appena reso piu' permissivo) potesse mai essere raggiunto):
    # recommended_ceiling (mediana scontata del 20%, o vendita diretta, o ultima vendita) era
    # usato come un muro rigido -- se l'offerta minima per stare in testa lo superava anche di
    # poco, l'asta veniva scartata SENZA MAI calcolare il margine vero contro direct_sale_price.
    # Questo aveva senso quando il margine si calcolava (per bug) su recommended_ceiling stesso
    # -- ora che si calcola sul prezzo VERO da pagare (starting_bid), il muro e' ridondante e
    # scarta affari legittimi: un'offerta minima leggermente sopra il tetto-mediana puo' avere
    # comunque un margine enorme se la vendita diretta e' molto piu' cara. Il prezzo da pagare
    # e' semplicemente quello vero (offerta minima se c'e', altrimenti il prezzo attuale);
    # recommended_ceiling resta calcolato e mostrato nella notifica come riferimento
    # informativo, ma non scarta piu' nulla da solo -- ci pensa il controllo sul margine
    # qui sotto, l'unico che conta davvero.
    starting_bid = min_next_bid_eur if min_next_bid_eur is not None else current_price_eur

    # FIX 17/07 (richiesta esplicita dell'utente, "impossibile zero notifiche" -- log reali
    # mostravano margine stimato ESATTAMENTE 0.0 su piu' aste, es. Ros/Hrvoje Babec): il margine
    # veniva calcolato come direct_sale_price - recommended_ceiling invece che sul prezzo VERO
    # da pagare. Il margine vero e' quanto si risparmia rispetto alla vendita diretta AL PREZZO
    # CHE SI PAGHEREBBE DAVVERO per essere in testa ora (starting_bid). NOTA (aggiornata dopo il
    # fix piu' sopra che ha tolto il muro rigido su recommended_ceiling): starting_bid NON e'
    # piu' garantito <= recommended_ceiling -- ma non serve piu' quella garanzia, perche' se
    # starting_bid supera direct_sale_price il margine risulta negativo e fallisce comunque
    # questo controllo da solo, senza bisogno di un muro separato a monte.
    margin_estimate = (direct_sale_price - starting_bid) if direct_sale_price is not None else None
    # FIX 17/07: soglia minima ora a scaglioni (vedi required_margin_eur piu' in alto) invece
    # del vecchio MIN_MARGIN_EUR fisso -- stesso spirito del fix gemello di zenlock/track.py.
    min_margin_required = required_margin_eur(direct_sale_price)
    if is_historical_reference:
        min_margin_required *= AUCTION_HISTORICAL_FALLBACK_MARGIN_MULTIPLIER

    if margin_estimate is None or margin_estimate < min_margin_required:
        # FIX 17/07 (richiesta esplicita dell'utente, "279 aste zero notifiche, non mi sembra
        # normale"): la riga di log non salvava direct_sale_price/starting_bid, quindi non era
        # possibile verificare a posteriori se required_margin_eur avesse usato il riferimento
        # giusto senza rifare i calcoli a mano. Aggiunti entrambi qui.
        log(f"{player_name}: margine stimato "
            f"{margin_estimate if margin_estimate is not None else 'n/d'} sotto la soglia minima "
            f"({min_margin_required:.2f}EUR{' , riferimento STORICO' if is_historical_reference else ''}), "
            f"non notifico -- vendita diretta minima "
            f"{direct_sale_price if direct_sale_price is not None else 'n/d'}"
            f"{' (storico/ultima vendita, non live)' if is_historical_reference else ''}, "
            f"minimo per essere in testa {starting_bid:.2f}EUR")
        log_decision(auction_id, player_slug, player_name, season_type,
                     "skip_margin_too_low_historical" if is_historical_reference else "skip_margin_too_low",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price, margin_estimate=margin_estimate)
        bump(stats, 'skip_margin_too_low_historical' if is_historical_reference else 'skip_margin_too_low')
        save_eval_snapshot(auction_id, entry_current_price_eur, entry_min_next_bid_eur)
        return

    # FIX 17/07 (bug introdotto dal fix precedente sullo stesso giro, trovato con un test
    # mirato prima di consegnare): rimosso il muro rigido su recommended_ceiling, un'offerta
    # minima per stare in testa (starting_bid) puo' ora essere SOPRA recommended_ceiling (e'
    # proprio il punto del fix -- casi con margine vero ottimo anche oltre il tetto-mediana).
    # Ma "OFFRI FINO A" nel messaggio Telegram usava ancora recommended_ceiling: risultato,
    # un'istruzione contraddittoria ("offri fino a 2.88" quando servono almeno 3.20 per essere
    # validi). Il vero tetto consigliabile ora e' quanto si puo' offrire mantenendo ALMENO il
    # margine minimo richiesto rispetto alla vendita diretta -- per costruzione sempre
    # >= starting_bid qui, visto che abbiamo gia' superato il controllo sul margine sopra.
    suggested_max_offer = (direct_sale_price - min_margin_required) if direct_sale_price is not None else recommended_ceiling
    if suggested_max_offer < starting_bid:
        suggested_max_offer = starting_bid  # rete di sicurezza, non dovrebbe mai servire

    log(f"ASTA INTERESSANTE!{' [RIFERIMENTO STORICO]' if is_historical_reference else ''} "
        f"{player_name}: attuale {current_price_eur:.2f}EUR, "
        f"minimo per essere in testa {starting_bid:.2f}EUR, "
        f"mediana riferimento {median_reference:.2f}EUR, "
        f"tetto consigliato (informativo) {recommended_ceiling:.2f}EUR, "
        f"offri fino a {suggested_max_offer:.2f}EUR, "
        f"vendita diretta minima {direct_sale_price if direct_sale_price is not None else 'n/d'}"
        f"{' (storico/ultima vendita, NON live)' if is_historical_reference else ''}, "
        f"margine stimato {margin_estimate if margin_estimate is not None else 'n/d'}")
    # FIX 17/07 (richiesta esplicita dell'utente, caso Seo Jin-Su -- "la mediana e' corretta?"):
    # senza i prezzi grezzi usati non era possibile verificare la mediana confrontandola con lo
    # storico vendite reale su Sorare. Dump esplicito, stesso principio gia' usato in zenlock
    # ("DEBUG comparabili grezzi") per poter controllare 1:1 ogni notifica futura.
    log(f"[asta] DEBUG prezzi grezzi usati per la mediana ({player_name}, ultime "
        f"{RECENT_PRICES_COUNT} vendite pubbliche+private): {recent_prices}")

    card_slug = target_card.get('slug')
    if card_slug:
        link = f"https://sorare.com/it/football/market/shop/auctions?rarity=limited&card={card_slug}"
        link_text = "Vai direttamente all'asta"
    else:
        link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
        link_text = "Vai alla pagina del giocatore (apri tu la scheda Aste)"

    indicator = "\U0001F7E0"
    if margin_estimate is not None and recommended_ceiling > 0:
        margin_pct = margin_estimate / recommended_ceiling
        if margin_pct >= 0.5:
            indicator = "\U0001F7E2"
        elif margin_pct >= 0.2:
            indicator = "\U0001F7E1"

    # "Offri fino a" e' il numero che conta davvero al volo, quindi va reso molto piu'
    # evidente delle altre righe. Prima si usava una conversione in caratteri Unicode
    # "fullwidth" per farlo sembrare piu' grande, ma su Telegram si spaziava male e le
    # parole si univano in modo illeggibile (casi Seo Jin-Su e German Berterame: "OFFRIFINOA:
    # 3. 09€"). Soluzione piu' semplice e affidabile: tutto maiuscolo, grassetto, e una
    # cornice di separatori sopra e sotto che lo isola visivamente dal resto del messaggio.
    seconds_left = seconds_until_end(auction.get('endDate'))
    time_remaining_label = format_time_remaining(seconds_left)
    is_urgent = seconds_left is not None and seconds_left <= URGENT_TIME_THRESHOLD_SECONDS
    if is_urgent:
        time_line = (f"⚠️ Scade tra: <b>{time_remaining_label}</b> "
                     f"-- affrettati, il link puo' scadere prima che tu clicchi!")
    else:
        time_line = f"⏱ Scade tra: <b>{time_remaining_label}</b>"

    separator = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    msg_lines = [
        f"{indicator} <b>Asta interessante — {player_name}</b>",
        "",
        f"\U0001F4B6 Prezzo attuale asta: <b>{current_price_eur:.2f}€</b>",
        f"\U0001F53C Minimo per essere in testa ora: <b>{starting_bid:.2f}€</b>",
        time_line,
        "",
        separator,
        f"\U0001F3AF <b>OFFRI FINO A: {suggested_max_offer:.2f}€</b>",
        separator,
        "",
        f"\U0001F4CA Mediana di riferimento: {median_reference:.2f}€",
    ]
    if direct_sale_price is not None:
        label = "Riferimento STORICO (ultima vendita, non live)" if is_historical_reference else "Vendita diretta minima"
        msg_lines.append(f"\U0001F3F7 {label}: {direct_sale_price:.2f}€")
    if margin_estimate is not None:
        msg_lines.append(f"\U0001F4B0 Margine stimato: ~{margin_estimate:.2f}€")
    if is_historical_reference:
        msg_lines.append(
            "⚠️ <b>Nessuna vendita diretta live disponibile ora</b> -- riferimento preso "
            "dall'ultima vendita reale osservata, non da un prezzo garantito adesso. Verifica a "
            "mano prima di offrire.")
    msg_lines += ["", f"<a href='{link}'>{link_text}</a>"]

    msg_text = "\n".join(msg_lines)
    send_telegram_msg(msg_text)
    mark_notified(auction_id)
    log_decision(auction_id, player_slug, player_name, season_type,
                 "notify_historical" if is_historical_reference else "notify",
                 current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                 median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                 direct_sale_price=direct_sale_price, margin_estimate=margin_estimate)
    bump(stats, 'notify_historical' if is_historical_reference else 'notify')


def handle_auction_event(auction, eth_rate, stats):
    auction_id = auction.get('id') or ''
    if not auction_id.startswith('EnglishAuction:'):
        return

    # Deduplica: Sorare manda a volte lo stesso identico evento piu' volte sullo stesso
    # WebSocket (verificato in diagnostica, sia sul canale offerte che su questo delle
    # aste). Se id+prezzo attuale+prossima offerta minima+scadenza sono TUTTI identici a
    # un evento gia' visto in questa esecuzione, e' un doppione: lo ignoriamo. Un vero
    # rilancio cambia almeno currentPrice/minNextBid, quindi non blocchiamo mai un
    # aggiornamento prezzo reale.
    dedup_key = (auction_id, auction.get('currentPrice'), auction.get('minNextBid'), auction.get('endDate'))
    if dedup_key in stats["seen_events"]:
        return
    stats["seen_events"].add(dedup_key)

    stats["processed"] += 1
    process_auction(auction, eth_rate, stats)


def main():
    init_db()
    reset_currency_branch_stats()
    reset_season_filter_stats()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")

    # Diagnostico una tantum (vedi discover_auctions_end_date_sort): lascia vuoto normalmente,
    # valorizza AUCTION_DIAGNOSTIC_END_DATE_SORT a qualunque valore per farlo scattare.
    if os.environ.get('AUCTION_DIAGNOSTIC_END_DATE_SORT', '').strip():
        discover_auctions_end_date_sort()

    # Diagnostico una tantum (vedi discover_auctions_pagination): lascia vuoto normalmente,
    # valorizza AUCTION_DIAGNOSTIC_PAGINATION a qualunque valore per farlo scattare.
    if os.environ.get('AUCTION_DIAGNOSTIC_PAGINATION', '').strip():
        discover_auctions_pagination()

    stats = {"processed": 0, "seen_events": set()}

    # Scansione di sicurezza PRIMA di aprire il WS -- vedi nota su NUM_SAFETY_POLL_AUCTIONS.
    run_safety_poll(eth_rate, stats)

    # Seconda scansione di sicurezza, complementare -- vedi commento su get_ending_soon_auctions.
    # ON di default (AUCTION_ENDING_SOON_ENABLED='si' se non impostata): gira anche nei run del
    # cron esterno. Valorizzare la env var a vuoto/qualcosa di falsy per disattivarla di nuovo.
    if AUCTION_ENDING_SOON_ENABLED:
        run_ending_soon_poll(eth_rate, stats)

    log(f"Ascolto aste in tempo reale per {LISTEN_SECONDS} secondi...")

    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenAuctionUpdated",
        "action": "execute",
    }

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
            log(f"Sottoscrizione RIFIUTATA: {message}")
            return
        payload = message.get('message')
        if not payload:
            return
        if payload.get('errors'):
            log(f"Errore GraphQL: {payload['errors']}")
            return
        data = (payload.get('result', {}).get('data', {}) or {})
        auction = data.get('tokenAuctionWasUpdated')
        if not auction:
            return
        try:
            handle_auction_event(auction, eth_rate, stats)
        except Exception as e:
            log(f"Errore nel processare un evento asta: {e}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). "
            f"Aste processate in questa esecuzione: {stats['processed']}")
        skip_keys = [k for k in stats if k.startswith('skip_')]
        breakdown = ', '.join(f"{k}={stats[k]}" for k in sorted(skip_keys)) or "nessuno scarto"
        # FIX 17/07: notify_historical (fallback storico, vedi AUCTION_HISTORICAL_FALLBACK_
        # MARGIN_MULTIPLIER) e' un contatore separato da 'notify' per poterli distinguere nei
        # log -- ma il totale "notifiche inviate" deve sommarli entrambi, altrimenti una
        # notifica storica sparirebbe dal riepilogo pur essendo stata mandata davvero.
        total_notify = stats.get('notify', 0) + stats.get('notify_historical', 0)
        log(f"[diagnostica aste] notifiche inviate: {total_notify} "
            f"(di cui su riferimento storico: {stats.get('notify_historical', 0)}), scarti: {breakdown}")
        log(f"[diagnostica valute] branch usati in eur_price_from_amounts questa esecuzione: "
            f"{get_currency_branch_stats()}")
        log(f"[diagnostica filtro stagione] con season ok: "
            f"{get_season_filter_stats()['with_season_ok']}, fallback senza season riuscito: "
            f"{get_season_filter_stats()['fallback_no_season_ok']}, entrambi vuoti: "
            f"{get_season_filter_stats()['both_empty']}")

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
    # ping_timeout alzato 10 -> 45 (FIX v3, vedi commento gemello sopra su
    # GRAPHQL_RETRY_MAX_WAIT_SECONDS): il cap per singolo tentativo non basta contro il blocco
    # cumulativo di piu' retry 429 di fila. ping_interval alzato in proporzione.
    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()
    log("Ascolto aste terminato.")


if __name__ == "__main__":
    main()
