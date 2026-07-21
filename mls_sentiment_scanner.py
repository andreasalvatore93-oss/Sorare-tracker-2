import json
import os
import time
import datetime
import threading
import statistics
import websocket
import requests

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# =====================================================================================
# MLS SENTIMENT ANALYSIS SCANNER
# =====================================================================================
# Scanner standalone per tracciare prezzi MLS in_season, accumulare dati storici,
# calcolare sentiment di mercato e generare consigli intelligenti basati su statistiche
# =====================================================================================

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"
MLS_SLUG = 'mls'
OUTPUT_DIR = 'mls'
SENTIMENT_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_analysis.json')
MARKDOWN_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_analysis.md')
HTML_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_chart.html')

# Default listen duration: 10 minutes (600 seconds)
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '600'))
INSUFFICIENT_FUNDS_STOP = [False]

# MLS Teams (all 28)
MLS_TEAMS = {
    'atlanta-united': 'Atlanta United',
    'chicago-fire': 'Chicago Fire',
    'colorado-rapids': 'Colorado Rapids',
    'columbus-crew': 'Columbus Crew',
    'dc-united': 'DC United',
    'fc-dallas': 'FC Dallas',
    'houston-dynamo': 'Houston Dynamo',
    'inter-miami': 'Inter Miami',
    'la-galaxy': 'LA Galaxy',
    'lafc': 'LAFC',
    'los-angeles-football-club': 'LAFC',
    'minnesota-united': 'Minnesota United',
    'montreal-impact': 'Montreal Impact',
    'new-england-revolution': 'New England Revolution',
    'new-york-city-fc': 'New York City FC',
    'new-york-red-bulls': 'New York Red Bulls',
    'orlando-city': 'Orlando City',
    'philadelphia-union': 'Philadelphia Union',
    'portland-timbers': 'Portland Timbers',
    'real-salt-lake': 'Real Salt Lake',
    'san-diego-loyal': 'San Diego Loyal',
    'san-jose-earthquakes': 'San Jose Earthquakes',
    'seattle-sounders': 'Seattle Sounders',
    'sporting-kansas-city': 'Sporting Kansas City',
    'toronto-fc': 'Toronto FC',
    'vancouver-whitecaps': 'Vancouver Whitecaps',
    'fc-cincinnati': 'FC Cincinnati',
    'cf-montreal': 'CF Montreal',
}

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()


def log(msg):
    timestamp = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{timestamp}] {msg}")


def ensure_output_dir():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        log(f"Creata cartella output: {OUTPUT_DIR}")


def eur_price_from_amounts(amounts, eth_rate):
    """Converte amounts in EUR price. Stessa logica di bot_supremo."""
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        try:
            return amounts['eurCents'] / 100
        except (ValueError, TypeError):
            pass
    if amounts.get('wei') is not None and eth_rate:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (ValueError, TypeError):
            pass
    return None


def graphql_query(query, variables=None):
    """Esegue query GraphQL via curl_cffi/requests."""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    cookies = os.environ.get('SORARE_COOKIE', '')
    if cookies:
        headers['Cookie'] = cookies
    
    payload = {
        'query': query,
        'variables': variables or {},
    }
    
    try:
        response = _http_session.post(
            GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"[GraphQL Error] {e}")
        return {}


SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    sender { ... on User { slug } }
    senderSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards {
        slug
        rarityTyped
        sport
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
        sportSeason { name }
        inSeasonEligible
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards { slug }
    }
  }
}
"""


def get_eth_rate():
    """Ottiene il tasso ETH/EUR corrente da API pubblica."""
    try:
        # Prova API CoinGecko (libera, no API key)
        response = requests.get(
            'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur',
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        eth_eur = data.get('ethereum', {}).get('eur')
        if eth_eur:
            return float(eth_eur)
    except Exception as e:
        log(f"[ETH Rate API] Errore CoinGecko: {e}")
    
    # Fallback: tasso medio storico approssimativo
    log("[ETH Rate] Usando fallback 1700 EUR/ETH")
    return 1700


def load_sentiment_data():
    """Carica il file JSON storico di sentiment."""
    if os.path.exists(SENTIMENT_FILE):
        try:
            with open(SENTIMENT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                log(f"Caricato storico sentiment: {len(data.get('teams', {}))} squadre")
                return data
        except Exception as e:
            log(f"[Errore caricamento] {e}")
    
    # Crea struttura vuota
    return {
        'metadata': {
            'first_run': datetime.datetime.utcnow().isoformat() + 'Z',
            'last_run': None,
            'total_runs': 0,
        },
        'summary': {
            'global_average_price_eur': 0,
            'global_trend': 'STABLE',
            'trend_change_pct': 0,
            'top10_movers': [],
        },
        'teams': {team_slug: {'team_name': team_name, 'players': {}} for team_slug, team_name in MLS_TEAMS.items()},
    }


def purge_old_entries(data, days=30):
    """Rimuove entry >30 giorni fa."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    cutoff_iso = cutoff.isoformat() + 'Z'
    
    removed_count = 0
    for team_slug in data.get('teams', {}):
        team_data = data['teams'][team_slug]
        players_to_keep = {}
        for player_slug, player_data in team_data.get('players', {}).items():
            last_update = player_data.get('last_update')
            if last_update and last_update < cutoff_iso:
                removed_count += 1
            else:
                players_to_keep[player_slug] = player_data
        team_data['players'] = players_to_keep
    
    if removed_count > 0:
        log(f"[Purge] Rimossi {removed_count} giocatori >30 giorni")
    
    return data


def run_listener(eth_rate, data, listen_seconds):
    """Ascolta WebSocket e raccoglie prezzi MLS in_season."""
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }
    
    stats = {"received": 0, "processed": 0, "prices_found": 0}
    ws_container = [None]  # Contenitore per WebSocket (per chiuderlo dal timer)
    seen_offer_status = set()
    
    def on_open(ws):
        log("Connesso al WebSocket Sorare, sottoscrizione in corso...")
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
            log("Sottoscrizione confermata, in ascolto...")
            return
        
        try:
            payload = message.get('message')
            if not payload:
                return
            
            stats["received"] += 1
            
            offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
            if not offer:
                if stats["received"] <= 3:
                    log(f"[DEBUG] Nessun offer nel payload #{stats['received']}: {json.dumps(payload)[:300]}")
                return
            
            offer_id = offer.get('id') or ''
            if not offer_id.startswith('SingleSaleOffer:'):
                if stats["received"] <= 10:
                    log(f"[DEBUG] Offer scartato, id={offer_id[:40]}")
                return
            
            offer_status = offer.get('status')
            dedup_key = (offer_id, offer_status)
            if dedup_key in seen_offer_status:
                return
            seen_offer_status.add(dedup_key)
            
            if offer_status != 'opened':
                return
            
            sender_side = offer.get('senderSide') or {}
            receiver_side = offer.get('receiverSide') or {}
            if receiver_side.get('anyCards'):
                return
            
            price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
            if price_eur is None:
                return
            
            sender_cards = sender_side.get('anyCards') or []
            if len(sender_cards) > 1:
                return
            
            for card in sender_cards:
                if card.get('rarityTyped') != 'limited' or card.get('sport') != 'FOOTBALL':
                    continue
                if not card.get('inSeasonEligible'):
                    continue
                
                player = card.get('anyPlayer') or {}
                player_slug = player.get('slug')
                player_name = player.get('displayName', player_slug)
                league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
                
                if not player_slug or league_slug != MLS_SLUG:
                    if stats["received"] <= 30 and league_slug:
                        log(f"[DEBUG] Carta in_season scartata: player={player_name}, league={league_slug} (cerco: {MLS_SLUG})")
                    continue
                
                stats["processed"] += 1
                
                # Registra il prezzo nella struttura dati
                team_slug = ''
                for ts, tn in MLS_TEAMS.items():
                    if player.get('activeClub', {}).get('slug') == ts:
                        team_slug = ts
                        break
                
                if team_slug not in data['teams']:
                    team_slug = list(data['teams'].keys())[0]  # fallback
                
                if player_slug not in data['teams'][team_slug]['players']:
                    data['teams'][team_slug]['players'][player_slug] = {
                        'name': player_name,
                        'prices_this_run': [],
                        'min_live_price': price_eur,
                        'max_live_price': price_eur,
                        'historical_mean': 0,
                        'std_dev': 0,
                        'occurrences': 0,
                        'change_from_mean_pct': 0,
                        'first_seen': datetime.datetime.utcnow().isoformat() + 'Z',
                        'last_update': datetime.datetime.utcnow().isoformat() + 'Z',
                    }
                
                player_data = data['teams'][team_slug]['players'][player_slug]
                player_data['prices_this_run'].append(price_eur)
                player_data['min_live_price'] = min(player_data['min_live_price'], price_eur)
                player_data['max_live_price'] = max(player_data['max_live_price'], price_eur)
                player_data['last_update'] = datetime.datetime.utcnow().isoformat() + 'Z'
                player_data['occurrences'] += 1
                stats["prices_found"] += 1
        
        except Exception as e:
            log(f"[Errore in on_message] {e}")
    
    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")
    
    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa. Events ricevuti: {stats['received']}, "
            f"prezzi trovati: {stats['prices_found']}")
    
    def close_ws_after_timeout():
        """Chiude il WebSocket dopo listen_seconds."""
        time.sleep(listen_seconds)
        if ws_container[0]:
            log(f"[Timeout] Chiusura WebSocket dopo {listen_seconds} secondi")
            ws_container[0].close()
    
    # Avvia thread di timeout
    timeout_thread = threading.Thread(target=close_ws_after_timeout, daemon=True)
    timeout_thread.start()
    
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    
    ws_container[0] = ws
    ws.run_forever(ping_interval=30)
    return data


