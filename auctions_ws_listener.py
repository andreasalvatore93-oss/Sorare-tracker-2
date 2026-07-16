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
CURRENT_SEASON_LABELS = {CURRENT_SEASON, CURRENT_SEASON_ALT}
BID_DISCOUNT = float(os.environ.get('BID_DISCOUNT', '0.25'))  # 25% fisso sul riferimento (mediana)
RECENT_PRICES_COUNT = int(os.environ.get('RECENT_PRICES_COUNT', '3'))

# Quante aste live (per lo stesso giocatore) controllare nella riverifica pre-notifica -- vedi
# verify_auction_still_live piu' sotto.
LIVE_AUCTION_RECHECK_COUNT = int(os.environ.get('LIVE_AUCTION_RECHECK_COUNT', '20'))

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

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


def graphql_query(query, variables=None):
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {"query": query, "variables": variables or {}}
    r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
    return r.json()


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
        receiverSide { amounts { eurCents wei } }
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


def fetch_all_live_offers(player_slug):
    """Scorre TUTTE le pagine di annunci live per un giocatore usando la paginazione a
    cursore confermata funzionante (before/startCursor), invece di fidarsi di un singolo
    "last: N" che il server tronca comunque a ~50 per richiesta."""
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


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        return wei_to_eur(amounts['wei'], eth_rate)
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


def get_recent_public_prices(player_slug, season_year, eth_rate, last_n=RECENT_PRICES_COUNT):
    query = """
    query RecentPrices($slug: String!, $rarity: Rarity!, $season: Int, $lastN: Int!) {
      anyPlayer(slug: $slug) {
        tokenPrices(rarity: $rarity, season: $season, last: $lastN, includePrivateSales: false) {
          nodes {
            amounts { eurCents wei }
          }
        }
      }
    }
    """
    try:
        variables = {"slug": player_slug, "rarity": "limited", "lastN": last_n}
        if season_year is not None:
            variables["season"] = season_year
        data = graphql_query(query, variables)
        if data.get('errors'):
            return []
        nodes = (((data.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}).get('nodes') or []
        prices = []
        for node in nodes:
            amounts = node.get('amounts') or {}
            if amounts.get('eurCents') is not None:
                prices.append(amounts['eurCents'] / 100)
            elif amounts.get('wei') is not None:
                p = wei_to_eur(amounts['wei'], eth_rate)
                if p is not None:
                    prices.append(p)
        return prices
    except Exception as e:
        log(f"Errore nel recuperare i prezzi recenti per {player_slug}: {e}")
        return []


# --- Riverifica live pre-notifica: query tokens.liveAuctions, la STESSA gia' usata e
# confermata funzionante dal vecchio bot a polling (auctions.py), qui filtrata per giocatore.
# NOTA: il filtro playerSlug non e' ancora stato verificato dal vivo in questa sessione --
# e' un tentativo per analogia (tokens.liveSingleSaleOffers accetta playerSlug ed e' un campo
# gemello sotto lo stesso tipo tokens, vedi nota storica su come liveSingleSaleOffers e' stato
# scoperto). Se il parametro non fosse supportato, la query torna un errore GraphQL e la
# riverifica fallisce in modo sicuro (non notifichiamo su dati non confermati) -- controllare i
# log per "[riverifica live asta] errore" per capire se va aggiustata.
LIVE_AUCTIONS_FOR_PLAYER_QUERY = """
query LiveAuctionsForPlayer($slug: String!, $n: Int!) {
  tokens {
    liveAuctions(playerSlug: $slug, last: $n) {
      nodes {
        id
        currentPrice
        minNextBid
        endDate
      }
    }
  }
}
"""


def get_live_auctions_for_player(player_slug, n):
    try:
        data = graphql_query(LIVE_AUCTIONS_FOR_PLAYER_QUERY, {"slug": player_slug, "n": n})
        if data.get('errors'):
            log(f"[riverifica live asta] errore nella query liveAuctions per {player_slug}: {data['errors']}")
            return None  # query fallita: distinto da "nessuna asta live trovata"
        nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {}).get('nodes') or []
        return nodes
    except Exception as e:
        log(f"[riverifica live asta] eccezione per {player_slug}: {e}")
        return None


