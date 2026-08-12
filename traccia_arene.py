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
import time

APIKEY = os.environ.get('SORARE_APIKEY', '')  # 12/08/2026: alza il tetto di complessita' e di richieste dell'account

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
PAUSA = float(os.environ.get('PAUSA_SECONDI', '0.35'))
_ultima = [0.0]


def _pausa():
    dt = time.time() - _ultima[0]
    if dt < PAUSA:
        time.sleep(PAUSA - dt)
    _ultima[0] = time.time()

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
        v = _re.findall(r'(?<![0-9])(\d{14})(?![0-9])', html)
        b = _re.findall(r'(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])', html)
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
        nodes { ranking score user { slug nickname } }
      }
    }
  }
}
"""

# Tipi di arena che ci interessano oggi (scelta esplicita dell'utente: cap 220
# e le altre restano fuori per non accumulare troppa roba).
# Costo d'ingresso noto solo per le arene che l'utente gioca abitualmente.
# L'ordine conta: le chiavi piu' lunghe vanno provate per prime, altrimenti
# 'arena_limited' cattura anche 'arena_limited_cap_220'.
TIPI = {
    'arena_limited_beginner': ('Beginner', 100),
    'arena_limited_uncapped': ('Uncapped', 300),
    'arena_limited_cap_220': ('cap 220', 200),
    'arena_limited': ('cap 260', 300),
}


def tipo_arena(slug):
    """Nome e costo di un'arena a partire dallo slug della sua classifica.

    ATTENZIONE: prima qui si tornava (None, None) per gli slug non elencati, e
    chi chiamava li scartava in silenzio. Cosi' sparivano tutte le arene rare e
    super rare: intere giornate del 2025 risultavano '0 arene' pur avendone
    fino a otto. Ora l'ultima parola e' allo slug: se contiene 'arena' e'
    un'arena, con un nome ricavato dallo slug e costo ignoto (None).
    """
    for chiave in sorted(TIPI, key=len, reverse=True):
        if chiave in slug:
            return TIPI[chiave]
    if 'arena' in slug:
        coda = slug.rsplit('arena', 1)[1].strip('_-')
        # lo slug finisce con l'UUID dell'arena: va tolto, se no ogni arena
        # diventerebbe un tipo a se'
        coda = coda.split('-')[0] if coda else ''
        return ('arena ' + coda).strip(), None
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
    if APIKEY:
        headers['APIKEY'] = APIKEY
    if CSRF:
        headers['x-csrf-token'] = CSRF
    for tentativo in range(5):
        _pausa()
        r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                    headers=headers, timeout=60)
        if r.status_code == 429:
            # ricostruire lo storico intero sono migliaia di richieste:
            # senza attesa crescente Sorare chiude il rubinetto a meta' lavoro
            attesa = min(2 ** tentativo * 3, 60)
            print(f'    rate limit, aspetto {attesa}s')
            time.sleep(attesa)
            continue
        try:
            return r.json()
        except Exception:
            return {'errors': [{'message': f'HTTP {r.status_code}'}]}
    return {'errors': [{'message': 'HTTP 429 dopo 5 tentativi'}]}


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
                # LISTA, non valore singolo: nella stessa arena si possono
                # avere fino a 3 formazioni (capita schierando in fretta:
                # finiscono nello stesso pool da 10), quindi i premi vinti
                # possono essere piu' d'uno. Tenendone uno solo se ne perdeva
                # uno e lo si duplicava sull'altra formazione.
                premi.setdefault(m.group(1), []).append((int(m.group(2)), q))
        for c in g.get('mySo5LeaderboardContenders') or []:
            slug = ((c.get('so5Leaderboard') or {}).get('slug')) or ''
            nome, costo = tipo_arena(slug)
            if nome:
                # lo slug del contender identifica la FORMAZIONE schierata:
                # serve per rileggerla e misurare quanto ci prende il modello
                out.append((slug, nome, costo, c.get('slug')))
    return out, fx.get('endDate'), premi


def classifica(slug):
    # ATTENZIONE: so5RankingsPaginated indicizza le pagine da ZERO. Partendo
    # da 1 su un'arena da 10 (una pagina sola) si chiede una pagina oltre la
    # fine e torna vuota: sembra un problema di permessi, non lo e'.
    nodi, page = [], 0
    while True:
        d = graphql(Q_CLASSIFICA, {'slug': slug, 'page': page})
        if d.get('errors'):
            return nodi
        pag = ((((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard') or {})
               .get('so5RankingsPaginated') or {})
        nodi.extend(pag.get('nodes') or [])
        if page >= (pag.get('pages') or 1) - 1:
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
        for slug, nome, costo, _cs in arene:
            nodi = classifica(slug)
            if not nodi:
                print(f'  {nome:10s} classifica vuota (serve il cookie)')
                continue
            nodi_ord = sorted(nodi, key=lambda n: n['score'], reverse=True)
            punteggi = [n['score'] for n in nodi_ord]
            partecipanti_dett = [{'punteggio': n['score'],
                                  'nickname': (n.get('user') or {}).get('nickname'),
                                  'slug': (n.get('user') or {}).get('slug')}
                                 for n in nodi_ord]
            mia = next((n for n in nodi
                        if (n.get('user') or {}).get('nickname', '').lower() == io), None)
            premi_lista = premi.get(slug, [])
            rank_premio, essenze = premi_lista[0] if premi_lista else (None, 0)
            riga = {'fixture': fx, 'fine': fine, 'slug': slug, 'tipo': nome,
                    # la mediana e' il numero che serve al consigliere
                    # d'ingresso: e' il campo da battere in quella arena
                    'mediana': statistics.median(punteggi),
                    'primo': punteggi[0], 'terzo': punteggi[2],
                    'costo': costo, 'partecipanti': len(nodi),
                    'premio_essenze': essenze, 'rank_premiato': rank_premio,
                    'punteggi': punteggi,
                    'partecipanti_dett': partecipanti_dett,
                    'mio_rank': mia.get('ranking') if mia else None,
                    'mio_score': mia.get('score') if mia else None}
            raccolta.append(riga)
            m = f"| tu {riga['mio_rank']}o con {riga['mio_score']:.1f}" if mia else ''
            if essenze:
                netto = f' (netto {essenze - costo:+d})' if costo else ''
                m += f' | premio {essenze} essenze{netto}'
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
