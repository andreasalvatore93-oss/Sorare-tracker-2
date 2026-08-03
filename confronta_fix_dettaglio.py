"""confronta_fix_dettaglio — quanto vale davvero il fix delle partite senza dettaglio.

PERCHE' SERVE UN BANCO A PARTE. Tutte le misure del repo passano da
`backtest_arene_previsioni.finestra_storica`, che SCARTA le partite di cui non
c'e' il dettaglio granulare in cache. La produzione invece le tiene: le scarica
sempre, e quando la chiamata fallisce si ritrova con `detail = None`. Fino al
03/08 in quel caso `extract_level_score` tornava 0.0 e l'intero punteggio della
partita finiva nel "granulare", con sopra il livello base 35 riaggiunto: pura
sovrastima.

Quindi il banco aggirava il problema e la produzione lo subiva, e nessuna misura
di MAE poteva vederlo. Qui la finestra storica si costruisce come in produzione
-- partite senza dettaglio INCLUSE -- e si confrontano le due formule sugli
stessi identici ingressi:

  PRIMA: partita senza dettaglio = level_score 0, granulare = punteggio intero
  DOPO : partita senza dettaglio = peso 0 (mask_weights)

Uso:  python confronta_fix_dettaglio.py [--max N]
"""
import argparse
import collections
import datetime
import json
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLI = ('Goalkeeper', 'Defender', 'Midfielder', 'Forward')
MIN_STORICO = 5


def _data(nodo):
    return ((nodo.get('anyGame') or {}).get('date') or '')[:10]


def finestra_come_produzione(cache, slug, cutoff, competizione):
    """Come prev.finestra_storica ma SENZA scartare le partite prive di
    dettaglio: e' cio' che fa build_prediction in produzione."""
    limite = cutoff - datetime.timedelta(days=prev.MAX_HISTORY_DAYS)
    passate = [n for n in cache.gamelog(slug)
               if (prev._dt(_data(n)) or limite) < cutoff
               and (prev._dt(_data(n)) or limite) >= limite]
    if not passate:
        return None, None
    if competizione:
        stessa = [n for n in passate
                  if (n.get('anyGame', {}).get('competition') or {}).get('slug') == competizione]
        if len(stessa) >= prev.MIN_SAME_COMPETITION:
            passate = stessa
    usable, totale = [], 0
    for nodo in reversed(passate):
        stato = nodo.get('scoreStatus')
        if stato == 'DID_NOT_PLAY':
            totale += 1
            continue
        if stato in ('FINAL', 'REVIEWING'):
            mins = (nodo.get('anyPlayerGameStats') or {}).get('minsPlayed')
            if mins is not None and mins < prev.test_def.MIN_MINUTES_PLAYED:
                totale += 1
                continue
            totale += 1
            usable.append(nodo)
        if len(usable) >= prev.WINDOW_SIZE:
            break
    if len(usable) < prev.MIN_USABLE_GAMES:
        return None, None
    usable.reverse()
    return usable, (len(usable) / totale if totale else 1.0)


