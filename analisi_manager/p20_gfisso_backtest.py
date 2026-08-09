"""BRIEF_SONNET_GFISSO_2026-08-09.txt -- G FISSO (tabella residui per lettera)
contro G VARIABILE (z-score di gruppo, meccanismo attuale). SOLO MISURA,
nessuna modifica alla produzione, nessuna modifica a p20_g_odds_arene_
backtest.py (import e riuso).

Non riscrive nulla: importa P20G e aggiunge rami _gf_v1/_gf_v2/_gf_v3 alle
pool_rows delle stesse unita' (825 formazioni, 90 unita' manager/gw, gia'
costruite da P20G.costruisci_unita).
"""
import os
os.environ.setdefault('ARENA_LEAGUES_ENABLED', 'tutte')

import sys
import io
import json
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p20_g_odds_arene_backtest as P20G
import p13_backtest_gw_crowss as P13
import p12_backtest_formazione_grade as S21
import analizza_gw as AG

# --- S1: tabella residui, campione allargato 25.326 righe, §12 handoff ----
TABELLA_S1 = {'A': 3.87, 'B': 2.66, 'C': 1.70, 'D': 1.26, 'E': -12.46, 'F': -33.15}
NUM_LETTERA = {v: k for k, v in S21.GRADE_NUM.items()}  # 6->A ... 1->F
LETTERE_EF = {'E', 'F'}


def valore_tabella(grade_num, scala):
    if grade_num is None:
        return None
    lettera = NUM_LETTERA.get(grade_num)
    if lettera is None:
        return None
    return scala.get(lettera)


def ricalcola_combinato_gruppo(membri, campo_out='_combinato_ricalc'):
    """Ricalcola lo z-score di gruppo (stesso schema di P13.costruisci_pool_rows,
    righe 215-231) su un sottoinsieme (usato per V3, pool ridotto)."""
    if not membri:
        return
    _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
    gp = [m['_grade'] for m in membri if m['_grade'] is not None]
    if len(gp) >= 2:
        _zg, _sdg, _mg = S21.zscore_gruppo(gp)
        it = iter(_zg)
        for m in membri:
            m['_zgrade_v3'] = next(it) if m['_grade'] is not None else 0.0
    else:
        for m in membri:
            m['_zgrade_v3'] = 0.0
    for m in membri:
        m[campo_out] = m['_cal'] + sd_atteso * m['_zgrade_v3']


def annota_gf(unita):
    """Scrive per ogni riga di pool_rows: _gf_v1, _gf_v2 (pool intero) e,
    su un pool FILTRATO senza E/F, _combinato_v3 (G ricalcolato) e _gf_v3
    (GF, entrambi sullo stesso pool ridotto -- variante V3)."""
    n_ef_scartate = 0
    n_tot = 0
    for u in unita:
        rows = u['pool_rows']
        n_tot += len(rows)
        # V1/V2 sul pool intero, per-carta (non serve gruppo: tabella fissa)
        for r in rows:
            gnum = r.get('_grade')
            lettera = NUM_LETTERA.get(gnum) if gnum is not None else None
            val = TABELLA_S1.get(lettera) if lettera else None
            if val is None:
                r['_gf_v1'] = r['_cal']
                r['_gf_v2'] = r['_cal']
            else:
                r['_gf_v2'] = r['_cal'] + val
                if lettera in LETTERE_EF:
                    r['_gf_v1'] = r['_combinato']  # su E/F resta lo z-score attuale (G)
                else:
                    r['_gf_v1'] = r['_cal'] + val

        # V3: filtra E/F dal pool, ricalcola i gruppi su cio' che resta
        pool_v3 = [r for r in rows if NUM_LETTERA.get(r.get('_grade')) not in LETTERE_EF]
        n_ef_scartate += len(rows) - len(pool_v3)
        gruppi = collections.defaultdict(list)
        for r in pool_v3:
            gruppi[(r['lega'], r['codice'])].append(r)
        for membri in gruppi.values():
            ricalcola_combinato_gruppo(membri, '_combinato_v3')
        for r in rows:
            if r not in pool_v3:
                r['_combinato_v3'] = None
                r['_gf_v3'] = None
            else:
                lettera = NUM_LETTERA.get(r.get('_grade'))
                val = TABELLA_S1.get(lettera) if lettera else None
                r['_gf_v3'] = r['_cal'] if val is None else r['_cal'] + val
        u['pool_rows_v3'] = pool_v3
    return n_ef_scartate, n_tot


