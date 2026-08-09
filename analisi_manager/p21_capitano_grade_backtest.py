"""BRIEF_SONNET_CAPITANO_GRADE_2026-08-09.txt -- capitano scelto col GRADE
(gerarchia lettera > atteso > ruolo) contro il capitano BASELINE
(atteso_cal, S21.capitano_atteso). SOLO MISURA, nessuna modifica alla
produzione. Non tocca p20_g_odds_arene_backtest.py, p20_gfisso_v2_backtest.py,
p12_backtest_formazione_grade.py: li importa e riusa.

INTERPRETAZIONE DELL'ORCHESTRATORE SULLE CARTE F (§1 punto 4 del brief):
il livello (1) della gerarchia elenca solo A>B>C>D>E, F esclusa. Trattiamo
quindi le carte F come le carte SENZA lettera ai fini del livello (4): non
vincono mai automaticamente la fascia col solo grade, competono sempre
sull'atteso_cal (livello 2). Annotato come richiesto dal brief se emergono
casi che la regola non copre esplicitamente.

REGOLA sulla decisione (rule 4): se la lettera migliore fra le carte con
lettera A-E e' A o B, quella carta vince la fascia SEMPRE, a prescindere
dall'atteso delle altre (poi livello 2/3 solo fra le carte a quella stessa
lettera). Se la lettera migliore e' C, D o E, la lettera non da' nessun
vantaggio automatico: TUTTE le carte (incluse quelle senza lettera/F)
competono sull'atteso_cal (livello 2), con eventuale tie-break di ruolo
(livello 3) se gli attesi sono vicini/uguali entro il margine M.

Il conteggio "livello 3 scattato" richiesto dal brief (§4, "due o piu'
candidati A PARI LETTERA con |delta atteso|<=M") e' riportato come
'livello3_pari_lettera' (il caso letterale del brief: tier a stessa
lettera, che si verifica solo nel ramo A/B forzato). Riportiamo INOLTRE
'livello3_misto' per trasparenza: casi in cui il tie-break di ruolo scatta
nel ramo "tutti competono sull'atteso" (lettera C/D/E o assente), che il
testo letterale del brief non nomina esplicitamente ma che la gerarchia
generale (punto 3, nessun vincolo di lettera nel testo) implica. Se il
verdetto sull'ordine dei ruoli dipende da quale dei due si usa, lo si
dichiara.

PERFORMANCE: ricostruire le formazioni con build_one_lineup_with_growth e'
il passo costoso. La decisione di entrata/uscita e il consumo del pool NON
dipendono da quale capitano si guarda DOPO che la formazione e' costruita
(il capitano si sceglie fra le 5 carte gia' scelte): quindi costruiamo le
formazioni UNA SOLA VOLTA per (popolazione, set soglie, ramo di decisione)
e per il confronto (A) ricalcoliamo capitano/M/ordine in post-processing
sulle righe della formazione gia' costruita (nessuna ricostruzione). Per
il confronto (B), che ha una decisione DIVERSA per il ramo grade, serve
un'unica ricostruzione aggiuntiva per popolazione/set-soglie con un
M/ordine di RIFERIMENTO fisso (M_RIFERIMENTO, ORDINE_RIFERIMENTO): la
griglia completa di M/ordine e' misurata solo sul confronto (A), primario.
"""
import os
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    import sys as _sys
    os.execvp(_sys.executable, [_sys.executable] + _sys.argv)

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
import p20_gfisso_v2_backtest as P20V2
import p12_backtest_formazione_grade as S21
import analizza_gw as AG

NUM_LETTERA = P20V2.NUM_LETTERA  # 6->'A' ... 1->'F'
LETTER_RANK = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4}
GRUPPI_ORDINE = ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland')

ORDINE_FWD = ['FWD', 'MID', 'DEF', 'GK']
ORDINE_MID = ['MID', 'FWD', 'DEF', 'GK']
GRIGLIA_M = (0, 0.5, 1, 2, 5)
M_RIFERIMENTO = 1.0
ORDINE_RIFERIMENTO = ORDINE_FWD

PROTEZIONE_SOGLIA_PRIMARIA = 1     # reale <= 1 = non giocante (convenzione repo)
PROTEZIONE_SOGLIA_SENSIBILITA = 20  # reale < 20 = non giocante (chi entra prende ~35)


