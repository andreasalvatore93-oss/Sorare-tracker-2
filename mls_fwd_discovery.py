"""
MLS Forward Discovery

Scopre TUTTI gli slug giocatore (deduplicati) delle carte possedute da
'crowss' che sono: rarity=limited, posizione=Forward, in_season_eligible=true,
lega attiva MLS (active_competitions:mlspa). Filtro applicato lato server
(refinements + advancedFilters), non dopo il fetch -- query leggera, nessun
campo pesante richiesto.

Basato sulla query reale 'UserCardsSearchQuery' osservata via DevTools
(24/07): stesso schema searchCards di my_cards_underpriced.py/track.py, ma
con refinements su position/in_season_eligible + advancedFilters per la lega.

Output: mls_fwd_discovery/player_slugs.json -- lista JSON di slug univoci,
usata dal job 'discover' in test_multi_fwd.yml per generare dinamicamente la
matrix del job 'predict'.
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
USER_SLUG = 'crowss'
OUTPUT_DIR = 'mls_fwd_discovery'
PAGE_SIZE = 20  # stesso valore osservato nella query reale via DevTools

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [mls_fwd_discovery] {msg}")


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
                log(f"[ERRORE HTTP {resp.status_code}] body (primi 1500 char): {resp.text[:1500]}")
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


# NOTA: user.id (uuid) e' richiesto dentro advancedFilters nella query reale
# osservata via DevTools. Lo recuperiamo con una prima query leggera, invece
# di hardcodarlo (piu' robusto se mai cambiasse).
def get_user_uuid(user_slug):
    query = """
    query GetUserId($slug: String!) {
      user(slug: $slug) {
        id
      }
    }
    """
    data = graphql_query(query, {"slug": user_slug}, operation_name="GetUserId")
    user_id = ((data.get('data') or {}).get('user') or {}).get('id') or ''
    # L'id torna nel formato "User:<uuid>" -- advancedFilters vuole solo l'uuid.
    if ':' in user_id:
        user_id = user_id.split(':', 1)[1]
    return user_id


def discover_mls_forwards_in_season(user_slug=USER_SLUG, max_pages=50):
    """Ritorna la lista deduplicata di slug giocatore (Forward, in_season,
    lega MLS) posseduti da user_slug. Filtro completamente lato server."""
    user_uuid = get_user_uuid(user_slug)
    if not user_uuid:
        log("Impossibile ottenere l'uuid utente, interrompo.")
        return []

    advanced_filters = (
        f"user.id:{user_uuid} AND sport:football AND (active_competitions:mlspa) "
        f"AND NOT sealed=1 AND NOT rarity:custom_series"
    )

    query = """
    query MlsForwardDiscovery($userSlug: String!, $page: Int!, $pageSize: Int!,
                               $advancedFilters: String, $refinements: [SearchRefinementInput!]) {
      user(slug: $userSlug) {
        searchCards(
          rarity: limited
          sport: FOOTBALL
          query: ""
          page: $page
          pageSize: $pageSize
          advancedFilters: $advancedFilters
          refinements: $refinements
        ) {
          hits {
            slug
            anyPlayer { slug }
          }
          nbHits
          nbPages
        }
      }
    }
    """

    refinements = [
        {"field": "position", "operator": "EQUAL", "values": [{"stringValue": "Forward"}]},
        {"field": "in_season_eligible", "operator": "EQUAL", "values": [{"stringValue": "true"}]},
    ]

    player_slugs = set()
    card_count = 0
    page = 1
    while page <= max_pages:
        data = graphql_query(query, {
            "userSlug": user_slug,
            "page": page,
            "pageSize": PAGE_SIZE,
            "advancedFilters": advanced_filters,
            "refinements": refinements,
        }, operation_name="MlsForwardDiscovery")

        search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
        hits = search.get('hits') or []
        if page == 1:
            log(f"Totale carte Forward/in_season/MLS trovate: {search.get('nbHits')} "
                f"({search.get('nbPages')} pagine)")
        if not hits:
            break

        for h in hits:
            card_count += 1
            p_slug = (h.get('anyPlayer') or {}).get('slug')
            if p_slug:
                player_slugs.add(p_slug)

        nb_pages = search.get('nbPages') or 1
        if page >= nb_pages:
            break
        page += 1
        time.sleep(0.3)

    log(f"Carte scansionate: {card_count} | Giocatori unici (dedup): {len(player_slugs)}")
    return sorted(player_slugs)


def main():
    log("Avvio discovery attaccanti MLS in_season...")
    slugs = discover_mls_forwards_in_season()

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    out_path = os.path.join(OUTPUT_DIR, 'player_slugs.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f, ensure_ascii=False, indent=2)

    log(f"Salvati {len(slugs)} slug in {out_path}: {slugs}")

    # Per il job GitHub Actions successivo (matrix dinamica), serve anche
    # l'output in formato leggibile da GITHUB_OUTPUT (JSON su singola riga).
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"player_slugs={json.dumps(slugs)}\n")


if __name__ == '__main__':
    main()
