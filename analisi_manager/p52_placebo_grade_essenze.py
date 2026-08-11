# -*- coding: utf-8 -*-
"""CALIBRAZIONE NULLA (placebo) del guadagno essenze del grade -- Opus
esecutore, 12/08/2026.

Perche' esiste: sullo stesso campione di 360 GW-manager oggi sono state
provate molte varianti (2 fonti x fattore x ricentraggio globale/per ruolo/
assente x fix celle n<2). Il numero riportato e' sempre il massimo della
ricerca, e il suo "% positivo" e' calcolato COME SE quella variante fosse
stata scelta prima di vedere i dati. Questo script misura quanto e' facile
ottenere un numero cosi' PER PURO CASO con la stessa identica macchina.

Metodo: si tiene tutto uguale (stesso pool, stessa tabella, stesso fattore,
stesso fix celle n<2, stesso ricentraggio per ruolo, stesso bootstrap) e si
rompe SOLO il legame fra il voto e il giocatore -- il grade viene rimescolato
fra le righe DENTRO la stessa GW-manager (stessa distribuzione di voti, stessi
mancanti, giocatore sbagliato). Se un voto finto produce spesso guadagni della
taglia di quello vero, il guadagno vero non e' dimostrato.

Uso: python analisi_manager/p52_placebo_grade_essenze.py [n_permutazioni]
Nessuna query di rete, nessuna modifica alla produzione.
"""
import os
import sys
import io
import json
import time
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p24_binario2_ga as B2
import p51_grade_essenze_fix as P51

GRADE_SCALE_PATH = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')
FATTORE = 0.75          # braccio archivio, lo stesso di p51


def gioca(pre_ok, tab_sd, fattore, permuta_seed=None, verbose=False):
    """Stessa ricetta di p51 (fix i gia' dentro la tabella, fix ii qui):
    se permuta_seed e' dato, il grade viene rimescolato fra le righe della
    STESSA GW-manager prima di applicare la formula."""
    varianti = []
    rnd = random.Random(permuta_seed) if permuta_seed is not None else None
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if rnd is not None:
            voti = [r.get('_grade') for r in rows]
            rnd.shuffle(voti)
            for r, g in zip(rows, voti):
                r['_grade'] = g
        S21.applica_gruppi_grade(rows, modo='storica_completa',
                                 tabella_sd_storica=tab_sd, fattore_storico=fattore)
        varianti.append((pre, rows))

    tutte = [r for _p, rows in varianti for r in rows]
    per_ruolo = collections.defaultdict(list)
    for r in tutte:
        per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
    media = {c: sum(v) / len(v) for c, v in per_ruolo.items()}
    for r in tutte:
        r['_combinato'] = round(r['_combinato'] - media[r['codice']], 2)
    if verbose:
        print('    ricentraggio per ruolo: ' + ', '.join(f'{k}={v:+.3f}' for k, v in sorted(media.items())))

    out = {}
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def main():
    n_perm = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    t0 = time.time()
    fixtures = B2.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print(f'fixture processate: {len(pre_ok)}   [pass1 {time.time()-t0:.0f}s]', flush=True)

    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)

    righe_arch = [r for pre in pre_ok for r in pre['pool_rows']]
    tab_arch, n_tolte = P51.costruisci_tabella_senza_celle_piccole(righe_arch)
    print(f'celle n<2 tolte: {n_tolte}', flush=True)

    tot_base = P51.gioca(pre_ok, 'lega_ruolo')
    print('--- braccio VERO (archivio 0,75, fix i+ii) ---', flush=True)
    tot_vero = gioca(pre_ok, tab_arch, FATTORE, verbose=True)
    r_vero = P51.boot(tot_base, tot_vero)
    print(f"VERO: delta {r_vero['delta']:+.0f}  IC95%=[{r_vero['lo']:+.0f};{r_vero['hi']:+.0f}]  "
          f"positivo {r_vero['pct']*100:.1f}%   [{time.time()-t0:.0f}s]", flush=True)

    print(f'\n--- {n_perm} placebo (grade rimescolato dentro la GW) ---', flush=True)
    nulli = []
    for i in range(n_perm):
        tot_p = gioca(pre_ok, tab_arch, FATTORE, permuta_seed=1000 + i)
        r = P51.boot(tot_base, tot_p, n_boot=2000, seed=7 + i)
        nulli.append((r['delta'], r['pct']))
        print(f"  placebo {i+1:2d}: delta {r['delta']:+7.0f}  positivo {r['pct']*100:5.1f}%  "
              f"[{time.time()-t0:.0f}s]", flush=True)

    deltas = sorted(d for d, _ in nulli)
    print('\n=== CALIBRAZIONE NULLA ===')
    print(f"delta VERO: {r_vero['delta']:+.0f} ({r_vero['pct']*100:.1f}% positivo)")
    print(f"placebo: mediana {deltas[len(deltas)//2]:+.0f}  min {deltas[0]:+.0f}  max {deltas[-1]:+.0f}")
    piu_grandi = sum(1 for d, _ in nulli if d >= r_vero['delta'])
    almeno_95 = sum(1 for _d, p in nulli if p >= 0.95)
    print(f"placebo con delta >= del vero: {piu_grandi}/{len(nulli)}")
    print(f"placebo che arrivano a >=95% positivo: {almeno_95}/{len(nulli)}")

    out = os.path.join('analisi_manager', 'dati', 'placebo_grade_essenze_2026-08-12.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({'vero': r_vero, 'placebo': [{'delta': d, 'pct': p} for d, p in nulli]},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio: {out}   [totale {time.time()-t0:.0f}s]')


if __name__ == '__main__':
    main()