def verify_auction_still_live(auction_id, player_slug, eth_rate):
    """Rilegge lo stato REALE dell'asta subito prima di notificare, invece di fidarsi
    ciecamente dei valori dell'evento WebSocket che ha innescato il controllo -- evento che
    puo' essere rimasto in coda o essere stato rielaborato con ritardo (caso Marco Reus:
    evento con currentPrice=2.17EUR e ~11h rimanenti, notificato quando l'asta era GIA' a
    10.24EUR con solo ~4h rimanenti). Ritorna una tupla (risultato, query_fallita):
    - (dati, False) se l'asta e' ancora tra le live per questo giocatore: dati e'
      (prezzo_attuale, offerta_minima_valida, data_scadenza).
    - (None, False) se la query ha funzionato ma l'asta NON e' piu' tra le live (conclusa o
      cambiata): in quel caso meglio non notificare che notificare su dati vecchi.
    - (None, True) se la query stessa e' fallita (es. parametro non supportato): in quel caso
      NON possiamo dire nulla sull'asta, quindi il chiamante ripiega sui dati originali
      dell'evento invece di scartare alla cieca (vedi STOPGAP del 16/07 in process_auction)."""
    nodes = get_live_auctions_for_player(player_slug, LIVE_AUCTION_RECHECK_COUNT)
    if nodes is None:
        return None, True
    for node in nodes:
        if node.get('id') != auction_id:
            continue
        current_price_eur = wei_to_eur(node.get('currentPrice'), eth_rate)
        if current_price_eur is None:
            return None, False
        min_next_bid_eur = wei_to_eur(node.get('minNextBid'), eth_rate)
        return (current_price_eur, min_next_bid_eur, node.get('endDate')), False
    return None, False


