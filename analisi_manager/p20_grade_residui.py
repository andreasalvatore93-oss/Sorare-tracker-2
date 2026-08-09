"""BRIEF_SONNET_GRADE_RESIDUI_2026-08-09.txt -- PASSO 1 SOLO: la tabella dei
residui (realizzato - atteso_di_produzione) per lettera del grade. SOLO
MISURA, nessuna query, nessuna modifica alla produzione.

Riusa l'indice grade e il campione di p20_tabella_grade.py (26.571 coppie
slug/data con punteggio in cache). L'atteso di produzione si ricostruisce
con backtest_arene_previsioni.score_atteso (P.score_atteso), la STESSA
funzione usata in p13_backtest_gw_crowss.py per il pool -- non calcola MAI
il grade al suo interno (grep: nessun riferimento a grade in
backtest_arene_previsioni.py), quindi e' gia' "atteso prima del grade" per
costruzione, nessun interruttore da spegnere. Calibrato con
generatore_formazioni.build_formazione_globale.calibra(atteso, codice_ruolo),
la stessa calibrazione di produzione, sulla stessa scala del punteggio
realizzato.

Limite dichiarato: score_atteso richiede il RUOLO (sceglie il modulo di
previsione), quindi il campione di questo script e' il sottoinsieme di
p20_tabella_grade.py con ruolo noto (dai file Defender/Midfielder/
Forward/Forward_ampio/Goalkeeper), non le 26.571 righe intere.
"""
import os
import sys
import io
import json
import random
import datetime
import statistics
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import p20_tabella_grade as T

random.seed(20260809)
cache = CACHE.CacheLocale()
LETTERE_ORDINE = T.LETTERE_ORDINE
ROLE_CODE = M.ROLE_CODE  # {'Goalkeeper':'GK', 'Defender':'DEF', 'Midfielder':'MID', 'Forward':'FWD'}


def costruisci_campione():
    """Stesse righe di p20_tabella_grade (grade + realizzato da cache), ma
    solo quelle con ruolo noto (serve a score_atteso). Ritorna lista di
    dict e contatori di scarto."""
    idx = T.costruisci_indice_principale()
    righe = []
    scarti = collections.Counter()
    for slug, entries in idx.items():
        ruolo_full = T.RUOLO_DA_FILE.get(slug)
        if ruolo_full is None:
            scarti['ruolo_ignoto'] += len(entries)
            continue
        codice = ROLE_CODE.get(ruolo_full)
        if codice is None:
            scarti['ruolo_non_mappato'] += len(entries)
            continue
        for data, grade in entries:
            score, status = T.score_esatto(slug, data)
            if score is None:
                scarti['no_cache_esatta'] += 1
                continue
            if status not in ('FINAL', 'REVIEWING', 'DID_NOT_PLAY'):
                scarti[f'status_{status}'] += 1
                continue
            righe.append({'slug': slug, 'data': data, 'grade': grade,
                          'ruolo': ruolo_full, 'codice': codice,
                          'realizzato': score, 'non_giocante': score <= 1})
    return righe, scarti


def aggancia_atteso(righe):
    """Per ogni riga, ricostruisce l'atteso di produzione (score_atteso +
    calibra), STESSA catena di p13_backtest_gw_crowss.costruisci_pool_rows.
    Scarta e conta chi non ha atteso ricostruibile (giocatore/finestra fuori
    dalla cache game-log)."""
    out = []
    scarti = collections.Counter()
    for r in righe:
        y, m, d = (int(x) for x in r['data'].split('-'))
        fine = datetime.datetime(y, m, d, 23, 59)
        res = P.score_atteso(cache, r['slug'], r['ruolo'], fine)
        if res is None or res.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        atteso_cal = S21.bfg.calibra(res['atteso'], r['codice'])
        rr = dict(r)
        rr['atteso_raw'] = res['atteso']
        rr['atteso_cal'] = atteso_cal
        rr['residuo'] = r['realizzato'] - atteso_cal
        out.append(rr)
    return out, scarti


def bootstrap_ci_per_giocatore(righe, n_iter=2000):
    """IC95 bootstrap sul residuo medio, CLUSTER = slug (non riga): si
    ricampionano i giocatori con reinserimento, non le singole righe."""
    per_slug = collections.defaultdict(list)
    for r in righe:
        per_slug[r['slug']].append(r['residuo'])
    slugs = list(per_slug.keys())
    if len(slugs) < 2:
        return None
    medie = []
    for _ in range(n_iter):
        campione_slug = [random.choice(slugs) for _ in slugs]
        vals = []
        for s in campione_slug:
            vals.extend(per_slug[s])
        if vals:
            medie.append(statistics.mean(vals))
    medie.sort()
    lo = medie[int(0.025 * len(medie))]
    hi = medie[int(0.975 * len(medie)) - 1]
    return lo, hi, len(slugs)


