# -*- coding: utf-8 -*-
"""STIAMO BUTTANDO VIA SEGNALE TAGLIANDO A 365 GIORNI? (14/08/2026)

DA DOVE NASCE. p67: due terzi del valore del voto sono "questo giocatore e'
forte", cioe' un difetto nostro. p68: il voto ci batte il DOPPIO sui
giocatori con poche partite recenti. p69: la cura ovvia (piu' shrinkage) non
funziona, perche' la calibrazione uno shrinkage lo fa gia'.

RESTA UNA SPIEGAZIONE SEMPLICE E MAI CONTROLLATA: che quei giocatori siano
"poco osservati" **solo perche' li tagliamo noi**. Il modello guarda
MAX_HISTORY_DAYS = 365 giorni (test_def.py:2102 e gemelli, e
backtest_arene_previsioni.py:38), ma la cache contiene lo storico COMPLETO
-- fino al 2013. Se prima di quel taglio c'e' segnale, il buco e' nostro e
si chiude senza chiedere niente a Sorare.

IL TEST. Per ogni carta-giornata si calcola:
  - residuo = realizzato - atteso (l'errore che lasciamo sul tavolo);
  - media VECCHIA = punteggi del giocatore fra 365 e 1095 giorni prima
    della giornata, cioe' la parte di storico che il modello NON guarda,
    espressa come scarto dalla media del suo ruolo (altrimenti si misura
    solo "i forti sono forti").
Se la media vecchia correla col residuo, quel pezzo di storico contiene
informazione che stiamo buttando. Si guarda in totale e per fascia di
esperienza RECENTE: l'ipotesi e' che serva soprattutto a chi ha pochi dati
nell'ultimo anno.

Walk-forward stretto: solo partite precedenti al primo calcio d'inizio.
Deduplicazione su (slug, fixture): trappola §15.

Uso: python analisi_manager/p70_storico_oltre_anno.py
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

RECENTE = 365          # cio' che il modello guarda
VECCHIO = 1095         # fin dove andiamo a scavare (3 anni)
MIN_MINUTI = 60
cache = CACHE.CacheLocale()
_memo = {}


def storico(slug, cutoff):
    """(n_recenti, media_vecchia, n_vecchie): partite piene prima del cutoff,
    divise fra dentro e fuori la finestra che il modello guarda."""
    k = (slug, cutoff.date().isoformat())
    if k in _memo:
        return _memo[k]
    limite_rec = cutoff - datetime.timedelta(days=RECENTE)
    limite_vec = cutoff - datetime.timedelta(days=VECCHIO)
    rec, vec = 0, []
    for n in cache.gamelog(slug) or []:
        d = P._dt((n.get('anyGame') or {}).get('date'))
        if d is None or d >= cutoff:
            continue
        st = n.get('anyPlayerGameStats') or {}
        if (st.get('minsPlayed') or 0) < MIN_MINUTI:
            continue
        s = n.get('score')
        if s is None:
            continue
        if d >= limite_rec:
            rec += 1
        elif d >= limite_vec:
            vec.append(float(s))
    out = (rec, (sum(vec) / len(vec)) if vec else None, len(vec))
    _memo[k] = out
    return out


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


def riga(eti, sub):
    if len(sub) < 150:
        print('  %-26s n=%5d  troppo pochi' % (eti, len(sub)))
        return
    xs = [r['vecchia_scarto'] for r in sub]
    ys = [r['residuo'] for r in sub]
    c = corr(xs, ys)
    lo, hi = boot_corr(xs, ys)
    nota = '   <-- esclude lo zero' if not (lo <= 0 <= hi) else ''
    print('  %-26s n=%5d  corr %+.4f  IC95[%+.4f;%+.4f]%s'
          % (eti, len(sub), c, lo, hi, nota))


def main():
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    visti = {}
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        cutoff = pre['primo_kickoff']
        for r in pre['pool_rows']:
            k = (r['slug'], fx)
            if k in visti or r.get('reale') is None or r.get('_cal') is None:
                continue
            rec, media_vec, n_vec = storico(r['slug'], cutoff)
            if media_vec is None:
                continue
            visti[k] = {'slug': r['slug'], 'codice': r['codice'],
                        'residuo': r['reale'] - r['_cal'],
                        'vecchia': media_vec, 'n_vecchie': n_vec,
                        'recenti': rec}
    righe = list(visti.values())
    print('osservazioni con storico OLTRE l\'anno disponibile: %d' % len(righe))
    if len(righe) < 500:
        print('troppo poche.')
        return
    quante = collections.Counter()
    for r in righe:
        quante['con >=5 vecchie'] += 1 if r['n_vecchie'] >= 5 else 0
    print('di cui con almeno 5 partite vecchie: %d' % quante['con >=5 vecchie'])

    # scarto dalla media di ruolo, altrimenti si misura "i forti sono forti"
    per_ruolo = collections.defaultdict(list)
    for r in righe:
        per_ruolo[r['codice']].append(r['vecchia'])
    med = {k: sum(v) / len(v) for k, v in per_ruolo.items()}
    for r in righe:
        r['vecchia_scarto'] = r['vecchia'] - med[r['codice']]

    print()
    print('LA MEDIA OLTRE L\'ANNO SPIEGA IL RESIDUO?')
    riga('tutti', righe)
    print()
    print('per partite RECENTI (quelle che il modello vede):')
    for lo, hi in ((0, 10), (10, 20), (20, 35), (35, 999)):
        sub = [r for r in righe if lo <= r['recenti'] < hi and r['n_vecchie'] >= 5]
        riga('%d-%d recenti' % (lo, hi if hi < 999 else 99), sub)
    print()
    print('per ruolo (solo con >=5 partite vecchie):')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        riga(cod, [r for r in righe if r['codice'] == cod and r['n_vecchie'] >= 5])

    print()
    print('COME SI LEGGE: se la correlazione e\' positiva e l\'intervallo esclude')
    print('lo zero -- soprattutto sulle fasce con POCHE partite recenti -- allora')
    print('il taglio a 365 giorni ci sta facendo buttare informazione, e la cura')
    print('e\' allungare la finestra lasciando che sia l\'half-life a pesare il')
    print('vecchio meno del nuovo. Se e\' zero, il taglio e\' giusto e la')
    print('spiegazione va cercata altrove.')


if __name__ == '__main__':
    main()
