"""La varianza di un giocatore e' prevedibile? E serve a qualcosa?

Oggi il modello prevede solo la MEDIA. In un gioco a soglia conta anche quanto
un giocatore e' imprevedibile: a parita' di punteggio atteso, chi oscilla di
piu' aiuta quando serve un colpo grosso e danneggia quando basta la mediana.

Due domande, in ordine:
  1. la dispersione passata di un giocatore predice quella futura? (se no, non
     c'e' niente da modellare);
  2. usarla nella scelta dei 5 migliora la P(superare soglia)?

Walk-forward su dati reali: la dispersione si calcola solo sulle partite
precedenti, mai su quella da prevedere.

Uso:  python formazione_mls/diagnostics/misura_varianza_prevedibile.py
"""
import collections
import glob
import json
import math
import os
import random
import statistics

MIN_STORICO = int(os.environ.get('MIN_STORICO', '10'))
TOP_N = int(os.environ.get('TOP_N', '5'))
MIN_GIOCATORI = int(os.environ.get('MIN_GIOCATORI', '12'))
HALF_LIFE = float(os.environ.get('HALF_LIFE', '20'))
RUOLO = os.environ.get('RUOLO', '').strip().lower()


def carica():
    per_slug = collections.defaultdict(list)
    patt = (f'dati_globali/detail_cache/*/{RUOLO}/*_detail_cache.json' if RUOLO
            else 'dati_globali/detail_cache/*/*/*_detail_cache.json')
    for path in glob.glob(patt):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict) or v.get('scoreStatus') != 'FINAL':
                continue
            data = ((v.get('anyGame') or {}).get('date') or '')[:10]
            if data and v.get('score') is not None:
                per_slug[slug].append((data, v['score']))
    for s in per_slug:
        per_slug[s].sort()
    return per_slug


def media_pesata(scores, hl):
    n = len(scores)
    pesi = [math.pow(0.5, (n - 1 - i) / hl) for i in range(n)]
    return sum(s * p for s, p in zip(scores, pesi)) / sum(pesi)


def correlazione(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx and dy else 0.0


def main():
    per_slug = carica()
    print(f'ruolo: {RUOLO or "tutti"} | giocatori: {len(per_slug)}')

    # --- 1. la dispersione passata predice quella futura?
    passata, futura = [], []
    for _slug, v in per_slug.items():
        s = [x[1] for x in v]
        if len(s) < 2 * MIN_STORICO:
            continue
        meta = len(s) // 2
        passata.append(statistics.pstdev(s[:meta]))
        futura.append(statistics.pstdev(s[meta:]))
    if len(passata) < 30:
        print('dati insufficienti per la parte 1')
    else:
        r = correlazione(passata, futura)
        print(f'1) dispersione passata vs futura: corr {r:+.3f} '
              f'(n={len(passata)} giocatori)')

    # --- 2. usarla nella scelta migliora la P(soglia)?
    date = sorted({x[0] for v in per_slug.values() for x in v})
    base, con_var = [], []
    for data in date:
        presenti = [(s, v) for s, v in per_slug.items() if any(x[0] == data for x in v)]
        if len(presenti) < MIN_GIOCATORI:
            continue
        righe = []
        for slug, v in presenti:
            passato = [x[1] for x in v if x[0] < data]
            if len(passato) < MIN_STORICO:
                continue
            m = media_pesata(passato, HALF_LIFE)
            sd = statistics.pstdev(passato)
            reale = next(x[1] for x in v if x[0] == data)
            righe.append((m, sd, reale))
        if len(righe) < TOP_N:
            continue
        base.append(sum(r for _m, _s, r in sorted(righe, reverse=True)[:TOP_N]))
        # a parita' di media, preferisci chi oscilla di piu': m + 0.25*sd
        ordinate = sorted(righe, key=lambda x: -(x[0] + 0.25 * x[1]))
        con_var.append(sum(r for _m, _s, r in ordinate[:TOP_N]))

    if len(base) < 20:
        print('dati insufficienti per la parte 2')
        return
    rif = sorted(base)
    soglie = [rif[int(q * len(rif)) - 1] for q in (0.5, 0.75, 0.9)]
    print(f'\n2) selezione su {len(base)} giornate')
    for nome, serie in (('solo media', base), ('media + 0.25*dispersione', con_var)):
        p = [sum(1 for t in serie if t > s) / len(serie) * 100 for s in soglie]
        print(f'   {nome:26s} medio {statistics.mean(serie):7.1f}   ' +
              '  '.join(f'P>{s:.0f} {x:5.1f}%' for s, x in zip(soglie, p)))
    d = [a - b for a, b in zip(con_var, base)]
    random.seed(1)
    v = sum(1 for _ in range(2000)
            if statistics.mean([random.choice(d) for _ in d]) > 0)
    print(f'   differenza media {statistics.mean(d):+.2f} pt | bootstrap {v/2000*100:.1f}%')


if __name__ == '__main__':
    main()
