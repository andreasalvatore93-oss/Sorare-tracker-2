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
OUTPUT_DIR = 'formazione_mls/output/mls_gk_discovery'
# 50 dal 13/08/2026 (era 20, tarato sul tetto di complessita' 500
# dell'accesso ANONIMO): qui il cookie c'e' sempre -- si chiedono le carte
# DI UN UTENTE -- e dal 12/08 c'e' anche l'APIKEY, tetto 30.000. MISURATO
# sulla stessa searchCards: 320 carte in 7 richieste invece di 16, stessi
# slug e stesso nbHits (docs/handoff/prova_pagesize.py, commit 577651ac9d).
# 50 e' il massimo vero del server: chiedendone di piu' non ne arrivano.
PAGE_SIZE = 50

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
    print(f"[{ts}] [mls_gk_discovery] {msg}")


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


# ---------------------------------------------------------------------------
# FILTRO STARTER-ODDS (25/07, SOLO pipeline produzione "miei giocatori"):
# scartiamo qui, PRIMA di generare la matrix del job 'predict', chi ha
# starter-odds della prossima partita sotto MIN_STARTER_ODDS_DISCOVERY --
# cosi' non spawna nemmeno un job CI (checkout+setup+pip install+15-30
# query di dettaglio) per un giocatore che verrebbe comunque escluso.
# Dato dinamico per giornata (es. un titolare fermo per turnover questa
# settimana torna la prossima), quindi va rifatto ad ogni run -- NON
# applicare questa logica alla discovery GLOBALE (tutti i giocatori MLS,
# usata per allargare la calibrazione): li' servono anche i giocatori che
# non partono titolari in una data giornata.
# Se il dato non e' disponibile (nessuna partita futura programmata,
# rotazione non ancora nota), il giocatore viene TENUTO per sicurezza
# invece di essere escluso a priori.
# ---------------------------------------------------------------------------
MIN_STARTER_ODDS_DISCOVERY = float(os.environ.get('MIN_STARTER_ODDS', '0.60'))

NEXT_GAME_ODDS_QUERY = """
query NextGameOdds($slug: String!) {
  anyPlayer(slug: $slug) {
    anyFutureGames(first: 1) {
      nodes {
        playerGameScore(playerSlug: $slug) {
          anyGame { date }
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints }
            }
          }
        }
      }
    }
  }
}
"""


# Quanti giorni in avanti considerare "questa giornata". Un giocatore la cui
# prossima partita e' oltre questa finestra NON serve a schierare adesso: va
# scartato QUI, prima di spawnare il job predict (che costa 15-30 query).
MATCH_WINDOW_DAYS = float(os.environ.get('MATCH_WINDOW_DAYS', '7'))


def get_next_game_odds_and_date(slug):
    """(probabilita' 0.0-1.0 di titolarita', data ISO della prossima partita).
    Ognuno dei due puo' essere None se il dato non e' disponibile."""
    data = graphql_query(NEXT_GAME_ODDS_QUERY, {"slug": slug}, operation_name="NextGameOdds")
    player = (data.get('data') or {}).get('anyPlayer') or {}
    future = (player.get('anyFutureGames') or {}).get('nodes') or []
    if not future:
        return None, None
    pgs = future[0].get('playerGameScore') or {}
    kickoff = (pgs.get('anyGame') or {}).get('date')
    odds = (pgs.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}
    bp = odds.get('starterOddsBasisPoints')
    return (bp / 10000.0 if bp is not None else None), kickoff


def get_next_game_starter_odds(slug):
    """Compatibilita' con il codice esistente."""
    return get_next_game_odds_and_date(slug)[0]


def _kickoff_within_window(kickoff, now=None):
    """True se la partita cade fra adesso e +MATCH_WINDOW_DAYS. Data assente o
    non parsabile = True (non si scarta per un dato mancante)."""
    if not kickoff:
        return True
    now = now or datetime.datetime.utcnow()
    try:
        dt = datetime.datetime.fromisoformat(kickoff.replace('Z', '')[:19])
    except ValueError:
        return True
    if dt < now - datetime.timedelta(hours=2):
        return False
    # Limite superiore in GIORNI DI CALENDARIO: fine giornata di (oggi + N).
    # Contarlo in ore da adesso tagliava le partite serali dell'ultimo giorno.
    ultimo = (now.date() + datetime.timedelta(days=int(MATCH_WINDOW_DAYS)))
    return dt.date() <= ultimo


