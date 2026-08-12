"""
spagna_mid_discovery_global.py

Discovery GLOBALE di tutti i centrocampisti LaLiga in_season attivi (NON solo
quelli posseduti dall'utente) -- usata per allargare il campione del grid
search di calibrazione, non per l'uso finale (schierare la formazione, che
resta sui soli giocatori posseduti via spagna_mid_discovery.py).

Clone di mls_mid_discovery_global.py, stesso approccio: per ognuna delle 18
squadre LaLiga interroga Club(slug).anyPlayers per il roster completo,
poi filtra lato client per posizione Midfielder (anyPositions del
giocatore). Nessuno scope utente richiesto: query pubblica.

Slug squadre ottenuti dal vivo (29/07) con la query pubblica
`football { competition(slug: "laliga-es") { clubs(first: 50) { nodes {
slug name } } } }` -- 18/18 squadre restituite (workflow
verify_bundesliga_clubs.yml, run 30455180403).

Filtro qualita' (29/07, stesso principio di MLS 25/07): tenuti solo i
giocatori con media (L5+L10+L40)/3 >= MIN_AVG_SCORE_QUALITY (default 30.0)
-- i giocatori "scarsi" non verrebbero comunque comprati e inquinerebbero
la calibrazione del modello.

Output: spagna_mid_discovery_global/player_slugs.json -- lista JSON di slug
giocatore centrocampiste unici, deduplicati su tutte le 18 squadre, FILTRATI per
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
OUTPUT_DIR = 'formazione_spagna/output/spagna_mid_discovery_global'
TARGET_POSITION = 'Midfielder'

# Slug ufficiali confermati dal vivo (query Competition(slug: "laliga-es")
# .clubs, 29/07) -- 18/18
SPAGNA_TEAM_SLUGS = [
    'athletic-club-bilbao',
    'atletico-madrid-madrid',
    'barcelona-barcelona',
    'celta-de-vigo-vigo',
    'deportivo-alaves-vitoria-gasteiz',
    'deportivo-la-coruna-a-coruna',
    'elche-elche',
    'espanyol-barcelona',
    'getafe-getafe-madrid',
    'levante-valencia',
    'malaga-malaga',
    'osasuna-pamplona-irunea',
    'racing-santander-santander',
    'rayo-vallecano-madrid',
    'real-betis-sevilla',
    'real-madrid-madrid',
    'real-sociedad-donostia-san-sebastian',
    'sevilla-sevilla-1890',
    'valencia-valencia',
    'villarreal-villarreal',
]

COOKIES = os.environ.get('SORARE_COOKIE', '')
# APIKEY (12/08/2026): alza il tetto di complessita' GraphQL da 500 a 30000
# e il limite di richieste dell'account. Si affianca al cookie, non lo
# sostituisce. Verificato sull'API vera: senza chiave una query da 8
# partite di dettaglio veniva rifiutata ("complexity of 505, which
# exceeds max complexity of 500"), con la chiave ne passano 200.
APIKEY = os.environ.get('SORARE_APIKEY', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [spagna_mid_discovery_global] {msg}")


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

MIN_AVG_SCORE_QUALITY = float(os.environ.get('MIN_AVG_SCORE_QUALITY', '40.0'))


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
            return [], {}
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
    # NUOVO (30/07, tema Best Five): displayName reale Sorare per ogni slug -- il campo
    # e' gia' nella risposta (vedi TEAM_ROSTER_QUERY sopra), prima veniva scartato,
    # zero chiamate API aggiuntive per persisterlo.
    names = {n['slug']: n.get('displayName') for n in nodes
             if n.get('slug') and n.get('displayName')}
    n_stale = sum(
        1 for n in nodes
        if n.get('slug') and position in (n.get('anyPositions') or [])
        and (n.get('activeClub') or {}).get('slug') != team_slug
    )
    if n_stale:
        log(f"[{team_slug}] {n_stale} {position.lower()} scartati: activeClub non corrisponde "
            f"(dato Sorare stantio, giocatore trasferito altrove).")
    log(f"[{team_slug}] {len(nodes)} giocatori totali, {len(matched)} {position.lower()}.")
    return matched, names


def main():
    log(f"Avvio discovery GLOBALE centrocampisti LaLiga su {len(SPAGNA_TEAM_SLUGS)} squadre...")

    all_slugs = set()
    all_names = {}
    for idx, team_slug in enumerate(SPAGNA_TEAM_SLUGS, 1):
        log(f"[{idx}/{len(SPAGNA_TEAM_SLUGS)}] Squadra: {team_slug}")
        players, names_batch = fetch_team_players_by_position(team_slug, TARGET_POSITION)
        all_slugs.update(players)
        all_names.update(names_batch)
        time.sleep(0.3)

    slugs = sorted(all_slugs)
    log(f"Totale centrocampisti LaLiga unici trovati: {len(slugs)}")

    log(f"Filtro qualita' (media L5/L10/L40 >= {MIN_AVG_SCORE_QUALITY})...")
    slugs = filter_by_quality(slugs)
    log(f"Totale centrocampisti LaLiga dopo filtro qualita': {len(slugs)}")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    out_path = os.path.join(OUTPUT_DIR, 'player_slugs.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f, ensure_ascii=False, indent=2)

    # NUOVO (30/07, tema Best Five, richiesta esplicita utente: "il nome sulle carte deve
    # essere il display name non lo slug"): nomi SOLO per gli slug sopravvissuti al
    # filtro qualita' (coerente con player_slugs.json/player_quality.json).
    names_path = os.path.join(OUTPUT_DIR, 'player_names.json')
    with open(names_path, 'w', encoding='utf-8') as f:
        json.dump({s: all_names[s] for s in slugs if s in all_names}, f, ensure_ascii=False)
    log(f"Salvati {sum(1 for s in slugs if s in all_names)} nomi in {names_path}")

    log(f"Salvati {len(slugs)} slug in {out_path}")

    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"player_slugs={json.dumps(slugs)}\n")


if __name__ == '__main__':
    main()
