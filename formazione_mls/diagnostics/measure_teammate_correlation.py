"""
Measure Teammate Correlation (26/07 notte -> 27/07, prossimo tema scelto
dall'utente a fine sessione precedente)

Domanda: quanto REALMENTE correlano i punteggi di compagni di squadra nella
STESSA partita, al netto di quello che il modello gia' prevede? Oggi ogni
slot della formazione viene scelto in modo indipendente (il migliore per il
suo ruolo), a parte una sinergia GK-DEF/GK-vs-FWD-avversario implementata a
intuito in `build_formazione_finale.py` (mai misurata sui dati). Se due
compagni di squadra tendono a fare bene/male insieme PIU' di quanto il caso
spiegherebbe, questo e' rilevante per come si costruisce la formazione
(specialmente Arena/All Stars, dove la varianza conta -- vedi backlog
"correlazione compagni di squadra" nel riassunto).

NESSUNA nuova query API: stesso approccio di `validate_team_defense_strength.py`
-- si riusano le cache di calibrazione gia' su disco (GK+DEF+MID+FWD).

Metodo:
1. Per ogni ruolo, walk-forward identico a `validate_team_defense_strength.py`:
   per ogni partita di test (i >= MIN_HISTORY), calcola un residuo =
   punteggio_reale - baseline, dove baseline = media_pesata_esponenziale *
   fattore_casa_trasferta * fattore_trend (stessa formula, SENZA fattore
   avversario -- gia' rimosso dalla produzione perche' dannoso, vedi
   `validate_team_defense_strength.py`). Il residuo isola quello che il
   modello NON spiega -- e' li' che puo' vivere una correlazione reale tra
   compagni di squadra (es. arbitro permissivo, partita ad alto ritmo,
   episodio di squadra) che il modello, guardando un solo giocatore alla
   volta, non vede.
2. Raggruppa i residui per (squadra, DATA della partita) attraverso tutti e
   4 i ruoli insieme -- stessa squadra stessa data = stessa partita reale.
3. Per ogni gruppo con 2+ giocatori, genera tutte le coppie compagno-compagno
   (escluso lo stesso giocatore) e le accumula per categoria di coppia di
   ruoli (gk-def, gk-mid, gk-fwd, def-def, def-mid, def-fwd, mid-mid,
   mid-fwd, fwd-fwd) oltre a un pool aggregato "qualsiasi coppia".
4. Calcola la correlazione di Pearson per ciascuna categoria con abbastanza
   coppie, e stampa n. coppie / n. partite distinte / n. squadre distinte
   per giudicare quanto e' solido il segnale.

NOTA METODOLOGICA: il baseline usato qui e' una versione semplificata della
formula di produzione (niente Stadio D/level_score/floor) -- lo stesso
compromesso gia' accettato in `validate_team_defense_strength.py`. Va bene
per isolare un residuo "grezzo" da correlare; non e' pensato per stimare un
MAE assoluto.

Uso: python formazione_mls/diagnostics/measure_teammate_correlation.py
"""
import os
import sys
import glob
import json
import random
import statistics
import importlib
import datetime
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.getcwd())

N_PERMUTATIONS = 999
RANDOM_SEED = 42

MIN_HISTORY = 6
ROLES = ('gk', 'def', 'mid', 'fwd')

