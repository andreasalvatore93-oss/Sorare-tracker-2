"""Crafted Card Scanner (NUOVO, 18/07 -- richiesta esplicita dell'utente).

Idea di fondo: su Sorare le carte possono anche essere CREATE (craftate tramite essenze, o
vinte come premio), non solo comprate -- e molto spesso i manager che ne hanno appena creata
una la svendono se ricevono subito un'offerta diretta. Questo scanner cerca proprio quel
momento: una carta appena CREATA (nelle ultime CRAFT_WINDOW_HOURS ore) dello stesso tipo di
una carta in season di fascia 1-20EUR appena vista sul mercato.

Flusso:
1. Ascolta lo stream WS del mercato (stessa subscription collaudata di track.py) per carte
   Limited FOOTBALL in season appena messe in vendita con prezzo minimo di mercato tra
   CRAFT_MIN_PRICE_EUR e CRAFT_MAX_PRICE_EUR.
2. Per ogni candidato, interroga le carte dello stesso giocatore e cerca stampe Limited in
   season CREATE nelle ultime CRAFT_WINDOW_HOURS ore (NON necessariamente in vendita).
3. Al primo match: notifica Telegram (STESSO canale di track classico/zenlock: env
   TELEGRAM_TOKEN/TELEGRAM_CHAT_ID) con giocatore, manager creatore, quante ore fa, prezzo
   minimo attuale, link alla carta -- e si FERMA (uno-shot per run).
4. Se nessun match entro MAX_RUN_SECONDS (default 500), termina senza notifica.

SCOPERTA SCHEMA (introspection disabilitata, come sempre in questo progetto si va per
tentativi): non esiste un campo noto "craft" -- la scoperta avviene in due fasi al primo run,
usando come banco di prova CRAFT_PROBE_CARD_SLUG (una carta DELL'UTENTE sicuramente creata:
heung-min-son-2026-limited-364):
  a) probe_creation_fields(): prova una lista di candidati di campo su anyCard (timestamp di
     creazione + eventuale tipo/provenienza) e logga per ciascuno OK/ERRORE -- il primo
     timestamp funzionante viene usato per la finestra delle 6 ore.
  b) probe_player_cards_query(): prova varianti di query per elencare le carte Limited di un
     giocatore (serve per il passo 2). Se nessuna funziona, il run termina con un log chiaro
     su cosa e' stato provato, cosi' si itera sui log come per tutto il resto del progetto.

Blacklist manager: se il creatore della carta trovata e' blacklistato, il match viene saltato
e si continua. Hardcoded: gli stessi 13 bot gia' hardcoded nel bundle scanner (SOLO quelli,
niente coda di raffreddamento -- richiesta esplicita). In piu' input dal workflow
(CRAFT_BLACKLIST_MANAGERS, lista separata da virgola) per aggiunte al volo.
"""
import datetime
import json
import os
import threading
import time

import websocket

import track

# --- Configurazione ---
MAX_RUN_SECONDS = float(os.environ.get('CRAFT_MAX_RUN_SECONDS', '500'))
CRAFT_WINDOW_HOURS = float(os.environ.get('CRAFT_WINDOW_HOURS', '6'))
CRAFT_MIN_PRICE_EUR = float(os.environ.get('CRAFT_MIN_PRICE_EUR', '1'))
CRAFT_MAX_PRICE_EUR = float(os.environ.get('CRAFT_MAX_PRICE_EUR', '20'))
# Carta di prova SICURAMENTE creata (dell'utente) per la scoperta dei campi schema.
CRAFT_PROBE_CARD_SLUG = os.environ.get('CRAFT_PROBE_CARD_SLUG', 'heung-min-son-2026-limited-364')

