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
    if not EMAIL_USER or not EMAIL_PASS: 
        return
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
        print(f"Errore invio email: {e}")

def load_and_clean_players():
    """Carica e pulisce il registro all'avvio"""
    try:
        with open('players_registry.json', 'r') as f:
            players = json.load(f)
        unique = {p['id']: p for p in players if p.get('id') and p.get('slug')}
        cleaned = list(unique.values())
        with open('players_registry.json', 'w') as f:
            json.dump(cleaned, f, indent=2)
        return cleaned
    except Exception as e:
        print(f"Errore caricamento registro: {e}")
        return []

def get_price_from_json_recursive(obj):
    """Restituisce {'price': valore, 'currency': 'EUR' o 'ETH'}"""
    if isinstance(obj, dict):
        # 1. Priorità: cerca EUR
        if obj.get('eurCents') is not None and isinstance(obj['eurCents'], (int, float)):
            return {'price': obj['eurCents'] / 100, 'currency': 'EUR'}
        # 2. Alternativa: cerca WEI (ETH)
        if obj.get('wei') is not None:
            return {'price': float(obj['wei']) / 1e18, 'currency': 'ETH'}
        # Ricorsione
        for v in obj.values():
            res = get_price_from_json_recursive(v)
            if res: return res
    elif isinstance(obj, list):
        for item in obj:
            res = get_price_from_json_recursive(item)
            if res: return res
    return None

def check_player(player_data, state):
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
                # --- MIGRAZIONE DATI VECCHI ---
                old_data = state.get(p_id)
                if isinstance(old_data, (int, float)):
                    old_data = {'price': float(old_data), 'currency': 'EUR'}
                
                # --- LOGICA ALERT ---
                if old_data and isinstance(old_data, dict) and old_data.get('currency') == new_data['currency']:
                    old_price = old_data.get('price', 0)
                    new_price = new_data['price']
                    if old_price > 0:
                        drop_percent = (old_price - new_price) / old_price
                        if new_price < old_price and drop_percent >= 0.05:
                            print(f"ALERT! {p_id} sceso: {old_price} {old_data['currency']} -> {new_price} {new_data['currency']}")
                            send_email(f"ALERT Sorare: {p_id}", f"Il prezzo è sceso del {drop_percent:.1%}.\nNuovo: {new_price} {new_data['currency']}\nPrecedente: {old_price} {old_data['currency']}")
                        else:
                            print(f"{p_id}: {new_price} {new_data['currency']} (nessuna variazione)")
                else:
                    print(f"{p_id}: {new_data['price']} {new_data['currency']} (inizializzazione o cambio valuta)")
                
                state[p_id] = new_data
            else:
                print(f"{p_id}: Nessun prezzo trovato")
    except Exception as e:
        print(f"Errore {p_id}: {e}")

# --- Esecuzione Principale ---
players = load_and_clean_players()
try:
    with open('state.json', 'r') as f: 
        state = json.load(f)
except: 
    state = {}

for p in players:
    check_player(p, state)
    time.sleep(1) 

with open('state.json', 'w') as f: 
    json.dump(state, f, indent=2)
