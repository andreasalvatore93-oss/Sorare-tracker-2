"""Verifica che players(slugs:) esponga anche partite future e starter odds."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),'formazione_turchia','discovery'))
os.environ.setdefault('MIN_STARTER_ODDS','0')
import turchia_gk_discovery as base

SL = ["elias-rafn-olafsson", "carlo-boukhalfa", "ignacio-pena-sotorres"]
Q = '''
query P($s:[String!]!){
  players(slugs:$s){
    slug
    displayName
    activeClub { domesticLeague { slug } }
    anyFutureGames(first: 3) {
      nodes {
        playerGameScore(playerSlug: "") { anyGame { date } }
      }
    }
  }
}
'''
Q2 = '''
query P($s:[String!]!){
  players(slugs:$s){
    slug
    activeClub { domesticLeague { slug } }
    futureGames(first: 3) { date }
  }
}
'''
for nome,q in (("con anyFutureGames",Q),("con futureGames",Q2)):
    print("\n--- "+nome+" ---")
    try:
        d = base.graphql_query(q, {"s": SL}, operation_name="P")
    except Exception as e:
        print("  eccezione:", repr(e)[:400]); continue
    if d.get('errors'):
        print("  errore:", json.dumps(d['errors'])[:600])
    else:
        print("  OK ->", json.dumps(d.get('data'))[:900])
