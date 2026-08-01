"""backtest_arene — il modello contro l'utente, a parita' di mazzo e di arene.

La domanda della sezione 48.E del riassunto: se le formazioni arena di quelle
giornate le avesse fatte il MODELLO invece dell'utente, cosa sarebbe successo?

Disegno (deciso con l'utente):

  * A PARITA' DI MAZZO. Dai dati sappiamo quali carte l'utente ha *schierato*,
    non quali possedeva. Il pool di una giornata e' quindi l'insieme delle
    carte che ha usato quella giornata. Non risponde a "avrebbe comprato
    meglio", risponde a "avrebbe scelto meglio fra le stesse carte".
  * A PARITA' DI ARENE. Il modello entra nelle stesse arene, stesso numero e
    stesso tipo: si isola la bravura di SELEZIONE, senza mescolarla con la
    decisione d'ingresso (che ha gia' un suo strumento, vedi 48.H).
  * ALLOCAZIONE LIBERA fra quelle arene: ogni carta si usa una volta sola
    nella giornata, ma il modello la puo' mettere dove vuole.
  * CAP L10 rispettato. Il cap non e' nei dati, ma l'L10 e' ricostruibile dal
    game log (verificato: le "cap 220" dell'utente stanno a 219.9 di mediana,
    le "cap 260" a 258.1). Il cap effettivo di ogni arena e' il massimo fra
    quello nominale e l'L10 ricostruito della formazione VERA dell'utente in
    quella stessa arena -- cosi' il rumore della ricostruzione non puo' mai
    rendere illegale una formazione che e' realmente esistita, e il confronto
    resta onesto.
  * CAPITANO da entrambe le parti (trappola 48.D.1: i punteggi di classifica
    Sorare hanno gia' dentro il x1.2; qui si lavora sempre sul punteggio
    GREZZO e il moltiplicatore si applica esplicitamente).
  * WALK-FORWARD: la previsione di ogni giocatore vede solo partite di data
    precedente a quella della giornata (vedi backtest_arene_previsioni).

Uso:
    python backtest_arene.py                 # tutte le giornate disponibili
    python backtest_arene.py --json out.json # salva anche il dettaglio
"""
import os
import sys
import json
import io
import math
import random
import argparse
import statistics
import collections
import itertools

import backtest_arene_cache as C
import backtest_arene_previsioni as P

MOLTIPLICATORE_CAPITANO = 1.2

# Cap nominale di L10 per tipo di arena. None = nessun cap.
CAP_NOMINALE = {
    'cap 220': 220.0,
    'cap 260': 260.0,
    'Beginner': 260.0,
    'arena division': 260.0,
    'Uncapped': None,
    'arena uncapped': None,
}

# Le tre composizioni di ruolo osservate nelle 593 formazioni reali:
# sempre 1 portiere, almeno un difensore/centrocampista/attaccante, uno slot libero.
COMPOSIZIONI = (
    {'Goalkeeper': 1, 'Defender': 2, 'Midfielder': 1, 'Forward': 1},
    {'Goalkeeper': 1, 'Defender': 1, 'Midfielder': 2, 'Forward': 1},
    {'Goalkeeper': 1, 'Defender': 1, 'Midfielder': 1, 'Forward': 2},
)


# --------------------------------------------------------------------------
# Dati
# --------------------------------------------------------------------------

def carica(percorso):
    with io.open(percorso, encoding='utf-8') as fh:
        return json.load(fh)


def fine_giornate(arene):
    """fixture -> istante di chiusura piu' precoce visto in quella giornata."""
    fine = {}
    for a in arene:
        prec = fine.get(a['fixture'])
        fine[a['fixture']] = a['fine'] if prec is None else min(prec, a['fine'])
    return {k: P._dt(v) for k, v in fine.items()}


class Carta(object):
    __slots__ = ('carta', 'slug', 'nome', 'ruolo', 'atteso', 'l10', 'reale')

    def __init__(self, carta, slug, nome, ruolo, atteso, l10, reale):
        self.carta = carta
        self.slug = slug
        self.nome = nome
        self.ruolo = ruolo
        self.atteso = atteso
        self.l10 = l10
        self.reale = reale


