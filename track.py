import json
import urllib.request
import os
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
    target_classic = player_data['isClassic']
    
    url = 'https://api.sorare.com/graphql'
    
    # Query stabile: non scade mai
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
        
        # Filtriamo internamente le carte ricevute
        cards = data['data']['anyPlayer']['allLimitedCards'] # O struttura simile
        match = None
        for card in cards:
            if card.get('isClassic') == target_classic:
                match = card
                break
        
        if not match:
            print(f"{p_id}: Nessuna carta trovata.")
            return
            
        price = match['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            tipo = "Classic" if target_classic else "In-Season"
            print(f"Variazione {p_id} ({tipo}): {old_price} -> {price}")
            send_email(f"Sorare: {p_id} ({tipo})", f"Prezzo cambiato: da {old_price} a {price}")
            state[p_id] = price
        else:
            print(f"{p_id} ({'Classic' if target_classic else 'In-Season'}): Nessuna variazione ({price})")
            
    except Exception as e:
        print(f"Errore per {p_id}: {e}")

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

with open('state.json', 'w') as f:
    json.dump(state, f)
