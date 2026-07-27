"""
Analyze FWD+MID Team Pairing (27/07 notte, richiesta esplicita dell'utente)

Domanda: e' piu' efficace schierare un attaccante e un centrocampista di
squadre DIVERSE con punteggio atteso combinato (sommato) piu' alto, oppure
un attaccante e un centrocampista della STESSA squadra con atteso combinato
piu' basso (scommettendo su una sinergia/correlazione reale tra compagni)?

PREMESSA TEORICA IMPORTANTE (verificata comunque con i dati, non solo
assunta): il bonus di una coppia di giocatori e' la SOMMA dei loro punteggi
reali. Per una somma di due variabili, il valore ATTESO della somma e'
SEMPRE la somma dei valori attesi, INDIPENDENTEMENTE dalla correlazione tra
le due variabili (E[X+Y] = E[X]+E[Y] sempre, che X e Y siano correlate o
no). La correlazione cambia SOLO la varianza della somma (rilevante per
Arena/All Stars dove il taglio premi conta, non per il valore atteso in
se'). Quindi, SE l'atteso di ciascun giocatore e' calibrato senza bias
sistematico per ruolo (verificato: MID +0.71pt, FWD +0.55pt di bias --
quasi nulli, vedi analyze_gk_captain_value.py), la coppia con atteso
combinato piu' alto ha SEMPRE il reale atteso combinato piu' alto, a
prescindere da chi gioca con chi -- l'unica cosa che la sinergia
same-team potrebbe cambiare e' la variabilita' del risultato, non la sua
media. Questo script verifica EMPIRICAMENTE se questo ragionamento tiene
(bias di calibrazione trascurabile per MID/FWD) e se esiste una
correlazione same-team misurabile per la coppia FWD-MID specificamente
(gia' accennata come debole/non significativa in measure_teammate_
correlation.py, qui rifatta in modo mirato e con il confronto diretto
richiesto: stesso bucket di atteso combinato, same-team vs cross-team).

Metodo (NESSUNA nuova query, solo cache di calibrazione gia' su disco,
MLS+K League insieme):
1. Walk-forward per MID e FWD (stesso approccio di analyze_gk_captain_
   value.py: rigorous_backtest con i parametri UFFICIALI di produzione)
   per ottenere, per ogni partita di test di ogni giocatore: (team_slug,
   data_partita, atteso, reale).
2. Raggruppa per (team_slug, data): un MID e un FWD della STESSA squadra
   nella STESSA partita = coppia "same-team" candidata reale.
3. Per lo stesso giorno di campionato (stessa data, squadre diverse):
   un MID di una squadra x un FWD di un'ALTRA squadra = coppia
   "cross-team" (quello che si otterrebbe scegliendo i due migliori
   indipendentemente, tipico della costruzione greedy attuale).
4. Confronto diretto per bucket di atteso COMBINATO (somma): a parita' di
   atteso combinato, il reale combinato medio e' diverso tra same-team e
   cross-team? Se no (differenza dentro il rumore), la sinergia same-team
   non aggiunge nulla oltre a quanto gia' catturato dall'atteso individuale.
5. Correlazione dei residui (reale - atteso) tra i due giocatori della
   coppia, same-team vs cross-team (quest'ultima e' un controllo di
   "falso positivo": non dovrebbe esserci alcuna correlazione reale tra
   giocatori di squadre diverse che non giocano nemmeno la stessa partita
   tra loro, salvo effetti di giornata/calendario condivisi).
6. Simulazione diretta della domanda dell'utente: per una serie di soglie
   di "gap" (quanto l'atteso combinato cross-team supera quello same-team),
   verifica se il reale combinato medio cross-team supera quello same-team
   ANCHE quando il gap e' piccolo -- risponde a "quanto atteso in meno posso
   accettare per la sinergia same-team, prima che convenga comunque l'altra
   coppia".

Uso: python formazione_mls/diagnostics/analyze_fwd_mid_team_pairing.py
"""
import os
import sys
import glob
import json
import random
import statistics
import importlib
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 6
N_PERMUTATIONS = 999
RANDOM_SEED = 42

