"""Fa girare la calibrazione anche quando non c'e' una partita futura.

Il bug (trovato 01/08 con la prima run reale sulle big5): in build_prediction
il grid search di CALIBRATION_MODE sta DOPO il controllo

    if not future_games:
        return None

Quel controllo esiste per la PREDIZIONE, che senza un avversario da
affrontare non si puo' calcolare. Ma la calibrazione e' un backtest sullo
STORICO: le partite future non le usa. Risultato: fuori stagione (le big5 a
inizio agosto) ogni giocatore usciva a mani vuote pur avendo lo storico
completo -- la run italia/gk ha chiuso 34 job verdi e zero dati.

Vale anche per MLS e K League, dove non si e' mai visto solo perche' sono In
Season e una partita futura c'e' sempre.

Cosa fa lo script, per ogni file:
  1. inserisce un ramo anticipato: se CALIBRATION_MODE e non ci sono partite
     future, gira il grid search sullo storico e torna un risultato marcato
     `solo_calibrazione`. La chiamata al grid search non e' riscritta: viene
     COPIATA dal ramo CALIBRATION_MODE gia' presente nello stesso file, cosi'
     le due strade non possono divergere;
  2. estrae il salvataggio di <slug>_grid.json in salva_grid_results(), e lo
     richiama da entrambe le strade (stesso motivo: una sola copia);
  3. aggiunge nel ciclo chiamante la gestione di `solo_calibrazione`.

Non tocca nulla del percorso di produzione: il ramo nuovo si attiva solo con
CALIBRATION_MODE attivo, che in produzione e' spento.
"""
import re
import sys

LEGHE = ('mls', 'kleague', 'francia', 'inghilterra', 'italia', 'belgio', 'spagna', 'germania')
RUOLI = {'gk': 'test_gk.py', 'def': 'test_def.py', 'mid': 'test_mid.py',
         'fwd': 'test_mls_fwd_all.py'}

GUARDIA = """    if not future_games:
        log("[FASE 4/4] INTERROTTO: nessuna partita futura trovata (anyFutureGames vuoto), "
            "impossibile calcolare una predizione senza un target.")
        return None
"""

BLOCCO_SALVATAGGIO_VECCHIO = """        grid_dir = os.path.join(OUTPUT_DIR, 'grid_search')
        if not os.path.exists(grid_dir):
            os.makedirs(grid_dir)
        grid_export = [
            {'label': r['label'], 'half_life': r['half_life'], 'range_multiplier': r['range_multiplier'],
             'opponent_sensitivity': r['opponent_sensitivity'], 'trend_intensity': r['trend_intensity'],
             'mae': r['mae'], 'pct_dentro_range': r['pct_dentro_range'],
             'n_test': len(r.get('rows') or [])}
            for r in (result.get('grid_results') or []) if r.get('mae') is not None
        ]
        grid_path = os.path.join(grid_dir, f'{slug}_grid.json')
        with open(grid_path, 'w', encoding='utf-8') as f:
            json.dump(grid_export, f, ensure_ascii=False, indent=2)
"""

FUNZIONE_SALVATAGGIO = '''def salva_grid_results(slug, result):
    """Scrive <slug>_grid.json per il job 'aggregate' separato.

    FUNZIONE UNICA (01/08): la chiamano sia il percorso normale sia quello di
    sola calibrazione (nessuna partita futura). Prima era un blocco inline;
    duplicarlo avrebbe significato due copie che possono divergere in
    silenzio, l'errore gia' visto altrove nel progetto."""
    grid_dir = os.path.join(OUTPUT_DIR, 'grid_search')
    if not os.path.exists(grid_dir):
        os.makedirs(grid_dir)
    grid_export = [
        {'label': r['label'], 'half_life': r['half_life'], 'range_multiplier': r['range_multiplier'],
         'opponent_sensitivity': r['opponent_sensitivity'], 'trend_intensity': r['trend_intensity'],
         'mae': r['mae'], 'pct_dentro_range': r['pct_dentro_range'],
         'n_test': len(r.get('rows') or [])}
        for r in (result.get('grid_results') or []) if r.get('mae') is not None
    ]
    grid_path = os.path.join(grid_dir, f'{slug}_grid.json')
    with open(grid_path, 'w', encoding='utf-8') as f:
        json.dump(grid_export, f, ensure_ascii=False, indent=2)
    return len(grid_export)


'''

