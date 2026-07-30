"""Test di non-regressione offline: compute_score_atteso_def vs formula inline di
build_prediction. La formula inline NON viene riscritta: viene ESTRATTA dal sorgente
di test_def.py (dal blocco level_score fino al += Stadio D) e eseguita con exec,
cosi' il confronto e' contro il codice di produzione letterale."""
import glob, json, os, re, sys, textwrap, random

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.path.join(REPO, 'formazione_mls', 'predict', 'test_def.py')
sys.path.insert(0, os.path.dirname(SRC))
os.environ.setdefault('SORARE_COOKIE', 'x')
import test_def as T

# --- estrazione del blocco inline di produzione ---
lines = open(SRC, encoding='utf-8').read().split('\n')
bp = next(i for i, l in enumerate(lines) if l.startswith('def build_prediction'))
start = next(i for i, l in enumerate(lines) if i > bp and l.strip().startswith('lambda_pos_dec = weighted_mean(pos_decisive_values'))
end = next(i for i, l in enumerate(lines) if '+ delta_clean_sheet_venue + delta_clean_sheet_avversario)' in l)
block = '\n'.join(l[4:] if l.startswith('    ') else l for l in lines[start:end + 1])
assert 'score_atteso = grezzo_nuovo_corretto' in block and 'score_atteso +=' in block
INLINE = compile(block, '<produzione-inline>', 'exec')


