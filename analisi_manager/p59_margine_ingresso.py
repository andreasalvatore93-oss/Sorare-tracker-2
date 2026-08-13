# -*- coding: utf-8 -*-
"""CONVIENE GIOCARE LE ARENE APPENA SOPRA IL PAREGGIO? (13/08/2026)

DOMANDA DELL'UTENTE, sua formulazione: il generatore propone arene fino al
pareggio secco, ma lui nella realta' salta le marginali -- un po' per
prudenza, un po' perche' il budget di essenze di quella giornata e' finito.
Quindi: conviene davvero entrare a filo di pareggio, o rende di piu' un
margine di sicurezza?

COME SI MISURA. `genera_arene_efficienti` si ferma quando la resa attesa
della prossima arena scende sotto `costo_ingresso * margine_quota`. Con
margine 0.0 (default di produzione) si entra fino al pareggio secco. Qui si
gira la STESSA giornata, sullo STESSO pool, cambiando solo quel margine, e
si guarda quante arene si giocano e quante essenze si portano a casa DAVVERO
(realizzato, non atteso).

CONTESTO DA SAPERE PRIMA DI LEGGERE I NUMERI:
  - il repo ha gia' un verdetto in direzione "entrare conviene" (§5.9 del
    riassunto unificato, QUOTA_MINIMA chiusa il 13/08: +82,8 essenze per
    formazione nel primo periodo, +19,6 nel secondo, stesso segno). Era pero'
    un campione piccolo: questo lo rifa' su quello nuovo.
  - 0.10 non e' un numero inventato: e' QUOTA_MINIMA, gia' usata in
    produzione per l'ETICHETTA ("MARGINALE -- meglio All Stars da 7 o Under
    23") e dal Binario 1 per la decisione entra/salta.
  - piu' margine = meno arene = meno varianza ma anche meno premi. Il numero
    che decide e' il NETTO, non il numero di arene.

Uso:
  python analisi_manager/p59_margine_ingresso.py --fixture football-20-24-feb-2026
  python analisi_manager/p59_margine_ingresso.py            # tutto l'archivio
  python analisi_manager/p59_margine_ingresso.py --braccio A
"""
import os
import sys
import io
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
import p24_binario2_ga as B2  # noqa: E402

MARGINI = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]


def boot_per_manager(a, b, n_boot=3000, seed=20260813):
    """Ricampiona i MANAGER (cluster), non le singole giornate."""
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
    return ds[int(0.025 * n)], ds[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', action='append', default=[])
    ap.add_argument('--braccio', default='G', choices=['G', 'A'],
                    help='G = con il voto (produzione), A = senza voto')
    args = ap.parse_args()

    fixtures = B2.elenca_fixture()
    if args.fixture:
        fixtures = [f for f in fixtures if f[1] in set(args.fixture)]
    if not fixtures:
        print('nessuna fixture trovata con questo filtro')
        return

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            S21.applica_gruppi_grade(pre['pool_rows'], modo='lega_ruolo')
            pre_ok.append(pre)
    n_man = len(set(p['manager'] for p in pre_ok))
    print('unita\' manager-giornata: %d   manager distinti: %d   braccio: %s'
          % (len(pre_ok), n_man, args.braccio))
    if len(pre_ok) < 30:
        print('*** n piccolo: serve a vedere se la leva MUOVE, non a decidere. ***')
    print()

    chiave = 'ris_G' if args.braccio == 'G' else 'ris_A'
    per_margine = {}
    print('%-9s %8s %8s %10s %12s' % ('margine', 'arene', 'per un.', 'netto', 'vs margine 0'))
    base = None
    for mq in MARGINI:
        B2.MARGINE_QUOTA = mq
        netti, arene = {}, 0
        for pre in pre_ok:
            esito = B2.processa_fixture_pass2({k: pre[k] for k in
                                               ('manager', 'fixture', 'pool_size',
                                                'escluse_dnp', 'primo_kickoff', 'pool_rows')})
            k = (pre['manager'], pre['fixture'])
            netti[k] = sum(r['netto_stimato'] for r in esito[chiave])
            arene += len(esito[chiave])
        per_margine[mq] = netti
        tot = sum(netti.values())
        if base is None:
            base = netti
            print('%-9.2f %8d %8.1f %10.0f %12s' % (mq, arene, arene / len(pre_ok), tot, '--'))
        else:
            lo, hi = boot_per_manager(base, netti)
            d = tot - sum(base.values())
            print('%-9.2f %8d %8.1f %10.0f %12s'
                  % (mq, arene, arene / len(pre_ok), tot,
                     '%+.0f [%+.0f;%+.0f]' % (d, lo, hi)))
    B2.MARGINE_QUOTA = 0.0

    tutti = [sum(v.values()) for v in per_margine.values()]
    if max(tutti) - min(tutti) < 1e-9:
        print('\nLA LEVA NON MUOVE NIENTE su questo campione: nessuna arena'
              ' cade nella fascia')
        print('fra pareggio e margine. Il confronto e\' NULLO per costruzione,'
              ' non un pareggio.')
        return
    meglio = max(per_margine, key=lambda m: sum(per_margine[m].values()))
    print('\nmargine col netto piu\' alto su questo campione: %.2f' % meglio)
    print('ATTENZIONE: il massimo di una griglia e\' sempre il migliore di N'
          ' tentativi sugli')
    print('stessi dati. Conta il SEGNO e se l\'intervallo esclude lo zero, non'
          ' quale casella vince.')


if __name__ == '__main__':
    main()
