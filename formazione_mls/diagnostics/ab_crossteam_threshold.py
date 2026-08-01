"""Misura la SCALA della penalita' cross-team con la metrica giusta: la
probabilita' di superare una soglia, non il punteggio atteso.

PERCHE' (backlog aperto dal 31/07, sez. 43.D del riassunto). La tabella
CROSS_TEAM_PENALTY_BY_PAIR nasce come "correlazione misurata x 20". Le
correlazioni sono state rimisurate piu' volte su campioni grandi e sono un
dato solido; il moltiplicatore 20 che le trasforma in punti, invece, non e'
mai stato validato -- e' lo stesso "a occhio" che per la sinergia same-team
si e' rivelato sbagliato (x20 -> x12, sez. 42.A).

METODO (identico a ab_arena_synergy_threshold.py, per non introdurre
differenze dovute allo strumento):
 1. si generano le formazioni riscalando la tabella di k/20, con k che varia
    (0 = penalita' spenta, 20 = produzione di oggi);
 2. per ogni formazione si fa Monte Carlo sul totale campionando punteggi
    REALI storici degli schierati;
 3. la dipendenza fra i punteggi e' preservata per COSTRUZIONE: qui non
    bastano i compagni di squadra: la penalita' cross-team esiste proprio per
    gli AVVERSARI nella stessa partita, quindi il campionamento raggruppa i
    giocatori per PARTITA (le due squadre che si sono affrontate in una data
    reale), non per squadra. E' l'unica differenza rispetto allo studio sulla
    sinergia, ed e' obbligatoria: campionando per squadra la correlazione
    negativa fra avversari andrebbe persa e il test misurerebbe zero per
    costruzione.
 4. si confronta P(almeno una formazione > soglia) fra le scale.

Uso:
  python formazione_mls/diagnostics/ab_crossteam_threshold.py
  SCALE=0,10,20,30 TIPI=ARENA_ALLSTARS_260 python .../ab_crossteam_threshold.py
"""
import os
import sys
import glob
import json
import random
import importlib
import statistics
from collections import defaultdict

os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '0')
os.environ.setdefault('ARENA_ALLSTARS_220', '0')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '0')
os.environ.setdefault('ALLSTARS', '0')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('IN_SEASON', '')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

N_TRIALS = int(os.environ.get('N_TRIALS', '100000'))
QUANTE = int(os.environ.get('QUANTE', '6'))
SCALE = [float(x) for x in os.environ.get('SCALE', '0,10,20,30,40').split(',')]
TIPI_DEFAULT = 'ARENA_ALLSTARS_260,ALLSTARS'
CAPTAIN_BONUS_BY_TIPO = {'ALLSTARS': 0.5, 'ALLSTARS_U23': 0.5}  # Arena: +20%
random.seed(20260801)


