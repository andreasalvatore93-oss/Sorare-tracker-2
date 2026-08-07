#!/usr/bin/env python3
"""Estrai velocemente tutti i manager della LISTA A."""
import subprocess
import os

LISTA_A = [
    "boss_paran-9dd7e583-f098-4302-b898-bd0869dd2545",
    "reins",
    "freecer",
    "alain-salice-gmail-com",
    "ffthinker",
    "l-empreinte-du-crapaud",
    "perenjoy",
]

for slug in LISTA_A:
    path = os.path.join('dati_globali', f'manager_{slug}.json')
    if os.path.exists(path):
        print(f"[SKIP] {slug}: gia' estratto")
        continue
    print(f"[ESTRAI] {slug}...", flush=True)
    try:
        result = subprocess.run(
            ['python', 'ricostruisci_manager.py', slug, '--dalle-mie-arene', '--max-giornate', '1'],
            timeout=180,
            capture_output=False
        )
        if result.returncode != 0:
            print(f"  ERRORE: exit code {result.returncode}")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
