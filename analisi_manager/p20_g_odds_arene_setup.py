"""BRIEF_SONNET_G_ODDS_ARENE_2026-08-09.txt -- verifica preliminare
(perimetro, §3; regimi/pool-vs-slot, §4/§7a) PRIMA di costruire il
backtest vero. Nessuna modifica alla produzione, nessuna query di rete.

Riusa la stessa normalizzazione leaderboard di
p20_grade_arene_copertura_finale.py (import diretto, non riscritta).
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
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_manager_grade as M
import p20_grade_arene_copertura_finale as G

GW6 = G.GW6
GRUPPI = G.GRUPPI


def costruisci_pool_globale(righe):
    """§4: pool = tutte le carte che il manager ha schierato quella
    giornata, in QUALUNQUE competizione (stessa costruzione di
    p13.costruisci_pool modo='globale', per identita' di carta = 'carta')."""
    pool = set()
    for f in righe:
        for c in (f.get('carte') or []):
            cid = c.get('carta')
            if cid:
                pool.add(cid)
    return pool


def main():
    formazioni = G.raccogli_formazioni()
    print(f'formazioni perimetro: {len(formazioni)} (atteso 825)')
    tot_per_gruppo = collections.Counter(f['gruppo'] for f in formazioni)
    for g in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        print(f'  {g:12s} {tot_per_gruppo[g]:4d} formazioni')
    tot_carte = sum(len(f['carte']) for f in formazioni)
    print(f'carte totali: {tot_carte} (atteso 4125)')

    per_unita = collections.defaultdict(list)
    for f in formazioni:
        per_unita[(f['manager'], f['gw'])].append(f)
    print(f'\nunita (manager,gw) con almeno 1 arena nel perimetro: {len(per_unita)}')

    files = {os.path.basename(fp)[len('manager_'):-len('.json')]: fp
             for fp in glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json'))}

    astensione, allocazione = [], []
    rapporti = []
    for (manager, gw), forms in per_unita.items():
        dati = json.load(open(files[manager], encoding='utf-8'))
        righe_gw = (dati.get('giornate') or {}).get(gw) or []
        pool = costruisci_pool_globale(righe_gw)
        slot = sum(len(f['carte']) for f in forms)
        n_pool = len(pool)
        rapporto = n_pool / slot if slot else None
        rapporti.append(rapporto)
        info = {'manager': manager, 'gw': gw, 'pool': n_pool, 'slot': slot, 'rapporto': rapporto}
        if n_pool <= slot:
            astensione.append(info)
        else:
            allocazione.append(info)

    print(f'\nREGIME ASTENSIONE (pool<=slot): {len(astensione)} unita (atteso 37)')
    print(f'REGIME ALLOCAZIONE (pool>slot): {len(allocazione)} unita (atteso 53)')
    rapp_alloc = sorted(a['rapporto'] for a in allocazione)
    if rapp_alloc:
        mediana = rapp_alloc[len(rapp_alloc)//2]
        print(f'  rapporto pool/slot allocazione: mediana={mediana:.2f}x  max={max(rapp_alloc):.2f}x  '
              f'(atteso mediana 1,58x max 20,8x)')

    anomale = [a for a in astensione if a['pool'] < a['slot']]
    if anomale:
        print(f'\nATTENZIONE: {len(anomale)} unita con pool < slot (dovrebbe essere impossibile, '
              'ogni carta schierata in arena e\' anche nel pool globale per costruzione):')
        for a in anomale[:10]:
            print('  ', a)

    # --- copertura classifiche_arene sulle leaderboard reali del perimetro ---
    cl = json.load(open('dati_globali/classifiche_arene_2026-08-08.json', encoding='utf-8'))
    idx_cl = {a['slug']: a for a in cl['arene']}
    leaderboard_reali = sorted(set(f['leaderboard'] for f in formazioni))
    presenti = [lb for lb in leaderboard_reali if lb in idx_cl]
    print(f'\nCOPERTURA classifiche_arene_2026-08-08.json sulle leaderboard reali del perimetro:')
    print(f'  leaderboard reali distinte: {len(leaderboard_reali)}')
    print(f'  presenti in classifiche_arene: {len(presenti)} ({100*len(presenti)/len(leaderboard_reali):.1f}%)')
    per_gruppo_cop = collections.Counter()
    per_gruppo_tot = collections.Counter()
    lb_gruppo = {}
    for f in formazioni:
        lb_gruppo[f['leaderboard']] = f['gruppo']
    for lb in leaderboard_reali:
        per_gruppo_tot[lb_gruppo[lb]] += 1
        if lb in idx_cl:
            per_gruppo_cop[lb_gruppo[lb]] += 1
    for g in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        t = per_gruppo_tot[g]
        c = per_gruppo_cop[g]
        if t:
            print(f'    {g:12s} {c}/{t} ({100*c/t:.1f}%)')

    # quante FORMAZIONI (non leaderboard) sono su una leaderboard coperta
    form_coperte = sum(1 for f in formazioni if f['leaderboard'] in idx_cl)
    print(f'  formazioni (non leaderboard) su leaderboard coperta: {form_coperte}/{len(formazioni)} '
          f'({100*form_coperte/len(formazioni):.1f}%)')

    esito = {
        'formazioni': len(formazioni), 'carte': tot_carte,
        'per_gruppo': dict(tot_per_gruppo),
        'unita_totali': len(per_unita),
        'astensione': astensione, 'allocazione': allocazione,
        'classifiche_copertura': {'leaderboard_reali': len(leaderboard_reali), 'presenti': len(presenti),
                                   'per_gruppo_tot': dict(per_gruppo_tot), 'per_gruppo_cop': dict(per_gruppo_cop),
                                   'formazioni_coperte': form_coperte},
    }
    with open('analisi_manager/p20_g_odds_arene_setup_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_g_odds_arene_setup_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
