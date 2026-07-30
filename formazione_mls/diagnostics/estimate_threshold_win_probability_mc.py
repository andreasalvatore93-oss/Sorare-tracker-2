"""Versione RAFFINATA (30/07) di estimate_threshold_win_probability.py:
Monte Carlo con dati REALI invece di un'approssimazione normale, e formazione
di giocatori FORTI (top per media) invece della media grezza di ruolo.

Perche' il modello normale del primo giro poteva essere impreciso: i
punteggi reali hanno un minimo a 0 e code lunghe a destra (eventi Poisson
rari, non simmetrici) -- proprio nella coda destra si decide se una
formazione supera la soglia premio. Qui invece di assumere una forma,
si CAMPIONA direttamente da punteggi reali osservati:
- Per la coppia correlata (GK-DEF), si estraggono le coppie di punteggi
  REALMENTE osservate nella STESSA partita/squadra (correlazione vera,
  qualunque sia la sua forma) -- stessa logica di pairing di
  measure_teammate_correlation.py ma su punteggi grezzi, non residui.
- Per i ruoli non correlati (MID, FWD, extra), si campiona indipendentemente
  dal pool di punteggi reali dei giocatori FORTI (top 25% per media),
  rappresentando cosa sceglierebbe davvero il tool.
Migliaia di trial Monte Carlo stimano P(totale > soglia) SENZA assumere
nessuna forma di distribuzione.

Uso: python formazione_mls/diagnostics/estimate_threshold_win_probability_mc.py
"""
import glob
import json
import random
import statistics
from collections import defaultdict

N_TRIALS = 200_000
CAPTAIN_BONUS_ARENA = 0.2
TOP_FRACTION = 0.60  # AMPLIATO 30/07 (richiesta esplicita utente, "allarga il campo": il
# 25% dava troppo poche osservazioni reali per coppia, campione sottile per decidere una
# modifica di produzione) -- top 60% per media storica, ancora sopra-mediano/realistico
# ma con molte piu' coppie reali osservate.


