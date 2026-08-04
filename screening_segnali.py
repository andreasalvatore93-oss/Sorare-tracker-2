"""screening_segnali — quali variabili osservabili prima del calcio d'inizio
mordono il residuo DENTRO il giocatore.

PERCHE'. `tetto_prevedibilita.py` ha mostrato che il 94% della varianza sta
dentro lo stesso giocatore (quando rende sopra o sotto la propria media) e che
li' il modello ha correlazione -0.047: canale mai aperto. `segnale_dentro_
giocatore.py` ha provato i primi segnali sulle 2.690 righe di
`errore_storico.json`. Qui si rifa' lo stesso screening sul campione grande —
le 75.474 coppie previsione/realizzato walk-forward di `taratura_coppie.json` —
e si aggiungono le variabili che in quel file non erano state guardate
(starter odds storiche, ranking avversario grezzo).

NESSUNA MODIFICA AL MODELLO. E' solo un banco di misura: tutte le formule
arrivano da dove gia' esistono (`segnale_dentro_giocatore` per correlazione,
IC bootstrap, quintili e gol attesi; `modello_partita` per il Poisson;
`test_def.team_ranking_from_game` per il ranking).

RESIDUO. Come chiesto, centrato per giocatore su entrambi i lati:

    res = (realizzato - media_realizzato_del_giocatore)
        - (previsto   - media_prevista_del_giocatore)

cioe' quanto ha reso sopra/sotto se stesso, al netto di quanto il modello
diceva che avrebbe reso sopra/sotto se stesso. Giocatori con meno di
MIN_OSSERVAZIONI presenze scartati.

CUTOFF. Ogni segnale usa solo dati antecedenti al calcio d'inizio:
  - gol attesi: checkpoint settimanale walk-forward di `modello_partita`,
    stimato su partite STRETTAMENTE precedenti al checkpoint (<= data gara);
  - riposo: ultima partita del giocatore con data < data della gara;
  - ranking avversario: `domesticLeagueRanking` del blocco anyGame, che e' il
    ranking al momento della gara;
  - starter odds: vedi l'AVVERTENZA stampata a fine tabella.

Uso:  python screening_segnali.py
"""
import argparse
import collections
import datetime
import json
import os
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_mls', 'predict'))

import backtest_arene_cache
import segnale_dentro_giocatore as sdg
from test_def import team_ranking_from_game

# Almeno 8 osservazioni per giocatore: sotto quella soglia la media per
# giocatore e' rumore e il residuo centrato non significa niente.
MIN_OSSERVAZIONI = 8
# `centra_per_giocatore` e `congiunta` di sdg leggono la loro soglia da qui:
# si allinea, cosi' la logica riusata lavora sullo stesso campione.
sdg.MIN_PRESENZE = MIN_OSSERVAZIONI

COPPIE = os.path.join('dati_globali', 'taratura_coppie.json')
USCITA = os.path.join('dati_globali', 'screening_segnali.json')

SEGNALI = [
    ('favorito', 'lambda squadra meno lambda avversario'),
    ('lambda_squadra', 'gol attesi della mia squadra'),
    ('lambda_avversario', 'gol attesi dell avversario'),
    ('lambda_totale', 'gol attesi totali della partita'),
    ('casa', 'casa (1) o trasferta (0), grezzo'),
    ('riposo', 'giorni dall ultima partita'),
    ('starter_odds', 'starter odds del giocatore (0-1)'),
    ('rank_avversario', 'ranking avversario grezzo'),
    ('rank_mio', 'ranking della mia squadra'),
    ('rank_diff', 'ranking avversario meno il mio'),
]


