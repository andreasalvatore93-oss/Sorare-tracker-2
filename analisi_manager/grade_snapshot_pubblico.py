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

Uso:
  python grade_snapshot_pubblico.py <game_id> [label]

game_id: es. "Game:2811948e-5d53-49c5-8a27-4dc5259b8450" (si trova con
una query so5Fixture(slug){anyGames{id date homeTeam{slug} awayTeam{slug}}}).
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
      anyPlayer { slug displayName }
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
            "captured_at_utc": now_utc.isoformat(),
        })
    return rows


def main():
    if len(sys.argv) < 2:
        print('Uso: python grade_snapshot_pubblico.py <game_id> [label]')
        sys.exit(1)
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
