"""confronta_in_season — le formazioni In Season di una giornata, rigiocate col modello di OGGI.

PERCHE' NON BASTA `confronta_previsioni_giornata.py`. Quello legge le previsioni
che la produzione aveva SCRITTO al momento (`prediction_log.json`). Se nel
frattempo il modello e' stato ritoccato, quel confronto misura un modello che
non esiste piu'. Qui le previsioni vengono RIFATTE walk-forward con le funzioni
di produzione attuali (`backtest_arene_previsioni`, che importa direttamente
`compute_score_atteso_*`): stesso taglio storico, nessuna informazione dal
futuro.

Le due previsioni vengono affiancate, cosi' si vede se la revisione ha
migliorato o peggiorato, sulle stesse carte e sugli stessi risultati.

Il punteggio del CAPITANO che arriva da Sorare include gia' il +20%: qui viene
riportato a grezzo (/1.2), altrimenti il capitano sembrerebbe sempre
sottostimato.

Uso:
  python confronta_in_season.py --lega us
  python confronta_in_season.py --lega korea --giornata football-31-jul-4-aug-2026
  python confronta_in_season.py --lega us --json out.json
"""
import argparse
import collections
import datetime
import json
import os
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as P
from confronta_previsioni_giornata import (carica_previsioni, finestra_giornata,
                                           MOLTIPLICATORE_CAPITANO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('--giornata', default='football-31-jul-4-aug-2026')
    ap.add_argument('--lega', default='us',
                    help="frammento dello slug leaderboard: us, korea, ... (in_season_<lega>_)")
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    percorso = os.path.join(ROOT, 'dati_globali', f'manager_{args.manager}.json')
    with open(percorso, encoding='utf-8') as f:
        dati = json.load(f)
    formazioni = [x for x in dati['giornate'][args.giornata]
                  if f'in_season_{args.lega}_' in (x.get('leaderboard') or '')]
    if not formazioni:
        print(f'nessuna formazione in_season_{args.lega}_ nella giornata {args.giornata}')
        return 1

    inizio, fine = finestra_giornata(args.giornata)
    fine_dt = datetime.datetime.combine(fine, datetime.time(23, 59))
    vecchie = carica_previsioni()
    cache = backtest_arene_cache.CacheLocale()

    memo = {}

    def nuova(slug, ruolo):
        if (slug, ruolo) not in memo:
            memo[(slug, ruolo)] = P.score_atteso(cache, slug, ruolo, fine_dt)
        return memo[(slug, ruolo)]

    righe = []
    for f_ in formazioni:
        for carta in f_.get('carte') or []:
            reale = carta.get('punteggio')
            if reale is None:
                continue
            if carta.get('capitano'):
                reale = reale / MOLTIPLICATORE_CAPITANO
            slug, ruolo = carta['slug'], carta['ruolo']
            r = nuova(slug, ruolo)
            v = None
            giorno = inizio
            while giorno <= fine:
                v = vecchie.get((slug, giorno.isoformat()))
                if v is not None:
                    break
                giorno += datetime.timedelta(days=1)
            righe.append({
                'formazione': f_['leaderboard'],
                'contender': f_['contender'],
                'nome': carta.get('nome') or slug,
                'slug': slug,
                'ruolo': ruolo,
                'capitano': bool(carta.get('capitano')),
                'reale': reale,
                'atteso_vecchio': (v or {}).get('score_atteso'),
                'atteso_nuovo': (r or {}).get('atteso'),
                'l10': (r or {}).get('l10'),
                'partite_storiche': (r or {}).get('partite_storiche'),
                'in_casa': (r or {}).get('in_casa'),
                'squadra': (r or {}).get('squadra'),
                'piazzamento': (f_.get('piazzamento') or {}).get('rank'),
                'punteggio_formazione': (f_.get('piazzamento') or {}).get('punteggio'),
            })

    _stampa(righe, args)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(righe, f, ensure_ascii=False, indent=1)
        print(f'\nscritto {args.json}')
    return 0


def _sintesi(valori, reali):
    coppie = [(a, b) for a, b in zip(valori, reali) if a is not None]
    if not coppie:
        return None
    err = [b - a for a, b in coppie]
    return {
        'n': len(coppie),
        'mae': statistics.fmean(abs(e) for e in err),
        'bias': statistics.fmean(err),
        'disp': statistics.pstdev([a for a, _ in coppie]) if len(coppie) > 1 else 0.0,
    }


def _stampa(righe, args):
    reali = [r['reale'] for r in righe]
    print('=' * 70)
    print(f"IN SEASON {args.lega.upper()} — {args.giornata}")
    print('=' * 70)
    per_formazione = collections.OrderedDict()
    for r in righe:
        per_formazione.setdefault(r['contender'], []).append(r)
    print(f"{len(per_formazione)} formazioni, {len(righe)} carte, "
          f"dispersione dei punteggi reali {statistics.pstdev(reali):.1f}")

    for nome, sintesi in (('previsione DEL MOMENTO', _sintesi([r['atteso_vecchio'] for r in righe], reali)),
                          ('previsione DI OGGI    ', _sintesi([r['atteso_nuovo'] for r in righe], reali))):
        if sintesi is None:
            print(f'{nome}: nessuna disponibile')
            continue
        print(f"{nome}: n={sintesi['n']:3d}  MAE {sintesi['mae']:5.1f}  "
              f"bias {sintesi['bias']:+5.1f}  dispersione previsioni {sintesi['disp']:5.1f}")

    mancanti = [r['nome'] for r in righe if r['atteso_nuovo'] is None]
    if mancanti:
        print(f"senza previsione nuova (storico insufficiente in cache): {len(mancanti)} — "
              + ', '.join(sorted(set(mancanti))[:8]))

    print('\nERRORI PIU\' GRANDI (previsione di oggi)')
    con = [r for r in righe if r['atteso_nuovo'] is not None]
    for r in sorted(con, key=lambda x: -abs(x['reale'] - x['atteso_nuovo']))[:15]:
        print(f"  {r['nome'][:22]:22s} {r['ruolo'][:3]:3s} "
              f"atteso {r['atteso_nuovo']:6.1f} (prima {r['atteso_vecchio'] or float('nan'):6.1f})  "
              f"reale {r['reale']:6.1f}  {r['reale'] - r['atteso_nuovo']:+6.1f}"
              f"{'  CAP' if r['capitano'] else ''}")

    print('\nPER FORMAZIONE (somma grezza, senza capitano)')
    for contender, gruppo in per_formazione.items():
        att = [g['atteso_nuovo'] for g in gruppo]
        somma_att = sum(a for a in att if a is not None) if all(a is not None for a in att) else None
        somma_reale = sum(g['reale'] for g in gruppo)
        print(f"  rank {str(gruppo[0]['piazzamento'] or '?'):>5s}  "
              f"totale Sorare {gruppo[0]['punteggio_formazione'] or 0:6.1f}  "
              f"grezzo atteso {somma_att if somma_att is None else round(somma_att, 1)}  "
              f"grezzo reale {somma_reale:6.1f}")


if __name__ == '__main__':
    sys.exit(main())
