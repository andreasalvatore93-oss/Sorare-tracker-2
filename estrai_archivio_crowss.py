"""Estrazione STANDARD per archivio_crowss/, arene Limited (10/08/2026).

Applica alla lettera lo schema deciso in `archivio_crowss/README.md`
(sezione "Schema dati" + "Come rilanciare un'estrazione"). Riusa SOLO
funzioni di produzione gia' verificate, non le riscrive:
  - `ricostruisci_manager.partecipazioni()` / `.formazione()` -- stesse
    query usate per costruire tutto `dati_globali/manager_*.json`.
  - `generatore_formazioni.build_formazione_globale.COSTO_INGRESSO` -- mai
    a mano.
  - `rewardsConfig` (query gia' in `scarica_premi_arene.py`) per il premio
    VERO di ogni leaderboard, non i vecchi `rank_premiato`/coefficienti.

NON legge MAI `dati_globali/manager_crowss.json` come fonte: quel file
serve solo, fuori da questo script, per sapere QUALI fixture esistono
(indice), mai per copiarne le righe -- e' esattamente il problema di
fiducia che questa cartella e' nata per risolvere (CLAUDE.md 09/08,
"i backtest sono il modello contro se stesso").

Scope: SOLO arene Limited (whitelist del README). Da7/In Season non
trattate qui (decisione esplicita dell'utente, 10/08: "sulle altre
competizioni diventano un bordello").

Uso:
  SORARE_COOKIE=... python estrai_archivio_crowss.py football-21-24-jul-2026 [altra-fixture ...]
"""
import os
import sys
import json
import time
import datetime
import collections

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'generatore_formazioni'))

# ricostruisci_manager.py rifà gia' il wrap di sys.stdout in UTF-8 al suo
# import (console Windows cp1252): non rifarlo qui, il doppio wrap chiude
# il buffer sottostante ("I/O operation on closed file").
import ricostruisci_manager as RM
import build_formazione_globale as bfg

MANAGER = 'crowss'
OUT_DIR = os.path.join(ROOT, 'archivio_crowss', 'pre_2026-08-07')

# stessa regola del README, applicata alla lettera -- nessuna euristica nuova
TIPO_COSTO = {
    'beginner': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_BEGINNER', 100),
    'cap220': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_220', 200),
    'cap260': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_260', 300),
    'uncapped': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_UNCAPPED', 300),
    # arene dedicate a un campionato: stesso costo della cap 260 (README,
    # verificato l'08/08 sulle costanti di produzione: stessa economia)
    'division': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_260', 300),
}

PREMI_QUERY = """
query Premi($slug: String!) {
  so5 {
    so5Leaderboard(slug: $slug) {
      rewardsConfig {
        ranking { ranks rewardConfigs { __typename ... on CardShardRewardConfig { quantity } } }
      }
    }
  }
}
"""


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def tipo_da_slug(leaderboard_slug):
    """Regola ESATTA del README (sezione 'Come si riconosce il tipo')."""
    s = leaderboard_slug or ''
    if 'arena_limited_beginner' in s:
        return 'beginner'
    if 'arena_limited_uncapped' in s:
        return 'uncapped'
    if 'arena_limited_cap_220' in s:
        return 'cap220'
    if 'arena_limited' in s and 'all_star' not in s:
        return 'division'
    if 'arena_limited' in s and 'all_star' in s:
        return 'cap260'
    return None


