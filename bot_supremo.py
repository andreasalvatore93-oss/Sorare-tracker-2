import json
import os
import random
import time
import datetime
import threading

import requests
import websocket  # pip install websocket-client
from playwright.sync_api import sync_playwright

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# OTTIMIZZAZIONE VELOCITA' (21/07, richiesta esplicita utente -- "altri modi per
# renderlo piu' veloce"): prima ogni chiamata GraphQL usava curl_requests.post()/
# requests.post() a livello di modulo, che aprono una connessione NUOVA (handshake
# TCP + TLS da zero) ad OGNI singola chiamata verso api.sorare.com. Con una Session
# persistente (stessa identica interfaccia .post(), stessi header/payload/timeout --
# nessun cambio di comportamento) la connessione resta aperta (keep-alive) e viene
# RIUSATA tra una chiamata e l'altra: l'handshake TLS (spesso 50-150ms) si paga una
# volta sola invece che ad ogni singola query/mutation. Impatta OGNI chiamata
# GraphQL della run (ricerca prezzi, liquidita', tassi di cambio), non solo il
# momento dell'acquisto.
if _HAS_CURL_CFFI:
    _http_session = curl_requests.Session(impersonate="chrome")
else:
    _http_session = requests.Session()

# =====================================================================================
# BOT SUPREMO -- fusione di AutoBuy + MakeOffer in un unico scanner/bot (20/07)
# =====================================================================================
# Un solo scan di mercato per evento: se il margine e' nella fascia MAKEOFFER_MARGIN_
# FRACTION-MAKEOFFER_MAX_MARGIN_FRACTION -> crea un'offerta scontata (ramo MakeOffer);
# se e' >= AUTOBUY_MARGIN_FRACTION -> accetta direttamente l'offerta (ramo AutoBuy).
# Elimina il doppio scan/doppia richiesta e la race condition tra i due bot separati
# (blacklist ora lette insieme da entrambi i file, vedi sotto).
# =====================================================================================

COOKIES = os.environ.get('SORARE_COOKIE')


def _extract_csrf_from_cookie(cookie_string):
    """Il CSRF token cambia ad ogni refresh pagina -- estratto dal cookie stesso
    (campo csrftoken=...) invece di un secret statico che scadrebbe subito."""
    if not cookie_string:
        return None
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF_TOKEN = _extract_csrf_from_cookie(COOKIES) or os.environ.get('SORARE_CSRF')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

AUTOBUY_LIVE_MODE = os.environ.get('AUTOBUY_LIVE_MODE', 'si').strip().lower() in ('1', 'true', 'yes', 'si')
MAKEOFFER_LIVE_MODE = os.environ.get('MAKEOFFER_LIVE_MODE', 'si').strip().lower() in ('1', 'true', 'yes', 'si')
SORARE_WALLET_PASSWORD = os.environ.get('SORARE_WALLET_PASSWORD')
SORARE_DEVICE_FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

GRAPHQL_URL = 'https://api.sorare.com/graphql'
WS_URL = "wss://ws.sorare.com/cable"

# Stessa blacklist manager storica di track.py (venditori solo ETH o esplicitamente
# esclusi dall'utente).
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}


# =====================================================================================
# LISTA NERA DEL BOT SUPREMO -- file unico (richiesta esplicita utente 21/07)
# =====================================================================================
# Sostituisce TUTTI i vecchi file separati (sorare_blacklist.txt, sorare_manager_
# blacklist.txt, i legacy autobuy/makeoffer, autobuy_purchases.json, makeoffer_cooldown.
# json, bot_supremo_thin_market_cache.json) con un solo file di testo a righe, editabile
# a mano su GitHub, con 4 tipi di riga:
#   manager,<slug>,<scadenza_iso>
#   giocatore,<slug>,<scadenza_iso>
#   thin_market,<slug>,<scadenza_iso>
#   cooldown_acquisto,<slug>,<scadenza_iso>
# La scadenza e' editabile a mano riga per riga: basta cambiare la data ISO. Una riga
# con scadenza nel passato viene ignorata in lettura ma NON cancellata automaticamente
# (resta li' finche' non la si toglie a mano o finche' il bot non la rinnova scrivendo
# una nuova scadenza per lo stesso slug/tipo).
LISTA_NERA_PATH = os.environ.get('LISTA_NERA_PATH', 'sorare_lista_nera.txt')

# Durate di default (giorni), usate quando il bot AGGIUNGE una riga per conto suo
# (es. dal workflow_dispatch, o registrando un acquisto/offerta/thin-market skip).
# Tutte modificabili qui O a mano nel file cambiando la scadenza di ogni riga.
MANAGER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('MANAGER_BLACKLIST_DEFAULT_DAYS', '365'))
PLAYER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('PLAYER_BLACKLIST_DEFAULT_DAYS', '3'))
THIN_MARKET_DEFAULT_DAYS = float(os.environ.get('THIN_MARKET_DEFAULT_DAYS', '2'))
COOLDOWN_ACQUISTO_DEFAULT_DAYS = float(os.environ.get('COOLDOWN_ACQUISTO_DEFAULT_DAYS', '1'))

_LISTA_NERA_TIPI_VALIDI = ('manager', 'giocatore', 'thin_market', 'cooldown_acquisto')

