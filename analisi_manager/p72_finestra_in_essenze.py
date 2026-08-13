# -*- coding: utf-8 -*-
"""LA FINESTRA STORICA, MISURATA IN ESSENZE (14/08/2026)

PERCHE'. p71 ha confrontato MAX_HISTORY_DAYS = 365 contro 730 e 1095 con i
tre indicatori del banco: il segno e' positivo su tutti e tre e a entrambe
le finestre, ma solo il MAE supera il proprio rumore (-0,011 contro un
tremolio documentato di 0,003); la correlazione guadagna 0,0008, che e'
esattamente il tremolio, e il lift 0,111 contro un rumore misurato di +/-1,6.
Un indicatore su tre. Non abbastanza per toccare la produzione.

Serve quindi il metro che decide davvero, quello che stanotte ha promosso il
voto A-F e bocciato la correzione intralega: **le essenze**, sullo stesso
archivio, con lo stesso Binario 2 e lo stesso bootstrap sui manager.

COSA CONFRONTA. Le stesse unita' manager-giornata, lo stesso pool, la stessa
regola di scelta: cambia SOLO quanto storico il modello guarda per stimare
ogni carta. Braccio G (produzione, voto acceso).

ATTENZIONE: qui non basta rifare la passata 2 come per il voto. La finestra
cambia l'ATTESO di ogni carta, quindi va rifatta anche la passata 1 -- che e'
la parte cara. Un giro per finestra.

Uso: python analisi_manager/p72_finestra_in_essenze.py
"""
import os
import sys
import io
import random
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
import backtest_arene_previsioni as P  # noqa: E402

FINESTRE = [365, 730]


def gioca_tutto(lega_di, idx_grade):
    """netto del braccio G per unita', con la finestra impostata ora."""
    fuori = {}
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        S21.applica_gruppi_grade(pre['pool_rows'], modo='lega_ruolo')
        esito = B2.processa_fixture_pass2(pre)
        fuori[(manager, fx)] = sum(x['netto_stimato'] for x in esito['ris_G'])
    return fuori


def boot(a, b, n_boot=5000, seed=20260814):
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
            'n': len(chiavi), 'man': len(manager),
            'disc': sum(1 for k in chiavi if abs(b[k] - a[k]) > 1e-9)}


def main():
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    esiti = {}
    for g in FINESTRE:
        P.MAX_HISTORY_DAYS = g
        esiti[g] = gioca_tutto(lega_di, idx_grade)
        print('finestra %4d giorni -> netto totale %+.0f  (%d unita\')'
              % (g, sum(esiti[g].values()), len(esiti[g])))
    P.MAX_HISTORY_DAYS = 365

    a, b = esiti[FINESTRE[0]], esiti[FINESTRE[1]]
    r = boot(a, b)
    print()
    print('DELTA %d - %d giorni (bootstrap ricampionando i MANAGER):'
          % (FINESTRE[1], FINESTRE[0]))
    print('  %+.0f essenze   IC95[%+.0f;%+.0f]   positivo %.1f%%'
          % (r['delta'], r['lo'], r['hi'], r['pct'] * 100))
    print('  unita\': %d (%d manager)   cambia davvero in %d'
          % (r['n'], r['man'], r['disc']))
    print('  per unita\': %+.1f essenze' % (r['delta'] / max(1, r['n'])))
    print()
    if r['disc'] == 0:
        print('ZERO unita\' discordanti: la finestra non cambia NESSUNA scelta.')
        print('Test nullo per costruzione, non un pareggio.')
    elif r['lo'] > 0:
        print('L\'intervallo esclude lo zero: allungare la finestra PAGA, e si')
        print('puo\' cambiare MAX_HISTORY_DAYS dietro verifica della catena')
        print('(soglie arena + scouting, regola CLAUDE.md).')
    elif r['hi'] < 0:
        print('L\'intervallo e\' sotto lo zero: allungare la finestra COSTA.')
        print('Il taglio a 365 giorni va tenuto, e ora si sa perche\'.')
    else:
        print('L\'intervallo contiene lo zero: nessuna prova che paghi ne\' che')
        print('costi. Con un effetto cosi\' piccolo la scelta e\' di merito, non')
        print('di misura -- e in dubbio non si tocca la produzione.')


if __name__ == '__main__':
    main()
