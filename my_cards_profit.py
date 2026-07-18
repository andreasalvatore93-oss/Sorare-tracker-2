"""
Tracker: Analisi profit carte mie

Scansiona TUTTE le carte dell'utente, le confronta col prezzo più basso del mercato.
Se ho un profit (prezzo_acquisto < prezzo_market), manda notifica.

FIX 18/07 (richiesta esplicita dell'utente, "il bot deve analizzare SEMPRE tutte le carte,
deve ignorare solo quelle che ha già rilevato in profitto"): la versione precedente segnava
come "già analizzata" (e quindi saltava per sempre) OGNI carta processata almeno una volta,
profittevole o no. Rischio reale: una carta in perdita al primo controllo ma che in seguito
sale di prezzo di mercato non veniva MAI più ricontrollata, perdendo l'occasione. Ora si
ignorano SOLO le carte già trovate in profitto e già notificate (non ha senso ri-notificarle
all'infinito) -- tutte le altre (in perdita, o senza prezzo di acquisto disponibile) vengono
sempre rimesse in coda per il prossimo giro. Dato che scansionare 1900+ carte per intero ad
ogni run sarebbe lento, si usa un cursore persistente che avanza di CARDS_TO_SCAN carte ad
ogni run e riparte da capo una volta arrivato in fondo alla lista (rotazione continua) --
cosi' TUTTE le carte vengono ricontrollate nel tempo, non solo le prime N per sempre.

FIX 18/07 (bug prezzo acquisto): la query precedente (anyCard.tokenTransfers con
buyer/seller/salePrice) non esiste nello schema ("Field 'tokenTransfers' doesn't exist on
type 'AnyCardInterface'", suggerimento dell'errore: 'tokenOwner'), quindi ogni carta finiva
sempre in backlog. Sostituita con track.fetch_user_trades(), la stessa query gia' collaudata
in produzione (snipe_pattern_analysis.py) che restituisce TUTTA la cronologia acquisti/vendite
di un manager in un'unica query paginata (molto piu' efficiente di una query per carta).
"""
import os
import json
from datetime import datetime
import track

MANAGER_SLUG = 'crowss'
# FIX 18/07: track.send_telegram_msg(msg) non accetta kwargs token/chat_id -- legge da
# track.TELEGRAM_TOKEN/track.TELEGRAM_CHAT_ID (i suoi globali di modulo, popolati dalle env
# var TELEGRAM_TOKEN/TELEGRAM_CHAT_ID). Stesso schema di manager_bundle_scan.py: il workflow
# .yml mappa i secret BUNDLE_TELEGRAM_TOKEN/BUNDLE_TELEGRAM_CHAT_ID su QUELLE env var (non su
# BUNDLE_TELEGRAM_TOKEN/BUNDLE_TELEGRAM_CHAT_ID), cosi' i messaggi arrivano nello stesso canale
# del bundle scanner senza bisogno di kwargs custom qui.

BLOCK_SIZE = 10
BLOCK_SEPARATOR = "\n" + "=" * 50 + "\n"

# Salva SOLO le carte gia' trovate in profitto e notificate (skip permanente -- non ha senso
# ri-notificare la stessa carta ad ogni run).
PROFITABLE_FOUND_FILE = '.my_cards_profit_found.txt'
# Cursore persistente: indice da cui riprendere la scansione al prossimo run (rotazione
# continua sulla lista di carte NON ancora trovate in profitto, cosi' nel tempo si ricontrollano
# tutte, non solo le prime N per sempre).
CURSOR_FILE = '.my_cards_profit_cursor.txt'
# Backlog solo informativo (carte per cui non si e' trovato un prezzo di acquisto nell'ultimo
# tentativo) -- NON usato per saltare carte, solo per diagnostica nei log.
UNSCANNED_BACKLOG_FILE = '.my_cards_profit_backlog.txt'

