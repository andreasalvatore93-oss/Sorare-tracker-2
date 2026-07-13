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

def get_token_offer_fields():
    """Interroga Sorare in tempo reale per scoprire i campi attuali di TokenOffer"""
    query = """
    query {
      __type(name: "TokenOffer") {
        fields {
          name
          type {
            kind
            name
            ofType {
              kind
              name
            }
          }
        }
      }
    }
    """
    req = urllib.request.Request('https://api.sorare.com/graphql', data=json.dumps({'query': query}).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            if 'data' in res and res['data']['__type'] and res['data']['__type']['fields']:
                return res['data']['__type']['fields']
    except Exception as e:
        print(f"Errore durante l'introspezione dello schema: {e}")
    return []

def check_sorare():
    # 1. Rilevamento automatico dei campi prezzo
    fields_list = get_token_offer_fields()
    field_names = [f['name'] for f in fields_list]
    print(f"DIAGNOSTICA -> Campi attualmente disponibili su TokenOffer: {field_names}")
    
    # Cerchiamo il campo migliore per il prezzo in Euro/Fiat
    preferences = ['priceInEur', 'fiatAmount', 'fiatPrice', 'amountInCents', 'price']
    selected_field = None
    
    for pref in preferences:
        if pref in field_names:
            selected_field = next(f for f in fields_list if f['name'] == pref)
            break
            
    if not selected_field:
        # Fallback se hanno cambiato totalmente nome (cerchiamo parole chiave)
        for f in fields_list:
            if 'eur' in f['name'].lower() or 'fiat' in f['name'].lower() or 'price' in f['name'].lower():
                selected_field = f
                break
                
    if not selected_field:
        print("LOG -> Impossibile trovare un campo prezzo valido. Interrompo per evitare l'errore 422.")
        return

    field_name = selected_field['name']
    
    # Controlliamo se il campo è un oggetto o un numero semplice
    kind = selected_field['type'].get('kind')
    if kind == 'NON_NULL' and selected_field['type'].get('ofType'):
        kind = selected_field['type']['ofType'].get('kind')
        
    is_object = (kind == 'OBJECT')
    query_selection = f"{field_name} {{ amount }}" if is_object else field_name
    print(f"LOG -> Campo selezionato dinamicamente per la query: {query_selection}")

    # 2. Monitoraggio Giocatori
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
        
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            ... on Player {{
              lowestPriceAnyCard(rarities: [LIMITED], inSeason: {in_season_bool}) {{
                liveSingleSaleOffer {{
                  {query_selection}
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
                    player = res['data']['players'][0]
                    card_data = player.get('lowestPriceAnyCard')
                    
                    if card_data and card_data.get('liveSingleSaleOffer'):
                        offer = card_data['liveSingleSaleOffer']
                        
                        # Estraiamo il prezzo in base a com'è strutturato il campo
                        if is_object and offer.get(field_name):
                            price_raw = offer[field_name].get('amount')
                        else:
                            price_raw = offer.get(field_name)
                            
                        if price_raw is not None:
                            prezzo = float(price_raw)
                            # Se Sorare restituisce il prezzo in centesimi (es. 9500 anziché 95.00), lo corregge
                            if prezzo > 2000 and soglia < 500: 
                                prezzo = prezzo / 100.0
                                
                            print(f"LOG -> {nome} ({tipo}): Prezzo rilevato {prezzo}€ | Soglia {soglia}€")
                            
                            if prezzo <= soglia:
                                send_email(
                                    f"🔔 ALERT SORARE: {nome} ({tipo})", 
                                    f"La carta {tipo} di {nome} è scesa a {prezzo}€! (La tua soglia: {soglia}€)"
                                )
                    else:
                        print(f"LOG -> {nome} ({tipo}): Nessuna carta sul mercato.")
        except Exception as e:
            print(f"Errore durante il controllo di {slug}: {e}")

if __name__ == '__main__':
    check_sorare()
