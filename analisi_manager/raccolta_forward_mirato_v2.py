#!/usr/bin/env python3
"""Raccolta Forward mirato v2: filtro lega pre-query, backoff 429, checkpoint."""
import sys, os, io, json, glob, random, time
from collections import defaultdict

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

SORARE_COOKIE = '_ga=GA1.1.1573227880.1768855406; _ga_1DHGT9FK62=GS2.1.s1768855406$o1$g1$t1768855595$j60$l0$h0; ajs_anonymous_id=705d24b1-35c6-49ff-a970-7ae536bb5ee1; ajs_user_id=d3a9c1da-ae7c-4d41-992e-4c6c8f494372; analytics_session_id=1784657654534; ab.storage.deviceId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%228a7f16c2-15b8-e354-9a7f-121e8c40380b%22%2C%22c%22%3A1769104355002%2C%22l%22%3A1784661012335%7D; ab.storage.userId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%22d3a9c1da-ae7c-4d41-992e-4c6c8f494372%22%2C%22c%22%3A1769104691504%2C%22l%22%3A1784661012335%7D; ab.storage.sessionId.f9062f4a-69b2-4d6b-a39c-23bc77cf4004=%7B%22g%22%3A%22aca56313-59d9-ed85-fedf-599ae3b8ace7%22%2C%22e%22%3A1784668364792%2C%22c%22%3A1784661012334%2C%22l%22%3A1784666564792%7D; analytics_session_id.last_access=1784666570046; tracking-preferences2=%7B%22version%22%3A1%2C%22destinations%22%3A%7B%22Actions%20Amplitude%22%3Afalse%2C%22Actions%20Google%20Analytic%204%22%3Afalse%2C%22altertable_dest%20(Sorare)%22%3Afalse%2C%22Appboy%22%3Afalse%2C%22AWS%20S3%22%3Afalse%2C%22Braze%20Web%20Mode%20(Actions)%22%3Afalse%2C%22Facebook%20Conversions%20API%20(Actions)%22%3Afalse%2C%22Google%20AdWords%20New%22%3Afalse%2C%22Google%20Analytics%204%20Web%22%3Afalse%2C%22Google%20Enhanced%20Conversions%22%3Afalse%2C%22Reddit%20Conversions%20Api%22%3Afalse%2C%22Snap%20Conversions%20Api%22%3Afalse%2C%22Twitter%20Conversion%20API%20Function%20(Sorare)%22%3Afalse%7D%7D; _sorare_session_id=6eRmePn8mE4kEDC8kGH36W%2FQEpSBzs%2F7fr5e6inOYiy%2FIqyJtVQt7MtoGE5pta1L9JNVWSPXeQuAEEN%2FzhJ7v0rTaup%2F5tMWqiJeu6zjzXf8k2ZAphSoArwlpNBAs4mCBtyvqwm%2BtV7SW1ifd5Q%2F%2FeyvswoBBpnxZ0UClH%2B47NvT8KGGEHm42GANaWMozGos5wP67mVp36tt3Z55xHr3XiD%2BMwdxkNQ2%2BepwWeKlkCPWH2NTGb6yUh1lRg7O1ZBjEM4ceiy16TWeyxc%2B7Oj%2BGGdmK68%2FG%2BJ6NlXSBRaUDqrK%2FtZYY72NCDTBWXFPCmLAGOhX8Kc8zyYXMU65uA%2FAEWWuoLDdjRmUdR4tperU0bcUYScE3J1Aqw0CJ5yrhmaT%2BkZSBjIV8ANk%2BnZfBCF8iJ8v7P%2F95Tduuy%2Bec6Kg1mwWy1rnyp7OcWE5LJ5d%2Bn3Rya%2FvPE40ZnhVQTibJmlwXgmq7sdh8n65fm6tSc%2BpDEoCLCaCTfzEYigzLogVJpxB5h2levfH5VI5ZZuKU6yf5pGXmgKPJl%2BYHhEkMuJxYIJ1oFDGIDnxcsXrq64YOOyC5kvo9xSwv4YAKpSVAIlLn7uHZxdi0uj%2Btp5%2FeDEVSSJ0S%2Bqa--of%2BuFovnJ4Z%2B7rzH--brvWWAnUimTExil0nl5Vtg%3D%3D; csrftoken=Qv4r_6w505I1M2-QosLm7MyRPDWm49ZwCjA-HU0ZAVS1tM_xrUq-fwsY8ka4_lpI4IJOtDH5DdbP_91vpi6EkQ'
SORARE_CSRF = 'Qv4r_6w505I1M2-QosLm7MyRPDWm49ZwCjA-HU0ZAVS1tM_xrUq-fwsY8ka4_lpI4IJOtDH5DdbP_91vpi6EkQ'

