"""QUALITA' DI SELEZIONE (27/07): misura il modello sulla metrica che decide
davvero le formazioni, non sul MAE.

Il MAE misura "quanto sbaglio il punteggio del singolo giocatore". Ma per
schierare non serve indovinare il punteggio: serve ORDINARE bene i candidati e
prendere i migliori. Un modello puo' avere MAE ottimo ed essere inutile per
scegliere (basta che sbagli in modo uniforme), e viceversa.

Qui, per ogni GIORNATA di ogni campionato, si prendono i giocatori che hanno
davvero giocato, si calcola la predizione usando SOLO lo storico precedente
(walk-forward, stessa disciplina del backtest), si ordina per predetto e si
misura il punteggio REALE ottenuto dai primi K -- confrontato con:
  - CASO (media di tutti i candidati di quella giornata) = il valore di
    schierare a caso; e' il vero baseline da battere;
  - ORACOLO (i migliori K veri) = il tetto massimo raggiungibile.
Il "lift catturato" e' la frazione della distanza caso->oracolo che il modello
riesce a percorrere: 0% = tanto vale scegliere a caso, 100% = preveggenza.

Confronta piu' STRATEGIE di ordinamento per capire da dove viene (o non viene)
il vantaggio.

Uso:  python formazione_mls/diagnostics/selection_quality.py [def|fwd]
"""
import glob
import os
import statistics
import sys
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'formazione_mls', 'predict'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('SORARE_COOKIE', 'x')

MIN_HISTORY = 6
TOP_K = 3          # quanti giocatori si schierano per ruolo (ordine di grandezza reale)
MIN_CANDIDATI = 5  # giornate con meno candidati non sono una vera scelta


def load(role):
    if role == 'def':
        import test_def as T
        from nonregression_score_atteso_def import arrays_from_cache
        def predict(d, i, **kw):
            return T.compute_score_atteso_def(
                d['scores'][:i], d['is_home'][:i], d['opp_rank'][:i],
                d['resid'][:i], d['gran'][:i], d['pos'][:i], d['neg'][:i],
                d['gc'][:i], d['pas'][:i], d['cs'][:i],
                target_is_home=d['is_home'][i], target_opp_rank=d['opp_rank'][i],
                p_gioca=1.0, **kw)
    else:
        import test_mls_fwd_all as T
        from nonregression_score_atteso_fwd import arrays_from_cache
        def predict(d, i, **kw):
            return T.compute_score_atteso_fwd(
                d['scores'][:i], d['is_home'][:i], d['resid'][:i], d['gran'][:i],
                d['pos'][:i], d['neg'][:i], d['pas'][:i],
                target_is_home=d['is_home'][i], p_gioca=1.0, **kw)
    return T, arrays_from_cache, predict


def with_dates(arrays_from_cache, path):
    """arrays_from_cache non conserva le date: le riestrae in parallelo, con lo
    STESSO filtro/ordinamento, per poter raggruppare le partite in giornate."""
    import json
    d = arrays_from_cache(path)
    if not d:
        return None
    cache = json.load(open(path, encoding='utf-8'))
    nodes = [v for v in cache.values() if v.get('scoreStatus') == 'FINAL' and v.get('anyGame')]
    nodes.sort(key=lambda v: v['anyGame'].get('date') or '')
    d['dates'] = [(v['anyGame'].get('date') or '')[:10] for v in nodes]
    assert len(d['dates']) == len(d['scores'])
    return d


def main():
    role = (sys.argv[1] if len(sys.argv) > 1 else 'def').lower()
    T, arrays_from_cache, predict = load(role)

    pattern = os.path.join(REPO, 'formazione_*', 'output', f'*_{role}_all', '.cache',
                           '*_detail_cache.json')
    players = []
    for f in sorted(glob.glob(pattern)):
        d = with_dates(arrays_from_cache, f)
        if not d or len(d['scores']) - MIN_HISTORY < 1:
            continue
        parts = os.path.normpath(f).split(os.sep)
        champ = [p for p in parts if p.startswith('formazione_')][0][len('formazione_'):]
        players.append((champ, os.path.basename(f)[:-19], d))

    # strategie di ordinamento da confrontare
    def s_modello(d, i):
        return predict(d, i)

    def s_media_pesata(d, i):
        w = T.exponential_weights(i, T.HALF_LIFE_GAMES)
        return T.weighted_mean(d['scores'][:i], w)

    def s_media_semplice(d, i):
        return sum(d['scores'][:i]) / i

    def s_ultima(d, i):
        return d['scores'][i - 1]

    def s_level_score(d, i):
        w = T.exponential_weights(i, T.HALF_LIFE_GAMES)
        return T.expected_level_from_rates(
            T.weighted_mean(d['pos'][:i], w), T.weighted_mean(d['neg'][:i], w))

    strategie = [('MODELLO (produzione)', s_modello),
                 ('media pesata storica', s_media_pesata),
                 ('media semplice', s_media_semplice),
                 ('solo level_score atteso', s_level_score),
                 ('ultima partita', s_ultima)]

    # raccoglie i candidati per (campionato, giornata)
    giornate = defaultdict(list)
    for champ, slug, d in players:
        for i in range(MIN_HISTORY, len(d['scores'])):
            preds = {}
            for nome, fn in strategie:
                try:
                    preds[nome] = fn(d, i)
                except Exception:
                    preds[nome] = None
            giornate[(champ, d['dates'][i])].append((slug, d['scores'][i], preds))

    valide = {k: v for k, v in giornate.items() if len(v) >= MIN_CANDIDATI}
    if not valide:
        print('Nessuna giornata con abbastanza candidati.')
        return

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
        for nome, _ in strategie:
            ok = [c for c in cands if c[2][nome] is not None]
            if len(ok) < MIN_CANDIDATI:
                somme[nome] += caso
                continue
            scelti = sorted(ok, key=lambda c: -c[2][nome])[:TOP_K]
            somme[nome] += statistics.mean(c[1] for c in scelti)

    print(f"RUOLO: {role.upper()}   giornate valutate: {n_g} "
          f"(>= {MIN_CANDIDATI} candidati, si schierano i top {TOP_K})")
    print(f"campionati: {len(set(k[0] for k in valide))}   "
          f"coppie giocatore-partita: {sum(len(v) for v in valide.values())}\n")
    caso_m = tot_caso / n_g
    orac_m = tot_oracolo / n_g
    print(f"{'strategia di scelta':<26} {'punti/giornata':>14} {'vs caso':>9} {'lift catturato':>15}")
    print(f"{'CASO (media candidati)':<26} {caso_m:>14.2f} {'--':>9} {'0.0%':>15}")
    righe = []
    for nome, _ in strategie:
        m = somme[nome] / n_g
        lift = (m - caso_m) / (orac_m - caso_m) * 100 if orac_m > caso_m else 0.0
        righe.append((lift, nome, m))
    for lift, nome, m in sorted(righe, reverse=True):
        print(f"{nome:<26} {m:>14.2f} {m - caso_m:>+9.2f} {lift:>14.1f}%")
    print(f"{'ORACOLO (top veri)':<26} {orac_m:>14.2f} {orac_m - caso_m:>+9.2f} {'100.0%':>15}")


if __name__ == '__main__':
    main()
