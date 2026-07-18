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
    query MyCardsForSale($userSlug: String!, $page: Int!, $pageSize: Int!) {
      user(slug: $userSlug) {
        searchCards(
          rarity: limited
          sport: FOOTBALL
          query: ""
          page: $page
          pageSize: $pageSize
        ) {
          hits {
            slug
            sport
            rarityTyped
            inSeasonEligible
            sportSeason { name }
            liveSingleSaleOffer {
              receiverSide {
                amounts { eurCents }
              }
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

            all_cards.extend(hits)
            page += 1
        except Exception as e:
            log(f"Eccezione durante fetch carte pagina {page}: {e}")
            break

    log(f"Trovate {len(all_cards)} carte in vendita")
    return all_cards


def get_market_min_price(card_slug, sport, rarity, season_year):
    """Ottieni il prezzo più basso del mercato per questa carta."""
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
            cards = node.get('receiverSide', {}).get('anyCards', [])
            if any(c.get('slug') == card_slug for c in cards):
                eur_cents = node.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur_cents:
                    prices.append(eur_cents / 100)

        return min(prices) if prices else None
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
    checked_count = 0
    skipped_no_price = 0
    skipped_no_market = 0

    for idx, card in enumerate(my_cards, 1):
        card_slug = card.get('slug')
        sale_offer = card.get('liveSingleSaleOffer')

        if not sale_offer:
            skipped_no_price += 1
            continue

        eur_cents = sale_offer.get('receiverSide', {}).get('amounts', {}).get('eurCents')

        if not eur_cents:
            skipped_no_price += 1
            continue

        my_price_eur = eur_cents / 100

        # Ottieni il prezzo più basso del mercato
        market_price_eur = get_market_min_price(
            card_slug,
            card.get('sport'),
            card.get('rarityTyped'),
            card.get('sportSeason', {}).get('name', '')
        )

        if market_price_eur is None:
            skipped_no_market += 1
            continue

        checked_count += 1

        # Diagnostica ogni 100 carte
        if checked_count % 100 == 0:
            log(f"  📊 Controllate {checked_count} carte, underpriced trovate: {len(underpriced)}")

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
                'season': card.get('sportSeason', {}).get('name', 'N/A'),
                'in_season': card.get('inSeasonEligible'),
            })
            log(f"🔴 {card_slug}: mio {my_price_eur:.2f}€ vs market {market_price_eur:.2f}€ "
                f"({diff_percent:+.1f}%)")
        else:
            # Log sample di carte OK (ogni 500)
            if checked_count % 500 == 0:
                log(f"  ✅ Sample: {card_slug}: mio {my_price_eur:.2f}€ ≤ market {market_price_eur:.2f}€ (OK)")

    # Statistiche finali
    log(f"\n📈 Statistiche scansione:")
    log(f"  Totale carte in vendita: {len(my_cards)}")
    log(f"  Carte effettivamente controllate: {checked_count}")
    log(f"  Carte scartate (no prezzo mio): {skipped_no_price}")
    log(f"  Carte scartate (no market price): {skipped_no_market}")
    log(f"  Carte underpriced trovate: {len(underpriced)}")

    if not underpriced:
        log("Nessuna carta underpriced")
        return

    # Manda notifiche in blocchi da BLOCK_SIZE
    log(f"\n💬 Invio {len(underpriced)} carte via Telegram...")
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
