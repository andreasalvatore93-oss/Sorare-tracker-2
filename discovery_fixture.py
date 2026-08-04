"""Discovery per GIORNATA (So5Fixture) -- 27/07.

Sostituisce la logica "scarica tutte le ~2000 carte possedute e poi scarta
quelle di altre leghe", ripetuta 80 volte (20 campionati x 4 ruoli).

Qui si parte dalla GIORNATA: si risolve la So5Fixture (per numero di gameweek o
per slug), si chiedono a Sorare SOLO le carte eleggibili per quella fixture --
filtro lato server, stesso meccanismo di active_competitions gia' usato da MLS
con 'mlspa' -- e su quel manipolo si applica la soglia starter-odds.

Output: per ogni lega con almeno un giocatore sopravvissuto, scrive
formazione_<lega>/output/<lega>_<ruolo>_discovery/player_slugs.json, piu' un
riepilogo JSON su stdout con le leghe da processare. Le leghe senza nessun
sopravvissuto non compaiono: niente job di predict per campionati in pausa.

Variabili d'ambiente:
  GAMEWEEK       numero di giornata (es. 95). In alternativa:
  FIXTURE_SLUG   slug esplicito (es. football-28-31-jul-2026)
  MIN_STARTER_ODDS  soglia (default 0.80); odds assenti = ESCLUSO
"""
import datetime
import json
import os
import sys
import random
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'formazione_turchia', 'discovery'))
os.environ.setdefault('MIN_STARTER_ODDS', '0.80')
import turchia_gk_discovery as base  # noqa: E402

MIN_ODDS = float(os.environ.get('MIN_STARTER_ODDS', '0.80'))
GAMEWEEK = os.environ.get('GAMEWEEK', '').strip()
FIXTURE_SLUG = os.environ.get('FIXTURE_SLUG', '').strip()

# Storico delle odds di titolarita' PRESE PRIMA DELLA DEADLINE (04/08).
# PERCHE': il campo starterOddsBasisPoints dentro il game log viene RISCRITTO
# dopo le formazioni ufficiali -- misurato su 230 coppie da
# verifica_odds_predeadline.py: il 100% dei valori post-partita e' 0% o 100%
# contro il 7,7% dei pre-deadline, e solo il 6,1% coincide. Lo storico
# post-partita quindi non serve a niente per prevedere, mentre il valore vivo
# che passa di qui ogni giornata e' il dato buono -- e finora veniva usato
# come semplice filtro di soglia e poi buttato.
ODDS_STORICO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'dati_globali', 'odds_titolarita_storico.json')
_RUN_TS = None

# Pausa fra una chiamata odds+L10 (combinata, vedi odds_e_l10_singola) e la
# successiva. Cronistoria (28/07): a 0.2s (~5 richieste/s) il 429 scattava
# quasi sempre (run 30336178358 e altri 4 precedenti, attese fino a 255s);
# alzato a 0.5s ma un run reale successivo (30337447148, prima di unire
# odds+L10 in una chiamata sola) ha mostrato che il vero limite di Sorare e'
# CUMULATIVO su tutto il job (~60-70 richieste/minuto), non per singolo
# blocco -- 0.5s (~2 richieste/s teoriche) restava comunque sopra soglia.
# Con la fusione odds+L10 il numero di chiamate e' dimezzato, ma la CADENZA
# (chiamate/minuto) resta quella data da questo valore -- alzato a 0.7s per
# restare sotto ~60/min con margine, invece di contare solo sulla riduzione
# del volume totale.
ODDS_L10_SLEEP = float(os.environ.get('ODDS_L10_SLEEP', '0.7'))

ROLE_BY_POSITION = {'Goalkeeper': 'gk', 'Defender': 'def',
                    'Midfielder': 'mid', 'Forward': 'fwd'}

# DISCOVERY_ROLES (28/07, TEST richiesto esplicitamente dall'utente -- vedi
# sezione 30.I del riassunto -- per spezzare la discovery in piu' job
# paralleli di GitHub Actions, uno per sottoinsieme di ruoli, per ridurre il
# tempo totale di parete): sottoinsieme separato da virgole di gk/def/mid/fwd
# da processare in QUESTA esecuzione. Default: tutti e 4 (comportamento
# INVARIATO se la env non e' impostata). Ogni job scrive solo le cartelle di
# output dei ruoli che gli competono -- nessuna sovrapposizione di file tra
# job paralleli.
_raw_roles = os.environ.get('DISCOVERY_ROLES', '').strip()
if _raw_roles:
    _wanted = {r.strip().lower() for r in _raw_roles.split(',') if r.strip()}
    ROLE_BY_POSITION = {pos: role for pos, role in ROLE_BY_POSITION.items() if role in _wanted}

# DISCOVERY_LEAGUE_SHARD (28/07, generalizzato da DISCOVERY_LEAGUE_HALF per
# il TEST v3 -- 12 job discovery -- vedi 30.I/30.K/30.L del riassunto):
# formato 'idx:n' (es. '0:4' = quota 0 di 4), per processare solo 1/n delle
# leghe di destinazione (split alfabetico fisso e deterministico), usato per
# spezzare ULTERIORMENTE un ruolo affollato (DEF, MID) in piu' job paralleli
# (non solo 2 come nella prima versione a meta'). La query CARDS_QUERY
# (paginazione carte) resta duplicata fra le quote dello stesso ruolo --
# costo piccolo -- ma le chiamate odds+L10 (il vero costo) sono filtrate
# PRIMA di essere fatte, quindi davvero divise per n a testa. Default: non
# impostata = nessun filtro (comportamento INVARIATO).
_raw_shard = os.environ.get('DISCOVERY_LEAGUE_SHARD', '').strip()
DISCOVERY_LEAGUE_SHARD = None
if _raw_shard:
    _idx_s, _n_s = _raw_shard.split(':')
    DISCOVERY_LEAGUE_SHARD = (int(_idx_s), int(_n_s))

# HEAVY_LEAGUE_SHARD (28/07, richiesta esplicita utente): le quote isolate di
# mls/kleague (vedi _HEAVY_LEAGUES sotto) restano piu' lente delle altre
# anche da sole -- hanno oggettivamente piu' carte possedute, quindi piu'
# chiamate odds+L10 (il vero costo). Formato 'idx:n', stesso principio dello
# sharding predict: divide gli slug SOPRAVVISSUTI di QUELLA lega (dopo il
# filtro club-in-campo, prima delle chiamate odds+L10) in n quote, cosi' piu'
# job possono condividere la STESSA DISCOVERY_LEAGUE_SHARD (isolano sempre e
# solo quella lega pesante) ma processano ciascuno solo 1/n dei suoi
# giocatori. Non tocca la paginazione CARDS_QUERY (costo piccolo, resta
# duplicato) ne' _WANTED_DIRNAMES. Default: non impostata = nessun filtro
# (comportamento INVARIATO, un solo job con tutti gli slug della lega).
_raw_heavy_shard = os.environ.get('HEAVY_LEAGUE_SHARD', '').strip()
HEAVY_LEAGUE_SHARD = None
if _raw_heavy_shard:
    _hidx_s, _hn_s = _raw_heavy_shard.split(':')
    HEAVY_LEAGUE_SHARD = (int(_hidx_s), int(_hn_s))

