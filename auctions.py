import os
import re
import json
import sqlite3
import statistics
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('AUCTION_TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('AUCTION_TELEGRAM_CHAT_ID', '').strip()

# Stessa stagione In Season usata dal bot principale (track.py) -- tenerle allineate.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')

BID_DISCOUNT = float(os.environ.get('BID_DISCOUNT', '0.25'))  # 25% fisso sul riferimento (mediana)
NUM_AUCTIONS = int(os.environ.get('NUM_AUCTIONS', '10'))
RECENT_PRICES_COUNT = int(os.environ.get('RECENT_PRICES_COUNT', '3'))  # quanti prezzi pubblici recenti usare per la mediana

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


def parse_season_year(season_name):
    """Estrae il primo anno a 4 cifre da un'etichetta di stagione (es. '2026' o '2025-26' -> 2025/2026)."""
    if not season_name:
        return None
    match = re.search(r'\d{4}', season_name)
    return int(match.group()) if match else None


# --- Ultimi N prezzi pubblici (Asta o Acquisto istantaneo) per un giocatore, stessa edizione della
#     carta in asta, dal piu' vecchio al piu' recente. Le offerte private sono escluse esplicitamente
#     con includePrivateSales: false; gli Scambi sono gia' esclusi dal campo tokenPrices per
#     definizione. Nota: __typename e' sempre "TokenPrice" (verificato), quindi non possiamo
#     distinguere lato server Asta da Acquisto istantaneo -- per carte appena droppate in asta
#     (come questi English auction) di solito la stragrande maggioranza delle transazioni recenti
#     sono comunque aste. ---
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
        log(f"[diagnostica aste] recentPrices per {player_slug} (season={season_year}): {json.dumps(data)[:500]}")
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
        return prices  # ordine: dal piu' vecchio al piu' recente
    except Exception as e:
        log(f"Errore nel recuperare i prezzi recenti per {player_slug}: {e}")
        return []


# --- Aste attualmente live (pezzo documentato ufficialmente da Sorare) ---
# minNextBid: l'offerta minima valida calcolata da Sorare stesso, rispetta gli scaglioni
# del sistema (non un semplice +10%, quindi non lo ricalcoliamo noi: lo leggiamo diretto).
def get_live_auctions(n):
    query = """
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

    min_next_bid_raw = auction.get('minNextBid')
    min_next_bid_eur = wei_to_eur(min_next_bid_raw, eth_rate)
    log(f"[diagnostica aste] minNextBid grezzo: {min_next_bid_raw} -> {min_next_bid_eur}")

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

    season_year = parse_season_year((target_card.get('sportSeason') or {}).get('name'))
    recent_prices = get_recent_public_prices(player_slug, season_year, eth_rate)
    if not recent_prices:
        log(f"{player_name}: nessun prezzo precedente trovato, salto")
        return

    last_price = recent_prices[-1]
    if current_price_eur >= last_price:
        log(f"{player_name}: asta attuale ({current_price_eur:.2f}EUR) non sotto l'ultimo prezzo "
            f"({last_price:.2f}EUR), salto")
        return

    direct_sale_price = get_current_min_direct_sale(player_slug)

    # Mediana tra gli ultimi prezzi pubblici osservati e il prezzo minimo di vendita diretta (se noto).
    # E' un riferimento piu' robusto del solo ultimo prezzo: non si fa influenzare da un singolo
    # outlier (es. una vendita anomala) e riflette meglio "quanto vale davvero" la carta adesso.
    median_inputs = list(recent_prices)
    if direct_sale_price is not None:
        median_inputs.append(direct_sale_price)
    median_reference = statistics.median(median_inputs)
    recommended_ceiling = median_reference * (1 - BID_DISCOUNT)

    if min_next_bid_eur is not None:
        if min_next_bid_eur > recommended_ceiling:
            log(f"{player_name}: offerta minima valida ({min_next_bid_eur:.2f}EUR) supera il tetto "
                f"consigliato ({recommended_ceiling:.2f}EUR), ignorata")
            return
        starting_bid = min_next_bid_eur
    else:
        if current_price_eur >= recommended_ceiling:
            log(f"{player_name}: asta a {current_price_eur:.2f}EUR gia' oltre il tetto consigliato "
                f"({recommended_ceiling:.2f}EUR), ignorata")
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

    # Indicatore visivo rapido della bonta' dell'affare, in base al margine stimato in % sul tetto.
    indicator = "\U0001F7E0"  # arancione, default / margine ignoto
    if margin_estimate is not None and recommended_ceiling > 0:
        margin_pct = margin_estimate / recommended_ceiling
        if margin_pct >= 0.5:
            indicator = "\U0001F7E2"  # verde, ottimo affare
        elif margin_pct >= 0.2:
            indicator = "\U0001F7E1"  # giallo, discreto

    msg_lines = [
        f"{indicator} <b>Asta interessante — {player_name}</b>",
        "",
        f"\U0001F4B6 Prezzo attuale asta: <b>{current_price_eur:.2f}€</b>",
        f"\U0001F53C Minimo per essere in testa ora: <b>{starting_bid:.2f}€</b>",
        f"\U0001F3AF Offri fino a: <b>{recommended_ceiling:.2f}€</b>",
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
