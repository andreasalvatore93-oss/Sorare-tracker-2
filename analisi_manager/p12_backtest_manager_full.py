"""Sez.24 -- backtest completo manager reale vs modello (A=produzione,
G=produzione+grade), stessa GW, stesse arene disponibili, pool di carte
allargato a tutte le arene giocate quella settimana (P50/P-tutte).

Unita' di analisi: coppia (manager, GW), sulle 8 GW gia' estratte
(analisi_manager/dati/righe_football-*.json) incrociate con lo storico
completo formazioni in dati_globali/manager_<nome>.json.

--- VERIFICA BONUS (richiesta esplicita, fatta PRIMA di scrivere lo script) ---
Campione: fins49, GW football-31-jul-4-aug-2026, 5 carte di una formazione
Cap 260. Confronto punteggio in dati_globali/manager_fins49.json contro lo
score RAW nella cache game-log locale (stessa partita, stessa data):
  viljami-sinisalo   (non capitano)  punteggio=72.5   cache=72.5   -> uguali
  alistair-johnston  (non capitano)  punteggio=71.28  cache=71.28  -> uguali
  blair-spittal      (non capitano)  punteggio=60.1   cache=60.1   -> uguali
  tuur-rommens       (non capitano)  punteggio=51.68  cache=51.68  -> uguali
  kevin-nisbet       (CAPITANO)      punteggio=91.08  cache=75.9   -> 75.9*1.2=91.08 ESATTO
VERDETTO: 'punteggio' in dati_globali/manager_*.json e' il punteggio RAW del
giocatore, MOLTIPLICATO per 1.2 se e solo se capitano. Nessun bonus_carta/xp/
in-season nel numero. Confermato quanto dichiarato dall'utente: uso diretto,
niente ricalcolo dal game-log per i candidati gia' schierati (piu' preciso
del window-matching di sez.23, zero ambiguita').

--- ARENE NEL CHOICE-SET DEL MODELLO ---
Cap 260, Cap 220, Uncapped: shape/pool_league/L10-cap di produzione
(generatore_formazioni/build_formazione_globale.py), soglia PAREGGIO_ARENA
per decidere se schierare.
Beginner: IDENTICA a Cap 260 tranne i premi (confermato esplicitamente
dall'utente) -- shape, L10 cap e soglia PAREGGIO_ARENA riusano quelli di
Cap 260 (259.5). I premi (diversi) non servono qui: il metro e' solo il
punteggio, non le essenze.
Elite ESCLUSA dal choice-set (richiesta esplicita utente: "troppo rare"),
ma le sue carte/punteggio RESTANO nel pool disponibile e nel totale
'reale' -- il modello semplicemente non puo' scegliere di giocarla.
"""
import os, sys, io, json, glob, random, datetime, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p12_backtest_manager_grade as M

cache = CACHE.CacheLocale()
random.seed(20260806)

ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped'}
# competizione -> (tipo_bfg da riusare per shape/pool/l10cap, ha_soglia_pareggio)
COMP_TO_BUILD = {
    'Cap 260': ('ARENA_ALLSTARS_260', True),
    'Cap 220': ('ARENA_ALLSTARS_220', True),
    'Uncapped': ('ARENA_ALLSTARS_UNCAPPED', True),
    'Beginner': ('ARENA_ALLSTARS_260', True),   # identica a Cap260 tranne i premi (confermato utente): stessa soglia
}
TUTTI_I_TIPI = ('Cap 260', 'Cap 220', 'Uncapped', 'Beginner', 'Elite')


def costruisci_pool(carte_ammesse):
    """P50 e P-tutte: dedup per 'carta' (non slug). In questo dataset
    coincidono SEMPRE perche' nessuno dei 10 manager ha mai giocato
    All Star/Hot Streak/In Season/U23 (verificato: 0 occorrenze su tutta
    la storia nota, 5 sole combinazioni competizione/tipo_arena in repo)."""
    pool = {}
    for c in carte_ammesse:
        cid = c.get('carta')
        if cid and cid not in pool:
            pool[cid] = c
    return pool


def trova_grade_finestra(idx_grade_per_slug, slug, d_start, d_end):
    """Cerca il grade del giocatore in QUALSIASI data dentro la finestra
    della GW (non solo l'ultimo giorno): il grade e' legato alla partita
    VERA di quella carta quella settimana, che puo' cadere in un giorno
    qualunque della finestra, non solo l'ultimo. Se piu' di una data
    combacia (raro, finestra di pochi giorni), prende la piu' vicina alla
    fine (comportamento gia' usato altrove: preferenza al dato piu' fresco)."""
    date_grade = idx_grade_per_slug.get(slug)
    if not date_grade:
        return None
    migliori = [(d, g) for d, g in date_grade.items()
               if d_start.isoformat() <= d <= d_end.isoformat()]
    if not migliori:
        return None
    migliori.sort()
    return migliori[-1][1]


