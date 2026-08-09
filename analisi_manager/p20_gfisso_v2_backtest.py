"""BRIEF_SONNET_GFISSO_V2_PULITO_2026-08-09.txt -- G FISSO vs G VARIABILE,
test pulito v2 sulla popolazione di produzione (proxy: pool senza le carte
F, approssimazione di "titolarita' >=0.80"). SOLO MISURA, nessuna modifica
alla produzione. Nuovo script: non tocca p20_gfisso_backtest.py ne'
p20_g_odds_arene_backtest.py, li importa e riusa (costruisci_unita,
soglia_decisione, rank_e_premio, punti_da_righe, esegui_allocazione,
carica_classifiche, opportunita_gw_tipo, ricalcola_combinato_gruppo,
NUM_LETTERA).
"""
import os
os.environ.setdefault('ARENA_LEAGUES_ENABLED', 'tutte')

import sys
import io
import json
import random
import statistics
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p20_g_odds_arene_backtest as P20G
import p20_gfisso_backtest as GF1
import p12_backtest_formazione_grade as S21
import analizza_gw as AG

NUM_LETTERA = GF1.NUM_LETTERA
LETTERE_ABCDE = ['A', 'B', 'C', 'D', 'E']

# --- griglia (§ IL MATERIALE / I DUE MODELLI) --------------------------
# (ii) tabella empirica: residui misurati su 25.326 righe (p20_grade_
# residui_allargato_out.json, gia' usata come TABELLA_S1 in p20_gfisso_
# backtest.py). Stessi numeri, non ricalcolati.
TABELLA_EMPIRICA = {'A': 3.87, 'B': 2.66, 'C': 1.70, 'D': 1.26, 'E': -12.46, 'F': -33.15}
# (i) scala dedotta monotona, moltiplicata per k
BASE_SCALA = {'A': 2.0, 'B': 1.0, 'C': 0.0, 'D': -1.0, 'E': -2.0, 'F': -4.0}
K_GRIGLIA = (0.5, 1, 2, 4, 8)

CAP_TYPE_LABEL = {
    'A1_cap260': 'cap260', 'A2_cap220': 'cap220', 'A3_uncapped': 'uncapped', 'A4_beginner': 'beginner',
    'B_us': 'arena_paese', 'B_korea': 'arena_paese', 'B_scotland': 'arena_paese',
}


def costruisci_griglia():
    griglia = []
    for k in K_GRIGLIA:
        tab = {let: v * k for let, v in BASE_SCALA.items()}
        griglia.append({'nome': f'scala_k{k}', 'tabella': tab, 'degenere': False})
    griglia.append({'nome': 'empirica', 'tabella': dict(TABELLA_EMPIRICA), 'degenere': False})
    griglia.append({'nome': 'placebo', 'tabella': {k: 0.0 for k in BASE_SCALA}, 'degenere': True})
    return griglia


# --- popolazioni --------------------------------------------------------

def costruisci_popolazione_noF(unita):
    """P_noF: le carte F escluse DAL POOL (nessuno dei due rami le vede).
    G VARIABILE viene ricalcolato sul pool ridotto (stesso schema di
    p20_gfisso_backtest.ricalcola_combinato_gruppo, campo '_combinato_noF')
    perche' il brief chiede che 'nessuno dei due rami' veda le F, quindi
    anche lo z-score di baseline va ricalcolato senza di loro."""
    nuove = []
    n_scendono = 0
    n_alloc_prima = 0
    for u in unita:
        rows_noF = [r for r in u['pool_rows'] if NUM_LETTERA.get(r.get('_grade')) != 'F']
        gruppi = collections.defaultdict(list)
        for r in rows_noF:
            gruppi[(r['lega'], r['codice'])].append(r)
        for membri in gruppi.values():
            GF1.ricalcola_combinato_gruppo(membri, '_combinato_noF')
        regime = 'astensione' if len(rows_noF) <= u['slot'] else 'allocazione'
        if u['regime'] == 'allocazione':
            n_alloc_prima += 1
            if regime == 'astensione':
                n_scendono += 1
        u2 = dict(u)
        u2['pool_rows'] = rows_noF
        u2['regime'] = regime
        nuove.append(u2)
    return nuove, n_scendono, n_alloc_prima


