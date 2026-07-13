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
    if not user or not pwd or not to_email: 
        log("Errore: Credenziali email non configurate.")
        return
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
    log("--- SCRIPT AVVIATO ---")
    lista_giocatori = [
        {"slug": "kylian-mbappe", "nome": "Kylian Mbappé", "tipo": "in_season", "soglia": 110.0},
    ]
    
    for target in lista_giocatori:
        slug = target["slug"]
        nome = target["nome"]
        tipo = target["tipo"]
        soglia = target["soglia"]
        in_season_bool = "true" if tipo == "in_season" else "false"
        
        log(f"--- CONTROLLO: {nome} ({tipo}) ---")
        
        # CORREZIONE: rarity: LIMITED (tutto maiuscolo)
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            ... on Player {{
              lowestPriceAnyCard(rarity: LIMITED, inSeason: {in_season_bool}) {{
                liveSingleSaleOffer {{
                  receiverSide {{
                    amounts {{
                      eurCents
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        
        try:
            req = urllib.request.Request('https://api.sorare.com/graphql', 
                                         data=json.dumps({'query': query}).encode('utf-8'), 
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                
                if not res.get('data', {}).get('players'):
                    log(f"DEBUG - Nessun dato per {slug}. Risposta: {res}")
                    continue

                card = res['data']['players'][0].get('lowestPriceAnyCard')
                if card and card.get('liveSingleSaleOffer'):
                    eur_cents = card['liveSingleSaleOffer']['receiverSide']['amounts'].get('eurCents')
                    if eur_cents is not None:
                        prezzo = float(eur_cents) / 100.0
                        log(f"SUCCESS - {nome} ({tipo}) trovato a {prezzo}€")
                        if prezzo <= soglia:
                            send_email(f"🔔 ALERT: {nome}", f"Prezzo: {prezzo}€")
                    else:
                        log(f"LOG -> {nome}: Offerta presente ma prezzo in euro non disponibile.")
                else:
                    log(f"LOG -> {nome}: Nessuna offerta attiva trovata.")
        except Exception as e:
            log(f"Errore query per {slug}: {e}")
            
    log("--- SCRIPT TERMINATO ---")

if __name__ == '__main__':
    check_sorare()
