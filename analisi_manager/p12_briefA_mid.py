"""Estensione Brief A al Midfielder (chat 06/08 ~22:15 Roma), su richiesta
utente. Zero query: dati da analisi_manager/dati/storico_grade_Midfielder_
20260806.json (Haiku, gia' in repo) + backtest di produzione locale
(backtest_arene_previsioni + backtest_arene_cache.CacheLocale, zero rete).

1) V2 ripetuto su MID: score_atteso walk-forward vs grade, stesse righe.
2) Test decisivo: giornate, atteso-solo vs atteso+grade combinati (z-score
   sommati, combinazione dichiarata, nessun peso tarato).
3) V4 FUORI CAMPIONE: split per giocatore (mai per riga), delta R2 medio su
   ripetizioni.
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


def bootstrap_diff_by_player(rows, field_a, field_b, n_boot=1000):
    by_player = collections.defaultdict(list)
    for r in rows:
        by_player[r['slug']].append(r)
    slugs = list(by_player.keys())
    diffs, corrs_a = [], []
    for _ in range(n_boot):
        sample_slugs = [random.choice(slugs) for _ in slugs]
        sample_rows = [r for s in sample_slugs for r in by_player[s]]
        ca = corr([r[field_a] for r in sample_rows], [r['score'] for r in sample_rows])
        if ca is None:
            continue
        corrs_a.append(ca)
        if field_b:
            cb = corr([r[field_b] for r in sample_rows], [r['score'] for r in sample_rows])
            if cb is None:
                continue
            diffs.append(ca - cb)
    out = {'n_boot': len(corrs_a), 'n_giocatori': len(slugs)}
    if corrs_a:
        out['corr_a_pct_positivo'] = sum(1 for c in corrs_a if c > 0) / len(corrs_a)
    if field_b and diffs:
        out['diff_pct_positivo'] = sum(1 for d in diffs if d > 0) / len(diffs)
        out['diff_media'] = sum(diffs) / len(diffs)
    return out


# ---------------------------------------------------------- caricamento ----
def load_mid(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    by_slug = collections.defaultdict(list)
    for r in data:
        slug = r.get('slug')
        date = r.get('game_date') or ''
        if not slug or not date:
            continue
        by_slug[slug].append({
            'date': date, 'grade': r.get('grade'), 'score': r.get('score_realizzato'),
            'starter_odds': r.get('starter_odds_bp'), 'scoreStatus': r.get('scoreStatus'),
        })
    players = []
    n_dup = 0
    for slug, rows in by_slug.items():
        by_date = {}
        dup = set()
        for r in rows:
            if r['date'] in by_date:
                dup.add(r['date'])
            else:
                by_date[r['date']] = r
        rows2 = [r for r in rows if r['date'] not in dup]
        n_dup += len(rows) - len(rows2)
        rows2.sort(key=lambda r: r['date'])
        players.append({'slug': slug, 'rows': rows2})
    return players, n_dup


def build_rows(players):
    """Righe con scoreStatus FINAL (proxy min>0, metodo sez.14), grade e
    starter_odds presenti, L10 (>=3 partite FINAL precedenti, fino a 10)."""
    out = []
    scarti = {'non_final': 0, 'l10_insufficiente': 0, 'grade_odds_mancanti': 0, 'score_nullo': 0}
    for p in players:
        rows = p['rows']
        final_scores_precedenti = []
        for r in rows:
            is_final = r.get('scoreStatus') == 'FINAL'
            if is_final and r.get('score') is None:
                scarti['score_nullo'] += 1
                is_final = False
            if not is_final:
                continue
            precedenti = final_scores_precedenti[-10:]
            if len(precedenti) < 3:
                scarti['l10_insufficiente'] += 1
            else:
                grade_num = GRADE_NUM.get(r.get('grade'))
                so = r.get('starter_odds')
                if grade_num is None or so is None:
                    scarti['grade_odds_mancanti'] += 1
                else:
                    l10 = sum(precedenti) / len(precedenti)
                    out.append({'slug': p['slug'], 'date': r['date'], 'score': r['score'],
                               'grade_num': grade_num, 'starter_odds': so, 'l10': l10})
            final_scores_precedenti.append(r['score'])
        # righe non-FINAL scartate a monte (DID_NOT_PLAY/REVIEWING/senza status)
    n_non_final = sum(1 for p in players for r in p['rows'] if r.get('scoreStatus') != 'FINAL')
    scarti['non_final'] = n_non_final
    return out, scarti


_ctx_cache = {}


def atteso_produzione(slug, date_iso, ruolo='Midfielder'):
    key = (slug, date_iso[:10])
    if key in _ctx_cache:
        return _ctx_cache[key]
    fd = _dt(date_iso)
    try:
        ctx = prev.contesto(cache, slug, ruolo, fd)
    except Exception:
        ctx = None
    if ctx is None:
        _ctx_cache[key] = None
        return None
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


def run_v2(rows, ruolo='Midfielder'):
    rows_v2 = []
    n_non_disp = 0
    for r in rows:
        atteso = atteso_produzione(r['slug'], r['date'], ruolo=ruolo)
        if atteso is None:
            n_non_disp += 1
            continue
        rows_v2.append(dict(r, atteso=atteso))
    if not rows_v2:
        print('--- V2 MID: FERMO, 0 righe con score_atteso disponibile ---')
        return None, []
    A_atteso = corr([r['atteso'] for r in rows_v2], [r['score'] for r in rows_v2])
    A_grade = corr([r['grade_num'] for r in rows_v2], [r['score'] for r in rows_v2])
    boot = bootstrap_diff_by_player(rows_v2, 'grade_num', 'atteso')
    out = {'n_righe': len(rows_v2), 'n_giocatori': len(set(r['slug'] for r in rows_v2)),
          'n_scartate_atteso_non_disponibile': n_non_disp,
          'corr_atteso_produzione': A_atteso, 'corr_grade_stesse_righe': A_grade,
          'bootstrap_grade_meno_atteso': boot}
    print('--- V2 MID ---')
    print(f'  n_righe={len(rows_v2)} n_giocatori={out["n_giocatori"]} scartate(no atteso)={n_non_disp}')
    print(f'  corr(atteso)={A_atteso}  corr(grade)={A_grade}  bootstrap grade-atteso: {boot.get("diff_pct_positivo")}')
    return out, rows_v2


def zscore(vals):
    n = len(vals)
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    if sd == 0:
        return [0.0] * n
    return [(v - m) / sd for v in vals]


def run_test2(rows_v2):
    by_day = collections.defaultdict(list)
    for r in rows_v2:
        by_day[r['date'][:10]].append(r)
    giornate = []
    scartate_pochi = 0
    for day, rr in by_day.items():
        by_slug = {}
        for r in rr:
            by_slug.setdefault(r['slug'], r)
        rr = list(by_slug.values())
        if len(rr) < 3:
            scartate_pochi += 1
            continue
        giornate.append((day, rr))

    righe_giornate = []
    for day, rr in giornate:
        z_atteso = zscore([r['atteso'] for r in rr])
        z_grade = zscore([r['grade_num'] for r in rr])
        combinato = [a + g for a, g in zip(z_atteso, z_grade)]
        idx_atteso = max(range(len(rr)), key=lambda i: rr[i]['atteso'])
        idx_comb = max(range(len(rr)), key=lambda i: combinato[i])
        idx_grade = max(range(len(rr)), key=lambda i: rr[i]['grade_num'])
        media_pool = sum(r['score'] for r in rr) / len(rr)
        righe_giornate.append({'day': day, 'n': len(rr),
                               'atteso_solo': rr[idx_atteso]['score'],
                               'combinato': rr[idx_comb]['score'],
                               'grade_solo': rr[idx_grade]['score'],
                               'media_pool': media_pool})

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
        'n_giornate': len(giornate), 'n_scartate_pochi': scartate_pochi,
        'punti_medi': {
            'atteso_solo': sum(r['atteso_solo'] for r in righe_giornate) / len(righe_giornate) if righe_giornate else None,
            'combinato': sum(r['combinato'] for r in righe_giornate) / len(righe_giornate) if righe_giornate else None,
            'grade_solo': sum(r['grade_solo'] for r in righe_giornate) / len(righe_giornate) if righe_giornate else None,
            'media_pool': sum(r['media_pool'] for r in righe_giornate) / len(righe_giornate) if righe_giornate else None,
        },
        'boot_combinato_meno_atteso': boot_giornate('combinato', 'atteso_solo'),
        'boot_combinato_meno_grade': boot_giornate('combinato', 'grade_solo'),
        'boot_grade_meno_atteso': boot_giornate('grade_solo', 'atteso_solo'),
        'boot_atteso_meno_pool': boot_giornate('atteso_solo', 'media_pool'),
    }
    print('--- TEST 2 (decisivo) ---')
    print(f'  n_giornate={len(giornate)} scartate(pochi)={scartate_pochi}')
    print('  punti medi:', out['punti_medi'])
    print('  boot combinato-atteso:', out['boot_combinato_meno_atteso'])
    print('  boot combinato-grade_solo:', out['boot_combinato_meno_grade'])
    print('  boot grade_solo-atteso:', out['boot_grade_meno_atteso'])
    return out


# --------------------------------------------------------------- V4 OOS ----
def ols(y, X):
    n = len(y)
    k = len(X[0])
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
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
    return [M[i][k] for i in range(k)]


def r2_out_of_sample(beta, y_test, X_test):
    y_hat = [sum(beta[j] * X_test[i][j] for j in range(len(beta))) for i in range(len(y_test))]
    my = sum(y_test) / len(y_test)
    ss_tot = sum((y - my) ** 2 for y in y_test)
    ss_res = sum((y_test[i] - y_hat[i]) ** 2 for i in range(len(y_test)))
    if ss_tot == 0:
        return None
    return 1 - ss_res / ss_tot


def run_v4_oos(rows, n_rep=20):
    slugs = sorted(set(r['slug'] for r in rows))
    rnd = random.Random(20260806)
    deltas_r2 = []
    base_r2s, ext_r2s = [], []
    for rep in range(n_rep):
        shuffled = slugs[:]
        rnd.shuffle(shuffled)
        cut = int(len(shuffled) * 0.8)
        train_slugs = set(shuffled[:cut])
        test_slugs = set(shuffled[cut:])
        train = [r for r in rows if r['slug'] in train_slugs]
        test = [r for r in rows if r['slug'] in test_slugs]
        if len(train) < 10 or len(test) < 10:
            continue
        y_tr = [r['score'] for r in train]
        Xb_tr = [[1.0, r['starter_odds'], r['l10']] for r in train]
        Xe_tr = [[1.0, r['starter_odds'], r['l10'], r['grade_num']] for r in train]
        beta_b = ols(y_tr, Xb_tr)
        beta_e = ols(y_tr, Xe_tr)
        if beta_b is None or beta_e is None:
            continue
        y_te = [r['score'] for r in test]
        Xb_te = [[1.0, r['starter_odds'], r['l10']] for r in test]
        Xe_te = [[1.0, r['starter_odds'], r['l10'], r['grade_num']] for r in test]
        r2b = r2_out_of_sample(beta_b, y_te, Xb_te)
        r2e = r2_out_of_sample(beta_e, y_te, Xe_te)
        if r2b is None or r2e is None:
            continue
        base_r2s.append(r2b)
        ext_r2s.append(r2e)
        deltas_r2.append(r2e - r2b)
    out = {
        'n_ripetizioni_valide': len(deltas_r2), 'n_giocatori_totali': len(slugs),
        'R2_base_medio_oos': sum(base_r2s) / len(base_r2s) if base_r2s else None,
        'R2_esteso_medio_oos': sum(ext_r2s) / len(ext_r2s) if ext_r2s else None,
        'delta_R2_medio_oos': sum(deltas_r2) / len(deltas_r2) if deltas_r2 else None,
        'delta_R2_pct_positivo': sum(1 for d in deltas_r2 if d > 0) / len(deltas_r2) if deltas_r2 else None,
        'delta_R2_range': [min(deltas_r2), max(deltas_r2)] if deltas_r2 else None,
    }
    print('--- V4 FUORI CAMPIONE (split per giocatore, 80/20, 20 ripetizioni) ---')
    print(f'  ripetizioni valide={out["n_ripetizioni_valide"]}/{n_rep}')
    print(f'  R2 base OOS medio={out["R2_base_medio_oos"]}  R2 esteso OOS medio={out["R2_esteso_medio_oos"]}')
    print(f'  delta R2 medio OOS={out["delta_R2_medio_oos"]}  pct positivo={out["delta_R2_pct_positivo"]}')
    return out


def esegui_ruolo(ruolo, path_dati, path_out):
    players, n_dup = load_mid(path_dati)
    rows, scarti = build_rows(players)
    print(f'--- COSTRUZIONE CAMPIONE {ruolo.upper()} ---')
    print(f'  giocatori totali: {len(players)}  righe utilizzabili: {len(rows)}  dup scartate: {n_dup}')
    print(f'  scarti: {scarti}')

    v2, rows_v2 = run_v2(rows, ruolo=ruolo)
    test2 = run_test2(rows_v2) if rows_v2 else None
    v4 = run_v4_oos(rows)

    A_grade_all = corr([r['grade_num'] for r in rows], [r['score'] for r in rows])
    A_odds_all = corr([r['starter_odds'] for r in rows], [r['score'] for r in rows])
    A_l10_all = corr([r['l10'] for r in rows], [r['score'] for r in rows])
    print(f'--- V0 riferimento {ruolo} (tutto il campione, in-sample) ---')
    print(f'  corr(grade)={A_grade_all}  corr(odds)={A_odds_all}  corr(L10)={A_l10_all}')

    result = {
        'ruolo': ruolo,
        'campione': {'n_giocatori': len(players), 'n_righe': len(rows), 'dup_scartate': n_dup, 'scarti': scarti},
        'V0_riferimento': {'corr_grade': A_grade_all, 'corr_odds': A_odds_all, 'corr_l10': A_l10_all},
        'V2': v2, 'test2_decisivo': test2, 'V4_out_of_sample': v4,
    }
    with open(path_out, 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    return result


def main():
    ruoli = [
        ('Midfielder', 'analisi_manager/dati/storico_grade_Midfielder_20260806.json',
         'analisi_manager/p12_briefA_mid_out.json'),
        ('Defender', 'analisi_manager/dati/storico_grade_Defender_20260806.json',
         'analisi_manager/p12_briefA_def_out.json'),
        ('Forward', 'analisi_manager/dati/storico_grade_Forward_20260806.json',
         'analisi_manager/p12_briefA_fwd_out.json'),
    ]
    for ruolo, path_dati, path_out in ruoli:
        print('\n' + '=' * 70)
        esegui_ruolo(ruolo, path_dati, path_out)
        _ctx_cache.clear()


if __name__ == '__main__':
    main()
