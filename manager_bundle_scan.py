"""Analisi mirata di un singolo manager Sorare (workflow MANUALE, uno-shot -- non un tracker che
ascolta in continuo come track.py/zenlock_model_tracker.py/auctions_ws_listener.py).

Richiesta esplicita dell'utente 18/07 (nata dall'osservazione del pattern "Satonio": un manager
che piazza in blocco tante carte a prezzi tondi, spesso fuorvianti -- vedi HANDOFF.md). Dato lo
slug (o l'URL del profilo) di un manager, trova tutte le sue carte Limited IN SEASON attualmente
in vendita (niente classic per ora, richiesta esplicita: "per non fare casino tracciamo solamente
le carte limited ed in season"), e per ciascuna calcola il prezzo minimo disponibile sul mercato
per lo stesso giocatore/bucket -- serve per valutare un'offerta CUMULATIVA ("pacchetto") su tutte
le sue carte in vendita insieme.

Nessuna scrittura su database: nessuno stato persistente tra un'esecuzione e l'altra, ogni run e'
autonomo (a differenza di tracker.db/auctions.db). Riusa SOLO funzioni di basso livello gia'
testate di track.py (graphql_query, get_bucket_prices, season_type_for_card,
eur_price_from_amounts via get_bucket_prices, send_telegram_msg, get_eth_rate) -- stesso identico
principio gia' seguito da zenlock_model_tracker.py, per non duplicare logica fragile.

LIMITE NOTO / DA VERIFICARE AL PRIMO RUN REALE (introspection disabilitata su tutto questo
progetto, come sempre bisogna scoprire per tentativi): non esiste -- o non e' ancora stato
scoperto -- un filtro GraphQL diretto "solo le carte attualmente in vendita" sul profilo di un
manager, anche se l'URL del sito (es. .../cards/limited?sale=true) suggerisce che esista lato
sito. Soluzione adottata, piu' pesante in numero di query ma basata SOLO su campi/query gia'
collaudati altrove in questo progetto: si scaricano TUTTE le carte Limited possedute dal manager
(stessa query gia' provata in fetch_user_recent_cards di track.py, qui riscritta aggiungendo
sportSeason/inSeasonEligible per poter distinguere in_season da classic), poi per ogni giocatore
UNICO tra queste si interroga il mercato live COMPLETO (get_bucket_prices, lo stesso dato gia'
usato da track.py/zenlock) e si incrocia per slug carta: se lo slug della carta posseduta compare
tra gli annunci live di quel giocatore, e' DAVVERO in vendita adesso, a quel prezzo -- un annuncio
ritirato o venduto sparisce da questa lista, quindi il solo incrocio garantisce "in vendita ORA"
senza bisogno di un filtro dedicato. Costo: una query per pagina di carte possedute + una query
(potenzialmente paginata) per ogni giocatore diverso posseduto dal manager -- per manager con
collezioni enormi puo' essere lento, vedi MAX_PLAYERS_TO_CHECK piu' sotto come freno di sicurezza.
Se sportSeason/inSeasonEligible non risultassero leggibili su questi hit (mai provato in questa
combinazione esatta prima d'ora), l'errore GraphQL nel log dira' subito quale campo correggere,
stesso principio "prova e leggi l'errore" usato in tutto il resto del progetto.
"""
import math
import os
import re
import time

import track

MANAGER_INPUT = os.environ.get('MANAGER_SLUG_OR_URL', '').strip()

MAX_OWNED_CARD_PAGES = int(os.environ.get('MAX_OWNED_CARD_PAGES', '20'))
OWNED_CARD_PAGE_SIZE = int(os.environ.get('OWNED_CARD_PAGE_SIZE', '50'))
MAX_PLAYERS_TO_CHECK = int(os.environ.get('MAX_PLAYERS_TO_CHECK', '300'))

# Margine di sconto sul totale minimo di mercato per l'offerta suggerita -- punto di partenza
# provvisorio (stesso valore di ZENLOCK_DISCOUNT_NORMAL per coerenza con il resto del progetto),
# "poi lo tuniamo" per esplicita ammissione dell'utente: nessun caso reale ancora osservato per
# calibrarlo meglio.
BUNDLE_OFFER_MARGIN_FRACTION = float(os.environ.get('BUNDLE_OFFER_MARGIN_FRACTION', '0.15'))

