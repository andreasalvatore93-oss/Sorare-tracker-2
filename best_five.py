"""
best_five.py (30/07, prototipo — vedi memoria project_backlog_best_five_funzione.md)

Per UNA lega scelta, trova la miglior formazione POSSIBILE scegliendo tra
TUTTE le carte disponibili nella lega (pool GLOBALE della discovery, non
solo i posseduti), con N candidati di backup per ogni ruolo (nel caso il
titolare scelto non scenda in campo quella giornata).

Script SEPARATO e READ-ONLY rispetto alla pipeline di produzione
(formazione_giornata.yml): riusa test_<ruolo>.py COSI' COM'E' come
libreria/processo esterno (subprocess), zero duplicazione della logica di
calcolo dello score_atteso. Non tocca budget/anti-stack/sinergie/multi-
lineup — quello resta specifico delle formazioni REALI sui posseduti
(build_formazione_finale.py).

Richiede che la lega scelta abbia gia' una discovery GLOBALE completa per
tutti e 4 i ruoli (oggi: mls, kleague, germania) — vedi
formazione_<lega>/output/<lega>_<ruolo>_discovery_global/player_slugs.json.

Uso:
  python best_five.py kleague              # usa l'ultimo output gia' presente per ogni ruolo (se c'e')
  python best_five.py kleague --run         # ri-esegue la predizione per ogni ruolo, poi rankinga
  python best_five.py kleague --run --backups 2   # 1 titolare + 2 backup per ruolo (default: 2 backup)
  python best_five.py kleague --run --roles mid,fwd   # solo sui ruoli indicati

Con --run (30/07 sera, ottimizzazione tempi): per ogni ruolo, il pool
GLOBALE della lega (gia' filtrato per qualita' >= 30 a monte, in
discovery_global) viene ulteriormente filtrato con una query leggera
starterOdds sulla prossima partita (soglia BEST_FIVE_MIN_STARTER_ODDS,
default 0.70, decisa esplicitamente dall'utente) PRIMA della predizione
costosa. Solo i sopravvissuti vengono passati a test_<ruolo>.py, UN
subprocess per giocatore (TARGET_SLUG, stile job matrix della pipeline di
produzione) invece che un unico subprocess sull'intero pool.

Il ranking usa lo stesso ORDINAMENTO (score senza shrinkage, dove
disponibile) gia' calcolato e stampato da ciascun test_<ruolo>.py —
nessuna logica di scoring duplicata qui, solo parsing + selezione top N.
Per compatibilita' con risultati gia' generati in modalita' "pool intero"
(es. GK/DEF K League del 30/07, un solo file prediction_all_*.txt per
ruolo), quel formato resta supportato e ha precedenza se presente.
"""
import os
import sys
import re
import json
import glob
import time
import base64
import subprocess
import datetime
import importlib.util

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
    import requests

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

GRAPHQL_URL = 'https://api.sorare.com/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')
_http_session = curl_requests.Session(impersonate="chrome") if _HAS_CURL_CFFI else requests.Session()

# Soglia starterOdds decisa esplicitamente dall'utente (30/07): sotto il 70%
# un giocatore e' "piu' rischioso e comunque non lo sceglierebbe" -- quindi
# filtrarlo PRIMA della predizione costosa non perde candidati che l'utente
# avrebbe scelto comunque. Il pool su cui si applica e' gia' filtrato per
# qualita' (media L5/L10/L40 >= 30) a monte, in discovery_global.
MIN_STARTER_ODDS_PREFILTER = float(os.environ.get('BEST_FIVE_MIN_STARTER_ODDS', '0.70'))

# Top-N esclusi per ruolo (31/07, richiesta esplicita utente): oltre alle
# formazioni intere generate, mostra sempre anche i migliori N candidati
# eleggibili (sopravvissuti al prefiltro starterOdds) MAI schierati in
# nessuna formazione -- utile soprattutto quando si chiedono molte
# formazioni (n_backup alto) e un ruolo scarso (es. i portieri di una lega
# piccola) esaurisce il pool prima degli altri: la lista dice comunque chi
# altro sarebbe stato eleggibile, invece di far sembrare il pool piu'
# povero di quanto sia davvero.
TOP_N_ESCLUSI = int(os.environ.get('BEST_FIVE_TOP_N_ESCLUSI', '10'))

# Cap per qualita' PRIMA delle starterOdds (30/07, richiesta esplicita
# utente: "implementa cap qualita'" -- riduzione ulteriore, sopra alla
# parallelizzazione gia' fatta, del numero di query starterOdds necessarie).
# Tiene solo i top-K per ruolo secondo la media L5/L10/L40 gia' persistita in
# player_quality.json (nessuna chiamata API aggiuntiva, il valore era gia'
# calcolato per il filtro qualita' di discovery_global). 0 o negativo =
# disattivato (comportamento precedente, pool intero). Se player_quality.json
# non esiste ancora (discovery non ancora rilanciata dopo l'aggiunta di
# questo file), il cap non si applica -- MAI un'esclusione silenziosa per
# dato mancante.
BEST_FIVE_TOP_K_QUALITA = int(os.environ.get('BEST_FIVE_TOP_K_QUALITA', '40'))

NEXT_MATCH_STARTER_ODDS_QUERY = """
query NextMatchStarterOdds($slug: String!) {
  anyPlayer(slug: $slug) {
    anyFutureGames(first: 1) {
      nodes {
        playerGameScore(playerSlug: $slug) {
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints reliability }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_next_match_starter_odds(slug):
    """Query leggera (nessuno storico, nessun game log) per lo starterOdds
    della prossima partita di un giocatore. Ritorna un float 0-1, o None se
    non disponibile (nessuna partita futura fissata, dato mancante, o
    fallimento della query dopo i retry)."""
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if COOKIES:
        headers['Cookie'] = COOKIES
    payload = {'query': NEXT_MATCH_STARTER_ODDS_QUERY, 'variables': {'slug': slug},
               'operationName': 'NextMatchStarterOdds'}

    backoff = 1.0
    for attempt in range(3):
        try:
            resp = _http_session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                log(f"[starterOdds] {slug}: HTTP {resp.status_code}, salto (trattato come dato mancante).")
                return None
            data = resp.json()
            nodes = (((data.get('data') or {}).get('anyPlayer') or {}).get('anyFutureGames') or {}).get('nodes') or []
            if not nodes:
                return None
            pgs = nodes[0].get('playerGameScore') or {}
            odds = ((pgs.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
            bp = odds.get('starterOddsBasisPoints')
            return bp / 10000.0 if bp is not None else None
        except Exception as e:
            log(f"[starterOdds] {slug}: eccezione tentativo {attempt+1}/3: {e!r}")
            time.sleep(backoff)
            backoff *= 2
    return None

# ruolo -> nome file script in formazione_<lega>/predict/
ROLE_SCRIPTS = {
    'gk': 'test_gk.py',
    'def': 'test_def.py',
    'mid': 'test_mid.py',
    'fwd': 'test_mls_fwd_all.py',  # nome storico, riusato identico per tutte le leghe
}

ROLE_LABELS = {
    'gk': 'PORTIERE',
    'def': 'DIFENSORE',
    'mid': 'CENTROCAMPISTA',
    'fwd': 'ATTACCANTE',
}

# Leghe con discovery GLOBALE completa per tutti e 4 i ruoli (30/07).
# Aggiornare quando altre leghe completano la discovery globale su tutti i ruoli.
LEGHE_SUPPORTATE = ('mls', 'kleague', 'germania')

RIGA_GIOCATORE_RE = re.compile(r'^\d+\)\s+([\w\-]+):\s+(-?\d+)\s+pt attesi \((-?\d+)-(-?\d+)\)\s*$')
RIGA_ORDINAMENTO_RE = re.compile(r'^\s*ORDINAMENTO:\s*(-?\d+(?:\.\d+)?)\s*$')
RIGA_SQUADRA_RE = re.compile(r'^\s*SQUADRA:\s*(\S+)\s*\|\s*AVVERSARIO:\s*(\S+)\s*$')


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [best_five] {msg}")


def discovery_global_dir(lega, ruolo):
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', f'{lega}_{ruolo}_discovery_global')


def carica_pool_qualita_filtrato(lega, ruolo):
    """Legge player_slugs.json della discovery globale -- gia' filtrato per
    qualita' (media L5/L10/L40 >= soglia) a monte da filter_by_quality().
    In piu' (30/07): applica il CAP per qualita' (BEST_FIVE_TOP_K_QUALITA),
    tenendo solo i top-K per media L5/L10/L40 (player_quality.json, stesso
    valore gia' calcolato in discovery_global) -- riduce ulteriormente il
    numero di candidati che arrivano al controllo starterOdds."""
    path = os.path.join(discovery_global_dir(lega, ruolo), 'player_slugs.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Discovery globale non trovata per {ruolo}: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        slugs = json.load(f)

    if BEST_FIVE_TOP_K_QUALITA <= 0:
        return slugs

    quality_path = os.path.join(discovery_global_dir(lega, ruolo), 'player_quality.json')
    if not os.path.exists(quality_path):
        log(f"[{ruolo}] player_quality.json non trovato -- cap qualita' NON applicato "
            f"(serve rilanciare la discovery_global per generarlo), pool completo usato.")
        return slugs

    if len(slugs) <= BEST_FIVE_TOP_K_QUALITA:
        return slugs

    with open(quality_path, encoding='utf-8') as f:
        quality_map = json.load(f)
    slugs_ordinati = sorted(slugs, key=lambda s: quality_map.get(s, 0.0), reverse=True)
    scartati = len(slugs) - BEST_FIVE_TOP_K_QUALITA
    log(f"[{ruolo}] Cap qualita': tenuti i top {BEST_FIVE_TOP_K_QUALITA}/{len(slugs)} per media "
        f"L5/L10/L40 ({scartati} scartati prima del controllo starterOdds).")
    return slugs_ordinati[:BEST_FIVE_TOP_K_QUALITA]


def prefiltra_starter_odds(ruolo, slugs, soglia=MIN_STARTER_ODDS_PREFILTER):
    """Interroga la query leggera starterOdds per ciascuno slug e tiene solo
    chi ha odds >= soglia sulla prossima partita. Chi ha odds mancanti (nessuna
    partita futura fissata, dato non disponibile) viene ESCLUSO -- e' un dato
    ignoto tanto quanto uno basso, e l'utente non lo sceglierebbe comunque."""
    sopravvissuti = []
    for idx, slug in enumerate(slugs, 1):
        odds = fetch_next_match_starter_odds(slug)
        esito = f"{odds:.0%}" if odds is not None else "N/D"
        if odds is not None and odds >= soglia:
            sopravvissuti.append(slug)
            log(f"[{ruolo}] [{idx}/{len(slugs)}] {slug}: starterOdds={esito} -> TENUTO")
        else:
            log(f"[{ruolo}] [{idx}/{len(slugs)}] {slug}: starterOdds={esito} -> scartato (< {soglia:.0%})")
        time.sleep(0.3)
    return sopravvissuti


def run_prediction_su_slug(lega, ruolo, slug):
    """Esegue test_<ruolo>.py su UN SOLO giocatore (TARGET_SLUG), PLAYER_POOL=global
    cosi' DISCOVERY_FILE punta comunque al pool globale (serve solo per il
    fallback/coerenza interna dello script, il TARGET_SLUG bypassa la lista)."""
    script = ROLE_SCRIPTS[ruolo]
    script_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'predict', script)
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script non trovato: {script_path}")

    env = dict(os.environ)
    env['PLAYER_POOL'] = 'global'
    env['TARGET_SLUG'] = slug
    env.pop('CALIBRATION_MODE', None)

    proc = subprocess.run([sys.executable, script_path], cwd=REPO_ROOT, env=env)
    if proc.returncode != 0:
        log(f"[{ruolo}] ATTENZIONE: processo terminato con codice {proc.returncode} per {slug} "
            f"(procedo comunque con il prossimo).")


