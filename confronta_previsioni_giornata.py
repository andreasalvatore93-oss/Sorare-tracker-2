"""confronta_previsioni_giornata — quanto ha sbagliato il modello, giocatore per giocatore.

A COSA SERVE. Fino ad oggi il modello e' stato validato solo all'indietro
(backtest walk-forward su cache storica). Questo script fa la cosa piu' diretta
possibile: prende le previsioni che la produzione ha DAVVERO scritto prima
della giornata (`prediction_log.json`, salvato da
`formazione_mls/predict/live_prediction_log.py` ad ogni run non di
calibrazione) e le confronta con i punteggi REALI delle carte che il manager ha
schierato, scaricati da `ricostruisci_manager.py`.

Nessuna formula viene ricalcolata qui: si legge cio' che il modello ha detto,
non cio' che direbbe oggi. Vale per qualunque giornata, anche passata, purche'
esistano i due ingredienti:

  1. `dati_globali/manager_<slug>.json`  -> python ricostruisci_manager.py <slug> --giornate <giornata>
  2. le previsioni della giornata dentro `formazione_*/output/*/prediction_log.json`
     (o `prediction_log_resolved.json`, se nel frattempo sono state risolte)

DUE TRAPPOLE, entrambe gia' costate care in passato (sezione 50.6 del riassunto):

  - IL CAPITANO. I punteggi che Sorare mette in classifica includono GIA' il
    +20% del capitano. Il modello prevede il punteggio GREZZO. Confrontarli
    cosi' com'e' gonfia l'errore del capitano di ~1/6. Qui il punteggio del
    capitano viene riportato a grezzo dividendo per 1.2.
  - LA CONSOLE WINDOWS e' cp1252 e muore stampando nomi coreani. stdout forzato
    a UTF-8.

Uso:
  python confronta_previsioni_giornata.py
  python confronta_previsioni_giornata.py --giornata football-31-jul-4-aug-2026
  python confronta_previsioni_giornata.py --manager forever-young --json out.json
  python confronta_previsioni_giornata.py --includi-zero      # tiene chi non ha giocato
"""
import argparse
import collections
import datetime
import glob
import json
import math
import os
import re
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
MOLTIPLICATORE_CAPITANO = 1.2

MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def finestra_giornata(slug):
    """Da 'football-31-jul-4-aug-2026' a (2026-07-31, 2026-08-04).

    Due forme in circolazione: con il mese ripetuto ('31-jul-4-aug-2026') e
    senza, quando inizio e fine cadono nello stesso mese ('4-7-aug-2026'). Il
    capodanno e' l'unico caso in cui l'anno dell'inizio non e' quello della
    fine, e si riconosce dal mese che torna indietro.
    """
    m = re.search(r'(\d{1,2})-([a-z]{3})-(\d{1,2})-([a-z]{3})-(\d{4})$', slug)
    if m:
        g1, m1, g2, m2, anno = int(m.group(1)), MESI[m.group(2)], int(m.group(3)), MESI[m.group(4)], int(m.group(5))
        anno1 = anno - 1 if m1 > m2 else anno
        return datetime.date(anno1, m1, g1), datetime.date(anno, m2, g2)
    m = re.search(r'(\d{1,2})-(\d{1,2})-([a-z]{3})-(\d{4})$', slug)
    if m:
        g1, g2, mese, anno = int(m.group(1)), int(m.group(2)), MESI[m.group(3)], int(m.group(4))
        return datetime.date(anno, mese, g1), datetime.date(anno, mese, g2)
    return None


def carica_previsioni():
    """Tutte le previsioni di produzione, di ogni lega e ogni ruolo.

    Chiave (giocatore, giorno della partita). Se lo stesso giocatore e' stato
    predetto piu' volte per la stessa partita -- normale, la pipeline gira piu'
    volte prima della scadenza -- vince l'ULTIMA, che e' quella su cui si e'
    davvero schierato.
    """
    per_chiave = {}
    for percorso in sorted(glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*', 'prediction_log*.json'))):
        lega = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(percorso))))
        lega = lega.replace('formazione_', '')
        try:
            with open(percorso, encoding='utf-8') as f:
                dati = json.load(f) or {}
        except (ValueError, OSError):
            continue
        for voce in dati.values():
            giorno = (voce.get('game_date') or '')[:10]
            if not giorno or voce.get('score_atteso') is None:
                continue
            voce = dict(voce, lega=lega)
            chiave = (voce.get('player_slug'), giorno)
            gia = per_chiave.get(chiave)
            if gia is None or (voce.get('generated_at') or '') >= (gia.get('generated_at') or ''):
                per_chiave[chiave] = voce
    return per_chiave


