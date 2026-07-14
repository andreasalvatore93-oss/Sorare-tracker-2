import json
import os
import asyncio
import aiohttp
import sqlite3
import datetime

# --- CONFIGURAZIONE ---
DB_NAME = "tracker.db"
# ID aggiornato da te
OPERATION_ID = "React/31bbd1d92597e943052af8044e6e3919aea872718f8662d7a89f64847cde2332"

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
    conn.commit()
    conn.close()

async def check_player(session, player):
    url = 'https://api.sorare.com/graphql'
    
    # Payload con il nuovo ID e i parametri corretti per la ricerca
    payload = {
        "operationName": "CardsQuery",
        "variables": {
            "first": 20, 
            "rarity": ["limited"], 
            "sort": "price_asc", 
            "text": player['slug'].replace('-', ' ')
        },
        "extensions": {
            "operationId": OPERATION_ID
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Cookie': os.environ.get('SORARE_COOKIE', ''),
        'x-csrf-token': os.environ.get('SORARE_CSRF', '')
    }

    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            
            # Percorso standard per 'CardsQuery'
            cards = data.get('data', {}).get('cards', {}).get('nodes', [])
            
            if not cards:
                log(f"Nessuna carta in vendita trovata per {player['slug']}")
                return

            # Dizionario per il minimo dell'anno
            min_prices = {}
            for card in cards:
                # Estrazione prezzo (assumiamo il campo sia 'price')
                price = float(card.get('price', 0))
                year = card.get('seasonYear')
                
                if year and (year not in min_prices or price < min_prices[year]):
                    min_prices[year] = price

            # Confronto con DB
            conn = sqlite3.connect(DB_NAME)
            for year, price in min_prices.items():
                db_id = f"{player['id']}_{year}"
                row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
                
                if row:
                    old_price = row[0]
                    # Alert se scende del 5%
                    if price < (old_price * 0.95):
                        log(f"🔥 OCCASIONE {year}: {player['slug']} a {price:.2f} ETH (Era {old_price:.2f} ETH)")
                    else:
                        log(f"CHECK {year}: {player['slug']} a {price:.2f} ETH")
                else:
                    log(f"NUOVO {year}: {player['slug']} a {price:.2f} ETH")
                
                conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))
            
            conn.commit()
            conn.close()

    except Exception as e:
        log(f"ERRORE su {player['slug']}: {e}")

async def main():
    init_db()
    if not os.path.exists('players_registry.json'):
        log("Errore: players_registry.json non trovato.")
        return
        
    with open('players_registry.json', 'r') as f:
        players = json.load(f)
        
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
