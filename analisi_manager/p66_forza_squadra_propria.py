# -*- coding: utf-8 -*-
"""LA FORZA DELLA PROPRIA SQUADRA SPIEGA QUALCOSA? (13/08/2026)

L'ULTIMO PEZZO DEL FILONE INTRALEGA, quello che l'utente aveva intuito e
che non era mai stato toccato. Non il livello della LEGA (§8terdecies,
misurato e lasciato spento) e non il confronto fra i reparti che si
affrontano (§8quaterdecies, chiuso): **quanto e' forte la squadra in cui il
giocatore sta adesso**. Casi che l'hanno fatto nascere: Ernst al Feyenoord
(lega piu' facile ma squadra forte) e Simsir al Trabzonspor (lega piu' dura
ma squadra forte).

PRIMO PASSO ECONOMICO, prima di costruire qualunque correzione: la forza
della propria squadra spiega qualcosa del RESIDUO (realizzato - atteso)?
Se il modello la cattura gia' -- e potrebbe, visto che lo storico personale
di un giocatore incorpora il contesto in cui giocava -- la correlazione e'
zero e il filone si chiude senza scrivere una riga di produzione.

COME
- residuo = punteggio REALE - atteso calibrato, per carta-giornata.
- forza squadra = media della serie storica di QUELLA squadra in QUEL
  reparto (analisi_manager/dati/intralega_serie.json, 1.212 serie), presa
  SOLO sulle date precedenti al primo calcio d'inizio della giornata --
  walk-forward stretto, finestra 365 giorni, minimo 3 partite.
- si correla il residuo con la forza, e con lo SCARTO della forza dalla
  media della lega (che e' la domanda vera: "squadra forte DENTRO la sua
  lega", non "lega forte", che e' gia' §8terdecies).

TRAPPOLA APPLICATA (§15 delle trappole): lo stesso giocatore-giornata
compare una volta per ogni manager che lo schiera. Qui si DEDUPLICA su
(slug, fixture) prima di correlare, altrimenti l'n e' gonfiata e ogni
intervallo esce falsamente stretto.

Uso: python analisi_manager/p66_forza_squadra_propria.py
"""
import os
import sys
import io
import json
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

SERIE_PATH = os.path.join('analisi_manager', 'dati', 'intralega_serie.json')
FINESTRA_GIORNI = 365
MIN_PARTITE_SERIE = 3


def carica_serie():
    with open(SERIE_PATH, encoding='utf-8') as fh:
        d = json.load(fh)
    fuori = {}
    for chiave, punti in d['serie'].items():
        fuori[chiave] = [(datetime.date.fromisoformat(dt), float(v))
                         for dt, v in punti]
    return fuori


def forza(serie, lega, squadra, codice, cutoff):
    """Media della squadra in quel reparto PRIMA del cutoff. None se pochi dati."""
    chiave = '%s|%s|%s' % (lega, squadra, codice.lower())
    punti = serie.get(chiave)
    if not punti:
        return None
    limite = cutoff - datetime.timedelta(days=FINESTRA_GIORNI)
    vals = [v for d, v in punti if limite <= d < cutoff]
    if len(vals) < MIN_PARTITE_SERIE:
        return None
    return sum(vals) / len(vals)


def correlazione(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def boot_corr(xs, ys, n_boot=2000, seed=20260813):
    rnd = random.Random(seed)
    n = len(xs)
    out = []
    for _ in range(n_boot):
        idx = [rnd.randrange(n) for _i in range(n)]
        out.append(correlazione([xs[i] for i in idx], [ys[i] for i in idx]))
    out.sort()
    return out[int(0.025 * n_boot)], out[int(0.975 * n_boot)]


def main():
    serie = carica_serie()
    print('serie squadra-reparto caricate: %d' % len(serie))
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    visti = {}          # (slug, fixture) -> riga, per deduplicare
    senza_serie = 0
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        cutoff = pre['primo_kickoff'].date()
        for r in pre['pool_rows']:
            chiave = (r['slug'], fx)
            if chiave in visti:
                continue
            if r.get('reale') is None or r.get('_cal') is None:
                continue
            f = forza(serie, r.get('lega'), r.get('squadra'), r['codice'], cutoff)
            if f is None:
                senza_serie += 1
                continue
            visti[chiave] = {'residuo': r['reale'] - r['_cal'], 'forza': f,
                             'lega': r.get('lega'), 'codice': r['codice'],
                             'reale': r['reale'], 'cal': r['_cal']}

    righe = list(visti.values())
    print('osservazioni carta-giornata DEDUPLICATE: %d  (scartate per serie '
          'troppo corta: %d)' % (len(righe), senza_serie))
    if len(righe) < 100:
        print('troppo poche per dire qualcosa.')
        return

    # scarto della forza dalla media della sua lega+reparto: e' la domanda vera
    per_gruppo = collections.defaultdict(list)
    for r in righe:
        per_gruppo[(r['lega'], r['codice'])].append(r['forza'])
    media_gruppo = {k: sum(v) / len(v) for k, v in per_gruppo.items()}
    for r in righe:
        r['scarto'] = r['forza'] - media_gruppo[(r['lega'], r['codice'])]

    print()
    print('%-28s %8s %9s %20s' % ('misura', 'n', 'corr', 'IC95'))
    for eti, chiave in (('forza squadra (assoluta)', 'forza'),
                        ('scarto dalla lega+ruolo', 'scarto')):
        xs = [r[chiave] for r in righe]
        ys = [r['residuo'] for r in righe]
        c = correlazione(xs, ys)
        lo, hi = boot_corr(xs, ys)
        print('%-28s %8d %9.4f  [%+.4f;%+.4f]' % (eti, len(righe), c, lo, hi))

    print()
    print('per ruolo, sullo SCARTO (la domanda vera):')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        sub = [r for r in righe if r['codice'] == cod]
        if len(sub) < 100:
            print('  %-4s n=%d, troppo pochi' % (cod, len(sub)))
            continue
        xs = [r['scarto'] for r in sub]
        ys = [r['residuo'] for r in sub]
        c = correlazione(xs, ys)
        lo, hi = boot_corr(xs, ys)
        print('  %-4s n=%5d  corr %+.4f  IC95[%+.4f;%+.4f]' % (cod, len(sub), c, lo, hi))

    print()
    print('quintili di scarto (squadra debole -> forte), residuo medio:')
    ordinati = sorted(righe, key=lambda r: r['scarto'])
    q = max(1, len(ordinati) // 5)
    for i in range(5):
        fetta = ordinati[i * q:(i + 1) * q] if i < 4 else ordinati[4 * q:]
        m = sum(r['residuo'] for r in fetta) / len(fetta)
        ms = sum(r['scarto'] for r in fetta) / len(fetta)
        print('  Q%d  n=%5d  scarto medio %+6.2f  residuo medio %+6.2f'
              % (i + 1, len(fetta), ms, m))

    print()
    print('COME SI LEGGE: se la correlazione e\' praticamente zero e i quintili')
    print('non mostrano una salita, il modello cattura gia\' la forza della')
    print('squadra propria (lo storico personale la incorpora) e non c\'e\'')
    print('niente da aggiungere. Se invece i quintili salgono, il residuo e\'')
    print('spiegato e vale la pena costruire una correzione.')


if __name__ == '__main__':
    main()
