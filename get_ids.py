import json
import urllib.request
import os

# Carichiamo il registro appena creato
with open('players_registry.json', 'r') as f:
    registry = json.load(f)

# Configurazione API (le stesse che usi in track.py)
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
        
        # Estraiamo l'ID univoco dal campo "id" che Sorare restituisce
        player_info = data.get('data', {}).get('anyPlayer')
        if player_info:
            return player_info.get('id')
    except Exception as e:
        print(f"Errore nel recupero ID per {slug}: {e}")
    return None

# Cicliamo tutti i giocatori e aggiorniamo il registro
for p in registry:
    if not p['sorare_id']: # Se l'ID è ancora vuoto
        print(f"Recupero ID per {p['slug']}...")
        uid = get_sorare_id(p['slug'])
        if uid:
            p['sorare_id'] = uid
            print(f"-> Trovato: {uid}")
        else:
            print(f"-> Fallito!")

# Salviamo il registro aggiornato
with open('players_registry.json', 'w') as f:
    json.dump(registry, f, indent=4)

print("Passo 2 completato: 'players_registry.json' ora contiene gli ID univoci.")
