"""
Analyze GK Captain Value (27/07 notte, richiesta esplicita dell'utente)

Domanda: a parita' (o quasi) di punteggio ATTESO, conviene davvero nominare
capitano un portiere invece di un giocatore di movimento? L'utente ha
un'intuizione da anni di esperienza su Sorare ("un portiere quasi mai
conviene da capitano, basta un gol subito per perdere il bonus clean sheet")
ma non basata su dati storici -- qui la verifichiamo con i dati reali gia'
in cache (nessuna nuova query API).

NOTA IMPORTANTE sulla logica del capitano: il bonus capitano e' bonus =
pct * punteggio REALE ottenuto da quel giocatore in quella giornata (non
sul punteggio atteso). Quindi, in puro valore atteso, capitanare il
giocatore con l'atteso piu' alto e' ottimale SOLO SE l'atteso e' un
predittore non distorto (ben calibrato) del punteggio reale ATTRAVERSO i
ruoli. Se il modello sovrastima sistematicamente i portieri rispetto ai
giocatori di movimento a parita' di atteso nominale, allora scegliere il
portiere in base al raw "atteso" e' un errore anche in pura logica di
valore atteso -- non serve invocare avversione al rischio per giustificare
l'intuizione dell'utente, basta una bias di calibrazione per ruolo.

Metodo (stesso approccio walk-forward gia' usato altrove nel progetto,
NESSUNA nuova query, solo le cache di calibrazione gia' su disco):
1. Per ogni ruolo (gk/def/mid/fwd) e ogni lega (mls/kleague), rilancia
   `rigorous_backtest` di ciascun `test_<ruolo>.py` con i PARAMETRI UFFICIALI
   di produzione (stessi half_life/range/trend, granulari OFF, opponent
   factor lasciato neutro -- gia' rimosso dallo score_atteso reale, vedi
   RIASSUNTO sezione 12) per ottenere, per ogni partita di test, la coppia
   (predetto, reale) -- 'predetto' e' esattamente la formula oggi in
   produzione.
2. Raggruppa DEF+MID+FWD in un unico pool "movimento" (outfield) e confronta
   con GK.
3. Bias di calibrazione per gruppo: media(reale - predetto).
4. Confronto per fascia di punteggio ATTESO (bucket): a parita' di predetto,
   confronta il reale medio GK vs movimento -- risponde direttamente alla
   domanda "un portiere con lo stesso atteso di un giocatore di movimento,
   realizza davvero lo stesso punteggio in media?"
5. Frequenza e ampiezza dei "crolli" (reale molto sotto il predetto, es.
   sotto META' del predetto) per gruppo -- verifica diretta dell'intuizione
   "basta un episodio negativo per affondare il portiere" in termini di
   downside frequency (rilevante anche se il valore atteso puro non
   dipendesse dalla varianza, perche' l'utente potrebbe preferire comunque
   ridurre il rischio, oltre a verificare se il bias di punto 3 è già
   sufficiente a spiegare l'intuizione).

Uso: python formazione_mls/diagnostics/analyze_gk_captain_value.py
"""
import os
import sys
import glob
import json
import importlib
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6

