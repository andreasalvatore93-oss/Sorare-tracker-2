"""punteggi_grezzi — il punteggio VERO del giocatore, ripulito da tutti i bonus.

PERCHE' SERVE. Il modello prevede il punteggio grezzo del giocatore. Sorare
pubblica il punteggio della CARTA, che e' un'altra cosa: ci sono dentro il
bonus della carta, i bonus di formazione e il capitano. Confrontare i due
numeri cosi' come sono gonfia l'errore proprio dove le carte sono migliori --
ed e' un errore invisibile, perche' il risultato resta plausibile.

LA REGOLA, verificata al centesimo su 16 casi reali: i bonus SI SOMMANO.

    punteggio carta = grezzo x (1 + bonus_carta + bonus_formazione + capitano)

  - bonus_carta: somma dei basis point del powerBreakdown (season, collection,
    xp, scarcity, special edition, active clubs, nationality, positions).
    Vale SOLO in In Season, All Star e Under 23. In arena e' ZERO.
  - bonus_formazione: +2% "Multi-club" (al massimo 2 giocatori dello stesso
    club) e +4% "Cap" (somma L10 sotto 260, o 370 nelle formazioni da 7),
    cumulabili. Anche questi solo dove valgono i bonus carta.
  - capitano: +50% in In Season/All Star/Under 23, +20% in arena.

Controprova che ha smontato l'ipotesi moltiplicativa: Kim Bong-Soo, capitano
in una In Season K-League senza bonus cap. In cascata darebbe
60.20 x 1.14 x 1.5 = 101.14; sommando, 60.20 x (1+0.12+0.02+0.50) = 98.73,
che e' esattamente il punteggio pubblicato.

COME SI RICAVA IL BONUS DI FORMAZIONE SENZA INDOVINARLO. Il pannello di Sorare
non e' nei dati e la somma L10 non e' ricostruibile con precisione sufficiente:
la soglia e' netta, e un L10 sbagliato di due punti ribalta il +4%. Quindi non
si stima, si RICAVA a catena:

  1. ogni carta schierata in ARENA da un grezzo certo -- li' non c'e' nessun
     bonus, il punteggio della carta e' il punteggio del giocatore;
  2. una formazione che contiene un giocatore a grezzo noto rivela il proprio
     bonus (l'unico dei quattro valori possibili che torna);
  3. noto il bonus, si ricavano i grezzi delle altre carte di quella
     formazione, che a loro volta aprono altre formazioni. Si itera.

Sulla giornata 31 lug-4 ago questo risolve 15 formazioni su 18 da solo. Le
rimanenti si chiedono all'utente una volta e restano in
`dati_globali/bonus_formazione_note.json`, insieme alle formazioni annullate
in corsa (che vanno escluse: non sono un esito reale).
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
NOTE = os.path.join(ROOT, 'dati_globali', 'bonus_formazione_note.json')

BONUS_AMMESSI = (0.0, 0.02, 0.04, 0.06)
TOLLERANZA = 0.005


def carica_note():
    if not os.path.exists(NOTE):
        return {}, {}
    with open(NOTE, encoding='utf-8') as f:
        d = json.load(f) or {}
    return d.get('bonus') or {}, d.get('formazioni_annullate') or {}


def _capitano(regole_f):
    return regole_f['cap'] - 1.0


def risolvi(formazioni, regole):
    """Ritorna (grezzi_per_slug, bonus_per_contender, irrisolte).

    `regole(leaderboard)` deve dare un dizionario con 'xp' (bool) e 'cap'
    (moltiplicatore capitano, 1.5 o 1.2)."""
    note_bonus, _ = carica_note()

    grezzi = {}
    for f in formazioni:
        r = regole(f['leaderboard'])
        if r['xp']:
            continue
        for c in f['carte']:
            if c.get('punteggio'):
                grezzi[c['slug']] = c['punteggio'] / (1.0 + (_capitano(r) if c['capitano'] else 0.0))

    con_bonus = [f for f in formazioni if regole(f['leaderboard'])['xp']]
    bonus = {f['contender']: note_bonus[f['contender']]
             for f in con_bonus if f['contender'] in note_bonus}
    for f in con_bonus:
        if f['contender'] in bonus:
            _propaga(f, bonus[f['contender']], regole(f['leaderboard']), grezzi)

    while True:
        nuovi = 0
        for f in con_bonus:
            if f['contender'] in bonus:
                continue
            r = regole(f['leaderboard'])
            trovato = None
            for c in f['carte']:
                if c['slug'] not in grezzi or not c.get('punteggio'):
                    continue
                atteso = c['punteggio'] / grezzi[c['slug']] - 1.0 \
                    - (c.get('bonus_carta') or 0.0) - (_capitano(r) if c['capitano'] else 0.0)
                vicino = min(BONUS_AMMESSI, key=lambda t: abs(t - atteso))
                if abs(atteso - vicino) < TOLLERANZA:
                    trovato = vicino
                    break
            if trovato is None:
                continue
            bonus[f['contender']] = trovato
            _propaga(f, trovato, r, grezzi)
            nuovi += 1
        if not nuovi:
            break

    irrisolte = [f for f in con_bonus if f['contender'] not in bonus]
    return grezzi, bonus, irrisolte


def _propaga(f, b, r, grezzi):
    for c in f['carte']:
        if c.get('punteggio') and c['slug'] not in grezzi:
            grezzi[c['slug']] = c['punteggio'] / (
                1.0 + b + (c.get('bonus_carta') or 0.0) + (_capitano(r) if c['capitano'] else 0.0))


def punteggio_carta(grezzo, bonus_carta, bonus_formazione, capitano, r):
    """Il percorso inverso: da grezzo a punteggio pubblicato da Sorare."""
    tot = 0.0
    if r['xp']:
        tot += (bonus_carta or 0.0) + (bonus_formazione or 0.0)
    if capitano:
        tot += _capitano(r)
    return grezzo * (1.0 + tot)
