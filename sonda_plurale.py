"""Cerca il campo della So5Fixture che elenca le PARTITE della giornata."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),'formazione_turchia','discovery'))
os.environ.setdefault('MIN_STARTER_ODDS','0')
import turchia_gk_discovery as base
S="football-28-31-jul-2026"
CAND=[
 ("games", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug games{ id } } } }'),
 ("anyGames", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug anyGames{ id date } } } }'),
 ("anyGames.nodes", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug anyGames(first:5){ nodes{ id date } } } } }'),
 ("footballGames", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug footballGames{ id } } } }'),
 ("mySo5Lineups", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug mySo5Lineups{ id } } } }'),
 ("so5Leaderboards", 'query F($s:String!){ so5{ so5Fixture(slug:$s){ slug so5Leaderboards{ slug displayName } } } }'),
]
for n,q in CAND:
    print("\n--- "+n+" ---")
    try: d=base.graphql_query(q,{"s":S},operation_name="F")
    except Exception as e: print("  ecc:",repr(e)[:300]); continue
    if d.get('errors'): print("  errore:",json.dumps(d['errors'])[:400])
    else: print("  OK ->",json.dumps(d.get('data'))[:600])