# ============================================================ capitano ===

def capitano_baseline_da_righe(righe):
    """Stessa formula di S21.capitano_atteso ma su una lista di righe
    (invece che su formazione = lista di tuple (x,r,t))."""
    if not righe:
        return None
    fuori = [r for r in righe if r['role_key'] != 'GK']
    gk = [r for r in righe if r['role_key'] == 'GK']
    bo = max(fuori, key=lambda r: r['atteso_cal']) if fuori else None
    bg = max(gk, key=lambda r: r['atteso_cal']) if gk else None
    marg = getattr(S21.bff, 'GK_CAPTAIN_MARGIN', 0)
    if bg and (not bo or bg['atteso_cal'] >= bo['atteso_cal'] + marg):
        return bg
    return bo or bg


def capitano_grade(righe, ordine_ruoli, M_margine, grade_enabled=True):
    """Gerarchia §1 del brief. Ritorna (riga_capitano, diagnostica)."""
    diag = {'livello3_pari_lettera': 0, 'livello3_misto': 0, 'forzato_AB': 0, 'nessuna_lettera_ABCDE': 0}
    if not righe:
        return None, diag
    if not grade_enabled:
        return capitano_baseline_da_righe(righe), diag

    def lettera(r):
        return NUM_LETTERA.get(r.get('_grade'))

    con_abcde = [r for r in righe if lettera(r) in ('A', 'B', 'C', 'D', 'E')]
    pari_lettera = False
    if con_abcde:
        best_letter_ch = min((lettera(r) for r in con_abcde), key=lambda l: LETTER_RANK[l])
        candidati_best = [r for r in con_abcde if lettera(r) == best_letter_ch]
        if best_letter_ch in ('A', 'B'):
            pool_decisione = candidati_best
            pari_lettera = True
            diag['forzato_AB'] = 1
        else:
            pool_decisione = righe
    else:
        pool_decisione = righe
        diag['nessuna_lettera_ABCDE'] = 1

    max_atteso = max(r['atteso_cal'] for r in pool_decisione)
    tier = [r for r in pool_decisione if max_atteso - r['atteso_cal'] <= M_margine]
    if len(tier) > 1:
        if pari_lettera:
            diag['livello3_pari_lettera'] = 1
        else:
            diag['livello3_misto'] = 1
        rank_ruolo = {ruolo: i for i, ruolo in enumerate(ordine_ruoli)}
        tier_sorted = sorted(tier, key=lambda r: (rank_ruolo.get(r['role_key'], 99), -r['atteso_cal']))
        scelto = tier_sorted[0]
    else:
        scelto = max(pool_decisione, key=lambda r: r['atteso_cal'])
    return scelto, diag


# ============================================================ costruzione formazioni (allocazione) ===

CAMPI_RIGA = ('atteso_cal', '_grade', 'role_key', 'reale', 'carta', 'slug')


def _riga_ridotta(r):
    return {k: r.get(k) for k in CAMPI_RIGA}


