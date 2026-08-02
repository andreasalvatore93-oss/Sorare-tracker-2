"""errore_modello_storico — dove sbaglia il modello, giocatore per giocatore, su tutte le giornate.

PERCHE' ESISTE. Il repo misura gia' l'errore in due modi, ed entrambi
rispondono a un'altra domanda:

  - `backtest_arene.py` confronta FORMAZIONI intere (utente contro modello):
    dice chi vince, non dove il modello si sbaglia;
  - i `validate_*.py` in formazione_mls/diagnostics misurano l'effetto di un
    singolo parametro sul MAE del pool di calibrazione.

Qui la domanda e' diversa: **su chi sbaglia, e in che verso**. Serve per
correggere il modello, non per giudicarlo.

IL CAMPIONE. Le arene davvero giocate dall'utente (`arene_formazioni.json`,
593 formazioni su 71 giornate). Sono il campione piu' pulito che esista in
questo progetto: **in arena non c'e' nessun bonus di carta ne' di formazione**,
quindi il punteggio pubblicato da Sorare E' il punteggio grezzo del giocatore,
l'unica cosa che il modello prova a prevedere. L'unica correzione e' il
capitano (+20%, additivo), che qui viene tolto esplicitamente.

Nelle In Season e nelle All Star invece i punteggi hanno dentro bonus carta e
bonus formazione: usarli senza toglierli gonfia l'errore proprio sulle carte
migliori. Vedi `punteggi_grezzi.py`.

LA PREVISIONE. Rigiocata all'indietro con `backtest_arene_previsioni`, che
chiama le stesse funzioni di produzione (`compute_score_atteso_*`): nessuna
formula riscritta, walk-forward stretto (si vedono solo partite precedenti a
quella della giornata).

COSA NON MISURA. Chi non e' sceso in campo (punteggio 0) e' escluso: un
infortunio al primo minuto non e' un errore di previsione, e' alea. Chi ha
giocato poco e preso pochi punti invece resta, perche' quei punti sono il
risultato di eventi (decisivi negativi, granulari) che il modello dovrebbe
saper prevedere.

Uso:
  python errore_modello_storico.py --giornate 5
  python errore_modello_storico.py                      # tutte
  python errore_modello_storico.py --json dati_globali/errore_storico.json
"""
import argparse
import collections
import json
import math
import os
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as P

CAPITANO_ARENA = 0.2


def fine_giornate():
    with open(os.path.join(ROOT, 'dati_globali', 'arene_storico.json'), encoding='utf-8') as f:
        arene = (json.load(f) or {}).get('arene') or []
    fine = {}
    for a in arene:
        prec = fine.get(a['fixture'])
        fine[a['fixture']] = a['fine'] if prec is None else min(prec, a['fine'])
    return {k: P._dt(v) for k, v in fine.items()}


def lega_per_slug():
    """La lega di ogni giocatore: la cartella da cui viene la sua previsione."""
    import glob
    fuori = {}
    for percorso in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*', 'prediction_log*.json')):
        lega = os.path.normpath(percorso).split(os.sep)[-4].replace('formazione_', '')
        try:
            with open(percorso, encoding='utf-8') as f:
                dati = json.load(f) or {}
        except (ValueError, OSError):
            continue
        for voce in dati.values():
            fuori.setdefault(voce.get('player_slug'), lega)
    return fuori


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


def riepilogo(righe):
    x = [r['atteso'] for r in righe]
    y = [r['reale'] for r in righe]
    err = [b - a for a, b in zip(x, y)]
    return {
        'n': len(righe),
        'mae': statistics.fmean(abs(e) for e in err),
        'bias': statistics.fmean(err),
        'corr': _corr(x, y),
        'sd_prev': statistics.pstdev(x) if len(x) > 1 else 0.0,
        'sd_reale': statistics.pstdev(y) if len(y) > 1 else 0.0,
    }