CONFIGS = [
    ('MLS', 'MID', 'formazione_mls.predict.test_mid', 'formazione_mls/output/mls_mid_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('MLS', 'FWD', 'formazione_mls.predict.test_mls_fwd_all', 'formazione_mls/output/mls_fwd_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'MID', 'formazione_kleague.predict.test_mid', 'formazione_kleague/output/kleague_mid_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
    ('KLEAGUE', 'FWD', 'formazione_kleague.predict.test_mls_fwd_all', 'formazione_kleague/output/kleague_fwd_calibration/.cache',
     dict(half_life=12.0, range_multiplier=1.4, opponent_sensitivity=29.0, use_granular_factors=False,
          use_trend=True, trend_intensity=0.7)),
]

MIN_PAIRS_FOR_REPORT = 15


def player_team_and_flags(entries):
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


def load_player_series(fpath):
    with open(fpath, encoding='utf-8') as f:
        cache = json.load(f)
    if not cache:
        return None
    entries = [e for e in cache.values() if e.get('anyGame') and e.get('scoreStatus') == 'FINAL']
    if len(entries) < MIN_HISTORY + 3:
        return None
    entries.sort(key=lambda e: e['anyGame'].get('date') or '')
    scores = [e.get('score') or 0.0 for e in entries]
    return entries, scores


def collect_role_records(league, ruolo, module_name, cache_dir, params):
    """Ritorna lista di (team_slug, match_date_iso, predetto, reale)."""
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

    out = []
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
            i = r['indice']
            match_date = (entries[i]['anyGame'].get('date') or '')[:10]
            if not match_date:
                continue
            out.append((team_slug, match_date, r['predetto'], r['reale']))

    print(f"  [{league}/{ruolo}] {n_players} giocatori, {len(out)} partite testate")
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


def build_pairs(mid_records, fwd_records):
    """Ritorna (same_team_pairs, cross_team_pairs), ognuna lista di dict
    {predetto_mid, reale_mid, predetto_fwd, reale_fwd}."""
    mid_by_date = defaultdict(list)
    for team, date, predetto, reale in mid_records:
        mid_by_date[date].append((team, predetto, reale))
    fwd_by_date = defaultdict(list)
    for team, date, predetto, reale in fwd_records:
        fwd_by_date[date].append((team, predetto, reale))

    same_team, cross_team = [], []
    common_dates = set(mid_by_date) & set(fwd_by_date)
    for date in common_dates:
        mids = mid_by_date[date]
        fwds = fwd_by_date[date]
        for (team_m, pm, rm) in mids:
            for (team_f, pf, rf) in fwds:
                entry = dict(predetto_mid=pm, reale_mid=rm, predetto_fwd=pf, reale_fwd=rf,
                             predetto_sum=pm + pf, reale_sum=rm + rf)
                if team_m == team_f:
                    same_team.append(entry)
                else:
                    cross_team.append(entry)
    return same_team, cross_team


def bucket_compare(same_team, cross_team, bucket_size=10, lo=70, hi=150):
    buckets_same = defaultdict(list)
    buckets_cross = defaultdict(list)
    for e in same_team:
        if lo <= e['predetto_sum'] < hi:
            b = int((e['predetto_sum'] - lo) // bucket_size) * bucket_size + lo
            buckets_same[b].append(e)
    for e in cross_team:
        if lo <= e['predetto_sum'] < hi:
            b = int((e['predetto_sum'] - lo) // bucket_size) * bucket_size + lo
            buckets_cross[b].append(e)
    keys = sorted(set(buckets_same) | set(buckets_cross))
    print(f"{'bucket atteso comb.':<20}{'same n':>8}{'same reale':>12}{'cross n':>9}{'cross reale':>13}{'gap same-cross':>16}")
    for b in keys:
        s = buckets_same.get(b, [])
        c = buckets_cross.get(b, [])
        s_mean = statistics.mean(e['reale_sum'] for e in s) if s else None
        c_mean = statistics.mean(e['reale_sum'] for e in c) if c else None
        s_str = f"{len(s):>8}{s_mean:>12.1f}" if s_mean is not None else f"{len(s):>8}{'--':>12}"
        c_str = f"{len(c):>9}{c_mean:>13.1f}" if c_mean is not None else f"{len(c):>9}{'--':>13}"
        gap_str = f"{(s_mean - c_mean):>+16.1f}" if s_mean is not None and c_mean is not None else f"{'--':>16}"
        print(f"{b}-{b+bucket_size:<15}{s_str}{c_str}{gap_str}")


def permutation_pvalue(xs, ys, observed_r, n_perm=N_PERMUTATIONS):
    rng = random.Random(RANDOM_SEED)
    ys_shuffled = list(ys)
    count = 0
    for _ in range(n_perm):
        rng.shuffle(ys_shuffled)
        r = pearson(xs, ys_shuffled)
        if r is not None and abs(r) >= abs(observed_r):
            count += 1
    return (count + 1) / (n_perm + 1)


def gap_simulation(same_team, cross_team, gaps=(0, 5, 10, 15, 20, 25)):
    """Per ogni soglia di gap, confronta: same-team con atteso combinato in
    [X, X+10) contro cross-team con atteso combinato in [X+gap, X+gap+10) --
    quale ha il reale combinato medio piu' alto?"""
    if not same_team or not cross_team:
        return
    print("\nPer ogni soglia di 'gap' (di quanto l'atteso combinato cross-team supera quello")
    print("same-team), confronto diretto tra reale combinato medio dei due gruppi:")
    print(f"{'gap richiesto':>14}{'same n':>8}{'same reale medio':>19}{'cross n':>9}{'cross reale medio':>20}{'vince':>10}")
    same_sorted = sorted(same_team, key=lambda e: e['predetto_sum'])
    for gap in gaps:
        # campiona same-team a bassa fascia (atteso combinato mediano del pool same-team)
        if not same_sorted:
            continue
        median_same = statistics.median(e['predetto_sum'] for e in same_sorted)
        same_bucket = [e for e in same_team if abs(e['predetto_sum'] - median_same) <= 5]
        cross_bucket = [e for e in cross_team if abs(e['predetto_sum'] - (median_same + gap)) <= 5]
        if len(same_bucket) < 5 or len(cross_bucket) < 5:
            continue
        s_mean = statistics.mean(e['reale_sum'] for e in same_bucket)
        c_mean = statistics.mean(e['reale_sum'] for e in cross_bucket)
        vince = 'same-team' if s_mean > c_mean else 'cross-team'
        print(f"{gap:>14}{len(same_bucket):>8}{s_mean:>19.1f}{len(cross_bucket):>9}{c_mean:>20.1f}{vince:>10}")


def main():
    print("Raccolta (team, data, atteso, reale) per MID e FWD, MLS+K League...")
    mid_records, fwd_records = [], []
    for league, ruolo, module_name, cache_dir, params in CONFIGS:
        recs = collect_role_records(league, ruolo, module_name, cache_dir, params)
        if ruolo == 'MID':
            mid_records.extend(recs)
        else:
            fwd_records.extend(recs)

    same_team, cross_team = build_pairs(mid_records, fwd_records)
    print(f"\nCoppie MID+FWD stessa squadra stessa partita: {len(same_team)}")
    print(f"Coppie MID+FWD squadre diverse stessa giornata (cross-team): {len(cross_team)}")

    print("\n=== Bias di calibrazione individuale (gia' noto da analyze_gk_captain_value.py, ricontrollato qui) ===")
    for label, recs in (('MID', mid_records), ('FWD', fwd_records)):
        bias = statistics.mean(r - p for _, _, p, r in recs)
        print(f"  {label}: n={len(recs)}  bias={bias:+.2f} pt (atteso ben calibrato se vicino a 0)")

    print("\n=== Correlazione dei residui (reale - atteso) tra i due membri della coppia ===")
    for label, pairs in (('same-team', same_team), ('cross-team', cross_team)):
        if len(pairs) < MIN_PAIRS_FOR_REPORT:
            print(f"  {label}: campione troppo piccolo ({len(pairs)} coppie)")
            continue
        res_mid = [e['reale_mid'] - e['predetto_mid'] for e in pairs]
        res_fwd = [e['reale_fwd'] - e['predetto_fwd'] for e in pairs]
        r = pearson(res_mid, res_fwd)
        if r is None:
            print(f"  {label}: n={len(pairs)}  correlazione n/d (varianza zero)")
            continue
        pval = permutation_pvalue(res_mid, res_fwd, r)
        sig = " *" if pval < 0.05 else ""
        print(f"  {label:<11} n={len(pairs):>5}  corr={r:+.3f}{sig}  p-value={pval:.4f}")
    print("  (* = p<0.05: correlazione piu' estrema del 95% di quelle ottenute mischiando a caso)")

    print("\n=== Confronto diretto per bucket di atteso COMBINATO (somma MID+FWD) ===")
    print("(a parita' di atteso combinato, il reale combinato medio same-team vs cross-team e' diverso?)")
    bucket_compare(same_team, cross_team)

    gap_simulation(same_team, cross_team)

    print("\n=== Riepilogo generale ===")
    for label, pairs in (('same-team', same_team), ('cross-team', cross_team)):
        if not pairs:
            continue
        mp = statistics.mean(e['predetto_sum'] for e in pairs)
        mr = statistics.mean(e['reale_sum'] for e in pairs)
        print(f"  {label:<11} n={len(pairs):>5}  atteso combinato medio={mp:.1f}  reale combinato medio={mr:.1f}  bias={mr-mp:+.2f}")


if __name__ == '__main__':
    main()
