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
MIN_PRICE_EUR = float(os.environ.get('MIN_PRICE_EUR', '3.0'))  # sotto questa soglia, ignoriamo la carta

# Se il riferimento (floor) salvato nel database e' piu' vecchio di cosi', non ci fidiamo piu':
# nei "buchi" di ascolto tra un'esecuzione e l'altra il mercato puo' essersi mosso senza che il
# bot se ne accorgesse, quindi un floor troppo vecchio produrrebbe un calo% inventato.
MAX_FLOOR_AGE_HOURS = float(os.environ.get('MAX_FLOOR_AGE_HOURS', '48'))

# Quanti annunci recenti interrogare per giocatore quando verifichiamo il prezzo minimo
# live (vedi get_live_min_offer). Abbastanza alto da coprire praticamente tutti i giocatori.
LIVE_CHECK_LAST_N = int(os.environ.get('LIVE_CHECK_LAST_N', '100'))

# Se il prezzo minimo attuale non e' almeno questa % piu' basso del SECONDO prezzo piu'
# basso attualmente in vendita, non e' un vero affare: e' solo rumore statistico dentro un
# gruppo di annunci quasi identici (es. 2.34EUR contro 2.35EUR) -- anche se rispetto al
# vecchio riferimento storico sembra un grande calo%.
MIN_MARGIN_OVER_SECOND = float(os.environ.get('MIN_MARGIN_OVER_SECOND', '0.08'))

