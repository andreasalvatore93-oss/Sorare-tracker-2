"""Estende p40 dalle 201 squadre crowss a TUTTE le squadre coperte da
archivio_ufficiale/aggregato/binario2_pool_rows.json (29 manager, 2.061
giocatori). Serve a Opus per il test di TENUTA out-of-sample della
correlazione gol-avversario/reale GK trovata su crowss (n=697): raddoppia
il campione GK con squadre indipendenti, i cui portieri hanno gia' le
quote 1X2 in dati_globali/odds_1x2_index.json.

Riusa partite_uniche()/estrai_gol() di p40 identiche (stesso metodo,
stessa finestra 2025/26, stessa query pubblica nodes(ids), batch 100).
Non re-interroga le partite gia' presenti nel file di p40: le riusa e
integra solo le mancanti.

Uso: python analisi_manager/p42_estrai_gol_tutte_squadre_archivio.py
Produce: analisi_manager/dati/gol_squadre_archivio_2025-26_<data>.json
"""
import os
import sys
import json
import glob
import time
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import ricostruisci_manager as RM
from analisi_manager.p40_estrai_gol_squadre_crowss import (
    partite_uniche, estrai_gol, CACHE_INDEX, FINESTRA_INIZIO)
from analisi_manager.p36_correlazioni_compagni import costruisci_indice_cache

POOL = 'archivio_ufficiale/aggregato/binario2_pool_rows.json'
OUT = os.path.join('analisi_manager', 'dati',
                    f'gol_squadre_archivio_2025-26_{datetime.date.today().isoformat()}.json')


def squadre_archivio():
    pool = json.load(open(POOL, encoding='utf-8'))
    giocatori = {r['slug'] for r in pool}
    # BUG REALE (11/08/2026, run 31520960100): prima leggeva CACHE_INDEX
    # direttamente con json.load, senza ricostruirlo se mancante. Il file
    # (20MB) non e' mai committato di proposito -- in un checkout CI fresco
    # non esiste -- e nessuno lo ricostruiva mai: il commento nel workflow
    # ("si ricostruisce da zero, non e' un bug") era falso, la funzione che
    # ricostruisce (costruisci_indice_cache, gia' in produzione per altri
    # script) non veniva mai chiamata da questo percorso. FileNotFoundError
    # certo su ogni checkout senza il file gia' presente.
    idx = costruisci_indice_cache()
    squadre = {idx[p]['squadra'] for p in giocatori if p in idx and idx[p].get('squadra')}
    return giocatori, squadre


def gia_estratte():
    """Riusa il file di p40 se presente: evita di ri-scaricare le stesse partite."""
    trovati = glob.glob('analisi_manager/dati/gol_squadre_crowss_2025-26_*.json')
    if not trovati:
        return {}
    f = sorted(trovati)[-1]
    print(f"riuso file gia' estratto: {f}")
    return json.load(open(f, encoding='utf-8'))


if __name__ == '__main__':
    giocatori, squadre = squadre_archivio()
    print(f"giocatori in binario2_pool_rows: {len(giocatori)}  squadre proprie: {len(squadre)}")

    partite = partite_uniche(squadre)
    print(f"partite uniche stagione 2025/26+ (universo esteso): {len(partite)}")

    esistenti = gia_estratte()
    da_scaricare = [gid for gid in partite if gid not in esistenti]
    print(f"gia' note da p40: {len(partite) - len(da_scaricare)}  da scaricare: {len(da_scaricare)}")

    t0 = time.time()
    gol_nuovi = estrai_gol(da_scaricare)
    print(f"gol estratti nuovi: {len(gol_nuovi)} / {len(da_scaricare)}  in {time.time()-t0:.0f}s")

    finale = {}
    for gid, meta in partite.items():
        if gid in esistenti:
            finale[gid] = esistenti[gid]
        else:
            g = gol_nuovi.get(gid, {})
            finale[gid] = {**meta, **g}

    mancanti = [gid for gid, r in finale.items() if r.get('home_goals') is None]
    if mancanti:
        print(f"ATTENZIONE: {len(mancanti)} partite senza gol (dump primi 5): {mancanti[:5]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(finale, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"salvato: {OUT}  ({len(finale)} partite totali)")

    print("\ndump 10 casi:")
    for gid in list(finale)[:10]:
        r = finale[gid]
        print(f"  {r['date']}  {r['home']} {r.get('home_goals')}-{r.get('away_goals')} {r['away']}")
