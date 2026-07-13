import json
import urllib.request
import os
import smtplib
from email.message import EmailMessage

# Configurazione (non serve più l'operationId)
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')

def check_player(player_data, state):
    slug = player_data['slug']
    p_id = player_data['id']
    target_classic = player_data['isClassic']
    
    # Query stabile
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
        
        # Estrazione (se fallisce, stampa tutto per debug)
        try:
            # Qui cerchiamo nel layout le carte disponibili
            market_cards = data['data']['anyPlayer']['allLimitedCards'] 
            match = [c for c in market_cards if c.get('isClassic') == target_classic]
            
            if not match:
                print(f"{p_id}: Nessuna carta trovata.")
                return
            
            price = match[0]['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
            
            # (Logica di notifica qui...)
            print(f"{p_id}: Prezzo trovato {price}")
            
        except KeyError:
            print(f"DEBUG: Struttura dati cambiata. Ecco cosa ho ricevuto: {json.dumps(data, indent=2)}")
            
    except Exception as e:
        print(f"Errore: {e}")

# ... (restante logica)