def contesto_produzione(cache, slug, ruolo, fine_giornata):
    modulo = prev._MODULO.get(ruolo)
    if modulo is None:
        return None
    target = prev.partita_target(cache, slug, fine_giornata)
    if target is None:
        return None
    cutoff = prev._data(target)          # gia' un datetime, non una stringa
    competizione = ((target['anyGame'].get('competition') or {}).get('slug'))
    usable, presenza = finestra_come_produzione(cache, slug, cutoff, competizione)
    if not usable:
        return None
    squadra = prev._squadra(usable, competizione)
    _own, opp_rank, casa = modulo.team_ranking_from_game(target['anyGame'], squadra)
    s = prev._serie(modulo, cache, slug, usable, squadra)
    ok = [cache.dettaglio_partita(slug, n['id'].replace('So5Score:', '')) is not None
          for n in usable]
    return {'modulo': modulo, 'ruolo': ruolo, 's': s, 'casa': casa,
            'opp_rank': opp_rank, 'presenza': presenza,
            'detail_ok_flags': ok, 'senza': sum(1 for x in ok if not x)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/confronto_fix_dettaglio.json')
    args = ap.parse_args()

    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache' % len(slugs))

    righe = []
    for i, slug in enumerate(slugs, 1):
        if args.max and i > args.max:
            break
        conteggi = collections.Counter()
        for nodo in cache.gamelog(slug):
            p = nodo.get('positionTyped') or nodo.get('position')
            if p in RUOLI:
                conteggi[p] += 1
        if not conteggi:
            continue
        ruolo = conteggi.most_common(1)[0][0]
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale, data = nodo.get('score'), _data(nodo)
            if reale is None or not data:
                continue
            giorno = datetime.datetime.strptime(data, '%Y-%m-%d') + datetime.timedelta(days=1)
            try:
                ctx = contesto_produzione(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < MIN_STORICO:
                continue
            try:
                prima = prev.calcola(ctx)                    # nessuna maschera
                ctx2 = dict(ctx)
                dopo = prev.calcola_con_maschera(ctx2)
            except Exception:
                continue
            righe.append([slug, ruolo, data, prima, dopo, reale, ctx['senza'], len(ctx['s']['scores'])])
        if i % 300 == 0:
            print('  [%d/%d] %d righe' % (i, len(slugs), len(righe)), flush=True)

    print('%d righe\n' % len(righe))
    tocc = [r for r in righe if r[6] > 0]
    print('partite la cui finestra contiene almeno una gara senza dettaglio: '
          '%d su %d (%.1f%%)' % (len(tocc), len(righe), 100 * len(tocc) / max(len(righe), 1)))
    giocatori_tocc = len({r[0] for r in tocc})
    print('giocatori interessati: %d su %d (%.1f%%)'
          % (giocatori_tocc, len({r[0] for r in righe}),
             100 * giocatori_tocc / max(len({r[0] for r in righe}), 1)))

    def blocco(nome, sotto):
        if not sotto:
            return
        ep = statistics.mean(abs(r[5] - r[3]) for r in sotto)
        ed = statistics.mean(abs(r[5] - r[4]) for r in sotto)
        sovra = statistics.mean(r[3] - r[4] for r in sotto)
        meglio = sum(1 for r in sotto if abs(r[5] - r[4]) < abs(r[5] - r[3]))
        print('\n%s (%d casi)' % (nome, len(sotto)))
        print('  errore medio PRIMA: %.3f   DOPO: %.3f   (%+.2f%%)'
              % (ep, ed, (ed - ep) / ep * 100))
        print('  la vecchia formula sovrastimava di %.2f punti in media (max %.1f)'
              % (sovra, max(r[3] - r[4] for r in sotto)))
        print('  casi in cui il nuovo sbaglia meno: %d (%.1f%%)'
              % (meglio, 100 * meglio / len(sotto)))

    blocco('SOLO le previsioni toccate dal fix', tocc)
    blocco('TUTTE le previsioni', righe)

    # ATTENZIONE ALLA LETTURA. Questo campione viene dalla cache del backtest,
    # dove per molti giocatori il dettaglio non e' mai stato scaricato: la
    # quota di partite senza dettaglio e' molto piu' alta che in produzione,
    # dove il predict lo scarica sempre e fallisce solo ogni tanto (misurato
    # sulle cache di produzione: il 3.3% delle partite nella finestra usata).
    # Quindi il totale qui sopra e' un limite superiore, non il numero di
    # produzione. La riga che assomiglia alla produzione e' "1 partita su
    # ~20-30": e' li' che va letto l'effetto vero.
    print('\n\nEFFETTO PER QUANTITA\' DI PARTITE SENZA DETTAGLIO NELLA FINESTRA')
    print('(in produzione il caso tipico e\' 0 o 1: il dettaglio si scarica sempre,')
    print(' fallisce nel 3.3% delle partite -- vedi il commento nel codice)')
    print('%-14s %7s %9s %9s %9s %12s' % ('mancanti', 'casi', 'err PRIMA', 'err DOPO',
                                          'variaz.', 'sovrastima'))
    fasce = [(0, 0, 'nessuna'), (1, 1, '1'), (2, 3, '2-3'), (4, 8, '4-8'), (9, 999, '9 o piu\'')]
    for lo, hi, eti in fasce:
        sotto = [r for r in righe if lo <= r[6] <= hi]
        if not sotto:
            continue
        ep = statistics.mean(abs(r[5] - r[3]) for r in sotto)
        ed = statistics.mean(abs(r[5] - r[4]) for r in sotto)
        sovra = statistics.mean(r[3] - r[4] for r in sotto)
        print('%-14s %7d %9.2f %9.2f %8.2f%% %12.2f'
              % (eti, len(sotto), ep, ed, (ed - ep) / ep * 100 if ep else 0, sovra))

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump({'n': len(righe), 'toccate': len(tocc)}, fh)
    return 0


if __name__ == '__main__':
    sys.exit(main())
