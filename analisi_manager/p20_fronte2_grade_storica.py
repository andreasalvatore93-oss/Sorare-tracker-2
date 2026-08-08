"""PASSO 2 del brief BRIEF_SONNET_GRADE_SCALA_STORICA_2026-08-08.txt --
rifa' il Fronte 2 (p14/p15, "a parita' di carte il bot decide meglio?") con
un TERZO ramo: S = G con GRADE_SCALE='storica' (media/sd del grade
dallo storico walk-forward invece che dal gruppo (lega,ruolo) della
singola giornata/pool). A e G-gruppo sono IDENTICI a p14/p15 (stessa
costruzione campione, stesso codice riusato). Il confronto che conta e'
S contro G, a parita' di tutto il resto (stesse 142 arene, stesso pool,
stesso capitano, stessa formazione -- cambia solo la fonte del grade).

Riusa: p14_fronte2_astensioni_arena (campione, calcola_pool_rows, soglie),
p18_grade_scala_storica (scala walk-forward, stesso cutoff-per-fixture di
p19). NON reinventa la formula ne' i filtri del campione.

A differenza del Passo 1 (non-arena), qui la formazione e' FISSA (quella
del manager): il placebo NON richiede rigiocare un knapsack, quindi e'
economico e si fa a piena potenza (200 permutazioni di default, non ridotte).

Uso:
  python analisi_manager/p20_fronte2_grade_storica.py [--placebo N]
"""
import os
import sys
import io
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import argparse
import p14_fronte2_astensioni_arena as F14
import p12_backtest_manager_grade as M
import p18_grade_scala_storica as P18

S21 = F14.S21
bfg = F14.bfg

RAMI = ['A-stretta', 'G-stretta', 'S-stretta', 'A-larga', 'G-larga', 'S-larga']
RAMI_G_S = ['G-stretta', 'S-stretta', 'G-larga', 'S-larga']


def scala_per(scala, lega, ruolo):
    voce = scala['per_lega_ruolo'].get(f'{lega}|{ruolo}')
    if voce:
        return voce['mean'], voce['sd']
    voce = scala['per_ruolo'].get(ruolo)
    if voce:
        return voce['mean'], voce['sd']
    if scala['globale']:
        return scala['globale']['mean'], scala['globale']['sd']
    return None


def applica_storica_dict(pool_rows_dict, scala):
    """Aggiunge '_storica' a ogni riga del pool (dict cid->row di
    F14.calcola_pool_rows): stessa sd_gruppo_atteso di _combinato, z con
    media/sd dalla scala storica invece che dal gruppo corrente."""
    rows = list(pool_rows_dict.values())
    gruppi = collections.defaultdict(list)
    for r in rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (lega, cod), membri in gruppi.items():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        voce = scala_per(scala, lega, cod)
        for m in membri:
            gn = m.get('_grade')   # gia' numerico, vedi p19
            if voce is not None and gn is not None and voce[1] > 0:
                z = (gn - voce[0]) / voce[1]
            else:
                z = 0.0
            m['_storica'] = m['_cal'] + sd_atteso * z


def permuta_e_ricalcola(pool_rows_dict, scala, rnd):
    """Come p19.permuta_e_ricalcola ma su un dict cid->row: copia le righe
    con _grade permutato dentro ogni gruppo (lega,codice), ricalcola
    _combinato_perm e _storica_perm."""
    rows = {cid: dict(r) for cid, r in pool_rows_dict.items()}
    gruppi = collections.defaultdict(list)
    for r in rows.values():
        gruppi[(r['lega'], r['codice'])].append(r)
    for (lega, cod), membri in gruppi.items():
        for m in membri:
            m['_combinato_perm'] = m['_cal']
            m['_storica_perm'] = m['_cal']
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp_idx = [i for i, m in enumerate(membri) if m.get('_grade') is not None]
        gp_originali = [membri[i]['_grade'] for i in gp_idx]

        if len(gp_idx) >= 2:
            gp_perm1 = list(gp_originali)
            rnd.shuffle(gp_perm1)
            zg, _, _ = S21.zscore_gruppo(gp_perm1)
            for i, z in zip(gp_idx, zg):
                membri[i]['_combinato_perm'] = membri[i]['_cal'] + sd_atteso * z

        voce = scala_per(scala, lega, cod)
        if gp_idx and voce is not None and voce[1] > 0:
            gp_perm2 = list(gp_originali)
            rnd.shuffle(gp_perm2)
            gmean, gsd = voce
            for i, gn in zip(gp_idx, gp_perm2):
                z = (gn - gmean) / gsd
                membri[i]['_storica_perm'] = membri[i]['_cal'] + sd_atteso * z
    return rows


