"""Tracker live "modello ZenLock" -- backlog #8/#11, richiesta esplicita dell'utente 17/07 dopo
l'analisi comportamentale (report_mode: trades/margin_model su fetch_user_trades). Ascolta lo
stesso stream di eventi Sorare del tracker principale (tokenOfferWasUpdated) ma valuta ogni
annuncio con SOGLIE DIVERSE, calibrate sul comportamento empirico di ZenLock invece che sul
nostro modello (MARGIN_TIERS in track.py):

- soglia di prezzo per fascia/stagione (in_season vs classic), presa dalla distribuzione reale
  dei suoi snipe puri (SINGLE_SALE_OFFER) su piu' finestre (7/10/14 giorni, vedi
  diagnostic_manager_trades_report): classic quasi sempre <=4EUR (57% sotto i 3EUR), in_season
  quasi sempre <=8EUR, con rare eccezioni su carte "big name" (Messi 65.71EUR, Kvaratskhelia
  21.96EUR) trattate come fascia a parte con soglia di sconto piu' severa.
- sconto vs un riferimento di mercato LIVE (mediana degli altri annunci aperti dello stesso
  giocatore/bucket in questo momento, via track.get_bucket_prices -- stessa fonte dati gia'
  usata e testata dal tracker principale per il proprio "secondo prezzo", quindi a costo zero
  in termini di rischio). NON usiamo lo storico vendite (fetch_player_recent_direct_buys) qui:
  e' pensato per un report offline, troppo pesante/lento per essere richiamato ad ogni singolo
  evento WS in tempo reale.

  IMPORTANTE (onesto sui limiti del modello): nel run di margin_model su 14gg, l'86% degli
  snipe REALI di ZenLock non aveva NESSUN comparabile di mercato disponibile -- prende carte
  cosi' di nicchia che a conti fatti compra "al buio" sul prezzo assoluto, non su uno sconto
  calcolato. Se replicassimo questo alla lettera (notificare ogni carta sotto soglia di prezzo
  anche senza sconto verificabile) il tracker sarebbe inondato di falsi positivi: praticamente
  ogni carta comune scarsa sotto i 3-4EUR passerebbe il filtro, senza nessun vero segnale di
  mispricing. Scelta esplicita: qui notifichiamo SOLO quando esiste un confronto di mercato
  verificabile E lo sconto supera la soglia -- sacrifichiamo l'86% "al buio" (non replicabile
  in modo sensato) per tenere il tracker utile sul 14% che invece mostra un vero pattern
  (sconto medio ~40%, mediana ~41%, osservato su 10 casi comparabili nella stessa finestra).

Deliberatamente NON importa/richiama run_listener/handle_offer_update/evaluate_player_offer di
track.py (userebbero MARGIN_TIERS e MIN_PRICE_EUR del bot principale, pensati per un modello
diverso -- es. MIN_PRICE_EUR=2.0EUR avrebbe scartato meta' degli snipe reali di ZenLock, che
comprano spesso sotto 1EUR). Riusa solo le funzioni di basso livello gia' testate (connessione
WS, query prezzi live, invio Telegram) per non duplicare logica fragile, ma la valutazione e il
loop eventi sono un percorso completamente separato: workflow GitHub Actions dedicato
(zenlock_model_tracker.yml), nessuna scrittura su tracker.db, nessun impatto sul tracker
principale nemmeno in caso di bug qui dentro.
"""
import json
import os
import time
import threading

import websocket

import track

# ---- Soglie modello ZenLock (env var per poter tarare senza toccare codice) ----
# (soglia_normale_EUR, soglia_eccezione_EUR) per bucket. Sopra soglia_eccezione: fuori dal suo
# range osservato, si scarta a prescindere.
ZENLOCK_CEILING_CLASSIC_NORMAL = float(os.environ.get('ZENLOCK_CEILING_CLASSIC_NORMAL', '4.0'))
ZENLOCK_CEILING_CLASSIC_EXCEPTION = float(os.environ.get('ZENLOCK_CEILING_CLASSIC_EXCEPTION', '30.0'))
ZENLOCK_CEILING_IN_SEASON_NORMAL = float(os.environ.get('ZENLOCK_CEILING_IN_SEASON_NORMAL', '8.0'))
ZENLOCK_CEILING_IN_SEASON_EXCEPTION = float(os.environ.get('ZENLOCK_CEILING_IN_SEASON_EXCEPTION', '70.0'))