# (campionato, ruolo) -> (modulo, cartella cache, parametri ufficiali di produzione)
CONFIGS = [
    ('MLS', 'GK', 'formazione_mls.predict.test_gk', 'formazione_mls/output/mls_gk_calibration/.cache',
     dict(half_life=9.0, range_multiplier=1.6, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('MLS', 'DEF', 'formazione_mls.predict.test_def', 'formazione_mls/output/mls_def_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.2, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('MLS', 'MID', 'formazione_mls.predict.test_mid', 'formazione_mls/output/mls_mid_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('MLS', 'FWD', 'formazione_mls.predict.test_mls_fwd_all', 'formazione_mls/output/mls_fwd_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'GK', 'formazione_kleague.predict.test_gk', 'formazione_kleague/output/kleague_gk_calibration/.cache',
     dict(half_life=9.0, range_multiplier=1.6, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'DEF', 'formazione_kleague.predict.test_def', 'formazione_kleague/output/kleague_def_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.2, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'MID', 'formazione_kleague.predict.test_mid', 'formazione_kleague/output/kleague_mid_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'FWD', 'formazione_kleague.predict.test_mls_fwd_all', 'formazione_kleague/output/kleague_fwd_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
]


def load_player_series(fpath):
    with open(fpath, encoding='utf-8') as f:
        cache = json.load(f)
    if not cache:
        return None
    entries = [e for e in cache.values() if e.get('anyGame') and e.get('scoreStatus') == 'FINAL']
    if len(entries) < MIN_HISTORY + 3:
        return None
    # ordina per data (le cache non sono garantite ordinate)
    def _date(e):
        return e['anyGame'].get('date') or ''
    entries.sort(key=_date)

    scores, is_home_flags, opponent_rankings = [], [], []
    for e in entries:
        g = e['anyGame']
        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
        # non sappiamo con certezza quale sia la squadra del giocatore da qui
        # (serve solo per il segno casa/trasferta) -- usiamo la maggioranza
        scores.append(e.get('score') or 0.0)
        is_home_flags.append(None)  # placeholder, corretto sotto
        opponent_rankings.append(None)  # opponent factor gia' rimosso dalla produzione, non serve

    return entries, scores


def player_team_and_flags(entries):
    """Determina la squadra piu' frequente (maggioranza) e ricostruisce
    is_home_flags coerente con quella squadra, stesso approccio di
    measure_teammate_correlation.py."""
    team_counts = defaultdict(int)
    for e in entries:
        g = e['anyGame']
        for side in ('homeTeam', 'awayTeam'):
            slug = (g.get(side) or {}).get('slug')
            if slug:
                team_counts[slug] += 1
    if not team_counts:
        return None, None
    team_slug = max(team_counts, key=team_counts.get)
    flags = []
    for e in entries:
        g = e['anyGame']
        home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
        if home.get('slug') == team_slug:
            flags.append(True)
        elif away.get('slug') == team_slug:
            flags.append(False)
        else:
            flags.append(None)
    return team_slug, flags


def collect_pairs(league, ruolo, module_name, cache_dir, params):
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        print(f"  [{league}/{ruolo}] modulo {module_name} non trovato, salto.")
        return []
    rigorous_backtest = mod.rigorous_backtest

    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    if not files:
        print(f"  [{league}/{ruolo}] nessuna cache trovata in {cache_dir}")
        return []

    pairs = []
    n_players = 0
    for fpath in files:
        loaded = load_player_series(fpath)
        if not loaded:
            continue
        entries, scores = loaded
        team_slug, is_home_flags = player_team_and_flags(entries)
        if team_slug is None or any(f is None for f in is_home_flags):
            continue
        opponent_rankings = [None] * len(scores)

        result = rigorous_backtest(scores, is_home_flags, opponent_rankings,
                                    min_history=MIN_HISTORY, **params)
        rows = result.get('rows') or []
        if not rows:
            continue
        n_players += 1
        for r in rows:
            pairs.append((r['predetto'], r['reale']))

    print(f"  [{league}/{ruolo}] {n_players} giocatori, {len(pairs)} partite testate")
    return pairs


def bucket_stats(pairs, bucket_size=5, lo=20, hi=95):
    """Ritorna dict bucket_start -> (n, mean_predetto, mean_reale)."""
    buckets = defaultdict(list)
    for predetto, reale in pairs:
        if predetto < lo or predetto >= hi:
            continue
        b = int((predetto - lo) // bucket_size) * bucket_size + lo
        buckets[b].append((predetto, reale))
    out = {}
    for b, vals in buckets.items():
        n = len(vals)
        mp = statistics.mean(v[0] for v in vals)
        mr = statistics.mean(v[1] for v in vals)
        out[b] = (n, mp, mr)
    return out


def downside_stats(pairs, ratio_threshold=0.5):
    """Frequenza e ampiezza media dei 'crolli': reale < ratio_threshold * predetto
    (solo per predetto > 0, evita divisioni per zero/predizioni nulle)."""
    valid = [(p, r) for p, r in pairs if p > 5]
    if not valid:
        return None
    crolli = [(p, r) for p, r in valid if r < ratio_threshold * p]
    freq = len(crolli) / len(valid)
    avg_gap = statistics.mean(p - r for p, r in crolli) if crolli else 0.0
    return freq, avg_gap, len(valid)


def main():
    print("Raccolta coppie (predetto, reale) per ruolo/lega con i parametri UFFICIALI di produzione...")
    by_role = defaultdict(list)  # 'GK' / 'OUTFIELD' -> [(predetto, reale), ...]
    by_role_detail = defaultdict(list)  # 'GK' / 'DEF' / 'MID' / 'FWD' -> [...]

    for league, ruolo, module_name, cache_dir, params in CONFIGS:
        pairs = collect_pairs(league, ruolo, module_name, cache_dir, params)
        by_role_detail[ruolo].extend(pairs)
        group = 'GK' if ruolo == 'GK' else 'OUTFIELD'
        by_role[group].extend(pairs)

    print("\n=== Bias di calibrazione complessivo (media reale - predetto) ===")
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        pairs = by_role_detail[ruolo]
        if not pairs:
            continue
        bias = statistics.mean(r - p for p, r in pairs)
        mae = statistics.mean(abs(r - p) for p, r in pairs)
        print(f"  {ruolo:<5} n={len(pairs):>5}  bias={bias:+.2f} pt  MAE={mae:.2f} pt")

    print("\n=== GK vs OUTFIELD (DEF+MID+FWD combinati), overall ===")
    for group in ('GK', 'OUTFIELD'):
        pairs = by_role[group]
        bias = statistics.mean(r - p for p, r in pairs)
        mae = statistics.mean(abs(r - p) for p, r in pairs)
        print(f"  {group:<10} n={len(pairs):>6}  bias={bias:+.2f} pt  MAE={mae:.2f} pt")

    print("\n=== Confronto per fascia di punteggio ATTESO (bucket da 5 pt) ===")
    print("(risponde alla domanda: a parita' di atteso, il reale medio e' lo stesso per GK e movimento?)")
    gk_buckets = bucket_stats(by_role['GK'])
    of_buckets = bucket_stats(by_role['OUTFIELD'])
    all_bucket_keys = sorted(set(gk_buckets) | set(of_buckets))
    print(f"{'bucket atteso':<16}{'GK n':>7}{'GK reale medio':>16}{'MOV n':>8}{'MOV reale medio':>18}{'gap GK-MOV':>13}")
    for b in all_bucket_keys:
        gk = gk_buckets.get(b)
        of = of_buckets.get(b)
        gk_str = f"{gk[0]:>7}{gk[2]:>16.2f}" if gk else f"{'--':>7}{'--':>16}"
        of_str = f"{of[0]:>8}{of[2]:>18.2f}" if of else f"{'--':>8}{'--':>18}"
        gap_str = f"{(gk[2] - of[2]):>+13.2f}" if gk and of else f"{'--':>13}"
        print(f"{b}-{b+5:<11}{gk_str}{of_str}{gap_str}")

    print("\n=== Downside: frequenza e ampiezza dei 'crolli' (reale < 50% del predetto) ===")
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        pairs = by_role_detail[ruolo]
        stats = downside_stats(pairs)
        if not stats:
            continue
        freq, avg_gap, n = stats
        print(f"  {ruolo:<5} n={n:>5}  frequenza crollo={freq:.1%}  gap medio nei crolli={avg_gap:.1f} pt")

    print("\n=== Focus 'zona capitano' (predetto >= 55, dove un giocatore competerebbe per la fascia")
    print("    che tipicamente vince la scelta capitano) ===")
    for group in ('GK', 'OUTFIELD'):
        pairs = [(p, r) for p, r in by_role[group] if p >= 55]
        if not pairs:
            print(f"  {group}: nessun dato in questa fascia")
            continue
        mp = statistics.mean(p for p, r in pairs)
        mr = statistics.mean(r for p, r in pairs)
        bias = mr - mp
        stats = downside_stats(pairs)
        freq, avg_gap, n = stats if stats else (None, None, len(pairs))
        print(f"  {group:<10} n={len(pairs):>5}  atteso medio={mp:.1f}  reale medio={mr:.1f}  "
              f"bias={bias:+.2f}  frequenza crollo={freq:.1%} (gap medio {avg_gap:.1f})" if freq is not None
              else f"  {group:<10} n={len(pairs):>5}  atteso medio={mp:.1f}  reale medio={mr:.1f}  bias={bias:+.2f}")


if __name__ == '__main__':
    main()
