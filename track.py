import json, asyncio, aiohttp, sqlite3, datetime, os

def log(message): print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def check_db(db_id):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute("SELECT price FROM tracker WHERE id=?", (db_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_db(db_id, price):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
    conn.commit()
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
        
        # Estrazione offerta
        token_prices = []
        def find_tokens(obj):
            if isinstance(obj, dict):
                if obj.get('__typename') == 'TokenPrice': token_prices.append(obj)
                for v in obj.values(): find_tokens(v)
            elif isinstance(obj, list):
                for item in obj: find_tokens(item)
        
        find_tokens(data)
        
        for tp in token_prices:
            deal = tp.get('deal', {})
            # FILTRO: Solo offerte senza acquirente
            if deal.get('buyer') is not None: continue
            
            # Calcolo Prezzo
            amounts = tp.get('amounts', {})
            price = float(amounts.get('wei', 0)) / 1e18
            if price == 0: continue
            
            # Categoria
            year = int(tp.get('card', {}).get('seasonYear', 2026))
            cat = 'current' if year >= 2026 else 'classic'
            
            # Controllo 5%
            old_price = check_db(f"{player['id']}_{cat}")
            if old_price and price < (old_price * 0.95):
                log(f"🔥 OCCASIONE {cat.upper()}! {player['slug']} a {price:.4f} ETH (Precedente: {old_price:.4f})")
            
            update_db(f"{player['id']}_{cat}", price)

async def main():
    if not os.path.exists('players_registry.json'): return
    with open('players_registry.json', 'r') as f: players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