def main():
    righe, scarti_campione = costruisci_campione()
    print(f'righe con ruolo noto (input a score_atteso): {len(righe)}')
    print(f'scarti campione: {dict(scarti_campione)}')
    print()

    righe_atteso, scarti_atteso = aggancia_atteso(righe)
    print(f'righe con atteso ricostruito: {len(righe_atteso)}/{len(righe)}')
    print(f'scarti atteso: {dict(scarti_atteso)}')
    print()

    # --- verifica di sanita': stampa 5 righe con atteso/realizzato/grade ---
    print('=== VERIFICA (5 righe a campione: atteso_raw/atteso_cal/realizzato/grade) ===')
    for r in righe_atteso[:5]:
        print(f"  {r['slug']:30} {r['data']}  grade={r['grade']}  "
              f"atteso_raw={r['atteso_raw']:.2f}  atteso_cal={r['atteso_cal']:.2f}  "
              f"realizzato={r['realizzato']:.2f}  residuo={r['residuo']:+.2f}")
    print()

    # --- 1a. residuo medio per lettera, con bootstrap sul giocatore ---
    print('=== 1a. RESIDUO MEDIO PER LETTERA (bootstrap cluster=giocatore) ===')
    tabella_residui = {}
    for g in LETTERE_ORDINE:
        rr = [r for r in righe_atteso if r['grade'] == g]
        if not rr:
            tabella_residui[g] = None
            print(f'  {g}: n=0 VUOTA')
            continue
        vals = [r['residuo'] for r in rr]
        media = statistics.mean(vals)
        mediana = statistics.median(vals)
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        ic = bootstrap_ci_per_giocatore(rr)
        n_slug = len(set(r['slug'] for r in rr))
        tabella_residui[g] = {'n': len(vals), 'n_slug': n_slug, 'media': media,
                              'mediana': mediana, 'sd': sd,
                              'ic95': ic[:2] if ic else None}
        ic_txt = f"[{ic[0]:+.2f}, {ic[1]:+.2f}] (n_slug={ic[2]})" if ic else 'n/a (troppo pochi slug)'
        print(f"  {g}: n={len(vals):5d} (slug={n_slug:4d})  media={media:+6.2f}  "
              f"mediana={mediana:+6.2f}  sd={sd:6.2f}  IC95={ic_txt}")
    print()

    # --- 1d. test di monotonia sui residui ---
    seq = [(g, tabella_residui[g]['media']) for g in LETTERE_ORDINE if tabella_residui[g]]
    monotona = all(seq[i][1] >= seq[i - 1][1] for i in range(1, len(seq)))
    print(f'TEST DI MONOTONIA SUI RESIDUI (media deve crescere F->A): {"OK" if monotona else "FALLITO"}')
    print(f'  sequenza: {[(g, round(v,2)) for g, v in seq]}')
    print()

    # --- 1b. separando giocanti/non-giocanti ---
    print('=== 1b. RESIDUO PER LETTERA, GIOCANTI vs NON-GIOCANTI ===')
    for g in LETTERE_ORDINE:
        for label, filtro in (('giocanti', lambda r: not r['non_giocante']),
                              ('non-giocanti', lambda r: r['non_giocante'])):
            vals = [r['residuo'] for r in righe_atteso if r['grade'] == g and filtro(r)]
            if len(vals) < 30:
                print(f'  {g} ({label}): n={len(vals)} (<30, non commentato)')
                continue
            print(f'  {g} ({label}): n={len(vals):5d}  media={statistics.mean(vals):+6.2f}  '
                  f'mediana={statistics.median(vals):+6.2f}')
    print()

    # --- 1c. stratificato per ruolo ---
    print('=== 1c. RESIDUO PER LETTERA, STRATIFICATO PER RUOLO ===')
    for codice in ('GK', 'DEF', 'MID', 'FWD'):
        rr_ruolo = [r for r in righe_atteso if r['codice'] == codice]
        print(f'  --- {codice} (n totale {len(rr_ruolo)}) ---')
        for g in LETTERE_ORDINE:
            vals = [r['residuo'] for r in rr_ruolo if r['grade'] == g]
            if len(vals) < 30:
                print(f'    {g}: n={len(vals)} (<30, non commentato)')
                continue
            print(f'    {g}: n={len(vals):5d}  media={statistics.mean(vals):+6.2f}')
    print()

    out = {'tabella_residui': tabella_residui, 'monotona': monotona,
           'n_righe': len(righe_atteso), 'scarti_campione': dict(scarti_campione),
           'scarti_atteso': dict(scarti_atteso)}
    with open('analisi_manager/p20_grade_residui_out.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print('output json: analisi_manager/p20_grade_residui_out.json')

    # --- dump leggibile ---
    dump_path = 'analisi_manager/p20_grade_residui_dump.txt'
    with open(dump_path, 'w', encoding='utf-8') as fh:
        for g in LETTERE_ORDINE:
            campione = [r for r in righe_atteso if r['grade'] == g][:10]
            fh.write(f'--- Grade {g} ---\n')
            for r in campione:
                fh.write(f"  {r['slug']:35} {r['data']}  ruolo={r['codice']:4}  "
                         f"atteso_cal={r['atteso_cal']:7.2f}  realizzato={r['realizzato']:7.2f}  "
                         f"residuo={r['residuo']:+7.2f}  giocato={'no' if r['non_giocante'] else 'si'}\n")
            fh.write('\n')
    print(f'dump scritto in {dump_path}')


if __name__ == '__main__':
    sys.exit(main() or 0)