def run_prediction_pool_prefiltrato(lega, ruolo):
    """Carica il pool globale (gia' filtrato per qualita'), applica il
    prefiltro starterOdds>=soglia, poi lancia UN subprocess per slug
    sopravvissuto (stile job matrix della pipeline di produzione)."""
    pool = carica_pool_qualita_filtrato(lega, ruolo)
    log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
    log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} sulla prossima partita...")
    sopravvissuti = prefiltra_starter_odds(ruolo, pool)
    log(f"[{ruolo}] Sopravvissuti al prefiltro: {len(sopravvissuti)}/{len(pool)}.")

    for idx, slug in enumerate(sopravvissuti, 1):
        log(f"[{ruolo}] [{idx}/{len(sopravvissuti)}] Predizione per {slug}...")
        run_prediction_su_slug(lega, ruolo, slug)
        if idx < len(sopravvissuti):
            time.sleep(2.0)


def output_dir_per_ruolo(lega, ruolo):
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', f'{lega}_{ruolo}_all')


def trova_ultimo_output(lega, ruolo):
    """Trova il file prediction_all_*.txt piu' recente per il ruolo (formato
    VECCHIO, scritto da un'esecuzione sull'intero pool senza TARGET_SLUG —
    es. GK/DEF di questa lega, gia' committati prima del prefiltro
    starterOdds). Ritorna None se non esiste (ruolo mai eseguito in modalita'
    pool intero -- vedi trova_output_per_slug per il formato NUOVO)."""
    out_dir = output_dir_per_ruolo(lega, ruolo)
    candidati = glob.glob(os.path.join(out_dir, 'prediction_all_*.txt'))
    if not candidati:
        return None
    return max(candidati, key=os.path.getmtime)


def trova_output_per_slug(lega, ruolo):
    """Formato NUOVO (prefiltro starterOdds): un file prediction_<slug>_*.txt
    per ogni giocatore sopravvissuto al prefiltro, uno per subprocess (stile
    job matrix). Ritorna il piu' recente per ciascuno slug trovato."""
    out_dir = output_dir_per_ruolo(lega, ruolo)
    tutti = glob.glob(os.path.join(out_dir, 'prediction_*_*.txt'))
    per_slug = {}
    for path in tutti:
        base = os.path.basename(path)
        if base.startswith('prediction_all_'):
            continue
        m = re.match(r'^prediction_(.+)_\d{4}-\d{2}-\d{2}_\d{6}\.txt$', base)
        if not m:
            continue
        slug = m.group(1)
        if slug not in per_slug or os.path.getmtime(path) > os.path.getmtime(per_slug[slug]):
            per_slug[slug] = path
    return list(per_slug.values())


def parse_riepilogo(path):
    """Estrae dal riepilogo comparativo in cima al file la lista ordinata
    (stesso ORDINAMENTO gia' calcolato da test_<ruolo>.py) di
    (slug, pt_attesi, low, high, ordinamento, squadra, avversario)."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    righe = []
    corrente = None
    for line in testo.splitlines():
        m = RIGA_GIOCATORE_RE.match(line)
        if m:
            if corrente:
                righe.append(corrente)
            corrente = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        # Fine del blocco riepilogo (sezione esclusi o separatore finale) --
        # smette di cercare altre righe giocatore dopo la prima riga vuota
        # successiva a un blocco gia' iniziato, o alla sezione "Esclusi".
        if corrente is not None:
            m2 = RIGA_ORDINAMENTO_RE.match(line)
            if m2:
                corrente['ordinamento'] = float(m2.group(1))
                continue
            m3 = RIGA_SQUADRA_RE.match(line)
            if m3:
                corrente['squadra'] = m3.group(1)
                corrente['avversario'] = m3.group(2)
                continue
        if line.startswith('--- Esclusi') or line.startswith('#' * 10):
            break
    if corrente:
        righe.append(corrente)

    # Si ordina sempre per pt_attesi (score MOSTRATO, con shrinkage) --
    # ALLINEATO alla produzione (30/07, "Revert score_ordinamento": il
    # ranking per ORDINAMENTO senza shrinkage duplicato qui aveva prodotto
    # proprio il caso reale che ha fatto scattare il revert, un DEF con 4
    # partite preferito a due backup piu' stabili). Il campo 'ordinamento'
    # resta nel dizionario solo per diagnostica, non entra piu' nel sort.
    righe.sort(key=lambda r: r['pt_attesi'], reverse=True)
    return righe


def parse_file_singolo_slug(path):
    """Estrae la singola riga consiglio da un file prediction_<slug>_*.txt
    (formato NUOVO, un giocatore per file) -- stesso schema di riga di
    parse_riepilogo, riusa le stesse regex."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    riga = None
    for line in testo.splitlines():
        m = RIGA_GIOCATORE_RE.match(line)
        if m:
            riga = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        if riga is not None:
            m2 = RIGA_ORDINAMENTO_RE.match(line)
            if m2:
                riga['ordinamento'] = float(m2.group(1))
                continue
            m3 = RIGA_SQUADRA_RE.match(line)
            if m3:
                riga['squadra'] = m3.group(1)
                riga['avversario'] = m3.group(2)
                continue
            break  # dopo la prima riga giocatore, il resto e' il dump completo -- basta cosi'
    return riga


# ruolo -> nome file script in formazione_<lega>/consiglio/
CONSIGLIO_SCRIPTS = {
    'gk': 'build_consiglio_gk.py',
    'def': 'build_consiglio_def.py',
    'mid': 'build_consiglio_mid.py',
    'fwd': 'build_consiglio.py',  # nome storico (FWD), stesso di ROLE_SCRIPTS['fwd']
}

CONSIGLIO_RIGA_RE = re.compile(r'^\d+\)\s+([\w\-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')

