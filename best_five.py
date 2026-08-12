"""
best_five.py (30/07, prototipo — vedi memoria project_backlog_best_five_funzione.md)

Per UNA lega scelta, trova la miglior formazione POSSIBILE scegliendo tra
TUTTE le carte disponibili nella lega (pool GLOBALE della discovery, non
solo i posseduti), con N candidati di backup per ogni ruolo (nel caso il
titolare scelto non scenda in campo quella giornata).

Script SEPARATO e READ-ONLY rispetto alla pipeline di produzione
(formazione_giornata.yml): riusa test_<ruolo>.py COSI' COM'E' come
libreria/processo esterno (subprocess), zero duplicazione della logica di
calcolo dello score_atteso. Non tocca budget/anti-stack/sinergie/multi-
lineup — quello resta specifico delle formazioni REALI sui posseduti
(build_formazione_finale.py).

Richiede che la lega scelta abbia gia' una discovery GLOBALE completa per
tutti e 4 i ruoli (oggi: mls, kleague, germania) — vedi
formazione_<lega>/output/<lega>_<ruolo>_discovery_global/player_slugs.json.

Uso:
  python best_five.py kleague              # usa l'ultimo output gia' presente per ogni ruolo (se c'e')
  python best_five.py kleague --run         # ri-esegue la predizione per ogni ruolo, poi rankinga
  python best_five.py kleague --run --backups 2   # 1 titolare + 2 backup per ruolo (default: 2 backup)
  python best_five.py kleague --run --roles mid,fwd   # solo sui ruoli indicati

Con --run (30/07 sera, ottimizzazione tempi): per ogni ruolo, il pool
GLOBALE della lega (gia' filtrato per qualita' >= 30 a monte, in
discovery_global) viene ulteriormente filtrato con una query leggera
starterOdds sulla prossima partita (soglia BEST_FIVE_MIN_STARTER_ODDS,
default 0.70, decisa esplicitamente dall'utente) PRIMA della predizione
costosa. Solo i sopravvissuti vengono passati a test_<ruolo>.py, UN
subprocess per giocatore (TARGET_SLUG, stile job matrix della pipeline di
produzione) invece che un unico subprocess sull'intero pool.

Il ranking usa lo stesso ORDINAMENTO (score senza shrinkage, dove
disponibile) gia' calcolato e stampato da ciascun test_<ruolo>.py —
nessuna logica di scoring duplicata qui, solo parsing + selezione top N.
Per compatibilita' con risultati gia' generati in modalita' "pool intero"
(es. GK/DEF K League del 30/07, un solo file prediction_all_*.txt per
ruolo), quel formato resta supportato e ha precedenza se presente.
"""
import os
import sys
import re
import json
import glob
import time
import base64
import shutil
import subprocess
import datetime
import importlib.util
import concurrent.futures

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
    import requests

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

GRAPHQL_URL = 'https://api.sorare.com/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')
# 12/08: alza il tetto di rate/complessita' sull'account, si aggiunge al cookie.
APIKEY = os.environ.get('SORARE_APIKEY', '')
_http_session = curl_requests.Session(impersonate="chrome") if _HAS_CURL_CFFI else requests.Session()

# Soglia starterOdds decisa esplicitamente dall'utente (30/07): sotto il 70%
# un giocatore e' "piu' rischioso e comunque non lo sceglierebbe" -- quindi
# filtrarlo PRIMA della predizione costosa non perde candidati che l'utente
# avrebbe scelto comunque. Il pool su cui si applica e' gia' filtrato per
# qualita' (media L5/L10/L40 >= 30) a monte, in discovery_global.
MIN_STARTER_ODDS_PREFILTER = float(os.environ.get('BEST_FIVE_MIN_STARTER_ODDS', '0.80'))

# Top-N esclusi per ruolo (31/07, richiesta esplicita utente): oltre alle
# formazioni intere generate, mostra sempre anche i migliori N candidati
# eleggibili (sopravvissuti al prefiltro starterOdds) MAI schierati in
# nessuna formazione -- utile soprattutto quando si chiedono molte
# formazioni (n_backup alto) e un ruolo scarso (es. i portieri di una lega
# piccola) esaurisce il pool prima degli altri: la lista dice comunque chi
# altro sarebbe stato eleggibile, invece di far sembrare il pool piu'
# povero di quanto sia davvero.
TOP_N_ESCLUSI = int(os.environ.get('BEST_FIVE_TOP_N_ESCLUSI', '10'))

# Cap per qualita' PRIMA delle starterOdds (30/07, richiesta esplicita
# utente: "implementa cap qualita'" -- riduzione ulteriore, sopra alla
# parallelizzazione gia' fatta, del numero di query starterOdds necessarie).
# Tiene solo i top-K per ruolo secondo la media L5/L10/L40 gia' persistita in
# player_quality.json (nessuna chiamata API aggiuntiva, il valore era gia'
# calcolato per il filtro qualita' di discovery_global). 0 o negativo =
# disattivato (comportamento precedente, pool intero). Se player_quality.json
# non esiste ancora (discovery non ancora rilanciata dopo l'aggiunta di
# questo file), il cap non si applica -- MAI un'esclusione silenziosa per
# dato mancante.
BEST_FIVE_TOP_K_QUALITA = int(os.environ.get('BEST_FIVE_TOP_K_QUALITA', '40'))

