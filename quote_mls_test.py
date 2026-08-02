"""quote_mls_test — le quote dei bookmaker aggiungono qualcosa al modello? (prova su MLS)

LA DOMANDA. Il modello sa dire il LIVELLO di un giocatore ma quasi niente sulla
singola partita: un portiere previsto a 50 ne fa in media 48, ma il caso singolo
sbaglia di 15 punti e meta' delle volte finisce fra 36 e 60. Tutto cio' che il
modello sa della partita viene dallo storico dell'avversario
(`opponent_strength`, gol reali). Le quote sono l'unica informazione sulla
singola partita mai provata in questo progetto -- la checklist maestra
(sezione 0 del riassunto) non le contiene.

PRIMA DI COSTRUIRE QUALUNQUE COSA, la prova minima e decisiva: **le quote
spiegano qualcosa che il modello non sa gia'?** Se la correlazione fra quota e
punteggio reale sparisce una volta tolto quello che il modello prevede gia',
non c'e' niente da agganciare e ci si ferma qui.

LA FONTE. football-data.co.uk, archivio "new leagues", file USA.csv: gratuito,
senza chiave, quote di CHIUSURA (le piu' informative) partita per partita.
Colonne usate: AvgCH/AvgCD/AvgCA = media di mercato su 1/X/2. Verificato:
marzo-maggio 2026 coperti, giugno 2026 MANCA, luglio parziale.

IL PUNTO FRAGILE. L'abbinamento dei nomi squadra: Sorare usa
`colorado-rapids-commerce-city-colorado`, il CSV usa `Colorado Rapids`. Lo
script lo costruisce da solo per sovrapposizione di parole e lo STAMPA tutto,
perche' un abbinamento sbagliato produce numeri plausibili e falsi.

Uso:
  python quote_mls_test.py --csv <percorso>/USA.csv --solo-mappa
  python quote_mls_test.py --csv <percorso>/USA.csv
"""
import argparse
import collections
import csv
import datetime
import json
import math
import os
import statistics
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as P
from errore_modello_storico import fine_giornate, lega_per_slug, CAPITANO_ARENA

# parole che compaiono in quasi tutti gli slug Sorare e non identificano nulla
RUMORE = {'fc', 'sc', 'cf', 'club', 'city', 'united', 'utd', 'new', 'real',
          'de', 'the', 'usa', 'us'}


def parole(testo):
    pezzi = testo.lower().replace('-', ' ').replace('.', ' ').split()
    return {p for p in pezzi if p not in RUMORE and len(p) > 2}


# Abbinamenti che l'automatismo sbaglia, corretti a mano dopo averli visti.
# 'rb' sta in una sigla di due lettere e viene scartato come rumore, quindi i
# Red Bulls finivano su New York City: numero plausibile, squadra sbagliata.
MANUALI = {
    'new-york-rb-secaucus-new-jersey': 'New York Red Bulls',
}


def costruisci_mappa(slug_sorare, nomi_csv):
    """slug Sorare -> nome nel CSV, per sovrapposizione di parole.

    Restituisce anche i casi ambigui/mancati, che vanno guardati a occhio: un
    abbinamento sbagliato non da' errore, da' un numero sbagliato."""
    mappa, dubbi = {}, []
    for slug in sorted(slug_sorare):
        if slug in MANUALI:
            mappa[slug] = MANUALI[slug]
            continue
        ps = parole(slug)
        punteggi = []
        for nome in nomi_csv:
            comuni = ps & parole(nome)
            if comuni:
                punteggi.append((len(comuni), -len(parole(nome)), nome))
        punteggi.sort(reverse=True)
        if not punteggi:
            dubbi.append((slug, None, 'nessun candidato'))
            continue
        migliore = punteggi[0]
        secondo = punteggi[1] if len(punteggi) > 1 else None
        if secondo and secondo[0] == migliore[0]:
            dubbi.append((slug, migliore[2], f'ambiguo con {secondo[2]}'))
        mappa[slug] = migliore[2]
    return mappa, dubbi


def leggi_quote(percorso):
    """(nome_casa, nome_fuori, data) -> probabilita' senza margine del bookmaker."""
    fuori = {}
    nomi = set()
    with open(percorso, encoding='utf-8-sig') as f:
        for riga in csv.DictReader(f):
            try:
                data = datetime.datetime.strptime(riga['Date'], '%d/%m/%Y').date()
            except (ValueError, KeyError):
                continue
            nomi.add(riga['Home'])
            nomi.add(riga['Away'])
            try:
                q = [float(riga['AvgCH']), float(riga['AvgCD']), float(riga['AvgCA'])]
            except (ValueError, KeyError, TypeError):
                continue
            grezze = [1.0 / v for v in q if v > 0]
            if len(grezze) != 3:
                continue
            somma = sum(grezze)          # >1: e' il margine del bookmaker
            p_casa, p_pari, p_fuori = [v / somma for v in grezze]
            fuori[(riga['Home'], riga['Away'], data)] = {
                'p_casa': p_casa, 'p_pari': p_pari, 'p_fuori': p_fuori,
                'gol_casa': riga.get('HG'), 'gol_fuori': riga.get('AG'),
            }
    return fuori, nomi


