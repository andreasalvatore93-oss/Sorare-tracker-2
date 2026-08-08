"""Fronte 2, follow-up (BRIEF_SONNET_FRONTE2_FOLLOWUP_2026-08-08.txt).

Il primo giro (p14_fronte2_astensioni_arena.py) ha trovato G-larga positivo
(+2.900 vs manager -600, IC95 [+100,+7.700]). Questo script NON rifa' il
test: lo mette alla prova su tre fronti, riusando le funzioni di p14.

  Compito B -- anatomia dei gruppi (lega,ruolo): quanto e' vero lo z-score
              quando il gruppo ha 2 soli membri col grade?
  Compito C -- test PLACEBO: grade permutati a caso dentro ogni gruppo.
              Se il vantaggio di G vero non sta nella coda della
              distribuzione placebo, il vantaggio non e' il grade.
  Compito D -- le 28 arene escluse per carta-senza-atteso: quanto pesano
              sul risultato, nei due scenari estremi.

NESSUNA MODIFICA ALLA PRODUZIONE. Solo lettura.

Uso:
  python analisi_manager/p15_fronte2_followup.py
"""
import os
import sys
import io
import glob
import json
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p14_fronte2_astensioni_arena as F14
import p12_backtest_manager_grade as M
import backtest_arene_previsioni as P

S21 = F14.S21
bfg = F14.bfg
cache = F14.cache

RAMI = ['A-stretta', 'G-stretta', 'A-larga', 'G-larga']


# ============================================================ ricostruzione
def costruisci_tutto():
    """Rifa' esattamente la costruzione di p14 (coppie -> campione ->
    pool_rows -> risultati), riusando le funzioni di p14. Ritorna anche le
    28 arene escluse per carta-senza-atteso (servono al compito D) e i
    pool_rows per compito B/C."""
    idx_grade, data_min = M.carica_indice_grade_esteso()
    lega_di = F14.AG.indice_lega()
    manager_files = F14.carica_manager_files()

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
    for manager, gw, arene, pool, d_start, d_end in coppie:
        pool_rows_by_pair[(manager, gw)] = F14.calcola_pool_rows(
            pool, d_start, d_end, idx_grade, lega_di, scarti_atteso)

    risultati = []
    escluse_no_atteso = []   # (manager, gw, f) -- compito D
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
            'A-larga': atteso_A >= soglia,
            'G-larga': atteso_G >= soglia,
        }
        risultati.append({'manager': manager, 'gw': gw, 'tipo': tipo, 'rank': rank,
                          'netto': netto, 'podio': podio_arena, 'rows5': rows5,
                          'atteso_A': atteso_A, 'atteso_G': atteso_G,
                          'decisioni': decisioni})

    return {'idx_grade': idx_grade, 'lega_di': lega_di, 'coppie': coppie,
           'campione': campione, 'pool_rows_by_pair': pool_rows_by_pair,
           'risultati': risultati, 'escluse_no_atteso': escluse_no_atteso}


def saldo_bot(risultati, ramo):
    return sum(r['netto'] for r in risultati if r['decisioni'][ramo])


def saldo_manager(risultati):
    return sum(r['netto'] for r in risultati)


# ==================================================================== A
def compito_a():
    print('=' * 78)
    print('COMPITO A -- correzione sez.12 (fatta in-place nell\'handoff, non qui)')
    print('=' * 78)
    print('A-stretta +2000 batte 0; G-stretta +2600 batte 0; A-larga -100 NON')
    print('batte 0; G-larga +2900 batte 0. 3 rami su 4 battono il pavimento.')


