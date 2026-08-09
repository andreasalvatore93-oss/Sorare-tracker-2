#!/usr/bin/env python3
"""Raccolta storico grade su larga scala (150-200 giocatori per ruolo, 15 partite ciascuno).
Rotta: anyPlayer(slug) -> playerGameScores(last: 15).
Campionamento da manager_*.json, solo leghe con pipeline completa.
"""
import sys, os, io, json, glob, random
from collections import defaultdict

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

SORARE_COOKIE = os.environ.get('SORARE_COOKIE', '')  # mai hardcodare: repo pubblico
SORARE_CSRF = os.environ.get('SORARE_CSRF', '')

QUERY_STORICO = """
query GetPlayerGameScores {
  anyPlayer(slug: "%s") {
    displayName
    slug
    activeClub { name slug }
    playerGameScores(last: 15) {
      id
      score
      scoreStatus
      anyGame {
        date
        homeTeam { slug }
        awayTeam { slug }
        homeStats { ... on FootballTeamGameStats { winOddsBasisPoints } }
        awayStats { ... on FootballTeamGameStats { winOddsBasisPoints } }
      }
      anyPlayerGameStats {
        ... on PlayerGameStats {
          footballPlayingStatusOdds { starterOddsBasisPoints reliability }
        }
      }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""

LEAGUE_DIR = {
    'mls', 'inseason_kleague', 'danimarca', 'norvegia', 'belgio', 'croazia',
    'germania', 'olanda', 'scozia', 'portogallo', 'austria', 'turchia',
    'giappone', 'messico', 'spagna2', 'italia2', 'brasile', 'argentina',
    'cile', 'svezia', 'israele', 'romania', 'polonia', 'repubblica_ceca',
    'grecia', 'ucraina', 'servia'
}

def read_managers():
    """Legge tutti i manager_*.json, estrae giocatori per ruolo."""
    players_by_role = defaultdict(set)
    total_players = 0

    pattern = os.path.join(os.path.dirname(__file__), '..', 'dati_globali', 'manager_*.json')
    manager_files = glob.glob(pattern)

    print(f"Leggendo {len(manager_files)} manager file...")
    for fh_path in sorted(manager_files):
        try:
            with open(fh_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except:
            continue

        giornate = data.get('giornate', {})
        for gw, formazioni_list in giornate.items():
            for formazione in formazioni_list:
                for carta in formazione.get('carte', []):
                    slug = carta.get('slug')
                    position = carta.get('ruolo')
                    if slug and position:
                        key = (slug, position)
                        players_by_role[position].add(key)
                        total_players += 1

    print(f"Totale giocatori unici letti: {total_players}")
    for pos in ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']:
        print(f"  {pos}: {len(players_by_role[pos])}")

    return players_by_role

def sample_players(players_by_role, target=175, seed=42):
    """Campiona i giocatori a caso per ruolo."""
    random.seed(seed)
    sampled = {}

    for pos in ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']:
        all_for_pos = list(players_by_role.get(pos, set()))

        if len(all_for_pos) > target:
            sampled[pos] = random.sample(all_for_pos, target)
        else:
            sampled[pos] = all_for_pos

        print(f"{pos}: {len(sampled[pos])} giocatori campionati (tot letto: {len(all_for_pos)})")

    return sampled, {}

def query_storico(slug):
    """Esegue la query storico per un giocatore."""
    if not SORARE_COOKIE or not SORARE_CSRF:
        return None

    query_str = QUERY_STORICO % slug
    payload = {"operationName": "GetPlayerGameScores", "query": query_str}
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': SORARE_COOKIE,
        'X-CSRF-Token': SORARE_CSRF
    }

    try:
        r = g._http_session.post(g.GRAPHQL_URL, json=payload, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get('errors'):
            return None
        return d.get('data', {}).get('anyPlayer')
    except:
        return None

def extract_rows(player_data, slug, role, lega=None):
    """Estrae righe giocatore×partita dal response GraphQL."""
    if not player_data:
        return []

    rows = []
    nome = player_data.get('displayName')
    team_slug = (player_data.get('activeClub') or {}).get('slug')

    for gs in player_data.get('playerGameScores', []):
        proj = gs.get('projection') or {}
        ag = gs.get('anyGame') or {}
        pgs = (gs.get('anyPlayerGameStats') or {}).get('footballPlayingStatusOdds') or {}

        home = ag.get('homeTeam', {}).get('slug')
        away = ag.get('awayTeam', {}).get('slug')
        is_home = team_slug == home
        own_odds = (ag.get('homeStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('awayStats') or {}).get('winOddsBasisPoints')
        opp_odds = (ag.get('awayStats') or {}).get('winOddsBasisPoints') if is_home else (ag.get('homeStats') or {}).get('winOddsBasisPoints')

        row = {
            'slug': slug,
            'nome': nome,
            'ruolo': role,
            'squadra': team_slug,
            'grade': proj.get('grade'),
            'reliability_bp': proj.get('reliabilityBasisPoints'),
            'score_realizzato': gs.get('score'),
            'scoreStatus': gs.get('scoreStatus'),
            'starter_odds_bp': pgs.get('starterOddsBasisPoints'),
            'starter_reliability': pgs.get('reliability'),
            'game_date': ag.get('date'),
            'home_team': home,
            'away_team': away,
            'own_win_odds_bp': own_odds,
            'opp_win_odds_bp': opp_odds,
        }
        if lega:
            row['lega'] = lega
        rows.append(row)

    return rows

def main():
    print("=== RACCOLTA STORICO GRADE ===\n")

    # Step 1: leggi manager
    players_by_role = read_managers()
    print()

    # Step 2: campiona
    sampled, skipped_leghe = sample_players(players_by_role)
    print()

    # Step 3: query e raccogli
    output_by_role = defaultdict(list)
    errors = []
    total_queried = 0

    for pos in ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']:
        print(f"Querying {pos}...")
        for i, (slug, role) in enumerate(sampled.get(pos, [])):
            if i % 20 == 0:
                print(f"  {i}/{len(sampled.get(pos, []))} completati")

            data = query_storico(slug)
            total_queried += 1

            if not data:
                errors.append(f"{slug} ({pos}): query fallita")
                continue

            n_games = len(data.get('playerGameScores', []))
            if n_games != 15:
                errors.append(f"{slug}: {n_games} partite invece di 15")

            rows = extract_rows(data, slug, role, None)
            output_by_role[pos].extend(rows)

    print(f"\nTotal queried: {total_queried}")

    # Step 4: salva per ruolo
    for pos in ['Goalkeeper', 'Defender', 'Midfielder', 'Forward']:
        rows = output_by_role[pos]
        fname = f"analisi_manager/dati/storico_grade_{pos}_20260806.json"
        with open(fname, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print(f"{pos}: {len(rows)} righe salvate in {fname}")

    # Step 5: report
    print(f"\nErrori ({len(errors)}):")
    for e in errors[:10]:
        print(f"  {e}")
    if len(errors) > 10:
        print(f"  ... e altri {len(errors) - 10}")

    print(f"\nLeghe scartate (fuori pipeline): {dict(skipped_leghe)}")

if __name__ == '__main__':
    main()
