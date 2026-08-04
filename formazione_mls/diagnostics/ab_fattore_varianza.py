"""ab_fattore_varianza — FORZA_NORM serve o no, misurato con la metrica giusta.

IL PROBLEMA. `fattore_varianza` scala i bonus di sinergia in base a quanto forte
sta venendo la formazione, ma la curva su cui si appoggia (_CAMBIO_DISPERSIONE)
e' misurata su una formazione ARENA da 5 slot, fascia 255-300, mentre
`_forza_stimata` proietta sul numero di slot VERO del tipo. Misurato
strumentando il generatore vero:

  ARENA_ALLSTARS_260   mai chiamato (quelle passano dal knapsack)
  ALLSTARS             forza 363-410  ->  fattore 0.585 SEMPRE (un solo valore)
  MLS_IN_SEASON        forza 239-266  ->  fattore 1.43-1.47

Cioe': su All Stars il meccanismo e' inerte (sconto fisso del 41%), sulle In
Season gonfia del 45% proprio dove la varianza conta meno, e dove la curva era
stata tarata non viene mai usato. FORZA_NORM=1 riporta la forza alla scala a 5
slot e passa la forza anche allo slot EXTRA (oggi l'unico escluso).

LA METRICA. Non il punteggio atteso: la sinergia non serve ad alzarlo, serve
ad alzare la correlazione fra gli schierati e quindi la varianza del totale. Si
misura la P(superare la soglia), a soglie FISSE (indispensabili per confrontare
due configurazioni che generano formazioni diverse). Monte Carlo su punteggi
REALI, coi compagni campionati dalla STESSA partita vera: la correlazione e'
preservata per costruzione, non per ipotesi.

Riusa carica_storico/simula di ab_inseason_synergy_threshold senza modificarli,
cosi' l'eventuale differenza non puo' venire dallo strumento.

Uso:  python formazione_mls/diagnostics/ab_fattore_varianza.py
      TIPI=ALLSTARS SOGLIE="470,490,510,530,550,570" python .../ab_fattore_varianza.py
"""
import importlib
import os
import random
import statistics
import sys

os.environ.setdefault('IN_SEASON', '')
os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '0')
os.environ.setdefault('ARENA_ALLSTARS_220', '0')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '0')
os.environ.setdefault('ALLSTARS', '0')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))
sys.path.insert(0, os.path.join(os.getcwd(), 'formazione_mls', 'diagnostics'))

import ab_inseason_synergy_threshold as base  # noqa: E402

N_TRIALS = int(os.environ.get('N_TRIALS', '100000'))

# quante formazioni, quale bonus capitano e quali soglie per ogni tipo.
# Le soglie sono FISSE e vengono da dove il tipo si gioca davvero: All Stars
# dalla calibrazione del 31/07 (sez. 42.A), In Season dai bersagli reali
# forniti dall'utente.
CONFIG = {
    'ALLSTARS': {'quante': 4, 'cap': 0.5,
                 'soglie': (470, 490, 510, 530, 550, 570)},
    'MLS_IN_SEASON': {'quante': 6, 'cap': 0.2,
                      'soglie': (320, 340, 360, 380, 400, 420)},
}
IN_SEASON_ENV = {'MLS_IN_SEASON': 'mls', 'KLEAGUE_IN_SEASON': 'kleague'}


