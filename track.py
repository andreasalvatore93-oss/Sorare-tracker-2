import json
import urllib.request
import os
import time
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
    slug = player_data['slug']
    p_id = player_data['id']
    
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
        
        player_info = data.get('data', {}).get('anyPlayer')
        if not player_info:
            print(f"ERRORE API per {p_id}: Nessun dato dal server.")
            return
            
        card = player_info.get('lowestPriceLimitedCard')
        if not card:
            print(f"{p_id}: Nessuna carta Limited 'Buy Now' disponibile.")
            return
            
        offer = card.get('liveSingleSaleOffer')
        if not offer:
            # DEBUG: Se arriviamo qui, stampiamo cosa c'è nella carta
            print(f"DEBUG {p_id}: Carta trovata ma senza 'liveSingleSaleOffer'. Dati carta: {card}")
            return
            
        price_cents = offer.get('receiverSide', {}).get('amounts', {}).get('eurCents')
        if price_cents is None:
            print(f"DEBUG {p_id}: Prezzo (eurCents) nullo.")
            return

        price = price_cents / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"Variazione {p_id}: {old_price} -> {price}")
            send_email(f"Notifica Sorare: {p_id}", f"Prezzo minimo {p_id} cambiato: da {old_price} a {price}€")
            state[p_id] = price
        else:
            print(f"{p_id}: Nessuna variazione ({price}€)")
            
    except Exception as e:
        print(f"ERRORE CRITICO per {p_id}: {e}")

# Esecuzione
with open('players.json', 'r') as f:
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
