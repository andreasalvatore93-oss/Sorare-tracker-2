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


def _csrf_dal_cookie(cookie_string):
    """Stessa logica di scanners/bot_profit.py: il token sta DENTRO il cookie,
    la variabile d'ambiente e' solo un ripiego. Usare solo quest'ultima faceva
    rispondere UNAUTHORIZED (01/08)."""
    for pair in (cookie_string or '').split(';'):
        pair = pair.strip()
        if pair.startswith('csrftoken='):
            return pair.split('=', 1)[1].strip()
    return None


CSRF = _csrf_dal_cookie(COOKIES) or os.environ.get('SORARE_CSRF', '')
FINGERPRINT = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:
    import requests as _rq
    _S = _rq.Session()

def _versione_corrente():
    """sorare-version e sorare-build cambiano ad ogni deploy del sito e nel
    repo erano fissati a mano (fermi al 17/07). Li leggiamo dalla home, cosi'
    non invecchiano: se la lettura fallisce restano i valori noti."""
    import re as _re
    ver = os.environ.get('SORARE_VERSION')
    build = os.environ.get('SORARE_BUILD')
    if ver and build:
        return ver, build
    try:
        r = _S.get('https://sorare.com/', timeout=30)
        html = r.text
        v = _re.findall(r'(\d{14})', html)
        b = _re.findall(r'([0-9a-f]{40})', html)
        if v and b:
            return v[0], b[0]
    except Exception:
        pass
    return '20260717144535', '41952aef67694959421f5e001684878b72a52225'


VERSIONE, BUILD = _versione_corrente()

# L'argomento si chiama groupType, non type: con 'type' Sorare risponde
# UNAUTHORIZED/timeout invece di segnalare l'errore di validazione, il che
# manda fuori strada. Verificato in chiaro il 01/08 (la validazione GraphQL
# avviene PRIMA dell'autenticazione, quindi la forma della query si prova
# senza cookie). myEligibleOrSo5Rewards e' una union: servono i frammenti.
Q_INDICE = """
query Indice($fixture: String!, $groupType: So5LeaderboardGroupType!) {
  so5 {
    so5Fixture(slug: $fixture) {
      slug
      endDate
      so5LeaderboardGroups(groupType: $groupType) {
        displayName
        mySo5LeaderboardContenders {
          slug
          so5Leaderboard { slug }
        }
        myEligibleOrSo5Rewards {
          ... on So5Reward {
            slug
            rewardConfigs {
              __typename
              ... on CardShardRewardConfig { quantity }
            }
          }
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
    # Stessi header di scanners/bot_profit.py: con i soli Content-Type/Cookie
    # Sorare risponde UNAUTHORIZED (01/08).
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'),
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': VERSIONE,
        'sorare-build': BUILD,
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    # Sorare lega la sessione al dispositivo: senza questo header il cookie e'
    # ben formato ma currentUser torna null. E' lo stesso segreto che usano i
    # bot che comprano davvero (autobuy, makeoffer), che infatti autenticano.
    if FINGERPRINT:
        headers['device_fingerprint'] = FINGERPRINT
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
    d = graphql(Q_INDICE, {'fixture': fixture,
                           'groupType': 'COMPETITION_WITH_ARENA'})
    if d.get('errors'):
        print(f'  {fixture}: errore indice -> {json.dumps(d["errors"])[:160]}')
        return [], None, {}
    fx = ((d.get('data') or {}).get('so5') or {}).get('so5Fixture') or {}
    out, premi = [], {}
    for g in fx.get('so5LeaderboardGroups') or []:
        # I premi effettivamente presi: lo slug e' <classifica>-rank-<N> e la
        # quantita' e' in frammenti, che per Sorare SONO le essenze (chiarito
        # dall'utente il 01/08).
        for r in g.get('myEligibleOrSo5Rewards') or []:
            m = re.match(r'(.+)-rank-(\d+)', r.get('slug') or '')
            if not m:
                continue
            q = 0
            for rc in r.get('rewardConfigs') or []:
                q += rc.get('quantity') or 0
            if q:
                premi[m.group(1)] = (int(m.group(2)), q)
        for c in g.get('mySo5LeaderboardContenders') or []:
            slug = ((c.get('so5Leaderboard') or {}).get('slug')) or ''
            nome, costo = tipo_arena(slug)
            if nome:
                out.append((slug, nome, costo))
    return out, fx.get('endDate'), premi


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
    nomi = [c.strip().split('=', 1)[0] for c in COOKIES.split(';') if '=' in c]
    print(f'cookie: {len(COOKIES)} caratteri, {len(nomi)} voci -> {", ".join(nomi)}')
    print(f'csrf: {"presente" if CSRF else "ASSENTE"} | '
          f'device_fingerprint: {"presente" if FINGERPRINT else "ASSENTE"}')
    print(f'sorare-version {VERSIONE} | build {BUILD[:12]}...')
    # La prova del nove: se currentUser e' null il cookie non autentica, per
    # quanto sia lungo. Il bot di mercato non se ne accorge perche' legge solo
    # dati pubblici (prezzi, offerte): non interroga mai un campo 'my*'.
    chi = graphql('{ currentUser { nickname } }', {})
    utente = ((chi.get('data') or {}).get('currentUser') or {}).get('nickname')
    if not utente:
        print('NON AUTENTICATO: currentUser torna null. Le classifiche arene '
              'non sono pubbliche, quindi senza login qui non si ricava nulla.')
        sys.exit(2)
    print(f'autenticato come {utente}')

    io = os.environ.get('NICKNAME', '').strip().lower()
    raccolta = []
    for fx in fixtures:
        arene, fine, premi = arene_della_giornata(fx)
        print(f'\n=== {fx} ({fine}) -- {len(arene)} arene')
        for slug, nome, costo in arene:
            nodi = classifica(slug)
            if not nodi:
                print(f'  {nome:10s} classifica vuota (serve il cookie)')
                continue
            punteggi = sorted((n['score'] for n in nodi), reverse=True)
            mia = next((n for n in nodi
                        if (n.get('user') or {}).get('nickname', '').lower() == io), None)
            rank_premio, essenze = premi.get(slug, (None, 0))
            riga = {'fixture': fx, 'fine': fine, 'slug': slug, 'tipo': nome,
                    'costo': costo, 'partecipanti': len(nodi),
                    'premio_essenze': essenze, 'rank_premiato': rank_premio,
                    'punteggi': punteggi,
                    'mio_rank': mia.get('ranking') if mia else None,
                    'mio_score': mia.get('score') if mia else None}
            raccolta.append(riga)
            m = f"| tu {riga['mio_rank']}o con {riga['mio_score']:.1f}" if mia else ''
            if essenze:
                m += f" | premio {essenze} essenze (netto {essenze - costo:+d})"
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
