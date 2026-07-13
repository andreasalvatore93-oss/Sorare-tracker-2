import json
import urllib.request
import os

print("--- AVVIO SINCRONIZZAZIONE ---")

try:
    with open('players_registry.json', 'r') as f:
        registry = json.load(f)
    print(f"File caricato. Trovati {len(registry)} giocatori.")
except Exception as e:
    print(f"Errore nel caricare il file: {e}")
    exit()

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def get_correct_slug(player_id):
    print(f"Cerco slug per ID: {player_id}")
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "SearchPlayers",
        "query": "query SearchPlayers($query: String!) { searchPlayers(query: $query) { nodes { slug displayName } } }",
        "variables": {"query": player_id}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            players = data.get('data', {}).get('searchPlayers', {}).get('nodes', [])
            if players:
                print(f"Trovato: {players[0]['slug']}")
                return players[0]['slug']
            else:
                print(f"Nessun risultato trovato per: {player_id}")
    except Exception as e:
        print(f"Errore nella richiesta API: {e}")
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
    print("Registro aggiornato con successo!")
else:
    print("Nessuna modifica necessaria.")

print("--- FINE SINCRONIZZAZIONE ---")
