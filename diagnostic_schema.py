"""
Script diagnostico una tantum: introspezione dello schema GraphQL di Sorare
per verificare se il campo `tokenPrices` (o il tipo `TokenPrice`) espone un modo
per filtrare/identificare il tipo di transazione (Asta / Scambio / Offerta diretta /
Acquisto istantaneo), invece di doverlo dedurre da `__typename` lato client.

Uso: python diagnostic_schema.py
Richiede le stesse env var di auctions.py: SORARE_COOKIE, SORARE_CSRF.

Da rimuovere (insieme al workflow diagnostic.yml) una volta ottenuta la risposta.
"""

import os
import json
import datetime
import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'


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
    return r.json()


def main():
    # 1) Che tipo ritorna il campo Query.anyPlayer?
    q_query_fields = """
    query {
      __type(name: "Query") {
        fields {
          name
          type { name kind ofType { name kind } }
        }
      }
    }
    """
    data = graphql_query(q_query_fields)
    log(f"[diag] Query.fields errors: {data.get('errors')}")
    fields = (((data.get('data') or {}).get('__type') or {}).get('fields')) or []
    any_player_field = next((f for f in fields if f.get('name') == 'anyPlayer'), None)
    log(f"[diag] campo anyPlayer: {json.dumps(any_player_field)}")

    any_player_type_name = None
    if any_player_field:
        t = any_player_field.get('type') or {}
        any_player_type_name = t.get('name') or (t.get('ofType') or {}).get('name')
    log(f"[diag] tipo di ritorno anyPlayer: {any_player_type_name}")

    # 2) Argomenti disponibili sul campo tokenPrices di quel tipo
    if any_player_type_name:
        q_type_fields = """
        query($typeName: String!) {
          __type(name: $typeName) {
            fields {
              name
              args {
                name
                type { name kind ofType { name kind } }
              }
            }
          }
        }
        """
        data2 = graphql_query(q_type_fields, {"typeName": any_player_type_name})
        log(f"[diag] {any_player_type_name}.fields errors: {data2.get('errors')}")
        fields2 = (((data2.get('data') or {}).get('__type') or {}).get('fields')) or []
        token_prices_field = next((f for f in fields2 if f.get('name') == 'tokenPrices'), None)
        log(f"[diag] campo tokenPrices su {any_player_type_name}: {json.dumps(token_prices_field)}")

    # 3) Campi del tipo TokenPrice
    q_token_price_type = """
    query {
      __type(name: "TokenPrice") {
        name
        fields {
          name
          type { name kind ofType { name kind } }
        }
      }
    }
    """
    data3 = graphql_query(q_token_price_type)
    log(f"[diag] TokenPrice errors: {data3.get('errors')}")
    log(f"[diag] TokenPrice type: {json.dumps(data3.get('data'))}")

    # 4) Elenco di tutti i tipi il cui nome contiene 'Price' o 'Sale' o 'Auction'
    #    (per scoprire tipi alternativi/più specifici che potremmo non conoscere)
    q_all_types = """
    query {
      __schema {
        types { name kind }
      }
    }
    """
    data4 = graphql_query(q_all_types)
    all_types = (((data4.get('data') or {}).get('__schema') or {}).get('types')) or []
    interesting = [t['name'] for t in all_types if t.get('name') and
                   any(k in t['name'] for k in ['Price', 'Sale', 'Auction', 'Trade', 'Offer'])]
    log(f"[diag] tipi rilevanti trovati nello schema: {interesting}")

    log("Diagnostica completata.")


if __name__ == "__main__":
    main()
