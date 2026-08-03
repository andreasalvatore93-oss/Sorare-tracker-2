"""
Analyze Captain Bias Variance (04/08, richiesta esplicita utente)

Seguito di analyze_captain_bias_outfield.py: il bias medio PER RUOLO,
tradotto in una regola di scelta capitano, non guadagnava quasi nulla in un
backtest della policy vera (+0.012 pt/formazione su 513 formazioni reali --
vedi RIASSUNTO_2026-08-04.md). L'ipotesi successiva, scartata quella dei
ruoli: forse conta la VARIANZA del singolo giocatore, non del ruolo. Il
capitano moltiplica 1.2x qualsiasi cosa succeda -- un giocatore "boom/bust"
puo' avere lo stesso atteso di uno stabile ma un profilo di rischio diverso.

Prima domanda (questo script): a parita' di atteso nella zona capitano
(>=55), i giocatori piu' VOLATILI hanno anche un bias diverso (sovra/sotto-
stimati sistematicamente di piu')? Se si', e' un bias vero da correggere,
non solo "rischio" -- misurabile con lo stesso approccio del bias per ruolo,
ma raggruppando per deviazione standard storica invece che per ruolo.

NESSUNA nuova query: la deviazione standard pesata del giocatore al momento
della previsione (dev_std) e' gia' calcolata da ogni test_<ruolo>.py per il
range di confidenza (range_conf = dev_std * range_multiplier, salvato in
ogni riga di rigorous_backtest) -- qui si recupera dividendo range_conf per
range_multiplier, nessun ricalcolo.

Uso: python formazione_mls/diagnostics/analyze_captain_bias_variance.py
"""
import os
import sys
import glob
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import formazione_mls.diagnostics.analyze_gk_captain_value as base

ZONA_CAPITANO_MIN_ATTESO = 55


def collect_triplette(league, ruolo, module_name, cache_dir, params):
    """Come base.collect_pairs, ma ritorna (predetto, reale, dev_std) --
    dev_std recuperata da range_conf/range_multiplier di ogni riga, stesso
    dato gia' calcolato da rigorous_backtest per il range di confidenza."""
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return []
    rigorous_backtest = mod.rigorous_backtest

    files = glob.glob(os.path.join(cache_dir, '*_detail_cache.json'))
    if not files:
        return []

    range_multiplier = params.get('range_multiplier') or 1.0
    triplette = []
    for fpath in files:
        loaded = base.load_player_series(fpath)
        if not loaded:
            continue
        entries, scores = loaded
        team_slug, is_home_flags = base.player_team_and_flags(entries)
        if team_slug is None or any(f is None for f in is_home_flags):
            continue
        opponent_rankings = [None] * len(scores)
        result = rigorous_backtest(scores, is_home_flags, opponent_rankings,
                                    min_history=base.MIN_HISTORY, **params)
        for r in (result.get('rows') or []):
            range_conf = r.get('range_conf')
            if range_conf is None:
                continue
            dev_std = range_conf / range_multiplier
            triplette.append((r['predetto'], r['reale'], dev_std))
    return triplette


def main():
    print("Raccolta terne (predetto, reale, dev_std) -- stessi dati/parametri di produzione, nessuna nuova query...\n")

    tutte = []  # (predetto, reale, dev_std, ruolo)
    for league, ruolo, module_name, cache_dir, params in base.CONFIGS:
        if ruolo == 'GK':
            continue  # gia' deciso di escludere il portiere dal capitano
        for predetto, reale, dev_std in collect_triplette(league, ruolo, module_name, cache_dir, params):
            tutte.append((predetto, reale, dev_std, ruolo))

    print(f"totale righe movimento raccolte: {len(tutte)}")

    zona = [(p, r, d, ru) for p, r, d, ru in tutte if p >= ZONA_CAPITANO_MIN_ATTESO]
    print(f"in zona capitano (atteso>={ZONA_CAPITANO_MIN_ATTESO}): {len(zona)}\n")

    devs = sorted(d for _p, _r, d, _ru in zona)
    n = len(devs)
    t1, t2 = devs[n // 3], devs[2 * n // 3]
    print(f"terzili dev_std (zona capitano): basso < {t1:.1f} <= medio < {t2:.1f} <= alto\n")

    def bucket_di(d):
        if d < t1:
            return 'BASSA volatilita'
        if d < t2:
            return 'MEDIA volatilita'
        return 'ALTA volatilita'

    per_bucket = defaultdict(list)
    for p, r, d, ru in zona:
        per_bucket[bucket_di(d)].append((p, r))

    print("=== Bias per bucket di volatilita' (dev_std storica pesata), zona capitano ===")
    for nome in ('BASSA volatilita', 'MEDIA volatilita', 'ALTA volatilita'):
        pairs = per_bucket[nome]
        if not pairs:
            continue
        mp = statistics.mean(p for p, r in pairs)
        mr = statistics.mean(r for p, r in pairs)
        bias = mr - mp
        mae = statistics.mean(abs(r - p) for p, r in pairs)
        crolli = sum(1 for p, r in pairs if r < 0.5 * p)
        print(f"  {nome:<18} n={len(pairs):>5}  atteso medio={mp:6.1f}  reale medio={mr:6.1f}  "
              f"bias={bias:+6.2f}  MAE={mae:5.2f}  freq crollo={crolli/len(pairs):.1%}")

    print("\n=== Gap a coppie fra bucket (per confronto: gap DEF-vs-MID misurato ieri = -2.37pt) ===")
    nomi = [n for n in ('BASSA volatilita', 'MEDIA volatilita', 'ALTA volatilita') if per_bucket[n]]
    bias_bucket = {}
    for nome in nomi:
        pairs = per_bucket[nome]
        bias_bucket[nome] = statistics.mean(r - p for p, r in pairs)
    for i, a in enumerate(nomi):
        for b in nomi[i + 1:]:
            print(f"  {a} vs {b}: {bias_bucket[a] - bias_bucket[b]:+.2f} pt")


if __name__ == '__main__':
    main()