def calculate_statistics(data):
    """Calcola media storica, deviazione standard, trend per ogni giocatore."""
    all_prices = []
    
    for team_slug in data.get('teams', {}):
        team_data = data['teams'][team_slug]
        for player_slug in team_data.get('players', {}):
            player_data = team_data['players'][player_slug]
            prices = player_data.get('prices_this_run', [])
            
            # Media storica: combina prezzi precedenti (se presenti) con questa run
            if player_data.get('historical_mean', 0) > 0:
                # Esiste storico: aggiorna la media incrementalmente
                old_count = player_data.get('occurrences', 0) - len(prices)
                if old_count < 0:
                    old_count = 0
                
                if old_count > 0:
                    old_sum = player_data['historical_mean'] * old_count
                    new_sum = old_sum + sum(prices)
                    total_count = old_count + len(prices)
                    player_data['historical_mean'] = new_sum / total_count if total_count > 0 else player_data['historical_mean']
                else:
                    # Prima volta o reset: media = media questa run
                    player_data['historical_mean'] = sum(prices) / len(prices) if prices else 0
            else:
                # Nessuno storico precedente: usa questa run
                player_data['historical_mean'] = sum(prices) / len(prices) if prices else 0
            
            # Deviazione standard
            if len(prices) > 1:
                player_data['std_dev'] = statistics.stdev(prices)
            else:
                player_data['std_dev'] = 0
            
            # Variazione % dalla media
            if player_data['historical_mean'] > 0:
                change = (player_data['min_live_price'] - player_data['historical_mean']) / player_data['historical_mean'] * 100
                player_data['change_from_mean_pct'] = round(change, 1)
            
            all_prices.extend(prices)
    
    # Media globale MLS
    global_mean = sum(all_prices) / len(all_prices) if all_prices else 0
    data['summary']['global_average_price_eur'] = round(global_mean, 2)
    
    # Trend: confronta media globale attuale vs storica (approssimato)
    if data['summary'].get('global_average_price_eur', 0) > 0:
        trend_change = (global_mean - (data['summary'].get('global_average_price_eur', global_mean))) / data['summary'].get('global_average_price_eur', global_mean) * 100 if data['summary'].get('global_average_price_eur', 0) > 0 else 0
        data['summary']['trend_change_pct'] = round(trend_change, 1)
        
        if trend_change <= -5:
            data['summary']['global_trend'] = 'STRONG_DESCENDING'
        elif -5 < trend_change < -1:
            data['summary']['global_trend'] = 'DESCENDING'
        elif -1 <= trend_change <= 1:
            data['summary']['global_trend'] = 'STABLE'
        elif 1 < trend_change < 3:
            data['summary']['global_trend'] = 'ASCENDING'
        else:
            data['summary']['global_trend'] = 'STRONG_ASCENDING'


