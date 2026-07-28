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
    birthDay
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


XP_PROBE_QUERY = """
query XpProbe($userSlug: String!) {
  user(slug: $userSlug) {
    searchCards(rarity: limited, sport: FOOTBALL, query: "", page: 1, pageSize: 3,
                sorts: [{field: "user_owner.from", direction: DESC}]) {
      hits {
        slug
        inSeasonEligible
        xp
        anyPlayer { slug displayName }
      }
    }
  }
}
"""


def probe_xp():
    print("\n" + "=" * 78)
    print("PROBE XP su carte possedute")
    print("=" * 78)
    data = base.graphql_query(XP_PROBE_QUERY, {"userSlug": base.USER_SLUG}, operation_name="XpProbe")
    if data.get('errors'):
        print("ERRORI GraphQL:", json.dumps(data['errors'], indent=2)[:2000])
    hits = ((data.get('data') or {}).get('user') or {}).get('searchCards', {}).get('hits') or []
    for h in hits:
        print(json.dumps(h, indent=2))


CARD_BONUS_PROBE_QUERY = """
query CardBonusProbe($slug: String!) {
  anyCard(slug: $slug) {
    slug
    ... on Card {
      xp
      seasonBonus
      collectionBonus
      experienceBonus
      powerBonus
      totalBonus
      bonusPercentage
      scoreBonuses
    }
  }
}
"""


def probe_card_bonus(card_slug):
    print("\n" + "=" * 78)
    print("PROBE bonus carta:", card_slug)
    print("=" * 78)
    try:
        data = base.graphql_query(CARD_BONUS_PROBE_QUERY, {"slug": card_slug}, operation_name="CardBonusProbe")
    except Exception as e:
        print("ERRORE query:", repr(e))
        return
    if data.get('errors'):
        print("ERRORI GraphQL:", json.dumps(data['errors'], indent=2)[:2000])
    card = (data.get('data') or {}).get('anyCard')
    print(json.dumps(card, indent=2) if card else "anyCard NULLO")


def main():
    slugs = [s.strip() for s in os.environ.get('SLUGS', 'carlos-miguel').split(',') if s.strip()]
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
        print(f"nome: {p.get('displayName')} | birthDay: {p.get('birthDay')}")
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
    probe_xp()
    card_slug = os.environ.get('CARD_SLUG', '').strip()
    if card_slug:
        probe_card_bonus(card_slug)
