import json
import os
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

# Per quanti secondi restare in ascolto ad ogni esecuzione.
# Deve stare abbondantemente sotto l'intervallo del cronjob esterno (5 minuti = 300s)
# per lasciare tempo a setup/commit e non sovrapporsi alla run successiva.
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '180'))

DROP_THRESHOLD = 0.05    # 5% = soglia minima per notificare
MAX_SUSPECT_DROP = 0.50  # oltre il 50% consideriamo il dato sospetto/errato

WS_URL = "wss://ws.sorare.com/cable"

SUBSCRIPTION_QUERY = """
subscription OnLimitedCardUpdated($rarities: [Rarity!], $sport: Sport) {
  anyCardWasUpdated(rarities: $rarities, sport: $sport) {
    slug
    rarityTyped
    sport
    anyPlayer { slug displayName }
    sportSeason { name }
    liveSingleSaleOffer {
      id
      endDate
      receiverSide {
        amounts { eurCents wei }
      }
    }
  }
}
"""


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


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
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "SELECT floor_price_eur FROM floors WHERE player_slug=? AND season_name=?",
        (player_slug, season_name)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


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


# --- Prezzo in EUR da un'offerta di vendita ---
def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def eur_price_from_offer(offer, eth_rate):
    if not offer:
        return None
    amounts = (offer.get('receiverSide') or {}).get('amounts') or {}
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            return None
    return None


# --- Elaborazione di un aggiornamento carta ricevuto dalla subscription ---
def handle_card_update(card, eth_rate):
    if not card:
        return
    if card.get('rarityTyped') != 'limited':
        return
    if card.get('sport') != 'FOOTBALL':
        return

    offer = card.get('liveSingleSaleOffer')
    price_eur = eur_price_from_offer(offer, eth_rate)
    if price_eur is None:
        return  # carta aggiornata ma non attualmente in vendita (o valuta non gestita)

    player = card.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    season_name = (card.get('sportSeason') or {}).get('name', 'unknown')

    if not player_slug:
        return

    floor = get_floor(player_slug, season_name)

    if floor is None:
        set_floor(player_slug, season_name, price_eur)
        log(f"{player_name} ({season_name}): inizializzazione a {price_eur:.2f}€")
        return

    if price_eur >= floor:
        return  # nessuna variazione rilevante

    drop_percent = (floor - price_eur) / floor if floor > 0 else 0

    if drop_percent > MAX_SUSPECT_DROP:
        log(f"ALERT SOSPETTO IGNORATO: {player_name} ({season_name}) sceso troppo "
            f"({drop_percent:.1%}). Dati probabilmente errati.")
        return

    if drop_percent >= DROP_THRESHOLD:
        log(f"ALERT! {player_name} ({season_name}) sceso: {floor:.2f}€ -> {price_eur:.2f}€ "
            f"({drop_percent:.1%})")
        link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
        msg_text = (
            f"🔥 <b>Occasione Sorare!</b>\n\n"
            f"Giocatore: {player_name}\n"
            f"Stagione: {season_name}\n"
            f"Calo: {drop_percent:.1%}\n"
            f"Prezzo precedente: {floor:.2f}€\n"
            f"Nuovo prezzo: {price_eur:.2f}€\n\n"
            f"<a href='{link}'>Clicca qui per vedere le offerte</a>"
        )
        send_telegram_msg(msg_text)
    else:
        log(f"{player_name} ({season_name}): piccola variazione, aggiorno il riferimento "
            f"({floor:.2f}€ -> {price_eur:.2f}€)")

    set_floor(player_slug, season_name, price_eur)


# --- WebSocket / ActionCable ---
def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {"rarities": ["limited"], "sport": "FOOTBALL"},
        "operationName": "OnLimitedCardUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0}

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

        # Errori GraphQL (es. argomento sbagliato) arrivano qui
        if payload.get('errors'):
            log(f"ERRORE GraphQL nella subscription: {payload['errors']}")
            return

        stats["received"] += 1
        card = (payload.get('result', {}).get('data', {}) or {}).get('anyCardWasUpdated')
        if card:
            handle_card_update(card, eth_rate)
            stats["processed"] += 1

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). "
            f"Eventi ricevuti: {stats['received']}, elaborati come Limited/football in vendita: {stats['processed']}")

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
    log(f"Ascolto per {LISTEN_SECONDS} secondi...")
    run_listener(eth_rate)
    log("Esecuzione terminata.")


if __name__ == "__main__":
    main()
