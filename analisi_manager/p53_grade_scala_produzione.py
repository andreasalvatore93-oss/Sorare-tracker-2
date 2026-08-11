# -*- coding: utf-8 -*-
"""(a) Ricostruisce la tabella del VOTO (gm/gsd per lega-ruolo) sulla STESSA
popolazione che poi si punteggia, non su "tutte le carte mai viste"
(grade_scala_storica.json, da dati_globali/manager_*.json).

Causa della spinta cieca, misurata da Opus (docs/HANDOFF_UNIFICATO_
MODELLO_SCOUTING.md §8bis-bis "Controllo placebo"): il pool che si
punteggia e' POST-DNP e POST-filtro starter-odds (solo probabili
titolari, voto medio 4,12), la tabella storica ha TUTTE le carte (voto
medio 3,10) -- discrepanza di popolazione, +1,02 in ogni ruolo. Qui si
ricostruisce il gm/gsd usando le stesse righe di
analisi_manager/dati/sd_atteso_produzione_righe.json (consiglio_*.txt,
gia' filtrate/dedup da p47 -- stessa popolazione della tabella sd_atteso),
con il grade agganciato via l'indice condiviso (S21.grade_in_finestra),
non da dati_globali/manager_*.json.

Uso: python analisi_manager/p53_grade_scala_produzione.py
Scrive analisi_manager/dati/grade_scala_produzione_2026-08-12.json, stesso
formato JSON di generatore_formazioni/dati/grade_scala_storica.json
(per_lega_ruolo/per_ruolo/globale con mean/sd/n) cosi' e' caricabile
direttamente in bfg._GRADE_SCALE_TABLE per i test successivi.
"""
import os
import sys
import io
import json
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21

SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati', 'sd_atteso_produzione_righe.json')
OUT_PATH = os.path.join('analisi_manager', 'dati', 'grade_scala_produzione_2026-08-12.json')
SOGLIA_LEGA_RUOLO = 30  # piu' bassa di p18 (100): qui la popolazione e' piccola (2.333 righe
                        # contro 20.955), e Opus ha misurato che soglie alte peggiorano (§8bis-bis
                        # punto 2) -- soglia bassa solo per evitare celle a n<2, non per "pulire" il rumore


def main():
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe = json.load(f)
    idx_grade, data_min = S21.carica_indice_grade()
    print(f'righe di produzione (input): {len(righe)}')
    print(f'prima data con grade disponibile: {data_min}')

    per_lr = collections.defaultdict(list)
    per_r = collections.defaultdict(list)
    tutti = []
    n_senza_grade = 0
    for r in righe:
        gn = S21.grade_in_finestra(idx_grade, r['slug'], r['kickoff'][:10])
        if gn is None:
            n_senza_grade += 1
            continue
        per_lr[(r['lega'], r['codice'])].append(gn)
        per_r[r['codice']].append(gn)
        tutti.append(gn)

    n_con_grade = len(tutti)
    print(f'righe con grade agganciato: {n_con_grade} ({100*n_con_grade/len(righe):.1f}%), '
          f'senza: {n_senza_grade}')

    def media_sd(vals):
        n = len(vals)
        m = sum(vals) / n
        sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
        return m, sd, n

    out_lr = {}
    for (lega, ruolo), vals in per_lr.items():
        if len(vals) >= SOGLIA_LEGA_RUOLO:
            m, sd, n = media_sd(vals)
            out_lr[f'{lega}|{ruolo}'] = {'mean': m, 'sd': sd, 'n': n}
    out_r = {}
    for ruolo, vals in per_r.items():
        m, sd, n = media_sd(vals)
        out_r[ruolo] = {'mean': m, 'sd': sd, 'n': n}
    globale = media_sd(tutti)
    globale = {'mean': globale[0], 'sd': globale[1], 'n': globale[2]}

    print(f'\ncelle (lega,ruolo) sopra soglia {SOGLIA_LEGA_RUOLO}: {len(out_lr)} / {len(per_lr)} totali')
    print('scala per ruolo:')
    for ruolo, v in sorted(out_r.items()):
        print(f'  {ruolo:4s} mean={v["mean"]:.3f} sd={v["sd"]:.3f} n={v["n"]}')
    print(f'globale: mean={globale["mean"]:.3f} sd={globale["sd"]:.3f} n={globale["n"]}')

    scala = {'per_lega_ruolo': out_lr, 'per_ruolo': out_r, 'globale': globale,
              'meta': {'fonte': 'consiglio_*.txt (stessa popolazione di sd_atteso_produzione)',
                       'soglia_lega_ruolo': SOGLIA_LEGA_RUOLO, 'n_righe_input': len(righe),
                       'n_con_grade': n_con_grade, 'n_senza_grade': n_senza_grade}}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(scala, fh, ensure_ascii=False, indent=2)
    print(f'\nsalvato: {OUT_PATH}')

    # confronto diretto con la tabella vecchia (dati_globali/manager_*.json), per misurare
    # se la discrepanza di popolazione (+1.02 per ruolo, misurata da Opus) si e' davvero tolta
    old_path = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')
    with open(old_path, encoding='utf-8') as f:
        vecchia = json.load(f)
    print('\nconfronto media per ruolo (nuova - vecchia, deve avvicinarsi a 0 se la causa e\' giusta):')
    for ruolo in sorted(out_r):
        nuova_m = out_r[ruolo]['mean']
        vecchia_m = vecchia.get('per_ruolo', {}).get(ruolo, {}).get('mean')
        if vecchia_m is not None:
            print(f'  {ruolo:4s} nuova={nuova_m:.3f}  vecchia={vecchia_m:.3f}  scarto={nuova_m-vecchia_m:+.3f}')


if __name__ == '__main__':
    main()
