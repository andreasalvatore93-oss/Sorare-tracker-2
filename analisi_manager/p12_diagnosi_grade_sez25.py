"""Sez.25 -- diagnosi PRIMA di rifare sez.24: dove si perde il segnale del
grade, a valle della copertura slug (che ora e' 678/678 = 100%).
Tre numeri: (1) righe pool con grade nella finestra della GW su totali,
(2) le stesse per ruolo, (3) quante hanno grade ma z-score azzerato perche'
sono l'UNICA carta con grade nel loro gruppo (lega,ruolo) quella giornata.
Zero query, riusa la stessa costruzione pool di p12_backtest_manager_full.py.
"""
import os, sys, io, json, glob, datetime, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p12_backtest_manager_grade as M
import p12_backtest_manager_full as F

cache = CACHE.CacheLocale()


def main():
    idx_grade, _ = M.carica_indice_grade_esteso()
    idx_grade_per_slug = collections.defaultdict(dict)
    for (slug, data), grade in idx_grade.items():
        idx_grade_per_slug[slug][data] = grade
    lega_di = AG.indice_lega()

    GRUPPO_A = ['braddersfc', 'eoghankelly', 'lairdinho', 'ninoshooter', 'shirimimi']
    fixtures = sorted({os.path.basename(f)[len('formazioni_'):-len('.json')]
                       for f in glob.glob('analisi_manager/dati/formazioni_football-*.json')})

    tot_righe = 0
    tot_con_grade = 0
    per_ruolo_tot = collections.Counter()
    per_ruolo_grade = collections.Counter()
    singleton_grade = 0  # ha grade ma e' l'unica nel suo gruppo (lega,codice) quella GW

    for man in GRUPPO_A:
        mf = f'dati_globali/manager_{man}.json'
        if not os.path.exists(mf):
            continue
        d = json.load(open(mf, encoding='utf-8'))
        giornate = d.get('giornate') or {}
        for gw in fixtures:
            giornate_gw = giornate.get(gw)
            if not giornate_gw:
                continue
            arene_reali = [f for f in giornate_gw if f.get('tipo_arena') in F.ARENE_AMMESSE_TIPO]
            if not arene_reali:
                continue
            tutte_le_carte = [c for f in arene_reali for c in (f.get('carte') or [])]
            pool = F.costruisci_pool(tutte_le_carte)
            slots_reali = [f for f in arene_reali if f['competizione'] in F.COMP_TO_BUILD]
            if not slots_reali:
                continue
            b = M.parse_fixture_bounds(gw)
            if b is None:
                continue
            d_start, d_end = b
            fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)

            pool_rows = []
            for carta_id, c in pool.items():
                ruolo_full = c.get('ruolo')
                cod = M.ROLE_CODE.get(ruolo_full)
                if cod is None:
                    continue
                slug = c.get('slug')
                r = P.score_atteso(cache, slug, ruolo_full, fine)
                if r is None or r.get('atteso') is None:
                    continue
                raw = c.get('punteggio')
                if raw is None:
                    continue
                lega = lega_di.get(slug) or 'senza_lega'
                grade = F.trova_grade_finestra(idx_grade_per_slug, slug, d_start, d_end)
                pool_rows.append({'slug': slug, 'codice': cod, 'lega': lega, '_grade': grade})
            if len(pool_rows) < 5:
                continue

            for c in pool_rows:
                tot_righe += 1
                per_ruolo_tot[c['codice']] += 1
                if c['_grade'] is not None:
                    tot_con_grade += 1
                    per_ruolo_grade[c['codice']] += 1

            gruppi = collections.defaultdict(list)
            for c in pool_rows:
                gruppi[(c['lega'], c['codice'])].append(c)
            for (lg, cod), membri in gruppi.items():
                con_grade = [m for m in membri if m['_grade'] is not None]
                if len(con_grade) == 1:
                    singleton_grade += 1

    print(f'--- PUNTO 1: righe pool con grade utilizzabile nella finestra ---')
    print(f'  {tot_con_grade}/{tot_righe} ({100*tot_con_grade/tot_righe:.1f}%)')

    print(f'\n--- PUNTO 2: per ruolo ---')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        tot = per_ruolo_tot[cod]
        cg = per_ruolo_grade[cod]
        pct = 100 * cg / tot if tot else 0.0
        print(f'  {cod}: {cg}/{tot} ({pct:.1f}%)')

    print(f'\n--- PUNTO 3: carte con grade ma z-score azzerato (unica con grade nel suo gruppo lega,ruolo,GW) ---')
    print(f'  {singleton_grade}/{tot_con_grade} righe-con-grade sono "singole" nel loro gruppo '
          f'(su {tot_con_grade} righe con grade totali)')


if __name__ == '__main__':
    main()
