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
    (3, 2.53),
    (5, 4.40),  # FIX 16/07 (v6, caso Kounde): 13.0% -> 12.0%, richiesta esplicita
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
      amounts { eurCents wei }
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
      amounts { eurCents wei }
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
        receiverSide { amounts { eurCents wei } anyCards { slug } }
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
    conn.commit()
    conn.close()


def log_decision(player_slug, player_name, season_type, season_name, decision,
                  floor_price=None, true_min_price=None, drop_percent=None,
                  second_min_price=None, margin_percent=None, reasons=None):
    """Registra una riga per ogni decisione presa (notificato o scartato, e perche').
    Query utili in futuro, es.: `SELECT decision, COUNT(*) FROM decisions_log GROUP BY decision`
    per vedere quanto viene notificato contro quanto viene scartato e con quale motivo."""
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


def eur_price_from_amounts(amounts, eth_rate):
    if not amounts:
        return None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100
    if amounts.get('wei') is not None:
        try:
            return float(amounts['wei']) / 1e18 * eth_rate
        except (TypeError, ValueError):
            return None
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
    tra bucket (cross_bucket_looks_dead) -- nello stesso fetch, senza query aggiuntive."""
    nodes = fetch_all_live_offers(player_slug)
    raw = {'in_season': [], 'classic': []}
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
            # Annuncio aperto e compatibile, ma Sorare non ci ha detto il prezzo: non possiamo
            # escluderlo dal conteggio, potrebbe essere il vero secondo (o primo) piu' economico.
            incomplete_flags[node_season_type] = True
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


def log_raw_offers_diagnostic(player_slug, eth_rate):
    """FIX 16/07 (caso Nico O'Reilly): quando scatta un ALERT, salviamo anche il dump grezzo di
    TUTTI gli annunci live per quel giocatore (status, prezzo, slug, rarita', sport, stagione),
    cosi' se in futuro il prezzo minimo notificato risultasse sbagliato (come successo con la
    carta da 4.70EUR di NFT Sportsclub, esclusa senza che nei log restasse traccia del motivo --
    ne' un'eccezione ne' un flag "dati incompleti") avremo l'evidenza per capire quale filtro
    l'ha esclusa, invece di doverlo dedurre ore dopo da uno screenshot. Chiamata solo sugli
    ALERT (evento raro), quindi il costo di un'interrogazione extra e' trascurabile."""
    try:
        nodes = fetch_all_live_offers(player_slug)
    except Exception as e:
        log(f"[diagnostica alert] impossibile scaricare il dump grezzo per {player_slug}: {e}")
        return
    log(f"[diagnostica alert] {player_slug}: {len(nodes)} annunci live grezzi trovati")
    for node in nodes:
        status = node.get('status')
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        if not cards:
            log(f"[diagnostica alert]   status={status} prezzo={price} (nessuna carta compatibile sul lato venditore)")
            continue
        for c in cards:
            log(f"[diagnostica alert]   status={status} prezzo={price} slug={c.get('slug')} "
                f"rarita'={c.get('rarityTyped')} sport={c.get('sport')} "
                f"stagione={(c.get('sportSeason') or {}).get('name')} "
                f"inSeasonEligible={c.get('inSeasonEligible')}")


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

    for card in (sender_side.get('anyCards') or []):
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
        send_instant_alert(player_slug, player_name, season_type, season_name, price_eur, card_slug)

        evaluate_player_offer(player_slug, player_name, season_type, season_name, price_eur,
                               card_slug, eth_rate, stats)


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
        return
    floor, floor_updated_at = floor_row
    if floor <= 0 or price_eur >= floor:
        return

    # FIX 16/07 (v13, casi Miazga/Thorstvedt vs Cakir): vedi nota su INSTANT_ALERT_MAX_FLOOR_AGE_HOURS
    # -- un floor non aggiornato di recente non e' abbastanza affidabile per un alert non
    # verificato, meglio saltarlo e aspettare l'alert ufficiale (che fa comunque una verifica live).
    if not floor_updated_at:
        return
    try:
        floor_age_hours = (
            datetime.datetime.now() - datetime.datetime.fromisoformat(floor_updated_at)
        ).total_seconds() / 3600
    except ValueError:
        return
    if floor_age_hours > INSTANT_ALERT_MAX_FLOOR_AGE_HOURS:
        return

    drop_percent = (floor - price_eur) / floor
    if drop_percent < INSTANT_ALERT_DROP_THRESHOLD:
        return
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
        f"<a href='{link}'>Clicca qui per vedere le offerte</a>"
    )
    send_telegram_msg(msg_text)


# FIX 16/07 (caso Antonio Sivera): logica di valutazione estratta dal loop di
# handle_offer_update in una funzione a se' stante, cosi' puo' essere richiamata anche dalla
# coda dei casi da riverificare (process_pending_rechecks) e non solo da un evento WS live.
# allow_requeue=False quando chiamata dalla riverifica stessa, per evitare di riaccodare
# all'infinito uno stesso caso che continua a risultare "margine troppo vicino".
def evaluate_player_offer(player_slug, player_name, season_type, season_name, price_eur,
                           card_slug, eth_rate, stats, allow_requeue=True):
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
        if (price_eur < true_min_price and true_min_price > 0
                and (true_min_price - price_eur) / true_min_price > INVISIBILITY_GAP_TOLERANCE):
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
        margin_percent = None
        if second_min_price is not None and second_min_price > 0:
            margin_percent = (second_min_price - true_min_price) / second_min_price
            required_margin = required_margin_fraction(second_min_price)
            if margin_percent < required_margin:
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
                + (f"⚠️ Confermato al secondo controllo dopo un calo dubbio iniziale ({', '.join(reasons_log)})\n"
                   if is_dubbio else "")
                + f"\n<a href='{link}'>Clicca qui per vedere le offerte</a>"
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


def main():
    init_db()
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    log(f"Stagione In Season corrente: {CURRENT_SEASON}")

    # FIX 16/07: riverifica prima di ascoltare nuovi eventi -- vedi nota su
    # MARKET_VISIBILITY_DELAY_SECONDS in process_pending_rechecks.
    process_pending_rechecks(eth_rate)

    log(f"Ascolto per {LISTEN_SECONDS} secondi...")
    run_listener(eth_rate)
    log("Esecuzione terminata.")


if __name__ == "__main__":
    main()
