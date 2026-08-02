"""ottimizza_giornata — col senno di poi, dove dovevano andare le carte.

LA DOMANDA. In una giornata si schierano decine di formazioni in competizioni
diverse, con le stesse carte. Il modello decide chi va dove. Conoscendo i
punteggi in anticipo, quanto meglio si poteva fare con le STESSE carte e le
STESSE formazioni? Quella distanza e' cio' che il modello si e' mangiato.

IL PUNTO CHE NON E' OVVIO, E CHE DECIDE COSA HA SENSO OTTIMIZZARE. Quasi ogni
carta viene schierata da qualche parte comunque, quindi la somma dei punteggi
GREZZI e' un invariante: non dipende dall'allocazione. Cio' che dipende
dall'allocazione sono i bonus, che non valgono uguale ovunque:

    punteggio carta = grezzo x (1 + bonus_carta + bonus_formazione + capitano)

Bonus carta e bonus formazione esistono SOLO in In Season, All Star e Under 23;
in arena sono zero e resta il solo capitano (+20% invece di +50%). Vedi
`punteggi_grezzi.py` per la regola completa e per come si ricava senza indovinare.

Quindi il conto si scompone in tre voci separate e verificabili una per una:

    totale = somma dei grezzi          <- invariante
           + bonus incassati           <- dipende da CHI finisce dove
           + guadagno del capitano     <- dipende da CHI porta la fascia

DUE ASSUNZIONI, dichiarate perche' cambiano il risultato:

  1. I bonus di FORMAZIONE (+2% multi-club, +4% cap) restano quelli davvero
     ottenuti. Spostando carte potrebbero cambiare: il multi-club viene
     imposto come vincolo (mai 3 dello stesso club), mentre il +4% del cap
     dipende dalla somma L10, che non e' ricostruibile con la precisione che
     una soglia netta richiede -- provato: sbaglia in entrambe le direzioni.
     Quindi il cap non viene ne' inseguito ne' perso: e' tenuto fermo.
  2. Le arene possono restare scoperte (scelta esplicita dell'utente): se una
     carta serve altrove, l'arena da cui esce non viene riempita d'ufficio.

VINCOLI RISPETTATI, letti dal codice di produzione o dai dati, mai dedotti:
forma della formazione come schierata; pool per competizione
(POOL_LEAGUE_BY_TYPE: In Season MLS solo MLS, K-League solo coreani, arena
dedicata solo quella lega, Under 23 solo u23Eligible, All Star pool misto);
almeno 4 carte in season su 5 nelle In Season (`inSeasonEligible` per CARTA,
chiesto a Sorare); una carta, un uso.

Uso:
  python ottimizza_giornata.py
  python ottimizza_giornata.py --giornata football-31-jul-4-aug-2026 --json out.json
"""
import argparse
import collections
import glob
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import punteggi_grezzi

REGOLE = [
    ('in_season_us_',    {'xp': True,  'cap': 1.5, 'pool': 'mls',     'min_in_season': 4, 'tipo': 'In Season MLS'}),
    ('in_season_korea_', {'xp': True,  'cap': 1.5, 'pool': 'kleague', 'min_in_season': 4, 'tipo': 'In Season K-League'}),
    ('under_twenty_one', {'xp': True,  'cap': 1.5, 'pool': 'u23',     'min_in_season': 0, 'tipo': 'Under 23'}),
    ('all_star_arena_limited_beginner', {'xp': False, 'cap': 1.2, 'pool': None, 'min_in_season': 0, 'tipo': 'Beginner'}),
    ('all_star_arena_limited_cap_220',  {'xp': False, 'cap': 1.2, 'pool': None, 'min_in_season': 0, 'tipo': 'Arena cap 220'}),
    ('all_star_arena_limited_uncapped', {'xp': False, 'cap': 1.2, 'pool': None, 'min_in_season': 0, 'tipo': 'Arena uncapped'}),
    ('all_star_arena_limited',          {'xp': False, 'cap': 1.2, 'pool': None, 'min_in_season': 0, 'tipo': 'Arena cap 260'}),
    ('us_arena_limited',    {'xp': False, 'cap': 1.2, 'pool': 'mls',     'min_in_season': 0, 'tipo': 'Arena MLS'}),
    ('korea_arena_limited', {'xp': False, 'cap': 1.2, 'pool': 'kleague', 'min_in_season': 0, 'tipo': 'Arena K-League'}),
    ('all_star_limited',    {'xp': True,  'cap': 1.5, 'pool': None,      'min_in_season': 0, 'tipo': 'All Star'}),
]


