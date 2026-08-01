"""La penalita' cross-team serve davvero? Misura con la metrica giusta.
(31/07, dopo il fix che l'ha resa attiva sulle In Season)

CONTESTO. `CROSS_TEAM_PENALTY_BY_PAIR` scoraggia di schierare insieme due
giocatori AVVERSARI nella stessa partita (es. un DEF del Minnesota e un MID
del San Diego in Minnesota-San Diego): se una squadra tiene la porta
inviolata il difensore segna e i centrocampisti avversari no, quindi i due
punteggi sono negativamente correlati. Fino al 31/07 la penalita' era INERTE
sulle In Season, per un bug: stava dentro il gate `apply_positive_synergy`,
spento li' per tutt'altro motivo.

PERCHE' RIMISURARLA. L'unico A/B che l'aveva mai toccata (29/07) non e' una
prova valida, per tre motivi: (1) spegneva TRE meccanismi insieme, quindi il
+2 pt misurato non e' attribuibile alla penalita'; (2) e' del 29/07, mentre la
coppia DEF-MID -- quella del caso reale trovato dall'utente -- e' nata il
30/07, quando il flag era gia' spento: non e' mai stata testata; (3) usava il
PUNTEGGIO ATTESO, che e' cieco all'effetto per cui la penalita' esiste. Due
giocatori anti-correlati RIDUCONO la varianza del totale, e con un bersaglio
sopra la propria media meno varianza e' un danno.

DIFFERENZA CHIAVE RISPETTO AGLI ALTRI STUDI. Il simulatore usato per le
sinergie campiona insieme solo i COMPAGNI di squadra. Qui non basta: la
correlazione da catturare e' fra AVVERSARI. Questo modulo campiona insieme
tutti i giocatori della STESSA PARTITA, da qualunque lato -- ricostruendo la
partita dalle date e dagli slug delle due squadre nel detail cache. Cosi' la
correlazione negativa fra avversari e' quella vera osservata, non assunta.

Uso:  python formazione_mls/diagnostics/ab_cross_team_threshold.py
      TIPI=MLS_IN_SEASON,KLEAGUE_IN_SEASON N_TRIALS=100000 ... (da ambiente)
"""
import glob
import json
import os
import random
import statistics
import sys
from collections import defaultdict

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

import importlib  # noqa: E402

N_TRIALS = int(os.environ.get('N_TRIALS', '100000'))
QUANTE = int(os.environ.get('QUANTE', '6'))
_s = os.environ.get('SCALA')
SCALA = float(_s) if _s else None
CAPTAIN_BONUS = 0.5
random.seed(20260731)


