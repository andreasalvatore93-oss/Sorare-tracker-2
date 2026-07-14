import json
import urllib.request
import os
import time
import smtplib
from email.message import EmailMessage

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

def load_and_clean_players():
    """Carica e pulisce il registro all'avvio"""
    try:
        with open('players_registry.json', 'r') as f:
            players = json.load(f)
        # Rimuove duplicati basandosi sull'id
        unique = {p['id']: p for p in players if p.get('id') and p.get('slug')}
        cleaned = list(unique.values())
        with open('players_registry.json', 'w') as f:
            json.dump(cleaned, f, indent=2)
        return cleaned
    except Exception as e:
        print(f"Errore caricamento registro: {e}")
        return []

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

def check_player(player_data, state):
    p_id = player_data['id']
    slug = player_data['slug']
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
            price = get_price_from_json_recursive(json.loads(response.read().decode()))
            if price:
                old_price = state.get(p_id, 0)
                if old_price != price:
                    print(f"{p_id}: {old_price}€ -> {price}€")
                    send_email(f"Notifica Sorare: {p_id}", f"Prezzo aggiornato: {price}€")
                    state[p_id] = price
                else:
                    print(f"{p_id}: {price}€ (nessuna variazione)")
            else:
                print(f"{p_id}: Nessun prezzo trovato")
    except Exception as e:
        print(f"Errore {p_id}: {e}")

# --- Esecuzione Principale ---
players = load_and_clean_players()
try:
    with open('state.json', 'r') as f: state = json.load(f)
except: state = {}

for p in players:
    check_player(p, state)
    time.sleep(1) 

with open('state.json', 'w') as f: json.dump(state, f)
