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
        print(f"Notifica inviata: {subject}")
    except Exception as e:
        print(f"Errore invio mail: {e}")

def check_sorare():
    # Elenco locale comprensivo di Nome leggibile per i tuoi alert
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
        
        # Query pulita: chiediamo solo il prezzo senza incappare in errori di interfaccia
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            lowestPriceAnyCard(rarities: [LIMITED], inSeason: {in_season_bool})
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
                
                if 'data' in res and res['data']['players'] and res['data']['players'][0]:
                    player = res['data']['players'][0]
                    prezzo_raw = player.get('lowestPriceAnyCard')
                    
                    if prezzo_raw is not None:
                        prezzo = float(prezzo_raw)
                        print(f"LOG -> {nome} ({tipo}): Prezzo attuale {prezzo}€ | Soglia {soglia}€")
                        
                        if prezzo <= soglia:
                            oggetto = f"🔔 ALERT SORARE: {nome} ({tipo}) sotto la soglia!"
                            corpo = f"La carta {tipo} di {nome} è in vendita a {prezzo}€!\nSoglia impostata: {soglia}€."
                            send_email(oggetto, corpo)
                    else:
                        print(f"LOG -> {nome} ({tipo}): Nessuna carta sul mercato.")
                else:
                    print(f"LOG -> Nessun dato per {slug}")
                    
        except urllib.error.HTTPError as e:
            print(f"Errore API per {slug}: {e.read().decode('utf-8')}")
        except Exception as e:
            print(f"Errore imprevisto per {slug}: {e}")

if __name__ == '__main__':
    check_sorare()
