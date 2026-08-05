"""Test SEPARATO, nessuna modifica a screening_segnali.py/taratura_confronto_parametri.py
(solo import). Misura favorito_odds (1X2 esterno) come correzione di
score_atteso, forma additiva e moltiplicativa, con test A/A e overlap con
opponent_lambda_mult/casa_k. Pilota SOLO ruolo DEF (dove sono gia' esposti
avversario_lambda e i tre k residui). Nessun commit, nessuna modifica di
produzione: solo report.
"""
import sys, os, json, random, statistics, collections, datetime

ROOT = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import raccogli, lift_selezione
from taratura_halflife_trend import RUOLI

FINESTRA_MIN = '2025-11-18'

cache = backtest_arene_cache.CacheLocale()
slugs = sorted(cache.slug_disponibili())
print(f'{len(slugs)} giocatori in cache')

# raccolta con filtro PRECOCE sulla data (prima di chiamare prev.contesto,
# che e' il passo costoso): niente senso ricostruire il contesto walk-forward
# per partite fuori dalla finestra coperta dalle quote, si scarterebbero comunque
import datetime as _dt
import backtest_arene_previsioni as _prevmod

def raccogli_finestra(cache, slugs, voluti, data_min, max_giochi_per_slug=60, cap_totale=None):
    """cap_totale: interrompe la raccolta appena raggiunto (mescola prima
    l'ordine degli slug, cosi' il campione resta rappresentativo di tutte le
    leghe/lettere invece che troncato alfabeticamente). Aggiunto DOPO aver
    osservato che senza cap il processo rallenta progressivamente accumulando
    decine di migliaia di contesti in memoria (nessuno slug preso singolarmente
    e' lento, verificato: e' un effetto di accumulo, non un dato patologico)."""
    import time as _time
    slugs = list(slugs)
    random.Random(0).shuffle(slugs)
    fuori = []
    for i, slug in enumerate(slugs, 1):
        if cap_totale and len(fuori) >= cap_totale:
            print(f'  cap di {cap_totale} punti raggiunto dopo {i} slug, mi fermo qui', flush=True)
            break
        t0 = _time.monotonic()
        ruolo = None
        n_processati = 0
        for nodo in cache.gamelog(slug):
            if nodo.get('scoreStatus') != 'FINAL':
                continue
            reale, data = nodo.get('score'), _prevmod._data(nodo)
            if reale is None or not data or data.strftime('%Y-%m-%d') < data_min:
                continue
            if ruolo is None:
                from taratura_halflife_trend import _ruolo_di
                ruolo = _ruolo_di(cache, slug)
                if ruolo is None or ruolo not in voluti:
                    break
            giorno = data + _dt.timedelta(days=1)
            try:
                ctx = _prevmod.contesto(cache, slug, ruolo, giorno)
            except Exception:
                continue
            if not ctx or len(ctx['s']['scores']) < 3:
                continue
            fuori.append((ruolo, slug, data.strftime('%Y-%m-%d'), ctx, reale))
            n_processati += 1
            if n_processati >= max_giochi_per_slug:
                break
        dt = _time.monotonic() - t0
        if dt > 2.0:
            print(f'  SLUG LENTO: {slug} ({dt:.1f}s, {n_processati} giochi)', flush=True)
        if i % 200 == 0:
            print(f'  [{i}/{len(slugs)}] {len(fuori)} punti', flush=True)
    return fuori

punti_grezzi = raccogli_finestra(cache, slugs, {RUOLI['def']}, FINESTRA_MIN, cap_totale=6000)
print(f'{len(punti_grezzi)} punti DEF nella finestra {FINESTRA_MIN}+ (prima del filtro odds)')

# filtro: solo dove le quote sono disponibili (automaticamente esclude
# eliteserien, gia' escluso in fase di costruzione dell'indice)
punti = [r for r in punti_grezzi if prev.delta_favorito_odds(r[3]) is not None]
print(f'{len(punti)} punti DEF con favorito_odds disponibile')

# dedup 8.15 su (slug, data)
visti = set()
dedup = []
for r in punti:
    k = (r[1], r[2])
    if k in visti:
        continue
    visti.add(k)
    dedup.append(r)
print(f'dopo dedup (slug,data): {len(dedup)} (rimossi {len(punti)-len(dedup)})')
punti = dedup

