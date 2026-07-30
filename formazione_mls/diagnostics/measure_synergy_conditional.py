"""
Synergy Conditional Splits + Momentum (30/07) -- ulteriori test proposti
dall'utente dopo la sessione di ricalibrazione, mai fatti prima:

4. La sinergia same-team cambia per casa/trasferta?
5. La sinergia same-team e' stabile tra le leghe (MLS/K League/Germania) o
   varia molto?
6. "Momentum di squadra": una buona partita di un giocatore alla giornata N
   predice quella di un COMPAGNO alla giornata N+1 (non nella stessa
   partita)? Effetto diverso dalla sinergia istantanea gia' misurata.

Riusa la stessa logica di residuo di measure_teammate_correlation.py (media
pesata*fattore_ct*fattore_trend), nessuna nuova query API.

Uso: python formazione_mls/diagnostics/measure_synergy_conditional.py
"""
import os
import sys
import glob
import json
import statistics
import importlib
import datetime
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
ROLES = ('gk', 'def', 'mid', 'fwd')
MIN_PAIRS = 30


def _discover_leagues():
    found = {}
    for gk_dir in sorted(glob.glob(os.path.join('formazione_*', 'output', '*_gk_all'))):
        champ_dir = os.path.basename(os.path.dirname(os.path.dirname(gk_dir)))
        league = champ_dir[len('formazione_'):]
        found[league] = (f'formazione_{league}.predict.test_{{ruolo}}',
                          f'formazione_{league}/output/{league}_{{ruolo}}_all/.cache')
    if 'mls' in found:
        found['mls'] = ('formazione_mls.predict.test_{ruolo}',
                         'formazione_mls/output/mls_{ruolo}_calibration/.cache')
    if 'kleague' in found:
        found['kleague'] = ('formazione_kleague.predict.test_{ruolo}',
                             'formazione_kleague/output/kleague_{ruolo}_calibration/.cache')
    return found


LEAGUES = _discover_leagues()


def _module_and_cache(league, ruolo):
    mod_tpl, cache_tpl = LEAGUES[league]
    if ruolo == 'fwd':
        prefix = mod_tpl.rsplit('.', 1)[0]
        mod_name = f"{prefix}.test_mls_fwd_all"
    else:
        mod_name = mod_tpl.format(ruolo=ruolo)
    return mod_name, cache_tpl.format(ruolo=ruolo)


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def collect_residuals_for_role(ruolo):
    """Ritorna lista di dict con team, opponent, data, player, residuo,
    is_home, league, game_index (indice cronologico del giocatore nella sua
    carriera cachata, per il calcolo del momentum N->N+1)."""
    out = []
    for league in LEAGUES:
        mod_name, cache_dir = _module_and_cache(league, ruolo)
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        exponential_weights = mod.exponential_weights
        weighted_mean = mod.weighted_mean
        compute_split_factor = mod.compute_split_factor
        compute_trend_factor = mod.compute_trend_factor
        HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
        TREND_INTENSITY = mod.TREND_INTENSITY

        files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
        for fpath in files:
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
            if not cache:
                continue
            entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
            entries.sort(key=lambda e: e['anyGame'].get('date') or '')
            if len(entries) < MIN_HISTORY + 3:
                continue
            games = [e['anyGame'] for e in entries]
            team_slug_raw = player_team_slug(games)
            if not team_slug_raw:
                continue
            team_slug = f"{league}:{team_slug_raw}"
            player_id = os.path.basename(fpath).replace('_detail_cache.json', '')

            scores, is_home_flags, dates = [], [], []
            for e in entries:
                g = e['anyGame']
                home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                if home.get('slug') == team_slug_raw:
                    is_home = True
                elif away.get('slug') == team_slug_raw:
                    is_home = False
                else:
                    continue
                scores.append(e.get('score') or 0.0)
                is_home_flags.append(is_home)
                dates.append(parse_date(g))

            n = len(scores)
            if n < MIN_HISTORY + 3:
                continue

            for i in range(MIN_HISTORY, n):
                if dates[i] is None:
                    continue
                hist_scores = scores[:i]
                hist_home = is_home_flags[:i]
                weights = exponential_weights(i, HALF_LIFE_GAMES)
                media = weighted_mean(hist_scores, weights)
                fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
                fattore_trend, _, _ = compute_trend_factor(
                    hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)
                baseline = media * fattore_ct * fattore_trend
                residuo = scores[i] - baseline
                out.append({
                    'team': team_slug, 'date': dates[i].date().isoformat(),
                    'player': f"{ruolo}:{league}:{player_id}", 'residuo': residuo,
                    'is_home': is_home_flags[i], 'league': league, 'game_index': i,
                })
    return out


