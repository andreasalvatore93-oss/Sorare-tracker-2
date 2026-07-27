"""
Validate Level Score via TASSO DI EVENTI (26/07, sesta sessione)

Domanda diversa da quella gia' testata (e SCARTATA) in
validate_level_score_decomposition.py: qui NON si ri-calibra un
half_life/trend_intensity separato per il pezzo level_score. Si usa invece
la regola ESATTA e VALIDATA netto->livello (vedi docs/RIASSUNTO_EVOLUZIONE_
MODELLO_PREDITTIVO.md sezione 11) per stimare, walk-forward, un TASSO
storico di eventi decisivi (quante volte per partita il giocatore genera
un evento POSITIVE_DECISIVE_STAT / NEGATIVE_DECISIVE_STAT, pesato con lo
stesso half_life gia' in produzione, NESSUNA ri-taratura), e da quel tasso
calcola il VALORE ATTESO della distribuzione CATEGORIALE di level_score
(non una media continua dei level_score gia' osservati -- quella e'
esattamente cio' che il tentativo precedente ha gia' mostrato essere
nullo/rumoroso).

Meccanismo:
1. Per ogni partita storica: netto = sum(statValue righe
   POSITIVE_DECISIVE_STAT) - sum(statValue righe NEGATIVE_DECISIVE_STAT).
   Verificato che level_score reale = tabella(netto) su tutte le partite in
   cache (Confronto preliminare, sezione 1 dello script).
2. Walk-forward: lambda_pos = media pesata (pesi esponenziali, stesso
   HALF_LIFE_GAMES di produzione, NESSUNA ri-taratura) della somma
   POSITIVE_DECISIVE_STAT per partita; lambda_neg idem per la somma
   NEGATIVE_DECISIVE_STAT. Questi due numeri sono un vero "tasso di eventi
   per partita" (gol+assist+... per partita, cartellini+errori per
   partita), non una media di punteggi gia' quantizzati.
3. Si modella il conteggio eventi positivi/negativi della prossima partita
   come Poisson(lambda_pos) / Poisson(lambda_neg) indipendenti (assunzione
   standard per conteggi rari discreti) e si convolve per ottenere la
   distribuzione di probabilita' P(netto=k) = P(pos-neg=k). Da qui:
   level_score_atteso = sum_k P(netto=k) * tabella(clamp(k, -2, 5))
   -- il vero valore atteso della variabile categoriale, che differisce da
   tabella(E[netto]) proprio a causa della non linearita' della tabella
   (salto grande 35->60 vs scalini da 10) -- e differisce anche dalla media
   pesata dei level_score storici gia' osservati, perche' il modello
   Poisson smussa la distribuzione empirica (rilevante su storici corti,
   MIN_HISTORY=6-9 partite, dove la distribuzione osservata e' un pugno di
   0 e uno-due eventi isolati).
4. Floor: applicato SOLO come variante diagnostica separata (vedi sotto) --
   la regola reale del floor opera su un valore REALIZZATO, non su un
   valore atteso continuo; qui si testa se max(level_score_atteso,
   level_score_atteso+granulare_atteso) come proxy migliora o peggiora il
   MAE totale, senza pretendere che sia la formulazione "corretta".

Confronto A: MAE isolato di level_score_atteso vs level_score REALE.
Confronto B (quello che conta): sostituendo nella formula attuale il pezzo
"level_score implicito nella media generica" con level_score_atteso (il
resto -- granulare_atteso via weighted_mean con lo stesso half_life/trend
di produzione, fattore_casa_trasferta sul totale -- resta come oggi), il
MAE TOTALE migliora o peggiora rispetto al baseline in produzione (media
pesata unica sul totale)?

Zero nuove chiamate API: solo le cache .cache/*_detail_cache.json gia' su
disco (stesso dato di inspect_granular_weights.py).

Uso: python formazione_mls/diagnostics/validate_level_score_event_rate.py
"""
import os
import sys
import json
import glob
import math
import statistics
import importlib
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
K_MAX = 6  # troncamento Poisson: massa residua P(X>=K_MAX) accumulata su K_MAX

