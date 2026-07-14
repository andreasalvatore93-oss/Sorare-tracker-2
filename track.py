import json, os, asyncio, aiohttp, datetime, sqlite3

# Configurazione
OPERATION_ID = "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"
MIN_THRESHOLD = 0.20  # Ignora prezzi <= 0.20 EUR
DB_NAME = "tracker.db"

def log(msg): print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
    conn.commit(); conn.close()

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": player['slug'], "rarity": "limited"},
        "extensions": {"operationId": OPERATION_ID}
    }
    headers = {
        'Content-Type': 'application/json',
        'Cookie': os.environ.get('SORARE_COOKIE', ''),
        'x-csrf-token': os.environ.get('SORARE_CSRF', '')
    }

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            
            # Dizionario per tenere il prezzo minimo per ogni anno trovato
            year_prices = {}

            def extract(obj):
                if isinstance(obj, dict):
                    if obj.get('__typename') == 'TokenPrice':
                        amounts = obj.get('amounts', {})
                        # Priorità EUR, poi USD convertito
                        price_val = None
                        if amounts.get('eurCents'): price_val = float(amounts['eurCents']) / 100
                        elif amounts.get('usdCents'): price_val = float(amounts['usdCents']) / 100 * 0.92
                        
                        if price_val and price_val > MIN_THRESHOLD:
                            year = int(obj.get('card', {}).get('seasonYear', 2026))
                            if year not in year_prices or price_val < year_prices[year]:
                                year_prices[year] = price_val
                    for v in obj.values(): extract(v)
                elif isinstance(obj, list):
                    for i in obj: extract(i)

            extract(data)

            # Verifica e aggiornamento DB
            conn = sqlite3.connect(DB_NAME)
            for year, price in year_prices.items():
                db_id = f"{player['id']}_{year}"
                row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
                
                if row:
                    old_price = row[0]
                    # Notifica se il nuovo prezzo è inferiore del 5% rispetto al salvato
                    if price < (old_price * 0.95):
                        log(f"🔥 OCCASIONE {year}: {player['slug']} a {price:.2f}€ (Precedente: {old_price:.2f}€)")
                
                # Aggiorna sempre con il minimo trovato per mantenere il floor aggiornato
                conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
            conn.commit(); conn.close()
            
    except Exception as e:
        log(f"ERRORE su {player['slug']}: {e}")

async def main():
    init_db()
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
