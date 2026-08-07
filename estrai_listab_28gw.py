#!/usr/bin/env python3
"""Estrai LISTA B con le 28 giornate feb-mag."""
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

# Primi 20 della LISTA B (max 30 totali - 10 LISTA A = 20 rimasti)
LISTA_B = [
    "mauri-89-fast-reply", "el11fiasco", "velebit", "akkinports", "jdtrey22",
    "hannes1401", "madrush123", "ether-united", "nopassaran", "pepit-s",
    "jeddyknight", "private-joker", "diego-dag", "jakobs-xi", "james168",
    "rosscowav", "piinkman", "haufen", "juanbou11", "vicvac",
]

for i, slug in enumerate(LISTA_B, 1):
    print(f"[{i}/20] {slug}...", flush=True)
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
            print(f"  FALLITO")
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
    except Exception as e:
        print(f"  ECCEZIONE: {e}")