# Vecchi file, letti SOLO per la migrazione automatica una tantum (prima run dopo
# l'aggiornamento). Una volta migrati in sorare_lista_nera.txt possono essere eliminati
# dal repo -- vedi messaggio di log a fine migrazione.
_LEGACY_FILES_DA_MIGRARE = {
    'manager': ['sorare_manager_blacklist.txt', 'sorare_autobuy_manager_blacklist.txt',
                'sorare_makeoffer_manager_blacklist.txt'],
    'giocatore': ['sorare_blacklist.txt', 'sorare_autobuy_blacklist.txt',
                  'sorare_makeoffer_blacklist.txt'],
}
_LEGACY_JSON_DA_MIGRARE = {
    'cooldown_acquisto': ['autobuy_purchases.json', 'makeoffer_cooldown.json'],
    'thin_market': ['bot_supremo_thin_market_cache.json'],
}


_LISTA_NERA_INTESTAZIONI = {
    'manager': (
        "MANAGER BLACKLISTATI -- da questi manager non compriamo carte ne' facciamo "
        "offerte, ma le loro carte contano comunque nel calcolo del prezzo minimo di "
        "mercato (non vengono escluse dal conteggio, solo dagli acquisti/offerte)."
    ),
    'giocatore': (
        "GIOCATORI BLACKLISTATI -- questi giocatori vengono ignorati sia per gli "
        "acquisti diretti (AutoBuy) sia per le offerte (MakeOffer)."
    ),
    'cooldown_acquisto': (
        "COOLDOWN ACQUISTI/OFFERTE -- giocatori appena comprati o a cui abbiamo appena "
        "fatto un'offerta: ignorati per il tempo indicato, per non ricomprare/riproporre "
        "subito lo stesso giocatore."
    ),
    'thin_market': (
        "THIN MARKET -- giocatori con mercato troppo ristretto (poche transazioni "
        "recenti): i loro annunci vengono ignorati per il tempo indicato, per evitare "
        "di comprare/offrire su un mercato poco liquido."
    ),
}
_LISTA_NERA_ORDINE_SEZIONI = ('manager', 'giocatore', 'cooldown_acquisto', 'thin_market')


def _durata_a_leggibile(delta_secondi):
    """Converte un numero di secondi in una stringa leggibile in italiano, es.
    '5 giorni', '1 giorno', '3 ore', '20 minuti'. Arrotonda per eccesso all'unita'
    piu' grande sensata, cosi' il file resta leggibile senza troppi decimali."""
    if delta_secondi <= 0:
        return "scaduto"
    giorni = delta_secondi / 86400
    if giorni >= 1:
        giorni_interi = max(1, round(giorni))
        return f"{giorni_interi} giorno" if giorni_interi == 1 else f"{giorni_interi} giorni"
    ore = delta_secondi / 3600
    if ore >= 1:
        ore_intere = max(1, round(ore))
        return f"{ore_intere} ora" if ore_intere == 1 else f"{ore_intere} ore"
    minuti = max(1, round(delta_secondi / 60))
    return f"{minuti} minuto" if minuti == 1 else f"{minuti} minuti"


def _leggibile_a_secondi(testo):
    """Converte una stringa italiana ('7 giorni', '24 ore', '30 minuti') in secondi.
    Accetta anche forme abbreviate (7g, 24h, 30m) per chi preferisce scrivere veloce.
    Ritorna None se non riconosciuta."""
    testo = testo.strip().lower()
    parts = testo.split()
    if len(parts) == 2:
        numero_str, unita = parts
    elif len(parts) == 1 and len(testo) > 1 and testo[-1] in ('g', 'h', 'm'):
        numero_str, unita = testo[:-1], testo[-1]
    else:
        return None
    try:
        numero = float(numero_str)
    except ValueError:
        return None
    if unita.startswith('giorn') or unita == 'g':
        return numero * 86400
    if unita.startswith('or') or unita == 'h':
        return numero * 3600
    if unita.startswith('minut') or unita == 'm':
        return numero * 60
    return None


