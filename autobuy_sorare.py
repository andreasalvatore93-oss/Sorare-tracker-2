import json
import os
import time
import datetime
import threading

import requests
import websocket  # pip install websocket-client

# =====================================================================================
# AUTOBUY SORARE -- FASE 1 (SOLO DIAGNOSTICA, NESSUN ACQUISTO REALE)
# =====================================================================================
# Script SEPARATO da track.py, con workflow GitHub Actions dedicato (autobuy.yml), per non
# creare confusione tra i due bot.
#
# Obiettivo finale (fase 2, non ancora implementata): comprare in automatico SOLO carte In
# Season in una fascia di prezzo stretta, quando il margine sul secondo prezzo attuale e'
# abbastanza ampio da essere "senza dubbio" un affare -- a differenza di track.py, qui NON
# guardiamo affatto il floor storico, il calo % nel tempo, le vendite recenti ne' il
# "mercato sottile": l'unico confronto e' istantaneo, tra il prezzo minimo attuale e il
# secondo prezzo minimo attuale, entrambi sullo stesso bucket in_season.
#
# FASE 1 (questa versione): il bot NON compra nulla. Quando troverebbe un caso che
# rispetta tutti i criteri, manda una notifica Telegram che dice "lo avrei acquistato",
# cosi' l'utente puo' controllare a mano se il bot ha ragione prima di passare
# all'acquisto reale automatizzato (fase 2, richiede la firma Starkware delle mutation
# GraphQL di acquisto -- vedi note a parte, non ancora implementato).
#
# Esecuzione: SEMPRE manuale (workflow_dispatch), non su un cron continuo come track.py.
# Il bot ascolta finche' non trova il PRIMO caso che avrebbe acquistato, manda la notifica
# e si ferma (si riavvia a mano). Se scade il tempo di ascolto senza nessun caso valido,
# si ferma comunque e basta.
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessa blacklist manager di track.py (venditori solo ETH o esplicitamente esclusi
# dall'utente) -- non ha senso valutare/comprare da questi annunci.
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}

# --- Parametri regolabili (fase di test, vedi autobuy.yml per gli input del workflow) ---
# Fascia di prezzo dell'ANNUNCIO che scatena la valutazione: default 1-5EUR, ma regolabile
# fino a un tetto piu' alto (es. 20EUR) durante i test.
AUTOBUY_MIN_PRICE_EUR = float(os.environ.get('AUTOBUY_MIN_PRICE_EUR', '1'))
AUTOBUY_MAX_PRICE_EUR = float(os.environ.get('AUTOBUY_MAX_PRICE_EUR', '5'))

# Margine minimo richiesto tra il prezzo minimo attuale e il secondo prezzo minimo attuale
# (stesso bucket in_season), es. 0.15 = 15%.
AUTOBUY_MARGIN_FRACTION = float(os.environ.get('AUTOBUY_MARGIN_FRACTION', '0.15'))

# Per quanti secondi restare in ascolto ad ogni esecuzione, se non si verifica prima un caso
# valido (il bot si ferma comunque al primo caso trovato).
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '250'))

_FIAT_RATE_CACHE = {}


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


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
    """Identica alla versione in track.py: legge il prezzo di un annuncio in qualunque
    valuta Sorare accetti (EUR/ETH/USD/GBP/SOL) e lo converte sempre in EUR."""
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


GRAPHQL_MIN_INTERVAL_SECONDS = 0.35
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        wait = GRAPHQL_MIN_INTERVAL_SECONDS - (now - _graphql_last_call_ts[0])
        if wait > 0:
            time.sleep(wait)
        _graphql_last_call_ts[0] = time.time()


