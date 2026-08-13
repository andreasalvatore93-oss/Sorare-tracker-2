# -*- coding: utf-8 -*-
"""ALLUNGARE LA FINESTRA STORICA CONVIENE? (14/08/2026)

DA DOVE NASCE. Il modello guarda MAX_HISTORY_DAYS = 365 giorni. Misurato il
14/08 sul mazzo dell'utente: 369 giocatori su 719 hanno la finestra NON
piena (meno di WINDOW_SIZE=30 partite nell'ultimo anno), e per 265 di loro
**i dati ci sono gia' in cache** -- 1.677 partite piene, in media +6,3 a
giocatore, scartate solo perche' hanno piu' di un anno. Il taglio in GIORNI
tratta in modo opposto chi ha bisogno: 365 giorni sono 40 partite per un
titolare e 9 per una riserva.

LA DOMANDA. Il taglio secco serve, o e' un secondo freno sopra l'half-life
che gia' pesa il vecchio meno del nuovo? (Stanotte lo stesso schema si e'
gia' visto due volte: shrinkage doppio in p69, margine d'ingresso doppio in
p59. Entrambe le volte il secondo freno era di troppo o inerte.)

PRIMA IL CONTROLLO DELL'INTERRUTTORE, poi i numeri: si conta quante partite
entrano DAVVERO nella finestra a 365, 730 e 1095 giorni. Se non cambia
niente, il test e' nullo per costruzione e ci si ferma li'.
ATTENZIONE (docstring di backtest_arene_previsioni.partite_finestra): il
banco scarta anche le partite senza DETTAGLIO GRANULARE in cache, che manca
su circa una su tre -- e le piu' vecchie sono le peggio coperte. Puo' quindi
succedere che la finestra si allunghi ma le partite utilizzabili no: e'
esattamente cio' che il controllo qui sotto misura.

METRO: MAE, correlazione e lift INSIEME (regola del repo). Il lift e' il
decile alto per giornata contro la media di giornata.

Uso: python analisi_manager/p71_finestra_storica.py
"""
import os
import sys
import io
import math
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p24_binario2_ga as B2  # noqa: E402
import backtest_arene_previsioni as P  # noqa: E402

FINESTRE = [365, 730, 1095]


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def raccogli(lega_di, idx_grade):
    """(slug,fixture) -> (atteso calibrato, realizzato) con la finestra
    attualmente impostata in P.MAX_HISTORY_DAYS."""
    fuori = {}
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        for r in pre['pool_rows']:
            k = (r['slug'], fx)
            if k in fuori or r.get('reale') is None or r.get('_cal') is None:
                continue
            fuori[k] = (r['_cal'], r['reale'])
    return fuori


def metriche(dati):
    stime = [v[0] for v in dati.values()]
    reali = [v[1] for v in dati.values()]
    mae = sum(abs(a - b) for a, b in zip(stime, reali)) / len(stime)
    c = corr(stime, reali)
    per_fx = collections.defaultdict(list)
    for (slug, fx), (s, r) in dati.items():
        per_fx[fx].append((s, r))
    sopra, media = [], []
    for fx, g in per_fx.items():
        if len(g) < 20:
            continue
        g.sort(key=lambda x: -x[0])
        top = g[:max(1, len(g) // 10)]
        sopra.append(sum(x[1] for x in top) / len(top))
        media.append(sum(x[1] for x in g) / len(g))
    lift = (sum(sopra) / len(sopra) - sum(media) / len(media)) if sopra else 0.0
    return mae, c, lift, len(stime)


def main():
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    print('CONTROLLO DELL\'INTERRUTTORE: le osservazioni cambiano al variare')
    print('della finestra? (se no, il test e\' nullo per costruzione)')
    print()
    risultati = {}
    base = None
    print('%-8s %9s %10s %10s %10s   %s'
          % ('giorni', 'oss.', 'MAE', 'corr', 'lift', 'verso'))
    for g in FINESTRE:
        P.MAX_HISTORY_DAYS = g
        dati = raccogli(lega_di, idx_grade)
        mae, c, lift, n = metriche(dati)
        risultati[g] = (mae, c, lift, n)
        if base is None:
            base = (mae, c, lift, n)
            print('%-8d %9d %10.4f %10.4f %10.3f   <- PRODUZIONE' % (g, n, mae, c, lift))
            continue
        segni = ['MAE %s' % ('meglio' if mae < base[0] else 'peggio'),
                 'corr %s' % ('meglio' if c > base[1] else 'peggio'),
                 'lift %s' % ('meglio' if lift > base[2] else 'peggio')]
        tutti = mae < base[0] and c > base[1] and lift > base[2]
        print('%-8d %9d %10.4f %10.4f %10.3f   %s%s'
              % (g, n, mae, c, lift, ', '.join(segni),
                 '   <== TUTTI E TRE MEGLIO' if tutti else ''))

    P.MAX_HISTORY_DAYS = 365
    n0 = risultati[FINESTRE[0]][3]
    uguali = all(risultati[g][3] == n0 for g in FINESTRE)
    print()
    if uguali:
        print('ATTENZIONE: il NUMERO di osservazioni non cambia mai. Questo non')
        print('vuol dire che il test sia nullo (la finestra puo\' cambiare la')
        print('STIMA di ogni riga senza cambiare quante righe sopravvivono), ma')
        print('se anche MAE/corr/lift sono identici allora l\'interruttore non')
        print('agisce e va capito perche\' prima di concludere qualsiasi cosa.')
    identiche = all(abs(risultati[g][0] - risultati[FINESTRE[0]][0]) < 1e-9
                    for g in FINESTRE)
    if identiche:
        print('INTERRUTTORE INERTE: MAE identico a tutte le finestre. Probabile')
        print('causa: il filtro sul dettaglio granulare mancante scarta le')
        print('partite vecchie prima che la finestra conti. NON concludere che')
        print('"allungare non serve" -- non e\' stato misurato.')
    else:
        print('Interruttore attivo: le metriche si muovono.')
        print('Si applica solo se MAE, correlazione e lift migliorano INSIEME.')


if __name__ == '__main__':
    main()
