"""In Season: formazione realistica con DUE gruppi-squadra scelti per
catturare solo le coppie "buone" trovate da estimate_inseason_synergy_
allpairs.py (gk-def, fwd-mid, mid-mid, def-mid, def-def positive; gk-mid
trascurabile; def-fwd/fwd-fwd(a bersagli bassi) negative).

Squadra A: GK + DEF (cattura gk-def, +).
Squadra B: MID + FWD(capitano) + MID2 (cattura fwd-mid x2 e mid-mid, le due
coppie piu' forti in assoluto). DEF resta isolato da FWD (evita def-fwd,
negativa su tutti i target) e da MID2 (perde il bonus def-mid, ma e' il
piu' debole delle "buone" -- scambio ragionevole per una struttura a 2
squadre semplice, realizzabile con solo 2 squadre coinvolte in tutta la
formazione).

Confronta 3 scenari sui 5 target reali (340/360/400/420/460):
  A) BASE: tutti indipendenti (nessuna sinergia, comportamento attuale)
  B) SMART: 2 gruppi-squadra come sopra (GK+DEF, MID+FWD+MID2)
  C) PEGGIORE possibile: tutti e 5 sulla stessa squadra (include anche le
     coppie dannose def-fwd/gk-mid) -- per mostrare che "impilare tutto"
     NON e' la strategia giusta.

Uso: python formazione_mls/diagnostics/estimate_inseason_combined_synergy.py
"""
import random
import statistics
from collections import defaultdict

from estimate_threshold_win_probability_mc import load_players, build_paired_pool, flat_pool

N_TRIALS = 150_000
CAPTAIN_BONUS_INSEASON = 0.5
THRESHOLDS = (340, 360, 400, 420, 460)


def build_triples(pool_mid, pool_fwd):
    """(MID, FWD, MID2) reali, stessa squadra/data, MID != MID2."""
    by_key = defaultdict(list)
    for fpath, team_key, obs, _ in pool_mid:
        for date, score in obs:
            by_key[(team_key, date)].append((fpath, score))
    fwd_by_key = defaultdict(list)
    for fpath, team_key, obs, _ in pool_fwd:
        for date, score in obs:
            fwd_by_key[(team_key, date)].append((fpath, score))
    triples = []
    for key, mids in by_key.items():
        fwds = fwd_by_key.get(key, [])
        if not fwds or len(mids) < 2:
            continue
        for i in range(len(mids)):
            for j in range(i + 1, len(mids)):
                for fwd_fpath, fwd_score in fwds:
                    triples.append((mids[i][1], fwd_score, mids[j][1]))
    return triples


