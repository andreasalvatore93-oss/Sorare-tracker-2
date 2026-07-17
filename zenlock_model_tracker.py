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
- sconto vs un riferimento di mercato LIVE. AGGIORNATO 17/07 (v3, caso Nayef Aguerd): non piu'
  una mediana su tutto il bucket (vulnerabile ad annunci vecchi/stagnanti mai aggiornati, vedi
  FIX piu' sotto vicino a compute_live_discount) ma il prezzo del PROSSIMO annuncio live piu'
  economico tra gli altri dello stesso giocatore/bucket, via track.get_bucket_prices -- stessa
  fonte dati e stesso principio gia' usati e testati dal tracker principale per il proprio
  "secondo prezzo" (required_margin_fraction/MARGIN_TIERS), quindi a costo zero in termini di
  rischio. NON usiamo lo storico vendite (fetch_player_recent_direct_buys) qui: e' pensato per
  un report offline, troppo pesante/lento per essere richiamato ad ogni singolo evento WS in
  tempo reale.

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
# FIX 17/07 (v6, ricalibrazione su 85 snipe reali/14gg, margin_model post-fix valute/paginazione):
# 70 -> 90. Distribuzione osservata: 43/48 in_season sotto 8EUR (soglia normale confermata), ma
# il piu' caro snipe eccezione osservato e' Messi a 65.71EUR -- solo 4.29EUR sotto il vecchio
# ceiling di 70. Troppo poco margine: un suo prossimo acquisto anche di poco piu' caro sarebbe
# stato scartato per prezzo, prima ancora di valutare lo sconto. 90 da' respiro mantenendo
# comunque un limite (non illimitato).
ZENLOCK_CEILING_IN_SEASON_EXCEPTION = float(os.environ.get('ZENLOCK_CEILING_IN_SEASON_EXCEPTION', '90.0'))

ZENLOCK_PRICE_CEILINGS = {
    'classic': (ZENLOCK_CEILING_CLASSIC_NORMAL, ZENLOCK_CEILING_CLASSIC_EXCEPTION),
    'in_season': (ZENLOCK_CEILING_IN_SEASON_NORMAL, ZENLOCK_CEILING_IN_SEASON_EXCEPTION),
}

# Sconto minimo richiesto vs mediana live degli altri annunci dello stesso bucket. Sotto la
# soglia normale usiamo il valore osservato (mediana ~41%, media ~40% sui 10 casi comparabili
# del run 14gg) meno un margine di sicurezza; sopra (fascia "eccezione", carte piu' costose e
# piu' rare) alziamo la soglia perche' il campione li' e' quasi zero e vogliamo essere piu'
# conservativi.
# FIX 17/07 (v7, TEST richiesto esplicitamente dall'utente -- "voglio ammorbidire, giro da
# un'ora e zero notifiche, se vengo inondato torniamo indietro"): 30% -> 25%. Tocco solo le
# soglie di sconto, NON i filtri anti-rumore aggiunti oggi (MIN_REFERENCE_EUR, MIN_COMPARABLES,
# classic_looks_cheap_everywhere) -- quelli restano, servono a evitare di reintrodurre proprio i
# falsi positivi gia' risolti in sessione (Balerdi, Jo Hyeon-Woo-style). Facile da riportare a
# 0.30 se il volume di notifiche sale troppo.
ZENLOCK_DISCOUNT_NORMAL = float(os.environ.get('ZENLOCK_DISCOUNT_NORMAL', '0.25'))
# FIX 17/07 (v6, richiesta esplicita dell'utente, caso Emiliano Martínez): 40% -> 20%. Sull'unico
# snipe eccezione con confronto di mercato verificabile (85 snipe/14gg), ZenLock ha comprato con
# solo il 9.7% di sconto reale -- ben sotto il 40% che il modello richiedeva, quindi quel caso
# oggi non l'avremmo notificato. Un solo dato, quindi non lo usiamo come soglia diretta: 20% e'
# circa il doppio del 9.7% osservato, un margine di sicurezza nel dubbio (non sappiamo ancora se
# 9.7% e' tipico o un'eccezione lui stesso). Da ritarare se emergono altri casi eccezione con
# confronto di mercato.
ZENLOCK_DISCOUNT_HIGH_VALUE = float(os.environ.get('ZENLOCK_DISCOUNT_HIGH_VALUE', '0.20'))

# Sotto il piu' economico snipe osservato (0.33-0.48EUR): filtro solo rumore vero (annunci a
# pochi centesimi), NON il MIN_PRICE_EUR=2.0 del tracker principale (troppo alto per questo
# modello, avrebbe scartato meta' degli snipe reali di ZenLock).
ZENLOCK_MIN_PRICE_EUR = float(os.environ.get('ZENLOCK_MIN_PRICE_EUR', '0.30'))

# Sotto questo numero di ALTRI annunci live comparabili nello stesso bucket, il riferimento di
# mercato non e' abbastanza affidabile da fidarsene (stesso principio del tracker principale
# con THIN_BUCKET_MAX_LISTINGS, qui applicato al nostro calcolo di mediana).
ZENLOCK_MIN_COMPARABLES = int(os.environ.get('ZENLOCK_MIN_COMPARABLES', '2'))

# FIX 17/07 (v2, primo test reale -- richiesta esplicita dell'utente, "tutte notifiche inutili"):
# il primo test (30s) ha sparato 5 notifiche su 25 carte valutate -- estrapolato sui 200s normali
# sarebbero 30+, molto piu' della frequenza reale di ZenLock (~6 snipe/giorno su TUTTO il
# mercato). Il problema: su carte quasi gratis (giocatori di squadra, poco richiesti) un salto di
# pochi centesimi produce uno sconto% enorme (es. Balerdi 0.97EUR vs mediana 1.50EUR = 35%, ma
# solo 0.53EUR di differenza) senza essere un vero mispricing -- e' solo rumore normale su un
# segmento senza domanda di rivendita reale, non un'occasione.
#
# Due filtri aggiuntivi, IN AND col resto (tutti richiesti insieme):
# - ZENLOCK_MIN_DISCOUNT_EUR: differenza assoluta minima (riferimento - prezzo) in euro. Il piu'
#   piccolo scarto assoluto osservato tra gli snipe REALI di ZenLock con confronto di mercato
#   era 0.39EUR (Bjorn Utvik) -- teniamo un filo sotto per non essere troppo severi.
# - ZENLOCK_MIN_REFERENCE_EUR: il prezzo di riferimento stesso deve valere almeno questa cifra --
#   esclude i giocatori "quasi gratis" dove qualsiasi calcolo percentuale e' rumore per
#   costruzione, indipendentemente dallo sconto. NOTA: questo esclude anche 2 dei 10 snipe reali
#   comparabili di ZenLock (Owusu mediana 0.99EUR, Utvik mediana 0.88EUR) -- compromesso
#   consapevole, prima iterazione: meglio perdere qualche caso genuino su carte da centesimi che
#   restare sommersi di notifiche senza edge reale. Da ritarare coi prossimi test.
# FIX 17/07 (v7, stesso TEST di ammorbidimento richiesto dall'utente): 0.50 -> 0.40, resta
# comunque sopra il minimo scarto assoluto reale osservato (0.39EUR, Bjorn Utvik) -- non lo
# tocchiamo verso il basso, solo ci avviciniamo.
ZENLOCK_MIN_DISCOUNT_EUR = float(os.environ.get('ZENLOCK_MIN_DISCOUNT_EUR', '0.40'))
ZENLOCK_MIN_REFERENCE_EUR = float(os.environ.get('ZENLOCK_MIN_REFERENCE_EUR', '1.50'))

# FIX 17/07 (v6, caso Ivan Perišić -- richiesta esplicita dell'utente dopo verifica a mano):
# stessa tolleranza gia' usata dal tracker principale per il check incrociato tra bucket
# (UNIQUE_DEAL_TOLERANCE) -- vedi classic_looks_cheap_everywhere piu' sotto.
ZENLOCK_SIBLING_TOLERANCE = float(os.environ.get('ZENLOCK_SIBLING_TOLERANCE', '0.05'))

ZENLOCK_LISTEN_SECONDS = int(os.environ.get('ZENLOCK_LISTEN_SECONDS', '200'))

# NOTA STORICA (17/07, v5, caso Jhegson Sebastian Mendez -- indagine chiusa): il debug
# comparabili grezzi mostrava solo 2 annunci (1.99EUR, 24.01EUR) quando sul mercato reale ce
# n'erano 4 (mancavano 0.59EUR e 1.92EUR, ENTRAMBI vecchi di giorni -- non la finestra di
# invisibilita' dei 2 minuti -- e confermato dall'utente che non erano Early Access). Il dump
# grezzo COMPLETO (diagnostic_dump_missing_offer, gia' in track.py) ha chiarito la causa: i due
# annunci mancanti NON compaiono nemmeno li' (9 nodi totali restituiti dalla query, nessuno dei
# due) -- quindi non e' un filtro nostro lato client, e' la query liveSingleSaleOffers di Sorare
# stessa che non li restituisce. Stesso fenomeno di "annunci fantasma" gia' documentato altrove
# in track.py (Cancelo, Sangare, O'Reilly, Jeong Seung-Won) e mai risolto nonostante indagini
# approfondite -- limite strutturale dei dati Sorare, non fixabile lato nostro. Implicazione:
# lo sconto% calcolato va sempre trattato come limite SUPERIORE (il vero minimo di mercato puo'
# essere piu' basso e invisibile a noi), da qui l'importanza del link "APRI SU SORARE" in ogni
# notifica per la verifica visiva finale prima di comprare. L'hook diagnostico resta disponibile
# (attivo solo se ZENLOCK_DIAGNOSTIC_PLAYER_SLUG e' valorizzato) per il prossimo caso dubbio.
ZENLOCK_DIAGNOSTIC_PLAYER_SLUG = os.environ.get('ZENLOCK_DIAGNOSTIC_PLAYER_SLUG', '').strip()


# FIX 17/07 (v3, caso Nayef Aguerd -- verificato a mano dall'utente): la carta era infortunata da
# mesi (Groin Injury, ritorno sconosciuto) -- TUTTO il mercato era gia' sceso in un cluster
# stretto 1.44-3.36EUR, ma la mediana calcolata su 15 comparabili risultava 7.87EUR, gonfiata da
# annunci vecchi/stagnanti mai aggiornati dal venditore dopo l'infortunio (nessuno li ha ne'
# ritirati ne' scontati, restano li' a un prezzo ormai falso). Stesso identico trabocchetto gia'
# risolto nel tracker principale (vedi commento su required_margin_fraction/MARGIN_TIERS e caso
# Muric, "PERICOLOSO in un caso reale e frequente: un giocatore si infortuna... DUE manager lo
# rimettono in vendita al nuovo prezzo basso"): la mediana su TUTTO il bucket e' vulnerabile
# esattamente a questo skew. La soluzione gia' testata li' e' non usare una statistica sull'intero
# bucket, ma confrontare solo col prezzo del PROSSIMO annuncio piu' economico disponibile ORA
# (own_prices[1] li', others[0] qui) -- se il mercato si e' davvero gia' adeguato (caso Aguerd),
# quel prezzo e' anch'esso basso e il confronto scarta correttamente il falso positivo; se invece
# e' un vero mispricing, il prossimo annuncio piu' economico resta comunque ben piu' caro.
def compute_live_discount(buckets, season_type, price_eur, exclude_card_slug):
    """Prezzo del prossimo annuncio live piu' economico tra gli ALTRI annunci aperti dello stesso
    giocatore/bucket (esclude l'annuncio che ha scatenato l'evento), e sconto di price_eur
    rispetto a quel prezzo. Ritorna (sconto_frazione, n_comparabili, prezzo_riferimento,
    others_raw) oppure None se il campione e' troppo scarno per fidarsene (vedi
    ZENLOCK_MIN_COMPARABLES). others_raw (lista completa (prezzo, slug_carta) ordinata) viene
    tenuta a disposizione SOLO per diagnostica sui MATCH (vedi FIX 17/07 v4, caso Barreiro --
    l'utente ha verificato a mano che il mercato aveva piu' annunci economici NON Early Access di
    quanti ne vedevamo noi (5), causa ancora da confermare -- serve il dato grezzo per capire se
    e' un bug di paginazione/bucket stagione o altro, invece di continuare a indovinare.

    FIX 17/07 (v6, caso Perišić): prende 'buckets' gia' calcolato invece di rifare la query --
    get_bucket_prices restituisce GIA' entrambi i bucket (in_season e classic) in un'unica
    lettura, serve anche a classic_looks_cheap_everywhere subito sotto senza query aggiuntive."""
    prices, _incomplete = buckets.get(season_type, ([], False))
    others = sorted((p, slug) for p, slug in prices if slug != exclude_card_slug)
    if len(others) < ZENLOCK_MIN_COMPARABLES:
        return None
    reference_price = others[0][0]
    if reference_price <= 0:
        return None
    discount = (reference_price - price_eur) / reference_price
    return discount, len(others), reference_price, others


def classic_looks_cheap_everywhere(buckets, season_type, price_eur):
    """FIX 17/07 (v6, richiesta esplicita dell'utente, caso Ivan Perišić): una carta CLASSIC
    segnalata va confrontata anche col bucket gemello IN_SEASON -- se il minimo in_season non e'
    sensibilmente piu' caro del prezzo che stiamo per notificare, il giocatore e' economico
    ovunque (non solo quella carta), il calo% calcolato nel solo bucket classic e' rumore, non un
    vero mispricing. Applicato SOLO in questa direzione (classic notificata -> controlla anche
    in_season): il contrario (carta in_season notificata, classic gemello piu' economico) e'
    normale/atteso -- il classic e' quasi sempre piu' economico dell'in_season per costruzione,
    non invalida un affare in_season vero, quindi non blocchiamo in quel verso.

    Caso reale che ha innescato il fix: Perišić classic 4.00EUR notificato con riferimento
    classic corretto (6.37EUR, secondo prezzo classic), ma il minimo in_season era 3.99EUR --
    piu' economico persino del prezzo "scontato" che stavamo per notificare. Confermato
    dall'utente via screenshot del mercato reale."""
    if season_type != 'classic':
        return False
    sibling_prices, _incomplete = buckets.get('in_season', ([], False))
    if not sibling_prices:
        return False  # nessun dato sul gemello, non possiamo giudicare: non blocchiamo al buio
    sibling_min = sibling_prices[0][0]
    if sibling_min <= 0:
        return False
    return price_eur >= sibling_min * (1 - ZENLOCK_SIBLING_TOLERANCE)


def evaluate_zenlock_offer(player_slug, player_name, season_type, season_name, price_eur,
                            card_slug, eth_rate, stats):
    ceilings = ZENLOCK_PRICE_CEILINGS.get(season_type)
    if not ceilings:
        return
    normal_ceiling, exception_ceiling = ceilings
    if price_eur > exception_ceiling:
        return  # fuori dal range osservato per questo bucket, ZenLock non compra qui

    required_discount = ZENLOCK_DISCOUNT_NORMAL if price_eur <= normal_ceiling else ZENLOCK_DISCOUNT_HIGH_VALUE

    # Un'unica lettura di ENTRAMBI i bucket (in_season + classic) -- serve sia al calcolo dello
    # sconto nel proprio bucket sia al check incrociato con l'in_season sotto (caso Perišić),
    # senza query duplicate.
    buckets = track.get_bucket_prices(player_slug, eth_rate)
    result = compute_live_discount(buckets, season_type, price_eur, card_slug)
    if result is None:
        stats['skipped_no_comparable'] = stats.get('skipped_no_comparable', 0) + 1
        return  # nessun confronto affidabile: per policy esplicita NON notifichiamo "al buio"

    discount, n_comparables, reference_price, others_raw = result
    if discount < required_discount:
        return
    if reference_price < ZENLOCK_MIN_REFERENCE_EUR:
        stats['skipped_reference_too_low'] = stats.get('skipped_reference_too_low', 0) + 1
        return  # giocatore "quasi gratis", sconto% e' rumore per costruzione qui
    if (reference_price - price_eur) < ZENLOCK_MIN_DISCOUNT_EUR:
        stats['skipped_diff_too_small'] = stats.get('skipped_diff_too_small', 0) + 1
        return  # sconto% alto ma differenza assoluta trascurabile, non un vero mispricing
    if classic_looks_cheap_everywhere(buckets, season_type, price_eur):
        stats['skipped_cheap_sibling'] = stats.get('skipped_cheap_sibling', 0) + 1
        return  # classic "scontata" ma l'in_season gemello e' economico uguale/di piu' (Perišić)

    stats['fired'] = stats.get('fired', 0) + 1
    fascia = "normale" if price_eur <= normal_ceiling else "eccezione (carta di valore)"
    # Stesso pattern di link gia' usato e testato dal tracker principale (vedi send_instant_alert
    # in track.py) -- porta direttamente alla scheda della carta sul market Sorare, per la
    # verifica rapida prima di comprare.
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    link = f"{base_link}?card={card_slug}" if card_slug else base_link
    msg = (f"🎯 <b>Modello ZenLock</b> -- {player_name} [{season_type}]\n\n"
           f"Prezzo: {price_eur:.2f}EUR (fascia {fascia})\n"
           f"Prossimo annuncio piu' economico: {reference_price:.2f}EUR ({n_comparables} comparabili)\n"
           f"Sconto: {discount:.1%} (soglia richiesta {required_discount:.0%})\n\n"
           f"👉 <b><a href='{link}'>APRI SU SORARE</a></b> 👈")
    track.log(f"[modello zenlock] MATCH -- {player_name} [{season_type}] {price_eur:.2f}EUR, "
              f"sconto {discount:.1%} su prossimo annuncio {reference_price:.2f}EUR (n={n_comparables})")
    # FIX 17/07 (v4, caso Barreiro -- diagnostica temporanea, rimuovere dopo verifica): l'utente
    # ha verificato a mano che il mercato reale aveva piu' annunci economici (non Early Access,
    # a suo dire) di quanti ne vedeva get_bucket_prices (5). Logghiamo la lista grezza completa
    # (prezzo, slug carta) di TUTTI i comparabili che la nostra query ha effettivamente visto, per
    # poterla confrontare 1:1 col mercato reale sul prossimo match e capire se manca un pezzo
    # (bug di paginazione/bucket) o se erano davvero solo 5 in quel preciso istante.
    track.log(f"[modello zenlock] DEBUG comparabili grezzi per {player_slug}/{season_type}: "
              f"{others_raw}")
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
    track.reset_currency_branch_stats()  # stesso motivo del tracker principale: azzera eventuali
    # chiamate precedenti (es. diagnostic_dump_missing_offer) cosi' il conteggio riflette solo
    # questo ascolto.
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
                  f"{stats.get('skipped_no_comparable', 0)}, scartate per riferimento troppo basso: "
                  f"{stats.get('skipped_reference_too_low', 0)}, scartate per differenza assoluta "
                  f"troppo piccola: {stats.get('skipped_diff_too_small', 0)}, scartate per gemello "
                  f"in_season altrettanto economico: {stats.get('skipped_cheap_sibling', 0)}")
        track.log(f"[modello zenlock] [diagnostica valute] branch usati in "
                  f"eur_price_from_amounts questa esecuzione: {track.get_currency_branch_stats()}")

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
    # NOTA STORICA (17/07): qui c'era un diagnostico temporaneo per il caso "module 'track' has
    # no attribute 'get_eth_rate'" -- causa trovata (track.py su GitHub era stato sovrascritto
    # per sbaglio col contenuto di questo stesso script) e file ripristinato dall'utente.
    # Diagnostico rimosso dopo conferma che il run seguente funzionava di nuovo.
    eth_rate = track.get_eth_rate()

    if ZENLOCK_DIAGNOSTIC_PLAYER_SLUG:
        track.diagnostic_dump_missing_offer(ZENLOCK_DIAGNOSTIC_PLAYER_SLUG)

    track.log(f"[modello zenlock] Tasso ETH/EUR: {eth_rate}")
    track.log(f"[modello zenlock] Ascolto per {ZENLOCK_LISTEN_SECONDS} secondi "
              f"(soglie: classic <={ZENLOCK_CEILING_CLASSIC_NORMAL}EUR / in_season "
              f"<={ZENLOCK_CEILING_IN_SEASON_NORMAL}EUR, sconto min "
              f"{ZENLOCK_DISCOUNT_NORMAL:.0%})...")
    run_zenlock_listener(eth_rate)
    track.log("[modello zenlock] esecuzione terminata.")
