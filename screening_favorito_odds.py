"""Test separato, NESSUNA modifica a screening_segnali.py / pipeline.
Confronta favorito interno (lambda) vs favorito_odds (1X2 esterno) sullo
STESSO sottoinsieme di taratura_coppie.json con winOddsBasisPoints disponibile.

PRIMO screening del filone favorito_odds (05/08): ha dato il via libera
(corr +0.114 vs +0.056, R2 incrementale +0.58%) a taratura_confronto_odds.py,
che poi ha misurato la cosa giusta (score_atteso, non solo il residuo) con
criterio severo. Risultato SUPERATO da quello: vedi
docs/handoff/HANDOFF_FAVORITO_ODDS_2026-08-06.txt.

NOTA RIPRODUCIBILITA': richiede dati_globali/odds_by_gameid.json (dump grezzo
per game-id delle quote 1X2, estratto via So5Fixture->anyGames in bulk per
fixture) che NON e' stato salvato nel repo in questa sessione (solo l'INDICE
gia' aggregato dati_globali/odds_1x2_index.json e' stato committato). Per
rilanciare questo script servirebbe rifare l'estrazione bulk (vedi
lo storico della sessione per la query esatta) o adattarlo a leggere
odds_1x2_index.json (formato diverso, chiave team|team|data invece che
per game-id).
"""
import sys, os, json, collections, statistics

ROOT = r"C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))

import backtest_arene_cache
import segnale_dentro_giocatore as sdg
from screening_segnali import prepara, MIN_OSSERVAZIONI

SCRATCH = os.path.join(ROOT, "dati_globali")

sdg.MIN_PRESENZE = MIN_OSSERVAZIONI

with open(os.path.join(ROOT, 'dati_globali', 'taratura_coppie.json'), encoding='utf-8') as fh:
    coppie = json.load(fh)

with open(os.path.join(SCRATCH, 'odds_by_gameid.json'), encoding='utf-8') as fh:
    odds_by_id = json.load(fh)

print(f'coppie totali: {len(coppie)}')
print(f'giochi con odds estratti: {len(odds_by_id)}')

# dedup (slug, partita) -- 8.15
seen = set()
dedup = []
for r in coppie:
    key = (r.get('slug'), r.get('partita'))
    if key in seen:
        continue
    seen.add(key)
    dedup.append(r)
print(f'dopo dedup (slug,partita): {len(dedup)} (rimosse {len(coppie)-len(dedup)})')

cache = backtest_arene_cache.CacheLocale()
pronte, mancanti = prepara(dedup, cache)
print(f'pronte (dopo prepara, soglia {MIN_OSSERVAZIONI} presenze): {len(pronte)}')
print('mancanti:', dict(mancanti))

# aggiungo le feature dalle quote esterne
n_odds_ok = 0
n_eliteserien = 0
for r in pronte:
    gid = r.get('partita')
    g = odds_by_id.get(gid)
    if g is None:
        continue
    lg = (g.get('homeTeam') or {}).get('domesticLeague', {})
    lg_slug = lg.get('slug') if isinstance(lg, dict) else None
    if lg_slug == 'eliteserien':
        n_eliteserien += 1
        continue
    ho = (g.get('homeStats') or {}).get('winOddsBasisPoints')
    ao = (g.get('awayStats') or {}).get('winOddsBasisPoints')
    if ho is None or ao is None:
        continue
    p_home = ho / 10000.0
    p_away = ao / 10000.0
    p_draw = 1.0 - p_home - p_away
    in_casa = r.get('in_casa')
    if in_casa is True:
        p_own, p_opp = p_home, p_away
    elif in_casa is False:
        p_own, p_opp = p_away, p_home
    else:
        continue
    r['p_win_own'] = p_own
    r['p_win_opp'] = p_opp
    r['p_draw'] = p_draw
    r['favorito_odds'] = p_own - p_opp
    n_odds_ok += 1

print(f'righe con odds valide (esclusa eliteserien): {n_odds_ok}')
print(f'righe escluse per eliteserien: {n_eliteserien}')

sottoinsieme = [r for r in pronte if r.get('favorito_odds') is not None]
print(f'\nSOTTOINSIEME PAIRED (odds + lambda + rank disponibili dove richiesto): {len(sottoinsieme)}')
date_min = min(r['data'] for r in sottoinsieme if r.get('data'))
date_max = max(r['data'] for r in sottoinsieme if r.get('data'))
print(f'range date: {date_min} .. {date_max}')
print(f'giocatori unici: {len({r["slug"] for r in sottoinsieme})}')


def misura(pronte, campo):
    x, y = sdg.centra_per_giocatore(pronte, campo)
    if len(x) < 50:
        return {'n': len(x), 'nota': 'campione insufficiente'}
    c = sdg._corr(x, y)
    if c is None:
        return {'n': len(x), 'nota': 'segnale costante'}
    lo, hi = sdg._ic_corr(x, y)
    return {'n': len(x), 'corr': c, 'ic_basso': lo, 'ic_alto': hi,
            'guadagno_quintili': sdg.guadagno_quintili(x, y)}


