import json
import urllib.request
import os
import time
import smtplib
import re
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
    except Exception as e:
        print(f"Errore invio email: {e}")

def generate_slug_guesses(player_data):
    p_id = player_data.get('id', '')
    provided_slug = player_data.get('slug', '')
    
    guesses = []
    if provided_slug:
        guesses.append(provided_slug)
        
    base = p_id.lower().strip().replace(" ", "-")
    if base and base not in guesses:
        guesses.append(base)
        
    parts = base.split("-")
    if len(parts) > 1:
        guesses.append(parts[-1]) 
        guesses.append(parts[0])  
        
    seen = set()
    return [x for x in guesses if not (x in seen or seen.add(x))]

def get_price_from_json(data):
    """Cerca ricorsivamente qualsiasi prezzo eurCents nel JSON di risposta"""
    s = str(data)
    # Cerca il pattern eurCents in tutto il JSON
    prices = re.findall(r"'eurCents': (\d+)", s)
    if prices:
        # Prende il prezzo minimo tra tutti quelli trovati (assicurandosi che sia > 0)
        valid_prices = [int(p) for p in prices if int(p) > 0]
        if valid_prices:
            return min(valid_prices) / 100
    return None

def check_player(player_data, state):
    p_id = player_data['id']
    candidates = generate_slug_guesses(player_data)
    
    for slug in candidates:
        url = 'https://api.sorare.com/graphql'
        payload = {
            "operationName": "AnyPlayerLayoutQuery",
            "variables": {"onlyPrimary": False, "slug": slug},
            "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
        }
        headers = {
            'Content-Type': 'application/json', 
            'Cookie': COOKIES, 
            'x-csrf-token': CSRF_TOKEN,
            'User-Agent': 'Mozilla/5.0'
        }
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            
            # Estrazione prezzo flessibile
            price = get_price_from_json(data)
            
            if price:
                old_price = state.get(p_id, 0)
                if old_price != price:
                    print(f"Variazione {p_id} (via {slug}): {old_price}€ -> {price}€")
                    send_email(f"Notifica Sorare: {p_id}", f"Il prezzo minimo per {p_id} è ora {price}€")
                    state[p_id] = price
                else:
                    print(f"{p_id} (slug: '{slug}'): {price}€ (nessuna variazione)")
                return # Trovato e fatto
                
        except Exception as e:
            print(f"Errore durante richiesta per {slug}: {e}")
            continue 

    print(f"{p_id}: Nessun prezzo trovato con nessuna combinazione.")

# Esecuzione
with open('players_registry.json', 'r') as f:
    players = json.load(f)

try:
    with open('state.json', 'r') as f:
        state = json.load(f)
except:
    state = {}

for p in players:
    check_player(p, state)
    time.sleep(4) 

with open('state.json', 'w') as f:
    json.dump(state, f)
