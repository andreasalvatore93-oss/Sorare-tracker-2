"""Measure Range Reliability (29/07, tema scelto dall'utente dopo caso reale
gw96 In Season MLS: Fernandez-Mercau atteso 76 range 62-98 [ampiezza 36] vs
McGlynn atteso 76 range 48-91 [ampiezza 43] -- stesso atteso, range diverso).

DOMANDA: il range di confidenza [range_low, range_high] (vedi test_def.py,
funzione weighted_percentile + variabili p16_score/p84_score/range_low/
range_high, righe ~1600-1850) e' un segnale REALE di affidabilita' storica
del giocatore, o e' rumore? E quanto e' diffuso/utile il fenomeno "stesso
atteso, range diverso" nella scelta 1-su-N (In Season)?

NESSUNA query API: si riusano le cache di calibrazione/produzione gia' su
disco, stesso principio walk-forward gia' applicato in
`nonregression_score_atteso_def.py`/`nonregression_score_atteso_fwd.py`
(arrays_from_cache) e in `selection_quality.py`/`measure_teammate_correlation.py`
(auto-discovery multi-lega dal filesystem).

METODO (per ogni ruolo GK/DEF/MID/FWD, per ogni giocatore/lega con storico
sufficiente, walk-forward: per ogni partita i >= MIN_HISTORY usa SOLO le
partite [:i] come storico):
  1. score_atteso = compute_score_atteso_<ruolo>(...) -- la STESSA funzione
     CONDIVISA di produzione usata da build_prediction e dal backtest di
     calibrazione (vedi test_def.py/test_mid.py/test_mls_fwd_all.py/test_gk.py).
     SEMPLIFICAZIONE ACCETTATA (stesso compromesso di
     measure_teammate_correlation.py): use_stadio_d=False per DEF/MID/FWD,
     cioe' SENZA le correzioni condizionate venue+avversario (Stadio D) --
     evita di dover ricostruire opponent_rankings/team-slug storici solo per
     questo diagnostico. Stadio D sposta score_atteso di poco (qualche punto)
     e non tocca affatto range_low/range_high (che dipendono solo da
     media_pesata/p16/p84 sui punteggi grezzi storici), quindi non altera le
     conclusioni su "il range e' un segnale?". GK non ha comunque Stadio D
     in produzione (gia' rimosso), quindi per GK il calcolo e' identico alla
     produzione al 100%.
  2. range_low/range_high con la STESSA formula di produzione:
       p16 = weighted_percentile(scores_storici, pesi, 16)
       p84 = weighted_percentile(scores_storici, pesi, 84)
       media_pesata = weighted_mean(scores_storici, pesi)
       range_low  = max(0, score_atteso - (media_pesata - p16))
       range_high = score_atteso + (p84 - media_pesata)
       range_width = range_high - range_low
     (pesi = weights esponenziali con l'half_life di PRODUZIONE del ruolo,
     stessi usati da score_atteso -- coerenza garantita).
  3. reale = punteggio VERO di quella partita (mai visto dallo storico).

Poi si rispondono le 4 domande dell'utente aggregando SOLO su dati
ex-ante/ex-post cosi' costruiti (nessuna fuga di informazione dal futuro).

Uso: python formazione_mls/diagnostics/measure_range_reliability.py
"""
import os
import sys
import glob
import json
import math
import statistics
import importlib
import datetime
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 7
ROLES = ('gk', 'def', 'mid', 'fwd')

STATS_NAMES = ('FOULS_STATS', 'DUELS_STATS', 'OFFENSIVE_STATS', 'PASSING_STATS',
               'DEFENSE_RARE_STATS', 'DEFENSIVE_ACTIONS_STATS', 'GOALS_CONCEDED_STATS',
               'CLEAN_SHEET_STATS')


# Stesso pattern di auto-discovery filesystem di measure_teammate_correlation.py
# (28/07): ogni cartella formazione_<lega>/output/<lega>_<ruolo>_all trovata
# entra in automatico; mls/kleague puntano alla cache "_calibration" (piu'
# grande, gia' usata per il grid search), le altre leghe alla cache "_all"
# di produzione (stessi dati per-partita).
def _discover_leagues():
    found = {}
    for gk_dir in sorted(glob.glob(os.path.join('formazione_*', 'output', '*_gk_all'))):
        champ_dir = os.path.basename(os.path.dirname(os.path.dirname(gk_dir)))
        league = champ_dir[len('formazione_'):]
        found[league] = (f'formazione_{league}.predict.test_{{ruolo}}',
                          f'formazione_{league}/output/{league}_{{ruolo}}_all/.cache')
    if 'mls' in found:
        found['mls'] = ('formazione_mls.predict.test_{ruolo}',
                         'formazione_mls/output/mls_{ruolo}_calibration/.cache')
    if 'kleague' in found:
        found['kleague'] = ('formazione_kleague.predict.test_{ruolo}',
                             'formazione_kleague/output/kleague_{ruolo}_calibration/.cache')
    return found


