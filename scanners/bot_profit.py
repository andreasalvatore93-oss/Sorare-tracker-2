"""
Bot Profit -- listener di mercato Sorare (stesso modello di Bot Supremo) che NON
punta ne' offre: si limita a tracciare, per ogni carta incontrata (limited, in
season + classic), i dati necessari a stimare il "potenziale di crescita di
valore" verso la prossima partita del giocatore.

REGOLA CHIAVE campionato MLS/K-League: in_season e classic sono due mercati
completamente separati (due "giocatori diversi" ai fini del tracciamento) --
due righe distinte, ognuna col proprio storico transazioni e proprio minimo,
mai mescolati. Per TUTTI gli altri campionati: un giocatore = una riga sola,
in_season+classic mescolati (stesso identico criterio di Bot Supremo).

Esclusioni (per alleggerire ogni analisi futura):
  - min_attuale < 2 EUR (FIX 29/07, era 1 EUR: richiesta esplicita utente --
    sotto questa soglia difficilmente ci sono variazioni di profit
    significative, non vale la pena nemmeno tracciarle) -> scartata SUBITO
    (prima query in assoluto), NESSUNA blacklist (il prezzo puo' risalire,
    non e' un'esclusione permanente)
  con blacklist dedicata a decadenza ISO (sorare_lista_nera_profit.txt),
  controllata PRIMA di ogni query cosi' le carte gia' note vengono saltate a
  costo zero:
  - coverageStatus=NOT_COVERED -> blacklist 30 giorni
  - L5 = 0 (o non disponibile)  -> blacklist 30 giorni
  - prossima partita = None     -> blacklist 3 giorni (transitorio, il
                                    calendario puo' aggiornarsi presto)

Dati registrati per ogni carta (per iniziare a soppesare il "potenziale
crescita" -- richiesta esplicita utente 24/07):
  - punteggio ULTIMA partita giocata (peso maggiore secondo l'esperienza utente)
  - L5 / L10 / L40 (pesi decrescenti in quest'ordine)
  - minimo attuale in vendita
  - media transazioni ultimi 7 GIORNI (non piu' ultime 30 transazioni --
    cambio richiesto 24/07, ritenuto piu' affidabile), trim di min/max
  - sconto% tra media 7gg trimmed e minimo attuale
  - data/ore alla prossima partita

Nessuna decisione di acquisto/offerta, nessun punteggio composito calcolato
ancora (i pesi relativi vanno concordati prima di tradurli in un unico score).

Output (FIX 27/07, richiesta esplicita utente: un solo output per run, niente
ambiguita' su quale aprire; FIX 29/07 quater, estensione K-League: classifiche
separate per lega invece di un unico file mescolato) in bot_profit_output/
(cartella in root del repo, non sotto scanners/), CLASSIFICA PERSISTENTE che
si aggiorna nel tempo (ricaricata ad ogni avvio, non riparte mai vuota) --
in_season e classic mescolati nella stessa riga (distinti dalla colonna
tipo_carta), ma MLS e K-League in due file separati:
  - profit_tracking_mlspa_<timestamp_utc>.csv -> top 50 carte MLS per potenziale_score
  - profit_tracking_k-league-1_<timestamp_utc>.csv -> top 50 carte K-League per potenziale_score
Il nome include data/ora UTC (formato YYYYMMDD_HHMM); ad ogni riscrittura il
file con timestamp precedente (PER QUELLA LEGA) viene cancellato, quindi ne
resta sempre e solo uno per lega (il piu' recente). Riscritto ad ogni commit
periodico (default 5 minuti) con SOLO le prime 50 carte per potenziale_score
decrescente.
Il bot si ferma automaticamente anche quando raggiunge MAX_TRACKED_CARDS
(default 500) di carte NUOVE, oltre che a fine LISTEN_SECONDS.
"""
import csv
import datetime
import glob
import json
import os
import subprocess
import threading
import time
import concurrent.futures

import requests
import websocket  # pip install websocket-client

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()

# =====================================================================================
# CONFIG / CREDENZIALI -- stesse variabili d'ambiente di Bot Supremo
# =====================================================================================
COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessi 2 campionati "a due mercati separati" (MLS, K-League), identico a Bot
# Supremo -- J League ESCLUSA da questo filtro (logica normale, mercato unico).
EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1'}

# FIX 29/07 quater (richiesta esplicita utente: estendere a K-League, INSIEME a
# MLS in una sola run, con classifiche/CSV separati -- progettato nella
# sessione pomeridiana del 28/07, vedi docs/BOT_PROFIT_RIASSUNTO_2026-07-28.md
# sezione H per il piano originale). Prima TEAM_WHITELIST era una lista piatta
# con UNA SOLA lega globale (SNAPSHOT_LEAGUE_SLUG) valida per tutte le squadre
# -- ora ogni squadra porta la propria lega, cosi' MLS e K-League convivono
# nella stessa run senza mescolarsi (stessi identici vincoli per entrambe:
# soglia 2 EUR, MIN_TRANSACTIONS_FOR_RANKING, TOP_N_OUTPUT -- nessuna
# differenziazione richiesta dall'utente).

CHECK_CLASSIC = os.environ.get('CHECK_CLASSIC', 'si').strip().lower() in ('1', 'true', 'yes', 'si')

