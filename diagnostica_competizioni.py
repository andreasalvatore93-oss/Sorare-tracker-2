"""Elenca le COMPETIZIONI attive delle carte possedute (27/07).

Obiettivo: sostituire la discovery per-campionato (che scarica tutte le carte
possedute e poi butta via quelle di altre leghe) con una discovery per
COMPETIZIONE, filtrata lato SERVER via advancedFilters `active_competitions:<slug>`
-- lo stesso meccanismo che la pipeline MLS usa gia' con 'mlspa'.

Se una lega e' in pausa, le sue carte non hanno competizioni attive e non
vengono nemmeno restituite: niente scansione, niente job, niente query odds.

Qui si scoprono gli slug esatti da usare: per un campione di carte possedute
stampa le competizioni a cui la carta e' eleggibile.
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'formazione_turchia', 'discovery'))
os.environ.setdefault('MIN_STARTER_ODDS', '0')
import turchia_gk_discovery as base  # noqa: E402

# Le carte hanno un campo con le competizioni per cui sono eleggibili adesso.
# Si provano piu' nomi possibili: il primo che l'API accetta viene usato.
CANDIDATE_QUERIES = [
    ("eligibleSo5Leaderboards", """
query CompAudit($userSlug: String!, $page: Int!, $pageSize: Int!, $advancedFilters: String) {
  user(slug: $userSlug) {
    searchCards(rarity: limited, sport: FOOTBALL, query: "", page: $page,
                pageSize: $pageSize, advancedFilters: $advancedFilters) {
      hits {
        slug
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
        latestEnrichedCard { eligibleSo5Leaderboards { slug displayName } }
      }
      nbHits
      nbPages
    }
  }
}
"""),
    ("activeCompetitions", """
query CompAudit($userSlug: String!, $page: Int!, $pageSize: Int!, $advancedFilters: String) {
  user(slug: $userSlug) {
    searchCards(rarity: limited, sport: FOOTBALL, query: "", page: $page,
                pageSize: $pageSize, advancedFilters: $advancedFilters) {
      hits {
        slug
        anyPlayer { slug displayName activeClub { domesticLeague { slug } } }
        activeCompetitions { slug displayName }
      }
      nbHits
      nbPages
    }
  }
}
"""),
]


def main():
    user_slug = base.USER_SLUG
    uuid = base.get_user_uuid(user_slug)
    if not uuid:
        print("uuid utente non ottenuto")
        return 1
    advanced = (f"user.id:{uuid} AND sport:football "
                f"AND NOT sealed=1 AND NOT rarity:custom_series")

    working = None
    for nome, q in CANDIDATE_QUERIES:
        print(f"\n--- provo campo '{nome}' ---")
        try:
            data = base.graphql_query(q, {"userSlug": user_slug, "page": 1,
                                          "pageSize": 50, "advancedFilters": advanced},
                                      operation_name="CompAudit")
        except Exception as e:
            print("  errore:", repr(e)[:200])
            continue
        if data.get('errors'):
            print("  GraphQL:", json.dumps(data['errors'])[:300])
            continue
        search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}
        if search.get('hits') is not None:
            print(f"  OK, campo valido. Carte totali: {search.get('nbHits')}")
            working = (nome, q, search)
            break

    if not working:
        print("\nNessun campo competizioni valido trovato: serve ispezionare lo schema.")
        return 1

    nome, q, first = working
    counter = Counter()
    esempi = {}
    page, pages = 1, first.get('nbPages') or 1
    search = first
    while page <= min(pages, 12):
        for h in (search.get('hits') or []):
            p = h.get('anyPlayer') or {}
            comps = h.get(nome) or (h.get('latestEnrichedCard') or {}).get('eligibleSo5Leaderboards') or []
            for c in comps:
                s = c.get('slug')
                if not s:
                    continue
                counter[s] += 1
                esempi.setdefault(s, (c.get('displayName'), p.get('displayName')))
        page += 1
        if page > pages:
            break
        time.sleep(0.3)
        data = base.graphql_query(q, {"userSlug": user_slug, "page": page, "pageSize": 50,
                                      "advancedFilters": advanced}, operation_name="CompAudit")
        search = ((data.get('data') or {}).get('user') or {}).get('searchCards') or {}

    print("\n" + "=" * 78)
    print("COMPETIZIONI ATTIVE SULLE TUE CARTE (slug da usare in active_competitions)")
    print("=" * 78)
    print(f"{'slug':<44}{'carte':>7}  nome / esempio")
    for s, n in counter.most_common():
        nm, pl = esempi[s]
        print(f"{s:<44}{n:>7}  {nm or ''} (es. {pl or ''})")
    if not counter:
        print("nessuna competizione attiva trovata sulle carte campionate")
    return 0


if __name__ == '__main__':
    sys.exit(main())
