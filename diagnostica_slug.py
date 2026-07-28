"""Diagnostica: cosa risponde Sorare per uno slug giocatore.

Serve a capire perche' un giocatore che sul sito ha le starter odds risulta
"senza dato odds" nelle discovery. Stampa il payload grezzo di anyFutureGames
(date, competizione, odds) e i dati di club/lega.

Uso:  SLUGS="inaki-pena,altro-slug" python diagnostica_slug.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'formazione_turchia', 'discovery'))
os.environ.setdefault('MIN_STARTER_ODDS', '0')
import turchia_gk_discovery as base  # noqa: E402

QUERY = """
query Diagnostica($slug: String!) {
  anyPlayer(slug: $slug) {
    slug
    displayName
    activeClub {
      name
      domesticLeague { slug displayName }
    }
    anyFutureGames(first: 5) {
      nodes {
        id
        playerGameScore(playerSlug: $slug) {
          anyGame {
            date
            competition { slug }
            homeTeam { ... on TeamInterface { name slug } }
            awayTeam { ... on TeamInterface { name slug } }
          }
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints }
            }
          }
        }
      }
    }
  }
}
"""


def main():
    slugs = [s.strip() for s in os.environ.get('SLUGS', 'inaki-pena').split(',') if s.strip()]
    for slug in slugs:
        print("\n" + "=" * 78)
        print("SLUG:", slug)
        print("=" * 78)
        try:
            data = base.graphql_query(QUERY, {"slug": slug}, operation_name="Diagnostica")
        except Exception as e:
            print("ERRORE query:", repr(e))
            continue
        if data.get('errors'):
            print("ERRORI GraphQL:", json.dumps(data['errors'], indent=2)[:1500])
        p = (data.get('data') or {}).get('anyPlayer')
        if not p:
            print("anyPlayer NULLO -> slug inesistente o non accessibile")
            continue
        club = p.get('activeClub') or {}
        dl = club.get('domesticLeague') or {}
        print(f"nome: {p.get('displayName')}")
        print(f"club: {club.get('name')} | domesticLeague: {dl.get('slug') or 'NESSUNA'}")
        nodes = (p.get('anyFutureGames') or {}).get('nodes') or []
        print(f"partite future restituite: {len(nodes)}")
        for n in nodes:
            pgs = n.get('playerGameScore') or {}
            g = pgs.get('anyGame') or {}
            odds = ((pgs.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {})
            print(f"  - {(g.get('date') or '?')[:16]} "
                  f"comp={((g.get('competition') or {}).get('slug') or '?')} "
                  f"{(g.get('homeTeam') or {}).get('name','?')} vs {(g.get('awayTeam') or {}).get('name','?')}")
            print(f"    odds: {odds if odds else 'NESSUN DATO'}")


if __name__ == '__main__':
    main()
