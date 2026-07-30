"""TEMA "meglio il piu' affidabile o il piu' forte" (30/07, richiesta esplicita
utente, backlog project_backlog_affidabile_vs_forte) -- TUTTI E 4 I RUOLI, TUTTE
LE LEGHE (stessa infrastruttura di selection_quality_shrinkage_allroles.py).

Domanda esatta: dato un gruppo di candidati per uno slot, conviene scegliere
quello con score_atteso piu' alto (strategia attuale, pura), o vale la pena
penalizzare lo score per la sua dispersione storica (dev_std pesata) e
preferire un giocatore piu' basso ma piu' consistente? MAI testato prima come
confronto diretto di strategie di selezione (i test del 29/07, checklist
sezione E, misuravano se il range PREDICE l'errore -- domanda diversa,
SCARTATA per mancanza di correlazione). Richiesto ORA perche' la produzione
e' stata appena aggiornata (fix anyPlayers/prior dinamico/opponent_lambda_mult)
e il pool di calibrazione e' quasi triplicato.

Uso: python formazione_mls/diagnostics/measure_reliability_vs_score_allroles.py
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

import measure_range_reliability as R  # noqa: E402
from selection_quality_shrinkage_allroles import score_with_shrink, SHRINK_ATTR  # noqa: E402

MIN_HISTORY = 6
TOP_K = 3
MIN_CANDIDATI = 5
LAMBDAS = (0.1, 0.2, 0.3, 0.5, 0.8)


def collect_for_role(ruolo):
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
                except Exception:
                    continue
                weights = mod.exponential_weights(i, half_life)
                mean_hist = mod.weighted_mean(a['scores'][:i], weights)
                dev = mod.weighted_stddev(a['scores'][:i], weights, mean_hist)
                reale = a['scores'][i]
                date = a['dates'][i].date().isoformat()
                preds = {'MODELLO (score puro, produzione)': pred_prod}
                for lam in LAMBDAS:
                    preds[f'score - {lam}*dev_std'] = pred_prod - lam * dev
                preds['score / dev_std (Sharpe)'] = pred_prod / dev if dev > 0.01 else pred_prod
                giornate[(league, date)].append((slug, reale, preds))
    return giornate, n_players


def report_role(ruolo):
    giornate, n_players = collect_for_role(ruolo)
    valide = {k: v for k, v in giornate.items() if len(v) >= MIN_CANDIDATI}
    print(f"\n=== {ruolo.upper()} ===")
    if not valide:
        print("  Nessuna giornata con abbastanza candidati.")
        return
    strategie = ['MODELLO (score puro, produzione)'] + \
        [f'score - {lam}*dev_std' for lam in LAMBDAS] + ['score / dev_std (Sharpe)']
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
    print(f"  {'strategia':<32} {'punti/giornata':>14} {'vs caso':>9} {'lift catturato':>15}")
    print(f"  {'CASO (media candidati)':<32} {caso_m:>14.2f} {'--':>9} {'0.0%':>15}")
    righe = []
    for nome in strategie:
        m = somme[nome] / n_g
        lift = (m - caso_m) / (orac_m - caso_m) * 100 if orac_m > caso_m else 0.0
        righe.append((lift, nome, m))
    for lift, nome, m in sorted(righe, reverse=True):
        print(f"  {nome:<32} {m:>14.2f} {m - caso_m:>+9.2f} {lift:>14.1f}%")
    print(f"  {'ORACOLO (top veri)':<32} {orac_m:>14.2f} {orac_m - caso_m:>+9.2f} {'100.0%':>15}")


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        report_role(ruolo)


if __name__ == '__main__':
    main()