# Stessi 13 bot hardcoded del bundle scanner (SOLO gli hardcoded, non il file additions ne' la
# coda di raffreddamento -- richiesta esplicita dell'utente).
CRAFT_BLACKLIST_MANAGERS = {
    'clem777', 'satonio', 'zenlock', 'cheaper-than-him', 'eli-aquim',
    'lamella-4aa53b98-9221-410e-8092-05aaabd1ba30', 'sir-hiss-the-swap-bot',
    'paweltrader', 'basilbot', 'ruv-liquidation-of-gallery-at-fixed-prices',
    'jrodwalts-trade-115-active-buyer-seller', 'meowmeow7',
    'bellona-f0b1a9d7-3700-4d59-9044-ec54b7b348aa',
}
_extra_blacklist = os.environ.get('CRAFT_BLACKLIST_MANAGERS', '').strip()
if _extra_blacklist:
    CRAFT_BLACKLIST_MANAGERS.update(
        s.strip().lower() for s in _extra_blacklist.split(',') if s.strip())


def log(msg):
    track.log(f"[craft-scanner] {msg}")


# --- FASE A: scoperta campo timestamp/tipo di creazione su anyCard ---
# Candidati timestamp (il primo che funziona vince). 'createdAt' e' GIA' noto NON esistere su
# AnyCardInterface (errore reale visto in my_cards_profit.py) ma lo riproviamo comunque per
# completezza in questo contesto diverso.
CREATION_TS_CANDIDATES = ['mintedAt', 'craftedAt', 'forgedAt', 'issuedAt', 'bornAt',
                          'createdAt', 'publicMintedAt', 'assetCreatedAt', publicMinPrices]
# Candidati "tipo/provenienza" (facoltativi: se nessuno funziona, la finestra temporale basta
# comunque -- una carta apparsa da poche ore e' comunque "nuova").
CREATION_TYPE_CANDIDATES = ['mintType', 'creationType', 'provenance', 'crafted', 'isCrafted',
                            'origin', 'cardEdition { name }']

_creation_ts_field = None    # None = non ancora scoperto, '' = nessuno funziona
_creation_type_field = None


def _probe_single_field(field_expr):
    """Prova un singolo campo su anyCard(CRAFT_PROBE_CARD_SLUG). Ritorna (ok, valore)."""
    query = """
    query ProbeCraftField($slug: String!) {
      anyCard(slug: $slug) { %s }
    }
    """ % field_expr
    try:
        data = track.graphql_query(query, {"slug": CRAFT_PROBE_CARD_SLUG})
    except Exception as e:
        log(f"probe '{field_expr}': eccezione di rete {e}")
        return False, None
    if data.get('errors'):
        # log compatto: solo il primo messaggio d'errore (di solito contiene il "Did you mean")
        first_err = (data['errors'][0] or {}).get('message', '')
        log(f"probe '{field_expr}': ERRORE -- {first_err}")
        return False, None
    card = (data.get('data') or {}).get('anyCard') or {}
    key = field_expr.split(' ')[0].split('{')[0]
    value = card.get(key)
    log(f"probe '{field_expr}': OK, valore = {value!r}")
    return True, value


def probe_creation_fields():
    """Scopre (una volta per run) quale campo timestamp/tipo esiste su anyCard. Ritorna True se
    almeno un timestamp funziona (indispensabile per la finestra delle 6 ore)."""
    global _creation_ts_field, _creation_type_field
    log(f"scoperta campi creazione sulla carta di prova {CRAFT_PROBE_CARD_SLUG} "
        f"(sicuramente creata)...")
    for cand in CREATION_TS_CANDIDATES:
        ok, value = _probe_single_field(cand)
        if ok and value:
            _creation_ts_field = cand
            log(f">>> campo timestamp di creazione: '{cand}' (valore sulla carta di prova: {value})")
            break
    if not _creation_ts_field:
        _creation_ts_field = ''
        log(">>> NESSUN candidato timestamp funziona su anyCard -- impossibile applicare la "
            "finestra delle 6 ore. Prossimi candidati da provare a mano nei log sopra "
            "(guarda i suggerimenti 'Did you mean' negli errori). Interrompo il run.")
        return False
    for cand in CREATION_TYPE_CANDIDATES:
        ok, value = _probe_single_field(cand)
        if ok and value is not None:
            _creation_type_field = cand
            log(f">>> campo tipo/provenienza: '{cand}' (valore: {value!r}) -- verra' loggato "
                f"per ogni match, utile per distinguere craft da premio")
            break
    if not _creation_type_field:
        _creation_type_field = ''
        log(">>> nessun campo tipo/provenienza trovato -- si va di sola finestra temporale "
            "(comunque sufficiente: una stampa apparsa da poche ore e' 'nuova' a prescindere)")
    return True