# ==================================================================== B
def compito_b(stato):
    print('\n' + '=' * 78)
    print('COMPITO B -- G e\' acceso o mezzo spento?')
    print('=' * 78)

    # B1: anatomia dei gruppi (lega,ruolo) nei pool usati dal test
    dist_gruppi = collections.Counter()   # n_grade -> numero di gruppi
    carte_totali = 0
    carte_in_gruppo_da_2 = 0
    carte_con_grade_totali = 0
    for (manager, gw), rows in stato['pool_rows_by_pair'].items():
        gruppi = collections.defaultdict(list)
        for r in rows.values():
            gruppi[(r['lega'], r['codice'])].append(r)
        for (_lg, _cod), membri in gruppi.items():
            n_grade = sum(1 for m in membri if m['_grade'] is not None)
            bucket = n_grade if n_grade < 5 else '5+'
            dist_gruppi[bucket] += 1
            carte_totali += len(membri)
            carte_con_grade_totali += n_grade
            if n_grade == 2:
                carte_in_gruppo_da_2 += 2

    print('\nB1 -- distribuzione dei gruppi (lega,ruolo) per numero di membri COL GRADE:')
    for k in (0, 1, 2, 3, 4, '5+'):
        if k in dist_gruppi:
            print(f'  gruppi con {k} membri col grade: {dist_gruppi[k]}')
    print(f'  carte totali nei pool: {carte_totali}, con grade: {carte_con_grade_totali}')
    print(f'  carte che stanno in un gruppo da ESATTAMENTE 2 membri col grade: '
          f'{carte_in_gruppo_da_2}/{carte_con_grade_totali} '
          f'({100*carte_in_gruppo_da_2/carte_con_grade_totali:.1f}% delle carte con grade)')

    # B2: confronto con la produzione -- gruppi (lega,ruolo) reali nei
    # player_card_counts.json di discovery/produzione (stessa struttura che
    # il generatore usa per role_data[lega][ruolo]), fra quelli con grade
    # fetchato (altrimenti G ci gira comunque in fallback, non e' un
    # confronto sullo stesso terreno).
    files = (glob.glob('formazione_*/output/*_discovery/player_card_counts.json')
            + glob.glob('formazione_*/output/*_all/player_card_counts.json'))
    sizes_grade_prod = []
    for fpath in files:
        try:
            d = json.load(open(fpath, encoding='utf-8'))
        except Exception:
            continue
        if not d:
            continue
        n_grade = sum(1 for v in d.values() if v.get('grade'))
        if n_grade == 0:
            continue
        sizes_grade_prod.append(n_grade)
    sizes_grade_prod.sort()

    def mediana(v):
        n = len(v)
        if n == 0:
            return float('nan')
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

    sizes_grade_test = []
    for (manager, gw), rows in stato['pool_rows_by_pair'].items():
        gruppi = collections.defaultdict(list)
        for r in rows.values():
            gruppi[(r['lega'], r['codice'])].append(r)
        for membri in gruppi.values():
            n_grade = sum(1 for m in membri if m['_grade'] is not None)
            if n_grade > 0:
                sizes_grade_test.append(n_grade)
    sizes_grade_test.sort()

    print(f'\nB2 -- membri COL GRADE per gruppo (lega,ruolo), fra i gruppi con almeno 1:')
    print(f'  in produzione (player_card_counts.json di oggi, {len(sizes_grade_prod)} gruppi '
          f'lega/ruolo con grade fetchato): mediana {mediana(sizes_grade_prod):.1f}, '
          f'distribuzione {sizes_grade_prod}')
    print(f'  nel test fronte 2 ({len(sizes_grade_test)} gruppi): mediana '
          f'{mediana(sizes_grade_test):.1f}, distribuzione {sizes_grade_test}')
    if mediana(sizes_grade_prod) <= 2:
        print('  ATTENZIONE: la produzione stessa ha gruppi piccoli su molte leghe/ruolo -- il')
        print('  problema dei gruppi da 2 (z meccanico +-1) NON e\' specifico del test, e\'')
        print('  strutturale ovunque il pool di candidati per lega/ruolo sia piccolo.')

    # B3: da dove viene il delta -- separare le arene dove A/G differiscono
    # in base alla dimensione del gruppo delle carte che hanno spostato la
    # decisione (quelle con _zgrade != 0).
    print('\nB3 -- da dove viene il delta (arene dove A e G decidono diverso):')
    for ramo_a, ramo_g in (('A-stretta', 'G-stretta'), ('A-larga', 'G-larga')):
        delta_gruppi_grandi = 0.0
        delta_gruppi_2 = 0.0
        n_grandi = 0
        n_solo2 = 0
        for r in stato['risultati']:
            dec_a = r['decisioni'][ramo_a]
            dec_g = r['decisioni'][ramo_g]
            if dec_a == dec_g:
                continue
            rows5 = r['rows5']
            gruppo_size = {}
            for row in rows5:
                if row['_zgrade'] != 0.0:
                    gruppo_size[row['carta']] = row.get('_n_grade_gruppo')
            max_size = max(gruppo_size.values()) if gruppo_size else 0
            contributo = r['netto'] if dec_g and not dec_a else (-r['netto'] if dec_a and not dec_g else 0.0)
            if max_size >= 3:
                delta_gruppi_grandi += contributo
                n_grandi += 1
            elif max_size == 2:
                delta_gruppi_2 += contributo
                n_solo2 += 1
        print(f'  {ramo_a}->{ramo_g}: arene con gruppo>=3 che decide: {n_grandi}  '
              f'(contributo al saldo: {delta_gruppi_grandi:+.0f})')
        print(f'                arene SOLO gruppi da 2: {n_solo2}  '
              f'(contributo al saldo: {delta_gruppi_2:+.0f})')
    print('  NOTA: serve _n_grade_gruppo su ogni row (annotato qui sotto prima di B3).')