_SLUG_DA_FILENAME_RE = re.compile(r'^prediction_(.+)_\d{4}-\d{2}-\d{2}_\d{6}\.txt$')


def _sopravvissuti_run_corrente():
    """Lista {'ruolo','slug'} sopravvissuta al prefiltro starterOdds di
    QUESTO run (passata dal job 'prefiltro_merge' via env PREFILTRO_GRUPPI,
    stesso JSON dei gruppi mandati al predict -- vedi _gruppi_da_items).
    None se non impostata (uso manuale/locale, nessun filtro extra).

    FIX BUG REALE (30/07, segnalato dall'utente): senza questo controllo,
    slugs_con_prediction prendeva QUALUNQUE prediction_<slug>_*.txt gia'
    presente nella cartella -- condivisa con la pipeline di produzione, che
    scrive li' le SUE predizioni per i posseduti, a QUALUNQUE starterOdds
    (test_<ruolo>.py non filtra per starterOdds, MIN_STARTER_ODDS e'
    disattivato li'). Risultato osservato: due giocatori con starterOdds
    30% e 70% finiti nella formazione nonostante soglia=80%, perche' un
    file prediction_<slug>_*.txt per loro esisteva gia' (da un run
    precedente, non necessariamente di Best Five) e veniva ripescato senza
    ricontrollare la soglia DI QUESTO run."""
    raw = os.environ.get('PREFILTRO_GRUPPI', '').strip()
    if not raw:
        return None
    try:
        gruppi = json.loads(raw)
    except json.JSONDecodeError:
        log("ATTENZIONE: PREFILTRO_GRUPPI non e' JSON valido, ignorato (nessun filtro extra).")
        return None
    items = []
    for g in gruppi:
        items.extend(json.loads(base64.b64decode(g['g']).decode()))
    return items


def slugs_con_prediction(lega, ruolo):
    """Slug per cui esiste almeno un prediction_<slug>_*.txt (formato NUOVO,
    un file per giocatore) -- l'insieme da passare a build_consiglio_<ruolo>.py
    via CONSIGLIO_DISCOVERY_FILE. Se PREFILTRO_GRUPPI e' impostata (run da
    workflow), filtra ANCHE per chi ha davvero superato il prefiltro
    starterOdds DI QUESTO run (vedi _sopravvissuti_run_corrente)."""
    slugs = []
    for path in trova_output_per_slug(lega, ruolo):
        m = _SLUG_DA_FILENAME_RE.match(os.path.basename(path))
        if m:
            slugs.append(m.group(1))

    sopravvissuti = _sopravvissuti_run_corrente()
    if sopravvissuti is not None:
        ammessi = {it['slug'] for it in sopravvissuti if it['ruolo'] == ruolo}
        prima = len(slugs)
        slugs = [s for s in slugs if s in ammessi]
        scartati = prima - len(slugs)
        if scartati:
            log(f"[{ruolo}] {scartati} slug con prediction gia' su disco ma NON sopravvissuti al "
                f"prefiltro di questo run -- esclusi dalla formazione.")
    return sorted(slugs)


def esegui_consiglio(lega, ruolo):
    """Chiama DAVVERO build_consiglio_<ruolo>.py (lo stesso script della
    pipeline di produzione, in subprocess) invece di duplicare qui la logica
    di parsing/ordinamento -- zero drift quando quella cambia (30/07: la
    produzione ha cambiato il criterio di ordinamento DEF/FWD mentre questo
    file duplicava ancora quello vecchio, vedi 'Revert score_ordinamento').
    Punta CONSIGLIO_DISCOVERY_FILE ai soli slug del pool Best Five (non i
    posseduti) tramite un JSON temporaneo. Ritorna il path del
    consiglio_*.txt generato, o None se non ci sono predizioni per questo
    ruolo o lo script fallisce (in quel caso si ricade sul parsing diretto)."""
    slugs = slugs_con_prediction(lega, ruolo)
    if not slugs:
        return None
    script = CONSIGLIO_SCRIPTS.get(ruolo)
    script_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'consiglio', script or '')
    if not script or not os.path.exists(script_path):
        return None

    tmp_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five')
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    slugs_path = os.path.join(tmp_dir, f'_consiglio_slugs_{ruolo}.json')
    with open(slugs_path, 'w', encoding='utf-8') as f:
        json.dump(slugs, f)

    env = dict(os.environ)
    env['CONSIGLIO_DISCOVERY_FILE'] = slugs_path
    proc = subprocess.run([sys.executable, script_path], cwd=REPO_ROOT, env=env,
                           capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"[{ruolo}] ATTENZIONE: {script} ha fallito (codice {proc.returncode}): "
            f"{proc.stderr[-500:]} — ricado sul parsing diretto.")
        return None
    m = re.search(r'Salvato in:\s*(\S+)', proc.stdout)
    if not m:
        log(f"[{ruolo}] ATTENZIONE: {script} non ha stampato il path di output atteso "
            f"— ricado sul parsing diretto.")
        return None
    # Il path stampato e' relativo alla cwd del SUBPROCESS (REPO_ROOT), non
    # necessariamente alla cwd di QUESTO processo (es. nei test) -- risolto
    # esplicitamente per evitare un FileNotFoundError silenzioso.
    return os.path.join(REPO_ROOT, m.group(1))


def parse_consiglio_output(path):
    """Estrae il ranking gia' pronto (gia' ordinato da build_consiglio_<ruolo>.py
    -- NESSUN re-sort qui, l'ordine del file e' quello giusto)."""
    with open(path, 'r', encoding='utf-8') as f:
        testo = f.read()

    righe = []
    corrente = None
    for line in testo.splitlines():
        m = CONSIGLIO_RIGA_RE.match(line.strip())
        if m:
            if corrente:
                righe.append(corrente)
            corrente = {
                'slug': m.group(1),
                'pt_attesi': int(m.group(2)),
                'low': int(m.group(3)),
                'high': int(m.group(4)),
                'ordinamento': None,
                'squadra': None,
                'avversario': None,
            }
            continue
        if corrente is not None:
            m2 = RIGA_SQUADRA_RE.match(line)
            if m2:
                corrente['squadra'] = m2.group(1)
                corrente['avversario'] = m2.group(2)
                continue
        if line.startswith('(') and 'esclusi' in line:
            break
    if corrente:
        righe.append(corrente)
    return righe


def costruisci_best_five(lega, ruoli, n_backup):
    risultati = {}
    for ruolo in ruoli:
        path_all = trova_ultimo_output(lega, ruolo)
        # Il formato VECCHIO (pool intero) ha la PRECEDENZA solo se e'
        # davvero il piu' recente -- FIX (30/07, bug reale segnalato
        # dall'utente): senza questo confronto, un run FRESCO in formato
        # NUOVO (es. GK/DEF ricalcolati oggi) veniva scartato in favore di un
        # prediction_all_*.txt vecchio di ore, perche' il vecchio formato
        # aveva sempre la precedenza a prescindere dall'eta'. Le starterOdds
        # cambiano di continuo, un risultato di ore fa non va bene per un
        # uso ripetuto nel tempo (non solo "oggi").
        per_slug_paths = trova_output_per_slug(lega, ruolo)
        piu_recente_per_slug = max((os.path.getmtime(p) for p in per_slug_paths), default=None)
        if path_all and piu_recente_per_slug is not None and piu_recente_per_slug > os.path.getmtime(path_all):
            log(f"[{ruolo}] Formato pool intero ({os.path.basename(path_all)}) piu' vecchio "
                f"dei risultati per-slug piu' recenti -- ignorato, uso quelli freschi.")
            path_all = None
        consiglio_path = None if path_all else esegui_consiglio(lega, ruolo)
        if path_all:
            # Formato VECCHIO (pool intero, es. GK/DEF K League gia'
            # committati prima del prefiltro starterOdds) -- parse_riepilogo
            # ordina comunque per pt_attesi, vedi sopra.
            righe = parse_riepilogo(path_all)
            log(f"[{ruolo}] {len(righe)} giocatori trovati nel riepilogo di {os.path.basename(path_all)} "
                f"(formato pool intero).")
        elif consiglio_path:
            righe = parse_consiglio_output(consiglio_path)
            log(f"[{ruolo}] {len(righe)} giocatori trovati nel consiglio prodotto da "
                f"{CONSIGLIO_SCRIPTS[ruolo]} (delegato alla produzione, zero logica duplicata).")
        else:
            # Fallback: build_consiglio_<ruolo>.py non disponibile/fallito --
            # parsing diretto dei file per-slug, sort per pt_attesi (allineato
            # comunque al criterio attuale di produzione, vedi parse_riepilogo).
            paths = trova_output_per_slug(lega, ruolo)
            righe = [r for r in (parse_file_singolo_slug(p) for p in paths) if r]
            righe.sort(key=lambda r: r['pt_attesi'], reverse=True)
            log(f"[{ruolo}] {len(righe)} giocatori trovati in {len(paths)} file prediction_<slug>_*.txt "
                f"(fallback, parsing diretto).")
        if not righe:
            log(f"[{ruolo}] Nessun output trovato in {output_dir_per_ruolo(lega, ruolo)} "
                f"— esegui con --run per generarlo.")
        risultati[ruolo] = righe[:1 + n_backup]
    return risultati


