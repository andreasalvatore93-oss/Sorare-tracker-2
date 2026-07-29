"""Selection Quality dello shrinkage, TUTTI E 4 I RUOLI (29/07, test scelto
dall'utente dopo il retuning globale dello shrinkage di oggi stesso).

DOMANDA CRITICA: oggi (stessa sessione) sono stati scelti nuovi valori di
SHRINK_K_OUTLIER_<ruolo> guardando SOLO il MAE (GK k=30, DEF k=15, MID k=5,
FWD k=5, modello unico globale). Ma la scoperta di sez. 27.C del RIASSUNTO
dice che uno shrinkage ottimo-per-MAE puo' PEGGIORARE la vera capacita' di
scegliere bene (lift, misurato da selection_quality.py) -- e' per questo che
DEF ha gia' `score_ordinamento` (shrink_k=0) separato dal punteggio mostrato.
GK/MID/FWD non sono mai stati controllati con questa metrica. Qui si
confrontano, per ogni ruolo, PRODUZIONE (shrink_k attuale) vs NO-SHRINK
(shrink_k=0) vs media pesata semplice, sulla metrica del lift (non MAE).

Stesso principio walk-forward/no-lookahead di sempre. Riusa le funzioni di
`measure_range_reliability.py` (discovery leghe, estrazione array per ruolo,
use_stadio_d=False per DEF/MID/FWD -- semplificazione gia' accettata li',
Stadio D non tocca lo shrinkage) per non duplicare codice.

Uso: python formazione_mls/diagnostics/selection_quality_shrinkage_allroles.py
"""
import os
import sys
import glob
import json
import importlib
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())
os.environ.setdefault('SORARE_COOKIE', 'x')

import measure_range_reliability as R  # noqa: E402 (discovery leghe + build_common + residui)

MIN_HISTORY = 6
TOP_K = 3
MIN_CANDIDATI = 5

SHRINK_ATTR = {'gk': 'SHRINK_K_OUTLIER_GK', 'def': 'SHRINK_K_OUTLIER_DEF',
               'mid': 'SHRINK_K_OUTLIER_MID', 'fwd': 'SHRINK_K_OUTLIER_FWD'}


def score_with_shrink(mod, ruolo, a, resid, i, shrink_k):
    target_is_home = a['is_home'][i]
    if ruolo == 'gk':
        return mod.compute_score_atteso_gk(
            a['scores'][:i], a['is_home'][:i], a['gran'][:i], a['pos'][:i], a['neg'][:i],
            target_is_home=target_is_home, p_gioca=1.0, shrink_k=shrink_k)
    if ruolo == 'fwd':
        return mod.compute_score_atteso_fwd(
            a['scores'][:i], a['is_home'][:i], resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['pa'][:i],
            target_is_home=target_is_home, p_gioca=1.0, use_stadio_d=False, shrink_k=shrink_k)
    if ruolo == 'def':
        return mod.compute_score_atteso_def(
            a['scores'][:i], a['is_home'][:i], [None] * i, resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['gc'][:i], a['pa'][:i], a['cs'][:i],
            target_is_home=target_is_home, target_opp_rank=None, p_gioca=1.0,
            use_stadio_d=False, shrink_k=shrink_k)
    if ruolo == 'mid':
        return mod.compute_score_atteso_mid(
            a['scores'][:i], a['is_home'][:i], [None] * i, resid[:i], a['gran'][:i],
            a['pos'][:i], a['neg'][:i], a['of'][:i], a['pa'][:i], a['gc'][:i],
            target_is_home=target_is_home, target_opp_rank=None, p_gioca=1.0,
            use_stadio_d=False, shrink_k=shrink_k)
    raise ValueError(ruolo)


def collect_for_role(ruolo):
    """Ritorna: giornate[(league, date)] = lista di (slug, reale, {strategia: pred}),
    piu' il valore di shrink_k di produzione usato (letto dal modulo MLS)."""
    mod_mls_name, _ = R._module_name('mls', ruolo)
    mod_mls = importlib.import_module(mod_mls_name)
    prod_k = getattr(mod_mls, SHRINK_ATTR[ruolo])

    giornate = defaultdict(list)
    n_players = 0
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

            slug = os.path.basename(fpath).replace('_detail_cache.json', '')
            n_players += 1
            half_life = mod.HALF_LIFE_GAMES

            for i in range(MIN_HISTORY, n):
                if a['dates'][i] is None:
                    continue
                try:
                    pred_prod = score_with_shrink(mod, ruolo, a, resid, i, prod_k)
                    pred_noshrink = score_with_shrink(mod, ruolo, a, resid, i, 0.0)
                except Exception:
                    continue
                weights = mod.exponential_weights(i, half_life)
                pred_media = mod.weighted_mean(a['scores'][:i], weights)
                reale = a['scores'][i]
                date = a['dates'][i].date().isoformat()
                giornate[(league, date)].append((
                    slug, reale,
                    {'MODELLO (shrink prod.)': pred_prod,
                     'NO-SHRINK (shrink_k=0)': pred_noshrink,
                     'media pesata storica': pred_media}))
    return giornate, prod_k, n_players


def report_role(ruolo):
    giornate, prod_k, n_players = collect_for_role(ruolo)
    valide = {k: v for k, v in giornate.items() if len(v) >= MIN_CANDIDATI}
    print(f"\n=== {ruolo.upper()} (produzione shrink_k={prod_k}) ===")
    if not valide:
        print("  Nessuna giornata con abbastanza candidati.")
        return
    strategie = ['MODELLO (shrink prod.)', 'NO-SHRINK (shrink_k=0)', 'media pesata storica']
    somme = defaultdict(float)
    n_g = 0
    tot_caso = tot_oracolo = 0.0
    for (champ, data), cands in sorted(valide.items()):
        reali = [c[1] for c in cands]
        caso = statistics.mean(reali)
        oracolo = statistics.mean(sorted(reali, reverse=True)[:TOP_K])
        tot_caso += caso
        tot_oracolo += oracolo
        n_g += 1
        for nome in strategie:
            scelti = sorted(cands, key=lambda c: -c[2][nome])[:TOP_K]
            somme[nome] += statistics.mean(c[1] for c in scelti)

    print(f"  giornate valutate: {n_g} (>= {MIN_CANDIDATI} candidati, schierati i top {TOP_K}), "
          f"{n_players} giocatori, {len(set(k[0] for k in valide))} leghe")
    caso_m = tot_caso / n_g
    orac_m = tot_oracolo / n_g
    print(f"  {'strategia':<24} {'punti/giornata':>14} {'vs caso':>9} {'lift catturato':>15}")
    print(f"  {'CASO (media candidati)':<24} {caso_m:>14.2f} {'--':>9} {'0.0%':>15}")
    righe = []
    for nome in strategie:
        m = somme[nome] / n_g
        lift = (m - caso_m) / (orac_m - caso_m) * 100 if orac_m > caso_m else 0.0
        righe.append((lift, nome, m))
    for lift, nome, m in sorted(righe, reverse=True):
        print(f"  {nome:<24} {m:>14.2f} {m - caso_m:>+9.2f} {lift:>14.1f}%")
    print(f"  {'ORACOLO (top veri)':<24} {orac_m:>14.2f} {orac_m - caso_m:>+9.2f} {'100.0%':>15}")


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        report_role(ruolo)


if __name__ == '__main__':
    main()
