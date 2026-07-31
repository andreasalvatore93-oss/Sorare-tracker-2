"""Verifica della sinergia same-team per ARENA e ALL STARS con la metrica
giusta: la probabilita' di superare una soglia, non il punteggio atteso.

PERCHE'. La tabella usata da Arena/All Stars
(bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR) e' nata come "correlazione misurata x
20": la correlazione fra compagni di squadra e' un dato reale, ma il
moltiplicatore 20 che la trasforma in punti e' stato scelto a occhio e mai
validato. Per le In Season la stessa domanda e' stata risolta il 31/07 con un
Monte Carlo su punteggi reali (ab_inseason_synergy_threshold.py), che ha
mostrato un effetto nullo e ha portato a lasciarle escluse. Qui si applica lo
STESSO metodo ad Arena/All Stars, dove invece la sinergia e' ATTIVA in
produzione -- quindi la domanda e' se stia aiutando davvero.

Il punto metodologico e' lo stesso: la sinergia non serve ad alzare il valore
atteso, serve ad alzare la CORRELAZIONE fra gli schierati e quindi la
varianza del totale. Con un bersaglio fisso sopra la propria media, piu'
varianza aumenta la probabilita' di superarlo anche a media invariata: il
valore atteso e' cieco proprio all'effetto per cui la tabella esiste.

METODO (identico a quello In Season, riusato per non introdurre differenze
non volute):
 1. si generano le formazioni con la configurazione di produzione (sinergia
    ATTIVA) e con la sinergia SPENTA;
 2. per ogni formazione si fa Monte Carlo sul totale campionando punteggi
    REALI storici dei giocatori effettivamente schierati;
 3. la correlazione e' preservata per COSTRUZIONE, non per ipotesi: i
    compagni di squadra vengono campionati dalla STESSA partita reale quando
    esiste una data in cui hanno giocato entrambi;
 4. si confronta P(totale > soglia) fra le due configurazioni.

Le soglie non sono fisse ma derivate dai totali attesi realmente prodotti in
questa run (mediana +/- scarti): soglie inventate a tavolino rischierebbero di
cadere tutte fuori dalla zona dove la differenza e' osservabile.

Uso:  python formazione_mls/diagnostics/ab_arena_synergy_threshold.py
      TIPI=ALLSTARS python formazione_mls/diagnostics/ab_arena_synergy_threshold.py
"""
import os
import sys
import random
import importlib
import statistics

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

# Riuso diretto di storico e Monte Carlo gia' scritti e usati per le In
# Season: stessa identica meccanica di campionamento, cosi' l'eventuale
# differenza fra i due studi non puo' venire dallo strumento.
import ab_inseason_synergy_threshold as base  # noqa: E402

N_TRIALS = int(os.environ.get('N_TRIALS', '100000'))
QUANTE = int(os.environ.get('QUANTE', '6'))
random.seed(20260731)

# Quante formazioni per tipo e con che bonus capitano. Arena: capitano +20%
# (CAPTAIN_BONUS_BY_TYPE). All Stars: +50%.
TIPI_DEFAULT = 'ARENA_ALLSTARS_260,ALLSTARS'


_PROBE = {}


def genera(tipo, usa_sinergia):
    """Genera le formazioni del tipo richiesto con la sinergia ON o OFF.

    ON = configurazione di PRODUZIONE (non si tocca nulla). OFF = si sostituisce
    synergy_sort_key con una versione che ignora il bonus same-team, lasciando
    tutto il resto (stack guard, variance mode) identico: cosi' l'unica
    differenza fra i due rami e' la sinergia."""
    for var, val in (('ARENA_ALLSTARS_260', '0'), ('ALLSTARS', '0'),
                     ('ARENA_ALLSTARS_220', '0'), ('ALLSTARS_U23', '0')):
        os.environ[var] = val
    os.environ[tipo if tipo != 'ALLSTARS' else 'ALLSTARS'] = str(QUANTE)

    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff

    # SCALA della tabella (31/07): il moltiplicatore "correlazione x 20" non e'
    # mai stato validato. Con SCALA=k la tabella viene riscalata di k/20, cosi'
    # si puo' confrontare 10/20/30/40 sulla stessa metrica (probabilita' di
    # superare la soglia) invece di fidarsi del valore storico.
    scala = float(os.environ.get('SCALA', '20')) / 20.0
    if usa_sinergia and abs(scala - 1.0) > 1e-9:
        bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR = {
            k: v * scala for k, v in bff.SAME_TEAM_SYNERGY_BONUS_BY_PAIR.items()}

    if not usa_sinergia:
        def sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None,
                     apply_stack_guard=False, variance_mode=False, apply_positive_synergy=True,
                     used_matches=None, chosen_roles_by_team=None, synergy_bonus_dict=None):
            adjusted = row.get('sort_score', row['atteso'])
            team_slug = row.get('team_slug')
            # NIENTE bonus same-team: e' esattamente cio' che si vuole misurare.
            if (apply_stack_guard and team_slug and team_counts
                    and team_counts.get(team_slug, 0) >= bff.IN_SEASON_STACK_LIMIT):
                adjusted -= bff.STACK_GUARD_PENALTY
            return adjusted

        def adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug, team_counts=None,
                          apply_stack_guard=False, variance_mode=False, apply_positive_synergy=True,
                          used_matches=None, chosen_roles_by_team=None, synergy_bonus_dict=None):
            return sorted(rows, key=lambda r: sort_key(
                role, r, gk_team_slug, gk_opponent_slug, team_counts, apply_stack_guard,
                variance_mode, apply_positive_synergy, used_matches, chosen_roles_by_team,
                synergy_bonus_dict), reverse=True)

        bff.synergy_sort_key = sort_key
        bff.synergy_adjusted_rows = adjusted_rows
        _PROBE['off_installato'] = True

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
    risultati = g.generate_lineups_for_type(tipo, QUANTE, role_data, pools, card_pool)

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


