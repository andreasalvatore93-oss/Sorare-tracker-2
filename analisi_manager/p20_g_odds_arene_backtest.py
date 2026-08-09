"""BRIEF_SONNET_G_ODDS_ARENE_2026-08-09.txt -- il test vero: G contro A e
G+O contro G, sulle arene (825 formazioni, 90 unita' manager/gw, due
regimi separati, due set di soglie). SOLO MISURA, nessuna modifica alla
produzione.

Riusa SENZA riscrivere:
  p13_backtest_gw_crowss.py: costruisci_pool/costruisci_pool_rows/gioca_arene
    (pool globale multi-competizione, punteggio grezzo da cache, D7).
  backtest_arene_previsioni.py: contesto/_p_own_opp_odds/delta_favorito_odds
    (segnale odds, forma DELTA -- stessa scelta gia' fatta in
    p20_odds_vs_grade.py per l'arena, §7c del brief).
  p12_backtest_formazione_grade.py: zscore_gruppo/calibra/costruisci/
    capitano_atteso/build_one_lineup_with_growth (bfg).

SCALA ODDS (§7c): delta_favorito_odds z-scorato per gruppo (lega,codice)
DENTRO ogni unita' (stessa unita' di calcolo del grade in p13), k=0.2 --
stessa convenzione e stesso k gia' usati/misurati sul non-arena
(p20_odds_vs_grade.py, p20_odds_livello_assoluto.py).

ARENE DI LEGA SINGOLA (B us/korea/scotland): mappate a arena_type('mls')/
'kleague'/'scozia' del generatore (richiede ARENA_LEAGUES_ENABLED='tutte',
impostato QUI prima di ogni import di bfg -- variabile d'ambiente di
processo, non tocca alcun file di produzione). Soglie/premi trattati come
Cap 260 (regola esplicita del brief §5/§6 per i premi; scelta dichiarata
per le soglie, stesso trattamento).
"""
import os
os.environ.setdefault('ARENA_LEAGUES_ENABLED', 'tutte')

import sys
import io
import json
import glob
import random
import argparse
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p13_backtest_gw_crowss as P13
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import backtest_arene_previsioni as prev
import p20_grade_arene_copertura_finale as GG
import analizza_gw as AG

cache = P13.cache

GRUPPI = GG.GRUPPI
GW6 = GG.GW6
RUOLO_FULL = {'GK': 'Goalkeeper', 'DEF': 'Defender', 'MID': 'Midfielder', 'FWD': 'Forward'}

# --- gruppo (A1..B_scotland) -> (tipo_bfg, tipo_premio, l10_cap_tipo) -----
TIPO_BFG = {
    'A1_cap260': 'ARENA_ALLSTARS_260', 'A2_cap220': 'ARENA_ALLSTARS_220',
    'A3_uncapped': 'ARENA_ALLSTARS_UNCAPPED', 'A4_beginner': 'ARENA_ALLSTARS_260',
    'B_us': S21.bfg.arena_type('mls'), 'B_korea': S21.bfg.arena_type('kleague'),
    'B_scotland': S21.bfg.arena_type('scozia'),
}
TIPO_PREMIO = {
    'A1_cap260': 'cap260', 'A2_cap220': 'cap220', 'A3_uncapped': 'uncapped', 'A4_beginner': 'beginner',
    'B_us': 'cap260', 'B_korea': 'cap260', 'B_scotland': 'cap260',
}

PREMI_STANDARD = {'cap260': (1300, 800, 500), 'uncapped': (1300, 800, 500),
                   'cap220': (1000, 500, 300), 'beginner': (500, 250, 150)}
COSTI_STANDARD = {'cap260': 300, 'cap220': 300, 'uncapped': 200, 'beginner': 100}

