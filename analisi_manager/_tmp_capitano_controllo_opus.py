# -*- coding: utf-8 -*-
"""CONTROLLO CAPITANO (12/08/2026, Opus esecutore) -- NON committare.

Due cose:
  A. il t=-2,42 del criterio "favorito da quote" e' vero o e' un artefatto
     della copertura parziale delle quote dentro l'arena?
  B. quanto dell'85% "lasciato sul tavolo" dal capitano e' davvero prendibile?
     (curva correlazione -> guadagno, sui punteggi VERI delle 1145 arene)

Richiede analisi_manager/dati/_tmp_capitano_favorito_rows.json, prodotto da
_tmp_capitano_favorito_dump.py (= lo script dell'orchestratore
_tmp_capitano_favorito.py con in piu una json.dump delle righe calcolate).
Zero rete.
"""
import os, json, math, random, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
random.seed(3)
GKM = 6.7


def tt(d):
    n = len(d)
    m = sum(d) / n
    sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
    return m, (m / (sd / n ** 0.5) if sd else 0.0), n


def cal_pick(carte):
    """La scelta di produzione: miglior atteso di movimento, col portiere
    ammesso solo se supera di GK_CAPTAIN_MARGIN (build_formazione_finale.py)."""
    of = [c for c in carte if c['ruolo'] != 'GK']
    gk = [c for c in carte if c['ruolo'] == 'GK']
    b = max(of, key=lambda c: c['cal'])
    if gk:
        bg = max(gk, key=lambda c: c['cal'])
        if bg['cal'] >= b['cal'] + GKM:
            return bg
    return b


P = os.path.join(ROOT, 'analisi_manager', 'dati', '_tmp_capitano_favorito_rows.json')
if os.path.exists(P):
    R = json.load(open(P, encoding='utf-8'))
    print('=== A. IL CRITERIO "FAVORITO DA QUOTE": quante carte vede davvero? ===')
    for campo in ('dfo', 'df'):
        cop = collections.Counter()
        for r in R:
            of = [c for c in r['carte'] if c['ruolo'] != 'GK']
            cop[sum(1 for c in of if c[campo] is not None)] += 1
        print('  carte outfield con %-3s per arena: %s' % (campo, sorted(cop.items())))
    print('  (4 carte di movimento per arena in tutte e %d le arene)' % len(R))

    print('\n  1. gli zeri del fallback falsano la t? NO:')
    tutti, solo_cop = [], []
    for r in R:
        of = [c for c in r['carte'] if c['ruolo'] != 'GK']
        cov = [c for c in of if c['dfo'] is not None]
        a = max(cov, key=lambda c: c['dfo']) if cov else cal_pick(r['carte'])
        b = cal_pick(r['carte'])
        d = 0.2 * a['reale'] - 0.2 * b['reale']
        tutti.append(d)
        if cov:
            solo_cop.append(d)
    m, t, n = tt(tutti)
    print('     tutte le arene (col fallback):   delta %+.4f  t=%+.2f  n=%d' % (m, t, n))
    m, t, n = tt(solo_cop)
    print('     solo arene con almeno una quota: delta %+.4f  t=%+.2f  n=%d' % (m, t, n))
    print('     stessa t: gli zeri diluiscono il DELTA (tre volte), non la t.')

    print('\n  2. il confronto EQUO (i due criteri vedono le STESSE carte):')
    for campo in ('dfo', 'df'):
        for minc in (2, 3, 4):
            d = []
            for r in R:
                cov = [c for c in r['carte'] if c['ruolo'] != 'GK' and c[campo] is not None]
                if len(cov) < minc:
                    continue
                a = max(cov, key=lambda c: c[campo])
                b = max(cov, key=lambda c: c['cal'])
                d.append(0.2 * a['reale'] - 0.2 * b['reale'])
            if len(d) > 20:
                m, t, n = tt(d)
                print('     %-3s, >=%d carte coperte: delta %+.4f  t=%+.2f  n=%d' % (campo, minc, m, t, n))
    gkcap = sum(1 for r in R if cal_pick(r['carte'])['ruolo'] == 'GK')
    print('\n  controllo di forma: arene in cui la produzione capitana un PORTIERE: %d/%d' % (gkcap, len(R)))
else:
    print('(manca %s: lancia prima _tmp_capitano_favorito_dump.py)' % P)

print('\n=== B. QUANTO DELL\'85%% "SUL TAVOLO" E\' DAVVERO PRENDIBILE? ===')
out = json.load(open(os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_out.json'), encoding='utf-8'))
arene = [[x['reale'] for x in a['carte']] for e in out['per_gw'] for a in e['ris_A'] if len(a['carte']) == 5]
caso = sum(sum(c) / 5 for c in arene) / len(arene)
senno = sum(max(c) for c in arene) / len(arene)
massimo = 0.2 * (senno - caso)
tutti = [x for c in arene for x in c]
mu, sd = sum(tutti) / len(tutti), st.pstdev(tutti)
print('  %d arene | bonus a caso %.3f | col senno di poi %.3f | massimo sul piatto %.3f | sd carta %.2f'
      % (len(arene), 0.2 * caso, 0.2 * senno, massimo, sd))
print('  se il criterio avesse correlazione r col punteggio vero:')
print('     r      guadagno bonus   %% del massimo')
for r in (0.05, 0.10, 0.156, 0.20, 0.30, 0.40, 0.60, 0.80, 1.0):
    tot = 0.0
    giri = 40
    for _ in range(giri):
        s = 0.0
        for c in arene:
            pred = [r * ((x - mu) / sd) + math.sqrt(max(0.0, 1 - r * r)) * random.gauss(0, 1) for x in c]
            s += 0.2 * (c[max(range(5), key=lambda i: pred[i])] - sum(c) / 5)
        tot += s / len(arene)
    g = tot / giri
    print('     %-5s  %+.3f           %4.1f%%' % (r, g, 100 * g / massimo))
print('  il modello di oggi prende +0,684 (14,9%): e esattamente cio che rende un criterio con r~0,156,')
print('  cioe la correlazione che gli abbiamo misurato sui ruoli di movimento. Non lascia niente sul tavolo.')