# --- FASE B: scoperta query "carte di un giocatore" ---
# Varianti candidate per elencare le stampe Limited di un giocatore (serve slug + timestamp +
# proprietario). {ts} viene sostituito col campo timestamp scoperto in fase A.
PLAYER_CARDS_QUERY_CANDIDATES = [
    ("anyPlayer.cards", """
     query PlayerCards($slug: String!) {
       anyPlayer(slug: $slug) {
         cards(rarities: [limited], first: 40) {
           nodes { slug {ts} inSeasonEligible sportSeason { name } user { slug } }
         }
       }
     }
     """),
    ("anyPlayer.anyCards", """
     query PlayerCards($slug: String!) {
       anyPlayer(slug: $slug) {
         anyCards(rarities: [limited], first: 40) {
           nodes { slug {ts} inSeasonEligible sportSeason { name } user { slug } }
         }
       }
     }
     """),
    ("football.player.cards", """
     query PlayerCards($slug: String!) {
       football {
         player(slug: $slug) {
           cards(rarities: [limited], first: 40) {
             nodes { slug {ts} inSeasonEligible sportSeason { name } user { slug } }
           }
         }
       }
     }
     """),
]

_player_cards_variant = None  # None = non scoperto, '' = nessuna funziona


def _extract_player_cards(data, variant):
    d = data.get('data') or {}
    if variant == 'football.player.cards':
        conn = (((d.get('football') or {}).get('player') or {}).get('cards') or {})
    else:
        field = variant.split('.')[1]
        conn = ((d.get('anyPlayer') or {}).get(field) or {})
    return conn.get('nodes') or []


def fetch_player_recent_limited_cards(player_slug):
    """Ritorna la lista di carte Limited del giocatore (nodi con slug/timestamp/owner), o None
    se nessuna variante di query funziona. Scoperta della variante al primo uso."""
    global _player_cards_variant
    if _player_cards_variant == '':
        return None
    variants = ([v for v in PLAYER_CARDS_QUERY_CANDIDATES if v[0] == _player_cards_variant]
                if _player_cards_variant else PLAYER_CARDS_QUERY_CANDIDATES)
    for variant, query_tpl in variants:
        query = query_tpl.replace('{ts}', _creation_ts_field)
        try:
            data = track.graphql_query(query, {"slug": player_slug})
        except Exception as e:
            log(f"eccezione di rete su query carte giocatore ({variant}): {e}")
            return None
        if data.get('errors'):
            if _player_cards_variant is None:
                first_err = (data['errors'][0] or {}).get('message', '')
                log(f"variante carte-giocatore '{variant}' NON funziona: {first_err}")
            continue
        if _player_cards_variant is None:
            _player_cards_variant = variant
            log(f">>> variante carte-giocatore '{variant}' FUNZIONA -- la uso da ora in poi.")
        return _extract_player_cards(data, variant)
    if _player_cards_variant is None:
        _player_cards_variant = ''
        log(">>> NESSUNA variante di query carte-giocatore funziona -- impossibile cercare le "
            "carte create. Guarda gli errori sopra (suggerimenti 'Did you mean') e aggiorna "
            "PLAYER_CARDS_QUERY_CANDIDATES. Interrompo la ricerca per questo run.")
    return None


