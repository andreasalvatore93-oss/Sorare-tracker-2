"""BRIEF_SONNET_G_SOPRA_ODDS_2026-08-09.txt -- quanto del vantaggio di G
sopra A (regime allocazione, +29.050/+24.150 essenze misurati stanotte in
p20_g_odds_arene_backtest.py) e' solo "evitare chi non gioca".

Riusa SENZA riscrivere: p20_g_odds_arene_backtest.py (costruisci_unita/
applica_odds/opportunita_gw_tipo/carica_classifiche/rank_e_premio/soglia_
decisione), p12_backtest_formazione_grade.py (S21.costruisci/capitano_
atteso/bfg), p13_backtest_gw_crowss.py (score gia' in pool_rows['reale']).
Il knapsack (build_one_lineup_with_growth) non viene toccato: la funzione
sotto e' una COPIA di BT.esegui_allocazione con l'unica aggiunta di
catturare, per ogni formazione accettata, quali carte non hanno giocato.

CRITERIO "NON HA GIOCATO" (dichiarato, §brief): pool_rows['reale'] viene
da P13.grezzo_carta, che legge P13.score_da_cache (filtra scoreStatus in
FINAL/REVIEWING) con fallback alla ricostruzione dal punteggio ufficiale
della carta SE la cache non ha un game FINAL/REVIEWING in finestra
(compreso il caso scoreStatus=DID_NOT_PLAY, che score_da_cache scarta
esplicitamente). Quindi 'reale' <= EPS_NON_GIOCANTE (dichiarato 1.0: il
level score minimo per chi scende in campo anche un minuto e' ~35,
§11 HANDOFF_G_ODDS_ARENE) e' un proxy affidabile SUL POOL GIA' ESPOSTO,
senza query aggiuntive.
CONTROLLO INDIPENDENTE: scorestatus_non_giocante() legge DIRETTAMENTE
cache.gamelog(slug) e cerca un nodo nella stessa finestra con
scoreStatus=='DID_NOT_PLAY' esplicito (dato di produzione, gia' letto
altrove nel repo). Riportato per confronto, NON usato per il filtro
(costerebbe una query di cache per carta in piu' senza aggiungere
informazione che 'reale' non abbia gia').
SOLO MISURA. Nessuna modifica alla produzione, nessuna query di rete
(dati gia' scaricati/cachati).
"""
import os
os.environ.setdefault('ARENA_LEAGUES_ENABLED', 'tutte')

import sys
import io
import json
import glob
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p20_g_odds_arene_backtest as BT
import p13_backtest_gw_crowss as P13
import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p20_grade_arene_copertura_finale as GG

cache = P13.cache
EPS_NON_GIOCANTE = 1.0
GRUPPI_ORDINE = ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland')


def scorestatus_non_giocante(slug, d_start, d_end):
    """Controllo INDIPENDENTE (non usato per il filtro): True/False/None
    (None = nessun game della finestra trovato in cache)."""
    a, b = d_start.isoformat()[:10], d_end.isoformat()[:10]
    for nodo in cache.gamelog(slug):
        data = ((nodo.get('anyGame') or {}).get('date') or '')[:10]
        if a <= data <= b:
            return nodo.get('scoreStatus') == 'DID_NOT_PLAY'
    return None


