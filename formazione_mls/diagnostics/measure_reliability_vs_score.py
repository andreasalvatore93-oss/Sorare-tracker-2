"""TEMA "meglio il piu' affidabile o il piu' forte" (30/07, richiesta esplicita
utente, backlog project_backlog_affidabile_vs_forte -- MAI eseguito prima come
test diretto: i test precedenti del 29/07 misuravano se il range PREDICE
l'errore reale (SCARTATO, correlazione ~0), non se conviene PREFERIRE un
giocatore piu' consistente a parita' di scelta. Domanda diversa.

Domanda esatta posta dall'utente: dato un gruppo di candidati per uno slot,
conviene scegliere quello con score_atteso piu' alto (strategia attuale, pura),
o vale la pena penalizzare lo score per la sua dispersione storica (dev_std
pesata) e preferire un giocatore piu' basso ma piu' consistente?

Stessa infrastruttura di selection_quality.py (giornate reali, walk-forward,
lift catturato vs caso/oracolo) -- qui si aggiungono strategie "risk-adjusted"
(score - lambda*dev_std) e uno "Sharpe" (score/dev_std) per vedere se battono
il MODELLO puro. Richiesto ORA (non nelle sessioni precedenti) perche' la
produzione e' stata appena aggiornata (fix anyPlayers/prior dinamico/
opponent_lambda_mult) e il pool di calibrazione e' quasi triplicato (~20k
partite vs ~7-8k di fine luglio).

Uso: python formazione_mls/diagnostics/measure_reliability_vs_score.py [def|fwd]
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

from selection_quality import load, with_dates  # noqa: E402

MIN_HISTORY = 6
TOP_K = 3
MIN_CANDIDATI = 5
LAMBDAS = (0.1, 0.2, 0.3, 0.5, 0.8, 1.2)


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

    def _score_dev(d, i):
        w = T.exponential_weights(i, T.HALF_LIFE_GAMES)
        mean = T.weighted_mean(d['scores'][:i], w)
        dev = T.weighted_stddev(d['scores'][:i], w, mean)
        score = predict(d, i)
        return score, dev

    def s_modello(d, i):
        return predict(d, i)

    strategie = [('MODELLO (score puro, produzione)', s_modello)]
    for lam in LAMBDAS:
        def _mk(lam):
            def s(d, i):
                score, dev = _score_dev(d, i)
                return score - lam * dev
            return s
        strategie.append((f'score - {lam}*dev_std', _mk(lam)))

    def s_sharpe(d, i):
        score, dev = _score_dev(d, i)
        return score / dev if dev > 0.01 else score
    strategie.append(('score / dev_std (Sharpe)', s_sharpe))

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
    print(f"{'strategia di scelta':<32} {'punti/giornata':>14} {'vs caso':>9} {'lift catturato':>15}")
    print(f"{'CASO (media candidati)':<32} {caso_m:>14.2f} {'--':>9} {'0.0%':>15}")
    righe = []
    for nome, _ in strategie:
        m = somme[nome] / n_g
        lift = (m - caso_m) / (orac_m - caso_m) * 100 if orac_m > caso_m else 0.0
        righe.append((lift, nome, m))
    for lift, nome, m in sorted(righe, reverse=True):
        print(f"{nome:<32} {m:>14.2f} {m - caso_m:>+9.2f} {lift:>14.1f}%")
    print(f"{'ORACOLO (top veri)':<32} {orac_m:>14.2f} {orac_m - caso_m:>+9.2f} {'100.0%':>15}")


if __name__ == '__main__':
    main()