LEAGUES = _discover_leagues()


def _module_name(league, ruolo):
    mod_tpl, cache_tpl = LEAGUES[league]
    if ruolo == 'fwd':
        prefix = mod_tpl.rsplit('.', 1)[0]
        return f"{prefix}.test_mls_fwd_all", cache_tpl.format(ruolo=ruolo)
    return mod_tpl.format(ruolo=ruolo), cache_tpl.format(ruolo=ruolo)


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def build_common(mod, entries, team_slug, ruolo):
    """Estrae gli array comuni (score, is_home, granulari, pos/neg decisive,
    date) -- stesso pattern di arrays_from_cache nei
    nonregression_score_atteso_*.py. GK non ha i gruppi granulari STATS
    (FOULS_STATS/DUELS_STATS/...): compute_score_atteso_gk non ne ha
    bisogno (nessun residual_values in firma), quindi si saltano."""
    scores, is_home, dates, gran, pos, neg = [], [], [], [], [], []
    fo, du, of, pa, dr, da, gc, cs = ([] for _ in range(8))
    need_stats = ruolo != 'gk'
    need_full = ruolo in ('def', 'mid')
    need_cs = ruolo == 'def'
    for v in entries:
        g = v['anyGame']
        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
        if home.get('slug') == team_slug:
            is_h = True
        elif away.get('slug') == team_slug:
            is_h = False
        else:
            continue
        gs = v.get('score') or 0.0
        lv = mod.extract_level_score(v)
        p, n_ = mod.extract_decisive_rates(v)
        scores.append(gs)
        is_home.append(is_h)
        dates.append(parse_date(g))
        gran.append(gs - lv)
        pos.append(p)
        neg.append(n_)
        if need_stats:
            fo.append(mod.extract_group_score(v, mod.FOULS_STATS))
            du.append(mod.extract_group_score(v, mod.DUELS_STATS))
            of.append(mod.extract_group_score(v, mod.OFFENSIVE_STATS))
            pa.append(mod.extract_group_score(v, mod.PASSING_STATS))
            dr.append(mod.extract_group_score(v, mod.DEFENSE_RARE_STATS))
            if need_full:
                da.append(mod.extract_group_score(v, mod.DEFENSIVE_ACTIONS_STATS))
                gc.append(mod.extract_group_score(v, mod.GOALS_CONCEDED_STATS))
                if need_cs:
                    cs.append(mod.extract_group_score(v, mod.CLEAN_SHEET_STATS))
                else:
                    cs.append(0.0)
            else:
                da.append(0.0)
                gc.append(0.0)
                cs.append(0.0)
    return dict(scores=scores, is_home=is_home, dates=dates, gran=gran, pos=pos, neg=neg,
                fo=fo, du=du, of=of, pa=pa, dr=dr, da=da, gc=gc, cs=cs)


def residual_def_mid(a, with_cs):
    covered = [f + d + o + p + dr_ + da_ + gc_ + (c if with_cs else 0.0)
               for f, d, o, p, dr_, da_, gc_, c in zip(a['fo'], a['du'], a['of'], a['pa'],
                                                        a['dr'], a['da'], a['gc'], a['cs'])]
    return [gs - cov for gs, cov in zip(a['scores'], covered)]


def residual_fwd(a):
    covered = [f + d + o + p + dr_ for f, d, o, p, dr_ in
               zip(a['fo'], a['du'], a['of'], a['pa'], a['dr'])]
    return [gs - cov for gs, cov in zip(a['scores'], covered)]


def score_atteso_at(mod, ruolo, a, resid, i):
    """score_atteso al passo i usando SOLO lo storico [:i]. opponent_rankings
    passato come None-list: con use_stadio_d=False non viene mai letto (early
    return prima del blocco Stadio D), quindi e' sicuro non calcolarlo per
    davvero -- risparmia la ricostruzione team_ranking_from_game."""
    target_is_home = a['is_home'][i]
    if ruolo == 'gk':
        return mod.compute_score_atteso_gk(
            a['scores'][:i], a['is_home'][:i], a['gran'][:i], a['pos'][:i], a['neg'][:i],
            target_is_home=target_is_home, p_gioca=1.0)
    if ruolo == 'fwd':
        return mod.compute_score_atteso_fwd(
            a['scores'][:i], a['is_home'][:i], resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['pa'][:i],
            target_is_home=target_is_home, p_gioca=1.0, use_stadio_d=False)
    if ruolo == 'def':
        return mod.compute_score_atteso_def(
            a['scores'][:i], a['is_home'][:i], [None] * i, resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['gc'][:i], a['pa'][:i], a['cs'][:i],
            target_is_home=target_is_home, target_opp_rank=None, p_gioca=1.0,
            use_stadio_d=False)
    if ruolo == 'mid':
        return mod.compute_score_atteso_mid(
            a['scores'][:i], a['is_home'][:i], [None] * i, resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['of'][:i], a['pa'][:i], a['gc'][:i],
            target_is_home=target_is_home, target_opp_rank=None, p_gioca=1.0,
            use_stadio_d=False)
    raise ValueError(ruolo)


