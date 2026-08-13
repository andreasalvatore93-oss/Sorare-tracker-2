# -*- coding: utf-8 -*-
"""DOVE il voto ci batte nel misurare un giocatore (13-14/08/2026)

DA DOVE NASCE. Il placebo per-giocatore (p67) ha mostrato che **due terzi**
del valore del voto sono "questo giocatore e' forte", non "questa partita
andra' bene". Siccome la qualita' di un giocatore dovrebbe stare tutta nel
nostro storico, quei due terzi sono un difetto NOSTRO: la media pesata dei
punteggi passati non cattura del tutto quanto vale uno.

QUESTO SCRIPT NON PROPONE UNA CURA: dice DOVE sta il buco, cosi' la cura si
sceglie invece di indovinarla. Tre ipotesi, distinguibili dai dati:
  1. POCHE PARTITE -- chi ha uno storico corto ha una media rumorosa, e noi
     non lo ancoriamo a niente. Se il vantaggio del voto e' concentrato sui
     giocatori con poche partite in cache, la cura e' un ancoraggio
     (shrinkage verso un livello di club/lega/ruolo).
  2. FINESTRA SBAGLIATA -- half_life fisso per ruolo, uguale per tutti.
     Si vedrebbe come vantaggio concentrato su chi ha molte partite ma
     eterogenee.
  3. BUCO SISTEMATICO -- il voto guarda qualcosa di strutturale che noi non
     guardiamo affatto. Si vedrebbe come vantaggio PIATTO rispetto al numero
     di partite.

COME
- residuo = punteggio REALE - `_cal` (l'atteso calibrato SENZA voto: e'
  esattamente cio' che il voto potrebbe spiegare).
- componente "chi" del voto = voto MEDIO di quel giocatore sulle sue ALTRE
  giornate (leave-one-out: la giornata in esame e' esclusa, altrimenti si
  userebbe l'informazione del giorno e si misurerebbe anche il "quando").
- si correla il residuo con quella media, in totale e per fascia di
  ESPERIENZA (partite giocate nei 365 giorni prima della giornata).
- deduplicazione su (slug, fixture): §15 delle trappole.

Uso: python analisi_manager/p68_dove_sbagliamo_il_giocatore.py
"""
import os
import sys
import io
import math
import random
import datetime
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
import backtest_arene_cache as CACHE  # noqa: E402
import backtest_arene_previsioni as P  # noqa: E402

FINESTRA_GIORNI = 365
cache = CACHE.CacheLocale()
_memo = {}


def partite_prima(slug, cutoff):
    k = (slug, cutoff.date().isoformat())
    if k in _memo:
        return _memo[k]
    inizio = cutoff - datetime.timedelta(days=FINESTRA_GIORNI)
    n = 0
    for nodo in cache.gamelog(slug) or []:
        d = P._dt((nodo.get('anyGame') or {}).get('date'))
        if d is None or not (inizio <= d < cutoff):
            continue
        if ((nodo.get('anyPlayerGameStats') or {}).get('minsPlayed') or 0) > 0:
            n += 1
    _memo[k] = n
    return n


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


def boot_corr(xs, ys, n_boot=1500, seed=20260814):
    rnd = random.Random(seed)
    n = len(xs)
    out = []
    for _ in range(n_boot):
        idx = [rnd.randrange(n) for _i in range(n)]
        out.append(corr([xs[i] for i in idx], [ys[i] for i in idx]))
    out.sort()
    return out[int(0.025 * n_boot)], out[int(0.975 * n_boot)]


def riga(eti, sub, chiave):
    if len(sub) < 150:
        print('  %-26s n=%5d  troppo pochi' % (eti, len(sub)))
        return
    xs = [r[chiave] for r in sub]
    ys = [r['residuo'] for r in sub]
    c = corr(xs, ys)
    lo, hi = boot_corr(xs, ys)
    stelle = '' if lo <= 0 <= hi else '   <-- esclude lo zero'
    print('  %-26s n=%5d  corr %+.4f  IC95[%+.4f;%+.4f]%s'
          % (eti, len(sub), c, lo, hi, stelle))


def main():
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    grezzo = {}
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        cutoff = pre['primo_kickoff']
        for r in pre['pool_rows']:
            k = (r['slug'], fx)
            if k in grezzo:
                continue
            if r.get('reale') is None or r.get('_cal') is None or r.get('_grade') is None:
                continue
            grezzo[k] = {'slug': r['slug'], 'fixture': fx, 'codice': r['codice'],
                         'residuo': r['reale'] - r['_cal'], 'voto': float(r['_grade']),
                         'cutoff': cutoff}

    per_slug = collections.defaultdict(list)
    for k, r in grezzo.items():
        per_slug[r['slug']].append(r)

    righe = []
    for slug, rs in per_slug.items():
        if len(rs) < 2:
            continue                      # senza altre giornate non c'e' leave-one-out
        somma = sum(r['voto'] for r in rs)
        for r in rs:
            r['voto_medio_altre'] = (somma - r['voto']) / (len(rs) - 1)
            r['esperienza'] = partite_prima(slug, r['cutoff'])
            righe.append(r)

    print('osservazioni (giocatore, giornata) deduplicate e con almeno 2 '
          'giornate: %d  |  giocatori: %d' % (len(righe), len(per_slug)))
    if len(righe) < 500:
        print('troppo poche.')
        return

    print()
    print('QUANTO SPIEGA IL VOTO, del residuo che lasciamo sul tavolo:')
    riga('voto DEL GIORNO', righe, 'voto')
    riga('voto MEDIO altre giornate', righe, 'voto_medio_altre')
    print('  (il primo contiene "chi" + "quando", il secondo solo "chi")')

    print()
    print('IL VOTO MEDIO (solo "chi"), PER FASCIA DI ESPERIENZA:')
    print('  esperienza = partite giocate nei 365 giorni prima della giornata')
    fasce = [(0, 5), (5, 10), (10, 20), (20, 35), (35, 999)]
    for lo, hi in fasce:
        sub = [r for r in righe if lo <= r['esperienza'] < hi]
        riga('%d-%d partite' % (lo, hi if hi < 999 else 99), sub, 'voto_medio_altre')

    print()
    print('PER RUOLO (solo "chi"):')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        riga(cod, [r for r in righe if r['codice'] == cod], 'voto_medio_altre')

    print()
    print('residuo medio per fascia di esperienza (dice se sbagliamo in')
    print('modo diverso i poco osservati):')
    for lo, hi in fasce:
        sub = [r for r in righe if lo <= r['esperienza'] < hi]
        if not sub:
            continue
        m = sum(r['residuo'] for r in sub) / len(sub)
        v = sum(r['voto_medio_altre'] for r in sub) / len(sub)
        print('  %-12s n=%5d  residuo medio %+6.2f  voto medio %.2f'
              % ('%d-%d' % (lo, hi if hi < 999 else 99), len(sub), m, v))

    print()
    print('COME SI LEGGE')
    print('  correlazione CONCENTRATA sulle fasce basse -> ipotesi 1: manca un')
    print('    ancoraggio per chi ha poche partite. Cura: shrinkage verso un')
    print('    livello di club/lega/ruolo.')
    print('  correlazione PIATTA su tutte le fasce -> ipotesi 3: il voto guarda')
    print('    qualcosa di strutturale che noi non guardiamo affatto, e va')
    print('    cercato cosa.')


if __name__ == '__main__':
    main()