def elabora_coppia(man, gw, giornate_gw, lega_di, idx_grade_per_slug):
    arene_reali = [f for f in giornate_gw if f.get('tipo_arena') in ARENE_AMMESSE_TIPO]
    if not arene_reali:
        return None

    tutte_le_carte = [c for f in arene_reali for c in (f.get('carte') or [])]
    pool50 = costruisci_pool(tutte_le_carte)
    pool_tutte = pool50  # identici in questo dataset, dichiarato sopra

    slots_reali = [f for f in arene_reali if f['competizione'] in COMP_TO_BUILD]
    if not slots_reali:
        return None

    b = M.parse_fixture_bounds(gw)
    if b is None:
        return None
    d_start, d_end = b
    fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
    gw_end_iso = d_end.isoformat()

    pool_rows = []
    for carta_id, c in pool_tutte.items():
        ruolo_full = c.get('ruolo')
        cod = M.ROLE_CODE.get(ruolo_full)
        if cod is None:
            continue
        slug = c.get('slug')
        r = P.score_atteso(cache, slug, ruolo_full, fine)
        if r is None or r.get('atteso') is None:
            continue
        raw = c.get('punteggio')
        if raw is None:
            continue
        if c.get('capitano'):
            raw = raw / 1.2
        lega = lega_di.get(slug) or 'senza_lega'
        pool_rows.append({'slug': slug, 'carta': carta_id, 'codice': cod, 'lega': lega,
                          'squadra': r.get('squadra'), 'opp_slug': r.get('opp_slug'),
                          'atteso_raw': r['atteso'], 'l10': r.get('l10'),
                          'copie': 1, 'reale': raw})
    if len(pool_rows) < 5:
        return None

    for c in pool_rows:
        c['_cal'] = S21.bfg.calibra(c['atteso_raw'], c['codice'])
        c['_grade'] = trova_grade_finestra(idx_grade_per_slug, c['slug'], d_start, d_end)
    gruppi = collections.defaultdict(list)
    for c in pool_rows:
        gruppi[(c['lega'], c['codice'])].append(c)
    for (lg, cod), membri in gruppi.items():
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

    slots = []
    for f in slots_reali:
        tipo_bfg, ha_soglia = COMP_TO_BUILD[f['competizione']]
        ruoli_reali = collections.Counter(M.ROLE_CODE.get(c.get('ruolo')) for c in f.get('carte') or [])
        ruoli_reali.pop(None, None)
        slots.append({'tipo': f['competizione'], 'tipo_bfg': tipo_bfg, 'ha_soglia': ha_soglia,
                      'reale_slugs': [c.get('slug') for c in f.get('carte') or []],
                      'reale_punti': (f.get('piazzamento') or {}).get('punteggio'),
                      'reale_ruoli': dict(ruoli_reali)})

    def gioca_con_soglia(obiettivo_key):
        gw_data = {'pool': pool_rows}
        role_data, pools, card_pool, leghe = S21.costruisci(gw_data, lambda c: c[obiettivo_key])
        orig = S21.bfg.LEAGUES
        S21.bfg.LEAGUES = tuple(leghe)
        out = []
        try:
            for s in slots:
                shape = S21.bfg.FORMATION_SHAPES[s['tipo_bfg']]
                pool_league = S21.bfg.POOL_LEAGUE_BY_TYPE[s['tipo_bfg']]
                l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(s['tipo_bfg'])
                stato = S21.bfg._istantanea_pool(card_pool)
                formazione, errore, _ok, _sp = S21.bfg.build_one_lineup_with_growth(
                    shape, pool_league, role_data, pools, card_pool, l10_cap,
                    apply_stack_guard=False, variance_mode=True,
                    apply_positive_synergy=False, strict_gk_anti_synergy=False)
                if errore or not formazione:
                    S21.bfg._ripristina_pool(card_pool, stato)
                    out.append({'tipo': s['tipo'], 'schierata': False, 'punti': 0.0, 'slugs': []})
                    continue
                cap_row = S21.capitano_atteso(formazione)
                atteso_sum = sum(r['atteso_cal'] for _x, r, _t in formazione) + \
                    0.2 * (cap_row['atteso_cal'] if cap_row else 0.0)
                if s['ha_soglia']:
                    soglia = S21.bfg.PAREGGIO_ARENA.get(s['tipo_bfg'])
                    margine = atteso_sum - soglia if soglia is not None else 1.0
                else:
                    margine = 1.0
                if margine < 0:
                    S21.bfg._ripristina_pool(card_pool, stato)
                    out.append({'tipo': s['tipo'], 'schierata': False, 'punti': 0.0, 'slugs': [], 'margine': margine})
                    continue
                punti = S21.realizzato(formazione, cap_row)
                slugs = [r['slug'] for _x, r, _t in formazione]
                ruoli = dict(collections.Counter(r['role_key'] for _x, r, _t in formazione))
                out.append({'tipo': s['tipo'], 'schierata': True, 'punti': punti, 'slugs': slugs,
                           'margine': margine, 'ruoli': ruoli})
        finally:
            S21.bfg.LEAGUES = orig
        return out

    esito_A = gioca_con_soglia('_cal')
    esito_G = gioca_con_soglia('_combinato')

    reale_per_tipo = collections.defaultdict(float)
    for f in arene_reali:
        reale_per_tipo[f['competizione']] += (f.get('piazzamento') or {}).get('punteggio') or 0.0

    return {
        'manager': man, 'gw': gw,
        'n_pool_P50': len(pool50), 'n_pool_Ptutte': len(pool_tutte),
        'reale_per_tipo': dict(reale_per_tipo),
        'reale_totale_tutte_arene': sum(reale_per_tipo.values()),
        'reale_totale_confrontabile': sum(v for k, v in reale_per_tipo.items() if k in COMP_TO_BUILD),
        'slots': slots, 'esito_A': esito_A, 'esito_G': esito_G,
    }


