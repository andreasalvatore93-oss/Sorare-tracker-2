import json
import os
import re
import time
import sqlite3
import datetime
import smtplib
import threading
from email.message import EmailMessage

import requests
import websocket  # pip install websocket-client

# ---- Configurazione da variabili d'ambiente (secrets) ----
COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = os.environ.get('SORARE_CSRF')
EMAIL_USER = os.environ.get('GMAIL_ADDRESS')
EMAIL_PASS = os.environ.get('GMAIL_APP_PASSWORD')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

GRAPHQL_URL = 'https://api.sorare.com/graphql'

# Per quanti secondi restare in ascolto ad ogni esecuzione.
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '200'))

DROP_THRESHOLD = 0.08    # FIX 16/07 (v10, richiesta esplicita): 13% -> 8%, in prova

# FIX 16/07 (v14, casi Zeki Celik / Ricardo Velho): la notifica veloce (send_instant_alert) non
# fa nessun controllo margine sul secondo prezzo attuale (lo salta apposta per restare veloce,
# senza query live) -- quindi puo' segnalare come "occasione" un prezzo che e' si' il minimo del
# momento, ma dentro un cluster fitto di annunci quasi identici (Celik: 2.58EUR contro
# 2.74/2.76/2.80EUR ecc., margine reale ~5.8% contro il 15.7% che la verifica completa
# richiederebbe per quella fascia; Velho: margine ~2.7% contro il 10% richiesto) -- non e' un
# affare distinto, solo rumore statistico. Senza dati sul secondo prezzo (che richiederebbe una
# query live, esattamente cio' che la notifica veloce evita), soglia piu' alta come proxy
# grezzo: un calo cosi' ampio raramente e' solo rumore di cluster. Richiesta esplicita: 12%,
# da provare.
INSTANT_ALERT_DROP_THRESHOLD = 0.12

MAX_SUSPECT_DROP = 0.50  # oltre il 50% consideriamo il dato sospetto/errato
MIN_PRICE_EUR = float(os.environ.get('MIN_PRICE_EUR', '2.0'))  # sotto questa soglia, ignoriamo la carta

# NOTA STORICA: qui c'era CLEAR_DROP_THRESHOLD (v4), che bypassava del tutto il controllo sul
# margine per i cali >=25%, per evitare che cali chiari e ampi venissero scartati solo perche'
# esisteva un secondo annuncio quasi altrettanto economico. Ma il caso Arijanet Muric ha
# mostrato il problema: un calo dell'58.6% con margine reale dello 0.5% (2.07EUR contro
# 2.08EUR, praticamente identici) e' passato senza alcun controllo, perche' il floor storico
# era probabilmente solo vecchio/sballato, non perche' quella carta specifica fosse
# un'occasione. Sostituito in v7 da find_meaningful_second_price qui sotto: invece di
# bypassare il controllo margine oltre una certa soglia di calo, scavalchiamo solo gli
# annunci troppo vicini al minimo (un "cluster" di prezzi quasi identici, es. 2.07/2.08/2.14
# come nel caso Muric) e confrontiamo con il primo prezzo che rappresenta un vero salto --
# funziona correttamente sia per cali piccoli che grandi, senza il bypass grezzo di prima.

# Se il riferimento (floor) salvato nel database e' piu' vecchio di cosi', non ci fidiamo piu':
# nei "buchi" di ascolto tra un'esecuzione e l'altra il mercato puo' essersi mosso senza che il
# bot se ne accorgesse, quindi un floor troppo vecchio produrrebbe un calo% inventato.
MAX_FLOOR_AGE_HOURS = float(os.environ.get('MAX_FLOOR_AGE_HOURS', '48'))

# FIX 16/07 (v13, casi Matt Miazga e Kristian Thorstvedt vs Ugurcan Cakir): la notifica veloce
# (send_instant_alert) confronta SOLO col floor salvato, senza nessuna verifica live -- se quel
# floor non viene aggiornato da tempo (nessun evento WS per quel giocatore/bucket da un pezzo),
# puo' restare bloccato su un valore ormai lontanissimo dal vero mercato: caso Miazga, floor
# fermo a ~4.21EUR mentre il mercato reale era gia' crollato a 0.32EUR (2.74EUR spacciato per un
# calo del 34.9% quando era 8 volte piu' caro del vero minimo); stesso pattern su Thorstvedt
# (calo dichiarato 42.9%, vero minimo di mercato 0.66EUR). D'altra parte una soglia troppo larga
# (es. le 48h di MAX_FLOOR_AGE_HOURS usate nella verifica completa) non basta a fare da "via di
# mezzo": il caso Ugurcan Cakir (6.07EUR, catturato PRIMA che comparisse nel mercato pubblico,
# floor probabilmente aggiornato solo poche ore prima) e' un'occasione vera che va lasciata
# passare. Soglia dedicata e piu' stretta solo per l'alert veloce: sopra questa eta' il floor
# non e' abbastanza fresco per fidarsi senza verifica live, si salta l'alert veloce e si aspetta
# comunque l'alert ufficiale (verificato) come sempre.
INSTANT_ALERT_MAX_FLOOR_AGE_HOURS = float(os.environ.get('INSTANT_ALERT_MAX_FLOOR_AGE_HOURS', '6'))

# NOTA STORICA: qui c'era un limite fisso "ultimi N annunci" (LIVE_CHECK_LAST_N, alzato da
# 100 a 300 dopo il caso Jonas Urbig), ma un diagnostico dedicato ha rivelato che il server
# tronca comunque le risposte a un massimo di ~50 nodi per richiesta indipendentemente dal
# valore chiesto -- quindi quel numero non stava davvero risolvendo nulla oltre 50 (confermato
# sul caso Justin Bijlow). Sostituito con la paginazione vera (PAGE_SIZE/MAX_PAGES piu' sotto,
# vedi fetch_all_live_offers), che scorre TUTTE le pagine invece di sperare in un numero grande
# a sufficienza.

# Se il prezzo minimo attuale non e' almeno questa % piu' basso del SECONDO prezzo piu'
# basso attualmente in vendita, non e' un vero affare: e' solo rumore statistico dentro un
# gruppo di annunci quasi identici (es. 2.34EUR contro 2.35EUR) -- anche se rispetto al
# vecchio riferimento storico sembra un grande calo%.
MIN_MARGIN_OVER_SECOND = float(os.environ.get('MIN_MARGIN_OVER_SECOND', '0.08'))  # fallback di sicurezza, vedi required_margin_fraction

# FIX 16/07: margine minimo richiesto non piu' fisso all'8% ma a scaglioni in base al prezzo
# di riferimento (second_min_price) -- numeri forniti direttamente dall'utente come "prezzo
# soglia -> prezzo massimo della carta nuova" per fascia, qui tradotti in percentuale
# (scaglione, prezzo_massimo_carta_nuova). Es. sotto i 3EUR il prezzo minimo verificato deve
# stare a 2.50EUR o meno (margine 16.7%); sotto i 5EUR a 4.30EUR o meno (14.0%); e cosi' via.
# Oltre i 60EUR si passa a uno sconto assoluto fisso di 5EUR (FLAT_MARGIN_EUR_ABOVE_60) invece
# che a una percentuale, altrimenti servirebbe uno sconto enorme in euro per carte costose.
# FIX 16/07 (v2): ogni soglia percentuale abbassata di 1 punto percentuale su richiesta
# esplicita dell'utente (il flat da 5EUR oltre i 60EUR NON tocco, non e' una percentuale).
MARGIN_TIERS = [
    (3, 2.59),  # FIX 17/07 (caso Philipp Kohn, richiesta esplicita): 15.7% -> 13.7%
    (5, 4.45),  # FIX 16/07 (v21, caso Amad Diallo): 12.0% -> 11.0%, richiesta esplicita
    (10, 9.05),  # FIX 16/07 (v17, caso Mike Penders): 10.0% -> 9.5%, richiesta esplicita
    (15, 13.65),
    (20, 18.40),  # FIX 16/07 (v5, caso Rodrigo): 9.0% -> 8.0%, richiesta esplicita
    (25, 23.25),
    (30, 27.80),
    (35, 32.85),
    (40, 36.40),
    (45, 42.45),
    (50, 47.50),
    (55, 52.75),
    (60, 56.60),
]
FLAT_MARGIN_EUR_ABOVE_60 = 5.0


def required_margin_fraction(reference_price):
    """Frazione minima di sconto richiesta tra il prezzo minimo vero e il secondo prezzo
    attuale, a scaglioni in base al prezzo di riferimento (vedi MARGIN_TIERS). Sotto ogni
    soglia si applica la percentuale di quello scaglione; da 60EUR in su si passa a uno
    sconto assoluto fisso di 5EUR (converte in percentuale via FLAT_MARGIN_EUR_ABOVE_60 /
    reference_price, quindi via via piu' basso in % man mano che il prezzo sale)."""
    if reference_price <= 0:
        return MIN_MARGIN_OVER_SECOND
    for upper_bound, max_price in MARGIN_TIERS:
        if reference_price < upper_bound:
            return (upper_bound - max_price) / upper_bound
    return FLAT_MARGIN_EUR_ABOVE_60 / reference_price


# NOTA STORICA: qui c'era find_meaningful_second_price (v7, caso Arijanet Muric), che
# scavalcava gli annunci vicini al minimo per confrontare con un "salto" piu' su nella lista.
# Rimossa in v9 (vedi nota nel blocco margine dentro evaluate_player_offer) perche' pericolosa
# nel caso di un giocatore infortunato: il crollo del prezzo "giusto" a un nuovo livello basso
# (piu' venditori si allineano li') veniva scavalcato a favore di un vecchio annuncio piu' caro
# e stagnante, scambiato per "occasione" quando in realta' era solo il nuovo prezzo di mercato.

# FIX 16/07 (caso Antonio Sivera): Sorare tiene un annuncio appena creato invisibile sul
# mercato pubblico per ~2 minuti (finestra per permettere al venditore di ritirarlo se ha
# sbagliato prezzo -- confermato dalla documentazione Sorare). Un annuncio piu' economico
# creato poco prima della nostra verifica live puo' quindi non comparire ancora nella query,
# facendo scartare per errore un caso come "margine troppo vicino al secondo annuncio" quando
# in realta' il vero piu' economico era ancora nella finestra di invisibilita'. Non ha senso
# aspettare BLOCCATI 2+ minuti dentro la gestione di un singolo evento (bloccherebbe l'intero
# ascolto): invece, i casi scartati per margine troppo vicino vengono messi in una coda
# (tabella pending_recheck) e riverificati piu' avanti, all'inizio di una esecuzione
# successiva, quando la finestra di invisibilita' e' sicuramente passata.
MARKET_VISIBILITY_DELAY_SECONDS = float(os.environ.get('MARKET_VISIBILITY_DELAY_SECONDS', '150'))  # 2.5 min, margine di sicurezza sopra i ~2 min di Sorare
PENDING_RECHECK_MAX_AGE_SECONDS = float(os.environ.get('PENDING_RECHECK_MAX_AGE_SECONDS', '1800'))  # oltre 30 min il caso non e' piu' rilevante, si scarta senza riverificare

# FIX 16/07 (v16, "bug del centesimo"): il controllo sopra (price_eur < true_min_price) confonde
# la vera finestra di invisibilita' con semplice rumore di arrotondamento nella conversione
# wei->EUR -- log reali mostrano casi ripetuti con scarti di 1-5 centesimi (~0.2-0.4% relativo,
# es. Sergi Dominguez 3.43 contro 3.44, Filip Jorgensen 3.76 contro 3.77, Gianluca Prestianni
# 2.29 contro 2.30) che non si risolvono MAI da un run all'altro (non e' un annuncio che diventa
# visibile, e' semplicemente rumore che si ripete identico), a differenza di scarti piu' ampi
# (es. Kevin Radulovic 2.13 contro 2.29, ~7%; Luis Suarez 11.00 contro 12.30, ~10.6%) che sono
# quasi certamente annunci genuinamente ancora invisibili. Sotto questa soglia relativa si
# considera rumore e si ignora (si procede con true_min_price come prima, senza log ne' coda).
INVISIBILITY_GAP_TOLERANCE = float(os.environ.get('INVISIBILITY_GAP_TOLERANCE', '0.01'))  # 1%

# La stagione In Season attualmente in corso su Sorare. ATTENZIONE: leghe diverse usano formati
# diversi per lo stesso concetto di "stagione corrente" -- le leghe europee usano "2025-26" (a
# cavallo di due anni), ma la MLS (e leghe simili a calendario solare) usano solo l'anno, es.
# "2026". Confrontare solo con CURRENT_SEASON lasciava fuori la MLS: la sua carta In Season vera
# veniva scambiata per "classic" e mescolata nel calcolo del prezzo minimo insieme alle carte
# Classic vere (che invece hanno prezzi tra loro simili, indipendentemente dall'anno di stampa --
# verificato su Roman Bürki: tutte le sue Classic 2023/2024/2025 sono in un range 2.70-5.50EUR,
# mentre la sua vera carta In Season 2026 vale 12-18EUR. Il calo "sospetto" di prima era proprio
# questo: la carta In Season da 12-18EUR scambiata per classic). CURRENT_SEASON_LABELS contiene
# entrambi i formati; una carta e' "in season" se la sua stagione compare in questo insieme.
# Cambia una volta l'anno, di solito ad agosto: quando succede, aggiorna questi due valori.
CURRENT_SEASON = os.environ.get('CURRENT_SEASON', '2025-26')
CURRENT_SEASON_ALT = os.environ.get('CURRENT_SEASON_ALT', '2026')  # formato MLS/calendario solare
CURRENT_SEASON_LABELS = {CURRENT_SEASON, CURRENT_SEASON_ALT}

# FIX 16/07 (v18, caso Harvey Elliott): il confronto sopra (nome stagione contro un elenco
# statico) e' strutturalmente impreciso -- scoperto per tentativi che l'API espone un campo
# diretto, inSeasonEligible, che riflette l'idoneita' REALE alle competizioni di Sorare (la
# stessa mostrata nella UI come "Idoneita' alle competizioni"). Confermato sul caso Elliott:
# una sua carta con stagione stampata "2025" (formato che CURRENT_SEASON_LABELS non riconosce)
# risultava "Idoneita': Di stagione fino al 10 ago" nella UI -- quindi ancora in season -- ma il
# vecchio confronto testuale l'avrebbe trattata come classic, mescolandola erroneamente con una
# sua carta "24/25" davvero classic. Usiamo ora inSeasonEligible quando disponibile; se per
# qualche motivo il campo risultasse assente (None), ripieghiamo sul vecchio confronto testuale
# come rete di sicurezza, invece di assumere silenziosamente un valore che potrebbe essere sbagliato.
def season_type_for_card(card, season_name):
    in_season_eligible = card.get('inSeasonEligible')
    if in_season_eligible is not None:
        return 'in_season' if in_season_eligible else 'classic'
    return 'in_season' if season_name in CURRENT_SEASON_LABELS else 'classic'

# --- Doppio controllo sugli alert "dubbi" (calo sospetto >50% o dati incompleti) ---
# Prima questi casi venivano scartati subito e basta (nessuna notifica, solo log). Ora, prima
# di scartarli definitivamente, ripetiamo UNA SOLA VOLTA la verifica live dopo una breve pausa:
# un affare vero mostra lo stesso prezzo minimo anche a una seconda interrogazione indipendente,
# mentre un dato Sorare sporco/vecchio tende a NON essere stabile (sparisce, cambia in modo
# vistoso, o l'incompletezza persiste). Se le due interrogazioni concordano (entro RECHECK_TOLERANCE)
# e la seconda non e' a sua volta incompleta, notifichiamo comunque -- altrimenti resta scartato.
RECHECK_DELAY_SECONDS = float(os.environ.get('RECHECK_DELAY_SECONDS', '3'))
RECHECK_TOLERANCE = float(os.environ.get('RECHECK_TOLERANCE', '0.05'))  # 5% di scostamento massimo ammesso

# --- Rete di sicurezza incrociata tra bucket (caso Aral Şimşir: campionato turco concluso,
# Sorare aveva gia' spostato la carta in Classic nella propria UI ("Idoneita' alle
# competizioni: Classico"), ma sportSeason.name diceva ancora "2025-26" quindi il nostro
# bucket la trattava ancora come in_season -- le uniche 2 offerte trovate li' erano residui
# vecchi, mentre tutto il mercato vero (20+ annunci) era ormai in Classic a un prezzo piu'
# basso, rendendo il calo% calcolato sul floor "in season" puro rumore. Il problema e'
# strutturale: un'etichetta di stagione statica non riflette il fatto che ogni lega chiude
# la propria stagione in un mese diverso, non tutte ad agosto come CURRENT_SEASON presume.
# Soglie tenute conservative apposta per non penalizzare giocatori con un mercato in season
# genuinamente sottile (poco popolari ma reali): serve lo squilibrio di VOLUME insieme al
# prezzo piu' basso, non basta uno dei due da solo.
THIN_BUCKET_MAX_LISTINGS = int(os.environ.get('THIN_BUCKET_MAX_LISTINGS', '2'))
SIBLING_MIN_LISTINGS = int(os.environ.get('SIBLING_MIN_LISTINGS', '5'))
SIBLING_MIN_LISTINGS_MULTIPLIER = float(os.environ.get('SIBLING_MIN_LISTINGS_MULTIPLIER', '3'))
# NON e' "il gemello deve essere molto piu' economico": se il prezzo rilevato nel bucket
# sottile fosse molto piu' basso del mercato liquido gemello resterebbe un affare raro
# genuino, da notificare comunque. Blocchiamo solo quando il prezzo rilevato NON e'
# significativamente piu' basso di quello gemello (entro questa tolleranza) -- segno che
# non sta succedendo nulla di speciale, e' solo rumore di un riferimento vecchio in un
# bucket ormai senza scambi veri (verificato sui numeri reali di Aral Şimşir: 2.70EUR
# rilevato contro 2.54EUR nel gemello, solo ~6% di differenza -- non un affare distinto).
UNIQUE_DEAL_TOLERANCE = float(os.environ.get('UNIQUE_DEAL_TOLERANCE', '0.05'))

WS_URL = "wss://ws.sorare.com/cable"

# tokenOfferWasUpdated: canale dedicato alle offerte/vendite sul mercato
# (a differenza di anyCardWasUpdated, che riguarda la carta in generale:
# livello, XP, cambi di proprietario, non necessariamente le vendite).
# Non ha filtri lato server per rarita'/sport: filtriamo noi in Python.
SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    senderSide {
      amounts { eurCents wei usdCents gbpCents }
      anyCards {
        slug
        rarityTyped
        sport
        anyPlayer { slug displayName }
        sportSeason { name }
        inSeasonEligible
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents }
      anyCards { slug }
    }
  }
}
"""

# Query REST (non subscription) usata per verificare, al momento dell'alert, quale sia
# DAVVERO il prezzo minimo attualmente in vendita per un giocatore -- scoperta per tentativi
# (introspection disabilitata da Sorare) partendo dal campo tokens.liveAuctions gia' noto:
# tokens.liveSingleSaleOffers esiste con la stessa forma. Non accetta filtri rarity/sortBy
# lato server, quindi filtriamo e ordiniamo noi in Python.
# NOTA IMPORTANTE (scoperta in diagnostica): il server tronca SEMPRE le risposte a un
# massimo di ~50 nodi per richiesta, indipendentemente dal valore chiesto in "last" (anche
# chiedendo last:300 tornavano solo 50 nodi) -- ecco perche' alzare LIVE_CHECK_LAST_N da
# 100 a 300 non risolveva davvero i casi Jonas Urbig/Justin Bijlow. Confermato pero' che la
# paginazione a cursore FUNZIONA (pageInfo.hasPreviousPage + argomento "before"): scorrendo
# le pagine precedenti si recuperano TUTTI gli annunci (verificato: Bijlow aveva 55 annunci
# totali, primi 50 + 5 mancanti recuperati con "before"). Vedi fetch_all_live_offers().
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        receiverSide { amounts { eurCents wei usdCents gbpCents } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            sportSeason { name }
            inSeasonEligible
          }
        }
      }
    }
  }
}
"""

PAGE_SIZE = 50  # il vero massimo per richiesta imposto dal server, confermato in diagnostica
MAX_PAGES = 20  # tetto di sicurezza (fino a 1000 annunci totali) per evitare loop su volumi estremi


