import json
import urllib.request
import os

with open('players_registry.json', 'r') as f:
    registry = json.load(f)

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
HEADERS = {
    'Content-Type': 'application/json',
    'Cookie': COOKIES,
    'x-csrf-token': CSRF_TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_real_slug(name):
    url = 'https://api.sorare.com/graphql'
    # Utilizziamo una struttura standard che il server accetta per la ricerca
    payload = {
        "operationName": "SearchPlayers",
        "variables": {"query": name},
        "query": "query SearchPlayers($query: String!) { searchPlayers(query: $query) { nodes { slug } } }"
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=HEADERS)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        nodes = data.get('data', {}).get('searchPlayers', {}).get('nodes', [])
        return nodes[0]['slug'] if nodes else None

def is_slug_valid(slug):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get('data', {}).get('anyPlayer') is not None
    except:
        return False

updated = False
for p in registry:
    if not is_slug_valid(p['slug']):
        print(f"Slug errato per {p['id']}: {p['slug']}. Cerco quello corretto...")
        correct_slug = get_real_slug(p['id'])
        if correct_slug and correct_slug != p['slug']:
            print(f"Aggiornato: {p['slug']} -> {correct_slug}")
            p['slug'] = correct_slug
            updated = True

if updated:
    with open('players_registry.json', 'w') as f:
        json.dump(registry, f, indent=4)
    print("Registro aggiornato.")
else:
    print("Nessuna modifica necessaria.")