modulo = punti[0][3]['modulo']
PROD_HL, PROD_TI = modulo.HALF_LIFE_GAMES, getattr(modulo, 'TREND_INTENSITY', 0.0)


# --------------------------------------------------------------------------
# STEP 1 -- test A/A sull'interruttore
# --------------------------------------------------------------------------
print('\n' + '=' * 96)
print('STEP 1 -- test A/A (il parametro si muove?)')
print('=' * 96)
campione_aa = punti[:5]
for etichetta, kwargs in [
    ('additivo k=0', dict(favorito_odds_k=0.0)),
    ('additivo k=1e9', dict(favorito_odds_k=1e9)),
    ('moltiplicativo k=0', dict(favorito_odds_mult_k=0.0)),
    ('moltiplicativo k=1e9', dict(favorito_odds_mult_k=1e9)),
]:
    vals = []
    for _r, _s, _d, ctx, _re in campione_aa:
        vals.append(prev.calcola(ctx, half_life=PROD_HL, trend_intensity=PROD_TI, **kwargs))
    print(f'  {etichetta:<24} score_atteso primi 5: {[round(v,2) if v is not None else None for v in vals]}')


# --------------------------------------------------------------------------
# metro ufficiale (stesse funzioni di taratura_confronto_parametri.py)
# --------------------------------------------------------------------------
def valuta_esteso(righe_ctx, **kwargs):
    righe = []
    for ruolo, slug, data, ctx, reale in righe_ctx:
        try:
            p = prev.calcola(ctx, half_life=PROD_HL, trend_intensity=PROD_TI, **kwargs)
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


def bootstrap_delta(righe_ctx, kwargs_base, kwargs_var, ripetizioni=35, seme=7):
    """IC95 del delta (variante - base) via bootstrap a grappoli sulle
    giornate (stessa logica di congiunta_estesa in screening_segnali.py):
    conta il delta, non il valore assoluto."""
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
        rb = valuta_esteso(sotto, **kwargs_base)
        rv = valuta_esteso(sotto, **kwargs_var)
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


risultati = {}

# --------------------------------------------------------------------------
# STEP 2 -- griglia, forma additiva vs moltiplicativa (opponent_lambda_mult e
# casa_k restano di PRODUZIONE, cioe' avversario_lambda=True, casa_k=None)
# --------------------------------------------------------------------------
print('\n' + '=' * 96)
print('STEP 2 -- griglia additiva (favorito_odds_k), sopra la produzione invariata')
print('=' * 96)
base = valuta_esteso(punti)
print(f"  k=0 (produzione)        n={base['n']:>6}  MAE={base['mae']:.4f}  corr={base['corr']:+.4f}  "
      f"lift={base['lift']:.2f}%  (giornate={base['giornate']})")
tabella_add = [{'k': 0.0, **base, 'delta_mae': 0.0, 'delta_corr': 0.0, 'delta_lift': 0.0}]
for k in (6.0, 25.0, 40.0, 60.0, 100.0):
    r = valuta_esteso(punti, favorito_odds_k=k)
    ics = bootstrap_delta(punti, {}, {'favorito_odds_k': k})
    esito = (r['mae'] < base['mae'], r['corr'] > base['corr'], (r['lift'] or 0) > (base['lift'] or 0))
    passa = 'PASSA' if all(esito) else 'no'
    print(f"  k={k:<6}                  n={r['n']:>6}  MAE={r['mae']:.4f} (d={r['mae']-base['mae']:+.4f} "
          f"IC{ics['d_mae_ic']})  corr={r['corr']:+.4f} (d={r['corr']-base['corr']:+.4f} IC{ics['d_corr_ic']})  "
          f"lift={r['lift']:.2f}% (d={(r['lift'] or 0)-(base['lift'] or 0):+.2f} IC{ics['d_lift_ic']})  {passa}")
    tabella_add.append({'k': k, **r, 'delta_mae': r['mae']-base['mae'],
                        'delta_corr': r['corr']-base['corr'],
                        'delta_lift': (r['lift'] or 0)-(base['lift'] or 0),
                        'ic': ics, 'esito': passa})
risultati['griglia_additiva'] = tabella_add

