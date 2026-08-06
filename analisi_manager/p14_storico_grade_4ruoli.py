"""Punto 14 handoff: rifa S4-bis + correlazioni su storico grade 175 giocatori x4 ruoli (Haiku).
Zero query, solo dati gia' in repo (analisi_manager/dati/storico_grade_<Ruolo>_20260806.json).
"""
import json, random, io, sys

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
random.seed(20260806)

ROLES = ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']


def load_players(role):
    with open(f'analisi_manager/dati/storico_grade_{role}_20260806.json', encoding='utf-8') as fh:
        data = json.load(fh)
    by_slug = {}
    for r in data:
        by_slug.setdefault(r['slug'], []).append(r)
    players = []
    for slug, rows in by_slug.items():
        clean = []
        for r in rows:
            if r['scoreStatus'] == 'REVIEWING':
                continue  # partita in corso, score parziale
            clean.append({
                'date': r['game_date'],
                'grade': r['grade'],
                'score': r['score_realizzato'],
                'starter_odds': r['starter_odds_bp'],
                'played': r['scoreStatus'] != 'DID_NOT_PLAY',
            })
        players.append({'slug': slug, 'rows': clean})
    return players


def sanity_sort_and_dedup(players):
    scartate = 0
    cleaned = []
    for p in players:
        by_date = {}
        dup = set()
        for r in p['rows']:
            if r['date'] in by_date:
                dup.add(r['date'])
            else:
                by_date[r['date']] = r
        rows_ok = [r for r in p['rows'] if r['date'] not in dup]
        scartate += len(p['rows']) - len(rows_ok)
        rows_ok.sort(key=lambda r: r['date'])
        cleaned.append({'slug': p['slug'], 'rows': rows_ok})
    return cleaned, scartate


def build_triples(players, value_field, min_filter='none'):
    triples = []
    for p in players:
        rows = p['rows']
        for i in range(1, len(rows) - 1):
            k, km1, kp1 = rows[i], rows[i - 1], rows[i + 1]
            val = k.get(value_field)
            if value_field == 'grade':
                val = GRADE_NUM.get(val)
            if val is None:
                continue
            if min_filter == 'k' and not k['played']:
                continue
            if min_filter == 'all3' and not (k['played'] and km1['played'] and kp1['played']):
                continue
            triples.append((p['slug'], val, k['score'], km1['score'], kp1['score']))
    return triples


