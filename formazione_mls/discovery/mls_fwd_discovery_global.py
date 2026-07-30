"""
mls_fwd_discovery_global.py

Discovery GLOBALE di tutti gli attaccanti MLS in_season attivi (NON solo
quelli posseduti dall'utente) -- usata per allargare il campione del grid
search di calibrazione, non per l'uso finale (schierare la formazione, che
resta sui soli giocatori posseduti via mls_fwd_discovery.py).

Clone di mls_mid_discovery_global.py, stesso approccio: per ognuna delle 30
squadre MLS interroga Club(slug).anyPlayers per il roster completo, poi
filtra lato client per posizione Forward (anyPositions del giocatore).
Nessuno scope utente richiesto: query pubblica.

Filtro qualita' (25/07): tenuti solo i giocatori con media (L5+L10+L40)/3 >=
MIN_AVG_SCORE_QUALITY (default 30.0) -- i giocatori "scarsi" non verrebbero
comunque comprati e inquinerebbero la calibrazione del modello.

Output: mls_fwd_discovery_global/player_slugs.json -- lista JSON di slug
giocatore attaccante unici, deduplicati su tutte le 30 squadre, FILTRATI per
qualita'.
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
OUTPUT_DIR = 'formazione_mls/output/mls_fwd_discovery_global'
TARGET_POSITION = 'Forward'

# Slug ufficiali confermati dal vivo (query Competition/stages, 25/07) -- 30/30
MLS_TEAM_SLUGS = [
    # Eastern Conference (15)
    'nashville-sc',
    'inter-miami',
    'chicago-fire-bridgeview-illinois',
    'new-england-foxborough-massachusetts',
    'cincinnati-cincinnati-ohio',
    'new-york-city-new-york-new-york',
    'charlotte-fc-charlotte-north-carolina',
    'new-york-rb-secaucus-new-jersey',
    'dc-united-washington-district-of-columbia',
    'orlando-city-lake-mary-florida',
    'columbus-crew-columbus-ohio',
    'toronto-toronto',
    'montreal-impact-montreal-quebec',
    'atlanta-united-atlanta-georgia',
    'philadelphia-union-chester-pennsylvania',
    # Western Conference (15)
    'vancouver-whitecaps-vancouver-british-columbia',
    'sj-earthquakes-santa-clara-california',
    'los-angeles-fc-los-angeles-california',
    'real-salt-lake-salt-lake-city-utah',
    'dallas-frisco-texas',
    'seattle-sounders-renton-washington',
    'houston-dynamo-houston-texas',
    'st-louis-city-st-louis-missouri',
    'minnesota-united-minneapolis-saint-paul-minnesota',
    'la-galaxy-los-angeles-california',
    'colorado-rapids-denver-colorado',
    'portland-timbers-portland-oregon',
    'san-diego-san-diego',
    'austin-austin-texas',
    'sporting-kc-kansas-city-kansas',
]

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [mls_fwd_discovery_global] {msg}")


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


TEAM_ROSTER_QUERY = """
query TeamRoster($slug: String!, $first: Int!, $after: String) {
  football {
    club(slug: $slug) {
      slug
      name
      activePlayers(first: $first, after: $after) {
        nodes {
          slug
          displayName
          anyPositions
          activeClub {
            slug
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""


PLAYER_AVG_SCORES_QUERY = """
query PlayerAvgScores($slug: String!) {
  anyPlayer(slug: $slug) {
    lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
  }
}
"""

# FILTRO QUALITA' (25/07, richiesta esplicita utente): la discovery globale
# serve a calibrare il modello sui giocatori che l'utente comprerebbe
# davvero, non su tutti i 300+ tesserati di un ruolo -- i giocatori "scarsi"
# (media bassa) non li comprerebbe comunque e inquinerebbero la
# calibrazione. Tenuti solo i giocatori con media (L5+L10+L40)/3 >= soglia.
# Se uno dei tre valori manca (tipico di chi ha poco storico/esordienti),
# il giocatore viene ESCLUSO per sicurezza -- coerente con l'intento
# "solo giocatori affidabili e con storico", non un'approssimazione al ribasso.
MIN_AVG_SCORE_QUALITY = float(os.environ.get('MIN_AVG_SCORE_QUALITY', '30.0'))


def get_quality_average(slug):
    """Ritorna la media (L5+L10+L40)/3 per slug, o None se uno dei tre valori
    non e' disponibile (giocatore con storico insufficiente)."""
    data = graphql_query(PLAYER_AVG_SCORES_QUERY, {"slug": slug}, operation_name="PlayerAvgScores")
    player = (data.get('data') or {}).get('anyPlayer') or {}
    l5 = player.get('lastFiveAvgScore')
    l10 = player.get('lastTenPlayedAvgScore')
    l40 = player.get('lastFortyAvgScore')
    if l5 is None or l10 is None or l40 is None:
        return None
    return (l5 + l10 + l40) / 3.0


def filter_by_quality(slugs, min_avg=MIN_AVG_SCORE_QUALITY):
    kept = []
    excluded = []
    for slug in slugs:
        avg = get_quality_average(slug)
        time.sleep(0.3)
        if avg is None or avg < min_avg:
            excluded.append((slug, avg))
            continue
        kept.append(slug)
    log(f"Filtro qualita' (media L5/L10/L40 >= {min_avg}): {len(excluded)} esclusi su {len(slugs)} "
        f"(storico insufficiente o media troppo bassa).")
    return kept


def fetch_team_players_by_position(team_slug, position):
    """Ritorna la lista di slug per una squadra, filtrando lato client su
    anyPositions contenente `position`."""
    all_nodes = []
    after = None
    while True:
        data = graphql_query(TEAM_ROSTER_QUERY, {"slug": team_slug, "first": 50, "after": after},
                              operation_name="TeamRoster")
        club = ((data.get('data') or {}).get('football') or {}).get('club')
        if not club:
            log(f"[{team_slug}] ATTENZIONE: nessun dato club restituito. "
                f"Risposta: {json.dumps(data, ensure_ascii=False)[:500]}")
            return []
        conn = club.get('activePlayers') or {}
        all_nodes.extend(conn.get('nodes') or [])
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        after = page_info.get('endCursor')

    nodes = all_nodes
    matched = [
        n['slug'] for n in nodes
        if n.get('slug') and position in (n.get('anyPositions') or [])
        and (n.get('activeClub') or {}).get('slug') == team_slug
    ]
    n_stale = sum(
        1 for n in nodes
        if n.get('slug') and position in (n.get('anyPositions') or [])
        and (n.get('activeClub') or {}).get('slug') != team_slug
    )
    if n_stale:
        log(f"[{team_slug}] {n_stale} {position.lower()} scartati: activeClub non corrisponde "
            f"(dato Sorare stantio, giocatore trasferito altrove).")
    log(f"[{team_slug}] {len(nodes)} giocatori totali, {len(matched)} {position.lower()}.")
    return matched


def main():
    log(f"Avvio discovery GLOBALE attaccanti MLS su {len(MLS_TEAM_SLUGS)} squadre...")

    all_slugs = set()
    for idx, team_slug in enumerate(MLS_TEAM_SLUGS, 1):
        log(f"[{idx}/{len(MLS_TEAM_SLUGS)}] Squadra: {team_slug}")
        players = fetch_team_players_by_position(team_slug, TARGET_POSITION)
        all_slugs.update(players)
        time.sleep(0.3)

    slugs = sorted(all_slugs)
    log(f"Totale attaccanti MLS unici trovati: {len(slugs)}")

    log(f"Filtro qualita' (media L5/L10/L40 >= {MIN_AVG_SCORE_QUALITY})...")
    slugs = filter_by_quality(slugs)
    log(f"Totale attaccanti MLS dopo filtro qualita': {len(slugs)}")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    out_path = os.path.join(OUTPUT_DIR, 'player_slugs.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f, ensure_ascii=False, indent=2)

    log(f"Salvati {len(slugs)} slug in {out_path}")

    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"player_slugs={json.dumps(slugs)}\n")


if __name__ == '__main__':
    main()
