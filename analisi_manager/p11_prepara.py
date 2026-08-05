# -*- coding: utf-8 -*-
"""P11 stadio 1 - prepara il pool per ogni giornata di arene REALI dell'utente.

Per ogni fixture di dati_globali/arene_storico.json:
  - pool = tutte le carte che l'utente ha davvero schierato quel giorno
    (mazzo fisso; le carte non si clonano, trappola 8.8) con il numero di
    COPIE possedute, previsione walk-forward (score_atteso GREZZO), L10 al
    momento della scelta, punteggio REALE grezzo;
  - slot = le arene reali di quella giornata con i 10 punteggi veri.

Modello di produzione: GK_TEAM_CS_WEIGHT = 22/35 (valore vivo in test_gk.py
dopo P9-ter). Nessuna scrittura nel repo.
"""
import os, sys, json, time, collections, datetime
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B
import backtest_arene_produzione as BP

assert abs(P._GK_CS_WEIGHT - 22.0 / 35.0) < 1e-9

OUT = sys.argv[1]
cache = C.CacheLocale()
formazioni = json.load(open('dati_globali/arene_formazioni.json', encoding='utf-8'))['formazioni']
arene = json.load(open('dati_globali/arene_storico.json', encoding='utf-8'))['arene']
fine = B.fine_giornate(arene)

fixtures = sorted(set(a['fixture'] for a in arene))
print('fixture:', len(fixtures), flush=True)

risultato = {}
t0 = time.time()
for i, fx in enumerate(fixtures, 1):
    fd = fine.get(fx)
    if fd is None:
        continue
    carte, form_per_slug = BP.raccogli_giornata(formazioni, fx, None)
    if not carte:
        continue
    coppie = sorted(set((c['slug'], c['ruolo']) for c in carte.values()))
    cutoff = B.inizio_giornata(cache, fd, coppie)
    if cutoff is None:
        continue

    copie = collections.Counter()
    reale_per = {}
    for c in carte.values():
        k = (c['slug'], c['ruolo'])
        copie[k] += 1
        if c['reale'] is not None:
            reale_per.setdefault(k, c['reale'])

    pool = []
    for slug, ruolo in coppie:
        r = P.score_atteso(cache, slug, ruolo, fd, cutoff)
        if r is None or r.get('atteso') is None or r.get('l10') is None:
            continue
        target = P.partita_target(cache, slug, fd)
        comp = (target['anyGame'].get('competition') or {}).get('slug') if target else None
        pool.append({
            'slug': slug, 'ruolo': ruolo, 'codice': BP.RUOLO_SORARE_TO_CODICE[ruolo],
            'atteso_raw': r['atteso'], 'l10': r['l10'],
            'squadra': r.get('squadra'), 'opp_slug': r.get('opp_slug'),
            'in_casa': r.get('in_casa'),
            'lega': BP.LEAGUE_DIR.get(comp, 'senza_lega'),
            'copie': copie[(slug, ruolo)],
            'reale': reale_per.get((slug, ruolo)),
        })

    slot = []
    for a in arene:
        if a['fixture'] != fx:
            continue
        tipo_bfg, fam, avviso = BP.classifica_tipo_produzione(a)
        slot.append({'slug': a['slug'], 'tipo': a['tipo'], 'tipo_bfg': tipo_bfg,
                     'famiglia': fam, 'avviso': avviso,
                     'punteggi': a.get('punteggi'), 'terzo': a.get('terzo'),
                     'mio_score': a.get('mio_score'), 'mio_rank': a.get('mio_rank'),
                     'premio_essenze': a.get('premio_essenze'),
                     'rank_premiato': a.get('rank_premiato'),
                     'costo': a.get('costo'), 'partecipanti': a.get('partecipanti')})

    risultato[fx] = {'fine': str(fd), 'cutoff': str(cutoff), 'pool': pool, 'slot': slot,
                     'n_carte_uniche': len(coppie), 'n_pool': len(pool)}
    print('[%2d/%d] %-28s pool %3d/%3d  slot %2d  (%.0fs)'
          % (i, len(fixtures), fx, len(pool), len(coppie), len(slot), time.time() - t0), flush=True)

with open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(risultato, fh, ensure_ascii=False)
print('scritto', OUT, 'giornate:', len(risultato), flush=True)
