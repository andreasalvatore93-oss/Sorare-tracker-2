"""backtest_arene_economia — la seconda direttrice: quanto si guadagna, in essenze.

Il confronto in punti (backtest_arene.py) dice se il modello sceglie meglio.
Non dice la cosa che conta davvero, che l'utente ha formulato cosi':

    il modello sarebbe entrato in quell'arena, con quelle carte?
    se si', quanto ho guadagnato; se no, quanto ho risparmiato?

Qui si risponde in essenze, simulando il piazzamento vero. Di ogni arena
l'archivio ha TUTTI E DIECI i punteggi: si toglie quello dell'utente, si
mette quello della formazione del modello, si riordina e si legge il
piazzamento. Non e' una soglia approssimata, e' la classifica.

Verifica del meccanismo: ricostruendo cosi' il piazzamento DELL'UTENTE si
ritrova il suo `mio_rank` in 670 arene su 673 (le 3 differenze sono
ex aequo).

LIMITE NOTO (trappola 48.D.2): fino a 3 formazioni dell'utente possono
trovarsi nello stesso pool da 10, cioe' l'utente gioca contro se stesso.
Se il modello cambia entrambe, sostituirle una per volta e' un'approssima-
zione — gli altri 9 punteggi restano quelli veri.
"""

# Costo d'ingresso per tipo (essenze). Presi dall'archivio dove c'e'
# (`costo`), completati con la tabella della sezione 48.C dove manca.
COSTO_INGRESSO = {
    'Beginner': 100,
    'cap 220': 200,
    'cap 260': 300,
    'arena division': 300,   # arena dedicata: stesso ingresso della cap 260
    'Uncapped': 300,
    'arena uncapped': 300,
}

# Punteggio atteso oltre il quale l'ingresso si ripaga (sezione 48.C, misurato
# sulle 673 arene reali) e quanto vale un punto sopra la soglia (48.H).
PAREGGIO = {
    'Beginner': 281.9,
    'cap 220': 265.0,
    'cap 260': 282.9,
    'arena division': 282.9,
    'Uncapped': 305.5,
    'arena uncapped': 305.5,
}
GUADAGNO_PER_PUNTO = {
    'Beginner': 7.0,
    'cap 220': 20.0,
    'cap 260': 29.0,
    'arena division': 29.0,
    'Uncapped': 22.0,
    'arena uncapped': 22.0,
}
# Si entra se il guadagno atteso vale almeno il 10% di cio' che si rischia
# (48.H: la soglia va ricavata dalla curva, non scelta a occhio).
QUOTA_MINIMA = 0.10

# Solo i primi tre prendono premio: in tutte le 673 arene dell'archivio
# `rank_premiato` non supera mai 3.
RANK_MASSIMO_PREMIATO = 3


def tabella_premi(arene):
    """(tipo, rank) -> essenze, ricavata dai premi realmente incassati.

    Dove lo stesso (tipo, rank) mostra importi diversi (arene speciali, o
    montepremi cambiato nel tempo) si tiene il valore piu' FREQUENTE: e' il
    caso normale, e sovrastimare i premi gonfierebbe il modello."""
    conteggi = {}
    for a in arene:
        rank = a.get('rank_premiato')
        if not rank:
            continue
        chiave = (a['tipo'], rank)
        conteggi.setdefault(chiave, {})
        premio = a.get('premio_essenze') or 0
        conteggi[chiave][premio] = conteggi[chiave].get(premio, 0) + 1
    return {k: max(v, key=v.get) for k, v in conteggi.items()}


def costo(arena):
    c = arena.get('costo')
    return c if c is not None else COSTO_INGRESSO.get(arena.get('tipo'), 300)


def piazzamento(arena, punteggio_utente, punteggio_nuovo):
    """Il piazzamento che avrebbe avuto `punteggio_nuovo` al posto dell'utente."""
    altri = list(arena.get('punteggi') or [])
    if punteggio_utente in altri:
        altri.remove(punteggio_utente)
    # In caso di parita' si sta DIETRO: e' come si e' comportata Sorare
    # nell'unico ex aequo dell'archivio (l'utente e' arrivato 2o, non 1o), ed
    # e' comunque la scelta che non regala nulla al modello.
    return sum(1 for p in altri if p >= punteggio_nuovo) + 1


def premio(arena, rank, premi):
    if rank > RANK_MASSIMO_PREMIATO:
        return 0
    # se e' esattamente il piazzamento che l'utente ha davvero fatto, si usa
    # l'importo VERO di quell'arena invece della tabella
    if arena.get('rank_premiato') == rank:
        return arena.get('premio_essenze') or 0
    return premi.get((arena.get('tipo'), rank), 0)


