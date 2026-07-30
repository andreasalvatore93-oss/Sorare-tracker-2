"""Verifica bias sistematico per giocatori a BASSA PRESENZA (30/07, richiesta
esplicita utente, caso reale Jonathan Sirois: gioca ~15% delle partite,
storico di 4 partite utilizzabili con un solo picco anomalo, ma lo shrinkage
verso il prior dinamico lo porta quasi alla pari di un titolare fisso).

A differenza di validate_low_history_bias.py (bucket per NUMERO di partite
osservate finora, che confonde "carriera appena iniziata" con "gioca
raramente"), qui si usa PRESENCE_RATE vero (partite giocate / partite
considerate, DID_NOT_PLAY incluse -- stesso dato usato dal prior dinamico
in produzione, da .game_log_cache) e si replica la formula REALE di
shrinkage (shrink_k=30 per GK, prior = 46.20 + 4.05*presence_rate) per
vedere se il prior ricalibrato stamattina e' abbastanza punitivo per i
casi di presenza quasi nulla.

Errore MEDIO CON SEGNO (non solo MAE) per bucket di presence_rate: un bias
positivo sistematico nei bucket a bassa presenza e' la prova diretta che il
prior e' troppo generoso li'.

Uso: python formazione_mls/diagnostics/validate_low_presence_bias.py
"""
import os
import sys
import glob
import json
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

SHRINK_K_GK = 30.0
PRIOR_BASE_GK = 46.20
PRIOR_SLOPE_GK = 4.05
WINDOW = 26  # stessa finestra "considerate" della produzione (WINDOW_SIZE)
MIN_HISTORY = 3

PRESENCE_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def load_gamelogs(role):
    players = {}
    patterns = [f'formazione_*/output/*_{role}_all/.game_log_cache',
                f'formazione_*/output/*_{role}_calibration/.game_log_cache']
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_gamelog.json')):
                slug = os.path.basename(fpath)[:-len('_gamelog.json')]
                if slug in players:
                    continue
                try:
                    with open(fpath, encoding='utf-8') as f:
                        d = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                nodes = [v for v in d.values() if (v.get('anyGame') or {}).get('date')]
                nodes.sort(key=lambda v: v['anyGame']['date'])
                players[slug] = nodes
    return players


def bucket_for(rate):
    for lo, hi in PRESENCE_BUCKETS:
        if lo <= rate < hi:
            return f"{lo:.1f}-{hi if hi <= 1.0 else 1.0:.1f}"
    return None


def main():
    role = (sys.argv[1] if len(sys.argv) > 1 else 'gk').lower()
    print(f"Caricamento game log {role.upper()}...")
    players = load_gamelogs(role)
    print(f"Giocatori con game log: {len(players)}\n")

    errors_by_bucket = defaultdict(list)
    n_skipped_short = 0

    for slug, nodes in players.items():
        # indici delle partite FINAL (quelle con uno score vero da predire)
        final_idxs = [i for i, v in enumerate(nodes) if v.get('scoreStatus') == 'FINAL']
        for idx in final_idxs:
            window_nodes = nodes[max(0, idx - WINDOW):idx]
            if len(window_nodes) < MIN_HISTORY:
                n_skipped_short += 1
                continue
            usable = [v for v in window_nodes if v.get('scoreStatus') == 'FINAL']
            n_usable = len(usable)
            if n_usable < MIN_HISTORY:
                n_skipped_short += 1
                continue
            total_considered = len(window_nodes)
            presence_rate = n_usable / total_considered if total_considered else 1.0
            scores = [v.get('score') or 0.0 for v in usable]
            media = sum(scores) / len(scores)
            prior = max(0.0, PRIOR_BASE_GK + PRIOR_SLOPE_GK * presence_rate)
            n = n_usable
            pred = (n / (n + SHRINK_K_GK)) * media + (SHRINK_K_GK / (n + SHRINK_K_GK)) * prior
            reale = nodes[idx].get('score') or 0.0
            errore = pred - reale
            b = bucket_for(presence_rate)
            if b:
                errors_by_bucket[b].append(errore)

    print(f"Casi con storico troppo corto (<{MIN_HISTORY}), saltati: {n_skipped_short}\n")
    print(f"{'presence_rate':<16} {'n casi':>8} {'errore medio':>14} {'MAE':>8}   interpretazione")
    for lo, hi in PRESENCE_BUCKETS:
        key = f"{lo:.1f}-{hi if hi <= 1.0 else 1.0:.1f}"
        errs = errors_by_bucket.get(key, [])
        if not errs:
            continue
        mean_err = statistics.mean(errs)
        mae = statistics.mean(abs(e) for e in errs)
        interp = "SOVRASTIMA" if mean_err > 1.0 else ("sottostima" if mean_err < -1.0 else "~neutro")
        print(f"{key:<16} {len(errs):>8} {mean_err:>+14.2f} {mae:>8.2f}   {interp}")


if __name__ == '__main__':
    main()
