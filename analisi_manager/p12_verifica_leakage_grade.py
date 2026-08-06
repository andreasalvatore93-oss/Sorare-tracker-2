"""P12 addendum -- test anti-riscrittura: confronta il grade pre-partita
catturato stamattina (analisi_manager/p12_step3_righe.json, 32 giocatori,
football-4-7-aug-2026) con il grade letto DOPO la partita via la rotta
alternativa anyPlayer.playerGameScores(last:N).projection.grade.

Da lanciare DOPO che le partite di football-4-7-aug-2026 sono concluse
(kickoff 18:00 Roma / 16:00 UTC, ultima 13:35 Roma del giorno dopo).

Uso: SORARE_COOKIE=... SORARE_CSRF=... python p12_verifica_leakage_grade.py
"""
import sys, os, io, json

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

CSRF = os.environ.get('SORARE_CSRF', '')
COOKIES = os.environ.get('SORARE_COOKIE', '') or g.COOKIES

QUERY = """
query PlayerPastGrade($slug: String!) {
  anyPlayer(slug: $slug) {
    playerGameScores(last: 8) {
      id
      score
      anyGame { date }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""


def past_grade_for_date(slug, target_date_prefix):
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF}
    r = g._http_session.post(g.GRAPHQL_URL, json={'query': QUERY, 'variables': {'slug': slug}}, headers=headers, timeout=20)
    d = r.json()
    if d.get('errors'):
        return None, d['errors']
    scores = ((d.get('data') or {}).get('anyPlayer') or {}).get('playerGameScores') or []
    for s in scores:
        gd = (s.get('anyGame') or {}).get('date') or ''
        if gd.startswith(target_date_prefix):
            return s, None
    return None, None


def main():
    with open('analisi_manager/p12_step3_righe.json', encoding='utf-8') as fh:
        morning = json.load(fh)

    results = []
    for row in morning:
        slug = row.get('slug')
        game_date = row.get('game_date') or ''
        date_prefix = game_date[:10]
        if not slug or not date_prefix:
            continue
        past, err = past_grade_for_date(slug, date_prefix)
        if err:
            results.append({'slug': slug, 'errore': str(err)[:200]})
            continue
        if past is None:
            results.append({'slug': slug, 'stato': 'non ancora disponibile (partita non finita o game non matchato)'})
            continue
        proj = past.get('projection') or {}
        results.append({
            'slug': slug,
            'grade_mattina': row.get('grade'),
            'grade_dopo_partita': proj.get('grade'),
            'identico': row.get('grade') == proj.get('grade'),
            'score_realizzato': past.get('score'),
        })

    with open('analisi_manager/p12_verifica_leakage_out.json', 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)

    n_confrontati = sum(1 for r in results if 'identico' in r)
    n_identici = sum(1 for r in results if r.get('identico') is True)
    n_diversi = sum(1 for r in results if r.get('identico') is False)
    print(f'Confrontati: {n_confrontati} / {len(morning)}')
    print(f'Identici (genuino pre-partita): {n_identici}')
    print(f'Diversi (riscritto = leakage): {n_diversi}')
    for r in results:
        print(' ', r)


if __name__ == '__main__':
    main()
