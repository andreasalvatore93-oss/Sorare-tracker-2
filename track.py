import aiohttp
import asyncio
import os

async def debug_sorare():
    url = 'https://api.sorare.com/graphql'
    # ID confermato
    OPERATION_ID = "React/31bbd1d92597e943052af8044e6e3919aea872718f8662d7a89f64847cde2332"
    
    # Payload senza filtri restrittivi
    payload = {
        "operationName": "CardsQuery",
        "variables": {
            "first": 5, 
            "sort": "price_asc"
        },
        "extensions": {
            "operationId": OPERATION_ID
        }
    }
    
    # Inserisci qui il tuo cookie attuale
    headers = {
        'Content-Type': 'application/json',
        'Cookie': 'INSERISCI_QUI_IL_TUO_COOKIE'
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            status = resp.status
            data = await resp.json()
            
            print(f"Status Code: {status}")
            # Estraiamo le carte se esistono
            cards = data.get('data', {}).get('cards', {}).get('nodes', [])
            
            if cards:
                print(f"CONNESSIONE OK! Trovate {len(cards)} carte.")
                print(f"Esempio carta: {cards[0].get('slug')}")
            else:
                print(f"DEBUG - Risposta server: {data}")

if __name__ == "__main__":
    asyncio.run(debug_sorare())
