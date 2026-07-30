"""Verifica se SPLIT_SHRINK_K_GK=5.0 (shrinkage del fattore casa/trasferta
per campione piccolo, aggiunto 28/07 per il caso Collodi) e' ben tarato
(30/07, richiesta esplicita utente dopo il caso Turner/Sirois -- il
meccanismo esiste gia' e sembra funzionare per quel caso specifico, ma non
era mai stato validato con un vero backtest walk-forward, solo aggiunto ad
hoc per correggere un caso singolo).

Metodo: walk-forward su punteggi REALI (GK), replica la formula esatta
(home_avg/overall_avg o away_avg/overall_avg, shrink = n_bucket/(n_bucket+K)),
grid search su K, MAE.

Uso: python formazione_mls/diagnostics/validate_venue_shrink_k.py
"""
import os
import sys
import glob
import json
import math
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
K_GRID = [0.0, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 1e9]  # 1e9 ~= nessun venue factor mai (sempre neutro)


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    import datetime
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                counts[slug] += 1
    return max(counts, key=counts.get) if counts else None


def load_role_players(role):
    players = []
    patterns = [f'formazione_*/output/*_{role}_all/.cache', f'formazione_*/output/*_{role}_calibration/.cache']
    seen_files = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath in seen_files:
                    continue
                seen_files.add(fpath)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        cache = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                entries = [e for e in cache.values() if e.get('anyGame')]
                entries = [e for e in entries if parse_date(e['anyGame']) is not None]
                if len(entries) < MIN_HISTORY + 1:
                    continue
                games = [e['anyGame'] for e in entries]
                team_slug = player_team_slug(games)
                if not team_slug:
                    continue
                rows = []
                for e in entries:
                    g = e['anyGame']
                    home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                    if home.get('slug') == team_slug:
                        is_home = True
                    elif away.get('slug') == team_slug:
                        is_home = False
                    else:
                        continue
                    rows.append({'date': parse_date(g), 'is_home': is_home, 'score': e.get('score') or 0.0})
                rows.sort(key=lambda r: r['date'])
                if len(rows) < MIN_HISTORY + 1:
                    continue
                players.append(rows)
    return players


def venue_factor(hist, target_is_home, shrink_k):
    scores = [r['score'] for r in hist]
    if not scores:
        return 1.0
    overall_avg = sum(scores) / len(scores)
    if overall_avg <= 0:
        return 1.0
    home_scores = [r['score'] for r in hist if r['is_home']]
    away_scores = [r['score'] for r in hist if not r['is_home']]
    if target_is_home:
        bucket = home_scores
    else:
        bucket = away_scores
    if not bucket:
        return 1.0
    bucket_avg = sum(bucket) / len(bucket)
    raw = bucket_avg / overall_avg
    n_bucket = len(bucket)
    shrink = n_bucket / (n_bucket + shrink_k) if shrink_k < 1e8 else 0.0
    return 1.0 + shrink * (raw - 1.0)


def main():
    role = (sys.argv[1] if len(sys.argv) > 1 else 'gk').lower()
    print(f"Caricamento giocatori {role.upper()}...")
    players = load_role_players(role)
    print(f"Giocatori utilizzabili: {len(players)}\n")

    # baseline: media pesata semplice (no half-life, per isolare SOLO
    # l'effetto del venue factor, non altre formule) x venue_factor(K)
    results_by_k = defaultdict(list)
    n_test = 0
    for rows in players:
        n = len(rows)
        for i in range(MIN_HISTORY, n):
            hist = rows[:i]
            media = sum(r['score'] for r in hist) / len(hist)
            target_is_home = rows[i]['is_home']
            reale = rows[i]['score']
            n_test += 1
            for k in K_GRID:
                vf = venue_factor(hist, target_is_home, k)
                pred = media * vf
                results_by_k[k].append((reale, pred))

    def mae(pairs):
        return statistics.mean(abs(r - p) for r, p in pairs)

    print(f"Punti di test: {n_test}\n")
    mae_current = mae(results_by_k[5.0])
    print(f"{'SPLIT_SHRINK_K':<18} {'MAE':>8} {'vs K=5 (attuale)':>18}")
    for k in K_GRID:
        m = mae(results_by_k[k])
        pct = (m - mae_current) / mae_current * 100
        label = "nessuno (neutro sempre)" if k >= 1e8 else f"{k:.1f}"
        flag = ' <== ATTUALE' if k == 5.0 else (' <== MIGLIORE' if m < mae_current - 0.001 else '')
        print(f"{label:<18} {m:>8.3f} {pct:>+17.2f}%{flag}")


if __name__ == '__main__':
    main()
