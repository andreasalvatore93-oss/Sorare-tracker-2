"""taratura_avversario — le sensibilita' degli aggiustamenti avversario, rimisurate.

PERCHE' ADESSO. I coefficienti di `opponent_strength` erano stati tarati sotto
ipotesi che il 03/08 non valgono piu':

  * `gk_def_pen_area_*` era un MOLTIPLICATORE su lambda_pos con il segno
    rovesciato; ora e' un delta ADDITIVO sul granulare col segno giusto. La
    sensibilita' 0.5 veniva da una griglia che non ha mai provato il segno
    opposto: non c'e' motivo di credere che valga ancora;
  * `fwd_offense_granular_delta` usava `abs()` sul granulare del giocatore e
    non aveva tetto; ora e' con segno e cappato a +-3;
  * tutte le serie hanno un ripiego GLOBALE cross-lega, quindi l'aggiustamento
    ora si applica anche dove prima cadeva in silenzio (le partite di coppa);
  * c'e' un peso per ampiezza del campione dove l'avversario ha meno di 10
    partite.

E soprattutto: il banco di misura li teneva SPENTI. Si tarava un coefficiente
guardando un modello in cui quel coefficiente non agiva.

COME. Walk-forward sullo storico in cache, con gli aggiustamenti accesi
(`calcola(..., usa_avversario=True)`) e la sensibilita' del ruolo sostituita a
runtime. Ogni valore e' giudicato su MAE, correlazione e selezione dei primi
cinque insieme -- il MAE da solo premia i modelli che non ordinano niente.

Uso:  python taratura_avversario.py
      python taratura_avversario.py --ruoli fwd,gk
"""
import argparse
import collections
import datetime
import json
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev
import opponent_strength as ops
from taratura_confronto_parametri import raccogli, lift_selezione
from taratura_halflife_trend import RUOLI

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

GRIGLIA_SENS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.4]
GRIGLIA_PEN_AREA = [0.0, 0.25, 0.5, 0.75, 1.0]
GRIGLIA_FWD_OFF = [0.0, 1.5, 3.0, 4.5, 6.0]


def misura(sotto):
    righe = []
    for _r, slug, data, ctx, reale in sotto:
        try:
            p = prev.calcola(ctx, usa_avversario=True)
        except Exception:
            continue
        righe.append((_r, slug, data, p, reale))
    if not righe:
        return None
    X = [r[3] for r in righe]
    Y = [r[4] for r in righe]
    mx, my = statistics.mean(X), statistics.mean(Y)
    sx, sy = statistics.pstdev(X), statistics.pstdev(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    mae = statistics.mean(abs(y - (a + b * x)) for x, y in zip(X, Y))
    corr = (sum((x - mx) * (y - my) for x, y in zip(X, Y)) / len(X) / (sx * sy)) if sx and sy else 0.0
    lift, _ = lift_selezione(righe)
    return {'mae': mae, 'corr': corr, 'lift': lift, 'n': len(righe)}


def sweep(nome, sotto, valori, leggi, scrivi):
    print('%-12s %8s %8s %8s' % (nome, 'MAE', 'corr', 'lift%'))
    prod = leggi()
    migliore = None
    for v in valori:
        scrivi(v)
        m = misura(sotto)
        if m is None:
            continue
        print('%-12s %8.3f %8.3f %8s%s'
              % (v, m['mae'], m['corr'],
                 '%.1f' % m['lift'] if m['lift'] is not None else '--',
                 '   <- produzione' if v == prod else ''))
        if migliore is None or m['mae'] < migliore[1]['mae']:
            migliore = (v, m)
    scrivi(prod)
    return migliore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='gk,def,mid,fwd')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/taratura_avversario.json')
    args = ap.parse_args()

    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    voluti = {RUOLI[b] for b in brevi}
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache' % len(slugs))
    punti = raccogli(cache, slugs, voluti, args.max or None)
    print('%d punti di test\n' % len(punti))

    esiti = {}
    for b in brevi:
        sotto = [p for p in punti if p[0] == RUOLI[b]]
        if len(sotto) < 500:
            continue
        print('=' * 74)
        print('%s -- %d punti' % (b.upper(), len(sotto)))
        print('=' * 74)
        mig = sweep('sensibilita', sotto, GRIGLIA_SENS,
                    lambda: ops.SENSITIVITY_BY_ROLE.get(b, 0.0),
                    lambda v: ops.SENSITIVITY_BY_ROLE.__setitem__(b, v))
        esiti[b] = {'sensibilita': [mig[0], mig[1]] if mig else None}
        print()
        if b == 'gk':
            mig2 = sweep('pen_area', sotto, GRIGLIA_PEN_AREA,
                         lambda: ops.GK_PEN_AREA_SENSITIVITY,
                         lambda v: setattr(ops, 'GK_PEN_AREA_SENSITIVITY', v))
            esiti[b]['pen_area'] = [mig2[0], mig2[1]] if mig2 else None
            print()
        if b == 'fwd':
            mig2 = sweep('offensivo', sotto, GRIGLIA_FWD_OFF,
                         lambda: ops.FWD_OFFENSE_SENSITIVITY,
                         lambda v: setattr(ops, 'FWD_OFFENSE_SENSITIVITY', v))
            esiti[b]['offensivo'] = [mig2[0], mig2[1]] if mig2 else None
            print()

    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2, default=float)
    print('salvato in %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