# =====================================================================================
# MODALITA' SNAPSHOT (richiesta esplicita utente 26/07): invece di aspettare eventi
# websocket per aggiornare una carta (comportamento normale, sotto), fa un giro
# esplicito sul roster completo delle squadre in TEAM_WHITELIST (query pubblica
# Club.anyPlayers, stesso pattern di formazione_mls/discovery/mls_mid_discovery_global.py)
# e ricalcola OGNI carta (in_season + classic) indipendentemente da eventi di mercato.
# Fase di test: si parte da UNA squadra sola (Vancouver Whitecaps) per validare i
# risultati prima di estendere a tutto il roster MLS/Korea.
# TEAM_WHITELIST vuota = nessuna restrizione (comportamento a eventi invariato).
SNAPSHOT_MODE = os.environ.get('SNAPSHOT_MODE', 'si').strip().lower() in ('1', 'true', 'yes', 'si')
_MLS_TEAM_SLUGS_DEFAULT = (
    'nashville-sc,inter-miami,chicago-fire-bridgeview-illinois,new-england-foxborough-massachusetts,'
    'cincinnati-cincinnati-ohio,new-york-city-new-york-new-york,charlotte-fc-charlotte-north-carolina,'
    'new-york-rb-secaucus-new-jersey,dc-united-washington-district-of-columbia,orlando-city-lake-mary-florida,'
    'columbus-crew-columbus-ohio,toronto-toronto,montreal-impact-montreal-quebec,atlanta-united-atlanta-georgia,'
    'philadelphia-union-chester-pennsylvania,vancouver-whitecaps-vancouver-british-columbia,'
    'sj-earthquakes-santa-clara-california,los-angeles-fc-los-angeles-california,'
    'real-salt-lake-salt-lake-city-utah,dallas-frisco-texas,seattle-sounders-renton-washington,'
    'houston-dynamo-houston-texas,st-louis-city-st-louis-missouri,'
    'minnesota-united-minneapolis-saint-paul-minnesota,la-galaxy-los-angeles-california,'
    'colorado-rapids-denver-colorado,portland-timbers-portland-oregon,san-diego-san-diego,'
    'austin-austin-texas,sporting-kc-kansas-city-kansas'
)
_KLEAGUE_TEAM_SLUGS_DEFAULT = (
    'anyang-anyang,bucheon-1995-bucheon,daejeon-citizen-daejeon,gangwon-gangneung,'
    'gwangju-gwangju,incheon-united-incheon,jeju-united-seogwipo-jeju-do,'
    'jeonbuk-motors-jeonju,pohang-steelers-pohang,sangju-sangmu-sangju,seoul-seoul,'
    'ulsan-ulsan'
)
MLS_TEAM_WHITELIST = [s.strip() for s in os.environ.get('TEAM_WHITELIST', _MLS_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
KLEAGUE_TEAM_WHITELIST = [s.strip() for s in os.environ.get('KLEAGUE_TEAM_WHITELIST', _KLEAGUE_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
# Mappa squadra -> lega (sostituisce la vecchia costante globale SNAPSHOT_LEAGUE_SLUG,
# che assumeva UNA sola lega per l'intera run): MLS e K-League vengono processate
# insieme in una sola run, ciascuna squadra sa gia' a quale lega appartiene.
TEAM_LEAGUE_MAP = {}
TEAM_LEAGUE_MAP.update({slug: 'mlspa' for slug in MLS_TEAM_WHITELIST})
TEAM_LEAGUE_MAP.update({slug: 'k-league-1' for slug in KLEAGUE_TEAM_WHITELIST})
TEAM_WHITELIST = list(TEAM_LEAGUE_MAP.keys())

# FIX 24/07 (richiesta esplicita utente, promemoria applicato ora): prima nessun
# default (obbligatorio ad ogni run), ora default 100 minuti -- resta comunque
# sovrascrivibile dal workflow_dispatch.
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '6000'))

# Commit periodico dei dati tracciati -- default 5 minuti (era 2, richiesta
# esplicita utente 24/07).
COMMIT_CHUNK_SECONDS = int(os.environ.get('COMMIT_CHUNK_SECONDS', '300'))

# FIX 24/07 (richiesta esplicita utente): non piu' un campione fisso di N
# transazioni, ma una FINESTRA TEMPORALE -- tutte le transazioni reali degli
# ultimi TRANSACTIONS_WINDOW_DAYS giorni (default 7, prima era 30 su un
# campione fisso di 30 transazioni). Ritenuto piu' affidabile dall'utente.
TRANSACTIONS_WINDOW_DAYS = int(os.environ.get('TRANSACTIONS_WINDOW_DAYS', '7'))
TRANSACTIONS_PAGE_SIZE = 50
TRANSACTIONS_MAX_PAGES = 3

TOP_N_OUTPUT = int(os.environ.get('TOP_N_OUTPUT', '50'))

# Stop automatico anche per numero di carte NUOVE tracciate in questa run,
# non solo per LISTEN_SECONDS -- default 500.
MAX_TRACKED_CARDS = int(os.environ.get('MAX_TRACKED_CARDS', '500'))

# FIX 26/07 (richiesta esplicita utente, ridurre ulteriormente il roster full-MLS),
# esteso 27/07 (richiesta esplicita utente) a L5 e L40 oltre a L10: sotto questa
# soglia su UNA QUALSIASI delle tre medie, il giocatore e' scartato GIA' nella
# query roster (vedi fetch_team_roster) -- zero query sprecate sulle costose
# (snapshot/minimo/transazioni) per chi non le supererebbe comunque.
# CHECK_CLASSIC resta 'si' (l'utente vuole continuare a tracciare le classic,
# solo il roster va tagliato).
ROSTER_MIN_AVG_SCORE = float(os.environ.get('ROSTER_MIN_AVG_SCORE', '35.0'))

# FIX 27/07 (richiesta esplicita utente, run troppo lento + 429): la pausa fissa
# per-giocatore del 26/07 serializzava tutto il giro. _graphql_throttle() e' gia'
# un rate-limiter GLOBALE condiviso (lock + intervallo minimo tra le richieste,
# si autoallenta a 0.6s dopo un 429) -- e' lui il vero argine ai 429, non un
# secondo ritardo sequenziale sopra. Sostituita con un pool di worker che
# processano piu' giocatori in parallelo: il throttle continua a limitare il
# RITMO delle richieste in uscita, la concorrenza serve solo a sovrapporre i
# tempi di attesa risposta invece di sommarli giocatore per giocatore.
# Ridotto da 8 a 5 il 27/07 (423 HTTP 429), poi RIPORTATO su e alzato a 10:
# la run con 5 worker ha ridotto i 429 (423->243) ma e' durata DI PIU' (10:11
# -> 12:02) perche' il taglio di throughput e' costato piu' di quanto abbia
# fatto risparmiare in retry evitati. Il ritmo piu' lento (0.25s, vedi sopra)
# resta invece confermato: quello sì ha ridotto i 429 senza il costo di
# throughput dei worker. Portato a 10 (richiesta esplicita utente, scendere
# sotto i 10 minuti): il throttle globale limita comunque il RITMO di invio a
# 1/0.25s, quindi piu' worker aumentano solo la sovrapposizione dei tempi di
# attesa risposta, non il ritmo reale verso Sorare.
SNAPSHOT_WORKER_THREADS = int(os.environ.get('SNAPSHOT_WORKER_THREADS', '10'))

# FIX 24/07 (richiesta esplicita utente): sotto questa soglia di transazioni nella
# finestra, il dato e' troppo rumoroso per la classifica (una singola transazione
# anomala puo' spostare la media intera) -- escluso, non solo dal trim ma dalla
# classifica stessa. Abbassato temporaneamente a 10 per il test full-MLS del
# 26-27/07 dopo l'esclusione di aste/acquisto istantaneo dalla media (vedi
# _is_countable_transaction, il conteggio e' naturalmente ~40-50% piu' basso a
# parita' di liquidita' reale) -- riportato a 15 (richiesta esplicita utente
# 27/07, priorita' a un risultato piu' pulito) per riallinearsi al default gia'
# usato in .github/workflows/bot_profit.yml, che non era mai stato cambiato.
MIN_TRANSACTIONS_FOR_RANKING = int(os.environ.get('MIN_TRANSACTIONS_FOR_RANKING', '15'))

# FIX 24/07 (richiesta esplicita utente): sotto questo prezzo minimo la carta
# viene scartata SUBITO, come prima query in assoluto -- niente tracciamento,
# niente blacklist (il prezzo puo' risalire, non e' un'esclusione permanente
# come coverage/L5/nessuna partita). Alleggerisce le chiamate successive.
MIN_PRICE_EUR_THRESHOLD = float(os.environ.get('MIN_PRICE_EUR_THRESHOLD', '2.0'))

OUTPUT_DIR = 'bot_profit_output'
# FIX 27/07 (richiesta esplicita utente: troppi file separati, "non so quale
# aprire"): un SOLO file combinato (in season+classic mescolati, tutte le
# leghe) al posto dei 3 file globali di prima (combinato/solo in season/solo
# classic) -- il filtro Tipo del viewer copre gia' il bisogno di isolare
# in_season o classic. Il nome include data/ora (UTC) cosi' si vede a colpo
# d'occhio quanto e' fresco senza aprire il file. Solo l'ULTIMO file resta sul
# disco: quelli vecchi vengono cancellati ad ogni scrittura (vedi
# _cleanup_and_write_ranked_csv).
OUTPUT_CSV_PREFIX = os.path.join(OUTPUT_DIR, 'profit_tracking')

EVENT_WORKER_THREADS = int(os.environ.get('EVENT_WORKER_THREADS', '2'))

# =====================================================================================
# BLACKLIST DEDICATA (decadenza ISO, formato identico a Bot Supremo: righe
# "tipo,slug,scadenza_iso") -- alleggerisce le analisi future saltando a costo
# zero le carte gia' note come non trattabili.
# =====================================================================================
LISTA_NERA_PROFIT_PATH = os.environ.get('LISTA_NERA_PROFIT_PATH', 'sorare_lista_nera_profit.txt')
NOT_COVERED_O_FORMA_ZERO_DAYS = float(os.environ.get('NOT_COVERED_O_FORMA_ZERO_DAYS', '30'))
NESSUNA_PARTITA_DAYS = float(os.environ.get('NESSUNA_PARTITA_DAYS', '3'))

_lista_nera_lock = threading.Lock()
_lista_nera_cache = None  # dict: slug -> datetime scadenza (solo voci ancora valide)


def _lista_nera_leggi():
    global _lista_nera_cache
    with _lista_nera_lock:
        if _lista_nera_cache is not None:
            return _lista_nera_cache
        cache = {}
        if os.path.exists(LISTA_NERA_PROFIT_PATH):
            with open(LISTA_NERA_PROFIT_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(',')
                    if len(parts) != 3:
                        continue
                    _tipo, slug, scadenza_iso = parts
                    try:
                        scadenza = datetime.datetime.fromisoformat(scadenza_iso)
                    except ValueError:
                        continue
                    esistente = cache.get(slug)
                    if esistente is None or scadenza > esistente:
                        cache[slug] = scadenza
        _lista_nera_cache = cache
        return cache


def is_player_blacklisted(player_slug):
    cache = _lista_nera_leggi()
    scadenza = cache.get(player_slug)
    if scadenza is None:
        return False
    now = datetime.datetime.now(scadenza.tzinfo) if scadenza.tzinfo else datetime.datetime.now()
    return now < scadenza


def blacklist_player(player_slug, motivo, giorni):
    global _lista_nera_cache
    with _lista_nera_lock:
        scadenza = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=giorni)
        with open(LISTA_NERA_PROFIT_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{motivo},{player_slug},{scadenza.isoformat()}\n")
        if _lista_nera_cache is not None:
            esistente = _lista_nera_cache.get(player_slug)
            if esistente is None or scadenza > esistente:
                _lista_nera_cache[player_slug] = scadenza


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [bot_profit] {message}", flush=True)


# =====================================================================================
# UTILITY DI RETE -- identiche a Bot Supremo (prezzo multi-valuta, tasso ETH, GraphQL)
# =====================================================================================
_FIAT_RATE_CACHE = {}


def get_eth_rate():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur",
            timeout=5
        )
        return float(r.json()['ethereum']['eur'])
    except Exception:
        return 3000.0


def get_usd_eur_rate():
    if 'usd' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['usd']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 0.92
    _FIAT_RATE_CACHE['usd'] = rate
    return rate


def get_gbp_eur_rate():
    if 'gbp' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['gbp']
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=GBP&to=EUR", timeout=5)
        rate = float(r.json()['rates']['EUR'])
    except Exception:
        rate = 1.17
    _FIAT_RATE_CACHE['gbp'] = rate
    return rate


def get_sol_eur_rate():
    if 'sol' in _FIAT_RATE_CACHE:
        return _FIAT_RATE_CACHE['sol']
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur",
            timeout=5
        )
        rate = float(r.json()['solana']['eur'])
    except Exception:
        rate = 150.0
    _FIAT_RATE_CACHE['sol'] = rate
    return rate


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
    if amounts.get('usdCents') is not None:
        try:
            return amounts['usdCents'] / 100 * get_usd_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('gbpCents') is not None:
        try:
            return amounts['gbpCents'] / 100 * get_gbp_eur_rate()
        except (TypeError, ValueError):
            return None
    if amounts.get('lamport') is not None:
        try:
            return float(amounts['lamport']) / 1e9 * get_sol_eur_rate()
        except (TypeError, ValueError):
            return None
    return None


# FIX 27/07 (richiesta esplicita utente, 423 HTTP 429 su ~1300-1500 richieste
# nell'ultima run -- ~30% finite in retry con backoff): alzato da 0.15 a 0.25s.
# Ritmo base piu' lento ma meno 429 = meno tempo perso nei backoff (2s/4s/8s
# per tentativo) e meno finestre di 45s a ritmo SAFE (0.6s) dopo ogni 429.
#
# FIX 29/07 (richiesta esplicita utente: priorita' e' accorciare la durata
# della run, un po' di 429 in piu' sono accettabili): la run del 27/07 ha
# mostrato 2 minuti filati di 429 anche a ritmo SAFE 0.6s -- il ritmo "sicuro"
# non evitava comunque i 429 durante una finestra di penalita' sostenuta, quindi
# non ha senso pagarne il costo pieno in throughput.
#
# Primo tentativo (FAST=0.15/SAFE=0.3/cooldown=20/backoff dimezzato): 4m30-4m54s
# ma 140+ giocatori scartati per retry esauriti (contro i 69 originali) --
# troppo, l'utente ha chiesto un compromesso (5-6 min, non 10, ma senza perdere
# cosi' tante carte). La causa principale era il BACKOFF dimezzato (2/4/8s
# invece di 2/4/16s): dava alle richieste meno margine per "aspettare che
# passi" il rate-limit prima di rinunciare al 3o tentativo. Backoff ripristinato
# all'originale (piu' importante per la sopravvivenza dei retry del ritmo
# stesso), ritmo base/safe/cooldown solo moderatamente piu' veloci
# dell'originale (non quanto il primo tentativo) per restare nella fascia
# 5-6 min richiesta.
# FIX 29/07 ter (richiesta esplicita utente) PROVATO E SMENTITO: l'ipotesi era
# che, col secondo giro dedicato a recuperare i rate-limited, un ritmo piu'
# aggressivo nel primo giro (0.12s/0.25s/20s) avrebbe risparmiato tempo netto
# visto che il paracadute del retry copre le perdite. Risultato reale: 6m03s,
# PEGGIO del 5m14s del ritmo precedente -- 112 giocatori finiti nel pool di
# retry (contro 12) hanno speso ciascuno fino a 2+4+16=22s di backoff nel
# primo giro PRIMA di arrendersi, un costo che supera il guadagno di ritmo.
# Ripristinato il compromesso precedente (0.2s/0.45s/30s), che resta il
# miglior punto trovato finora (5m14s-5m28s, ~70 rate-limited di cui 0
# persistenti dopo il secondo giro).
GRAPHQL_MIN_INTERVAL_SECONDS_FAST = float(os.environ.get('GRAPHQL_MIN_INTERVAL_SECONDS_FAST', '0.2'))
GRAPHQL_MIN_INTERVAL_SECONDS_SAFE = float(os.environ.get('GRAPHQL_MIN_INTERVAL_SECONDS_SAFE', '0.45'))
GRAPHQL_429_COOLDOWN_SECONDS = float(os.environ.get('GRAPHQL_429_COOLDOWN_SECONDS', '30.0'))
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]
_graphql_last_429_ts = [0.0]

# ESPERIMENTO 29/07 (richiesta esplicita utente, osservazione su un log reale):
# nella run delle 07:35 il primo 429 e' scattato solo dopo ~1m39s e ~250
# giocatori analizzati SENZA NESSUN 429 -- poi, una volta scattato, e' stata
# sostanzialmente una raffica ininterrotta. Ipotesi testata: Sorare non limita
# per "ritmo istantaneo" ma per QUANTITA' di richieste in una finestra
# scorrevole -- una pausa fissa periodica (60s lavoro / 20s pausa,
# indipendente dai 429) avrebbe dovuto "svuotare" quella finestra prima che
# scattasse. RISULTATO: SMENTITA (con 20s di pausa). Run di verifica
# (07:52-07:54): primo 429 scattato comunque a ~2 minuti dall'inizio, stesso
# punto della run senza pausa.
#
# ESPERIMENTO 29/07 quater (richiesta esplicita utente, test A/B tra due run
# GitHub Actions reali e indipendenti sullo stesso branch): Run A (15 squadre
# MLS) primo 429 a 2m56s dall'avvio; Run A cancellata; Run B (altre 15 squadre
# MLS, stesso account/cookie Sorare) lanciata SOLO 45s dopo la fine di Run A --
# primo 429 di Run B a 2m42s dal SUO avvio, praticamente identico a Run A.
# Conclusione: il limite NON e' un conto cumulativo sull'account che si
# esaurisce e basta (altrimenti Run B avrebbe dovuto sbattere subito) -- si
# RICARICA in appena ~45s di inattivita' verso l'API. La pausa di 20s
# dell'esperimento precedente era quindi probabilmente troppo breve per
# ricaricare la finestra, non uno smentita della logica "pausa periodica" in
# se'. Riprovato con pausa piu' lunga (default ora ATTIVO): lavoro
# GRAPHQL_BURST_WORK_SECONDS=150s (margine di sicurezza sotto i ~2m45-2m56s
# osservati prima del muro) seguito da GRAPHQL_BURST_PAUSE_SECONDS=60s (oltre
# i 45s che si sono dimostrati sufficienti nel test A/B) -- da verificare con
# una run reale prima di considerarlo risolto.
GRAPHQL_BURST_WORK_SECONDS = float(os.environ.get('GRAPHQL_BURST_WORK_SECONDS', '150.0'))
GRAPHQL_BURST_PAUSE_SECONDS = float(os.environ.get('GRAPHQL_BURST_PAUSE_SECONDS', '60.0'))
_burst_window_start = [None]
_burst_paused_until = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        pause_remaining = 0.0
        if GRAPHQL_BURST_WORK_SECONDS > 0:
            if _burst_window_start[0] is None:
                _burst_window_start[0] = now
            if now < _burst_paused_until[0]:
                pause_remaining = _burst_paused_until[0] - now
            elif now - _burst_window_start[0] >= GRAPHQL_BURST_WORK_SECONDS:
                _burst_paused_until[0] = now + GRAPHQL_BURST_PAUSE_SECONDS
                _burst_window_start[0] = _burst_paused_until[0]
                pause_remaining = GRAPHQL_BURST_PAUSE_SECONDS
                log(f"[burst] {GRAPHQL_BURST_WORK_SECONDS:.0f}s di lavoro completati, "
                    f"pausa fissa di {GRAPHQL_BURST_PAUSE_SECONDS:.0f}s...")
        recent_429 = (now - _graphql_last_429_ts[0]) < GRAPHQL_429_COOLDOWN_SECONDS
        min_interval = GRAPHQL_MIN_INTERVAL_SECONDS_SAFE if recent_429 else GRAPHQL_MIN_INTERVAL_SECONDS_FAST
        wait = min_interval - (now - _graphql_last_call_ts[0])
        total_wait = max(wait, 0.0) + pause_remaining
        if total_wait > 0:
            time.sleep(total_wait)
        _graphql_last_call_ts[0] = time.time()


