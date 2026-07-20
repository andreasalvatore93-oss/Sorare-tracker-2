import json
import os

import requests

# =====================================================================================
# INTROSPECTION SCHEMA -- fetchEncryptedPrivateKeyInput
# =====================================================================================
# Script isolato, SOLO LETTURA (nessuna mutation, nessun acquisto, nessun rischio).
# Interroga direttamente lo schema GraphQL di Sorare per scoprire TUTTI i campi
# realmente accettati da fetchEncryptedPrivateKeyInput -- invece di continuare a
# indovinare nomi di campo uno alla volta (authorizationId/fingerprint/offerId gia'
# tentati e tutti rifiutati dallo schema, vedi note progetto).
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
GRAPHQL_URL = 'https://api.sorare.com/graphql'


def log(message):
    print(f"[introspection] {message}", flush=True)


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


INTROSPECTION_QUERY = """
query IntrospectFetchEncryptedPrivateKeyInput {
  __type(name: "fetchEncryptedPrivateKeyInput") {
    name
    inputFields {
      name
      type {
        name
        kind
        ofType {
          name
          kind
        }
      }
      defaultValue
    }
  }
}
"""


def main():
    data = graphql_query(INTROSPECTION_QUERY)
    if data.get('errors'):
        log(f"ERRORE: introspection fallita o disabilitata: {data['errors']}")
        return

    type_info = (data.get('data') or {}).get('__type')
    if not type_info:
        log("ERRORE: __type ha restituito null -- il tipo 'fetchEncryptedPrivateKeyInput' "
            "non esiste con questo nome esatto, o l'introspection e' disabilitata sul "
            "server (comune in produzione per motivi di sicurezza).")
        return

    log(f"Tipo trovato: {type_info.get('name')}")
    fields = type_info.get('inputFields') or []
    if not fields:
        log("Il tipo esiste ma non ha campi (input completamente vuoto, "
            "confermando che {} e' davvero l'unico input valido).")
        return

    log(f"Campi reali accettati da fetchEncryptedPrivateKeyInput ({len(fields)}):")
    for f in fields:
        ftype = f.get('type') or {}
        of_type = ftype.get('ofType') or {}
        type_name = ftype.get('name') or of_type.get('name') or ftype.get('kind')
        log(f"  - {f.get('name')}: {type_name} (default: {f.get('defaultValue')})")


if __name__ == "__main__":
    main()
