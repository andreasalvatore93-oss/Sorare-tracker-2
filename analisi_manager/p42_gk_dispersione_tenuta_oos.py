"""Test di tenuta out-of-sample del segnale di dispersione sul GK.

Seguito del §11 (RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt) e del cambio di
criterio deciso dall'utente: non piu' "il delta batte le quote con margine",
ma "il segnale produce dispersione VERA correlata al punteggio reale del
portiere" (l'atteso di produzione oggi e' piatto, sd 0,97 contro sd 18,7 del
reale, e la sua correlazione col reale include lo zero: +0,061).

Sui 697 crowss avevo trovato che la debolezza offensiva dell'AVVERSARIO (media
gol fatti, gol veri) correla +0,151 [+0,082; +0,215] col punteggio reale GK.
Qui verifico se REGGE su squadre indipendenti: storico esteso a tutte le 29
squadre dei manager (file gol_squadre_archivio_2025-26), split fra il campione
crowss originale (IN-SAMPLE) e il resto delle squadre nuove (OOS).

Zero query. Nessuna modifica alla produzione.
Uso: python analisi_manager/p42_gk_dispersione_tenuta_oos.py
"""
import os
import sys
import io
import json
import glob
import math
import bisect
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

GOL = 'analisi_manager/dati/gol_squadre_archivio_2025-26_2026-08-11.json'
CAMPIONE = 'analisi_manager/dati/clean_sheet_quote_2026-08-13.json'
CACHE_INDEX = 'analisi_manager/dati/_cache_index_gamelog.json'
MIN_STORICO = 4


def squadre_crowss():
    files = glob.glob('archivio_ufficiale/manager_crowss/pre_2026-08-07/*.json') + \
            glob.glob('archivio_ufficiale/manager_crowss/dal_2026-08-07/*.json')
    giocatori = set()
    for f in files:
        d = json.load(open(f, encoding='utf-8'))
        righe = d['righe'] if isinstance(d, dict) else d
        for riga in righe:
            for c in riga['carte']:
                giocatori.add(c['slug'])
    idx = json.load(open(CACHE_INDEX, encoding='utf-8'))
    return {idx[p]['squadra'] for p in giocatori if p in idx and idx[p].get('squadra')}


def pearson(xs, ys):
    n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
    sxy = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sxx = sum((x-mx)**2 for x in xs); syy = sum((y-my)**2 for y in ys)
    return sxy/math.sqrt(sxx*syy) if sxx and syy else 0.0


def lift(rows, f):
    rs = sorted(rows, key=f); q = len(rs)//5
    if q == 0:
        return None
    return sum(x['reale'] for x in rs[-q:])/q - sum(x['reale'] for x in rs[:q])/q


def boot_cluster(rows, stat, B=2000, seed=11):
    g = collections.defaultdict(list)
    for r in rows:
        g[(r['squadra'], r['fixture'])].append(r)
    ch = list(g)
    rnd = random.Random(seed)
    out = []
    for _ in range(B):
        camp = []
        for _ in range(len(ch)):
            camp.extend(g[ch[rnd.randrange(len(ch))]])
        v = stat(camp)
        if v is not None:
            out.append(v)
    out.sort()
    return out[int(0.025*len(out))], out[int(0.975*len(out))]


def main():
    gol = json.load(open(GOL, encoding='utf-8'))
    print(f'partite nel file gol esteso: {len(gol)}')

    storia = collections.defaultdict(list)   # squadra -> [(data, subiti, fatti)]
    esito = {}                               # (squadra, data) -> (subiti, fatti)
    for g in gol.values():
        h, a, d = g['home'], g['away'], g['date']
        hg, ag = g.get('home_goals'), g.get('away_goals')
        if hg is None or ag is None or not h or not a or not d:
            continue
        storia[h].append((d, ag, hg))
        storia[a].append((d, hg, ag))
        esito[(h, d)] = (ag, hg)
        esito[(a, d)] = (hg, ag)
    for v in storia.values():
        v.sort()
    print(f'squadre con storico: {len(storia)}')

    crowss = squadre_crowss()
    print(f'squadre crowss (in-sample): {len(crowss)}')

    def media_prima(storico, data, campo):
        i = bisect.bisect_left(storico, (data,))
        prec = storico[:i]
        if len(prec) < MIN_STORICO:
            return None
        return sum(r[campo] for r in prec) / len(prec)

    R = json.load(open(CAMPIONE, encoding='utf-8'))
    print(f'campione di valutazione: {len(R)}')

    righe = []
    for r in R:
        sq, avv, data = r['squadra'], r['avversario'], r['data']
        dif = media_prima(storia.get(sq, []), data, 1)      # gol subiti mia squadra
        att = media_prima(storia.get(avv, []), data, 2)      # gol fatti avversario
        if att is None:                                      # il segnale che conta e' l'attacco avv
            continue
        e = esito.get((sq, data))
        y = (e[0] == 0) if e is not None else r['cs']
        righe.append(dict(r, dif_media=dif, att_media=att, y=y,
                          sq_crowss=(sq in crowss)))
    print(f'righe con attacco-avversario calcolabile: {len(righe)}')

    ins = [r for r in righe if r['sq_crowss']]
    oos = [r for r in righe if not r['sq_crowss']]
    print(f'  IN-SAMPLE (squadra crowss): {len(ins)}')
    print(f'  OOS (squadre nuove, indipendenti): {len(oos)}')

    seg_att = lambda r: -r['att_media']      # avv segna meno = segnale piu' alto
    seg_quote = lambda r: r['p_own'] + r['p_draw']
    seg_atteso = lambda r: r['atteso']

    def blocco(nome, rows):
        if len(rows) < 100:
            print(f'\n### {nome} (n={len(rows)}) -- SOTTO 100, non decide.')
            return
        print(f'\n### {nome} (n={len(rows)}) ###')
        for et, f in (('attacco-avv (media gol fatti, neg)', seg_att),
                      ('quote p_own+p_draw', seg_quote),
                      ('atteso di produzione', seg_atteso)):
            reals = [x['reale'] for x in rows]
            sig = [f(x) for x in rows]
            c = pearson(sig, reals)
            icc = boot_cluster(rows, lambda camp: pearson([f(x) for x in camp],
                                                          [x['reale'] for x in camp]))
            lf = lift(rows, f)
            icl = boot_cluster(rows, lambda camp: lift(camp, f))
            print(f'  {et:38s} corr {c:+.3f} [{icc[0]:+.3f},{icc[1]:+.3f}]  '
                  f'lift {lf:+6.2f} [{icl[0]:+6.2f},{icl[1]:+6.2f}]')

    blocco('IN-SAMPLE crowss', ins)
    blocco('OUT-OF-SAMPLE squadre nuove', oos)
    blocco('TUTTO insieme', righe)

    # magnitudine: sd della dispersione "vera" implicata dalla corr OOS
    if len(oos) >= 100:
        sd_reale = (sum((x['reale']-sum(y['reale'] for y in oos)/len(oos))**2
                        for x in oos)/len(oos))**0.5
        c_oos = pearson([seg_att(x) for x in oos], [x['reale'] for x in oos])
        print(f'\nMAGNITUDINE OOS: sd reale {sd_reale:.1f}  corr {c_oos:+.3f}  '
              f'=> dispersione vera catturata ~{abs(c_oos)*sd_reale:.1f} punti')

    out = 'analisi_manager/dati/gk_dispersione_tenuta_2026-08-11.json'
    json.dump([{k: v for k, v in r.items() if k != '_rk'} for r in righe],
              open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
