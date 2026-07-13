import json
import urllib.request
import os
import smtplib
from email.message import EmailMessage

# 1. Configurazione Credenziali
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')

def send_email(subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = NOTIFY_EMAIL

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("Email di notifica inviata con successo.")
    except Exception as e:
        print(f"Errore invio email: {e}")

def main():
    if not COOKIES or not CSRF_TOKEN:
        print("Errore: Credenziali Sorare mancanti!")
        return

    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": "kylian-mbappe-lottin"},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Origin': 'https://sorare.com'
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        player = data.get('data', {}).get('anyPlayer', {})
        limited_card = player.get('lowestPriceLimitedCard')
        
        if not limited_card or not limited_card.get('liveSingleSaleOffer'):
            print("Nessuna offerta attiva trovata.")
            return

        current_price = limited_card['liveSingleSaleOffer']['receiverSide']['amounts']['eurCents'] / 100
        print(f"Prezzo attuale: {current_price} EUR")

        state_file = 'state.json'
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            state = {"price": 0}

        old_price = state.get("price", 0)

        if old_price != current_price:
            print("Variazione rilevata!")
            send_email("Notifica Sorare: Cambio Prezzo!", f"Il prezzo di Kylian Mbappé è passato da {old_price}€ a {current_price}€.")
            
            state["price"] = current_price
            with open(state_file, 'w') as f:
                json.dump(state, f)
        else:
            print("Nessuna variazione di prezzo.")

    except Exception as e:
        print(f"Errore generale: {e}")

if __name__ == '__main__':
    main()