def main():
    idx_grade, _ = M.carica_indice_grade_esteso()
    idx_grade_per_slug = collections.defaultdict(dict)
    for (slug, data), grade in idx_grade.items():
        idx_grade_per_slug[slug][data] = grade
    lega_di = AG.indice_lega()

    mgrs = set()
    for f in glob.glob('analisi_manager/dati/righe_football-*.json'):
        for r in json.load(open(f, encoding='utf-8')):
            mgrs.add(r['manager'])
    mgrs_sorted = sorted(mgrs)
    GRUPPO_A = [m for i, m in enumerate(mgrs_sorted) if i % 2 == 0]
    GRUPPO_B = [m for i, m in enumerate(mgrs_sorted) if i % 2 == 1]
    print(f'GRUPPO A: {GRUPPO_A}')
    print(f'GRUPPO B (non toccato): {GRUPPO_B}')

    fixtures = sorted({os.path.basename(f)[len('formazioni_'):-len('.json')]
                       for f in glob.glob('analisi_manager/dati/formazioni_football-*.json')})

    def processa(gruppo):
        risultati = []
        for man in gruppo:
            mf = f'dati_globali/manager_{man}.json'
            if not os.path.exists(mf):
                continue
            d = json.load(open(mf, encoding='utf-8'))
            giornate = d.get('giornate') or {}
            for gw in fixtures:
                giornate_gw = giornate.get(gw)
                if not giornate_gw:
                    continue
                r = elabora_coppia(man, gw, giornate_gw, lega_di, idx_grade_per_slug)
                if r:
                    risultati.append(r)
        return risultati

    risultati_A = processa(GRUPPO_A)
    print(f'\ncoppie (manager,GW) valide gruppo A: {len(risultati_A)}')

    # --- report ---
    dist_pool = [r['n_pool_P50'] for r in risultati_A]
    print(f'dimensione pool (P50=P-tutte in questo dataset): min={min(dist_pool)} '
          f'mediana={sorted(dist_pool)[len(dist_pool)//2]} max={max(dist_pool)}')

    tot_reale_conf = sum(r['reale_totale_confrontabile'] for r in risultati_A)
    tot_reale_tutte = sum(r['reale_totale_tutte_arene'] for r in risultati_A)
    tot_A = sum(sum(s['punti'] for s in r['esito_A']) for r in risultati_A)
    tot_G = sum(sum(s['punti'] for s in r['esito_G']) for r in risultati_A)
    print(f'\nPUNTI TOTALI (somma su {len(risultati_A)} coppie):')
    print(f'  reale (tutte le arene incl. Elite): {tot_reale_tutte:.1f}')
    print(f'  reale (solo tipi nel choice-set modello): {tot_reale_conf:.1f}')
    print(f'  A (produzione): {tot_A:.1f}')
    print(f'  G (produzione+grade): {tot_G:.1f}')

    print('\nPER TIPO ARENA:')
    for tipo in TUTTI_I_TIPI:
        reale_tipo = sum(r['reale_per_tipo'].get(tipo, 0.0) for r in risultati_A)
        n_reale = sum(1 for r in risultati_A for f_tipo, v in r['reale_per_tipo'].items() if f_tipo == tipo)
        if tipo in COMP_TO_BUILD:
            a_tipo = sum(s['punti'] for r in risultati_A for s in r['esito_A'] if s['tipo'] == tipo)
            g_tipo = sum(s['punti'] for r in risultati_A for s in r['esito_G'] if s['tipo'] == tipo)
            n_a = sum(1 for r in risultati_A for s in r['esito_A'] if s['tipo'] == tipo and s['schierata'])
            n_g = sum(1 for r in risultati_A for s in r['esito_G'] if s['tipo'] == tipo and s['schierata'])
            print(f'  {tipo:10s} reale={reale_tipo:8.1f}(n={n_reale:3d})  '
                  f'A={a_tipo:8.1f}(schierate={n_a:3d})  G={g_tipo:8.1f}(schierate={n_g:3d})')
        else:
            print(f'  {tipo:10s} reale={reale_tipo:8.1f}(n={n_reale:3d})  A=N/A (fuori choice-set)  G=N/A')

    n_slot_reali = sum(len(r['slots']) for r in risultati_A)
    n_a_schierate = sum(1 for r in risultati_A for s in r['esito_A'] if s['schierata'])
    n_g_schierate = sum(1 for r in risultati_A for s in r['esito_G'] if s['schierata'])
    print(f'\nQUANTE ARENE SCHIERA (su {n_slot_reali} slot reali disponibili nel choice-set):')
    print(f'  A: {n_a_schierate}/{n_slot_reali}  totale grezzo={tot_A:.1f}  '
          f'media/arena schierata={tot_A/n_a_schierate if n_a_schierate else float("nan"):.2f}')
    print(f'  G: {n_g_schierate}/{n_slot_reali}  totale grezzo={tot_G:.1f}  '
          f'media/arena schierata={tot_G/n_g_schierate if n_g_schierate else float("nan"):.2f}')
    tot_reale_slot = sum(s['reale_punti'] or 0.0 for r in risultati_A for s in r['slots'])
    print(f'  reale: {n_slot_reali}/{n_slot_reali}  totale grezzo={tot_reale_slot:.1f}  '
          f'media/arena={tot_reale_slot/n_slot_reali if n_slot_reali else float("nan"):.2f}')

    def cambia_stat(esito_key):
        cambiate, confrontabili = 0, 0
        ruoli_reale, ruoli_pol = collections.Counter(), collections.Counter()
        for r in risultati_A:
            for s, e in zip(r['slots'], r[esito_key]):
                confrontabili += 1
                real_set = set(s['reale_slugs'])
                if not e['schierata']:
                    cambiate += 1
                    continue
                pol_set = set(e['slugs'])
                if pol_set != real_set:
                    cambiate += 1
        return cambiate, confrontabili

    ca, na = cambia_stat('esito_A')
    cg, ng = cambia_stat('esito_G')
    print(f'\nFORMAZIONI CHE CAMBIANO >=1 CARTA vs reale (su {na} slot):')
    print(f'  A: {ca}/{na} ({100*ca/na:.1f}%)')
    print(f'  G: {cg}/{ng} ({100*cg/ng:.1f}%)')

    ruoli_reale, ruoli_A, ruoli_G = collections.Counter(), collections.Counter(), collections.Counter()
    for r in risultati_A:
        for s in r['slots']:
            ruoli_reale.update(s.get('reale_ruoli') or {})
        for e in r['esito_A']:
            if e['schierata']:
                ruoli_A.update(e.get('ruoli') or {})
        for e in r['esito_G']:
            if e['schierata']:
                ruoli_G.update(e.get('ruoli') or {})
    print(f'\nCOMPOSIZIONE PER RUOLO (su tutte le formazioni schierate, extra_roles inclusi):')
    print(f'  reale: {dict(ruoli_reale)}')
    print(f'  A:     {dict(ruoli_A)}')
    print(f'  G:     {dict(ruoli_G)}')

    by_coppia = risultati_A
    n = len(by_coppia)
    rnd = random.Random(20260806)
    diffs = []
    for _ in range(4000):
        num, den = 0.0, 0
        for _ in range(n):
            r = by_coppia[rnd.randrange(n)]
            num += sum(s['punti'] for s in r['esito_G']) - sum(s['punti'] for s in r['esito_A'])
            den += 1
        if den:
            diffs.append(num / den)
    diffs.sort()
    d_medio = (tot_G - tot_A) / n if n else float('nan')
    lo, hi = diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]
    pos = sum(1 for d in diffs if d > 0) / len(diffs)
    print(f'\ndelta G-A medio per coppia: {d_medio:+.3f}  bootstrap (n={n} coppie, 4000): '
          f'IC95 [{lo:+.3f},{hi:+.3f}]  positivo {100*pos:.1f}%')

    with open('analisi_manager/p12_backtest_manager_full_out.json', 'w', encoding='utf-8') as fh:
        json.dump({'gruppo_a': GRUPPO_A, 'gruppo_b': GRUPPO_B, 'risultati_A': risultati_A,
                   'delta_medio': d_medio, 'IC95': [lo, hi], 'pct_positivo': pos},
                  fh, ensure_ascii=False, indent=1)
    print('\nsalvato analisi_manager/p12_backtest_manager_full_out.json')


if __name__ == '__main__':
    main()
