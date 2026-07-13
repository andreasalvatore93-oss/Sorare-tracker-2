import urllib.request
import re

def test_scrape_alaba():
    slug = "david-olatukunbo-alaba"
    url = f"https://sorare.com/it/football/players/{slug}"
    print(f"Test connessione a: {url}")
    
    # Mascheriamo la richiesta fingendoci un browser standard
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # Cerchiamo tutti i valori "eurCents" nascosti nel codice
            prices = re.findall(r'"eurCents":(\d+)', html)
            
            if prices:
                valid_prices = [int(p) for p in prices if int(p) > 0]
                if valid_prices:
                    min_price = min(valid_prices) / 100
                    print(f"SUCCESSO! Prezzo minimo trovato: {min_price}€")
                else:
                    print("Trovati campi eurCents, ma tutti a 0.")
            else:
                print("La pagina è stata scaricata, ma non ho trovato la parola chiave dei prezzi.")
                
    except urllib.error.HTTPError as e:
        print(f"BLOCCATO DAL SERVER! Errore: {e.code} - {e.reason} (Probabile blocco Cloudflare)")
    except Exception as e:
        print(f"ERRORE GENERICO: {e}")

test_scrape_alaba()