def costruisci_tutto():
    idx_grade, data_min = M.carica_indice_grade_esteso()
    lega_di = F14.AG.indice_lega()
    manager_files = F14.carica_manager_files()
    osservazioni, _scarti_oss, _dm = P18.costruisci_osservazioni()

    coppie = []
    for manager, d in manager_files.items():
        for gw, righe in (d.get('giornate') or {}).items():
            arene = [f for f in righe if F14.arena_ammessa(f)]
            if not arene:
                continue
            slot = 5 * len(arene)
            pool = F14.costruisci_pool_globale(righe)
            if slot == 0 or len(pool) / slot > F14.POOL_SLOT_MAX:
                continue
            bounds = M.parse_fixture_bounds(gw)
            if bounds is None:
                continue
            d_start, d_end = bounds
            fine_str = d_end.isoformat()
            covered = sum(1 for c in pool.values()
                         if S21.grade_in_finestra(idx_grade, c.get('slug'), fine_str) is not None)
            coverage = covered / len(pool) if pool else 0.0
            if coverage < F14.COPERTURA_MINIMA:
                continue
            coppie.append((manager, gw, arene, pool, d_start, d_end))

    campione = []
    for manager, gw, arene, pool, d_start, d_end in coppie:
        for f in arene:
            carte = f.get('carte') or []
            if len(carte) != 5:
                continue
            somma = sum(c.get('punteggio') or 0 for c in carte)
            uff = (f.get('piazzamento') or {}).get('punteggio')
            if uff is None or abs(somma - uff) > 0.5:
                continue
            campione.append((manager, gw, f, pool, d_start, d_end))

    scarti_atteso = collections.Counter()
    pool_rows_by_pair = {}
    scala_by_cutoff = {}
    for manager, gw, arene, pool, d_start, d_end in coppie:
        rows = F14.calcola_pool_rows(pool, d_start, d_end, idx_grade, lega_di, scarti_atteso)
        cutoff = d_start.isoformat()
        if cutoff not in scala_by_cutoff:
            scala_by_cutoff[cutoff] = P18.costruisci_scala(osservazioni, cutoff=cutoff)
        applica_storica_dict(rows, scala_by_cutoff[cutoff])
        pool_rows_by_pair[(manager, gw)] = rows

    risultati = []
    escluse_no_atteso = []
    for manager, gw, f, pool, d_start, d_end in campione:
        rows_pair = pool_rows_by_pair[(manager, gw)]
        carte = f.get('carte')
        rows5 = [rows_pair.get(c.get('carta')) for c in carte]
        if any(r is None for r in rows5):
            escluse_no_atteso.append((manager, gw, f))
            continue
        cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
        if cap_idx is None:
            continue
        atteso_A = sum(r['_cal'] for r in rows5) + 0.2 * rows5[cap_idx]['_cal']
        atteso_G = sum(r['_combinato'] for r in rows5) + 0.2 * rows5[cap_idx]['_combinato']
        atteso_S = sum(r['_storica'] for r in rows5) + 0.2 * rows5[cap_idx]['_storica']
        tipo = f.get('competizione')
        tipo_bfg = F14.COMP_TO_TIPO_BFG[tipo]
        soglia = bfg.PAREGGIO_ARENA[tipo_bfg]
        costo = bfg.COSTO_INGRESSO[tipo_bfg]
        guad_punto = bfg.GUADAGNO_PER_PUNTO[tipo_bfg]
        soglia_decisione = soglia + costo * bfg.QUOTA_MINIMA / guad_punto
        rank = (f.get('piazzamento') or {}).get('rank')
        netto = F14.netto_reale(tipo, rank)
        podio_arena = rank is not None and rank <= 3
        decisioni = {
            'A-stretta': atteso_A >= soglia_decisione,
            'G-stretta': atteso_G >= soglia_decisione,
            'S-stretta': atteso_S >= soglia_decisione,
            'A-larga': atteso_A >= soglia,
            'G-larga': atteso_G >= soglia,
            'S-larga': atteso_S >= soglia,
        }
        risultati.append({'manager': manager, 'gw': gw, 'tipo': tipo, 'rank': rank,
                          'netto': netto, 'podio': podio_arena, 'rows5': rows5,
                          'cap_idx': cap_idx,
                          'atteso_A': atteso_A, 'atteso_G': atteso_G, 'atteso_S': atteso_S,
                          'decisioni': decisioni})

    return {'idx_grade': idx_grade, 'lega_di': lega_di, 'coppie': coppie,
           'campione': campione, 'pool_rows_by_pair': pool_rows_by_pair,
           'risultati': risultati, 'escluse_no_atteso': escluse_no_atteso,
           'scala_by_cutoff': scala_by_cutoff, 'osservazioni': osservazioni}


