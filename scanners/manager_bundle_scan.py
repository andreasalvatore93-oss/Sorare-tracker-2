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
import datetime
import json
import math
import os
import re
import threading
import time

import track

MANAGER_INPUT = os.environ.get('MANAGER_SLUG_OR_URL', '').strip()

# FIX 18/07 (v3, richiesta esplicita dell'utente, "trova dei manager da scansionare"): modalita'
# auto-discovery OPZIONALE, di default SPENTA e attiva SOLO se non e' stato fornito nessun
# manager (l'input manuale resta intoccato e ha sempre la precedenza). Se attiva: ascolta il
# mercato (stessa subscription WS gia' collaudata di track.py) per un po', raccoglie le carte
# Limited in_season appena messe in vendita, risale al manager venditore di ciascuna, e al primo
# manager trovato con ALMENO AUTO_FIND_MIN_CARDS_FOR_SALE carte in_season in vendita fa partire
# lo scan classico su di lui.
AUTO_FIND_MANAGER = os.environ.get('AUTO_FIND_MANAGER', '').strip().lower() in ('1', 'true', 'si', 'yes')
# FIX 18/07 (v6, richiesta esplicita dell'utente): ascolto default 60->120s (piu' candidati per
# giro) e soglia carte in vendita 10->5 (anche manager con 5+ carte in season valgono uno scan).
AUTO_FIND_LISTEN_SECONDS = float(os.environ.get('AUTO_FIND_LISTEN_SECONDS', '120'))
AUTO_FIND_MIN_CARDS_FOR_SALE = int(os.environ.get('AUTO_FIND_MIN_CARDS_FOR_SALE', '5'))
# FIX 10/08 (richiesta esplicita dell'utente, caso reale jafar1006: 27 carte "gia' al minimo" ma
# ognuna solo pochi centesimi sotto -- non un'occasione, ma il segnale di un manager/bot che non
# accetta offerte al ribasso, esattamente il tipo di target che questo scanner deve SCARTARE).
# Soglia minima sulla SOMMA degli scarti (second_min_price - market_min_price) delle carte nel
# pacchetto best-deal: sotto questa soglia il candidato viene scartato in auto-discovery e la
# ricerca CONTINUA sul prossimo candidato (vedi auto_find_manager) -- non si applica all'input
# manuale (l'utente ha scelto quel manager apposta, nessuna "ricerca" da continuare).
AUTO_FIND_MIN_BEST_DEAL_GAP_EUR = float(os.environ.get('AUTO_FIND_MIN_BEST_DEAL_GAP_EUR', '2.0'))
# Tetti di sicurezza: quanti manager diversi controllare al massimo (ognuno costa la scansione
# paginata delle sue carte possedute) e quante carte al massimo sottoporre al lookup del
# proprietario (1 query ciascuna).
AUTO_FIND_MAX_MANAGERS_TO_CHECK = int(os.environ.get('AUTO_FIND_MAX_MANAGERS_TO_CHECK', '5'))
AUTO_FIND_MAX_OWNER_LOOKUPS = int(os.environ.get('AUTO_FIND_MAX_OWNER_LOOKUPS', '30'))

# FIX 18/07 (v4, richiesta esplicita dell'utente): blacklist di manager bot noti che non accettano
# offerte negoziate -- scansionarli e' inutile perche' rispondono solo a loro stessa logica bot,
# non a margini. Ignorati durante l'auto-discovery (l'input manuale resta intoccato per il testing).
# BLACKLIST_MANAGERS env var (da workflow) aggiunge manager temporaneamente per quella run.
AUTO_FIND_BLACKLIST_MANAGERS = {
    'clem777', 'satonio', 'zenlock', 'cheaper-than-him', 'eli-aquim',
    'lamella-4aa53b98-9221-410e-8092-05aaabd1ba30', 'sir-hiss-the-swap-bot',
    'paweltrader', 'basilbot', 'ruv-liquidation-of-gallery-at-fixed-prices',
    'jrodwalts-trade-115-active-buyer-seller', 'meowmeow7',
    'bellona-f0b1a9d7-3700-4d59-9044-ec54b7b348aa',
}
# Aggiungi blacklist permanente da file (salvate dalle run precedenti)
_blacklist_file = '.github/auto_find_blacklist_additions.txt'
if os.path.exists(_blacklist_file):
    try:
        with open(_blacklist_file) as f:
            _file_slugs = [line.strip().lower() for line in f if line.strip() and not line.startswith('#')]
            AUTO_FIND_BLACKLIST_MANAGERS.update(_file_slugs)
    except Exception as e:
        pass  # se il file non è leggibile, ignora silenziosamente

# Aggiungi blacklist temporanea dal workflow (lista separata da virgola)
_temp_blacklist = os.environ.get('BLACKLIST_MANAGERS', '').strip()
if _temp_blacklist:
    _temp_slugs = [s.strip().lower() for s in _temp_blacklist.split(',') if s.strip()]
    AUTO_FIND_BLACKLIST_MANAGERS.update(_temp_slugs)

# FIX 18/07 (v5, richiesta esplicita dell'utente): raffreddamento (cooldown) SOLO per
# l'auto-discovery -- se una carta di un manager gia' scansionato di recente resta "sotto tiro"
# nello stream WS, l'auto-discovery lo riselezionerebbe ad ogni run, generando notifiche
# ripetute sullo stesso manager/stesse carte. Una volta scansionato (auto-discovery), il manager
# resta escluso dalla SOLA auto-discovery per AUTO_FIND_COOLDOWN_DAYS giorni. L'input MANUALE
# (slug/URL inserito a mano) NON viene mai ne' controllato ne' scritto qui -- resta identico a
# prima, nessun raffreddamento, richiesta esplicita: "se cerco un manager specifico resta tutto
# uguale".
AUTO_FIND_COOLDOWN_DAYS = float(os.environ.get('AUTO_FIND_COOLDOWN_DAYS', '7'))
AUTO_FIND_COOLDOWN_FILE = '.manager_bundle_scan_cooldown.json'


