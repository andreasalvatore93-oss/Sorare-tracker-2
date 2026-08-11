"""Clean sheet con GOL VERI al posto del proxy binario (score portiere >=60).

Seguito del §10 di RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt. Li' forza
difensiva/offensiva costruite sul PROXY binario (portiere >=60) fallivano su
tutta la linea (AUC 0,522/0,504, nessun delta positivo contro le quote). La
causa dichiarata al §10.1: "la cache non ha i gol". Ora i gol veri ci sono per
un sottoinsieme (squadre crowss, stagione 2025/26): file
analisi_manager/dati/gol_squadre_crowss_2025-26_2026-08-11.json.

Domanda unica: col MARGINE di gol (segnale continuo) invece del binario CS, le
due forze battono le quote 1X2 sull'AUC del clean sheet?

Tutto walk-forward: per ogni riga si usano SOLO le partite precedenti alla
data. Nessuna query di rete. Nessuna modifica alla produzione.

Uso: python analisi_manager/p41_clean_sheet_gol_veri.py
"""
import os
import sys
import io
import json
import glob
import bisect
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

GOL = 'analisi_manager/dati/gol_squadre_crowss_2025-26_2026-08-11.json'
CAMPIONE = 'analisi_manager/dati/clean_sheet_quote_2026-08-13.json'
CACHE_INDEX = 'analisi_manager/dati/_cache_index_gamelog.json'

MIN_STORICO = 4          # partite precedenti minime perche' una forza valga
PESO_PRIOR = 5.0         # quante "partite finte" vale il prior (shrinkage)


def squadre_crowss():
    """Le 201 squadre con storico COMPLETO (tutte le loro partite estratte).
    Gli avversari non-crowss nel file gol hanno solo le partite contro crowss."""
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


