# -*- coding: utf-8 -*-
"""residuo_smart_money — i pick dei manager battono il nostro `atteso`?

Domanda del filone (HANDOFF_UNIFICATO §7): esiste un segnale "smart money" che
il modello NON ha? Si misura il RESIDUO = realizzato - atteso sui giocatori
schierati in arena da un campione di manager, in una GW CHIUSA.

- atteso: walk-forward STRETTO as-of pre-GW, calcolato con le STESSE funzioni di
  produzione (`backtest_arene_previsioni.score_atteso`, moduli MLS = modello
  unico). Nessuna formula riscritta. La partita target (in GW1) e' nel game log
  cachato; il cutoff e' la sua data, quindi la finestra storica vede solo
  partite precedenti.
- realizzato: `punteggio` grezzo della carta in arena (nessun bonus carta/
  formazione in arena, §3), tolto il capitano +20% additivo.
- residuo medio (bias):
    ~0  -> il modello cattura gia' i loro pick -> nessun edge da aggiungere.
    >0  -> i loro pick sovraperformano l'atteso -> segnale smart-money reale.

Uso:
  python residuo_smart_money.py            # GW1, 8 manager attivi
  python residuo_smart_money.py --json dati_globali/smart_money/residuo_gw1.json
"""
import argparse
import datetime
import json
import math
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import backtest_arene_cache
import backtest_arene_previsioni as P

CAPITANO_ARENA = 0.2
GW = 'football-31-jul-4-aug-2026'
FINE_GIORNATA = datetime.datetime(2026, 8, 4, 23, 59)  # fine finestra GW1
MANAGER = ['eoghankelly', 'milkyfresht', 'lairdinho', 'bxl-spartak',
           'spillo678', 'shirimimi', 'fins49', 'ninoshooter']


def _corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def riepilogo(righe):
    a = [r['atteso'] for r in righe]
    reale = [r['reale'] for r in righe]
    err = [r['reale'] - r['atteso'] for r in righe]
    n = len(righe)
    bias = sum(err) / n
    mae = sum(abs(e) for e in err) / n
    sdp = (sum((x - sum(a) / n) ** 2 for x in a) / n) ** 0.5
    sdr = (sum((x - sum(reale) / n) ** 2 for x in reale) / n) ** 0.5
    return {'n': n, 'bias': bias, 'mae': mae, 'corr': _corr(a, reale),
            'sd_prev': sdp, 'sd_reale': sdr}


def tabella(titolo, gruppi, minimo=1):
    print(f"\n{titolo}")
    print(f"  {'gruppo':22} {'n':>4} {'bias':>7} {'MAE':>6} {'corr':>6}")
    for nome, righe in sorted(gruppi.items(), key=lambda kv: -len(kv[1])):
        if len(righe) < minimo:
            continue
        s = riepilogo(righe)
        c = f"{s['corr']:+.2f}" if s['corr'] is not None else '   -'
        print(f"  {nome:22} {s['n']:>4} {s['bias']:>+7.1f} {s['mae']:>6.1f} {c:>6}")


def _gruppi(righe, campo):
    g = {}
    for r in righe:
        g.setdefault(r[campo], []).append(r)
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', help='salva le righe grezze')
    args = ap.parse_args()

    cache = backtest_arene_cache.CacheLocale()
    righe = []
    saltate = {}
    def salta(k):
        saltate[k] = saltate.get(k, 0) + 1

    for man in MANAGER:
        path = os.path.join(ROOT, 'dati_globali', f'manager_{man}.json')
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding='utf-8'))
        visti = set()
        for f in (d.get('giornate') or {}).get(GW) or []:
            for c in (f.get('carte') or []):
                slug, ruolo = c.get('slug'), c.get('ruolo')
                if not slug or not ruolo:
                    continue
                if (man, c.get('carta')) in visti:
                    continue          # stessa carta in piu' arene dello stesso manager
                visti.add((man, c.get('carta')))
                reale = c.get('punteggio')
                if reale is None:
                    salta('senza punteggio'); continue
                if c.get('capitano'):
                    reale = reale / (1.0 + CAPITANO_ARENA)
                if reale == 0:
                    salta('non ha giocato (0)'); continue
                r = P.score_atteso(cache, slug, ruolo, FINE_GIORNATA)
                if r is None or r.get('atteso') is None:
                    salta('storico insufficiente / no target'); continue
                righe.append({'manager': man, 'slug': slug, 'nome': c.get('nome'),
                              'ruolo': ruolo, 'atteso': r['atteso'], 'reale': reale,
                              'residuo': reale - r['atteso'], 'l10': r.get('l10'),
                              'partite_storiche': r.get('partite_storiche')})

    if not righe:
        print('nessuna osservazione utilizzabile'); return 1

    s = riepilogo(righe)
    print(f"GW1 {GW} — manager attivi {len(MANAGER)}")
    print(f"osservazioni {s['n']}   scartate: " +
          ', '.join(f'{v} {k}' for k, v in sorted(saltate.items(), key=lambda kv: -kv[1])))
    c = f"{s['corr']:+.3f}" if s['corr'] is not None else '-'
    print(f"\n>>> RESIDUO MEDIO (bias reale-atteso) = {s['bias']:+.2f}   "
          f"[>0 = smart money batte il modello, ~0 = STOP]")
    print(f"    MAE {s['mae']:.1f}   correlazione atteso/reale {c}")
    print(f"    dispersione: previsto {s['sd_prev']:.1f}  reale {s['sd_reale']:.1f}")

    tabella('PER RUOLO', _gruppi(righe, 'ruolo'))
    tabella('PER MANAGER', _gruppi(righe, 'manager'))

    # dedup a giocatore unico (una riga per slug): consenso, non peso-per-popolarita'
    per_slug = {}
    for r in righe:
        per_slug.setdefault(r['slug'], r)
    su = riepilogo(list(per_slug.values()))
    print(f"\nDEDUP a giocatore unico: n {su['n']}  bias {su['bias']:+.2f}  "
          f"corr {su['corr'] if su['corr'] is None else round(su['corr'],3)}")

    if args.json:
        json.dump(righe, open(os.path.join(ROOT, args.json), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f"\nrighe salvate in {args.json}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
