import json
import os
import asyncio
import aiohttp
import datetime
import smtplib
import random
import sqlite3
from email.message import EmailMessage

# Configurazione
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')
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

# --- Funzioni di utilità (Sincrone) ---
def send_email(subject, body):
    if not EMAIL_USER or not EMAIL_PASS: return
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

async def send_telegram_msg_async(session, player_name, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        async with session.post(url, json=payload) as response:
            pass
    except Exception as e:
        log(f"Errore invio Telegram: {e}")

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

# --- Cuore del programma (Asincrono) ---
async def check_player(session, player_data, eth_rate):
    p_id = player_data['id']
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": player_data['slug']},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    async with semaphore:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                new_data = get_price_from_json_recursive(data)
                
                if new_data:
                    new_price_eur = new_data['price'] * eth_rate if new_data['currency'] == 'ETH' else new_data['price']
                    old_data = get_player_data(p_id)
                    
                    if old_data:
                        old_price_eur = old_data['price'] * eth_rate if old_data['currency'] == 'ETH' else old_data['price']
                        if old_price_eur > 0:
                            drop_percent = (old_price_eur - new_price_eur) / old_price_eur
                            if new_price_eur < old_price_eur and drop_percent >= 0.05:
                                log(f"ALERT! {p_id} sceso: {old_price_eur:.2f}€ -> {new_price_eur:.2f}€")
                                link = f"https://sorare.com/cards/players/{player_data['slug']}"
                                msg_text = f"🔥 <b>Occasione Sorare!</b>\n\nGiocatore: {p_id}\nCalo: {drop_percent:.1%}\nNuovo prezzo: {new_price_eur:.2f}€\n\n<a href='{link}'>Clicca qui per le offerte</a>"
                                send_email(f"ALERT Sorare: {p_id}", msg_text)
                                await send_telegram_msg_async(session, p_id, msg_text)
                            else:
                                log(f"{p_id}: nessuna variazione")
                    else:
                        log(f"{p_id}: inizializzazione")
                    
                    update_player_data(p_id, new_data['price'], new_data['currency'])
                else:
                    log(f"{p_id}: Nessun prezzo trovato")
        except Exception as e:
            log(f"Errore {p_id}: {e}")

async def main():
    init_db()
    
    with open('players_registry.json', 'r') as f:
        players = json.load(f)

    import urllib.request
    def get_eth_sync():
        try:
            with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
                return float(json.loads(r.read().decode())['ethereum']['eur'])
        except: return 3000.0
    
    eth_rate = get_eth_sync()
    log(f"Tasso ETH/EUR: {eth_rate}")

    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, eth_rate) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
