import json
import urllib.request

def log(msg):
    print(msg, flush=True)

def check_search():
    log("--- AVVIO RICERCA MBAPPE ---")
    query = """
    query {
      search(term: "Kylian Mbappé") {
        players {
          slug
          displayName
        }
      }
    }
    """
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request('https://api.sorare.com/graphql', data=json.dumps({'query': query}).encode('utf-8'), headers=headers)
    
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        log(f"RISULTATO RICERCA: {res}")

if __name__ == '__main__':
    check_search()
