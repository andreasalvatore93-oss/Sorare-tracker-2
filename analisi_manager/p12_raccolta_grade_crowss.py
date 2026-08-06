"""Raccolta grade MIRATA sui 717 giocatori distinti presenti nel pool
disponibile delle 232 arene reali del backtest di formazione (sez.21).
Stessa rotta storica gia' validata (anyPlayer.playerGameScores(last:15)),
stessi campi delle altre raccolte Haiku. Pausa 1s fra query, backoff sul 429.

Uso: SORARE_COOKIE=... SORARE_CSRF=... python analisi_manager/p12_raccolta_grade_crowss.py
"""
import sys, os, io, json, time

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'formazione_mls', 'discovery'))
import mls_def_discovery_global as g

CSRF = os.environ.get('SORARE_CSRF', '')
COOKIES = os.environ.get('SORARE_COOKIE', '') or g.COOKIES

QUERY = """
query PlayerHistGrade($slug: String!) {
  anyPlayer(slug: $slug) {
    slug
    displayName
    playerGameScores(last: 15) {
      score
      scoreStatus
      anyGame {
        date
        homeTeam { slug }
        awayTeam { slug }
      }
      projection { grade reliabilityBasisPoints }
      anyPlayerGameStats {
        ... on PlayerGameStats {
          footballPlayingStatusOdds { starterOddsBasisPoints reliability }
        }
      }
    }
  }
}
"""


def query_slug(slug, tentativo=0):
    headers = {'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF}
    r = g._http_session.post(g.GRAPHQL_URL, json={'query': QUERY, 'variables': {'slug': slug}}, headers=headers, timeout=20)
    if r.status_code == 429:
        if tentativo >= 4:
            return None, '429 dopo 4 tentativi'
        attesa = 5 * (2 ** tentativo)
        print(f'  429 su {slug}, attendo {attesa}s (tentativo {tentativo+1})', flush=True)
        time.sleep(attesa)
        return query_slug(slug, tentativo + 1)
    try:
        d = r.json()
    except Exception:
        return None, f'HTTP {r.status_code}: {r.text[:200]}'
    if d.get('errors'):
        return None, str(d['errors'])[:200]
    return (d.get('data') or {}).get('anyPlayer'), None


def main():
    r = g._http_session.post(g.GRAPHQL_URL, json={'query': '{ currentUser { slug } }'},
                             headers={'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF}, timeout=20)
    who = (r.json().get('data') or {}).get('currentUser')
    print('currentUser:', who, flush=True)
    if not who or who.get('slug') != 'crowss':
        print('COOKIE NON VALIDO O UTENTE SBAGLIATO -- mi fermo.')
        return

    slugs = json.load(open('analisi_manager/p12_crowss_slug_target.json', encoding='utf-8'))
    print(f'giocatori target: {len(slugs)}', flush=True)

    risultati = []
    errori = []
    t0 = time.time()
    for i, slug in enumerate(slugs, 1):
        player, err = query_slug(slug)
        if err:
            errori.append({'slug': slug, 'errore': err})
        elif player is None:
            errori.append({'slug': slug, 'errore': 'anyPlayer nullo'})
        else:
            risultati.append(player)
        if i % 25 == 0 or i == len(slugs):
            print(f'  [{i}/{len(slugs)}] ok={len(risultati)} errori={len(errori)}  ({time.time()-t0:.0f}s)', flush=True)
            with open('analisi_manager/dati/storico_grade_crowss_20260806.json', 'w', encoding='utf-8') as fh:
                json.dump({'giocatori': risultati, 'errori': errori}, fh, ensure_ascii=False, indent=1)
        time.sleep(1.0)

    with open('analisi_manager/dati/storico_grade_crowss_20260806.json', 'w', encoding='utf-8') as fh:
        json.dump({'giocatori': risultati, 'errori': errori}, fh, ensure_ascii=False, indent=1)
    print(f'FINE: {len(risultati)} ok, {len(errori)} errori, salvato in analisi_manager/dati/storico_grade_crowss_20260806.json')


if __name__ == '__main__':
    main()