# lega Sorare (domesticLeague.slug) -> cartella formazione_<x> nel repo
LEAGUE_DIR = {
    'major-league-soccer': 'mls', 'mlspa': 'mls', 'k-league-1': 'kleague',
    'austrian-bundesliga': 'austria', 'jupiler-pro-league': 'belgio',
    'campeonato-brasileiro-serie-a': 'brasile', '1-hnl': 'croazia',
    'ligue-1-fr': 'francia', 'ligue-2-fr': 'francia2', 'bundesliga-de': 'germania',
    '2-bundesliga': 'germania2', 'j1-league': 'giappone',
    'j1-100-year-vision-league': 'giappone100', 'premier-league-gb-eng': 'inghilterra',
    'football-league-championship': 'inghilterra2', 'serie-a-it': 'italia',
    'eredivisie': 'olanda', 'primeira-liga-pt': 'portogallo',
    'premiership-gb-sct': 'scozia', 'laliga-es': 'spagna',
    'spor-toto-super-lig': 'turchia', 'superliga-dk': 'danimarca',
    'superliga-argentina-de-futbol': 'argentina', 'super-league-ch': 'svizzera',
    'super-league-1': 'grecia',
    # Aggiunte 28/07 (richiesta esplicita utente, giocatori eleggibili visti
    # su Sorare ma scartati come "lega senza pipeline"): Kacper Urbanski
    # (Ekstraklasa, Polonia) e Francisco Gonzalez (Primera Division, Cile).
    'ekstraklasa': 'polonia', 'primera-division-cl': 'cile',
    # Aggiunte 31/07 (richiesta esplicita utente: "basta che poi il bot
    # riconosca che io ho quelle carte quando devo schierare"). Elenco preso
    # dall'audit reale delle carte possedute (audit_leghe_possedute.py, run
    # del 31/07): TUTTE le domesticLeague in cui l'utente ha almeno una carta
    # e che non avevano ancora una cartella. Senza la voce qui,
    # discovery_fixture.py scartava quelle carte come "lega senza pipeline"
    # e non arrivavano mai al generatore, per quanti punti valessero.
    # Le prime tre sono le uniche con volume significativo (17/11/10 carte),
    # il resto e' coda lunga da 1-6 carte -- costano comunque nulla, la
    # pipeline e' clonata e i ruoli senza candidati restano semplicemente
    # vuoti.
    'liga-mx': 'messico', 'segunda-division-es': 'spagna2',
    'serie-b-it': 'italia2', 'first-division-b': 'belgio2',
    '2-liga': 'germania3', 'russian-premier-league': 'russia',
    'pro-league': 'arabia', 'primera-a': 'colombia',
    'eliteserien': 'norvegia', 'k-league-2': 'kleague2',
    'j2-league': 'giappone2', 'eerste-divisie': 'olanda2',
    'allsvenskan': 'svezia', 'liga-1': 'romania',
    'czech-liga': 'cechia', 'super-liga-rs': 'serbia',
    'ligat-ha-al': 'israele', 'ukrainian-premier-league': 'ucraina',
    'chinese-super-league': 'cina', 'primera-division-ve': 'venezuela',
    'tipsport-liga': 'slovacchia', 'premyer-liqa': 'azerbaigian',
    # Aggiunte 02/08: leghe presenti nella giornata 2 (football-4-7-aug-2026)
    # ma senza cartella -- i loro club scendevano in campo e i giocatori
    # sarebbero stati scartati come "lega senza pipeline". Slug presi dal vivo
    # da club.domesticLeague dei 74 club della fixture, mai indovinati.
    'primera-division-pe': 'peru', '1-division-cy': 'cipro',
    'urvalsdeild': 'islanda',
}

# Split delle cartelle di destinazione in n quote -- usato solo se
# DISCOVERY_LEAGUE_SHARD e' impostata. Split PESATO (28/07, bug reale trovato
# dall'utente su run reali: discovery_def_5/discovery_def_6/discovery_gk_3/
# discovery_fwd_3 impiegavano 2-5x le altre quote, sempre le STESSE ogni
# run): il vecchio taglio era alfabetico CIECO su numero di leghe, non su
# carico di lavoro -- mls e kleague (di gran lunga le leghe con piu' carte
# possedute, quindi piu' chiamate odds+L10) finivano SEMPRE nello stesso
# blocchetto alfabetico ('kleague'/'mls' sono alfabeticamente vicine), quindi
# SEMPRE le stesse quote sovraccariche mentre le altre restavano quasi vuote.
# Fix: le leghe pesanti hanno una quota TUTTA PER LORO (isolate, non miste
# con nessun'altra lega), le restanti leghe leggere si dividono alfabeticamente
# le quote rimanenti -- stesso principio del vecchio taglio ma senza mai
# mischiare una lega pesante con altre leghe nella stessa quota.
_HEAVY_LEAGUES = ['mls', 'kleague']
_ALL_DIRNAMES = sorted(set(LEAGUE_DIR.values()) | {'senza_lega'})
_LIGHT_DIRNAMES = sorted(set(_ALL_DIRNAMES) - set(_HEAVY_LEAGUES))
_WANTED_DIRNAMES = None
if DISCOVERY_LEAGUE_SHARD is not None:
    _idx, _n = DISCOVERY_LEAGUE_SHARD
    _n_heavy = len(_HEAVY_LEAGUES)
    if _n > _n_heavy:
        # Ultime _n_heavy quote = una lega pesante ciascuna (isolata). Le
        # prime (_n - _n_heavy) quote si dividono le leghe leggere.
        if _idx >= _n - _n_heavy:
            _WANTED_DIRNAMES = {_HEAVY_LEAGUES[_idx - (_n - _n_heavy)]}
        else:
            _n_light = _n - _n_heavy
            _tot = len(_LIGHT_DIRNAMES)
            _start = (_tot * _idx) // _n_light
            _end = (_tot * (_idx + 1)) // _n_light
            _WANTED_DIRNAMES = set(_LIGHT_DIRNAMES[_start:_end])
    else:
        # Troppe poche quote per isolare le leghe pesanti (n <= 2): fallback
        # al vecchio taglio alfabetico cieco su TUTTE le leghe, comportamento
        # precedente (nessuna configurazione attuale usa n cosi' basso).
        _tot = len(_ALL_DIRNAMES)
        _start = (_tot * _idx) // _n
        _end = (_tot * (_idx + 1)) // _n
        _WANTED_DIRNAMES = set(_ALL_DIRNAMES[_start:_end])

