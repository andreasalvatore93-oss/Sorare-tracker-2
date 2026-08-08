"""PASSO 2 del brief BRIEF_SONNET_CRITERIO_ARENE_2026-08-08.txt -- controllo
di realta' RETROSPETTIVO (nessuna query): ROI per tipo di arena e per costo
d'ingresso, su TUTTI i manager e su crowss, con premi BASE (golden non
distinte -- dichiarato, sottostima il ROI vero ma non altera l'ordine fra
tipi, vedi CLAUDE.md D5).

Fonte: dati_globali/manager_*.json (54 file validi, come Fronte 2/D1-D7).
netto = premio(tipo, rank) - costo(tipo); ROI% = 100 * sum(netto) / sum(costo).

Uso:
  python analisi_manager/p21_criterio_arene_roi.py
"""
import os
import sys
import io
import json
import glob
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# Premi BASE e costo, le 4 tipologie osservate nei file manager con premi
# noti (Elite escluso: nessuna osservazione affidabile finora, vedi D-A
# HANDOFF_G_ARENE). Uncapped/Cap260/Cap220 dalla misura su p11_pool.json
# (673 arene, gia' in CLAUDE.md); Beginner da analisi_manager/valida_soglie.py.
PREMI = {
    'Cap 260':  {'costo': 300, 1: 1300, 2: 800, 3: 500},
    'Cap 220':  {'costo': 200, 1: 1000, 2: 500, 3: 300},
    'Uncapped': {'costo': 300, 1: 1300, 2: 800, 3: 500},
    'Beginner': {'costo': 100, 1: 500, 2: 250, 3: 150},
}
ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_uncapped', 'arena_limited_beginner'}


def netto_reale(tipo, rank):
    t = PREMI[tipo]
    return t.get(rank, 0) - t['costo']


def carica_manager_files():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json'))):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        if 'giornate' not in d:
            continue
        base = os.path.basename(path)
        nome = base[len('manager_'):-len('.json')]
        out[nome] = d
    return out


def raccogli_arene(manager_files, solo_manager=None):
    """Una riga per formazione arena con tipo/rank noti e premi definiti."""
    righe = []
    scarti = collections.Counter()
    for manager, d in manager_files.items():
        if solo_manager and manager not in solo_manager:
            continue
        for gw, formazioni in (d.get('giornate') or {}).items():
            for f in formazioni:
                if f.get('tipo_arena') not in ARENE_AMMESSE_TIPO:
                    continue
                comp = f.get('competizione')
                if comp not in PREMI:
                    scarti[f'competizione_sconosciuta:{comp}'] += 1
                    continue
                rank = (f.get('piazzamento') or {}).get('rank')
                if rank is None:
                    scarti['rank_mancante'] += 1
                    continue
                righe.append({'manager': manager, 'gw': gw, 'tipo': comp, 'rank': rank,
                             'netto': netto_reale(comp, rank), 'costo': PREMI[comp]['costo']})
    return righe, scarti


def stampa_roi(righe, etichetta):
    print(f'\n{"="*78}\n{etichetta}  (n={len(righe)} arene)\n{"="*78}')
    if not righe:
        print('  (nessuna arena)')
        return
    per_tipo = collections.defaultdict(list)
    per_costo = collections.defaultdict(list)
    for r in righe:
        per_tipo[r['tipo']].append(r)
        per_costo[r['costo']].append(r)

    print(f'\n  PER TIPO:')
    print(f'  {"tipo":10s} {"n":>6s} {"netto_tot":>12s} {"costo_tot":>12s} {"ROI%":>8s}')
    for tipo in ('Cap 260', 'Cap 220', 'Uncapped', 'Beginner'):
        rs = per_tipo.get(tipo, [])
        if not rs:
            continue
        netto_tot = sum(r['netto'] for r in rs)
        costo_tot = sum(r['costo'] for r in rs)
        roi = 100 * netto_tot / costo_tot if costo_tot else float('nan')
        print(f'  {tipo:10s} {len(rs):6d} {netto_tot:12.0f} {costo_tot:12.0f} {roi:7.1f}%')

    print(f'\n  PER COSTO D\'INGRESSO:')
    print(f'  {"costo":10s} {"n":>6s} {"netto_tot":>12s} {"costo_tot":>12s} {"ROI%":>8s}')
    for costo in sorted(per_costo, reverse=True):
        rs = per_costo[costo]
        netto_tot = sum(r['netto'] for r in rs)
        costo_tot = sum(r['costo'] for r in rs)
        roi = 100 * netto_tot / costo_tot if costo_tot else float('nan')
        print(f'  {costo:10d} {len(rs):6d} {netto_tot:12.0f} {costo_tot:12.0f} {roi:7.1f}%')

    netto_tot = sum(r['netto'] for r in righe)
    costo_tot = sum(r['costo'] for r in righe)
    print(f'\n  TOTALE: n={len(righe)}  netto={netto_tot:+.0f}  costo={costo_tot:.0f}  '
          f'ROI={100*netto_tot/costo_tot:.1f}%')


def main():
    print('=' * 78)
    print('PASSO 2 -- CONTROLLO DI REALTA\' RETROSPETTIVO (ROI per tipo/costo)')
    print('=' * 78)
    print('LIMITE dichiarato: premi BASE, golden NON distinte (CLAUDE.md D5) -- il')
    print('ROI assoluto e\' sottostimato, ma il moltiplicatore golden lascia il costo')
    print('dov\'e\' quindi NON cambia quale tipo conviene di piu\', solo il livello.')

    manager_files = carica_manager_files()
    print(f'\nfile manager validi: {len(manager_files)}')

    righe_tutti, scarti_tutti = raccogli_arene(manager_files)
    print(f'scarti (tutti i manager): {dict(scarti_tutti)}')
    stampa_roi(righe_tutti, 'TUTTI I MANAGER')

    righe_crowss, scarti_crowss = raccogli_arene(manager_files, solo_manager={'crowss'})
    print(f'\nscarti (crowss): {dict(scarti_crowss)}')
    stampa_roi(righe_crowss, 'SOLO crowss')

    print(f'\n{"="*78}')
    print('NOTA (brief 1d, da ripetere sempre insieme a questi numeri): la fonte')
    print('esterna indipendente (screenshot utente, 710 ingressi, ROI 11.79%) mostra')
    print('lo STESSO ORDINE fra tipi (cap220 > cap260 > uncapped > beginner per costo')
    print('investito) -- citata come fonte esterna, non ricalcolata qui. Due bias:')
    print('l\'utente selezionava le cap220 "a mano" (ROI gonfiato), e le cap220 hanno')
    print('strutturalmente meno ingressi (vincolo L10<=220), non e\' un difetto.')


if __name__ == '__main__':
    sys.exit(main() or 0)
