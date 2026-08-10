"""
Tracker: Analisi profit carte mie

Scansiona TUTTE le carte dell'utente, le confronta col prezzo più basso del mercato.
Se ho un profit (prezzo_acquisto < prezzo_market), manda notifica.

FIX 18/07 (richiesta esplicita dell'utente, "il bot deve analizzare SEMPRE tutte le carte,
deve ignorare solo quelle che ha già rilevato in profitto"): la versione precedente segnava
come "già analizzata" (e quindi saltava per sempre) OGNI carta processata almeno una volta,
profittevole o no. Rischio reale: una carta in perdita al primo controllo ma che in seguito
sale di prezzo di mercato non veniva MAI più ricontrollata, perdendo l'occasione. Ora si
ignorano SOLO le carte già trovate in profitto e già notificate (non ha senso ri-notificarle
all'infinito) -- tutte le altre (in perdita, o senza prezzo di acquisto disponibile) vengono
sempre rimesse in coda per il prossimo giro. Dato che scansionare 1900+ carte per intero ad
ogni run sarebbe lento, si usa un cursore persistente che avanza di CARDS_TO_SCAN carte ad
ogni run e riparte da capo una volta arrivato in fondo alla lista (rotazione continua) --
cosi' TUTTE le carte vengono ricontrollate nel tempo, non solo le prime N per sempre.

FIX 18/07 (bug prezzo acquisto): la query precedente (anyCard.tokenTransfers con
buyer/seller/salePrice) non esiste nello schema ("Field 'tokenTransfers' doesn't exist on
type 'AnyCardInterface'", suggerimento dell'errore: 'tokenOwner'), quindi ogni carta finiva
sempre in backlog. Sostituita con track.fetch_user_trades(), la stessa query gia' collaudata
in produzione (snipe_pattern_analysis.py) che restituisce TUTTA la cronologia acquisti/vendite
di un manager in un'unica query paginata (molto piu' efficiente di una query per carta).

FIX 10/08 (richiesta esplicita dell'utente, 3 modifiche testate in locale sull'account reale):
1) get_market_min_price non rifa' piu' la query anyCard->anyPlayer.slug per un dato gia' noto
   dal chiamante (player_slug arriva direttamente dalla carta) -- dimezza le query per carta.
2) Le carte SENZA prezzo di acquisto attribuibile (probabile craft/premio, non un vero
   acquisto) non vengono piu' scartate a priori: si guarda comunque il loro prezzo di mercato e,
   se sopra MIN_PROFIT_EUR, si notificano come "craft/premio di valore" (vedi
   send_craft_notifications), non come "profit" in senso stretto. Caso reale verificato:
   sergi-dominguez-viloria-2026-limited-121, zero transazioni in storico, market 21.05€.
3) Grazie al fix (1), un giro completo delle ~2000 carte reali sta in circa 12-13 minuti
   (misurato in locale: overhead fisso ~57s + ~0.34s/carta) -- CARDS_TO_SCAN di default e il
   timeout del workflow sono stati alzati di conseguenza per fare un giro completo ad ogni run
   invece che a rotazione su piu' run (l'utente lancia il workflow manualmente ~1 volta a
   settimana, niente cron).
4) Le notifiche non sono piu' blocchi di messaggi Telegram (uno per carta) ma UN report HTML
   statico con tutte le carte in un'unica tabella (link cliccabile alla carta, prezzo
   d'acquisto se noto, margine) -- vedi generate_and_send_report/build_html_report. Il file
   viene committato dal workflow e il messaggio Telegram contiene solo il link (stesso schema
   raw.githack.com gia' collaudato in produzione da bot_profit_telegram_notify.py).
5) Le carte SENZA prezzo di acquisto NON sono tutte craft/premio: alcune sono ricevute in
   SCAMBIO carta-per-carta (caso reale verificato: brian-schwake-2025-limited-106, zero
   trade visibili ma ottenuta cedendo altre carte, non gratis). find_swap_received_slugs
   distingue i due casi leggendo entrambi i lati di ogni offerta grezza (fetch_user_trades
   non lo permette, vede solo un lato per offerta) -- le carte da scambio vengono escluse
   del tutto, mai trattate come craft.
6) Le carte vinte all'ASTA sono un TERZO canale di acquisto invisibile a
   build_purchase_price_map (user.trades vede solo TokenOffer, un'asta e' un tipo diverso).
   Caso reale verificato: seung-hyun-jung-2026-limited-187, vinta a 1.98e, zero trade
   visibili -- sarebbe finita tra i craft/premio per errore. build_auction_price_map legge
   user.tokenAuctions (scoperto per tentativi, introspection disabilitata) e aggiunge il
   prezzo della migliore offerta (bestBid) alla stessa mappa prezzi d'acquisto.
"""
import os
import json
from datetime import datetime, timedelta
import track

MANAGER_SLUG = 'crowss'
# FIX 18/07: track.send_telegram_msg(msg) non accetta kwargs token/chat_id -- legge da
# track.TELEGRAM_TOKEN/track.TELEGRAM_CHAT_ID (i suoi globali di modulo, popolati dalle env
# var TELEGRAM_TOKEN/TELEGRAM_CHAT_ID). Stesso schema di manager_bundle_scan.py: il workflow
# .yml mappa i secret BUNDLE_TELEGRAM_TOKEN/BUNDLE_TELEGRAM_CHAT_ID su QUELLE env var (non su
# BUNDLE_TELEGRAM_TOKEN/BUNDLE_TELEGRAM_CHAT_ID), cosi' i messaggi arrivano nello stesso canale
# del bundle scanner senza bisogno di kwargs custom qui.