def collect_observations():
    """Ritorna lista di dict: league, ruolo, player_id, match_date, score_atteso,
    range_low, range_high, range_width, reale."""
    out = []
    per_role_players = defaultdict(int)

    for league in sorted(LEAGUES):
        for ruolo in ROLES:
            mod_name, cache_dir = _module_name(league, ruolo)
            try:
                mod = importlib.import_module(mod_name)
            except ModuleNotFoundError:
                continue
            files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
            for fpath in files:
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
                team_slug = player_team_slug(games)
                if not team_slug:
                    continue
                a = build_common(mod, entries, team_slug, ruolo)
                n = len(a['scores'])
                if n < MIN_HISTORY + 3:
                    continue
                if ruolo == 'fwd':
                    resid = residual_fwd(a)
                elif ruolo in ('def', 'mid'):
                    resid = residual_def_mid(a, with_cs=(ruolo == 'def'))
                else:
                    resid = None

                player_id = os.path.basename(fpath).replace('_detail_cache.json', '')
                per_role_players[ruolo] += 1
                half_life = mod.HALF_LIFE_GAMES

                for i in range(MIN_HISTORY, n):
                    if a['dates'][i] is None:
                        continue
                    try:
                        score_atteso = score_atteso_at(mod, ruolo, a, resid, i)
                    except Exception:
                        continue
                    weights = mod.exponential_weights(i, half_life)
                    scores_hist = a['scores'][:i]
                    media_pesata = mod.weighted_mean(scores_hist, weights)
                    p16 = mod.weighted_percentile(scores_hist, weights, 16)
                    p84 = mod.weighted_percentile(scores_hist, weights, 84)
                    if p16 is None or p84 is None:
                        continue
                    range_low = max(0.0, score_atteso - (media_pesata - p16))
                    range_high = score_atteso + (p84 - media_pesata)
                    range_width = range_high - range_low
                    reale = a['scores'][i]
                    match_date = a['dates'][i].date().isoformat()
                    out.append(dict(league=league, ruolo=ruolo, player_id=player_id,
                                     match_date=match_date, score_atteso=score_atteso,
                                     range_width=range_width, reale=reale))

    print("Giocatori con storico sufficiente per ruolo:", dict(per_role_players))
    return out


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


