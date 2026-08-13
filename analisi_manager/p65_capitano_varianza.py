# -*- coding: utf-8 -*-
"""CAPITANO E VARIANZA -- vale la coda alta invece della media? (13/08/2026)

PREMESSA TEORICA, da leggere prima dei numeri. Il bonus capitano e'
LINEARE: +20% del punteggio realizzato. Quindi in puro valore atteso
massimizzare la media massimizza il bonus, e la varianza NON entra --
non e' un'opinione, e' aritmetica. La coda alta conterebbe solo se
l'obiettivo fosse non lineare, tipo P(podio); ma per calcolare il podio
contro-fattuale servirebbero i punteggi degli altri 9 partecipanti, che
l'archivio non ha (scelta esplicita: le soglie calibrate bastano).

QUINDI COSA SI TESTA QUI, che e' una cosa diversa e sensata: `atteso` non
e' la media vera, e' una STIMA. Se il modello sbaglia in modo sistematico
sui giocatori piu' volatili -- per esempio se comprime verso il basso chi
ha la coda lunga -- allora correggere la scelta con la dispersione
storica migliorerebbe il capitano NON perche' la varianza sia desiderabile
in se', ma perche' compensa un errore di stima. Questo si misura con i
dati che abbiamo.

REGOLE A CONFRONTO, sulle stesse 5 carte (cambia solo chi porta la fascia):
  PRODUZIONE   atteso piu' alto (col margine portiere di 6,7)
  atteso + k*sd   per k = -0,50 / -0,25 / +0,25 / +0,50 / +1,00
  SOLO SD      il piu' volatile, ignorando l'atteso (controllo estremo)
  ORACOLO      il punteggio realizzato piu' alto (tetto)

sd = deviazione standard dei punteggi GREZZI del giocatore nelle partite
PRECEDENTI al primo calcio d'inizio della giornata (walk-forward stretto,
finestra 365 giorni, minimo 4 partite; sotto quel minimo sd=0, cioe' la
riga si comporta come la produzione e non inquina il confronto).

Uso: python analisi_manager/p65_capitano_varianza.py
"""
import os
import sys
import io
import math
import random
import datetime
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
import backtest_arene_cache as CACHE  # noqa: E402
import backtest_arene_previsioni as P  # noqa: E402

BONUS = 0.20
GK_CAPTAIN_MARGIN = 6.7
FINESTRA_GIORNI = 365
MIN_PARTITE = 4
KAPPA = [-0.50, -0.25, 0.25, 0.50, 1.00]

cache = CACHE.CacheLocale()
_sd_memo = {}


def sd_storica(slug, cutoff):
    """Dispersione dei punteggi prima del cutoff. 0.0 se troppo pochi dati."""
    chiave = (slug, cutoff.date().isoformat())
    if chiave in _sd_memo:
        return _sd_memo[chiave]
    inizio = cutoff - datetime.timedelta(days=FINESTRA_GIORNI)
    punti = []
    for n in cache.gamelog(slug) or []:
        d = P._dt((n.get('anyGame') or {}).get('date'))
        if d is None or not (inizio <= d < cutoff):
            continue
        s = n.get('score')
        if s is None:
            continue
        mins = ((n.get('anyPlayerGameStats') or {}).get('minsPlayed')) or 0
        if mins <= 0:
            continue          # le assenze non sono volatilita' di rendimento
        punti.append(float(s))
    if len(punti) < MIN_PARTITE:
        _sd_memo[chiave] = 0.0
        return 0.0
    m = sum(punti) / len(punti)
    sd = math.sqrt(sum((x - m) ** 2 for x in punti) / (len(punti) - 1))
    _sd_memo[chiave] = sd
    return sd


def scegli(carte, chiave):
    mov = [c for c in carte if c['codice'] != 'GK']
    gk = [c for c in carte if c['codice'] == 'GK']
    bm = max(mov, key=chiave) if mov else None
    bg = max(gk, key=chiave) if gk else None
    if bm is None:
        return bg
    if bg is not None and chiave(bg) >= chiave(bm) + GK_CAPTAIN_MARGIN:
        return bg
    return bm


