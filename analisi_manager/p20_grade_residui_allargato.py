"""BRIEF_SONNET_SCORE_E_GRADE_2026-08-09.txt -- TRACCIA 2, punto A: allargare
il campione della tabella residui (p20_grade_residui.py) recuperando il
ruolo anche da dati_globali/manager_*.json, dove il collo di bottiglia era
"ruolo non ricostruibile dai file grade" (17.700 righe scartate su 26.571).

Precedenza dichiarata: 1) ruolo dai file grade di produzione (Defender/
Midfielder/Forward/Forward_ampio/Goalkeeper -- gia' quello di
p20_tabella_grade.RUOLO_DA_FILE); 2) se assente, ruolo DOMINANTE dello slug
nei file manager (D7 CLAUDE.md: il ruolo e' della CARTA non del giocatore,
quindi quando i file manager mostrano ruoli discordanti per lo stesso slug
si conta e si dichiara, non si sceglie a caso -- qui si usa comunque il
dominante per poter calcolare l'atteso, ma il conteggio dei discordanti e'
riportato separatamente).

SOLO MISURA, nessuna modifica di produzione.
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
import p20_grade_residui as R

random.seed(20260809)
cache = CACHE.CacheLocale()
LETTERE_ORDINE = T.LETTERE_ORDINE
ROLE_CODE = M.ROLE_CODE
CODE_TO_FULL = {v: k for k, v in ROLE_CODE.items()}


def costruisci_mappa_ruolo_manager():
    """slug -> (ruolo_dominante, conteggio_per_ruolo). Scansiona
    dati_globali/manager_*.json UNA volta, nessuna query."""
    import glob
    conteggio = collections.defaultdict(collections.Counter)
    for fp in glob.glob('dati_globali/manager_*.json'):
        d = json.load(open(fp, encoding='utf-8'))
        for gw, forms in (d.get('giornate') or {}).items():
            for f in forms:
                for c in f.get('carte') or []:
                    s, r = c.get('slug'), c.get('ruolo')
                    if s and r:
                        conteggio[s][r] += 1
    mappa = {}
    for s, c in conteggio.items():
        dominante = c.most_common(1)[0][0]
        mappa[s] = (dominante, dict(c))
    return mappa


def costruisci_campione_allargato():
    idx = T.costruisci_indice_principale()
    mappa_manager = costruisci_mappa_ruolo_manager()
    righe = []
    scarti = collections.Counter()
    discordanti_usati = 0
    for slug, entries in idx.items():
        ruolo_full = T.RUOLO_DA_FILE.get(slug)
        fonte = 'file_grade'
        if ruolo_full is None:
            info = mappa_manager.get(slug)
            if info is None:
                scarti['ruolo_ignoto'] += len(entries)
                continue
            ruolo_full, conteggio_ruoli = info
            fonte = 'manager_dominante'
            if len(conteggio_ruoli) > 1:
                discordanti_usati += 1
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
                          'ruolo': ruolo_full, 'codice': codice, 'fonte_ruolo': fonte,
                          'realizzato': score, 'non_giocante': score <= 1})
    return righe, scarti, discordanti_usati


def main():
    righe, scarti, discordanti_usati = costruisci_campione_allargato()
    n_manager = sum(1 for r in righe if r['fonte_ruolo'] == 'manager_dominante')
    print(f'righe con ruolo noto (campione allargato): {len(righe)}')
    print(f'  di cui da file grade di produzione: {len(righe) - n_manager}')
    print(f'  di cui da ruolo dominante nei file manager: {n_manager} '
          f'(slug con ruoli discordanti fra loro: {discordanti_usati})')
    print(f'scarti campione: {dict(scarti)}')
    print()

    righe_atteso, scarti_atteso = R.aggancia_atteso(righe)
    print(f'righe con atteso ricostruito: {len(righe_atteso)}/{len(righe)}')
    print(f'scarti atteso: {dict(scarti_atteso)}')
    print()

    print('=== TABELLA RESIDUI -- CAMPIONE ALLARGATO vs CAMPIONO DI IERI ===')
    tabella_nuova = {}
    for g in LETTERE_ORDINE:
        rr = [r for r in righe_atteso if r['grade'] == g]
        if not rr:
            tabella_nuova[g] = None
            print(f'  {g}: n=0 VUOTA')
            continue
        vals = [r['residuo'] for r in rr]
        media = statistics.mean(vals)
        ic = R.bootstrap_ci_per_giocatore(rr)
        n_slug = len(set(r['slug'] for r in rr))
        tabella_nuova[g] = {'n': len(vals), 'n_slug': n_slug, 'media': media, 'ic95': ic[:2] if ic else None}
        ic_txt = f"[{ic[0]:+.2f}, {ic[1]:+.2f}]" if ic else 'n/a'
        print(f"  {g}: n={len(vals):6d} (slug={n_slug:4d})  media={media:+6.2f}  IC95={ic_txt}")
    print()

    seq = [(g, tabella_nuova[g]['media']) for g in LETTERE_ORDINE if tabella_nuova[g]]
    monotona = all(seq[i][1] >= seq[i - 1][1] for i in range(1, len(seq)))
    print(f'TEST DI MONOTONIA SUL CAMPIONE ALLARGATO: {"OK" if monotona else "FALLITO"}')
    print(f'  sequenza: {[(g, round(v,2)) for g, v in seq]}')
    print()

    # confronto diretto B vs C sui due campioni
    print('=== FOCUS INVERSIONE B/C: campione di ieri vs campione allargato ===')
    print(f"  ieri (n=9.727):     B={-99:.2f}  -- vedi §9.2 handoff per i valori esatti")
    if tabella_nuova.get('B') and tabella_nuova.get('C'):
        b, c = tabella_nuova['B']['media'], tabella_nuova['C']['media']
        print(f"  allargato: B={b:+.2f} (n={tabella_nuova['B']['n']})  C={c:+.2f} (n={tabella_nuova['C']['n']})  "
              f"differenza C-B={c-b:+.2f}")

    out = {'tabella_residui_allargata': tabella_nuova, 'monotona': monotona,
           'n_righe': len(righe_atteso), 'n_da_manager': n_manager,
           'discordanti_usati': discordanti_usati, 'scarti_campione': dict(scarti),
           'scarti_atteso': dict(scarti_atteso)}
    with open('analisi_manager/p20_grade_residui_allargato_out.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print('output json: analisi_manager/p20_grade_residui_allargato_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