def accoppia(formazioni, previsioni, inizio, fine, includi_zero):
    """Una riga per ogni carta schierata di cui esiste una previsione."""
    righe = []
    senza_previsione = []
    non_giocate = 0
    for formazione in formazioni:
        for carta in formazione.get('carte') or []:
            slug = carta.get('slug')
            reale = carta.get('punteggio')
            if reale is None:
                continue
            if carta.get('capitano'):
                reale = reale / MOLTIPLICATORE_CAPITANO
            if reale == 0 and not includi_zero:
                non_giocate += 1
                continue
            trovata = None
            giorno = inizio
            while giorno <= fine:
                candidata = previsioni.get((slug, giorno.isoformat()))
                if candidata is not None:
                    trovata = candidata
                    break
                giorno += datetime.timedelta(days=1)
            if trovata is None:
                senza_previsione.append(carta.get('nome') or slug)
                continue
            atteso = trovata['score_atteso']
            righe.append({
                'slug': slug,
                'nome': carta.get('nome') or slug,
                'ruolo': carta.get('ruolo'),
                'lega': trovata.get('lega'),
                'capitano': bool(carta.get('capitano')),
                'competizione': formazione.get('competizione'),
                'atteso': atteso,
                'reale': reale,
                'errore': reale - atteso,
                'data_partita': trovata.get('game_date'),
            })
    return righe, senza_previsione, non_giocate


def _regressione(x, y):
    """reale ~ a + b * previsto. Serve a vedere se la scala e' giusta: b<1
    vuol dire previsioni schiacciate, che e' esattamente il difetto noto."""
    n = len(x)
    if n < 3:
        return None, None, None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if sxx == 0:
        return None, None, None
    b = sxy / sxx
    a = my - b * mx
    syy = sum((v - my) ** 2 for v in y)
    r = sxy / math.sqrt(sxx * syy) if syy > 0 else None
    return a, b, r


def _riepilogo(righe):
    errori = [r['errore'] for r in righe]
    return {
        'n': len(righe),
        'mae': statistics.fmean(abs(e) for e in errori),
        'bias': statistics.fmean(errori),
        'atteso_medio': statistics.fmean(r['atteso'] for r in righe),
        'reale_medio': statistics.fmean(r['reale'] for r in righe),
        'disp_atteso': statistics.pstdev([r['atteso'] for r in righe]),
        'disp_reale': statistics.pstdev([r['reale'] for r in righe]),
    }


def _tabella(titolo, gruppi, minimo=3):
    print(f'\n{titolo}')
    print(f"  {'':22s} {'n':>4s} {'MAE':>7s} {'bias':>7s} {'atteso':>8s} {'reale':>8s}")
    for chiave, righe in sorted(gruppi.items(), key=lambda kv: -len(kv[1])):
        if len(righe) < minimo:
            continue
        s = _riepilogo(righe)
        print(f"  {str(chiave)[:22]:22s} {s['n']:4d} {s['mae']:7.1f} {s['bias']:+7.1f} "
              f"{s['atteso_medio']:8.1f} {s['reale_medio']:8.1f}")


