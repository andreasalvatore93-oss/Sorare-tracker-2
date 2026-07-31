"""AUDIT (31/07): quanto conta, in MAE reale, la divergenza fra la formula
che il BACKTEST di calibrazione misura e quella che la PRODUZIONE usa
davvero, per il portiere.

Divergenze trovate leggendo il codice (rigorous_backtest_prod_gk vs
build_prediction in test_gk.py):
  1. il backtest NON passa `opponent_lambda_mult` -> usa 1.0, mentre la
     produzione applica opponent_strength.opponent_lambda_multiplier
     (sensibilita' GK 0.7, segno -1) moltiplicato per
     gk_def_pen_area_multiplier. Per DEF e FWD questa stessa divergenza e'
     stata corretta il 30/07; GK e MID sono rimasti indietro.
  2. il backtest NON passa `presence_rate` -> usa il prior FISSO (48.81),
     mentre la produzione usa il prior dinamico (46.20 + 4.05*presence).

Se la produzione e' MIGLIORE del backtest, la calibrazione ha semplicemente
sottostimato il modello. Se e' PEGGIORE, tutti i parametri scelti con quel
backtest (half_life, trend, range, shrink) sono tarati su una formula che
non e' quella che gira, ed e' un problema serio.

Chiama la funzione condivisa REALE (gk.compute_score_atteso_gk), non una
reimplementazione, cosi' il confronto non puo' divergere per errore mio.

Uso: python formazione_mls/diagnostics/audit_backtest_vs_produzione_gk.py
"""
import os
import sys
import glob
import json
import datetime
import statistics
import importlib.util
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import opponent_strength  # noqa: E402


def _imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gk = _imp('test_gk_lib', 'formazione_mls/predict/test_gk.py')

MIN_HISTORY = 6


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def team_of(games):
    c = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            s = (g.get(side) or {}).get('slug')
            if s:
                c[s] += 1
    return max(c, key=c.get) if c else None


def presence_rate_for(cache_dir, slug):
    """Stessa definizione della produzione: quota di partite NON
    DID_NOT_PLAY sul totale in .game_log_cache."""
    p = os.path.join(os.path.dirname(cache_dir), '.game_log_cache', f'{slug}_gamelog.json')
    if not os.path.isfile(p):
        return None
    try:
        log = json.load(open(p, encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None
    st = [v.get('scoreStatus') for v in log.values() if isinstance(v, dict)]
    if len(st) < 8:
        return None
    return 1.0 - sum(1 for s in st if s == 'DID_NOT_PLAY') / len(st)


def load_players():
    out = []
    for pattern in ('formazione_*/output/*_gk_all/.cache', 'formazione_*/output/*_gk_calibration/.cache'):
        for cache_dir in glob.glob(pattern):
            lega = cache_dir.split('formazione_', 1)[1].split(os.sep)[0].split('/')[0]
            for f in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                slug = os.path.basename(f).replace('_detail_cache.json', '')
                try:
                    cache = json.load(open(f, encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    continue
                entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
                if len(entries) < MIN_HISTORY + 3:
                    continue
                team = team_of([e['anyGame'] for e in entries])
                if not team:
                    continue
                rows = []
                for e in entries:
                    g = e['anyGame']
                    home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                    if home.get('slug') == team:
                        is_home, opp = True, away.get('slug')
                    elif away.get('slug') == team:
                        is_home, opp = False, home.get('slug')
                    else:
                        continue
                    dt = parse_date(g)
                    if dt is None:
                        continue
                    pos = neg = 0.0
                    lvl = 0.0
                    for r in e['detailedScore']:
                        cat = r.get('category')
                        v = r.get('statValue') or 0.0
                        if cat == 'POSITIVE_DECISIVE_STAT':
                            pos += v
                        elif cat == 'NEGATIVE_DECISIVE_STAT':
                            neg += v
                        if r.get('stat') == 'level_score':
                            lvl = r.get('totalScore', 0.0) or 0.0
                    sc = e.get('score') or 0.0
                    rows.append(dict(dt=dt, is_home=is_home, opp=opp, pos=pos, neg=neg,
                                     gran=sc - lvl, score=sc))
                rows.sort(key=lambda r: r['dt'])
                if len(rows) < MIN_HISTORY + 3:
                    continue
                out.append((lega, slug, rows, presence_rate_for(cache_dir, slug)))
    return out


def main():
    players = load_players()
    print(f"Portieri utilizzabili: {len(players)}  "
          f"(con presence_rate noto: {sum(1 for p in players if p[3] is not None)})\n")

    err = {k: [] for k in ('backtest', '+opponent', '+presence', 'produzione')}
    for lega, slug, rows, pr in players:
        n = len(rows)
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            args = dict(
                scores=[r['score'] for r in hist],
                is_home_flags=[r['is_home'] for r in hist],
                granulari_values=[r['gran'] for r in hist],
                pos_decisive_values=[r['pos'] for r in hist],
                neg_decisive_values=[r['neg'] for r in hist],
                target_is_home=rows[i]['is_home'],
            )
            mult = opponent_strength.opponent_lambda_multiplier(lega, 'gk', rows[i]['opp'], rows[i]['dt'])
            mult *= opponent_strength.gk_def_pen_area_multiplier(lega, rows[i]['opp'], rows[i]['dt'])
            reale = rows[i]['score']
            varianti = {
                'backtest':   dict(),
                '+opponent':  dict(opponent_lambda_mult=mult),
                '+presence':  dict(presence_rate=pr),
                'produzione': dict(opponent_lambda_mult=mult, presence_rate=pr),
            }
            for nome, extra in varianti.items():
                if 'presence_rate' in extra and extra['presence_rate'] is None:
                    extra = {k: v for k, v in extra.items() if k != 'presence_rate'}
                pred = gk.compute_score_atteso_gk(**args, **extra)
                err[nome].append(abs(reale - pred))

    print(f"{'variante':<14} {'MAE':>8} {'vs backtest':>14}   descrizione")
    base = statistics.mean(err['backtest'])
    desc = {
        'backtest': "cio' che la calibrazione misura oggi",
        '+opponent': "aggiunge SOLO l'aggiustamento avversario (come DEF/FWD dal 30/07)",
        '+presence': "aggiunge SOLO il prior dinamico",
        'produzione': "la formula che gira DAVVERO in produzione",
    }
    for nome in ('backtest', '+opponent', '+presence', 'produzione'):
        m = statistics.mean(err[nome])
        pct = (m - base) / base * 100
        print(f"{nome:<14} {m:>8.3f} {pct:>+13.2f}%   {desc[nome]}")
    print(f"\nPunti di test: {len(err['backtest'])}")


if __name__ == '__main__':
    main()