FIXTURE_BY_GW = """
query FixtureList($first: Int!) {
  so5 {
    so5Fixtures(first: $first) {
      nodes { slug seasonGameWeek aasmState startDate endDate }
    }
  }
}
"""

FIXTURE_BY_SLUG = """
query FixtureBySlug($slug: String!) {
  so5 { so5Fixture(slug: $slug) { slug seasonGameWeek aasmState startDate endDate } }
}
"""

# Partite della giornata: da qui si ricavano le SQUADRE che scendono in campo.
# E' la chiave per non interrogare le starter odds di ~2000 giocatori: si
# tengono solo i posseduti il cui club gioca in questa giornata.
FIXTURE_GAMES = """
query FixtureGames($slug: String!) {
  so5 {
    so5Fixture(slug: $slug) {
      anyGames {
        date
        homeTeam { ... on TeamInterface { slug name } }
        awayTeam { ... on TeamInterface { slug name } }
      }
    }
  }
}
"""

# Carte possedute ELEGGIBILI per la fixture indicata: il filtro vive in
# advancedFilters, quindi Sorare restituisce gia' solo quelle giuste.
CARDS_QUERY = """
query FixtureCards($userSlug: String!, $page: Int!, $pageSize: Int!,
                   $advancedFilters: String, $refinements: [SearchRefinementInput!]) {
  user(slug: $userSlug) {
    searchCards(rarity: limited, sport: FOOTBALL, query: "", page: $page,
                pageSize: $pageSize, advancedFilters: $advancedFilters,
                refinements: $refinements) {
      hits {
        slug
        inSeasonEligible
        # u23Eligible/xp/powerBreakdown vivono sul tipo CONCRETO Card, non
        # sull'interfaccia AnyCardInterface restituita da 'hits' -- senza il
        # fragment esplicito la query fallisce per intero (stesso bug gia'
        # documentato per coverageStatus in bots/autobuy_sorare.py, 19/07,
        # riscoperto qui il 28/07: nessuna carta viene piu' trovata, silenzioso).
        ... on Card {
          u23Eligible
          xp
          powerBreakdown {
            seasonBasisPoints
            collectionBasisPoints
            xpBasisPoints
            scarcityBasisPoints
            specialEditionCardsBasisPoints
            activeClubsBasisPoints
            nationalityBasisPoints
            positionsBasisPoints
          }
        }
        anyPlayer {
          slug
          displayName
          activeClub { slug domesticLeague { slug } }
        }
      }
      nbHits
      nbPages
    }
  }
}
"""

# Combinata odds+L10 (28/07, richiesta esplicita utente: la discovery
# impiegava 9+ minuti per via del rate limit di Sorare -- vedi ODDS_L10_SLEEP
# sopra -- e la causa principale era 2 chiamate HTTP separate per ogni
# sopravvissuto, odds e L10, sullo STESSO slug. Qui NON e' l'alias-su-piu'-
# slug gia' verificato rifiutato da Sorare (vedi bot_profit.py/quality_filter
# .py): e' un solo 'anyPlayer(slug)' con due gruppi di campi diversi per lo
# STESSO giocatore, sintassi GraphQL normale senza alias duplicati -- dimezza
# le chiamate totali (e quindi il rischio di 429) senza cambiare ne' i dati
# richiesti ne' il filtro applicato dopo.
ODDS_AND_L10_QUERY = """
query NextOddsAndL10($slug: String!) {
  anyPlayer(slug: $slug) {
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
    anyFutureGames(first: 3) {
      nodes {
        playerGameScore(playerSlug: $slug) {
          anyGame { date }
          anyPlayerGameStats {
            ... on PlayerGameStats {
              footballPlayingStatusOdds { starterOddsBasisPoints }
            }
          }
        }
      }
    }
  }
}
"""


