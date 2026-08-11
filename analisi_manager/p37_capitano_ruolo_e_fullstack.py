"""Domande D (capitano per ruolo) ed E (fullstack) del brief correlazioni,
misurate sulle FORMAZIONI REALI dell'archivio ufficiale.

D -- capitano: a formazione fissa (le 5 carte vere), cambia SOLO chi porta la
fascia. In arena il capitano vale +20% del suo punteggio reale, quindi il
totale e' somma(5) + 0,2*punteggio(capitano): confrontare due regole di scelta
del capitano e' un confronto esatto, senza rigenerare niente.
Baseline = la regola di produzione semplificata: atteso piu' alto fra i
giocatori di movimento (pick_captain applica anche un margine per il portiere,
qui approssimato escludendo il GK dai candidati -- differenza dichiarata).

E -- fullstack: per ogni formazione reale, quante carte vengono dalla stessa
squadra, e come cambiano media e dispersione del residuo (reale meno atteso)
al crescere dello stack.

Uso: python analisi_manager/p37_capitano_ruolo_e_fullstack.py
"""
import os
import sys
import io
import json
import glob
import math
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p23_binario1_mga as B1

BONUS_CAPITANO_ARENA = 0.2


def carica_pool():
    """(slug, fixture) -> riga con atteso calibrato, grade, ruolo."""
    rows = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json',
                          encoding='utf-8'))
    d = {}
    for r in rows:
        d.setdefault((r['slug'], r['fixture']), r)
    return d


def carica_squadre():
    idx = json.load(open('analisi_manager/dati/_cache_index_gamelog.json', encoding='utf-8'))
    return {s: v.get('squadra') for s, v in idx.items()}


def carica_formazioni_reali(pool):
    """Formazioni vere con tutte e 5 le carte agganciate al pool."""
    out = []
    for path in glob.glob('archivio_ufficiale/manager_*/**/*.json', recursive=True):
        try:
            righe = B1.carica_formazioni(path)
        except Exception:
            continue
        if not isinstance(righe, list):
            continue
        for r in righe:
            if not isinstance(r, dict) or not r.get('carte'):
                continue
            fx = r.get('fixture_slug')
            if not fx or r.get('annullata'):
                continue
            carte = []
            for c in r['carte']:
                p = pool.get((c['slug'], fx))
                if p is None or c.get('punteggio') is None:
                    carte = None
                    break
                carte.append({'slug': c['slug'], 'nome': c['nome'],
                              'reale': c['punteggio'], 'atteso': p['_cal'],
                              'grade': p.get('_grade'), 'ruolo': p['codice'],
                              'capitano_vero': bool(c.get('capitano'))})
            if not carte or len(carte) != 5:
                continue
            out.append({'fixture': fx, 'tipo': r.get('tipo'), 'carte': carte,
                        'manager': path.split(os.sep)[1].replace('manager_', '')})
    return out


def totale(carte, cap):
    return sum(c['reale'] for c in carte) + BONUS_CAPITANO_ARENA * cap['reale']


def cap_baseline(carte):
    mov = [c for c in carte if c['ruolo'] != 'GK'] or carte
    return max(mov, key=lambda c: c['atteso'])


def cap_grade(carte, solo_ruolo=None):
    """Capitano alla carta col grade piu' alto. Se solo_ruolo e' indicato, la
    regola si applica SOLO quando quella carta e' di quel ruolo; altrimenti si
    ripiega sulla baseline."""
    con_grade = [c for c in carte if c.get('grade') is not None]
    if not con_grade:
        return cap_baseline(carte)
    migliore = max(con_grade, key=lambda c: (c['grade'], c['atteso']))
    if solo_ruolo is not None and migliore['ruolo'] != solo_ruolo:
        return cap_baseline(carte)
    return migliore


