"""
scouting_gw.py -- i candidati all'acquisto di una giornata FUTURA.

Perche' esiste
--------------
La pipeline di produzione parte dalle carte POSSEDUTE e si appoggia alle
starter odds, che Sorare pubblica solo a 24-48h dal calcio d'inizio. Per
COMPRARE serve l'opposto: sapere con giorni di anticipo chi scendera' in campo
nella prossima giornata, includendo carte che l'utente non ha.

Due percorsi, stesso JSON in uscita
-----------------------------------
1. `searchPlayers` (DEFAULT, ~12 query, 7 secondi). E' la query dietro la
   pagina "Scouting" di Sorare: filtra per giornata e per stato del giocatore,
   e porta gia' L5/L10/L40, presenze, infortuni, proiezione, carte possedute e
   prezzo minimo. Vedi il blocco di commento sopra SEARCH_QUERY per le due
   trappole (alias sui nomi dei campi, filtri solo via `refinements`) e per il
   confronto misurato fra il suo filtro e il nostro.

2. `--roster`: il percorso lento di controllo. Fixture -> `anyGames` -> una
   query per club (~75) -> ~2.400 giocatori, poi `--screen` per la scrematura
   "2 delle ultime 3 partite con 60+ minuti", 1 query a giocatore. Serve a
   verificare il primo, non a sostituirlo: la sua uscita contiene anche
   giocatori senza carte sul mercato, che per un tool di acquisti sono rumore.

Uso
---
    python scouting_gw.py --gameweek 2
    python scouting_gw.py --fixture football-4-7-aug-2026 --screen
    python scouting_gw.py --roster --gameweek 2 --screen

Output: un JSON con, per ogni giocatore, ruolo, club, avversario, data e la
cartella `formazione_<lega>` a cui appartiene (o None se la lega non ha
pipeline -- viene segnalato, mai scartato in silenzio).
"""
import os
import re
import sys
import glob
import json
import time
import argparse
import datetime
import concurrent.futures
import importlib.util
from collections import defaultdict

