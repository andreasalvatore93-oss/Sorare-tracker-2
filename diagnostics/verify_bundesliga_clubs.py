"""
Verifica dal vivo gli slug ufficiali dei club Bundesliga (Germania) via
`football { competition(slug: "bundesliga-de") { clubs(first: 50) { nodes {
slug name } } } }` -- stesso pattern gia' usato per K League (26/07, vedi
formazione_kleague/discovery/kleague_gk_discovery_global.py). Script
standalone, sola lettura, nessuna scrittura sul repo -- output solo su
stdout (letto dai log della run GitHub Actions).

Uso: python diagnostics/verify_bundesliga_clubs.py
Richiede SORARE_COOKIE.
"""
import os
import json
import time
import datetime
import requests

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [verify_bundesliga_clubs] {msg}")


def graphql_query(query, variables=None, operation_name=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    payload = {'query': query, 'variables': variables or {}}
    if operation_name:
        payload['operationName'] = operation_name

    backoff = 1.0
    for attempt in range(5):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                sleep_s = float(retry_after) if retry_after else backoff
                log(f"[429] tentativo {attempt+1}/5, attesa {sleep_s:.1f}s")
                time.sleep(sleep_s)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                log(f"[ERRORE HTTP {resp.status_code}] tentativo {attempt+1}/5, body (primi 1500 char): {resp.text[:1500]}")
                if attempt < 4:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return {}
            data = resp.json()
            if data.get('errors'):
                log(f"[ERRORE GraphQL] {json.dumps(data['errors'], ensure_ascii=False)[:1500]}")
            return data
        except Exception as e:
            log(f"[ECCEZIONE] {e}")
            time.sleep(backoff)
            backoff *= 2
    return {}


QUERY = """
query BundesligaClubs($slug: String!, $first: Int!) {
  football {
    competition(slug: $slug) {
      slug
      name
      clubs(first: $first) {
        nodes {
          slug
          name
        }
      }
    }
  }
}
"""

# Candidati di slug per la competizione tedesca -- proviamo in ordine finche'
# uno non risponde con dati validi (mai indovinare UN SOLO slug e fermarsi
# li' se torna vuoto, potrebbe essere lo slug sbagliato non l'assenza di dati).
CANDIDATE_SLUGS = ['bundesliga-de', 'bundesliga', '1-bundesliga', 'bundesliga-1-de']


def main():
    for comp_slug in CANDIDATE_SLUGS:
        log(f"Provo competition slug: '{comp_slug}'")
        data = graphql_query(QUERY, {"slug": comp_slug, "first": 50}, operation_name="BundesligaClubs")
        comp = ((data.get('data') or {}).get('football') or {}).get('competition')
        if not comp:
            log(f"  -> nessun dato per '{comp_slug}'. Risposta: {json.dumps(data, ensure_ascii=False)[:400]}")
            time.sleep(0.5)
            continue
        clubs = (comp.get('clubs') or {}).get('nodes') or []
        log(f"  -> TROVATO: competition.name='{comp.get('name')}' slug='{comp.get('slug')}' -- {len(clubs)} club:")
        for c in clubs:
            log(f"     {c.get('slug')}  ({c.get('name')})")
        if clubs:
            log("RISULTATO UTILE TROVATO, mi fermo qui.")
            return
        time.sleep(0.5)
    log("ATTENZIONE: nessuno slug candidato ha restituito club. Serve investigare lo schema/slug corretto.")


if __name__ == '__main__':
    main()
