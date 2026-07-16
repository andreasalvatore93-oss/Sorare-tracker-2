import os
import json
import base64
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
TEST_AUCTION_ID = "EnglishAuction:647cd6ff-6b86-4ffc-a72c-f91baa26cbed"  # Heung-min Son, 16/07 05:27:48
TEST_CARD_SLUG = "heung-min-son-2026-limited-811"  # stessa riga di log, stessa asta


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

    log("TENTATIVO 1: query node(id: ...) -- id in chiaro")
    status, data = graphql_query(NODE_QUERY, {"id": TEST_AUCTION_ID})
    log(f"HTTP status: {status}")
    log(f"Risposta completa: {json.dumps(data, indent=2)}")
    node_ok = not data.get('errors') and (data.get('data') or {}).get('node')
    if node_ok:
        log(">>> FUNZIONA! Usa questa query (node(id:...), id in chiaro) per la riverifica pre-notifica.")
    else:
        log(">>> Non ha funzionato con l'id in chiaro. Passo al tentativo 1b (id codificato in base64).")

    if not node_ok:
        log("=" * 70)
        log("TENTATIVO 1b: query node(id: ...) -- id codificato in base64")
        # Molti schemi GraphQL in stile Relay vogliono il "Global ID" codificato in base64
        # (es. base64("TokenAuction:1234")), non la stringa in chiaro "EnglishAuction:1234"
        # che l'evento WebSocket ci restituisce -- il tentativo 1 ha confermato che il campo
        # node ESISTE (l'errore parla del formato dell'id, non di un campo inesistente),
        # quindi vale la pena provare questa codifica prima di arrendersi.
        encoded_id = base64.b64encode(TEST_AUCTION_ID.encode()).decode()
        log(f"Id in chiaro: {TEST_AUCTION_ID}")
        log(f"Id codificato in base64: {encoded_id}")
        status1b, data1b = graphql_query(NODE_QUERY, {"id": encoded_id})
        log(f"HTTP status: {status1b}")
        log(f"Risposta completa: {json.dumps(data1b, indent=2)}")
        if not data1b.get('errors') and (data1b.get('data') or {}).get('node'):
            log(">>> FUNZIONA! Usa node(id:...) con l'id codificato in base64 (TypeName:internalId) "
                "per la riverifica pre-notifica.")
        else:
            log(">>> Non ha funzionato nemmeno in base64 (vedi errori sopra). Passo al tentativo 2.")

    log("=" * 70)
    log("TENTATIVO 3: query per carta (anyCard/card/footballCard(slug: ...)) -- proviamo piu' "
        "nomi di campo, dato che anyPlayer(slug:...) e' gia' confermato funzionante altrove")

    # Aggiornamento: anyCard(slug: ...) ESISTE davvero (l'errore precedente era solo sul nome
    # del sotto-campo "activeAuction", inventato da noi -- il messaggio d'errore ha anche
    # rivelato il nome esatto del tipo: AnyCardInterface). Prima di continuare a indovinare
    # sotto-campi a caso, chiediamo direttamente a GraphQL l'elenco dei campi di quel tipo:
    # l'introspezione SUL SINGOLO TIPO (__type) a volte funziona anche quando quella globlale
    # (__schema) e' disabilitata.
    log("--- prima: introspezione mirata su AnyCardInterface (__type) ---")
    introspect_query = """
    query IntrospectAnyCard($name: String!) {
      __type(name: $name) {
        name
        fields {
          name
          type { name kind ofType { name kind } }
        }
      }
    }
    """
    status_i, data_i = graphql_query(introspect_query, {"name": "AnyCardInterface"})
    log(f"HTTP status: {status_i}")
    log(f"Risposta: {json.dumps(data_i, indent=2)}")
    field_names_from_introspection = []
    type_info = (data_i.get('data') or {}).get('__type')
    if type_info:
        field_names_from_introspection = [f['name'] for f in (type_info.get('fields') or [])]
        log(f">>> Introspezione riuscita! Campi disponibili su AnyCardInterface: {field_names_from_introspection}")
    else:
        log(">>> Introspezione bloccata anche sul singolo tipo. Proviamo una lista di nomi plausibili.")

    # Candidati per il sotto-campo giusto: quelli suggeriti dall'introspezione (se ha
    # funzionato) hanno priorita', altrimenti proviamo una lista di nomi plausibili a mano.
    candidate_fields = [f for f in field_names_from_introspection
                        if 'auction' in f.lower() or 'sale' in f.lower() or 'offer' in f.lower()]
    if not candidate_fields:
        candidate_fields = ["auction", "currentAuction", "liveAuction", "englishAuction",
                            "activeEnglishAuction", "currentOffer", "liveOffer"]
    log(f"Sotto-campi candidati da provare su anyCard: {candidate_fields}")

    found_field = None
    for field_name in candidate_fields:
        query = f"""
        query GetCardAuction($slug: String!) {{
          anyCard(slug: $slug) {{
            slug
            {field_name} {{ id currentPrice minNextBid endDate }}
          }}
        }}
        """
        status3, data3 = graphql_query(query, {"slug": TEST_CARD_SLUG})
        log(f"--- sotto-campo provato: anyCard.{field_name} (HTTP {status3}) ---")
        log(f"Risposta: {json.dumps(data3, indent=2)}")
        if not data3.get('errors'):
            log(f">>> FUNZIONA! Il campo giusto e': anyCard(slug: ...).{field_name}")
            found_field = field_name
            break
    if not found_field:
        log(">>> Nessuno dei sotto-campi provati ha funzionato. Passo al tentativo 2.")

    log("=" * 70)
    log("TENTATIVO 3c: uno degli errori sopra ha suggerito un campo REALE che esiste davvero: "
        "'livePrimaryOffer' (Did you mean 'livePrimaryOffer'? sul tentativo liveOffer). "
        "Proviamo prima solo il __typename (per scoprire il tipo concreto senza indovinare "
        "i sotto-campi), poi i campi utili con fragment su piu' tipi plausibili.")
    query_typename = """
    query GetLivePrimaryOfferType($slug: String!) {
      anyCard(slug: $slug) {
        slug
        livePrimaryOffer {
          __typename
        }
      }
    }
    """
    status3c, data3c = graphql_query(query_typename, {"slug": TEST_CARD_SLUG})
    log(f"HTTP status: {status3c}")
    log(f"Risposta: {json.dumps(data3c, indent=2)}")
    card_data = (data3c.get('data') or {}).get('anyCard')
    if card_data and card_data.get('livePrimaryOffer'):
        log(f">>> livePrimaryOffer esiste ed e' di tipo: {card_data['livePrimaryOffer'].get('__typename')}")
    elif card_data and 'livePrimaryOffer' in card_data:
        log(">>> Il campo livePrimaryOffer esiste ma e' null per questa carta "
            "(forse non ha aste/offerte live in questo momento, o la carta e' cambiata nel frattempo).")
    else:
        log(">>> livePrimaryOffer non ha funzionato come campo (vedi errori sopra).")

    log("--- ora proviamo a leggere i campi utili su livePrimaryOffer, con fragment su piu' tipi ---")
    query_fields = """
    query GetLivePrimaryOfferFields($slug: String!) {
      anyCard(slug: $slug) {
        slug
        livePrimaryOffer {
          __typename
          ... on TokenAuction {
            id
            currentPrice
            minNextBid
            endDate
          }
          ... on SingleSaleOffer {
            id
            price
            endDate
          }
        }
      }
    }
    """
    status3d, data3d = graphql_query(query_fields, {"slug": TEST_CARD_SLUG})
    log(f"HTTP status: {status3d}")
    log(f"Risposta: {json.dumps(data3d, indent=2)}")
    if not data3d.get('errors'):
        log(">>> FUNZIONA! anyCard(slug: ...).livePrimaryOffer con fragment su TokenAuction/SingleSaleOffer "
            "e' la query giusta da usare per la riverifica pre-notifica.")
    else:
        log(">>> Errori sui nomi di tipo/campo usati nei fragment (vedi sopra) -- i nomi giusti dei tipi "
            "(TokenAuction/SingleSaleOffer) potrebbero essere diversi, il messaggio d'errore dovrebbe "
            "suggerire quello corretto se sbagliamo per un pelo.")

    log("=" * 70)
    log("TENTATIVO 3e: due indizi importanti dal tentativo precedente: (1) l'errore "
        "\"Fragment on TokenAuction can't be spread inside TokenPrimaryOffer\" CONFERMA che "
        "il tipo 'TokenAuction' esiste davvero nello schema (altrimenti avrebbe detto "
        "'No such type', come ha fatto per SingleSaleOffer); (2) livePrimaryOffer e' risultato "
        "null pur con l'asta aperta da 10 ore -- quindi 'primary offer' e' quasi certamente il "
        "mercato primario (pacchetti/distribuzione iniziale Sorare), non l'asta di rivendita. "
        "Cerchiamo quindi il campo 'gemello' per il mercato secondario (rivendita/aste).")
    secondary_candidates = ["liveSecondaryOffer", "secondaryOffer", "currentSecondaryOffer",
                             "activeSecondaryOffer", "liveResaleOffer", "resaleOffer",
                             "liveAuctionOffer", "secondaryMarketOffer", "liveMarketOffer"]
    found_secondary_field = None
    for field_name in secondary_candidates:
        query = f"""
        query GetSecondaryOffer($slug: String!) {{
          anyCard(slug: $slug) {{
            slug
            {field_name} {{
              __typename
              ... on TokenAuction {{
                id
                currentPrice
                minNextBid
                endDate
              }}
            }}
          }}
        }}
        """
        status3e, data3e = graphql_query(query, {"slug": TEST_CARD_SLUG})
        log(f"--- sotto-campo provato: anyCard.{field_name} (HTTP {status3e}) ---")
        log(f"Risposta: {json.dumps(data3e, indent=2)}")
        if not data3e.get('errors'):
            log(f">>> FUNZIONA! Il campo giusto e': anyCard(slug: ...).{field_name}")
            found_secondary_field = field_name
            break
    if not found_secondary_field:
        log(">>> Nessuno dei candidati 'secondary' ha funzionato. Passo al tentativo 2.")

    log("=" * 70)
    log("TENTATIVO 3f: il tentativo 'liveResaleOffer' ha suggerito un altro campo REALE: "
        "'liveSingleSaleOffer' (singolare, sulla carta -- diverso dal campo 'liveSingleSaleOffers' "
        "plurale gia' noto su tokens, filtrato per playerSlug). Ipotesi: su Sorare 'SingleSaleOffer' "
        "potrebbe significare 'offerta per questa singola carta' in senso lato (comprando sia "
        "vendita a prezzo fisso SIA asta), non necessariamente solo 'buy now'. Proviamo a "
        "leggerlo con fragment su TokenAuction.")
    query_single_sale = """
    query GetLiveSingleSaleOffer($slug: String!) {
      anyCard(slug: $slug) {
        slug
        liveSingleSaleOffer {
          __typename
          ... on TokenAuction {
            id
            currentPrice
            minNextBid
            endDate
          }
        }
      }
    }
    """
    status3f, data3f = graphql_query(query_single_sale, {"slug": TEST_CARD_SLUG})
    log(f"HTTP status: {status3f}")
    log(f"Risposta: {json.dumps(data3f, indent=2)}")
    if not data3f.get('errors'):
        card_data_f = (data3f.get('data') or {}).get('anyCard') or {}
        offer = card_data_f.get('liveSingleSaleOffer')
        if offer:
            log(f">>> FUNZIONA! anyCard(slug: ...).liveSingleSaleOffer esiste ed e' di tipo "
                f"{offer.get('__typename')}. Dati: {offer}")
        else:
            log(">>> Il campo liveSingleSaleOffer esiste ma e' null per questa carta in questo momento.")
    else:
        log(">>> Errore su liveSingleSaleOffer (vedi sopra) -- se l'errore riguarda solo il fragment "
            "TokenAuction, il campo esiste comunque ma restituisce un tipo diverso.")

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