def filter_by_starter_odds(slugs, player_card_counts, min_starter_odds=MIN_STARTER_ODDS_DISCOVERY):
    kept_slugs = []
    kept_counts = {}
    excluded = []
    fuori_finestra = []
    senza_odds = []
    for slug in slugs:
        odds, kickoff = get_next_game_odds_and_date(slug)
        time.sleep(0.3)
        # 1) La partita e' fuori dalla giornata per cui si schiera: inutile.
        if not _kickoff_within_window(kickoff):
            fuori_finestra.append((slug, (kickoff or '?')[:16]))
            continue
        # 2) Soglia richiesta ma odds assenti: NON si tiene "per sicurezza".
        # Le starter odds escono a ~24-48h dal match; se qui mancano pur essendo
        # la partita dentro la finestra, la titolarita' e' ignota e il giocatore
        # non e' affidabile per schierare. Tenerlo rendeva la soglia inerte.
        if odds is None:
            if min_starter_odds > 0:
                senza_odds.append(slug)
                continue
        elif odds < min_starter_odds:
            excluded.append((slug, odds))
            continue
        kept_slugs.append(slug)
        kept_counts[slug] = player_card_counts[slug]

    log(f"Filtro giornata (+{MATCH_WINDOW_DAYS:g}g): {len(fuori_finestra)} esclusi perche' "
        f"la prossima partita e' fuori finestra. Esempi: {fuori_finestra[:5]}")
    log(f"Filtro starter-odds >= {min_starter_odds:.0%}: {len(excluded)} sotto soglia, "
        f"{len(senza_odds)} senza dato odds (esclusi: con una soglia attiva il dato "
        f"mancante NON e' piu' tenuto). Sotto soglia: {excluded}")
    return kept_slugs, kept_counts


# ---------------------------------------------------------------------------
# FILTRO ATTIVITA' MINIMA (26/07, SOLO pipeline produzione "miei giocatori",
# richiesta esplicita utente): scarta chi ha media 0 nelle ultime 5 partite
# -- "carte morte" mai schierabili (l'utente ha verificato a mano sulla
# propria galleria Sorare che questo taglia circa 80 giocatori inutili).
# Soglia MOLTO bassa apposta (default 0.0, non un vero filtro qualita'):
# l'obiettivo e' solo evitare di sprecare un intero job predict (checkout+
# setup+15-30 query di dettaglio) su chi non gioca mai, NON escludere per
# errore chi e' solo in un momento di forma basso. Se il dato manca (storico
# insufficiente, es. esordiente), il giocatore viene TENUTO per sicurezza,
# stesso principio del filtro starter-odds sopra.
# ---------------------------------------------------------------------------
MIN_ACTIVITY_SCORE = float(os.environ.get('MIN_ACTIVITY_SCORE', '0.0'))
# NUOVO (26/07, richiesta esplicita utente): scarta anche chi ha una media
# ultime 10 partite GIOCATE <= questa soglia -- non solo le "carte morte"
# (L5<=0) ma anche chi e' costantemente sottotono, per ridurre ulteriormente
# il numero di job predict inutili nelle run di produzione ("i miei
# giocatori"). LAST_TEN_PLAYED (non LAST_TEN semplice) conta solo le partite
# EFFETTIVAMENTE giocate, evitando che le assenze abbassino artificialmente
# la media. Stessa logica di sicurezza del filtro L5: dato mancante = tenuto.
MIN_L10_SCORE = float(os.environ.get('MIN_L10_SCORE', '35.0'))

LAST_FIVE_AVG_QUERY = """
query LastFiveAvg($slug: String!) {
  anyPlayer(slug: $slug) {
    lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
  }
}
"""


def get_last_five_avg(slug):
    """Ritorna (media ultime 5, media ultime 10 giocate) per slug -- None per
    ciascun valore non disponibile (storico insufficiente). Un'unica query
    per entrambi i dati, per non raddoppiare le chiamate API."""
    data = graphql_query(LAST_FIVE_AVG_QUERY, {"slug": slug}, operation_name="LastFiveAvg")
    player = (data.get('data') or {}).get('anyPlayer') or {}
    return player.get('lastFiveAvgScore'), player.get('lastTenPlayedAvgScore')


def filter_by_activity(slugs, player_card_counts, min_avg=MIN_ACTIVITY_SCORE, min_l10=MIN_L10_SCORE):
    kept_slugs = []
    kept_counts = {}
    excluded = []
    for slug in slugs:
        avg5, avg10 = get_last_five_avg(slug)
        time.sleep(0.3)
        if avg5 is not None and avg5 <= min_avg:
            excluded.append((slug, 'L5', avg5))
            continue
        if avg10 is not None and avg10 <= min_l10:
            excluded.append((slug, 'L10', avg10))
            continue
        kept_slugs.append(slug)
        # NUOVO (26/07, seconda sessione): persiste L10 (media ultime 10
        # partite giocate) in player_card_counts.json -- serve a
        # build_formazione_finale.py per il tuning "Arena L10 cap" (opzione
        # che limita la L10 combinata dei 5 giocatori in formazione Arena).
        kept_counts[slug] = dict(player_card_counts[slug], l10=avg10)

    log(f"Filtro attivita' minima (media ultime 5 > {min_avg} E media ultime 10 giocate > {min_l10}): "
        f"{len(excluded)} esclusi su {len(slugs)} (dato mancante = tenuto per sicurezza). Esclusi: {excluded}")
    return kept_slugs, kept_counts


def main():
    log("Avvio discovery portieri MLS (in_season + classic)...")
    slugs, card_counts = discover_mls_goalkeepers_all()

    log("Filtro attivita' minima (media ultime 5 e ultime 10 partite giocate, taglia carte morte e sottotono)...")
    slugs, card_counts = filter_by_activity(slugs, card_counts)

    log("Filtro starter-odds sulla prossima partita (solo pipeline produzione)...")
    slugs, card_counts = filter_by_starter_odds(slugs, card_counts)

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
