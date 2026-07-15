import os
import json
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Giocatore/carta noti per essere attualmente in vendita a prezzi diversi (usiamo Evander,
# gia' verificato manualmente: prezzo minimo reale attuale = 18.00EUR).
TEST_SLUG = 'evander-da-silva-ferreira'


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def graphql_query(query, variables=None):
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {"query": query, "variables": variables or {}}
    try:
        r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        return r.status_code, r.json()
    except Exception as e:
        return None, {"exception": str(e)}


CANDIDATES = [
    ("A: anyPlayer.cards(onSale, sortBy PRICE_ASC)", """
    query A($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, sortBy: PRICE_ASC, first: 5) {
          nodes { slug }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("B: anyPlayer.cards(onSale, orderBy PRICE_ASC)", """
    query B($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, orderBy: PRICE_ASC, first: 5) {
          nodes { slug }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("C: anyPlayer.cards(onSale) no sort, with activeSingleSaleOffer", """
    query C($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, first: 10) {
          nodes {
            slug
            activeSingleSaleOffer { amounts { eurCents } }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("D: anyPlayer.cards(onSale) with latestPublicOffer", """
    query D($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, first: 10) {
          nodes {
            slug
            latestPublicOffer { amounts { eurCents } }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("E: anyPlayer.cards(onSale) with liveSingleSaleOffer", """
    query E($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, first: 10) {
          nodes {
            slug
            liveSingleSaleOffer { amounts { eurCents } }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("F: tokens.liveSingleSaleOffers(playerSlug, sortBy)", """
    query F($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, last: 5) {
          nodes {
            id
            amounts { eurCents }
            anyCard { slug }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("G: anyPlayer.cards no filters (see full field list via error)", """
    query G($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, first: 3) {
          nodes { slug price }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("H: anyPlayer.cards with 'onSaleFrom' style price field guess", """
    query H($slug: String!) {
      anyPlayer(slug: $slug) {
        cards(rarity: limited, onSale: true, first: 5) {
          nodes {
            slug
            price
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),
]


def main():
    log(f"Diagnostica prezzi minimi -- test slug: {TEST_SLUG}")
    log("Prezzo minimo reale verificato manualmente su Sorare: 18.00EUR (annuncio di wizzar61)")
    log("=" * 70)
    for name, query, variables in CANDIDATES:
        status, data = graphql_query(query, variables)
        log(f"--- {name} ---")
        log(f"HTTP status: {status}")
        log(json.dumps(data)[:1500])
        log("")
    log("Diagnostica terminata.")


if __name__ == "__main__":
    main()
