import json, asyncio, aiohttp, sqlite3, datetime, os

def log(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

# Inizializza DB
conn = sqlite3.connect('tracker.db')
conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
conn.close()

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": player['slug'], "rarity": "limited"},
        "extensions": {"operationId": "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"}
    }
    headers = {'Cookie': os.environ.get('SORARE_COOKIE'), 'x-csrf-token': os.environ.get('SORARE_CSRF')}
    
    async with session.post(url, json=payload, headers=headers) as response:
        data = await response.json()
        
        # Estrazione dati (ricorsiva per sicurezza)
        prices = {'current': float('inf'), 'classic': float('inf')}
        
        def extract(obj):
            if isinstance(obj, dict):
                if obj.get('__typename') == 'TokenPrice':
                    deal = obj.get('deal', {})
                    # Filtro: Ignoriamo tutto ciò che ha un compratore
                    if deal.get('buyer') is None:
                        amount = obj.get('amounts', {}).get('wei')
                        if amount:
                            price = float(amount) / 1e18
                            year = int(obj.get('card', {}).get('seasonYear', 2026))
                            cat = 'current' if year >= 2026 else 'classic'
                            if price < prices[cat]: prices[cat] = price
                for v in obj.values(): extract(v)
            elif isinstance(obj, list):
                for i in obj: extract(i)
        
        extract(data)
        
        # Confronto e Notifica
        conn = sqlite3.connect('tracker.db')
        for cat, price in prices.items():
            if price == float('inf'): continue
            
            db_id = f"{player['id']}_{cat}"
            row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
            
            if row:
                old_price = row[0]
                if price < (old_price * 0.95):
                    log(f"🔥 {cat.upper()} CALO 5%! {player['slug']} a {price:.4f} (Precedente: {old_price:.4f})")
            
            conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
        conn.commit()
        conn.close()

async def main():
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
