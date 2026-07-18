"""
Tracker: Analisi profit carte mie

Scansiona TUTTE le carte dell'utente (eccetto sealed), le confronta col prezzo più basso
del mercato. Se ho un profit (prezzo_acquisto < prezzo_market), manda notifica.

- Ignora carte già analizzate precedentemente
- Mantiene backlog per carte non scannerizzabili (prezzo acquisto non trovato)
- Processa sempre almeno 10 carte NUOVE per run (ignorate non contano nel counter)
- Notifiche in blocchi da 10
"""
import os
import json
from datetime import datetime
import track

MANAGER_SLUG = 'crowss'
TELEGRAM_TOKEN = os.environ.get('BUNDLE_TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('BUNDLE_TELEGRAM_CHAT_ID', '')

BLOCK_SIZE = 10
BLOCK_SEPARATOR = "\n" + "=" * 50 + "\n"

# Salva lo stato delle carte già analizzate
ANALYZED_CARDS_FILE = '.my_cards_profit_analyzed.txt'
# Salva il backlog di carte con prezzo acquisto non trovato
UNSCANNED_BACKLOG_FILE = '.my_cards_profit_backlog.txt'

# Input dal workflow
CARDS_TO_SCAN = int(os.environ.get('MY_CARDS_PROFIT_SCAN_COUNT', '10'))

def log(msg):
    print(f"[my-cards-profit] {msg}")


def load_analyzed_cards():
    """Carica la lista di carte già analizzate."""
    if not os.path.exists(ANALYZED_CARDS_FILE):
        return set()
    try:
        with open(ANALYZED_CARDS_FILE) as f:
            return set(line.strip() for line in f if line.strip())
    except:
        return set()


def save_analyzed_cards(slugs):
    """Salva le carte analizzate (append)."""
    with open(ANALYZED_CARDS_FILE, 'a') as f:
        for slug in slugs:
            f.write(slug + '\n')


def load_backlog():
    """Carica il backlog di carte non scannerizzabili."""
    if not os.path.exists(UNSCANNED_BACKLOG_FILE):
        return {}
    try:
        with open(UNSCANNED_BACKLOG_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_backlog(backlog):
    """Salva il backlog."""
    with open(UNSCANNED_BACKLOG_FILE, 'w') as f:
        json.dump(backlog, f, indent=2)


def get_all_my_cards():
    """Fetch tutte le carte di 'crowss' ECCETTO sealed."""
    log("Ricerca tutte le carte (no sealed)...")

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
            status
            createdAt
            liveSingleSaleOffer {
              amountInCents
            }
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

            for card in hits:
                # Filtra out le carte sealed
                if card.get('status') != 'sealed':
                    all_cards.append(card)

            page += 1
        except Exception as e:
            log(f"Eccezione durante fetch carte pagina {page}: {e}")
            break

    log(f"Trovate {len(all_cards)} carte (escluse sealed)")
    return all_cards


def get_purchase_price(card_slug):
    """Ottieni il prezzo di acquisto dalla cronologia transazioni."""
    query = """
    {
      anyCard(slug: "%s") {
        tokenTransfers(first: 50) {
          edges {
            node {
              createdAt
              buyer {
                slug
              }
              seller {
                slug
              }
              salePrice
            }
          }
        }
      }
    }
    """ % card_slug

    try:
        data = track.graphql_query(query, {})
        if data.get('errors'):
            return None

        transfers = (data.get('data', {}).get('anyCard', {}).get('tokenTransfers', {})
                    .get('edges', []))

        # Cerca la transazione dove buyer == crowss (l'acquisto)
        for transfer in transfers:
            node = transfer.get('node', {})
            buyer = node.get('buyer', {}).get('slug', '')
            if buyer.lower() == 'crowss':
                # Trovato l'acquisto
                price_str = node.get('salePrice', '')
                if price_str:
                    try:
                        return float(price_str)
                    except:
                        return None
        return None
    except Exception as e:
        log(f"Eccezione durante ricerca prezzo acquisto per {card_slug}: {e}")
        return None


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
    """Scansiona le carte e calcola profit."""
    log(f"Inizio scan profit ({CARDS_TO_SCAN} carte nuove)...")

    analyzed = load_analyzed_cards()
    backlog = load_backlog()

    all_cards = get_all_my_cards()
    if not all_cards:
        log("Nessuna carta trovata")
        return

    # Ordina per data più recente (nuove carte prima)
    all_cards.sort(key=lambda c: c.get('createdAt', ''), reverse=True)

    profitable = []
    newly_analyzed = []
    updated_backlog = backlog.copy()

    processed_count = 0

    for card in all_cards:
        card_slug = card.get('slug')

        # Se già analizzata, salta (non conteggia)
        if card_slug in analyzed:
            log(f"⏭️ {card_slug} - già analizzata, ignoro")
            continue

        # Se raggiunto il numero di carte da scannerizzare, stop
        if processed_count >= CARDS_TO_SCAN:
            log(f"Limite {CARDS_TO_SCAN} carte raggiunto")
            break

        processed_count += 1
        newly_analyzed.append(card_slug)

        log(f"Analizzando ({processed_count}/{CARDS_TO_SCAN}): {card_slug}")

        # Ottieni prezzo di acquisto
        purchase_price = get_purchase_price(card_slug)
        if purchase_price is None:
            log(f"  ⚠️ Prezzo acquisto non trovato → backlog")
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
                'purchase_price': purchase_price,
                'market_price': market_price,
                'profit': profit,
                'profit_percent': profit_percent,
                'season': card.get('sportSeason', {}).get('name', 'N/A'),
                'in_season': card.get('inSeasonEligible'),
            })
        else:
            log(f"  ❌ No profit: acquistato {purchase_price:.2f}€, market {market_price:.2f}€ "
                f"({profit_percent:+.1f}%)")

    # Salva stato
    if newly_analyzed:
        save_analyzed_cards(newly_analyzed)
        log(f"Salvate {len(newly_analyzed)} carte analizzate")

    save_backlog(updated_backlog)
    if updated_backlog:
        log(f"Backlog aggiornato: {len(updated_backlog)} carte con problema")

    if not profitable:
        log("Nessuna carta con profit trovata")
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
            msg += (
                f"<b>{card['slug']}</b>\n"
                f"Acquistato: {card['purchase_price']:.2f}€\n"
                f"Market min: {card['market_price']:.2f}€\n"
                f"<b>Profit: +{card['profit']:.2f}€ ({card['profit_percent']:+.1f}%)</b>\n"
                f"Stagione: {season_label}\n"
                f"👉 <a href='https://sorare.com/it/football/market/shop/{card['slug']}'>Vedi sul market</a>\n"
                f"\n"
            )

        msg = msg.rstrip() + BLOCK_SEPARATOR
        track.send_telegram_msg(msg, token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
        log(f"Notifica blocco {block_num} inviata")


if __name__ == '__main__':
    run_profit_scan()
    log("Esecuzione terminata.")