NEXT_MATCH_STARTER_ODDS_QUERY = """
query NextMatchStarterOdds($slug: String!) {
  anyPlayer(slug: $slug) {
    anyFutureGames(first: 1) {
      nodes {
        playerGameScore(playerSlug: $slug) {
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints reliability }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_next_match_starter_odds(slug):
    """Query leggera (nessuno storico, nessun game log) per lo starterOdds
    della prossima partita di un giocatore. Ritorna un float 0-1, o None se
    non disponibile (nessuna partita futura fissata, dato mancante, o
    fallimento della query dopo i retry)."""
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    if APIKEY:
        headers['APIKEY'] = APIKEY
    payload = {'query': NEXT_MATCH_STARTER_ODDS_QUERY, 'variables': {'slug': slug},
               'operationName': 'NextMatchStarterOdds'}

    backoff = 1.0
    for attempt in range(3):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                log(f"[starterOdds] {slug}: HTTP {resp.status_code}, salto (trattato come dato mancante).")
                return None
            data = resp.json()
            nodes = (((data.get('data') or {}).get('anyPlayer') or {}).get('anyFutureGames') or {}).get('nodes') or []
            if not nodes:
                return None
            pgs = nodes[0].get('playerGameScore') or {}
            odds = ((pgs.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
            bp = odds.get('starterOddsBasisPoints')
            return bp / 10000.0 if bp is not None else None
        except Exception as e:
            log(f"[starterOdds] {slug}: eccezione tentativo {attempt+1}/3: {e!r}")
            time.sleep(backoff)
            backoff *= 2
    return None


# RISPETTA_CAP_L10 (31/07, richiesta esplicita utente): il cap 260 delle
# Arene NON e' mai stato applicato davvero in Best Five -- ne' per MLS/K
# League (IN_SEASON, cap sempre None per design), ne' per le Arene vere (bug
# reale: bff._pareto_frontier collassa a 1 solo candidato per ruolo quando
# tutti gli L10 sono sconosciuti/0.0, vedi _tipo_per_lega). Con questo flag
# a 'true', il cap torna a essere applicato DAVVERO: serve pero' l'L10 reale
# di ogni candidato (altrimenti si ripresenta lo stesso bug), quindi in quel
# caso si fa UNA query in piu' per giocatore (fetch_l10_reale) -- costo
# accettabile solo se l'utente lo chiede esplicitamente, per questo resta
# disattivato di default. Utile per generare Arene dedicate DAVVERO valide
# su Sorare invece di formazioni generiche senza vincolo di livello.
# ACCESO DI DEFAULT dal 04/08 (era '0', cioe' spento, dal 31/07). Motivo:
# l'audit di coerenza scouting/generatore ha trovato che il generatore applica
# SEMPRE il cap L10 alle arene (260/220, build_formazione_globale.py) mentre
# qui era spento, quindi lo scouting consigliava acquisti che in arena non
# sarebbero stati schierabili -- "si comprano carte che non si schierano".
# Le arene sono il canale che conta, quindi il default deve riflettere il
# vincolo vero.
# COSTO, che resta quello descritto sotto: con il cap attivo serve l'L10 REALE
# di ogni candidato, cioe' una query in piu' per giocatore (fetch_l10_per_ruoli).
# COSA NON CAMBIA: nessuna carta sparisce dall'output. Questo flag decide solo
# quali FORMAZIONI sono costruibili; l'elenco dei candidati dello scouting
# arriva dai consiglio_*.txt e non passa di qui.
RISPETTA_CAP_L10 = os.environ.get('BEST_FIVE_RISPETTA_CAP_L10', '1').strip() not in ('0', 'false', 'no', '')

# Pausa prima del secondo giro sugli L10 non letti (vedi fetch_l10_per_ruoli).
L10_RETRY_PAUSA = float(os.environ.get('BEST_FIVE_L10_RETRY_PAUSA', '30'))

# Cache degli L10 (31/07): stesso schema/TTL della cache prezzi. L'L10 e' una
# media sulle ultime 10 partite GIOCATE, quindi cambia solo quando il
# giocatore scende in campo -- rifarla a ogni run era il vero costo dello step
# report una volta che i prezzi erano in cache.
L10_CACHE_PATH = os.path.join(REPO_ROOT, 'best_five_l10_cache.json')
L10_CACHE_TTL_ORE = float(os.environ.get('BEST_FIVE_L10_CACHE_TTL_ORE', str(24 * 5)))


def _l10_cache_leggi():
    if not os.path.exists(L10_CACHE_PATH):
        return {}
    try:
        with open(L10_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _l10_cache_scrivi(cache):
    with open(L10_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def _voce_l10_valida(voce, ora):
    """Una voce di cache L10 vale finche' siamo nella STESSA giornata in cui
    e' stata scritta (31/07, richiesta esplicita utente: "lega sempre cache
    degli L10 anche alla fine gw, come prima, altrimenti e' un casino").

    Motivo: l'L10 cambia quando il giocatore scende in campo, cioe' proprio
    alla fine della giornata -- una scadenza a ore la prenderebbe sempre o
    troppo presto o troppo tardi, mentre la giornata e' il confine esatto. Si
    riusa la stessa finestra gia' risolta per le predizioni
    (_finestra_giornata), quindi zero query in piu'. Se la giornata non e'
    risolvibile si ricade sul TTL a ore."""
    ts = voce.get('ts')
    if not ts:
        return False
    finestra = _finestra_giornata()
    if finestra:
        inizio, _fine = finestra
        # Scritta durante QUESTA giornata (cioe' non prima del suo inizio):
        # ancora valida. Scritta prima, appartiene alla giornata precedente e
        # nel frattempo si e' giocato: da rifare.
        return ts[:19] >= inizio[:19]
    try:
        eta_ore = (ora - datetime.datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except ValueError:
        return False
    return eta_ore <= L10_CACHE_TTL_ORE

L10_REALE_QUERY = """
query L10Reale($slug: String!) {
  anyPlayer(slug: $slug) {
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
  }
}
"""


def fetch_l10_reale(slug):
    """L10 reale (media SO5 ultime 10 partite giocate) di un giocatore --
    stesso campo gia' usato in discovery_global per il filtro qualita', qui
    riletto per singolo slug (serve solo quando RISPETTA_CAP_L10 e' attivo).
    Ritorna (valore, esito) con esito in 'ok' | 'assente' | 'errore':
    - 'ok'      -> valore numerico affidabile
    - 'assente' -> Sorare risponde ma il giocatore non ha storico (None vero)
    - 'errore'  -> la query e' fallita (429 esauriti, HTTP 4xx/5xx, eccezione)

    FIX BUG REALE (31/07, trovato dall'utente su una formazione MLS che
    dichiarava "L10 combinata 79.0 / cap 260" per 5 giocatori, cioe' ~16 di
    media, impossibile): prima questa funzione restituiva None SIA quando il
    giocatore non ha storico SIA quando la query falliva -- e su HTTP >= 400
    lo faceva pure in silenzio, senza un log. A valle un None diventa 0.0
    (vedi _candidati_prezzo_ruolo), quindi i giocatori persi per rate limit
    entravano nel conto come se avessero L10 zero: totale sottostimato e --
    molto peggio -- vincolo del cap 260 di fatto disattivato, con formazioni
    che su Sorare potrebbero sforare davvero. Verificato sul caso reale: dei
    5 schierati solo Cleveland (36) e Sealy (43) erano stati letti, 36+43=79,
    mentre Yamane (48) e Almiron (52) risultavano a zero per errore di
    query."""
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    if APIKEY:
        headers['APIKEY'] = APIKEY
    payload = {'query': L10_REALE_QUERY, 'variables': {'slug': slug}, 'operationName': 'L10Reale'}
    backoff = 1.0
    for attempt in range(3):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                log(f"[L10 reale] {slug}: HTTP {resp.status_code} -- dato NON letto "
                    f"(non e' 'nessuno storico', e' un errore).")
                return None, 'errore'
            data = resp.json()
            player = (data.get('data') or {}).get('anyPlayer') or {}
            valore = player.get('lastTenPlayedAvgScore')
            return valore, ('ok' if valore is not None else 'assente')
        except Exception as e:
            log(f"[L10 reale] {slug}: eccezione tentativo {attempt+1}/3: {e!r}")
            time.sleep(backoff)
            backoff *= 2
    return None, 'errore'


def fetch_l10_per_ruoli(role_data_dict):
    """L10 reale per TUTTI gli slug in role_data_dict (dict ROLE -> righe),
    ritorna {slug: l10_o_None}.

    Chi fallisce per errore di query (non per assenza di storico) viene
    RITENTATO in un secondo giro dopo una pausa -- stesso principio del
    rate_limited_pool di bot_profit.py. Alla fine logga quanti restano
    davvero ignoti, distinguendo "senza storico" da "non letti": la
    differenza conta, perche' a valle un L10 ignoto vale 0 e quindi
    ammorbidisce silenziosamente il cap (vedi fetch_l10_reale)."""
    slugs = sorted({r['slug'] for rows in role_data_dict.values() for r in rows})

    # CACHE + PARALLELISMO (31/07, osservazione dell'utente: "pagina prezzi
    # comunque e' a 3 minuti anche se li ha gia'"). I prezzi erano davvero
    # tutti in cache: il tempo se ne andava TUTTO qui, 233 query L10 in
    # SEQUENZA e senza alcuna cache, ripetute identiche a ogni run. L'L10 e'
    # una media sulle ultime 10 partite giocate: si muove solo quando il
    # giocatore jscende in campo, quindi e' esattamente il tipo di dato da
    # mettere in cache come i prezzi (stesso file-schema, stesso TTL).
    cache = _l10_cache_leggi()
    ora = datetime.datetime.utcnow()
    l10_map = {}
    da_interrogare = []
    for slug in slugs:
        voce = cache.get(slug)
        if voce is not None and _voce_l10_valida(voce, ora):
            l10_map[slug] = voce.get('l10')
            continue
        da_interrogare.append(slug)

    if not da_interrogare:
        log(f"[L10 reale] {len(slugs)} giocatori tutti in cache (< {L10_CACHE_TTL_ORE:g}h), nessuna query.")
        return l10_map

    log(f"[L10 reale] {len(slugs) - len(da_interrogare)} da cache, "
        f"{len(da_interrogare)} da interrogare dal vivo.")
    ts_ora = ora.isoformat()
    falliti = []
    fatti = 0
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=5, thread_name_prefix='l10') as executor:
        futures = {executor.submit(fetch_l10_reale, slug): slug for slug in da_interrogare}
        for future in concurrent.futures.as_completed(futures):
            slug = futures[future]
            valore, esito = future.result()
            l10_map[slug] = valore
            if esito == 'errore':
                falliti.append(slug)
            else:
                cache[slug] = {'l10': valore, 'ts': ts_ora}
            fatti += 1
            if fatti % PREZZI_CACHE_CHUNK == 0:
                _l10_cache_scrivi(cache)
                log(f"[L10 reale] [{fatti}/{len(da_interrogare)}] fatto (cache salvata).")
            elif fatti % 20 == 0 or fatti == len(da_interrogare):
                log(f"[L10 reale] [{fatti}/{len(da_interrogare)}] fatto.")

    if falliti:
        log(f"[L10 reale] {len(falliti)} giocatori non letti al primo giro "
            f"(errori/rate limit): secondo tentativo fra {L10_RETRY_PAUSA:g}s...")
        time.sleep(L10_RETRY_PAUSA)
        ancora = []
        for slug in falliti:
            valore, esito = fetch_l10_reale(slug)
            l10_map[slug] = valore
            if esito == 'errore':
                ancora.append(slug)
            else:
                cache[slug] = {'l10': valore, 'ts': ts_ora}
        falliti = ancora
    _l10_cache_scrivi(cache)

    senza_storico = sum(1 for s_, v in l10_map.items() if v is None and s_ not in falliti)
    if falliti:
        log(f"[L10 reale] ATTENZIONE: {len(falliti)} giocatori restano NON LETTI dopo il "
            f"retry -- per loro l'L10 vale 0 nei conti, quindi il cap risulta piu' largo "
            f"del reale. Esempi: {falliti[:5]}")
    log(f"[L10 reale] Letti {len(slugs) - len(falliti) - senza_storico}/{len(slugs)}; "
        f"{senza_storico} senza storico, {len(falliti)} non letti.")
    return l10_map


# ruolo -> nome file script in formazione_<lega>/predict/
ROLE_SCRIPTS = {
    'gk': 'test_gk.py',
    'def': 'test_def.py',
    'mid': 'test_mid.py',
    'fwd': 'test_mls_fwd_all.py',  # nome storico, riusato identico per tutte le leghe
}

ROLE_LABELS = {
    'gk': 'PORTIERE',
    'def': 'DIFENSORE',
    'mid': 'CENTROCAMPISTA',
    'fwd': 'ATTACCANTE',
}

# Leghe con discovery GLOBALE completa per tutti e 4 i ruoli (aggiornato 31/07:
# austria/croazia/germania2 per il backlog Contender, scozia lega a se').
# Aggiornare quando altre leghe completano la discovery globale su tutti i ruoli.
LEGHE_SUPPORTATE = ('mls', 'kleague', 'germania', 'austria', 'croazia', 'germania2', 'scozia')

RIGA_GIOCATORE_RE = re.compile(r'^\d+\)\s+([\w\-]+):\s+(-?\d+)\s+pt attesi \((-?\d+)-(-?\d+)\)\s*$')
RIGA_ORDINAMENTO_RE = re.compile(r'^\s*ORDINAMENTO:\s*(-?\d+(?:\.\d+)?)\s*$')
RIGA_SQUADRA_RE = re.compile(r'^\s*SQUADRA:\s*(\S+)\s*\|\s*AVVERSARIO:\s*(\S+)\s*$')


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [best_five] {msg}")


def discovery_global_dir(lega, ruolo):
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', f'{lega}_{ruolo}_discovery_global')


def carica_pool_qualita_filtrato(lega, ruolo):
    """Legge player_slugs.json della discovery globale -- gia' filtrato per
    qualita' (media L5/L10/L40 >= soglia) a monte da filter_by_quality().
    In piu' (30/07): applica il CAP per qualita' (BEST_FIVE_TOP_K_QUALITA),
    tenendo solo i top-K per media L5/L10/L40 (player_quality.json, stesso
    valore gia' calcolato in discovery_global) -- riduce ulteriormente il
    numero di candidati che arrivano al controllo starterOdds."""
    path = os.path.join(discovery_global_dir(lega, ruolo), 'player_slugs.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Discovery globale non trovata per {ruolo}: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        slugs = json.load(f)

    if BEST_FIVE_TOP_K_QUALITA <= 0:
        return slugs

    quality_path = os.path.join(discovery_global_dir(lega, ruolo), 'player_quality.json')
    if not os.path.exists(quality_path):
        log(f"[{ruolo}] player_quality.json non trovato -- cap qualita' NON applicato "
            f"(serve rilanciare la discovery_global per generarlo), pool completo usato.")
        return slugs

    if len(slugs) <= BEST_FIVE_TOP_K_QUALITA:
        return slugs

    with open(quality_path, encoding='utf-8') as f:
        quality_map = json.load(f)
    slugs_ordinati = sorted(slugs, key=lambda s: quality_map.get(s, 0.0), reverse=True)
    scartati = len(slugs) - BEST_FIVE_TOP_K_QUALITA
    log(f"[{ruolo}] Cap qualita': tenuti i top {BEST_FIVE_TOP_K_QUALITA}/{len(slugs)} per media "
        f"L5/L10/L40 ({scartati} scartati prima del controllo starterOdds).")
    return slugs_ordinati[:BEST_FIVE_TOP_K_QUALITA]


def prefiltra_starter_odds(ruolo, slugs, soglia=MIN_STARTER_ODDS_PREFILTER):
    """Interroga la query leggera starterOdds per ciascuno slug e tiene solo
    chi ha odds >= soglia sulla prossima partita. Chi ha odds mancanti (nessuna
    partita futura fissata, dato non disponibile) viene ESCLUSO -- e' un dato
    ignoto tanto quanto uno basso, e l'utente non lo sceglierebbe comunque."""
    sopravvissuti = []
    for idx, slug in enumerate(slugs, 1):
        odds = fetch_next_match_starter_odds(slug)
        esito = f"{odds:.0%}" if odds is not None else "N/D"
        if odds is not None and odds >= soglia:
            # (slug, odds): le odds servono a valle per il tie-break fra
            # candidati con punteggio quasi identico (31/07, richiesta
            # esplicita utente) -- prima venivano usate solo per filtrare e
            # poi buttate via.
            sopravvissuti.append((slug, odds))
            log(f"[{ruolo}] [{idx}/{len(slugs)}] {slug}: starterOdds={esito} -> TENUTO")
        else:
            log(f"[{ruolo}] [{idx}/{len(slugs)}] {slug}: starterOdds={esito} -> scartato (< {soglia:.0%})")
        time.sleep(0.3)
    return sopravvissuti


# --- Riuso delle predizioni della stessa giornata (31/07, richiesta esplicita
# utente: "una cache predizione su giornata... lancio korea standalone, registra
# le predizioni; poi lancio korea e mls insieme, korea usa quelle cachate e mls
# fa tutto dall'inizio") -----------------------------------------------------
#
# CHIAVE DI VALIDITA': il kickoff della partita predetta, che i file
# prediction_<slug>_*.txt scrivono gia' nella riga 'Data: YYYY-MM-DDTHH:MM'
# (la stessa da cui build_consiglio_<ruolo>.py ricava il campo KICKOFF). Non
# serve conoscere il numero di giornata: se quel kickoff e' ANCORA NEL FUTURO,
# la "prossima partita" del giocatore e' la stessa di quando la predizione e'
# stata calcolata, quindi la predizione vale ancora. Se e' passato, la
# prossima partita e' un'altra e va ricalcolata. Questo rende la scadenza
# automaticamente tarata sulla giornata, senza doverla configurare.
#
# Le starterOdds NON entrano nella chiave, ed e' corretto (osservazione
# dell'utente): sono un filtro applicato PRIMA, a monte -- se cambiano, il
# giocatore semplicemente non supera il prefiltro e non arriva qui, ma il
# punteggio atteso per quella partita resta lo stesso.
#
# Tetto di eta' come rete di sicurezza: se fra le due run e' stata giocata
# un'altra partita o sono cambiati i parametri del modello, la forma recente
# puo' essersi mossa. Oltre PREDIZIONI_MAX_ORE si ricalcola comunque.
RIUSA_PREDIZIONI = os.environ.get('BEST_FIVE_RIUSA_PREDIZIONI', '1').strip() not in ('0', 'false', 'no', '')
PREDIZIONI_MAX_ORE = float(os.environ.get('BEST_FIVE_PREDIZIONI_MAX_ORE', '72'))

_DATA_PREDIZIONE_RE = re.compile(r'^Data:\s+(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?)\s*$', re.MULTILINE)

# Finestra della GIORNATA corrente, risolta una volta sola per run.
# 31/07 (osservazione dell'utente): "piu' che una finestra temporale bisognava
# agganciarlo alla fine della gw, come abbiamo fatto per il generatore". Vero:
# 'kickoff ancora futuro' + un tetto di ore e' un'approssimazione, mentre la
# giornata ha un inizio e una fine ESATTI. Con l'aggancio alla fixture una
# predizione vale se e solo se la partita che predice sta DENTRO questa
# giornata -- una predizione per la giornata successiva non viene riusata per
# quella corrente, e alla chiusura della giornata scade da sola senza che
# nessuna soglia debba indovinare quando.
# Nessun input GAMEWEEK qui (l'utente ha scelto di non aggiungerlo a Best
# Five): risolvi_fixture() senza GAMEWEEK/FIXTURE_SLUG risolve da sola la
# giornata in corso o la prossima, che e' esattamente quella per cui Best Five
# sta lavorando. Una sola query per run.
_FINESTRA_GW = [None]  # None = non ancora risolta; False = risoluzione fallita


def _finestra_giornata():
    """(inizio, fine) ISO della giornata corrente, o None se non risolvibile
    (nessun cookie, rete assente, run locale di test) -- in quel caso si
    ricade sulla regola 'kickoff ancora futuro' + tetto di ore."""
    if _FINESTRA_GW[0] is not None:
        return _FINESTRA_GW[0] or None
    try:
        spec = importlib.util.spec_from_file_location(
            'discovery_fixture_best_five', os.path.join(REPO_ROOT, 'discovery_fixture.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fx = mod.risolvi_fixture()
    except Exception as e:
        log(f"[predizioni] finestra giornata non risolvibile ({e!r}) -- "
            f"ricado su 'kickoff futuro' + tetto {PREDIZIONI_MAX_ORE:g}h.")
        _FINESTRA_GW[0] = False
        return None
    if not fx:
        _FINESTRA_GW[0] = False
        return None
    inizio = (fx.get('startDate') or '')[:19]
    fine = (fx.get('endDate') or '')[:19]
    if not inizio or not fine:
        _FINESTRA_GW[0] = False
        return None
    log(f"[predizioni] giornata corrente: {fx.get('slug')} (gameweek "
        f"{fx.get('seasonGameWeek')}) dal {inizio} al {fine} -- riuso ancorato a questa.")
    _FINESTRA_GW[0] = (inizio, fine)
    return _FINESTRA_GW[0]


def _predizione_riutilizzabile(lega, ruolo, slug, adesso=None):
    """True se esiste gia' una predizione valida per la PROSSIMA partita di
    questo giocatore -- vedi il commento sopra per la regola. Ritorna
    (riusabile, kickoff, path_del_file) -- il path serve a ricopiare la
    predizione dove il passo consiglio se la aspetta."""
    if not RIUSA_PREDIZIONI:
        return False, None, None
    candidati = glob.glob(os.path.join(_dir_predizioni_best_five(lega, ruolo),
                                        f'prediction_{slug}_*.txt'))
    candidati += glob.glob(os.path.join(output_dir_per_ruolo(lega, ruolo),
                                         f'prediction_{slug}_*.txt'))
    if not candidati:
        return False, None, None
    adesso = adesso or datetime.datetime.utcnow()
    finestra = _finestra_giornata()
    for path in sorted(candidati, key=_timestamp_da_nome_file, reverse=True):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                m = _DATA_PREDIZIONE_RE.search(f.read())
        except OSError:
            continue
        if not m:
            continue
        if finestra:
            # Aggancio alla GIORNATA (preferito): vale se e solo se la partita
            # predetta cade dentro la finestra reale della fixture corrente.
            inizio, fine = finestra
            ko19 = m.group(1) if len(m.group(1)) > 10 else m.group(1) + 'T00:00'
            ko19 = ko19[:19]
            if inizio[:16] <= ko19[:16] <= fine[:16]:
                return True, m.group(1), path
            continue
        # Fallback (giornata non risolvibile): kickoff ancora futuro + tetto
        # di eta' sul file.
        if (adesso - _timestamp_da_nome_file(path)).total_seconds() / 3600.0 > PREDIZIONI_MAX_ORE:
            continue
        try:
            kickoff = datetime.datetime.fromisoformat(m.group(1))
        except ValueError:
            continue
        if kickoff > adesso:
            return True, m.group(1), path
    return False, None, None


def _dir_predizioni_best_five(lega, ruolo):
    """Cartella isolata dove Best Five tiene le proprie predizioni (vedi
    _isola_output_best_five: NON quella condivisa con la produzione)."""
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five', f'_raw_{ruolo}')


def _timestamp_da_nome_file(path):
    """Timestamp dal NOME del file, non dall'mtime: un git checkout/pull
    riscrive gli mtime e li rende inservibili (stesso motivo per cui il
    controllo di freschezza in build_formazione_globale.py legge il nome)."""
    m = re.search(r'_(\d{4}-\d{2}-\d{2})_(\d{6})\.txt$', os.path.basename(path))
    if not m:
        return datetime.datetime.min
    try:
        return datetime.datetime.strptime(m.group(1) + m.group(2), '%Y-%m-%d%H%M%S')
    except ValueError:
        return datetime.datetime.min


def run_prediction_su_slug(lega, ruolo, slug):
    """Esegue test_<ruolo>.py su UN SOLO giocatore (TARGET_SLUG), PLAYER_POOL=global
    cosi' DISCOVERY_FILE punta comunque al pool globale (serve solo per il
    fallback/coerenza interna dello script, il TARGET_SLUG bypassa la lista)."""
    riusabile, kickoff, path_riuso = _predizione_riutilizzabile(lega, ruolo, slug)
    if riusabile:
        # La predizione riusata puo' stare nella cartella ISOLATA di Best Five
        # (_raw_<ruolo>, dove la sposta _isola_output_best_five a fine run),
        # mentre il passo successivo -- build_consiglio_<ruolo>.py via
        # slugs_con_prediction/trova_output_per_slug -- guarda SOLO in
        # <lega>_<ruolo>_all. Senza questa copia il giocatore sparirebbe dal
        # consiglio proprio perche' la sua predizione era gia' pronta.
        dest_dir = output_dir_per_ruolo(lega, ruolo)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(path_riuso))
        if os.path.abspath(path_riuso) != os.path.abspath(dest):
            shutil.copy2(path_riuso, dest)
        log(f"[{ruolo}] {slug}: predizione gia' su disco per la partita del {kickoff} "
            f"(ancora futura) -- RIUSATA, nessuna query.")
        return

    script = ROLE_SCRIPTS[ruolo]
    script_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'predict', script)
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script non trovato: {script_path}")

    env = dict(os.environ)
    env['PLAYER_POOL'] = 'global'
    env['TARGET_SLUG'] = slug
    env.pop('CALIBRATION_MODE', None)

    proc = subprocess.run([sys.executable, script_path], cwd=REPO_ROOT, env=env)
    if proc.returncode != 0:
        log(f"[{ruolo}] ATTENZIONE: processo terminato con codice {proc.returncode} per {slug} "
            f"(procedo comunque con il prossimo).")


def run_prediction_pool_prefiltrato(lega, ruolo):
    """Carica il pool globale (gia' filtrato per qualita'), applica il
    prefiltro starterOdds>=soglia, poi lancia UN subprocess per slug
    sopravvissuto (stile job matrix della pipeline di produzione)."""
    pool = carica_pool_qualita_filtrato(lega, ruolo)
    log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
    log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} sulla prossima partita...")
    sopravvissuti = prefiltra_starter_odds(ruolo, pool)
    log(f"[{ruolo}] Sopravvissuti al prefiltro: {len(sopravvissuti)}/{len(pool)}.")

    for idx, (slug, _odds) in enumerate(sopravvissuti, 1):
        log(f"[{ruolo}] [{idx}/{len(sopravvissuti)}] Predizione per {slug}...")
        run_prediction_su_slug(lega, ruolo, slug)
        if idx < len(sopravvissuti):
            time.sleep(2.0)


def output_dir_per_ruolo(lega, ruolo):
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', f'{lega}_{ruolo}_all')


def trova_ultimo_output(lega, ruolo):
    """Trova il file prediction_all_*.txt piu' recente per il ruolo (formato
    VECCHIO, scritto da un'esecuzione sull'intero pool senza TARGET_SLUG —
    es. GK/DEF di questa lega, gia' committati prima del prefiltro
    starterOdds). Ritorna None se non esiste (ruolo mai eseguito in modalita'
    pool intero -- vedi trova_output_per_slug per il formato NUOVO)."""
    out_dir = output_dir_per_ruolo(lega, ruolo)
    candidati = glob.glob(os.path.join(out_dir, 'prediction_all_*.txt'))
    if not candidati:
        return None
    return max(candidati, key=os.path.getmtime)


def trova_output_per_slug(lega, ruolo):
    """Formato NUOVO (prefiltro starterOdds): un file prediction_<slug>_*.txt
    per ogni giocatore sopravvissuto al prefiltro, uno per subprocess (stile
    job matrix). Ritorna il piu' recente per ciascuno slug trovato."""
    out_dir = output_dir_per_ruolo(lega, ruolo)
    tutti = glob.glob(os.path.join(out_dir, 'prediction_*_*.txt'))
    per_slug = {}
    for path in tutti:
        base = os.path.basename(path)
        if base.startswith('prediction_all_'):
            continue
        m = re.match(r'^prediction_(.+)_\d{4}-\d{2}-\d{2}_\d{6}\.txt$', base)
        if not m:
            continue
        slug = m.group(1)
        if slug not in per_slug or os.path.getmtime(path) > os.path.getmtime(per_slug[slug]):
            per_slug[slug] = path
    return list(per_slug.values())


def parse_riepilogo(path):
    """Estrae dal riepilogo comparativo in cima al file la lista ordinata
    (stesso ORDINAMENTO gia' calcolato da test_<ruolo>.py) di
    (slug, pt_attesi, low, high, ordinamento, squadra, avversario)."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    righe = []
    corrente = None
    for line in testo.splitlines():
        m = RIGA_GIOCATORE_RE.match(line)
        if m:
            if corrente:
                righe.append(corrente)
            corrente = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        # Fine del blocco riepilogo (sezione esclusi o separatore finale) --
        # smette di cercare altre righe giocatore dopo la prima riga vuota
        # successiva a un blocco gia' iniziato, o alla sezione "Esclusi".
        if corrente is not None:
            m2 = RIGA_ORDINAMENTO_RE.match(line)
            if m2:
                corrente['ordinamento'] = float(m2.group(1))
                continue
            m3 = RIGA_SQUADRA_RE.match(line)
            if m3:
                corrente['squadra'] = m3.group(1)
                corrente['avversario'] = m3.group(2)
                continue
        if line.startswith('--- Esclusi') or line.startswith('#' * 10):
            break
    if corrente:
        righe.append(corrente)

    # Si ordina sempre per pt_attesi (score MOSTRATO, con shrinkage) --
    # ALLINEATO alla produzione (30/07, "Revert score_ordinamento": il
    # ranking per ORDINAMENTO senza shrinkage duplicato qui aveva prodotto
    # proprio il caso reale che ha fatto scattare il revert, un DEF con 4
    # partite preferito a due backup piu' stabili). Il campo 'ordinamento'
    # resta nel dizionario solo per diagnostica, non entra piu' nel sort.
    righe.sort(key=lambda r: r['pt_attesi'], reverse=True)
    return righe


def parse_file_singolo_slug(path):
    """Estrae la singola riga consiglio da un file prediction_<slug>_*.txt
    (formato NUOVO, un giocatore per file) -- stesso schema di riga di
    parse_riepilogo, riusa le stesse regex."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    riga = None
    for line in testo.splitlines():
        m = RIGA_GIOCATORE_RE.match(line)
        if m:
            riga = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        if riga is not None:
            m2 = RIGA_ORDINAMENTO_RE.match(line)
            if m2:
                riga['ordinamento'] = float(m2.group(1))
                continue
            m3 = RIGA_SQUADRA_RE.match(line)
            if m3:
                riga['squadra'] = m3.group(1)
                riga['avversario'] = m3.group(2)
                continue
            break  # dopo la prima riga giocatore, il resto e' il dump completo -- basta cosi'
    return riga


# ruolo -> nome file script in formazione_<lega>/consiglio/
CONSIGLIO_SCRIPTS = {
    'gk': 'build_consiglio_gk.py',
    'def': 'build_consiglio_def.py',
    'mid': 'build_consiglio_mid.py',
    'fwd': 'build_consiglio.py',  # nome storico (FWD), stesso di ROLE_SCRIPTS['fwd']
}

CONSIGLIO_RIGA_RE = re.compile(r'^\d+\)\s+([\w\-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')

_SLUG_DA_FILENAME_RE = re.compile(r'^prediction_(.+)_\d{4}-\d{2}-\d{2}_\d{6}\.txt$')


def _odds_run_corrente():
    """{slug: odds} dei sopravvissuti al prefiltro di QUESTO run (31/07,
    richiesta esplicita utente): serve ad attaccare le starterOdds alle righe
    del consiglio, cosi' il tie-break condiviso con la produzione
    (_sort_ordinamento in build_formazione_globale.py) puo' preferire un
    titolare all'80% a uno al 70% quando i punteggi sono quasi pari. Vuoto in
    uso locale/manuale, dove PREFILTRO_GRUPPI non e' impostata: in quel caso
    nessun bonus e comportamento invariato."""
    items = _sopravvissuti_run_corrente()
    if not items:
        return {}
    return {it['slug']: it['odds'] for it in items if it.get('odds') is not None}


def _attach_odds(role_data_dict, odds_map):
    """Attacca 'starter_odds' a ogni riga per cui l'abbiamo."""
    if not odds_map:
        return
    for rows in role_data_dict.values():
        for r in rows:
            odds = odds_map.get(r['slug'])
            if odds is not None:
                r['starter_odds'] = odds


def _sopravvissuti_run_corrente():
    """Lista {'ruolo','slug'} sopravvissuta al prefiltro starterOdds di
    QUESTO run (passata dal job 'prefiltro_merge' via env PREFILTRO_GRUPPI,
    stesso JSON dei gruppi mandati al predict -- vedi _gruppi_da_items).
    None se non impostata (uso manuale/locale, nessun filtro extra).

    FIX BUG REALE (30/07, segnalato dall'utente): senza questo controllo,
    slugs_con_prediction prendeva QUALUNQUE prediction_<slug>_*.txt gia'
    presente nella cartella -- condivisa con la pipeline di produzione, che
    scrive li' le SUE predizioni per i posseduti, a QUALUNQUE starterOdds
    (test_<ruolo>.py non filtra per starterOdds, MIN_STARTER_ODDS e'
    disattivato li'). Risultato osservato: due giocatori con starterOdds
    30% e 70% finiti nella formazione nonostante soglia=80%, perche' un
    file prediction_<slug>_*.txt per loro esisteva gia' (da un run
    precedente, non necessariamente di Best Five) e veniva ripescato senza
    ricontrollare la soglia DI QUESTO run."""
    raw = os.environ.get('PREFILTRO_GRUPPI', '').strip()
    if not raw:
        return None
    try:
        gruppi = json.loads(raw)
    except json.JSONDecodeError:
        log("ATTENZIONE: PREFILTRO_GRUPPI non e' JSON valido, ignorato (nessun filtro extra).")
        return None
    items = []
    for g in gruppi:
        items.extend(json.loads(base64.b64decode(g['g']).decode()))
    return items


def slugs_con_prediction(lega, ruolo):
    """Slug per cui esiste almeno un prediction_<slug>_*.txt (formato NUOVO,
    un file per giocatore) -- l'insieme da passare a build_consiglio_<ruolo>.py
    via CONSIGLIO_DISCOVERY_FILE. Se PREFILTRO_GRUPPI e' impostata (run da
    workflow), filtra ANCHE per chi ha davvero superato il prefiltro
    starterOdds DI QUESTO run (vedi _sopravvissuti_run_corrente)."""
    slugs = []
    for path in trova_output_per_slug(lega, ruolo):
        m = _SLUG_DA_FILENAME_RE.match(os.path.basename(path))
        if m:
            slugs.append(m.group(1))

    sopravvissuti = _sopravvissuti_run_corrente()
    if sopravvissuti is not None:
        ammessi = {it['slug'] for it in sopravvissuti if it['ruolo'] == ruolo}
        prima = len(slugs)
        slugs = [s for s in slugs if s in ammessi]
        scartati = prima - len(slugs)
        if scartati:
            log(f"[{ruolo}] {scartati} slug con prediction gia' su disco ma NON sopravvissuti al "
                f"prefiltro di questo run -- esclusi dalla formazione.")
    return sorted(slugs)


def esegui_consiglio(lega, ruolo):
    """Chiama DAVVERO build_consiglio_<ruolo>.py (lo stesso script della
    pipeline di produzione, in subprocess) invece di duplicare qui la logica
    di parsing/ordinamento -- zero drift quando quella cambia (30/07: la
    produzione ha cambiato il criterio di ordinamento DEF/FWD mentre questo
    file duplicava ancora quello vecchio, vedi 'Revert score_ordinamento').
    Punta CONSIGLIO_DISCOVERY_FILE ai soli slug del pool Best Five (non i
    posseduti) tramite un JSON temporaneo. Ritorna il path del
    consiglio_*.txt generato, o None se non ci sono predizioni per questo
    ruolo o lo script fallisce (in quel caso si ricade sul parsing diretto)."""
    slugs = slugs_con_prediction(lega, ruolo)
    if not slugs:
        return None
    script = CONSIGLIO_SCRIPTS.get(ruolo)
    script_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'consiglio', script or '')
    if not script or not os.path.exists(script_path):
        return None

    tmp_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five')
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    slugs_path = os.path.join(tmp_dir, f'_consiglio_slugs_{ruolo}.json')
    with open(slugs_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f)

    env = dict(os.environ)
    env['CONSIGLIO_DISCOVERY_FILE'] = slugs_path
    proc = subprocess.run([sys.executable, script_path], cwd=REPO_ROOT, env=env,
                           capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"[{ruolo}] ATTENZIONE: {script} ha fallito (codice {proc.returncode}): "
            f"{proc.stderr[-500:]} — ricado sul parsing diretto.")
        return None
    m = re.search(r'Salvato in:\s*(\S+)', proc.stdout)
    if not m:
        log(f"[{ruolo}] ATTENZIONE: {script} non ha stampato il path di output atteso "
            f"— ricado sul parsing diretto.")
        return None
    # Il path stampato e' relativo alla cwd del SUBPROCESS (REPO_ROOT), non
    # necessariamente alla cwd di QUESTO processo (es. nei test) -- risolto
    # esplicitamente per evitare un FileNotFoundError silenzioso.
    consiglio_path = os.path.join(REPO_ROOT, m.group(1))
    return _isola_output_best_five(lega, ruolo, consiglio_path, slugs)


