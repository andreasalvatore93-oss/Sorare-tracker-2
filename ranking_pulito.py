"""ranking_pulito — il ranking avversario misurato SOLO dove e' definito.

LA DOMANDA. Il segnale ranking (corr +0.074 col residuo dentro-giocatore) e'
stato congelato perche' il 24% delle righe di misura sta in condizioni in cui
domesticLeagueRanking non esiste, non e' confrontabile fra leghe diverse, o
non e' ancora informativo a inizio stagione (riverifica indipendente del
04/08, sezione 5). Il segnale non e' mai stato misurato dove e' pulito.

Qui si rifa' la misura sul solo sottoinsieme pulito:
  - stessa competizione, e stessa lega domestica per ENTRAMBE le squadre;
  - dimensione delle due leghe entro 2 squadre;
  - almeno 5 giornate gia' giocate in quella competizione e stagione.

E si confrontano DUE forme dello stesso segnale:
  - posizione assoluta in classifica;
  - PERCENTILE dentro la propria lega (posizione / numero di squadre), che e'
    la forma che risolve il problema delle leghe di dimensione diversa ed e'
    il vero test dell'ipotesi.

REGOLA DI LETTURA gia' fissata dall'utente (non la decido io):
  corr > +0.12 e il percentile fa meglio dell'assoluto -> il ranking non e' da
     buttare ma da normalizzare;
  corr < +0.09 -> congelamento definitivo;
  in mezzo -> resta aperto.

Nessuna applicazione alla produzione, qualunque sia il risultato.

Uso:  python ranking_pulito.py
"""
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

import backtest_arene_cache
import screening_segnali as ss
import segnale_dentro_giocatore as sdg

# stacco oltre il quale due partite della stessa squadra nella stessa
# competizione appartengono a due stagioni diverse
GIORNI_NUOVA_STAGIONE = 60
MIN_GIORNATE_GIOCATE = 5
MAX_DIFFERENZA_DIMENSIONE = 2
USCITA = os.path.join('dati_globali', 'ranking_pulito.json')


def anagrafica_competizioni(cache):
    """Per ogni competizione le squadre viste, e per ogni squadra la sua lega
    domestica (la competizione in cui gioca piu' spesso: le coppe sono sempre
    una minoranza delle partite di una squadra)."""
    squadre_per_comp = collections.defaultdict(set)
    comp_per_squadra = collections.defaultdict(collections.Counter)
    partite_squadra = collections.defaultdict(set)   # (squadra, comp) -> {(data, id)}
    visti = set()
    for slug in cache.slug_disponibili():
        for nodo in cache.gamelog(slug):
            g = nodo.get('anyGame') or {}
            gid = g.get('id')
            comp = (g.get('competition') or {}).get('slug')
            d = ss._quando(g.get('date'))
            if not gid or not comp or d is None or gid in visti:
                continue
            visti.add(gid)
            for lato in ('homeTeam', 'awayTeam'):
                t = (g.get(lato) or {}).get('slug')
                if not t:
                    continue
                squadre_per_comp[comp].add(t)
                comp_per_squadra[t][comp] += 1
                partite_squadra[(t, comp)].add((d, gid))
    dimensione = {c: len(s) for c, s in squadre_per_comp.items()}
    lega_di = {t: c.most_common(1)[0][0] for t, c in comp_per_squadra.items() if c}
    calendario = {k: sorted(v) for k, v in partite_squadra.items()}
    return dimensione, lega_di, calendario


def giornate_giocate(calendario, squadra, comp, quando):
    """Quante partite quella squadra aveva gia' giocato in quella competizione
    nella stessa stagione, prima di `quando`. None se non ricostruibile."""
    partite = calendario.get((squadra, comp))
    if not partite:
        return None
    inizio_stagione = None
    precedente = None
    conta = 0
    for d, _gid in partite:
        if d >= quando:
            break
        if precedente is not None and (d - precedente).days > GIORNI_NUOVA_STAGIONE:
            conta = 0
        precedente = d
        conta += 1
    return conta


