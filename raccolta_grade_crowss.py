#!/usr/bin/env python3
"""Raccolta grade storico per crowss, evitando duplicati."""
import sys, os, io, json, glob, time
from collections import defaultdict

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'formazione_mls', 'discovery'))

# Import from raccolta_grade_storico
import requests
SORARE_COOKIE = os.environ.get('SORARE_COOKIE', '')
SORARE_CSRF = os.environ.get('SORARE_CSRF', '')

QUERY = """
query GetPlayerGameScores {
  anyPlayer(slug: "%s") {
    displayName
    slug
    activeClub { name slug }
    playerGameScores(last: 15) {
      id
      score
      scoreStatus
      anyGame { date homeTeam { slug } awayTeam { slug } homeStats { ... on FootballTeamGameStats { winOddsBasisPoints } } awayStats { ... on FootballTeamGameStats { winOddsBasisPoints } } }
      anyPlayerGameStats { ... on PlayerGameStats { footballPlayingStatusOdds { starterOddsBasisPoints reliability } } }
      projection { grade reliabilityBasisPoints }
    }
  }
}
"""

def query_storico(slug):
    """Query grado per uno slug."""
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0',
        'Cookie': SORARE_COOKIE,
        'X-CSRF-Token': SORARE_CSRF,
    }
    body = {'query': QUERY % slug}
    r = requests.post('https://api.sorare.com/federation/graphql', json=body, headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get('errors'):
        return None
    return (data.get('data') or {}).get('anyPlayer')

def read_crowss():
    """Estrae giocatori da manager_crowss.json."""
    players = set()
    path = 'dati_globali/manager_crowss.json'
    if not os.path.exists(path):
        print(f"ERRORE: {path} non trovato")
        return players

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for gw, formazioni_list in (data.get('giornate') or {}).items():
        for formazione in formazioni_list:
            for carta in formazione.get('carte', []):
                slug = carta.get('slug')
                role = carta.get('ruolo')
                if slug and role:
                    players.add((slug, role))

    print(f"Letti {len(players)} giocatori da crowss")
    return players

def read_existing_slugs():
    """Legge gli slug gia' fetchati da storico_grade_*.json."""
    existing = set()
    pattern = 'analisi_manager/dati/storico_grade_*.json'
    for fpath in glob.glob(pattern):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                rows = json.load(f)
            for row in rows:
                existing.add(row.get('slug'))
        except:
            pass
    print(f"Trovati {len(existing)} slug gia' fetchati")
    return existing

def extract_rows(player_data, slug, role):
    """Estrae righe dal response."""
    rows = []
    if not player_data:
        return rows

    nome = player_data.get('displayName')
    team_slug = (player_data.get('activeClub') or {}).get('slug')

    for gs in player_data.get('playerGameScores', []):
        proj = gs.get('projection') or {}
        ag = gs.get('anyGame') or {}

        row = {
            'slug': slug,
            'nome': nome,
            'ruolo': role,
            'squadra': team_slug,
            'grade': proj.get('grade'),
            'game_date': ag.get('date'),
        }
        rows.append(row)

    return rows

def main():
    print("=== RACCOLTA GRADE CROWSS (DEDUP) ===\n")

    crowss_players = read_crowss()
    existing_slugs = read_existing_slugs()

    missing = [(s, r) for s, r in crowss_players if s not in existing_slugs]
    print(f"Giocatori crowss da fetcharc: {len(missing)}\n")

    output_rows = []
    errors = []

    for i, (slug, role) in enumerate(sorted(missing)):
        if i % 20 == 0:
            print(f"  {i}/{len(missing)} completati", flush=True)

        data = query_storico(slug)
        if not data:
            errors.append(f"{slug}: query fallita")
            continue

        n_games = len(data.get('playerGameScores', []))
        if n_games < 1:
            errors.append(f"{slug}: 0 partite")
            continue

        rows = extract_rows(data, slug, role)
        output_rows.extend(rows)

        time.sleep(1)  # Rate limit

    print(f"\nFetchate {len(output_rows)} righe")
    print(f"Errori: {len(errors)}")

    # Salva
    fname = f"analisi_manager/dati/storico_grade_crowss_20260807.json"
    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(output_rows, f, ensure_ascii=False)

    print(f"Salvato in: {fname}")

    # Copertura
    n_con_grade = sum(1 for r in output_rows if r.get('grade') is not None)
    pct = 100 * n_con_grade / len(output_rows) if output_rows else 0
    print(f"Copertura grade: {n_con_grade}/{len(output_rows)} ({pct:.0f}%)")

if __name__ == '__main__':
    main()
