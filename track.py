import json
import urllib.request
import os
import time
import smtplib
import re
from email.message import EmailMessage
from playwright.sync_api import sync_playwright

# Configurazione
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')

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
    except: pass

def get_price_from_json_recursive(data):
    prices = []
    def extract_prices(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == 'eurCents' and isinstance(v, (int, float)): prices.append(v)
                else: extract_prices(v)
        elif isinstance(obj, list):
            for item in obj: extract_prices(item)
    extract_prices(data)
    valid = [p for p in prices if p > 0]
    return min(valid) / 100 if valid else None

def get_price_via_api(slug):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            return get_price_from_json_recursive(json.loads(response.read().decode()))
    except: return None

def get_price_via_browser(slug):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"https://sorare.com/it/football/players/{slug}", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            content = page.content()
            prices = re.findall(r'"eurCents":(\d+)', content)
            browser.close()
            valid = [int(p) for p in prices if int(p) > 0]
            return min(valid) / 100 if valid else None
    except: return None

def check_player(player_data, state):
    p_id = player_data['id']
    slug = player_data['slug']
    
    # 1. Prova API (veloce)
    price = get_price_via_api(slug)
    method = "API"
    
    # 2. Se fallisce, prova Browser (lento)
    if not price:
        price = get_price_via_browser(slug)
        method = "Browser"
    
    if price:
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"[{method}] {p_id}: {old_price}€ -> {price}€")
            send_email(f"Notifica Sorare: {p_id}", f"Prezzo aggiornato: {price}€")
            state[p_id] = price
        else:
            print(f"[{method}] {p_id}: {price}€ (nessuna variazione)")
    else:
        print(f"Nessun prezzo trovato per {p_id}")

# Esecuzione
with open('players_registry.json', 'r') as f: players = json.load(f)
try:
    with open('state.json', 'r') as f: state = json.load(f)
except: state = {}

for p in players:
    check_player(p, state)
    time.sleep(1) # Pausa minima tra le chiamate API

with open('state.json', 'w') as f: json.dump(state, f)