def entra(tipo, punteggio_atteso):
    """La regola d'ingresso della sezione 48.H, applicata al punteggio atteso."""
    soglia = PAREGGIO.get(tipo)
    if soglia is None:
        return True, 0.0
    margine = punteggio_atteso - soglia
    guadagno = margine * GUADAGNO_PER_PUNTO.get(tipo, 29.0)
    ingresso = COSTO_INGRESSO.get(tipo, 300)
    return guadagno >= QUOTA_MINIMA * ingresso, guadagno


def bilancio(confronti, arene_storico):
    """Tre bilanci a confronto, sulle stesse arene:

      utente               — quello che e' realmente successo
      modello, stesse arene— entra ovunque e' entrato lui, ma con le sue carte
      modello, con verdetto— entra solo dove il verdetto 48.H dice di entrare
    """
    premi = tabella_premi(arene_storico)
    per_slug = {a['slug']: a for a in arene_storico}

    ris = {
        'utente': {'ingressi': 0, 'costi': 0, 'premi': 0, 'a_premio': 0},
        'modello_stesse': {'ingressi': 0, 'costi': 0, 'premi': 0, 'a_premio': 0},
        'modello_verdetto': {'ingressi': 0, 'costi': 0, 'premi': 0, 'a_premio': 0},
        'controllo_utente_ricostruito': 0,
        'arene': 0,
    }
    dettaglio = []

    for c in confronti:
        arena = per_slug.get(c.get('arena'))
        if arena is None or not arena.get('punteggi'):
            continue
        ris['arene'] += 1
        tipo = c['tipo']
        ingresso = costo(arena)

        # --- utente: il fatto, come registrato
        ris['utente']['ingressi'] += 1
        ris['utente']['costi'] += ingresso
        vinto_utente = arena.get('premio_essenze') or 0
        ris['utente']['premi'] += vinto_utente
        if vinto_utente:
            ris['utente']['a_premio'] += 1
        # controllo: lo stesso premio ricalcolato dalla classifica
        rank_ric = piazzamento(arena, arena.get('mio_score'), arena.get('mio_score'))
        ris['controllo_utente_ricostruito'] += premio(arena, rank_ric, premi)

        # --- modello sulle stesse arene
        rank_m = piazzamento(arena, arena.get('mio_score'), c['modello_reale'])
        vinto_m = premio(arena, rank_m, premi)
        ris['modello_stesse']['ingressi'] += 1
        ris['modello_stesse']['costi'] += ingresso
        ris['modello_stesse']['premi'] += vinto_m
        if vinto_m:
            ris['modello_stesse']['a_premio'] += 1

        # --- modello che decide anche se entrare
        sceglie, guadagno_atteso = entra(tipo, c['modello_atteso'])
        if sceglie:
            ris['modello_verdetto']['ingressi'] += 1
            ris['modello_verdetto']['costi'] += ingresso
            ris['modello_verdetto']['premi'] += vinto_m
            if vinto_m:
                ris['modello_verdetto']['a_premio'] += 1

        dettaglio.append({
            'arena': arena['slug'], 'tipo': tipo, 'ingresso': ingresso,
            'utente_score': arena.get('mio_score'), 'utente_rank': arena.get('mio_rank'),
            'utente_premio': vinto_utente,
            'modello_score': c['modello_reale'], 'modello_rank': rank_m,
            'modello_premio': vinto_m,
            'modello_atteso': c['modello_atteso'],
            'entra': sceglie, 'guadagno_atteso': guadagno_atteso,
        })

    return ris, dettaglio