def esegui_allocazione_capitano(unita_allocazione, idx_classifiche, opportunita, set_soglie, label,
                                 ordine_riferimento, M_riferimento, decisione='baseline', cap_extra=8):
    """Come P20G.esegui_allocazione (STESSA build_one_lineup_with_growth,
    STESSO ciclo/soglia/consumo pool), ma per ogni arena costruita calcola
    ENTRAMBI i capitani (baseline e grade, con ordine/M di riferimento) e
    salva la formazione ridotta per il ricalcolo successivo (griglia M).
    decisione='baseline'|'grade': quale capitano governa atteso_sum/stop
    (quindi quali arene si giocano e come si consuma il pool)."""
    righe_out = []
    for u in unita_allocazione:
        gw = u['gw']
        gw_data = {'pool': u['pool_rows']}
        role_data, pools, card_pool, leghe = S21.costruisci(gw_data, lambda c: c[label])
        orig_leagues = S21.bfg.LEAGUES
        S21.bfg.LEAGUES = tuple(leghe)
        try:
            for grp in GRUPPI_ORDINE:
                tipo_bfg = P20G.TIPO_BFG[grp]
                tipo_premio = P20G.TIPO_PREMIO[grp]
                soglia_dec, _pareggio, costo = P20G.soglia_decisione(tipo_premio, set_soglie)
                shape = S21.bfg.FORMATION_SHAPES.get(tipo_bfg)
                pool_league = S21.bfg.POOL_LEAGUE_BY_TYPE.get(tipo_bfg)
                if shape is None or pool_league is None or (pool_league != 'mixed' and pool_league not in leghe):
                    continue
                l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
                opp_list = opportunita.get((gw, grp)) or []
                n_entrate = 0
                for _tentativo in range(cap_extra):
                    stato = S21.bfg._istantanea_pool(card_pool)
                    formazione, errore, _ok, _sp = S21.bfg.build_one_lineup_with_growth(
                        shape, pool_league, role_data, pools, card_pool, l10_cap,
                        apply_stack_guard=False, variance_mode=True,
                        apply_positive_synergy=False, strict_gk_anti_synergy=False)
                    if errore or not formazione:
                        S21.bfg._ripristina_pool(card_pool, stato)
                        break
                    righe = [r for _x, r, _t in formazione]
                    cap_base = capitano_baseline_da_righe(righe)
                    cap_grade, diag = capitano_grade(righe, ordine_riferimento, M_riferimento)
                    cap_dec = cap_base if decisione == 'baseline' else cap_grade
                    atteso_sum = sum(r['atteso'] for r in righe) + 0.2 * (cap_dec['atteso'] if cap_dec else 0.0)
                    if atteso_sum < soglia_dec:
                        S21.bfg._ripristina_pool(card_pool, stato)
                        break
                    somma_reale = sum(r['reale'] for r in righe)
                    real_base = somma_reale + 0.2 * (cap_base['reale'] if cap_base else 0.0)
                    real_grade = somma_reale + 0.2 * (cap_grade['reale'] if cap_grade else 0.0)
                    if opp_list:
                        lb = opp_list[n_entrate % len(opp_list)]
                    else:
                        lb = None
                    rank_base = premio_base = rank_grade = premio_grade = None
                    if lb is not None:
                        rank_base, premio_base, _n = P20G.rank_e_premio(real_base, lb, idx_classifiche, tipo_premio)
                        rank_grade, premio_grade, _n = P20G.rank_e_premio(real_grade, lb, idx_classifiche, tipo_premio)
                    premio_base = premio_base or 0
                    premio_grade = premio_grade or 0
                    righe_out.append({
                        'manager': u['manager'], 'gw': gw, 'gruppo': grp, 'label': label,
                        'tipo_premio': tipo_premio, 'leaderboard_usata': lb, 'atteso_decisione': atteso_sum,
                        'costo': costo,
                        'real_base': real_base, 'rank_base': rank_base, 'premio_base': premio_base,
                        'netto_base': premio_base - costo,
                        'real_grade': real_grade, 'rank_grade': rank_grade, 'premio_grade': premio_grade,
                        'netto_grade': premio_grade - costo,
                        'cap_base_carta': cap_base.get('carta') if cap_base else None,
                        'cap_base_reale': cap_base.get('reale') if cap_base else None,
                        'cap_base_lettera': NUM_LETTERA.get(cap_base.get('_grade')) if cap_base else None,
                        'cap_grade_carta': cap_grade.get('carta') if cap_grade else None,
                        'cap_grade_reale': cap_grade.get('reale') if cap_grade else None,
                        'cap_grade_lettera': NUM_LETTERA.get(cap_grade.get('_grade')) if cap_grade else None,
                        'cambia_carta': (cap_base is None or cap_grade is None
                                         or cap_base.get('carta') != cap_grade.get('carta')),
                        'diag_riferimento': diag,
                        'righe_formazione': [_riga_ridotta(r) for r in righe],
                    })
                    n_entrate += 1
        finally:
            S21.bfg.LEAGUES = orig_leagues
    return righe_out