# soglie (§6): due set. Beginner nel set VECCHIO eredita Cap 260 (stessa
# convenzione di p13/produzione: mappato allo stesso tipo_bfg
# ARENA_ALLSTARS_260, dichiarato non inventato).
SOGLIE_VECCHIE = {'pareggio': {'cap260': 259.5, 'cap220': 244.1, 'uncapped': 288.3, 'beginner': 259.5},
                   'guadagno': {'cap260': 7.9, 'cap220': 6.3, 'uncapped': 8.0, 'beginner': 7.9}}
SOGLIE_NUOVE = {'pareggio': {'cap260': 264.5, 'cap220': 247.1, 'uncapped': 279.6, 'beginner': 256.5},
                 'guadagno': {'cap260': 6.96, 'cap220': 5.11, 'uncapped': 5.88, 'beginner': 2.46}}
QUOTA_MINIMA = S21.bfg.QUOTA_MINIMA
K_ODDS = 0.2


def soglia_decisione(tipo_premio, set_soglie):
    pareggio = set_soglie['pareggio'][tipo_premio]
    guadagno = set_soglie['guadagno'][tipo_premio]
    costo = COSTI_STANDARD[tipo_premio]
    return pareggio + costo * QUOTA_MINIMA / guadagno, pareggio, costo


def carica_classifiche():
    idx = {}
    for path in ('dati_globali/classifiche_arene_2026-08-08.json',
                 'dati_globali/classifiche_arene_mancanti_2026-08-09.json'):
        d = json.load(open(path, encoding='utf-8'))
        for a in d['arene']:
            idx[a['slug']] = a
    return idx


def rank_e_premio(punteggio, leaderboard, idx_classifiche, tipo_premio):
    """Rank (1-based) e premio standard. None se leaderboard non in indice
    (non deve succedere dopo il download, ma dichiarato se capita)."""
    arena = idx_classifiche.get(leaderboard)
    if arena is None:
        return None, None, None
    punteggi = arena['punteggi']
    rank = 1 + sum(1 for p in punteggi if p > punteggio)
    premi = PREMI_STANDARD[tipo_premio]
    premio = premi[rank - 1] if rank <= 3 else 0
    return rank, premio, len(punteggi)