def annota_dimensione_gruppo(stato):
    """Aggiunge a ogni row _n_grade_gruppo = quanti membri col grade ha il
    suo gruppo (lega,codice) in quella coppia (manager,GW). Serve a B3."""
    for (manager, gw), rows in stato['pool_rows_by_pair'].items():
        gruppi = collections.defaultdict(list)
        for r in rows.values():
            gruppi[(r['lega'], r['codice'])].append(r)
        for membri in gruppi.values():
            n_grade = sum(1 for m in membri if m['_grade'] is not None)
            for m in membri:
                m['_n_grade_gruppo'] = n_grade


# ==================================================================== C
def placebo_pool_rows(rows_orig, rnd):
    """Copia le rows con i _grade permutati a caso DENTRO ogni gruppo
    (lega,codice), poi ricalcola _zgrade/_combinato con la stessa formula
    di p14.calcola_pool_rows (z-score sul gruppo)."""
    rows = {cid: dict(r) for cid, r in rows_orig.items()}
    gruppi = collections.defaultdict(list)
    for r in rows.values():
        gruppi[(r['lega'], r['codice'])].append(r)
    for membri in gruppi.values():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp_idx = [i for i, m in enumerate(membri) if m['_grade'] is not None]
        gp_vals = [membri[i]['_grade'] for i in gp_idx]
        if len(gp_vals) >= 2:
            rnd.shuffle(gp_vals)   # permutazione: stessi valori, assegnazione a caso
            for i, v in zip(gp_idx, gp_vals):
                membri[i]['_grade_perm'] = v
            zg, _, _ = S21.zscore_gruppo(gp_vals)
            it = iter(zg)
            for i in gp_idx:
                membri[i]['_zgrade'] = next(it)
            for i, m in enumerate(membri):
                if i not in gp_idx:
                    m['_zgrade'] = 0.0
        else:
            for m in membri:
                m['_zgrade'] = 0.0
        for m in membri:
            m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']
    return rows


def saldo_placebo(pool_rows_by_pair_placebo, campione_valide, ramo_suffix):
    """ramo_suffix: 'stretta' o 'larga'. Ricalcola solo il ramo G (placebo)
    sulle stesse 142 arene valutate, con soglia dello stesso tipo."""
    tot = 0.0
    for manager, gw, f, cap_idx, tipo_bfg, soglia, soglia_decisione, netto, carte_ids in campione_valide:
        rows_pair = pool_rows_by_pair_placebo[(manager, gw)]
        rows5 = [rows_pair.get(cid) for cid in carte_ids]
        if any(r is None for r in rows5):
            continue
        atteso_G = sum(r['_combinato'] for r in rows5) + 0.2 * rows5[cap_idx]['_combinato']
        soglia_uso = soglia_decisione if ramo_suffix == 'stretta' else soglia
        if atteso_G >= soglia_uso:
            tot += netto
    return tot


