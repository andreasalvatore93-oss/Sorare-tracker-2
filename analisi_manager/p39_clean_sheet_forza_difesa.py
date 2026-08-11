"""Clean sheet: si prevede meglio con forza-difesa e forza-attacco?

Seguito del §9 di RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt. Le quote 1X2 gia'
in repo danno AUC 0,585: dicono chi VINCE, non chi non SUBISCE. Qui provo a
costruire i due ingredienti veri del clean sheet, ex ante e senza rete:
  - quanto la MIA squadra tiene la porta inviolata (forza difensiva);
  - quanto l'AVVERSARIO fallisce nel segnare (debolezza offensiva).

RETTIFICA A UNA MIA AFFERMAZIONE (13/08, §9.5): avevo scritto che i "gol
subiti" sono ricavabili dalla cache game-log. E' FALSO: la cache contiene
solo fieldStatus, gameStarted, minsPlayed, yellowCard, footballPlayingStatus
Odds -- nessun gol, ne' fatti ne' subiti. Verificato su 20.011 entry.
Si puo' pero' ricavare l'EVENTO clean sheet, che e' cio' che serve davvero:
il punteggio del portiere di una squadra dice se quella squadra ha tenuto la
porta inviolata (soglia 60, level_score GK 35 senza / 60 con). Da li' si
costruiscono entrambe le forze, sull'evento binario invece che sui gol.

Tutto walk-forward: per ogni partita si usano SOLO le partite precedenti.
Nessuna query di rete. Nessuna modifica alla produzione.

Uso: python analisi_manager/p39_clean_sheet_forza_difesa.py
"""
import os
import sys
import io
import json
import bisect
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

CS_SOGLIA = 60.0
MIN_STORICO = 4          # partite precedenti minime perche' una forza valga
PRIOR = 0.29             # tasso base di clean sheet misurato in archivio
PESO_PRIOR = 5.0         # quante "partite finte" vale il prior (shrinkage)


def carica_indice():
    p = 'analisi_manager/dati/_cache_index_gamelog.json'
    if not os.path.exists(p):
        print('manca _cache_index_gamelog.json: lancia prima p36_correlazioni_compagni.py')
        sys.exit(1)
    return json.load(open(p, encoding='utf-8'))


def tabella_clean_sheet(idx):
    """(squadra, data) -> True/False, da TUTTA la cache, non solo dall'archivio.

    Il portiere di una squadra dice se quella squadra ha tenuto la porta
    inviolata. Se in cache ci sono piu' portieri della stessa squadra nella
    stessa partita (carte diverse, stesso uomo o secondo portiere entrato),
    vince chi ha giocato piu' minuti.
    """
    best = {}
    for slug, v in idx.items():
        squadra = v.get('squadra')
        if not squadra:
            continue
        for data, (score, mins, casa, fuori) in v['partite'].items():
            if score is None or not mins:
                continue
            # solo portieri: li riconosco dal fatto che il ruolo non e' nella
            # cache -- uso il filtro a valle (vedi carica_portieri)
            k = (slug, squadra, data, casa, fuori)
            best[k] = (score, mins)
    return best


