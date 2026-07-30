"""Verifica bias sistematico per giocatori con POCHISSIMO storico (30/07,
richiesta esplicita utente, caso reale Jonathan Sirois: 4 partite utilizzabili
su 26, un solo picco anomalo di 69, ma il modello lo mette quasi alla pari di
Matt Turner -- storico ricco, piu' picchi alti, ma trend recente debole).

Ipotesi: non e' solo che i giocatori con poco storico hanno un ERRORE PIU'
GRANDE (atteso, ovvio) -- l'ipotesi e' che l'errore sia SISTEMATICAMENTE
POSITIVO (il modello li SOVRASTIMA), per due motivi strutturali:
1. compute_trend_factor richiede >= 10 partite, altrimenti ritorna
   ESATTAMENTE 1.0 (neutro) -- un giocatore con trend negativo ma storico
   corto non viene MAI penalizzato per quel trend, a differenza di uno con
   storico lungo.
2. Il prior dinamico (presence_rate -> prior) ha uno spread stretto tra
   "non gioca mai" e "gioca sempre" (per GK: 46.20 a presence_rate=0 vs
   50.25 a presence_rate=1, solo 4 punti di differenza) -- potrebbe non
   essere abbastanza punitivo per i casi estremi.

Metodo: walk-forward su dati reali (stesso principio di sempre), bucket per
NUMERO DI PARTITE DISPONIBILI al momento della predizione (n storico), errore
MEDIO CON SEGNO (non MAE) per bucket -- un bias positivo sistematico nei
bucket piccoli e' la prova diretta.

Uso: python formazione_mls/diagnostics/validate_low_history_bias.py [ruolo]
"""
import os
import sys
import glob
import json
import math
import statistics
import datetime
from collections import defaultdict

sys.path.insert(0, os.getcwd())

MIN_HISTORY = 3  # abbassato apposta (non 6) per includere anche i casi con pochissimo storico
N_BUCKETS = [(3, 5), (6, 9), (10, 15), (16, 25), (26, 999)]


def parse_date(g):
    d = g.get('date')
    if not d:
        return None
    try:
        return datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    except ValueError:
        return None


def load_role_players(role):
    players = []
    patterns = [f'formazione_*/output/*_{role}_all/.cache', f'formazione_*/output/*_{role}_calibration/.cache']
    seen_files = set()
    for pattern in patterns:
        for cache_dir in glob.glob(pattern):
            for fpath in glob.glob(os.path.join(cache_dir, '*_detail_cache.json')):
                if fpath in seen_files:
                    continue
                seen_files.add(fpath)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        cache = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                entries = [e for e in cache.values() if e.get('anyGame')]
                entries = [e for e in entries if parse_date(e['anyGame']) is not None]
                if len(entries) < MIN_HISTORY + 1:
                    continue
                entries.sort(key=lambda e: parse_date(e['anyGame']))
                scores = [e.get('score') or 0.0 for e in entries]
                players.append(scores)
    return players


def bucket_for(n):
    for lo, hi in N_BUCKETS:
        if lo <= n <= hi:
            return f"{lo}-{hi if hi < 999 else '+'}"
    return None


def main():
    role = (sys.argv[1] if len(sys.argv) > 1 else 'gk').lower()
    print(f"Caricamento giocatori {role.upper()}...")
    players = load_role_players(role)
    print(f"Giocatori utilizzabili: {len(players)}\n")

    errors_by_bucket = defaultdict(list)
    for scores in players:
        n_total = len(scores)
        for i in range(MIN_HISTORY, n_total):
            hist = scores[:i]
            # media semplice (no pesi/shrink/trend -- baseline pura, per
            # isolare SOLO l'effetto "quanti dati ho", non altre formule)
            pred = sum(hist) / len(hist)
            reale = scores[i]
            errore = pred - reale  # positivo = SOVRASTIMA
            b = bucket_for(i)
            if b:
                errors_by_bucket[b].append(errore)

    print(f"{'storico (n partite)':<22} {'n casi':>8} {'errore medio':>14} {'MAE':>8}   interpretazione")
    for lo, hi in N_BUCKETS:
        key = f"{lo}-{hi if hi < 999 else '+'}"
        errs = errors_by_bucket.get(key, [])
        if not errs:
            continue
        mean_err = statistics.mean(errs)
        mae = statistics.mean(abs(e) for e in errs)
        interp = "SOVRASTIMA" if mean_err > 0.5 else ("sottostima" if mean_err < -0.5 else "~neutro")
        print(f"{key:<22} {len(errs):>8} {mean_err:>+14.2f} {mae:>8.2f}   {interp}")


if __name__ == '__main__':
    main()
