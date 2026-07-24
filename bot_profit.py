"""
Bot Profit -- listener di mercato Sorare (stesso modello di Bot Supremo) che NON
punta ne' offre: si limita a tracciare, per ogni carta incontrata (limited, in
season + classic), i dati necessari a stimare il "potenziale di crescita di
valore" verso la prossima partita del giocatore.

Per ogni carta valida (esclude solo: coverageStatus=NOT_COVERED e forma-zero,
cioe' media punti 0 nelle ultime 10 e/o nelle ultime 40 giocate) registra:
  - L5 / L10 / L40 (medie voto SO5)
  - media transazioni ultime 30 (esclusi il valore piu' basso e piu' alto, per
    evitare distorsioni da outlier)
  - minimo attuale in vendita (stessa separazione season/classic di Bot Supremo:
    MLS/K-League confrontano solo la stagione giusta, altri campionati misti)
  - sconto% = (media_transazioni_30gg_trimmed - minimo_attuale) / media_transazioni_30gg_trimmed
  - data/ore alla prossima partita

Nessuna decisione di acquisto/offerta. Nessuna blacklist. Output: un CSV in
bot_profit/, riscritto ad ogni commit periodico (default 2 minuti) con TUTTE
le carte tracciate dall'inizio della run, ordinate per sconto% decrescente --
cosi' interrompendo manualmente il workflow in qualsiasi momento il file
contiene gia' l'intero tracciato fino a quel punto.
"""
import csv
import datetime
import json
import os
import subprocess
import threading
import time
import concurrent.futures

import requests
import websocket  # pip install websocket-client

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()

# =====================================================================================
# CONFIG / CREDENZIALI -- stesse variabili d'ambiente di Bot Supremo
# =====================================================================================
COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessi 2 campionati esclusi dal confronto season+classic misto (MLS, K-League),
# identico a Bot Supremo -- J League ESCLUSA da questo filtro (logica normale).
EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1'}

CHECK_CLASSIC = os.environ.get('CHECK_CLASSIC', 'si').strip().lower() in ('1', 'true', 'yes', 'si')

# Nessun valore di default: la durata dell'ascolto va sempre specificata a mano
# per questo bot di test (richiesta esplicita utente).
LISTEN_SECONDS = int(os.environ['LISTEN_SECONDS'])

# Commit periodico dei dati tracciati -- default 2 minuti (richiesta esplicita utente),
# diverso dal default 5 minuti di Bot Supremo.
COMMIT_CHUNK_SECONDS = int(os.environ.get('COMMIT_CHUNK_SECONDS', '120'))

TRANSACTIONS_SAMPLE_SIZE = int(os.environ.get('TRANSACTIONS_SAMPLE_SIZE', '30'))

OUTPUT_DIR = 'bot_profit'
OUTPUT_CSV_PATH = os.path.join(OUTPUT_DIR, 'profit_tracking.csv')

EVENT_WORKER_THREADS = int(os.environ.get('EVENT_WORKER_THREADS', '4'))


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [bot_profit] {message}", flush=True)


# =====================================================================================
# UTILITY DI RETE -- identiche a Bot Supremo (prezzo multi-valuta, tasso ETH, GraphQL)
# =====================================================================================
_FIAT_RATE_CACHE = {}


def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def get_usd_eur_rate():
    if 'usd' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['usd']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 0.92
    _FIAT_RATE_CACHE['usd'] = rate
    return rate


def get_gbp_eur_rate():
    if 'gbp' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['gbp']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=GBP&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 1.17
    _FIAT_RATE_CACHE['gbp'] = rate
    return rate


def get_sol_eur_rate():
    if 'sol' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['sol']
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur",
            timeout=5
        )
        rate = float(r.json()['solana']['eur'])
    except Exception:
        rate = 150.0
    _FIAT_RATE_CACHE['sol'] = rate
    return rate


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            return None
    if amounts.get('usdCents') is not None:
        try:
            return amounts['usdCents'] / 100 * get_usd_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('gbpCents') is not None:
        try:
            return amounts['gbpCents'] / 100 * get_gbp_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('lamport') is not None:
        try:
            return float(amounts['lamport']) / 1e9 * get_sol_eur_rate()
        except (TypeError, ValueError):
            return None
    return None


