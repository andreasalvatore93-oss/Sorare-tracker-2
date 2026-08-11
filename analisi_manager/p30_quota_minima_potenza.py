"""QUOTA_MINIMA: quanto campione serve per sciogliere il disaccordo train/test.

Il grid di p29 confronta i TOTALI, ma fra due valori di q cambia solo la sorte
delle formazioni nella BANDA MARGINALE (quelle che entrano con q basso e non
con q alto). Tutte le altre entrano/non entrano in entrambi i casi e si
cancellano. Quindi:
  - il segno della decisione = segno del guadagno MEDIO delle formazioni
    marginali (positivo -> q basso meglio; negativo -> q alto meglio);
  - l'n che conta NON e' 778/272, ma quante formazioni cadono nella banda;
  - il campione necessario si calcola dalla dispersione di quel guadagno.

Uso: python analisi_manager/p30_quota_minima_potenza.py
"""
import os
import sys
import json
import math
import random
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p23_binario1_mga as B1
import generatore_formazioni.build_formazione_globale as BFG

TRAIN_END = datetime.datetime(2026, 6, 12)
TEST_START = datetime.datetime(2026, 7, 20)
Q_BASSO, Q_ALTO = 0.0, 0.15


def carica_righe():
    d = json.load(open(os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario1_out.json'),
                       encoding='utf-8'))
    righe = []
    for gw in d['per_gw']:
        dt = B1.fine_giornata_da_slug(gw['fixture'])
        for r in gw['risultati']:
            if r.get('punteggio_totale') is None:
                continue
            r2 = dict(r)
            r2['dt'] = dt
            r2['fixture'] = gw['fixture']
            t = B1.TIPO_TO_BFG[r2['tipo']]
            r2['soglia'] = BFG.PAREGGIO_ARENA[t]
            r2['costo'] = BFG.COSTO_INGRESSO[t]
            r2['guad'] = BFG.GUADAGNO_PER_PUNTO[t]
            r2['gain'] = (r2['punteggio_totale'] - r2['soglia']) * r2['guad']
            righe.append(r2)
    return righe


def soglia_dec(r, q):
    return r['soglia'] + r['costo'] * q / r['guad']


def banda(rows, qb, qa):
    """Formazioni che entrano con qb ma non con qa."""
    return [r for r in rows
            if r['atteso_G'] >= soglia_dec(r, qb) and r['atteso_G'] < soglia_dec(r, qa)]


def stat(vals):
    n = len(vals)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    return n, m, sd, sd / math.sqrt(n)


def boot_cluster(rows, chiave, B=2000, seed=20260813):
    """Bootstrap sul cluster (manager o fixture): le formazioni dello stesso
    manager non sono indipendenti."""
    rnd = random.Random(seed)
    gruppi = {}
    for r in rows:
        gruppi.setdefault(r.get(chiave), []).append(r['gain'])
    chiavi = list(gruppi)
    if len(chiavi) < 2:
        return None
    medie = []
    for _ in range(B):
        camp = []
        for _ in range(len(chiavi)):
            camp.extend(gruppi[chiavi[rnd.randrange(len(chiavi))]])
        if camp:
            medie.append(sum(camp) / len(camp))
    medie.sort()
    lo = medie[int(0.025 * len(medie))]
    hi = medie[int(0.975 * len(medie))]
    quota_pos = sum(1 for m in medie if m > 0) / len(medie)
    return lo, hi, quota_pos


def main():
    righe = carica_righe()
    train = [r for r in righe if r['dt'] <= TRAIN_END]
    test = [r for r in righe if r['dt'] >= TEST_START]
    print(f'righe totali {len(righe)} | train {len(train)} | test {len(test)}')
    print(f'chiave cluster disponibile: {sorted(set(righe[0]) & {"manager", "fixture"})}')
    print()

    for nome, rows in (('TRAIN', train), ('TEST', test), ('TRAIN+TEST', train + test)):
        b = banda(rows, Q_BASSO, Q_ALTO)
        n, m, sd, se = stat([r['gain'] for r in b])
        print(f'--- {nome} --- banda q={Q_BASSO} vs q={Q_ALTO}')
        print(f'  formazioni marginali n={n}  ({n / max(len(rows), 1):.1%} del campione)')
        print(f'  guadagno medio della formazione marginale: {m:+.1f}  sd {sd:.1f}  errore std {se:.1f}')
        print(f'  totale che si sposta: {m * n:+.0f}')
        for ch in ('manager', 'fixture'):
            if ch in (b[0] if b else {}):
                r_ = boot_cluster(b, ch)
                if r_:
                    lo, hi, qp = r_
                    print(f'  bootstrap su {ch}: IC95% [{lo:+.1f}, {hi:+.1f}], '
                          f'quota ricampionamenti con media>0 = {qp:.1%}')
        # quanta n servirebbe per un verdetto a 3 errori standard
        if sd > 0 and abs(m) > 0:
            n_serve = (3 * sd / abs(m)) ** 2
            print(f'  n marginali per |media| = 3 errori std, se l\'effetto vero fosse '
                  f'questo: {n_serve:.0f}')
        print()

    # quante formazioni marginali per GW-manager (per convertire n in giornate)
    b = banda(train + test, Q_BASSO, Q_ALTO)
    gw_man = {(r['fixture'], r.get('manager')) for r in (train + test)}
    print(f'unita GW-manager nel campione: {len(gw_man)}')
    print(f'formazioni per GW-manager: {len(train + test) / max(len(gw_man), 1):.1f}')
    print(f'formazioni MARGINALI per GW-manager: {len(b) / max(len(gw_man), 1):.2f}')


if __name__ == '__main__':
    main()
