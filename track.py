import json
import os
import urllib.request
import sys

def log(msg):
    print(msg, flush=True)

log("--- SCRIPT AVVIATO E FORZATO A SCRIVERE ---")

def check_sorare():
    lista_giocatori = [
        {"slug": "kylian-mbappe", "nome": "Kylian Mbappé", "tipo": "in_season"},
    ]
    
    for target in lista_giocatori:
        slug = target["slug"]
        in_season_bool = "true" if target["tipo"] == "in_season" else "false"
        
        # Query semplificata per debug
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            slug
          }}
        }}
        """
        
        try:
            req = urllib.request.Request('https://api.sorare.com/graphql', data=json.dumps({'query': query}).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                
                # SE NON TROVIAMO GIOCATORI, STAMPIAMO TUTTA LA RISPOSTA GREZZA
                if not res.get('data', {}).get('players'):
                    log(f"DEBUG - RISPOSTA GREZZA PER {slug}: {res}")
                else:
                    log(f"SUCCESSO - GIOCATORE TROVATO: {res}")
        except Exception as e:
            log(f"Errore query per {slug}: {e}")
            
    log("--- SCRIPT TERMINATO ---")

if __name__ == '__main__':
    check_sorare()
