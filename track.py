import json
import urllib.request
import os
import time
import sys
import smtplib
from email.message import EmailMessage

# Caricamento sicuro dei segreti
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')

# Controllo immediato errori
if not COOKIES or not CSRF_TOKEN:
    print("ERRORE CRITICO: SORARE_COOKIE o SORARE_CSRF non trovati negli environment variables!")
    sys.exit(1)

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
        
        player_info = data.get('data', {}).get('anyPlayer')
        if not player_info:
            print(f"ERRORE API per {p_id}: Nessun dato dal server.")
            return

        # LOGICA AGGIORNATA: cerchiamo il prezzo minore tra In-Season e Classic
        prices = []
        
        # 1. In-Season
        in_season = player_info.get('lowestPriceLimitedCard')
        if in_season and in_season.get('liveSingleSaleOffer'):
            cents = in_season.get('liveSingleSaleOffer').get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if cents: prices.append(cents)
            
        # 2. Classic
        classic = player_info.get('lowestPriceClassicLimitedCard')
        if classic and classic.get('liveSingleSaleOffer'):
            cents = classic.get('liveSingleSaleOffer').get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if cents: prices.append(cents)
        
        if not prices:
            print(f"{p_id}: Nessuna carta Limited (In-Season o Classic) disponibile.")
            return
            
        price = min(prices) / 100
        
        # Confronto con lo stato
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
