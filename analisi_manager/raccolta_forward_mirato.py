#!/usr/bin/env python3
"""Raccolta Forward mirato: 400 giocatori dalle leghe con pipeline, 15 partite ciascuno."""
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

def get_leghe_pipeline():
    """Legge le leghe con pipeline dalle cartelle formazione_*/"""
    root = os.path.join(os.path.dirname(__file__), '..')
    leghe = set()
    for d in os.listdir(root):
        if d.startswith('formazione_') and os.path.isdir(os.path.join(root, d)):
            lega = d.replace('formazione_', '')
            leghe.add(lega)
    return leghe

def read_managers_forward_pipeline():
    """Legge Forward dai manager, filtrando per leghe con pipeline.
    NOTA: la lega non è nei dati manager, la mappa dalla squadra è un'approssimazione."""
    leghe_pipeline = get_leghe_pipeline()
    forwards = []

    pattern = os.path.join(os.path.dirname(__file__), '..', 'dati_globali', 'manager_*.json')
    manager_files = glob.glob(pattern)

    print(f"Leghe con pipeline: {len(leghe_pipeline)}")
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
                    if carta.get('ruolo') == 'Forward':
                        slug = carta.get('slug')
                        if slug:
                            forwards.append((slug, carta.get('squadra')))

    forwards = list(set(forwards))
    print(f"Forward unici letti (no filtro lega): {len(forwards)}")
    return forwards, leghe_pipeline

def query_n_games(slug):
    """Esegue query per contare quante partite disponibili ha un giocatore."""
    if not SORARE_COOKIE or not SORARE_CSRF:
        return 0

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
            return 0
        d = r.json()
        if d.get('errors'):
            return 0
        player = d.get('data', {}).get('anyPlayer')
        if not player:
            return 0
        return len(player.get('playerGameScores', []))
    except:
        return 0

def extract_rows(player_data, slug, role=None):
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
            'ruolo': 'Forward',
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
        rows.append(row)

    return rows

def main():
    print("=== RACCOLTA FORWARD MIRATO ===\n")

    # Step 1: leggi Forward dalle leghe con pipeline
    forwards, leghe_pipeline = read_managers_forward_pipeline()
    print(f"Leghe con pipeline ({len(leghe_pipeline)}): {', '.join(sorted(leghe_pipeline)[:10])}...")
    print()

    # Step 2: filtra per almeno 10 partite (questo costa query)
    print("Filtrando per n_games >= 10 (questo costa query)...")
    valid_forwards = []
    for i, (slug, team) in enumerate(forwards):
        if i % 100 == 0:
            print(f"  {i}/{len(forwards)} processati...")
        n_games = query_n_games(slug)
        if n_games >= 10:
            valid_forwards.append((slug, team, n_games))

    print(f"Forward con >=10 partite: {len(valid_forwards)}/{len(forwards)}")
    print()

    # Step 3: campiona 400
    random.seed(42)
    if len(valid_forwards) > 400:
        sampled = random.sample(valid_forwards, 400)
    else:
        sampled = valid_forwards

    print(f"Campionati {len(sampled)} Forward (richiesti 400)")
    print()

    # Step 4: query storico
    output = []
    errors = []
    for i, (slug, team, n_games_prev) in enumerate(sampled):
        if i % 50 == 0:
            print(f"  {i}/{len(sampled)} query completate")

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
                errors.append(f"{slug}: HTTP {r.status_code}")
                continue
            d = r.json()
            if d.get('errors'):
                errors.append(f"{slug}: GraphQL error")
                continue
            player = d.get('data', {}).get('anyPlayer')
            if not player:
                errors.append(f"{slug}: no player data")
                continue

            n_games = len(player.get('playerGameScores', []))
            rows = extract_rows(player, slug)
            output.extend(rows)
        except Exception as e:
            errors.append(f"{slug}: {str(e)[:50]}")

    # Step 5: salva
    with open('analisi_manager/dati/storico_grade_Forward_mirato_20260806.json', 'w', encoding='utf-8') as fh:
        json.dump(output, fh, ensure_ascii=False, indent=1)

    print(f"\n{len(output)} righe salvate in analisi_manager/dati/storico_grade_Forward_mirato_20260806.json")
    print(f"Errori ({len(errors)}):")
    for e in errors[:15]:
        print(f"  {e}")
    if len(errors) > 15:
        print(f"  ... e altri {len(errors) - 15}")

if __name__ == '__main__':
    main()
