import json
import urllib.request

def check_simple():
    # Una query che non richiede argomenti, deve restituire un risultato base
    query = "{ __typename }"
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request('https://api.sorare.com/graphql', 
                                 data=json.dumps({'query': query}).encode('utf-8'), 
                                 headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            print(f"RISPOSTA: {response.read().decode()}")
    except Exception as e:
        print(f"ERRORE: {e}")

if __name__ == '__main__':
    check_simple()
