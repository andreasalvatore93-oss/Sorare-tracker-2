"""
Full Synergy Matrix (30/07) -- nuovi test proposti dall'utente dopo la
sessione di ricalibrazione: matrice COMPLETA di correlazione compagni di
squadra, non piu' solo le coppie scelte a intuito.

Copre in un solo giro:
1. Granulari cross-ruolo: OGNI sottocategoria granulare di un ruolo contro
   OGNI sottocategoria di ogni altro ruolo (non solo le 4 coppie testate il
   29/07 in measure_granular_subcategory_correlation.py).
2. Granulare-vs-punteggio-totale: una sottocategoria di un ruolo contro il
   punteggio TOTALE (residuo) di un compagno di un altro ruolo.
3. Eventi decisivi (level_score) tra compagni: i tassi pos/neg decisive
   (proxy diretto di "la squadra ha giocato bene insieme", diverso dal
   residuo generico gia' misurato in measure_teammate_correlation.py).

Riusa build_common() di measure_range_reliability.py (stesso pattern del
28-29/07), nessuna nuova query API -- solo le cache gia' su disco.

Uso: python formazione_mls/diagnostics/measure_full_synergy_matrix.py
"""
import os
import sys
import glob
import json
import random
import statistics
import importlib
from collections import defaultdict
from itertools import combinations, product

sys.path.insert(0, os.getcwd())
sys.path.insert(0, 'formazione_mls/diagnostics')
import measure_range_reliability as R

MIN_HISTORY = 7
MIN_PAIRS = 30
N_PERM = 199  # ridotto rispetto a 999: la matrice ha molte piu' celle, serve restare veloce

# campi disponibili per ruolo (coerente con build_common: GK non ha gli
# stats granulari, FOULS_STATS escluso ovunque -- gia' noto peso ~0)
FIELDS_BY_ROLE = {
    'gk':  ['gran', 'pos', 'neg'],
    'def': ['du', 'of', 'pa', 'dr', 'da', 'gc', 'cs', 'gran', 'pos', 'neg'],
    'mid': ['du', 'of', 'pa', 'dr', 'da', 'gc', 'gran', 'pos', 'neg'],
    'fwd': ['du', 'of', 'pa', 'dr', 'gran', 'pos', 'neg'],
}


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
    """Ritorna lista di (league, team, data, player_id, residuo_walk_forward)
    per il campo scelto. residuo = valore reale - media storica semplice
    (no lookahead)."""
    out = []
    for league in sorted(R.LEAGUES):
        mod_name, cache_dir = R._module_name(league, ruolo)
        try:
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
            if not vals:
                continue
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


def build_pairs(records_a, records_b, same_series):
    idx_b = defaultdict(list)
    for league, team, date, pid, res in records_b:
        idx_b[(league, team, date)].append((pid, res))
    pairs = []
    seen_teams = set()
    for league, team, date, pid, res in records_a:
        key = (league, team, date)
        for pid_b, res_b in idx_b.get(key, []):
            if same_series and pid_b == pid:
                continue
            pairs.append((res, res_b))
            seen_teams.add(team)
    return pairs, seen_teams


def permutation_pvalue(records_a, records_b, same_series, observed_r, n_perm=N_PERM, seed=42):
    rng = random.Random(seed)
    vals_a = [r[4] for r in records_a]
    count = 0
    for _ in range(n_perm):
        shuffled = vals_a[:]
        rng.shuffle(shuffled)
        perm_a = [(rec[0], rec[1], rec[2], rec[3], v) for rec, v in zip(records_a, shuffled)]
        pairs, _ = build_pairs(perm_a, records_b, same_series)
        if len(pairs) < 2:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r = pearson(xs, ys)
        if r is not None and abs(r) >= abs(observed_r):
            count += 1
    return (count + 1) / (n_perm + 1)


def main():
    print("Raccolta serie per (ruolo, campo)...")
    series = {}
    for ruolo, fields in FIELDS_BY_ROLE.items():
        for field in fields:
            key = (ruolo, field)
            series[key] = collect(ruolo, field)
            print(f"  {ruolo}:{field} -> {len(series[key])} punti")

    keys = list(series.keys())

    print("\n=== 1+2. Matrice completa granulari cross-ruolo + granulare-vs-totale ===")
    print("(same-team, stessa partita; 'gran'=granulare totale, 'pos'/'neg'=tassi eventi decisivi)")
    print(f"{'coppia':<28} {'n':>7} {'squadre':>8} {'corr':>8} {'p-value':>10}")

    rows = []
    for (ra, fa), (rb, fb) in combinations(keys, 2):
        if ra == rb and fa == fb:
            continue
        # evita duplicati simmetrici quando ra==rb (es. def:du vs def:pa già distinto da def:pa vs def:du)
        recs_a, recs_b = series[(ra, fa)], series[(rb, fb)]
        same_series = (ra == rb and fa == fb)
        pairs, teams = build_pairs(recs_a, recs_b, same_series)
        if len(pairs) < MIN_PAIRS:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r = pearson(xs, ys)
        if r is None:
            continue
        rows.append((ra, fa, rb, fb, len(pairs), len(teams), r, recs_a, recs_b, same_series))

    # ordina per |corr| decrescente, mostra solo le celle con segnale minimamente interessante
    rows.sort(key=lambda t: -abs(t[6]))
    shown = 0
    for ra, fa, rb, fb, n, nteams, r, recs_a, recs_b, same_series in rows:
        if abs(r) < 0.05:
            continue
        pval = permutation_pvalue(recs_a, recs_b, same_series, r)
        sig = " *" if pval < 0.05 else ""
        label = f"{ra}:{fa} vs {rb}:{fb}"
        print(f"{label:<28} {n:>7} {nteams:>8} {r:+.3f}{sig:<4} {pval:>8.4f}")
        shown += 1
    if shown == 0:
        print("Nessuna coppia con |corr| >= 0.05 e campione sufficiente.")
    print(f"\n({len(rows)} coppie totali con campione sufficiente, {shown} mostrate con |corr|>=0.05)")


if __name__ == '__main__':
    main()
