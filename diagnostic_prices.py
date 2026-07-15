import os
import json
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Caso segnalato dall'utente: il bot ha visto solo 2.65EUR e 3.52EUR come primo/secondo
# prezzo, ma sul sito esistono chiaramente anche annunci a 2.76EUR e 3.00EUR nel mezzo.
# Vogliamo l'elenco COMPLETO e non filtrato per capire perche' vengono esclusi.
TEST_SLUG = 'arnau-tenas'


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
    r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
    return r.status_code, r.json()


QUERY = """
query DebugOffers($slug: String!, $n: Int!) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n) {
      nodes {
        status
        receiverSide { amounts { eurCents wei } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            sportSeason { name }
          }
        }
      }
    }
  }
}
"""


def main():
    log(f"Diagnostica dettagliata -- test slug: {TEST_SLUG}")
    status, data = graphql_query(QUERY, {"slug": TEST_SLUG, "n": 100})
    log(f"HTTP status: {status}")
    if data.get('errors'):
        log(f"ERRORI: {data['errors']}")
        return
    nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {}).get('nodes') or []
    log(f"Trovati {len(nodes)} nodi totali (nessun filtro applicato)")
    log("=" * 70)
    for i, node in enumerate(nodes):
        status_val = node.get('status')
        amounts = (node.get('receiverSide') or {}).get('amounts') or {}
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        card_info = []
        for c in cards:
            season = (c.get('sportSeason') or {}).get('name')
            card_info.append(
                f"slug={c.get('slug')} rarity={c.get('rarityTyped')} sport={c.get('sport')} season={season}"
            )
        log(f"[{i}] status={status_val} eurCents={amounts.get('eurCents')} wei={amounts.get('wei')} "
            f"cards=[{'; '.join(card_info) if card_info else 'NESSUNA CARTA'}]")
    log("Diagnostica terminata.")


if __name__ == "__main__":
    main()
