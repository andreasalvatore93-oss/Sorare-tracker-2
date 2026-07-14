import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import shutil

# ... [Configurazione e funzioni di base invariate] ...
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

semaphore = asyncio.Semaphore(5)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

# ... [Invariate init_db, get_player_data, update_player_data, send_telegram_msg_async] ...
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
    conn.commit()
    conn.close()

async def send_telegram_msg_async(session, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    # ... (omesso per brevità, resta invariato)
    pass

# --- NUOVA LOGICA DI ESTRAZIONE ---
def get_prices_by_season(data):
    all_prices = [] # Lista per vedere TUTTO quello che troviamo
    
    def find_price_data(obj, path="root"):
        if not isinstance(obj, dict): return
        
        price_val = None
        currency = None
        if obj.get('eurCents') is not None:
            price_val = float(obj['eurCents']) / 100
            currency = 'EUR'
        elif obj.get('wei') is not None:
            price_val = float(obj['wei']) / 1e18
            currency = 'ETH'
            
        if price_val is not None:
            # Salviamo il dato con il suo percorso per capire da dove viene
            all_prices.append({'price': price_val, 'path': path})
        
        for k, v in obj.items():
            new_path = f"{path}.{k}"
            if isinstance(v, (dict, list)): find_price_data(v, new_path)
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    find_price_data(item, f"{new_path}[{i}]")

    find_price_data(data)
    return all_prices

async def check_player(session, player_data, eth_rate):
    slug = player_data.get('slug')
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
                # Recuperiamo tutti i prezzi trovati
                found_prices = get_prices_by_season(data)
                # Logghiamo TUTTO per vedere cosa c'è dentro
                log(f"DEBUG {slug}: Trovati {len(found_prices)} prezzi:")
                for p in found_prices:
                    log(f" -> {p['price']}€ in {p['path']}")
        except Exception as e:
            log(f"ERRORE {slug}: {str(e)}")

async def main():
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, 1630.0) for p in players] # Tasso fisso per ora
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