ZENLOCK_PRICE_CEILINGS = {
    'classic': (ZENLOCK_CEILING_CLASSIC_NORMAL, ZENLOCK_CEILING_CLASSIC_EXCEPTION),
    'in_season': (ZENLOCK_CEILING_IN_SEASON_NORMAL, ZENLOCK_CEILING_IN_SEASON_EXCEPTION),
}

# Sconto minimo richiesto vs mediana live degli altri annunci dello stesso bucket. Sotto la
# soglia normale usiamo il valore osservato (mediana ~41%, media ~40% sui 10 casi comparabili
# del run 14gg) meno un margine di sicurezza; sopra (fascia "eccezione", carte piu' costose e
# piu' rare) alziamo la soglia perche' il campione li' e' quasi zero e vogliamo essere piu'
# conservativi.
ZENLOCK_DISCOUNT_NORMAL = float(os.environ.get('ZENLOCK_DISCOUNT_NORMAL', '0.30'))
ZENLOCK_DISCOUNT_HIGH_VALUE = float(os.environ.get('ZENLOCK_DISCOUNT_HIGH_VALUE', '0.40'))

# Sotto il piu' economico snipe osservato (0.33-0.48EUR): filtro solo rumore vero (annunci a
# pochi centesimi), NON il MIN_PRICE_EUR=2.0 del tracker principale (troppo alto per questo
# modello, avrebbe scartato meta' degli snipe reali di ZenLock).
ZENLOCK_MIN_PRICE_EUR = float(os.environ.get('ZENLOCK_MIN_PRICE_EUR', '0.30'))

# Sotto questo numero di ALTRI annunci live comparabili nello stesso bucket, il riferimento di
# mercato non e' abbastanza affidabile da fidarsene (stesso principio del tracker principale
# con THIN_BUCKET_MAX_LISTINGS, qui applicato al nostro calcolo di mediana).
ZENLOCK_MIN_COMPARABLES = int(os.environ.get('ZENLOCK_MIN_COMPARABLES', '2'))

ZENLOCK_LISTEN_SECONDS = int(os.environ.get('ZENLOCK_LISTEN_SECONDS', '200'))


