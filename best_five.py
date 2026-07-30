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
import subprocess
import datetime

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
    qualita' (media L5/L10/L40 >= 30) a monte da filter_by_quality(), nessun
    filtro aggiuntivo da fare qui."""
    path = os.path.join(discovery_global_dir(lega, ruolo), 'player_slugs.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Discovery globale non trovata per {ruolo}: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


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

    # Riordina per ORDINAMENTO se presente (stesso criterio usato dallo
    # script sorgente), altrimenti mantiene l'ordine gia' presente nel file.
    if any(r['ordinamento'] is not None for r in righe):
        righe.sort(key=lambda r: (r['ordinamento'] if r['ordinamento'] is not None else -1e9),
                   reverse=True)
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


def costruisci_best_five(lega, ruoli, n_backup):
    risultati = {}
    for ruolo in ruoli:
        path_all = trova_ultimo_output(lega, ruolo)
        if path_all:
            righe = parse_riepilogo(path_all)
            log(f"[{ruolo}] {len(righe)} giocatori trovati nel riepilogo di {os.path.basename(path_all)} "
                f"(formato pool intero).")
        else:
            paths = trova_output_per_slug(lega, ruolo)
            righe = [r for r in (parse_file_singolo_slug(p) for p in paths) if r]
            if any(r['ordinamento'] is not None for r in righe):
                righe.sort(key=lambda r: (r['ordinamento'] if r['ordinamento'] is not None else -1e9),
                           reverse=True)
            else:
                righe.sort(key=lambda r: r['pt_attesi'], reverse=True)
            log(f"[{ruolo}] {len(righe)} giocatori trovati in {len(paths)} file prediction_<slug>_*.txt "
                f"(formato prefiltro starterOdds).")
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


def main():
    args = sys.argv[1:]
    if not args:
        print(f"Uso: python best_five.py <lega> [--run] [--backups N] [--roles gk,def,mid,fwd]\n"
              f"Leghe supportate (discovery globale completa): {', '.join(LEGHE_SUPPORTATE)}")
        sys.exit(1)

    lega = args[0]
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

    risultati = costruisci_best_five(lega, ruoli, n_backup)
    report = formatta_report(lega, risultati, n_backup)

    out_dir = os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', 'best_five')
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join(out_dir, f'best_five_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print("\n" + report)
    log(f"Report salvato in: {out_path}")


if __name__ == '__main__':
    main()
