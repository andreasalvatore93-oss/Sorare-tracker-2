"""Test temporaneo, NON parte del bot: verifica se Sorare accetta piu' slug
diversi aliasati a livello ROOT nella stessa query GraphQL (a differenza del
pattern gia' rifiutato che annidava allPlayerGameScores dentro anyPlayers).
Da cancellare dopo il test."""
import os
import re
import sys

import requests

COOKIES = os.environ.get('SORARE_COOKIE')
CSRF_TOKEN = None
if COOKIES:
    m = re.search(r'_sorare_csrf_token=([^;]+)', COOKIES)
    if m:
        CSRF_TOKEN = m.group(1)
CSRF_TOKEN = CSRF_TOKEN or os.environ.get('SORARE_CSRF')

HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Cookie': COOKIES,
    'x-csrf-token': CSRF_TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'Origin': 'https://sorare.com',
    'Referer': 'https://sorare.com/',
    'Accept-Language': 'it',
    'sorare-client': 'Web',
    'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
    'sorare-build': os.environ.get('SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
}
if os.environ.get('SORARE_DEVICE_FINGERPRINT'):
    HEADERS['device_fingerprint'] = os.environ['SORARE_DEVICE_FINGERPRINT']

SLUG_A = 'kylian-mbappe'
SLUG_B = 'erling-haaland'

QUERY = """
query AliasTest($slugA: String!, $slugB: String!) {
  a: anyPlayer(slug: $slugA) {
    slug
    activeClub { ... on Club { name } }
  }
  b: anyPlayer(slug: $slugB) {
    slug
    activeClub { ... on Club { name } }
  }
  tokens {
    liveA: liveSingleSaleOffers(playerSlug: $slugA, last: 1) {
      nodes { status }
    }
    liveB: liveSingleSaleOffers(playerSlug: $slugB, last: 1) {
      nodes { status }
    }
  }
}
"""

resp = requests.post(
    'https://api.sorare.com/graphql',
    json={'query': QUERY, 'variables': {'slugA': SLUG_A, 'slugB': SLUG_B}},
    headers=HEADERS, timeout=20,
)
print('HTTP status:', resp.status_code)
print(resp.text[:4000])
if resp.status_code != 200:
    sys.exit(1)
data = resp.json()
if data.get('errors'):
    print('GRAPHQL ERRORS:', data['errors'])
    sys.exit(1)
print('OK: alias multipli a livello root FUNZIONANO')