print('\n' + '=' * 92)
print('MISURA SINGOLA (sullo stesso sottoinsieme paired) -- baseline interna vs odds')
print('=' * 92)
for campo in ('favorito', 'favorito_odds', 'rank_avversario', 'casa'):
    r = misura(sottoinsieme, campo)
    r['segnale'] = campo
    if r.get('corr') is None:
        print(f"  {campo:<20} n={r['n']:>6}   ({r.get('nota')})")
    else:
        print(f"  {campo:<20} n={r['n']:>6}  corr={r['corr']:+.3f}  "
              f"IC95=[{r['ic_basso']:+.3f}, {r['ic_alto']:+.3f}]  "
              f"guadagno={r.get('guadagno_quintili')}")


def _r2(colonne, y, indici=None):
    if indici is not None:
        colonne = [[c[i] for i in indici] for c in colonne]
        y = [y[i] for i in indici]
    beta = sdg._ols(colonne, y)
    if beta is None:
        return None, None
    stimato = [sum(b * col[t] for b, col in zip(beta, colonne)) for t in range(len(y))]
    c = sdg._corr(stimato, y)
    return (c ** 2 if c is not None else None), beta


def congiunta_estesa(pronte, campi, ripetizioni=200, seme=0, etichetta=''):
    print('\n' + '-' * 92)
    print(f'REGRESSIONE CONGIUNTA [{etichetta}]  campi={campi}')
    print('-' * 92)
    per_slug = collections.defaultdict(list)
    for r in pronte:
        if all(r.get(c) is not None for c in campi):
            per_slug[r['slug']].append(r)
    righe = [g for gruppo in per_slug.values() if len(gruppo) >= MIN_OSSERVAZIONI for g in gruppo]
    if not righe:
        print('  nessuna riga con tutti i campi presenti')
        return None
    colonne = [sdg.centra_per_giocatore(righe, c)[0] for c in campi]
    y = sdg.centra_per_giocatore(righe, campi[0])[1]
    if any(len(c) != len(righe) for c in colonne) or len(y) != len(righe):
        print('  allineamento fallito')
        return None
    n = len(righe)
    r2_pieno, beta = _r2(colonne, y)
    if r2_pieno is None:
        print('  sistema singolare')
        return None

    import random
    per_giornata = collections.defaultdict(list)
    for i, r in enumerate(righe):
        per_giornata[str(r.get('data'))[:10]].append(i)
    grappoli = list(per_giornata.values())
    rng = random.Random(seme)
    campioni = [[] for _ in campi]
    for _ in range(ripetizioni):
        idx = []
        for _ in range(len(grappoli)):
            idx.extend(grappoli[rng.randrange(len(grappoli))])
        b = sdg._ols([[c[i] for i in idx] for c in colonne], [y[i] for i in idx])
        if b is None:
            continue
        for j, v in enumerate(b):
            campioni[j].append(v)

    print(f'  n={n}  giornate={len(grappoli)}  bootstrap x{ripetizioni}')
    print(f"  {'variabile':<20} {'coeff':>9} {'IC 95%':>22} {'R2 aggiunto':>12}")
    esiti = []
    for j, campo in enumerate(campi):
        resto = [c for k, c in enumerate(colonne) if k != j]
        r2_senza, _ = _r2(resto, y) if resto else (0.0, None)
        incremento = r2_pieno - (r2_senza or 0.0)
        v = sorted(campioni[j])
        lo = v[int(0.025 * len(v))] if len(v) >= 50 else None
        hi = v[int(0.975 * len(v)) - 1] if len(v) >= 50 else None
        ic = f'[{lo:+.3f}, {hi:+.3f}]' if lo is not None else ''
        print(f"  {campo:<20} {beta[j]:+9.4f} {ic:>22} {incremento:>11.5%}")
        esiti.append({'campo': campo, 'coefficiente': beta[j], 'ic_basso': lo,
                      'ic_alto': hi, 'r2_incrementale': incremento})
    print(f'  R2 modello completo: {r2_pieno:.4%}  (n={n})')
    return {'n': n, 'n_giornate': len(grappoli), 'r2_totale': r2_pieno, 'variabili': esiti}


risultati = {}
risultati['baseline_interna_ridotta'] = congiunta_estesa(
    sottoinsieme, ('rank_avversario', 'casa', 'favorito'),
    etichetta='BASELINE INTERNA su sottoinsieme ridotto (stesso campione delle altre)')

risultati['solo_favorito_confronto'] = congiunta_estesa(
    sottoinsieme, ('favorito', 'favorito_odds'),
    etichetta='favorito interno vs favorito_odds, uno contro l\'altro')

risultati['odds_aggiunto_sopra_baseline'] = congiunta_estesa(
    sottoinsieme, ('rank_avversario', 'casa', 'favorito', 'favorito_odds'),
    etichetta='favorito_odds aggiunto SOPRA rank_avversario+casa+favorito')

risultati['solo_odds'] = congiunta_estesa(
    sottoinsieme, ('rank_avversario', 'casa', 'favorito_odds'),
    etichetta='favorito_odds al posto di favorito (stessa baseline)')

with open(os.path.join(SCRATCH, 'risultato_favorito_odds.json'), 'w', encoding='utf-8') as fh:
    json.dump(risultati, fh, ensure_ascii=False, indent=1, default=str)

print('\nsalvato in', os.path.join(SCRATCH, 'risultato_favorito_odds.json'))
