import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import urllib.request
import sys

# --- Configurazione ---
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

semaphore = asyncio.Semaphore(5)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def get_eth_rate():
    try:
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur", timeout=5) as r:
            data = json.loads(r.read().decode())
            return float(data['ethereum']['eur'])
    except:
        return 3000.0

def get_prices_by_season(data, eth_rate):
    prices = {'current': None, 'classic': None}
    
    token_prices = []
    def find_token_prices(obj):
        if isinstance(obj, dict):
            if obj.get('__typename') == 'TokenPrice':
                token_prices.append(obj)
            for v in obj.values():
                find_token_prices(v)
        elif isinstance(obj, list):
            for item in obj:
                find_token_prices(item)
    
    find_token_prices(data)
    
    for tp in token_prices:
        amounts = tp.get('amounts', {})
        card = tp.get('card', {})
        deal = tp.get('deal', {})
        
        # --- DEBUG AGGRESSIVO: Vediamo cosa c'è dentro ogni deal ---
        log(f"DEBUG: Found TokenPrice | Buyer: {deal.get('buyer')} | Deal: {json.dumps(deal)[:100]}")
        
        price_val_eur = 0
        if amounts.get('wei'):
            price_val_eur = (float(amounts['wei']) / 1e18) * eth_rate
        elif amounts.get('eurCents'):
            price_val_eur = float(amounts['eurCents']) / 100
            
        if price_val_eur > 0:
            year = int(card.get('seasonYear', 2026))
            cat = 'current' if year >= 2026 else 'classic'
            
            # Senza filtri, registriamo il minimo che troviamo
            if not prices[cat] or price_val_eur < prices[cat]['price_in_eur']:
                prices[cat] = {'price': price_val_eur, 'currency': 'EUR', 'price_in_eur': price_val_eur}
                
    return prices

async def check_player(session, player_data, eth_rate):
    slug = player_data.get('slug')
    url = 'https://api.sorare.com/graphql'
    
    payload = {
        "operationName": "LazyPriceGraphQuery",
        "variables": {"playerSlug": slug, "rarity": "limited"},
        "extensions": {"operationId": "React/3a17d0b9e886a8c514ba3352073a63a87b7d270b4397b2e10eeb0276d54ceb6b"}
    }
    
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'x-csrf-token': CSRF_TOKEN, 'User-Agent': 'Mozilla/5.0'}
    
    async with semaphore:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                data = await response.json()
                season_prices = get_prices_by_season(data, eth_rate)
                log(f"Analisi completata. Risultati minimi trovati (senza filtri): {season_prices}")
        except Exception as e:
            log(f"ERRORE: {e}")

async def main():
    log("Inizio esecuzione...")
    eth_rate = get_eth_rate()
    with open('players_registry.json', 'r') as f: 
        players = json.load(f)
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_player(session, p, eth_rate) for p in players]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
