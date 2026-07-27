"""Cerca una query PLURALE per interrogare piu' giocatori in una richiesta.
anyPlayer non ammette alias duplicati ('Duplicated root field'), quindi il
batching va fatto con un campo che accetti una lista di slug."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),'formazione_turchia','discovery'))
os.environ.setdefault('MIN_STARTER_ODDS','0')
import turchia_gk_discovery as base

SL = ["elias-rafn-olafsson", "carlo-boukhalfa"]
CANDIDATI = [
    ("anyPlayers(slugs)", 'query P($s:[String!]!){ anyPlayers(slugs:$s){ slug displayName } }'),
    ("players(slugs)",    'query P($s:[String!]!){ players(slugs:$s){ slug displayName } }'),
    ("football.players(slugs)", 'query P($s:[String!]!){ football { players(slugs:$s){ nodes { slug displayName } } } }'),
    ("nodes(ids)",        'query P($s:[String!]!){ nodes(ids:$s){ __typename } }'),
    ("anyPlayers(first)", 'query P{ anyPlayers(first:2){ nodes { slug } } }'),
]
for nome,q in CANDIDATI:
    print("\n--- "+nome+" ---")
    try:
        d = base.graphql_query(q, {"s": SL}, operation_name="P")
    except Exception as e:
        print("  eccezione:", repr(e)[:300]); continue
    if d.get('errors'):
        print("  errore:", json.dumps(d['errors'])[:400])
    else:
        print("  OK ->", json.dumps(d.get('data'))[:400])
