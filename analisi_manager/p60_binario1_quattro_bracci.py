# -*- coding: utf-8 -*-
"""BINARIO 1 A QUATTRO BRACCI -- M vs A vs G-variabile vs G-fisso (13/08/2026).

Il Binario 1 gira su FORMAZIONI FISSE: le cinque carte e il capitano sono
quelli che il manager ha davvero schierato, e nessuno li cambia. L'unica
differenza fra i bracci e' la decisione ENTRA / SALTA quell'arena.
  M           -- il manager reale: entra sempre (e' quello che e' successo),
                 quindi incassa sempre il premio_netto vero.
  A           -- decide sull'atteso calibrato, senza voto (`_cal`).
  G-variabile -- PRODUZIONE DI OGGI: voto col gruppo nativo (lega, ruolo)
                 dentro la giornata; dove il gruppo ha meno di 2 membri il
                 voto si spegne da solo.
  G-fisso     -- LA VARIANTE DA VALIDARE: voto sempre applicato, tabelle
                 congelate il 12/08, fattore 0,482, ricentraggio per ruolo.
Chi non entra fa 0 su quella formazione: non paga l'ingresso e non prende
premi.

PERCHE' ESISTE: p23_binario1_mga.py ne gira TRE (M, A, G) e non sa filtrare
per giornata. Il quarto braccio non c'era perche' G-fisso doveva essere
validato solo dopo il 25/08 -- scelta di calendario, non statistica.

REGOLA D'INGRESSO: `soglia + costo * QUOTA_MINIMA / guadagno_per_punto`
(p23_binario1_mga.py:201), cioe' si entra se il guadagno atteso vale almeno
il 10% di quello che si rischia. E' la stessa regola dell'etichetta di
produzione, ed e' come gioca davvero l'utente. ATTENZIONE: e' DIVERSA da
quella del Binario 2, che entra fino al pareggio secco (vedi
analisi_manager/p59_margine_ingresso.py, che misura quanto conta).

DNP: dall'11/08 il filtro e' SPENTO di default (ESCLUDI_DNP=1 lo riaccende).
Il filtro toglieva il 19,3% delle formazioni, precisamente quelle andate
peggio, e gonfiava M da +11.500 a +42.500. Lo script stampa quale regime sta
usando: se leggi un numero di M molto alto, guarda prima quella riga.

Uso:
  python analisi_manager/p60_binario1_quattro_bracci.py --fixture football-20-24-feb-2026
  python analisi_manager/p60_binario1_quattro_bracci.py
"""
import os
import sys
import io
import json
import random
import argparse
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p23_binario1_mga as B1  # noqa: E402

GRADE_SCALE_PATH = os.path.join('analisi_manager', 'dati',
                                'grade_scala_produzione_cutoff_2026-08-14.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati',
                                  'sd_atteso_produzione_righe_cutoff_2026-08-14.json')
FATTORE = 0.482


def carica_tabelle_congelate():
    for p in (GRADE_SCALE_PATH, SD_PRODUZIONE_PATH):
        if not os.path.exists(p):
            print(f'ERRORE: manca la tabella congelata {p}')
            return None
    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_prod)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_prod)
    for k, n in conteggio.items():
        if n < 2 and k in tab_sd['lega_ruolo']:
            del tab_sd['lega_ruolo'][k]
    return tab_sd


def righe_con_voto(pre_ok, modo, tab_sd=None, fattore=1.0, ricentra=False):
    """Una copia delle righe del pool per ogni unita', col voto applicato
    secondo `modo`. Il pool grezzo NON viene toccato: i bracci devono
    partire tutti dalle stesse carte."""
    fuori = []
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if modo == 'lega_ruolo':
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        else:
            S21.applica_gruppi_grade(rows, modo='storica_completa',
                                     tabella_sd_storica=tab_sd,
                                     fattore_storico=fattore)
        fuori.append(rows)
    if ricentra:
        tutte = [r for rows in fuori for r in rows]
        per_ruolo = collections.defaultdict(list)
        for r in tutte:
            per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
        media = {c: sum(v) / len(v) for c, v in per_ruolo.items()}
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media[r['codice']], 2)
        print('  ricentraggio per ruolo: '
              + ', '.join(f'{k}={v:+.3f}' for k, v in sorted(media.items())))
    return fuori


def boot_per_manager(a, b, n_boot=5000, seed=20260813):
    chiavi = sorted(set(a) & set(b))
    per_man = collections.defaultdict(list)
    for k in chiavi:
        per_man[k[0]].append(k)
    manager = sorted(per_man)
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        tot = 0.0
        for _i in range(len(manager)):
            m = manager[rnd.randrange(len(manager))]
            for k in per_man[m]:
                tot += b[k] - a[k]
        ds.append(tot)
    ds.sort()
    n = len(ds)
    return {'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n,
            'n_unita': len(chiavi), 'n_manager': len(manager),
            'discordanti': sum(1 for k in chiavi if abs(b[k] - a[k]) > 1e-9)}