def _load_auto_find_cooldown():
    """Carica {slug: timestamp_iso_ultima_scansione_auto-discovery} dal file persistente."""
    if not os.path.exists(AUTO_FIND_COOLDOWN_FILE):
        return {}
    try:
        with open(AUTO_FIND_COOLDOWN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_auto_find_cooldown(cooldown):
    with open(AUTO_FIND_COOLDOWN_FILE, 'w') as f:
        json.dump(cooldown, f, indent=2)


# FIX 18/07 (v6, richiesta esplicita dell'utente, "anti raffreddamento"): input dal workflow per
# TOGLIERE manager dalla coda di raffreddamento (7gg) senza aspettare la scadenza -- lista di
# slug separati da virgola, rimossi dal file di cooldown all'avvio.
_remove_cooldown = os.environ.get('REMOVE_COOLDOWN_MANAGERS', '').strip()
if _remove_cooldown:
    _cd = _load_auto_find_cooldown()
    _removed = []
    for _slug in (s.strip().lower() for s in _remove_cooldown.split(',') if s.strip()):
        if _slug in _cd:
            del _cd[_slug]
            _removed.append(_slug)
    if _removed:
        _save_auto_find_cooldown(_cd)
        print(f"[bundle-scan] anti-raffreddamento: rimossi dal cooldown {_removed}")
    else:
        print(f"[bundle-scan] anti-raffreddamento: nessuno degli slug richiesti era in cooldown")


def _is_in_auto_find_cooldown(slug, cooldown):
    """True se 'slug' e' stato scansionato via auto-discovery meno di AUTO_FIND_COOLDOWN_DAYS
    giorni fa. Timestamp illeggibile/malformato = tratta come NON in cooldown (mai bloccare per
    un dato corrotto)."""
    ts = cooldown.get(slug)
    if not ts:
        return False
    try:
        last_scanned = datetime.datetime.fromisoformat(ts)
    except ValueError:
        return False
    age_days = (datetime.datetime.now() - last_scanned).total_seconds() / 86400
    return age_days < AUTO_FIND_COOLDOWN_DAYS

MAX_OWNED_CARD_PAGES = int(os.environ.get('MAX_OWNED_CARD_PAGES', '20'))
OWNED_CARD_PAGE_SIZE = int(os.environ.get('OWNED_CARD_PAGE_SIZE', '50'))
MAX_PLAYERS_TO_CHECK = int(os.environ.get('MAX_PLAYERS_TO_CHECK', '300'))

# Margine di sconto sul totale minimo di mercato per l'offerta suggerita -- punto di partenza
# provvisorio (stesso valore di ZENLOCK_DISCOUNT_NORMAL per coerenza con il resto del progetto),
# "poi lo tuniamo" per esplicita ammissione dell'utente: nessun caso reale ancora osservato per
# calibrarlo meglio.
# FIX 18/07 (v2, richiesta esplicita dell'utente, "alziamo margine di default a 25 percento"):
# alzato da 0.15 a 0.25 dopo i primi run reali.
BUNDLE_OFFER_MARGIN_FRACTION = float(os.environ.get('BUNDLE_OFFER_MARGIN_FRACTION', '0.25'))

# FIX 18/07 (v2, richiesta esplicita dell'utente, "ignoriamo le carte che hanno un prezzo minimo
# di vendita inferiore ad un euro"): carte il cui prezzo minimo di mercato e' sotto questa soglia
# vengono scartate PRIMA di entrare in on_sale -- niente blocchi, niente bonus, niente best deal
# per queste, sono considerate troppo marginali per valere l'analisi.
BUNDLE_MIN_MARKET_PRICE_EUR = float(os.environ.get('BUNDLE_MIN_MARKET_PRICE_EUR', '1.0'))

# FIX 18/07 (richiesta esplicita dell'utente): Sorare permette di fare un'unica offerta
# cumulativa su al massimo 10 carte dello stesso manager. Organizziamo quindi le carte in
# vendita in blocchi da 10, ognuno con il proprio subtotale e la propria offerta suggerita,
# cosi' ogni blocco e' immediatamente azionabile su Sorare senza dover ricalcolare a mano.
# L'ordine e' quello di scoperta (arbitrario -- l'utente ha confermato che va bene cosi':
# "va bene anche in ordine sparso").
BUNDLE_BLOCK_SIZE = int(os.environ.get('BUNDLE_BLOCK_SIZE', '10'))

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
    dell'utente ("gli inserisco l'url e lui ricava lo slug cosi' non ho rischio di errori").

    FIX 18/07 (QoL, richiesta esplicita dell'utente dopo un errore reale scrivendo 'satonio'
    a mano nel campo del workflow invece dell'URL): due normalizzazioni aggiunte, entrambe
    pensate per tollerare errori di battitura/copia-incolla ("questa non e' una cosa di vitale
    importanza, e' solo qol"):
    1) rimozione di TUTTI gli spazi (non solo iniziali/finali, anche eventuali spazi interni
       accidentali e non-breaking space   tipici di un copia-incolla dal browser) -- uno
       slug/URL valido non contiene mai spazi, quindi toglierli e' sempre sicuro;
    2) minuscolo forzato -- tutti gli slug/username Sorare osservati finora in questo progetto
       sono sempre in minuscolo (flobob-fc, crowss, mikileefoo, satonio...), quindi normalizzare
       il case e' un'operazione a basso rischio che rende l'input case-insensitive."""
    raw_input = (raw_input or '').replace(' ', ' ')
    raw_input = re.sub(r'\s+', '', raw_input).lower()
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
# FIX 18/07 (performance, caso reale flobob-fc): {sale_field} e' un punto di innesto per un
# campo opzionale che dice se QUESTA carta specifica ha un'offerta di vendita attiva -- vedi
# probe_live_single_sale_offer_field() piu' sotto per il motivo e il meccanismo di scoperta.
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
    ) {{
      hits {{
        slug
        rarityTyped
        sport
        sportSeason {{ name }}
        inSeasonEligible
        anyPlayer {{ slug displayName }}
        {sale_field}
      }}
      nbHits
    }}
  }}
}}
"""

OWNED_CARDS_QUERY = OWNED_CARDS_QUERY_TEMPLATE.format(sale_field="")

# FIX 18/07 (performance, caso reale flobob-fc): possedeva 1741 carte Limited (464 giocatori
# diversi in_season), ma SOLO 18 erano davvero in vendita -- il codice pre-fix scaricava tutte
# le carte possedute e poi controllava il mercato live per OGNI giocatore posseduto (anche i
# 446 che non c'entravano), costando ~115 secondi solo per quel ciclo.
#
# TENTATIVO 1 (FALLITO, confermato dal log reale 18/07 11:02 UTC): un argomento booleano diretto
# su searchCards (onSale/forSale/sale/isOnSale/onlyOnSale/listedForSale) -- TUTTI e 6 hanno dato
# lo stesso identico errore netto "Field 'searchCards' doesn't accept argument '...'": searchCards
# NON ha nessun argomento del genere (almeno non con questi nomi). Rimosso, inutile riprovarlo a
# ogni run.
#
# TENTATIVO 2 (questo): un CAMPO (non un argomento) sulla carta stessa, "liveSingleSaleOffer" --
# stesso campo gia' individuato (ma mai testato in QUESTO contesto/tipo esatto) in
# diagnostic_live_auction_lookup.py per un altro scopo (riverifica pre-notifica di
# auctions_ws_listener.py). Se leggibile anche dentro searchCards.hits, ci dice DIRETTAMENTE
# (nessuna query aggiuntiva) quali carte possedute sono in vendita ORA, permettendoci di saltare
# il controllo mercato per i giocatori che non c'entrano. Introspection disabilitata: un solo
# probe minimo (pageSize=1), se da' errore fallback automatico alla query senza questo campo
# (comportamento precedente, piu' lento ma sempre corretto, mai un crash).
SALE_FIELD_PROBE = "liveSingleSaleOffer { __typename }"
OWNED_CARDS_QUERY_WITH_SALE_FIELD = OWNED_CARDS_QUERY_TEMPLATE.format(sale_field=SALE_FIELD_PROBE)


def probe_live_single_sale_offer_field(manager_slug):
    """Prova il campo liveSingleSaleOffer dentro searchCards.hits con un probe minimo
    (pageSize=1) contro il manager reale che stiamo per analizzare. Ritorna True se leggibile
    (lo useremo per tutta la scansione), False altrimenti (fallback automatico). MAI presa per
    buona senza verifica: logghiamo l'esito esatto."""
    try:
        data = track.graphql_query(OWNED_CARDS_QUERY_WITH_SALE_FIELD, {
            "userSlug": manager_slug, "page": 1, "pageSize": 1})
    except Exception as e:
        log(f"[filtro carte in vendita] campo liveSingleSaleOffer -- eccezione di rete: {e} "
            f"-- fallback al comportamento precedente.")
        return False
    if data.get('errors'):
        log(f"[filtro carte in vendita] campo liveSingleSaleOffer NON leggibile in questo "
            f"contesto (searchCards.hits) -- fallback al comportamento precedente (controllo il "
            f"mercato per ogni giocatore posseduto, piu' lento). Errore: {data['errors']}")
        return False
    log("[filtro carte in vendita] campo liveSingleSaleOffer FUNZIONA dentro searchCards.hits -- "
        "lo uso per sapere SUBITO quali carte possedute sono davvero in vendita, senza "
        "controllare il mercato per i giocatori che non c'entrano.")
    return True