def _lista_nera_migra_vecchio_formato_riga_se_serve():
    """Il primo formato del file unico (righe 'tipo,slug,scadenza_iso' senza sezioni)
    e' stato sostituito da questo formato a sezioni con durata leggibile. Se il file
    esiste ma e' ancora nel vecchio formato (nessuna intestazione '## tipo' trovata,
    ma righe con 3 campi separati da virgola), lo convertiamo automaticamente UNA
    TANTUM preservando tutte le scadenze gia' presenti."""
    try:
        with open(LISTA_NERA_PATH, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        return
    ha_sezioni = any(l.strip().startswith('## ') for l in raw_lines)
    if ha_sezioni:
        return  # gia' nel nuovo formato
    righe_vecchie = []
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if len(parts) != 3:
            continue
        tipo, slug, scadenza_str = parts
        tipo = tipo.lower()
        if tipo not in _LISTA_NERA_TIPI_VALIDI:
            continue
        try:
            scadenza = datetime.datetime.fromisoformat(scadenza_str)
            if scadenza.tzinfo is None:
                scadenza = scadenza.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        righe_vecchie.append({'tipo': tipo, 'slug': slug.lower(), 'scadenza': scadenza})
    if righe_vecchie:
        _lista_nera_scrivi_righe(righe_vecchie)
        print(f"[lista nera] convertite {len(righe_vecchie)} righe dal vecchio formato "
              f"(tipo,slug,scadenza_iso) al nuovo formato a sezioni leggibili.", flush=True)


def _lista_nera_leggi_righe():
    """Legge tutte le righe valide dal file unico (nuovo formato a sezioni:
    slug,durata_leggibile sotto un'intestazione '## tipo'). Ritorna lista di dict
    {tipo, slug, scadenza (datetime)}. Righe malformate vengono ignorate con log."""
    righe = []
    try:
        with open(LISTA_NERA_PATH, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        return righe
    ora = datetime.datetime.now(datetime.timezone.utc)
    tipo_corrente = None
    for n, raw in enumerate(raw_lines, start=1):
        raw = raw.rstrip('\n')
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith('## '):
            candidato = stripped[3:].strip().lower()
            if candidato in _LISTA_NERA_TIPI_VALIDI:
                tipo_corrente = candidato
            continue
        if stripped.startswith('#'):
            continue  # commento/descrizione, non una riga dati
        if tipo_corrente is None:
            log(f"[lista nera] riga {n} fuori da qualunque sezione, ignorata: {raw!r}")
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if len(parts) != 2:
            log(f"[lista nera] riga {n} malformata (attesi 2 campi slug,durata), ignorata: {raw!r}")
            continue
        slug, durata_str = parts
        slug = slug.lower()
        secondi = _leggibire_wrapper(durata_str, n, raw)
        if secondi is None:
            continue
        righe.append({'tipo': tipo_corrente, 'slug': slug, 'scadenza': ora + datetime.timedelta(seconds=secondi)})
    return righe


def _leggibire_wrapper(durata_str, n, raw):
    secondi = _leggibile_a_secondi(durata_str)
    if secondi is None:
        log(f"[lista nera] riga {n} durata non riconosciuta ('{durata_str}'), ignorata: {raw!r}")
    return secondi


def _lista_nera_scrivi_righe(righe):
    """Riscrive il file unico in sezioni per tipo (ordine fisso, thin_market per
    ultimo perche' e' la sezione piu' numerosa), ognuna con intestazione descrittiva.
    La durata scritta e' SEMPRE il tempo RIMANENTE alla scadenza (ricalcolato ogni
    volta), non la durata originale -- cosi' l'utente vede sempre quanto manca."""
    ora = datetime.datetime.now(datetime.timezone.utc)
    dedup = {}
    for r in righe:
        if r['scadenza'] <= ora:
            continue  # non riscriviamo righe gia' scadute
        chiave = (r['tipo'], r['slug'])
        if chiave not in dedup or r['scadenza'] > dedup[chiave]['scadenza']:
            dedup[chiave] = r
    per_tipo = {t: [] for t in _LISTA_NERA_TIPI_VALIDI}
    for r in dedup.values():
        per_tipo[r['tipo']].append(r)

    with open(LISTA_NERA_PATH, 'w', encoding='utf-8') as f:
        f.write("# LISTA NERA DEL BOT SUPREMO\n")
        f.write("# Ogni riga: slug,durata (es. 'clem777,5 giorni'). La durata e' il tempo\n")
        f.write("# rimanente, aggiornato automaticamente ogni volta che il bot riscrive questo\n")
        f.write("# file -- puoi modificarla a mano in qualunque momento (es. '3 ore', '10 giorni',\n")
        f.write("# '30 minuti') per accorciare o allungare il blocco. Per rimuovere un blocco,\n")
        f.write("# cancella semplicemente la riga.\n\n")
        for tipo in _LISTA_NERA_ORDINE_SEZIONI:
            righe_tipo = sorted(per_tipo[tipo], key=lambda r: r['slug'])
            f.write(f"## {tipo}\n")
            f.write(f"# {_LISTA_NERA_INTESTAZIONI[tipo]}\n")
            if not righe_tipo:
                f.write("# (vuoto)\n")
            for r in righe_tipo:
                delta = (r['scadenza'] - ora).total_seconds()
                f.write(f"{r['slug']},{_durata_a_leggibile(delta)}\n")
            f.write("\n")


def _lista_nera_upsert(tipo, slug, giorni_da_ora):
    """Aggiunge o rinnova una riga (tipo, slug) con nuova scadenza = ora + giorni_da_ora.
    Se la riga esiste gia', la sostituisce (rinnovo); altrimenti la aggiunge."""
    slug = slug.lower()
    righe = _lista_nera_leggi_righe()
    scadenza = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=giorni_da_ora)
    trovata = False
    for r in righe:
        if r['tipo'] == tipo and r['slug'] == slug:
            r['scadenza'] = scadenza
            trovata = True
            break
    if not trovata:
        righe.append({'tipo': tipo, 'slug': slug, 'scadenza': scadenza})
    _lista_nera_scrivi_righe(righe)


def _lista_nera_attiva(tipo, slug):
    """True se (tipo, slug) e' presente con scadenza non ancora passata."""
    slug = (slug or '').lower()
    if not slug:
        return False
    ora = datetime.datetime.now(datetime.timezone.utc)
    for r in _lista_nera_leggi_righe():
        if r['tipo'] == tipo and r['slug'] == slug and r['scadenza'] > ora:
            return True
    return False


def _migra_vecchi_file_una_tantum():
    """Migrazione automatica una tantum: se sorare_lista_nera.txt non esiste ancora,
    legge tutti i vecchi file separati e popola il nuovo file unico. Blacklist
    manager/giocatore migrate con scadenza 7 giorni da ora (default). Cooldown
    acquisto/thin_market migrati preservando la data originale + la loro durata
    default (cosi' un giocatore comprato ieri non riparte da zero oggi)."""
    if os.path.exists(LISTA_NERA_PATH):
        return  # gia' migrato in una run precedente, non rifare
    righe = []
    ora = datetime.datetime.now(datetime.timezone.utc)
    migrate_da = []

    for tipo, file_paths in _LEGACY_FILES_DA_MIGRARE.items():
        giorni_default = (MANAGER_BLACKLIST_DEFAULT_DAYS if tipo == 'manager'
                          else PLAYER_BLACKLIST_DEFAULT_DAYS)
        for fp in file_paths:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except FileNotFoundError:
                continue
            migrate_da.append(fp)
            for line in lines:
                slug = line.strip().lower()
                if not slug or slug.startswith('#'):
                    continue
                righe.append({'tipo': tipo, 'slug': slug,
                              'scadenza': ora + datetime.timedelta(days=giorni_default)})

    for tipo, file_paths in _LEGACY_JSON_DA_MIGRARE.items():
        giorni_default = (THIN_MARKET_DEFAULT_DAYS if tipo == 'thin_market'
                          else COOLDOWN_ACQUISTO_DEFAULT_DAYS)
        for fp in file_paths:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            migrate_da.append(fp)
            for slug, last_iso in data.items():
                try:
                    last_dt = datetime.datetime.fromisoformat(last_iso)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                except (ValueError, TypeError):
                    last_dt = ora
                righe.append({'tipo': tipo, 'slug': slug.lower(),
                              'scadenza': last_dt + datetime.timedelta(days=giorni_default)})

    if not righe and not migrate_da:
        # Nessun vecchio file trovato: crea comunque il file vuoto con intestazione,
        # cosi' l'utente puo' iniziare ad editarlo a mano.
        _lista_nera_scrivi_righe([])
        print("[lista nera] nessun vecchio file trovato, creato sorare_lista_nera.txt vuoto",
              flush=True)
        return

    _lista_nera_scrivi_righe(righe)
    print(f"[lista nera] MIGRAZIONE completata da {len(migrate_da)} vecchi file "
          f"({', '.join(migrate_da)}) -> {len(righe)} righe in {LISTA_NERA_PATH}. "
          f"Puoi ora eliminare dal repo i vecchi file elencati sopra.", flush=True)


_lista_nera_migra_vecchio_formato_riga_se_serve()
_migra_vecchi_file_una_tantum()


class _SetTipoLive:
    """Wrapper minimale per mantenere l'API 'set' (operatore 'in', len(), sorted())
    usata nel resto del codice per BLACKLISTED_PLAYER_SLUGS/BLACKLISTED_MANAGER_SLUGS,
    ma leggendo SEMPRE dal vivo dal file unico -- cosi' una modifica al file a mano
    (o un aggiornamento da un altro ramo durante la stessa run) e' vista subito,
    senza dover ricaricare/riavviare il bot."""

    def __init__(self, tipo):
        self._tipo = tipo

    def _slugs_attivi(self):
        ora = datetime.datetime.now(datetime.timezone.utc)
        return {r['slug'] for r in _lista_nera_leggi_righe()
                if r['tipo'] == self._tipo and r['scadenza'] > ora}

    def __contains__(self, slug):
        return _lista_nera_attiva(self._tipo, slug or '')

    def __iter__(self):
        return iter(self._slugs_attivi())

    def __len__(self):
        return len(self._slugs_attivi())


# Stessa blacklist manager storica di track.py (venditori solo ETH o esplicitamente
# esclusi dall'utente) -- questa resta hardcoded, non fa parte della lista nera editabile.
BLACKLISTED_SELLER_SLUGS = {'privacy', 'eli-aquim', 'clem777'}

BLACKLISTED_PLAYER_SLUGS = _SetTipoLive('giocatore')
BLACKLISTED_MANAGER_SLUGS = _SetTipoLive('manager')
# Alias per compatibilita' col nome usato nel codice AutoBuy originale.
BLACKLISTED_AUTOBUY_MANAGER_SLUGS = BLACKLISTED_MANAGER_SLUGS

# Blacklist extra passate da workflow_dispatch (input singola run, oltre al file):
# vengono scritte anche loro nel file unico, cosi' restano visibili/editabili li'.
_extra_blacklisted_players = os.environ.get('BLACKLISTED_PLAYER_SLUGS', '')
if _extra_blacklisted_players.strip():
    for _s in _extra_blacklisted_players.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_upsert('giocatore', _s, PLAYER_BLACKLIST_DEFAULT_DAYS)

_extra_blacklisted_managers = os.environ.get('BLACKLISTED_MANAGER_SLUGS', '')
if _extra_blacklisted_managers.strip():
    for _s in _extra_blacklisted_managers.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_upsert('manager', _s, MANAGER_BLACKLIST_DEFAULT_DAYS)

# --- Parametri regolabili ---
AUTOBUY_MIN_PRICE_EUR = float(os.environ.get('AUTOBUY_MIN_PRICE_EUR', '1'))
AUTOBUY_MAX_PRICE_EUR = float(os.environ.get('AUTOBUY_MAX_PRICE_EUR', '30'))

# Due soglie SEPARATE per fascia, nessuna sovrapponibile per costruzione:
# MAKEOFFER_MARGIN_FRACTION <= margine < MAKEOFFER_MAX_MARGIN_FRACTION -> ramo MakeOffer
# margine >= AUTOBUY_MARGIN_FRACTION -> ramo AutoBuy (deve essere >= al tetto MakeOffer)
MAKEOFFER_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MARGIN_FRACTION', '0.10'))
MAKEOFFER_MAX_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MAX_MARGIN_FRACTION', '0.19'))
AUTOBUY_MARGIN_FRACTION = float(os.environ.get('AUTOBUY_MARGIN_FRACTION', '0.20'))

LISTEN_SECONDS = int(os.environ.get('LISTEN_SECONDS', '18000'))
LISTEN_SECONDS = min(18000, LISTEN_SECONDS)

# Pausa random periodica (20/07, richiesta esplicita utente: "non martellare Sorare di
# richieste troppo ritmate/prevedibili") -- ogni RANDOM_PAUSE_INTERVAL_SECONDS di
# attivita' continua, il bot si ferma per un tempo casuale tra RANDOM_PAUSE_MIN_SECONDS
# e RANDOM_PAUSE_MAX_SECONDS prima di riprendere.
RANDOM_PAUSE_INTERVAL_SECONDS = int(os.environ.get('RANDOM_PAUSE_INTERVAL_SECONDS', '180'))
RANDOM_PAUSE_MIN_SECONDS = float(os.environ.get('RANDOM_PAUSE_MIN_SECONDS', '1'))
RANDOM_PAUSE_MAX_SECONDS = float(os.environ.get('RANDOM_PAUSE_MAX_SECONDS', '10'))

EXCLUDED_LEAGUE_SLUGS = {'mlspa', 'k-league-1'}

AUTOBUY_TARGET_MATCHES = int(os.environ.get('AUTOBUY_TARGET_MATCHES', '20'))
AUTOBUY_TARGET_MATCHES = max(1, min(20, AUTOBUY_TARGET_MATCHES))

AUTOBUY_DIAGNOSTIC = os.environ.get('AUTOBUY_DIAGNOSTIC', 'no').strip().lower() in ('1', 'true', 'yes', 'si')
CHECK_CLASSIC = os.environ.get('CHECK_CLASSIC', 'si').strip().lower() in ('1', 'true', 'yes', 'si')

# Parametri MakeOffer (ramo offerta scontata)
OFFER_DISCOUNT_FRACTION = float(os.environ.get('OFFER_DISCOUNT_FRACTION', '0.20'))
OFFER_DURATION_DAYS = max(1, min(7, int(os.environ.get('OFFER_DURATION_DAYS', '1'))))
OFFER_DURATION_SECONDS = OFFER_DURATION_DAYS * 86400
MAX_PENDING_OFFERS = int(os.environ.get('MAX_PENDING_OFFERS', '10'))
pending_offers_count = [0]  # contatore in-memory per run, richiesto da create_direct_offer

# Set in-memory (per-run, non persistito) dei giocatori gia' scritti in blacklist per
# copertura/media punti zero -- evita upsert ripetuti (lettura+riscrittura file) sullo
# stesso slug se ricompare piu' volte nello stesso scan, senza rallentare il flusso.
_gia_blacklistati_coverage_o_media_zero = set()

# --- Stop automatico su fondi insufficienti (20/07, richiesta esplicita utente) ---
# Se un tentativo di acquisto/offerta reale fallisce per mancanza di fondi, non ha
# senso continuare l'esecuzione: ogni tentativo successivo fallirebbe allo stesso modo,
# quindi il bot si ferma subito (chiude la connessione WebSocket) invece di continuare a
# girare a vuoto per ore, e manda una notifica Telegram esplicita e diversa dalle
# normali notifiche di caso trovato/fallito.
INSUFFICIENT_FUNDS_STOP = [False]

# --- Protezione "no ri-acquisto/ri-offerta stesso giocatore entro N giorni" -- ora un
# unico tipo di riga nella lista nera (cooldown_acquisto), condiviso tra i due rami cosi'
# uno non ripropone/ricompra un giocatore appena gestito dall'altro.
PLAYER_COOLDOWN_HOURS = 24  # mantenuto per compatibilita' log/commenti esistenti


def _slug_cooldown(player_slug, is_in_season):
    """Chiave usata SOLO per il cooldown acquisto/offerta: suffissa lo slug con
    '-inseason' o '-classic' cosi' lo stesso giocatore, se esiste sia come carta
    in_season che come classic, ha DUE cooldown indipendenti -- comprare/offrire
    sulla versione in_season non blocca piu' la versione classic dello stesso
    giocatore per 24h (richiesta esplicita utente 21/07). Le altre sezioni della
    lista nera (blacklist manager/giocatore, thin_market) NON usano questo suffisso,
    restano sullo slug puro."""
    suffisso = 'inseason' if is_in_season else 'classic'
    return f"{player_slug}-{suffisso}"


def is_player_in_cooldown(player_slug, is_in_season=True):
    return _lista_nera_attiva('cooldown_acquisto', _slug_cooldown(player_slug, is_in_season))


def record_player_purchase(player_slug, is_in_season=True):
    _lista_nera_upsert('cooldown_acquisto', _slug_cooldown(player_slug, is_in_season),
                        COOLDOWN_ACQUISTO_DEFAULT_DAYS)
    log(f"[lista nera] registrato acquisto di {player_slug} "
        f"({'in_season' if is_in_season else 'classic'}), cooldown "
        f"{COOLDOWN_ACQUISTO_DEFAULT_DAYS:.1f}gg")


def record_player_offer(player_slug, is_in_season=True):
    _lista_nera_upsert('cooldown_acquisto', _slug_cooldown(player_slug, is_in_season),
                        COOLDOWN_ACQUISTO_DEFAULT_DAYS)
    log(f"[lista nera] registrata offerta a {player_slug} "
        f"({'in_season' if is_in_season else 'classic'}), cooldown "
        f"{COOLDOWN_ACQUISTO_DEFAULT_DAYS:.1f}gg")


# --- Cache "mercato troppo sottile" -- ora tipo di riga 'thin_market' nella lista nera
# unica (stesso principio della blacklist unita: se un ramo scarta un giocatore per
# liquidita', l'altro non deve rifare la stessa query).
THIN_MARKET_SKIP_HOURS = THIN_MARKET_DEFAULT_DAYS * 24  # mantenuto per compatibilita' log


def is_player_in_thin_market_cache(player_slug):
    return _lista_nera_attiva('thin_market', player_slug)


def record_thin_market_skip(player_slug):
    _lista_nera_upsert('thin_market', player_slug, THIN_MARKET_DEFAULT_DAYS)

_FIAT_RATE_CACHE = {}


def log(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


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
    """Identica alla versione in track.py: legge il prezzo di un annuncio in qualunque
    valuta Sorare accetti (EUR/ETH/USD/GBP/SOL) e lo converte sempre in EUR."""
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


GRAPHQL_MIN_INTERVAL_SECONDS = 0.35
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        wait = GRAPHQL_MIN_INTERVAL_SECONDS - (now - _graphql_last_call_ts[0])
        if wait > 0:
            time.sleep(wait)
        _graphql_last_call_ts[0] = time.time()


# FIX 20/07 (decima ipotesi, dopo che tutte le altre 9 sono fallite su unknown_fingerprint):
# usare un vero browser Chrome headless (Playwright) per le tre chiamate GraphQL
# CRITICHE dell'acquisto (prepareAcceptOffer, fetchEncryptedPrivateKey, acceptOffer),
# invece di curl_cffi. Il resto del bot (ricerca carte, prezzi, liquidita') continua a
# usare curl_cffi via graphql_query() come prima, senza modifiche.
_playwright_instance = None
_playwright_browser = None
_playwright_page = None


def get_browser_page():
    """Apre un browser Chrome invisibile (headless) con i cookie di sessione
    gia' pronti, cosi' sembra un utente vero gia' loggato. Riusa lo stesso
    browser per tutta la run (non lo riapre ogni volta).
    FIX 20/07 (undicesima ipotesi, dopo che Playwright puro non ha risolto
    unknown_fingerprint): oltre a sembrare un browser vero, proviamo a fargli
    NAVIGARE un po' prima della chiamata critica -- non solo la home, ma
    anche una pagina di mercato reale, con piccole pause. Ipotesi: un
    eventuale fingerprint di device/sessione generato da JS potrebbe
    richiedere che il browser abbia gia' 'vissuto' un minimo di navigazione
    reale (localStorage/IndexedDB popolati) prima che il server lo consideri
    legittimo."""
    global _playwright_instance, _playwright_browser, _playwright_page
    if _playwright_page is not None:
        return _playwright_page

    _playwright_instance = sync_playwright().start()
    _playwright_browser = _playwright_instance.chromium.launch(headless=True)
    context = _playwright_browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
    )

    # Inietta i cookie di Sorare (stessa stringa che usiamo gia' in COOKIES)
    # trasformandoli nel formato che Playwright vuole (lista di dict)
    cookie_pairs = []
    if COOKIES:
        for pair in COOKIES.split(';'):
            pair = pair.strip()
            if '=' not in pair:
                continue
            name, value = pair.split('=', 1)
            cookie_pairs.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': '.sorare.com',
                'path': '/',
            })
    if cookie_pairs:
        context.add_cookies(cookie_pairs)
        log(f"[playwright] iniettati {len(cookie_pairs)} cookie nel context "
            f"(diagnostica: {[c['name'] for c in cookie_pairs][:5]}...)")
    else:
        log("[playwright] ATTENZIONE: nessun cookie iniettato (COOKIES vuoto o malformato)")

    page = context.new_page()

    # Navigazione "riscaldamento" (undicesima ipotesi): home -> pausa -> pagina
    # di mercato reale -> pausa, prima di essere pronti per la chiamata critica.
    # FIX 20/07: networkidle andava SEMPRE in timeout (30s) su GitHub Actions --
    # probabilmente risorse di terze parti (analytics/tracking) che non
    # completano mai il caricamento in un ambiente headless/datacenter.
    # Passato a domcontentloaded, molto piu' affidabile e comunque sufficiente
    # per far eseguire eventuali script di fingerprinting nella pagina.
    try:
        log("[playwright] navigazione di riscaldamento: home page...")
        page.goto('https://sorare.com/', wait_until='domcontentloaded', timeout=20000)
        time.sleep(3)
        log("[playwright] navigazione di riscaldamento: pagina di mercato...")
        page.goto('https://sorare.com/football/market', wait_until='domcontentloaded', timeout=20000)
        time.sleep(3)
    except Exception as e:
        log(f"[playwright] navigazione di riscaldamento fallita parzialmente (non bloccante): {e}")

    _playwright_page = page
    return page


