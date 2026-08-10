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

# EXTEND_ODDS_060_070 (10/08/2026, richiesta esplicita utente): filone
# "pool suppletivo" nel generatore (solo Arena Beginner/All Stars/U23,
# meccanismo di riserva quando la prima tornata a MIN_ODDS non riempie gli
# slot richiesti). Di default (flag spento) il comportamento e' INVARIATO:
# sotto MIN_ODDS si scarta e basta. Acceso, si tiene ANCHE la fascia
# 0.60-0.70 inclusi (non un range continuo: le starter-odds Sorare escono a
# blocchi da 10, quindi 0.60/0.70 sono gli UNICI due valori possibili sotto
# 0.80 -- niente si perde fissando gli estremi invece di un confronto '<').
# Il generatore (build_formazione_globale.py) e' l'unico a decidere se e
# quando usarli: qui si scrive solo starter_odds come sempre, la riga non e'
# "marcata" in alcun modo speciale -- la separazione primario/suppletivo e'
# tutta a valle, sul valore starter_odds gia' persistito.
EXTEND_ODDS_060_070 = os.environ.get('EXTEND_ODDS_060_070', '0') == '1'
EXTEND_ODDS_BAND = (0.60, 0.70)

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

# --- GRADE G (07/08/2026, DOC_SONNET_G_IN_PRODUZIONE, TAPPA 1) ------------
# projection.grade (A..F) per la GW CORRENTE APERTA, DOPO il filtro starter-
# odds (design gia' deciso con l'utente: si chiede solo per chi potrebbe
# davvero entrare in formazione). Fonte VERIFICATA in analisi_manager/
# grade_snapshot.py: query FootballComposeBenchQuery, campo
# myFilteredBench(...).eligiblePlayerGameScores(...).projection.grade, sulla
# leaderboard della GW aperta -- NON recuperabile a ritroso (leaderboard
# chiusa torna 0 nodi).
#
# TRE leaderboard bulk (stessa formula del test isolato GW3, che ha dato
# 93% di copertura sul pool completo, quasi uniforme): il pool "all_star"
# (arena + non-arena) copre di fatto QUALSIASI lega perche' l'Arena/i All
# Stars accettano carte di qualunque nazionalita'; korea in_season copre la
# competizione dedicata K League. Rarity assunta 'limited' (quella
# osservata nel mazzo dell'utente nel test GW3) -- NON generalizzato ad
# altre rarity, limite noto, vedi report.
#
# PAGINAZIONE OBBLIGATORIA (bug reale trovato dall'utente 07/08 nel test
# isolato): il server la CAPPA A 50 nodi/pagina indipendentemente dal
# pageSize richiesto (hasNextPage=True anche con pageSize=300). Senza
# paginare si prendono solo i "50 piu' popolari" per ruolo per leaderboard
# -> copertura crollata al 32.5% invece del 93% reale. Va SEMPRE paginato
# fino a hasNextPage=False.
GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
FETCH_GRADE = os.environ.get('FETCH_GRADE', '1') == '1'
SORARE_CSRF = os.environ.get('SORARE_CSRF', '')


_grade_session = None


def _grade_http():
    """Sessione HTTP DEDICATA al grade, con il barattolo dei cookie sempre
    vuoto.

    CAUSA VERA DEL BUG DEI '0 NODI' (07/08/2026, misurata):
        bench su sessione pulita              -> 50 nodi
        bench dopo UNA query senza CSRF       ->  0 nodi
    base.graphql_query manda il Cookie ma NON il CSRF; a quelle richieste
    Sorare risponde con un Set-Cookie che assegna un _sorare_session_id
    ANONIMO. curl_cffi lo salva nel barattolo della sessione condivisa e da
    quel momento il cookie del barattolo vince su quello che passiamo a mano
    nell'header: la sessione e' anonima, currentUser diventa null e
    myFilteredBench torna 0 nodi con HTTP 200 e nessun errore GraphQL.

    Su GitHub Actions la discovery esegue decine di query (giornata, partite,
    carte, odds) PRIMA del grade, quindi arrivava al grade sempre con la
    sessione gia' anonima -- ecco perche' li' non ha mai funzionato, mentre in
    locale i test isolati facevano solo la query del bench e riuscivano. Non
    c'entravano ne' l'IP dei runner, ne' gli header di client Web, ne' la
    versione di curl_cffi, ne' la scadenza dei secret: tutte ipotesi provate e
    smentite prima di arrivare alla misura qui sopra."""
    global _grade_session
    if _grade_session is None:
        if getattr(base, '_HAS_CURL_CFFI', False):
            from curl_cffi import requests as _cr
            _grade_session = _cr.Session(impersonate="chrome")
        else:
            import requests as _rq
            _grade_session = _rq.Session()
    _grade_session.cookies.clear()
    return _grade_session


