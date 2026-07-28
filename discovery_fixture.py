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
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'formazione_turchia', 'discovery'))
os.environ.setdefault('MIN_STARTER_ODDS', '0.80')
import turchia_gk_discovery as base  # noqa: E402

MIN_ODDS = float(os.environ.get('MIN_STARTER_ODDS', '0.80'))
GAMEWEEK = os.environ.get('GAMEWEEK', '').strip()
FIXTURE_SLUG = os.environ.get('FIXTURE_SLUG', '').strip()

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
}

# Split alfabetico fisso delle cartelle di destinazione (incluso 'senza_lega')
# in n quote contigue -- usato solo se DISCOVERY_LEAGUE_SHARD e' impostata.
_ALL_DIRNAMES = sorted(set(LEAGUE_DIR.values()) | {'senza_lega'})
_WANTED_DIRNAMES = None
if DISCOVERY_LEAGUE_SHARD is not None:
    _idx, _n = DISCOVERY_LEAGUE_SHARD
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


def log(msg):
    print(f"[discovery_fixture] {msg}", flush=True)


def risolvi_fixture():
    if FIXTURE_SLUG:
        d = base.graphql_query(FIXTURE_BY_SLUG, {"slug": FIXTURE_SLUG},
                               operation_name="FixtureBySlug")
        f = ((d.get('data') or {}).get('so5') or {}).get('so5Fixture')
        if f:
            return f
        log(f"ATTENZIONE: fixture '{FIXTURE_SLUG}' non trovata.")
    if GAMEWEEK:
        # so5Fixtures non accetta un filtro per gameweek: si prendono le ultime
        # e si sceglie quella giusta lato client.
        d = base.graphql_query(FIXTURE_BY_GW, {"first": 30}, operation_name="FixtureList")
        nodes = (((d.get('data') or {}).get('so5') or {})
                 .get('so5Fixtures') or {}).get('nodes') or []
        match = [n for n in nodes if str(n.get('seasonGameWeek')) == str(GAMEWEEK)]
        if match:
            aperte = [n for n in match if n.get('aasmState') == 'opened']
            return (aperte or match)[0]
        disponibili = sorted({str(n.get('seasonGameWeek')) for n in nodes})
        log(f"ATTENZIONE: gameweek {GAMEWEEK} non fra quelle restituite: {disponibili}")
    return None


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
        page = 1
        while page <= 50:
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
                # u23Eligible vive sulla CARTA (28/07, confermato dall'utente via
                # DevTools -- il flag Sorare, non un calcolo nostro su birthDay:
                # un 24enne puo' restare flaggato true se ha compiuto gli anni a
                # stagione iniziata), gia' nella stessa CARDS_QUERY -- zero query
                # in piu'. OR fra le carte dello stesso giocatore: basta che una
                # sia flaggata per considerarlo eleggibile.
                if h.get('u23Eligible'):
                    u23_di[p['slug']] = True
                # Bonus xp/collezione/stagione (28/07, richiesta esplicita
                # utente: il bot non li considerava affatto nello schieramento
                # -- da qui in poi solo RACCOLTA dato, l'integrazione nello
                # score e' un passo successivo, ancora da progettare). Vive
                # sulla CARTA, stessa query di u23Eligible, zero costo in piu'.
                # Season/collection/xp contano SOLO in In Season/All Stars
                # (7 e U23), MAI nelle Arene (dove xp=0 di default per tutti,
                # solo il capitano ha un bonus fisso) -- quella distinzione va
                # applicata a valle, qui si salva il dato grezzo per tutti.
                pb = h.get('powerBreakdown') or {}
                if pb or h.get('xp') is not None:
                    power_di[p['slug']] = {
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
        log(f"  {position}: {len(elenco)} giocatori di squadre che giocano "
            f"(su {s.get('nbHits')} carte possedute) -> interrogo le odds")
        # odds + L10 in UNA chiamata per giocatore (28/07, vedi
        # odds_e_l10_singola) invece di due passaggi separati -- dimezza il
        # numero di round-trip verso Sorare rispetto a prima, stesso dato.
        risultati = {}
        for sl in elenco:
            risultati[sl] = odds_e_l10_singola(sl, inizio, fine)
            time.sleep(ODDS_L10_SLEEP)
        for slug in elenco:
            lega = lega_di[slug]
            odds, data, l10 = risultati.get(slug, (None, None, None))
            if data is None:
                esclusi_finestra += 1
                continue
            if odds is None or odds < MIN_ODDS:
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
            # L10 (28/07): gia' ottenuta assieme alle odds nella stessa
            # chiamata sopra. Copie possedute NON tracciate da questa
            # pipeline veloce (a differenza delle vecchie discovery per-
            # campionato): si tiene l'assunzione preesistente "1 copia
            # in_season" gia' usata da CardPool come default per uno slug
            # assente dal file -- qui va scritta esplicitamente perche' il
            # file adesso include lo slug (per portarci l10), e altrimenti
            # verrebbe letta come 0 copie.
            entry = {'in_season': 1, 'classic': 0}
            if l10 is not None:
                entry['l10'] = l10
            if u23_di.get(slug):
                entry['u23'] = True
            if power_di.get(slug):
                entry['power'] = power_di[slug]
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

    matrice = [{"league": lg, "role": r} for lg, ruoli in sorted(scritti.items())
               for r in sorted(ruoli)]
    print("\nMATRICE_JSON=" + json.dumps(matrice, separators=(',', ':')))
    gh_out = os.environ.get('GITHUB_OUTPUT')
    if gh_out:
        with open(gh_out, 'a', encoding='utf-8') as f:
            f.write("matrice=" + json.dumps(matrice, separators=(',', ':')) + "\n")
            f.write("fixture=" + (fx.get('slug') or '') + "\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
