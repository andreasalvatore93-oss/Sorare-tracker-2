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
    is_classic = player_data['isClassic']
    
    url = 'https://api.sorare.com/graphql'
    
    # Payload per la ricerca di mercato (MarketSearch)
    payload = {
        "operationName": "MarketSearchQuery",
        "variables": {
            "filters": {
                "playerSlugs": [slug],
                "rarities": ["limited"],
                "isClassic": is_classic
            }
        },
        "extensions": {"operationId": "React/5e6b12a84976451e0646c06a86c63b65e949646b9772390f727c621390fe40d"}
    }
    
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            raw_response = response.read().decode()
            data = json.loads(raw_response)
        
        # Verifica se la risposta contiene dati validi
        if 'data' not in data:
            print(f"Errore: API ha risposto ma manca 'data'. Risposta: {raw_response}")
            return

        nodes = data['data']['marketSearch']['nodes']
        if not nodes:
            print(f"{p_id}: Nessuna carta trovata con isClassic={is_classic}")
            return
            
        # Prende il prezzo della carta più economica (prima della lista)
        price = nodes[0]['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            print(f"Variazione {p_id}: {old_price} -> {price}")
            send_email("Notifica Sorare", f"Prezzo {p_id} cambiato: da {old_price} a {price}")
            state[p_id] = price
        else:
            print(f"{p_id}: Nessuna variazione ({price})")
            
    except Exception as e:
        print(f"Errore critico per {p_id}: {str(e)}")

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