def regole(leaderboard):
    for frammento, r in REGOLE:
        if frammento in leaderboard:
            return r
    return None


def lega_per_slug():
    """La lega di ogni giocatore: la cartella da cui viene la sua previsione di
    produzione. `player_card_counts.json` NON va bene -- contiene solo il pool
    della run piu' recente, quindi per una giornata passata manca quasi tutto."""
    fuori = {}
    for percorso in glob.glob(os.path.join(ROOT, 'formazione_*', 'output', '*', 'prediction_log*.json')):
        lega = os.path.normpath(percorso).split(os.sep)[-4].replace('formazione_', '')
        try:
            with open(percorso, encoding='utf-8') as f:
                dati = json.load(f) or {}
        except (ValueError, OSError):
            continue
        for voce in dati.values():
            fuori.setdefault(voce.get('player_slug'), lega)
    return fuori


def ammessa(carta, r):
    if r['pool'] == 'u23':
        return carta['u23']
    if r['pool'] is None:
        return True
    return carta['lega'] == r['pool']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('--giornata', default='football-31-jul-4-aug-2026')
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    with open(os.path.join(ROOT, 'dati_globali', f'manager_{args.manager}.json'), encoding='utf-8') as f:
        tutte = json.load(f)['giornate'][args.giornata]
    _note, annullate = punteggi_grezzi.carica_note()
    formazioni = [f for f in tutte if f['contender'] not in annullate]

    print('=' * 74)
    print(f'OTTIMO COL SENNO DI POI — {args.giornata}')
    print('=' * 74)
    if len(formazioni) != len(tutte):
        print(f'escluse {len(tutte) - len(formazioni)} formazioni annullate in corsa dall\'utente')

    ignote = {f['leaderboard'] for f in formazioni if regole(f['leaderboard']) is None}
    if ignote:
        print('FERMO: competizioni che non so classificare. Non calcolo niente.')
        for s in sorted(ignote):
            print('  ' + s)
        return 1

    grezzi, bonus_f, irrisolte = punteggi_grezzi.risolvi(formazioni, regole)
    if irrisolte:
        print(f'FERMO: {len(irrisolte)} formazioni con bonus non ricavabile. '
              f'Vanno lette sul pannello di Sorare e messe in bonus_formazione_note.json:')
        for f in irrisolte:
            print(f"  {regole(f['leaderboard'])['tipo']}  {f['contender']}")
        return 1

    lega_di = lega_per_slug()
    carte = {}
    for f in formazioni:
        for c in f['carte']:
            if not c.get('punteggio') or c['carta'] in carte:
                continue
            if c['slug'] not in grezzi:
                continue
            carte[c['carta']] = {
                'carta': c['carta'], 'slug': c['slug'], 'nome': c['nome'], 'ruolo': c['ruolo'],
                'squadra': c.get('squadra'), 'bonus': c.get('bonus_carta') or 0.0,
                'grezzo': grezzi[c['slug']], 'in_season': bool(c.get('in_season')),
                'u23': bool(c.get('u23')), 'lega': lega_di.get(c['slug']),
            }
    senza_lega = sorted({c['nome'] for c in carte.values() if not c['lega']})
    if senza_lega:
        print(f'{len(senza_lega)} carte senza lega nota: restano fuori dai pool per lega '
              f'({", ".join(senza_lega[:5])})')

    base = sum(c['grezzo'] for c in carte.values())
    reale = sum(c['punteggio'] for f in formazioni for c in f['carte'] if c.get('punteggio'))

    # --- VOCE 1: il capitano, a parita' di carte gia' schierate -------------
    guadagno_cap = 0.0
    sbagliati = []
    for f in formazioni:
        r = regole(f['leaderboard'])
        valide = [c for c in f['carte'] if c.get('punteggio') and c['slug'] in grezzi]
        if not any(c['capitano'] for c in valide):
            continue
        b = bonus_f.get(f['contender'], 0.0)

        def valore(c):
            """Quanto porta la carta SENZA fascia: e' su questo che si sceglie."""
            extra = (c.get('bonus_carta') or 0.0) + b if r['xp'] else 0.0
            return grezzi[c['slug']] * (1.0 + extra)

        scelto = next(c for c in valide if c['capitano'])
        migliore = max(valide, key=valore)
        # la fascia moltiplica il GREZZO, non il valore con bonus (i bonus si sommano)
        delta = (grezzi[migliore['slug']] - grezzi[scelto['slug']]) * (r['cap'] - 1.0)
        guadagno_cap += delta
        if delta > 0.05:
            sbagliati.append((delta, r['tipo'], scelto['nome'], migliore['nome']))

    # --- VOCE 2: i bonus, cioe' quali carte finiscono dove si pagano ---------
    incassato = 0.0
    for f in formazioni:
        r = regole(f['leaderboard'])
        if not r['xp']:
            continue
        b = bonus_f.get(f['contender'], 0.0)
        for c in f['carte']:
            if c.get('punteggio') and c['slug'] in grezzi:
                incassato += grezzi[c['slug']] * ((c.get('bonus_carta') or 0.0) + b)

    libere = dict(carte)
    massimo = 0.0
    piazzate = []
    con_bonus = sorted([f for f in formazioni if regole(f['leaderboard'])['xp']],
                       key=lambda f: -bonus_f.get(f['contender'], 0.0))
    for f in con_bonus:
        r = regole(f['leaderboard'])
        b = bonus_f.get(f['contender'], 0.0)
        ruoli = [c['ruolo'] for c in f['carte'] if c.get('punteggio')]
        scelte, club = [], collections.Counter()
        for i, ruolo in enumerate(ruoli):
            restanti = len(ruoli) - i - 1
            servono = max(0, r['min_in_season'] - sum(1 for c in scelte if c['in_season']))
            candidate = [c for c in libere.values()
                         if c['ruolo'] == ruolo and ammessa(c, r) and club[c['squadra']] < 2]
            if servono > restanti:
                candidate = [c for c in candidate if c['in_season']]
            if not candidate:
                continue
            migliore = max(candidate, key=lambda c: c['grezzo'] * (c['bonus'] + b))
            scelte.append(migliore)
            club[migliore['squadra']] += 1
            del libere[migliore['carta']]
        massimo += sum(c['grezzo'] * (c['bonus'] + b) for c in scelte)
        piazzate.append((f, r, b, scelte))

    recuperabile = guadagno_cap + (massimo - incassato)
    print(f"\nformazioni {len(formazioni)}   carte distinte {len(carte)}   "
          f"grezzi ricavati {len(grezzi)}   bonus di formazione risolti {len(bonus_f)}")
    print(f"\nSOMMA DEI GREZZI (invariante)            {base:9.1f}")
    print(f"BONUS incassati                          {incassato:9.1f}   "
          f"massimo possibile {massimo:8.1f}   recuperabile {massimo - incassato:+8.1f}")
    print(f"CAPITANO, a parita' di carte schierate                        "
          f"                    recuperabile {guadagno_cap:+8.1f}")
    print(f"\nTOTALE REALE {reale:9.1f}   ->  ricollocando bene {reale + recuperabile:9.1f}   "
          f"({recuperabile:+.1f}, {100.0 * recuperabile / reale:+.1f}%)")

    if sbagliati:
        print('\nFASCE SBAGLIATE (le prime 8, a parita' + "'" + ' di carte)')
        for delta, tipo, scelto, migliore in sorted(sbagliati, reverse=True)[:8]:
            print(f"  {tipo[:22]:22s} {scelto[:20]:20s} -> {migliore[:20]:20s} {delta:+6.1f}")

    dentro = {c['carta'] for _f, _r, _b, cs in piazzate for c in cs}
    fuori = set()
    for f in formazioni:
        if not regole(f['leaderboard'])['xp']:
            fuori.update(c['carta'] for c in f['carte'] if c.get('punteggio'))
    guadagno_di = {}
    for _f, _r, b, cs in piazzate:
        for c in cs:
            guadagno_di[c['carta']] = c['grezzo'] * (c['bonus'] + b)
    print('\nCARTE CHE DOVEVANO STARE DOVE I BONUS SI PAGANO (erano in arena)')
    for carta in sorted(dentro & fuori, key=lambda k: -guadagno_di[k])[:10]:
        c = carte[carta]
        print(f"  {c['nome'][:22]:22s} {c['ruolo'][:3]:3s} grezzo {c['grezzo']:6.1f}  "
              f"bonus carta {c['bonus']*100:4.1f}%  ->  {guadagno_di[carta]:+5.1f} punti")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'base': base, 'reale': reale, 'capitano_recuperabile': guadagno_cap,
                       'bonus_incassati': incassato, 'bonus_massimo': massimo,
                       'carte': list(carte.values()),
                       'bonus_formazione': bonus_f}, fh, ensure_ascii=False, indent=1)
        print(f'\nscritto {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
