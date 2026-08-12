"""scomponi_portieri — di cosa e' fatto il punteggio di un portiere, voce per voce.

PERCHE'. Il modello prevede il punteggio di un portiere come
`level_score_atteso + granulari`, dove il level_score e' la base che Sorare
assegna (circa 35 senza clean sheet, circa 60 con clean sheet nei primi 60
minuti) e i granulari sono parate, uscite, passaggi, gol subiti.

Finche' si guarda solo il totale non si sa QUALE delle due parti sbaglia. Il
caso Takaoka della giornata 31 lug-4 ago: previsione 54.26, realizzato 37.70.
Sembra un errore da 16 punti sui granulari, e invece i granulari erano quasi
esatti (attesi 7.89, realizzati 7.70): tutto lo scarto stava nel level_score,
atteso 41.98 e uscito 35.0 -- cioe' il modello gli dava una probabilita'
apprezzabile di clean sheet, e il clean sheet non c'e' stato.

Questo script fa la stessa scomposizione per TUTTI i portieri di una giornata,
per capire se e' un caso isolato o il difetto sistematico del modulo portiere.

Il `detailedScore` va chiesto a Sorare (la cache di produzione non contiene le
partite giocate dopo l'ultima run). E' pubblico, ma con il cookie il tetto e'
60 query al minuto invece di 20: PAUSA=1.2 sta dentro.

Uso:
  python scomponi_portieri.py
  python scomponi_portieri.py --giornata football-31-jul-4-aug-2026 --json out.json
"""
import argparse
import datetime
import json
import os
import statistics
import sys
import time

import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))

import backtest_arene_cache
import backtest_arene_previsioni as P
import test_gk as G
from confronta_previsioni_giornata import finestra_giornata

APIKEY = os.environ.get('SORARE_APIKEY', '')  # 12/08/2026: alza il tetto di complessita' e di richieste dell'account

URL = 'https://api.sorare.com/graphql'
PAUSA = float(os.environ.get('PAUSA', '1.2'))
COOKIE = os.environ.get('SORARE_COOKIE', '')

DETTAGLIO = """
query Dettaglio($id: ID!) {
  node(id: $id) {
    ... on So5Score {
      score
      scoreStatus
      detailedScore { stat statValue totalScore }
    }
  }
}
"""


def intestazioni():
    h = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    if COOKIE:
        h['Cookie'] = COOKIE
    if APIKEY:
        h['APIKEY'] = APIKEY
        for pezzo in COOKIE.split(';'):
            pezzo = pezzo.strip()
            if pezzo.startswith('csrftoken='):
                h['X-CSRF-Token'] = pezzo.split('=', 1)[1]
    return h


def chiedi(score_id, tentativi=5):
    for i in range(tentativi):
        try:
            r = requests.post(URL, json={'query': DETTAGLIO, 'variables': {'id': score_id}},
                              headers=intestazioni(), timeout=30)
        except requests.RequestException:
            time.sleep(5)
            continue
        if r.status_code == 429:
            time.sleep(15 * (i + 1))
            continue
        try:
            d = r.json()
        except ValueError:
            time.sleep(5)
            continue
        nodo = (d.get('data') or {}).get('node')
        if nodo:
            return nodo
        time.sleep(5)
    return None


