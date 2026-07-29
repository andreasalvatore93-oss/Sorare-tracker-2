"""Due test scelti dall'utente (29/07) sulla scia di measure_range_reliability.py
(che ha scartato il range storico come segnale di affidabilita'): stesso standard
di rigore, walk-forward dove possibile, nessuna query API.

TEST A -- "trend recente come rischio": un giocatore in fase calante/crescente
(scostamento fra media ultime 5 e ultime 10 partite) ha un errore di previsione
|reale-atteso| sistematicamente piu' alto della media? Oggi il trend aggiusta
solo il VALORE atteso (compute_trend_factor in test_def.py ecc.), mai la
varianza attesa -- qui si misura se dovrebbe.

TEST B -- "tasso di presenza come proxy di affidabilita'": il presence_rate
(gia' usato per lo shrinkage del prior, sez.31.D del RIASSUNTO, corr con la
MEDIA del punteggio) predice anche la CONSISTENZA (dev.std. dei punteggi
storici del giocatore) meglio del range scartato? Analisi cross-sezionale
per giocatore (stesso approccio di sez.31.D, non walk-forward partita per
partita: presence_rate e dev.std. sono entrambe statistiche aggregate sul
giocatore).

Uso: python formazione_mls/diagnostics/measure_trend_presence_reliability.py
"""
import os
import sys
import glob
import json
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import measure_range_reliability as R  # riusa discovery leghe + build_common + score_atteso_at

MIN_HISTORY = 7
LONG_WINDOW = 10


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


# ---------------------------------------------------------------------------
# TEST A: trend recente come rischio
# ---------------------------------------------------------------------------

