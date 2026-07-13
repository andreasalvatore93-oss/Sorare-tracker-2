import json
import os
import urllib.request

def check_sorare():
    with open('config.json', 'r') as f:
        targets = json.load(f)
    
    # Se il JSON è un singolo blocco e non una lista, lo converte al volo
    if isinstance(targets, dict):
        targets = [targets]
        
    for target in targets:
        # Riconosce automaticamente se hai scritto solo il nome o l'intero blocco dati
        slug = target if isinstance(target, str) else target.get('slug')
        
        if not slug:
            continue
            
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            slug
            name
          }}
        }}
        """
        
        req = urllib.request.Request(
            'https://api.sorare.com/graphql',
            data=json.dumps({'query': query}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'APIKEY': ''}
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                print(f"Controllo API riuscito per {slug}: {data}")
        except Exception as e:
            print(f"Errore durante l'esecuzione per {slug}: {e}")

if __name__ == '__main__':
    check_sorare()
