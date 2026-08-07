#!/usr/bin/env python3
"""Estrai velocemente i primi 10 della LISTA B."""
import subprocess
import os

LISTA_B = [
    "ruben-s-trophy-chasers", "eugeneg", "istvan-babos2001", "tail-s", "kadro-muhendisi",
    "kalatocha", "poukinou", "miro5", "paultergeist", "noisy-neighbour",
]

for slug in LISTA_B:
    path = os.path.join('dati_globali', f'manager_{slug}.json')
    if os.path.exists(path):
        print(f"[SKIP] {slug}: gia' estratto")
        continue
    print(f"[ESTRAI] {slug}...", flush=True)
    try:
        result = subprocess.run(
            ['python', 'ricostruisci_manager.py', slug, '--dalle-mie-arene', '--max-giornate', '1'],
            timeout=120,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            if 'ERRORE' in result.stderr or 'ERROR' in result.stderr:
                print(f"  FALLITO: slug non valido/non trovato")
            else:
                print(f"  ERRORE: exit code {result.returncode}")
        else:
            print(f"  OK")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
    except Exception as e:
        print(f"  ECCEZIONE: {e}")
