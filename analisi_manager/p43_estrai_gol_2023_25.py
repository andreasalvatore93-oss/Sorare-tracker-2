"""Estrae i gol veri delle stagioni 2023/24 e 2024/25 (dal 2023-08-01 al
2025-07-31) per le squadre dell'archivio (stesse 378 di p42), per portare
il test di tenuta OOS del segnale attacco-avversario/GK da 193 a ~900+
righe indipendenti (chiesto da Opus esecutore in §11.9, eseguito
dall'orchestratore per contenere il costo -- l'utente ha chiesto di non
usare piu' Opus se non necessario).

Il periodo e' indipendente da quello gia' usato (2025/26): niente
sovrapposizione di partite-eval, la storia 2023/24 serve solo da lead-in
walk-forward per i primi mesi della 2024/25.

Uso: python analisi_manager/p43_estrai_gol_2023_25.py
Produce: analisi_manager/dati/gol_squadre_archivio_2023_25_<data>.json
"""
import os
import sys
import json
import time
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from analisi_manager.p42_estrai_gol_tutte_squadre_archivio import squadre_archivio
from analisi_manager.p40_estrai_gol_squadre_crowss import estrai_gol

FINESTRA_INIZIO = '2023-08-01'
FINESTRA_FINE = '2025-07-31'
OUT = os.path.join('analisi_manager', 'dati',
                    f'gol_squadre_archivio_2023_25_{datetime.date.today().isoformat()}.json')


def partite_uniche(squadre):
    partite = {}
    for root, _dirs, files in os.walk('.'):
        if not root.endswith('.game_log_cache'):
            continue
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            try:
                d = json.load(open(os.path.join(root, fn), encoding='utf-8'))
            except Exception:
                continue
            for v in (d or {}).values():
                g = (v or {}).get('anyGame') or {}
                gid = g.get('id')
                data = (g.get('date') or '')[:10]
                if not gid or not data or data < FINESTRA_INIZIO or data > FINESTRA_FINE:
                    continue
                if g.get('statusTyped') != 'played':
                    continue
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if casa not in squadre and fuori not in squadre:
                    continue
                partite[gid] = {'date': data, 'home': casa, 'away': fuori}
    return partite


if __name__ == '__main__':
    _giocatori, squadre = squadre_archivio()
    print(f"squadre archivio: {len(squadre)}")

    partite = partite_uniche(squadre)
    print(f"partite uniche {FINESTRA_INIZIO} -> {FINESTRA_FINE}: {len(partite)}")

    t0 = time.time()
    gol = estrai_gol(partite.keys())
    print(f"gol estratti: {len(gol)} / {len(partite)}  in {time.time()-t0:.0f}s")

    mancanti = [gid for gid in partite if gid not in gol]
    if mancanti:
        print(f"ATTENZIONE: {len(mancanti)} partite senza gol (dump primi 5): {mancanti[:5]}")

    finale = {}
    for gid, meta in partite.items():
        g = gol.get(gid, {})
        finale[gid] = {**meta, **g}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(finale, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"salvato: {OUT}  ({len(finale)} partite)")

    print("\ndump 10 casi:")
    for gid in list(finale)[:10]:
        r = finale[gid]
        print(f"  {r['date']}  {r['home']} {r.get('home_goals')}-{r.get('away_goals')} {r['away']}")
