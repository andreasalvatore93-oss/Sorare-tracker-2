"""Storico completo delle arene: quali hai giocato, come sono andate, com'era il campo.

A COSA SERVE. Per decidere se conviene pagare l'ingresso di un'arena serve
sapere quanto e' forte il campo. Finche' lo si simulava con le stesse carte
dell'utente il vantaggio usciva zero per costruzione; con questi dati non si
stima piu' niente, si misura. Sostituisce SorareScore, che ha smesso di
aggiornarsi e di cui non si conosce nemmeno la data dell'ultimo aggiornamento.

QUERY (catturate dalle DevTools il 01/08 -- l'introspection su Sorare e'
disabilitata, quindi i nomi dei campi vengono da li' e non sono indovinati):

  1. ArenaBoardFixtureLineupsPageQuery(fixture, groupType, sport)
     -> per ogni giornata, TUTTE le formazioni dell'utente con lo slug della
        loro classifica. E' l'indice: da qui si ricavano le arene giocate.
  2. so5Leaderboard(slug).so5RankingsPaginated(page)
     -> la classifica completa: ranking, punteggio, avversari.
  3. so5LeaderboardContender(slug).so5Leaderboard.rewardsConfig
     -> premi per posizione e punteggio di chi occupa quella posizione.

NOTA: le classifiche NON sono pubbliche. Senza cookie la query risponde ma
torna vuota, quindi questo gira su GitHub Actions dove i segreti ci sono.

Uso:  FIXTURES=football-24-28-jul-2026,football-17-21-jul-2026 python traccia_arene.py
"""
import collections
import datetime
import json
import os
import re
import statistics
import sys

GRAPHQL_URL = 'https://api.sorare.com/graphql'
OUT = 'dati_globali/arene_storico.json'
COOKIES = os.environ.get('SORARE_COOKIE', '')
CSRF = os.environ.get('SORARE_CSRF', '')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()

Q_INDICE = """
query Indice($fixture: String!) {
  so5 {
    so5Fixture(slug: $fixture) {
      slug
      endDate
      so5LeaderboardGroups(type: COMPETITION_WITH_ARENA) {
        displayName
        mySo5LeaderboardContenders {
          slug
          so5Leaderboard { slug }
        }
      }
    }
  }
}
"""

Q_CLASSIFICA = """
query Classifica($slug: String!, $page: Int) {
  so5 {
    so5Leaderboard(slug: $slug) {
      so5RankingsPaginated(page: $page) {
        pages
        nodes { ranking score user { nickname } }
      }
    }
  }
}
"""

# Tipi di arena che ci interessano oggi (scelta esplicita dell'utente: cap 220
# e le altre restano fuori per non accumulare troppa roba).
TIPI = {
    'arena_limited_beginner': ('Beginner', 100),
    'arena_limited_uncapped': ('Uncapped', 300),
    'arena_limited_cap_220': ('cap 220', 200),
    'arena_limited': ('cap 260', 300),   # va testato per ultimo: e' un prefisso
}


def tipo_arena(slug):
    for chiave, (nome, costo) in TIPI.items():
        if chiave in slug:
            return nome, costo
    return None, None


def graphql(query, variables):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'sorare-client': 'Web',
    }
    if COOKIES:
        headers['Cookie'] = COOKIES
    if CSRF:
        headers['x-csrf-token'] = CSRF
    r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                headers=headers, timeout=60)
    try:
        return r.json()
    except Exception:
        return {'errors': [{'message': f'HTTP {r.status_code}'}]}


def arene_della_giornata(fixture):
    """[(slug_classifica, tipo, costo)] delle arene giocate in quella giornata."""
    d = graphql(Q_INDICE, {'fixture': fixture})
    if d.get('errors'):
        print(f'  {fixture}: errore indice -> {json.dumps(d["errors"])[:160]}')
        return [], None
    fx = ((d.get('data') or {}).get('so5') or {}).get('so5Fixture') or {}
    out = []
    for g in fx.get('so5LeaderboardGroups') or []:
        for c in g.get('mySo5LeaderboardContenders') or []:
            slug = ((c.get('so5Leaderboard') or {}).get('slug')) or ''
            nome, costo = tipo_arena(slug)
            if nome:
                out.append((slug, nome, costo))
    return out, fx.get('endDate')


def classifica(slug):
    nodi, page = [], 1
    while True:
        d = graphql(Q_CLASSIFICA, {'slug': slug, 'page': page})
        if d.get('errors'):
            return nodi
        pag = ((((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard') or {})
               .get('so5RankingsPaginated') or {})
        nodi.extend(pag.get('nodes') or [])
        if page >= (pag.get('pages') or 1):
            break
        page += 1
    return nodi


def main():
    fixtures = [x.strip() for x in os.environ.get('FIXTURES', '').split(',') if x.strip()]
    if not fixtures:
        print('Passare FIXTURES=<slug-giornata>[,<altro>]')
        sys.exit(1)
    if not COOKIES:
        print('ATTENZIONE: senza SORARE_COOKIE le classifiche tornano vuote.')

    io = os.environ.get('NICKNAME', '').strip().lower()
    raccolta = []
    for fx in fixtures:
        arene, fine = arene_della_giornata(fx)
        print(f'\n=== {fx} ({fine}) -- {len(arene)} arene')
        for slug, nome, costo in arene:
            nodi = classifica(slug)
            if not nodi:
                print(f'  {nome:10s} classifica vuota (serve il cookie)')
                continue
            punteggi = sorted((n['score'] for n in nodi), reverse=True)
            mia = next((n for n in nodi
                        if (n.get('user') or {}).get('nickname', '').lower() == io), None)
            riga = {'fixture': fx, 'fine': fine, 'slug': slug, 'tipo': nome,
                    'costo': costo, 'partecipanti': len(nodi),
                    'punteggi': punteggi,
                    'mio_rank': mia.get('ranking') if mia else None,
                    'mio_score': mia.get('score') if mia else None}
            raccolta.append(riga)
            m = f"| tu {riga['mio_rank']}o con {riga['mio_score']:.1f}" if mia else ''
            print(f'  {nome:10s} {len(nodi):>2} partecipanti | 1o {punteggi[0]:6.1f} '
                  f'| 3o {punteggi[2]:6.1f} | mediana {statistics.median(punteggi):6.1f} {m}')

    if not raccolta:
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'aggiornato': datetime.datetime.utcnow().isoformat() + 'Z',
                   'arene': raccolta}, f, ensure_ascii=False, indent=1)

    print('\n=== CAMPO PER TIPO')
    per_tipo = collections.defaultdict(list)
    for r in raccolta:
        per_tipo[r['tipo']].extend(r['punteggi'])
    for tipo, v in sorted(per_tipo.items()):
        print(f'  {tipo:10s} {len(v):>4} formazioni | media {statistics.mean(v):6.1f} '
              f'| dev.std {statistics.pstdev(v):5.1f}')
    print(f'\nsalvato in {OUT}')


if __name__ == '__main__':
    main()
