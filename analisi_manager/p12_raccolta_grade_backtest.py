"""Raccolta grade BACKTEST su 625 giocatori distinti delle 8 GW manager.
Estrae gli slug dai file righe_football-*.json, dedup. Stessa rotta storica
validata (anyPlayer.playerGameScores(last:15)), stessi campi. Pausa 1s fra query,
backoff sul 429. Check sessione: solo che currentUser{slug} sia non nullo
(non vincolato a username specifico, la rotta anyPlayer funziona su qualunque slug).

Uso: SORARE_COOKIE=... SORARE_CSRF=... python analisi_manager/p12_raccolta_grade_backtest.py
"""
import sys, os, io, json, time, glob

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


def extract_slugs_from_righe():
    """Legge tutti i file righe_football-*.json e torna gli slug distinti."""
    slugs = set()
    pattern = os.path.join('analisi_manager', 'dati', 'righe_football-*.json')
    for fpath in glob.glob(pattern):
        try:
            data = json.load(open(fpath, encoding='utf-8'))
            for row in data:
                if 'slug' in row:
                    slugs.add(row['slug'])
        except Exception as e:
            print(f'ERRORE lettura {fpath}: {e}', flush=True)
    return sorted(list(slugs))


def main():
    r = g._http_session.post(g.GRAPHQL_URL, json={'query': '{ currentUser { slug } }'},
                             headers={'Content-Type': 'application/json', 'Cookie': COOKIES, 'X-CSRF-Token': CSRF}, timeout=20)
    who = (r.json().get('data') or {}).get('currentUser')
    print('currentUser:', who, flush=True)
    if not who or not who.get('slug'):
        print('SESSIONE NON VALIDA (currentUser.slug nullo) -- mi fermo.')
        return

    slugs = extract_slugs_from_righe()
    print(f'giocatori distinti estratti: {len(slugs)}', flush=True)

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
            with open('analisi_manager/dati/storico_grade_backtest_20260806.json', 'w', encoding='utf-8') as fh:
                json.dump({'giocatori': risultati, 'errori': errori}, fh, ensure_ascii=False, indent=1)
        time.sleep(1.0)

    with open('analisi_manager/dati/storico_grade_backtest_20260806.json', 'w', encoding='utf-8') as fh:
        json.dump({'giocatori': risultati, 'errori': errori}, fh, ensure_ascii=False, indent=1)

    slug_falliti = [e['slug'] for e in errori]
    print(f'\nFINE: {len(risultati)} ok, {len(errori)} errori', flush=True)
    if errori:
        print(f'slug falliti: {slug_falliti}', flush=True)
    print(f'Salvato in analisi_manager/dati/storico_grade_backtest_20260806.json', flush=True)


if __name__ == '__main__':
    main()