QUERY_STORICO = """
query GetPlayerGameScores {
  anyPlayer(slug: "%s") {
    displayName
    slug
    activeClub { name slug }
    playerGameScores(last: 15) {
      id score scoreStatus
      anyGame {
        date
        homeTeam { slug } awayTeam { slug }
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

LEGA_MAPPING = {
    'us': 'mls', 'korea': 'kleague', 'mls': 'mls',
}

def get_leghe_pipeline():
    root = os.path.join(os.path.dirname(__file__), '..')
    leghe = set()
    for d in os.listdir(root):
        if d.startswith('formazione_') and os.path.isdir(os.path.join(root, d)):
            lega = d.replace('formazione_', '')
            leghe.add(lega)
    return leghe

def lega_from_leaderboard(leaderboard_slug):
    """Estrae la lega dal leaderboard slug."""
    parts = leaderboard_slug.split('-seasonal-')
    if len(parts) < 2:
        return None
    lega_raw = parts[1].split('-')[0]
    return LEGA_MAPPING.get(lega_raw, lega_raw)

def read_managers_forward_pipeline():
    """Legge Forward dai manager, filtrando per leghe con pipeline."""
    leghe_pipeline = get_leghe_pipeline()
    forwards = {}
    leghe_count = defaultdict(int)

    pattern = os.path.join(os.path.dirname(__file__), '..', 'dati_globali', 'manager_*.json')
    manager_files = glob.glob(pattern)

    print(f"Leghe con pipeline ({len(leghe_pipeline)}): {', '.join(sorted(leghe_pipeline)[:10])}...")
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
                lega = lega_from_leaderboard(formazione.get('leaderboard', ''))
                if lega not in leghe_pipeline:
                    continue

                for carta in formazione.get('carte', []):
                    if carta.get('ruolo') == 'Forward':
                        slug = carta.get('slug')
                        if slug and slug not in forwards:
                            forwards[slug] = (carta.get('squadra'), lega)
                            leghe_count[lega] += 1

    print(f"Forward dalle leghe pipeline: {len(forwards)}")
    print(f"Per lega: {dict(leghe_count)}")
    return forwards, leghe_pipeline

def extract_rows(player_data, slug):
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
        rows.append({
            'slug': slug, 'nome': nome, 'ruolo': 'Forward', 'squadra': team_slug,
            'grade': proj.get('grade'), 'reliability_bp': proj.get('reliabilityBasisPoints'),
            'score_realizzato': gs.get('score'), 'scoreStatus': gs.get('scoreStatus'),
            'starter_odds_bp': pgs.get('starterOddsBasisPoints'), 'starter_reliability': pgs.get('reliability'),
            'game_date': ag.get('date'), 'home_team': home, 'away_team': away,
            'own_win_odds_bp': own_odds, 'opp_win_odds_bp': opp_odds,
        })
    return rows

wait_sec = 1.0

def query_storico(slug):
    """Query con backoff su 429."""
    global wait_sec
    query_str = QUERY_STORICO % slug
    payload = {"operationName": "GetPlayerGameScores", "query": query_str}
    headers = {
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'Cookie': SORARE_COOKIE, 'X-CSRF-Token': SORARE_CSRF
    }

    while True:
        time.sleep(wait_sec)
        try:
            r = g._http_session.post(g.GRAPHQL_URL, json=payload, headers=headers, timeout=15)
            if r.status_code == 429:
                wait_sec *= 2
                print(f"  [429] backoff to {wait_sec:.1f}s, riprovo {slug}...")
                continue
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            d = r.json()
            if d.get('errors'):
                return None, "GraphQL error"
            player = d.get('data', {}).get('anyPlayer')
            return player, None
        except Exception as e:
            return None, str(e)[:50]

def main():
    print("=== RACCOLTA FORWARD MIRATO V2 ===\n")

    # Crea cartella dati se non esiste
    os.makedirs('analisi_manager/dati', exist_ok=True)

    forwards, _ = read_managers_forward_pipeline()
    target = min(400, len(forwards))

    if len(forwards) > target:
        random.seed(42)
        slugs_to_query = random.sample(list(forwards.keys()), target)
    else:
        slugs_to_query = list(forwards.keys())

    print(f"Campionati {len(slugs_to_query)} Forward (disponibili {len(forwards)})")
    print()

    # Checkpoint
    checkpoint_file = 'analisi_manager/dati/storico_grade_Forward_mirato_checkpoint_20260806.json'
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r') as fh:
            checkpoint = json.load(fh)
        output = checkpoint.get('output', [])
        start_idx = checkpoint.get('idx', 0)
        errors = checkpoint.get('errors', [])
        n_429 = checkpoint.get('n_429', 0)
        wait_sec = checkpoint.get('wait_sec', 1.0)
        print(f"Riprendo dal checkpoint: {start_idx}/{len(slugs_to_query)}, {n_429} 429 visti")
    else:
        output, start_idx, errors, n_429, wait_sec = [], 0, [], 0, 1.0

    for i in range(start_idx, len(slugs_to_query)):
        slug = slugs_to_query[i]
        if i % 25 == 0:
            print(f"  {i}/{len(slugs_to_query)} query completate ({n_429} 429)")

        player, err = query_storico(slug)
        if err:
            if '429' in str(err):
                n_429 += 1
            errors.append(f"{slug}: {err}")
            continue

        if not player:
            continue

        n_games = len(player.get('playerGameScores', []))
        if n_games < 10:
            continue

        rows = extract_rows(player, slug)
        output.extend(rows)

        # Salva checkpoint ogni 25
        if (i + 1) % 25 == 0:
            with open(checkpoint_file, 'w') as fh:
                json.dump({
                    'output': output, 'idx': i + 1, 'errors': errors,
                    'n_429': n_429, 'wait_sec': wait_sec
                }, fh)

    # Salva risultato finale
    with open('analisi_manager/dati/storico_grade_Forward_mirato_20260806.json', 'w', encoding='utf-8') as fh:
        json.dump(output, fh, ensure_ascii=False, indent=1)

    os.remove(checkpoint_file) if os.path.exists(checkpoint_file) else None

    print(f"\n{len(output)} righe salvate")
    print(f"Errori: {len(errors)} ({n_429} da 429)")

if __name__ == '__main__':
    main()
