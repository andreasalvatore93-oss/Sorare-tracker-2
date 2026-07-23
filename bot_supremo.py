import json
import os
import random
import time
import datetime
import threading
import concurrent.futures
from zoneinfo import ZoneInfo

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
# Cache in memoria per _lista_nera_leggi_righe (ottimizzazione velocita' 21/07) --
# None finche' non e' stata fatta la prima lettura, poi lista di dict finche' non
# viene invalidata da _lista_nera_scrivi_righe dopo ogni scrittura.
_lista_nera_cache = None

# Durate di default (giorni), usate quando il bot AGGIUNGE una riga per conto suo
# (es. dal workflow_dispatch, o registrando un acquisto/offerta/thin-market skip).
# Tutte modificabili qui O a mano nel file cambiando la scadenza di ogni riga.
MANAGER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('MANAGER_BLACKLIST_DEFAULT_DAYS', '365'))
PLAYER_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('PLAYER_BLACKLIST_DEFAULT_DAYS', '3'))
# FIX 21/07: durata SEPARATA (365gg) per la blacklist AUTOMATICA quando un giocatore
# viene scartato per coverageStatus=NOT_COVERED o media punti 0 -- diversa dalla
# blacklist manuale/da workflow (PLAYER_BLACKLIST_DEFAULT_DAYS, 3gg), perche' un
# giocatore con questi problemi resta problematico a lungo, non solo per pochi giorni.
PLAYER_BLACKLIST_DEFAULT_365_DAYS = float(os.environ.get('PLAYER_BLACKLIST_DEFAULT_365_DAYS', '365'))
# FIX 22/07 (richiesta esplicita utente): la blacklist per MEDIA PUNTI ZERO
# (ultime 10 e/o ultime 40) e' stata SEPARATA da quella di coverage -- e' una
# condizione TRANSITORIA (il giocatore puo' tornare a giocare e segnare), quindi
# durata breve (3gg, come forma_bassa_ultime_5) invece dei 365gg permanenti usati
# per coverageStatus=NOT_COVERED (quella si', condizione strutturale/permanente).
MEDIA_ZERO_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('MEDIA_ZERO_BLACKLIST_DEFAULT_DAYS', '3'))
THIN_MARKET_DEFAULT_DAYS = float(os.environ.get('THIN_MARKET_DEFAULT_DAYS', '2'))
COOLDOWN_ACQUISTO_DEFAULT_DAYS = float(os.environ.get('COOLDOWN_ACQUISTO_DEFAULT_DAYS', '1'))
# FIX 21/07 (richiesta esplicita utente): durata default per la blacklist CAMPIONATI --
# 15 giorni, rinnovabile/modificabile a mano nel file come tutte le altre sezioni.
LEAGUE_BLACKLIST_DEFAULT_DAYS = float(os.environ.get('LEAGUE_BLACKLIST_DEFAULT_DAYS', '15'))

_LISTA_NERA_TIPI_VALIDI = ('manager', 'giocatore', 'thin_market', 'cooldown_acquisto', 'campionato',
                           'forma_bassa_ultime_5')

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
    'campionato': (
        "CAMPIONATI BLACKLISTATI -- slug del campionato (es. 'premiership-gb-sct'), "
        "SEZIONE SEPARATA da manager/giocatori/thin_market/cooldown, non confonderla "
        "con le altre. Ogni carta di un giocatore attivo in uno di questi campionati "
        "viene ignorata COMPLETAMENTE (nessun acquisto, nessuna offerta), controllato "
        "PRIMA di qualunque altra valutazione per risparmiare tempo. Durata di default "
        "15 giorni, rinnovabile o modificabile a mano come le altre sezioni."
    ),
    'forma_bassa_ultime_5': (
        "FORMA BASSA ULTIME 5 -- giocatori con media punti SO5 nelle ultime 5 partite "
        "giocate inferiore a 30: ignorati per il tempo indicato (default 1 mese), "
        "SEZIONE SEPARATA e distinta dai blacklist permanenti (coverage/media-zero "
        "restano in 'giocatore'), perche' questa e' una condizione transitoria che "
        "puo' rientrare -- non merita un blocco di 365gg."
    ),
}
_LISTA_NERA_ORDINE_SEZIONI = ('manager', 'giocatore', 'cooldown_acquisto', 'thin_market', 'campionato',
                              'forma_bassa_ultime_5')


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
    {tipo, slug, scadenza (datetime)}. Righe malformate vengono ignorate con log.

    OTTIMIZZAZIONE VELOCITA' (21/07, richiesta esplicita utente -- "trova qualcosa
    da ottimizzare senza rischiare di rompere niente"): CACHATA in memoria per tutta
    la run. Questa funzione viene chiamata per OGNI singolo evento del mercato
    valutato (is_player_in_cooldown + is_player_in_thin_market_cache, dentro
    evaluate_event) -- con centinaia di eventi al minuto, prima del fix questo
    significava altrettante aperture+letture+parsing dell'intero file da disco,
    anche quando il contenuto non era affatto cambiato dall'ultima lettura. La
    cache viene invalidata automaticamente da _lista_nera_scrivi_righe (unico punto
    che modifica il file), quindi resta sempre sincronizzata con lo stato vero --
    zero rischio di leggere dati stantii. NON tocca la logica di
    acquisto/firma/Playwright, solo il path di lettura di questo file."""
    global _lista_nera_cache
    if _lista_nera_cache is not None:
        return _lista_nera_cache

    righe = []
    try:
        with open(LISTA_NERA_PATH, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except FileNotFoundError:
        _lista_nera_cache = righe
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
        # FIX 22/07 (leggibilita' ora locale): un eventuale commento inline '# scade: ...'
        # (aggiunto in scrittura per mostrare l'orario in ora di Roma, puramente
        # informativo) va scartato PRIMA di dividere sulla virgola -- altrimenti
        # finirebbe attaccato al valore ISO/durata e ne romperebbe il parsing.
        stripped_dati = stripped.split('#', 1)[0].strip()
        parts = [p.strip() for p in stripped_dati.split(',')]
        if len(parts) != 2:
            log(f"[lista nera] riga {n} malformata (attesi 2 campi slug,durata), ignorata: {raw!r}")
            continue
        slug, valore_str = parts
        slug = slug.lower()
        # FIX 22/07 (richiesta esplicita utente): thin_market e cooldown_acquisto usano
        # ora una SCADENZA ASSOLUTA (ISO), non piu' una durata testuale -- una durata
        # testuale viene reinterpretata "da adesso" ad OGNI lettura, quindi una riga
        # mai piu' riscritta non scade mai davvero se il file resta statico tra le
        # letture. giocatore/manager/campionato restano a durata leggibile (l'utente
        # vuole poter scrivere/editare "X giorni" a mano per questi).
        if tipo_corrente in ('thin_market', 'cooldown_acquisto', 'forma_bassa_ultime_5'):
            try:
                scadenza = datetime.datetime.fromisoformat(valore_str.replace('Z', '+00:00'))
                if scadenza.tzinfo is None:
                    scadenza = scadenza.replace(tzinfo=datetime.timezone.utc)
                righe.append({'tipo': tipo_corrente, 'slug': slug, 'scadenza': scadenza})
                continue
            except ValueError:
                pass  # non e' ISO -- prova il vecchio formato durata testuale (compatibilita'
                      # con entry scritte prima di questo fix, verranno convertite in ISO alla
                      # prossima riscrittura del file)
            secondi_legacy = _leggibire_wrapper(valore_str, n, raw)
            if secondi_legacy is None:
                continue
            righe.append({'tipo': tipo_corrente, 'slug': slug, 'scadenza': ora + datetime.timedelta(seconds=secondi_legacy)})
            continue
        secondi = _leggibire_wrapper(valore_str, n, raw)
        if secondi is None:
            continue
        righe.append({'tipo': tipo_corrente, 'slug': slug, 'scadenza': ora + datetime.timedelta(seconds=secondi)})
    _lista_nera_cache = righe
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
    volta), non la durata originale -- cosi' l'utente vede sempre quanto manca.
    Invalida la cache di lettura (vedi _lista_nera_leggi_righe) dopo la scrittura,
    cosi' la prossima lettura riflette sempre lo stato vero del file."""
    global _lista_nera_cache
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
        f.write("# Sezioni giocatore/manager/campionato: ogni riga 'slug,durata' (es. 'clem777,5\n")
        f.write("# giorni'). La durata e' il tempo rimanente, aggiornata automaticamente ad ogni\n")
        f.write("# scrittura -- modificabile a mano in qualunque momento (es. '3 ore', '10 giorni').\n")
        f.write("# Sezioni thin_market/cooldown_acquisto: ogni riga 'slug,scadenza_ISO' -- data/ora\n")
        f.write("# ASSOLUTA di scadenza in UTC (fix 22/07: una durata testuale si 'rinnovava' da\n")
        f.write("# sola ad ogni lettura se il file restava statico tra le run). Dopo la virgola, un\n")
        f.write("# commento '# scade: ...' mostra lo stesso istante in ora di Roma (Europe/Rome, si\n")
        f.write("# adatta automaticamente a legale/solare) solo per comodita' di lettura -- il bot\n")
        f.write("# usa SEMPRE e SOLO il valore ISO prima della virgola/cancelletto, il commento e'\n")
        f.write("# puramente informativo e viene ignorato in lettura. NON pensate per modifica a\n")
        f.write("# mano, gestite automaticamente dal bot. Per rimuovere un blocco in ogni sezione,\n")
        f.write("# cancella semplicemente la riga.\n\n")
        for tipo in _LISTA_NERA_ORDINE_SEZIONI:
            righe_tipo = sorted(per_tipo[tipo], key=lambda r: r['slug'])
            f.write(f"## {tipo}\n")
            f.write(f"# {_LISTA_NERA_INTESTAZIONI[tipo]}\n")
            if not righe_tipo:
                f.write("# (vuoto)\n")
            for r in righe_tipo:
                if tipo in ('thin_market', 'cooldown_acquisto', 'forma_bassa_ultime_5'):
                    scadenza_roma = r['scadenza'].astimezone(ZoneInfo('Europe/Rome'))
                    f.write(f"{r['slug']},{r['scadenza'].isoformat()}  "
                            f"# scade: {scadenza_roma.strftime('%d/%m/%Y %H:%M')} ora di Roma\n")
                else:
                    delta = (r['scadenza'] - ora).total_seconds()
                    f.write(f"{r['slug']},{_durata_a_leggibile(delta)}\n")
            f.write("\n")
    # Invalida la cache: la prossima chiamata a _lista_nera_leggi_righe ricarichera'
    # dal file appena scritto, cosi' resta sempre sincronizzata con lo stato vero.
    _lista_nera_cache = None


def _lista_nera_upsert(tipo, slug, giorni_da_ora):
    """Aggiunge o rinnova una riga (tipo, slug) con nuova scadenza = ora + giorni_da_ora.
    Se la riga esiste gia', la sostituisce (rinnovo); altrimenti la aggiunge.
    Protetto da _lista_nera_lock (22/07): con piu' eventi valutati in parallelo,
    senza lock due thread potrebbero leggere lo stesso stato e scriversi sopra a
    vicenda, perdendo un aggiornamento."""
    slug = slug.lower()
    with _lista_nera_lock:
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
BLACKLISTED_LEAGUE_SLUGS = _SetTipoLive('campionato')
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

# FIX 21/07 (richiesta esplicita utente): stesso pattern per campionati -- lo
# slug del primo campionato da blacklistare (es. 'premiership-gb-sct', il
# campionato scozzese) viene passato da workflow_dispatch e scritto nella
# sezione '## campionato' del file unico, editabile a mano in seguito come
# tutte le altre sezioni.
_extra_blacklisted_leagues = os.environ.get('BLACKLISTED_LEAGUE_SLUGS', '')
if _extra_blacklisted_leagues.strip():
    for _s in _extra_blacklisted_leagues.split(','):
        _s = _s.strip().lower()
        if _s:
            _lista_nera_upsert('campionato', _s, LEAGUE_BLACKLIST_DEFAULT_DAYS)

# Log verboso opzionale per il filtro campionati (richiesta esplicita utente per il
# primo test) -- se attivo, logga OGNI carta scartata per campionato blacklistato con
# dettagli; se spento (default), il filtro funziona comunque ma resta silenzioso per
# non riempire i log di rumore una volta che il comportamento e' stato verificato.
LEAGUE_BLACKLIST_VERBOSE_LOG = os.environ.get('LEAGUE_BLACKLIST_VERBOSE_LOG', 'no').strip().lower() in ('si', 'true', '1', 'yes')

# --- Parametri regolabili ---
AUTOBUY_MIN_PRICE_EUR = float(os.environ.get('AUTOBUY_MIN_PRICE_EUR', '1.50'))
AUTOBUY_MAX_PRICE_EUR = float(os.environ.get('AUTOBUY_MAX_PRICE_EUR', '30'))

# Due soglie SEPARATE per fascia, nessuna sovrapponibile per costruzione:
# MAKEOFFER_MARGIN_FRACTION <= margine < MAKEOFFER_MAX_MARGIN_FRACTION -> ramo MakeOffer
# margine >= AUTOBUY_MARGIN_FRACTION -> ramo AutoBuy (deve essere >= al tetto MakeOffer)
MAKEOFFER_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MARGIN_FRACTION', '0.15'))
MAKEOFFER_MAX_MARGIN_FRACTION = float(os.environ.get('MAKEOFFER_MAX_MARGIN_FRACTION', '0.25'))
AUTOBUY_MARGIN_FRACTION = float(os.environ.get('AUTOBUY_MARGIN_FRACTION', '0.26'))

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
OFFER_DISCOUNT_FRACTION = float(os.environ.get('OFFER_DISCOUNT_FRACTION', '0.25'))
OFFER_DURATION_DAYS = max(1, min(7, int(os.environ.get('OFFER_DURATION_DAYS', '1'))))
OFFER_DURATION_SECONDS = OFFER_DURATION_DAYS * 86400
MAX_PENDING_OFFERS = int(os.environ.get('MAX_PENDING_OFFERS', '10'))
pending_offers_count = [0]  # contatore in-memory per run, richiesto da create_direct_offer

# Set in-memory (per-run, non persistito) dei giocatori gia' scritti in blacklist per
# copertura/media punti zero -- evita upsert ripetuti (lettura+riscrittura file) sullo
# stesso slug se ricompare piu' volte nello stesso scan, senza rallentare il flusso.
_gia_blacklistati_coverage_o_media_zero = set()

# Stessa idea, per la nuova sezione 'forma_bassa_ultime_5' (22/07, richiesta esplicita
# utente): evita upsert ripetuti sullo stesso slug se ricompare piu' volte nello stesso
# scan.
_gia_in_forma_bassa_ultime_5 = set()

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


def is_player_in_thin_market_cache(player_slug, is_in_season=True):
    """FIX 21/07 (bug segnalato dall'utente: classic thin market bloccava anche
    l'in_season dello stesso giocatore, che aveva liquidita' normale): stesso
    principio gia' applicato al cooldown acquisto -- suffisso -inseason/-classic
    sullo slug, cosi' le due stagioni sono tracciate separatamente e una classic
    sottile non blocca piu' la ricerca sull'in_season (e viceversa)."""
    return _lista_nera_attiva('thin_market', _slug_cooldown(player_slug, is_in_season))


def record_thin_market_skip(player_slug, is_in_season=True):
    _lista_nera_upsert('thin_market', _slug_cooldown(player_slug, is_in_season), THIN_MARKET_DEFAULT_DAYS)


# FORMA BASSA ULTIME 5 (22/07, richiesta esplicita utente): media punti SO5 nelle
# ultime 5 partite giocate -- se < 30 (strettamente, non <=), il giocatore viene
# ignorato per FORMA_BASSA_DEFAULT_DAYS (default 30gg = 1 mese). A differenza di
# coverage/media-zero (condizioni quasi permanenti, blacklist 365gg in 'giocatore'),
# questa e' una condizione TRANSITORIA (un giocatore puo' tornare in forma), quindi
# sezione separata e scadenza molto piu' breve. Nessun suffisso stagione: la media
# ultime 5 e' una statistica del GIOCATORE, identica per la sua carta in_season e
# classic -- lo stesso della logica coverage/media-zero esistente.
FORMA_BASSA_DEFAULT_DAYS = float(os.environ.get('FORMA_BASSA_DEFAULT_DAYS', '3'))
LAST_FIVE_AVG_SCORE_THRESHOLD = float(os.environ.get('LAST_FIVE_AVG_SCORE_THRESHOLD', '0'))


def is_player_in_forma_bassa(player_slug):
    return _lista_nera_attiva('forma_bassa_ultime_5', (player_slug or '').lower())


def record_forma_bassa(player_slug):
    _lista_nera_upsert('forma_bassa_ultime_5', player_slug, FORMA_BASSA_DEFAULT_DAYS)
    log(f"[lista nera] {player_slug} in 'forma bassa ultime 5' per {FORMA_BASSA_DEFAULT_DAYS:.0f}gg "
        f"-- media SO5 ultime 5 partite sotto soglia ({LAST_FIVE_AVG_SCORE_THRESHOLD:.0f})")

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


GRAPHQL_MIN_INTERVAL_SECONDS_FAST = 0.05
GRAPHQL_MIN_INTERVAL_SECONDS_SAFE = 0.35
GRAPHQL_429_COOLDOWN_SECONDS = 30.0
_graphql_throttle_lock = threading.Lock()
_graphql_last_call_ts = [0.0]
_graphql_last_429_ts = [0.0]


def _graphql_throttle():
    with _graphql_throttle_lock:
        now = time.time()
        recent_429 = (now - _graphql_last_429_ts[0]) < GRAPHQL_429_COOLDOWN_SECONDS
        min_interval = GRAPHQL_MIN_INTERVAL_SECONDS_SAFE if recent_429 else GRAPHQL_MIN_INTERVAL_SECONDS_FAST
        wait = min_interval - (now - _graphql_last_call_ts[0])
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

    # 23/07 (ottimizzazione CDP): pre-registra la funzione di fetch GraphQL UNA
    # SOLA VOLTA su window -- ogni chiamata successiva (_graphql_call_via_browser_raw)
    # invia solo un piccolo wrapper invece del corpo intero della funzione, riducendo
    # l'overhead di trasferimento/parsing per ogni page.evaluate. Stesso identico
    # fetch() reale dentro Chrome, nessun cambiamento di comportamento/fingerprint.
    page.evaluate("""
    () => {
        window.__sorareGraphqlFetch = async (url, payload, csrfToken, deviceFingerprint) => {
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
        };
    }
    """)

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


def _graphql_call_via_browser_raw(query, variables=None):
    """Logica GRAFFA della chiamata GraphQL via browser (get_browser_page +
    page.evaluate), IDENTICA a prima ma SENZA il dispatch a
    _run_on_browser_thread -- da chiamare SOLO quando si e' gia' in esecuzione
    sul thread dedicato al browser (dentro una funzione gia' sottomessa tramite
    _run_on_browser_thread). Chiamarla da un thread diverso causa il crash
    Playwright 'Cannot switch to a different thread'. Introdotta 22/07 v6
    (ottimizzazione velocita', richiesta esplicita utente) per permettere di
    fondere piu' chiamate browser consecutive (es. prepare+accept) in UN SOLO
    dispatch al thread dedicato, invece di uno per chiamata -- dimezza
    l'overhead di cross-thread hop nel percorso critico di acquisto/offerta.
    Gestisce le proprie eccezioni e ritorna sempre un dict (mai propaga)."""
    page = get_browser_page()
    payload = {"query": query, "variables": variables or {}}

    try:
        result = page.evaluate(
            "([url, payload, csrfToken, deviceFingerprint]) => "
            "window.__sorareGraphqlFetch(url, payload, csrfToken, deviceFingerprint)",
            [GRAPHQL_URL, payload, CSRF_TOKEN, SORARE_DEVICE_FINGERPRINT],
        )
        body_text = result.get('body', '')
        return json.loads(body_text)
    except Exception as e:
        log(f"[playwright graphql] eccezione: {e}")
        return {"errors": [{"message": f"playwright_exception: {e}"}]}