def _corr(x, y):
    if len(x) < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def _residui(x, y):
    """y meno la parte spiegata da x: serve a chiedersi se le quote aggiungono
    qualcosa DOPO il modello, invece che sovrapporsi a lui."""
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return list(y)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    a0 = my - b * mx
    return [c - (a0 + b * v) for v, c in zip(x, y)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True, help='USA.csv di football-data.co.uk')
    ap.add_argument('--da', default='2026-02-01')
    ap.add_argument('--a', default='2026-06-01')
    ap.add_argument('--solo-mappa', action='store_true',
                    help='stampa solo l\'abbinamento delle squadre e si ferma')
    args = ap.parse_args()

    quote, nomi_csv = leggi_quote(args.csv)
    da = datetime.date.fromisoformat(args.da)
    a = datetime.date.fromisoformat(args.a)

    with open(os.path.join(ROOT, 'dati_globali', 'arene_formazioni.json'), encoding='utf-8') as f:
        formazioni = (json.load(f) or {})['formazioni']
    fine = fine_giornate()
    cache = backtest_arene_cache.CacheLocale()
    lega_di = lega_per_slug()

    # osservazioni MLS nella finestra coperta dalle quote
    osservazioni = []
    visti = set()
    memo = {}
    for v in formazioni.values():
        fd = fine.get(v['fixture'])
        if fd is None or not (da <= fd.date() <= a):
            continue
        for g in v['giocatori']:
            if lega_di.get(g['slug']) != 'mls':
                continue
            chiave = (v['fixture'], g['carta'])
            if chiave in visti:
                continue
            visti.add(chiave)
            reale = g.get('punteggio')
            if not reale:
                continue
            if g.get('capitano'):
                reale = reale / (1.0 + CAPITANO_ARENA)
            k = (g['slug'], g['ruolo'], v['fixture'])
            if k not in memo:
                memo[k] = P.score_atteso(cache, g['slug'], g['ruolo'], fd)
            r = memo[k]
            if r is None or r.get('atteso') is None or not r.get('squadra'):
                continue
            osservazioni.append({'slug': g['slug'], 'nome': g['nome'], 'ruolo': g['ruolo'],
                                 'atteso': r['atteso'], 'reale': reale,
                                 'squadra': r['squadra'], 'in_casa': r.get('in_casa'),
                                 'data': r['data_partita'].date() if r.get('data_partita') else None})

    squadre = {o['squadra'] for o in osservazioni if o['squadra']}
    mappa, dubbi = costruisci_mappa(squadre, nomi_csv)

    print('=' * 74)
    print('ABBINAMENTO SQUADRE (guardalo: un abbinamento sbagliato non da\' errore)')
    print('=' * 74)
    for slug in sorted(mappa):
        print(f"  {slug[:44]:44s} -> {mappa[slug]}")
    for slug, nome, motivo in dubbi:
        print(f"  DUBBIO  {slug[:40]:40s} -> {nome}   ({motivo})")
    print(f"\n{len(mappa)} squadre abbinate, {len(dubbi)} da controllare, "
          f"{len(osservazioni)} osservazioni MLS nella finestra")
    if args.solo_mappa:
        return 0

    righe = []
    mancate = collections.Counter()
    for o in osservazioni:
        nome = mappa.get(o['squadra'])
        if not nome or not o['data']:
            mancate['senza squadra o data'] += 1
            continue
        trovata = None
        for scarto in (0, -1, 1):
            giorno = o['data'] + datetime.timedelta(days=scarto)
            for (casa, fuor, d), q in quote.items():
                if d != giorno:
                    continue
                if casa == nome:
                    trovata = (q['p_casa'], q['p_fuori'], True)
                    break
                if fuor == nome:
                    trovata = (q['p_fuori'], q['p_casa'], False)
                    break
            if trovata:
                break
        if not trovata:
            mancate['partita non trovata nel CSV'] += 1
            continue
        p_vince, p_perde, _casa = trovata
        o['p_vince'] = p_vince
        o['p_perde'] = p_perde
        righe.append(o)

    print(f"\nagganciate alle quote: {len(righe)}   "
          + ', '.join(f'{v} {k}' for k, v in mancate.most_common()))
    if len(righe) < 30:
        print('troppo poche per dire qualcosa. Mi fermo.')
        return 1

    print('\n' + '=' * 74)
    print('LE QUOTE AGGIUNGONO QUALCOSA?')
    print('=' * 74)
    for etichetta, sotto in [('TUTTI', righe)] + [
            (r, [x for x in righe if x['ruolo'] == r])
            for r in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward')]:
        if len(sotto) < 25:
            continue
        reale = [x['reale'] for x in sotto]
        atteso = [x['atteso'] for x in sotto]
        pv = [x['p_vince'] for x in sotto]
        residuo = _residui(atteso, reale)
        c_modello = _corr(atteso, reale)
        c_quote = _corr(pv, reale)
        c_extra = _corr(pv, residuo)
        print(f"\n{etichetta}  (n={len(sotto)})")
        print(f"  modello -> reale                      {c_modello:+.3f}")
        print(f"  probabilita' di vittoria -> reale     {c_quote:+.3f}")
        print(f"  probabilita' -> cio' che il modello NON spiega   {c_extra:+.3f}"
              f"   <- se e' ~0, le quote non servono")
    return 0


if __name__ == '__main__':
    sys.exit(main())
