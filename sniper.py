import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import urllib.request

# Configurazione credenziali da ambiente GitHub
COOKIES = os.environ.get('SORARE_COOKIE', '').strip()
CSRF_TOKEN = os.environ.get('SORARE_CSRF', '').strip()
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# CONFIGURAZIONE FILTRI
MIN_PRICE_EUR = 0.1
MIN_L5_SCORE = 0
MIN_DISCOUNT = -1.0  # Accetta qualsiasi prezzo, anche se non è un vero sconto

semaphore = asyncio.Semaphore(5)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def init_db():
    conn = sqlite3.connect('sniper.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notified_offers (
            offer_id TEXT PRIMARY KEY,
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_already_notified(offer_id):
    conn = sqlite3.connect('sniper.db')
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM notified_offers WHERE offer_id=?", (offer_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_as_notified(offer_id):
    conn = sqlite3.connect('sniper.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO notified_offers (offer_id) VALUES (?)", (offer_id,))
    conn.commit()
    conn.close()

def get_price_from_json_recursive(obj):
    if isinstance(obj, dict):
        if obj.get('eurCents') is not None and isinstance(obj['eurCents'], (int, float)):
            return {'price': obj['eurCents'] / 100, 'currency': 'EUR'}
        if obj.get('wei') is not None:
            return {'price': float(obj['wei']) / 1e18, 'currency': 'ETH'}
        for v in obj.values():
            res = get_price_from_json_recursive(v)
            if res: return res
    elif isinstance(obj, list):
        for item in obj:
            res = get_price_from_json_recursive(item)
            if res: return res
    return None

async def send_telegram_msg_async(session, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        log("Configurazione Telegram mancante.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': False}
    try:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                log(f"Errore Telegram HTTP: {response.status}")
    except Exception as e:
        log(f"Errore connessione Telegram: {e}")

async def get_player_floor_prices(session, slug):
    url = 'https://api.sorare.com/graphql'
    query = """
    query PlayerFloor($slug: String!) {
      football {
        player(slug: $slug) {
          cards(scarcities: [limited], onSale: true) {
            nodes {
              id
              liveSingleSaleOffer {
                id
                price
              }
            }
          }
        }
      }
    }
    """
    payload = {"query": query, "variables": {"slug": slug}}
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    try:
        async with session.post(url, json=payload, headers=headers) as response:
            data = await response.json()
            cards = data.get('data', {}).get('football', {}).get('player', {}).get('cards', {}).get('nodes', [])
            return cards
    except Exception as e:
        log(f"Errore recupero floor per {slug}: {e}")
        return []

async def process_offer(session, offer, eth_rate):
    offer_id = offer.get('id')
    if not offer_id or is_already_notified(offer_id):
        return

    card = offer.get('card', {})
    player = card.get('player', {})
    if not player: return

    slug = player.get('slug')
    name = player.get('displayName')
    l5 = player.get('lastFiveSo5AverageScore', 0) or 0

    if l5 < MIN_L5_SCORE:
        return

    new_price_data = get_price_from_json_recursive(offer)
    if not new_price_data: return
    new_price_eur = new_price_data['price'] * eth_rate if new_price_data['currency'] == 'ETH' else new_price_data['price']

    if new_price_eur < MIN_PRICE_EUR:
        return

    other_listings = await get_player_floor_prices(session, slug)
    other_prices = []

    for item in other_listings:
        sale_offer = item.get('liveSingleSaleOffer')
        if not sale_offer or sale_offer.get('id') == offer_id:
            continue
        p_data = get_price_from_json_recursive(sale_offer)
        if p_data:
            p_eur = p_data['price'] * eth_rate if p_data['currency'] == 'ETH' else p_data['price']
            other_prices.append(p_eur)

    if not other_prices:
        return

    floor_competitor = min(other_prices)

    if new_price_eur < floor_competitor:
        discount = (floor_competitor - new_price_eur) / floor_competitor
        if discount >= MIN_DISCOUNT:
            log(f"🔥 OCCASIONE: {name} a {new_price_eur:.2f}€ | Floor: {floor_competitor:.2f}€ (-{discount:.1%})")
            link = f"https://sorare.com/football/players/{slug}"
            msg = (
                f"🎯 <b>NUOVO SNIPE TROVATO!</b>\n\n"
                f"👤 <b>{name}</b> (L5: {l5})\n"
                f"💰 Prezzo offerta: <b>{new_price_eur:.2f}€</b>\n"
                f"📉 Secondo prezzo più basso: {floor_competitor:.2f}€\n"
                f"🎁 Sconto calcolato: <b>{discount:.1%}</b>\n\n"
                f"👉 <a href='{link}'>Vedi la carta su Sorare</a>"
            )
            await send_telegram_msg_async(session, msg)
            mark_as_notified(offer_id)

async def main():
    init_db()
    
    try:
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
            eth_rate = float(json.loads(r.read().decode())['ethereum']['eur'])
    except Exception as e:
        log(f"Errore CoinGecko, uso fallback: {e}")
        eth_rate = 3000.0
        
    log(f"Tasso ETH/EUR: {eth_rate}")

    url = 'https://api.sorare.com/graphql'
    query = """
    query LatestLimitedOffers {
      football {
        openedSingleSaleOffers(first: 20, cardScarcities: [limited]) {
          nodes {
            id
            price
            card {
              id
              slug
              player {
                slug
                displayName
                lastFiveSo5AverageScore
              }
            }
          }
        }
      }
    }
    """
    payload = {"query": query}
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                res_json = await response.json()
                offers = res_json.get('data', {}).get('football', {}).get('openedSingleSaleOffers', {}).get('nodes', [])
                
                if not offers:
                    log("Nessuna nuova offerta sul mercato.")
                    return

                tasks = [process_offer(session, offer, eth_rate) for offer in offers]
                await asyncio.gather(*tasks)
        except Exception as e:
            log(f"Errore nel ciclo principale: {e}")

if __name__ == "__main__":
    asyncio.run(main())