def main():
    idx = carica_indice()
    print(f'giocatori in cache: {len(idx)}')

    # i ruoli non sono nella cache: prendo i portieri noti dal pool
    # dell'archivio (codice GK) e li estendo a TUTTE le loro partite in cache
    pool = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json',
                          encoding='utf-8'))
    gk_slugs = {r['slug'] for r in pool if r['codice'] == 'GK'}
    print(f'portieri identificati dall\'archivio: {len(gk_slugs)}')

    # tabella partita -> clean sheet delle due squadre
    cs = {}          # (squadra, data) -> bool
    avversario = {}  # (squadra, data) -> squadra avversaria
    for slug in gk_slugs:
        v = idx.get(slug)
        if not v or not v.get('squadra'):
            continue
        sq = v['squadra']
        for data, (score, mins, casa, fuori) in v['partite'].items():
            if score is None or not mins:
                continue
            k = (sq, data)
            # se due portieri della stessa squadra, tengo il punteggio piu' alto
            # (il titolare che ha finito la partita)
            if k not in cs or score > cs[k][1]:
                cs[k] = (score >= CS_SOGLIA, score)
            avversario[k] = fuori if sq == casa else casa
    print(f'partite-squadra con esito clean sheet ricostruito: {len(cs)}')
    date_tot = sorted({d for _s, d in cs})
    print(f'  finestra: {date_tot[0]} -> {date_tot[-1]}')
    print(f'  tasso clean sheet complessivo: '
          f'{sum(1 for v in cs.values() if v[0])/len(cs):.1%}')

    # storico per squadra, ordinato per data
    per_squadra = collections.defaultdict(list)   # squadra -> [(data, cs)]
    for (sq, d), (val, _s) in cs.items():
        per_squadra[sq].append((d, val))
    for v in per_squadra.values():
        v.sort()
    print(f'squadre con storico: {len(per_squadra)}  '
          f'partite medie per squadra: {sum(len(v) for v in per_squadra.values())/len(per_squadra):.1f}')

    # "quante volte NON sono riuscito a segnare" = clean sheet dell'avversario
    non_segna = collections.defaultdict(list)     # squadra -> [(data, avversario_ha_fatto_cs)]
    for (sq, d), avv in avversario.items():
        v = cs.get((avv, d))
        if v is not None:
            non_segna[sq].append((d, v[0]))
    for v in non_segna.values():
        v.sort()

    def tasso_prima(storico, data):
        """Tasso storico STRETTAMENTE prima di 'data', con shrinkage verso il
        tasso base: senza shrinkage una squadra con 5 partite e 5 clean sheet
        varrebbe 1,00 e dominerebbe l'ordinamento."""
        i = bisect.bisect_left(storico, (data,))
        prec = storico[:i]
        if len(prec) < MIN_STORICO:
            return None
        k = sum(1 for _d, v in prec if v)
        return (k + PRIOR * PESO_PRIOR) / (len(prec) + PESO_PRIOR)

    # campione: i portieri con quote, gia' preparato da p38
    R = json.load(open('analisi_manager/dati/clean_sheet_quote_2026-08-13.json',
                       encoding='utf-8'))
    print(f'\ncampione di valutazione (portieri con quote): {len(R)}')
    righe = []
    for r in R:
        dif = tasso_prima(per_squadra.get(r['squadra'], []), r['data'])
        att = tasso_prima(non_segna.get(r['avversario'], []), r['data'])
        if dif is None or att is None:
            continue
        righe.append(dict(r, forza_dif=dif, debolezza_att_avv=att))
    print(f'  con entrambe le forze calcolabili ({MIN_STORICO}+ partite precedenti): {len(righe)}')
    if len(righe) < 100:
        print('  campione insufficiente')
        return
    print(f'  tasso clean sheet nel campione: '
          f'{sum(r["cs"] for r in righe)/len(righe):.1%}')

    def auc(c):
        pos = sorted(p for y, p in c if y); neg = sorted(p for y, p in c if not y)
        if not pos or not neg:
            return None
        t = 0.0
        for a in pos:
            l = bisect.bisect_left(neg, a)
            t += l + 0.5 * (bisect.bisect_right(neg, a) - l)
        return t / (len(pos) * len(neg))

    def boot_delta(righe, f1, f2, B=2000, seed=20260813):
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
            a1 = auc([(x['cs'], f1(x)) for x in camp])
            a2 = auc([(x['cs'], f2(x)) for x in camp])
            if a1 is not None and a2 is not None:
                out.append(a1 - a2)
        out.sort()
        return out[int(0.025*len(out))], out[int(0.975*len(out))], sum(1 for v in out if v > 0)/len(out)

    rango = {}
    for nome, f in (('dif', lambda r: r['forza_dif']),
                    ('att', lambda r: r['debolezza_att_avv']),
                    ('odds', lambda r: r['p_own'] + r['p_draw'])):
        ordinati = sorted(righe, key=f)
        for i, r in enumerate(ordinati):
            rango.setdefault(id(r), {})[nome] = i / len(ordinati)

    segnali = [
        ('atteso di produzione (oggi)', lambda r: r['atteso']),
        ('quote: p_own + p_draw', lambda r: r['p_own'] + r['p_draw']),
        ('forza difensiva mia squadra', lambda r: r['forza_dif']),
        ('debolezza offensiva avversario', lambda r: r['debolezza_att_avv']),
        ('difesa + attacco (media ranghi)', lambda r: rango[id(r)]['dif'] + rango[id(r)]['att']),
        ('difesa + attacco + quote', lambda r: rango[id(r)]['dif'] + rango[id(r)]['att'] + rango[id(r)]['odds']),
    ]
    print('\n=== AUC SUL CLEAN SHEET (0,50 = a caso) ===')
    for nome, f in segnali:
        print(f'  {nome:36s} AUC {auc([(r["cs"], f(r)) for r in righe]):.3f}')

    print('\n=== DELTA APPAIATO contro le sole quote (bootstrap squadra-giornata) ===')
    base = lambda r: r['p_own'] + r['p_draw']
    for nome, f in segnali[2:]:
        lo, hi, q = boot_delta(righe, f, base)
        d = auc([(r['cs'], f(r)) for r in righe]) - auc([(r['cs'], base(r)) for r in righe])
        print(f'  {nome:36s} delta {d:+.3f}  IC95% [{lo:+.3f}, {hi:+.3f}]  positivo {q:.1%}')

    print('\n=== LIFT SUL PUNTEGGIO REALE DEL PORTIERE (quintili) ===')
    for nome, f in segnali:
        rs = sorted(righe, key=f); q = len(rs)//5
        print(f'  {nome:36s} basso {sum(x["reale"] for x in rs[:q])/q:5.1f}  '
              f'alto {sum(x["reale"] for x in rs[-q:])/q:5.1f}  '
              f'delta {sum(x["reale"] for x in rs[-q:])/q - sum(x["reale"] for x in rs[:q])/q:+6.2f}')

    out = 'analisi_manager/dati/clean_sheet_forze_2026-08-13.json'
    json.dump(righe, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\nsalvato: {out}')


if __name__ == '__main__':
    main()