def tabella(titolo, gruppi, minimo=15):
    print(f'\n{titolo}')
    print(f"  {'':22s} {'n':>5s} {'MAE':>6s} {'bias':>7s} {'corr':>6s} {'sd_prev':>8s} {'sd_reale':>9s}")
    for chiave, righe in sorted(gruppi.items(), key=lambda kv: -len(kv[1])):
        if len(righe) < minimo:
            continue
        s = riepilogo(righe)
        c = f"{s['corr']:+.3f}" if s['corr'] is not None else '   -  '
        print(f"  {str(chiave)[:22]:22s} {s['n']:5d} {s['mae']:6.1f} {s['bias']:+7.1f} "
              f"{c:>6s} {s['sd_prev']:8.1f} {s['sd_reale']:9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--giornate', type=int, default=None,
                    help='usa solo le N giornate piu' + "'" + ' recenti (default: tutte)')
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    with open(os.path.join(ROOT, 'dati_globali', 'arene_formazioni.json'), encoding='utf-8') as f:
        formazioni = (json.load(f) or {})['formazioni']
    fine = fine_giornate()
    cache = backtest_arene_cache.CacheLocale()
    lega_di = lega_per_slug()

    per_giornata = collections.defaultdict(list)
    for chiave, v in formazioni.items():
        per_giornata[v['fixture']].append(v)
    giornate = sorted(per_giornata, key=lambda g: fine.get(g) or P._dt('1970-01-01T00:00:00Z'))
    if args.giornate:
        giornate = giornate[-args.giornate:]

    print('=' * 82)
    print(f'ERRORE DEL MODELLO, GIOCATORE PER GIOCATORE — {len(giornate)} giornate di arene')
    print('=' * 82)

    memo = {}
    righe = []
    saltate = collections.Counter()
    visti = set()
    for giornata in giornate:
        fd = fine.get(giornata)
        if fd is None:
            saltate['giornata senza data'] += 1
            continue
        for v in per_giornata[giornata]:
            for g in v['giocatori']:
                chiave = (giornata, g['carta'])
                if chiave in visti:
                    continue          # la stessa carta puo' comparire in piu' arene
                visti.add(chiave)
                reale = g.get('punteggio')
                if reale is None:
                    saltate['senza punteggio'] += 1
                    continue
                if g.get('capitano'):
                    reale = reale / (1.0 + CAPITANO_ARENA)
                if reale == 0:
                    saltate['non ha giocato'] += 1
                    continue
                k = (g['slug'], g['ruolo'], giornata)
                if k not in memo:
                    memo[k] = P.score_atteso(cache, g['slug'], g['ruolo'], fd)
                r = memo[k]
                if r is None or r.get('atteso') is None:
                    saltate['storico insufficiente'] += 1
                    continue
                righe.append({
                    'giornata': giornata, 'slug': g['slug'], 'nome': g['nome'],
                    'ruolo': g['ruolo'], 'lega': lega_di.get(g['slug']) or '?',
                    'atteso': r['atteso'], 'reale': reale, 'errore': reale - r['atteso'],
                    'l10': r.get('l10'), 'partite_storiche': r.get('partite_storiche'),
                    'in_casa': r.get('in_casa'),
                })

    if not righe:
        print('nessuna osservazione utilizzabile')
        return 1

    s = riepilogo(righe)
    print(f"osservazioni {s['n']}   scartate: " +
          ', '.join(f'{v} {k}' for k, v in saltate.most_common()))
    c = f"{s['corr']:+.3f}" if s['corr'] is not None else '-'
    print(f"\nMAE {s['mae']:.1f}   bias {s['bias']:+.1f}   correlazione {c}")
    print(f"dispersione: previsioni {s['sd_prev']:.1f}   realta' {s['sd_reale']:.1f}"
          f"   (rapporto {s['sd_reale'] / s['sd_prev']:.1f}x)")

    tabella('PER RUOLO', _gruppi(righe, 'ruolo'))
    tabella('PER LEGA', _gruppi(righe, 'lega'), minimo=40)

    ordinate = sorted(righe, key=lambda r: r['atteso'])
    fasce = {}
    for i in range(5):
        pezzo = ordinate[i * len(ordinate) // 5:(i + 1) * len(ordinate) // 5]
        if pezzo:
            fasce[f'{i+1}. {pezzo[0]["atteso"]:.0f}-{pezzo[-1]["atteso"]:.0f}'] = pezzo
    tabella('PER FASCIA DI PREVISIONE (il modello ordina bene?)', fasce, minimo=1)

    for ruolo in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
        sotto = [r for r in righe if r['ruolo'] == ruolo]
        if len(sotto) < 40:
            continue
        ordinate = sorted(sotto, key=lambda r: r['atteso'])
        fasce = {}
        for i in range(3):
            pezzo = ordinate[i * len(ordinate) // 3:(i + 1) * len(ordinate) // 3]
            if pezzo:
                fasce[f'{pezzo[0]["atteso"]:.0f}-{pezzo[-1]["atteso"]:.0f}'] = pezzo
        tabella(f'{ruolo.upper()} per fascia', fasce, minimo=1)

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(righe, f, ensure_ascii=False, indent=1)
        print(f'\nscritto {args.json} ({len(righe)} righe)')
    return 0


def _gruppi(righe, campo):
    fuori = collections.defaultdict(list)
    for r in righe:
        fuori[r.get(campo) or '?'].append(r)
    return fuori


if __name__ == '__main__':
    sys.exit(main())
