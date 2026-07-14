import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import shutil

# Configurazione
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

semaphore = asyncio.Semaphore(5)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

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

def get_prices_by_season(data):
    prices = {'current': None, 'classic': None}
    
    def find_price_data(obj, path="root"):
        if not isinstance(obj, dict): return
        
        # FILTRO AGGRESSIVO: ignoriamo tutto ciò che non è floor price o listing
        # e scartiamo a priori le SuperRare
        if any(bad in path for bad in ['SuperRare', 'LastSale', 'SingleSaleOffer']):
            return
        
        # Cerchiamo solo se il nodo sembra essere rilevante per il mercato
        is_market_data = 'floorPrice' in path.lower() or 'listings' in path.lower() or 'market' in path.lower()
        
        eur_cents = obj.get('eurCents')
        wei = obj.get('wei')
        
        if (eur_cents is not None or wei is not None) and is_market_data:
            price_val = float(eur_cents)/100 if eur_cents is not None else float(wei)/1e18
            currency = 'EUR' if eur_cents is not None else 'ETH'
            
            # Categoria
            cat = 'current'
            season = obj.get('season')
            if isinstance(season, dict):
                year = int(season.get('year', 2026))
                cat = 'current' if year >= 2025 else 'classic'
            
            if not prices[cat] or price_val < prices[cat]['price']:
                prices[cat] = {'price': price_val, 'currency': currency}
        
        for k, v in obj.items():
            new_path = f"{path}.{k}"
            if isinstance(v, (dict, list)): find_price_data(v, new_path)
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    find_price_data(item, f"{new_path}[{i}]")

    find_price_data(data)
    return prices

async def check_player(session, player_data, eth_rate):
    slug = player_data.get('slug')
    p_id = player_data.get('id')
    
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    async with semaphore:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                season_prices = get_prices_by_season(data)
                log(f"Analisi {slug}: {season_prices}")
                
                for s_type in ['current', 'classic']:
                    new_data = season_prices.get(s_type)
                    if not new_data: continue
                    
                    db_id = p_id if s_type == 'current' else f"{p_id}_{s_type}"
                    new_price_eur = new_data['price'] * eth_rate if new_data['currency'] == 'ETH' else new_data['price']
                    old_data = get_player_data(db_id)
                    
                    if old_data:
                        old_price_eur = old_data['price'] * eth_rate if old_data['currency'] == 'ETH' else old_data['price']
                        drop_percent = (old_price_eur - new_price_eur) / old_price_eur
                        if new_price_eur < old_price_eur and drop_percent >= 0.05:
                            log(f"ALERT! {slug} ({s_type}) sceso: {old_price_eur:.2f}€ -> {new_price_eur:.2f}€")
                            await send_telegram_msg_async(session, f"🔥 <b>Occasione {s_type.upper()}!</b>\n{slug}\nCalo: {drop_percent:.1%}\nPrezzo: {new_price_eur:.2f}€")
                    
                    update_player_data(db_id, new_data['price'], new_data['currency'])
        except Exception as e:
            log(f"ERRORE CRITICO {slug}: {str(e)}")

async def main():
    init_db()
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
            eth_rate = float(json.loads(r.read().decode())['ethereum']['eur'])
    except: eth_rate = 3000.0
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, eth_rate) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
