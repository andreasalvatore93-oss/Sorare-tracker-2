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
CURRENT_YEAR = "2026" # Anno corrente per distinguere Season da Classic

def send_email(subject, body):
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
    mode = player_data['type'] # 'season' o 'classic'
    
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    
    try:
        # Recuperiamo la carta Limited più economica
        card = data['data']['anyPlayer']['lowestPriceLimitedCard']
        if not card:
            print(f"{p_id}: Nessuna carta limited trovata.")
            return

        card_slug = card['slug']
        is_season = CURRENT_YEAR in card_slug # Se contiene 2026, è Season
        price = card['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
        
        # Logica di filtraggio
        final_price = None
        if mode == 'season' and is_season:
            final_price = price
        elif mode == 'classic' and not is_season:
            final_price = price
        else:
            # La carta trovata non corrisponde alla categoria (es: cerchi Classic ma la più economica è Season)
            print(f"{p_id}: La carta più economica ({card_slug}) non è di tipo {mode}")
            return

        # Confronto e notifica
        old_price = state.get(p_id, 0)
        if old_price != final_price:
            print(f"Variazione {p_id}: {old_price} -> {final_price}")
            send_email("Notifica Sorare", f"Prezzo {p_id} cambiato: da {old_price} a {final_price}")
            state[p_id] = final_price
        else:
            print(f"{p_id}: Nessuna variazione ({final_price})")

    except (TypeError, KeyError) as e:
        print(f"Errore nella lettura del prezzo per {p_id}: {e}")

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