def arrays_from_cache(path):
    cache = json.load(open(path, encoding='utf-8'))
    nodes = [v for v in cache.values() if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
    nodes.sort(key=lambda v: v['anyGame'].get('date') or '')
    if len(nodes) < 8:
        return None
    counts = {}
    for v in nodes:
        for side in ('homeTeam', 'awayTeam'):
            s = (v['anyGame'].get(side) or {}).get('slug')
            if s:
                counts[s] = counts.get(s, 0) + 1
    team = max(counts, key=counts.get)
    d = {k: [] for k in ('scores is_home opp_rank fouls duels off pas defrare defact gc cs resid '
                         'lvl gran pos neg opp_slug game_dt').split()}
    for v in nodes:
        gs = v.get('score', 0.0)
        _own, opp, home = T.team_ranking_from_game(v['anyGame'], team)
        d['scores'].append(gs); d['is_home'].append(home); d['opp_rank'].append(opp)
        _g_home = v['anyGame'].get('homeTeam') or {}
        _g_away = v['anyGame'].get('awayTeam') or {}
        if _g_home.get('slug') == team:
            d['opp_slug'].append(_g_away.get('slug'))
        elif _g_away.get('slug') == team:
            d['opp_slug'].append(_g_home.get('slug'))
        else:
            d['opp_slug'].append(None)
        _dt_raw = v['anyGame'].get('date')
        d['game_dt'].append(
            __import__('datetime').datetime.fromisoformat(_dt_raw.replace('Z', '+00:00')).replace(tzinfo=None)
            if _dt_raw else None)
        fo = T.extract_group_score(v, T.FOULS_STATS)
        du = T.extract_group_score(v, T.DUELS_STATS)
        of = T.extract_group_score(v, T.OFFENSIVE_STATS)
        pa = T.extract_group_score(v, T.PASSING_STATS)
        dr = T.extract_group_score(v, T.DEFENSE_RARE_STATS)
        da = T.extract_group_score(v, T.DEFENSIVE_ACTIONS_STATS)
        gc = T.extract_group_score(v, T.GOALS_CONCEDED_STATS)
        cs = T.extract_group_score(v, T.CLEAN_SHEET_STATS)
        d['fouls'].append(fo); d['duels'].append(du); d['off'].append(of); d['pas'].append(pa)
        d['defrare'].append(max(-T.DEFENSE_RARE_CAP, min(T.DEFENSE_RARE_CAP, dr)))
        d['defact'].append(da)
        d['gc'].append(max(-T.GOALS_CONCEDED_CAP, min(T.GOALS_CONCEDED_CAP, gc)))
        d['cs'].append(cs)
        lv = T.extract_level_score(v)
        d['lvl'].append(lv); d['gran'].append(gs - lv)
        p, ng = T.extract_decisive_rates(v)
        d['pos'].append(p); d['neg'].append(ng)
        d['resid'].append(gs - (fo + du + of + pa + dr + da + gc + cs))
    return d


def run_case(d, next_is_home, next_opp_rank, p_gioca, next_opp_slug):
    n = len(d['scores'])
    weights = T.exponential_weights(n, T.HALF_LIFE_GAMES)
    _opp_lambda_mult = (T.opponent_strength.opponent_lambda_multiplier(
        'mls', 'def', next_opp_slug, __import__('datetime').datetime.utcnow())
        if next_opp_slug else 1.0)
    ns = dict(vars(T))
    ns.update(dict(
        n=n, weights=weights,
        scores=d['scores'], is_home_flags=d['is_home'], opponent_rankings=d['opp_rank'],
        residual_values=d['resid'], granulari_values=d['gran'],
        pos_decisive_values=d['pos'], neg_decisive_values=d['neg'],
        goals_conceded_values=d['gc'], passing_values=d['pas'], clean_sheet_values=d['cs'],
        media_granulari_pesata=T.weighted_mean(d['gran'], weights),
        fattore_casa_trasferta=T.compute_split_factor(d['resid'], d['is_home'], next_is_home),
        avg_opp_rank_hist=(sum(r for r in d['opp_rank'] if r is not None) /
                           len([r for r in d['opp_rank'] if r is not None]))
                          if any(r is not None for r in d['opp_rank']) else None,
        next_is_home=next_is_home, next_opp_rank=next_opp_rank, p_gioca=p_gioca,
        _opp_lambda_mult=_opp_lambda_mult, presence_rate=1.0,
        opponent_team_slugs_hist=d['opp_slug'], game_dates_hist=d['game_dt'],
        next_opponent_team_slug=next_opp_slug,
    ))
    exec(INLINE, ns)
    inline = ns['score_atteso']
    shared = T.compute_score_atteso_def(
        d['scores'], d['is_home'], d['opp_rank'], d['resid'], d['gran'],
        d['pos'], d['neg'], d['gc'], d['pas'], d['cs'],
        target_is_home=next_is_home, target_opp_rank=next_opp_rank, p_gioca=p_gioca,
        presence_rate=1.0,
        opponent_team_slugs_hist=d['opp_slug'], game_dates_hist=d['game_dt'],
        next_opponent_team_slug=next_opp_slug, league='mls')
    return inline, shared


def main():
    files = sorted(glob.glob(os.path.join(
        REPO, 'formazione_*', 'output', '*_def_all', '.cache', '*_detail_cache.json')))
    worst = 0.0
    n_cases = n_players = 0
    fails = []
    for f in files:
        d = arrays_from_cache(f)
        if not d:
            continue
        n_players += 1
        ranks = [r for r in d['opp_rank'] if r is not None] or [None]
        slugs = [s for s in d['opp_slug'] if s] or [None]
        # next_opp_slug SEMPRE reale (slugs[0]): la produzione (build_prediction)
        # ha SEMPRE lo slug dell'avversario, non esiste un caso None -- testare
        # None confronterebbe l'inline (che chiama opponent_is_strong sempre) con
        # un fallback della funzione condivisa mai usato in produzione.
        for nh in (True, False, None):
            for nr in (ranks[0], max(ranks) if ranks[0] is not None else None, None):
                for pg in (1.0, 0.83):
                    try:
                        a, b = run_case(d, nh, nr, pg, slugs[0])
                    except Exception as e:
                        fails.append((f, repr(e)))
                        continue
                    n_cases += 1
                    diff = abs(a - b)
                    worst = max(worst, diff)
                    if diff > 1e-9:
                        fails.append((os.path.basename(f), nh, nr, pg, a, b, diff))

    print(f"giocatori: {n_players}  casi: {n_cases}  diff massima: {worst:.3e}")
    if fails:
        print("FALLIMENTI:", len(fails))
        for x in fails[:10]:
            print("  ", x)
    else:
        print("IDENTICO: nessuna divergenza sopra 1e-9")


if __name__ == '__main__':
    main()