def collect_trend_observations():
    out = []
    for league in sorted(R.LEAGUES):
        for ruolo in R.ROLES:
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
                entries = [v for v in cache.values()
                           if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
                entries.sort(key=lambda v: v['anyGame'].get('date') or '')
                if len(entries) < MIN_HISTORY + 3:
                    continue
                games = [e['anyGame'] for e in entries]
                team_slug = R.player_team_slug(games)
                if not team_slug:
                    continue
                a = R.build_common(mod, entries, team_slug, ruolo)
                n = len(a['scores'])
                if n < MIN_HISTORY + 3:
                    continue
                if ruolo == 'fwd':
                    resid = R.residual_fwd(a)
                elif ruolo in ('def', 'mid'):
                    resid = R.residual_def_mid(a, with_cs=(ruolo == 'def'))
                else:
                    resid = None

                for i in range(MIN_HISTORY, n):
                    if a['dates'][i] is None:
                        continue
                    if i < LONG_WINDOW:
                        continue
                    try:
                        score_atteso = R.score_atteso_at(mod, ruolo, a, resid, i)
                    except Exception:
                        continue
                    recent_short = a['scores'][i - 5:i]
                    recent_long = a['scores'][i - LONG_WINDOW:i]
                    avg_short = sum(recent_short) / len(recent_short)
                    avg_long = sum(recent_long) / len(recent_long)
                    if avg_long == 0:
                        continue
                    trend_raw = abs(avg_short / avg_long - 1.0)
                    reale = a['scores'][i]
                    out.append(dict(league=league, ruolo=ruolo,
                                     match_date=a['dates'][i].date().isoformat(),
                                     score_atteso=score_atteso, trend_raw=trend_raw,
                                     reale=reale))
    return out


def test_a():
    print("=" * 70)
    print("TEST A -- trend recente (|avg5/avg10 - 1|) come rischio")
    print("=" * 70)
    obs = collect_trend_observations()
    by_role = defaultdict(list)
    for o in obs:
        by_role[o['ruolo']].append(o)
    print(f"Totale osservazioni: {len(obs)}")
    for ruolo in R.ROLES:
        rows = by_role[ruolo]
        if len(rows) < 30:
            print(f"  {ruolo.upper()}: n insufficiente ({len(rows)})")
            continue
        xs = [r['trend_raw'] for r in rows]
        ys = [abs(r['reale'] - r['score_atteso']) for r in rows]
        r_all = pearson(xs, ys)
        rows_sorted = sorted(rows, key=lambda r: r['match_date'])
        mid = len(rows_sorted) // 2
        first, second = rows_sorted[:mid], rows_sorted[mid:]
        r1 = pearson([r['trend_raw'] for r in first], [abs(r['reale'] - r['score_atteso']) for r in first])
        r2 = pearson([r['trend_raw'] for r in second], [abs(r['reale'] - r['score_atteso']) for r in second])
        rs = f"{r_all:+.3f}" if r_all is not None else "n/d"
        r1s = f"{r1:+.3f}" if r1 is not None else "n/d"
        r2s = f"{r2:+.3f}" if r2 is not None else "n/d"
        # bucket alto/basso trend (mediana), confronto errore assoluto medio
        trends_sorted = sorted(xs)
        med = trends_sorted[len(trends_sorted) // 2]
        low_err = [abs(r['reale'] - r['score_atteso']) for r in rows if r['trend_raw'] <= med]
        high_err = [abs(r['reale'] - r['score_atteso']) for r in rows if r['trend_raw'] > med]
        print(f"  {ruolo.upper():<4} n={len(rows):>6}  corr(trend_raw, |err|)={rs}  "
              f"split-half: prima={r1s} (n={len(first)}) seconda={r2s} (n={len(second)})")
        print(f"        |err| medio -- trend basso: {statistics.mean(low_err):.2f}  "
              f"trend alto: {statistics.mean(high_err):.2f}  "
              f"diff: {statistics.mean(high_err) - statistics.mean(low_err):+.2f}")


# ---------------------------------------------------------------------------
# TEST B: presence_rate come proxy di affidabilita' (consistenza, non media)
# ---------------------------------------------------------------------------

def collect_presence_vs_consistency():
    """Per ogni giocatore con .game_log_cache E detail_cache disponibili:
    presence_rate = frazione di partite 'considerate' (non DID_NOT_PLAY) sul
    totale nella finestra .game_log_cache; dev_std_pesata = dev.std. (non pesata,
    per semplicita' -- coerente con l'obiettivo cross-sezionale) dei punteggi
    REALI in detail_cache (stessa fonte gia' usata per il range, sez. Q2)."""
    rows = []
    for league in sorted(R.LEAGUES):
        for ruolo in R.ROLES:
            mod_name, cache_dir = R._module_name(league, ruolo)
            # .game_log_cache vive sempre in .../<ruolo>_all|_calibration/.game_log_cache
            log_dir = os.path.join(os.path.dirname(cache_dir), '.game_log_cache')
            if not os.path.isdir(log_dir):
                continue
            for log_path in glob.glob(os.path.join(log_dir, '*_gamelog.json')):
                slug = os.path.basename(log_path).replace('_gamelog.json', '')
                detail_path = os.path.join(cache_dir, f'{slug}_detail_cache.json')
                if not os.path.isfile(detail_path):
                    continue
                try:
                    log_cache = json.load(open(log_path, encoding='utf-8'))
                    detail_cache = json.load(open(detail_path, encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    continue
                statuses = [v.get('scoreStatus') for v in log_cache.values() if isinstance(v, dict)]
                total = len(statuses)
                if total < 8:
                    continue
                dnp = sum(1 for s in statuses if s == 'DID_NOT_PLAY')
                presence_rate = 1.0 - (dnp / total)
                scores = [v.get('score') for v in detail_cache.values()
                          if isinstance(v, dict) and v.get('scoreStatus') == 'FINAL'
                          and v.get('score') is not None]
                if len(scores) < 8:
                    continue
                dev_std = statistics.pstdev(scores)
                rows.append(dict(league=league, ruolo=ruolo, slug=slug,
                                  presence_rate=presence_rate, dev_std=dev_std,
                                  n=len(scores)))
    return rows


def test_b():
    print()
    print("=" * 70)
    print("TEST B -- presence_rate come proxy di consistenza (dev.std. punteggi reali)")
    print("=" * 70)
    rows = collect_presence_vs_consistency()
    by_role = defaultdict(list)
    for r in rows:
        by_role[r['ruolo']].append(r)
    print(f"Totale giocatori con game_log_cache+detail_cache: {len(rows)}")
    for ruolo in R.ROLES:
        grp = by_role[ruolo]
        if len(grp) < 15:
            print(f"  {ruolo.upper()}: n insufficiente ({len(grp)})")
            continue
        xs = [r['presence_rate'] for r in grp]
        ys = [r['dev_std'] for r in grp]
        corr = pearson(xs, ys)
        cs = f"{corr:+.3f}" if corr is not None else "n/d"
        pres_sorted = sorted(xs)
        med = pres_sorted[len(pres_sorted) // 2]
        low_pres_std = [r['dev_std'] for r in grp if r['presence_rate'] <= med]
        high_pres_std = [r['dev_std'] for r in grp if r['presence_rate'] > med]
        print(f"  {ruolo.upper():<4} n={len(grp):>4}  corr(presence_rate, dev_std)={cs}  "
              f"dev_std medio -- presenza bassa: {statistics.mean(low_pres_std):.2f}  "
              f"presenza alta: {statistics.mean(high_pres_std):.2f}  "
              f"diff: {statistics.mean(high_pres_std) - statistics.mean(low_pres_std):+.2f}")


if __name__ == '__main__':
    test_a()
    test_b()
