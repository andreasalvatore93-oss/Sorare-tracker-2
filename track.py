import json
import os
import asyncio
import aiohttp
import sqlite3
import datetime

# --- CONFIGURAZIONE ---
OPERATION_ID = "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"
DB_NAME = "tracker.db"
MIN_PRICE_THRESHOLD = 0.20  # Ignora qualsiasi prezzo <= 0.20 EUR
DROP_PERCENTAGE = 0.05      # Notifica se il prezzo scende del 5% o più

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS tracker (id TEXT PRIMARY KEY, price REAL)")
    conn.commit()
    conn.close()

async def fetch_player_data(session, player):
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
    
    async with session.post(url, json=payload, headers=headers) as response:
        return await response.json()

def process_data(data, player_id):
    """
    Analizza il JSON e ritorna un dizionario {anno: prezzo_minimo}
    """
    found_prices = {}

    def recursive_search(obj):
        if not isinstance(obj, dict): return
        
        # Se troviamo un blocco prezzo
        if obj.get('__typename') == 'TokenPrice':
            amounts = obj.get('amounts', {})
            # Recupera prezzo in EUR (o converte se necessario)
            # Priorità: eurCents, poi wei (convertito approssimativo)
            val = None
            if amounts.get('eurCents'):
                val = float(amounts['eurCents']) / 100
            elif amounts.get('wei'):
                val = float(amounts['wei']) / 1e18 * 2500 # Conversione grezza ETH->EUR
            
            if val is not None:
                season = int(obj.get('card', {}).get('seasonYear', 2026))
                
                # Debug log: vediamo cosa trova prima di filtrare
                if val <= MIN_PRICE_THRESHOLD:
                    # log(f"DEBUG: Scartato {val}€ (Sotto soglia)")
                    pass
                else:
                    if season not in found_prices or val < found_prices[season]:
                        found_prices[season] = val
                        log(f"DEBUG: Trovato min per {season}: {val}€")
        
        # Continua la ricerca ricorsiva
        for v in obj.values():
            if isinstance(v, (dict, list)):
                recursive_search(v)
            elif isinstance(v, list):
                for item in v: recursive_search(item)

    recursive_search(data)
    return found_prices

async def check_player(session, player):
    try:
        data = await fetch_player_data(session, player)
        year_prices = process_data(data, player['id'])
        
        if not year_prices:
            log(f"Nessun dato valido trovato per {player['slug']}")
            return

        conn = sqlite3.connect(DB_NAME)
        for year, price in year_prices.items():
            db_id = f"{player['id']}_{year}"
            row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
            
            if row:
                old_price = row[0]
                # Controllo calo del 5%
                if price < (old_price * (1 - DROP_PERCENTAGE)):
                    log(f"🔥 OCCASIONE {year}: {player['slug']} a {price:.2f}€ (Era {old_price:.2f}€)")
            
            # Aggiorna sempre il db con il nuovo minimo rilevato
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
        tasks = [check_player(session, p) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
