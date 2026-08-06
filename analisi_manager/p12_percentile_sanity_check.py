"""Test di coerenza (richiesta utente, chat 06/08 ~17:00 Roma): sui DEF, la
sez.19 mostra score_atteso con percentile medio ~= caso (50.7 vs 50.0), ma
REPORT_PASSAGGIO_2_OPUS_P3 misura lift 18.6% (n=5531) sullo stesso ruolo con
un altro metro. Se il calcolo del percentile e' corretto, applicato a un
campione AMPIO di DEF (non solo i 175 con grade) deve mostrare un vantaggio
sopra il caso. Se non lo mostra, il bug e' nel conto del percentile.

Campione: DEF distinti dai roster reali in dati_globali/manager_*.json (1590
slug), campionati a caso, storia intera dalla cache locale (zero query),
NESSUN filtro su grade (qui non serve: si misura solo score_atteso vs
realizzato, come nel backtest P3).
"""
import os, sys, io, json, random, glob, collections, datetime

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import backtest_arene_cache as CACHE
import backtest_arene_previsioni as prev

random.seed(20260806)
cache = CACHE.CacheLocale()


def percentile_rank(scores, i):
    n = len(scores)
    if n <= 1:
        return 50.0
    x = scores[i]
    minori_o_uguali = sum(1 for s in scores if s <= x) - 1
    return 100.0 * minori_o_uguali / (n - 1)


def raccogli_slug_def(n_campione=250):
    slugs = set()
    for f in glob.glob('dati_globali/manager_*.json'):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for gw, righe in (d.get('giornate') or {}).items():
            for riga in righe:
                for c in riga.get('carte') or []:
                    if c.get('ruolo') == 'Defender':
                        slugs.add(c['slug'])
    slugs = sorted(slugs)
    random.shuffle(slugs)
    return slugs[:n_campione]


def costruisci_righe(slugs):
    righe = []
    n_slug_ok = 0
    for slug in slugs:
        nodi = cache.gamelog(slug)
        finali = [n for n in nodi if n.get('scoreStatus') == 'FINAL' and n.get('score') is not None]
        if len(finali) < 4:
            continue
        usato = False
        for nodo in finali:
            data_iso = (nodo.get('anyGame') or {}).get('date')
            if not data_iso:
                continue
            try:
                fd = datetime.datetime.fromisoformat(data_iso.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                continue
            try:
                ctx = prev.contesto(cache, slug, 'Defender', fd)
            except Exception:
                ctx = None
            if ctx is None:
                continue
            cutoff = ctx.get('cutoff')
            if cutoff is None or abs((cutoff - fd).days) > 2:
                continue
            try:
                atteso = prev.calcola(ctx)
            except Exception:
                atteso = None
            if atteso is None:
                continue
            righe.append({'slug': slug, 'date': data_iso, 'score': nodo['score'], 'atteso': atteso})
            usato = True
        if usato:
            n_slug_ok += 1
    return righe, n_slug_ok


def costruisci_giornate(righe):
    by_day = collections.defaultdict(list)
    for r in righe:
        by_day[r['date'][:10]].append(r)
    giornate = []
    scartate = 0
    for day, rr in by_day.items():
        by_slug = {}
        for r in rr:
            by_slug.setdefault(r['slug'], r)
        rr = list(by_slug.values())
        if len(rr) < 3:
            scartate += 1
            continue
        giornate.append((day, rr))
    return giornate, scartate


def main():
    slugs = raccogli_slug_def(n_campione=250)
    print(f'slug DEF campionati: {len(slugs)} (da 1590 distinti nei roster manager)')
    righe, n_slug_ok = costruisci_righe(slugs)
    print(f'righe con score_atteso calcolato: {len(righe)}  slug con almeno 1 riga utile: {n_slug_ok}')

    giornate, scartate = costruisci_giornate(righe)
    print(f'giornate valide (>=3 candidati): {len(giornate)}  scartate (pool<3): {scartate}')
    if len(giornate) < 20:
        print('CAMPIONE INSUFFICIENTE per un test di coerenza affidabile, fermo qui.')
        return

    n = len(giornate)
    best_atteso = 0
    perc_tot = 0.0
    perc_caso_tot = 0.0
    best_caso_tot = 0.0
    for day, rr in giornate:
        scores = [r['score'] for r in rr]
        idx_atteso = max(range(len(rr)), key=lambda i: rr[i]['atteso'])
        percentili = [percentile_rank(scores, i) for i in range(len(rr))]
        perc_tot += percentili[idx_atteso]
        best_atteso += 1 if scores[idx_atteso] >= max(scores) else 0
        perc_caso_tot += sum(percentili) / len(rr)  # sempre 50 per costruzione
        best_caso_tot += 1.0 / len(rr)

    print('\n--- RISULTATO TEST DI COERENZA (campione ampio, solo score_atteso) ---')
    print(f'  n_giornate={n}')
    print(f'  tasso "migliore del pool": atteso={100*best_atteso/n:.1f}%   caso={100*best_caso_tot/n:.1f}%')
    print(f'  percentile medio:          atteso={perc_tot/n:.1f}          caso={perc_caso_tot/n:.1f}')

    with open('analisi_manager/p12_percentile_sanity_check_out.json', 'w', encoding='utf-8') as fh:
        json.dump({
            'n_slug_campionati': len(slugs), 'n_slug_con_righe': n_slug_ok,
            'n_righe': len(righe), 'n_giornate': n, 'n_giornate_scartate': scartate,
            'tasso_migliore_atteso_pct': 100 * best_atteso / n,
            'tasso_migliore_caso_pct': 100 * best_caso_tot / n,
            'percentile_medio_atteso': perc_tot / n,
            'percentile_medio_caso': perc_caso_tot / n,
        }, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
