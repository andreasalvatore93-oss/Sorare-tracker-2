import json
import urllib.request
import os
import time
import smtplib
import random
import datetime
from email.message import EmailMessage

# Configurazione
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def get_eth_to_eur():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return float(data['ethereum']['eur'])
    except:
        return 3000.0

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

def send_telegram_msg(player_name, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            log(f"Telegram: Messaggio inviato con successo per {player_name}")
    except Exception as e:
        log(f"Errore invio Telegram: {e}")

def load_and_clean_players():
    try:
        with open('players_registry.json', 'r') as f:
            players = json.load(f)
        return [p for p in players if p.get('id') and p.get('slug')]
    except:
        return []

def get_price_from_json_recursive(obj):
    if isinstance(obj, dict):
        if obj.get('eurCents') is not None:
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

def check_player(player_data, state, eth_rate):
    p_id = player_data['id']
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": player_data['slug']},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            new_data = get_price_from_json_recursive(data)
            
            if new_data:
                new_price_eur = new_data['price'] * eth_rate if new_data['currency'] == 'ETH' else new_data['price']
                old_data = state.get(p_id)
                
                if old_data:
                    old_price_eur = old_data['price'] * eth_rate if old_data['currency'] == 'ETH' else old_data['price']
                    if old_price_eur > 0:
                        drop_percent = (old_price_eur - new_price_eur) / old_price_eur
                        if new_price_eur < old_price_eur and drop_percent >= 0.05:
                            log(f"ALERT! {p_id} sceso!")
                            link = f"https://sorare.com/cards/players/{player_data['slug']}"
                            msg_text = f"🔥 <b>Occasione Sorare!</b>\n\nGiocatore: {p_id}\nCalo: {drop_percent:.1%}\nNuovo prezzo: {new_price_eur:.2f}€\n\n<a href='{link}'>Clicca qui per le offerte</a>"
                            send_telegram_msg(p_id, msg_text)
                            send_email(f"ALERT Sorare: {p_id}", f"Calo del {drop_percent:.1%}")
                state[p_id] = new_data
    except Exception as e:
        log(f"Errore {p_id}: {e}")

# --- Esecuzione Principale ---
eth_rate = get_eth_to_eur()
# Test iniziale per confermare la connessione
send_telegram_msg("Test", "<b>Bot operativo!</b>\nConnessione Telegram stabilita con successo.")

players = load_and_clean_players()
try:
    with open('state.json', 'r') as f: state = json.load(f)
except: state = {}

for p in players:
    check_player(p, state, eth_rate)
    time.sleep(random.uniform(1.5, 3.5)) 

with open('state.json', 'w') as f: json.dump(state, f, indent=2)