def saldo_bot(risultati, ramo):
    return sum(r['netto'] for r in risultati if r['decisioni'][ramo])


def saldo_manager(risultati):
    return sum(r['netto'] for r in risultati)


def stampa_matrice_saldo(risultati, etichetta):
    print(f'\n{"="*78}\n{etichetta}  (n={len(risultati)})\n{"="*78}')
    if not risultati:
        print('  (nessuna arena)')
        return
    sm = saldo_manager(risultati)
    print(f'saldo manager reale ("gioca sempre"): {sm:+.0f}  |  pavimento "non gioca mai": 0')
    for ramo in RAMI:
        gioca_podio = sum(1 for r in risultati if r['decisioni'][ramo] and r['podio'])
        gioca_no = sum(1 for r in risultati if r['decisioni'][ramo] and not r['podio'])
        salta_podio = sum(1 for r in risultati if not r['decisioni'][ramo] and r['podio'])
        salta_no = sum(1 for r in risultati if not r['decisioni'][ramo] and not r['podio'])
        sb = sum(r['netto'] for r in risultati if r['decisioni'][ramo])
        risparmio = sum(-r['netto'] for r in risultati if not r['decisioni'][ramo] and r['netto'] < 0)
        mancato = sum(r['netto'] for r in risultati if not r['decisioni'][ramo] and r['netto'] > 0)
        quadra = sm + risparmio - mancato
        giuste = gioca_podio + salta_no
        print(f'\n  ramo {ramo}:')
        print(f'    matrice [bot gioca/non gioca x podio/non podio]: '
              f'gioca(podio={gioca_podio},no={gioca_no})  non_gioca(podio={salta_podio},no={salta_no})')
        print(f'    tasso decisioni giuste: {giuste}/{len(risultati)} ({100*giuste/len(risultati):.1f}%)')
        print(f'    saldo_bot={sb:+.0f}  risparmio={risparmio:+.0f}  mancato_guadagno={mancato:+.0f}  '
              f'quadratura={quadra:+.0f}  {"OK" if abs(quadra-sb)<1e-6 else "ERRORE"}')


