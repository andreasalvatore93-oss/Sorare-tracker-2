"""Catena sez.16/19 applicata al Forward AMPIO (500 giocatori, 7497 righe,
291 squadre, multi-lega, sostituisce il campione Forward mirato scartato in
sez.20 perche' limitato a 2 leghe). Riusa p12_briefA_mid.py (V2/test2/V4) e
p12_briefA_arena_metrics.py (metriche di piazzamento) senza modificarli,
zero query. Output: Sezione 22 in HANDOFF_LETTERA_GRADE_2026-08-06.txt.
"""
import os, sys, io, json

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import importlib.util
spec = importlib.util.spec_from_file_location('briefA', 'analisi_manager/p12_briefA_mid.py')
briefA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(briefA)

spec2 = importlib.util.spec_from_file_location('arena_metrics', 'analisi_manager/p12_briefA_arena_metrics.py')
arena = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(arena)

PATH = 'analisi_manager/dati/storico_grade_Forward_ampio_20260806.json'

def main():
    result = briefA.esegui_ruolo('Forward', PATH, 'analisi_manager/p12_forward_ampio_out.json')

    players, n_dup = briefA.load_mid(PATH)
    rows, scarti = briefA.build_rows(players)
    v2, rows_v2 = briefA.run_v2(rows, ruolo='Forward')
    briefA._ctx_cache.clear()
    placement = None
    if rows_v2:
        placement = arena.report_ruolo('Forward', rows_v2=rows_v2)
    with open('analisi_manager/p12_forward_ampio_placement_out.json', 'w', encoding='utf-8') as fh:
        json.dump(placement, fh, ensure_ascii=False, indent=1)

    print('\n\n=== RIEPILOGO SALVATO ===')
    print('analisi_manager/p12_forward_ampio_out.json')
    print('analisi_manager/p12_forward_ampio_placement_out.json')

if __name__ == '__main__':
    main()
