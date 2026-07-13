import json
import os
import urllib.request
import urllib.error
import smtplib
from email.mime.text import MIMEText

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
        print(f"Notifica inviata con successo: {subject}")
    except Exception as e:
        print(f"Errore invio mail: {e}")

def check_sorare():
    lista_giocatori = [
        {"slug": "kylian-mbappe", "nome": "Kylian Mbappé", "tipo": "in_season", "soglia": 100.0},
        {"slug": "kylian-mbappe", "nome": "Kylian Mbappé", "tipo": "classic", "soglia": 96.0},
        {"slug": "hans-vanaken", "nome": "Hans Vanaken", "tipo": "in_season", "soglia": 8.0},
        {"slug": "hans-vanaken", "nome": "Hans Vanaken", "tipo": "classic", "soglia": 7.0}
    ]
        
    for target in lista_giocatori:
        slug = target["slug"]
        nome = target["nome"]
        tipo = target["tipo"]
        soglia = target["soglia"]
        in_season_bool = "true" if tipo == "in_season" else "false"
        
        # Query corretta ed ufficiale: puntiamo all'oggetto priceInFiat ed estraiamo eur
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            ... on Player {{
              lowestPriceAnyCard(rarities: [LIMITED], inSeason: {in_season_bool}) {{
                liveSingleSaleOffer {{
                  priceInFiat {{
                    eur
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        req = urllib.request.Request(
            'https://api.sorare.com/graphql', 
            data=json.dumps({'query': query}).encode('utf-8'), 
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                print(f"LOG -> Risposta ricevuta per {slug} ({tipo}): {res}")
                
                if 'data' in res and res['data']['players'] and res['data']['players'][0]:
                    player = res['data']['players'][0]
                    card_data = player.get('lowestPriceAnyCard')
                    
                    if card_data and card_data.get('liveSingleSaleOffer'):
                        offer = card_data['liveSingleSaleOffer']
                        fiat_data = offer.get('priceInFiat')
                        
                        if fiat_data and fiat_data.get('eur') is not None:
                            prezzo = float(fiat_data['eur'])
                            print(f"LOG -> {nome} ({tipo}): Prezzo attuale {prezzo}€ | Soglia {soglia}€")
                            
                            if prezzo <= soglia:
                                send_email(
                                    f"🔔 ALERT SORARE: {nome} ({tipo})", 
                                    f"La carta {tipo} di {nome} è scesa a {prezzo}€! (Soglia impostata: {soglia}€)"
                                )
                    else:
                        print(f"LOG -> {nome} ({tipo}): Nessuna carta attualmente in vendita diretta sul mercato.")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"Errore API Sorare per {slug} ({tipo}): Codice {e.code} - Dettaglio: {error_body}")
        except Exception as e:
            print(f"Errore imprevisto per {slug}: {e}")

if __name__ == '__main__':
    check_sorare()