print('\n' + '=' * 96)
print('STEP 2 -- griglia moltiplicativa (favorito_odds_mult_k)')
print('=' * 96)
tabella_mult = [{'k': 0.0, **base, 'delta_mae': 0.0, 'delta_corr': 0.0, 'delta_lift': 0.0}]
for k in (0.1, 0.3, 0.5, 0.8, 1.2, 2.0):
    r = valuta_esteso(punti, favorito_odds_mult_k=k)
    ics = bootstrap_delta(punti, {}, {'favorito_odds_mult_k': k})
    esito = (r['mae'] < base['mae'], r['corr'] > base['corr'], (r['lift'] or 0) > (base['lift'] or 0))
    passa = 'PASSA' if all(esito) else 'no'
    print(f"  k={k:<6}                  n={r['n']:>6}  MAE={r['mae']:.4f} (d={r['mae']-base['mae']:+.4f} "
          f"IC{ics['d_mae_ic']})  corr={r['corr']:+.4f} (d={r['corr']-base['corr']:+.4f} IC{ics['d_corr_ic']})  "
          f"lift={r['lift']:.2f}% (d={(r['lift'] or 0)-(base['lift'] or 0):+.2f} IC{ics['d_lift_ic']})  {passa}")
    tabella_mult.append({'k': k, **r, 'delta_mae': r['mae']-base['mae'],
                         'delta_corr': r['corr']-base['corr'],
                         'delta_lift': (r['lift'] or 0)-(base['lift'] or 0),
                         'ic': ics, 'esito': passa})
risultati['griglia_moltiplicativa'] = tabella_mult

# k migliore (additivo) sul solo criterio "PASSA", altrimenti il piu vicino
migliori = [r for r in tabella_add[1:] if r.get('esito') == 'PASSA']
K_SCELTO = migliori[0]['k'] if migliori else tabella_add[1]['k']
print(f"\nk scelto per gli scenari di overlap (additivo): {K_SCELTO}"
      f"{' (nessuno passava insieme, uso il primo della griglia)' if not migliori else ''}")

# --------------------------------------------------------------------------
# STEP 3 -- overlap con opponent_lambda_mult e casa_k
# --------------------------------------------------------------------------
print('\n' + '=' * 96)
print(f'STEP 3 -- overlap (favorito_odds_k={K_SCELTO} additivo dove presente)')
print('=' * 96)
scenari = [
    ('e) baseline produzione',            dict()),
    ('a) odds SOLO (casa/opp_lambda spenti)', dict(favorito_odds_k=K_SCELTO, avversario_lambda=False)),
    ('b) odds + casa (opp_lambda spento)',    dict(favorito_odds_k=K_SCELTO, avversario_lambda=False, casa_k=0.05)),
    ('c) odds al posto di opp_lambda, casa acceso (=produzione)', dict(favorito_odds_k=K_SCELTO, avversario_lambda=False)),
    ('d) tutti e tre accesi (odds+opp_lambda+casa)', dict(favorito_odds_k=K_SCELTO, avversario_lambda=True, casa_k=0.05)),
]
tabella_overlap = []
for etichetta, kwargs in scenari:
    r = valuta_esteso(punti, **kwargs)
    ics = bootstrap_delta(punti, {}, kwargs) if kwargs else {'d_mae_ic': (0,0), 'd_corr_ic': (0,0), 'd_lift_ic': (0,0)}
    dm = r['mae'] - base['mae']
    dc = r['corr'] - base['corr']
    dl = (r['lift'] or 0) - (base['lift'] or 0)
    print(f"  {etichetta:<48} n={r['n']:>6}  MAE={r['mae']:.4f} (d={dm:+.4f})  "
          f"corr={r['corr']:+.4f} (d={dc:+.4f})  lift={r['lift']:.2f}% (d={dl:+.2f})")
    tabella_overlap.append({'scenario': etichetta, **r, 'delta_mae': dm, 'delta_corr': dc,
                            'delta_lift': dl, 'ic': ics, 'kwargs': kwargs})
risultati['overlap'] = tabella_overlap
risultati['n_totale'] = len(punti)
risultati['k_scelto_additivo'] = K_SCELTO

# --------------------------------------------------------------------------
# segnali MISTI: corr/lift migliorano ma MAE peggiora, o viceversa
# --------------------------------------------------------------------------
print('\n' + '=' * 96)
print('SEGNALI MISTI (corr/lift vs MAE in direzioni opposte) -- da non scartare in silenzio')
print('=' * 96)
tutte_righe = []
for r in tabella_add[1:]:
    tutte_righe.append(('additiva k=%g' % r['k'], r))
for r in tabella_mult[1:]:
    tutte_righe.append(('moltiplicativa k=%g' % r['k'], r))
