import json
import os
import subprocess

import requests

# =====================================================================================
# TEST ISOLATO FIRMA STARKWARE -- NESSUN ACQUISTO REALE
# =====================================================================================
# Script SEPARATO da autobuy_sorare.py, usato SOLO per verificare che
# sorare-sign/decrypt_and_sign.js produca una signature valida, PRIMA di collegare
# l'automazione completa. NON chiama mai AcceptOfferMutation: si ferma subito dopo aver
# ottenuto (o fallito ad ottenere) la signature.
#
# Uso: richiede in input un authorization_request REALE gia' ottenuto da una precedente
# chiamata a prepare_accept_offer() di autobuy_sorare.py (fingerprint + request), preso
# dai log di una run passata (es. il caso Sergey Pinyaev). Se quell'offerta e' scaduta o
# gia' venduta nel frattempo non e' un problema: qui NON si accetta l'offerta, si genera
# solo la firma per verificare che il meccanismo funzioni.
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')
GRAPHQL_URL = 'https://api.sorare.com/graphql'


def log(message):
    print(f"[test firma] {message}", flush=True)


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


ENCRYPTED_PRIVATE_KEY_QUERY = """
query EncryptedPrivateKeyQuery {
  currentUser {
    sorarePrivateKey {
      encryptedPrivateKey
      iv
      salt
    }
  }
}
"""


def fetch_encrypted_private_key():
    """Recupera encryptedPrivateKey/iv/salt -- campo gia' visto rispondere con successo
    dentro una risposta piu' ampia di currentUser (JSON condiviso dall'utente in
    precedenza), qui isolato in una query dedicata piu' leggera."""
    data = graphql_query(ENCRYPTED_PRIVATE_KEY_QUERY)
    log(f"[debug] risposta grezza query chiave cifrata: {json.dumps(data)}")
    if data.get('errors'):
        log(f"ERRORE query chiave cifrata: {data['errors']}")
        return None
    key_data = ((data.get('data') or {}).get('currentUser') or {}).get('sorarePrivateKey')
    if not key_data:
        log("ERRORE: sorarePrivateKey assente nella risposta")
        return None
    log("Chiave cifrata recuperata con successo (encryptedPrivateKey/iv/salt presenti, "
        "valori non loggati per sicurezza)")
    return key_data


def test_signature(authorization_request, fingerprint):
    """Chiama decrypt_and_sign.js con dati REALI ma senza mai completare l'acquisto --
    stampa solo se la firma e' stata generata, o l'errore esatto, MAI la signature/chiave
    in chiaro."""
    key_data = fetch_encrypted_private_key()
    if not key_data:
        log("Impossibile procedere senza la chiave cifrata.")
        return

    if not WALLET_PASSWORD:
        log("ERRORE: variabile SORARE_WALLET_PASSWORD non impostata.")
        return

    payload = json.dumps({
        'password': WALLET_PASSWORD,
        'encryptedPrivateKey': key_data.get('encryptedPrivateKey'),
        'iv': key_data.get('iv'),
        'salt': key_data.get('salt'),
        'authorizationRequest': authorization_request,
    })

    script_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'sorare-sign', 'decrypt_and_sign.js')
    log(f"Chiamo {script_path}...")
    try:
        result = subprocess.run(
            ['node', script_path],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        log(f"ERRORE eccezione lanciando node: {e}")
        return

    if result.returncode != 0:
        log(f"Script terminato con codice {result.returncode}, stderr: {result.stderr.strip()}")

    try:
        output = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        log(f"ERRORE: output non JSON valido: {result.stdout!r}")
        return

    if 'error' in output:
        log(f"FIRMA FALLITA -- errore riportato: {output['error']}")
        return

    signature = output.get('signature')
    if signature:
        log(f"FIRMA GENERATA CON SUCCESSO (lunghezza: {len(str(signature))} caratteri, "
            f"contenuto non loggato per sicurezza) -- fingerprint={fingerprint}")
        log("NESSUN ACQUISTO EFFETTUATO: questo script si ferma qui, non chiama "
            "AcceptOfferMutation.")
    else:
        log("ERRORE: nessuna signature nell'output e nessun campo 'error' -- risposta "
            f"inattesa: {output}")


def main():
    # ESEMPIO -- sostituire con un caso reale preso dai log di una run precedente di
    # autobuy_sorare.py (funzione prepare_accept_offer), es. il caso Sergey Pinyaev:
    # [prepare accept] risposta grezza: {"data": {"prepareAcceptOffer": {"authorizations":
    # [{"fingerprint": "...", "id": "...", "request": {"currency": "EUR", "amount": 1049,
    # "mangopayWalletId": "...", "nonce": 9961, "operationHash": "..."}}], ...}}}
    fingerprint = os.environ.get('TEST_FINGERPRINT', '')
    authorization_request_json = os.environ.get('TEST_AUTHORIZATION_REQUEST', '')

    log(f"[debug] TEST_FINGERPRINT ricevuto: {fingerprint!r}")
    log(f"[debug] TEST_AUTHORIZATION_REQUEST ricevuto (lunghezza {len(authorization_request_json)}): "
        f"{authorization_request_json!r}")

    if not fingerprint or not authorization_request_json:
        log("ERRORE: servono le variabili TEST_FINGERPRINT e TEST_AUTHORIZATION_REQUEST "
            "(quest'ultima con l'oggetto 'request' completo in JSON, incluso __typename).")
        return

    try:
        authorization_request = json.loads(authorization_request_json)
    except json.JSONDecodeError as e:
        log(f"ERRORE: TEST_AUTHORIZATION_REQUEST non e' JSON valido: {e}")
        return

    test_signature(authorization_request, fingerprint)


if __name__ == "__main__":
    main()