def main():
    print('=' * 92)
    print('RANKING MISURATO SOLO DOVE E DEFINITO')
    print('=' * 92)
    cache = backtest_arene_cache.CacheLocale()
    percorso = os.path.join(ROOT, 'dati_globali', 'taratura_coppie.json')
    if os.path.exists(percorso):
        with open(percorso, encoding='utf-8') as fh:
            coppie = json.load(fh)
        print('%d coppie da taratura_coppie.json' % len(coppie))
    else:
        # su un runner pulito il file non c'e' (dati_globali/ e' in .gitignore):
        # si ricostruisce con LO STESSO codice che lo produce, non con una
        # raccolta scritta qui. Costa una mezz'ora di CPU, nessuna rete.
        print('taratura_coppie.json assente: lo ricostruisco con '
              'taratura_giocatore.raccogli (nessuna rete, ~30 minuti)', flush=True)
        import taratura_giocatore
        coppie = taratura_giocatore.raccogli(cache, sorted(cache.slug_disponibili()))
        os.makedirs(os.path.dirname(percorso), exist_ok=True)
        with open(percorso, 'w', encoding='utf-8') as fh:
            json.dump(coppie, fh, ensure_ascii=False)
        print('%d coppie ricostruite e salvate' % len(coppie))
    print('costruisco residui e segnali (riuso screening_segnali.prepara)...', flush=True)
    pronte, _mancanti = ss.prepara(coppie, cache, con_lambda=False)
    print('anagrafica competizioni...', flush=True)
    dimensione, lega_di, calendario = anagrafica_competizioni(cache)

    motivi = collections.Counter()
    for r in pronte:
        comp = r.get('competizione')
        mia, avv = r.get('squadra'), r.get('opp_slug')
        r['_pulita'] = False
        if r.get('rank_avversario') is None or r.get('rank_mio') is None:
            motivi['ranking assente'] += 1
            continue
        if not comp or not mia or not avv:
            motivi['competizione o squadre ignote'] += 1
            continue
        lega_mia, lega_avv = lega_di.get(mia), lega_di.get(avv)
        if lega_mia is None or lega_avv is None:
            motivi['lega di una squadra ignota'] += 1
            continue
        if lega_mia != lega_avv or comp != lega_mia:
            motivi['leghe diverse o partita non di campionato'] += 1
            continue
        n_mia, n_avv = dimensione.get(lega_mia), dimensione.get(lega_avv)
        if not n_mia or not n_avv or abs(n_mia - n_avv) > MAX_DIFFERENZA_DIMENSIONE:
            motivi['dimensione lega non confrontabile'] += 1
            continue
        gg = giornate_giocate(calendario, mia, comp, r.get('quando'))
        if gg is None or gg < MIN_GIORNATE_GIOCATE:
            motivi['meno di %d giornate giocate' % MIN_GIORNATE_GIOCATE] += 1
            continue
        r['_pulita'] = True
        r['rank_percentile'] = float(r['rank_avversario']) / float(n_avv)
        r['rank_percentile_diff'] = (float(r['rank_avversario']) / float(n_avv)
                                     - float(r['rank_mio']) / float(n_mia))

    pulite = [r for r in pronte if r['_pulita']]
    print('\n%d righe totali, %d pulite (%.1f%%)'
          % (len(pronte), len(pulite), 100.0 * len(pulite) / max(1, len(pronte))))
    print('scartate per:')
    for motivo, quante in motivi.most_common():
        print('  %-46s %7d  %5.1f%%' % (motivo, quante, 100.0 * quante / max(1, len(pronte))))

    segnali = [
        ('rank_avversario', 'posizione assoluta dell avversario'),
        ('rank_percentile', 'percentile dell avversario nella sua lega'),
        ('rank_percentile_diff', 'percentile avversario meno il mio'),
        ('rank_diff', 'posizione avversario meno la mia'),
    ]
    esiti = {}
    for campione, righe in (('pulito', pulite), ('tutto', pronte)):
        print('\nCAMPIONE %s (%d righe)' % (campione.upper(), len(righe)))
        print('  %-44s %7s %8s %20s %10s' % ('segnale', 'n', 'corr', 'IC 95%', 'guadagno'))
        for campo, etichetta in segnali:
            x, y = sdg.centra_per_giocatore(righe, campo)
            if len(x) < 50:
                print('  %-44s %7d   (campione insufficiente)' % (etichetta, len(x)))
                continue
            c = sdg._corr(x, y)
            lo, hi = sdg._ic_corr(x, y)
            g = sdg.guadagno_quintili(x, y)
            print('  %-44s %7d %+8.3f %20s %+9.1f pt'
                  % (etichetta, len(x), c,
                     '[%+.3f, %+.3f]' % (lo, hi) if lo is not None else '',
                     g if g is not None else 0.0))
            esiti['%s|%s' % (campione, campo)] = {
                'n': len(x), 'corr': c, 'ic_basso': lo, 'ic_alto': hi,
                'guadagno_quintili': g}

    ass = esiti.get('pulito|rank_avversario', {}).get('corr')
    pct = esiti.get('pulito|rank_percentile', {}).get('corr')
    print('\n' + '=' * 92)
    if ass is None or pct is None:
        verdetto = 'non misurabile: campione pulito troppo piccolo'
    else:
        migliore = max(ass, pct)
        if migliore > 0.12 and pct > ass:
            verdetto = ('SALE NETTAMENTE e il percentile batte l assoluto: il ranking '
                        'non e da buttare, e da NORMALIZZARE')
        elif migliore > 0.12:
            verdetto = ('sale sopra +0.12 ma il percentile NON batte l assoluto: '
                        'resta aperto, la normalizzazione non e la risposta')
        elif migliore < 0.09:
            verdetto = 'resta sotto +0.09: CONGELAMENTO DEFINITIVO'
        else:
            verdetto = 'fra +0.09 e +0.12: resta aperto, si decide coi numeri davanti'
    print('VERDETTO (regola di lettura fissata dall utente): %s' % verdetto)
    print('  assoluto %s   percentile %s   grezzo di riferimento +0.074'
          % ('%+.3f' % ass if ass is not None else '-',
             '%+.3f' % pct if pct is not None else '-'))

    with open(os.path.join(ROOT, USCITA), 'w', encoding='utf-8') as fh:
        json.dump({'n_totali': len(pronte), 'n_pulite': len(pulite),
                   'scartate': dict(motivi), 'esiti': esiti, 'verdetto': verdetto},
                  fh, ensure_ascii=False, indent=1)
    print('\nsalvato in %s' % USCITA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
