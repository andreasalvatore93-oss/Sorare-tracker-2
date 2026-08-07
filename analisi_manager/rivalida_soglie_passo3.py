"""PASSO 3 -- pareggi per tipo sul campione grande (manager_*.json).

LIMITE SCOPERTO E NON RISOLTO (da riportare, non nascondere): i file
manager_*.json NON contengono il premio essenze incassato per arena (solo
'piazzamento': rank+punteggio). Il pool di AVVERSARI si allarga tantissimo
coi manager, ma il pool di PREMI OSSERVATI resta quello di
dati_globali/arene_storico.json (160 righe totali) perche' e' l'UNICA fonte
che registra premio_essenze/rank_premiato. Per cap 220 e Uncapped quel pool
resta sotto le 20 righe che lo script stesso pretende come minimo (16 e 8).
Quindi: il pareggio qui sotto e' piu' solido sul LATO CAMPO (chi sono i 9
avversari), ma eredita la stessa debolezza di prima sul LATO PREMIO per i
tipi piccoli. Non e' un numero definitivo per cap 220/Uncapped.
"""
import glob
import json
import random
import statistics
import sys

sys.path.insert(0, '.')
from consiglio_arena import REGOLE, premi_osservati
import consiglio_arena as ca

# mappa competizione manager -> tipo REGOLE (dedicate a un campionato = cap 260,
# regola gia' scritta in consiglio_arena.py REGOLE, confermata dall'utente 03/08)
CAP260_ALIASES = {
    'Cap 260', 'Arena - Limited', 'All Star � Limited', 'Under 23 � Limited',
    'MLS � Hot Streak � Limited', 'Challenger � Limited', 'Contender � Limited',
    'LALIGA EA SPORTS � Limited', 'Champion � Limited', 'K-League � Hot Streak � Limited',
    'All Star Arena - Limited', 'Jupiler Pro League � Limited', 'Premier League � Limited',
    'Bundesliga � Limited', 'Eredivisie � Limited', 'Ligue 1 � Limited', 'MLS � Limited',
    'J-League � Hot Streak � Limited',
}
MAPPA = {}
for c in CAP260_ALIASES:
    MAPPA[c] = 'cap 260'
MAPPA['Cap 220'] = 'cap 220'
MAPPA['Uncapped'] = 'Uncapped'
MAPPA['Arena - Uncapped - Limited'] = 'Uncapped'
MAPPA['Beginner'] = 'Beginner'
MAPPA['Elite'] = 'elite'

TIPO_ARENA_VALIDI = {'arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped'}


def carica_pool():
    files = [f for f in glob.glob('dati_globali/manager_*.json') if 'predizioni' not in f]
    pool = {}
    for f in files:
        d = json.load(open(f, encoding='utf-8'))
        if 'manager' not in d:
            continue
        for gw, voci in d['giornate'].items():
            for v in voci:
                if v.get('tipo_arena') not in TIPO_ARENA_VALIDI:
                    continue
                tipo = MAPPA.get(v.get('competizione'))
                if tipo is None:
                    continue
                p = v.get('piazzamento') or {}
                score = p.get('punteggio')
                if score is None:
                    continue
                pool.setdefault(tipo, []).append(score)
    return pool


def pareggio_indipendente(pool, costo, premi, tipo, sigma=0, prove=20000, seme=7):
    if ca._PREMI_OSS is None:
        ca._PREMI_OSS = premi_osservati()

    def incasso(atteso, rnd):
        totale = 0
        for _ in range(prove):
            mio = rnd.gauss(atteso, sigma) if sigma else atteso
            nove = [pool[rnd.randrange(len(pool))] for _ in range(9)]
            posizione = 1 + sum(1 for x in nove if x > mio)
            if posizione > 3:
                continue
            visti = ca._PREMI_OSS.get((tipo, posizione))
            if visti:
                totale += visti[rnd.randrange(len(visti))]
            else:
                totale += premi[posizione - 1]
        return totale / prove

    basso, alto = 150.0, 450.0
    for _ in range(24):
        meta = (basso + alto) / 2
        rnd = random.Random(seme)
        if incasso(meta, rnd) < costo:
            basso = meta
        else:
            alto = meta
    return (basso + alto) / 2


if __name__ == '__main__':
    pool = carica_pool()
    n_premi = {}
    d = json.load(open(ca.ARCHIVIO, encoding='utf-8'))
    for r in d['arene']:
        if r.get('rank_premiato'):
            n_premi.setdefault(r['tipo'], 0)
            n_premi[r['tipo']] += 1

    print(f"{'tipo':10s} {'n avversari':>12} {'n premi oss.':>13} {'pareggio':>9} {'IC (5 semi)':>18}")
    for tipo, regole in REGOLE.items():
        p = pool.get(tipo)
        if not p:
            continue
        vals = [pareggio_indipendente(p, regole['costo'], regole['premi'], tipo, seme=s)
                for s in (7, 17, 27, 37, 47)]
        m = statistics.mean(vals)
        sd = statistics.pstdev(vals)
        npr = n_premi.get(tipo, 0) if tipo != 'elite' else n_premi.get('Uncapped', 0)
        print(f'{tipo:10s} {len(p):>12} {npr:>13} {m:>9.1f} {m - 2*sd:>7.1f}..{m + 2*sd:<7.1f}')

    print()
    print('CONFRONTO con produzione (build_formazione_globale.PAREGGIO_ARENA):')
    print('  cap 260: prod 265.0 (sigma 42.70 storica) / VALIDAZIONE 259.5 (sigma 50.6)')
    print('  cap 220: prod 244.1')
    print('  uncapped: prod 288.3')
    print('  elite: prod 342.7')