def graphql_query_via_browser(query, variables=None, timeout_ms=20000):
    """Fa una chiamata GraphQL usando fetch() DENTRO un vero browser Chrome
    (non con curl_cffi/requests) -- cosi' la richiesta esce con l'impronta
    autentica del browser (TLS, JS engine, eventuali controlli antibot lato
    client), impossibile da imitare fino in fondo con librerie Python.
    Usata SOLO per le chiamate critiche dell'acquisto/offerta (prepareAcceptOffer,
    fetchEncryptedPrivateKey, acceptOffer, prepareOffer, createDirectOffer) --
    ipotesi 20/07 per unknown_fingerprint.
    FIX 22/07 v6: ora un thin wrapper -- la logica vera e' in
    _graphql_call_via_browser_raw (vedi sopra), qui si limita a sottometterla
    sul thread dedicato tramite _run_on_browser_thread. Usare direttamente
    _graphql_call_via_browser_raw (MAI questa funzione) quando si e' gia'
    dentro una funzione sottomessa a _run_on_browser_thread, per evitare un
    doppio dispatch annidato (deadlock certo: l'unico worker del pool
    resterebbe bloccato in attesa di se stesso)."""
    return _run_on_browser_thread(_graphql_call_via_browser_raw, query, variables)


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
            _graphql_last_429_ts[0] = time.time()
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
              lastFiveAvgScore: averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
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
    skipped_forma_bassa = []
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
                # FIX 21/07 (correzione): oltre a scartare la carta per questo confronto,
                # blacklista il giocatore permanentemente (365gg) -- non solo per questa
                # run, richiesta esplicita utente. Set in-memory evita upsert ripetuti
                # (lettura+riscrittura file) se lo stesso slug ricompare piu' volte
                # nello stesso scan.
                if player_slug not in _gia_blacklistati_coverage_o_media_zero:
                    _lista_nera_upsert('giocatore', player_slug, PLAYER_BLACKLIST_DEFAULT_365_DAYS)
                    _gia_blacklistati_coverage_o_media_zero.add(player_slug)
                    log(f"[lista nera] {player_slug} blacklistato 365gg -- carta non coperta "
                        f"da SO5 (coverageStatus=NOT_COVERED)")
                continue  # carta in una squadra non coperta da SO5 (es. finita in un
                          # campionato che Sorare non copre), punti non conteggiati --
                          # richiesta esplicita utente 21/07, non va considerata
                          # nemmeno per il calcolo del minimo/margine
            player_c = c.get('anyPlayer') or {}
            last_ten_avg = player_c.get('lastTenPlayedAvgScore')
            last_forty_avg = player_c.get('lastFortyAvgScore')
            if last_ten_avg == 0.0 or last_forty_avg == 0.0:
                skipped_zero_avg.append(c.get('slug'))
                # FIX 22/07 (richiesta esplicita utente): non piu' blacklist permanente
                # condivisa con coverage -- ora durata breve dedicata
                # (MEDIA_ZERO_BLACKLIST_DEFAULT_DAYS, default 3gg), perche' un giocatore
                # puo' tornare a giocare e la media si aggiorna da sola alla query
                # successiva -- niente senso tenerlo fuori per un anno.
                if player_slug not in _gia_blacklistati_coverage_o_media_zero:
                    _lista_nera_upsert('giocatore', player_slug, MEDIA_ZERO_BLACKLIST_DEFAULT_DAYS)
                    _gia_blacklistati_coverage_o_media_zero.add(player_slug)
                    log(f"[lista nera] {player_slug} blacklistato "
                        f"{MEDIA_ZERO_BLACKLIST_DEFAULT_DAYS:.0f}gg -- media punti 0 "
                        f"nelle ultime 10 e/o nelle ultime 40 giocate")
                continue  # media punti 0 nelle ultime 10 o nelle ultime 40 -- stesso
                          # filtro/motivazione di coverageStatus, richiesta utente 21/07
            last_five_avg = player_c.get('lastFiveAvgScore')
            if last_five_avg is not None and last_five_avg <= LAST_FIVE_AVG_SCORE_THRESHOLD:
                skipped_forma_bassa.append(c.get('slug'))
                # NUOVO 22/07 (richiesta esplicita utente): media SO5 ultime 5 partite
                # sotto soglia -- condizione TRANSITORIA, sezione separata
                # 'forma_bassa_ultime_5' con scadenza breve (default 30gg), non la
                # blacklist permanente 365gg usata per coverage/media-zero sopra.
                if player_slug not in _gia_in_forma_bassa_ultime_5:
                    record_forma_bassa(player_slug)
                    _gia_in_forma_bassa_ultime_5.add(player_slug)
                continue
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
            f"confronto -- coverageStatus=NOT_COVERED (squadra non coperta da SO5)")
    if skipped_zero_avg:
        log(f"[scarto media 0] {player_slug}: {len(skipped_zero_avg)} carta/e esclusa/e dal "
            f"confronto -- media 0 nelle ultime 10 giocate e/o nelle ultime 40")
    if skipped_forma_bassa:
        log(f"[scarto forma bassa] {player_slug}: {len(skipped_forma_bassa)} carta/e esclusa/e "
            f"dal confronto -- media SO5 ultime 5 sotto soglia ({LAST_FIVE_AVG_SCORE_THRESHOLD:.0f})")
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

    return True


def is_asia_americas_excluded_league(league_slug):
    """I 2 campionati (MLS, K League) per cui il confronto con il classic va escluso --
    restano solo con la logica in_season pura gia' in produzione. J League ESCLUSA da questo
    filtro su decisione dell'utente (19/07): per J League vale la logica normale in_season+
    classic come tutti gli altri campionati. Vedi nota nell'area di memoria del progetto:
    motivazione non tecnica, richiesta esplicita dell'utente. Se league_slug e' None/
    sconosciuto (es. giocatore attualmente senza squadra), NON viene considerato escluso --
    si applica comunque in_season+classic, comportamento di default corretto e verificato."""
    return league_slug in EXCLUDED_LEAGUE_SLUGS


def get_in_season_prices(player_slug, eth_rate, league_slug):
    """Restituisce (prices_da_confrontare, is_excluded_league) dove prices_da_confrontare
    e' una lista (prezzo, card_slug) ordinata crescente:
    - Per MLS/K League/J League (is_excluded_league=True): SOLO in_season, comportamento
      identico a prima del confronto con classic (nessuna modifica di logica per questi 3).
    - Per tutti gli altri campionati: in_season + classic UNITI in un'unica lista ordinata,
      trattando il classic come "un ulteriore annuncio in_season" ai fini del vero minimo/
      secondo prezzo -- criterio esplicito richiesto dall'utente."""
    buckets = get_bucket_prices(player_slug, eth_rate)
    excluded = is_asia_americas_excluded_league(league_slug)
    if excluded:
        return buckets['in_season'], True
    combined = buckets['in_season'] + buckets['classic']
    combined.sort(key=lambda p: p[0])
    if AUTOBUY_DIAGNOSTIC and buckets['classic']:
        log(f"[diagnostica lega] player={player_slug} league_slug={league_slug!r} -- "
            f"unito in_season ({len(buckets['in_season'])} annunci) con classic "
            f"({len(buckets['classic'])} annunci) per il confronto sul vero minimo")
    return combined, False


def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log(f"Errore invio Telegram (HTTP {r.status_code}): {r.text[:500]}")
    except Exception as e:
        log(f"Errore invio Telegram: {e}")


def build_card_link(player_slug, card_slug):
    base_link = f"https://sorare.com/it/football/market/shop/manager-sales/{player_slug}/limited"
    return f"{base_link}?card={card_slug}" if card_slug else base_link


# --- Protezione "liquidita' minima del giocatore" (richiesta esplicita utente, 19/07) ---
# Motivazione: se un giocatore ha pochissime transazioni recenti, un annuncio "affare" puo'
# essere frutto di un evento anomalo (es. infortunio, con manager che svendono a raffica le
# poche carte rimaste) piuttosto che un vero errore di prezzo su un mercato liquido -- meglio
# ignorare il caso piuttosto che rischiare di comprare su un mercato cosi' sottile. Query
# riusata da track.py (funzione fetch_player_recent_direct_buys, gia' confermata funzionante
# dal vivo): tokens.tokenPrices(playerSlug, rarity: limited) con deal.type -- a differenza di
# track.py (che filtra SOLO deal.type == 'SINGLE_SALE_OFFER' per isolare lo sniping), qui
# contiamo QUALSIASI transazione (deal.type presente, qualunque valore: SINGLE_SALE_OFFER,
# SINGLE_BUY_OFFER, DIRECT_OFFER, aste, ecc. -- richiesta esplicita "di qualunque tipo incluso
# le aste, offerta diretta, scambio"), perche' qui l'obiettivo e' misurare la liquidita'
# generale del giocatore, non isolare un tipo di transazione specifico.
# FIX 22/07 (unificazione, richiesta esplicita utente -- "perche' funziona solo per
# MLS/Korea, risolvi anche per le altre leghe"): esisteva una SECONDA query,
# RECENT_TRANSACTIONS_QUERY su tokens.tokenPrices(playerSlug), usata per tutti i
# campionati "normali" -- ma quel campo e' CONFERMATO dal server essere una lista
# piatta senza alcuna paginazione (last/before rifiutati esplicitamente). Il campo
# QUI SOTTO (anyPlayer.tokenPrices) e' invece un vero TokenPriceConnection con
# paginazione Relay CONFERMATA FUNZIONANTE dal vivo (last/before/pageInfo). Non c'e'
# alcun motivo di continuare a usare il campo rotto quando lo stesso dato (transazioni
# di un giocatore) e' raggiungibile con paginazione vera tramite questo secondo campo
# -- quindi ora e' l'UNICA query usata, per tutti i campionati. Il filtro per stagione
# (season_filter, via card.inSeasonEligible) viene applicato lato Python SOLO per
# MLS/K-League, esattamente come prima; per gli altri campionati passa None e conta
# tutte le transazioni (in_season+classic mescolate, coerente col resto della logica).
RECENT_TRANSACTIONS_QUERY_BY_SEASON = """
query RecentTransactionsBySeasonQuery($p: String!, $n: Int!, $cursor: String) {
  anyPlayer(slug: $p) {
    tokenPrices(rarity: limited, last: $n, before: $cursor) {
      nodes {
        date
        deal {
          __typename
          ... on TokenOffer {
            type
          }
        }
        card {
          inSeasonEligible
        }
        amounts { eurCents wei usdCents gbpCents lamport }
      }
      pageInfo { hasPreviousPage startCursor }
    }
  }
}
"""
# FIX 22/07 v4 (richiesta esplicita utente -- ottimizzazione velocita', "prova a
# fonderle e facciamo un test con diagnostica"): campo 'amounts' AGGIUNTO qui,
# fondendo questa query con quella (ora ex) dedicata al prezzo -- un solo
# round-trip di rete invece di due, anche se gia' in parallelo. RISCHIO ACCETTATO
# ESPLICITAMENTE dall'utente: questa fusione va CONTRO la scelta originale di
# tenerle separate (vedi nota storica sotto, rimasta per contesto) -- se il campo
# 'amounts' (mai confermato al 100% contro lo schema) dovesse rompersi, ora
# romperebbe ANCHE il conteggio liquidita' (prima isolato e protetto). Fail-safe
# di entrambi i controlli INVARIATO (nessun blocco su acquisti/offerte in caso di
# errore), ma non piu' indipendenti l'uno dall'altro come prima.

# Doppio layer di protezione liquidita' (richiesta esplicita utente, 19/07): la finestra
# breve (7gg) da sola potrebbe far passare un giocatore con un breve picco isolato di
# transazioni ma comunque poco liquido nel complesso -- aggiunta una seconda soglia su
# una finestra piu' lunga (30gg) come controllo incrociato. ENTRAMBE le condizioni devono
# essere soddisfatte perche' il giocatore passi (basta che UNA delle due fallisca per
# scartare il caso).
MIN_RECENT_TRANSACTIONS = int(os.environ.get('MIN_RECENT_TRANSACTIONS', '3'))
RECENT_TRANSACTIONS_WINDOW_DAYS = int(os.environ.get('RECENT_TRANSACTIONS_WINDOW_DAYS', '3'))
MIN_TRANSACTIONS_30D = int(os.environ.get('MIN_TRANSACTIONS_30D', '6'))
TRANSACTIONS_WINDOW_30D_DAYS = int(os.environ.get('TRANSACTIONS_WINDOW_30D_DAYS', '30'))


LIQUIDITY_DIAGNOSTIC = os.environ.get('LIQUIDITY_DIAGNOSTIC', 'no').strip().lower() == 'si'

# STORIA (22/07, superata dalla fusione sopra, lasciata per contesto): il prezzo da
# pagare (AutoBuy) o da offrire (MakeOffer, gia' scontato) deve essere INFERIORE
# all'ultima transazione reale (vendita/scambio/asta) di quella carta -- altrimenti
# si rischia di pagare piu' di quanto qualcuno abbia gia' accettato di recente.
# In origine questa era una query SEPARATA e DEDICATA proprio per isolare il rischio
# del campo 'amounts' non confermato -- ora fusa nella query di liquidita' sopra su
# richiesta esplicita dell'utente, che ha accettato il rischio di accoppiamento.
# NOTA 22/07 v4: _LAST_PRICE_CHECK_DISABLED/_last_price_warning_logged (kill-switch
# manuale per un errore di schema sul campo 'amounts') sono state RIMOSSE -- non
# avevano piu' un punto di attivazione chiaro dopo la fusione delle query (il
# fallimento del fetch ora e' gestito a monte in get_liquidity_and_last_price,
# fail-open su entrambi i risultati).


