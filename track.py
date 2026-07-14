import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import urllib.request

# --- Configurazione ---
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

semaphore = asyncio.Semaphore(5)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def get_eth_rate():
    try:
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
            data = json.loads(r.read().decode())
            return float(data['ethereum']['eur'])
    except:
        return 3000.0

def init_db():
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, price REAL, currency TEXT)''')
    conn.commit()
    conn.close()

def get_player_data(p_id):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute("SELECT price, currency FROM players WHERE id=?", (p_id,))
    row = cursor.fetchone()
    conn.close()
    return {'price': row[0], 'currency': row[1]} if row else None

def update_player_data(p_id, price, currency):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO players (id, price, currency) VALUES (?, ?, ?)", (p_id, price, currency))
    conn.commit()
    conn.close()

async def send_telegram_msg_async(session, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        async with session.post(url, json=payload) as response:
            pass
    except Exception as e:
        log(f"Errore Telegram: {e}")

def get_prices_by_season(data, eth_rate):
    prices = {'current': None, 'classic': None}
    
    token_prices = []
    def find_token_prices(obj):
        if isinstance(obj, dict):
            if obj.get('__typename') == 'TokenPrice':
                token_prices.append(obj)
            for v in obj.values():
                find_token_prices(v)
        elif isinstance(obj, list):
            for item in obj:
                find_token_prices(item)
    
    find_token_prices(data)
    
    for tp in token_prices:
        amounts = tp.get('amounts', {})
        card = tp.get('card', {})
        deal = tp.get('deal', {})
        
        # FILTRO ATTIVO: Se esiste un 'buyer', è una vendita conclusa -> Scartiamo
        if deal.get('buyer') is not None:
            continue
            
        # Calcolo prezzo
        price_val_eur = 0
        if amounts.get('wei'):
            price_val_eur = (float(amounts['wei']) / 1e18) * eth_rate
        elif amounts.get('eurCents'):
            price_val_eur = float(amounts['eurCents']) / 100
        else:
            continue
            
        if price_val_eur > 0:
            year_raw = card.get('seasonYear')
            year = int(year_raw) if year_raw else 2026
            cat = 'current' if year >= 2026 else 'classic'
            
            # Debug per vedere cosa stiamo leggendo ora
            log(f"FILTERED: {cat.upper()} | Anno: {year} | Prezzo: {price_val_eur:.2f} EUR")
            
            if not prices[cat] or price_val_eur < prices[cat]['price_in_eur']:
                prices[cat] = {'price': price_val_eur, 'currency': 'EUR', 'price_in_eur': price_val_eur}
                
    return prices

async def check_player(session, player_data, eth_rate):
    slug = player_data.get('slug')
    p_id = player_data.get('id')
    url = 'https://api.sorare.com/graphql'
    
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": slug, "rarity": "limited"},
        "extensions": {"operationId": "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"}
    }
    
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    async with semaphore:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                
                season_prices = get_prices_by_season(data, eth_rate)
                
                for s_type in ['current', 'classic']:
                    new_data = season_prices.get(s_type)
                    if not new_data: continue
                    
                    db_id = f"{p_id}_{s_type}"
                    new_price_eur = new_data['price_in_eur']
                    old_data = get_player_data(db_id)
                    
                    if old_data:
                        old_price_eur = old_data['price']
                        drop_percent = (old_price_eur - new_price_eur) / old_price_eur
                        if new_price_eur < old_price_eur and drop_percent >= 0.05:
                            await send_telegram_msg_async(session, f"🔥 <b>Occasione {s_type.upper()}!</b>\n{slug}\nCalo: {drop_percent:.1%}\nPrezzo: {new_price_eur:.2f}€")
                    
                    update_player_data(db_id, new_price_eur, 'EUR')
        except Exception as e:
            log(f"ERRORE CRITICO {slug}: {str(e)}")

async def main():
    init_db()
    eth_rate = get_eth_rate()
    if not os.path.exists('players_registry.json'): 
        log("File registry non trovato!")
        return
        
    with open('players_registry.json', 'r') as f: 
        players = json.load(f)
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, eth_rate) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
