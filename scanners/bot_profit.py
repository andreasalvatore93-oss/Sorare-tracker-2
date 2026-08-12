"""
Bot Profit -- listener di mercato Sorare (stesso modello di Bot Supremo) che NON
punta ne' offre: si limita a tracciare, per ogni carta incontrata (limited, in
season + classic), i dati necessari a stimare il "potenziale di crescita di
valore" verso la prossima partita del giocatore.

REGOLA CHIAVE campionati MLS/K-League/Eredivisie/Belgio (vedi EXCLUDED_LEAGUE_SLUGS):
in_season e classic sono due mercati completamente separati (due "giocatori
diversi" ai fini del tracciamento) -- due righe distinte, ognuna col proprio
storico transazioni e proprio minimo, mai mescolati. Per TUTTI gli altri
campionati: un giocatore = una riga sola, in_season+classic mescolati (stesso
identico criterio di Bot Supremo).

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
  - prezzo_basso_o_senza_annunci in modalita' SNAPSHOT (min_attuale sotto
    soglia o nessun annuncio live, scoperto DOPO la query combinata) ->
    blacklist PREZZO_BASSO_SKIP_DAYS giorni (default 2, FIX 29/07: verificato
    su run reali ravvicinate che il prezzo minimo resta quasi sempre
    invariato su questa scala di tempo, e il bot serve solo 1-2 snapshot al
    giorno -- taglia dalla run successiva circa il 25-30% del volume di
    richieste verso Sorare, la quota tipica di questo esito)

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
separate per lega; FIX 29/07 quinquies, estensione Eredivisie/Belgio:
classifiche per GRUPPO, vedi OUTPUT_GROUPS -- Eredivisie e Belgio condividono
lo stesso file, mescolate) in bot_profit_output/ (cartella in root del repo,
non sotto scanners/), CLASSIFICA PERSISTENTE che si aggiorna nel tempo
(ricaricata ad ogni avvio, non riparte mai vuota) -- in_season e classic
mescolati nella stessa riga (distinti dalla colonna tipo_carta), un file per
gruppo:
  - profit_tracking_mlspa_<timestamp_utc>.csv -> top 50 carte MLS per potenziale_score
  - profit_tracking_k-league-1_<timestamp_utc>.csv -> top 50 carte K-League per potenziale_score
  - profit_tracking_eredivisie_belgio_<timestamp_utc>.csv -> top 50 carte Eredivisie+Belgio MESCOLATE per potenziale_score
  - profit_tracking_global_<timestamp_utc>.csv -> FIX 30/07 sera (richiesta
    esplicita utente): le righe GIA' scritte nei 3 file sopra, rimescolate in
    un'unica classifica ordinata per verdetto/punteggio_occasione (vedi
    _write_global_csv) -- e' l'unico file che la notifica Telegram legge ora.
Il nome include data/ora UTC (formato YYYYMMDD_HHMM); ad ogni riscrittura il
file con timestamp precedente (PER QUEL GRUPPO) viene cancellato, quindi ne
resta sempre e solo uno per gruppo (il piu' recente). Riscritto ad ogni commit
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
import itertools
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
# 12/08: alza il tetto di rate/complessita' sull'account, si aggiunge al cookie.
APIKEY = os.environ.get('SORARE_APIKEY', '')

# TRE CHIAVI A ROTAZIONE (12/08/2026 sera). Ogni APIKEY Sorare vale 200
# richieste/minuto e i tetti sono INDIPENDENTI (documentazione:
# github.com/sorare/api, verificato in laboratorio). Questo bot gira come UN
# processo con 10 thread e a ritmo base 0,2s punta a ~300 richieste/minuto:
# con una chiave sola sfonda comunque il tetto di 200. Ruotando le tre chiave
# per richiesta il tetto sale a 600 e il ritmo attuale ci sta dentro senza
# toccare nient'altro.
#
# Il motivo per cui questo file era pieno di freni si legge nei commenti piu'
# sotto ("423 HTTP 429 su ~1300-1500 richieste", ritmo SAFE a 0,9s = 66
# richieste/minuto): erano tarati contro il tetto della SESSIONE COL COOKIE,
# che vale 60/minuto. Quel muro con la chiave non c'e' piu'.
#
# Se le chiavi 2 e 3 non sono impostate si usa solo la prima: comportamento
# identico a prima, nessuna regressione.
_APIKEYS = [k for k in (APIKEY,
                        os.environ.get('SORARE_APIKEY_2', ''),
                        os.environ.get('SORARE_APIKEY_3', '')) if k]
_apikey_giro = itertools.cycle(_APIKEYS) if _APIKEYS else None
_apikey_lock = threading.Lock()


def _prossima_apikey():
    """La chiave da usare per la prossima richiesta, a rotazione.
    Il lock serve perche' i thread di snapshot chiamano in parallelo e
    itertools.cycle non e' garantito thread-safe."""
    if not _apikey_giro:
        return ''
    with _apikey_lock:
        return next(_apikey_giro)


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

