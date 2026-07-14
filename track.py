import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3

# [Configurazione invariata...]
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')

async def check_player(session, player_data, eth_rate):
    slug = player_data.get('slug')
    url = 'https://api.sorare.com/graphql'
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {"onlyPrimary": False, "slug": slug},
        "extensions": {"operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"}
    }
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    async with session.post(url, json=payload, headers=headers) as response:
        data = await response.json()
        
        # --- DEBUG: SALVA IL JSON COMPLETO ---
        with open(f"debug_{slug}.json", "w") as f:
            json.dump(data, f, indent=4)
        print(f"DEBUG: File debug_{slug}.json creato.", flush=True)
        
        # ... resto del codice invariato ...
