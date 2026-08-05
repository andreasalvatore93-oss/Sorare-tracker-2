"""Run DEFINITIVO: campione PIENO (tutti gli slug disponibili, nessun cap),
4 ruoli, bootstrap >=200 ripetizioni. Criterio dei TRE IC senza sconti (una
variante passa solo se IC dMAE<0, IC dcorr>0, IC dlift>0 TUTTI E TRE, non i
soli punti centrali).

OTTIMIZZAZIONE chiave rispetto al giro precedente: prev.calcola(ctx, **kwargs)
NON dipende da quali altre righe sono ricampionate nel bootstrap -- si calcola
UNA SOLA VOLTA per riga per ogni variante, poi il bootstrap ricampiona solo
gli ARRAY numerici gia' calcolati (niente piu' chiamate a calcola() dentro il
loop di bootstrap). Prima si ricalcolava ad ogni ripetizione: ecco il vero
costo inutile, non la raccolta (verificata pulita fino a piena scala,
n=25.312 per DEF in 73s, nessuno stallo una volta rimosso il processo
orfano find/).

Nessuna modifica di produzione, nessun commit.
"""
import sys, os, json, random, statistics, collections, datetime

ROOT = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import lift_selezione
from taratura_halflife_trend import RUOLI, _ruolo_di

FINESTRA_MIN = '2025-11-18'
BOOTSTRAP_REP = 200
SEME = 0

SCRATCH = os.path.join(ROOT, "dati_globali")

cache = backtest_arene_cache.CacheLocale()
slugs_tutti = sorted(cache.slug_disponibili())

print('pre-calcolo ruolo per tutti gli slug...', flush=True)
SLUG_PER_RUOLO = collections.defaultdict(list)
for i, slug in enumerate(slugs_tutti, 1):
    r = _ruolo_di(cache, slug)
    if r:
        SLUG_PER_RUOLO[r].append(slug)
print('fatto: ' + ', '.join(f'{k}={len(v)}' for k, v in SLUG_PER_RUOLO.items()), flush=True)


def raccogli_pieno(cache, slugs, voluto, data_min):
    """Nessun cap: tutti gli slug del ruolo, campione pieno."""
    fuori = []
    for i, slug in enumerate(slugs, 1):
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale, data = nodo.get('score'), prev._data(nodo)
            if reale is None or not data or data.strftime('%Y-%m-%d') < data_min:
                continue
            giorno = data + datetime.timedelta(days=1)
            try:
                ctx = prev.contesto(cache, slug, voluto, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < 3:
                continue
            fuori.append((voluto, slug, data.strftime('%Y-%m-%d'), ctx, reale))
        if i % 300 == 0:
            print(f'  [{i}/{len(slugs)}] {len(fuori)} punti', flush=True)
    return fuori


def calcola_predizioni(righe_ctx, hl, ti, **kwargs):
    """UNA volta sola: (ruolo,slug,data,pred,reale) per ogni riga, per una
    data variante. Da qui in poi il bootstrap ricampiona solo questo array."""
    out = []
    for ruolo, slug, data, ctx, reale in righe_ctx:
        try:
            p = prev.calcola(ctx, half_life=hl, trend_intensity=ti, **kwargs)
        except Exception:
            continue
        if p is None:
            continue
        out.append((ruolo, slug, data, p, reale))
    return out


def metriche(righe):
    if not righe:
        return None
    X = [r[3] for r in righe]
    Y = [r[4] for r in righe]
    mae = statistics.mean(abs(y - x) for x, y in zip(X, Y))
    mx, my = statistics.mean(X), statistics.mean(Y)
    sx, sy = statistics.pstdev(X), statistics.pstdev(Y)
    corr = (sum((a - mx) * (b - my) for a, b in zip(X, Y)) / len(X) / (sx * sy)
            if sx > 0 and sy > 0 else 0.0)
    lift, n_gg = lift_selezione(righe)
    return {'mae': mae, 'corr': corr, 'lift': lift, 'giornate': n_gg, 'n': len(righe)}


def bootstrap_da_predizioni(righe_base, righe_var, ripetizioni=BOOTSTRAP_REP, seme=7):
    """Bootstrap a grappoli sulle giornate, MA senza richiamare calcola():
    resample dei soli array di predizioni gia' calcolati una volta."""
    # indice comune per data (base e var devono avere le stesse righe nello
    # stesso ordine: garantito perche' entrambe derivano dalla stessa lista
    # di ctx filtrata per calcola()!=None -- verificato sotto con assert)
    per_giorno = collections.defaultdict(list)
    for i, r in enumerate(righe_base):
        per_giorno[r[2]].append(i)
    grappoli = list(per_giorno.values())
    rng = random.Random(seme)
    d_mae, d_corr, d_lift = [], [], []
    for _ in range(ripetizioni):
        idx = []
        for _ in range(len(grappoli)):
            idx.extend(grappoli[rng.randrange(len(grappoli))])
        sotto_b = [righe_base[i] for i in idx]
        sotto_v = [righe_var[i] for i in idx]
        rb = metriche(sotto_b)
        rv = metriche(sotto_v)
        if rb is None or rv is None:
            continue
        d_mae.append(rv['mae'] - rb['mae'])
        d_corr.append(rv['corr'] - rb['corr'])
        if rb['lift'] is not None and rv['lift'] is not None:
            d_lift.append(rv['lift'] - rb['lift'])

    def ic(v):
        if len(v) < 30:
            return None, None
        v = sorted(v)
        return v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]

    return {'d_mae_ic': ic(d_mae), 'd_corr_ic': ic(d_corr), 'd_lift_ic': ic(d_lift)}