# Campionati "a due mercati separati" (in_season e classic non si mescolano
# mai, due righe distinte), identico a Bot Supremo -- J League ESCLUSA da
# questo filtro (logica normale, mercato unico).
# FIX 29/07 sexies (richiesta esplicita utente): aggiunte Eredivisie e Belgio --
# da oggi sono uscite le nuove carte in season, quindi tutte le carte in
# season fino a ieri sono ora classic, stesso identico ciclo gia' vissuto da
# MLS/K-League. Prima erano trattate come campionati "normali" (mercato
# unico, tipo_carta='misto') -- ora is_excluded_league() le tratta come le
# altre due, nessun'altra modifica necessaria (gia' tutto generico su questa
# funzione: _row_key, tipo_carta, _current_minimum_from_nodes,
# _countable_transactions_from_nodes).
EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1', 'eredivisie', 'jupiler-pro-league'}

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
# FIX 29/07 quinquies (richiesta esplicita utente: estendere a Eredivisie e Belgio,
# MESCOLATI in un solo output invece di uno per lega -- diverso da MLS/K-League
# che restano separate). Slug squadre confermati DAL VIVO (29/07) con la query
# pubblica gia' documentata per K-League (formazione_kleague/discovery/
# kleague_mid_discovery_global.py): `football { competition(slug: "eredivisie") {
# clubs(first: 50) { nodes { slug name } } } }` (18 squadre) e stesso pattern con
# slug "jupiler-pro-league" (18 squadre) -- nessuna supposizione, verificato live.
_EREDIVISIE_TEAM_SLUGS_DEFAULT = (
    'ado-den-haag-den-haag,az-alkmaar,ajax-amsterdam,cambuur-leeuwarden,excelsior-rotterdam,'
    'feyenoord-rotterdam,fortuna-sittard-sittard,go-ahead-eagles-deventer,groningen-groningen,'
    'heerenveen-heerenveen-1920,nec-nijmegen,pec-zwolle-zwolle,psv-eindhoven,sparta-rotterdam-rotterdam,'
    'telstar-velsen-zuid,twente-enschede,utrecht-utrecht,willem-ii-tilburg'
)
_BELGIO_TEAM_SLUGS_DEFAULT = (
    'anderlecht-bruxelles-brussel,antwerp-deurne,cercle-brugge-brugge,club-brugge-brugge,'
    'genk-genk,gent-gent,kortrijk-kortrijk,la-louviere-la-louviere,lommel-lommel,'
    'mechelen-mechelen-malines,oh-leuven-heverlee,sint-truiden-sint-truiden-st-trond,'
    'sporting-charleroi-charleroi,standard-liege-liege-luik,union-saint-gilloise-bruxelles-brussels,'
    'waasland-beveren-beveren-waas,westerlo-westerlo,zulte-waregem-waregem'
)
MLS_TEAM_WHITELIST = [s.strip() for s in os.environ.get('TEAM_WHITELIST', _MLS_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
KLEAGUE_TEAM_WHITELIST = [s.strip() for s in os.environ.get('KLEAGUE_TEAM_WHITELIST', _KLEAGUE_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
EREDIVISIE_TEAM_WHITELIST = [s.strip() for s in os.environ.get('EREDIVISIE_TEAM_WHITELIST', _EREDIVISIE_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
BELGIO_TEAM_WHITELIST = [s.strip() for s in os.environ.get('BELGIO_TEAM_WHITELIST', _BELGIO_TEAM_SLUGS_DEFAULT).split(',') if s.strip()]
# Mappa squadra -> lega (sostituisce la vecchia costante globale SNAPSHOT_LEAGUE_SLUG,
# che assumeva UNA sola lega per l'intera run): tutte le leghe vengono processate
# insieme in una sola run, ciascuna squadra sa gia' a quale lega appartiene.
# Eredivisie/Belgio NON sono in EXCLUDED_LEAGUE_SLUGS (non sono mercati "a due
# binari" come MLS/K-League) -- in_season+classic si mescolano automaticamente
# in una riga sola per giocatore (tipo_carta='misto'), stesso criterio identico
# di Bot Supremo per tutti i campionati "normali".
TEAM_LEAGUE_MAP = {}
TEAM_LEAGUE_MAP.update({slug: 'mlspa' for slug in MLS_TEAM_WHITELIST})
TEAM_LEAGUE_MAP.update({slug: 'k-league-1' for slug in KLEAGUE_TEAM_WHITELIST})
TEAM_LEAGUE_MAP.update({slug: 'eredivisie' for slug in EREDIVISIE_TEAM_WHITELIST})
TEAM_LEAGUE_MAP.update({slug: 'jupiler-pro-league' for slug in BELGIO_TEAM_WHITELIST})
TEAM_WHITELIST = list(TEAM_LEAGUE_MAP.keys())

# FIX 24/07 (richiesta esplicita utente, promemoria applicato ora): prima nessun
# default (obbligatorio ad ogni run), ora default 100 minuti -- resta comunque
# sovrascrivibile dal workflow_dispatch.
LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '6000'))

# Commit periodico dei dati tracciati -- default 30 secondi (FIX 29/07, era
# 300/5 minuti: richiesta esplicita utente, dopo aver verificato che una
# cancellazione manuale della run non salva NULLA di quanto tracciato/
# blacklistato dall'ultimo commit periodico in poi -- il commit di fallback
# "if: always()" nel workflow non ha mai prodotto un commit reale nei 3 casi
# osservati. Un intervallo cosi' breve limita la perdita a pochi secondi di
# lavoro in caso di stop manuale).
COMMIT_CHUNK_SECONDS = int(os.environ.get('COMMIT_CHUNK_SECONDS', '30'))

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
MIN_PRICE_EUR_THRESHOLD = float(os.environ.get('MIN_PRICE_EUR_THRESHOLD', '2.5'))

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
# FIX 29/07 (richiesta esplicita utente, ridurre i 429 e la durata della run):
# verificato su run reali ravvicinate (Korea da sola e MLS+Korea insieme) che il
# prezzo minimo di una carta resta quasi sempre identico al centesimo su scale
# di tempo di minuti -- niente occasioni perse a saltare a costo zero, per un
# TTL ampio, i giocatori gia' scartati per prezzo sotto soglia/nessun annuncio.
# L'utente usa questo bot solo 1-2 volte al giorno (e' uno snapshot di mercato,
# non serve piu' fresco di cosi') e ha chiesto esplicitamente una finestra di
# almeno 2 giorni ("difficilmente un giocatore varia cosi' tanto di prezzo su
# Sorare in 2 giorni") -- taglia dalla run successiva circa il 25-30% del
# volume di richieste verso Sorare (la quota tipica di questo esito), verificato
# su run reali: 429 -57%, durata -39% con TTL attivo su MLS+Korea insieme.
PREZZO_BASSO_SKIP_DAYS = float(os.environ.get('PREZZO_BASSO_SKIP_DAYS', '2'))

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
#
# FIX 30/07 -- RITMO ADATTIVO + BARRIERA GLOBALE (richiesta esplicita utente:
# risolvere il rate limit "per davvero", non arginarlo, in vista di TUTTI i
# campionati e non solo 3). Analisi dei log reali delle run 66/69/71/72:
#
#   run 66 (a freddo)  16m58s  835 HTTP 429  ~1150 richieste andate a buon fine
#   run 69             12m21s  551 HTTP 429
#   run 71              7m23s  291 HTTP 429
#   run 72 (a regime)   4m37s   36 HTTP 429
#
# Nella run 72 il PRIMO 429 e' scattato esattamente 122s dopo la prima query,
# cioe' dopo ~600 richieste al ritmo di 0.2s -- e nella run 66 il log mostra un
# ciclo regolare di ~2 minuti di lavoro pulito seguiti da ~2-3 minuti quasi
# completamente bloccati (minuti interi con 110+ 429 e ZERO giocatori
# completati). Il comportamento e' quello di un token bucket lato Sorare:
# capienza ~600 richieste, ricarica di ~1.5-2 richieste al secondo. Il ritmo
# fisso di 0.2s (5 req/s) e' quindi ~3 volte oltre il sostenibile: una volta
# svuotato il secchio non c'e' ritmo "sicuro" che tenga, e i 10 worker
# continuavano a sbattere contro il muro ognuno per conto suo (ogni 429 costava
# fino a 2+4+16=22s di backoff SOLO a quel thread, mentre gli altri 9
# continuavano a generare altri 429).
#
# Due cambiamenti, entrambi mirati alla causa e non al sintomo:
#  1) BARRIERA GLOBALE: quando arriva un 429 si alza una pausa CONDIVISA da
#     tutti i thread (nessuno parte finche' non scade), invece di far
#     aspettare solo lo sfortunato. Un 429 quindi non si moltiplica piu' per
#     il numero di worker. I 429 che arrivano mentre la barriera e' gia'
#     alzata sono la coda della stessa ondata e NON vengono contati come
#     nuova penalita' (altrimenti 10 worker moltiplicherebbero per 10 la
#     reazione a un singolo evento).
#  2) RITMO ADATTIVO (AIMD, stessa idea del controllo di congestione TCP):
#     si parte veloci (GRAPHQL_MIN_INTERVAL_SECONDS_FAST, che sfrutta la
#     capienza iniziale del secchio), a ogni ondata di 429 l'intervallo viene
#     moltiplicato per GRAPHQL_PACE_BACKOFF_FACTOR, e dopo
#     GRAPHQL_PACE_RECOVER_EVERY richieste consecutive andate a buon fine
#     viene riavvicinato al pavimento. Cosi' il bot TROVA DA SOLO il ritmo
#     sostenibile del momento invece di usarne uno tarato a mano su una run
#     passata -- ed e' la parte che regge l'aggiunta di nuovi campionati:
#     piu' volume non significa piu' 429, significa solo che il ritmo si
#     assesta dove Sorare lo consente.
#
# Effetto atteso (e motivo per cui non e' un compromesso velocita/429): oggi il
# tempo perso NON e' nell'attesa, e' nelle richieste sprecate. Nella run 66,
# 835 429 su ~2000 richieste totali = il 42% del traffico buttato, piu' i
# backoff. Andare al ritmo giusto fin da subito significa fare MENO richieste
# in totale e non restare bloccati per minuti interi.
GRAPHQL_MIN_INTERVAL_SECONDS_FAST = float(os.environ.get('GRAPHQL_MIN_INTERVAL_SECONDS_FAST', '0.2'))
# Ritmo sostenibile stimato, cioe' il PAVIMENTO valido DOPO il primo 429 della
# run (prima resta GRAPHQL_MIN_INTERVAL_SECONDS_FAST).
#
# MISURATO sulla run 73 (la prima con questo codice): 470 richieste in 637s con
# 4 ondate di 429. Escludendo i ~180s di pausa forzata, il ritmo effettivo e'
# stato ~1.03 richieste/s, e le ondate scattavano ancora a 0.72s/richiesta
# (1.39/s) -- il sostenibile vero sta quindi intorno a 1 richiesta/s, non alle
# 1.8/s stimate dal solo comportamento iniziale.
#
# Perche' e' un PAVIMENTO e non un semplice punto di partenza: la run 73 ha
# mostrato che Sorare risponde ai 429 con un header **Retry-After di ~45
# secondi** (le pause da 45.0s/40.0s/39.0s nel log non sono stime nostre --
# la nostra prima stima e' 5s -- sono il suo conto alla rovescia). Un 429
# costa quindi 45 secondi di fermo totale: la capienza iniziale del secchio e'
# un regalo che si spende UNA volta, e tornare a spingere dopo averla esaurita
# non fa recuperare tempo, lo fa perdere a blocchi da 45s. Da qui la scelta di
# non far piu' risalire il ritmo sopra questa soglia una volta incassato il
# primo 429.
GRAPHQL_MIN_INTERVAL_SECONDS_SAFE = float(os.environ.get('GRAPHQL_MIN_INTERVAL_SECONDS_SAFE', '0.9'))
# Tetto: oltre questo intervallo non si rallenta piu' (a 1.5s/richiesta siamo
# gia' ampiamente sotto la soglia sostenibile misurata, se Solare limita ancora
# il problema non e' il ritmo).
GRAPHQL_MAX_INTERVAL_SECONDS = float(os.environ.get('GRAPHQL_MAX_INTERVAL_SECONDS', '1.5'))
GRAPHQL_PACE_BACKOFF_FACTOR = float(os.environ.get('GRAPHQL_PACE_BACKOFF_FACTOR', '1.6'))
GRAPHQL_PACE_RECOVER_EVERY = int(os.environ.get('GRAPHQL_PACE_RECOVER_EVERY', '40'))
GRAPHQL_PACE_RECOVER_FACTOR = float(os.environ.get('GRAPHQL_PACE_RECOVER_FACTOR', '0.9'))
# Pausa globale (tutti i thread) alla prima ondata di 429; raddoppia a ogni
# ondata successiva fino al tetto, si dimezza quando il ritmo si riprende.
GRAPHQL_429_GLOBAL_PAUSE_SECONDS = float(os.environ.get('GRAPHQL_429_GLOBAL_PAUSE_SECONDS', '5.0'))
GRAPHQL_429_GLOBAL_PAUSE_MAX = float(os.environ.get('GRAPHQL_429_GLOBAL_PAUSE_MAX', '45.0'))
GRAPHQL_429_COOLDOWN_SECONDS = float(os.environ.get('GRAPHQL_429_COOLDOWN_SECONDS', '30.0'))
# Alzato da 3 a 5 (FIX 30/07): ora un tentativo fallito non costa piu' un
# backoff locale lungo, costa solo l'attesa della barriera globale che il bot
# avrebbe comunque rispettato -- ritentare di piu' e' quasi gratis e riduce i
# giocatori persi per 'rate_limited_max_retries_exceeded' (30 persistenti nella
# run 66).
GRAPHQL_MAX_RETRIES = int(os.environ.get('GRAPHQL_MAX_RETRIES', '5'))
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]
_graphql_last_429_ts = [0.0]
_pace_interval = [GRAPHQL_MIN_INTERVAL_SECONDS_FAST]
# Pavimento corrente della ripresa: parte da FAST (finche' la capienza iniziale
# del secchio regge) e diventa SAFE dopo il primo 429 -- vedi il commento su
# GRAPHQL_MIN_INTERVAL_SECONDS_SAFE.
_pace_floor = [GRAPHQL_MIN_INTERVAL_SECONDS_FAST]
_pace_ok_streak = [0]
_pace_blocked_until = [0.0]
_pace_penalty = [0.0]
_pace_429_totali = [0]
_pace_ondate = [0]

# ESPERIMENTO 29/07 (richiesta esplicita utente, osservazione su un log reale):
# nella run delle 07:35 il primo 429 e' scattato solo dopo ~1m39s e ~250
# giocatori analizzati SENZA NESSUN 429 -- poi, una volta scattato, e' stata
# sostanzialmente una raffica ininterrotta. Ipotesi testata: Sorare non limita
# per "ritmo istantaneo" ma per QUANTITA' di richieste in una finestra
# scorrevole -- una pausa fissa periodica (60s lavoro / 20s pausa,
# indipendente dai 429) avrebbe dovuto "svuotare" quella finestra prima che
# scattasse. RISULTATO: SMENTITA. Run di verifica (07:52-07:54): primo 429
# scattato comunque a ~2 minuti dall'inizio, stesso punto della run senza
# pausa. Il limite sembra legato al TEMPO TRASCORSO, non al conteggio di
# richieste in coda -- una pausa non "resetta" nulla. Lasciato disattivato di
# default (0) ma il meccanismo resta disponibile via env var nel caso si
# voglia testare un work/pause diverso in futuro.
GRAPHQL_BURST_WORK_SECONDS = float(os.environ.get('GRAPHQL_BURST_WORK_SECONDS', '0'))
GRAPHQL_BURST_PAUSE_SECONDS = float(os.environ.get('GRAPHQL_BURST_PAUSE_SECONDS', '20.0'))
_burst_window_start = [None]
_burst_paused_until = [0.0]


def _graphql_throttle():
    """Ritmo globale adattivo + barriera condivisa (vedi il blocco di commento
    sopra le costanti GRAPHQL_PACE_*). Due attese distinte:
      - la BARRIERA (_pace_blocked_until): nessun thread parte finche' non
        scade, e' la reazione condivisa a un'ondata di 429;
      - lo SLOT di ritmo: ogni chiamante si prenota il prossimo istante utile
        spostando _graphql_last_call_ts, cosi' N thread si distribuiscono
        ordinatamente invece di dormire tutti fino allo stesso istante e poi
        partire insieme (che era il difetto della versione precedente)."""
    while True:
        with _graphql_throttle_lock:
            now = time.time()
            attesa_burst = 0.0
            if GRAPHQL_BURST_WORK_SECONDS > 0:
                if _burst_window_start[0] is None:
                    _burst_window_start[0] = now
                if now < _burst_paused_until[0]:
                    attesa_burst = _burst_paused_until[0] - now
                elif now - _burst_window_start[0] >= GRAPHQL_BURST_WORK_SECONDS:
                    _burst_paused_until[0] = now + GRAPHQL_BURST_PAUSE_SECONDS
                    _burst_window_start[0] = _burst_paused_until[0]
                    attesa_burst = GRAPHQL_BURST_PAUSE_SECONDS
                    log(f"[burst] {GRAPHQL_BURST_WORK_SECONDS:.0f}s di lavoro completati, "
                        f"pausa fissa di {GRAPHQL_BURST_PAUSE_SECONDS:.0f}s...")
            # max() e non somma: sono due pause indipendenti (barriera 429 e
            # pausa fissa sperimentale), aspettare la piu' lunga le soddisfa
            # entrambe. Sommandole, una barriera gia' scaduta (valore negativo)
            # avrebbe potuto annullare una pausa burst ancora attiva.
            attesa_barriera = max(_pace_blocked_until[0] - now, attesa_burst)
            if attesa_barriera <= 0:
                slot = max(now, _graphql_last_call_ts[0] + _pace_interval[0])
                _graphql_last_call_ts[0] = slot
                attesa_slot = slot - now
                break
        # Fuori dal lock: dormire tenendolo bloccherebbe anche chi deve solo
        # registrare un esito. Si ricontrolla in cima al giro perche' nel
        # frattempo un altro thread puo' aver allungato la barriera.
        time.sleep(min(attesa_barriera, 2.0))
    if attesa_slot > 0:
        time.sleep(attesa_slot)
    # Uno slot prenotato puo' cadere DOPO che un altro thread ha alzato la
    # barriera (con 10 worker gli slot sono prenotati fino a ~10 intervalli
    # avanti): senza questo secondo controllo quelle richieste partirebbero
    # comunque contro il muro, che e' esattamente cio' che la barriera esiste
    # per evitare. Qui NON si riprenota lo slot -- e' gia' stato consumato,
    # si aspetta solo che la barriera cada.
    while True:
        with _graphql_throttle_lock:
            residuo = _pace_blocked_until[0] - time.time()
        if residuo <= 0:
            return
        time.sleep(min(residuo, 2.0))


def _pace_registra_429(retry_after=None):
    """Registra un 429. Ritorna (pausa_globale_applicata, intervallo_corrente):
    pausa_globale_applicata e' None se questo 429 e' stato riconosciuto come
    coda di un'ondata gia' gestita (nessuna nuova penalita')."""
    with _graphql_throttle_lock:
        now = time.time()
        _graphql_last_429_ts[0] = now
        _pace_429_totali[0] += 1
        _pace_ok_streak[0] = 0
        nuova_ondata = now >= _pace_blocked_until[0]
        pausa = None
        if nuova_ondata:
            _pace_ondate[0] += 1
            # Dal primo 429 in poi la capienza iniziale del secchio e' esaurita:
            # il pavimento della ripresa sale al ritmo sostenibile misurato,
            # cosi' l'AIMD non riporta il bot a spingere fino al 45s successivo.
            _pace_floor[0] = GRAPHQL_MIN_INTERVAL_SECONDS_SAFE
            _pace_interval[0] = max(
                min(_pace_interval[0] * GRAPHQL_PACE_BACKOFF_FACTOR, GRAPHQL_MAX_INTERVAL_SECONDS),
                _pace_floor[0],
            )
            _pace_penalty[0] = min(
                max(_pace_penalty[0] * 2, GRAPHQL_429_GLOBAL_PAUSE_SECONDS),
                GRAPHQL_429_GLOBAL_PAUSE_MAX,
            )
            pausa = _pace_penalty[0]
            # Un Retry-After esplicito di Sorare vale piu' di qualunque stima
            # nostra (sulla run 73 diceva ~45s, contro i 5s che stimavamo noi).
            # Applicato SOLO qui, sulla nuova ondata: i 429 successivi sono le
            # risposte di richieste gia' in volo quando la barriera si e'
            # alzata, e usarli per riallungare la barriera la faceva scorrere in
            # avanti a ogni straggler -- attesa piu' lunga del necessario per un
            # evento gia' gestito.
            if retry_after is not None:
                pausa = max(pausa, min(retry_after, GRAPHQL_429_GLOBAL_PAUSE_MAX))
            _pace_blocked_until[0] = max(_pace_blocked_until[0], now + pausa)
        return pausa, _pace_interval[0]


def _pace_registra_successo():
    """Ripresa graduale: dopo GRAPHQL_PACE_RECOVER_EVERY richieste consecutive
    riuscite, il ritmo torna un passo verso il pavimento. Serve a non restare
    lenti per il resto della run dopo una singola ondata passeggera."""
    with _graphql_throttle_lock:
        _pace_ok_streak[0] += 1
        if (_pace_ok_streak[0] >= GRAPHQL_PACE_RECOVER_EVERY
                and _pace_interval[0] > _pace_floor[0]):
            _pace_ok_streak[0] = 0
            _pace_interval[0] = max(
                _pace_interval[0] * GRAPHQL_PACE_RECOVER_FACTOR, _pace_floor[0])
            _pace_penalty[0] = _pace_penalty[0] / 2


def _pace_riepilogo():
    with _graphql_throttle_lock:
        return (f"HTTP 429 totali: {_pace_429_totali[0]} in {_pace_ondate[0]} ondate distinte "
                f"(ogni ondata costa ~45s di fermo, e' il Retry-After di Sorare), "
                f"ritmo finale: {_pace_interval[0]:.2f}s/richiesta "
                f"(pavimento corrente {_pace_floor[0]:.2f}s)")


def _retry_after_seconds(response):
    """Retry-After di Sorare, se presente. Gestita solo la forma numerica (in
    secondi), non la variante con data HTTP: non e' mai stata osservata nei log
    e interpretarla male sarebbe peggio che ignorarla. None se assente o
    illeggibile -- in quel caso vale la stima interna."""
    valore = None
    try:
        valore = response.headers.get('Retry-After') or response.headers.get('retry-after')
    except Exception:
        return None
    if not valore:
        return None
    try:
        return max(float(str(valore).strip()), 0.0)
    except ValueError:
        return None


def graphql_query(query, variables=None, max_retries=None):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF_TOKEN,
        **({'APIKEY': _prossima_apikey()} if _APIKEYS else {}),
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
    if max_retries is None:
        max_retries = GRAPHQL_MAX_RETRIES
    for attempt in range(max_retries):
        _graphql_throttle()
        r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            # FIX 30/07: niente piu' backoff LOCALE del singolo thread (era
            # 2/4/16s, quindi fino a 22s buttati da ogni thread mentre gli
            # altri continuavano a generare altri 429). Ora la pausa e'
            # GLOBALE e viene decisa una volta sola per ondata da
            # _pace_registra_429 -- al giro successivo _graphql_throttle()
            # aspetta la barriera per conto di tutti. Log emesso SOLO alla
            # nuova ondata: nella run 66 questa riga era stampata 835 volte.
            pausa, ritmo = _pace_registra_429(_retry_after_seconds(r))
            if pausa:
                log(f"[rate limit] HTTP 429: pausa globale di {pausa:.1f}s per tutti i thread, "
                    f"ritmo rallentato a {ritmo:.2f}s/richiesta (ondata #{_pace_ondate[0]})")
            continue
        # FIX 29/07 (bug reale, run crashata: Sorare ha risposto con un body
        # vuoto/non-JSON, probabile errore 5xx transitorio -- r.json() faceva
        # esplodere l'intera run con un JSONDecodeError non gestito, perso
        # tutto il lavoro fatto finora. Trattato come il 429: retry con lo
        # stesso backoff, poi errore esplicito (gia' gestito da tutti i
        # chiamanti via data.get('errors')) se i tentativi si esauriscono,
        # invece di un crash fatale.
        try:
            data = r.json()
        except ValueError:
            wait_seconds = min((2 ** attempt) * 2, 16.0)
            log(f"[errore HTTP] risposta non-JSON (status {r.status_code}, tentativo "
                f"{attempt + 1}/{max_retries}), attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        _pace_registra_successo()
        return data
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

# =====================================================================================
# CACHE ROSTER SU DISCO (FIX 30/07, richiesta esplicita utente: ridurre il rate
# limit in vista di TUTTI i campionati)
#
# Il roster e' la meta' NASCOSTA del costo di una run: nella run 72 le 78
# squadre hanno richiesto 78 query di prima pagina + le pagine successive
# (roster storici da 111 a 229 giocatori, quindi 2-3 pagine ciascuna) = ~190
# richieste, spese nei primi 45 secondi su 275 totali. Con tutti i campionati
# (~27 leghe x ~18 squadre) diventerebbero da sole oltre 1000 richieste PRIMA
# ancora di guardare un prezzo.
#
# Ma il contenuto di quella query cambia pochissimo: chi e' in rosa e le medie
# L5/L10/L40 si muovono SOLO quando si gioca una partita, cioe' una volta a
# settimana per squadra -- mentre il bot fa 1-2 snapshot di mercato al giorno.
# Ricaricarlo ad ogni run e' spreco puro. Qui viene salvato su disco (JSON
# committato nel repo come i CSV, cosi' sopravvive tra una run GitHub Actions e
# l'altra) e riusato entro ROSTER_CACHE_HOURS.
#
# La cache memorizza il roster GIA' FILTRATO (stessa logica di fetch_team_roster:
# solo giocatori ancora al club e sopra ROSTER_MIN_AVG_SCORE). Se la soglia
# cambia, la voce viene considerata non valida e la squadra si riscarica -- cosi'
# un cambio di parametro non resta silenziosamente "congelato" nella cache.
ROSTER_CACHE_PATH = os.environ.get('ROSTER_CACHE_PATH', 'bot_profit_roster_cache.json')
ROSTER_CACHE_HOURS = float(os.environ.get('ROSTER_CACHE_HOURS', '48'))

_roster_cache_lock = threading.Lock()
_roster_cache = [None]
_roster_cache_modificata = [False]
_roster_cache_stats = {'da_cache': 0, 'scaricati': 0}


def _roster_cache_leggi():
    with _roster_cache_lock:
        if _roster_cache[0] is None:
            dati = {}
            if os.path.exists(ROSTER_CACHE_PATH):
                try:
                    with open(ROSTER_CACHE_PATH, 'r', encoding='utf-8') as f:
                        letto = json.load(f)
                    if isinstance(letto, dict) and isinstance(letto.get('squadre'), dict):
                        dati = letto['squadre']
                except (ValueError, OSError) as e:
                    log(f"[cache roster] file illeggibile ({e}), riparto da cache vuota")
            _roster_cache[0] = dati
        return _roster_cache[0]


def _roster_da_cache(team_slug):
    """Roster valido in cache per questa squadra, o None se assente/scaduto."""
    if ROSTER_CACHE_HOURS <= 0:
        return None
    voce = _roster_cache_leggi().get(team_slug)
    if not voce:
        return None
    if voce.get('soglia_media') != ROSTER_MIN_AVG_SCORE:
        return None
    try:
        scaricato = datetime.datetime.fromisoformat(voce['scaricato_il'])
    except (KeyError, ValueError, TypeError):
        return None
    eta_ore = (datetime.datetime.now(datetime.timezone.utc) - scaricato).total_seconds() / 3600.0
    if eta_ore > ROSTER_CACHE_HOURS:
        return None
    roster = []
    for p in voce.get('giocatori') or []:
        roster.append((p['slug'], p.get('nome') or p['slug'], {
            'l5': p.get('l5'), 'l10': p.get('l10'), 'l40': p.get('l40'),
            'squadra': p.get('squadra'), 'squadra_slug': p.get('squadra_slug'),
            'prossimo_avversario': None, 'next_game_date_str': None,
            'ultima_partita_score': None, 'match_dates': [],
        }))
    return roster, eta_ore


def _roster_salva_in_cache(team_slug, roster):
    with _roster_cache_lock:
        if _roster_cache[0] is None:
            _roster_cache[0] = {}
        _roster_cache[0][team_slug] = {
            'scaricato_il': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'soglia_media': ROSTER_MIN_AVG_SCORE,
            'giocatori': [
                {'slug': slug, 'nome': nome, 'l5': snap.get('l5'), 'l10': snap.get('l10'),
                 'l40': snap.get('l40'), 'squadra': snap.get('squadra'),
                 'squadra_slug': snap.get('squadra_slug')}
                for slug, nome, snap in roster
            ],
        }
        _roster_cache_modificata[0] = True


def scrivi_roster_cache():
    with _roster_cache_lock:
        if not _roster_cache_modificata[0] or _roster_cache[0] is None:
            return
        dati = {'squadre': _roster_cache[0]}
        _roster_cache_modificata[0] = False
    try:
        with open(ROSTER_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(dati, f, ensure_ascii=False, indent=1, sort_keys=True)
        log(f"[cache roster] salvata ({len(dati['squadre'])} squadre) in {ROSTER_CACHE_PATH}")
    except OSError as e:
        log(f"[cache roster] impossibile salvare {ROSTER_CACHE_PATH}: {e}")


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
    Sorare.

    FIX 30/07 (richiesta esplicita utente, rate limit): prima di scaricare si
    controlla la cache su disco (vedi ROSTER_CACHE_PATH) -- rosa e medie
    L5/L10/L40 cambiano solo quando si gioca, non serve rileggerle a ogni
    snapshot di mercato."""
    in_cache = _roster_da_cache(team_slug)
    if in_cache is not None:
        roster, eta_ore = in_cache
        _roster_cache_stats['da_cache'] += 1
        log(f"[roster] {team_slug}: {len(roster)} rilevanti da cache "
            f"(aggiornata {eta_ore:.1f}h fa, zero query)")
        return roster

    _roster_cache_stats['scaricati'] += 1
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
    # Non si mette in cache un roster vuoto: quasi sempre e' il sintomo di una
    # query andata male (errore GraphQL/rate limit, vedi i break sopra), non di
    # una squadra davvero senza giocatori rilevanti -- congelarlo per ore
    # cancellerebbe la squadra dalle run successive.
    if roster:
        _roster_salva_in_cache(team_slug, roster)
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
#
# RITARATO 30/07 sui dati reali (analisi del dataset grezzo
# bot_profit_output/pattern_raw_transactions_20260729_1845.csv, 3658
# transazioni / 142 carte, prodotto da bot_profit_pattern_export.py). Misura
# fatta: per ogni transazione, sconto rispetto alla media della stessa carta
# nei 3 giorni precedenti, e variazione % media del prezzo nelle 48h
# SUCCESSIVE. Incrociando sconto e trend (n = numero di casi):
#
#   sconto >=10%  trend down  n=173  mediana  +9.9%   68% positivi
#   sconto >=10%  trend flat  n=183  mediana +17.7%   84% positivi
#   sconto >=10%  trend up    n= 56  mediana +25.4%   88% positivi
#
# Il verso della vecchia taratura e' confermato (down peggio di flat, flat
# peggio di up), ma la PENALITA' ERA TROPPO DURA: 'down' non e' affatto un
# esito negativo (mediana +9.9%, due volte su tre in guadagno), mentre 0.5
# lo dimezzava fino a farlo sparire dalla classifica. Rapporto reale misurato
# 9.9/17.7 = 0.56 sul singolo bucket ma solo 0.51/... sui bucket di sconto
# piu' bassi (dati piu' rumorosi, n minore) -- adottato 0.65, prudente ma non
# punitivo, e 1.25 per 'up' (rapporto misurato 25.4/17.7 = 1.44, tenuto piu'
# basso perche' e' il bucket con meno campioni).
TREND_SCORE_MULTIPLIER = {'up': 1.25, 'flat': 1.0, 'down': 0.65, None: 0.85}

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


# FIX 30/07: 'segnale', 'punteggio_occasione', 'motivo_segnale' e
# 'aggiornato_il' sono le colonne del verdetto per-carta (vedi valuta_occasione)
# -- messe SUBITO dopo il nome, sono la prima cosa che si legge aprendo il file.
CSV_FIELDNAMES = [
    'player_slug', 'player_name', 'segnale', 'punteggio_occasione', 'motivo_segnale',
    'link_sorare', 'league_slug', 'tipo_carta', 'potenziale_score',
    'squadra', 'prossimo_avversario',
    'ultima_partita_score', 'l5', 'l10', 'l40',
    'min_attuale_eur', 'media_transazioni_7gg_trimmed_eur', 'n_transazioni_usate',
    'sconto_percent', 'trend_recente', 'media_transazioni_recente_eur', 'media_transazioni_storica_eur',
    'prossima_partita_data', 'ore_alla_partita', 'finestra_acquisto_ideale', 'aggiornato_il',
    'ultimo_tipo_evento',
]

# FIX 29/07 (richiesta esplicita utente, analisi pattern_raw_transactions_
# 20260729_1845.csv, script bot_profit_pattern_export.py): PRIMA versione
# (finestra -3gg/-1gg a bucket interi) era SBAGLIATA -- verificato dopo la
# richiesta esplicita dell'utente di ricontrollare i calcoli, rifacendo
# l'analisi a grana piu' fine (bin da 0.5gg invece di 1gg intero): -2gg e -1gg
# NON sono affatto uno sconto, sono anzi un SOVRAPPREZZO (+3/+8% su tutte e 3
# le leghe, il prezzo sale avvicinandosi al kickoff) -- lo sconto reale e'
# concentrato strettamente in un picco stretto a -3.5/-3.0gg PRIMA del kickoff
# della partita di quel giocatore (non della gameweek collettiva -- ogni
# squadra ha il proprio orario reale), confermato sui bin piu' fini su tutte e
# 3 le leghe individualmente (MLS -13.9%/-17.7%, Korea -15.3%/-16.0%,
# Eredivisie/Belgio -6.6%/-3.7%) e sul dataset combinato (-12.5%/-10.0%,
# n=71/103). Finestra corretta: da 3.5 a 2.5 giorni PRIMA del kickoff (mezza
# giornata di tolleranza attorno al picco -3gg, richiesta esplicita utente),
# non piu' un range largo fino a -1gg. Colonna derivata a costo zero da
# prossima_partita_data gia' presente, nessuna query aggiuntiva -- calcolata
# al momento della scrittura del CSV (vedi _finestra_acquisto_ideale), non
# serve toccare gli altri punti dove le righe vengono costruite/aggiornate.
BUY_WINDOW_DAYS_BEFORE_MAX = 3.5
BUY_WINDOW_DAYS_BEFORE_MIN = 2.5


# Stessi limiti espressi in ORE (invece di giorni) -- FIX 29/07 ter (richiesta
# esplicita utente: top pick ricalibrati su chi e' DAVVERO nella finestra
# ORA, non solo il potenziale_score piu' alto in assoluto): riusa ore_alla_partita,
# gia' presente in ogni riga del CSV, per un check "sono dentro la finestra
# adesso?" senza dover riparsare prossima_partita_data -- stesso identico
# calcolo, solo espresso nell'unita' gia' disponibile a valle (viewer/notifica
# Telegram, che non hanno accesso alle funzioni Python di bot_profit.py).
BUY_WINDOW_HOURS_MAX = BUY_WINDOW_DAYS_BEFORE_MAX * 24
BUY_WINDOW_HOURS_MIN = BUY_WINDOW_DAYS_BEFORE_MIN * 24


def _buy_window_bounds(prossima_partita_data_iso):
    """(start, end) della finestra ideale in UTC, o None se la data manca/non
    e' parsabile. Fattorizzato (FIX 29/07 ter) per essere riusato sia da
    _finestra_acquisto_ideale (colonna CSV) sia da chi voglia controllare se
    ADESSO si e' dentro la finestra (vedi bot_profit_telegram_notify.py)."""
    if not prossima_partita_data_iso:
        return None
    try:
        match_dt = datetime.datetime.fromisoformat(prossima_partita_data_iso.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    start = match_dt - datetime.timedelta(days=BUY_WINDOW_DAYS_BEFORE_MAX)
    end = match_dt - datetime.timedelta(days=BUY_WINDOW_DAYS_BEFORE_MIN)
    return start, end


def _finestra_acquisto_ideale(prossima_partita_data_iso):
    bounds = _buy_window_bounds(prossima_partita_data_iso)
    if bounds is None:
        return ''
    start, end = bounds
    if end < datetime.datetime.now(datetime.timezone.utc):
        return 'finestra gia\' passata'
    # FIX 29/07 ter (richiesta esplicita utente: colonna troppo larga nel
    # viewer, costringeva a scorrere a destra -- rimossa la ripetizione della
    # data partita, gia' visibile nella colonna prossima_partita_data a
    # fianco) -- formato compatto, solo le due date/ore della finestra.
    fmt = '%d/%m %H:%M'
    return f"{start.strftime(fmt)}-{end.strftime(fmt)} UTC"


# =====================================================================================
# SEGNALE DI ACQUISTO (FIX 30/07 -- richiesta esplicita utente: "dopo ogni
# snapshot voglio gia' sapere esattamente se quello e' un buon momento per
# comprare il giocatore analizzato... un segnale chiaro e forte nel csv")
#
# Fino a ieri il CSV rispondeva solo "quando sarebbe la finestra ideale"
# (finestra_acquisto_ideale) e dava un potenziale_score astratto: due
# informazioni generiche, che lasciavano all'utente il lavoro di incrociarle.
# Qui il bot prende posizione carta per carta.
#
# COME E' STATA DEFINITA LA REGOLA -- non a intuito, misurata sul dataset
# grezzo gia' presente nel repo (pattern_raw_transactions_20260729_1845.csv,
# 3658 transazioni reali su 142 carte, 3 gruppi di campionati). Domanda posta
# ai dati: "se compro una carta a questo prezzo, com'e' il prezzo di quella
# stessa carta nelle 48 ore successive?". Risposta, per fascia di sconto
# rispetto alla media della carta nei 3 giorni precedenti:
#
#   sconto      n     mediana a 48h    % di casi in guadagno
#   < 0%      1690      -4.3%                 33-42%
#   0-5%       295      +0.8%                   55%
#   5-10%      217      +3.2%                   59%
#   10-20%     315      +7.9%                   70%
#   >= 20%     310     +25.2%                   82%
#
# Lo SCONTO e' quindi il segnale dominante, ed e' monotono: piu' e' grande,
# piu' spesso e piu' forte il prezzo sale dopo. Uno sconto negativo
# (sovrapprezzo) e' altrettanto affidabile al contrario: perde in 6 casi su 10.
#
# I due modificatori, misurati sullo stesso dataset:
#  - TREND (vedi TREND_SCORE_MULTIPLIER): a parita' di sconto >=10%, mediana
#    +9.9% con trend 'down', +17.7% 'flat', +25.4% 'up'.
#  - FINESTRA TEMPORALE: a parita' di sconto >=10%, chi era dentro la finestra
#    -3.5/-2.5 giorni dal kickoff ha reso mediana +21.0% con il 93% di casi in
#    guadagno, contro +14.0% e 75% fuori finestra. La finestra quindi NON crea
#    l'occasione (uno sconto forte rende bene anche lontano dalla partita:
#    misurato +20.4% mediana, 88% positivi, a piu' di 5.5 giorni dal kickoff)
#    ma la amplifica di circa 1.4x. Per questo NON viene usata come filtro --
#    e' stata verificata e scartata l'idea di saltare del tutto le squadre
#    lontane dalla partita: avrebbe buttato via una delle fasce piu' redditizie.
#    A meno di 1.5 giorni dal kickoff, invece, il prezzo e' in PREMIO (dal
#    grafico per bin da mezza giornata: da +3.7% a +6.6% sopra la media della
#    carta): comprare li' e' il momento peggiore, penalizzato.
#
# PUNTEGGIO_OCCASIONE = stima del guadagno % a 48 ore, cioe' un numero che si
# legge direttamente ("questa carta vale circa +18%"), non un indice astratto
# tra 0 e 1 come potenziale_score. Interpolazione lineare sulle mediane
# misurate sopra, poi moltiplicata per trend e finestra.
BUY_SIGNAL_CURVE = (
    # (sconto_percent, guadagno_mediano_% misurato a 48h) -- punti centrali
    # delle fasce della tabella qui sopra; in mezzo si interpola linearmente
    # cosi' il punteggio e' continuo (con le fasce a gradino, due carte con
    # sconto 19.9% e 20.1% finivano in due mondi diversi).
    (0.0, 0.0),
    (2.5, 0.8),
    (7.5, 3.2),
    (15.0, 7.9),
    (30.0, 25.0),
)
BUY_SIGNAL_CURVE_SLOPE_OLTRE = 1.14   # pendenza oltre il 30% di sconto
BUY_SIGNAL_CURVE_CAP = 45.0           # tetto: oltre non ci sono dati che reggano
# Compressione della coda alta del punteggio FINALE (dopo trend e finestra).
# Senza, uno sconto del 50% con trend in salita dentro la finestra arriverebbe a
# +70% atteso: un numero che nessuna misura nel dataset sostiene (il bucket
# migliore osservato, sconto >=20% con trend 'up', ha mediana +25.4% e media
# +33.6%). Oltre la soglia l'eccedenza viene schiacciata invece che tagliata di
# netto: un taglio secco appiattirebbe le carte migliori tutte sullo stesso
# numero, perdendo l'ordine tra loro, mentre cosi' restano distinguibili senza
# promettere cifre fuori scala.
BUY_SIGNAL_COMPRESSIONE_SOPRA = 25.0
BUY_SIGNAL_COMPRESSIONE_FATTORE = 0.3
BUY_SIGNAL_PUNTEGGIO_CAP = 45.0
BUY_SIGNAL_WINDOW_MULT = 1.4          # dentro la finestra -3.5/-2.5gg
BUY_SIGNAL_IMMINENTE_MULT = 0.75      # partita a meno di BUY_SIGNAL_IMMINENTE_HOURS
# 54h = 2.25 giorni: e' il punto in cui, nei bin da mezza giornata del dataset
# grezzo, il prezzo smette di essere scontato e passa in PREMIO rispetto alla
# media della carta (-2.5gg: -4.2%, ma gia' -2.0gg: +6.6%, -1.5gg: +5.5%,
# -1.0gg: +3.7%, kickoff: +2.9%). Sotto questa soglia si compra caro.
BUY_SIGNAL_IMMINENTE_HOURS = 54.0

# Soglie dei livelli. COMPRA ORA vuole DUE condizioni insieme:
#  1) superare la soglia assoluta (un guadagno atteso che valga la pena),
#  2) essere tra i primi BUY_SIGNAL_MAX_PER_GRUPPO del proprio campionato.
# Il punto 2 non e' cosmetico: lo sconto medio varia enormemente da lega a lega
# e da momento a momento (nell'ultima run reale la mediana era +15.8% in MLS,
# +8.1% in K-League e -0.2% in Eredivisie/Belgio) -- con la sola soglia
# assoluta, in MLS sarebbero finite in giallo 27 righe su 50, che non e' un
# segnale ma un colore di sfondo. Il tetto per gruppo tiene il segnale
# selettivo qualunque sia lo stato del mercato di quella lega.
BUY_SIGNAL_SOGLIA_COMPRA = float(os.environ.get('BUY_SIGNAL_SOGLIA_COMPRA', '10.0'))
BUY_SIGNAL_SOGLIA_BUONA = float(os.environ.get('BUY_SIGNAL_SOGLIA_BUONA', '4.0'))
BUY_SIGNAL_MAX_PER_GRUPPO = int(os.environ.get('BUY_SIGNAL_MAX_PER_GRUPPO', '15'))

# Una riga della classifica persistente puo' venire da una run precedente (il
# CSV non riparte mai vuoto, vedi load_previous_tracked). Un prezzo di due
# giorni fa non puo' generare un "COMPRA ORA": oltre questa eta' il segnale
# viene sospeso e la riga lo dichiara esplicitamente.
SEGNALE_MAX_AGE_HOURS = float(os.environ.get('SEGNALE_MAX_AGE_HOURS', '12'))

SEGNALE_COMPRA = 'COMPRA ORA'
SEGNALE_BUONA = 'buona occasione'
SEGNALE_NEUTRO = 'neutro'
SEGNALE_EVITA = 'evita (sovrapprezzo)'
SEGNALE_NON_VALUTABILE = 'dato non aggiornato'
SEGNALE_RANK = {SEGNALE_COMPRA: 4, SEGNALE_BUONA: 3, SEGNALE_NEUTRO: 2,
                SEGNALE_EVITA: 1, SEGNALE_NON_VALUTABILE: 0}


def _guadagno_atteso_da_sconto(sconto_percent):
    """Interpolazione lineare sulla curva misurata (BUY_SIGNAL_CURVE)."""
    if sconto_percent is None or sconto_percent <= 0:
        return 0.0
    ultimo_x, ultimo_y = BUY_SIGNAL_CURVE[-1]
    if sconto_percent >= ultimo_x:
        return min(ultimo_y + (sconto_percent - ultimo_x) * BUY_SIGNAL_CURVE_SLOPE_OLTRE,
                   BUY_SIGNAL_CURVE_CAP)
    for i in range(1, len(BUY_SIGNAL_CURVE)):
        x0, y0 = BUY_SIGNAL_CURVE[i - 1]
        x1, y1 = BUY_SIGNAL_CURVE[i]
        if sconto_percent <= x1:
            return y0 + (y1 - y0) * (sconto_percent - x0) / (x1 - x0)
    return ultimo_y


def _eta_riga_ore(aggiornato_il_iso):
    """Da quante ore il prezzo di questa riga non viene rinfrescato. None se il
    dato manca (righe scritte prima dell'introduzione della colonna)."""
    if not aggiornato_il_iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(aggiornato_il_iso).replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600.0


def valuta_occasione(sconto_percent, trend_recente, prossima_partita_data_iso, aggiornato_il_iso):
    """Verdetto su UNA riga. Ritorna (punteggio_occasione, motivo, ore_alla_partita).

    punteggio_occasione = guadagno % atteso a 48h (0 se non c'e' occasione).
    Il livello finale (COMPRA ORA / buona / ...) NON si decide qui: dipende
    anche dal confronto con le altre carte dello stesso gruppo, quindi viene
    assegnato al momento della scrittura del CSV (vedi _assegna_segnali)."""
    eta_ore = _eta_riga_ore(aggiornato_il_iso)
    if eta_ore is None or eta_ore > SEGNALE_MAX_AGE_HOURS:
        eta_txt = 'mai aggiornata' if eta_ore is None else f'{eta_ore:.0f}h fa'
        return 0.0, f"dato vecchio ({eta_txt}), prezzo non verificato in questa run", None

    ore = hours_until(prossima_partita_data_iso)
    if ore is None:
        return 0.0, 'prossima partita sconosciuta', None
    if ore <= 0:
        return 0.0, "partita gia' iniziata o in corso", ore

    if sconto_percent is None:
        return 0.0, 'nessuno storico prezzi utilizzabile', ore
    if sconto_percent <= 0:
        return 0.0, (f"prezzo {abs(sconto_percent):.0f}% SOPRA la sua media 7gg "
                     f"(sovrapprezzo, non e' un affare)"), ore

    base = _guadagno_atteso_da_sconto(sconto_percent)
    mult_trend = TREND_SCORE_MULTIPLIER.get(trend_recente, TREND_SCORE_MULTIPLIER[None])

    if BUY_WINDOW_HOURS_MIN <= ore <= BUY_WINDOW_HOURS_MAX:
        mult_finestra = BUY_SIGNAL_WINDOW_MULT
        nota_finestra = 'DENTRO la finestra ideale ora'
    elif ore < BUY_SIGNAL_IMMINENTE_HOURS:
        mult_finestra = BUY_SIGNAL_IMMINENTE_MULT
        nota_finestra = f'partita tra {ore:.0f}h, finestra passata (prezzi in premio)'
    else:
        mult_finestra = 1.0
        nota_finestra = f'partita tra {ore / 24:.1f}gg, fuori finestra'

    grezzo = base * mult_trend * mult_finestra
    if grezzo > BUY_SIGNAL_COMPRESSIONE_SOPRA:
        grezzo = BUY_SIGNAL_COMPRESSIONE_SOPRA + (
            grezzo - BUY_SIGNAL_COMPRESSIONE_SOPRA) * BUY_SIGNAL_COMPRESSIONE_FATTORE
    punteggio = round(min(grezzo, BUY_SIGNAL_PUNTEGGIO_CAP), 1)
    trend_txt = {'up': 'trend in salita', 'flat': 'trend stabile',
                 'down': 'trend in calo'}.get(trend_recente, 'trend sconosciuto')
    motivo = f"sconto {sconto_percent:.0f}% | {trend_txt} | {nota_finestra}"
    return punteggio, motivo, ore


def _assegna_segnali(rows_gruppo):
    """Assegna segnale/punteggio_occasione/motivo_segnale a tutte le righe di un
    gruppo e le riordina: prima i livelli piu' alti, poi il punteggio, poi il
    vecchio potenziale_score come spareggio. Il CSV che ne esce si legge
    dall'alto: le prime righe sono le carte da comprare adesso."""
    for r in rows_gruppo:
        punteggio, motivo, _ore = valuta_occasione(
            r.get('sconto_percent'), r.get('trend_recente'),
            r.get('prossima_partita_data'), r.get('aggiornato_il'))
        r['punteggio_occasione'] = punteggio
        r['motivo_segnale'] = motivo
        r['finestra_acquisto_ideale'] = _finestra_acquisto_ideale(r.get('prossima_partita_data'))

    rows_gruppo.sort(
        key=lambda r: (r['punteggio_occasione'],
                       r['potenziale_score'] if r.get('potenziale_score') is not None else -999),
        reverse=True)

    promossi = 0
    for r in rows_gruppo:
        punteggio = r['punteggio_occasione']
        motivo = r['motivo_segnale']
        if motivo.startswith('dato vecchio'):
            r['segnale'] = SEGNALE_NON_VALUTABILE
        elif punteggio <= 0:
            r['segnale'] = SEGNALE_EVITA if 'sovrapprezzo' in motivo else SEGNALE_NEUTRO
        elif punteggio >= BUY_SIGNAL_SOGLIA_COMPRA and promossi < BUY_SIGNAL_MAX_PER_GRUPPO:
            r['segnale'] = SEGNALE_COMPRA
            promossi += 1
        elif punteggio >= BUY_SIGNAL_SOGLIA_BUONA:
            r['segnale'] = SEGNALE_BUONA
        else:
            r['segnale'] = SEGNALE_NEUTRO

    rows_gruppo.sort(
        key=lambda r: (SEGNALE_RANK.get(r['segnale'], 0), r['punteggio_occasione'],
                       r['potenziale_score'] if r.get('potenziale_score') is not None else -999),
        reverse=True)
    return rows_gruppo

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
#
# Ricalibrati 30/07 sul dataset pattern_raw_transactions (3658 tx, 142 carte):
# a parita' di sconto, 1gg/5% e' la combinazione con l'ordine down<flat<up piu'
# pulito e il divario piu' ampio tra i due estremi (n grandi in entrambe le
# code). Da finestra=3-4gg in su l'ordine si rompe spesso ('flat' supera 'up').
# Verificato che non rompe il caso reale Munie (crash confermato dall'utente):
# a window=1gg il trend resta 'down' negli stessi punti temporali di window=2gg.
TREND_RECENT_WINDOW_DAYS = int(os.environ.get('TREND_RECENT_WINDOW_DAYS', '1'))
TREND_FLAT_THRESHOLD_PERCENT = float(os.environ.get('TREND_FLAT_THRESHOLD_PERCENT', '5.0'))


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

    FIX 29/07 quater (estensione K-League), FIX 29/07 quinquies (estensione
    Eredivisie/Belgio): ora esistono fino a N file (uno per GRUPPO, vedi
    OUTPUT_GROUPS) invece di un unico combinato -- carica tutti quelli
    presenti. Mantiene anche il fallback sul vecchio nome combinato
    (profit_tracking_<timestamp>.csv, senza suffisso gruppo) per non perdere
    una classifica scritta prima di questo cambio."""
    paths = [p for p in (_find_latest_output_csv(_output_csv_prefix_for_group(g)) for g in OUTPUT_GROUPS) if p]
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
                        # FIX 30/07: quando questa riga e' stata davvero
                        # rinfrescata. Serve a non spacciare per "COMPRA ORA"
                        # un prezzo ereditato da una run di due giorni fa (la
                        # classifica e' persistente, vedi SEGNALE_MAX_AGE_HOURS).
                        # Righe scritte prima di questa colonna: campo vuoto,
                        # trattate come non aggiornate finche' non si rivedono.
                        'aggiornato_il': row.get('aggiornato_il') or None,
                        'ultimo_tipo_evento': row.get('ultimo_tipo_evento') or None,
                    }
                    caricate += 1
    log(f"[classifica persistente] caricate {caricate} righe da {len(paths)} CSV precedente/i come stato di partenza")


def _write_ranked_csv(rows_liquidi, path, label):
    """FIX 30/07 (richiesta esplicita utente: segnale chiaro e forte nel CSV):
    l'ordinamento non e' piu' il solo potenziale_score, ma il VERDETTO --
    prima i COMPRA ORA, poi le buone occasioni, poi il resto (vedi
    _assegna_segnali), col punteggio_occasione come criterio interno e il
    potenziale_score come spareggio. Effetto pratico: le carte da comprare
    adesso stanno nelle prime righe del file e nessuna di esse puo' finire
    tagliata fuori dal top TOP_N_OUTPUT (prima poteva succedere: il taglio era
    per potenziale_score, dove il timing pesa 0.40 e poteva sotterrare una
    carta con uno sconto enorme ma la partita lontana)."""
    rows_sorted = _assegna_segnali(list(rows_liquidi))[:TOP_N_OUTPUT]
    _write_plain_csv(rows_sorted, path)
    n_compra = sum(1 for r in rows_sorted if r.get('segnale') == SEGNALE_COMPRA)
    n_buona = sum(1 for r in rows_sorted if r.get('segnale') == SEGNALE_BUONA)
    log(f"[csv] {label}: scritte {len(rows_sorted)}/{len(rows_liquidi)} carte in {path} "
        f"-- {n_compra} da COMPRARE ORA, {n_buona} buone occasioni")
    return rows_sorted


def _write_plain_csv(rows_sorted, path):
    """Scrive rows_sorted cosi' come sono, senza ricalcolare segnale/punteggio
    (gia' assegnati da _assegna_segnali) -- usato sia per i file per gruppo sia
    per il file globale, che si limita a rimescolare righe gia' valutate."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for r in rows_sorted:
            writer.writerow(r)


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
    rows_sorted = _write_ranked_csv(rows_liquidi, path, label)
    return path, len(rows_sorted), rows_sorted


# FIX 29/07 quater (estensione K-League, richiesta esplicita utente: classifiche
# separate MLS/Korea invece di un unico CSV mescolato -- vedi TEAM_LEAGUE_MAP
# sopra). Un prefisso di file per GRUPPO di output, es. profit_tracking_mlspa_<ts>.csv
# e profit_tracking_k-league-1_<ts>.csv -- stessi vincoli (soglia prezzo,
# MIN_TRANSACTIONS_FOR_RANKING, TOP_N_OUTPUT) applicati identici a tutte le leghe.
#
# FIX 29/07 quinquies (estensione Eredivisie/Belgio, richiesta esplicita utente:
# "1 solo output mescolato" per queste due, a differenza di MLS/K-League che
# restano separate): un GRUPPO puo' contenere piu' league_slug -- le righe di
# tutte le leghe del gruppo finiscono nello STESSO file/classifica, competendo
# tra loro per il taglio TOP_N_OUTPUT (non tagliate separatamente per lega
# prima di unire).
OUTPUT_GROUPS = {
    'mlspa': ('mlspa',),
    'k-league-1': ('k-league-1',),
    'eredivisie_belgio': ('eredivisie', 'jupiler-pro-league'),
}


def _output_csv_prefix_for_group(group_name):
    return f"{OUTPUT_CSV_PREFIX}_{group_name}"


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
    """FIX 29/07 quater (estensione K-League), FIX 29/07 quinquies (estensione
    Eredivisie/Belgio, richiesta esplicita utente): classifiche separate PER
    GRUPPO (vedi OUTPUT_GROUPS) invece di un unico CSV globale -- ogni riga
    viene assegnata al gruppo la cui tupla di league_slug contiene la sua
    league_slug (profit_tracking_mlspa_<ts>.csv / profit_tracking_k-league-1_<ts>.csv
    / profit_tracking_eredivisie_belgio_<ts>.csv, quest'ultimo con le due leghe
    MESCOLATE nella stessa classifica), ciascuno top TOP_N_OUTPUT per
    potenziale_score, in_season+classic mescolati come prima (colonna
    tipo_carta). Ad ogni scrittura viene cancellato il file con timestamp
    precedente PER QUEL GRUPPO (vedi _cleanup_and_write_ranked_csv) -- ne
    resta sempre e solo uno per gruppo, il piu' recente. Righe di leghe non
    presenti in nessun gruppo di OUTPUT_GROUPS (non dovrebbe mai capitare in
    modalita' snapshot) non vengono scritte in nessun file."""
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

    # BUG REALE trovato 30/07 rileggendo i CSV committati: la classifica e'
    # PERSISTENTE (load_previous_tracked ricarica tutto quello che c'era) ma il
    # ricaricamento non riapplica MIN_PRICE_EUR_THRESHOLD -- righe scritte
    # quando la soglia era 1 EUR sono rimaste dentro anche dopo che l'utente
    # l'ha alzata prima a 2 e poi a 2.5, e nell'ultimo CSV reale ce n'erano
    # ancora a 1.24/1.40/1.52 EUR. Su una carta da 1.24 EUR anche un 17% di
    # sconto vale 21 centesimi: non e' un'occasione, ed e' esattamente cio' che
    # la soglia doveva togliere di mezzo. Il filtro va quindi applicato anche
    # in scrittura, non solo in fase di raccolta.
    rows_liquidi = [
        r for r in rows_liquidi
        if r.get('min_attuale_eur') is None or r['min_attuale_eur'] >= MIN_PRICE_EUR_THRESHOLD
    ]
    esclusi_prezzo_basso = (len(rows_con_storico) - esclusi_poco_liquidi) - len(rows_liquidi)

    timestamp = _run_timestamp_utc()

    per_lega_riepilogo = []
    rows_per_gruppo = []
    for group_name, group_leagues in OUTPUT_GROUPS.items():
        rows_gruppo = [r for r in rows_liquidi if r.get('league_slug') in group_leagues]
        path, n_scritte, rows_scritte = _cleanup_and_write_ranked_csv(
            rows_gruppo, OUTPUT_DIR, f'profit_tracking_{group_name}', timestamp, group_name)
        per_lega_riepilogo.append(f"{group_name}: {n_scritte} nel file {path}")
        rows_per_gruppo.extend(rows_scritte)

    log(f"[csv] totale tracciate: {len(rows)}, {esclusi_senza_storico} escluse per assenza di storico, "
        f"{esclusi_poco_liquidi} escluse per meno di {MIN_TRANSACTIONS_FOR_RANKING} transazioni, "
        f"{esclusi_prezzo_basso} escluse per minimo sotto {MIN_PRICE_EUR_THRESHOLD}EUR "
        f"({'; '.join(per_lega_riepilogo)})")

    _write_global_csv(rows_per_gruppo, timestamp)


# FIX 30/07 sera (richiesta esplicita utente: troppe notifiche Telegram, una
# per gruppo -- vuole un'unica classifica globale mescolata tra campionati e
# la notifica solo su quella). Non ricalcola segnale/punteggio_occasione: li
# riusa cosi' come sono gia' stati assegnati PER GRUPPO da _assegna_segnali
# (quindi il tetto BUY_SIGNAL_MAX_PER_GRUPPO resta per lega, non diventa
# globale) -- questo file e' una "selezione dentro la selezione": rimescola le
# righe gia' scelte da ciascun gruppo in un'unica classifica ordinata per
# verdetto/punteggio, non ne calcola una nuova.
#
# FIX 30/07 sera bis (richiesta esplicita utente: "non ha senso farmi arrivare
# anche il resto della classifica, i compra ora sono al massimo 15"): il file
# globale contiene SOLO le righe COMPRA ORA, non il solito top TOP_N_OUTPUT
# misto -- niente "buona occasione"/neutro/evita. Se nessun gruppo ha COMPRA
# ORA il file resta con la sola intestazione (0 righe), la notifica lo segnala.
GLOBAL_OUTPUT_PREFIX = 'profit_tracking_global'


def _write_global_csv(rows_tutti_i_gruppi, timestamp):
    rows_compra = [r for r in rows_tutti_i_gruppi if r.get('segnale') == SEGNALE_COMPRA]
    rows_sorted = sorted(
        rows_compra,
        key=lambda r: (r['punteggio_occasione'],
                       r['potenziale_score'] if r.get('potenziale_score') is not None else -999),
        reverse=True)
    for old_path in glob.glob(os.path.join(OUTPUT_DIR, f"{GLOBAL_OUTPUT_PREFIX}_*.csv")):
        os.remove(old_path)
    path = os.path.join(OUTPUT_DIR, f"{GLOBAL_OUTPUT_PREFIX}_{timestamp}.csv")
    _write_plain_csv(rows_sorted, path)
    log(f"[csv] globale: scritte {len(rows_sorted)} carte COMPRA ORA in {path}")


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
        scrivi_roster_cache()
        paths_da_committare = [OUTPUT_DIR]
        if os.path.exists(LISTA_NERA_PROFIT_PATH):
            paths_da_committare.append(LISTA_NERA_PROFIT_PATH)
        # FIX 30/07: la cache roster va committata come i CSV, altrimenti resta
        # nel runner effimero di GitHub Actions e la run successiva riparte da
        # zero -- cioe' il risparmio di query non arriverebbe mai.
        if os.path.exists(ROSTER_CACHE_PATH):
            paths_da_committare.append(ROSTER_CACHE_PATH)
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--'] + paths_da_committare,
            capture_output=True, text=True, timeout=30
        )
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip() or 'main'
        # BUG REALE 29/07 (trovato dall'utente: link Telegram a un CSV mai
        # arrivato su GitHub, 404): se il push di un giro precedente falliva
        # (es. conflitto con un'altra run in parallelo), il commit restava
        # SOLO in locale nel runner -- il giro successivo vedeva
        # `git status --porcelain` vuoto (nessuna modifica non committata) e
        # usciva subito senza mai ritentare il push di quel commit gia' fatto.
        # Lo stesso identico difetto era nello step finale del workflow YAML
        # (stesso controllo). Fix: controllare SEMPRE se HEAD e' avanti
        # rispetto a origin/<branch> (commit locali non ancora pushati), non
        # solo se ci sono modifiche non committate nel working tree -- se lo
        # e', si ritenta pull+push anche senza nuove modifiche da scrivere.
        if not status.stdout.strip():
            ahead = subprocess.run(
                ['git', 'rev-list', '--count', f'origin/{branch}..HEAD'],
                capture_output=True, text=True, timeout=15
            )
            if not (ahead.returncode == 0 and ahead.stdout.strip() not in ('', '0')):
                return
            log(f"[commit periodico] {ahead.stdout.strip()} commit locali non ancora pushati "
                f"(push precedente fallito), ritento senza nuove modifiche...")
        else:
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
        pull = subprocess.run(
            ['git', 'pull', '--rebase', '--autostash', 'origin', branch],
            capture_output=True, text=True, timeout=60
        )
        if pull.returncode != 0:
            # FIX 26/07: un rebase fallito lascia il repo a meta' rebase -- se non lo
            # annulliamo, TUTTI i prossimi giri di commit periodico falliscono allo
            # stesso modo per il resto della run. Annullato cosi' il prossimo giro
            # riparte pulito (i dati di QUESTO giro restano committati solo in
            # locale, verranno ripushati al prossimo giro se il conflitto rientra,
            # vedi il controllo "ahead" sopra).
            subprocess.run(['git', 'rebase', '--abort'], capture_output=True, text=True, timeout=30)
            log(f"[commit periodico] git pull --rebase fallito su branch={branch}, annullato il rebase, "
                f"salto il push di questo giro: {pull.stderr.strip()}")
            return
        push = subprocess.run(['git', 'push'], capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            log("[commit periodico] dati tracciati committati e pushati con successo (run ancora in corso)")
        else:
            log(f"[commit periodico] push fallito, ritento al prossimo giro: {push.stderr.strip()}")
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
            'aggiornato_il': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
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
        f"({len(MLS_TEAM_WHITELIST)} MLS + {len(KLEAGUE_TEAM_WHITELIST)} K-League + "
        f"{len(EREDIVISIE_TEAM_WHITELIST)} Eredivisie + {len(BELGIO_TEAM_WHITELIST)} Belgio): {TEAM_WHITELIST}")

    roster = {}  # slug -> (displayName, team_slug attesa, snapshot voto/partita, league_slug), deduplicato tra squadre
    for team_slug in TEAM_WHITELIST:
        league_slug = TEAM_LEAGUE_MAP[team_slug]
        for player_slug, player_name, snapshot in fetch_team_roster(team_slug):
            roster.setdefault(player_slug, (player_name, team_slug, snapshot, league_slug))

    log(f"Roster totale (deduplicato): {len(roster)} giocatori "
        f"({_roster_cache_stats['da_cache']} squadre servite dalla cache, "
        f"{_roster_cache_stats['scaricati']} riscaricate da Sorare).")
    scrivi_roster_cache()

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
            # FIX 29/07 (richiesta esplicita utente): blacklist a TTL ampio
            # (default 2 giorni, vedi PREZZO_BASSO_SKIP_DAYS) invece di
            # riprovare ogni run -- il prezzo su questa scala di tempo resta
            # quasi sempre invariato (verificato su run reali ravvicinate),
            # e il bot serve solo 1-2 snapshot al giorno.
            blacklist_player(player_slug, 'prezzo_basso_o_senza_annunci', PREZZO_BASSO_SKIP_DAYS)
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
    log(f"[rate limit] {_pace_riepilogo()}")
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
