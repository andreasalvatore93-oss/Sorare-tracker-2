"""Brief A -- quanto vale davvero il grade sul portiere
(docs/handoff/BRIEF_SONNET_A_VALORE_GRADE_2026-08-06.txt).
Zero query API: dati gia' in repo (analisi_manager/p12_r5_gk_ampio.json) +
il backtest di produzione locale (backtest_arene_previsioni, CacheLocale,
nessuna chiamata di rete).
"""
import os, sys, io, json, random, datetime, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import backtest_arene_cache as CACHE
import backtest_arene_previsioni as prev

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
random.seed(20260806)

cache = CACHE.CacheLocale()


def _dt(iso):
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)


def load_players(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    players = []
    for entry in data:
        slug = entry.get('slug')
        rows = []
        for s in entry.get('scores') or []:
            date = ((s.get('anyGame') or {}).get('date')) or ''
            proj = s.get('projection') or {}
            grade = proj.get('grade')
            score = s.get('score')
            stats = s.get('anyPlayerGameStats') or {}
            odds = (stats.get('footballPlayingStatusOdds') or {})
            starter_odds = odds.get('starterOddsBasisPoints')
            mins = stats.get('minsPlayed')
            if not date or score is None:
                continue
            rows.append({'date': date, 'grade': grade, 'score': score,
                         'starter_odds': starter_odds, 'mins': mins})
        # dedup + ordina ascendente (stesso metodo di S4)
        by_date = {}
        dup = set()
        for r in rows:
            if r['date'] in by_date:
                dup.add(r['date'])
            else:
                by_date[r['date']] = r
        rows = [r for r in rows if r['date'] not in dup]
        rows.sort(key=lambda r: r['date'])
        players.append({'slug': slug, 'rows': rows})
    return players


def build_rows_con_l10(players):
    """Per ogni riga con mins>0 (filtro S4-bis 'k'), calcola L10 con le sole
    partite PRECEDENTI (min 3 richieste, finestra fino a 10), coerente con R6.
    Ritorna lista di dict con tutti i campi utili per V0/V2/V3/V4."""
    out = []
    n_scartate_minzero = 0
    n_scartate_l10 = 0
    n_scartate_grade_odds = 0
    for p in players:
        rows = p['rows']
        for i, r in enumerate(rows):
            if not (r.get('mins') or 0) > 0:
                n_scartate_minzero += 1
                continue
            precedenti = [rr['score'] for rr in rows[:i]]
            if len(precedenti) < 3:
                n_scartate_l10 += 1
                continue
            ultimi = precedenti[-10:]
            l10 = sum(ultimi) / len(ultimi)
            grade_num = GRADE_NUM.get(r.get('grade'))
            starter_odds = r.get('starter_odds')
            if grade_num is None or starter_odds is None:
                n_scartate_grade_odds += 1
                continue
            out.append({'slug': p['slug'], 'date': r['date'], 'score': r['score'],
                        'grade_num': grade_num, 'starter_odds': starter_odds, 'l10': l10})
    return out, {'scartate_minzero': n_scartate_minzero, 'scartate_l10_insufficiente': n_scartate_l10,
                 'scartate_grade_odds_mancanti': n_scartate_grade_odds}


def corr(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def bootstrap_diff(rows, field_a, field_b, n_boot=1000):
    by_player = collections.defaultdict(list)
    for r in rows:
        by_player[r['slug']].append(r)
    slugs = list(by_player.keys())
    diffs = []
    corrs_a = []
    for _ in range(n_boot):
        sample_slugs = [random.choice(slugs) for _ in slugs]
        sample_rows = [r for s in sample_slugs for r in by_player[s]]
        ca = corr([r[field_a] for r in sample_rows], [r['score'] for r in sample_rows])
        cb = corr([r[field_b] for r in sample_rows], [r['score'] for r in sample_rows]) if field_b else None
        if ca is None:
            continue
        corrs_a.append(ca)
        if field_b:
            if cb is None:
                continue
            diffs.append(ca - cb)
    result = {'n_boot': len(corrs_a), 'n_giocatori': len(slugs)}
    if field_b:
        pos = sum(1 for d in diffs if d > 0) / len(diffs) if diffs else None
        result['diff_pct_positivo'] = pos
        result['diff_range'] = [min(diffs), max(diffs)] if diffs else None
    pos_a = sum(1 for c in corrs_a if c > 0) / len(corrs_a) if corrs_a else None
    result['corr_a_pct_positivo'] = pos_a
    result['corr_a_range'] = [min(corrs_a), max(corrs_a)] if corrs_a else None
    return result


# ---------------------------------------------------------------- V0 -------
def run_v0(rows):
    A_grade = corr([r['grade_num'] for r in rows], [r['score'] for r in rows])
    A_odds = corr([r['starter_odds'] for r in rows], [r['score'] for r in rows])
    A_l10 = corr([r['l10'] for r in rows], [r['score'] for r in rows])
    boot_vs_odds = bootstrap_diff(rows, 'grade_num', 'starter_odds')
    boot_vs_l10 = bootstrap_diff(rows, 'grade_num', 'l10')
    boot_solo = bootstrap_diff(rows, 'grade_num', None)
    out = {
        'n_righe': len(rows), 'n_giocatori': len(set(r['slug'] for r in rows)),
        'corr_grade': A_grade, 'corr_starter_odds': A_odds, 'corr_l10': A_l10,
        'bootstrap_grade_meno_odds': boot_vs_odds,
        'bootstrap_grade_meno_l10': boot_vs_l10,
        'bootstrap_grade_solo': boot_solo,
    }
    print('--- V0 ---')
    print(f'  n_righe={len(rows)} n_giocatori={out["n_giocatori"]}')
    print(f'  corr(grade)={A_grade}  corr(starter_odds)={A_odds}  corr(L10)={A_l10}')
    print(f'  bootstrap grade-odds: {boot_vs_odds["diff_pct_positivo"]}')
    print(f'  bootstrap grade-L10:  {boot_vs_l10["diff_pct_positivo"]}')
    print(f'  bootstrap grade>0:    {boot_solo["corr_a_pct_positivo"]}')
    return out


# ---------------------------------------------------------------- V2 -------
_ctx_cache = {}


def atteso_produzione(slug, date_iso):
    key = (slug, date_iso[:10])
    if key in _ctx_cache:
        return _ctx_cache[key]
    fd = _dt(date_iso)
    try:
        ctx = prev.contesto(cache, slug, 'Goalkeeper', fd)
    except Exception:
        ctx = None
    if ctx is None:
        _ctx_cache[key] = None
        return None
    # verifica che la partita-bersaglio del contesto sia la stessa (entro 2gg)
    cutoff = ctx.get('cutoff')
    if cutoff is None or abs((cutoff - fd).days) > 2:
        _ctx_cache[key] = None
        return None
    try:
        atteso = prev.calcola(ctx)
    except Exception:
        atteso = None
    _ctx_cache[key] = atteso
    return atteso


def run_v2(rows):
    rows_v2 = []
    n_non_disponibile = 0
    for r in rows:
        atteso = atteso_produzione(r['slug'], r['date'])
        if atteso is None:
            n_non_disponibile += 1
            continue
        rows_v2.append(dict(r, atteso=atteso))
    if not rows_v2:
        print('--- V2: FERMO, 0 righe con score_atteso di produzione disponibile ---')
        return None, rows_v2
    A_atteso = corr([r['atteso'] for r in rows_v2], [r['score'] for r in rows_v2])
    A_grade_stesse = corr([r['grade_num'] for r in rows_v2], [r['score'] for r in rows_v2])
    boot = bootstrap_diff(rows_v2, 'grade_num', 'atteso')
    out = {
        'n_righe': len(rows_v2), 'n_giocatori': len(set(r['slug'] for r in rows_v2)),
        'n_scartate_atteso_non_disponibile': n_non_disponibile,
        'corr_atteso_produzione': A_atteso,
        'corr_grade_sulle_stesse_righe': A_grade_stesse,
        'bootstrap_grade_meno_atteso': boot,
    }
    print('--- V2 ---')
    print(f'  n_righe={len(rows_v2)} n_giocatori={out["n_giocatori"]} scartate(no atteso)={n_non_disponibile}')
    print(f'  corr(score_atteso produzione)={A_atteso}  corr(grade, stesse righe)={A_grade_stesse}')
    print(f'  bootstrap grade-atteso: {boot["diff_pct_positivo"]}')
    return out, rows_v2


# ---------------------------------------------------------------- V3 -------
def run_v3(rows_v2):
    """Raggruppa per GIORNATA = stessa data (giorno) di partita fra piu'
    portieri diversi. Richiede almeno 3 portieri disponibili per giornata."""
    by_day = collections.defaultdict(list)
    for r in rows_v2:
        by_day[r['date'][:10]].append(r)
    giornate = []
    scartate_pochi = 0
    for day, rr in by_day.items():
        # un portiere puo' comparire una sola volta per giornata: dedup su slug
        by_slug = {}
        for r in rr:
            by_slug.setdefault(r['slug'], r)
        rr = list(by_slug.values())
        if len(rr) < 3:
            scartate_pochi += 1
            continue
        giornate.append((day, rr))

    def punti_strategia(rr, key):
        best = max(rr, key=lambda r: r[key])
        return best['score']

    righe_giornate = []
    for day, rr in giornate:
        p_grade = punti_strategia(rr, 'grade_num')
        p_atteso = punti_strategia(rr, 'atteso')
        p_l10 = punti_strategia(rr, 'l10')
        # "a caso" = VALORE ATTESO di un sorteggio uniforme = media del pool
        # disponibile quella giornata (non un singolo sorteggio, troppo
        # rumoroso: un solo draw per giornata non stima l'atteso, lo simula
        # male). Il numero giusto per il confronto e' la media, che e' anche
        # il valore che si ottiene mediando infiniti sorteggi.
        casuale = sum(r['score'] for r in rr) / len(rr)
        righe_giornate.append({'day': day, 'n_disponibili': len(rr),
                               'grade': p_grade, 'atteso': p_atteso, 'l10': p_l10,
                               'casuale': casuale, 'media_pool': casuale})

    def mae(rr_g, key):
        # MAE della strategia "scelgo il migliore secondo key" rispetto al
        # MASSIMO REALE disponibile quel giorno (errore di selezione)
        errs = []
        for day, rr in giornate:
            best_key = max(rr, key=lambda r: r[key])
            best_real = max(r['score'] for r in rr)
            errs.append(abs(best_real - best_key['score']))
        return sum(errs) / len(errs) if errs else None

    def media(campo):
        vals = [r[campo] for r in righe_giornate]
        return sum(vals) / len(vals) if vals else None

    def boot_giornate(campo_a, campo_b, n_boot=1000):
        n = len(righe_giornate)
        if n < 2:
            return None
        diffs = []
        for _ in range(n_boot):
            sample = [righe_giornate[random.randrange(n)] for _ in range(n)]
            da = sum(r[campo_a] for r in sample) / n
            db = sum(r[campo_b] for r in sample) / n
            diffs.append(da - db)
        diffs.sort()
        pos = sum(1 for d in diffs if d > 0) / len(diffs)
        return {'media_diff': sum(diffs) / len(diffs), 'pct_positivo': pos,
               'IC95': [diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]]}

    out = {
        'n_giornate': len(giornate), 'n_giornate_scartate_pochi_portieri': scartate_pochi,
        'punti_medi': {k: media(k) for k in ('grade', 'atteso', 'l10', 'casuale', 'media_pool')},
        'MAE_selezione': {'grade': mae(giornate, 'grade_num'), 'atteso': mae(giornate, 'atteso'),
                          'l10': mae(giornate, 'l10')},
        'boot_grade_meno_casuale': boot_giornate('grade', 'casuale'),
        'boot_atteso_meno_casuale': boot_giornate('atteso', 'casuale'),
        'boot_grade_meno_atteso': boot_giornate('grade', 'atteso'),
        'boot_grade_meno_l10': boot_giornate('grade', 'l10'),
    }
    print('--- V3 ---')
    print(f'  n_giornate={len(giornate)} scartate(pochi portieri)={scartate_pochi}')
    print('  punti medi:', out['punti_medi'])
    print('  MAE selezione:', out['MAE_selezione'])
    print('  boot grade-casuale:', out['boot_grade_meno_casuale'])
    print('  boot atteso-casuale:', out['boot_atteso_meno_casuale'])
    print('  boot grade-atteso:', out['boot_grade_meno_atteso'])
    return out


# ---------------------------------------------------------------- V4 -------
def ols(y, X):
    """OLS manuale via equazioni normali. X: lista di righe [1, x1, x2, ...]."""
    n = len(y)
    k = len(X[0])
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    # Gauss-Jordan
    M = [row[:] + [Xty[idx]] for idx, row in enumerate(XtX)]
    for col in range(k):
        piv = max(range(col, k), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        if abs(M[col][col]) < 1e-12:
            return None
        pivval = M[col][col]
        M[col] = [v / pivval for v in M[col]]
        for r in range(k):
            if r != col:
                factor = M[r][col]
                M[r] = [M[r][c2] - factor * M[col][c2] for c2 in range(k + 1)]
    beta = [M[i][k] for i in range(k)]
    y_hat = [sum(beta[j] * X[i][j] for j in range(k)) for i in range(n)]
    my = sum(y) / n
    ss_tot = sum((yi - my) ** 2 for yi in y)
    ss_res = sum((y[i] - y_hat[i]) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    return {'beta': beta, 'r2': r2}


def run_v4(rows):
    y = [r['score'] for r in rows]
    X_base = [[1.0, r['starter_odds'], r['l10']] for r in rows]
    X_ext = [[1.0, r['starter_odds'], r['l10'], r['grade_num']] for r in rows]
    base = ols(y, X_base)
    ext = ols(y, X_ext)
    corr_grade_l10 = corr([r['grade_num'] for r in rows], [r['l10'] for r in rows])
    out = {
        'n_righe': len(rows), 'n_giocatori': len(set(r['slug'] for r in rows)),
        'R2_base_odds_l10': base['r2'] if base else None,
        'beta_base': base['beta'] if base else None,
        'R2_esteso_odds_l10_grade': ext['r2'] if ext else None,
        'beta_esteso': ext['beta'] if ext else None,
        'delta_R2': (ext['r2'] - base['r2']) if (base and ext and base['r2'] is not None and ext['r2'] is not None) else None,
        'corr_grade_l10': corr_grade_l10,
    }
    print('--- V4 ---')
    print(f'  n_righe={len(rows)} n_giocatori={out["n_giocatori"]}')
    print(f'  R2 base (odds+L10)={out["R2_base_odds_l10"]}  R2 esteso (+grade)={out["R2_esteso_odds_l10_grade"]}')
    print(f'  delta R2={out["delta_R2"]}  corr(grade,L10)={corr_grade_l10}')
    print(f'  beta esteso={out["beta_esteso"]}')
    return out


def main():
    players = load_players('analisi_manager/p12_r5_gk_ampio.json')
    rows, scarti = build_rows_con_l10(players)
    print('--- COSTRUZIONE CAMPIONE ---')
    print(f'  giocatori totali: {len(players)}  righe utilizzabili (grade+odds+L10, min>0): {len(rows)}')
    print(f'  scarti: {scarti}')

    v0 = run_v0(rows)
    v2, rows_v2 = run_v2(rows)
    v3 = run_v3(rows_v2) if rows_v2 else None
    v4 = run_v4(rows)

    result = {
        'campione': {'n_giocatori_totali': len(players), 'n_righe_utilizzabili': len(rows), 'scarti': scarti},
        'V0': v0, 'V2': v2, 'V3': v3, 'V4': v4,
    }
    with open('analisi_manager/p12_briefA_out.json', 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
