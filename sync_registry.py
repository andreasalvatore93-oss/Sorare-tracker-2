import json
import urllib.request
import os

# 1. Carichiamo il registro
with open('players_registry.json', 'r') as f:
    registry = json.load(f)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def get_correct_slug(player_name):
    url = 'https://api.sorare.com/graphql'
    query = """
    query SearchPlayers($query: String!) {
      searchPlayers(query: $query) {
        nodes {
          slug
          displayName
        }
      }
    }
    """
    payload = {"query": query, "variables": {"query": player_name}}
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            players = data.get('data', {}).get('searchPlayers', {}).get('nodes', [])
            if players:
                # Prende il primo risultato trovato
                return players[0]['slug']
    except Exception as e:
        print(f"Errore ricerca per {player_name}: {e}")
    return None

# 2. Controllo e aggiornamento
updated = False
for p in registry:
    # Cerchiamo lo slug corretto usando l'id (che contiene il nome)
    new_slug = get_correct_slug(p['id'])
    if new_slug and new_slug != p['slug']:
        print(f"Aggiornato: {p['slug']} -> {new_slug}")
        p['slug'] = new_slug
        updated = True

# 3. Salviamo se ci sono state modifiche
if updated:
    with open('players_registry.json', 'w') as f:
        json.dump(registry, f, indent=4)
    print("Registro aggiornato con successo!")
else:
    print("Nessuna modifica necessaria.")