def _isola_output_best_five(lega, ruolo, consiglio_path, slugs):
    iso_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five', f'_raw_{ruolo}')
    os.makedirs(iso_dir, exist_ok=True)
    shared_dir = output_dir_per_ruolo(lega, ruolo)

    dest_consiglio = consiglio_path
    if consiglio_path and os.path.exists(consiglio_path):
        dest_consiglio = os.path.join(iso_dir, os.path.basename(consiglio_path))
        shutil.move(consiglio_path, dest_consiglio)

    for slug in slugs:
        for p in glob.glob(os.path.join(shared_dir, f'prediction_{slug}_*.txt')):
            shutil.move(p, os.path.join(iso_dir, os.path.basename(p)))

    return dest_consiglio


def parse_consiglio_output(path):
    """Estrae il ranking gia' pronto (gia' ordinato da build_consiglio_<ruolo>.py
    -- NESSUN re-sort qui, l'ordine del file e' quello giusto)."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    righe = []
    corrente = None
    for line in testo.splitlines():
        m = CONSIGLIO_RIGA_RE.match(line.strip())
        if m:
            if corrente:
                righe.append(corrente)
            corrente = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        if corrente is not None:
            m2 = RIGA_SQUADRA_RE.match(line)
            if m2:
                corrente['squadra'] = m2.group(1)
                corrente['avversario'] = m2.group(2)
                continue
        if line.startswith('(') and 'esclusi' in line:
            break
    if corrente:
        righe.append(corrente)
    return righe


def costruisci_best_five(lega, ruoli, n_backup):
    risultati = {}
    for ruolo in ruoli:
        path_all = trova_ultimo_output(lega, ruolo)
        # Il formato VECCHIO (pool intero) ha la PRECEDENZA solo se e'
        # davvero il piu' recente -- FIX (30/07, bug reale segnalato
        # dall'utente): senza questo confronto, un run FRESCO in formato
        # NUOVO (es. GK/DEF ricalcolati oggi) veniva scartato in favore di un
        # prediction_all_*.txt vecchio di ore, perche' il vecchio formato
        # aveva sempre la precedenza a prescindere dall'eta'. Le starterOdds
        # cambiano di continuo, un risultato di ore fa non va bene per un
        # uso ripetuto nel tempo (non solo "oggi").
        per_slug_paths = trova_output_per_slug(lega, ruolo)
        piu_recente_per_slug = max((os.path.getmtime(p) for p in per_slug_paths), default=None)
        if path_all and piu_recente_per_slug is not None and piu_recente_per_slug > os.path.getmtime(path_all):
            log(f"[{ruolo}] Formato pool intero ({os.path.basename(path_all)}) piu' vecchio "
                f"dei risultati per-slug piu' recenti -- ignorato, uso quelli freschi.")
            path_all = None
        consiglio_path = None if path_all else esegui_consiglio(lega, ruolo)
        if path_all:
            # Formato VECCHIO (pool intero, es. GK/DEF K League gia'
            # committati prima del prefiltro starterOdds) -- parse_riepilogo
            # ordina comunque per pt_attesi, vedi sopra.
            righe = parse_riepilogo(path_all)
            log(f"[{ruolo}] {len(righe)} giocatori trovati nel riepilogo di {os.path.basename(path_all)} "
                f"(formato pool intero).")
        elif consiglio_path:
            righe = parse_consiglio_output(consiglio_path)
            log(f"[{ruolo}] {len(righe)} giocatori trovati nel consiglio prodotto da "
                f"{CONSIGLIO_SCRIPTS[ruolo]} (delegato alla produzione, zero logica duplicata).")
        else:
            # Fallback: build_consiglio_<ruolo>.py non disponibile/fallito --
            # parsing diretto dei file per-slug, sort per pt_attesi (allineato
            # comunque al criterio attuale di produzione, vedi parse_riepilogo).
            paths = trova_output_per_slug(lega, ruolo)
            righe = [r for r in (parse_file_singolo_slug(p) for p in paths) if r]
            righe.sort(key=lambda r: r['pt_attesi'], reverse=True)
            log(f"[{ruolo}] {len(righe)} giocatori trovati in {len(paths)} file prediction_<slug>_*.txt "
                f"(fallback, parsing diretto).")
        if not righe:
            log(f"[{ruolo}] Nessun output trovato in {output_dir_per_ruolo(lega, ruolo)} "
                f"— esegui con --run per generarlo.")
        risultati[ruolo] = righe[:1 + n_backup]
    return risultati


def formatta_report(lega, risultati, n_backup):
    lines = []
    lines.append("=" * 70)
    lines.append(f"BEST FIVE — {lega.upper()} (titolare + {n_backup} backup per ruolo)")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("Pool: TUTTI i giocatori della lega (discovery globale), non solo posseduti.")
    lines.append("=" * 70)
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        candidati = risultati.get(ruolo, [])
        lines.append("")
        lines.append(f"--- {ROLE_LABELS[ruolo]} ---")
        if not candidati:
            lines.append("  (nessun dato disponibile)")
            continue
        for idx, c in enumerate(candidati):
            ruolo_str = "TITOLARE" if idx == 0 else f"BACKUP {idx}"
            lines.append(f"  [{ruolo_str}] {c['slug']}: {c['pt_attesi']} pt attesi "
                         f"({c['low']}-{c['high']}) | squadra={c['squadra'] or 'N/D'} "
                         f"avversario={c['avversario'] or 'N/D'}")
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


# Stessi colori per ruolo del generatore formazioni principale
# (formazione_mls/build_formazione_finale.py, ROLE_COLORS_HTML) — coerenza
# visiva tra i due report HTML.
ROLE_COLORS_HTML = {'gk': '#8b7cf6', 'def': '#3aa1e8', 'mid': '#2fbf8f', 'fwd': '#ef5b5b'}

HTML_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #0a0d12; --surface: #131a23; --surface-2: #1c2530;
    --text: #edf1f6; --muted: #8a93a6; --gold: #f4c542; --border: rgba(255,255,255,0.08);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f3f4f7; --surface: #ffffff; --surface-2: #eef0f4;
      --text: #1a2029; --muted: #5b6474; --border: rgba(20,25,35,0.08);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
    padding: 40px 24px 64px; max-width: 900px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 6px; }}
  .subhead {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 32px; }}
  /* Layout A RIGA (30/07, richiesta esplicita utente): i 4 ruoli affiancati
     in un'unica riga -- stessa struttura orizzontale della formazione vera
     (formazione_mls/build_formazione_finale.py, .lineup-row/.card-strip),
     non piu' una sezione per ruolo impilata verticalmente. */
  .formazione-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .ruolo-colonna {{ flex: 1 1 200px; min-width: 180px; }}
  .role-title {{
    font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--role-color); margin-bottom: 10px;
  }}
  .pcard {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px; position: relative; margin-bottom: 8px;
  }}
  .pcard.titolare {{ border-color: var(--role-color); box-shadow: 0 0 0 1px var(--role-color); }}
  .pcard.backup {{ padding: 8px 10px; }}
  .pcard-tag {{
    font-size: 0.55rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--role-color); margin-bottom: 6px;
  }}
  .pcard.backup .pcard-tag {{ margin-bottom: 2px; }}
  .pcard-name {{ font-size: 0.8rem; font-weight: 650; line-height: 1.25; margin-bottom: 6px; }}
  .pcard.backup .pcard-name {{ font-size: 0.72rem; margin-bottom: 2px; }}
  .pcard-score {{ font-size: 1.3rem; font-weight: 800; color: var(--role-color); font-variant-numeric: tabular-nums; }}
  .pcard.backup .pcard-score {{ font-size: 0.9rem; }}
  .pcard-range {{ font-size: 0.62rem; color: var(--muted); margin-bottom: 6px; }}
  .pcard.backup .pcard-range {{ margin-bottom: 0; }}
  .pcard-match {{ font-size: 0.66rem; color: var(--text); opacity: 0.8; line-height: 1.3; }}
  .pcard.backup .pcard-match {{ display: none; }}
  .empty {{ color: var(--muted); font-size: 0.8rem; }}
  .footer {{ margin-top: 32px; color: var(--muted); font-size: 0.72rem; }}
</style>
</head>
<body>
<h1>{page_title}</h1>
<p class="subhead">{page_subhead}</p>
<div class="formazione-row">
{colonne_ruolo}
</div>
<p class="footer">{footer}</p>
</body>
</html>
"""


def _card_html(c, ruolo, is_titolare):
    tag = "TITOLARE" if is_titolare else "BACKUP"
    color = ROLE_COLORS_HTML[ruolo]
    match = f"{c['squadra'] or 'N/D'} vs {c['avversario'] or 'N/D'}"
    classe = "pcard titolare" if is_titolare else "pcard backup"
    return (
        f'<div class="{classe}" style="--role-color:{color}">'
        f'<div class="pcard-tag">{tag}</div>'
        f'<div class="pcard-name">{c["slug"]}</div>'
        f'<div class="pcard-score">{c["pt_attesi"]}</div>'
        f'<div class="pcard-range">{c["low"]}-{c["high"]} pt attesi</div>'
        f'<div class="pcard-match">{match}</div>'
        f'</div>'
    )


def formatta_report_html(lega, risultati, n_backup):
    colonne = []
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        candidati = risultati.get(ruolo, [])
        color = ROLE_COLORS_HTML[ruolo]
        cards = "".join(_card_html(c, ruolo, idx == 0) for idx, c in enumerate(candidati))
        body = cards if candidati else '<p class="empty">Nessun dato disponibile.</p>'
        colonne.append(
            f'<div class="ruolo-colonna">'
            f'<div class="role-title" style="--role-color:{color}">{ROLE_LABELS[ruolo]}</div>'
            f'{body}'
            f'</div>'
        )

    page_title = f"Best Five — {lega.upper()}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"titolare + {n_backup} backup per ruolo, pool TUTTI i giocatori "
                     f"della lega (discovery globale, non solo posseduti).")
    footer = ("Script separato e READ-ONLY rispetto alla pipeline di produzione — non tiene conto "
              "di budget/anti-stack/sinergie/multi-lineup.")
    return HTML_TEMPLATE.format(page_title=page_title, page_subhead=page_subhead,
                                 colonne_ruolo="\n".join(colonne), footer=footer)


# --- Formazione VERA (30/07, richiesta esplicita utente: "voglio la miglior
# formazione con sinergie/combinazioni come fa il tool unificato, non un
# elenco top-5 per ruolo") ---------------------------------------------
#
# FIX 31/07 (audit di allineamento, richiesto dall'utente prima di fidarsi
# dei risultati): questa funzione chiamava PRIMA bff.generate_lineups_for_type
# di formazione_mls/build_formazione_finale.py -- che il file STESSO segnala
# in un commento (righe ~1748) come "!!! NON USATA IN PRODUZIONE (accertato
# 31/07, audit completo) !!!": tre parametri diversi da quelli reali per le
# formazioni IN_SEASON --
#   - variance_mode=True sempre (produzione: False per MLS/KLEAGUE_IN_SEASON,
#     VARIANCE_MODE_TYPES le esclude esplicitamente)
#   - apply_positive_synergy=True sulla prima formazione quando ne sono
#     richieste 2+ (produzione: SEMPRE False per le In Season)
#   - synergy_bonus_dict=IN_SEASON_SYNERGY_BONUS_BY_PAIR passato esplicito
#     (produzione non lo passa MAI -- vedi commento IN_SEASON_SYNERGY_
#     BONUS_BY_PAIR "NON USATA IN PRODUZIONE")
# Risultato: Best Five poteva scegliere/ordinare i candidati in modo diverso
# da quello che il tool unificato sceglierebbe DAVVERO con lo stesso pool.
#
# Ora si riusa DAVVERO l'orchestratore di produzione (generatore_formazioni/
# build_formazione_globale.py, lo stesso file che gira in
# formazione_giornata.yml) importato dinamicamente come modulo a se' --
# stessa tecnica di importlib gia' usata li' per formazione_mls/build_
# formazione_finale.py. Si chiama la SUA generate_lineups_for_type(tipo,
# count, role_data, pools, card_pool) con tipo='MLS_IN_SEASON'/'KLEAGUE_
# IN_SEASON' (leghe dedicate) o l'Arena dedicata della lega per le altre --
# stessi nomi di tipo, stessi dizionari (L10_CAP_BY_TYPE, STACK_GUARD_TYPES,
# VARIANCE_MODE_TYPES, CHECK_CAP260_TYPES, XP_BONUS_TYPES,
# CAPTAIN_BONUS_BY_TYPE) che leggerebbe la pipeline reale. Il rendering
# (format_lineup/render_lineup_html) usa lo STESSO'bff' interno al modulo
# 'gg' (non un'istanza separata) perche' e' li' che generatore_formazioni/
# build_formazione_globale.py registra CAPTAIN_BONUS_BY_TYPE['MLS_IN_SEASON']
# ecc. (build_formazione_finale.py da solo conosce solo 'IN_SEASON').
#
# La differenza con la produzione resta SOLO nella CardPool: invece delle
# copie REALMENTE possedute (da player_card_counts.json), si passa una
# CardPool VUOTA (CardPool({}, names=...)) -- CardPool._total_for() ripiega
# gia' da solo su 1 copia IN_SEASON virtuale per qualunque slug non
# presente nei counts, quindi ogni giocatore del pool globale risulta
# "posseduto" con 1 copia, senza scrivere nessun dato finto. Stesso
# meccanismo per il bonus XP: power_bonus_fraction() ritorna 0.0 senza un
# breakdown noto -- coerente con la richiesta precedente dell'utente di
# vedere lo score GREZZO, senza bonus (vedi messaggio 30/07 alla sessione
# "Riassunto evoluzione modello predittivo"), e comunque IDENTICO a come la
# produzione mostra il numero (apply_xp_bonus=False SOLO nel rendering,
# vedi FASE 2 di build_formazione_globale.py).

