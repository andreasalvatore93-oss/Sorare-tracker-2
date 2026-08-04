"""tetto_prevedibilita — quanta varianza del punteggio e' spiegabile, al massimo.

PERCHE'. `errore_modello_storico.py` dice che il modello spiega il 4% della
varianza dei punteggi (correlazione +0.203) e che sbaglia in modo uniforme:
nessun ruolo, lega o fascia e' peggiore delle altre. La domanda che ne segue
non e' "dove correggere" ma **quanto c'e' da prendere**: se il tetto teorico
fosse il 6%, il modello e' gia' a due terzi e il filone si chiude; se fosse il
20%, c'e' un fattore 5 da recuperare.

METODO. Nessun modello, nessuna formula: solo scomposizione della varianza
sulle STESSE 2690 osservazioni usate da errore_modello_storico (le carte
davvero schierate in arena, punteggio grezzo, chi non ha giocato escluso).

  Var(punteggio) = Var(fra giocatori) + Var(dentro lo stesso giocatore)

La parte "fra giocatori" e' cio' che un modello puo' sperare di cogliere
conoscendo solo CHI gioca: e' il tetto di qualunque previsione basata sulla
qualita' del giocatore. La parte "dentro" e' la giornata storta o storica: un
modello puo' morderne solo la fetta legata al contesto (avversario, campo),
misurata qui a parte.

Stimatore: ANOVA a effetti casuali a una via con gruppi di taglia diversa
(sigma2_fra = (MSB - MSW)/n0). E' NON DISTORTO: la varianza delle medie
osservate e' gonfiata dal rumore campionario, sottrarre MSW la ripulisce.

CONTROPROVA. Split-half: si stima la media di ogni giocatore sulle sue partite
di indice PARI e la si correla coi punteggi delle sue partite DISPARI. E' una
previsione vera e propria (fuori campione, per giocatore) che usa solo
l'identita' del giocatore -- dice sul campo, non in teoria, quanto ordina un
modello perfetto di sola qualita' individuale.

Uso:  python tetto_prevedibilita.py
      python tetto_prevedibilita.py --json dati_globali/errore_storico.json
"""
import argparse
import collections
import json
import math
import os
import random
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))


