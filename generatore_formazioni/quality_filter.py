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

Fallback di sicurezza: se per un ruolo/lega il filtro lascia meno carte del
minimo di sicurezza (MIN_KEPT_PER_ROLE), si ripescano le migliori scartate
(per punteggio atteso) finche' non si raggiunge il minimo -- mai un ruolo
lasciato vuoto per colpa del filtro.
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
MIN_KEPT_PER_ROLE = int(os.environ.get('QUALITY_FALLBACK_MIN', '3'))

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


def filter_role_rows(role, league, rows, min_score=MIN_QUALITY_SCORE, min_kept=MIN_KEPT_PER_ROLE):
    """rows: lista gia' ordinata per 'atteso' decrescente (come restituita da
    parse_consiglio). Ritorna la stessa lista filtrata (stesso ordine), con
    eventuale ripesca di fallback se resta troppo corta."""
    kept, excluded = [], []
    for row in rows:
        l5, l10, l40 = fetch_l5_l10_l40(row['slug'])
        time.sleep(0.3)
        if _passes(l5, l10, l40, min_score):
            kept.append(row)
        else:
            excluded.append(row)

    if len(kept) < min_kept and excluded:
        need = min_kept - len(kept)
        ripescati = excluded[:need]
        kept = sorted(kept + ripescati, key=lambda r: r['atteso'], reverse=True)
        log(f"[{league}/{role}] Fallback qualita': pool sotto il minimo ({min_kept}), "
            f"ripescati {len(ripescati)} scartati per media insufficiente.")

    log(f"[{league}/{role}] Filtro qualita' (L5/L10/L40 tutti >= {min_score}): "
        f"{len(rows) - len(kept)} esclusi su {len(rows)} (dato mancante = escluso).")
    return kept
