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
MLS_SLUG = 'mlspa'
OUTPUT_DIR = 'mls'
SENTIMENT_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_analysis.json')
MARKDOWN_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_analysis.md')
HTML_FILE = os.path.join(OUTPUT_DIR, 'mls_sentiment_chart.html')
COOKIES = os.environ.get('SORARE_COOKIE')

# Default listen duration: 60 minutes (3600 seconds)
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '3600'))
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
        anyPlayer { slug displayName activeClub { slug name domesticLeague { slug } } }
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

LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n) {
      nodes {
        status
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            inSeasonEligible
          }
        }
      }
    }
  }
}
"""


def fetch_min_in_season_price(player_slug, eth_rate):
    """Query diretta: cerca tra TUTTI gli annunci live aperti di un giocatore
    (classic + in_season) e restituisce il minimo prezzo SOLO tra quelli in_season."""
    data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": 50})
    if data.get('errors'):
        return None
    
    nodes = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {}).get('nodes') or []
    min_price = None
    
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        receiver_side = node.get('receiverSide') or {}
        if receiver_side.get('anyCards'):
            continue
        
        price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
        if price_eur is None:
            continue
        
        sender_cards = (node.get('senderSide') or {}).get('anyCards') or []
        if len(sender_cards) > 1:
            continue
        
        for card in sender_cards:
            if card.get('rarityTyped') != 'limited' or card.get('sport') != 'FOOTBALL':
                continue
            if not card.get('inSeasonEligible'):
                continue
            if min_price is None or price_eur < min_price:
                min_price = price_eur
    
    return min_price


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
    
    # Crea struttura vuota -- le squadre si aggiungono dinamicamente in register_price()
    # usando gli slug REALI restituiti da Sorare, non più una lista indovinata a mano
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
        'teams': {},
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
    
    def register_price(player_slug, player_name, player, price_eur, source='live'):
        """Registra un prezzo in_season nella struttura dati. source = 'live' o 'trigger'."""
        club = player.get('activeClub') or {}
        club_slug = club.get('slug')
        club_name = club.get('name') or club_slug or 'Unknown'
        
        if not club_slug:
            club_slug = 'unknown-team'
            club_name = 'Unknown'
        
        # Creiamo la squadra al volo con lo slug REALE di Sorare se non esiste ancora
        # (i nomi hard-coded in MLS_TEAMS erano indovinati e non corrispondevano)
        if club_slug not in data['teams']:
            data['teams'][club_slug] = {'team_name': club_name, 'players': {}}
        
        team_slug = club_slug
        
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
        
        tag = "trigger da classic" if source == 'trigger' else "live"
        log(f"[Carta trovata - {tag}] {player_name} (slug: {player_slug}) — "
            f"{data['teams'][team_slug]['team_name']} — {price_eur:.2f} EUR")
    
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
                return
            
            offer_id = offer.get('id') or ''
            if not offer_id.startswith('SingleSaleOffer:'):
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
                
                player = card.get('anyPlayer') or {}
                player_slug = player.get('slug')
                player_name = player.get('displayName', player_slug)
                league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
                
                if not player_slug or league_slug != MLS_SLUG:
                    continue
                
                # Ascoltiamo anche le classic MLS per agganciare il bot più spesso.
                # Quando vediamo una classic, facciamo una query diretta per cercare
                # il minimo in_season disponibile in questo momento per lo stesso giocatore.
                if not card.get('inSeasonEligible'):
                    stats["classic_seen"] = stats.get("classic_seen", 0) + 1
                    
                    trigger_price = fetch_min_in_season_price(player_slug, eth_rate)
                    if trigger_price is not None:
                        register_price(player_slug, player_name, player, trigger_price, source='trigger')
                    continue
                
                stats["processed"] += 1
                register_price(player_slug, player_name, player, price_eur, source='live')
        
        except Exception as e:
            log(f"[Errore in on_message] {e}")
    
    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")
    
    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa. Events ricevuti: {stats['received']}, "
            f"prezzi in_season trovati: {stats['prices_found']}, "
            f"classic MLS viste (scartate): {stats.get('classic_seen', 0)}")
    
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
        header=[f"Cookie: {COOKIES}"] if COOKIES else [],
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
    
    chart_pages_url = "https://andreasalvatore93-oss.github.io/Sorare-tracker-2/mls/mls_sentiment_chart.html"
    md_content.append(f"📊 **[Apri i grafici interattivi]({chart_pages_url})**\n\n")
    
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


PRICE_TIERS = [
    (0, 2, 'Scarso', '#8B0000'),
    (2, 5, 'Starter', '#FF4500'),
    (5, 10, 'Buono', '#FFA500'),
    (10, 20, 'Ottimo', '#FFD700'),
    (20, 30, 'Eccellente', '#9ACD32'),
    (30, float('inf'), 'Leggendario', '#00C853'),
]


def classify_price_tier(price):
    """Restituisce (nome_fascia, colore) in base al prezzo minimo."""
    for low, high, name, color in PRICE_TIERS:
        if low <= price < high:
            return name, color
    return PRICE_TIERS[-1][2], PRICE_TIERS[-1][3]


def generate_html_chart(data):
    """Genera HTML con grafici Chart.js: prezzo medio per squadra e opportunità di acquisto."""
    ensure_output_dir()
    
    # Preparazione dati per il grafico prezzo medio per squadra
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
    
    # Preparazione dati per il grafico opportunità: ogni giocatore con sconto % dalla media storica,
    # ordinato dal migliore sconto (più negativo) al peggiore -- così si vede a colpo d'occhio
    # dove conviene guardare per comprare
    opportunities = []
    for team_slug, team_data in data['teams'].items():
        for player_slug, player_data in team_data.get('players', {}).items():
            change_pct = player_data.get('change_from_mean_pct', 0)
            occurrences = player_data.get('occurrences', 0)
            opportunities.append({
                'name': player_data.get('name', player_slug),
                'team': team_data['team_name'],
                'change_pct': change_pct,
                'price': player_data.get('min_live_price', 0),
                'mean': player_data.get('historical_mean', 0),
                'occurrences': occurrences,
            })
    opportunities.sort(key=lambda x: x['change_pct'])
    top_opportunities = opportunities[:15]  # le 15 migliori occasioni
    
    # Preparazione dati per fasce di prezzo: raggruppa tutti i giocatori per tier
    # e calcola sconto medio + conteggio per ogni fascia -- risponde alla domanda
    # "quale fascia di carte sta calando/salendo di più in questo momento?"
    tier_stats = {name: {'changes': [], 'color': color, 'count': 0} for _, _, name, color in PRICE_TIERS}
    for team_slug, team_data in data['teams'].items():
        for player_slug, player_data in team_data.get('players', {}).items():
            price = player_data.get('min_live_price', 0)
            if price <= 0:
                continue
            tier_name, _ = classify_price_tier(price)
            tier_stats[tier_name]['changes'].append(player_data.get('change_from_mean_pct', 0))
            tier_stats[tier_name]['count'] += 1
    
    tier_chart_data = []
    for low, high, name, color in PRICE_TIERS:
        changes = tier_stats[name]['changes']
        avg_change = sum(changes) / len(changes) if changes else 0
        tier_chart_data.append({
            'name': name,
            'avg_change': round(avg_change, 1),
            'count': tier_stats[name]['count'],
            'color': color,
            'range': f"{low:.0f}-{high:.0f}" if high != float('inf') else f"{low:.0f}+",
        })
    
    global_trend = data['summary'].get('global_trend', 'STABLE')
    global_trend_pct = data['summary'].get('trend_change_pct', 0)
    global_avg = data['summary'].get('global_average_price_eur', 0)
    
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MLS Sentiment Analysis Chart</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        :root {
            --bg: #f5f5f7;
            --card-bg: #ffffff;
            --text: #1d1d1f;
            --text-secondary: #6e6e73;
            --border: #e5e5e7;
            --green: #34c759;
            --red: #ff3b30;
            --blue: #4A90E2;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #121214;
                --card-bg: #1c1c1e;
                --text: #f5f5f7;
                --text-secondary: #a1a1a6;
                --border: #38383a;
                --green: #30d158;
                --red: #ff453a;
                --blue: #64a8f0;
            }
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--bg);
            color: var(--text);
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: var(--text);
            margin-bottom: 8px;
        }
        .subtitle {
            text-align: center;
            color: var(--text-secondary);
            margin-bottom: 30px;
            font-size: 14px;
        }
        .summary-banner {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 15px;
        }
        .summary-item {
            text-align: center;
        }
        .summary-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--text);
        }
        .summary-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .chart-wrapper {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .chart-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 4px;
        }
        .chart-subtitle {
            font-size: 12px;
            color: var(--text-secondary);
            margin-bottom: 15px;
        }
        canvas {
            max-height: 400px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 MLS Sentiment Analysis</h1>
        <div class="subtitle">Analisi in tempo reale del mercato MLS in-season</div>
        
        <div class="summary-banner">
            <div class="summary-item">
                <div class="summary-value">__GLOBAL_AVG__ EUR</div>
                <div class="summary-label">Prezzo medio</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">__GLOBAL_TREND_EMOJI__ __GLOBAL_TREND_PCT__%</div>
                <div class="summary-label">Trend mercato</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">__TOTAL_PLAYERS__</div>
                <div class="summary-label">Giocatori tracciati</div>
            </div>
        </div>
        
        <div class="chart-wrapper">
            <div class="chart-title">🎯 Migliori Opportunità di Acquisto</div>
            <div class="chart-subtitle">Sconto % rispetto alla media storica — barre verdi = sotto la media (occasione), rosse = sopra la media</div>
            <canvas id="opportunityChart"></canvas>
        </div>
        
        <div class="chart-wrapper">
            <div class="chart-title">🏷️ Andamento per Fascia di Livello</div>
            <div class="chart-subtitle">Sconto/rialzo medio per fascia di prezzo — capisci se sta calando tutto il mercato o solo una fascia specifica</div>
            <canvas id="tierChart"></canvas>
            <div id="tierLegend" style="display:flex; flex-wrap:wrap; gap:10px; margin-top:15px; justify-content:center;"></div>
        </div>
        
        <div class="chart-wrapper">
            <div class="chart-title">Prezzo Medio per Squadra</div>
            <canvas id="teamChart"></canvas>
        </div>
    </div>
    
    <script>
        const teamsData = __TEAMS_DATA_JSON__;
        const opportunitiesData = __OPPORTUNITIES_DATA_JSON__;
        const tierData = __TIER_DATA_JSON__;
        
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const textColor = isDark ? '#f5f5f7' : '#1d1d1f';
        const gridColor = isDark ? '#38383a' : '#e5e5e7';
        const greenColor = isDark ? '#30d158' : '#34c759';
        const redColor = isDark ? '#ff453a' : '#ff3b30';
        const blueColor = isDark ? '#64a8f0' : '#4A90E2';
        
        Chart.defaults.color = textColor;
        Chart.defaults.borderColor = gridColor;
        
        // Grafico opportunità: sconto % per giocatore, colorato in base a sopra/sotto media
        const oppLabels = opportunitiesData.map(o => o.name + ' (' + o.team + ')');
        const oppValues = opportunitiesData.map(o => o.change_pct);
        const oppColors = oppValues.map(v => v < 0 ? greenColor : redColor);
        
        const ctxOpp = document.getElementById('opportunityChart').getContext('2d');
        new Chart(ctxOpp, {
            type: 'bar',
            data: {
                labels: oppLabels,
                datasets: [{
                    label: 'Sconto vs media storica (%)',
                    data: oppValues,
                    backgroundColor: oppColors,
                    borderRadius: 4,
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const o = opportunitiesData[ctx.dataIndex];
                                return o.change_pct.toFixed(1) + '% — Prezzo: ' + o.price.toFixed(2) + 
                                       ' EUR (media: ' + o.mean.toFixed(2) + ' EUR, ' + o.occurrences + ' occorrenze)';
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {color: gridColor},
                        title: {display: true, text: '% sconto (negativo = sotto media, buona occasione)'}
                    },
                    y: {grid: {display: false}},
                },
            },
        });
        
        // Grafico fasce di prezzo: sconto medio per fascia, colore crescente rosso->verde
        const tierLabels = tierData.map(t => t.name + ' (' + t.range + ' EUR)');
        const tierValues = tierData.map(t => t.avg_change);
        const tierColors = tierData.map(t => t.color);
        
        const ctxTier = document.getElementById('tierChart').getContext('2d');
        new Chart(ctxTier, {
            type: 'bar',
            data: {
                labels: tierLabels,
                datasets: [{
                    label: 'Sconto/rialzo medio (%)',
                    data: tierValues,
                    backgroundColor: tierColors,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const t = tierData[ctx.dataIndex];
                                return t.avg_change.toFixed(1) + '% medio — ' + t.count + ' carte in questa fascia';
                            }
                        }
                    }
                },
                scales: {
                    y: {grid: {color: gridColor}, title: {display: true, text: '% sconto medio dalla media storica'}},
                    x: {grid: {display: false}},
                },
            },
        });
        
        // Legenda colorata sotto il grafico fasce
        const legendDiv = document.getElementById('tierLegend');
        tierData.forEach(t => {
            const badge = document.createElement('div');
            badge.style.cssText = 'padding:6px 12px; border-radius:20px; font-size:12px; font-weight:600; color:white; background:' + t.color;
            badge.textContent = t.name + ': ' + t.count + ' carte';
            legendDiv.appendChild(badge);
        });
        
        // Grafico prezzo medio per squadra
        const teamLabels = Object.keys(teamsData).sort();
        const teamAvgs = teamLabels.map(t => teamsData[t].avg.toFixed(2));
        
        const ctx1 = document.getElementById('teamChart').getContext('2d');
        new Chart(ctx1, {
            type: 'bar',
            data: {
                labels: teamLabels,
                datasets: [{
                    label: 'Average Price (EUR)',
                    data: teamAvgs,
                    backgroundColor: blueColor,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                },
                scales: {
                    y: {beginAtZero: true, grid: {color: gridColor}},
                    x: {grid: {display: false}},
                },
            },
        });
    </script>
</body>
</html>
"""
    
    html_content = html_content.replace('__TEAMS_DATA_JSON__', json.dumps(teams_data))
    html_content = html_content.replace('__OPPORTUNITIES_DATA_JSON__', json.dumps(top_opportunities))
    html_content = html_content.replace('__TIER_DATA_JSON__', json.dumps(tier_chart_data))
    html_content = html_content.replace('__GLOBAL_AVG__', f"{global_avg:.2f}")
    trend_emoji = {'STRONG_DESCENDING': '📉', 'DESCENDING': '📉', 'STABLE': '➡️', 'ASCENDING': '📈', 'STRONG_ASCENDING': '📈'}.get(global_trend, '➡️')
    html_content = html_content.replace('__GLOBAL_TREND_EMOJI__', trend_emoji)
    html_content = html_content.replace('__GLOBAL_TREND_PCT__', f"{global_trend_pct:+.1f}")
    total_players = sum(len(td.get('players', {})) for td in data['teams'].values())
    html_content = html_content.replace('__TOTAL_PLAYERS__', str(total_players))
    
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
