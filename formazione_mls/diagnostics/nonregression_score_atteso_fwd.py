"""Test di non-regressione offline per FWD (gemello della versione DEF).

Confronta compute_score_atteso_fwd con la formula inline di build_prediction:
la formula inline NON viene riscritta, viene ESTRATTA dal sorgente di
test_mls_fwd_all.py (dal blocco level_score fino al += Stadio D "Passaggio") ed
eseguita con exec, cosi' il confronto e' contro il codice di produzione letterale.
"""
import glob
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.path.join(REPO, 'formazione_mls', 'predict', 'test_mls_fwd_all.py')
sys.path.insert(0, os.path.dirname(SRC))
os.environ.setdefault('SORARE_COOKIE', 'x')
import test_mls_fwd_all as T

_lines = open(SRC, encoding='utf-8').read().split('\n')
_bp = next(i for i, l in enumerate(_lines) if l.startswith('def build_prediction'))
_start = next(i for i, l in enumerate(_lines)
              if i > _bp and l.strip().startswith('lambda_pos_dec = weighted_mean(pos_decisive_values'))
_end = next(i for i, l in enumerate(_lines)
            if i > _start and l.strip() == 'score_atteso += delta_passaggio_venue')
_block = '\n'.join(l[4:] if l.startswith('    ') else l for l in _lines[_start:_end + 1])
assert 'score_atteso = grezzo_nuovo_corretto' in _block and 'score_atteso +=' in _block
INLINE = compile(_block, '<produzione-inline-fwd>', 'exec')


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
    d = {k: [] for k in 'scores is_home pas resid gran pos neg opp_slug off'.split()}
    for v in nodes:
        gs = v.get('score', 0.0)
        _own, _opp, home = T.team_ranking_from_game(v['anyGame'], team)
        d['scores'].append(gs)
        d['is_home'].append(home)
        _g_home = v['anyGame'].get('homeTeam') or {}
        _g_away = v['anyGame'].get('awayTeam') or {}
        if _g_home.get('slug') == team:
            d['opp_slug'].append(_g_away.get('slug'))
        elif _g_away.get('slug') == team:
            d['opp_slug'].append(_g_home.get('slug'))
        else:
            d['opp_slug'].append(None)
        fo = T.extract_group_score(v, T.FOULS_STATS)
        du = T.extract_group_score(v, T.DUELS_STATS)
        of = T.extract_group_score(v, T.OFFENSIVE_STATS)
        pa = T.extract_group_score(v, T.PASSING_STATS)
        dr = T.extract_group_score(v, T.DEFENSE_RARE_STATS)
        d['pas'].append(pa)
        d['off'].append(of)
        lv = T.extract_level_score(v)
        d['gran'].append(gs - lv)
        p, ng = T.extract_decisive_rates(v)
        d['pos'].append(p)
        d['neg'].append(ng)
        d['resid'].append(gs - (fo + du + of + pa + dr))
    return d


def run_case(d, next_is_home, p_gioca, next_opp_slug):
    n = len(d['scores'])
    weights = T.exponential_weights(n, T.HALF_LIFE_GAMES)
    _opp_lambda_mult = (T.opponent_strength.opponent_lambda_multiplier(
        'mls', 'fwd', next_opp_slug, __import__('datetime').datetime.utcnow())
        if next_opp_slug else 1.0)
    ns = dict(vars(T))
    ns.update(dict(
        n=n, weights=weights,
        scores=d['scores'], is_home_flags=d['is_home'],
        residual_values=d['resid'], granulari_values=d['gran'],
        pos_decisive_values=d['pos'], neg_decisive_values=d['neg'],
        passing_values=d['pas'],
        media_granulari_pesata=T.weighted_mean(d['gran'], weights),
        fattore_casa_trasferta=T.compute_split_factor(d['resid'], d['is_home'], next_is_home),
        next_is_home=next_is_home, p_gioca=p_gioca,
        _opp_lambda_mult=_opp_lambda_mult, presence_rate=1.0,
        offensive_values=d['off'], next_opponent_team_slug=next_opp_slug,
    ))
    exec(INLINE, ns)
    inline = ns['score_atteso']
    shared = T.compute_score_atteso_fwd(
        d['scores'], d['is_home'], d['resid'], d['gran'],
        d['pos'], d['neg'], d['pas'],
        target_is_home=next_is_home, p_gioca=p_gioca,
        next_opponent_team_slug=next_opp_slug, league='mls',
        presence_rate=1.0, offensive_values=d['off'])
    return inline, shared


def main():
    files = sorted(glob.glob(os.path.join(
        REPO, 'formazione_*', 'output', '*_fwd_all', '.cache', '*_detail_cache.json')))
    worst = 0.0
    n_cases = n_players = 0
    fails = []
    for f in files:
        d = arrays_from_cache(f)
        if not d:
            continue
        n_players += 1
        slugs = [s for s in d['opp_slug'] if s] or [None]
        for nh in (True, False, None):
            for pg in (1.0, 0.83):
                try:
                    a, b = run_case(d, nh, pg, slugs[0])
                except Exception as e:
                    fails.append((f, repr(e)))
                    continue
                n_cases += 1
                diff = abs(a - b)
                worst = max(worst, diff)
                if diff > 1e-9:
                    fails.append((os.path.basename(f), nh, pg, a, b, diff))

    print(f"giocatori: {n_players}  casi: {n_cases}  diff massima: {worst:.3e}")
    if fails:
        print("FALLIMENTI:", len(fails))
        for x in fails[:10]:
            print("  ", x)
    else:
        print("IDENTICO: nessuna divergenza sopra 1e-9")


if __name__ == '__main__':
    main()