def compute_live_discount(player_slug, season_type, price_eur, exclude_card_slug, eth_rate):
    """Mediana degli ALTRI annunci live aperti dello stesso giocatore/bucket (esclude
    l'annuncio che ha scatenato l'evento), e sconto di price_eur rispetto a quella mediana.
    Ritorna (sconto_frazione, n_comparabili, mediana) oppure None se il campione e' troppo
    scarno per fidarsene (vedi ZENLOCK_MIN_COMPARABLES)."""
    buckets = track.get_bucket_prices(player_slug, eth_rate)
    prices, _incomplete = buckets.get(season_type, ([], False))
    others = sorted(p for p, slug in prices if slug != exclude_card_slug)
    if len(others) < ZENLOCK_MIN_COMPARABLES:
        return None
    n = len(others)
    median = others[n // 2] if n % 2 == 1 else (others[n // 2 - 1] + others[n // 2]) / 2
    if median <= 0:
        return None
    discount = (median - price_eur) / median
    return discount, len(others), median


def evaluate_zenlock_offer(player_slug, player_name, season_type, season_name, price_eur,
                            card_slug, eth_rate, stats):
    ceilings = ZENLOCK_PRICE_CEILINGS.get(season_type)
    if not ceilings:
        return
    normal_ceiling, exception_ceiling = ceilings
    if price_eur > exception_ceiling:
        return  # fuori dal range osservato per questo bucket, ZenLock non compra qui

    required_discount = ZENLOCK_DISCOUNT_NORMAL if price_eur <= normal_ceiling else ZENLOCK_DISCOUNT_HIGH_VALUE

    result = compute_live_discount(player_slug, season_type, price_eur, card_slug, eth_rate)
    if result is None:
        stats['skipped_no_comparable'] = stats.get('skipped_no_comparable', 0) + 1
        return  # nessun confronto affidabile: per policy esplicita NON notifichiamo "al buio"

    discount, n_comparables, median = result
    if discount < required_discount:
        return

    stats['fired'] = stats.get('fired', 0) + 1
    fascia = "normale" if price_eur <= normal_ceiling else "eccezione (carta di valore)"
    # Stesso pattern di link gia' usato e testato dal tracker principale (vedi send_instant_alert
    # in track.py) -- porta direttamente alla scheda della carta sul market Sorare, per la
    # verifica rapida prima di comprare.
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    link = f"{base_link}?card={card_slug}" if card_slug else base_link
    msg = (f"🎯 <b>Modello ZenLock</b> -- {player_name} [{season_type}]\n\n"
           f"Prezzo: {price_eur:.2f}EUR (fascia {fascia})\n"
           f"Mediana live altri annunci: {median:.2f}EUR ({n_comparables} comparabili)\n"
           f"Sconto: {discount:.1%} (soglia richiesta {required_discount:.0%})\n\n"
           f"👉 <b><a href='{link}'>APRI SU SORARE</a></b> 👈")
    track.log(f"[modello zenlock] MATCH -- {player_name} [{season_type}] {price_eur:.2f}EUR, "
              f"sconto {discount:.1%} su mediana {median:.2f}EUR (n={n_comparables})")
    track.send_telegram_msg(msg)


def handle_zenlock_offer_update(offer, eth_rate, stats):
    if not offer:
        return
    offer_id = offer.get('id') or ''
    if not offer_id.startswith('SingleSaleOffer:'):
        return

    offer_status = offer.get('status')
    if offer_status != 'opened':
        return

    stats.setdefault('seen_offer_status', set())
    dedup_key = (offer_id, offer_status)
    if dedup_key in stats['seen_offer_status']:
        return
    stats['seen_offer_status'].add(dedup_key)

    sender_side = offer.get('senderSide') or {}
    receiver_side = offer.get('receiverSide') or {}
    if receiver_side.get('anyCards'):
        return  # scambio carta-per-carta, non ci interessa

    price_eur = track.eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
    if price_eur is None or price_eur < ZENLOCK_MIN_PRICE_EUR:
        return

    for card in (sender_side.get('anyCards') or []):
        if card.get('rarityTyped') != 'limited':
            continue
        if card.get('sport') != 'FOOTBALL':
            continue

        player = card.get('anyPlayer') or {}
        player_slug = player.get('slug')
        if not player_slug:
            continue
        player_name = player.get('displayName', player_slug)
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        card_slug = card.get('slug')
        season_type = track.season_type_for_card(card, season_name)

        stats['processed'] = stats.get('processed', 0) + 1
        evaluate_zenlock_offer(player_slug, player_name, season_type, season_name, price_eur,
                                card_slug, eth_rate, stats)


def run_zenlock_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": track.SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }
    stats = {"received": 0, "processed": 0, "fired": 0, "skipped_no_comparable": 0}

    def on_open(ws):
        track.log("[modello zenlock] connesso al canale eventi Sorare, sottoscrizione in corso...")
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
            track.log("[modello zenlock] sottoscrizione confermata, in ascolto...")
            return
        if msg_type == 'reject_subscription':
            track.log(f"[modello zenlock] ERRORE: sottoscrizione rifiutata: {message}")
            return

        payload = message.get('message')
        if not payload or payload.get('errors'):
            return

        stats["received"] += 1
        offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
        if offer:
            handle_zenlock_offer_update(offer, eth_rate, stats)

    def on_error(ws, error):
        track.log(f"[modello zenlock] errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        track.log(f"[modello zenlock] connessione chiusa (codice {close_status_code}). "
                  f"Eventi: {stats['received']}, carte valutate: {stats['processed']}, "
                  f"notifiche inviate: {stats['fired']}, scartate per mancanza comparabili: "
                  f"{stats['skipped_no_comparable']}")

    ws = websocket.WebSocketApp(
        track.WS_URL,
        header=[f"Cookie: {track.COOKIES}"] if track.COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    timer = threading.Timer(ZENLOCK_LISTEN_SECONDS, ws.close)
    timer.daemon = True
    timer.start()
    ws.run_forever(ping_interval=30, ping_timeout=10)
    timer.cancel()


if __name__ == "__main__":
    eth_rate = track.get_eth_rate()
    track.log(f"[modello zenlock] Tasso ETH/EUR: {eth_rate}")
    track.log(f"[modello zenlock] Ascolto per {ZENLOCK_LISTEN_SECONDS} secondi "
              f"(soglie: classic <={ZENLOCK_CEILING_CLASSIC_NORMAL}EUR / in_season "
              f"<={ZENLOCK_CEILING_IN_SEASON_NORMAL}EUR, sconto min "
              f"{ZENLOCK_DISCOUNT_NORMAL:.0%})...")
    run_zenlock_listener(eth_rate)
    track.log("[modello zenlock] esecuzione terminata.")
