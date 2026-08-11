# -*- coding: utf-8 -*-
"""PASSO 2bis (12/08/2026, Opus esecutore) -- NON committare, NON produzione.

Rifa' il giro dell'orchestratore (_tmp_gk_passo2_pcs_vs_storico.py) ma SALVA
tutte le colonne su disco, cosi' le statistiche che mancavano si calcolano
gratis senza ricostruire ogni volta i checkpoint di modello_partita (che
costano minuti).

In piu' del suo: tiene anche il GRANULARE e il punteggio TOTALE (in produzione
si sceglie il portiere sul totale, non sul livello), la squadra (per l'IC a
grappolo per SQUADRA, non solo per portiere) e la data.

Lancio: python analisi_manager/_tmp_gk_passo2bis_opus.py
Output: analisi_manager/dati/_tmp_gk_passo2bis_rows.json
"""
import os, sys, json, glob, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))
sys.path.insert(0, ROOT)
import test_gk as G
import backtest_arene_previsioni as P

MINH = 6


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
        saves = 0.0
        gc = 0.0
        for e in ds:
            c, s, sv = e.get('category'), e.get('stat'), e.get('statValue') or 0.0
            if c == 'POSITIVE_DECISIVE_STAT':
                pos += sv
            elif c == 'NEGATIVE_DECISIVE_STAT':
                neg += sv
            elif s == 'level_score':
                lvl = e.get('totalScore') or 0.0
            if s == 'saves':
                saves = sv
            elif s == 'goals_conceded':
                gc = sv
        sc = v.get('score')
        if lvl is None or sc is None:
            continue
        out.append(dict(date=gm['date'][:10], score=float(sc), lvl=float(lvl),
                        gran=float(sc) - float(lvl), pos=pos, neg=neg, saves=saves, gc=gc,
                        home=(gm.get('homeTeam') or {}).get('slug'),
                        away=(gm.get('awayTeam') or {}).get('slug')))
    out.sort(key=lambda r: r['date'])
    return out


PLAYERS = {}
for cdir in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*_gk_all', '.cache')):
    lega = cdir.split(os.sep)[-4].replace('formazione_', '')
    for f in glob.glob(os.path.join(cdir, '*_detail_cache.json')):
        ms = leggi_dettaglio(f)
        if ms:
            PLAYERS[(lega, os.path.basename(f).replace('_detail_cache.json', ''))] = ms
print('portieri caricati:', len(PLAYERS), flush=True)


def squadra_da_storico(recenti):
    c = {}
    for m in recenti:
        for t in (m['home'], m['away']):
            if t:
                c[t] = c.get(t, 0) + 1
    return max(c, key=c.get) if c else None


rows = []
n_none = n_squadra_ko = 0
for (lega, slug), ms in PLAYERS.items():
    if len(ms) <= MINH:
        continue
    for i in range(MINH, len(ms)):
        st, tg = ms[:i], ms[i]
        w = G.exponential_weights(len(st), G.HALF_LIFE_GAMES)
        lp = G.weighted_mean([m['pos'] for m in st], w)
        ln = G.weighted_mean([m['neg'] for m in st], w)
        la = G.expected_level_from_rates(lp, ln)
        ga = G.weighted_mean([m['gran'] for m in st], w)
        sav = G.weighted_mean([m['saves'] for m in st], w)
        recenti = st[-5:] if len(st) >= 5 else st
        squadra = squadra_da_storico(recenti)
        home, away = tg['home'], tg['away']
        if not squadra or not home or not away or squadra not in (home, away):
            n_squadra_ko += 1
            continue
        opp = away if squadra == home else home
        casa = (squadra == home)
        try:
            cutoff = datetime.datetime.strptime(tg['date'], '%Y-%m-%d')
        except ValueError:
            continue
        pcs = P._pcs_squadra({'squadra': squadra, 'opp_slug': opp, 'cutoff': cutoff, 'casa': casa})
        if pcs is None:
            n_none += 1
            continue
        rows.append(dict(slug=slug, lega=lega, data=tg['date'], squadra=squadra, opp=opp, casa=casa,
                         lvl_att=la, gran_att=ga, tot_att=la + ga, saves_att=sav, pcs=pcs,
                         lvl_re=tg['lvl'], gran_re=tg['gran'], tot_re=tg['score'],
                         saves_re=tg['saves'], gc_re=tg['gc']))

out = os.path.join(ROOT, 'analisi_manager', 'dati', '_tmp_gk_passo2bis_rows.json')
json.dump(rows, open(out, 'w'), indent=0)
print('righe salvate:', len(rows), '| pcs None:', n_none, '| squadra non risolta:', n_squadra_ko)
print('portieri:', len(set(r['slug'] for r in rows)), '| squadre:', len(set(r['squadra'] for r in rows)))
print('scritto in', out)
