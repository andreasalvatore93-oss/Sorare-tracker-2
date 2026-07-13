import json
import urllib.request
import os
import time
import sys
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
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)

def check_player(player_data, state):
    slug = player_data['slug']
    p_id = player_data['id']
    
    url = 'https://api.sorare.com/graphql'
    # Questa query è più ampia e dovrebbe includere tutti i dati di mercato
    payload = {
        "operationName": "MarketplaceSearchQuery", 
        "variables": {"slugs": [slug], "rarities": ["limited"]},
        "extensions": {"operationId": "React/8651c890918738321287968531764014e854f4ba174c338"} 
    }
    
    headers = {
        'Content-Type': 'application/json', 
        'Cookie': COOKIES, 
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        
        # Estrattore dati Marketplace (logica diversa da AnyPlayer)
        results = data.get('data', {}).get('cards', {}).get('nodes', [])
        
        # Filtriamo le offerte attive (senza distinzione Classic/In-Season, prendiamo il minimo assoluto)
        prices = []
        for card in results:
            offer = card.get('liveSingleSaleOffer')
            if offer:
                cents = offer.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if cents: prices.append(cents)
        
        if not prices:
            print(f"{p_id}: Nessuna offerta attiva trovata.")
            return
            
        price = min(prices) / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"Variazione {p_id}: {old_price}€ -> {price}€")
            send_email(f"Notifica Sorare: {p_id}", f"Prezzo minimo {p_id} aggiornato: {price}€")
            state[p_id] = price
        else:
            print(f"{p_id}: {price}€ (nessuna variazione)")
            
    except Exception as e:
        print(f"Errore su {p_id}: {e}")

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
