"""taratura_calib_per_ruolo -- rifitta i 4 coefficienti di CALIB_PER_RUOLO
(GK/DEF/MID/FWD) da dati_globali/taratura_coppie.json, con lo stesso metodo
gia' usato per la retta unica in taratura_giocatore.py: OLS a livello di
GIOCATORE, reale = a + b*previsto, un fit separato per ruolo.

Non esisteva nel repo uno script che generasse questi 4 coefficienti (solo il
risultato hardcoded in generatore_formazioni/build_formazione_globale.py:394-
399): due sessioni precedenti (P10 05/08, diagnosi CALIB_PER_RUOLO 06/08)
l'hanno cercato senza trovarlo. Questo script lo ricostruisce.

NON tocca la produzione: legge CALIB_PER_RUOLO solo per confronto, non lo
scrive da nessuna parte.

Uso:
  python taratura_calib_per_ruolo.py                    # fit sui dati attuali
  python taratura_calib_per_ruolo.py --max-data 2026-08-03   # solo partite
                                                           # fino a quella data
                                                           # (proxy dello
                                                           # snapshot storico,
                                                           # vedi limite sotto)
  python taratura_calib_per_ruolo.py --json out.json     # salva anche il json

LIMITE METODOLOGICO (importante, non aggirabile con questo script): il campo
'previsto' in taratura_coppie.json e' calcolato da taratura_giocatore.raccogli
col modello di PRODUZIONE ATTUALE, anche per le partite piu' vecchie (non e'
un replay del modello come era il giorno X). Filtrare per --max-data controlla
la COMPOSIZIONE del campione (quali partite entrano), non il modello con cui
'previsto' e' stato calcolato: un fit su --max-data 2026-08-03 NON e' identico
a quello che sarebbe uscito il 03/08, se nel frattempo il modello e' cambiato
(es. GK_TEAM_CS_WEIGHT, P9). Vedi REPORT_PASSAGGIO_2_SONNET_P10_2026-08-05.txt.
"""
import argparse
import json
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLO_LUNGO_A_CORTO = {
    'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD',
}


def retta(X, Y):
    n = len(X)
    mx = statistics.mean(X)
    my = statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(X, Y)]
    return a, b, statistics.pstdev(res)


def bootstrap_incertezza(X, Y, n_rep=200, seme=9):
    import random
    rnd = random.Random(seme)
    n = len(X)
    idx_pool = list(range(n))
    pars = []
    for _ in range(n_rep):
        idx = [rnd.choice(idx_pool) for _ in range(n)]
        pars.append(retta([X[i] for i in idx], [Y[i] for i in idx]))
    return (statistics.pstdev([p[0] for p in pars]),
            statistics.pstdev([p[1] for p in pars]))


def calib_produzione():
    """Legge CALIB_PER_RUOLO da generatore_formazioni/build_formazione_globale.py
    senza duplicare i valori a mano (i coefficienti vivono in un posto solo)."""
    import re
    path = 'generatore_formazioni/build_formazione_globale.py'
    testo = open(path, encoding='utf-8').read()
    m = re.search(r"CALIB_PER_RUOLO\s*=\s*\{(.*?)\n\}", testo, re.S)
    blocco = m.group(1)
    out = {}
    for riga in re.finditer(
            r"'(\w+)':\s*\(float\(os\.environ\.get\('CALIB_A_\w+',\s*'([\d.]+)'\)\),"
            r"\s*float\(os\.environ\.get\('CALIB_B_\w+',\s*'([\d.]+)'\)\)\)",
            blocco):
        ruolo, a, b = riga.groups()
        out[ruolo] = (float(a), float(b))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--coppie', default='dati_globali/taratura_coppie.json')
    ap.add_argument('--max-data', default=None,
                     help='tiene solo le coppie con data <= a questa (YYYY-MM-DD)')
    ap.add_argument('--json', default=None)
    ap.add_argument('--bootstrap', action='store_true',
                     help='stima anche l\'incertezza (200 resample, piu\' lento)')
    args = ap.parse_args()

    coppie = json.load(open(args.coppie, encoding='utf-8'))
    if args.max_data:
        coppie = [c for c in coppie if c.get('data', '') <= args.max_data]
    print(f'{len(coppie)} coppie caricate da {args.coppie}'
          + (f' (filtrate a data <= {args.max_data})' if args.max_data else ''))

    prod = calib_produzione()
    print(f'\nCALIB_PER_RUOLO in produzione (build_formazione_globale.py): {prod}\n')

    risultati = {}
    print(f'{"ruolo":5s} {"n":>7s} {"a":>8s} {"b":>8s}  {"a_prod":>8s} {"b_prod":>8s}'
          f'  {"prev.60->reale":>15s}  {"sd_residua":>10s}')
    for lungo, corto in RUOLO_LUNGO_A_CORTO.items():
        sub = [c for c in coppie if c.get('ruolo') == lungo]
        if len(sub) < 30:
            print(f'{corto:5s} solo {len(sub)} coppie, salto')
            continue
        X = [c['previsto'] for c in sub]
        Y = [c['reale'] for c in sub]
        a, b, sd = retta(X, Y)
        a_p, b_p = prod.get(corto, (float('nan'), float('nan')))
        risultati[corto] = {'n': len(sub), 'a': a, 'b': b, 'sd_residua': sd,
                             'a_prod': a_p, 'b_prod': b_p,
                             'prev60_reale': a + b * 60}
        riga = (f'{corto:5s} {len(sub):7d} {a:8.2f} {b:8.3f}  {a_p:8.2f} {b_p:8.3f}'
                f'  {a + b * 60:15.1f}  {sd:10.2f}')
        if args.bootstrap:
            sd_a, sd_b = bootstrap_incertezza(X, Y)
            risultati[corto]['bootstrap_sd_a'] = sd_a
            risultati[corto]['bootstrap_sd_b'] = sd_b
            riga += f'   (boot: a+/-{sd_a:.2f}, b+/-{sd_b:.3f})'
        print(riga)

    print('\n=== CONFRONTO CON I VALORI HARDCODED IN PRODUZIONE ===')
    for corto, r in risultati.items():
        da = r['a'] - r['a_prod']
        db = r['b'] - r['b_prod']
        entro_rumore = ''
        if 'bootstrap_sd_a' in r:
            entro_rumore = (' [entro 2 sigma bootstrap]'
                             if abs(da) < 2 * r['bootstrap_sd_a']
                             and abs(db) < 2 * r['bootstrap_sd_b']
                             else ' [FUORI 2 sigma bootstrap]')
        print(f'  {corto}: delta_a={da:+.2f}  delta_b={db:+.3f}{entro_rumore}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'n_totale': len(coppie), 'max_data': args.max_data,
                       'risultati': risultati}, fh, indent=1, ensure_ascii=False)
        print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
