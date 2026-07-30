"""In Season: quali coppie same-team, se correlate, cambiano davvero la
probabilita' di superare il bersaglio settimanale -- e con quale robustezza
al variare del bersaglio (30/07, richiesta esplicita utente: "il target si
alza ogni settimana, non e' fisso" -- niente numero singolo, si testa un
range realistico).

Estende estimate_threshold_win_probability_mc.py a TUTTE le 8 coppie
same-team misurate (non solo GK-DEF) e a un range di bersagli (300-450,
passo 30), per capire quali coppie vale la pena modellare e quanto la
conclusione regge al variare del target.

Metodo IDENTICO al file GK-DEF: Monte Carlo con punteggi REALI, coppie
correlate estratte da osservazioni vere (stessa squadra/data), captain
bonus In Season (+50%). Un solo lever alla volta: si isola l'effetto della
coppia testata, il resto della formazione resta indipendente (baseline
fissa) -- non e' un confronto tra formazioni diverse, solo "questa coppia
correlata vs decorrelata, a parita' di tutto il resto".

Uso: python formazione_mls/diagnostics/estimate_inseason_synergy_allpairs.py
"""
import random
import statistics
from collections import defaultdict

from estimate_threshold_win_probability_mc import load_players, flat_pool

N_TRIALS = 80_000
CAPTAIN_BONUS_INSEASON = 0.5
THRESHOLDS = (340, 360, 400, 420, 460)  # i 5 target reali In Season (progressione settimanale, dato utente 30/07)

PAIRS = [
    ('gk', 'def'), ('def', 'def'), ('fwd', 'mid'), ('gk', 'mid'),
    ('def', 'mid'), ('mid', 'mid'), ('fwd', 'fwd'), ('def', 'fwd'),
]


def build_paired_pool_general(players_a, players_b, same_role):
    """Coppie di punteggi REALI (stessa team_key/data). Se same_role=True
    (es. DEF-DEF), evita di accoppiare un giocatore con se stesso -- richiede
    che i due punteggi vengano da SLUG diversi nella stessa (team, data)."""
    by_key = defaultdict(list)  # (team_key, date) -> [(slug, score), ...]
    for fpath, team_key, obs, _ in players_a:
        for date, score in obs:
            by_key[(team_key, date)].append((fpath, score))
    pairs = []
    if same_role:
        for key, entries in by_key.items():
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    if entries[i][0] != entries[j][0]:
                        pairs.append((entries[i][1], entries[j][1]))
    else:
        by_key_b = defaultdict(list)
        for fpath, team_key, obs, _ in players_b:
            for date, score in obs:
                by_key_b[(team_key, date)].append((fpath, score))
        for key, entries_a in by_key.items():
            for fpath_a, score_a in entries_a:
                for fpath_b, score_b in by_key_b.get(key, []):
                    if fpath_a != fpath_b:
                        pairs.append((score_a, score_b))
    return pairs