# FIX 18/07 (richiesta esplicita dell'utente): Sorare permette di fare un'unica offerta
# cumulativa su al massimo 10 carte dello stesso manager. Organizziamo quindi le carte in
# vendita in blocchi da 10, ognuno con il proprio subtotale e la propria offerta suggerita,
# cosi' ogni blocco e' immediatamente azionabile su Sorare senza dover ricalcolare a mano.
# L'ordine e' quello di scoperta (arbitrario -- l'utente ha confermato che va bene cosi':
# "va bene anche in ordine sparso").
BUNDLE_BLOCK_SIZE = int(os.environ.get('BUNDLE_BLOCK_SIZE', '10'))

# Tetto di sicurezza sul numero di blocchi mostrati per intero nel messaggio Telegram (limite
# di lunghezza dei messaggi Telegram) -- oltre questo tetto, i blocchi restanti vengono solo
# riassunti con un conteggio (il dettaglio resta comunque nel log completo su GitHub).
MAX_BLOCKS_IN_TELEGRAM_MESSAGE = int(os.environ.get('MAX_BLOCKS_IN_TELEGRAM_MESSAGE', '10'))

# Pausa tra una query di mercato e la successiva (un giocatore diverso) -- stesso principio di
# spaziatura gia' usato altrove nel progetto (fetch_user_recent_cards/filter_recent_direct_buy_
# candidates in track.py), per non sparare tutte le query nello stesso istante.
PER_PLAYER_QUERY_DELAY_SECONDS = float(os.environ.get('PER_PLAYER_QUERY_DELAY_SECONDS', '0.2'))

LOG_PREFIX = "[manager bundle scan]"


def log(msg):
    track.log(f"{LOG_PREFIX} {msg}")


def extract_manager_slug(raw_input):
    """Accetta sia uno slug diretto (es. 'satonio') sia l'URL del profilo Sorare (es.
    'https://sorare.com/it/football/my-club/satonio', anche con suffissi tipo
    '/cards/limited?sale=true') e ritorna sempre e solo lo slug -- richiesta esplicita
    dell'utente ("gli inserisco l'url e lui ricava lo slug cosi' non ho rischio di errori")."""
    raw_input = (raw_input or '').strip()
    if not raw_input:
        return ''
    match = re.search(r'my-club/([^/?#]+)', raw_input)
    if match:
        return match.group(1)
    # Non sembra un URL con /my-club/ -- trattalo come slug diretto, ripulendo eventuali
    # slash iniziali/finali per sicurezza.
    return raw_input.strip('/')


# Stessa identica query (stessi nomi di campo) gia' collaudata in fetch_user_recent_cards di
# track.py -- qui aggiunti solo rarityTyped/sport/sportSeason/inSeasonEligible (campi gia'
# confermati altrove, es. LIVE_OFFERS_QUERY, sullo stesso tipo di oggetto carta) per poter
# distinguere in_season da classic, cosa che fetch_user_recent_cards non fa.
#
# FIX 18/07 (performance, caso reale flobob-fc): {filter_arg} e' un punto di innesto per un
# argomento opzionale di filtro "solo carte attualmente in vendita" -- vedi
# discover_on_sale_query() piu' sotto per il motivo e il meccanismo di scoperta.
OWNED_CARDS_QUERY_TEMPLATE = """
query ManagerOwnedLimitedCards($userSlug: String!, $page: Int!, $pageSize: Int!) {{
  user(slug: $userSlug) {{
    slug
    searchCards(
      rarity: limited
      sport: FOOTBALL
      query: ""
      page: $page
      pageSize: $pageSize
      sorts: [{{field: "user_owner.from", direction: DESC}}]
      {filter_arg}
    ) {{
      hits {{
        slug
        rarityTyped
        sport
        sportSeason {{ name }}
        inSeasonEligible
        anyPlayer {{ slug displayName }}
      }}
      nbHits
    }}
  }}
}}
"""

OWNED_CARDS_QUERY = OWNED_CARDS_QUERY_TEMPLATE.format(filter_arg="")

