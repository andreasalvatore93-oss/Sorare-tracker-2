"""Perche' le query 'my*' rispondono UNAUTHORIZED anche con cookie valido?

Prova quattro richieste in scala, dalla piu' semplice alla piu' complessa, per
capire a quale livello si rompe:
  1. pubblica senza auth        -> se fallisce, e' la rete/gli header
  2. currentUser { nickname }   -> se fallisce, l'autenticazione non passa
  3. so5Fixture senza campi my* -> se fallisce, e' la query
  4. so5Fixture con campi my*   -> se fallisce solo questa, servono permessi
                                    o header diversi per i dati personali
"""
import json
import os

APIKEY = os.environ.get('SORARE_APIKEY', '')  # 12/08/2026: alza il tetto di complessita' e di richieste dell'account

GRAPHQL_URL = 'https://api.sorare.com/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')


def _csrf(c):
    for p in (c or '').split(';'):
        p = p.strip()
        if p.startswith('csrftoken='):
            return p.split('=', 1)[1].strip()
    return None


CSRF = _csrf(COOKIES) or os.environ.get('SORARE_CSRF', '')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()


def prova(nome, query, variables=None, con_auth=True):
    h = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get('SORARE_BUILD',
                                       '41952aef67694959421f5e001684878b72a52225'),
    }
    if con_auth:
        h['Cookie'] = COOKIES
    if APIKEY:
        h['APIKEY'] = APIKEY
        h['x-csrf-token'] = CSRF
    try:
        r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables or {}},
                    headers=h, timeout=60)
        d = r.json()
    except Exception as e:
        print(f'{nome:38s} ECCEZIONE {str(e)[:60]}')
        return
    if d.get('errors'):
        print(f'{nome:38s} ERRORE {json.dumps(d["errors"])[:110]}')
    else:
        print(f'{nome:38s} OK  {json.dumps(d.get("data"))[:100]}')


FX = os.environ.get('FIXTURE', 'football-24-28-jul-2026')

prova('1. pubblica, senza auth',
      '{ so5 { so5Fixture(slug: "%s") { slug endDate } } }' % FX, con_auth=False)
prova('2. currentUser (serve auth)',
      '{ currentUser { nickname } }')
prova('3. so5Fixture, campi pubblici',
      '{ so5 { so5Fixture(slug: "%s") { slug seasonGameWeek } } }' % FX)
prova('4. so5LeaderboardGroups senza my*',
      '{ so5 { so5Fixture(slug: "%s") { so5LeaderboardGroups(type: COMPETITION_WITH_ARENA)'
      ' { displayName slug } } } }' % FX)
prova('5. con mySo5LeaderboardContenders',
      '{ so5 { so5Fixture(slug: "%s") { so5LeaderboardGroups(type: COMPETITION_WITH_ARENA)'
      ' { mySo5LeaderboardContenders { slug } } } } }' % FX)