def graphql_query(query, variables=None, max_retries=3):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get(
            'SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if SORARE_DEVICE_FINGERPRINT:
        headers['device_fingerprint'] = SORARE_DEVICE_FINGERPRINT
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        _graphql_throttle()
        r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            _graphql_last_429_ts[0] = time.time()
            # FIX 29/07 bis: backoff dimezzato (2/4/8s) provato e SCARTATO --
            # ha piu' che raddoppiato i giocatori persi per retry esauriti
            # (69 -> 140+) a fronte di un risparmio di tempo minimo (~25%).
            # Ripristinato l'originale: il backoff lungo da' al retry il tempo
            # di uscire dalla finestra di penalita' prima di rinunciare.
            wait_seconds = min((2 ** attempt) * 2, 16.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


def is_excluded_league(league_slug):
    """MLS/K-League: in_season e classic sono due mercati separati."""
    return league_slug in EXCLUDED_LEAGUE_SLUGS


# =====================================================================================
# QUERY: roster completo di una squadra (modalita' SNAPSHOT) -- query pubblica,
# nessuno scope utente richiesto. Stesso pattern di
# formazione_mls/discovery/mls_mid_discovery_global.py (TeamRoster/anyPlayers).
# =====================================================================================
TEAM_ROSTER_QUERY = """
query TeamRoster($slug: String!, $first: Int!, $after: String) {
  football {
    club(slug: $slug) {
      slug
      name
      anyPlayers(first: $first, after: $after) {
        nodes {
          slug
          displayName
          activeClub { slug name }
          lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
          lastTenAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
          lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

TEAM_ROSTER_PAGE_SIZE = 100
TEAM_ROSTER_MAX_PAGES = 10  # tetto di sicurezza (fino a 1000 giocatori/squadra)


def fetch_team_roster(team_slug, page_size=TEAM_ROSTER_PAGE_SIZE):
    """FIX 26/07 (bug segnalato dall'utente confrontando col roster reale di una
    partita): anyPlayers(first: 50) SENZA paginazione tagliava fuori giocatori
    attuali della rosa (restituisce a quanto pare TUTTI i giocatori mai passati
    per il club, non solo quelli attuali, e l'ordine non e' legato all'attualita').
    Ora pagina finche' hasNextPage=false o il tetto di sicurezza, cosi' prendiamo
    l'intera lista.

    FIX 26/07 bis (richiesta esplicita utente, velocizzare): activeClub.slug
    (stesso campo gia' usato/verificato in PROFIT_PLAYER_DATA_QUERY) viene
    richiesto GIA' qui, cosi' scartiamo gli ex-giocatori SUBITO -- zero query
    aggiuntive sprecate su di loro nel ciclo principale (niente snapshot,
    niente controllo blacklist), invece di scoprirlo solo dopo la fetch dello
    snapshot in _process_player_snapshot.

    FIX 26/07 ter (richiesta esplicita utente, ridurre il campione da 952 a
    ~400 su tutta la MLS -- causa diretta dei 429 nel run precedente): stesso
    principio applicato all'L5, gia' incluso in QUESTA query (1 query per
    squadra, non per giocatore) -- chi ha L5 assente/zero viene scartato QUI,
    PRIMA di spendere snapshot/minimo/transazioni (le query davvero costose,
    fino a ~9 per giocatore). Stesso identico criterio gia' usato in
    _process_player_snapshot (L5 assente o 0 = 'forma_zero'), solo spostato
    a monte per non pagarne il costo query.

    FIX 26/07 quater (richiesta esplicita utente, il filtro L5 da solo non ha
    tagliato abbastanza -- 645 giocatori restanti, run da 28 minuti con 43
    429 falliti): aggiunto anche L10 <= ROSTER_MIN_AVG_SCORE (default 35.0)
    come scarto, stesso principio -- gia' disponibile in QUESTA query.

    FIX 27/07 (richiesta esplicita utente): stessa soglia estesa anche a L5 e
    L40 (prima L5 scartava solo se assente/zero) -- ora tutte e tre le medie
    (L5, L10, L40) devono superare ROSTER_MIN_AVG_SCORE, non solo L10.

    FIX 27/07 bis (richiesta esplicita utente, ridurre il numero di query verso
    Sorare): un primo tentativo di accorpare PROFIT_PLAYER_DATA_QUERY con alias
    GraphQL (piu' 'anyPlayer(slug: ...)' nella stessa richiesta) e' stato
    RIFIUTATO dal server Sorare con errore 'Duplicated root field: anyPlayer'
    su ogni batch (verificato con un run reale) -- niente aliasing di campi
    radice ripetuti, a differenza di quanto permette lo standard GraphQL.

    CORREZIONE 27/07 (run reale 30306125200, TUTTE le 30 squadre MLS a 0
    giocatori): il FIX 27/07 ter precedente affermava che annidare
    allPlayerGameScores (ultima partita) dentro questa query di roster
    funzionasse -- MAI verificato su una run reale successiva, e in realta'
    Sorare rifiuta anche questo campo con lo stesso identico errore gia' visto
    per anyFutureGames: 'Selecting allPlayerGameScores within a list of
    AnyPlayerInterface (anyPlayers) is not supported, please select
    allPlayerGameScores for a specific AnyPlayerInterface instead.' Rimosso da
    QUESTA query -- ultima partita ora fetchata per-giocatore assieme a prezzo,
    prossima partita e transazioni in un'unica query combinata (vedi
    fetch_player_combined_snapshot, FIX 27/07 quater) -- nessuno di questi e'
    annidabile dentro una lista anyPlayers per limite esplicito dello schema
    Sorare."""
    all_nodes = []
    cursor = None
    for _ in range(TEAM_ROSTER_MAX_PAGES):
        data = graphql_query(TEAM_ROSTER_QUERY, {"slug": team_slug, "first": page_size, "after": cursor})
        if data.get('errors'):
            log(f"[roster] errore GraphQL per {team_slug}: {data['errors']}")
            break
        club = ((data.get('data') or {}).get('football') or {}).get('club')
        if not club:
            if not all_nodes:
                log(f"[roster] ATTENZIONE: nessun dato club restituito per {team_slug}.")
            break
        conn = club.get('anyPlayers') or {}
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')
        if not cursor:
            break

    roster_completo = [(n['slug'], n.get('displayName') or n['slug']) for n in all_nodes if n.get('slug')]
    roster_attuale = [
        n for n in all_nodes
        if n.get('slug') and (n.get('activeClub') or {}).get('slug') == team_slug
    ]
    roster_nodi = [
        n for n in roster_attuale
        if (n.get('lastFiveAvgScore') or 0) > ROSTER_MIN_AVG_SCORE
        and (n.get('lastTenAvgScore') or 0) > ROSTER_MIN_AVG_SCORE
        and (n.get('lastFortyAvgScore') or 0) > ROSTER_MIN_AVG_SCORE
    ]
    roster = [(n['slug'], n.get('displayName') or n['slug'], _parse_player_snapshot_node(n)) for n in roster_nodi]

    scartati_ex = len(roster_completo) - len(roster_attuale)
    scartati_media_bassa = len(roster_attuale) - len(roster_nodi)
    log(f"[roster] {team_slug}: {len(roster_completo)} giocatori totali nel roster storico, "
        f"{scartati_ex} scartati subito (non piu' al club), {scartati_media_bassa} scartati per "
        f"L5/L10/L40 <= {ROSTER_MIN_AVG_SCORE} (una qualsiasi), {len(roster)} rilevanti da processare.")
    return roster


# =====================================================================================
# QUERY: annunci live del giocatore -- per il MINIMO attuale (identica a Bot Supremo)
# =====================================================================================
LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      pageInfo { hasPreviousPage startCursor }
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

LIVE_OFFERS_PAGE_SIZE = 50
LIVE_OFFERS_MAX_PAGES = 2


def fetch_all_live_offers(player_slug):
    all_nodes = []
    cursor = None
    for _ in range(LIVE_OFFERS_MAX_PAGES):
        data = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": LIVE_OFFERS_PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[minimo attuale] errore paginazione per {player_slug}: {data['errors']}")
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


def _current_minimum_from_nodes(nodes, is_in_season, league_slug, eth_rate):
    """Nucleo di filtro condiviso, fattorizzato (FIX 27/07) da get_current_minimum
    per poter riusare GLI STESSI nodi live-offers gia' scaricati sia per il ramo
    in_season sia per quello classic nel giro snapshot, invece di richiamare
    fetch_all_live_offers() due volte per lo stesso giocatore (dimezza le
    richieste di rete per questa parte, indipendentemente dalla concorrenza)."""
    excluded = is_excluded_league(league_slug)
    prices_in_season = []
    prices_classic = []
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited' or c.get('sport') != 'FOOTBALL':
                continue
            match = c
            break
        if not match:
            continue
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            continue
        if match.get('inSeasonEligible'):
            prices_in_season.append(price)
        else:
            prices_classic.append(price)
    if excluded:
        candidates = prices_in_season if is_in_season else prices_classic
    else:
        candidates = prices_in_season + prices_classic
    return min(candidates) if candidates else None


def get_current_minimum(player_slug, is_in_season, league_slug, eth_rate):
    """Minimo attuale in vendita.
    - MLS/K-League: SOLO il tipo (in_season o classic) corrispondente alla carta
      dell'evento -- i due mercati non si toccano mai.
    - Tutti gli altri campionati: in_season+classic mescolati (stesso identico
      criterio di Bot Supremo -- un giocatore, un solo mercato)."""
    nodes = fetch_all_live_offers(player_slug)
    return _current_minimum_from_nodes(nodes, is_in_season, league_slug, eth_rate)


# =====================================================================================
# QUERY: ultime transazioni REALI in una FINESTRA di TRANSACTIONS_WINDOW_DAYS giorni
# (paginata -- stesso campo/pattern confermato funzionante di Bot Supremo)
# =====================================================================================
TRANSACTIONS_QUERY = """
query RecentTransactionsQuery($p: String!, $n: Int!, $cursor: String) {
  anyPlayer(slug: $p) {
    tokenPrices(rarity: limited, last: $n, before: $cursor) {
      nodes {
        date
        deal { __typename ... on TokenOffer { type } }
        card { inSeasonEligible }
        amounts { eurCents wei usdCents gbpCents lamport }
      }
      pageInfo { hasPreviousPage startCursor }
    }
  }
}
"""


def _is_countable_transaction(node):
    # Aste (TokenAuction) e acquisti diretti dalla riserva di Sorare (TokenPrimaryOffer, seller
    # sempre null -- verificato su dati reali 26/07: "Acquisto istantaneo" con seller=null e'
    # sempre TokenPrimaryOffer) escluse dalla media -- entrambi prezzi non di mercato tra
    # manager (aste per meccaniche di gioco, primary offer perche' non c'e' un venditore reale).
    # Restano solo le transazioni TokenOffer (Scambio/Offerta diretta), che hanno sempre 'type'.
    deal = node.get('deal') or {}
    return bool(deal.get('type'))


def fetch_transaction_nodes_window(player_slug):
    """Pagina le transazioni finche' il nodo piu' vecchio della pagina esce dalla
    finestra TRANSACTIONS_WINDOW_DAYS, o finisce le pagine/il limite di sicurezza."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=TRANSACTIONS_WINDOW_DAYS)
    all_nodes = []
    cursor = None
    for _ in range(TRANSACTIONS_MAX_PAGES):
        data = graphql_query(TRANSACTIONS_QUERY, {"p": player_slug, "n": TRANSACTIONS_PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[transazioni {TRANSACTIONS_WINDOW_DAYS}gg] errore paginazione per {player_slug}: {data['errors']}")
            break
        conn = ((data.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        oldest_date_str = nodes[-1].get('date') if nodes else None
        if not nodes:
            break
        try:
            oldest_dt = datetime.datetime.fromisoformat((oldest_date_str or '').replace('Z', '+00:00'))
            if oldest_dt < cutoff:
                break
        except (ValueError, AttributeError):
            pass
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes, cutoff


def _countable_transactions_from_nodes(nodes, cutoff, is_in_season, league_slug, eth_rate):
    """Nucleo di filtro condiviso, fattorizzato (FIX 27/07) da
    _fetch_countable_transactions per poter riusare GLI STESSI nodi transazione
    gia' paginati sia per il ramo in_season sia per quello classic nel giro
    snapshot, invece di richiamare fetch_transaction_nodes_window() due volte
    per lo stesso giocatore (dimezza le richieste di rete per questa parte)."""
    excluded = is_excluded_league(league_slug)
    out = []
    for node in nodes:
        date_str = node.get('date') or ''
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        if dt < cutoff:
            continue
        if excluded:
            card = node.get('card') or {}
            if bool(card.get('inSeasonEligible')) != is_in_season:
                continue
        if not _is_countable_transaction(node):
            continue
        price = eur_price_from_amounts(node.get('amounts'), eth_rate)
        if price is not None:
            out.append((dt, price))
    return out


def _fetch_countable_transactions(player_slug, is_in_season, league_slug, eth_rate):
    """Nucleo condiviso: transazioni reali (stesso filtro di sempre) con data E
    prezzo, negli ultimi TRANSACTIONS_WINDOW_DAYS giorni. Fattorizzato (FIX 26/07,
    richiesta esplicita utente) per riusare la STESSA query/filtro sia per la
    media prezzi sia per il pattern giorni-da-partita, senza raddoppiare le
    query GraphQL per carta."""
    nodes, cutoff = fetch_transaction_nodes_window(player_slug)
    return _countable_transactions_from_nodes(nodes, cutoff, is_in_season, league_slug, eth_rate)


def get_recent_transaction_prices(player_slug, is_in_season, league_slug, eth_rate):
    """Prezzi (EUR) delle transazioni reali negli ultimi TRANSACTIONS_WINDOW_DAYS
    giorni. MLS/K-League: solo lo stesso tipo (in_season/classic) della riga;
    altri campionati: mescolati (stesso criterio del minimo attuale)."""
    return [price for _, price in _fetch_countable_transactions(player_slug, is_in_season, league_slug, eth_rate)]


def giorni_da_partita_piu_vicina(dt, match_date_strs):
    """Distanza in giorni (con segno: negativo = prima della partita, positivo =
    dopo) tra dt e la partita piu' vicina nell'elenco date passato (mix di
    passate/future). None se non c'e' nessuna data valida. Richiesta esplicita
    utente 26/07: capire il pattern prezzo/distanza-da-partita nell'arco della
    settimana (non giorno-di-calendario, perche' ogni squadra gioca in giorni
    diversi)."""
    best = None
    for date_str in match_date_strs:
        if not date_str:
            continue
        try:
            match_dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        delta_days = (dt - match_dt).total_seconds() / 86400.0
        if best is None or abs(delta_days) < abs(best):
            best = delta_days
    return best


# =====================================================================================
# QUERY: medie voto (L5/L10/L40), punteggio ULTIMA partita giocata, prossima partita
# =====================================================================================
PROFIT_PLAYER_DATA_QUERY = """
query ProfitPlayerData($slug: String!) {
  anyPlayer(slug: $slug) {
    slug
    displayName
    activeClub {
      ... on Club { slug name }
    }
    lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
    lastTenAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
    anyFutureGames(first: 1) {
      nodes {
        date
        homeTeam { ... on Club { slug name } }
        awayTeam { ... on Club { slug name } }
      }
    }
    allPlayerGameScores(first: 3) {
      nodes {
        score
        scoreStatus
        anyGame { date }
      }
    }
  }
}
"""


def _parse_player_snapshot_node(player):
    """Nucleo di parsing condiviso (FIX 27/07 bis): estrae lo stesso identico
    snapshot sia dal ramo anyPlayer singolo (get_player_snapshot, usato da
    run_listener evento-per-evento) sia da un nodo del roster per squadra
    (fetch_team_roster/TEAM_ROSTER_QUERY, usato da run_snapshot_sweep, dove
    gli stessi campi sono annidati dentro club.anyPlayers) -- stessa forma di
    ritorno in entrambi i casi."""
    if not player:
        return None

    l5 = player.get('lastFiveAvgScore')
    l10 = player.get('lastTenAvgScore')
    l40 = player.get('lastFortyAvgScore')

    squadra = (player.get('activeClub') or {}).get('name')
    squadra_slug = (player.get('activeClub') or {}).get('slug')

    future_nodes = ((player.get('anyFutureGames') or {}).get('nodes')) or []
    next_game_date_str = None
    prossimo_avversario = None
    if future_nodes:
        next_game = future_nodes[0]
        next_game_date_str = next_game.get('date')
        home = next_game.get('homeTeam') or {}
        away = next_game.get('awayTeam') or {}
        if squadra_slug and home.get('slug') == squadra_slug:
            prossimo_avversario = f"{away.get('name', '?')} (casa)"
        elif squadra_slug and away.get('slug') == squadra_slug:
            prossimo_avversario = f"{home.get('name', '?')} (trasferta)"
        elif home.get('name') or away.get('name'):
            prossimo_avversario = f"{home.get('name', '?')} vs {away.get('name', '?')}"

    last_game_nodes = ((player.get('allPlayerGameScores') or {}).get('nodes')) or []
    ultima_partita_score = last_game_nodes[0].get('score') if last_game_nodes else None
    past_game_dates = [
        (n.get('anyGame') or {}).get('date') for n in last_game_nodes if (n.get('anyGame') or {}).get('date')
    ]
    match_dates = past_game_dates + ([next_game_date_str] if next_game_date_str else [])

    return {
        'l5': l5,
        'l10': l10,
        'l40': l40,
        'squadra': squadra,
        'squadra_slug': squadra_slug,
        'prossimo_avversario': prossimo_avversario,
        'next_game_date_str': next_game_date_str,
        'ultima_partita_score': ultima_partita_score,
        'match_dates': match_dates,
    }


def get_player_snapshot(player_slug):
    """Medie voto, prossima partita, punteggio dell'ULTIMA partita giocata (peso
    maggiore secondo l'esperienza utente -- un 70+ nell'ultima gara spinge il
    prezzo piu' in alto di un L5 alto ma con l'ultima gara sottotono). Ritorna
    anche match_dates: date passate (fino a 3) + prossima, per il pattern
    prezzo/distanza-da-partita (richiesta esplicita utente 26/07).
    Usata SOLO da run_listener (un giocatore alla volta, arrivano da eventi
    live) -- il giro snapshot (run_snapshot_sweep) prende L5/L10/L40 dal
    roster (fetch_team_roster/TEAM_ROSTER_QUERY) e il resto (prezzo, prossima/
    ultima partita, transazioni) in un'unica query combinata per giocatore
    (fetch_player_combined_snapshot, FIX 27/07 quater)."""
    data = graphql_query(PROFIT_PLAYER_DATA_QUERY, {"slug": player_slug})
    if data.get('errors'):
        log(f"[snapshot] errore GraphQL per {player_slug}: {data['errors']}")
        return None
    player = ((data.get('data') or {}).get('anyPlayer')) or {}
    return _parse_player_snapshot_node(player)


COMBINED_PLAYER_SNAPSHOT_QUERY = """
query PlayerCombinedSnapshot($slug: String!, $liveN: Int!, $liveCursor: String, $txN: Int!, $txCursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $liveN, before: $liveCursor) {
      pageInfo { hasPreviousPage startCursor }
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
  anyPlayer(slug: $slug) {
    activeClub { ... on Club { slug name } }
    anyFutureGames(first: 1) {
      nodes {
        date
        homeTeam { ... on Club { slug name } }
        awayTeam { ... on Club { slug name } }
      }
    }
    allPlayerGameScores(first: 3) {
      nodes {
        score
        scoreStatus
        anyGame { date }
      }
    }
    tokenPrices(rarity: limited, last: $txN, before: $txCursor) {
      nodes {
        date
        deal { __typename ... on TokenOffer { type } }
        card { inSeasonEligible }
        amounts { eurCents wei usdCents gbpCents lamport }
      }
      pageInfo { hasPreviousPage startCursor }
    }
  }
}
"""


def _oldest_transaction_before_cutoff(nodes, cutoff):
    if not nodes:
        return False
    try:
        oldest_dt = datetime.datetime.fromisoformat((nodes[-1].get('date') or '').replace('Z', '+00:00'))
        return oldest_dt < cutoff
    except (ValueError, AttributeError):
        return False


def fetch_player_combined_snapshot(player_slug):
    """FIX 27/07 quater (richiesta esplicita utente: troppi HTTP 429, ottimizzare
    accorpando le query invece di alzare la concorrenza): prezzo (live offers),
    prossima/ultima partita E prima pagina di transazioni in UNA SOLA richiesta,
    al posto di 3 round-trip separati (fetch_all_live_offers + il vecchio
    fetch_player_next_game + fetch_transaction_nodes_window) -- root fields
    diversi (tokens/anyPlayer) sullo STESSO slug in una query, cosa diversa dal
    tentativo gia' rifiutato da Sorare ('Duplicated root field: anyPlayer') che
    riguardava PIU' slug differenti aliasati nella stessa query. Taglia le
    query per-giocatore da fino a 3 a 1 nel caso comune (nessuna carta con
    volume di annunci/transazioni cosi' alto da superare una pagina), riducendo
    sensibilmente sia il tempo totale sia gli HTTP 429. La paginazione oltre la
    prima pagina (rara, solo carte molto liquide) continua con richieste
    aggiuntive dedicate, come nelle funzioni precedenti."""
    data = graphql_query(COMBINED_PLAYER_SNAPSHOT_QUERY, {
        "slug": player_slug, "liveN": LIVE_OFFERS_PAGE_SIZE, "liveCursor": None,
        "txN": TRANSACTIONS_PAGE_SIZE, "txCursor": None,
    })
    if data.get('errors'):
        log(f"[combined snapshot] errore GraphQL per {player_slug}: {data['errors']}")
        # FIX 29/07 (richiesta esplicita utente): distinguere un errore (quasi
        # sempre rate_limited_max_retries_exceeded) da un "davvero nessuna
        # offerta/dato" -- prima venivano confusi (entrambi tornavano liste
        # vuote), un giocatore rate-limitato finiva silenziosamente
        # scartato come 'prezzo_basso_o_senza_annunci', indistinguibile da chi
        # non aveva davvero annunci. L'ultimo elemento (errored=True) permette
        # di isolare questi casi per un secondo giro dedicato (vedi
        # run_snapshot_sweep) invece di perderli senza appello.
        return [], None, None, None, [], [], None, True

    root = data.get('data') or {}

    live_conn = ((root.get('tokens') or {}).get('liveSingleSaleOffers')) or {}
    live_nodes = live_conn.get('nodes') or []
    live_page_info = live_conn.get('pageInfo') or {}
    if live_page_info.get('hasPreviousPage'):
        cursor = live_page_info.get('startCursor')
        for _ in range(LIVE_OFFERS_MAX_PAGES - 1):
            if not cursor:
                break
            more = graphql_query(LIVE_OFFERS_QUERY, {"slug": player_slug, "n": LIVE_OFFERS_PAGE_SIZE, "cursor": cursor})
            if more.get('errors'):
                break
            conn = (((more.get('data') or {}).get('tokens') or {}).get('liveSingleSaleOffers')) or {}
            nodes = conn.get('nodes') or []
            live_nodes.extend(nodes)
            page_info = conn.get('pageInfo') or {}
            if not page_info.get('hasPreviousPage'):
                break
            cursor = page_info.get('startCursor')

    player = root.get('anyPlayer') or {}
    squadra_slug = (player.get('activeClub') or {}).get('slug')

    future_nodes = ((player.get('anyFutureGames') or {}).get('nodes')) or []
    next_game_date_str = None
    prossimo_avversario = None
    if future_nodes:
        next_game = future_nodes[0]
        next_game_date_str = next_game.get('date')
        home = next_game.get('homeTeam') or {}
        away = next_game.get('awayTeam') or {}
        if squadra_slug and home.get('slug') == squadra_slug:
            prossimo_avversario = f"{away.get('name', '?')} (casa)"
        elif squadra_slug and away.get('slug') == squadra_slug:
            prossimo_avversario = f"{home.get('name', '?')} (trasferta)"
        elif home.get('name') or away.get('name'):
            prossimo_avversario = f"{home.get('name', '?')} vs {away.get('name', '?')}"

    last_game_nodes = ((player.get('allPlayerGameScores') or {}).get('nodes')) or []
    ultima_partita_score = last_game_nodes[0].get('score') if last_game_nodes else None
    past_game_dates = [
        (n.get('anyGame') or {}).get('date') for n in last_game_nodes if (n.get('anyGame') or {}).get('date')
    ]

    tx_conn = player.get('tokenPrices') or {}
    tx_nodes = tx_conn.get('nodes') or []
    tx_page_info = tx_conn.get('pageInfo') or {}
    tx_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=TRANSACTIONS_WINDOW_DAYS)
    if tx_nodes and not _oldest_transaction_before_cutoff(tx_nodes, tx_cutoff) and tx_page_info.get('hasPreviousPage'):
        cursor = tx_page_info.get('startCursor')
        for _ in range(TRANSACTIONS_MAX_PAGES - 1):
            if not cursor:
                break
            more = graphql_query(TRANSACTIONS_QUERY, {"p": player_slug, "n": TRANSACTIONS_PAGE_SIZE, "cursor": cursor})
            if more.get('errors'):
                break
            conn = ((more.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}
            nodes = conn.get('nodes') or []
            tx_nodes.extend(nodes)
            page_info = conn.get('pageInfo') or {}
            if _oldest_transaction_before_cutoff(nodes, tx_cutoff) or not page_info.get('hasPreviousPage'):
                break
            cursor = page_info.get('startCursor')

    return (live_nodes, next_game_date_str, prossimo_avversario, ultima_partita_score,
            past_game_dates, tx_nodes, tx_cutoff, False)


def trimmed_average(prices):
    """Media transazioni escludendo il valore piu' basso e piu' alto. Se ci sono
    meno di 3 valori, niente trim, media semplice su quello che c'e'."""
    n_totali = len(prices)
    if n_totali == 0:
        return None, 0, 0
    if n_totali < 3:
        return sum(prices) / n_totali, n_totali, n_totali
    ordered = sorted(prices)
    trimmed = ordered[1:-1]
    return sum(trimmed) / len(trimmed), len(trimmed), n_totali


def hours_until(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = dt - now
    return delta.total_seconds() / 3600.0


# =====================================================================================
# POTENZIALE SCORE (formula concordata 24/07, pesi ripesati 27/07, riequilibrati
# di nuovo 29/07 ter -- richiesta esplicita utente) -- 4 fattori, nessun peso su
# n_transazioni oltre a quanto segue (resta comunque in colonna solo per
# valutazione finale manuale):
#   0.40 x peso_timing (prossimita' partita, 3 bucket ricalibrati 27/07 sui
#         dati reali di pattern_giorni_da_partita.csv) -- alzato da 0.35
#         (FIX 29/07 ter, richiesta esplicita utente: piu' peso a timing/sconto,
#         meno a ultima_partita/forma generale)
#   0.15 x ultima_partita/100 (prestazione ULTIMA gara secca, non L5) --
#         abbassato da 0.20 (FIX 29/07 ter)
#   0.10 x media_generale (0.5*L5 + 0.3*L10 + 0.2*L40)/100 -- pesi decrescenti
#         (FIX 27/07, richiesta esplicita utente): prima era una media piatta
#         (L5+L10+L40)/3, incoerente col fatto che L5 riflette la forma PIU'
#         recente e deve pesare di piu' di L40 (che include partite di mesi fa).
#         Abbassato da 0.15 (FIX 29/07 ter)
#   0.35 x sconto_normalizzato (sconto% clampato [-30,100] / 100) -- alzato da
#         0.30 (FIX 29/07 ter, richiesta esplicita utente)
# =====================================================================================
TIMING_WEIGHT_BUCKETS = (
    # (soglia_ore_esclusiva, peso) -- controllate in ordine, la prima che
    # soddisfa ore < soglia vince. Ricalibrati 27/07 su dati reali
    # (pattern_giorni_da_partita.csv, run full-MLS 30201147701, migliaia di
    # campioni): <48h e 48-96h mostravano pesi diversi (0.1/0.3) ma
    # scostamento reale IDENTICO (+3.9%/+4.0%, nessuno sconto) -> unificati.
    # 48-96h prima resta il picco di sconto reale (-9.3%/-15.9%). Oltre le
    # 96h i dati sono troppo scarsi (11 campioni a -4gg, zero oltre) per
    # giustificare un peso alto: ridotto a 0.3, prudente invece che assunto.
    (48, 0.1),
    (96, 1.0),
    (float('inf'), 0.3),
)


def timing_weight(ore_alla_partita):
    if ore_alla_partita is None:
        return 0.0
    for soglia, peso in TIMING_WEIGHT_BUCKETS:
        if ore_alla_partita < soglia:
            return peso
    return TIMING_WEIGHT_BUCKETS[-1][1]


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


# Moltiplicatore di affidabilita' del trend_recente sullo sconto_percent --
# stessa euristica gia' validata lato-viewer nel bottone Top 5 (29/07: promossa
# a formula ufficiale su richiesta esplicita utente, dopo essere rimasta solo
# visiva per una sessione). 'down' = sconto sospetto (mercato in caduta,
# probabile inseguimento di un calo, non una vera occasione) -> penalizzato
# forte; 'up' = sconto affidabile (mercato in salita) -> premiato; 'flat' =
# nessuna correzione; mancante (storico insufficiente per lo split 2gg/7gg) =
# leggera cautela.
TREND_SCORE_MULTIPLIER = {'up': 1.2, 'flat': 1.0, 'down': 0.5, None: 0.8}

# FIX 29/07 (richiesta esplicita utente, caso reale Nicolas Fernandez-Mercau
# in season: sconto_percent=-79.6%, cioe' il prezzo minimo attuale e' quasi il
# DOPPIO della media storica -- un premio enorme, l'opposto di un affare -- ma
# con trend='up' finiva comunque in cima alla classifica/al viewer perche'
# timing+forma (70% del peso) dominavano la componente sconto (30%, clampata
# a [-30,100] quindi mai abbastanza negativa da farlo scendere sotto un vero
# affare). Aggiunta una penalita' FORTE e SEPARATA dal peso dello sconto:
# sotto questa soglia il punteggio intero viene moltiplicato (non solo la
# fetta 30%), cosi' un sovrapprezzo estremo declassa la carta a prescindere
# da quanto siano alti timing/forma.
SOVRAPPREZZO_PENALTY_THRESHOLD_PERCENT = -15.0
SOVRAPPREZZO_PENALTY_MULTIPLIER = 0.3

# FIX 29/07 bis (richiesta esplicita utente, caso reale Jonathan Bond classic):
# sconto_percent quasi zero (-1.22%, prezzo stabile 2-3EUR da sempre, nessuna
# vera occasione) eppure score alto (0.3552) -- causa: ultima_partita_score=92.5
# contro L5=L10=47 (gap di +45.5 punti, quasi il doppio della sua norma), un
# singolo exploit isolato che pesa il 20% come se fosse forma consolidata.
# Confrontato con casi validati dall'utente (Zimmerman/Gavran, sconto
# altrettanto vicino a zero ma score giustificato da timing ottimale + forma
# COERENTE, gap ultima/L5 di soli +17.9 o negativo) -- una soglia minima di
# sconto avrebbe escluso anche questi, sbagliato (l'utente l'ha respinta).
# Il difetto vero e' l'ultima_partita_score isolata dal contesto: clampata qui
# a non superare L5 di piu' di ULTIMA_GAP_CAP punti, cosi' un exploit isolato
# non puo' piu' da solo gonfiare lo score quanto una forma davvero buona e
# ripetuta.
ULTIMA_GAP_CAP = 20.0


def compute_potenziale_score(ultima_partita_score, l5, l10, l40, sconto_percent, ore_alla_partita,
                              trend_recente=None):
    """Ritorna None se manca un ingrediente essenziale (timing sconosciuto --
    non dovrebbe succedere, le carte senza prossima partita sono gia' in
    blacklist prima di arrivare qui)."""
    if ore_alla_partita is None:
        return None
    peso_timing = timing_weight(ore_alla_partita)
    ultima_raw = ultima_partita_score or 0.0
    if l5 is not None:
        ultima_raw = min(ultima_raw, l5 + ULTIMA_GAP_CAP)
    ultima = ultima_raw / 100.0
    media_generale = (0.5 * (l5 or 0.0) + 0.3 * (l10 or 0.0) + 0.2 * (l40 or 0.0)) / 100.0
    sconto_norm = _clamp(sconto_percent, -30.0, 100.0) / 100.0 if sconto_percent is not None else 0.0
    sconto_norm *= TREND_SCORE_MULTIPLIER.get(trend_recente, TREND_SCORE_MULTIPLIER[None])
    score = (0.40 * peso_timing) + (0.15 * ultima) + (0.10 * media_generale) + (0.35 * sconto_norm)
    if sconto_percent is not None and sconto_percent < SOVRAPPREZZO_PENALTY_THRESHOLD_PERCENT:
        score *= SOVRAPPREZZO_PENALTY_MULTIPLIER
    return round(score, 4)


# =====================================================================================
# PATTERN GIORNI-DA-PARTITA (diagnostico, richiesta esplicita utente 26/07)
# Accumulatore GLOBALE (non per singola carta -- 7gg di storico per una sola
# carta danno troppi pochi campioni): bucket = giorno intero rispetto alla
# partita piu' vicina (negativo=prima, positivo=dopo) -> lista di prezzi
# NORMALIZZATI (prezzo / media della carta in quella finestra), cosi' carte di
# valore diverso si possono sommare senza che le piu' costose pesino di piu'.
# =====================================================================================
_pattern_giorni_lock = threading.Lock()
_pattern_giorni = {}  # bucket_int -> [prezzo_normalizzato, ...]


def _registra_pattern_giorni(match_dates, tx_con_date, baseline):
    """Per ogni transazione (dt, prezzo) calcola il bucket giorno-da-partita e
    accumula il prezzo normalizzato (prezzo/baseline) nell'accumulatore globale.
    baseline = media (non trimmed, per semplicita') dei prezzi della carta in
    questa finestra -- se manca o e' zero, non c'e' niente da normalizzare."""
    if not baseline or baseline <= 0 or not match_dates:
        return
    with _pattern_giorni_lock:
        for dt, price in tx_con_date:
            offset = giorni_da_partita_piu_vicina(dt, match_dates)
            if offset is None:
                continue
            bucket = int(round(offset))
            _pattern_giorni.setdefault(bucket, []).append(price / baseline)


def write_pattern_giorni_csv():
    """Scrive scanners/bot_profit_output/pattern_giorni_da_partita.csv: una riga
    per bucket giorno-da-partita, prezzo medio normalizzato (1.0 = media della
    carta) e sconto%/premio% implicito -- per capire in quale punto del ciclo
    settimanale conviene comprare (valore minimo) o vendere (valore massimo)."""
    with _pattern_giorni_lock:
        snapshot_buckets = {k: list(v) for k, v in _pattern_giorni.items()}
    if not snapshot_buckets:
        return
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    path = os.path.join(OUTPUT_DIR, 'pattern_giorni_da_partita.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['giorni_da_partita', 'n_transazioni', 'prezzo_medio_normalizzato', 'scostamento_percent'])
        for bucket in sorted(snapshot_buckets):
            valori = snapshot_buckets[bucket]
            media_norm = sum(valori) / len(valori)
            writer.writerow([bucket, len(valori), round(media_norm, 4), round((media_norm - 1.0) * 100, 2)])
    log(f"[pattern giorni-da-partita] scritto {path} ({len(snapshot_buckets)} bucket, "
        f"{sum(len(v) for v in snapshot_buckets.values())} transazioni totali)")


# =====================================================================================
# STATO CONDIVISO (thread-safe)
# Chiave: MLS/K-League -> "slug::in_season" / "slug::classic" (due righe separate);
#         altri campionati -> "slug" (una riga sola, mercato unico).
# =====================================================================================
_tracked_lock = threading.Lock()
_tracked = {}


def _row_key(player_slug, is_in_season, league_slug):
    if is_excluded_league(league_slug):
        return f"{player_slug}::{'in_season' if is_in_season else 'classic'}"
    return player_slug


def _upsert_tracked_row(key, row):
    """Ritorna il numero totale di carte tracciate DOPO l'inserimento (per lo
    stop automatico a MAX_TRACKED_CARDS -- una entry NUOVA conta, un
    aggiornamento di una gia' esistente no)."""
    with _tracked_lock:
        is_new = key not in _tracked
        _tracked[key] = row
        return len(_tracked), is_new


CSV_FIELDNAMES = [
    'player_slug', 'player_name', 'link_sorare', 'league_slug', 'tipo_carta', 'potenziale_score',
    'squadra', 'prossimo_avversario',
    'ultima_partita_score', 'l5', 'l10', 'l40',
    'min_attuale_eur', 'media_transazioni_7gg_trimmed_eur', 'n_transazioni_usate',
    'sconto_percent', 'trend_recente', 'media_transazioni_recente_eur', 'media_transazioni_storica_eur',
    'prossima_partita_data', 'ore_alla_partita', 'ultimo_tipo_evento',
]

# FIX 27/07 quinquies (richiesta esplicita utente): lo sconto_percent confronta
# il minimo attuale con la media dell'INTERA finestra a 7gg -- se il prezzo sta
# gia' scendendo da un paio di giorni, quella media e' "vecchia" e lo sconto
# appare piu' grande di quanto sia in realta' un'occasione (sta solo inseguendo
# un mercato in calo, non necessariamente destinato a tornare alla vecchia
# media). Confermato su un caso reale (Anthony Markanich/Daniel Munie, min
# verificato dall'utente su Sorare: crollo reale da ~8-10EUR a ~3.5EUR negli
# ultimi 2 giorni). Aggiunta una media "recente" separata (ultimi
# TREND_RECENT_WINDOW_DAYS giorni) confrontata con la media del resto della
# finestra, per segnalare quando lo sconto e' meno affidabile. Dal 29/07 pesa
# anche potenziale_score (vedi TREND_SCORE_MULTIPLIER sopra), non e' piu' solo
# un indicatore visivo.
TREND_RECENT_WINDOW_DAYS = int(os.environ.get('TREND_RECENT_WINDOW_DAYS', '2'))
TREND_FLAT_THRESHOLD_PERCENT = float(os.environ.get('TREND_FLAT_THRESHOLD_PERCENT', '10.0'))


def _split_recent_vs_storico(tx_con_date, now=None):
    """Divide le transazioni (gia' filtrate is_in_season/lega, con datetime e
    prezzo) in 'recenti' (ultimi TREND_RECENT_WINDOW_DAYS giorni) e 'storiche'
    (il resto della finestra a 7gg), e calcola la media trimmed di ciascun
    gruppo. Ritorna (media_recente, media_storica, trend_arrow)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    soglia_recente = now - datetime.timedelta(days=TREND_RECENT_WINDOW_DAYS)
    prezzi_recenti = [p for dt, p in tx_con_date if dt >= soglia_recente]
    prezzi_storici = [p for dt, p in tx_con_date if dt < soglia_recente]
    media_recente, _, _ = trimmed_average(prezzi_recenti)
    media_storica, _, _ = trimmed_average(prezzi_storici)

    trend = None
    if media_recente is not None and media_storica is not None and media_storica > 0:
        variazione = (media_recente - media_storica) / media_storica * 100
        if variazione <= -TREND_FLAT_THRESHOLD_PERCENT:
            trend = 'down'
        elif variazione >= TREND_FLAT_THRESHOLD_PERCENT:
            trend = 'up'
        else:
            trend = 'flat'
    return media_recente, media_storica, trend


def _sorare_market_link(player_slug):
    """Link diretto alla pagina giocatore su Sorare -- richiesta esplicita
    utente 27/07, per aprire la carta con un clic dal CSV/viewer invece di
    cercarla a mano (corretto lo stesso giorno: non la pagina mercato/shop
    ma quella profilo giocatore, es. .../football/players/anthony-markanich)."""
    return f"https://sorare.com/it/football/players/{player_slug}"


def _key_from_csv_row(row):
    """Ricostruisce la stessa chiave di _row_key partendo da una riga GIA' letta
    dal CSV (dove non abbiamo piu' league_slug, solo l'etichetta tipo_carta gia'
    scritta in precedenza)."""
    tipo = row.get('tipo_carta')
    if tipo == 'in season':
        return f"{row['player_slug']}::in_season"
    if tipo == 'classic':
        return f"{row['player_slug']}::classic"
    return row['player_slug']


def _parse_float_or_none(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_previous_tracked():
    """FIX 24/07 (richiesta esplicita utente): il CSV non e' piu' uno snapshot
    che riparte vuoto ad ogni run -- e' una CLASSIFICA che si aggiorna nel
    tempo. Ad ogni avvio, se esiste gia' un profit_tracking_<timestamp>.csv nel
    repo, ricarica il PIU' RECENTE in _tracked come stato di partenza (FIX
    27/07: il nome ora cambia ad ogni scrittura, vedi _find_latest_output_csv);
    le carte incontrate in questa run aggiornano (upsert) le righe esistenti o
    ne aggiungono di nuove, senza perdere quello che le run precedenti avevano
    gia' trovato.

    FIX 29/07 quater (estensione K-League): ora esistono fino a 2 file (uno per
    lega, vedi OUTPUT_LEAGUE_SLUGS) invece di un unico combinato -- carica
    entrambi se presenti. Mantiene anche il fallback sul vecchio nome combinato
    (profit_tracking_<timestamp>.csv, senza suffisso lega) per non perdere una
    classifica scritta prima di questo cambio."""
    paths = [p for p in (_find_latest_output_csv(_output_csv_prefix_for_league(l)) for l in OUTPUT_LEAGUE_SLUGS) if p]
    if not paths:
        legacy_path = _find_latest_output_csv()
        if legacy_path is None:
            log("[classifica persistente] nessun CSV precedente trovato, parto da zero")
            return
        paths = [legacy_path]

    caricate = 0
    for latest_path in paths:
        with open(latest_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            with _tracked_lock:
                for row in reader:
                    key = _key_from_csv_row(row)
                    _tracked[key] = {
                        'player_slug': row.get('player_slug'),
                        'player_name': row.get('player_name'),
                        'link_sorare': _sorare_market_link(row.get('player_slug')) if row.get('player_slug') else None,
                        'league_slug': row.get('league_slug') or None,
                        'tipo_carta': row.get('tipo_carta'),
                        'potenziale_score': _parse_float_or_none(row.get('potenziale_score')),
                        'squadra': row.get('squadra') or None,
                        'prossimo_avversario': row.get('prossimo_avversario') or None,
                        'ultima_partita_score': _parse_float_or_none(row.get('ultima_partita_score')),
                        'l5': _parse_float_or_none(row.get('l5')),
                        'l10': _parse_float_or_none(row.get('l10')),
                        'l40': _parse_float_or_none(row.get('l40')),
                        'min_attuale_eur': _parse_float_or_none(row.get('min_attuale_eur')),
                        'media_transazioni_7gg_trimmed_eur': _parse_float_or_none(
                            row.get('media_transazioni_7gg_trimmed_eur')),
                        'n_transazioni_usate': row.get('n_transazioni_usate'),
                        'sconto_percent': _parse_float_or_none(row.get('sconto_percent')),
                        'trend_recente': row.get('trend_recente') or None,
                        'media_transazioni_recente_eur': _parse_float_or_none(row.get('media_transazioni_recente_eur')),
                        'media_transazioni_storica_eur': _parse_float_or_none(row.get('media_transazioni_storica_eur')),
                        'prossima_partita_data': row.get('prossima_partita_data') or None,
                        'ore_alla_partita': _parse_float_or_none(row.get('ore_alla_partita')),
                        'ultimo_tipo_evento': row.get('ultimo_tipo_evento') or None,
                    }
                    caricate += 1
    log(f"[classifica persistente] caricate {caricate} righe da {len(paths)} CSV precedente/i come stato di partenza")


def _write_ranked_csv(rows_liquidi, path, label):
    """Ordina per potenziale_score decrescente, taglia a TOP_N_OUTPUT e scrive
    su disco."""
    rows_sorted = sorted(
        rows_liquidi,
        key=lambda r: (r['potenziale_score'] if r['potenziale_score'] is not None else -999),
        reverse=True,
    )[:TOP_N_OUTPUT]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in rows_sorted:
            writer.writerow(r)
    log(f"[csv] {label}: scritte {len(rows_sorted)}/{len(rows_liquidi)} carte "
        f"(top {TOP_N_OUTPUT} per potenziale_score) in {path}")
    return len(rows_sorted)


def _run_timestamp_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M')


def _cleanup_and_write_ranked_csv(rows_liquidi, dir_path, prefix, timestamp, label):
    """Come _write_ranked_csv, ma con nome file <prefix>_<timestamp>.csv (FIX
    27/07, richiesta esplicita utente: data/ora gia' nel nome, un solo file
    alla volta). Cancella PRIMA ogni <prefix>_*.csv preesistente nella stessa
    cartella, cosi' non si accumulano vecchie versioni ad ogni run/commit
    periodico -- ne resta sempre e solo uno, il piu' recente."""
    for old_path in glob.glob(os.path.join(dir_path, f"{prefix}_*.csv")):
        os.remove(old_path)
    path = os.path.join(dir_path, f"{prefix}_{timestamp}.csv")
    return path, _write_ranked_csv(rows_liquidi, path, label)


# FIX 29/07 quater (estensione K-League, richiesta esplicita utente: classifiche
# separate MLS/Korea invece di un unico CSV mescolato -- vedi TEAM_LEAGUE_MAP
# sopra). Un prefisso di file per lega, es. profit_tracking_mlspa_<ts>.csv e
# profit_tracking_k-league-1_<ts>.csv -- stessi vincoli (soglia prezzo,
# MIN_TRANSACTIONS_FOR_RANKING, TOP_N_OUTPUT) applicati identici a entrambe.
OUTPUT_LEAGUE_SLUGS = ('mlspa', 'k-league-1')


def _output_csv_prefix_for_league(league_slug):
    return f"{OUTPUT_CSV_PREFIX}_{league_slug}"


def _find_latest_output_csv(prefix=None):
    """Trova il file <prefix>_<timestamp>.csv piu' recente (ordinamento
    lessicografico = cronologico col formato YYYYMMDD_HHMM) -- serve a
    load_previous_tracked() dato che il nome cambia ad ogni run. Senza prefix,
    usa il vecchio nome combinato profit_tracking_<timestamp>.csv (compatibilita'
    con classifiche scritte prima dello split per lega)."""
    base = prefix or OUTPUT_CSV_PREFIX
    candidates = sorted(glob.glob(f"{base}_*.csv"))
    return candidates[-1] if candidates else None


def write_csv_snapshot():
    """FIX 29/07 quater (estensione K-League, richiesta esplicita utente):
    classifiche separate per lega invece di un unico CSV mescolato -- una
    riga per riga viene assegnata al CSV della propria league_slug
    (profit_tracking_mlspa_<ts>.csv / profit_tracking_k-league-1_<ts>.csv),
    ciascuno top TOP_N_OUTPUT per potenziale_score, in_season+classic
    mescolati come prima (colonna tipo_carta). Ad ogni scrittura viene
    cancellato il file con timestamp precedente PER QUELLA LEGA (vedi
    _cleanup_and_write_ranked_csv) -- ne resta sempre e solo uno per lega, il
    piu' recente. Righe di leghe non in OUTPUT_LEAGUE_SLUGS (non dovrebbe mai
    capitare in modalita' snapshot) non vengono scritte in nessun file."""
    with _tracked_lock:
        rows = list(_tracked.values())
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # FIX 24/07 (richiesta esplicita utente): le carte senza NESSUNA transazione
    # nella finestra (0/0, media_trimmed=None) non vanno in classifica -- niente
    # storico prezzo = dato inutilizzabile per il confronto. Vengono escluse PRIMA
    # del taglio top-N, cosi' la 51esima carta valida prende il loro posto invece
    # di lasciare un buco.
    rows_con_storico = [r for r in rows if r['media_transazioni_7gg_trimmed_eur'] is not None]
    esclusi_senza_storico = len(rows) - len(rows_con_storico)

    def _n_totali(r):
        try:
            return int(r['n_transazioni_usate'].split('/')[1])
        except (ValueError, IndexError, AttributeError):
            return 0

    # FIX 24/07 (richiesta esplicita utente): sotto MIN_TRANSACTIONS_FOR_RANKING
    # transazioni nella finestra, il dato resta troppo rumoroso -- escluso anche
    # questo dalla classifica (non solo lo 0/0 di prima).
    rows_liquidi = [r for r in rows_con_storico if _n_totali(r) >= MIN_TRANSACTIONS_FOR_RANKING]
    esclusi_poco_liquidi = len(rows_con_storico) - len(rows_liquidi)

    timestamp = _run_timestamp_utc()

    per_lega_riepilogo = []
    for league_slug in OUTPUT_LEAGUE_SLUGS:
        rows_lega = [r for r in rows_liquidi if r.get('league_slug') == league_slug]
        path, n_scritte = _cleanup_and_write_ranked_csv(
            rows_lega, OUTPUT_DIR, f'profit_tracking_{league_slug}', timestamp, league_slug)
        per_lega_riepilogo.append(f"{league_slug}: {n_scritte} nel file {path}")

    log(f"[csv] totale tracciate: {len(rows)}, {esclusi_senza_storico} escluse per assenza di storico, "
        f"{esclusi_poco_liquidi} escluse per meno di {MIN_TRANSACTIONS_FOR_RANKING} transazioni "
        f"({'; '.join(per_lega_riepilogo)})")


# =====================================================================================
# COMMIT PERIODICO (default 2 minuti) -- stesso pattern di Bot Supremo
# =====================================================================================
_stop_periodic_commit = threading.Event()


def _commit_output_se_serve():
    try:
        write_csv_snapshot()
        write_pattern_giorni_csv()
        # FIX 27/07: i nomi file dentro OUTPUT_DIR ora cambiano ad ogni scrittura
        # (timestamp) -- si committa l'intera cartella invece di elencare nomi
        # fissi, cosi' git vede automaticamente sia i file nuovi sia la
        # cancellazione di quelli vecchi (vedi _cleanup_and_write_ranked_csv).
        paths_da_committare = [OUTPUT_DIR]
        if os.path.exists(LISTA_NERA_PROFIT_PATH):
            paths_da_committare.append(LISTA_NERA_PROFIT_PATH)
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--'] + paths_da_committare,
            capture_output=True, text=True, timeout=30
        )
        if not status.stdout.strip():
            return
        subprocess.run(['git', 'config', 'user.name', 'bot-profit'], timeout=30)
        subprocess.run(['git', 'config', 'user.email',
                         'bot-profit@users.noreply.github.com'], timeout=30)
        subprocess.run(['git', 'add'] + paths_da_committare, timeout=30)
        commit = subprocess.run(
            ['git', 'commit', '-m', 'Bot Profit: commit periodico dati tracciati (run in corso)'],
            capture_output=True, text=True, timeout=30
        )
        if commit.returncode != 0:
            log(f"[commit periodico] nulla da committare o commit fallito: "
                f"{commit.stdout.strip()} {commit.stderr.strip()}")
            return
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip() or 'main'
        pull = subprocess.run(
            ['git', 'pull', '--rebase', '--autostash', 'origin', branch],
            capture_output=True, text=True, timeout=60
        )
        if pull.returncode != 0:
            # FIX 26/07: un rebase fallito lascia il repo a meta' rebase -- se non lo
            # annulliamo, TUTTI i prossimi giri di commit periodico falliscono allo
            # stesso modo per il resto della run. Annullato cosi' il prossimo giro
            # riparte pulito (i dati di QUESTO giro restano committati solo in
            # locale, verranno ripushati al prossimo giro se il conflitto rientra).
            subprocess.run(['git', 'rebase', '--abort'], capture_output=True, text=True, timeout=30)
            log(f"[commit periodico] git pull --rebase fallito su branch={branch}, annullato il rebase, "
                f"salto il push di questo giro: {pull.stderr.strip()}")
            return
        push = subprocess.run(['git', 'push'], capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            log("[commit periodico] dati tracciati committati e pushati con successo (run ancora in corso)")
        else:
            log(f"[commit periodico] push fallito: {push.stderr.strip()}")
    except Exception as e:
        log(f"[commit periodico] eccezione non bloccante, ritento al prossimo giro: {e}")


def _periodic_commit_loop():
    while not _stop_periodic_commit.wait(COMMIT_CHUNK_SECONDS):
        _commit_output_se_serve()


# =====================================================================================
# LISTENER WEBSOCKET -- stesso canale di Bot Supremo, ma nessuna decisione di
# acquisto/offerta: solo tracciamento.
# =====================================================================================
SUBSCRIPTION_QUERY = """
subscription OnTokenOfferUpdated {
  tokenOfferWasUpdated {
    id
    status
    senderSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards {
        slug
        rarityTyped
        sport
        inSeasonEligible
        ... on Card {
          coverageStatus
        }
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
      }
    }
    receiverSide {
      amounts { eurCents wei usdCents gbpCents lamport }
      anyCards { slug }
    }
  }
}
"""


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "tracked": 0, "skipped_forma_zero": 0,
              "skipped_coverage": 0, "skipped_nessuna_partita": 0, "skipped_blacklist": 0,
              "skipped_prezzo_basso": 0, "_closed_max_tracked": False}
    stats_lock = threading.Lock()
    seen_offer_status = set()
    event_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=EVENT_WORKER_THREADS, thread_name_prefix='evt')

    def _process_one_card_event(player_slug, player_name, league_slug, is_in_season):
        try:
            # Ricontrollo blacklist (potrebbe essere stata scritta da un altro
            # thread worker nel frattempo, tra il check in on_message e l'esecuzione).
            if is_player_blacklisted(player_slug):
                with stats_lock:
                    stats['skipped_blacklist'] += 1
                return

            # FIX 24/07 (richiesta esplicita utente): PRIMA query in assoluto --
            # sotto MIN_PRICE_EUR_THRESHOLD la carta viene scartata subito, senza
            # nessun'altra chiamata e SENZA blacklist (il prezzo puo' risalire).
            min_attuale = get_current_minimum(player_slug, is_in_season, league_slug, eth_rate)
            if min_attuale is None or min_attuale < MIN_PRICE_EUR_THRESHOLD:
                with stats_lock:
                    stats['skipped_prezzo_basso'] += 1
                return

            snapshot = get_player_snapshot(player_slug)
            if snapshot is None:
                return

            l5 = snapshot['l5']
            if not l5:  # None o 0
                blacklist_player(player_slug, 'l5_zero_o_assente', NOT_COVERED_O_FORMA_ZERO_DAYS)
                with stats_lock:
                    stats['skipped_forma_zero'] += 1
                log(f"[blacklist] {player_name} ({player_slug}): L5 assente/zero -- "
                    f"blacklistato {NOT_COVERED_O_FORMA_ZERO_DAYS:.0f}gg")
                return

            if not snapshot['next_game_date_str']:
                blacklist_player(player_slug, 'nessuna_partita', NESSUNA_PARTITA_DAYS)
                with stats_lock:
                    stats['skipped_nessuna_partita'] += 1
                log(f"[blacklist] {player_name} ({player_slug}): nessuna prossima partita -- "
                    f"blacklistato {NESSUNA_PARTITA_DAYS:.0f}gg")
                return

            tx_con_date = _fetch_countable_transactions(player_slug, is_in_season, league_slug, eth_rate)
            tx_prices = [price for _, price in tx_con_date]
            avg_trimmed, n_usati, n_totali = trimmed_average(tx_prices)

            sconto_percent = None
            if avg_trimmed and avg_trimmed > 0 and min_attuale is not None:
                sconto_percent = round((avg_trimmed - min_attuale) / avg_trimmed * 100, 2)

            media_recente, media_storica, trend_recente = _split_recent_vs_storico(tx_con_date)

            ore_alla_partita = hours_until(snapshot['next_game_date_str'])

            potenziale_score = compute_potenziale_score(
                l5=l5, l10=snapshot['l10'], l40=snapshot['l40'],
                ultima_partita_score=snapshot['ultima_partita_score'],
                sconto_percent=sconto_percent, ore_alla_partita=ore_alla_partita,
                trend_recente=trend_recente,
            )

            excluded = is_excluded_league(league_slug)
            tipo_carta = ('in season' if is_in_season else 'classic') if excluded else 'misto'

            row = {
                'player_slug': player_slug,
                'player_name': player_name,
                'link_sorare': _sorare_market_link(player_slug),
                'league_slug': league_slug,
                'tipo_carta': tipo_carta,
                'potenziale_score': potenziale_score,
                'squadra': snapshot['squadra'],
                'prossimo_avversario': snapshot['prossimo_avversario'],
                'ultima_partita_score': snapshot['ultima_partita_score'],
                'l5': l5,
                'l10': snapshot['l10'],
                'l40': snapshot['l40'],
                'min_attuale_eur': round(min_attuale, 2) if min_attuale is not None else None,
                'media_transazioni_7gg_trimmed_eur': round(avg_trimmed, 2) if avg_trimmed is not None else None,
                'n_transazioni_usate': f"{n_usati}/{n_totali}",
                'sconto_percent': sconto_percent,
                'trend_recente': trend_recente,
                'media_transazioni_recente_eur': round(media_recente, 2) if media_recente is not None else None,
                'media_transazioni_storica_eur': round(media_storica, 2) if media_storica is not None else None,
                'prossima_partita_data': snapshot['next_game_date_str'],
                'ore_alla_partita': round(ore_alla_partita, 1) if ore_alla_partita is not None else None,
                'ultimo_tipo_evento': 'in_season' if is_in_season else 'classic',
            }
            key = _row_key(player_slug, is_in_season, league_slug)
            total_tracked, is_new = _upsert_tracked_row(key, row)

            with stats_lock:
                if is_new:
                    stats['tracked'] += 1
                tracked_count = stats['tracked']
                # FIX 24/07: con la classifica persistente, il conteggio verso
                # MAX_TRACKED_CARDS deve restare quello delle carte NUOVE
                # trovate in QUESTA run (stats['tracked']), non la dimensione
                # totale della classifica (total_tracked), che ora include
                # anche le righe ricaricate dalle run precedenti.
                raggiunto_max = tracked_count >= MAX_TRACKED_CARDS and not stats['_closed_max_tracked']
                if raggiunto_max:
                    stats['_closed_max_tracked'] = True

            log(f"[tracciata] {player_name} ({tipo_carta}): score={potenziale_score} "
                f"ultima_partita={row['ultima_partita_score']} "
                f"L5={l5} L10={row['l10']} L40={row['l40']} "
                f"min={row['min_attuale_eur']}EUR media7gg_trim={row['media_transazioni_7gg_trimmed_eur']}EUR "
                f"sconto={sconto_percent}% prossima_partita={snapshot['next_game_date_str']} "
                f"({row['ore_alla_partita']}h) -- totale tracciate finora: {tracked_count}/{MAX_TRACKED_CARDS}")

            if raggiunto_max:
                log(f"STOP: raggiunte {tracked_count}/{MAX_TRACKED_CARDS} carte NUOVE tracciate in questa run "
                    f"(classifica totale: {total_tracked} righe), chiudo la connessione")
                ws.close()
        except Exception as e:
            log(f"[ERRORE in valutazione evento] {player_name}: eccezione non gestita, la salto: {e}")

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

        try:
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
                return  # scambio carta-per-carta

            sender_cards = sender_side.get('anyCards') or []
            if len(sender_cards) > 1:
                return  # bundle multi-carta

            for card in sender_cards:
                if card.get('rarityTyped') != 'limited':
                    continue
                if card.get('sport') != 'FOOTBALL':
                    continue
                if card.get('coverageStatus') == 'NOT_COVERED':
                    player_tmp = card.get('anyPlayer') or {}
                    slug_tmp = player_tmp.get('slug')
                    if slug_tmp:
                        blacklist_player(slug_tmp, 'not_covered', NOT_COVERED_O_FORMA_ZERO_DAYS)
                    with stats_lock:
                        stats['skipped_coverage'] += 1
                    continue

                player = card.get('anyPlayer') or {}
                player_slug = player.get('slug')
                player_name = player.get('displayName', player_slug)
                if not player_slug:
                    continue

                # Check blacklist SUBITO -- zero query per carte gia' note.
                if is_player_blacklisted(player_slug):
                    with stats_lock:
                        stats['skipped_blacklist'] += 1
                    continue

                is_in_season = bool(card.get('inSeasonEligible'))
                if not is_in_season and not CHECK_CLASSIC:
                    continue

                league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')

                stats["processed"] += 1
                event_executor.submit(_process_one_card_event, player_slug, player_name,
                                       league_slug, is_in_season)
        except Exception as e:
            log(f"[ERRORE in on_message] eccezione non gestita, la salto e continuo ad ascoltare: {e}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: {stats['received']}, "
            f"carte elaborate: {stats['processed']}, tracciate: {stats['tracked']}/{MAX_TRACKED_CARDS}, "
            f"scartate per blacklist: {stats['skipped_blacklist']}, "
            f"scartate per prezzo < {MIN_PRICE_EUR_THRESHOLD}EUR: {stats['skipped_prezzo_basso']}, "
            f"scartate per forma zero/L5 assente: {stats['skipped_forma_zero']}, "
            f"scartate per non-copertura: {stats['skipped_coverage']}, "
            f"scartate per nessuna partita: {stats['skipped_nessuna_partita']}")

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

    ws.run_forever(ping_interval=60, ping_timeout=45)
    timer.cancel()
    event_executor.shutdown(wait=True)

    return stats


# =====================================================================================
# MODALITA' SNAPSHOT -- giro esplicito sul roster delle squadre in TEAM_WHITELIST,
# nessun websocket. Ricalcola SEMPRE ogni carta (in_season + classic), a differenza
# del listener a eventi che aggiorna una carta solo quando genera un evento.
# Riusa le STESSE funzioni del percorso a eventi (get_current_minimum,
# get_player_snapshot, get_recent_transaction_prices, blacklist) -- stessa identica
# logica di esclusione/blacklist, cambia solo cosa la innesca.
# =====================================================================================
def _process_player_snapshot(player_slug, player_name, expected_team_slug, league_slug, eth_rate,
                              live_offer_nodes, snapshot, next_game_date_str, prossimo_avversario,
                              ultima_partita_score, past_game_dates, tx_nodes, tx_cutoff):
    """FIX 27/07 bis (richiesta esplicita utente, ridurre il numero di query
    verso Sorare): live_offer_nodes (prezzo), la prossima/ultima partita e le
    transazioni arrivano GIA' pronte dal chiamante (run_snapshot_sweep, un'unica
    query combinata per giocatore, vedi fetch_player_combined_snapshot -- FIX
    27/07 quater), mentre snapshot (voto) arriva dal roster per squadra
    (fetch_team_roster/TEAM_ROSTER_QUERY) -- qui restano solo gli scarti/il
    calcolo che dipendono dai dati gia' in mano, passati come parametri invece
    che ri-scaricati per ogni giocatore."""
    if snapshot is None:
        log(f"[snapshot] {player_name} ({player_slug}): nessun dato giocatore, salto.")
        return 'no_snapshot'

    # FIX 26/07 (bug segnalato dall'utente): Club.anyPlayers restituisce anche
    # giocatori NON piu' al club (storico), non solo la rosa attuale -- niente
    # blacklist qui (potrebbero comunque essere validi altrove/in futuro), solo
    # uno scarto SILENZIOSO subito, PRIMA di sprecare le query su minimo/
    # transazioni per un giocatore che non appartiene piu' a questa squadra.
    if snapshot.get('squadra_slug') != expected_team_slug:
        return 'squadra_diversa'

    l5 = snapshot['l5']
    if not l5:  # None o 0 -- il roster gia' filtra L5 a monte (fetch_team_roster),
        # qui e' solo rete di sicurezza silenziosa, nessuna blacklist: il prossimo
        # sweep ricontrolla il roster gratis, un blocco di 30gg non aggiungerebbe nulla.
        return 'forma_zero'

    if not next_game_date_str:
        blacklist_player(player_slug, 'nessuna_partita', NESSUNA_PARTITA_DAYS)
        log(f"[blacklist] {player_name} ({player_slug}): nessuna prossima partita -- "
            f"blacklistato {NESSUNA_PARTITA_DAYS:.0f}gg")
        return 'nessuna_partita'

    match_dates = past_game_dates + [next_game_date_str]
    ore_alla_partita = hours_until(next_game_date_str)
    righe_scritte = 0

    for is_in_season in (True, False):
        if not is_in_season and not CHECK_CLASSIC:
            continue

        min_attuale = _current_minimum_from_nodes(live_offer_nodes, is_in_season, league_slug, eth_rate)
        if min_attuale is None or min_attuale < MIN_PRICE_EUR_THRESHOLD:
            continue  # niente blacklist, il prezzo puo' risalire (stesso criterio del percorso a eventi)

        tx_con_date = _countable_transactions_from_nodes(tx_nodes, tx_cutoff, is_in_season, league_slug, eth_rate)
        tx_prices = [price for _, price in tx_con_date]
        avg_trimmed, n_usati, n_totali = trimmed_average(tx_prices)

        sconto_percent = None
        if avg_trimmed and avg_trimmed > 0:
            sconto_percent = round((avg_trimmed - min_attuale) / avg_trimmed * 100, 2)

        media_recente, media_storica, trend_recente = _split_recent_vs_storico(tx_con_date)

        if tx_prices:
            baseline_pattern = sum(tx_prices) / len(tx_prices)
            _registra_pattern_giorni(match_dates, tx_con_date, baseline_pattern)

        potenziale_score = compute_potenziale_score(
            l5=l5, l10=snapshot['l10'], l40=snapshot['l40'],
            ultima_partita_score=ultima_partita_score,
            sconto_percent=sconto_percent, ore_alla_partita=ore_alla_partita,
            trend_recente=trend_recente,
        )

        excluded = is_excluded_league(league_slug)
        tipo_carta = ('in season' if is_in_season else 'classic') if excluded else 'misto'

        row = {
            'player_slug': player_slug,
            'player_name': player_name,
            'link_sorare': _sorare_market_link(player_slug),
            'league_slug': league_slug,
            'tipo_carta': tipo_carta,
            'potenziale_score': potenziale_score,
            'squadra': snapshot['squadra'],
            'prossimo_avversario': prossimo_avversario,
            'ultima_partita_score': ultima_partita_score,
            'l5': l5,
            'l10': snapshot['l10'],
            'l40': snapshot['l40'],
            'min_attuale_eur': round(min_attuale, 2) if min_attuale is not None else None,
            'media_transazioni_7gg_trimmed_eur': round(avg_trimmed, 2) if avg_trimmed is not None else None,
            'n_transazioni_usate': f"{n_usati}/{n_totali}",
            'sconto_percent': sconto_percent,
            'trend_recente': trend_recente,
            'media_transazioni_recente_eur': round(media_recente, 2) if media_recente is not None else None,
            'media_transazioni_storica_eur': round(media_storica, 2) if media_storica is not None else None,
            'prossima_partita_data': next_game_date_str,
            'ore_alla_partita': round(ore_alla_partita, 1) if ore_alla_partita is not None else None,
            'ultimo_tipo_evento': 'in_season' if is_in_season else 'classic',
        }
        key = _row_key(player_slug, is_in_season, league_slug)
        _upsert_tracked_row(key, row)
        righe_scritte += 1

        log(f"[snapshot] {player_name} ({tipo_carta}): score={potenziale_score} "
            f"min={row['min_attuale_eur']}EUR media7gg_trim={row['media_transazioni_7gg_trimmed_eur']}EUR "
            f"sconto={sconto_percent}% n_transazioni={row['n_transazioni_usate']}")

    return 'ok' if righe_scritte else 'prezzo_basso_o_senza_annunci'


RATE_LIMIT_RETRY_PAUSE_SECONDS = float(os.environ.get('RATE_LIMIT_RETRY_PAUSE_SECONDS', '30.0'))


def run_snapshot_sweep(eth_rate):
    log(f"Avvio SNAPSHOT su {len(TEAM_WHITELIST)} squadra/e "
        f"({len(MLS_TEAM_WHITELIST)} MLS + {len(KLEAGUE_TEAM_WHITELIST)} K-League): {TEAM_WHITELIST}")

    roster = {}  # slug -> (displayName, team_slug attesa, snapshot voto/partita, league_slug), deduplicato tra squadre
    for team_slug in TEAM_WHITELIST:
        league_slug = TEAM_LEAGUE_MAP[team_slug]
        for player_slug, player_name, snapshot in fetch_team_roster(team_slug):
            roster.setdefault(player_slug, (player_name, team_slug, snapshot, league_slug))

    log(f"Roster totale (deduplicato): {len(roster)} giocatori.")

    # FIX 27/07 (run troppo lento, richiesta esplicita utente): pool di worker
    # invece del giro sequenziale con pausa fissa -- _graphql_throttle() e' gia'
    # un rate-limiter globale (lock condiviso), quindi la concorrenza qui
    # sovrappone i tempi di attesa risposta tra giocatori diversi senza
    # aumentare il ritmo delle richieste in uscita verso Sorare.
    stats = {}
    stats_lock = threading.Lock()
    total = len(roster)
    done = [0]

    def _registra_esito(player_name, player_slug, esito):
        with stats_lock:
            stats[esito] = stats.get(esito, 0) + 1
            done[0] += 1
            log(f"[{done[0]}/{total}] {player_name} ({player_slug}): {esito}")

    # FIX 27/07 bis (richiesta esplicita utente, ridurre il numero di query
    # verso Sorare): lo snapshot voto arriva GIA' con il roster (vedi
    # fetch_team_roster/TEAM_ROSTER_QUERY, 1 sola richiesta per squadra).
    # FIX 27/07 quater (richiesta esplicita utente, troppi HTTP 429): prezzo,
    # prossima/ultima partita e prima pagina di transazioni ora arrivano in
    # UNA sola richiesta per giocatore (fetch_player_combined_snapshot), non
    # piu' tre round-trip separati -- vedi quella funzione per il dettaglio.
    tipi_da_provare = (True, False) if CHECK_CLASSIC else (True,)

    # FIX 29/07 (richiesta esplicita utente): i giocatori la cui query fallisce
    # per rate-limit esaurito venivano persi senza appello, confusi con un
    # "davvero nessuna offerta" -- finiscono qui invece, per un secondo giro
    # dedicato DOPO che il primo e' finito (quando il rate-limit di Sorare si
    # e' presumibilmente allentato, la raffica di 429 osservata era comunque
    # concentrata nella seconda meta' della run).
    rate_limited_pool = []
    rate_limited_lock = threading.Lock()

    def _worker(player_slug, player_name, expected_team_slug, snapshot, league_slug, is_retry=False):
        if not is_retry and is_player_blacklisted(player_slug):
            _registra_esito(player_name, player_slug, 'blacklist')
            return
        (live_offer_nodes, next_game_date_str, prossimo_avversario, ultima_partita_score,
         past_game_dates, tx_nodes, tx_cutoff, errored) = fetch_player_combined_snapshot(player_slug)
        if errored:
            if is_retry:
                _registra_esito(player_name, player_slug, 'rate_limited_persistente')
            else:
                with rate_limited_lock:
                    rate_limited_pool.append((player_slug, player_name, expected_team_slug, snapshot, league_slug))
            return
        prezzo_ok = any(
            (m := _current_minimum_from_nodes(live_offer_nodes, tipo, league_slug, eth_rate)) is not None
            and m >= MIN_PRICE_EUR_THRESHOLD
            for tipo in tipi_da_provare
        )
        if not prezzo_ok:
            _registra_esito(player_name, player_slug, 'prezzo_basso_o_senza_annunci')
            return
        esito = _process_player_snapshot(
            player_slug, player_name, expected_team_slug, league_slug, eth_rate,
            live_offer_nodes, snapshot, next_game_date_str, prossimo_avversario,
            ultima_partita_score, past_game_dates, tx_nodes, tx_cutoff,
        )
        _registra_esito(player_name, player_slug, esito)

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=SNAPSHOT_WORKER_THREADS, thread_name_prefix='snap') as executor:
        futures = [
            executor.submit(_worker, player_slug, player_name, expected_team_slug, snapshot, league_slug)
            for player_slug, (player_name, expected_team_slug, snapshot, league_slug) in roster.items()
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()  # rilancia eventuali eccezioni non gestite dentro _worker

    log(f"SNAPSHOT primo giro completato. Riepilogo: {stats}")

    if rate_limited_pool:
        log(f"[retry rate-limit] {len(rate_limited_pool)} giocatori scartati per rate-limit nel primo "
            f"giro, secondo giro dedicato dopo {RATE_LIMIT_RETRY_PAUSE_SECONDS:.0f}s di pausa...")
        time.sleep(RATE_LIMIT_RETRY_PAUSE_SECONDS)
        done[0] = 0
        total = len(rate_limited_pool)
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=SNAPSHOT_WORKER_THREADS, thread_name_prefix='snap-retry') as executor:
            futures = [
                executor.submit(_worker, player_slug, player_name, expected_team_slug, snapshot, league_slug, True)
                for player_slug, player_name, expected_team_slug, snapshot, league_slug in rate_limited_pool
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()
        log(f"[retry rate-limit] secondo giro completato. Riepilogo aggiornato: {stats}")

    log(f"SNAPSHOT completato. Riepilogo per giocatore: {stats}")
    return stats


def main():
    log(f"Avvio Bot Profit. SNAPSHOT_MODE={SNAPSHOT_MODE} TEAM_WHITELIST={TEAM_WHITELIST} "
        f"LISTEN_SECONDS={LISTEN_SECONDS} COMMIT_CHUNK_SECONDS={COMMIT_CHUNK_SECONDS} "
        f"CHECK_CLASSIC={CHECK_CLASSIC} "
        f"TRANSACTIONS_WINDOW_DAYS={TRANSACTIONS_WINDOW_DAYS} "
        f"TOP_N_OUTPUT={TOP_N_OUTPUT} MAX_TRACKED_CARDS={MAX_TRACKED_CARDS} "
        f"MIN_TRANSACTIONS_FOR_RANKING={MIN_TRANSACTIONS_FOR_RANKING} "
        f"MIN_PRICE_EUR_THRESHOLD={MIN_PRICE_EUR_THRESHOLD}")

    if not COOKIES or not CSRF_TOKEN:
        log("ERRORE: SORARE_COOKIE/SORARE_CSRF mancanti, impossibile continuare.")
        return

    if SNAPSHOT_MODE and not TEAM_WHITELIST:
        log("ERRORE: SNAPSHOT_MODE attivo ma TEAM_WHITELIST vuota, impossibile continuare.")
        return

    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")

    load_previous_tracked()

    if SNAPSHOT_MODE:
        stats = run_snapshot_sweep(eth_rate)
        _commit_output_se_serve()
        log(f"Bot Profit (snapshot) terminato. Riepilogo: {stats}")
        return

    commit_thread = threading.Thread(target=_periodic_commit_loop, daemon=True)
    commit_thread.start()
    log(f"Thread di commit periodico avviato (ogni {COMMIT_CHUNK_SECONDS}s se ci sono modifiche)")

    stats = run_listener(eth_rate)

    _stop_periodic_commit.set()
    commit_thread.join(timeout=10)

    _commit_output_se_serve()

    log(f"Bot Profit terminato. Riepilogo: {stats}")


if __name__ == '__main__':
    main()