GESTIONE_CHIAMANTE = """        # Sola calibrazione (01/08): il giocatore ha storico ma nessuna partita
        # futura (fuori stagione). C'e' un grid search da salvare e nessuna
        # predizione da mettere a report.
        if result.get('solo_calibrazione'):
            n_comb = salva_grid_results(slug, result)
            log(f"[{slug}] SOLO CALIBRAZIONE: {n_comb} combinazioni salvate "
                f"(nessuna partita futura, grid search fatto sullo storico).")
            summary_rows.append((slug, 'SOLO CALIBRAZIONE', None, None,
                                 'nessuna partita futura'))
            continue

"""

ANCORA_CHIAMANTE = """        if result.get('excluded'):
"""


def _chiamata_grid(s, ruolo):
    """Copia LETTERALE della chiamata al grid search dal ramo CALIBRATION_MODE
    gia' presente nel file: cosi' il ramo nuovo non puo' divergere."""
    m = re.search(r'^        grid_results = run_grid_search_prod_\w+\(\n(?:.*\n)*?.*?\)\n',
                  s, re.M)
    if not m:
        return None
    return m.group(0)


def patcha(path, ruolo):
    s = open(path, encoding='utf-8', newline='').read()
    crlf = '\r\n' in s
    if crlf:
        s = s.replace('\r\n', '\n')

    if 'solo_calibrazione' in s:
        return 'gia fatto'
    chiamata = _chiamata_grid(s, ruolo)
    if chiamata is None:
        return 'NESSUN GRID ALLINEATO (saltato)'
    for cosa, testo in (('guardia', GUARDIA),
                        ('blocco salvataggio', BLOCCO_SALVATAGGIO_VECCHIO),
                        ('ancora chiamante', ANCORA_CHIAMANTE)):
        if s.count(testo) != 1:
            return f'ERRORE: {cosa} trovata {s.count(testo)} volte'

    ramo = (
        "    # CALIBRAZIONE FUORI STAGIONE (01/08): il grid search e' un backtest\n"
        "    # sullo STORICO e non ha bisogno di una partita futura. Il controllo\n"
        "    # qui sotto protegge la PREDIZIONE, che senza avversario non si puo'\n"
        "    # calcolare; senza questo ramo, con i campionati fermi ogni giocatore\n"
        "    # usciva a mani vuote pur avendo storico completo (run italia/gk del\n"
        "    # 01/08: 34 job verdi, zero dati raccolti).\n"
        "    if CALIBRATION_MODE and not future_games:\n"
        "        presence_rate = len(usable) / total_considered if total_considered else 1.0\n"
        "        log(f\"CALIBRATION_MODE senza partita futura: grid search ALLINEATO \"\n"
        "            f\"sullo storico ({len(GRID_SEARCH_COMBINATIONS_PROD)} combinazioni)...\")\n"
        + chiamata +
        "        return {'solo_calibrazione': True, 'grid_results': grid_results}\n"
        "\n"
    )

    s = s.replace(GUARDIA, ramo + GUARDIA, 1)
    s = s.replace(BLOCCO_SALVATAGGIO_VECCHIO,
                  "        salva_grid_results(slug, result)\n", 1)
    s = s.replace(ANCORA_CHIAMANTE, GESTIONE_CHIAMANTE + ANCORA_CHIAMANTE, 1)

    # la funzione va definita prima del ciclo che la usa: la si mette subito
    # prima di build_prediction, che e' top-level in tutti i file.
    if s.count('def build_prediction(') != 1:
        return 'ERRORE: build_prediction non unica'
    s = s.replace('def build_prediction(', FUNZIONE_SALVATAGGIO + 'def build_prediction(', 1)

    if crlf:
        s = s.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(s)
    return 'patchato'


if __name__ == '__main__':
    leghe = sys.argv[1:] or LEGHE
    for lega in leghe:
        for ruolo, fname in RUOLI.items():
            path = f'formazione_{lega}/predict/{fname}'
            print(f'{lega:12s} {ruolo:4s} -> {patcha(path, ruolo)}')