def fetch_manager_owned_in_season_limited_cards(manager_slug):
    """Scarica le carte Limited possedute dal manager (paginato fino a MAX_OWNED_CARD_PAGES),
    filtra client-side alle sole IN SEASON (season_type_for_card, stessa classificazione di
    track.py/zenlock). Prima di scaricare, prova (probe_live_single_sale_offer_field) ad
    aggiungere un campo che dice DIRETTAMENTE se ogni carta e' in vendita ora -- se funziona,
    filtriamo subito alle sole carte confermate in vendita, evitando di controllare il mercato
    per i giocatori che non c'entrano (vedi FIX 18/07 sopra). Ritorna (lista_carte_in_season,
    nb_hits_totale, manager_trovato, filtrato_lato_client). manager_trovato=False se user() e'
    risultato nullo (slug inesistente); None se non siamo nemmeno riusciti a interrogare (errore
    di rete/GraphQL alla prima pagina)."""
    has_sale_field = probe_live_single_sale_offer_field(manager_slug)
    query = OWNED_CARDS_QUERY_WITH_SALE_FIELD if has_sale_field else OWNED_CARDS_QUERY

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
            log(f"'{manager_slug}': {nb_hits_total} carte Limited possedute in totale (tutte le "
                f"stagioni), scansiono fino a un massimo di "
                f"{MAX_OWNED_CARD_PAGES * OWNED_CARD_PAGE_SIZE}...")
        if not hits:
            break
        all_hits.extend(hits)
        if len(hits) < OWNED_CARD_PAGE_SIZE:
            break  # ultima pagina: meno risultati della page size richiesta
        time.sleep(0.2)

    if manager_found and nb_hits_total is not None and nb_hits_total > len(all_hits):
        log(f"ATTENZIONE: '{manager_slug}' possiede {nb_hits_total} carte Limited ma ne ho "
            f"scansionate solo {len(all_hits)} (limite MAX_OWNED_CARD_PAGES="
            f"{MAX_OWNED_CARD_PAGES}) -- alcune carte piu' vecchie potrebbero non essere state "
            f"controllate, il risultato finale potrebbe essere incompleto.")

    if has_sale_field:
        before = len(all_hits)
        all_hits = [h for h in all_hits if h.get('liveSingleSaleOffer') is not None]
        log(f"[filtro carte in vendita] {before} carte possedute scansionate, {len(all_hits)} "
            f"confermate in vendita ORA (liveSingleSaleOffer non nullo) -- salto il controllo "
            f"mercato per le restanti {before - len(all_hits)}.")

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
    return in_season_cards, nb_hits_total, manager_found, has_sale_field


