import json, os, asyncio, aiohttp, sqlite3, datetime

DB_NAME = "tracker.db"
OPERATION_ID = "React/31bbd1d92597e943052af8044e6e3919aea872718f8662d7a89f64847cde2332"

# --- IMPOSTATO A 3 (RICERCA GLOBALE) ---
SEARCH_METHOD = 3 

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    
    # Payload configurabile
    variables = {
        "first": 5, # Limitiamo a 5 per test
        "sort": "price_asc", 
        "rarity": ["limited"],
        "editableLists": False, 
        "onlyPrimary": False, 
        "slugs": []
    }
    
    # Metodo 3 ignora i filtri specifici: vede tutto ciò che c'è sul mercato
    
    payload = {"operationName": "CardsQuery", "variables": variables, "extensions": {"operationId": OPERATION_ID}}
    headers = {'Content-Type': 'application/json', 'Cookie': os.environ.get('SORARE_COOKIE', '')}

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            cards = data.get('data', {}).get('cards', {}).get('nodes', [])
            
            if not cards:
                log(f"FALLITO: Nessuna carta trovata sul mercato globale. Controlla il Cookie.")
            else:
                log(f"SUCCESSO! Ho trovato {len(cards)} carte sul mercato.")
                for c in cards:
                    log(f"-> Esempio: {c.get('slug')} a {c.get('price')} ETH")
    except Exception as e:
        log(f"ERRORE: {e}")

async def main():
    # Eseguiamo una sola volta, non serve il file json per il test globale
    async with aiohttp.ClientSession() as session:
        await check_player(session, {"id": "test", "slug": "test"})

if __name__ == "__main__":
    asyncio.run(main())
