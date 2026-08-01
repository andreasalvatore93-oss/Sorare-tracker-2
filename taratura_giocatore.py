"""taratura_giocatore — calibra previsione contro realizzato su MIGLIAIA di casi.

PERCHE'. La soglia d'ingresso in arena e' il numero su cui l'utente vuole
agganciare gli acquisti: un solo punto sposta la scelta fra un giocatore e un
altro. Misurata sulle 306 formazioni del backtest esce **269.2 punti, ma con un
intervallo al 90% fra 258.8 e 273.9** -- quindici punti, inutilizzabile per
decidere un acquisto.

Il bootstrap dice da dove viene quell'incertezza: **4.6 punti dalla taratura**
(612 coppie previsione/realizzato) contro 2.1 dal campo avversario (gia'
campionato bene con 673 arene). Quindi non servono altre arene: servono altre
coppie.

E per calibrare non serve che le formazioni siano dell'utente, ne' che siano
arene. Serve solo una previsione fatta walk-forward e il punteggio realizzato:
due cose che esistono per **ogni giocatore in ogni partita** dello storico gia'
in cache. Da 612 coppie si passa a decine di migliaia.

COSA FA. Per ogni (giocatore, partita) in cache rigioca la previsione di
produzione con i soli dati precedenti a quella data, e la confronta col
punteggio realizzato. Da li' ricava:

  - la retta di calibrazione a livello di GIOCATORE
  - la dispersione dell'errore del singolo giocatore
  - la **correlazione fra compagni di squadra**, che serve perche' l'errore di
    una formazione NON e' semplicemente radice-di-cinque volte quello del
    singolo: se una squadra prende tre gol, portiere e difensori sbagliano
    insieme.

Uso:  python taratura_giocatore.py               # tutti i giocatori in cache
      python taratura_giocatore.py --max 300     # prova rapida
      python taratura_giocatore.py --json out.json
"""
import argparse
import collections
import datetime
import json
import math
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLI = ('Goalkeeper', 'Defender', 'Midfielder', 'Forward')
# Sotto questa soglia di partite precedenti la previsione non e' quella che il
# modello userebbe davvero in produzione, e sporcherebbe la calibrazione.
MIN_STORICO = 5


def _data(nodo):
    return ((nodo.get('anyGame') or {}).get('date') or '')[:10]


def _ruolo_di(cache, slug):
    """Il ruolo con cui il giocatore compare piu' spesso nel game log."""
    conteggi = collections.Counter()
    for nodo in cache.gamelog(slug):
        p = nodo.get('positionTyped') or nodo.get('position')
        if p in RUOLI:
            conteggi[p] += 1
    return conteggi.most_common(1)[0][0] if conteggi else None


def raccogli(cache, slugs, limite=None):
    """[(slug, data, squadra, previsto, realizzato)] su tutto lo storico."""
    coppie = []
    for i, slug in enumerate(slugs, 1):
        if limite and i > limite:
            break
        ruolo = _ruolo_di(cache, slug)
        if ruolo is None:
            continue
        nodi = cache.gamelog(slug)
        for nodo in nodi:
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale = nodo.get('score')
            data = _data(nodo)
            if reale is None or not data:
                continue
            # la previsione va fatta come se fosse il giorno prima
            giorno = datetime.datetime.strptime(data, '%Y-%m-%d')
            try:
                r = prev.score_atteso(cache, slug, ruolo,
                                      giorno + datetime.timedelta(days=1))
            except Exception:
                continue
            if not r or r.get('atteso') is None:
                continue
            if (r.get('partite_storiche') or 0) < MIN_STORICO:
                continue
            g = nodo.get('anyGame') or {}
            # ATTENZIONE: per raggruppare i COMPAGNI serve la squadra del
            # giocatore, non quella di casa. Usando homeTeam si mettevano
            # insieme le due squadre della partita, e le correlazioni di
            # compagni e avversari si annullavano a vicenda (usciva rho=0.002).
            coppie.append({'slug': slug, 'data': data,
                           'partita': g.get('id') or '',
                           'squadra': r.get('squadra'),
                           'competizione': (g.get('competition') or {}).get('slug'),
                           'ruolo': ruolo, 'in_casa': r.get('in_casa'),
                           'previsto': r['atteso'], 'reale': reale})
        if i % 50 == 0:
            print(f'  [{i}/{len(slugs)}] {len(coppie)} coppie', flush=True)
    return coppie


def retta(X, Y):
    n = len(X)
    mx = statistics.mean(X)
    my = statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(X, Y)]
    return a, b, statistics.pstdev(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json')
    args = ap.parse_args()

    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print(f'{len(slugs)} giocatori in cache')
    coppie = raccogli(cache, slugs, args.max or None)
    if len(coppie) < 100:
        print(f'Solo {len(coppie)} coppie: troppo poche.')
        return 1

    # le coppie si salvano SEMPRE: ricalcolarle costa mezz'ora, e servono a
    # tutte le analisi successive (bias per ruolo, per lega, correlazioni)
    with open('dati_globali/taratura_coppie.json', 'w', encoding='utf-8') as fh:
        json.dump(coppie, fh, ensure_ascii=False)
    print(f'  coppie salvate in dati_globali/taratura_coppie.json')

    X = [c['previsto'] for c in coppie]
    Y = [c['reale'] for c in coppie]
    a, b, sd = retta(X, Y)
    print(f'\n=== TARATURA DEL SINGOLO GIOCATORE ({len(coppie)} coppie)')
    print(f'  realizzato = {a:.2f} + {b:.3f} x previsto')
    print(f'  errore del singolo giocatore: {sd:.2f} punti')
    print(f'  bias medio: {statistics.mean(x - y for x, y in zip(X, Y)):+.2f}')

    # correlazione fra compagni: stessa squadra, stessa data
    per_partita = collections.defaultdict(list)
    for c in coppie:
        if c.get('squadra') and c.get('partita'):
            per_partita[(c['partita'], c['squadra'])].append(
                c['reale'] - (a + b * c['previsto']))
    coppie_res = []
    for v in per_partita.values():
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                coppie_res.append((v[i], v[j]))
    if len(coppie_res) > 50:
        A = [x for x, _ in coppie_res]
        B = [y for _, y in coppie_res]
        ma, mb = statistics.mean(A), statistics.mean(B)
        cov = sum((x - ma) * (y - mb) for x, y in zip(A, B)) / len(A)
        rho = cov / (statistics.pstdev(A) * statistics.pstdev(B))
        print(f'\n=== CORRELAZIONE FRA COMPAGNI ({len(coppie_res)} coppie)')
        print(f'  rho = {rho:+.3f}')
    else:
        rho = 0.0
        print('\n  compagni: troppo pochi per misurare, assumo indipendenza')

    # errore di una formazione da 5, tenendo conto della correlazione
    n = 5
    indip = sd * math.sqrt(n)
    reale = sd * math.sqrt(n + n * (n - 1) * max(rho, 0.0))
    print(f'\n=== ERRORE DI UNA FORMAZIONE DA 5')
    print(f'  se i cinque fossero indipendenti: {indip:.1f} punti')
    print(f'  con la correlazione misurata:     {reale:.1f} punti')
    print(f'  (misurato sulle formazioni vere del backtest: 49.4)')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'n_coppie': len(coppie), 'intercetta': a, 'pendenza': b,
                       'errore_giocatore': sd, 'rho_compagni': rho,
                       'errore_formazione': reale}, fh, indent=1)
        print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
