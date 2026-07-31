"""Test DECISIVO (31/07) sulla sinergia same-team per le In Season, con la
metrica GIUSTA: la probabilita' di superare la soglia premio, non il
punteggio atteso.

Perche' serve: ab_inseason_synergy_gate.py ha misurato il COSTO in punti
attesi (0-3 pt per lega, quasi nulla). Ma la sinergia same-team non nasce
per alzare il valore atteso -- nasce per alzare la CORRELAZIONE fra i
giocatori schierati, quindi la varianza del totale. Con un bersaglio FISSO
sopra la propria media, piu' varianza aumenta la probabilita' di superarlo
anche a media invariata. Il valore atteso e' quindi cieco proprio
all'effetto per cui quella tabella e' stata calibrata il 30/07.

Metodo (stesso impianto di estimate_threshold_win_probability_mc.py, ma
applicato alle formazioni REALI prodotte dal generatore, non a squadre
sintetiche):
 1. si generano le 6 In Season con la configurazione di OGGI (sinergie
    spente) e con la tabella IN_SEASON_SYNERGY_BONUS_BY_PAIR attiva;
 2. per ogni formazione si fa Monte Carlo sul totale campionando punteggi
    REALI storici dei giocatori effettivamente schierati;
 3. la correlazione e' preservata NON per ipotesi ma per costruzione: i
    compagni di squadra vengono campionati dalla STESSA partita reale
    quando esiste una data in cui hanno giocato entrambi, cosi' la
    dipendenza fra i loro punteggi e' quella vera osservata sul campo;
 4. si confronta P(totale > soglia) fra le due configurazioni, su piu'
    soglie realistiche.

Uso: python formazione_mls/diagnostics/ab_inseason_synergy_threshold.py
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
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

N_TRIALS = 100_000
CAPTAIN_BONUS = 0.5           # In Season
SOGLIE = [320, 340, 360, 380, 400, 420]
random.seed(20260731)


# ---------------------------------------------------------------- storico
def carica_storico():
    """slug -> (team, {data: score}) dai detail cache gia' su disco."""
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
                per_data = {}
                for v in nodi:
                    d = (v['anyGame'].get('date') or '')[:10]
                    if d:
                        per_data[d] = v['score']
                if len(per_data) >= 6:
                    storico[slug] = (team, per_data)
    return storico


# ------------------------------------------------------------- generazione
def genera(lega, tipo, usa_sinergia):
    os.environ['ONLY_LEAGUES'] = lega
    os.environ['IN_SEASON'] = f"mls:{6 if lega == 'mls' else 0},kleague:{6 if lega == 'kleague' else 0}"
    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff

    if usa_sinergia:
        originale = bff.synergy_sort_key

        def sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None,
                     apply_stack_guard=False, variance_mode=False, apply_positive_synergy=True,
                     used_matches=None, chosen_roles_by_team=None, synergy_bonus_dict=None):
            adjusted = row.get('sort_score', row['atteso'])
            team_slug = row.get('team_slug')
            if team_slug:
                adjusted += bff._same_team_synergy_bonus(
                    role, row, chosen_roles_by_team, bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR)
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
        del originale

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
    risultati = g.generate_lineups_for_type(tipo, 6, role_data, pools, card_pool)

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
def simula(formazione, storico, n_trials=N_TRIALS):
    """Campiona il totale reale della formazione. I compagni di squadra sono
    campionati dalla STESSA data quando disponibile: cosi' la correlazione
    fra loro e' quella osservata davvero, non una assunta."""
    membri = [s for s in formazione['slugs'] if s in storico]
    if len(membri) < len(formazione['slugs']):
        return None
    per_team = defaultdict(list)
    for s in membri:
        per_team[storico[s][0]].append(s)

    date_comuni = {}
    for team, gruppo in per_team.items():
        if len(gruppo) < 2:
            continue
        comuni = set(storico[gruppo[0]][1])
        for s in gruppo[1:]:
            comuni &= set(storico[s][1])
        if comuni:
            date_comuni[team] = sorted(comuni)

    cap = formazione['capitano']
    totali = []
    for _ in range(n_trials):
        tot = 0.0
        for team, gruppo in per_team.items():
            if team in date_comuni and len(gruppo) >= 2:
                d = random.choice(date_comuni[team])
                for s in gruppo:
                    v = storico[s][1][d]
                    tot += v * (1 + CAPTAIN_BONUS) if s == cap else v
            else:
                for s in gruppo:
                    v = random.choice(list(storico[s][1].values()))
                    tot += v * (1 + CAPTAIN_BONUS) if s == cap else v
        totali.append(tot)
    return totali


def main():
    print("Carico storico punteggi reali dai detail cache...")
    storico = carica_storico()
    print(f"Giocatori con storico utilizzabile: {len(storico)}\n")

    for lega, tipo, label in (('mls', 'MLS_IN_SEASON', 'In Season MLS'),
                               ('kleague', 'KLEAGUE_IN_SEASON', 'In Season K League')):
        print(f"\n{'=' * 82}\n{label}\n{'=' * 82}")
        conf = {}
        for nome, usa in (('oggi (spente)', False), ('sinergia 30/07', True)):
            formazioni = genera(lega, tipo, usa)
            sim = []
            for f in formazioni:
                t = simula(f, storico)
                if t is not None:
                    sim.append((f, t))
            conf[nome] = sim
            n_stack = sum(1 for f, _ in sim
                          if len({storico[s][0] for s in f['slugs'] if s in storico}) < len(f['slugs']))
            print(f"  {nome}: {len(sim)}/{len(formazioni)} formazioni simulabili, "
                  f"{n_stack} con almeno 2 compagni di squadra")

        if not all(conf.values()):
            print("  dati insufficienti per il confronto")
            continue

        print(f"\n  {'soglia':>7} " + "".join(f"{n:>22}" for n in conf) + "   delta")
        for soglia in SOGLIE:
            probs = {}
            for nome, sim in conf.items():
                # probabilita' che ALMENO UNA delle 6 formazioni superi la soglia
                # (e' cosi' che si gioca davvero: si schierano tutte)
                p_nessuna = 1.0
                for _f, totali in sim:
                    p = sum(1 for t in totali if t > soglia) / len(totali)
                    p_nessuna *= (1 - p)
                probs[nome] = 1 - p_nessuna
            valori = list(probs.values())
            delta = (valori[1] - valori[0]) * 100
            riga = "".join(f"{probs[n] * 100:>21.2f}%" for n in conf)
            print(f"  {soglia:>7} {riga}   {delta:+.2f} pt")

        for nome, sim in conf.items():
            medie = [statistics.mean(t) for _f, t in sim]
            sd = [statistics.pstdev(t) for _f, t in sim]
            print(f"  {nome}: media totale simulata {statistics.mean(medie):.1f}, "
                  f"dev.std media {statistics.mean(sd):.1f}")


if __name__ == '__main__':
    main()