def find_current_listing_and_market_min(card_slug, player_slug, eth_rate):
    """Interroga il mercato live COMPLETO per player_slug (get_bucket_prices, stesso dato gia'
    usato da track.py/zenlock) e cerca card_slug tra gli annunci in_season -- se lo trova, e'
    la conferma che quella carta e' DAVVERO in vendita adesso, al prezzo li' indicato. Il minimo
    dell'intero bucket (che PUO' coincidere con questa stessa carta, se il manager e' gia' il
    piu' economico -- in quel caso zero arbitraggio su questa carta specifica, ma resta comunque
    utile mostrarla nel riepilogo) e' il 'prezzo minimo di mercato'. Ritorna None se la carta
    posseduta non risulta (piu') in vendita ora (es. ritirata o venduta nel frattempo, oppure
    query fallita).

    FIX 18/07 (v2, richiesta esplicita dell'utente, funzione "best deal"): in aggiunta ai due
    valori di sempre, ritorna ora anche second_min_price -- il SECONDO prezzo piu' economico
    dell'intero bucket in_season (in_season_prices e' gia' ordinato crescente, vedi
    get_bucket_prices), oppure None se in quel bucket c'e' un solo annuncio in vendita (nessun
    comparabile, "scarto" non calcolabile). Serve SOLO per il caso in cui QUESTA carta e' essa
    stessa il minimo del bucket: in quel caso second_min_price e' esattamente "la carta
    immediatamente piu' costosa in vendita sul mercato" richiesta dall'utente per calcolare lo
    scarto del blocco best deal (vedi run_bundle_scan)."""
    buckets = track.get_bucket_prices(player_slug, eth_rate, use_cache=False)
    in_season_prices, _incomplete = buckets.get('in_season', ([], False))
    if not in_season_prices:
        return None
    market_min_price = in_season_prices[0][0]
    second_min_price = in_season_prices[1][0] if len(in_season_prices) > 1 else None
    listing_price = None
    for price, slug in in_season_prices:
        if slug == card_slug:
            listing_price = price
            break
    if listing_price is None:
        return None  # posseduta ma non (piu') in vendita adesso
    return listing_price, market_min_price, second_min_price


def format_eur(value):
    return f"{value:.2f}EUR"


def scan_manager_market(manager_slug, eth_rate):
    """Scarica le carte Limited in_season possedute da manager_slug e controlla il mercato live
    per ognuna -- stessa identica logica usata sia dall'input manuale sia dall'auto-discovery
    (FIX 10/08: prima viveva solo dentro run_bundle_scan; ora auto_find_manager la riusa PRIMA di
    impegnarsi su un candidato, per calcolare lo scarto del pacchetto best-deal e poterlo
    scartare in favore del prossimo candidato se il margine e' troppo piccolo). Ritorna
    (on_sale, manager_found): manager_found=False se lo slug non esiste, None se errore di
    rete/GraphQL prima ancora di una risposta valida -- in entrambi i casi on_sale e' []."""
    owned_in_season_cards, nb_hits_total, manager_found, has_sale_field = \
        fetch_manager_owned_in_season_limited_cards(manager_slug)

    if manager_found is False:
        log(f"manager '{manager_slug}' NON TROVATO su Sorare (query user() ha restituito null) "
            f"-- controlla che lo slug/URL sia corretto.")
        return [], manager_found
    if manager_found is None:
        log(f"impossibile determinare se '{manager_slug}' esiste (errore di rete/GraphQL prima "
            f"ancora di ricevere una risposta valida, vedi dettaglio errore sopra nel log).")
        return [], manager_found

    scope_desc = ("GIA' filtrate alle sole confermate in vendita (liveSingleSaleOffer)"
                  if has_sale_field else f"su {nb_hits_total} carte Limited totali, tutte le stagioni")
    log(f"'{manager_slug}': {len(owned_in_season_cards)} carte Limited IN SEASON possedute "
        f"({scope_desc}).")
    if not owned_in_season_cards:
        log(f"'{manager_slug}' non possiede nessuna carta Limited in_season -- nessuna carta da controllare.")
        return [], manager_found

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
    below_min_price_count = 0
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
        listing_price, market_min_price, second_min_price = result
        # FIX 18/07 (v2, richiesta esplicita dell'utente, "ignoriamo le carte che hanno un
        # prezzo minimo di vendita inferiore ad un euro"): scartate PRIMA di entrare in on_sale,
        # quindi assenti da blocchi/bonus/best deal.
        if market_min_price < BUNDLE_MIN_MARKET_PRICE_EUR:
            below_min_price_count += 1
            continue
        on_sale.append({
            'player_name': card['player_name'],
            'player_slug': card['player_slug'],
            'card_slug': card['card_slug'],
            'listing_price': listing_price,
            'market_min_price': market_min_price,
            'second_min_price': second_min_price,
        })
        time.sleep(PER_PLAYER_QUERY_DELAY_SECONDS)

    log(f"[diagnostica] {len(owned_in_season_cards)} carte in_season possedute controllate, "
        f"{len(on_sale)} risultano DAVVERO in vendita ora, {not_on_sale_count} possedute ma NON "
        f"in vendita (o ritirate/vendute nel frattempo), {below_min_price_count} scartate perche' "
        f"sotto {format_eur(BUNDLE_MIN_MARKET_PRICE_EUR)} di prezzo minimo di mercato, "
        f"{error_count} errori di query.")
    log(f"[diagnostica valute] branch usati in eur_price_from_amounts: "
        f"{track.get_currency_branch_stats()}")

    return on_sale, manager_found


# --- Auto-discovery del manager (FIX 18/07 v3, vedi AUTO_FIND_MANAGER sopra) ---

# Come risalire dal singolo card_slug al manager che lo possiede (= il venditore, dato che
# raccogliamo solo carte con un annuncio di vendita appena aperto): introspection disabilitata
# come sempre, quindi si prova per tentativi una lista di forme note/plausibili del campo
# "proprietario attuale" su anyCard, nello stesso stile di probe_live_single_sale_offer_field.
# La prima che risponde senza errori con uno slug leggibile viene usata per tutte le carte.
CARD_OWNER_QUERY_CANDIDATES = [
    ("user", "query CardOwner($slug: String!) { anyCard(slug: $slug) { slug user { slug } } }"),
    ("userOwner", "query CardOwner($slug: String!) { anyCard(slug: $slug) { slug userOwner { user { slug } } } }"),
    ("tokenOwner", "query CardOwner($slug: String!) { anyCard(slug: $slug) { slug tokenOwner { user { slug } } } }"),
]

_card_owner_variant = None  # None = non ancora scoperto, '' = nessun candidato funziona


def _extract_owner_slug(card_data, variant):
    if not card_data:
        return None
    if variant == 'user':
        return (card_data.get('user') or {}).get('slug')
    return ((card_data.get(variant) or {}).get('user') or {}).get('slug')