# Input dal workflow
CARDS_TO_SCAN = int(os.environ.get('MY_CARDS_PROFIT_SCAN_COUNT', '10'))
# Finestra e paginazione per lo storico acquisti (track.fetch_user_trades) -- di default molto
# ampia (anni), perche' ci serve la cronologia acquisti COMPLETA per calcolare il profit, non
# solo gli ultimi giorni come nell'uso originale (snipe pattern) di questa funzione.
PURCHASE_HISTORY_WINDOW_DAYS = int(os.environ.get('MY_CARDS_PROFIT_HISTORY_DAYS', '3650'))
PURCHASE_HISTORY_MAX_PAGES = int(os.environ.get('MY_CARDS_PROFIT_HISTORY_MAX_PAGES', '100'))


def log(msg):
    print(f"[my-cards-profit] {msg}")


def load_profitable_found():
    """Carica lo slug delle carte gia' trovate in profitto (skip permanente)."""
    if not os.path.exists(PROFITABLE_FOUND_FILE):
        return set()
    try:
        with open(PROFITABLE_FOUND_FILE) as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def save_profitable_found(slugs):
    """Aggiunge slug al file delle carte gia' trovate in profitto (append)."""
    if not slugs:
        return
    with open(PROFITABLE_FOUND_FILE, 'a') as f:
        for slug in slugs:
            f.write(slug + '\n')


def load_cursor():
    """Carica l'indice da cui riprendere la scansione."""
    if not os.path.exists(CURSOR_FILE):
        return 0
    try:
        with open(CURSOR_FILE) as f:
            return int(f.read().strip() or '0')
    except Exception:
        return 0


def save_cursor(cursor):
    """Salva l'indice per il prossimo run."""
    with open(CURSOR_FILE, 'w') as f:
        f.write(str(cursor))