# FIX 18/07 (performance, caso reale flobob-fc): possedeva 1741 carte Limited (464 giocatori
# diversi in_season), ma SOLO 18 erano davvero in vendita -- il codice pre-fix scaricava tutte
# le carte possedute e poi controllava il mercato live per OGNI giocatore posseduto (anche i
# 446 che non c'entravano), costando ~115 secondi solo per quel ciclo. Il sito Sorare stesso
# applica un filtro lato server per "carte in vendita" nella galleria di un manager (vedi URL
# osservato dall'utente: .../cards/limited?sale=true&is=true) -- proviamo quindi a passare un
# argomento booleano analogo direttamente a searchCards (la STESSA query che gia' usiamo per le
# carte possedute), invece di scaricare tutto e filtrare dopo. Introspection disabilitata su
# tutto questo progetto: nessun modo di sapere il nome esatto dell'argomento in anticipo, quindi
# proviamo una lista di candidati e usiamo il primo che non da' errore GraphQL -- stesso identico
# principio "prova e leggi l'errore" gia' usato altrove (vedi diagnostic_live_auction_lookup.py).
# Se NESSUNO dei candidati funziona, fallback automatico al comportamento precedente (scarica
# tutto, filtra dopo) -- piu' lento ma sempre corretto, non deve mai bloccare la scansione.
ON_SALE_FILTER_CANDIDATES = [
    "onSale: true",
    "forSale: true",
    "sale: true",
    "isOnSale: true",
    "onlyOnSale: true",
    "listedForSale: true",
]


def discover_on_sale_query(manager_slug):
    """Prova ogni candidato in ON_SALE_FILTER_CANDIDATES con un probe minimo (pageSize=1) contro
    il manager reale che stiamo per analizzare. Ritorna (query_da_usare, filter_arg_trovato) --
    filter_arg_trovato e' None se nessun candidato ha funzionato (fallback alla query originale
    senza filtro). MAI presa per buona senza verifica: se un candidato non da' errori GraphQL lo
    consideriamo valido, ma logghiamo comunque il conteggio hits del probe per un controllo
    manuale a occhio nel log."""
    for filter_arg in ON_SALE_FILTER_CANDIDATES:
        query = OWNED_CARDS_QUERY_TEMPLATE.format(filter_arg=filter_arg)
        try:
            data = track.graphql_query(query, {
                "userSlug": manager_slug, "page": 1, "pageSize": 1})
        except Exception as e:
            log(f"[filtro carte in vendita] candidato '{filter_arg}' -- eccezione di rete: {e}")
            continue
        if data.get('errors'):
            log(f"[filtro carte in vendita] candidato '{filter_arg}' -- errore GraphQL "
                f"(candidato scartato): {data['errors']}")
            continue
        probe_hits = (((data.get('data') or {}).get('user') or {}).get('searchCards') or {})
        log(f"[filtro carte in vendita] candidato '{filter_arg}' FUNZIONA (nbHits probe="
            f"{probe_hits.get('nbHits')}) -- lo uso per tutta la scansione: niente piu' "
            f"controllo mercato sulle carte NON in vendita.")
        return query, filter_arg
    log("[filtro carte in vendita] nessun candidato ha funzionato -- fallback al comportamento "
        "precedente (scarico tutte le carte Limited possedute e controllo il mercato per ogni "
        "giocatore diverso, piu' lento). Vedi gli errori sopra per capire il nome giusto da "
        "aggiungere ai candidati in futuro.")
    return OWNED_CARDS_QUERY, None