def fetch_all_live_offers(player_slug):
    """Scorre TUTTE le pagine di annunci live per un giocatore usando la paginazione a
    cursore confermata funzionante (before/startCursor), invece di fidarsi di un singolo
    "last: N" che il server tronca comunque a ~50 per richiesta."""
    all_nodes = []
    cursor = None
    for _ in range(MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[paginazione annunci live] errore per {player_slug}: {data['errors']}")
            break
        conn = (((data.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers') or {})
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


# FIX 17/07 (richiesta esplicita dell'utente, "mai capitato prima, ora con le aste 429"): con
# tre tracker attivi in concorrenza (classico, ZenLock, aste), il carico cumulativo di query
# verso Sorare a volte supera il rate limit (HTTP 429). Prima nessuna delle nostre graphql_query
# controllava lo status code -- un 429 veniva passato a .json() cosi' com'e' e il chiamante lo
# trattava come un generico "data.get('errors')" o, peggio, come lista vuota silenziosa
# (indistinguibile da "nessun dato reale disponibile" -- probabile causa dell'apparente bug nel
# filtro stagione delle aste e del picco anomalo di "scartate per mancanza comparabili" su
# ZenLock, entrambi nella stessa finestra di carico pesante di oggi). Ora rileva il 429
# esplicitamente e ritenta con backoff (rispetta l'header Retry-After se Sorare lo manda,
# altrimenti backoff esponenziale breve) invece di arrendersi subito.
def graphql_query(query, variables=None, max_retries=3):
    headers = {
        'Content-Type': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        r = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            retry_after = r.headers.get('Retry-After')
            try:
                wait_seconds = float(retry_after) if retry_after else (2 ** attempt) * 2
            except ValueError:
                wait_seconds = (2 ** attempt) * 2
            log(f"[rate limit] HTTP 429 da Sorare (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s prima di ritentare...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    log(f"[rate limit] HTTP 429 persistente dopo {max_retries} tentativi, rinuncio a questa query")
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


# --- Database: prezzo minimo storico per (giocatore, stagione) ---
def init_db():
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS floors (
            player_slug TEXT NOT NULL,
            season_name TEXT NOT NULL,
            floor_price_eur REAL NOT NULL,
            updated_at TEXT,
            PRIMARY KEY (player_slug, season_name)
        )
    ''')
    # Log strutturato di OGNI decisione (notifica o scarto), non solo degli alert mandati.
    # Obiettivo: poter calcolare a posteriori, guardando lo storico, quante notifiche erano
    # affari veri e quanti "SALTATO" erano invece occasioni perse -- un tasso misurabile di
    # falsi positivi/negativi, invece di doverselo ricordare a memoria dai messaggi Telegram.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS decisions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            player_slug TEXT,
            player_name TEXT,
            season_type TEXT,
            season_name TEXT,
            decision TEXT,
            floor_price REAL,
            true_min_price REAL,
            drop_percent REAL,
            second_min_price REAL,
            margin_percent REAL,
            reasons TEXT
        )
    ''')
    # Coda dei casi scartati per "margine troppo vicino" da riverificare piu' avanti, dopo
    # che la finestra di invisibilita' di ~2 minuti di Sorare per i nuovi annunci e' passata
    # (vedi nota su MARKET_VISIBILITY_DELAY_SECONDS). Un solo caso in coda per player_slug+
    # season_type alla volta: se lo stesso caso si ripresenta prima di essere processato,
    # aggiorniamo la riga esistente invece di accumularne altre.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pending_recheck (
            player_slug TEXT NOT NULL,
            season_type TEXT NOT NULL,
            player_name TEXT,
            season_name TEXT,
            price_eur REAL,
            card_slug TEXT,
            queued_at TEXT,
            PRIMARY KEY (player_slug, season_type)
        )
    ''')
    # FIX 16/07 (v19, caso Andres Cubas): il bot notificava solo sui CALI rispetto al floor
    # storico, mai su un margine ampio e persistente verso il secondo prezzo che pero' non
    # rappresenta un calo "nuovo" (es. il floor era gia' li' da un run precedente). Tabella
    # separata (non tocchiamo lo schema di floors, che usa INSERT OR REPLACE e cancellerebbe
    # una colonna aggiunta li' ad ogni aggiornamento) per ricordare l'ULTIMO prezzo minimo per
    # cui abbiamo gia' segnalato questa opportunita' di margine, cosi' da non ripeterla ad ogni
    # evento successivo se il prezzo non e' cambiato (evitare doppioni, vedi evaluate_player_offer).
    cur.execute('''
        CREATE TABLE IF NOT EXISTS margin_alerts (
            player_slug TEXT NOT NULL,
            season_type TEXT NOT NULL,
            last_margin_alert_price REAL,
            PRIMARY KEY (player_slug, season_type)
        )
    ''')
    # FIX 16/07 (caso Sengezer): tokenPrices (vedi get_recent_sale_history) restituisce
    # transazioni vere ma senza modo di distinguere Acquisto istantaneo/Asta da Scambia/Offerta
    # diretta (11 nomi di campo candidati provati, nessuno esiste su TokenPrice) -- ne' di
    # filtrare per bucket in_season/classic esatto. Costruiamo quindi il nostro storico,
    # catturando in tempo reale gli eventi status='accepted' dalla stessa subscription WS gia'
    # in ascolto per gli annunci 'opened' (vedi record_accepted_sale in handle_offer_update):
    # ogni riga qui e' garantita una vendita di mercato pubblico vera (stessi filtri gia'
    # validati altrove: solo SingleSaleOffer, niente scambi carta-per-carta). Parte da zero da
    # questo deploy in poi, non recupera lo storico precedente.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sale_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_slug TEXT NOT NULL,
            season_type TEXT NOT NULL,
            season_name TEXT,
            price_eur REAL NOT NULL,
            card_slug TEXT,
            occurred_at TEXT NOT NULL
        )
    ''')
    cur.execute('''
        CREATE INDEX IF NOT EXISTS idx_sale_history_lookup
        ON sale_history (player_slug, season_type, occurred_at)
    ''')
    conn.commit()
    conn.close()


# FIX 16/07 (v22, richiesta esplicita): contatore in memoria per un riepilogo a fine
# esecuzione (vedi log_decision_summary sotto). Volutamente NON include il ramo silenzioso
# "nessuna variazione" (true_min_price >= floor) -- quel ramo resta senza log_decision per
# esplicita richiesta dell'utente (troppo rumoroso, capita quasi ad ogni evento), quindi non
# comparira' nel riepilogo. Copre solo le categorie gia' tracciate in decisions_log.
_decision_counts = {}

# Etichette leggibili in italiano per il riepilogo, nell'ordine in cui vogliamo mostrarle.
_DECISION_LABELS = [
    ("init", "Inizializzati"),
    ("stale_realign", "Riferimento riallineato (stantio)"),
    ("skip_margin_too_close", "Margine insufficiente"),
    ("skip_cross_bucket_dead", "Bucket morto/residuale"),
    ("skip_in_season_substitute_cheaper", "Sostituto in season piu' economico"),
    ("skip_recent_sales_gate", "Bloccato (vendite recenti gia' piu' economiche)"),
    ("skip_thin_market_gate", "Bloccato (mercato troppo sottile, poche transazioni)"),
    ("skip_dubbio_unconfirmed", "Dubbio non confermato"),
    ("notify", "Notificati (calo diretto)"),
    ("notify_after_recheck", "Notificati (dopo doppio controllo)"),
    ("notify_margin_opportunity", "Notificati (opportunita' di margine)"),
    ("update_small_variation", "Piccola variazione"),
    ("instant_alert_unverified", "Notifiche veloci (non verificate)"),
]


def log_decision(player_slug, player_name, season_type, season_name, decision,
                  floor_price=None, true_min_price=None, drop_percent=None,
                  second_min_price=None, margin_percent=None, reasons=None):
    """Registra una riga per ogni decisione presa (notificato o scartato, e perche').
    Query utili in futuro, es.: `SELECT decision, COUNT(*) FROM decisions_log GROUP BY decision`
    per vedere quanto viene notificato contro quanto viene scartato e con quale motivo."""
    _decision_counts[decision] = _decision_counts.get(decision, 0) + 1
    conn = sqlite3.connect('tracker.db')
    conn.execute(
        '''INSERT INTO decisions_log
           (ts, player_slug, player_name, season_type, season_name, decision,
            floor_price, true_min_price, drop_percent, second_min_price, margin_percent, reasons)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (datetime.datetime.now().isoformat(), player_slug, player_name, season_type, season_name,
         decision, floor_price, true_min_price, drop_percent, second_min_price, margin_percent,
         ', '.join(reasons) if reasons else None)
    )
    conn.commit()
    conn.close()


def log_decision_summary():
    """Riepilogo a fine esecuzione di quante volte e' scattata ogni categoria di decisione,
    per farsi un'idea rapida senza scorrere tutto il log. Il ramo silenzioso "nessuna
    variazione" resta escluso di proposito (vedi nota su _decision_counts)."""
    if not _decision_counts:
        log("[riepilogo] nessuna decisione registrata in questa esecuzione.")
        return
    parti = []
    for code, label in _DECISION_LABELS:
        count = _decision_counts.get(code, 0)
        if count:
            parti.append(f"{label} {count}")
    # Eventuali categorie non previste in _DECISION_LABELS (nel caso ne aggiungessimo di
    # nuove in futuro senza aggiornare questa lista) -- le mostriamo comunque col nome grezzo.
    for code, count in _decision_counts.items():
        if code not in dict(_DECISION_LABELS):
            parti.append(f"{code} {count}")
    log(f"[riepilogo] {', '.join(parti)}")


def get_floor(player_slug, season_name):
    """Restituisce (prezzo, data_ultimo_aggiornamento) oppure None se non c'e' ancora un riferimento."""
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "SELECT floor_price_eur, updated_at FROM floors WHERE player_slug=? AND season_name=?",
        (player_slug, season_name)
    )
    row = cur.fetchone()
    conn.close()
    return row if row else None


def set_floor(player_slug, season_name, price):
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO floors (player_slug, season_name, floor_price_eur, updated_at) VALUES (?, ?, ?, ?)",
        (player_slug, season_name, price, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_last_margin_alert_price(player_slug, season_type):
    """Restituisce l'ultimo prezzo minimo per cui abbiamo gia' segnalato un'opportunita' di
    margine ampio per questo giocatore/bucket, o None se non l'abbiamo mai fatto."""
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "SELECT last_margin_alert_price FROM margin_alerts WHERE player_slug=? AND season_type=?",
        (player_slug, season_type)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_last_margin_alert_price(player_slug, season_type, price):
    conn = sqlite3.connect('tracker.db')
    conn.execute(
        "INSERT OR REPLACE INTO margin_alerts (player_slug, season_type, last_margin_alert_price) VALUES (?, ?, ?)",
        (player_slug, season_type, price)
    )
    conn.commit()
    conn.close()


def queue_pending_recheck(player_slug, player_name, season_type, season_name, price_eur, card_slug):
    """Accoda un caso scartato per margine troppo vicino, da riverificare piu' avanti (vedi
    nota su MARKET_VISIBILITY_DELAY_SECONDS). INSERT OR REPLACE: se lo stesso player_slug+
    season_type e' gia' in coda, aggiorna semplicemente l'orario e i dati piu' recenti invece
    di accumulare righe duplicate."""
    conn = sqlite3.connect('tracker.db')
    conn.execute(
        "INSERT OR REPLACE INTO pending_recheck "
        "(player_slug, season_type, player_name, season_name, price_eur, card_slug, queued_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (player_slug, season_type, player_name, season_name, price_eur, card_slug,
         datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def pop_due_pending_rechecks():
    """Estrae (e rimuove subito dalla coda) tutti i casi la cui finestra di invisibilita' e'
    sicuramente passata (piu' vecchi di MARKET_VISIBILITY_DELAY_SECONDS). I casi troppo
    vecchi (oltre PENDING_RECHECK_MAX_AGE_SECONDS) vengono scartati senza essere riverificati:
    non sono piu' rilevanti a quel punto. Rimuove subito dalla tabella per evitare di
    riprocessare due volte lo stesso caso se l'esecuzione successiva parte prima che questa
    abbia finito."""
    conn = sqlite3.connect('tracker.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM pending_recheck").fetchall()
    due, expired = [], []
    now = datetime.datetime.now()
    to_delete = []
    for row in rows:
        try:
            queued_at = datetime.datetime.fromisoformat(row["queued_at"])
            age_seconds = (now - queued_at).total_seconds()
        except (TypeError, ValueError):
            age_seconds = None
        if age_seconds is None or age_seconds >= MARKET_VISIBILITY_DELAY_SECONDS:
            to_delete.append((row["player_slug"], row["season_type"]))
            if age_seconds is not None and age_seconds > PENDING_RECHECK_MAX_AGE_SECONDS:
                expired.append(row)
            else:
                due.append(row)
    for player_slug, season_type in to_delete:
        conn.execute(
            "DELETE FROM pending_recheck WHERE player_slug=? AND season_type=?",
            (player_slug, season_type)
        )
    conn.commit()
    conn.close()
    return due, expired


# --- Notifiche ---
def send_email(subject, body):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = NOTIFY_EMAIL
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
    except Exception as e:
        log(f"Errore invio email: {e}")


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


# --- Prezzo in EUR ---
def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


# FIX 17/07 (bug valuta USD/GBP, caso Jhegson Sebastian Mendez -- richiesta esplicita
# dell'utente "insisti, chissa' quanti falsi allarmi"): scoperto via DevTools (payload reale di
# CardsQuery, la query usata dalla pagina mercato) che eur_price_from_amounts leggeva SOLO
# eurCents e wei, ignorando silenziosamente usdCents/gbpCents -- un venditore che prezza in
# dollari o sterline invece che euro diventava per noi "prezzo assente" (None), sparendo del
# tutto dai comparabili/margini anche se l'annuncio era vivo e vero (verificato: due annunci di
# Mendez, 0.59EUR e 1.92EUR, erano ENTRAMBI in realta' USD-only -- usdCents 67 e 220, eurCents
# null -- e per questo invisibili sia al tracker principale che al modello ZenLock). Non e' un
# limite dei dati Sorare come si pensava all'inizio (fenomeno "annunci fantasma" gia' documentato
# altrove) -- e' un bug nostro di lettura, fixabile. Aggiunti usdCents/gbpCents a TUTTE le query
# che leggono MonetaryAmount (vedi "amounts { eurCents wei usdCents gbpCents }"); qui
# aggiungiamo la conversione, con lo stesso pattern gia' collaudato di get_eth_rate (fetch con
# timeout breve, fallback fisso se l'API cade -- i cambi fiat si muovono pochissimo giorno per
# giorno, un fallback statico e' un rischio molto piu' basso che per l'ETH). Cache in-memory
# semplice (un dict globale) perche' il tasso non cambia nell'arco di una singola esecuzione e
# non ha senso richiederlo piu' volte.
_FIAT_RATE_CACHE = {}


def get_usd_eur_rate():
    if 'usd' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['usd']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 0.92  # fallback approssimativo (cambio USD/EUR storicamente stabile intorno a li')
    _FIAT_RATE_CACHE['usd'] = rate
    return rate


def get_gbp_eur_rate():
    if 'gbp' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['gbp']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=GBP&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 1.17  # fallback approssimativo (cambio GBP/EUR storicamente stabile intorno a li')
    _FIAT_RATE_CACHE['gbp'] = rate
    return rate


# FIX 17/07 (richiesta esplicita dell'utente, dopo la scoperta del bug valute): contatore
# leggero per capire QUANTO materiale reale stavamo perdendo prima del fix usdCents/gbpCents --
# finora solo aneddotico (caso Mendez: 2 annunci su 4-5). Un dict globale incrementato dentro
# eur_price_from_amounts copre automaticamente OGNI punto di chiamata (listener live, bucket
# prices, storico vendite, analisi trade) senza dover passare 'stats' attraverso ogni funzione
# che lo chiama -- costo trascurabile (un incremento di dict per chiamata, nessuna I/O).
_CURRENCY_BRANCH_STATS = {'eurCents': 0, 'wei': 0, 'usdCents': 0, 'gbpCents': 0, 'none': 0}


def get_currency_branch_stats():
    return dict(_CURRENCY_BRANCH_STATS)


def reset_currency_branch_stats():
    for k in _CURRENCY_BRANCH_STATS:
        _CURRENCY_BRANCH_STATS[k] = 0


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        _CURRENCY_BRANCH_STATS['none'] += 1
        return None
    if amounts.get('eurCents') is not None:
        _CURRENCY_BRANCH_STATS['eurCents'] += 1
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            price = float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['wei'] += 1
        return price
    if amounts.get('usdCents') is not None:
        try:
            price = amounts['usdCents'] / 100 * get_usd_eur_rate()
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['usdCents'] += 1
        return price
    if amounts.get('gbpCents') is not None:
        try:
            price = amounts['gbpCents'] / 100 * get_gbp_eur_rate()
        except (TypeError, ValueError):
            _CURRENCY_BRANCH_STATS['none'] += 1
            return None
        _CURRENCY_BRANCH_STATS['gbpCents'] += 1
        return price
    _CURRENCY_BRANCH_STATS['none'] += 1
    return None


# --- Verifica live del prezzo minimo REALE attualmente in vendita per un giocatore ---
# A differenza del semplice ascolto della subscription (che vede solo i CAMBIAMENTI di stato),
# questa e' un'istantanea del mercato reale in questo momento: risolve il problema per cui un
# annuncio piu' economico, aperto prima che il bot iniziasse ad ascoltare, restava invisibile.
def get_bucket_prices(player_slug, eth_rate):
    """Scorre TUTTI gli annunci live di un giocatore UNA SOLA VOLTA e li divide subito nei due
    bucket in_season/classic, invece di interrogare Sorare una volta per bucket. Restituisce
    {'in_season': (lista_prezzi_ordinata, dati_incompleti), 'classic': (..., ...)} dove
    lista_prezzi_ordinata e' una lista di (prezzo, slug_carta) crescente. Usata sia per il
    prezzo minimo del bucket richiesto (get_live_min_offer) sia per il controllo incrociato
    tra bucket (cross_bucket_looks_dead) -- nello stesso fetch, senza query aggiuntive.

    LIMITE NOTO (17/07, caso Joao Cancelo): le carte "Early Access" (badge speciale su
    stampe Limited appena estratte, slug identico alle Limited normali -- verificato sul
    caso Joel Mvuka, "joel-mvuka-2025-limited-511") NON compaiono MAI tra i nodi restituiti
    da fetch_all_live_offers/liveSingleSaleOffers, anche quando l'annuncio e' live da ore
    (non e' quindi la solita finestra di invisibilita' dei 2 minuti). Non e' un filtro
    lato nostro (rarityTyped/sport/slug sono standard, dovrebbero passare) -- sembra che
    Sorare le gestisca con un circuito di vendita/rivelazione separato non ancora scoperto.
    Effetto pratico: un annuncio Early Access piu' economico del "secondo prezzo" calcolato
    puo' restare invisibile, gonfiando il margine e facendo scattare un alert che dal vivo
    e' meno margine di quanto sembri (caso Cancelo: secondo prezzo vero 2.97EUR, non
    3.33EUR). Accettato come limite noto per ora (fenomeno di nicchia, poche carte
    Early Access sul mercato in un dato momento) -- da rivedere se capitano altri casi."""
    nodes = fetch_all_live_offers(player_slug)
    raw = {'in_season': [], 'classic': []}
    # NOTA (v23): questo flag ora non viene piu' impostato a True da nessuna parte (vedi FIX
    # v23 piu' sotto, caso Scherpen) -- resta qui per non toccare la forma del valore restituito
    # (usata da evaluate_player_offer per "dubbio") e per poterlo eventualmente reintrodurre in
    # forma piu' mirata in futuro, se emergesse un vero caso di dato illeggibile diverso dagli
    # annunci "Fai un'offerta" senza prezzo fisso.
    incomplete_flags = {'in_season': False, 'classic': False}
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        # FIX 16/07 (v15, caso Nicolo Barella): gli annunci di scambio carta-per-carta
        # (receiverSide.anyCards non vuoto) non hanno mai un prezzo in denaro -- prima
        # venivano contati come "annuncio compatibile ma prezzo illeggibile", marcando il
        # bucket come "dati incompleti" per SEMPRE se quel giocatore ha anche un solo scambio
        # attivo (comune sui giocatori popolari). Un dato "incompleto" strutturale, non
        # transitorio, non si conferma mai al secondo controllo (double_check_suspect_drop) --
        # cosi' un calo reale (Barella: 30.00EUR -> 10.50EUR, 65%, confermato dal mercato vero)
        # veniva scartato per sempre. Stesso filtro gia' usato per gli eventi WS
        # (handle_offer_update): uno scambio non e' una vendita in denaro, va escluso del tutto,
        # non trattato come "dato mancante".
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited':
                continue
            if c.get('sport') != 'FOOTBALL':
                continue
            match = c
            break
        if not match:
            continue
        node_season = (match.get('sportSeason') or {}).get('name', 'unknown')
        node_season_type = season_type_for_card(match, node_season)
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            # FIX 16/07 (v23, caso Kjell Scherpen -- diagnosticato su un log reale): il fix sugli
            # scambi carta-per-carta non copriva tutti i casi di "dati incompleti". Il diagnostico
            # temporaneo ha mostrato che questi annunci (status='opened', non uno scambio, ma
            # eurCents E wei ENTRAMBI assenti) capitano su QUASI OGNI giocatore, non sono affatto
            # rari -- la spiegazione piu' probabile e' che siano annunci "Fai un'offerta" (nessun
            # prezzo fisso "Compra Subito" impostato dal venditore), non un dato sporco o
            # illeggibile: semplicemente non esiste un numero da darci, perche' il venditore non
            # ha fissato un prezzo. Non nascondono un vero minimo piu' economico non ancora letto
            # -- vanno esclusi dal conteggio come gli scambi, non trattati come motivo di dubbio
            # su tutto il bucket (prima questo faceva scattare "dati incompleti" quasi sempre,
            # bloccando affari reali gia' confermati a mano, es. Scherpen a 7.00EUR).
            continue
        raw[node_season_type].append((price, match.get('slug')))
    result = {}
    for key in ('in_season', 'classic'):
        raw[key].sort(key=lambda p: p[0])
        result[key] = (raw[key], incomplete_flags[key])
    return result


def get_live_min_offer(player_slug, season_type, eth_rate):
    """Restituisce (prezzo_minimo, slug_carta_minima, secondo_prezzo_minimo, dati_incompleti)
    oppure None. dati_incompleti e' True se esistono annunci aperti e compatibili (stessa
    rarita'/sport/categoria in_season-o-classic) di cui pero' Sorare non restituisce il prezzo
    (eurCents e wei entrambi nulli, capitato in pratica: vedi caso Arnau Tenas) -- in quel caso
    il vero secondo prezzo potrebbe essere nascosto li' dentro e non ci si puo' fidare del margine.

    NOTA: il confronto usa il bucket 'in_season'/'classic', NON la stagione esatta. Verificato
    con dati reali (schermate del mercato di Roman Bürki) che le stampe Classic di ANNI diversi
    hanno prezzi tra loro simili (es. tutte tra 2.70 e 5.50EUR indipendentemente dall'anno di
    stampa) -- sono considerate equivalenti dai manager, cambia solo se una carta e' In Season o
    Classic. Il vero bug (caso Bürki: 2.95EUR rilevato contro 12.35EUR reali) non era la
    mescolanza tra annate Classic, ma il fatto che la sua carta In Season vera (stagione MLS
    "2026") veniva scambiata per "classic" perche' il confronto guardava solo il formato europeo
    "2025-26" -- vedi CURRENT_SEASON_LABELS."""
    try:
        buckets = get_bucket_prices(player_slug, eth_rate)
        prices, incomplete = buckets.get(season_type, ([], False))
        if not prices:
            return None
        best_price, best_card_slug = prices[0]
        second_min_price = prices[1][0] if len(prices) > 1 else None
        return best_price, best_card_slug, second_min_price, incomplete
    except Exception as e:
        log(f"[verifica live] eccezione per {player_slug}: {e}")
        return None


def cross_bucket_looks_dead(buckets, season_type, true_min_price):
    """Rete di sicurezza per il caso "stagione finita ma l'etichetta non lo sa" (vedi Aral
    Şimşir nel commento sulle costanti SIBLING_*). Se il bucket rilevato (season_type) ha
    pochissimi annunci (<= THIN_BUCKET_MAX_LISTINGS) mentre il bucket gemello ne ha molti di
    piu' (almeno SIBLING_MIN_LISTINGS, e almeno SIBLING_MIN_LISTINGS_MULTIPLIER volte tanti) a
    un prezzo sensibilmente piu' basso (almeno SIBLING_CHEAPER_THRESHOLD), e' segno che il
    bucket rilevato e' morto/residuale e il vero mercato si e' spostato altrove: in quel caso
    il calo% calcolato sul bucket rilevato e' inaffidabile. Richiede ENTRAMBE le condizioni
    (volume E prezzo) per non penalizzare giocatori con un mercato in season genuinamente
    sottile ma reale."""
    sibling_type = 'classic' if season_type == 'in_season' else 'in_season'
    own_prices, _ = buckets.get(season_type, ([], False))
    sibling_prices, _ = buckets.get(sibling_type, ([], False))
    own_count = len(own_prices)
    sibling_count = len(sibling_prices)
    if own_count > THIN_BUCKET_MAX_LISTINGS:
        return False
    if sibling_count < SIBLING_MIN_LISTINGS:
        return False
    if sibling_count < own_count * SIBLING_MIN_LISTINGS_MULTIPLIER:
        return False
    if not sibling_prices or not true_min_price or true_min_price <= 0:
        return False
    sibling_min_price = sibling_prices[0][0]
    if sibling_min_price <= 0:
        return False
    # Se il prezzo rilevato e' significativamente piu' basso del mercato gemello, resta un
    # affare raro genuino -- non lo blocchiamo. Lo blocchiamo solo se e' sostanzialmente alla
    # pari o piu' caro del gemello (entro UNIQUE_DEAL_TOLERANCE).
    not_meaningfully_cheaper = true_min_price >= sibling_min_price * (1 - UNIQUE_DEAL_TOLERANCE)
    return not_meaningfully_cheaper


def double_check_suspect_drop(player_slug, season_type, first_price, eth_rate):
    """Secondo livello di verifica per un calo segnalato come "dubbio" (sospetto >50% o dati
    incompleti), PRIMA di scartarlo definitivamente. Ripete la stessa query live usata per il
    primo controllo, dopo una breve pausa: se il prezzo minimo e' ancora li' (entro
    RECHECK_TOLERANCE) e la seconda lettura non e' a sua volta incompleta, e' molto piu'
    probabile che sia un affare reale e stabile piuttosto che un dato Sorare sporco/vecchio
    (che tipicamente sparisce o cambia in modo vistoso alla richiesta successiva).
    Ritorna True se confermato (va notificato), False se non confermato (resta scartato)."""
    time.sleep(RECHECK_DELAY_SECONDS)
    second_result = get_live_min_offer(player_slug, season_type, eth_rate)
    if second_result is None:
        return False
    second_price, _second_slug, _second_second_min, second_incomplete = second_result
    if second_incomplete:
        return False
    if not first_price or first_price <= 0:
        return False
    diff_percent = abs(second_price - first_price) / first_price
    return diff_percent <= RECHECK_TOLERANCE


DIAGNOSTIC_MAX_ROWS = 8  # FIX 17/07: vedi nota sotto, il dump completo era pura verbosita'


def log_raw_offers_diagnostic(player_slug, eth_rate):
    """FIX 16/07 (caso Nico O'Reilly): quando scatta un ALERT, salviamo anche il dump grezzo di
    TUTTI gli annunci live per quel giocatore (status, prezzo, slug, rarita', sport, stagione),
    cosi' se in futuro il prezzo minimo notificato risultasse sbagliato (come successo con la
    carta da 4.70EUR di NFT Sportsclub, esclusa senza che nei log restasse traccia del motivo --
    ne' un'eccezione ne' un flag "dati incompleti") avremo l'evidenza per capire quale filtro
    l'ha esclusa, invece di doverlo dedurre ore dopo da uno screenshot. Chiamata solo sugli
    ALERT (evento raro), quindi il costo di un'interrogazione extra e' trascurabile.

    FIX 17/07 (richiesta esplicita, verificato su log reali): il dump completo arrivava a
    60+ righe per un singolo alert (es. Rodrigo De Paul) senza aggiungere informazione utile --
    cio' che serve per verificare true_min/second_min e' vedere i prezzi piu' bassi, non l'intera
    lista di annunci. Ridotto ai DIAGNOSTIC_MAX_ROWS piu' economici (ordinati per prezzo, quelli
    senza prezzo/None in fondo), col conteggio totale comunque loggato per contesto."""
    try:
        nodes = fetch_all_live_offers(player_slug)
    except Exception as e:
        log(f"[diagnostica alert] impossibile scaricare il dump grezzo per {player_slug}: {e}")
        return
    log(f"[diagnostica alert] {player_slug}: {len(nodes)} annunci live grezzi trovati")

    rows = []
    for node in nodes:
        status = node.get('status')
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        if not cards:
            rows.append((price, f"status={status} prezzo={price} (nessuna carta compatibile sul lato venditore)"))
            continue
        for c in cards:
            rows.append((price, f"status={status} prezzo={price} slug={c.get('slug')} "
                                 f"rarita'={c.get('rarityTyped')} sport={c.get('sport')} "
                                 f"stagione={(c.get('sportSeason') or {}).get('name')} "
                                 f"inSeasonEligible={c.get('inSeasonEligible')}"))

    rows.sort(key=lambda r: (r[0] is None, r[0]))
    for _, line in rows[:DIAGNOSTIC_MAX_ROWS]:
        log(f"[diagnostica alert]   {line}")
    if len(rows) > DIAGNOSTIC_MAX_ROWS:
        log(f"[diagnostica alert]   ... altri {len(rows) - DIAGNOSTIC_MAX_ROWS} annunci omessi "
            f"(mostrati solo i {DIAGNOSTIC_MAX_ROWS} piu' economici)")


# FIX 16/07 (caso Sengezer, richiesta esplicita): vedi nota su sale_history in init_db per il
# perche'. Riusa ESATTAMENTE gli stessi filtri gia' validati per gli annunci 'opened' piu' sotto
# (niente scambi carta-per-carta, solo limited/FOOTBALL) cosi' ogni riga salvata e' garantita
# una vendita di mercato pubblico vera, non una trattativa privata o un valore di scambio
# stimato -- a differenza di tokenPrices, di cui non sappiamo distinguere il tipo.
def record_accepted_sale(offer, eth_rate):
    sender_side = offer.get('senderSide') or {}
    receiver_side = offer.get('receiverSide') or {}
    if receiver_side.get('anyCards'):
        return  # scambio carta-per-carta, non una vendita in denaro
    price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
    if price_eur is None:
        return
    for card in (sender_side.get('anyCards') or []):
        if card.get('rarityTyped') != 'limited':
            continue
        if card.get('sport') != 'FOOTBALL':
            continue
        player = card.get('anyPlayer') or {}
        player_slug = player.get('slug')
        if not player_slug:
            continue
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        season_type = season_type_for_card(card, season_name)
        card_slug = card.get('slug')
        conn = sqlite3.connect('tracker.db')
        conn.execute(
            "INSERT INTO sale_history (player_slug, season_type, season_name, price_eur, "
            "card_slug, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
            (player_slug, season_type, season_name, price_eur, card_slug,
             datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        log(f"[storico vendite reali] registrata vendita conclusa: "
            f"{player.get('displayName', player_slug)} ({season_type}, {season_name}) "
            f"a {price_eur:.2f}EUR")


def get_own_recent_sales(player_slug, season_type, last_n=5):
    """Ultime vendite REALMENTE concluse (accepted, no scambi/offerte private) per questo
    giocatore E bucket in_season/classic esatto -- a differenza di get_recent_sale_history
    (tokenPrices), qui ogni riga e' garantita un acquisto istantaneo/asta vero sul mercato
    pubblico, e il bucket e' quello giusto (tokenPrices non lo permetteva). Il rovescio: i dati
    esistono solo da quando sale_history e' stata attivata, quindi puo' essere vuoto o scarso
    per giocatori poco scambiati o appena dopo il deploy."""
    conn = sqlite3.connect('tracker.db')
    cur = conn.cursor()
    cur.execute(
        "SELECT occurred_at, price_eur FROM sale_history WHERE player_slug=? AND season_type=? "
        "ORDER BY occurred_at DESC LIMIT ?",
        (player_slug, season_type, last_n)
    )
    rows = cur.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows] or None


# --- Elaborazione di un'offerta ricevuta dalla subscription ---
def handle_offer_update(offer, eth_rate, stats):
    if not offer:
        return

    # Vogliamo solo le vendite pubbliche "compra subito" (SingleSaleOffer), non le proposte
    # private mandate al proprietario di una carta specifica (DirectOffer) -- queste ultime
    # non compaiono mai sul mercato pubblico, quindi non ci interessano.
    offer_id = offer.get('id') or ''
    if not offer_id.startswith('SingleSaleOffer:'):
        return

    # tokenOfferWasUpdated scatta per QUALSIASI aggiornamento dell'offerta (creazione,
    # modifica prezzo, cancellazione, scadenza, vendita conclusa). Vogliamo intercettare
    # il momento in cui una carta VIENE MESSA IN VENDITA a un prezzo basso (per poterla
    # comprare noi), quindi il segnale giusto e' 'opened' (annuncio appena creato/attivo
    # a quel prezzo) -- non 'accepted' (vendita gia' conclusa tra altri manager, carta
    # non piu' disponibile) ne' 'cancelled' (annuncio ritirato, prezzo non piu' valido).
    offer_status = offer.get('status')
    stats.setdefault("status_counts", {})
    stats["status_counts"][offer_status] = stats["status_counts"].get(offer_status, 0) + 1

    # Sorare a volte manda lo stesso evento due (o piu') volte sullo stesso WebSocket
    # (verificato empiricamente). Se abbiamo gia' visto esattamente questo stesso
    # (offer_id, status) in questa esecuzione, e' un doppione: lo ignoriamo.
    stats.setdefault("seen_offer_status", set())
    dedup_key = (offer_id, offer_status)
    if dedup_key in stats["seen_offer_status"]:
        return
    stats["seen_offer_status"].add(dedup_key)

    # FIX 16/07 (v2, richiesta esplicita dell'utente): rimossa la cattura indiscriminata di
    # OGNI 'accepted' per OGNI giocatore (record_accepted_sale, vedi sale_history in init_db) --
    # scriveva su sqlite ad ogni singola vendita conclusa nel mercato intero (6-9 per esecuzione
    # nei log), un costo bloccante nel loop eventi WS per giocatori quasi sempre irrilevanti (non
    # e' mai quello su cui stiamo per notificare). Lo storico vendite ora si guarda SOLO al
    # momento di notificare, e solo per quel giocatore specifico, via tokenPrices
    # (get_recent_sale_history) -- vedi find_cheaper_recent_sale in evaluate_player_offer.
    # record_accepted_sale/get_own_recent_sales restano definite piu' sotto ma non sono piu'
    # chiamate, nel caso servano in futuro per un uso mirato invece che globale.
    if offer_status != 'opened':
        return

    sender_side = offer.get('senderSide') or {}
    receiver_side = offer.get('receiverSide') or {}

    # Vogliamo solo offerte "vendita diretta a soldi":
    # dal lato di chi vende ci sono le carte, dal lato ricevente NON ci sono carte
    # (altrimenti e' uno scambio carta-per-carta, che non ci interessa qui).
    if receiver_side.get('anyCards'):
        return

    price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
    if price_eur is None:
        return

    # NOTA STORICA: qui c'era un diagnostico temporaneo (16/07, caso Kim Dae-Won) che ipotizzava
    # eurCents assente + wei presente come segnale di annuncio "solo ETH" (non acquistabile in
    # cash/carta). Rimosso dopo aver controllato un log reale di ~2200 casi: il pattern "solo un
    # campo dei due presente" e' comunissimo (~13-16% di TUTTI gli annunci, non un'eccezione
    # rara), quindi non isola davvero gli annunci eth-only -- e' solo un modo normale in cui
    # Sorare a volte restituisce il prezzo. Serve un altro modo per isolare il caso Kim Dae-Won,
    # ancora in backlog.

    # FIX 17/07 (sessione 3, stesso bug gia' trovato e risolto in fetch_user_trades per le
    # analisi retroattive -- richiesta esplicita dell'utente "sistema questo bug" dopo la
    # scoperta): un'offerta puo' impacchettare PIU' carte per un unico prezzo aggregato
    # (bundle). Il loop sotto valutava ogni carta del lotto con l'intero price_eur come se
    # fosse il prezzo di QUELLA singola carta -- gonfiando falsamente il margine (o
    # nascondendo affari veri, a seconda del caso) su qualsiasi annuncio multi-carta. Non
    # esiste un modo affidabile di scomporre il prezzo aggregato in un prezzo per-carta
    # (potrebbero avere valore molto diverso tra loro), quindi scartiamo l'intero annuncio
    # invece di leggerlo sbagliato -- stessa scelta gia' fatta per l'analisi storica.
    sender_cards = sender_side.get('anyCards') or []
    if len(sender_cards) > 1:
        return

    for card in sender_cards:
        if card.get('rarityTyped') != 'limited':
            continue
        if card.get('sport') != 'FOOTBALL':
            continue

        player = card.get('anyPlayer') or {}
        player_slug = player.get('slug')
        player_name = player.get('displayName', player_slug)
        season_name = (card.get('sportSeason') or {}).get('name', 'unknown')
        card_slug = card.get('slug')
        if not player_slug:
            continue

        if price_eur < MIN_PRICE_EUR:
            continue  # scarto veloce sul prezzo dell'evento, solo per non fare la verifica live inutilmente:
                      # il controllo vero (sul prezzo REALE verificato) e' piu' sotto, dopo get_live_min_offer

        season_type = season_type_for_card(card, season_name)

        stats["processed"] += 1

        # FIX 16/07 (v11, richiesta esplicita): notifica "veloce" immediata, PRIMA della verifica
        # live completa -- vedi docstring di send_instant_alert per il motivo (l'evento WS arriva
        # prima che l'annuncio sia visibile pubblicamente su Sorare, quindi da' un vantaggio di
        # tempo reale). La valutazione completa (sotto) segue comunque, invariata.
        instant_alert_sent = send_instant_alert(player_slug, player_name, season_type, season_name,
                                                 price_eur, card_slug)

        evaluate_player_offer(player_slug, player_name, season_type, season_name, price_eur,
                               card_slug, eth_rate, stats,
                               instant_alert_just_sent=instant_alert_sent)


def send_instant_alert(player_slug, player_name, season_type, season_name, price_eur, card_slug):
    """FIX 16/07 (v11, richiesta esplicita): notifica IMMEDIATA, non verificata, basata solo sul
    confronto col floor storico gia' salvato in database -- nessuna query live, quindi zero
    attesa. L'evento WebSocket arriva PRIMA che l'annuncio sia visibile pubblicamente sul mercato
    Sorare (~2 minuti di anticipo, vedi MARKET_VISIBILITY_DELAY_SECONDS), quindi questa notifica
    puo' dare un vantaggio di velocita' reale su altri manager. In cambio pero' salta TUTTE le
    protezioni della valutazione completa (margine sul secondo prezzo attuale, calo sospetto,
    dati incompleti, bucket morto/residuale): e' un segnale grezzo e non verificato, va sempre
    controllato a mano prima di comprare. evaluate_player_offer (la valutazione completa) segue
    comunque subito dopo con l'alert "ufficiale" se conferma tutto -- questa non la sostituisce,
    la anticipa."""
    floor_row = get_floor(player_slug, season_type)
    if floor_row is None:
        return False
    floor, floor_updated_at = floor_row
    if floor <= 0 or price_eur >= floor:
        return False

    # FIX 16/07 (v13, casi Miazga/Thorstvedt vs Cakir): vedi nota su INSTANT_ALERT_MAX_FLOOR_AGE_HOURS
    # -- un floor non aggiornato di recente non e' abbastanza affidabile per un alert non
    # verificato, meglio saltarlo e aspettare l'alert ufficiale (che fa comunque una verifica live).
    if not floor_updated_at:
        return False
    try:
        floor_age_hours = (
            datetime.datetime.now() - datetime.datetime.fromisoformat(floor_updated_at)
        ).total_seconds() / 3600
    except ValueError:
        return False
    if floor_age_hours > INSTANT_ALERT_MAX_FLOOR_AGE_HOURS:
        return False

    drop_percent = (floor - price_eur) / floor
    if drop_percent < INSTANT_ALERT_DROP_THRESHOLD:
        return False
    log(f"VELOCE (non verificato) {player_name} ({season_type}, {season_name}) sceso: "
        f"{floor:.2f}EUR -> {price_eur:.2f}EUR ({drop_percent:.1%}) -- notifica immediata, "
        f"prima della verifica live completa")
    log_decision(player_slug, player_name, season_type, season_name, "instant_alert_unverified",
                 floor_price=floor, true_min_price=price_eur, drop_percent=drop_percent)
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    link = f"{base_link}?card={card_slug}" if card_slug else base_link
    msg_text = (
        f"⚡ <b>Occasione VELOCE (non verificata)!</b>\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: {'In Season' if season_type == 'in_season' else 'Classic (stagione passata)'}\n"
        f"Stagione carta: {season_name}\n"
        f"Calo: {drop_percent:.1%}\n"
        f"Prezzo: {price_eur:.2f}EUR\n\n"
        f"⚠️ Non ancora verificato (nessun controllo su margine/dati sospetti) -- "
        f"controlla a mano prima di comprare, arriva anche l'alert ufficiale a breve.\n\n"
        f"👉 <b><a href='{link}'>APRI SU SORARE</a></b> 👈"
    )
    send_telegram_msg(msg_text)
    return True


# FIX 16/07 (casi Yuma Suzuki/Samuel Kotto): il bot notificava affari basandosi solo sugli
# annunci ATTIVI (ask price), mai sulle vendite REALMENTE concluse -- confermato che il prezzo
# "verificato" come affare era in realta' piu' caro di quanto la gente paghi davvero di recente
# (Kotto: 5.00EUR notificato contro 1.26-1.60EUR di vendite reali nelle ultime settimane, dato
# via discover_sales_history_field: il campo giusto e' tokenPrices(playerSlug, rarity: limited)
# { date amounts { eurCents wei usdCents gbpCents } }, non introspection-abile, trovato per tentativi). Restituisce
# le ultime vendite reali concluse (data, prezzo EUR), piu' recenti prima, o None se la query
# fallisce.
#
# FIX 16/07 (v2, richiesta esplicita dell'utente -- ora e' un filtro, vedi
# recent_sale_gate_blocks): tokenPrices non espone stagione/idoneita' per singola vendita
# (provato: season/sportSeason/rarity/playerSlug/cardSlug tutti assenti su TokenPrice), quindi
# non possiamo garantire che le vendite restituite siano della stessa categoria in_season/classic
# della carta valutata -- potrebbero mescolare stampe diverse con prezzi molto diversi (vedi caso
# Luis Diaz). Non distingue nemmeno il TIPO di transazione (11 nomi di campo provati per un
# tipo/kind, nessuno esiste su TokenPrice -- caso Sengezer): puo' includere vendita/scambio/asta/
# offerta diretta senza modo di escludere quest'ultima. L'utente ha comunque scelto esplicitamente
# di considerare valide anche vendita/scambio/asta come segnale ("se altre 3 persone prima di me
# l'hanno gia' avuto a un prezzo piu' basso, non e' un affare, anche se sembra un calo") -- quindi
# usiamo questi dati cosi' come sono. C'e' un ritardo strutturale da tenere a mente: una vendita
# compare qui solo dopo che qualcuno ha DAVVERO comprato/scambiato, quindi in un calo genuino e
# recentissimo (es. infortunio, caso Muric) lo storico puo' restare ancorato al prezzo vecchio
# piu' alto per un po' -- ma questo giocherebbe contro il blocco (falso negativo, non falso
# positivo: al peggio non blocchiamo un caso che forse avremmo dovuto), non a favore.
def get_recent_sale_history(player_slug, eth_rate, last_n=5):
    query = """
    query RecentSaleHistory($p: String!) {
      tokens {
        tokenPrices(playerSlug: $p, rarity: limited) {
          date
          amounts { eurCents wei usdCents gbpCents }
        }
      }
    }
    """
    try:
        data = graphql_query(query, {"p": player_slug})
        if data.get('errors'):
            return None
        nodes = ((data.get('data') or {}).get('tokens') or {}).get('tokenPrices') or []
    except Exception:
        return None
    sales = []
    for n in nodes:
        price = eur_price_from_amounts(n.get('amounts'), eth_rate)
        if price is not None:
            sales.append((n.get('date') or '', price))
    sales.sort(key=lambda s: s[0], reverse=True)
    return sales[:last_n] or None


# FIX 17/07 (backlog item "Satonio pattern-mining", richiesta esplicita dell'utente): indagine
# manuale via DevTools (pagina "Cronologia delle vendite" di un giocatore) ha scoperto che
# tokens.tokenPrices ACCETTA in realta' un sotto-campo "deal" (tipo TokenOffer) con "type",
# "buyer", "seller" -- smentisce la nota precedente ("tokenPrices non distingue il tipo") e i
# vecchi tentativi fallliti di discover_token_price_type_field (che provava nomi di campo
# direttamente su TokenPrice, non dentro un sotto-oggetto "deal"). Valori di "deal.type"
# confermati empiricamente su transazioni reali con esito noto (screenshot utente + cronologia):
# SINGLE_SALE_OFFER = annuncio a prezzo fisso, comprato al volo dal primo che clicca (UI: label
# fuorviante "Scambia") -- e' il vero sniping, quello che interessa per l'analisi Satonio/ZenLock.
# SINGLE_BUY_OFFER e DIRECT_OFFER = offerte negoziate/proposte da una parte e accettate dall'altra
# (UI: entrambe raggruppate sotto "Offerta diretta") -- non lo sniping, escluse dall'analisi.
# Non ancora usato per RECENT_SALE_GATE/build_sale_history_context (restano com'erano, l'utente
# non ha chiesto di toccarli) -- per ora solo per il pattern-mining sotto.
def fetch_user_recent_cards(user_slug, max_pages=20, page_size=20):
    """Recupera gli slug delle carte Limited possedute ATTUALMENTE da user_slug, ordinate dalla
    piu' recente acquisizione, paginando fino a max_pages. Ricostruita per tentativi dai nomi di
    variabile osservati via DevTools sulla richiesta reale "UserCardsSearchQuery" (query
    persistita lato client, solo operationId, niente testo della query originale disponibile) --
    quindi qui e' una query ad-hoc scritta a mano con gli stessi nomi di campo/variabili, non
    garantita al 100% di matchare lo schema esatto: se fallisce, l'errore GraphQL va letto per
    capire cosa correggere. LIMITE NOTO: cattura solo carte ancora possedute da user_slug al
    momento della query -- se le ha gia' rivendute prima di questo controllo, non compaiono qui
    (mancherebbero all'analisi)."""
    query = """
    query SnipeRecentCards($userSlug: String!, $page: Int!, $pageSize: Int!) {
      user(slug: $userSlug) {
        slug
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
            anyPlayer { slug }
          }
          nbHits
        }
      }
    }
    """
    all_hits = []
    for page in range(1, max_pages + 1):
        try:
            data = graphql_query(query, {"userSlug": user_slug, "page": page, "pageSize": page_size})
        except Exception as e:
            log(f"[snipe analysis] eccezione pagina {page} per {user_slug}: {e}")
            break
        if data.get('errors'):
            log(f"[snipe analysis] errore GraphQL pagina {page} per {user_slug}: {data['errors']}")
            break
        search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
        hits = search.get('hits') or []
        if page == 1:
            log(f"[snipe analysis] {user_slug}: {search.get('nbHits')} carte Limited totali possedute, "
                f"scansiono le piu' recenti (max {max_pages * page_size})...")
        if not hits:
            break
        all_hits.extend(hits)
        time.sleep(0.2)
    return all_hits


# FIX 17/07 (richiesta esplicita dell'utente, "c'e' modo di velocizzarlo?"): fetch_player_
# recent_direct_buys interroga la cronologia COMPLETA di ogni giocatore trovato (anche 300+),
# ma la maggior parte delle carte possedute da un manager non sono nemmeno arrivate li' via
# sniping (pacchetti, scambi, altro) -- collo di bottiglia principale. Questa funzione fa un
# controllo rapido A BLOCCHI (tante carte per chiamata, invece di una chiamata per giocatore)
# usando "anyCards(slugs: [...])" con tokenOwner{transferType, from} -- lo stesso campo
# scoperto ieri sul caso Alex Kral -- per scartare SUBITO le carte la cui acquisizione attuale
# non e' un SINGLE_SALE_OFFER recente, prima di spendere una query per-giocatore su
# tokenPrices. Query ricostruita per tentativi (stesso principio di fetch_user_recent_cards),
# non garantita al 100% -- se fallisce l'errore GraphQL dice cosa correggere.
def filter_recent_direct_buy_candidates(hits, buyer_slug, window_days, batch_size=40):
    """Da una lista di hit (slug carta + player slug) restituisce solo i player_slug le cui
    carte risultano acquisite da buyer_slug via SINGLE_SALE_OFFER negli ultimi window_days
    giorni (secondo il tokenOwner ATTUALE della carta -- riflette l'acquisizione vera di
    buyer_slug dato che e' lui il proprietario corrente, vedi hits gia' filtrati per user_slug
    a monte in fetch_user_recent_cards)."""
    query = """
    query SnipeCardsFilter($slugs: [String!]!) {
      anyCards(slugs: $slugs) {
        slug
        anyPlayer { slug }
        tokenOwner {
          transferType
          from
        }
      }
    }
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(days=window_days)
    candidates = []
    seen_players = set()
    card_slugs = [h.get('slug') for h in hits if h.get('slug')]
    for i in range(0, len(card_slugs), batch_size):
        batch = card_slugs[i:i + batch_size]
        try:
            data = graphql_query(query, {"slugs": batch})
        except Exception as e:
            log(f"[snipe analysis] eccezione filtro rapido blocco {i // batch_size + 1}: {e}")
            continue
        if data.get('errors'):
            log(f"[snipe analysis] errore GraphQL filtro rapido blocco {i // batch_size + 1}: {data['errors']}")
            continue
        cards = (data.get('data') or {}).get('anyCards') or []
        for c in cards:
            owner = c.get('tokenOwner') or {}
            if owner.get('transferType') != 'SINGLE_SALE_OFFER':
                continue
            try:
                dt = datetime.datetime.fromisoformat(
                    (owner.get('from') or '').replace('Z', '+00:00')).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue
            if dt < cutoff:
                continue
            p_slug = (c.get('anyPlayer') or {}).get('slug')
            if p_slug and p_slug not in seen_players:
                seen_players.add(p_slug)
                candidates.append(p_slug)
        time.sleep(0.2)
    return candidates


def fetch_player_recent_direct_buys(player_slug, buyer_slug, window_days, eth_rate):
    """Interroga tokens.tokenPrices(playerSlug, rarity: limited) col sotto-campo deal{type buyer
    seller} scoperto oggi, filtra alle transazioni dove deal.buyer.slug == buyer_slug e
    deal.type == 'SINGLE_SALE_OFFER' (acquisto diretto a prezzo fisso, vedi nota sopra), negli
    ultimi window_days giorni. Ritorna una lista di dict con giocatore/carta/prezzo/data/venditore
    PIU' il contesto di margine: FIX 17/07 (richiesta esplicita dell'utente, "estendere il
    contesto"): per ogni acquisto trovato calcola anche "market_median" (mediana di TUTTE le
    altre transazioni SINGLE_SALE_OFFER dello stesso giocatore nella stessa risposta gia'
    scaricata, quindi senza chiamate API aggiuntive -- non e' il "secondo prezzo live" esatto
    che usa il bot principale, e' un'approssimazione retroattiva basata sullo storico vendite
    concluse) e "discount_vs_median" (di quanto, in percentuale, il prezzo pagato era sotto
    quella mediana) -- serve a capire se il prezzo pagato era un vero affare o nella norma per
    quel giocatore, non solo il prezzo assoluto."""
    query = """
    query SnipePlayerBuys($p: String!) {
      tokens {
        tokenPrices(playerSlug: $p, rarity: limited) {
          date
          amounts { eurCents wei usdCents gbpCents }
          card { slug serialNumber }
          deal {
            ... on TokenOffer {
              type
              buyer { ... on User { slug nickname } }
              seller { ... on User { slug nickname } }
            }
          }
        }
      }
    }
    """
    try:
        data = graphql_query(query, {"p": player_slug})
        if data.get('errors'):
            log(f"[snipe analysis] errore GraphQL tokenPrices per {player_slug}: {data['errors']}")
            return []
        nodes = ((data.get('data') or {}).get('tokens') or {}).get('tokenPrices') or []
    except Exception as e:
        log(f"[snipe analysis] eccezione tokenPrices per {player_slug}: {e}")
        return []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=window_days)

    # Prima passata: tutte le vendite SINGLE_SALE_OFFER di questo giocatore nella risposta --
    # e' il campione di riferimento per il "prezzo tipico". FIX 17/07 (richiesta esplicita
    # dell'utente): ESCLUSE le transazioni dove buyer_slug e' acquirente O venditore -- un
    # manager che compra e rimette subito in vendita la stessa carta (flip) genera transazioni
    # che non sono un prezzo di mercato indipendente, includerle nella mediana la farebbe
    # tendere verso il SUO stesso comportamento invece di misurarlo contro il mercato esterno.
    all_single_sale_prices = []
    for n in nodes:
        deal_ctx = n.get('deal') or {}
        if deal_ctx.get('type') != 'SINGLE_SALE_OFFER':
            continue
        b_slug = (deal_ctx.get('buyer') or {}).get('slug')
        s_slug = (deal_ctx.get('seller') or {}).get('slug')
        if b_slug == buyer_slug or s_slug == buyer_slug:
            continue
        price = eur_price_from_amounts(n.get('amounts'), eth_rate)
        if price is not None:
            all_single_sale_prices.append((n.get('date') or '', price))

    results = []
    for n in nodes:
        deal = n.get('deal') or {}
        buyer = deal.get('buyer') or {}
        if buyer.get('slug') != buyer_slug or deal.get('type') != 'SINGLE_SALE_OFFER':
            continue
        try:
            dt = datetime.datetime.fromisoformat((n.get('date') or '').replace('Z', '+00:00')).replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if dt < cutoff:
            continue
        date_str = n.get('date') or ''
        price = eur_price_from_amounts(n.get('amounts'), eth_rate)

        others = [p for d, p in all_single_sale_prices
                  if not (d == date_str and price is not None and abs(p - price) < 0.001)]
        market_median = None
        discount_vs_median = None
        if others:
            others_sorted = sorted(others)
            mid = len(others_sorted) // 2
            if len(others_sorted) % 2 == 1:
                market_median = others_sorted[mid]
            else:
                market_median = (others_sorted[mid - 1] + others_sorted[mid]) / 2
            if price is not None and market_median and market_median > 0:
                discount_vs_median = (market_median - price) / market_median

        results.append({
            "player_slug": player_slug,
            "card_slug": (n.get('card') or {}).get('slug'),
            "date": date_str,
            "price": price,
            "seller": (deal.get('seller') or {}).get('nickname'),
            "market_median": market_median,
            "discount_vs_median": discount_vs_median,
            "sample_size": len(others),
        })
    return results


SNIPE_USER_SLUG = os.environ.get('SNIPE_USER_SLUG', 'zenlock')
SNIPE_WINDOW_DAYS = int(os.environ.get('SNIPE_WINDOW_DAYS', '7'))
SNIPE_MAX_PAGES = int(os.environ.get('SNIPE_MAX_PAGES', '10'))


def diagnostic_snipe_pattern_report(eth_rate):
    """Backlog item "Satonio pattern-mining" (richiesta esplicita dell'utente, 17/07): raccoglie
    gli acquisti diretti a prezzo fisso (SINGLE_SALE_OFFER, il vero sniping) fatti da
    SNIPE_USER_SLUG negli ultimi SNIPE_WINDOW_DAYS giorni, per capire il pattern
    (che margine cerca, che tipo di giocatori, che ora del giorno). Solo raccolta/log, nessuna
    azione automatica. Prima prova su ZenLock (meno carte di Satonio, piu' veloce da validare),
    poi si riusa la stessa funzione su satonio cambiando SNIPE_USER_SLUG."""
    log(f"[snipe analysis] avvio analisi per {SNIPE_USER_SLUG}, finestra "
        f"{SNIPE_WINDOW_DAYS} giorni, max {SNIPE_MAX_PAGES * 20} carte scansionate...")
    hits = fetch_user_recent_cards(SNIPE_USER_SLUG, max_pages=SNIPE_MAX_PAGES)
    log(f"[snipe analysis] {len(hits)} carte scansionate, filtro rapido a blocchi per scartare "
        f"quelle non acquisite via SINGLE_SALE_OFFER nella finestra...")
    player_slugs = filter_recent_direct_buy_candidates(hits, SNIPE_USER_SLUG, SNIPE_WINDOW_DAYS)
    log(f"[snipe analysis] {len(player_slugs)} giocatori candidati dopo il filtro rapido "
        f"(invece di {len(set((h.get('anyPlayer') or {}).get('slug') for h in hits))} totali) "
        f"-- controllo per intero solo questi")

    all_buys = []
    for p_slug in player_slugs:
        all_buys.extend(fetch_player_recent_direct_buys(
            p_slug, SNIPE_USER_SLUG, SNIPE_WINDOW_DAYS, eth_rate))
        time.sleep(0.3)

    all_buys.sort(key=lambda b: b['date'], reverse=True)
    log(f"[snipe analysis] === RISULTATO: {len(all_buys)} acquisti diretti (SINGLE_SALE_OFFER) di "
        f"{SNIPE_USER_SLUG} negli ultimi {SNIPE_WINDOW_DAYS} giorni ===")
    for b in all_buys:
        prezzo = f"{b['price']:.2f}EUR" if b['price'] is not None else "prezzo N/D"
        contesto = ""
        if b.get('discount_vs_median') is not None:
            contesto = (f" [mediana altre vendite: {b['market_median']:.2f}EUR, "
                        f"sconto {b['discount_vs_median']:.1%}, campione {b['sample_size']}]")
        elif b.get('market_median') is None:
            contesto = " [nessuna altra vendita SINGLE_SALE_OFFER trovata per confronto]"
        log(f"[snipe analysis]   {b['date']} -- {b['player_slug']} ({b['card_slug']}): {prezzo} "
            f"da {b['seller']}{contesto}")
    prices = [b['price'] for b in all_buys if b['price'] is not None]
    if prices:
        log(f"[snipe analysis] prezzo medio: {sum(prices)/len(prices):.2f}EUR, "
            f"min {min(prices):.2f}EUR, max {max(prices):.2f}EUR")
    discounts = [b['discount_vs_median'] for b in all_buys if b.get('discount_vs_median') is not None]
    if discounts:
        log(f"[snipe analysis] sconto medio vs mediana altre vendite: {sum(discounts)/len(discounts):.1%} "
            f"(su {len(discounts)}/{len(all_buys)} acquisti con campione di confronto disponibile)")
    log(f"[snipe analysis] analisi completata.")


# BREAKTHROUGH 17/07 (richiesta esplicita dell'utente: "e se provo a cercare nelle query di una
# vendita di zenlock?"): scoperta su DevTools navigando la pagina pubblica "Transazioni" del
# profilo di un manager (sorare.com/it/football/my-club/<slug>/transactions, pubblica per
# QUALSIASI manager, non solo se stessi -- a differenza di UserAccountEntriesQuery che e'
# scoped a currentUser e quindi inutilizzabile per analizzare altri). Il campo root
# user(slug).trades restituisce DIRETTAMENTE tutta la cronologia di transazioni del manager --
# sia ACQUISTI che VENDITE, di ogni giocatore -- in un'unica query paginata (Relay-style,
# pageInfo{endCursor, hasNextPage}). Risolve il problema strutturale della pipeline precedente
# (fetch_user_recent_cards + filter_recent_direct_buy_candidates + fetch_player_recent_direct_buys):
# quella vedeva solo le carte ANCORA possedute, quindi perdeva quasi tutti gli acquisti gia'
# rivenduti (confermato empiricamente su Satonio: allargare la finestra da 3 a 10 giorni ha
# aggiunto solo 1 acquisto su 10 totali). trades non ha questo limite: mostra la transazione a
# prescindere da chi possiede la carta oggi.
#
# Ogni nodo e' un TokenOffer con struttura sender/senderSide e receiver/receiverSide (side =
# {amounts, anyCards}). Il lato con anyCards non vuoto e' chi CEDE la carta (il venditore), il
# lato con amounts valorizzato e senza carte e' chi PAGA (il compratore). Verificato su due casi
# reali (dati incollati dall'utente il 17/07):
#   - SingleBuyOffer, sender=zenlock, senderSide.amounts=4.34EUR, senderSide.anyCards=[],
#     receiver=Leeds United Community, receiverSide.anyCards=[Julian Hall] -> zenlock compra.
#   - SingleSaleOffer, sender=art34, senderSide.anyCards=[Emiliano Martinez], receiver=null,
#     receiverSide.amounts=12.00EUR -> art34 vende, zenlock (query scoped a lui) e' l'acquirente
#     implicito: per un annuncio pubblico SingleSaleOffer il campo receiver resta null anche a
#     transazione conclusa, il compratore si deduce dal fatto che la transazione compare nella
#     LISTA DI ZENLOCK.
# Da qui la logica di ruolo in fetch_user_trades: se lo slug cercato compare esplicitamente come
# sender o receiver, il ruolo si legge dal suo lato (ha carte = vende, ha importo senza carte =
# compra); se non compare in nessuno dei due (receiver nullo, caso SingleSaleOffer pubblico), lo
# slug cercato e' per costruzione la controparte implicita, con ruolo opposto al sender.
def fetch_user_trades(user_slug, window_days, eth_rate, max_pages=10):
    """Interroga direttamente user(slug).trades: TUTTE le transazioni (acquisti E vendite) di un
    manager, senza passare dalle carte attualmente possedute -- vedi nota sopra per come e'
    stata scoperta e perche' sostituisce/completa la pipeline precedente. Pagina finche' non
    esce dalla finestra window_days (i nodi sono ordinati dal piu' recente) o finisce
    max_pages. Ritorna una lista di dict: type, date, role ("buy"/"sell"), price, counterparty,
    player_slug, player_name, card_slug."""
    # NOTA (fix dopo primo test in produzione, 17/07): trades.nodes e' di tipo TokenDeal, union
    # come deal in tokenPrices -- stesso errore "Selections can't be made directly on unions"
    # gia' visto li', stessa soluzione: fragment inline "... on TokenOffer". sender/receiver
    # sono a loro volta BlockchainUser (union), serve "... on User" anche li'.
    query = """
    query SnipeUserTrades($slug: String!, $after: String) {
      user(slug: $slug) {
        slug
        trades(sport: FOOTBALL, after: $after) {
          nodes {
            ... on TokenOffer {
              id
              type
              transactionDate
              sender { ... on User { slug nickname } }
              senderSide {
                amounts { eurCents wei usdCents gbpCents }
                anyCards { slug anyPlayer { slug displayName } sportSeason { name } inSeasonEligible }
              }
              receiver { ... on User { slug nickname } }
              receiverSide {
                amounts { eurCents wei usdCents gbpCents }
                anyCards { slug anyPlayer { slug displayName } sportSeason { name } inSeasonEligible }
              }
            }
          }
          pageInfo { endCursor hasNextPage }
        }
      }
    }
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(days=window_days)
    results = []
    after = None
    for page in range(max_pages):
        try:
            data = graphql_query(query, {"slug": user_slug, "after": after})
        except Exception as e:
            log(f"[snipe analysis] eccezione trades pagina {page + 1} per {user_slug}: {e}")
            break
        if not data or data.get('errors'):
            log(f"[snipe analysis] errore GraphQL trades pagina {page + 1} per {user_slug}: "
                f"{data.get('errors') if data else 'nessuna risposta'}")
            break
        trades = ((data.get('data') or {}).get('user') or {}).get('trades') or {}
        nodes = trades.get('nodes') or []
        if not nodes:
            break
        stop = False
        for n in nodes:
            try:
                dt = datetime.datetime.fromisoformat(
                    (n.get('transactionDate') or '').replace('Z', '+00:00')).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue
            if dt < cutoff:
                stop = True
                continue

            sender = n.get('sender') or {}
            receiver = n.get('receiver') or {}
            sender_side = n.get('senderSide') or {}
            receiver_side = n.get('receiverSide') or {}
            sender_cards = sender_side.get('anyCards') or []
            receiver_cards = receiver_side.get('anyCards') or []

            if sender.get('slug') == user_slug:
                is_selling = bool(sender_cards)
                counterparty = receiver.get('nickname') or receiver.get('slug') or '?'
                cards = sender_cards if is_selling else receiver_cards
                pay_amounts = receiver_side.get('amounts') if is_selling else sender_side.get('amounts')
            elif receiver.get('slug') == user_slug:
                is_selling = bool(receiver_cards)
                counterparty = sender.get('nickname') or sender.get('slug') or '?'
                cards = receiver_cards if is_selling else sender_cards
                pay_amounts = sender_side.get('amounts') if is_selling else receiver_side.get('amounts')
            else:
                # receiver nullo (annuncio pubblico SingleSaleOffer): user_slug e' la
                # controparte implicita, ruolo opposto a quello del sender.
                sender_is_seller = bool(sender_cards)
                is_selling = not sender_is_seller
                counterparty = sender.get('nickname') or sender.get('slug') or '?'
                cards = receiver_cards if is_selling else sender_cards
                pay_amounts = sender_side.get('amounts') if is_selling else receiver_side.get('amounts')

            # FIX 17/07 (richiesta esplicita dell'utente, scoperto sui dati reali di Satonio:
            # decine di carte diverse vendute allo stesso secondo allo stesso prezzo, es. Yunus
            # Akgun x14 a 2.24EUR, Kamal Miller x6 a 1.98EUR -- sono trade bundle, PIU' carte in
            # un'unica offerta con UN prezzo aggregato). Prima il prezzo totale del bundle veniva
            # assegnato per intero a OGNI carta del bundle (stesso importo ripetuto N volte),
            # gonfiando artificialmente prezzo pagato/incassato e quindi anche i margini
            # calcolati sulle vendite (visti margini assurdi tipo -91.7%/-96.9% su Satonio, un
            # acquisto bundle da 85.91EUR attribuito per intero a due carte vendute separatamente
            # per pochi euro). Non c'e' modo affidabile di scomporre il prezzo aggregato per
            # singola carta (i valori delle carte in un bundle non sono necessariamente uguali),
            # quindi seguendo lo stesso principio gia' usato altrove nel bot (scambi carta-per-
            # carta esclusi dalla verifica live perche' il prezzo non e' attribuibile) i bundle
            # (piu' di una carta sullo stesso lato) vengono ESCLUSI dal prezzo per-carta: price
            # resta None (non entra nelle statistiche di prezzo/sconto/margine), ma la
            # transazione resta visibile nei log con bundle_size per trasparenza.
            bundle_size = len(cards)
            is_bundle = bundle_size > 1
            price = None if is_bundle else eur_price_from_amounts(pay_amounts, eth_rate)
            bundle_total_price = eur_price_from_amounts(pay_amounts, eth_rate) if is_bundle else None
            for c in cards:
                player = c.get('anyPlayer') or {}
                season_name = (c.get('sportSeason') or {}).get('name', 'unknown')
                results.append({
                    "type": n.get('type'),
                    "date": n.get('transactionDate'),
                    "role": "sell" if is_selling else "buy",
                    "price": price,
                    "counterparty": counterparty,
                    "player_slug": player.get('slug'),
                    "player_name": player.get('displayName'),
                    "card_slug": c.get('slug'),
                    "season_name": season_name,
                    # riusa season_type_for_card gia' esistente (stessa logica in_season/classic
                    # del bot principale, basata su inSeasonEligible con fallback testuale) --
                    # richiesta esplicita dell'utente (17/07): "guarda anche la tipologia che
                    # compra, se in season, se classic".
                    "season_type": season_type_for_card(c, season_name),
                    "bundle_size": bundle_size,
                    "bundle_total_price": bundle_total_price,
                })

        if stop or not (trades.get('pageInfo') or {}).get('hasNextPage'):
            break
        after = (trades.get('pageInfo') or {}).get('endCursor')
        time.sleep(0.2)

    return results


def diagnostic_manager_trades_report(eth_rate):
    """Come diagnostic_snipe_pattern_report ma basato su fetch_user_trades: mostra ACQUISTI e
    VENDITE di SNIPE_USER_SLUG nella finestra SNIPE_WINDOW_DAYS in un'unica query paginata,
    incluse le carte gia' rivendute (invisibili al vecchio approccio basato sulle carte
    possedute). Per ogni vendita, cerca nella stessa lista un acquisto precedente della STESSA
    carta per ricostruire il ciclo compra-poi-rivendi (task esplicito dell'utente: "non ci
    sarebbe modo di vedere le vendite che ha fatto? e poi controllare come erano state
    acquistate quelle carte"). Solo raccolta/log, nessuna azione automatica."""
    log(f"[snipe analysis] avvio analisi trades per {SNIPE_USER_SLUG}, finestra "
        f"{SNIPE_WINDOW_DAYS} giorni (max {SNIPE_MAX_PAGES} pagine)...")
    reset_currency_branch_stats()  # FIX 17/07 (richiesta esplicita, dopo scoperta bug valute):
    # quantifica quanti prezzi di questa analisi arrivavano da USD/GBP -- prima del fix erano
    # invisibili (None), quindi questi snipe/vendite mancavano del tutto dal report.
    trades = fetch_user_trades(SNIPE_USER_SLUG, SNIPE_WINDOW_DAYS, eth_rate, max_pages=SNIPE_MAX_PAGES)
    buys = [t for t in trades if t['role'] == 'buy' and t['type'] == 'SINGLE_SALE_OFFER']
    sells = [t for t in trades if t['role'] == 'sell']
    other_buys = [t for t in trades if t['role'] == 'buy' and t['type'] != 'SINGLE_SALE_OFFER']
    log(f"[snipe analysis] === {len(trades)} transazioni totali: {len(buys)} snipe (acquisto "
        f"diretto), {len(other_buys)} acquisti negoziati/altro, {len(sells)} vendite ===")

    buys_by_card = {}
    for b in buys + other_buys:
        buys_by_card.setdefault(b['card_slug'], []).append(b)

    log(f"[snipe analysis] --- SNIPE (SINGLE_SALE_OFFER, acquisto diretto) ---")
    for b in sorted(buys, key=lambda x: x['date'], reverse=True):
        prezzo = f"{b['price']:.2f}EUR" if b['price'] is not None else "prezzo N/D"
        log(f"[snipe analysis]   {b['date']} -- {b['player_name']} ({b['card_slug']}) "
            f"[{b.get('season_type', '?')}/{b.get('season_name', '?')}]: {prezzo} "
            f"da {b['counterparty']}")
    prices = [b['price'] for b in buys if b['price'] is not None]
    if prices:
        log(f"[snipe analysis] prezzo medio snipe: {sum(prices) / len(prices):.2f}EUR, "
            f"min {min(prices):.2f}EUR, max {max(prices):.2f}EUR")

    # FIX 17/07 (richiesta esplicita dell'utente, "concentriamoci sul puro snipe... guarda
    # anche la tipologia che compra, se in season, se classic, e a quale prezzo"): bucket
    # in_season/classic (riusa season_type_for_card, stessa logica del bot principale) +
    # fasce di prezzo (stessi confini concettuali di MARGIN_TIERS) sulla SOLA lista di snipe --
    # primo mattone per modellare le sue soglie e progettare un tracker sul suo comportamento.
    for season_key in ('in_season', 'classic', 'unknown'):
        bucket_prices = [b['price'] for b in buys
                          if b.get('season_type') == season_key and b['price'] is not None]
        if bucket_prices:
            log(f"[snipe analysis] bucket {season_key}: {len(bucket_prices)}/{len(buys)} snipe, "
                f"prezzo medio {sum(bucket_prices) / len(bucket_prices):.2f}EUR, "
                f"range {min(bucket_prices):.2f}-{max(bucket_prices):.2f}EUR")
    price_tiers = [(3, '<3'), (5, '3-5'), (10, '5-10'), (15, '10-15'), (20, '15-20'),
                   (30, '20-30'), (60, '30-60'), (float('inf'), '60+')]
    lo = 0
    for hi, label in price_tiers:
        tier_prices = [p for p in prices if lo <= p < hi]
        if tier_prices:
            log(f"[snipe analysis] fascia {label}EUR: {len(tier_prices)}/{len(prices)} snipe "
                f"({len(tier_prices) / len(prices):.0%}), media {sum(tier_prices) / len(tier_prices):.2f}EUR")
        lo = hi

    log(f"[snipe analysis] --- VENDITE (con acquisto precedente della stessa carta, se trovato) ---")
    bundle_sells_skipped = 0
    for s in sorted(sells, key=lambda x: x['date'], reverse=True):
        # FIX 17/07: se e' un bundle (piu' carte nella stessa offerta), il prezzo per-carta non
        # e' attribuibile -- vedi nota sopra fetch_user_trades. Lo segnaliamo esplicitamente
        # invece di scrivere "prezzo N/D" generico, che farebbe pensare a un dato mancante
        # invece che a un limite strutturale del calcolo.
        if s.get('bundle_size', 1) > 1:
            bundle_sells_skipped += 1
            tot = f"{s['bundle_total_price']:.2f}EUR" if s.get('bundle_total_price') is not None else "N/D"
            log(f"[snipe analysis]   {s['date']} -- {s['player_name']} ({s['card_slug']}): "
                f"venduta a {s['counterparty']} in un BUNDLE di {s['bundle_size']} carte "
                f"(prezzo totale bundle {tot}, non attribuibile a questa carta singola) -- saltata")
            continue
        prezzo_v = f"{s['price']:.2f}EUR" if s['price'] is not None else "prezzo N/D"
        acquisto_prec = [b for b in buys_by_card.get(s['card_slug'], []) if b.get('bundle_size', 1) == 1]
        if acquisto_prec:
            a = acquisto_prec[0]
            prezzo_a = f"{a['price']:.2f}EUR" if a['price'] is not None else "prezzo N/D"
            margine = ""
            if a['price'] is not None and s['price'] is not None and a['price'] > 0:
                margine = f", margine {(s['price'] - a['price']) / a['price']:.1%}"
            log(f"[snipe analysis]   {s['date']} -- {s['player_name']} ({s['card_slug']}): "
                f"venduta a {s['counterparty']} per {prezzo_v} -- comprata il {a['date']} "
                f"({a['type']}) per {prezzo_a}{margine}")
        else:
            log(f"[snipe analysis]   {s['date']} -- {s['player_name']} ({s['card_slug']}): "
                f"venduta a {s['counterparty']} per {prezzo_v} -- acquisto precedente non "
                f"trovato nella finestra analizzata")
    if bundle_sells_skipped:
        log(f"[snipe analysis] {bundle_sells_skipped} vendite bundle saltate dal calcolo margine "
            f"(prezzo non attribuibile a singola carta)")
    log(f"[snipe analysis] [diagnostica valute] branch usati in eur_price_from_amounts durante "
        f"questa analisi: {get_currency_branch_stats()}")
    log(f"[snipe analysis] analisi trades completata.")


# FIX 17/07 (richiesta esplicita dell'utente, step 1 di "progettare un tracker sul suo
# modello", scelto tra piu' opzioni: prima le soglie derivate dai dati, poi eventualmente un
# osservatore live -- vedi backlog item 8 gia' esistente per quest'ultimo): unisce la
# pipeline COMPLETA di fetch_user_trades (niente piu' carte invisibili perche' gia' rivendute)
# con il calcolo di discount_vs_median gia' scritto in fetch_player_recent_direct_buys (mediana
# delle altre vendite SINGLE_SALE_OFFER dello stesso giocatore, escluso lui stesso). Prima
# c'erano due pipeline separate con scopi diversi (una trovava I candidati partendo dalle carte
# possedute, l'altra calcolava il margine); ora la lista di snipe e' gia' completa da
# fetch_user_trades, quindi basta arricchirla per-giocatore (un giocatore alla volta, dedup)
# per ottenere: prezzo, sconto% vs mercato, bucket in_season/classic, fascia di prezzo -- i
# quattro assi su cui si basera' la tabella di soglie "modello ZenLock" (per ora solo
# raccolta/log dei dati, la tabella vera e propria si scrive quando i numeri sono abbastanza
# solidi da calibrarla).
def diagnostic_snipe_margin_model_report(eth_rate):
    """Come diagnostic_manager_trades_report ma focalizzato SOLO sugli snipe puri
    (SINGLE_SALE_OFFER) e arricchito col contesto di margine (sconto% vs mediana altre vendite
    dello stesso giocatore) e col bucket in_season/classic -- i dati grezzi per progettare un
    tracker calibrato sul comportamento di SNIPE_USER_SLUG invece che sul nostro."""
    log(f"[snipe analysis] avvio modello soglie snipe per {SNIPE_USER_SLUG}, finestra "
        f"{SNIPE_WINDOW_DAYS} giorni...")
    reset_currency_branch_stats()  # FIX 17/07: vedi nota in diagnostic_manager_trades_report
    trades = fetch_user_trades(SNIPE_USER_SLUG, SNIPE_WINDOW_DAYS, eth_rate, max_pages=SNIPE_MAX_PAGES)
    buys = [t for t in trades if t['role'] == 'buy' and t['type'] == 'SINGLE_SALE_OFFER']
    log(f"[snipe analysis] {len(buys)} snipe trovati, arricchimento margine per giocatore "
        f"unico (query per-giocatore, come nella pipeline precedente)...")

    unique_players = sorted(set(b['player_slug'] for b in buys if b['player_slug']))
    context_by_card = {}
    for p_slug in unique_players:
        for ctx in fetch_player_recent_direct_buys(p_slug, SNIPE_USER_SLUG, SNIPE_WINDOW_DAYS, eth_rate):
            context_by_card[ctx['card_slug']] = ctx
        time.sleep(0.3)

    enriched = []
    for b in buys:
        ctx = context_by_card.get(b['card_slug'])
        enriched.append({
            **b,
            "market_median": ctx.get('market_median') if ctx else None,
            "discount_vs_median": ctx.get('discount_vs_median') if ctx else None,
            "sample_size": ctx.get('sample_size') if ctx else None,
        })

    log(f"[snipe analysis] --- MODELLO SOGLIE: snipe con contesto di mercato ---")
    for e in sorted(enriched, key=lambda x: x['date'], reverse=True):
        prezzo = f"{e['price']:.2f}EUR" if e['price'] is not None else "N/D"
        contesto = ""
        if e.get('discount_vs_median') is not None:
            contesto = (f" [mediana {e['market_median']:.2f}EUR, sconto {e['discount_vs_median']:.1%}, "
                        f"campione {e['sample_size']}]")
        elif not context_by_card:
            contesto = ""
        else:
            contesto = " [nessun confronto disponibile]"
        log(f"[snipe analysis]   {e['date']} -- {e['player_name']} [{e.get('season_type', '?')}] "
            f"{prezzo}{contesto}")

    # Tabella soglie per fascia di prezzo: sconto MEDIO osservato, separatamente per
    # in_season/classic dove il campione lo permette -- questa e' la base della futura
    # "MARGIN_TIERS di ZenLock".
    price_tiers = [(3, '<3'), (5, '3-5'), (10, '5-10'), (15, '10-15'), (20, '15-20'),
                   (30, '20-30'), (60, '30-60'), (float('inf'), '60+')]
    log(f"[snipe analysis] --- TABELLA SOGLIE (sconto% medio vs mediana, per fascia/stagione) ---")
    for season_key in ('in_season', 'classic'):
        lo = 0
        for hi, label in price_tiers:
            bucket = [e for e in enriched
                      if e.get('season_type') == season_key and e['price'] is not None
                      and lo <= e['price'] < hi and e.get('discount_vs_median') is not None]
            if bucket:
                discounts = [e['discount_vs_median'] for e in bucket]
                log(f"[snipe analysis]   {season_key} {label}EUR: n={len(bucket)}, "
                    f"sconto medio {sum(discounts) / len(discounts):.1%}")
            lo = hi
    log(f"[snipe analysis] [diagnostica valute] branch usati in eur_price_from_amounts durante "
        f"questa analisi: {get_currency_branch_stats()}")
    log(f"[snipe analysis] modello soglie completato.")


# FIX 16/07 (v3, richiesta esplicita dell'utente, caso Kotto/Sengezer): il v2 bloccava la
# notifica del tutto se una delle ultime 3 transazioni era pari o piu' economica. Ripensato su
# richiesta dell'utente: invece manda comunque la notifica, ma segnalando chiaramente se nella
# finestra di RECENT_SALE_WINDOW_DAYS giorni precedenti esiste gia' una transazione (vendita,
# scambio, asta -- confermato oggi che tokenPrices ESPONE il tipo tramite deal.type, vedi nota
# sopra su fetch_player_recent_direct_buys) pari o piu' economica -- l'utente decide con tutte
# le informazioni, invece di non vedere affatto il caso.
RECENT_SALE_WINDOW_DAYS = int(os.environ.get('RECENT_SALE_WINDOW_DAYS', '7'))


def find_cheaper_recent_sale(true_min_price, recent_sales):
    """Cerca, tra le transazioni concluse degli ultimi RECENT_SALE_WINDOW_DAYS giorni, la piu'
    recente pari o piu' economica del prezzo notificato. Ritorna (data, prezzo) o None."""
    if not recent_sales:
        return None
    cutoff = datetime.datetime.now() - datetime.timedelta(days=RECENT_SALE_WINDOW_DAYS)
    for date_str, price in recent_sales:
        try:
            sale_dt = datetime.datetime.fromisoformat((date_str or '').replace('Z', '+00:00'))
            sale_dt = sale_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if sale_dt < cutoff:
            continue
        if price <= true_min_price:
            return (date_str, price)
    return None


# FIX 17/07 (richiesta esplicita dell'utente): find_cheaper_recent_sale segnala solo SE esiste
# almeno una vendita recente pari o piu' economica, ma non dice QUANTE -- l'utente ha chiesto di
# ragionare sulla proporzione. Il dettaglio va comunque loggato per poter verificare a mano se
# la segnalazione avrebbe avuto senso. Il blocco si applica SOLO quando il campione e' pieno
# (RECENT_SALE_GATE_SAMPLE_SIZE vendite nella finestra): con meno, il mercato e' semplicemente
# sottile e resta valido il percorso "MERCATO SOTTILE" gia' esistente in
# build_sale_history_context (notifica comunque, solo avviso informativo) -- richiesta esplicita
# dell'utente, per non bloccare su un campione troppo piccolo per essere significativo.
#
# FIX 17/07 (v2, richiesta esplicita dell'utente, "rendiamolo meno hard"): soglia inizialmente
# 3 su 5 in 7 giorni, ripensata subito dopo -- troppo facile da far scattare (bastava una
# maggioranza semplice). Alzata a un consenso quasi totale: 6 vendite su 6 (non solo "la
# maggioranza"), guardando una finestra piu' ampia di 14 giorni invece di 7 per avere un
# campione piu' robusto prima di bloccare. La finestra di 7 giorni (RECENT_SALE_WINDOW_DAYS)
# resta invariata per l'avviso soft esistente (find_cheaper_recent_sale) -- e' una feature
# distinta, l'utente ha chiesto di ammorbidire solo il gate.
#
# LIMITE NOTO (17/07, richiesta esplicita dell'utente): idealmente questo confronto andrebbe
# fatto solo contro vendite dello STESSO bucket (classic o in_season) della carta segnalata, ma
# tokenPrices (unica fonte di storico vendite retroattivo che abbiamo) non espone la stagione
# per singola transazione (vedi nota sopra in get_recent_sale_history: season/sportSeason/
# cardSlug tutti assenti su TokenPrice, verificato per tentativi). L'alternativa scoped
# (sale_history/get_own_recent_sales) esiste ma non si popola piu' (cattura disattivata per
# costo) e comunque partirebbe da zero, quindi non utilizzabile subito. Scelta consapevole
# dell'utente: accettare il mix classic/in_season di tokenPrices com'e' piuttosto che aspettare
# settimane di dati scoped o bloccare la feature -- da rivedere se si trova un altro campo/query
# che espone la stagione per vendita.
RECENT_SALE_GATE_MIN_CHEAPER = 6
RECENT_SALE_GATE_SAMPLE_SIZE = 6
RECENT_SALE_GATE_WINDOW_DAYS = 14


def count_cheaper_recent_sales(true_min_price, recent_sales):
    """Ritorna (cheaper_count, total_in_window): quante transazioni concluse (vendita/scambio/
    asta/offerta) negli ultimi RECENT_SALE_GATE_WINDOW_DAYS giorni sono pari o piu' economiche
    di true_min_price, su quante totali cadono in quella stessa finestra (tra le fino a
    RECENT_SALE_GATE_SAMPLE_SIZE restituite da get_recent_sale_history)."""
    if not recent_sales:
        return 0, 0
    cutoff = datetime.datetime.now() - datetime.timedelta(days=RECENT_SALE_GATE_WINDOW_DAYS)
    cheaper_count = 0
    total_in_window = 0
    for date_str, price in recent_sales:
        try:
            sale_dt = datetime.datetime.fromisoformat((date_str or '').replace('Z', '+00:00'))
            sale_dt = sale_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if sale_dt < cutoff:
            continue
        total_in_window += 1
        if price <= true_min_price:
            cheaper_count += 1
    return cheaper_count, total_in_window


# FIX 17/07 (richiesta esplicita dell'utente, caso Issahaku Fatawu): "il giocatore ha appena 3
# vendite in 21 giorni" -- con cosi' poche transazioni reali, il secondo prezzo che genera il
# margine e' meno affidabile (basta un singolo annuncio isolato a determinarlo): non e' che il
# prezzo sia sopravvalutato come nel caso Sengezer, e' che il mercato e' troppo sottile per
# fidarsi del segnale. Soglia tarata esplicitamente sull'esempio dell'utente: MIN_SALES=4 in
# WINDOW_DAYS=21 fa scattare l'avviso proprio sul caso "3 vendite in 21 giorni".
#
# FIX 17/07 (v2, richiesta esplicita dell'utente, stesso giorno): inizialmente solo un avviso
# informativo (vedi build_sale_history_context piu' sotto, non toccato). L'utente ha poi chiesto
# esplicitamente di bloccare del tutto la notifica in questo caso, non solo segnalarlo: "non
# notificare se ci sono state solo 3 transazioni reali negli ultimi 21 giorni". Il blocco vero e
# proprio (thin_market_blocked) e' cablato in evaluate_player_offer, su entrambi i percorsi di
# notifica (ALERT diretto e opportunita' di margine) -- l'avviso testuale qui sotto in
# build_sale_history_context resta com'era, viene comunque loggato prima del blocco per referenza.
THIN_MARKET_MIN_SALES = int(os.environ.get('THIN_MARKET_MIN_SALES', '4'))
THIN_MARKET_WINDOW_DAYS = int(os.environ.get('THIN_MARKET_WINDOW_DAYS', '21'))


def count_recent_sales_in_window(recent_sales, window_days):
    """Conta quante transazioni (tra quelle restituite da get_recent_sale_history, al massimo
    le ultime 5) cadono negli ultimi window_days giorni. Nota: se ce ne fossero piu' di 5 nella
    finestra, il conteggio resta comunque tappato a 5 (limite di get_recent_sale_history) -- non
    e' un problema per rilevare un mercato SOTTILE (dove per definizione ce ne sono poche), solo
    per distinguere un mercato "abbastanza liquido" da uno "molto liquido", distinzione che qui
    non ci interessa."""
    if not recent_sales:
        return 0
    cutoff = datetime.datetime.now() - datetime.timedelta(days=window_days)
    count = 0
    for date_str, _ in recent_sales:
        try:
            sale_dt = datetime.datetime.fromisoformat((date_str or '').replace('Z', '+00:00'))
            sale_dt = sale_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if sale_dt >= cutoff:
            count += 1
    return count


def build_sale_history_context(recent_sales, cheaper_recent):
    """Restituisce (log_extra, msg_extra) da inserire nei due punti di notifica: sempre il
    contesto delle ultime transazioni, piu' un avviso esplicito se find_cheaper_recent_sale ha
    trovato una transazione recente pari o piu' economica, piu' un avviso separato se il mercato
    risulta sottile (vedi commenti sopra)."""
    if not recent_sales:
        return "", ""
    sale_prices = [p for _, p in recent_sales]
    log_line = (f"ultime {len(recent_sales)} transazioni concluse, dalla piu' recente "
                f"(vendita/scambio/asta/offerta, tutte le stampe 'limited'): "
                + ", ".join(f"{p:.2f}EUR" for p in sale_prices))
    msg_extra = (f"Transazioni recenti (dalla piu' recente): "
                 + ", ".join(f"{p:.2f}EUR" for p in sale_prices) + "\n")
    if cheaper_recent:
        cheaper_date, cheaper_price = cheaper_recent
        log_line += (f" -- ATTENZIONE: una transazione del {cheaper_date} si e' gia' conclusa a "
                     f"{cheaper_price:.2f}EUR, pari o piu' economica: potrebbe non essere un vero "
                     f"affare nonostante il calo rilevato")
        msg_extra += (f"⚠️ Una transazione recente ({cheaper_date[:10]}) si e' gia' conclusa a "
                      f"{cheaper_price:.2f}EUR, pari o piu' economica -- verifica prima di "
                      f"comprare.\n")
    recent_count = count_recent_sales_in_window(recent_sales, THIN_MARKET_WINDOW_DAYS)
    if recent_count < THIN_MARKET_MIN_SALES:
        log_line += (f" -- MERCATO SOTTILE: solo {recent_count} transazioni negli ultimi "
                     f"{THIN_MARKET_WINDOW_DAYS} giorni, il secondo prezzo e' meno affidabile")
        msg_extra += (f"📊 Mercato sottile: solo {recent_count} transazioni reali negli ultimi "
                      f"{THIN_MARKET_WINDOW_DAYS} giorni -- il margine si basa su pochi dati.\n")
    return log_line, msg_extra


# FIX 16/07 (proseguimento, caso Sengezer): proviamo a scoprire se TokenPrice espone un campo
# che distingua il TIPO di transazione (Acquisto istantaneo/Asta vs Scambia/Offerta diretta) --
# se esiste, possiamo finalmente filtrare tokenPrices agli stessi criteri gia' usati altrove nel
# bot per il mercato "vero" (SingleSaleOffer pubblico, non DirectOffer, non scambi carta-per-
# carta). Stesso approccio a tentativi usato per tutti i campi scoperti finora.
def discover_token_price_type_field():
    field_candidates = [
        'type', 'kind', 'transactionType', 'saleType', 'dealType', 'offerType',
        'method', 'source', 'via', 'offerKind', 'category',
    ]
    for field_name in field_candidates:
        query = f"""
        query DiscoverTokenPriceType($p: String!) {{
          tokens {{
            tokenPrices(playerSlug: $p, rarity: limited) {{
              date
              {field_name}
            }}
          }}
        }}
        """
        try:
            data = graphql_query(query, {"p": SALES_HISTORY_DISCOVERY_PLAYER_SLUG})
            if data.get('errors'):
                log(f"[diagnostica tipo transazione] TokenPrice.{field_name}: errore -- {data['errors']}")
            else:
                log(f"[diagnostica tipo transazione] TokenPrice.{field_name}: SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica tipo transazione] TokenPrice.{field_name}: eccezione -- {e}")
    log("[diagnostica tipo transazione] tentativi completati.")


# FIX 16/07 (caso Antonio Sivera): logica di valutazione estratta dal loop di
# handle_offer_update in una funzione a se' stante, cosi' puo' essere richiamata anche dalla
# coda dei casi da riverificare (process_pending_rechecks) e non solo da un evento WS live.
# allow_requeue=False quando chiamata dalla riverifica stessa, per evitare di riaccodare
# all'infinito uno stesso caso che continua a risultare "margine troppo vicino".
def evaluate_player_offer(player_slug, player_name, season_type, season_name, price_eur,
                           card_slug, eth_rate, stats, allow_requeue=True,
                           instant_alert_just_sent=False):
        # Verifica live: qual e' DAVVERO il prezzo minimo attualmente in vendita per questo
        # giocatore, nella stessa categoria in_season/classic (vedi nota nella docstring di
        # get_live_min_offer)? Se la query fallisce per qualsiasi motivo, ripieghiamo sul
        # prezzo di questo singolo evento (comportamento precedente).
        try:
            buckets = get_bucket_prices(player_slug, eth_rate)
        except Exception as e:
            log(f"[verifica live] eccezione per {player_slug}: {e}")
            buckets = None

        # FIX 16/07 (caso Frank Feller): se la verifica live fallisce per un errore di rete
        # transitorio (es. ConnectionResetError, capita spesso -- confermato nei log: 4 volte
        # in 3m27s di ascolto), NON dobbiamo fidarci del prezzo grezzo dell'evento come se
        # fosse il prezzo minimo verificato -- e' esattamente cio' che la verifica live serve
        # ad evitare. Prima di questo fix, un'eccezione qui faceva silenziosamente ripiegare su
        # price_eur come "true_min_price", bypassando tutte le protezioni sotto (margine minimo,
        # calo sospetto, ecc.): confermato che la carta RealDoha da 3.42EUR su Frank Feller era
        # gia' in vendita da giorni, ma la notifica ha usato 4.20EUR (il prezzo grezzo
        # dell'evento) come se fosse il minimo. Ora, se il fetch fallisce, accodiamo il caso per
        # una riverifica alla prossima occasione (stessa coda pending_recheck usata per il caso
        # "margine troppo vicino"), invece di notificare alla cieca o perdere il caso del tutto.
        if buckets is None:
            if allow_requeue:
                log(f"{player_name} ({season_type}, {season_name}): verifica live fallita "
                    f"(errore di rete), accodo per riverifica invece di fidarmi del prezzo "
                    f"grezzo dell'evento ({price_eur:.2f}EUR)")
                queue_pending_recheck(player_slug, player_name, season_type, season_name,
                                       price_eur, card_slug)
            else:
                log(f"{player_name} ({season_type}, {season_name}): verifica live fallita di "
                    f"nuovo in riverifica, scarto senza notificare")
            return

        own_prices, data_incomplete = buckets.get(season_type, ([], False))
        if own_prices:
            true_min_price, true_min_card_slug = own_prices[0]
        else:
            true_min_price, true_min_card_slug = price_eur, card_slug
        # second_min_price/margin_percent vengono calcolati piu' sotto con
        # find_meaningful_second_price (v7), non piu' come semplice own_prices[1].

        # FIX 16/07 (v8, caso Fredrik Andre Bjorkan): l'evento che ha scatenato QUESTA
        # valutazione puo' essere esso stesso un annuncio nuovo di zecca, ma se la verifica
        # live parte troppo presto (entro la finestra di invisibilita' ~2 minuti di Sorare,
        # vedi MARKET_VISIBILITY_DELAY_SECONDS) quell'annuncio non compare ancora nella query
        # -- quindi price_eur (il prezzo dell'evento) puo' risultare PIU' BASSO del minimo
        # trovato dalla query stessa. Confermato: la notifica su Fredrik Andre Bjorkan ha usato
        # 2.62EUR come minimo, ma l'annuncio che aveva scatenato l'evento (Buffett, 2.50EUR,
        # in vendita da meno di un'ora) non era ancora visibile alla query -- se l'utente avesse
        # comprato la carta segnalata a 2.62EUR, ne esisteva gia' una migliore a 2.50EUR.
        # Continuiamo comunque a valutare/notificare normalmente col minimo trovato dalla query
        # (non ha senso ritardare un affare gia' buono), ma accodiamo ANCHE il prezzo grezzo
        # dell'evento per una riverifica successiva: quando l'annuncio diventa visibile, il
        # floor si riallinea al vero minimo (e se il calo residuo e' abbastanza ampio, arriva
        # comunque una notifica separata).
        # FIX 17/07 (caso Manu Duah, confermato dall'utente via screenshot): l'annuncio che ha
        # scatenato l'evento (NYGh05t97, 6.99EUR) era davvero ancora invisibile alla query -- ma
        # lo scarto verso il minimo trovato (MathiasM13, 7.00EUR, slug DIVERSO) era solo 0.14%,
        # sotto INVISIBILITY_GAP_TOLERANCE, quindi scartato come "bug del centesimo" invece che
        # riaccodato per riverifica. Il problema: la tolleranza sul solo scarto% non distingue
        # "stessa carta riletta con arrotondamento leggermente diverso" (il vero bug del
        # centesimo, dove lo slug e' identico) da "carta diversa genuinamente ancora invisibile"
        # (dove lo slug e' per forza diverso) -- ed e' proprio quest'ultimo il caso Duah. Usiamo
        # ora anche lo slug: se e' diverso da quello del minimo trovato, qualunque scarto (anche
        # di un centesimo) e' un segnale vero di invisibilita', non rumore, e va sempre riaccodato.
        is_same_card = true_min_card_slug == card_slug
        gap_relative = (true_min_price - price_eur) / true_min_price if true_min_price > 0 else 0
        if (price_eur < true_min_price and true_min_price > 0
                and (not is_same_card or gap_relative > INVISIBILITY_GAP_TOLERANCE)):
            log(f"{player_name} ({season_type}, {season_name}): l'annuncio che ha scatenato "
                f"l'evento ({price_eur:.2f}EUR) e' piu' economico del minimo trovato dalla "
                f"verifica live ({true_min_price:.2f}EUR) -- probabilmente ancora nella "
                f"finestra di invisibilita' di Sorare"
                + (", accodo per riverifica" if allow_requeue else ", ma questa e' gia' una "
                   "riverifica: non riaccodo di nuovo, evito un ciclo senza fine"))
            if allow_requeue:
                queue_pending_recheck(player_slug, player_name, season_type, season_name,
                                       price_eur, card_slug)

        # Il controllo sopra (price_eur < MIN_PRICE_EUR) filtra solo il prezzo dell'EVENTO
        # che ha innescato il controllo, non il vero prezzo minimo verificato live -- per
        # questo motivo carte a 0.80EUR passavano comunque (caso Lovro Majer: l'evento
        # scatenante era su un annuncio piu' caro, ma la verifica live trovava un prezzo
        # piu' basso altrove, che finiva nell'alert bypassando il filtro). Controlliamo
        # anche il prezzo REALMENTE segnalato, non solo quello dell'evento.
        if true_min_price < MIN_PRICE_EUR:
            return

        # Il riferimento (floor) e' tracciato per bucket in_season/classic (non per stagione
        # esatta): verificato con dati reali che le stampe Classic di anni diversi hanno prezzi
        # tra loro simili -- per i manager sono equivalenti, cambia solo se e' In Season o no.
        floor_row = get_floor(player_slug, season_type)

        if floor_row is None:
            set_floor(player_slug, season_type, true_min_price)
            log(f"{player_name} ({season_type}, {season_name}): inizializzazione a {true_min_price:.2f}EUR")
            log_decision(player_slug, player_name, season_type, season_name, "init",
                         true_min_price=true_min_price)
            return

        floor, floor_updated_at = floor_row

        # Riferimento troppo vecchio: nei "buchi" di ascolto tra un'esecuzione e l'altra
        # il mercato puo' essersi mosso senza che il bot lo vedesse. Meglio riallinearsi
        # in silenzio piuttosto che mostrare un calo% calcolato su un dato ormai stantio.
        # Se non abbiamo affatto un timestamp (righe create da versioni precedenti del
        # bot, prima che questa colonna esistesse sempre), l'eta' e' sconosciuta: meglio
        # trattarla come "troppo vecchia" (riallineo in silenzio) piuttosto che rischiare
        # di confrontare il prezzo vero con un riferimento di eta' ignota e segnalarlo
        # come falso "sospetto" -- e' proprio quello che stava succedendo.
        if not floor_updated_at:
            stale = True
        else:
            try:
                age_hours = (
                    datetime.datetime.now() - datetime.datetime.fromisoformat(floor_updated_at)
                ).total_seconds() / 3600
                stale = age_hours > MAX_FLOOR_AGE_HOURS
            except ValueError:
                stale = True

        if stale:
            log(f"{player_name} ({season_type}, {season_name}): riferimento salvato troppo vecchio "
                f"(ultimo aggiornamento {floor_updated_at}), lo riallineo senza notificare "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR)")
            log_decision(player_slug, player_name, season_type, season_name, "stale_realign",
                         floor_price=floor, true_min_price=true_min_price)
            set_floor(player_slug, season_type, true_min_price)
            return

        if true_min_price >= floor:
            return

        drop_percent = (floor - true_min_price) / floor if floor > 0 else 0

        # Un calo enorme (>50%) e' spesso un dato Sorare errato/vecchio piuttosto che un
        # affare reale. Con il riconoscimento corretto in_season/classic (comprensivo del
        # formato MLS, vedi CURRENT_SEASON_LABELS) il caso Bürki dovrebbe gia' essere
        # risolto alla radice -- ma teniamo comunque questo controllo come rete di sicurezza.
        suspect_drop = drop_percent > MAX_SUSPECT_DROP

        # Il calo% rispetto allo storico puo' sembrare grande anche quando il prezzo minimo
        # e' praticamente identico al secondo annuncio piu' economico attuale (es. 2.34 contro
        # 2.35EUR): in quel caso non e' un vero affare, e' solo il primo di un gruppo di
        # annunci quasi uguali. FIX 16/07 (v9, caso Arijanet Muric -- ripensato): v7 scavalcava
        # gli annunci vicini al minimo per cercare un "salto" piu' su nella lista, ma questo e'
        # PERICOLOSO in un caso reale e frequente: un giocatore si infortuna per mesi, il prezzo
        # "giusto" crolla da 5EUR a ~2.35-2.40EUR e DUE manager lo rimettono in vendita a quel
        # nuovo prezzo basso (un cluster stretto, es. 2.35/2.40EUR) -- v7 avrebbe scavalcato
        # quel cluster e confrontato con un vecchio annuncio rimasto piu' caro (stagnante, non
        # ancora aggiornato dal venditore), scambiando per "occasione" quello che e' semplicemente
        # il nuovo prezzo di mercato corretto. Tornati quindi al confronto diretto SOLO col
        # prezzo letteralmente successivo (own_prices[1]): le soglie per fascia di prezzo
        # (MARGIN_TIERS, gia' calibrate piu' volte sui casi reali: Pec/Guehi, Kounde, Rodrigo)
        # restano l'unico meccanismo per decidere se un calo con un secondo prezzo vicino e'
        # comunque abbastanza ampio da essere un affare distinto.
        second_min_price = own_prices[1][0] if len(own_prices) > 1 else None
        # FIX 16/07 (caso Luis Diaz, richiesta esplicita): una carta IN SEASON e' idonea a
        # tutto cio' per cui lo e' una carta CLASSIC (es. Classic Global Cup, All Star) PIU'
        # le competizioni della stagione corrente (vedi season_type_for_card/inSeasonEligible
        # -- confermato sulla carta Bayern di Luis Diaz: "Di stagione fino al 17 ago" +
        # entrambi i badge Classic Global Cup/All Star). E' quindi un sostituto valido, non
        # un'alternativa "diversa": se il bucket in valutazione e' 'classic' e un annuncio
        # in season e' vicino o piu' economico del secondo prezzo classic, il vero divario e'
        # quello verso la carta in season, non verso il secondo prezzo classic (che puo' essere
        # molto piu' alto, es. caso reale 17.40 vs 22.90 classic, ma solo 17.42 in season --
        # un divario di 2 centesimi, non il 24% mostrato). Il gap sparira' comunque del tutto
        # appena quella carta in season smettera' di esserlo. L'inverso non vale (una classic
        # non sostituisce una in season, le manca l'idoneita' alla stagione corrente), quindi
        # non tocchiamo il caso season_type == 'in_season'.
        if season_type == 'classic':
            in_season_prices, _ = buckets.get('in_season', ([], False))
            if in_season_prices:
                in_season_min = in_season_prices[0][0]
                # FIX 17/07 (caso Franko Kolic): in_season_min puo' essere piu' economico anche
                # del true_min_price CLASSIC stesso, non solo del secondo prezzo classic --
                # usarlo comunque come "secondo prezzo" produceva un margine negativo senza senso
                # (es. -79.2%, true_min 3.44 vs "secondo" 1.92). Se il sostituto in season e' gia'
                # piu' economico del nostro stesso minimo, il problema non e' "margine troppo
                # stretto", e' che il sostituto e' semplicemente il vero affare adesso: messaggio
                # e motivo di scarto dedicati, niente calcolo di margine in quel verso.
                if in_season_min < true_min_price:
                    log(f"{player_name} ({season_type}, {season_name}): sostituto in season ancora "
                        f"piu' economico ({in_season_min:.2f}EUR contro {true_min_price:.2f}EUR "
                        f"classic), non e' un affare distinto, salto la notifica")
                    log_decision(player_slug, player_name, season_type, season_name,
                                 "skip_in_season_substitute_cheaper",
                                 floor_price=floor, true_min_price=true_min_price,
                                 drop_percent=drop_percent, second_min_price=in_season_min)
                    set_floor(player_slug, season_type, true_min_price)
                    return
                if second_min_price is None or in_season_min < second_min_price:
                    second_min_price = in_season_min
        margin_percent = None
        if second_min_price is not None and second_min_price > 0:
            margin_percent = (second_min_price - true_min_price) / second_min_price
            required_margin = required_margin_fraction(second_min_price)
            # FIX 17/07 (backlog item 1, richiesta esplicita dell'utente): questo controllo
            # girava per QUALSIASI calo, anche minimo (es. 0.3%), che non avrebbe comunque mai
            # superato DROP_THRESHOLD -- gonfiava la coda pending_recheck (27-44 casi/run) con
            # casi che, anche dopo un doppio controllo riuscito, non sarebbero mai diventati un
            # ALERT diretto (il drop_percent resta sotto soglia a prescindere dal margine). Ora
            # il blocco "troppo vicino, riaccoda per riverifica" scatta solo se il calo aveva
            # comunque una possibilita' reale di superare la soglia (drop_percent >=
            # DROP_THRESHOLD). Per i cali sotto soglia, invece di uscire subito qui, si prosegue
            # verso il ramo "piccola variazione" piu' sotto (che gia' mostra margine/secondo
            # prezzo a scopo informativo e valuta comunque l'eventuale "opportunita' di
            # margine") -- stesso esito finale (nessuna notifica ALERT), ma senza lo spreco di
            # una riverifica con nuova chiamata API che non avrebbe mai potuto cambiare l'esito.
            if margin_percent < required_margin and drop_percent >= DROP_THRESHOLD:
                log(f"{player_name} ({season_type}, {season_name}): prezzo minimo ({true_min_price:.2f}EUR) "
                    f"troppo vicino al secondo annuncio attuale ({second_min_price:.2f}EUR, "
                    f"margine {margin_percent:.1%}, richiesto {required_margin:.1%} "
                    f"per questa fascia di prezzo), non e' un affare distinto, salto la notifica")
                log_decision(player_slug, player_name, season_type, season_name, "skip_margin_too_close",
                             floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent)
                set_floor(player_slug, season_type, true_min_price)
                # FIX 16/07 (caso Antonio Sivera): l'annuncio davvero piu' economico potrebbe
                # essere stato creato da meno di ~2 minuti e non ancora visibile pubblicamente
                # su Sorare (vedi nota su MARKET_VISIBILITY_DELAY_SECONDS) -- accodiamo per una
                # riverifica successiva invece di scartare in modo definitivo. Non riaccodare
                # se questa valutazione e' gia' lei stessa una riverifica (allow_requeue=False),
                # altrimenti un caso persistente resterebbe in coda all'infinito.
                if allow_requeue:
                    queue_pending_recheck(player_slug, player_name, season_type, season_name,
                                           true_min_price, true_min_card_slug)
                return

        # Rete di sicurezza: il bucket rilevato sembra morto/residuale (stagione di quella lega
        # gia' finita nella pratica, anche se l'etichetta sportSeason.name non lo riflette
        # ancora) mentre il mercato vero si e' spostato nel bucket gemello a un prezzo piu'
        # basso? Vedi cross_bucket_looks_dead per i dettagli (caso Aral Şimşir). A differenza dei
        # cali "dubbi" qui sotto, NON ha senso rifare un doppio controllo sullo stesso bucket:
        # il prezzo li' e' stabile da giorni, il problema e' che quel bucket non e' piu' il
        # mercato reale, non un dato instabile -- quindi si scarta subito, senza secondo tentativo.
        if drop_percent >= DROP_THRESHOLD and buckets is not None:
            if cross_bucket_looks_dead(buckets, season_type, true_min_price):
                sibling_type = 'classic' if season_type == 'in_season' else 'in_season'
                sibling_prices = buckets[sibling_type][0]
                log(f"SALTATO (bucket {season_type} sembra morto/residuale: {len(buckets[season_type][0])} "
                    f"annunci contro {len(sibling_prices)} nel bucket {sibling_type}, li' a partire da "
                    f"{sibling_prices[0][0]:.2f}EUR) {player_name} ({season_type}, {season_name}) -- "
                    f"non notifico, il riferimento e' probabilmente su un mercato non piu' reale")
                log_decision(player_slug, player_name, season_type, season_name, "skip_cross_bucket_dead",
                             floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent,
                             reasons=[f"bucket gemello {sibling_type} ha {len(sibling_prices)} annunci da "
                                      f"{sibling_prices[0][0]:.2f}EUR, molto piu' attivo ed economico"])
                set_floor(player_slug, season_type, true_min_price)
                return

        # Scelta esplicita dell'utente: meglio rischiare di perdere qualche affare vero che
        # mandare notifiche su cui c'e' un dubbio ragionevole che siano fasulle. Percio' un calo
        # sospetto (>50%, possibile dato Sorare errato/vecchio) o dati incompleti (prezzo
        # illeggibile su alcuni annunci compatibili) non vengono notificati alla prima lettura.
        # PRIMA di scartarli pero' proviamo un secondo livello di verifica (double_check_suspect_drop):
        # se una seconda interrogazione indipendente, dopo una breve pausa, conferma lo stesso
        # prezzo minimo (e non e' a sua volta incompleta), e' molto piu' probabile che sia un
        # affare reale e stabile piuttosto che un dato sporco -- in quel caso notifichiamo
        # comunque. Se non si conferma, resta scartato come prima. Il riferimento viene sempre
        # aggiornato, notificato o no, per continuare a tracciare correttamente il prezzo.
        is_dubbio = suspect_drop or data_incomplete
        recheck_confirmed = False
        reasons_log = []
        if drop_percent >= DROP_THRESHOLD and is_dubbio:
            if suspect_drop:
                reasons_log.append("calo molto ampio (>50%)")
            if data_incomplete:
                reasons_log.append("dati incompleti (prezzo illeggibile su alcuni annunci compatibili)")
            log(f"DUBBIO ({', '.join(reasons_log)}) {player_name} ({season_type}, {season_name}) "
                f"sceso: {floor:.2f}EUR -> {true_min_price:.2f}EUR ({drop_percent:.1%}) "
                f"-- eseguo un secondo controllo prima di scartare")
            recheck_confirmed = double_check_suspect_drop(player_slug, season_type, true_min_price, eth_rate)
            if recheck_confirmed:
                log(f"CONFERMATO al secondo controllo: {player_name} resta a {true_min_price:.2f}EUR, procedo con la notifica")
            else:
                log(f"SALTATO (dubbio non confermato al secondo controllo: {', '.join(reasons_log)}) "
                    f"{player_name} ({season_type}, {season_name}) -- non notifico per evitare falsi allarmi")

        should_notify = drop_percent >= DROP_THRESHOLD and (not is_dubbio or recheck_confirmed)

        if should_notify:
            decision = "notify_after_recheck" if is_dubbio else "notify"
            log(f"ALERT! {player_name} ({season_type}, {season_name}) sceso: "
                f"{floor:.2f}EUR -> {true_min_price:.2f}EUR ({drop_percent:.1%}) [prezzo minimo verificato live]")
            # FIX 16/07 (caso Nico O'Reilly): il prezzo minimo notificato (4.74EUR) si e'
            # rivelato sbagliato -- esisteva una carta classic attiva da giorni a 4.70EUR che
            # get_bucket_prices non ha incluso, senza pero' ne' un'eccezione ne' un flag "dati
            # incompleti" nei log, quindi la causa esatta (status diverso da "opened"? rarita'/
            # sport non combacianti? altro?) non era ricostruibile a posteriori. Su ogni ALERT
            # (evento raro, costo trascurabile) salviamo ora il dump grezzo di TUTTI gli annunci
            # live per quel giocatore, cosi' se ricapita abbiamo l'evidenza invece di doverla
            # dedurre da uno screenshot fatto ore dopo.
            log_raw_offers_diagnostic(player_slug, eth_rate)

            # FIX 16/07 (v3, richiesta esplicita dell'utente): non blocchiamo piu' -- notifica
            # comunque, con un avviso se nella finestra di RECENT_SALE_WINDOW_DAYS giorni esiste
            # gia' una transazione pari o piu' economica (vedi find_cheaper_recent_sale).
            # FIX 17/07: last_n alzato a RECENT_SALE_GATE_SAMPLE_SIZE (6, era 5) per avere
            # abbastanza dati anche per il gate qui sotto, che guarda una finestra piu' ampia
            # (14gg) del semplice avviso soft (7gg) -- find_cheaper_recent_sale/build_sale_
            # history_context restano invariati, filtrano comunque da soli sui 7gg.
            recent_sales = get_recent_sale_history(player_slug, eth_rate, last_n=RECENT_SALE_GATE_SAMPLE_SIZE)
            cheaper_recent = find_cheaper_recent_sale(true_min_price, recent_sales)
            sale_history_log, sale_history_msg = build_sale_history_context(recent_sales, cheaper_recent)
            if sale_history_log:
                log(f"{player_name}: {sale_history_log}")

            # FIX 17/07 (richiesta esplicita dell'utente): su un campione pieno di 5 vendite
            # nella finestra, se 3 o piu' sono gia' pari o piu' economiche del prezzo che stiamo
            # per notificare, blocchiamo l'invio -- probabile che sia il livello reale del
            # mercato, non un affare. Con meno di 5 vendite nella finestra il campione e' troppo
            # piccolo per essere significativo: niente blocco, resta il percorso "MERCATO
            # SOTTILE" gia' esistente sopra (notifica comunque, solo avviso informativo).
            cheaper_count, sales_in_window = count_cheaper_recent_sales(true_min_price, recent_sales)
            recent_sales_blocked = (
                sales_in_window >= RECENT_SALE_GATE_SAMPLE_SIZE
                and cheaper_count >= RECENT_SALE_GATE_MIN_CHEAPER
            )

            # FIX 17/07 (v2, richiesta esplicita dell'utente, caso Issahaku Fatawu): non piu'
            # solo avviso informativo -- se ci sono meno di THIN_MARKET_MIN_SALES transazioni
            # reali negli ultimi THIN_MARKET_WINDOW_DAYS giorni, il mercato e' troppo sottile per
            # fidarsi del margine e la notifica va bloccata del tutto, non solo segnalata.
            recent_count_21d = count_recent_sales_in_window(recent_sales, THIN_MARKET_WINDOW_DAYS)
            thin_market_blocked = recent_count_21d < THIN_MARKET_MIN_SALES

            if recent_sales_blocked:
                log(f"{player_name}: BLOCCATO -- {cheaper_count}/{sales_in_window} vendite negli "
                    f"ultimi {RECENT_SALE_GATE_WINDOW_DAYS} giorni pari o piu' economiche di "
                    f"{true_min_price:.2f}EUR, probabile prezzo di mercato reale: notifica NON "
                    f"inviata (solo loggata per controllo)")
                log_decision(player_slug, player_name, season_type, season_name,
                             "skip_recent_sales_gate", floor_price=floor,
                             true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent,
                             reasons=[f"{cheaper_count}/{sales_in_window} vendite recenti pari o "
                                      f"piu' economiche"])
            elif thin_market_blocked:
                log(f"{player_name}: BLOCCATO -- solo {recent_count_21d} transazioni reali negli "
                    f"ultimi {THIN_MARKET_WINDOW_DAYS} giorni (minimo richiesto "
                    f"{THIN_MARKET_MIN_SALES}), mercato troppo sottile per fidarsi del margine: "
                    f"notifica NON inviata (solo loggata per controllo)")
                log_decision(player_slug, player_name, season_type, season_name,
                             "skip_thin_market_gate", floor_price=floor,
                             true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent,
                             reasons=[f"{recent_count_21d} transazioni negli ultimi "
                                      f"{THIN_MARKET_WINDOW_DAYS}gg"])
            else:
                log_decision(player_slug, player_name, season_type, season_name, decision,
                             floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                             second_min_price=second_min_price, margin_percent=margin_percent,
                             reasons=reasons_log or None)

                # true_min_card_slug e' la carta REALMENTE piu' economica in questo momento
                # (verificata live), non necessariamente quella di questo specifico evento.
                base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
                if true_min_card_slug:
                    link = f"{base_link}?card={true_min_card_slug}"
                else:
                    sort_param = "s=Cards+On+Sale+Lowest+Price"
                    link = f"{base_link}?{sort_param}"

                msg_text = (
                    f"\U0001F525 <b>Occasione Sorare!</b>\n\n"
                    f"Giocatore: {player_name}\n"
                    f"Categoria: {'In Season' if season_type == 'in_season' else 'Classic (stagione passata)'}\n"
                    f"Stagione carta: {season_name}\n"
                    f"Calo: {drop_percent:.1%}\n"
                    f"Nuovo prezzo: {true_min_price:.2f}EUR\n"
                    + (f"Secondo prezzo attuale: {second_min_price:.2f}EUR (margine {margin_percent:.1%})\n"
                       if second_min_price is not None else "")
                    + sale_history_msg
                    + (f"⚠️ Confermato al secondo controllo dopo un calo dubbio iniziale ({', '.join(reasons_log)})\n"
                       if is_dubbio else "")
                    + f"\n👉 <b><a href='{link}'>APRI SU SORARE</a></b> 👈"
                )
                send_telegram_msg(msg_text)
        elif drop_percent >= DROP_THRESHOLD:
            log_decision(player_slug, player_name, season_type, season_name, "skip_dubbio_unconfirmed",
                         floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                         second_min_price=second_min_price, margin_percent=margin_percent,
                         reasons=reasons_log or None)
        else:
            # FIX 16/07 (richiesta utente): mostrare margine/secondo prezzo anche qui, non solo
            # negli scarti -- utile per vedere ad occhio quanto ci si avvicina alle soglie anche
            # sui casi che non arrivano nemmeno al 13% di calo, per tararle meglio nel tempo.
            margin_info = (f", secondo prezzo {second_min_price:.2f}EUR (margine {margin_percent:.1%})"
                           if second_min_price is not None else "")
            log(f"{player_name} ({season_type}, {season_name}): piccola variazione, aggiorno il riferimento "
                f"({floor:.2f}EUR -> {true_min_price:.2f}EUR){margin_info}")
            log_decision(player_slug, player_name, season_type, season_name, "update_small_variation",
                         floor_price=floor, true_min_price=true_min_price, drop_percent=drop_percent,
                         second_min_price=second_min_price, margin_percent=margin_percent)

            # FIX 16/07 (v19, caso Andres Cubas): niente calo nuovo rispetto allo storico, ma se
            # il margine verso il secondo prezzo e' GIA' abbastanza ampio da essere considerato
            # un "affare distinto" secondo le nostre stesse soglie (MARGIN_TIERS -- la stessa
            # soglia che altrove impedisce di scartare un calo come "troppo vicino"), vale la
            # pena segnalarlo comunque: non e' un calo, ma e' comunque un divario reale che vale
            # la pena sapere, anche se il floor era gia' li' da un run precedente (magari il
            # divario si e' allargato dopo, perche' altri annunci economici sono spariti). Per
            # evitare di ripetere la stessa segnalazione ad ogni evento successivo se il prezzo
            # non cambia, la mandiamo solo se true_min_price e' diverso dall'ultima volta che
            # abbiamo gia' segnalato questo stesso margine per questo giocatore/bucket.
            # FIX 16/07 (v20, caso Fredrik Andre Bjorkan, richiesta esplicita): se la notifica
            # veloce e' appena partita per questo stesso evento, saltiamo questa -- altrimenti
            # arrivano due messaggi a pochi secondi di distanza per la stessa situazione (uno
            # "veloce" non verificato, uno "margine" verificato ma su un prezzo leggermente
            # diverso a causa della finestra di invisibilita'), percepiti come doppione anche se
            # tecnicamente informazioni distinte. L'utente ha gia' ricevuto un segnale su questa
            # carta, non serve un secondo messaggio nello stesso ciclo.
            if second_min_price is not None and second_min_price > 0 and not instant_alert_just_sent:
                required_margin = required_margin_fraction(second_min_price)
                if margin_percent >= required_margin:
                    last_margin_alert_price = get_last_margin_alert_price(player_slug, season_type)
                    already_alerted = (
                        last_margin_alert_price is not None
                        and abs(true_min_price - last_margin_alert_price) < 0.01
                    )
                    if not already_alerted:
                        # FIX 17/07 (caso Jeong Seung-Won, confermato dall'utente via screenshot):
                        # esiste lo stesso bug mai risolto del caso Nico O'Reilly -- un annuncio
                        # attivo da GIORNI (qui: 2g23o, non la finestra di invisibilita' di ~2
                        # minuti) escluso dalla verifica live senza eccezione ne' flag "dati
                        # incompleti" (4.70EUR di opra michael mancante, notificato 4.78EUR come
                        # se fosse il minimo). Il percorso ALERT salva gia' il dump grezzo di
                        # tutti gli annunci su ogni notifica (log_raw_offers_diagnostic) proprio
                        # per poter diagnosticare casi cosi' -- questo percorso "opportunita' di
                        # margine" non lo faceva, quindi per Jeong Seung-Won non abbiamo
                        # l'evidenza. Aggiunta qui, cosi' alla prossima occorrenza avremo i dati
                        # per capire la causa (status diverso da opened? rarita'/sport non
                        # combacianti? altro?).
                        log_raw_offers_diagnostic(player_slug, eth_rate)

                        # FIX 16/07 (v3, richiesta esplicita dell'utente): non blocchiamo piu' --
                        # notifica comunque, con avviso se c'e' una transazione recente pari o
                        # piu' economica (vedi find_cheaper_recent_sale).
                        # FIX 17/07: last_n alzato a RECENT_SALE_GATE_SAMPLE_SIZE (6, era 5), vedi
                        # nota gemella nel percorso ALERT diretto qui sopra.
                        recent_sales = get_recent_sale_history(player_slug, eth_rate, last_n=RECENT_SALE_GATE_SAMPLE_SIZE)
                        cheaper_recent = find_cheaper_recent_sale(true_min_price, recent_sales)
                        sale_history_log, sale_history_msg = build_sale_history_context(
                            recent_sales, cheaper_recent)

                        # FIX 17/07 (richiesta esplicita dell'utente): stessa regola del percorso
                        # ALERT diretto -- su un campione pieno di 5 vendite nella finestra, 3 o
                        # piu' pari o piu' economiche del prezzo segnalato blocca l'invio (probabile
                        # livello di mercato reale, non un affare); con meno di 5 vendite niente
                        # blocco, resta valido il percorso "MERCATO SOTTILE" gia' esistente.
                        cheaper_count, sales_in_window = count_cheaper_recent_sales(true_min_price, recent_sales)
                        recent_sales_blocked = (
                            sales_in_window >= RECENT_SALE_GATE_SAMPLE_SIZE
                            and cheaper_count >= RECENT_SALE_GATE_MIN_CHEAPER
                        )

                        # FIX 17/07 (v2, richiesta esplicita dell'utente, caso Issahaku Fatawu):
                        # stessa regola del percorso ALERT diretto -- meno di THIN_MARKET_MIN_SALES
                        # transazioni reali negli ultimi THIN_MARKET_WINDOW_DAYS giorni blocca
                        # l'invio, non solo lo segnala.
                        recent_count_21d = count_recent_sales_in_window(recent_sales, THIN_MARKET_WINDOW_DAYS)
                        thin_market_blocked = recent_count_21d < THIN_MARKET_MIN_SALES

                        if recent_sales_blocked:
                            log(f"OPPORTUNITA' DI MARGINE (nessun calo recente) {player_name} "
                                f"({season_type}, {season_name}): minimo {true_min_price:.2f}EUR, "
                                f"secondo prezzo {second_min_price:.2f}EUR (margine {margin_percent:.1%}, "
                                f"richiesto {required_margin:.1%}) -- BLOCCATO: "
                                f"{cheaper_count}/{sales_in_window} vendite negli ultimi "
                                f"{RECENT_SALE_GATE_WINDOW_DAYS} giorni pari o piu' economiche, notifica "
                                f"NON inviata (solo loggata per controllo)")
                            if sale_history_log:
                                log(f"{player_name}: {sale_history_log}")
                            log_decision(player_slug, player_name, season_type, season_name,
                                         "skip_recent_sales_gate", floor_price=floor,
                                         true_min_price=true_min_price, drop_percent=drop_percent,
                                         second_min_price=second_min_price, margin_percent=margin_percent,
                                         reasons=[f"{cheaper_count}/{sales_in_window} vendite recenti "
                                                  f"pari o piu' economiche"])
                            set_last_margin_alert_price(player_slug, season_type, true_min_price)
                        elif thin_market_blocked:
                            log(f"OPPORTUNITA' DI MARGINE (nessun calo recente) {player_name} "
                                f"({season_type}, {season_name}): minimo {true_min_price:.2f}EUR, "
                                f"secondo prezzo {second_min_price:.2f}EUR (margine {margin_percent:.1%}, "
                                f"richiesto {required_margin:.1%}) -- BLOCCATO: solo {recent_count_21d} "
                                f"transazioni reali negli ultimi {THIN_MARKET_WINDOW_DAYS} giorni "
                                f"(minimo richiesto {THIN_MARKET_MIN_SALES}), mercato troppo sottile, "
                                f"notifica NON inviata (solo loggata per controllo)")
                            if sale_history_log:
                                log(f"{player_name}: {sale_history_log}")
                            log_decision(player_slug, player_name, season_type, season_name,
                                         "skip_thin_market_gate", floor_price=floor,
                                         true_min_price=true_min_price, drop_percent=drop_percent,
                                         second_min_price=second_min_price, margin_percent=margin_percent,
                                         reasons=[f"{recent_count_21d} transazioni negli ultimi "
                                                  f"{THIN_MARKET_WINDOW_DAYS}gg"])
                            set_last_margin_alert_price(player_slug, season_type, true_min_price)
                        else:
                            log(f"OPPORTUNITA' DI MARGINE (nessun calo recente) {player_name} "
                                f"({season_type}, {season_name}): minimo {true_min_price:.2f}EUR, "
                                f"secondo prezzo {second_min_price:.2f}EUR (margine {margin_percent:.1%}, "
                                f"richiesto {required_margin:.1%})")
                            log_decision(player_slug, player_name, season_type, season_name,
                                         "notify_margin_opportunity", floor_price=floor,
                                         true_min_price=true_min_price, drop_percent=drop_percent,
                                         second_min_price=second_min_price, margin_percent=margin_percent)
                            if sale_history_log:
                                log(f"{player_name}: {sale_history_log}")

                            base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
                            link = f"{base_link}?card={true_min_card_slug}" if true_min_card_slug else base_link
                            msg_text = (
                                f"\U0001F4D0 <b>Opportunita' di margine (nessun calo recente)</b>\n\n"
                                f"Giocatore: {player_name}\n"
                                f"Categoria: {'In Season' if season_type == 'in_season' else 'Classic (stagione passata)'}\n"
                                f"Stagione carta: {season_name}\n"
                                f"Prezzo minimo: {true_min_price:.2f}EUR\n"
                                f"Secondo prezzo attuale: {second_min_price:.2f}EUR (margine {margin_percent:.1%})\n"
                                + sale_history_msg
                                + f"\nNon e' un calo rispetto allo storico, ma il divario verso il secondo "
                                f"prezzo e' gia' ampio -- puo' valere la pena controllare.\n\n"
                                f"👉 <b><a href='{link}'>APRI SU SORARE</a></b> 👈"
                            )
                            send_telegram_msg(msg_text)
                            set_last_margin_alert_price(player_slug, season_type, true_min_price)

        set_floor(player_slug, season_type, true_min_price)


def process_pending_rechecks(eth_rate):
    """Riverifica, a inizio esecuzione, i casi scartati per "margine troppo vicino" nelle
    esecuzioni precedenti e la cui finestra di invisibilita' Sorare (~2 minuti) e' ormai
    sicuramente passata (vedi nota su MARKET_VISIBILITY_DELAY_SECONDS). Riusa esattamente la
    stessa logica di valutazione di un evento live (evaluate_player_offer): se nel frattempo
    e' comparso un annuncio davvero piu' economico, il margine sul nuovo "secondo prezzo"
    (che prima era il vecchio minimo) sara' quasi certamente sufficiente per notificare."""
    stats = {"processed": 0}
    due, expired = pop_due_pending_rechecks()
    for row in expired:
        log(f"[coda riverifica] {row['player_name']} ({row['season_type']}, {row['season_name']}): "
            f"caso troppo vecchio (accodato il {row['queued_at']}), scartato senza riverificare")
    if not due:
        return
    log(f"[coda riverifica] {len(due)} casi da riverificare (finestra di invisibilita' annunci passata)...")
    for row in due:
        log(f"[coda riverifica] {row['player_name']} ({row['season_type']}, {row['season_name']}): "
            f"riverifico (accodato il {row['queued_at']} a {row['price_eur']}EUR)")
        evaluate_player_offer(row['player_slug'], row['player_name'], row['season_type'],
                               row['season_name'], row['price_eur'], row['card_slug'],
                               eth_rate, stats, allow_requeue=False)
    log("[coda riverifica] completata.")


# --- WebSocket / ActionCable ---
def run_listener(eth_rate):
    reset_currency_branch_stats()  # azzera eventuali chiamate a eur_price_from_amounts avvenute
    # prima dell'ascolto (es. diagnostici), cosi' il conteggio riflette solo questa esecuzione.
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "status_counts": {}}

    def on_open(ws):
        log("Connesso al canale eventi Sorare, sottoscrizione in corso...")
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
        if msg_type == 'reject_subscription':
            log(f"ERRORE: sottoscrizione rifiutata: {message}")
            return

        payload = message.get('message')
        if not payload:
            return

        if payload.get('errors'):
            log(f"ERRORE GraphQL nella subscription: {payload['errors']}")
            return

        stats["received"] += 1
        offer = (payload.get('result', {}).get('data', {}) or {}).get('tokenOfferWasUpdated')
        if offer:
            handle_offer_update(offer, eth_rate, stats)

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). "
            f"Eventi ricevuti: {stats['received']}, carte Limited/football elaborate: {stats['processed']}")
        log(f"[diagnostica tracker] distribuzione status offerte osservate: {stats['status_counts']}")
        log(f"[diagnostica valute] branch usati in eur_price_from_amounts questa esecuzione: "
            f"{get_currency_branch_stats()}")

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

    ws.run_forever(ping_interval=30, ping_timeout=10)
    timer.cancel()


# NOTA STORICA: qui c'era discover_eligibility_field(), un diagnostico temporaneo (caso Harvey
# Elliott) che ha provato per tentativi diversi nomi di campo/tipo GraphQL per scoprire come
# accedere all'idoneita' reale alle competizioni di una carta. Trovato: il campo si chiama
# inSeasonEligible (esiste su AnyCardInterface, confermato via log reale: unico tentativo senza
# errore tra vari candidati). Rimosso il diagnostico ora che sappiamo il nome giusto -- vedi
# season_type_for_card() sopra (vicino a CURRENT_SEASON_LABELS) per come viene usato.


# DIAGNOSTICA TEMPORANEA (16/07, casi Yuma Suzuki e Samuel Kotto -- rimuovere dopo verifica):
# il bot notifica affari basandosi solo sugli annunci ATTIVI (ask price), mai sulle vendite
# REALMENTE concluse -- confermato sia su Suzuki che su Kotto che il prezzo "verificato" come
# affare era in realta' piu' caro di quanto la gente paghi davvero di recente (Kotto: 5.00EUR
# notificato contro 0.94-1.60EUR di vendite reali nelle ultime settimane). Proviamo per
# tentativi (introspection disabilitata, stesso approccio usato per inSeasonEligible) a
# scoprire il campo/query per lo storico vendite (quello dietro la scheda "Cronologia delle
# vendite" nella UI), cosi' in futuro possiamo confrontare il prezzo notificato con le vendite
# reali recenti invece di fidarci solo degli annunci in vendita.
SALES_HISTORY_DISCOVERY_PLAYER_SLUG = os.environ.get('SALES_HISTORY_DISCOVERY_PLAYER_SLUG', 'samuel-junior-kotto')


# FIX 17/07 (richiesta esplicita, caso Mamadou Sangare/talwiwi): un'offerta live REALE (4.59EUR,
# in vendita da mesi) non compariva tra i nodi restituiti da fetch_all_live_offers/
# tokens.liveSingleSaleOffers -- stesso pattern mai risolto di Nico O'Reilly e Jeong Seung-Won.
# Indagata a fondo (ipotesi blockchain Solana, confronto con l'indice Algolia usato dalla UI
# Sorare, campo blockchainId): nessuna delle piste ha trovato la causa -- l'offerta risultava
# assente anche da Algolia, e blockchainId si e' rivelato un ID univoco per carta, non un
# indicatore di blockchain utile a filtrare. Causa radice non risolvibile con le fonti dati
# disponibili (vedi task "Tetto su margine Opportunita' di margine (caso Sangare)" per il
# seguito). Questa funzione resta per un dump grezzo non filtrato generico, utile se dovesse
# ripresentarsi un caso simile in futuro.
DIAGNOSTIC_MISSING_OFFER_PLAYER_SLUG = os.environ.get('DIAGNOSTIC_MISSING_OFFER_PLAYER_SLUG', 'mamadou-sangare')


def diagnostic_dump_missing_offer(player_slug):
    """Dump grezzo e COMPLETO (nessun filtro su status/rarita'/sport) di tutti i nodi restituiti
    da fetch_all_live_offers per un giocatore, per verificare se un'offerta nota compare o meno
    nella risposta -- se non compare per niente, il problema e' lato server/query, non un nostro
    filtro lato client."""
    log(f"[diagnostica offerta mancante] dump completo NON filtrato per {player_slug}...")
    nodes = fetch_all_live_offers(player_slug)
    log(f"[diagnostica offerta mancante] {player_slug}: {len(nodes)} nodi grezzi totali restituiti "
        f"(nessun filtro status/rarita'/sport applicato)")
    for node in nodes:
        status = node.get('status')
        amounts = (node.get('receiverSide') or {}).get('amounts')
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        if not cards:
            log(f"[diagnostica offerta mancante]   status={status} amounts={amounts} "
                f"(nessuna carta sul lato venditore)")
            continue
        for c in cards:
            log(f"[diagnostica offerta mancante]   status={status} amounts={amounts} "
                f"slug={c.get('slug')} rarita'={c.get('rarityTyped')} sport={c.get('sport')} "
                f"stagione={(c.get('sportSeason') or {}).get('name')} "
                f"inSeasonEligible={c.get('inSeasonEligible')}")
    log(f"[diagnostica offerta mancante] dump completato.")


def discover_sales_history_field():
    """Tenta diversi nomi di campo candidati sotto tokens{} per scoprire come accedere allo
    storico delle vendite concluse (non solo agli annunci live). Logga solo esito, non tocca
    la logica del bot."""
    log("[diagnostica storico vendite] inizio tentativi...")
    field_candidates = [
        'closedSingleSaleOffers', 'singleSaleOffersHistory', 'cardSales', 'salesHistory',
        'tokenSales', 'closedOffers', 'pastSingleSaleOffers', 'completedSingleSaleOffers',
        'soldSingleSaleOffers',
    ]
    for field_name in field_candidates:
        query = f"""
        query DiscoverSalesHistory($slug: String!, $n: Int!) {{
          tokens {{
            {field_name}(playerSlug: $slug, last: $n) {{
              nodes {{
                status
              }}
            }}
          }}
        }}
        """
        try:
            data = graphql_query(query, {"slug": SALES_HISTORY_DISCOVERY_PLAYER_SLUG, "n": 5})
            if data.get('errors'):
                log(f"[diagnostica storico vendite] campo '{field_name}': errore -- {data['errors']}")
            else:
                log(f"[diagnostica storico vendite] campo '{field_name}': SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica storico vendite] campo '{field_name}': eccezione -- {e}")

    # FIX 16/07: GraphQL stesso ha suggerito "tokenPrices" come alternativa quando abbiamo
    # provato 'tokenSales' (messaggio "Did you mean tokenPrices?") -- ma il nome suggerisce che
    # riguardi un singolo TOKEN (carta specifica), non un giocatore intero come gli altri
    # tentativi sopra, quindi probabilmente ha argomenti diversi (slug della carta, non
    # playerSlug). Proviamo piu' nomi di argomento plausibili, usando __typename al posto di
    # un campo specifico nella selezione -- e' sempre valido su qualsiasi tipo, quindi ci dice
    # se l'argomento e' quello giusto senza dover indovinare anche la forma del risultato.
    token_slug_for_test = 'samuel-junior-kotto-2025-limited-338'  # carta vista nei log reali (caso Kotto)
    arg_name_candidates = ['slug', 'tokenSlug', 'cardSlug', 'tokenId']
    for arg_name in arg_name_candidates:
        query = f"""
        query DiscoverTokenPrices($v: String!) {{
          tokens {{
            tokenPrices({arg_name}: $v) {{
              __typename
            }}
          }}
        }}
        """
        try:
            data = graphql_query(query, {"v": token_slug_for_test})
            if data.get('errors'):
                log(f"[diagnostica storico vendite] tokenPrices({arg_name}=...): errore -- {data['errors']}")
            else:
                log(f"[diagnostica storico vendite] tokenPrices({arg_name}=...): SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica storico vendite] tokenPrices({arg_name}=...): eccezione -- {e}")

    # FIX 16/07 (proseguimento, log reale): il tentativo sopra ha rivelato la vera firma del
    # campo -- l'errore dice "missing required arguments: playerSlug, rarity" (non slug/
    # tokenSlug/cardSlug/tokenId come provato sopra) -- quindi tokenPrices riguarda TUTTE le
    # vendite di un giocatore per una data rarita', non un singolo token. rarity e'
    # probabilmente un enum GraphQL (non la stringa minuscola 'limited' restituita altrove da
    # rarityTyped) -- proviamo piu' varianti plausibili e lasciamo che l'errore di GraphQL
    # confermi quale, stesso approccio usato sopra.
    rarity_candidates = ['LIMITED', 'Limited', 'limited']
    for rarity_value in rarity_candidates:
        query = f"""
        query DiscoverTokenPrices2($p: String!) {{
          tokens {{
            tokenPrices(playerSlug: $p, rarity: {rarity_value}) {{
              __typename
            }}
          }}
        }}
        """
        try:
            data = graphql_query(query, {"p": SALES_HISTORY_DISCOVERY_PLAYER_SLUG})
            if data.get('errors'):
                log(f"[diagnostica storico vendite] tokenPrices(playerSlug, rarity={rarity_value}): "
                    f"errore -- {data['errors']}")
            else:
                log(f"[diagnostica storico vendite] tokenPrices(playerSlug, rarity={rarity_value}): "
                    f"SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica storico vendite] tokenPrices(playerSlug, rarity={rarity_value}): "
                f"eccezione -- {e}")

    # FIX 16/07 (proseguimento, log reale): tokenPrices(playerSlug: ..., rarity: limited) ha
    # risposto SUCCESSO -- confermato, il campo esiste, l'enum rarity vuole la stringa
    # minuscola 'limited' (non LIMITED/Limited), e restituisce una LISTA di oggetti
    # 'TokenPrice' (5 nodi su Kotto, senza pagination esplicita richiesta -- da capire poi se
    # c'e' un default o se sono TUTTI quelli disponibili). Introspection disabilitata, quindi
    # non possiamo elencare i campi di TokenPrice -- proviamo per tentativi anche qui, un nome
    # alla volta insieme a __typename, stesso approccio usato sopra per scoprire l'argomento
    # giusto. Candidati plausibili per un prezzo/data di vendita.
    token_price_field_candidates = [
        'price', 'amount', 'amounts', 'priceEur', 'eurCents', 'wei', 'eur', 'usd',
        'date', 'soldAt', 'createdAt', 'updatedAt', 'timestamp', 'playerSlug', 'rarity',
        'cardSlug', 'tokenSlug', 'slug', 'season', 'sportSeason',
    ]
    for field_name in token_price_field_candidates:
        query = f"""
        query DiscoverTokenPriceFields($p: String!) {{
          tokens {{
            tokenPrices(playerSlug: $p, rarity: limited) {{
              __typename
              {field_name}
            }}
          }}
        }}
        """
        try:
            data = graphql_query(query, {"p": SALES_HISTORY_DISCOVERY_PLAYER_SLUG})
            if data.get('errors'):
                log(f"[diagnostica storico vendite] TokenPrice.{field_name}: errore -- {data['errors']}")
            else:
                log(f"[diagnostica storico vendite] TokenPrice.{field_name}: SUCCESSO -- {data['data']}")
        except Exception as e:
            log(f"[diagnostica storico vendite] TokenPrice.{field_name}: eccezione -- {e}")

    # FIX 16/07 (proseguimento, log reale): 'date' e' SUCCESSO diretto (confermato: 5 date
    # reali su Kotto, la piu' recente 2026-07-12 -- coerente con vendite recenti, non annunci
    # live). 'amounts' ha dato un errore DIVERSO dagli altri ("must have selections... returns
    # MonetaryAmount"): non "non esiste", ma "esiste, e' un oggetto, servono le sotto-selezioni"
    # -- esattamente lo stesso tipo MonetaryAmount gia' usato altrove nel bot per gli annunci
    # live (eurCents/wei, vedi eur_price_from_amounts). Proviamo direttamente la combinazione
    # completa: se funziona, abbiamo finalmente data+prezzo di vendite reali passate, non solo
    # annunci live -- esattamente cio' che serviva per i casi Suzuki/Kotto.
    query = """
    query DiscoverTokenPriceShape($p: String!) {
      tokens {
        tokenPrices(playerSlug: $p, rarity: limited) {
          date
          amounts { eurCents wei usdCents gbpCents }
        }
      }
    }
    """
    try:
        data = graphql_query(query, {"p": SALES_HISTORY_DISCOVERY_PLAYER_SLUG})
        if data.get('errors'):
            log(f"[diagnostica storico vendite] TokenPrice{{date, amounts{{eurCents wei}}}}: "
                f"errore -- {data['errors']}")
        else:
            log(f"[diagnostica storico vendite] TokenPrice{{date, amounts{{eurCents wei}}}}: "
                f"SUCCESSO -- {data['data']}")
    except Exception as e:
        log(f"[diagnostica storico vendite] TokenPrice{{date, amounts{{eurCents wei}}}}: eccezione -- {e}")

    log("[diagnostica storico vendite] tentativi completati.")


def main():
    init_db()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    log(f"Stagione In Season corrente: {CURRENT_SEASON}")

    # FIX 17/07 (backlog "pattern-mining sniping manager", richiesta esplicita dell'utente): la
    # funzione diagnostic_snipe_pattern_report (e le sue dipendenze fetch_user_recent_cards/
    # fetch_player_recent_direct_buys, vedi sopra) NON viene piu' richiamata da qui -- gira invece
    # da un workflow GitHub Actions separato e dedicato (snipe_pattern.yml + snipe_pattern_
    # analysis.py, che importa questo modulo), per non impattare mai l'esecuzione normale del
    # bot (timeout, rate limit, rischio di girare ad ogni ciclo se ci si dimentica di disattivarla).

    # FIX 17/07: diagnostico temporaneo per il caso Mamadou Sangare/talwiwi (ipotesi Solana
    # esclusa da tokens.liveSingleSaleOffers) rimosso da qui dopo la raccolta dei log --
    # conclusione: l'offerta mancante non e' visibile ne' dalla nostra query ne' da Algolia
    # (stesso indice usato dalla UI Sorare) ne' distinguibile via blockchainId (e' un ID
    # univoco per carta, non un indicatore di blockchain) -- causa radice non risolvibile con
    # le fonti dati disponibili. diagnostic_dump_missing_offer resta definita piu' sotto nel
    # caso serva in futuro (stesso principio di discover_token_price_type_field/
    # discover_sales_history_field).

    # FIX 16/07: entrambi i diagnostici temporanei (campo storico vendite, poi campo tipo
    # transazione) sono stati rimossi da qui -- il secondo (discover_token_price_type_field) ha
    # confermato lo stesso esito negativo su due esecuzioni distinte (11 nomi di campo, nessuno
    # esiste su TokenPrice): vicolo cieco confermato, non ha senso ripeterlo ancora. Da qui in
    # poi lo storico vendite si basa su tokenPrices (retroattivo, tipo misto, vedi
    # get_recent_sale_history) per il gate duro, e su sale_history (nostro, solo accepted
    # verificati, vedi record_accepted_sale) che intanto continua ad accumularsi in background.

    # FIX 16/07: riverifica prima di ascoltare nuovi eventi -- vedi nota su
    # MARKET_VISIBILITY_DELAY_SECONDS in process_pending_rechecks.
    process_pending_rechecks(eth_rate)

    log(f"Ascolto per {LISTEN_SECONDS} secondi...")
    run_listener(eth_rate)
    log_decision_summary()
    log("Esecuzione terminata.")


if __name__ == "__main__":
    main()
