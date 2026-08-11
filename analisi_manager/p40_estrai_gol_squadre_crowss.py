"""Estrae i gol veri (homeGoals/awayGoals) delle partite stagione 2025/26
delle squadre coperte dall'archivio crowss, per rifare forza difensiva/
offensiva col margine reale invece del proxy binario clean-sheet (fallito,
vedi docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §10).

Finestra e metodo decisi da Opus esecutore (secco, in chat, non file):
stagione 2025/26 + oggi (dal 2025-08-01), non storia intera (piu' storia
peggiora l'AUC, §10.5) ne' solo le 18 giornate crowss (troppo corta per il
lead-in walk-forward).

Passi:
1. squadre crowss: giocatori in archivio_ufficiale/manager_crowss/{pre,dal}
   -> squadra propria via analisi_manager/dati/_cache_index_gamelog.json.
2. partite uniche: scansione DIRETTA dei file .game_log_cache/*_gamelog.json
   (non l'indice ridotto, che non tiene il Game.id) per Game.id univoco,
   date >= 2025-08-01, status 'played', squadra in squadre crowss.
3. gol veri: query pubblica nodes(ids: [Game!]) homeGoals/awayGoals, batch
   100/richiesta, no cookie (dati pubblici, budget anonimo, verificato oggi).

Uso: python analisi_manager/p40_estrai_gol_squadre_crowss.py
Produce: analisi_manager/dati/gol_squadre_crowss_2025-26_<data>.json
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

CACHE_INDEX = os.path.join('analisi_manager', 'dati', '_cache_index_gamelog.json')
FINESTRA_INIZIO = '2025-08-01'
OUT = os.path.join('analisi_manager', 'dati',
                    f'gol_squadre_crowss_2025-26_{datetime.date.today().isoformat()}.json')


def squadre_crowss():
    files = glob.glob('archivio_ufficiale/manager_crowss/pre_2026-08-07/*.json') + \
            glob.glob('archivio_ufficiale/manager_crowss/dal_2026-08-07/*.json')
    giocatori = set()
    for f in files:
        d = json.load(open(f, encoding='utf-8'))
        righe = d['righe'] if isinstance(d, dict) else d
        for riga in righe:
            for c in riga['carte']:
                giocatori.add(c['slug'])
    idx = json.load(open(CACHE_INDEX, encoding='utf-8'))
    squadre = {idx[p]['squadra'] for p in giocatori if p in idx and idx[p].get('squadra')}
    return giocatori, squadre


def partite_uniche(squadre):
    partite = {}  # game_id -> {date, home, away}
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
                if not gid or not data or data < FINESTRA_INIZIO:
                    continue
                if g.get('statusTyped') != 'played':
                    continue
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if casa not in squadre and fuori not in squadre:
                    continue
                partite[gid] = {'date': data, 'home': casa, 'away': fuori}
    return partite


QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    id
    ... on Game {
      homeGoals
      awayGoals
    }
  }
}
"""


def estrai_gol(game_ids):
    out = {}
    ids = list(game_ids)
    for i in range(0, len(ids), 100):
        lotto = ids[i:i + 100]
        r = RM.graphql(QUERY, {'ids': lotto}, con_cookie=False)
        if 'errors' in r:
            print(f"  lotto {i//100}: ERRORE {r['errors']}")
            continue
        for node in r['data']['nodes']:
            if node is None:
                continue
            out[node['id']] = {'home_goals': node.get('homeGoals'),
                                'away_goals': node.get('awayGoals')}
        print(f"  lotto {i//100+1}/{(len(ids)+99)//100} ok ({len(out)} totali)")
    return out


if __name__ == '__main__':
    giocatori, squadre = squadre_crowss()
    print(f"giocatori crowss: {len(giocatori)}  squadre proprie: {len(squadre)}")

    partite = partite_uniche(squadre)
    print(f"partite uniche stagione 2025/26+: {len(partite)}")

    t0 = time.time()
    gol = estrai_gol(partite.keys())
    print(f"gol estratti: {len(gol)} / {len(partite)}  in {time.time()-t0:.0f}s")

    mancanti = [gid for gid in partite if gid not in gol]
    if mancanti:
        print(f"ATTENZIONE: {len(mancanti)} partite senza gol estratti (dump primi 5): {mancanti[:5]}")

    finale = {}
    for gid, meta in partite.items():
        g = gol.get(gid, {})
        finale[gid] = {**meta, **g}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(finale, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"salvato: {OUT}")

    print("\ndump 10 casi:")
    for gid in list(finale)[:10]:
        r = finale[gid]
        print(f"  {r['date']}  {r['home']} {r.get('home_goals')}-{r.get('away_goals')} {r['away']}")
