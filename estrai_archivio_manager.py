"""Estrazione STANDARD per archivio_ufficiale/, arene Limited (10/08/2026).

Generalizzato da estrai_archivio_crowss.py (10/08/2026, decisione utente):
la base di misura non e' piu' solo crowss, puo' includere altri manager,
SEMPRE a una condizione non negoziabile -- vedi archivio_ufficiale/README.md
in testa: il confronto nei binari resta sempre G vs A, MAI "battiamo il
manager X". Il manager fornisce solo la formazione reale e il suo esito
reale.

Applica alla lettera lo schema in `archivio_ufficiale/README.md`. Riusa
SOLO funzioni di produzione gia' verificate, non le riscrive:
  - `ricostruisci_manager.partecipazioni()` / `.formazione()` -- stesse
    query usate per costruire tutto `dati_globali/manager_*.json`, e
    funzionano per QUALUNQUE manager (query pubbliche tranne l'indice).
  - `generatore_formazioni.build_formazione_globale.COSTO_INGRESSO` -- mai
    a mano.
  - `rewardsConfig` per il premio VERO di ogni leaderboard.

NON legge MAI `dati_globali/manager_*.json` come fonte: quei file servono
solo, fuori da questo script, per sapere QUALI fixture esistono (indice),
mai per copiarne le righe.

Scope: SOLO arene Limited (whitelist del README, division escluse). Da7/In
Season non trattate qui.

Dove scrive: per `--manager crowss` rispetta la partizione
pre_2026-08-07/dal_2026-08-07 (solo crowss ha "prima/dopo G", e' il nostro
modello). Per qualunque altro manager scrive direttamente in
`manager_<slug>/`, senza sotto-cartelle (le sue formazioni sono sempre
schieramenti umani reali).

Uso:
  SORARE_COOKIE=... python estrai_archivio_manager.py --manager crowss football-21-24-jul-2026 [altra-fixture ...]
  SORARE_COOKIE=... python estrai_archivio_manager.py --manager forever-young football-21-24-jul-2026
"""
import os
import sys
import json
import time
import argparse
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
import graphql_batch as GB

ARCHIVIO_ROOT = os.path.join(ROOT, 'archivio_ufficiale')
TAGLIO_G = datetime.date(2026, 8, 7)
MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
       'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

# stessa regola del README, applicata alla lettera -- nessuna euristica nuova
TIPO_COSTO = {
    'beginner': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_BEGINNER', 100),
    'cap220': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_220', 200),
    'cap260': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_260', 300),
    'uncapped': bfg.COSTO_INGRESSO.get('ARENA_ALLSTARS_UNCAPPED', 300),
}

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


def fine_fixture(fx):
    """Ultimo giorno della fixture, per decidere pre/dal-G (solo crowss)."""
    toks = fx.split('-')[1:]
    year = int(toks[-1])
    toks = toks[:-1]
    midx = [i for i, t in enumerate(toks) if t in MESI]
    ei = midx[-1]
    d2, m2 = int(toks[ei - 1]), MESI[toks[ei]]
    return datetime.date(year, m2, d2)


def cartella_output(manager, fx):
    if manager == 'crowss':
        sotto = 'dal_2026-08-07' if fine_fixture(fx) >= TAGLIO_G else 'pre_2026-08-07'
        return os.path.join(ARCHIVIO_ROOT, 'manager_crowss', sotto)
    return os.path.join(ARCHIVIO_ROOT, f'manager_{manager}')


def estrai_fixture(manager, fixture):
    log(f'--- {manager} / {fixture} ---')
    righe_idx, ok = RM.partecipazioni(manager, fixture)
    if not ok:
        log(f'  INDICE INCOMPLETO: non salvo nulla per {fixture} (429 o pagina persa).')
        return None
    # 'division' (arene dedicate a un campionato) ESCLUSE di proposito
    # (decisione utente 10/08/2026): niente dato grezzo da conservare per
    # una tipologia che non si gioca piu' e non e' cablata nei binari 1/2.
    arene = [r for r in righe_idx if tipo_da_slug(r['leaderboard']) not in (None, 'division')]
    log(f'  partecipazioni totali: {len(righe_idx)}  |  arene Limited (division escluse): {len(arene)}')
    if not arene:
        log('  nessuna arena limited questa GW, salto.')
        return {'fixture_slug': fixture, 'manager': manager, 'tipo_sezione': 'arene_limited', 'righe': []}

    # Batch via alias GraphQL (10/08/2026, verificato identico riga per riga
    # alle chiamate una-alla-volta su 19 formazioni + 18 leaderboard reali):
    # tutte le formazioni e tutti i premi si scaricano PRIMA, in poche
    # richieste HTTP invece di una a contender/leaderboard.
    contenders = [a['contender'] for a in arene]
    leaderboards_uniche = list(dict.fromkeys(a['leaderboard'] for a in arene))
    log(f'  scarico {len(contenders)} formazioni in lotti da {GB.formazioni_batch.__defaults__[0]}...')
    formazioni_cache = GB.formazioni_batch(contenders)
    log(f'  scarico {len(leaderboards_uniche)} leaderboard di premi in lotti da {GB.premi_batch.__defaults__[0]}...')
    premi_cache = GB.premi_batch(leaderboards_uniche)

    righe_out = []
    n_annullate = 0
    for a in arene:
        carte, manager_reale, piazzamento = formazioni_cache.get(a['contender'], (None, None, None))
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

        premi = premi_cache.get(a['leaderboard'])
        rank = (piazzamento or {}).get('rank')
        premio = None
        if premi and rank:
            trovato = next((q for p, q in premi if p == rank), None)
            premio = trovato or 0
        costo = TIPO_COSTO.get(tipo, 300)

        righe_out.append({
            'contender_slug': a['contender'], 'fixture_slug': fixture, 'gw': fixture,
            'manuale': True,  # schieramento umano reale (crowss pre-G o qualunque altro manager)
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
    return {'fixture_slug': fixture, 'manager': manager, 'tipo_sezione': 'arene_limited', 'righe': righe_out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('fixtures', nargs='+')
    args = ap.parse_args()

    if not RM.COOKIE:
        print('SORARE_COOKIE mancante in env: partecipazioni() non puo funzionare senza.')
        sys.exit(1)
    for fx in args.fixtures:
        out = estrai_fixture(args.manager, fx)
        if out is None:
            continue
        out_dir = cartella_output(args.manager, fx)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f'{fx}_arene_limited.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        log(f'  scritto {path}')


if __name__ == '__main__':
    main()