# Salva SOLO le carte gia' trovate in profitto e notificate (skip permanente -- non ha senso
# ri-notificare la stessa carta ad ogni run).
PROFITABLE_FOUND_FILE = '.my_cards_profit_found.txt'
# Cursore persistente: indice da cui riprendere la scansione al prossimo run (rotazione
# continua sulla lista di carte NON ancora trovate in profitto, cosi' nel tempo si ricontrollano
# tutte, non solo le prime N per sempre).
CURSOR_FILE = '.my_cards_profit_cursor.txt'
# Backlog solo informativo (carte per cui non si e' trovato un prezzo di acquisto nell'ultimo
# tentativo) -- NON usato per saltare carte, solo per diagnostica nei log.
UNSCANNED_BACKLOG_FILE = '.my_cards_profit_backlog.txt'

# Input dal workflow. FIX 10/08: default alzato da 10 a 3000 (sopra le ~2000 carte reali, con
# margine di crescita) per coprire l'intero archivio in un solo giro invece che a rotazione su
# piu' run manuali -- vedi nota FIX 10/08 in cima al file per i tempi misurati.
CARDS_TO_SCAN = int(os.environ.get('MY_CARDS_PROFIT_SCAN_COUNT', '3000'))
# FIX 18/07 (richiesta esplicita dell'utente): non segnalare se il profit assoluto e' sotto
# questa soglia -- pochi centesimi non sono un vero affare, solo rumore.
MIN_PROFIT_EUR = float(os.environ.get('MY_CARDS_PROFIT_MIN_EUR', '0.50'))
# Finestra e paginazione per lo storico acquisti (track.fetch_user_trades) -- di default molto
# ampia (anni), perche' ci serve la cronologia acquisti COMPLETA per calcolare il profit, non
# solo gli ultimi giorni come nell'uso originale (snipe pattern) di questa funzione.
PURCHASE_HISTORY_WINDOW_DAYS = int(os.environ.get('MY_CARDS_PROFIT_HISTORY_DAYS', '3650'))
PURCHASE_HISTORY_MAX_PAGES = int(os.environ.get('MY_CARDS_PROFIT_HISTORY_MAX_PAGES', '100'))


def log(msg):
    print(f"[my-cards-profit] {msg}")


def load_profitable_found():
    """Carica lo slug delle carte gia' trovate in profitto (skip permanente)."""
    if not os.path.exists(PROFITABLE_FOUND_FILE):
        return set()
    try:
        with open(PROFITABLE_FOUND_FILE) as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def save_profitable_found(slugs):
    """Aggiunge slug al file delle carte gia' trovate in profitto (append)."""
    if not slugs:
        return
    with open(PROFITABLE_FOUND_FILE, 'a') as f:
        for slug in slugs:
            f.write(slug + '\n')


def load_cursor():
    """Carica l'indice da cui riprendere la scansione."""
    if not os.path.exists(CURSOR_FILE):
        return 0
    try:
        with open(CURSOR_FILE) as f:
            return int(f.read().strip() or '0')
    except Exception:
        return 0


def save_cursor(cursor):
    """Salva l'indice per il prossimo run."""
    with open(CURSOR_FILE, 'w') as f:
        f.write(str(cursor))