def compito_c(stato):
    print('\n' + '=' * 78)
    print('COMPITO C -- TEST PLACEBO (grade permutati a caso dentro il gruppo)')
    print('=' * 78)

    # arene valutabili (142), con i dati minimi per ricalcolare G-placebo
    campione_valide = []
    for r in stato['risultati']:
        manager, gw, tipo = r['manager'], r['gw'], r['tipo']
        tipo_bfg = F14.COMP_TO_TIPO_BFG[tipo]
        soglia = bfg.PAREGGIO_ARENA[tipo_bfg]
        costo = bfg.COSTO_INGRESSO[tipo_bfg]
        guad_punto = bfg.GUADAGNO_PER_PUNTO[tipo_bfg]
        soglia_decisione = soglia + costo * bfg.QUOTA_MINIMA / guad_punto
        carte_ids = [row['carta'] for row in r['rows5']]
        cap_idx = None
        # rows5 e' gia' nell'ordine delle carte della formazione originale;
        # il capitano e' quello con lo stesso indice usato in costruisci_tutto
        # (rows5[cap_idx]) -- lo ricaviamo confrontando atteso_G ricostruito.
        # Piu' robusto: ricalcoliamolo dal campione originale.
        campione_valide.append((manager, gw, r, None, tipo_bfg, soglia, soglia_decisione, r['netto'], carte_ids))

    # servono i cap_idx veri: li ricaviamo scorrendo campione (manager,gw,f)
    # e allineando su tipo+rank+netto (stessa chiave usata sopra).
    lookup_cap = {}
    for manager, gw, f, pool, d_start, d_end in stato['campione']:
        carte = f.get('carte')
        cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
        rank = (f.get('piazzamento') or {}).get('rank')
        tipo = f.get('competizione')
        lookup_cap[(manager, gw, tipo, rank)] = (cap_idx, [c.get('carta') for c in carte])

    campione_valide2 = []
    for manager, gw, r, _cap, tipo_bfg, soglia, soglia_decisione, netto, _cids in campione_valide:
        key = (manager, gw, r['tipo'], r['rank'])
        cap_idx, carte_ids = lookup_cap[key]
        campione_valide2.append((manager, gw, r, cap_idx, tipo_bfg, soglia, soglia_decisione, netto, carte_ids))
    campione_valide = campione_valide2

    saldo_mgr = saldo_manager(stato['risultati'])
    reale_stretta = saldo_bot(stato['risultati'], 'G-stretta') - saldo_mgr
    reale_larga = saldo_bot(stato['risultati'], 'G-larga') - saldo_mgr
    print(f'delta reale G-stretta vs manager: {reale_stretta:+.0f}')
    print(f'delta reale G-larga vs manager: {reale_larga:+.0f}')

    N_PERM = 200
    deltas_stretta = []
    deltas_larga = []
    for seed in range(N_PERM):
        rnd = random.Random(90000 + seed)
        pool_rows_placebo = {key: placebo_pool_rows(rows, rnd)
                             for key, rows in stato['pool_rows_by_pair'].items()}
        sb_stretta = saldo_placebo(pool_rows_placebo, campione_valide, 'stretta')
        sb_larga = saldo_placebo(pool_rows_placebo, campione_valide, 'larga')
        deltas_stretta.append(sb_stretta - saldo_mgr)
        deltas_larga.append(sb_larga - saldo_mgr)

    deltas_stretta.sort()
    deltas_larga.sort()

    def percentile(vals, x):
        n = len(vals)
        sotto = sum(1 for v in vals if v < x)
        uguale = sum(1 for v in vals if v == x)
        return 100 * (sotto + 0.5 * uguale) / n

    pct_stretta = percentile(deltas_stretta, reale_stretta)
    pct_larga = percentile(deltas_larga, reale_larga)

    print(f'\n{N_PERM} permutazioni placebo (grade rimescolati dentro ogni gruppo lega/ruolo):')
    print(f'  regola stretta: distribuzione placebo del delta min={min(deltas_stretta):+.0f} '
          f'mediana={deltas_stretta[N_PERM//2]:+.0f} max={max(deltas_stretta):+.0f}')
    print(f'    G VERO ({reale_stretta:+.0f}) sta al percentile {pct_stretta:.1f} della distribuzione placebo')
    print(f'  regola larga:   distribuzione placebo del delta min={min(deltas_larga):+.0f} '
          f'mediana={deltas_larga[N_PERM//2]:+.0f} max={max(deltas_larga):+.0f}')
    print(f'    G VERO ({reale_larga:+.0f}) sta al percentile {pct_larga:.1f} della distribuzione placebo')

    for nome, pct in (('stretta', pct_stretta), ('larga', pct_larga)):
        if pct >= 95:
            print(f'  -> regola {nome}: il G vero e\' oltre il 95esimo percentile del placebo: SEGNALE VERO.')
        elif pct <= 60:
            print(f'  -> regola {nome}: il G vero e\' dentro la nuvola del placebo (percentile {pct:.0f}): '
                  'il vantaggio NON viene dal grade, viene dal solo perturbare/saltare arene. Da scrivere cosi\'.')
        else:
            print(f'  -> regola {nome}: percentile {pct:.0f}, ne\' chiaramente rumore ne\' chiaramente segnale.')

    return {'reale_stretta': reale_stretta, 'reale_larga': reale_larga,
           'pct_stretta': pct_stretta, 'pct_larga': pct_larga}