def _parse_ts(value):
    try:
        return datetime.datetime.fromisoformat(
            (value or '').replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def find_recently_created_card(player_slug, exclude_card_slug):
    """Cerca tra le carte Limited in season del giocatore una stampa creata nelle ultime
    CRAFT_WINDOW_HOURS ore (esclusa quella dell'evento). Ritorna (card_node, ore_fa) o None."""
    nodes = fetch_player_recent_limited_cards(player_slug)
    if nodes is None:
        return None
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=CRAFT_WINDOW_HOURS)
    for node in nodes:
        if node.get('slug') == exclude_card_slug:
            continue
        season_name = (node.get('sportSeason') or {}).get('name', 'unknown')
        if track.season_type_for_card(node, season_name) != 'in_season':
            continue
        ts = _parse_ts(node.get(_creation_ts_field))
        if ts is None or ts < cutoff:
            continue
        hours_ago = (datetime.datetime.utcnow() - ts).total_seconds() / 3600
        return node, hours_ago
    return None


def get_market_min_price(player_slug, eth_rate):
    """Prezzo minimo di mercato in season per il giocatore (riusa get_bucket_prices di track)."""
    try:
        buckets = track.get_bucket_prices(player_slug, eth_rate)
        prices, _incomplete = buckets.get('in_season', ([], False))
        return prices[0][0] if prices else None
    except Exception as e:
        log(f"eccezione su prezzo minimo per {player_slug}: {e}")
        return None


# --- Ascolto WS + valutazione ---
_match_found = threading.Event()


def handle_event(offer, eth_rate, stats):
    if _match_found.is_set() or not offer:
        return
    offer_id = offer.get('id') or ''
    if not offer_id.startswith('SingleSaleOffer:'):
        return
    if offer.get('status') != 'opened':
        return
    receiver_side = offer.get('receiverSide') or {}
    if receiver_side.get('anyCards'):
        return  # scambio carta-per-carta
    price_eur = track.eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
    if price_eur is None:
        return
    for card in ((offer.get('senderSide') or {}).get('anyCards') or []):
        if _match_found.is_set():
            return
        if card.get('rarityTyped') != 'limited' or card.get('sport') != 'FOOTBALL':
            continue
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        if track.season_type_for_card(card, season_name) != 'in_season':
            continue
        player = card.get('anyPlayer') or {}
        player_slug = player.get('slug')
        if not player_slug:
            continue
        # dedup per giocatore: inutile ricontrollare lo stesso giocatore piu' volte per run
        stats.setdefault('checked_players', set())
        if player_slug in stats['checked_players']:
            continue
        # Filtro fascia sul PREZZO MINIMO DI MERCATO (richiesta esplicita: "valore compreso tra
        # 1-20 euro (confronto con prezzo minimo)"). Prefiltro grezzo sull'evento per non fare
        # query inutili sui casi palesemente fuori fascia.
        if price_eur < CRAFT_MIN_PRICE_EUR or price_eur > CRAFT_MAX_PRICE_EUR * 2:
            continue
        stats['checked_players'].add(player_slug)
        min_price = get_market_min_price(player_slug, eth_rate)
        if min_price is None or not (CRAFT_MIN_PRICE_EUR <= min_price <= CRAFT_MAX_PRICE_EUR):
            continue
        stats['candidates'] = stats.get('candidates', 0) + 1
        result = find_recently_created_card(player_slug, card.get('slug'))
        if _player_cards_variant == '':
            _match_found.set()  # query non scoperta: inutile continuare ad ascoltare
            return
        if result is None:
            log(f"{player.get('displayName', player_slug)}: nessuna stampa creata nelle ultime "
                f"{CRAFT_WINDOW_HOURS:.0f}h, passo oltre")
            continue
        node, hours_ago = result
        owner_slug = ((node.get('user') or {}).get('slug') or '').lower()
        if owner_slug in CRAFT_BLACKLIST_MANAGERS:
            log(f"MATCH SCARTATO: {node.get('slug')} creato da '{owner_slug}' (blacklistato), "
                f"passo oltre")
            continue
        # MATCH!
        player_name = player.get('displayName', player_slug)
        card_slug = node.get('slug')
        type_info = ''
        if _creation_type_field:
            type_key = _creation_type_field.split(' ')[0].split('{')[0]
            type_info = f" [{type_key}: {node.get(type_key)!r}]"
        link = (f"https://sorare.com/it/football/market/shop/manager-sales/"
                f"{player_slug}/limited?card={card_slug}")
        log(f"MATCH! {player_name}: {card_slug} creata {hours_ago:.1f}h fa da "
            f"'{owner_slug or 'sconosciuto'}'{type_info}, minimo mercato {min_price:.2f}EUR")
        msg = (
            f"\U0001F528 <b>Crafted Card Scanner -- MATCH!</b>\n\n"
            f"Giocatore: {player_name}\n"
            f"Carta creata: {card_slug}\n"
            f"Creata da/vinta da: <b>{owner_slug or 'sconosciuto'}</b>, "
            f"{hours_ago:.1f} ore fa{type_info}\n"
            f"Prezzo minimo attuale della carta: {min_price:.2f}EUR\n\n"
            f"\U0001F4A1 Il manager potrebbe svenderla con un'offerta diretta immediata.\n\n"
            f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
        )
        track.send_telegram_msg(msg)
        stats['matches'] = stats.get('matches', 0) + 1
        _match_found.set()
        return


