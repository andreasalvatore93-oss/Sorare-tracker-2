"""Cattura grade A-F (So5Score.projection.grade) su partita FUTURA, per
TUTTI i giocatori di una partita, via query PUBBLICA (nessun cookie).

Scoperto 09/08/2026 (docs/handoff/ANALISI_DUMP_COMPOSEBENCH_2026-08-09.txt):
il grade su partita 'scheduled' e' appeso al Game (anyGame.playerGameScores),
non al Player (player.playerGameScores(last:N), che per una partita futura
non ha ancora nessun nodo). anyGame(id) e' pubblico, verificato: la stessa
query restituisce projection.grade senza Cookie/CSRF.

A differenza di grade_snapshot.py (FootballComposeBenchQuery, richiede
cookie, limitato alle carte POSSEDUTE dall'utente), questo script legge
TUTTI i giocatori della partita, titolari e non, di entrambe le squadre.

RIPETIZIONE (accumulo pre-lock, brief BRIEF_SONNET_SNAPSHOT_ACCUMULO):
  comando esatto:  python analisi_manager/grade_snapshot_pubblico.py --fixture <slug-fixture>
  quando:          a ridosso del lock, PRIMA del primo kickoff della GW
                   (le ufficiali congelano il grade, vedi §18 HANDOFF_TABELLA_GRADE)
  cosa NON serve:  nessun cookie, nessuna APIKEY

Uso:
  python grade_snapshot_pubblico.py <game_id> [label]
      Un solo game_id (1 query). game_id es.
      "Game:2811948e-5d53-49c5-8a27-4dc5259b8450".

  python grade_snapshot_pubblico.py --fixture <fixture_slug> [--include-live]
      TUTTA LA GIORNATA: risolve tutti i game della fixture (1 query) e
      cattura solo quelli con statusTyped=='scheduled' (non ancora iniziati,
      quindi non ancora pre-ufficiali "scaduti"; con --include-live include
      anche 'started'), un game per query (bulk per fixture, non per
      giocatore: N partite = N+1 query totali, dichiarate a schermo).
      Salva un unico file per tutta la giornata in analisi_manager/dati/.
"""
import sys, os, io, json
from datetime import datetime, timezone

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_turchia', 'discovery'))
import turchia_gk_discovery as base  # noqa: E402

QUERY = """
query GameProjection($id: ID!) {
  anyGame(id: $id) {
    date
    statusTyped
    homeTeam { slug }
    awayTeam { slug }
    playerGameScores {
      anyPlayer { slug displayName l10: averageScore(type: LAST_TEN_PLAYED_SO5_AVERAGE_SCORE) }
      scoreStatus
      anyPlayerGameStats {
        ... on PlayerGameStats {
          fieldStatus
          anyTeam { slug }
          footballPlayingStatusOdds { starterOddsBasisPoints reliability }
        }
      }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""


def capture(game_id):
    now_utc = datetime.now(timezone.utc)
    d = base.graphql_query(QUERY, {"id": game_id}, operation_name="GameProjection")
    game = ((d or {}).get('data') or {}).get('anyGame') or {}
    rows = []
    for sc in game.get('playerGameScores') or []:
        ap = sc.get('anyPlayer') or {}
        stats = sc.get('anyPlayerGameStats') or {}
        odds = stats.get('footballPlayingStatusOdds') or {}
        proj = sc.get('projection') or {}
        rows.append({
            "game_id": game_id,
            "game_date": game.get('date'), "statusTyped": game.get('statusTyped'),
            "home_team": (game.get('homeTeam') or {}).get('slug'),
            "away_team": (game.get('awayTeam') or {}).get('slug'),
            "player_slug": ap.get('slug'), "player_nome": ap.get('displayName'),
            "squadra": stats.get('anyTeam', {}).get('slug'),
            "fieldStatus": stats.get('fieldStatus'),
            "scoreStatus": sc.get('scoreStatus'),
            "starter_odds_bp": odds.get('starterOddsBasisPoints'),
            "starter_reliability": odds.get('reliability'),
            "grade": proj.get('grade'),
            "reliability_bp": proj.get('reliabilityBasisPoints'),
            "l10": (sc.get('anyPlayer') or {}).get('l10'),
            "captured_at_utc": now_utc.isoformat(),
        })
    return rows


_FIXTURE_GAMES_STATUS = """
query FixtureGamesStatus($slug: String!) {
  so5 {
    so5Fixture(slug: $slug) {
      anyGames {
        id date statusTyped
        homeTeam { ... on TeamInterface { slug } }
        awayTeam { ... on TeamInterface { slug } }
      }
    }
  }
}
"""


def capture_fixture(fixture_slug, include_live=False):
    """Cattura tutti i giocatori di TUTTE le partite 'scheduled' (non ancora
    iniziate) di una fixture, in un colpo solo. 1 query per risolvere i
    game_id + 1 query per ogni partita catturata (bulk per fixture, non per
    giocatore)."""
    d = base.graphql_query(_FIXTURE_GAMES_STATUS, {"slug": fixture_slug},
                            operation_name="FixtureGamesStatus")
    fx = (((d or {}).get('data') or {}).get('so5') or {}).get('so5Fixture') or {}
    games = fx.get('anyGames') or []
    stati_ok = {'scheduled'} | ({'started'} if include_live else set())
    target = [g for g in games if g.get('statusTyped') in stati_ok and g.get('id')]
    print(f"Fixture {fixture_slug}: {len(games)} partite totali, "
          f"{len(target)} da catturare (statusTyped in {sorted(stati_ok)}). "
          f"Query totali: 1 (lista) + {len(target)} (partite) = {1 + len(target)}.")
    rows = []
    for g in target:
        rows.extend(capture(g['id']))
    return rows, target


def main():
    if len(sys.argv) < 2:
        print('Uso: python grade_snapshot_pubblico.py <game_id> [label]')
        print('     python grade_snapshot_pubblico.py --fixture <fixture_slug> [--include-live]')
        sys.exit(1)
    if sys.argv[1] == '--fixture':
        if len(sys.argv) < 3:
            print('Uso: python grade_snapshot_pubblico.py --fixture <fixture_slug> [--include-live]')
            sys.exit(1)
        fixture_slug = sys.argv[2]
        include_live = '--include-live' in sys.argv[3:]
        rows, target = capture_fixture(fixture_slug, include_live=include_live)
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
        out_path = f'analisi_manager/dati/snapshot_public_fixture_{fixture_slug}_{ts}Z.json'
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print(f'{len(rows)} righe ({len(target)} partite) salvate in {out_path}')
        return
    game_id = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else game_id.split(':')[-1][:8]
    rows = capture(game_id)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    out_path = f'analisi_manager/dati/snapshot_public_game_{label}_{ts}Z.json'
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f'{len(rows)} righe salvate in {out_path}')


if __name__ == '__main__':
    main()