def odds_e_l10_singola(slug, inizio, fine):
    """(odds, data, l10) in UNA sola chiamata HTTP invece di due (28/07):
    stessa logica di filtro finestra di prima, solo unita in una query con
    due gruppi di campi sullo stesso 'anyPlayer(slug)' -- dimezza le
    richieste verso Sorare per ogni sopravvissuto."""
    d = base.graphql_query(ODDS_AND_L10_QUERY, {"slug": slug}, operation_name="NextOddsAndL10")
    # Query FALLITA (429 con retry esauriti, blocco CloudFront, ecc.): oggi
    # finiva indistinguibile da "nessuna partita nella finestra" e il
    # giocatore posseduto sparisce dalle formazioni SENZA errore visibile --
    # la stessa classe di bug di "Zinckernagel perso in silenzio". Il
    # comportamento non cambia (non abbiamo il dato, il giocatore resta
    # fuori), ma ora si vede nel log.
    if not ((d or {}).get('data') or {}).get('anyPlayer'):
        log(f"  ATTENZIONE: odds/L10 non ottenute per {slug} (query fallita, "
            f"non 'nessuna partita in finestra') -- giocatore NON considerato")
    p = (d.get('data') or {}).get('anyPlayer') or {}
    l10 = p.get('lastTenPlayedAvgScore')
    for n in ((p.get('anyFutureGames') or {}).get('nodes') or []):
        pgs = n.get('playerGameScore') or {}
        dt = (pgs.get('anyGame') or {}).get('date') or ''
        if inizio and fine and not (inizio <= dt[:19] <= fine):
            continue
        o = ((pgs.get('anyPlayerGameStats') or {})
             .get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
        return (o / 10000.0 if o is not None else None), dt, l10
    return None, None, l10


# L10 puro, senza le odds e senza la finestra: serve al top-up del generatore
# (build_formazione_globale) per riempire l'L10 di un candidato a cui la
# discovery non l'ha persistito -- l'L10 e' un campo API player-level, dinamico
# (si aggiorna dopo ogni partita) e SEMPRE esposto, quindi un candidato senza
# L10 e' un buco di raccolta nostro, mai un dato inesistente. Contarlo 0 nel
# cap arena faceva sforare il tetto in silenzio.
L10_ONLY_QUERY = """
query L10Only($slug: String!) {
  anyPlayer(slug: $slug) {
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
  }
}
"""


def l10_da_api(slug):
    """L10 (lastTenPlayedAvgScore) di un giocatore, o None solo se l'API la
    torna davvero nulla (giocatore senza nessuna So5 giocata). base.graphql_query
    ha gia' il suo retry, quindi un 429/blocco transitorio non lascia il buco."""
    try:
        d = base.graphql_query(L10_ONLY_QUERY, {"slug": slug}, operation_name="L10Only")
    except Exception as e:
        log(f"  L10 non ottenuta per {slug}: {e!r}")
        return None
    p = ((d or {}).get('data') or {}).get('anyPlayer') or {}
    return p.get('lastTenPlayedAvgScore')


_GAMES_DELLA_FIXTURE = """
query FixtureGameIds($slug: String!) {
  so5 { so5Fixture(slug: $slug) { anyGames { id } } }
}
"""

_ODDS_DI_UNA_PARTITA = """
query OddsPartita($id: ID!) {
  anyGame(id: $id) {
    playerGameScores {
      anyPlayer { slug }
      anyPlayerGameStats {
        ... on PlayerGameStats { footballPlayingStatusOdds { starterOddsBasisPoints } }
      }
    }
  }
}
"""


def odds_per_giornata(fixture_slug, worker=6):
    """Map slug -> starter odds (0-1) di TUTTA la giornata, presa dalle sue
    partite invece che giocatore per giocatore.

    Le odds stanno su ogni partita (anyGame.playerGameScores), non solo sul
    giocatore: una query a partita porta le odds di TUTTI i suoi giocatori
    (~76). Una giornata ha ~37 partite, quindi ~37 query in <1s contro le
    centinaia (una a candidato) del percorso vecchio, che sotto rate-limit
    arrivava a 12 minuti. Ritorna {} se le odds non sono ancora uscite.

    ATTENZIONE (verificato 03/08): l'argomento id di anyGame e' ID!, non
    String! -- con String! la query fallisce con 'Type mismatch' e la map
    resta vuota (= tutte le odds mancanti = tutti esclusi in silenzio)."""
    import concurrent.futures
    d = base.graphql_query(_GAMES_DELLA_FIXTURE, {"slug": fixture_slug},
                           operation_name="FixtureGameIds")
    fx = (((d or {}).get('data') or {}).get('so5') or {}).get('so5Fixture') or {}
    ids = [g['id'] for g in (fx.get('anyGames') or []) if g.get('id')]
    if not ids:
        return {}

    def _una(gid):
        try:
            r = base.graphql_query(_ODDS_DI_UNA_PARTITA, {"id": gid}, operation_name="OddsPartita")
        except Exception:
            return {}
        node = ((r or {}).get('data') or {}).get('anyGame') or {}
        out = {}
        for p in (node.get('playerGameScores') or []):
            sl = (p.get('anyPlayer') or {}).get('slug')
            bp = ((p.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
            if sl and bp is not None:
                out[sl] = bp / 10000.0
        return out

    odds = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker) as ex:
        for parziale in ex.map(_una, ids):
            odds.update(parziale)
    log(f"Odds giornata da {len(ids)} partite: {len(odds)} giocatori con odds "
        f"({sum(1 for v in odds.values() if v >= 0.80)} sopra 0.80).")
    return odds


def log(msg):
    print(f"[discovery_fixture] {msg}", flush=True)


def salva_odds_storico(fixture, risultati):
    """Persiste le odds gia' in mano, senza nessuna query in piu'.

    `risultati` e' {slug: (odds, data_partita, l10)} PRIMA del filtro
    MIN_ODDS: si salva tutto, anche chi sta sotto soglia e chi non ha ancora
    odds pubblicate. Tenere solo i sopra-soglia ricostruirebbe lo stesso
    campione troncato che gia' abbiamo (starter odds >= 0.80), dove la
    titolarita' attesa e' quasi costante e il segnale non si puo' misurare.

    Struttura:  {fixture: {slug: [{'t': istante_scarico, 'odds': 0.9,
                                   'partita': data_iso}, ...]}}
    Idempotente: rilanciare la stessa giornata non aggiunge una riga se il
    valore non e' cambiato dall'ultimo scarico (e riscrive quella con lo
    stesso istante). A prova di errore: qualunque problema qui non deve
    fermare la discovery, che e' il lavoro vero.

    NB: il file si rilegge e si riscrive intero a ogni chiamata (una per
    ruolo). Se in futuro due shard girassero in parallelo sulla STESSA
    macchina potrebbero sovrascriversi a vicenda; oggi gli shard sono job
    separati con filesystem separati, quindi non succede."""
    global _RUN_TS
    try:
        if not fixture or not risultati:
            return
        if _RUN_TS is None:
            _RUN_TS = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
        dati = {}
        if os.path.exists(ODDS_STORICO):
            try:
                with open(ODDS_STORICO, encoding='utf-8') as fh:
                    dati = json.load(fh) or {}
            except Exception as e:
                # file corrotto: si riparte da zero ma la copia rotta si tiene
                # da parte, non si butta uno storico che non si puo' rifare
                try:
                    os.replace(ODDS_STORICO, ODDS_STORICO + '.corrotto')
                except Exception:
                    pass
                log(f"  storico odds illeggibile ({e!r}): messo da parte in "
                    f"{os.path.basename(ODDS_STORICO)}.corrotto, riparto da capo")
                dati = {}
        if not isinstance(dati, dict):
            dati = {}
        per_fixture = dati.setdefault(fixture, {})
        nuovi = aggiornati = 0
        for slug, valore in risultati.items():
            odds = valore[0] if isinstance(valore, (tuple, list)) and valore else None
            data = valore[1] if isinstance(valore, (tuple, list)) and len(valore) > 1 else None
            storia = per_fixture.setdefault(slug, [])
            if not isinstance(storia, list):
                storia = per_fixture[slug] = []
            gia = next((r for r in storia if isinstance(r, dict) and r.get('t') == _RUN_TS), None)
            if gia is not None:
                gia['odds'], gia['partita'] = odds, data
                aggiornati += 1
                continue
            ultimo = storia[-1] if storia else None
            if ultimo is not None and ultimo.get('odds') == odds and ultimo.get('partita') == data:
                continue
            storia.append({'t': _RUN_TS, 'odds': odds, 'partita': data})
            nuovi += 1
        os.makedirs(os.path.dirname(ODDS_STORICO), exist_ok=True)
        tmp = ODDS_STORICO + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(dati, fh, ensure_ascii=False)
        os.replace(tmp, ODDS_STORICO)
        log(f"  storico odds: {nuovi} nuove righe, {aggiornati} riscritte, "
            f"{len(per_fixture)} giocatori su {fixture}")
    except Exception as e:
        log(f"  ATTENZIONE: storico odds non salvato ({e!r}) -- la discovery prosegue")


def _resolve_query_with_retry(query, variables, operation_name, extract):
    """Esegue una query CRITICA di bootstrap (gira UNA volta per job, non per
    giocatore) con un piccolo retry -- 29/07, bug reale: un job discovery su
    34 e' fallito per intero perche' l'UNICA chiamata di risoluzione
    giornata ha incrociato un blocco CloudFront transitorio (visto anche sui
    predict, vedi circuit breaker li') e nessun retry la copriva, a
    differenza delle query per-giocatore che ne hanno gia' uno. Qui il costo
    di un retry e' trascurabile (1 sola chiamata per job), quindi nessun
    motivo per non averlo.

    29/07 sera: 3 tentativi da 3s (~20s totali, dentro i 5 retry HTTP interni
    di base.graphql_query) non sono bastati -- un job su 34 e' comunque
    fallito per intero (e con lui l'intera run, perche' predict richiede il
    successo di TUTTI i job discovery) per un blocco CloudFront durato piu'
    a lungo dei ~20s coperti. Portato a 6 tentativi con backoff crescente e
    jitter (5,10,15,20,25s + jitter), ~90s di margine totale -- costo ancora
    trascurabile (1 chiamata per job) rispetto al rischio di uccidere
    l'intera run per un blocco transitorio piu' lungo."""
    delays = (5.0, 10.0, 15.0, 20.0, 25.0)
    for attempt in range(6):
        d = base.graphql_query(query, variables, operation_name=operation_name)
        result = extract(d)
        if result is not None:
            return result, d
        if attempt < 5:
            wait = delays[attempt] + random.uniform(0, 3.0)
            log(f"ATTENZIONE: {operation_name} senza risultato utilizzabile (tentativo {attempt + 1}/6), riprovo tra {wait:.1f}s...")
            time.sleep(wait)
    return None, d


def risolvi_fixture():
    if FIXTURE_SLUG:
        f, _d = _resolve_query_with_retry(
            FIXTURE_BY_SLUG, {"slug": FIXTURE_SLUG}, "FixtureBySlug",
            lambda d: ((d.get('data') or {}).get('so5') or {}).get('so5Fixture'))
        if f:
            return f
        log(f"ATTENZIONE: fixture '{FIXTURE_SLUG}' non trovata.")
    if GAMEWEEK:
        # so5Fixtures non accetta un filtro per gameweek: si prendono le ultime
        # e si sceglie quella giusta lato client.
        nodes, _d = _resolve_query_with_retry(
            FIXTURE_BY_GW, {"first": 30}, "FixtureList",
            lambda d: (((d.get('data') or {}).get('so5') or {}).get('so5Fixtures') or {}).get('nodes') or None)
        nodes = nodes or []
        match = [n for n in nodes if str(n.get('seasonGameWeek')) == str(GAMEWEEK)]
        if match:
            aperte = [n for n in match if n.get('aasmState') == 'opened']
            return (aperte or match)[0]
        disponibili = sorted({str(n.get('seasonGameWeek')) for n in nodes})
        log(f"ATTENZIONE: gameweek {GAMEWEEK} non fra quelle restituite: {disponibili}")
        return None
    # NUOVO (30/07, richiesta esplicita utente): se ne' FIXTURE_SLUG ne'
    # GAMEWEEK sono valorizzati, risolve automaticamente la PROSSIMA
    # giornata -- senza bisogno di indovinare/aggiornare un numero a mano
    # ad ogni run (causa del fallimento "impossibile risolvere la
    # giornata" quando l'input restava vuoto). Se uno dei due campi E'
    # valorizzato, il comportamento sopra resta identico (punta a quella
    # specifica, mai sovrascritto da questo fallback).
    nodes, _d = _resolve_query_with_retry(
        FIXTURE_BY_GW, {"first": 30}, "FixtureList",
        lambda d: (((d.get('data') or {}).get('so5') or {}).get('so5Fixtures') or {}).get('nodes') or None)
    nodes = nodes or []
    if not nodes:
        log("ATTENZIONE: nessuna giornata restituita da Sorare per la risoluzione automatica.")
        return None
    now_iso = datetime.datetime.utcnow().isoformat()
    # "Prossima" = non ancora conclusa (endDate >= adesso), la piu' vicina
    # per data di inizio -- copre sia la giornata IN CORSO (endDate futuro,
    # startDate gia' passato) sia la successiva non ancora iniziata.
    non_concluse = [n for n in nodes if (n.get('endDate') or '') >= now_iso]
    if non_concluse:
        non_concluse.sort(key=lambda n: n.get('startDate') or '')
        # FIX 31/07: prima si prendeva semplicemente la prima non conclusa,
        # cioe' anche una giornata GIA' PARTITA (aasmState 'started'). Per una
        # giornata live le formazioni non si possono piu' inserire, quindi il
        # tool avrebbe prodotto proposte inutilizzabili -- e in silenzio.
        # Emerso col cambio stagione del 31/07 (la giornata in corso e' passata
        # da "96" a "1" e ha iniziato a giocarsi mentre lavoravamo): fino a
        # quel momento le run capitavano sempre a giornata ancora aperta e il
        # caso non si era mai presentato. Ora si preferisce una giornata
        # 'opened' (accetta formazioni); se non ce n'e' nessuna si ripiega
        # sulla prima non conclusa come prima, dicendolo nel log.
        aperte = [n for n in non_concluse if n.get('aasmState') == 'opened']
        if aperte:
            scelta = aperte[0]
            log(f"GAMEWEEK/FIXTURE_SLUG non impostati: risolta automaticamente la prossima "
                f"giornata APERTA (gameweek {scelta.get('seasonGameWeek')}, "
                f"{scelta.get('slug')}).")
            return scelta
        scelta = non_concluse[0]
        log(f"GAMEWEEK/FIXTURE_SLUG non impostati: nessuna giornata 'opened' disponibile, "
            f"uso la prima non conclusa (gameweek {scelta.get('seasonGameWeek')}, stato "
            f"{scelta.get('aasmState')}) -- se e' gia' partita le formazioni potrebbero "
            f"non essere piu' inseribili.")
        return scelta
    # Fallback estremo (nessuna delle 30 restituite e' ancora aperta/futura,
    # improbabile mafunziona -- possibile solo se so5Fixtures(first: 30)
    # ritorna solo giornate passate): prende comunque la piu' recente invece
    # di fallire, con log ben visibile per non farlo passare inosservato.
    nodes.sort(key=lambda n: n.get('startDate') or '')
    scelta = nodes[-1]
    log(f"ATTENZIONE: nessuna giornata futura trovata fra le 30 restituite -- "
        f"uso la piu' recente disponibile (gameweek {scelta.get('seasonGameWeek')}) "
        f"come fallback, verificarla.")
    return scelta



def main():
    fx = risolvi_fixture()
    if not fx:
        log("ERRORE: impossibile risolvere la giornata. Imposta GAMEWEEK o FIXTURE_SLUG.")
        return 1
    inizio = (fx.get('startDate') or '')[:19]
    fine = (fx.get('endDate') or '')[:19]
    log(f"Giornata: {fx.get('slug')} (gameweek {fx.get('seasonGameWeek')}, "
        f"stato {fx.get('aasmState')}) dal {inizio} al {fine}")

    # Squadre che giocano in questa giornata
    dg = base.graphql_query(FIXTURE_GAMES, {"slug": fx.get('slug')},
                            operation_name="FixtureGames")
    games = (((dg.get('data') or {}).get('so5') or {})
             .get('so5Fixture') or {}).get('anyGames') or []
    squadre_in_campo = set()
    for g in games:
        for lato in ('homeTeam', 'awayTeam'):
            sl = (g.get(lato) or {}).get('slug')
            if sl:
                squadre_in_campo.add(sl)
    log(f"Partite nella giornata: {len(games)} | squadre in campo: {len(squadre_in_campo)}")
    if not squadre_in_campo:
        log("ERRORE: nessuna squadra ricavata dalla fixture.")
        return 1

    uuid = base.get_user_uuid(base.USER_SLUG)
    if not uuid:
        log("ERRORE: uuid utente non ottenuto.")
        return 1
    # NB: active_competitions NON accetta lo slug della fixture (provato: 0 hit),
    # accetta slug di competizione tipo 'mlspa'. Finche' non sono noti tutti, si
    # scarica UNA volta per ruolo (4 scansioni invece di 80) e si screma con le
    # odds in BATCH -- vedi odds_batch(). Il costo dominante non era la
    # scansione delle carte ma le ~2000 query odds una per giocatore.
    advanced = (f"user.id:{uuid} AND sport:football "
                f"AND NOT sealed=1 AND NOT rarity:custom_series")

    per_lega_ruolo = defaultdict(lambda: defaultdict(set))
    nomi_per_lega_ruolo = defaultdict(lambda: defaultdict(dict))
    counts_per_lega_ruolo = defaultdict(lambda: defaultdict(dict))
    esclusi_odds = 0
    esclusi_finestra = 0
    tot_carte = 0

    for position, role in ROLE_BY_POSITION.items():
        visti = set()
        u23_di = {}
        power_di = {}
        club_di = {}  # slug -> club attuale (activeClub), vedi sotto
        # Copie reali possedute per slug (28/07 sera, bug reale trovato
        # dall'utente: prima si assumeva SEMPRE 1 copia in_season a
        # prescindere, quindi un giocatore con 2+ copie (es. Messi, comprato
        # apposta per schierarlo in piu' formazioni In Season) spariva dal
        # pool dopo la prima formazione anche se una seconda copia reale era
        # disponibile). CARDS_QUERY restituisce un hit per OGNI carta
        # posseduta -- basta contarli invece di deduplicare per giocatore.
        copie_di = defaultdict(lambda: {'in_season': 0, 'classic': 0})
        page = 1
        while page <= 50:
            # Retry (28/07, bug reale trovato dall'utente: Zinckernagel perso
            # in silenzio da una run locale -- ripetuto con paginazione pulita
            # lo trovava a pagina 5/21). Una pagina con hits vuoti a META'
            # paginazione (page < nbPages) e' un glitch transitorio, non la
            # fine dei risultati -- prima veniva scambiata per "fine" e tutte
            # le pagine/giocatori successivi sparivano senza alcun errore.
            # Fino a 3 tentativi prima di arrendersi con un errore VISIBILE
            # (mai piu' un troncamento silenzioso).
            for _retry in range(3):
                d = base.graphql_query(CARDS_QUERY, {
                    "userSlug": base.USER_SLUG, "page": page, "pageSize": base.PAGE_SIZE,
                    "advancedFilters": advanced,
                    "refinements": [{"field": "position", "operator": "EQUAL",
                                     "values": [{"stringValue": position}]}],
                }, operation_name="FixtureCards")
                if d.get('errors'):
                    log(f"GraphQL ({position}): {json.dumps(d['errors'])[:300]}")
                    return 2
                s = ((d.get('data') or {}).get('user') or {}).get('searchCards') or {}
                hits = s.get('hits') or []
                nb_pages = s.get('nbPages') or 1
                if hits or page >= nb_pages:
                    break
                log(f"ATTENZIONE ({position}): pagina {page}/{nb_pages} vuota ma non "
                    f"dovrebbe esserlo -- probabile glitch transitorio, riprovo "
                    f"(tentativo {_retry + 1}/3).")
                time.sleep(1.0)
            else:
                log(f"ERRORE ({position}): pagina {page}/{nb_pages} resta vuota dopo 3 "
                    f"tentativi -- interrotto per non troncare la discovery in silenzio "
                    f"(prima questo caso veniva scambiato per fine paginazione).")
                return 2
            if page == 1:
                log(f"{position}: {s.get('nbHits')} carte ELEGGIBILI per la giornata "
                    f"(filtro lato server, non scaricate tutte le possedute)")
            if not hits:
                break
            for h in hits:
                p = h.get('anyPlayer') or {}
                club = p.get('activeClub') or {}
                if not p.get('slug'):
                    continue
                # PRE-FILTRO decisivo: se il club non gioca in questa giornata,
                # non serve nemmeno chiedere le starter odds. E' questo che
                # abbatte i tempi: da ~2000 interrogazioni a poche decine.
                if club.get('slug') not in squadre_in_campo:
                    continue
                visti.add((p['slug'], (club.get('domesticLeague') or {}).get('slug'),
                           p.get('displayName') or ''))
                # Club ATTUALE secondo Sorare (01/08). Dato gia' in mano qui,
                # nessuna query in piu'. A valle la squadra viene dedotta dalle
                # ultime partite giocate, che sbaglia su chi si e' appena
                # trasferito e non ha ancora esordito.
                if club.get('slug'):
                    club_di[p['slug']] = club['slug']
                if h.get('inSeasonEligible'):
                    copie_di[p['slug']]['in_season'] += 1
                else:
                    copie_di[p['slug']]['classic'] += 1
                # u23Eligible vive sulla CARTA (28/07, confermato dall'utente via
                # DevTools -- il flag Sorare, non un calcolo nostro su birthDay:
                # un 24enne puo' restare flaggato true se ha compiuto gli anni a
                # stagione iniziata), gia' nella stessa CARDS_QUERY -- zero query
                # in piu'. OR fra le carte dello stesso giocatore: basta che una
                # sia flaggata per considerarlo eleggibile.
                if h.get('u23Eligible'):
                    u23_di[p['slug']] = True
                # Bonus xp/collezione/stagione (28/07, richiesta esplicita
                # utente): vive sulla CARTA, stessa query di u23Eligible, zero
                # costo in piu'. Season/collection/xp contano SOLO in In
                # Season/All Stars (7 e U23), MAI nelle Arene (confermato
                # dall'utente: nelle Arene tutti i bonus sono a 0, solo il
                # capitano ha il suo +20% fisso) -- quella distinzione si
                # applica a valle nello score, qui si salva il dato grezzo.
                # Se il giocatore ha piu' carte possedute con bonus diversi,
                # tiene quella col bonus TOTALE piu' alto (confermato
                # dall'utente: ha senso prendere la migliore disponibile).
                pb = h.get('powerBreakdown') or {}
                if pb or h.get('xp') is not None:
                    candidato = {
                        'xp': h.get('xp'),
                        'season_bp': pb.get('seasonBasisPoints'),
                        'collection_bp': pb.get('collectionBasisPoints'),
                        'xp_bp': pb.get('xpBasisPoints'),
                        'scarcity_bp': pb.get('scarcityBasisPoints'),
                        'special_edition_bp': pb.get('specialEditionCardsBasisPoints'),
                        'active_clubs_bp': pb.get('activeClubsBasisPoints'),
                        'nationality_bp': pb.get('nationalityBasisPoints'),
                        'positions_bp': pb.get('positionsBasisPoints'),
                    }
                    tot_candidato = sum(v or 0 for k, v in candidato.items() if k.endswith('_bp'))
                    tot_attuale = sum(v or 0 for k, v in (power_di.get(p['slug']) or {}).items()
                                      if k.endswith('_bp'))
                    if p['slug'] not in power_di or tot_candidato > tot_attuale:
                        power_di[p['slug']] = candidato
            if page >= (s.get('nbPages') or 1):
                break
            page += 1
            time.sleep(0.25)

        tot_carte += len(visti)
        lega_di = {slug: lega for slug, lega, _nome in visti}
        nome_di = {slug: nome for slug, _lega, nome in visti if nome}
        elenco = sorted(lega_di)
        if _WANTED_DIRNAMES is not None:
            # Filtra PRIMA di interrogare odds+L10 (il vero costo): tiene solo
            # gli slug la cui lega di destinazione ricade nella meta' voluta.
            elenco = [sl for sl in elenco
                      if (LEAGUE_DIR.get(lega_di[sl]) if lega_di[sl] else 'senza_lega') in _WANTED_DIRNAMES]
        if HEAVY_LEAGUE_SHARD is not None:
            # Ulteriore sotto-shard della lega pesante isolata (mls/kleague,
            # vedi HEAVY_LEAGUE_SHARD sopra): split deterministico per
            # indice, stesso criterio degli altri shard.
            _hidx, _hn = HEAVY_LEAGUE_SHARD
            elenco = [sl for i, sl in enumerate(elenco) if i % _hn == _hidx]
        log(f"  {position}: {len(elenco)} giocatori di squadre che giocano "
            f"(su {s.get('nbHits')} carte possedute) -> interrogo le odds")
        # odds + L10 in UNA chiamata per giocatore (28/07, vedi
        # odds_e_l10_singola) invece di due passaggi separati -- dimezza il
        # numero di round-trip verso Sorare rispetto a prima, stesso dato.
        risultati = {}
        for sl in elenco:
            risultati[sl] = odds_e_l10_singola(sl, inizio, fine)
            time.sleep(ODDS_L10_SLEEP)
        # le odds si salvano QUI, prima del filtro MIN_ODDS sotto: sono il
        # valore vivo pre-deadline, l'unico non contaminato (vedi ODDS_STORICO)
        salva_odds_storico(fx.get('slug'), risultati)
        for slug in elenco:
            lega = lega_di[slug]
            odds, data, l10 = risultati.get(slug, (None, None, None))
            if data is None:
                esclusi_finestra += 1
                continue
            # Odds assenti (partita troppo lontana, Sorare non le ha ancora
            # pubblicate -- escono a ~24-48h dal match): con una soglia ATTIVA
            # (>0) escludono per sicurezza (non sappiamo se giochera'); con
            # soglia 0 (nessun filtro richiesto) restano INCLUSI, coerente con
            # la regola gia' corretta una volta in questa pipeline (sez. 28.B
            # del riassunto: "senza soglia il comportamento permissivo resta")
            # -- riscoperta oggi perche' qui il controllo era regredito a
            # escludere SEMPRE quando odds is None, ignorando MIN_ODDS.
            if odds is None:
                if MIN_ODDS > 0:
                    esclusi_odds += 1
                    continue
            elif odds < MIN_ODDS:
                esclusi_odds += 1
                continue
            if lega:
                dirname = LEAGUE_DIR.get(lega)
                if not dirname:
                    log(f"  lega senza pipeline: {lega} (giocatore {slug}) -- ignorato")
                    continue
            else:
                # Nessun domesticLeague: dirottato sulla pipeline dedicata
                # formazione_senza_lega (filtro invertito, gia' esistente).
                dirname = 'senza_lega'
            per_lega_ruolo[dirname][role].add(slug)
            if nome_di.get(slug):
                nomi_per_lega_ruolo[dirname][role][slug] = nome_di[slug]
            # L10 (28/07) gia' ottenuta assieme alle odds nella stessa
            # chiamata sopra. Copie possedute (28/07 sera, bug reale
            # -- vedi copie_di sopra): ora CONTATE per davvero dagli hit di
            # CARDS_QUERY, non piu' assunte fisse a 1. Fallback a 1 copia
            # in_season solo se per qualche motivo lo slug non risulta in
            # copie_di (non dovrebbe succedere, e' popolato per lo stesso
            # slug qui sopra nello stesso ciclo).
            entry = dict(copie_di.get(slug) or {'in_season': 1, 'classic': 0})
            if l10 is not None:
                entry['l10'] = l10
            # starterOdds PERSISTITE (31/07, richiesta esplicita utente): fin
            # qui le odds servivano solo a filtrare e poi venivano buttate,
            # quindi a valle nessuno sapeva PIU' se un candidato fosse un
            # titolare all'80% o un dubbio al 70%. Servono al tie-break fra
            # giocatori con punteggio quasi identico (vedi PREFERENZA_ODDS_*
            # in build_formazione_globale.py). Nessuna query in piu': il dato
            # e' gia' in mano qui, viene solo salvato.
            if odds is not None:
                entry['starter_odds'] = odds
            if u23_di.get(slug):
                entry['u23'] = True
            if power_di.get(slug):
                entry['power'] = power_di[slug]
            if club_di.get(slug):
                entry['club'] = club_di[slug]
            counts_per_lega_ruolo[dirname][role][slug] = entry

    log(f"\nGiocatori eleggibili esaminati: {tot_carte} | esclusi: "
        f"{esclusi_finestra} senza partita nella giornata, {esclusi_odds} "
        f"sotto soglia o senza odds (soglia {MIN_ODDS:.0%})")

    scritti = {}
    for lega, ruoli in sorted(per_lega_ruolo.items()):
        for role, slugs in sorted(ruoli.items()):
            outdir = os.path.join(f'formazione_{lega}', 'output', f'{lega}_{role}_discovery')
            os.makedirs(outdir, exist_ok=True)
            with open(os.path.join(outdir, 'player_slugs.json'), 'w', encoding='utf-8') as f:
                json.dump(sorted(slugs), f, ensure_ascii=False)
            # displayName reale Sorare (28/07, richiesta esplicita utente: lo
            # slug a volte si allontana troppo dal nome per essere riconosciuto
            # a colpo d'occhio) -- gia' presente in CARDS_QUERY, nessuna query
            # in piu'. Se manca per un giocatore, il renderer ripiega sullo
            # slug title-case come faceva prima.
            nomi = nomi_per_lega_ruolo.get(lega, {}).get(role, {})
            with open(os.path.join(outdir, 'player_names.json'), 'w', encoding='utf-8') as f:
                json.dump(nomi, f, ensure_ascii=False)
            # L10 (28/07): sovrascrive il player_card_counts.json esistente
            # con i soli sopravvissuti di QUESTA giornata (le vecchie voci di
            # altri giocatori non piu' candidati non servono e verrebbero
            # comunque ignorate da CardPool, che legge solo gli slug dei
            # consigli prodotti in questa run).
            counts = counts_per_lega_ruolo.get(lega, {}).get(role, {})
            with open(os.path.join(outdir, 'player_card_counts.json'), 'w', encoding='utf-8') as f:
                json.dump(counts, f, ensure_ascii=False)
            scritti.setdefault(lega, {})[role] = sorted(slugs)

    print("\n" + "=" * 78)
    print("LEGHE DA PROCESSARE PER QUESTA GIORNATA")
    print("=" * 78)
    for lega, ruoli in sorted(scritti.items()):
        tot = sum(len(v) for v in ruoli.values())
        det = " ".join(f"{r}:{len(v)}" for r, v in sorted(ruoli.items()))
        print(f"  {lega:<16}{tot:>4} giocatori   ({det})")
    if not scritti:
        print("  nessuna: nessun giocatore posseduto e' titolare probabile in questa giornata")

    # Sharding del job 'predict' per le leghe piu' numerose (28/07, richiesta
    # esplicita utente): mls/kleague hanno spesso decine di giocatori per
    # ruolo elaborati IN SEQUENZA in un solo job (un TARGET_SLUG alla volta),
    # mentre le altre leghe (1-2 giocatori tipici) finiscono in fretta --
    # collo di bottiglia sul tempo totale. Ogni combinazione lega/ruolo di
    # queste leghe viene sdoppiata in PREDICT_SHARD_N sotto-job paralleli
    # (stessa lega/ruolo, quota diversa), che si dividono la lista di slug.
    # Le altre leghe restano un solo job (comportamento INVARIATO). Il
    # consiglio finale (aggregazione di TUTTI gli slug del ruolo) si genera
    # in un job separato 'consiglio', dopo che TUTTI gli shard di 'predict'
    # sono completati -- vedi formazione_giornata.yml.
    # 29/07 (sera): generalizzato da {'mls','kleague'} a TUTTE le leghe --
    # con le stagioni ormai avviate, altre leghe (Belgio/Olanda/Germania2/
    # Giappone, ecc.) hanno accumulato altrettanti candidati per ruolo e
    # pagavano lo stesso collo di bottiglia (un job DEF da 40+ giocatori in
    # sequenza, 10-15 minuti, mai sminuzzato). La soglia PREDICT_SHARD_
    # TARGET_SIZE=25 sotto fa gia' da filtro naturale: le leghe piccole
    # restano 1 solo job (shard_n=1, comportamento INVARIATO), solo quelle
    # davvero affollate ne prendono 2+.
    PREDICT_SHARD_LEAGUES = None  # None = si applica a tutte le leghe
    # 29/07: PREDICT_SHARD_N fisso (prima 2, poi 4) si e' rivelato sbagliato
    # in entrambe le direzioni. A 2 shard il ruolo piu' affollato (DEF, ~95
    # giocatori/lega) restava a ~48 giocatori/shard, ~6m30s sul percorso
    # critico. Alzato a 4 SEMBRAVA la mossa giusta (~24 giocatori/shard) ma
    # ha PEGGIORATO i tempi: il vero limite (vedi RIASSUNTO sez. 30, gia'
    # scoperto una volta) e' il tetto di ~20 job CONCORRENTI dell'account,
    # non max-parallel del workflow (77) -- con 56 job predict totali invece
    # di 40, i job in piu' si mettevano semplicemente in coda (spread fra
    # primo e ultimo avvio passato da 161s a oltre 4 minuti), nessun
    # guadagno reale. Sharding ora ADATTIVO: una quota ogni ~20 giocatori
    # (non un N fisso per ogni ruolo) -- i ruoli piccoli (GK/FWD, 30-55
    # giocatori) restano 1-3 shard invece di sempre 4, i ruoli grandi
    # (DEF/MID, 70-95) ne prendono comunque abbastanza da stare sotto il
    # tempo per shard, minimizzando il conteggio TOTALE di job predict.
    # ABBASSATO (29/07 sera) da 25 a 15: verificato su run reale che FWD in
    # particolare e' diventato piu' lento per giocatore (opponent_strength.py
    # scansiona due cartelle cache per giocatore FWD invece di una, e le
    # cartelle cache sono cresciute a 200+ file per le leghe piu' vecchie) --
    # una soglia piu' bassa sminuzza meglio i job pesanti, indipendentemente
    # dalla causa esatta del rallentamento per giocatore.
    PREDICT_SHARD_TARGET_SIZE = 15
    matrice = []
    for lg, ruoli in sorted(scritti.items()):
        for r in sorted(ruoli):
            if PREDICT_SHARD_LEAGUES is None or lg in PREDICT_SHARD_LEAGUES:
                n_players = len(ruoli[r])
                shard_n = max(1, -(-n_players // PREDICT_SHARD_TARGET_SIZE))
                if shard_n <= 1:
                    matrice.append({"league": lg, "role": r})
                else:
                    for i in range(shard_n):
                        matrice.append({"league": lg, "role": r, "shard": f"{i}:{shard_n}"})
            else:
                matrice.append({"league": lg, "role": r})
    print("\nMATRICE_JSON=" + json.dumps(matrice, separators=(',', ':')))
    gh_out = os.environ.get('GITHUB_OUTPUT')
    if gh_out:
        with open(gh_out, 'a', encoding='utf-8') as f:
            f.write("matrice=" + json.dumps(matrice, separators=(',', ':')) + "\n")
            f.write("fixture=" + (fx.get('slug') or '') + "\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
