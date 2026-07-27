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

ROLE_BY_POSITION = {'Goalkeeper': 'gk', 'Defender': 'def',
                    'Midfielder': 'mid', 'Forward': 'fwd'}

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
}

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

ODDS_QUERY = """
query NextOdds($slug: String!) {
  anyPlayer(slug: $slug) {
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


# L10 (28/07, richiesta esplicita utente): stessa query gia' usata da
# generatore_formazioni/quality_filter.py per il filtro qualita'. Interrogata
# SOLO per i sopravvissuti finali (dopo finestra+odds), mai per i ~2000
# posseduti -- stesso principio del pre-filtro squadre in campo.
L10_QUERY = """
query PlayerL10($slug: String!) {
  anyPlayer(slug: $slug) {
    lastTenPlayedAvgScore: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE)
  }
}
"""


def l10_singola(slug):
    d = base.graphql_query(L10_QUERY, {"slug": slug}, operation_name="PlayerL10")
    return (d.get('data') or {}).get('anyPlayer', {}).get('lastTenPlayedAvgScore')


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


def odds_singola(slug, inizio, fine):
    """(odds, data) della prima partita del giocatore dentro la finestra.
    NB: Sorare non consente il batching -- alias duplicati su anyPlayer sono
    rifiutati ("Duplicated root field") e players(slugs:) non permette di
    selezionare anyFutureGames. Per questo il pre-filtro sulle squadre che
    giocano e' l'unica leva che conta sui tempi."""
    d = base.graphql_query(ODDS_QUERY, {"slug": slug}, operation_name="NextOdds")
    p = (d.get('data') or {}).get('anyPlayer') or {}
    for n in ((p.get('anyFutureGames') or {}).get('nodes') or []):
        pgs = n.get('playerGameScore') or {}
        dt = (pgs.get('anyGame') or {}).get('date') or ''
        if inizio and fine and not (inizio <= dt[:19] <= fine):
            continue
        o = ((pgs.get('anyPlayerGameStats') or {})
             .get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
        return (o / 10000.0 if o is not None else None), dt
    return None, None


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
            if page >= (s.get('nbPages') or 1):
                break
            page += 1
            time.sleep(0.25)

        tot_carte += len(visti)
        lega_di = {slug: lega for slug, lega, _nome in visti}
        nome_di = {slug: nome for slug, _lega, nome in visti if nome}
        elenco = sorted(lega_di)
        log(f"  {position}: {len(elenco)} giocatori di squadre che giocano "
            f"(su {s.get('nbHits')} carte possedute) -> interrogo le odds")
        risultati = {}
        for sl in elenco:
            risultati[sl] = odds_singola(sl, inizio, fine)
            time.sleep(0.2)
        for slug in elenco:
            lega = lega_di[slug]
            odds, data = risultati.get(slug, (None, None))
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
            # L10 (28/07): solo per i sopravvissuti finali, mai per l'intero
            # pool. Copie possedute NON tracciate da questa pipeline veloce
            # (a differenza delle vecchie discovery per-campionato): si tiene
            # l'assunzione preesistente "1 copia in_season" gia' usata da
            # CardPool come default per uno slug assente dal file -- qui va
            # scritta esplicitamente perche' il file adesso include lo slug
            # (per portarci l10), e altrimenti verrebbe letta come 0 copie.
            l10 = l10_singola(slug)
            time.sleep(0.2)
            entry = {'in_season': 1, 'classic': 0}
            if l10 is not None:
                entry['l10'] = l10
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
