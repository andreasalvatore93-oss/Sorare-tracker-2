"""Come taratura_confronto_odds.py ma parametrizzato per ruolo. Stesso identico
setup del run DEF n=3.433 (cap 6000 righe grezze, seme 0, bootstrap 35 rip.,
finestra 18/11/2025+, eliteserien esclusa via indice quote). Solo griglia
(no overlap step, non richiesto per questo giro). Nessuna modifica di
produzione, nessun commit.
"""
import sys, os, json, random, statistics, collections, datetime

ROOT = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import lift_selezione
from taratura_halflife_trend import RUOLI

FINESTRA_MIN = '2025-11-18'
CAP_TOTALE = 6000
BOOTSTRAP_REP = 35
SEME = 0

cache = backtest_arene_cache.CacheLocale()
slugs_tutti = sorted(cache.slug_disponibili())

print('pre-calcolo ruolo per tutti gli slug (una volta sola, veloce)...', flush=True)
from taratura_halflife_trend import _ruolo_di
_t0 = datetime.datetime.now()
SLUG_PER_RUOLO = collections.defaultdict(list)
for i, slug in enumerate(slugs_tutti, 1):
    r = _ruolo_di(cache, slug)
    if r:
        SLUG_PER_RUOLO[r].append(slug)
    if i % 1000 == 0:
        print(f'  ruoli: {i}/{len(slugs_tutti)}', flush=True)
print(f'fatto in {(datetime.datetime.now()-_t0).total_seconds():.1f}s: '
      + ', '.join(f'{k}={len(v)}' for k, v in SLUG_PER_RUOLO.items()), flush=True)


def raccogli_finestra(cache, slugs, voluto, data_min, max_giochi_per_slug=60, cap_totale=None):
    slugs = list(slugs)
    random.Random(SEME).shuffle(slugs)
    fuori = []
    for i, slug in enumerate(slugs, 1):
        if cap_totale and len(fuori) >= cap_totale:
            print(f'  cap di {cap_totale} punti raggiunto dopo {i} slug, mi fermo qui', flush=True)
            break
        n_processati = 0
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
            n_processati += 1
            if n_processati >= max_giochi_per_slug:
                break
        if i % 200 == 0:
            print(f'  [{i}/{len(slugs)}] {len(fuori)} punti', flush=True)
    return fuori


def valuta_esteso(righe_ctx, hl, ti, **kwargs):
    righe = []
    for ruolo, slug, data, ctx, reale in righe_ctx:
        try:
            p = prev.calcola(ctx, half_life=hl, trend_intensity=ti, **kwargs)
        except Exception:
            continue
        if p is None:
            continue
        righe.append((ruolo, slug, data, p, reale))
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


def bootstrap_delta(righe_ctx, hl, ti, kwargs_var, ripetizioni=BOOTSTRAP_REP, seme=7):
    per_giorno = collections.defaultdict(list)
    for i, r in enumerate(righe_ctx):
        per_giorno[r[2]].append(i)
    grappoli = list(per_giorno.values())
    rng = random.Random(seme)
    d_mae, d_corr, d_lift = [], [], []
    for _ in range(ripetizioni):
        idx = []
        for _ in range(len(grappoli)):
            idx.extend(grappoli[rng.randrange(len(grappoli))])
        sotto = [righe_ctx[i] for i in idx]
        rb = valuta_esteso(sotto, hl, ti)
        rv = valuta_esteso(sotto, hl, ti, **kwargs_var)
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


SCRATCH = os.path.join(ROOT, "dati_globali")