def soglie_da(formazioni_on, formazioni_off):
    """Soglie realistiche derivate dai totali attesi di QUESTA run."""
    attesi = [f['atteso'] for f in formazioni_on + formazioni_off]
    if not attesi:
        return []
    centro = statistics.median(attesi)
    # Scarti configurabili: la zona interessante non e' intorno alla media ma
    # SOPRA di essa (e' li' che la varianza puo' pagare), e dove cada il punto
    # di pareggio non si sa a priori.
    # SOGLIE assolute: indispensabili per confrontare configurazioni DIVERSE
    # fra loro. Con le soglie derivate dalla mediana, ogni configurazione
    # genera formazioni un po' diverse e quindi soglie diverse -- le righe
    # non sarebbero piu' confrontabili riga per riga.
    fisse = os.environ.get('SOGLIE', '').strip()
    if fisse:
        return [float(x) for x in fisse.split(',')]
    scarti = [float(x) for x in os.environ.get(
        'SOGLIE_OFFSET', '-40,-20,0,20,40,60').split(',')]
    return [round((centro + d) / 10) * 10 for d in scarti]


def main():
    tipi = [t.strip() for t in os.environ.get('TIPI', TIPI_DEFAULT).split(',') if t.strip()]
    print("Carico lo storico dei punteggi reali dai detail cache...")
    storico = base.carica_storico()
    print(f"Giocatori con storico utilizzabile: {len(storico)}")

    for tipo in tipi:
        print(f"\n{'=' * 78}\n{tipo}\n{'=' * 78}")
        risultati = {}
        for usa in (True, False):
            etichetta = 'sinergia ON (produzione)' if usa else 'sinergia OFF'
            formazioni = genera(tipo, usa)
            if not formazioni:
                print(f"  {etichetta}: nessuna formazione generata, salto il tipo.")
                risultati = {}
                break
            risultati[usa] = formazioni
            print(f"  {etichetta}: {len(formazioni)} formazioni, "
                  f"totale atteso medio {statistics.mean(f['atteso'] for f in formazioni):.1f} pt")
        if not risultati:
            continue

        soglie = soglie_da(risultati[True], risultati[False])
        print(f"\n  {'soglia':>8} {'P(>soglia) ON':>15} {'P(>soglia) OFF':>16} {'differenza':>13}")
        simulabili = {}
        for soglia in soglie:
            probs = {}
            for usa in (True, False):
                # simula() ritorna None se anche UN solo schierato non ha
                # storico: quelle formazioni non sono simulabili e vanno
                # escluse, non fatte passare per "mai sopra soglia".
                p = [t for t in (base.simula(f, storico, N_TRIALS)
                                 for f in risultati[usa]) if t]
                if not p:
                    probs[usa] = None
                    continue
                # probabilita' che ALMENO UNA delle formazioni superi la soglia
                # (e' cosi' che si gioca: piu' formazioni, un solo premio)
                p_nessuna = 1.0
                for tot in p:
                    p_nessuna *= (1.0 - sum(1 for t in tot if t > soglia) / len(tot))
                probs[usa] = 1.0 - p_nessuna
                simulabili[usa] = len(p)
            if probs[True] is None or probs[False] is None:
                print(f"  {soglia:>8} {'n/d':>14} {'n/d':>15} "
                      f"{'nessuna formazione simulabile':>26}")
                continue
            diff = (probs[True] - probs[False]) * 100
            print(f"  {soglia:>8} {probs[True] * 100:>14.2f}% {probs[False] * 100:>15.2f}% "
                  f"{diff:>+12.2f} pp")
        if simulabili:
            print(f"  (formazioni effettivamente simulabili: ON={simulabili.get(True)}, "
                  f"OFF={simulabili.get(False)})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
