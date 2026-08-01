"""I parametri vanno scelti sul MAE o su quanto e' buona la SELEZIONE?

Il MAE misura quanto il modello sbaglia il punteggio di ogni giocatore. Ma la
decisione reale non e' "quanto fara' Tizio", e' "quali 5 schiero": due modelli
con lo stesso MAE possono scegliere formazioni molto diverse, e uno puo' essere
sistematicamente migliore dell'altro nel mettere in cima i giocatori giusti.

METODO. Per ogni giornata (data) e per ogni combinazione di parametri:
  1. si prevede ogni giocatore usando SOLO le partite precedenti (walk-forward);
  2. si prendono i TOP-5 per punteggio previsto;
  3. si somma il punteggio REALE di quei 5.
Si confrontano le combinazioni sul totale realizzato e su P(superare soglia),
non sull'errore medio.

Confronto onesto: la soglia e' fissa fra le combinazioni, altrimenti ognuna
verrebbe giudicata su un bersaglio diverso.

Uso:  python formazione_mls/diagnostics/valuta_selezione.py
      COMBO="20,0.0,1.1;30,0.0,1.0;6,0.0,1.15"   MIN_GIOCATORI=12
"""
import collections
import glob
import json
import math
import os
import statistics
import sys

MIN_GIOCATORI = int(os.environ.get('MIN_GIOCATORI', '12'))
MIN_STORICO = int(os.environ.get('MIN_STORICO', '6'))
TOP_N = int(os.environ.get('TOP_N', '5'))


def _combo_da_env():
    raw = os.environ.get('COMBO', '')
    if not raw:
        return [(20.0, 0.0), (25.0, 0.2), (30.0, 0.0), (6.0, 0.0), (12.0, 0.7)]
    out = []
    for pezzo in raw.split(';'):
        p = [float(x) for x in pezzo.split(',')]
        out.append((p[0], p[1]))
    return out


RUOLO = os.environ.get('RUOLO', '').strip().lower()


def carica():
    """slug -> [(data, score)] ordinate, dai detail cache consolidati.
    Con RUOLO=gk/def/mid/fwd tiene solo quel ruolo (la cartella lo dice)."""
    per_slug = collections.defaultdict(list)
    patt = f'dati_globali/detail_cache/*/{RUOLO}/*_detail_cache.json' if RUOLO         else 'dati_globali/detail_cache/*/*/*_detail_cache.json'
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


def previsione(storico, half_life, trend):
    """Media pesata esponenziale + trend, sulla stessa forma della produzione.
    Non replica lo shrinkage (che qui non discrimina fra combinazioni: agisce
    uguale su tutte), serve a ORDINARE i candidati."""
    if len(storico) < MIN_STORICO:
        return None
    scores = [s for _d, s in storico]
    n = len(scores)
    pesi = [math.pow(0.5, (n - 1 - i) / half_life) for i in range(n)]
    tot = sum(pesi)
    media = sum(s * p for s, p in zip(scores, pesi)) / tot
    if trend and n >= 10:
        corto = statistics.mean(scores[-5:])
        lungo = statistics.mean(scores[-10:])
        if lungo:
            media *= 1.0 + trend * ((corto / lungo) - 1.0)
    return media


def main():
    per_slug = carica()
    date = sorted({d for v in per_slug.values() for d, _s in v})
    combos = _combo_da_env()
    print(f'giocatori: {len(per_slug)} | giornate: {len(date)} | '
          f'combinazioni: {len(combos)}\n')

    risultati = {c: [] for c in combos}
    for data in date:
        presenti = [(s, v) for s, v in per_slug.items()
                    if any(d == data for d, _x in v)]
        if len(presenti) < MIN_GIOCATORI:
            continue
        for combo in combos:
            hl, tr = combo
            righe = []
            for slug, v in presenti:
                passato = [(d, s) for d, s in v if d < data]
                p = previsione(passato, hl, tr)
                if p is None:
                    continue
                reale = next(s for d, s in v if d == data)
                righe.append((p, reale))
            if len(righe) < TOP_N:
                continue
            righe.sort(reverse=True)
            risultati[combo].append(sum(r for _p, r in righe[:TOP_N]))

    validi = {c: v for c, v in risultati.items() if len(v) >= 20}
    if not validi:
        print('dati insufficienti')
        return
    # soglia comune: mediana della prima combinazione, cosi' il bersaglio e'
    # lo stesso per tutte
    rif = sorted(next(iter(validi.values())))
    soglie = [rif[int(q * len(rif)) - 1] for q in (0.5, 0.75, 0.9)]

    print(f'{"half_life":>9} {"trend":>6} {"giornate":>9} {"totale medio":>13}   ' +
          '  '.join(f'P>{s:.0f}' for s in soglie))
    for combo, tot in sorted(validi.items(), key=lambda x: -statistics.mean(x[1])):
        hl, tr = combo
        p = [sum(1 for t in tot if t > s) / len(tot) * 100 for s in soglie]
        print(f'{hl:9.1f} {tr:6.1f} {len(tot):9d} {statistics.mean(tot):13.1f}   ' +
              '  '.join(f'{x:5.1f}%' for x in p))


if __name__ == '__main__':
    main()
