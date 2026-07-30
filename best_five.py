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
  python best_five.py kleague --run         # ri-esegue la predizione sul pool GLOBALE per ogni ruolo, poi rankinga
  python best_five.py kleague --run --backups 2   # 1 titolare + 2 backup per ruolo (default: 2 backup)

Il ranking usa lo stesso ORDINAMENTO (score senza shrinkage) gia' calcolato
e stampato da ciascun test_<ruolo>.py nel riepilogo comparativo in cima al
file di output — nessuna logica di scoring duplicata qui, solo parsing +
selezione top N.
"""
import os
import sys
import re
import glob
import subprocess
import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

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


def run_prediction_pool_globale(lega, ruolo):
    """Esegue test_<ruolo>.py sul pool GLOBALE (PLAYER_POOL=global, non
    CALIBRATION_MODE) per TUTTI i giocatori della lega, senza TARGET_SLUG.
    Streamma l'output a schermo come la pipeline di produzione."""
    script = ROLE_SCRIPTS[ruolo]
    script_path = os.path.join(REPO_ROOT, f'formazione_{lega}', 'predict', script)
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script non trovato: {script_path}")

    env = dict(os.environ)
    env['PLAYER_POOL'] = 'global'
    env.pop('CALIBRATION_MODE', None)
    env.pop('TARGET_SLUG', None)

    log(f"[{ruolo}] Avvio predizione sul pool GLOBALE ({script_path})...")
    proc = subprocess.run([sys.executable, script_path], cwd=REPO_ROOT, env=env)
    if proc.returncode != 0:
        log(f"[{ruolo}] ATTENZIONE: processo terminato con codice {proc.returncode} "
            f"(procedo comunque a leggere l'output eventualmente scritto).")


def output_dir_per_ruolo(lega, ruolo):
    return os.path.join(REPO_ROOT, f'formazione_{lega}', 'output', f'{lega}_{ruolo}_all')


def trova_ultimo_output(lega, ruolo):
    """Trova il file prediction_all_*.txt piu' recente per il ruolo (scritto
    dall'esecuzione in modalita' lista completa, cioe' senza TARGET_SLUG)."""
    out_dir = output_dir_per_ruolo(lega, ruolo)
    candidati = glob.glob(os.path.join(out_dir, 'prediction_all_*.txt'))
    if not candidati:
        return None
    return max(candidati, key=os.path.getmtime)


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


def costruisci_best_five(lega, ruoli, n_backup):
    risultati = {}
    for ruolo in ruoli:
        path = trova_ultimo_output(lega, ruolo)
        if not path:
            log(f"[{ruolo}] Nessun output trovato in {output_dir_per_ruolo(lega, ruolo)} "
                f"— esegui con --run per generarlo.")
            risultati[ruolo] = []
            continue
        righe = parse_riepilogo(path)
        log(f"[{ruolo}] {len(righe)} giocatori trovati nel riepilogo di {os.path.basename(path)}.")
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
    # tutti e 4 i ruoli, leggendo l'ultimo prediction_all_*.txt disponibile
    # per ciascuno -- quindi funziona anche a run misti (alcuni ruoli
    # generati in una sessione precedente, altri in questa).
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
            run_prediction_pool_globale(lega, ruolo)

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
