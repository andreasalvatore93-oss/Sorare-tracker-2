"""Quante arene si possono ricostruire dai file manager gia' in repo?

consiglio_arena.py ha bisogno, per ogni arena, dei punteggi del CAMPO (i nove
avversari), non solo del proprio. Nei manager_*.json ogni riga e' UN
partecipante di UN'arena: se piu' manager capitano nella stessa leaderboard si
puo' ricostruire una parte del campo. Qui si misura quanto.
"""
import collections
import glob
import json
import os

os.chdir(r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2')

per_tipo = collections.Counter()
part_per_lb = collections.defaultdict(set)      # leaderboard -> {(manager, score)}
tipo_di_lb = {}
gw_di_lb = {}

for f in sorted(glob.glob('dati_globali/manager_*.json')):
    try:
        with open(f, encoding='utf-8') as fh:
            d = json.load(fh)
    except Exception:
        continue
    man = d.get('manager') or os.path.basename(f)
    for gw, righe in (d.get('giornate') or {}).items():
        if not isinstance(righe, list):
            continue
        for e in righe:
            if not isinstance(e, dict):
                continue
            lb = e.get('leaderboard')
            comp = e.get('competizione')
            piaz = e.get('piazzamento') or {}
            sc = piaz.get('punteggio')
            if not lb or sc is None:
                continue
            if 'arena' not in (e.get('tipo_arena') or ''):
                continue
            per_tipo[comp] += 1
            part_per_lb[lb].add((man, round(float(sc), 2)))
            tipo_di_lb[lb] = comp
            gw_di_lb[lb] = gw

print("RIGHE ARENA TROVATE NEI FILE MANAGER (un partecipante ciascuna)")
for k, v in per_tipo.most_common():
    print(f"   {str(k):<16}{v:>7}")
print(f"   {'TOTALE':<16}{sum(per_tipo.values()):>7}")

print(f"\nARENE DISTINTE (leaderboard uniche): {len(part_per_lb)}")
dist = collections.Counter(len(v) for v in part_per_lb.values())
print("partecipanti che conosciamo per arena:")
for n in sorted(dist):
    print(f"   {n} partecipant{'e' if n == 1 else 'i'}: {dist[n]} arene")

print("\nARENE PER TIPO (distinte), e quante hanno >=2 partecipanti noti:")
tot = collections.Counter()
multi = collections.Counter()
for lb, part in part_per_lb.items():
    t = tipo_di_lb[lb]
    tot[t] += 1
    if len(part) >= 2:
        multi[t] += 1
for t in tot:
    print(f"   {str(t):<16}{tot[t]:>6} distinte   {multi[t]:>5} con 2+ partecipanti")

print("\nGIORNATE COPERTE:", len(set(gw_di_lb.values())))
