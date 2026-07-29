import os, sys, glob, json, statistics
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.getcwd())
sys.path.insert(0, 'formazione_mls/diagnostics')
import measure_range_reliability as R

MIN_HISTORY = 7


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


def collect(ruolo, field):
    """residuo walk-forward = valore_reale - media_storica_semplice (no lookahead),
    per il campo granulare 'field' (es. 'du'=duelli, 'pa'=passaggio, 'of'=offensivo)."""
    out = []
    for league in sorted(R.LEAGUES):
        mod_name, cache_dir = R._module_name(league, ruolo)
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
            if not cache:
                continue
            entries = [v for v in cache.values() if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
            entries.sort(key=lambda v: v['anyGame'].get('date') or '')
            if len(entries) < MIN_HISTORY + 3:
                continue
            games = [e['anyGame'] for e in entries]
            team_slug = R.player_team_slug(games)
            if not team_slug:
                continue
            a = R.build_common(mod, entries, team_slug, ruolo)
            vals = a.get(field)
            n = len(vals)
            if n < MIN_HISTORY + 3:
                continue
            slug = os.path.basename(fpath).replace('_detail_cache.json', '')
            for i in range(MIN_HISTORY, n):
                if a['dates'][i] is None:
                    continue
                hist = vals[:i]
                media = sum(hist) / len(hist)
                residuo = vals[i] - media
                date = a['dates'][i].date().isoformat()
                out.append((league, team_slug, date, f'{ruolo}:{slug}', residuo))
    return out


def build_pairs(records_a, records_b):
    """records_a/b: liste di (league, team, data, id, residuo). Coppie stessa squadra stessa data."""
    idx_b = defaultdict(list)
    for league, team, date, pid, res in records_b:
        idx_b[(league, team, date)].append((pid, res))
    pairs = []
    seen_teams = set()
    for league, team, date, pid, res in records_a:
        key = (league, team, date)
        for pid_b, res_b in idx_b.get(key, []):
            if pid_b == pid:
                continue
            pairs.append((res, res_b))
            seen_teams.add(team)
    return pairs, seen_teams


def main():
    combos = [('def', 'du', 'mid', 'du', 'Duelli DEF vs Duelli MID'),
              ('mid', 'pa', 'def', 'da', 'Passaggio MID vs Azioni_difensive DEF'),
              ('fwd', 'of', 'mid', 'pa', 'Offensivo FWD vs Passaggio MID'),
              ('def', 'gc', 'mid', 'of', 'Gol_subiti DEF vs Offensivo MID')]
    for role_a, field_a, role_b, field_b, label in combos:
        recs_a = collect(role_a, field_a)
        recs_b = collect(role_b, field_b) if not (role_a == role_b and field_a == field_b) else recs_a
        pairs, teams = build_pairs(recs_a, recs_b)
        if len(pairs) < 30:
            print(f'{label:<45} n insufficiente ({len(pairs)})')
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r = pearson(xs, ys)
        rs = f'{r:+.3f}' if r is not None else 'n/d'
        print(f'{label:<45} n={len(pairs):>6}  squadre={len(teams):>3}  corr={rs}')


if __name__ == '__main__':
    main()
