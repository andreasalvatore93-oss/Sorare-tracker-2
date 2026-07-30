"""Modello dedicato bonus sinergia Arena/All Stars (30/07, richiesta esplicita
utente): invece di scalare la correlazione misurata per una costante a naso
(x20, vedi SAME_TEAM_SYNERGY_BONUS_BY_PAIR in build_formazione_finale.py),
stima DIRETTAMENTE quanto la correlazione tra compagni di squadra cambia la
PROBABILITA' di superare la soglia premio reale.

Dati di ancoraggio forniti dall'utente (screenshot/classifiche reali, 30/07):
- Arena: top 3 di 10 avversari, NESSUN bonus tranne capitano (+20%, non +50%
  come In Season/All Stars -- gia' corretto in CAPTAIN_BONUS_BY_TYPE). Soglia
  osservata: 270-310 punti circa (rumorosa, dipende dai 9 avversari).
- Under23/All Stars: soglia premio minimo = NUMERO FISSO di posti (non
  percentuale) -- 1500/2807 (296pt), 1500/3363 (354pt), 3000/19428 (489pt).

Metodo: la somma di N giocatori (media attesa nota, deviazione standard
individuale nota da weighted_stddev) ha:
  media_totale = somma delle medie
  varianza_totale = somma delle varianze + 2 * somma delle covarianze
  covarianza(i,j) = correlazione(ruolo_i,ruolo_j) * std_i * std_j
Approssimando la somma come normale (5 termini, nessuno dominante -- CLT
ragionevole anche se i singoli punteggi non sono normali), si stima
P(totale > soglia) col CDF normale. Confrontando la stessa formazione con e
senza le correlazioni same-team misurate, si vede quanto VALE realmente la
sinergia in termini di probabilita' di premio -- e quanti punti di media
servirebbero per ottenere lo stesso guadagno, cioe' il bonus "corretto".

NON sostituisce SAME_TEAM_SYNERGY_BONUS_BY_PAIR (che resta il meccanismo in
produzione) -- e' il primo passo per capire se/quanto vale la pena rifarlo
con questo criterio invece di "correlazione x20".
"""
import glob
import json
import math
import statistics