def esegui_allocazione_esteso(unita_allocazione, idx_classifiche, opportunita, set_soglie, label, cap_extra=8):
    """COPIA di BT.esegui_allocazione (stesso knapsack, stessa logica),
    con l'aggiunta di 'carte' (slug/reale/non_giocante) per ogni formazione
    accettata e 'n_non_giocanti'/'ha_non_giocante' come chiavi dirette."""
    righe = []
    for u in unita_allocazione:
        gw = u['gw']
        gw_data = {'pool': u['pool_rows']}
        role_data, pools, card_pool, leghe = S21.costruisci(gw_data, lambda c: c[label])
        orig_leagues = S21.bfg.LEAGUES
        S21.bfg.LEAGUES = tuple(leghe)
        try:
            for grp in GRUPPI_ORDINE:
                tipo_bfg = BT.TIPO_BFG[grp]
                tipo_premio = BT.TIPO_PREMIO[grp]
                soglia_dec, _pareggio, costo = BT.soglia_decisione(tipo_premio, set_soglie)
                shape = S21.bfg.FORMATION_SHAPES.get(tipo_bfg)
                pool_league = S21.bfg.POOL_LEAGUE_BY_TYPE.get(tipo_bfg)
                if shape is None or pool_league is None or (pool_league != 'mixed' and pool_league not in leghe):
                    continue
                l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
                opp_list = opportunita.get((gw, grp)) or []
                n_entrate = 0
                for tentativo in range(cap_extra):
                    stato = S21.bfg._istantanea_pool(card_pool)
                    formazione, errore, _ok, _sp = S21.bfg.build_one_lineup_with_growth(
                        shape, pool_league, role_data, pools, card_pool, l10_cap,
                        apply_stack_guard=False, variance_mode=True,
                        apply_positive_synergy=False, strict_gk_anti_synergy=False)
                    if errore or not formazione:
                        S21.bfg._ripristina_pool(card_pool, stato)
                        break
                    cap_row = S21.capitano_atteso(formazione)
                    atteso_sum = sum(r['atteso'] for _x, r, _t in formazione) + \
                        0.2 * (cap_row['atteso'] if cap_row else 0.0)
                    if atteso_sum < soglia_dec:
                        S21.bfg._ripristina_pool(card_pool, stato)
                        break
                    real_points = sum(r['reale'] for _x, r, _t in formazione) + \
                        0.2 * (cap_row['reale'] if cap_row else 0.0)
                    carte_info = [{'slug': r['slug'], 'nome': r.get('nome'), 'reale': r['reale'],
                                    'non_giocante': (r['reale'] is None or r['reale'] <= EPS_NON_GIOCANTE)}
                                   for _x, r, _t in formazione]
                    n_non_giocanti = sum(1 for c in carte_info if c['non_giocante'])
                    if opp_list:
                        lb = opp_list[n_entrate % len(opp_list)]
                    else:
                        lb = None
                    rank = premio_std = None
                    if lb is not None:
                        rank, premio_std, _n = BT.rank_e_premio(real_points, lb, idx_classifiche, tipo_premio)
                    if premio_std is None:
                        premio_std = 0
                    righe.append({'manager': u['manager'], 'gw': gw, 'gruppo': grp, 'label': label,
                                   'leaderboard_usata': lb, 'atteso': atteso_sum, 'real_points': real_points,
                                   'rank': rank, 'premio_std': premio_std, 'costo': costo,
                                   'netto': premio_std - costo, 'carte': carte_info,
                                   'n_non_giocanti': n_non_giocanti, 'ha_non_giocante': n_non_giocanti > 0})
                    n_entrate += 1
        finally:
            S21.bfg.LEAGUES = orig_leagues
    return righe


def bootstrap_delta(per_manager_x, per_manager_y, B=3000, seed=61):
    managers = sorted(set(per_manager_x) | set(per_manager_y))
    rnd = random.Random(seed)
    n = len(managers)
    if n == 0:
        return None, None, None
    vals = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = managers[rnd.randrange(n)]
            tot += sum(per_manager_x.get(m, [])) - sum(per_manager_y.get(m, []))
        vals.append(tot)
    vals.sort()
    punto = sum(sum(per_manager_x.get(m, [])) - sum(per_manager_y.get(m, [])) for m in managers)
    return punto, vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def totale(righe):
    return sum(r['netto'] for r in righe)


def per_manager(righe):
    pm = collections.defaultdict(list)
    for r in righe:
        pm[r['manager']].append(r['netto'])
    return pm