# La stagione In Season attualmente in corso su Sorare (formato uguale a quello sulle carte, es. "2025-26").
# Cambia una volta l'anno, di solito ad agosto: quando succede, aggiorna solo questa riga.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')

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
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n) {
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
def get_live_min_offer(player_slug, season_type, eth_rate):
    """Restituisce (prezzo_minimo, slug_carta_minima, secondo_prezzo_minimo, dati_incompleti)
    oppure None. dati_incompleti e' True se esistono annunci aperti e compatibili (stessa
    rarita'/sport/stagione) di cui pero' Sorare non restituisce il prezzo (eurCents e wei
    entrambi nulli, capitato in pratica: vedi caso Arnau Tenas) -- in quel caso il vero
    secondo prezzo potrebbe essere nascosto li' dentro e non ci si puo' fidare del margine."""
    try:
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": LIVE_CHECK_LAST_N})
        if data.get('errors'):
            log(f"[verifica live] errore per {player_slug}: {data['errors']}")
            return None
        nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {}).get('nodes') or []
        prices = []
        incomplete = False
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
                node_season = (c.get('sportSeason') or {}).get('name', 'unknown')
                node_season_type = 'in_season' if node_season == CURRENT_SEASON else 'classic'
                if node_season_type != season_type:
                    continue
                match = c
                break
            if not match:
                continue
            price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
            if price is None:
                # Annuncio aperto e compatibile, ma Sorare non ci ha detto il prezzo: non possiamo
                # escluderlo dal conteggio, potrebbe essere il vero secondo (o primo) piu' economico.
                incomplete = True
                continue
            prices.append((price, match.get('slug')))
        if not prices:
            return None
        prices.sort(key=lambda p: p[0])
        best_price, best_card_slug = prices[0]
        second_min_price = prices[1][0] if len(prices) > 1 else None
        return best_price, best_card_slug, second_min_price, incomplete
    except Exception as e:
        log(f"[verifica live] eccezione per {player_slug}: {e}")
        return None


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
            continue  # carta troppo economica: margine di trading troppo basso, non ci interessa

        season_type = 'in_season' if season_name == CURRENT_SEASON else 'classic'

        stats["processed"] += 1

        # Verifica live: qual e' DAVVERO il prezzo minimo attualmente in vendita per questo
        # giocatore/stagione? Se la query fallisce per qualsiasi motivo, ripieghiamo sul
        # prezzo di questo singolo evento (comportamento precedente).
        live_result = get_live_min_offer(player_slug, season_type, eth_rate)
        if live_result is not None:
            true_min_price, true_min_card_slug, second_min_price, data_incomplete = live_result
        else:
            true_min_price, true_min_card_slug, second_min_price, data_incomplete = price_eur, card_slug, None, False

        floor_row = get_floor(player_slug, season_type)

        if floor_row is None:
            set_floor(player_slug, season_type, true_min_price)
            log(f"{player_name} ({season_type}, {season_name}): inizializzazione a {true_min_price:.2f}EUR")
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
            log(f"{player_name} ({season_type}): riferimento salvato troppo vecchio "
                f"(ultimo aggiornamento {floor_updated_at}), lo riallineo senza notificare "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR)")
            set_floor(player_slug, season_type, true_min_price)
            continue

        if true_min_price >= floor:
            continue

        drop_percent = (floor - true_min_price) / floor if floor > 0 else 0

        if drop_percent > MAX_SUSPECT_DROP:
            log(f"ALERT SOSPETTO IGNORATO: {player_name} ({season_type}) sceso troppo "
                f"({drop_percent:.1%}). Dati probabilmente errati.")
            # Anche se non notifichiamo, il prezzo vero verificato live e' comunque
            # affidabile (viene dalla query GraphQL, non dal solo evento WS): riallineiamo
            # il floor a questo valore cosi' il riferimento si autocorregge da solo, invece
            # di restare bloccato su un valore vecchio/contaminato che farebbe scattare
            # questo stesso "sospetto" per sempre ad ogni evento successivo.
            set_floor(player_slug, season_type, true_min_price)
            continue

        # A volte Sorare restituisce annunci aperti e compatibili ma senza prezzo leggibile
        # (eurCents e wei entrambi nulli -- capitato in pratica, caso Arnau Tenas). In quel
        # caso non possiamo fidarci del margine calcolato: il vero secondo prezzo potrebbe
        # essere nascosto proprio li'. Meglio non notificare che rischiare un falso allarme.
        if data_incomplete:
            log(f"{player_name} ({season_type}): alcuni annunci compatibili hanno prezzo non "
                f"leggibile da Sorare, non mi fido del margine calcolato, salto la notifica")
            set_floor(player_slug, season_type, true_min_price)
            continue

        # Il calo% rispetto allo storico puo' sembrare grande anche quando il prezzo minimo
        # e' praticamente identico al secondo annuncio piu' economico attuale (es. 2.34 contro
        # 2.35EUR): in quel caso non e' un vero affare, e' solo il primo di un gruppo di
        # annunci quasi uguali. Richiediamo un margine minimo REALE sul secondo prezzo attuale.
        margin_percent = None
        if second_min_price is not None and second_min_price > 0:
            margin_percent = (second_min_price - true_min_price) / second_min_price
            if margin_percent < MIN_MARGIN_OVER_SECOND:
                log(f"{player_name} ({season_type}): prezzo minimo ({true_min_price:.2f}EUR) troppo vicino "
                    f"al secondo annuncio attuale ({second_min_price:.2f}EUR, margine {margin_percent:.1%}), "
                    f"non e' un affare distinto, salto la notifica")
                set_floor(player_slug, season_type, true_min_price)
                continue

        if drop_percent >= DROP_THRESHOLD:
            log(f"ALERT! {player_name} ({season_type}, {season_name}) sceso: {floor:.2f}EUR -> {true_min_price:.2f}EUR "
                f"({drop_percent:.1%}) [prezzo minimo verificato live]")

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
                f"Prezzo precedente: {floor:.2f}EUR\n"
                f"Nuovo prezzo: {true_min_price:.2f}EUR\n"
                + (f"Secondo prezzo attuale: {second_min_price:.2f}EUR (margine {margin_percent:.1%})\n"
                   if second_min_price is not None else "")
                + f"\n<a href='{link}'>Clicca qui per vedere le offerte</a>"
            )
            send_telegram_msg(msg_text)
        else:
            log(f"{player_name} ({season_type}, {season_name}): piccola variazione, aggiorno il riferimento "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR)")

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
