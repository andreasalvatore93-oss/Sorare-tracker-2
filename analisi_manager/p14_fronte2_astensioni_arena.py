"""Fronte 2 -- "a parita' di carte, il bot decide meglio?" (brief
BRIEF_SONNET_FRONTE2_ASTENSIONI_2026-08-08.txt, disegno completo in
docs/handoff/HANDOFF_G_ARENE_2026-08-08.txt sez.11).

Prende le coppie (manager, GW) in cui il manager ha schierato SOLO arene
(pool/slot <= 1.05): niente carte di scorta, quindi niente selezione da
misurare. Le 5 carte e il capitano restano quelli del manager, inchiodati
all'arena in cui li ha messi -- l'unica domanda e' SE il bot sarebbe entrato.
Quando entra, la formazione e' identica al manager: stesso punteggio, stesso
rank. Tutta la differenza nasce dalle arene che il bot rifiuta.

NESSUNA MODIFICA ALLA PRODUZIONE. Solo lettura di generatore_formazioni/
build_formazione_globale.py (soglie) e P.score_atteso (previsione walk-forward).

Uso:
  python analisi_manager/p14_fronte2_astensioni_arena.py
"""
import os
import sys
import io
import json
import glob
import random
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21   # bfg, calibra, zscore_gruppo, grade_in_finestra
import p12_backtest_manager_grade as M        # carica_indice_grade_esteso, ROLE_CODE, parse_fixture_bounds
import analizza_gw as AG                      # indice_lega()

bfg = S21.bfg
cache = CACHE.CacheLocale()

COMPETIZIONI_ARENA_AMMESSE = {'Cap 260', 'Cap 220', 'Uncapped'}
ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_uncapped'}
COMP_TO_TIPO_BFG = {'Cap 260': 'ARENA_ALLSTARS_260', 'Cap 220': 'ARENA_ALLSTARS_220',
                    'Uncapped': 'ARENA_ALLSTARS_UNCAPPED'}
COPERTURA_MINIMA = 0.70
POOL_SLOT_MAX = 1.05

# premi BASE e costi (misurati su p11_pool.json, 673 arene -- brief sez.5)
PREMI = {
    'Cap 260':  {'costo': 300, 1: 1300, 2: 800, 3: 500},
    'Cap 220':  {'costo': 200, 1: 1000, 2: 500, 3: 300},
    'Uncapped': {'costo': 300, 1: 1300, 2: 800, 3: 500},
}


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


def arena_ammessa(f):
    return (f.get('tipo_arena') in ARENE_AMMESSE_TIPO
            and f.get('competizione') in COMPETIZIONI_ARENA_AMMESSE)


def costruisci_pool_globale(righe):
    """Una voce per carta distinta, da TUTTE le competizioni della giornata."""
    pool = {}
    for f in righe:
        for c in (f.get('carte') or []):
            cid = c.get('carta')
            if cid and cid not in pool:
                pool[cid] = c
    return pool


def calcola_pool_rows(pool, d_start, d_end, idx_grade, lega_di, scarti):
    """Score atteso walk-forward + z-grade per gruppo (lega, ruolo), sul pool
    INTERO della coppia (manager, GW) -- non solo sulle carte in arena."""
    fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
    fine_str = d_end.isoformat()
    rows = {}
    for cid, c in pool.items():
        ruolo_full = c.get('ruolo')
        cod = M.ROLE_CODE.get(ruolo_full)
        if cod is None:
            scarti['ruolo_sconosciuto'] += 1
            continue
        slug = c.get('slug')
        r = P.score_atteso(cache, slug, ruolo_full, fine)
        if r is None or r.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        lega = lega_di.get(slug) or 'senza_lega'
        grade = S21.grade_in_finestra(idx_grade, slug, fine_str)
        rows[cid] = {'slug': slug, 'carta': cid, 'nome': c.get('nome'), 'codice': cod,
                     'lega': lega, 'ruolo': ruolo_full, 'atteso_raw': r['atteso'],
                     '_grade': grade}
    for r in rows.values():
        r['_cal'] = bfg.calibra(r['atteso_raw'], r['codice'])
    gruppi = collections.defaultdict(list)
    for r in rows.values():
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp = [m['_grade'] for m in membri if m['_grade'] is not None]
        if len(gp) >= 2:
            zg, _, _ = S21.zscore_gruppo(gp)
            it = iter(zg)
            for m in membri:
                m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
        else:
            for m in membri:
                m['_zgrade'] = 0.0
        for m in membri:
            m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']
    return rows


