import json
import os
import time
import datetime
import threading

import websocket  # pip install websocket-client

COOKIES = os.environ.get('SORARE_COOKIE')
WS_URL = "wss://ws.sorare.com/cable"

LISTEN_SECONDS = 90

# Proviamo ad arricchire la subscription gia' confermata funzionante (tokenAuctionWasUpdated)
# con gli stessi campi che usiamo nella query REST liveAuctions (auctions.py), per capire se
# possiamo ricevere direttamente slug/giocatore/rarita'/stagione della carta in asta senza
# dover fare una query separata per ogni evento.
QUERY = """
subscription OnTokenAuctionUpdatedRich {
  tokenAuctionWasUpdated {
    id
    currentPrice
    minNextBid
    endDate
    anyCards {
      slug
      rarityTyped
      sport
      anyPlayer { slug displayName }
      sportSeason { name }
    }
  }
}
"""


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def main():
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": QUERY,
        "variables": {},
        "operationName": "OnTokenAuctionUpdatedRich",
        "action": "execute",
    }
    state = {"confirmed": False, "rejected": False, "errors": [], "count": 0}

    def on_open(ws):
        log("Connesso, sottoscrizione in corso...")
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({
            "command": "message",
            "identifier": identifier,
            "data": json.dumps(subscription_payload),
        }))

    def on_message(ws, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return
        msg_type = message.get('type')
        if msg_type in ('welcome', 'ping'):
            return
        if msg_type == 'confirm_subscription':
            state["confirmed"] = True
            log("Sottoscrizione CONFERMATA, in ascolto...")
            return
        if msg_type == 'reject_subscription':
            state["rejected"] = True
            log(f"Sottoscrizione RIFIUTATA: {message}")
            return
        payload = message.get('message')
        if not payload:
            return
        if payload.get('errors'):
            state["errors"].append(payload['errors'])
            log(f"ERRORE GraphQL: {payload['errors']}")
            return
        state["count"] += 1
        data = (payload.get('result', {}).get('data', {}) or {})
        log(f"Evento #{state['count']}: {json.dumps(data)}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). "
            f"Eventi ricevuti: {state['count']}, confermata={state['confirmed']}, "
            f"rifiutata={state['rejected']}, errori={len(state['errors'])}")

    ws = websocket.WebSocketApp(
        WS_URL,
        header=[f"Cookie: {COOKIES}"] if COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    timer = threading.Timer(LISTEN_SECONDS, ws.close)
    timer.daemon = True
    timer.start()
    log(f"In ascolto per {LISTEN_SECONDS}s...")
    ws.run_forever(ping_interval=30, ping_timeout=10)
    timer.cancel()
    log("Diagnostica terminata.")


if __name__ == "__main__":
    main()