def punteggio_grezzo(giocatore):
    """Il punteggio della carta SENZA il moltiplicatore del capitano."""
    p = giocatore.get('punteggio')
    if p is None:
        return None
    return p / MOLTIPLICATORE_CAPITANO if giocatore.get('capitano') else p


def totale_formazione(carte, capitano):
    """Totale di classifica: somma dei grezzi + il bonus del capitano."""
    base = sum(c.reale for c in carte)
    return base + (MOLTIPLICATORE_CAPITANO - 1.0) * capitano.reale


def totale_atteso(carte, capitano):
    base = sum(c.atteso for c in carte)
    return base + (MOLTIPLICATORE_CAPITANO - 1.0) * capitano.atteso


# --------------------------------------------------------------------------
# Costruzione delle formazioni del modello
# --------------------------------------------------------------------------

def _migliore_per_arena(pool, cap, larghezza=7):
    """La formazione col piu' alto totale ATTESO fra quelle legali nel pool.

    Ricerca esatta ristretta ai `larghezza` giocatori piu' promettenti per
    ruolo: oltre quella soglia nessuna combinazione puo' vincere, visto che
    si somma e i giocatori sono ordinati."""
    per_ruolo = collections.defaultdict(list)
    for c in pool:
        per_ruolo[c.ruolo].append(c)
    for r in per_ruolo:
        per_ruolo[r].sort(key=lambda c: c.atteso, reverse=True)
        del per_ruolo[r][larghezza:]

    migliore = None
    migliore_valore = None
    for comp in COMPOSIZIONI:
        if any(len(per_ruolo.get(r, ())) < n for r, n in comp.items()):
            continue
        gruppi = [list(itertools.combinations(per_ruolo[r], n)) for r, n in comp.items()]
        for scelta in itertools.product(*gruppi):
            carte = [c for gruppo in scelta for c in gruppo]
            if cap is not None and sum(c.l10 for c in carte) > cap:
                continue
            capitano = max(carte, key=lambda c: c.atteso)
            valore = totale_atteso(carte, capitano)
            if migliore_valore is None or valore > migliore_valore:
                migliore_valore = valore
                migliore = (carte, capitano)
    return migliore


def alloca(pool, arene, iterazioni_scambio=4000, seme=0):
    """Assegna le carte del pool alle arene della giornata.

    Prima passata greedy sulle arene piu' vincolate (cap piu' basso), poi
    scambi locali fra formazioni finche' il totale atteso complessivo sale.
    Non e' un ottimo garantito -- e' un massimo locale robusto, e la domanda
    ("sceglie meglio dell'utente?") non richiede l'ottimo esatto."""
    rimaste = list(pool)
    ordine = sorted(range(len(arene)),
                    key=lambda i: (arene[i]['cap'] is None, arene[i]['cap'] or 0.0))
    formazioni = [None] * len(arene)
    for i in ordine:
        scelta = _migliore_per_arena(rimaste, arene[i]['cap'])
        if scelta is None:
            continue
        carte, _cap = scelta
        formazioni[i] = list(carte)
        usate = set(id(c) for c in carte)
        rimaste = [c for c in rimaste if id(c) not in usate]

    indici_pieni = [i for i, f in enumerate(formazioni) if f]

    def legale(carte, cap):
        ruoli = collections.Counter(c.ruolo for c in carte)
        if ruoli['Goalkeeper'] != 1 or len(carte) != 5:
            return False
        if any(ruoli[r] < 1 for r in ('Defender', 'Midfielder', 'Forward')):
            return False
        return cap is None or sum(c.l10 for c in carte) <= cap

    rng = random.Random(seme)
    if len(indici_pieni) >= 2:
        for _ in range(iterazioni_scambio):
            a, b = rng.sample(indici_pieni, 2)
            ca = rng.randrange(5)
            cb = rng.randrange(5)
            fa, fb = formazioni[a], formazioni[b]
            if fa[ca].ruolo != fb[cb].ruolo:
                continue
            prima = _valore(fa) + _valore(fb)
            fa[ca], fb[cb] = fb[cb], fa[ca]
            if (legale(fa, arene[a]['cap']) and legale(fb, arene[b]['cap'])
                    and _valore(fa) + _valore(fb) > prima + 1e-9):
                continue  # scambio tenuto
            fa[ca], fb[cb] = fb[cb], fa[ca]  # annullato

    return formazioni