def previsione(cache, slug, fine_dt):
    """La previsione di produzione rigiocata all'indietro, con i suoi pezzi."""
    target = P.partita_target(cache, slug, fine_dt)
    if target is None:
        return None
    cutoff = P._data(target)
    competizione = ((target['anyGame'].get('competition') or {}).get('slug'))
    usable, presenza = P.finestra_storica(cache, slug, cutoff, competizione)
    if not usable:
        return None
    squadra = P._squadra(usable, competizione)
    _own, _opp, casa = G.team_ranking_from_game(target['anyGame'], squadra)
    s = P._serie(G, cache, slug, usable, squadra)
    n = len(s['scores'])
    pesi = G.exponential_weights(n, G.HALF_LIFE_GAMES)
    granulari = G.weighted_mean(s['granulari'], pesi)
    lam_pos = G.weighted_mean(s['pos_dec'], pesi)
    lam_neg = G.weighted_mean(s['neg_dec'], pesi)
    livello = G.expected_level_from_rates(lam_pos, lam_neg)
    trend, _a, _b = G.compute_trend_factor(s['granulari'], 5, 10, G.TREND_INTENSITY)
    prior = max(0.0, 46.20 + 4.05 * presenza) if presenza is not None else G.MEDIA_RUOLO_GK_PRIOR
    k = G.SHRINK_K_OUTLIER_GK
    grezzo = livello + granulari * trend
    corretto = (n / (n + k)) * grezzo + (k / (n + k)) * prior
    venue = G.venue_factor_gk(s['scores'], s['is_home'], casa, pesi)
    return {'atteso': corretto * venue, 'livello_atteso': livello,
            'granulari_attesi': granulari, 'prior': prior, 'venue': venue,
            'n': n, 'in_casa': casa, 'score_id': target.get('id')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('--giornata', default='football-31-jul-4-aug-2026')
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    with open(os.path.join(ROOT, 'dati_globali', f'manager_{args.manager}.json'), encoding='utf-8') as f:
        formazioni = json.load(f)['giornate'][args.giornata]
    _inizio, fine = finestra_giornata(args.giornata)
    fine_dt = datetime.datetime.combine(fine, datetime.time(23, 59))
    cache = backtest_arene_cache.CacheLocale()

    portieri = {}
    for f in formazioni:
        for c in f['carte']:
            if c['ruolo'] == 'Goalkeeper' and c['slug'] not in portieri:
                portieri[c['slug']] = c['nome']

    righe, senza = [], []
    for slug, nome in portieri.items():
        pr = previsione(cache, slug, fine_dt)
        if pr is None or not pr.get('score_id'):
            senza.append(nome)
            continue
        nodo = chiedi(pr['score_id'])
        time.sleep(PAUSA)
        if nodo is None:
            senza.append(nome)
            continue
        voci = {e['stat']: e for e in (nodo.get('detailedScore') or [])}
        livello = (voci.get('level_score') or {}).get('totalScore')
        if livello is None:
            senza.append(nome)
            continue
        granulari = sum((e.get('totalScore') or 0.0) for k, e in voci.items()
                        if k not in ('level_score', 'mins_played'))
        righe.append({
            'slug': slug, 'nome': nome,
            'reale': nodo.get('score'), 'stato': nodo.get('scoreStatus'),
            'livello_reale': livello, 'granulari_reali': granulari,
            'minuti': (voci.get('mins_played') or {}).get('statValue'),
            'gol_subiti': (voci.get('goals_conceded') or {}).get('statValue') or 0,
            'atteso': pr['atteso'], 'livello_atteso': pr['livello_atteso'],
            'granulari_attesi': pr['granulari_attesi'],
            'prior': pr['prior'], 'venue': pr['venue'], 'n': pr['n'],
        })

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(righe, f, ensure_ascii=False, indent=1)
    _stampa(righe, senza)
    return 0


def _stampa(righe, senza):
    if not righe:
        print('nessun portiere ricostruito')
        return
    print(f'{len(righe)} portieri' + (f'   ({len(senza)} non ricostruiti: '
                                      + ', '.join(senza[:6]) + ')' if senza else ''))
    print()
    print(f"{'portiere':<24}{'gol':>4}{'LIV att':>9}{'LIV vero':>9}{'GRA att':>9}{'GRA vero':>9}"
          f"{'previsto':>10}{'reale':>8}{'errore':>8}")
    for r in sorted(righe, key=lambda x: x['reale'] - x['atteso']):
        print(f"  {r['nome'][:22]:<22}{r['gol_subiti']:>4.0f}{r['livello_atteso']:>9.1f}"
              f"{r['livello_reale']:>9.1f}{r['granulari_attesi']:>9.1f}{r['granulari_reali']:>9.1f}"
              f"{r['atteso']:>10.1f}{r['reale']:>8.1f}{r['reale'] - r['atteso']:>+8.1f}")

    err_liv = [r['livello_reale'] - r['livello_atteso'] for r in righe]
    err_gra = [r['granulari_reali'] - r['granulari_attesi'] for r in righe]
    err_tot = [r['reale'] - r['atteso'] for r in righe]
    print()
    print(f"errore medio assoluto  totale {statistics.fmean(abs(e) for e in err_tot):5.1f}"
          f"   di cui level_score {statistics.fmean(abs(e) for e in err_liv):5.1f}"
          f"   granulari {statistics.fmean(abs(e) for e in err_gra):5.1f}")
    print(f"bias                   totale {statistics.fmean(err_tot):+5.1f}"
          f"   level_score {statistics.fmean(err_liv):+5.1f}"
          f"   granulari {statistics.fmean(err_gra):+5.1f}")
    puliti = [r for r in righe if r['gol_subiti'] == 0]
    print(f"\nclean sheet: {len(puliti)} su {len(righe)}"
          f"   level_score medio con clean sheet "
          f"{statistics.fmean([r['livello_reale'] for r in puliti]) if puliti else float('nan'):.1f}"
          f"   senza {statistics.fmean([r['livello_reale'] for r in righe if r['gol_subiti'] > 0]):.1f}")


if __name__ == '__main__':
    sys.exit(main())
