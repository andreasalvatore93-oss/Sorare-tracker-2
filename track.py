import json
import asyncio
import aiohttp
import sqlite3
import datetime
import os

# CONFIGURAZIONE
OPERATION_ID = "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"
DB_NAME = "tracker.db"

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
    conn.commit()
    conn.close()

async def process_player(session, player):
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": player.get('slug'), "rarity": "limited"},
        "extensions": {"operationId": OPERATION_ID}
    }
    headers = {
        'Cookie': os.environ.get('SORARE_COOKIE', ''),
        'x-csrf-token': os.environ.get('SORARE_CSRF', ''),
        'Content-Type': 'application/json'
    }

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            prices = {'current': float('inf'), 'classic': float('inf')}

            def extract(obj):
                if isinstance(obj, dict):
                    if obj.get('__typename') == 'TokenPrice':
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

            conn = sqlite3.connect(DB_NAME)
            for cat, price in prices.items():
                if price == float('inf'): continue

                db_id = f"{player.get('id')}_{cat}"
                row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()

                if row:
                    old_price = row[0]
                    if price < (old_price * 0.95):
                        log(f"🔥 OCCASIONE {cat.upper()}! {player.get('slug')} a {price:.4f} (Precedente: {old_price:.4f})")
                
                conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
            conn.commit()
            conn.close()
    except Exception as e:
        log(f"ERRORE su {player.get('slug')}: {e}")

async def main():
    init_db()
    if not os.path.exists('players_registry.json'):
        log("ERRORE: players_registry.json non trovato")
        return
    with open('players_registry.json', 'r') as f:
        players = json.load(f)
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[process_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