def fetch_manager_owned_in_season_limited_cards(manager_slug):
    """Scarica le carte Limited possedute dal manager (paginato fino a MAX_OWNED_CARD_PAGES),
    filtra client-side alle sole IN SEASON (season_type_for_card, stessa classificazione di
    track.py/zenlock). Prima di scaricare, prova (discover_on_sale_query) a restringere GIA' lato
    server alle sole carte attualmente in vendita -- se funziona, evitiamo di scaricare l'intera
    collezione e controllare il mercato per giocatori che non sono nemmeno in vendita (vedi FIX
    18/07 sopra). Ritorna (lista_carte_in_season, nb_hits_totale, manager_trovato,
    filtrato_lato_server). manager_trovato=False se user() e' risultato nullo (slug inesistente);
    None se non siamo nemmeno riusciti a interrogare (errore di rete/GraphQL alla prima pagina)."""
    query, filter_arg = discover_on_sale_query(manager_slug)
    filtered_to_on_sale = filter_arg is not None

    all_hits = []
    nb_hits_total = None
    manager_found = None
    for page in range(1, MAX_OWNED_CARD_PAGES + 1):
        try:
            data = track.graphql_query(query, {
                "userSlug": manager_slug, "page": page, "pageSize": OWNED_CARD_PAGE_SIZE})
        except Exception as e:
            log(f"eccezione pagina {page} carte possedute per '{manager_slug}': {e}")
            break
        if data.get('errors'):
            log(f"errore GraphQL pagina {page} carte possedute per '{manager_slug}': {data['errors']}")
            break
        user_data = (data.get('data') or {}).get('user')
        if user_data is None:
            manager_found = False
            break
        manager_found = True
        search = user_data.get('searchCards') or {}
        hits = search.get('hits') or []
        if page == 1:
            nb_hits_total = search.get('nbHits')
            scope = ("GIA' filtrate lato server alle sole in vendita" if filtered_to_on_sale
                     else "possedute in totale (tutte le stagioni) -- nessun filtro on-sale "
                          "disponibile, controllero' il mercato per ogni giocatore posseduto")
            log(f"'{manager_slug}': {nb_hits_total} carte Limited {scope}, scansiono fino a un "
                f"massimo di {MAX_OWNED_CARD_PAGES * OWNED_CARD_PAGE_SIZE}...")
        if not hits:
            break
        all_hits.extend(hits)
        if len(hits) < OWNED_CARD_PAGE_SIZE:
            break  # ultima pagina: meno risultati della page size richiesta
        time.sleep(0.2)

    if manager_found and nb_hits_total is not None and nb_hits_total > len(all_hits):
        log(f"ATTENZIONE: '{manager_slug}' ha {nb_hits_total} carte Limited (in questo scope) ma "
            f"ne ho scansionate solo {len(all_hits)} (limite MAX_OWNED_CARD_PAGES="
            f"{MAX_OWNED_CARD_PAGES}) -- alcune carte piu' vecchie potrebbero non essere state "
            f"controllate, il risultato finale potrebbe essere incompleto.")

    in_season_cards = []
    skipped_no_player = 0
    for hit in all_hits:
        player = hit.get('anyPlayer') or {}
        player_slug = player.get('slug')
        if not player_slug:
            skipped_no_player += 1
            continue
        season_name = (hit.get('sportSeason') or {}).get('name', 'unknown')
        season_type = track.season_type_for_card(hit, season_name)
        if season_type != 'in_season':
            continue
        in_season_cards.append({
            'card_slug': hit.get('slug'),
            'player_slug': player_slug,
            'player_name': player.get('displayName', player_slug),
        })
    if skipped_no_player:
        log(f"[diagnostica] {skipped_no_player} carte possedute scartate: nessun anyPlayer.slug "
            f"leggibile (dato grezzo anomalo, da controllare se capita spesso).")
    return in_season_cards, nb_hits_total, manager_found, filtered_to_on_sale


def find_current_listing_and_market_min(card_slug, player_slug, eth_rate):
    """Interroga il mercato live COMPLETO per player_slug (get_bucket_prices, stesso dato gia'
    usato da track.py/zenlock) e cerca card_slug tra gli annunci in_season -- se lo trova, e'
    la conferma che quella carta e' DAVVERO in vendita adesso, al prezzo li' indicato. Il minimo
    dell'intero bucket (che PUO' coincidere con questa stessa carta, se il manager e' gia' il
    piu' economico -- in quel caso zero arbitraggio su questa carta specifica, ma resta comunque
    utile mostrarla nel riepilogo) e' il 'prezzo minimo di mercato'. Ritorna None se la carta
    posseduta non risulta (piu') in vendita ora (es. ritirata o venduta nel frattempo, oppure
    query fallita)."""
    buckets = track.get_bucket_prices(player_slug, eth_rate, use_cache=False)
    in_season_prices, _incomplete = buckets.get('in_season', ([], False))
    if not in_season_prices:
        return None
    market_min_price = in_season_prices[0][0]
    listing_price = None
    for price, slug in in_season_prices:
        if slug == card_slug:
            listing_price = price
            break
    if listing_price is None:
        return None  # posseduta ma non (piu') in vendita adesso
    return listing_price, market_min_price


def format_eur(value):
    return f"{value:.2f}EUR"