def sostituisci_pool(unita_list, campo):
    """Ritorna una lista di unita' 'viste' con pool_rows scambiate col campo
    v3 (solo carte non E/F), per passare a esegui_astensione/esegui_allocazione
    senza toccare l'originale."""
    nuove = []
    for u in unita_list:
        u2 = dict(u)
        u2['pool_rows'] = u['pool_rows_v3']
        nuove.append(u2)
    return nuove


def somma_netto_allocazione(righe):
    return sum(r['netto'] for r in righe)


def somma_netto_astensione(righe, label):
    return sum(r[f'netto_{label}'] for r in righe)


def bootstrap_delta_allocazione(righe_a, righe_b, chiave_manager='manager', B=3000, seed=51):
    """Bootstrap per manager sul delta (B - A) netto, stesso schema di
    P20G.bootstrap_manager ma sul delta fra due rami appaiati per manager."""
    per_m_a = collections.defaultdict(list)
    per_m_b = collections.defaultdict(list)
    for r in righe_a:
        per_m_a[r[chiave_manager]].append(r['netto'])
    for r in righe_b:
        per_m_b[r[chiave_manager]].append(r['netto'])
    managers = sorted(set(per_m_a) | set(per_m_b))
    rnd = random.Random(seed)
    n = len(managers)
    if n == 0:
        return None, None, None
    deltas = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = managers[rnd.randrange(n)]
            tot += sum(per_m_b.get(m, [])) - sum(per_m_a.get(m, []))
        deltas.append(tot)
    deltas.sort()
    media = sum(deltas) / len(deltas)
    return media, deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas))]