def load_backlog():
    """Carica il backlog (solo informativo) di carte senza prezzo di acquisto trovato."""
    if not os.path.exists(UNSCANNED_BACKLOG_FILE):
        return {}
    try:
        with open(UNSCANNED_BACKLOG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_backlog(backlog):
    """Salva il backlog (solo informativo, non usato per saltare carte)."""
    with open(UNSCANNED_BACKLOG_FILE, 'w') as f:
        json.dump(backlog, f, indent=2)


def get_all_my_cards():
    """Fetch tutte le carte di 'crowss'.
    FIX 18/07: 'status' non esiste su AnyCardInterface (l'errore GraphQL bloccava l'intera
    query, quindi 0 carte trovate ad ogni run) -- rimosso. 'amountInCents' su liveSingleSaleOffer
    non esiste nemmeno lui (stesso bug gia' corretto in my_cards_underpriced.py) ed era comunque
    inutilizzato qui, rimosso anche quello. 'createdAt' NEMMENO esiste su AnyCardInterface
    (stesso errore, stesso blocco) -- rimosso anche quello: l'ordinamento "piu' recenti prima"
    e' gia' garantito server-side da sorts: user_owner.from DESC, non serve un campo data
    lato client per rifare lo stesso ordinamento in Python. Introspection disabilitata: senza
    un campo/stato "sealed" noto e funzionante, per ora non filtriamo le carte sealed (rischio
    di includerne qualcuna per errore e' preferibile a bloccare l'intero tracker su un campo
    indovinato)."""
    log("Ricerca tutte le carte...")

    query = """
    query MyAllCards($userSlug: String!, $page: Int!, $pageSize: Int!) {
      user(slug: $userSlug) {
        searchCards(
          rarity: limited
          sport: FOOTBALL
          query: ""
          page: $page
          pageSize: $pageSize
          sorts: [{field: "user_owner.from", direction: DESC}]
        ) {
          hits {
            slug
            sport
            rarityTyped
            inSeasonEligible
            sportSeason { name }
            anyPlayer { slug }
          }
          nbHits
        }
      }
    }
    """

    all_cards = []
    page = 1
    max_pages = 100

    while page <= max_pages:
        try:
            data = track.graphql_query(query, {
                "userSlug": "crowss",
                "page": page,
                "pageSize": 100
            })
            if data.get('errors'):
                log(f"Errore GraphQL: {data['errors']}")
                break

            hits = (data.get('data', {}).get('user', {}).get('searchCards', {}).get('hits', []))
            if not hits:
                break

            all_cards.extend(hits)

            page += 1
        except Exception as e:
            log(f"Eccezione durante fetch carte pagina {page}: {e}")
            break

    log(f"Trovate {len(all_cards)} carte")
    return all_cards


def build_purchase_price_map():
    """Costruisce slug_carta -> prezzo_pagato usando track.fetch_user_trades (query bulk gia'
    collaudata in produzione, vedi snipe_pattern_analysis.py) invece di una query per carta.
    Solo le transazioni role='buy' con un prezzo attribuibile (esclusi i bundle multi-carta,
    dove il prezzo aggregato non e' scomponibile per singola carta -- stesso limite noto e
    documentato in track.py) entrano nella mappa. Se la stessa carta compare piu' volte
    (comprata, rivenduta, ricomprata), vince l'acquisto piu' recente (i nodi sono ordinati dal
    piu' recente al piu' vecchio da fetch_user_trades, quindi il primo trovato per slug vince)."""
    log(f"Ricerca cronologia acquisti (finestra {PURCHASE_HISTORY_WINDOW_DAYS} giorni, "
        f"max {PURCHASE_HISTORY_MAX_PAGES} pagine)...")
    eth_rate = track.get_eth_rate()
    try:
        trades = track.fetch_user_trades(MANAGER_SLUG, PURCHASE_HISTORY_WINDOW_DAYS, eth_rate,
                                          max_pages=PURCHASE_HISTORY_MAX_PAGES)
    except Exception as e:
        log(f"Eccezione durante fetch cronologia acquisti: {e}")
        return {}

    price_map = {}
    bundle_skipped = 0
    for t in trades:
        if t.get('role') != 'buy':
            continue
        card_slug = t.get('card_slug')
        if not card_slug:
            continue
        if t.get('price') is None:
            # Acquisto in bundle (piu' carte, un unico prezzo aggregato) -- non attribuibile
            # alla singola carta, stesso principio gia' usato in track.py.
            bundle_skipped += 1
            continue
        if card_slug not in price_map:
            price_map[card_slug] = t['price']

    log(f"Cronologia acquisti: {len(trades)} transazioni totali, {len(price_map)} carte con "
        f"prezzo di acquisto attribuibile, {bundle_skipped} scartate (acquisti in bundle)")
    return price_map


def get_market_min_price(card_slug, in_season_eligible):
    """Ottieni il prezzo più basso del mercato per il giocatore di questa carta, tra gli
    annunci aperti con la stessa categoria (in_season/classic) -- stesso schema query di
    track.py (fetch_all_live_offers/get_live_min_offer): la carta messa in vendita sta in
    senderSide.anyCards, il prezzo chiesto sta in receiverSide.amounts. receiverSide.anyCards
    NON vuoto significa scambio carta-per-carta (nessun prezzo in denaro, va escluso).
    FIX 18/07: la versione precedente cercava card_slug dentro receiverSide.anyCards (il lato
    del pagamento, quasi sempre vuoto per una vendita a prezzo fisso) invece che in
    senderSide.anyCards (il lato della carta venduta) -- il match falliva quasi sempre,
    lasciando il prezzo di mercato sempre a None."""
    query = """
    {
      anyCard(slug: "%s") {
        anyPlayer { slug }
      }
    }
    """ % card_slug

    try:
        data = track.graphql_query(query, {})
        if data.get('errors') or not data.get('data', {}).get('anyCard'):
            return None

        player_slug = (data.get('data', {}).get('anyCard', {})
                      .get('anyPlayer', {}).get('slug'))
        if not player_slug:
            return None

        offers_query = """
        query LiveOffers($slug: String!, $n: Int!) {
          tokens {
            liveSingleSaleOffers(playerSlug: $slug, last: $n) {
              nodes {
                status
                receiverSide {
                  amounts { eurCents }
                  anyCards { slug }
                }
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

        data = track.graphql_query(offers_query, {"slug": player_slug, "n": 50})
        if data.get('errors'):
            return None

        nodes = (data.get('data', {}).get('tokens', {})
                .get('liveSingleSaleOffers', {}).get('nodes', []))

        if not nodes:
            return None

        prices = []
        for node in nodes:
            if node.get('status') != 'opened':
                continue
            # scambio carta-per-carta (nessun prezzo in denaro): escluso, stesso filtro di track.py
            if (node.get('receiverSide') or {}).get('anyCards'):
                continue
            sender_cards = (node.get('senderSide') or {}).get('anyCards') or []
            match = None
            for c in sender_cards:
                if c.get('rarityTyped') != 'limited':
                    continue
                if c.get('sport') != 'FOOTBALL':
                    continue
                if c.get('inSeasonEligible') != in_season_eligible:
                    continue
                match = c
                break
            if not match:
                continue
            eur_cents = node.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if eur_cents:
                prices.append(eur_cents / 100)

        return min(prices) if prices else None
    except Exception as e:
        log(f"Eccezione durante fetch market price per {card_slug}: {e}")
        return None


def run_profit_scan():
    """Scansiona le carte e calcola profit. Ignora SOLO le carte gia' trovate in profitto in
    un run precedente (gia' notificate) -- tutte le altre vengono sempre rimesse in coda,
    tramite un cursore rotante, cosi' una carta prima in perdita che poi diventa profittevole
    non viene mai persa."""
    log(f"Inizio scan profit ({CARDS_TO_SCAN} carte per run)...")

    profitable_found = load_profitable_found()
    cursor = load_cursor()

    all_cards = get_all_my_cards()
    if not all_cards:
        log("Nessuna carta trovata")
        return

    # Escludi SOLO le carte gia' trovate in profitto e notificate -- tutte le altre restano
    # candidate per la rotazione (anche quelle gia' controllate in passato senza profit).
    candidates = [c for c in all_cards if c.get('slug') not in profitable_found]
    log(f"{len(all_cards)} carte totali, {len(all_cards) - len(candidates)} gia' trovate in "
        f"profitto (escluse), {len(candidates)} candidate per questo giro")

    if not candidates:
        log("Nessuna carta candidata (tutte gia' trovate in profitto?)")
        return

    # Cursore rotante: riprende da dove si era arrivati, ricomincia da capo se supera la fine
    # della lista -- cosi' nel tempo TUTTE le carte candidate vengono ricontrollate.
    if cursor >= len(candidates):
        cursor = 0

    # Prezzi di acquisto per TUTTE le carte in un colpo solo (query bulk), invece di una query
    # per carta come nella versione precedente (rotta e comunque inefficiente su 1900+ carte).
    purchase_price_map = build_purchase_price_map()

    profitable = []
    newly_profitable_slugs = []
    updated_backlog = {}

    batch = []
    idx = cursor
    while len(batch) < CARDS_TO_SCAN and len(batch) < len(candidates):
        batch.append(candidates[idx])
        idx = (idx + 1) % len(candidates)

    log(f"Batch di questo giro: {len(batch)} carte (da indice {cursor})")

    for i, card in enumerate(batch, 1):
        card_slug = card.get('slug')
        log(f"Analizzando ({i}/{len(batch)}): {card_slug}")

        purchase_price = purchase_price_map.get(card_slug)
        if purchase_price is None:
            log(f"  ⚠️ Prezzo acquisto non trovato")
            updated_backlog[card_slug] = {
                'reason': 'prezzo_acquisto_non_trovato',
                'last_attempt': datetime.now().isoformat(),
            }
            continue

        # Ottieni prezzo market minimo (stessa categoria in_season/classic)
        market_price = get_market_min_price(card_slug, card.get('inSeasonEligible'))
        if market_price is None:
            log(f"  ⚠️ Prezzo market non trovato")
            continue

        # Calcola profit
        profit = market_price - purchase_price
        profit_percent = (profit / purchase_price * 100) if purchase_price > 0 else 0

        if profit > 0:
            log(f"  ✅ PROFIT: acquistato {purchase_price:.2f}€, market {market_price:.2f}€ "
                f"(+{profit:.2f}€, {profit_percent:+.1f}%)")
            profitable.append({
                'slug': card_slug,
                'player_slug': (card.get('anyPlayer') or {}).get('slug'),
                'purchase_price': purchase_price,
                'market_price': market_price,
                'profit': profit,
                'profit_percent': profit_percent,
                'season': card.get('sportSeason', {}).get('name', 'N/A'),
                'in_season': card.get('inSeasonEligible'),
            })
            newly_profitable_slugs.append(card_slug)
        else:
            log(f"  ❌ No profit: acquistato {purchase_price:.2f}€, market {market_price:.2f}€ "
                f"({profit_percent:+.1f}%)")

    # Salva stato: cursore avanzato di quante carte abbiamo effettivamente processato in questo
    # giro (rotazione continua sulla lista candidati, non su all_cards).
    save_cursor(idx)
    log(f"Cursore aggiornato a {idx}/{len(candidates)} (prossimo run riparte da li')")

    if newly_profitable_slugs:
        save_profitable_found(newly_profitable_slugs)
        log(f"Salvate {len(newly_profitable_slugs)} carte in profitto (skip permanente)")

    save_backlog(updated_backlog)
    if updated_backlog:
        log(f"Backlog (solo informativo) di questo giro: {len(updated_backlog)} carte senza "
            f"prezzo di acquisto")

    if not profitable:
        log("Nessuna carta con profit trovata in questo giro")
        return

    log(f"Totale carte con profit: {len(profitable)}")
    send_notifications(profitable)


def send_notifications(profit_cards):
    """Manda notifiche Telegram in blocchi da BLOCK_SIZE."""
    blocks = [profit_cards[i:i+BLOCK_SIZE] for i in range(0, len(profit_cards), BLOCK_SIZE)]

    for block_num, block in enumerate(blocks, 1):
        msg = f"<b>💰 Carte con Profit (Blocco {block_num}/{len(blocks)})</b>\n\n"

        for card in block:
            season_label = f"{card['season']} {'(In Season)' if card['in_season'] else '(Classic)'}"
            # FIX 18/07 (richiesta esplicita, link portava al mercato generale invece che alla
            # carta): stesso schema corretto gia' applicato in my_cards_underpriced.py, verificato
            # in produzione da track.py (send_instant_alert/evaluate_player_offer).
            player_slug = card.get('player_slug')
            if player_slug:
                card_link = (f"https://sorare.com/it/football/market/shop/manager-sales/"
                             f"{player_slug}/limited?card={card['slug']}")
            else:
                card_link = f"https://sorare.com/it/football/market/shop/{card['slug']}"
            msg += (
                f"<b>{card['slug']}</b>\n"
                f"Acquistato: {card['purchase_price']:.2f}€\n"
                f"Market min: {card['market_price']:.2f}€\n"
                f"<b>Profit: +{card['profit']:.2f}€ ({card['profit_percent']:+.1f}%)</b>\n"
                f"Stagione: {season_label}\n"
                f"👉 <a href='{card_link}'>Vedi la carta</a>\n"
                f"\n"
            )

        msg = msg.rstrip() + BLOCK_SEPARATOR
        track.send_telegram_msg(msg)
        log(f"Notifica blocco {block_num} inviata")


if __name__ == '__main__':
    run_profit_scan()
    log("Esecuzione terminata.")
