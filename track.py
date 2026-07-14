import json, os, asyncio, aiohttp, sqlite3, datetime

# Configurazione
DB_NAME = "tracker.db"
MIN_THRESHOLD = 0.20  # Ignora tutto ciò che è <= 0.20€

def log(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
    conn.commit(); conn.close()

def extract_and_filter(data):
    # Dizionario che terrà il prezzo minimo per ogni anno: {2025: 4.50, 2024: 3.20}
    found_min_prices = {}

    def search(obj):
        if isinstance(obj, dict):
            if obj.get('__typename') == 'TokenPrice':
                amounts = obj.get('amounts', {})
                # Estrai prezzo (priorità eurCents)
                price_val = None
                if amounts.get('eurCents'): 
                    price_val = float(amounts['eurCents']) / 100
                
                # Applica filtro soglia
                if price_val and price_val > MIN_THRESHOLD:
                    year = int(obj.get('card', {}).get('seasonYear', 2026))
                    # Mantiene solo il più basso per quell'anno
                    if year not in found_min_prices or price_val < found_min_prices[year]:
                        found_min_prices[year] = price_val
            
            for v in obj.values(): search(v)
        elif isinstance(obj, list):
            for i in obj: search(i)

    search(data)
    return found_min_prices

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": player['slug'], "rarity": "limited"},
        "extensions": {"operationId": "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': os.environ.get('SORARE_COOKIE', ''), 'x-csrf-token': os.environ.get('SORARE_CSRF', '')}

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            prices_found = extract_and_filter(data)
            
            if not prices_found:
                log(f"Nessun dato valido (sopra 0.20€) per {player['slug']}")
                return

            conn = sqlite3.connect(DB_NAME)
            for year, current_price in prices_found.items():
                db_id = f"{player['id']}_{year}"
                row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
                
                if row:
                    old_price = row[0]
                    # Log di confronto
                    if current_price < (old_price * 0.95):
                        log(f"🔥 OCCASIONE {year}: {player['slug']} a {current_price:.2f}€ (Era {old_price:.2f}€)")
                    else:
                        log(f"CHECK {year}: {player['slug']} a {current_price:.2f}€ (OK)")
                else:
                    log(f"NUOVO {year}: {player['slug']} registrato a {current_price:.2f}€")
                
                conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, current_price))
            
            conn.commit(); conn.close()
    except Exception as e:
        log(f"ERRORE su {player['slug']}: {e}")

async def main():
    init_db()
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__": asyncio.run(main())
