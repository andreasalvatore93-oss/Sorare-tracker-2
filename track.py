print("--- SCRIPT AVVIATO ---")
import json
import urllib.request

def check_sorare():
    lista_giocatori = [
        {"slug": "kylian-mbappe", "nome": "Kylian Mbappé", "tipo": "in_season"},
    ]
        
    for target in lista_giocatori:
        slug = target["slug"]
        tipo = target["tipo"]
        in_season_bool = "true" if tipo == "in_season" else "false"
        
        query = f"""
        query {{
          players(slugs: ["{slug}"]) {{
            ... on Player {{
              lowestPriceAnyCard(rarities: [LIMITED], inSeason: {in_season_bool}) {{
                liveSingleSaleOffer {{
                  receiverSide {{
                    amounts {{
                      eurCents
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        
        req = urllib.request.Request('https://api.sorare.com/graphql', 
                                     data=json.dumps({'query': query}).encode('utf-8'), 
                                     headers={'Content-Type': 'application/json'})
        
        try:
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                # --- QUESTA RIGA È IL DEBUG ---
                print(f"DEBUG RISPOSTA PER {slug}: {res}")
                # ------------------------------
        except Exception as e:
            print(f"Errore query: {e}")
    print("--- SCRIPT TERMINATO ---")

if __name__ == '__main__':
    check_sorare()