def role_stats(role):
    files = glob.glob(f'formazione_*/output/*_{role}_all/.cache/*_detail_cache.json')
    means, stds = [], []
    for f in files:
        try:
            cache = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        nodes = [v for v in cache.values() if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
        if len(nodes) < 8:
            continue
        scores = [v.get('score', 0.0) for v in nodes]
        means.append(statistics.mean(scores))
        stds.append(statistics.stdev(scores))
    return statistics.mean(means), statistics.mean(stds), len(means)


def normal_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_win(mean_total, std_total, threshold):
    if std_total <= 0:
        return 1.0 if mean_total > threshold else 0.0
    z = (mean_total - threshold) / std_total
    return 1 - normal_cdf(-z)  # P(X > threshold) = 1 - CDF((threshold-mean)/std) = CDF(z)


# Correlazioni same-team misurate 30/07 (measure_teammate_correlation.py,
# 30.068 coppie) -- stesse usate per SAME_TEAM_SYNERGY_BONUS_BY_PAIR.
CORR = {
    frozenset(('GK', 'DEF')): 0.333,
    frozenset(('DEF', 'DEF')): 0.219,
    frozenset(('FWD', 'MID')): 0.135,
    frozenset(('GK', 'MID')): 0.107,
    frozenset(('DEF', 'MID')): 0.094,
    frozenset(('MID', 'MID')): 0.108,
    frozenset(('FWD', 'FWD')): 0.223,
    frozenset(('DEF', 'FWD')): 0.060,
}

CAPTAIN_BONUS_ARENA = 0.2


def team_total(players, same_team_pairs):
    """players: lista di (ruolo, media, std). same_team_pairs: set di indici
    (i,j) i<j che sono nella STESSA squadra (quindi la correlazione si
    applica). Ritorna (media_totale, std_totale)."""
    mean_total = sum(p[1] for p in players)
    var_total = sum(p[2] ** 2 for p in players)
    for i, j in same_team_pairs:
        role_i, role_j = players[i][0], players[j][0]
        r = CORR.get(frozenset((role_i, role_j)), 0.0)
        cov = r * players[i][2] * players[j][2]
        var_total += 2 * cov
    return mean_total, math.sqrt(var_total)


def apply_captain(players, idx, bonus_pct):
    p = list(players)
    role, mean, std = p[idx]
    p[idx] = (role, mean * (1 + bonus_pct), std * (1 + bonus_pct))
    return p


def main():
    stats = {}
    for role in ('gk', 'def', 'mid', 'fwd'):
        m, s, n = role_stats(role)
        stats[role.upper()] = (m, s)
        print(f"{role.upper()}: n={n}  media={m:.1f}  std={s:.1f}")
    print()

    # Formazione tipo Arena: GK, DEF, MID, FWD, EXTRA (extra = un altro
    # movimento, qui preso MID per semplicita' -- non cambia la sostanza).
    base_players = [
        ('GK', *stats['GK']),
        ('DEF', *stats['DEF']),
        ('MID', *stats['MID']),
        ('FWD', *stats['FWD']),
        ('MID', *stats['MID']),
    ]

    # Capitano: il piu' alto per media (qui FWD/MID pari, prendo indice 3=FWD)
    cap_idx = max(range(len(base_players)), key=lambda i: base_players[i][1])
    players = apply_captain(base_players, cap_idx, CAPTAIN_BONUS_ARENA)

    thresholds = [270, 290, 310]

    print("=== Scenario A: NESSUNA correlazione (tutti in squadre diverse) ===")
    mean_a, std_a = team_total(players, same_team_pairs=set())
    print(f"media totale={mean_a:.1f}  std totale={std_a:.1f}")
    for t in thresholds:
        print(f"  P(vincere Arena, soglia {t}) = {p_win(mean_a, std_a, t)*100:.1f}%")
    print()

    print("=== Scenario B: GK+DEF stessa squadra (r=0.333, la piu' forte) ===")
    mean_b, std_b = team_total(players, same_team_pairs={(0, 1)})
    print(f"media totale={mean_b:.1f}  std totale={std_b:.1f}")
    for t in thresholds:
        pa = p_win(mean_a, std_a, t)
        pb = p_win(mean_b, std_b, t)
        print(f"  P(vincere, soglia {t}) = {pb*100:.1f}%  (vs {pa*100:.1f}% senza sinergia, delta {pb*100-pa*100:+.1f}pt di probabilita')")
    print()

    print("=== Scenario C: tutti e 5 stessa squadra (caso limite, difficilmente ammesso da anti-stack) ===")
    all_pairs = {(i, j) for i in range(len(players)) for j in range(i + 1, len(players))}
    mean_c, std_c = team_total(players, same_team_pairs=all_pairs)
    print(f"media totale={mean_c:.1f}  std totale={std_c:.1f}")
    for t in thresholds:
        pa = p_win(mean_a, std_a, t)
        pc = p_win(mean_c, std_c, t)
        print(f"  P(vincere, soglia {t}) = {pc*100:.1f}%  (vs {pa*100:.1f}% senza sinergia, delta {pc*100-pa*100:+.1f}pt di probabilita')")
    print()

    # Traduzione in punti equivalenti: quanta media in PIU' servirebbe nello
    # scenario A (senza sinergia) per ottenere la STESSA P(vincere) dello
    # scenario B, a parita' di soglia 290 (via bisezione).
    target_p = p_win(mean_b, std_b, 290)
    lo, hi = 0.0, 60.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if p_win(mean_a + mid, std_a, 290) < target_p:
            lo = mid
        else:
            hi = mid
    print(f"Per eguagliare, SENZA sinergia, la P(vincere soglia 290) dello scenario B (GK-DEF stessa "
          f"squadra), servirebbero +{(lo+hi)/2:.2f} punti di media totale attesa.")
    print("Questo e' il valore 'giusto' del bonus GK-DEF per Arena a questa soglia -- confrontalo con "
          "il bonus attuale in produzione (7, su SAME_TEAM_SYNERGY_BONUS_BY_PAIR).")


if __name__ == '__main__':
    main()
