"""BRIEF_SONNET_COPERTURA_GRADE_2026-08-09.txt -- copertura del grade: una
formula che non lasci fuori nessuna carta col voto. SOLO MISURA, nessuna
modifica alla produzione, nessuna query, nessuna run GitHub.

Riusa SENZA riscrivere:
  p20_g_odds_arene_backtest.py (P20G): costruisci_unita, carica_classifiche,
    opportunita_gw_tipo, esegui_allocazione, soglia_decisione, rank_e_premio,
    punti_da_righe, SOGLIE_VECCHIE/NUOVE.
  p20_gfisso_v2_backtest.py (GF2): costruisci_popolazione_noF,
    astensione_generica, bootstrap_delta_astensione, stratifica,
    costruisci_griglia, scrivi_gf, calcola_media_tabella, NUM_LETTERA.
  p20_gfisso_backtest.py (GF1): bootstrap_delta_allocazione.
  p12_backtest_formazione_grade.py (S21): zscore_gruppo.

Variante (a) TABELLA FISSA e' gia' stata misurata per intero (griglia
scala_k + empirica, raw/centrata, criterio pieno) in
p20_gfisso_v2_backtest_out.json -- verdetto: nessuna tabella passa il
criterio (GF NON VINCE). Qui NON si rifa quella misura: si riusa il suo
verdetto e si aggiunge solo la CONTABILITA' DI COPERTURA che quello script
non riportava (quante carte restano a zero e perche').
Le varianti NUOVE misurate qui sono (b) IBRIDA e (c) GRUPPO PIU' LARGO.
"""
import os
os.environ.setdefault('ARENA_LEAGUES_ENABLED', 'tutte')
os.environ.setdefault('PYTHONHASHSEED', '0')

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

import p20_g_odds_arene_backtest as P20G
import p20_gfisso_v2_backtest as GF2
import p20_gfisso_backtest as GF1
import p12_backtest_formazione_grade as S21
import analizza_gw as AG

NUM_LETTERA = GF2.NUM_LETTERA

# tabella di fallback per (b): 'empirica', gia' misurata su 25.326 righe,
# stessi numeri di GF2.TABELLA_EMPIRICA (non ricalcolati qui).
TABELLA_FALLBACK = dict(GF2.TABELLA_EMPIRICA)

CONTROLLI_ATTESI = {
    'pool_totale': 7619, 'con_grade': 7381, 'F': 778,
    'unita_allocazione_prima_filtro_F': 53, 'scendono_ad_astensione': 2,
}


# ======================================================================
# FORMULA GENERICA: stesso schema additivo di produzione
# (atteso_combinato = atteso_cal + sd_gruppo(atteso_cal) * z_grade), ma con
# gruppo e fallback parametrizzabili. group_key_fn=None => niente z-score,
# solo tabella (variante a). fallback_tabella=None => nessun fallback,
# le carte in gruppi degeneri restano invariate (questa e' esattamente la
# produzione quando group_key_fn=lambda r:(lega,codice)).
# ======================================================================

def applica_variante(pool_rows, campo_out, group_key_fn, fallback_tabella=None):
    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[group_key_fn(r)].append(r)
    for membri in gruppi.values():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        grade_vals = [m['_grade'] for m in membri if m.get('_grade') is not None]
        degenere_n = len(grade_vals) < 2
        sd_grade = 0.0
        iz = iter(())
        if not degenere_n:
            zg, sd_grade, _mg = S21.zscore_gruppo(grade_vals)
            iz = iter(zg)
        degenere_sd0 = (not degenere_n) and sd_grade == 0.0
        for m in membri:
            if m.get('_grade') is None:
                m[campo_out] = m['_cal']
                m[f'{campo_out}__reason'] = 'nessuna_lettera'
                continue
            if not degenere_n and not degenere_sd0:
                z = next(iz)
                m[campo_out] = m['_cal'] + sd_atteso * z
                m[f'{campo_out}__reason'] = 'zscore'
                continue
            # gruppo degenere: 1 sola lettera oppure lettere tutte uguali
            reason = 'gruppo_1_lettera' if degenere_n else 'lettere_uguali'
            lettera = NUM_LETTERA.get(m['_grade'])
            if fallback_tabella is not None and lettera in fallback_tabella:
                m[campo_out] = m['_cal'] + fallback_tabella[lettera]
                m[f'{campo_out}__reason'] = f'tabella_fallback({reason})'
            else:
                m[campo_out] = m['_cal']
                m[f'{campo_out}__reason'] = reason
        # consuma eventuali z avanzati (non deve succedere, len coerenti)