def lookup_card_owner(card_slug):
    """Ritorna lo slug del manager proprietario di card_slug, o None. Al primo utilizzo scopre
    (e logga) quale variante di query funziona; le chiamate successive riusano quella."""
    global _card_owner_variant
    if _card_owner_variant == '':
        return None
    variants = ([v for v in CARD_OWNER_QUERY_CANDIDATES if v[0] == _card_owner_variant]
                if _card_owner_variant else CARD_OWNER_QUERY_CANDIDATES)
    for variant, query in variants:
        try:
            data = track.graphql_query(query, {"slug": card_slug})
        except Exception as e:
            log(f"[auto-find] eccezione di rete sul lookup proprietario di {card_slug}: {e}")
            return None
        if data.get('errors'):
            if _card_owner_variant is None:
                log(f"[auto-find] variante proprietario '{variant}' NON leggibile: {data['errors']}")
            continue
        card_data = (data.get('data') or {}).get('anyCard')
        owner = _extract_owner_slug(card_data, variant)
        if _card_owner_variant is None:
            _card_owner_variant = variant
            log(f"[auto-find] variante proprietario '{variant}' FUNZIONA su anyCard -- la uso "
                f"per tutti i lookup successivi.")
        return owner
    if _card_owner_variant is None:
        _card_owner_variant = ''
        log("[auto-find] NESSUNA variante di lookup proprietario funziona su anyCard -- "
            "auto-discovery impossibile con le query note, interrompo (gli errori esatti sono "
            "sopra nel log, da li' si capisce come correggere i nomi di campo).")
    return None


