"""Script temporaneo di misura (non di produzione, non committare).
Confronta scelta capitano per _cal (oggi) vs _zgrade puro vs _combinato,
sulle 1.145 arene con capitano di archivio_ufficiale/aggregato/binario2_out.json (ris_A).
"""
import os, json, random, statistics, collections

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)

GK_CAPTAIN_MARGIN = 6.7

out = json.load(open('archivio_ufficiale/aggregato/binario2_out.json', encoding='utf-8'))
pool_rows = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json', encoding='utf-8'))

idx = {}
for r in pool_rows:
    idx.setdefault((r['manager'], r['fixture'], r['slug']), []).append(r)

arene = []
n_arene_con_cap = 0
buchi = 0
for e in out['per_gw']:
    manager, fx = e['manager'], e['fixture']
    for a in e['ris_A']:
        carte = a['carte']
        if not any(c['capitano'] for c in carte):
            continue
        n_arene_con_cap += 1
        righe = []
        ok = True
        for c in carte:
            cands = idx.get((manager, fx, c['slug']))
            if not cands:
                ok = False
                buchi += 1
                continue
            r = cands[0]  # join 1:1 assunto, verificato sotto
            righe.append({**r, 'capitano_oggi': c['capitano']})
        if not ok or len(righe) != 5:
            buchi += 1
            continue
        arene.append({'manager': manager, 'fixture': fx, 'carte': righe})

print('n arene con capitano (ris_A):', n_arene_con_cap)
print('n arene con join completo (5/5):', len(arene))
print('buchi join:', buchi)

def bonus(cap_row):
    return 0.2 * cap_row['reale']

def scegli_cal(righe):
    fuori = [r for r in righe if r['codice'] != 'GK']
    gk = [r for r in righe if r['codice'] == 'GK']
    bo = max(fuori, key=lambda r: r['_cal']) if fuori else None
    bg = max(gk, key=lambda r: r['_cal']) if gk else None
    if bg and (not bo or bg['_cal'] >= bo['_cal'] + GK_CAPTAIN_MARGIN):
        return bg
    return bo or bg

def scegli_zgrade(righe):
    fuori = [r for r in righe if r['codice'] != 'GK']
    gk = [r for r in righe if r['codice'] == 'GK']
    bo = max(fuori, key=lambda r: r['_zgrade']) if fuori else None
    bg = max(gk, key=lambda r: r['_zgrade']) if gk else None
    if bg and (not bo or bg['_zgrade'] >= bo['_zgrade'] + GK_CAPTAIN_MARGIN):
        return bg
    return bo or bg

def scegli_combinato(righe):
    fuori = [r for r in righe if r['codice'] != 'GK']
    gk = [r for r in righe if r['codice'] == 'GK']
    bo = max(fuori, key=lambda r: r['_combinato']) if fuori else None
    bg = max(gk, key=lambda r: r['_combinato']) if gk else None
    if bg and (not bo or bg['_combinato'] >= bo['_combinato'] + GK_CAPTAIN_MARGIN):
        return bg
    return bo or bg

def scegli_oggi(righe):
    return next(r for r in righe if r['capitano_oggi'])

def scegli_senno(righe):
    return max(righe, key=lambda r: r['reale'])

random.seed(42)

def valuta(nome, fn, per_manager=None):
    tot = 0.0
    vals = []
    per_mgr = collections.defaultdict(list)
    for a in arene:
        cap = fn(a['carte'])
        b = bonus(cap)
        tot += b
        vals.append(b)
        per_mgr[a['manager']].append(b)
    media = tot / len(arene)
    return media, vals, per_mgr

# baseline: capitano oggi (dalla produzione, campo 'capitano' nell'archivio)
media_oggi, vals_oggi, mgr_oggi = valuta('oggi', scegli_oggi)
# a caso: media dei 5 possibili (esatta, non simulata)
def media_a_caso(righe):
    return sum(bonus(r) for r in righe) / len(righe)