def load_players(role):
    """Ritorna lista di (slug, team_key, [(date, score), ...]) per giocatori
    con storico sufficiente, ordinati per media storica decrescente."""
    files = glob.glob(f'formazione_*/output/*_{role}_all/.cache/*_detail_cache.json')
    players = []
    for f in files:
        try:
            cache = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        nodes = [v for v in cache.values() if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
        if len(nodes) < 8:
            continue
        # squadra piu' frequente (stesso criterio di measure_teammate_correlation.py)
        counts = defaultdict(int)
        for v in nodes:
            for side in ('homeTeam', 'awayTeam'):
                s = (v['anyGame'].get(side) or {}).get('slug')
                if s:
                    counts[s] += 1
        if not counts:
            continue
        team = max(counts, key=counts.get)
        league = f.split('formazione_', 1)[1].split('/', 1)[0].split('\\', 1)[0]
        team_key = f"{league}:{team}"
        obs = []
        for v in nodes:
            d = v['anyGame'].get('date')
            s = v.get('score', 0.0)
            if d:
                obs.append((d[:10], s))
        if len(obs) < 8:
            continue
        mean_score = statistics.mean(s for _, s in obs)
        players.append((f, team_key, obs, mean_score))
    players.sort(key=lambda p: -p[3])
    cutoff = max(1, int(len(players) * TOP_FRACTION))
    return players[:cutoff]


def build_paired_pool(players_a, players_b):
    """Coppie di punteggi REALI osservati nella stessa (team_key, data) tra
    un giocatore del pool A e uno del pool B (es. GK e DEF forti)."""
    by_key_a = defaultdict(list)
    for _, team_key, obs, _ in players_a:
        for date, score in obs:
            by_key_a[(team_key, date)].append(score)
    pairs = []
    for _, team_key, obs, _ in players_b:
        for date, score_b in obs:
            for score_a in by_key_a.get((team_key, date), []):
                pairs.append((score_a, score_b))
    return pairs


def flat_pool(players):
    return [s for _, _, obs, _ in players for _, s in obs]


def p_win_mc(sample_fn, threshold, n_trials=N_TRIALS):
    wins = 0
    totals = []
    for _ in range(n_trials):
        t = sample_fn()
        totals.append(t)
        if t > threshold:
            wins += 1
    return wins / n_trials, totals


def main():
    print(f"Carico pool 'forti' (top {TOP_FRACTION:.0%} per media storica) per ruolo...")
    pools = {}
    for role in ('gk', 'def', 'mid', 'fwd'):
        pools[role] = load_players(role)
        print(f"  {role.upper()}: {len(pools[role])} giocatori nel pool forte")

    gk_def_pairs = build_paired_pool(pools['gk'], pools['def'])
    print(f"\nCoppie GK-DEF stessa squadra/data osservate REALMENTE: {len(gk_def_pairs)}")
    if len(gk_def_pairs) < 30:
        print("Troppo poche coppie reali per un Monte Carlo affidabile su GK-DEF -- fermo qui.")
        return

    mid_pool = flat_pool(pools['mid'])
    fwd_pool = flat_pool(pools['fwd'])
    gk_pool = flat_pool(pools['gk'])
    def_pool = flat_pool(pools['def'])

    def sample_correlated():
        gk_s, def_s = random.choice(gk_def_pairs)
        mid_s = random.choice(mid_pool)
        fwd_s = random.choice(fwd_pool) * (1 + CAPTAIN_BONUS_ARENA)  # capitano = FWD
        mid2_s = random.choice(mid_pool)
        return gk_s + def_s + mid_s + fwd_s + mid2_s

    def sample_decorrelated():
        gk_s = random.choice(gk_pool)
        def_s = random.choice(def_pool)
        mid_s = random.choice(mid_pool)
        fwd_s = random.choice(fwd_pool) * (1 + CAPTAIN_BONUS_ARENA)
        mid2_s = random.choice(mid_pool)
        return gk_s + def_s + mid_s + fwd_s + mid2_s

    thresholds = [270, 290, 310]
    print(f"\n{N_TRIALS} trial Monte Carlo per scenario...\n")

    p_corr = {}
    p_decorr = {}
    for t in thresholds:
        pc, totals_c = p_win_mc(sample_correlated, t, N_TRIALS)
        pd, totals_d = p_win_mc(sample_decorrelated, t, N_TRIALS)
        p_corr[t] = pc
        p_decorr[t] = pd
        print(f"Soglia {t}: P(vincere) CON correlazione reale GK-DEF = {pc*100:.2f}%   "
              f"SENZA (decorrelato) = {pd*100:.2f}%   delta = {(pc-pd)*100:+.2f}pt")

    print(f"\nMedia totale campionata: correlato={statistics.mean(totals_c):.1f}  "
          f"decorrelato={statistics.mean(totals_d):.1f}")
    print(f"Dev.std totale campionata: correlato={statistics.stdev(totals_c):.1f}  "
          f"decorrelato={statistics.stdev(totals_d):.1f}")

    # Punti equivalenti alla soglia 290 (bisezione su un bonus additivo al pool decorrelato)
    target_p = p_corr[290]
    lo, hi = 0.0, 40.0
    for _ in range(25):
        mid_bonus = (lo + hi) / 2
        p, _ = p_win_mc(lambda: sample_decorrelated() + mid_bonus, 290, 20_000)
        if p < target_p:
            lo = mid_bonus
        else:
            hi = mid_bonus
    print(f"\nPer eguagliare (soglia 290) la P(vincere) CON sinergia GK-DEF reale, servirebbero "
          f"SENZA sinergia +{(lo+hi)/2:.2f} punti di media totale attesa.")
    print("Confronta con il bonus attuale in produzione per GK-DEF: 7 punti.")


if __name__ == '__main__':
    main()