def run_bundle_scan():
    manager_slug = extract_manager_slug(MANAGER_INPUT)
    if not manager_slug:
        log("nessuno slug/URL manager fornito (env var MANAGER_SLUG_OR_URL vuota) -- interrompo, "
            "nessuna notifica Telegram.")
        return
    log(f"input ricevuto: {MANAGER_INPUT!r} -> slug estratto: '{manager_slug}'")

    eth_rate = track.get_eth_rate()
    track.reset_currency_branch_stats()

    owned_in_season_cards, nb_hits_total, manager_found, filtered_to_on_sale = \
        fetch_manager_owned_in_season_limited_cards(manager_slug)

    if manager_found is False:
        log(f"manager '{manager_slug}' NON TROVATO su Sorare (query user() ha restituito null) "
            f"-- controlla che lo slug/URL sia corretto. Nessuna notifica Telegram inviata.")
        return
    if manager_found is None:
        log(f"impossibile determinare se '{manager_slug}' esiste (errore di rete/GraphQL prima "
            f"ancora di ricevere una risposta valida, vedi dettaglio errore sopra nel log). "
            f"Nessuna notifica Telegram inviata.")
        return

    scope_desc = ("gia' filtrate lato server alle sole in vendita" if filtered_to_on_sale
                  else f"su {nb_hits_total} carte Limited totali, tutte le stagioni")
    log(f"'{manager_slug}': {len(owned_in_season_cards)} carte Limited IN SEASON possedute "
        f"({scope_desc}).")
    if not owned_in_season_cards:
        log(f"'{manager_slug}' non possiede nessuna carta Limited in_season -- nessuna carta da "
            f"controllare, nessuna notifica Telegram inviata.")
        return

    unique_players = []
    seen_players = set()
    for card in owned_in_season_cards:
        p = card['player_slug']
        if p not in seen_players:
            seen_players.add(p)
            unique_players.append(p)

    if len(unique_players) > MAX_PLAYERS_TO_CHECK:
        log(f"ATTENZIONE: '{manager_slug}' ha {len(unique_players)} giocatori diversi tra le "
            f"carte in_season possedute, oltre il tetto MAX_PLAYERS_TO_CHECK="
            f"{MAX_PLAYERS_TO_CHECK} -- controllo solo i primi {MAX_PLAYERS_TO_CHECK} (per "
            f"acquisizione piu' recente), il risultato potrebbe essere incompleto.")
        allowed_players = set(unique_players[:MAX_PLAYERS_TO_CHECK])
        owned_in_season_cards = [c for c in owned_in_season_cards
                                  if c['player_slug'] in allowed_players]
        unique_players = unique_players[:MAX_PLAYERS_TO_CHECK]

    log(f"controllo il mercato live per {len(unique_players)} giocatori diversi "
        f"({len(owned_in_season_cards)} carte possedute da verificare)...")

    on_sale = []
    not_on_sale_count = 0
    error_count = 0
    for card in owned_in_season_cards:
        try:
            result = find_current_listing_and_market_min(
                card['card_slug'], card['player_slug'], eth_rate)
        except Exception as e:
            log(f"eccezione controllando {card['player_name']} ({card['card_slug']}): {e}")
            error_count += 1
            continue
        if result is None:
            not_on_sale_count += 1
            continue
        listing_price, market_min_price = result
        on_sale.append({
            'player_name': card['player_name'],
            'card_slug': card['card_slug'],
            'listing_price': listing_price,
            'market_min_price': market_min_price,
        })
        time.sleep(PER_PLAYER_QUERY_DELAY_SECONDS)

    log(f"[diagnostica] {len(owned_in_season_cards)} carte in_season possedute controllate, "
        f"{len(on_sale)} risultano DAVVERO in vendita ora, {not_on_sale_count} possedute ma NON "
        f"in vendita (o ritirate/vendute nel frattempo), {error_count} errori di query.")
    log(f"[diagnostica valute] branch usati in eur_price_from_amounts: "
        f"{track.get_currency_branch_stats()}")

    if not on_sale:
        log(f"'{manager_slug}' possiede carte in_season ma NESSUNA risulta attualmente in "
            f"vendita -- nessuna notifica Telegram inviata.")
        return

    total_asking = sum(c['listing_price'] for c in on_sale)
    total_market_min = sum(c['market_min_price'] for c in on_sale)
    n_blocks = math.ceil(len(on_sale) / BUNDLE_BLOCK_SIZE)

    log(f"RISULTATO -- '{manager_slug}': {len(on_sale)} carte in vendita organizzate in "
        f"{n_blocks} blocchi da {BUNDLE_BLOCK_SIZE} (limite Sorare per offerta cumulativa), "
        f"richiesta totale {format_eur(total_asking)}, minimo di mercato totale "
        f"{format_eur(total_market_min)} (dettaglio/offerta per blocco nel messaggio Telegram).")

    message = build_telegram_message(manager_slug, on_sale)
    track.send_telegram_msg(message)
    log("notifica Telegram inviata (canale aste, riuso temporaneo).")