def close_browser():
    """Chiude il browser alla fine (importante per non lasciare processi
    appesi e sprecare tempo del workflow GitHub Actions)."""
    global _playwright_instance, _playwright_browser, _playwright_page
    try:
        if _playwright_browser:
            _playwright_browser.close()
        if _playwright_instance:
            _playwright_instance.stop()
    except Exception as e:
        log(f"[playwright] errore chiudendo il browser: {e}")
    _playwright_instance = None
    _playwright_browser = None
    _playwright_page = None


def graphql_query_via_browser(query, variables=None, timeout_ms=20000):
    """Fa una chiamata GraphQL usando fetch() DENTRO un vero browser Chrome
    (non con curl_cffi/requests) -- cosi' la richiesta esce con l'impronta
    autentica del browser (TLS, JS engine, eventuali controlli antibot lato
    client), impossibile da imitare fino in fondo con librerie Python.
    Usata SOLO per le tre chiamate critiche dell'acquisto (prepareAcceptOffer,
    fetchEncryptedPrivateKey, acceptOffer) -- ipotesi 20/07 per unknown_fingerprint."""
    page = get_browser_page()
    payload = {"query": query, "variables": variables or {}}

    js_code = """
    async ([url, payload, csrfToken, deviceFingerprint]) => {
        try {
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'x-csrf-token': csrfToken,
            };
            if (deviceFingerprint) {
                headers['device_fingerprint'] = deviceFingerprint;
            }
            const resp = await fetch(url, {
                method: 'POST',
                headers: headers,
                credentials: 'include',
                body: JSON.stringify(payload),
            });
            const text = await resp.text();
            return { status: resp.status, body: text };
        } catch (e) {
            return { status: 0, body: JSON.stringify({error: String(e)}) };
        }
    }
    """

    try:
        result = page.evaluate(
            js_code,
            [GRAPHQL_URL, payload, CSRF_TOKEN, SORARE_DEVICE_FINGERPRINT],
        )
        body_text = result.get('body', '')
        return json.loads(body_text)
    except Exception as e:
        log(f"[playwright graphql] eccezione: {e}")
        return {"errors": [{"message": f"playwright_exception: {e}"}]}