def boot(valori, cluster, B=2000, seed=20260813):
    rnd = random.Random(seed)
    g = collections.defaultdict(list)
    for v, k in zip(valori, cluster):
        g[k].append(v)
    ch = list(g)
    if len(ch) < 5:
        return None
    out = []
    for _ in range(B):
        camp = []
        for _ in range(len(ch)):
            camp.extend(g[ch[rnd.randrange(len(ch))]])
        out.append(sum(camp) / len(camp))
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def domanda_D(forms):
    print('=== D. CAPITANO: grade piu alto, ma SOLO se e di un certo ruolo ===')
    print('    delta = punti di formazione guadagnati rispetto alla baseline')
    print('    (baseline = atteso piu alto fra i giocatori di movimento)')
    base = [totale(f['carte'], cap_baseline(f['carte'])) for f in forms]
    cluster = [(f['manager'], f['fixture']) for f in forms]
    print(f'    n formazioni = {len(forms)}   cluster (manager,giornata) = {len(set(cluster))}')
    regole = [('grade piu alto (sempre)', None),
              ('grade piu alto SOLO se DEF', 'DEF'),
              ('grade piu alto SOLO se MID', 'MID'),
              ('grade piu alto SOLO se FWD', 'FWD'),
              ('grade piu alto SOLO se GK', 'GK')]
    for nome, ruolo in regole:
        alt = [totale(f['carte'], cap_grade(f['carte'], ruolo)) for f in forms]
        delta = [a - b for a, b in zip(alt, base)]
        cambiate = sum(1 for x in delta if abs(x) > 1e-9)
        ic = boot(delta, cluster)
        m = sum(delta) / len(delta)
        s_ic = f'IC95% [{ic[0]:+.2f}, {ic[1]:+.2f}]' if ic else 'IC n/d'
        print(f'  {nome:30s} cambia il capitano in {cambiate:5d}/{len(forms)} '
              f'({cambiate/len(forms):5.1%})  delta medio {m:+6.2f} punti  {s_ic}')
        if cambiate:
            solo = [x for x in delta if abs(x) > 1e-9]
            print(f'  {"":30s}   sulle sole formazioni cambiate: {sum(solo)/len(solo):+6.2f} punti')
    print()


def domanda_E(forms, squadra_di):
    print('=== E. FULLSTACK: piu carte della stessa squadra nella stessa formazione ===')
    per_stack = collections.defaultdict(list)
    for f in forms:
        sq = [squadra_di.get(c['slug']) for c in f['carte']]
        sq = [s for s in sq if s]
        if len(sq) < 5:
            continue
        top = collections.Counter(sq).most_common(1)[0][1]
        att = sum(c['atteso'] for c in f['carte'])
        cap = cap_baseline(f['carte'])
        att += BONUS_CAPITANO_ARENA * cap['atteso']
        rea = totale(f['carte'], cap)
        per_stack[top].append((rea - att, rea, att, (f['manager'], f['fixture'])))
    print('  stack = quante carte della squadra piu rappresentata (su 5)')
    print('  stack   n     residuo medio   dispersione del residuo   atteso medio')
    for k in sorted(per_stack):
        v = per_stack[k]
        res = [x[0] for x in v]
        m = sum(res) / len(res)
        sd = math.sqrt(sum((x - m) ** 2 for x in res) / (len(res) - 1)) if len(res) > 1 else float('nan')
        ic = boot(res, [x[3] for x in v])
        s_ic = f'IC95% [{ic[0]:+6.1f}, {ic[1]:+6.1f}]' if ic else 'IC n/d'
        print(f'   {k:3d}  {len(v):5d}   {m:+8.2f}  {s_ic}   sd {sd:6.1f}      '
              f'{sum(x[2] for x in v)/len(v):6.1f}')
    print()
    return per_stack


def dump_leggibile(forms, squadra_di):
    print('=== DUMP LEGGIBILE: una formazione vera con stack >= 3 ===')
    for f in forms:
        sq = [squadra_di.get(c['slug']) for c in f['carte']]
        cnt = collections.Counter([s for s in sq if s])
        if not cnt or cnt.most_common(1)[0][1] < 3:
            continue
        cap = cap_baseline(f['carte'])
        print(f"  manager={f['manager']}  giornata={f['fixture']}  tipo={f['tipo']}")
        print(f"  {'giocatore':28s} {'ruolo':5s} {'squadra':32s} {'atteso':>7s} {'reale':>7s} {'grade':>5s} cap")
        for c, s in zip(f['carte'], sq):
            print(f"  {c['nome'][:28]:28s} {c['ruolo']:5s} {str(s)[:32]:32s} "
                  f"{c['atteso']:7.1f} {c['reale']:7.1f} {str(c['grade']):>5s} "
                  f"{'C' if c is cap else ''}")
        att = sum(c['atteso'] for c in f['carte']) + 0.2 * cap['atteso']
        print(f"  TOTALE atteso {att:.1f}   reale {totale(f['carte'], cap):.1f}")
        break
    print()


def main():
    pool = carica_pool()
    squadra_di = carica_squadre()
    forms = carica_formazioni_reali(pool)
    print(f'formazioni reali agganciate al pool (tutte e 5 le carte): {len(forms)}')
    print(f'giornate distinte: {len({f["fixture"] for f in forms})}  '
          f'manager distinti: {len({f["manager"] for f in forms})}\n')
    domanda_D(forms)
    domanda_E(forms, squadra_di)
    dump_leggibile(forms, squadra_di)


if __name__ == '__main__':
    main()
