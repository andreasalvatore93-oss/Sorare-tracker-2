"""P12 -- lettera A-F (potenziale della GW): step1/2/3 del brief lettera.
Query GraphQL reale (FootballComposeBenchQuery, scoperta col cookie utente e
X-CSRF-Token, tipo BenchFilterInput). Nessuna modifica produzione, nessun
commit."""
import sys, os, io, json
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

CSRF = os.environ.get('SORARE_CSRF', 'HIldTmfZ8W3p06r7S7nXGa22u0KfdXBW16PQWA39ii_rw7lAZqqcgNf4Ny1RhWu9gaXJwwhvq_ASbDMq5soP6g')

QUERY = """
query FootballComposeBenchQuery($so5LeaderboardSlug: String!, $filters: BenchFilterInput!, $pageSize: Int) {
  so5 {
    so5Leaderboard(slug: $so5LeaderboardSlug) {
      myFilteredBench(filters: $filters, first: $pageSize) {
        nodes {
          __typename
          ... on ComposeTeamBenchCard {
            id
            position
            anyPlayer { displayName slug }
            anyCard { anyTeam { name slug } }
            eligiblePlayerGameScores(so5LeaderboardSlug: $so5LeaderboardSlug) {
              id
              position
              scoreStatus
              anyGame {
                date
                homeTeam { slug }
                awayTeam { slug }
                homeStats { ... on FootballTeamGameStats { winOddsBasisPoints } }
                awayStats { ... on FootballTeamGameStats { winOddsBasisPoints } }
              }
              anyPlayerGameStats {
                ... on PlayerGameStats { footballPlayingStatusOdds { starterOddsBasisPoints reliability } }
              }
              projection { grade reliabilityBasisPoints }
            }
          }
        }
      }
      slug
    }
  }
}
"""


def bench_query(so5_slug, positions, page_size=20):
    variables = {
        "filters": {
            "query": "", "rarities": [], "includeUsed": True, "includeNoGame": False,
            "inSeasonEligible": False, "includeUnavailablePlayers": True,
            "lastTenPlayedSo5AverageScore": {"max": 100}, "positions": positions,
            "selectedObjectIds": [], "sortType": {"type": "POPULAR_STARTERS", "direction": "DESC"},
            "teamMode": "ALL"
        },
        "pageSize": page_size,
        "so5LeaderboardSlug": so5_slug,
    }
    payload = {"operationName": "FootballComposeBenchQuery", "query": QUERY, "variables": variables}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'Cookie': g.COOKIES, 'X-CSRF-Token': CSRF}
    r = g._http_session.post(g.GRAPHQL_URL, json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        print('ERRORE', r.status_code, r.text[:500])
        return []
    d = r.json()
    if d.get('errors'):
        print('ERRORE GraphQL', d['errors'][:2])
        return []
    nodes = (((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard') or {}).get('myFilteredBench', {}).get('nodes') or []
    return nodes


def main():
    so5_slug = "football-4-7-aug-2026-seasonal-all_star-all_seasons_all_star_arena_limited"
    out = []
    for pos in ("Goalkeeper", "Defender", "Midfielder", "Forward"):
        nodes = bench_query(so5_slug, [pos], page_size=8)
        for n in nodes:
            ap = n.get('anyPlayer') or {}
            team = ((n.get('anyCard') or {}).get('anyTeam') or {})
            for sc in n.get('eligiblePlayerGameScores') or []:
                proj = sc.get('projection') or {}
                ag = sc.get('anyGame') or {}
                pgs = (sc.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}
                home = ag.get('homeTeam', {}).get('slug')
                away = ag.get('awayTeam', {}).get('slug')
                is_home = team.get('slug') == home
                own_odds = (ag.get('homeStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('awayStats') or {}).get('winOddsBasisPoints')
                opp_odds = (ag.get('awayStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('homeStats') or {}).get('winOddsBasisPoints')
                out.append({
                    'ruolo': pos,
                    'nome': ap.get('displayName'),
                    'slug': ap.get('slug'),
                    'squadra': team.get('slug'),
                    'grade': proj.get('grade'),
                    'reliability_bp': proj.get('reliabilityBasisPoints'),
                    'starter_odds_bp': pgs.get('starterOddsBasisPoints'),
                    'starter_reliability': pgs.get('reliability'),
                    'scoreStatus': sc.get('scoreStatus'),
                    'game_date': ag.get('date'),
                    'own_win_odds_bp': own_odds,
                    'opp_win_odds_bp': opp_odds,
                })
    with open('analisi_manager/p12_step1_grade.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f'{len(out)} righe salvate in analisi_manager/p12_step1_grade.json')
    for r in out:
        print(f"  {r['ruolo']:11s} {r['nome'] or r['slug']:25s} {r['squadra']:20s} grade={r['grade']} rel={r['reliability_bp']} starter_odds={r['starter_odds_bp']} status={r['scoreStatus']}")


if __name__ == '__main__':
    main()