# --- Logica di valutazione di un'asta, identica a quella gia' validata in auctions.py:
#     l'evento WS (con anyCards incluso) ha la STESSA forma di un nodo liveAuctions, quindi
#     questa funzione e' riutilizzabile cosi' com'e'. ---
def process_auction(auction, eth_rate):
    auction_id = auction.get('id')
    current_price_eur = wei_to_eur(auction.get('currentPrice'), eth_rate)
    if auction_id is None or current_price_eur is None:
        return

    if already_notified(auction_id):
        return

    # Stampa sempre l'id, per ogni asta valutata -- cosi' e' facile prenderne uno reale dai
    # log per test/diagnostica, senza dover aprire auctions.db (es. diagnostic_live_auction_lookup.py).
    log(f"[asta] valutazione evento id={auction_id}")

    min_next_bid_raw = auction.get('minNextBid')
    min_next_bid_eur = wei_to_eur(min_next_bid_raw, eth_rate)

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
        return

    player = target_card.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    if not player_slug:
        return

    season_name = (target_card.get('sportSeason') or {}).get('name', 'unknown')
    season_type = 'in_season' if season_name in CURRENT_SEASON_LABELS else 'classic'

    season_year = parse_season_year(season_name)
    recent_prices = get_recent_public_prices(player_slug, season_year, eth_rate)
    if not recent_prices:
        log(f"{player_name}: nessun prezzo precedente trovato, salto")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_no_recent_prices",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur)
        return

    last_price = recent_prices[-1]
    if current_price_eur >= last_price:
        log(f"{player_name}: asta attuale ({current_price_eur:.2f}EUR) non sotto l'ultimo prezzo "
            f"({last_price:.2f}EUR), salto")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_not_below_last_price",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur)
        return

    # Verifica LIVE del prezzo minimo di vendita diretta -- confronto per bucket in_season/
    # classic (vedi nota nella docstring di get_live_min_direct_sale).
    direct_sale_price = get_live_min_direct_sale(player_slug, season_type, eth_rate)
    if direct_sale_price is None:
        # Fallback alla cache locale di track.py, che pero' usa solo il bucket generico
        # in_season/classic (non la stagione esatta) -- meno preciso, usato solo se la
        # query live fallisce.
        direct_sale_price = get_current_min_direct_sale(player_slug, season_type)

    median_inputs = list(recent_prices)
    if direct_sale_price is not None:
        median_inputs.append(direct_sale_price)
    median_reference = statistics.median(median_inputs)
    recommended_ceiling = median_reference * (1 - BID_DISCOUNT)

    # Riverifica live subito prima di decidere se notificare: l'evento che ha innescato
    # questo controllo potrebbe essere vecchio (vedi verify_auction_still_live/caso Marco
    # Reus). Sovrascriviamo prezzo/offerta minima/scadenza dell'evento con quelli letti ORA,
    # cosi' la decisione finale e il messaggio si basano sui numeri reali del momento, non su
    # quelli di quando l'evento e' stato emesso.
    # STOPGAP (16/07): la query di riverifica con filtro playerSlug NON e' supportata da
    # Sorare ("Field 'liveAuctions' doesn't accept argument 'playerSlug'", scoperto in
    # produzione sul caso Roman Celentano) -- finche' non troviamo il modo giusto di
    # riverificare una singola asta, un errore di query non deve piu' bloccare TUTTE le
    # notifiche (come stava succedendo): trattiamo un errore di query diversamente da
    # un'asta genuinamente non trovata tra le live. Se la query stessa fallisce, ripieghiamo
    # sui dati dell'evento originale (comportamento pre-fix, rischio dati vecchi accettato
    # temporaneamente); se invece la query FUNZIONA ma l'asta non c'e' piu' tra le live,
    # continuiamo a scartare come prima (l'asta e' davvero conclusa/cambiata).
    fresh, query_failed = verify_auction_still_live(auction_id, player_slug, eth_rate)
    if query_failed:
        log(f"{player_name}: riverifica live non disponibile (query non supportata), "
            f"procedo con i dati dell'evento originale come prima di questo fix")
    elif fresh is None:
        log(f"{player_name}: impossibile riverificare l'asta tra le live in questo momento "
            f"(evento forse vecchio o asta gia' conclusa/cambiata), non notifico per sicurezza")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_could_not_reverify_live",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        return
    else:
        fresh_current_price_eur, fresh_min_next_bid_eur, fresh_end_date = fresh
        if abs(fresh_current_price_eur - current_price_eur) > 0.01:
            log(f"{player_name}: prezzo aggiornato alla riverifica live ({current_price_eur:.2f}EUR "
                f"dell'evento -> {fresh_current_price_eur:.2f}EUR reale)")
        current_price_eur = fresh_current_price_eur
        min_next_bid_eur = fresh_min_next_bid_eur
        auction = dict(auction, endDate=fresh_end_date)

    if min_next_bid_eur is not None:
        if min_next_bid_eur > recommended_ceiling:
            log(f"{player_name}: offerta minima valida ({min_next_bid_eur:.2f}EUR) supera il tetto "
                f"consigliato ({recommended_ceiling:.2f}EUR), ignorata")
            log_decision(auction_id, player_slug, player_name, season_type, "skip_min_bid_exceeds_ceiling",
                         current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                         median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                         direct_sale_price=direct_sale_price)
            return
        starting_bid = min_next_bid_eur
    else:
        if current_price_eur >= recommended_ceiling:
            log(f"{player_name}: asta a {current_price_eur:.2f}EUR gia' oltre il tetto consigliato "
                f"({recommended_ceiling:.2f}EUR), ignorata")
            log_decision(auction_id, player_slug, player_name, season_type, "skip_price_exceeds_ceiling",
                         current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                         median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                         direct_sale_price=direct_sale_price)
            return
        starting_bid = current_price_eur

    margin_estimate = (direct_sale_price - recommended_ceiling) if direct_sale_price is not None else None

    log(f"ASTA INTERESSANTE! {player_name}: attuale {current_price_eur:.2f}EUR, "
        f"minimo per essere in testa {starting_bid:.2f}EUR, "
        f"mediana riferimento {median_reference:.2f}EUR, "
        f"tetto consigliato {recommended_ceiling:.2f}EUR, "
        f"vendita diretta minima {direct_sale_price if direct_sale_price is not None else 'n/d'}, "
        f"margine stimato {margin_estimate if margin_estimate is not None else 'n/d'}")

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
        f"\U0001F3AF <b>OFFRI FINO A: {recommended_ceiling:.2f}€</b>",
        separator,
        "",
        f"\U0001F4CA Mediana di riferimento: {median_reference:.2f}€",
    ]
    if direct_sale_price is not None:
        msg_lines.append(f"\U0001F3F7 Vendita diretta minima: {direct_sale_price:.2f}€")
    if margin_estimate is not None:
        msg_lines.append(f"\U0001F4B0 Margine stimato: ~{margin_estimate:.2f}€")
    msg_lines += ["", f"<a href='{link}'>{link_text}</a>"]

    msg_text = "\n".join(msg_lines)
    send_telegram_msg(msg_text)
    mark_notified(auction_id)
    log_decision(auction_id, player_slug, player_name, season_type, "notify",
                 current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                 median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                 direct_sale_price=direct_sale_price, margin_estimate=margin_estimate)


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
    process_auction(auction, eth_rate)


def main():
    init_db()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    log(f"Ascolto aste in tempo reale per {LISTEN_SECONDS} secondi...")

    stats = {"processed": 0, "seen_events": set()}

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
    ws.run_forever(ping_interval=30, ping_timeout=10)
    timer.cancel()
    log("Ascolto aste terminato.")


if __name__ == "__main__":
    main()
