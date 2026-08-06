"""S4 -- test "il confronto coi vicini" (brief BRIEF_SONNET_S4_VICINI_2026-08-06.txt).
Zero query: usa solo dati gia' in repo.
"""
import json, random, io, sys

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
random.seed(20260806)


def load_player_rows(path, is_r5=False):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    players = []
    for entry in data:
        slug = entry.get('slug')
        ruolo = entry.get('ruolo')
        scores = entry.get('scores') or []
        rows = []
        for s in scores:
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
            rows.append({'date': date, 'grade': grade, 'score': score, 'starter_odds': starter_odds, 'mins': mins})
        players.append({'slug': slug, 'ruolo': ruolo, 'rows': rows})
    return players


def sanity_sort_and_dedup(players):
    scartate = 0
    cleaned = []
    for p in players:
        by_date = {}
        dup_dates = set()
        for r in p['rows']:
            d = r['date']
            if d in by_date:
                dup_dates.add(d)
            else:
                by_date[d] = r
        rows_ok = [r for r in p['rows'] if r['date'] not in dup_dates]
        scartate += len(p['rows']) - len(rows_ok)
        rows_ok.sort(key=lambda r: r['date'])
        cleaned.append({'slug': p['slug'], 'ruolo': p['ruolo'], 'rows': rows_ok})
    return cleaned, scartate


def build_triples(players, value_field, min_filter='none'):
    """Ritorna lista di (player_slug, value_k, score_k, score_km1, score_kp1)
    solo per righe con tutti e 3 gli score disponibili e value_k non nullo.
    min_filter: 'none' | 'k' (solo minsPlayed_k>0) | 'all3' (min>0 su k,k-1,k+1)."""
    triples = []
    for p in players:
        rows = p['rows']
        for i in range(1, len(rows) - 1):
            k = rows[i]
            km1 = rows[i - 1]
            kp1 = rows[i + 1]
            val = k.get(value_field)
            if value_field == 'grade':
                val = GRADE_NUM.get(val)
            if val is None:
                continue
            if k['score'] is None or km1['score'] is None or kp1['score'] is None:
                continue
            if min_filter == 'k':
                if not (k.get('mins') or 0) > 0:
                    continue
            elif min_filter == 'all3':
                if not ((k.get('mins') or 0) > 0 and (km1.get('mins') or 0) > 0 and (kp1.get('mins') or 0) > 0):
                    continue
            triples.append((p['slug'], val, k['score'], km1['score'], kp1['score']))
    return triples


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


def compute_abc(triples):
    if not triples:
        return None, None, None, 0
    vals = [t[1] for t in triples]
    sk = [t[2] for t in triples]
    skm1 = [t[3] for t in triples]
    skp1 = [t[4] for t in triples]
    A = corr(vals, sk)
    B = corr(vals, skm1)
    C = corr(vals, skp1)
    return A, B, C, len(triples)


def bootstrap_by_player(triples, n_boot=1000):
    by_player = {}
    for t in triples:
        by_player.setdefault(t[0], []).append(t)
    slugs = list(by_player.keys())
    if len(slugs) < 2:
        return None
    diffs_ac = []
    diffs_ab = []
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
    pct_ac_pos = sum(1 for d in diffs_ac if d > 0) / len(diffs_ac)
    pct_ab_pos = sum(1 for d in diffs_ab if d > 0) / len(diffs_ab)
    return {
        'n_boot': len(diffs_ac),
        'n_giocatori_distinti': len(slugs),
        'A_meno_C_pct_positivo': pct_ac_pos,
        'A_meno_C_range': [min(diffs_ac), max(diffs_ac)],
        'A_meno_B_pct_positivo': pct_ab_pos,
        'A_meno_B_range': [min(diffs_ab), max(diffs_ab)],
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
            'n_righe': n,
            'n_giocatori_distinti': n_players_used,
            'A_corr_grade_k_score_k': A,
            'B_corr_grade_k_score_km1': B,
            'C_corr_grade_k_score_kp1': C,
            'bootstrap': boot,
        }
        print(f'--- {tag} / {label} (filtro={min_filter}) ---')
        print(f'  n_righe={n} n_giocatori={n_players_used}')
        print(f'  A={A}  B={B}  C={C}')
        if boot:
            print(f'  bootstrap: A-C>0 in {boot["A_meno_C_pct_positivo"]*100:.1f}% dei 1000, '
                  f'A-B>0 in {boot["A_meno_B_pct_positivo"]*100:.1f}%')
    return out


def main():
    gk55 = load_player_rows('analisi_manager/p12_r5_gk_ampio.json')
    small12 = load_player_rows('analisi_manager/p12_r1_minuti.json')

    results = {}
    results['a_gk_ampio_55'] = run_sample('S4 (a) GK ampio 55', gk55)
    results['b_campione_piccolo_12_tutti_ruoli'] = run_sample('S4 (b) campione piccolo 12 (4 ruoli insieme)', small12)

    ruoli = sorted(set(p['ruolo'] for p in small12))
    results['b_campione_piccolo_per_ruolo'] = {}
    for ruolo in ruoli:
        sub = [p for p in small12 if p['ruolo'] == ruolo]
        results['b_campione_piccolo_per_ruolo'][ruolo] = run_sample(f'S4 (b) {ruolo} (3 giocatori)', sub)

    # S4-BIS: filtrato per minuti giocati (addendum 06/08 20:30 Roma)
    results['s4_bis_a_gk_ampio_filtro_k'] = run_sample('S4-BIS (a) GK ampio, filtro min>0 su k', gk55, min_filter='k')
    results['s4_bis_a_gk_ampio_filtro_all3'] = run_sample('S4-BIS (a) GK ampio, filtro min>0 su k,k-1,k+1', gk55, min_filter='all3')
    results['s4_bis_b_piccolo_filtro_k'] = run_sample('S4-BIS (b) piccolo 12, filtro min>0 su k', small12, min_filter='k')
    results['s4_bis_b_piccolo_filtro_all3'] = run_sample('S4-BIS (b) piccolo 12, filtro min>0 su k,k-1,k+1', small12, min_filter='all3')

    with open('analisi_manager/p12_s4_vicini_out.json', 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