MODULE_BY_ROLE = {
    'gk': 'formazione_mls.predict.test_gk',
    'def': 'formazione_mls.predict.test_def',
    'mid': 'formazione_mls.predict.test_mid',
    'fwd': 'formazione_mls.predict.test_mls_fwd_all',
}

# 27/07 notte: esteso da MLS-only a tutti e 6 i campionati (stesso motivo
# delle altre reindagini di stasera -- campione piu' ampio, stessa cache
# gia' su disco, nessuna nuova query). I moduli funzione (exponential_
# weights/weighted_mean/ecc.) restano presi da MLS -- logica identica in
# tutti i cloni, solo la CACHE cambia per lega.
LEAGUE_CACHE_TPL = {
    'mls': 'formazione_mls/output/mls_{ruolo}_calibration/.cache',
    'kleague': 'formazione_kleague/output/kleague_{ruolo}_calibration/.cache',
    'portogallo': 'formazione_portogallo/output/portogallo_{ruolo}_all/.cache',
    'austria': 'formazione_austria/output/austria_{ruolo}_all/.cache',
    'scozia': 'formazione_scozia/output/scozia_{ruolo}_all/.cache',
    'croazia': 'formazione_croazia/output/croazia_{ruolo}_all/.cache',
}


# ---------------------------------------------------------------------------
# Tabella netto -> level_score (REGOLA VALIDATA, sezione 11 del riassunto)
# ---------------------------------------------------------------------------

LEVEL_TABLE = {-2: 5, -1: 15, 0: 35, 1: 60, 2: 70, 3: 80, 4: 90, 5: 100}


def netto_to_level(netto):
    k = max(-2, min(5, round(netto)))
    return LEVEL_TABLE[k]


# ---------------------------------------------------------------------------
# Estrazione dati dalle cache
# ---------------------------------------------------------------------------

def player_team_slug(games):
    team_counts = defaultdict(int)
    for g in games:
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    return max(team_counts, key=team_counts.get) if team_counts else None


def extract_level_score(detailed_score):
    for row in detailed_score or []:
        if row.get('stat') == 'level_score':
            return row.get('totalScore') or 0.0
    return 0.0


def extract_netto(detailed_score):
    """netto = somma statValue righe POSITIVE_DECISIVE_STAT meno somma
    statValue righe NEGATIVE_DECISIVE_STAT. Ritorna anche i due addendi
    separati (pos_sum, neg_sum) per il modello a tasso di eventi."""
    pos_sum, neg_sum = 0.0, 0.0
    for row in detailed_score or []:
        cat = row.get('category')
        val = row.get('statValue') or 0.0
        if cat == 'POSITIVE_DECISIVE_STAT':
            pos_sum += val
        elif cat == 'NEGATIVE_DECISIVE_STAT':
            neg_sum += val
    return pos_sum, neg_sum


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
        scores, level_scores, is_home_flags = [], [], []
        pos_sums, neg_sums, nettos = [], [], []
        for e in entries:
            g = e['anyGame']
            home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
            if home.get('slug') == team_slug:
                is_home = True
            elif away.get('slug') == team_slug:
                is_home = False
            else:
                continue
            total = e.get('score') or 0.0
            detail = e.get('detailedScore')
            lvl = extract_level_score(detail)
            pos_sum, neg_sum = extract_netto(detail)
            scores.append(total)
            level_scores.append(lvl)
            is_home_flags.append(is_home)
            pos_sums.append(pos_sum)
            neg_sums.append(neg_sum)
            nettos.append(pos_sum - neg_sum)
        if len(scores) < MIN_HISTORY + 3:
            continue
        players.append({
            'scores': scores, 'level_scores': level_scores, 'is_home_flags': is_home_flags,
            'pos_sums': pos_sums, 'neg_sums': neg_sums, 'nettos': nettos,
        })
    return players


# ---------------------------------------------------------------------------
# Sezione 1: verifica della regola netto -> level_score sui dati reali
# ---------------------------------------------------------------------------

