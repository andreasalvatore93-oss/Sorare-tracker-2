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
    ("I: liveSingleSaleOffers con struttura offer completa (come subscription)", """
    query I($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, last: 10) {
          nodes {
            id
            status
            receiverSide { amounts { eurCents wei } }
            senderSide {
              anyCards { slug rarityTyped sport }
            }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("J: liveSingleSaleOffers con filtro rarity", """
    query J($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, rarity: limited, last: 10) {
          nodes {
            id
            status
            receiverSide { amounts { eurCents wei } }
            senderSide {
              anyCards { slug rarityTyped sport }
            }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("K: liveSingleSaleOffers con sortBy PRICE_ASC", """
    query K($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, last: 10, sortBy: PRICE_ASC) {
          nodes {
            id
            receiverSide { amounts { eurCents wei } }
          }
        }
      }
    }
    """, {"slug": TEST_SLUG}),

    ("L: liveSingleSaleOffers globale (senza playerSlug) per vedere la forma", """
    query L {
      tokens {
        liveSingleSaleOffers(last: 3) {
          nodes {
            id
            status
            receiverSide { amounts { eurCents wei } }
            senderSide {
              anyCards { slug rarityTyped sport anyPlayer { slug displayName } }
            }
          }
        }
      }
    }
    """, None),
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