def formazione_casuale(pool, cap, rng, tentativi=200):
    """Una formazione legale pescata a caso dal pool.

    Serve per la correlazione previsto/realizzato da confrontare con la
    tabella della sezione 48.C. Quella misurata sulle formazioni SCELTE (dal
    modello o dall'utente) e' sempre piu' bassa del vero per una ragione
    statistica, non di modello: chi sceglie prende solo i punteggi previsti
    alti, la gamma dei previsti si restringe e la correlazione si schiaccia.
    Su formazioni non selezionate quel restringimento non c'e'."""
    per_ruolo = collections.defaultdict(list)
    for c in pool:
        per_ruolo[c.ruolo].append(c)
    for _ in range(tentativi):
        comp = rng.choice(COMPOSIZIONI)
        if any(len(per_ruolo.get(r, ())) < n for r, n in comp.items()):
            continue
        carte = []
        for ruolo, quanti in comp.items():
            carte.extend(rng.sample(per_ruolo[ruolo], quanti))
        if cap is not None and sum(c.l10 for c in carte) > cap:
            continue
        return carte
    return None


def _valore(carte):
    capitano = max(carte, key=lambda c: c.atteso)
    return totale_atteso(carte, capitano)


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def esegui(verbose=True):
    cache = C.CacheLocale()
    formazioni_utente = carica('dati_globali/arene_formazioni.json')['formazioni']
    arene_storico = carica('dati_globali/arene_storico.json')['arene']
    fine = fine_giornate(arene_storico)
    per_slug_arena = {a['slug']: a for a in arene_storico}

    per_giornata = collections.defaultdict(list)
    for chiave, v in formazioni_utente.items():
        per_giornata[v['fixture']].append((chiave, v))

    previsioni = {}

    def previsione(slug, ruolo, fd):
        ch = (slug, ruolo, fd)
        if ch not in previsioni:
            previsioni[ch] = P.score_atteso(cache, slug, ruolo, fd)
        return previsioni[ch]

    confronti = []
    saltate = collections.Counter()
    giornate_usate = 0

    for fixture in sorted(per_giornata):
        fd = fine.get(fixture)
        if fd is None:
            saltate['giornata senza data'] += len(per_giornata[fixture])
            continue

        # Pool della giornata: ogni carta una volta sola, prevista e realizzata.
        pool = {}
        complete = []
        for chiave, v in per_giornata[fixture]:
            carte = []
            ok = True
            for g in v['giocatori']:
                reale = punteggio_grezzo(g)
                r = previsione(g['slug'], g['ruolo'], fd)
                if reale is None or r is None or r['l10'] is None:
                    ok = False
                    break
                c = pool.get(g['carta'])
                if c is None:
                    c = Carta(g['carta'], g['slug'], g['nome'], g['ruolo'],
                              r['atteso'], r['l10'], reale)
                    pool[g['carta']] = c
                carte.append(c)
            if ok:
                complete.append((chiave, v, carte,
                                 next(c for c, g in zip(carte, v['giocatori']) if g['capitano'])
                                 if any(g['capitano'] for g in v['giocatori']) else None))
            else:
                saltate['giocatore senza storico utilizzabile'] += 1

        complete = [t for t in complete if t[3] is not None]
        if not complete:
            continue

        # Le carte di formazioni incomplete non entrano nel pool: il modello
        # gioca solo con quelle di cui sa tutto, e sulle stesse arene.
        usate = set()
        for _k, _v, carte, _cap in complete:
            usate.update(c.carta for c in carte)
        pool_giornata = [c for k, c in pool.items() if k in usate]

        arene_modello = []
        for chiave, v, carte, capitano in complete:
            a = per_slug_arena.get(v['slug'], {})
            nominale = CAP_NOMINALE.get(v['tipo'], 260.0)
            l10_utente = sum(c.l10 for c in carte)
            cap = None if nominale is None else max(nominale, l10_utente)
            arene_modello.append({'chiave': chiave, 'tipo': v['tipo'], 'cap': cap,
                                  'arena': a, 'utente': carte, 'capitano_utente': capitano})

        scelte = alloca(pool_giornata, arene_modello)
        giornate_usate += 1
        rng_casuale = random.Random(hash(fixture) & 0xffff)

        for arena, carte_modello in zip(arene_modello, scelte):
            if not carte_modello:
                continue
            cap_m = max(carte_modello, key=lambda c: c.atteso)
            casuale = formazione_casuale(pool_giornata, arena['cap'], rng_casuale)
            confronti.append({
                'casuale_reale': (totale_formazione(casuale, max(casuale, key=lambda c: c.atteso))
                                  if casuale else None),
                'casuale_atteso': (totale_atteso(casuale, max(casuale, key=lambda c: c.atteso))
                                   if casuale else None),
                'fixture': fixture,
                'tipo': arena['tipo'],
                'arena': arena['arena'].get('slug'),
                'terzo': arena['arena'].get('terzo'),
                'premio': arena['arena'].get('premio_essenze'),
                'utente_reale': totale_formazione(arena['utente'], arena['capitano_utente']),
                'utente_atteso': totale_atteso(arena['utente'], arena['capitano_utente']),
                'modello_reale': totale_formazione(carte_modello, cap_m),
                'modello_atteso': totale_atteso(carte_modello, cap_m),
                'carte_modello': [c.nome for c in carte_modello],
                'carte_utente': [c.nome for c in arena['utente']],
                'uguali': sorted(c.carta for c in carte_modello) == sorted(c.carta for c in arena['utente']),
            })

    return confronti, saltate, giornate_usate