def _import_gg():
    path = os.path.join(REPO_ROOT, 'generatore_formazioni', 'build_formazione_globale.py')
    spec = importlib.util.spec_from_file_location('gg_best_five', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_consiglio_calibrato(bff, gg, path, ruolo=None):
    """Le righe di un consiglio, sulla STESSA scala della produzione.

    Il generatore calibra all'ingresso (`calibra_riga` in
    `load_league_role_data`, misurato 02/08: `realizzato = 10.21 + 0.767 x
    previsto`), cosi' che in tutto il sistema esista una scala sola: le soglie
    d'arena, i bonus di sinergia e il rapporto punti/L10 sono tutti espressi in
    punteggio REALE. Best Five leggeva gli stessi file SENZA calibrarli, quindi
    confrontava previsioni grezze con costanti tarate sull'altra scala e
    sopravvalutava ogni carta di circa il 13% -- proprio nel numero su cui si
    decide un acquisto.

    Si chiama `gg.calibra_riga`, non una copia locale: i coefficienti devono
    vivere in un posto solo (in questo progetto i file gemelli disallineati
    hanno gia' causato bug veri).

    ruolo (03/08): dal 03/08 la retta di calibrazione e' diversa per ruolo
    (`CALIB_PER_RUOLO`), perche' quella unica appiattiva tre punti di scarto
    fra portieri e attaccanti -- e Best Five confronta proprio carte di ruoli
    diversi fra loro. Senza il ruolo si ricade sulla retta media di prima."""
    rows = bff.parse_consiglio(path)
    for row in rows:
        gg.calibra_riga(row, ruolo)
    return rows


# --- Prezzo minimo di mercato (31/07, richiesta esplicita utente) ----------
#
# Riusa il meccanismo di SCANSIONE di scanners/bot_profit.py (query
# LIVE_OFFERS_QUERY su tokens.liveSingleSaleOffers, con throttling/backoff
# globale gia' tarato -- vedi memoria project_bot_profit_429_varianza_causa_
# ignota) -- NON quello di bots/bot_definitivo.py, che e' il bot che ASCOLTA
# il mercato in tempo reale via websocket (side-effect di blacklist inclusi),
# inadatto a una query puntuale come questa. Solo lettura, nessun effetto
# collaterale (a differenza di bot_profit.py, qui non si aggiorna nessuna
# blacklist/cache -- e' un semplice snapshot).
#
# Interrogato SOLO sui giocatori gia' sopravvissuti al prefiltro starterOdds
# di QUESTA run (role_data_lega/merged_role_data), non sull'intero pool
# scoperto -- stesso principio del prefiltro stesso, il costo resta bounded.
def _import_bot_profit():
    path = os.path.join(REPO_ROOT, 'scanners', 'bot_profit.py')
    spec = importlib.util.spec_from_file_location('bot_profit_best_five', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prezzi_minimi_slug(bp, eth_rate, player_slug):
    """Ritorna (prezzo_minimo_in_season, prezzo_minimo_classic) in EUR per uno
    slug, None per la rarita' senza annunci live -- entrambi calcolati dagli
    STESSI nodi (un solo fetch), a differenza di bp.get_current_minimum che
    ne restituisce uno solo in base alle regole di esclusione lega (qui
    servono SEMPRE entrambi, per mostrarli affiancati)."""
    nodes = bp.fetch_all_live_offers(player_slug)
    prezzi_in_season, prezzi_classic = [], []
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta, non una vendita in denaro
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited' or c.get('sport') != 'FOOTBALL':
                continue
            match = c
            break
        if not match:
            continue
        prezzo = bp.eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if prezzo is None:
            continue
        if match.get('inSeasonEligible'):
            prezzi_in_season.append(prezzo)
        else:
            prezzi_classic.append(prezzo)
    return (min(prezzi_in_season) if prezzi_in_season else None,
            min(prezzi_classic) if prezzi_classic else None)


# Cache prezzi (31/07, richiesta esplicita utente: "questo tool e' solo di
# aiuto, non sono cosi' fiscale sui prezzi, alleggerisci le run di test") --
# file JSON committato nel repo (stesso schema di makeoffer_cooldown.json/
# autobuy_purchases.json), scaduto dopo 24h. In test ripetuti a distanza di
# poco tempo (come oggi, piu' run sulla stessa lega) evita di rifare le
# stesse query di mercato -- il prezzo reale non cambia cosi' spesso da
# giustificarle ogni volta, e questo tool non decide acquisti in автономia.
PREZZI_CACHE_PATH = os.path.join(REPO_ROOT, 'best_five_prezzi_cache.json')
# TTL alzato 24h -> 5 giorni (31/07, richiesta esplicita utente): con le run
# ripetute della stessa giornata il prezzo minimo non si muove abbastanza da
# giustificare di riscaricarlo ogni giorno, e ogni miss costa richieste su un
# rate limit gia' stretto (vedi le ondate di 429 su MLS). Questo tool aiuta a
# scegliere la formazione, non decide acquisti: un prezzo di qualche giorno fa
# e' piu' che sufficiente.
PREZZI_CACHE_TTL_ORE = float(os.environ.get('BEST_FIVE_PREZZI_CACHE_TTL_ORE', str(24 * 5)))

# Ogni quanti giocatori riscrivere la cache su disco durante il fetch (vedi
# il commento nel ciclo di fetch_prezzi): serve a non perdere tutto se il job
# muore a meta'. 25 e' un compromesso -- abbastanza raro da non pesare (il
# file e' piccolo e la scrittura e' locale), abbastanza frequente da limitare
# la perdita a pochi giocatori.
PREZZI_CACHE_CHUNK = int(os.environ.get('BEST_FIVE_PREZZI_CACHE_CHUNK', '25'))

# Ondate di 429 dopo le quali il fetch prezzi si arrende (0 = mai). Vedi il
# commento nel ciclo: ha senso solo perche' cache prezzi e predizioni ora si
# accumulano fra run, quindi arrendersi presto non spreca il lavoro fatto.
MAX_ONDATE_429 = int(os.environ.get('BEST_FIVE_MAX_ONDATE_429', '2'))


def _prezzi_cache_leggi():
    if not os.path.exists(PREZZI_CACHE_PATH):
        return {}
    try:
        with open(PREZZI_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _prezzi_cache_scrivi(cache):
    with open(PREZZI_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def fetch_prezzi(slugs):
    """Prezzo minimo in_season/classic per ciascuno slug in 'slugs' (deduplicati).
    Ritorna {slug: {'in_season': float|None, 'classic': float|None}}. Prima
    controlla la cache su disco (PREZZI_CACHE_TTL_ORE, default 24h) -- solo
    gli slug scaduti o mai visti fanno una query di rete vera. Import
    dinamico di bot_profit.py fatto qui (non a livello di modulo) per non
    pagare il costo di caricamento/pip curl_cffi quando questa funzione non
    viene mai chiamata (es. tutte le modalita' --matrice/--predict-shard)."""
    cache = _prezzi_cache_leggi()
    ora = datetime.datetime.utcnow()
    prezzi = {}
    da_interrogare = []
    unici = sorted(set(slugs))
    for slug in unici:
        voce = cache.get(slug)
        if voce is not None:
            try:
                eta_ore = (ora - datetime.datetime.fromisoformat(voce['ts'])).total_seconds() / 3600.0
            except (KeyError, ValueError):
                eta_ore = None
            if eta_ore is not None and eta_ore <= PREZZI_CACHE_TTL_ORE:
                prezzi[slug] = {'in_season': voce.get('in_season'), 'classic': voce.get('classic')}
                continue
        da_interrogare.append(slug)

    if not da_interrogare:
        log(f"[prezzi] {len(unici)} giocatori tutti in cache (< {PREZZI_CACHE_TTL_ORE:g}h), nessuna query.")
        return prezzi

    log(f"[prezzi] {len(unici) - len(da_interrogare)} da cache, {len(da_interrogare)} da interrogare dal vivo.")
    bp = _import_bot_profit()
    # FIX BUG REALE (31/07, run Scozia: TUTTI i prezzi N/D): LIVE_OFFERS_QUERY
    # a pagina 50 (default di bot_profit.py) supera il limite di complessita'
    # GraphQL dell'account senza APIKEY (osservato: complessita' 1306 su un
    # massimo di 500) -- ogni fetch falliva con errore GraphQL, mai un
    #'errore HTTP' quindi non veniva nemmeno ritentato. Ridotta SOLO per
    # questa istanza importata (non tocca bot_profit.py su disco ne' la sua
    # produzione, che potrebbe girare con un account/APIKEY diverso): con
    # n=10 la complessita' stimata scende a ~260, ben sotto soglia. Prezzo
    # minimo resta corretto anche su un campione piu' piccolo di annunci --
    # i candidati Best Five sono in genere giocatori poco posseduti, con
    # mercati sottili dove i primi annunci restituiti coprono gia' il
    # minimo reale nella grande maggioranza dei casi.
    bp.LIVE_OFFERS_PAGE_SIZE = 10

    # FIX BUG REALE (31/07, run MLS standalone: "pieno di 429, non riesco a
    # completare nemmeno una singola run"). Due cause distinte, entrambe qui:
    #
    # 1) IL PACER PARTE TROPPO VELOCE. bot_profit.py assume di iniziare col
    #    secchio del rate limit PIENO, quindi parte a
    #    GRAPHQL_MIN_INTERVAL_SECONDS_FAST (0.2s) e scende a SAFE (0.9s) solo
    #    DOPO aver incassato il primo 429. Vero per bot_profit, che e' la
    #    prima cosa che gira nel suo processo; FALSO per Best Five, che
    #    arriva qui dopo discovery + starterOdds + predict, cioe' con
    #    centinaia di richieste gia' spese sullo stesso account (e per giunta
    #    fatte con 'requests' diretto, mai viste dal pacer). Risultato: la
    #    prima raffica va a vuoto e ogni ondata costa 45s di pausa GLOBALE su
    #    tutti i thread -- su MLS, che ha il pool piu' grande, le ondate si
    #    accumulano fino a far scadere il job. Qui si parte direttamente al
    #    ritmo SAFE, senza pagare la scoperta.
    bp._pace_interval[0] = max(bp._pace_interval[0], bp.GRAPHQL_MIN_INTERVAL_SECONDS_SAFE)
    bp._pace_floor[0] = max(bp._pace_floor[0], bp.GRAPHQL_MIN_INTERVAL_SECONDS_SAFE)

    # 2) OGNI GIOCATORE COSTAVA FINO A 2 RICHIESTE. fetch_all_live_offers
    #    pagina fino a LIVE_OFFERS_MAX_PAGES (2 di default): con page size
    #    gia' ridotto a 10, la seconda pagina raddoppia il costo per i soli
    #    giocatori con mercato liquido. Per il minimo di prezzo -- l'unica
    #    cosa che serve a Best Five -- una pagina basta nella stragrande
    #    maggioranza dei casi (stesso ragionamento gia' fatto per il page
    #    size, vedi sopra). Dimezza le richieste sui giocatori piu' scambiati,
    #    che sono esattamente quelli che facevano scattare le ondate.
    bp.LIVE_OFFERS_MAX_PAGES = 1

    eth_rate = bp.get_eth_rate()
    ts_ora = ora.isoformat()

    # FIX BUG REALE (31/07, run K League: 4 ondate di 429 SEQUENZIALI per
    # soli 73 giocatori -- 6+ minuti solo per i prezzi, inaccettabile):
    # bot_profit.py stesso scandaglia 1200 giocatori in 4 minuti perche' lo fa
    # con CONCORRENZA (ThreadPoolExecutor, SNAPSHOT_WORKER_THREADS=10, vedi
    # scanners/bot_profit.py) -- tanti worker sovrappongono l'attesa di
    # rete, il pacer adattivo condiviso (_pace_registra_429/_pace_slot, dentro
    # graphql_query) throttla il RITMO aggregato in uscita, non il numero di
    # thread. Qui invece si chiamava _prezzi_minimi_slug in un for SEQUENZIALE
    # (una richiesta alla volta, thread singolo): stesso ritmo massimo per
    # singola richiesta ma si spreca tutta l'attesa di rete invece di
    # sovrapporla, quindi per completare lo stesso volume ci vuole molto piu'
    # tempo a parita' di rate limit reale. Fix: stesso ThreadPoolExecutor di
    # bot_profit.py (import gia' fatto sopra, pacer condiviso -- funziona
    # automaticamente anche multi-thread, e' module-level in bot_profit.py).
    def _worker(slug):
        return slug, _prezzi_minimi_slug(bp, eth_rate, slug)

    # Scrittura A CHUNK della cache (31/07, richiesta esplicita utente: "metti
    # dei chunk al registro prezzi, almeno accumula"). Prima la cache veniva
    # scritta UNA SOLA VOLTA a fine ciclo: se il job veniva cancellato o andava
    # in timeout a meta' -- cioe' esattamente quello che succedeva a MLS, che
    # con 233 giocatori da interrogare non e' MAI riuscita a completare una run
    # -- si perdeva TUTTO il lavoro fatto e la run successiva ripartiva da zero.
    # Circolo chiuso: senza una run completa la cache non si popola, senza
    # cache la run non completa. Scrivendo ogni CHUNK i prezzi si accumulano
    # anche fra run fallite, e prima o poi la cache copre l'intero pool.
    # La scrittura avviene nel thread principale (dentro as_completed), quindi
    # non serve alcun lock.
    fatti = 0
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=5, thread_name_prefix='prezzi') as executor:
        futures = [executor.submit(_worker, slug) for slug in da_interrogare]
        for future in concurrent.futures.as_completed(futures):
            slug, (in_season, classic) = future.result()
            prezzi[slug] = {'in_season': in_season, 'classic': classic}
            cache[slug] = {'in_season': in_season, 'classic': classic, 'ts': ts_ora}
            fatti += 1
            if fatti % PREZZI_CACHE_CHUNK == 0:
                _prezzi_cache_scrivi(cache)
                log(f"[prezzi] [{fatti}/{len(da_interrogare)}] fatto "
                    f"(cache salvata, {len(cache)} voci totali).")
            elif fatti % 20 == 0 or fatti == len(da_interrogare):
                log(f"[prezzi] [{fatti}/{len(da_interrogare)}] fatto.")

            # RESA ANTICIPATA dopo N ondate di 429 (31/07, osservazione
            # dell'utente: "con la cache delle predizioni le puoi far morire
            # dopo un paio di 429 ormai"). Ha senso solo ORA che il lavoro si
            # accumula: ogni ondata costa 45s di pausa globale e le successive
            # arrivano sempre piu' fitte, quindi insistere sullo stesso run
            # rende pochissimo. Meglio chiudere con quello che si e' preso --
            # gia' salvato a chunk -- e lasciare che sia la run successiva a
            # continuare da li', partendo con meta' pool gia' in cache. Il
            # report esce comunque: i prezzi sono un'informazione accessoria,
            # le formazioni si generano lo stesso (chi resta senza prezzo
            # compare come 'N/D').
            if MAX_ONDATE_429 > 0 and bp._pace_ondate[0] >= MAX_ONDATE_429:
                for f in futures:
                    f.cancel()
                _prezzi_cache_scrivi(cache)
                log(f"[prezzi] RESA ANTICIPATA dopo {bp._pace_ondate[0]} ondate di 429: "
                    f"{fatti}/{len(da_interrogare)} presi e salvati in cache "
                    f"({len(cache)} voci totali). Il resto lo prendera' la prossima run, "
                    f"che ripartira' da qui invece che da zero.")
                break
    _prezzi_cache_scrivi(cache)
    return prezzi


def _attach_prezzi(role_data_dict):
    """Fetcha i prezzi per TUTTI gli slug presenti in role_data_dict (dict
    ROLE -> lista di righe consiglio, gia' filtrate per starterOdds a monte)
    e li attacca ad ogni riga come 'prezzo_in_season'/'prezzo_classic' --
    cosi' sia le formazioni generate sia _blocco_top_esclusi possono
    mostrarli senza rifetchare nulla. Ritorna anche il dict {slug: {...}}
    grezzo, per l'annotazione HTML finale (vedi _annota_prezzi_html)."""
    tutti_slug = [r['slug'] for rows in role_data_dict.values() for r in rows]
    prezzi = fetch_prezzi(tutti_slug)
    for rows in role_data_dict.values():
        for r in rows:
            info = prezzi.get(r['slug'], {})
            r['prezzo_in_season'] = info.get('in_season')
            r['prezzo_classic'] = info.get('classic')
    return prezzi


# --- Eta / Under-23 (31/07, richiesta esplicita utente: "stemmino" su ogni
# carta se under 23 + una colonna dedicata 'Cheapest Under-23') -----------
#
# Sorare espone un campo 'age' diretto su anyPlayer (verificato dal vivo,
# nessuna auth richiesta: query di test su kieran-tierney -> age=29,
# coerente con la sua data di nascita reale) -- niente bisogno di calcolare
# l'eta' da una data di nascita, ne' di un nuovo campo mai visto prima nella
# pipeline. Cache SEPARATA dai prezzi (TTL lunghissimo, l'eta' di un
# giocatore cambia una volta l'anno, non ogni 24h) per non invalidare inutil-
# mente le voci ad ogni run.
UNDER23_MAX_ETA = 22  # "Under 23" = eta' <= 22 (compie 23 anni durante o dopo questa stagione)

ETA_QUERY = """
query EtaGiocatore($slug: String!) {
  anyPlayer(slug: $slug) {
    age
  }
}
"""

ETA_CACHE_PATH = os.path.join(REPO_ROOT, 'best_five_eta_cache.json')
ETA_CACHE_TTL_ORE = float(os.environ.get('BEST_FIVE_ETA_CACHE_TTL_ORE', str(24 * 180)))  # 180 giorni


def _eta_cache_leggi():
    if not os.path.exists(ETA_CACHE_PATH):
        return {}
    try:
        with open(ETA_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _eta_cache_scrivi(cache):
    with open(ETA_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def fetch_eta_reale(slug):
    """Eta' reale (anni) di un giocatore via il campo 'age' di anyPlayer.
    None se non disponibile. Stesso pattern di retry/backoff di
    fetch_l10_reale (query leggera, un giocatore per chiamata)."""
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    if APIKEY:
        headers['APIKEY'] = APIKEY
    payload = {'query': ETA_QUERY, 'variables': {'slug': slug}, 'operationName': 'EtaGiocatore'}
    backoff = 1.0
    for attempt in range(3):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                return None
            data = resp.json()
            player = (data.get('data') or {}).get('anyPlayer') or {}
            return player.get('age')
        except Exception as e:
            log(f"[eta] {slug}: eccezione tentativo {attempt+1}/3: {e!r}")
            time.sleep(backoff)
            backoff *= 2
    return None


def fetch_eta(slugs):
    """Eta' per ciascuno slug in 'slugs' (deduplicati), con cache su disco
    (TTL molto lungo, vedi ETA_CACHE_TTL_ORE) -- stesso meccanismo di
    fetch_prezzi ma piu' semplice (query diretta via GraphQL, nessun import
    di bot_profit.py). Ritorna {slug: eta_o_None}."""
    cache = _eta_cache_leggi()
    ora = datetime.datetime.utcnow()
    eta_map = {}
    da_interrogare = []
    unici = sorted(set(slugs))
    for slug in unici:
        voce = cache.get(slug)
        if voce is not None:
            try:
                eta_ore = (ora - datetime.datetime.fromisoformat(voce['ts'])).total_seconds() / 3600.0
            except (KeyError, ValueError):
                eta_ore = None
            if eta_ore is not None and eta_ore <= ETA_CACHE_TTL_ORE:
                eta_map[slug] = voce.get('age')
                continue
        da_interrogare.append(slug)

    if not da_interrogare:
        log(f"[eta] {len(unici)} giocatori tutti in cache, nessuna query.")
        return eta_map

    log(f"[eta] {len(unici) - len(da_interrogare)} da cache, {len(da_interrogare)} da interrogare dal vivo.")
    ts_ora = ora.isoformat()
    # Stesso fix di concorrenza di fetch_prezzi (vedi commento li'): richieste
    # in parallelo invece di un for sequenziale,_http_session e' condivisa e
    # thread-safe (usata gia' cosi' altrove in questo file).
    fatti = 0
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=5, thread_name_prefix='eta') as executor:
        futures = {executor.submit(fetch_eta_reale, slug): slug for slug in da_interrogare}
        for future in concurrent.futures.as_completed(futures):
            slug = futures[future]
            eta = future.result()
            eta_map[slug] = eta
            cache[slug] = {'age': eta, 'ts': ts_ora}
            fatti += 1
            if fatti % PREZZI_CACHE_CHUNK == 0:
                _eta_cache_scrivi(cache)
                log(f"[eta] [{fatti}/{len(da_interrogare)}] fatto (cache salvata).")
            elif fatti % 20 == 0 or fatti == len(da_interrogare):
                log(f"[eta] [{fatti}/{len(da_interrogare)}] fatto.")
    _eta_cache_scrivi(cache)
    return eta_map


def _attach_eta(role_data_dict):
    """Fetcha l'eta' per TUTTI gli slug in role_data_dict e la attacca a
    ogni riga come 'eta'/'under23' -- stesso pattern di _attach_prezzi.
    Ritorna anche il dict grezzo {slug: eta_o_None} per l'annotazione HTML."""
    tutti_slug = [r['slug'] for rows in role_data_dict.values() for r in rows]
    eta_map = fetch_eta(tutti_slug)
    for rows in role_data_dict.values():
        for r in rows:
            eta = eta_map.get(r['slug'])
            r['eta'] = eta
            r['under23'] = eta is not None and eta <= UNDER23_MAX_ETA
    return eta_map


def _registra_tipo_arena(gg, lega):
    """FIX (31/07, bug reale: KeyError 'AUSTRIA_ARENA' su una lega che NON e'
    tra le ARENA_LEAGUES di produzione -- quella lista e' una tupla fissa di
    slug scelti dall'utente per le leghe con Arena dedicata VERA su Sorare,
    non tutte le leghe con una pipeline attiva. Per Best Five (che deve poter
    generare un pool globale per QUALUNQUE lega con discovery_global, non
    solo quelle gia' promosse ad Arena dedicata), se il tipo Arena non esiste
    ancora lo registra qui a runtime con gli stessi identici parametri
    standard di un'Arena dedicata (cap L10 260, capitano +20%, variance_mode
    attivo, nessun bonus XP/cap260/stack-guard -- stesso trattamento di
    build_formazione_globale.py per ARENA_LEAGUES). Il cap L10 viene poi
    rimosso da _tipo_per_lega A MENO CHE RISPETTA_CAP_L10 sia attivo (vedi
    li' per il motivo). Nessun impatto su produzione: 'gg' qui e' sempre
    un'istanza importata a parte (vedi _import_gg), mai quella del workflow
    reale."""
    tipo = gg.arena_type(lega)
    if tipo in gg.FORMATION_SHAPES:
        return tipo  # gia' una vera Arena dedicata di produzione, nulla da fare
    gg.FORMATION_SHAPES[tipo] = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
                                  'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None}
    gg.POOL_LEAGUE_BY_TYPE[tipo] = lega
    gg.LABELS[tipo] = f'Arena {lega.capitalize()} (cap 260)'
    gg.L10_CAP_BY_TYPE[tipo] = 260.0
    gg.VARIANCE_MODE_TYPES.add(tipo)
    gg.bff.CAPTAIN_BONUS_BY_TYPE[tipo] = 0.2
    return tipo


def _tipo_per_lega(gg, lega):
    """Nome del tipo FORMATION_SHAPES di produzione per la lega scelta:
    'MLS_IN_SEASON'/'KLEAGUE_IN_SEASON' per le due leghe dedicate (stessa
    competizione In Season che gioca l'utente), l'Arena dedicata per
    qualunque altra lega -- non esiste un tipo 'In Season' generico per le
    leghe non dedicate in produzione. Se la lega non ha ancora un'Arena
    dedicata VERA in produzione (es. Austria/2.Bundesliga, usate qui solo
    come fonte dati per Contender), ne registra una ad-hoc (vedi
    _registra_tipo_arena).

    FIX (31/07, bug reale trovato su Scozia: "NON GENERATA" nonostante
    decine di candidati validi disponibili -- vedi commit di questa stessa
    sessione): il cap L10 260 delle Arene VERE si affida a
    bff._pareto_frontier, che ordina i candidati per L10 crescente e tiene
    solo chi migliora il punteggio rispetto ai piu' economici -- corretto
    quando l'L10 varia da carta a carta (produzione, carte reali possedute),
    ma la CardPool sintetica di Best Five non ha MAI l'L10 reale di un
    giocatore non posseduto (sempre trattato come 0.0 per tutti):
    con tutti i candidati a costo IDENTICO, la frontiera di Pareto collassa
    al SOLO candidato con punteggio piu' alto per ruolo (il resto sembra
    'dominato' pur non essendolo, la funzione confronta costi diversi da
    zero). Risultato: mai piu' di 1 candidato per ruolo, formazione
    impossibile da completare appena il migliore serve altrove.
    Il cap 260 non era comunque MAI stato un vincolo reale in Best Five
    (MLS/K League/Contender non lo applicano gia' oggi, sono IN_SEASON senza
    cap) -- qui si rimuove esplicitamente ANCHE per le Arene vere (es.
    SCOZIA_ARENA, che in produzione lo ha) SOLO per l'istanza 'gg' di questa
    run di Best Five, mai per quella reale del workflow."""
    if lega in gg.DEDICATED_LEAGUES:
        return f'{lega.upper()}_IN_SEASON'
    tipo = _registra_tipo_arena(gg, lega)
    if not RISPETTA_CAP_L10:
        gg.L10_CAP_BY_TYPE.pop(tipo, None)
        if gg.LABELS.get(tipo, '').endswith('(cap 260)'):
            gg.LABELS[tipo] = gg.LABELS[tipo][:-len('(cap 260)')].strip()
    return tipo


def costruisci_formazione_vera(lega, count):
    """Genera fino a 'count' formazioni (GK/DEF/MID/FWD/EXTRA, con
    sinergie/anti-stack/captain -- IDENTICO al tool unificato, stessa
    funzione di produzione richiamata qui) sul pool GLOBALE della lega. Il
    conteggio 'count' fa le veci del vecchio 'n_backup': con la CardPool
    sintetica (1 copia virtuale a testa) la 2a/3a formazione non puo'
    riusare un giocatore gia' schierato nella 1a, quindi sono
    automaticamente alternative complete con giocatori diversi -- lo
    stesso ruolo di "backup" di prima, ma a livello di formazione intera
    invece che di singolo slot.

    Richiede che i consiglio_*.txt esistano gia' per tutti e 4 i ruoli
    (li scrive esegui_consiglio, chiamato qui per ciascun ruolo)."""
    gg = _import_gg()
    bff = gg.bff  # STESSA istanza usata da produzione per registrare CAPTAIN_BONUS_BY_TYPE/CAP260 ecc.

    role_data_lega = {}
    for ruolo, ROLE in (('gk', 'GK'), ('def', 'DEF'), ('mid', 'MID'), ('fwd', 'FWD')):
        consiglio_path = esegui_consiglio(lega, ruolo)
        if consiglio_path and os.path.exists(consiglio_path):
            role_data_lega[ROLE] = _parse_consiglio_calibrato(bff, gg, consiglio_path, ROLE)
        else:
            log(f"[{ruolo}] Nessun consiglio disponibile, ruolo vuoto per la formazione vera.")
            role_data_lega[ROLE] = []

    mancanti = [r for r in gg.ROLES if not role_data_lega.get(r)]
    if mancanti:
        log(f"ATTENZIONE: ruoli senza candidati: {mancanti} — la formazione potrebbe non essere generabile.")

    _attach_odds(role_data_lega, _odds_run_corrente())
    prezzi = _attach_prezzi(role_data_lega)
    eta_map = _attach_eta(role_data_lega) if GENERA_UNDER23 else {}

    # displayName reale Sorare (30/07, richiesta esplicita utente: "il nome
    # sulle carte deve essere il display name non lo slug"). LIMITE NOTO:
    # player_names.json esiste solo nella discovery POSSEDUTI (scritto da
    # discovery_fixture.py, che quando scansiona i roster raccoglie i nomi),
    # NON nella discovery_global usata dal pool Best Five -- quella script
    # oggi scarta il campo 'name' gia' presente nella query TeamRoster,
    # persiste solo gli slug (vedi kleague_gk_discovery_global.py). Quindi
    # oggi i nomi coprono solo i giocatori gia' visti dalla discovery
    # posseduti (in pratica: le tue carte + le squadre delle tue fixture),
    # non l'intero pool globale -- per chi manca, CardPool.display_name()
    # ripiega da solo sullo slug title-case (stesso fallback della
    # produzione). Coprire l'intero pool richiede di far persistere 'name'
    # anche a discovery_global (follow-up separato, non fatto qui).
    names = {}
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output',
                             f'{lega}_{ruolo}_discovery', 'player_names.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                names.update(json.load(f))

    # RISPETTA_CAP_L10 (31/07): serve l'L10 REALE per far funzionare il cap
    # 260 (altrimenti bff._pareto_frontier collassa a 1 candidato per ruolo,
    # vedi _tipo_per_lega) -- passato al costruttore di CardPool nello stesso
    # formato di player_card_counts.json (breakdown['l10'] per slug), cosi'
    # CardPool.l10(slug) ritorna il valore vero invece di None/0.0.
    if RISPETTA_CAP_L10:
        l10_map = fetch_l10_per_ruoli(role_data_lega)
        counts_con_l10 = {
            ROLE: {r['slug']: {'in_season': 1, 'classic': 0, 'l10': l10_map.get(r['slug'])}
                   for r in rows}
            for ROLE, rows in role_data_lega.items()
        }
        card_pool = bff.CardPool(counts_con_l10, names=names)
    else:
        card_pool = bff.CardPool({}, names=names)

    tipo = _tipo_per_lega(gg, lega)
    role_data = {lega: role_data_lega}
    pools = {lega: {role: gg._NoFilterPool(role, lega, role_data_lega[role]) for role in gg.ROLES}}

    # Chiamata DAVVERO alla generate_lineups_for_type di produzione (stessa
    # funzione che gira in formazione_giornata.yml) -- legge da soli i
    # dizionari L10_CAP_BY_TYPE/STACK_GUARD_TYPES/VARIANCE_MODE_TYPES/
    # CHECK_CAP260_TYPES/XP_BONUS_TYPES di 'gg' in base a 'tipo', nessun
    # parametro riscritto qui: se domani la produzione cambia un flag per
    # MLS_IN_SEASON/KLEAGUE_IN_SEASON, Best Five lo eredita automaticamente.
    all_results = gg.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
    generated, totale, lineup_blocks, lineup_html_blocks = _renderizza_risultati(bff, all_results, card_pool)
    lineup_blocks = [_annota_prezzi_testo(b, prezzi) for b in lineup_blocks]
    lineup_blocks = [_annota_eta_testo(b, eta_map) for b in lineup_blocks]

    testo_esclusi, html_esclusi = _blocco_top_esclusi(bff, card_pool, role_data_lega)
    lineup_blocks.append(testo_esclusi)
    lineup_html_blocks.append(html_esclusi)

    if GENERA_CHEAPEST:
        l10_map_cheapest = l10_map if RISPETTA_CAP_L10 else fetch_l10_per_ruoli(role_data_lega)
        testo_cheap, html_cheap = blocco_cheapest(bff, card_pool, role_data_lega, prezzi, l10_map_cheapest)
        lineup_blocks.append(testo_cheap)
        lineup_html_blocks.append(html_cheap)

    if GENERA_UNDER23:
        testo_u23, html_u23 = blocco_cheapest_under23(bff, card_pool, role_data_lega)
        lineup_blocks.append(testo_u23)
        lineup_html_blocks.append(html_u23)

    log(f"Formazione vera: {generated}/{count} generate (pool globale, CardPool sintetica, "
        f"tipo={tipo}, stesso motore della produzione).")
    return bff, generated, totale, lineup_blocks, lineup_html_blocks, prezzi, eta_map


# Scale-down moderato (31/07, richiesta esplicita utente: "non troppo piu
# piccoli" -- il primo tentativo con carte minuscole non andava bene) per
# distinguere a colpo d'occhio le carte di esclusi/cheapest (info, non
# formazioni vere) da quelle delle 3 formazioni principali, senza pero'
# renderle illeggibili. Riusa DAVVERO .pcard (bff.render_card_html), solo
# un wrapper scoped che applica scale() -- nessuna modifica al CSS
# condiviso con la produzione. Idempotente se ripetuto piu' volte nella
# stessa pagina (stesso selettore, stesse regole).
MINI_CARD_CSS = """
<style>
.mini-card-strip { display: flex; flex-wrap: wrap; gap: 2px; margin: 6px 0 14px 0; }
.mini-card { transform: scale(0.85); transform-origin: top left; margin: 0 -22px -22px 0; }
</style>
"""


def _prezzo_str(row):
    """'IS: 12.50EUR | CL: 4.00EUR' -- 'N/D' per la rarita' senza annunci
    live. row puo' non avere affatto i campi prezzo (fetch_prezzi non ancora
    chiamata, es. in un contesto di test) -- in quel caso stringa vuota."""
    if 'prezzo_in_season' not in row and 'prezzo_classic' not in row:
        return ""
    isp = row.get('prezzo_in_season')
    cl = row.get('prezzo_classic')
    isp_s = f"{isp:.2f}EUR" if isp is not None else "N/D"
    cl_s = f"{cl:.2f}EUR" if cl is not None else "N/D"
    return f" | IS: {isp_s} | CL: {cl_s}"


def _blocco_top_esclusi(bff, card_pool, role_data_per_ruolo, n=TOP_N_ESCLUSI):
    """Top N candidati per ruolo (per 'atteso') MAI schierati in nessuna
    delle formazioni gia' generate -- stesso concetto del pannello 'esclusi'
    di generatore_formazioni/build_formazione_globale.py (card_pool.used_
    slugs()), qui SOLO per i ruoli/leghe di questa run di Best Five, non per
    l'intera pipeline di produzione. Ritorna (testo, html).

    HTML (31/07, richiesta esplicita utente: "mostrami la carta, non solo la
    riga di testo"): riusa DAVVERO bff.render_card_html (STESSA funzione delle
    carte principali, nessuna duplicazione) dentro un wrapper '.mini-card'
    rimpicciolito via CSS scoped (vedi MINI_CARD_CSS) -- 'ctype' sempre
    'in_season' qui: un escluso non ha una rarita' reale associata, e' solo
    un candidato mai schierato, non un acquisto implicito."""
    used = card_pool.used_slugs()
    lines = ["", "=" * 70, f"TOP {n} ESCLUSI PER RUOLO (eleggibili per starterOdds, mai schierati)", "=" * 70]
    html_parts = [MINI_CARD_CSS, '<div class="esclusi-panel"><h3>Top %d esclusi per ruolo</h3>' % n]
    for ROLE in ('GK', 'DEF', 'MID', 'FWD'):
        rows = role_data_per_ruolo.get(ROLE, [])
        esclusi = sorted((r for r in rows if r['slug'] not in used),
                         key=lambda r: r.get('atteso', 0), reverse=True)[:n]
        lines.append(f"\n--- {ROLE} ---")
        html_parts.append(f'<div class="esclusi-role"><strong>{ROLE}</strong><div class="mini-card-strip">')
        if not esclusi:
            lines.append("  (nessuno)")
            html_parts.append('<p class="empty">(nessuno)</p>')
        for i, r in enumerate(esclusi, 1):
            squadra = r.get('team_slug') or 'N/D'
            prezzo = _prezzo_str(r)
            lines.append(f"  {i}) {r['slug']}: {r.get('atteso')} pt (squadra={squadra}){prezzo}")
            html_parts.append(f'<div class="mini-card">{bff.render_card_html(ROLE, r, "in_season", card_pool, False)}</div>')
        html_parts.append('</div></div>')
    html_parts.append('</div>')
    return "\n".join(lines), "".join(html_parts)


# --- Formazioni "cheapest" (31/07, richiesta esplicita utente) ------------
#
# Trova la formazione COMPLETA di prezzo TOTALE minimo (a parita' di prezzo,
# punteggio piu' alto), in 3 varianti che l'utente ha chiesto esplicitamente:
#   A) 4 In Season + 1 Classic (come MLS/K League/Contender In Season),
#      NESSUN cap L10.
#   B) 4 In Season + 1 Classic, CON cap L10 260 (Arena-legale davvero).
#   C) NESSUN limite di carte Classic (tutte e 5 possono esserlo), CON cap
#      L10 260.
#
# Implementazione ISOLATA (nessun uso di bff.CardPool/build_one_lineup,
# quel motore ragiona per SCORE non per PREZZO) -- un piccolo knapsack
# scritto qui apposta, mai eseguito in produzione. La CardPool sintetica di
# Best Five tratta ogni carta come "1 copia in_season virtuale" quindi non
# sa nulla di prezzo/rarita' reale: qui si lavora direttamente sui prezzi
# gia' fetchati da fetch_prezzi (in_season/classic) senza passare da
# CardPool per niente.
GENERA_CHEAPEST = os.environ.get('BEST_FIVE_GENERA_CHEAPEST', '0').strip() not in ('0', 'false', 'no', '')

# Cheapest Under-23 (31/07, richiesta esplicita utente). Default FALSE (non
# 'true' come GENERA_CHEAPEST): fetch_eta interroga l'API UNA VOLTA PER
# GIOCATORE (Sorare rifiuta il batching via alias multipli sullo stesso
# root field -- verificato dal vivo, errore "Duplicated root field:
# anyPlayer"), quindi RADDOPPIA le richieste sequenziali nello stesso step
# 'report' rispetto ai soli prezzi -- osservato causare rallentamenti/
# percepita 'run bloccata' su una lega a cache fredda (K League, 31/07).
# On-demand via BEST_FIVE_GENERA_UNDER23=1 finche' non si trova un modo piu'
# economico di fetchare l'eta' (es. solo per un sottoinsieme piu' piccolo).
GENERA_UNDER23 = os.environ.get('BEST_FIVE_GENERA_UNDER23', '0').strip() not in ('0', 'false', 'no', '')

CHEAPEST_CONFIGS = (
    # (etichetta, max_classic, l10_cap)
    ('4 In Season + 1 Classic, nessun cap L10', 1, None),
    ('4 In Season + 1 Classic, cap L10 260', 1, 260.0),
    ('Nessun limite Classic (fino a 5), cap L10 260', None, 260.0),
)

_RES_L10 = 10     # decimi di L10
_RES_PREZZO = 100  # centesimi di EUR


def _candidati_prezzo_ruolo(rows, prezzi, l10_map, rarita_ammesse):
    out = []
    for row in rows:
        for rarita in rarita_ammesse:
            prezzo = (prezzi.get(row['slug']) or {}).get(rarita)
            if prezzo is None:
                continue
            l10 = (l10_map or {}).get(row['slug']) or 0.0
            out.append((row, rarita, prezzo, l10))
    return out


def _ottimizza_lineup_min_prezzo(shape, role_data, prezzi, max_classic, l10_cap=None, l10_map=None):
    """Ritorna {'prezzo_totale', 'punteggio_totale', 'picks'} per la
    formazione COMPLETA di prezzo minimo che rispetta 'shape' (GK/DEF/MID/
    FWD + 1 EXTRA da extra_roles), max_classic (0/1/None) ed l10_cap
    (None = ignorato). None se nessuna combinazione e' possibile (pool
    insufficiente per un ruolo, o nessuna rientra nel cap L10).
    'picks': {ROLE: (row, rarita, prezzo)}, con 'EXTRA' anche il ruolo
    scelto: (ruolo, row, rarita, prezzo)."""
    rarita_ammesse = ('in_season',) if max_classic == 0 else ('in_season', 'classic')
    cap_units = int(round(l10_cap * _RES_L10)) if l10_cap is not None else None

    def candidati(role):
        return _candidati_prezzo_ruolo(role_data.get(role, []), prezzi, l10_map, rarita_ammesse)

    # stato (l10_units_usati, n_classic_usati) -> (prezzo_tot, punteggio_tot, picks, slug_usati)
    states = {(0, 0): (0.0, 0, {}, frozenset())}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        cands = candidati(role)
        if not cands:
            return None
        nuovi = {}
        for (l10u, ncl), (prezzo_tot, score_tot, picks, usati) in states.items():
            for row, rarita, prezzo, l10 in cands:
                if row['slug'] in usati:
                    continue
                nc = ncl + (1 if rarita == 'classic' else 0)
                if max_classic is not None and nc > max_classic:
                    continue
                l10u2 = l10u + int(round(l10 * _RES_L10))
                if cap_units is not None and l10u2 > cap_units:
                    continue
                pt2 = prezzo_tot + prezzo
                sc2 = score_tot + row['atteso']
                key = (l10u2, nc)
                cur = nuovi.get(key)
                if cur is None or pt2 < cur[0] - 1e-9 or (abs(pt2 - cur[0]) < 1e-9 and sc2 > cur[1]):
                    new_picks = dict(picks)
                    new_picks[role] = (row, rarita, prezzo)
                    nuovi[key] = (pt2, sc2, new_picks, usati | {row['slug']})
        if not nuovi:
            return None
        states = nuovi

    extra_cands = []
    for role in shape['extra_roles']:
        extra_cands.extend((role, row, rarita, prezzo, l10)
                            for row, rarita, prezzo, l10 in candidati(role))

    migliore = None
    for (l10u, ncl), (prezzo_tot, score_tot, picks, usati) in states.items():
        for role, row, rarita, prezzo, l10 in extra_cands:
            if row['slug'] in usati:
                continue
            nc = ncl + (1 if rarita == 'classic' else 0)
            if max_classic is not None and nc > max_classic:
                continue
            l10u2 = l10u + int(round(l10 * _RES_L10))
            if cap_units is not None and l10u2 > cap_units:
                continue
            pt2 = prezzo_tot + prezzo
            sc2 = score_tot + row['atteso']
            if migliore is None or pt2 < migliore[0] - 1e-9 or (abs(pt2 - migliore[0]) < 1e-9 and sc2 > migliore[1]):
                risultato = dict(picks)
                risultato['EXTRA'] = (role, row, rarita, prezzo)
                migliore = (pt2, sc2, risultato)
    if migliore is None:
        return None
    prezzo_tot, score_tot, picks = migliore
    # L10 combinata REALE (31/07, richiesta esplicita utente: "stampa il
    # totale degli L10, cosi' per sicurezza" -- il vincolo era gia' rispettato
    # internamente dal DP, qui lo si rende visibile per verifica).
    l10_totale = 0.0
    l10_ignoti = 0
    for slot, entry in picks.items():
        row = entry[1] if slot == 'EXTRA' else entry[0]
        _l10 = (l10_map or {}).get(row['slug'])
        if _l10 is None:
            l10_ignoti += 1
        l10_totale += _l10 or 0.0
    return {'prezzo_totale': prezzo_tot, 'punteggio_totale': score_tot, 'picks': picks,
            'l10_totale': l10_totale, 'l10_cap': l10_cap, 'l10_ignoti': l10_ignoti}


# --- Formazioni "ottimizzate valore" (31/07, richiesta esplicita utente) --
#
# Le 3 "cheapest" sopra minimizzano il prezzo puro -- a volte scartano un
# giocatore quasi identico in prezzo ma con un punteggio molto piu' alto
# (caso reale segnalato dall'utente: George Stanger 42pt/0.33EUR preferito a
# Ryan Astley 51pt/0.50EUR, 9 punti in piu' per 0.17EUR). L'utente ha
# chiesto un "compromesso statistico" invece di un moltiplicatore
# arbitrario: nessuno storico di prezzi salvato per un vero backtest, quindi
# la soglia si calcola sul pool REALE di ogni singola run (non un numero
# scelto a mano) -- media di prezzo/punteggio su TUTTI i candidati
# eleggibili di questa run (non solo quelli gia' scelti in una formazione,
# richiesta esplicita), per ciascuna rarita' disponibile. Un candidato piu'
# caro entra al posto di uno piu' economico SOLO se il costo marginale per
# punto aggiuntivo e' <= questa media -- "un affare nella media o meglio"
# del mercato di quella run, non una soglia fissa indovinata.
def _baseline_costo_punto(role_data, prezzi):
    """Media di prezzo/punteggio su tutti i candidati (in_season E classic)
    con prezzo noto e punteggio > 0, in TUTTI i ruoli di role_data -- questa
    e' la soglia auto-calcolata, non un numero deciso a mano."""
    rapporti = []
    for rows in role_data.values():
        for row in rows:
            if row.get('atteso', 0) <= 0:
                continue
            info = prezzi.get(row['slug']) or {}
            for rarita in ('in_season', 'classic'):
                prezzo = info.get(rarita)
                if prezzo is not None:
                    rapporti.append(prezzo / row['atteso'])
    if not rapporti:
        return None
    return sum(rapporti) / len(rapporti)


def _ottimizza_lineup_valore(shape, role_data, prezzi, max_classic, l10_cap, l10_map, baseline_costo_punto):
    """Come _ottimizza_lineup_min_prezzo, ma l'obiettivo massimizzato per
    ogni stato e' 'valore' = punteggio - prezzo/baseline_costo_punto invece
    del prezzo minimo -- un candidato piu' caro vince solo se il punteggio
    extra 'vale' il prezzo extra secondo la soglia media del pool reale
    (vedi _baseline_costo_punto). Se baseline_costo_punto e' None (nessun
    prezzo noto in tutto il pool) ritorna None -- non ha senso ottimizzare
    un valore senza nessun dato di prezzo."""
    if baseline_costo_punto is None or baseline_costo_punto <= 0:
        return None
    rarita_ammesse = ('in_season',) if max_classic == 0 else ('in_season', 'classic')
    cap_units = int(round(l10_cap * _RES_L10)) if l10_cap is not None else None

    def candidati(role):
        return _candidati_prezzo_ruolo(role_data.get(role, []), prezzi, l10_map, rarita_ammesse)

    def valore_di(row, prezzo):
        return row['atteso'] - prezzo / baseline_costo_punto

    # stato (l10_units_usati, n_classic_usati) -> (valore_tot, prezzo_tot, punteggio_tot, picks, slug_usati)
    states = {(0, 0): (0.0, 0.0, 0, {}, frozenset())}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        cands = candidati(role)
        if not cands:
            return None
        nuovi = {}
        for (l10u, ncl), (val_tot, prezzo_tot, score_tot, picks, usati) in states.items():
            for row, rarita, prezzo, l10 in cands:
                if row['slug'] in usati:
                    continue
                nc = ncl + (1 if rarita == 'classic' else 0)
                if max_classic is not None and nc > max_classic:
                    continue
                l10u2 = l10u + int(round(l10 * _RES_L10))
                if cap_units is not None and l10u2 > cap_units:
                    continue
                v2 = val_tot + valore_di(row, prezzo)
                key = (l10u2, nc)
                cur = nuovi.get(key)
                if cur is None or v2 > cur[0] + 1e-9:
                    new_picks = dict(picks)
                    new_picks[role] = (row, rarita, prezzo)
                    nuovi[key] = (v2, prezzo_tot + prezzo, score_tot + row['atteso'], new_picks,
                                  usati | {row['slug']})
        if not nuovi:
            return None
        states = nuovi

    extra_cands = []
    for role in shape['extra_roles']:
        extra_cands.extend((role, row, rarita, prezzo, l10)
                            for row, rarita, prezzo, l10 in candidati(role))

    migliore = None
    for (l10u, ncl), (val_tot, prezzo_tot, score_tot, picks, usati) in states.items():
        for role, row, rarita, prezzo, l10 in extra_cands:
            if row['slug'] in usati:
                continue
            nc = ncl + (1 if rarita == 'classic' else 0)
            if max_classic is not None and nc > max_classic:
                continue
            l10u2 = l10u + int(round(l10 * _RES_L10))
            if cap_units is not None and l10u2 > cap_units:
                continue
            v2 = val_tot + valore_di(row, prezzo)
            if migliore is None or v2 > migliore[0] + 1e-9:
                risultato = dict(picks)
                risultato['EXTRA'] = (role, row, rarita, prezzo)
                migliore = (v2, prezzo_tot + prezzo, score_tot + row['atteso'], risultato)
    if migliore is None:
        return None
    _, prezzo_tot, score_tot, picks = migliore
    l10_totale = 0.0
    l10_ignoti = 0
    for slot, entry in picks.items():
        row = entry[1] if slot == 'EXTRA' else entry[0]
        _l10 = (l10_map or {}).get(row['slug'])
        if _l10 is None:
            l10_ignoti += 1
        l10_totale += _l10 or 0.0
    return {'prezzo_totale': prezzo_tot, 'punteggio_totale': score_tot, 'picks': picks,
            'l10_totale': l10_totale, 'l10_cap': l10_cap, 'l10_ignoti': l10_ignoti}


def _render_cheapest(bff, card_pool, label, risultato, titolo='Cheapest'):
    """Testo + HTML per una formazione 'cheapest'. Il testo non riusa
    format_lineup (struttura 'picks' diversa da quella di bff.build_one_
    lineup) -- rendering minimale dedicato. L'HTML invece (31/07, richiesta
    esplicita utente: "mostrami la carta") riusa DAVVERO bff.render_card_html
    per ogni pick, con la rarita' VERA scelta dall'ottimizzatore (in_season/
    classic, non sempre 'in_season' come per gli esclusi) dentro lo stesso
    wrapper '.mini-card' rimpicciolito di _blocco_top_esclusi."""
    if risultato is None or risultato.get('impossibile'):
        # Il motivo VERO, non un generico "budget esiguo" (31/07: l'utente ha
        # visto quel messaggio su K League e ha pensato ci fosse un tetto di
        # spesa, mentre la formazione non usciva perche' NESSUNA combinazione
        # arrivava al punteggio richiesto -- causa completamente diversa).
        if risultato and risultato.get('motivo'):
            motivo = risultato['motivo']
        else:
            motivo = ("nessuna combinazione trovata nel pool eleggibile "
                      "(candidati insufficienti per qualche ruolo, o prezzi/L10 non noti)")
        testo = f"--- {titolo} — {label} ---\nNON GENERATA: {motivo}."
        html = (f'<div class="esclusi-panel"><h3>{titolo} — {label}</h3>'
                f'<p class="empty">Non generata: {motivo}.</p></div>')
        return testo, html

    nota = risultato.get('nota')
    suffisso = f" [{nota}]" if nota else ""
    righe = [f"--- {titolo} — {label} ---{suffisso}"]
    html_nota = (f'<p class="empty" style="margin:2px 0 8px">{nota}</p>' if nota else '')
    html_righe = [MINI_CARD_CSS, f'<div class="esclusi-panel"><h3>{titolo} — {label}</h3>{html_nota}<div class="mini-card-strip">']
    for slot in ('GK', 'DEF', 'MID', 'FWD', 'EXTRA'):
        entry = risultato['picks'].get(slot)
        if not entry:
            continue
        if slot == 'EXTRA':
            ruolo, row, rarita, prezzo = entry
            etichetta_slot = f"EXTRA ({ruolo})"
        else:
            row, rarita, prezzo = entry
            etichetta_slot = slot
        tag = " [CLASSIC]" if rarita == 'classic' else ""
        righe.append(f"{etichetta_slot:<12} {row['slug']}: {row['atteso']} pt{tag} -- {prezzo:.2f}EUR")
        card_html = bff.render_card_html(etichetta_slot, row, rarita, card_pool, False)
        html_righe.append(
            f'<div class="mini-card">{card_html}'
            f'<div class="pcard-prezzo" style="font-size:0.78rem;font-weight:700;'
            f'color:var(--gold);margin-top:4px">{prezzo:.2f}EUR</div></div>')
    l10_cap = risultato.get('l10_cap')
    l10_nota = f" / cap {l10_cap:.0f}" if l10_cap is not None else " (nessun cap)"
    # Se per qualche schierato l'L10 non e' stato letto, il totale e' per forza
    # SOTTOSTIMATO e il cap non e' verificabile: dirlo invece di far credere
    # che sia rispettato (bug reale del 31/07, vedi fetch_l10_reale).
    _ignoti = risultato.get('l10_ignoti') or 0
    if _ignoti:
        l10_nota += (f" -- ATTENZIONE: {_ignoti} giocatori senza L10 letto, contati come 0: "
                     f"il totale reale e' piu' alto e il cap NON e' verificato")
    righe.append(f"TOTALE: {risultato['punteggio_totale']} pt -- {risultato['prezzo_totale']:.2f}EUR")
    righe.append(f"L10 combinata: {risultato['l10_totale']:.1f}{l10_nota}")
    html_righe.append(f"</div><p><strong>TOTALE: {risultato['punteggio_totale']} pt -- "
                       f"{risultato['prezzo_totale']:.2f}EUR</strong></p>"
                       f"<p>L10 combinata: {risultato['l10_totale']:.1f}{l10_nota}</p></div>")
    return "\n".join(righe), "".join(html_righe)


# Soglie "valore" (31/07, richiesta esplicita utente dopo aver visto le 6
# formazioni originali: "le cheapest ottimizzate sono le piu' utili, in
# particolare quella solo classic"): NON piu' 3 config (A/B/C) con la
# STESSA soglia -- solo la config preferita (nessun limite Classic, cap L10
# 260), in 3 varianti che aumentano quanto l'algoritmo e' disposto a
# spendere per punto (soglia normale/x2/x3 -- NON un tetto di spesa fisso,
# solo meno avversione al prezzo: con una soglia piu' alta un candidato
# piu' caro ma migliore diventa relativamente piu' conveniente in
# 'punteggio - prezzo/soglia').
# --- Formazioni economiche sotto cap L10 (31/07, richiesta esplicita utente)
#
# Nate da un tentativo scartato: la prima versione ("fill 260") riempiva il cap
# al prezzo minimo e produceva formazioni corrette ma inutilizzabili -- 319 pt
# a 53 EUR, "una follia" (parole dell'utente). Il cap pieno da solo non e' un
# obiettivo sensato: e' il PREZZO a dover guidare, con il cap come vincolo.
# Sostituita da due criteri, entrambi con cap L10 rispettato:
#
#   A) MINIMO EUR/PUNTO -- minimizza prezzo_totale / punteggio_totale. Premia
#      chi rende molto per poco e scarta i "costosi ma forti" (es. 31 EUR per
#      73 pt). Risposta diretta a "cheapest for projected score".
#   B) PREZZO MINIMO PER RAGGIUNGERE UN TARGET -- la formazione piu' economica
#      che arriva ad almeno TARGET_PUNTEGGIO punti attesi (default 300). Se il
#      pool non ci arriva, lo dice invece di restituire un ripiego silenzioso.
#
# Vincolo DISTRIBUTIVO condiviso (richiesta esplicita: "non ha senso mettere un
# giocatore con l10 di 80 e altri 4 con l10 di 30"): nessuno schierato supera
# FILL_QUOTA_MAX volte la quota media (cap/5). Con cap 260 la quota e' 52 e il
# tetto 83.2, quindi quel caso non e' costruibile.
#
# Chi ha L10 ignoto e' ESCLUSO: qui il cap e' un vincolo vero, contarlo 0
# falserebbe tutto (vedi il bug del 31/07 in fetch_l10_reale).
FILL_QUOTA_MAX = float(os.environ.get('BEST_FIVE_FILL_QUOTA_MAX', '1.6'))
TARGET_PUNTEGGIO = float(os.environ.get('BEST_FIVE_TARGET_PUNTEGGIO', '300'))

# RIMOSSE (B04, P7 passaggio 2): PAREGGIO_ARENA_260 e RAPPORTO_ARENA_MINIMO
# erano un doppione HARDCODATO (259.5) del pareggio vero in
# build_formazione_globale.py (PAREGGIO_ARENA['ARENA_ALLSTARS_260']) --
# il commento diceva "ora si legge da li'" ma il codice non lo faceva
# affatto, proprio il tipo di divergenza silenziosa che questo progetto ha
# gia' pagato caro. Verificato che nessun punto del repo le importava
# (ne' qui ne' altrove, solo un commento in scouting_gw.py le nominava,
# rimosso anche quello): costanti morte, non solo disallineate. La
# previsione va CALIBRATA prima di confrontarla con l'L10, ma qui non serve
# nessuna costante locale: le righe arrivano gia' calibrate da
# _parse_consiglio_calibrato, che usa `gg.calibra_riga`.


def _stati_sotto_cap(shape, role_data, prezzi, max_classic, l10_cap, l10_map):
    """DP condivisa dai due criteri: esplora tutte le formazioni complete che
    rispettano cap L10, max_classic e il vincolo distributivo. Ritorna la
    lista di (punteggio, prezzo, l10_units, picks). None se il pool non basta."""
    if l10_cap is None or not l10_map:
        return None
    rarita_ammesse = ('in_season',) if max_classic == 0 else ('in_season', 'classic')
    cap_units = int(round(l10_cap * _RES_L10))
    n_slot = len(shape['role_slots']) + 1
    tetto_giocatore = (l10_cap / n_slot) * FILL_QUOTA_MAX

    def candidati(role):
        out = []
        for row, rarita, prezzo, l10 in _candidati_prezzo_ruolo(
                role_data.get(role, []), prezzi, l10_map, rarita_ammesse):
            if not l10 or l10 <= 0 or l10 > tetto_giocatore:
                continue
            out.append((row, rarita, prezzo, l10))
        return out

    # stato (l10_units, n_classic, punteggio) -> (prezzo_min, picks, usati).
    # Il punteggio entra nella CHIAVE: serve a tenere, per ogni punteggio
    # raggiungibile, il modo piu' economico di ottenerlo -- e' quello che
    # permette a entrambi i criteri di lavorare sulla stessa frontiera.
    states = {(0, 0, 0): (0.0, {}, frozenset())}
    for role in shape['role_slots']:
        cands = candidati(role)
        if not cands:
            return None
        nuovi = {}
        for (l10u, ncl, score), (prezzo_tot, picks, usati) in states.items():
            for row, rarita, prezzo, l10 in cands:
                if row['slug'] in usati:
                    continue
                nc = ncl + (1 if rarita == 'classic' else 0)
                if max_classic is not None and nc > max_classic:
                    continue
                l10u2 = l10u + int(round(l10 * _RES_L10))
                if l10u2 > cap_units:
                    continue
                key = (l10u2, nc, score + row['atteso'])
                p2 = prezzo_tot + prezzo
                cur = nuovi.get(key)
                if cur is None or p2 < cur[0] - 1e-9:
                    np_ = dict(picks)
                    np_[role] = (row, rarita, prezzo)
                    nuovi[key] = (p2, np_, usati | {row['slug']})
        if not nuovi:
            return None
        states = nuovi

    extra_cands = []
    for role in shape['extra_roles']:
        extra_cands.extend((role, row, rarita, prezzo, l10)
                            for row, rarita, prezzo, l10 in candidati(role))

    complete = []
    for (l10u, ncl, score), (prezzo_tot, picks, usati) in states.items():
        for role, row, rarita, prezzo, l10 in extra_cands:
            if row['slug'] in usati:
                continue
            nc = ncl + (1 if rarita == 'classic' else 0)
            if max_classic is not None and nc > max_classic:
                continue
            l10u2 = l10u + int(round(l10 * _RES_L10))
            if l10u2 > cap_units:
                continue
            finale = dict(picks)
            finale['EXTRA'] = (role, row, rarita, prezzo)
            complete.append((score + row['atteso'], prezzo_tot + prezzo, l10u2, finale))
    return complete or None


def _risultato_da(scelta, l10_cap):
    score, prezzo, l10_units, picks = scelta
    return {'prezzo_totale': prezzo, 'punteggio_totale': score, 'picks': picks,
            'l10_totale': l10_units / _RES_L10, 'l10_cap': l10_cap, 'l10_ignoti': 0}


def _ottimizza_lineup_euro_per_punto(shape, role_data, prezzi, max_classic, l10_cap, l10_map):
    """Criterio A: minimo prezzo/punteggio, con cap L10 rispettato."""
    complete = _stati_sotto_cap(shape, role_data, prezzi, max_classic, l10_cap, l10_map)
    if not complete:
        return None
    # A parita' di rapporto vince il punteggio piu' alto (l'utente: "cio' che
    # conta e' sempre il projected score").
    migliore = min(complete, key=lambda c: (c[1] / c[0] if c[0] > 0 else float('inf'), -c[0]))
    return _risultato_da(migliore, l10_cap)


def _ottimizza_lineup_target(shape, role_data, prezzi, max_classic, l10_cap, l10_map,
                              target=None):
    """Criterio B: formazione piu' economica che raggiunge almeno 'target'
    punti attesi, con cap L10 rispettato. None se il target e' irraggiungibile
    (il chiamante lo segnala, invece di mostrare un ripiego)."""
    target = TARGET_PUNTEGGIO if target is None else target
    complete = _stati_sotto_cap(shape, role_data, prezzi, max_classic, l10_cap, l10_map)
    if not complete:
        return None
    ammesse = [c for c in complete if c[0] >= target]
    if not ammesse:
        # RIPIEGO (31/07, richiesta esplicita utente: "se non arriva a 300
        # fagli generare comunque quella con pr totale piu' alto on a
        # budget"): invece di non mostrare nulla si prende il massimo
        # punteggio raggiungibile, e fra le formazioni che lo raggiungono la
        # piu' economica. Cosi' su una lega "corta" come K League -- che sotto
        # cap 260 non arriva a 300 -- si vede comunque la proposta migliore
        # possibile, con l'etichetta che dice chiaramente che il target non
        # era raggiungibile.
        massimo = max(c[0] for c in complete)
        migliore = min((c for c in complete if c[0] == massimo), key=lambda c: c[1])
        ris = _risultato_da(migliore, l10_cap)
        ris['nota'] = (f"target {target:.0f} pt non raggiungibile sotto cap {l10_cap:.0f} "
                       f"con questo pool: mostrata la migliore possibile ({massimo:.0f} pt)")
        log(f"[target {target:.0f}] {ris['nota']}")
        return ris
    migliore = min(ammesse, key=lambda c: (c[1], -c[0]))
    return _risultato_da(migliore, l10_cap)


VALORE_MOLTIPLICATORI = (1, 2, 3)
_VALORE_CONFIG = ('Nessun limite Classic (fino a 5), cap L10 260', None, 260.0)


def blocco_cheapest(bff, card_pool, role_data_dict, prezzi, l10_map):
    """Genera le 3 varianti CHEAPEST_CONFIGS (prezzo minimo assoluto,
    _ottimizza_lineup_min_prezzo) PIU' 3 varianti "ottimizzata valore"
    (_ottimizza_lineup_valore) sulla SOLA config preferita dall'utente
    (nessun limite Classic, cap L10 260) a soglia x1/x2/x3 (vedi
    VALORE_MOLTIPLICATORI) -- 6 formazioni totali. shape fissa GK/DEF/MID/
    FWD + 1 EXTRA da DEF/MID/FWD -- stessa struttura di IN_SEASON/ARENA."""
    shape = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD']}
    baseline = _baseline_costo_punto(role_data_dict, prezzi)
    testi, html_parti = [], []
    for label, max_classic, l10_cap in CHEAPEST_CONFIGS:
        risultato = _ottimizza_lineup_min_prezzo(shape, role_data_dict, prezzi, max_classic, l10_cap, l10_map)
        t, h = _render_cheapest(bff, card_pool, label, risultato, titolo='Cheapest')
        testi.append(t)
        html_parti.append(h)
    label_v, max_classic_v, l10_cap_v = _VALORE_CONFIG
    for moltiplicatore in VALORE_MOLTIPLICATORI:
        soglia = baseline * moltiplicatore if baseline is not None else None
        risultato = _ottimizza_lineup_valore(shape, role_data_dict, prezzi, max_classic_v, l10_cap_v, l10_map, soglia)
        etichetta = f"{label_v} — soglia x{moltiplicatore}"
        t, h = _render_cheapest(bff, card_pool, etichetta, risultato, titolo='Ottimizzata valore (prezzo/punteggio)')
        testi.append(t)
        html_parti.append(h)

    # Due formazioni economiche sotto cap L10 (31/07, richiesta esplicita
    # utente dopo aver scartato la versione "riempi il cap": produceva 319 pt
    # a 53 EUR, corretta ma inutilizzabile). Vedi il commento sopra i due
    # ottimizzatori.
    ris_rapporto = _ottimizza_lineup_euro_per_punto(shape, role_data_dict, prezzi,
                                                     max_classic_v, l10_cap_v, l10_map)
    t, h = _render_cheapest(bff, card_pool, label_v, ris_rapporto,
                             titolo=f'Miglior rapporto EUR/punto (cap {l10_cap_v:.0f})')
    testi.append(t)
    html_parti.append(h)

    ris_target = _ottimizza_lineup_target(shape, role_data_dict, prezzi,
                                           max_classic_v, l10_cap_v, l10_map)
    t, h = _render_cheapest(bff, card_pool, label_v, ris_target,
                             titolo=f'Piu economica da {TARGET_PUNTEGGIO:.0f}+ pt (cap {l10_cap_v:.0f})')
    testi.append(t)
    html_parti.append(h)
    return "\n\n".join(testi), "".join(html_parti)


N_CHEAPEST_UNDER23 = int(os.environ.get('BEST_FIVE_N_CHEAPEST_UNDER23', '3'))


def blocco_cheapest_under23(bff, card_pool, role_data_dict, n=N_CHEAPEST_UNDER23):
    """Elenco (NON una formazione completa, richiesta esplicita utente:
    "non per forza con formazione, bastano 2/3 per ogni ruolo") dei top-N
    candidati under-23 piu' economici per ruolo, presi dallo STESSO pool
    eleggibile per starterOdds gia' usato per le formazioni vere (non solo
    chi e' finito in una formazione). 'Economico' = il minimo tra i prezzi
    in_season/classic conosciuti; chi non ha NESSUN prezzo noto non entra in
    classifica (non e' confrontabile). Richiede _attach_eta/_attach_prezzi
    gia' chiamate su role_data_dict (legge 'under23'/'prezzo_in_season'/
    'prezzo_classic' gia' presenti su ogni riga)."""
    lines = ["", "=" * 70, f"CHEAPEST UNDER-23 (top {n} per ruolo, solo elenco, non formazione)", "=" * 70]
    html_parts = [MINI_CARD_CSS, f'<div class="esclusi-panel"><h3>Cheapest Under-23 (top {n} per ruolo)</h3>']
    for ROLE in ('GK', 'DEF', 'MID', 'FWD'):
        rows = role_data_dict.get(ROLE, [])
        candidati = []
        for r in rows:
            if not r.get('under23'):
                continue
            isp = r.get('prezzo_in_season')
            cl = r.get('prezzo_classic')
            disponibili = [p for p in (isp, cl) if p is not None]
            if not disponibili:
                continue
            prezzo_min = min(disponibili)
            rarita = 'classic' if (cl is not None and cl == prezzo_min) else 'in_season'
            candidati.append((prezzo_min, rarita, r))
        candidati.sort(key=lambda t: t[0])
        top = candidati[:n]

        lines.append(f"\n--- {ROLE} ---")
        html_parts.append(f'<div class="esclusi-role"><strong>{ROLE}</strong><div class="mini-card-strip">')
        if not top:
            lines.append("  (nessun under-23 con prezzo noto)")
            html_parts.append('<p class="empty">(nessun under-23 con prezzo noto)</p>')
        for i, (prezzo_min, rarita, r) in enumerate(top, 1):
            eta = r.get('eta')
            lines.append(f"  {i}) {r['slug']}: {r.get('atteso')} pt, eta {eta} -- {prezzo_min:.2f}EUR ({rarita})")
            card_html = bff.render_card_html(ROLE, r, rarita, card_pool, False)
            html_parts.append(
                f'<div class="mini-card">{card_html}'
                f'<div class="pcard-prezzo" style="font-size:0.78rem;font-weight:700;'
                f'color:var(--gold);margin-top:4px">{prezzo_min:.2f}EUR</div></div>')
        html_parts.append('</div></div>')
    html_parts.append('</div>')
    return "\n".join(lines), "".join(html_parts)


# NOTA: lo slot EXTRA e' etichettato "EXTRA (DEF)" (con parentesi, uno spazio
# interno) -- il gruppo 1 usa '.*' GREEDY apposta cosi' cattura tutto lo slot
# (qualunque sia la sua forma) fino all'ULTIMA occorrenza di "slug: N pt" sulla
# riga, invece di fermarsi al primo spazio come farebbe un '\S+' non greedy.
_SLUG_RIGA_FORMAZIONE_RE = re.compile(r'^(\S.*)\s([\w\-]+): (-?\d+) pt')


def _annota_prezzi_testo(blocco_testo, prezzi):
    """Aggiunge ' | IS: X€ | CL: Y€' in coda a ogni riga giocatore di un
    blocco testuale gia' formattato da bff.format_lineup -- nessuna modifica
    a format_lineup stesso (condiviso con la produzione), solo un
    post-processing di stringa qui in Best Five. Aggiunge ANCHE una riga con
    il prezzo TOTALE (somma In Season) della formazione, subito prima della
    riga 'TOTALE: N pt' gia' scritta da format_lineup (31/07, richiesta
    esplicita utente)."""
    righe_nuove = []
    totale_prezzo = 0.0
    mancanti = 0
    for riga in blocco_testo.split("\n"):
        m = _SLUG_RIGA_FORMAZIONE_RE.match(riga)
        if m:
            slug = m.group(2)
            info = prezzi.get(slug)
            if info is not None:
                isp = info.get('in_season')
                cl = info.get('classic')
                if isp is not None:
                    totale_prezzo += isp
                else:
                    mancanti += 1
                isp_s = f"{isp:.2f}EUR" if isp is not None else "N/D"
                cl_s = f"{cl:.2f}EUR" if cl is not None else "N/D"
                riga = f"{riga} [IS: {isp_s} | CL: {cl_s}]"
            else:
                mancanti += 1
        if riga.startswith("TOTALE:"):
            nota = f" (+{mancanti} senza prezzo noto)" if mancanti else ""
            righe_nuove.append(f"PREZZO TOTALE FORMAZIONE (In Season): {totale_prezzo:.2f}EUR{nota}")
        righe_nuove.append(riga)
    return "\n".join(righe_nuove)


def _annota_prezzi_html(html_blocco, prezzi):
    """Inietta un <script> che, per ogni .pcard[data-slug] gia' presente nel
    report (render_lineup_html di bff, condiviso con la produzione, non
    toccato), aggiunge una riga prezzo -- stesso pattern di
    rendi_carte_cliccabili (post-processing via script, non una modifica del
    template). Aggiunge ANCHE il prezzo TOTALE (somma In Season) di ogni
    formazione, sommando i prezzi delle carte dello stesso .lineup-block
    (31/07, richiesta esplicita utente: font prezzo per-carta troppo piccolo/
    illeggibile, e totale formazione non visibile -- entrambi fix qui)."""
    payload = json.dumps(prezzi)
    script = f"""
<script>
(function() {{
  var prezzi = {payload};
  document.querySelectorAll('.pcard[data-slug]').forEach(function (card) {{
    var info = prezzi[card.dataset.slug];
    if (!info) return;
    var isp = info.in_season != null ? info.in_season.toFixed(2) + 'EUR' : 'N/D';
    var cl = info.classic != null ? info.classic.toFixed(2) + 'EUR' : 'N/D';
    var div = document.createElement('div');
    div.className = 'pcard-prezzo';
    div.style.cssText = 'font-size:0.78rem;font-weight:700;color:var(--gold);margin-top:4px;line-height:1.3';
    div.textContent = 'IS: ' + isp + ' | CL: ' + cl;
    card.querySelector('.pcard-body, .pcard').appendChild(div);
  }});
  document.querySelectorAll('.lineup-block').forEach(function (block) {{
    var cards = block.querySelectorAll('.pcard[data-slug]');
    if (!cards.length) return;
    var totale = 0, mancanti = 0;
    cards.forEach(function (card) {{
      var info = prezzi[card.dataset.slug];
      var isp = info ? info.in_season : null;
      if (isp != null) {{ totale += isp; }} else {{ mancanti += 1; }}
    }});
    var meta = block.querySelector('.lineup-meta');
    if (!meta) return;
    var div = document.createElement('div');
    div.className = 'lineup-prezzo-totale';
    div.style.cssText = 'font-size:0.85rem;font-weight:700;color:var(--gold);margin-top:6px';
    var nota = mancanti ? (' (+' + mancanti + ' senza prezzo noto)') : '';
    div.textContent = 'Prezzo totale formazione (In Season): ' + totale.toFixed(2) + 'EUR' + nota;
    meta.appendChild(div);
  }});
}})();
</script>
"""
    if '</body>' in html_blocco:
        return html_blocco.replace('</body>', script + '</body>')
    return html_blocco + script


def _annota_eta_testo(blocco_testo, eta_map):
    """Aggiunge ' [U23]' in coda a ogni riga giocatore under-23 -- stesso
    post-processing per riga di _annota_prezzi_testo, ma SEPARATO (chiamato
    dopo, sulla stringa gia' annotata con i prezzi) per non toccare quella
    funzione gia' testata."""
    righe_nuove = []
    for riga in blocco_testo.split("\n"):
        m = _SLUG_RIGA_FORMAZIONE_RE.match(riga)
        if m:
            slug = m.group(2)
            eta = eta_map.get(slug)
            if eta is not None and eta <= UNDER23_MAX_ETA:
                riga = f"{riga} [U23]"
        righe_nuove.append(riga)
    return "\n".join(righe_nuove)


def _annota_eta_html(html_blocco, eta_map):
    """Inietta un <script> che aggiunge un piccolo 'stemmino' U23 (angolo
    opposto al badge capitano, stesso stile .pcard-captain gia' usato in
    produzione per il badge 'C' -- nessun CSS nuovo) su ogni .pcard[data-
    slug] under-23 (31/07, richiesta esplicita utente). Stesso pattern di
    _annota_prezzi_html: post-processing via script separato, mai una
    modifica di render_card_html condiviso con la produzione."""
    payload = json.dumps(eta_map)
    script = f"""
<script>
(function() {{
  var eta = {payload};
  document.querySelectorAll('.pcard[data-slug]').forEach(function (card) {{
    var e = eta[card.dataset.slug];
    if (e == null || e > {UNDER23_MAX_ETA}) return;
    var badge = document.createElement('span');
    badge.className = 'pcard-captain';
    badge.style.cssText = 'left:5px; right:auto; background:#3aa1e8; font-size:0.5rem;';
    badge.title = 'Under 23 (eta\\' ' + e + ')';
    badge.textContent = 'U23';
    card.appendChild(badge);
  }});
}})();
</script>
"""
    if '</body>' in html_blocco:
        return html_blocco.replace('</body>', script + '</body>')
    return html_blocco + script


def _renderizza_risultati(bff, all_results, card_pool):
    """Fattorizzato da costruisci_formazione_vera (31/07, riuso identico per
    costruisci_formazione_contender): trasforma i risultati di
    gg.generate_lineups_for_type in blocchi testo/HTML, STESSO rendering
    (format_lineup/render_lineup_html, apply_xp_bonus=False) usato dalla
    produzione in FASE 2 di build_formazione_globale.py."""
    lineup_blocks, lineup_html_blocks = [], []
    generated, totale = 0, 0
    for r in all_results:
        if 'error' in r:
            lineup_blocks.append(r['error'])
            lineup_html_blocks.append(f'<p class="error-block">{r["error"]}</p>')
            continue
        block_text, punti = bff.format_lineup(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'])
        lineup_blocks.append(block_text)
        lineup_html_blocks.append(bff.render_lineup_html(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'], apply_xp_bonus=False))
        generated += 1
        totale += punti
    return generated, totale, lineup_blocks, lineup_html_blocks


# --- "Contender" limitato a N leghe (31/07, richiesta esplicita utente) ----
#
# L'utente vuole Best Five per la competizione Sorare "Contender" (slug reale
# confermato via query live: eligibleSo5Competitions='seasonal-contenders',
# stesse regole di MLS/K League In Season: 5 titolari+2 riserve, min 4 carte
# In Season, capitano +50%), ma limitata SOLO a 3 campionati gia' tracciati
# (Austria, Croazia, 2.Bundesliga) invece che alle ~20 leghe reali che
# Contender raggruppa su Sorare -- una pipeline completa (nuova eleggibilita'
# trasversale nella discovery di produzione) resta backlog separato, vedi
# project_backlog_slug_contender.
#
# Qui NON si duplica la logica MLS_IN_SEASON/KLEAGUE_IN_SEASON: si registra
# un tipo 'CONTENDER_IN_SEASON' a runtime sulla PROPRIA istanza di 'gg'
# (import dinamico, non quella di produzione -- zero rischio per
# formazione_giornata.yml) e si passa da generate_lineups_for_type REALE con
# lo stesso trattamento di MLS/K League: IN_SEASON_TYPES.add(...) fa si' che
# in_season_multi/apply_positive_synergy=False si applichino automaticamente
# (vedi il refactor di build_formazione_globale.py, IN_SEASON_TYPES).
def _registra_tipo_in_season(gg, tipo, pool_league, label):
    gg.FORMATION_SHAPES[tipo] = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
                                  'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1}
    gg.POOL_LEAGUE_BY_TYPE[tipo] = pool_league
    gg.LABELS[tipo] = label
    gg.IN_SEASON_TYPES.add(tipo)
    gg.STACK_GUARD_TYPES.add(tipo)
    gg.CHECK_CAP260_TYPES.add(tipo)
    gg.XP_BONUS_TYPES.add(tipo)
    # gg.L10_CAP_BY_TYPE: NESSUNA voce per 'tipo' -- assenza = nessun cap
    # obbligatorio, corretto per un tipo In Season (a differenza delle Arene).
    # gg.VARIANCE_MODE_TYPES: NON aggiunto apposta -- stesso motivo per cui
    # MLS_IN_SEASON/KLEAGUE_IN_SEASON non ci sono (variance_mode=False per
    # le In Season, misurato irrilevante/rumoroso il 30-31/07).
    gg.bff.CAPTAIN_BONUS_BY_TYPE[tipo] = 0.5
    gg.bff.CAP260_L10_THRESHOLD_BY_TYPE[tipo] = 260.0


def costruisci_formazione_contender(leghe, count):
    """Best Five 'Contender' limitato alle leghe passate in 'leghe' (es.
    ['austria','croazia','germania2']): pool COMBINATO delle migliori carte
    globali di ciascuna, NESSUNA nuova query -- legge il consiglio_*.txt piu'
    recente gia' prodotto dal run Best Five NORMALE di ciascuna lega
    (formazione_<lega>/output/<lega>_<ruolo>_all/consiglio_*.txt, stessa
    formula di produzione di quella lega). Richiede che ciascuna lega abbia
    gia' un Best Five --run completato di recente per tutti e 4 i ruoli."""
    gg = _import_gg()
    bff = gg.bff
    tipo = 'CONTENDER_IN_SEASON'
    _registra_tipo_in_season(gg, tipo, 'contender', 'In Season Contender')

    merged_role_data = {ROLE: [] for ROLE in gg.ROLES}
    names = {}
    for lega in leghe:
        for ruolo, ROLE in (('gk', 'GK'), ('def', 'DEF'), ('mid', 'MID'), ('fwd', 'FWD')):
            out_dir = output_dir_per_ruolo(lega, ruolo)
            path = bff.latest_consiglio(out_dir)
            if not path:
                log(f"[{lega}/{ruolo}] Nessun consiglio_*.txt trovato in {out_dir} -- "
                    f"esegui prima 'python best_five.py {lega} --run' per questa lega.")
                continue
            rows = _parse_consiglio_calibrato(bff, gg, path, ROLE)
            for row in rows:
                row['league'] = lega
            merged_role_data[ROLE].extend(rows)
            log(f"[{lega}/{ruolo}] {len(rows)} giocatori da {os.path.basename(path)}.")
            # Nomi: preferenza al discovery_global (pool intero), fallback al
            # discovery posseduti (stesso schema di costruisci_formazione_vera).
            for names_dir in (f'{lega}_{ruolo}_discovery_global', f'{lega}_{ruolo}_discovery'):
                names_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', names_dir, 'player_names.json')
                if os.path.exists(names_path):
                    with open(names_path, encoding='utf-8') as f:
                        loaded = json.load(f)
                    for slug, nome in loaded.items():
                        names.setdefault(slug, nome)

    mancanti = [r for r in gg.ROLES if not merged_role_data.get(r)]
    if mancanti:
        log(f"ATTENZIONE: ruoli senza candidati nel pool Contender combinato: {mancanti}.")

    _attach_odds(merged_role_data, _odds_run_corrente())
    prezzi = _attach_prezzi(merged_role_data)
    eta_map = _attach_eta(merged_role_data) if GENERA_UNDER23 else {}

    role_data = {'contender': merged_role_data}
    pools = {'contender': {role: gg._NoFilterPool(role, 'contender', merged_role_data[role]) for role in gg.ROLES}}
    card_pool = bff.CardPool({}, names=names)

    all_results = gg.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
    generated, totale, lineup_blocks, lineup_html_blocks = _renderizza_risultati(bff, all_results, card_pool)
    lineup_blocks = [_annota_prezzi_testo(b, prezzi) for b in lineup_blocks]
    lineup_blocks = [_annota_eta_testo(b, eta_map) for b in lineup_blocks]

    testo_esclusi, html_esclusi = _blocco_top_esclusi(bff, card_pool, merged_role_data)
    lineup_blocks.append(testo_esclusi)
    lineup_html_blocks.append(html_esclusi)

    if GENERA_CHEAPEST:
        l10_map_cheapest = fetch_l10_per_ruoli(merged_role_data)
        testo_cheap, html_cheap = blocco_cheapest(bff, card_pool, merged_role_data, prezzi, l10_map_cheapest)
        lineup_blocks.append(testo_cheap)
        lineup_html_blocks.append(html_cheap)

    if GENERA_UNDER23:
        testo_u23, html_u23 = blocco_cheapest_under23(bff, card_pool, merged_role_data)
        lineup_blocks.append(testo_u23)
        lineup_html_blocks.append(html_u23)

    log(f"Formazione Contender (leghe: {', '.join(leghe)}): {generated}/{count} generate.")
    return bff, generated, totale, lineup_blocks, lineup_html_blocks, prezzi, eta_map


def rendi_carte_cliccabili(html_report):
    """Aggiunge un click-handler alle pcard del report (30/07, richiesta
    esplicita utente: "che mi rimandino proprio alla carta") che apre la
    pagina Sorare del giocatore in una nuova scheda -- stesso pattern URL
    gia' usato in produzione (scanners/bot_profit.py, _sorare_market_link,
    pagina PROFILO giocatore, non lo shop/mercato con filtro rarita': li' si
    vedono comunque le carte in vendita). Post-processing via <script>
    iniettato invece di modificare render_card_html/render_report_html in
    formazione_mls/build_formazione_finale.py -- quel file resta condiviso
    con la produzione (drag&drop tra formazioni reali), toccarlo per un
    comportamento SOLO di Best Five sarebbe rischioso. Le pcard hanno gia'
    'data-slug' (vedi render_card_html), qui si legge soltanto."""
    script = """
<script>
document.querySelectorAll('.pcard[data-slug]').forEach(function (card) {
  card.style.cursor = 'pointer';
  card.title = 'Apri su Sorare';
  card.addEventListener('click', function () {
    window.open('https://sorare.com/it/football/players/' + card.dataset.slug, '_blank', 'noopener');
  });
});
</script>
"""
    if '</body>' in html_report:
        return html_report.replace('</body>', script + '</body>')
    return html_report + script


# --- Restyling report Best Five (31/07, richiesta esplicita utente) -------
#
# SOLO Best Five: la produzione (formazione_giornata.yml) continua a usare
# HTML_REPORT_TEMPLATE/render_report_html di formazione_mls invariati -- qui
# si aggiunge soltanto, in coda al documento gia' prodotto, uno <style> che
# vince per ordine di cascata e uno <script> che raggruppa i blocchi gia'
# presenti in sezioni navigabili. Nessuna riscrittura del markup lato server:
# stesso identico pattern di rendi_carte_cliccabili/_annota_prezzi_html, cosi'
# se domani cambia il template condiviso questo continua a funzionare (o al
# massimo perde la sola parte estetica, mai i dati).
#
# Tab: "Intero" mostra tutto scorrevole (default), le altre mostrano SOLO la
# sezione scelta (richiesta esplicita utente: "falle bloccare, in modo che si
# veda solo quella selezionata").
RESTYLE_CSS = """
<style>
  :root {
    --bg: #0c1210; --surface: #141c19; --surface-2: #1d2824; --stripe: #26332d;
    --text: #eef1ec; --muted: #8fa199; --muted-2: #63756c; --gold: #e8b84b;
    --border: rgba(238,241,236,0.09);
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f2f4f0; --surface: #ffffff; --surface-2: #eef1ec; --stripe: #e3e8e1;
      --text: #16211c; --muted: #566159; --muted-2: #869185; --gold: #9c7414;
      --border: rgba(20,30,25,0.10);
    }
  }
  body { padding: 0 !important; max-width: none !important; }
  .bf-topbar {
    position: sticky; top: 0; z-index: 30;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    padding: 14px 32px 0;
  }
  .bf-topbar-inner { max-width: 1180px; margin: 0 auto; }
  .bf-tabs { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; }
  .bf-tabs::-webkit-scrollbar { display: none; }
  .bf-tab {
    appearance: none; border: none; background: none; color: var(--muted);
    font-size: 0.82rem; font-weight: 600; padding: 10px 16px 12px; cursor: pointer;
    border-bottom: 2px solid transparent; white-space: nowrap; font-family: inherit;
    transition: color 0.15s ease;
  }
  .bf-tab:hover { color: var(--text); }
  .bf-tab[aria-current="true"] { color: var(--text); border-bottom-color: var(--gold); }
  .bf-tab .bf-count { color: var(--muted-2); font-weight: 700; margin-left: 5px; }
  .bf-strip { display: flex; gap: 10px; overflow-x: auto; padding: 14px 0 16px; }
  .bf-strip::-webkit-scrollbar { display: none; }
  .bf-chip {
    flex: 0 0 auto; display: flex; flex-direction: column; gap: 5px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 9px 15px; min-width: 150px; cursor: pointer; color: inherit;
    text-decoration: none; transition: border-color 0.15s ease, transform 0.15s ease;
  }
  .bf-chip:hover { border-color: var(--gold); transform: translateY(-1px); }
  .bf-chip-label {
    font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); font-weight: 700;
  }
  .bf-chip-score { font-size: 1.25rem; font-weight: 800; font-variant-numeric: tabular-nums; }
  .bf-chip-score .bf-unit { font-size: 0.66rem; color: var(--muted); font-weight: 600; margin-left: 3px; }
  .bf-head { max-width: 1180px; margin: 0 auto; padding: 26px 32px 0; }
  .bf-main { max-width: 1180px; margin: 0 auto; padding: 8px 32px 72px; }
  .bf-section { scroll-margin-top: 130px; }
  .bf-section-head {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: 12px; margin: 34px 0 14px;
  }
  .bf-section-head h2 {
    font-size: 1rem; font-weight: 800; letter-spacing: 0.01em; margin: 0;
  }
  .bf-section-head .bf-hint { color: var(--muted); font-size: 0.75rem; }
  .lineup-block, .esclusi-panel {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 18px; margin-bottom: 16px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  }
  @media (prefers-color-scheme: light) {
    .lineup-block, .esclusi-panel { box-shadow: 0 8px 24px rgba(20,30,25,0.07); }
  }
  .esclusi-panel h3 { margin-top: 0; }
  footer { max-width: 1180px; margin: 0 auto; padding: 0 32px 48px; }
</style>
"""

RESTYLE_JS = """
<script>
(function () {
  var SEZIONI = [
    { id: 'formazioni', label: 'Formazioni',
      hint: 'Scelte solo per punteggio atteso, il prezzo e informativo' },
    { id: 'esclusi', label: 'Top esclusi',
      hint: 'Candidati eleggibili mai schierati in nessuna formazione' },
    { id: 'cheapest', label: 'Cheapest',
      hint: 'Prezzo totale minimo assoluto, punteggio come criterio di pareggio' },
    { id: 'valore', label: 'Ottimizzata valore',
      hint: 'Soglia prezzo/punteggio calcolata sul pool reale di questa run' },
    { id: 'under23', label: 'Under 23',
      hint: 'Solo elenco dei piu economici per ruolo, non una formazione' }
  ];

  function sezioneDi(el) {
    if (el.classList && el.classList.contains('lineup-block')) return 'formazioni';
    var h3 = el.querySelector ? el.querySelector('h3') : null;
    if (!h3) return null;
    var t = (h3.textContent || '').trim();
    if (t.indexOf('Cheapest Under-23') === 0) return 'under23';
    if (t.indexOf('Ottimizzata valore') === 0) return 'valore';
    if (t.indexOf('Miglior rapporto') === 0 || t.indexOf('Piu economica') === 0) return 'valore';
    if (t.indexOf('Cheapest') === 0) return 'cheapest';
    if (t.indexOf('Top') === 0) return 'esclusi';
    return null;
  }

  var h1 = document.querySelector('h1');
  var subhead = document.querySelector('p.subhead');
  var footer = document.querySelector('footer');
  if (!h1) return;

  // Raccoglie i blocchi gia' renderizzati, nell'ordine in cui stanno nel
  // documento (uno <style> di MINI_CARD_CSS precede ogni pannello: resta
  // dov'e', e' inerte e vale per tutta la pagina).
  var gruppi = {};
  SEZIONI.forEach(function (s) { gruppi[s.id] = []; });
  Array.prototype.slice.call(document.body.children).forEach(function (el) {
    var sez = sezioneDi(el);
    if (sez) gruppi[sez].push(el);
  });

  var head = document.createElement('div');
  head.className = 'bf-head';
  head.appendChild(h1);
  if (subhead) head.appendChild(subhead);

  var main = document.createElement('main');
  main.className = 'bf-main';
  SEZIONI.forEach(function (s) {
    if (!gruppi[s.id].length) return;
    var sec = document.createElement('section');
    sec.className = 'bf-section';
    sec.id = 'bf-' + s.id;
    var sh = document.createElement('div');
    sh.className = 'bf-section-head';
    sh.innerHTML = '<h2></h2><span class="bf-hint"></span>';
    sh.querySelector('h2').textContent = s.label;
    sh.querySelector('.bf-hint').textContent = s.hint;
    sec.appendChild(sh);
    gruppi[s.id].forEach(function (el) { sec.appendChild(el); });
    main.appendChild(sec);
  });

  var topbar = document.createElement('div');
  topbar.className = 'bf-topbar';
  var inner = document.createElement('div');
  inner.className = 'bf-topbar-inner';
  var nav = document.createElement('nav');
  nav.className = 'bf-tabs';
  var strip = document.createElement('div');
  strip.className = 'bf-strip';
  inner.appendChild(nav);
  inner.appendChild(strip);
  topbar.appendChild(inner);

  document.body.insertBefore(topbar, document.body.firstChild);
  topbar.parentNode.insertBefore(head, topbar.nextSibling);
  head.parentNode.insertBefore(main, head.nextSibling);
  if (footer) document.body.appendChild(footer);

  function mostra(vista, btn) {
    Array.prototype.slice.call(nav.children).forEach(function (b) {
      b.removeAttribute('aria-current');
    });
    if (btn) btn.setAttribute('aria-current', 'true');
    SEZIONI.forEach(function (s) {
      var sec = document.getElementById('bf-' + s.id);
      if (!sec) return;
      sec.style.display = (vista === 'intero' || vista === s.id) ? '' : 'none';
    });
  }

  function aggiungiTab(id, label, count) {
    var b = document.createElement('button');
    b.className = 'bf-tab';
    b.type = 'button';
    b.textContent = label;
    if (count) {
      var sp = document.createElement('span');
      sp.className = 'bf-count';
      sp.textContent = count;
      b.appendChild(sp);
    }
    b.addEventListener('click', function () { mostra(id, b); window.scrollTo({ top: 0, behavior: 'smooth' }); });
    nav.appendChild(b);
    return b;
  }

  var tabIntero = aggiungiTab('intero', 'Intero', 0);
  SEZIONI.forEach(function (s) {
    if (gruppi[s.id].length) aggiungiTab(s.id, s.label, gruppi[s.id].length);
  });
  mostra('intero', tabIntero);

  // Riepilogo cliccabile: una scheda per formazione principale, salta al
  // blocco corrispondente tornando prima alla vista "Intero" (il blocco
  // potrebbe stare in una sezione nascosta dal filtro attivo).
  gruppi['formazioni'].forEach(function (blocco, i) {
    var titolo = blocco.querySelector('.lineup-title');
    var fig = blocco.querySelector('.lineup-total .figure');
    var figCap = blocco.querySelector('.lineup-total .figure.with-captain');
    var prezzo = blocco.querySelector('.lineup-prezzo-totale');
    if (!blocco.id) blocco.id = 'bf-formazione-' + (i + 1);
    var chip = document.createElement('a');
    chip.className = 'bf-chip';
    chip.href = '#' + blocco.id;
    var lab = document.createElement('span');
    lab.className = 'bf-chip-label';
    lab.textContent = titolo ? titolo.textContent.trim() : ('Formazione ' + (i + 1));
    var sc = document.createElement('span');
    sc.className = 'bf-chip-score';
    sc.textContent = (figCap || fig) ? (figCap || fig).textContent.trim() : '';
    if (figCap) {
      var u = document.createElement('span');
      u.className = 'bf-unit';
      u.textContent = 'c/cap.';
      sc.appendChild(u);
    }
    chip.appendChild(lab);
    chip.appendChild(sc);
    if (prezzo) {
      var pr = document.createElement('span');
      pr.className = 'bf-chip-label';
      pr.style.color = 'var(--gold)';
      pr.textContent = (prezzo.textContent.split(':')[1] || '').trim();
      chip.appendChild(pr);
    }
    chip.addEventListener('click', function (ev) {
      ev.preventDefault();
      mostra('intero', tabIntero);
      blocco.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    strip.appendChild(chip);
  });
  if (!gruppi['formazioni'].length) strip.style.display = 'none';
})();
</script>
"""


def applica_restyling(html_report):
    """Restyling del report Best Five (tab Intero/per-sezione + tema e
    spaziature), SOLO additivo -- vedi commento sopra."""
    blocco = RESTYLE_CSS + RESTYLE_JS
    if '</body>' in html_report:
        return html_report.replace('</body>', blocco + '</body>')
    return html_report + blocco


# Tetto REALE di job concorrenti dell'account GitHub Actions (stesso valore
# di SLOT_CONCORRENTI in pipeline_artifacts.py, verificato sulla pipeline di
# produzione — vedi commento li' per i dettagli della misura).
SLOT_CONCORRENTI = 20


def raccogli_sopravvissuti(lega, ruoli):
    """Per ogni ruolo richiesto: pool gia' filtrato per qualita' + prefiltro
    starterOdds. Ritorna una lista PIATTA di {'ruolo': r, 'slug': s} su tutti
    i ruoli insieme (il job predict a matrice non distingue per ruolo, vedi
    bin_round_robin)."""
    sopravvissuti = []
    for ruolo in ruoli:
        pool = carica_pool_qualita_filtrato(lega, ruolo)
        log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
        log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} sulla prossima partita...")
        survived = prefiltra_starter_odds(ruolo, pool)
        log(f"[{ruolo}] Sopravvissuti al prefiltro: {len(survived)}/{len(pool)}.")
        sopravvissuti.extend({'ruolo': ruolo, 'slug': sl, 'odds': od} for sl, od in survived)
    return sopravvissuti


def bin_round_robin(items, n_bin):
    """Distribuisce items in <= n_bin gruppi bilanciati per NUMERO (non per
    costo stimato: a differenza della pipeline di produzione, qui non c'e'
    ancora uno storico di costi misurati per giocatore -- vedi
    pipeline_costi.json/LPT in pipeline_artifacts.py per il modello completo,
    non replicato qui per semplicita', il pool e' molto piu' piccolo). Ordine
    round-robin invece che a blocchi, cosi' un ruolo piu' lento (es. MID,
    ~28s/giocatore contro i ~20s di FWD) non finisce concentrato in pochi bin."""
    if not items:
        return []
    n_bin = max(1, min(n_bin, len(items)))
    bins = [[] for _ in range(n_bin)]
    for i, item in enumerate(items):
        bins[i % n_bin].append(item)
    return [b for b in bins if b]


def _scrivi_gruppi_output(nome_var, gruppi):
    """Scrive 'nome_var=<json compatto>' su GITHUB_OUTPUT (se presente) e su
    stdout -- stesso formato per tutti gli step 'matrice' del workflow."""
    output_line = f'{nome_var}=' + json.dumps(gruppi, separators=(',', ':'))
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(output_line + '\n')
    print(output_line)


def _gruppi_da_items(items, n_bin):
    """bin_round_robin + incapsulamento in payload base64/etichetta --
    fattorizzato perche' usato sia per shardare il pool (prima delle
    starterOdds) sia per shardare i sopravvissuti (prima del predict)."""
    gruppi_raw = bin_round_robin(items, n_bin)
    gruppi = []
    for i, g in enumerate(gruppi_raw):
        payload = base64.b64encode(json.dumps(g, separators=(',', ':')).encode()).decode()
        etichetta = ' '.join(f"{it['ruolo']}/{it['slug']}" for it in g[:2])
        if len(g) > 2:
            etichetta += f' +{len(g) - 2}'
        gruppi.append({'nome': f"{i + 1:02d} {etichetta}", 'g': payload})
    return gruppi


def cmd_matrice_pool(lega, ruoli, n_bin):
    """NUOVO (30/07, parallelizzazione del prefiltro): sharda il pool GIA'
    filtrato per qualita' in <= n_bin gruppi, SENZA controllare le
    starterOdds qui -- quel controllo (costoso, una query per giocatore)
    avviene poi in parallelo nel job 'prefiltro' a matrice, invece che in un
    unico job sequenziale (era il vero collo di bottiglia: ~5-6 minuti per
    ~280 candidati K League, misurato sui run reali del 30/07)."""
    pool_piatto = []
    for ruolo in ruoli:
        pool = carica_pool_qualita_filtrato(lega, ruolo)
        log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
        pool_piatto.extend({'ruolo': ruolo, 'slug': s} for s in pool)
    gruppi = _gruppi_da_items(pool_piatto, n_bin)
    _scrivi_gruppi_output('gruppi_pool', gruppi)
    log(f"[matrice-pool] {len(pool_piatto)} candidati totali (pre-starterOdds) in {len(gruppi)} gruppi.")


def cmd_prefiltra_shard(lega, payload_b64, out_path):
    """Controlla le starterOdds SOLO per lo shard ricevuto (una frazione del
    pool totale) e scrive i sopravvissuti su disco, per essere caricati come
    artifact e uniti nel job 'prefiltro_merge'. Gira in parallelo con gli
    altri shard (fino a SLOT_CONCORRENTI insieme) -- stesso guadagno di
    velocita' gia' visto per il predict."""
    items = json.loads(base64.b64decode(payload_b64).decode())
    per_ruolo = {}
    for it in items:
        per_ruolo.setdefault(it['ruolo'], []).append(it['slug'])
    sopravvissuti = []
    for ruolo, slugs in per_ruolo.items():
        log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} "
            f"su {len(slugs)} candidati di questo shard...")
        survived = prefiltra_starter_odds(ruolo, slugs)
        sopravvissuti.extend({'ruolo': ruolo, 'slug': sl, 'odds': od} for sl, od in survived)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(sopravvissuti, f)
    log(f"Shard: {len(sopravvissuti)}/{len(items)} sopravvissuti, scritti in {out_path}")


def cmd_merge_prefiltro(artifacts_dir, n_bin):
    """Unisce i sopravvissuti di tutti gli shard del prefiltro (un file
    survivors.json per artifact scaricato) e li risharda in <= n_bin gruppi
    per il job predict -- STESSO output ('gruppi=', vedi _scrivi_gruppi_output)
    di quando il prefiltro era un unico job sequenziale, cosi' il job
    'predict' a valle non ha bisogno di nessuna modifica."""
    sopravvissuti = []
    if os.path.isdir(artifacts_dir):
        for root, _dirs, files in os.walk(artifacts_dir):
            for name in files:
                if name == 'survivors.json':
                    with open(os.path.join(root, name), encoding='utf-8') as f:
                        sopravvissuti.extend(json.load(f))
    gruppi = _gruppi_da_items(sopravvissuti, n_bin)
    _scrivi_gruppi_output('gruppi', gruppi)
    log(f"[merge-prefiltro] {len(sopravvissuti)} sopravvissuti totali (da tutti gli shard) "
        f"in {len(gruppi)} gruppi per il predict.")


def cmd_matrice(lega, ruoli, n_bin):
    """Prefiltro (qualita' gia' fatta in discovery, starterOdds qui) + shard
    in <= n_bin gruppi per il job predict a matrice -- stesso schema
    discovery/predict di formazione_giornata.yml (vedi pipeline_artifacts.py
    'matrice'), senza pero' il modello di costo storico: qui il pool dopo il
    doppio filtro e' piccolo (decine, non centinaia) e i tempi per giocatore
    abbastanza uniformi da non giustificare quella complessita'."""
    sopravvissuti = raccogli_sopravvissuti(lega, ruoli)
    gruppi = _gruppi_da_items(sopravvissuti, n_bin)
    _scrivi_gruppi_output('gruppi', gruppi)
    log(f"[matrice] {len(sopravvissuti)} sopravvissuti totali in {len(gruppi)} gruppi "
        f"(target <= {n_bin}).")


def cmd_predict_shard(lega, payload_b64):
    """Esegue le predizioni per lo shard ricevuto (lista di {'ruolo','slug'}),
    un subprocess TARGET_SLUG per giocatore, in sequenza DENTRO questo job --
    ma il job stesso gira in parallelo con gli altri shard della matrice
    (fino a SLOT_CONCORRENTI insieme, gestito da GitHub Actions), che e' dove
    sta il guadagno di velocita' reale rispetto al vecchio loop sequenziale
    in un unico job."""
    items = json.loads(base64.b64decode(payload_b64).decode())
    log(f"Shard ricevuto: {len(items)} giocatori.")
    for idx, item in enumerate(items, 1):
        ruolo, slug = item['ruolo'], item['slug']
        log(f"[{ruolo}] [{idx}/{len(items)}] Predizione per {slug}...")
        run_prediction_su_slug(lega, ruolo, slug)
        if idx < len(items):
            time.sleep(2.0)


def main():
    args = sys.argv[1:]
    if not args:
        print(f"Uso: python best_five.py <lega> [--run] [--backups N] [--roles gk,def,mid,fwd]\n"
              f"     python best_five.py <lega> --matrice [--roles ...] [--n-bin N]   # job 'prefiltro'\n"
              f"     python best_five.py <lega> --predict-shard <base64>              # job 'predict' (un bin)\n"
              f"Leghe supportate (discovery globale completa): {', '.join(LEGHE_SUPPORTATE)}")
        sys.exit(1)

    lega = args[0]

    # Modalita' "contender" (31/07, richiesta esplicita utente): pool
    # COMBINATO di piu' leghe gia' processate singolarmente con Best Five
    # normale (--run su ciascuna), NESSUNA nuova query qui -- solo lettura
    # dei consiglio_*.txt piu' recenti di ciascuna lega elencata in --leghe.
    # Esce subito, non condivide il resto di main() (che serve alla lega
    # singola).
    if lega == 'contender':
        if '--leghe' not in args:
            log("ERRORE: 'contender' richiede --leghe lega1,lega2,... (es. austria,croazia,germania2).")
            sys.exit(1)
        idx = args.index('--leghe')
        leghe = [s.strip() for s in args[idx + 1].split(',') if s.strip()]
        n_backup = 2
        if '--backups' in args:
            idx_b = args.index('--backups')
            n_backup = int(args[idx_b + 1])

        bff, generated, totale, lineup_blocks, lineup_html_blocks, prezzi, eta_map = costruisci_formazione_contender(
            leghe, 1 + n_backup)

        out_dir = os.path.join(REPO_ROOT, 'formazione_contender', 'output', 'best_five')
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')

        report = (
            "=" * 70 + "\n"
            f"BEST FIVE — CONTENDER (limitato a: {', '.join(leghe)})\n"
            f"Generato: {datetime.datetime.utcnow().isoformat()}Z\n"
            f"{generated} formazione/i generata/e su {1 + n_backup} richieste, "
            f"totale complessivo {totale} pt attesi.\n"
            f"Pool: solo le leghe {', '.join(leghe)} (NON tutte le leghe reali di Contender su "
            "Sorare, vedi backlog). Sinergie/anti-stack/captain calcolati come nel tool unificato.\n"
            + "=" * 70 + "\n\n"
            + "\n\n".join(lineup_blocks)
        )
        out_path = os.path.join(out_dir, f'best_five_contender_{ts}.txt')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(report)

        page_title = "Best Five — Contender (limitato)"
        page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                         f"{generated}/{1 + n_backup} formazioni, pool limitato a {', '.join(leghe)} "
                         "(NON tutte le leghe reali di Contender). Sinergie/anti-stack/captain "
                         "come nel tool unificato.")
        footer = "Script separato e READ-ONLY rispetto alla pipeline di produzione."
        html_report = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer)
        html_report = rendi_carte_cliccabili(html_report)
        html_report = _annota_prezzi_html(html_report, prezzi)
        html_report = _annota_eta_html(html_report, eta_map)
        html_report = applica_restyling(html_report)
        html_path = os.path.join(out_dir, f'best_five_contender_{ts}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_report)

        print("\n" + report)
        log(f"Report salvato in: {out_path}")
        log(f"Report HTML salvato in: {html_path}")
        return

    # Modalita' a matrice (30/07, parallelizzazione stile formazione_giornata.yml):
    # tre job separati invece di un unico loop sequenziale -- vedi
    # .github/workflows/best_five.yml. Queste due modalita' fanno UNA cosa
    # sola e ritornano subito, non condividono il resto di main() (che serve
    # invece al job 'report', identico a prima: legge i file gia' su disco e
    # costruisce il ranking, senza bisogno di flag nuovi).
    ruoli_tutti = ('gk', 'def', 'mid', 'fwd')

    def _ruoli_da_args():
        ruoli = ruoli_tutti
        if '--roles' in args:
            idx = args.index('--roles')
            richiesti = [r.strip() for r in args[idx + 1].split(',') if r.strip()]
            ruoli = tuple(r for r in richiesti if r in ruoli_tutti) or ruoli_tutti
        return ruoli

    def _n_bin_da_args():
        n_bin = SLOT_CONCORRENTI
        if '--n-bin' in args:
            idx = args.index('--n-bin')
            n_bin = int(args[idx + 1])
        return n_bin

    if '--matrice' in args:
        cmd_matrice(lega, _ruoli_da_args(), _n_bin_da_args())
        return

    # --matrice-pool / --prefiltra-shard / --merge-prefiltro (30/07,
    # parallelizzazione del prefiltro: richiesta esplicita utente dopo aver
    # visto che il prefiltro sequenziale (--matrice, sopra) restava
    # comunque 5-6 minuti su ~280 candidati K League -- il collo di
    # bottiglia non era il predict ma le query starterOdds una per una.
    # Sostituisce --matrice nel workflow con 3 step: shard del pool (qui),
    # controllo starterOdds in parallelo (job a matrice), poi merge +
    # shard dei sopravvissuti per il predict (identico a prima da qui in poi).
    if '--matrice-pool' in args:
        cmd_matrice_pool(lega, _ruoli_da_args(), _n_bin_da_args())
        return

    if '--prefiltra-shard' in args:
        idx = args.index('--prefiltra-shard')
        payload = args[idx + 1]
        idx_out = args.index('--out')
        out_path = args[idx_out + 1]
        cmd_prefiltra_shard(lega, payload, out_path)
        return

    if '--merge-prefiltro' in args:
        idx = args.index('--merge-prefiltro')
        artifacts_dir = args[idx + 1]
        cmd_merge_prefiltro(artifacts_dir, _n_bin_da_args())
        return

    if '--predict-shard' in args:
        idx = args.index('--predict-shard')
        cmd_predict_shard(lega, args[idx + 1])
        return

    esegui = '--run' in args
    n_backup = 2
    if '--backups' in args:
        idx = args.index('--backups')
        n_backup = int(args[idx + 1])

    if lega not in LEGHE_SUPPORTATE:
        log(f"ATTENZIONE: '{lega}' non e' tra le leghe con discovery globale completa nota "
            f"({', '.join(LEGHE_SUPPORTATE)}) — procedo comunque, ma potrebbe mancare il pool.")

    ruoli = ('gk', 'def', 'mid', 'fwd')

    # --roles (30/07, ripresa run parziale): permette di rilanciare --run SOLO
    # sui ruoli mancanti (es. dopo che una sessione precedente ha gia'
    # completato e committato gk/def) invece di rifare tutto da capo. Il
    # ranking finale (costruisci_best_five sotto) resta invece SEMPRE su
    # tutti e 4 i ruoli, leggendo l'ultimo output disponibile per ciascuno
    # (formato pool intero O per-slug, vedi costruisci_best_five) -- quindi
    # funziona anche a run misti (alcuni ruoli generati in una sessione
    # precedente, altri in questa).
    ruoli_da_eseguire = ruoli
    if '--roles' in args:
        idx = args.index('--roles')
        richiesti = [r.strip() for r in args[idx + 1].split(',') if r.strip()]
        non_validi = [r for r in richiesti if r not in ruoli]
        if non_validi:
            log(f"ATTENZIONE: ruoli non validi ignorati: {non_validi} (validi: {ruoli})")
        ruoli_da_eseguire = tuple(r for r in richiesti if r in ruoli) or ruoli

    if esegui:
        for ruolo in ruoli_da_eseguire:
            run_prediction_pool_prefiltrato(lega, ruolo)

    # Formazione VERA (30/07, richiesta esplicita utente: sinergie/anti-stack/
    # captain come il tool unificato, non un elenco top-N per ruolo) --
    # sostituisce costruisci_best_five/formatta_report* come output
    # principale. count = 1 (titolare) + n_backup (formazioni alternative
    # complete, vedi costruisci_formazione_vera).
    bff, generated, totale, lineup_blocks, lineup_html_blocks, prezzi, eta_map = costruisci_formazione_vera(
        lega, 1 + n_backup)

    out_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five')
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')

    report = (
        "=" * 70 + "\n"
        f"BEST FIVE — {lega.upper()} (formazione IN SEASON, pool globale)\n"
        f"Generato: {datetime.datetime.utcnow().isoformat()}Z\n"
        f"{generated} formazione/i generata/e su {1 + n_backup} richieste, "
        f"totale complessivo {totale} pt attesi.\n"
        "Pool: TUTTI i giocatori della lega (discovery globale), non solo posseduti. "
        "Sinergie/anti-stack/captain calcolati come nel tool unificato.\n"
        + "=" * 70 + "\n\n"
        + "\n\n".join(lineup_blocks)
    )
    out_path = os.path.join(out_dir, f'best_five_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    page_title = f"Best Five — {lega.upper()}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"{generated}/{1 + n_backup} formazioni, pool TUTTI i giocatori della lega "
                     f"(discovery globale, non solo posseduti). Sinergie/anti-stack/captain "
                     f"come nel tool unificato.")
    footer = "Script separato e READ-ONLY rispetto alla pipeline di produzione."
    html_report = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer)
    html_report = rendi_carte_cliccabili(html_report)
    html_report = _annota_prezzi_html(html_report, prezzi)
    html_report = _annota_eta_html(html_report, eta_map)
    html_report = applica_restyling(html_report)
    html_path = os.path.join(out_dir, f'best_five_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_report)

    print("\n" + report)
    log(f"Report salvato in: {out_path}")
    log(f"Report HTML salvato in: {html_path}")


if __name__ == '__main__':
    main()