# 27/07 notte: esteso da MLS-only a tutti e 6 i campionati con cache
# disponibile (K League + Portogallo/Austria/Scozia/Croazia, aggiunti in
# questa sessione). I 4 nuovi non hanno ancora cartelle "_calibration"
# (mai lanciata la calibrazione allargata li'), quindi si usa la cache di
# produzione "_all" -- stessi identici dati (score/detailedScore per
# partita), solo generata dal run normale invece che da CALIBRATION_MODE.
LEAGUES = {
    'mls': ('formazione_mls.predict.test_{ruolo}', 'formazione_mls/output/mls_{ruolo}_calibration/.cache'),
    'kleague': ('formazione_kleague.predict.test_{ruolo}', 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache'),
    'portogallo': ('formazione_portogallo.predict.test_{ruolo}', 'formazione_portogallo/output/portogallo_{ruolo}_all/.cache'),
    'austria': ('formazione_austria.predict.test_{ruolo}', 'formazione_austria/output/austria_{ruolo}_all/.cache'),
    'scozia': ('formazione_scozia.predict.test_{ruolo}', 'formazione_scozia/output/scozia_{ruolo}_all/.cache'),
    'croazia': ('formazione_croazia.predict.test_{ruolo}', 'formazione_croazia/output/croazia_{ruolo}_all/.cache'),
    'belgio': ('formazione_belgio.predict.test_{ruolo}', 'formazione_belgio/output/belgio_{ruolo}_all/.cache'),
}
MIN_PAIRS_FOR_REPORT = 20


def _module_and_cache(league, ruolo):
    mod_tpl, cache_tpl = LEAGUES[league]
    if ruolo == 'fwd':
        prefix = mod_tpl.rsplit('.', 1)[0]  # es. 'formazione_mls.predict'
        mod_name = f"{prefix}.test_mls_fwd_all"
    else:
        mod_name = mod_tpl.format(ruolo=ruolo)
    return mod_name, cache_tpl.format(ruolo=ruolo)


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def collect_residuals_for_role(ruolo):
    """Ritorna lista di (team_slug, match_date_iso, player_id, residuo),
    ACCORPANDO tutti i campionati in LEAGUES (27/07 notte: esteso da MLS-only
    a MLS+K League+4 nuovi). team_slug e' prefissato con la lega per evitare
    di accorpare per errore due squadre omonime di campionati diversi nel
    raggruppamento (team_slug, data) usato da build_pair_values."""
    out = []
    n_players_used = 0

    for league in LEAGUES:
        mod_name, cache_dir = _module_and_cache(league, ruolo)
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        exponential_weights = mod.exponential_weights
        weighted_mean = mod.weighted_mean
        compute_split_factor = mod.compute_split_factor
        compute_trend_factor = mod.compute_trend_factor
        HALF_LIFE_GAMES = mod.HALF_LIFE_GAMES
        TREND_INTENSITY = mod.TREND_INTENSITY

        files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
        for fpath in files:
            with open(fpath, encoding='utf-8') as f:
                cache = json.load(f)
            if not cache:
                continue
            entries = [e for e in cache.values() if e.get('anyGame') and e.get('detailedScore')]
            if len(entries) < MIN_HISTORY + 3:
                continue
            games = [e['anyGame'] for e in entries]
            team_slug_raw = player_team_slug(games)
            if not team_slug_raw:
                continue
            team_slug = f"{league}:{team_slug_raw}"

            player_id = os.path.basename(fpath).replace('_detail_cache.json', '')

            scores, is_home_flags, dates, opponents = [], [], [], []
            for e in entries:
                g = e['anyGame']
                home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
                if home.get('slug') == team_slug_raw:
                    is_home, opp_slug = True, away.get('slug')
                elif away.get('slug') == team_slug_raw:
                    is_home, opp_slug = False, home.get('slug')
                else:
                    continue
                dt = parse_date(g)
                scores.append(e.get('score') or 0.0)
                is_home_flags.append(is_home)
                dates.append(dt)
                opponents.append(f"{league}:{opp_slug}" if opp_slug else None)

            n = len(scores)
            if n < MIN_HISTORY + 3:
                continue
            n_players_used += 1

            for i in range(MIN_HISTORY, n):
                if dates[i] is None:
                    continue
                hist_scores = scores[:i]
                hist_home = is_home_flags[:i]
                weights = exponential_weights(i, HALF_LIFE_GAMES)

                media = weighted_mean(hist_scores, weights)
                fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
                fattore_trend, _, _ = compute_trend_factor(
                    hist_scores, short_window=5, long_window=10, trend_intensity=TREND_INTENSITY)

                baseline = media * fattore_ct * fattore_trend
                reale = scores[i]
                residuo = reale - baseline

                match_date = dates[i].date().isoformat()
                out.append((team_slug, opponents[i], match_date, f"{ruolo}:{league}:{player_id}", residuo))

    print(f"  {ruolo.upper()}: {n_players_used} giocatori, {len(out)} punti con residuo")
    return out


def role_pair_key(id_a, id_b):
    ra = id_a.split(':', 1)[0]
    rb = id_b.split(':', 1)[0]
    return tuple(sorted((ra, rb)))


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = statistics.pstdev(xs)
    sy = statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def build_pair_values(records):
    """records: lista di (team_slug, opponent_slug, match_date, player_id,
    residuo). Ritorna dict role_pair -> [(res_a, res_b), ...] (coppie DELLA
    STESSA squadra) e n. partite/squadre."""
    groups = defaultdict(list)
    for team_slug, opponent_slug, match_date, player_id, residuo in records:
        groups[(team_slug, match_date)].append((player_id, residuo))

    pair_values = defaultdict(list)
    n_matches_with_pairs = 0
    teams_with_pairs = set()
    for (team_slug, match_date), rows in groups.items():
        if len(rows) < 2:
            continue
        n_matches_with_pairs += 1
        teams_with_pairs.add(team_slug)
        for (id_a, res_a), (id_b, res_b) in combinations(rows, 2):
            key = role_pair_key(id_a, id_b)
            pair_values[key].append((res_a, res_b))
            pair_values[('any', 'any')].append((res_a, res_b))
    return pair_values, n_matches_with_pairs, teams_with_pairs


def build_cross_team_pair_values(records):
    """records: stessa lista di build_pair_values. Ritorna dict role_pair ->
    [(res_gk_o_altro_ruolo_proprio, res_avversario), ...] SOLO per coppie di
    squadre AVVERSARIE nella stessa partita -- usato per verificare
    l'anti-sinergia GK-vs-attaccante-avversario gia' codificata a mano in
    `build_formazione_finale.py` (synergy_sort_key), che e' una relazione
    CROSS-team, diversa dalla sinergia same-team misurata da build_pair_values."""
    groups = defaultdict(list)  # (frozenset({team,opp}), data) -> [(team, role, residuo), ...]
    for team_slug, opponent_slug, match_date, player_id, residuo in records:
        if not opponent_slug:
            continue
        role = player_id.split(':', 1)[0]
        key = (frozenset((team_slug, opponent_slug)), match_date)
        groups[key].append((team_slug, role, residuo))

    pair_values = defaultdict(list)
    n_matches_with_pairs = 0
    for key, rows in groups.items():
        teams_present = {t for t, _, _ in rows}
        if len(teams_present) < 2:
            continue
        n_matches_with_pairs += 1
        for (team_a, role_a, res_a), (team_b, role_b, res_b) in combinations(rows, 2):
            if team_a == team_b:
                continue
            pair_key = tuple(sorted((role_a, role_b)))
            pair_values[pair_key].append((res_a, res_b))
    return pair_values, n_matches_with_pairs


def permutation_pvalues(records_by_role, observed, keys, n_perm=N_PERMUTATIONS,
                         pair_builder=lambda recs: build_pair_values(recs)[0]):
    """Shuffle SOLO i valori di residuo entro ciascun ruolo (fissi team/data/
    player), ricostruisce le coppie e ricalcola la correlazione per tutte le
    `keys` in un solo passaggio per permutazione (piu' efficiente che farlo
    key per key). Rompe l'associazione "chi ha giocato con chi" preservando
    marginali e struttura dei gruppi -- test dell'ipotesi nulla 'nessun
    effetto di partita reale'. p-value a due code per ciascuna key.
    `pair_builder` sceglie same-team (default) o cross-team (avversari)."""
    rng = random.Random(RANDOM_SEED)
    counts = {k: 0 for k in keys}
    for _ in range(n_perm):
        perm_records = []
        for ruolo, recs in records_by_role.items():
            residui = [r[4] for r in recs]
            rng.shuffle(residui)
            for (team_slug, opponent_slug, match_date, player_id, _), new_res in zip(recs, residui):
                perm_records.append((team_slug, opponent_slug, match_date, player_id, new_res))
        pair_values = pair_builder(perm_records)
        for key in keys:
            pairs = pair_values.get(key, [])
            if len(pairs) < 2:
                continue
            xs = [a for a, _ in pairs]
            ys = [b for _, b in pairs]
            r = pearson(xs, ys)
            if r is not None and abs(r) >= abs(observed[key]):
                counts[key] += 1
    return {k: (counts[k] + 1) / (n_perm + 1) for k in keys}


def split_half_check(records, key, label, pair_builder=lambda recs: build_pair_values(recs)[0]):
    """Ordina le partite (squadra, data) cronologicamente e ricalcola la
    correlazione separatamente su prima e seconda meta -- se il segno/ordine
    di grandezza regge in entrambe le meta', e' piu' probabile un effetto
    reale che rumore campionario."""
    match_dates = sorted({(team, d) for team, _, d, _, _ in records}, key=lambda t: t[1])
    if len(match_dates) < 10:
        return
    mid = len(match_dates) // 2
    first_set = set(match_dates[:mid])
    second_set = set(match_dates[mid:])
    first_records = [r for r in records if (r[0], r[2]) in first_set]
    second_records = [r for r in records if (r[0], r[2]) in second_set]
    pv1 = pair_builder(first_records)
    pv2 = pair_builder(second_records)
    p1, p2 = pv1.get(key, []), pv2.get(key, [])
    r1 = pearson([a for a, _ in p1], [b for _, b in p1]) if len(p1) >= 15 else None
    r2 = pearson([a for a, _ in p2], [b for _, b in p2]) if len(p2) >= 15 else None
    r1_str = f"{r1:+.3f} (n={len(p1)})" if r1 is not None else f"n/d (n={len(p1)})"
    r2_str = f"{r2:+.3f} (n={len(p2)})" if r2 is not None else f"n/d (n={len(p2)})"
    print(f"    split-half {label}: prima meta' {r1_str}  |  seconda meta' {r2_str}")


def main():
    print("Raccolta residui walk-forward per ruolo (baseline senza fattore avversario)...")
    records_by_role = {}
    all_residuals = []
    for ruolo in ROLES:
        recs = collect_residuals_for_role(ruolo)
        records_by_role[ruolo] = recs
        all_residuals.extend(recs)

    pair_values, n_matches_with_pairs, teams_with_pairs = build_pair_values(all_residuals)

    print(f"\nPartite (squadra, data) con 2+ giocatori cachati: {n_matches_with_pairs}")
    print(f"Squadre distinte coinvolte: {len(teams_with_pairs)}")

    print("\n=== Correlazione residui tra compagni di squadra, stessa partita ===")
    print(f"{'coppia ruoli':<14} {'n coppie':>10} {'corr Pearson':>14} {'p-value (perm.)':>16}")
    reportable_keys = [k for k in pair_values if len(pair_values[k]) >= MIN_PAIRS_FOR_REPORT]
    reportable_keys.sort(key=lambda k: -len(pair_values[k]))

    observed = {}
    for key in reportable_keys:
        pairs = pair_values[key]
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        r = pearson(xs, ys)
        if r is not None:
            observed[key] = r

    print(f"  (test di permutazione: {N_PERMUTATIONS} shuffle, un solo passaggio per tutte le coppie di ruoli)")
    pvalues = permutation_pvalues(records_by_role, observed, list(observed.keys()))

    results = {}
    for key in reportable_keys:
        pairs = pair_values[key]
        label = 'qualsiasi' if key == ('any', 'any') else '-'.join(key)
        if key not in observed:
            print(f"{label:<14} {len(pairs):>10} {'n/d (var=0)':>14} {'--':>16}")
            continue
        r = observed[key]
        pval = pvalues[key]
        sig = " *" if pval < 0.05 else ""
        print(f"{label:<14} {len(pairs):>10} {r:+.3f}{sig:<10} {pval:>10.4f}")
        results[key] = (r, pval)

    print("\n=== Stabilita' split-half (prima vs seconda meta' cronologica delle partite) ===")
    for key in reportable_keys:
        if key not in results:
            continue
        label = 'qualsiasi' if key == ('any', 'any') else '-'.join(key)
        print(f"  {label}:")
        split_half_check(all_residuals, key, label)

    print("\n(* = p<0.05 nel test di permutazione: la correlazione osservata e' piu' estrema "
          "del 95% di quelle ottenute mischiando casualmente i residui tra le partite, a parita' "
          "di marginali e struttura dei gruppi.)")

    # --- Cross-team: verifica diretta dell'anti-sinergia GK-vs-attaccante
    # avversario gia' codificata a mano in build_formazione_finale.py
    # (synergy_sort_key: ANTI_SYNERGY_PENALTY su MID/FWD della squadra
    # avversaria del GK scelto). Tutto quanto sopra e' SAME-team -- questa
    # e' un'ipotesi diversa e va misurata separatamente.
    cross_pair_values, n_cross_matches = build_cross_team_pair_values(all_residuals)
    print("\n\n=== Cross-team: GK vs ruoli di movimento della squadra AVVERSARIA, stessa partita ===")
    print("(verifica diretta dell'anti-sinergia GK-vs-attaccante-avversario in build_formazione_finale.py)")
    print(f"Partite con entrambe le squadre cachate: {n_cross_matches}")
    print(f"{'coppia ruoli':<14} {'n coppie':>10} {'corr Pearson':>14} {'p-value (perm.)':>16}")

    cross_reportable = [k for k in cross_pair_values if len(cross_pair_values[k]) >= MIN_PAIRS_FOR_REPORT]
    cross_reportable.sort(key=lambda k: -len(cross_pair_values[k]))

    cross_observed = {}
    for key in cross_reportable:
        pairs = cross_pair_values[key]
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        r = pearson(xs, ys)
        if r is not None:
            cross_observed[key] = r

    cross_builder = lambda recs: build_cross_team_pair_values(recs)[0]
    cross_pvalues = permutation_pvalues(records_by_role, cross_observed, list(cross_observed.keys()),
                                         pair_builder=cross_builder)

    cross_results = {}
    for key in cross_reportable:
        pairs = cross_pair_values[key]
        label = '-'.join(key)
        if key not in cross_observed:
            print(f"{label:<14} {len(pairs):>10} {'n/d (var=0)':>14} {'--':>16}")
            continue
        r = cross_observed[key]
        pval = cross_pvalues[key]
        sig = " *" if pval < 0.05 else ""
        print(f"{label:<14} {len(pairs):>10} {r:+.3f}{sig:<10} {pval:>10.4f}")
        cross_results[key] = (r, pval)

    print("\n=== Stabilita' split-half (cross-team) ===")
    for key in cross_reportable:
        if key not in cross_results:
            continue
        label = '-'.join(key)
        print(f"  {label}:")
        split_half_check(all_residuals, key, label, pair_builder=cross_builder)

    print("\nAttesa a priori: gk-fwd e gk-mid CROSS-team dovrebbero essere NEGATIVI se "
          "l'anti-sinergia codificata (un gol subito dal GK e' spesso un evento POSITIVO per "
          "l'attaccante avversario) e' un effetto reale e non solo intuizione.")


if __name__ == '__main__':
    main()