if hasattr(sys.stdout, 'buffer'):  # console Windows in cp1252: i nomi non
    import io as _io      # latini farebbero morire lo script IN STAMPA, dopo
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _import(nome, rel_path):
    path = os.path.join(REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(nome, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# discovery_fixture porta la risoluzione della giornata, la mappa lega->cartella
# e la query delle partite; il modulo di discovery globale porta il client
# GraphQL con retry/backoff gia' tarato. Nessuna delle due logiche viene
# riscritta qui.
_df = _import('scouting_discovery_fixture', 'discovery_fixture.py')
_gql = _import('scouting_gql', 'formazione_mls/discovery/mls_def_discovery_global.py')

ROLE_BY_POSITION = {'Goalkeeper': 'GK', 'Defender': 'DEF',
                    'Midfielder': 'MID', 'Forward': 'FWD'}

# Roster di un club. Stessa query di <lega>_<ruolo>_discovery_global.py:
# `activePlayers` e' la rosa ATTUALE, non `anyPlayers` che e' il roster storico
# (bug reale del 30/07: il Bayern tornava 346 giocatori fra giovanili ed
# ex-tesserati, e i trasferiti restavano attribuiti al club vecchio).
TEAM_ROSTER_QUERY = """
query TeamRoster($slug: String!, $first: Int!, $after: String) {
  football {
    club(slug: $slug) {
      slug
      name
      domesticLeague { slug }
      activePlayers(first: $first, after: $after) {
        nodes {
          slug
          displayName
          anyPositions
          activeClub { slug }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

PAUSA = float(os.environ.get('SCOUTING_PAUSA', '0.25'))
PAGINA_ROSTER = int(os.environ.get('SCOUTING_PAGINA_ROSTER', '50'))


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    print(f"[{ts}] [scouting_gw] {msg}", flush=True)


def risolvi_giornata(gameweek=None, fixture_slug=None):
    """La fixture target. Accetta il numero di giornata o lo slug; senza
    nessuno dei due usa la risoluzione automatica di discovery_fixture (la
    prossima giornata aperta)."""
    if fixture_slug:
        fx, _ = _df._resolve_query_with_retry(
            _df.FIXTURE_BY_SLUG, {"slug": fixture_slug}, "FixtureBySlug",
            lambda d: ((d.get('data') or {}).get('so5') or {}).get('so5Fixture'))
        return fx
    nodes, _ = _df._resolve_query_with_retry(
        _df.FIXTURE_BY_GW, {"first": 30}, "FixtureList",
        lambda d: (((d.get('data') or {}).get('so5') or {}).get('so5Fixtures') or {}).get('nodes') or None)
    nodes = nodes or []
    if gameweek is not None:
        match = [n for n in nodes if str(n.get('seasonGameWeek')) == str(gameweek)]
        if match:
            # A cavallo di due stagioni lo stesso numero puo' comparire due
            # volte (la 95 di luglio e la 1 di agosto): si prende la piu'
            # recente non ancora conclusa.
            match.sort(key=lambda n: n.get('startDate') or '')
            return match[-1]
        disponibili = sorted({str(n.get('seasonGameWeek')) for n in nodes})
        log(f"ERRORE: giornata {gameweek} non fra quelle restituite: {disponibili}")
        return None
    return _df.risolvi_fixture()


def partite_della_giornata(slug):
    """(club -> (avversario, data)) per ogni squadra in campo. Una query."""
    games, _ = _df._resolve_query_with_retry(
        _df.FIXTURE_GAMES, {"slug": slug}, "FixtureGames",
        lambda d: (((d.get('data') or {}).get('so5') or {}).get('so5Fixture') or {}).get('anyGames'))
    avversario = {}
    for g in games or []:
        casa = (g.get('homeTeam') or {}).get('slug')
        fuori = (g.get('awayTeam') or {}).get('slug')
        if not (casa and fuori):
            # Fuori dalle competizioni di club homeTeam/awayTeam possono
            # essere vuoti (visto su global-cup): la partita non e' usabile
            # per capire chi gioca, si salta dicendolo.
            log(f"ATTENZIONE: partita senza entrambe le squadre, ignorata ({g.get('date')}).")
            continue
        avversario[casa] = (fuori, g.get('date'))
        avversario[fuori] = (casa, g.get('date'))
    return avversario, len(games or [])


def roster_club(slug):
    """Rosa attuale di un club: lista di (slug, nome, [posizioni]).

    Tiene solo chi ha `activeClub` UGUALE al club richiesto: Sorare elenca
    anche i tesserati della squadra B (visto su Sparta Praha, due difensori
    con activeClub 'sparta-praha-ii'), che in prima squadra non giocano."""
    fuori, after, lega = [], None, None
    for _pagina in range(10):
        d = _gql.graphql_query(TEAM_ROSTER_QUERY,
                               {"slug": slug, "first": PAGINA_ROSTER, "after": after},
                               operation_name="TeamRoster")
        club = ((d.get('data') or {}).get('football') or {}).get('club') or {}
        if not club:
            log(f"ATTENZIONE: nessun club per slug '{slug}' -- saltato.")
            return [], None
        lega = (club.get('domesticLeague') or {}).get('slug')
        conn = club.get('activePlayers') or {}
        for n in conn.get('nodes') or []:
            if ((n.get('activeClub') or {}).get('slug')) != slug:
                continue
            fuori.append((n.get('slug'), n.get('displayName'), n.get('anyPositions') or []))
        info = conn.get('pageInfo') or {}
        if not info.get('hasNextPage') or not info.get('endCursor'):
            break
        after = info.get('endCursor')
    return fuori, lega


def costruisci_pool(gameweek=None, fixture_slug=None):
    fx = risolvi_giornata(gameweek, fixture_slug)
    if not fx:
        return None
    log(f"Giornata: {fx.get('slug')} (gameweek {fx.get('seasonGameWeek')}, "
        f"stato {fx.get('aasmState')}, {fx.get('startDate')} -> {fx.get('endDate')})")

    avversario, n_partite = partite_della_giornata(fx.get('slug'))
    log(f"Partite: {n_partite} | club in campo: {len(avversario)}")
    if not avversario:
        log("ERRORE: nessuna squadra ricavata dalla fixture.")
        return None

    giocatori = []
    leghe_senza_pipeline = defaultdict(set)
    for i, club in enumerate(sorted(avversario), 1):
        rosa, lega = roster_club(club)
        cartella = _df.LEAGUE_DIR.get(lega)
        if lega and not cartella:
            leghe_senza_pipeline[lega].add(club)
        opp, data = avversario[club]
        for slug, nome, posizioni in rosa:
            ruoli = [ROLE_BY_POSITION[p] for p in posizioni if p in ROLE_BY_POSITION]
            if not ruoli:
                continue
            giocatori.append({
                'slug': slug, 'nome': nome, 'ruoli': ruoli,
                'club': club, 'avversario': opp, 'data': data,
                'lega': lega, 'cartella': cartella,
            })
        if i % 10 == 0 or i == len(avversario):
            log(f"  roster {i}/{len(avversario)} club, {len(giocatori)} giocatori finora")
        time.sleep(PAUSA)

    # Un giocatore puo' comparire con piu' ruoli (il ruolo su Sorare vive sulla
    # CARTA, non sul giocatore -- caso reale Lee Dong-kyung, classic da
    # centrocampo e in season da attacco): si tiene la lista, non si sceglie.
    per_ruolo = defaultdict(int)
    for g in giocatori:
        for r in g['ruoli']:
            per_ruolo[r] += 1
    log(f"POOL: {len(giocatori)} giocatori "
        f"(GK {per_ruolo['GK']}, DEF {per_ruolo['DEF']}, MID {per_ruolo['MID']}, FWD {per_ruolo['FWD']})")
    if leghe_senza_pipeline:
        for lega, clubs in sorted(leghe_senza_pipeline.items()):
            log(f"ATTENZIONE: lega '{lega}' senza cartella formazione_* "
                f"({len(clubs)} club) -- i suoi giocatori restano nel pool ma "
                f"non avranno punteggio atteso finche' non si aggiunge la voce "
                f"in LEAGUE_DIR di discovery_fixture.py.")

    return {
        'fixture': {k: fx.get(k) for k in ('slug', 'seasonGameWeek', 'aasmState', 'startDate', 'endDate')},
        'club_in_campo': len(avversario),
        'partite': n_partite,
        'giocatori': giocatori,
        'leghe_senza_pipeline': {k: sorted(v) for k, v in leghe_senza_pipeline.items()},
    }


# --- IL PERCORSO VELOCE: searchPlayers -------------------------------------
#
# E' la query dietro la pagina "Scouting" di Sorare, e fa in ~12 chiamate quello
# che sopra ne costa ~2.400: filtra per giornata, porta L5/L10/L40, presenze,
# infortuni, proiezione, carte possedute, prezzo minimo e -- quando esistono --
# le starter odds. Il pool dei roster resta come controllo (--roster), non
# perche' serva: vedi la misura sotto.
#
# Due trappole costate un'ora il 02/08, entrambe invisibili dal payload del
# browser:
#
#   1. i nomi che si leggono nella RISPOSTA sono ALIAS. `lastTenPlayedSo5-
#      AverageScore` non esiste su Player: il campo vero e'
#      `averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)`. L'errore
#      GraphQL suggerisce `lastFortySo5Appearances` e manda fuori strada.
#   2. `rarity` e `inSeason` NON sono argomenti di searchPlayers. Tutto passa
#      dai `refinements`, compresi rarita' e prezzi (`floor_prices.*`).
#
# E un limite da conoscere: il VALORE del floor non e' richiedibile (non esiste
# un campo `floorPrices` sull'oggetto), si puo' solo FILTRARE. Il prezzo che
# torna e' `lowestPriceAnyCard`, cioe' la carta piu' economica di QUALUNQUE
# rarita' e stagione, a volte quotata in USD/GBP/ETH invece che in euro.
#
# Perche' il filtro e' quello di Sorare e non il nostro (misurato su GW2):
#
#     nostro pool (roster dei 74 club)      2357
#     nostri idonei (2-su-3 a 60')           890
#     pool searchPlayers                    1147
#     playing_status starter+regular         557
#
# Dei nostri 890 idonei solo 527 esistono nel pool di searchPlayers: gli altri
# 363 non sono nell'indice del mercato, cioe' NON SONO ACQUISTABILI (il caso
# limite e' Vikingur Reykjavik, 1 carta in vendita su 31 giocatori). Sulla base
# comune i due filtri concordano su 478; 49 passano solo il nostro, 79 solo
# quello di Sorare. Scelta dell'utente: filtra Sorare, il nostro 2-su-3 resta
# come dato di controllo da calcolare a parte sui sopravvissuti.
SEARCH_QUERY = """
query ScoutingGiornata($page: Int!, $pageSize: Int!,
                       $refinements: [SearchRefinementInput!], $advancedFilters: String) {
  searchPlayers(query: "", page: $page, pageSize: $pageSize,
                refinements: $refinements, advancedFilters: $advancedFilters) {
    nbHits
    nbPages
    commonPlayerHits {
      anyPlayer {
        slug
        displayName
        anyPositions
        activeClub { slug ... on Club { domesticLeague { slug } } }
        activeInjuries { id }
        l5:  averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE)
        l10: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
        l40: averageScore(type: LAST_FORTY_SO5_AVERAGE_SCORE)
        lastFiveSo5Appearances
        lastFifteenSo5Appearances
        lastFortySo5Appearances
        # `nextClassicFixtureProjectedGrade` e' la prossima partita DEL
        # GIOCATORE, non della fixture che stiamo interrogando (trappola
        # generale sui campi `next*`, vedi HANDOFF_UNIFICATO_MODELLO_
        # SCOUTING.md §8 trappola 17). Regge SOLO perche' il refinement
        # `playing_next=<fixture_target>` (vedi _refinements) filtra a
        # monte chi gioca in quella fixture: verificato 09/08/2026 che
        # anche i club con una GW precedente ancora da chiudere (18 casi,
        # 8 con carta nel bench per il confronto) danno lo stesso grade
        # del bench di produzione scoped alla fixture target (116/117
        # identici in totale, 8/8 sul sottoinsieme a rischio) -- §8ter.
        # Non riusare questo campo SENZA lo stesso filtro playing_next.
        ... on Player { age ownedCardsCount nextClassicFixtureProjectedScore
          nextClassicFixtureProjectedGrade { grade } }
        lowestPriceAnyCard(rarity: limited) {
          rarityTyped
          liveSingleSaleOffer {
            receiverSide { amounts { eurCents usdCents gbpCents wei lamport referenceCurrency } }
          }
        }
      }
    }
  }
}
"""

# Le starter odds NON si prendono da qui, ed e' una cosa da sapere prima di
# riprovarci: `anyGameStats(last: N)` restituisce solo partite GIA' GIOCATE, e
# la giornata target e' futura per definizione (verificato il 02/08: chiedendo
# fino a 8 righe, la piu' recente e' sempre la giornata precedente). Nel payload
# del browser la riga della giornata futura compare perche' la loro query usa il
# contesto "scoped" sulla fixture, che da fuori non e' esprimibile.
#
# Restano quelle che la pipeline gia' usa:
# discovery_fixture.odds_e_l10_singola / best_five, `footballPlayingStatusOdds
# { starterOddsBasisPoints reliability }`, una query a giocatore -- sostenibile
# proprio perche' arriva DOPO questo filtro, su qualche centinaio di nomi.

# Gli stati che Sorare considera "gioca". `not_playing`, `substitute` e
# `super_substitute` restano fuori dal filtro ma il campo NON viene chiesto per
# giocatore: e' gia' il refinement a selezionarli.
STATI_TITOLARE = tuple(
    s.strip() for s in os.environ.get('SCOUTING_STATI', 'starter,regular').split(',') if s.strip())

PAGINA_SEARCH = int(os.environ.get('SCOUTING_PAGINA_SEARCH', '50'))

# --- L'ECONOMIA DELL'ACQUISTO ---------------------------------------------
#
# Una carta si schiera UNA volta per giornata in arena (regola di gioco, non
# stima): niente moltiplicatore per il numero di arene, il ritorno e' per GW.
#
# Il campo di un'arena vale ~259 punti su 5 carte, quindi uno slot medio vale
# ~51.8 punti; il gradiente misurato dice che +20 punti sopra il campo valgono
# +153 essenze a ingresso, cioe' ~7.65 essenze per punto (sez. 46.B).
#
# Da qui l'unico rapporto che regge: EURO PER ESSENZA-AL-TURNO, cioe'
# prezzo / essenze guadagnate a giornata. Il valore in euro dell'essenza NON
# serve per sceglere fra candidati -- e' un fattore comune a tutti, moltiplica
# tutto per lo stesso numero e non cambia l'ordine. Serve solo a decidere se
# comprare in assoluto, e quella resta una valutazione manuale dell'utente.
#
# Il tasso serve percio' a una cosa sola, le "GW di rientro", e va dichiarato:
# il riassunto stima 1000 essenze fra 0.50 e 15 EUR a seconda di come le spendi
# (craft, burn, indizi), con 3 EUR come numero di lavoro. Qui il default e' 2,
# scelta dell'utente come valore MINIMO prudente: se sbaglia, sbaglia dicendo
# che una carta rende meno di quanto rendera'.
#
# Il rientro si calcola sul PREZZO PIENO, che e' il caso pessimo: le classic si
# rivendono, e una stima seria del deprezzamento non e' possibile (Yamal da 187
# in season a ~120 classic; per una carta di Liga MX non si sa nemmeno quante
# giornate Sorare coprira'). Meglio una soglia prudente di una stima finta.
# Quanto puo' essere vecchio un consiglio per valere ancora: oltre, l'atteso e'
# di un'altra giornata e di un altro avversario.
ORE_CONSIGLIO_VALIDO = float(os.environ.get('SCOUTING_ORE_CONSIGLIO', '12'))

# FALLBACK statici, usati solo se il generatore non e' caricabile (vedi
# _slot_medio_e_per_punto). B01/B02 (passaggio 2, P2): prima erano l'UNICO
# valore usato, sempre, confrontati con un atteso GREZZO -- due errori che si
# sommavano (scala diversa fra generatore e scouting, e valore non aggiornato
# col merge del 05/08 che aveva portato la cap 260 da 8.8 a 7.9 essenze/punto).
PUNTI_SLOT_MEDIO = float(os.environ.get('SCOUTING_PUNTI_SLOT', '51.8'))
ESSENZE_PER_PUNTO = float(os.environ.get('SCOUTING_ESSENZE_PUNTO', '8.8'))
EURO_PER_1000_ESSENZE = float(os.environ.get('SCOUTING_EURO_1000_ESSENZE', '2'))
# RIMOSSA (B03, P7 passaggio 2): RAPPORTO_ARENA_MINIMO_TESTO='1.019' era un
# valore statico (265.0/260, superato dal 05/08: il vivo e' 259.5/260=0.998)
# e mai letto da nessun tooltip o punto del codice -- costante morta, non
# solo stale. best_five.PAREGGIO_ARENA_260/RAPPORTO_ARENA_MINIMO a cui
# puntava sono a loro volta morte (mai importate da qui ne' da altri, vedi
# rimozione in best_five.py).


def _slot_medio_e_per_punto(gg):
    """Slot medio (punti REALI di uno slot in una formazione da 5 a cap 260) e
    essenze guadagnate per punto REALE sopra quella soglia -- dal generatore,
    stessa fonte della sezione arene (getattr, come _conto_arena), non piu'
    una costante locale scollegata (B02).

    PAREGGIO_ARENA['ARENA_ALLSTARS_260'] e' il pareggio della FORMAZIONE da 5
    carte: diviso 5 e' il pareggio di UNO slot, la stessa quantita' che
    PUNTI_SLOT_MEDIO approssimava a mano. GUADAGNO_PER_PUNTO della stessa
    chiave e' l'essenze/punto REALE per quel tipo di arena -- si compra per
    giocare in cap 260, quindi e' quella la scala giusta, non una media fra
    tipi diversi. Fallback ai vecchi default statici se gg manca o non ha
    ancora queste chiavi (nessuna regressione per chi non ha il generatore)."""
    if gg is None:
        return PUNTI_SLOT_MEDIO, ESSENZE_PER_PUNTO
    pareggio = getattr(gg, 'PAREGGIO_ARENA', {}).get('ARENA_ALLSTARS_260')
    per_punto = getattr(gg, 'GUADAGNO_PER_PUNTO', {}).get('ARENA_ALLSTARS_260')
    slot_medio = (pareggio / 5.0) if pareggio is not None else PUNTI_SLOT_MEDIO
    per_punto = per_punto if per_punto is not None else ESSENZE_PER_PUNTO
    return slot_medio, per_punto


def _economia(atteso, prezzo_eur, slot_medio=None, per_punto=None):
    """(essenze a giornata, euro per essenza-al-turno, GW di rientro).

    Ognuno None quando non calcolabile, mai zero al posto di 'non lo so'.
    slot_medio/per_punto: se non passati, ricadono sui vecchi default statici
    (compatibilita' per chiamanti che non hanno gg)."""
    if not atteso:
        return None, None, None
    sm = PUNTI_SLOT_MEDIO if slot_medio is None else slot_medio
    pp = ESSENZE_PER_PUNTO if per_punto is None else per_punto
    essenze_gw = (atteso - sm) * pp
    if prezzo_eur is None or essenze_gw <= 0:
        # Sotto la media di slot la carta non guadagna essenze: un "euro per
        # essenza" li' sarebbe un numero senza senso, e le GW di rientro
        # sarebbero infinite. Si mostra il vantaggio negativo e basta.
        return essenze_gw, None, None
    euro_per_essenza_gw = prezzo_eur / essenze_gw
    euro_a_giornata = essenze_gw / 1000.0 * EURO_PER_1000_ESSENZE
    return essenze_gw, euro_per_essenza_gw, prezzo_eur / euro_a_giornata


# Il rapporto minimo punti/L10 sotto cap 260, misurato su 673 arene reali: sotto
# questa riga la carta non paga il posto che occupa nel cap. Vive qui perche' il
# report lo usa per colorare la colonna Att/L10 -- se cambia in produzione, va
# cambiato anche qui (e nella tabella dei numeri di riferimento).
SOGLIA_PUNTI_PER_L10 = float(os.environ.get('SCOUTING_SOGLIA_L10', '1.017'))


def _refinements(fixture_slug, stati=STATI_TITOLARE, solo_in_vendita=True):
    ref = [{"field": "playing_next", "operator": "EQUAL",
            "values": [{"stringValue": fixture_slug}]}]
    if stati:
        ref.append({"field": "player.playing_status", "operator": "EQUAL",
                    "values": [{"stringValue": s} for s in stati]})
    if solo_in_vendita:
        # Toglie chi non ha NESSUNA limited in vendita: su GW2 sono 28
        # giocatori, che per un tool di acquisti sono rumore puro.
        ref.append({"field": "floor_prices.all_seasons.limited",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "values": [{"integerValue": 1}]})
    return ref


# I cambi arrivano da frankfurter.app, la stessa fonte gia' usata da
# bots/autobuy_sorare.py: una chiamata per valuta per run, poi in cache. Se non
# risponde si usa un fallback statico -- un cambio approssimato e' meglio di un
# prezzo mancante, e serve solo a ordinare i candidati.
_CAMBI = {}
_CAMBI_FALLBACK = {'USD': 0.92, 'GBP': 1.17}


def _cambio_in_eur(valuta):
    if valuta in _CAMBI:
        return _CAMBI[valuta]
    tasso = _CAMBI_FALLBACK.get(valuta, 1.0)
    try:
        import requests
        r = requests.get(f"https://api.frankfurter.app/latest?from={valuta}&to=EUR", timeout=5)
        tasso = float(r.json()['rates']['EUR'])
    except Exception as e:
        log(f"ATTENZIONE: cambio {valuta}->EUR non recuperato ({e}), uso {tasso}.")
    _CAMBI[valuta] = tasso
    return tasso


def _prezzo_eur(player):
    """(euro, valuta_originale) della limited piu' economica in vendita.

    Sempre e solo LIMITED: e' la rarita' che si usa in arena, e la query la
    filtra a monte con `lowestPriceAnyCard(rarity: limited)`.

    USD e GBP vengono convertiti. Le offerte in cripto (ETH, SOL) tornano
    (None, 'CRIPTO') e il chiamante le scarta: l'utente compra solo in euro,
    quindi una carta acquistabile solo in ETH non e' un candidato -- tenerla in
    elenco con un prezzo finto sarebbe peggio che non averla."""
    card = player.get('lowestPriceAnyCard') or {}
    amounts = (((card.get('liveSingleSaleOffer') or {}).get('receiverSide') or {})
               .get('amounts')) or {}
    if not amounts:
        return None, None
    if amounts.get('eurCents') is not None:
        return amounts['eurCents'] / 100.0, 'EUR'
    for chiave, valuta in (('usdCents', 'USD'), ('gbpCents', 'GBP')):
        if amounts.get(chiave) is not None:
            return amounts[chiave] / 100.0 * _cambio_in_eur(valuta), valuta
    if amounts.get('wei') is not None or amounts.get('lamport') is not None:
        return None, 'CRIPTO'
    return None, None


def pool_da_search(gameweek=None, fixture_slug=None,
                   stati=STATI_TITOLARE, solo_in_vendita=True):
    """Il pool della giornata via searchPlayers: ~12 query invece di ~2.400.

    Stesso schema di uscita di costruisci_pool -- chi legge il JSON non deve
    sapere da quale dei due percorsi arriva -- con in piu' i campi che
    searchPlayers regala: L5/L40, presenze, infortuni, proiezione Sorare, carte
    possedute, prezzo minimo e starter odds quando esistono."""
    fx = risolvi_giornata(gameweek, fixture_slug)
    if not fx:
        return None
    slug_fx = fx.get('slug')
    log(f"Giornata: {slug_fx} (gameweek {fx.get('seasonGameWeek')}, "
        f"stato {fx.get('aasmState')}, {fx.get('startDate')} -> {fx.get('endDate')})")

    # La fixture serve comunque, per l'avversario: searchPlayers da' la partita
    # del giocatore, ma non tutte le partite della giornata.
    avversario, n_partite = partite_della_giornata(slug_fx)
    log(f"Partite: {n_partite} | club in campo: {len(avversario)}")

    ref = _refinements(slug_fx, stati, solo_in_vendita)
    log(f"Filtri: playing_next={slug_fx}"
        + (f", playing_status={'/'.join(stati)}" if stati else ", nessun filtro di stato")
        + (", solo con limited in vendita" if solo_in_vendita else ""))

    query = SEARCH_QUERY
    # Il client di bot_profit, non quello di discovery_global: misurato il
    # 02/08, con quest'ultimo la stessa identica query passa alla pagina 1 e
    # viene poi respinta con "depth 8 / complexity 1404" da tutte le successive,
    # mentre con bot_profit passa sempre. Il tetto e' sull'header, non sulla
    # forma della query -- e come effetto collaterale si eredita il throttle.
    client = _client_ritmato()

    def _chiedi(variabili):
        if client is not None:
            return client.graphql_query(query, variabili) or {}
        return _gql.graphql_query(query, variabili,
                                  operation_name="ScoutingGiornata") or {}

    giocatori, visti = [], set()
    leghe_senza_pipeline = defaultdict(set)
    scartati_cripto = 0
    pagina, pagine_totali, nb_hits = 1, 1, None
    while pagina <= pagine_totali:
        d = _chiedi({"page": pagina, "pageSize": PAGINA_SEARCH,
                     "advancedFilters": "sport:football", "refinements": ref})
        if d.get('errors') or not d.get('data'):
            log(f"ERRORE alla pagina {pagina}: {str(d.get('errors'))[:200]}")
            return None
        res = (d.get('data') or {}).get('searchPlayers') or {}
        if nb_hits is None:
            nb_hits = res.get('nbHits')
            pagine_totali = res.get('nbPages') or 1
            log(f"searchPlayers: {nb_hits} giocatori su {pagine_totali} pagine da {PAGINA_SEARCH}")
        for hit in res.get('commonPlayerHits') or []:
            p = hit.get('anyPlayer') or {}
            slug = p.get('slug')
            if not slug or slug in visti:
                continue
            visti.add(slug)
            ruoli = [ROLE_BY_POSITION[x] for x in (p.get('anyPositions') or [])
                     if x in ROLE_BY_POSITION]
            if not ruoli:
                # Allenatori e ruoli non giocanti: searchPlayers li restituisce
                # (caso reale Rafael Marquez, anyPositions ['Coach']).
                continue
            club = (p.get('activeClub') or {}).get('slug')
            lega = ((p.get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
            cartella = _df.LEAGUE_DIR.get(lega)
            if lega and not cartella:
                leghe_senza_pipeline[lega].add(club)
            opp, data = avversario.get(club, (None, None))
            prezzo, valuta = _prezzo_eur(p)
            if valuta == 'CRIPTO':
                # Acquistabile solo in ETH/SOL: non e' un candidato, l'utente
                # compra in euro. Contato e riportato, non sparito in silenzio.
                scartati_cripto += 1
                continue
            giocatori.append({
                'slug': slug, 'nome': p.get('displayName'), 'ruoli': ruoli,
                'club': club, 'avversario': opp, 'data': data,
                'lega': lega, 'cartella': cartella,
                'l5': p.get('l5'), 'l10': p.get('l10'), 'l40': p.get('l40'),
                'presenze_5': p.get('lastFiveSo5Appearances'),
                'presenze_15': p.get('lastFifteenSo5Appearances'),
                'presenze_40': p.get('lastFortySo5Appearances'),
                'eta': p.get('age'),
                'carte_mie': p.get('ownedCardsCount'),
                'infortunato': bool(p.get('activeInjuries')),
                'proiezione_sorare': p.get('nextClassicFixtureProjectedScore'),
                'grade': (p.get('nextClassicFixtureProjectedGrade') or {}).get('grade'),
                'prezzo_eur': round(prezzo, 2) if prezzo is not None else None,
                'prezzo_valuta_originale': valuta,
                'prezzo_rarita': (p.get('lowestPriceAnyCard') or {}).get('rarityTyped'),
            })
        pagina += 1
        time.sleep(PAUSA)

    per_ruolo = defaultdict(int)
    for g in giocatori:
        for r in g['ruoli']:
            per_ruolo[r] += 1
    log(f"POOL: {len(giocatori)} giocatori "
        f"(GK {per_ruolo['GK']}, DEF {per_ruolo['DEF']}, MID {per_ruolo['MID']}, FWD {per_ruolo['FWD']})")
    if scartati_cripto:
        log(f"Scartati {scartati_cripto} giocatori la cui limited piu' economica "
            f"e' in vendita solo in cripto (ETH/SOL): si compra in euro.")
    if leghe_senza_pipeline:
        for lega, clubs in sorted(leghe_senza_pipeline.items()):
            log(f"ATTENZIONE: lega '{lega}' senza cartella formazione_* "
                f"({len(clubs)} club) -- i suoi giocatori restano nel pool ma non "
                f"avranno punteggio atteso finche' non si aggiunge la voce in "
                f"LEAGUE_DIR di discovery_fixture.py.")

    return {
        'fixture': {k: fx.get(k) for k in ('slug', 'seasonGameWeek', 'aasmState', 'startDate', 'endDate')},
        'sorgente': 'searchPlayers',
        'filtri': {'stati': list(stati), 'solo_in_vendita': solo_in_vendita},
        'club_in_campo': len(avversario),
        'partite': n_partite,
        'giocatori': giocatori,
        'leghe_senza_pipeline': {k: sorted(v) for k, v in leghe_senza_pipeline.items()},
    }


# --- FASE 2: la scrematura -------------------------------------------------
#
# Il pool di una giornata sono ~2.400 giocatori, ma la gran parte non scende in
# campo: riserve, giovani, chi non ha mai esordito. Senza le odds l'unico
# segnale disponibile e' il passato prossimo, ed e' quello che l'utente usa a
# mano: chi ha appena giocato da titolare probabilmente rigiochera'.
#
# Criterio: almeno 2 delle ultime 3 partite con 60+ minuti. Il "2 su 3" tollera
# un turno di riposo o un'uscita anticipata senza buttare via un titolare vero,
# che e' il rischio che conta -- in una giornata infrasettimanale i candidati
# sono gia' pochi. Non si filtra per competizione (scelta esplicita
# dell'utente): contano i minuti, da qualunque partita arrivino.
#
# Resta una scrematura, non un verdetto: la titolarita' vera la giudica
# l'utente sui sopravvissuti.
SCREEN_QUERY = """
query Screen($slug: String!, $first: Int!) {
  anyPlayer(slug: $slug) {
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    allPlayerGameScores(first: $first) {
      nodes {
        anyGame { date competition { slug } }
        anyPlayerGameStats {
          ... on PlayerGameStats { fieldStatus gameStarted minsPlayed }
        }
      }
    }
  }
}
"""

# Il criterio e' PER GIOCATORE, non per giornata di calendario: si guardano le
# sue ultime partite, non le ultime giornate Sorare. Un giocatore la cui
# squadra ha saltato due giornate non va penalizzato -- caso reale Skriniar,
# le cui due partite piu' recenti sono di Champions, entrambe da titolare.
#
# `fieldStatus` distingue tre situazioni che i soli minuti confondono:
#   ON_FIELD / SUBSTITUTED  ha giocato
#   ON_BENCH                era in panchina e non e' entrato -- conta come non
#                           giocata, e' una scelta tecnica (Brady in global-cup)
#   NOT_ON_GAME_SHEET       non era nemmeno in distinta, tipicamente amichevoli
#                           o finestre di nazionale (Rondon, due friendlies con
#                           minsPlayed null). Queste si ESCLUDONO: non dicono
#                           niente sulla sua titolarita' di club, e contarle
#                           come zero minuti scarterebbe titolari veri.
FIELD_STATUS_DA_IGNORARE = {'NOT_ON_GAME_SHEET'}

# Si chiedono piu' righe di quelle che servono, perche' una parte viene
# scartata dal filtro sopra: 8 bastano a trovarne 3 valide anche a chi ha
# appena avuto una finestra di nazionale.
PARTITE_DA_CHIEDERE = int(os.environ.get('SCOUTING_PARTITE_CHIESTE', '8'))
PARTITE_DA_GUARDARE = int(os.environ.get('SCOUTING_PARTITE', '3'))
MINUTI_TITOLARE = int(os.environ.get('SCOUTING_MINUTI', '60'))
IDONEI_SU = int(os.environ.get('SCOUTING_IDONEI_SU', '2'))


# Il ritmo lo governa il throttle di scanners/bot_profit.py, non uno scritto
# qui. Motivo, misurato sul campo il 02/08: la prima versione spalmava la
# scrematura su 8 job paralleli con una pausa fissa di 0,2s, e tutti e otto
# hanno preso un 429 quasi subito. Il tetto di Sorare e' sull'ACCOUNT (~60
# richieste al minuto autenticato), non sul job: parallelizzare i runner non
# alza il tetto, lo sfonda piu' in fretta.
#
# `bot_profit` quel problema lo ha gia' risolto, con numeri veri alle spalle
# (run 66: 835 429 su ~2000 richieste; run 72 a regime: 36). Tre pezzi:
#   - BARRIERA GLOBALE condivisa: a un 429 si fermano tutti i thread, non solo
#     lo sfortunato, cosi' un'ondata non si moltiplica per il numero di worker;
#   - RITMO adattivo: l'intervallo fra richieste sale a ogni ondata e
#     ridiscende dopo 40 richieste consecutive andate a buon fine;
#   - riconoscimento dell'header `Retry-After`, che Sorare valorizza a ~45s.
#
# Qui si riusa il suo `graphql_query` e basta: nessun throttle nostro da
# tarare, e i miglioramenti futuri di quel file arrivano gratis.
def _client_ritmato():
    """Il client GraphQL di bot_profit, o None se non utilizzabile.

    Non tocca nessuna delle sue strutture con effetti collaterali (blacklist,
    cache): si usa solo la funzione di query."""
    try:
        path = os.path.join(REPO_ROOT, 'scanners', 'bot_profit.py')
        spec = importlib.util.spec_from_file_location('scouting_bot_profit', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not mod.COOKIES:
            log("ATTENZIONE: SORARE_COOKIE assente, uso il client base senza throttle.")
            return None
        return mod
    except Exception as e:
        log(f"ATTENZIONE: throttle di bot_profit non disponibile ({e}), uso il client base.")
        return None


WORKER = int(os.environ.get('SCOUTING_WORKER', '6'))


def _partite_valutabili(player, quante=None):
    """Le ultime partite che dicono qualcosa sulla titolarita' di club.

    Ordine dalla piu' recente, gia' filtrate da FIELD_STATUS_DA_IGNORARE e
    troncate a 'quante'."""
    quante = PARTITE_DA_GUARDARE if quante is None else quante
    out = []
    for n in (player.get('allPlayerGameScores') or {}).get('nodes') or []:
        stats = n.get('anyPlayerGameStats') or {}
        if stats.get('fieldStatus') in FIELD_STATUS_DA_IGNORARE:
            continue
        out.append({
            'data': ((n.get('anyGame') or {}).get('date') or '')[:10],
            'competizione': ((n.get('anyGame') or {}).get('competition') or {}).get('slug'),
            'minuti': stats.get('minsPlayed') or 0,
            'stato': stats.get('fieldStatus'),
        })
        if len(out) >= quante:
            break
    return out


def _valuta(g, client):
    """Una query, e l'esito della scrematura per un giocatore."""
    if client is not None:
        d = client.graphql_query(SCREEN_QUERY,
                                 {"slug": g['slug'], "first": PARTITE_DA_CHIEDERE}) or {}
    else:
        d = _gql.graphql_query(SCREEN_QUERY,
                               {"slug": g['slug'], "first": PARTITE_DA_CHIEDERE},
                               operation_name="Screen") or {}
    if d.get('errors') or not d.get('data'):
        # Un errore non e' un "non idoneo": si segna come ignoto, cosi' non
        # sparisce in silenzio (e' la classe di bug che in questo progetto ha
        # gia' fatto perdere giocatori posseduti).
        g['idoneo'] = None
        g['errore'] = str(d.get('errors'))[:120]
        return g
    p = (d.get('data') or {}).get('anyPlayer') or {}
    recenti = _partite_valutabili(p)
    titolari = sum(1 for r in recenti if r['minuti'] >= MINUTI_TITOLARE)
    g['l10'] = p.get('lastTenPlayedAvgScore')
    g['partite_recenti'] = recenti
    g['minuti_recenti'] = [r['minuti'] for r in recenti]
    g['partite_da_titolare'] = titolari
    # Chi non ha nemmeno una partita valutabile (mai sceso in campo, appena
    # tesserato) non e' "non idoneo": e' non valutabile, e va detto.
    g['idoneo'] = (titolari >= IDONEI_SU) if recenti else None
    return g


def screma(giocatori, worker=None):
    """Aggiunge a ogni giocatore L10, minuti recenti ed esito della scrematura.

    Una query per giocatore, che porta ENTRAMBE le cose (L10 e ultime partite)
    nello stesso `anyPlayer`: non e' l'alias multiplo che Sorare rifiuta
    ("Duplicated root field"), e' un solo nodo con due gruppi di campi. Stessa
    forma gia' usata in discovery_fixture.odds_e_l10_singola per dimezzare le
    chiamate.

    Il ritmo lo detta il throttle condiviso di bot_profit (vedi
    _client_ritmato): i worker qui sotto NON accelerano oltre quel tetto, gli
    permettono solo di stare sempre pieno invece di lasciare la connessione
    ferma fra una risposta e la successiva."""
    client = _client_ritmato()
    worker = worker or (WORKER if client is not None else 1)
    log(f"Scrematura di {len(giocatori)} giocatori "
        f"({'throttle bot_profit' if client else 'client base'}, {worker} worker)")
    inizio = time.time()
    fatti = [0]

    def _uno(g):
        _valuta(g, client)
        fatti[0] += 1
        if fatti[0] % 200 == 0 or fatti[0] == len(giocatori):
            idonei = sum(1 for x in giocatori if x.get('idoneo'))
            trascorso = time.time() - inizio
            log(f"  {fatti[0]}/{len(giocatori)} -- idonei {idonei} "
                f"({trascorso:.0f}s, {fatti[0] / max(trascorso, 1e-9) * 60:.0f} giocatori/min)")

    if worker > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker) as pool:
            list(pool.map(_uno, giocatori))
    else:
        for g in giocatori:
            _uno(g)
    return giocatori


def _shard(giocatori):
    """Quota di questo job, se SCOUTING_SHARD='idx:n' e' impostata. Split
    'i % n == idx' come nel resto della pipeline: quote di dimensione simile
    senza dipendere dall'ordine."""
    raw = os.environ.get('SCOUTING_SHARD', '').strip()
    if not raw:
        return giocatori
    idx, n = (int(x) for x in raw.split(':'))
    quota = [g for i, g in enumerate(giocatori) if i % n == idx]
    log(f"SCOUTING_SHARD {idx}/{n}: {len(quota)} giocatori su {len(giocatori)}")
    return quota


def unisci(cartella):
    """Rimette insieme le quote prodotte dai job di scrematura.

    Ogni quota e' un pool completo con solo i suoi giocatori: si concatenano,
    l'intestazione della giornata e' la stessa per tutti. Deduplica per slug
    per sicurezza -- se due quote si sovrapponessero per un errore di sharding,
    meglio un giocatore solo che due righe uguali."""
    pezzi = sorted(glob.glob(os.path.join(cartella, '**', 'scouting_*.json'), recursive=True))
    if not pezzi:
        log(f"ERRORE: nessun file scouting_*.json sotto {cartella}.")
        return None
    unito, visti = None, set()
    for p in pezzi:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        if unito is None:
            unito = dict(d)
            unito['giocatori'] = []
        for g in d.get('giocatori') or []:
            if g['slug'] in visti:
                continue
            visti.add(g['slug'])
            unito['giocatori'].append(g)
        log(f"  {os.path.basename(p)}: {len(d.get('giocatori') or [])} giocatori")
    log(f"Unite {len(pezzi)} quote -> {len(unito['giocatori'])} giocatori distinti")
    return unito


def stampa_candidati(pool, limite=None):
    """I candidati del percorso searchPlayers, ordinati per L10 dentro il ruolo.

    Se e' stata fatta anche la scrematura nostra, la colonna 'min' mostra i
    minuti delle ultime partite: e' un controllo, non un filtro -- chi non la
    passa resta in elenco, marcato."""
    righe_tutte = pool['giocatori']
    scremati = any('idoneo' in g for g in righe_tutte)
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        righe = [g for g in righe_tutte if ruolo in g['ruoli']]
        righe.sort(key=lambda g: -(g.get('l10') or 0))
        print(f"\n=== {ruolo} -- {len(righe)} candidati")
        for g in (righe[:limite] if limite else righe):
            prezzo = ('--' if g.get('prezzo_eur') is None
                      else f"{g['prezzo_eur']:.2f}EUR")
            proiezione = ('--' if not g.get('proiezione_sorare')
                          else f"{g['proiezione_sorare']:.0f}")
            nota = ''
            if g.get('infortunato'):
                nota += ' INFORTUNATO'
            if scremati and g.get('idoneo') is False:
                nota += ' [non 2su3]'
            if g.get('carte_mie'):
                nota += f" [ne ho {g['carte_mie']}]"
            print(f"  {(g.get('nome') or g['slug'])[:24]:<24} L10 {(g.get('l10') or 0):>5.1f}  "
                  f"proj {proiezione:>3}  {prezzo:>9}  {(g.get('club') or '')[:22]:<22} "
                  f"vs {(g.get('avversario') or '')[:20]:<20} {(g.get('data') or '')[:10]}"
                  f"  [{g.get('cartella')}]{nota}")


# --- IL FILTRO STARTER ODDS ------------------------------------------------
#
# Identico a quello del generatore, e non "ispirato a": si chiama la sua
# `discovery_fixture.odds_e_l10_singola`, stessa query e stessa finestra di
# fixture. Stessa convenzione, che e' la parte che conta: ODDS ASSENTI =
# ESCLUSO. Un giocatore senza odds pubblicate non e' "forse titolare", e'
# ignoto -- trattarlo come idoneo rimetterebbe dentro proprio quelli che il
# filtro serve a togliere.
#
# Va usato SOLO quando le odds sono uscite (24-48h dal kickoff): prima, la
# soglia scarterebbe tutti. Per questo il default e' spento (0), che e' la
# differenza rispetto al generatore, dove le odds ci sono sempre perche' gira
# a ridosso della giornata.
#
# Si applica PRIMA del campionamento: scremare dopo vorrebbe dire scegliere i
# 40 migliori e poi scoprire che meta' non gioca, invece di scegliere i 40
# migliori FRA CHI GIOCA.
def filtra_per_odds(pool, soglia, worker=None):
    """Tiene solo chi ha starter odds >= soglia, prendendo le odds in BLOCCO
    dalle partite della giornata (discovery_fixture.odds_per_giornata): ~37
    query in <1s invece di una a candidato (che sotto rate-limit arrivava a
    12 minuti). Se le odds non sono ancora uscite (map vuota) NON si scarta
    nessuno: si analizza tutto il pool -- e' l'unico dato onesto prima delle
    24-48h dal kickoff."""
    fx = pool.get('fixture') or {}
    giocatori = pool['giocatori']
    slug_fixture = fx.get('slug')

    odds_map = _df.odds_per_giornata(slug_fixture) if slug_fixture else {}
    for g in giocatori:
        o = odds_map.get(g['slug'])
        g['starter_odds'] = o

    if not odds_map:
        log(f"Odds della giornata non ancora uscite: analizzo TUTTO il pool "
            f"({len(giocatori)} candidati), nessun filtro odds.")
        pool['filtri'] = dict(pool.get('filtri') or {}, odds_min=None)
        return giocatori

    tenuti = [g for g in giocatori if (g.get('starter_odds') or 0) >= soglia]
    senza = sum(1 for g in giocatori if g.get('starter_odds') is None)
    log(f"Filtro starter odds >= {soglia:.0%}: {len(tenuti)}/{len(giocatori)} sopra soglia "
        f"({senza} senza odds pubblicate per la loro partita, esclusi).")
    pool['filtri'] = dict(pool.get('filtri') or {}, odds_min=soglia)
    return tenuti


# --- IL CAMPIONE -----------------------------------------------------------
#
# Prendere i migliori N per L10 e' l'errore che sembra ovvio e non lo e'.
# Sotto un cap la valuta NON e' il punteggio, e' il punteggio PER UNITA' DI L10
# (soglia misurata: 1.017 sotto cap 260, sez. dei numeri di riferimento). I top
# per L10 sono esattamente le carte che saturano il cap -- Messi, L10 88, si
# mangia un terzo di un cap 260 da solo. Chi riempie bene un cap 220/260 e'
# l'opposto: L10 basso e atteso alto. Ordinando per L10 quei candidati non
# entrano mai nel campione, per costruzione.
#
# Il problema e' che l'atteso lo sappiamo solo DOPO il predict, e il predict
# gira solo sul campione: circolarita'. Si rompe con un proxy calcolabile
# PRIMA, senza una query in piu':
#
#   - L5 sopra L10        chi rende sopra la propria media recente sta salendo,
#                         ed e' il caso in cui il modello supera l'L10;
#   - proiezione Sorare   una stima indipendente dalla nostra, gia' in tabella;
#   - L10 basso           sotto cap serve anche gente economica, punto.
#
# E si campiona a FASCE di L10 invece che a soglia unica: quattro fasce per
# quartili calcolati sul ruolo (misurati sul pool GW2: Q1 44, mediana 48, Q3 53
# -- una distribuzione stretta, dove bande fisse a occhio sarebbero sbagliate),
# N/4 per fascia. Cosi' il campione copre per costruzione sia i costosi per le
# arene uncapped sia gli economici per i cap, e non dipende da una sola metrica
# rumorosa: ordinare solo per efficienza premierebbe chi ha L10 minuscolo e una
# partita fortunata.
def _efficienza_attesa(g):
    """Quanto ci si aspetta che renda per unita' di L10, PRIMA del predict.

    Il numeratore e' la stima piu' ottimista fra quelle disponibili: e' un
    criterio di ORDINAMENTO dentro una fascia, non una previsione -- la
    previsione la fa il modello, dopo."""
    l10 = g.get('l10') or 0
    if l10 <= 0:
        return 0.0
    stima = max(l10, g.get('l5') or 0, g.get('proiezione_sorare') or 0)
    return stima / l10


def campiona(giocatori, per_ruolo, a_fasce=True):
    """Il campione da mandare al predict: per_ruolo candidati per ruolo.

    Con a_fasce (default) sono divisi in quattro fasce di L10 per quartili del
    ruolo, ordinati per efficienza attesa dentro ciascuna. Un giocatore con due
    ruoli entra se e' scelto in almeno uno."""
    tenuti = set()
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        righe = [g for g in giocatori if ruolo in g['ruoli'] and (g.get('l10') or 0) > 0]
        if not righe:
            continue
        if not a_fasce or len(righe) < 8:
            for g in sorted(righe, key=lambda x: -(x.get('l10') or 0))[:per_ruolo]:
                tenuti.add(g['slug'])
            continue
        valori = sorted(g['l10'] for g in righe)
        # Quartili a mano: nessuna dipendenza da statistics per un calcolo che
        # deve solo dividere in quattro gruppi di dimensione simile.
        tagli = [valori[int(len(valori) * q)] for q in (0.25, 0.50, 0.75)]

        def fascia(g):
            l10 = g['l10']
            return sum(1 for t in tagli if l10 >= t)

        quota_base, resto = divmod(per_ruolo, 4)
        scelti_ruolo = []
        for f in range(4):
            # Il resto va alle fasce ALTE: a parita' di tutto, un punto in piu'
            # vale piu' di uno sconto sul cap in un'arena uncapped.
            quota = quota_base + (1 if f >= 4 - resto else 0)
            if not quota:
                continue
            in_fascia = sorted((g for g in righe if fascia(g) == f),
                               key=lambda g: (-_efficienza_attesa(g), -(g.get('l10') or 0)))
            scelti_ruolo.extend(in_fascia[:quota])
        # Se una fascia era piu' vuota della sua quota, si completa con i
        # migliori rimasti invece di consegnare meno candidati del richiesto.
        if len(scelti_ruolo) < per_ruolo:
            gia = {g['slug'] for g in scelti_ruolo}
            avanzi = sorted((g for g in righe if g['slug'] not in gia),
                            key=lambda g: (-_efficienza_attesa(g), -(g.get('l10') or 0)))
            scelti_ruolo.extend(avanzi[:per_ruolo - len(scelti_ruolo)])
        tenuti.update(g['slug'] for g in scelti_ruolo)
        log(f"  {ruolo}: fasce L10 <{tagli[0]:.0f} / {tagli[0]:.0f}-{tagli[1]:.0f} / "
            f"{tagli[1]:.0f}-{tagli[2]:.0f} / >{tagli[2]:.0f}")

    scelti = [g for g in giocatori if g['slug'] in tenuti]
    log(f"Campione: {per_ruolo} per ruolo "
        f"({'a fasce di L10' if a_fasce else 'i migliori per L10'}) -> {len(scelti)} candidati")
    return scelti


# --- IL PONTE VERSO I PREDICT ---------------------------------------------
#
# I predict NON vanno modificati: ognuno legge la sua lista da
# `formazione_<lega>/output/<lega>_<ruolo>_discovery/player_slugs.json` (o un
# singolo giocatore da TARGET_SLUG). Basta scrivere quel file con i candidati
# dello scouting e la pipeline esistente gira su carte che l'utente NON ha,
# senza toccare una riga dei suoi 2.500.
#
# Va saputo che questo SOVRASCRIVE la discovery di produzione della lega: la
# prossima run di `formazione_giornata` la rigenera comunque (e' il primo job),
# ma nel frattempo un run manuale dei predict userebbe questa lista. Per questo
# il default e' un campione piccolo e una lega sola.
RUOLO_DIR = {'GK': 'gk', 'DEF': 'def', 'MID': 'mid', 'FWD': 'fwd'}


def scrivi_discovery(pool, leghe=None, limite_per_ruolo=None):
    """Scrive player_slugs.json per ogni (lega, ruolo) presente nel pool.

    Ritorna la lista di (cartella, ruolo, quanti) scritti, cosi' il workflow
    sa esattamente cosa lanciare."""
    per_gruppo = defaultdict(list)
    for g in sorted(pool['giocatori'], key=lambda x: -(x.get('l10') or 0)):
        cartella = g.get('cartella')
        if not cartella or (leghe and cartella not in leghe):
            continue
        for ruolo in g['ruoli']:
            per_gruppo[(cartella, ruolo)].append(g['slug'])

    scritti = []
    for (cartella, ruolo), slugs in sorted(per_gruppo.items()):
        if limite_per_ruolo:
            slugs = slugs[:limite_per_ruolo]
        # La MLS ha un solo predict per gli attaccanti (test_mls_fwd_all.py) ma
        # la cartella di discovery segue lo stesso schema degli altri ruoli.
        dest_dir = os.path.join(REPO_ROOT, f"formazione_{cartella}", 'output',
                                f"{cartella}_{RUOLO_DIR[ruolo]}_discovery")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, 'player_slugs.json')
        with open(dest, 'w', encoding='utf-8') as f:
            json.dump(slugs, f, ensure_ascii=False, indent=1)
        scritti.append((cartella, ruolo, len(slugs)))
        log(f"  discovery scritta: {os.path.relpath(dest, REPO_ROOT)} ({len(slugs)} slug)")

    # L'elenco di cosa e' stato scritto, cosi' il workflow sa quali predict
    # lanciare SENZA che nessuno debba elencare le leghe a mano (18 slug scritti
    # a mano sono 18 occasioni di sbagliarne uno, e uno slug sbagliato in questo
    # progetto non da' errore: da' zero risultati in silenzio).
    indice = os.path.join(REPO_ROOT, 'dati_globali', 'scouting_da_predire.tsv')
    os.makedirs(os.path.dirname(indice), exist_ok=True)
    with open(indice, 'w', encoding='utf-8') as f:
        for cartella, ruolo, quanti in scritti:
            f.write(f"{cartella}\t{RUOLO_DIR[ruolo]}\t{quanti}\n")
    log(f"Indice per i predict: {os.path.relpath(indice, REPO_ROOT)}")

    _scrivi_lavori(per_gruppo, limite_per_ruolo)
    return scritti


# Chi ha GIA' una previsione per QUESTA giornata non va ripredetto: non serve
# nemmeno il refresh leggero, perche' la previsione e' per definizione legata
# alla partita, e se la partita e' la stessa il numero non cambia.
#
# La regola non la scriviamo qui: e' `best_five._predizione_riutilizzabile`,
# che aggancia la validita' alla FINESTRA DELLA FIXTURE invece che a un tetto
# di ore -- una previsione vale se e solo se la partita che predice cade dentro
# la giornata corrente, quindi scade da sola quando la giornata chiude, senza
# che nessuna soglia debba indovinare quando.
#
# SPENTO DI DEFAULT PER LO SCOUTING (09/08/2026, richiesta esplicita
# dell'utente): finche' il grade G non e' innestato con sicurezza nello
# scouting, una previsione salvata prima potrebbe essere stata calcolata
# senza G o con un grade diverso e verrebbe riusata in silenzio. Questo NON
# tocca `best_five.RIUSA_PREDIZIONI` (che resta '1' per il generatore di
# formazioni): `bf` qui e' un'istanza fresca caricata da `_import`, spegnere
# il riuso qui non spegne nient'altro che importi best_five altrove.
SCOUTING_RIUSA_PREDIZIONI = os.environ.get(
    'SCOUTING_RIUSA_PREDIZIONI', '0').strip() not in ('0', 'false', 'no', '')


def _predizioni_gia_fatte(coppie):
    """(da_fare, gia_fatte) sulla lista di (lega, ruolo_dir, slug)."""
    try:
        bf = _import('scouting_best_five_pred', 'best_five.py')
    except Exception as e:
        log(f"ATTENZIONE: riuso predizioni non disponibile ({e}), le rifaccio tutte.")
        return list(coppie), []
    da_fare, gia = [], []
    n_riusabili = 0
    for lega, ruolo, slug in coppie:
        try:
            riusabile, _kickoff, _path = bf._predizione_riutilizzabile(lega, ruolo, slug)
        except Exception:
            riusabile = False
        if riusabile:
            n_riusabili += 1
        (gia if (riusabile and SCOUTING_RIUSA_PREDIZIONI) else da_fare).append(
            (lega, ruolo, slug))
    if SCOUTING_RIUSA_PREDIZIONI:
        log(f"[riuso] ACCESO (SCOUTING_RIUSA_PREDIZIONI=1): {n_riusabili}/{len(coppie)} "
            f"previsioni riusate da disco.")
    else:
        log(f"[riuso] SPENTO per lo scouting (default, SCOUTING_RIUSA_PREDIZIONI=0): "
            f"{n_riusabili}/{len(coppie)} previsioni erano riusabili ma vengono "
            f"RIFATTE per questo motivo.")
    return da_fare, gia


def _scrivi_lavori(per_gruppo, limite_per_ruolo):
    """L'elenco `lega|ruolo|slug` dei predict che servono DAVVERO.

    Lo legge il workflow per costruire la matrice: chi ha gia' la previsione
    di questa giornata non genera nemmeno il job."""
    coppie = []
    for (cartella, ruolo), slugs in sorted(per_gruppo.items()):
        for slug in (slugs[:limite_per_ruolo] if limite_per_ruolo else slugs):
            coppie.append((cartella, RUOLO_DIR[ruolo], slug))
    da_fare, gia = _predizioni_gia_fatte(coppie)
    dest = os.path.join(REPO_ROOT, 'dati_globali', 'scouting_lavori.txt')
    with open(dest, 'w', encoding='utf-8') as f:
        for lega, ruolo, slug in da_fare:
            f.write(f"{lega}|{ruolo}|{slug}\n")
    log(f"Predict da fare: {len(da_fare)}/{len(coppie)} "
        f"({len(gia)} hanno gia' la previsione di questa giornata, saltati).")
    return da_fare


# --- LE FORMAZIONI IPOTETICHE ---------------------------------------------
#
# "Se comprassi questi, che arena ci farei?" Non si costruisce niente a mano:
# si chiama la STESSA generate_lineups_for_type della produzione, con i tipi
# arena veri (ARENA_ALLSTARS_260 / _220 / _UNCAPPED), esattamente come fa
# best_five.costruisci_formazione_contender per il pool multi-lega. Cap L10,
# anti-stack, sinergie e capitano arrivano dai dizionari di quel modulo: se
# domani cambiano in produzione, cambiano anche qui.
#
# DUE COSE CHE QUESTE FORMAZIONI NON SANNO, e vanno lette sapendolo:
#   1. assumono che i candidati GIOCHINO. Senza odds (che escono a 24-48h dal
#      kickoff) la titolarita' e' una scommessa: qui c'e' solo il filtro
#      `playing_status` di Sorare e, se richiesto, il controllo 2-su-3. Con le
#      odds pubblicate lo stesso codice diventa molto piu' affidabile.
#   2. sono carte che NON POSSIEDI. E' una simulazione d'acquisto, non una
#      formazione schierabile.
TIPI_ARENA = ('ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED')

# Quante arene al massimo provare a comporre. Non e' un obiettivo: il motore si
# ferma da solo quando la prossima non renderebbe piu' essenze.
# Tetto pratico, non un obiettivo: il motore si ferma da solo quando la
# prossima arena non renderebbe piu' essenze. 20 e' lo stesso tetto per tipo
# che usa il generatore (HARD_CAP_BY_TYPE).
MAX_ARENE = int(os.environ.get('SCOUTING_MAX_ARENE', '20'))

# Scegliere le arene per ESSENZE PER EURO invece che per essenze: e' la
# domanda di chi compra. Acceso di default qui, inesistente nel generatore.
PER_EURO = os.environ.get('SCOUTING_ARENE_PER_EURO', '1').strip() not in ('0', 'false', 'no', '')

# Quanto si assume che costi una carta di cui non conosciamo il prezzo. Alto
# apposta: e' l'unico modo di non far vincere le formazioni piene di incognite.
PREZZO_IGNOTO = float(os.environ.get('SCOUTING_PREZZO_IGNOTO', '25'))

# Quanto allargare il campione PRIMA di chiedere le odds: il filtro scarta, e
# senza margine resterebbero meno candidati di quanti richiesti.
MARGINE_ODDS = int(os.environ.get('SCOUTING_MARGINE_ODDS', '3'))


def componi_arene(pool, tipi=TIPI_ARENA, massimo=None):
    """Le arene che converrebbe giocare coi soli candidati del pool.

    Ritorna [(etichetta, blocco_testo)]. Lista vuota se i consigli non ci sono
    ancora: senza punteggio atteso non si compone niente, e inventarlo sarebbe
    peggio che non mostrare la sezione."""
    try:
        bf = _import('scouting_best_five', 'best_five.py')
        gg = bf._import_gg()
        bff = gg.bff
    except Exception as e:
        log(f"ATTENZIONE: motore formazioni non caricabile ({e}), sezione arene saltata.")
        return []

    massimo = MAX_ARENE if massimo is None else massimo
    candidati = {g['slug'] for g in pool['giocatori']}
    l10_per_slug = {g['slug']: g.get('l10') for g in pool['giocatori']}
    gruppi = {(g['cartella'], r) for g in pool['giocatori'] if g.get('cartella') for r in g['ruoli']}

    # Le righe vanno tenute PER LEGA, non in un unico contenitore: le arene All
    # Stars hanno pool_league 'mixed', e `_view_for` costruisce quel pool
    # unendo pools[lg] per ogni lg in gg.LEAGUES. Una chiave inventata (il
    # primo tentativo usava 'scouting') non verrebbe mai letta: zero
    # formazioni sempre, senza errore, qualunque cosa ci sia nei consigli.
    per_lega = {lega: {ROLE: [] for ROLE in gg.ROLES} for lega in gg.LEAGUES}
    merged = {ROLE: [] for ROLE in gg.ROLES}
    for cartella, ROLE in sorted(gruppi):
        out_dir = bf.output_dir_per_ruolo(cartella, RUOLO_DIR[ROLE])
        path = bff.latest_consiglio(out_dir)
        if not path:
            continue
        try:
            # ROLE va passato (03/08): dal 03/08 la retta di calibrazione e'
            # diversa per ruolo (CALIB_PER_RUOLO nel generatore), perche'
            # quella unica appiattiva tre punti fra portieri e attaccanti.
            # Senza il ruolo lo scouting ricadeva sulla retta media, e avrebbe
            # dato allo stesso giocatore un punteggio DIVERSO da quello del
            # generatore: comprato su un numero, schierato su un altro.
            righe = bf._parse_consiglio_calibrato(bff, gg, path, ROLE)
        except Exception as e:
            log(f"ATTENZIONE: consiglio {os.path.basename(path)} non leggibile ({e}).")
            continue
        # SOLO i candidati di questo scouting: quei consigli contengono anche
        # i giocatori gia' posseduti, che qui non c'entrano -- la domanda e'
        # cosa comprare, non cosa schierare.
        righe = [r for r in righe if r.get('slug') in candidati]
        for r in righe:
            r['league'] = cartella
        merged[ROLE].extend(righe)
        if cartella in per_lega:
            per_lega[cartella][ROLE].extend(righe)
        else:
            log(f"ATTENZIONE: lega '{cartella}' non fra quelle note al generatore "
                f"({len(gg.LEAGUES)}): i suoi {len(righe)} candidati non entreranno "
                f"nelle arene.")

    if not any(merged.values()):
        log("Nessun consiglio utilizzabile: sezione formazioni saltata.")
        return []

    role_data = {lega: dati for lega, dati in per_lega.items()}
    pools = {lega: {role: gg._NoFilterPool(role, lega, dati[role]) for role in gg.ROLES}
             for lega, dati in per_lega.items()}
    # L10 vero nella CardPool: senza, il cap 260/220 non morde e le tre
    # formazioni verrebbero identiche (stesso inciampo documentato in
    # best_five, RISPETTA_CAP_L10). Le carte sono classic: in arena si gioca
    # con quelle.
    counts = {ROLE: {r['slug']: {'in_season': 0, 'classic': 1,
                                 'l10': l10_per_slug.get(r['slug'])}
                     for r in righe}
              for ROLE, righe in merged.items()}
    card_pool = bff.CardPool(counts)
    prezzi_per_slug = {g['slug']: g.get('prezzo_eur') for g in pool['giocatori']}

    # genera_arene_efficienti, non un ciclo di generate_lineups_for_type per
    # tipo: e' la funzione che la produzione usa dal 02/08 (sez. 53). Sceglie
    # da sola TIPO e NUMERO massimizzando le ESSENZE invece dei punti --
    # provando a ogni passo tutti i tipi e tenendo il migliore, e fermandosi
    # quando nessuno rende piu'. Sullo stesso mazzo valeva +20% di essenze
    # contro il mix deciso a mano, e le uncapped venivano scartate da sole
    # perche' restavano sotto la loro soglia di 288.2.
    #
    # Qui conta doppio: un pool di ACQUISTI ha senso solo se si vede in quale
    # arena quelle carte renderebbero, e con che margine sopra il pareggio.
    if PER_EURO:
        risultati = _arene_per_euro(gg, list(tipi), massimo, role_data, pools,
                                    card_pool, prezzi_per_slug)
        return _confeziona(gg, bf, bff, risultati, card_pool, pool)

    if not hasattr(gg, 'genera_arene_efficienti'):
        log("ATTENZIONE: genera_arene_efficienti non disponibile in questo "
            "generatore -- sezione arene saltata invece di usare un motore "
            "diverso da quello di produzione.")
        return []
    try:
        risultati = gg.genera_arene_efficienti(list(tipi), massimo, role_data, pools, card_pool)
    except Exception as e:
        log(f"ATTENZIONE: arene non generate ({e}).")
        return []
    if not risultati:
        log("Nessuna arena conviene con questi candidati: nessuna formazione "
            "arriva sopra la propria soglia di pareggio.")
        return []
    # Servono i blocchi HTML, non solo il testo: sono le stesse card del
    # generatore (.pcard con data-slug), e su quelle best_five sa gia'
    # annotare prezzo per carta e totale di formazione.
    return _confeziona(gg, bf, bff, risultati, card_pool, pool)


# L'ottimizzatore per EURO vive SOLO qui, e non nel generatore: li' le carte
# l'utente le possiede gia', il prezzo non esiste come vincolo e aggiungerlo
# sarebbe un peso inutile su un motore condiviso con la produzione.
#
# La differenza rispetto a `genera_arene_efficienti`: quella e' avida sulle
# ESSENZE, quindi prende volentieri una carta da 30 EUR per due punti in piu'.
# Qui l'avidita' e' sulle ESSENZE PER EURO, che e' la domanda di chi deve
# COMPRARE -- e sui dati del 02/08 la differenza si vedeva a occhio: la prima
# formazione rendeva 240 essenze costando 6.87 EUR, la terza 173 costandone
# 41.67.
#
# Il resto e' identico e riusa le primitive del generatore: stessa
# generate_lineups_for_type, stesse istantanee del pool per provare un tipo e
# disfare la prova, stesse soglie di pareggio e guadagno per punto.
def _arene_per_euro(gg, tipi, massimo, role_data, pools, card_pool, prezzi_per_slug):
    scelte = []
    for _ in range(max(0, massimo)):
        migliore = None
        for tipo in tipi:
            soglia = getattr(gg, 'PAREGGIO_ARENA', {}).get(tipo)
            if soglia is None:
                continue
            stato = gg._istantanea_pool(card_pool)
            try:
                prova = gg.generate_lineups_for_type(tipo, 1, role_data, pools, card_pool)
            except Exception:
                prova = []
            gg._ripristina_pool(card_pool, stato)
            valide = [r for r in prova if 'error' not in r]
            if not valide:
                continue
            atteso = gg._atteso_con_capitano(valide[0])
            essenze = (atteso - soglia) * getattr(gg, 'GUADAGNO_PER_PUNTO', {}).get(tipo, 7.9)  # B05
            if essenze <= 0:
                continue
            costo = 0.0
            for _slot, riga, _c in valide[0].get('formazione') or []:
                prezzo = prezzi_per_slug.get(riga.get('slug'))
                # Prezzo ignoto: si assume che costi, e parecchio. Trattarlo
                # come gratis farebbe vincere le formazioni piene di carte di
                # cui non sappiamo niente.
                costo += PREZZO_IGNOTO if prezzo is None else prezzo
            # +1 EUR al denominatore: senza, una formazione di sole carte
            # gia' possedute (costo 0) avrebbe resa infinita e vincerebbe
            # sempre, a prescindere da quanto rende davvero.
            resa = essenze / (costo + 1.0)
            if migliore is None or resa > migliore[0]:
                migliore = (resa, tipo, atteso, essenze, costo)
        if migliore is None:
            break
        resa, tipo, atteso, essenze, costo = migliore
        vera = gg.generate_lineups_for_type(tipo, 1, role_data, pools, card_pool)
        for r in vera:
            if 'error' not in r:
                scelte.append(r)
        log(f"  arena #{len(scelte)} per euro: {getattr(gg,'LABELS',{}).get(tipo,tipo)} "
            f"-- atteso {atteso:.1f}, {essenze:.0f} essenze, {costo:.2f} EUR "
            f"-> {resa:.0f} essenze/EUR")
    return scelte


def _confeziona(gg, bf, bff, risultati, card_pool, pool):
    """Dai risultati grezzi del motore ai conti pronti per il report."""
    if not risultati:
        log("Nessuna arena conviene con questi candidati: nessuna formazione "
            "arriva sopra la propria soglia di pareggio.")
        return []
    prezzi_per_slug = {g['slug']: g.get('prezzo_eur') for g in pool['giocatori']}
    _gen, _tot, blocchi, blocchi_html = bf._renderizza_risultati(bff, risultati, card_pool)
    formazioni = []
    for risultato, blocco, blocco_html in zip(risultati, blocchi, blocchi_html):
        conto = _conto_arena(gg, risultato, prezzi_per_slug)
        conto['blocco'] = blocco
        conto['blocco_html'] = blocco_html
        formazioni.append(conto)

    # Ordine per RESA PER EURO, non per essenze assolute. Un'arena da 5 euro con
    # +30 sopra soglia batte una da 15 con +35: rende meno in assoluto ma molto
    # di piu' per euro investito, e le carte comprate restano comunque tue.
    # Chi non ha un prezzo completo finisce in fondo: e' un conto incompleto,
    # non un buon affare da nascondere in cima.
    formazioni.sort(key=lambda c: -(c['essenze_per_euro'] if c['essenze_per_euro'] is not None else -1))
    log(f"  arene efficienti: {len(formazioni)} formazioni scelte dal motore.")
    for c in formazioni:
        log(f"    {c['etichetta_breve']}: atteso {c['atteso']:.1f} "
            f"(margine {c['margine']:+.1f}), {c['essenze']:+.0f} essenze, "
            f"costo {'n/d' if c['costo'] is None else format(c['costo'], '.2f') + ' EUR'}"
            + ('' if c['essenze_per_euro'] is None
               else f", {c['essenze_per_euro']:.0f} essenze/EUR"))
    return formazioni


def _conto_arena(gg, risultato, prezzi_per_slug):
    """Costo, margine sopra il pareggio e resa per euro di una formazione.

    Soglie, guadagno per punto, costo d'ingresso e verdetto arrivano TUTTI dal
    generatore (PAREGGIO_ARENA, GUADAGNO_PER_PUNTO, COSTO_INGRESSO,
    _etichetta_arena): sono misurati su 673 arene reali e vivono in un posto
    solo. Qui si aggiunge la sola cosa che il generatore non ha motivo di
    sapere -- il PREZZO IN EURO delle carte, perche' lui gioca con carte che
    l'utente possiede gia' e per lui l'acquisto non esiste."""
    tipo = risultato.get('tipo') or ''
    soglia = getattr(gg, 'PAREGGIO_ARENA', {}).get(tipo)
    try:
        atteso = gg._atteso_con_capitano(risultato)
    except Exception:
        atteso = sum(row.get('atteso', 0) for _s, row, _c in risultato.get('formazione') or [])
    margine = (atteso - soglia) if soglia is not None else None
    per_punto = getattr(gg, 'GUADAGNO_PER_PUNTO', {}).get(tipo, 7.9)  # B05
    # Guadagno NETTO sopra l'ingresso: il pareggio e' per definizione il punto
    # in cui il premio atteso copre le essenze spese per entrare.
    essenze = margine * per_punto if margine is not None else None
    ingresso = getattr(gg, 'COSTO_INGRESSO', {}).get(tipo, 300)
    try:
        verdetto, colore = gg._etichetta_arena(tipo, atteso)
    except Exception:
        verdetto, colore = None, None

    slug_schierati = [row.get('slug') for _s, row, _c in risultato.get('formazione') or []]
    prezzi = [prezzi_per_slug.get(s) for s in slug_schierati]
    noti = [p for p in prezzi if p is not None]
    # Il costo si dichiara solo se si conoscono TUTTI i prezzi: sommare quelli
    # che ci sono darebbe un totale piu' basso del vero, cioe' un affare
    # migliore di quello che e'.
    costo = round(sum(noti), 2) if len(noti) == len(prezzi) and prezzi else None
    senza_prezzo = len(prezzi) - len(noti)
    essenze_per_euro = (essenze / costo) if (essenze and costo and costo > 0) else None

    etichetta = getattr(gg, 'LABELS', {}).get(tipo, tipo or 'Arena')
    return {
        'tipo': tipo, 'etichetta_breve': etichetta, 'soglia': soglia,
        'atteso': atteso, 'margine': margine, 'essenze': essenze,
        'ingresso': ingresso, 'verdetto': verdetto, 'colore': colore,
        'costo': costo, 'senza_prezzo': senza_prezzo,
        'essenze_per_euro': essenze_per_euro,
        'carte': slug_schierati,
    }


# --- IL REPORT ------------------------------------------------------------
_HTML_TESTA = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scouting %(fixture)s</title><style>
:root{color-scheme:dark}
body{background:#12141a;color:#e6e8ee;font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:16px}
h1{font-size:18px;margin:0 0 4px} h2{font-size:15px;margin:22px 0 8px;color:#8ab4ff}
.meta{color:#9aa0ad;font-size:12px;margin-bottom:8px}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%%;min-width:640px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #232733;white-space:nowrap}
th{position:sticky;top:0;background:#1a1d26;color:#9aa0ad;font-weight:600;font-size:12px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr:nth-child(even){background:#161922}
.mia{color:#7ee787} .ko{color:#ff7b72} .warn{color:#ffa657} .muted{color:#6e7481}
a{color:inherit;text-decoration:none;border-bottom:1px dotted #4a5164}
a:hover{color:#8ab4ff}
.btn-scelta{background:#1a1d26;color:#9aa0ad;border:1px solid #2a2f3d;border-radius:4px;
  padding:4px 10px;font-size:12px;cursor:pointer}
.btn-scelta:hover{border-color:#4a5164;color:#e6e8ee}
.btn-scelta.attivo{background:#2a3550;color:#8ab4ff;border-color:#8ab4ff}
</style></head><body>
<h1>Scouting -- %(fixture)s</h1>
<div class="meta">%(quando)s &middot; %(n)d candidati &middot; %(filtri)s</div>
<div class="meta">Prezzo = carta piu' economica di QUALUNQUE rarita' e stagione (non per forza
una classic limited). Proj = proiezione di Sorare. L10 = media ultime 10 giocate.
Atteso = il nostro modello, gia' calibrato su scala reale.</div>
"""

# Ordinamento cliccando l'intestazione. Nessuna libreria: si riordinano i <tr>
# gia' presenti. I numeri si leggono dal testo ripulito da tutto quello che
# numero non e' (euro, percentuali, segni, spazi unificatori), cosi' "+148",
# "12.94 EUR" e "80%" si confrontano come numeri e non come stringhe -- con
# l'ordinamento alfabetico "9" verrebbe dopo "80".
_HTML_ORDINAMENTO = """
<script>
(function () {
  var tab = document.getElementById('candidati');
  if (!tab) return;
  var intestazioni = tab.querySelectorAll('tr:first-child th');
  intestazioni.forEach(function (th, colonna) {
    th.style.cursor = 'pointer';
    th.title = (th.title ? th.title + ' -- ' : '') + 'clicca per ordinare';
    th.addEventListener('click', function () {
      var righe = Array.prototype.slice.call(tab.querySelectorAll('tr')).slice(1);
      var discendente = th.dataset.ordine !== 'desc';
      intestazioni.forEach(function (altra) {
        delete altra.dataset.ordine;
        altra.textContent = altra.textContent.replace(/ [\\u25b2\\u25bc]$/, '');
      });
      th.dataset.ordine = discendente ? 'desc' : 'asc';
      th.textContent = th.textContent + (discendente ? ' \\u25bc' : ' \\u25b2');
      var numero = function (cella) {
        var t = (cella.textContent || '').replace(/\\u00a0/g, ' ')
                 .replace(/[^0-9,.\\-+]/g, '').replace(',', '.');
        var v = parseFloat(t);
        return isNaN(v) ? null : v;
      };
      righe.sort(function (a, b) {
        var ca = a.cells[colonna], cb = b.cells[colonna];
        if (!ca || !cb) return 0;
        var na = numero(ca), nb = numero(cb);
        // Colonne di TESTO (Giocatore, Ruolo, Club, Avversario, Lega, Note):
        // si ordinano alfabeticamente. Prima non funzionavano perche' il
        // confronto era solo numerico e ogni cella valeva "null", quindi
        // finivano tutte in fondo e l'ordine non cambiava mai.
        if (na === null && nb === null) {
          var ta = (ca.textContent || '').trim(), tb = (cb.textContent || '').trim();
          if (!ta && !tb) return 0;
          if (!ta) return 1;
          if (!tb) return -1;
          var cmp = ta.localeCompare(tb, 'it', { sensitivity: 'base' });
          return discendente ? -cmp : cmp;
        }
        // Miste: la cella senza valore sta SEMPRE in fondo, in entrambi i
        // versi -- altrimenti ordinando per prezzo crescente vincerebbero le
        // carte di cui non sappiamo il prezzo.
        if (na === null) return 1;
        if (nb === null) return -1;
        return discendente ? nb - na : na - nb;
      });
      righe.forEach(function (r) { tab.appendChild(r); });
    });
  });
})();
</script>
"""

_HTML_CODA = _HTML_ORDINAMENTO + "</body></html>"


def _atteso_dai_consigli(pool, gg=None):
    """L'atteso di ogni candidato, letto dalle PREDIZIONI GREZZE
    (prediction_<slug>_*.txt), non dai consigli aggregati.

    Il consiglio e' una lista TRONCATA per lega/ruolo: i candidati sotto la sua
    soglia restavano senza Atteso pur AVENDO la predizione (run 30835805352:
    79/196 candidati con predizione ma fuori dal consiglio). Qui ogni candidato
    del pool che ha una predizione per QUESTA giornata prende il suo numero,
    direttamente dal file di predizione.

    Per ogni slug si tiene l'ULTIMA predizione (timestamp nel nome, non mtime:
    git checkout in CI lo riscrive). Il KICKOFF (riga 'Data:') dev'essere nella
    finestra della fixture: una predizione vecchia punta a un'altra partita.
    Predict non ancora lanciato = colonna vuota, nessun numero inventato.

    CALIBRAZIONE (B01, P2 passaggio 2): il valore scritto nel file e' quello
    GREZZO di score_atteso (vedi test_{gk,def,mid,fwd}.py, riga "N) slug: X pt
    attesi") -- il commento che diceva "gia' calibrato su scala reale" era
    falso, il generatore calibra SOLO quando legge il consiglio aggregato via
    calibra_riga/_parse_consiglio_calibrato, non quando scrive il file. Qui si
    applica la STESSA calibrazione (gg.calibra, CALIB_PER_RUOLO) prima di
    restituire il valore, cosi' la tabella confronta ruoli sulla stessa scala
    del generatore -- se gg non e' disponibile si ricade sul grezzo
    (comportamento INVARIATO, nessuna regressione per chi non ha il generatore).

    Ritorna (per_slug, ambigui) -- 'ambigui' e' l'insieme degli slug il cui
    file predizione porta 'AMBIGUO_FIXTURE: si' (10/08/2026, caso Matt Freese:
    due partite future con odds pubblicate insieme -- vedi _prossima_partita_
    vera in test_gk.py e affini). Informativo, non filtra nulla da solo."""
    ruolo_per_slug = {}
    avversario_per_slug = {}
    for g in pool['giocatori']:
        if g.get('slug') and g.get('ruoli'):
            ruolo_per_slug[g['slug']] = g['ruoli'][0]
        if g.get('slug') and g.get('avversario'):
            avversario_per_slug[g['slug']] = g['avversario']
    inizio = (pool['fixture'].get('startDate') or '')[:10]
    fine = (pool['fixture'].get('endDate') or '')[:10]
    slugs_pool = {g['slug'] for g in pool['giocatori'] if g.get('slug')}
    cartelle = {g.get('cartella') for g in pool['giocatori'] if g.get('cartella')}
    _re_nome = re.compile(r'prediction_(.+)_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})\.txt$')
    ultimo = {}   # slug -> (timestamp, path)
    for cartella in sorted(cartelle):
        for path in glob.glob(os.path.join(REPO_ROOT, f"formazione_{cartella}",
                                           'output', '**', 'prediction_*.txt'),
                              recursive=True):
            m = _re_nome.search(os.path.basename(path))
            if not m:
                continue
            slug, ts = m.group(1), m.groups()[1:]
            if slug not in slugs_pool:
                continue
            if slug not in ultimo or ts > ultimo[slug][0]:
                ultimo[slug] = (ts, path)
    per_slug, ambigui, fuori_giornata = {}, set(), 0
    for slug, (_ts, path) in ultimo.items():
        try:
            with open(path, encoding='utf-8') as f:
                testo = f.read()
        except OSError:
            continue
        mk = re.search(r'^Data:\s*(\d{4}-\d{2}-\d{2})', testo, re.M)
        if mk and inizio and fine and not (inizio <= mk.group(1) <= fine):
            fuori_giornata += 1
            continue
        # Riga d'intestazione: "1) <slug>: 52 pt attesi (37-68)". Il "pt" e' gia'
        # calibrato su scala reale.
        ms = re.search(r'^\s*\d+\)\s*' + re.escape(slug) +
                       r':\s*([0-9]+(?:\.[0-9]+)?)\s*pt', testo, re.M)
        if ms:
            per_slug[slug] = float(ms.group(1))
            if re.search(r'^\s*AMBIGUO_FIXTURE:\s*si\s*$', testo, re.M):
                ambigui.add(slug)
    if fuori_giornata:
        log(f"Attesi: {fuori_giornata} predizioni con kickoff fuori da "
            f"{inizio}..{fine} (altre giornate, scartate).")
    if ambigui:
        log(f"AVVISO: {len(ambigui)} candidati con fixture ambigua (due GW con odds "
            f"pubblicate insieme, vedi HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §10bis): "
            f"{', '.join(sorted(ambigui))}")
    if gg is not None and hasattr(gg, 'calibra'):
        per_slug = {slug: gg.calibra(v, ruolo_per_slug.get(slug)) if v is not None else v
                    for slug, v in per_slug.items()}
        # GK_ATT_AVV (11/08/2026): stesso correttivo del generatore
        # (build_formazione_globale._apply_gk_att_avv, GK_ATT_AVV_ENABLED/
        # _FORMULA). Questa funzione legge le predizioni grezze per un
        # percorso SEPARATO dal generatore: senza questo, a flag acceso, un
        # portiere avrebbe un atteso diverso fra generatore e scouting
        # (fino a ~6-7 punti, segnalato da Opus -- catena
        # produzione->soglie->scouting, CLAUDE.md). Rispetta lo stesso
        # flag/formula: a GK_ATT_AVV_ENABLED spento l'aggiustamento e'
        # sempre 0.0, nessun cambiamento per chi non ha il generatore.
        if hasattr(gg, 'gk_att_avv_aggiustamento') and getattr(gg, 'GK_ATT_AVV_ENABLED', False):
            per_slug = {
                slug: (round(v + gg.gk_att_avv_aggiustamento(avversario_per_slug.get(slug)), 1)
                       if v is not None and ruolo_per_slug.get(slug) == 'GK' else v)
                for slug, v in per_slug.items()}
    return per_slug, ambigui


def _script_delle_carte(bf):
    """Gli <script> del template del generatore.

    Servono, e non sono un di piu': il markup di una .pcard tiene il contenuto
    in `data-body` HTML-escapato, ed e' UNO SCRIPT a disegnarlo. Copiando il
    solo <style> le carte restano vuote e il testo si impila in colonna --
    successo il 02/08: markup identico a quello del generatore, CSS corretto,
    e a schermo una sfilza di righe illeggibili."""
    try:
        template = bf._import_gg().bff.HTML_REPORT_TEMPLATE
        script = ''.join(re.findall(r'<script>.*?</script>', template, re.S))
        return script.replace('{{', '{').replace('}}', '}')
    except Exception:
        return ''


def _prezzi_sulle_carte(prezzi_per_slug):
    """Prezzo su ogni carta e totale della formazione, in euro.

    Non si riusa `best_five._annota_prezzi_html` perche' quello somma i prezzi
    IN SEASON, e qui le carte sono tutte CLASSIC: il totale usciva sempre 0
    (segnalato dall'utente il 02/08)."""
    payload = json.dumps({k: v for k, v in prezzi_per_slug.items() if v is not None})
    return """
<script>
(function () {
  var prezzi = %s;
  document.querySelectorAll('.lineup-block').forEach(function (blocco) {
    var totale = 0, noti = 0, mancanti = 0;
    blocco.querySelectorAll('.pcard[data-slug]').forEach(function (card) {
      var p = prezzi[card.dataset.slug];
      var riga = document.createElement('div');
      riga.style.cssText = 'text-align:center;font-size:11px;padding:2px 0;font-weight:600';
      if (p == null) { riga.textContent = 'prezzo n/d'; riga.style.color = '#8fa199'; mancanti++; }
      else { riga.textContent = p.toFixed(2) + ' EUR'; riga.style.color = '#7ee787'; totale += p; noti++; }
      card.appendChild(riga);
    });
    if (noti) {
      var tot = document.createElement('div');
      tot.style.cssText = 'margin:6px 0 2px;font-size:13px;font-weight:700;color:#e8b84b';
      tot.textContent = 'Costo formazione: ' + totale.toFixed(2) + ' EUR'
                      + (mancanti ? ' (+' + mancanti + ' senza prezzo)' : '');
      blocco.appendChild(tot);
    }
  });
})();
</script>
""" % payload


def _css_delle_carte(bf):
    """Il foglio di stile delle .pcard, preso dal template del generatore.

    Estratto da HTML_REPORT_TEMPLATE invece di ricopiato: se domani cambia il
    look delle carte in produzione, cambia anche qui. Se il template non fosse
    piu' in quella forma si torna a stringa vuota -- le formazioni restano
    leggibili, perdono solo la grafica."""
    try:
        template = bf._import_gg().bff.HTML_REPORT_TEMPLATE
        m = re.search(r'<style>.*?</style>', template, re.S)
        if not m:
            return ''
        # HTML_REPORT_TEMPLATE e' una stringa da passare a .format(), quindi le
        # graffe letterali del CSS sono RADDOPPIATE. Estraendola grezza il
        # browser riceve `.pcard {{ ... }}`, che non e' CSS valido: lo ignora in
        # silenzio e le formazioni appaiono vuote (successo il 02/08 -- le card
        # c'erano tutte nel sorgente, 476 nodi, ma non si vedeva niente).
        return m.group(0).replace('{{', '{').replace('}}', '}')
    except Exception:
        return ''


def _escape(testo):
    return (testo.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _atteso_combinato_per_gruppo(pool, attesi, gg):
    """atteso_combinato = atteso + sd_gruppo * z_grade, la STESSA formula gia'
    validata in produzione (generatore, build_formazione_globale._apply_grade_
    group -- vedi HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §8bis), non
    reinventata qui: gruppo = (lega, ruolo primario), come nel generatore.
    sd_gruppo e' la dispersione degli ATTESI dentro il gruppo (non del
    grade); z_grade e' lo z-score del grade numerico (A=6..F=1) dentro lo
    stesso gruppo. Con meno di 2 atteso o 2 grade nel gruppo, fallback allo
    stesso identico atteso (z=0), mai un numero inventato.
    Ritorna {slug: atteso_combinato} SOLO per chi ha un atteso.

    ORDINE (13/08/2026): il correttivo GK_ATT_AVV e' gia' dentro `attesi`
    (lo applica _atteso_dai_consigli, per allineare la colonna Atteso al
    generatore), ma nel generatore l'effetto del grade si calcola PRIMA del
    correttivo -- load_league_role_data chiama _apply_grade_group e SOLO
    DOPO _apply_gk_att_avv, che sovrascrive 'atteso' senza ritoccare
    'atteso_combinato'. Calcolando il grade sugli attesi gia' corretti si
    gonfia la dispersione del gruppo portieri, e il voto pesa ~il doppio:
    l'atteso GK di produzione e' quasi piatto (sd 0,97 sulle 1.932 righe
    citate in build_formazione_globale) mentre il correttivo ha sd 1,73 e
    range -6,7/+6,0 sulle 741 squadre in tabella. Quindi qui si SCALA il
    correttivo prima di misurare il gruppo e lo si risomma alla fine,
    esattamente come fa il generatore. (Lo scarto di arrotondamento e'
    <=0,05 pt: _atteso_dai_consigli arrotonda a un decimale dopo la somma.)"""
    grade_num = getattr(gg, 'GRADE_NUM', None) or {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
    gruppi = defaultdict(list)
    for g in pool['giocatori']:
        if attesi.get(g['slug']) is None or not g.get('ruoli'):
            continue
        gruppi[(g.get('lega'), g['ruoli'][0])].append(g)

    # Il correttivo GK per slug, ricalcolato con lo stesso helper del
    # generatore (a flag spento resta vuoto: nessuna riga cambia).
    gk_adj = {}
    if (gg is not None and getattr(gg, 'GK_ATT_AVV_ENABLED', False)
            and hasattr(gg, 'gk_att_avv_aggiustamento')):
        for g in pool['giocatori']:
            if (g.get('ruoli') and g['ruoli'][0] == 'GK'
                    and attesi.get(g['slug']) is not None):
                gk_adj[g['slug']] = gg.gk_att_avv_aggiustamento(g.get('avversario'))

    combinato = {}
    for righe in gruppi.values():
        vals = [attesi[r['slug']] - gk_adj.get(r['slug'], 0.0) for r in righe]
        m = sum(vals) / len(vals)
        sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 if len(vals) >= 2 else 0.0
        grade_members = [grade_num[r['grade']] for r in righe if r.get('grade') in grade_num]
        if len(grade_members) >= 2:
            gm = sum(grade_members) / len(grade_members)
            gsd = (sum((v - gm) ** 2 for v in grade_members) / len(grade_members)) ** 0.5
        else:
            gm, gsd = 0.0, 0.0
        for r in righe:
            gn = grade_num.get(r.get('grade'))
            z = (gn - gm) / gsd if (gn is not None and gsd > 0) else 0.0
            base = attesi[r['slug']] - gk_adj.get(r['slug'], 0.0)
            combinato[r['slug']] = base + sd * z + gk_adj.get(r['slug'], 0.0)
    return combinato


# Filtro ruolo (bottoni "Mostra solo") + Best Five/Best per ruolo, tutto su
# data-* nelle righe (mai testo da riparsare -- l'unico script che parsava il
# testo delle celle e' quello di ordinamento generico, invariato). Standalone,
# incluso solo dentro la tabella minimale.
_HTML_CONTROLLI_MINIMALE = """
<script>
(function () {
  var tab = document.getElementById('candidati');
  if (!tab) return;
  var righe = function () { return Array.prototype.slice.call(tab.querySelectorAll('tr')).slice(1); };

  function numAttr(tr, nome) {
    var v = tr.getAttribute(nome);
    if (v === null || v === '') return null;
    var n = parseFloat(v);
    return isNaN(n) ? null : n;
  }
  function ruoliDi(tr) {
    return (tr.getAttribute('data-ruoli') || '').split(',').filter(Boolean);
  }
  function rapporto(tr) {
    var prezzo = numAttr(tr, 'data-prezzo');
    var punteggio = numAttr(tr, 'data-ag');
    if (punteggio === null) punteggio = numAttr(tr, 'data-atteso');
    if (prezzo === null || punteggio === null || prezzo <= 0 || punteggio <= 0) return null;
    return prezzo / punteggio;
  }

  // --- Vista attiva: 'TUTTI' | 'GK' | 'DEF' | 'MID' | 'FWD' | 'BEST5' |
  // 'BESTROLE'. Una sola alla volta: cliccare una vista nasconde TUTTE le
  // righe che non ci appartengono (09/08/2026 notte, richiesta esplicita:
  // "deve mostrare solo e soltanto i 5, non gli altri" -- prima erano solo
  // evidenziate in mezzo alle altre).
  var COLORI_RUOLO = { GK: '#8ab4ff', DEF: '#7ee787', MID: '#ffa657', FWD: '#ff7b72' };
  var btnRuoli = Array.prototype.slice.call(document.querySelectorAll('.btn-ruolo'));
  var btnBest5 = document.getElementById('btn-best5');
  var btnBestRole = document.getElementById('btn-bestrole');
  var vista = 'TUTTI';

  function pulisciStiliRiga(tr) {
    tr.style.borderLeft = '';
    tr.style.background = '';
  }

  function aggiornaBottoniAttivi() {
    btnRuoli.forEach(function (b) { b.classList.toggle('attivo', b.dataset.ruolo === vista); });
    if (btnBest5) btnBest5.classList.toggle('attivo', vista === 'BEST5');
    if (btnBestRole) btnBestRole.classList.toggle('attivo', vista === 'BESTROLE');
  }

  function applica() {
    aggiornaBottoniAttivi();
    var tutte = righe();
    tutte.forEach(pulisciStiliRiga);

    if (vista === 'TUTTI') {
      tutte.forEach(function (tr) { tr.style.display = ''; });
      return;
    }
    if (vista === 'GK' || vista === 'DEF' || vista === 'MID' || vista === 'FWD') {
      tutte.forEach(function (tr) {
        tr.style.display = (ruoliDi(tr).indexOf(vista) !== -1) ? '' : 'none';
      });
      return;
    }
    var conRapporto = tutte.map(function (tr) {
      return { tr: tr, r: rapporto(tr) };
    }).filter(function (x) { return x.r !== null; });

    if (vista === 'BEST5') {
      var scelti = conRapporto.slice().sort(function (a, b) { return a.r - b.r; }).slice(0, 5);
      var scelteTr = scelti.map(function (x) { return x.tr; });
      tutte.forEach(function (tr) {
        var dentro = scelteTr.indexOf(tr) !== -1;
        tr.style.display = dentro ? '' : 'none';
        if (dentro) { tr.style.background = 'rgba(255,215,100,0.10)'; }
      });
      return;
    }
    if (vista === 'BESTROLE') {
      var scelteTr2 = [];
      ['GK', 'DEF', 'MID', 'FWD'].forEach(function (ruolo) {
        var candidati = conRapporto.filter(function (x) { return ruoliDi(x.tr).indexOf(ruolo) !== -1; });
        if (!candidati.length) return;
        candidati.sort(function (a, b) { return a.r - b.r; });
        var migliore = candidati[0].tr;
        migliore.style.borderLeft = '4px solid ' + COLORI_RUOLO[ruolo];
        migliore.style.background = 'rgba(255,255,255,0.05)';
        scelteTr2.push(migliore);
      });
      tutte.forEach(function (tr) {
        tr.style.display = (scelteTr2.indexOf(tr) !== -1) ? '' : 'none';
      });
    }
  }

  btnRuoli.forEach(function (btn) {
    btn.addEventListener('click', function () {
      vista = btn.dataset.ruolo;
      applica();
    });
  });
  if (btnBest5) btnBest5.addEventListener('click', function () {
    vista = (vista === 'BEST5') ? 'TUTTI' : 'BEST5';
    applica();
  });
  if (btnBestRole) btnBestRole.addEventListener('click', function () {
    vista = (vista === 'BESTROLE') ? 'TUTTI' : 'BESTROLE';
    applica();
  });
})();
</script>
"""


def _tabella_minimale(pool, attesi, gg=None, fixture_ambigue=frozenset()):
    """Tabella semplificata (09/08/2026, richiesta utente): SOLO giocatore,
    ruolo, club, odds, prezzo, grade, atteso, A+G -- niente arene, niente
    essenze/GW, niente "si ripaga in". UNA lista sola, ordinata per A+G
    (atteso_combinato) decrescente, colonne ordinabili col click (JS gia'
    esistente in _HTML_ORDINAMENTO, agganciato su table#candidati). Chi non
    ha ancora l'atteso (predict non fatto) resta in fondo, mai a valore
    inventato."""
    combinato = _atteso_combinato_per_gruppo(pool, attesi, gg)
    righe = sorted(pool['giocatori'],
                   key=lambda g: -(combinato.get(g['slug'], float('-inf'))))

    pezzi = [
        f"<h2>{len(righe)} candidati</h2>"
        "<div class='meta'>A+G = atteso + effetto del grade dentro il gruppo "
        "lega/ruolo (stessa formula del generatore di formazioni). Ordinamento "
        "di default. Clicca un'intestazione per riordinare su un'altra "
        "colonna.</div>"
        "<div class='meta'>Mostra solo: "
        "<button type='button' class='btn-scelta btn-ruolo attivo' data-ruolo='TUTTI'>Tutti</button> "
        "<button type='button' class='btn-scelta btn-ruolo' data-ruolo='GK'>GK</button> "
        "<button type='button' class='btn-scelta btn-ruolo' data-ruolo='DEF'>DEF</button> "
        "<button type='button' class='btn-scelta btn-ruolo' data-ruolo='MID'>MID</button> "
        "<button type='button' class='btn-scelta btn-ruolo' data-ruolo='FWD'>FWD</button>"
        "</div>"
        "<div class='meta'>"
        "<button type='button' id='btn-best5' class='btn-scelta'>Best Five</button> "
        "<button type='button' id='btn-bestrole' class='btn-scelta'>Best per ruolo</button> "
        "<span class='muted'>rapporto prezzo/A+G (prezzo/Atteso se manca il grade), "
        "piu' basso e' meglio -- esclusi i candidati senza prezzo o senza atteso.</span>"
        "</div>"
        "<div class='wrap'><table id='candidati'>"
        "<tr><th>Giocatore</th><th>R</th><th>Club</th>"
        "<th class='n' title='Starter odds Sorare'>Odds</th><th class='n'>Prezzo</th>"
        "<th class='n' title='Lettera Sorare A..F per la prossima partita classic'>Grade</th>"
        "<th class='n'>Atteso</th>"
        "<th class='n' title='Atteso + effetto del grade dentro il gruppo lega/ruolo'>A+G</th></tr>"]
    for g in righe:
        atteso = attesi.get(g['slug'])
        ag = combinato.get(g['slug'])
        prezzo_num = g.get('prezzo_eur')
        prezzo = ('&mdash;' if prezzo_num is None
                  else '%.2f&nbsp;&euro;' % prezzo_num)
        odds_txt = ('&mdash;' if g.get('starter_odds') is None
                    else "<span class='%s'>%.0f%%</span>"
                         % ('mia' if g['starter_odds'] >= 0.8 else 'warn',
                            g['starter_odds'] * 100))
        grade = g.get('grade') or '&mdash;'
        avviso_ambiguo = (
            " <span class='warn' title=\"Due partite future avevano gia' le "
            "starter odds pubblicate insieme: scelta la piu' tardiva. "
            "Verifica a mano se e' quella giusta (caso limite, vedi HANDOFF_"
            "UNIFICATO_MODELLO_SCOUTING.md §8bis).\">⚠️</span>"
        ) if g['slug'] in fixture_ambigue else ''
        # data-* robusti (non testo da riparsare) per filtro ruolo e bottoni
        # Best Five/Best per ruolo -- niente fragilita' sul formato mostrato.
        pezzi.append(
            "<tr"
            f" data-ruoli='{','.join(g['ruoli'])}'"
            f" data-prezzo='{'' if prezzo_num is None else prezzo_num}'"
            f" data-atteso='{'' if atteso is None else atteso}'"
            f" data-ag='{'' if ag is None else ag}'>"
            f"<td><a href='https://sorare.com/football/players/{g['slug']}' "
            f"target='_blank' rel='noopener'>{(g.get('nome') or g['slug'])}</a>{avviso_ambiguo}</td>"
            f"<td>{'/'.join(g['ruoli'])}</td>"
            f"<td>{(g.get('club') or '')}</td>"
            f"<td class='n'>{odds_txt}</td>"
            f"<td class='n'><a href='https://sorare.com/football/players/{g['slug']}/cards' "
            f"target='_blank' rel='noopener'>{prezzo}</a></td>"
            f"<td class='n'>{grade}</td>"
            f"<td class='n'>{'&mdash;' if atteso is None else '%.1f' % atteso}</td>"
            f"<td class='n'>{'&mdash;' if ag is None else '%.1f' % ag}</td>"
            "</tr>")
    pezzi.append("</table></div>")
    pezzi.append(_HTML_CONTROLLI_MINIMALE)
    return pezzi


def scrivi_html(pool, dest, formazioni=(), minimal=False):
    # gg (generatore) caricato qui, non a livello modulo: stesso schema di
    # componi_arene, cosi' calibrazione (CALIB_PER_RUOLO) e soglie
    # (PAREGGIO_ARENA/GUADAGNO_PER_PUNTO) vengono da un solo posto invece di
    # essere ricopiate localmente e disallinearsi in silenzio (B01/B02).
    try:
        gg = _import('scouting_best_five', 'best_five.py')._import_gg()
    except Exception as e:
        log(f"ATTENZIONE: generatore non caricabile ({e}), atteso/soglie "
            f"scouting ricadono sui vecchi valori grezzi/statici.")
        gg = None
    attesi, fixture_ambigue = _atteso_dai_consigli(pool, gg)

    # Copertura di ogni run, sempre in log (09/08/2026 notte, terzo giro):
    # senza questo numero l'utente non sa se una colonna sara' piena o
    # quasi vuota finche' non apre l'HTML e conta a occhio.
    n_pool = len(pool['giocatori'])
    n_odds = sum(1 for g in pool['giocatori'] if g.get('starter_odds') is not None)
    n_grade = sum(1 for g in pool['giocatori'] if g.get('grade'))
    n_atteso = sum(1 for g in pool['giocatori'] if attesi.get(g['slug']) is not None)
    n_prezzo = sum(1 for g in pool['giocatori'] if g.get('prezzo_eur') is not None)
    def _pct(n):
        return f"{n}/{n_pool} ({100*n/n_pool:.0f}%)" if n_pool else f"{n}/0"
    log(f"COPERTURA -- pool: {n_pool} | odds pubblicate: {_pct(n_odds)} | "
        f"grade: {_pct(n_grade)} | atteso: {_pct(n_atteso)} | prezzo: {_pct(n_prezzo)}")

    slot_medio, per_punto = _slot_medio_e_per_punto(gg)
    filtri = pool.get('filtri') or {}
    testa = _HTML_TESTA % {
        'fixture': pool['fixture']['slug'],
        'quando': datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC'),
        'n': len(pool['giocatori']),
        'filtri': ('stati ' + '/'.join(filtri.get('stati') or ['tutti'])
                   + (', solo con limited in vendita' if filtri.get('solo_in_vendita') else '')
                   + (f", starter odds >= {filtri['odds_min']:.0%}" if filtri.get('odds_min') else '')),
    }
    scremati = any('idoneo' in g for g in pool['giocatori'])
    pezzi = [testa]
    if minimal:
        pezzi += _tabella_minimale(pool, attesi, gg, fixture_ambigue)
        pezzi.append(_HTML_CODA)
        documento = '\n'.join(pezzi)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(documento)
        log(f"Report HTML MINIMALE: {dest}" + (f" ({len(attesi)} attesi dai consigli)" if attesi
                                              else " (nessun consiglio trovato: colonna Atteso vuota)"))
        return
    # Una tabella SOLA, non una per ruolo (richiesta dell'utente 02/08): il
    # ruolo diventa una colonna, e l'ordinamento si fa cliccando le
    # intestazioni. Cosi' si confrontano fra loro anche giocatori di ruoli
    # diversi -- che e' la domanda vera quando si compra: "con dieci euro,
    # cosa mi conviene prendere?".
    for ruolo in ('TUTTI',):
        righe = list(pool['giocatori'])
        if not righe:
            continue
        # VERDETTO d'acquisto (03/08, richiesta utente: tabella semplice, "chi
        # conviene comprare e chi no"). La domanda e' il rapporto fra atteso,
        # costo ed essenze guadagnate a giornata: se una carta rende essenze in
        # piu' di uno slot medio (essenze_gw > 0) e si ripaga in poche giornate
        # (rientro basso), conviene. Ordinato coi migliori affari in cima.
        soglia_odds = filtri.get('odds_min') or 0

        def _giudizio(g):
            atteso = attesi.get(g['slug'])
            if atteso is None:
                return (4, None, 'muted', 'dati mancanti', None, None)
            essenze_gw, _e, rientro = _economia(atteso, g.get('prezzo_eur'), slot_medio, per_punto)
            odds = g.get('starter_odds')
            if odds is not None and odds < soglia_odds:
                return (3, essenze_gw, 'ko', 'NO', rientro, 'odds basse')
            if essenze_gw is None or essenze_gw <= 0:
                return (3, essenze_gw, 'ko', 'NO', rientro, 'non rende')
            if g.get('prezzo_eur') is None:
                return (2, essenze_gw, 'warn', 'FORSE', rientro, 'prezzo ignoto')
            # Soglie tarate sui dati reali (mediana rientro ~38 GW): le essenze
            # in euro rendono poco, quindi ripagare il prezzo pieno e' lungo --
            # COMPRA = fra i piu' efficienti (si ripaga in <=15 GW).
            if rientro is not None and rientro <= 15:
                return (0, essenze_gw, 'mia', 'COMPRA', rientro, None)
            if rientro is not None and rientro <= 40:
                return (1, essenze_gw, 'warn', 'FORSE', rientro, None)
            return (3, essenze_gw, 'ko', 'NO', rientro, 'poco efficiente')

        # ordine: prima i COMPRA, poi rientro piu' basso (affare migliore), poi
        # atteso piu' alto.
        righe.sort(key=lambda g: (_giudizio(g)[0],
                                  _giudizio(g)[4] if _giudizio(g)[4] is not None else 1e9,
                                  -(attesi.get(g['slug']) or 0)))
        pezzi.append(
            f"<h2>{len(righe)} candidati &mdash; ordinati dal miglior affare</h2>"
            "<div class='meta'>Verdetto sul rapporto <b>atteso / costo / essenze a "
            "giornata</b>. <span class='mia'>COMPRA</span> = rende e si ripaga "
            "in poche giornate; <span class='warn'>FORSE</span> = rende ma caro o "
            "prezzo ignoto; <span class='ko'>NO</span> = non rende piu' di uno slot "
            "medio. Clicca un'intestazione per riordinare.</div>"
            "<div class='wrap'><table id='candidati'>"
            "<tr><th>Conviene</th><th>Giocatore</th><th>R</th><th>Atteso</th>"
            "<th>Prezzo</th>"
            "<th title='Essenze in piu' a giornata rispetto a uno slot medio "
            f"da {slot_medio:.1f} punti (scala calibrata, cap 260)'>Ess/GW</th>"
            "<th title='In quante giornate le essenze guadagnate ripagano il "
            "prezzo pieno della carta'>Si ripaga in</th>"
            "<th title='Starter odds Sorare'>Odds</th><th>Note</th></tr>")
        for g in righe:
            atteso = attesi.get(g['slug'])
            rank, essenze_gw, classe, etichetta, rientro, motivo = _giudizio(g)
            prezzo = ('&mdash;' if g.get('prezzo_eur') is None
                      else '%.2f&nbsp;&euro;' % g['prezzo_eur'])
            verdetto = f"<span class='{classe}'><b>{etichetta}</b></span>"
            if motivo:
                verdetto += f" <span class='muted'>{motivo}</span>"
            if essenze_gw is None:
                ess_txt = '&mdash;'
            elif essenze_gw <= 0:
                ess_txt = "<span class='ko'>%+.0f</span>" % essenze_gw
            else:
                ess_txt = "<span class='mia'>+%.0f</span>" % essenze_gw
            rientro_txt = ('&mdash;' if rientro is None
                           else "%.0f&nbsp;GW" % rientro)
            odds_txt = ('&mdash;' if g.get('starter_odds') is None
                        else "<span class='%s'>%.0f%%</span>"
                             % ('mia' if g['starter_odds'] >= 0.8 else 'warn',
                                g['starter_odds'] * 100))
            note = []
            if g.get('carte_mie'):
                note.append(f"<span class='mia'>ne ho {g['carte_mie']}</span>")
            if g.get('infortunato'):
                note.append("<span class='ko'>infortunato</span>")
            if scremati and g.get('idoneo') is False:
                note.append("<span class='warn'>non 2su3</span>")
            # Stesso avviso "fixture ambigua" gia' presente nella tabella
            # minimale (12/08/2026, richiesta esplicita utente: copertura
            # coerente anche nella tabella verdetto/"candidati" di questa
            # modalita' non-minimale, che prima non lo mostrava).
            avviso_ambiguo = (
                " <span class='warn' title=\"Due partite future avevano gia' le "
                "starter odds pubblicate insieme: scelta la piu' tardiva. "
                "Verifica a mano se e' quella giusta (caso limite, vedi HANDOFF_"
                "UNIFICATO_MODELLO_SCOUTING.md §8bis).\">⚠️</span>"
            ) if g['slug'] in fixture_ambigue else ''

            pezzi.append(
                "<tr>"
                f"<td>{verdetto}</td>"
                f"<td><a href='https://sorare.com/football/players/{g['slug']}' "
                f"target='_blank' rel='noopener'>{(g.get('nome') or g['slug'])}</a>{avviso_ambiguo}</td>"
                f"<td>{'/'.join(g['ruoli'])}</td>"
                f"<td class='n'>{'&mdash;' if atteso is None else '%.1f' % atteso}</td>"
                f"<td class='n'><a href='https://sorare.com/football/players/{g['slug']}/cards' "
                f"target='_blank' rel='noopener'>{prezzo}</a></td>"
                f"<td class='n'>{ess_txt}</td>"
                f"<td class='n'>{rientro_txt}</td>"
                f"<td class='n'>{odds_txt}</td>"
                f"<td>{' '.join(note)}</td>"
                "</tr>")
        pezzi.append("</table></div>")

    if formazioni:
        pezzi.append("<h2>Se le comprassi &mdash; arene ipotetiche</h2>"
                     "<div class='meta'>Costruite con lo stesso motore della produzione "
                     "(cap L10, anti-stack, sinergie, capitano). Due avvertenze: "
                     "<b>assumono che questi giocatori scendano in campo</b> &mdash; senza "
                     "starter odds la titolarita' e' una scommessa &mdash; e sono carte che "
                     "<b>non possiedi</b>: e' una simulazione d'acquisto.</div>")
        # Prima il quadro d'insieme, ordinato per resa per euro: e' la domanda
        # vera ("quale conviene comprare?"), e un'arena da 5 EUR con +30 sopra
        # soglia batte una da 15 EUR con +35 pur rendendo meno in assoluto.
        pezzi.append("<div class='wrap'><table><tr><th>Arena</th><th>Atteso</th>"
                     "<th title='Punti sopra la soglia di pareggio'>Margine</th>"
                     "<th title='Essenze nette attese, oltre l&apos;ingresso gia&apos; "
                     "coperto dal pareggio'>Essenze</th>"
                     "<th title='Ingresso in essenze'>Ingresso</th>"
                     "<th title='Somma dei prezzi delle 5 carte'>Costo carte</th>"
                     "<th title='Essenze nette a giornata per euro speso: il rapporto "
                     "che dice quale conviene'>Ess/&euro;</th><th>Verdetto</th></tr>")
        for c in formazioni:
            costo_txt = ('&mdash;' if c['costo'] is None
                         else '%.2f&nbsp;&euro;' % c['costo'])
            if c['senza_prezzo']:
                costo_txt = (f"<span class='warn'>{c['senza_prezzo']} senza prezzo</span>")
            rapporto = ('&mdash;' if c['essenze_per_euro'] is None
                        else '%.0f' % c['essenze_per_euro'])
            colore = c.get('colore') or '#9aa0ad'
            verdetto = (c.get('verdetto') or '').split('--')[0].strip() or '&mdash;'
            pezzi.append(
                f"<tr><td>{c['etichetta_breve']}</td>"
                f"<td class='n'>{c['atteso']:.1f}</td>"
                f"<td class='n'>{c['margine']:+.1f}</td>"
                f"<td class='n'>{c['essenze']:+.0f}</td>"
                f"<td class='n'>{c['ingresso']}</td>"
                f"<td class='n'>{costo_txt}</td>"
                f"<td class='n'>{rapporto}</td>"
                f"<td style='color:{colore}'>{verdetto}</td></tr>")
        totale_costo = [c['costo'] for c in formazioni if c['costo'] is not None]
        totale_ess = [c['essenze'] for c in formazioni if c['essenze'] is not None]
        if totale_costo:
            pezzi.append(
                f"<tr><td><b>Tutte insieme</b></td><td colspan='2'></td>"
                f"<td class='n'><b>{sum(totale_ess):+.0f}</b></td>"
                f"<td class='n'>{sum(c['ingresso'] for c in formazioni)}</td>"
                f"<td class='n'><b>{sum(totale_costo):.2f}&nbsp;&euro;</b></td>"
                f"<td class='n'><b>{sum(totale_ess) / sum(totale_costo):.0f}</b></td>"
                f"<td class='muted'>carte distinte, si sommano</td></tr>")
        pezzi.append("</table></div>")

        for c in formazioni:
            etichetta = c['etichetta_breve']
            if c['soglia']:
                etichetta += f" &mdash; pareggio a {c['soglia']:.1f}"
            pezzi.append(f"<h3 style='font-size:14px;margin:14px 0 4px;color:#9aa0ad'>{etichetta}</h3>")
            # Le card grafiche del generatore quando ci sono (stesse .pcard,
            # con prezzo per carta e totale annotati sopra); il testo solo se
            # per qualche motivo l'HTML manca.
            if c.get('blocco_html'):
                pezzi.append(c['blocco_html'])
            else:
                pezzi.append(f"<pre style='background:#161922;padding:10px;overflow-x:auto;"
                             f"border-radius:6px;font-size:12px'>{_escape(c['blocco'])}</pre>")
    pezzi.append(_HTML_CODA)
    documento = '\n'.join(pezzi)

    # I blocchi formazione sono le .pcard del generatore, e senza il suo CSS
    # sarebbero un elenco slavato. Il foglio di stile arriva da li' -- non
    # ricopiato, letto -- e con lui i due post-processing che best_five applica
    # gia' ai suoi report: prezzo su ogni carta piu' totale di formazione, e
    # click sulla carta che apre la pagina Sorare del giocatore.
    if any(c.get('blocco_html') for c in formazioni):
        try:
            bf = _import('scouting_best_five_html', 'best_five.py')
            documento = documento.replace('</head>', _css_delle_carte(bf) + '</head>')
            prezzi_carte = {g['slug']: g.get('prezzo_eur') for g in pool['giocatori']}
            # Prima lo script che DISEGNA le carte, poi quello che ci appende i
            # prezzi: l'ordine conta, il secondo lavora sul risultato del primo.
            documento = documento.replace(
                '</body>', _script_delle_carte(bf) + _prezzi_sulle_carte(prezzi_carte) + '</body>')
            documento = bf.rendi_carte_cliccabili(documento)
        except Exception as e:
            log(f"ATTENZIONE: stile/prezzi delle card non applicati ({e}); "
                f"le formazioni restano leggibili ma senza grafica.")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(documento)
    log(f"Report HTML: {dest}" + (f" ({len(attesi)} attesi dai consigli)" if attesi
                                  else " (nessun consiglio trovato: colonna Atteso vuota)"))
    return dest


def stampa_idonei(pool, limite=None):
    """L'elenco dei candidati, ordinato per L10 dentro ciascun ruolo."""
    idonei = [g for g in pool['giocatori'] if g.get('idoneo')]
    idonei.sort(key=lambda g: -(g.get('l10') or 0))
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        righe = [g for g in idonei if ruolo in g['ruoli']]
        print(f"\n=== {ruolo} -- {len(righe)} candidati")
        for g in (righe[:limite] if limite else righe):
            minuti = '/'.join(str(m) for m in g.get('minuti_recenti') or [])
            print(f"  {(g.get('nome') or g['slug'])[:26]:<26} L10 {(g.get('l10') or 0):>5.1f}  "
                  f"min {minuti:<12} {g['club'][:26]:<26} vs {g['avversario'][:24]:<24} "
                  f"{(g.get('data') or '')[:10]}  [{g.get('cartella')}]")


def main():
    ap = argparse.ArgumentParser(description="Pool di una giornata futura, senza odds.")
    ap.add_argument('--gameweek', type=int, default=None, help="numero di giornata (es. 2)")
    ap.add_argument('--fixture', default=None, help="slug fixture (es. football-4-7-aug-2026)")
    ap.add_argument('--json', default=None, help="file di output (default: dati_globali/scouting_<fixture>.json)")
    ap.add_argument('--screen', action='store_true',
                    help="dopo il pool, screma con le ultime partite (1 query a giocatore)")
    ap.add_argument('--da-pool', default=None,
                    help="salta la costruzione e screma un pool gia' scritto (per lo sharding)")
    ap.add_argument('--unisci', default=None,
                    help="cartella con le quote scremate da rimettere insieme")
    ap.add_argument('--roster', action='store_true',
                    help="percorso lento di controllo: pool dai roster dei club "
                         "(~75 query) invece di searchPlayers (~12)")
    ap.add_argument('--tutti-gli-stati', action='store_true',
                    help="non filtrare per playing_status (pool completo della giornata)")
    ap.add_argument('--anche-non-in-vendita', action='store_true',
                    help="tieni anche chi non ha nessuna limited in vendita")
    ap.add_argument('--odds-min', type=float, default=None,
                    help="tieni solo chi ha starter odds >= X (es. 0.80), come il "
                         "generatore: odds assenti = escluso. Usalo solo quando le "
                         "odds sono uscite, altrimenti scarta tutti")
    ap.add_argument('--lega', default=None,
                    help="tieni solo queste cartelle lega, separate da virgola (es. mls,messico)")
    ap.add_argument('--per-ruolo', type=int, default=None,
                    help="campione: N candidati per ruolo, divisi in quattro fasce di L10")
    ap.add_argument('--solo-l10', action='store_true',
                    help="campione vecchio stile: i migliori N per L10 e basta "
                         "(satura i cap, tenuto solo per confronto)")
    ap.add_argument('--scrivi-discovery', action='store_true',
                    help="scrive player_slugs.json per lega/ruolo, cosi' i predict "
                         "girano sui candidati SOVRASCRIVENDO la discovery di produzione")
    ap.add_argument('--html', default=None,
                    help="report HTML (default con --scrivi-discovery: "
                         "generatore_formazioni/output/scouting_<fixture>.html)")
    ap.add_argument('--minimal', action='store_true',
                    help="tabella minima: giocatore/ruolo/club/odds/prezzo/atteso/grade, "
                         "niente arene ne' essenze/GW (09/08/2026, richiesta utente: "
                         "'a me interessa semplificarlo e farlo funzionare'). Le sezioni "
                         "complete restano nel codice e si riaccendono senza questo flag")
    ap.add_argument('--riusa-pool', action='store_true',
                    help="il report riusa lo STESSO pool gia' scritto dal job "
                         "candidati (dati_globali/scouting_<fixture>.json) invece "
                         "di ricostruirlo con searchPlayers+odds: cosi' i "
                         "giocatori mostrati sono ESATTAMENTE quelli predetti, "
                         "tutti con l'Atteso, e non un set diverso pescato a "
                         "un'ora di distanza")
    args = ap.parse_args()

    pool = None
    if args.riusa_pool:
        # Il report NON ricostruisce il pool: carica quello gia' scritto e
        # committato dal job candidati. Ricostruirlo con searchPlayers+odds a
        # un'ora di distanza dava un set DIVERSO (le odds cambiano) e lasciava
        # senza Atteso i candidati non piu' selezionati -- 125 analizzati ma
        # solo ~60 con l'Atteso (run 30814827740). Se il pool committato manca
        # (commit fallito), si RICOSTRUISCE (fallback) invece di fallire secco.
        fx = risolvi_giornata(args.gameweek, args.fixture)
        ppath = (os.path.join(REPO_ROOT, 'dati_globali', f"scouting_{fx['slug']}.json")
                 if fx else None)
        if ppath and os.path.exists(ppath):
            with open(ppath, encoding='utf-8') as f:
                pool = json.load(f)
            log(f"Report dallo STESSO pool di candidati: {len(pool['giocatori'])} "
                f"giocatori (giornata {fx['slug']}).")
        else:
            log("ATTENZIONE: pool committato non trovato -> RICOSTRUISCO con "
                "searchPlayers+odds (fallback, set potenzialmente diverso).")

    if pool is not None:
        pass  # gia' caricato da --riusa-pool
    elif args.unisci:
        pool = unisci(args.unisci)
        if not pool:
            return 1
        stampa_idonei(pool)
    elif args.da_pool:
        with open(args.da_pool, encoding='utf-8') as f:
            pool = json.load(f)
        log(f"Pool letto da {args.da_pool}: {len(pool['giocatori'])} giocatori "
            f"(giornata {pool['fixture']['slug']})")
        pool['giocatori'] = _shard(pool['giocatori'])
        screma(pool['giocatori'])
    elif args.roster:
        pool = costruisci_pool(args.gameweek, args.fixture)
        if not pool:
            return 1
        if args.screen:
            pool['giocatori'] = _shard(pool['giocatori'])
            screma(pool['giocatori'])
    else:
        # Con le odds attive il prefiltro `playing_status` si spegne da solo.
        # Non e' un conflitto tecnico -- sarebbero in AND -- ma un
        # restringimento che fa perdere gente: chi Sorare classifica
        # 'substitute' non entrerebbe MAI nel pool, nemmeno con odds all'85%.
        # E quando le odds sono pubblicate sono il dato migliore che abbiamo:
        # e' una probabilita' misurata da Sorare su quella partita, mentre
        # playing_status e' un'etichetta generica sul giocatore.
        stati = () if (args.tutti_gli_stati or args.odds_min) else STATI_TITOLARE
        if args.odds_min and not args.tutti_gli_stati:
            log("Odds attive: prefiltro starter/regular disattivato, decidono le "
                "odds (piu' affidabili e specifiche di quella partita).")
        pool = pool_da_search(
            args.gameweek, args.fixture,
            stati=stati,
            solo_in_vendita=not args.anche_non_in_vendita)
        if not pool:
            return 1
        if args.lega:
            leghe = {x.strip() for x in args.lega.split(',') if x.strip()}
            prima = len(pool['giocatori'])
            pool['giocatori'] = [g for g in pool['giocatori'] if g.get('cartella') in leghe]
            log(f"Filtro lega {sorted(leghe)}: {len(pool['giocatori'])}/{prima} candidati")
        if args.odds_min:
            # Le odds si prendono in BLOCCO dalle partite della giornata
            # (filtra_per_odds -> odds_per_giornata): ~37 query in <1s, non piu'
            # una a candidato. Quindi niente campione "largo" preventivo: si
            # analizzano TUTTI quelli con odds >= soglia. Se le odds non sono
            # ancora uscite, filtra_per_odds torna l'intero pool (nessun filtro).
            pool['giocatori'] = filtra_per_odds(pool, args.odds_min)
            if not pool['giocatori']:
                log("ERRORE: le odds sono uscite ma nessun candidato supera la "
                    "soglia. Non scrivo niente e mi fermo. Abbassa odds_min o "
                    "rilancia senza.")
                return 1
        if args.per_ruolo:
            # Retrocompatibile: se qualcuno passa ancora --per-ruolo si campiona,
            # ma NON e' piu' il percorso normale (ora si analizza tutto il pool
            # con odds valorizzata).
            pool['giocatori'] = campiona(pool['giocatori'], args.per_ruolo,
                                         a_fasce=not args.solo_l10)
        if args.screen:
            # Qui la scrematura non filtra: e' il controllo sui candidati che
            # Sorare ha gia' selezionato, e costa 1 query a testa su qualche
            # centinaio di giocatori invece che su 2.400.
            screma(pool['giocatori'])
            passa = sum(1 for g in pool['giocatori'] if g.get('idoneo'))
            log(f"CONTROLLO 2-su-3: {passa}/{len(pool['giocatori'])} confermati "
                f"(chi non passa resta in elenco, marcato)")
        stampa_candidati(pool)

    if pool['giocatori'] and 'idoneo' in pool['giocatori'][0] and pool.get('sorgente') != 'searchPlayers':
        idonei = [g for g in pool['giocatori'] if g.get('idoneo')]
        ignoti = [g for g in pool['giocatori'] if g.get('idoneo') is None]
        per_ruolo = defaultdict(int)
        for g in idonei:
            for r in g['ruoli']:
                per_ruolo[r] += 1
        log(f"IDONEI: {len(idonei)}/{len(pool['giocatori'])} "
            f"(GK {per_ruolo['GK']}, DEF {per_ruolo['DEF']}, MID {per_ruolo['MID']}, "
            f"FWD {per_ruolo['FWD']})" + (f" -- {len(ignoti)} non valutabili" if ignoti else ""))
        stampa_idonei(pool)

    dest = args.json or os.path.join(
        REPO_ROOT, 'dati_globali', f"scouting_{pool['fixture']['slug']}.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        # Compatto: il pool di una giornata sono ~2.400 giocatori e con
        # l'indentazione supera il mezzo mega. E' rigenerabile in 30 secondi,
        # non vale peso nell'albero (il checkout di ogni job lo paga).
        json.dump(pool, f, ensure_ascii=False, separators=(',', ':'))
    log(f"Scritto {dest}")

    if args.scrivi_discovery:
        leghe = {x.strip() for x in (args.lega or '').split(',') if x.strip()} or None
        scritti = scrivi_discovery(pool, leghe=leghe)
        if not scritti:
            log("ATTENZIONE: nessuna discovery scritta (nessun candidato con una "
                "cartella formazione_* fra quelli rimasti).")
        else:
            totale = sum(n for _, _, n in scritti)
            log(f"Discovery scritte: {len(scritti)} gruppi lega/ruolo, {totale} slug in tutto. "
                f"Ora i predict di quelle leghe girano su QUESTI giocatori.")

    if args.html or args.scrivi_discovery:
        # Le formazioni si possono comporre solo quando i consigli esistono
        # gia': alla prima passata (quella che SCRIVE la discovery) non ci
        # sono ancora, e la sezione semplicemente non compare.
        # --minimal: niente arene in nessun caso, la modalita' semplificata
        # non le mostra.
        formazioni = (() if (args.scrivi_discovery or args.minimal)
                     else componi_arene(pool))
        scrivi_html(pool, args.html or os.path.join(
            REPO_ROOT, 'generatore_formazioni', 'output',
            f"scouting_{pool['fixture']['slug']}.html"), formazioni,
            minimal=args.minimal)
    return 0


if __name__ == '__main__':
    sys.exit(main())
