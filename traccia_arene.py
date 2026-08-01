"""Traccia gli ingressi in arena: costi, premi, piazzamenti, ROI.

Sostituisce SorareScore (che ha smesso di aggiornarsi) e serve soprattutto a
TARARE il consigliere d'ingresso: per sapere se conviene pagare 300 essenze
bisogna sapere quanto e' forte il campo, e l'unico modo onesto e' ricavarlo dai
risultati veri.

Perche' e' importante spezzare per periodo: il ROI complessivo mescola un anno
intero, partito con pochissime carte. La taratura va fatta sugli ingressi
RECENTI, altrimenti il campo risulta piu' forte di quanto sia oggi.

Richiede SORARE_COOKIE (e SORARE_CSRF): sono dati dell'account, non pubblici.
Gira su GitHub Actions, dove i segreti ci sono.

Uso:  python traccia_arene.py            # ultime 200 partecipazioni
      LIMITE=500 python traccia_arene.py
"""
import collections
import datetime
import json
import os
import sys

GRAPHQL_URL = 'https://api.sorare.com/graphql'
LIMITE = int(os.environ.get('LIMITE', '200'))
OUT = 'dati_globali/arene_storico.json'

COOKIES = os.environ.get('SORARE_COOKIE', '')
CSRF = os.environ.get('SORARE_CSRF', '')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()


def graphql(query, variables=None):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cookie': COOKIES,
        'x-csrf-token': CSRF,
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'sorare-client': 'Web',
    }
    r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables or {}},
                headers=headers, timeout=60)
    try:
        return r.json()
    except Exception:
        return {'errors': [{'message': f'HTTP {r.status_code}'}]}


# Le partecipazioni alle arene stanno sotto currentUser; la forma esatta va
# verificata alla prima esecuzione (lo schema Sorare cambia spesso). Si prova
# la query completa e, se il campo non esiste, si stampa l'errore invece di
# fallire in silenzio -- e' il tipo di bug che ha gia' fatto perdere ore.
Q = """
query ArenaStorico($first: Int!, $after: String) {
  currentUser {
    nickname
    arenaTicketsBalance: essenceBalance
    so5 {
      so5Lineups(first: $first, after: $after) {
        nodes {
          id
          score
          rank
          so5Leaderboard {
            slug
            displayName
            so5League { displayName }
          }
          so5Fixture { slug startDate }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def main():
    if not COOKIES:
        print('SORARE_COOKIE mancante: questa query legge dati dell\'account, '
              'non e\' pubblica. Lanciare su GitHub Actions.')
        sys.exit(1)

    nodi, after = [], None
    while len(nodi) < LIMITE:
        d = graphql(Q, {'first': min(50, LIMITE - len(nodi)), 'after': after})
        if d.get('errors'):
            print('ERRORE GraphQL:', json.dumps(d['errors'])[:400])
            print('\nLo schema e\' cambiato: serve adattare la query. '
                  'I campi disponibili si scoprono con una introspection.')
            sys.exit(2)
        cu = (d.get('data') or {}).get('currentUser') or {}
        conn = ((cu.get('so5') or {}).get('so5Lineups') or {})
        nuovi = conn.get('nodes') or []
        if not nuovi:
            break
        nodi.extend(nuovi)
        pi = conn.get('pageInfo') or {}
        if not pi.get('hasNextPage'):
            break
        after = pi.get('endCursor')

    print(f'partecipazioni lette: {len(nodi)}')
    per_tipo = collections.defaultdict(lambda: {'n': 0, 'somma_rank': 0})
    for n in nodi:
        lb = n.get('so5Leaderboard') or {}
        tipo = lb.get('displayName') or lb.get('slug') or '?'
        v = per_tipo[tipo]
        v['n'] += 1
        if n.get('rank'):
            v['somma_rank'] += n['rank']

    print(f'\n{"competizione":42s} {"n":>5} {"rank medio":>11}')
    for tipo, v in sorted(per_tipo.items(), key=lambda x: -x[1]['n']):
        rm = v['somma_rank'] / v['n'] if v['n'] else 0
        print(f'{tipo[:42]:42s} {v["n"]:>5} {rm:>11.1f}')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'aggiornato': datetime.datetime.utcnow().isoformat() + 'Z',
                   'partecipazioni': nodi}, f, ensure_ascii=False, indent=1)
    print(f'\nsalvato in {OUT}')


if __name__ == '__main__':
    main()