def build_same_team_pairs(records, filter_fn=None):
    groups = defaultdict(list)
    for r in records:
        if filter_fn and not filter_fn(r):
            continue
        groups[(r['team'], r['date'])].append(r)
    pairs = []
    for (team, date), rows in groups.items():
        if len(rows) < 2:
            continue
        for a, b in combinations(rows, 2):
            pairs.append((a['residuo'], b['residuo']))
    return pairs


def report(label, pairs):
    if len(pairs) < MIN_PAIRS:
        print(f"  {label:<30} n insufficiente ({len(pairs)})")
        return
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    r = pearson(xs, ys)
    rs = f"{r:+.3f}" if r is not None else "n/d"
    print(f"  {label:<30} n={len(pairs):>6}  corr={rs}")


def main():
    print("Raccolta residui (con is_home/league/game_index)...")
    all_records = []
    by_role = {}
    for ruolo in ROLES:
        recs = collect_residuals_for_role(ruolo)
        by_role[ruolo] = recs
        all_records.extend(recs)
        print(f"  {ruolo.upper()}: {len(recs)} punti")

    print("\n=== TEST 4: sinergia same-team, CASA vs TRASFERTA ===")
    home_pairs = build_same_team_pairs(all_records, lambda r: r['is_home'])
    away_pairs = build_same_team_pairs(all_records, lambda r: not r['is_home'])
    report("qualsiasi coppia, IN CASA", home_pairs)
    report("qualsiasi coppia, IN TRASFERTA", away_pairs)

    print("\n=== TEST 5: sinergia same-team, PER LEGA (solo le 3 leghe con calibrazione completa) ===")
    for league in ('mls', 'kleague', 'germania'):
        pairs = build_same_team_pairs(all_records, lambda r, lg=league: r['league'] == lg)
        report(f"qualsiasi coppia, {league}", pairs)

    print("\n=== TEST 6: MOMENTUM -- buona partita di A alla giornata N predice quella di un")
    print("    compagno B alla giornata N+1 (partita SUCCESSIVA, non la stessa)? ===")
    # index per team+player: lista ordinata di (date, residuo, game_index)
    by_team = defaultdict(lambda: defaultdict(list))
    for r in all_records:
        by_team[r['team']][r['player']].append((r['date'], r['residuo']))
    for team, players in by_team.items():
        for p in players:
            players[p].sort()

    lag_pairs = []
    for team, players in by_team.items():
        player_ids = list(players.keys())
        if len(player_ids) < 2:
            continue
        # per ogni coppia di giocatori della stessa squadra, allinea le partite di A
        # alla data N con quelle di B alla PRIMA data successiva > N (lag reale in
        # partite di squadra, non indice locale del singolo giocatore)
        all_dates_team = sorted({d for p in player_ids for d, _ in players[p]})
        next_date = {d: nd for d, nd in zip(all_dates_team, all_dates_team[1:])}
        for pa, pb in combinations(player_ids, 2):
            res_a_by_date = dict(players[pa])
            res_b_by_date = dict(players[pb])
            for d, res_a in players[pa]:
                nd = next_date.get(d)
                if nd is None:
                    continue
                res_b_next = res_b_by_date.get(nd)
                if res_b_next is not None:
                    lag_pairs.append((res_a, res_b_next))
    report("A(N) vs B(N+1), stessa squadra", lag_pairs)
    print("  (per confronto, la sinergia ISTANTANEA 'qualsiasi coppia' stessa partita e' ~+0.138")
    print("   da measure_teammate_correlation.py -- se il momentum e' vicino a 0, l'effetto e'")
    print("   davvero solo 'stessa partita', non una forma di squadra che dura nel tempo)")


if __name__ == '__main__':
    main()
