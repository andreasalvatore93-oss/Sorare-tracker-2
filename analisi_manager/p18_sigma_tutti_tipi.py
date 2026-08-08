"""PASSO 2 (BRIEF_SONNET_SOGLIE_DEFINITIVE_2026-08-08): rimisura la sigma
(residuo atteso-vs-realizzato) per TUTTI i tipi di arena su un campione
vero, non piu' solo sulle 8 osservazioni cap 220 del 05/08.

Per ogni arena REALMENTE giocata da un manager (formazione FISSA = quella
che ha schierato, nessuna selezione qui, come TEST3 di
p13_backtest_gw_crowss.py): atteso = somma degli score_atteso calibrati
walk-forward delle 5 carte + 0.2 * atteso del capitano (bonus arena).
realizzato = punteggio UFFICIALE della formazione (gia' con bonus, stessa
scala di PAREGGIO_ARENA). residuo = realizzato - atteso.

SOLO MISURA. Non tocca produzione, non scrive in dati_globali/arene_storico*.

Uso: python analisi_manager/p18_sigma_tutti_tipi.py
"""
import os
import sys
import io
import json
import glob
import collections
import statistics

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M

cache = CACHE.CacheLocale()

# tipo_arena ammessi (arena_altro/arena_rare esclusi: n troppo piccolo/formato
# non chiaro, non richiesti dal brief).
TIPO_ARENA_AMMESSI = {'arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped'}

# competizione -> tipo per la tabella finale (i 4 tipi del brief). 'Elite' e
# le arene dedicate a campionato (Jupiler, ecc.) NON sono nei 4 richiesti,
# escluse qui.
COMP_TIPO = {'Cap 260': 'cap 260', 'Cap 220': 'cap 220', 'Uncapped': 'Uncapped',
             'Beginner': 'Beginner'}


def carica_tutte_le_giornate():
    out = []  # (manager, gw, riga)
    for path in glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')):
        manager = os.path.basename(path)[len('manager_'):-len('.json')]
        d = json.load(open(path, encoding='utf-8'))
        for gw, righe in (d.get('giornate') or {}).items():
            for r in righe:
                if r.get('tipo_arena') in TIPO_ARENA_AMMESSI and r.get('competizione') in COMP_TIPO:
                    out.append((manager, gw, r))
    return out


def main():
    righe = carica_tutte_le_giornate()
    print(f'arene candidate (tipo_arena ammesso + competizione nota): {len(righe)}')

    bounds_cache = {}
    residui = collections.defaultdict(list)
    scarti = collections.Counter()
    dettaglio_sample = collections.defaultdict(list)

    for manager, gw, r in righe:
        tipo = COMP_TIPO[r['competizione']]
        carte = r.get('carte')
        if not carte or len(carte) < 5:
            scarti['formazione_incompleta'] += 1
            continue
        if gw not in bounds_cache:
            bounds_cache[gw] = M.parse_fixture_bounds(gw)
        bounds = bounds_cache[gw]
        if bounds is None:
            scarti['gw_senza_date'] += 1
            continue
        d_start, d_end = bounds
        import datetime
        fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)

        attesi = []
        ok = True
        cap_idx = None
        for i, c in enumerate(carte):
            slug = c.get('slug')
            ruolo_full = c.get('ruolo')
            atteso_r = P.score_atteso(cache, slug, ruolo_full, fine)
            if atteso_r is None or atteso_r.get('atteso') is None:
                ok = False
                break
            cod = M.ROLE_CODE.get(ruolo_full)
            if cod is None:
                ok = False
                break
            cal = S21.bfg.calibra(atteso_r['atteso'], cod)
            attesi.append(cal)
            if c.get('capitano'):
                cap_idx = i
        if not ok:
            scarti['no_atteso'] += 1
            continue
        atteso_tot = sum(attesi) + (0.2 * attesi[cap_idx] if cap_idx is not None else 0.0)
        realizzato = sum(c.get('punteggio') or 0 for c in carte)
        residuo = realizzato - atteso_tot
        residui[tipo].append(residuo)
        if len(dettaglio_sample[tipo]) < 3:
            dettaglio_sample[tipo].append((manager, gw, atteso_tot, realizzato, residuo))

    print(f'scarti: {dict(scarti)}')
    print()
    print(f"{'tipo':10s} {'n':>5} {'media residuo':>14} {'sigma':>8}")
    risultato = {}
    for tipo, vals in residui.items():
        if len(vals) < 2:
            continue
        m = statistics.mean(vals)
        sd = statistics.pstdev(vals)
        risultato[tipo] = {'n': len(vals), 'media': m, 'sigma': sd}
        print(f'{tipo:10s} {len(vals):>5} {m:>+14.2f} {sd:>8.2f}')

    print()
    print('campioni (manager, gw, atteso, realizzato, residuo):')
    for tipo, camp in dettaglio_sample.items():
        print(f'  {tipo}:')
        for c in camp:
            print(f'    {c}')

    json.dump({'n_totale_candidate': len(righe), 'scarti': dict(scarti), 'per_tipo': risultato},
               open('analisi_manager/p18_sigma_risultato.json', 'w', encoding='utf-8'),
               ensure_ascii=False, indent=1)
    print('\nscritto analisi_manager/p18_sigma_risultato.json')


if __name__ == '__main__':
    main()
