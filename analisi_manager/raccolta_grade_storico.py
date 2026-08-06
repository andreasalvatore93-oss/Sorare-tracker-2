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

SORARE_COOKIE = '_ga=GA1.1.1573227880.1768855406; _ga_1DHGT9FK62=GS2.1.s1768855406$o1$g1$t1768855595$j60$l0$h0; ajs_anonymous_id=705d24b1-35c6-49ff-a970-7ae536bb5ee1; ajs_user_id=d3a9c1da-ae7c-4d41-992e-4c6c8f494372; analytics_session_id=1784657654534; ab.storage.deviceId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%228a7f16c2-15b8-e354-9a7f-121e8c40380b%22%2C%22c%22%3A1769104355002%2C%22l%22%3A1784661012335%7D; ab.storage.userId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%22d3a9c1da-ae7c-4d41-992e-4c6c8f494372%22%2C%22c%22%3A1769104691504%2C%22l%22%3A1784661012335%7D; ab.storage.sessionId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%22aca56313-59d9-ed85-fedf-599ae3b8ace7%22%2C%22e%22%3A1784668364792%2C%22c%22%3A1784661012334%2C%22l%22%3A1784666564792%7D; analytics_session_id.last_access=1784666570046; tracking-preferences2=%7B%22version%22%3A1%2C%22destinations%22%3A%7B%22Actions%20Amplitude%22%3Afalse%2C%22Actions%20Google%20Analytic%204%22%3Afalse%2C%22altertable_dest%20(Sorare)%22%3Afalse%2C%22Appboy%22%3Afalse%2C%22AWS%20S3%22%3Afalse%2C%22Braze%20Web%20Mode%20(Actions)%22%3Afalse%2C%22Facebook%20Conversions%20API%20(Actions)%22%3Afalse%2C%22Google%20AdWords%20New%22%3Afalse%2C%22Google%20Analytics%204%20Web%22%3Afalse%2C%22Google%20Enhanced%20Conversions%22%3Afalse%2C%22Reddit%20Conversions%20Api%22%3Afalse%2C%22Snap%20Conversions%20Api%22%3Afalse%2C%22Tiktok%20Conversions%22%3Afalse%2C%22Twitter%20Conversion%20API%20Function%20(Sorare)%22%3Afalse%7D%7D; _sorare_session_id=6eRmePn8mE4kEDC8kGH36W%2FQEpSBzs%2F7fr5e6inOYiy%2FIqyJtVQt7MtoGE5pta1L9JNVWSPXeQuAEEN%2FzhJ7v0rTaup%2F5tMWqiJeu6zjzXf8k2ZAphSoArwlpNBAs4mCBtyvqwm%2BtV7SW1ifd5Q%2F%2FeyvswoBBpnxZ0UClH%2B47NvT8KGGEHm42GANaWMozGos5wP67mVp36tt3Z55xHr3XiD%2BMwdxkNQ2%2BepwWeKlkCPWH2NTGb6yUh1lRg7O1ZBjEM4ceiy16TWeyxc%2B7Oj%2BGGdmK68%2FG%2BJ6NlXSBRaUDqrK%2FtZYY72NCDTBWXFPCmLAGOhX8Kc8zyYXMU65uA%2FAEWWuoLDdjRmUdR4tperU0bcUYScE3J1Aqw0CJ5yrhmaT%2BkZSBjIV8ANk%2BnZfBCF8iJ8v7P%2F95Tduuy%2Bec6Kg1mwWy1rnyp7OcWE5LJ5d%2Bn3Rya%2FvPE40ZnhVQTibJmlwXgmq7sdh8n65fm6tSc%2BpDEoCLCaCTfzEYigzLogVJpxB5h2levfH5VI5ZZuKU6yf5pGXmgKPJl%2BYHhEkMuJxYIJ1oFDGIDnxcsXrq64YOOyC5kvo9xSwv4YAKpSVAIlLn7uHZxdi0uj%2Btp5%2FeDEVSSJ0S%2Bqa--of%2BuFovnJ4Z%2B7rzH--brvWWAnUimTExil0nl5Vtg%3D%3D; csrftoken=Qv4r_6w505I1M2-QosLm7MyRPDWm49ZwCjA-HU0ZAVS1tM_xrUq-fwsY8ka4_lpI4IJOtDH5DdbP_91vpi6EkQ'
SORARE_CSRF = 'Qv4r_6w505I1M2-QosLm7MyRPDWm49ZwCjA-HU0ZAVS1tM_xrUq-fwsY8ka4_lpI4IJOtDH5DdbP_91vpi6EkQ'

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
