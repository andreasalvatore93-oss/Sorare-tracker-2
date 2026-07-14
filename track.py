import json, asyncio, aiohttp, sqlite3, datetime, os

# CONFIGURAZIONE
OPERATION_ID = "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"

def log(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": player['slug'], "rarity": "limited"},
        "extensions": {"operationId": OPERATION_ID}
    }
    headers = {'Cookie': os.environ.get('SORARE_COOKIE', ''), 'x-csrf-token': os.environ.get('SORARE_CSRF', '')}
    
    async with session.post(url, json=payload, headers=headers) as response:
        data = await response.json()
        
        # Dizionario prezzi per anno: {2024: price, 2025: price, ...}
        prices_by_year = {}
        
        def extract(obj):
            if isinstance(obj, dict):
                if obj.get('__typename') == 'TokenPrice':
                    amount = obj.get('amounts', {}).get('wei')
                    year = int(obj.get('card', {}).get('seasonYear', 2026))
                    if amount:
                        price = float(amount) / 1e18
                        if year not in prices_by_year or price < prices_by_year[year]:
                            prices_by_year[year] = price
                for v in obj.values(): extract(v)
            elif isinstance(obj, list):
                for i in obj: extract(i)
        
        extract(data)
        
        # Salvataggio e confronto
        conn = sqlite3.connect('tracker.db')
        conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
        
        for year, price in prices_by_year.items():
            db_id = f"{player['id']}_{year}"
            row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
            
            if row and price < (row[0] * 0.95):
                log(f"🔥 OCCASIONE {year}! {player['slug']} a {price:.4f} ETH")
            
            conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
        
        conn.commit(); conn.close()

async def main():
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__": asyncio.run(main())
