"""taratura_confronto_parametri — il MAE non basta a scegliere i parametri.

PERCHE'. Un modello che predice tutti vicino alla mediana ha un MAE ottimo ed
e' inutile: per schierare non serve indovinare il punteggio, serve ORDINARE i
candidati. E' lo stesso motivo per cui nel 2026-07 lo shrinkage e' stato
riconosciuto come "minimizza il MAE ma comprime le differenze". Un half_life
molto corto ha lo stesso rischio: insegue l'ultima partita, il MAE scende, ma
la previsione puo' diventare rumore travestito da segnale.

Quindi ogni combinazione candidata viene giudicata su quattro numeri, non uno:

  MAE          quanto sbaglia il singolo punteggio (piu' basso e' meglio)
  correlazione previsto contro realizzato: se crolla, il modello non ordina
  sd previsto  dispersione delle previsioni: se collassa, il modello dice
               "tutti uguali" e non puo' scegliere nessuno
  lift         quanto del divario fra "scegliere a caso" e "oracolo" viene
               catturato scegliendo i primi cinque della giornata

Uso:  python taratura_confronto_parametri.py --ruoli fwd,mid
      python taratura_confronto_parametri.py --ruoli fwd --candidati 25:0.15,4:0,1.5:0
"""
import argparse
import collections
import datetime
import json
import random
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_halflife_trend import RUOLI, MIN_STORICO, _data, _ruolo_di

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def raccogli(cache, slugs, voluti, limite=None):
    """[(ruolo, slug, data, contesto, realizzato)]"""
    fuori = []
    for i, slug in enumerate(slugs, 1):
        if limite and i > limite:
            break
        ruolo = _ruolo_di(cache, slug)
        if ruolo is None or ruolo not in voluti:
            continue
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale, data = nodo.get('score'), _data(nodo)
            if reale is None or not data:
                continue
            giorno = datetime.datetime.strptime(data, '%Y-%m-%d') + datetime.timedelta(days=1)
            try:
                ctx = prev.contesto(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < MIN_STORICO:
                continue
            fuori.append((ruolo, slug, data, ctx, reale))
        if i % 200 == 0:
            print('  [%d/%d] %d punti' % (i, len(slugs), len(fuori)), flush=True)
    return fuori


def lift_selezione(righe, quanti=5, prove=200, seme=3):
    """Quanto del divario caso->oracolo cattura la scelta dei primi 'quanti'.

    Per ogni giornata con abbastanza candidati: si ordina per previsione, si
    prendono i primi 'quanti', si somma il REALIZZATO. Si confronta con la
    media di scelte casuali (0%) e con la scelta perfetta (100%)."""
    per_data = collections.defaultdict(list)
    for _r, _s, data, prevv, reale in righe:
        per_data[data].append((prevv, reale))
    rnd = random.Random(seme)
    quote = []
    for data, v in per_data.items():
        if len(v) < quanti * 3:
            continue
        scelto = sum(r for _p, r in sorted(v, key=lambda x: -x[0])[:quanti])
        oracolo = sum(sorted((r for _p, r in v), reverse=True)[:quanti])
        caso = statistics.mean(
            sum(r for _p, r in rnd.sample(v, quanti)) for _ in range(prove))
        if oracolo - caso <= 0:
            continue
        quote.append((scelto - caso) / (oracolo - caso))
    return (statistics.mean(quote) * 100 if quote else None), len(quote)


def valuta(punti, hl, ti, favorito_k=None):
    righe = []
    for ruolo, slug, data, ctx, reale in punti:
        try:
            p = prev.calcola(ctx, half_life=hl, trend_intensity=ti,
                             favorito_k=favorito_k)
        except Exception:
            continue
        righe.append((ruolo, slug, data, p, reale))
    X = [r[3] for r in righe]
    Y = [r[4] for r in righe]
    mae = statistics.mean(abs(y - x) for x, y in zip(X, Y))
    mx, my = statistics.mean(X), statistics.mean(Y)
    sx, sy = statistics.pstdev(X), statistics.pstdev(Y)
    corr = (sum((a - mx) * (b - my) for a, b in zip(X, Y)) / len(X) / (sx * sy)
            if sx > 0 and sy > 0 else 0.0)
    lift, n_gg = lift_selezione(righe)
    return {'mae': mae, 'corr': corr, 'sd_prev': sx, 'sd_reale': sy,
            'bias': my - mx, 'lift': lift, 'giornate': n_gg, 'n': len(righe)}


def griglia_favorito(breve, punti, prod, spec):
    """La correzione di contesto partita, giudicata sullo stesso metro.

    Tiene half_life/trend di produzione e muove solo k: cosi' l'unica cosa che
    cambia fra le righe e' la correzione, e il confronto e' pulito. La riga
    k=0 e' il modello di oggi."""
    ks = [float(x) for x in spec.split(',') if x.strip()]
    if 0.0 not in ks:
        ks.insert(0, 0.0)
    hl, ti = prod
    print('=' * 96)
    print('%s -- %d punti | CONTESTO PARTITA (k punti per gol di differenziale atteso)' %
          (breve.upper(), len(punti)))
    print('half_life=%s trend=%s tenuti a produzione' % (hl, ti))
    print('=' * 96)
    print('%-16s %8s %8s %9s %8s %8s %7s' %
          ('k', 'MAE', 'corr', 'sd prev', 'sd real', 'bias', 'lift%'))
    risultati = []
    for k in ks:
        r = valuta(punti, hl, ti, favorito_k=k)
        r['favorito_k'] = k
        r['produzione'] = (k == 0.0)
        risultati.append(r)
        print('%-16s %8.3f %8.3f %9.2f %8.2f %+8.2f %7s%s' %
              ('%g' % k, r['mae'], r['corr'], r['sd_prev'], r['sd_reale'], r['bias'],
               ('%.1f' % r['lift']) if r['lift'] is not None else '--',
               '   <- oggi (spento)' if r['produzione'] else ''))
    base = risultati[0]
    print('\nregola CLAUDE.md: si applica solo se MAE, correlazione e lift migliorano INSIEME')
    for r in risultati[1:]:
        segni = (r['mae'] < base['mae'], r['corr'] > base['corr'],
                 (r['lift'] or 0) > (base['lift'] or 0))
        esito = 'PASSA' if all(segni) else 'no'
        print('  k=%-6g MAE %+6.3f  corr %+6.4f  lift %+5.1f   %s' %
              (r['favorito_k'], r['mae'] - base['mae'], r['corr'] - base['corr'],
               (r['lift'] or 0) - (base['lift'] or 0), esito))
    print()
    return risultati


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='fwd,mid')
    ap.add_argument('--candidati', default='')
    ap.add_argument('--favorito', default='',
                    help='griglia di k per la correzione di contesto partita, '
                         'es. 0,1,2,4 (punti per gol di differenziale atteso). '
                         'Tiene half_life/trend di produzione e muove solo k.')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/taratura_confronto_parametri.json')
    args = ap.parse_args()

    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    voluti = {RUOLI[b] for b in brevi}
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache, ruoli: %s' % (len(slugs), ', '.join(brevi)))
    punti = raccogli(cache, slugs, voluti, args.max or None)
    print('%d punti di test\n' % len(punti))

    esiti = {}
    for b in brevi:
        sotto = [p for p in punti if p[0] == RUOLI[b]]
        if not sotto:
            continue
        modulo = sotto[0][3]['modulo']
        prod = (modulo.HALF_LIFE_GAMES, getattr(modulo, 'TREND_INTENSITY', 0.0))
        if args.favorito:
            esiti[b] = griglia_favorito(b, sotto, prod, args.favorito)
            continue
        if args.candidati:
            cand = [tuple(float(x) for x in c.split(':')) for c in args.candidati.split(',')]
        else:
            cand = [prod, (12.0, 0.0), (6.0, 0.0), (4.0, 0.0), (2.0, 0.0), (1.5, 0.0)]
        if prod not in cand:
            cand.insert(0, prod)
        print('=' * 96)
        print('%s -- %d punti | produzione half_life=%s trend=%s' % (b.upper(), len(sotto), prod[0], prod[1]))
        print('=' * 96)
        print('%-16s %8s %8s %9s %8s %8s %7s' %
              ('half_life/trend', 'MAE', 'corr', 'sd prev', 'sd real', 'bias', 'lift%'))
        risultati = []
        for hl, ti in cand:
            r = valuta(sotto, hl, ti)
            r['half_life'], r['trend_intensity'] = hl, ti
            r['produzione'] = (hl, ti) == prod
            risultati.append(r)
            print('%-16s %8.3f %8.3f %9.2f %8.2f %+8.2f %7s%s' %
                  ('%s / %s' % (hl, ti), r['mae'], r['corr'], r['sd_prev'], r['sd_reale'],
                   r['bias'], ('%.1f' % r['lift']) if r['lift'] is not None else '--',
                   '   <- produzione' if r['produzione'] else ''))
        esiti[b] = risultati
        print()

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print('salvato in %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