def stampa(ris, dettaglio):
    if not ris['arene']:
        return
    print(f"\n{'='*74}")
    print("BILANCIO IN ESSENZE — sulle stesse arene, simulando la classifica vera")
    print('='*74)
    v = ris['utente']
    print(f"\nControllo del meccanismo: premi dell'utente ricalcolati dalla classifica "
          f"{ris['controllo_utente_ricostruito']} contro {v['premi']} registrati "
          f"({'combaciano' if ris['controllo_utente_ricostruito'] == v['premi'] else 'NON combaciano'})")

    righe = (('utente (il fatto)', ris['utente']),
             ('modello, stesse arene', ris['modello_stesse']),
             ('modello, entra col verdetto 48.H', ris['modello_verdetto']))
    print(f"\n{'':34s} {'ingressi':>9s} {'costo':>8s} {'premi':>8s} {'netto':>9s} {'ROI':>8s}")
    for nome, d in righe:
        netto = d['premi'] - d['costi']
        roi = netto / d['costi'] if d['costi'] else 0.0
        print(f"  {nome:32s} {d['ingressi']:9d} {d['costi']:8d} {d['premi']:8d} "
              f"{netto:+9d} {roi:+7.1%}")

    for nome, chiave in (('stesse arene', 'modello_stesse'),
                         ('col verdetto', 'modello_verdetto')):
        d = ris[chiave]
        delta = (d['premi'] - d['costi']) - (v['premi'] - v['costi'])
        print(f"\n  modello {nome}: {delta:+d} essenze rispetto all'utente")
        if chiave == 'modello_verdetto':
            saltate = ris['utente']['ingressi'] - d['ingressi']
            risparmio = ris['utente']['costi'] - d['costi']
            persi = ris['modello_stesse']['premi'] - d['premi']
            print(f"    non entra in {saltate} arene su {ris['utente']['ingressi']}: "
                  f"{risparmio} essenze di ingresso risparmiate")
            print(f"    di quelle rinunciate avrebbe comunque vinto {persi} essenze, "
                  f"quindi il risparmio netto e' {risparmio - persi:+d}")

    a_premio = ris['modello_stesse']['a_premio']
    print(f"\n  arene a premio: utente {v['a_premio']}, modello {a_premio} "
          f"(su {ris['arene']})")

    # Per tipo, perche' la media nasconde un caso grosso: l'`arena division`
    # paga 500/250/150 come la Beginner (contro 1300/800/500 della cap 260) ma
    # costa 300 come la cap 260. A parita' di formazione la Beginner la domina.
    print(f"\n--- BILANCIO PER TIPO (utente contro modello, stesse arene) ---")
    print(f"  {'tipo':16s} {'n':>4s} {'ingresso':>9s} {'utente':>9s} {'modello':>9s} "
          f"{'ROI ut.':>8s} {'ROI mod.':>9s}")
    per_tipo = {}
    for d in dettaglio:
        t = per_tipo.setdefault(d['tipo'], {'n': 0, 'costi': 0, 'ut': 0, 'mod': 0})
        t['n'] += 1
        t['costi'] += d['ingresso']
        t['ut'] += d['utente_premio']
        t['mod'] += d['modello_premio']
    for tipo, t in sorted(per_tipo.items(), key=lambda kv: -kv[1]['n']):
        roi_u = (t['ut'] - t['costi']) / t['costi'] if t['costi'] else 0.0
        roi_m = (t['mod'] - t['costi']) / t['costi'] if t['costi'] else 0.0
        print(f"  {tipo:16s} {t['n']:4d} {t['costi']:9d} {t['ut'] - t['costi']:+9d} "
              f"{t['mod'] - t['costi']:+9d} {roi_u:+7.1%} {roi_m:+8.1%}")
    print("  NB: il costo dell'`arena division` non e' registrato in archivio, qui e'")
    print("      assunto a 300 su indicazione dell'utente. analizza_arene.py invece la")
    print("      tiene FUORI dal bilancio (costo ignoto), quindi i due totali non")
    print("      sono confrontabili senza tenerne conto.")


def quadranti_verdetto(confronti, arene_storico):
    """Il verdetto d'ingresso applicato alle formazioni VERE dell'utente.

    Qui il modello non ridistribuisce niente: guarda la formazione che
    l'utente ha davvero schierato, ne calcola il punteggio atteso e dice
    soltanto "entra" o "non entrare". Poi si confronta con com'e' andata.
    Sono le quattro caselle che l'utente ha chiesto:

      dice ENTRA  + ha vinto   -> consigliato bene, essenze guadagnate
      dice ENTRA  + ha perso   -> consigliato male, essenze buttate
      dice NON    + ha vinto   -> quanto avrei PERSO dandogli retta
      dice NON    + ha perso   -> quanto avrei RISPARMIATO dandogli retta
    """
    per_slug = {a['slug']: a for a in arene_storico}
    caselle = {}
    for c in confronti:
        arena = per_slug.get(c.get('arena'))
        if arena is None:
            continue
        sceglie, _g = entra(c['tipo'], c['utente_atteso'])
        vinto = arena.get('premio_essenze') or 0
        ingresso = costo(arena)
        chiave = (sceglie, vinto > 0)
        d = caselle.setdefault(chiave, {'n': 0, 'costi': 0, 'premi': 0})
        d['n'] += 1
        d['costi'] += ingresso
        d['premi'] += vinto
    return caselle


