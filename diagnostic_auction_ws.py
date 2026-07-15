import json
import os
import time
import datetime
import threading

import websocket  # pip install websocket-client

COOKIES = os.environ.get('SORARE_COOKIE')
WS_URL = "wss://ws.sorare.com/cable"

# Fase 1: quanto ascoltare la subscription GIA' NOTA (tokenOfferWasUpdated) SENZA filtrare
# per prefisso SingleSaleOffer, per vedere se passano di la' anche eventi di tipo Auction.
PHASE1_SECONDS = 60

# Fase 2: quanto provare la subscription IPOTETICA tokenAuctionWasUpdated (simmetrica a
# tokenOfferWasUpdated), per vedere se esiste davvero.
PHASE2_SECONDS = 30

PHASE1_QUERY = """
subscription OnTokenOfferUpdatedBroad {
  tokenOfferWasUpdated {
    id
    status
  }
}
"""

PHASE2_QUERY = """
subscription OnTokenAuctionUpdated {
  tokenAuctionWasUpdated {
    id
    currentPrice
    minNextBid
    endDate
  }
}
"""


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def run_phase(query, operation_name, listen_seconds, on_event):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": query,
        "variables": {},
        "operationName": operation_name,
        "action": "execute",
    }
    state = {"confirmed": False, "rejected": False, "errors": [], "count": 0}

    def on_open(ws):
        log(f"[{operation_name}] Connesso, sottoscrizione in corso...")
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
            log(f"[{operation_name}] Sottoscrizione CONFERMATA, in ascolto...")
            return
        if msg_type == 'reject_subscription':
            state["rejected"] = True
            log(f"[{operation_name}] Sottoscrizione RIFIUTATA: {message}")
            return
        payload = message.get('message')
        if not payload:
            return
        if payload.get('errors'):
            state["errors"].append(payload['errors'])
            log(f"[{operation_name}] ERRORE GraphQL: {payload['errors']}")
            return
        state["count"] += 1
        data = (payload.get('result', {}).get('data', {}) or {})
        on_event(data)

    def on_error(ws, error):
        log(f"[{operation_name}] Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"[{operation_name}] Connessione chiusa (codice {close_status_code}). "
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

    timer = threading.Timer(listen_seconds, ws.close)
    timer.daemon = True
    timer.start()
    ws.run_forever(ping_interval=30, ping_timeout=10)
    timer.cancel()
    return state


def main():
    log("=" * 70)
    log(f"FASE 1: ascolto tokenOfferWasUpdated SENZA filtro prefisso per {PHASE1_SECONDS}s")
    log("=" * 70)
    prefix_counts = {}

    def on_event_phase1(data):
        offer = data.get('tokenOfferWasUpdated')
        if not offer:
            return
        offer_id = offer.get('id') or ''
        prefix = offer_id.split(':')[0] if ':' in offer_id else offer_id
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    run_phase(PHASE1_QUERY, "OnTokenOfferUpdatedBroad", PHASE1_SECONDS, on_event_phase1)
    log(f"FASE 1 risultato -- distribuzione prefissi id osservati: {prefix_counts}")

    log("=" * 70)
    log(f"FASE 2: provo la subscription ipotetica tokenAuctionWasUpdated per {PHASE2_SECONDS}s")
    log("=" * 70)
    auction_events = {"count": 0}

    def on_event_phase2(data):
        auction_events["count"] += 1
        log(f"[FASE 2] evento ricevuto: {json.dumps(data)[:500]}")

    state2 = run_phase(PHASE2_QUERY, "OnTokenAuctionUpdated", PHASE2_SECONDS, on_event_phase2)
    log(f"FASE 2 risultato -- confermata={state2['confirmed']}, rifiutata={state2['rejected']}, "
        f"errori={state2['errors']}, eventi_ricevuti={auction_events['count']}")

    log("Diagnostica terminata.")


if __name__ == "__main__":
    main()
