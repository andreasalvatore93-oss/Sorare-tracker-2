"""Introspezione mirata dello schema Sorare: campi dei tipi che servono per
capire come filtrare le carte per giornata/competizione."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),'formazione_turchia','discovery'))
os.environ.setdefault('MIN_STARTER_ODDS','0')
import turchia_gk_discovery as base

Q = """
query Introspect($name: String!) {
  __type(name: $name) {
    name
    fields { name type { name kind ofType { name kind } } args { name } }
  }
}
"""
for tipo in ('So5Fixture','Card','So5Leaderboard','So5Root'):
    d = base.graphql_query(Q, {"name": tipo}, operation_name="Introspect")
    t = (d.get('data') or {}).get('__type')
    print("\n" + "="*70)
    print("TIPO:", tipo)
    if not t:
        print("  non trovato", json.dumps(d.get('errors') or [])[:200]); continue
    for f in (t.get('fields') or []):
        ty = f['type']; nm = ty.get('name') or (ty.get('ofType') or {}).get('name')
        args = ",".join(a['name'] for a in (f.get('args') or []))
        interessante = any(k in f['name'].lower() for k in
                           ('competition','leaderboard','fixture','eligib','game','league'))
        if tipo in ('So5Fixture','So5Root') or interessante:
            print(f"  {f['name']:<38} {nm or '?':<26} args({args})")
