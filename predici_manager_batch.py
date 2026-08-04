# -*- coding: utf-8 -*-
"""Popola la cache del modello (detail_cache = game log passato) per una lista
di giocatori — tipicamente i giocatori NON posseduti schierati da altri manager
in una GW chiusa (filone "smart money", vedi HANDOFF_UNIFICATO §7).

Per ogni slug lancia il predict del ruolo giusto con TARGET_SLUG: il predict
predice la prossima partita futura, ma come EFFETTO scarica e cacha il game log
passato in formazione_<dir>/output/<dir>_<ruolo>_all/.cache/<slug>_detail_cache.json.
Quella cache e' l'asset riusabile: una volta scritta, il walk-forward as-of di
qualunque GW passata e' un calcolo locale a costo zero (nessuna query in piu').

Cache INCREMENTALE: si salta subito ogni slug che ha gia' il detail_cache, e
si committa (opzionale, --commit-every N) man mano — una run interrotta non
perde nulla e riparte da dove era.

Input: un JSON {slug: {ruolo, club, lega, dir}} (prodotto dallo scoping
manager). Uso:
    python predici_manager_batch.py --input dati_globali/smart_money/miss_gw1.json
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))

# ruolo Sorare (dal json manager) -> (sotto-cartella ruolo, script predict)
RUOLO_MAP = {
    'Goalkeeper': ('gk', 'test_gk.py'),
    'Defender': ('def', 'test_def.py'),
    'Midfielder': ('mid', 'test_mid.py'),
    'Forward': ('fwd', 'test_mls_fwd_all.py'),
}


def log(msg):
    print(msg, flush=True)


def gia_cachato(slug):
    """True se esiste gia' il game-log cache per lo slug in QUALSIASI lega/ruolo.
    Il game log e' player-level (non dipende dalla cartella) ed e' l'asset vero:
    viene scritto anche per i giocatori con storico strutturalmente insufficiente,
    quindi e' il criterio giusto di "dato gia' raccolto".
    NB: os.walk, non glob('**'): glob NON scende in modo affidabile nelle cartelle
    nascoste (.game_log_cache/.cache) su questo filesystem (verificato)."""
    target = f'{slug}_gamelog.json'
    for _, _, files in os.walk(REPO):
        if target in files:
            return True
    return False


def commit(msg):
    subprocess.run(['git', 'add', '-A'], cwd=REPO, check=False)
    r = subprocess.run(['git', 'commit', '-m', msg], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode == 0:
        log(f"  [git] commit: {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='JSON {slug:{ruolo,dir,...}}')
    ap.add_argument('--commit-every', type=int, default=0,
                    help='committa ogni N giocatori nuovi (0 = mai)')
    ap.add_argument('--timeout', type=int, default=240,
                    help='timeout in secondi per singolo predict')
    ap.add_argument('--force', action='store_true',
                    help='ri-predici anche se il gamelog esiste gia (per '
                         'APPENDERE nuove partite a cache stantie, es. la GW '
                         'appena chiusa non ancora nel game log)')
    args = ap.parse_args()

    with open(os.path.join(REPO, args.input), encoding='utf-8') as f:
        data = json.load(f)

    tot = len(data)
    fatti = saltati = falliti = 0
    scoperti = []  # lega senza pipeline
    nuovi_da_commit = 0

    for i, (slug, info) in enumerate(sorted(data.items()), 1):
        ruolo = info.get('ruolo')
        dirn = info.get('dir')
        prefix = f"[{i}/{tot}] {slug} ({ruolo}, {dirn})"

        if gia_cachato(slug) and not args.force:
            saltati += 1
            log(f"{prefix} -> gia' cachato, salto.")
            continue
        if not dirn:
            scoperti.append((slug, info.get('lega')))
            log(f"{prefix} -> LEGA SENZA PIPELINE ({info.get('lega')}), salto.")
            continue
        rm = RUOLO_MAP.get(ruolo)
        if not rm:
            falliti += 1
            log(f"{prefix} -> ruolo non mappato, salto.")
            continue

        sub, script = rm
        path = os.path.join(REPO, f'formazione_{dirn}', 'predict', script)
        if not os.path.exists(path):
            falliti += 1
            log(f"{prefix} -> script mancante {path}, salto.")
            continue

        env = dict(os.environ, TARGET_SLUG=slug, PYTHONIOENCODING='utf-8')
        log(f"{prefix} -> predict {script} ...")
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, path], cwd=REPO, env=env,
                               capture_output=True, text=True, timeout=args.timeout)
            ok = gia_cachato(slug)
        except subprocess.TimeoutExpired:
            ok = gia_cachato(slug)
        dt = time.time() - t0
        if ok:
            fatti += 1
            nuovi_da_commit += 1
            log(f"  OK ({dt:.0f}s) cache scritta.")
        else:
            falliti += 1
            log(f"  FALLITO ({dt:.0f}s): nessuna cache prodotta.")

        if args.commit_every and nuovi_da_commit >= args.commit_every:
            commit(f"smart-money: cache incrementale ({fatti} nuovi)")
            nuovi_da_commit = 0

    if args.commit_every and nuovi_da_commit:
        commit(f"smart-money: cache incrementale finale ({fatti} nuovi)")

    log("\n=== RIEPILOGO ===")
    log(f"totale {tot} | cachati nuovi {fatti} | gia' presenti {saltati} | "
        f"falliti {falliti} | leghe senza pipeline {len(scoperti)}")
    if scoperti:
        log("SCOPERTI (nessuna pipeline, non predetti):")
        for sl, lg in scoperti:
            log(f"  {sl} -> {lg}")


if __name__ == '__main__':
    main()