def get_top_movers(data, top_n=10):
    """Identifica top10 rialzi (discese) e discese (rialzi)."""
    all_players = []
    
    for team_slug in data.get('teams', {}):
        team_data = data['teams'][team_slug]
        for player_slug, player_data in team_data.get('players', {}).items():
            if player_data.get('occurrences', 0) > 0:
                all_players.append({
                    'team_slug': team_slug,
                    'team_name': team_data['team_name'],
                    'player_slug': player_slug,
                    'player_name': player_data.get('name', player_slug),
                    'change_pct': player_data.get('change_from_mean_pct', 0),
                    'min_price': player_data.get('min_live_price', 0),
                    'mean_price': player_data.get('historical_mean', 0),
                    'occurrences': player_data.get('occurrences', 0),
                    'std_dev': player_data.get('std_dev', 0),
                })
    
    # Sort per variazione
    all_players.sort(key=lambda x: x['change_pct'])
    
    top_descending = all_players[:top_n]  # Più negativi (rialzi/discese)
    top_ascending = all_players[-top_n:]  # Più positivi (discese/rialzi)
    top_ascending.reverse()
    
    return {
        'descending': top_descending,
        'ascending': top_ascending,
    }


def build_recommendations(data, movers):
    """Costruisce consigli intelligenti basati su trend e movers."""
    recommendations = []
    
    # Trend globale
    trend = data['summary']['global_trend']
    trend_emoji = {
        'STRONG_DESCENDING': '📉',
        'DESCENDING': '📉',
        'STABLE': '➡️',
        'ASCENDING': '📈',
        'STRONG_ASCENDING': '📈',
    }.get(trend, '➡️')
    
    trend_change_pct = data['summary'].get('trend_change_pct', 0)
    
    recommendations.append({
        'type': 'global_trend',
        'emoji': trend_emoji,
        'text': f"TREND GLOBALE: {trend} ({trend_change_pct:+.1f}%)",
        'action': _trend_to_action(trend, trend_change_pct),
    })
    
    # Top 3 movers
    descending = movers.get('descending', [])[:3]
    for i, mover in enumerate(descending, 1):
        strength = 'FORTE OPPORTUNITÀ' if mover['change_pct'] < -15 else 'MOD. OPPORTUNITÀ'
        recommendations.append({
            'type': 'mover',
            'rank': i,
            'emoji': ['🥇', '🥈', '🥉'][i-1],
            'player_name': mover['player_name'],
            'team_name': mover['team_name'],
            'strength': strength,
            'min_price': mover['min_price'],
            'mean_price': mover['mean_price'],
            'change_pct': mover['change_pct'],
            'occurrences': mover['occurrences'],
            'std_dev': mover['std_dev'],
            'action': _mover_to_action(mover),
        })
    
    return recommendations


def _trend_to_action(trend, change_pct):
    """Traduce trend in azione consigliata."""
    if 'STRONG_DESCENDING' in trend or change_pct <= -5:
        return "Il mercato sta crollando. Eccellente momento di accumulo. Valuta le carte con sconto >15% dalla media storica."
    elif 'DESCENDING' in trend:
        return "Mercato in leggero calo. Selettivo: guarda carte con sconto >12%. Le squadre stabili offrono prezzi prevedibili."
    elif 'STABLE' in trend:
        return "Mercato equilibrato. Aspetta opportunità chiarissime prima di entrare."
    elif 'ASCENDING' in trend:
        return "I prezzi stanno salendo. Se hai carte in portafoglio, potrebbe essere buon momento per vendere."
    else:
        return "Mercato molto rialzista. Solo carte a -10% dalla media sono ancora interessanti."


def _mover_to_action(mover):
    """Traduce mover in azione consigliata."""
    occurrences = mover.get('occurrences', 0)
    change_pct = mover.get('change_pct', 0)
    
    if occurrences < 10:
        return "Liquidità bassa. Aspetta conferma prima di comprare grosse quantità."
    elif change_pct < -20:
        return "Sconto coerente e carta liquida. Se margine sufficiente, proponi offerta MakeOffer."
    elif change_pct < -12:
        return "Buona opportunità. Valuta di entrare se liquidità alta."
    else:
        return "Opportunità moderata. Aspetta conferma ulteriore prima di agire."


