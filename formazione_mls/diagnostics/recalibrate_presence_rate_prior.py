"""Ricalibra i coefficienti della regressione presence_rate -> prior di ruolo
(29/07, test proposto in sez. 0 punto 33b del RIASSUNTO).

I coefficienti oggi in produzione (`_media_ruolo_prior_dinamico = max(0.0, a + b*presence_rate)`
in ciascun test_<ruolo>.py) furono stimati il 28/07 (sez. 31.D) su un pool piu' piccolo di
quello di oggi (27 leghe). Qui si rifa' la stessa regressione lineare semplice (presence_rate
per giocatore vs punteggio medio REALE quando gioca) sul pool ATTUALE, per confrontare.

Metodo (identico a sez. 31.D, nessuna nuova query API):
- presence_rate: frazione di partite 'considerate' (NON DID_NOT_PLAY) su tutte quelle nella
  finestra di `.game_log_cache` (l'unica cache con lo status, vedi nota sez. 31.D: NON usare
  `.cache`, quello non ha DID_NOT_PLAY).
- punteggio medio: media semplice (non pesata) degli score REALI quando gioca, da `.cache`
  detail_cache dello stesso giocatore.
- Una regressione lineare per ruolo (GK/DEF/MID/FWD), pool tutte le leghe.

Uso: python formazione_mls/diagnostics/recalibrate_presence_rate_prior.py
"""
import os
import sys
import glob
import json
import statistics

sys.path.insert(0, os.getcwd())
import measure_range_reliability as R  # noqa: E402


def collect_presence_vs_mean():
    rows = []
    for league in sorted(R.LEAGUES):
        for ruolo in R.ROLES:
            mod_name, cache_dir = R._module_name(league, ruolo)
            log_dir = os.path.join(os.path.dirname(cache_dir), '.game_log_cache')
            if not os.path.isdir(log_dir):
                continue
            for log_path in glob.glob(os.path.join(log_dir, '*_gamelog.json')):
                slug = os.path.basename(log_path).replace('_gamelog.json', '')
                detail_path = os.path.join(cache_dir, f'{slug}_detail_cache.json')
                if not os.path.isfile(detail_path):
                    continue
                try:
                    log_cache = json.load(open(log_path, encoding='utf-8'))
                    detail_cache = json.load(open(detail_path, encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    continue
                statuses = [v.get('scoreStatus') for v in log_cache.values() if isinstance(v, dict)]
                total = len(statuses)
                if total < 8:
                    continue
                dnp = sum(1 for s in statuses if s == 'DID_NOT_PLAY')
                presence_rate = 1.0 - (dnp / total)
                scores = [v.get('score') for v in detail_cache.values()
                          if isinstance(v, dict) and v.get('scoreStatus') == 'FINAL'
                          and v.get('score') is not None]
                if len(scores) < 6:
                    continue
                rows.append(dict(league=league, ruolo=ruolo, slug=slug,
                                  presence_rate=presence_rate, media=statistics.mean(scores),
                                  n=len(scores)))
    return rows


def linreg(xs, ys):
    n = len(xs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    return a, b


CURRENT = {
    'gk': None,  # da leggere dal modulo
    'def': None,
    'mid': None,
    'fwd': None,
}


def main():
    rows = collect_presence_vs_mean()
    by_role = {}
    for r in rows:
        by_role.setdefault(r['ruolo'], []).append(r)

    print(f"{'ruolo':<5} {'n':>5} {'corr':>7} {'a (nuovo)':>10} {'b (nuovo)':>10}   riga attuale in produzione")
    for ruolo in R.ROLES:
        grp = by_role.get(ruolo, [])
        if len(grp) < 15:
            print(f"{ruolo.upper():<5} n insufficiente ({len(grp)})")
            continue
        xs = [r['presence_rate'] for r in grp]
        ys = [r['media'] for r in grp]
        a, b = linreg(xs, ys)
        corr = R.__dict__.get('pearson') if False else None
        # pearson locale (measure_range_reliability non lo espone col nome giusto per import diretto)
        mx, my = statistics.mean(xs), statistics.mean(ys)
        sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
        corr = cov / (sx * sy) if sx and sy else None
        cs = f"{corr:+.3f}" if corr is not None else "n/d"
        print(f"{ruolo.upper():<5} {len(grp):>5} {cs:>7} {a:>10.2f} {b:>10.2f}")

    print("\nCoefficienti ATTUALI in produzione (letti dal codice, sez. 31.D):")
    print("  GK:  45.41 + 4.36 * presence_rate")
    print("  DEF: 38.08 + 14.95 * presence_rate")
    print("  MID: 34.89 + 19.42 * presence_rate")
    print("  FWD: 34.42 + 18.71 * presence_rate")


if __name__ == '__main__':
    main()
