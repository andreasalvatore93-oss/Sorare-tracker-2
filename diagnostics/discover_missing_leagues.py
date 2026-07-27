"""
Discovery campionati mancanti (diagnostics/discover_missing_leagues.py)
========================================================================

SCOPO
-----
Tool standalone di RICOGNIZIONE (non di produzione). Interroga TUTTE le
carte football possedute dall'utente su Sorare (qualunque ruolo, rarita',
lega -- nessun filtro di posizione/lega/qualita' come invece fanno le
discovery dedicate dentro formazione_*/) e aggrega per campionato
(anyPlayer.activeClub.domesticLeague.slug), cosi' da capire quali leghe
l'utente possiede in quantita' significativa ma che NON hanno ancora una
pipeline dedicata (discovery+predict+consiglio+build).

Il risultato serve a decidere dove investire tempo nel costruire le
prossime pipeline (dopo Spagna/Olanda, attualmente in corso).

INDIPENDENZA
-------------
Questo script e' COMPLETAMENTE INDIPENDENTE dalle cartelle formazione_*/:
nessun import da li', nessuna dipendenza sui loro output. Il pattern di
query (graphql_query/get_user_uuid/retry con backoff esponenziale su
HTTP>=400/429, paginazione, refinements in_season_eligible true/false) e'
ricalcato manualmente da formazione_belgio/discovery/belgio_gk_discovery.py
solo come riferimento collaudato, non importato.

USO
---
    python diagnostics/discover_missing_leagues.py

Richiede la variabile d'ambiente SORARE_COOKIE (stesso cookie di sessione
usato dal resto del progetto). Nessuna scrittura se il cookie manca --
lo script si limita a loggare l'errore e uscire.

OUTPUT
------
- Report leggibile a schermo, ordinato per numero di carte decrescente,
  con SOLO le leghe non ancora coperte da una pipeline dedicata.
- diagnostics/output/missing_leagues_report.json -- stesso contenuto in
  formato JSON, per consultazione successiva (la cartella viene creata se
  non esiste).

COSA FARNE DEL RISULTATO
-------------------------
Guardare le leghe in cima alla lista (piu' carte/giocatori unici): sono le
candidate migliori per la prossima pipeline dedicata da costruire. Leghe
con 1-2 carte marginali sono probabilmente da ignorare.
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
PAGE_SIZE = 50
OUTPUT_DIR = os.path.join('diagnostics', 'output')
OUTPUT_PATH = os.path.join(OUTPUT_DIR, 'missing_leagues_report.json')

# ---------------------------------------------------------------------------
# Leghe GIA' coperte da una pipeline dedicata (discovery+predict+consiglio+
# build) -- vanno escluse dal report perche' non sono "mancanti".
# ---------------------------------------------------------------------------
KNOWN_LEAGUE_SLUGS = {
    'k-league-1',                    # K League (Corea del Sud)
    'mls',                           # MLS (USA/Canada)
    'campeonato-brasileiro-serie-a', # Brasileirao (Brasile)
    '1-hnl',                         # HNL (Croazia)
    'primeira-liga-pt',              # Primeira Liga (Portogallo)
    'premiership-gb-sct',            # Premiership (Scozia)
    'austrian-bundesliga',           # Bundesliga (Austria)
    'jupiler-pro-league',            # Jupiler Pro League (Belgio)
    # NOTA: 'laliga-es' (Spagna) ed 'eredivisie' (Olanda) NON sono incluse
    # qui di proposito: sono pipeline ancora IN CORSO di verifica in questa
    # sessione, non ancora considerate "sicure/complete" dall'utente. Vanno
    # quindi mostrate nel report se compaiono tra le carte possedute, cosi'
    # da tenerne traccia finche' non vengono ufficialmente completate e
    # aggiunte a questo set.
}

COOKIES = os.environ.get('SORARE_COOKIE', '')

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [discover_missing_leagues] {msg}")


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
    if ':' in user_id:
        user_id = user_id.split(':', 1)[1]
    return user_id


# Query TUTTE le carte football possedute, SENZA filtro di posizione/ruolo e
# SENZA filtro rarity/lega -- vogliamo la ricognizione completa. L'unico
# filtro e' quello "base" (utente, sport, non sealed, non custom_series) gia'
# usato ovunque nel progetto per escludere carte non giocabili.
ALL_CARDS_QUERY = """
query MissingLeaguesDiscovery($userSlug: String!, $page: Int!, $pageSize: Int!,
                           $advancedFilters: String, $refinements: [SearchRefinementInput!]) {
  user(slug: $userSlug) {
    searchCards(
      sport: FOOTBALL
      query: ""
      page: $page
      pageSize: $pageSize
      advancedFilters: $advancedFilters
      refinements: $refinements
    ) {
      hits {
        slug
        anyPlayer {
          slug
          displayName
          activeClub {
            name
            domesticLeague { slug name }
          }
        }
      }
      nbHits
      nbPages
    }
  }
}
"""


def discover_all_owned_cards(user_slug=USER_SLUG, max_pages=200):
    """Ritorna la lista grezza di hit (carta + giocatore + lega) per TUTTE le
    carte football possedute da user_slug, qualunque ruolo/rarita'/lega, SIA
    in_season CHE classic (stessa iterazione su refinements
    in_season_eligible del pattern collaudato in formazione_belgio)."""
    user_uuid = get_user_uuid(user_slug)
    if not user_uuid:
        log("Impossibile ottenere l'uuid utente, interrompo.")
        return []

    advanced_filters = (
        f"user.id:{user_uuid} AND sport:football "
        f"AND NOT sealed=1 AND NOT rarity:custom_series"
    )

    all_hits = []
    for in_season_value, type_key in (("true", "in_season"), ("false", "classic")):
        refinements = [
            {"field": "in_season_eligible", "operator": "EQUAL", "values": [{"stringValue": in_season_value}]},
        ]

        page = 1
        while page <= max_pages:
            data = graphql_query(ALL_CARDS_QUERY, {
                "userSlug": user_slug,
                "page": page,
                "pageSize": PAGE_SIZE,
                "advancedFilters": advanced_filters,
                "refinements": refinements,
            }, operation_name="MissingLeaguesDiscovery")

            search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
            hits = search.get('hits') or []
            if page == 1:
                log(f"Totale carte {type_key} (TUTTE le leghe/ruoli): {search.get('nbHits')} "
                    f"({search.get('nbPages')} pagine)")
            if not hits:
                break

            all_hits.extend(hits)

            nb_pages = search.get('nbPages') or 1
            if page >= nb_pages:
                break
            page += 1
            time.sleep(0.3)

    log(f"Totale carte scansionate (in_season + classic): {len(all_hits)}")
    return all_hits


def aggregate_by_league(hits):
    """Aggrega gli hit per domesticLeague.slug. Ritorna un dict
    slug -> {league_name, n_cards, players: {slug: {name, count}}}."""
    leagues = {}
    for h in hits:
        player = h.get('anyPlayer') or {}
        p_slug = player.get('slug')
        p_name = player.get('displayName') or p_slug
        club = player.get('activeClub') or {}
        league = club.get('domesticLeague') or {}
        league_slug = league.get('slug')
        league_name = league.get('name')

        if not league_slug:
            league_slug = '__unknown__'
            league_name = league_name or '(lega sconosciuta/mancante)'

        entry = leagues.setdefault(league_slug, {
            'league_slug': league_slug,
            'league_name': league_name,
            'n_cards': 0,
            'players': {},
        })
        entry['n_cards'] += 1
        if p_slug:
            pentry = entry['players'].setdefault(p_slug, {'slug': p_slug, 'name': p_name, 'count': 0})
            pentry['count'] += 1

    return leagues


def build_report(leagues, known_slugs=KNOWN_LEAGUE_SLUGS):
    """Filtra le leghe gia' coperte da pipeline dedicate e produce una lista
    di righe report ordinata per n_cards decrescente."""
    rows = []
    for league_slug, entry in leagues.items():
        if league_slug in known_slugs:
            continue
        players = list(entry['players'].values())
        players_sorted = sorted(players, key=lambda p: p['count'], reverse=True)
        examples = players_sorted[:3]
        rows.append({
            'league_slug': league_slug,
            'league_name': entry['league_name'],
            'n_cards': entry['n_cards'],
            'n_unique_players': len(players),
            'examples': [{'slug': p['slug'], 'name': p['name']} for p in examples],
        })
    rows.sort(key=lambda r: r['n_cards'], reverse=True)
    return rows


def print_report(rows):
    if not rows:
        print("Nessuna lega mancante trovata: tutte le carte possedute appartengono "
              "a leghe gia' coperte da una pipeline dedicata.")
        return

    print("\n" + "=" * 78)
    print("LEGHE NON ANCORA COPERTE DA UNA PIPELINE DEDICATA")
    print("=" * 78)
    for r in rows:
        examples_str = ', '.join(f"{e['name']} ({e['slug']})" for e in r['examples']) or '-'
        print(f"\n- slug: {r['league_slug']}")
        print(f"  nome: {r['league_name']}")
        print(f"  carte possedute: {r['n_cards']}")
        print(f"  giocatori unici: {r['n_unique_players']}")
        print(f"  esempi: {examples_str}")
    print("\n" + "=" * 78)


def main():
    if not COOKIES:
        log("SORARE_COOKIE non impostato in ambiente. Interrompo senza eseguire query.")
        return

    log(f"Avvio ricognizione completa carte possedute da '{USER_SLUG}' (tutte le leghe/ruoli)...")
    hits = discover_all_owned_cards()
    if not hits:
        log("Nessuna carta trovata (o errore di query). Interrompo.")
        return

    leagues = aggregate_by_league(hits)
    rows = build_report(leagues)
    print_report(rows)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    report_payload = {
        'generated_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'user_slug': USER_SLUG,
        'known_league_slugs_excluded': sorted(KNOWN_LEAGUE_SLUGS),
        'total_cards_scanned': len(hits),
        'missing_leagues': rows,
    }
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    log(f"Report scritto in {OUTPUT_PATH} ({len(rows)} leghe mancanti trovate)")


if __name__ == '__main__':
    main()
