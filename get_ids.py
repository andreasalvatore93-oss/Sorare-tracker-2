import json
import urllib.request
import os

# Carichiamo il registro
with open('players_registry.json', 'r') as f:
    registry = json.load(f)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

def get_sorare_id(slug):
    url = 'https://api.sorare.com/graphql'
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
        
        player_info = data.get('data', {}).get('anyPlayer')
        if player_info:
            return player_info.get('id')
        else:
            # Qui vediamo esattamente cosa risponde Sorare se lo slug è sbagliato
            print(f"DEBUG: Nessun giocatore trovato per lo slug '{slug}'. Risposta server: {data}")
            return None
    except Exception as e:
        print(f"DEBUG: Errore di connessione per {slug}: {e}")
        return None

# Ciclo di aggiornamento
for p in registry:
    if not p.get('sorare_id'):
        print(f"Tentativo recupero ID per {p['slug']}...")
        uid = get_sorare_id(p['slug'])
        if uid:
            p['sorare_id'] = uid
            print(f"-> Trovato: {uid}")
        else:
            print(f"-> NON TROVATO. Slug errato o API bloccata.")

with open('players_registry.json', 'w') as f:
    json.dump(registry, f, indent=4)
