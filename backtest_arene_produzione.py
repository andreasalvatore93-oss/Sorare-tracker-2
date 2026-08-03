"""backtest_arene_produzione — il modello DI PRODUZIONE (allocatore vero)
contro l'utente, su una giornata gia' giocata.

Differenza rispetto a backtest_arene.py: quello usa un greedy interno
(_migliore_per_arena + scambi locali) scritto solo per il backtest. Qui si
usa l'allocatore VERO -- build_one_lineup di formazione_mls/build_formazione_finale.py,
la stessa funzione che genera le formazioni reali (build_formazione_globale.py
importa da li' senza duplicare nulla) -- cosi' il confronto misura il modello
che gira oggi, non un suo sostituto.

Disegno (deciso con l'utente, 03/08 sera):
  * A PARITA' DI MAZZO: le carte sono quelle REALMENTE schierate dall'utente
    quel giorno (stesso pool di backtest_arene.py), con l'L10 che avevano
    quel giorno (walk-forward, dallo stesso cutoff-giornata che fixa il
    leak -- vedi backtest_arene.inizio_giornata).
  * A PARITA' DI CONTENITORI: gli "slot" arena sono quelli REALMENTE esistiti
    quel giorno (arene_storico.json, con la loro soglia/terzo/premio veri).
    Non se ne inventano di nuovi: di un'arena mai entrata dall'utente non
    conosciamo la soglia, quindi non e' valutabile onestamente.
  * LIBERTA' DI ALLOCAZIONE: il modello riempie gli slot in ordine di
    priorita' (cap 260/Beginner -> cap 220 -> Uncapped, stessa priorita'
    dichiarata in generatore_formazioni/build_formazione_globale.py), con
    build_one_lineup vero (sinergia GK-DEF, anti-sinergia avversario,
    knapsack esatto sotto cap). Si ferma da solo quando il pool si esaurisce
    per quella forma -- puo' quindi lasciare SLOT VUOTI (non gioca) o
    scegliere carte diverse da quelle vere dell'utente per lo stesso slot.
    NON decide se un'arena "conviene" in essenze (soglie PAREGGIO_ARENA/
    GUADAGNO_PER_PUNTO derivano dai backtest col leak, ancora da ricalibrare):
    qui si valuta solo la qualita' di SELEZIONE, a pool identico.
  * NESSUN VOTO FINALE nella previsione: build_one_lineup/pick_captain usano
    solo 'atteso' (walk-forward). Il punteggio REALE (gia' segnato quel
    giorno) entra SOLO nel confronto finale, mai nella scelta.

Uso:
    python backtest_arene_produzione.py --fixture football-1-5-may-2026
"""
import os
import sys
import json
import io
import argparse
import importlib.util
import collections

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _import_module(name, rel_path):
    path = os.path.join(_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bff = _import_module('mls_bff_backtest', 'formazione_mls/build_formazione_finale.py')

MOLTIPLICATORE_CAPITANO = 1.2

RUOLO_SORARE_TO_CODICE = {
    'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD',
}

# Stesso cap nominale di backtest_arene.py, ma qui SEMPRE quello vero di
# Sorare (nessun aggiustamento verso l'alto: il modello sceglie da solo,
# quindi non c'e' bisogno di allargare il cap per non invalidare una
# formazione reale dell'utente).
NOMINAL_CAP = {
    'cap 220': 220.0, 'cap 260': 260.0, 'Beginner': 260.0,
    'arena division': 260.0, 'Uncapped': None, 'arena uncapped': None,
}
SHAPE_BY_CAP = {260.0: 'ARENA_260', 220.0: 'ARENA_220', None: 'ARENA_UNCAPPED'}
# Ordine di priorita' dichiarato in build_formazione_globale.py: cap 260 (qui
# insieme a Beginner, stesso cap/stessa shape) -> cap 220 -> uncapped.
ORDINE_CAP = [260.0, 220.0, None]


def carica(percorso):
    with io.open(percorso, encoding='utf-8') as fh:
        return json.load(fh)


def _punteggio_grezzo(g):
    p = g.get('punteggio')
    if p is None:
        return None
    return p / MOLTIPLICATORE_CAPITANO if g.get('capitano') else p


def raccogli_giornata(formazioni, fixture):
    """Tutte le formazioni utente di quella giornata, con le carte uniche
    (per id-carta, non solo slug: un giocatore puo' avere piu' copie)."""
    voci = [(k, v) for k, v in formazioni.items() if v['fixture'] == fixture]
    carte = {}  # carta_id -> dict(slug, ruolo, nome, reale)
    for _k, v in voci:
        for g in v['giocatori']:
            reale = _punteggio_grezzo(g)
            carte[g['carta']] = {'slug': g['slug'], 'ruolo': g['ruolo'],
                                  'nome': g['nome'], 'reale': reale}
    return voci, carte


def costruisci_pool_e_previsioni(cache, fd, cutoff, carte):
    """Previsioni walk-forward (modello DI OGGI) per ogni (slug, ruolo)
    unico, poi role_data/CardPool nel formato di build_one_lineup, con le
    copie REALMENTE possedute quel giorno (contate per id-carta)."""
    slug_ruolo_unici = sorted(set((c['slug'], c['ruolo']) for c in carte.values()))
    previsioni = {}
    mancanti = []
    for slug, ruolo in slug_ruolo_unici:
        r = P.score_atteso(cache, slug, ruolo, fd, cutoff)
        if r is None or r['l10'] is None:
            mancanti.append((slug, ruolo))
        else:
            previsioni[(slug, ruolo)] = r

    copie = collections.Counter()
    reale_per_slug_ruolo = {}
    for c in carte.values():
        chiave = (c['slug'], c['ruolo'])
        copie[chiave] += 1
        if c['reale'] is not None:
            reale_per_slug_ruolo.setdefault(chiave, c['reale'])

    role_data = {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')}
    counts_by_role = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}
    for (slug, ruolo_s), n in copie.items():
        pred = previsioni.get((slug, ruolo_s))
        if pred is None:
            continue
        codice = RUOLO_SORARE_TO_CODICE[ruolo_s]
        atteso = pred['atteso']
        row = {'slug': slug, 'atteso': atteso, 'low': round(atteso), 'high': round(atteso),
               'team_slug': pred.get('squadra'), 'opponent_team_slug': pred.get('opp_slug'),
               'ordinamento': None, 'kickoff': None, 'opp_factor': None,
               # SOLO per il nostro confronto finale -- build_one_lineup non la legge:
               'reale': reale_per_slug_ruolo.get((slug, ruolo_s))}
        role_data[codice].append(row)
        counts_by_role[codice][slug] = {'in_season': n, 'classic': 0, 'l10': pred['l10']}

    for codice in role_data:
        role_data[codice].sort(key=lambda r: r['atteso'], reverse=True)

    card_pool = bff.CardPool(counts_by_role)
    return role_data, card_pool, previsioni, mancanti


def _totale(formazione, capitano_row):
    """Totale ATTESO e REALE (grezzo + bonus capitano) di una formazione
    costruita da build_one_lineup: formazione e' [(slot_label, row, tipo), ..]."""
    atteso = sum(r['atteso'] for _s, r, _t in formazione)
    atteso += (MOLTIPLICATORE_CAPITANO - 1.0) * capitano_row['atteso']
    reali = [r.get('reale') for _s, r, _t in formazione]
    if any(v is None for v in reali):
        return atteso, None
    reale = sum(reali) + (MOLTIPLICATORE_CAPITANO - 1.0) * capitano_row['reale']
    return atteso, reale


def gioca_giornata(cache, fixture, arene_storico, formazioni):
    fine = B.fine_giornate(arene_storico)
    fd = fine.get(fixture)
    if fd is None:
        raise SystemExit(f"giornata senza data di chiusura: {fixture}")

    _voci, carte = raccogli_giornata(formazioni, fixture)
    if not carte:
        raise SystemExit(f"nessuna formazione utente per {fixture}")

    cutoff = B.inizio_giornata(cache, fd, sorted(set((c['slug'], c['ruolo']) for c in carte.values())))
    print(f"giornata {fixture}: chiusura {fd}, inizio-giornata (cutoff walk-forward) {cutoff}")

    role_data, card_pool, previsioni, mancanti = costruisci_pool_e_previsioni(cache, fd, cutoff, carte)
    n_slug_unici = len(set((c['slug'], c['ruolo']) for c in carte.values()))
    print(f"carte uniche (slug+ruolo) quel giorno: {n_slug_unici}")
    print(f"con previsione+L10 validi: {len(previsioni)}   mancanti: {len(mancanti)}")
    if mancanti:
        for slug, ruolo in mancanti[:15]:
            print(f"  manca: {slug} ({ruolo})")
        if len(mancanti) > 15:
            print(f"  ... e altre {len(mancanti) - 15}")

    # Slot REALI di quella giornata: solo quelli con soglia/premio noti
    # (arene davvero entrate dall'utente), raggruppati per cap effettivo.
    slot_per_cap = collections.defaultdict(list)
    arene_fx = [a for a in arene_storico if a['fixture'] == fixture]
    for a in arene_fx:
        cap = NOMINAL_CAP.get(a['tipo'])
        slot_per_cap[cap].append(a)

    risultati = []
    for cap in ORDINE_CAP:
        slots = slot_per_cap.get(cap, [])
        if not slots:
            continue
        shape_nome = SHAPE_BY_CAP[cap]
        shape = bff.FORMATION_SHAPES[shape_nome]
        for slot in slots:
            formazione, errore, l10_ok, _stack = bff.build_one_lineup(
                shape, role_data, card_pool, l10_cap=cap,
                apply_stack_guard=False, variance_mode=True,
                apply_positive_synergy=True, strict_gk_anti_synergy=False)
            if errore:
                risultati.append({'arena': slot, 'cap': cap, 'giocata': False, 'errore': errore})
                continue
            cap_slot, cap_row, cap_tipo = bff.pick_captain(formazione)
            atteso, reale = _totale(formazione, cap_row)
            risultati.append({
                'arena': slot, 'cap': cap, 'giocata': True,
                'modello_atteso': atteso, 'modello_reale': reale,
                'carte_modello': [(lbl, r['slug']) for lbl, r, _t in formazione],
                'capitano_modello': cap_row['slug'],
                'l10_rispettato': l10_ok,
            })

    return risultati, mancanti


def rapporto(risultati, arene_fx):
    giocate = [r for r in risultati if r['giocata']]
    non_giocate = [r for r in risultati if not r['giocata']]
    print(f"\n{'='*74}")
    print("BACKTEST ARENE — ALLOCATORE DI PRODUZIONE (build_one_lineup) vs utente")
    print('='*74)
    print(f"\nSlot reali quel giorno: {len(arene_fx)}   "
          f"modello ha giocato: {len(giocate)}   saltati (pool esaurito): {len(non_giocate)}")

    con_reale = [r for r in giocate if r['modello_reale'] is not None]
    if con_reale:
        du = [r['arena']['mio_score'] for r in con_reale]
        dm = [r['modello_reale'] for r in con_reale]
        diff = [m - u for m, u in zip(dm, du)]
        print(f"\n--- SU {len(con_reale)} SLOT GIOCATI DA ENTRAMBI (stesso slot, stesso vero risultato) ---")
        print(f"  utente : media {sum(du)/len(du):6.2f}")
        print(f"  modello: media {sum(dm)/len(dm):6.2f}")
        print(f"  differenza media: {sum(diff)/len(diff):+6.2f} punti per arena")
        vinte = sum(1 for d in diff if d > 0)
        print(f"  arene in cui il modello fa meglio: {vinte}/{len(diff)} ({vinte/len(diff):.1%})")

        con_terzo = [r for r in con_reale if r['arena'].get('terzo') is not None]
        if con_terzo:
            pu = sum(1 for r in con_terzo if r['arena']['mio_score'] >= r['arena']['terzo'])
            pm = sum(1 for r in con_terzo if r['modello_reale'] >= r['arena']['terzo'])
            print(f"\n  a premio (soglia vera, {len(con_terzo)} slot): "
                  f"utente {pu} ({pu/len(con_terzo):.1%})  "
                  f"modello {pm} ({pm/len(con_terzo):.1%})")

    if non_giocate:
        print(f"\n--- {len(non_giocate)} SLOT NON GIOCATI DAL MODELLO (pool esaurito) ---")
        per_cap = collections.Counter(r['cap'] for r in non_giocate)
        for cap, n in per_cap.items():
            perso = sum(r['arena']['mio_score'] for r in non_giocate if r['cap'] == cap
                        if r['arena'].get('mio_score') is not None)
            print(f"  cap {cap}: {n} slot saltati (l'utente li aveva giocati per {perso:.1f} punti totali)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', required=True)
    args = ap.parse_args()

    cache = C.CacheLocale()
    formazioni = carica('dati_globali/arene_formazioni.json')['formazioni']
    arene_storico = carica('dati_globali/arene_storico.json')['arene']

    risultati, _mancanti = gioca_giornata(cache, args.fixture, arene_storico, formazioni)
    arene_fx = [a for a in arene_storico if a['fixture'] == args.fixture]
    rapporto(risultati, arene_fx)


if __name__ == '__main__':
    main()