def carica_storico():
    """slug -> {data: (score, mia_squadra, avversario)}.

    Rispetto al simulatore delle sinergie qui serve anche l'AVVERSARIO di ogni
    partita: e' cio' che permette di riconoscere due giocatori come rivali
    nella stessa partita e campionarli dalla stessa data.
    """
    sep = chr(92)
    storico = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        if slug in storico:
            continue
        try:
            cache = json.load(open(path, encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        # squadra del giocatore = quella che compare piu' spesso
        conteggi = defaultdict(int)
        nodi = []
        for v in cache.values():
            if not isinstance(v, dict) or v.get('score') is None:
                continue
            g = v.get('anyGame') or {}
            casa = (g.get('homeTeam') or {}).get('slug')
            fuori = (g.get('awayTeam') or {}).get('slug')
            data = (g.get('date') or '')[:10]
            if not (casa and fuori and data):
                continue
            conteggi[casa] += 1
            conteggi[fuori] += 1
            nodi.append((data, float(v['score']), casa, fuori))
        if len(nodi) < 6 or not conteggi:
            continue
        mia = max(conteggi, key=conteggi.get)
        per_data = {}
        for data, score, casa, fuori in nodi:
            if mia not in (casa, fuori):
                continue
            avversario = fuori if casa == mia else casa
            per_data[data] = (score, mia, avversario)
        if len(per_data) >= 6:
            storico[slug] = per_data
    return storico


def genera(tipo, penalita_attiva):
    lega = 'mls' if tipo.startswith('MLS') else 'kleague'
    os.environ['ONLY_LEAGUES'] = lega
    os.environ['IN_SEASON'] = f"mls:{QUANTE if lega == 'mls' else 0},kleague:{QUANTE if lega == 'kleague' else 0}"
    import build_formazione_globale as g
    importlib.reload(g)
    b = g.bff
    if not penalita_attiva:
        # Esattamente com'era prima del fix: penalita' inerte.
        b._cross_team_penalty = lambda role, row, chosen: 0
    elif SCALA is not None:
        # SCALA=N riscala la tabella come se la convenzione fosse xN invece di
        # x20 (01/08): serve a misurare il moltiplicatore, mai verificato.
        _orig = b._cross_team_penalty
        _f = SCALA / 20.0
        b._cross_team_penalty = lambda role, row, chosen: _orig(role, row, chosen) * _f

    role_data, role_counts, names = g.load_league_role_data()
    role_data = g.filter_by_window(role_data)
    pools = g.build_quality_pools(role_data)
    merged = {}
    for role in g.ROLES:
        acc = {}
        for lg in g.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged[role] = acc
    card_pool = b.CardPool(merged, names=names)
    risultati = g.generate_lineups_for_type(tipo, QUANTE, role_data, pools, card_pool)

    formazioni, captained = [], set()
    for r in risultati:
        if 'error' in r:
            continue
        f = r['formazione']
        _s, cap_row, _c = b.pick_captain(f, captained)
        captained.add(cap_row['slug'])
        formazioni.append({'slugs': [row['slug'] for _sl, row, _ct in f],
                           # squadra/avversario della partita DI QUESTA giornata:
                           # serve a raggruppare correttamente chi si affronta
                           # (vedi simula), non si puo' dedurre dallo storico.
                           'squadre': {row['slug']: (row.get('team_slug'),
                                                     row.get('opponent_team_slug'))
                                       for _sl, row, _ct in f},
                           'capitano': cap_row['slug'],
                           'atteso': sum(row['atteso'] for _sl, row, _ct in f)})
    return formazioni


def simula(formazione, storico, n_trials):
    """Totale della formazione campionando punteggi reali.

    I giocatori impegnati nella STESSA partita di questa giornata -- compagni
    E avversari -- vengono campionati da una stessa data storica in cui quella
    sfida si e' gia' giocata, cosi' la loro correlazione (positiva fra
    compagni, negativa fra avversari) e' quella osservata davvero.

    NIENTE unione transitiva fra gruppi: raggruppare per co-occorrenza storica
    finiva per fondere tutti e cinque gli schierati in un blocco unico e poi
    pretendere una data in cui avessero giocato TUTTI insieme -- condizione
    quasi impossibile, che collassava la simulazione su una o due date sole e
    azzerava la varianza (visto in pratica: totali fra 342 e 343 su 20.000
    estrazioni). Il raggruppamento giusto e' quello della partita imminente,
    che per costruzione coinvolge al massimo due squadre.
    """
    membri = [s for s in formazione['slugs'] if s in storico]
    if len(membri) < len(formazione['slugs']):
        return None
    squadre = formazione.get('squadre') or {}

    # gruppi = partite di questa giornata (coppia non ordinata di squadre)
    gruppi = defaultdict(list)
    sciolti = []
    for s in membri:
        team, opp = squadre.get(s, (None, None))
        if team and opp:
            gruppi[frozenset((team, opp))].append(s)
        else:
            sciolti.append(s)

    # per ogni gruppo, le date storiche in cui TUTTI i suoi membri hanno
    # giocato la stessa partita
    date_gruppo = {}
    for chiave, membri_g in gruppi.items():
        if len(membri_g) < 2:
            continue
        comuni = set(storico[membri_g[0]])
        for s in membri_g[1:]:
            comuni &= set(storico[s])
        valide = []
        for d in comuni:
            squadre_d = {storico[s][d][1] for s in membri_g}
            avversari_d = {storico[s][d][2] for s in membri_g}
            # tutti nella stessa sfida: le squadre coinvolte sono al massimo 2
            # e ognuno ha come avversario una di quelle
            if len(squadre_d | avversari_d) <= 2:
                valide.append(d)
        if valide:
            date_gruppo[chiave] = sorted(valide)

    cap = formazione['capitano']
    tutti_punteggi = {s: [v[0] for v in storico[s].values()] for s in membri}
    totali = []
    for _ in range(n_trials):
        tot = 0.0
        for chiave, membri_g in gruppi.items():
            date = date_gruppo.get(chiave)
            if date and len(membri_g) >= 2:
                d = random.choice(date)
                for s in membri_g:
                    v = storico[s][d][0]
                    tot += v * (1 + CAPTAIN_BONUS) if s == cap else v
            else:
                for s in membri_g:
                    v = random.choice(tutti_punteggi[s])
                    tot += v * (1 + CAPTAIN_BONUS) if s == cap else v
        for s in sciolti:
            v = random.choice(tutti_punteggi[s])
            tot += v * (1 + CAPTAIN_BONUS) if s == cap else v
        totali.append(tot)
    return totali


def main():
    tipi = [t.strip() for t in os.environ.get(
        'TIPI', 'MLS_IN_SEASON,KLEAGUE_IN_SEASON').split(',') if t.strip()]
    print("Carico lo storico (con avversario per partita)...")
    storico = carica_storico()
    print(f"Giocatori con storico utilizzabile: {len(storico)}\n")

    for tipo in tipi:
        print("=" * 78)
        print(tipo)
        print("=" * 78)
        risultati = {}
        for attiva in (True, False):
            et = 'penalita ATTIVA (dopo il fix)' if attiva else 'penalita INERTE (prima)'
            forms = genera(tipo, attiva)
            if not forms:
                print(f"  {et}: nessuna formazione generata."); risultati = {}; break
            risultati[attiva] = forms
            print(f"  {et}: {len(forms)} formazioni, atteso medio "
                  f"{statistics.mean(f['atteso'] for f in forms):.1f} pt")
        if not risultati:
            continue

        attesi = [f['atteso'] for lst in risultati.values() for f in lst]
        centro = statistics.median(attesi)
        soglie = [round((centro + d) / 10) * 10 for d in (0, 20, 40, 60, 80)]

        print(f"\n  {'soglia':>8}{'P(>soglia) ATTIVA':>20}{'P(>soglia) INERTE':>20}{'differenza':>14}")
        simulabili = {}
        for soglia in soglie:
            probs = {}
            for attiva in (True, False):
                sim = [t for t in (simula(f, storico, N_TRIALS) for f in risultati[attiva]) if t]
                simulabili[attiva] = len(sim)
                if not sim:
                    probs[attiva] = None
                    continue
                p_nessuna = 1.0
                for tot in sim:
                    p_nessuna *= 1.0 - sum(1 for x in tot if x > soglia) / len(tot)
                probs[attiva] = 1.0 - p_nessuna
            if probs[True] is None or probs[False] is None:
                print(f"  {soglia:>8}{'n/d':>20}{'n/d':>20}")
                continue
            diff = (probs[True] - probs[False]) * 100
            print(f"  {soglia:>8}{probs[True]*100:>19.2f}%{probs[False]*100:>19.2f}%{diff:>+13.2f} pp")
        print(f"  (formazioni simulabili: attiva={simulabili.get(True)}, inerte={simulabili.get(False)})\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