tot_caso = sum(media_a_caso(a['carte']) for a in arene) / len(arene)
# senno di poi
media_senno, vals_senno, mgr_senno = valuta('senno', scegli_senno)
# ricalcolo _cal (test A/A)
media_cal, vals_cal, mgr_cal = valuta('cal', scegli_cal)
# varianti
media_zg, vals_zg, mgr_zg = valuta('zgrade', scegli_zgrade)
media_comb, vals_comb, mgr_comb = valuta('combinato', scegli_combinato)

print()
print('CONTROLLO A/A: media bonus oggi (dal campo capitano prod) =', round(media_oggi, 4))
print('CONTROLLO A/A: media bonus ricalcolato per _cal            =', round(media_cal, 4))
print('media a caso (esatta)                                     =', round(tot_caso, 4))
print('media senno di poi                                        =', round(media_senno, 4))
print()

guad_oggi = media_oggi - tot_caso
guad_cal = media_cal - tot_caso
guad_zg = media_zg - tot_caso
guad_comb = media_comb - tot_caso
guad_senno = media_senno - tot_caso

print(f'oggi(prod):  bonus/arena={media_oggi:.4f}  guadagno={guad_oggi:.4f}  %max={100*guad_oggi/guad_senno:.1f}')
print(f'A/A _cal:    bonus/arena={media_cal:.4f}  guadagno={guad_cal:.4f}  %max={100*guad_cal/guad_senno:.1f}')
print(f'(a) zgrade:  bonus/arena={media_zg:.4f}  guadagno={guad_zg:.4f}  %max={100*guad_zg/guad_senno:.1f}')
print(f'(b) combin.: bonus/arena={media_comb:.4f}  guadagno={guad_comb:.4f}  %max={100*guad_comb/guad_senno:.1f}')
print(f'senno poi:   bonus/arena={media_senno:.4f}  guadagno={guad_senno:.4f}  %max=100.0')

# t-test appaiato: combinato vs cal, su 1145 arene
def paired_t(a_vals, b_vals):
    d = [x - y for x, y in zip(a_vals, b_vals)]
    n = len(d)
    md = statistics.mean(d)
    sd = statistics.stdev(d)
    se = sd / (n ** 0.5)
    t = md / se if se > 0 else float('nan')
    return md, t, n

md, t, n = paired_t(vals_comb, vals_cal)
print()
print(f'delta combinato vs cal (appaiato su {n} arene): media={md:.4f}  t={t:.2f}')
md2, t2, n2 = paired_t(vals_zg, vals_cal)
print(f'delta zgrade vs cal (appaiato su {n2} arene): media={md2:.4f}  t={t2:.2f}')

# bootstrap cluster manager per combinato vs cal
def bootstrap_cluster(per_mgr_a, per_mgr_b, iters=2000):
    managers = list(per_mgr_a.keys())
    diffs = []
    for _ in range(iters):
        sample = [random.choice(managers) for _ in managers]
        tot_a = sum(sum(per_mgr_a[m]) for m in sample)
        tot_b = sum(sum(per_mgr_b[m]) for m in sample)
        n_a = sum(len(per_mgr_a[m]) for m in sample)
        n_b = sum(len(per_mgr_b[m]) for m in sample)
        diffs.append(tot_a / n_a - tot_b / n_b)
    diffs.sort()
    lo = diffs[int(0.025 * iters)]
    hi = diffs[int(0.975 * iters)]
    return lo, hi

lo, hi = bootstrap_cluster(mgr_comb, mgr_cal)
print(f'bootstrap cluster-manager (combinato - cal), IC95: [{lo:.4f}, {hi:.4f}]')

print()
print('=== DUMP 10 ARENE ===')
for a in arene[:10]:
    print(f"--- {a['manager']} {a['fixture']} ---")
    for r in a['carte']:
        marks = []
        if r['capitano_oggi']:
            marks.append('OGGI')
        if r is scegli_zgrade(a['carte']):
            marks.append('ZGRADE')
        if r is scegli_combinato(a['carte']):
            marks.append('COMBINATO')
        if r is scegli_senno(a['carte']):
            marks.append('SENNO')
        print(f"  {r['slug']:30s} {r['codice']:4s} _cal={r['_cal']:.2f} _grade={r['_grade']} "
              f"_zgrade={r['_zgrade']:.2f} _combinato={r['_combinato']:.2f} reale={r['reale']:.1f}  {' '.join(marks)}")
