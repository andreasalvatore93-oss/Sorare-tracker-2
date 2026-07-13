"""
Sorare Price Tracker
---------------------
Controlla il prezzo piu' basso in vendita per ogni giocatore/rarity
configurato in config.json e invia una email quando scende sotto la
soglia impostata.

Non serve nessun login Sorare: i dati del transfer market sono pubblici.
"""

import json
import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText

import requests

GRAPHQL_URL = "https://api.sorare.com/graphql"
CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

QUERY = """
query GetPlayerCards($slug: String!, $first: Int!) {
  player(slug: $slug) {
    displayName
    cards(rarity: %s, first: $first) {
      nodes {
        slug
        onSale
        inSeasonEligible
        liveSingleSaleOffer {
          priceInFiat: amountInFiat(currency: EUR) {
            eur
          }
        }
      }
    }
  }
}
"""

# Alcune versioni dello schema espongono priceInFiat come oggetto diretto
# invece che tramite amountInFiat(currency:). Se la query sopra fallisce,
# lo script prova automaticamente questa query alternativa.
QUERY_FALLBACK = """
query GetPlayerCards($slug: String!, $first: Int!) {
  player(slug: $slug) {
    displayName
    cards(rarity: %s, first: $first) {
      nodes {
        slug
        onSale
        inSeasonEligible
        liveSingleSaleOffer {
          priceInFiat {
            eur
          }
        }
      }
    }
  }
}
"""


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_query(query_template, rarity, player_slug):
    query = query_template % rarity
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": {"slug": player_slug, "first": 100}},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_cheapest_listing(player_slug, rarity, in_season_only):
    try:
        data = run_query(QUERY, rarity, player_slug)
    except Exception:
        data = run_query(QUERY_FALLBACK, rarity, player_slug)

    player = data.get("player")
    if not player:
        print(f"  giocatore non trovato: {player_slug}")
        return None, None

    nodes = player["cards"]["nodes"]
    best_price = None
    best_slug = None

    for card in nodes:
        if not card.get("onSale"):
            continue
        if in_season_only and not card.get("inSeasonEligible"):
            continue
        offer = card.get("liveSingleSaleOffer")
        if not offer:
            continue
        price_obj = offer.get("priceInFiat")
        if not price_obj:
            continue
        price = price_obj.get("eur")
        if price is None:
            continue
        price = float(price)
        if best_price is None or price < best_price:
            best_price = price
            best_slug = card["slug"]

    return best_price, best_slug


def send_email(subject, body):
    sender = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_EMAIL", sender)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, app_password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    config = load_json(CONFIG_FILE, {"trackers": []})
    state = load_json(STATE_FILE, {})

    any_error = False

    for tracker in config["trackers"]:
        name = tracker["name"]
        player_slug = tracker["player_slug"]
        rarity = tracker["rarity"]
        max_price = float(tracker["max_price_eur"])
        in_season_only = tracker.get("in_season_only", True)

        print(f"Controllo: {name} (soglia {max_price} EUR)")

        try:
            price, slug = get_cheapest_listing(player_slug, rarity, in_season_only)
        except Exception as e:
            print(f"  ERRORE nella query per {name}: {e}")
            any_error = True
            continue

        key = name
        last_notified_price = state.get(key, {}).get("last_notified_price")

        if price is None:
            print("  nessuna carta in vendita trovata con questi filtri")
            continue

        print(f"  prezzo piu' basso trovato: {price} EUR ({slug})")

        if price <= max_price:
            # Notifica solo se non abbiamo gia' avvisato per un prezzo
            # uguale o piu' basso (evita spam ad ogni run).
            if last_notified_price is None or price < last_notified_price:
                subject = f"Sorare: {name} sotto soglia! {price} EUR"
                body = (
                    f"Trovata carta '{slug}' in vendita a {price} EUR "
                    f"(soglia impostata: {max_price} EUR).\n\n"
                    f"https://sorare.com/football/cards/{slug}"
                )
                try:
                    send_email(subject, body)
                    print("  EMAIL INVIATA")
                except Exception as e:
                    print(f"  ERRORE invio email: {e}")
                    any_error = True
                state[key] = {"last_notified_price": price}
        else:
            # Il prezzo e' risalito sopra soglia: resettiamo cosi' una
            # futura discesa sotto soglia generera' una nuova notifica.
            if key in state:
                del state[key]

    save_json(STATE_FILE, state)

    if any_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