def _corr(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def scomponi(gruppi):
    """ANOVA a una via, gruppi = {chiave: [valori]}. Ritorna le componenti."""
    gruppi = {k: v for k, v in gruppi.items() if len(v) >= 1}
    valori = [v for vals in gruppi.values() for v in vals]
    n_tot, k = len(valori), len(gruppi)
    if k < 2 or n_tot <= k:
        return None
    grande = statistics.fmean(valori)
    msb = sum(len(v) * (statistics.fmean(v) - grande) ** 2 for v in gruppi.values()) / (k - 1)
    msw = sum(sum((x - statistics.fmean(v)) ** 2 for x in v) for v in gruppi.values()) / (n_tot - k)
    n0 = (n_tot - sum(len(v) ** 2 for v in gruppi.values()) / n_tot) / (k - 1)
    fra = max(0.0, (msb - msw) / n0)
    return {
        'n': n_tot, 'gruppi': k, 'n0': n0,
        'var_totale': statistics.pvariance(valori),
        'var_fra': fra, 'var_dentro': msw,
        'quota': fra / (fra + msw),
        'corr_max': math.sqrt(fra / (fra + msw)),
    }


def stampa(titolo, s):
    if s is None:
        print(f'\n{titolo}: campione insufficiente')
        return
    print(f'\n{titolo}')
    print(f"  osservazioni {s['n']}   gruppi {s['gruppi']}   partite per gruppo {s['n0']:.1f}")
    print(f"  deviazione standard: fra gruppi {math.sqrt(s['var_fra']):5.1f}   "
          f"dentro {math.sqrt(s['var_dentro']):5.1f}")
    print(f"  TETTO: quota di varianza spiegabile {s['quota']:6.1%}   "
          f"correlazione massima +{s['corr_max']:.3f}")


def split_half(righe, minimo=6, ripetizioni=200):
    """Previsione fuori campione con la sola identita' del giocatore.

    Per ogni giocatore con almeno `minimo` osservazioni si divide a caso lo
    storico in due meta': la media della prima meta' e' la 'previsione', i
    singoli punteggi della seconda sono la 'realta''. Ripetuto su piu'
    divisioni casuali per non dipendere da una partizione fortunata."""
    per_slug = collections.defaultdict(list)
    for r in righe:
        per_slug[r['slug']].append(r['reale'])
    usabili = {k: v for k, v in per_slug.items() if len(v) >= minimo}
    if not usabili:
        return None
    rng = random.Random(0)
    corrs, maes = [], []
    for _ in range(ripetizioni):
        prev, veri = [], []
        for punteggi in usabili.values():
            mescolati = punteggi[:]
            rng.shuffle(mescolati)
            meta = len(mescolati) // 2
            media = statistics.fmean(mescolati[:meta])
            for v in mescolati[meta:]:
                prev.append(media)
                veri.append(v)
        c = _corr(prev, veri)
        if c is not None:
            corrs.append(c)
            maes.append(statistics.fmean(abs(a - b) for a, b in zip(prev, veri)))
    if not corrs:
        return None
    return {
        'giocatori': len(usabili),
        'osservazioni': sum(len(v) - len(v) // 2 for v in usabili.values()),
        'corr': statistics.fmean(corrs),
        'mae': statistics.fmean(maes),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join('dati_globali', 'errore_storico.json'))
    args = ap.parse_args()

    percorso = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
    if not os.path.exists(percorso):
        print(f'manca {percorso}: lancia prima  python errore_modello_storico.py --json {args.json}')
        return 1
    with open(percorso, encoding='utf-8') as f:
        righe = json.load(f)

    print('=' * 82)
    print(f'TETTO DI PREVEDIBILITA — {len(righe)} carte schierate in arena')
    print('=' * 82)

    x = [r['atteso'] for r in righe]
    y = [r['reale'] for r in righe]
    c_modello = _corr(x, y)
    print(f"\nil modello di oggi: correlazione {c_modello:+.3f}   "
          f"varianza spiegata {c_modello ** 2:.1%}   MAE {statistics.fmean(abs(b - a) for a, b in zip(x, y)):.1f}")

    per_slug = collections.defaultdict(list)
    for r in righe:
        per_slug[r['slug']].append(r['reale'])
    stampa('TETTO 1 — sapere CHI gioca (identita del giocatore)', scomponi(per_slug))

    for ruolo in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
        sotto = collections.defaultdict(list)
        for r in righe:
            if r['ruolo'] == ruolo:
                sotto[r['slug']].append(r['reale'])
        s = scomponi(sotto)
        if s:
            print(f"  {ruolo:<12} tetto {s['quota']:6.1%}  (corr max +{s['corr_max']:.3f}, "
                  f"n={s['n']}, giocatori={s['gruppi']})")

    # quanto pesa la GIORNATA in se' (condizioni comuni a tutti quel giorno)
    per_giornata = collections.defaultdict(list)
    for r in righe:
        per_giornata[r['giornata']].append(r['reale'])
    stampa('TETTO 2 — sapere in che GIORNATA si gioca (effetto comune)', scomponi(per_giornata))

    # squadra/lega: un modello che conoscesse solo il contesto di squadra
    per_lega = collections.defaultdict(list)
    for r in righe:
        per_lega[r['lega']].append(r['reale'])
    stampa('TETTO 3 — sapere solo la LEGA', scomponi(per_lega))

    sh = split_half(righe)
    if sh:
        print('\nCONTROPROVA FUORI CAMPIONE (media storica del giocatore come previsione)')
        print(f"  {sh['giocatori']} giocatori con >=6 presenze, {sh['osservazioni']} previsioni")
        print(f"  correlazione {sh['corr']:+.3f}   MAE {sh['mae']:.1f}")
        print(f"  (il modello di oggi: correlazione {c_modello:+.3f})")

    print('\nCASA/TRASFERTA (quanto aggiunge il contesto piu ovvio)')
    casa = [r['reale'] for r in righe if r.get('in_casa') is True]
    fuori = [r['reale'] for r in righe if r.get('in_casa') is False]
    if len(casa) > 30 and len(fuori) > 30:
        print(f"  casa n={len(casa)} media {statistics.fmean(casa):.1f}   "
              f"trasferta n={len(fuori)} media {statistics.fmean(fuori):.1f}   "
              f"differenza {statistics.fmean(casa) - statistics.fmean(fuori):+.1f} pt")

    dentro_e_fuori(righe)
    return 0


def dentro_e_fuori(righe, minimo=4):
    """Il segnale del modello e' FRA giocatori o DENTRO lo stesso giocatore?

    Il tetto 1 misura solo la parte 'fra': ma un modello puo' anche prevedere
    QUANDO un giocatore rende sopra o sotto la propria media (forma,
    avversario, campo). Qui si tolgono le medie per giocatore da previsione e
    realta' e si guarda cosa resta: se la correlazione dei residui e' zero,
    quel canale e' completamente inesplorato -- ed e' il 94% della varianza."""
    per_slug = collections.defaultdict(list)
    for r in righe:
        per_slug[r['slug']].append(r)
    usabili = {k: v for k, v in per_slug.items() if len(v) >= minimo}
    if not usabili:
        return
    medie_prev, medie_reale, res_prev, res_reale = [], [], [], []
    for gruppo in usabili.values():
        mp = statistics.fmean(g['atteso'] for g in gruppo)
        mr = statistics.fmean(g['reale'] for g in gruppo)
        medie_prev.append(mp)
        medie_reale.append(mr)
        for g in gruppo:
            res_prev.append(g['atteso'] - mp)
            res_reale.append(g['reale'] - mr)
    n_oss = len(res_prev)
    print(f'\nIL SEGNALE DEL MODELLO E FRA O DENTRO I GIOCATORI? '
          f'({len(usabili)} giocatori con >={minimo} presenze, {n_oss} partite)')
    c_fra = _corr(medie_prev, medie_reale)
    c_dentro = _corr(res_prev, res_reale)
    print(f"  FRA giocatori   (media prevista vs media reale)   correlazione "
          f"{c_fra:+.3f}" if c_fra is not None else '  FRA: -')
    print(f"  DENTRO lo stesso giocatore (scarti dalla media)  correlazione "
          f"{c_dentro:+.3f}" if c_dentro is not None else '  DENTRO: -')
    sd_res_prev = statistics.pstdev(res_prev)
    sd_res_reale = statistics.pstdev(res_reale)
    print(f"  dispersione degli scarti: previsioni {sd_res_prev:.1f}   realta' {sd_res_reale:.1f}"
          f"   (il modello muove {sd_res_prev / sd_res_reale:.1%} di quanto muove la realta')")


if __name__ == '__main__':
    sys.exit(main())