def get_last_transaction_prices(player_slug, is_in_season, league_slug, eth_rate, nodes):
    """Ritorna una tupla (ultimo_prezzo, penultimo_prezzo) delle transazioni reali
    (vendita/scambio/asta) piu' recenti di player_slug, in EUR -- ciascuno None se non
    disponibile/query fallita (fail-safe, il chiamante NON deve bloccare l'acquisto
    solo per questo).

    FIX 22/07 v2 (richiesta esplicita utente, secondo layer di protezione): oltre
    all'ultima transazione, ora si guarda anche la PENULTIMA -- protezione in piu'
    contro il caso in cui l'ultima transazione sia un singolo valore anomalo/outlier
    (es. una svendita isolata) che da sola non rappresenta il vero prezzo di mercato,
    mentre la penultima racconta una storia diversa. Rinominata al plurale (era
    get_last_transaction_price) per riflettere che ora ritorna piu' di un valore --
    nessun'altra logica cambiata.

    Stessa differenziazione per campionato gia' in uso altrove (richiesta esplicita
    utente): MLS/K-League confrontano SOLO la stagione giusta (season vs season,
    classic vs classic); altri campionati prendono le transazioni in assoluto,
    mescolando in_season+classic (coerente col resto della logica per questi
    campionati).

    FUSIONE 22/07 (richiesta esplicita utente): non fa piu' una query di rete
    propria -- riceve 'nodes', gia' scaricati una volta sola da
    get_liquidity_and_last_price (stessa lista usata anche per il conteggio
    liquidita'). Funzione pura, stessa identica logica di derivazione di prima
    (ordinamento esplicito per data decrescente + filtro stagione solo sui
    campionati esclusi)."""
    def _parse_date_per_ordinamento(nodo):
        try:
            return datetime.datetime.fromisoformat((nodo.get('date') or '').replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    nodes_ordinati = sorted(nodes or [], key=_parse_date_per_ordinamento, reverse=True)

    excluded_league = is_asia_americas_excluded_league(league_slug)
    prezzi_trovati = []
    for node in nodes_ordinati:
        if excluded_league:
            card = node.get('card') or {}
            if bool(card.get('inSeasonEligible')) != is_in_season:
                continue
        price = eur_price_from_amounts(node.get('amounts'), eth_rate)
        if price is not None:
            prezzi_trovati.append(price)
            if len(prezzi_trovati) == 2:
                break
    ultimo = prezzi_trovati[0] if len(prezzi_trovati) >= 1 else None
    penultimo = prezzi_trovati[1] if len(prezzi_trovati) >= 2 else None
    return ultimo, penultimo

# NUOVA PROTEZIONE (22/07, richiesta esplicita utente): oltre alla liquidita' storica
# (transazioni passate), controlla anche quante carte dello stesso giocatore sono
# ATTUALMENTE in vendita in questo momento -- un mercato con pochissimi annunci vivi
# e' rischioso anche se lo storico transazioni sembra ok. Usa la stessa lista 'prices'
# gia' calcolata per il margine (nessuna query aggiuntiva), che segue gia' la stessa
# separazione per stagione del resto della logica: MLS/K-League confrontano SOLO la
# stagione giusta (season vs season, classic vs classic), gli altri campionati
# mescolano in_season+classic come sempre.
MIN_LISTED_CARDS_FOR_PURCHASE = int(os.environ.get('MIN_LISTED_CARDS_FOR_PURCHASE', '4'))
MIN_LISTED_CARDS_DIAGNOSTIC = os.environ.get('MIN_LISTED_CARDS_DIAGNOSTIC', 'no').strip().lower() == 'si'

# NUOVO 22/07 (richiesta esplicita utente): log dedicato opt-in (default spento) per
# segnalare quando un'offerta e' stata fatta/tentata tramite il meccanismo "trigger su
# minimo non allineato" -- vedi evaluate_event per la logica completa.
MIN_NON_TRIGGER_LOG = os.environ.get('MIN_NON_TRIGGER_LOG', 'no').strip().lower() == 'si'


def _count_transactions_from_nodes(nodes, season_filter=None, player_slug=None, force_log=False):
    """Fattorizzata da count_recent_transactions: conta le transazioni valide (short/long
    window) da una lista di nodi tokenPrices, qualunque sia la query che li ha prodotti.

    season_filter: se non None (True=in_season, False=classic), scarta i nodi il cui
    campo card.inSeasonEligible non corrisponde -- usato solo dalla query per stagione
    (RECENT_TRANSACTIONS_QUERY_BY_SEASON, che porta quel campo); la query combinata di
    fallback non ha quel campo nei nodi quindi li passa tutti (season_filter=None).

    DIAGNOSTICA (22/07, richiesta esplicita utente -- giocatori con transazioni reali
    visibili sul sito segnalati come 'mercato sottile' dal bot): se LIQUIDITY_DIAGNOSTIC='si'
    logga, per player_slug, il totale nodi ricevuti dal server e quanti vengono scartati
    da ciascun filtro (season_filter, is_countable, data non parsabile, fuori finestra
    30gg) -- permette di capire SENZA ambiguita' se il problema e' il filtro is_countable
    (deal.__typename non previsto), la finestra data, o il numero di nodi che il server
    restituisce per quella query (possibile troncamento lato server, mai verificato).

    force_log (22/07, seconda diagnostica -- permanente, non opt-in): se True, stampa
    lo stesso identico blocco diagnostico indipendentemente da LIQUIDITY_DIAGNOSTIC.
    Usato da evaluate_event proprio nel momento in cui una carta rischia di essere
    scartata per mercato sottile, cosi' la PROSSIMA volta che succede dal vivo il log
    del run contiene gia' tutto il dettaglio necessario, senza dover rilanciare un
    test isolato a posteriori."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_short = now - datetime.timedelta(days=RECENT_TRANSACTIONS_WINDOW_DAYS)
    cutoff_long = now - datetime.timedelta(days=TRANSACTIONS_WINDOW_30D_DAYS)
    count_short = 0
    count_long = 0
    diag_totale = len(nodes)
    diag_scartati_stagione = 0
    diag_scartati_tipo = 0
    _diag_on = LIQUIDITY_DIAGNOSTIC or force_log
    diag_typename_visti = {} if _diag_on else None
    diag_scartati_data = 0
    diag_scartati_finestra = 0
    for n in nodes:
        if season_filter is not None:
            card = n.get('card') or {}
            if bool(card.get('inSeasonEligible')) != season_filter:
                diag_scartati_stagione += 1
                continue
        deal = n.get('deal') or {}
        deal_typename = deal.get('__typename')
        if _diag_on:
            diag_typename_visti[str(deal_typename)] = diag_typename_visti.get(str(deal_typename), 0) + 1
        is_countable = bool(deal.get('type')) or deal_typename in ('TokenAuction', 'TokenPrimaryOffer')
        if not is_countable:
            diag_scartati_tipo += 1
            continue
        date_str = n.get('date') or ''
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            diag_scartati_data += 1
            continue
        if dt >= cutoff_long:
            count_long += 1
            if dt >= cutoff_short:
                count_short += 1
        else:
            diag_scartati_finestra += 1
    if _diag_on:
        log(f"[diagnostica liquidita'] {player_slug or '?'}: season_filter={season_filter}, "
            f"nodi totali ricevuti dal server={diag_totale}, scartati per stagione={diag_scartati_stagione}, "
            f"scartati per tipo deal (is_countable=False)={diag_scartati_tipo}, "
            f"tipi __typename visti={diag_typename_visti}, "
            f"scartati per data non parsabile={diag_scartati_data}, "
            f"scartati perche' fuori finestra 30gg={diag_scartati_finestra}, "
            f"risultato finale: count_7d={count_short}, count_30d={count_long}")
    return count_short, count_long


TRANSACTIONS_PAGE_SIZE = 50
TRANSACTIONS_MAX_PAGES = 2


def _fetch_paginated_transaction_nodes(player_slug):
    """Pagina davvero le transazioni di un giocatore tramite anyPlayer.tokenPrices, un
    vero TokenPriceConnection con paginazione Relay CONFERMATA funzionante dal vivo
    (last/before/pageInfo). Usata per TUTTI i campionati (22/07: unificata, prima
    esisteva un secondo campo -- tokens.tokenPrices(playerSlug) -- confermato invece
    essere una lista piatta senza paginazione, rimosso perche' ridondante e peggiore).
    Si ferma quando il nodo piu' vecchio della pagina esce dalla finestra 7gg (i nodi
    arrivano dal piu' recente al piu' vecchio con 'last', ordine Relay standard), quando
    il server non ha piu' pagine, o dopo TRANSACTIONS_MAX_PAGES di sicurezza.
    FIX 22/07 v5 (richiesta esplicita utente, chiave del rallentamento su giocatori
    molto scambiati come Angus Gunn/Hrvoje Babec): il taglio era ancora a 30gg
    (TRANSACTIONS_WINDOW_30D_DAYS) nonostante count_30d non sia piu' usato per
    nessuna decisione dal fix che ha rimosso la soglia 30gg -- solo un log
    diagnostico opzionale lo legge. Per un giocatore molto scambiato, le prime 50
    transazioni possono coprire solo pochi giorni, costringendo la paginazione a
    tirare dentro pagine su pagine pur di arrivare a 30gg -- tempo sprecato per un
    dato che non serve piu'. Ora si ferma a 7gg (RECENT_TRANSACTIONS_WINDOW_DAYS,
    la stessa finestra dell'unica soglia ancora attiva): count_7d resta identico e
    accurato (la finestra e' comunque sempre coperta per intero), ultimo/penultimo
    prezzo restano identici (derivati da qualunque nodo gia' fetchato, indipendenti
    dal taglio), count_30d diventa potenzialmente sottostimato ma e' innocuo (mai
    usato per decisioni, solo diagnostica).
    FIX 22/07 (richiesta esplicita utente -- ripristino log puliti): il log dettagliato
    per pagina torna OPT-IN (LIQUIDITY_DIAGNOSTIC='si'), non piu' permanente su ogni
    chiamata -- era stato reso permanente durante l'indagine sul falso mercato sottile,
    ora che la causa e' stata isolata ed esclusa non serve piu' di default."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_pagine = now - datetime.timedelta(days=RECENT_TRANSACTIONS_WINDOW_DAYS)
    all_nodes = []
    cursor = None
    for page_num in range(1, TRANSACTIONS_MAX_PAGES + 1):
        data = graphql_query(RECENT_TRANSACTIONS_QUERY_BY_SEASON,
                              {"p": player_slug, "n": TRANSACTIONS_PAGE_SIZE, "cursor": cursor})
        if data.get('errors'):
            log(f"[liquidita' paginazione] {player_slug}: pagina {page_num} errore GraphQL: {data['errors']}")
            break
        conn = ((data.get('data') or {}).get('anyPlayer') or {}).get('tokenPrices') or {}
        nodes = conn.get('nodes') or []
        all_nodes.extend(nodes)
        page_info = conn.get('pageInfo') or {}
        oldest_date_str = nodes[-1].get('date') if nodes else None
        if LIQUIDITY_DIAGNOSTIC:
            log(f"[liquidita' paginazione] {player_slug}: pagina {page_num}, "
                f"{len(nodes)} nodi (totale {len(all_nodes)}), piu' vecchio: {oldest_date_str or 'n/d'}")
        if not nodes:
            break
        try:
            oldest_dt = datetime.datetime.fromisoformat((oldest_date_str or '').replace('Z', '+00:00'))
            if oldest_dt < cutoff_pagine:
                if LIQUIDITY_DIAGNOSTIC:
                    log(f"[liquidita' paginazione] {player_slug}: nodo piu' vecchio "
                        f"della pagina {page_num} fuori dalla finestra {RECENT_TRANSACTIONS_WINDOW_DAYS}gg, mi fermo")
                break
        except (ValueError, AttributeError):
            pass
        if not page_info.get('hasPreviousPage'):
            break
        cursor = page_info.get('startCursor')
        if not cursor:
            break
    return all_nodes


def get_liquidity_and_last_price(player_slug, is_in_season=True, league_slug=None, eth_rate=None,
                                  force_diagnostic=False):
    """FUSIONE 22/07 (richiesta esplicita utente -- "prova a fonderle"): un SOLO
    fetch paginato (_fetch_paginated_transaction_nodes) al posto delle due query
    separate di prima (conteggio liquidita' + ultimo/penultimo prezzo) -- un solo
    round-trip di rete invece di due, anche se gia' in parallelo. Da questa stessa
    lista di nodi si derivano ENTRAMBI i risultati:
    - count_7d/count_30d via _count_transactions_from_nodes (season_filter=
      is_in_season SEMPRE, per tutti i campionati -- fix Souleymane Isaak Touré,
      invariato)
    - ultimo/penultimo prezzo via get_last_transaction_prices (ora funzione pura,
      nessuna chiamata di rete propria, riceve i nodi gia' scaricati)

    RISCHIO ACCETTATO ESPLICITAMENTE dall'utente: le due query erano separate DI
    PROPOSITO (vedi nota storica sopra la vecchia LAST_TRANSACTION_PRICE_QUERY)
    per isolare il campo 'amounts' (mai confermato al 100% contro lo schema) dal
    conteggio liquidita' gia' validato -- fondendole, un problema sul campo
    'amounts' ora romperebbe ANCHE il conteggio liquidita' (prima restava isolato).
    Fail-safe INVARIATO: se il fetch fallisce, i nodi tornano vuoti, count_7d
    risulta 0 (sotto soglia -> scarto per mercato sottile, esito sicuro) e
    ultimo/penultimo tornano None (controllo prezzo saltato, non blocca).

    Ritorna (count_7d, count_30d, ultimo_prezzo, penultimo_prezzo)."""
    season_filter = is_in_season
    if force_diagnostic:
        excluded_league = is_asia_americas_excluded_league(league_slug)
        log(f"[diagnostica liquidita'] {player_slug}: chiamata con is_in_season={is_in_season}, "
            f"league_slug={league_slug!r}, excluded_league(MLS/K-League)={excluded_league}, "
            f"season_filter effettivo={season_filter}")
    try:
        nodes = _fetch_paginated_transaction_nodes(player_slug)
    except Exception as e:
        log(f"[liquidita'+ultimo prezzo] eccezione per {player_slug}: {e}")
        return None, None, None, None

    count_7d, count_30d = _count_transactions_from_nodes(
        nodes, season_filter=season_filter, player_slug=player_slug, force_log=force_diagnostic)
    ultimo, penultimo = get_last_transaction_prices(player_slug, is_in_season, league_slug, eth_rate, nodes)

    if LIQUIDITY_DIAGNOSTIC:
        log(f"[diagnostica fusione] {player_slug}: {len(nodes)} nodi fetched (1 sola query) -- "
            f"count_7d={count_7d}, count_30d={count_30d}, ultimo={ultimo}, penultimo={penultimo}")

    return count_7d, count_30d, ultimo, penultimo


EXCHANGE_RATE_QUERY = """
query ExchangeRateQuery {
  config {
    exchangeRate { id }
  }
}
"""


def get_exchange_rate_id():
    """Recupera l'id del tasso di cambio corrente (serve a PrepareAcceptOfferMutation/
    PrepareOfferMutation), stessa query ExchangeRateQuery vista nel flusso reale di
    acquisto in browser.
    OTTIMIZZAZIONE VELOCITA' (20/07, richiesta esplicita utente -- ogni millisecondo
    conta nello sniping): CACHATO in memoria per l'intera durata del run, stesso
    principio gia' usato per fetch_encrypted_private_key. Il tasso di cambio (qui
    sempre EUR, la valuta di acquisto/offerta e' sempre EUR) non cambia abbastanza in
    fretta da giustificare una query di rete separata ad OGNI singolo tentativo --
    prima query del run la recupera, tutte le successive riusano lo stesso valore
    senza contattare di nuovo il server. Elimina una chiamata di rete intera dal
    percorso critico di ogni acquisto/offerta.
    """
    try:
        data = graphql_query(EXCHANGE_RATE_QUERY)
        rate_id = (((data.get('data') or {}).get('config') or {}).get('exchangeRate') or {}).get('id')
        return rate_id
    except Exception as e:
        log(f"[prepare accept] errore lettura tasso di cambio: {e}")
        return None

PREPARE_ACCEPT_OFFER_MUTATION = """
mutation PrepareAcceptOfferMutation($input: prepareAcceptOfferInput!) {
  prepareAcceptOffer(input: $input) {
    authorizations {
      fingerprint
      id
      request {
        ... on MangopayWalletTransferAuthorizationRequest {
          currency
          amount
          mangopayWalletId
          nonce
          operationHash
        }
      }
    }
    errors { message }
    primaryOffer { id }
  }
}
"""


def classify_prepare_accept_error(root_errors, payload_errors):
    """Classifica gli errori di PrepareAcceptOfferMutation/AcceptOfferMutation in categorie
    note, per poter loggare/notificare in modo chiaro E per dare a fase 2 (automazione
    completa) un segnale univoco su cosa e' successo. Finche' non osserviamo dal vivo i
    messaggi esatti per fondi insufficienti / valuta non supportata / offerta scaduta,
    questa funzione e' VOLUTAMENTE conservativa: qualunque errore non riconosciuto finisce
    in 'sconosciuto', mai in una categoria che potrebbe indurre un retry o un tentativo
    alternativo automatico. Principio fisso per fase 2: ogni categoria = STOP, mai retry.
    Ritorna (category, raw_errors) dove category e' una delle stringhe:
    'fondi_insufficienti', 'valuta_non_supportata', 'offerta_non_disponibile',
    'nessun_errore', 'sconosciuto'."""
    all_errors = list(root_errors or []) + list(payload_errors or [])
    if not all_errors:
        return 'nessun_errore', all_errors

    combined_text = ' '.join(
        str(e.get('message', '')) + ' ' + str(e.get('extensions', {}).get('code', ''))
        for e in all_errors if isinstance(e, dict)
    ).lower()

    # Parole chiave PROVVISORIE (da confermare/affinare al primo caso reale osservato) --
    # non togliamo mai un errore dalla categoria 'sconosciuto' solo per somiglianza vaga.
    if any(kw in combined_text for kw in
           ('insufficient', 'not_enough', 'balance', 'fondi', 'saldo')):
        return 'fondi_insufficienti', all_errors
    if any(kw in combined_text for kw in
           ('currency', 'payment_method', 'unsupported', 'valuta')):
        return 'valuta_non_supportata', all_errors
    if any(kw in combined_text for kw in
           ('not_found', 'expired', 'already', 'sold', 'unavailable', 'not_available')):
        return 'offerta_non_disponibile', all_errors

    return 'sconosciuto', all_errors


# FIX BUG CRITICO (20/07): durante la fusione dei due bot, la funzione di
# classificazione errori del ramo MakeOffer (classify_prepare_offer_error) e' stata
# accorpata in classify_prepare_accept_error, ma create_direct_offer/prepare_offer
# continuavano a chiamare il vecchio nome -- causava NameError ad OGNI offerta live
# reale (visto dal vivo: caso Sean Johnson e Leandro Paredes, quest'ultimo sniperato
# nel frattempo perche' l'offerta non e' mai partita a causa di questo crash). La
# logica di classificazione e' identica per entrambi i rami (stessi messaggi
# GraphQL/categorie), quindi alias diretto, nessuna duplicazione.
classify_prepare_offer_error = classify_prepare_accept_error


def prepare_accept_offer(offer_id, _call_fn=None):
    """FASE 2 (prima meta'): 'prenota'/valida l'offerta lato server chiamando la stessa
    PrepareAcceptOfferMutation usata dal sito quando l'utente clicca 'Acquista', PRIMA
    ancora che l'utente clicchi -- riduce la finestra in cui un altro manager potrebbe
    comprare la carta nel frattempo. NON firma nulla (nessuna chiave privata coinvolta):
    restituisce solo l'operationHash/nonce che servirebbero alla firma, dati utili da
    includere nella notifica per velocizzare la conferma manuale. Ritorna la tupla
    (dict 'authorizations[0].request', categoria_errore) -- il dict e' None se la
    chiamata fallisce, e categoria_errore e' valorizzata SOLO in quel caso (es.
    'valuta_non_supportata' per annunci in ETH/crypto, non gestibili dall'acquisto
    automatico) cosi' il chiamante puo' distinguere questo caso da un fallimento
    generico invece di loggare sempre lo stesso messaggio. Il click finale
    dell'utente sul sito resta INVARIATO e necessario (fase 2 = opzione "conferma manuale",
    vedi nota progetto).
    _call_fn (22/07 v6, ottimizzazione velocita'): vedi nota su fetch_encrypted_private_key
    -- passare _graphql_call_via_browser_raw quando gia' dentro un dispatch a
    _run_on_browser_thread, per fondere piu' chiamate in un solo hop."""
    call_fn = _call_fn or graphql_query_via_browser
    exchange_rate_id = get_exchange_rate_id()
    if not exchange_rate_id:
        log("[prepare accept] exchange_rate_id non ottenuto, impossibile procedere")
        return None, None
    variables = {
        "input": {
            "offerId": offer_id,
            "attemptReference": None,
            "settlementInfo": {
                "currency": "EUR",
                "exchangeRateId": exchange_rate_id,
                "paymentMethod": "WALLET",
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        }
    }
    try:
        data = call_fn(PREPARE_ACCEPT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('prepareAcceptOffer') or {}
        payload_errors = payload.get('errors') or []

        if root_errors or payload_errors:
            category, all_errors = classify_prepare_accept_error(root_errors, payload_errors)
            log(f"[prepare accept] fallita, categoria='{category}', errori={all_errors}")
            return None, category

        auths = payload.get('authorizations') or []
        if not auths:
            log("[prepare accept] nessuna authorization restituita, categoria='sconosciuto'")
            return None, 'sconosciuto'
        # Restituiamo fingerprint + request (con __typename incluso) -- servono ENTRAMBI a
        # sign_authorization_via_node/signAuthorizationRequest quando si attivera' la firma
        # automatica (opzione 1, non ancora collegata a nulla qui). Oggi 'fingerprint' non
        # viene ancora usato da nessuna parte del bot.
        auth = auths[0]
        request = dict(auth.get('request') or {})
        request['__typename'] = 'MangopayWalletTransferAuthorizationRequest'
        # FIX 19/07 (velocizzazione sniping): esponiamo anche exchange_rate_id gia'
        # ottenuto qui, cosi' execute_live_purchase puo' riusarlo invece di rifare la
        # stessa query GraphQL una seconda volta -- ogni millisecondo conta nello sniping.
        # FIX 20/07 (nuovo tentativo unknown_fingerprint): espongo anche l'id completo
        # dell'authorization ("TokenService::Core::MangopayWalletTransferAuthorization:
        # UUID"), diverso dal fingerprint (che e' sempre lo stesso valore fisso in ogni
        # test, confermato anche nel caso riuscito -- probabilmente identifica il TIPO
        # di authorization, non l'istanza specifica). L'id invece cambia sempre, ad ogni
        # chiamata -- e' l'ipotesi piu' plausibile di identificatore reale da correlare
        # con fetchEncryptedPrivateKey.
        return {'fingerprint': auth.get('fingerprint'), 'request': request,
                'exchange_rate_id': exchange_rate_id, 'authorization_id': auth.get('id')}, None
    except Exception as e:
        log(f"[prepare accept] eccezione: {e}")
        return None, 'sconosciuto'


import subprocess
import queue
import collections

# OTTIMIZZAZIONE VELOCITA' SNIPING (21/07, richiesta esplicita utente): il processo
# Node per la firma non viene piu' avviato da zero ad OGNI acquisto/offerta -- resta
# vivo per tutta la run e riceve richieste ripetute via un protocollo a righe
# (NDJSON) su stdin/stdout, vedi sorare-sign/decrypt_and_sign.js. Avviare Node e
# caricare @sorare/crypto costa tipicamente qualche centinaio di millisecondi:
# prima veniva pagato ad ogni singolo tentativo, ora si paga UNA SOLA VOLTA
# (idealmente gia' durante il warm-up all'avvio, vedi main()). Un thread separato
# legge le risposte dallo stdout del processo cosi' il chiamante puo' aspettarle
# con un timeout vero (niente rischio di restare bloccati per sempre se il
# processo Node si pianta senza rispondere).
_node_process = None
_node_process_lock = threading.Lock()
# OTTIMIZZAZIONE VELOCITA' -- CONCORRENZA (22/07, richiesta esplicita utente,
# rischio accettato): con piu' eventi valutati in parallelo (vedi run_listener/
# on_message piu' sotto), queste risorse condivise NON erano protette prima
# (bastava un solo thread alla volta). _lista_nera_lock protegge il ciclo
# leggi-modifica-scrivi di _lista_nera_upsert (senza lock, due thread potrebbero
# leggere lo stesso stato e poi sovrascriversi a vicenda, perdendo un
# aggiornamento -- "lost update"). _browser_lock protegge l'uso della singola
# pagina Playwright condivisa (graphql_query_via_browser) -- non e' pensata per
# essere usata da piu' thread contemporaneamente. _node_process_lock (sopra)
# esisteva GIA' e protegge gia' correttamente la comunicazione col processo Node
# di firma, nessuna modifica necessaria li'.
_lista_nera_lock = threading.Lock()
# FIX 22/07 v2 (bug reale confermato dal vivo, 3 casi -- "Cannot switch to a
# different thread" / greenlet): un _browser_lock semplice NON basta per
# Playwright in modalita' sync -- la sua API e' legata (via greenlet) al thread
# ESATTO che l'ha creata/usata, non solo serializzata nell'accesso. Chiamarla da
# un thread DIVERSO fallisce sempre, anche con un lock che garantisce "un thread
# alla volta" -- il problema non e' la concorrenza, e' l'identita' del thread.
# FIX: un ThreadPoolExecutor con un SOLO worker dedicato -- ogni interazione con
# Playwright (creazione inclusa) passa SEMPRE da li', sottomessa e attesa
# (.result()) da qualunque thread la richieda, cosi' Playwright vede sempre lo
# stesso identico thread dall'inizio alla fine della run.
_browser_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='browser')
# OTTIMIZZAZIONE VELOCITA' 23/07 (stessa idea del parallelismo prepare_accept_offer/
# liquidita', estesa al ramo MakeOffer): pool DEDICATO e leggero per chiamate non-
# Playwright che possono partire in anticipo (get_card_offer_details) in parallelo
# alla query di liquidita' -- separato da _browser_executor (riservato a Playwright)
# e da event_executor (per non contendere con la valutazione di altri eventi in corso).
_speculative_executor = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix='speculative')


def _run_on_browser_thread(fn, *args, **kwargs):
    """Esegue fn(*args, **kwargs) SEMPRE sull'unico thread dedicato al browser
    Playwright (vedi nota sopra su _browser_executor) -- usare per QUALUNQUE
    interazione con get_browser_page/pagina/browser/playwright, sia in lettura
    che in scrittura, chiamata da qualunque altro thread.

    DIAGNOSTICA TEMPORANEA CODA (22/07, richiesta esplicita utente -- capire se
    piu' candidati valutati in parallelo si mettono in coda su questo unico
    thread dedicato): misura quanto tempo passa tra la richiesta di questa
    chiamata e l'inizio effettivo dell'esecuzione sul thread dedicato -- se
    l'unico worker e' gia' occupato con un'altra chiamata, questo tempo cresce.
    Log solo se l'attesa e' non trascurabile, per non riempire i log a vuoto.
    RIMUOVERE (il wrapping + il blocco di log) quando l'indagine e' conclusa."""
    _t_richiesta = time.monotonic()

    def _con_diagnostica():
        if EVENT_TIMING_DIAGNOSTIC:
            _attesa = time.monotonic() - _t_richiesta
            if _attesa > 0.01:
                log(f"[diagnostica coda browser] attesa in coda prima di iniziare "
                    f"{getattr(fn, '__name__', '?')}: {_attesa:.3f}s")
        return fn(*args, **kwargs)

    return _browser_executor.submit(_con_diagnostica).result()
_node_stdout_queue = None
_node_stderr_tail = collections.deque(maxlen=20)


def _node_stdout_reader(proc, q):
    """Gira in un thread dedicato per tutta la vita del processo Node: legge una
    riga alla volta dal suo stdout e la mette in coda. Quando lo stdout si chiude
    (processo terminato/crashato), mette None in coda cosi' chi e' in attesa lo sa
    subito invece di restare appeso fino al timeout."""
    try:
        for line in proc.stdout:
            q.put(line)
    except Exception:
        pass
    q.put(None)


def _node_stderr_reader(proc, tail):
    """Thread dedicato per lo stderr del processo Node: lo teniamo solo per
    diagnostica (ultime righe, utili nei log se una richiesta fallisce o il
    processo muore), non blocca mai nessuno."""
    try:
        for line in proc.stderr:
            tail.append(line.rstrip('\n'))
    except Exception:
        pass


def _ensure_node_sign_process():
    """Ritorna il processo Node persistente per la firma, avviandolo (o
    riavviandolo se e' morto) se necessario. Chiamata sempre sotto
    _node_process_lock dal chiamante."""
    global _node_process, _node_stdout_queue
    if _node_process is not None and _node_process.poll() is None:
        return _node_process

    if _node_process is not None:
        log(f"[firma Node] il processo persistente precedente non e' piu' attivo "
            f"(codice uscita {_node_process.poll()}), lo riavvio -- ultime righe stderr: "
            f"{list(_node_stderr_tail)}")

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sorare-sign', 'decrypt_and_sign.js')
    log("[firma Node] avvio processo Node persistente per la firma "
        "(una tantum/riavvio, poi resta vivo e riusato per tutta la run)...")
    proc = subprocess.Popen(
        ['node', script_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,  # line-buffered, essenziale per il protocollo a righe
    )
    q = queue.Queue()
    threading.Thread(target=_node_stdout_reader, args=(proc, q), daemon=True).start()
    threading.Thread(target=_node_stderr_reader, args=(proc, _node_stderr_tail), daemon=True).start()
    _node_process = proc
    _node_stdout_queue = q
    return proc


def close_node_sign_process():
    """Chiude il processo Node persistente a fine run (chiamata da close_browser/
    finally in main()), stesso principio di pulizia gia' applicato al browser
    Playwright -- non lasciare processi appesi al termine del workflow."""
    global _node_process
    with _node_process_lock:
        if _node_process is not None:
            try:
                if _node_process.poll() is None:
                    _node_process.stdin.close()
                    _node_process.wait(timeout=5)
            except Exception as e:
                log(f"[firma Node] errore chiudendo il processo persistente: {e}")
                try:
                    _node_process.kill()
                except Exception:
                    pass
            _node_process = None


def sign_authorization_via_node(password, encrypted_private_key, iv, salt, authorization_request):
    """Invia una richiesta di firma al processo Node PERSISTENTE (vedi
    _ensure_node_sign_process sopra) tramite il protocollo a righe di
    sorare-sign/decrypt_and_sign.js: una riga JSON in stdin, una riga JSON in
    risposta da stdout, timeout vero via thread separato.

    Lo script Node decripta la chiave privata (PBKDF2 + AES-GCM, stesso algoritmo usato
    dal sito sorare.com) e poi chiama @sorare/crypto.signAuthorizationRequest per
    ottenere la signature.

    OTTIMIZZAZIONE VELOCITA' (20/07 + 21/07, richiesta esplicita utente -- ogni
    millisecondo conta nello sniping): la chiave privata decriptata e' SEMPRE la
    stessa per tutta la sessione (stessa password/encrypted_private_key/iv/salt,
    gia' cachati a monte in _encrypted_key_cache) -- rifare il decrypt PBKDF2(50000
    iterazioni)+AES-GCM ad OGNI singolo acquisto/offerta e' uno spreco puro. Dalla
    SECONDA chiamata in poi nella stessa sessione, saltiamo il decrypt passando
    direttamente la chiave gia' in chiaro allo script Node (campo
    'decryptedPrivateKey'). IN PIU' (21/07): il processo Node stesso non viene piu'
    riavviato ad ogni chiamata -- resta vivo per tutta la run, eliminando anche il
    costo fisso di avvio Node + caricamento di @sorare/crypto da ogni singolo
    tentativo (prima pagato sempre, ora pagato una volta sola).

    Ritorna la stringa signature (da usare in approvals[0].mangopayWalletTransferApproval)
    oppure None se qualcosa fallisce (password sbagliata, script non trovato, dipendenze
    npm non installate, timeout, processo morto, ecc.) -- logga sempre il motivo."""
    global _node_process
    if 'decrypted_private_key' in _decrypted_key_cache:
        payload = {
            'decryptedPrivateKey': _decrypted_key_cache['decrypted_private_key'],
            'authorizationRequest': authorization_request,
        }
    else:
        payload = {
            'password': password,
            'encryptedPrivateKey': encrypted_private_key,
            'iv': iv,
            'salt': salt,
            'authorizationRequest': authorization_request,
        }
    line = json.dumps(payload)

    with _node_process_lock:
        try:
            proc = _ensure_node_sign_process()
            q = _node_stdout_queue
            proc.stdin.write(line + '\n')
            proc.stdin.flush()
        except Exception as e:
            log(f"[firma Node] eccezione scrivendo la richiesta al processo persistente "
                f"(lo forzo a ripartire al prossimo tentativo): {e}")
            try:
                if _node_process is not None:
                    _node_process.kill()
            except Exception:
                pass
            _node_process = None
            return None

        try:
            raw = q.get(timeout=30)
        except queue.Empty:
            log("[firma Node] timeout (30s) in attesa della risposta dal processo "
                "persistente -- lo forzo a ripartire al prossimo tentativo")
            try:
                proc.kill()
            except Exception:
                pass
            _node_process = None
            return None

        if raw is None:
            log(f"[firma Node] il processo persistente e' terminato mentre aspettavo "
                f"la risposta (ultime righe stderr: {list(_node_stderr_tail)}) -- "
                f"ripartira' al prossimo tentativo")
            _node_process = None
            return None

    try:
        output = json.loads(raw.strip())
    except json.JSONDecodeError:
        log(f"[firma Node] risposta non JSON valida: {raw!r}")
        return None
    if 'error' in output:
        log(f"[firma Node] errore riportato dallo script: {output['error']}")
        return None
    # Se lo script ha restituito la chiave decriptata (prima chiamata della sessione),
    # la mettiamo in cache per le chiamate successive.
    if output.get('decryptedPrivateKey'):
        _decrypted_key_cache['decrypted_private_key'] = output['decryptedPrivateKey']
    return output.get('signature')


FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION = """
mutation FetchEncryptedPrivateKey($input: fetchEncryptedPrivateKeyInput!) {
  fetchEncryptedPrivateKey(input: $input) {
    errors { message }
    sorarePrivateKey {
      encryptedPrivateKey
      iv
      salt
    }
  }
}
"""

# FIX 20/07 (nuovo tentativo, dopo che cache+header non hanno risolto unknown_fingerprint):
# proviamo a passare l'id completo dell'authorization (o il fingerprint) come possibile
# parametro atteso da fetchEncryptedPrivateKey -- finora chiamata sempre con input
# completamente vuoto. Se il campo non esiste nello schema, GraphQL rispondera' con un
# errore esplicito del tipo "Field 'xxx' is not defined" (stesso pattern gia' visto con
# coverageStatus), in tal caso ripieghiamo silenziosamente sulla chiamata con input vuoto
# (comportamento precedente, per non introdurre una regressione se l'ipotesi e' sbagliata).
FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION = """
mutation FetchEncryptedPrivateKey($input: fetchEncryptedPrivateKeyInput!) {
  fetchEncryptedPrivateKey(input: $input) {
    errors { message }
    sorarePrivateKey {
      encryptedPrivateKey
      iv
      salt
    }
  }
}
"""

# FIX 20/07 (scoperta chiave, confermata dal vivo su un acquisto reale completato con
# successo): il flusso REALE del browser va DIRETTAMENTE da PrepareAcceptOfferMutation
# ad AcceptOfferMutation -- fetchEncryptedPrivateKey non compare MAI nel network
# catturato durante un acquisto vero, nemmeno subito dopo aver inserito la password nel
# popup "Sblocca il tuo wallet" (0 richieste GraphQL in quel momento). La chiave e'
# quindi probabilmente decriptata/tenuta in memoria LOCALE dal browser per tutta la
# sessione, non richiesta al server ad ogni singolo acquisto. Il bot invece la
# richiamava ad ogni tentativo -- comportamento anomalo rispetto al pattern reale,
# sospettato causa di "unknown_fingerprint". Fix: cache in-memory a livello di modulo,
# la chiave viene recuperata dal server SOLO alla prima chiamata della sessione/run,
# poi riusata per tutti gli acquisti successivi.
_encrypted_key_cache = {}

# Cache separata per la chiave privata GIA' DECRIPTATA (in chiaro, esadecimale) --
# diversa da _encrypted_key_cache sopra (quella tiene encryptedPrivateKey/iv/salt
# ancora cifrati, cosi' come arrivano dal server). Popolata da sign_authorization_via_node
# dopo il primo decrypt riuscito della sessione, poi riusata per saltare PBKDF2+AES-GCM
# nelle chiamate successive (vedi commento dettagliato in sign_authorization_via_node).
_decrypted_key_cache = {}


def fetch_encrypted_private_key(authorization_id=None, fingerprint=None, offer_id=None, _call_fn=None):
    """Recupera encryptedPrivateKey/iv/salt tramite la mutation FetchEncryptedPrivateKey
    (nome/struttura CONFERMATI dal vivo il 19/07 catturando via DevTools la vera
    richiesta che il sito manda durante un'offerta reale -- NON e' una query su
    currentUser.sorarePrivateKey, quella torna sempre null). Ritorna il dict
    {encryptedPrivateKey, iv, salt} o None se fallisce per qualunque motivo.
    CACHATA in memoria (vedi nota sopra): la query GraphQL viene fatta solo la prima
    volta per l'intera esecuzione del bot, le chiamate successive riusano lo stesso
    risultato senza contattare di nuovo il server (in pratica, dato il precarico
    all'avvio, questa funzione durante lo sniping vero e proprio ritorna sempre
    dalla cache, riga sopra, senza mai eseguire il resto del corpo).
    FIX 20/07 (nona ipotesi -- body-based scartato in precedenza, schema rifiuta
    authorizationId/fingerprint/offerId come campi dell'input): proviamo stavolta a
    passare fingerprint/authorizationId come HEADER HTTP della richiesta invece che nel
    body GraphQL -- variante concettualmente diversa, mai testata finora.
    _call_fn (22/07 v6, ottimizzazione velocita'): permette di passare
    _graphql_call_via_browser_raw quando questa funzione viene chiamata da
    dentro un'altra funzione gia' sottomessa a _run_on_browser_thread (evita un
    doppio dispatch annidato/deadlock) -- default None, che equivale al
    comportamento precedente (graphql_query_via_browser, sicura da qualunque
    thread)."""
    if 'key_data' in _encrypted_key_cache:
        return _encrypted_key_cache['key_data']
    call_fn = _call_fn or graphql_query_via_browser

    extra_headers = {}
    if fingerprint:
        extra_headers['fingerprint'] = fingerprint
        extra_headers['Fingerprint'] = fingerprint
        extra_headers['x-fingerprint'] = fingerprint
    if authorization_id:
        extra_headers['authorization-id'] = authorization_id

    try:
        data = call_fn(FETCH_ENCRYPTED_PRIVATE_KEY_MUTATION, {"input": {}})
        if data.get('errors'):
            log(f"[chiave cifrata] errore GraphQL: {data['errors']}")
            log(f"[chiave cifrata] risposta grezza completa (diagnostica): {json.dumps(data)}")
            return None
        payload = (data.get('data') or {}).get('fetchEncryptedPrivateKey') or {}
        payload_errors = payload.get('errors') or []
        if payload_errors:
            log(f"[chiave cifrata] errore payload: {payload_errors}")
            log(f"[chiave cifrata] risposta grezza completa (diagnostica): {json.dumps(data)}")
            return None
        key_data = payload.get('sorarePrivateKey')
        if not key_data:
            log("[chiave cifrata] sorarePrivateKey assente nella risposta")
            return None
        log("[chiave cifrata] recuperata dal server e messa in cache per il resto della run "
            "(non verra' richiesta di nuovo finche' il bot non riparte)")
        _encrypted_key_cache['key_data'] = key_data
        return key_data
    except Exception as e:
        log(f"[chiave cifrata] eccezione: {e}")
        return None


ACCEPT_OFFER_MUTATION = """
mutation AcceptOfferMutation($input: acceptOfferInput!) {
  acceptOffer(input: $input) {
    errors { message }
  }
}
"""


def accept_offer(offer_id, fingerprint, nonce, signature, exchange_rate_id, _call_fn=None):
    """Ultimo passo del flusso di acquisto reale: completa DAVVERO l'operazione.
    Fail-safe assoluto -- qualunque errore ritorna (False, categoria, messaggio_errore),
    MAI un'eccezione non gestita, MAI un retry automatico. La categoria riusa
    classify_prepare_accept_error (stessa logica gia' usata per prepare_accept_offer:
    fondi_insufficienti/valuta_non_supportata/offerta_non_disponibile/sconosciuto) cosi'
    l'utente capisce SUBITO dal log/notifica il tipo di problema, senza dover decifrare
    il messaggio GraphQL grezzo.
    _call_fn (22/07 v6): vedi nota su fetch_encrypted_private_key -- passare
    _graphql_call_via_browser_raw quando gia' dentro un dispatch a
    _run_on_browser_thread."""
    call_fn = _call_fn or graphql_query_via_browser
    variables = {
        "input": {
            "offerId": offer_id,
            "migrationData": None,
            "approvals": [{
                "fingerprint": fingerprint,
                "mangopayWalletTransferApproval": {
                    "nonce": nonce,
                    "signature": signature,
                },
            }],
            "settlementInfo": {
                "currency": "EUR",
                "exchangeRateId": exchange_rate_id,
                "paymentMethod": "WALLET",
                "platform": "WEB",
                "useAvailableCredits": False,
            },
        },
    }
    try:
        data = call_fn(ACCEPT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('acceptOffer') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_prepare_accept_error(root_errors, payload_errors)
            log(f"[accept offer] fallita, categoria='{category}', errori={all_errors}")
            return False, category, str(all_errors)
        # FIX 20/07: il campo 'offer' non esiste piu' nello schema acceptOfferPayload
        # (errore "Field 'offer' doesn't exist" osservato dal vivo) -- probabilmente
        # Sorare ha cambiato la struttura del payload di risposta. Senza introspection
        # disponibile (disabilitata su Sorare) non possiamo vedere il nome esatto del
        # campo sostitutivo -- determiniamo il successo SOLO dall'assenza di errori
        # (root_errors/payload_errors), gia' verificata sopra.
        log("[accept offer] successo (nessun errore restituito dal server)")
        return True, None, None
    except Exception as e:
        log(f"[accept offer] eccezione: {e}")
        return False, 'eccezione', str(e)


def execute_live_purchase(offer_id, prepared, _call_fn=None):
    """Orchestrazione FASE 2 completa (automazione totale, attiva SOLO se
    AUTOBUY_LIVE_MODE e' 'si'): chiave cifrata -> firma -> accept. Fail-safe assoluto:
    ritorna (True, None) se l'acquisto e' andato a buon fine, (False, motivo_esatto)
    altrimenti -- MAI retry, MAI tentativi alternativi, un solo tentativo secco. Ogni
    step logga il proprio esito (successo o fallimento) per poter capire SUBITO dai log
    quale step specifico e' fallito, senza dover dedurlo dal messaggio finale.
    IMPORTANTE (20/07): fetch_encrypted_private_key() va chiamata SOLO ora, DOPO che
    prepare_accept_offer() e' gia' stata completata con successo (vedi nota in
    evaluate_event) -- un tentativo di parallelizzare le due chiamate ha causato
    "unknown_fingerprint" in 3 test su 3 dal vivo, il fingerprint deve esistere
    lato server prima che questa chiamata possa risolversi.
    _call_fn (22/07 v6, ottimizzazione velocita'): se valorizzato (con
    _graphql_call_via_browser_raw), indica che questa funzione gira gia' dentro
    un dispatch a _run_on_browser_thread (fusa con prepare_accept_offer in un
    solo hop, vedi _run_autobuy_merged) -- viene passato a sua volta a
    fetch_encrypted_private_key/accept_offer per evitare un doppio dispatch
    annidato. sign_authorization_via_node NON e' toccata: usa il proprio canale
    IPC verso il processo Node, gia' thread-safe (protetto da _node_process_lock)
    indipendentemente da quale thread la chiami."""
    log(f"[acquisto live] avvio -- offer_id={offer_id}")

    if not SORARE_WALLET_PASSWORD:
        log("[acquisto live] STOP: SORARE_WALLET_PASSWORD non impostata")
        return False, "SORARE_WALLET_PASSWORD non impostata"

    fingerprint = prepared.get('fingerprint')
    request = prepared.get('request') or {}
    nonce = request.get('nonce')
    authorization_id = prepared.get('authorization_id')

    # 23/07: timing granulare per capire dove va il tempo dentro esecuzione_finale
    # (fetch_key/firma_node/accept separati) -- nessuna logica toccata, solo misure.
    _t0 = time.monotonic()
    key_data = fetch_encrypted_private_key(
        authorization_id=authorization_id, fingerprint=fingerprint, offer_id=offer_id,
        _call_fn=_call_fn)
    _t_fetch_key = time.monotonic() - _t0
    if not key_data:
        log("[acquisto live] STOP: chiave cifrata non recuperata (vedi log [chiave cifrata] sopra)")
        return False, "impossibile recuperare la chiave cifrata (fetchEncryptedPrivateKey)"
    log(f"[acquisto live] step 1/3 OK: chiave cifrata recuperata (fetch_key={_t_fetch_key:.3f}s)")

    _t1 = time.monotonic()
    signature = sign_authorization_via_node(
        SORARE_WALLET_PASSWORD,
        key_data.get('encryptedPrivateKey'),
        key_data.get('iv'),
        key_data.get('salt'),
        request,
    )
    _t_firma = time.monotonic() - _t1
    if not signature:
        log("[acquisto live] STOP: firma fallita (vedi log [firma Node] sopra per il dettaglio esatto)")
        return False, "firma fallita (vedi log [firma Node] per il dettaglio esatto)"
    log(f"[acquisto live] step 2/3 OK: firma generata (firma_node={_t_firma:.3f}s)")

    # FIX 19/07 (velocizzazione sniping): riusiamo l'exchange_rate_id gia' ottenuto da
    # prepare_accept_offer invece di rifare la stessa query GraphQL una seconda volta --
    # una chiamata di rete in meno nel percorso critico dell'acquisto.
    exchange_rate_id = prepared.get('exchange_rate_id')
    if not exchange_rate_id:
        log("[acquisto live] STOP: exchange_rate_id non disponibile da prepared")
        return False, "exchange_rate_id non disponibile"

    _t2 = time.monotonic()
    success, category, error = accept_offer(offer_id, fingerprint, nonce, signature,
                                             exchange_rate_id, _call_fn=_call_fn)
    _t_accept = time.monotonic() - _t2
    if not success:
        log(f"[acquisto live] STOP: step 3/3 fallito, categoria='{category}' (accept={_t_accept:.3f}s)")
        return False, f"AcceptOfferMutation fallita [{category}]: {error}"
    log(f"[acquisto live] step 3/3 OK: acquisto completato "
        f"(fetch_key={_t_fetch_key:.3f}s, firma_node={_t_firma:.3f}s, accept={_t_accept:.3f}s)")
    return True, None


PREPARE_OFFER_MUTATION = """
mutation PrepareOfferMutation($input: prepareOfferInput!) {
  prepareOffer(input: $input) {
    authorizations {
      fingerprint
      id
      request {
        ... on MangopayWalletTransferAuthorizationRequest {
          currency
          amount
          mangopayWalletId
          nonce
          operationHash
        }
      }
    }
    errors { message }
  }
}
"""


def prepare_offer(card_asset_id, receiver_slug, offer_amount_eur, _call_fn=None):
    """Prenota/valida la creazione di un'offerta diretta lato server -- mutation
    confermata dal vivo (19/07, catturata via DevTools mentre l'utente faceva un'offerta
    reale su una carta di test). NON invia ancora l'offerta: restituisce
    {fingerprint, request, exchange_rate_id} da usare per firmare e poi chiamare
    create_direct_offer. card_asset_id e' l'assetId ESADECIMALE della carta (campo
    'assetId' della carta, es. "0x0400...", NON lo slug) -- confermato nel payload reale
    catturato (receiveAssetIds contiene l'assetId, non lo slug).
    _call_fn (22/07 v6, ottimizzazione velocita'): vedi nota su fetch_encrypted_private_key
    -- passare _graphql_call_via_browser_raw quando gia' dentro un dispatch a
    _run_on_browser_thread, per fondere piu' chiamate in un solo hop."""
    call_fn = _call_fn or graphql_query_via_browser
    exchange_rate_id = get_exchange_rate_id()
    if not exchange_rate_id:
        log("[prepare offer] exchange_rate_id non ottenuto, impossibile procedere")
        return None
    # FIX BUG CRITICO (20/07): confermato dal vivo che il campo 'amount' restituito
    # dal server dentro l'authorization request (quello REALMENTE firmato ed
    # eseguito, vedi execute_live_offer) e' in CENTESIMI interi, non in euro con
    # decimali. Mandando "6.0" EUR il server rispondeva amount=6 (troncando i
    # decimali), e quell'intero veniva poi eseguito come 6 CENTESIMI = 0.06EUR
    # (caso reale Alex Roldan, offerta 6.00EUR eseguita a 0.06EUR, poi annullata
    # manualmente dall'utente). Ora inviamo l'importo gia' in centesimi interi.
    amount_cents = int(round(offer_amount_eur * 100))
    variables = {
        "input": {
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(amount_cents), "currency": "EUR"},
            "receiveAmount": {"amount": "0", "currency": "EUR"},
            "settlementCurrencies": ["EUR"],
        }
    }
    try:
        data = call_fn(PREPARE_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('prepareOffer') or {}
        payload_errors = payload.get('errors') or []

        if root_errors or payload_errors:
            category, all_errors = classify_prepare_offer_error(root_errors, payload_errors)
            log(f"[prepare offer] fallita, categoria='{category}', errori={all_errors}")
            return None

        auths = payload.get('authorizations') or []
        if not auths:
            log("[prepare offer] nessuna authorization restituita")
            return None
        auth = auths[0]
        request = dict(auth.get('request') or {})
        request['__typename'] = 'MangopayWalletTransferAuthorizationRequest'
        # FIX 21/07 (sospetta causa di 'invalid Mangopay wallet transfer signature'):
        # in precedenza qui si sovrascriveva 'amount' col valore lordo (amount_cents)
        # quando il server ne restituiva uno diverso (es. 152 invece di 160, probabile
        # netto post-fee 5% venditore) -- ma il server verifica la firma contro IL SUO
        # 'amount' originale, non contro un valore che gli rimandiamo indietro
        # modificato. Sovrascriverlo rompeva la firma. L'importo che l'utente paga
        # resta comunque quello giusto: e' gia' fissato da sendAmount/amount_cents
        # inviato SOPRA nella richiesta PrepareOfferMutation (il buyer paga sempre
        # l'importo dichiarato, il venditore incassa il 95% -- confermato
        # dall'utente). Qui firmiamo l'amount ESATTO restituito dal server, senza
        # toccarlo, cosi' la firma corrisponde a quello che lui stesso verifica.
        server_amount = request.get('amount')
        if server_amount is not None and int(server_amount) != amount_cents:
            log(f"[prepare offer] diagnostica: amount del server ({server_amount}) "
                f"diverso dal lordo inviato ({amount_cents}) -- probabile netto "
                f"post-fee 5% venditore. NON lo sovrascrivo piu', firmo il valore "
                f"esatto del server (fix 21/07 per invalid signature).")
        return {'fingerprint': auth.get('fingerprint'), 'request': request,
                'exchange_rate_id': exchange_rate_id}
    except Exception as e:
        log(f"[prepare offer] eccezione: {e}")
        return None



CREATE_DIRECT_OFFER_MUTATION = """
mutation CreateDirectOfferMutation($input: createDirectOfferInput!) {
  createDirectOffer(input: $input) {
    errors { message }
    tokenOffer {
      id
      senderSide {
        amounts { eurCents }
      }
    }
  }
}
"""


import uuid


def generate_deal_id():
    """dealId CONFERMATO (20/07, verifica dal vivo) essere un UUID v4 generato
    CLIENT-SIDE (dal browser), NON restituito da PrepareOfferMutation (verificato che
    la risposta contiene solo authorizations+errors, mai un dealId). Lunghezza del
    dealId reale osservato (39 cifre decimali) coincide esattamente con un UUID v4
    convertito in intero. Lo stesso valore generato qui va riusato IDENTICO sia nella
    prepare (se mai richiesto in futuro) sia nella create_direct_offer finale."""
    return str(uuid.uuid4().int)


def create_direct_offer(card_asset_id, receiver_slug, offer_amount_eur, fingerprint, nonce, signature,
                         deal_id, _call_fn=None):
    """Ultimo passo: invia DAVVERO l'offerta diretta al venditore -- mutation confermata
    dal vivo (19/07, caso reale David Alaba/satonio, offerta di test inviata con
    successo). Fail-safe assoluto: qualunque errore ritorna (False, categoria, msg), MAI
    un'eccezione non gestita, MAI un retry automatico.
    _call_fn (22/07 v6): vedi nota su fetch_encrypted_private_key -- passare
    _graphql_call_via_browser_raw quando gia' dentro un dispatch a
    _run_on_browser_thread."""
    call_fn = _call_fn or graphql_query_via_browser
    # FIX BUG CRITICO (20/07): stesso fix di prepare_offer, per coerenza -- vedi
    # commento dettagliato li'. sendAmount va in centesimi interi.
    amount_cents = int(round(offer_amount_eur * 100))
    variables = {
        "input": {
            "dealId": deal_id,
            "sendAssetIds": [],
            "receiveAssetIds": [card_asset_id],
            "receiverSlug": receiver_slug,
            "sendAmount": {"amount": str(amount_cents), "currency": "EUR"},
            "duration": OFFER_DURATION_SECONDS,
            "migrationData": None,
            "approvals": [{
                "fingerprint": fingerprint,
                "mangopayWalletTransferApproval": {
                    "nonce": nonce,
                    "signature": signature,
                },
            }],
        }
    }
    try:
        data = call_fn(CREATE_DIRECT_OFFER_MUTATION, variables)
        root_errors = data.get('errors')
        payload = (data.get('data') or {}).get('createDirectOffer') or {}
        payload_errors = payload.get('errors') or []
        if root_errors or payload_errors:
            category, all_errors = classify_prepare_offer_error(root_errors, payload_errors)
            log(f"[create offer] fallita, categoria='{category}', errori={all_errors}")
            return False, category, str(all_errors)
        token_offer = payload.get('tokenOffer')
        if not token_offer:
            # FIX 20/07 (prudenza, stesso pattern gia' visto su acceptOffer -- il
            # campo 'offer' e' scomparso dallo schema di acceptOfferPayload, quindi e'
            # plausibile che anche 'tokenOffer' possa mancare qui senza che sia un
            # vero fallimento): se NON ci sono errori, trattiamo comunque come
            # successo, solo con un log di avviso.
            log(f"[create offer] risposta senza 'tokenOffer' ma NESSUN errore -- "
                f"probabile successo (schema Sorare potrebbe non restituire piu' "
                f"questo campo, vedi caso analogo 'offer' in acceptOffer): "
                f"{json.dumps(data)[:500]}")
            return True, None, None
        log(f"[create offer] successo, offer id={token_offer.get('id')}")
        return True, None, None
    except Exception as e:
        log(f"[create offer] eccezione: {e}")
        return False, 'eccezione', str(e)


def execute_live_offer(card_asset_id, receiver_slug, offer_amount_eur, prepared, _call_fn=None):
    """Orchestrazione completa (attiva SOLO se MAKEOFFER_LIVE_MODE e' 'si'): chiave
    cifrata -> firma -> create_direct_offer. Fail-safe assoluto: MAI retry, un solo
    tentativo secco. Logga ogni step con OK/STOP esplicito.
    _call_fn (22/07 v6, ottimizzazione velocita'): se valorizzato (con
    _graphql_call_via_browser_raw), indica che questa funzione gira gia' dentro
    un dispatch a _run_on_browser_thread (fusa con prepare_offer in un solo
    hop, vedi _run_makeoffer_merged) -- passato a fetch_encrypted_private_key/
    create_direct_offer per evitare un doppio dispatch annidato."""
    log(f"[offerta live] avvio -- carta={card_asset_id}, venditore={receiver_slug}, "
        f"offerta={offer_amount_eur:.2f}EUR")

    if not SORARE_WALLET_PASSWORD:
        log("[offerta live] STOP: SORARE_WALLET_PASSWORD non impostata")
        return False, "SORARE_WALLET_PASSWORD non impostata"

    key_data = fetch_encrypted_private_key(_call_fn=_call_fn)
    if not key_data:
        log("[offerta live] STOP: chiave cifrata non recuperata (vedi log [chiave cifrata] sopra)")
        return False, "impossibile recuperare la chiave cifrata (fetchEncryptedPrivateKey)"
    log("[offerta live] step 1/3 OK: chiave cifrata recuperata")

    fingerprint = prepared.get('fingerprint')
    request = prepared.get('request') or {}
    nonce = request.get('nonce')

    signature = sign_authorization_via_node(
        SORARE_WALLET_PASSWORD,
        key_data.get('encryptedPrivateKey'),
        key_data.get('iv'),
        key_data.get('salt'),
        request,
    )
    if not signature:
        log("[offerta live] STOP: firma fallita (vedi log [firma Node] sopra per il dettaglio esatto)")
        return False, "firma fallita (vedi log [firma Node] per il dettaglio esatto)"
    log("[offerta live] step 2/3 OK: firma generata")

    deal_id = generate_deal_id()
    success, category, error = create_direct_offer(
        card_asset_id, receiver_slug, offer_amount_eur, fingerprint, nonce, signature, deal_id,
        _call_fn=_call_fn)
    if not success:
        log(f"[offerta live] STOP: step 3/3 fallito, categoria='{category}'")
        return False, f"CreateDirectOfferMutation fallita [{category}]: {error}"
    log("[offerta live] step 3/3 OK: offerta inviata")
    return True, None

CARD_OFFER_DETAILS_QUERY = """
query CardOfferDetailsQuery($slug: String!) {
  anyCard(slug: $slug) {
    slug
    assetId
    liveSingleBuyOffers {
      id
      sender { ... on User { slug } }
    }
    liveSingleSaleOffer {
      settlementCurrencies
    }
  }
}
"""


def get_card_offer_details(card_slug):
    """Recupera assetId (necessario per creare l'offerta), le eventuali offerte
    pendenti gia' presenti su questa carta (liveSingleBuyOffers, per lo skip "gia' ho
    un'offerta pendente" richiesto esplicitamente dall'utente), e le valute accettate
    dal venditore (settlementCurrencies, per lo skip "se non accetta EUR" richiesto
    esplicitamente). Fail-safe: se la query fallisce, ritorna None e il chiamante deve
    SALTARE il caso (senza assetId non si puo' fare l'offerta comunque)."""
    try:
        data = graphql_query(CARD_OFFER_DETAILS_QUERY, {"slug": card_slug})
        if data.get('errors'):
            log(f"[dettagli carta] errore per {card_slug}: {data['errors']}")
            return None
        card = (data.get('data') or {}).get('anyCard')
        if not card:
            return None
        return card
    except Exception as e:
        log(f"[dettagli carta] eccezione per {card_slug}: {e}")
        return None

def send_autobuy_alert(player_name, player_slug, price_eur, second_price, margin_percent,
                        card_slug, excluded_league, prepared=None, is_in_season=True,
                        live_mode=False, purchase_completed=False, purchase_error=None):
    link = build_card_link(player_slug, card_slug)
    if not is_in_season:
        categoria = "CLASSIC (modalita' check_classic, confronto su tutti i campionati)"
    else:
        categoria = "In Season" if excluded_league else "In Season + Classic (confronto unito)"
    prenotazione = (
        "\u2705 Offerta prenotata lato server (piu' veloce da confermare)\n"
        if prepared else
        "\u26A0\uFE0F Prenotazione lato server non riuscita, apri e conferma normalmente\n"
    )
    if live_mode:
        if purchase_completed:
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- ACQUISTATO IN AUTOMATICO</b>"
            esito = "\u2705 <b>Acquisto completato con successo, nessuna azione richiesta.</b>\n\n"
        else:
            titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- ACQUISTO AUTOMATICO FALLITO</b>"
            esito = (f"\u274C <b>Acquisto automatico NON riuscito</b>: {purchase_error}\n"
                      f"Apri e valuta se confermare a mano.\n\n")
    else:
        titolo = "\U0001F916\U0001F4B0 <b>Bot Supremo (AutoBuy) -- LO AVREI ACQUISTATO</b>"
        esito = "\u26A0\uFE0F Fase di test: nessun acquisto reale eseguito, controlla a mano.\n\n"
    msg_text = (
        f"{titolo}\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: {categoria}\n"
        f"Prezzo minimo attuale: {price_eur:.2f}EUR\n"
        f"Secondo prezzo attuale: {second_price:.2f}EUR (margine {margin_percent:.1%}, "
        f"soglia richiesta {AUTOBUY_MARGIN_FRACTION:.0%})\n\n"
        f"{prenotazione}"
        f"{esito}"
        f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
    )
    send_telegram_msg(msg_text)


def send_makeoffer_alert(player_name, player_slug, price_eur, second_price, margin_percent,
                          card_slug, excluded_league, prepared=None, is_in_season=True,
                          live_mode=False, purchase_completed=False, purchase_error=None,
                          offer_amount_eur=None, via_periodic_bid=False):
    link = build_card_link(player_slug, card_slug)
    if not is_in_season:
        categoria = "CLASSIC (modalita' check_classic, confronto su tutti i campionati)"
    else:
        categoria = "In Season" if excluded_league else "In Season + Classic (confronto unito)"
    prenotazione = (
        "\u2705 Offerta prenotata lato server (piu' veloce da confermare)\n"
        if prepared else
        "\u26A0\uFE0F Prenotazione lato server non riuscita, apri e conferma normalmente\n"
    )
    offer_line = f"Offerta calcolata: {offer_amount_eur:.2f}EUR\n" if offer_amount_eur is not None else ""
    tag_periodico = " [Bid periodico]" if via_periodic_bid else ""
    if live_mode:
        if purchase_completed:
            titolo = f"\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer){tag_periodico} -- OFFERTA INVIATA IN AUTOMATICO</b>"
            esito = "\u2705 <b>Offerta inviata con successo, in attesa che il venditore risponda.</b>\n\n"
        else:
            titolo = f"\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer){tag_periodico} -- OFFERTA AUTOMATICA FALLITA</b>"
            esito = (f"\u274C <b>Offerta automatica NON inviata</b>: {purchase_error}\n"
                      f"Apri e valuta se fare l'offerta a mano.\n\n")
    else:
        titolo = f"\U0001F916\U0001F4B0 <b>Bot Supremo (MakeOffer){tag_periodico} -- FAREI UN'OFFERTA</b>"
        esito = "\u26A0\uFE0F Fase di test: nessuna offerta reale inviata, controlla a mano.\n\n"
    msg_text = (
        f"{titolo}\n\n"
        f"Giocatore: {player_name}\n"
        f"Categoria: {categoria}\n"
        f"Prezzo minimo attuale: {price_eur:.2f}EUR\n"
        f"Secondo prezzo attuale: {second_price:.2f}EUR (margine {margin_percent:.1%}, "
        f"soglia richiesta {MAKEOFFER_MARGIN_FRACTION:.0%})\n"
        f"{offer_line}\n"
        f"{prenotazione}"
        f"{esito}"
        f"\U0001F449 <b><a href='{link}'>APRI SU SORARE</a></b> \U0001F448"
    )
    send_telegram_msg(msg_text)


def _is_insufficient_funds_error(error_message):
    """Rileva se un messaggio di errore (gia' formattato da execute_live_purchase/
    execute_live_offer, es. 'AcceptOfferMutation fallita [fondi_insufficienti]: ...')
    indica fondi insufficienti -- la categoria e' gia' classificata a monte da
    classify_prepare_accept_error/classify_prepare_offer_error, qui controlliamo solo
    che compaia nel messaggio finale."""
    if not error_message:
        return False
    return '[fondi_insufficienti]' in error_message


def _is_invalid_signature_error(error_message):
    """Rileva se un messaggio di errore indica una firma non valida ('invalid Mangopay
    wallet transfer signature') -- errore visto dal vivo il 20/07 solo nel ramo
    MakeOffer, causa non ancora confermata. Serve per attivare la diagnostica dedicata
    in send_invalid_signature_diagnostic_alert (vedi sotto)."""
    if not error_message:
        return False
    return 'invalid mangopay wallet transfer signature' in error_message.lower()


def send_invalid_signature_diagnostic_alert(player_name, seller_slug, offer_amount_eur):
    """Notifica diagnostica DEDICATA (20/07, richiesta esplicita utente) per il caso
    'invalid Mangopay wallet transfer signature' nel ramo MakeOffer -- NON confermiamo
    la causa (e' solo un'ipotesi dell'utente, non un fatto accertato): potrebbe essere
    che il venditore/manager abbia bloccato il nostro account dalle offerte dirette
    (Sorare lo permette, pur consentendo la vendita diretta allo stesso account), oppure
    un problema di firma/cache lato bot. La notifica elenca il fatto osservato (verso
    quale manager e' fallita) senza affermare la causa, cosi' l'utente puo' verificare
    manualmente se accumula ripetutamente sullo stesso manager (indizio di blocco)."""
    send_telegram_msg(
        f"\U0001F50D <b>Bot Supremo -- DIAGNOSTICA: firma non valida (MakeOffer)</b>\n\n"
        f"Giocatore: {player_name}\n"
        f"Venditore/manager: {seller_slug}\n"
        f"Offerta tentata: {offer_amount_eur:.2f}EUR\n\n"
        f"Causa non confermata -- possibili ipotesi: questo manager potrebbe averti "
        f"bloccato dalle offerte dirette (Sorare lo permette anche se accetta la "
        f"vendita diretta allo stesso account), oppure un problema di firma/cache. "
        f"Se questo errore si ripete SEMPRE con lo stesso manager, e' un indizio "
        f"a favore dell'ipotesi del blocco."
    )


def send_insufficient_funds_alert(player_name, ramo):
    send_telegram_msg(
        f"\U0001F6D1 <b>Bot Supremo -- FONDI INSUFFICIENTI, ESECUZIONE FERMATA</b>\n\n"
        f"Rilevato durante il tentativo su {player_name} (ramo {ramo}).\n"
        f"Il bot si e' fermato subito invece di continuare a tentare a vuoto -- "
        f"ricarica il wallet prima di rilanciare."
    )


def send_startup_msg():
    classic_msg = "\nModalita' CLASSIC attiva (tutti i campionati)" if CHECK_CLASSIC else ""
    autobuy_stato = "ATTIVO" if AUTOBUY_LIVE_MODE else "solo diagnostica"
    makeoffer_stato = "ATTIVO" if MAKEOFFER_LIVE_MODE else "solo diagnostica"
    send_telegram_msg(
        f"\U0001F916 <b>Bot Supremo avviato</b>\n"
        f"AutoBuy: margine >= {AUTOBUY_MARGIN_FRACTION:.0%} ({autobuy_stato})\n"
        f"MakeOffer: margine {MAKEOFFER_MARGIN_FRACTION:.0%}-{MAKEOFFER_MAX_MARGIN_FRACTION:.0%} ({makeoffer_stato})\n"
        f"Fascia prezzo: {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR\n"
        f"Ascolto per {LISTEN_SECONDS}s o fino a {AUTOBUY_TARGET_MATCHES} casi trovati.{classic_msg}"
    )


def send_end_msg(matches_found, target_reached):
    esito = (
        f"\u2705 Target raggiunto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
        if target_reached else
        f"\u23F1 Tempo scaduto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati"
    )
    send_telegram_msg(
        f"\U0001F916 <b>Bot Supremo terminato</b>\n"
        f"{esito}"
    )


# NOTA 22/07 v4: _parallel_liquidity_and_last_price (due thread paralleli) e'
# stata RIMOSSA -- superata dalla fusione delle due query in una sola
# (get_liquidity_and_last_price), che fa un solo fetch di rete invece di due
# (nemmeno piu' bisogno del parallelismo, dato che non c'e' piu' una seconda
# query da parallelizzare).


def evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate, league_slug=None,
                    offer_id=None, seller_slug=None, is_in_season=True):
    """Valutazione UNICA condivisa (un solo scan di mercato per evento, niente doppio
    lavoro tra i due bot separati). Dopo il calcolo del margine, biforca:
    - margine >= AUTOBUY_MARGIN_FRACTION -> ramo AutoBuy (accetta offerta esistente)
    - MAKEOFFER_MARGIN_FRACTION <= margine < AUTOBUY_MARGIN_FRACTION (tetto MakeOffer
      MAKEOFFER_MAX_MARGIN_FRACTION incluso in questo range per costruzione) -> ramo
      MakeOffer (crea offerta scontata)
    Ritorna True se questo evento ha portato a un caso valido (di QUALSIASI ramo),
    False altrimenti -- usato dal listener per decidere se fermarsi."""
    _t0 = time.monotonic()
    if INSUFFICIENT_FUNDS_STOP[0]:
        return False  # bot gia' fermato per fondi insufficienti, non valutare altro

    if player_slug and player_slug.lower() in BLACKLISTED_PLAYER_SLUGS:
        log(f"{player_name}: scarto -- giocatore in blacklist manuale ({player_slug})")
        return False

    if player_slug and is_player_in_forma_bassa(player_slug.lower()):
        log(f"{player_name}: scarto -- in 'forma bassa ultime 5' (media SO5 sotto soglia, "
            f"registrata in precedenza)")
        return False

    # FIX 21/07 (richiesta esplicita utente): filtro campionato, controllato IL PIU'
    # PRESTO POSSIBILE (subito dopo i check istantanei in RAM, prima di qualunque I/O
    # su file/rete) per risparmiare secondi preziosi su carte che verranno comunque
    # ignorate -- niente query di liquidita', niente fetch prezzi, niente altro lavoro
    # sprecato su un campionato che non vogliamo toccare.
    if league_slug and league_slug.lower() in BLACKLISTED_LEAGUE_SLUGS:
        if LEAGUE_BLACKLIST_VERBOSE_LOG:
            log(f"{player_name}: scarto -- campionato blacklistato ({league_slug})")
        return False

    if player_slug and is_player_in_cooldown(player_slug, is_in_season):
        log(f"{player_name}: scarto -- gia' acquistato/offerto ({'in_season' if is_in_season else 'classic'}) "
            f"nelle ultime {PLAYER_COOLDOWN_HOURS}h (protezione anti-svendita/infortunio)")
        return False

    if not (AUTOBUY_MIN_PRICE_EUR <= price_eur <= AUTOBUY_MAX_PRICE_EUR):
        return False

    # OTTIMIZZAZIONE VELOCITA' (22/07, richiesta esplicita utente -- "ogni millisecondo
    # e' importante nello sniping"): il controllo di liquidita' (cache thin_market +
    # query di rete get_liquidity_and_last_price) e' stato SPOSTATO piu' in basso, DOPO
    # il calcolo del margine, invece di stare qui subito dopo il filtro prezzo. Motivo:
    # la query di liquidita' e' la piu' costosa del percorso (fino a 6 round-trip
    # GraphQL paginati) ed era pagata SEMPRE, anche per carte che poi risultavano
    # scartate per margine insufficiente (la maggioranza dei casi nei log reali) --
    # lavoro di rete sprecato. Ora si paga solo per candidati che sono gia' un affare
    # sulla carta (margine sufficiente), zero costo aggiuntivo sui veri affari (la
    # query serve comunque prima di procedere), risparmio netto sui casi scartati.
    # La cache thin_market (istantanea, RAM/file) resta comunque a costo quasi zero
    # ovunque si trovi nell'ordine -- il vero risparmio e' sulla query di rete.

    if is_in_season:
        prices, excluded_league = get_in_season_prices(player_slug, eth_rate, league_slug)
        if AUTOBUY_DIAGNOSTIC:
            modalita = "SOLO in_season (lega esclusa)" if excluded_league else "in_season + classic uniti"
            log(f"[diagnostica lega] {player_name}: league_slug={league_slug!r} -> {modalita}, "
                f"{len(prices)} annunci totali nel confronto")
    else:
        buckets = get_bucket_prices(player_slug, eth_rate)
        prices = buckets['in_season'] + buckets['classic']
        prices.sort(key=lambda p: p[0])
        excluded_league = False
        if AUTOBUY_DIAGNOSTIC:
            log(f"[check classic] {player_name}: {len(prices)} annunci totali "
                f"(in_season {len(buckets['in_season'])} + classic {len(buckets['classic'])})")
    if not prices:
        return False
    _t_scan_prezzi = time.monotonic()

    true_min_price, true_min_card_slug, true_min_seller_slug = prices[0]

    # NUOVO 22/07 (richiesta esplicita utente -- "trigger su minimo non allineato"):
    # quando l'annuncio triggerante NON e' il minimo assoluto di mercato, invece di
    # scartare subito il caso proviamo comunque il minimo assoluto come bersaglio di
    # un'offerta (ramo MakeOffer soltanto, MAI AutoBuy) -- il minimo era gia' sul
    # mercato ed e' probabile che sia gia' stato preso da qualcun altro, ma tentare
    # un'offerta scontata su di esso non costa nulla in piu' (stesso identico
    # calcolo/lista prices gia' fatto sopra, zero query extra). Il flag qui sotto
    # viene riusato piu' avanti per: (a) impedire al router di instradare questo
    # caso verso AutoBuy anche se il margine risultasse sufficiente, (b) loggare in
    # modo dedicato quando MIN_NON_TRIGGER_LOG e' attivo.
    trigger_su_minimo_non_allineato = False
    if true_min_card_slug != card_slug:
        if price_eur < true_min_price:
            log(f"{player_name}: minimo query non aggiornato ({true_min_price:.2f}EUR), "
                f"ma evento a {price_eur:.2f}EUR e' piu' basso -- procedo con l'evento")
            true_min_price, true_min_card_slug, true_min_seller_slug = price_eur, card_slug, seller_slug
            prices = [(price_eur, card_slug, seller_slug)] + [p for p in prices if p[1] != card_slug]
        else:
            categoria = "in_season" if excluded_league else "in_season/classic"
            if not (AUTOBUY_MIN_PRICE_EUR <= true_min_price <= AUTOBUY_MAX_PRICE_EUR):
                log(f"{player_name}: scarto -- il vero minimo ({true_min_price:.2f}EUR, carta "
                    f"{true_min_card_slug}) e' fuori dal range prezzo consentito "
                    f"({AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR), 'trigger su "
                    f"minimo non allineato' non si applica")
                return False
            trigger_su_minimo_non_allineato = True
            if MIN_NON_TRIGGER_LOG:
                log(f"[trigger su minimo non allineato] {player_name}: annuncio a "
                    f"{price_eur:.2f}EUR ({categoria}) non e' il minimo attuale -- provo "
                    f"comunque il minimo vero ({true_min_price:.2f}EUR, carta "
                    f"{true_min_card_slug}) come bersaglio di un'offerta (solo ramo "
                    f"MakeOffer, mai AutoBuy)")

    if true_min_seller_slug in BLACKLISTED_SELLER_SLUGS or \
            true_min_seller_slug in BLACKLISTED_MANAGER_SLUGS:
        log(f"{player_name}: scarto -- il minimo attuale ({true_min_price:.2f}EUR) e' di un "
            f"venditore blacklistato ({true_min_seller_slug}), non acquistabile")
        return False

    if len(prices) < MIN_LISTED_CARDS_FOR_PURCHASE:
        log(f"{player_name}: scarto -- solo {len(prices)} carta/e in vendita (minimo richiesto "
            f"{MIN_LISTED_CARDS_FOR_PURCHASE}), mercato poco popolato")
        return False
    if MIN_LISTED_CARDS_DIAGNOSTIC:
        log(f"[diagnostica carte in vendita] {player_name}: {len(prices)} carte in vendita "
            f"(soglia {MIN_LISTED_CARDS_FOR_PURCHASE}), controllo superato")

    second_min_price, _, _ = prices[1]
    if second_min_price <= 0:
        return False

    margin_percent = (second_min_price - true_min_price) / second_min_price
    log(f"{player_name}: minimo {true_min_price:.2f}EUR, secondo {second_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%} (soglie MakeOffer {MAKEOFFER_MARGIN_FRACTION:.0%}-"
        f"{MAKEOFFER_MAX_MARGIN_FRACTION:.0%}, AutoBuy >= {AUTOBUY_MARGIN_FRACTION:.0%})")

    if margin_percent < MAKEOFFER_MARGIN_FRACTION:
        # BID PERIODICO (22/07, richiesta esplicita utente): prima di scartare per
        # margine insufficiente, se la carta e' nella fascia 2-30EUR fissa del
        # meccanismo periodico, la confrontiamo col candidato gia' tracciato per il
        # ciclo di 2 minuti corrente -- se e' PIU' VICINA alla soglia MakeOffer
        # (margine piu' alto, anche restando sotto), diventa la nuova "migliore del
        # periodo". Zero query extra: riusa margin_percent/true_min_price gia'
        # calcolati qui sopra. Il candidato tracciato viene poi verificato DA CAPO
        # (liquidita', cooldown, offerte pendenti, ecc.) dal thread del timer prima
        # di offrire -- questo e' solo il tracciamento, nessuna offerta parte da qui.
        if (PERIODIC_BID_ENABLED and player_slug
                and PERIODIC_BID_MIN_PRICE_EUR <= true_min_price <= PERIODIC_BID_MAX_PRICE_EUR):
            global _periodic_bid_best
            with _periodic_bid_lock:
                gia_migliore = (_periodic_bid_best is not None
                                 and _periodic_bid_best['margin_percent'] >= margin_percent)
                if not gia_migliore:
                    _periodic_bid_best = {
                        'player_slug': player_slug,
                        'player_name': player_name,
                        'card_slug': true_min_card_slug,
                        'seller_slug': true_min_seller_slug,
                        'true_min_price': true_min_price,
                        'margin_percent': margin_percent,
                        'is_in_season': is_in_season,
                        'league_slug': league_slug,
                        'excluded_league': excluded_league,
                    }
        return False  # margine insufficiente per qualunque ramo -- niente query liquidita' sprecata

    # Controllo liquidita' (thin_market cache + query di rete) spostato QUI: solo ora
    # sappiamo che la carta e' gia' un affare sulla carta, quindi vale la pena del
    # costo della verifica -- vedi nota sopra sul filtro prezzo per il razionale.
    if player_slug and is_player_in_thin_market_cache(player_slug, is_in_season):
        log(f"{player_name}: scarto -- gia' segnalato come mercato troppo sottile nelle "
            f"ultime {THIN_MARKET_SKIP_HOURS:.0f}h, salto la riverifica")
        return False

    # OTTIMIZZAZIONE VELOCITA' 23/07 (richiesta esplicita utente -- casi Edier Ocampo/
    # Alex Roldan persi a prepare_accept_offer per "Too late"): se questo evento
    # portera' comunque al ramo AutoBuy (margine gia' sufficiente, non e' un caso
    # "trigger su minimo non allineato" che e' sempre MakeOffer), lanciamo
    # prepare_accept_offer ORA, in parallelo alla query di liquidita' che segue,
    # invece di aspettare che liquidita' finisca prima di partire. Nessun controllo
    # rimosso: se liquidita' (o i controlli successivi) scartano il caso, il
    # risultato speculativo viene semplicemente ignorato -- prepare_accept_offer non
    # firma nulla e non muove soldi (solo prenotazione/validazione), quindi non c'e'
    # nulla da annullare. Costo accettato: un prepare_accept_offer "sprecato" in piu'
    # nei rari casi in cui liquidita' scarta un candidato gia' qualificato per AutoBuy.
    # STESSA IDEA estesa al ramo MakeOffer (dati reali 23/07: dettagli_carta pesa
    # 0.16-0.31s SEMPRE dopo liquidita', mai in parallelo) -- se il margine e' gia'
    # noto e NON portera' ad AutoBuy, a questo punto sappiamo GIA' con certezza che
    # andra' a MakeOffer (il caso margine < soglia MakeOffer e' gia' stato scartato
    # sopra), quindi get_card_offer_details puo' partire subito, in parallelo alla
    # stessa query di liquidita' -- e' una chiamata indipendente (curl_cffi, non
    # Playwright), nessun conflitto di thread. Stesso costo accettato: sprecata se
    # liquidita' scarta il caso.
    _prepare_future = None
    _t_prepare_fired = None
    _card_details_future = None
    _t_card_details_fired = None
    _va_verso_autobuy = (not trigger_su_minimo_non_allineato
                          and margin_percent >= AUTOBUY_MARGIN_FRACTION)
    if _va_verso_autobuy and offer_id:
        _t_prepare_fired = time.monotonic()
        _prepare_future = _browser_executor.submit(
            prepare_accept_offer, offer_id, _call_fn=_graphql_call_via_browser_raw)
    elif not _va_verso_autobuy:
        _makeoffer_target_card_slug = true_min_card_slug if trigger_su_minimo_non_allineato else card_slug
        _t_card_details_fired = time.monotonic()
        _card_details_future = _speculative_executor.submit(
            get_card_offer_details, _makeoffer_target_card_slug)

    count_7d, count_30d, ultimo_prezzo_transazione, penultimo_prezzo_transazione = \
        get_liquidity_and_last_price(player_slug, is_in_season, league_slug, eth_rate)
    _t_liquidita = time.monotonic()
    if count_7d is not None and count_7d < MIN_RECENT_TRANSACTIONS:
        log(f"{player_name}: scarto -- solo {count_7d} transazioni negli ultimi "
            f"{RECENT_TRANSACTIONS_WINDOW_DAYS} giorni (minimo richiesto "
            f"{MIN_RECENT_TRANSACTIONS}), mercato troppo sottile")
        if player_slug:
            record_thin_market_skip(player_slug, is_in_season)
        return False
    # NOTA 22/07 (richiesta esplicita utente): rimossa l'imposizione della soglia a
    # 30gg (MIN_TRANSACTIONS_30D) -- quella a 7gg basta e avanza. count_30d viene
    # ancora calcolato dalla stessa identica logica (nessuna modifica a
    # _count_transactions_from_nodes), semplicemente non viene piu' confrontato con
    # nessuna soglia qui.

    # --- ROUTER: nessuna sovrapposizione per costruzione ---
    # NUOVO 22/07: il caso "trigger su minimo non allineato" e' SOLO MakeOffer per
    # richiesta esplicita -- anche se il margine calcolato risultasse >= soglia
    # AutoBuy, non deve MAI finire nel ramo AutoBuy (non stiamo accettando
    # un'offerta esistente su quella carta specifica, stiamo proponendo
    # un'offerta scontata su un'altra carta che risulta essere il vero minimo).
    if trigger_su_minimo_non_allineato:
        if MAKEOFFER_MARGIN_FRACTION <= margin_percent <= MAKEOFFER_MAX_MARGIN_FRACTION:
            prezzo_da_pagare = round(true_min_price * (1 - OFFER_DISCOUNT_FRACTION), 2)
        else:
            return False
    elif margin_percent >= AUTOBUY_MARGIN_FRACTION:
        prezzo_da_pagare = true_min_price
    elif MAKEOFFER_MARGIN_FRACTION <= margin_percent <= MAKEOFFER_MAX_MARGIN_FRACTION:
        prezzo_da_pagare = round(true_min_price * (1 - OFFER_DISCOUNT_FRACTION), 2)
    else:
        return False

    # OTTIMIZZAZIONE VELOCITA' (22/07, richiesta esplicita utente -- "prova a
    # fonderle"): count_7d/count_30d e ultimo/penultimo prezzo ora derivano da UN
    # SOLO fetch di rete (get_liquidity_and_last_price), non piu' due query
    # separate (nemmeno parallele) -- un intero round-trip risparmiato. Nessun
    # controllo saltato: entrambi i risultati arrivano comunque insieme prima di
    # decidere, esattamente come prima.
    if ultimo_prezzo_transazione is not None and prezzo_da_pagare >= ultimo_prezzo_transazione:
        log(f"{player_name}: scarto -- prezzo di acquisto/offerta e' inferiore ad "
            f"ultima/penultima transazione ({prezzo_da_pagare:.2f}EUR >= ultima "
            f"{ultimo_prezzo_transazione:.2f}EUR)")
        return False
    if penultimo_prezzo_transazione is not None and prezzo_da_pagare >= penultimo_prezzo_transazione:
        log(f"{player_name}: scarto -- prezzo di acquisto/offerta e' inferiore ad "
            f"ultima/penultima transazione ({prezzo_da_pagare:.2f}EUR >= penultima "
            f"{penultimo_prezzo_transazione:.2f}EUR)")
        return False

    _timing = (_t0, _t_scan_prezzi, _t_liquidita)

    if trigger_su_minimo_non_allineato:
        # Offerta sempre sulla carta del VERO minimo (true_min_card_slug/
        # true_min_seller_slug), non su quella dell'evento triggerante -- e' il
        # minimo ad essere il bersaglio dell'offerta, l'evento ha solo fatto
        # scattare la rivalutazione del mercato.
        return _handle_makeoffer_branch(player_name, player_slug, true_min_price, second_min_price,
                                         margin_percent, true_min_card_slug, excluded_league,
                                         is_in_season, true_min_seller_slug,
                                         via_trigger_non_allineato=True, timing=_timing,
                                         card_details_future=_card_details_future,
                                         card_details_started_at=_t_card_details_fired)

    if margin_percent >= AUTOBUY_MARGIN_FRACTION:
        return _handle_autobuy_branch(player_name, player_slug, true_min_price, second_min_price,
                                       margin_percent, card_slug, excluded_league, is_in_season,
                                       offer_id, timing=_timing, prepare_future=_prepare_future,
                                       prepare_started_at=_t_prepare_fired)
    return _handle_makeoffer_branch(player_name, player_slug, true_min_price, second_min_price,
                                     margin_percent, card_slug, excluded_league, is_in_season,
                                     seller_slug, timing=_timing, card_details_future=_card_details_future,
                                     card_details_started_at=_t_card_details_fired)


def _run_autobuy_merged(player_name, offer_id, prepare_future=None, prepare_started_at=None):
    """OTTIMIZZAZIONE VELOCITA' 22/07 v6 + 23/07 (richiesta esplicita utente -- casi
    Edier Ocampo/Alex Roldan persi a prepare_accept_offer per "Too late"):
    prepare_accept_offer puo' ora arrivare GIA' lanciata (prepare_future, sottomessa
    da evaluate_event in parallelo alla query di liquidita') -- la riusiamo qui invece
    di rifare la chiamata da capo. Questo riporta execute_live_purchase a un dispatch
    SEPARATO (invece del singolo dispatch fuso del 22/07 v6) SOLO quando prepare e'
    stata pre-lanciata: costa un hop in piu' (~0.25-0.3s) ma SOLO DOPO aver gia' vinto
    la prenotazione (prepare riuscita = carta gia' assicurata), quindi non costa piu'
    la corsa contro altri bot. prepare_started_at preserva il tempo REALE di durata
    di prepare_accept_offer nel log [timing] anche se il .result() qui sotto ritorna
    subito perche' il lavoro era gia' in corso da prima. Se prepare_future non e'
    stata lanciata (fallback), stesso comportamento di prima (fusa in un dispatch).
    Ritorna (prepared, prepare_category, purchase_completed, purchase_error,
    durata_prepare, durata_esecuzione)."""
    if prepare_future is not None:
        _t_a = prepare_started_at if prepare_started_at is not None else time.monotonic()
        prepared, prepare_category = prepare_future.result()
        _t_b = time.monotonic()
        if not prepared or not AUTOBUY_LIVE_MODE:
            return prepared, prepare_category, False, None, _t_b - _t_a, 0.0
        try:
            purchase_completed, purchase_error = _browser_executor.submit(
                execute_live_purchase, offer_id, prepared,
                _call_fn=_graphql_call_via_browser_raw).result()
        except Exception as e:
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante acquisto live -- {e}")
            return prepared, prepare_category, False, f"eccezione imprevista: {e}", \
                _t_b - _t_a, time.monotonic() - _t_b
        return (prepared, prepare_category, purchase_completed, purchase_error,
                _t_b - _t_a, time.monotonic() - _t_b)

    def _sequenza_completa():
        _t_a = time.monotonic()
        prepared, prepare_category = prepare_accept_offer(
            offer_id, _call_fn=_graphql_call_via_browser_raw)
        _t_b = time.monotonic()
        if not prepared or not AUTOBUY_LIVE_MODE:
            return prepared, prepare_category, False, None, _t_b - _t_a, 0.0
        try:
            purchase_completed, purchase_error = execute_live_purchase(
                offer_id, prepared, _call_fn=_graphql_call_via_browser_raw)
        except Exception as e:
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante acquisto live -- {e}")
            return prepared, prepare_category, False, f"eccezione imprevista: {e}", \
                _t_b - _t_a, time.monotonic() - _t_b
        return (prepared, prepare_category, purchase_completed, purchase_error,
                _t_b - _t_a, time.monotonic() - _t_b)
    return _run_on_browser_thread(_sequenza_completa)


def _run_makeoffer_merged(player_name, card_asset_id, seller_slug, offer_amount_eur):
    """Stessa ottimizzazione di _run_autobuy_merged, per il ramo MakeOffer:
    prepare_offer + execute_live_offer (che include create_direct_offer) fusi
    in UN SOLO dispatch al thread dedicato Playwright, invece di due. Usata sia
    dal MakeOffer normale (_handle_makeoffer_branch) sia dal bid periodico
    (_try_periodic_bid) -- stessa logica di offerta, stesso beneficio.
    Rispetta MAKEOFFER_LIVE_MODE internamente (esegue create_direct_offer SOLO
    se e' 'si' e prepare_offer e' riuscita), stessa logica di prima.
    Ritorna (prepared, offer_sent, offer_error, durata_prepare, durata_esecuzione)."""
    def _sequenza_completa():
        _t_a = time.monotonic()
        prepared = prepare_offer(card_asset_id, seller_slug, offer_amount_eur,
                                  _call_fn=_graphql_call_via_browser_raw)
        _t_b = time.monotonic()
        if not prepared or not MAKEOFFER_LIVE_MODE:
            return prepared, False, None, _t_b - _t_a, 0.0
        try:
            offer_sent, offer_error = execute_live_offer(
                card_asset_id, seller_slug, offer_amount_eur, prepared,
                _call_fn=_graphql_call_via_browser_raw)
        except Exception as e:
            log(f"{player_name}: ECCEZIONE IMPREVISTA durante offerta live -- {e}")
            return prepared, False, f"eccezione imprevista: {e}", _t_b - _t_a, time.monotonic() - _t_b
        return prepared, offer_sent, offer_error, _t_b - _t_a, time.monotonic() - _t_b
    return _run_on_browser_thread(_sequenza_completa)


def _handle_autobuy_branch(player_name, player_slug, true_min_price, second_min_price,
                            margin_percent, card_slug, excluded_league, is_in_season, offer_id,
                            timing=None, prepare_future=None, prepare_started_at=None):
    log(f"AUTOBUY: {player_name} -- LO AVREI ACQUISTATO ({true_min_price:.2f}EUR, "
        f"margine {margin_percent:.1%})")

    prepared = None
    prepare_category = None
    purchase_completed = False
    purchase_error = None
    _durata_prepare = None
    _durata_esecuzione = None

    # FIX 22/07 v6 + 23/07 (ottimizzazione velocita'): se prepare_future e' gia' stata
    # lanciata in parallelo al controllo di liquidita' (vedi evaluate_event), la
    # riusiamo qui -- nessuna doppia chiamata prepareAcceptOffer. In quel caso
    # execute_live_purchase parte come dispatch SEPARATO (un hop in piu', ma solo
    # DOPO aver gia' vinto la prenotazione, quindi non costa piu' la corsa). Se
    # prepare_future non e' stata lanciata (fallback), stessa fusione di prima.
    if offer_id:
        prepared, prepare_category, purchase_completed, purchase_error, \
            _durata_prepare, _durata_esecuzione = _run_autobuy_merged(
                player_name, offer_id, prepare_future=prepare_future,
                prepare_started_at=prepare_started_at)
        if prepared:
            nonce = (prepared.get('request') or {}).get('nonce')
            log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
        elif prepare_category == 'valuta_non_supportata':
            log(f"{player_name}: prenotazione non riuscita -- annuncio in valuta "
                f"crypto/ETH non gestibile dall'acquisto automatico (stesso motivo "
                f"per cui MakeOffer scarterebbe un annuncio solo-ETH)")
        else:
            log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

    if AUTOBUY_LIVE_MODE and offer_id and prepared:
        if purchase_completed:
            log(f"{player_name}: ACQUISTO COMPLETATO CON SUCCESSO")
            if player_slug:
                record_player_purchase(player_slug, is_in_season)
        else:
            log(f"{player_name}: acquisto automatico fallito -- {purchase_error}")
            if _is_insufficient_funds_error(purchase_error):
                log(f"{player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot, "
                    f"nessun tentativo successivo avrebbe senso")
                INSUFFICIENT_FUNDS_STOP[0] = True
                send_insufficient_funds_alert(player_name, "AutoBuy")
    elif AUTOBUY_LIVE_MODE and offer_id and not prepared:
        purchase_error = "prenotazione (prepareAcceptOffer) non riuscita, acquisto automatico saltato"
        log(f"{player_name}: {purchase_error}")

    # DIAGNOSTICA TEMPORANEA TEMPI (22/07, richiesta esplicita utente -- capire
    # dove va il tempo nei casi persi per velocita' contro altri bot). Da
    # rimuovere quando l'indagine e' conclusa (EVENT_TIMING_DIAGNOSTIC).
    if EVENT_TIMING_DIAGNOSTIC and timing:
        _t0, _t_scan, _t_liq = timing
        _t_fine = time.monotonic()
        _parti = [f"scan_prezzi={_t_scan - _t0:.3f}s", f"liquidita+ultimo_prezzo={_t_liq - _t_scan:.3f}s"]
        if _durata_prepare is not None:
            _parti.append(f"prepare_accept_offer={_durata_prepare:.3f}s")
            _parti.append(f"esecuzione_finale={_durata_esecuzione:.3f}s")
        _nota_parallelo = " [prepare in parallelo con liquidita']" if prepare_started_at is not None else ""
        log(f"[timing] {player_name}: {', '.join(_parti)} -- TOTALE={_t_fine - _t0:.3f}s{_nota_parallelo}")

    send_autobuy_alert(player_name, player_slug, true_min_price, second_min_price,
                        margin_percent, card_slug, excluded_league, prepared, is_in_season,
                        live_mode=AUTOBUY_LIVE_MODE, purchase_completed=purchase_completed,
                        purchase_error=purchase_error)
    return True


def _handle_makeoffer_branch(player_name, player_slug, true_min_price, second_min_price,
                              margin_percent, card_slug, excluded_league, is_in_season, seller_slug,
                              via_trigger_non_allineato=False, timing=None, card_details_future=None,
                              card_details_started_at=None):
    if via_trigger_non_allineato:
        log(f"MAKEOFFER [trigger su minimo non allineato]: {player_name} -- TROVATO AFFARE "
            f"({true_min_price:.2f}EUR, margine {margin_percent:.1%}) -- valuto se fare un'offerta "
            f"sul vero minimo (carta {card_slug}, diversa dall'annuncio che ha fatto scattare "
            f"l'evento)")
    else:
        log(f"MAKEOFFER: {player_name} -- TROVATO AFFARE ({true_min_price:.2f}EUR, "
            f"margine {margin_percent:.1%}) -- valuto se fare un'offerta")

    # OTTIMIZZAZIONE VELOCITA' 23/07: se card_details_future e' gia' stata lanciata in
    # parallelo alla query di liquidita' (vedi evaluate_event), la riusiamo qui invece
    # di rifare la chiamata da capo. Fallback (nessuna future) = comportamento di prima.
    if card_details_future is not None:
        card_details = card_details_future.result()
    else:
        card_details = get_card_offer_details(card_slug)
    _t_card_details = time.monotonic()
    if not card_details:
        log(f"{player_name}: scarto -- impossibile recuperare i dettagli della carta "
            f"({card_slug}), niente assetId disponibile")
        return False

    card_asset_id = card_details.get('assetId')
    if not card_asset_id:
        log(f"{player_name}: scarto -- assetId assente per {card_slug}")
        return False

    existing_offers = card_details.get('liveSingleBuyOffers') or []
    if existing_offers:
        log(f"{player_name}: scarto -- offerta gia' pendente su questa carta "
            f"({len(existing_offers)} offerta/e attiva/e), non ne faccio una seconda")
        return False

    sale_offer = card_details.get('liveSingleSaleOffer') or {}
    settlement_currencies = sale_offer.get('settlementCurrencies') or []
    crypto_only_currencies = {'WEI', 'ETH'}
    if settlement_currencies and set(settlement_currencies).issubset(crypto_only_currencies):
        log(f"{player_name}: scarto -- venditore accetta solo cripto, niente fiat "
            f"(valute accettate: {settlement_currencies})")
        return False

    if pending_offers_count[0] >= MAX_PENDING_OFFERS:
        log(f"{player_name}: scarto -- gia' raggiunto il tetto di {MAX_PENDING_OFFERS} "
            f"offerte pendenti in questa esecuzione")
        return False

    offer_amount_eur = round(true_min_price * (1 - OFFER_DISCOUNT_FRACTION), 2)
    if offer_amount_eur <= 0:
        log(f"{player_name}: scarto -- offerta calcolata non positiva ({offer_amount_eur}EUR)")
        return False

    log(f"{player_name}: offerta calcolata: {offer_amount_eur:.2f}EUR "
        f"(minimo {true_min_price:.2f}EUR - sconto {OFFER_DISCOUNT_FRACTION:.0%}), "
        f"durata {OFFER_DURATION_DAYS} giorni")

    prepared, offer_sent, offer_error, _durata_prepare, _durata_esecuzione = \
        _run_makeoffer_merged(player_name, card_asset_id, seller_slug, offer_amount_eur)
    if prepared:
        nonce = (prepared.get('request') or {}).get('nonce')
        log(f"{player_name}: offerta prenotata lato server (nonce={nonce})")
    else:
        log(f"{player_name}: prenotazione offerta non riuscita, procedo comunque con la notifica")

    if MAKEOFFER_LIVE_MODE and prepared:
        if offer_sent:
            log(f"{player_name}: OFFERTA INVIATA CON SUCCESSO")
            if via_trigger_non_allineato and MIN_NON_TRIGGER_LOG:
                log(f"[trigger su minimo non allineato] {player_name}: offerta di "
                    f"{offer_amount_eur:.2f}EUR inviata con successo tramite questo "
                    f"meccanismo (carta {card_slug})")
            if player_slug:
                record_player_offer(player_slug, is_in_season)
            pending_offers_count[0] += 1
        else:
            log(f"{player_name}: offerta automatica fallita -- {offer_error}")
            if _is_insufficient_funds_error(offer_error):
                log(f"{player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot, "
                    f"nessun tentativo successivo avrebbe senso")
                INSUFFICIENT_FUNDS_STOP[0] = True
                send_insufficient_funds_alert(player_name, "MakeOffer")
            elif _is_invalid_signature_error(offer_error):
                log(f"{player_name}: FIRMA NON VALIDA rilevata verso il manager "
                    f"'{seller_slug}' -- invio notifica diagnostica (causa non "
                    f"confermata, vedi Telegram)")
                send_invalid_signature_diagnostic_alert(player_name, seller_slug, offer_amount_eur)
    elif MAKEOFFER_LIVE_MODE and not prepared:
        offer_error = "prenotazione (prepareOffer) non riuscita, offerta automatica saltata"
        log(f"{player_name}: {offer_error}")

    # DIAGNOSTICA TEMPORANEA TEMPI (22/07, richiesta esplicita utente -- capire
    # dove va il tempo nei casi persi per velocita' contro altri bot, in
    # particolare per il ramo MakeOffer che ha uno step in piu' (dettagli carta)
    # rispetto ad AutoBuy. Da rimuovere quando l'indagine e' conclusa
    # (EVENT_TIMING_DIAGNOSTIC).
    if EVENT_TIMING_DIAGNOSTIC and timing:
        _t0, _t_scan, _t_liq = timing
        _t_fine = time.monotonic()
        _base_dettagli = card_details_started_at if card_details_started_at is not None else _t_liq
        _parti = [f"scan_prezzi={_t_scan - _t0:.3f}s", f"liquidita+ultimo_prezzo={_t_liq - _t_scan:.3f}s",
                  f"dettagli_carta={_t_card_details - _base_dettagli:.3f}s",
                  f"prepare_offer={_durata_prepare:.3f}s",
                  f"esecuzione_finale={_durata_esecuzione:.3f}s"]
        _nota_parallelo = " [dettagli_carta in parallelo con liquidita']" \
            if card_details_started_at is not None else ""
        log(f"[timing] {player_name}: {', '.join(_parti)} -- TOTALE={_t_fine - _t0:.3f}s{_nota_parallelo}")

    send_makeoffer_alert(player_name, player_slug, true_min_price, second_min_price,
                          margin_percent, card_slug, excluded_league, prepared, is_in_season,
                          live_mode=MAKEOFFER_LIVE_MODE, purchase_completed=offer_sent,
                          purchase_error=offer_error, offer_amount_eur=offer_amount_eur)
    return True
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


def run_listener(eth_rate):
    identifier = json.dumps({"channel": "GraphqlChannel"})
    subscription_payload = {
        "query": SUBSCRIPTION_QUERY,
        "variables": {},
        "operationName": "OnTokenOfferUpdated",
        "action": "execute",
    }

    stats = {"received": 0, "processed": 0, "matches_found": 0,
              "_closed_target": False, "_closed_insufficient_funds": False}
    seen_offer_status = set()
    # OTTIMIZZAZIONE VELOCITA' -- CONCORRENZA (22/07): stats_lock protegge gli
    # incrementi/controlli su stats fatti dai thread worker (sotto), e le due
    # flag "_closed_*" evitano di chiudere il WebSocket piu' di una volta se piu'
    # thread arrivano alla condizione di stop quasi insieme.
    stats_lock = threading.Lock()
    # Pool di thread per valutare piu' eventi IN PARALLELO invece che uno alla
    # volta -- vedi nota su EVENT_WORKER_THREADS. on_message torna subito dopo
    # aver sottomesso il lavoro, restando libero di leggere il prossimo evento.
    event_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=EVENT_WORKER_THREADS, thread_name_prefix='evt')

    # --- Pausa random periodica (20/07, richiesta esplicita utente: "non martellare
    # Sorare di richieste troppo ritmate/prevedibili") -- ogni RANDOM_PAUSE_INTERVAL_
    # SECONDS (default 180s = 3 minuti) di attivita', il bot si ferma per un tempo
    # casuale tra RANDOM_PAUSE_MIN_SECONDS e RANDOM_PAUSE_MAX_SECONDS (default 1-10s)
    # prima di riprendere a valutare eventi. Il timer parte dall'avvio dell'ascolto,
    # non resetta ad ogni evento -- e' un ritmo di fondo, non legato al volume di
    # eventi ricevuti.
    pause_state = {"last_pause_at": time.monotonic()}
    # OTTIMIZZAZIONE VELOCITA' -- CONCORRENZA (22/07): con piu' thread worker che
    # possono chiamare maybe_random_pause() quasi insieme, serve un lock -- ma
    # SOLO per il controllo/marcatura "e' ora di pausare?", non per il time.sleep
    # vero e proprio (che resta FUORI dal lock, altrimenti un thread in pausa
    # bloccherebbe anche gli altri dal controllare/aggiornare il proprio stato).
    _pause_lock = threading.Lock()

    def maybe_random_pause():
        due = False
        with _pause_lock:
            now = time.monotonic()
            if now - pause_state["last_pause_at"] >= RANDOM_PAUSE_INTERVAL_SECONDS:
                due = True
                pause_state["last_pause_at"] = now
        if due:
            pause_seconds = random.uniform(RANDOM_PAUSE_MIN_SECONDS, RANDOM_PAUSE_MAX_SECONDS)
            log(f"[pausa random] fermo {pause_seconds:.1f}s (ritmo di fondo anti-martellamento)")
            time.sleep(pause_seconds)

    def on_open(ws):
        log("Connesso al canale eventi Sorare, sottoscrizione in corso...")
        ws.send(json.dumps({"command": "subscribe", "identifier": identifier}))
        time.sleep(1)
        ws.send(json.dumps({
            "command": "message",
            "identifier": identifier,
            "data": json.dumps(subscription_payload),
        }))

    def _process_one_card_event(player_slug, player_name, price_eur, card_slug,
                                 league_slug, offer_id, seller_slug, is_in_season):
        """Gira in un thread del pool: valuta UN candidato per intero (stessa
        identica logica di prima), senza bloccare on_message/il lettore
        WebSocket nel frattempo. Ogni eccezione e' catturata qui (on_message
        NON puo' piu' farlo per questo pezzo, dato che ora gira in un thread
        separato) -- stesso principio 'mai un crash silenzioso' di sempre."""
        try:
            found = evaluate_event(player_slug, player_name, price_eur, card_slug, eth_rate,
                                    league_slug, offer_id, seller_slug, is_in_season)
        except Exception as e:
            log(f"[ERRORE in valutazione evento] {player_name}: eccezione non gestita "
                f"durante la valutazione (thread worker), la salto e continuo: {e}")
            found = False

        maybe_random_pause()

        if INSUFFICIENT_FUNDS_STOP[0]:
            with stats_lock:
                gia_chiuso = stats["_closed_insufficient_funds"]
                stats["_closed_insufficient_funds"] = True
            if not gia_chiuso:
                log("STOP: fondi insufficienti rilevati, chiudo la connessione -- "
                    "nessun tentativo successivo avrebbe senso")
                ws.close()
            return

        if found:
            with stats_lock:
                stats["matches_found"] += 1
                trovati = stats["matches_found"]
                target_raggiunto = trovati >= AUTOBUY_TARGET_MATCHES and not stats["_closed_target"]
                if target_raggiunto:
                    stats["_closed_target"] = True
            log(f"Casi trovati finora: {trovati}/{AUTOBUY_TARGET_MATCHES}")
            if target_raggiunto:
                ws.close()

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

        # FIX diagnostica 'bot piantato': tutto il corpo di valutazione dell'evento e'
        # ora dentro un try/except generale. Prima, un'eccezione imprevista in un
        # qualunque punto (evaluate_event, playwright, parsing di un campo mancante,
        # ecc.) usciva dal callback on_message senza essere loggata da noi -- a seconda
        # della versione di websocket-client questo puo' interrompere silenziosamente
        # il thread che legge dal socket, dando l'impressione che il bot sia
        # "piantato" dopo la connessione, senza nessun log ne' su Telegram ne' in
        # console che lo spieghi.
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

            seller_slug = ((offer.get('sender') or {}).get('slug') or '').lower()
            if seller_slug in BLACKLISTED_SELLER_SLUGS:
                return
            if seller_slug in BLACKLISTED_MANAGER_SLUGS:
                return

            sender_side = offer.get('senderSide') or {}
            receiver_side = offer.get('receiverSide') or {}
            if receiver_side.get('anyCards'):
                return  # scambio carta-per-carta

            price_eur = eur_price_from_amounts(receiver_side.get('amounts'), eth_rate)
            if price_eur is None:
                return

            sender_cards = sender_side.get('anyCards') or []
            if len(sender_cards) > 1:
                return  # bundle multi-carta, prezzo per-carta non ricavabile

            for card in sender_cards:
                if card.get('rarityTyped') != 'limited':
                    continue
                if card.get('sport') != 'FOOTBALL':
                    continue

                player = card.get('anyPlayer') or {}
                player_slug = player.get('slug')
                player_name = player.get('displayName', player_slug)
                card_slug = card.get('slug')

                is_in_season = bool(card.get('inSeasonEligible'))
                if not is_in_season and not CHECK_CLASSIC:
                    continue  # modalita' base: SOLO in season
                league_slug = ((player.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
                if not player_slug:
                    continue

                stats["processed"] += 1
                # OTTIMIZZAZIONE VELOCITA' -- CONCORRENZA (22/07, richiesta esplicita
                # utente): invece di valutare qui (bloccando la lettura del prossimo
                # evento WebSocket per tutta la durata di evaluate_event), il lavoro
                # viene sottomesso al pool e on_message torna subito -- il bot resta
                # libero di leggere/valutare il prossimo evento mentre questo e'
                # ancora in corso. Stessa identica logica di valutazione, solo non
                # piu' bloccante per il lettore WebSocket.
                event_executor.submit(_process_one_card_event, player_slug, player_name,
                                       price_eur, card_slug, league_slug, offer_id,
                                       seller_slug, is_in_season)
        except Exception as e:
            log(f"[ERRORE in on_message] eccezione non gestita durante la valutazione "
                f"di un evento, la salto e continuo ad ascoltare: {e}")

    def on_error(ws, error):
        log(f"Errore WebSocket: {error}")

    def on_close(ws, close_status_code, close_message):
        log(f"Connessione chiusa (codice {close_status_code}). Eventi ricevuti: "
            f"{stats['received']}, carte in season elaborate: {stats['processed']}, "
            f"casi validi trovati: {stats['matches_found']}/{AUTOBUY_TARGET_MATCHES}")

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
    # Aspetta che eventuali valutazioni ancora in corso nel pool finiscano
    # (es. un'offerta/acquisto gia' avviato) prima di chiudere -- niente
    # tentativi troncati a meta' solo perche' la connessione WebSocket si e'
    # chiusa nel frattempo.
    event_executor.shutdown(wait=True)

    return stats["matches_found"]


# COMMIT PERIODICO LISTA NERA (21/07, richiesta esplicita utente -- "evitare che
# un'interruzione della run perda blacklist/cooldown accumulati"): il file
# sorare_lista_nera.txt viene gia' scritto su disco ad ogni upsert (vedi
# _lista_nera_scrivi_righe), ma restava solo LOCALE fino al commit finale del
# workflow -- se la run si interrompeva a meta' (timeout, cancellazione manuale,
# crash), tutto cio' che il bot aveva imparato in quella sessione (nuovi cooldown,
# nuove blacklist automatiche 365gg) andava perso. Un thread separato, parallelo
# al listener WebSocket (che resta l'UNICA cosa che deve restare vivo/continuo --
# niente piu' restart a chunk come per MLS Sentiment, qui romperebbe la sessione
# live), fa git add/commit/push ogni COMMIT_INTERVAL_SECONDS (default 300s = 5
# minuti) SOLO se il file e' effettivamente cambiato dall'ultimo commit.
COMMIT_INTERVAL_SECONDS = int(os.environ.get('COMMIT_INTERVAL_SECONDS', '300'))
# BID PERIODICO OGNI 2 MINUTI (22/07, richiesta esplicita utente, specifica completa
# concordata) -- meccanismo INDIPENDENTE dal listener WebSocket, CONVIVE in parallelo.
# Ogni PERIODIC_BID_INTERVAL_SECONDS, prende il candidato che durante la finestra si
# e' avvicinato di piu' alla soglia MakeOffer (anche restando sotto), e gli fa
# un'offerta secca al PERIODIC_BID_DISCOUNT sotto il minimo REGISTRATO in quel
# momento -- bypassando la sola soglia minima di margine. SOLO offerte (MakeOffer),
# MAI acquisto diretto. Fascia prezzo e sconto FISSI nel codice (non configurabili),
# solo l'attivazione e' un input del workflow (default 'si').
PERIODIC_BID_ENABLED = os.environ.get('PERIODIC_BID_ENABLED', 'si').strip().lower() == 'si'
PERIODIC_BID_INTERVAL_SECONDS = 120
PERIODIC_BID_MIN_PRICE_EUR = 2.0
PERIODIC_BID_MAX_PRICE_EUR = 30.0
PERIODIC_BID_DISCOUNT_FRACTION = 0.30

# Stato condiviso tra i thread worker di evaluate_event (che scrivono il candidato
# migliore del ciclo corrente) e il thread del timer periodico (che legge e svuota).
# Protetto da _periodic_bid_lock -- scritture concorrenti da piu' thread evaluate_event,
# lettura+svuotamento dal thread del timer.
_periodic_bid_lock = threading.Lock()
_periodic_bid_best = None  # dict col candidato migliore del ciclo corrente, o None
# OTTIMIZZAZIONE VELOCITA' -- CONCORRENZA (22/07, richiesta esplicita utente,
# rischio accettato): quanti eventi valutare IN PARALLELO invece che uno alla
# volta. Prima, on_message chiamava evaluate_event in modo sincrono/bloccante --
# mentre il bot era occupato a valutare un candidato (anche uno che poi risultava
# uno scarto, dopo una o piu' query di rete), non poteva nemmeno leggere il
# prossimo evento in arrivo dal WebSocket, restando "cieco" proprio nel momento
# in cui poteva arrivare il vero affare. Non esposta nel workflow_dispatch
# (il file .yml e' gia' al limite di 25 input) -- modificabile qui o con una env
# var settata direttamente nel job se mai servisse.
EVENT_WORKER_THREADS = int(os.environ.get('EVENT_WORKER_THREADS', '6'))
# DIAGNOSTICA TEMPORANEA TEMPI (22/07, richiesta esplicita utente -- capire dove
# va il tempo nei casi persi per velocita' contro altri bot). Default 'si'
# apposta (non 'no' come le altre diagnostiche opt-in) perche' e' esattamente
# quello che serve ORA per l'indagine in corso -- non esposta nel
# workflow_dispatch (.yml gia' al limite di 25 input), disattivabile con una env
# var se mai servisse. RIMUOVERE (variabile + tutti i blocchi 'if
# EVENT_TIMING_DIAGNOSTIC') quando l'indagine e' conclusa.
EVENT_TIMING_DIAGNOSTIC = os.environ.get('EVENT_TIMING_DIAGNOSTIC', 'si').strip().lower() == 'si'
_stop_periodic_commit = threading.Event()
_stop_periodic_bid = threading.Event()


def _commit_lista_nera_se_serve():
    """Un solo tentativo di commit+push, non bloccante per il resto del bot in
    caso di errore (rete, conflitto git, ecc.) -- logga e continua, la prossima
    esecuzione periodica ritentera' comunque."""
    try:
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--', LISTA_NERA_PATH],
            capture_output=True, text=True, timeout=30
        )
        if not status.stdout.strip():
            return  # nessuna modifica, niente da committare
        subprocess.run(['git', 'config', 'user.name', 'bot-supremo'], timeout=30)
        subprocess.run(['git', 'config', 'user.email',
                         'bot-supremo@users.noreply.github.com'], timeout=30)
        subprocess.run(['git', 'add', LISTA_NERA_PATH], timeout=30)
        commit = subprocess.run(
            ['git', 'commit', '-m', 'Bot Supremo: commit periodico lista nera (run in corso)'],
            capture_output=True, text=True, timeout=30
        )
        if commit.returncode != 0:
            log(f"[commit periodico] nulla da committare o commit fallito: {commit.stdout.strip()} {commit.stderr.strip()}")
            return
        pull = subprocess.run(
            ['git', 'pull', '--rebase', '--autostash', 'origin', 'main'],
            capture_output=True, text=True, timeout=60
        )
        if pull.returncode != 0:
            log(f"[commit periodico] git pull --rebase fallito, salto il push di questo giro: {pull.stderr.strip()}")
            return
        push = subprocess.run(['git', 'push'], capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            log("[commit periodico] lista nera committata e pushata con successo (run ancora in corso)")
        else:
            log(f"[commit periodico] push fallito: {push.stderr.strip()}")
    except Exception as e:
        log(f"[commit periodico] eccezione non bloccante, ritento al prossimo giro: {e}")


def _periodic_commit_loop():
    while not _stop_periodic_commit.wait(COMMIT_INTERVAL_SECONDS):
        _commit_lista_nera_se_serve()


def _try_periodic_bid(candidato, eth_rate):
    """Verifica DA CAPO il candidato scelto (cooldown, offerte pendenti, liquidita',
    ultimo/penultimo prezzo -- esattamente come una carta target normale del
    MakeOffer) e, se passa tutto, invia un'offerta secca al PERIODIC_BID_DISCOUNT_
    FRACTION sotto il minimo REGISTRATO al momento del tracciamento (non ricalcolato
    fresco, scelta esplicita dell'utente). SOLO offerte, MAI acquisto diretto. Se un
    qualunque controllo fallisce, salta il giro -- NESSUN ripiego su altri candidati
    (confermato esplicitamente dall'utente)."""
    player_slug = candidato['player_slug']
    player_name = candidato['player_name']
    card_slug = candidato['card_slug']
    seller_slug = candidato['seller_slug']
    true_min_price = candidato['true_min_price']
    is_in_season = candidato['is_in_season']
    league_slug = candidato['league_slug']

    log(f"[bid periodico] {player_name}: candidato del ciclo -- minimo registrato "
        f"{true_min_price:.2f}EUR, margine registrato {candidato['margin_percent']:.1%} "
        f"-- rivalidazione in corso prima dell'offerta")

    # Stessi controlli di cooldown/offerte pendenti di una carta target normale --
    # possono essere cambiati nei ~2 minuti trascorsi dal tracciamento.
    if player_slug and is_player_in_cooldown(player_slug, is_in_season):
        log(f"[bid periodico] {player_name}: scarto -- gia' acquistato/offerto di "
            f"recente (cooldown), salto questo ciclo")
        return False
    if player_slug and is_player_in_forma_bassa(player_slug.lower()):
        log(f"[bid periodico] {player_name}: scarto -- in 'forma bassa ultime 5', "
            f"salto questo ciclo")
        return False
    if player_slug and is_player_in_thin_market_cache(player_slug, is_in_season):
        log(f"[bid periodico] {player_name}: scarto -- gia' segnalato come mercato "
            f"troppo sottile di recente, salto questo ciclo")
        return False

    count_7d, count_30d, ultimo_prezzo_transazione, penultimo_prezzo_transazione = \
        get_liquidity_and_last_price(player_slug, is_in_season, league_slug, eth_rate)
    if count_7d is not None and count_7d < MIN_RECENT_TRANSACTIONS:
        log(f"[bid periodico] {player_name}: scarto -- solo {count_7d} transazioni "
            f"negli ultimi {RECENT_TRANSACTIONS_WINDOW_DAYS} giorni, mercato troppo "
            f"sottile, salto questo ciclo")
        if player_slug:
            record_thin_market_skip(player_slug, is_in_season)
        return False

    offer_amount_eur = round(true_min_price * (1 - PERIODIC_BID_DISCOUNT_FRACTION), 2)
    if offer_amount_eur <= 0:
        log(f"[bid periodico] {player_name}: scarto -- offerta calcolata non positiva")
        return False
    if ultimo_prezzo_transazione is not None and offer_amount_eur >= ultimo_prezzo_transazione:
        log(f"[bid periodico] {player_name}: scarto -- offerta ({offer_amount_eur:.2f}EUR) "
            f"non inferiore all'ultima transazione ({ultimo_prezzo_transazione:.2f}EUR), "
            f"salto questo ciclo")
        return False
    if penultimo_prezzo_transazione is not None and offer_amount_eur >= penultimo_prezzo_transazione:
        log(f"[bid periodico] {player_name}: scarto -- offerta ({offer_amount_eur:.2f}EUR) "
            f"non inferiore alla penultima transazione ({penultimo_prezzo_transazione:.2f}EUR), "
            f"salto questo ciclo")
        return False

    # Da qui in poi, IDENTICO a _handle_makeoffer_branch: dettagli carta, offerta
    # pendente gia' esistente, valute accettate, invio -- stessi identici controlli
    # di una carta target normale.
    card_details = get_card_offer_details(card_slug)
    if not card_details:
        log(f"[bid periodico] {player_name}: scarto -- impossibile recuperare i "
            f"dettagli della carta, salto questo ciclo")
        return False
    card_asset_id = card_details.get('assetId')
    if not card_asset_id:
        log(f"[bid periodico] {player_name}: scarto -- assetId assente, salto questo ciclo")
        return False
    existing_offers = card_details.get('liveSingleBuyOffers') or []
    if existing_offers:
        log(f"[bid periodico] {player_name}: scarto -- offerta gia' pendente su "
            f"questa carta, salto questo ciclo")
        return False
    sale_offer = card_details.get('liveSingleSaleOffer') or {}
    settlement_currencies = sale_offer.get('settlementCurrencies') or []
    crypto_only_currencies = {'WEI', 'ETH'}
    if settlement_currencies and set(settlement_currencies).issubset(crypto_only_currencies):
        log(f"[bid periodico] {player_name}: scarto -- venditore accetta solo cripto, "
            f"salto questo ciclo")
        return False
    if pending_offers_count[0] >= MAX_PENDING_OFFERS:
        log(f"[bid periodico] {player_name}: scarto -- gia' raggiunto il tetto di "
            f"offerte pendenti in questa esecuzione, salto questo ciclo")
        return False

    log(f"[bid periodico] {player_name}: offerta calcolata {offer_amount_eur:.2f}EUR "
        f"(minimo registrato {true_min_price:.2f}EUR - sconto "
        f"{PERIODIC_BID_DISCOUNT_FRACTION:.0%}), durata {OFFER_DURATION_DAYS} giorni")

    prepared, offer_sent, offer_error, _durata_prepare, _durata_esecuzione = \
        _run_makeoffer_merged(player_name, card_asset_id, seller_slug, offer_amount_eur)
    if not prepared:
        log(f"[bid periodico] {player_name}: prenotazione offerta non riuscita, "
            f"salto questo ciclo")
        send_makeoffer_alert(player_name, player_slug, true_min_price, true_min_price,
                              candidato['margin_percent'], card_slug, candidato['excluded_league'],
                              prepared, is_in_season, live_mode=MAKEOFFER_LIVE_MODE,
                              purchase_completed=False,
                              purchase_error="prenotazione (prepareOffer) non riuscita",
                              offer_amount_eur=offer_amount_eur, via_periodic_bid=True)
        return False
    nonce = (prepared.get('request') or {}).get('nonce')
    log(f"[bid periodico] {player_name}: offerta prenotata lato server (nonce={nonce})")

    if not MAKEOFFER_LIVE_MODE:
        log(f"[bid periodico] {player_name}: MAKEOFFER_LIVE_MODE spento, offerta non inviata")
        return False

    if offer_sent:
        log(f"[bid periodico] {player_name}: OFFERTA INVIATA CON SUCCESSO")
        if player_slug:
            record_player_offer(player_slug, is_in_season)
        pending_offers_count[0] += 1
        send_makeoffer_alert(player_name, player_slug, true_min_price, true_min_price,
                              candidato['margin_percent'], card_slug, candidato['excluded_league'],
                              prepared, is_in_season, live_mode=MAKEOFFER_LIVE_MODE,
                              purchase_completed=True, offer_amount_eur=offer_amount_eur,
                              via_periodic_bid=True)
        return True

    log(f"[bid periodico] {player_name}: offerta fallita -- {offer_error}")
    if _is_insufficient_funds_error(offer_error):
        log(f"[bid periodico] {player_name}: FONDI INSUFFICIENTI rilevati -- fermo il bot")
        INSUFFICIENT_FUNDS_STOP[0] = True
        send_insufficient_funds_alert(player_name, "Bid periodico")
    send_makeoffer_alert(player_name, player_slug, true_min_price, true_min_price,
                          candidato['margin_percent'], card_slug, candidato['excluded_league'],
                          prepared, is_in_season, live_mode=MAKEOFFER_LIVE_MODE,
                          purchase_completed=False, purchase_error=offer_error,
                          offer_amount_eur=offer_amount_eur, via_periodic_bid=True)
    return False


def _periodic_bid_loop(eth_rate):
    """Gira in un thread dedicato per tutta la run, indipendente dal listener
    WebSocket -- ogni PERIODIC_BID_INTERVAL_SECONDS (default 120s = 2 minuti),
    prende il candidato migliore del ciclo appena concluso (se c'e'), svuota
    SUBITO il tracciamento per il ciclo successivo, poi lo rivalida da capo e
    prova l'offerta. Se non c'e' nessun candidato, o se fallisce un controllo,
    salta semplicemente il giro -- il timer riparte comunque."""
    global _periodic_bid_best
    while not _stop_periodic_bid.wait(PERIODIC_BID_INTERVAL_SECONDS):
        if INSUFFICIENT_FUNDS_STOP[0]:
            continue
        with _periodic_bid_lock:
            candidato = _periodic_bid_best
            _periodic_bid_best = None
        if candidato is None:
            log("[bid periodico] nessun candidato idoneo in questo ciclo, salto")
            continue
        try:
            _try_periodic_bid(candidato, eth_rate)
        except Exception as e:
            log(f"[bid periodico] eccezione non gestita, salto questo ciclo e continuo: {e}")


def main():
    eth_rate = get_eth_rate()
    log(f"Tasso ETH/EUR: {eth_rate}")
    autobuy_modalita = "ACQUISTO REALE ATTIVO" if AUTOBUY_LIVE_MODE else "solo diagnostica"
    makeoffer_modalita = "OFFERTE REALI ATTIVE" if MAKEOFFER_LIVE_MODE else "solo diagnostica"
    log(f"Bot Supremo -- AutoBuy: {autobuy_modalita} | MakeOffer: {makeoffer_modalita}")
    log(f"[network] curl_cffi (impronta TLS Chrome) {'ATTIVO' if _HAS_CURL_CFFI else 'NON DISPONIBILE, uso requests standard'}")
    csrf_source = "estratto dal cookie (csrftoken=...)" if _extract_csrf_from_cookie(COOKIES) else "da secret SORARE_CSRF (fallback)"
    log(f"[auth] CSRF token in uso: {csrf_source}, valore: {(CSRF_TOKEN or '')[:20]}...")
    log(f"Fascia prezzo {AUTOBUY_MIN_PRICE_EUR:.2f}-{AUTOBUY_MAX_PRICE_EUR:.2f}EUR, "
        f"MakeOffer {MAKEOFFER_MARGIN_FRACTION:.0%}-{MAKEOFFER_MAX_MARGIN_FRACTION:.0%}, "
        f"AutoBuy >= {AUTOBUY_MARGIN_FRACTION:.0%}, target casi da trovare: {AUTOBUY_TARGET_MATCHES}")
    log(f"Giocatori in blacklist unita ({len(BLACKLISTED_PLAYER_SLUGS)}): "
        f"{sorted(BLACKLISTED_PLAYER_SLUGS)}")
    log(f"Manager in blacklist unita ({len(BLACKLISTED_MANAGER_SLUGS)}): "
        f"{sorted(BLACKLISTED_MANAGER_SLUGS)}")
    if AUTOBUY_LIVE_MODE or MAKEOFFER_LIVE_MODE:
        log("[playwright] pre-apertura browser all'avvio (ottimizzazione velocita')...")
        # FIX 22/07 v2: la creazione della pagina Playwright DEVE avvenire sullo
        # stesso thread dedicato che verra' riusato per ogni chiamata successiva
        # (vedi _run_on_browser_thread) -- altrimenti il browser nascerebbe sul
        # thread principale e le chiamate successive (dal thread dedicato)
        # fallirebbero comunque con "Cannot switch to a different thread".
        _run_on_browser_thread(get_browser_page)
        log("[playwright] browser pronto e riscaldato, in attesa di occasioni")

        # OTTIMIZZAZIONE VELOCITA' SNIPING: exchange_rate_id e la chiave cifrata del
        # wallet sono entrambe cachate in memoria per tutta la run (vedi
        # get_exchange_rate_id/fetch_encrypted_private_key) -- ma finora la CACHE
        # veniva popolata solo al PRIMO acquisto/offerta reale, cioe' proprio nel
        # momento in cui ogni millisecondo conta per battere altri bot sullo stesso
        # annuncio. Le pre-carichiamo qui, all'avvio (stesso principio del warm-up
        # del browser sopra), cosi' quando arriva il primo evento buono queste due
        # chiamate di rete sono gia' state fatte e la pipeline di acquisto/offerta
        # parte direttamente dal passo di firma, senza aspettarle. Nessuna modifica
        # alla logica di acquisto/decisione -- solo l'ordine in cui il lavoro
        # (comunque necessario) viene svolto.
        log("[precarico velocita'] recupero anticipato chiave cifrata del wallet...")
        # NOTA 21/07: exchange_rate_id NON viene piu' precaricato/cachato -- causava
        # 'exchange rate has expired' riusando lo stesso id gia' consumato su piu'
        # acquisti. Ora richiesto fresco ad ogni prepare_accept_offer.
        if SORARE_WALLET_PASSWORD:
            pre_key = fetch_encrypted_private_key()
            if pre_key:
                log("[precarico velocita'] chiave cifrata del wallet gia' in cache")
            else:
                log("[precarico velocita'] ATTENZIONE: precarico chiave cifrata fallito, "
                    "verra' ritentato al primo acquisto/offerta reale")
            # OTTIMIZZAZIONE VELOCITA' (21/07): avviamo qui anche il processo Node
            # persistente per la firma (sorare-sign/decrypt_and_sign.js), invece di
            # lasciare che parta al primo acquisto/offerta reale -- l'avvio di Node
            # e il caricamento di @sorare/crypto costano qualche centinaio di
            # millisecondi, e non vogliamo pagarli proprio mentre stiamo
            # competendo con altri bot sullo stesso annuncio.
            with _node_process_lock:
                _ensure_node_sign_process()
            log("[precarico velocita'] processo Node persistente per la firma avviato "
                "e pronto (restera' vivo per tutta la run)")
        else:
            log("[precarico velocita'] SORARE_WALLET_PASSWORD non impostata, salto il "
                "precarico della chiave cifrata e del processo Node di firma")
    if not validate_live_offers_schema():
        log("STOP: self-check dello schema GraphQL fallito, esco senza avviare l'ascolto "
            "(evita ore di ascolto a vuoto senza mai trovare un caso valido).")
        return
    send_startup_msg()
    commit_thread = threading.Thread(target=_periodic_commit_loop, daemon=True)
    commit_thread.start()
    log(f"[commit periodico] thread avviato, commit+push lista nera ogni "
        f"{COMMIT_INTERVAL_SECONDS}s se ci sono modifiche")
    periodic_bid_thread = threading.Thread(target=_periodic_bid_loop, args=(eth_rate,), daemon=True)
    periodic_bid_thread.start()
    log(f"[bid periodico] thread avviato -- ogni {PERIODIC_BID_INTERVAL_SECONDS}s, "
        f"attivo={PERIODIC_BID_ENABLED}")
    try:
        matches_found = run_listener(eth_rate)
        target_reached = matches_found >= AUTOBUY_TARGET_MATCHES
        send_end_msg(matches_found, target_reached)
        if target_reached:
            log(f"Target raggiunto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi trovati e "
                f"notificati -- esecuzione terminata.")
        else:
            log(f"Tempo di ascolto scaduto: {matches_found}/{AUTOBUY_TARGET_MATCHES} casi "
                f"trovati -- esecuzione terminata.")
    finally:
        _stop_periodic_commit.set()
        _stop_periodic_bid.set()
        _commit_lista_nera_se_serve()  # ultimo commit sincrono, cattura eventuali modifiche recenti
        # FIX 22/07 v2: chiusura anch'essa sullo stesso thread dedicato -- tocca
        # gli stessi oggetti Playwright creati li'.
        _run_on_browser_thread(close_browser)
        _browser_executor.shutdown(wait=True)
        close_node_sign_process()


if __name__ == "__main__":
    main()