def stampa_quadranti(caselle):
    if not caselle:
        return
    print(f"\n{'='*74}")
    print("IL VERDETTO D'INGRESSO SULLE FORMAZIONI VERE DELL'UTENTE")
    print('='*74)
    print("\nIl modello non cambia le carte: guarda la formazione che hai schierato")
    print("davvero e dice solo se valeva la pena pagare l'ingresso.\n")
    etichette = {
        (True, True): "dice ENTRA  e hai vinto      -> consigliato bene",
        (True, False): "dice ENTRA  e hai perso      -> consigliato male",
        (False, True): "dice NON entrare, hai vinto  -> quanto ti avrebbe fatto PERDERE",
        (False, False): "dice NON entrare, hai perso  -> quanto ti avrebbe RISPARMIATO",
    }
    print(f"  {'':60s} {'n':>4s} {'costo':>7s} {'premi':>7s} {'netto':>8s}")
    for chiave in ((True, True), (True, False), (False, True), (False, False)):
        d = caselle.get(chiave)
        if not d:
            continue
        netto = d['premi'] - d['costi']
        print(f"  {etichette[chiave]:60s} {d['n']:4d} {d['costi']:7d} {d['premi']:7d} {netto:+8d}")

    entrate = [caselle.get((True, True), {}), caselle.get((True, False), {})]
    saltate = [caselle.get((False, True), {}), caselle.get((False, False), {})]
    n_e = sum(d.get('n', 0) for d in entrate)
    n_s = sum(d.get('n', 0) for d in saltate)
    netto_e = sum(d.get('premi', 0) - d.get('costi', 0) for d in entrate)
    netto_s = sum(d.get('premi', 0) - d.get('costi', 0) for d in saltate)
    print(f"\n  Seguendo il verdetto avresti giocato {n_e} arene su {n_e + n_s} "
          f"e chiuso a {netto_e:+d} essenze.")
    print(f"  Le {n_s} che ti avrebbe fatto saltare valevano {netto_s:+d}: "
          f"{'evitarle era giusto' if netto_s < 0 else 'evitarle sarebbe costato'}.")
    if netto_e + netto_s:
        print(f"  Il fatto (tutte e {n_e + n_s}): {netto_e + netto_s:+d} essenze.")


def mostra_ridistribuzioni(confronti, dettaglio, quante=8):
    """Le scelte concrete: stesse carte, distribuite diversamente.

    E' la domanda dell'utente ("quali scelte avrebbe fatto il modello, potendo
    usare tutte le carte che ha usato lui, ma ridistribuendole?"): un numero
    aggregato non la soddisfa, servono i casi."""
    per_arena = {d['arena']: d for d in dettaglio}
    casi = [c for c in confronti if c.get('arena') in per_arena and not c['uguali']]
    if not casi:
        return
    casi.sort(key=lambda c: per_arena[c['arena']]['modello_premio']
              - per_arena[c['arena']]['utente_premio'], reverse=True)

    def blocco(titolo, elenco):
        print(f"\n--- {titolo} ---")
        for c in elenco:
            d = per_arena[c['arena']]
            fuori = [n for n in c['carte_utente'] if n not in c['carte_modello']]
            dentro = [n for n in c['carte_modello'] if n not in c['carte_utente']]
            print(f"\n  {c['fixture']}  {c['tipo']}  (ingresso {d['ingresso']})")
            print(f"    toglie : {', '.join(fuori) or '-'}")
            print(f"    mette  : {', '.join(dentro) or '-'}")
            print(f"    utente  {d['utente_score']:6.1f} -> {d['utente_rank']}o, "
                  f"{d['utente_premio']} essenze")
            print(f"    modello {d['modello_score']:6.1f} -> {d['modello_rank']}o, "
                  f"{d['modello_premio']} essenze   "
                  f"[verdetto: {'ENTRA' if d['entra'] else 'NON entra'}]")

    print(f"\n{'='*74}")
    print("LE SCELTE: stesse carte della giornata, ridistribuite dal modello")
    print('='*74)
    print(f"\nFormazioni cambiate: {len(casi)} su {len(confronti)}")
    blocco(f"i {quante} casi in cui ci ha guadagnato di piu'", casi[:quante])
    blocco(f"i {quante} casi in cui ci ha rimesso di piu'", casi[-quante:][::-1])