def annota_odds(pool_rows, d_start, d_end):
    """Scrive _delta_odds per riga (stesso meccanismo di delta_favorito_odds,
    approssimazione 'fine giornata' gia' usata in p20_odds_vs_grade.py)."""
    fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
    n_con = n_senza = 0
    for r in pool_rows:
        try:
            ctx = prev.contesto(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
        except Exception:
            ctx = None
        d = prev.delta_favorito_odds(ctx) if ctx else None
        r['_delta_odds'] = d
        if d is None:
            n_senza += 1
        else:
            n_con += 1
    return n_con, n_senza


def applica_odds(pool_rows, k):
    """z-score di _delta_odds per gruppo (lega,codice) DENTRO questa unita',
    poi _odds_cal/_odds_combinato con lo stesso schema additivo di
    _combinato (riusa _zgrade gia' scritto da p13.costruisci_pool_rows)."""
    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        idx_con = [i for i, m in enumerate(membri) if m.get('_delta_odds') is not None]
        vals = [membri[i]['_delta_odds'] for i in idx_con]
        if len(vals) >= 2:
            zs, _sd, _m = S21.zscore_gruppo(vals)
            for i, z in zip(idx_con, zs):
                membri[i]['_delta_z'] = z
        for m in membri:
            if '_delta_z' not in m:
                m['_delta_z'] = 0.0
    for r in pool_rows:
        z = r.get('_delta_z', 0.0)
        raw_adj = r['atteso_raw'] * (1.0 + k * z) if k else r['atteso_raw']
        r['_odds_cal'] = S21.bfg.calibra(raw_adj, r['codice'])
    for (_lg, _cod), membri in gruppi.items():
        _z, sd_odds, _m = S21.zscore_gruppo([m['_odds_cal'] for m in membri])
        for m in membri:
            m['_odds_combinato'] = m['_odds_cal'] + sd_odds * m.get('_zgrade', 0.0)


def costruisci_unita(files, idx_per_slug, lega_di):
    """Una voce per (manager,gw) con pool_rows annotati (_cal/_combinato/
    _odds_cal/_odds_combinato), le formazioni reali del perimetro
    (7 gruppi) e la classificazione di regime."""
    formazioni_per_unita = collections.defaultdict(list)
    for f in GG.raccogli_formazioni():
        formazioni_per_unita[(f['manager'], f['gw'])].append(f)

    unita = []
    conta_cache = collections.Counter()
    for (manager, gw), forms in formazioni_per_unita.items():
        righe_gw = P13.carica_gw(manager, gw)
        pool, vuote = P13.costruisci_pool(righe_gw, modo='globale')
        bounds = M.parse_fixture_bounds(gw)
        d_start, d_end = bounds
        pool_rows, scarti = P13.costruisci_pool_rows(pool, d_start, d_end, conta_cache, lega_di, idx_per_slug)
        n_con, n_senza = annota_odds(pool_rows, d_start, d_end)

        slot = sum(len(f['carte']) for f in forms)
        regime = 'astensione' if len(pool) <= slot else 'allocazione'
        unita.append({'manager': manager, 'gw': gw, 'pool': pool, 'pool_rows': pool_rows,
                       'formazioni': forms, 'slot': slot, 'regime': regime,
                       'd_start': d_start, 'd_end': d_end,
                       'odds_con': n_con, 'odds_senza': n_senza})
    return unita, conta_cache


def punti_da_righe(rows, cap_idx, campo='reale'):
    tot = sum(r[campo] for r in rows)
    if cap_idx is not None:
        tot += 0.2 * rows[cap_idx][campo]
    return tot


def esegui_astensione(unita_astensione, idx_classifiche, set_soglie):
    """§4a: formazione FISSA (quella reale), il bot decide solo entra/salta.
    Ritorna righe per manager con essenze nette per A/G/G+O e per REALE."""
    righe = []
    for u in unita_astensione:
        riga_per_carta = {r['carta']: r for r in u['pool_rows']}
        for f in u['formazioni']:
            grp = f['gruppo']
            tipo_bfg = TIPO_BFG[grp]
            tipo_premio = TIPO_PREMIO[grp]
            soglia_dec, pareggio, costo = soglia_decisione(tipo_premio, set_soglie)
            carte = f['carte']
            rows = [riga_per_carta.get(c.get('carta')) for c in carte]
            if any(r is None for r in rows):
                continue
            cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
            real_points = punti_da_righe(rows, cap_idx, 'reale')
            rank, premio_std, n_avv = rank_e_premio(real_points, f['leaderboard'], idx_classifiche, tipo_premio)
            if rank is None:
                continue
            atteso = {'A': punti_da_righe(rows, cap_idx, '_cal'),
                      'G': punti_da_righe(rows, cap_idx, '_combinato'),
                      'GO': punti_da_righe(rows, cap_idx, '_odds_combinato')}
            riga = {'manager': u['manager'], 'gw': u['gw'], 'gruppo': grp, 'leaderboard': f['leaderboard'],
                    'real_points': real_points, 'rank': rank, 'premio_std': premio_std, 'costo': costo,
                    'reale_netto': premio_std - costo, 'soglia_decisione': soglia_dec}
            for label in ('A', 'G', 'GO'):
                entra = atteso[label] >= soglia_dec
                if entra:
                    netto = premio_std - costo
                else:
                    netto = 0.0
                riga[f'entra_{label}'] = entra
                riga[f'netto_{label}'] = netto
                riga[f'atteso_{label}'] = atteso[label]
            righe.append(riga)
    return righe


def esegui_allocazione(unita_allocazione, idx_classifiche, opportunita, set_soglie, label, cap_extra=8):
    """§4b: il bot costruisce le proprie formazioni con build_one_lineup_
    with_growth, LIBERO su tipo/quantita'. Per ogni unita' e ogni tipo
    prova a costruire lineup finche' l'atteso non scende sotto la
    soglia_decisione o il pool si esaurisce, fino a un tetto pratico
    cap_extra per tipo (il pool reale lo rende comunque vincolante prima).
    Le arene aggiuntive vengono assegnate alle leaderboard reali dello
    stesso (gw,tipo) nel nostro indice (`opportunita`), CICLANDO se il
    bot ne vuole piu' di quante ne abbiamo osservate -- approssimazione
    dichiarata (non abbiamo un censimento di TUTTE le arene esistite quel
    giorno, solo quelle viste dai manager tracciati)."""
    righe = []
    zero_giocatori_ripetuti = True
    controllo_carte_diverse = collections.Counter()
    for u in unita_allocazione:
        gw = u['gw']
        gw_data = {'pool': u['pool_rows']}
        role_data, pools, card_pool, leghe = S21.costruisci(gw_data, lambda c: c[label])
        orig_leagues = S21.bfg.LEAGUES
        S21.bfg.LEAGUES = tuple(leghe)
        try:
            for grp in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
                tipo_bfg = TIPO_BFG[grp]
                tipo_premio = TIPO_PREMIO[grp]
                soglia_dec, _pareggio, costo = soglia_decisione(tipo_premio, set_soglie)
                shape = S21.bfg.FORMATION_SHAPES.get(tipo_bfg)
                pool_league = S21.bfg.POOL_LEAGUE_BY_TYPE.get(tipo_bfg)
                if shape is None or pool_league is None or (pool_league != 'mixed' and pool_league not in leghe):
                    continue
                l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
                opp_list = opportunita.get((gw, grp)) or []
                n_entrate = 0
                usati_slug_per_carta = set()
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
                    # S21.costruisci mette l'obiettivo scelto (lambda c: c[label])
                    # nel campo 'atteso' di ogni riga (r['atteso_cal'] e' SEMPRE
                    # _cal, indipendentemente dall'obiettivo -- bug/scorciatoia
                    # gia' presente in p13.gioca_arene, qui evitata usando
                    # 'atteso' che riflette davvero il ramo in corso).
                    atteso_sum = sum(r['atteso'] for _x, r, _t in formazione) + \
                        0.2 * (cap_row['atteso'] if cap_row else 0.0)
                    if atteso_sum < soglia_dec:
                        S21.bfg._ripristina_pool(card_pool, stato)
                        break
                    slug_in_formazione = [r['slug'] for _x, r, _t in formazione]
                    if len(set(slug_in_formazione)) != len(slug_in_formazione):
                        zero_giocatori_ripetuti = False
                    for s in slug_in_formazione:
                        if s in usati_slug_per_carta:
                            controllo_carte_diverse['stesso_slug_riusato_carta_diversa'] += 1
                        usati_slug_per_carta.add(s)
                    real_points = sum(r['reale'] for _x, r, _t in formazione) + \
                        0.2 * (cap_row['reale'] if cap_row else 0.0)
                    if opp_list:
                        lb = opp_list[n_entrate % len(opp_list)]
                    else:
                        lb = None
                    rank = premio_std = None
                    if lb is not None:
                        rank, premio_std, _n = rank_e_premio(real_points, lb, idx_classifiche, tipo_premio)
                    if premio_std is None:
                        premio_std = 0
                    righe.append({'manager': u['manager'], 'gw': gw, 'gruppo': grp, 'label': label,
                                   'leaderboard_usata': lb, 'atteso': atteso_sum, 'real_points': real_points,
                                   'rank': rank, 'premio_std': premio_std, 'costo': costo,
                                   'netto': premio_std - costo})
                    n_entrate += 1
        finally:
            S21.bfg.LEAGUES = orig_leagues
    return righe, zero_giocatori_ripetuti, controllo_carte_diverse


def opportunita_gw_tipo(idx_classifiche, unita_list):
    """Per ogni (gw,gruppo) le leaderboard REALI (nel nostro indice, quindi
    viste da qualche manager tracciato) di quel tipo/giornata -- limite
    dichiarato al punto 4b."""
    out = collections.defaultdict(list)
    for f in GG.raccogli_formazioni():
        if f['leaderboard'] in idx_classifiche:
            out[(f['gw'], f['gruppo'])].append(f['leaderboard'])
    for k in out:
        out[k] = sorted(set(out[k]))
    return out


def bootstrap_manager(per_manager_vals, B=3000, seed=51):
    rnd = random.Random(seed)
    manager_list = sorted(per_manager_vals.keys())
    n = len(manager_list)
    if n == 0:
        return None, None
    vals = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = manager_list[rnd.randrange(n)]
            tot += sum(per_manager_vals[m])
        vals.append(tot)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit-unita', type=int, default=None)
    args = ap.parse_args()

    lega_di = AG.indice_lega()
    # indice DOPO (produzione 6 file + Forward_ampio + Goalkeeper + download
    # arene 09/08): stesso indice gia' costruito e validato in
    # p20_grade_arene_copertura_finale.indice_dopo_download(), riusato qui
    # senza duplicarne la logica. E' gia' slug -> [(data, grade_NUMERICO)]:
    # si passa NUMERICO a P13.costruisci_pool_rows, stessa convenzione di
    # T13.costruisci_pool_rows (vedi commento p19_nonarena_grade_scala.py
    # riga 81, "'_grade' qui e' GIA' numerico"). NON si usa
    # P13.prepara_righe_pool: e' un bug pre-esistente in p13.py (unpacking
    # sbagliato su carica_indice_grade_esteso, che ritorna slug->lista, non
    # (slug,data)->grade -- crasha con ValueError se chiamata) che avrebbe
    # anche prodotto grade a LETTERA, facendo poi crashare lo zscore piu'
    # sotto in costruisci_pool_rows (zscore_gruppo su stringhe). Bypassato
    # costruendo l'indice qui, coerente con la convenzione numerica gia'
    # in uso altrove -- non ho toccato p13.py, annotato in fondo (§ bug).
    idx_num = GG.indice_dopo_download()
    idx_per_slug = collections.defaultdict(dict)
    for slug, entries in idx_num.items():
        for data, gn in entries:
            idx_per_slug[slug][data] = gn

    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    unita, conta_cache = costruisci_unita(files, idx_per_slug, lega_di)
    if args.limit_unita:
        unita = unita[:args.limit_unita]
    print(f'unita totali: {len(unita)}')
    astensione = [u for u in unita if u['regime'] == 'astensione']
    allocazione = [u for u in unita if u['regime'] == 'allocazione']
    print(f'  astensione: {len(astensione)}  allocazione: {len(allocazione)}')

    # --- 7b interruttore ---
    for u in unita:
        applica_odds(u['pool_rows'], k=0.0)
    max_diff = max((abs(r['_odds_cal'] - r['_cal']) for u in unita for r in u['pool_rows']), default=0.0)
    print(f'CONTROLLO 7b interruttore k=0: max|_odds_cal-_cal| = {max_diff:.10f}')

    for u in unita:
        applica_odds(u['pool_rows'], k=K_ODDS)
    n_camb = sum(1 for u in unita for r in u['pool_rows'] if abs(r['_odds_cal'] - r['_cal']) > 1e-9)
    n_tot = sum(len(u['pool_rows']) for u in unita)
    print(f'CONTROLLO 7b k={K_ODDS}: {n_camb}/{n_tot} carte cambiate atteso ({100*n_camb/n_tot:.1f}%)')

    # --- 7d copertura odds sul perimetro (solo le 4125 carte reali, non tutto il pool) ---
    riga_per_carta_per_unita = [{r['carta']: r for r in u['pool_rows']} for u in unita]
    n_con = n_tot_perim = 0
    for u, rpc in zip(unita, riga_per_carta_per_unita):
        for f in u['formazioni']:
            for c in f['carte']:
                r = rpc.get(c.get('carta'))
                n_tot_perim += 1
                if r is not None and r.get('_delta_odds') is not None:
                    n_con += 1
    print(f'CONTROLLO 7d copertura odds sul perimetro arene: {n_con}/{n_tot_perim} ({100*n_con/n_tot_perim:.1f}%)')

    idx_classifiche = carica_classifiche()
    opportunita = opportunita_gw_tipo(idx_classifiche, unita)

    esito = {'interruttore': {'max_diff_k0': max_diff, 'n_cambiate_k02': n_camb, 'n_tot': n_tot},
             'copertura_odds_perimetro': {'con': n_con, 'tot': n_tot_perim},
             'astensione': {}, 'allocazione': {}}

    for nome_set, set_soglie in (('vecchio', SOGLIE_VECCHIE), ('nuovo', SOGLIE_NUOVE)):
        print(f'\n=== SET SOGLIE {nome_set.upper()} ===')
        righe_ast = esegui_astensione(astensione, idx_classifiche, set_soglie)
        print(f'  astensione: {len(righe_ast)} arene valutate')
        esito['astensione'][nome_set] = righe_ast

        righe_alloc_A, zgr_A, ctrl_A = esegui_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, '_cal')
        righe_alloc_G, zgr_G, ctrl_G = esegui_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, '_combinato')
        righe_alloc_GO, zgr_GO, ctrl_GO = esegui_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, '_odds_combinato')
        print(f'  allocazione A: {len(righe_alloc_A)} arene giocate  (zero ripetuti: {zgr_A})')
        print(f'  allocazione G: {len(righe_alloc_G)} arene giocate  (zero ripetuti: {zgr_G})')
        print(f'  allocazione G+O: {len(righe_alloc_GO)} arene giocate  (zero ripetuti: {zgr_GO})')
        esito['allocazione'][nome_set] = {'A': righe_alloc_A, 'G': righe_alloc_G, 'GO': righe_alloc_GO,
                                            'zero_ripetuti': zgr_A and zgr_G and zgr_GO}

    with open('analisi_manager/p20_g_odds_arene_backtest_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito, fh, ensure_ascii=False, indent=1, default=str)
    print('\nsalvato analisi_manager/p20_g_odds_arene_backtest_out.json')
    print(f"punteggi grezzi da CACHE: {conta_cache['cache']}  RICOSTRUITI: {conta_cache['fallback']}")


if __name__ == '__main__':
    sys.exit(main() or 0)


# ===================================================================
# PLACEBO (§7f) -- solo per il ramo G in ALLOCAZIONE, l'unico risultato
# con IC95 tutto positivo (G contro A). Permuta _zgrade dentro ogni
# gruppo (lega,codice) di ogni unita', ricalcola _combinato_perm con la
# STESSA formula additiva (_cal + sd_gruppo(_cal)*z_perm), rigioca G con
# l'obiettivo permutato e confronta il totale netto contro A (fisso).
# ===================================================================
def permuta_grade(pool_rows, rnd):
    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        idx_con = [i for i, m in enumerate(membri) if m.get('_grade') is not None]
        zg_originali = [membri[i]['_zgrade'] for i in idx_con]
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        if idx_con:
            perm = list(zg_originali)
            rnd.shuffle(perm)
            for i, z in zip(idx_con, perm):
                membri[i]['_zgrade_perm'] = z
        for m in membri:
            if '_zgrade_perm' not in m:
                m['_zgrade_perm'] = 0.0
            m['_combinato_perm'] = m['_cal'] + sd_atteso * m['_zgrade_perm']


def placebo_g_vs_a_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, tot_netto_A, N=30, seed0=90000):
    print(f'\nPLACEBO G-vs-A allocazione (N={N}, set soglie usato: vedi chiamata)')
    deltas = []
    for seed in range(N):
        rnd = random.Random(seed0 + seed)
        for u in allocazione:
            permuta_grade(u['pool_rows'], rnd)
        righe_perm, _z, _c = esegui_allocazione(allocazione, idx_classifiche, opportunita, set_soglie, '_combinato_perm')
        tot_perm = sum(r['netto'] for r in righe_perm)
        deltas.append(tot_perm - tot_netto_A)
    deltas.sort()
    return deltas
