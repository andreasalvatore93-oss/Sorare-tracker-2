import json
import os
import re
import time
import sqlite3
import datetime
import smtplib
import threading
from email.message import EmailMessage

import requests
import websocket  # pip install websocket-client

# ---- Configurazione da variabili d'ambiente (secrets) ----
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Per quanti secondi restare in ascolto ad ogni esecuzione.
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '200'))

DROP_THRESHOLD = 0.13    # 13% = soglia minima per notificare
MAX_SUSPECT_DROP = 0.50  # oltre il 50% consideriamo il dato sospetto/errato
MIN_PRICE_EUR = float(os.environ.get('MIN_PRICE_EUR', '2.0'))  # sotto questa soglia, ignoriamo la carta

# Se il riferimento (floor) salvato nel database e' piu' vecchio di cosi', non ci fidiamo piu':
# nei "buchi" di ascolto tra un'esecuzione e l'altra il mercato puo' essersi mosso senza che il
# bot se ne accorgesse, quindi un floor troppo vecchio produrrebbe un calo% inventato.
MAX_FLOOR_AGE_HOURS = float(os.environ.get('MAX_FLOOR_AGE_HOURS', '48'))

# NOTA STORICA: qui c'era un limite fisso "ultimi N annunci" (LIVE_CHECK_LAST_N, alzato da
# 100 a 300 dopo il caso Jonas Urbig), ma un diagnostico dedicato ha rivelato che il server
# tronca comunque le risposte a un massimo di ~50 nodi per richiesta indipendentemente dal
# valore chiesto -- quindi quel numero non stava davvero risolvendo nulla oltre 50 (confermato
# sul caso Justin Bijlow). Sostituito con la paginazione vera (PAGE_SIZE/MAX_PAGES piu' sotto,
# vedi fetch_all_live_offers), che scorre TUTTE le pagine invece di sperare in un numero grande
# a sufficienza.

# Se il prezzo minimo attuale non e' almeno questa % piu' basso del SECONDO prezzo piu'
# basso attualmente in vendita, non e' un vero affare: e' solo rumore statistico dentro un
# gruppo di annunci quasi identici (es. 2.34EUR contro 2.35EUR) -- anche se rispetto al
# vecchio riferimento storico sembra un grande calo%.
MIN_MARGIN_OVER_SECOND = float(os.environ.get('MIN_MARGIN_OVER_SECOND', '0.08'))

# La stagione In Season attualmente in corso su Sorare. ATTENZIONE: leghe diverse usano formati
# diversi per lo stesso concetto di "stagione corrente" -- le leghe europee usano "2025-26" (a
# cavallo di due anni), ma la MLS (e leghe simili a calendario solare) usano solo l'anno, es.
# "2026". Confrontare solo con CURRENT_SEASON lasciava fuori la MLS: la sua carta In Season vera
# veniva scambiata per "classic" e mescolata nel calcolo del prezzo minimo insieme alle carte
# Classic vere (che invece hanno prezzi tra loro simili, indipendentemente dall'anno di stampa --
# verificato su Roman Bürki: tutte le sue Classic 2023/2024/2025 sono in un range 2.70-5.50EUR,
# mentre la sua vera carta In Season 2026 vale 12-18EUR. Il calo "sospetto" di prima era proprio
# questo: la carta In Season da 12-18EUR scambiata per classic). CURRENT_SEASON_LABELS contiene
# entrambi i formati; una carta e' "in season" se la sua stagione compare in questo insieme.
# Cambia una volta l'anno, di solito ad agosto: quando succede, aggiorna questi due valori.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')
CURRENT_SEASON_ALT = os.environ.get('CURRENT_SEASON_ALT', '2026')  # formato MLS/calendario solare
CURRENT_SEASON_LABELS = {CURRENT_SEASON, CURRENT_SEASON_ALT}

# --- Doppio controllo sugli alert "dubbi" (calo sospetto >50% o dati incompleti) ---
# Prima questi casi venivano scartati subito e basta (nessuna notifica, solo log). Ora, prima
# di scartarli definitivamente, ripetiamo UNA SOLA VOLTA la verifica live dopo una breve pausa:
# un affare vero mostra lo stesso prezzo minimo anche a una seconda interrogazione indipendente,
# mentre un dato Sorare sporco/vecchio tende a NON essere stabile (sparisce, cambia in modo
# vistoso, o l'incompletezza persiste). Se le due interrogazioni concordano (entro RECHECK_TOLERANCE)
# e la seconda non e' a sua volta incompleta, notifichiamo comunque -- altrimenti resta scartato.
RECHECK_DELAY_SECONDS = float(os.environ.get('RECHECK_DELAY_SECONDS', '3'))
RECHECK_TOLERANCE = float(os.environ.get('RECHECK_TOLERANCE', '0.05'))  # 5% di scostamento massimo ammesso