def applica_tabella_pura(pool_rows, campo_out, tabella):
    """Variante (a): nessun gruppo, solo tabella lettera->punti."""
    for r in pool_rows:
        lettera = NUM_LETTERA.get(r.get('_grade'))
        if lettera is None:
            r[campo_out] = r['_cal']
            r[f'{campo_out}__reason'] = 'nessuna_lettera'
        elif lettera in tabella:
            r[campo_out] = r['_cal'] + tabella[lettera]
            r[campo_out + '__reason'] = 'tabella_fissa'
        else:
            r[campo_out] = r['_cal']
            r[f'{campo_out}__reason'] = 'lettera_fuori_tabella'


def conta_copertura(pool_rows, campo_out, eps=1e-9):
    con_lettera = [r for r in pool_rows if r.get('_grade') is not None]
    non_zero = [r for r in con_lettera if abs(r[campo_out] - r['_cal']) > eps]
    zero = [r for r in con_lettera if abs(r[campo_out] - r['_cal']) <= eps]
    ragioni = collections.Counter(r.get(f'{campo_out}__reason', '?') for r in zero)
    return {
        'con_lettera': len(con_lettera),
        'spostamento_non_zero': len(non_zero),
        'a_zero': len(zero),
        'a_zero_per_ragione': dict(ragioni),
    }


# ======================================================================
# essenze nette per una coppia (baseline, variante), astensione+allocazione,
# stesso schema di GF2.main() ma parametrizzato sulle nostre varianti.
# ======================================================================

def misura_essenze(astensione_pop, allocazione_pop, idx_classifiche, opportunita,
                    campo_baseline, campo_variante, righe_alloc_baseline_cache):
    out = {}
    for set_nome, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
        # --- astensione ---
        righe_ast = GF2.astensione_generica(astensione_pop, idx_classifiche, set_soglie,
                                             campo_baseline, campo_variante)
        netto_base_ast = sum(r['netto_var'] for r in righe_ast)
        netto_var_ast = sum(r['netto_gf'] for r in righe_ast)
        delta_ast = netto_var_ast - netto_base_ast
        media_bs, lo_bs, hi_bs = GF2.bootstrap_delta_astensione(righe_ast)
        strat_base_ast = GF2.stratifica(righe_ast, 'netto_var')
        strat_var_ast = GF2.stratifica(righe_ast, 'netto_gf')

        # --- allocazione (baseline cachata per set_soglie, ricalcolata una sola volta) ---
        righe_alloc_base = righe_alloc_baseline_cache[set_nome]
        righe_alloc_var, zgr_var, _ = P20G.esegui_allocazione(
            allocazione_pop, idx_classifiche, opportunita, set_soglie, campo_variante)
        netto_base_alloc = sum(r['netto'] for r in righe_alloc_base)
        netto_var_alloc = sum(r['netto'] for r in righe_alloc_var)
        delta_alloc = netto_var_alloc - netto_base_alloc
        media_bs_a, lo_bs_a, hi_bs_a = GF1.bootstrap_delta_allocazione(righe_alloc_base, righe_alloc_var)
        strat_base_alloc = GF2.stratifica(righe_alloc_base, 'netto')
        strat_var_alloc = GF2.stratifica(righe_alloc_var, 'netto')

        out[set_nome] = {
            'astensione': {
                'n': len(righe_ast), 'netto_base': netto_base_ast, 'netto_variante': netto_var_ast,
                'delta': delta_ast, 'bootstrap_ic95': [lo_bs, hi_bs],
                'per_cap_type_base': strat_base_ast, 'per_cap_type_variante': strat_var_ast,
            },
            'allocazione': {
                'n_base': len(righe_alloc_base), 'n_variante': len(righe_alloc_var),
                'netto_base': netto_base_alloc, 'netto_variante': netto_var_alloc,
                'delta': delta_alloc, 'bootstrap_ic95': [lo_bs_a, hi_bs_a],
                'zero_ripetuti_variante': zgr_var,
                'per_cap_type_base': strat_base_alloc, 'per_cap_type_variante': strat_var_alloc,
            },
        }
    return out


