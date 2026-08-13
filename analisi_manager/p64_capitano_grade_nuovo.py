# -*- coding: utf-8 -*-
"""IL CAPITANO, RIPROVATO COL GRADE NUOVO (13/08/2026).

PERCHE' SI RIAPRE UN FILONE CHIUSO. Il capitano col grade fu testato il
12/08 e usci' NEGATIVO (t=-1,93). Ma quel test girava sul grade VECCHIO:
z-score dentro il gruppetto nativo (lega, ruolo, giornata), che con meno di
2 membri si spegneva del tutto -- il 51%+ delle righe di produzione. Da
stasera il grade si applica SEMPRE, con le tabelle storiche, ed e' anche
meno rumoroso (dispersione dell'effetto quasi dimezzata sul pool vero).
E' un segnale diverso: l'obiezione dell'utente e' legittima e il test costa
poco.

LE REGOLE A CONFRONTO, sulle STESSE 5 carte della formazione reale --
cambia SOLO chi porta la fascia. In arena il capitano vale +20% del suo
punteggio REALE, quindi la somma delle altre quattro e' identica in tutti i
bracci e il confronto e' esattamente 0,2 x (punteggio del capitano scelto).

  PRODUZIONE  atteso piu' alto (che ora contiene gia' il grade), con la
              regola del portiere: un GK diventa capitano solo se batte il
              miglior giocatore di movimento di almeno GK_CAPTAIN_MARGIN
              (6,7 punti) -- pick_captain in
              formazione_mls/build_formazione_finale.py:1658.
  UTENTE      grade piu' alto; a parita' di grade l'atteso maggiore; a
              parita' di entrambi l'ordine di ruolo MID > FWD > DEF (scelta
              esplicita dell'utente per i casi limite).
  SENZA VOTO  atteso piu' alto ignorando il grade (_cal): serve a separare
              "il grade aiuta" da "l'atteso aiuta".
  ORACOLO     il punteggio realizzato piu' alto. Non e' una regola
              giocabile: e' il tetto, dice quanto margine esiste in tutto.
  CASO        capitano a sorte fra le 5 carte (media su tutte e 5): il
              pavimento.

Bootstrap ricampionando i MANAGER. Nessuna query.

Uso: python analisi_manager/p64_capitano_grade_nuovo.py
     python analisi_manager/p64_capitano_grade_nuovo.py --manager crowss
"""
import os
import sys
import io
import random
import argparse
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p23_binario1_mga as B1  # noqa: E402

BONUS = 0.20                 # capitano in arena, +20% (regola Sorare)
GK_CAPTAIN_MARGIN = 6.7      # formazione_mls/build_formazione_finale.py:1655
ORDINE_RUOLO = {'MID': 0, 'FWD': 1, 'DEF': 2, 'GK': 3}   # scelta dell'utente
GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}


def cap_produzione(carte):
    """atteso piu' alto, col margine per il portiere."""
    mov = [c for c in carte if c['codice'] != 'GK']
    gk = [c for c in carte if c['codice'] == 'GK']
    best_mov = max(mov, key=lambda c: c['atteso']) if mov else None
    best_gk = max(gk, key=lambda c: c['atteso']) if gk else None
    if best_mov is None:
        return best_gk
    if best_gk is not None and best_gk['atteso'] >= best_mov['atteso'] + GK_CAPTAIN_MARGIN:
        return best_gk
    return best_mov


def _grade_num(g):
    """Il grade nelle righe del pool e' GIA' numerico (A=6..F=1), lo mette
    cosi' grade_in_finestra in p12. Si accetta anche la lettera per non
    dipendere da quel dettaglio. None/assente -> 0, cioe' ultimo."""
    if g is None:
        return 0
    if isinstance(g, str):
        return GRADE_NUM.get(g.strip().upper(), 0)
    try:
        return float(g)
    except (TypeError, ValueError):
        return 0


def cap_utente(carte):
    """grade piu' alto -> atteso -> ordine di ruolo MID, FWD, DEF."""
    def chiave(c):
        return (-_grade_num(c['grade']), -c['atteso'],
                ORDINE_RUOLO.get(c['codice'], 9))
    return sorted(carte, key=chiave)[0]


def cap_senza_voto(carte):
    mov = [c for c in carte if c['codice'] != 'GK']
    gk = [c for c in carte if c['codice'] == 'GK']
    best_mov = max(mov, key=lambda c: c['cal']) if mov else None
    best_gk = max(gk, key=lambda c: c['cal']) if gk else None
    if best_mov is None:
        return best_gk
    if best_gk is not None and best_gk['cal'] >= best_mov['cal'] + GK_CAPTAIN_MARGIN:
        return best_gk
    return best_mov