def main():
    gol = json.load(open(GOL, encoding='utf-8'))
    print(f'partite nel file gol: {len(gol)}')

    # storico per squadra: squadra -> [(data, gol_subiti, gol_fatti)]
    storia = collections.defaultdict(list)
    # esito partita per (squadra, data): (gol_subiti, gol_fatti)
    esito = {}
    for g in gol.values():
        h, a, d = g['home'], g['away'], g['date']
        hg, ag = g.get('home_goals'), g.get('away_goals')
        if hg is None or ag is None or not h or not a or not d:
            continue
        storia[h].append((d, ag, hg))   # home subisce ag, fa hg
        storia[a].append((d, hg, ag))   # away subisce hg, fa ag
        esito[(h, d)] = (ag, hg)
        esito[(a, d)] = (hg, ag)
    for v in storia.values():
        v.sort()
    print(f'squadre con storico gol: {len(storia)}')

    crowss = squadre_crowss()
    print(f'squadre crowss (storico completo): {len(crowss)}')

    # tasso base clean sheet vero, dalle partite in archivio
    tot = sum(len(v) for v in storia.values())
    cs_veri = sum(1 for v in storia.values() for (_d, sub, _f) in v if sub == 0)
    PRIOR = cs_veri / tot
    print(f'partite-squadra: {tot}  tasso clean sheet vero: {PRIOR:.1%}')

    def media_prima(storico, data, campo):
        """Media di 'campo' (1=subiti, 2=fatti) STRETTAMENTE prima di 'data'."""
        i = bisect.bisect_left(storico, (data,))
        prec = storico[:i]
        if len(prec) < MIN_STORICO:
            return None
        return sum(r[campo] for r in prec) / len(prec)

    def tasso_zero_prima(storico, data, campo):
        """Tasso di partite con campo==0 prima di 'data', con shrinkage al prior."""
        i = bisect.bisect_left(storico, (data,))
        prec = storico[:i]
        if len(prec) < MIN_STORICO:
            return None
        k = sum(1 for r in prec if r[campo] == 0)
        return (k + PRIOR * PESO_PRIOR) / (len(prec) + PESO_PRIOR)

    R = json.load(open(CAMPIONE, encoding='utf-8'))
    print(f'\ncampione di valutazione originale: {len(R)}')

    righe = []
    disc = {'proxy_si_vero_no': 0, 'proxy_no_vero_si': 0, 'concordi': 0, 'senza_vero': 0}
    for r in R:
        sq, avv, data = r['squadra'], r['avversario'], r['data']
        # forza difensiva della MIA squadra (meno gol subisco = piu' forte)
        dif_media = media_prima(storia.get(sq, []), data, 1)      # gol subiti
        dif_tasso = tasso_zero_prima(storia.get(sq, []), data, 1)  # tasso CS vero
        # debolezza offensiva dell'avversario (meno segna = piu' debole)
        att_media = media_prima(storia.get(avv, []), data, 2)      # gol fatti avv
        att_tasso = tasso_zero_prima(storia.get(avv, []), data, 2)  # tasso avv non segna
        if dif_media is None or att_media is None:
            continue
        # etichetta clean sheet VERA se la partita e' nel file gol
        e = esito.get((sq, data))
        cs_vero = None
        if e is not None:
            cs_vero = (e[0] == 0)
            if cs_vero and r['cs']:
                disc['concordi'] += 1
            elif cs_vero and not r['cs']:
                disc['proxy_no_vero_si'] += 1
            elif not cs_vero and r['cs']:
                disc['proxy_si_vero_no'] += 1
            else:
                disc['concordi'] += 1
        else:
            disc['senza_vero'] += 1
        righe.append(dict(
            r,
            dif_media=dif_media, dif_tasso=dif_tasso,
            att_media=att_media, att_tasso=att_tasso,
            cs_vero=cs_vero,
            avv_crowss=(avv in crowss), sq_crowss=(sq in crowss),
        ))
    print(f'  con entrambe le forze calcolabili ({MIN_STORICO}+ partite prec.): {len(righe)}')
    if len(righe) < 100:
        print('  *** CAMPIONE SOTTO 100: non decide niente (vedi brief §4). ***')

    n_avv_crowss = sum(1 for r in righe if r['avv_crowss'])
    print(f'  di cui avversario crowss (storico avv COMPLETO): {n_avv_crowss}'
          f'   avversario non-crowss (storico avv PARZIALE): {len(righe)-n_avv_crowss}')

    # --- confronto etichetta proxy vs vera ---
    print('\n=== ETICHETTA CLEAN SHEET: PROXY (GK>=60) vs VERA (gol_subiti==0) ===')
    entrambe = disc['concordi'] + disc['proxy_si_vero_no'] + disc['proxy_no_vero_si']
    print(f'  righe con entrambe le etichette: {entrambe}   senza etichetta vera: {disc["senza_vero"]}')
    if entrambe:
        print(f'  concordi: {disc["concordi"]} ({disc["concordi"]/entrambe:.1%})')
        print(f'  proxy dice CS ma VERO no (proxy sovrastima): {disc["proxy_si_vero_no"]}')
        print(f'  proxy dice no ma VERO CS (proxy sottostima): {disc["proxy_no_vero_si"]}')

    # etichetta usata per l'AUC: la VERA dove c'e', altrimenti il proxy
    for r in righe:
        r['y'] = r['cs_vero'] if r['cs_vero'] is not None else r['cs']
    print(f'\n  tasso clean sheet (etichetta usata) nel campione: '
          f'{sum(r["y"] for r in righe)/len(righe):.1%}')

    # --- dump leggibile 10 righe ---
    print('\n=== DUMP 10 RIGHE DEL CAMPIONE FINALE ===')
    print(f'  {"squadra":26s} {"data":10s} {"difMed":>6s} {"difTas":>6s} '
          f'{"attMed":>6s} {"attTas":>6s} {"csPr":>4s} {"csVe":>4s} {"reale":>6s}')
    for r in righe[:10]:
        print(f'  {r["squadra"][:26]:26s} {r["data"]:10s} '
              f'{r["dif_media"]:6.2f} {r["dif_tasso"]:6.2f} '
              f'{r["att_media"]:6.2f} {r["att_tasso"]:6.2f} '
              f'{str(r["cs"]):>4s} {str(r["cs_vero"]):>4s} {r["reale"]:6.1f}')

    if len(righe) < 100:
        json.dump(righe, open('analisi_manager/dati/clean_sheet_gol_veri_2026-08-11.json',
                              'w', encoding='utf-8'), ensure_ascii=False)
        print('\nmi fermo: campione insufficiente per un verdetto.')
        return

    def auc(c):
        pos = sorted(p for y, p in c if y); neg = sorted(p for y, p in c if not y)
        if not pos or not neg:
            return None
        t = 0.0
        for a in pos:
            l = bisect.bisect_left(neg, a)
            t += l + 0.5 * (bisect.bisect_right(neg, a) - l)
        return t / (len(pos) * len(neg))

    def boot_delta(righe, f1, f2, B=2000, seed=20260811):
        rnd = random.Random(seed)
        g = collections.defaultdict(list)
        for r in righe:
            g[(r['squadra'], r['fixture'])].append(r)
        ch = list(g)
        out = []
        for _ in range(B):
            camp = []
            for _ in range(len(ch)):
                camp.extend(g[ch[rnd.randrange(len(ch))]])
            a1 = auc([(x['y'], f1(x)) for x in camp])
            a2 = auc([(x['y'], f2(x)) for x in camp])
            if a1 is not None and a2 is not None:
                out.append(a1 - a2)
        out.sort()
        return out[int(0.025*len(out))], out[int(0.975*len(out))], sum(1 for v in out if v > 0)/len(out)

    def boot_auc(righe, f, B=2000, seed=20260811):
        rnd = random.Random(seed)
        g = collections.defaultdict(list)
        for r in righe:
            g[(r['squadra'], r['fixture'])].append(r)
        ch = list(g)
        out = []
        for _ in range(B):
            camp = []
            for _ in range(len(ch)):
                camp.extend(g[ch[rnd.randrange(len(ch))]])
            a = auc([(x['y'], f(x)) for x in camp])
            if a is not None:
                out.append(a)
        out.sort()
        return out[int(0.025*len(out))], out[int(0.975*len(out))]

    # ranghi per le combinazioni
    rango = {}
    for nome, f in (('dif', lambda r: -r['dif_media']),       # meno subiti = piu' forte
                    ('att', lambda r: -r['att_media']),       # avv segna meno = piu' debole
                    ('odds', lambda r: r['p_own'] + r['p_draw'])):
        ordinati = sorted(righe, key=f)
        for i, r in enumerate(ordinati):
            rango.setdefault(id(r), {})[nome] = i / len(ordinati)

    # NB: i segnali sono orientati perche' AUC alto = segnale alto sui clean sheet.
    #     meno gol subiti/fatti => segnale piu' alto => nego la media.
    segnali = [
        ('atteso di produzione (oggi)', lambda r: r['atteso']),
        ('quote: p_own + p_draw', lambda r: r['p_own'] + r['p_draw']),
        ('forza dif - MEDIA gol subiti', lambda r: -r['dif_media']),
        ('forza dif - TASSO CS vero', lambda r: r['dif_tasso']),
        ('debolezza att avv - MEDIA gol fatti', lambda r: -r['att_media']),
        ('debolezza att avv - TASSO avv non segna', lambda r: r['att_tasso']),
        ('dif+att (media ranghi, gol)', lambda r: rango[id(r)]['dif'] + rango[id(r)]['att']),
        ('dif+att+quote (media ranghi)', lambda r: rango[id(r)]['dif'] + rango[id(r)]['att'] + rango[id(r)]['odds']),
    ]
    print('\n=== AUC SUL CLEAN SHEET (0,50 = a caso) ===')
    for nome, f in segnali:
        lo, hi = boot_auc(righe, f)
        print(f'  {nome:40s} AUC {auc([(r["y"], f(r)) for r in righe]):.3f}  IC95% [{lo:.3f}, {hi:.3f}]')

    print('\n=== DELTA APPAIATO contro le sole quote (bootstrap squadra-giornata) ===')
    base = lambda r: r['p_own'] + r['p_draw']
    for nome, f in segnali[2:]:
        lo, hi, q = boot_delta(righe, f, base)
        d = auc([(r['y'], f(r)) for r in righe]) - auc([(r['y'], base(r)) for r in righe])
        print(f'  {nome:40s} delta {d:+.3f}  IC95% [{lo:+.3f}, {hi:+.3f}]  positivo {q:.1%}')

    print('\n=== LIFT SUL PUNTEGGIO REALE DEL PORTIERE (quintili) ===')
    for nome, f in segnali:
        rs = sorted(righe, key=f); q = len(rs)//5
        print(f'  {nome:40s} basso {sum(x["reale"] for x in rs[:q])/q:5.1f}  '
              f'alto {sum(x["reale"] for x in rs[-q:])/q:5.1f}  '
              f'delta {sum(x["reale"] for x in rs[-q:])/q - sum(x["reale"] for x in rs[:q])/q:+6.2f}')

    # --- solo avversari crowss (storico avversario completo) ---
    solo_avv = [r for r in righe if r['avv_crowss']]
    print(f'\n=== SOTTOCAMPIONE: SOLO AVVERSARI CROWSS (storico avv completo), n={len(solo_avv)} ===')
    if len(solo_avv) >= 100:
        for nome, f in segnali:
            print(f'  {nome:40s} AUC {auc([(r["y"], f(r)) for r in solo_avv]):.3f}')
    else:
        print('  (sotto 100, non riportato)')

    out = 'analisi_manager/dati/clean_sheet_gol_veri_2026-08-11.json'
    json.dump(righe, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