GRAPHQL_MIN_INTERVAL_SECONDS_FAST = 0.05
GRAPHQL_MIN_INTERVAL_SECONDS_SAFE = 0.35
GRAPHQL_429_COOLDOWN_SECONDS = 30.0
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]
_graphql_last_429_ts = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        recent_429 = (now - _graphql_last_429_ts[0]) < GRAPHQL_429_COOLDOWN_SECONDS
        min_interval = GRAPHQL_MIN_INTERVAL_SECONDS_SAFE if recent_429 else GRAPHQL_MIN_INTERVAL_SECONDS_FAST
        wait = min_interval - (now - _graphql_last_call_ts[0])
        if wait > 0:
            time.sleep(wait)
        _graphql_last_call_ts[0] = time.time()


def graphql_query(query, variables=None, max_retries=3):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get(
            'SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if SORARE_DEVICE_FINGERPRINT:
        headers['device_fingerprint'] = SORARE_DEVICE_FINGERPRINT
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        _graphql_throttle()
        r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            _graphql_last_429_ts[0] = time.time()
            wait_seconds = min((2 ** attempt) * 2, 8.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


def is_excluded_league(league_slug):
    return league_slug in EXCLUDED_LEAGUE_SLUGS


# =====================================================================================
# QUERY: annunci live del giocatore -- per il MINIMO attuale (identica a Bot Supremo)
# =====================================================================================
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            inSeasonEligible
          }
        }
      }
    }
  }
}
"""

LIVE_OFFERS_PAGE_SIZE = 50
LIVE_OFFERS_MAX_PAGES = 2


def fetch_all_live_offers(player_slug):
    all_nodes = []
    cursor = None
    for _ in range(LIVE_OFFERS_MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": LIVE_OFFERS_PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[minimo attuale] errore paginazione per {player_slug}: {data['errors']}")
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes


def get_current_minimum(player_slug, is_in_season, league_slug, eth_rate):
    """Minimo attuale in vendita, stessa separazione season/classic di Bot Supremo:
    MLS/K-League confrontano solo la stagione giusta, altri campionati mescolano
    in_season+classic."""
    nodes = fetch_all_live_offers(player_slug)
    excluded = is_excluded_league(league_slug)
    prices_in_season = []
    prices_classic = []
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited' or c.get('sport') != 'FOOTBALL':
                continue
            match = c
            break
        if not match:
            continue
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            continue
        if match.get('inSeasonEligible'):
            prices_in_season.append(price)
        else:
            prices_classic.append(price)
    if excluded:
        candidates = prices_in_season if is_in_season else []
    else:
        candidates = prices_in_season + prices_classic
    return min(candidates) if candidates else None


# =====================================================================================
# QUERY COMBINATA: medie voto (L5/L10/L40), prossima partita, ultime N transazioni
# =====================================================================================
PROFIT_PLAYER_DATA_QUERY = """
query ProfitPlayerData($slug: String!, $n: Int!) {
  anyPlayer(slug: $slug) {
    slug
    displayName
    lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
    lastTenAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
    anyFutureGames(first: 1) {
      nodes {
        date
      }
    }
    tokenPrices(rarity: limited, last: $n) {
      nodes {
        date
        deal { __typename ... on TokenOffer { type } }
        card { inSeasonEligible }
        amounts { eurCents wei usdCents gbpCents lamport }
      }
    }
  }
}
"""


def _is_countable_transaction(node):
    deal = node.get('deal') or {}
    return bool(deal.get('type')) or deal.get('__typename') in ('TokenAuction', 'TokenPrimaryOffer')


def get_player_snapshot(player_slug, is_in_season, league_slug, eth_rate):
    """Un'unica chiamata: medie voto, prossima partita, ultime N transazioni (per la
    media trimmed). Ritorna None se la query fallisce."""
    data = graphql_query(PROFIT_PLAYER_DATA_QUERY, {"slug": player_slug, "n": TRANSACTIONS_SAMPLE_SIZE})
    if data.get('errors'):
        log(f"[snapshot] errore GraphQL per {player_slug}: {data['errors']}")
        return None
    player = ((data.get('data') or {}).get('anyPlayer')) or {}
    if not player:
        return None

    l5 = player.get('lastFiveAvgScore')
    l10 = player.get('lastTenAvgScore')
    l40 = player.get('lastFortyAvgScore')

    future_nodes = ((player.get('anyFutureGames') or {}).get('nodes')) or []
    next_game_date_str = future_nodes[0].get('date') if future_nodes else None

    excluded = is_excluded_league(league_slug)
    tx_nodes = ((player.get('tokenPrices') or {}).get('nodes')) or []
    tx_prices = []
    for node in tx_nodes:
        if excluded:
            card = node.get('card') or {}
            if bool(card.get('inSeasonEligible')) != is_in_season:
                continue
        if not _is_countable_transaction(node):
            continue
        price = eur_price_from_amounts(node.get('amounts'), eth_rate)
        if price is not None:
            tx_prices.append(price)

    return {
        'l5': l5,
        'l10': l10,
        'l40': l40,
        'next_game_date_str': next_game_date_str,
        'tx_prices': tx_prices,
    }


def trimmed_average(prices):
    """Media delle transazioni escludendo il valore piu' basso e piu' alto (protezione
    da outlier). Se ci sono meno di 3 valori, niente trim (non abbastanza dati),
    media semplice su quello che c'e'. Ritorna (media, n_usati_dopo_trim, n_totali)."""
    n_totali = len(prices)
    if n_totali == 0:
        return None, 0, 0
    if n_totali < 3:
        return sum(prices) / n_totali, n_totali, n_totali
    ordered = sorted(prices)
    trimmed = ordered[1:-1]
    return sum(trimmed) / len(trimmed), len(trimmed), n_totali


def hours_until(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = dt - now
    return delta.total_seconds() / 3600.0


# =====================================================================================
# STATO CONDIVISO (thread-safe) -- una riga per giocatore, sempre l'ultimo snapshot
# =====================================================================================
_tracked_lock = threading.Lock()
_tracked = {}  # player_slug -> dict di riga CSV


def _upsert_tracked_row(player_slug, player_name, row):
    with _tracked_lock:
        _tracked[player_slug] = row


CSV_FIELDNAMES = [
    'player_slug', 'player_name', 'l5', 'l10', 'l40',
    'min_attuale_eur', 'media_transazioni_30gg_trimmed_eur', 'n_transazioni_usate',
    'sconto_percent', 'prossima_partita_data', 'ore_alla_partita',
]


def write_csv_snapshot():
    """Riscrive il CSV completo con tutte le carte tracciate finora, ordinate per
    sconto% decrescente (carta piu' sottostimata in cima)."""
    with _tracked_lock:
        rows = list(_tracked.values())
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    rows_sorted = sorted(
        rows,
        key=lambda r: (r['sconto_percent'] if r['sconto_percent'] is not None else -999999),
        reverse=True,
    )
    with open(OUTPUT_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in rows_sorted:
            writer.writerow(r)
    log(f"[csv] scritto {len(rows_sorted)} carte tracciate in {OUTPUT_CSV_PATH}")


# =====================================================================================
# COMMIT PERIODICO (default 2 minuti) -- stesso pattern di Bot Supremo
# =====================================================================================
_stop_periodic_commit = threading.Event()


def _commit_output_se_serve():
    try:
        write_csv_snapshot()
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--', OUTPUT_CSV_PATH],
            capture_output=True, text=True, timeout=30
        )
        if not status.stdout.strip():
            return
        subprocess.run(['git', 'config', 'user.name', 'bot-profit'], timeout=30)
        subprocess.run(['git', 'config', 'user.email',
                         'bot-profit@users.noreply.github.com'], timeout=30)
        subprocess.run(['git', 'add', OUTPUT_CSV_PATH], timeout=30)
        commit = subprocess.run(
            ['git', 'commit', '-m', 'Bot Profit: commit periodico dati tracciati (run in corso)'],
            capture_output=True, text=True, timeout=30
        )
        if commit.returncode != 0:
            log(f"[commit periodico] nulla da committare o commit fallito: "
                f"{commit.stdout.strip()} {commit.stderr.strip()}")
            return
        pull = subprocess.run(
            ['git', 'pull', '--rebase', '--autostash', 'origin', 'main'],
            capture_output=True, text=True, timeout=60
        )
        if pull.returncode != 0:
            log(f"[commit periodico] git pull --rebase fallito, salto il push di questo giro: {pull.stderr.strip()}")
            return
        push = subprocess.run(['git', 'push'], capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            log("[commit periodico] dati tracciati committati e pushati con successo (run ancora in corso)")
        else:
            log(f"[commit periodico] push fallito: {push.stderr.strip()}")
    except Exception as e:
        log(f"[commit periodico] eccezione non bloccante, ritento al prossimo giro: {e}")


def _periodic_commit_loop():
    while not _stop_periodic_commit.wait(COMMIT_CHUNK_SECONDS):
        _commit_output_se_serve()


# =====================================================================================
# LISTENER WEBSOCKET -- stesso canale di Bot Supremo, ma nessuna decisione di
# acquisto/offerta: solo tracciamento.
# =====================================================================================
SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    senderSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards {
        slug
        rarityTyped
        sport
        inSeasonEligible
        ... on Card {
          coverageStatus
        }
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards { slug }
    }
  }
}
"""


def _process_one_card_event(player_slug, player_name, league_slug, is_in_season, eth_rate, stats, stats_lock):
    try:
        snapshot = get_player_snapshot(player_slug, is_in_season, league_slug, eth_rate)
        if snapshot is None:
            return

        l5, l10, l40 = snapshot['l5'], snapshot['l10'], snapshot['l40']
        if l10 == 0.0 or l40 == 0.0:
            with stats_lock:
                stats['skipped_forma_zero'] += 1
            return  # "carta a forma 0" -- esclusa su richiesta esplicita

        min_attuale = get_current_minimum(player_slug, is_in_season, league_slug, eth_rate)
        avg_trimmed, n_usati, n_totali = trimmed_average(snapshot['tx_prices'])

        sconto_percent = None
        if avg_trimmed and avg_trimmed > 0 and min_attuale is not None:
            sconto_percent = round((avg_trimmed - min_attuale) / avg_trimmed * 100, 2)

        ore_alla_partita = hours_until(snapshot['next_game_date_str'])

        row = {
            'player_slug': player_slug,
            'player_name': player_name,
            'l5': l5,
            'l10': l10,
            'l40': l40,
            'min_attuale_eur': round(min_attuale, 2) if min_attuale is not None else None,
            'media_transazioni_30gg_trimmed_eur': round(avg_trimmed, 2) if avg_trimmed is not None else None,
            'n_transazioni_usate': f"{n_usati}/{n_totali}",
            'sconto_percent': sconto_percent,
            'prossima_partita_data': snapshot['next_game_date_str'],
            'ore_alla_partita': round(ore_alla_partita, 1) if ore_alla_partita is not None else None,
        }
        _upsert_tracked_row(player_slug, player_name, row)

        with stats_lock:
            stats['tracked'] += 1
            tracked_count = stats['tracked']
        log(f"[tracciata] {player_name} ({player_slug}): L5={l5} L10={l10} L40={l40} "
            f"min={row['min_attuale_eur']}EUR media30gg_trim={row['media_transazioni_30gg_trimmed_eur']}EUR "
            f"sconto={sconto_percent}% prossima_partita={snapshot['next_game_date_str']} "
            f"({row['ore_alla_partita']}h) -- totale tracciate finora: {tracked_count}")
    except Exception as e:
        log(f"[ERRORE in valutazione evento] {player_name}: eccezione non gestita, la salto: {e}")


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "tracked": 0, "skipped_forma_zero": 0, "skipped_coverage": 0}
    stats_lock = threading.Lock()
    seen_offer_status = set()
    event_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=EVENT_WORKER_THREADS, thread_name_prefix='evt')

    def on_open(ws):
        log("Connesso al canale eventi Sorare, sottoscrizione in corso...")
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({
            "command": "message",
            "identifier": identifier,
            "data": json.dumps(subscription_payload),
        }))

    def on_message(ws, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        msg_type = message.get('type')
        if msg_type in ('welcome', 'ping'):
            return
        if msg_type == 'confirm_subscription':
            log("Sottoscrizione confermata, in ascolto...")
            return
        if msg_type == 'reject_subscription':
            log(f"ERRORE: sottoscrizione rifiutata: {message}")
            return

        payload = message.get('message')
        if not payload:
            return
        if payload.get('errors'):
            log(f"ERRORE GraphQL nella subscription: {payload['errors']}")
            return

        try:
            stats["received"] += 1
            offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
            if not offer:
                return

            offer_id = offer.get('id') or ''
            if not offer_id.startswith('SingleSaleOffer:'):
                return

            offer_status = offer.get('status')
            dedup_key = (offer_id, offer_status)
            if dedup_key in seen_offer_status:
                return
            seen_offer_status.add(dedup_key)

            if offer_status != 'opened':
                return

            sender_side = offer.get('senderSide') or {}
            receiver_side = offer.get('receiverSide') or {}
            if receiver_side.get('anyCards'):
                return  # scambio carta-per-carta

            sender_cards = sender_side.get('anyCards') or []
            if len(sender_cards) > 1:
                return  # bundle multi-carta

            for card in sender_cards:
                if card.get('rarityTyped') != 'limited':
                    continue
                if card.get('sport') != 'FOOTBALL':
                    continue
                if card.get('coverageStatus') == 'NOT_COVERED':
                    with stats_lock:
                        stats['skipped_coverage'] += 1
                    continue  # "carta non coperta da Sorare" -- esclusa su richiesta esplicita

                player = card.get('anyPlayer') or {}
                player_slug = player.get('slug')
                player_name = player.get('displayName', player_slug)
                if not player_slug:
                    continue

                is_in_season = bool(card.get('inSeasonEligible'))
                if not is_in_season and not CHECK_CLASSIC:
                    continue
                league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')

                stats["processed"] += 1
                event_executor.submit(_process_one_card_event, player_slug, player_name,
                                       league_slug, is_in_season, eth_rate, stats, stats_lock)
        except Exception as e:
            log(f"[ERRORE in on_message] eccezione non gestita, la salto e continuo ad ascoltare: {e}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: {stats['received']}, "
            f"carte elaborate: {stats['processed']}, tracciate: {stats['tracked']}, "
            f"scartate per forma zero: {stats['skipped_forma_zero']}, "
            f"scartate per non-copertura: {stats['skipped_coverage']}")

    ws = websocket.WebSocketApp(
        WS_URL,
        header=[f"Cookie: {COOKIES}"] if COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    timer = threading.Timer(LISTEN_SECONDS, ws.close)
    timer.daemon = True
    timer.start()

    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()
    event_executor.shutdown(wait=True)

    return stats


def main():
    log(f"Avvio Bot Profit. LISTEN_SECONDS={LISTEN_SECONDS} COMMIT_CHUNK_SECONDS={COMMIT_CHUNK_SECONDS} "
        f"CHECK_CLASSIC={CHECK_CLASSIC} TRANSACTIONS_SAMPLE_SIZE={TRANSACTIONS_SAMPLE_SIZE}")

    if not COOKIES or not CSRF_TOKEN:
        log("ERRORE: SORARE_COOKIE/SORARE_CSRF mancanti, impossibile continuare.")
        return

    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")

    commit_thread = threading.Thread(target=_periodic_commit_loop, daemon=True)
    commit_thread.start()
    log(f"Thread di commit periodico avviato (ogni {COMMIT_CHUNK_SECONDS}s se ci sono modifiche)")

    stats = run_listener(eth_rate)

    _stop_periodic_commit.set()
    commit_thread.join(timeout=10)

    # Scrittura/commit finale, per non perdere l'ultimo pezzo tra l'ultimo commit
    # periodico e la chiusura del listener.
    _commit_output_se_serve()

    log(f"Bot Profit terminato. Riepilogo: {stats}")


if __name__ == '__main__':
    main()