# ---------------------------------------------------------------- storico
def carica_storico():
    """slug -> (team, {data: score}, {data: avversario}).

    Rispetto a ab_inseason_synergy_threshold.carica_storico() serve in piu'
    l'AVVERSARIO per data: e' quello che permette di ricostruire le partite e
    campionare insieme giocatori di squadre opposte."""
    storico = {}
    for pattern in ('formazione_*/output/*_gk_all/.cache',
                    'formazione_*/output/*_def_all/.cache',
                    'formazione_*/output/*_mid_all/.cache',
                    'formazione_*/output/*_fwd_all/.cache'):
        for cache_dir in glob.glob(pattern):
            for f in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                slug = os.path.basename(f).replace('_detail_cache.json', '')
                if slug in storico:
                    continue
                try:
                    cache = json.load(open(f, encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    continue
                nodi = [v for v in cache.values()
                        if v.get('anyGame') and v.get('score') is not None]
                if len(nodi) < 6:
                    continue
                conteggi = defaultdict(int)
                for v in nodi:
                    for lato in ('homeTeam', 'awayTeam'):
                        s = (v['anyGame'].get(lato) or {}).get('slug')
                        if s:
                            conteggi[s] += 1
                if not conteggi:
                    continue
                team = max(conteggi, key=conteggi.get)
                per_data, avversario = {}, {}
                for v in nodi:
                    g = v['anyGame']
                    d = (g.get('date') or '')[:10]
                    if not d:
                        continue
                    home = (g.get('homeTeam') or {}).get('slug')
                    away = (g.get('awayTeam') or {}).get('slug')
                    if home == team:
                        opp = away
                    elif away == team:
                        opp = home
                    else:
                        continue
                    per_data[d] = v['score']
                    avversario[d] = opp
                if len(per_data) >= 6:
                    storico[slug] = (team, per_data, avversario)
    return storico


# ------------------------------------------------------------- generazione
def genera(tipo, scala, originale):
    """Genera le formazioni con la tabella cross-team riscalata di scala/20.

    scala=20 e' la produzione di oggi (nessuna modifica), scala=0 spegne la
    penalita'. Tutto il resto della configurazione resta intatto: l'unica
    differenza fra i rami e' il peso della tabella."""
    for var in ('ARENA_ALLSTARS_260', 'ALLSTARS', 'ARENA_ALLSTARS_220', 'ALLSTARS_U23'):
        os.environ[var] = '0'
    os.environ[tipo] = str(QUANTE)

    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff
    bff.CROSS_TEAM_PENALTY_BY_PAIR = {k: v * scala / 20.0 for k, v in originale.items()}

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


# ------------------------------------------------------------- monte carlo
def gruppi_per_partita(membri, storico):
    """Raggruppa gli schierati in blocchi campionabili insieme.

    Un blocco e' una PARTITA reale: due squadre che si sono affrontate in una
    o piu' date in cui tutti i giocatori del blocco hanno un punteggio. I
    compagni di squadra finiscono nello stesso blocco (correlazione positiva),
    e cosi' gli avversari (correlazione negativa) -- che e' il motivo per cui
    esiste questo test.

    Ritorna [(lista_slug, lista_date_comuni_o_None), ...]."""
    per_team = defaultdict(list)
    for s in membri:
        per_team[storico[s][0]].append(s)

    def date_comuni(gruppo, vincolo_avversario=None):
        comuni = None
        for s in gruppo:
            _t, per_data, avv = storico[s]
            date = set(per_data)
            if vincolo_avversario is not None:
                date = {d for d in date if avv.get(d) in vincolo_avversario}
            comuni = date if comuni is None else (comuni & date)
        return sorted(comuni or [])

    teams = list(per_team)
    usate = set()
    blocchi = []
    # prima le coppie di squadre AVVERSARIE fra loro (il caso che conta)
    for i, a in enumerate(teams):
        if a in usate:
            continue
        for b in teams[i + 1:]:
            if b in usate:
                continue
            gruppo = per_team[a] + per_team[b]
            date_a = date_comuni(per_team[a], {b})
            date_b = date_comuni(per_team[b], {a})
            comuni = sorted(set(date_a) & set(date_b))
            if comuni:
                blocchi.append((gruppo, comuni))
                usate.add(a)
                usate.add(b)
                break
    for t in teams:
        if t in usate:
            continue
        gruppo = per_team[t]
        comuni = date_comuni(gruppo) if len(gruppo) >= 2 else []
        blocchi.append((gruppo, comuni or None))
    return blocchi


def simula(formazione, storico, captain_bonus, n_trials=N_TRIALS):
    membri = [s for s in formazione['slugs'] if s in storico]
    if len(membri) < len(formazione['slugs']):
        return None
    blocchi = gruppi_per_partita(membri, storico)
    cap = formazione['capitano']
    totali = []
    for _ in range(n_trials):
        tot = 0.0
        for gruppo, date in blocchi:
            if date:
                d = random.choice(date)
                for s in gruppo:
                    v = storico[s][1][d]
                    tot += v * (1 + captain_bonus) if s == cap else v
            else:
                for s in gruppo:
                    v = random.choice(list(storico[s][1].values()))
                    tot += v * (1 + captain_bonus) if s == cap else v
        totali.append(tot)
    return totali


def soglie_da(tutte):
    fisse = os.environ.get('SOGLIE', '').strip()
    if fisse:
        return [float(x) for x in fisse.split(',')]
    attesi = [f['atteso'] for lista in tutte for f in lista]
    if not attesi:
        return []
    centro = statistics.median(attesi)
    scarti = [float(x) for x in os.environ.get(
        'SOGLIE_OFFSET', '-40,-20,0,20,40,60').split(',')]
    return [round((centro + d) / 10) * 10 for d in scarti]


def main():
    tipi = [t.strip() for t in os.environ.get('TIPI', TIPI_DEFAULT).split(',') if t.strip()]
    print("Carico lo storico dei punteggi reali dai detail cache...")
    storico = carica_storico()
    print(f"Giocatori con storico utilizzabile: {len(storico)}")

    sys.path.insert(0, os.path.join(os.getcwd(), 'formazione_mls'))
    import build_formazione_finale as bff_mod
    originale = dict(bff_mod.CROSS_TEAM_PENALTY_BY_PAIR)

    for tipo in tipi:
        print(f"\n{'=' * 78}\n{tipo}\n{'=' * 78}")
        cap_bonus = CAPTAIN_BONUS_BY_TIPO.get(tipo, 0.2)
        per_scala = {}
        for scala in SCALE:
            formazioni = genera(tipo, scala, originale)
            if not formazioni:
                print(f"  scala x{scala:g}: nessuna formazione generata, salto.")
                continue
            per_scala[scala] = formazioni
            print(f"  scala x{scala:g}: {len(formazioni)} formazioni, "
                  f"totale atteso medio {statistics.mean(f['atteso'] for f in formazioni):.1f} pt")
        if len(per_scala) < 2:
            continue

        soglie = soglie_da(list(per_scala.values()))
        # I totali Monte Carlo si calcolano UNA volta per scala e si riusano su
        # tutte le soglie: rifarli per ogni soglia costerebbe 6x senza aggiungere
        # informazione (e introdurrebbe rumore di campionamento fra le righe).
        totali_per_scala = {}
        simulabili = {}
        for scala, formazioni in per_scala.items():
            p = [t for t in (simula(f, storico, cap_bonus) for f in formazioni) if t]
            totali_per_scala[scala] = p
            simulabili[scala] = len(p)
        intestazione = ' '.join(f"{'x%g' % s:>9}" for s in per_scala)
        print(f"\n  {'soglia':>8} {intestazione}   (P che almeno una formazione superi la soglia)")
        for soglia in soglie:
            riga = []
            for scala in per_scala:
                p = totali_per_scala[scala]
                if not p:
                    riga.append('n/d')
                    continue
                p_nessuna = 1.0
                for tot in p:
                    p_nessuna *= (1.0 - sum(1 for t in tot if t > soglia) / len(tot))
                riga.append(f"{(1.0 - p_nessuna) * 100:.2f}%")
            print(f"  {soglia:>8} " + ' '.join(f"{v:>9}" for v in riga))
        if simulabili:
            print("  (formazioni simulabili per scala: "
                  + ', '.join(f"x{s:g}={n}" for s, n in simulabili.items()) + ")")
    return 0


if __name__ == '__main__':
    sys.exit(main())
