"""Ricalibrazione MID e FWD sulla formula ALLINEATA alla produzione (31/07),
gemello di recalibra_gk_formula_allineata.py.

Stesso problema del portiere: il grid search che gira in CALIBRATION_MODE per
MID e FWD usa la vecchia `rigorous_backtest` (media pesata x fattore casa x
fattore forza avversario x trend), non `compute_score_atteso_mid/_fwd`. Manca
quindi level_score da tassi Poisson, shrinkage verso il prior di ruolo,
shrinkage venue e opponent_lambda_mult -- e in piu' USA il fattore ranking
avversario che dalla produzione era stato rimosso. Le funzioni allineate
`rigorous_backtest_prod_mid/_fwd` esistono ma non sono mai chiamate.

Qui si rifa' il grid search chiamando le funzioni REALI di produzione, sui
dati gia' in cache, e si confronta il vincitore con i valori attuali.

L'estrazione dei granulari usa le COSTANTI E LE FUNZIONI DEI MODULI STESSI
(OFFENSIVE_STATS, PASSING_STATS, extract_group_score, ...), non una copia:
cosi' non puo' divergere da come la produzione li calcola.

Uso: python formazione_mls/diagnostics/recalibra_mid_fwd_formula_allineata.py [mid|fwd]
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

MIN_HISTORY = 6
HALF_LIVES = (6.0, 9.0, 12.0, 15.0, 20.0, 25.0, 30.0)
TREND_INTENSITIES = (0.0, 0.2, 0.3, 0.7, 1.0, 1.3)
RANGE_MULTS = (1.0, 1.1, 1.15, 1.2, 1.3, 1.4)

MODULI = {
    'mid': 'formazione_mls/predict/test_mid.py',
    'fwd': 'formazione_mls/predict/test_mls_fwd_all.py',
    'def': 'formazione_mls/predict/test_def.py',
}
CACHE_GLOB = {
    'mid': ('formazione_*/output/*_mid_all/.cache', 'formazione_*/output/*_mid_calibration/.cache'),
    'fwd': ('formazione_*/output/*_fwd_all/.cache', 'formazione_*/output/*_fwd_calibration/.cache'),
    'def': ('formazione_*/output/*_def_all/.cache', 'formazione_*/output/*_def_calibration/.cache'),
}


def imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
        for lato in ('homeTeam', 'awayTeam'):
            s = (g.get(lato) or {}).get('slug')
            if s:
                c[s] += 1
    return max(c, key=c.get) if c else None


def presence_rate_for(cache_dir, slug):
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


def carica(ruolo, mod):
    out = []
    for pattern in CACHE_GLOB[ruolo]:
        for cache_dir in glob.glob(pattern):
            lega = cache_dir.split('formazione_', 1)[1].split(os.sep)[0].split('/')[0]
            for f in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                slug = os.path.basename(f).replace('_detail_cache.json', '')
                try:
                    cache = json.load(open(f, encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    continue
                nodi = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
                if len(nodi) < MIN_HISTORY + 3:
                    continue
                team = team_of([e['anyGame'] for e in nodi])
                if not team:
                    continue
                righe = []
                for e in nodi:
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
                    score = e.get('score') or 0.0
                    lvl = mod.extract_level_score(e)
                    pos_v, neg_v = mod.extract_decisive_rates(e)
                    fouls_v = mod.extract_group_score(e, mod.FOULS_STATS)
                    duels_v = mod.extract_group_score(e, mod.DUELS_STATS)
                    off_v = mod.extract_group_score(e, mod.OFFENSIVE_STATS)
                    pass_v = mod.extract_group_score(e, mod.PASSING_STATS)
                    def_raw = mod.extract_group_score(e, mod.DEFENSE_RARE_STATS)
                    riga = dict(dt=dt, is_home=is_home, opp=opp, score=score,
                                gran=score - lvl, pos=pos_v, neg=neg_v,
                                off=off_v, pas=pass_v)
                    if ruolo == 'def':
                        def_act = mod.extract_group_score(e, mod.DEFENSIVE_ACTIONS_STATS)
                        gc = mod.extract_group_score(e, mod.GOALS_CONCEDED_STATS)
                        cs = mod.extract_group_score(e, mod.CLEAN_SHEET_STATS)
                        coperto = (fouls_v + duels_v + off_v + pass_v
                                   + def_raw + def_act + gc + cs)
                        riga['gc'] = gc
                        riga['cs'] = cs
                        riga['res'] = score - coperto
                    elif ruolo == 'mid':
                        def_act = mod.extract_group_score(e, mod.DEFENSIVE_ACTIONS_STATS)
                        gc = mod.extract_group_score(e, mod.GOALS_CONCEDED_STATS)
                        cap = mod.DEFENSE_RARE_CAP
                        def_raw_c = max(-cap, min(cap, def_raw))
                        coperto = fouls_v + duels_v + off_v + pass_v + def_raw_c + def_act + gc
                        riga['gc'] = gc
                        riga['res'] = score - coperto
                    else:
                        coperto = fouls_v + duels_v + off_v + pass_v + def_raw
                        riga['res'] = score - coperto
                    righe.append(riga)
                righe.sort(key=lambda r: r['dt'])
                if len(righe) < MIN_HISTORY + 3:
                    continue
                out.append((lega, righe, presence_rate_for(cache_dir, slug)))
    return out


def predici(ruolo, mod, righe, i, hl, ti, pr, lega):
    h = righe[:i]
    comune = dict(
        scores=[r['score'] for r in h], is_home_flags=[r['is_home'] for r in h],
        residual_values=[r['res'] for r in h], granulari_values=[r['gran'] for r in h],
        pos_decisive_values=[r['pos'] for r in h], neg_decisive_values=[r['neg'] for r in h],
        target_is_home=righe[i]['is_home'], p_gioca=1.0,
        half_life=hl, trend_intensity=ti, presence_rate=pr, league=lega,
    )
    if ruolo == 'def':
        return mod.compute_score_atteso_def(
            opponent_rankings=[None] * i,
            goals_conceded_values=[r['gc'] for r in h],
            passing_values=[r['pas'] for r in h],
            clean_sheet_values=[r['cs'] for r in h],
            target_opp_rank=None,
            opponent_team_slugs_hist=[r['opp'] for r in h],
            game_dates_hist=[r['dt'] for r in h],
            next_opponent_team_slug=righe[i]['opp'],
            next_game_date=righe[i]['dt'],
            **comune)
    if ruolo == 'mid':
        return mod.compute_score_atteso_mid(
            opponent_rankings=[None] * i,
            offensive_values=[r['off'] for r in h],
            passing_values=[r['pas'] for r in h],
            goals_conceded_values=[r['gc'] for r in h],
            target_opp_rank=None,
            opponent_team_slugs=[r['opp'] for r in h],
            game_dates=[r['dt'] for r in h],
            target_opponent_team_slug=righe[i]['opp'],
            target_cutoff_dt=righe[i]['dt'],
            **comune)
    return mod.compute_score_atteso_fwd(
        passing_values=[r['pas'] for r in h],
        offensive_values=[r['off'] for r in h],
        next_opponent_team_slug=righe[i]['opp'],
        next_game_date=righe[i]['dt'],
        **comune)


def main():
    ruoli = sys.argv[1:] or ['def', 'mid', 'fwd']
    for ruolo in ruoli:
        mod = imp(f'test_{ruolo}_lib', MODULI[ruolo])
        print(f"\n{'=' * 78}\nRUOLO {ruolo.upper()} — ricalibrazione su formula allineata\n{'=' * 78}")
        dataset = carica(ruolo, mod)
        print(f"Giocatori: {len(dataset)}")

        risultati = []
        for hl in HALF_LIVES:
            for ti in TREND_INTENSITIES:
                errori, sds = [], []
                for lega, righe, pr in dataset:
                    n = len(righe)
                    for i in range(MIN_HISTORY, n):
                        pred = predici(ruolo, mod, righe, i, hl, ti, pr, lega)
                        errori.append(righe[i]['score'] - pred)
                        w = mod.exponential_weights(i, hl)
                        sc = [r['score'] for r in righe[:i]]
                        sds.append(mod.weighted_stddev(sc, w, mod.weighted_mean(sc, w)))
                mae = statistics.mean(abs(e) for e in errori)
                for rm in RANGE_MULTS:
                    cop = sum(1 for e, sd in zip(errori, sds)
                              if sd > 0 and abs(e) <= sd * rm) / len(errori) * 100
                    risultati.append((mae + abs(cop - 68.0) * 0.3, mae, cop, hl, ti, rm))
        risultati.sort()

        print(f"\n{'#':>3} {'composite':>10} {'MAE':>8} {'copert.':>9} {'half_life':>10} {'trend':>7} {'range':>7}")
        for idx, (c, mae, cop, hl, ti, rm) in enumerate(risultati[:10], 1):
            print(f"{idx:>3} {c:>10.3f} {mae:>8.3f} {cop:>8.1f}% {hl:>10} {ti:>7} {rm:>7}")

        hl_att, ti_att = mod.HALF_LIFE_GAMES, mod.TREND_INTENSITY
        rm_att = getattr(mod, 'RANGE_MULTIPLIER', 1.1)
        att = [r for r in risultati if r[3] == hl_att and r[4] == ti_att and abs(r[5] - rm_att) < 1e-9]
        if att:
            c, mae, cop, hl, ti, rm = att[0]
            print(f"\nPRODUZIONE OGGI: half_life={hl}, trend={ti}, range={rm}")
            print(f"  composite {c:.3f} (MAE {mae:.3f}, copertura {cop:.1f}%) "
                  f"-> posizione {risultati.index(att[0]) + 1} su {len(risultati)}")
            b = risultati[0]
            print(f"VINCITORE:       half_life={b[3]}, trend={b[4]}, range={b[5]}")
            print(f"  composite {b[0]:.3f} (MAE {b[1]:.3f}, copertura {b[2]:.1f}%)")
            print(f"\nGuadagno potenziale in MAE: {(b[1] - mae) / mae * 100:+.2f}%")
        else:
            print(f"\n(combinazione di produzione hl={hl_att}/ti={ti_att}/rm={rm_att} "
                  f"non presente nella griglia testata)")


if __name__ == '__main__':
    main()
