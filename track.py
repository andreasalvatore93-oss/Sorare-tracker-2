import json
import os
import urllib.request
import smtplib
from email.mime.text import MIMEText

def log(msg):
    print(msg, flush=True)

def send_email(subject, body):
    user = os.environ.get('GMAIL_ADDRESS')
    pwd = os.environ.get('GMAIL_APP_PASSWORD')
    to_email = os.environ.get('NOTIFY_EMAIL')
    if not user or not pwd or not to_email: return
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = to_email
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        log("Email inviata con successo.")
    except Exception as e:
        log(f"Errore email: {e}")

def check_sorare():
    log("--- INIZIO CONTROLLO CON SPORT: FOOTBALL ---")
    
    # Query aggiornata con il parametro sport: FOOTBALL
    query = """
    query {
      players(slugs: ["kylian-mbappe"], sport: FOOTBALL) {
        ... on Player {
          lowestPriceAnyCard(rarity: LIMITED, inSeason: true) {
            liveSingleSaleOffer { 
              receiverSide { 
                amounts { 
                  eurCents 
                } 
              } 
            }
          }
        }
      }
    }
    """
    
    try:
        req = urllib.request.Request('https://api.sorare.com/graphql', 
                                     data=json.dumps({'query': query}).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            
            # Diagnostica
            players = res.get('data', {}).get('players', [])
            if players:
                card = players[0].get('lowestPriceAnyCard')
                if card and card.get('liveSingleSaleOffer'):
                    eur_cents = card['liveSingleSaleOffer']['receiverSide']['amounts'].get('eurCents')
                    prezzo = float(eur_cents) / 100.0
                    log(f"SUCCESS - Prezzo rilevato: {prezzo}€")
                    if prezzo <= 110.0:
                        send_email("🔔 TEST RIUSCITO", f"Mbappé trovato a {prezzo}€")
                else:
                    log("Giocatore trovato, ma nessuna offerta attiva.")
            else:
                log(f"ERRORE - Ancora nessun giocatore trovato. Risposta: {res}")
                
    except Exception as e:
        log(f"Errore query: {e}")

if __name__ == '__main__':
    check_sorare()