def boot_delta_manager(per_manager_righe, ramo, B=3000, seed=41):
    rnd = random.Random(seed)
    manager_list = sorted(per_manager_righe.keys())
    n = len(manager_list)
    if n == 0:
        return None, None
    vals = []
    for _ in range(B):
        saldo_bot_v = 0.0
        saldo_mgr_v = 0.0
        for _ in range(n):
            m = manager_list[rnd.randrange(n)]
            for r in per_manager_righe[m]:
                saldo_mgr_v += r['netto']
                if r['decisioni'][ramo]:
                    saldo_bot_v += r['netto']
        vals.append(saldo_bot_v - saldo_mgr_v)
    vals.sort()
    frac_pos = sum(1 for v in vals if v > 0) / len(vals)
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))], frac_pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--placebo', type=int, default=200)
    args = ap.parse_args()

    print('=' * 78)
    print('PASSO 2 -- FRONTE 2 con GRADE_SCALE=storica (S) vs G-gruppo (G) vs A')
    print('=' * 78)

    stato = costruisci_tutto()
    risultati = stato['risultati']
    print(f'\narene nel campione: {len(stato["campione"])}  (controllo: 170, vedi p14/p15)')
    print(f'arene valutate (atteso disponibile per tutte le regole): {len(risultati)}  (controllo: 142)')
    print(f'arene escluse per carta-senza-atteso: {len(stato["escluse_no_atteso"])}')

    managers_set = sorted(set(r['manager'] for r in risultati))
    print(f'manager nelle arene valutate: {len(managers_set)}')

    per_tipo = collections.defaultdict(list)
    for r in risultati:
        per_tipo[r['tipo']].append(r)

    stampa_matrice_saldo(risultati, 'AGGREGATO (tutte le arene valutate)')
    for tipo in ('Cap 260', 'Cap 220', 'Uncapped'):
        stampa_matrice_saldo(per_tipo.get(tipo, []), f'STRATIFICATO PER TIPO -- {tipo}')

    print(f'\n{"="*78}\nBOOTSTRAP sui MANAGER (cluster), 3.000 resample -- delta saldo_bot - saldo_manager\n{"="*78}')
    per_manager_righe = collections.defaultdict(list)
    for r in risultati:
        per_manager_righe[r['manager']].append(r)
    ic_per_ramo = {}
    for ramo in RAMI:
        lo, hi, frac_pos = boot_delta_manager(per_manager_righe, ramo)
        ic_per_ramo[ramo] = (lo, hi, frac_pos)
        print(f'  {ramo}: IC95 [{lo:+.0f}, {hi:+.0f}]  positivo nel {100*frac_pos:.1f}% dei resample')

    print(f'\n{"="*78}\nCONFRONTO DIRETTO S vs G (quello che interessa, brief Passo 2)\n{"="*78}')
    for suff in ('stretta', 'larga'):
        cambi = sum(1 for r in risultati if r['decisioni'][f'G-{suff}'] != r['decisioni'][f'S-{suff}'])
        sb_g = saldo_bot(risultati, f'G-{suff}')
        sb_s = saldo_bot(risultati, f'S-{suff}')
        print(f'  regola {suff}: arene dove S decide diverso da G: {cambi}/{len(risultati)}  '
              f'saldo G={sb_g:+.0f}  saldo S={sb_s:+.0f}  delta S-G={sb_s-sb_g:+.0f}')

    # --- placebo (economico: nessun knapsack, formazione fissa) ---
    if args.placebo > 0:
        print(f'\n{"="*78}\nPLACEBO ({args.placebo} permutazioni, formazione fissa -> economico)\n{"="*78}')
        sm = saldo_manager(risultati)
        reali = {ramo: saldo_bot(risultati, ramo) - sm for ramo in RAMI_G_S}
        deltas_placebo = {ramo: [] for ramo in RAMI_G_S}

        cutoff_per_pair = {(m, gw): ds.isoformat() for m, gw, _a, _p, ds, _de in stato['coppie']}

        for seed in range(args.placebo):
            rnd = random.Random(70000 + seed)
            pool_rows_perm_by_pair = {
                key: permuta_e_ricalcola(rows, stato['scala_by_cutoff'][cutoff_per_pair[key]], rnd)
                for key, rows in stato['pool_rows_by_pair'].items()}
            sb = {ramo: 0.0 for ramo in RAMI_G_S}
            for r in risultati:
                key = (r['manager'], r['gw'])
                rows_perm = pool_rows_perm_by_pair[key]
                rows5_perm = [rows_perm[row['carta']] for row in r['rows5']]
                cap_idx = r['cap_idx']
                atteso_G_perm = sum(x['_combinato_perm'] for x in rows5_perm) + 0.2 * rows5_perm[cap_idx]['_combinato_perm']
                atteso_S_perm = sum(x['_storica_perm'] for x in rows5_perm) + 0.2 * rows5_perm[cap_idx]['_storica_perm']
                tipo_bfg = F14.COMP_TO_TIPO_BFG[r['tipo']]
                soglia = bfg.PAREGGIO_ARENA[tipo_bfg]
                costo = bfg.COSTO_INGRESSO[tipo_bfg]
                guad_punto = bfg.GUADAGNO_PER_PUNTO[tipo_bfg]
                soglia_decisione = soglia + costo * bfg.QUOTA_MINIMA / guad_punto
                if atteso_G_perm >= soglia_decisione:
                    sb['G-stretta'] += r['netto']
                if atteso_S_perm >= soglia_decisione:
                    sb['S-stretta'] += r['netto']
                if atteso_G_perm >= soglia:
                    sb['G-larga'] += r['netto']
                if atteso_S_perm >= soglia:
                    sb['S-larga'] += r['netto']
            for ramo in RAMI_G_S:
                deltas_placebo[ramo].append(sb[ramo] - sm)

        def percentile(vals, x):
            n = len(vals)
            sotto = sum(1 for v in vals if v < x)
            uguale = sum(1 for v in vals if v == x)
            return 100 * (sotto + 0.5 * uguale) / n

        for ramo in RAMI_G_S:
            vals = sorted(deltas_placebo[ramo])
            pct = percentile(vals, reali[ramo])
            print(f'  {ramo}: placebo delta [{min(vals):+.0f},{max(vals):+.0f}] mediana '
                  f'{vals[len(vals)//2]:+.0f}  |  VERO ({reali[ramo]:+.0f}) al percentile {pct:.1f}')


if __name__ == '__main__':
    sys.exit(main() or 0)