# ==================================================================== D
def compito_d(stato):
    print('\n' + '=' * 78)
    print('COMPITO D -- le 28 arene escluse (bias a favore del bot)')
    print('=' * 78)

    escluse = stato['escluse_no_atteso']
    print(f'arene escluse per carta-senza-atteso: {len(escluse)}')

    # D1: motivo per ciascuna carta senza atteso nel pool (34 carte)
    motivi = collections.Counter()
    esempi = []
    slugs_falliti = set()
    for (manager, gw), rows in stato['pool_rows_by_pair'].items():
        pass  # le righe SENZA atteso non sono in rows (calcola_pool_rows le scarta): dobbiamo rifarlo a parte
    for manager, gw, arene, pool, d_start, d_end in stato['coppie']:
        import datetime as _dt
        fine = _dt.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
        for cid, c in pool.items():
            ruolo_full = c.get('ruolo')
            cod = M.ROLE_CODE.get(ruolo_full)
            slug = c.get('slug')
            if cod is None:
                continue
            r = P.score_atteso(cache, slug, ruolo_full, fine)
            if r is not None and r.get('atteso') is not None:
                continue
            if slug in slugs_falliti:
                continue
            slugs_falliti.add(slug)
            gamelog = cache.gamelog(slug)
            if not gamelog:
                motivo = 'cache game-log vuota (slug mai visto)'
            else:
                target = P.partita_target(cache, slug, fine)
                if target is None:
                    motivo = 'nessuna partita trovata entro la finestra (6gg) prima di fine-fixture'
                else:
                    motivo = 'storico insufficiente (finestra_storica fallita)'
            motivi[motivo] += 1
            if len(esempi) < 8:
                esempi.append((c.get('nome'), slug, ruolo_full, motivo, len(gamelog)))

    print(f'\nD1 -- motivi (su {len(slugs_falliti)} slug distinti senza atteso, controllo brief: 34 carte '
          '-- puo\' differire leggermente perche\' qui e\' per SLUG distinto, non per carta):')
    for m, n in motivi.most_common():
        print(f'  {m}: {n}')
    print('  esempi:')
    for nome, slug, ruolo, motivo, n_gamelog in esempi:
        print(f'    {nome} ({slug}, {ruolo}): {motivo}  [gamelog: {n_gamelog} partite]')

    # D2: recuperabili?
    lega_di = stato['lega_di']
    con_lega = sum(1 for _n, slug, _r, mo, _g in esempi if lega_di.get(slug))
    print(f'\nD2 -- NON lancio nessuna estrazione (richiesto dal brief). Diagnosi:')
    n_cache_vuota = motivi.get('cache game-log vuota (slug mai visto)', 0)
    n_no_target = motivi.get('nessuna partita trovata entro la finestra (6gg) prima di fine-fixture', 0)
    print(f'  {n_cache_vuota} slug con cache game-log VUOTA: se la loro lega ha pipeline completa,')
    print(f'    sono recuperabili con un\'estrazione game-log per quello slug (1 query a slug).')
    print(f'  {n_no_target} slug CON cache ma senza una partita trovata vicino alla fine-fixture:')
    print(f'    non e\' un buco di query, e\' che il giocatore non ha giocato in quella finestra')
    print(f'    (o gioca in una lega/fixture che qui non tracciamo) -- non recuperabile con piu\' query.')

    # D3: quanto pesano -- scenario (a) bot gioca tutte le 28, (b) le salta tutte
    print('\nD3 -- quanto pesano le 28 arene escluse sul risultato:')
    netto_escluse_tot = sum(F14.netto_reale(f.get('competizione'), (f.get('piazzamento') or {}).get('rank'))
                            for _m, _g, f in escluse)
    n_escluse = len(escluse)
    print(f'  saldo manager sulle {n_escluse} arene escluse: {netto_escluse_tot:+.0f} '
          f'({netto_escluse_tot/n_escluse if n_escluse else 0:+.1f} a testa)')
    saldo_mgr_142 = saldo_manager(stato['risultati'])
    print(f'  saldo manager sulle 142 valutate: {saldo_mgr_142:+.0f} '
          f'({saldo_mgr_142/len(stato["risultati"]):+.1f} a testa)')
    saldo_mgr_170 = saldo_mgr_142 + netto_escluse_tot
    print(f'  saldo manager sulle {n_escluse+len(stato["risultati"])} (142+28): {saldo_mgr_170:+.0f}')

    for ramo in RAMI:
        sb_142 = saldo_bot(stato['risultati'], ramo)
        sb_a = sb_142 + netto_escluse_tot   # scenario: bot le gioca tutte -> prende lo stesso netto del manager
        sb_b = sb_142 + 0.0                 # scenario: bot le salta tutte -> zero
        delta_142 = sb_142 - saldo_mgr_142
        delta_a = sb_a - saldo_mgr_170
        delta_b = sb_b - saldo_mgr_170
        print(f'  ramo {ramo}: delta su 142 = {delta_142:+.0f}  |  '
              f'scenario (a) bot gioca le 28 = {delta_a:+.0f}  |  '
              f'scenario (b) bot le salta = {delta_b:+.0f}  '
              f'{"REGGE (sempre positivo)" if delta_a > 0 and delta_b > 0 else ("SI RIBALTA in almeno uno scenario" if (delta_a>0) != (delta_b>0) else "resta negativo in entrambi")}')


def main():
    stato = costruisci_tutto()
    annota_dimensione_gruppo(stato)
    compito_a()
    compito_b(stato)
    esito_c = compito_c(stato)
    compito_d(stato)

    print('\n' + '=' * 78)
    print('RIEPILOGO PER L\'UTENTE')
    print('=' * 78)
    print(f'placebo stretta: G vero al percentile {esito_c["pct_stretta"]:.1f}  '
          f'(delta reale {esito_c["reale_stretta"]:+.0f})')
    print(f'placebo larga:   G vero al percentile {esito_c["pct_larga"]:.1f}  '
          f'(delta reale {esito_c["reale_larga"]:+.0f})')


if __name__ == '__main__':
    sys.exit(main() or 0)
