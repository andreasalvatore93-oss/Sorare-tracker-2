import json
import os
import asyncio
import aiohttp
import datetime
import smtplib
import sqlite3
from email.message import EmailMessage

# Configurazione
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

semaphore = asyncio.Semaphore(10)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

# --- Funzioni Database ---
def init_db():
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            price REAL,
            currency TEXT
        )
    ''')
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
    cursor.execute("INSERT OR REPLACE INTO players (id, price, currency) VALUES (?, ?, ?)", 
                   (p_id, price, currency))
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
        log(f"Errore invio Telegram: {e}")

# --- Logica Estrazione Prezzi ---
def get_prices_by_season(data):
    """
    Scansiona il JSON per trovare il prezzo floor di Current e Classic.
    Assumiamo che la stagione corrente sia '2025/2026' (o l'anno corrente).
    """
    prices = {'current': None, 'classic': None}
    
    # Questa parte naviga nella struttura standard Sorare
    # Cerchiamo liste di carte (spesso in cards.nodes)
    def search_node(node):
        if not isinstance(node, dict): return
        
        # Estrai Prezzo
        price_obj = node.get('floorPrice') or node.get('price')
        if not price_obj: return
        
        price = None
        if 'eurCents' in price_obj: price = {'price': price_obj['eurCents'] / 100, 'currency': 'EUR'}
        elif 'wei' in price_obj: price = {'price': float(price_obj['wei']) / 1e18, 'currency': 'ETH'}
        
        if not price: return

        # Identifica Stagione
        season = node.get('season') or node.get('card', {}).get('season')
        year = season.get('year') if isinstance(season, dict) else None
        
        # LOGICA: Se anno >= 2025 è Current, altrimenti Classic
        if year and int(year) >= 2025:
            if not prices['current'] or price['price'] < prices['current']['price']:
                prices['current'] = price
        else:
            if not prices['classic'] or price['price'] < prices['classic']['price']:
                prices['classic'] = price

    # Recursive search per trovare i nodi carta nel JSON
    def find_cards(obj):
        if isinstance(obj, dict):
            if 'floorPrice' in obj or 'price' in obj: search_node(obj)
            for v in obj.values(): find_cards(v)
        elif isinstance(obj, list):
            for item in obj: find_cards(item)

    find_cards(data)
    return prices

# --- Cuore del programma ---
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
                
                # Processiamo sia 'current' che 'classic'
                for s_type in ['current', 'classic']:
                    new_data = season_prices.get(s_type)
                    if not new_data: continue
                    
                    # ID unico per il database (es: p_id_classic)
                    db_id = p_id if s_type == 'current' else f"{p_id}_{s_type}"
                    
                    new_price_eur = new_data['price'] * eth_rate if new_data['currency'] == 'ETH' else new_data['price']
                    old_data = get_player_data(db_id)
                    
                    if old_data:
                        old_price_eur = old_data['price'] * eth_rate if old_data['currency'] == 'ETH' else old_data['price']
                        if old_price_eur > 0:
                            drop_percent = (old_price_eur - new_price_eur) / old_price_eur
                            if new_price_eur < old_price_eur and drop_percent >= 0.05:
                                if drop_percent > 0.50:
                                    log(f"ALERT SOSPETTO {s_type.upper()}: {slug} sceso troppo. Ignorato.")
                                else:
                                    log(f"ALERT {s_type.upper()}! {slug} sceso: {old_price_eur:.2f}€ -> {new_price_eur:.2f}€")
                                    link = f"https://sorare.com/football/players/{slug}"
                                    msg_text = f"🔥 <b>Occasione {s_type.upper()}!</b>\n\nGiocatore: {slug}\nCalo: {drop_percent:.1%}\nNuovo prezzo: {new_price_eur:.2f}€\n\n<a href='{link}'>Clicca qui per le offerte</a>"
                                    await send_telegram_msg_async(session, msg_text)
                    
                    update_player_data(db_id, new_data['price'], new_data['currency'])
        except Exception as e:
            log(f"Errore {slug}: {e}")

async def main():
    init_db()
    
    with open('players_registry.json', 'r') as f:
        players = json.load(f)

    import urllib.request
    try:
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
            eth_rate = float(json.loads(r.read().decode())['ethereum']['eur'])
    except: eth_rate = 3000.0
    
    log(f"Tasso ETH/EUR: {eth_rate}")

    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, eth_rate) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
