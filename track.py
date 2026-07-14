import json, os, asyncio, aiohttp, sqlite3, datetime

DB_NAME = "tracker.db"
OPERATION_ID = "React/31bbd1d92597e943052af8044e6e3919aea872718f8662d7a89f64847cde2332"

# --- SCEGLI LA TUA ALTERNATIVA (1, 2 o 3) ---
SEARCH_METHOD = 1 

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    
    # Payload configurabile in base all'alternativa scelta
    variables = {
        "first": 20, "sort": "price_asc", "rarity": ["limited"],
        "editableLists": False, "onlyPrimary": False, "slugs": []
    }
    
    if SEARCH_METHOD == 1: # Metodo Slug (ID Univoco)
        variables["slugs"] = [player['slug']]
    elif SEARCH_METHOD == 2: # Metodo Name (Testuale)
        variables["text"] = player['slug'].replace('-', ' ').title()
    # Se SEARCH_METHOD == 3 non aggiungiamo nulla, fa una ricerca globale

    payload = {"operationName": "CardsQuery", "variables": variables, "extensions": {"operationId": OPERATION_ID}}
    headers = {'Content-Type': 'application/json', 'Cookie': os.environ.get('SORARE_COOKIE', '')}

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            cards = data.get('data', {}).get('cards', {}).get('nodes', [])
            
            if not cards:
                log(f"Nessuna carta trovata per {player['slug']} (Metodo {SEARCH_METHOD})")
                return

            conn = sqlite3.connect(DB_NAME)
            for card in cards:
                price = float(card.get('price', 0))
                year = card.get('seasonYear')
                log(f"TROVATO {year}: {player['slug']} a {price:.2f} ETH")
            conn.close()
    except Exception as e:
        log(f"ERRORE su {player['slug']}: {e}")

async def main():
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
