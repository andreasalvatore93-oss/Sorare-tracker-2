"""Cattura snapshot grade A-F (So5Score.projection.grade) pre-partita, per la
GW corrente. Il grade non e' recuperabile a ritroso (leaderboard chiusa torna
0 nodi): l'unico modo per giudicarlo e' registrarlo in avanti. Vedi
docs/handoff/HANDOFF_LETTERA_GRADE_2026-08-06.txt sezione 7/8.

Uso:
  SORARE_COOKIE=... SORARE_CSRF=... python grade_snapshot.py <leaderboard_slug>
"""
import sys, os, io, json
from datetime import datetime, timezone, timedelta

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

COOKIES = os.environ.get('SORARE_COOKIE', '')
CSRF = os.environ.get('SORARE_CSRF', '')

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
            anyPlayer { displayName slug l10: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE) }
            anyCard { rarityTyped anyTeam { name slug } }
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


def _check_credentials():
    r = g._http_session.post(
        g.GRAPHQL_URL,
        json={'query': 'query { currentUser { slug } }'},
        headers={'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF},
        timeout=20,
    )
    d = r.json()
    user = (d.get('data') or {}).get('currentUser')
    if not user:
        raise RuntimeError(f'Credenziali Sorare scadute o mancanti: currentUser=null. Risposta: {d}')
    return user['slug']


def bench_query(so5_slug, positions, page_size=100):
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
               'Cookie': COOKIES, 'X-CSRF-Token': CSRF}
    r = g._http_session.post(g.GRAPHQL_URL, json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:500]}')
    d = r.json()
    if d.get('errors'):
        raise RuntimeError(f'GraphQL errors: {d["errors"][:3]}')
    nodes = (((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard') or {}).get('myFilteredBench', {}).get('nodes') or []
    return nodes


def capture(so5_slug):
    now_utc = datetime.now(timezone.utc)
    now_roma = now_utc.astimezone(timezone(timedelta(hours=2)))
    out = []
    for pos in ("Goalkeeper", "Defender", "Midfielder", "Forward"):
        nodes = bench_query(so5_slug, [pos], page_size=100)
        for n in nodes:
            ap = n.get('anyPlayer') or {}
            card = n.get('anyCard') or {}
            team = (card.get('anyTeam') or {})
            for sc in n.get('eligiblePlayerGameScores') or []:
                proj = sc.get('projection') or {}
                ag = sc.get('anyGame') or {}
                pgs = (sc.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}
                home = ag.get('homeTeam', {}).get('slug')
                away = ag.get('awayTeam', {}).get('slug')
                is_home = team.get('slug') == home
                own_odds = (ag.get('homeStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('awayStats') or {}).get('winOddsBasisPoints')
                opp_odds = (ag.get('awayStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('homeStats') or {}).get('winOddsBasisPoints')
                game_date = ag.get('date')
                minuti_al_fischio = None
                if game_date:
                    try:
                        gd = datetime.fromisoformat(game_date.replace('Z', '+00:00'))
                        minuti_al_fischio = round((gd - now_utc).total_seconds() / 60, 1)
                    except Exception:
                        pass
                out.append({
                    'ruolo': pos,
                    'nome': ap.get('displayName'),
                    'slug': ap.get('slug'),
                    'squadra': team.get('slug'),
                    'rarity': card.get('rarityTyped'),
                    'grade': proj.get('grade'),
                    'reliability_bp': proj.get('reliabilityBasisPoints'),
                    'starter_odds_bp': pgs.get('starterOddsBasisPoints'),
                    'starter_reliability': pgs.get('reliability'),
                    'scoreStatus': sc.get('scoreStatus'),
                    'l10': ap.get('l10'),
                    'game_date': game_date,
                    'home_team': home,
                    'away_team': away,
                    'own_win_odds_bp': own_odds,
                    'opp_win_odds_bp': opp_odds,
                    'leaderboard_slug': so5_slug,
                    'captured_at_utc': now_utc.isoformat(),
                    'captured_at_roma': now_roma.isoformat(),
                    'minuti_al_fischio': minuti_al_fischio,
                })
    return out


def main():
    if len(sys.argv) < 2:
        print('Uso: python grade_snapshot.py <leaderboard_slug>')
        sys.exit(1)
    so5_slug = sys.argv[1]
    _check_credentials()
    rows = capture(so5_slug)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    gw_tag = so5_slug.split('-seasonal')[0]
    out_path = f'analisi_manager/dati/grade_snapshot_{gw_tag}_{ts}.json'
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f'{len(rows)} righe salvate in {out_path}')
    by_role = {}
    for r in rows:
        by_role[r['ruolo']] = by_role.get(r['ruolo'], 0) + 1
    for role, n in by_role.items():
        print(f'  {role}: {n}')


if __name__ == '__main__':
    main()