def load_backlog():
    """Carica il backlog (solo informativo) di carte senza prezzo di acquisto trovato."""
    if not os.path.exists(UNSCANNED_BACKLOG_FILE):
        return {}
    try:
        with open(UNSCANNED_BACKLOG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_backlog(backlog):
    """Salva il backlog (solo informativo, non usato per saltare carte)."""
    with open(UNSCANNED_BACKLOG_FILE, 'w') as f:
        json.dump(backlog, f, indent=2)


def get_all_my_cards():
    """Fetch tutte le carte di 'crowss'.
    FIX 18/07: 'status' non esiste su AnyCardInterface (l'errore GraphQL bloccava l'intera
    query, quindi 0 carte trovate ad ogni run) -- rimosso. 'amountInCents' su liveSingleSaleOffer
    non esiste nemmeno lui (stesso bug gia' corretto in my_cards_underpriced.py) ed era comunque
    inutilizzato qui, rimosso anche quello. 'createdAt' NEMMENO esiste su AnyCardInterface
    (stesso errore, stesso blocco) -- rimosso anche quello: l'ordinamento "piu' recenti prima"
    e' gia' garantito server-side da sorts: user_owner.from DESC, non serve un campo data
    lato client per rifare lo stesso ordinamento in Python. Introspection disabilitata: senza
    un campo/stato "sealed" noto e funzionante, per ora non filtriamo le carte sealed (rischio
    di includerne qualcuna per errore e' preferibile a bloccare l'intero tracker su un campo
    indovinato)."""
    log("Ricerca tutte le carte...")

    query = """
    query MyAllCards($userSlug: String!, $page: Int!, $pageSize: Int!) {
      user(slug: $userSlug) {
        searchCards(
          rarity: limited
          sport: FOOTBALL
          query: ""
          page: $page
          pageSize: $pageSize
          sorts: [{field: "user_owner.from", direction: DESC}]
        ) {
          hits {
            slug
            sport
            rarityTyped
            inSeasonEligible
            sportSeason { name }
            anyPlayer { slug }
            ... on Card { pack { id } }
          }
          nbHits
        }
      }
    }
    """

    all_cards = []
    page = 1
    max_pages = 100

    while page <= max_pages:
        try:
            data = track.graphql_query(query, {
                "userSlug": "crowss",
                "page": page,
                "pageSize": 100
            })
            if data.get('errors'):
                log(f"Errore GraphQL: {data['errors']}")
                break

            hits = (data.get('data', {}).get('user', {}).get('searchCards', {}).get('hits', []))
            if not hits:
                break

            all_cards.extend(hits)

            page += 1
        except Exception as e:
            log(f"Eccezione durante fetch carte pagina {page}: {e}")
            break

    log(f"Trovate {len(all_cards)} carte")
    return all_cards


def build_purchase_price_map_and_swaps(eth_rate):
    """Un solo giro sulla cronologia trade (query bulk paginata, UNA sola volta) che estrae
    DUE cose insieme, per non raddoppiare il costo della query:
    1) slug_carta -> prezzo_pagato (stessa logica di track.fetch_user_trades: solo le
       transazioni 'buy' con un prezzo attribuibile, bundle multi-carta esclusi perche' il
       prezzo aggregato non e' scomponibile per singola carta).
    2) slug delle carte ricevute in SCAMBIO carta-per-carta (richiesta esplicita dell'utente,
       caso reale verificato brian-schwake-2025-limited-106: nessun prezzo d'acquisto
       attribuibile, MA non e' un craft/premio -- ottenuta cedendo altre carte in cambio, un
       costo reale c'e', solo non esprimibile in euro).
    FIX 10/08: prima erano due funzioni separate, ciascuna con la sua query paginata sulla
    stessa identica cronologia -- track.fetch_user_trades() per il prezzo (che pero' registra,
    per ogni offerta, SOLO il lato che il manager DA' o SOLO quello che RICEVE, mai entrambi,
    quindi non basta per distinguere gli scambi) e una query grezza duplicata per gli scambi
    (serve leggere ENTRAMBI i lati della stessa offerta, dato che fetch_user_trades scarta
    quello che non usa). Unite in un solo giro qui, con processing locale che replica la
    logica di attribuzione prezzo di track.fetch_user_trades (stessa attribuzione, stesso
    principio di esclusione bundle) invece di chiamarla -- serve accesso ai dati grezzi che
    quella funzione non espone. Se la stessa carta compare piu' volte, vince l'acquisto piu'
    recente (i nodi sono ordinati dal piu' recente al piu' vecchio)."""
    log(f"Ricerca cronologia acquisti/scambi (finestra {PURCHASE_HISTORY_WINDOW_DAYS} giorni, "
        f"max {PURCHASE_HISTORY_MAX_PAGES} pagine)...")
    query = """
    query SnipeUserTrades($slug: String!, $after: String) {
      user(slug: $slug) {
        slug
        trades(sport: FOOTBALL, after: $after, first: 100) {
          nodes {
            ... on TokenOffer {
              transactionDate
              sender { ... on User { slug } }
              senderSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
              receiver { ... on User { slug } }
              receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
            }
          }
          pageInfo { endCursor hasNextPage }
        }
      }
    }
    """
    cutoff = datetime.now() - timedelta(days=PURCHASE_HISTORY_WINDOW_DAYS)
    price_map = {}
    swap_received = set()
    bundle_skipped = 0
    total_trades = 0
    after = None
    try:
        for _ in range(PURCHASE_HISTORY_MAX_PAGES):
            data = track.graphql_query(query, {"slug": MANAGER_SLUG, "after": after})
            if not data or data.get('errors'):
                log(f"Errore GraphQL cronologia trade: {data.get('errors') if data else 'nessuna risposta'}")
                break
            trades = ((data.get('data') or {}).get('user') or {}).get('trades') or {}
            nodes = trades.get('nodes') or []
            if not nodes:
                break
            stop = False
            for n in nodes:
                try:
                    dt = datetime.fromisoformat(
                        (n.get('transactionDate') or '').replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    continue
                if dt < cutoff:
                    stop = True
                    continue
                total_trades += 1

                sender = n.get('sender') or {}
                receiver = n.get('receiver') or {}
                sender_side = n.get('senderSide') or {}
                receiver_side = n.get('receiverSide') or {}
                sender_cards = sender_side.get('anyCards') or []
                receiver_cards = receiver_side.get('anyCards') or []

                # --- (2) rilevazione scambio: entrambi i lati hanno carte ---
                if sender_cards and receiver_cards:
                    if sender.get('slug') == MANAGER_SLUG:
                        swap_received.update(c.get('slug') for c in receiver_cards if c.get('slug'))
                    elif receiver.get('slug') == MANAGER_SLUG:
                        swap_received.update(c.get('slug') for c in sender_cards if c.get('slug'))

                # --- (1) prezzo di acquisto (stessa logica di track.fetch_user_trades) ---
                if sender.get('slug') == MANAGER_SLUG:
                    is_selling = bool(sender_cards)
                    cards = sender_cards if is_selling else receiver_cards
                    pay_amounts = receiver_side.get('amounts') if is_selling else sender_side.get('amounts')
                elif receiver.get('slug') == MANAGER_SLUG:
                    is_selling = bool(receiver_cards)
                    cards = receiver_cards if is_selling else sender_cards
                    pay_amounts = sender_side.get('amounts') if is_selling else receiver_side.get('amounts')
                else:
                    continue
                if is_selling or not cards:
                    continue  # qui interessano solo gli acquisti (role='buy')
                if len(cards) > 1:
                    bundle_skipped += 1
                    continue  # bundle multi-carta: prezzo aggregato non attribuibile, vedi track.py
                price = track.eur_price_from_amounts(pay_amounts, eth_rate)
                if price is None:
                    continue
                card_slug = cards[0].get('slug')
                if card_slug and card_slug not in price_map:
                    price_map[card_slug] = price

            if stop or not (trades.get('pageInfo') or {}).get('hasNextPage'):
                break
            after = (trades.get('pageInfo') or {}).get('endCursor')
        else:
            # FIX 10/08 (nato dal caso reale heung-min-son-2025-limited-226, acquistata a 20e
            # ma non trovata in un run: il ciclo aveva esaurito PURCHASE_HISTORY_MAX_PAGES
            # SENZA che hasNextPage diventasse false, troncando in silenzio la cronologia molto
            # prima della finestra di 10 anni -- nessuna eccezione, nessun log, solo dati
            # mancanti. for...else scatta SOLO se il ciclo finisce tutte le iterazioni senza
            # mai fare 'break', cioe' esattamente questo caso.
            log(f"⚠️ ATTENZIONE: esauriti tutti i {PURCHASE_HISTORY_MAX_PAGES} pagine senza "
                f"arrivare in fondo alla cronologia (hasNextPage ancora true) -- la mappa "
                f"prezzi d'acquisto e' TRONCATA, alza PURCHASE_HISTORY_MAX_PAGES")
    except Exception as e:
        log(f"Eccezione durante fetch cronologia acquisti/scambi: {e}")

    log(f"Cronologia trade: {total_trades} transazioni totali, {len(price_map)} carte con "
        f"prezzo di acquisto attribuibile, {bundle_skipped} scartate (acquisti in bundle), "
        f"{len(swap_received)} carte ricevute in scambio")
    return price_map, swap_received


def build_auction_price_map(eth_rate):
    """Costruisce slug_carta -> prezzo_pagato per le carte vinte all'ASTA (richiesta esplicita
    dell'utente, caso reale verificato seung-hyun-jung-2026-limited-187: bestBid 1.98e,
    "l'ho pagato, comprato in asta" -- confermato, ma invisibile a build_purchase_price_map
    perche' user(slug).trades restituisce solo nodi TokenOffer, e un'asta vinta NON e' un
    TokenOffer: e' un tipo completamente diverso (TokenAuction/EnglishAuction), su un campo
    diverso dello user (tokenAuctions, non trades). Scoperto per tentativi (introspection
    disabilitata): 'tokenAuctions' suggerito dall'errore su un campo indovinato
    ('wonAuctions'), poi bestBid.amounts (non 'amount') per il prezzo vincente.
    Nessun campo 'winner'/'bidder' esposto nello schema pubblico per dire ESPLICITAMENTE se
    la carta l'ho vinta io o un altro concorrente piu' alto -- euristica usata (stessa logica
    gia' implicita per gli scambi): l'asta e' chiusa (open=False, cancelled=False) E la carta
    e' ATTUALMENTE nella mia collezione (il chiamante controlla solo gli slug che possiede
    davvero) => l'ho vinta io, altrimenti non la possiederei. Se la stessa carta compare in
    piu' aste (rivenduta e riacquistata), vince l'asta piu' recente (i nodi sono ordinati dal
    piu' recente al piu' vecchio, come tokenAuctions)."""
    log(f"Ricerca aste vinte (finestra {PURCHASE_HISTORY_WINDOW_DAYS} giorni, "
        f"max {PURCHASE_HISTORY_MAX_PAGES} pagine)...")
    query = """
    query UserTokenAuctions($slug: String!, $after: String) {
      user(slug: $slug) {
        tokenAuctions(first: 100, after: $after) {
          nodes {
            endDate
            open
            cancelled
            anyCards { slug }
            bestBid { amounts { eurCents wei usdCents gbpCents lamport } }
          }
          pageInfo { endCursor hasNextPage }
        }
      }
    }
    """
    cutoff = datetime.now() - timedelta(days=PURCHASE_HISTORY_WINDOW_DAYS)
    price_map = {}
    after = None
    total_auctions = 0
    try:
        for _ in range(PURCHASE_HISTORY_MAX_PAGES):
            data = track.graphql_query(query, {"slug": MANAGER_SLUG, "after": after})
            if not data or data.get('errors'):
                log(f"Errore GraphQL ricerca aste: {data.get('errors') if data else 'nessuna risposta'}")
                break
            conn = ((data.get('data') or {}).get('user') or {}).get('tokenAuctions') or {}
            nodes = conn.get('nodes') or []
            if not nodes:
                break
            stop = False
            for n in nodes:
                total_auctions += 1
                try:
                    dt = datetime.fromisoformat(
                        (n.get('endDate') or '').replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    continue
                if dt < cutoff:
                    stop = True
                    continue
                if n.get('open') or n.get('cancelled'):
                    continue  # non ancora chiusa o annullata: nessun vincitore definitivo
                bid = n.get('bestBid')
                if not bid:
                    continue
                price = track.eur_price_from_amounts(bid.get('amounts'), eth_rate)
                if price is None:
                    continue
                for c in (n.get('anyCards') or []):
                    card_slug = c.get('slug')
                    if card_slug and card_slug not in price_map:
                        price_map[card_slug] = price
            if stop or not (conn.get('pageInfo') or {}).get('hasNextPage'):
                break
            after = (conn.get('pageInfo') or {}).get('endCursor')
    except Exception as e:
        log(f"Eccezione durante ricerca aste: {e}")

    log(f"Aste esaminate: {total_auctions}, {len(price_map)} carte con prezzo d'asta attribuibile")
    return price_map


def get_market_min_price(player_slug, season_type, eth_rate):
    """Ottieni il prezzo più basso del mercato per questo giocatore, tra gli
    annunci aperti con la stessa categoria (in_season/classic) -- stesso schema query di
    track.py (fetch_all_live_offers/get_live_min_offer): la carta messa in vendita sta in
    senderSide.anyCards, il prezzo chiesto sta in receiverSide.amounts. receiverSide.anyCards
    NON vuoto significa scambio carta-per-carta (nessun prezzo in denaro, va escluso).
    FIX 18/07 (v1): la versione precedente cercava card_slug dentro receiverSide.anyCards (il
    lato del pagamento, quasi sempre vuoto per una vendita a prezzo fisso) invece che in
    senderSide.anyCards (il lato della carta venduta) -- il match falliva quasi sempre,
    lasciando il prezzo di mercato sempre a None.
    FIX 18/07 (v2, caso reale cheol-woo-park-2024-limited-143, richiesta esplicita dell'utente):
    confrontare inSeasonEligible con un uguaglianza diretta (True/False) e' fragile -- questo
    campo puo' risultare None per alcuni annunci (dato non sempre popolato da Sorare), e in quel
    caso l'annuncio passava comunque il filtro per errore, mescolando prezzi in_season con
    carte classic dello stesso giocatore (la carta 2024/classic dell'utente veniva confrontata
    con un annuncio in_season a 4.28EUR invece che con la sua vera categoria). Fix: usa
    track.season_type_for_card (stessa funzione, stesso fallback su sportSeason.name gia'
    collaudato in track.py) sia per la mia carta che per ogni candidato, e confronta le
    CATEGORIE ('in_season'/'classic') invece del booleano grezzo.
    FIX 18/07 (v3, richiesta esplicita dell'utente): esclude gli annunci del manager
    'privacy' (vende solo in ETH, non e' un'opzione utilizzabile per l'utente) dal calcolo
    del prezzo minimo di mercato -- stesso blacklist condiviso di track.py.
    FIX 10/08 (richiesta esplicita dell'utente): il chiamante ha GIA' player_slug (viene dalla
    stessa query bulk di get_all_my_cards, campo anyPlayer.slug) -- prima si rifaceva una query
    anyCard(slug)->anyPlayer.slug per ritrovare un dato gia' in mano, raddoppiando le chiamate
    GraphQL per ogni carta processata. Ora si passa player_slug direttamente.
    FIX 10/08 bis (bug reale trovato ispezionando dong-kyung-lee-2026-limited-104 sul mercato
    vero: la pagina mostrava annunci in_season a 15.08€/16.09€/17.30€, ma questa funzione
    restituiva 25.00€ come minimo): la query leggeva SOLO receiverSide.amounts.eurCents,
    ignorando gli annunci prezzati in USD/GBP/ETH/SOL (eurCents torna null in quel caso, non
    "annuncio assente" -- STESSO bug gia' documentato e risolto in track.py il 17/07, caso
    Jhegson Sebastian Mendez, mai applicato pero' a questo file). Ora si richiedono tutti i
    campi valuta e si usa track.eur_price_from_amounts (stessa funzione, stessa conversione)
    invece di leggere eurCents a mano."""
    try:
        offers_query = """
        query LiveOffers($slug: String!, $n: Int!) {
          tokens {
            liveSingleSaleOffers(playerSlug: $slug, last: $n) {
              nodes {
                status
                sender { ... on User { slug } }
                receiverSide {
                  amounts { eurCents wei usdCents gbpCents lamport }
                  anyCards { slug }
                }
                senderSide {
                  anyCards {
                    slug
                    rarityTyped
                    sport
                    inSeasonEligible
                    sportSeason { name }
                  }
                }
              }
            }
          }
        }
        """

        data = track.graphql_query(offers_query, {"slug": player_slug, "n": 50})
        if data.get('errors'):
            return None

        nodes = (data.get('data', {}).get('tokens', {})
                .get('liveSingleSaleOffers', {}).get('nodes', []))

        if not nodes:
            return None

        prices = []
        for node in nodes:
            if node.get('status') != 'opened':
                continue
            seller_slug = ((node.get('sender') or {}).get('slug') or '').lower()
            if seller_slug in track.BLACKLISTED_SELLER_SLUGS:
                continue
            # scambio carta-per-carta (nessun prezzo in denaro): escluso, stesso filtro di track.py
            if (node.get('receiverSide') or {}).get('anyCards'):
                continue
            sender_cards = (node.get('senderSide') or {}).get('anyCards') or []
            match = None
            for c in sender_cards:
                if c.get('rarityTyped') != 'limited':
                    continue
                if c.get('sport') != 'FOOTBALL':
                    continue
                c_season_name = (c.get('sportSeason') or {}).get('name', 'unknown')
                if track.season_type_for_card(c, c_season_name) != season_type:
                    continue
                match = c
                break
            if not match:
                continue
            price = track.eur_price_from_amounts(node.get('receiverSide', {}).get('amounts'), eth_rate)
            if price:
                prices.append(price)

        return min(prices) if prices else None
    except Exception as e:
        log(f"Eccezione durante fetch market price per {player_slug}: {e}")
        return None


def run_profit_scan():
    """Scansiona le carte e calcola profit. Ignora SOLO le carte gia' trovate in profitto (o
    segnalate come craft di valore, vedi sotto) e gia' notificate -- tutte le altre vengono
    sempre rimesse in coda, tramite un cursore rotante, cosi' una carta prima in perdita che poi
    diventa profittevole non viene mai persa.

    FIX 10/08 (richiesta esplicita dell'utente, caso reale verificato
    sergi-dominguez-viloria-2026-limited-121: pack=None, createdAt presente, ZERO transazioni
    nello storico crowss): le carte senza prezzo di acquisto attribuibile (niente 'buy' in
    track.fetch_user_trades) sono in larghissima parte carte CRAFTATE con essenze o vinte come
    premio (confermato: 59-81% di ogni batch da 100, contro un 3.7% di scarto per soli acquisti
    bundle -- il grosso non e' spiegato dai bundle). Prima venivano scartate PRIMA di guardare
    il prezzo di mercato (non hanno un costo in EUR da confrontare). Ora, per queste carte, si
    guarda comunque il prezzo minimo di mercato: se supera MIN_PROFIT_EUR viene segnalato come
    valore di realizzo potenziale (non un "profit" in senso stretto, perche' il costo reale e'
    in essenze non in euro). Sorare non espone via API un campo che dica esplicitamente
    "craftata" (verificato nello schema pubblico da crafted_card_scanner.py, 19/07): 'pack'
    valorizzato = quasi certamente da un pacchetto acquistato; 'pack' nullo = craft o premio
    plausibile, non certezza. Lo includiamo nel messaggio solo come indizio, non come fatto."""
    log(f"Inizio scan profit ({CARDS_TO_SCAN} carte per run)...")

    profitable_found = load_profitable_found()
    cursor = load_cursor()

    all_cards = get_all_my_cards()
    if not all_cards:
        log("Nessuna carta trovata")
        return

    # Escludi SOLO le carte gia' trovate in profitto/valore e notificate -- tutte le altre
    # restano candidate per la rotazione (anche quelle gia' controllate in passato senza esito).
    candidates = [c for c in all_cards if c.get('slug') not in profitable_found]
    log(f"{len(all_cards)} carte totali, {len(all_cards) - len(candidates)} gia' notificate "
        f"(escluse), {len(candidates)} candidate per questo giro")

    if not candidates:
        log("Nessuna carta candidata (tutte gia' notificate?)")
        return

    # Cursore rotante: riprende da dove si era arrivati, ricomincia da capo se supera la fine
    # della lista -- cosi' nel tempo TUTTE le carte candidate vengono ricontrollate.
    if cursor >= len(candidates):
        cursor = 0

    # Tasso ETH/EUR preso una volta sola (FIX 10/08: serve a track.eur_price_from_amounts per
    # convertire gli annunci prezzati in ETH/USD/GBP/SOL, vedi docstring get_market_min_price).
    eth_rate = track.get_eth_rate()

    # Prezzi di acquisto (query bulk, un solo giro) + carte ricevute in scambio (escluse dal
    # craft/premio, vedi docstring build_purchase_price_map_and_swaps).
    purchase_price_map, swap_received_slugs = build_purchase_price_map_and_swaps(eth_rate)
    # Carte vinte all'asta (richiesta esplicita utente, caso reale seung-hyun-jung-2026-
    # limited-187, bestBid 1.98e): invisibili a user.trades (un'asta vinta e' un tipo diverso,
    # TokenAuction non TokenOffer) -- vedi docstring build_auction_price_map. Priorita' al
    # prezzo da trade normale se per assurdo esistesse gia' (non dovrebbe capitare, canali di
    # acquisto diversi per la stessa carta).
    auction_price_map = build_auction_price_map(eth_rate)
    for slug, price in auction_price_map.items():
        purchase_price_map.setdefault(slug, price)

    profitable = []
    craft_value = []
    newly_notified_slugs = []
    updated_backlog = {}

    batch = []
    idx = cursor
    while len(batch) < CARDS_TO_SCAN and len(batch) < len(candidates):
        batch.append(candidates[idx])
        idx = (idx + 1) % len(candidates)

    log(f"Batch di questo giro: {len(batch)} carte (da indice {cursor})")

    for i, card in enumerate(batch, 1):
        card_slug = card.get('slug')
        player_slug = (card.get('anyPlayer') or {}).get('slug')
        log(f"Analizzando ({i}/{len(batch)}): {card_slug}")

        if not player_slug:
            log(f"  ⚠️ player_slug mancante, salto")
            continue

        purchase_price = purchase_price_map.get(card_slug)

        if purchase_price is None and card_slug in swap_received_slugs:
            # Ricevuta in scambio carta-per-carta: nessun costo in euro, ma NON e' un
            # craft/premio gratuito -- un costo reale c'e' (le carte cedute), solo non
            # quantificabile. Esclusa del tutto, niente query di mercato (richiesta esplicita
            # utente: "vanno escluse"). Non finisce nemmeno in backlog: non e' un dato mancante
            # da ritentare, e' un caso noto e permanente per questa carta.
            log(f"  \U0001F501 Ricevuta in scambio, esclusa (nessun costo in euro quantificabile)")
            continue

        # Ottieni prezzo market minimo (stessa categoria in_season/classic, FIX 18/07: match
        # per season_type invece che booleano grezzo, vedi docstring di get_market_min_price).
        # FIX 10/08: player_slug viene passato direttamente (gia' noto dalla carta), non piu'
        # ririchiesto con una query separata (vedi docstring get_market_min_price).
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        season_type = track.season_type_for_card(card, season_name)
        market_price = get_market_min_price(player_slug, season_type, eth_rate)

        if purchase_price is None:
            # Carta senza acquisto attribuibile: probabile craft/premio (vedi docstring sopra).
            if market_price is None:
                log(f"  ⚠️ Prezzo acquisto E prezzo market non trovati")
                updated_backlog[card_slug] = {
                    'reason': 'prezzo_acquisto_e_mercato_non_trovati',
                    'last_attempt': datetime.now().isoformat(),
                }
                continue
            if market_price > MIN_PROFIT_EUR:
                is_pack = card.get('pack') is not None
                log(f"  \U0001F528 CRAFT/PREMIO DI VALORE: nessun acquisto noto, market "
                    f"{market_price:.2f}€ (pack={is_pack})")
                craft_value.append({
                    'slug': card_slug,
                    'player_slug': player_slug,
                    'market_price': market_price,
                    'season': card.get('sportSeason', {}).get('name', 'N/A'),
                    'in_season': card.get('inSeasonEligible'),
                    'likely_pack': is_pack,
                })
                newly_notified_slugs.append(card_slug)
            else:
                log(f"  ➖ Nessun acquisto noto, market {market_price:.2f}€ (sotto soglia)")
            continue

        if market_price is None:
            log(f"  ⚠️ Prezzo market non trovato")
            continue

        # Calcola profit
        profit = market_price - purchase_price
        profit_percent = (profit / purchase_price * 100) if purchase_price > 0 else 0

        # FIX 18/07 (richiesta esplicita dell'utente): non segnalare se il profit assoluto e'
        # sotto MIN_PROFIT_EUR -- pochi centesimi di "profit" sono spesso solo rumore di
        # arrotondamento/differenze di 1-2 offerte, non un vero affare da cogliere.
        if profit > MIN_PROFIT_EUR:
            log(f"  ✅ PROFIT: acquistato {purchase_price:.2f}€, market {market_price:.2f}€ "
                f"(+{profit:.2f}€, {profit_percent:+.1f}%)")
            profitable.append({
                'slug': card_slug,
                'player_slug': player_slug,
                'purchase_price': purchase_price,
                'market_price': market_price,
                'profit': profit,
                'profit_percent': profit_percent,
                'season': card.get('sportSeason', {}).get('name', 'N/A'),
                'in_season': card.get('inSeasonEligible'),
            })
            newly_notified_slugs.append(card_slug)
        else:
            log(f"  ❌ No profit: acquistato {purchase_price:.2f}€, market {market_price:.2f}€ "
                f"({profit_percent:+.1f}%)")

    # Salva stato: cursore avanzato di quante carte abbiamo effettivamente processato in questo
    # giro (rotazione continua sulla lista candidati, non su all_cards).
    save_cursor(idx)
    log(f"Cursore aggiornato a {idx}/{len(candidates)} (prossimo run riparte da li')")

    if newly_notified_slugs:
        save_profitable_found(newly_notified_slugs)
        log(f"Salvate {len(newly_notified_slugs)} carte notificate (skip permanente)")

    save_backlog(updated_backlog)
    if updated_backlog:
        log(f"Backlog (solo informativo) di questo giro: {len(updated_backlog)} carte senza "
            f"prezzo di acquisto ne' di mercato")

    if not profitable and not craft_value:
        log("Nessuna carta con profit o valore craft trovata in questo giro")
        return

    log(f"Totale carte con profit: {len(profitable)}, carte craft/premio di valore: "
        f"{len(craft_value)}")
    generate_and_send_report(profitable, craft_value)


def _card_link(player_slug, card_slug):
    # FIX 10/08 (richiesta esplicita dell'utente): il link deve portare alla MIA carta (la
    # pagina "my-cards" della propria collezione, stesso pattern indicato dall'utente per
    # sergi-dominguez-viloria-2026-limited-121), non alla vetrina del mercato -- quella mostra
    # tutti gli annunci del giocatore, non la carta specifica posseduta.
    return f"https://sorare.com/it/football/my-cards/cards/limited?card={card_slug}"


def _season_label(card):
    return f"{card['season']} {'(In Season)' if card['in_season'] else '(Classic)'}"


def build_html_report(profit_cards, craft_cards):
    """Un solo file HTML statico e autosufficiente (dati incorporati, nessun caricamento
    esterno) con tutte le carte trovate in un'unica tabella -- richiesta esplicita dell'utente
    (10/08): prima arrivavano blocchi di messaggi Telegram separati per carta, uno scomodo da
    scorrere. Colonne: carta (link cliccabile alla carta su Sorare), prezzo di acquisto (solo
    se noto -- per le carte craft/premio resta '—', non l'hanno pagate), prezzo di mercato,
    margine. Righe ordinate per margine decrescente (l'affare piu' grande in cima)."""
    rows = []
    for c in profit_cards:
        rows.append({
            'slug': c['slug'], 'player_slug': c['player_slug'],
            'tipo': 'Acquistata', 'acquisto': c['purchase_price'],
            'market': c['market_price'], 'margine': c['profit'],
            'margine_pct': c['profit_percent'], 'season_label': _season_label(c),
        })
    for c in craft_cards:
        rows.append({
            'slug': c['slug'], 'player_slug': c['player_slug'],
            'tipo': 'Craft/premio', 'acquisto': None,
            'market': c['market_price'], 'margine': c['market_price'],
            'margine_pct': None, 'season_label': _season_label(c),
        })
    rows.sort(key=lambda r: r['margine'], reverse=True)

    ts_label = datetime.now().strftime('%d/%m/%Y %H:%M')
    trs = []
    for r in rows:
        acquisto_cell = f"{r['acquisto']:.2f}€" if r['acquisto'] is not None else "—"
        margine_pct = f" ({r['margine_pct']:+.1f}%)" if r['margine_pct'] is not None else ""
        link = _card_link(r['player_slug'], r['slug'])
        trs.append(
            "<tr>"
            f"<td><a href='{link}' target='_blank' rel='noopener'>{r['slug']}</a>"
            f"<div class='sub'>{r['season_label']}</div></td>"
            f"<td>{r['tipo']}</td>"
            f"<td>{acquisto_cell}</td>"
            f"<td>{r['market']:.2f}€</td>"
            f"<td class='profit'>+{r['margine']:.2f}€{margine_pct}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My Cards Profit — {ts_label}</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0f1216; color: #e6e6e6;
         margin: 0; padding: 20px; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .subtitle {{ color: #9aa4af; font-size: 13px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #262b31; }}
  th {{ color: #9aa4af; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }}
  td a {{ color: #6fd3ff; text-decoration: none; }}
  td a:hover {{ text-decoration: underline; }}
  td .sub {{ color: #6b7580; font-size: 11px; }}
  td.profit {{ color: #3ddc84; font-weight: 600; white-space: nowrap; }}
  tr:hover {{ background: #161a1f; }}
</style>
</head>
<body>
  <h1>My Cards Profit</h1>
  <div class="subtitle">{ts_label} — {len(profit_cards)} carte acquistate in profitto,
    {len(craft_cards)} carte craft/premio di valore</div>
  <table>
    <thead><tr><th>Carta</th><th>Tipo</th><th>Acquisto</th><th>Mercato</th><th>Margine</th></tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
</body>
</html>
"""


REPORT_PATH = os.path.join('scanners', 'output', 'my_cards_profit_report.html')
GIT_REF = os.environ.get('GIT_REF', 'main').strip() or 'main'
REPO_SLUG = os.environ.get('GITHUB_REPOSITORY', 'andreasalvatore93-oss/Sorare-tracker-2').strip()


def _report_viewer_url():
    """raw.githack.com serve raw.githubusercontent.com col Content-Type text/html corretto,
    cosi' il link apre la pagina renderizzata invece di scaricare il file -- stesso schema gia'
    collaudato in produzione da bot_profit_telegram_notify.py (funziona solo su repo pubblici,
    gia' verificato li')."""
    path_url = REPORT_PATH.replace(os.sep, '/')
    return f"https://raw.githack.com/{REPO_SLUG}/{GIT_REF}/{path_url}"


def generate_and_send_report(profit_cards, craft_cards):
    """Scrive il report HTML su disco (il workflow lo committa, vedi .yml) e manda UN solo
    messaggio Telegram con il link cliccabile -- sostituisce i vecchi blocchi di messaggi
    Telegram per singola carta (richiesta esplicita dell'utente, 10/08)."""
    if not profit_cards and not craft_cards:
        return
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    html = build_html_report(profit_cards, craft_cards)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f"Report HTML scritto in {REPORT_PATH}")

    msg = (
        f"<b>💰 My Cards Profit</b>\n"
        f"{len(profit_cards)} carte acquistate in profitto, {len(craft_cards)} craft/premio "
        f"di valore\n"
        f"👉 <a href='{_report_viewer_url()}'>Apri il report</a>"
    )
    track.send_telegram_msg(msg)
    log("Notifica con link al report inviata")


if __name__ == '__main__':
    run_profit_scan()
    log("Esecuzione terminata.")
