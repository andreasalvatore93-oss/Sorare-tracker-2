#!/usr/bin/env python3
"""Riestrai LISTA A con le 28 giornate feb-mag corrette."""
import subprocess

GIORNATE = ",".join([
    "football-30-jan-3-feb-2026",  "football-6-10-feb-2026",   "football-13-17-feb-2026",
    "football-17-20-feb-2026",     "football-20-24-feb-2026",  "football-24-27-feb-2026",
    "football-3-6-mar-2026",       "football-6-10-mar-2026",   "football-10-13-mar-2026",
    "football-13-17-mar-2026",     "football-17-20-mar-2026",  "football-20-24-mar-2026",
    "football-27-31-mar-2026",     "football-31-mar-3-apr-2026",
    "football-3-7-apr-2026",       "football-10-10-apr-2026",  "football-10-14-apr-2026",
    "football-17-17-apr-2026",     "football-17-21-apr-2026",  "football-21-24-apr-2026",
    "football-24-28-apr-2026",     "football-29-apr-1-may-2026",
    "football-1-5-may-2026",       "football-8-12-may-2026",   "football-13-15-may-2026",
    "football-15-19-may-2026",     "football-23-26-may-2026",  "football-26-29-may-2026",
])

LISTA_A = [
    "zinomalte-9d1f1e9a-6917-4352-b706-dfb26f3631c2",
    "ice013-open-for-good-trades",
    "edjeraketje",
    "boss_paran-9dd7e583-f098-4302-b898-bd0869dd2545",
    "reins",
    "freecer",
    "alain-salice-gmail-com",
    "ffthinker",
    "l-empreinte-du-crapaud",
    "perenjoy",
]

for i, slug in enumerate(LISTA_A, 1):
    print(f"[{i}/10] {slug}...", flush=True)
    try:
        result = subprocess.run(
            ['python', 'ricostruisci_manager.py', slug, '--giornate', GIORNATE],
            timeout=300,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  OK")
        else:
            print(f"  ERRORE: exit {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
    except Exception as e:
        print(f"  ECCEZIONE: {e}")