def formatta_report(lega, risultati, n_backup):
    lines = []
    lines.append("=" * 70)
    lines.append(f"BEST FIVE — {lega.upper()} (titolare + {n_backup} backup per ruolo)")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("Pool: TUTTI i giocatori della lega (discovery globale), non solo posseduti.")
    lines.append("=" * 70)
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        candidati = risultati.get(ruolo, [])
        lines.append("")
        lines.append(f"--- {ROLE_LABELS[ruolo]} ---")
        if not candidati:
            lines.append("  (nessun dato disponibile)")
            continue
        for idx, c in enumerate(candidati):
            ruolo_str = "TITOLARE" if idx == 0 else f"BACKUP {idx}"
            lines.append(f"  [{ruolo_str}] {c['slug']}: {c['pt_attesi']} pt attesi "
                         f"({c['low']}-{c['high']}) | squadra={c['squadra'] or 'N/D'} "
                         f"avversario={c['avversario'] or 'N/D'}")
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


# Stessi colori per ruolo del generatore formazioni principale
# (formazione_mls/build_formazione_finale.py, ROLE_COLORS_HTML) — coerenza
# visiva tra i due report HTML.
ROLE_COLORS_HTML = {'gk': '#8b7cf6', 'def': '#3aa1e8', 'mid': '#2fbf8f', 'fwd': '#ef5b5b'}

HTML_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #0a0d12; --surface: #131a23; --surface-2: #1c2530;
    --text: #edf1f6; --muted: #8a93a6; --gold: #f4c542; --border: rgba(255,255,255,0.08);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f3f4f7; --surface: #ffffff; --surface-2: #eef0f4;
      --text: #1a2029; --muted: #5b6474; --border: rgba(20,25,35,0.08);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
    padding: 40px 24px 64px; max-width: 900px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 6px; }}
  .subhead {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 32px; }}
  /* Layout A RIGA (30/07, richiesta esplicita utente): i 4 ruoli affiancati
     in un'unica riga -- stessa struttura orizzontale della formazione vera
     (formazione_mls/build_formazione_finale.py, .lineup-row/.card-strip),
     non piu' una sezione per ruolo impilata verticalmente. */
  .formazione-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .ruolo-colonna {{ flex: 1 1 200px; min-width: 180px; }}
  .role-title {{
    font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--role-color); margin-bottom: 10px;
  }}
  .pcard {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px; position: relative; margin-bottom: 8px;
  }}
  .pcard.titolare {{ border-color: var(--role-color); box-shadow: 0 0 0 1px var(--role-color); }}
  .pcard.backup {{ padding: 8px 10px; }}
  .pcard-tag {{
    font-size: 0.55rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--role-color); margin-bottom: 6px;
  }}
  .pcard.backup .pcard-tag {{ margin-bottom: 2px; }}
  .pcard-name {{ font-size: 0.8rem; font-weight: 650; line-height: 1.25; margin-bottom: 6px; }}
  .pcard.backup .pcard-name {{ font-size: 0.72rem; margin-bottom: 2px; }}
  .pcard-score {{ font-size: 1.3rem; font-weight: 800; color: var(--role-color); font-variant-numeric: tabular-nums; }}
  .pcard.backup .pcard-score {{ font-size: 0.9rem; }}
  .pcard-range {{ font-size: 0.62rem; color: var(--muted); margin-bottom: 6px; }}
  .pcard.backup .pcard-range {{ margin-bottom: 0; }}
  .pcard-match {{ font-size: 0.66rem; color: var(--text); opacity: 0.8; line-height: 1.3; }}
  .pcard.backup .pcard-match {{ display: none; }}
  .empty {{ color: var(--muted); font-size: 0.8rem; }}
  .footer {{ margin-top: 32px; color: var(--muted); font-size: 0.72rem; }}
