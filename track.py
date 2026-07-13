import json
import urllib.request
import os

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def check_player(player_data):
    slug = player_data['slug']
    url = 'https://api.sorare.com/graphql'
    
    # Query stabile
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
        
        # DEBUG: Stampiamo le chiavi principali per capire dove sono le carte
        print(f"--- Dati ricevuti per {slug} ---")
        player_root = data.get('data', {}).get('anyPlayer', {})
        print(f"Chiavi disponibili in anyPlayer: {list(player_root.keys())}")
        
    except Exception as e:
        print(f"Errore: {e}")

with open('players.json', 'r') as f:
    players = json.load(f)
for p in players:
    check_player(p)