def run_scanner():
    log(f"avvio -- fascia {CRAFT_MIN_PRICE_EUR:.0f}-{CRAFT_MAX_PRICE_EUR:.0f}EUR, finestra "
        f"creazione {CRAFT_WINDOW_HOURS:.0f}h, durata max {MAX_RUN_SECONDS:.0f}s, blacklist "
        f"{len(CRAFT_BLACKLIST_MANAGERS)} manager")
    if not probe_creation_fields():
        return
    eth_rate = track.get_eth_rate()
    log(f"tasso ETH/EUR: {eth_rate}")
    stats = {}
    deadline = time.time() + MAX_RUN_SECONDS

    # Handshake/parsing identici a run_listener di track.py (gia' collaudati in produzione).
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": track.SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    def on_open(ws):
        log("connesso al canale eventi Sorare, sottoscrizione in corso...")
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({
            "command": "message",
            "identifier": identifier,
            "data": json.dumps(subscription_payload),
        }))

    def on_message(ws, raw_message):
        if _match_found.is_set() or time.time() >= deadline:
            ws.close()
            return
        try:
            message = json.loads(raw_message)
        except (ValueError, TypeError):
            return
        msg_type = message.get('type')
        if msg_type in ('welcome', 'ping'):
            return
        if msg_type == 'confirm_subscription':
            log("sottoscrizione confermata, in ascolto...")
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
        offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
        try:
            handle_event(offer, eth_rate, stats)
        except Exception as e:
            log(f"eccezione durante la valutazione di un evento: {e}")
        if _match_found.is_set():
            ws.close()

    def on_error(ws, error):
        log(f"errore WebSocket: {error}")

    ws = websocket.WebSocketApp(
        track.WS_URL,
        header=[f"Cookie: {track.COOKIES}"] if track.COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    timer = threading.Timer(MAX_RUN_SECONDS, ws.close)
    timer.start()
    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()

    log(f"fine run -- candidati in fascia: {stats.get('candidates', 0)}, "
        f"match: {stats.get('matches', 0)}"
        + (" (match trovato, run interrotto come previsto)" if _match_found.is_set() else
           " (nessun match entro il tempo massimo)"))


if __name__ == '__main__':
    run_scanner()
    log("esecuzione terminata.")