</style>
</head>
<body>
<h1>{page_title}</h1>
<p class="subhead">{page_subhead}</p>
<div class="formazione-row">
{colonne_ruolo}
</div>
<p class="footer">{footer}</p>
</body>
</html>
"""


def _card_html(c, ruolo, is_titolare):
    tag = "TITOLARE" if is_titolare else "BACKUP"
    color = ROLE_COLORS_HTML[ruolo]
    match = f"{c['squadra'] or 'N/D'} vs {c['avversario'] or 'N/D'}"
    classe = "pcard titolare" if is_titolare else "pcard backup"
    return (
        f'<div class="{classe}" style="--role-color:{color}">'
        f'<div class="pcard-tag">{tag}</div>'
        f'<div class="pcard-name">{c["slug"]}</div>'
        f'<div class="pcard-score">{c["pt_attesi"]}</div>'
        f'<div class="pcard-range">{c["low"]}-{c["high"]} pt attesi</div>'
        f'<div class="pcard-match">{match}</div>'
        f'</div>'
    )


def formatta_report_html(lega, risultati, n_backup):
    colonne = []
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        candidati = risultati.get(ruolo, [])
        color = ROLE_COLORS_HTML[ruolo]
        cards = "".join(_card_html(c, ruolo, idx == 0) for idx, c in enumerate(candidati))
        body = cards if candidati else '<p class="empty">Nessun dato disponibile.</p>'
        colonne.append(
            f'<div class="ruolo-colonna">'
            f'<div class="role-title" style="--role-color:{color}">{ROLE_LABELS[ruolo]}</div>'
            f'{body}'
            f'</div>'
        )

    page_title = f"Best Five — {lega.upper()}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"titolare + {n_backup} backup per ruolo, pool TUTTI i giocatori "
                     f"della lega (discovery globale, non solo posseduti).")
    footer = ("Script separato e READ-ONLY rispetto alla pipeline di produzione — non tiene conto "
              "di budget/anti-stack/sinergie/multi-lineup.")
    return HTML_TEMPLATE.format(page_title=page_title, page_subhead=page_subhead,
                                 colonne_ruolo="\n".join(colonne), footer=footer)


# --- Formazione VERA (30/07, richiesta esplicita utente: "voglio la miglior
# formazione con sinergie/combinazioni come fa il tool unificato, non un
# elenco top-5 per ruolo") ---------------------------------------------
#
# FIX 31/07 (audit di allineamento, richiesto dall'utente prima di fidarsi
# dei risultati): questa funzione chiamava PRIMA bff.generate_lineups_for_type
# di formazione_mls/build_formazione_finale.py -- che il file STESSO segnala
# in un commento (righe ~1748) come "!!! NON USATA IN PRODUZIONE (accertato
# 31/07, audit completo) !!!": tre parametri diversi da quelli reali per le
# formazioni IN_SEASON --
#   - variance_mode=True sempre (produzione: False per MLS/KLEAGUE_IN_SEASON,
#     VARIANCE_MODE_TYPES le esclude esplicitamente)
#   - apply_positive_synergy=True sulla prima formazione quando ne sono
#     richieste 2+ (produzione: SEMPRE False per le In Season)
#   - synergy_bonus_dict=IN_SEASON_SYNERGY_BONUS_BY_PAIR passato esplicito
#     (produzione non lo passa MAI -- vedi commento IN_SEASON_SYNERGY_
#     BONUS_BY_PAIR "NON USATA IN PRODUZIONE")
# Risultato: Best Five poteva scegliere/ordinare i candidati in modo diverso
# da quello che il tool unificato sceglierebbe DAVVERO con lo stesso pool.
#
# Ora si riusa DAVVERO l'orchestratore di produzione (generatore_formazioni/
# build_formazione_globale.py, lo stesso file che gira in
# formazione_giornata.yml) importato dinamicamente come modulo a se' --
# stessa tecnica di importlib gia' usata li' per formazione_mls/build_
# formazione_finale.py. Si chiama la SUA generate_lineups_for_type(tipo,
# count, role_data, pools, card_pool) con tipo='MLS_IN_SEASON'/'KLEAGUE_
# IN_SEASON' (leghe dedicate) o l'Arena dedicata della lega per le altre --
# stessi nomi di tipo, stessi dizionari (L10_CAP_BY_TYPE, STACK_GUARD_TYPES,
# VARIANCE_MODE_TYPES, CHECK_CAP260_TYPES, XP_BONUS_TYPES,
# CAPTAIN_BONUS_BY_TYPE) che leggerebbe la pipeline reale. Il rendering
# (format_lineup/render_lineup_html) usa lo STESSO'bff' interno al modulo
# 'gg' (non un'istanza separata) perche' e' li' che generatore_formazioni/
# build_formazione_globale.py registra CAPTAIN_BONUS_BY_TYPE['MLS_IN_SEASON']
# ecc. (build_formazione_finale.py da solo conosce solo 'IN_SEASON').
#
# La differenza con la produzione resta SOLO nella CardPool: invece delle
# copie REALMENTE possedute (da player_card_counts.json), si passa una
# CardPool VUOTA (CardPool({}, names=...)) -- CardPool._total_for() ripiega
# gia' da solo su 1 copia IN_SEASON virtuale per qualunque slug non
# presente nei counts, quindi ogni giocatore del pool globale risulta
# "posseduto" con 1 copia, senza scrivere nessun dato finto. Stesso
# meccanismo per il bonus XP: power_bonus_fraction() ritorna 0.0 senza un
# breakdown noto -- coerente con la richiesta precedente dell'utente di
# vedere lo score GREZZO, senza bonus (vedi messaggio 30/07 alla sessione
# "Riassunto evoluzione modello predittivo"), e comunque IDENTICO a come la
# produzione mostra il numero (apply_xp_bonus=False SOLO nel rendering,
# vedi FASE 2 di build_formazione_globale.py).

def _import_gg():
    path = os.path.join(REPO_ROOT, 'generatore_formazioni', 'build_formazione_globale.py')
    spec = importlib.util.spec_from_file_location('gg_best_five', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registra_tipo_arena(gg, lega):
    """FIX (31/07, bug reale: KeyError 'AUSTRIA_ARENA' su una lega che NON e'
    tra le ARENA_LEAGUES di produzione -- quella lista e' una tupla fissa di
    slug scelti dall'utente per le leghe con Arena dedicata VERA su Sorare,
    non tutte le leghe con una pipeline attiva. Per Best Five (che deve poter
    generare un pool globale per QUALUNQUE lega con discovery_global, non
    solo quelle gia' promosse ad Arena dedicata), se il tipo Arena non esiste
    ancora lo registra qui a runtime con gli stessi identici parametri
    standard di un'Arena dedicata (cap L10 260 obbligatorio, capitano +20%,
    variance_mode attivo, nessun bonus XP/cap260/stack-guard -- stesso
    trattamento di build_formazione_globale.py per ARENA_LEAGUES). Nessun
    impatto su produzione: 'gg' qui e' sempre un'istanza importata a parte
    (vedi _import_gg), mai quella del workflow reale."""
    tipo = gg.arena_type(lega)
    if tipo in gg.FORMATION_SHAPES:
        return tipo  # gia' una vera Arena dedicata di produzione, nulla da fare
    gg.FORMATION_SHAPES[tipo] = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
                                  'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None}
    gg.POOL_LEAGUE_BY_TYPE[tipo] = lega
    gg.LABELS[tipo] = f'Arena {lega.capitalize()} (cap 260)'
    gg.L10_CAP_BY_TYPE[tipo] = 260.0
    gg.VARIANCE_MODE_TYPES.add(tipo)
    gg.bff.CAPTAIN_BONUS_BY_TYPE[tipo] = 0.2
    return tipo


def _tipo_per_lega(gg, lega):
    """Nome del tipo FORMATION_SHAPES di produzione per la lega scelta:
    'MLS_IN_SEASON'/'KLEAGUE_IN_SEASON' per le due leghe dedicate (stessa
    competizione In Season che gioca l'utente), l'Arena dedicata (cap L10
    260 obbligatorio) per qualunque altra lega -- non esiste un tipo
    'In Season' generico per le leghe non dedicate in produzione. Se la lega
    non ha ancora un'Arena dedicata VERA in produzione (es. Austria/
    2.Bundesliga, usate qui solo come fonte dati per Contender), ne registra
    una ad-hoc (vedi _registra_tipo_arena)."""
    if lega in gg.DEDICATED_LEAGUES:
        return f'{lega.upper()}_IN_SEASON'
    return _registra_tipo_arena(gg, lega)


def costruisci_formazione_vera(lega, count):
    """Genera fino a 'count' formazioni (GK/DEF/MID/FWD/EXTRA, con
    sinergie/anti-stack/captain -- IDENTICO al tool unificato, stessa
    funzione di produzione richiamata qui) sul pool GLOBALE della lega. Il
    conteggio 'count' fa le veci del vecchio 'n_backup': con la CardPool
    sintetica (1 copia virtuale a testa) la 2a/3a formazione non puo'
    riusare un giocatore gia' schierato nella 1a, quindi sono
    automaticamente alternative complete con giocatori diversi -- lo
    stesso ruolo di "backup" di prima, ma a livello di formazione intera
    invece che di singolo slot.

    Richiede che i consiglio_*.txt esistano gia' per tutti e 4 i ruoli
    (li scrive esegui_consiglio, chiamato qui per ciascun ruolo)."""
    gg = _import_gg()
    bff = gg.bff  # STESSA istanza usata da produzione per registrare CAPTAIN_BONUS_BY_TYPE/CAP260 ecc.

    role_data_lega = {}
    for ruolo, ROLE in (('gk', 'GK'), ('def', 'DEF'), ('mid', 'MID'), ('fwd', 'FWD')):
        consiglio_path = esegui_consiglio(lega, ruolo)
        if consiglio_path and os.path.exists(consiglio_path):
            role_data_lega[ROLE] = bff.parse_consiglio(consiglio_path)
        else:
            log(f"[{ruolo}] Nessun consiglio disponibile, ruolo vuoto per la formazione vera.")
            role_data_lega[ROLE] = []

    mancanti = [r for r in gg.ROLES if not role_data_lega.get(r)]
    if mancanti:
        log(f"ATTENZIONE: ruoli senza candidati: {mancanti} — la formazione potrebbe non essere generabile.")

    # displayName reale Sorare (30/07, richiesta esplicita utente: "il nome
    # sulle carte deve essere il display name non lo slug"). LIMITE NOTO:
    # player_names.json esiste solo nella discovery POSSEDUTI (scritto da
    # discovery_fixture.py, che quando scansiona i roster raccoglie i nomi),
    # NON nella discovery_global usata dal pool Best Five -- quella script
    # oggi scarta il campo 'name' gia' presente nella query TeamRoster,
    # persiste solo gli slug (vedi kleague_gk_discovery_global.py). Quindi
    # oggi i nomi coprono solo i giocatori gia' visti dalla discovery
    # posseduti (in pratica: le tue carte + le squadre delle tue fixture),
    # non l'intero pool globale -- per chi manca, CardPool.display_name()
    # ripiega da solo sullo slug title-case (stesso fallback della
    # produzione). Coprire l'intero pool richiede di far persistere 'name'
    # anche a discovery_global (follow-up separato, non fatto qui).
    names = {}
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output',
                             f'{lega}_{ruolo}_discovery', 'player_names.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                names.update(json.load(f))

    card_pool = bff.CardPool({}, names=names)

    tipo = _tipo_per_lega(gg, lega)
    role_data = {lega: role_data_lega}
    pools = {lega: {role: gg._NoFilterPool(role, lega, role_data_lega[role]) for role in gg.ROLES}}

    # Chiamata DAVVERO alla generate_lineups_for_type di produzione (stessa
    # funzione che gira in formazione_giornata.yml) -- legge da soli i
    # dizionari L10_CAP_BY_TYPE/STACK_GUARD_TYPES/VARIANCE_MODE_TYPES/
    # CHECK_CAP260_TYPES/XP_BONUS_TYPES di 'gg' in base a 'tipo', nessun
    # parametro riscritto qui: se domani la produzione cambia un flag per
    # MLS_IN_SEASON/KLEAGUE_IN_SEASON, Best Five lo eredita automaticamente.
    all_results = gg.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
    generated, totale, lineup_blocks, lineup_html_blocks = _renderizza_risultati(bff, all_results, card_pool)

    testo_esclusi, html_esclusi = _blocco_top_esclusi(role_data_lega, card_pool)
    lineup_blocks.append(testo_esclusi)
    lineup_html_blocks.append(html_esclusi)

    log(f"Formazione vera: {generated}/{count} generate (pool globale, CardPool sintetica, "
        f"tipo={tipo}, stesso motore della produzione).")
    return bff, generated, totale, lineup_blocks, lineup_html_blocks


def _blocco_top_esclusi(role_data_per_ruolo, card_pool, n=TOP_N_ESCLUSI):
    """Top N candidati per ruolo (per 'atteso') MAI schierati in nessuna
    delle formazioni gia' generate -- stesso concetto del pannello 'esclusi'
    di generatore_formazioni/build_formazione_globale.py (card_pool.used_
    slugs()), qui SOLO per i ruoli/leghe di questa run di Best Five, non per
    l'intera pipeline di produzione. Ritorna (testo, html)."""
    used = card_pool.used_slugs()
    lines = ["", "=" * 70, f"TOP {n} ESCLUSI PER RUOLO (eleggibili per starterOdds, mai schierati)", "=" * 70]
    html_parts = ['<div class="esclusi-panel"><h3>Top %d esclusi per ruolo</h3>' % n]
    for ROLE in ('GK', 'DEF', 'MID', 'FWD'):
        rows = role_data_per_ruolo.get(ROLE, [])
        esclusi = sorted((r for r in rows if r['slug'] not in used),
                         key=lambda r: r.get('atteso', 0), reverse=True)[:n]
        lines.append(f"\n--- {ROLE} ---")
        html_parts.append(f'<div class="esclusi-role"><strong>{ROLE}</strong><ol>')
        if not esclusi:
            lines.append("  (nessuno)")
        for i, r in enumerate(esclusi, 1):
            squadra = r.get('team_slug') or 'N/D'
            lines.append(f"  {i}) {r['slug']}: {r.get('atteso')} pt (squadra={squadra})")
            html_parts.append(f"<li>{r['slug']}: {r.get('atteso')} pt (squadra={squadra})</li>")
        html_parts.append('</ol></div>')
    html_parts.append('</div>')
    return "\n".join(lines), "".join(html_parts)


def _renderizza_risultati(bff, all_results, card_pool):
    """Fattorizzato da costruisci_formazione_vera (31/07, riuso identico per
    costruisci_formazione_contender): trasforma i risultati di
    gg.generate_lineups_for_type in blocchi testo/HTML, STESSO rendering
    (format_lineup/render_lineup_html, apply_xp_bonus=False) usato dalla
    produzione in FASE 2 di build_formazione_globale.py."""
    lineup_blocks, lineup_html_blocks = [], []
    generated, totale = 0, 0
    for r in all_results:
        if 'error' in r:
            lineup_blocks.append(r['error'])
            lineup_html_blocks.append(f'<p class="error-block">{r["error"]}</p>')
            continue
        block_text, punti = bff.format_lineup(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'])
        lineup_blocks.append(block_text)
        lineup_html_blocks.append(bff.render_lineup_html(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'], apply_xp_bonus=False))
        generated += 1
        totale += punti
    return generated, totale, lineup_blocks, lineup_html_blocks


# --- "Contender" limitato a N leghe (31/07, richiesta esplicita utente) ----
#
# L'utente vuole Best Five per la competizione Sorare "Contender" (slug reale
# confermato via query live: eligibleSo5Competitions='seasonal-contenders',
# stesse regole di MLS/K League In Season: 5 titolari+2 riserve, min 4 carte
# In Season, capitano +50%), ma limitata SOLO a 3 campionati gia' tracciati
# (Austria, Croazia, 2.Bundesliga) invece che alle ~20 leghe reali che
# Contender raggruppa su Sorare -- una pipeline completa (nuova eleggibilita'
# trasversale nella discovery di produzione) resta backlog separato, vedi
# project_backlog_slug_contender.
#
# Qui NON si duplica la logica MLS_IN_SEASON/KLEAGUE_IN_SEASON: si registra
# un tipo 'CONTENDER_IN_SEASON' a runtime sulla PROPRIA istanza di 'gg'
# (import dinamico, non quella di produzione -- zero rischio per
# formazione_giornata.yml) e si passa da generate_lineups_for_type REALE con
# lo stesso trattamento di MLS/K League: IN_SEASON_TYPES.add(...) fa si' che
# in_season_multi/apply_positive_synergy=False si applichino automaticamente
# (vedi il refactor di build_formazione_globale.py, IN_SEASON_TYPES).
def _registra_tipo_in_season(gg, tipo, pool_league, label):
    gg.FORMATION_SHAPES[tipo] = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
                                  'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1}
    gg.POOL_LEAGUE_BY_TYPE[tipo] = pool_league
    gg.LABELS[tipo] = label
    gg.IN_SEASON_TYPES.add(tipo)
    gg.STACK_GUARD_TYPES.add(tipo)
    gg.CHECK_CAP260_TYPES.add(tipo)
    gg.XP_BONUS_TYPES.add(tipo)
    # gg.L10_CAP_BY_TYPE: NESSUNA voce per 'tipo' -- assenza = nessun cap
    # obbligatorio, corretto per un tipo In Season (a differenza delle Arene).
    # gg.VARIANCE_MODE_TYPES: NON aggiunto apposta -- stesso motivo per cui
    # MLS_IN_SEASON/KLEAGUE_IN_SEASON non ci sono (variance_mode=False per
    # le In Season, misurato irrilevante/rumoroso il 30-31/07).
    gg.bff.CAPTAIN_BONUS_BY_TYPE[tipo] = 0.5
    gg.bff.CAP260_L10_THRESHOLD_BY_TYPE[tipo] = 260.0


def costruisci_formazione_contender(leghe, count):
    """Best Five 'Contender' limitato alle leghe passate in 'leghe' (es.
    ['austria','croazia','germania2']): pool COMBINATO delle migliori carte
    globali di ciascuna, NESSUNA nuova query -- legge il consiglio_*.txt piu'
    recente gia' prodotto dal run Best Five NORMALE di ciascuna lega
    (formazione_<lega>/output/<lega>_<ruolo>_all/consiglio_*.txt, stessa
    formula di produzione di quella lega). Richiede che ciascuna lega abbia
    gia' un Best Five --run completato di recente per tutti e 4 i ruoli."""
    gg = _import_gg()
    bff = gg.bff
    tipo = 'CONTENDER_IN_SEASON'
    _registra_tipo_in_season(gg, tipo, 'contender', 'In Season Contender')

    merged_role_data = {ROLE: [] for ROLE in gg.ROLES}
    names = {}
    for lega in leghe:
        for ruolo, ROLE in (('gk', 'GK'), ('def', 'DEF'), ('mid', 'MID'), ('fwd', 'FWD')):
            out_dir = output_dir_per_ruolo(lega, ruolo)
            path = bff.latest_consiglio(out_dir)
            if not path:
                log(f"[{lega}/{ruolo}] Nessun consiglio_*.txt trovato in {out_dir} -- "
                    f"esegui prima 'python best_five.py {lega} --run' per questa lega.")
                continue
            rows = bff.parse_consiglio(path)
            for row in rows:
                row['league'] = lega
            merged_role_data[ROLE].extend(rows)
            log(f"[{lega}/{ruolo}] {len(rows)} giocatori da {os.path.basename(path)}.")
            # Nomi: preferenza al discovery_global (pool intero), fallback al
            # discovery posseduti (stesso schema di costruisci_formazione_vera).
            for names_dir in (f'{lega}_{ruolo}_discovery_global', f'{lega}_{ruolo}_discovery'):
                names_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', names_dir, 'player_names.json')
                if os.path.exists(names_path):
                    with open(names_path, encoding='utf-8') as f:
                        loaded = json.load(f)
                    for slug, nome in loaded.items():
                        names.setdefault(slug, nome)

    mancanti = [r for r in gg.ROLES if not merged_role_data.get(r)]
    if mancanti:
        log(f"ATTENZIONE: ruoli senza candidati nel pool Contender combinato: {mancanti}.")

    role_data = {'contender': merged_role_data}
    pools = {'contender': {role: gg._NoFilterPool(role, 'contender', merged_role_data[role]) for role in gg.ROLES}}
    card_pool = bff.CardPool({}, names=names)

    all_results = gg.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
    generated, totale, lineup_blocks, lineup_html_blocks = _renderizza_risultati(bff, all_results, card_pool)

    testo_esclusi, html_esclusi = _blocco_top_esclusi(merged_role_data, card_pool)
    lineup_blocks.append(testo_esclusi)
    lineup_html_blocks.append(html_esclusi)

    log(f"Formazione Contender (leghe: {', '.join(leghe)}): {generated}/{count} generate.")
    return bff, generated, totale, lineup_blocks, lineup_html_blocks


def rendi_carte_cliccabili(html_report):
    """Aggiunge un click-handler alle pcard del report (30/07, richiesta
    esplicita utente: "che mi rimandino proprio alla carta") che apre la
    pagina Sorare del giocatore in una nuova scheda -- stesso pattern URL
    gia' usato in produzione (scanners/bot_profit.py, _sorare_market_link,
    pagina PROFILO giocatore, non lo shop/mercato con filtro rarita': li' si
    vedono comunque le carte in vendita). Post-processing via <script>
    iniettato invece di modificare render_card_html/render_report_html in
    formazione_mls/build_formazione_finale.py -- quel file resta condiviso
    con la produzione (drag&drop tra formazioni reali), toccarlo per un
    comportamento SOLO di Best Five sarebbe rischioso. Le pcard hanno gia'
    'data-slug' (vedi render_card_html), qui si legge soltanto."""
    script = """
<script>
document.querySelectorAll('.pcard[data-slug]').forEach(function (card) {
  card.style.cursor = 'pointer';
  card.title = 'Apri su Sorare';
  card.addEventListener('click', function () {
    window.open('https://sorare.com/it/football/players/' + card.dataset.slug, '_blank', 'noopener');
  });
});
</script>
"""
    if '</body>' in html_report:
        return html_report.replace('</body>', script + '</body>')
    return html_report + script


# Tetto REALE di job concorrenti dell'account GitHub Actions (stesso valore
# di SLOT_CONCORRENTI in pipeline_artifacts.py, verificato sulla pipeline di
# produzione — vedi commento li' per i dettagli della misura).
SLOT_CONCORRENTI = 20


def raccogli_sopravvissuti(lega, ruoli):
    """Per ogni ruolo richiesto: pool gia' filtrato per qualita' + prefiltro
    starterOdds. Ritorna una lista PIATTA di {'ruolo': r, 'slug': s} su tutti
    i ruoli insieme (il job predict a matrice non distingue per ruolo, vedi
    bin_round_robin)."""
    sopravvissuti = []
    for ruolo in ruoli:
        pool = carica_pool_qualita_filtrato(lega, ruolo)
        log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
        log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} sulla prossima partita...")
        survived = prefiltra_starter_odds(ruolo, pool)
        log(f"[{ruolo}] Sopravvissuti al prefiltro: {len(survived)}/{len(pool)}.")
        sopravvissuti.extend({'ruolo': ruolo, 'slug': s} for s in survived)
    return sopravvissuti


def bin_round_robin(items, n_bin):
    """Distribuisce items in <= n_bin gruppi bilanciati per NUMERO (non per
    costo stimato: a differenza della pipeline di produzione, qui non c'e'
    ancora uno storico di costi misurati per giocatore -- vedi
    pipeline_costi.json/LPT in pipeline_artifacts.py per il modello completo,
    non replicato qui per semplicita', il pool e' molto piu' piccolo). Ordine
    round-robin invece che a blocchi, cosi' un ruolo piu' lento (es. MID,
    ~28s/giocatore contro i ~20s di FWD) non finisce concentrato in pochi bin."""
    if not items:
        return []
    n_bin = max(1, min(n_bin, len(items)))
    bins = [[] for _ in range(n_bin)]
    for i, item in enumerate(items):
        bins[i % n_bin].append(item)
    return [b for b in bins if b]


def _scrivi_gruppi_output(nome_var, gruppi):
    """Scrive 'nome_var=<json compatto>' su GITHUB_OUTPUT (se presente) e su
    stdout -- stesso formato per tutti gli step 'matrice' del workflow."""
    output_line = f'{nome_var}=' + json.dumps(gruppi, separators=(',', ':'))
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(output_line + '\n')
    print(output_line)


def _gruppi_da_items(items, n_bin):
    """bin_round_robin + incapsulamento in payload base64/etichetta --
    fattorizzato perche' usato sia per shardare il pool (prima delle
    starterOdds) sia per shardare i sopravvissuti (prima del predict)."""
    gruppi_raw = bin_round_robin(items, n_bin)
    gruppi = []
    for i, g in enumerate(gruppi_raw):
        payload = base64.b64encode(json.dumps(g, separators=(',', ':')).encode()).decode()
        etichetta = ' '.join(f"{it['ruolo']}/{it['slug']}" for it in g[:2])
        if len(g) > 2:
            etichetta += f' +{len(g) - 2}'
        gruppi.append({'nome': f"{i + 1:02d} {etichetta}", 'g': payload})
    return gruppi


def cmd_matrice_pool(lega, ruoli, n_bin):
    """NUOVO (30/07, parallelizzazione del prefiltro): sharda il pool GIA'
    filtrato per qualita' in <= n_bin gruppi, SENZA controllare le
    starterOdds qui -- quel controllo (costoso, una query per giocatore)
    avviene poi in parallelo nel job 'prefiltro' a matrice, invece che in un
    unico job sequenziale (era il vero collo di bottiglia: ~5-6 minuti per
    ~280 candidati K League, misurato sui run reali del 30/07)."""
    pool_piatto = []
    for ruolo in ruoli:
        pool = carica_pool_qualita_filtrato(lega, ruolo)
        log(f"[{ruolo}] Pool globale (gia' filtrato per qualita'): {len(pool)} giocatori.")
        pool_piatto.extend({'ruolo': ruolo, 'slug': s} for s in pool)
    gruppi = _gruppi_da_items(pool_piatto, n_bin)
    _scrivi_gruppi_output('gruppi_pool', gruppi)
    log(f"[matrice-pool] {len(pool_piatto)} candidati totali (pre-starterOdds) in {len(gruppi)} gruppi.")


def cmd_prefiltra_shard(lega, payload_b64, out_path):
    """Controlla le starterOdds SOLO per lo shard ricevuto (una frazione del
    pool totale) e scrive i sopravvissuti su disco, per essere caricati come
    artifact e uniti nel job 'prefiltro_merge'. Gira in parallelo con gli
    altri shard (fino a SLOT_CONCORRENTI insieme) -- stesso guadagno di
    velocita' gia' visto per il predict."""
    items = json.loads(base64.b64decode(payload_b64).decode())
    per_ruolo = {}
    for it in items:
        per_ruolo.setdefault(it['ruolo'], []).append(it['slug'])
    sopravvissuti = []
    for ruolo, slugs in per_ruolo.items():
        log(f"[{ruolo}] Prefiltro starterOdds >= {MIN_STARTER_ODDS_PREFILTER:.0%} "
            f"su {len(slugs)} candidati di questo shard...")
        survived = prefiltra_starter_odds(ruolo, slugs)
        sopravvissuti.extend({'ruolo': ruolo, 'slug': s} for s in survived)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(sopravvissuti, f)
    log(f"Shard: {len(sopravvissuti)}/{len(items)} sopravvissuti, scritti in {out_path}")


def cmd_merge_prefiltro(artifacts_dir, n_bin):
    """Unisce i sopravvissuti di tutti gli shard del prefiltro (un file
    survivors.json per artifact scaricato) e li risharda in <= n_bin gruppi
    per il job predict -- STESSO output ('gruppi=', vedi _scrivi_gruppi_output)
    di quando il prefiltro era un unico job sequenziale, cosi' il job
    'predict' a valle non ha bisogno di nessuna modifica."""
    sopravvissuti = []
    if os.path.isdir(artifacts_dir):
        for root, _dirs, files in os.walk(artifacts_dir):
            for name in files:
                if name == 'survivors.json':
                    with open(os.path.join(root, name), encoding='utf-8') as f:
                        sopravvissuti.extend(json.load(f))
    gruppi = _gruppi_da_items(sopravvissuti, n_bin)
    _scrivi_gruppi_output('gruppi', gruppi)
    log(f"[merge-prefiltro] {len(sopravvissuti)} sopravvissuti totali (da tutti gli shard) "
        f"in {len(gruppi)} gruppi per il predict.")


def cmd_matrice(lega, ruoli, n_bin):
    """Prefiltro (qualita' gia' fatta in discovery, starterOdds qui) + shard
    in <= n_bin gruppi per il job predict a matrice -- stesso schema
    discovery/predict di formazione_giornata.yml (vedi pipeline_artifacts.py
    'matrice'), senza pero' il modello di costo storico: qui il pool dopo il
    doppio filtro e' piccolo (decine, non centinaia) e i tempi per giocatore
    abbastanza uniformi da non giustificare quella complessita'."""
    sopravvissuti = raccogli_sopravvissuti(lega, ruoli)
    gruppi = _gruppi_da_items(sopravvissuti, n_bin)
    _scrivi_gruppi_output('gruppi', gruppi)
    log(f"[matrice] {len(sopravvissuti)} sopravvissuti totali in {len(gruppi)} gruppi "
        f"(target <= {n_bin}).")


def cmd_predict_shard(lega, payload_b64):
    """Esegue le predizioni per lo shard ricevuto (lista di {'ruolo','slug'}),
    un subprocess TARGET_SLUG per giocatore, in sequenza DENTRO questo job --
    ma il job stesso gira in parallelo con gli altri shard della matrice
    (fino a SLOT_CONCORRENTI insieme, gestito da GitHub Actions), che e' dove
    sta il guadagno di velocita' reale rispetto al vecchio loop sequenziale
    in un unico job."""
    items = json.loads(base64.b64decode(payload_b64).decode())
    log(f"Shard ricevuto: {len(items)} giocatori.")
    for idx, item in enumerate(items, 1):
        ruolo, slug = item['ruolo'], item['slug']
        log(f"[{ruolo}] [{idx}/{len(items)}] Predizione per {slug}...")
        run_prediction_su_slug(lega, ruolo, slug)
        if idx < len(items):
            time.sleep(2.0)


def main():
    args = sys.argv[1:]
    if not args:
        print(f"Uso: python best_five.py <lega> [--run] [--backups N] [--roles gk,def,mid,fwd]\n"
              f"     python best_five.py <lega> --matrice [--roles ...] [--n-bin N]   # job 'prefiltro'\n"
              f"     python best_five.py <lega> --predict-shard <base64>              # job 'predict' (un bin)\n"
              f"Leghe supportate (discovery globale completa): {', '.join(LEGHE_SUPPORTATE)}")
        sys.exit(1)

    lega = args[0]

    # Modalita' "contender" (31/07, richiesta esplicita utente): pool
    # COMBINATO di piu' leghe gia' processate singolarmente con Best Five
    # normale (--run su ciascuna), NESSUNA nuova query qui -- solo lettura
    # dei consiglio_*.txt piu' recenti di ciascuna lega elencata in --leghe.
    # Esce subito, non condivide il resto di main() (che serve alla lega
    # singola).
    if lega == 'contender':
        if '--leghe' not in args:
            log("ERRORE: 'contender' richiede --leghe lega1,lega2,... (es. austria,croazia,germania2).")
            sys.exit(1)
        idx = args.index('--leghe')
        leghe = [s.strip() for s in args[idx + 1].split(',') if s.strip()]
        n_backup = 2
        if '--backups' in args:
            idx_b = args.index('--backups')
            n_backup = int(args[idx_b + 1])

        bff, generated, totale, lineup_blocks, lineup_html_blocks = costruisci_formazione_contender(
            leghe, 1 + n_backup)

        out_dir = os.path.join(REPO_ROOT, 'formazione_contender', 'output', 'best_five')
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')

        report = (
            "=" * 70 + "\n"
            f"BEST FIVE — CONTENDER (limitato a: {', '.join(leghe)})\n"
            f"Generato: {datetime.datetime.utcnow().isoformat()}Z\n"
            f"{generated} formazione/i generata/e su {1 + n_backup} richieste, "
            f"totale complessivo {totale} pt attesi.\n"
            f"Pool: solo le leghe {', '.join(leghe)} (NON tutte le leghe reali di Contender su "
            "Sorare, vedi backlog). Sinergie/anti-stack/captain calcolati come nel tool unificato.\n"
            + "=" * 70 + "\n\n"
            + "\n\n".join(lineup_blocks)
        )
        out_path = os.path.join(out_dir, f'best_five_contender_{ts}.txt')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(report)

        page_title = "Best Five — Contender (limitato)"
        page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                         f"{generated}/{1 + n_backup} formazioni, pool limitato a {', '.join(leghe)} "
                         "(NON tutte le leghe reali di Contender). Sinergie/anti-stack/captain "
                         "come nel tool unificato.")
        footer = "Script separato e READ-ONLY rispetto alla pipeline di produzione."
        html_report = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer)
        html_report = rendi_carte_cliccabili(html_report)
        html_path = os.path.join(out_dir, f'best_five_contender_{ts}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_report)

        print("\n" + report)
        log(f"Report salvato in: {out_path}")
        log(f"Report HTML salvato in: {html_path}")
        return

    # Modalita' a matrice (30/07, parallelizzazione stile formazione_giornata.yml):
    # tre job separati invece di un unico loop sequenziale -- vedi
    # .github/workflows/best_five.yml. Queste due modalita' fanno UNA cosa
    # sola e ritornano subito, non condividono il resto di main() (che serve
    # invece al job 'report', identico a prima: legge i file gia' su disco e
    # costruisce il ranking, senza bisogno di flag nuovi).
    ruoli_tutti = ('gk', 'def', 'mid', 'fwd')

    def _ruoli_da_args():
        ruoli = ruoli_tutti
        if '--roles' in args:
            idx = args.index('--roles')
            richiesti = [r.strip() for r in args[idx + 1].split(',') if r.strip()]
            ruoli = tuple(r for r in richiesti if r in ruoli_tutti) or ruoli_tutti
        return ruoli

    def _n_bin_da_args():
        n_bin = SLOT_CONCORRENTI
        if '--n-bin' in args:
            idx = args.index('--n-bin')
            n_bin = int(args[idx + 1])
        return n_bin

    if '--matrice' in args:
        cmd_matrice(lega, _ruoli_da_args(), _n_bin_da_args())
        return

    # --matrice-pool / --prefiltra-shard / --merge-prefiltro (30/07,
    # parallelizzazione del prefiltro: richiesta esplicita utente dopo aver
    # visto che il prefiltro sequenziale (--matrice, sopra) restava
    # comunque 5-6 minuti su ~280 candidati K League -- il collo di
    # bottiglia non era il predict ma le query starterOdds una per una.
    # Sostituisce --matrice nel workflow con 3 step: shard del pool (qui),
    # controllo starterOdds in parallelo (job a matrice), poi merge +
    # shard dei sopravvissuti per il predict (identico a prima da qui in poi).
    if '--matrice-pool' in args:
        cmd_matrice_pool(lega, _ruoli_da_args(), _n_bin_da_args())
        return

    if '--prefiltra-shard' in args:
        idx = args.index('--prefiltra-shard')
        payload = args[idx + 1]
        idx_out = args.index('--out')
        out_path = args[idx_out + 1]
        cmd_prefiltra_shard(lega, payload, out_path)
        return

    if '--merge-prefiltro' in args:
        idx = args.index('--merge-prefiltro')
        artifacts_dir = args[idx + 1]
        cmd_merge_prefiltro(artifacts_dir, _n_bin_da_args())
        return

    if '--predict-shard' in args:
        idx = args.index('--predict-shard')
        cmd_predict_shard(lega, args[idx + 1])
        return

    esegui = '--run' in args
    n_backup = 2
    if '--backups' in args:
        idx = args.index('--backups')
        n_backup = int(args[idx + 1])

    if lega not in LEGHE_SUPPORTATE:
        log(f"ATTENZIONE: '{lega}' non e' tra le leghe con discovery globale completa nota "
            f"({', '.join(LEGHE_SUPPORTATE)}) — procedo comunque, ma potrebbe mancare il pool.")

    ruoli = ('gk', 'def', 'mid', 'fwd')

    # --roles (30/07, ripresa run parziale): permette di rilanciare --run SOLO
    # sui ruoli mancanti (es. dopo che una sessione precedente ha gia'
    # completato e committato gk/def) invece di rifare tutto da capo. Il
    # ranking finale (costruisci_best_five sotto) resta invece SEMPRE su
    # tutti e 4 i ruoli, leggendo l'ultimo output disponibile per ciascuno
    # (formato pool intero O per-slug, vedi costruisci_best_five) -- quindi
    # funziona anche a run misti (alcuni ruoli generati in una sessione
    # precedente, altri in questa).
    ruoli_da_eseguire = ruoli
    if '--roles' in args:
        idx = args.index('--roles')
        richiesti = [r.strip() for r in args[idx + 1].split(',') if r.strip()]
        non_validi = [r for r in richiesti if r not in ruoli]
        if non_validi:
            log(f"ATTENZIONE: ruoli non validi ignorati: {non_validi} (validi: {ruoli})")
        ruoli_da_eseguire = tuple(r for r in richiesti if r in ruoli) or ruoli

    if esegui:
        for ruolo in ruoli_da_eseguire:
            run_prediction_pool_prefiltrato(lega, ruolo)

    # Formazione VERA (30/07, richiesta esplicita utente: sinergie/anti-stack/
    # captain come il tool unificato, non un elenco top-N per ruolo) --
    # sostituisce costruisci_best_five/formatta_report* come output
    # principale. count = 1 (titolare) + n_backup (formazioni alternative
    # complete, vedi costruisci_formazione_vera).
    bff, generated, totale, lineup_blocks, lineup_html_blocks = costruisci_formazione_vera(
        lega, 1 + n_backup)

    out_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five')
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')

    report = (
        "=" * 70 + "\n"
        f"BEST FIVE — {lega.upper()} (formazione IN SEASON, pool globale)\n"
        f"Generato: {datetime.datetime.utcnow().isoformat()}Z\n"
        f"{generated} formazione/i generata/e su {1 + n_backup} richieste, "
        f"totale complessivo {totale} pt attesi.\n"
        "Pool: TUTTI i giocatori della lega (discovery globale), non solo posseduti. "
        "Sinergie/anti-stack/captain calcolati come nel tool unificato.\n"
        + "=" * 70 + "\n\n"
        + "\n\n".join(lineup_blocks)
    )
    out_path = os.path.join(out_dir, f'best_five_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    page_title = f"Best Five — {lega.upper()}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"{generated}/{1 + n_backup} formazioni, pool TUTTI i giocatori della lega "
                     f"(discovery globale, non solo posseduti). Sinergie/anti-stack/captain "
                     f"come nel tool unificato.")
    footer = "Script separato e READ-ONLY rispetto alla pipeline di produzione."
    html_report = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer)
    html_report = rendi_carte_cliccabili(html_report)
    html_path = os.path.join(out_dir, f'best_five_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_report)

    print("\n" + report)
    log(f"Report salvato in: {out_path}")
    log(f"Report HTML salvato in: {html_path}")


if __name__ == '__main__':
    main()
