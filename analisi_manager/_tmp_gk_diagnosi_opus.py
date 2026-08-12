# -*- coding: utf-8 -*-
"""TEMPORANEO (12/08/2026, Opus esecutore) — NON committare, NON produzione.

Cinque controlli sul filone "il portiere non lo prevediamo", tutti LOCALI
(zero query di rete): leggono solo le cache dettaglio gia' in repo e
l'aggregato binario2. Riusano le funzioni di produzione di
formazione_mls/predict/test_gk.py.

  1. identita' netto -> level_score sulle partite GK reali (il pezzo 'b' e'
     estratto giusto?)
  2. composizione vera degli eventi decisivi del portiere (cos'e' il pezzo 'b')
  3. monotonia di expected_level_from_rates (puo' invertire un segno?)
  4. campione pool: duplicazione righe, correlazione deduplicata, IC95 a
     grappolo per giocatore (per tutti e 4 i ruoli)
  5. campione indipendente walk-forward dalla cache: ogni pezzo del modello
     contro il pezzo di punteggio che dovrebbe prevedere, + placebo
     (ordine partite mescolato) + sweep half-life

Lancio: python analisi_manager/_tmp_gk_diagnosi_opus.py   (~2 minuti)
"""
import os, sys, json, glob, math, random, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))
import test_gk as G

random.seed(12)
MINH = 6


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def ic_grappolo(rows, ka, kb, kcluster, giri=1000):
    """IC95 bootstrap ricampionando i GIOCATORI (non le righe): righe dello
    stesso giocatore non sono osservazioni indipendenti."""
    byc = collections.defaultdict(list)
    for r in rows:
        byc[r[kcluster]].append(r)
    cl = list(byc)
    out = []
    for _ in range(giri):
        s = []
        for _ in range(len(cl)):
            s += byc[random.choice(cl)]
        v = corr([r[ka] for r in s], [r[kb] for r in s])
        if v is not None:
            out.append(v)
    out.sort()
    return out[int(.025 * len(out))], out[int(.975 * len(out))]


def leggi_dettaglio(path):
    try:
        dd = json.load(open(path, encoding='utf-8'))
    except Exception:
        return []
    out = []
    for v in dd.values():
        ds = v.get('detailedScore') or []
        if not ds or v.get('scoreStatus') != 'FINAL':
            continue
        gm = v.get('anyGame') or {}
        if not gm.get('date'):
            continue
        pos = neg = 0.0
        lvl = None
        det = {}
        for e in ds:
            c, s, sv = e.get('category'), e.get('stat'), e.get('statValue') or 0.0
            if c == 'POSITIVE_DECISIVE_STAT':
                pos += sv
                if sv:
                    det[s] = det.get(s, 0) + sv
            elif c == 'NEGATIVE_DECISIVE_STAT':
                neg += sv
                if sv:
                    det[s] = det.get(s, 0) + sv
            elif s == 'level_score':
                lvl = e.get('totalScore') or 0.0
        sc = v.get('score')
        if lvl is None or sc is None:
            continue
        out.append(dict(date=gm['date'][:10], score=float(sc), lvl=float(lvl),
                        gran=float(sc) - float(lvl), pos=pos, neg=neg, det=det))
    out.sort(key=lambda r: r['date'])
    return out


print('Carico le cache dettaglio GK...')
PLAYERS = {}
for cdir in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*_gk_all', '.cache')):
    lega = cdir.split(os.sep)[-4].replace('formazione_', '')
    for f in glob.glob(os.path.join(cdir, '*_detail_cache.json')):
        ms = leggi_dettaglio(f)
        if ms:
            PLAYERS[(lega, os.path.basename(f).replace('_detail_cache.json', ''))] = ms
TUTTE = [(k, m) for k, ms in PLAYERS.items() for m in ms]
print('  %d portieri, %d partite con dettaglio, %d leghe\n'
      % (len(PLAYERS), len(TUTTE), len(set(k[0] for k in PLAYERS))))

print('=== 1. IDENTITA netto_to_level(pos-neg) == level_score ===')
ok = sum(1 for k, m in TUTTE if abs(G.netto_to_level(m['pos'] - m['neg']) - m['lvl']) < 1e-6)
print('  %d/%d (%.1f%%) -> estrazione del pezzo (b) CORRETTA\n' % (ok, len(TUTTE), 100 * ok / len(TUTTE)))

print('=== 1bis. DUMP LEGGIBILE (10 partite vere) ===')
print('  %-22s %-10s %-4s %-4s %-6s %-6s %-6s  eventi' % ('portiere', 'data', 'pos', 'neg', 'level', 'gran', 'tot'))
for k, m in TUTTE[::len(TUTTE) // 10][:10]:
    print('  %-22s %-10s %-4g %-4g %-6.0f %-6.1f %-6.1f  %s'
          % (k[1][:22], m['date'], m['pos'], m['neg'], m['lvl'], m['gran'], m['score'], m['det'] or '-'))
print()

print('=== 2. COSA SONO DAVVERO GLI EVENTI DECISIVI DEL PORTIERE ===')
pc, nc = collections.Counter(), collections.Counter()
for k, m in TUTTE:
    for s, v in m['det'].items():
        (pc if s in ('goals', 'goal_assist', 'assist_penalty_won', 'clearance_off_line',
                     'last_man_tackle', 'penalty_save', 'clean_sheet_60') else nc)[s] += v
tp, tn = sum(pc.values()), sum(nc.values())
print('  POSITIVI:', [(s, '%.0f%%' % (100 * v / tp)) for s, v in pc.most_common()])
print('  NEGATIVI:', [(s, '%.0f%%' % (100 * v / tn)) for s, v in nc.most_common()])
print('  -> NON sono "parate/gol subiti": saves e goals_conceded stanno nel GRANULARE.\n')

print('=== 3. expected_level_from_rates PUO INVERTIRE UN SEGNO? ===')
print('  lam_pos (lam_neg=0.05):', ' '.join('%.1f->%.1f' % (lp, G.expected_level_from_rates(lp, 0.05))
                                            for lp in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)))