for r in tabella_overlap:
    if r['scenario'].startswith('e)'):
        continue
    tutte_righe.append((r['scenario'], r))

misti = []
for nome, r in tutte_righe:
    corr_migliora = r['delta_corr'] > 0
    lift_migliora = r['delta_lift'] > 0
    mae_migliora = r['delta_mae'] < 0
    concordi = (corr_migliora == mae_migliora) and (lift_migliora == mae_migliora)
    if not concordi:
        misti.append((nome, r))
        print(f"  {nome:<48} MAE {r['delta_mae']:+.4f}  corr {r['delta_corr']:+.4f}  "
              f"lift {r['delta_lift']:+.2f}%   <- SEGNALE MISTO")
if not misti:
    print('  nessuno: in tutte le varianti testate le tre gambe si muovono nella stessa direzione')
risultati['segnali_misti'] = [{'nome': n, **{k: v for k, v in r.items() if k in
                               ('delta_mae', 'delta_corr', 'delta_lift', 'n')}} for n, r in misti]

# --------------------------------------------------------------------------
# variante migliore su corr/lift: quanto si sposta score_atteso in media/p95/max
# confrontato con l'incertezza nota sulle soglie arena (+/-15 pt)
# --------------------------------------------------------------------------
print('\n' + '=' * 96)
print('SPOSTAMENTO DI score_atteso PER LA VARIANTE MIGLIORE SU CORR/LIFT vs incertezza soglie arena (+/-15pt)')
print('=' * 96)
candidate_per_corr_lift = [(nome, r) for nome, r in tutte_righe if r['delta_corr'] > 0 and r['delta_lift'] > 0]
if not candidate_per_corr_lift:
    candidate_per_corr_lift = tutte_righe
migliore_nome, migliore_r = max(candidate_per_corr_lift, key=lambda t: (t[1]['delta_corr'] + t[1]['delta_lift'] / 100))
print(f"  variante scelta: {migliore_nome}  (delta corr={migliore_r['delta_corr']:+.4f}, "
      f"delta lift={migliore_r['delta_lift']:+.2f}%, delta MAE={migliore_r['delta_mae']:+.4f})")

kwargs_migliore = {}
if migliore_nome.startswith('additiva'):
    kwargs_migliore = {'favorito_odds_k': float(migliore_nome.split('=')[1])}
elif migliore_nome.startswith('moltiplicativa'):
    kwargs_migliore = {'favorito_odds_mult_k': float(migliore_nome.split('=')[1])}
else:
    for etichetta, kwargs in scenari:
        if etichetta == migliore_nome:
            kwargs_migliore = kwargs
            break

delta_scores = []
for ruolo, slug, data, ctx, reale in punti:
    try:
        base_v = prev.calcola(ctx, half_life=PROD_HL, trend_intensity=PROD_TI)
        var_v = prev.calcola(ctx, half_life=PROD_HL, trend_intensity=PROD_TI, **kwargs_migliore)
    except Exception:
        continue
    if base_v is None or var_v is None:
        continue
    delta_scores.append(var_v - base_v)

if delta_scores:
    abs_delta = sorted(abs(d) for d in delta_scores)
    media = statistics.mean(abs_delta)
    p95 = abs_delta[int(0.95 * len(abs_delta))]
    massimo = abs_delta[-1]
    print(f"  |delta score_atteso| su n={len(delta_scores)}:  media={media:.2f}pt  p95={p95:.2f}pt  max={massimo:.2f}pt")
    print(f"  soglia arena nota: +/-15pt  ->  media e' il {100*media/15:.0f}% della soglia, "
          f"p95 e' il {100*p95/15:.0f}%, max e' il {100*massimo/15:.0f}%")
    risultati['spostamento_score_atteso'] = {
        'variante': migliore_nome, 'n': len(delta_scores),
        'media_pt': media, 'p95_pt': p95, 'max_pt': massimo,
        'pct_soglia_arena_media': 100*media/15, 'pct_soglia_arena_p95': 100*p95/15,
        'pct_soglia_arena_max': 100*massimo/15}
else:
    print('  nessun delta calcolabile')

SCRATCH = os.path.join(ROOT, "dati_globali")
with open(os.path.join(SCRATCH, 'esito_taratura_odds.json'), 'w', encoding='utf-8') as fh:
    json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)
print(f"\nsalvato in {os.path.join(SCRATCH, 'esito_taratura_odds.json')}")