def genera(tipo, norm):
    """Genera col generatore VERO. L'unica differenza fra i due rami e'
    FORZA_NORM, letto da build_formazione_finale all'import."""
    for var in ('ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220',
                'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS', 'ALLSTARS_U23'):
        os.environ[var] = '0'
    os.environ['IN_SEASON'] = ''
    quante = CONFIG[tipo]['quante']
    if tipo in IN_SEASON_ENV:
        os.environ['IN_SEASON'] = f'{IN_SEASON_ENV[tipo]}:{quante}'
    else:
        os.environ[tipo] = str(quante)
    os.environ['FORZA_NORM'] = '1' if norm else '0'

    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff
    # bff e' caricato da path (non sta in sys.modules, non si puo' reload):
    # il flag si imposta direttamente sul modulo, dopo il reload di g.
    bff.FORZA_NORM = norm

    role_data, role_counts, names = g.load_league_role_data()
    role_data = g.filter_by_window(role_data)
    pools = g.build_quality_pools(role_data)
    merged = {}
    for role in g.ROLES:
        acc = {}
        for lg in g.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged[role] = acc
    card_pool = bff.CardPool(merged, names=names)
    risultati = g.generate_lineups_for_type(tipo, quante, role_data, pools, card_pool)

    formazioni, captained = [], set()
    for r in risultati:
        if 'error' in r:
            continue
        f = r['formazione']
        _s, cap_row, _c = bff.pick_captain(f, captained)
        captained.add(cap_row['slug'])
        formazioni.append({'slugs': [row['slug'] for _sl, row, _ct in f],
                           'capitano': cap_row['slug'],
                           'atteso': sum(row['atteso'] for _sl, row, _ct in f)})
    return formazioni


def p_almeno_una(formazioni, storico, soglia):
    """Come si gioca davvero: piu' formazioni, un solo premio."""
    tot = [t for t in (base.simula(f, storico, N_TRIALS) for f in formazioni) if t]
    if not tot:
        return None, 0
    p_nessuna = 1.0
    for t in tot:
        p_nessuna *= 1.0 - sum(1 for x in t if x > soglia) / len(t)
    return 1.0 - p_nessuna, len(tot)


def main():
    tipi = [t.strip() for t in os.environ.get(
        'TIPI', 'ALLSTARS,MLS_IN_SEASON').split(',') if t.strip()]
    print('Carico lo storico dei punteggi reali dai detail cache...')
    storico = base.carica_storico()
    print(f'Giocatori con storico utilizzabile: {len(storico)}')

    for tipo in tipi:
        if tipo not in CONFIG:
            print(f'\n{tipo}: nessuna configurazione, salto.')
            continue
        print(f"\n{'=' * 78}\n{tipo}\n{'=' * 78}")
        base.CAPTAIN_BONUS = CONFIG[tipo]['cap']
        gruppi = {}
        for norm in (False, True):
            eti = 'FORZA_NORM=1 (variante)' if norm else 'produzione oggi'
            f = genera(tipo, norm)
            if not f:
                print(f'  {eti}: nessuna formazione generata, salto il tipo.')
                gruppi = {}
                break
            gruppi[norm] = f
            print(f'  {eti}: {len(f)} formazioni, atteso medio '
                  f'{statistics.mean(x["atteso"] for x in f):.1f} pt')
        if not gruppi:
            continue

        uguali = ([sorted(x['slugs']) for x in gruppi[False]]
                  == [sorted(x['slugs']) for x in gruppi[True]])
        if uguali:
            print('\n  Le formazioni sono IDENTICHE: su questo snapshot la '
                  'variante non cambia nessuna scelta, niente da simulare.')
            continue

        soglie = os.environ.get('SOGLIE', '').strip()
        soglie = ([float(x) for x in soglie.split(',')] if soglie
                  else CONFIG[tipo]['soglie'])
        print(f"\n  {'soglia':>8} {'P oggi':>10} {'P variante':>12} {'differenza':>13}")
        for s in soglie:
            random.seed(20260804)
            p_no, n_no = p_almeno_una(gruppi[False], storico, s)
            random.seed(20260804)
            p_si, n_si = p_almeno_una(gruppi[True], storico, s)
            if p_no is None or p_si is None or n_no != n_si:
                print(f'  {s:>8.0f} {"n/d":>10} {"n/d":>12}   '
                      f'formazioni simulabili diverse ({n_no} vs {n_si})')
                continue
            print(f'  {s:>8.0f} {p_no * 100:>9.2f}% {p_si * 100:>11.2f}% '
                  f'{(p_si - p_no) * 100:>+12.2f} pp')
    return 0


if __name__ == '__main__':
    sys.exit(main())