def main():
    print("Carico pool 'forti' per ruolo...")
    pools = {r: load_players(r) for r in ('gk', 'def', 'mid', 'fwd')}
    for r, p in pools.items():
        print(f"  {r.upper()}: {len(p)} giocatori")

    gk_def_pairs = build_paired_pool(pools['gk'], pools['def'])
    mid_fwd_mid_triples = build_triples(pools['mid'], pools['fwd'])
    print(f"\nCoppie reali GK-DEF: {len(gk_def_pairs)}")
    print(f"Triple reali MID-FWD-MID2: {len(mid_fwd_mid_triples)}")

    flat = {r: flat_pool(pools[r]) for r in pools}
    cap = 1 + CAPTAIN_BONUS_INSEASON

    def sample_base():
        gk = random.choice(flat['gk'])
        d = random.choice(flat['def'])
        m = random.choice(flat['mid'])
        f = random.choice(flat['fwd']) * cap
        m2 = random.choice(flat['mid'])
        return gk + d + m + f + m2

    # CORREZIONE (30/07, bug reale trovato): il pool di triple reali MID-FWD-
    # MID2 e' piccolo (175 combinazioni, poche partite indipendenti dietro) e
    # ha una media DIVERSA dal pool generale (mid1 +5.7, fwd +2.4) -- non e'
    # correlazione vera, e' rumore campionario. Senza correggerlo, SMART
    # sembrava vincere anche solo perche' "in media" piu' forte, non perche'
    # piu' sinergico. Si ricentra ogni pool sulla stessa media del pool
    # flat corrispondente PRIMA di sommare, cosi' il confronto isola SOLO
    # l'effetto della correlazione (stessa media attesa in entrambi gli
    # scenari), non un mix di media+correlazione.
    import statistics as _st
    _gk_pair_mean = _st.mean(a for a, b in gk_def_pairs)
    _def_pair_mean = _st.mean(b for a, b in gk_def_pairs)
    _gk_shift = _st.mean(flat['gk']) - _gk_pair_mean
    _def_shift = _st.mean(flat['def']) - _def_pair_mean
    _mid1_mean = _st.mean(t[0] for t in mid_fwd_mid_triples)
    _fwd_t_mean = _st.mean(t[1] for t in mid_fwd_mid_triples)
    _mid2_mean = _st.mean(t[2] for t in mid_fwd_mid_triples)
    _mid1_shift = _st.mean(flat['mid']) - _mid1_mean
    _fwd_t_shift = _st.mean(flat['fwd']) - _fwd_t_mean
    _mid2_shift = _st.mean(flat['mid']) - _mid2_mean
    print(f"\nCorrezione media applicata: GK{_gk_shift:+.1f} DEF{_def_shift:+.1f} "
          f"MID1{_mid1_shift:+.1f} FWD{_fwd_t_shift:+.1f} MID2{_mid2_shift:+.1f}")

    def sample_smart():
        gk_s, def_s = random.choice(gk_def_pairs)
        m_s, f_s, m2_s = random.choice(mid_fwd_mid_triples)
        gk_s += _gk_shift
        def_s += _def_shift
        m_s += _mid1_shift
        f_s += _fwd_t_shift
        m2_s += _mid2_shift
        return gk_s + def_s + m_s + (f_s * cap) + m2_s

    # Scenario C: tutti e 5 stessa squadra -- approssimato incollando insieme
    # la coppia GK-DEF reale e la tripla MID-FWD-MID2 reale (non sono la
    # STESSA squadra/data tra loro, quindi non cattura la correlazione
    # GK/DEF-vs-MID/FWD/MID2, ma include comunque TUTTE le coppie dannose
    # (def-fwd, gk-mid) che una formazione mono-squadra avrebbe -- limite
    # dei dati disponibili (troppo poche formazioni intere reali, 63, per
    # un pool 5-way diretto). Sottostima l'effetto ma resta indicativo.
    def_fwd_pairs = build_paired_pool(pools['def'], pools['fwd'])
    gk_mid_pairs = build_paired_pool(pools['gk'], pools['mid'])

    def sample_allsame():
        gk_s, def_s = random.choice(gk_def_pairs)
        _, fwd_s = random.choice(def_fwd_pairs)  # fwd coerente col def scelto sopra, approssimato
        _, mid_s = random.choice(gk_mid_pairs)
        m2_s = random.choice(flat['mid'])
        return gk_s + def_s + mid_s + (fwd_s * cap) + m2_s

    print(f"\n{N_TRIALS} trial per scenario...\n")
    print(f"{'scenario':<10}" + "".join(f"{'T='+str(t):>10}" for t in THRESHOLDS))

    scenarios = [('BASE', sample_base), ('SMART', sample_smart), ('ALLSAME', sample_allsame)]
    results = {}
    for name, fn in scenarios:
        totals = [fn() for _ in range(N_TRIALS)]
        results[name] = totals
        print(f"media={statistics.mean(totals):.1f} std={statistics.stdev(totals):.1f}  ({name})")

    print()
    for name, _ in scenarios:
        totals = results[name]
        row = "".join(f"{sum(1 for x in totals if x > t)/N_TRIALS*100:>9.2f}%" for t in THRESHOLDS)
        print(f"{name:<10}{row}")

    print("\nDelta SMART vs BASE (punti percentuali di probabilita' in piu'):")
    for t in THRESHOLDS:
        pb = sum(1 for x in results['BASE'] if x > t) / N_TRIALS
        ps = sum(1 for x in results['SMART'] if x > t) / N_TRIALS
        print(f"  T={t}: {(ps-pb)*100:+.2f}pt")


if __name__ == '__main__':
    main()
