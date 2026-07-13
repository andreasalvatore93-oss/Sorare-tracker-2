import json
import urllib.request
import os
import time
import smtplib
from email.message import EmailMessage

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
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)

def check_player(player_data, state):
    p_id = player_data['id']
    candidates = player_data.get('slugs', [player_data.get('slug')])
    
    for slug in candidates:
        if not slug: continue
        url = 'https://api.sorare.com/graphql'
        payload = {
            "operationName": "AnyPlayerLayoutQuery",
            "variables": {"onlyPrimary": False, "slug": slug},
            "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
        }
        headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            
            player_info = data.get('data', {}).get('anyPlayer', {})
            
            if player_info:
                prices = []
                is_card = player_info.get('lowestPriceLimitedCard')
                if is_card and is_card.get('liveSingleSaleOffer'):
                    cents = is_card.get('liveSingleSaleOffer', {}).get('receiverSide', {}).get('amounts', {}).get('eurCents')
                    if cents: prices.append(cents)
                
                if not prices:
                    print(f"{p_id}: Trovato con slug '{slug}', ma nessuna carta Limited disponibile.")
                    return
                
                price = min(prices) / 100
                old_price = state.get(p_id, 0)
                if old_price != price:
                    print(f"Variazione {p_id} (slug: {slug}): {old_price}€ -> {price}€")
                    send_email(f"Notifica Sorare: {p_id}", f"Il prezzo minimo per {p_id} è {price}€")
                    state[p_id] = price
                else:
                    print(f"{p_id}: {price}€ (nessuna variazione)")
                return
                
        except Exception as e:
            print(f"Tentativo fallito per {slug}: {e}")
            continue

    print(f"{p_id}: Nessuno degli slug ha funzionato.")

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
