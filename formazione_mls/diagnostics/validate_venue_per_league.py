"""
Validate fattore_casa_trasferta PER LEGA (29/07, richiesta esplicita utente:
approfondire il tema venue con breakdown per singola lega, non solo
aggregato -- per vedere se il vantaggio casa/trasferta e' uniforme tra
campionati o varia molto).

Riusa mae_for_params/exponential_weights/weighted_mean/compute_split_factor/
compute_trend_factor dal modulo di produzione (import diretto, stessa
formula walk-forward esatta di validate_halflife_venue.py), ma raggruppa i
giocatori per LEGA (estratta dal path del file cache) invece di aggregare
tutto insieme.

Uso: python formazione_mls/diagnostics/validate_venue_per_league.py
"""
import os
import sys
import json
import glob
import re
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

_LEAGUE_RE = re.compile(r'formazione_([a-z0-9_]+)[\\/]output')


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_players_by_league(ruolo):
    """Ritorna dict lega -> lista di dict {scores, is_home_flags}."""
    patterns = [f'formazione_*/output/*_{ruolo}_calibration/.cache',
                f'formazione_*/output/*_{ruolo}_all/.cache']
    files = []
    seen = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath not in seen:
                    seen.add(fpath)
                    files.append(fpath)
    by_league = defaultdict(list)
    for fpath in files:
        m = _LEAGUE_RE.search(fpath)
        league = m.group(1) if m else 'sconosciuta'
        with open(fpath, encoding='utf-8') as f:
            cache = json.load(f)
        if not cache:
            continue
        entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
        if len(entries) < MIN_HISTORY + 3:
            continue
        games = [e['anyGame'] for e in entries]
        team_slug = player_team_slug(games)
        if not team_slug:
            continue
        scores, is_home_flags = [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            scores.append(e.get('score') or 0.0)
            is_home_flags.append(is_home)
        if len(scores) < MIN_HISTORY + 3:
            continue
        by_league[league].append({'scores': scores, 'is_home_flags': is_home_flags})
    return by_league


def mae_for_params(players, exponential_weights, weighted_mean, compute_split_factor,
                    compute_trend_factor, half_life, trend_intensity, use_venue):
    errori = []
    for p in players:
        scores, is_home_flags = p['scores'], p['is_home_flags']
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            weights = exponential_weights(i, half_life)
            media = weighted_mean(hist_scores, weights)
            if use_venue:
                fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            else:
                fattore_ct = 1.0
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=trend_intensity)
            pred = media * fattore_ct * fattore_trend
            errori.append(scores[i] - pred)
    if not errori:
        return None, 0
    return statistics.mean(abs(e) for e in errori), len(errori)


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
        exponential_weights = mod.exponential_weights
        weighted_mean = mod.weighted_mean
        compute_split_factor = mod.compute_split_factor
        compute_trend_factor = mod.compute_trend_factor
        HL = mod.HALF_LIFE_GAMES
        TI = getattr(mod, 'TREND_INTENSITY', 0.0)

        print(f"\n{'='*78}\n{ruolo.upper()} (half_life={HL}, trend_intensity={TI})\n{'='*78}")
        by_league = load_players_by_league(ruolo)
        risultati = []
        for league, players in sorted(by_league.items()):
            n_players = len(players)
            if n_players < 3:
                continue
            mae_on, n_on = mae_for_params(players, exponential_weights, weighted_mean,
                                           compute_split_factor, compute_trend_factor, HL, TI, True)
            mae_off, n_off = mae_for_params(players, exponential_weights, weighted_mean,
                                             compute_split_factor, compute_trend_factor, HL, TI, False)
            if mae_on is None or n_on < 20:
                continue
            pct = (mae_off - mae_on) / mae_on * 100
            risultati.append((league, n_players, n_on, mae_on, mae_off, pct))

        risultati.sort(key=lambda r: -r[2])
        print(f"{'Lega':<20} {'giocatori':>9} {'punti test':>10} {'MAE ON':>8} {'MAE OFF':>8} {'venue aiuta':>12}")
        for league, n_players, n_on, mae_on, mae_off, pct in risultati:
            verdict = f"{-pct:+.2f}%" if pct != 0 else "0.00%"
            flag = " <-- PEGGIORA" if pct < 0 else ""
            print(f"{league:<20} {n_players:>9} {n_on:>10} {mae_on:>8.3f} {mae_off:>8.3f} {verdict:>12}{flag}")


if __name__ == '__main__':
    main()
