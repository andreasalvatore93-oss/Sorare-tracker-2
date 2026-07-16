import os
import json
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Caso segnalato: la riverifica pre-notifica delle aste (auctions_ws_listener.py) prova a
# leggere lo stato REALE di una singola asta prima di notificare, ma tokens.liveAuctions NON
# accetta un filtro playerSlug ("Field 'liveAuctions' doesn't accept argument 'playerSlug'",
# scoperto in produzione sul caso Roman Celentano). Ci serve un modo per recuperare UNA
# specifica asta dato il suo id (formato "EnglishAuction:1234", visto nei log/nel database
# auctions.db) senza dover scaricare/scorrere la lista globale di TUTTE le aste live della
# piattaforma (troppo dispersiva e costosa).
#
# COME USARLO: prendi un auction_id REALE e ancora aperto dai log dell'ultima esecuzione di
# auctions_ws_listener.py (una riga tipo "EnglishAuction:XXXXXXX" comparira' nei log, oppure
# guarda la colonna auction_id in auctions.db -> tabella notified_auctions/decisions_log per
# un'asta recente), incollalo qui sotto in TEST_AUCTION_ID, poi esegui questo script con le
# stesse variabili d'ambiente SORARE_COOKIE/SORARE_CSRF usate dal bot vero. Copiami tutto
# l'output.
TEST_AUCTION_ID = "EnglishAuction:e43fb964-8cb5-4185-9104-ce2e409c41b2"


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


# --- Tentativo 1 (il piu' promettente): l'id "EnglishAuction:1234" e' gia' nel formato
# GraphQL "Global ID" standard (Relay). Molti schemi GraphQL, incluso probabilmente quello di
# Sorare, espongono un campo generico node(id: ID!) per recuperare QUALSIASI entita' dal suo
# id globale, senza bisogno di sapere in anticipo il tipo o un filtro dedicato. Se funziona,
# e' la soluzione ideale: una query mirata su un'unica asta, niente liste da scorrere. ---
NODE_QUERY = """
query GetAuctionByNodeId($id: ID!) {
  node(id: $id) {
    id
    __typename
    ... on TokenAuction {
      currentPrice
      minNextBid
      endDate
    }
  }
}
"""

# --- Tentativo 2 (fallback): dump grezzo delle ultime N aste live globali (query gia'
# confermata funzionante, usata da auctions.py), per vedere manualmente se il nostro
# auction_id compare tra queste e farsi un'idea di quanto e' "affollata" la lista globale. ---
LIVE_AUCTIONS_QUERY = """
query DebugLiveAuctions($n: Int!) {
  tokens {
    liveAuctions(last: $n) {
      nodes {
        id
        currentPrice
        minNextBid
        endDate
      }
    }
  }
}
"""


def main():
    log(f"Diagnostica riverifica asta singola -- test id: {TEST_AUCTION_ID}")
    log("=" * 70)

    log("TENTATIVO 1: query node(id: ...) -- lookup diretto per id globale")
    status, data = graphql_query(NODE_QUERY, {"id": TEST_AUCTION_ID})
    log(f"HTTP status: {status}")
    log(f"Risposta completa: {json.dumps(data, indent=2)}")
    if not data.get('errors') and (data.get('data') or {}).get('node'):
        log(">>> FUNZIONA! Usa questa query (node(id:...)) per la riverifica pre-notifica.")
    else:
        log(">>> Non ha funzionato (vedi errori/risposta sopra). Passo al tentativo 2.")

    log("=" * 70)
    log("TENTATIVO 2: dump delle ultime 200 aste live globali (nessun filtro)")
    status2, data2 = graphql_query(LIVE_AUCTIONS_QUERY, {"n": 200})
    log(f"HTTP status: {status2}")
    if data2.get('errors'):
        log(f"ERRORI: {data2['errors']}")
    else:
        nodes = (((data2.get('data') or {}).get('tokens') or {}).get('liveAuctions') or {}).get('nodes') or []
        log(f"Trovate {len(nodes)} aste live (ultime 200 globali)")
        ids = [n.get('id') for n in nodes]
        if TEST_AUCTION_ID in ids:
            log(f">>> Il nostro auction_id E' presente tra le ultime 200 globali (posizione {ids.index(TEST_AUCTION_ID)}).")
        else:
            log(">>> Il nostro auction_id NON e' tra le ultime 200 globali "
                "(la lista globale non e' un modo affidabile per trovare un'asta specifica).")

    log("=" * 70)
    log("Diagnostica terminata. Copia TUTTO l'output qui sopra.")


if __name__ == "__main__":
    main()
