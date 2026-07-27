"""Audit delle leghe possedute (27/07).

Elenca, per OGNI ruolo, quante carte possiedi in ogni domesticLeague, con lo
slug ESATTO usato da Sorare. Serve a creare le pipeline dei campionati non
ancora tracciati (Danimarca, Argentina, Grecia, ...) senza indovinare gli slug:
si legge da qui e si clona una pipeline esistente con quel valore.

Riusa la stessa query searchCards delle discovery per-lega, ma NON filtra per
lega: le raggruppa tutte. Nessuna scrittura, solo output a video.
"""
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'formazione_turchia', 'discovery'))

os.environ.setdefault('MIN_STARTER_ODDS', '0')
import turchia_gk_discovery as base  # noqa: E402  (riusa graphql_query/USER_SLUG/PAGE_SIZE)

POSITIONS = ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']

QUERY = """
query LeagueAudit($userSlug: String!, $page: Int!, $pageSize: Int!,
                  $advancedFilters: String, $refinements: [SearchRefinementInput!]) {
  user(slug: $userSlug) {
    searchCards(
      rarity: limited
      sport: FOOTBALL
      query: ""
      page: $page
      pageSize: $pageSize
      advancedFilters: $advancedFilters
      refinements: $refinements
    ) {
      hits {
        slug
        anyPlayer {
          slug
          displayName
          activeClub { name domesticLeague { slug displayName } }
        }
      }
      nbHits
      nbPages
    }
  }
}
"""


def main():
    user_slug = base.USER_SLUG
    user_uuid = base.get_user_uuid(user_slug)
    if not user_uuid:
        print('Impossibile ottenere uuid utente')
        return 1
    advanced = (f"user.id:{user_uuid} AND sport:football "
                f"AND NOT sealed=1 AND NOT rarity:custom_series")

    per_league = defaultdict(lambda: defaultdict(set))   # league -> ruolo -> slug
    league_names = {}

    for position in POSITIONS:
        for in_season_value in ('true', 'false'):
            refinements = [
                {"field": "position", "operator": "EQUAL",
                 "values": [{"stringValue": position}]},
                {"field": "in_season_eligible", "operator": "EQUAL",
                 "values": [{"stringValue": in_season_value}]},
            ]
            page = 1
            while page <= 50:
                data = base.graphql_query(QUERY, {
                    "userSlug": user_slug, "page": page, "pageSize": base.PAGE_SIZE,
                    "advancedFilters": advanced, "refinements": refinements,
                }, operation_name="LeagueAudit")
                search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
                hits = search.get('hits') or []
                if not hits:
                    break
                for h in hits:
                    p = h.get('anyPlayer') or {}
                    club = p.get('activeClub') or {}
                    dl = club.get('domesticLeague') or {}
                    slug = dl.get('slug') or '(nessuna lega)'
                    league_names[slug] = dl.get('displayName') or ''
                    if p.get('slug'):
                        per_league[slug][position].add(p['slug'])
                if page >= (search.get('nbPages') or 1):
                    break
                page += 1
                time.sleep(0.3)

    tracciate = {
        'austrian-bundesliga', 'jupiler-pro-league', 'campeonato-brasileiro-serie-a',
        '1-hnl', 'ligue-1-fr', 'ligue-2-fr', 'bundesliga-de', '2-bundesliga',
        'j1-league', 'j1-100-year-vision-league', 'premier-league-gb-eng',
        'football-league-championship', 'serie-a-it', 'k-league-1', 'major-league-soccer',
        'eredivisie', 'primeira-liga-pt', 'premiership-gb-sct', 'laliga-es',
        'spor-toto-super-lig',
    }

    righe = []
    for slug, ruoli in per_league.items():
        tot = sum(len(v) for v in ruoli.values())
        righe.append((tot, slug, ruoli))
    righe.sort(reverse=True)

    print("\n" + "=" * 78)
    print("LEGHE IN CUI POSSIEDI CARTE (slug esatto Sorare)")
    print("=" * 78)
    print(f"{'slug':<38}{'GK':>4}{'DEF':>5}{'MID':>5}{'FWD':>5}{'tot':>6}  stato")
    for tot, slug, ruoli in righe:
        g, d, m, f = (len(ruoli.get(p, ())) for p in POSITIONS)
        stato = 'tracciata' if slug in tracciate else '*** NON TRACCIATA ***'
        print(f"{slug:<38}{g:>4}{d:>5}{m:>5}{f:>5}{tot:>6}  {stato}")

    mancanti = {s: {p: sorted(v) for p, v in r.items()}
                for _, s, r in righe if s not in tracciate and s != '(nessuna lega)'}
    print("\n--- LEGHE DA CREARE (slug -> giocatori posseduti) ---")
    print(json.dumps(mancanti, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