def check_rule(players):
    total, exact = 0, 0
    mismatches = []
    for p in players:
        for netto, lvl in zip(p['nettos'], p['level_scores']):
            total += 1
            predicted = netto_to_level(netto)
            if abs(predicted - lvl) < 1e-6:
                exact += 1
            else:
                mismatches.append((netto, lvl, predicted))
    pct = exact / total * 100 if total else 0.0
    return total, exact, pct, mismatches


# ---------------------------------------------------------------------------
# Sezione 2: modello a tasso di eventi (Poisson pos/neg) walk-forward
# ---------------------------------------------------------------------------

def exponential_weights_local(n, half_life):
    decay = math.log(2) / half_life
    return [math.exp(-decay * (n - 1 - i)) for i in range(n)]


def weighted_mean_local(values, weights):
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_w


def poisson_pmf_truncated(lam, k_max):
    """Distribuzione Poisson(lam) troncata a k_max: la massa residua
    P(X>=k_max) viene accumulata sull'ultimo bin, cosi' la somma resta 1."""
    if lam <= 0:
        probs = [0.0] * (k_max + 1)
        probs[0] = 1.0
        return probs
    probs = []
    cum = 0.0
    for k in range(k_max):
        p = math.exp(-lam) * (lam ** k) / math.factorial(k)
        probs.append(p)
        cum += p
    probs.append(max(0.0, 1.0 - cum))
    return probs


def expected_level_from_rates(lambda_pos, lambda_neg):
    """Convolve le due Poisson troncate (positivi/negativi) e calcola il
    valore atteso di level_score sulla distribuzione risultante di netto."""
    probs_pos = poisson_pmf_truncated(lambda_pos, K_MAX)
    probs_neg = poisson_pmf_truncated(lambda_neg, K_MAX)
    expected = 0.0
    for i, pp in enumerate(probs_pos):
        if pp == 0.0:
            continue
        for j, pn in enumerate(probs_neg):
            if pn == 0.0:
                continue
            netto_k = i - j
            expected += pp * pn * netto_to_level(netto_k)
    return expected


def confronto_a(players, half_life):
    """MAE isolato: level_score_atteso (tasso eventi) vs level_score REALE."""
    errori = []
    for p in players:
        pos_sums, neg_sums, level_scores = p['pos_sums'], p['neg_sums'], p['level_scores']
        n = len(level_scores)
        for i in range(MIN_HISTORY, n):
            weights = exponential_weights_local(i, half_life)
            lambda_pos = weighted_mean_local(pos_sums[:i], weights)
            lambda_neg = weighted_mean_local(neg_sums[:i], weights)
            atteso = expected_level_from_rates(lambda_pos, lambda_neg)
            errori.append(level_scores[i] - atteso)
    return statistics.mean(abs(e) for e in errori), len(errori)


def mae_baseline_totale(players, exponential_weights, weighted_mean, compute_split_factor,
                         compute_trend_factor, half_life, trend_intensity):
    """Baseline attuale in produzione: media pesata unica sul punteggio totale."""
    errori = []
    for p in players:
        scores, is_home_flags = p['scores'], p['is_home_flags']
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            weights = exponential_weights(i, half_life)
            media = weighted_mean(hist_scores, weights)
            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            fattore_trend, _, _ = compute_trend_factor(
                hist_scores, short_window=5, long_window=10, trend_intensity=trend_intensity)
            pred = media * fattore_ct * fattore_trend
            errori.append(scores[i] - pred)
    return statistics.mean(abs(e) for e in errori), len(errori)