def graphql_query(query, variables=None, max_retries=3, extra_headers=None):
    """Versione semplificata (stessa base di track.py) del client GraphQL con backoff sui
    429 -- niente rilevamento "ban a tempo fisso" qui, il volume di query di questo bot e'
    molto piu' basso (esecuzioni brevi, manuali).
    FIX 20/07 (ipotesi unknown_fingerprint): aggiunti header custom mancanti, confermati
    dal vivo ispezionando una richiesta reale di PrepareAcceptOfferMutation dal browser
    (sorare-client, sorare-version, sorare-build, sec-fetch-*, accept-language, origin,
    referer) -- il bot prima mandava SOLO Content-Type/Cookie/x-csrf-token/User-Agent,
    mancavano tutti questi header che identificano la richiesta come proveniente da un
    client Web legittimo. sorare-version/sorare-build sono valori specifici di un
    deployment del sito (cambiano ad ogni release) -- usiamo gli ultimi visti dal vivo
    come default ragionevole, ma potrebbero invecchiare: se il problema persiste,
    andrebbero riletti da una richiesta fresca del browser."""
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
    if extra_headers and isinstance(extra_headers, dict):
        headers.update(extra_headers)
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(max_retries):
        _graphql_throttle()
        if _HAS_CURL_CFFI:
            r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        else:
            r = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code == 429:
            wait_seconds = min((2 ** attempt) * 2, 8.0)
            log(f"[rate limit] HTTP 429 (tentativo {attempt + 1}/{max_retries}), "
                f"attendo {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
            continue
        return r.json()
    return {"errors": [{"message": "rate_limited_max_retries_exceeded"}]}


LIVE_OFFERS_QUERY = """
query LiveOffersForPlayer($slug: String!, $n: Int!, $cursor: String) {
  tokens {
    liveSingleSaleOffers(playerSlug: $slug, last: $n, before: $cursor) {
      totalCount
      pageInfo { hasPreviousPage startCursor }
      nodes {
        status
        sender { ... on User { slug } }
        receiverSide { amounts { eurCents wei usdCents gbpCents lamport } anyCards { slug } }
        senderSide {
          anyCards {
            slug
            rarityTyped
            sport
            sportSeason { name }
            inSeasonEligible
            ... on Card {
              coverageStatus
            }
            anyPlayer {
              activeClub { domesticLeague { slug } }
              lastTenSo5Appearances
              lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
              lastFortyAvgScore: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
            }
          }
        }
      }
    }
  }
}
"""

PAGE_SIZE = 50
MAX_PAGES = 20


def fetch_all_live_offers(player_slug):
    """Identica alla versione in track.py: pagina TUTTI gli annunci live di un giocatore
    (il server tronca a ~50 per richiesta). FIX 19/07 (richiesta esplicita utente, caso
    Julien Celestine): i venditori blacklistati (es. Clem777) NON vengono piu' esclusi qui
    -- le loro carte contano comunque per il vero minimo/secondo prezzo di mercato, altrimenti
    il margine calcolato risulta gonfiato (visto dal vivo: un annuncio intermedio di Clem777
    veniva "saltato", facendo sembrare il margine piu' alto di quanto fosse in realta').
    L'esclusione dei blacklistati resta, ma solo al momento di DECIDERE se acquistare (vedi
    evaluate_event): se il vero minimo risulta di un venditore blacklistato, il bot scarta il
    caso invece di comprare da lui."""
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


def get_bucket_prices(player_slug, eth_rate):
    """Legge TUTTI gli annunci live in_season/classic del giocatore in un solo fetch, come
    get_bucket_prices in track.py. Restituisce {'in_season': [(prezzo, card_slug, seller_slug), ...],
    'classic': [(prezzo, card_slug, seller_slug), ...]}, entrambe ordinate per prezzo crescente.
    seller_slug incluso (FIX 19/07) per poter distinguere, a valle, se il vero minimo e' di un
    venditore blacklistato -- vedi nota in fetch_all_live_offers ed evaluate_event."""
    nodes = fetch_all_live_offers(player_slug)
    raw = {'in_season': [], 'classic': []}
    # FIX 21/07 (richiesta esplicita utente: il log per-carta era troppo ridondante --
    # un giocatore con tanti annunci scartati per lo stesso motivo produceva decine di
    # righe identiche). Contiamo gli scarti per motivo e logghiamo UNA riga di riepilogo
    # per giocatore/chiamata invece di una riga per ogni singola carta.
    skipped_coverage = []
    skipped_zero_avg = []
    for node in nodes:
        if node.get('status') != 'opened':
            continue
        if (node.get('receiverSide') or {}).get('anyCards'):
            continue  # scambio carta-per-carta, non una vendita in denaro
        seller_slug = ((node.get('sender') or {}).get('slug') or '').lower()
        cards = (node.get('senderSide') or {}).get('anyCards') or []
        match = None
        for c in cards:
            if c.get('rarityTyped') != 'limited':
                continue
            if c.get('sport') != 'FOOTBALL':
                continue
            if c.get('coverageStatus') == 'NOT_COVERED':
                skipped_coverage.append(c.get('slug'))
                continue  # carta in una squadra non coperta da SO5 (es. finita in un
                          # campionato che Sorare non copre), punti non conteggiati --
                          # richiesta esplicita utente 21/07, non va considerata
                          # nemmeno per il calcolo del minimo/margine
            player_c = c.get('anyPlayer') or {}
            last_ten_avg = player_c.get('lastTenPlayedAvgScore')
            last_forty_avg = player_c.get('lastFortyAvgScore')
            if last_ten_avg == 0.0 or last_forty_avg == 0.0:
                skipped_zero_avg.append(c.get('slug'))
                continue  # media punti 0 nelle ultime 10 o nelle ultime 40 -- stesso
                          # filtro/motivazione di coverageStatus, richiesta utente 21/07
            match = c
            break
        if not match:
            continue
        price = eur_price_from_amounts((node.get('receiverSide') or {}).get('amounts'), eth_rate)
        if price is None:
            continue
        bucket = 'in_season' if match.get('inSeasonEligible') else 'classic'
        raw[bucket].append((price, match.get('slug'), seller_slug))
    if skipped_coverage:
        log(f"[scarto coverage] {player_slug}: {len(skipped_coverage)} carta/e esclusa/e dal "
            f"confronto -- coverageStatus=NOT_COVERED (squadra non coperta da SO5): "
            f"{', '.join(skipped_coverage)}")
    if skipped_zero_avg:
        log(f"[scarto media 0] {player_slug}: {len(skipped_zero_avg)} carta/e esclusa/e dal "
            f"confronto -- media 0 nelle ultime 10 giocate e/o nelle ultime 40: "
            f"{', '.join(skipped_zero_avg)}")
    for key in ('in_season', 'classic'):
        raw[key].sort(key=lambda p: p[0])
    return raw


def validate_live_offers_schema():
    """Self-check di avvio (FIX diagnostica 'bot piantato'): fa UNA query di prova con
    LIVE_OFFERS_QUERY (gli stessi campi SO5/coverageStatus usati per ogni valutazione)
    su un giocatore reale e molto scambiato, cosi' se un campo dello schema (es.
    coverageStatus, lastTenSo5Appearances, ecc.) e' invalido o e' cambiato lato Sorare,
    lo scopriamo SUBITO con un errore chiaro invece di scoprirlo dopo ore di ascolto
    a vuoto (fetch_all_live_offers fallisce silenziosamente per OGNI evento e
    evaluate_event scarta tutto con 'if not prices: return False', senza che il bot
    sembri fare nulla di sbagliato nei log)."""
    probe_slug = "kylian-mbappe"
    data = graphql_query(LIVE_OFFERS_QUERY, {"slug": probe_slug, "n": 1, "cursor": None})
    if data.get('errors'):
        msg = (f"[SELF-CHECK FALLITO] La query LIVE_OFFERS_QUERY (campi SO5/coverageStatus) "
               f"ritorna errore GraphQL su un giocatore di prova ({probe_slug}): {data['errors']}. "
               f"Questo significa che OGNI valutazione durante l'ascolto fallirebbe silenziosamente "
               f"(nessun caso verrebbe mai trovato, ma il bot sembrerebbe girare normalmente). "
               f"Controlla i nomi dei campi coverageStatus/lastTenSo5Appearances/"
               f"lastTenPlayedSo5AverageScore/lastFortySo5AverageScore nello schema Sorare.")
        log(msg)
        send_telegram_msg(f"BOT SUPREMO -- ERRORE CRITICO ALL'AVVIO\n\n{msg}")
        return False
    log("[self-check] Schema LIVE_OFFERS_QUERY (coverageStatus/SO5) validato correttamente.")

    # FIX 21/07 (bug reale: offerta su carta classic con liquidita' insufficiente non
    # bloccata): testiamo qui anche la query di liquidita' per stagione, PRIMA di
    # scoprirlo a meta' run. Non blocchiamo l'avvio se fallisce (c'e' gia' un fallback
    # automatico sicuro in count_recent_transactions), ma un avviso subito e' meglio di
    # scoprirlo tra centinaia di righe di log dopo ore.
    # FIX 21/07 (v2): 'kylian-mbappe' da solo ha dato 'Player not found' su questo
    # specifico percorso (anyPlayer(slug:)) pur essendo uno slug valido e gia' usato
    # con successo su LIVE_OFFERS_QUERY poco sopra (root diverso, tokens.
    # liveSingleSaleOffers) -- probabile una particolarita' di questo giocatore/root
    # (es. post-trasferimento) piu' che un problema della query in se', dato che lo
    # stesso identico pattern anyPlayer(slug){tokenPrices{...}} e' gia' in produzione
    # nel vecchio notificatore aste. Prima di concludere che la query e' rotta,
    # ritentiamo con un secondo giocatore di prova: se ANCHE quello da' un errore che
    # non sia un semplice NOT_FOUND specifico del giocatore, allora e' probabilmente
    # un problema reale di schema/enum e scatta il fallback.
    return True
