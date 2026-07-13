import json
import os
import urllib.request
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
    except Exception as e:
        print(f"Errore email: {e}")

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
        
        # CORREZIONE: rarities -> rarity
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
        req = urllib.request.Request('https://api.sorare.com/graphql', data=json.dumps({'query': query}).encode('utf-8'), headers={'Content-Type': 'application/json'})
        
        try:
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                
                if 'data' in res and res['data']['players'] and res['data']['players'][0]:
                    card = res['data']['players'][0].get('lowestPriceAnyCard')
                    if card and card.get('liveSingleSaleOffer'):
                        receiver_side = card['liveSingleSaleOffer'].get('receiverSide')
                        if receiver_side and receiver_side.get('amounts'):
                            prezzo = float(receiver_side['amounts'].get('eurCents', 0)) / 100.0
                            print(f"LOG -> {nome} ({tipo}): {prezzo}€")
                            if prezzo <= soglia:
                                send_email(f"🔔 ALERT: {nome}", f"Prezzo: {prezzo}€")
                        else:
                            print(f"LOG -> {nome} ({tipo}): Nessun prezzo disponibile.")
                    else:
                        print(f"LOG -> {nome} ({tipo}): Nessuna offerta attiva.")
        except Exception as e:
            print(f"Errore query per {slug}: {e}")

if __name__ == '__main__':
    check_sorare()