def main():
    from estimate_threshold_win_probability_mc import TOP_FRACTION
    print(f"Carico pool 'forti' (top {TOP_FRACTION:.0%} per media storica) per ruolo...")
    pools = {r: load_players(r) for r in ('gk', 'def', 'mid', 'fwd')}
    for r, p in pools.items():
        print(f"  {r.upper()}: {len(p)} giocatori")
    flat = {r: flat_pool(pools[r]) for r in pools}

    # baseline: formazione GK+DEF+MID+FWD+MID(extra), indipendente, captain=FWD
    print(f"\n{N_TRIALS} trial per scenario, {len(THRESHOLDS)} soglie x {len(PAIRS)} coppie...\n")
    print(f"{'coppia':<12}" + "".join(f"{'T='+str(t):>10}" for t in THRESHOLDS))

    results_summary = []
    for role_a, role_b in PAIRS:
        same_role = role_a == role_b
        pairs_real = build_paired_pool_general(pools[role_a], pools[role_b], same_role)
        if len(pairs_real) < 30:
            print(f"{role_a}-{role_b:<8}  troppo poche coppie reali ({len(pairs_real)}), salto")
            continue

        # Formazione base: gk, def, mid, fwd(capitano), extra. extra e' un
        # secondo giocatore dello stesso ruolo di role_a se la coppia testata
        # e' same-role (es. def-def), altrimenti un mid generico indipendente.
        extra_role = role_a if same_role else 'mid'
        cap_mult = 1 + CAPTAIN_BONUS_INSEASON

        # CORREZIONE MEDIA (30/07, bug reale trovato su un test collegato,
        # estimate_inseason_combined_synergy.py): il pool di coppie reali
        # stessa-squadra/data puo' avere media DIVERSA dal pool flat (specie
        # per n piccoli) -- senza ricentrare, il confronto correlato/
        # decorrelato mischia "media diversa" con "correlazione", gonfiando
        # o sgonfiando il delta a seconda del segno dello scarto. Si ricentra
        # ogni pool sulla media del pool flat corrispondente prima di sommare.
        a_mean = statistics.mean(a for a, _ in pairs_real)
        b_mean = statistics.mean(b for _, b in pairs_real)
        a_shift = statistics.mean(flat[role_a]) - a_mean
        b_shift = statistics.mean(flat[role_b]) - b_mean

        def sample_corr():
            a_s, b_s = random.choice(pairs_real)
            a_s += a_shift
            b_s += b_shift
            vals = {r: random.choice(flat[r]) for r in ('gk', 'def', 'mid', 'fwd')}
            extra_val = random.choice(flat[extra_role])
            if same_role:
                vals[role_a] = a_s
                extra_val = b_s
            else:
                vals[role_a] = a_s
                vals[role_b] = b_s
            return vals['gk'] + vals['def'] + vals['mid'] + (vals['fwd'] * cap_mult) + extra_val

        def sample_decorr():
            vals = {r: random.choice(flat[r]) for r in ('gk', 'def', 'mid', 'fwd')}
            extra_val = random.choice(flat[extra_role])
            return vals['gk'] + vals['def'] + vals['mid'] + (vals['fwd'] * cap_mult) + extra_val

        totals_c = [sample_corr() for _ in range(N_TRIALS)]
        totals_d = [sample_decorr() for _ in range(N_TRIALS)]
        deltas = []
        equiv_points = []
        for t in THRESHOLDS:
            pc = sum(1 for x in totals_c if x > t) / N_TRIALS
            pd = sum(1 for x in totals_d if x > t) / N_TRIALS
            deltas.append((pc - pd) * 100)
            # punti equivalenti: quanto bisognerebbe alzare la media SENZA
            # sinergia per eguagliare la P(clear) CON sinergia, a questa soglia
            lo, hi = 0.0, 20.0
            for _ in range(20):
                mid = (lo + hi) / 2
                p = sum(1 for x in totals_d if x + mid > t) / N_TRIALS
                if p < pc:
                    lo = mid
                else:
                    hi = mid
            equiv_points.append((lo + hi) / 2)
        label = f"{role_a}-{role_b} (n={len(pairs_real)})"
        print(f"{label:<20}" + "".join(f"{d:>+9.2f}%" for d in deltas))
        results_summary.append((role_a, role_b, len(pairs_real), statistics.mean(equiv_points), equiv_points))

    print("\n=== Punti equivalenti (media SENZA sinergia necessaria per eguagliare CON, media sui 5 target) ===")
    for role_a, role_b, n, avg_pts, pts in sorted(results_summary, key=lambda r: -r[3]):
        pts_str = ", ".join(f"{p:.1f}" for p in pts)
        print(f"  {role_a}-{role_b:<6} (n={n:>5}): media={avg_pts:.2f} pt  [per soglia: {pts_str}]")


if __name__ == '__main__':
    main()