def boot(per_unita, a, b, n_boot=5000, seed=20260813):
    chiavi = sorted(per_unita)
    per_man = collections.defaultdict(list)
    for k in chiavi:
        per_man[k[0]].append(k)
    manager = sorted(per_man)
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        tot = 0.0
        for _i in range(len(manager)):
            m = manager[rnd.randrange(len(manager))]
            for k in per_man[m]:
                tot += per_unita[k][b] - per_unita[k][a]
        ds.append(tot)
    ds.sort()
    n = len(ds)
    return {'delta': sum(per_unita[k][b] - per_unita[k][a] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', action='append', default=[])
    args = ap.parse_args()

    fixtures = B1.elenca_fixture()
    if args.manager:
        fixtures = [f for f in fixtures if f[0] in set(args.manager)]
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    regole = {'PRODUZIONE': cap_produzione, 'UTENTE': cap_utente,
              'SENZA VOTO': cap_senza_voto}
    totali = collections.Counter()
    per_unita = collections.defaultdict(lambda: collections.Counter())
    n_form = 0
    concordi = collections.Counter()
    for manager, fx, path in fixtures:
        pre = B1.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        S21.applica_gruppi_grade(pre['pool_rows'], modo='lega_ruolo')
        riga = {r['carta']: r for r in pre['pool_rows']}
        for form in pre['pulite']:
            carte = []
            ok = True
            for c in form['carte']:
                r = riga.get(c.get('carta'))
                if r is None or c.get('punteggio') is None:
                    ok = False
                    break
                grezzo = c['punteggio'] / 1.2 if c.get('capitano') else c['punteggio']
                carte.append({'slug': c['slug'], 'codice': r['codice'],
                              'atteso': r['_combinato'], 'cal': r['_cal'],
                              'grade': r.get('_grade'), 'reale': grezzo})
            if not ok or len(carte) != 5:
                continue
            n_form += 1
            k = (manager, fx)
            scelte = {}
            for nome, fn in regole.items():
                c = fn(carte)
                scelte[nome] = c['slug']
                v = BONUS * c['reale']
                totali[nome] += v
                per_unita[k][nome] += v
            oracolo = max(carte, key=lambda c: c['reale'])
            totali['ORACOLO'] += BONUS * oracolo['reale']
            per_unita[k]['ORACOLO'] += BONUS * oracolo['reale']
            caso = BONUS * sum(c['reale'] for c in carte) / 5.0
            totali['CASO'] += caso
            per_unita[k]['CASO'] += caso
            if scelte['UTENTE'] == scelte['PRODUZIONE']:
                concordi['stesso capitano'] += 1
            else:
                concordi['capitano diverso'] += 1

    print('=' * 92)
    print('CAPITANO -- stesse 5 carte, cambia solo chi porta la fascia')
    print('formazioni: %d   unita\' manager-giornata: %d' % (n_form, len(per_unita)))
    print('UTENTE e PRODUZIONE scelgono lo stesso capitano in %d formazioni su %d (%.0f%%)'
          % (concordi['stesso capitano'], n_form,
             100.0 * concordi['stesso capitano'] / max(1, n_form)))
    print('=' * 92)
    print('%-12s %14s %12s' % ('regola', 'essenze bonus', 'per arena'))
    for nome in ('CASO', 'SENZA VOTO', 'PRODUZIONE', 'UTENTE', 'ORACOLO'):
        print('%-12s %14.0f %12.3f' % (nome, totali[nome], totali[nome] / max(1, n_form)))
    print()
    print('quanto margine esiste in tutto: ORACOLO - CASO = %.3f punti per arena'
          % ((totali['ORACOLO'] - totali['CASO']) / max(1, n_form)))
    print('quanto ne prende la produzione: %.3f (%.0f%% del massimo)'
          % ((totali['PRODUZIONE'] - totali['CASO']) / max(1, n_form),
             100.0 * (totali['PRODUZIONE'] - totali['CASO'])
             / max(1e-9, totali['ORACOLO'] - totali['CASO'])))
    print()
    print('DELTA APPAIATI (bootstrap sui manager), in punti realizzati:')
    for a, b in (('PRODUZIONE', 'UTENTE'), ('SENZA VOTO', 'PRODUZIONE'),
                 ('CASO', 'PRODUZIONE')):
        r = boot(per_unita, a, b)
        print('  %-24s %+9.1f   IC95[%+8.1f;%+8.1f]  positivo %5.1f%%'
              % ('%s - %s' % (b, a), r['delta'], r['lo'], r['hi'], r['pct'] * 100))
    print()
    print('La riga che decide e\' la prima: la regola dell\'utente batte quella')
    print('di produzione? Se l\'intervallo contiene lo zero, non si tocca niente.')


if __name__ == '__main__':
    main()