def corr(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def compute_abc(triples):
    if not triples:
        return None, None, None, 0
    vals = [t[1] for t in triples]
    sk = [t[2] for t in triples]
    skm1 = [t[3] for t in triples]
    skp1 = [t[4] for t in triples]
    return corr(vals, sk), corr(vals, skm1), corr(vals, skp1), len(triples)


def bootstrap_by_player(triples, n_boot=1000):
    by_player = {}
    for t in triples:
        by_player.setdefault(t[0], []).append(t)
    slugs = list(by_player.keys())
    if len(slugs) < 2:
        return None
    diffs_ac, diffs_ab = [], []
    for _ in range(n_boot):
        sample_slugs = [random.choice(slugs) for _ in slugs]
        sample_triples = []
        for s in sample_slugs:
            sample_triples.extend(by_player[s])
        A, B, C, n = compute_abc(sample_triples)
        if A is None or B is None or C is None:
            continue
        diffs_ac.append(A - C)
        diffs_ab.append(A - B)
    if not diffs_ac:
        return None
    return {
        'n_boot': len(diffs_ac),
        'n_giocatori_distinti': len(slugs),
        'A_meno_C_pct_positivo': sum(1 for d in diffs_ac if d > 0) / len(diffs_ac),
        'A_meno_B_pct_positivo': sum(1 for d in diffs_ab if d > 0) / len(diffs_ab),
    }


def run_sample(tag, players, min_filter='none'):
    out = {}
    players_clean, scartate = sanity_sort_and_dedup(players)
    out['scartate_doppia_data'] = scartate
    out['n_giocatori'] = len(players_clean)
    for value_field, label in [('grade', 'grade'), ('starter_odds', 'starter_odds')]:
        triples = build_triples(players_clean, value_field, min_filter=min_filter)
        A, B, C, n = compute_abc(triples)
        n_players_used = len(set(t[0] for t in triples))
        boot = bootstrap_by_player(triples)
        out[label] = {
            'n_righe': n, 'n_giocatori_distinti': n_players_used,
            'A': A, 'B': B, 'C': C, 'bootstrap': boot,
        }
        print(f'--- {tag} / {label} (filtro={min_filter}) ---')
        print(f'  n_righe={n} n_giocatori={n_players_used}  A={A} B={B} C={C}')
        if boot:
            print(f'  bootstrap: A-C>0 {boot["A_meno_C_pct_positivo"]*100:.1f}%  A-B>0 {boot["A_meno_B_pct_positivo"]*100:.1f}%')
    return out


# ---------- Punto 3: corr(grade), corr(odds), corr(L10), diff bootstrap ----------

def build_rows_with_l10(players):
    """Per ogni riga k (con k>=1, cioe' almeno 1 partita precedente disponibile),
    calcola L10 = media (non pesata) degli score delle fino a 10 partite precedenti
    NEL DATASET (sequenza cronologica), solo tra quelle giocate (played=True)."""
    rows = []
    for p in players:
        r = p['rows']
        for i in range(1, len(r)):
            k = r[i]
            if not k['played']:
                continue
            prev_played = [x['score'] for x in r[:i] if x['played']]
            if not prev_played:
                continue
            l10 = sum(prev_played[-10:]) / len(prev_played[-10:])
            grade_val = GRADE_NUM.get(k['grade'])
            if grade_val is None or k['starter_odds'] is None:
                continue
            rows.append({
                'slug': p['slug'], 'grade': grade_val, 'starter_odds': k['starter_odds'],
                'l10': l10, 'score': k['score'],
            })
    return rows


def corr_and_diff_bootstrap(rows, field_a, field_b, n_boot=1000):
    by_player = {}
    for r in rows:
        by_player.setdefault(r['slug'], []).append(r)
    slugs = list(by_player.keys())

    def corr_pair(sub_rows, field):
        return corr([r[field] for r in sub_rows], [r['score'] for r in sub_rows])

    A = corr_pair(rows, field_a)
    B = corr_pair(rows, field_b)
    diffs = []
    for _ in range(n_boot):
        sample_slugs = [random.choice(slugs) for _ in slugs]
        sample_rows = []
        for s in sample_slugs:
            sample_rows.extend(by_player[s])
        ca = corr_pair(sample_rows, field_a)
        cb = corr_pair(sample_rows, field_b)
        if ca is None or cb is None:
            continue
        diffs.append(ca - cb)
    if not diffs:
        return A, B, None
    pct_pos = sum(1 for d in diffs if d > 0) / len(diffs)
    return A, B, {'n_boot': len(diffs), 'pct_a_meno_b_positivo': pct_pos, 'n_giocatori': len(slugs)}


def run_point3(role, players):
    rows = build_rows_with_l10(players)
    out = {'n_righe': len(rows), 'n_giocatori': len(set(r['slug'] for r in rows))}
    corr_grade = corr([r['grade'] for r in rows], [r['score'] for r in rows])
    corr_odds = corr([r['starter_odds'] for r in rows], [r['score'] for r in rows])
    corr_l10 = corr([r['l10'] for r in rows], [r['score'] for r in rows])
    out['corr_grade'] = corr_grade
    out['corr_starter_odds'] = corr_odds
    out['corr_l10'] = corr_l10
    A, B, boot = corr_and_diff_bootstrap(rows, 'grade', 'starter_odds')
    out['grade_vs_odds'] = {'A_grade': A, 'B_odds': B, 'bootstrap_A_meno_B': boot}
    A, B, boot = corr_and_diff_bootstrap(rows, 'grade', 'l10')
    out['grade_vs_l10'] = {'A_grade': A, 'B_l10': B, 'bootstrap_A_meno_B': boot}
    print(f'--- PUNTO 3 {role} --- n_righe={out["n_righe"]} n_giocatori={out["n_giocatori"]}')
    print(f'  corr_grade={corr_grade} corr_odds={corr_odds} corr_l10={corr_l10}')
    print(f'  grade-odds bootstrap A>B: {boot if False else out["grade_vs_odds"]["bootstrap_A_meno_B"]}')
    print(f'  grade-l10  bootstrap A>B: {out["grade_vs_l10"]["bootstrap_A_meno_B"]}')
    return out


def main():
    results = {}

    # Punto 1: distribuzione partite per giocatore Forward (verifica distorsione campione)
    fwd = load_players('Forward')
    n_partite = [len(p['rows']) for p in fwd]
    n_partite.sort()
    results['punto1_fwd_distribuzione_partite'] = {
        'n_giocatori': len(fwd),
        'min': n_partite[0] if n_partite else None,
        'p25': n_partite[len(n_partite)//4] if n_partite else None,
        'mediana': n_partite[len(n_partite)//2] if n_partite else None,
        'p75': n_partite[3*len(n_partite)//4] if n_partite else None,
        'max': n_partite[-1] if n_partite else None,
        'n_con_meno_di_5': sum(1 for x in n_partite if x < 5),
        'n_con_15_o_piu': sum(1 for x in n_partite if x >= 15),
    }
    print('PUNTO 1 (Forward):', results['punto1_fwd_distribuzione_partite'])

    all_players = {r: load_players(r) for r in ROLES}

    # Punto 2: S4-bis per ruolo, filtro k e all3
    results['punto2_s4bis'] = {}
    for role in ROLES:
        results['punto2_s4bis'][role] = {
            'filtro_k': run_sample(f'{role} filtro k', all_players[role], min_filter='k'),
            'filtro_all3': run_sample(f'{role} filtro all3', all_players[role], min_filter='all3'),
        }

    # Punto 3 + 4: solo per ruoli che passano punto 2 -- lo decide l'orchestratore leggendo l'output,
    # qui lo calcoliamo per tutti e 4 cosi' il verdetto si legge subito senza un secondo giro.
    results['punto3_e_4_corr'] = {}
    for role in ROLES:
        results['punto3_e_4_corr'][role] = run_point3(role, all_players[role])

    with open('analisi_manager/p14_storico_grade_4ruoli_out.json', 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print('\nSalvato analisi_manager/p14_storico_grade_4ruoli_out.json')


if __name__ == '__main__':
    main()
