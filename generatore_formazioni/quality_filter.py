"""
quality_filter.py

Filtro qualita' per il Generatore Formazioni (script fuso MLS+K League, 27/07).
Non tocca i due tool dedicati esistenti: e' un passaggio IN PIU', applicato
dopo aver letto i consigli di ruolo gia' prodotti da MLS e K League, prima di
costruire le lineup fuse.

Regola (decisa esplicitamente dall'utente il 27/07): una carta entra nel pool
solo se ha almeno 35 in TUTTE e tre le medie L5/L10/L40 (AND severo, non
media dei tre come nel discovery_global di calibrazione) -- basta una sola
sotto soglia per escluderla. Dato mancante = escluso per sicurezza (stessa
convenzione del filtro qualita' del discovery_global, non quella piu'
permissiva degli altri filtri del progetto -- qui l'obiettivo e' proprio
selezionare solo carte con storico affidabile).

Interrogazione LAZY (27/07, seconda revisione -- richiesta esplicita utente
dopo che una prima versione "controlla tutto il pool subito" ha impiegato
~7 minuti/287 query per generare solo 4 formazioni, incappando anche in un
429 con Retry-After di 4 minuti): vedi LazyQualityPool sotto -- si controllano
solo i candidati migliori man mano che servono per completare le formazioni
richieste, mai l'intero pool scoperto in un colpo solo.
"""
import os
import time
import datetime
import requests

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/federation/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')

MIN_QUALITY_SCORE = float(os.environ.get('MIN_QUALITY_SCORE', '35.0'))

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [quality_filter] {msg}")


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
                log(f"[ERRORE HTTP {resp.status_code}] body (primi 1000 char): {resp.text[:1000]}")
                return {}
            data = resp.json()
            if data.get('errors'):
                log(f"[ERRORE GraphQL] {data['errors']}")
            return data
        except Exception as e:
            log(f"[ECCEZIONE] {e}")
            time.sleep(backoff)
            backoff *= 2
    return {}


PLAYER_AVG_SCORES_QUERY = """
query PlayerAvgScores($slug: String!) {
  anyPlayer(slug: $slug) {
    lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
  }
}
"""


def fetch_l5_l10_l40(slug):
    data = graphql_query(PLAYER_AVG_SCORES_QUERY, {"slug": slug}, operation_name="PlayerAvgScores")
    player = (data.get('data') or {}).get('anyPlayer') or {}
    return player.get('lastFiveAvgScore'), player.get('lastTenPlayedAvgScore'), player.get('lastFortyAvgScore')


def _passes(l5, l10, l40, min_score):
    return (l5 is not None and l5 >= min_score
            and l10 is not None and l10 >= min_score
            and l40 is not None and l40 >= min_score)


class LazyQualityPool:
    """Interroga L5/L10/L40 SOLO per quanti candidati servono davvero, non per
    tutto il pool scoperto (27/07, richiesta esplicita utente dopo una run
    reale che ha impiegato ~7 minuti per interrogare 287 carte per generare
    solo 4 formazioni, e ha preso pure un 429 con Retry-After di quasi 4
    minuti).

    'full' e' la lista COMPLETA gia' ordinata per punteggio atteso
    decrescente (come restituita da parse_consiglio) -- MAI interrogata tutta
    subito. grow(n) controlla i prossimi 'n' candidati NON ancora controllati
    (in ordine di punteggio) e aggiunge alla lista 'passing' quelli che
    superano la soglia; ritorna quanti ne ha effettivamente controllati (0 =
    pool esaurito). Il chiamante (build_one_lineup_with_growth in
    build_formazione_globale.py) chiama grow() solo quando build_one_lineup
    segnala che gli manca un candidato per completare una formazione --
    "prova, se non basta controlla il prossimo, riprova" come richiesto."""

    def __init__(self, role, league, full_candidates, min_score=MIN_QUALITY_SCORE):
        self.role = role
        self.league = league
        self.full = full_candidates
        self.min_score = min_score
        self.checked_idx = 0
        self.passing = []

    def grow(self, batch):
        checked = 0
        while checked < batch and self.checked_idx < len(self.full):
            row = self.full[self.checked_idx]
            self.checked_idx += 1
            l5, l10, l40 = fetch_l5_l10_l40(row['slug'])
            time.sleep(0.3)
            checked += 1
            if _passes(l5, l10, l40, self.min_score):
                self.passing.append(row)
        return checked
