# -*- coding: utf-8 -*-
"""Costruisce le righe (lega, codice, _cal) per la tabella sd_atteso "di
produzione" -- filone gruppo grade esteso alla giornata, priorita' 2
(11/08/2026), punto 1 di "cosa manca" in docs/HANDOFF_UNIFICATO_MODELLO_
SCOUTING.md §8bis-bis.

Fonte decisa da Opus esecutore il 12/08/2026 (vedi §8bis-bis "Fonte per
sd_atteso"), verificata nel codice dall'orchestratore prima di scrivere
questo script: i `consiglio_*.txt` in formazione_<lega>/output/<lega>_
<ruolo>_all/ sono LETTERALMENTE le righe su cui la produzione calcola oggi
_apply_grade_group (build_formazione_globale.py:1109-1152, load_
league_role_data -> parse_consiglio + calibra_riga -> _apply_grade_group).
Costruire la tabella su queste righe passate e' quindi la stessa
grandezza/popolazione/funzioni della produzione, zero query, zero
ricalcolo del modello -- niente a che fare con l'archivio backtest (29
manager) usato finora, che restava un proxy.

Trappola obbligatoria (da Opus): la stessa giornata viene riconsigliata
decine di volte al giorno (stesso slug+kickoff, run diverse dello stesso
generatore) -- serve DEDUP per (lega, codice, slug, kickoff), altrimenti le
fixture ri-girate piu' spesso pesano 18x. Qui si tiene, per ogni chiave, la
riga con il timestamp file (dal NOME, mai dall'mtime -- vedi CLAUDE.md
run_verde_non_vuol_dire_riuscita e _ts_da_nome_consiglio) PIU' RECENTE.

Uso:
  python analisi_manager/p47_sd_atteso_produzione.py
  (scrive analisi_manager/dati/sd_atteso_produzione_righe.json: lista di
  righe deduplicate {lega, codice, slug, kickoff, atteso_raw, _cal};
  stampa anche l'aggregazione con costruisci_tabella_sd_atteso() di
  p12_backtest_formazione_grade.py, giusto per un'anteprima -- il builder
  vero della tabella resta quella funzione, qui si producono solo le righe
  in input).

Funzione riusabile: costruisci_righe_produzione(cutoff=None) -- cutoff e'
un datetime.datetime, walk-forward: usa solo consigli con timestamp file <
cutoff (stesso schema di p18_grade_scala_storica.costruisci_scala).
"""
import os
import sys
import io
import glob
import json
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_produzione as BP
import p12_backtest_formazione_grade as S21

bfg = BP.bfg
bff = BP.bff

OUT_PATH = os.path.join(ROOT, 'analisi_manager', 'dati', 'sd_atteso_produzione_righe.json')


def costruisci_righe_produzione(cutoff=None):
    """Ritorna (righe_dedup, stats). righe_dedup: lista di dict {lega,
    codice, slug, kickoff, atteso_raw, _cal}. stats: conteggi di controllo
    (n_file, n_righe_totali, n_righe_distinte, per_ruolo_grezzo)."""
    scelte = {}  # (lega, codice, slug, kickoff) -> (ts_file, atteso_raw)
    n_file = 0
    n_righe_totali = 0

    for lega in bfg.LEAGUES:
        for codice in bfg.ROLES:
            out_dir = bfg.CONSIGLIO_DIRS[lega][codice]
            abs_dir = os.path.join(ROOT, out_dir) if not os.path.isabs(out_dir) else out_dir
            for path in sorted(glob.glob(os.path.join(abs_dir, 'consiglio_*.txt'))):
                ts = bfg._ts_da_nome_consiglio(path)
                if ts is None:
                    continue
                if cutoff is not None and not (ts < cutoff):
                    continue
                n_file += 1
                for row in bff.parse_consiglio(path):
                    n_righe_totali += 1
                    slug = row.get('slug')
                    kickoff = row.get('kickoff')
                    atteso_raw = row.get('atteso')
                    if slug is None or kickoff is None or atteso_raw is None:
                        continue
                    chiave = (lega, codice, slug, kickoff)
                    prec = scelte.get(chiave)
                    if prec is None or ts > prec[0]:
                        scelte[chiave] = (ts, atteso_raw)

    righe = []
    per_ruolo_grezzo = collections.Counter()
    for (lega, codice, slug, kickoff), (ts, atteso_raw) in scelte.items():
        cal = bfg.calibra(atteso_raw, codice)
        righe.append({'lega': lega, 'codice': codice, 'slug': slug, 'kickoff': kickoff,
                      'atteso_raw': atteso_raw, '_cal': cal})
        per_ruolo_grezzo[codice] += 1

    stats = {
        'n_file': n_file,
        'n_righe_totali': n_righe_totali,
        'n_righe_distinte': len(righe),
        'per_ruolo_grezzo': dict(per_ruolo_grezzo),
    }
    return righe, stats


def main():
    righe, stats = costruisci_righe_produzione(cutoff=None)
    print('=' * 78)
    print('RIGHE DI PRODUZIONE PER sd_atteso (fonte: consiglio_*.txt, deduplicate)')
    print('=' * 78)
    print(f"file consiglio letti: {stats['n_file']}")
    print(f"righe totali (pre-dedup): {stats['n_righe_totali']}")
    print(f"righe distinte (lega,codice,slug,kickoff): {stats['n_righe_distinte']}")
    print(f"per ruolo (grezzo, pre-calibrazione): {stats['per_ruolo_grezzo']}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(righe, fh, ensure_ascii=False, indent=1)
    print(f"\nsalvato: {OUT_PATH}")

    tabella = S21.costruisci_tabella_sd_atteso(righe)
    print('\n--- anteprima aggregazione (costruisci_tabella_sd_atteso) ---')
    print(f"globale: mean={tabella['globale'][0]:.2f} sd={tabella['globale'][1]:.2f}")
    print('per ruolo:')
    for codice in sorted(tabella['ruolo']):
        m, sd = tabella['ruolo'][codice]
        n = stats['per_ruolo_grezzo'].get(codice, 0)
        print(f"  {codice:4s} mean={m:.2f} sd={sd:.2f} n={n}")
    print(f"celle (lega,ruolo) distinte: {len(tabella['lega_ruolo'])}")
    grandi = [(k, v) for k, v in tabella['lega_ruolo'].items()]
    print('prime 10 celle per n (serve un conteggio n per cella: ricalcolo qui sotto)')
    conteggio_celle = collections.Counter((r['lega'], r['codice']) for r in righe)
    for k, n in conteggio_celle.most_common(10):
        m, sd = tabella['lega_ruolo'][k]
        print(f"  {k[0]:20s} {k[1]:4s} n={n:5d} mean={m:.2f} sd={sd:.2f}")
    n_sopra_100 = sum(1 for n in conteggio_celle.values() if n >= 100)
    print(f"\ncelle (lega,ruolo) con n>=100: {n_sopra_100} / {len(conteggio_celle)}")


if __name__ == '__main__':
    sys.exit(main() or 0)
