#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ricompone nel repo quello che i job `predict` dello scouting hanno prodotto.

PERCHE' ESISTE (14/08/2026, misura sulla run 31740179423). Nella matrice
vecchia ogni job predict finiva con `git commit && git push` sul proprio
giocatore. Misurato sui 256 job di quella run, mediana per job:

    checkout                          25s
    pip install                        4s
    il predict vero                    3s   <-- il modello
    git commit + push della previsione 68s   <-- la fila alla cassa

Il 64% del tempo era la contesa su main: 256 job che si accodano a pushare
sullo stesso branch, ciascuno con retry, sleep e merge. Ora i job predict non
pushano piu' niente: impacchettano i file che hanno prodotto in un tar
(`predict-shard-<n>`) e un solo job a valle li rimette insieme qui, con un
commit unico.

L'UNICO FILE CHE NON SI PUO' SOVRASCRIVERE E' `prediction_log.json`: e' un
dizionario per (slug|data_partita) condiviso da tutti i giocatori dello stesso
gruppo lega/ruolo, quindi due shard che hanno predetto due giocatori della
stessa lega ne portano indietro due versioni diverse, ognuna con le proprie
righe. Estraendo i tar uno sopra l'altro l'ultimo vincerebbe e le righe degli
altri sparirebbero (nella matrice vecchia succedeva gia', per via del
`git merge -X ours` nei retry). Qui invece i dizionari si FONDONO: si tengono
tutte le chiavi, e a parita' di chiave vince la voce con `generated_at` piu'
recente. Tutti gli altri file sono per-giocatore (prediction_<slug>_*.txt,
.cache/, .game_log_cache/): la copia semplice va bene, non c'e' niente da
fondere.

Uso:
    python scouting_raccogli_predict.py <cartella_artifact> [--repo .]

dove <cartella_artifact> e' la directory in cui actions/download-artifact ha
scaricato gli artifact (una sottocartella per shard, ciascuna con un .tgz).
"""
import os
import io
import re
import sys
import json
import glob
import shutil
import tarfile
import argparse
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[raccogli] {msg}", flush=True)


def _fondi_prediction_log(dest, sorgente):
    """Unione dei due dizionari (slug|data) -> previsione. A parita' di chiave
    vince `generated_at` piu' recente; se manca il campo vince la sorgente
    nuova (ha appena girato)."""
    try:
        with open(dest, encoding='utf-8') as f:
            vecchio = json.load(f)
    except Exception:
        vecchio = {}
    try:
        with open(sorgente, encoding='utf-8') as f:
            nuovo = json.load(f)
    except Exception as e:
        log(f"ATTENZIONE: {sorgente} illeggibile ({e}), lo salto")
        return 0
    if not isinstance(vecchio, dict) or not isinstance(nuovo, dict):
        # Formato inatteso: non invento una fusione, tengo il file nuovo.
        shutil.copy2(sorgente, dest)
        return 0
    aggiunte = 0
    for chiave, voce in nuovo.items():
        if chiave not in vecchio:
            vecchio[chiave] = voce
            aggiunte += 1
            continue
        v_old = (vecchio[chiave] or {}).get('generated_at') or ''
        v_new = (voce or {}).get('generated_at') or ''
        if v_new >= v_old:
            vecchio[chiave] = voce
    with open(dest, 'w', encoding='utf-8') as f:
        json.dump(vecchio, f, ensure_ascii=False)
    return aggiunte


def _applica_cancellazioni(elenco, repo):
    """I prediction_*.txt che il predict ha sostituito: il file di servizio
    `.scouting_shard/cancellati.txt` dentro l'archivio li elenca. Senza questo
    passaggio resterebbero nel repo per sempre (prima li toglieva il commit del
    singolo job). Si cancella SOLO dentro il repo e solo file, mai cartelle."""
    tolti = 0
    try:
        with open(elenco, encoding='utf-8') as f:
            nomi = [r.strip() for r in f if r.strip()]
    except Exception:
        return 0
    radice = os.path.abspath(repo)
    for nome in nomi:
        percorso = os.path.abspath(os.path.join(repo, nome))
        if not percorso.startswith(radice + os.sep):
            log(f"ATTENZIONE: {nome} e' fuori dal repo, non lo tocco")
            continue
        if os.path.isfile(percorso):
            os.remove(percorso)
            tolti += 1
    return tolti


def raccogli(cartella_artifact, repo=REPO_ROOT):
    archivi = sorted(glob.glob(os.path.join(cartella_artifact, '**', '*.tgz'),
                               recursive=True))
    if not archivi:
        log(f"nessun archivio in {cartella_artifact}: i job predict non hanno "
            f"prodotto niente (o non sono girati).")
        return 0, 0
    log(f"{len(archivi)} archivi da rimettere nel repo.")
    n_file = 0
    n_log = 0
    n_tolti = 0
    for archivio in archivi:
        tmp = tempfile.mkdtemp(prefix='shard_')
        try:
            with tarfile.open(archivio, 'r:gz') as tar:
                # Nessun percorso assoluto o con '..': gli archivi li produce il
                # nostro workflow, ma estrarre alla cieca resta una cattiva idea.
                membri = [m for m in tar.getmembers()
                          if not m.name.startswith(('/', '..'))
                          and '..' not in m.name.split('/')]
                tar.extractall(tmp, members=membri)
            elenco_tolti = os.path.join(tmp, '.scouting_shard', 'cancellati.txt')
            if os.path.isfile(elenco_tolti):
                n_tolti += _applica_cancellazioni(elenco_tolti, repo)
            for radice, _dirs, file_ in os.walk(tmp):
                for nome in file_:
                    sorgente = os.path.join(radice, nome)
                    relativo = os.path.relpath(sorgente, tmp)
                    # File di servizio dell'archivio, non roba da copiare.
                    if relativo.replace(os.sep, '/').startswith('.scouting_shard/'):
                        continue
                    dest = os.path.join(repo, relativo)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if nome == 'prediction_log.json' and os.path.exists(dest):
                        n_log += _fondi_prediction_log(dest, sorgente)
                    else:
                        shutil.copy2(sorgente, dest)
                    n_file += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    log(f"{n_file} file rimessi nel repo, {n_log} righe nuove nei "
        f"prediction_log.json fusi, {n_tolti} previsioni vecchie rimosse.")
    return len(archivi), n_file


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cartella', help="dove download-artifact ha scaricato gli artifact")
    ap.add_argument('--repo', default=REPO_ROOT)
    args = ap.parse_args()
    raccogli(args.cartella, args.repo)


if __name__ == '__main__':
    main()