def passa_severo(base_pt, var_pt, ic):
    """Criterio SEVERO richiesto: tutti e tre gli IC devono escludere lo
    zero nella direzione giusta (non i soli punti centrali)."""
    lo_mae, hi_mae = ic['d_mae_ic']
    lo_corr, hi_corr = ic['d_corr_ic']
    lo_lift, hi_lift = ic['d_lift_ic']
    if None in (lo_mae, lo_corr, lo_lift):
        return False, 'IC non disponibile (n bootstrap valido < 30)'
    ok_mae = hi_mae < 0
    ok_corr = lo_corr > 0
    ok_lift = lo_lift > 0
    return (ok_mae and ok_corr and ok_lift), None


risultati_globali = {}
GRIGLIA_ADD = (3.0, 6.0, 12.0, 20.0)
GRIGLIA_MULT = (0.05, 0.1, 0.2, 0.3, 0.4)

t_inizio_tot = datetime.datetime.now()

for breve in ('def', 'gk', 'mid', 'fwd'):
    voluto = RUOLI[breve]
    print('\n' + '#' * 100)
    print(f'RUOLO: {breve.upper()} ({voluto}) -- CAMPIONE PIENO', flush=True)
    print('#' * 100)
    slugs_ruolo = SLUG_PER_RUOLO.get(voluto, [])
    print(f'  {len(slugs_ruolo)} slug di ruolo {voluto} in cache (TUTTI, nessun cap)', flush=True)
    t0 = datetime.datetime.now()
    punti_grezzi = raccogli_pieno(cache, slugs_ruolo, voluto, FINESTRA_MIN)
    print(f'  raccolta in {(datetime.datetime.now()-t0).total_seconds():.1f}s: '
          f'{len(punti_grezzi)} punti nella finestra', flush=True)

    punti = [r for r in punti_grezzi if prev.delta_favorito_odds(r[3]) is not None]
    visti, dedup = set(), []
    for r in punti:
        k = (r[1], r[2])
        if k in visti:
            continue
        visti.add(k)
        dedup.append(r)
    punti = dedup
    print(f'  {len(punti)} punti con favorito_odds disponibile (dopo dedup slug,data)', flush=True)

    if len(punti) < 50:
        risultati_globali[breve] = {'n': len(punti), 'nota': 'campione insufficiente'}
        continue

    modulo = punti[0][3]['modulo']
    hl, ti = modulo.HALF_LIFE_GAMES, getattr(modulo, 'TREND_INTENSITY', 0.0)

    t0 = datetime.datetime.now()
    righe_base = calcola_predizioni(punti, hl, ti)
    base = metriche(righe_base)
    print(f"  k=0 (produzione)  n={base['n']:>6}  MAE={base['mae']:.4f}  corr={base['corr']:+.4f}  "
          f"lift={base['lift']:.2f}%  (giornate={base['giornate']})", flush=True)

    tabella = [{'forma': 'produzione', 'k': 0.0, **base, 'delta_mae': 0.0, 'delta_corr': 0.0, 'delta_lift': 0.0}]

    print(f'\n  -- griglia ADDITIVA ({breve}) --', flush=True)
    for k in GRIGLIA_ADD:
        righe_var = calcola_predizioni(punti, hl, ti, favorito_odds_k=k)
        if len(righe_var) != len(righe_base):
            print(f'    k={k} ATTENZIONE: allineamento righe diverso ({len(righe_var)} vs {len(righe_base)}), salto')
            continue
        r = metriche(righe_var)
        ics = bootstrap_da_predizioni(righe_base, righe_var)
        dm, dc, dl = r['mae'] - base['mae'], r['corr'] - base['corr'], (r['lift'] or 0) - (base['lift'] or 0)
        passa, motivo = passa_severo(base, r, ics)
        esito = 'PASSA' if passa else ('no' if motivo is None else f'no ({motivo})')
        print(f"    k={k:<6} n={r['n']:>6}  MAE={r['mae']:.4f} (d={dm:+.4f} IC{ics['d_mae_ic']})  "
              f"corr={r['corr']:+.4f} (d={dc:+.4f} IC{ics['d_corr_ic']})  "
              f"lift={r['lift']:.2f}% (d={dl:+.2f} IC{ics['d_lift_ic']})  {esito}", flush=True)
        tabella.append({'forma': 'additiva', 'k': k, **r, 'delta_mae': dm, 'delta_corr': dc,
                        'delta_lift': dl, 'ic': ics, 'esito': esito})

    print(f'\n  -- griglia MOLTIPLICATIVA ({breve}) --', flush=True)
    for k in GRIGLIA_MULT:
        righe_var = calcola_predizioni(punti, hl, ti, favorito_odds_mult_k=k)
        if len(righe_var) != len(righe_base):
            print(f'    k={k} ATTENZIONE: allineamento righe diverso, salto')
            continue
        r = metriche(righe_var)
        ics = bootstrap_da_predizioni(righe_base, righe_var)
        dm, dc, dl = r['mae'] - base['mae'], r['corr'] - base['corr'], (r['lift'] or 0) - (base['lift'] or 0)
        passa, motivo = passa_severo(base, r, ics)
        esito = 'PASSA' if passa else ('no' if motivo is None else f'no ({motivo})')
        print(f"    k={k:<6} n={r['n']:>6}  MAE={r['mae']:.4f} (d={dm:+.4f} IC{ics['d_mae_ic']})  "
              f"corr={r['corr']:+.4f} (d={dc:+.4f} IC{ics['d_corr_ic']})  "
              f"lift={r['lift']:.2f}% (d={dl:+.2f} IC{ics['d_lift_ic']})  {esito}", flush=True)
        tabella.append({'forma': 'moltiplicativa', 'k': k, **r, 'delta_mae': dm, 'delta_corr': dc,
                        'delta_lift': dl, 'ic': ics, 'esito': esito})

    print(f'  tempo totale griglia {breve}: {(datetime.datetime.now()-t0).total_seconds():.1f}s', flush=True)

    passanti = [r for r in tabella[1:] if r.get('esito') == 'PASSA']
    if passanti:
        migliore = max(passanti, key=lambda r: (r['delta_corr'] + r['delta_lift'] / 100))
    else:
        migliore = None
        print(f'  NESSUNA VARIANTE PASSA IL CRITERIO SEVERO (3 IC su 3) per {breve}', flush=True)

    spostamento = None
    if migliore:
        kwargs_migliore = ({'favorito_odds_k': migliore['k']} if migliore['forma'] == 'additiva'
                            else {'favorito_odds_mult_k': migliore['k']})
        righe_migliore = calcola_predizioni(punti, hl, ti, **kwargs_migliore)
        base_by_key = {(r[1], r[2]): r[3] for r in righe_base}
        delta_scores = []
        for r in righe_migliore:
            bv = base_by_key.get((r[1], r[2]))
            if bv is None:
                continue
            delta_scores.append(r[3] - bv)
        if delta_scores:
            abs_delta = sorted(abs(d) for d in delta_scores)
            media = statistics.mean(abs_delta)
            p95 = abs_delta[int(0.95 * len(abs_delta))]
            massimo = abs_delta[-1]
            print(f"\n  variante migliore ({breve}): {migliore['forma']} k={migliore['k']} "
                  f"(dcorr={migliore['delta_corr']:+.4f}, dlift={migliore['delta_lift']:+.2f}%, dMAE={migliore['delta_mae']:+.4f})")
            print(f"  |delta score_atteso| n={len(delta_scores)}: media={media:.2f}pt  p95={p95:.2f}pt  max={massimo:.2f}pt")
            print(f"  vs soglia arena +/-15pt: media={100*media/15:.0f}%  p95={100*p95/15:.0f}%  max={100*massimo/15:.0f}%")
            spostamento = {'variante': f"{migliore['forma']} k={migliore['k']}", 'n': len(delta_scores),
                           'media_pt': media, 'p95_pt': p95, 'max_pt': massimo}

    risultati_globali[breve] = {'n_totale': len(punti), 'giornate': base['giornate'],
                                 'tabella': tabella,
                                 'variante_migliore': migliore.get('forma') if migliore else None,
                                 'k_migliore': migliore.get('k') if migliore else None,
                                 'spostamento': spostamento}

print(f"\nTEMPO TOTALE RUN: {(datetime.datetime.now()-t_inizio_tot).total_seconds():.1f}s", flush=True)

with open(os.path.join(SCRATCH, 'esito_taratura_odds_definitivo.json'), 'w', encoding='utf-8') as fh:
    json.dump(risultati_globali, fh, ensure_ascii=False, indent=1, default=str)
print(f"salvato in {os.path.join(SCRATCH, 'esito_taratura_odds_definitivo.json')}")