def ricalcola_grade_su_riga(riga, ordine_ruoli, M_margine, idx_classifiche, grade_enabled=True):
    """Post-processing: ricalcola SOLO il capitano grade (nessuna
    ricostruzione di formazione) su una riga gia' costruita da
    esegui_allocazione_capitano, con un M/ordine diversi da quelli di
    riferimento. Usato per la griglia M x ordine sul confronto (A)."""
    righe = riga['righe_formazione']
    cap_grade, diag = capitano_grade(righe, ordine_ruoli, M_margine, grade_enabled=grade_enabled)
    somma_reale = sum(r['reale'] for r in righe)
    real_grade = somma_reale + 0.2 * (cap_grade['reale'] if cap_grade else 0.0)
    rank_grade = premio_grade = None
    if riga['leaderboard_usata'] is not None:
        rank_grade, premio_grade, _n = P20G.rank_e_premio(real_grade, riga['leaderboard_usata'], idx_classifiche, riga['tipo_premio'])
    premio_grade = premio_grade or 0
    return {
        'real_grade': real_grade, 'rank_grade': rank_grade, 'premio_grade': premio_grade,
        'netto_grade': premio_grade - riga['costo'],
        'cap_grade_carta': cap_grade.get('carta') if cap_grade else None,
        'cambia_carta': (riga['cap_base_carta'] is None or cap_grade is None
                         or riga['cap_base_carta'] != cap_grade.get('carta')),
        'diag': diag,
    }


# ============================================================ bootstrap ===

def bootstrap_paired_manager(pairs_per_manager, B=3000, seed=51):
    managers = sorted(pairs_per_manager.keys())
    n = len(managers)
    if n == 0:
        return None, None, None
    rnd = random.Random(seed)
    deltas = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = managers[rnd.randrange(n)]
            tot += sum(pairs_per_manager[m])
        deltas.append(tot)
    deltas.sort()
    media = sum(deltas) / len(deltas)
    return media, deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas))]


def delta_confronto_A(righe, campo_netto_grade='netto_grade', campo_netto_base='netto_base'):
    per_m = collections.defaultdict(list)
    for r in righe:
        per_m[r['manager']].append(r[campo_netto_grade] - r[campo_netto_base])
    delta_tot = sum(v for lst in per_m.values() for v in lst)
    media_bs, lo, hi = bootstrap_paired_manager(per_m)
    return delta_tot, lo, hi, len(righe)


# ============================================================ stratificazione ===

def stratifica_delta(righe, campo_g='netto_grade', campo_b='netto_base'):
    out = collections.defaultdict(lambda: {'n': 0, 'netto_base': 0.0, 'netto_grade': 0.0})
    for r in righe:
        cap = P20V2.CAP_TYPE_LABEL.get(r['gruppo'], r['gruppo'])
        out[cap]['n'] += 1
        out[cap]['netto_base'] += r[campo_b]
        out[cap]['netto_grade'] += r[campo_g]
    for v in out.values():
        v['delta'] = v['netto_grade'] - v['netto_base']
    return dict(out)


# ============================================================ protezione/spinta ===

def protezione_spinta(righe, soglia_dnp):
    if soglia_dnp <= PROTEZIONE_SOGLIA_PRIMARIA:
        protezione = [r for r in righe if r['cap_base_reale'] is not None and r['cap_base_reale'] <= soglia_dnp]
    else:
        protezione = [r for r in righe if r['cap_base_reale'] is not None and r['cap_base_reale'] < soglia_dnp]
    spinta = [r for r in righe if r['cap_base_reale'] is not None and r['cap_grade_reale'] is not None
              and r['cap_base_reale'] >= PROTEZIONE_SOGLIA_SENSIBILITA and r['cap_grade_reale'] >= PROTEZIONE_SOGLIA_SENSIBILITA]
    misto = [r for r in righe if r['cap_base_reale'] is not None and r['cap_grade_reale'] is not None
             and r['cap_base_reale'] < PROTEZIONE_SOGLIA_SENSIBILITA and r['cap_grade_reale'] >= PROTEZIONE_SOGLIA_SENSIBILITA]

    def riassumi(sotto):
        delta_tot, lo, hi, n = delta_confronto_A(sotto)
        return {'n': n, 'delta_netto': delta_tot, 'bootstrap_ic95': [lo, hi]}

    return {'protezione': riassumi(protezione), 'spinta': riassumi(spinta), 'misto_gioca_grade_non_base': riassumi(misto)}


# ============================================================ main ===