def main():
    print("=== SETUP (identico a p20_g_odds_arene_backtest.py) ===")
    lega_di = AG.indice_lega()
    idx_num = GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    unita, _conta_cache = BT.costruisci_unita(files, idx_per_slug, lega_di)
    allocazione = [u for u in unita if u['regime'] == 'allocazione']
    print(f"unita allocazione: {len(allocazione)}")

    for u in unita:
        BT.applica_odds(u['pool_rows'], k=BT.K_ODDS)

    idx_classifiche = BT.carica_classifiche()
    opportunita = BT.opportunita_gw_tipo(idx_classifiche, unita)

    # === A/A: riprodurre +29.050 / +24.150 sul pool INTERO, invariato =====
    print("\n=== A/A: riproduzione dei delta di stanotte (pool intero) ===")
    risultati_pool_intero = {}
    for nome_set, set_soglie in (('vecchio', BT.SOGLIE_VECCHIE), ('nuovo', BT.SOGLIE_NUOVE)):
        righe_A = esegui_allocazione_esteso(allocazione, idx_classifiche, opportunita, set_soglie, '_cal')
        righe_G = esegui_allocazione_esteso(allocazione, idx_classifiche, opportunita, set_soglie, '_combinato')
        tot_A, tot_G = totale(righe_A), totale(righe_G)
        delta = tot_G - tot_A
        print(f"  set {nome_set}: A={tot_A:+.0f} ({len(righe_A)} arene)  G={tot_G:+.0f} ({len(righe_G)} arene)  "
              f"delta G-A={delta:+.0f}")
        risultati_pool_intero[nome_set] = {'A': righe_A, 'G': righe_G, 'tot_A': tot_A, 'tot_G': tot_G, 'delta': delta}

    atteso_delta = {'vecchio': 29050, 'nuovo': 24150}
    for nome_set, exp in atteso_delta.items():
        got = risultati_pool_intero[nome_set]['delta']
        scarto = abs(got - exp)
        stato = 'OK' if scarto < 50 else 'SCARTO'
        print(f"  controllo A/A {nome_set}: atteso {exp:+.0f}, ottenuto {got:+.0f} ({stato}, scarto {scarto:.0f})")
        if scarto >= 50:
            print("  ATTENZIONE: A/A NON riprodotto entro tolleranza -- vedi nota nell'handoff prima di fidarsi del resto.")

    with open('analisi_manager/p21_g_titolarita_pool_intero.json', 'w', encoding='utf-8') as fh:
        json.dump({k: {'tot_A': v['tot_A'], 'tot_G': v['tot_G'], 'delta': v['delta'],
                        'A': v['A'], 'G': v['G']}
                   for k, v in risultati_pool_intero.items()},
                  fh, ensure_ascii=False, indent=1, default=str)
    print("salvato analisi_manager/p21_g_titolarita_pool_intero.json")

    # === PASSO 1: DECOMPORRE ================================================
    print("\n=== PASSO 1: decomposizione non-giocanti ===")
    passo1 = {}
    for nome_set in ('vecchio', 'nuovo'):
        righe_A = risultati_pool_intero[nome_set]['A']
        righe_G = risultati_pool_intero[nome_set]['G']
        print(f"\n--- set {nome_set} ---")
        for lab, righe in (('A', righe_A), ('G', righe_G)):
            n_form = len(righe)
            n_con_nongiocante = sum(1 for r in righe if r['ha_non_giocante'])
            n_carte_nongiocanti = sum(r['n_non_giocanti'] for r in righe)
            n_carte_tot = sum(len(r['carte']) for r in righe)
            print(f"  {lab}: {n_form} formazioni, {n_con_nongiocante} con >=1 non-giocante "
                  f"({100*n_con_nongiocante/n_form:.1f}%), {n_carte_nongiocanti}/{n_carte_tot} carte "
                  f"non-giocanti ({100*n_carte_nongiocanti/n_carte_tot:.1f}%)")

        # 1c/1d: costo per bucket (con/senza non-giocante), per ramo
        bucket = {}
        for lab, righe in (('A', righe_A), ('G', righe_G)):
            con = [r for r in righe if r['ha_non_giocante']]
            senza = [r for r in righe if not r['ha_non_giocante']]
            bucket[lab] = {'con_tot': totale(con), 'con_n': len(con),
                            'senza_tot': totale(senza), 'senza_n': len(senza)}
            pa_con = bucket[lab]['con_tot'] / len(con) if con else float('nan')
            pa_senza = bucket[lab]['senza_tot'] / len(senza) if senza else float('nan')
            print(f"  {lab} formazioni CON non-giocante: netto totale={bucket[lab]['con_tot']:+.0f} "
                  f"(n={bucket[lab]['con_n']}, per-arena={pa_con:+.1f})")
            print(f"  {lab} formazioni SENZA non-giocante: netto totale={bucket[lab]['senza_tot']:+.0f} "
                  f"(n={bucket[lab]['senza_n']}, per-arena={pa_senza:+.1f})")

        delta_tot = totale(righe_G) - totale(righe_A)
        delta_con = bucket['G']['con_tot'] - bucket['A']['con_tot']
        delta_senza = bucket['G']['senza_tot'] - bucket['A']['senza_tot']
        quota_con = delta_con / delta_tot if delta_tot else float('nan')
        print(f"  delta G-A totale: {delta_tot:+.0f}  (bucket CON non-giocante: {delta_con:+.0f}, "
              f"bucket SENZA: {delta_senza:+.0f}, quota attribuibile a CON: {100*quota_con:.1f}%)")

        passo1[nome_set] = {'bucket': bucket, 'delta_tot': delta_tot, 'delta_con': delta_con,
                             'delta_senza': delta_senza, 'quota_con': quota_con}

    with open('analisi_manager/p21_g_titolarita_passo1_out.json', 'w', encoding='utf-8') as fh:
        json.dump(passo1, fh, ensure_ascii=False, indent=1, default=str)
    print("\nsalvato analisi_manager/p21_g_titolarita_passo1_out.json")

    # === PASSO 2: POOL RIPULITO DAI NON-GIOCANTI VERI =======================
    print("\n=== PASSO 2: pool ripulito (filtro titolarita' PERFETTO) ===")
    allocazione_pulita = []
    n_unita_scese_a_pool_uguale_slot = 0
    tot_carte_tolte = tot_carte_rimaste = 0
    for u in allocazione:
        pool_rows_puliti = [r for r in u['pool_rows'] if not (r['reale'] is None or r['reale'] <= EPS_NON_GIOCANTE)]
        n_tolte = len(u['pool_rows']) - len(pool_rows_puliti)
        tot_carte_tolte += n_tolte
        tot_carte_rimaste += len(pool_rows_puliti)
        if len(pool_rows_puliti) <= u['slot']:
            n_unita_scese_a_pool_uguale_slot += 1
            continue  # esce dal regime allocazione (controllo §obbligatorio)
        u2 = dict(u)
        u2['pool_rows'] = pool_rows_puliti
        allocazione_pulita.append(u2)

    print(f"unita allocazione originali: {len(allocazione)}, dopo pulizia restano in regime "
          f"allocazione: {len(allocazione_pulita)} (escluse perche' scese a pool<=slot: "
          f"{n_unita_scese_a_pool_uguale_slot})")
    print(f"carte tolte dal pool in totale: {tot_carte_tolte}, carte rimaste: {tot_carte_rimaste} "
          f"({100*tot_carte_tolte/(tot_carte_tolte+tot_carte_rimaste):.1f}% tolte)")

    passo2 = {'n_unita_originali': len(allocazione), 'n_unita_pulite': len(allocazione_pulita),
              'n_unita_escluse_pool_uguale_slot': n_unita_scese_a_pool_uguale_slot,
              'carte_tolte': tot_carte_tolte, 'carte_rimaste': tot_carte_rimaste, 'per_set': {}}

    for nome_set, set_soglie in (('vecchio', BT.SOGLIE_VECCHIE), ('nuovo', BT.SOGLIE_NUOVE)):
        righe_A2 = esegui_allocazione_esteso(allocazione_pulita, idx_classifiche, opportunita, set_soglie, '_cal')
        righe_G2 = esegui_allocazione_esteso(allocazione_pulita, idx_classifiche, opportunita, set_soglie, '_combinato')
        pm_A2, pm_G2 = per_manager(righe_A2), per_manager(righe_G2)
        punto, lo, hi = bootstrap_delta(pm_G2, pm_A2)
        tot_A2, tot_G2 = totale(righe_A2), totale(righe_G2)
        print(f"\n--- set {nome_set}, pool ripulito ---")
        print(f"  A: netto totale={tot_A2:+.0f} ({len(righe_A2)} arene)  G: netto totale={tot_G2:+.0f} "
              f"({len(righe_G2)} arene)")
        print(f"  DELTA G contro A (pool ripulito): {punto:+.0f}  IC95=[{lo:+.0f},{hi:+.0f}]")
        print(f"  confronto col pool intero (stesso set): delta pool intero = "
              f"{risultati_pool_intero[nome_set]['delta']:+.0f}")
        passo2['per_set'][nome_set] = {'tot_A': tot_A2, 'tot_G': tot_G2, 'delta_punto': punto,
                                        'delta_ic95_lo': lo, 'delta_ic95_hi': hi,
                                        'n_arene_A': len(righe_A2), 'n_arene_G': len(righe_G2)}

    with open('analisi_manager/p21_g_titolarita_passo2_out.json', 'w', encoding='utf-8') as fh:
        json.dump(passo2, fh, ensure_ascii=False, indent=1, default=str)
    print("\nsalvato analisi_manager/p21_g_titolarita_passo2_out.json")

    # === CONTROLLO INDIPENDENTE scoreStatus (su un campione, evita costo enorme) ===
    print("\n=== CONTROLLO scoreStatus DID_NOT_PLAY (campione righe A/G set vecchio) ===")
    campione = (risultati_pool_intero['vecchio']['A'][:60] + risultati_pool_intero['vecchio']['G'][:60])
    accordo = disaccordo = nessun_dato = 0
    for r in campione:
        for c in r['carte']:
            u_match = next((u for u in allocazione if u['manager'] == r['manager'] and u['gw'] == r['gw']), None)
            if u_match is None:
                continue
            ss = scorestatus_non_giocante(c['slug'], u_match['d_start'], u_match['d_end'])
            if ss is None:
                nessun_dato += 1
            elif ss == c['non_giocante']:
                accordo += 1
            else:
                disaccordo += 1
    print(f"  accordo reale<=eps vs scoreStatus: {accordo} accordo, {disaccordo} disaccordo, "
          f"{nessun_dato} senza game in finestra (giocatore senza partite nella GW)")

    # === DUMP: un caso dove A pesca un non-giocante e G no =================
    print("\n=== DUMP: A pesca un non-giocante, G no (stesso manager/gw/gruppo se possibile) ===")
    righe_A_v = risultati_pool_intero['vecchio']['A']
    righe_G_v = risultati_pool_intero['vecchio']['G']
    trovato = None
    for rA in righe_A_v:
        if not rA['ha_non_giocante']:
            continue
        for rG in righe_G_v:
            if rG['manager'] == rA['manager'] and rG['gw'] == rA['gw'] and rG['gruppo'] == rA['gruppo'] \
                    and not rG['ha_non_giocante']:
                trovato = (rA, rG)
                break
        if trovato:
            break
    if trovato:
        rA, rG = trovato
        print(f"  manager={rA['manager']}  gw={rA['gw']}  gruppo={rA['gruppo']}")
        print("  --- formazione A (obiettivo A, pesca un non-giocante) ---")
        for c in rA['carte']:
            print(f"    {(c['nome'] or c['slug']):30s} reale={c['reale']}  non_giocante={c['non_giocante']}")
        print(f"    atteso={rA['atteso']:.1f}  real_points={rA['real_points']:.1f}  netto={rA['netto']:+.0f}")
        print("  --- formazione G (stesso manager/gw/gruppo, obiettivo G, nessun non-giocante) ---")
        for c in rG['carte']:
            print(f"    {(c['nome'] or c['slug']):30s} reale={c['reale']}  non_giocante={c['non_giocante']}")
        print(f"    atteso={rG['atteso']:.1f}  real_points={rG['real_points']:.1f}  netto={rG['netto']:+.0f}")
    else:
        print("  Nessun caso trovato con A che pesca un non-giocante E G che nello stesso "
              "manager/gw/gruppo non lo pesca (possono capitare su gruppi diversi -- vedi JSON grezzo).")


if __name__ == '__main__':
    sys.exit(main() or 0)
