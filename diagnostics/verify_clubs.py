"""
Verifica dal vivo gli slug ufficiali dei club di UNA O PIU competizioni via
`football { competition(slug: X) { clubs(first: 50) { nodes { slug name } } } }`
-- generalizzazione di verify_bundesliga_clubs.py (che restava fisso su
bundesliga-de/candidati), usata qui per il backlog "Contender limitato a
Austria/Croazia/2.Bundesliga" (slug gia' noti e verificati in produzione via
discovery_fixture.py: austrian-bundesliga, 1-hnl, 2-bundesliga -- serve solo
la lista CLUB di ciascuna competizione per scrivere i discovery_global,
niente da "indovinare" sullo slug competizione stesso).

Script standalone, sola lettura, nessuna scrittura sul repo -- output solo su
stdout (letto dai log della run GitHub Actions).

Uso: COMP_SLUGS="austrian-bundesliga,1-hnl,2-bundesliga" python diagnostics/verify_clubs.py
Richiede SORARE_COOKIE.
"""
import os
import json
import time
import datetime
import requests

APIKEY = os.environ.get('SORARE_APIKEY', '')  # 12/08/2026: alza il tetto di complessita' e di richieste dell'account

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
    print(f"[{ts}] [verify_clubs] {msg}")


def graphql_query(query, variables=None, operation_name=None):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    if APIKEY:
        headers['APIKEY'] = APIKEY
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
query CompetitionClubs($slug: String!, $first: Int!) {
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


def main():
    comp_slugs = [s.strip() for s in os.environ.get('COMP_SLUGS', '').split(',') if s.strip()]
    if not comp_slugs:
        log("ATTENZIONE: COMP_SLUGS vuota, niente da fare.")
        return
    for comp_slug in comp_slugs:
        log(f"Competition slug: '{comp_slug}'")
        data = graphql_query(QUERY, {"slug": comp_slug, "first": 50}, operation_name="CompetitionClubs")
        comp = ((data.get('data') or {}).get('football') or {}).get('competition')
        if not comp:
            log(f"  -> NESSUN DATO per '{comp_slug}'. Risposta: {json.dumps(data, ensure_ascii=False)[:400]}")
            time.sleep(0.5)
            continue
        clubs = (comp.get('clubs') or {}).get('nodes') or []
        log(f"  -> TROVATO: competition.name='{comp.get('name')}' slug='{comp.get('slug')}' -- {len(clubs)} club:")
        for c in clubs:
            log(f"     {c.get('slug')}  ({c.get('name')})")
        time.sleep(0.5)


if __name__ == '__main__':
    main()