def graphql_query(query, variables=None, max_retries=3):
    """Versione semplificata (stessa base di track.py) del client GraphQL con backoff sui
    429 -- niente rilevamento "ban a tempo fisso" qui, il volume di query di questo bot e'
    molto piu' basso (esecuzioni brevi, manuali)."""
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        _graphql_throttle()
        r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            wait_seconds = min((2 ** attempt) * 2, 8.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        sender { ... on User { slug } }
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            sportSeason { name }
            inSeasonEligible
          }
        }
      }
    }
  }
}
"""

PAGE_SIZE = 50
MAX_PAGES = 20


def fetch_all_live_offers(player_slug):
    """Identica alla versione in track.py: pagina TUTTI gli annunci live di un giocatore
    (il server tronca a ~50 per richiesta), escludendo i venditori blacklistati."""
    all_nodes = []
    cursor = None
    for _ in range(MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[paginazione annunci live] errore per {player_slug}: {data['errors']}")
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
        nodes = conn.get('nodes') or []
        for node in nodes:
            seller_slug = ((node.get('sender') or {}).get('slug') or '').lower()
            if seller_slug in BLACKLISTED_SELLER_SLUGS:
                continue
            all_nodes.append(node)
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes


def get_in_season_prices(player_slug, eth_rate):
    """A differenza di get_bucket_prices in track.py (che restituisce ENTRAMBI i bucket
    in_season/classic), qui ci interessa SOLO in_season -- l'AutoBuy ignora le carte
    Classic per criterio esplicito dell'utente. Restituisce una lista (prezzo, card_slug)
    ordinata crescente, oppure lista vuota se non ci sono annunci validi."""
    nodes = fetch_all_live_offers(player_slug)
    prices = []
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta, non una vendita in denaro
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited':
                continue
            if c.get('sport') != 'FOOTBALL':
                continue
            if not c.get('inSeasonEligible'):
                continue  # SOLO in season, criterio esplicito AutoBuy
            match = c
            break
        if not match:
            continue
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            continue
        prices.append((price, match.get('slug')))
    prices.sort(key=lambda p: p[0])
    return prices


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log(f"Errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


def build_card_link(player_slug, card_slug):
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    return f"{base_link}?card={card_slug}" if card_slug else base_link


def send_would_have_bought_alert(player_name, player_slug, price_eur, second_price, margin_percent, card_slug):
    link = build_card_link(player_slug, card_slug)
    msg_text = (
        f"\U0001F916\U0001F4B0 <b>AutoBuy Sorare -- LO AVREI ACQUISTATO</b>\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: In Season\n"
        f"Prezzo minimo attuale: {price_eur:.2f}EUR\n"
        f"Secondo prezzo attuale: {second_price:.2f}EUR (margine {margin_percent:.1%}, "
        f"soglia richiesta {AUTOBUY_MARGIN_FRACTION:.0%})\n\n"
        f"\u26A0\uFE0F Fase di test: nessun acquisto reale eseguito, controlla a mano.\n\n"
        f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
    )
    send_telegram_msg(msg_text)


def send_startup_msg():
    send_telegram_msg(
        f"\U0001F916 <b>AutoBuy Sorare avviato</b> (solo diagnostica, nessun acquisto reale)\n"
        f"Fascia prezzo: {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR\n"
        f"Margine richiesto: {AUTOBUY_MARGIN_FRACTION:.0%}\n"
        f"Ascolto per {LISTEN_SECONDS}s o fino al primo caso valido."
    )


def evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate):
    """Ritorna True se questo evento ha portato a un caso valido (avrebbe acquistato),
    False altrimenti -- usato dal listener per decidere se fermarsi."""
    if not (AUTOBUY_MIN_PRICE_EUR <= price_eur <= AUTOBUY_MAX_PRICE_EUR):
        return False

    prices = get_in_season_prices(player_slug, eth_rate)
    if not prices:
        return False

    true_min_price, true_min_card_slug = prices[0]

    # Il prezzo dell'evento potrebbe non essere il minimo reale attuale (altri annunci gia'
    # piu' economici sullo stesso giocatore) -- criterio esplicito: valutiamo solo se la
    # carta appena spuntata E' il minimo attuale sul mercato in_season.
    if true_min_card_slug != card_slug:
        log(f"{player_name}: scarto -- annuncio a {price_eur:.2f}EUR non e' il minimo attuale "
            f"in_season (minimo vero: {true_min_price:.2f}EUR)")
        return False

    if len(prices) < 2:
        log(f"{player_name}: scarto -- nessun secondo annuncio in_season per confrontare il margine")
        return False

    second_min_price, _ = prices[1]
    if second_min_price <= 0:
        return False

    margin_percent = (second_min_price - true_min_price) / second_min_price
    log(f"{player_name}: minimo {true_min_price:.2f}EUR, secondo {second_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%} (soglia {AUTOBUY_MARGIN_FRACTION:.0%})")

    if margin_percent < AUTOBUY_MARGIN_FRACTION:
        return False

    log(f"AUTOBUY: {player_name} -- LO AVREI ACQUISTATO ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%})")
    send_would_have_bought_alert(player_name, player_slug, true_min_price, second_min_price,
                                  margin_percent, card_slug)
    return True


SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    sender { ... on User { slug } }
    senderSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards {
        slug
        rarityTyped
        sport
        anyPlayer { slug displayName }
        sportSeason { name }
        inSeasonEligible
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards { slug }
    }
  }
}
"""


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "found_match": False}
    seen_offer_status = set()

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

        seller_slug = ((offer.get('sender') or {}).get('slug') or '').lower()
        if seller_slug in BLACKLISTED_SELLER_SLUGS:
            return

        sender_side = offer.get('senderSide') or {}
        receiver_side = offer.get('receiverSide') or {}
        if receiver_side.get('anyCards'):
            return  # scambio carta-per-carta

        price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
        if price_eur is None:
            return

        sender_cards = sender_side.get('anyCards') or []
        if len(sender_cards) > 1:
            return  # bundle multi-carta, prezzo per-carta non ricavabile

        for card in sender_cards:
            if card.get('rarityTyped') != 'limited':
                continue
            if card.get('sport') != 'FOOTBALL':
                continue
            if not card.get('inSeasonEligible'):
                continue  # SOLO in season

            player = card.get('anyPlayer') or {}
            player_slug = player.get('slug')
            player_name = player.get('displayName', player_slug)
            card_slug = card.get('slug')
            if not player_slug:
                continue

            stats["processed"] += 1
            found = evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate)
            if found:
                stats["found_match"] = True
                ws.close()

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: "
            f"{stats['received']}, carte in season elaborate: {stats['processed']}, "
            f"caso valido trovato: {stats['found_match']}")

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

    return stats["found_match"]


def main():
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    log(f"AutoBuy Sorare (fase 1, solo diagnostica) -- fascia prezzo "
        f"{AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR, "
        f"margine richiesto {AUTOBUY_MARGIN_FRACTION:.0%}")
    send_startup_msg()
    found = run_listener(eth_rate)
    if found:
        log("Caso valido trovato e notificato -- esecuzione terminata.")
    else:
        log("Nessun caso valido trovato entro il tempo di ascolto -- esecuzione terminata.")


if __name__ == "__main__":
    main()
