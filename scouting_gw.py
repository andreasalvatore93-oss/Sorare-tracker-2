"""
scouting_gw.py -- il pool di una giornata FUTURA, prima che escano le odds.

Perche' esiste
--------------
La pipeline di produzione parte dalle carte POSSEDUTE e si appoggia alle
starter odds, che Sorare pubblica solo a 24-48h dal calcio d'inizio. Per
COMPRARE serve l'opposto: sapere con giorni di anticipo chi scendera' in campo
nella prossima giornata, includendo carte che l'utente non ha.

L'aggancio e' la fixture. `so5Fixture(slug).anyGames` elenca tutte le partite
della giornata CON le squadre, ed e' interrogabile appena la giornata esiste --
anche mentre quella precedente e' ancora in corso, che e' esattamente il caso
in cui serve. Chi non gioca in uno di quei club non e' un candidato, punto: e'
un filtro esatto, non una stima, e costa UNA query.

Da li' i roster: `club(slug).activePlayers` e' pubblico (verificato senza
cookie il 02/08) e torna posizione e `activeClub` di ogni tesserato. Una query
per club, tipicamente una pagina sola.

Cosa NON fa
-----------
Nessuna query per giocatore: niente qualita' (L5/L10/L40), niente minuti
giocati, niente prezzi. Quelle costano una chiamata a testa e su ~2.500
candidati sono insostenibili -- vanno fatte DOPO, sui sopravvissuti alla
scrematura. Qui si costruisce solo l'insieme di partenza.

Uso
---
    python scouting_gw.py --gameweek 2
    python scouting_gw.py --fixture football-4-7-aug-2026 --json out.json

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
    args = ap.parse_args()

    if args.unisci:
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
    else:
        pool = costruisci_pool(args.gameweek, args.fixture)
        if not pool:
            return 1
        if args.screen:
            pool['giocatori'] = _shard(pool['giocatori'])
            screma(pool['giocatori'])

    if pool['giocatori'] and 'idoneo' in pool['giocatori'][0]:
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
