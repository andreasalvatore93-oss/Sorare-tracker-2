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
          activeClub { domesticLeague { slug } }
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


def odds_e_data(slug, inizio, fine):
    """(odds, data) della prima partita del giocatore DENTRO la fixture."""
    d = base.graphql_query(ODDS_QUERY, {"slug": slug}, operation_name="NextOdds")
    p = (d.get('data') or {}).get('anyPlayer') or {}
    for n in ((p.get('anyFutureGames') or {}).get('nodes') or []):
        pgs = n.get('playerGameScore') or {}
        data = (pgs.get('anyGame') or {}).get('date') or ''
        if inizio and fine and not (inizio <= data[:19] <= fine):
            continue
        odds = ((pgs.get('anyPlayerGameStats') or {})
                .get('footballPlayingStatusOdds') or {}).get('starterOddsBasisPoints')
        return (odds / 10000.0 if odds is not None else None), data
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

    uuid = base.get_user_uuid(base.USER_SLUG)
    if not uuid:
        log("ERRORE: uuid utente non ottenuto.")
        return 1
    advanced = (f"user.id:{uuid} AND sport:football "
                f"AND NOT sealed=1 AND NOT rarity:custom_series "
                f"AND active_competitions:{fx.get('slug')}")

    per_lega_ruolo = defaultdict(lambda: defaultdict(set))
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
                if p.get('slug'):
                    visti.add((p['slug'], ((p.get('activeClub') or {})
                                           .get('domesticLeague') or {}).get('slug')))
            if page >= (s.get('nbPages') or 1):
                break
            page += 1
            time.sleep(0.25)

        tot_carte += len(visti)
        for slug, lega in sorted(visti):
            odds, data = odds_e_data(slug, inizio, fine)
            time.sleep(0.25)
            if data is None:
                esclusi_finestra += 1
                continue
            if odds is None or odds < MIN_ODDS:
                esclusi_odds += 1
                continue
            dirname = LEAGUE_DIR.get(lega)
            if not dirname:
                log(f"  lega senza pipeline: {lega} (giocatore {slug}) -- ignorato")
                continue
            per_lega_ruolo[dirname][role].add(slug)

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