def save_sentiment_data(data):
    """Salva il JSON finale."""
    ensure_output_dir()
    
    data['metadata']['last_run'] = datetime.datetime.utcnow().isoformat() + 'Z'
    data['metadata']['total_runs'] = data['metadata'].get('total_runs', 0) + 1
    
    with open(SENTIMENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    log(f"Salvato JSON: {SENTIMENT_FILE}")
    return True


def generate_markdown(data, recommendations, movers):
    """Genera il file Markdown leggibile."""
    ensure_output_dir()
    
    md_content = []
    md_content.append("# 🔍 MLS SENTIMENT ANALYSIS\n")
    
    run_date = data['metadata'].get('last_run', 'N/A')
    md_content.append(f"**Data analisi:** {run_date}\n")
    md_content.append(f"**Run totali:** {data['metadata'].get('total_runs', 0)}\n\n")
    
    # Riepilogo globale
    md_content.append("## 📈 RIEPILOGO GLOBALE\n")
    avg_price = data['summary'].get('global_average_price_eur', 0)
    trend = data['summary'].get('global_trend', 'STABLE')
    trend_change = data['summary'].get('trend_change_pct', 0)
    trend_emoji = {'STRONG_DESCENDING': '📉', 'DESCENDING': '📉', 'STABLE': '➡️', 'ASCENDING': '📈', 'STRONG_ASCENDING': '📈'}.get(trend, '➡️')
    
    md_content.append(f"- **Prezzo medio MLS:** {avg_price:.2f} EUR\n")
    md_content.append(f"- **Trend mercato:** {trend_emoji} {trend} ({trend_change:+.1f}%)\n\n")
    
    # Consigli
    md_content.append("## 💡 CONSIGLI INTELLIGENTI\n")
    for rec in recommendations:
        if rec['type'] == 'global_trend':
            md_content.append(f"**{rec['emoji']} {rec['text']}**\n")
            md_content.append(f"{rec['action']}\n\n")
        elif rec['type'] == 'mover':
            md_content.append(f"**{rec['emoji']} {rec['strength']} — {rec['player_name']} ({rec['team_name']})**\n")
            md_content.append(f"Prezzo: **{rec['min_price']:.2f} EUR** | Media: **{rec['mean_price']:.2f} EUR** | Sconto: **{rec['change_pct']:.1f}%**\n")
            md_content.append(f"Liquidità: **{rec['occurrences']} occorrenze** | Volatilità: {rec['std_dev']:.2f}\n")
            md_content.append(f"{rec['action']}\n\n")
    
    # Top10 rialzi/discese
    md_content.append("## ⬆️ TOP 10 RIALZI (Stanno CALANDO di prezzo)\n")
    for i, mover in enumerate(movers['descending'][:10], 1):
        md_content.append(f"{i}. {mover['player_name']} ({mover['team_name']}) — "
                        f"**{mover['change_pct']:.1f}%** vs media ({mover['min_price']:.2f} EUR vs {mover['mean_price']:.2f} EUR)\n")
    md_content.append("\n")
    
    md_content.append("## ⬇️ TOP 10 DISCESE (Stanno SALENDO di prezzo)\n")
    for i, mover in enumerate(movers['ascending'][:10], 1):
        md_content.append(f"{i}. {mover['player_name']} ({mover['team_name']}) — "
                        f"**+{mover['change_pct']:.1f}%** vs media ({mover['min_price']:.2f} EUR vs {mover['mean_price']:.2f} EUR)\n")
    md_content.append("\n")
    
    # Sentiment per squadra
    md_content.append("## 🏟️ SENTIMENT PER SQUADRA\n")
    for team_slug, team_data in data['teams'].items():
        players = team_data.get('players', {})
        if players:
            prices = [p.get('min_live_price', 0) for p in players.values() if p.get('min_live_price', 0) > 0]
            if prices:
                team_avg = sum(prices) / len(prices)
                volatility = statistics.stdev(prices) if len(prices) > 1 else 0
                md_content.append(f"**{team_data['team_name']}**\n")
                md_content.append(f"Carte trovate: {len(players)} | Prezzo medio: {team_avg:.2f} EUR | Volatilità (σ): {volatility:.2f}\n\n")
    
    with open(MARKDOWN_FILE, 'w', encoding='utf-8') as f:
        f.write(''.join(md_content))
    
    log(f"Generato Markdown: {MARKDOWN_FILE}")


def generate_html_chart(data):
    """Genera HTML con grafici Chart.js."""
    ensure_output_dir()
    
    # Preparazione dati per i grafici
    teams_data = {}
    for team_slug, team_data in data['teams'].items():
        players = team_data.get('players', {})
        if players:
            prices = [p.get('min_live_price', 0) for p in players.values() if p.get('min_live_price', 0) > 0]
            if prices:
                teams_data[team_data['team_name']] = {
                    'avg': sum(prices) / len(prices),
                    'count': len(players),
                }
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MLS Sentiment Analysis Chart</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 30px;
        }}
        .chart-wrapper {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .chart-title {{
            font-size: 16px;
            font-weight: 600;
            color: #333;
            margin-bottom: 15px;
        }}
        canvas {{
            max-height: 300px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 MLS Sentiment Analysis</h1>
        
        <div class="chart-wrapper">
            <div class="chart-title">Average Price by Team</div>
            <canvas id="teamChart"></canvas>
        </div>
        
        <div class="chart-wrapper">
            <div class="chart-title">Cards Found per Team</div>
            <canvas id="countChart"></canvas>
        </div>
    </div>
    
    <script>
        const teamsData = {teams_data_json};
        
        // Team average prices
        const teamLabels = Object.keys(teamsData).sort();
        const teamAvgs = teamLabels.map(t => teamsData[t].avg.toFixed(2));
        
        const ctx1 = document.getElementById('teamChart').getContext('2d');
        new Chart(ctx1, {{
            type: 'bar',
            data: {{
                labels: teamLabels,
                datasets: [{{
                    label: 'Average Price (EUR)',
                    data: teamAvgs,
                    backgroundColor: '#4A90E2',
                    borderColor: '#2E5C8A',
                    borderWidth: 1,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{display: false}},
                }},
                scales: {{
                    y: {{beginAtZero: true}},
                }},
            }},
        }});
        
        // Cards found per team
        const teamCounts = teamLabels.map(t => teamsData[t].count);
        
        const ctx2 = document.getElementById('countChart').getContext('2d');
        new Chart(ctx2, {{
            type: 'bar',
            data: {{
                labels: teamLabels,
                datasets: [{{
                    label: 'Cards Found',
                    data: teamCounts,
                    backgroundColor: '#7ED321',
                    borderColor: '#4A8A0E',
                    borderWidth: 1,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{display: false}},
                }},
                scales: {{
                    y: {{beginAtZero: true}},
                }},
            }},
        }});
    </script>
</body>
</html>
"""
    
    html_content = html_content.replace('{teams_data_json}', json.dumps(teams_data))
    
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    log(f"Generato HTML chart: {HTML_FILE}")


def main():
    """Main flow dello scanner."""
    log("=" * 80)
    log("MLS SENTIMENT ANALYSIS SCANNER - INIZIO")
    log("=" * 80)
    
    ensure_output_dir()
    
    # Load storico
    data = load_sentiment_data()
    
    # Purge >30gg
    data = purge_old_entries(data, days=30)
    
    # Get ETH rate
    eth_rate = get_eth_rate()
    if not eth_rate:
        eth_rate = 2500  # fallback
    log(f"Tasso ETH/EUR: {eth_rate}")
    
    # Listen WebSocket
    log(f"Ascolto WebSocket per {LISTEN_SECONDS} secondi...")
    data = run_listener(eth_rate, data, LISTEN_SECONDS)
    
    # Calculate stats
    calculate_statistics(data)
    
    # Get movers
    movers = get_top_movers(data, top_n=10)
    
    # Build recommendations
    recommendations = build_recommendations(data, movers)
    
    # Save JSON
    json_modified = save_sentiment_data(data)
    
    # Generate Markdown e HTML se JSON modificato
    if json_modified:
        generate_markdown(data, recommendations, movers)
        generate_html_chart(data)
        
        # Output URL finale
        repo_url = "https://raw.githubusercontent.com/andreasalvatore93-oss/Sorare-tracker-2/main"
        html_url = f"{repo_url}/mls/mls_sentiment_chart.html"
        log(f"\n📊 Chart URL: {html_url}\n")
    
    log("=" * 80)
    log("MLS SENTIMENT ANALYSIS SCANNER - COMPLETATO")
    log("=" * 80)


if __name__ == '__main__':
    main()