def stampa(righe, senza_previsione, non_giocate, giornata):
    s = _riepilogo(righe)
    print('=' * 70)
    print(f'CONFRONTO PREVISIONE / REALTA\'  —  {giornata}')
    print('=' * 70)
    print(f"osservazioni: {s['n']}   scartate perche' non hanno giocato: {non_giocate}   "
          f"senza previsione: {len(senza_previsione)}")
    if senza_previsione:
        print('  ' + ', '.join(sorted(set(senza_previsione))[:10]))
    print(f"\nMAE           {s['mae']:6.1f} punti")
    print(f"bias          {s['bias']:+6.1f}  (negativo = il modello e' OTTIMISTA)")
    print(f"medie         atteso {s['atteso_medio']:.1f}   reale {s['reale_medio']:.1f}")
    print(f"dispersione   atteso {s['disp_atteso']:.1f}   reale {s['disp_reale']:.1f}"
          f"   (se la prima e' molto piu' bassa, le previsioni sono schiacciate)")

    a, b, r = _regressione([x['atteso'] for x in righe], [x['reale'] for x in righe])
    if b is not None:
        print(f"\nricalibrazione  reale = {a:.1f} + {b:.3f} x previsto     correlazione {r:.3f}")

    _tabella('PER RUOLO', collections.defaultdict(list, _raggruppa(righe, 'ruolo')))
    _tabella('PER LEGA', collections.defaultdict(list, _raggruppa(righe, 'lega')))
    _tabella('PER COMPETIZIONE', collections.defaultdict(list, _raggruppa(righe, 'competizione')))

    ordinate = sorted(righe, key=lambda x: x['atteso'])
    n_fasce = 5
    fasce = {}
    for i in range(n_fasce):
        pezzo = ordinate[i * len(ordinate) // n_fasce:(i + 1) * len(ordinate) // n_fasce]
        if pezzo:
            fasce[f'{i+1}. {pezzo[0]["atteso"]:.0f}-{pezzo[-1]["atteso"]:.0f}'] = pezzo
    _tabella('PER FASCIA DI PREVISIONE (il modello ordina bene?)', fasce, minimo=1)

    print('\nDOVE HA SBAGLIATO DI PIU\' (sottostimati)')
    for r_ in sorted(righe, key=lambda x: -x['errore'])[:10]:
        print(f"  {r_['nome'][:24]:24s} {r_['ruolo'][:3]:3s} atteso {r_['atteso']:6.1f}  "
              f"reale {r_['reale']:6.1f}  {r_['errore']:+6.1f}")
    print('\nDOVE HA SBAGLIATO DI PIU\' (sopravvalutati)')
    for r_ in sorted(righe, key=lambda x: x['errore'])[:10]:
        print(f"  {r_['nome'][:24]:24s} {r_['ruolo'][:3]:3s} atteso {r_['atteso']:6.1f}  "
              f"reale {r_['reale']:6.1f}  {r_['errore']:+6.1f}")


def _raggruppa(righe, campo):
    fuori = collections.defaultdict(list)
    for r in righe:
        fuori[r.get(campo) or '?'].append(r)
    return fuori


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss', help='slug del manager (default: crowss)')
    ap.add_argument('--giornata', default=None,
                    help='slug della giornata; se omesso, tutte quelle presenti nel file del manager')
    ap.add_argument('--includi-zero', action='store_true',
                    help='tiene anche le carte a punteggio 0 (chi non ha giocato)')
    ap.add_argument('--json', default=None, help='file di uscita con una riga per osservazione')
    args = ap.parse_args()

    percorso = os.path.join(ROOT, 'dati_globali', f'manager_{args.manager}.json')
    if not os.path.exists(percorso):
        print(f'manca {percorso}: lancia prima ricostruisci_manager.py {args.manager}')
        return 1
    with open(percorso, encoding='utf-8') as f:
        dati = json.load(f)

    previsioni = carica_previsioni()
    print(f'previsioni di produzione caricate: {len(previsioni)}')

    giornate = [args.giornata] if args.giornata else list(dati.get('giornate') or {})
    tutte = []
    for giornata in giornate:
        formazioni = (dati.get('giornate') or {}).get(giornata)
        if not formazioni:
            print(f'{giornata}: nessuna formazione nel file del manager')
            continue
        finestra = finestra_giornata(giornata)
        if finestra is None:
            print(f'{giornata}: non riesco a ricavare le date dallo slug')
            continue
        inizio, fine = finestra
        righe, senza, zero = accoppia(formazioni, previsioni, inizio, fine, args.includi_zero)
        if not righe:
            print(f'{giornata}: nessuna carta schierata ha una previsione salvata')
            continue
        for r in righe:
            r['giornata'] = giornata
        stampa(righe, senza, zero, giornata)
        tutte.extend(righe)

    if args.json and tutte:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(tutte, f, ensure_ascii=False, indent=1)
        print(f'\nscritto {args.json} ({len(tutte)} righe)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
