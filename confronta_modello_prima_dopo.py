"""confronta_modello_prima_dopo — il modello di oggi sbaglia meno di quello di ieri?

La domanda sembra banale e non lo e': ogni misura del repo gira sul modello
ATTUALE, quindi non puo' dire quanto si e' guadagnato rispetto a prima. Qui i
due modelli girano davvero, fianco a fianco, sugli stessi identici
(giocatore, partita) dello storico gia' in cache -- previsione walk-forward
contro punteggio realizzato.

Il modello vecchio non e' riscritto a mano: sono i file veri estratti dal
commit precedente ai fix, messi in una cartella a parte. Per questo lo script
gira in DUE PROCESSI separati (i due modelli hanno gli stessi nomi di modulo e
in un processo solo si sovrascriverebbero).

Uso:
  python confronta_modello_prima_dopo.py --raccogli nuovo   --out nuovo.json
  python confronta_modello_prima_dopo.py --raccogli vecchio --out vecchio.json --radice CARTELLA
  python confronta_modello_prima_dopo.py --confronta vecchio.json nuovo.json
"""
import argparse
import collections
import datetime
import json
import random
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLI = ('Goalkeeper', 'Defender', 'Midfielder', 'Forward')
MIN_STORICO = 5


def _data(nodo):
    return ((nodo.get('anyGame') or {}).get('date') or '')[:10]


