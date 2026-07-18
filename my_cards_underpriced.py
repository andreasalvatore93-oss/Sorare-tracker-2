"""
Tracker: Carte mie in vendita vs prezzo mercato

Scansiona SOLO le carte dell'utente attualmente in vendita, le confronta col prezzo
più basso del mercato per la stessa carta. Se il mio prezzo è superiore al mercato,
manda notifica 🔴 (pallino rosso).

Notifiche in blocchi da 10.
"""
import os
import json
from collections import defaultdict
import track

MANAGER_SLUG = 'crowss'
TELEGRAM_TOKEN = os.environ.get('BUNDLE_TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('BUNDLE_TELEGRAM_CHAT_ID', '')

BLOCK_SIZE = 10
BLOCK_SEPARATOR = "\n" + "=" * 50 + "\n"

def log(msg):
    print(f"[my-cards-underpriced] {msg}")


def get_my_cards_for_sale():
    """Fetch tutte le carte di 'crowss' attualmente in vendita (liveSingleSaleOffer != null)."""
    log("Ricerca carte in vendita...")

    query = """
    {
      manager(slug: "crowss") {
        ownedCards(first: 100, filter: {onSale: true}) {
          edges {
            node {
              slug
              sport
              rarity
              inSeasonEligible
              seasonYear
              liveSingleSaleOffer {
                amountInCents
                currencyCode
              }
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """

    all_cards = []
    has_next = True
    cursor = None

    while has_next:
        try:
            data = track.graphql_query(query, {"cursor": cursor} if cursor else {})
            if data.get('errors'):
                log(f"Errore GraphQL: {data['errors']}")
                break

            edges = (data.get('data', {}).get('manager', {}).get('ownedCards', {}).get('edges', []))
            all_cards.extend([e['node'] for e in edges])

            page_info = (data.get('data', {}).get('manager', {}).get('ownedCards', {}).get('pageInfo', {}))
            has_next = page_info.get('hasNextPage', False)
            cursor = page_info.get('endCursor')
        except Exception as e:
            log(f"Eccezione durante fetch carte: {e}")
            break

    log(f"Trovate {len(all_cards)} carte in vendita")
    return all_cards


def get_market_min_price(card_slug, sport, rarity, season_year):
    """Ottieni il prezzo più basso del mercato per questa carta."""
    query = """
    {
      liveOffers(filter: {cardSlugs: ["%s"]}) {
        edges {
          node {
            amountInCents
            currencyCode
            card {
              slug
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

        offers = data.get('data', {}).get('liveOffers', {}).get('edges', [])
        if offers:
            min_offer = min(offers, key=lambda e: e['node']['amountInCents'])
            amount_cents = min_offer['node']['amountInCents']
            currency = min_offer['node']['currencyCode']
            # Converti in EUR se necessario
            if currency == 'EUR':
                return amount_cents / 100
            elif currency == 'WEI':
                eth_rate = track.get_eth_rate()
                return (amount_cents / 1e18) * eth_rate
        return None
    except Exception as e:
        log(f"Eccezione durante fetch market price per {card_slug}: {e}")
        return None


def run_underpriced_scan():
    """Scansiona le carte in vendita e confronta con il mercato."""
    log("Inizio scan carte underpriced...")

    my_cards = get_my_cards_for_sale()
    if not my_cards:
        log("Nessuna carta in vendita")
        return

    underpriced = []

    for card in my_cards:
        card_slug = card.get('slug')
        my_price_cents = card.get('liveSingleSaleOffer', {}).get('amountInCents')
        my_currency = card.get('liveSingleSaleOffer', {}).get('currencyCode')

        if not my_price_cents:
            continue

        # Converti il mio prezzo in EUR
        if my_currency == 'EUR':
            my_price_eur = my_price_cents / 100
        elif my_currency == 'WEI':
            eth_rate = track.get_eth_rate()
            my_price_eur = (my_price_cents / 1e18) * eth_rate
        else:
            continue

        # Ottieni il prezzo più basso del mercato
        market_price_eur = get_market_min_price(
            card_slug,
            card.get('sport'),
            card.get('rarity'),
            card.get('seasonYear')
        )

        if market_price_eur is None:
            continue

        # Se il mio prezzo è maggiore del market → underpriced
        if my_price_eur > market_price_eur:
            diff = my_price_eur - market_price_eur
            diff_percent = (diff / market_price_eur) * 100

            underpriced.append({
                'slug': card_slug,
                'my_price': my_price_eur,
                'market_price': market_price_eur,
                'diff': diff,
                'diff_percent': diff_percent,
                'season': card.get('seasonYear'),
                'in_season': card.get('inSeasonEligible'),
            })
            log(f"🔴 {card_slug}: mio {my_price_eur:.2f}€ vs market {market_price_eur:.2f}€ "
                f"({diff_percent:+.1f}%)")

    if not underpriced:
        log("Nessuna carta underpriced")
        return

    # Manda notifiche in blocchi da BLOCK_SIZE
    log(f"Totale carte underpriced: {len(underpriced)}")
    send_notifications(underpriced)


def send_notifications(underpriced_cards):
    """Manda notifiche Telegram in blocchi da BLOCK_SIZE."""
    blocks = [underpriced_cards[i:i+BLOCK_SIZE] for i in range(0, len(underpriced_cards), BLOCK_SIZE)]

    for block_num, block in enumerate(blocks, 1):
        msg = f"<b>🔴 Carte Underpriced (Blocco {block_num}/{len(blocks)})</b>\n\n"

        for card in block:
            season_label = f"{card['season']} {'(In Season)' if card['in_season'] else '(Classic)'}"
            msg += (
                f"<b>{card['slug']}</b>\n"
                f"Mio prezzo: <b>{card['my_price']:.2f}€</b>\n"
                f"Market min: {card['market_price']:.2f}€\n"
                f"Differenza: +{card['diff']:.2f}€ ({card['diff_percent']:+.1f}%)\n"
                f"Stagione: {season_label}\n"
                f"👉 <a href='https://sorare.com/it/football/market/shop/{card['slug']}'>Vedi sul market</a>\n"
                f"\n"
            )

        msg = msg.rstrip() + BLOCK_SEPARATOR
        track.send_telegram_msg(msg, token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
        log(f"Notifica blocco {block_num} inviata")


if __name__ == '__main__':
    run_underpriced_scan()
    log("Esecuzione terminata.")