print('  lam_neg (lam_pos=0.35):', ' '.join('%.2f->%.1f' % (ln, G.expected_level_from_rates(0.35, ln))
                                            for ln in (0.0, 0.1, 0.2, 0.4)))
print('  -> crescente in lam_pos, decrescente in lam_neg: monotona, non puo invertire un segno.\n')

print('=== 4. CAMPIONE POOL (binario2_pool_rows): duplicazione e IC veri ===')
d = json.load(open(os.path.join(ROOT, 'archivio_ufficiale', 'aggregato', 'binario2_pool_rows.json'), encoding='utf-8'))
print('  ruolo | n righe | corr righe | n coppie uniche | corr dedup | IC95 a grappolo | giocatori')
for cod in ('GK', 'DEF', 'MID', 'FWD'):
    r = [x for x in d if x['codice'] == cod and x.get('_cal') is not None and x.get('reale') is not None]
    g = collections.defaultdict(list)
    for x in r:
        g[(x['slug'], x['fixture'])].append(x)
    ded = [dict(slug=k[0], a=sum(z['_cal'] for z in v) / len(v), r=v[0]['reale']) for k, v in g.items()]
    lo, hi = ic_grappolo(ded, 'a', 'r', 'slug')
    print('  %-5s | %5d | %+.4f | %5d | %+.4f | [%+.4f, %+.4f] | %d'
          % (cod, len(r), corr([x['_cal'] for x in r], [x['reale'] for x in r]), len(ded),
             corr([x['a'] for x in ded], [x['r'] for x in ded]), lo, hi, len(set(x['slug'] for x in ded))))
print('  (IC95 ingenuo su 1932 righe = +-%.4f: sottostima, le righe non sono indipendenti)\n' % (1.96 / math.sqrt(1932)))


def walk(hl, players):
    out = []
    for k, ms in players.items():
        for i in range(MINH, len(ms)):
            st, tg = ms[:i], ms[i]
            w = G.exponential_weights(len(st), hl)
            lp = G.weighted_mean([m['pos'] for m in st], w)
            ln = G.weighted_mean([m['neg'] for m in st], w)
            la = G.expected_level_from_rates(lp, ln)
            ga = G.weighted_mean([m['gran'] for m in st], w)
            out.append(dict(slug=k[1], lega=k[0], lvl_att=la, gran_att=ga, tot_att=la + ga,
                            lvl_re=tg['lvl'], gran_re=tg['gran'], tot_re=tg['score']))
    return out


def dentro_giocatore(rows):
    per = collections.defaultdict(list)
    for r in rows:
        per[r['slug']].append(r)
    a, b = [], []
    for slug, rs in per.items():
        if len(rs) < 4:
            continue
        ma = sum(x['tot_att'] for x in rs) / len(rs)
        mr = sum(x['tot_re'] for x in rs) / len(rs)
        for x in rs:
            a.append(x['tot_att'] - ma)
            b.append(x['tot_re'] - mr)
    return corr(a, b)


print('=== 5. CAMPIONE INDIPENDENTE walk-forward dalla cache (hl=%g di produzione) ===' % G.HALF_LIFE_GAMES)
P6 = {k: v for k, v in PLAYERS.items() if len(v) > MINH}
rows = walk(G.HALF_LIFE_GAMES, P6)
print('  n=%d punti, %d portieri, %d leghe' % (rows and len(rows), len(set(r['slug'] for r in rows)),
                                               len(set(r['lega'] for r in rows))))
for a, b in (('lvl_att', 'lvl_re'), ('gran_att', 'gran_re'), ('lvl_att', 'tot_re'), ('tot_att', 'tot_re')):
    lo, hi = ic_grappolo(rows, a, b, 'slug')
    print('  corr(%-8s, %-7s) = %+.4f  IC95 a grappolo [%+.4f, %+.4f]'
          % (a, b, corr([r[a] for r in rows], [r[b] for r in rows]), lo, hi))
print()
vero = dentro_giocatore(rows)
pl = [dentro_giocatore(walk(G.HALF_LIFE_GAMES, {k: random.sample(v, len(v)) for k, v in P6.items()}))
      for _ in range(20)]
print('  dentro-giocatore: vero %+.4f | PLACEBO (ordine mescolato) %+.4f'
      % (vero, sum(pl) / len(pl)))
print('  -> il negativo dentro-giocatore e MECCANICO (demeaning), non "il modello insegue le serie calde".\n')

print('  sweep half-life (stesso campione, cambia solo hl):')
for hl in (3.0, 6.0, 12.0, 30.0, 1000.0):
    rr = walk(hl, P6)
    mae = sum(abs(r['tot_att'] - r['tot_re']) for r in rr) / len(rr)
    print('    hl=%-6.0f corr %+.4f | MAE %.3f' % (hl, corr([r['tot_att'] for r in rr], [r['tot_re'] for r in rr]), mae))
