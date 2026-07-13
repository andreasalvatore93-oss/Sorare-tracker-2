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
    
    if not user or not pwd or not to_email:
        print("Mancano i Secrets di GitHub. Impossibile inviare l'email.")
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
        print(f"Notifica email inviata con successo per: {subject}")
    except Exception as e:
        print(f"Errore nell'invio della mail: {e}")

def check_sorare():
    lista_giocatori = [
        {"slug": "kylian-mbappe", "tipo": "in_season", "soglia": 100.0},
        {"slug": "kylian-mbappe", "tipo": "classic", "soglia": 96.0},
        {"slug": "hans-vanaken", "tipo": "in_season", "soglia": 8.0},
        {"slug": "hans-vanaken", "tipo": "classic", "soglia": 7.0}
    ]
        
    for target in lista_giocatori:
        slug = target["slug"]
        tipo = target["tipo"]
        soglia = target["soglia"]
        in_season_bool = "true" if tipo == "in_season" else "false"
        
        # Corretto 'limited' in 'LIMITED' (Maiuscolo richiesto dalle specifiche GraphQL)
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            name
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
                    nome = player['name']
                    prezzo_raw = player.get('lowestPriceAnyCard')
                    
                    if prezzo_raw is not None:
                        prezzo = float(prezzo_raw)
                        print(f"LOG -> {nome} ({tipo}): Prezzo attuale {prezzo}€ | Soglia {soglia}€")
                        
                        if prezzo <= soglia:
                            oggetto = f"🔔 ALERT SORARE: {nome} ({tipo}) sotto la soglia!"
                            corpo = f"La carta {tipo} di {nome} è in vendita a {prezzo}€!\nLa tua soglia impostata era di {soglia}€."
                            send_email(oggetto, corpo)
                    else:
                        print(f"LOG -> {nome} ({tipo}): Nessuna carta di questo tipo sul mercato al momento.")
                else:
                    print(f"LOG -> Dati non strutturati per {slug}: {res}")
                    
        except urllib.error.HTTPError as e:
            # Questa modifica permette di leggere la motivazione reale sputata dal server di Sorare
            error_body = e.read().decode('utf-8')
            print(f"Errore API Sorare per {slug} ({tipo}): Codice {e.code} - Dettaglio: {error_body}")
        except Exception as e:
            print(f"Errore imprevisto durante il controllo di {slug} ({tipo}): {e}")

if __name__ == '__main__':
    check_sorare()