# --- Rete di sicurezza incrociata tra bucket (caso Aral Şimşir: campionato turco concluso,
# Sorare aveva gia' spostato la carta in Classic nella propria UI ("Idoneita' alle
# competizioni: Classico"), ma sportSeason.name diceva ancora "2025-26" quindi il nostro
# bucket la trattava ancora come in_season -- le uniche 2 offerte trovate li' erano residui
# vecchi, mentre tutto il mercato vero (20+ annunci) era ormai in Classic a un prezzo piu'
# basso, rendendo il calo% calcolato sul floor "in season" puro rumore. Il problema e'
# strutturale: un'etichetta di stagione statica non riflette il fatto che ogni lega chiude
# la propria stagione in un mese diverso, non tutte ad agosto come CURRENT_SEASON presume.
# Soglie tenute conservative apposta per non penalizzare giocatori con un mercato in season
# genuinamente sottile (poco popolari ma reali): serve lo squilibrio di VOLUME insieme al
# prezzo piu' basso, non basta uno dei due da solo.
THIN_BUCKET_MAX_LISTINGS = int(os.environ.get('THIN_BUCKET_MAX_LISTINGS', '2'))
SIBLING_MIN_LISTINGS = int(os.environ.get('SIBLING_MIN_LISTINGS', '5'))
SIBLING_MIN_LISTINGS_MULTIPLIER = float(os.environ.get('SIBLING_MIN_LISTINGS_MULTIPLIER', '3'))
# NON e' "il gemello deve essere molto piu' economico": se il prezzo rilevato nel bucket
# sottile fosse molto piu' basso del mercato liquido gemello resterebbe un affare raro
# genuino, da notificare comunque. Blocchiamo solo quando il prezzo rilevato NON e'
# significativamente piu' basso di quello gemello (entro questa tolleranza) -- segno che
# non sta succedendo nulla di speciale, e' solo rumore di un riferimento vecchio in un
# bucket ormai senza scambi veri (verificato sui numeri reali di Aral Şimşir: 2.70EUR
# rilevato contro 2.54EUR nel gemello, solo ~6% di differenza -- non un affare distinto).
UNIQUE_DEAL_TOLERANCE = float(os.environ.get('UNIQUE_DEAL_TOLERANCE', '0.05'))

WS_URL = "wss://ws.sorare.com/cable"

