import json
import urllib.request
import os

# Configurazione identica al tuo bot
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def run_debug():
    # Carichiamo solo il primo giocatore per non intasare il log
    with open('players_registry.json', 'r') as f:
        players = json.load(f)
    
    player = players[0]
    slug = player['slug']
    print(f"DEBUG: Analizzando slug '{slug}'")

    url = 'https://api.sorare.com/graphql'
    
    # Usiamo la MarketplaceSearchQuery che ci sta dando problemi
    payload = {
        "operationName": "MarketplaceSearchQuery", 
        "variables": {"slugs": [slug], "rarities": ["limited"]},
        "extensions": {"operationId": "React/8651c890918738321287968531764014e854f4ba174c338"} 
    }
    
    headers = {
        'Content-Type': 'application/json', 
        'Cookie': COOKIES, 
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0'
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            raw_data = response.read().decode()
            data = json.loads(raw_data)
            print("--- RISPOSTA GREZZA ---")
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"ERRORE DI CONNESSIONE: {e}")

run_debug()
