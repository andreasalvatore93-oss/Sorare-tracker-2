# -*- coding: utf-8 -*-
"""P11 passo 1 - raccolta coppie (previsto, reale) col modello DI PRODUZIONE
(GK_TEAM_CS_WEIGHT = 22/35, valore attuale di test_gk.py dopo P9-ter).

Non tocca dati_globali/taratura_coppie.json: scrive solo nello scratchpad.
"""
import os, sys, json, time
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
import taratura_giocatore as TG

assert abs(prev._GK_CS_WEIGHT - 22.0 / 35.0) < 1e-9, prev._GK_CS_WEIGHT

OUT = sys.argv[1]
t0 = time.time()
cache = backtest_arene_cache.CacheLocale()
slugs = sorted(cache.slug_disponibili())
print('giocatori in cache:', len(slugs), flush=True)
coppie = TG.raccogli(cache, slugs)
print('coppie:', len(coppie), 'in %.0fs' % (time.time() - t0), flush=True)
with open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(coppie, fh, ensure_ascii=False)
print('scritto', OUT, flush=True)
