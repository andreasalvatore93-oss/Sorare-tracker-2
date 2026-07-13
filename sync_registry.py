import json
import urllib.request
import os

with open('players_registry.json', 'r') as f:
    registry = json.load(f)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def get_correct_slug(player_id):
    url = 'https://api.sorare.com/graphql'
    
    # Struttura richiesta ottimizzata
    payload = {
        "operationName": "SearchPlayers",
        "variables": {"query": player_id},
        "extensions": {"operationId": "8b3f17d2a5d2b78125435905581977755f1a5857211848529367980313554449"}
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            players = data.get('data', {}).get('searchPlayers', {}).get('nodes', [])
            return players[0]['slug'] if players else None
    except Exception as e:
        print(f"Errore su {player_id}: {e}")
        return None

updated = False
for p in registry:
    new_slug = get_correct_slug(p['id'])
    if new_slug and new_slug != p['slug']:
        print(f"Aggiornato: {p['slug']} -> {new_slug}")
        p['slug'] = new_slug
        updated = True

if updated:
    with open('players_registry.json', 'w') as f:
        json.dump(registry, f, indent=4)
    print("Registro aggiornato.")
else:
    print("Nessuna modifica necessaria.")
