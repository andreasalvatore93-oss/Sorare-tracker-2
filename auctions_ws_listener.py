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
MIN_MARGIN_EUR = float(os.environ.get('MIN_MARGIN_EUR', '1.5'))

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
def process_auction(auction, eth_rate):
    auction_id = auction.get('id')
    current_price_eur = wei_to_eur(auction.get('currentPrice'), eth_rate)
    if auction_id is None or current_price_eur is None:
        return

    if already_notified(auction_id):
        return

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

    # Stampa sempre id asta E slug carta, per ogni asta valutata -- cosi' e' facile prenderne
    # una reale dai log per test/diagnostica, senza dover aprire auctions.db (es.
    # diagnostic_live_auction_lookup.py).
    log(f"[asta] valutazione evento id={auction_id} card_slug={target_card.get('slug')}")

    player = target_card.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    if not player_slug:
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
        return
    if fresh is None:
        log(f"{player_name}: l'asta non esiste piu' alla riverifica live "
            f"(conclusa/rimossa nel frattempo), non notifico")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_could_not_reverify_live",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
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
        return

    fresh_current_price_eur = wei_to_eur(fresh.get('currentPrice'), eth_rate)
    fresh_min_next_bid_eur = wei_to_eur(fresh.get('minNextBid'), eth_rate)
    if fresh_current_price_eur is None:
        log(f"{player_name}: dati di prezzo mancanti alla riverifica live, non notifico per sicurezza")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_recheck_missing_price",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price)
        return
    if abs(fresh_current_price_eur - current_price_eur) > 0.01:
        log(f"{player_name}: prezzo aggiornato alla riverifica live ({current_price_eur:.2f}EUR "
            f"dell'evento -> {fresh_current_price_eur:.2f}EUR reale)")
    current_price_eur = fresh_current_price_eur
    min_next_bid_eur = fresh_min_next_bid_eur
    auction = dict(auction, endDate=fresh.get('endDate'))

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

    if margin_estimate is None or margin_estimate < MIN_MARGIN_EUR:
        log(f"{player_name}: margine stimato "
            f"{margin_estimate if margin_estimate is not None else 'n/d'} sotto la soglia minima "
            f"({MIN_MARGIN_EUR:.2f}EUR), non notifico")
        log_decision(auction_id, player_slug, player_name, season_type, "skip_margin_too_low",
                     current_price=current_price_eur, min_next_bid=min_next_bid_eur,
                     median_reference=median_reference, recommended_ceiling=recommended_ceiling,
                     direct_sale_price=direct_sale_price, margin_estimate=margin_estimate)
        return

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

    stats = {"processed": 0, "seen_events": set()}

    # Scansione di sicurezza PRIMA di aprire il WS -- vedi nota su NUM_SAFETY_POLL_AUCTIONS.
    run_safety_poll(eth_rate, stats)

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
