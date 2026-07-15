import os
import json
import sqlite3
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('AUCTION_TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('AUCTION_TELEGRAM_CHAT_ID', '').strip()

# Stessa stagione In Season usata dal bot principale (track.py) -- tenerle allineate.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')

BID_DISCOUNT = float(os.environ.get('BID_DISCOUNT', '0.10'))  # 10% fisso sul riferimento piu' basso
NUM_AUCTIONS = int(os.environ.get('NUM_AUCTIONS', '10'))

GRAPHQL_URL = 'https://api.sorare.com/graphql'


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


# --- Database (solo per non notificare due volte la stessa asta) ---
def init_db():
    conn = sqlite3.connect('auctions.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notified_auctions (
            auction_id TEXT PRIMARY KEY,
            notified_at TEXT
        )
    ''')
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


# --- Prezzo minimo attualmente in vendita diretta, letto dal database del bot principale ---
def get_current_min_direct_sale(player_slug):
    try:
        conn = sqlite3.connect('tracker.db')
        row = conn.execute(
            "SELECT floor_price_eur FROM floors WHERE player_slug=? AND season_name='in_season'",
            (player_slug,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log(f"Impossibile leggere tracker.db ({e}), procedo senza riferimento di vendita diretta")
        return None


# --- Ultima asta conclusa per un giocatore (pezzo NON ancora verificato: log dettagliato apposta) ---
def get_last_concluded_auction_price(player_slug, eth_rate):
    query = """
    query LastAuctionPrice($slug: String!, $rarity: Rarity!) {
      anyPlayer(slug: $slug) {
        tokenPrices(rarity: $rarity, last: 5) {
          nodes {
            __typename
            amounts { eurCents wei }
          }
        }
      }
    }
    """
    try:
        data = graphql_query(query, {"slug": player_slug, "rarity": "limited"})
        log(f"[diagnostica aste] tokenPrices per {player_slug}: {json.dumps(data)[:500]}")
        if data.get('errors'):
            return None
        nodes = (((data.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}).get('nodes') or []
        if not nodes:
            return None
        latest = nodes[-1]
        amounts = latest.get('amounts') or {}
        if amounts.get('eurCents') is not None:
            return amounts['eurCents'] / 100
        if amounts.get('wei') is not None:
            return wei_to_eur(amounts['wei'], eth_rate)
        return None
    except Exception as e:
        log(f"Errore nel recuperare l'ultima asta per {player_slug}: {e}")
        return None


# --- Aste attualmente live (pezzo documentato ufficialmente da Sorare) ---
def get_live_auctions(n):
    query = """
    query ListLiveAuctions($n: Int!) {
      tokens {
        liveAuctions(last: $n) {
          nodes {
            id
            currentPrice
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
    try:
        data = graphql_query(query, {"n": n})
        log(f"[diagnostica aste] liveAuctions risposta grezza: {json.dumps(data)[:800]}")
        if data.get('errors'):
            log(f"Errore nella query liveAuctions: {data['errors']}")
            return []
        nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {}).get('nodes') or []
        return nodes
    except Exception as e:
        log(f"Errore nel recuperare le aste live: {e}")
        return []


def process_auction(auction, eth_rate):
    auction_id = auction.get('id')
    current_price_eur = wei_to_eur(auction.get('currentPrice'), eth_rate)
    if auction_id is None or current_price_eur is None:
        return

    if already_notified(auction_id):
        return

    cards = auction.get('anyCards') or []
    target_card = None
    for c in cards:
        if c.get('rarityTyped') != 'limited':
            continue
        if c.get('sport') != 'FOOTBALL':
            continue
        # Le carte Classic non vanno mai in asta su Sorare: una Limited in asta
        # e' quindi sempre In Season, indipendentemente da come Sorare etichetta
        # quella specifica stampa (non sempre nel formato "2025-26").
        target_card = c
        break

    if not target_card:
        return

    player = target_card.get('anyPlayer') or {}
    player_slug = player.get('slug')
    player_name = player.get('displayName', player_slug)
    if not player_slug:
        return

    last_auction_price = get_last_concluded_auction_price(player_slug, eth_rate)
    if last_auction_price is None:
        log(f"{player_name}: nessun prezzo d'asta precedente trovato, salto")
        return

    if current_price_eur >= last_auction_price:
        log(f"{player_name}: asta attuale ({current_price_eur:.2f}EUR) non sotto la precedente "
            f"({last_auction_price:.2f}EUR), salto")
        return

    direct_sale_price = get_current_min_direct_sale(player_slug)
    reference = min(last_auction_price, direct_sale_price) if direct_sale_price is not None else last_auction_price
    recommended_bid = reference * (1 - BID_DISCOUNT)

    if current_price_eur >= recommended_bid:
        log(f"{player_name}: asta a {current_price_eur:.2f}EUR gia' oltre l'offerta consigliata "
            f"({recommended_bid:.2f}EUR), ignorata")
        return

    log(f"ASTA INTERESSANTE! {player_name}: attuale {current_price_eur:.2f}EUR, "
        f"asta precedente {last_auction_price:.2f}EUR, "
        f"vendita diretta minima {direct_sale_price if direct_sale_price is not None else 'n/d'}, "
        f"offerta consigliata {recommended_bid:.2f}EUR")

    card_slug = target_card.get('slug')
    if card_slug:
        link = f"https://sorare.com/it/football/market/shop/auctions?rarity=limited&card={card_slug}"
        link_text = "Vai direttamente all'asta"
    else:
        link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
        link_text = "Vai alla pagina del giocatore (apri tu la scheda Aste)"
    msg_text = (
        f"\U0001F528 <b>Asta interessante su Sorare!</b>\n\n"
        f"Giocatore: {player_name}\n"
        f"Prezzo attuale asta: {current_price_eur:.2f}EUR\n"
        f"Ultima asta conclusa: {last_auction_price:.2f}EUR\n"
        + (f"Vendita diretta minima: {direct_sale_price:.2f}EUR\n" if direct_sale_price is not None else "")
        + f"Offerta consigliata: fino a {recommended_bid:.2f}EUR\n\n"
        f"<a href='{link}'>{link_text}</a>"
    )
    send_telegram_msg(msg_text)
    mark_notified(auction_id)


def main():
    init_db()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    auctions = get_live_auctions(NUM_AUCTIONS)
    log(f"Trovate {len(auctions)} aste live da esaminare")
    for auction in auctions:
        process_auction(auction, eth_rate)
    log("Controllo aste terminato.")


if __name__ == "__main__":
    main()