def premi_per_posizione(leaderboard_slug):
    """[(pos_1based, quantity)] per quella leaderboard, sessione anonima."""
    d = RM.graphql(PREMI_QUERY, {'slug': leaderboard_slug}, con_cookie=False)
    if d.get('errors'):
        return None, str(d['errors'])[:200]
    lb = ((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard')
    if not lb or not lb.get('rewardsConfig'):
        return None, 'rewardsConfig null'
    out, pos = [], 1
    for fascia in (lb['rewardsConfig'].get('ranking') or []):
        larghezza = fascia.get('ranks') or 1
        q = None
        for x in (fascia.get('rewardConfigs') or []):
            if x.get('__typename') == 'CardShardRewardConfig':
                q = x.get('quantity')
                break
        for _ in range(larghezza):
            out.append((pos, q))
            pos += 1
    return out, None


def estrai_fixture(fixture):
    log(f'--- {fixture} ---')
    righe_idx, ok = RM.partecipazioni(MANAGER, fixture)
    if not ok:
        log(f'  INDICE INCOMPLETO: non salvo nulla per {fixture} (429 o pagina persa).')
        return None
    # 'division' (arene dedicate a un campionato) ESCLUSE di proposito
    # (decisione utente 10/08/2026): l'utente non le gioca piu', la soglia
    # dedicata in produzione e' dietro un flag spento di default e non e'
    # cablata nei binari 1/2 -- niente dato grezzo da conservare, i dati
    # Sorare non sono scarsi. Risparmia anche le query formazione/premi per
    # quelle arene.
    arene = [r for r in righe_idx if tipo_da_slug(r['leaderboard']) not in (None, 'division')]
    log(f'  partecipazioni totali: {len(righe_idx)}  |  arene Limited (division escluse): {len(arene)}')
    if not arene:
        log('  nessuna arena limited questa GW, salto.')
        return {'fixture_slug': fixture, 'manager': MANAGER, 'tipo_sezione': 'arene_limited', 'righe': []}

    premi_cache = {}
    righe_out = []
    n_annullate = 0
    for a in arene:
        carte, manager_reale, piazzamento = RM.formazione(a['contender'])
        if carte is None:
            log(f"  ATTENZIONE: formazione non recuperata per {a['contender']} -- SALTATA (non silenziosa: contata sotto)")
            continue
        tipo = tipo_da_slug(a['leaderboard'])
        gold = 'gold' in (a.get('competizione') or '').lower()
        somma = sum(c.get('punteggio') or 0.0 for c in carte)
        ufficiale = (piazzamento or {}).get('punteggio')
        annullata = False
        if ufficiale is not None and abs(somma - ufficiale) > 0.5:
            if ufficiale == 0.0 and somma > 0:
                annullata = True
                n_annullate += 1
            else:
                log(f"  ATTENZIONE coerenza: {a['contender']} somma={somma:.2f} "
                    f"ufficiale={ufficiale:.2f} -- tenuta ma segnalata, non e' il pattern annullata noto")

        lb = a['leaderboard']
        if lb not in premi_cache:
            premi_cache[lb], errore = premi_per_posizione(lb)
            if errore:
                log(f"  premi non disponibili per {lb}: {errore}")
        premi = premi_cache.get(lb)
        rank = (piazzamento or {}).get('rank')
        premio = None
        if premi and rank:
            trovato = next((q for p, q in premi if p == rank), None)
            premio = trovato or 0
        costo = TIPO_COSTO.get(tipo, 300)

        righe_out.append({
            'contender_slug': a['contender'], 'fixture_slug': fixture, 'gw': fixture,
            'manuale': True,  # pre-G: crowss correggeva sempre a mano, README
            'annullata': annullata,
            'capitano': next(({'slug': c['slug'], 'ruolo': c['ruolo']}
                             for c in carte if c['capitano']), None),
            'punteggio_totale': None if annullata else ufficiale,
            'rank': rank,
            'carte': [{'slug': c['slug'], 'nome': c['nome'], 'carta': c['carta'],
                      'ruolo': c['ruolo'], 'rarita': c['rarita'], 'capitano': c['capitano'],
                      'punteggio': c['punteggio']} for c in carte],
            'tipo': tipo, 'gold': gold, 'costo_ingresso': costo,
            'premio': 0 if annullata else premio,
            'premio_netto': (-costo if annullata else
                            (premio - costo if premio is not None else None)),
        })

    log(f'  formazioni scritte: {len(righe_out)}  (annullate: {n_annullate})')
    return {'fixture_slug': fixture, 'manager': MANAGER, 'tipo_sezione': 'arene_limited', 'righe': righe_out}


def main():
    fixtures = sys.argv[1:]
    if not fixtures:
        print('Uso: python estrai_archivio_crowss.py fixture1 [fixture2 ...]')
        sys.exit(1)
    if not RM.COOKIE:
        print('SORARE_COOKIE mancante in env: partecipazioni() non puo funzionare senza.')
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    for fx in fixtures:
        out = estrai_fixture(fx)
        if out is None:
            continue
        path = os.path.join(OUT_DIR, f'{fx}_arene_limited.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        log(f'  scritto {path}')


if __name__ == '__main__':
    main()
