# -*- coding: utf-8 -*-
"""Quanto e' rumoroso il LIFT DI SELEZIONE? (13/08/2026)

NASCE DA UN DUBBIO PRECISO. Il filone intralega si e' fermato su un caso solo:
per il DIFENSORE, i gol fatti dall'avversario migliorano MAE (-0,051) e
correlazione (+0,0156) in modo monotono, ma il lift resta fermo (-0,1/-0,7) e
la regola del repo pretende che tutti e tre migliorino INSIEME. La domanda: quel
"-0,1" e' un no, o e' rumore travestito da no?

COME SI MISURA BENE, cioe' APPAIATO. Il lift di un giorno e'
    (scelto - caso) / (oracolo - caso)
e di questi tre pezzi SOLO `scelto` dipende dalla previsione: `caso` e
`oracolo` guardano i punteggi realizzati, quindi sono IDENTICI per le due
varianti. Quindi si confrontano i due bracci giorno per giorno, sullo stesso
insieme di giorni, e si ricampionano i GIORNI per l'intervallo di confidenza.
Confrontare due medie calcolate su giorni diversi sarebbe l'errore.

UNA CORREZIONE AL METRO, gia' che si passa di qui: `taratura_confronto_
parametri.lift_selezione` stima `caso` con 200 estrazioni casuali, ma il valore
esatto si sa in forma chiusa -- il valore atteso della somma di `quanti` carte
pescate a caso e' `quanti * media del giorno`. Qui si usa l'esatto: toglie di
mezzo una fonte di rumore che non c'era bisogno di avere, e rende il confronto
riproducibile senza dipendere dal seme.

Uso (dalla radice): python analisi_manager/p36_lift_rumore.py --ruolo def --k -4
"""
import os
import sys
import json
import random
import argparse
import datetime
import statistics
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import raccogli
from taratura_halflife_trend import RUOLI, _ruolo_di


def quote_per_giorno(righe, quanti=5):
    """giorno -> (scelto, caso_esatto, oracolo). `caso` in forma chiusa."""
    per_data = collections.defaultdict(list)
    for _r, _s, data, previsione, reale in righe:
        per_data[data].append((previsione, reale))
    fuori = {}
    for data, v in per_data.items():
        if len(v) < quanti * 3:
            continue
        reali = [r for _p, r in v]
        scelto = sum(r for _p, r in sorted(v, key=lambda x: -x[0])[:quanti])
        oracolo = sum(sorted(reali, reverse=True)[:quanti])
        caso = quanti * (sum(reali) / len(reali))
        if oracolo - caso <= 0:
            continue
        fuori[data] = (scelto, caso, oracolo)
    return fuori


def bootstrap_delta(delta_per_giorno, giri=2000, seme=20260813):
    rng = random.Random(seme)
    giorni = list(delta_per_giorno)
    stime = []
    for _ in range(giri):
        campione = [delta_per_giorno[giorni[rng.randrange(len(giorni))]]
                    for _ in range(len(giorni))]
        stime.append(statistics.mean(campione))
    stime.sort()
    return stime[int(0.025 * giri)], stime[int(0.975 * giri)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruolo', default='def')
    ap.add_argument('--k', type=float, default=-4.0)
    ap.add_argument('--correzione', default='gol_fatti_avv',
                    choices=('gol_fatti_avv', 'reparto_avv'))
    ap.add_argument('--max', type=int, default=0)
    args = ap.parse_args()

    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    punti = raccogli(cache, slugs, {RUOLI[args.ruolo]}, args.max or None)
    print(f"{len(punti)} punti di test per {args.ruolo}\n")
    modulo = punti[0][3]['modulo']
    hl = modulo.HALF_LIFE_GAMES
    ti = getattr(modulo, 'TREND_INTENSITY', 0.0)

    def righe_con(k):
        out = []
        for ruolo, slug, data, ctx, reale in punti:
            try:
                p = prev.calcola(ctx, half_life=hl, trend_intensity=ti,
                                 usa_avversario=True, **{f'{args.correzione}_k': k})
            except Exception:
                continue
            out.append((ruolo, slug, data, p, reale))
        return out

    q0 = quote_per_giorno(righe_con(0.0))
    qk = quote_per_giorno(righe_con(args.k))
    comuni = sorted(set(q0) & set(qk))
    print(f"giornate valide: {len(comuni)} (comuni ai due bracci)")

    lift0, liftk, delta = {}, {}, {}
    for g in comuni:
        s0, caso, oracolo = q0[g]
        sk, _c, _o = qk[g]
        lift0[g] = (s0 - caso) / (oracolo - caso) * 100
        liftk[g] = (sk - caso) / (oracolo - caso) * 100
        delta[g] = liftk[g] - lift0[g]

    m0, mk = statistics.mean(lift0.values()), statistics.mean(liftk.values())
    md = statistics.mean(delta.values())
    basso, alto = bootstrap_delta(delta)
    diversi = sum(1 for g in comuni if abs(delta[g]) > 1e-9)

    print(f"\nlift medio  k=0    : {m0:.2f}%")
    print(f"lift medio  k={args.k:g}   : {mk:.2f}%")
    print(f"differenza appaiata: {md:+.2f} punti di lift")
    print(f"intervallo di confidenza 95% (ricampionando i giorni): "
          f"[{basso:+.2f} ; {alto:+.2f}]")
    print(f"giornate in cui la scelta CAMBIA davvero: {diversi} su {len(comuni)}")
    print(f"deviazione standard del delta fra giornate: "
          f"{statistics.pstdev(list(delta.values())):.2f}")
    verdetto = ('lo zero e\' DENTRO l\'intervallo: il lift non sa distinguere '
                'le due varianti' if basso <= 0 <= alto else
                'lo zero e\' FUORI: la differenza sul lift e\' reale')
    print(f"\n=> {verdetto}")

    out = os.path.join(_HERE, 'dati',
                       f'lift_rumore_{args.ruolo}_{args.correzione}.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({'quando': datetime.datetime.now().isoformat(timespec='seconds'),
                   'ruolo': args.ruolo, 'correzione': args.correzione, 'k': args.k,
                   'n_punti': len(punti), 'giornate': len(comuni),
                   'lift_k0': m0, 'lift_k': mk, 'delta': md,
                   'ic95': [basso, alto], 'giornate_cambiate': diversi}, fh,
                  ensure_ascii=False, indent=2)
    print(f"scritto: {out}")


if __name__ == '__main__':
    main()
