"""
MLS Goalkeeper Discovery

Scopre TUTTI gli slug giocatore (deduplicati) delle carte possedute da
'crowss' che sono: rarity=limited, posizione=Goalkeeper, in_season_eligible=true,
lega attiva MLS (active_competitions:mlspa). Filtro applicato lato server
(refinements + advancedFilters), non dopo il fetch -- query leggera, nessun
campo pesante richiesto.

Basato sulla query reale 'UserCardsSearchQuery' osservata via DevTools
(24/07): stesso schema searchCards di my_cards_underpriced.py/track.py, ma
con refinements su position/in_season_eligible + advancedFilters per la lega.

Output: mls_gk_discovery/player_slugs.json -- lista JSON di slug univoci,
usata dal job 'discover' in test_mid.yml per generare dinamicamente la
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
OUTPUT_DIR = 'mls_gk_discovery'
PAGE_SIZE = 20  # stesso valore osservato nella query reale via DevTools

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [mls_gk_discovery] {msg}")


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


def discover_mls_goalkeepers_all(user_slug=USER_SLUG, max_pages=50):
    """Ritorna la lista deduplicata di slug giocatore (Goalkeeper, lega MLS)
    posseduti da user_slug, SIA in_season CHE classic (due passate separate
    sullo stesso filtro server-side in_season_eligible=true/false, cosi' da
    coprire l'intera collezione posseduta, non solo le carte in_season)."""
    user_uuid = get_user_uuid(user_slug)
    if not user_uuid:
        log("Impossibile ottenere l'uuid utente, interrompo.")
        return [], {}

    advanced_filters = (
        f"user.id:{user_uuid} AND sport:football AND (active_competitions:mlspa) "
        f"AND NOT sealed=1 AND NOT rarity:custom_series"
    )

    query = """
    query MlsGoalkeeperDiscovery($userSlug: String!, $page: Int!, $pageSize: Int!,
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

    # slug -> {'in_season': n, 'classic': n} -- copie possedute per tipo di carta.
    player_card_counts = {}
    total_card_count = 0

    for in_season_value, type_key in (("true", "in_season"), ("false", "classic")):
        refinements = [
            {"field": "position", "operator": "EQUAL", "values": [{"stringValue": "Goalkeeper"}]},
            {"field": "in_season_eligible", "operator": "EQUAL", "values": [{"stringValue": in_season_value}]},
        ]

        page = 1
        while page <= max_pages:
            data = graphql_query(query, {
                "userSlug": user_slug,
                "page": page,
                "pageSize": PAGE_SIZE,
                "advancedFilters": advanced_filters,
                "refinements": refinements,
            }, operation_name="MlsGoalkeeperDiscovery")

            search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
            hits = search.get('hits') or []
            if page == 1:
                log(f"Totale carte Goalkeeper/{type_key}/MLS trovate: {search.get('nbHits')} "
                    f"({search.get('nbPages')} pagine)")
            if not hits:
                break

            for h in hits:
                total_card_count += 1
                p_slug = (h.get('anyPlayer') or {}).get('slug')
                if p_slug:
                    player_card_counts.setdefault(p_slug, {'in_season': 0, 'classic': 0})
                    player_card_counts[p_slug][type_key] += 1

            nb_pages = search.get('nbPages') or 1
            if page >= nb_pages:
                break
            page += 1
            time.sleep(0.3)

    slugs = sorted(player_card_counts)
    log(f"Carte scansionate: {total_card_count} | Giocatori unici (dedup): {len(slugs)}")
    return slugs, player_card_counts


def main():
    log("Avvio discovery portieri MLS (in_season + classic)...")
    slugs, card_counts = discover_mls_goalkeepers_all()

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    out_path = os.path.join(OUTPUT_DIR, 'player_slugs.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f, ensure_ascii=False, indent=2)

    # NUOVO: numero di carte possedute per ciascun giocatore, SEPARATE per
    # tipo ({'in_season': n, 'classic': m}) -- per la fusione finale
    # multi-formazione: un giocatore puo' essere riusato in una seconda
    # lineup solo se ne possiedi piu' di una copia, e la regola "max 1
    # classic per formazione" richiede di sapere quali copie sono classic.
    counts_path = os.path.join(OUTPUT_DIR, 'player_card_counts.json')
    with open(counts_path, 'w', encoding='utf-8') as f:
        json.dump(card_counts, f, ensure_ascii=False, indent=2)

    log(f"Salvati {len(slugs)} slug in {out_path}: {slugs}")

    # Per il job GitHub Actions successivo (matrix dinamica), serve anche
    # l'output in formato leggibile da GITHUB_OUTPUT (JSON su singola riga).
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"player_slugs={json.dumps(slugs)}\n")


if __name__ == '__main__':
    main()