def q1_bias_check(obs_by_role):
    print("\n=== Q1: bias -- reale medio, bucket score_atteso x stretto/largo (mediana range_width) ===")
    for ruolo in ROLES:
        rows = obs_by_role[ruolo]
        if len(rows) < 30:
            print(f"  {ruolo.upper()}: n insufficiente ({len(rows)})")
            continue
        buckets = defaultdict(list)
        for r in rows:
            b = int(r['score_atteso'] // 5) * 5
            buckets[b].append(r)
        print(f"  {ruolo.upper()} (n={len(rows)} osservazioni)")
        print(f"    {'bucket atteso':>14} {'n stretto':>10} {'reale stretto':>14} "
              f"{'n largo':>9} {'reale largo':>13} {'diff':>7}")
        for b in sorted(buckets):
            grp = buckets[b]
            if len(grp) < 12:
                continue
            widths = sorted(r['range_width'] for r in grp)
            med = widths[len(widths) // 2]
            stretto = [r['reale'] for r in grp if r['range_width'] <= med]
            largo = [r['reale'] for r in grp if r['range_width'] > med]
            if len(stretto) < 5 or len(largo) < 5:
                continue
            ms, ml = statistics.mean(stretto), statistics.mean(largo)
            print(f"    {b:>12}-{b+5:<2} {len(stretto):>10} {ms:>14.1f} "
                  f"{len(largo):>9} {ml:>13.1f} {ms-ml:>+7.1f}")


def q2_range_predicts_dispersion(obs_by_role):
    print("\n=== Q2: correlazione range_width (ex-ante) vs |reale-atteso| (ex-post) ===")
    for ruolo in ROLES:
        rows = obs_by_role[ruolo]
        if len(rows) < 30:
            print(f"  {ruolo.upper()}: n insufficiente ({len(rows)})")
            continue
        xs = [r['range_width'] for r in rows]
        ys = [abs(r['reale'] - r['score_atteso']) for r in rows]
        r_all = pearson(xs, ys)
        rows_sorted = sorted(rows, key=lambda r: r['match_date'])
        mid = len(rows_sorted) // 2
        first, second = rows_sorted[:mid], rows_sorted[mid:]
        r1 = pearson([r['range_width'] for r in first], [abs(r['reale'] - r['score_atteso']) for r in first])
        r2 = pearson([r['range_width'] for r in second], [abs(r['reale'] - r['score_atteso']) for r in second])
        r1s = f"{r1:+.3f}" if r1 is not None else "n/d"
        r2s = f"{r2:+.3f}" if r2 is not None else "n/d"
        rs = f"{r_all:+.3f}" if r_all is not None else "n/d"
        print(f"  {ruolo.upper():<4} n={len(rows):>6}  corr totale={rs}   "
              f"split-half: prima meta'={r1s} (n={len(first)})  seconda meta'={r2s} (n={len(second)})")


def q3_diffusione_fenomeno(obs_by_role):
    print("\n=== Q3: tra candidati con atteso entro +-3pt (stessa giornata/ruolo/lega), "
          "% con |diff range_width| >= 15 ===")
    for ruolo in ROLES:
        rows = obs_by_role[ruolo]
        if len(rows) < 20:
            print(f"  {ruolo.upper()}: n insufficiente ({len(rows)})")
            continue
        groups = defaultdict(list)
        for r in rows:
            groups[(r['league'], r['match_date'])].append(r)
        n_pairs = 0
        n_wide_diff = 0
        for key, grp in groups.items():
            if len(grp) < 2:
                continue
            for a, b in combinations(grp, 2):
                if abs(a['score_atteso'] - b['score_atteso']) <= 3.0:
                    n_pairs += 1
                    if abs(a['range_width'] - b['range_width']) >= 15.0:
                        n_wide_diff += 1
        pct = (n_wide_diff / n_pairs * 100.0) if n_pairs else None
        pct_s = f"{pct:.1f}%" if pct is not None else "n/d"
        print(f"  {ruolo.upper():<4} coppie candidate (atteso +-3pt, stessa giornata/lega): "
              f"{n_pairs:>7}   con diff range_width>=15: {n_wide_diff:>6} ({pct_s})")


def q4_rilevanza_soglie(obs_by_role):
    print("\n=== Q4: tra le coppie con atteso simile (+-3pt), stretto vs largo -- "
          "tasso di superamento soglie assolute ===")
    thresholds = (60, 70, 80)
    for ruolo in ROLES:
        rows = obs_by_role[ruolo]
        if len(rows) < 20:
            print(f"  {ruolo.upper()}: n insufficiente ({len(rows)})")
            continue
        groups = defaultdict(list)
        for r in rows:
            groups[(r['league'], r['match_date'])].append(r)
        stretto_reali, largo_reali = [], []
        for key, grp in groups.items():
            if len(grp) < 2:
                continue
            for a, b in combinations(grp, 2):
                if abs(a['score_atteso'] - b['score_atteso']) > 3.0:
                    continue
                if a['range_width'] == b['range_width']:
                    continue
                s, l = (a, b) if a['range_width'] < b['range_width'] else (b, a)
                stretto_reali.append(s['reale'])
                largo_reali.append(l['reale'])
        n = len(stretto_reali)
        print(f"  {ruolo.upper():<4} n coppie stretto/largo confrontabili: {n}")
        if n < 15:
            continue
        for th in thresholds:
            pct_s = sum(1 for x in stretto_reali if x >= th) / n * 100.0
            pct_l = sum(1 for x in largo_reali if x >= th) / n * 100.0
            print(f"    reale >= {th}: stretto {pct_s:5.1f}%   largo {pct_l:5.1f}%   diff {pct_s-pct_l:+5.1f}")


def main():
    print(f"Leghe scoperte ({len(LEAGUES)}): {sorted(LEAGUES)}")
    print("Raccolta osservazioni walk-forward (score_atteso + range, use_stadio_d=False "
          "per DEF/MID/FWD -- vedi docstring)...")
    all_obs = collect_observations()
    print(f"Totale osservazioni (tutti i ruoli/leghe): {len(all_obs)}")

    obs_by_role = defaultdict(list)
    for o in all_obs:
        obs_by_role[o['ruolo']].append(o)

    q1_bias_check(obs_by_role)
    q2_range_predicts_dispersion(obs_by_role)
    q3_diffusione_fenomeno(obs_by_role)
    q4_rilevanza_soglie(obs_by_role)


if __name__ == '__main__':
    main()