def _quando(iso):
    try:
        return datetime.datetime.strptime(str(iso)[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def indice_gamelog(cache, slugs):
    """slug -> (partita_id -> nodo, [date ordinate]).

    Le date servono per il riposo; il nodo per avversario, ranking e odds."""
    fuori = {}
    for slug in slugs:
        per_id, date = {}, []
        for nodo in cache.gamelog(slug):
            g = nodo.get('anyGame') or {}
            d = _quando(g.get('date'))
            if d is None:
                continue
            date.append(d)
            if g.get('id'):
                per_id[g['id']] = nodo
        date.sort()
        fuori[slug] = (per_id, date)
    return fuori


def _riposo(date, quando):
    """Giorni dall'ultima partita STRETTAMENTE precedente al calcio d'inizio."""
    import bisect
    i = bisect.bisect_left(date, quando) - 1
    if i < 0:
        return None
    giorni = (quando - date[i]).days
    return float(giorni) if 0 <= giorni <= 40 else None


def prepara(coppie, cache):
    """Aggiunge a ogni riga il residuo e i segnali candidati.

    Il residuo finisce nella chiave 'res_reale' perche' e' quella che
    `sdg.centra_per_giocatore` legge come variabile da spiegare. Attenzione:
    qui dentro c'e' il residuo COMPLETO (reale meno previsto, entrambi
    centrati), non solo la parte reale come in `segnale_dentro_giocatore`."""
    per_slug = collections.defaultdict(list)
    for r in coppie:
        if r.get('previsto') is None or r.get('reale') is None:
            continue
        per_slug[r['slug']].append(r)

    indice = indice_gamelog(cache, list(per_slug))
    pronte, mancanti = [], collections.Counter()
    for slug, gruppo in per_slug.items():
        if len(gruppo) < MIN_OSSERVAZIONI:
            continue
        media_r = statistics.fmean(g['reale'] for g in gruppo)
        media_p = statistics.fmean(g['previsto'] for g in gruppo)
        per_id, date = indice.get(slug, ({}, []))
        for g in gruppo:
            g['res_reale'] = (g['reale'] - media_r) - (g['previsto'] - media_p)
            quando = _quando(g.get('data'))
            g['quando'] = quando
            if g.get('in_casa') is not None:
                g['casa'] = 1.0 if g['in_casa'] else 0.0
            if quando is None:
                pronte.append(g)
                continue
            r = _riposo(date, quando)
            if r is not None:
                g['riposo'] = r
            nodo = per_id.get(g.get('partita'))
            if nodo is None:
                mancanti['nodo'] += 1
            else:
                gioco = nodo.get('anyGame') or {}
                mio, avv, in_casa = team_ranking_from_game(gioco, g.get('squadra'))
                if mio is not None:
                    g['rank_mio'] = float(mio)
                if avv is not None:
                    g['rank_avversario'] = float(avv)
                if mio is not None and avv is not None:
                    g['rank_diff'] = float(avv) - float(mio)
                casa_slug = (gioco.get('homeTeam') or {}).get('slug')
                fuori_slug = (gioco.get('awayTeam') or {}).get('slug')
                if in_casa is True:
                    g['opp_slug'] = fuori_slug
                elif in_casa is False:
                    g['opp_slug'] = casa_slug
                stat = nodo.get('anyPlayerGameStats') or {}
                bp = (stat.get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
                if bp is not None:
                    g['starter_odds'] = float(bp) / 10000.0
                    g['_started'] = stat.get('gameStarted')
                else:
                    mancanti['odds'] += 1
            if g.get('opp_slug'):
                lam_mio, lam_avv = sdg.gol_attesi(g.get('squadra'), g['opp_slug'],
                                                  quando, bool(g.get('in_casa')))
                if lam_mio is not None:
                    g['lambda_squadra'] = lam_mio
                    g['lambda_avversario'] = lam_avv
                    g['lambda_totale'] = lam_mio + lam_avv
                    g['favorito'] = lam_mio - lam_avv
                else:
                    mancanti['lambda'] += 1
            pronte.append(g)
    return pronte, mancanti


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


def avvertenza_odds(pronte):
    """Le starter odds stanno nel game log SCARICATO DOPO la partita: se
    Sorare le aggiorna all'uscita delle formazioni ufficiali (che escono DOPO
    la deadline), il segnale e' pre-kickoff ma NON utilizzabile al momento in
    cui si schiera. Qui si stampa quanto e' estremo il dato, che e' l'indizio."""
    v = [(r['starter_odds'], r.get('_started')) for r in pronte
         if r.get('starter_odds') is not None]
    if not v:
        return None
    estremi = sum(1 for o, _ in v if o <= 0.001 or o >= 0.999) / len(v)
    con_flag = [(o, s) for o, s in v if s is not None]
    coerenza = None
    if len(con_flag) >= 50:
        coerenza = sum(1 for o, s in con_flag if (o >= 0.5) == (s == 1)) / len(con_flag)
    return {'n': len(v), 'quota_estremi': estremi, 'coerenza_con_titolarita': coerenza}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--coppie', default=COPPIE)
    ap.add_argument('--json', default=USCITA)
    ap.add_argument('--ruolo', default=None)
    args = ap.parse_args()

    percorso = args.coppie if os.path.isabs(args.coppie) else os.path.join(ROOT, args.coppie)
    if not os.path.exists(percorso):
        print(f'manca {percorso}: lancia prima  python taratura_giocatore.py')
        return 1
    with open(percorso, encoding='utf-8') as fh:
        coppie = json.load(fh)
    if args.ruolo:
        coppie = [c for c in coppie if c.get('ruolo') == args.ruolo]

    print('=' * 92)
    print('SCREENING SEGNALI — cosa prevede il residuo DENTRO il giocatore')
    print('=' * 92)
    print(f'{len(coppie)} coppie in ingresso, soglia {MIN_OSSERVAZIONI} presenze per giocatore')
    print('costruisco i checkpoint walk-forward dei gol attesi...', flush=True)

    cache = backtest_arene_cache.CacheLocale()
    pronte, mancanti = prepara(coppie, cache)
    if not pronte:
        print('nessuna riga utilizzabile')
        return 1
    sd = statistics.pstdev([r['res_reale'] for r in pronte])
    giocatori = len({r['slug'] for r in pronte})
    print(f'{len(pronte)} partite di {giocatori} giocatori')
    print(f'dispersione del residuo da spiegare: {sd:.1f} punti')
    if mancanti:
        print('dati non trovati: ' + ', '.join(f'{k}={v}' for k, v in sorted(mancanti.items())))

    risultati = []
    for campo, etichetta in SEGNALI:
        r = misura(pronte, campo)
        r['segnale'] = campo
        r['etichetta'] = etichetta
        risultati.append(r)
    risultati.sort(key=lambda r: abs(r.get('corr') or 0.0), reverse=True)

    print()
    print(f"  {'segnale':<38} {'n':>6} {'corr':>7} {'IC 95%':>18} {'guadagno':>10}")
    print('  ' + '-' * 82)
    for r in risultati:
        if r.get('corr') is None:
            print(f"  {r['etichetta']:<38} {r['n']:>6}   ({r.get('nota')})")
            continue
        ic = (f"[{r['ic_basso']:+.3f}, {r['ic_alto']:+.3f}]"
              if r.get('ic_basso') is not None else '')
        g = r.get('guadagno_quintili')
        gs = f'{g:+.1f} pt' if g is not None else ''
        print(f"  {r['etichetta']:<38} {r['n']:>6} {r['corr']:+7.3f} {ic:>18} {gs:>10}")

    print('\nguadagno = differenza di residuo medio fra il quinto piu alto e il quinto piu')
    print('basso del segnale, a parita di giocatore (segnale centrato per giocatore).')

    odds = avvertenza_odds(pronte)
    if odds:
        print(f"\nAVVERTENZA starter odds ({odds['n']} righe): quota di valori estremi "
              f"(0% o 100%) {odds['quota_estremi']:.1%}")
        if odds['coerenza_con_titolarita'] is not None:
            print(f"  coincidenza con la titolarita' effettiva: {odds['coerenza_con_titolarita']:.1%}")
        print('  il game log si scarica DOPO la partita: se Sorare aggiorna le odds')
        print("  all'uscita delle formazioni ufficiali, il valore e' pre-kickoff ma NON")
        print('  disponibile alla deadline. Da verificare su una giornata futura prima')
        print('  di usarlo come segnale.')

    uscita = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
    with open(uscita, 'w', encoding='utf-8') as fh:
        json.dump({'n_coppie': len(coppie), 'n_partite': len(pronte),
                   'n_giocatori': giocatori, 'min_osservazioni': MIN_OSSERVAZIONI,
                   'sd_residuo': sd, 'dati_mancanti': dict(mancanti),
                   'starter_odds_diagnostica': odds,
                   'segnali': risultati}, fh, ensure_ascii=False, indent=1)
    print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
