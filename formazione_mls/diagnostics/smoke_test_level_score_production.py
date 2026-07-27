"""
Smoke test (27/07 notte): verifica che la formula REALE di produzione (dopo
l'implementazione di level_score atteso, sezione 22 del riassunto) migliori
il MAE walk-forward rispetto alla vecchia formula, usando le funzioni VERE
dei moduli modificati (non una reimplementazione separata come lo script
diagnostico originale). Copre solo il "core swap" (level_score_atteso +
granulare_atteso invece della media generica) + le correzioni additive
Stadio D residue per DEF/MID/FWD (venue/avversario sulle sotto-categorie
granulari) + lo shrinkage FWD -- non l'intera pipeline di build_prediction
(niente filtro competizione/starter odds, irrilevante per il MAE storico).

Zero nuove query: cache .cache/*_detail_cache.json gia' su disco.
"""
import os
import sys
import json
import glob
import importlib
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

LEAGUE_CACHE_TPL = {
    'mls': 'formazione_mls/output/mls_{ruolo}_calibration/.cache',
    'kleague': 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache',
    'portogallo': 'formazione_portogallo/output/portogallo_{ruolo}_all/.cache',
    'austria': 'formazione_austria/output/austria_{ruolo}_all/.cache',
    'scozia': 'formazione_scozia/output/scozia_{ruolo}_all/.cache',
    'croazia': 'formazione_croazia/output/croazia_{ruolo}_all/.cache',
}


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def load_players(ruolo):
    files = []
    for tpl in LEAGUE_CACHE_TPL.values():
        cache_dir = tpl.format(ruolo=ruolo)
        files.extend(glob.glob(os.path.join(cache_dir, '*_detail_cache.json')))
    players = []
    for fpath in files:
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
        recs = []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            recs.append({'score': e.get('score') or 0.0, 'is_home': is_home,
                         'detail': {'detailedScore': e.get('detailedScore')}})
        if len(recs) < MIN_HISTORY + 3:
            continue
        players.append(recs)
    return players


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    weighted_mean = mod.weighted_mean
    exponential_weights = mod.exponential_weights
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    extract_level_score = mod.extract_level_score
    extract_decisive_rates = mod.extract_decisive_rates
    expected_level_from_rates = mod.expected_level_from_rates
    HL = mod.HALF_LIFE_GAMES
    TI = mod.TREND_INTENSITY

    players = load_players(ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato")
        return

    errori_old, errori_new = [], []
    for recs in players:
        scores = [r['score'] for r in recs]
        is_home_flags = [r['is_home'] for r in recs]
        level_scores = [extract_level_score(r['detail']) for r in recs]
        granulari = [s - l for s, l in zip(scores, level_scores)]
        pos_dec, neg_dec = [], []
        for r in recs:
            p, ng = extract_decisive_rates(r['detail'])
            pos_dec.append(p)
            neg_dec.append(ng)

        n = len(scores)
        for i in range(MIN_HISTORY, n):
            weights = exponential_weights(i, HL)
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]

            # OLD: media pesata sul totale
            media = weighted_mean(hist_scores, weights)
            fattore_ct_old = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend_old, _, _ = compute_trend_factor(hist_scores, trend_intensity=TI)
            pred_old = media * fattore_ct_old * fattore_trend_old

            # NEW: level_score atteso (tasso eventi) + granulare atteso trend
            lam_pos = weighted_mean(pos_dec[:i], weights)
            lam_neg = weighted_mean(neg_dec[:i], weights)
            level_atteso = expected_level_from_rates(lam_pos, lam_neg)
            gran_atteso = weighted_mean(granulari[:i], weights)
            fattore_trend_gran, _, _ = compute_trend_factor(granulari[:i], trend_intensity=TI)
            fattore_ct_new = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            pred_new = (level_atteso + gran_atteso * fattore_trend_gran) * fattore_ct_new

            errori_old.append(scores[i] - pred_old)
            errori_new.append(scores[i] - pred_new)

    mae_old = statistics.mean(abs(e) for e in errori_old)
    mae_new = statistics.mean(abs(e) for e in errori_new)
    pct = (mae_new - mae_old) / mae_old * 100
    print(f"{ruolo.upper()}: n={len(errori_old)}  MAE old={mae_old:.3f}  MAE new={mae_new:.3f}  "
          f"delta={pct:+.2f}%")


if __name__ == '__main__':
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        run_role(ruolo)
