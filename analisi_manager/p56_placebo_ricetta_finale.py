# -*- coding: utf-8 -*-
"""Placebo + diagnostica di MECCANISMO sulla RICETTA FINALE (p55) -- Opus
esecutore, 12/08/2026 notte.

Perche' serve un secondo placebo: quello di p52 girava sulla ricetta
VECCHIA (sd archivio, tabella voto vecchia, ricentraggio PER RUOLO). La
ricetta finale e' un'altra cosa: tabella voto di produzione, ricentraggio
GLOBALE. Con la tabella voto di produzione la spinta cieca per ruolo e'
molto diversa fra ruoli (p54: GK+0,83 DEF+2,91 MID+2,17 FWD+3,06), quindi
una costante globale (~+2,34) lascia un residuo sistematico grosso e di
segno opposto sui portieri (~-1,5 pt, e la sd dell'atteso GK e' solo 2,25):
il modello potrebbe guadagnare non perche' ordina meglio, ma perche' abbassa
in blocco i portieri e quindi GIOCA MENO ARENE. Le arene marginali possono
perdere essenze, quindi giocarne meno e' un guadagno meccanico che non ha
niente a che fare col voto.

Due controlli, sulla ricetta finale esatta:
  1) placebo: voto rimescolato dentro la GW-manager, tutto il resto uguale.
     Se il finto guadagna quanto il vero, il guadagno e' del meccanismo.
  2) conteggio arene giocate e residuo per ruolo dopo il ricentraggio
     globale: dice SE il meccanismo sopra e' attivo e quanto.

Uso: python analisi_manager/p56_placebo_ricetta_finale.py [n_permutazioni]
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

GRADE_SCALE_PRODUZIONE = os.path.join('analisi_manager', 'dati', 'grade_scala_produzione_2026-08-12.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati', 'sd_atteso_produzione_righe.json')
FATTORE = 0.482


def gioca(pre_ok, tab_sd, baseline=False, permuta_seed=None, verbose=False):
    """Ricetta finale di p55; se baseline=True usa il modo 'lega_ruolo'.
    Ritorna (essenze_per_gw, n_arene_totali)."""
    varianti = []
    rnd = random.Random(permuta_seed) if permuta_seed is not None else None
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if rnd is not None:
            voti = [r.get('_grade') for r in rows]
            rnd.shuffle(voti)
            for r, g in zip(rows, voti):
                r['_grade'] = g
        if baseline:
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        else:
            S21.applica_gruppi_grade(rows, modo='storica_completa',
                                     tabella_sd_storica=tab_sd, fattore_storico=FATTORE)
        varianti.append((pre, rows))

    if not baseline:
        tutte = [r for _p, rows in varianti for r in rows]
        media = sum(r['_combinato'] - r['_cal'] for r in tutte) / len(tutte)
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media, 2)
        if verbose:
            per_ruolo = collections.defaultdict(list)
            for r in tutte:
                per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
            print(f'  costante globale tolta: {media:+.3f}')
            print('  residuo per ruolo DOPO il ricentraggio globale: ' +
                  ', '.join(f'{k}={sum(v)/len(v):+.3f}' for k, v in sorted(per_ruolo.items())))

    out = {}
    n_arene = 0
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
        n_arene += len(esito['ris_G'])
    return out, n_arene


def boot(a, b, n_boot=5000, seed=20260812):
    chiavi = sorted(set(a) & set(b))
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        camp = [chiavi[rnd.randrange(len(chiavi))] for _i in range(len(chiavi))]
        ds.append(sum(b[k] for k in camp) - sum(a[k] for k in camp))
    ds.sort()
    n = len(ds)
    return {'n_gw': len(chiavi), 'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n}


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

    with open(GRADE_SCALE_PRODUZIONE, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_prod)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_prod)
    for k, n in conteggio.items():
        if n < 2 and k in tab_sd['lega_ruolo']:
            del tab_sd['lega_ruolo'][k]

    tot_base, arene_base = gioca(pre_ok, tab_sd, baseline=True)
    print(f'baseline: G={sum(tot_base.values()):+.0f}  arene giocate={arene_base}', flush=True)
    print('--- ricetta finale VERA ---', flush=True)
    tot_vero, arene_vero = gioca(pre_ok, tab_sd, verbose=True)
    r_vero = boot(tot_base, tot_vero)
    print(f"VERO: G={sum(tot_vero.values()):+.0f}  arene={arene_vero} "
          f"({arene_vero-arene_base:+d} vs baseline)  delta {r_vero['delta']:+.0f} "
          f"IC95%=[{r_vero['lo']:+.0f};{r_vero['hi']:+.0f}] {r_vero['pct']*100:.1f}%  "
          f"[{time.time()-t0:.0f}s]", flush=True)

    print(f'\n--- {n_perm} placebo sulla RICETTA FINALE ---', flush=True)
    nulli = []
    for i in range(n_perm):
        tot_p, arene_p = gioca(pre_ok, tab_sd, permuta_seed=2000 + i)
        r = boot(tot_base, tot_p, n_boot=2000, seed=17 + i)
        nulli.append({'delta': r['delta'], 'pct': r['pct'], 'arene': arene_p})
        print(f"  placebo {i+1:2d}: delta {r['delta']:+7.0f}  positivo {r['pct']*100:5.1f}%  "
              f"arene {arene_p} ({arene_p-arene_base:+d})  [{time.time()-t0:.0f}s]", flush=True)

    ds = sorted(x['delta'] for x in nulli)
    print('\n=== CALIBRAZIONE NULLA SULLA RICETTA FINALE ===')
    print(f"VERO: {r_vero['delta']:+.0f} ({r_vero['pct']*100:.1f}%), arene {arene_vero-arene_base:+d} vs baseline")
    print(f"placebo: mediana {ds[len(ds)//2]:+.0f}  min {ds[0]:+.0f}  max {ds[-1]:+.0f}")
    print(f"placebo con delta >= del vero: {sum(1 for d in ds if d >= r_vero['delta'])}/{len(ds)}")
    print(f"placebo che arrivano a >=95% positivo: {sum(1 for x in nulli if x['pct'] >= 0.95)}/{len(nulli)}")
    arene_p_medie = sum(x['arene'] for x in nulli) / len(nulli)
    print(f"arene giocate: baseline {arene_base}, vero {arene_vero}, placebo in media {arene_p_medie:.0f}")

    out = os.path.join('analisi_manager', 'dati', 'placebo_ricetta_finale_2026-08-12.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({'vero': r_vero, 'arene_baseline': arene_base, 'arene_vero': arene_vero,
                   'placebo': nulli}, fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio: {out}   [totale {time.time()-t0:.0f}s]')


if __name__ == '__main__':
    main()
