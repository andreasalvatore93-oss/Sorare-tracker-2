import json
import os
import asyncio
import aiohttp
import sqlite3
import datetime

# --- CONFIGURAZIONE ---
DB_NAME = "tracker.db"
# ID estratto dalla tua richiesta di rete
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

    # Payload CORRETTO: include tutte le variabili obbligatorie per evitare l'errore 400
    payload = {
        "operationName": "CardsQuery",
        "variables": {
            "first": 20,
            "sort": "price_asc",
            "rarity": ["limited"],
            "editableLists": False,
            "onlyPrimary": False,
            "slugs": [],
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

            # Verifica se il server ha risposto con errori
            if 'errors' in data:
                log(f"ERRORE API su {player['slug']}: {data['errors']}")
                return

            # Percorso standard per 'CardsQuery'
            cards = data.get('data', {}).get('cards', {}).get('nodes', [])

            if not cards:
                log(f"Nessuna carta trovata per {player['slug']}")
                return

            # Elaborazione e confronto
            conn = sqlite3.connect(DB_NAME)
            for card in cards:
                price = float(card.get('price', 0))
                year = card.get('seasonYear')
                db_id = f"{player['id']}_{year}"

                # Logica di notifica
                row = conn.execute("SELECT price FROM tracker WHERE id=?", (db_id,)).fetchone()
                if row:
                    if price < (row[0] * 0.95):
                        log(f"🔥 OCCASIONE {year}: {player['slug']} a {price:.2f} ETH")
                    else:
                        log(f"CHECK {year}: {player['slug']} a {price:.2f} ETH")
                else:
                    log(f"NUOVO {year}: {player['slug']} a {price:.2f} ETH")

                conn.execute("INSERT OR REPLACE INTO tracker (id, price) VALUES (?, ?)", (db_id, price))

            conn.commit()
            conn.close()

    except Exception as e:
        log(f"ERRORE di connessione su {player['slug']}: {e}")

async def main():
    init_db()
    # Verifica esistenza file giocatori
    if not os.path.exists('players_registry.json'):
        log("File players_registry.json mancante.")
        return

    with open('players_registry.json', 'r') as f:
        players = json.load(f)

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[check_player(session, p) for p in players])

if __name__ == "__main__":
    asyncio.run(main())
