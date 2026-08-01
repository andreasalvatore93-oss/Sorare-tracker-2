import glob, json, os, collections, statistics

viste = collections.defaultdict(collections.Counter)
righe = []
for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
    slug = os.path.basename(path).replace('_detail_cache.json', '')
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    for v in d.values():
        if not isinstance(v, dict) or v.get('scoreStatus') != 'FINAL':
            continue
        g = v.get('anyGame') or {}
        h = (g.get('homeTeam') or {}).get('slug')
        a = (g.get('awayTeam') or {}).get('slug')
        if not (h and a) or v.get('score') is None:
            continue
        viste[slug][h] += 1
        viste[slug][a] += 1
        righe.append((slug, v['score']))

club_di = {s: c.most_common(1)[0][0] for s, c in viste.items() if c}
punteggi = collections.defaultdict(list)
for slug, sc in righe:
    c = club_di.get(slug)
    if c:
        punteggi[c].append(sc)
forza = {c: statistics.mean(v) for c, v in punteggi.items() if len(v) >= 30}
ordina = sorted(forza.items(), key=lambda x: -x[1])
print('PIU FORTI:')
for c, f in ordina[:5]:
    print(f'   {f:5.1f}  {c}')
print('PIU DEBOLI:')
for c, f in ordina[-5:]:
    print(f'   {f:5.1f}  {c}')
json.dump({c: round(f, 2) for c, f in forza.items()},
          open('forza_rosa.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'\nsalvato forza_rosa.json con {len(forza)} club')