# --- tabelle (raw/centrata) ---------------------------------------------

def calcola_media_tabella(tutte_rows, tabella):
    vals = [tabella[NUM_LETTERA[r['_grade']]] for r in tutte_rows
            if r.get('_grade') is not None and NUM_LETTERA.get(r['_grade']) in tabella]
    return statistics.mean(vals) if vals else 0.0


def scrivi_gf(pool_rows, tabella):
    for r in pool_rows:
        lettera = NUM_LETTERA.get(r.get('_grade'))
        val = tabella.get(lettera) if lettera else None
        r['_gf_combinato'] = r['_cal'] if val is None else r['_cal'] + val


# --- astensione generica (campi parametrizzati, a differenza di P20G.
# esegui_astensione che ha 'A'/'G'/'GO' fissi) -- riusa soglia_decisione/
# rank_e_premio/punti_da_righe da P20G senza duplicarne la logica -------

def astensione_generica(unita_astensione, idx_classifiche, set_soglie, campo_var, campo_gf):
    righe = []
    for u in unita_astensione:
        riga_per_carta = {r['carta']: r for r in u['pool_rows']}
        for f in u['formazioni']:
            grp = f['gruppo']
            tipo_premio = P20G.TIPO_PREMIO[grp]
            soglia_dec, _pareggio, costo = P20G.soglia_decisione(tipo_premio, set_soglie)
            carte = f['carte']
            rows = [riga_per_carta.get(c.get('carta')) for c in carte]
            if any(r is None for r in rows):
                continue
            cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
            real_points = P20G.punti_da_righe(rows, cap_idx, 'reale')
            rank, premio_std, _n = P20G.rank_e_premio(real_points, f['leaderboard'], idx_classifiche, tipo_premio)
            if rank is None:
                continue
            atteso_var = P20G.punti_da_righe(rows, cap_idx, campo_var)
            atteso_gf = P20G.punti_da_righe(rows, cap_idx, campo_gf)
            riga = {'manager': u['manager'], 'gw': u['gw'], 'gruppo': grp, 'leaderboard': f['leaderboard'],
                    'real_points': real_points, 'rank': rank, 'premio_std': premio_std, 'costo': costo,
                    'soglia_decisione': soglia_dec}
            for lab, atteso in (('var', atteso_var), ('gf', atteso_gf)):
                entra = atteso >= soglia_dec
                netto = (premio_std - costo) if entra else 0.0
                riga[f'entra_{lab}'] = entra
                riga[f'netto_{lab}'] = netto
                riga[f'atteso_{lab}'] = atteso
            righe.append(riga)
    return righe


# --- bootstrap per manager -----------------------------------------------

def bootstrap_delta_astensione(righe, B=3000, seed=51):
    per_m = collections.defaultdict(list)
    for r in righe:
        per_m[r['manager']].append((r['netto_var'], r['netto_gf']))
    managers = sorted(per_m.keys())
    n = len(managers)
    if n == 0:
        return None, None, None
    rnd = random.Random(seed)
    deltas = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = managers[rnd.randrange(n)]
            for va, vg in per_m[m]:
                tot += vg - va
        deltas.append(tot)
    deltas.sort()
    media = sum(deltas) / len(deltas)
    return media, deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas))]


# --- stratificazione per tipo arena --------------------------------------

def stratifica(righe, campo_netto):
    out = collections.defaultdict(lambda: {'n': 0, 'tot': 0.0})
    for r in righe:
        cap = CAP_TYPE_LABEL.get(r['gruppo'], r['gruppo'])
        out[cap]['n'] += 1
        out[cap]['tot'] += r[campo_netto]
    return dict(out)


# --- residui per lega/ruolo (extra §CONTROLLI) ----------------------------

