"""Terzo blocco di tenuta OOS per il segnale attacco-avversario/GK, stavolta
indipendente per TEMPO (stagione 2024/25) invece che per squadra (§11.8/11.9
di RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt erano squadra-based, n troppo
piccolo per un IC che escluda lo zero). Eseguito dall'orchestratore, non da
Opus (costo).

Metodo IDENTICO a p42_gk_dispersione_tenuta_oos.py (stessa corr Pearson,
stesso bootstrap cluster squadra-giornata, stesso MIN_STORICO=4), ma:
- campione di valutazione NON dall'archivio arene (che copre solo 2026):
  ogni carta GK nota (stesso elenco 'codice'=='GK' di binario2_pool_rows.json)
  con una partita reale nella stagione 2024/25 (2024-08-01 -> 2025-07-31),
  punteggio gia' in cache (zero query);
- storico attacco-avversario walk-forward costruito su TUTTA la storia gol
  disponibile (2023-08-01 -> oggi, uniendo i due file estratti), non solo
  sulla finestra di valutazione.

Uso: python analisi_manager/p44_gk_tenuta_2024_25.py
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

CACHE_INDEX = 'analisi_manager/dati/_cache_index_gamelog.json'
POOL = 'archivio_ufficiale/aggregato/binario2_pool_rows.json'
GOL_FILES = sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2025-26_*.json')) + \
            sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2023_25_*.json'))
EVAL_INIZIO = '2024-08-01'
EVAL_FINE = '2025-07-31'
MIN_STORICO = 4


def pearson(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def boot_cluster(rows, stat, chiave, B=2000, seed=44):
    g = collections.defaultdict(list)
    for r in rows:
        g[chiave(r)].append(r)
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
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def main():
    print(f"file gol usati: {GOL_FILES}")
    storia = collections.defaultdict(list)   # squadra -> [(data, subiti, fatti)]
    esito = {}                                # (squadra, data) -> (subiti, fatti)
    n_partite = 0
    for gf in GOL_FILES:
        gol = json.load(open(gf, encoding='utf-8'))
        for g in gol.values():
            h, a, d = g.get('home'), g.get('away'), g.get('date')
            hg, ag = g.get('home_goals'), g.get('away_goals')
            if hg is None or ag is None or not h or not a or not d:
                continue
            storia[h].append((d, ag, hg))
            storia[a].append((d, hg, ag))
            esito[(h, d)] = (ag, hg)
            esito[(a, d)] = (hg, ag)
            n_partite += 1
    for v in storia.values():
        v.sort()
    print(f"partite totali unite: {n_partite}  squadre con storico: {len(storia)}")

    idx = json.load(open(CACHE_INDEX, encoding='utf-8'))
    pool = json.load(open(POOL, encoding='utf-8'))
    gk_slugs = {r['slug'] for r in pool if r['codice'] == 'GK'}
    print(f"portieri noti dal pool: {len(gk_slugs)}")

    def media_prima(storico, data, campo):
        i = bisect.bisect_left(storico, (data,))
        prec = storico[:i]
        if len(prec) < MIN_STORICO:
            return None
        return sum(r[campo] for r in prec) / len(prec)

    righe = []
    scartate_squadra = 0
    scartate_avv_storico = 0
    for slug in gk_slugs:
        v = idx.get(slug)
        if not v or not v.get('squadra'):
            continue
        sq = v['squadra']
        for data, entry in v['partite'].items():
            if data < EVAL_INIZIO or data > EVAL_FINE:
                continue
            score, mins, casa, fuori = entry
            if score is None or not mins:
                continue
            if casa != sq and fuori != sq:
                scartate_squadra += 1
                continue
            avv = fuori if casa == sq else casa
            att = media_prima(storia.get(avv, []), data, 2)
            if att is None:
                scartate_avv_storico += 1
                continue
            dif = media_prima(storia.get(sq, []), data, 1)
            e = esito.get((sq, data))
            y = (e[0] == 0) if e is not None else None
            righe.append({'slug': slug, 'squadra': sq, 'avversario': avv, 'data': data,
                          'reale': score, 'att_media': att, 'dif_media': dif, 'y': y})
    print(f"righe GK stagione 2024/25 con attacco-avv calcolabile: {len(righe)}")
    print(f"  scartate (squadra non risolta nel match): {scartate_squadra}")
    print(f"  scartate (storico avversario < {MIN_STORICO}): {scartate_avv_storico}")

    if len(righe) < 100:
        print("SOTTO 100, non decide.")
        return

    seg_att = lambda r: -r['att_media']

    reals = [r['reale'] for r in righe]
    sig = [seg_att(r) for r in righe]
    c = pearson(sig, reals)
    icc = boot_cluster(righe, lambda camp: pearson([seg_att(x) for x in camp],
                                                     [x['reale'] for x in camp]),
                        lambda r: (r['squadra'], r['data']))
    rs = sorted(righe, key=seg_att); q = len(rs) // 5
    lf = sum(x['reale'] for x in rs[-q:]) / q - sum(x['reale'] for x in rs[:q]) / q
    icl = boot_cluster(righe, lambda camp: (lambda rs2, q2:
                        sum(x['reale'] for x in rs2[-q2:]) / q2 - sum(x['reale'] for x in rs2[:q2]) / q2
                        if (q2 := len(rs2) // 5) else None)(sorted(camp, key=seg_att), None),
                        lambda r: (r['squadra'], r['data']))

    print(f"\n=== STAGIONE 2024/25 (blocco temporale indipendente, n={len(righe)}) ===")
    print(f"  attacco-avv (media gol fatti, neg)  corr {c:+.3f} [{icc[0]:+.3f},{icc[1]:+.3f}]  "
          f"lift {lf:+6.2f} [{icl[0]:+6.2f},{icl[1]:+6.2f}]")

    sd_reale = (sum((x - sum(reals) / len(reals)) ** 2 for x in reals) / len(reals)) ** 0.5
    print(f"\nMAGNITUDINE: sd reale {sd_reale:.1f}  corr {c:+.3f}  "
          f"=> dispersione vera catturata ~{abs(c) * sd_reale:.1f} punti")

    n_y = sum(1 for r in righe if r['y'] is not None)
    print(f"\netichetta CS vera disponibile per {n_y}/{len(righe)} righe")

    print("\ndump 10 casi:")
    for r in righe[:10]:
        print(f"  {r['data']}  {r['slug']:30s} sq={r['squadra']:25s} avv={r['avversario']:25s} "
              f"att_media={r['att_media']:.2f}  reale={r['reale']:.1f}  y={r['y']}")

    out = 'analisi_manager/dati/gk_tenuta_2024_25_2026-08-11.json'
    json.dump(righe, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"\nsalvato: {out}")


if __name__ == '__main__':
    main()