def confronto_b(players, exponential_weights, weighted_mean, compute_split_factor,
                 compute_trend_factor, half_life, trend_intensity, apply_floor=False):
    """Sostituisce il pezzo level_score (implicito nella media generica) con
    la stima a tasso di eventi; il granulare resta previsto con la stessa
    media pesata esponenziale/trend gia' in produzione (NESSUNA ri-taratura).
    Un solo fattore casa/trasferta applicato al totale, come oggi."""
    errori = []
    for p in players:
        scores = p['scores']
        level_scores = p['level_scores']
        is_home_flags = p['is_home_flags']
        pos_sums, neg_sums = p['pos_sums'], p['neg_sums']
        gran_scores = [s - l for s, l in zip(scores, level_scores)]
        n = len(scores)
        for i in range(MIN_HISTORY, n):
            hist_scores = scores[:i]
            hist_home = is_home_flags[:i]
            hist_gran = gran_scores[:i]

            weights = exponential_weights(i, half_life)
            lambda_pos = weighted_mean_local(pos_sums[:i], weights)
            lambda_neg = weighted_mean_local(neg_sums[:i], weights)
            level_atteso = expected_level_from_rates(lambda_pos, lambda_neg)

            gran_atteso = weighted_mean(hist_gran, weights)
            trend_gran, _, _ = compute_trend_factor(
                hist_gran, short_window=5, long_window=10, trend_intensity=trend_intensity)

            fattore_ct = compute_split_factor(hist_scores, hist_home, is_home_flags[i])
            pred_raw = level_atteso + gran_atteso * trend_gran
            pred = pred_raw * fattore_ct

            if apply_floor and level_atteso >= 60:
                pred = max(level_atteso, pred)

            errori.append(scores[i] - pred)
    return statistics.mean(abs(e) for e in errori), len(errori)


def run_role(ruolo):
    mod = importlib.import_module(MODULE_BY_ROLE[ruolo])
    exponential_weights = mod.exponential_weights
    weighted_mean = mod.weighted_mean
    compute_split_factor = mod.compute_split_factor
    compute_trend_factor = mod.compute_trend_factor
    HL_ATTUALE = mod.HALF_LIFE_GAMES
    TI_ATTUALE = mod.TREND_INTENSITY

    players = load_players(ruolo)
    if not players:
        print(f"{ruolo.upper()}: nessun dato utilizzabile")
        return
    n_test = sum(len(p['scores']) - MIN_HISTORY for p in players)
    print(f"\n{'='*82}\n{ruolo.upper()} ({len(players)} giocatori, {n_test} punti test) "
          f"-- half_life={HL_ATTUALE}, trend_intensity={TI_ATTUALE} (NESSUNA ri-taratura)\n{'='*82}")

    # Sezione 1: verifica regola netto -> level_score
    total, exact, pct, mismatches = check_rule(players)
    print(f"  [1] Regola netto->level_score: {exact}/{total} esatte ({pct:.2f}%)")
    if mismatches:
        print(f"      Esempi mismatch (netto, level_reale, level_predetto): {mismatches[:5]}")

    # Sezione 2/Confronto A: MAE isolato di level_score_atteso
    mae_a, n_a = confronto_a(players, HL_ATTUALE)
    print(f"  [2] Confronto A -- MAE isolato level_score_atteso vs level_score reale: "
          f"{mae_a:.3f} ({n_a} punti test)")

    # Baseline produzione (media pesata sul totale)
    mae_base, n_base = mae_baseline_totale(players, exponential_weights, weighted_mean,
                                            compute_split_factor, compute_trend_factor,
                                            HL_ATTUALE, TI_ATTUALE)
    print(f"  [3] Baseline produzione (media pesata sul totale): MAE={mae_base:.3f} ({n_base} punti test)")

    # Confronto B senza floor
    mae_b, n_b = confronto_b(players, exponential_weights, weighted_mean, compute_split_factor,
                              compute_trend_factor, HL_ATTUALE, TI_ATTUALE, apply_floor=False)
    pct_b = (mae_b - mae_base) / mae_base * 100
    print(f"  [4] Confronto B -- level_score_atteso (tasso eventi) + granulare_atteso: "
          f"MAE={mae_b:.3f} ({pct_b:+.2f}% vs baseline)")

    # Confronto B con floor (variante diagnostica)
    mae_bf, n_bf = confronto_b(players, exponential_weights, weighted_mean, compute_split_factor,
                                compute_trend_factor, HL_ATTUALE, TI_ATTUALE, apply_floor=True)
    pct_bf = (mae_bf - mae_base) / mae_base * 100
    print(f"  [5] Confronto B + floor (max su level_atteso>=60): "
          f"MAE={mae_bf:.3f} ({pct_bf:+.2f}% vs baseline)")


def main():
    ruoli = sys.argv[1:] or ('gk', 'def', 'mid', 'fwd')
    for ruolo in ruoli:
        run_role(ruolo)


if __name__ == '__main__':
    main()