def residui_per_lega_ruolo(unita):
    rows = [r for u in unita for r in u['pool_rows']
            if NUM_LETTERA.get(r.get('_grade')) in LETTERE_ABCDE
            and r.get('reale') is not None and r.get('_cal') is not None]
    per_lega = collections.defaultdict(lambda: collections.defaultdict(list))
    per_ruolo = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        lettera = NUM_LETTERA[r['_grade']]
        resid = r['reale'] - r['_cal']
        per_lega[lettera][r['lega']].append(resid)
        per_ruolo[lettera][r['codice']].append(resid)

    def riassumi(d):
        return {let: {chiave: {'n': len(v), 'media': round(statistics.mean(v), 2)}
                      for chiave, v in dd.items() if len(v) >= 5}
                for let, dd in d.items()}
    return riassumi(per_lega), riassumi(per_ruolo)


def main():
    lega_di = AG.indice_lega()
    idx_num = P20G.GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    unita, conta_cache = P20G.costruisci_unita(None, idx_per_slug, lega_di)
    print(f'unita totali: {len(unita)}')
    for u in unita:
        P20G.applica_odds(u['pool_rows'], k=0.0)  # popola _odds_cal, non usato qui (compat)

    idx_classifiche = P20G.carica_classifiche()
    opportunita = P20G.opportunita_gw_tipo(idx_classifiche, unita)

    unita_noF, n_scendono, n_alloc_prima = costruisci_popolazione_noF(unita)
    n_tot_carte = sum(len(u['pool_rows']) for u in unita)
    n_F = sum(1 for u in unita for r in u['pool_rows'] if NUM_LETTERA.get(r.get('_grade')) == 'F')
    n_grade = sum(1 for u in unita for r in u['pool_rows'] if r.get('_grade') is not None)
    print(f'\nC0 popolazione: pool totale {n_tot_carte} carte, con grade noto {n_grade}, di cui F {n_F}')
    print(f'C1 (P_noF): unita allocazione prima del filtro F: {n_alloc_prima}; '
          f'scendono a pool<=slot dopo il filtro: {n_scendono}')

    popolazioni = {
        'P_ALL': (unita, '_combinato'),
        'P_noF': (unita_noF, '_combinato_noF'),
    }

    # ---- C2 interruttore A/A: tabella=0 -> GF==_cal; tabella grande -> si muove
    prova = unita[0]['pool_rows'][:30] if unita else []
    tab0 = {k: 0.0 for k in BASE_SCALA}
    scrivi_gf(prova, tab0)
    ok_zero = all(abs(r['_gf_combinato'] - r['_cal']) < 1e-9 for r in prova if r.get('_grade') is not None)
    tab_grande = {k: 5000.0 for k in BASE_SCALA}
    scrivi_gf(prova, tab_grande)
    diffs = [abs(r['_gf_combinato'] - r['_cal']) for r in prova if r.get('_grade') is not None]
    ok_grande = bool(diffs) and all(d > 4000 for d in diffs)
    n_con_grade_prova = sum(1 for r in prova if r.get('_grade') is not None)
    print(f'\nC2 interruttore GF: tabella=0 -> identico a _cal: {ok_zero}; '
          f'tabella=+5000 -> si muove: {ok_grande} (carte con grade nel campione: {n_con_grade_prova}/{len(prova)})')

    griglia = costruisci_griglia()

    risultati = {'controlli': {
        'C0_pool_totale': n_tot_carte, 'C0_con_grade': n_grade, 'C0_F': n_F,
        'C1_unita_allocazione_prima_filtro_F': n_alloc_prima, 'C1_scendono_ad_astensione': n_scendono,
        'C2_interruttore_zero_ok': ok_zero, 'C2_interruttore_grande_ok': ok_grande,
    }, 'popolazioni': {}}

    # ---- extra: residui realizzato-atteso per lettera, spaccati per lega/ruolo
    res_lega, res_ruolo = residui_per_lega_ruolo(unita)
    risultati['residui_extra_per_lega'] = res_lega
    risultati['residui_extra_per_ruolo'] = res_ruolo
    print('\nEXTRA (residuo reale-_cal per lettera, spaccato per lega): vedi JSON, campo residui_extra_per_lega')
    print('EXTRA (idem per ruolo): vedi JSON, campo residui_extra_per_ruolo')

    dump_scelto = None  # (delta, pop, tabella_nome, centrata, set_nome, righe_ast_gf, unit_esempio)

    for pop_nome, (unita_pop, campo_var) in popolazioni.items():
        astensione_pop = [u for u in unita_pop if u['regime'] == 'astensione']
        allocazione_pop = [u for u in unita_pop if u['regime'] == 'allocazione']
        tutte_rows = [r for u in unita_pop for r in u['pool_rows']]
        print(f'\n============ POPOLAZIONE {pop_nome} '
              f'(astensione n_unita={len(astensione_pop)}, allocazione n_unita={len(allocazione_pop)}) ============')

        risultati['popolazioni'][pop_nome] = {}

        # baseline G VARIABILE indipendente dalla tabella: 1 calcolo per set soglie, riusato per tutte le tabelle
        baseline = {}
        for set_nome, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
            righe_alloc_var, zgr_var, _ = P20G.esegui_allocazione(allocazione_pop, idx_classifiche, opportunita, set_soglie, campo_var)
            netto_alloc_var = sum(r['netto'] for r in righe_alloc_var)
            baseline[set_nome] = {'righe_alloc_var': righe_alloc_var, 'netto_alloc_var': netto_alloc_var,
                                   'n_alloc_var': len(righe_alloc_var), 'zero_ripetuti_var': zgr_var}
            print(f'[{pop_nome}/{set_nome}] baseline allocazione G_var: n={len(righe_alloc_var)} '
                  f'netto={netto_alloc_var:.1f} zero_ripetuti={zgr_var}')

        for entry in griglia:
            tab_nome, tabella_base, degenere = entry['nome'], entry['tabella'], entry['degenere']
            for centrata in (False, True):
                if centrata:
                    media = calcola_media_tabella(tutte_rows, tabella_base)
                    tabella = {k: v - media for k, v in tabella_base.items()}
                else:
                    media = 0.0
                    tabella = dict(tabella_base)
                for u in unita_pop:
                    scrivi_gf(u['pool_rows'], tabella)

                chiave_tab = f"{tab_nome}{'_centrata' if centrata else ''}"
                risultati['popolazioni'][pop_nome].setdefault(chiave_tab, {'degenere': degenere, 'media_sottratta': media})

                for set_nome, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
                    # --- ASTENSIONE (primario) ---
                    righe_ast = astensione_generica(astensione_pop, idx_classifiche, set_soglie, campo_var, '_gf_combinato')
                    netto_var_ast = sum(r['netto_var'] for r in righe_ast)
                    netto_gf_ast = sum(r['netto_gf'] for r in righe_ast)
                    delta_ast = netto_gf_ast - netto_var_ast
                    media_bs, lo_bs, hi_bs = bootstrap_delta_astensione(righe_ast)
                    strat_var_ast = stratifica(righe_ast, 'netto_var')
                    strat_gf_ast = stratifica(righe_ast, 'netto_gf')

                    # --- ALLOCAZIONE (secondario) ---
                    righe_alloc_gf, zgr_gf, _ = P20G.esegui_allocazione(allocazione_pop, idx_classifiche, opportunita, set_soglie, '_gf_combinato')
                    netto_alloc_gf = sum(r['netto'] for r in righe_alloc_gf)
                    b = baseline[set_nome]
                    delta_alloc = netto_alloc_gf - b['netto_alloc_var']
                    media_bs_a, lo_bs_a, hi_bs_a = GF1.bootstrap_delta_allocazione(b['righe_alloc_var'], righe_alloc_gf)
                    strat_var_alloc = stratifica(b['righe_alloc_var'], 'netto')
                    strat_gf_alloc = stratifica(righe_alloc_gf, 'netto')

                    # --- INSIEME (informativo, non decisivo) ---
                    netto_var_insieme = netto_var_ast + b['netto_alloc_var']
                    netto_gf_insieme = netto_gf_ast + netto_alloc_gf
                    n_insieme_var = len(righe_ast) + b['n_alloc_var']
                    n_insieme_gf = len(righe_ast) + len(righe_alloc_gf)

                    blocco = {
                        'astensione': {
                            'n': len(righe_ast), 'netto_var': netto_var_ast, 'netto_gf': netto_gf_ast,
                            'delta': delta_ast, 'bootstrap_ic95': [lo_bs, hi_bs],
                            'per_cap_type_var': strat_var_ast, 'per_cap_type_gf': strat_gf_ast,
                        },
                        'allocazione': {
                            'n_var': b['n_alloc_var'], 'n_gf': len(righe_alloc_gf),
                            'netto_var': b['netto_alloc_var'], 'netto_gf': netto_alloc_gf,
                            'delta': delta_alloc, 'bootstrap_ic95': [lo_bs_a, hi_bs_a],
                            'zero_ripetuti_gf': zgr_gf,
                            'per_cap_type_var': strat_var_alloc, 'per_cap_type_gf': strat_gf_alloc,
                        },
                        'insieme_informativo': {
                            'n_var': n_insieme_var, 'n_gf': n_insieme_gf,
                            'netto_var': netto_var_insieme, 'netto_gf': netto_gf_insieme,
                            'delta': netto_gf_insieme - netto_var_insieme,
                        },
                    }
                    risultati['popolazioni'][pop_nome][chiave_tab][set_nome] = blocco

                    print(f'[{pop_nome}/{chiave_tab}/{set_nome}] '
                          f'AST n={len(righe_ast)} var={netto_var_ast:.0f} gf={netto_gf_ast:.0f} delta={delta_ast:+.0f} '
                          f'IC95=[{lo_bs:.0f};{hi_bs:.0f}] || '
                          f'ALLOC n_var={b["n_alloc_var"]} n_gf={len(righe_alloc_gf)} '
                          f'var={b["netto_alloc_var"]:.0f} gf={netto_alloc_gf:.0f} delta={delta_alloc:+.0f} '
                          f'IC95=[{lo_bs_a:.0f};{hi_bs_a:.0f}]')

                    if pop_nome == 'P_noF' and not degenere:
                        if dump_scelto is None or delta_ast > dump_scelto[0]:
                            dump_scelto = (delta_ast, pop_nome, tab_nome, centrata, set_nome)

    # ---- DECISIONE (criterio del brief: P_noF, astensione, entrambi i set soglie,
    # segno positivo stabile, IC95 non attraversa zero, tabella non degenere,
    # sia raw che centrata) ----------------------------------------------------
    vincitrici = []
    dati_noF = risultati['popolazioni']['P_noF']
    for entry in griglia:
        if entry['degenere']:
            continue
        for suffisso in ('', '_centrata'):
            chiave = f"{entry['nome']}{suffisso}"
            blocco = dati_noF.get(chiave)
            if not blocco:
                continue
            ok = True
            for set_nome in ('vecchio', 'nuovo'):
                b = blocco.get(set_nome)
                if not b:
                    ok = False
                    break
                d = b['astensione']['delta']
                lo, hi = b['astensione']['bootstrap_ic95']
                if not (d > 0 and lo is not None and lo > 0):
                    ok = False
                    break
            if ok:
                vincitrici.append(chiave)

    # criterio pieno: serve la stessa tabella-base vincente sia raw sia centrata
    basi_vincenti = set()
    for entry in griglia:
        if entry['degenere']:
            continue
        nome = entry['nome']
        if nome in vincitrici and f'{nome}_centrata' in vincitrici:
            basi_vincenti.add(nome)

    verdetto = 'GF VINCE' if basi_vincenti else 'GF NON VINCE'
    risultati['decisione'] = {
        'criterio': 'P_noF, astensione, delta>0 e IC95>0 su ENTRAMBI i set soglie, tabella non degenere, sia raw che centrata',
        'tabelle_che_passano_solo_parzialmente_raw_o_centrata': sorted(vincitrici),
        'tabelle_che_passano_il_criterio_pieno': sorted(basi_vincenti),
        'verdetto': verdetto,
    }
    print(f'\n=== DECISIONE: {verdetto} ===')
    print(f'  tabelle che passano (raw o centrata, singolarmente): {sorted(vincitrici)}')
    print(f'  tabelle che passano il criterio PIENO (raw E centrata): {sorted(basi_vincenti)}')

    with open('analisi_manager/p20_gfisso_v2_backtest_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)
    print('\nsalvato analisi_manager/p20_gfisso_v2_backtest_out.json')

    # ---- DUMP LEGGIBILE --------------------------------------------------
    if dump_scelto:
        d_delta, d_pop, d_tab, d_centrata, d_set = dump_scelto
    else:
        d_delta, d_pop, d_tab, d_centrata, d_set = (0, 'P_noF', 'empirica', False, 'vecchio')
    unita_dump_pop, _campo_var_dump = popolazioni[d_pop]
    # ricrea la tabella scelta per il dump
    entry_dump = next(e for e in griglia if e['nome'] == d_tab)
    tutte_rows_dump = [r for u in unita_dump_pop for r in u['pool_rows']]
    if d_centrata:
        media_dump = calcola_media_tabella(tutte_rows_dump, entry_dump['tabella'])
        tabella_dump = {k: v - media_dump for k, v in entry_dump['tabella'].items()}
    else:
        tabella_dump = dict(entry_dump['tabella'])
    for u in unita_dump_pop:
        scrivi_gf(u['pool_rows'], tabella_dump)

    u_dump = next((u for u in unita_dump_pop if u['formazioni'] and u['pool_rows']), unita_dump_pop[0] if unita_dump_pop else None)
    if u_dump:
        campo_var_dump = _campo_var_dump
        with open('analisi_manager/p20_gfisso_v2_dump.txt', 'w', encoding='utf-8') as fh:
            fh.write(f"DUMP manager={u_dump['manager']} gw={u_dump['gw']} regime={u_dump['regime']}\n")
            fh.write(f"popolazione={d_pop}  tabella={d_tab}{'_centrata' if d_centrata else ''}  set_soglie={d_set}\n")
            fh.write(f"pool: {len(u_dump['pool_rows'])} carte, slot reali: {u_dump['slot']}\n\n")
            fh.write('--- POOL (ordinato per _cal) ---\n')
            for r in sorted(u_dump['pool_rows'], key=lambda x: -(x['_cal'] or 0))[:40]:
                lettera = NUM_LETTERA.get(r.get('_grade'), '?')
                gvar = r.get(campo_var_dump)
                gf = r.get('_gf_combinato')
                fh.write(f"{r['slug']:28s} {r['codice']:4s} lega={r['lega']:14s} grade={lettera:1s}  "
                         f"cal={r['_cal']:.1f}  G_var={gvar if gvar is None else round(gvar,1)}  "
                         f"GF={gf if gf is None else round(gf,1)}  reale={r.get('reale')}\n")
            fh.write('\n--- ARENA PER ARENA (formazioni reali di questa unita) ---\n')
            for f in u_dump['formazioni']:
                fh.write(f"\ngruppo={f['gruppo']}  leaderboard={f['leaderboard']}\n")
                for c in f['carte']:
                    fh.write(f"  carta={c.get('carta')}  slug={c.get('slug')}  ruolo={c.get('ruolo')}  "
                             f"capitano={c.get('capitano')}\n")
        print('salvato analisi_manager/p20_gfisso_v2_dump.txt')

    print(f"\npunteggi grezzi da CACHE: {conta_cache['cache']}  RICOSTRUITI: {conta_cache['fallback']}")


if __name__ == '__main__':
    sys.exit(main() or 0)
