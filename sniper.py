import json
import os
import asyncio
import aiohttp
import datetime
import sqlite3
import urllib.request

# Configurazione credenziali
COOKIES = os.environ.get('SORARE_COOKIE', '').strip()
CSRF_TOKEN = os.environ.get('SORARE_CSRF', '').strip()
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

MIN_PRICE_EUR = 0.1
MIN_L5_SCORE = 0
MIN_DISCOUNT = -1.0

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

async def send_telegram_msg_async(session, message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    await session.post(url, json=payload)

async def main():
    log("Avvio test Strategia 3: Query Standard (senza Operation ID)")
    
    url = 'https://api.sorare.com/graphql'
    
    # Query GraphQL esplicita
    query = """
    query MarketListings($first: Int, $filters: MarketListingsFiltersInput) {
      market {
        marketListings(first: $first, filters: $filters) {
          nodes {
            id
            price
            card {
              slug
              player {
                displayName
                lastFiveSo5AverageScore
              }
            }
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "first": 20,
            "filters": {"cardScarcities": ["LIMITED"]}
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                res_text = await response.text()
                log(f"Risposta ricevuta (primi 500 caratteri): {res_text[:500]}")
                
                res_json = json.loads(res_text)
                if "errors" in res_json:
                    log(f"⚠️ Errore (Strategia 3): {json.dumps(res_json['errors'])}")
                else:
                    log("✅ Query inviata con successo! Controlla i dati sopra.")
        except Exception as e:
            log(f"Errore: {e}")

if __name__ == "__main__":
    asyncio.run(main())