def main():
    print('=' * 78)
    print('FRONTE 2 -- "a parita\' di carte, il bot decide meglio?"')
    print('=' * 78)

    idx_grade, data_min = M.carica_indice_grade_esteso()
    n_coppie = sum(len(v) for v in idx_grade.values())
    print(f'\nindice grade: {len(idx_grade)} slug, {n_coppie} coppie (slug,data), '
          f'da {data_min} (controllo brief: ~1.639 slug, ~24.529 coppie, da 2025-07-13 a 2026-08-07)')

    lega_di = AG.indice_lega()
    manager_files = carica_manager_files()
    print(f'file manager validi: {len(manager_files)} (controllo brief: 54)')

    # --- fase 1: selezione coppie (manager, GW) --------------------------
    coppie = []   # (manager, gw, arene_ammesse, pool, d_start, d_end, coverage)
    scarti_coppie = collections.Counter()
    for manager, d in manager_files.items():
        for gw, righe in (d.get('giornate') or {}).items():
            arene = [f for f in righe if arena_ammessa(f)]
            if not arene:
                continue
            slot = 5 * len(arene)
            pool = costruisci_pool_globale(righe)
            if slot == 0 or len(pool) / slot > POOL_SLOT_MAX:
                scarti_coppie['pool_slot_oltre_1.05'] += 1
                continue
            bounds = M.parse_fixture_bounds(gw)
            if bounds is None:
                scarti_coppie['data_non_parsabile'] += 1
                continue
            d_start, d_end = bounds
            fine_str = d_end.isoformat()
            covered = sum(1 for c in pool.values()
                         if S21.grade_in_finestra(idx_grade, c.get('slug'), fine_str) is not None)
            coverage = covered / len(pool) if pool else 0.0
            if coverage < COPERTURA_MINIMA:
                scarti_coppie['copertura_grade_sotto_70pct'] += 1
                continue
            coppie.append((manager, gw, arene, pool, d_start, d_end, coverage))

    print(f'\ncoppie (manager,GW) con >=1 arena ammessa e pool/slot<=1.05 e copertura>=70%: {len(coppie)}')
    print(f'scarti fase coppie: {dict(scarti_coppie)}')

    # --- fase 2: filtro a livello di ARENA (5 carte, somma = ufficiale) ---
    campione = []   # (manager, gw, f_arena, pool, d_start, d_end)
    scarti_arena = collections.Counter()
    for manager, gw, arene, pool, d_start, d_end, coverage in coppie:
        for f in arene:
            carte = f.get('carte') or []
            if len(carte) != 5:
                scarti_arena['non_5_carte'] += 1
                continue
            somma = sum(c.get('punteggio') or 0 for c in carte)
            uff = (f.get('piazzamento') or {}).get('punteggio')
            if uff is None or abs(somma - uff) > 0.5:
                scarti_arena['somma_diversa_da_ufficiale'] += 1
                continue
            campione.append((manager, gw, f, pool, d_start, d_end))

    print(f'\narene nel campione (dopo filtro 5-carte + somma=ufficiale): {len(campione)}  '
          f'(controllo brief: 171)')
    print(f'scarti fase arena: {dict(scarti_arena)}')

    managers_set = sorted(set(m for m, *_ in campione))
    gw_set = sorted(set(g for _m, g, *_ in campione))
    print(f'manager: {len(managers_set)}  (controllo brief: 14)')
    print(f'GW: {len(gw_set)}  (controllo brief: 13)')
    rip = collections.Counter(f.get('competizione') for _m, _g, f, *_ in campione)
    print(f'ripartizione: {dict(rip)}  (controllo brief: Cap 260=101, Cap 220=44, Uncapped=26)')
    per_manager = collections.Counter(m for m, *_ in campione)
    print('arene per manager:', dict(per_manager.most_common()))
    podio = sum(1 for *_x, f, _p, _ds, _de in campione if (f.get('piazzamento') or {}).get('rank', 99) <= 3)
    print(f'a podio: {podio}/{len(campione)} ({100*podio/len(campione):.1f}%)  (controllo brief: 54/171, 31.6%)')

    # controllo 6.3 -- pool/slot sul campione finale
    ps_ratios = []
    for manager, gw, arene, pool, d_start, d_end, coverage in coppie:
        slot = 5 * len(arene)
        ps_ratios.append(len(pool) / slot)
    ps_ratios.sort()
    med = ps_ratios[len(ps_ratios) // 2]
    print(f'\n--- CONTROLLO 6.3: pool/slot sulle coppie ammesse: mediana={med:.3f}  massimo={max(ps_ratios):.3f}')

    # --- fase 3: score atteso + z-grade per ogni coppia (una volta sola) --
    scarti_atteso = collections.Counter()
    pool_rows_by_pair = {}
    for manager, gw, arene, pool, d_start, d_end, coverage in coppie:
        pool_rows_by_pair[(manager, gw)] = calcola_pool_rows(pool, d_start, d_end, idx_grade, lega_di, scarti_atteso)
    print(f'\nscarti nel calcolo atteso/grade sul pool (per tutte le coppie): {dict(scarti_atteso)}')

    # --- fase 4: decisione per arena, 4 rami (A/G x stretta/larga) --------
    risultati = []
    n_carte_con_grade = 0
    n_arene_5_grade = 0
    scarti_decisione = collections.Counter()
    for manager, gw, f, pool, d_start, d_end in campione:
        rows_pair = pool_rows_by_pair[(manager, gw)]
        carte = f.get('carte')
        rows5 = [rows_pair.get(c.get('carta')) for c in carte]
        if any(r is None for r in rows5):
            scarti_decisione['carta_senza_atteso'] += 1
            continue
        n_con_grade = sum(1 for r in rows5 if r.get('_grade') is not None)
        n_carte_con_grade += n_con_grade
        if n_con_grade == 5:
            n_arene_5_grade += 1
        cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
        if cap_idx is None:
            scarti_decisione['senza_capitano'] += 1
            continue
        atteso_A = sum(r['_cal'] for r in rows5) + 0.2 * rows5[cap_idx]['_cal']
        atteso_G = sum(r['_combinato'] for r in rows5) + 0.2 * rows5[cap_idx]['_combinato']

        tipo = f.get('competizione')
        tipo_bfg = COMP_TO_TIPO_BFG[tipo]
        soglia = bfg.PAREGGIO_ARENA[tipo_bfg]
        costo = bfg.COSTO_INGRESSO[tipo_bfg]
        guad_punto = bfg.GUADAGNO_PER_PUNTO[tipo_bfg]
        soglia_decisione = soglia + costo * bfg.QUOTA_MINIMA / guad_punto

        rank = (f.get('piazzamento') or {}).get('rank')
        netto = netto_reale(tipo, rank)
        podio_arena = rank is not None and rank <= 3

        decisioni = {
            'A-stretta': atteso_A >= soglia_decisione,
            'G-stretta': atteso_G >= soglia_decisione,
            'A-larga': atteso_A >= soglia,
            'G-larga': atteso_G >= soglia,
        }
        risultati.append({'manager': manager, 'gw': gw, 'tipo': tipo, 'rank': rank,
                          'netto': netto, 'podio': podio_arena,
                          'atteso_A': atteso_A, 'atteso_G': atteso_G,
                          'soglia': soglia, 'soglia_decisione': soglia_decisione,
                          'decisioni': decisioni})

    print(f'\nscarti nella decisione (arene del campione escluse dai numeri finali): {dict(scarti_decisione)}')
    print(f'arene valutate nei 4 rami: {len(risultati)}')
    n_valutate5 = len(risultati) * 5
    print(f'carte con grade (sulle arene valutate): {n_carte_con_grade}/{n_valutate5} '
          f'({100*n_carte_con_grade/n_valutate5:.1f}%)  (controllo brief: 815/855, 95.3%)')
    print(f'arene con tutte e 5 le carte col grade: {n_arene_5_grade}/{len(risultati)}  '
          f'(controllo brief: 146/171)')

    # controllo saldo netto REALE manager (sulle arene valutate)
    saldo_manager_tot = sum(r['netto'] for r in risultati)
    saldo_per_tipo = collections.Counter()
    for r in risultati:
        saldo_per_tipo[r['tipo']] += r['netto']
    print(f'\nsaldo netto REALE manager (arene valutate): {saldo_manager_tot:+.0f} essenze '
          f'(controllo brief: +500)')
    print(f'  ripartizione: {dict(saldo_per_tipo)}  (controllo brief: Cap 260 -4.400, Cap 220 +2.600, Uncapped +2.300)')

    # --- controllo 6.1: interruttore funziona? ----------------------------
    print('\n--- CONTROLLO 6.1: interruttore G vs A ---')
    for suff in ('stretta', 'larga'):
        cambi = sum(1 for r in risultati if r['decisioni'][f'A-{suff}'] != r['decisioni'][f'G-{suff}'])
        print(f'  regola {suff}: arene dove G decide diverso da A: {cambi}/{len(risultati)}')
    n_z0 = 0
    n_z0_causa = collections.Counter()
    for manager, gw in pool_rows_by_pair:
        for r in pool_rows_by_pair[(manager, gw)].values():
            if r['_zgrade'] == 0.0:
                n_z0 += 1
                if r['_grade'] is None:
                    n_z0_causa['nessun_grade'] += 1
                else:
                    n_z0_causa['gruppo_lega_ruolo_<2_col_grade'] += 1
    tot_righe_pool = sum(len(v) for v in pool_rows_by_pair.values())
    print(f'  carte del pool con z_grade=0: {n_z0}/{tot_righe_pool}  cause: {dict(n_z0_causa)}')

    # --- controllo 6.2: test A/A ------------------------------------------
    print('\n--- CONTROLLO 6.2: test A/A (due run del ramo A devono essere identici) ---')
    pool_rows_by_pair_2 = {}
    for manager, gw, arene, pool, d_start, d_end, coverage in coppie:
        pool_rows_by_pair_2[(manager, gw)] = calcola_pool_rows(pool, d_start, d_end, idx_grade, lega_di, collections.Counter())
    diffs = 0
    for (manager, gw), rows1 in pool_rows_by_pair.items():
        rows2 = pool_rows_by_pair_2[(manager, gw)]
        for cid, r1 in rows1.items():
            r2 = rows2.get(cid)
            if r2 is None or r1['_cal'] != r2['_cal']:
                diffs += 1
    print(f'  differenze fra run1 e run2 (ramo A, atteso_cal): {diffs}  (deve essere 0)')

    # --- fase 5: matrici, saldo, tasso decisioni giuste, stratificazioni --
    RAMI = ['A-stretta', 'G-stretta', 'A-larga', 'G-larga']

    def stampa_blocco(sottoinsieme, etichetta):
        print(f'\n{"="*78}\n{etichetta}  (n={len(sottoinsieme)})\n{"="*78}')
        if not sottoinsieme:
            print('  (nessuna arena)')
            return
        saldo_manager = sum(r['netto'] for r in sottoinsieme)
        print(f'saldo manager reale ("gioca sempre"): {saldo_manager:+.0f}  |  '
              f'pavimento "non gioca mai": 0')
        for ramo in RAMI:
            gioca_podio = sum(1 for r in sottoinsieme if r['decisioni'][ramo] and r['podio'])
            gioca_no = sum(1 for r in sottoinsieme if r['decisioni'][ramo] and not r['podio'])
            salta_podio = sum(1 for r in sottoinsieme if not r['decisioni'][ramo] and r['podio'])
            salta_no = sum(1 for r in sottoinsieme if not r['decisioni'][ramo] and not r['podio'])
            saldo_bot = sum(r['netto'] for r in sottoinsieme if r['decisioni'][ramo])
            risparmio = sum(-r['netto'] for r in sottoinsieme if not r['decisioni'][ramo] and r['netto'] < 0)
            mancato = sum(r['netto'] for r in sottoinsieme if not r['decisioni'][ramo] and r['netto'] > 0)
            quadra = saldo_manager + risparmio - mancato
            giuste = gioca_podio + salta_no
            print(f'\n  ramo {ramo}:')
            print(f'    matrice 2x2 [bot gioca/non gioca x podio/non podio]:')
            print(f'                    podio    non podio')
            print(f'      bot gioca     {gioca_podio:5d}    {gioca_no:5d}')
            print(f'      bot non gioca {salta_podio:5d}    {salta_no:5d}')
            print(f'    tasso decisioni giuste (diagonale/n): {giuste}/{len(sottoinsieme)} '
                  f'({100*giuste/len(sottoinsieme):.1f}%)   vs "gioca sempre"='
                  f'{100*sum(1 for r in sottoinsieme if r["podio"])/len(sottoinsieme):.1f}%   '
                  f'vs "non gioca mai"={100*sum(1 for r in sottoinsieme if not r["podio"])/len(sottoinsieme):.1f}%')
            print(f'    saldo_bot={saldo_bot:+.0f}  risparmio={risparmio:+.0f}  mancato_guadagno={mancato:+.0f}  '
                  f'quadratura(manager+risp-mancato)={quadra:+.0f}  {"OK" if abs(quadra-saldo_bot)<1e-6 else "ERRORE QUADRATURA"}')

    stampa_blocco(risultati, 'F1-F2-F4: TUTTE LE ARENE VALUTATE (aggregato)')
    for tipo in ('Cap 260', 'Cap 220', 'Uncapped'):
        stampa_blocco([r for r in risultati if r['tipo'] == tipo], f'F5: STRATIFICATO PER TIPO -- {tipo}')
    for manager in managers_set:
        sotto = [r for r in risultati if r['manager'] == manager]
        if sotto:
            stampa_blocco(sotto, f'F5: STRATIFICATO PER MANAGER -- {manager}')

    # --- F6: bootstrap sui manager -----------------------------------------
    print(f'\n{"="*78}\nF6: BOOTSTRAP sui 14 MANAGER (cluster), 2.000 resample\n{"="*78}')
    per_manager_righe = collections.defaultdict(list)
    for r in risultati:
        per_manager_righe[r['manager']].append(r)
    manager_list = sorted(per_manager_righe.keys())
    rnd = random.Random(20260808)
    for ramo in RAMI:
        deltas = []
        for _ in range(2000):
            camp = [manager_list[rnd.randrange(len(manager_list))] for _ in range(len(manager_list))]
            saldo_bot = 0.0
            saldo_mgr = 0.0
            for m in camp:
                for r in per_manager_righe[m]:
                    saldo_mgr += r['netto']
                    if r['decisioni'][ramo]:
                        saldo_bot += r['netto']
            deltas.append(saldo_bot - saldo_mgr)
        deltas.sort()
        lo = deltas[int(0.025 * len(deltas))]
        hi = deltas[int(0.975 * len(deltas))]
        frac_pos = sum(1 for x in deltas if x > 0) / len(deltas)
        print(f'  ramo {ramo}: delta (saldo_bot - saldo_manager) IC95 [{lo:+.0f}, {hi:+.0f}]  '
              f'frazione resample col segno positivo: {100*frac_pos:.1f}%')

    # --- 7.6: riepilogo scarti ----------------------------------------------
    print(f'\n{"="*78}\n7.6: RIEPILOGO SCARTI\n{"="*78}')
    print(f'coppie escluse: {dict(scarti_coppie)}')
    print(f'arene escluse a livello arena (5-carte/somma): {dict(scarti_arena)}')
    print(f'scarti nel calcolo atteso/grade (sul pool, non tutte finiscono nel campione): {dict(scarti_atteso)}')
    print(f'arene del campione escluse dalla decisione: {dict(scarti_decisione)}')

    # --- dump leggibile (6.4) -----------------------------------------------
    dump_manager = None
    for m in per_manager.most_common():
        nm = m[0]
        tipi = set(r['tipo'] for r in per_manager_righe.get(nm, []))
        if m[1] >= 3 and len(tipi) >= 2:
            dump_manager = nm
            break
    if dump_manager is None and per_manager:
        dump_manager = per_manager.most_common(1)[0][0]
    dump_path = os.path.join(ROOT, 'analisi_manager', 'p14_dump_esempio.txt')
    with open(dump_path, 'w', encoding='utf-8') as fh:
        fh.write(f'DUMP FRONTE 2 -- manager {dump_manager}\n\n')
        righe_m = [r for r in risultati if r['manager'] == dump_manager]
        gw_di_m = sorted(set(r['gw'] for r in righe_m))
        gw_dump = gw_di_m[0]
        fh.write(f'GW: {gw_dump}\n\n')
        for manager, gw, f, pool, d_start, d_end in campione:
            if manager != dump_manager or gw != gw_dump:
                continue
            rows_pair = pool_rows_by_pair[(manager, gw)]
            carte = f.get('carte')
            match = next((r for r in righe_m if r['gw'] == gw and r['tipo'] == f.get('competizione')
                         and r['rank'] == (f.get('piazzamento') or {}).get('rank')), None)
            fh.write(f"--- ARENA {f.get('competizione')}  rank={ (f.get('piazzamento') or {}).get('rank')}  "
                     f"punteggio_ufficiale={(f.get('piazzamento') or {}).get('punteggio')} ---\n")
            for c in carte:
                r5 = rows_pair.get(c.get('carta'))
                cap = '  [CAPITANO]' if c.get('capitano') else ''
                if r5:
                    fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):26} "
                             f"grade={r5.get('_grade') or '-':>2} atteso_A={r5['_cal']:7.2f} "
                             f"atteso_G={r5['_combinato']:7.2f} punteggio_uff={c.get('punteggio'):7.2f}{cap}\n")
                else:
                    fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):26} SENZA ATTESO{cap}\n")
            if match:
                fh.write(f"    atteso_totale A={match['atteso_A']:.2f}  G={match['atteso_G']:.2f}  "
                         f"soglia={match['soglia']:.2f}  soglia_decisione={match['soglia_decisione']:.2f}\n")
                for ramo in RAMI:
                    fh.write(f"    {ramo}: {'ENTRA' if match['decisioni'][ramo] else 'SALTA'}\n")
                fh.write(f"    netto reale manager: {match['netto']:+.0f}  podio={match['podio']}\n")
            else:
                fh.write('    (arena esclusa dalla decisione: carta senza atteso o senza capitano)\n')
            fh.write('\n')
    print(f'\ndump scritto in {dump_path}')


if __name__ == '__main__':
    sys.exit(main() or 0)
