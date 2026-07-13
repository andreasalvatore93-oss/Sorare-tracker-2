import json
import urllib.request
import os

# Recupera i dati sensibili dalle variabili d'ambiente (GitHub Secrets)
cookies = os.environ.get('SORARE_COOKIE')
csrf_token = os.environ.get('SORARE_CSRF')

def main():
    if not cookies or not csrf_token:
        print("Errore: Credenziali mancanti! Verifica che SORARE_COOKIE e SORARE_CSRF siano impostati su GitHub.")
        return

    url = 'https://api.sorare.com/graphql'
    
    # Payload basato sulla tua richiesta cURL
    payload = {
        "operationName": "AnyPlayerLayoutQuery",
        "variables": {
            "onlyPrimary": False,
            "slug": "kylian-mbappe-lottin"
        },
        "extensions": {
            "operationId": "React/a809e5dae931764014e854f4ba174c338195ee3fe2cf12bc971687941c0fe40d"
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Cookie': cookies,
        'x-csrf-token': csrf_token,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com'
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Status Code: {response.getcode()}")
            raw_data = response.read().decode()
            data = json.loads(raw_data)
            print("--- RISPOSTA DAL SERVER ---")
            print(json.dumps(data, indent=2))
            
    except Exception as e:
        print(f"Errore durante la richiesta: {e}")

if __name__ == '__main__':
    main()