def collect_on_sale_candidates_from_market(eth_rate, listen_seconds):
    """Ascolta il canale eventi Sorare (STESSA subscription gia' collaudata di track.py, zero
    query nuove da scoprire) per listen_seconds secondi e raccoglie le carte Limited FOOTBALL
    in_season appena messe in vendita: status 'opened', vendita diretta a soldi (nessuna carta
    lato ricevente), singola carta (niente bundle, stesso principio di track.py), prezzo >=
    BUNDLE_MIN_MARKET_PRICE_EUR (coerente col filtro dello scan). Ritorna una lista di dict
    {card_slug, player_slug, price} senza doppioni."""
    candidates = []
    seen_slugs = set()
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": track.SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    def on_open(ws):
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({"command": "message", "identifier": identifier,
                            "data": json.dumps(subscription_payload)}))

    def on_message(ws, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return
        if message.get('type') in ('welcome', 'ping', 'confirm_subscription'):
            return
        payload = message.get('message')
        if not payload or payload.get('errors'):
            return
        offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
        if not offer:
            return
        if not (offer.get('id') or '').startswith('SingleSaleOffer:'):
            return
        if offer.get('status') != 'opened':
            return
        sender_side = offer.get('senderSide') or {}
        receiver_side = offer.get('receiverSide') or {}
        if receiver_side.get('anyCards'):
            return  # scambio carta-per-carta, non una vendita a soldi
        price = track.eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
        if price is None or price < BUNDLE_MIN_MARKET_PRICE_EUR:
            return
        cards = sender_side.get('anyCards') or []
        if len(cards) != 1:
            return  # bundle multi-carta o dato vuoto, prezzo non attribuibile
        card = cards[0]
        if card.get('rarityTyped') != 'limited' or card.get('sport') != 'FOOTBALL':
            return
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        if track.season_type_for_card(card, season_name) != 'in_season':
            return
        card_slug = card.get('slug')
        if not card_slug or card_slug in seen_slugs:
            return
        seen_slugs.add(card_slug)
        candidates.append({
            'card_slug': card_slug,
            'player_slug': (card.get('anyPlayer') or {}).get('slug'),
            'price': price,
        })

    def on_error(ws, error):
        log(f"[auto-find] errore WebSocket durante l'ascolto: {error}")

    ws = track.websocket.WebSocketApp(
        track.WS_URL,
        header=[f"Cookie: {track.COOKIES}"] if track.COOKIES else [],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    timer = threading.Timer(listen_seconds, ws.close)
    timer.daemon = True
    timer.start()
    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()
    return candidates


def auto_find_manager(eth_rate):
    """Trova un manager 'interessante' da scansionare: ascolta il mercato, raggruppa le carte
    appena messe in vendita per manager venditore (i manager visti PIU' volte nello stream sono
    controllati per primi: chi sta listando molte carte e' il candidato piu' probabile ad averne
    almeno AUTO_FIND_MIN_CARDS_FOR_SALE), e ritorna (slug, on_sale) del primo candidato che
    supera SIA la soglia sul numero di carte SIA la soglia sullo scarto best-deal -- oppure
    (None, None) se nessuno le supera entro i tetti di sicurezza.

    FIX 10/08 (v2, richiesta esplicita dell'utente, caso reale jafar1006: 27 carte 'gia' al
    minimo di mercato' ma ognuna solo pochi centesimi sotto -- non un'occasione, il segnale di
    un manager/bot che non accetta offerte al ribasso): superata la soglia sul numero di carte,
    il candidato viene scansionato per intero (scan_manager_market, la STESSA logica usata per
    l'input manuale) e si calcola lo scarto totale del pacchetto best-deal. Sotto
    AUTO_FIND_MIN_BEST_DEAL_GAP_EUR il candidato viene scartato e la ricerca CONTINUA sul
    prossimo -- mai una notifica su un pacchetto senza un vero margine."""
    log(f"[auto-find] nessun manager fornito e modalita' auto-discovery ATTIVA: ascolto il "
        f"mercato per {AUTO_FIND_LISTEN_SECONDS:.0f}s a caccia di manager con almeno "
        f"{AUTO_FIND_MIN_CARDS_FOR_SALE} carte in_season in vendita...")
    candidates = collect_on_sale_candidates_from_market(eth_rate, AUTO_FIND_LISTEN_SECONDS)
    log(f"[auto-find] ascolto terminato: {len(candidates)} carte in_season appena messe in "
        f"vendita raccolte (sopra {format_eur(BUNDLE_MIN_MARKET_PRICE_EUR)}).")
    if not candidates:
        return None, None

    owner_counts = {}
    lookups = 0
    for cand in candidates:
        if lookups >= AUTO_FIND_MAX_OWNER_LOOKUPS:
            break
        owner = lookup_card_owner(cand['card_slug'])
        lookups += 1
        time.sleep(PER_PLAYER_QUERY_DELAY_SECONDS)
        if _card_owner_variant == '':
            return None, None  # nessuna query di lookup funziona, gia' loggato
        if owner:
            owner_counts[owner] = owner_counts.get(owner, 0) + 1
    if not owner_counts:
        log("[auto-find] nessun proprietario leggibile tra le carte raccolte, interrompo.")
        return None, None

    ordered = sorted(owner_counts.items(), key=lambda kv: kv[1], reverse=True)
    log(f"[auto-find] {len(ordered)} manager venditori distinti individuati "
        f"(top: {', '.join(f'{m} x{c}' for m, c in ordered[:5])}) -- controllo quante carte "
        f"in_season hanno DAVVERO in vendita, in ordine di frequenza nello stream...")
    cooldown = _load_auto_find_cooldown()
    for owner, seen_count in ordered[:AUTO_FIND_MAX_MANAGERS_TO_CHECK]:
        # FIX 18/07 (v4): ignora i manager in blacklist durante auto-discovery
        if owner in AUTO_FIND_BLACKLIST_MANAGERS:
            log(f"[auto-find] '{owner}': blacklistato (bot noto che non accetta offerte "
                f"negoziate), passo oltre.")
            continue
        # FIX 18/07 (v5, richiesta esplicita dell'utente): gia' scansionato via auto-discovery
        # negli ultimi AUTO_FIND_COOLDOWN_DAYS giorni -- passo oltre per evitare di notificare
        # ripetutamente sullo stesso manager solo perche' una sua carta e' rimasta "sotto tiro"
        # nello stream. Non si applica all'input manuale (che non passa da questa funzione).
        if _is_in_auto_find_cooldown(owner, cooldown):
            log(f"[auto-find] '{owner}': scansionato di recente (entro {AUTO_FIND_COOLDOWN_DAYS:.0f} "
                f"giorni) via auto-discovery, in raffreddamento -- passo oltre.")
            continue
        cards, _nb, found, has_sale_field = fetch_manager_owned_in_season_limited_cards(owner)
        if not found:
            log(f"[auto-find] '{owner}': non trovato (slug non risolvibile?), passo oltre.")
            continue
        if not has_sale_field:
            log(f"[auto-find] '{owner}': campo liveSingleSaleOffer non disponibile, il "
                f"conteggio 'in vendita' non e' verificabile a costo ragionevole -- passo oltre.")
            continue
        n_for_sale = len(cards)
        log(f"[auto-find] '{owner}': {n_for_sale} carte in_season in vendita "
            f"(soglia {AUTO_FIND_MIN_CARDS_FOR_SALE}).")
        if n_for_sale < AUTO_FIND_MIN_CARDS_FOR_SALE:
            continue

        log(f"[auto-find] '{owner}': sopra soglia carte -- controllo il mercato per calcolare "
            f"lo scarto del pacchetto best-deal prima di impegnarmi...")
        on_sale, _found2 = scan_manager_market(owner, eth_rate)
        # Scansionato per intero: in raffreddamento per la sola auto-discovery a prescindere
        # dall'esito, per non ripetere la stessa scansione costosa ogni run.
        cooldown[owner] = datetime.datetime.now().isoformat()
        _save_auto_find_cooldown(cooldown)
        if not on_sale:
            log(f"[auto-find] '{owner}': nessuna carta davvero in vendita dopo il controllo "
                f"mercato, passo oltre.")
            continue
        cheapest_only = [c for c in on_sale if c['listing_price'] <= c['market_min_price']]
        best_deal_cards = _select_best_deal_cards(cheapest_only)
        gap_sum = sum(c['gap'] for c in best_deal_cards)
        log(f"[auto-find] '{owner}': scarto totale pacchetto best-deal {format_eur(gap_sum)} "
            f"su {len(best_deal_cards)} carte (soglia {format_eur(AUTO_FIND_MIN_BEST_DEAL_GAP_EUR)}).")
        if gap_sum < AUTO_FIND_MIN_BEST_DEAL_GAP_EUR:
            log(f"[auto-find] '{owner}': scarto sotto soglia -- probabile manager/bot che non "
                f"accetta offerte al ribasso, scarto il candidato e continuo la ricerca.")
            continue
        log(f"[auto-find] SELEZIONATO '{owner}' -- parte il report (in raffreddamento per i "
            f"prossimi {AUTO_FIND_COOLDOWN_DAYS:.0f} giorni per la sola auto-discovery).")
        return owner, on_sale
    log(f"[auto-find] nessun manager idoneo (soglia carte + soglia scarto best-deal) tra i primi "
        f"{AUTO_FIND_MAX_MANAGERS_TO_CHECK} controllati -- nessuno scan, riprova piu' tardi "
        f"(o allunga AUTO_FIND_LISTEN_SECONDS).")
    return None, None


def run_bundle_scan():
    manager_slug = extract_manager_slug(MANAGER_INPUT)

    # FIX 18/07 (v3): l'input manuale ha SEMPRE la precedenza (richiesta esplicita: "non mi
    # toccare la possibilita' di inserire io il manager che voglio") -- l'auto-discovery parte
    # solo se il campo manager e' vuoto E la modalita' e' esplicitamente attivata.
    if not manager_slug and not AUTO_FIND_MANAGER:
        log("nessuno slug/URL manager fornito (env var MANAGER_SLUG_OR_URL vuota) e "
            "auto-discovery spenta -- interrompo, nessuna notifica Telegram.")
        return

    eth_rate = track.get_eth_rate()
    track.reset_currency_branch_stats()

    if manager_slug:
        log(f"input ricevuto: {MANAGER_INPUT!r} -> slug estratto: '{manager_slug}'")
        # Input manuale: nessuna soglia di scarto best-deal (l'utente ha scelto apposta questo
        # manager, non c'e' una "ricerca" da continuare su un altro candidato).
        on_sale, manager_found = scan_manager_market(manager_slug, eth_rate)
        if manager_found is False or manager_found is None:
            log("nessuna notifica Telegram inviata.")
            return
    else:
        manager_slug, on_sale = auto_find_manager(eth_rate)
        if not manager_slug:
            log("[auto-find] nessun manager idoneo trovato in questo giro -- interrompo, "
                "nessuna notifica Telegram.")
            return

    if not on_sale:
        log(f"'{manager_slug}' possiede carte in_season ma NESSUNA risulta attualmente in "
            f"vendita -- nessuna notifica Telegram inviata.")
        return

    total_asking = sum(c['listing_price'] for c in on_sale)
    total_market_min = sum(c['market_min_price'] for c in on_sale)
    n_blocks = math.ceil(len(on_sale) / BUNDLE_BLOCK_SIZE)
    n_cheapest_only = sum(1 for c in on_sale if c['listing_price'] <= c['market_min_price'])

    log(f"RISULTATO -- '{manager_slug}': {len(on_sale)} carte in vendita organizzate in "
        f"{n_blocks} blocchi da {BUNDLE_BLOCK_SIZE} (limite Sorare per offerta cumulativa), "
        f"richiesta totale {format_eur(total_asking)}, minimo di mercato totale "
        f"{format_eur(total_market_min)} (dettaglio/offerta per blocco nel messaggio Telegram) -- "
        f"di cui {n_cheapest_only} gia' al minimo di mercato (sezione bonus separata).")

    html_path = write_html_report(manager_slug, on_sale)
    log(f"report HTML scritto: {html_path}")
    # Riga grezza (non attraverso log(), per restare facilmente grep-abile dal workflow) che
    # segnala che QUESTA run ha davvero prodotto un report -- il file HTML e' a percorso fisso
    # e sovrascritto ad ogni run, quindi la sua sola presenza non basta a dire che e' fresco.
    print(f"REPORT_READY {manager_slug} {len(on_sale)}")


# FIX 10/08 (richiesta esplicita dell'utente): al posto dei messaggi Telegram a blocchi (limite
# 4096 caratteri, impacchettamento in piu' messaggi separati), un UNICO report HTML con la stessa
# identica logica (blocchi da BUNDLE_BLOCK_SIZE, sezione bonus "gia' al minimo di mercato", best
# deal) ma senza limiti di lunghezza e con i nomi dei giocatori cliccabili -- link diretto alla
# carta sul mercato (stesso pattern gia' collaudato in track.py, manager-sales/<player_slug>/
# limited?card=<card_slug>). Percorso fisso, sovrascritto ad ogni run (stesso principio del log
# accodato dagli altri scanner: si legge dopo un pull, senza Chrome ne' copia-incolla).
HTML_REPORT_PATH = os.environ.get('HTML_REPORT_PATH', 'scanners/logs/manager_bundle_scan_report.html')

CARD_MARKET_LINK_TEMPLATE = ("https://sorare.com/it/football/market/shop/manager-sales/"
                              "{player_slug}/limited?card={card_slug}")


def _card_link(c):
    return CARD_MARKET_LINK_TEMPLATE.format(player_slug=c['player_slug'], card_slug=c['card_slug'])


def _html_escape(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                .replace('"', '&quot;'))


def _render_card_row_html(c):
    ok = c['listing_price'] <= c['market_min_price']
    dot = '🟢' if ok else '🔴'
    return (f'<tr class="{"ok" if ok else "over"}"><td>{dot}</td>'
            f'<td><a href="{_card_link(c)}" target="_blank">{_html_escape(c["player_name"])}</a></td>'
            f'<td>{format_eur(c["listing_price"])}</td>'
            f'<td>{format_eur(c["market_min_price"])}</td></tr>')


def _render_block_html(block, block_idx, start_n, end_n):
    rows = "\n".join(_render_card_row_html(c) for c in block)
    block_asking = sum(c['listing_price'] for c in block)
    block_market_min = sum(c['market_min_price'] for c in block)
    block_offer = block_market_min * (1 - BUNDLE_OFFER_MARGIN_FRACTION)
    return f"""<div class="block">
  <h3>Blocco {block_idx} (carte {start_n}-{end_n})</h3>
  <table>
    <tr><th></th><th>Giocatore</th><th>In vendita</th><th>Minimo mercato</th></tr>
    {rows}
  </table>
  <p class="subtotal">Subtotale: richiesto {format_eur(block_asking)}, minimo mercato {format_eur(block_market_min)}</p>
  <p class="offer">OFFRI FINO A {format_eur(block_offer)} <span class="margin">(margine {BUNDLE_OFFER_MARGIN_FRACTION:.0%} -- valore provvisorio, da tarare)</span></p>
</div>"""


def _render_blocks_section_html(title, subtitle, cards):
    """Genera una sezione (titolo + blocchi da BUNDLE_BLOCK_SIZE + totale) per una lista generica
    di carte -- riusata sia per TUTTE le carte in vendita sia per il sotto-insieme "gia' al minimo
    di mercato" (stessa fattorizzazione che prima serviva ai messaggi Telegram, vedi _render_card_
    blocks nella versione precedente). Nessun limite di blocchi mostrati: a differenza di Telegram,
    l'HTML non ha un tetto di caratteri per messaggio."""
    if not cards:
        return ""
    blocks = [cards[i:i + BUNDLE_BLOCK_SIZE] for i in range(0, len(cards), BUNDLE_BLOCK_SIZE)]
    blocks_html = []
    for idx, block in enumerate(blocks, start=1):
        start_n = (idx - 1) * BUNDLE_BLOCK_SIZE + 1
        end_n = start_n + len(block) - 1
        blocks_html.append(_render_block_html(block, idx, start_n, end_n))
    total_asking = sum(c['listing_price'] for c in cards)
    total_market_min = sum(c['market_min_price'] for c in cards)
    subtitle_html = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
    return f"""<section>
  <h2>{title} ({len(cards)} carte, {len(blocks)} blocchi da {BUNDLE_BLOCK_SIZE})</h2>
  {subtitle_html}
  {"".join(blocks_html)}
  <p class="total">Totale complessivo: {len(cards)} carte, richiesto {format_eur(total_asking)}, minimo mercato {format_eur(total_market_min)} (informativo -- non offribile in un colpo solo oltre le {BUNDLE_BLOCK_SIZE} carte, vedi offerte per blocco sopra)</p>
</section>"""


def _select_best_deal_cards(cheapest_only):
    """FIX 18/07 (v2, richiesta esplicita dell'utente, funzione 'best deal'): tra le carte GIA'
    al minimo di mercato (cheapest_only), seleziona fino a BUNDLE_BLOCK_SIZE carte classificando
    per lo SCARTO verso 'la sua carta immediatamente piu' costosa in vendita sul mercato'
    (second_min_price). Esempio dell'utente: manager X vende Mbappe a 5EUR (il minimo), il
    secondo venditore piu' economico lo offre a 6EUR -> scarto 1EUR; tra tutte le carte gia' al
    minimo, prendiamo le 10 con lo scarto piu' ampio (l'occasione piu' isolata dalla
    concorrenza). A parita' di scarto, richiesta esplicita dell'utente: "preferire nel pacchetto
    best deal la carta piu' costosa" -- tie-break su market_min_price decrescente.

    Le carte SENZA un secondo prezzo comparabile (second_min_price None, nessun altro annuncio
    per quel giocatore) sono escluse da questa classifica: senza un secondo prezzo lo scarto non
    e' calcolabile in modo significativo -- restano comunque nei blocchi normali e nella sezione
    bonus, solo non concorrono al best deal. Ritorna una lista (eventualmente vuota) di al
    massimo BUNDLE_BLOCK_SIZE dict, ciascuno con in piu' la chiave 'gap' rispetto a
    cheapest_only."""
    candidates = [dict(c, gap=c['second_min_price'] - c['market_min_price'])
                  for c in cheapest_only if c.get('second_min_price') is not None]
    candidates.sort(key=lambda c: (c['gap'], c['market_min_price']), reverse=True)
    return candidates[:BUNDLE_BLOCK_SIZE]


def _render_best_deal_row_html(c):
    return (f'<tr class="ok"><td>🟢</td>'
            f'<td><a href="{_card_link(c)}" target="_blank">{_html_escape(c["player_name"])}</a></td>'
            f'<td>{format_eur(c["market_min_price"])}</td>'
            f'<td>{format_eur(c["second_min_price"])}</td>'
            f'<td>{format_eur(c["gap"])}</td></tr>')


def _render_best_deal_section_html(cards):
    """Renderizza l'UNICA sezione speciale 'BEST DEAL' -- al massimo BUNDLE_BLOCK_SIZE carte, mai
    paginata in piu' blocchi (e' gia' una cernita tra le migliori, non l'intero insieme)."""
    if not cards:
        return ""
    rows = "\n".join(_render_best_deal_row_html(c) for c in cards)
    asking = sum(c['listing_price'] for c in cards)
    market_min = sum(c['market_min_price'] for c in cards)
    offer = market_min * (1 - BUNDLE_OFFER_MARGIN_FRACTION)
    return f"""<section>
  <h2>🏆 Best deal -- le {len(cards)} carte piu' isolate dalla concorrenza</h2>
  <table>
    <tr><th></th><th>Giocatore</th><th>Minimo mercato</th><th>Secondo prezzo</th><th>Scarto</th></tr>
    {rows}
  </table>
  <p class="subtotal">Subtotale: richiesto {format_eur(asking)}, minimo mercato {format_eur(market_min)}</p>
  <p class="offer">OFFRI FINO A {format_eur(offer)} <span class="margin">(margine {BUNDLE_OFFER_MARGIN_FRACTION:.0%} -- valore provvisorio, da tarare)</span></p>
</section>"""


def write_html_report(manager_slug, on_sale):
    """Genera l'UNICO report HTML per questa scansione -- stessa identica logica dei vecchi
    messaggi Telegram a blocchi (blocchi da BUNDLE_BLOCK_SIZE ordinati per prezzo crescente,
    sezione bonus "gia' al minimo di mercato", sezione best deal), ma in un solo file senza
    limiti di lunghezza e con i nomi dei giocatori cliccabili (link diretto alla carta sul
    mercato). Sovrascrive HTML_REPORT_PATH ad ogni run. Ritorna il percorso scritto."""
    on_sale = sorted(on_sale, key=lambda c: c['listing_price'])
    manager_url = (f"https://sorare.com/it/football/my-club/{manager_slug}/cards/limited"
                   f"?sale=true&is=true")
    cheapest_only = [c for c in on_sale if c['listing_price'] <= c['market_min_price']]
    best_deal_cards = _select_best_deal_cards(cheapest_only)

    main_section = _render_blocks_section_html(
        "Tutte le carte in vendita", None, on_sale)
    bonus_section = _render_blocks_section_html(
        "🟢 Bonus -- gia' al minimo di mercato",
        "Per queste il manager e' gia' il venditore piu' economico -- nessuna alternativa piu' "
        "a buon mercato altrove.",
        cheapest_only)
    best_deal_section = _render_best_deal_section_html(best_deal_cards)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bundle scan -- {manager_slug}</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; max-width: 720px; margin: 20px auto; padding: 0 12px; color: #222; }}
h1 {{ font-size: 1.3rem; }}
h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
h3 {{ font-size: 1rem; margin-bottom: 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; margin-bottom: 6px; }}
td, th {{ padding: 4px 6px; border-bottom: 1px solid #eee; text-align: left; }}
tr.over td {{ color: #a33; }}
tr.ok td {{ color: #1a7a1a; }}
a {{ color: #1a5cbf; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.subtotal {{ margin: 4px 0; font-size: 0.9rem; }}
.offer {{ background: #fff3cd; border: 1px solid #ffe08a; padding: 8px; font-weight: bold; text-align: center; border-radius: 6px; }}
.margin {{ font-weight: normal; font-size: 0.8rem; }}
.total {{ font-weight: bold; margin-top: 8px; }}
.subtitle {{ font-size: 0.85rem; color: #666; }}
.block {{ margin-bottom: 1.2rem; }}
</style>
</head>
<body>
<h1>🎯 {manager_slug} -- {len(on_sale)} carte Limited in_season in vendita</h1>
<p><a href="{manager_url}" target="_blank">📂 Vai alle carte in vendita di {manager_slug}</a></p>
<p style="font-size:0.85rem;color:#666;">Generato {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} -- 🟢 gia' al minimo di mercato, 🔴 in vendita sopra il minimo (esiste altrove piu' a buon mercato).</p>
{best_deal_section}
{main_section}
{bonus_section}
</body>
</html>
"""
    os.makedirs(os.path.dirname(HTML_REPORT_PATH) or '.', exist_ok=True)
    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    return HTML_REPORT_PATH


if __name__ == '__main__':
    run_bundle_scan()