# tokenOfferWasUpdated: canale dedicato alle offerte/vendite sul mercato
# (a differenza di anyCardWasUpdated, che riguarda la carta in generale:
# livello, XP, cambi di proprietario, non necessariamente le vendite).
# Non ha filtri lato server per rarita'/sport: filtriamo noi in Python.
SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    senderSide {
      amounts { eurCents wei }
      anyCards {
        slug
        rarityTyped
        sport
        anyPlayer { slug displayName }
        sportSeason { name }
      }
    }
    receiverSide {
      amounts { eurCents wei }
      anyCards { slug }
    }
  }
}
"""

# Query REST (non subscription) usata per verificare, al momento dell'alert, quale sia
# DAVVERO il prezzo minimo attualmente in vendita per un giocatore -- scoperta per tentativi
# (introspection disabilitata da Sorare) partendo dal campo tokens.liveAuctions gia' noto:
# tokens.liveSingleSaleOffers esiste con la stessa forma. Non accetta filtri rarity/sortBy
# lato server, quindi filtriamo e ordiniamo noi in Python.
# NOTA IMPORTANTE (scoperta in diagnostica): il server tronca SEMPRE le risposte a un
# massimo di ~50 nodi per richiesta, indipendentemente dal valore chiesto in "last" (anche
# chiedendo last:300 tornavano solo 50 nodi) -- ecco perche' alzare LIVE_CHECK_LAST_N da
# 100 a 300 non risolveva davvero i casi Jonas Urbig/Justin Bijlow. Confermato pero' che la
# paginazione a cursore FUNZIONA (pageInfo.hasPreviousPage + argomento "before"): scorrendo
# le pagine precedenti si recuperano TUTTI gli annunci (verificato: Bijlow aveva 55 annunci
# totali, primi 50 + 5 mancanti recuperati con "before"). Vedi fetch_all_live_offers().
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
            slug
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
MAX_PAGES = 20  # tetto di sicurezza (fino a 1000 annunci totali) per evitare loop su volumi estremi


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


# --- Database: prezzo minimo storico per (giocatore, stagione) ---
def init_db():
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS floors (
            player_slug TEXT NOT NULL,
            season_name TEXT NOT NULL,
            floor_price_eur REAL NOT NULL,
            updated_at TEXT,
            PRIMARY KEY (player_slug, season_name)
        )
    ''')
    # Log strutturato di OGNI decisione (notifica o scarto), non solo degli alert mandati.
    # Obiettivo: poter calcolare a posteriori, guardando lo storico, quante notifiche erano
    # affari veri e quanti "SALTATO" erano invece occasioni perse -- un tasso misurabile di
    # falsi positivi/negativi, invece di doverselo ricordare a memoria dai messaggi Telegram.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS decisions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            player_slug TEXT,
            player_name TEXT,
            season_type TEXT,
            season_name TEXT,
            decision TEXT,
            floor_price REAL,
            true_min_price REAL,
            drop_percent REAL,
            second_min_price REAL,
            margin_percent REAL,
            reasons TEXT
        )
    ''')
    conn.commit()
    conn.close()


def log_decision(player_slug, player_name, season_type, season_name, decision,
                  floor_price=None, true_min_price=None, drop_percent=None,
                  second_min_price=None, margin_percent=None, reasons=None):
    """Registra una riga per ogni decisione presa (notificato o scartato, e perche').
    Query utili in futuro, es.: `SELECT decision, COUNT(*) FROM decisions_log GROUP BY decision`
    per vedere quanto viene notificato contro quanto viene scartato e con quale motivo."""
    conn = sqlite3.connect('tracker.db')
    conn.execute(
        '''INSERT INTO decisions_log
           (ts, player_slug, player_name, season_type, season_name, decision,
            floor_price, true_min_price, drop_percent, second_min_price, margin_percent, reasons)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (datetime.datetime.now().isoformat(), player_slug, player_name, season_type, season_name,
         decision, floor_price, true_min_price, drop_percent, second_min_price, margin_percent,
         ', '.join(reasons) if reasons else None)
    )
    conn.commit()
    conn.close()


def get_floor(player_slug, season_name):
    """Restituisce (prezzo, data_ultimo_aggiornamento) oppure None se non c'e' ancora un riferimento."""
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "SELECT floor_price_eur, updated_at FROM floors WHERE player_slug=? AND season_name=?",
        (player_slug, season_name)
    )
    row = cur.fetchone()
    conn.close()
    return row if row else None


def set_floor(player_slug, season_name, price):
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO floors (player_slug, season_name, floor_price_eur, updated_at) VALUES (?, ?, ?, ?)",
        (player_slug, season_name, price, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# --- Notifiche ---
def send_email(subject, body):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = NOTIFY_EMAIL
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
    except Exception as e:
        log(f"Errore invio email: {e}")


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


# --- Prezzo in EUR ---
def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            return None
    return None


# --- Verifica live del prezzo minimo REALE attualmente in vendita per un giocatore ---
# A differenza del semplice ascolto della subscription (che vede solo i CAMBIAMENTI di stato),
# questa e' un'istantanea del mercato reale in questo momento: risolve il problema per cui un
# annuncio piu' economico, aperto prima che il bot iniziasse ad ascoltare, restava invisibile.
def get_bucket_prices(player_slug, eth_rate):
    """Scorre TUTTI gli annunci live di un giocatore UNA SOLA VOLTA e li divide subito nei due
    bucket in_season/classic, invece di interrogare Sorare una volta per bucket. Restituisce
    {'in_season': (lista_prezzi_ordinata, dati_incompleti), 'classic': (..., ...)} dove
    lista_prezzi_ordinata e' una lista di (prezzo, slug_carta) crescente. Usata sia per il
    prezzo minimo del bucket richiesto (get_live_min_offer) sia per il controllo incrociato
    tra bucket (cross_bucket_looks_dead) -- nello stesso fetch, senza query aggiuntive."""
    nodes = fetch_all_live_offers(player_slug)
    raw = {'in_season': [], 'classic': []}
    incomplete_flags = {'in_season': False, 'classic': False}
    for node in nodes:
        if node.get('status') != 'opened':
            continue
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
        node_season = (match.get('sportSeason') or {}).get('name', 'unknown')
        node_season_type = 'in_season' if node_season in CURRENT_SEASON_LABELS else 'classic'
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            # Annuncio aperto e compatibile, ma Sorare non ci ha detto il prezzo: non possiamo
            # escluderlo dal conteggio, potrebbe essere il vero secondo (o primo) piu' economico.
            incomplete_flags[node_season_type] = True
            continue
        raw[node_season_type].append((price, match.get('slug')))
    result = {}
    for key in ('in_season', 'classic'):
        raw[key].sort(key=lambda p: p[0])
        result[key] = (raw[key], incomplete_flags[key])
    return result


def get_live_min_offer(player_slug, season_type, eth_rate):
    """Restituisce (prezzo_minimo, slug_carta_minima, secondo_prezzo_minimo, dati_incompleti)
    oppure None. dati_incompleti e' True se esistono annunci aperti e compatibili (stessa
    rarita'/sport/categoria in_season-o-classic) di cui pero' Sorare non restituisce il prezzo
    (eurCents e wei entrambi nulli, capitato in pratica: vedi caso Arnau Tenas) -- in quel caso
    il vero secondo prezzo potrebbe essere nascosto li' dentro e non ci si puo' fidare del margine.

    NOTA: il confronto usa il bucket 'in_season'/'classic', NON la stagione esatta. Verificato
    con dati reali (schermate del mercato di Roman Bürki) che le stampe Classic di ANNI diversi
    hanno prezzi tra loro simili (es. tutte tra 2.70 e 5.50EUR indipendentemente dall'anno di
    stampa) -- sono considerate equivalenti dai manager, cambia solo se una carta e' In Season o
    Classic. Il vero bug (caso Bürki: 2.95EUR rilevato contro 12.35EUR reali) non era la
    mescolanza tra annate Classic, ma il fatto che la sua carta In Season vera (stagione MLS
    "2026") veniva scambiata per "classic" perche' il confronto guardava solo il formato europeo
    "2025-26" -- vedi CURRENT_SEASON_LABELS."""
    try:
        buckets = get_bucket_prices(player_slug, eth_rate)
        prices, incomplete = buckets.get(season_type, ([], False))
        if not prices:
            return None
        best_price, best_card_slug = prices[0]
        second_min_price = prices[1][0] if len(prices) > 1 else None
        return best_price, best_card_slug, second_min_price, incomplete
    except Exception as e:
        log(f"[verifica live] eccezione per {player_slug}: {e}")
        return None


def cross_bucket_looks_dead(buckets, season_type, true_min_price):
    """Rete di sicurezza per il caso "stagione finita ma l'etichetta non lo sa" (vedi Aral
    Şimşir nel commento sulle costanti SIBLING_*). Se il bucket rilevato (season_type) ha
    pochissimi annunci (<= THIN_BUCKET_MAX_LISTINGS) mentre il bucket gemello ne ha molti di
    piu' (almeno SIBLING_MIN_LISTINGS, e almeno SIBLING_MIN_LISTINGS_MULTIPLIER volte tanti) a
    un prezzo sensibilmente piu' basso (almeno SIBLING_CHEAPER_THRESHOLD), e' segno che il
    bucket rilevato e' morto/residuale e il vero mercato si e' spostato altrove: in quel caso
    il calo% calcolato sul bucket rilevato e' inaffidabile. Richiede ENTRAMBE le condizioni
    (volume E prezzo) per non penalizzare giocatori con un mercato in season genuinamente
    sottile ma reale."""
    sibling_type = 'classic' if season_type == 'in_season' else 'in_season'
    own_prices, _ = buckets.get(season_type, ([], False))
    sibling_prices, _ = buckets.get(sibling_type, ([], False))
    own_count = len(own_prices)
    sibling_count = len(sibling_prices)
    if own_count > THIN_BUCKET_MAX_LISTINGS:
        return False
    if sibling_count < SIBLING_MIN_LISTINGS:
        return False
    if sibling_count < own_count * SIBLING_MIN_LISTINGS_MULTIPLIER:
        return False
    if not sibling_prices or not true_min_price or true_min_price <= 0:
        return False
    sibling_min_price = sibling_prices[0][0]
    if sibling_min_price <= 0:
        return False
    # Se il prezzo rilevato e' significativamente piu' basso del mercato gemello, resta un
    # affare raro genuino -- non lo blocchiamo. Lo blocchiamo solo se e' sostanzialmente alla
    # pari o piu' caro del gemello (entro UNIQUE_DEAL_TOLERANCE).
    not_meaningfully_cheaper = true_min_price >= sibling_min_price * (1 - UNIQUE_DEAL_TOLERANCE)
    return not_meaningfully_cheaper


def double_check_suspect_drop(player_slug, season_type, first_price, eth_rate):
    """Secondo livello di verifica per un calo segnalato come "dubbio" (sospetto >50% o dati
    incompleti), PRIMA di scartarlo definitivamente. Ripete la stessa query live usata per il
    primo controllo, dopo una breve pausa: se il prezzo minimo e' ancora li' (entro
    RECHECK_TOLERANCE) e la seconda lettura non e' a sua volta incompleta, e' molto piu'
    probabile che sia un affare reale e stabile piuttosto che un dato Sorare sporco/vecchio
    (che tipicamente sparisce o cambia in modo vistoso alla richiesta successiva).
    Ritorna True se confermato (va notificato), False se non confermato (resta scartato)."""
    time.sleep(RECHECK_DELAY_SECONDS)
    second_result = get_live_min_offer(player_slug, season_type, eth_rate)
    if second_result is None:
        return False
    second_price, _second_slug, _second_second_min, second_incomplete = second_result
    if second_incomplete:
        return False
    if not first_price or first_price <= 0:
        return False
    diff_percent = abs(second_price - first_price) / first_price
    return diff_percent <= RECHECK_TOLERANCE


# --- Elaborazione di un'offerta ricevuta dalla subscription ---
def handle_offer_update(offer, eth_rate, stats):
    if not offer:
        return

    # Vogliamo solo le vendite pubbliche "compra subito" (SingleSaleOffer), non le proposte
    # private mandate al proprietario di una carta specifica (DirectOffer) -- queste ultime
    # non compaiono mai sul mercato pubblico, quindi non ci interessano.
    offer_id = offer.get('id') or ''
    if not offer_id.startswith('SingleSaleOffer:'):
        return

    # tokenOfferWasUpdated scatta per QUALSIASI aggiornamento dell'offerta (creazione,
    # modifica prezzo, cancellazione, scadenza, vendita conclusa). Vogliamo intercettare
    # il momento in cui una carta VIENE MESSA IN VENDITA a un prezzo basso (per poterla
    # comprare noi), quindi il segnale giusto e' 'opened' (annuncio appena creato/attivo
    # a quel prezzo) -- non 'accepted' (vendita gia' conclusa tra altri manager, carta
    # non piu' disponibile) ne' 'cancelled' (annuncio ritirato, prezzo non piu' valido).
    offer_status = offer.get('status')
    stats.setdefault("status_counts", {})
    stats["status_counts"][offer_status] = stats["status_counts"].get(offer_status, 0) + 1

    # Sorare a volte manda lo stesso evento due (o piu') volte sullo stesso WebSocket
    # (verificato empiricamente). Se abbiamo gia' visto esattamente questo stesso
    # (offer_id, status) in questa esecuzione, e' un doppione: lo ignoriamo.
    stats.setdefault("seen_offer_status", set())
    dedup_key = (offer_id, offer_status)
    if dedup_key in stats["seen_offer_status"]:
        return
    stats["seen_offer_status"].add(dedup_key)

    if offer_status != 'opened':
        return

    sender_side = offer.get('senderSide') or {}
    receiver_side = offer.get('receiverSide') or {}

    # Vogliamo solo offerte "vendita diretta a soldi":
    # dal lato di chi vende ci sono le carte, dal lato ricevente NON ci sono carte
    # (altrimenti e' uno scambio carta-per-carta, che non ci interessa qui).
    if receiver_side.get('anyCards'):
        return

    price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
    if price_eur is None:
        return

    for card in (sender_side.get('anyCards') or []):
        if card.get('rarityTyped') != 'limited':
            continue
        if card.get('sport') != 'FOOTBALL':
            continue

        player = card.get('anyPlayer') or {}
        player_slug = player.get('slug')
        player_name = player.get('displayName', player_slug)
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        card_slug = card.get('slug')
        if not player_slug:
            continue

        if price_eur < MIN_PRICE_EUR:
            continue  # scarto veloce sul prezzo dell'evento, solo per non fare la verifica live inutilmente:
                      # il controllo vero (sul prezzo REALE verificato) e' piu' sotto, dopo get_live_min_offer

        season_type = 'in_season' if season_name in CURRENT_SEASON_LABELS else 'classic'

        stats["processed"] += 1

        # Verifica live: qual e' DAVVERO il prezzo minimo attualmente in vendita per questo
        # giocatore, nella stessa categoria in_season/classic (vedi nota nella docstring di
        # get_live_min_offer)? Se la query fallisce per qualsiasi motivo, ripieghiamo sul
        # prezzo di questo singolo evento (comportamento precedente).
        try:
            buckets = get_bucket_prices(player_slug, eth_rate)
        except Exception as e:
            log(f"[verifica live] eccezione per {player_slug}: {e}")
            buckets = None

        own_prices = buckets.get(season_type, ([], False))[0] if buckets else []
        if own_prices:
            true_min_price, true_min_card_slug = own_prices[0]
            second_min_price = own_prices[1][0] if len(own_prices) > 1 else None
            data_incomplete = buckets[season_type][1]
        else:
            true_min_price, true_min_card_slug, second_min_price, data_incomplete = price_eur, card_slug, None, False

        # Il controllo sopra (price_eur < MIN_PRICE_EUR) filtra solo il prezzo dell'EVENTO
        # che ha innescato il controllo, non il vero prezzo minimo verificato live -- per
        # questo motivo carte a 0.80EUR passavano comunque (caso Lovro Majer: l'evento
        # scatenante era su un annuncio piu' caro, ma la verifica live trovava un prezzo
        # piu' basso altrove, che finiva nell'alert bypassando il filtro). Controlliamo
        # anche il prezzo REALMENTE segnalato, non solo quello dell'evento.
        if true_min_price < MIN_PRICE_EUR:
            continue

        # Il riferimento (floor) e' tracciato per bucket in_season/classic (non per stagione
        # esatta): verificato con dati reali che le stampe Classic di anni diversi hanno prezzi
        # tra loro simili -- per i manager sono equivalenti, cambia solo se e' In Season o no.
        floor_row = get_floor(player_slug, season_type)

        if floor_row is None:
            set_floor(player_slug, season_type, true_min_price)
            log(f"{player_name} ({season_type}, {season_name}): inizializzazione a {true_min_price:.2f}EUR")
            log_decision(player_slug, player_name, season_type, season_name, "init",
                         true_min_price=true_min_price)
            continue

        floor, floor_updated_at = floor_row

        # Riferimento troppo vecchio: nei "buchi" di ascolto tra un'esecuzione e l'altra
        # il mercato puo' essersi mosso senza che il bot lo vedesse. Meglio riallinearsi
        # in silenzio piuttosto che mostrare un calo% calcolato su un dato ormai stantio.
        # Se non abbiamo affatto un timestamp (righe create da versioni precedenti del
        # bot, prima che questa colonna esistesse sempre), l'eta' e' sconosciuta: meglio
        # trattarla come "troppo vecchia" (riallineo in silenzio) piuttosto che rischiare
        # di confrontare il prezzo vero con un riferimento di eta' ignota e segnalarlo
        # come falso "sospetto" -- e' proprio quello che stava succedendo.
        if not floor_updated_at:
            stale = True
        else:
            try:
                age_hours = (
                    datetime.datetime.now() - datetime.datetime.fromisoformat(floor_updated_at)
                ).total_seconds() / 3600
                stale = age_hours > MAX_FLOOR_AGE_HOURS
            except ValueError:
                stale = True

        if stale:
            log(f"{player_name} ({season_type}, {season_name}): riferimento salvato troppo vecchio "
                f"(ultimo aggiornamento {floor_updated_at}), lo riallineo senza notificare "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR)")
            log_decision(player_slug, player_name, season_type, season_name, "stale_realign",
                         floor_price=floor, true_min_price=true_min_price)
            set_floor(player_slug, season_type, true_min_price)
            continue

        if true_min_price >= floor:
            continue

        drop_percent = (floor - true_min_price) / floor if floor > 0 else 0

        # Un calo enorme (>50%) e' spesso un dato Sorare errato/vecchio piuttosto che un
        # affare reale. Con il riconoscimento corretto in_season/classic (comprensivo del
        # formato MLS, vedi CURRENT_SEASON_LABELS) il caso Bürki dovrebbe gia' essere
        # risolto alla radice -- ma teniamo comunque questo controllo come rete di sicurezza.
        suspect_drop = drop_percent > MAX_SUSPECT_DROP

        # Il calo% rispetto allo storico puo' sembrare grande anche quando il prezzo minimo
        # e' praticamente identico al secondo annuncio piu' economico attuale (es. 2.34 contro
        # 2.35EUR): in quel caso non e' un vero affare, e' solo il primo di un gruppo di
        # annunci quasi uguali. Richiediamo un margine minimo REALE sul secondo prezzo attuale.
        margin_percent = None
        if second_min_price is not None and second_min_price > 0:
            margin_percent = (second_min_price - true_min_price) / second_min_price
            if margin_percent < MIN_MARGIN_OVER_SECOND:
                log(f"{player_name} ({season_type}, {season_name}): prezzo minimo ({true_min_price:.2f}EUR) "
                    f"troppo vicino al secondo annuncio attuale ({second_min_price:.2f}EUR, "
                    f"margine {margin_percent:.1%}), non e' un affare distinto, salto la notifica")
                log_decision(player_slug, player_name, season_type, season_name, "skip_margin_too_close",
                             floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent)
                set_floor(player_slug, season_type, true_min_price)
                continue

        # Rete di sicurezza: il bucket rilevato sembra morto/residuale (stagione di quella lega
        # gia' finita nella pratica, anche se l'etichetta sportSeason.name non lo riflette
        # ancora) mentre il mercato vero si e' spostato nel bucket gemello a un prezzo piu'
        # basso? Vedi cross_bucket_looks_dead per i dettagli (caso Aral Şimşir). A differenza dei
        # cali "dubbi" qui sotto, NON ha senso rifare un doppio controllo sullo stesso bucket:
        # il prezzo li' e' stabile da giorni, il problema e' che quel bucket non e' piu' il
        # mercato reale, non un dato instabile -- quindi si scarta subito, senza secondo tentativo.
        if drop_percent >= DROP_THRESHOLD and buckets is not None:
            if cross_bucket_looks_dead(buckets, season_type, true_min_price):
                sibling_type = 'classic' if season_type == 'in_season' else 'in_season'
                sibling_prices = buckets[sibling_type][0]
                log(f"SALTATO (bucket {season_type} sembra morto/residuale: {len(buckets[season_type][0])} "
                    f"annunci contro {len(sibling_prices)} nel bucket {sibling_type}, li' a partire da "
                    f"{sibling_prices[0][0]:.2f}EUR) {player_name} ({season_type}, {season_name}) -- "
                    f"non notifico, il riferimento e' probabilmente su un mercato non piu' reale")
                log_decision(player_slug, player_name, season_type, season_name, "skip_cross_bucket_dead",
                             floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent,
                             reasons=[f"bucket gemello {sibling_type} ha {len(sibling_prices)} annunci da "
                                      f"{sibling_prices[0][0]:.2f}EUR, molto piu' attivo ed economico"])
                set_floor(player_slug, season_type, true_min_price)
                continue

        # Scelta esplicita dell'utente: meglio rischiare di perdere qualche affare vero che
        # mandare notifiche su cui c'e' un dubbio ragionevole che siano fasulle. Percio' un calo
        # sospetto (>50%, possibile dato Sorare errato/vecchio) o dati incompleti (prezzo
        # illeggibile su alcuni annunci compatibili) non vengono notificati alla prima lettura.
        # PRIMA di scartarli pero' proviamo un secondo livello di verifica (double_check_suspect_drop):
        # se una seconda interrogazione indipendente, dopo una breve pausa, conferma lo stesso
        # prezzo minimo (e non e' a sua volta incompleta), e' molto piu' probabile che sia un
        # affare reale e stabile piuttosto che un dato sporco -- in quel caso notifichiamo
        # comunque. Se non si conferma, resta scartato come prima. Il riferimento viene sempre
        # aggiornato, notificato o no, per continuare a tracciare correttamente il prezzo.
        is_dubbio = suspect_drop or data_incomplete
        recheck_confirmed = False
        reasons_log = []
        if drop_percent >= DROP_THRESHOLD and is_dubbio:
            if suspect_drop:
                reasons_log.append("calo molto ampio (>50%)")
            if data_incomplete:
                reasons_log.append("dati incompleti (prezzo illeggibile su alcuni annunci compatibili)")
            log(f"DUBBIO ({', '.join(reasons_log)}) {player_name} ({season_type}, {season_name}) "
                f"sceso: {floor:.2f}EUR -> {true_min_price:.2f}EUR ({drop_percent:.1%}) "
                f"-- eseguo un secondo controllo prima di scartare")
            recheck_confirmed = double_check_suspect_drop(player_slug, season_type, true_min_price, eth_rate)
            if recheck_confirmed:
                log(f"CONFERMATO al secondo controllo: {player_name} resta a {true_min_price:.2f}EUR, procedo con la notifica")
            else:
                log(f"SALTATO (dubbio non confermato al secondo controllo: {', '.join(reasons_log)}) "
                    f"{player_name} ({season_type}, {season_name}) -- non notifico per evitare falsi allarmi")

        should_notify = drop_percent >= DROP_THRESHOLD and (not is_dubbio or recheck_confirmed)

        if should_notify:
            decision = "notify_after_recheck" if is_dubbio else "notify"
            log(f"ALERT! {player_name} ({season_type}, {season_name}) sceso: "
                f"{floor:.2f}EUR -> {true_min_price:.2f}EUR ({drop_percent:.1%}) [prezzo minimo verificato live]")
            log_decision(player_slug, player_name, season_type, season_name, decision,
                         floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                         second_min_price=second_min_price, margin_percent=margin_percent,
                         reasons=reasons_log or None)

            # true_min_card_slug e' la carta REALMENTE piu' economica in questo momento
            # (verificata live), non necessariamente quella di questo specifico evento.
            base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
            if true_min_card_slug:
                link = f"{base_link}?card={true_min_card_slug}"
            else:
                sort_param = "s=Cards+On+Sale+Lowest+Price"
                link = f"{base_link}?{sort_param}"

            msg_text = (
                f"\U0001F525 <b>Occasione Sorare!</b>\n\n"
                f"Giocatore: {player_name}\n"
                f"Categoria: {'In Season' if season_type == 'in_season' else 'Classic (stagione passata)'}\n"
                f"Stagione carta: {season_name}\n"
                f"Calo: {drop_percent:.1%}\n"
                f"Nuovo prezzo: {true_min_price:.2f}EUR\n"
                + (f"Secondo prezzo attuale: {second_min_price:.2f}EUR (margine {margin_percent:.1%})\n"
                   if second_min_price is not None else "")
                + (f"⚠️ Confermato al secondo controllo dopo un calo dubbio iniziale ({', '.join(reasons_log)})\n"
                   if is_dubbio else "")
                + f"\n<a href='{link}'>Clicca qui per vedere le offerte</a>"
            )
            send_telegram_msg(msg_text)
        elif drop_percent >= DROP_THRESHOLD:
            log_decision(player_slug, player_name, season_type, season_name, "skip_dubbio_unconfirmed",
                         floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                         second_min_price=second_min_price, margin_percent=margin_percent,
                         reasons=reasons_log or None)
        else:
            log(f"{player_name} ({season_type}, {season_name}): piccola variazione, aggiorno il riferimento "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR)")
            log_decision(player_slug, player_name, season_type, season_name, "update_small_variation",
                         floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                         second_min_price=second_min_price, margin_percent=margin_percent)

        set_floor(player_slug, season_type, true_min_price)


# --- WebSocket / ActionCable ---
def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "status_counts": {}}

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
        if offer:
            handle_offer_update(offer, eth_rate, stats)

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). "
            f"Eventi ricevuti: {stats['received']}, carte Limited/football elaborate: {stats['processed']}")
        log(f"[diagnostica tracker] distribuzione status offerte osservate: {stats['status_counts']}")

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


def main():
    init_db()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    log(f"Stagione In Season corrente: {CURRENT_SEASON}")
    log(f"Ascolto per {LISTEN_SECONDS} secondi...")
    run_listener(eth_rate)
    log("Esecuzione terminata.")


if __name__ == "__main__":
    main()
