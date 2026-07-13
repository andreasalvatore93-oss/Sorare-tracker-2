import urllib.request
import json
import re

def inspect_page_data():
    slug = "david-olatukunbo-alaba"
    url = f"https://sorare.com/it/football/players/{slug}"
    
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    with urllib.request.urlopen(req) as response:
        html = response.read().decode('utf-8')
        
        # Cerchiamo il blocco __NEXT_DATA__ dove solitamente risiede tutto il JSON della pagina
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        
        if match:
            data = json.loads(match.group(1))
            # Stampiamo solo una parte per vedere la struttura, senza intasare il log
            print("Estratto il JSON di Sorare. Analisi struttura:")
            # Convertiamo in stringa e ne stampiamo i primi 1000 caratteri
            print(str(data)[:1000])
        else:
            print("Blocco __NEXT_DATA__ non trovato.")

inspect_page_data()