def confronto(eti, a, b):
    r = boot_per_manager(a, b)
    print('%-28s %+9.0f   IC95%%[%+8.0f ; %+8.0f]  positivo %5.1f%%   cambia in %d/%d'
          % (eti, r['delta'], r['lo'], r['hi'], r['pct'] * 100,
             r['discordanti'], r['n_unita']))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', action='append', default=[])
    ap.add_argument('--manager', action='append', default=[],
                    help='limita a uno o piu\' manager (ripetibile). Con '
                         '--manager crowss si confronta l\'utente CON SE '
                         'STESSO: stesso mazzo, stesse arene, stesse '
                         'giornate, cambia solo chi decide se entrare. Per '
                         'crowss vengono lette solo le fixture pre_2026-08-07, '
                         'cioe' + " quando schierava a mano (B1.elenca_fixture).")
    args = ap.parse_args()

    fixtures = B1.elenca_fixture()
    if args.fixture:
        fixtures = [f for f in fixtures if f[1] in set(args.fixture)]
    if args.manager:
        fixtures = [f for f in fixtures if f[0] in set(args.manager)]
    if not fixtures:
        print('nessuna fixture trovata con questo filtro')
        return

    print('=' * 92)
    print('BINARIO 1 A QUATTRO BRACCI -- M vs A vs G-variabile vs G-fisso')
    print('formazioni FISSE, cambia solo la decisione entra/salta')
    print('filtro DNP: %s' % ('ACCESO (ESCLUDI_DNP=1) -- attenzione, gonfia M'
                              if B1.ESCLUDI_DNP else 'spento (default dall\'11/08)'))
    print('=' * 92)

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B1.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    if not pre_ok:
        print('nessuna unita\' utilizzabile.')
        return
    n_man = len(set(p['manager'] for p in pre_ok))
    print('unita\' manager-giornata: %d   manager distinti: %d' % (len(pre_ok), n_man))
    if len(pre_ok) < 30:
        print('*** n piccolo: serve a vedere se la catena gira, NON a decidere. ***')

    tab_sd = carica_tabelle_congelate()
    if tab_sd is None:
        return
    print('\n--- voto: gruppo nativo (G-variabile) ---')
    righe_var = righe_con_voto(pre_ok, 'lega_ruolo')
    print('--- voto: tabelle congelate (G-fisso, fattore %.3f) ---' % FATTORE)
    righe_fis = righe_con_voto(pre_ok, 'storica_completa', tab_sd, FATTORE, ricentra=True)

    netti = {k: {} for k in ('M', 'A', 'Gvar', 'Gfis')}
    entrate = collections.Counter()
    n_form = 0
    for pre, rv, rf in zip(pre_ok, righe_var, righe_fis):
        k = (pre['manager'], pre['fixture'])
        for nome in netti:
            netti[nome].setdefault(k, 0.0)
        mappa_v = {r['carta']: r for r in rv}
        mappa_f = {r['carta']: r for r in rf}
        for form in pre['pulite']:
            _a, _s, entra_A = B1.decidi_entra(mappa_v, form, '_cal')
            if entra_A is None:
                continue
            _a2, _s2, entra_A2 = B1.decidi_entra(mappa_f, form, '_cal')
            if entra_A2 != entra_A:
                print('TEST A/A FALLITO su %s %s: il braccio A cambia fra le due'
                      ' passate. Non leggere oltre.' % k)
                return
            _g1, _s3, entra_Gv = B1.decidi_entra(mappa_v, form, '_combinato')
            _g2, _s4, entra_Gf = B1.decidi_entra(mappa_f, form, '_combinato')
            netto = form['premio_netto']
            n_form += 1
            netti['M'][k] += netto
            entrate['M'] += 1
            for nome, entra in (('A', entra_A), ('Gvar', entra_Gv), ('Gfis', entra_Gf)):
                if entra:
                    netti[nome][k] += netto
                    entrate[nome] += 1

    print('\nTEST A/A sul braccio A: OK, identico fra le due passate')
    print('formazioni valutate: %d' % n_form)
    print('\n%-14s %10s %10s' % ('braccio', 'entra in', 'netto'))
    for nome, eti in (('M', 'M (reale)'), ('A', 'A (senza voto)'),
                      ('Gvar', 'G-variabile'), ('Gfis', 'G-fisso')):
        print('%-14s %10d %10.0f' % (eti, entrate[nome], sum(netti[nome].values())))

    print('\nDELTA APPAIATI (bootstrap ricampionando i MANAGER):')
    confronto('A          - M', netti['M'], netti['A'])
    confronto('G-variabile - M', netti['M'], netti['Gvar'])
    confronto('G-fisso     - M', netti['M'], netti['Gfis'])
    confronto('G-variabile - A', netti['A'], netti['Gvar'])
    r = confronto('G-fisso - G-variabile', netti['Gvar'], netti['Gfis'])
    if r['discordanti'] == 0:
        print('\nZERO unita\' discordanti fra G-fisso e G-variabile: prendono le'
              ' stesse decisioni,')
        print('quindi il confronto e\' NULLO PER COSTRUZIONE, non un pareggio.')


if __name__ == '__main__':
    main()