def raccogli(prev, cache, limite=None):
    """[(slug, ruolo, data, previsto, reale)] -- stesso ordine in entrambi i
    modelli, cosi' il confronto e' appaiato riga per riga."""
    fuori = []
    slugs = sorted(cache.slug_disponibili())
    for i, slug in enumerate(slugs, 1):
        if limite and i > limite:
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
                r = prev.score_atteso(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not r or r.get('atteso') is None:
                continue
            if (r.get('partite_storiche') or 0) < MIN_STORICO:
                continue
            fuori.append([slug, ruolo, data, r['atteso'], reale])
        if i % 300 == 0:
            print('  [%d/%d] %d righe' % (i, len(slugs), len(fuori)), flush=True)
    return fuori


def _retta(X, Y):
    n = len(X); mx = statistics.mean(X); my = statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    return my - b * mx, b


def _lift(righe, quanti=5, prove=200, seme=3):
    per_data = collections.defaultdict(list)
    for _s, _r, data, p, reale in righe:
        per_data[data].append((p, reale))
    rnd = random.Random(seme)
    quote = []
    for _d, v in per_data.items():
        if len(v) < quanti * 3:
            continue
        scelto = sum(r for _p, r in sorted(v, key=lambda x: -x[0])[:quanti])
        oracolo = sum(sorted((r for _p, r in v), reverse=True)[:quanti])
        caso = statistics.mean(sum(r for _p, r in rnd.sample(v, quanti)) for _ in range(prove))
        if oracolo - caso > 0:
            quote.append((scelto - caso) / (oracolo - caso))
    return statistics.mean(quote) * 100 if quote else None


def _metriche(righe, calibrata=True):
    """MAE dopo calibrazione: e' il numero che conta, perche' in produzione la
    previsione arriva all'utente gia' calibrata. Senza calibrare si misurerebbe
    anche un errore di scala che il sistema corregge da solo."""
    X = [r[3] for r in righe]; Y = [r[4] for r in righe]
    a, b = _retta(X, Y) if calibrata else (0.0, 1.0)
    P = [a + b * x for x in X]
    mae = statistics.mean(abs(y - p) for p, y in zip(P, Y))
    sx, sy = statistics.pstdev(X), statistics.pstdev(Y)
    mx, my = statistics.mean(X), statistics.mean(Y)
    corr = (sum((x - mx) * (y - my) for x, y in zip(X, Y)) / len(X) / (sx * sy)
            if sx > 0 and sy > 0 else 0.0)
    return {'n': len(righe), 'mae': mae, 'corr': corr, 'a': a, 'b': b,
            'sd_prev': sx, 'lift': _lift(righe)}


def confronta(pvecchio, pnuovo):
    v = {tuple(r[:3]): r for r in json.load(open(pvecchio, encoding='utf-8'))}
    n = {tuple(r[:3]): r for r in json.load(open(pnuovo, encoding='utf-8'))}
    comuni = sorted(set(v) & set(n))
    print('righe confrontabili (stesso giocatore, stessa partita): %d' % len(comuni))
    print('  (solo nel vecchio: %d | solo nel nuovo: %d)\n' % (len(set(v) - set(n)), len(set(n) - set(v))))
    V = [v[k] for k in comuni]
    N = [n[k] for k in comuni]

    print('%-22s %8s %8s %8s %8s' % ('', 'MAE', 'corr', 'sd prev', 'lift%'))
    for eti, righe in (('PRIMA dei fix', V), ('DOPO i fix', N)):
        m = _metriche(righe)
        print('%-22s %8.3f %8.3f %8.2f %8s'
              % (eti, m['mae'], m['corr'], m['sd_prev'],
                 '%.1f' % m['lift'] if m['lift'] is not None else '--'))
    mv, mn = _metriche(V), _metriche(N)
    print('\nvariazione MAE: %+.3f punti (%+.2f%%)'
          % (mn['mae'] - mv['mae'], (mn['mae'] - mv['mae']) / mv['mae'] * 100))

    # confronto appaiato: su quante partite il nuovo sbaglia meno?
    av, bv = mv['a'], mv['b']
    an, bn = mn['a'], mn['b']
    meglio = peggio = 0
    diffs = []
    for rv, rn in zip(V, N):
        ev = abs(rv[4] - (av + bv * rv[3]))
        en = abs(rn[4] - (an + bn * rn[3]))
        diffs.append(en - ev)
        if en < ev - 1e-9:
            meglio += 1
        elif en > ev + 1e-9:
            peggio += 1
    print('partite in cui il nuovo sbaglia MENO: %d (%.1f%%) | di piu\': %d (%.1f%%) | uguale: %d'
          % (meglio, 100 * meglio / len(V), peggio, 100 * peggio / len(V),
             len(V) - meglio - peggio))
    sd = statistics.pstdev(diffs)
    es = sd / (len(diffs) ** 0.5)
    media = statistics.mean(diffs)
    print('differenza media di errore: %+.4f punti, errore standard %.4f -> %.1f sigma'
          % (media, es, abs(media / es) if es else 0))

    for ru in RUOLI:
        Vr = [r for r in V if r[1] == ru]
        Nr = [r for r in N if r[1] == ru]
        if len(Vr) < 200:
            continue
        a1, b1 = _metriche(Vr), _metriche(Nr)
        print('  %-12s MAE %.3f -> %.3f (%+.2f%%) | corr %.3f -> %.3f | lift %s -> %s'
              % (ru, a1['mae'], b1['mae'], (b1['mae'] - a1['mae']) / a1['mae'] * 100,
                 a1['corr'], b1['corr'],
                 '%.1f' % a1['lift'] if a1['lift'] else '--',
                 '%.1f' % b1['lift'] if b1['lift'] else '--'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raccogli', choices=['vecchio', 'nuovo'])
    ap.add_argument('--radice', help='cartella del modello vecchio')
    ap.add_argument('--out')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--confronta', nargs=2)
    args = ap.parse_args()

    if args.confronta:
        confronta(*args.confronta)
        return 0

    if args.raccogli == 'vecchio':
        if not args.radice:
            print('serve --radice'); return 1
        sys.path.insert(0, args.radice)
    import backtest_arene_cache
    import backtest_arene_previsioni as prev
    print('modello %s caricato da %s' % (args.raccogli, prev.__file__))
    cache = backtest_arene_cache.CacheLocale()
    righe = raccogli(prev, cache, args.max or None)
    print('%d righe' % len(righe))
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(righe, fh)
    print('salvato in %s' % args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