def main():
    lega_di = AG.indice_lega()
    idx_num = P20G.GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    unita, conta_cache = P20G.costruisci_unita(None, idx_per_slug, lega_di)
    print(f'unita totali: {len(unita)}')
    astensione = [u for u in unita if u['regime'] == 'astensione']
    allocazione = [u for u in unita if u['regime'] == 'allocazione']
    print(f'  astensione: {len(astensione)}  allocazione: {len(allocazione)}')

    for u in unita:
        P20G.applica_odds(u['pool_rows'], k=0.0)  # popola _odds_cal=_cal, serve solo a non rompere nulla

    n_ef_scartate, n_tot_carte = annota_gf(unita)
    print(f'\nCONTROLLO C4 copertura grade: {n_tot_carte - n_ef_scartate}... vedi dettaglio sotto')

    # ---- C4: copertura grade sul pool totale ----
    n_con_grade = sum(1 for u in unita for r in u['pool_rows'] if r.get('_grade') is not None)
    n_tot = sum(len(u['pool_rows']) for u in unita)
    print(f'C4 copertura grade (pool totale): {n_con_grade}/{n_tot} ({100*n_con_grade/n_tot:.1f}%)')
    print(f'C4 di cui E/F: {n_ef_scartate}/{n_tot} ({100*n_ef_scartate/n_tot:.1f}%) -- scartate in V3')

    # ---- C0: gia' verificato leggendo il codice (vedi handoff): r['_cal'] in
    # P20G.costruisci_unita e' S21.bfg.calibra(atteso_raw, codice), STESSO
    # oggetto usato in p20_grade_residui_allargato.aggancia_atteso per calcolare
    # i residui S1. Stessa scala, stessa unita' (essenze per carta). PASS.
    print('\nC0 (scala atteso): PASS -- stesso _cal = S21.bfg.calibra(...) in entrambi gli script (verificato leggendo il codice)')

    # ---- C2: interruttore A/A su GF ----
    # valore 0 per tutte le lettere -> deve riprodurre G? No: deve riprodurre
    # A (_cal) quando la tabella e' azzerata, perche' GF sostituisce lo
    # z-score, non lo somma. Verifichiamo GF(tabella=0) == _cal.
    prova = unita[0]['pool_rows'][:20] if unita else []
    tab0 = {k: 0.0 for k in TABELLA_S1}
    ok_zero = True
    for r in prova:
        lettera = NUM_LETTERA.get(r.get('_grade'))
        val = tab0.get(lettera) if lettera else None
        gf0 = r['_cal'] if val is None else r['_cal'] + val
        if abs(gf0 - r['_cal']) > 1e-9:
            ok_zero = False
    tab_grande = {k: 1000.0 for k in TABELLA_S1}
    diffs = []
    for r in prova:
        lettera = NUM_LETTERA.get(r.get('_grade'))
        if lettera:
            diffs.append(abs((r['_cal'] + tab_grande[lettera]) - r['_cal']))
    ok_grande = any(d > 500 for d in diffs) if diffs else False
    print(f'C2 interruttore GF: tabella=0 -> identico a _cal: {ok_zero}; tabella=+1000 -> si muove: {ok_grande} (n carte con grade nel campione di prova: {len(diffs)})')

    idx_classifiche = P20G.carica_classifiche()
    opportunita = P20G.opportunita_gw_tipo(idx_classifiche, unita)

    # V3: unita con pool ridotto (E/F escluse)
    astensione_v3 = sostituisci_pool(astensione, 'v3')
    allocazione_v3 = sostituisci_pool(allocazione, 'v3')

    # ---- C1: pool contro slot, per V3 (il piu' a rischio di restringere) ----
    sotto_soglia = 0
    for u in allocazione_v3:
        if len(u['pool_rows']) <= u['slot']:
            sotto_soglia += 1
    print(f'C1 (V3, regime allocazione): unita con pool<=slot dopo il filtro E/F: {sotto_soglia}/{len(allocazione_v3)}')

    risultati = {}
    for nome_set, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
        print(f'\n===================== SET SOGLIE {nome_set.upper()} =====================')
        blocco = {}

        # --- ASTENSIONE: G e' gia' nel dizionario esistito (uso G/A del file P20G) ---
        righe_ast = P20G.esegui_astensione(astensione, idx_classifiche, set_soglie)
        netto_A = sum(r['netto_A'] for r in righe_ast)
        netto_G = sum(r['netto_G'] for r in righe_ast)
        print(f'[astensione] n={len(righe_ast)}  A={netto_A:.1f}  G={netto_G:.1f}  (essenze, LIMITE SUPERIORE non realizzabile in produzione)')
        blocco['astensione'] = {'n': len(righe_ast), 'A': netto_A, 'G': netto_G}

        for variante, label_gf, unita_astensione_uso in (
            ('V1', '_gf_v1', astensione), ('V2', '_gf_v2', astensione), ('V3', '_gf_v3', astensione_v3),
        ):
            if variante == 'V3':
                righe_g_v3 = P20G.esegui_astensione(
                    [dict(u, formazioni=u['formazioni']) for u in unita_astensione_uso],
                    idx_classifiche, set_soglie)
                # in V3 confrontiamo G ricalcolato sul pool ridotto (_combinato_v3) vs GF v3
                # esegui_astensione usa sempre '_combinato' per G: sostituiamo temporaneamente.
                for u in unita_astensione_uso:
                    for r in u['pool_rows']:
                        r['_combinato_bak'] = r['_combinato']
                        if r.get('_combinato_v3') is not None:
                            r['_combinato'] = r['_combinato_v3']
                righe_g_v3 = P20G.esegui_astensione(unita_astensione_uso, idx_classifiche, set_soglie)
                for u in unita_astensione_uso:
                    for r in u['pool_rows']:
                        r['_odds_combinato_bak'] = r['_odds_combinato']
                        if r.get('_gf_v3') is not None:
                            r['_odds_combinato'] = r['_gf_v3']
                righe_gf_v3 = P20G.esegui_astensione(unita_astensione_uso, idx_classifiche, set_soglie)
                for u in unita_astensione_uso:
                    for r in u['pool_rows']:
                        r['_combinato'] = r['_combinato_bak']
                        r['_odds_combinato'] = r['_odds_combinato_bak']
                n = len(righe_g_v3)
                netto_g_v3 = sum(r['netto_G'] for r in righe_g_v3)
                netto_gf_v3 = sum(r['netto_GO'] for r in righe_gf_v3)
                print(f'[astensione V3] n_G={n} n_GF={len(righe_gf_v3)}  G(ricalc.)={netto_g_v3:.1f}  GF={netto_gf_v3:.1f}  delta={netto_gf_v3-netto_g_v3:+.1f}')
                blocco[f'astensione_{variante}'] = {'n': n, 'G': netto_g_v3, 'GF': netto_gf_v3, 'delta': netto_gf_v3 - netto_g_v3}
                continue
            # V1/V2: sostituisco temporaneamente _odds_combinato col ramo GF per riusare esegui_astensione (colonna GO)
            for u in astensione:
                for r in u['pool_rows']:
                    r['_odds_combinato_bak'] = r['_odds_combinato']
                    r['_odds_combinato'] = r[label_gf]
            righe_gf = P20G.esegui_astensione(astensione, idx_classifiche, set_soglie)
            for u in astensione:
                for r in u['pool_rows']:
                    r['_odds_combinato'] = r['_odds_combinato_bak']
            netto_gf = sum(r['netto_GO'] for r in righe_gf)
            delta = netto_gf - netto_G
            print(f'[astensione {variante}] n={len(righe_gf)}  G={netto_G:.1f}  GF={netto_gf:.1f}  delta={delta:+.1f}')
            blocco[f'astensione_{variante}'] = {'n': len(righe_gf), 'G': netto_G, 'GF': netto_gf, 'delta': delta}

        # --- ALLOCAZIONE ---
        righe_alloc_G, zgr_G, _ = P20G.esegui_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, '_combinato')
        netto_alloc_G = somma_netto_allocazione(righe_alloc_G)
        print(f'[allocazione] n={len(righe_alloc_G)}  G={netto_alloc_G:.1f}  zero_ripetuti={zgr_G}')
        blocco['allocazione'] = {'n': len(righe_alloc_G), 'G': netto_alloc_G, 'zero_ripetuti': zgr_G}

        for variante, label_gf, uso in (
            ('V1', '_gf_v1', allocazione), ('V2', '_gf_v2', allocazione), ('V3', '_gf_v3', allocazione_v3),
        ):
            if variante == 'V3':
                righe_g_v3, zgr_g3, _ = P20G.esegui_allocazione(uso, idx_classifiche, opportunita, set_soglie, '_combinato_v3')
                righe_gf_v3, zgr_gf3, _ = P20G.esegui_allocazione(uso, idx_classifiche, opportunita, set_soglie, '_gf_v3')
                netto_g3 = somma_netto_allocazione(righe_g_v3)
                netto_gf3 = somma_netto_allocazione(righe_gf_v3)
                media_bs, lo_bs, hi_bs = bootstrap_delta_allocazione(righe_g_v3, righe_gf_v3)
                print(f'[allocazione V3] n_G={len(righe_g_v3)} n_GF={len(righe_gf_v3)}  G={netto_g3:.1f}  GF={netto_gf3:.1f}  delta={netto_gf3-netto_g3:+.1f}  bootstrap_manager IC95=[{lo_bs:.1f};{hi_bs:.1f}]  zero_ripetuti(G,GF)=({zgr_g3},{zgr_gf3})')
                blocco[f'allocazione_{variante}'] = {'n_G': len(righe_g_v3), 'n_GF': len(righe_gf_v3),
                                                       'G': netto_g3, 'GF': netto_gf3, 'delta': netto_gf3 - netto_g3,
                                                       'bootstrap_ic95': [lo_bs, hi_bs], 'zero_ripetuti': zgr_g3 and zgr_gf3}
                continue
            righe_gf, zgr_gf, _ = P20G.esegui_allocazione(uso, idx_classifiche, opportunita, set_soglie, label_gf)
            netto_gf = somma_netto_allocazione(righe_gf)
            delta = netto_gf - netto_alloc_G
            media_bs, lo_bs, hi_bs = bootstrap_delta_allocazione(righe_alloc_G, righe_gf)
            print(f'[allocazione {variante}] n={len(righe_gf)}  G={netto_alloc_G:.1f}  GF={netto_gf:.1f}  delta={delta:+.1f}  bootstrap_manager IC95=[{lo_bs:.1f};{hi_bs:.1f}]  zero_ripetuti={zgr_gf}')
            blocco[f'allocazione_{variante}'] = {'n': len(righe_gf), 'G': netto_alloc_G, 'GF': netto_gf, 'delta': delta,
                                                   'bootstrap_ic95': [lo_bs, hi_bs], 'zero_ripetuti': zgr_gf}

        risultati[nome_set] = blocco

    with open('analisi_manager/p20_gfisso_backtest_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)
    print('\nsalvato analisi_manager/p20_gfisso_backtest_out.json')

    # ---- DUMP LEGGIBILE: un'unita di allocazione, arena per arena ----
    if allocazione:
        u = allocazione[0]
        with open('analisi_manager/p20_gfisso_dump.txt', 'w', encoding='utf-8') as fh:
            fh.write(f"DUMP manager={u['manager']} gw={u['gw']} regime={u['regime']}\n")
            fh.write(f"pool: {len(u['pool_rows'])} carte, slot reali: {u['slot']}\n\n")
            for r in sorted(u['pool_rows'], key=lambda x: -(x['_cal'] or 0))[:40]:
                lettera = NUM_LETTERA.get(r.get('_grade'), '?')
                fh.write(f"{r['slug']:28s} {r['codice']:4s} grade={lettera:1s}  cal={r['_cal']:.1f}  "
                         f"G={r['_combinato']:.1f}  GFv1={r['_gf_v1']:.1f}  GFv2={r['_gf_v2']:.1f}  "
                         f"reale={r.get('reale')}\n")
        print('salvato analisi_manager/p20_gfisso_dump.txt')


if __name__ == '__main__':
    sys.exit(main() or 0)