def main():
    lega_di = AG.indice_lega()
    idx_num = P20G.GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    unita, conta_cache = P20G.costruisci_unita(None, idx_per_slug, lega_di)
    print(f'unita totali: {len(unita)}')
    managers = sorted(set(u['manager'] for u in unita))
    gws = sorted(set(u['gw'] for u in unita))
    print(f'manager distinti: {len(managers)}  GW distinte: {len(gws)}  GW: {gws}')
    astensione = [u for u in unita if u['regime'] == 'astensione']
    allocazione = [u for u in unita if u['regime'] == 'allocazione']
    print(f'ripartizione: astensione={len(astensione)}  allocazione={len(allocazione)}')

    idx_classifiche = P20G.carica_classifiche()
    opportunita = P20G.opportunita_gw_tipo(idx_classifiche, unita)

    # ---- numeri di controllo (§3 del brief) ----
    unita_noF, n_scendono, n_alloc_prima = P20V2.costruisci_popolazione_noF(unita)
    n_tot_carte = sum(len(u['pool_rows']) for u in unita)
    n_grade = sum(1 for u in unita for r in u['pool_rows'] if r.get('_grade') is not None)
    n_F = sum(1 for u in unita for r in u['pool_rows'] if NUM_LETTERA.get(r.get('_grade')) == 'F')
    print('\n=== CONTROLLO NUMERI (devono combaciare con p20_gfisso_v2_backtest_out.json) ===')
    print(f'pool totale: {n_tot_carte}  con grade noto: {n_grade}  F: {n_F}')
    print(f'unita allocazione prima del filtro F: {n_alloc_prima}  scendono ad astensione dopo: {n_scendono}')
    attesi = (7619, 7381, 778, 53, 2)
    trovati = (n_tot_carte, n_grade, n_F, n_alloc_prima, n_scendono)
    if trovati != attesi:
        print(f'!!! MISMATCH: attesi {attesi}, trovati {trovati} -- FERMO QUI COME DA BRIEF')
        with open('analisi_manager/p21_capitano_grade_out.json', 'w', encoding='utf-8') as fh:
            json.dump({'ERRORE': 'mismatch numeri di controllo', 'attesi': attesi, 'trovati': trovati}, fh)
        return 1
    print('OK: numeri di controllo combaciano.')

    popolazioni = {'P_noF': unita_noF, 'P_ALL': unita}

    # ---- C3: pool vs slot per le unita di allocazione (per popolazione) ----
    controllo_pool_slot = {}
    for pop_nome, unita_pop in popolazioni.items():
        alloc_pop = [u for u in unita_pop if u['regime'] == 'allocazione']
        controllo_pool_slot[pop_nome] = [
            {'manager': u['manager'], 'gw': u['gw'], 'pool': len(u['pool_rows']), 'slot': u['slot']}
            for u in alloc_pop
        ]
        print(f"\nC3 (pool vs slot) {pop_nome}: {len(alloc_pop)} unita allocazione, "
              f"pool medio={sum(x['pool'] for x in controllo_pool_slot[pop_nome])/max(1,len(alloc_pop)):.1f} "
              f"slot medio={sum(x['slot'] for x in controllo_pool_slot[pop_nome])/max(1,len(alloc_pop)):.1f}")

    risultati = {
        'controlli': {
            'pool_totale': n_tot_carte, 'con_grade': n_grade, 'F': n_F,
            'unita_allocazione_prima_filtro_F': n_alloc_prima, 'unita_scendono_astensione': n_scendono,
            'manager_distinti': len(managers), 'gw_distinte': len(gws), 'gw_elenco': gws,
            'ripartizione_astensione_allocazione': {'astensione': len(astensione), 'allocazione': len(allocazione)},
            'pool_vs_slot': controllo_pool_slot,
            'PYTHONHASHSEED': os.environ.get('PYTHONHASHSEED'),
        },
        'popolazioni': {},
    }

    for pop_nome, unita_pop in popolazioni.items():
        allocazione_pop = [u for u in unita_pop if u['regime'] == 'allocazione']
        campo_var = '_combinato_noF' if pop_nome == 'P_noF' else '_combinato'
        risultati['popolazioni'][pop_nome] = {}
        print(f'\n{"="*30} POPOLAZIONE {pop_nome} (allocazione n_unita={len(allocazione_pop)}) {"="*30}')

        for set_nome, set_soglie in (('vecchio', P20G.SOGLIE_VECCHIE), ('nuovo', P20G.SOGLIE_NUOVE)):
            print(f'\n--- set soglie {set_nome} ---')

            # ---- CONFRONTO (A): decisione congelata sul baseline ----
            righe_A = esegui_allocazione_capitano(allocazione_pop, idx_classifiche, opportunita, set_soglie,
                                                   campo_var, ORDINE_RIFERIMENTO, M_RIFERIMENTO, decisione='baseline')
            n_A = len(righe_A)
            netto_base_A = sum(r['netto_base'] for r in righe_A)
            netto_grade_A = sum(r['netto_grade'] for r in righe_A)
            delta_A, lo_A, hi_A, _n = delta_confronto_A(righe_A)
            n_cambia = sum(1 for r in righe_A if r['cambia_carta'])
            print(f'[A] n={n_A}  netto_base={netto_base_A:.1f}  netto_grade={netto_grade_A:.1f}  '
                  f'delta={delta_A:+.1f}  IC95=[{lo_A:.1f};{hi_A:.1f}]  fascia cambia carta: {n_cambia}/{n_A}')

            # C2: distribuzione lettere capitano nei due rami
            dist_base = collections.Counter(r['cap_base_lettera'] or '-' for r in righe_A)
            dist_grade = collections.Counter(r['cap_grade_lettera'] or '-' for r in righe_A)
            print(f'  distribuzione lettere capitano BASELINE: {dict(dist_base)}')
            print(f'  distribuzione lettere capitano GRADE:    {dict(dist_grade)}')

            # C1: interruttore spento = identita' (grade_enabled=False deve riprodurre baseline bit per bit)
            id_ok = True
            for r in righe_A:
                ric = ricalcola_grade_su_riga(r, ORDINE_RIFERIMENTO, M_RIFERIMENTO, idx_classifiche, grade_enabled=False)
                if (abs(ric['real_grade'] - r['real_base']) > 1e-9 or ric['rank_grade'] != r['rank_base']
                        or ric['premio_grade'] != r['premio_base']):
                    id_ok = False
                    break
            print(f'  C1 interruttore spento = identita alla baseline: {id_ok}')

            # stratificazione per tipo arena
            strat_A = stratifica_delta(righe_A)
            print(f'  stratificazione per tipo arena: {strat_A}')

            # protezione / spinta / misto, due soglie DNP
            prot_primaria = protezione_spinta(righe_A, PROTEZIONE_SOGLIA_PRIMARIA)
            prot_sensib = protezione_spinta(righe_A, PROTEZIONE_SOGLIA_SENSIBILITA)
            print(f'  protezione/spinta (soglia<=1): {prot_primaria}')
            print(f'  protezione/spinta (soglia<20, sensibilita): {prot_sensib}')

            # ---- griglia M x ordine ruoli (post-processing, nessuna ricostruzione) ----
            griglia_out = {}
            for M_val in GRIGLIA_M:
                griglia_out[str(M_val)] = {}
                for ord_nome, ordine in (('FWD_MID_DEF_GK', ORDINE_FWD), ('MID_FWD_DEF_GK', ORDINE_MID)):
                    ricalcoli = [ricalcola_grade_su_riga(r, ordine, M_val, idx_classifiche) for r in righe_A]
                    n_liv3 = sum(1 for ric in ricalcoli if ric['diag']['livello3_pari_lettera']
                                 or ric['diag']['livello3_misto'])
                    n_liv3_pari = sum(1 for ric in ricalcoli if ric['diag']['livello3_pari_lettera'])
                    per_m = collections.defaultdict(list)
                    for r, ric in zip(righe_A, ricalcoli):
                        per_m[r['manager']].append(ric['netto_grade'] - r['netto_base'])
                    delta_tot = sum(v for lst in per_m.values() for v in lst)
                    _media_bs, lo_g, hi_g = bootstrap_paired_manager(per_m)
                    griglia_out[str(M_val)][ord_nome] = {
                        'livello3_scattato_totale': n_liv3, 'livello3_pari_lettera': n_liv3_pari,
                        'delta_netto': delta_tot, 'bootstrap_ic95': [lo_g, hi_g],
                    }
                    print(f'    M={M_val} ordine={ord_nome}: livello3 scattato={n_liv3} '
                          f'(pari_lettera={n_liv3_pari})  delta={delta_tot:+.1f} IC95=[{lo_g:.1f};{hi_g:.1f}]')

            # ---- CONFRONTO (B): ogni ramo decide libero ----
            righe_B_base = esegui_allocazione_capitano(allocazione_pop, idx_classifiche, opportunita, set_soglie,
                                                        campo_var, ORDINE_RIFERIMENTO, M_RIFERIMENTO, decisione='baseline')
            righe_B_grade = esegui_allocazione_capitano(allocazione_pop, idx_classifiche, opportunita, set_soglie,
                                                         campo_var, ORDINE_RIFERIMENTO, M_RIFERIMENTO, decisione='grade')
            conta_base = collections.Counter((r['manager'], r['gw'], r['gruppo']) for r in righe_B_base)
            conta_grade = collections.Counter((r['manager'], r['gw'], r['gruppo']) for r in righe_B_grade)
            celle_comuni = set(conta_base) & set(conta_grade)
            celle_tenute = [c for c in celle_comuni if conta_base[c] == conta_grade[c]]
            celle_scartate = (set(conta_base) | set(conta_grade)) - set(celle_tenute)
            righe_B_base_tenute = [r for r in righe_B_base if (r['manager'], r['gw'], r['gruppo']) in set(celle_tenute)]
            righe_B_grade_tenute = [r for r in righe_B_grade if (r['manager'], r['gw'], r['gruppo']) in set(celle_tenute)]
            netto_base_B = sum(r['netto_base'] for r in righe_B_base_tenute)
            netto_grade_B = sum(r['netto_grade'] for r in righe_B_grade_tenute)
            per_m_B = collections.defaultdict(list)
            for r in righe_B_base_tenute:
                per_m_B[r['manager']].append(-r['netto_base'])
            for r in righe_B_grade_tenute:
                per_m_B[r['manager']].append(r['netto_grade'])
            _media_bs_B, lo_B, hi_B = bootstrap_paired_manager(per_m_B)
            delta_B = netto_grade_B - netto_base_B
            print(f'[B] celle tenute={len(celle_tenute)}  celle scartate={len(celle_scartate)}  '
                  f'netto_base={netto_base_B:.1f}  netto_grade={netto_grade_B:.1f}  delta={delta_B:+.1f}  '
                  f'IC95=[{lo_B:.1f};{hi_B:.1f}]  (SECONDARIO, M/ordine di riferimento={M_RIFERIMENTO}/FWD_MID_DEF_GK)')

            risultati['popolazioni'][pop_nome][set_nome] = {
                'confronto_A': {
                    'n': n_A, 'netto_base': netto_base_A, 'netto_grade': netto_grade_A,
                    'delta': delta_A, 'bootstrap_ic95': [lo_A, hi_A],
                    'fascia_cambia_carta': n_cambia,
                    'distribuzione_lettere_base': dict(dist_base), 'distribuzione_lettere_grade': dict(dist_grade),
                    'C1_interruttore_identita': id_ok,
                    'stratificazione_per_tipo_arena': strat_A,
                    'protezione_spinta_soglia1': prot_primaria,
                    'protezione_spinta_soglia20': prot_sensib,
                    'griglia_M_ordine': griglia_out,
                },
                'confronto_B': {
                    'celle_tenute': len(celle_tenute), 'celle_scartate': len(celle_scartate),
                    'netto_base': netto_base_B, 'netto_grade': netto_grade_B,
                    'delta': delta_B, 'bootstrap_ic95': [lo_B, hi_B],
                    'M_riferimento': M_RIFERIMENTO, 'ordine_riferimento': 'FWD_MID_DEF_GK',
                },
            }

            # dump scelto: prima combinazione P_noF/vecchio con >=1 arena
            if pop_nome == 'P_noF' and set_nome == 'vecchio' and righe_A:
                risultati.setdefault('_dump_source', righe_A)

    # ---- CRITERIO DI DECISIONE (§6): P_noF, confronto (A), delta>0 e IC95 basso>0 su ENTRAMBI i set soglie ----
    blocco_noF = risultati['popolazioni']['P_noF']
    ok_vecchio = blocco_noF['vecchio']['confronto_A']['delta'] > 0 and blocco_noF['vecchio']['confronto_A']['bootstrap_ic95'][0] > 0
    ok_nuovo = blocco_noF['nuovo']['confronto_A']['delta'] > 0 and blocco_noF['nuovo']['confronto_A']['bootstrap_ic95'][0] > 0
    verdetto = 'GRADE VINCE' if (ok_vecchio and ok_nuovo) else 'GRADE NON VINCE'
    risultati['decisione'] = {
        'criterio': 'P_noF, confronto (A), delta>0 e IC95 basso>0 su ENTRAMBI i set soglie (M/ordine di riferimento)',
        'M_riferimento': M_RIFERIMENTO, 'ordine_riferimento': 'FWD_MID_DEF_GK',
        'ok_soglie_vecchie': ok_vecchio, 'ok_soglie_nuove': ok_nuovo,
        'verdetto': verdetto,
    }
    print(f'\n=== DECISIONE: {verdetto} ===')
    print(f'  P_noF/vecchio delta={blocco_noF["vecchio"]["confronto_A"]["delta"]:+.1f} '
          f'IC95={blocco_noF["vecchio"]["confronto_A"]["bootstrap_ic95"]}')
    print(f'  P_noF/nuovo   delta={blocco_noF["nuovo"]["confronto_A"]["delta"]:+.1f} '
          f'IC95={blocco_noF["nuovo"]["confronto_A"]["bootstrap_ic95"]}')

    # ---- DUMP LEGGIBILE (C5) ----
    dump_source = risultati.pop('_dump_source', None)
    if dump_source:
        per_um = collections.defaultdict(list)
        for r in dump_source:
            per_um[(r['manager'], r['gw'])].append(r)
        (m_dump, gw_dump), righe_dump = max(per_um.items(), key=lambda kv: len(kv[1]))
        u_dump = next(u for u in unita_noF if u['manager'] == m_dump and u['gw'] == gw_dump)
        with open('analisi_manager/p21_capitano_grade_dump.txt', 'w', encoding='utf-8') as fh:
            fh.write(f'DUMP manager={m_dump} gw={gw_dump}  popolazione=P_noF  set_soglie=vecchio\n')
            fh.write(f"pool: {len(u_dump['pool_rows'])} carte, slot reali: {u_dump['slot']}\n\n")
            fh.write('--- POOL (ordinato per _cal) ---\n')
            for r in sorted(u_dump['pool_rows'], key=lambda x: -(x['_cal'] or 0))[:60]:
                lettera = NUM_LETTERA.get(r.get('_grade'), '?')
                fh.write(f"{r['slug']:28s} {r['codice']:4s} lega={r['lega']:14s} grade={lettera:1s}  "
                         f"cal={r['_cal']:.1f}  combinato_noF={r.get('_combinato_noF')}  reale={r.get('reale')}\n")
            fh.write('\n--- ARENA PER ARENA (formazioni COSTRUITE dal bot, confronto A) ---\n')
            for r in righe_dump:
                fh.write(f"\ngruppo={r['gruppo']}  leaderboard={r['leaderboard_usata']}\n")
                for c in r['righe_formazione']:
                    lettera = NUM_LETTERA.get(c.get('_grade'), '?')
                    is_cap_base = c.get('carta') == r['cap_base_carta']
                    is_cap_grade = c.get('carta') == r['cap_grade_carta']
                    fh.write(f"  slug={c['slug']:24s} ruolo={c['role_key']:4s} grade={lettera:1s}  "
                             f"cal={c['atteso_cal']:.1f}  reale={c['reale']}  "
                             f"{'<-- CAP BASELINE' if is_cap_base else ''}{' <-- CAP GRADE' if is_cap_grade else ''}\n")
                fh.write(f"  realizzato: BASELINE={r['real_base']:.1f} (rank={r['rank_base']} premio={r['premio_base']})  "
                         f"GRADE={r['real_grade']:.1f} (rank={r['rank_grade']} premio={r['premio_grade']})\n")
        print(f'\nsalvato analisi_manager/p21_capitano_grade_dump.txt (manager={m_dump}, gw={gw_dump}, {len(righe_dump)} arene)')

    with open('analisi_manager/p21_capitano_grade_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)
    print('\nsalvato analisi_manager/p21_capitano_grade_out.json')
    print(f"punteggi grezzi da CACHE: {conta_cache['cache']}  RICOSTRUITI: {conta_cache['fallback']}")
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
