"""Test a livello di CARTA (non GW) del filone "gruppo grade esteso alla
giornata" (11/08/2026). Proposta di Opus dopo il verdetto sulla finestra
temporale (docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §15):
le essenze per GW sommano premi a lotteria (rumore enorme, 360 unita'), la
stessa domanda a livello di carta ha ~28x le osservazioni e azzera il
rumore delle arene -- stesso disegno che aveva gia' chiuso in positivo
"il grade porta informazione a livello di carta" (placebo p=0,005).

Domanda: lo z-score del grade calcolato sul gruppo LARGO (pool_largo,
multi-manager per la stessa fixture) correla MEGLIO col residuo
(reale - atteso_calibrato) di quello calcolato sul gruppo NATIVO
(lega_ruolo, solo le carte del manager)?

Ipotesi PRIMA dei numeri: si', perche' in produzione (verificato da Opus
sui consigli veri su disco) il 51% dei gruppi (lega,ruolo) ha un solo
giocatore -- per quelle righe lega_ruolo da' SEMPRE zgrade=0 (return
anticipato in _apply_grade_group, build_formazione_globale.py:514-520),
quindi qualunque informazione reale del grade viene persa. pool_largo
dovrebbe recuperarne una parte. Se il risultato e' negativo o nullo, va
scritto cosi': significherebbe che il grade non porta segnale neppure
quando lo si puo' calcolare, non solo che il gruppo e' piccolo.

Uso: python analisi_manager/p46_grade_group_carta.py
"""
import os
import sys
import io
import json
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


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def main():
    fixtures = B2.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print(f'fixture processate: {len(pre_ok)} (su {len(fixtures)})')

    # Riferimento incrociato pool_largo (righe di TUTTI i manager per la
    # stessa fixture/lega/ruolo), identico a p24 main().
    esterno_per_fixture = collections.defaultdict(lambda: collections.defaultdict(list))
    for pre in pre_ok:
        for r in pre['pool_rows']:
            esterno_per_fixture[pre['fixture']][(r['lega'], r['codice'])].append(r)

    righe = []
    for pre in pre_ok:
        rows = pre['pool_rows']
        # dimensione del gruppo NATIVO (lega,ruolo) per QUESTO manager/fixture,
        # prima di applicare qualunque modalita' -- serve per stratificare.
        per_lega_ruolo_nativo = collections.defaultdict(int)
        for r in rows:
            per_lega_ruolo_nativo[(r['lega'], r['codice'])] += 1

        S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        for r in rows:
            r['_zgrade_lega_ruolo'] = r['_zgrade']
        S21.applica_gruppi_grade(rows, modo='pool_largo',
                                 riferimento_esterno=esterno_per_fixture[pre['fixture']])
        for r in rows:
            r['_zgrade_pool_largo'] = r['_zgrade']

        for r in rows:
            if r.get('_grade') is None or r.get('_cal') is None or r.get('reale') is None:
                continue
            righe.append({
                'manager': pre['manager'], 'fixture': pre['fixture'], 'slug': r['slug'],
                'lega': r['lega'], 'codice': r['codice'],
                'n_gruppo_nativo': per_lega_ruolo_nativo[(r['lega'], r['codice'])],
                'residuo': r['reale'] - r['_cal'],
                'z_lega_ruolo': r['_zgrade_lega_ruolo'],
                'z_pool_largo': r['_zgrade_pool_largo'],
            })

    print(f'righe con grade noto (base del test): {len(righe)}')
    n_gruppo1 = sum(1 for r in righe if r['n_gruppo_nativo'] < 2)
    print(f'  di cui con gruppo nativo < 2 (z_lega_ruolo sempre 0 per costruzione): '
          f'{n_gruppo1} ({100*n_gruppo1/len(righe):.1f}%)')

    def corr_pair(sub):
        a = pearson([r['z_lega_ruolo'] for r in sub], [r['residuo'] for r in sub])
        b = pearson([r['z_pool_largo'] for r in sub], [r['residuo'] for r in sub])
        return a, b

    def bootstrap(sub, n_boot=3000, seed=51):
        by_gw = collections.defaultdict(list)
        for r in sub:
            by_gw[(r['manager'], r['fixture'])].append(r)
        chiavi = list(by_gw.keys())
        rnd = random.Random(seed)
        diffs = []
        for _ in range(n_boot):
            camp = []
            for _i in range(len(chiavi)):
                k = chiavi[rnd.randrange(len(chiavi))]
                camp.extend(by_gw[k])
            a, b = corr_pair(camp)
            if a is None or b is None:
                continue
            diffs.append(b - a)
        diffs.sort()
        if not diffs:
            return None
        n = len(diffs)
        return {
            'n_boot': n, 'lo': diffs[int(0.025 * n)], 'hi': diffs[int(0.975 * n)],
            'pct_pool_largo_meglio': sum(1 for d in diffs if d > 0) / n,
        }

    print()
    print('=== TUTTE LE RIGHE ===')
    a, b = corr_pair(righe)
    print(f'  corr(z_lega_ruolo, residuo) = {a:+.4f}')
    print(f'  corr(z_pool_largo, residuo) = {b:+.4f}')
    boot = bootstrap(righe)
    print(f'  bootstrap (cluster manager-fixture, B={boot["n_boot"]}): '
          f'delta pool_largo-lega_ruolo IC95%=[{boot["lo"]:+.4f};{boot["hi"]:+.4f}] '
          f'pool_largo migliore nel {boot["pct_pool_largo_meglio"]*100:.1f}% dei casi')

    print()
    print("=== SOLO GRUPPO NATIVO < 2 (lega_ruolo da' sempre z=0) ===")
    sub = [r for r in righe if r['n_gruppo_nativo'] < 2]
    print(f'  n={len(sub)}')
    a, b = corr_pair(sub)
    print(f'  corr(z_lega_ruolo, residuo) = {a}')
    print(f'  corr(z_pool_largo, residuo) = {b:+.4f}')
    boot = bootstrap(sub)
    if boot:
        print(f'  bootstrap: delta IC95%=[{boot["lo"]:+.4f};{boot["hi"]:+.4f}] '
              f'pool_largo migliore nel {boot["pct_pool_largo_meglio"]*100:.1f}%')

    print()
    print("=== SOLO GRUPPO NATIVO >= 2 (lega_ruolo gia' attivo) ===")
    sub = [r for r in righe if r['n_gruppo_nativo'] >= 2]
    print(f'  n={len(sub)}')
    a, b = corr_pair(sub)
    print(f'  corr(z_lega_ruolo, residuo) = {a:+.4f}')
    print(f'  corr(z_pool_largo, residuo) = {b:+.4f}')
    boot = bootstrap(sub)
    if boot:
        print(f'  bootstrap: delta IC95%=[{boot["lo"]:+.4f};{boot["hi"]:+.4f}] '
              f'pool_largo migliore nel {boot["pct_pool_largo_meglio"]*100:.1f}%')

    print()
    print('=== DUMP: 10 righe a caso con gruppo nativo < 2 ===')
    rnd = random.Random(7)
    camp = rnd.sample([r for r in righe if r['n_gruppo_nativo'] < 2], k=min(10, n_gruppo1))
    for r in camp:
        print(f"  {r['manager']:12s} {r['fixture']:26s} {r['slug']:28s} lega={r['lega']:10s} "
              f"z_lega_ruolo={r['z_lega_ruolo']:+.2f} z_pool_largo={r['z_pool_largo']:+.2f} "
              f"residuo={r['residuo']:+.1f}")

    out_path = os.path.join('analisi_manager', 'dati', 'grade_group_carta_2026-08-11.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'n_righe': len(righe), 'n_gruppo1': n_gruppo1, 'righe': righe},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