risultati_globali = {}
for breve in ('gk', 'mid', 'fwd'):
    voluto = RUOLI[breve]
    print('\n' + '#' * 100)
    print(f'RUOLO: {breve.upper()} ({voluto})')
    print('#' * 100)
    slugs_ruolo = SLUG_PER_RUOLO.get(voluto, [])
    print(f'  {len(slugs_ruolo)} slug di ruolo {voluto} in cache', flush=True)
    punti_grezzi = raccogli_finestra(cache, slugs_ruolo, voluto, FINESTRA_MIN, cap_totale=CAP_TOTALE)
    print(f'{len(punti_grezzi)} punti {breve} nella finestra (prima del filtro odds)')
    punti = [r for r in punti_grezzi if prev.delta_favorito_odds(r[3]) is not None]
    visti, dedup = set(), []
    for r in punti:
        k = (r[1], r[2])
        if k in visti:
            continue
        visti.add(k)
        dedup.append(r)
    punti = dedup
    print(f'{len(punti)} punti con favorito_odds disponibile (dopo dedup slug,data)')

    if len(punti) < 50:
        print(f'  CAMPIONE INSUFFICIENTE per {breve} (n={len(punti)}), salto')
        risultati_globali[breve] = {'n': len(punti), 'nota': 'campione insufficiente'}
        continue

    modulo = punti[0][3]['modulo']
    hl, ti = modulo.HALF_LIFE_GAMES, getattr(modulo, 'TREND_INTENSITY', 0.0)

    base = valuta_esteso(punti, hl, ti)
    print(f"  k=0 (produzione)  n={base['n']:>6}  MAE={base['mae']:.4f}  corr={base['corr']:+.4f}  "
          f"lift={base['lift']:.2f}%  (giornate={base['giornate']})")

    tabella = [{'forma': 'produzione', 'k': 0.0, **base, 'delta_mae': 0.0, 'delta_corr': 0.0, 'delta_lift': 0.0}]

    print(f'\n  -- griglia ADDITIVA ({breve}) --')
    for k in (3.0, 6.0, 12.0, 25.0):
        r = valuta_esteso(punti, hl, ti, favorito_odds_k=k)
        ics = bootstrap_delta(punti, hl, ti, {'favorito_odds_k': k})
        dm, dc, dl = r['mae'] - base['mae'], r['corr'] - base['corr'], (r['lift'] or 0) - (base['lift'] or 0)
        esito_bool = (dm < 0, dc > 0, dl > 0)
        passa = 'PASSA' if all(esito_bool) else 'no'
        print(f"    k={k:<6} n={r['n']:>6}  MAE={r['mae']:.4f} (d={dm:+.4f} IC{ics['d_mae_ic']})  "
              f"corr={r['corr']:+.4f} (d={dc:+.4f} IC{ics['d_corr_ic']})  "
              f"lift={r['lift']:.2f}% (d={dl:+.2f} IC{ics['d_lift_ic']})  {passa}")
        tabella.append({'forma': 'additiva', 'k': k, **r, 'delta_mae': dm, 'delta_corr': dc,
                        'delta_lift': dl, 'ic': ics, 'esito': passa})

    print(f'\n  -- griglia MOLTIPLICATIVA ({breve}) --')
    for k in (0.1, 0.2, 0.3, 0.5):
        r = valuta_esteso(punti, hl, ti, favorito_odds_mult_k=k)
        ics = bootstrap_delta(punti, hl, ti, {'favorito_odds_mult_k': k})
        dm, dc, dl = r['mae'] - base['mae'], r['corr'] - base['corr'], (r['lift'] or 0) - (base['lift'] or 0)
        esito_bool = (dm < 0, dc > 0, dl > 0)
        passa = 'PASSA' if all(esito_bool) else 'no'
        print(f"    k={k:<6} n={r['n']:>6}  MAE={r['mae']:.4f} (d={dm:+.4f} IC{ics['d_mae_ic']})  "
              f"corr={r['corr']:+.4f} (d={dc:+.4f} IC{ics['d_corr_ic']})  "
              f"lift={r['lift']:.2f}% (d={dl:+.2f} IC{ics['d_lift_ic']})  {passa}")
        tabella.append({'forma': 'moltiplicativa', 'k': k, **r, 'delta_mae': dm, 'delta_corr': dc,
                        'delta_lift': dl, 'ic': ics, 'esito': passa})

    # variante migliore su corr+lift fra quelle che PASSANO; se nessuna passa, fra tutte
    passanti = [r for r in tabella[1:] if r.get('esito') == 'PASSA']
    pool = passanti if passanti else tabella[1:]
    migliore = max(pool, key=lambda r: (r['delta_corr'] + r['delta_lift'] / 100))
    kwargs_migliore = ({'favorito_odds_k': migliore['k']} if migliore['forma'] == 'additiva'
                        else {'favorito_odds_mult_k': migliore['k']})

    delta_scores = []
    for ruolo, slug, data, ctx, reale in punti:
        try:
            bv = prev.calcola(ctx, half_life=hl, trend_intensity=ti)
            vv = prev.calcola(ctx, half_life=hl, trend_intensity=ti, **kwargs_migliore)
        except Exception:
            continue
        if bv is None or vv is None:
            continue
        delta_scores.append(vv - bv)

    spostamento = None
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
                       'media_pt': media, 'p95_pt': p95, 'max_pt': massimo,
                       'pct_soglia_media': 100*media/15, 'pct_soglia_p95': 100*p95/15, 'pct_soglia_max': 100*massimo/15}

    risultati_globali[breve] = {'n_totale': len(punti), 'giornate': base['giornate'],
                                 'tabella': tabella, 'variante_migliore': migliore.get('forma'),
                                 'k_migliore': migliore.get('k'), 'spostamento': spostamento}

with open(os.path.join(SCRATCH, 'esito_taratura_odds_multiruolo.json'), 'w', encoding='utf-8') as fh:
    json.dump(risultati_globali, fh, ensure_ascii=False, indent=1, default=str)
print(f"\nsalvato in {os.path.join(SCRATCH, 'esito_taratura_odds_multiruolo.json')}")
