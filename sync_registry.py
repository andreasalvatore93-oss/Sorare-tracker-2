import json
import urllib.request
import os

# Carica il registro
with open('players_registry.json', 'r') as f:
    registry = json.load(f)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def get_correct_slug(player_id):
    url = 'https://api.sorare.com/graphql'
    
    # Struttura richiesta che simula un browser
    payload = {
        "operationName": "SearchPlayers",
        "variables": {"query": player_id},
        "query": "query SearchPlayers($query: String!) { searchPlayers(query: $query) { nodes { slug displayName } } }"
    }
    
    # Headers con User-Agent per evitare blocco 422
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            players = data.get('data', {}).get('searchPlayers', {}).get('nodes', [])
            return players[0]['slug'] if players else None
    except Exception as e:
        print(f"Errore su {player_id}: {e}")
        return None

# Esegui aggiornamento
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
