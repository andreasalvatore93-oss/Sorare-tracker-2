"""Test a livello di CARTA (non GW) del filone "gruppo grade esteso alla
giornata" (11/08/2026). Round 2, risposta di Opus §16
(RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt): il round 1 aveva confrontato
solo lo z-score del grade, non l'AGGIUSTAMENTO vero (sd_atteso * z) che e'
quello che sposta 'atteso'/_combinato in produzione. pool_largo allargava
DUE scale insieme (sd_atteso e grade), non una sola.

QUATTRO BRACCI, stesso identico test (correlazione fra aggiustamento e
residuo = reale - atteso_calibrato, bootstrap cluster manager-fixture):
  1. lega_ruolo    -- baseline produzione (gruppo nativo, entrambe le
                       scale dal gruppetto (lega,ruolo,manager,fixture)).
  2. pool_largo    -- tetto teorico (entrambe le scale da TUTTI i manager
                       della stessa fixture -- non disponibile in
                       produzione, serve solo come limite superiore).
  3. storica_grade -- SOLO gm/gsd del grade dalla tabella storica
                       (generatore_formazioni/dati/grade_scala_storica.json,
                       gia' in produzione dietro GRADE_SCALE='storica').
                       sd_atteso resta dal gruppo nativo (quindi ~0 per i
                       gruppi di 1 carta: l'aggiustamento si azzera lo
                       stesso li', anche se lo z e' ben definito).
  4. storica_completa -- gm/gsd E sd_atteso ENTRAMBI dalla storia,
                       calcolata sulla stessa materia prima gia' in repo
                       (10.255 righe binario2_pool_rows.json, _cal per
                       lega/codice) -- unico pezzo NUOVO, piccolo.

IPOTESI PRE-REGISTRATA (Opus, prima dei numeri): 1 < 3 < 4 <= 2. Se esce
3 > 4 o 4 > 2 e' un errore di implementazione, non una scoperta -- va
fermato e corretto, non interpretato.

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

GRADE_SCALE_PATH = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')


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


def _media_sd(vals):
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return m, sd


def costruisci_tabella_sd_atteso(tutte_le_righe):
    """Stessa gerarchia a 3 livelli di grade_scala_storica.json
    (lega_ruolo -> ruolo -> globale), stessa materia prima (10.255 righe
    gia' in repo), ma per la SD di _cal (non per il grade). Pezzo nuovo,
    piccolo -- richiesto da Opus §16 punto (ii)/(iii)."""
    per_lega_ruolo = collections.defaultdict(list)
    per_ruolo = collections.defaultdict(list)
    tutti = []
    for r in tutte_le_righe:
        per_lega_ruolo[(r['lega'], r['codice'])].append(r['_cal'])
        per_ruolo[r['codice']].append(r['_cal'])
        tutti.append(r['_cal'])
    tab_lega_ruolo = {k: _media_sd(v) for k, v in per_lega_ruolo.items()}
    tab_ruolo = {k: _media_sd(v) for k, v in per_ruolo.items()}
    tab_globale = _media_sd(tutti)
    return tab_lega_ruolo, tab_ruolo, tab_globale


def sd_atteso_storico(tab, lega, codice):
    tab_lr, tab_r, tab_g = tab
    if (lega, codice) in tab_lr:
        return tab_lr[(lega, codice)][1]
    if codice in tab_r:
        return tab_r[codice][1]
    return tab_g[1]


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

    # Attiva la tabella storica del grade (normalmente dietro
    # GRADE_SCALE='storica', qui la carichiamo direttamente per riusare
    # ESATTAMENTE bfg._scala_storica_per, nessuna reimplementazione).
    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    print(f'tabella storica grade caricata: {GRADE_SCALE_PATH}')

    esterno_per_fixture = collections.defaultdict(lambda: collections.defaultdict(list))
    for pre in pre_ok:
        for r in pre['pool_rows']:
            esterno_per_fixture[pre['fixture']][(r['lega'], r['codice'])].append(r)

    tutte_le_righe_grezze = [r for pre in pre_ok for r in pre['pool_rows']]
    tab_sd = costruisci_tabella_sd_atteso(tutte_le_righe_grezze)
    print(f'tabella storica sd_atteso: {len(tab_sd[0])} coppie lega-ruolo, '
          f'{len(tab_sd[1])} ruoli, globale sd={tab_sd[2][1]:.2f} (n={len(tutte_le_righe_grezze)})')

    righe = []
    for pre in pre_ok:
        rows = pre['pool_rows']
        per_lega_ruolo_nativo = collections.defaultdict(int)
        for r in rows:
            per_lega_ruolo_nativo[(r['lega'], r['codice'])] += 1

        # Braccio 1: lega_ruolo (baseline produzione).
        S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        for r in rows:
            r['_agg_1'] = r['_combinato'] - r['_cal']

        # Braccio 2: pool_largo (tetto teorico).
        S21.applica_gruppi_grade(rows, modo='pool_largo',
                                 riferimento_esterno=esterno_per_fixture[pre['fixture']])
        for r in rows:
            r['_agg_2'] = r['_combinato'] - r['_cal']

        # Braccio 3: storica SOLO sul grade (gm/gsd storici, sd_atteso
        # nativo -- ~0 per i gruppi di 1, l'aggiustamento si azzera lo
        # stesso li' anche se lo z sotto e' ben definito).
        for r in rows:
            scala = S21.bfg._scala_storica_per(r['lega'], r['codice'])
            gm, gsd, _liv = scala if scala else (0.0, 0.0, None)
            z = (r['_grade'] - gm) / gsd if (r['_grade'] is not None and gsd > 0) else 0.0
            gruppo_nativo = [m for m in rows if m['lega'] == r['lega'] and m['codice'] == r['codice']]
            _m_att, sd_atteso_nativo = _media_sd([m['_cal'] for m in gruppo_nativo])
            r['_agg_3'] = sd_atteso_nativo * z

        # Braccio 4: storica su grade E su sd_atteso (nessuna dipendenza
        # dal gruppetto nativo).
        for r in rows:
            scala = S21.bfg._scala_storica_per(r['lega'], r['codice'])
            gm, gsd, _liv = scala if scala else (0.0, 0.0, None)
            z = (r['_grade'] - gm) / gsd if (r['_grade'] is not None and gsd > 0) else 0.0
            sd_atteso_stor = sd_atteso_storico(tab_sd, r['lega'], r['codice'])
            r['_agg_4'] = sd_atteso_stor * z

        for r in rows:
            if r.get('_grade') is None or r.get('_cal') is None or r.get('reale') is None:
                continue
            righe.append({
                'manager': pre['manager'], 'fixture': pre['fixture'], 'slug': r['slug'],
                'lega': r['lega'], 'codice': r['codice'],
                'n_gruppo_nativo': per_lega_ruolo_nativo[(r['lega'], r['codice'])],
                'residuo': r['reale'] - r['_cal'],
                'agg_1_lega_ruolo': r['_agg_1'], 'agg_2_pool_largo': r['_agg_2'],
                'agg_3_storica_grade': r['_agg_3'], 'agg_4_storica_completa': r['_agg_4'],
            })

    print(f'righe con grade noto (base del test): {len(righe)}')
    n_gruppo1 = sum(1 for r in righe if r['n_gruppo_nativo'] < 2)
    print(f'  di cui con gruppo nativo < 2: {n_gruppo1} ({100*n_gruppo1/len(righe):.1f}%)')

    campi = ['agg_1_lega_ruolo', 'agg_2_pool_largo', 'agg_3_storica_grade', 'agg_4_storica_completa']
    etichette = {'agg_1_lega_ruolo': '1 lega_ruolo', 'agg_2_pool_largo': '2 pool_largo (tetto)',
                'agg_3_storica_grade': '3 storica_grade', 'agg_4_storica_completa': '4 storica_completa'}

    def corr_tutti(sub):
        return {c: pearson([r[c] for r in sub], [r['residuo'] for r in sub]) for c in campi}

    def bootstrap_coppia(sub, campo_a, campo_b, n_boot=3000, seed=51):
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
            a = pearson([r[campo_a] for r in camp], [r['residuo'] for r in camp])
            b = pearson([r[campo_b] for r in camp], [r['residuo'] for r in camp])
            if a is None or b is None:
                continue
            diffs.append(b - a)
        diffs.sort()
        if not diffs:
            return None
        n = len(diffs)
        return {'n_boot': n, 'lo': diffs[int(0.025 * n)], 'hi': diffs[int(0.975 * n)],
                'pct_positivo': sum(1 for d in diffs if d > 0) / n}

    coppie = [('agg_1_lega_ruolo', 'agg_3_storica_grade', '1 vs 3'),
             ('agg_1_lega_ruolo', 'agg_4_storica_completa', '1 vs 4'),
             ('agg_1_lega_ruolo', 'agg_2_pool_largo', '1 vs 2'),
             ('agg_3_storica_grade', 'agg_4_storica_completa', '3 vs 4'),
             ('agg_4_storica_completa', 'agg_2_pool_largo', '4 vs 2 (arriva al tetto?)')]

    for nome, filtro in (('TUTTE LE RIGHE', lambda r: True),
                         ('SOLO GRUPPO NATIVO >= 2 (il numero che decide, Opus §16)',
                          lambda r: r['n_gruppo_nativo'] >= 2),
                         ('SOLO GRUPPO NATIVO < 2 (qui il braccio 1 e 3 sono ~0 per costruzione)',
                          lambda r: r['n_gruppo_nativo'] < 2)):
        sub = [r for r in righe if filtro(r)]
        print(f'\n=== {nome} === n={len(sub)}')
        corr = corr_tutti(sub)
        for c in campi:
            v = corr[c]
            print(f'  {etichette[c]:24s} corr={v:+.4f}' if v is not None else f'  {etichette[c]:24s} corr=indefinita (varianza zero)')
        for campo_a, campo_b, etichetta_coppia in coppie:
            boot = bootstrap_coppia(sub, campo_a, campo_b)
            if boot:
                print(f'    {etichetta_coppia}: delta IC95%=[{boot["lo"]:+.4f};{boot["hi"]:+.4f}] '
                      f'positivo (b>a) nel {boot["pct_positivo"]*100:.1f}%')

    out_path = os.path.join('analisi_manager', 'dati', 'grade_group_carta_bracci_2026-08-11.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'n_righe': len(righe), 'n_gruppo1': n_gruppo1, 'righe': righe},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