def correlazione(xs, ys):
    n = len(xs)
    if n < 3:
        return float('nan')
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else float('nan')


def intervallo_media(valori, seme=0, giri=2000):
    """IC 95% della media per bootstrap (le giornate non sono indipendenti,
    quindi va letto come indicativo)."""
    rng = random.Random(seme)
    n = len(valori)
    medie = []
    for _ in range(giri):
        medie.append(sum(valori[rng.randrange(n)] for _ in range(n)) / n)
    medie.sort()
    return medie[int(0.025 * giri)], medie[int(0.975 * giri)]


def rapporto(confronti, saltate, giornate):
    print(f"\n{'='*74}")
    print("BACKTEST ARENE — il modello contro l'utente, a parita' di mazzo e di arene")
    print('='*74)
    print(f"\nArene confrontate: {len(confronti)} su {len(confronti)+sum(saltate.values())} "
          f"({giornate} giornate)")
    for causa, n in saltate.most_common():
        print(f"  escluse: {n:4d} — {causa}")

    if not confronti:
        return

    du = [c['utente_reale'] for c in confronti]
    dm = [c['modello_reale'] for c in confronti]
    diff = [m - u for m, u in zip(dm, du)]

    print(f"\n--- PUNTEGGIO REALIZZATO (capitano incluso da entrambe le parti) ---")
    print(f"  utente : media {statistics.mean(du):6.2f}   mediana {statistics.median(du):6.2f}")
    print(f"  modello: media {statistics.mean(dm):6.2f}   mediana {statistics.median(dm):6.2f}")
    lo, hi = intervallo_media(diff)
    print(f"  DIFFERENZA media {statistics.mean(diff):+6.2f} punti per arena "
          f"(IC95% bootstrap {lo:+.2f} .. {hi:+.2f})")
    vinte = sum(1 for d in diff if d > 0)
    print(f"  arene in cui il modello fa meglio: {vinte}/{len(diff)} ({vinte/len(diff):.1%})")
    identiche = sum(1 for c in confronti if c['uguali'])
    print(f"  formazioni identiche a quelle dell'utente: {identiche} ({identiche/len(confronti):.1%})")

    print(f"\n--- CORRELAZIONE previsto/realizzato sul totale di formazione ---")
    print("  (e' il numero da incrociare con la tabella della sezione 48.C)")
    cm = correlazione([c['modello_atteso'] for c in confronti], dm)
    cu = correlazione([c['utente_atteso'] for c in confronti], du)
    print(f"  formazioni del MODELLO: {cm:+.3f}   (n={len(confronti)})")
    print(f"  formazioni dell'UTENTE: {cu:+.3f}   [stesso modello, scelte sue]")
    casuali = [c for c in confronti if c.get('casuale_reale') is not None]
    if casuali:
        cc = correlazione([c['casuale_atteso'] for c in casuali],
                          [c['casuale_reale'] for c in casuali])
        print(f"  formazioni CASUALI    : {cc:+.3f}   (n={len(casuali)}) <-- questo va in 48.C")
        print("  Le prime due sono schiacciate dalla selezione (si scelgono solo i previsti")
        print("  alti, la gamma si restringe): non sono confrontabili con quella tabella.")
        cas = [c['casuale_reale'] for c in casuali]
        print(f"  [riferimento] punteggio medio di una formazione a caso dal pool: "
              f"{statistics.mean(cas):.2f}")

    print(f"\n--- SOPRA LA SOGLIA DEL TERZO (premio effettivamente preso) ---")
    con_terzo = [c for c in confronti if c.get('terzo') is not None]
    if con_terzo:
        pu = sum(1 for c in con_terzo if c['utente_reale'] >= c['terzo'])
        pm = sum(1 for c in con_terzo if c['modello_reale'] >= c['terzo'])
        print(f"  su {len(con_terzo)} arene con soglia nota:")
        print(f"    utente  a premio: {pu:4d} ({pu/len(con_terzo):.1%})")
        print(f"    modello a premio: {pm:4d} ({pm/len(con_terzo):.1%})")
        print("  NB: la soglia e' quella VERA di quell'arena, cioe' il punteggio del terzo")
        print("      quando c'era dentro la formazione dell'utente. Se schiera un'altra")
        print("      formazione la soglia cambia un po': va letto come approssimazione.")

    print(f"\n--- PER TIPO DI ARENA ---")
    per_tipo = collections.defaultdict(list)
    for c in confronti:
        per_tipo[c['tipo']].append(c['modello_reale'] - c['utente_reale'])
    for tipo, d in sorted(per_tipo.items(), key=lambda kv: -len(kv[1])):
        print(f"  {tipo:16s} n={len(d):4d}  differenza media {statistics.mean(d):+6.2f}")

    print(f"\n--- PER GIORNATA (aggregato, meno rumoroso) ---")
    per_g = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for c in confronti:
        v = per_g[c['fixture']]
        v[0] += c['modello_reale']
        v[1] += c['utente_reale']
        v[2] += 1
    diffs = [(m - u) / n for m, u, n in per_g.values()]
    meglio = sum(1 for d in diffs if d > 0)
    print(f"  giornate in cui il modello fa meglio: {meglio}/{len(diffs)} ({meglio/len(diffs):.1%})")
    print(f"  differenza media per giornata: {statistics.mean(diffs):+.2f} punti per arena")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', help='salva il dettaglio arena per arena')
    args = ap.parse_args()
    confronti, saltate, giornate = esegui()
    rapporto(confronti, saltate, giornate)
    if args.json:
        with io.open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(confronti, fh, ensure_ascii=False, indent=1)
        print(f"\nDettaglio salvato in {args.json}")


if __name__ == '__main__':
    main()