def _headers_client_web():
    """Header di un client Web Sorare legittimo -- gli stessi che manda
    bots/bot_definitivo.py (riga ~1245), che opera autenticato da GitHub
    Actions senza problemi.

    PERCHE' SERVONO (07/08/2026, misurato). Con i soli Cookie + CSRF la
    sessione veniva accettata dal PC dell'utente e RIFIUTATA dai runner
    GitHub: currentUser=None, e quindi myFilteredBench -> 0 nodi con HTTP 200
    e nessun errore GraphQL (indistinguibile da 'leaderboard chiusa', che ci
    ha depistati per giorni). Da casa Sorare e' tollerante, da datacenter
    pretende il set completo: sorare-client/version/build + fingerprint.
    Il bot lo sapeva gia'; la query grade no.

    sorare-version/sorare-build cambiano ad ogni release del sito: stanno nei
    secret SORARE_VERSION/SORARE_BUILD (gia' esistenti nel repo, usati da
    bot_definitivo). I default sono gli ultimi valori visti dal vivo."""
    h = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get(
            'SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if base.COOKIES:
        h['Cookie'] = base.COOKIES
    if SORARE_CSRF:
        h['x-csrf-token'] = SORARE_CSRF
    fp = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')
    if fp:
        h['device_fingerprint'] = fp
    return h
GRADE_BENCH_QUERY = """
query FootballComposeBenchQuery($so5LeaderboardSlug: String!, $filters: BenchFilterInput!, $pageSize: Int, $after: String) {
  so5 {
    so5Leaderboard(slug: $so5LeaderboardSlug) {
      myFilteredBench(filters: $filters, first: $pageSize, after: $after) {
        nodes {
          __typename
          ... on ComposeTeamBenchCard {
            anyPlayer { slug }
            eligiblePlayerGameScores(so5LeaderboardSlug: $so5LeaderboardSlug) {
              projection { grade }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


ESCLUDI_LOCKATE = os.environ.get('ESCLUDI_LOCKATE', '0') == '1'

# LE MIE FORMAZIONI GIA' SCHIERATE (07/08/2026, richiesta dell'utente).
# Problema reale: rilanciando il generatore a giornata iniziata, lui ripescava
# carte gia' impegnate in formazioni BLOCCATE, e quelle formazioni non si
# riuscivano piu' a schierare.
#
# Schema scoperto sondando i messaggi d'errore (l'introspezione e' disabilitata):
#  - il contender e' l'iscrizione a una leaderboard; il suo so5Lineup contiene
#    le so5Appearances, e ogni apparizione porta anyCard.slug -> lo slug della
#    CARTA, non del giocatore. Serve esattamente quello: il vincolo Sorare e'
#    una carta = un uso per giornata, quindi chi possiede 3 carte dello stesso
#    giocatore e ne blocca una puo' ancora schierare le altre due. Escludere
#    per giocatore toglierebbe carte ancora usabili.
#  - canEdit distingue BLOCCATA da modificabile, ed e' lo stesso stato che sul
#    sito mostra o nasconde i tasti "Modifica formazione"/"Cancella squadra".
#    SOLO le canEdit=false vanno escluse: una formazione inviata ma ancora
#    modificabile NON blocca le sue carte (decisione dell'utente).
#
# Verificato sui dati veri della GW3, e i conti tornano a quelli che l'utente
# vedeva a schermo: 4 All Stars da 7 + 4 Under 23 da 7 + 3 arene = 11
# formazioni bloccate, 71 carte; 5 K League modificabili, 25 carte, lasciate
# disponibili. Zero carte in entrambi gli insiemi.
#
# groupType validi (ricavati facendo fallire apposta un valore inventato):
# RARITY, COMPETITION, ARENA, COMPETITION_WITH_ARENA, ARENA_CLASSIC,
# ARENA_IN_SEASON. Se ne leggono piu' d'uno deduplicando per slug del
# contender: COMPETITION_WITH_ARENA da solo bastava sulla GW3, ma se Sorare
# sposta un gruppo non lo voglio perdere in silenzio.
LINEUP_MIEI_QUERY = """
query MieFormazioni($fixture: String!, $groupType: So5LeaderboardGroupType!) {
  so5 {
    so5Fixture(slug: $fixture) {
      so5LeaderboardGroups(groupType: $groupType) {
        displayName
        mySo5LeaderboardContenders {
          slug
          so5Lineup {
            canEdit
            so5Leaderboard { slug }
            so5Appearances { anyCard { slug } }
          }
        }
      }
    }
  }
}
"""

_GRUPPI_LINEUP = ('COMPETITION_WITH_ARENA', 'ARENA_CLASSIC', 'ARENA_IN_SEASON')


def carte_bloccate_live(fixture_slug):
    """Slug delle CARTE impegnate in formazioni BLOCCATE della giornata.

    Ritorna (set_di_slug_carta, dettaglio_per_il_log).
    SOLLEVA un'eccezione se la query fallisce, invece di tornare un insieme
    vuoto: 'non ci sono formazioni bloccate' e 'non sono riuscito a leggerle'
    devono restare distinguibili. Confonderli e' esattamente l'errore che il
    07/08 e' costato una giornata."""
    visti_contender = set()
    carte = set()
    n_bloccate = n_modificabili = n_in_season = 0
    for gt in _GRUPPI_LINEUP:
        r = _grade_http().post(
            base.GRAPHQL_URL,
            json={'query': LINEUP_MIEI_QUERY,
                  'variables': {'fixture': fixture_slug, 'groupType': gt},
                  'operationName': 'MieFormazioni'},
            headers=_headers_client_web(), timeout=30)
        d = r.json()
        if d.get('errors'):
            raise RuntimeError(f"formazioni schierate ({gt}): {str(d['errors'])[:200]}")
        gruppi = (((d.get('data') or {}).get('so5') or {})
                  .get('so5Fixture') or {}).get('so5LeaderboardGroups') or []
        for g in gruppi:
            for c in (g.get('mySo5LeaderboardContenders') or []):
                if c.get('slug') in visti_contender:
                    continue
                visti_contender.add(c.get('slug'))
                lineup = c.get('so5Lineup') or {}
                if not lineup:
                    continue
                lb = (lineup.get('so5Leaderboard') or {}).get('slug') or ''
                if lineup.get('canEdit'):
                    # MODIFICABILE. Di regola le sue carte restano LIBERE, ma
                    # non se la competizione e' IN SEASON (07/08, richiesta
                    # dell'utente dopo il primo uso sul campo): quelle
                    # formazioni non le smonta, quindi le carte sono impegnate
                    # nei fatti anche se Sorare lascia ancora il tasto
                    # Modifica. Riconosciute dallo slug della leaderboard, che
                    # contiene 'in_season' (verificato: le due K League
                    # modificabili della GW3 sono
                    # ...-in_season_korea_limited_pvp e ..._pve, mentre tutte
                    # le bloccate non lo contengono).
                    if 'in_season' not in lb:
                        n_modificabili += 1
                        continue
                    n_in_season += 1
                else:
                    n_bloccate += 1
                for a in (lineup.get('so5Appearances') or []):
                    cs = (a.get('anyCard') or {}).get('slug')
                    if cs:
                        carte.add(cs)
    return carte, {'bloccate': n_bloccate, 'in_season_modificabili': n_in_season,
                   'modificabili_libere': n_modificabili}


def _grade_bench_page(so5_slug, position, after):
    variables = {
        "filters": {
            "query": "", "rarities": [], "includeUsed": True, "includeNoGame": False,
            "inSeasonEligible": False, "includeUnavailablePlayers": True,
            "lastTenPlayedSo5AverageScore": {"max": 100}, "positions": [position],
            "selectedObjectIds": [], "sortType": {"type": "POPULAR_STARTERS", "direction": "DESC"},
            "teamMode": "ALL"
        },
        "pageSize": 50, "so5LeaderboardSlug": so5_slug, "after": after,
    }
    headers = _headers_client_web()
    # 429: 6 tentativi con attesa 2,4,8,16,32,60s invece di 4 con 1,2,4,8.
    # Misurato sulla run 31190547919: 4-8 risposte 429 per job, e uno shard si
    # e' fermato a 200 slug con grade invece di 877 perche' finiti i tentativi
    # la paginazione si interrompeva a meta' -- e si interrompeva IN SILENZIO,
    # con un risultato parziale indistinguibile da uno completo. Ora se i
    # tentativi si esauriscono lo si scrive nel log.
    backoff = 2.0
    for attempt in range(6):
        try:
            r = _grade_http().post(base.GRAPHQL_URL,
                                   json={'query': GRADE_BENCH_QUERY, 'variables': variables},
                                   headers=headers, timeout=20)
            if r.status_code == 429:
                attesa = min(backoff, 60.0)
                if attempt >= 2:
                    log(f"  [grade] 429 su {so5_slug}/{position}, tentativo "
                        f"{attempt + 1}/6, attendo {attesa:.0f}s")
                time.sleep(attesa)
                backoff *= 2
                continue
            d = r.json()
        except Exception as e:
            log(f"  [grade] eccezione {so5_slug}/{position}: {e}")
            time.sleep(backoff)
            backoff *= 2
            continue
        if d.get('errors'):
            log(f"  [grade] GraphQL errors {so5_slug}/{position}: {str(d['errors'])[:200]}")
            return [], False
        lb = ((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard')
        if not lb:
            return [], False
        b = (lb.get('myFilteredBench') or {})
        nodes = b.get('nodes') or []
        pinfo = b.get('pageInfo') or {}
        if not nodes and after is None:
            # DEBUG (07/08/2026 notte): la risposta grezza non era mai stata
            # ispezionata su GH Actions, solo il conteggio nodi riassunto dal
            # nostro stesso log -- vietato dedurre senza vedere il dato
            # grezzo. Stampa status/header/body reali una volta per
            # leaderboard/posizione quando torna vuota, per vedere SE e COSA
            # sta filtrando (WAF/cache/risposta genuina).
            hdrs_utili = {k: v for k, v in r.headers.items()
                          if k.lower() in ('cf-ray', 'cf-cache-status', 'server',
                                           'content-type', 'x-request-id')}
            log(f"  [grade][DEBUG] {so5_slug}/{position}: HTTP {r.status_code}, "
                f"headers={hdrs_utili}, body[:500]={r.text[:500]!r}")
        return nodes, pinfo.get('hasNextPage'), pinfo.get('endCursor')
    log(f"  [grade] ATTENZIONE: {so5_slug}/{position} ha esaurito i 6 tentativi "
        f"(429 o eccezioni). La paginazione si ferma qui: il grade di questa "
        f"leaderboard/ruolo sara' PARZIALE, non completo.")
    return [], False, None


def fetch_grade_live(fixture_slug):
    """Grade (A..F) per slug giocatore, sulla GW aperta 'fixture_slug'.
    Ritorna (grade_map, copertura_per_leaderboard) -- copertura_per_leaderboard
    e' {leaderboard_slug: n_nodi_bench} per far vedere se una leaderboard e'
    tornata vuota (leaderboard chiusa/slug sbagliato -> possibile GW gia'
    chiusa, da NON ignorare in silenzio)."""
    if not FETCH_GRADE:
        log("[grade] FETCH_GRADE=0, salto il fetch (G restera' in fallback z=0).")
        return {}, {}
    # ARTIFACT DELLA STESSA RUN, NON UNA CACHE (07/08/2026).
    # Il job 'grade' fa la fetch UNA VOLTA e la passa qui come artifact. Prima
    # ognuno dei 20 shard la rifaceva per conto suo: ~4.800 richieste identiche
    # a run, con 4-8 risposte 429 per job e paginazioni troncate (uno shard si
    # e' fermato a 200 slug invece di 877). Il file nasce e muore dentro la
    # run, non e' committato e non puo' invecchiare; se la giornata dentro non
    # e' quella che stiamo processando lo si scarta, perche' un artifact di
    # un'altra giornata sarebbe il fallback silenzioso da evitare.
    p = 'pool_gw.json'
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            if d.get('fixture') != fixture_slug:
                log(f"[grade] ATTENZIONE: {p} e' della giornata "
                    f"{d.get('fixture')!r}, non {fixture_slug!r}: lo IGNORO e "
                    f"faccio la fetch diretta.")
            else:
                gm = d.get('grade_map') or {}
                log(f"[grade] da artifact {p}: {len(gm)} slug con grade "
                    f"(fetch fatta una sola volta dal job 'grade' di questa run).")
                return gm, d.get('copertura') or {}
        except Exception as e:
            log(f"[grade] {p} illeggibile ({e}): faccio la fetch diretta.")
    if not SORARE_CSRF:
        log("[grade] SORARE_CSRF assente: la query bench potrebbe fallire o "
            "tornare vuota senza CSRF. Procedo comunque, verifica copertura.")
    # PROBE AUTENTICAZIONE (07/08/2026 notte). myFilteredBench e' una query
    # "my": senza sessione autenticata risponde HTTP 200 + nodes:[] SENZA
    # errori GraphQL -- indistinguibile da "leaderboard chiusa" se si guarda
    # solo il conteggio. Le carte possedute invece si leggono con
    # user(slug:) (query PUBBLICA, riga ~394), quindi funzionano anche a
    # cookie morto: non sono una prova che l'auth regga. Qui si chiede
    # currentUser, che e' null se e solo se la sessione non autentica.
    # La probe RIPROVA sui 429 (difetto trovato il 07/08 sulla run
    # 31190547919: senza retry un rate limit veniva stampato come
    # "SESSIONE NON AUTENTICATA", cioe' una diagnosi sbagliata proprio nella
    # riga che serve a diagnosticare). Rate limit e sessione morta sono due
    # cose diverse e vanno dette con parole diverse.
    _probe_h = _headers_client_web()
    _cu, _rate_limited = None, False
    _bk = 2.0
    for _t in range(5):
        try:
            _pr = _grade_http().post(
                base.GRAPHQL_URL, json={'query': '{ currentUser { slug } }'},
                headers=_probe_h, timeout=20)
            if _pr.status_code == 429:
                _rate_limited = True
                time.sleep(min(_bk, 60.0))
                _bk *= 2
                continue
            _rate_limited = False
            _pd = _pr.json()
            _cu = ((_pd.get('data') or {}).get('currentUser') or {}).get('slug')
            break
        except Exception as _e:
            log(f"[grade] PROBE auth, tentativo {_t + 1}/5 fallito: {_e}")
            time.sleep(min(_bk, 60.0))
            _bk *= 2
    log(f"[grade] PROBE auth: currentUser={_cu!r} "
        f"(len cookie={len(base.COOKIES)}, len csrf={len(SORARE_CSRF)})")
    if _rate_limited:
        log("[grade] PROBE inconcludente: 429 su tutti i tentativi. E' un "
            "RATE LIMIT, non una sessione morta: non trarre conclusioni "
            "sull'autenticazione da questa riga.")
    elif not _cu:
        log("[grade] SESSIONE NON AUTENTICATA: currentUser e' null. Il "
            "bench tornera' 0 nodi per questo motivo, NON perche' la GW e' "
            "chiusa. Rigenerare SORARE_COOKIE/SORARE_CSRF nei secret.")
    leaderboards = [
        f'{fixture_slug}-seasonal-all_star-all_seasons_all_star_arena_limited',
        f'{fixture_slug}-seasonal-all_star-all_seasons_all_star_limited',
        f'{fixture_slug}-seasonal-korea-in_season_korea_limited_pvp',
    ]
    grade_map = {}
    copertura = {}
    for lb_slug in leaderboards:
        n_totale = 0
        for pos in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
            after = None
            while True:
                nodes, has_next, *rest = _grade_bench_page(lb_slug, pos, after)
                n_totale += len(nodes)
                for n in nodes:
                    pslug = (n.get('anyPlayer') or {}).get('slug')
                    if not pslug:
                        continue
                    for sc in n.get('eligiblePlayerGameScores') or []:
                        g = (sc.get('projection') or {}).get('grade')
                        if g and pslug not in grade_map:
                            grade_map[pslug] = g
                if not has_next:
                    break
                after = rest[0] if rest else None
                if after is None:
                    break
                time.sleep(0.2)
        copertura[lb_slug] = n_totale
        log(f"[grade] {lb_slug}: {n_totale} nodi bench")
        if n_totale == 0:
            log(f"[grade] ATTENZIONE: {lb_slug} torna 0 nodi -- la GW potrebbe "
                f"essere gia' chiusa o lo slug leaderboard e' sbagliato. NON "
                f"fermo la discovery (le odds restano valide), ma il grade da "
                f"questa leaderboard sara' assente per tutti.")
    log(f"[grade] TOTALE slug distinti con grade: {len(grade_map)}")
    return grade_map, copertura

ROLE_BY_POSITION = {'Goalkeeper': 'gk', 'Defender': 'def',
                    'Midfielder': 'mid', 'Forward': 'fwd'}

# L10 DELLA CARTA, NON DEL GIOCATORE (08/08/2026) -- causa vera delle arene
# che sforavano il cap.
#
# COSA SUCCEDEVA: si e' sempre letta l'L10 da `anyPlayer.averageScore(...)`,
# cioe' quella del GIOCATORE. Sorare invece capa sulla CARTA
# (`ComposeTeamBenchCard.averageScore(...)`), che pesa i punteggi col ruolo
# con cui la carta e' stata EMESSA. E' lo stesso D7 gia' noto sul ruolo: se
# Sorare cambia ruolo a un giocatore, le carte gia' emesse tengono il ruolo
# vecchio, e la loro L10 resta calcolata su quello.
#
# MISURATO su 400 carte vere del mazzo dell'utente (leaderboard all_star
# arena, 08/08):
#   - ruolo carta == ruolo giocatore: 373 carte, 362 identiche (97%),
#     11 diverse e tutte entro +-2 (rumore di arrotondamento);
#   - ruolo carta DIVERSO:             27 carte,  11 identiche,
#     16 DIVERSE, fino a +-5 punti.
# Casi reali: jeppe-erenbjerg carta Forward / player Midfielder 62 -> 66;
# melle-meulensteen carta Defender 47 -> 52; anders-dreyer carta Midfielder /
# player Forward 66 -> 61. NB: va in ENTRAMBE le direzioni, quindi non si
# aggiusta con un margine di sicurezza sul cap -- serve il campo giusto.
# Verificato anche che il valore NON dipende dalla leaderboard (arena e
# non-arena danno lo stesso numero) e che due carte dello stesso giocatore
# nello stesso ruolo danno lo stesso valore.
CARD_L10_BENCH_QUERY = """
query FootballComposeBenchQuery($so5LeaderboardSlug: String!, $filters: BenchFilterInput!, $pageSize: Int, $after: String) {
  so5 {
    so5Leaderboard(slug: $so5LeaderboardSlug) {
      myFilteredBench(filters: $filters, first: $pageSize, after: $after) {
        nodes {
          ... on ComposeTeamBenchCard {
            position
            anyPlayer { slug }
            cardL10: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def l10_carte_da_bench(fixture_slug, max_pagine=80):
    """Map (slug_giocatore, ruolo) -> L10 DELLA CARTA, per tutto il mazzo.

    Una pagina da 50 carte per richiesta: ~23 richieste per un mazzo da ~1100
    carte, pochi secondi. Usa la sessione dedicata del grade (_grade_http +
    _headers_client_web): e' una query "my", quindi SENZA cookie+CSRF validi
    Sorare risponde 200 con nodes vuoti (sessione anonima, vedi il bug gia'
    documentato in fetch_grade_live) -- in quel caso si ritorna {} e il
    chiamante resta sull'L10 del giocatore, come prima.

    Il ruolo tornato e' gia' nella nostra convenzione (gk/def/mid/fwd) via
    ROLE_BY_POSITION. Se due carte dello stesso giocatore hanno lo stesso
    ruolo ma L10 diverse si tiene la PIU' ALTA: sul cap e' la scelta prudente
    (mai sottostimare cio' che Sorare sommera')."""
    if not base.COOKIES:
        log("[cardL10] nessun SORARE_COOKIE: salto, si usa l'L10 del giocatore.")
        return {}
    lb = f'{fixture_slug}-seasonal-all_star-all_seasons_all_star_arena_limited'
    out = {}
    # UNA PAGINAZIONE PER POSIZIONE, come gia' fa il grade (_grade_bench_page).
    # NON si usa positions: [] sperando che valga "tutte": misurato l'08/08 che
    # con la lista vuota tornano def/mid/fwd ma ZERO portieri (293/240/210/0),
    # cioe' un buco intero e silenzioso -- esattamente il tipo di dato parziale
    # indistinguibile da uno completo gia' pagato col grade.
    for _pos in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
        out.update(_l10_carte_una_posizione(lb, _pos, max_pagine))
    log(f"[cardL10] L10 di CARTA raccolte: {len(out)} coppie (slug,ruolo).")
    return out


def _l10_carte_una_posizione(lb, position, max_pagine):
    """Pagina il bench per UNA posizione. Vedi l10_carte_da_bench."""
    out, after, pagine = {}, None, 0
    while pagine < max_pagine:
        variables = {
            "filters": {
                "query": "", "rarities": [], "includeUsed": True,
                "includeNoGame": False, "inSeasonEligible": False,
                "includeUnavailablePlayers": True, "positions": [position],
                "selectedObjectIds": [],
                "sortType": {"type": "LAST_TEN_PLAYED_SO5_AVERAGE_SCORE",
                             "direction": "DESC"},
                "teamMode": "ALL",
            },
            "pageSize": 50, "so5LeaderboardSlug": lb, "after": after,
        }
        backoff = 2.0
        nodes = pinfo = None
        for tentativo in range(6):
            try:
                r = _grade_http().post(
                    base.GRAPHQL_URL,
                    json={'query': CARD_L10_BENCH_QUERY, 'variables': variables},
                    headers=_headers_client_web(), timeout=20)
                if r.status_code == 429:
                    attesa = min(backoff, 60.0)
                    log(f"  [cardL10] 429 pagina {pagine + 1}, attendo {attesa:.0f}s")
                    time.sleep(attesa)
                    backoff *= 2
                    continue
                d = r.json()
            except Exception as e:
                log(f"  [cardL10] eccezione pagina {pagine + 1}: {e}")
                time.sleep(backoff)
                backoff *= 2
                continue
            if d.get('errors'):
                log(f"  [cardL10] GraphQL errors: {str(d['errors'])[:200]}")
                return out
            b = ((((d.get('data') or {}).get('so5') or {})
                  .get('so5Leaderboard') or {}).get('myFilteredBench') or {})
            nodes, pinfo = b.get('nodes') or [], b.get('pageInfo') or {}
            break
        if nodes is None:
            # Tentativi esauriti: NON si finge che il mazzo finisca qui (un
            # troncamento silenzioso e' il difetto gia' pagato col grade).
            log(f"  [cardL10] ATTENZIONE: pagina {pagine + 1} fallita dopo 6 "
                f"tentativi, la mappa e' PARZIALE ({len(out)} carte finora).")
            return out
        for n in nodes:
            slug = ((n.get('anyPlayer') or {}).get('slug'))
            role = ROLE_BY_POSITION.get(n.get('position'))
            val = n.get('cardL10')
            if not slug or not role or val is None:
                continue
            k = (slug, role)
            if k not in out or val > out[k]:
                out[k] = val
        pagine += 1
        if not pinfo.get('hasNextPage'):
            break
        after = pinfo.get('endCursor')
    log(f"  [cardL10] {position}: {len(out)} carte in {pagine} pagine.")
    return out


_cardl10_cache = {}


def cardl10_condivise(fixture_slug):
    """l10_carte_da_bench una volta sola per processo (i 4 ruoli della stessa
    discovery la riuserebbero identica)."""
    if fixture_slug not in _cardl10_cache:
        _cardl10_cache[fixture_slug] = l10_carte_da_bench(fixture_slug)
    return _cardl10_cache[fixture_slug]

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
    # Aggiunta 10/08: unico club Bolivia della GW4 (football-11-14-aug-2026),
    # trovato scartato come "lega senza pipeline" nella verifica empirica
    # portieri richiesta dall'utente (Carlos Lampe, Bolivar La Paz).
    'primera-division': 'bolivia',
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
          # L10 QUI (07/08/2026): stesso campo di L10_ONLY_QUERY, ma dentro una
          # query che stiamo gia' facendo -- zero richieste in piu'. Prima si
          # chiedeva una per giocatore sopravvissuto (308 a run, a 0.7s l'una).
          lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
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


_odds_giornata_cache = {}


def _odds_giornata_condivise(fixture_slug):
    """Odds di tutta la giornata: dall'artifact della run se c'e', altrimenti
    prese in bulk dalle partite UNA volta sola per processo.

    Tre livelli, dal piu' economico al piu' caro:
      1. pool_gw.json, scritto dal job 'grade' e scaricato come artifact:
         ZERO query, e la fetch e' stata fatta una volta per tutta la run
         invece che una volta per shard;
      2. odds_per_giornata(): ~183 query (una per partita) che coprono TUTTI
         i giocatori, memorizzate qui cosi' i 4 ruoli dello stesso processo
         non le rifanno;
      3. {} -> chi chiama ripiega sulle chiamate per giocatore.
    """
    if fixture_slug in _odds_giornata_cache:
        return _odds_giornata_cache[fixture_slug]
    odds = {}
    p = 'pool_gw.json'
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            if d.get('fixture') == fixture_slug:
                odds = d.get('odds') or {}
                if odds:
                    log(f"[odds] da artifact {p}: {len(odds)} giocatori con odds "
                        f"(nessuna query: fetch fatta una volta sola in questa run).")
            else:
                log(f"[odds] {p} e' della giornata {d.get('fixture')!r}, non "
                    f"{fixture_slug!r}: lo IGNORO.")
        except Exception as e:
            log(f"[odds] {p} illeggibile ({e}).")
    if not odds:
        try:
            odds = odds_per_giornata(fixture_slug) or {}
        except Exception as e:
            log(f"[odds] fetch in bulk fallita ({e}): si ripiega per giocatore.")
            odds = {}
    _odds_giornata_cache[fixture_slug] = odds
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
    # Jitter iniziale (05/08): con max-parallel 20, tutti gli shard sparano la
    # query di risoluzione giornata nello stesso istante -- raffica che ha
    # fatto scattare blocchi CloudFront 403 durati piu' a lungo dei retry
    # (vedi run fallite 03-05/08, sempre sulla stessa query). Disperdendo le
    # 20 chiamate su una finestra di 15s si evita il burst simultaneo, a
    # costo trascurabile (una volta per job).
    time.sleep(random.uniform(0, 15.0))
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

    # Odds di giornata prese subito (10/08/2026): servono anche come fallback
    # nel pre-filtro squadre-in-campo qui sotto, vedi 'club_di'/'odds_giornata'
    # piu' avanti. Zero costo: e' la stessa mappa cachata che il ciclo ruoli
    # richiedera' comunque piu' sotto (_odds_giornata_condivise memoizza per
    # fixture_slug, questa e' solo la prima chiamata a valorizzarla).
    odds_giornata = _odds_giornata_condivise(fx.get('slug'))

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

    # Leghe/ruoli ESAMINATI, anche quelli rimasti senza superstiti (07/08).
    # Serve a svuotare i loro file invece di lasciarli intatti: vedi il
    # commento sul ciclo di scrittura in fondo, e' un bug reale costato due
    # arene (caso pedro-david-gallese-quiroz).
    esaminati_lega_ruolo = set()
    per_lega_ruolo = defaultdict(lambda: defaultdict(set))
    nomi_per_lega_ruolo = defaultdict(lambda: defaultdict(dict))
    counts_per_lega_ruolo = defaultdict(lambda: defaultdict(dict))
    esclusi_odds = 0
    esclusi_finestra = 0
    tot_carte = 0

    # CARTE GIA' BLOCCATE IN ALTRE FORMAZIONI (ESCLUDI_LOCKATE=1).
    # Si legge una volta sola per processo, prima del ciclo sui ruoli. Se la
    # lettura fallisce la run si FERMA: proseguire come se non ci fossero
    # formazioni bloccate rimetterebbe l'utente esattamente nel problema che
    # questa funzione deve evitare, e in silenzio.
    _carte_bloccate = set()
    n_carte_saltate = [0]
    if ESCLUDI_LOCKATE:
        p = 'pool_gw.json'
        letto_da_artifact = False
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as f:
                    _d = json.load(f)
                if _d.get('fixture') == fx.get('slug') and _d.get('carte_bloccate') is not None:
                    _carte_bloccate = set(_d['carte_bloccate'])
                    letto_da_artifact = True
                    log(f"[lockate] da artifact {p}: {len(_carte_bloccate)} carte "
                        f"gia' impegnate in formazioni BLOCCATE, le escludo dal pool.")
            except Exception as e:
                log(f"[lockate] {p} illeggibile ({e}), interrogo Sorare.")
        if not letto_da_artifact:
            _carte_bloccate, _det = carte_bloccate_live(fx.get('slug'))
            log(f"[lockate] {_det['bloccate']} bloccate + "
                f"{_det['in_season_modificabili']} modificabili IN SEASON -> "
                f"{len(_carte_bloccate)} carte escluse dal pool; "
                f"{_det['modificabili_libere']} formazioni modificabili non "
                f"in-season, le loro carte restano DISPONIBILI.")
        if not _carte_bloccate:
            log("[lockate] ATTENZIONE: nessuna carta bloccata trovata. Se avevi "
                "gia' schierato formazioni non modificabili, questo e' un "
                "difetto, non una buona notizia: controlla prima di fidarti.")
    else:
        log("[lockate] ESCLUDI_LOCKATE=0: le carte gia' schierate in formazioni "
            "bloccate NON vengono escluse (comportamento storico).")

    for position, role in ROLE_BY_POSITION.items():
        visti = set()
        l10_di = {}   # slug -> L10, arriva gratis dalla CARDS_QUERY
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
                # ESAMINATA: si registra QUI, dove le carte si vedono, non
                # nel ciclo dei sopravvissuti. Errore trovato subito dopo
                # averlo scritto: una lega il cui unico giocatore viene
                # SCARTATO (carta bloccata) non entra mai in 'elenco', quindi
                # non risultava esaminata, quindi i suoi file non venivano
                # svuotati e restavano quelli di ieri. E' esattamente il caso
                # Gallese: le sue due carte venivano scartate correttamente,
                # ma il file di colombia/gk continuava a dichiararne 2.
                _lg = (p.get('activeClub') or {}).get('domesticLeague') or {}
                _dn_pag = LEAGUE_DIR.get(_lg.get('slug')) if _lg.get('slug') else 'senza_lega'
                if _dn_pag:
                    esaminati_lega_ruolo.add((_dn_pag, role))
                # CARTA gia' impegnata in una formazione BLOCCATA: si salta
                # QUESTA carta, non il giocatore. Se ne possiede altre copie
                # libere, quelle continuano a contare normalmente qui sotto
                # (copie_di) e restano schierabili; se erano tutte bloccate il
                # giocatore non entra mai in 'visti' e sparisce dal pool, che
                # e' il comportamento voluto. Attivo solo con ESCLUDI_LOCKATE=1.
                if _carte_bloccate and h.get('slug') in _carte_bloccate:
                    n_carte_saltate[0] += 1
                    continue
                # PRE-FILTRO decisivo: se il club non gioca in questa giornata,
                # non serve nemmeno chiedere le starter odds. E' questo che
                # abbatte i tempi: da ~2000 interrogazioni a poche decine.
                # FALLBACK (10/08/2026, bug reale trovato dall'utente: Jamiro
                # Monteiro spariva dal pool MID nonostante avesse una partita
                # reale l'11/08 con 90% di titolarita'). activeClub e' un dato
                # Sorare che dopo un trasferimento resta stantio per giorni
                # (verificato in diretta: PEC Zwolle, mentre la partita vera e'
                # con NEC Nijmegen). odds_giornata viene dalle partite REALI
                # della giornata (playerGameScores di ogni anyGame), non da
                # activeClub: se il giocatore ci compare sta davvero giocando
                # questa GW anche se il suo club "attuale" secondo Sorare non
                # e' fra quelli in campo. Zero query in piu' (mappa gia' pronta
                # sopra). La lega/club salvati restano quelli di activeClub
                # (stantii in questo caso): a valle in PREDICT c'e' gia' un
                # fallback dedicato (test_def.py, fix 29/07) che ripiega sulla
                # squadra reale della partita quando activeClub non corrisponde.
                if club.get('slug') not in squadre_in_campo and p['slug'] not in odds_giornata:
                    continue
                visti.add((p['slug'], (club.get('domesticLeague') or {}).get('slug'),
                           p.get('displayName') or ''))
                # Club ATTUALE secondo Sorare (01/08). Dato gia' in mano qui,
                # nessuna query in piu'. A valle la squadra viene dedotta dalle
                # ultime partite giocate, che sbaglia su chi si e' appena
                # trasferito e non ha ancora esordito.
                if club.get('slug'):
                    club_di[p['slug']] = club['slug']
                if p.get('lastTenPlayedAvgScore') is not None:
                    l10_di[p['slug']] = p['lastTenPlayedAvgScore']
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
        # ODDS IN BULK, POI L10 SOLO AI SOPRAVVISSUTI (07/08/2026).
        # Prima: una chiamata odds+L10 per OGNI giocatore di squadra in campo,
        # in sequenza con 0.7s di pausa. Misurato sulla run 31190547919: la
        # fase odds prendeva 308-609s per shard, quasi tutto attesa da 429
        # (Retry-After a 152s), perche' 20 shard in parallelo chiedevano
        # centinaia di volte quello che si puo' chiedere una volta sola.
        # Ora: odds di TUTTA la giornata dalle sue partite (odds_per_giornata,
        # ~183 query per l'intera run, non per shard, e in piu' condivise via
        # artifact) e L10 chiesta SOLO a chi supera la soglia -- in uno shard
        # tipico 9 giocatori invece di 57.
        # E' la regola gia' scritta in CLAUDE.md ("valuto se si puo' fare in
        # bulk: odds di tutta la giornata dalle partite invece di una query a
        # giocatore"): la funzione bulk esisteva dal 03/08 ed era gia' usata
        # dallo scouting, ma qui non era mai stata collegata.
        odds_bulk = _odds_giornata_condivise(fx.get('slug'))
        risultati = {}
        if odds_bulk:
            # Presente nella mappa = la partita e' di questa giornata, quindi
            # dentro la finestra per costruzione (la mappa nasce dalle partite
            # della fixture). Assente = odds non pubblicate: stesso esito di
            # prima, escluso se la soglia e' attiva.
            sopravvissuti = [sl for sl in elenco
                             if odds_bulk.get(sl) is not None
                             and (MIN_ODDS <= 0 or odds_bulk[sl] >= MIN_ODDS)]
            log(f"  {position}: odds in bulk -> {len(sopravvissuti)}/{len(elenco)} "
                f"sopra soglia (L10 gia' presa con le carte, zero query)")
            for sl in elenco:
                # data SEMPRE valorizzata: chi e' in 'elenco' ha gia' superato
                # il pre-filtro sulle squadre in campo, quindi la partita in
                # questa giornata ce l'ha per costruzione. Lasciarla a None
                # quando mancano le odds sarebbe una regressione silenziosa:
                # con MIN_ODDS=0 (nessun filtro richiesto) quei giocatori
                # devono restare INCLUSI -- regola gia' corretta una volta in
                # questa pipeline, vedi il commento su MIN_ODDS piu' sotto.
                # Misurato: con data=None diventavano 5 "senza partita", con
                # data valorizzata tornano 0 come nel percorso vecchio.
                risultati[sl] = (odds_bulk.get(sl), inizio, l10_di.get(sl))
        else:
            # Odds di giornata non disponibili (non ancora pubblicate o query
            # a vuoto): si torna al percorso vecchio, giocatore per giocatore.
            log(f"  {position}: odds di giornata non disponibili, "
                f"ripiego sulle chiamate per giocatore")
            for sl in elenco:
                risultati[sl] = odds_e_l10_singola(sl, inizio, fine)
                time.sleep(ODDS_L10_SLEEP)
        # le odds si salvano QUI, prima del filtro MIN_ODDS sotto: sono il
        # valore vivo pre-deadline, l'unico non contaminato (vedi ODDS_STORICO)
        salva_odds_storico(fx.get('slug'), risultati)
        for slug in elenco:
            lega = lega_di[slug]
            # ESAMINATA: si registra PRIMA di ogni filtro (finestra, odds,
            # lega senza pipeline), perche' quello che conta e' "questo job ha
            # guardato questa lega/ruolo", non "qualcuno e' sopravvissuto". Se
            # si registrasse dopo, una lega i cui giocatori vengono tutti
            # scartati resterebbe con i file di ieri -- che e' il bug stesso.
            _dn = LEAGUE_DIR.get(lega) if lega else 'senza_lega'
            if _dn:
                esaminati_lega_ruolo.add((_dn, role))
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
                # Banda suppletiva 0.60-0.70 (vedi EXTEND_ODDS_060_070 sopra):
                # se accesa, chi cade DENTRO la banda non viene scartato qui,
                # resta nel pool con il suo starter_odds vero -- decide il
                # generatore, non la discovery. Sotto 0.60 resta escluso.
                if not (EXTEND_ODDS_060_070 and EXTEND_ODDS_BAND[0] <= odds <= EXTEND_ODDS_BAND[1]):
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
            # L10: prima quella della CARTA per QUESTO ruolo (e' il numero su
            # cui Sorare capa davvero, vedi l10_carte_da_bench), poi come
            # ripiego quella del giocatore presa con le odds. Il ripiego
            # scatta quando manca il cookie, quando la carta non e' nel bench
            # di quella leaderboard, o se la fetch e' andata parziale.
            _card_l10 = cardl10_condivise(fx.get('slug')).get((slug, role))
            if _card_l10 is not None:
                entry['l10'] = _card_l10
            elif l10 is not None:
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
    if ESCLUDI_LOCKATE:
        log(f"[lockate] carte SALTATE perche' gia' in formazioni bloccate: "
            f"{n_carte_saltate[0]} (su {len(_carte_bloccate)} note; le altre "
            f"sono di ruoli/leghe non processati da questo job)")

    # GRADE G (TAPPA 1, DOC_SONNET_G_IN_PRODUZIONE): fetch UNA volta per tutta
    # la run, DOPO il filtro odds (counts_per_lega_ruolo contiene gia' solo i
    # kept_slugs). Scritto nella stessa entry di starter_odds, letto da
    # build_formazione_globale.py via counts.get(slug)['grade'].
    grade_map, grade_copertura = fetch_grade_live(fx.get('slug'))
    n_entry_tot = 0
    n_entry_grade = 0
    copertura_per_lega_ruolo = {}
    for lega, ruoli in counts_per_lega_ruolo.items():
        for role, slugs_dict in ruoli.items():
            n_g = 0
            for slug, entry in slugs_dict.items():
                n_entry_tot += 1
                g = grade_map.get(slug)
                if g:
                    entry['grade'] = g
                    n_entry_grade += 1
                    n_g += 1
            if slugs_dict:
                copertura_per_lega_ruolo[(lega, role)] = (n_g, len(slugs_dict))
    if n_entry_tot:
        log(f"[grade] copertura sui kept_slugs (post filtro odds): "
            f"{n_entry_grade}/{n_entry_tot} ({100*n_entry_grade/n_entry_tot:.1f}%)")
        for (lega, role), (n_g, n_tot) in sorted(copertura_per_lega_ruolo.items()):
            if n_g == 0 and n_tot > 0:
                log(f"[grade] ATTENZIONE: {lega}/{role} ha {n_tot} kept_slugs "
                    f"ma ZERO con grade -- questa lega/ruolo girera' G in "
                    f"fallback (z_grade=0, identico ad A) per questa GW.")

    # SVUOTA le lega/ruolo esaminate ma rimaste senza nessun superstite
    # (07/08/2026, bug reale costato due arene -- caso
    # pedro-david-gallese-quiroz).
    # Prima si scriveva SOLO per le lega/ruolo con superstiti: se una si
    # svuotava, i suoi player_slugs/player_names/player_card_counts restavano
    # quelli della run precedente. Il generatore non prende i candidati da
    # qui, li prende dai consiglio_*.txt -- e anche quelli non venivano
    # rigenerati, perche' la lega usciva dalla matrice. Risultato: Gallese,
    # entrambe le carte gia' bloccate, restava nel consiglio delle 16:37 e nei
    # conteggi con 2 copie, e il generatore lo schierava in due arene che poi
    # non erano schierabili davvero.
    # Scrivendo i file VUOTI, CardPool torna a vedere 0 copie ("mai schierare
    # un giocatore di cui non c'e' prova di possesso", _total_for) e il
    # giocatore non e' piu' selezionabile anche se il consiglio e' stantio.
    for _dn, _role in sorted(esaminati_lega_ruolo):
        if _dn not in per_lega_ruolo or _role not in per_lega_ruolo[_dn]:
            per_lega_ruolo[_dn][_role] = set()
            log(f"  {_dn}/{_role}: nessun candidato oggi -> file svuotati "
                f"(prima restavano quelli della run precedente)")

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
