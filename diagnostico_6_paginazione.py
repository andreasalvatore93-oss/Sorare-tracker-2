import os
import json
import datetime
import requests

# Diagnostico per capire se tokens.liveSingleSaleOffers supporta la paginazione completa
# (stile Relay: totalCount, pageInfo { hasNextPage, hasPreviousPage, startCursor,
# endCursor }, argomento 'before'/'after'). Se si', possiamo scorrere TUTTI gli annunci di
# un giocatore invece di limitarci agli "ultimi N" globali (limite confermato sui casi
# Jonas Urbig e Justin Bijlow: annunci reali piu' economici restavano fuori dalla finestra).
# Sola lettura, nessun rischio.

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Slug gia' confermato funzionante in diagnostici precedenti, usato come baseline sicura
# per verificare l'ESISTENZA dei campi di paginazione (non serve volume alto per questo).
BASELINE_SLUG = 'arnau-tenas-urena'

# Giocatori ad alto volume dove abbiamo GIA' confermato che last:300 non basta -- usati per
# vedere il vero totalCount e se pageInfo segnala effettivamente hasNextPage/hasPreviousPage.
HIGH_VOLUME_SLUGS = ['justin-bijlow', 'jonas-urbig']


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
    r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=20)
    return r.status_code, r.json()


QUERY_WITH_PAGEINFO = """
query PaginationTest($slug: String!, $n: Int!) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n) {
      totalCount
      pageInfo {
        hasNextPage
        hasPreviousPage
        startCursor
        endCursor
      }
      nodes {
        status
      }
    }
  }
}
"""

QUERY_WITH_BEFORE = """
query PaginationBefore($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo {
        hasNextPage
        hasPreviousPage
        startCursor
        endCursor
      }
      nodes {
        status
      }
    }
  }
}
"""


def main():
    log("STEP 1: verifica esistenza campi totalCount/pageInfo (slug baseline noto)")
    log("=" * 70)
    status, data = graphql_query(QUERY_WITH_PAGEINFO, {"slug": BASELINE_SLUG, "n": 5})
    log(f"HTTP {status}")
    log(f"Risposta: {json.dumps(data)[:800]}")
    log("=" * 70)

    log("STEP 2: totalCount/pageInfo su giocatori ad alto volume (last: 300)")
    log("=" * 70)
    cursors = {}
    for slug in HIGH_VOLUME_SLUGS:
        status, data = graphql_query(QUERY_WITH_PAGEINFO, {"slug": slug, "n": 300})
        log(f"[{slug}] HTTP {status}")
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
        if data.get('errors'):
            log(f"[{slug}] errori: {data['errors']}")
        else:
            log(f"[{slug}] totalCount={conn.get('totalCount')}, pageInfo={conn.get('pageInfo')}, "
                f"nodi_restituiti={len(conn.get('nodes') or [])}")
            page_info = conn.get('pageInfo') or {}
            if page_info.get('hasPreviousPage') and page_info.get('startCursor'):
                cursors[slug] = page_info['startCursor']
        log("-" * 70)

    log("STEP 3: prova argomento 'before' per scorrere a una pagina precedente (se disponibile)")
    log("=" * 70)
    if not cursors:
        log("Nessun cursore disponibile dal passo precedente (hasPreviousPage sempre falso "
            "o pageInfo/startCursor non supportati) -- non posso testare 'before' su dati reali, "
            "provo comunque con un cursore fittizio per vedere se l'argomento esiste a livello di schema.")
        for slug in HIGH_VOLUME_SLUGS:
            status, data = graphql_query(QUERY_WITH_BEFORE, {"slug": slug, "n": 300, "cursor": "FAKE_CURSOR"})
            log(f"[{slug}] (cursore finto) HTTP {status}")
            log(f"[{slug}] risposta: {json.dumps(data)[:500]}")
            log("-" * 70)
    else:
        for slug, cursor in cursors.items():
            status, data = graphql_query(QUERY_WITH_BEFORE, {"slug": slug, "n": 300, "cursor": cursor})
            log(f"[{slug}] con cursore reale HTTP {status}")
            conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
            if data.get('errors'):
                log(f"[{slug}] errori: {data['errors']}")
            else:
                log(f"[{slug}] pagina precedente -- totalCount={conn.get('totalCount')}, "
                    f"pageInfo={conn.get('pageInfo')}, nodi_restituiti={len(conn.get('nodes') or [])}")
            log("-" * 70)

    log("Diagnostica terminata.")


if __name__ == "__main__":
    main()
