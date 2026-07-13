import json
import os

KNOWN_SLUGS = {
    "alaba": "david-olatukunbo-alaba",
    "vallejo": "jesus-vallejo-lazaro",
    "fran-garcia": "francisco-jose-garcia-torres",
    "ceballos": "daniel-ceballos-fernandez",
    "mbappe": "kylian-mbappe-lottin", # <--- AGGIUNTA VIRGOLA
    "brahim": "brahim-abdelkader-diaz"
}

def is_slug_valid(slug):
    import urllib.request
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    HEADERS = {'Content-Type': 'application/json', 'Cookie': os.environ.get('SORARE_COOKIE')}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode()).get('data', {}).get('anyPlayer') is not None
    except: return False

with open('players_registry.json', 'r') as f:
    registry = json.load(f)

updated = False
for p in registry:
    target_slugs = [p['slug'], KNOWN_SLUGS.get(p['id']), f"{p['id']}-real-madrid", f"{p['id']}-2025"]
    
    if not is_slug_valid(p['slug']):
        print(f"Slug errato per {p['id']}: {p['slug']}. Provo tentativi intelligenti...")
        for candidate in target_slugs:
            if candidate and is_slug_valid(candidate):
                print(f"Trovato slug corretto: {candidate}")
                p['slug'] = candidate
                updated = True
                break
        else:
            print(f"ATTENZIONE: Nessuno slug indovinato per {p['id']}.")

if updated:
    with open('players_registry.json', 'w') as f:
        json.dump(registry, f, indent=4)
    print("Registro aggiornato.")
