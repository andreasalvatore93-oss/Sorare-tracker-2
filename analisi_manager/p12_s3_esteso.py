"""S3 esteso (brief BRIEF_SONNET_S3_LEAKAGE_2026-08-06.txt).
S3.1/S3.2: confronto grade pre-partita (rotta compose) vs grade post-partita
(rotta storica anyPlayer.playerGameScores), su 32 righe e poi su 174 righe.
S3.3: discriminante corr(delta, realizzato), solo se emergono righe diverse.
S3.4: confronto a costo zero fra le due catture pre-partita (10:39 vs 13:24).
S3.5: sanity check sul matching per data.

Uso: SORARE_COOKIE=... SORARE_CSRF=... python analisi_manager/p12_s3_esteso.py
"""
import sys, os, io, json
from collections import Counter

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

CSRF = os.environ.get('SORARE_CSRF', '')
COOKIES = os.environ.get('SORARE_COOKIE', '') or g.COOKIES

QUERY = """
query PlayerPastGrade($slug: String!) {
  anyPlayer(slug: $slug) {
    playerGameScores(last: 15) {
      id
      score
      anyGame { date }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}


def past_grade_for_date(slug, target_date_prefix):
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF}
    r = g._http_session.post(g.GRAPHQL_URL, json={'query': QUERY, 'variables': {'slug': slug}}, headers=headers, timeout=20)
    d = r.json()
    if d.get('errors'):
        return None, d['errors'], []
    scores = ((d.get('data') or {}).get('anyPlayer') or {}).get('playerGameScores') or []
    matches = [s for s in scores if ((s.get('anyGame') or {}).get('date') or '').startswith(target_date_prefix)]
    if not matches:
        return None, None, []
    return matches[0], None, matches


def build_comparison(rows, cache):
    """rows: lista con 'slug','grade','game_date'. cache: slug -> (past,err,matches)."""
    out = []
    scarti_doppia_data = 0
    for row in rows:
        slug = row.get('slug')
        game_date = row.get('game_date') or ''
        date_prefix = game_date[:10]
        if not slug or not date_prefix:
            continue
        if slug not in cache:
            cache[slug] = past_grade_for_date(slug, date_prefix)
        past, err, matches = cache[slug]
        if err:
            out.append({'slug': slug, 'errore': str(err)[:200]})
            continue
        if len(matches) > 1:
            scarti_doppia_data += 1
            out.append({'slug': slug, 'stato': 'scartata: piu partite stessa data'})
            continue
        if past is None:
            out.append({'slug': slug, 'stato': 'non confrontabile (partita non finita o non matchata)'})
            continue
        score = past.get('score')
        if score is None:
            out.append({'slug': slug, 'stato': 'non confrontabile (score nullo, partita non davvero chiusa)'})
            continue
        proj = past.get('projection') or {}
        grade_pre = row.get('grade')
        grade_post = proj.get('grade')
        out.append({
            'slug': slug,
            'ruolo': row.get('ruolo'),
            'grade_pre': grade_pre,
            'grade_post': grade_post,
            'identico': grade_pre == grade_post,
            'score_realizzato': score,
            'grade_pre_num': GRADE_NUM.get(grade_pre),
            'grade_post_num': GRADE_NUM.get(grade_post),
        })
    return out, scarti_doppia_data


def summarize(tag, rows):
    confr = [r for r in rows if 'identico' in r]
    ident = [r for r in confr if r['identico']]
    divers = [r for r in confr if not r['identico']]
    print(f'--- {tag} ---')
    print(f'  righe totali: {len(rows)}  confrontabili: {len(confr)}  identici: {len(ident)}  diversi: {len(divers)}')
    per_ruolo = Counter(r.get('ruolo') for r in confr)
    per_ruolo_ident = Counter(r.get('ruolo') for r in ident)
    for ruolo, n in per_ruolo.items():
        print(f'    {ruolo}: confrontabili={n} identici={per_ruolo_ident.get(ruolo,0)}')
    return confr, ident, divers


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


def main():
    with open('analisi_manager/p12_step3_righe.json', encoding='utf-8') as fh:
        rows32 = json.load(fh)
    with open('analisi_manager/dati/grade_snapshot_football-4-7-aug-2026_20260806_1124.json', encoding='utf-8') as fh:
        rows174 = json.load(fh)

    cache = {}

    # S3.1
    cmp32, scarti32 = build_comparison(rows32, cache)
    confr32, ident32, divers32 = summarize('S3.1 baseline (32 righe di partenza)', cmp32)

    # S3.2
    cmp174, scarti174 = build_comparison(rows174, cache)
    confr174, ident174, divers174 = summarize('S3.2 esteso (174 righe di partenza)', cmp174)

    # S3.3 -- solo se ci sono righe diverse in S3.1+S3.2
    s33 = None
    tutte_diverse = divers32 + divers174
    tutte_confr = confr32 + confr174
    if tutte_diverse:
        # dedup per slug (stesso giocatore potrebbe comparire in entrambi i campioni)
        by_slug = {}
        for r in tutte_confr:
            by_slug[r['slug']] = r
        rows_u = list(by_slug.values())
        pre = [r['grade_pre_num'] for r in rows_u if r['grade_pre_num'] is not None and r['grade_post_num'] is not None and r['score_realizzato'] is not None]
        post = [r['grade_post_num'] for r in rows_u if r['grade_pre_num'] is not None and r['grade_post_num'] is not None and r['score_realizzato'] is not None]
        delta = [b - a for a, b in zip(pre, post)]
        real = [r['score_realizzato'] for r in rows_u if r['grade_pre_num'] is not None and r['grade_post_num'] is not None and r['score_realizzato'] is not None]
        c_pre = corr(pre, real)
        c_post = corr(post, real)
        c_delta = corr(delta, real)
        saliti = [r for r in rows_u if r.get('grade_pre_num') is not None and r.get('grade_post_num') is not None and r['grade_post_num'] > r['grade_pre_num']]
        scesi = [r for r in rows_u if r.get('grade_pre_num') is not None and r.get('grade_post_num') is not None and r['grade_post_num'] < r['grade_pre_num']]
        avg_saliti = sum(r['score_realizzato'] for r in saliti) / len(saliti) if saliti else None
        avg_scesi = sum(r['score_realizzato'] for r in scesi) / len(scesi) if scesi else None
        s33 = {
            'n_righe_diverse_uniche': len(rows_u) - len([r for r in rows_u if r['identico']]),
            'n_totale_uniche': len(rows_u),
            'corr_pre_realizzato': c_pre,
            'corr_post_realizzato': c_post,
            'corr_delta_realizzato': c_delta,
            'n_saliti': len(saliti),
            'n_scesi': len(scesi),
            'punteggio_medio_saliti': avg_saliti,
            'punteggio_medio_scesi': avg_scesi,
        }
        print('--- S3.3 discriminante ---')
        print(' ', s33)
    else:
        print('--- S3.3: SALTATO, nessuna riga diversa in S3.1+S3.2 ---')

    # S3.4 -- costo zero, nessuna query: confronto fra le due catture pre-partita
    grade_1039 = {r['slug']: r.get('grade') for r in rows32 if r.get('slug')}
    grade_1324 = {r['slug']: r.get('grade') for r in rows174 if r.get('slug')}
    intersez = set(grade_1039) & set(grade_1324)
    ident_1039_1324 = sum(1 for s in intersez if grade_1039[s] == grade_1324[s])
    print('--- S3.4 (nessuna query, due catture pre-partita stessa rotta) ---')
    print(f'  intersezione giocatori: {len(intersez)}  identici: {ident_1039_1324}')

    scarti_totali = scarti32 + scarti174
    print(f'--- S3.5 sanity check matching ---')
    print(f'  righe scartate per doppia partita stessa data: {scarti_totali}')

    out = {
        's3_1_baseline_32': cmp32,
        's3_2_esteso_174': cmp174,
        's3_3_discriminante': s33,
        's3_4_due_catture_pre_partita': {
            'n_intersezione': len(intersez),
            'n_identici': ident_1039_1324,
            'slug_diversi': [s for s in intersez if grade_1039[s] != grade_1324[s]],
        },
        's3_5_scarti_doppia_data': scarti_totali,
    }
    with open('analisi_manager/p12_s3_esteso_out.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
