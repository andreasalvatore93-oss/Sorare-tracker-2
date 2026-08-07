"""Sez.23 -- backtest a livello di FORMAZIONE sulle 8 GW dei manager reali
(non crowss). Stesso metodo di sez.21 (p12_backtest_formazione_grade.py:
policy A = produzione pura, policy G = produzione+grade riordinamento,
z-score(atteso_cal)+z-score(grade) per gruppo lega/ruolo), MA:

- pool CANDIDATO = proxy walk-backward: tutte le carte distinte (rarita
  limited, non in_season) che quel manager ha schierato in GW con data
  STRETTAMENTE precedente alla GW target (mai guardare avanti). Non e' il
  mazzo vero (che richiederebbe query), e' un sottoinsieme -> il test
  SOTTOSTIMA il guadagno possibile, dichiarato.
- METRO = solo punteggio della formazione (niente rank/premio: non
  abbiamo la lista punteggi degli avversari per 41/42 manager, solo
  crowss ce l'ha in dati_globali/arene_storico.json).
- bootstrap sulle COPPIE (manager, GW target), non sulle arene/giornate.

Split A/B (richiesto dall'utente, da fissare PRIMA di guardare i numeri):
manager ordinati per slug alfabetico, indici pari (0-based) -> gruppo A
(ricerca), indici dispari -> gruppo B (verifica, non si guarda finche' A
non ha una combinazione candidata).

AVVISO: il brief originale parlava di "42 manager". I file
analisi_manager/dati/righe_football-*.json (le 8 GW gia' estratte)
contengono SOLO 10 manager distinti (MANAGER_SMART filtrato da
analizza_gw.py). Uso i 10 realmente presenti, dichiarato qui, non 42.
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
import p12_backtest_formazione_grade as S21  # riusa costruisci/gioca/capitano_atteso/realizzato/bfg
import analizza_gw as AG  # riusa indice_lega()

cache = CACHE.CacheLocale()
random.seed(20260806)

MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
        'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
ROLE_CODE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}
GRADE_NUM = S21.GRADE_NUM
COMP_TO_TIPO = {'Cap 220': ('cap 220', 'ARENA_ALLSTARS_220', 220.0),
                'Cap 260': ('cap 260', 'ARENA_ALLSTARS_260', 260.0)}


def parse_fixture_bounds(fx):
    """'football-1-4-jul-2026' o 'football-31-jul-4-aug-2026' -> (data_inizio, data_fine)."""
    toks = fx.split('-')
    if toks[0] != 'football':
        return None
    toks = toks[1:]
    try:
        year = int(toks[-1])
    except ValueError:
        return None
    toks = toks[:-1]
    month_idxs = [i for i, t in enumerate(toks) if t in MESI]
    if not month_idxs:
        return None
    try:
        start_day = int(toks[0])
        start_month = MESI[toks[month_idxs[0]]]
        end_idx = month_idxs[-1]
        end_day = int(toks[end_idx - 1])
        end_month = MESI[toks[end_idx]]
        return (datetime.date(year, start_month, start_day), datetime.date(year, end_month, end_day))
    except Exception:
        return None


def carica_indice_grade_esteso():
    """Come S21.carica_indice_grade() ma AGGIUNGE storico_grade_backtest_20260806.json
    (raccolta mirata sui 625 slug delle 8 GW manager, priorita' massima di copertura
    su questo campione specifico).

    FIX 07/08/2026 (stesso bug/fix di S21.carica_indice_grade, richiesta
    esplicita utente): idx e' slug -> lista (data,grade_num), non piu' un
    dict a chiave esatta (slug,data) -- il lookup a valle usa
    S21.grade_in_finestra(), che ammette qualunque partita entro
    S21.GRADE_WINDOW_GIORNI giorni prima della fine fixture (le fixture
    durano piu' giorni, la partita vera raramente cade esattamente
    sull'ultimo -- match esatto 3.4% vs finestra 56.6% sugli stessi dati)."""
    idx, date_min = S21.carica_indice_grade()
    path = 'analisi_manager/dati/storico_grade_backtest_20260806.json'
    if os.path.exists(path):
        d = json.load(open(path, encoding='utf-8'))
        for p in d.get('giocatori') or []:
            for s in p.get('playerGameScores') or []:
                proj = s.get('projection') or {}
                gn = GRADE_NUM.get(proj.get('grade'))
                dt = (s.get('anyGame') or {}).get('date')
                slug = p.get('slug')
                if gn is None or not dt or not slug:
                    continue
                idx[slug].append((dt[:10], gn))
                if date_min is None or dt < date_min:
                    date_min = dt
    for slug in idx:
        idx[slug] = sorted(set(idx[slug]))
    return idx, date_min


def reale_in_finestra(slug, d_start, d_end):
    """Score realizzato del giocatore in una partita FINAL/REVIEWING dentro
    [d_start, d_end] (estremi inclusi); None se non trovata (non ha giocato)."""
    for n in cache.gamelog(slug):
        if n.get('scoreStatus') not in ('FINAL', 'REVIEWING'):
            continue
        dt = n.get('anyGame', {}).get('date')
        if not dt:
            continue
        try:
            gdate = datetime.date.fromisoformat(dt[:10])
        except ValueError:
            continue
        if d_start <= gdate <= d_end:
            return n.get('score')
    return None


def main():
    idx_grade, data_min_grade = carica_indice_grade_esteso()
    print(f'indice grade esteso: {len(idx_grade)} coppie (slug,data)')
    lega_di = AG.indice_lega()

    # --- manager realmente presenti (non 42, dichiarato) ---
    mgrs = set()
    for f in glob.glob('analisi_manager/dati/righe_football-*.json'):
        for r in json.load(open(f, encoding='utf-8')):
            mgrs.add(r['manager'])
    mgrs_sorted = sorted(mgrs)
    GRUPPO_A = [m for i, m in enumerate(mgrs_sorted) if i % 2 == 0]
    GRUPPO_B = [m for i, m in enumerate(mgrs_sorted) if i % 2 == 1]
    print(f'manager totali (reali, non 42): {len(mgrs_sorted)}')
    print(f'GRUPPO A (ricerca): {GRUPPO_A}')
    print(f'GRUPPO B (verifica, non guardato ora): {GRUPPO_B}')

    fixtures = sorted({os.path.basename(f)[len('formazioni_'):-len('.json')]
                       for f in glob.glob('analisi_manager/dati/formazioni_football-*.json')})
    bounds = {fx: parse_fixture_bounds(fx) for fx in fixtures}
    print(f'fixture target: {fixtures}')

    manager_giornate = {}   # manager -> {fixture: [formazioni]} (tutte le GW note, non solo le 8)
    for mf in glob.glob('dati_globali/manager_*.json'):
        man = os.path.basename(mf)[len('manager_'):-len('.json')]
        if man not in mgrs_sorted:
            continue
        d = json.load(open(mf, encoding='utf-8'))
        manager_giornate[man] = d.get('giornate') or {}

    righe = []
    scarti = collections.Counter()

    def processa_gruppo(gruppo, nome_gruppo):
        for man in gruppo:
            giornate = manager_giornate.get(man)
            if not giornate:
                scarti['manager senza dati_globali'] += 1
                continue
            fixture_bounds_manager = {fx: parse_fixture_bounds(fx) for fx in giornate}
            for fx in fixtures:
                b_target = bounds.get(fx)
                if b_target is None:
                    scarti['fixture non parsabile'] += 1
                    continue
                fpath = f'analisi_manager/dati/formazioni_{fx}.json'
                if not os.path.exists(fpath):
                    continue
                forms_target = [f for f in json.load(open(fpath, encoding='utf-8'))
                                if f['manager'] == man and f['competizione'] in COMP_TO_TIPO]
                if not forms_target:
                    continue

                # --- pool proxy walk-backward: carte distinte, GW strettamente precedenti ---
                proxy = {}
                for fx2, forms2 in giornate.items():
                    if fx2 == fx:
                        continue
                    b2 = fixture_bounds_manager.get(fx2)
                    if b2 is None or b2[0] >= b_target[0]:
                        continue
                    for f2 in forms2:
                        for c in f2.get('carte') or []:
                            if c.get('rarita') != 'limited' or c.get('in_season'):
                                continue
                            slug = c.get('slug')
                            if not slug:
                                continue
                            proxy[slug] = c  # dedup per slug (ultima occorrenza vista)

                for f in forms_target:
                    # 23-bis: le 5 carte EFFETTIVAMENTE schierate quella GW sono un
                    # fatto osservato (il manager le possedeva con certezza), non
                    # una previsione -- vanno aggiunte al pool per definizione,
                    # nessun look-ahead (non stiamo guardando il loro atteso/reale
                    # futuro, solo il fatto che esistevano nel mazzo quella GW).
                    pool_completo = dict(proxy)
                    for c in f.get('carte') or []:
                        slug = c.get('slug')
                        if slug and slug not in pool_completo:
                            pool_completo[slug] = {'ruolo': c.get('ruolo')}

                    if len(pool_completo) < 15:
                        scarti[f'pool<15 ({nome_gruppo})'] += 1
                        continue

                    tipo, tipo_bfg, l10cap = COMP_TO_TIPO[f['competizione']]
                    d_start, d_end = b_target

                    pool_rows = []
                    ruoli_presenti = collections.Counter()
                    for slug, card in pool_completo.items():
                        ruolo_full = card.get('ruolo')
                        cod = ROLE_CODE.get(ruolo_full)
                        if cod is None:
                            continue
                        fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
                        r = P.score_atteso(cache, slug, ruolo_full, fine)
                        if r is None or r.get('atteso') is None:
                            continue
                        reale = reale_in_finestra(slug, d_start, d_end)
                        lega = lega_di.get(slug) or 'senza_lega'
                        pool_rows.append({
                            'slug': slug, 'codice': cod, 'lega': lega,
                            'squadra': r.get('squadra'), 'opp_slug': r.get('opp_slug'),
                            'atteso_raw': r['atteso'], 'l10': r.get('l10'),
                            'copie': 1, 'reale': reale if reale is not None else 0.0,
                        })
                        ruoli_presenti[cod] += 1
                    if not all(ruoli_presenti[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
                        scarti[f'pool senza tutti i ruoli ({nome_gruppo})'] += 1
                        continue

                    gw = {'pool': pool_rows}
                    for c in pool_rows:
                        c['_cal'] = S21.bfg.calibra(c['atteso_raw'], c['codice'])
                        c['_grade'] = S21.grade_in_finestra(idx_grade, c['slug'], d_end.isoformat()[:10])

                    gruppi = collections.defaultdict(list)
                    for c in pool_rows:
                        gruppi[(c['lega'], c['codice'])].append(c)
                    for (lg, cod), membri in gruppi.items():
                        z_atteso, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
                        grade_presenti = [m['_grade'] for m in membri if m['_grade'] is not None]
                        if len(grade_presenti) >= 2:
                            z_grade_p, _, _ = S21.zscore_gruppo(grade_presenti)
                            it = iter(z_grade_p)
                            for m in membri:
                                m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
                        else:
                            for m in membri:
                                m['_zgrade'] = 0.0
                        for m in membri:
                            m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']

                    slot = {'slug': f'{man}_{fx}_{tipo}', 'tipo': tipo, 'tipo_bfg': tipo_bfg}
                    fa = S21.gioca(gw, [slot], lambda c: c['_cal'], depleta=True)
                    fg = S21.gioca(gw, [slot], lambda c: c['_combinato'], depleta=True)
                    la, lg_ = fa[0], fg[0]
                    if la is None or lg_ is None:
                        scarti[f'knapsack fallito ({nome_gruppo})'] += 1
                        continue

                    ca = S21.capitano_atteso(la)
                    cg = S21.capitano_atteso(lg_)
                    pa = S21.realizzato(la, ca)
                    pg = S21.realizzato(lg_, cg)
                    sa = set(r['slug'] for _x, r, _t in la)
                    sg = set(r['slug'] for _x, r, _t in lg_)
                    n_grade_g = sum(1 for _x, r, _t in lg_ if r.get('_grade') is not None)
                    ruoli_a = collections.Counter(r['role_key'] for _x, r, _t in la)
                    ruoli_g = collections.Counter(r['role_key'] for _x, r, _t in lg_)

                    righe.append({
                        'manager': man, 'gruppo': nome_gruppo, 'fixture': fx, 'tipo': tipo,
                        'n_pool': len(pool_rows), 'A_punti': pa, 'G_punti': pg,
                        'overlap': len(sa & sg), 'identiche': sa == sg,
                        'n_grade_in_G': n_grade_g,
                        'ruoli_A': dict(ruoli_a), 'ruoli_G': dict(ruoli_g),
                    })

    processa_gruppo(GRUPPO_A, 'A')

    print(f'\nscarti: {dict(scarti)}')
    print(f'righe valide (gruppo A): {len(righe)}')
    coppie = sorted(set((r['manager'], r['fixture']) for r in righe))
    print(f'coppie (manager,GW) distinte: {len(coppie)}')
    if not righe:
        print('NESSUNA RIGA VALIDA, mi fermo.')
        return

    print(f'copertura grade nel pool (righe con almeno 1 grade in G): '
          f'{sum(1 for r in righe if r["n_grade_in_G"] > 0)}/{len(righe)}')
    cambiate = sum(1 for r in righe if not r['identiche'])
    print(f'formazioni che cambiano almeno 1 carta: {cambiate}/{len(righe)} '
          f'({100*cambiate/len(righe):.1f}%)')

    dist_overlap = collections.Counter(r['overlap'] for r in righe)
    print('distribuzione overlap A vs G (carte in comune su 5):')
    for k in sorted(dist_overlap):
        print(f'  {k}/5: {dist_overlap[k]} ({100*dist_overlap[k]/len(righe):.1f}%)')

    tot_A = collections.Counter()
    tot_G = collections.Counter()
    for r in righe:
        tot_A.update(r['ruoli_A'])
        tot_G.update(r['ruoli_G'])
    print(f'composizione ruoli A: {dict(tot_A)}')
    print(f'composizione ruoli G: {dict(tot_G)}')

    def media(v):
        v = list(v)
        return sum(v) / len(v) if v else float('nan')

    d_punti = media(r['G_punti'] - r['A_punti'] for r in righe)
    print(f'\ndelta punti medio (G-A), su {len(righe)} righe: {d_punti:+.3f}')
    print(f'  punteggio medio A={media(r["A_punti"] for r in righe):.2f}  '
          f'G={media(r["G_punti"] for r in righe):.2f}')

    # bootstrap sulle COPPIE (manager, GW), non sulle arene
    by_coppia = collections.defaultdict(list)
    for r in righe:
        by_coppia[(r['manager'], r['fixture'])].append(r)
    unita = list(by_coppia.values())
    n = len(unita)
    rnd = random.Random(20260806)
    diffs = []
    for _ in range(4000):
        num, den = 0.0, 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r['G_punti'] - r['A_punti']
                den += 1
        if den:
            diffs.append(num / den)
    diffs.sort()
    lo, hi = diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]
    pos = sum(1 for d in diffs if d > 0) / len(diffs)
    print(f'  bootstrap (coppie manager-GW, n={n}, 4000 resample): '
          f'IC95 [{lo:+.3f}, {hi:+.3f}]  positivo nel {100*pos:.1f}% dei casi')

    with open('analisi_manager/p12_backtest_manager_grade_bis_out.json', 'w', encoding='utf-8') as fh:
        json.dump({'gruppo_a': GRUPPO_A, 'gruppo_b': GRUPPO_B, 'scarti': dict(scarti),
                   'righe': righe, 'delta_punti_medio': d_punti,
                   'bootstrap_IC95': [lo, hi], 'bootstrap_pct_positivo': pos},
                  fh, ensure_ascii=False, indent=1)
    print('\nsalvato analisi_manager/p12_backtest_manager_grade_bis_out.json')


if __name__ == '__main__':
    main()