def criterio_passa_regime(blocco_set_soglie, regime):
    """CRITERIO del brief: delta>0 e IC95>0 su ENTRAMBI i set soglie, NELLO
    STESSO REGIME (astensione o allocazione, mai pesati insieme)."""
    for set_nome in ('vecchio', 'nuovo'):
        b = blocco_set_soglie[set_nome][regime]
        d = b['delta']
        lo, hi = b['bootstrap_ic95']
        if not (d > 0 and lo is not None and lo > 0):
            return False
    return True


def criterio_passa(blocco_set_soglie):
    return {'astensione': criterio_passa_regime(blocco_set_soglie, 'astensione'),
            'allocazione': criterio_passa_regime(blocco_set_soglie, 'allocazione')}


def main():
    lega_di = AG.indice_lega()
    idx_num = P20G.GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    unita, conta_cache = P20G.costruisci_unita(None, idx_per_slug, lega_di)
    idx_classifiche = P20G.carica_classifiche()
    opportunita = P20G.opportunita_gw_tipo(idx_classifiche, unita)
    unita_noF, n_scendono, n_alloc_prima = GF2.costruisci_popolazione_noF(unita)

    n_tot_carte = sum(len(u['pool_rows']) for u in unita)
    n_F = sum(1 for u in unita for r in u['pool_rows'] if NUM_LETTERA.get(r.get('_grade')) == 'F')
    n_grade = sum(1 for u in unita for r in u['pool_rows'] if r.get('_grade') is not None)

    controlli = {
        'pool_totale': n_tot_carte, 'con_grade': n_grade, 'F': n_F,
        'unita_allocazione_prima_filtro_F': n_alloc_prima, 'scendono_ad_astensione': n_scendono,
    }
    print('=== C0 CONTROLLI DI COPERTURA POOL (attesi dal brief) ===')
    for k, v in controlli.items():
        atteso = CONTROLLI_ATTESI[k]
        ok = '=' if v == atteso else '!!! MISMATCH !!!'
        print(f'  {k}: trovato={v}  atteso={atteso}  {ok}')
    mismatch = any(controlli[k] != CONTROLLI_ATTESI[k] for k in CONTROLLI_ATTESI)
    if mismatch:
        print('\n!!! ALMENO UN NUMERO DI CONTROLLO NON CORRISPONDE. Come da brief, mi fermo qui e lo dichiaro. !!!')
        risultati_stop = {'controlli': controlli, 'controlli_attesi': CONTROLLI_ATTESI, 'STOP': True}
        with open('analisi_manager/p22_copertura_grade_out.json', 'w', encoding='utf-8') as fh:
            json.dump(risultati_stop, fh, ensure_ascii=False, indent=1, default=str)
        return 1

    populazioni = {
        'P_ALL': (unita, '_combinato'),
        'P_noF': (unita_noF, '_combinato_noF'),
    }

    risultati = {'controlli': controlli, 'popolazioni': {}}

    # --------------------------------------------------------------
    # C1 INTERRUTTORE SPENTO = IDENTITA': stessa formula/gruppo di
    # produzione via applica_variante deve dare _combinato identico
    # --------------------------------------------------------------
    campione = unita[0]['pool_rows'] if unita else []
    applica_variante(campione, '_check_identita', lambda r: (r['lega'], r['codice']), fallback_tabella=None)
    max_diff_identita = max((abs(r['_check_identita'] - r['_combinato']) for r in campione
                              if r.get('_grade') is not None), default=0.0)
    print(f'\nC1 interruttore spento = identita: max|check-_combinato| = {max_diff_identita:.10f} '
          f'(su {sum(1 for r in campione if r.get("_grade") is not None)} carte con grade, unita 0)')
    risultati['C1_identita_max_diff'] = max_diff_identita

    # --------------------------------------------------------------
    # C5 A/A: due esecuzioni della stessa variante devono dare lo stesso numero
    # --------------------------------------------------------------
    applica_variante(campione, '_aa_run1', lambda r: (r['lega'], r['codice']), fallback_tabella=TABELLA_FALLBACK)
    applica_variante(campione, '_aa_run2', lambda r: (r['lega'], r['codice']), fallback_tabella=TABELLA_FALLBACK)
    max_diff_aa = max((abs(r['_aa_run1'] - r['_aa_run2']) for r in campione), default=0.0)
    print(f'C5 A/A (PYTHONHASHSEED=0 dichiarato): max diff fra due run identiche = {max_diff_aa:.10f}')
    risultati['C5_AA_max_diff'] = max_diff_aa

    dump_pool = None
    dump_unita = None

    for pop_nome, (unita_pop, campo_baseline) in populazioni.items():
        astensione_pop = [u for u in unita_pop if u['regime'] == 'astensione']
        allocazione_pop = [u for u in unita_pop if u['regime'] == 'allocazione']
        tutte_rows = [r for u in unita_pop for r in u['pool_rows']]
        print(f'\n============ POPOLAZIONE {pop_nome} '
              f'(astensione n_unita={len(astensione_pop)}, allocazione n_unita={len(allocazione_pop)}) ============')
        print(f'C4 pool vs slot (allocazione): {[(u["manager"], u["gw"], len(u["pool_rows"]), u["slot"]) for u in allocazione_pop][:3]} ...')

        risultati['popolazioni'][pop_nome] = {}

        # baseline (produzione) allocazione una volta per set soglie, riusata come riferimento
        righe_alloc_baseline_cache = {}
        for set_nome, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
            righe_b, _zgr, _c = P20G.esegui_allocazione(allocazione_pop, idx_classifiche, opportunita, set_soglie, campo_baseline)
            righe_alloc_baseline_cache[set_nome] = righe_b

        # ---- copertura PRODUZIONE (baseline): ricalcolata con applica_variante
        # (fallback=None, stesso gruppo (lega,codice)) SOLO per avere le
        # ragioni di zero; i valori sono identici a campo_baseline (verificato
        # da C1 sopra, stessa formula). IMPORTANTE: lo z-score di produzione e'
        # calcolato PER UNITA' (ogni manager/gw ha il suo pool separato), MAI
        # sull'archivio intero appiattito -- altrimenti si mischiano pool di
        # unita' diverse in un solo gruppo, cambiando media/sd. Quindi si
        # applica unita' per unita', qui e per (b)/(c) piu' sotto.
        campo_prod_check = f'_prod_check_{pop_nome}'
        for u in unita_pop:
            applica_variante(u['pool_rows'], campo_prod_check, lambda r: (r['lega'], r['codice']), fallback_tabella=None)
        max_diff_prod = max((abs(r[campo_prod_check] - r[campo_baseline]) for r in tutte_rows
                              if r.get('_grade') is not None), default=0.0)
        cov_prod = conta_copertura(tutte_rows, campo_prod_check)
        print(f'[{pop_nome}] copertura PRODUZIONE ({campo_baseline}, ricontrollo max_diff={max_diff_prod:.10f}): {cov_prod}')
        risultati['popolazioni'][pop_nome]['copertura_produzione'] = cov_prod
        risultati['popolazioni'][pop_nome]['copertura_produzione_max_diff_check'] = max_diff_prod

        varianti = {}

        # ---- (a) tabella fissa pura (empirica, raw) — coverage nuova, essenze da p20_gfisso_v2 gia' misurate ----
        campo_a = f'_var_a_{pop_nome}'
        applica_tabella_pura(tutte_rows, campo_a, GF2.TABELLA_EMPIRICA)
        cov_a = conta_copertura(tutte_rows, campo_a)
        varianti['a_tabella_fissa_empirica'] = {'copertura': cov_a, 'essenze': 'vedi p20_gfisso_v2_backtest_out.json (gia misurato, non riprodotto)'}
        print(f'[{pop_nome}] copertura (a) tabella fissa pura: {cov_a}')

        # ---- (b) ibrida: z-score se gruppo>=2 lettere e sd>0, altrimenti tabella fallback ----
        # (gruppo PER UNITA', come la produzione -- vedi nota sopra)
        campo_b = f'_var_b_{pop_nome}'
        for u in unita_pop:
            applica_variante(u['pool_rows'], campo_b, lambda r: (r['lega'], r['codice']), fallback_tabella=TABELLA_FALLBACK)
        cov_b = conta_copertura(tutte_rows, campo_b)
        print(f'[{pop_nome}] copertura (b) ibrida: {cov_b}')
        essenze_b = misura_essenze(astensione_pop, allocazione_pop, idx_classifiche, opportunita,
                                    campo_baseline, campo_b, righe_alloc_baseline_cache)
        varianti['b_ibrida'] = {'copertura': cov_b, 'essenze': essenze_b, 'criterio_passa': criterio_passa(essenze_b)}
        for set_nome in ('vecchio', 'nuovo'):
            a = essenze_b[set_nome]['astensione']
            al = essenze_b[set_nome]['allocazione']
            print(f'  (b)/{set_nome} AST n={a["n"]} delta={a["delta"]:+.0f} IC95={a["bootstrap_ic95"]} || '
                  f'ALLOC n_base={al["n_base"]} n_var={al["n_variante"]} delta={al["delta"]:+.0f} IC95={al["bootstrap_ic95"]}')

        # ---- (c) gruppo piu' largo: gruppo=ruolo su tutte le leghe INSIEME,
        # ma sempre DENTRO la stessa unita' (manager/gw) -- il brief allarga
        # solo la lega, non mischia pool di manager/giornate diverse (quello
        # sarebbe un errore diverso, lo stesso appena corretto sopra) ----
        campo_c = f'_var_c_{pop_nome}'
        for u in unita_pop:
            applica_variante(u['pool_rows'], campo_c, lambda r: r['codice'], fallback_tabella=None)
        cov_c = conta_copertura(tutte_rows, campo_c)
        print(f'[{pop_nome}] copertura (c) gruppo largo: {cov_c}')
        essenze_c = misura_essenze(astensione_pop, allocazione_pop, idx_classifiche, opportunita,
                                    campo_baseline, campo_c, righe_alloc_baseline_cache)
        varianti['c_gruppo_largo'] = {'copertura': cov_c, 'essenze': essenze_c, 'criterio_passa': criterio_passa(essenze_c)}
        for set_nome in ('vecchio', 'nuovo'):
            a = essenze_c[set_nome]['astensione']
            al = essenze_c[set_nome]['allocazione']
            print(f'  (c)/{set_nome} AST n={a["n"]} delta={a["delta"]:+.0f} IC95={a["bootstrap_ic95"]} || '
                  f'ALLOC n_base={al["n_base"]} n_var={al["n_variante"]} delta={al["delta"]:+.0f} IC95={al["bootstrap_ic95"]}')

        # ---- C2 interruttore acceso = si muove ----
        for nome_v, campo_v in (('b', campo_b), ('c', campo_c)):
            diffs = [abs(r[campo_v] - r['_cal']) for r in tutte_rows if r.get('_grade') is not None]
            n_camb = sum(1 for d in diffs if d > 1e-9)
            media_d = sum(diffs) / len(diffs) if diffs else 0.0
            max_d = max(diffs) if diffs else 0.0
            print(f'C2 [{pop_nome}] variante {nome_v}: {n_camb}/{len(diffs)} carte cambiate, media={media_d:.3f} max={max_d:.3f}')

        risultati['popolazioni'][pop_nome]['varianti'] = varianti

        if pop_nome == 'P_noF' and dump_pool is None:
            u_dump = next((u for u in unita_pop if u['formazioni'] and len(u['pool_rows']) > 5), None)
            if u_dump:
                dump_pool = u_dump
                dump_unita = u_dump

    # ---- C3 PLACEBO: produzione (G) contro nessun grade (A), riusa p20_g_odds_arene_backtest_out.json ----
    try:
        d_placebo = json.load(open('analisi_manager/p20_g_odds_arene_backtest_out.json', encoding='utf-8'))
        placebo = {}
        for set_nome in ('vecchio', 'nuovo'):
            ast = d_placebo['astensione'][set_nome]
            netA = sum(r['netto_A'] for r in ast)
            netG = sum(r['netto_G'] for r in ast)
            allocA = d_placebo['allocazione'][set_nome]['A']
            allocG = d_placebo['allocazione'][set_nome]['G']
            placebo[set_nome] = {
                'astensione_netA': netA, 'astensione_netG': netG, 'G_meglio_di_A_astensione': netG > netA,
                'allocazione_nettoA': sum(r['netto'] for r in allocA),
                'allocazione_nettoG': sum(r['netto'] for r in allocG),
                'G_meglio_di_A_allocazione': sum(r['netto'] for r in allocG) > sum(r['netto'] for r in allocA),
            }
        risultati['C3_placebo_G_vs_A'] = placebo
        print(f'\nC3 PLACEBO (da p20_g_odds_arene_backtest_out.json, non ricalcolato): {placebo}')
    except FileNotFoundError:
        print('\nC3 PLACEBO: p20_g_odds_arene_backtest_out.json non trovato, salto (dichiarato)')
        risultati['C3_placebo_G_vs_A'] = None

    with open('analisi_manager/p22_copertura_grade_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)
    print('\nsalvato analisi_manager/p22_copertura_grade_out.json')

    # ---- C6 DUMP LEGGIBILE ----
    if dump_unita:
        with open('analisi_manager/p22_copertura_grade_dump.txt', 'w', encoding='utf-8') as fh:
            fh.write(f"DUMP manager={dump_unita['manager']} gw={dump_unita['gw']} regime={dump_unita['regime']}\n")
            fh.write(f"popolazione=P_noF  pool: {len(dump_unita['pool_rows'])} carte, slot reali: {dump_unita['slot']}\n\n")
            fh.write('--- POOL (ordinato per _cal) ---\n')
            campo_b_dump = '_var_b_P_noF'
            campo_c_dump = '_var_c_P_noF'
            for r in sorted(dump_unita['pool_rows'], key=lambda x: -(x['_cal'] or 0)):
                lettera = NUM_LETTERA.get(r.get('_grade'), '?')
                fh.write(f"{r['slug']:28s} {r['codice']:4s} lega={r['lega']:14s} grade={lettera:1s}  "
                         f"cal={r['_cal']:.1f}  "
                         f"PROD={round(r.get('_combinato_noF', r['_cal']), 1)} ({r.get('_combinato_noF__reason', 'n/a')})  "
                         f"B={round(r.get(campo_b_dump, r['_cal']), 1)} ({r.get(campo_b_dump + '__reason', 'n/a')})  "
                         f"C={round(r.get(campo_c_dump, r['_cal']), 1)} ({r.get(campo_c_dump + '__reason', 'n/a')})  "
                         f"reale={r.get('reale')}\n")
            fh.write('\n--- ARENA PER ARENA (formazioni reali di questa unita) ---\n')
            for f in dump_unita['formazioni']:
                fh.write(f"\ngruppo={f['gruppo']}  leaderboard={f['leaderboard']}\n")
                for c in f['carte']:
                    fh.write(f"  carta={c.get('carta')}  slug={c.get('slug')}  ruolo={c.get('ruolo')}  "
                             f"capitano={c.get('capitano')}\n")
            # gruppo di esempio a z=0 in produzione
            gruppi_zero = collections.defaultdict(list)
            for r in dump_unita['pool_rows']:
                if r.get('_grade') is not None and r.get(f'_combinato_noF__reason', '') != 'zscore':
                    gruppi_zero[(r['lega'], r['codice'])].append(r)
            if gruppi_zero:
                (lg, cod), membri = next(iter(gruppi_zero.items()))
                fh.write(f"\n--- ESEMPIO GRUPPO A z=0 IN PRODUZIONE: lega={lg} ruolo={cod} ---\n")
                for r in membri:
                    fh.write(f"  {r['slug']:28s} grade={NUM_LETTERA.get(r.get('_grade'),'?')} "
                             f"ragione={r.get('_combinato_noF__reason')}\n")
        print('salvato analisi_manager/p22_copertura_grade_dump.txt')

    print(f"\npunteggi grezzi da CACHE: {conta_cache['cache']}  RICOSTRUITI: {conta_cache['fallback']}")
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