def boot(per_unita, a, b, n_boot=4000, seed=20260813):
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

    nomi = ['PRODUZIONE'] + ['k=%+.2f' % k for k in KAPPA] + ['SOLO SD', 'ORACOLO']
    totali = collections.Counter()
    per_unita = collections.defaultdict(lambda: collections.Counter())
    n_form = 0
    diversi = collections.Counter()
    sd_viste = []
    for manager, fx, path in fixtures:
        pre = B1.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        S21.applica_gruppi_grade(pre['pool_rows'], modo='lega_ruolo')
        riga = {r['carta']: r for r in pre['pool_rows']}
        cutoff = pre['primo_kickoff']
        for form in pre['pulite']:
            carte, ok = [], True
            for c in form['carte']:
                r = riga.get(c.get('carta'))
                if r is None or c.get('punteggio') is None:
                    ok = False
                    break
                grezzo = c['punteggio'] / 1.2 if c.get('capitano') else c['punteggio']
                carte.append({'slug': c['slug'], 'codice': r['codice'],
                              'atteso': r['_combinato'], 'reale': grezzo,
                              'sd': sd_storica(c['slug'], cutoff)})
            if not ok or len(carte) != 5:
                continue
            n_form += 1
            sd_viste.extend(c['sd'] for c in carte)
            k_unita = (manager, fx)
            base = scegli(carte, lambda c: c['atteso'])
            totali['PRODUZIONE'] += BONUS * base['reale']
            per_unita[k_unita]['PRODUZIONE'] += BONUS * base['reale']
            for k in KAPPA:
                nome = 'k=%+.2f' % k
                c = scegli(carte, lambda c, k=k: c['atteso'] + k * c['sd'])
                totali[nome] += BONUS * c['reale']
                per_unita[k_unita][nome] += BONUS * c['reale']
                if c['slug'] != base['slug']:
                    diversi[nome] += 1
            c = scegli(carte, lambda c: c['sd'])
            totali['SOLO SD'] += BONUS * c['reale']
            per_unita[k_unita]['SOLO SD'] += BONUS * c['reale']
            if c['slug'] != base['slug']:
                diversi['SOLO SD'] += 1
            o = max(carte, key=lambda c: c['reale'])
            totali['ORACOLO'] += BONUS * o['reale']
            per_unita[k_unita]['ORACOLO'] += BONUS * o['reale']

    sd_ok = [s for s in sd_viste if s > 0]
    print('=' * 96)
    print('CAPITANO E VARIANZA -- %d formazioni, %d unita\'' % (n_form, len(per_unita)))
    print('dispersione storica calcolata su %d carte-formazione su %d (%.0f%%); '
          'mediana %.1f punti'
          % (len(sd_ok), len(sd_viste), 100.0 * len(sd_ok) / max(1, len(sd_viste)),
             sorted(sd_ok)[len(sd_ok) // 2] if sd_ok else 0.0))
    print('=' * 96)
    print('%-12s %14s %12s %14s' % ('regola', 'essenze bonus', 'per arena', 'cambia in'))
    for nome in nomi:
        print('%-12s %14.0f %12.3f %14s'
              % (nome, totali[nome], totali[nome] / max(1, n_form),
                 diversi.get(nome, '-') if nome in diversi else '-'))
    print()
    print('DELTA contro PRODUZIONE (bootstrap sui manager):')
    for nome in nomi:
        if nome in ('PRODUZIONE', 'ORACOLO'):
            continue
        r = boot(per_unita, 'PRODUZIONE', nome)
        print('  %-10s %+9.1f  IC95[%+9.1f;%+9.1f]  positivo %5.1f%%'
              % (nome, r['delta'], r['lo'], r['hi'], r['pct'] * 100))
    print()
    print('Se nessun k batte la produzione con l\'intervallo sopra lo zero, la')
    print('risposta e\' quella che l\'aritmetica gia\' suggeriva: il bonus e\'')
    print('lineare, la media e\' il criterio giusto, e l\'atteso non ha un errore')
    print('sistematico legato alla volatilita\' da correggere.')


if __name__ == '__main__':
    main()
