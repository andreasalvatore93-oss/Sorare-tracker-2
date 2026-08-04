"""verifica_stadio_d_avversario — riproduce i tre arm del candidato DEF.

PERCHE'. La decisione di spegnere la gamba AVVERSARIO dello Stadio D sui
difensori si regge su tre terne di numeri prodotte da un'altra sessione
(docs/handoff/HANDOFF_riverifica_indipendente_2026-08-04.txt, sezione 3.C).
Prima di toccare la produzione quelle terne vanno ritrovate qui, sullo stesso
campione, altrimenti si applica una decisione presa su un campione che non e'
il nostro.

I TRE ARM, e perche' servono tutti e tre:

  1 PRODUZIONE            canale avversario acceso, com'e' oggi
  4 STADIO_D_AVVERSARIO   solo la gamba avversario spenta, venue TENUTO
                          = il candidato, il nuovo interruttore esplicito
  3 use_stadio_d=False    Stadio D INTERO spento, venue compreso
                          = l'errore di misura del 04/08, qui tenuto apposta

L'arm 3 e' il controllo che l'interruttore nuovo faccia davvero solo la sua
meta': se STADIO_D_AVVERSARIO spegnesse anche il venue, l'arm 4 uscirebbe
uguale all'arm 3. Sono terne ben separate, quindi il controllo discrimina.

Uso:  python verifica_stadio_d_avversario.py [--ruolo def] [--max N]
"""
import argparse
import json
import os
import statistics
import sys

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import lift_selezione, raccogli
from taratura_halflife_trend import RUOLI

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# I numeri della riverifica indipendente (sezione 3.C, n=25.738), tenuti come
# RIFERIMENTO STORICO e stampati per confronto -- non come cancello.
# Il cancello sui valori assoluti e' stato tolto il 04/08 sera: quei valori
# tremolavano fra ambienti per l'ordine dei file (poi corretto, vedi
# opponent_strength._build_series_for_league). Cio' che deve reggere e' il
# DELTA fra gli arm, come dice la regola in CLAUDE.md.
ATTESI = {
    'produzione': (14.990365, 0.176337, 16.0641),
    'stadio_d_avversario_spento': (14.970303, 0.182627, 17.2155),
    'stadio_d_intero_spento': (14.989160, 0.176039, 16.8662),
}
# segni attesi del delta candidato - produzione: MAE giu', corr su, lift su
SEGNI_ATTESI = {'mae': -1, 'corr': +1, 'lift': +1}


def misura(punti, **kwargs):
    righe = []
    for ruolo, slug, data, ctx, reale in punti:
        try:
            p = prev.calcola(ctx, **kwargs)
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
    return {'n': len(righe), 'mae': mae, 'corr': corr, 'lift': lift, 'giornate': n_gg}


def _scarto_storico(nome, r):
    """Di quanto la terna misurata si discosta da quella pubblicata."""
    mae_a, corr_a, lift_a = ATTESI[nome]
    return (r['mae'] - mae_a, r['corr'] - corr_a, (r['lift'] or 0) - lift_a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruolo', default='def')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--json', default='dati_globali/verifica_stadio_d_avversario.json')
    args = ap.parse_args()

    ruolo_lungo = RUOLI[args.ruolo]
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    print('%d giocatori in cache, ruolo %s' % (len(slugs), args.ruolo), flush=True)
    punti = raccogli(cache, slugs, {ruolo_lungo}, args.max or None)
    print('%d punti di test\n' % len(punti), flush=True)

    modulo = punti[0][3]['modulo']
    if not hasattr(modulo, 'STADIO_D_AVVERSARIO'):
        print('ERRORE: il modulo di produzione non espone STADIO_D_AVVERSARIO')
        return 1

    esiti = {}
    originale = modulo.STADIO_D_AVVERSARIO
    try:
        modulo.STADIO_D_AVVERSARIO = True
        esiti['produzione'] = misura(punti, usa_avversario=True)
        esiti['stadio_d_intero_spento'] = misura(punti, usa_avversario=True,
                                                 avversario_stadio_d=False)
        modulo.STADIO_D_AVVERSARIO = False
        esiti['stadio_d_avversario_spento'] = misura(punti, usa_avversario=True)
    finally:
        modulo.STADIO_D_AVVERSARIO = originale

    base = esiti['produzione']
    print('=' * 96)
    print('%s -- %d punti, %d giornate' % (args.ruolo.upper(), base['n'], base['giornate']))
    print('=' * 96)
    print('%-34s %12s %11s %10s %11s %11s %9s' %
          ('arm', 'MAE', 'corr', 'lift', 'dMAE', 'dcorr', 'dlift'))
    for nome in ('produzione', 'stadio_d_avversario_spento', 'stadio_d_intero_spento'):
        r = esiti[nome]
        r['scarto_vs_storico'] = _scarto_storico(nome, r)
        print('%-34s %12.6f %11.6f %10.4f %+11.6f %+11.6f %+9.4f' %
              (nome, r['mae'], r['corr'], r['lift'] or 0,
               r['mae'] - base['mae'], r['corr'] - base['corr'],
               (r['lift'] or 0) - (base['lift'] or 0)))

    print('\nriferimento storico (riverifica indipendente, sez. 3.C) e scarto:')
    for nome, (m, c, l) in ATTESI.items():
        s = esiti[nome]['scarto_vs_storico']
        print('  %-34s MAE %.6f (%+.6f)  corr %.6f (%+.6f)  lift %.4f (%+.4f)'
              % (nome, m, s[0], c, s[1], l, s[2]))

    # IL CANCELLO VERO: i tre segni del delta candidato - produzione.
    cand_delta = {'mae': esiti['stadio_d_avversario_spento']['mae'] - base['mae'],
                  'corr': esiti['stadio_d_avversario_spento']['corr'] - base['corr'],
                  'lift': (esiti['stadio_d_avversario_spento']['lift'] or 0) - (base['lift'] or 0)}
    segni_ok = all((cand_delta[k] < 0) if v < 0 else (cand_delta[k] > 0)
                   for k, v in SEGNI_ATTESI.items())
    print('\nDELTA candidato - produzione: MAE %+.6f  corr %+.6f  lift %+.4f -> %s'
          % (cand_delta['mae'], cand_delta['corr'], cand_delta['lift'],
             'tutti e tre nel verso giusto' if segni_ok else 'SEGNI NON COERENTI'))
    tutto_ok = segni_ok

    cand = esiti['stadio_d_avversario_spento']
    intero = esiti['stadio_d_intero_spento']
    separati = abs(cand['corr'] - intero['corr']) > 0.001
    print('\nCONTROLLO INTERRUTTORE: il candidato e lo spegnimento intero sono %s'
          % ('DIVERSI (il venue e\' rimasto acceso, come deve)' if separati
             else 'UGUALI -> STADIO_D_AVVERSARIO sta spegnendo anche il venue'))
    print('ESITO COMPLESSIVO: %s' % ('il candidato regge il metro'
                                     if tutto_ok else 'IL CANDIDATO NON REGGE'))

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), args.json),
              'w', encoding='utf-8') as fh:
        json.dump({'ruolo': args.ruolo, 'riferimento_storico': ATTESI, 'esiti': esiti,
                   'delta_candidato': cand_delta, 'segni_coerenti': segni_ok,
                   'interruttore_separato': separati},
                  fh, ensure_ascii=False, indent=1)
    print('\nsalvato in %s' % args.json)
    return 0 if (tutto_ok and separati) else 2


if __name__ == '__main__':
    sys.exit(main())