def build_telegram_message(manager_slug, on_sale):
    """Organizza le carte in vendita in BLOCCHI DA BUNDLE_BLOCK_SIZE (default 10) -- limite
    pratico di Sorare per fare un'unica offerta cumulativa su piu' carte dello stesso manager
    (richiesta esplicita dell'utente). Ogni blocco riporta il proprio subtotale (richiesto,
    minimo di mercato) e la propria offerta suggerita, cosi' e' immediatamente azionabile su
    Sorare senza dover ricalcolare nulla a mano. L'ordine e' quello di scoperta (arbitrario --
    l'utente ha confermato "va bene anche in ordine sparso"). Niente margine di profitto per
    blocco: "poi il margine di profitto eventualmente me lo trovo io" (l'utente lo calcola da
    solo).

    Evidenziazione: Telegram (parse_mode HTML) non supporta colori del testo, solo grassetto/
    corsivo/link/ecc -- l'unico modo pratico di "colorare" una riga e' un'emoji. Usiamo 🔴
    quando il prezzo chiesto e' SOPRA il minimo di mercato (esiste un'alternativa piu' economica
    altrove: questa carta pesa nel pacchetto ma non e' lei stessa l'occasione) e 🟢 quando la
    carta e' GIA' al prezzo minimo di mercato (nessuna alternativa piu' economica trovata)."""
    blocks = [on_sale[i:i + BUNDLE_BLOCK_SIZE] for i in range(0, len(on_sale), BUNDLE_BLOCK_SIZE)]
    blocks_shown = blocks[:MAX_BLOCKS_IN_TELEGRAM_MESSAGE]

    lines = [f"🎯 <b>{manager_slug}</b> -- carte Limited in_season in vendita ({len(on_sale)}, "
             f"{len(blocks)} blocchi da {BUNDLE_BLOCK_SIZE})\n"]

    for block_idx, block in enumerate(blocks_shown, start=1):
        start_n = (block_idx - 1) * BUNDLE_BLOCK_SIZE + 1
        end_n = start_n + len(block) - 1
        lines.append(f"<b>Blocco {block_idx} (carte {start_n}-{end_n})</b>")
        for c in block:
            marker = "🟢" if c['listing_price'] <= c['market_min_price'] else "🔴"
            lines.append(f"{marker} {c['player_name']}: in vendita a "
                          f"{format_eur(c['listing_price'])}, minimo mercato "
                          f"{format_eur(c['market_min_price'])}")
        block_asking = sum(c['listing_price'] for c in block)
        block_market_min = sum(c['market_min_price'] for c in block)
        block_offer = block_market_min * (1 - BUNDLE_OFFER_MARGIN_FRACTION)
        lines.append(f"Subtotale: richiesto {format_eur(block_asking)}, minimo mercato "
                      f"{format_eur(block_market_min)}")
        lines.append(f"👉 <b>Offri fino a {format_eur(block_offer)}</b> per questo blocco "
                      f"(margine {BUNDLE_OFFER_MARGIN_FRACTION:.0%} -- valore provvisorio, "
                      f"da tarare)")
        lines.append("")

    if len(blocks) > MAX_BLOCKS_IN_TELEGRAM_MESSAGE:
        remaining_blocks = blocks[MAX_BLOCKS_IN_TELEGRAM_MESSAGE:]
        remaining_cards = sum(len(b) for b in remaining_blocks)
        lines.append(f"... altri {len(remaining_blocks)} blocchi ({remaining_cards} carte) "
                      f"omessi dal messaggio, vedi log completo su GitHub")
        lines.append("")

    total_asking = sum(c['listing_price'] for c in on_sale)
    total_market_min = sum(c['market_min_price'] for c in on_sale)
    lines.append(f"Totale complessivo (tutti i blocchi): {len(on_sale)} carte, richiesto "
                 f"{format_eur(total_asking)}, minimo mercato {format_eur(total_market_min)} "
                 f"(informativo -- non offribile in un colpo solo oltre le {BUNDLE_BLOCK_SIZE} "
                 f"carte, vedi offerte per blocco sopra)")
    lines.append("🟢 = gia' al minimo di mercato   🔴 = in vendita sopra il minimo di mercato "
                 "(esiste altrove piu' a buon mercato)")
    return "\n".join(lines)


if __name__ == '__main__':
    run_bundle_scan()
