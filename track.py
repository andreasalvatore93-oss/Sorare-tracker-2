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
    
    # Payload per MarketSearchQuery (con filtro isClassic)
    payload = {
        "operationName": "MarketSearchQuery",
        "variables": {
            "filters": {
                "playerSlugs": [slug],
                "rarities": ["limited"],
                "isClassic": is_classic
            }
        },
        # SE IL BOT DA ERRORE "Operation not found", 
        # COPIA L'ID DAL TUO BROWSER (F12 -> Rete -> graphql -> Payload) E INCOLLALO QUI:
        "extensions": {"operationId": "React/7d4e3a89e63b65e949646b9772390f727c621390fe40d"}
    }
    
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            raw_response = response.read().decode()
            data = json.loads(raw_response)
        
        # Verifica errore API
        if 'data' not in data:
            print(f"Errore API per {p_id}: {raw_response}")
            return

        # MarketSearchQuery ritorna una lista (nodes)
        nodes = data['data']['marketSearch']['nodes']
        if not nodes:
            print(f"{p_id}: Nessuna carta trovata con isClassic={is_classic}")
            return
            
        # Prende la prima carta (la più economica ordinata di default)
        price = nodes[0]['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
        
        old_price = state.get(p_id, 0)
        if old_price != price:
            tipo = "Classic" if is_classic else "In-Season"
            print(f"Variazione {p_id} ({tipo}): {old_price} -> {price}")
            send_email(f"Notifica Sorare {tipo}", f"Prezzo {p_id} ({tipo}) cambiato: da {old_price} a {price}")
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
