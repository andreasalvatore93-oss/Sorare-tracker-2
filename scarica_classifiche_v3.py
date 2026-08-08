"""Scarica le classifiche complete delle arene (BRIEF_SONNET_SOGLIE_DEFINITIVE
+ decisioni utente 08/08 notte: lista ridotta invece di 6.006 slug, e
sessione HTTP DEDICATA invece di riusare quella di ricostruisci_manager).

CAUSA DEI 429 A RAFFICA (misurata in sessione, 08/08 notte): la sessione
condivisa di ricostruisci_manager._S era gia' stata "avvelenata" da query
precedenti senza CSRF (test_leaderboard_query.py e i tentativi falliti di
Haiku): senza x-csrf-token Sorare risponde con un Set-Cookie che assegna un
_sorare_session_id ANONIMO, che il barattolo dei cookie della sessione
salva e che poi VINCE sul Cookie passato a mano -- stesso bug gia'
documentato in discovery_fixture._grade_http() (righe 94-125). Fix: sessione
DEDICATA col barattolo svuotato ad ogni richiesta, header completi da client
web (discovery_fixture._headers_client_web(), righe 127-166), CSRF sempre
presente. Probe di autenticazione (currentUser) PRIMA di lanciare il batch,
per distinguere "rate limit vero" da "sessione morta" (la differenza conta:
sul primo si rallenta, sul secondo rallentare non serve a niente).

LISTA: Cap 220 e Uncapped COMPLETE (748+348), Cap 260 e Beginner CAMPIONATE
10 arene per fixture (33+37 fixture), precedenza alle arene con piu' di un
nostro manager (verificabili al controllo del punto 6 del brief originale).

RIPRENDIBILE: legge il file di output esistente e salta gli slug gia'
presenti. Salva a blocchi di 200.

Uso:
  export SORARE_COOKIE=... SORARE_CSRF=...
  python scarica_classifiche_v3.py
"""
import os
import sys
import json
import glob
import time
import collections
import datetime

try:
    from curl_cffi import requests as _rq
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as _rq
    _HAS_CURL_CFFI = False

GRAPHQL_URL = 'https://api.sorare.com/federation/graphql'
COOKIES = os.environ.get('SORARE_COOKIE', '')
CSRF = os.environ.get('SORARE_CSRF', '')
OUT_PATH = 'dati_globali/classifiche_arene_2026-08-08.json'
FALLITI_PATH = 'dati_globali/classifiche_arene_2026-08-08_falliti.json'
TIPI_ARENA = {'arena_limited', 'arena_limited_uncapped', 'arena_limited_beginner'}
COMP_VALIDE = {'Cap 260', 'Cap 220', 'Uncapped', 'Beginner'}
CAMPIONE_PER_FIXTURE = 10

_session = None


def _http():
    """Sessione DEDICATA, barattolo dei cookie sempre vuoto prima dell'uso
    (vedi docstring del modulo -- stesso fix di discovery_fixture._grade_http())."""
    global _session
    if _session is None:
        if _HAS_CURL_CFFI:
            _session = _rq.Session(impersonate='chrome')
        else:
            _session = _rq.Session()
    _session.cookies.clear()
    return _session


def _headers_client_web():
    """Header completi da client Web Sorare -- stesso set di
    discovery_fixture._headers_client_web(), copiato 1:1 (nato per lo stesso
    problema: da datacenter/sessione anonima Sorare pretende il set
    completo, non solo Cookie+CSRF)."""
    h = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'Origin': 'https://sorare.com',
        'Referer': 'https://sorare.com/',
        'Accept-Language': 'it',
        'sorare-client': 'Web',
        'sorare-version': os.environ.get('SORARE_VERSION', '20260717144535'),
        'sorare-build': os.environ.get(
            'SORARE_BUILD', '41952aef67694959421f5e001684878b72a52225'),
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if COOKIES:
        h['Cookie'] = COOKIES
    if CSRF:
        h['x-csrf-token'] = CSRF
    fp = os.environ.get('SORARE_DEVICE_FINGERPRINT', '')
    if fp:
        h['device_fingerprint'] = fp
    return h


def log(msg):
    print(f"[{datetime.datetime.utcnow().isoformat()}Z] [v3] {msg}", flush=True)


CONTATORE_429 = {'n': 0}


def graphql(query, variables):
    """Una query, backoff sui 429 (stessa logica di ricostruisci_manager.graphql,
    ma su sessione dedicata pulita ad ogni chiamata)."""
    headers = _headers_client_web()
    for tentativo in range(8):
        try:
            r = _http().post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                              headers=headers, timeout=60)
        except Exception as e:
            log(f"  rete: {e!r}, ritento")
            time.sleep(3 * (tentativo + 1))
            continue
        if r.status_code == 429:
            CONTATORE_429['n'] += 1
            attesa = min(int(r.headers.get('retry-after') or 0) or 2 ** tentativo * 3, 90)
            log(f"  rate limit, aspetto {attesa}s")
            time.sleep(attesa)
            continue
        try:
            return r.json()
        except Exception:
            return {'errors': [{'message': f'HTTP {r.status_code}'}]}
    return {'errors': [{'message': '429 dopo 8 tentativi'}]}


def probe_autenticazione():
    """currentUser: se torna null la sessione e' morta (rigenerare cookie/
    csrf), non un rate limit -- non ha senso rallentare in quel caso."""
    d = graphql('{ currentUser { slug } }', {})
    if d.get('errors'):
        return None, f"errore: {d['errors']}"
    cu = ((d.get('data') or {}).get('currentUser') or {}).get('slug')
    return cu, None


QUERY_CLASSIFICA = """
query Classifica($slug: String!) {
  so5 {
    so5Leaderboard(slug: $slug) {
      slug
      so5RankingsPaginated(page: 0) {
        pages
        nodes { ranking score }
      }
    }
  }
}
"""


def costruisci_lista():
    slug_info = {}
    manager_per_slug = collections.defaultdict(set)
    for f in glob.glob('dati_globali/manager_*.json'):
        d = json.load(open(f, encoding='utf-8'))
        if 'giornate' not in d:
            continue
        manager = os.path.basename(f)[len('manager_'):-len('.json')]
        for gw, righe in d['giornate'].items():
            for r in righe:
                if r.get('tipo_arena') in TIPI_ARENA and r.get('competizione') in COMP_VALIDE \
                        and r.get('leaderboard'):
                    slug = r['leaderboard']
                    slug_info[slug] = (r['competizione'], gw)
                    manager_per_slug[slug].add(manager)

    per_tipo_fixture = collections.defaultdict(lambda: collections.defaultdict(list))
    for slug, (tipo, gw) in slug_info.items():
        per_tipo_fixture[tipo][gw].append(slug)

    scelti = {}
    for slug, (tipo, gw) in slug_info.items():
        if tipo in ('Cap 220', 'Uncapped'):
            scelti[slug] = (tipo, gw, len(manager_per_slug[slug]))

    for tipo in ('Cap 260', 'Beginner'):
        for gw, slugs in per_tipo_fixture[tipo].items():
            slugs_ord = sorted(slugs, key=lambda s: (-len(manager_per_slug[s]), s))
            for slug in slugs_ord[:CAMPIONE_PER_FIXTURE]:
                scelti[slug] = (tipo, gw, len(manager_per_slug[slug]))

    return scelti, manager_per_slug


def carica_esistenti():
    if not os.path.exists(OUT_PATH):
        return {}
    try:
        d = json.load(open(OUT_PATH, encoding='utf-8'))
        return {a['slug']: a for a in d.get('arene', [])}
    except Exception:
        return {}


def salva(risultati, falliti):
    tmp = OUT_PATH + '.tmp'
    json.dump({'aggiornato': 'scarica_classifiche_v3.py', 'arene': list(risultati.values())},
               open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)
    json.dump(falliti, open(FALLITI_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def scarica_arena(slug, tipo):
    d = graphql(QUERY_CLASSIFICA, {'slug': slug})
    if d.get('errors'):
        return None, str(d['errors'])[:200]
    lb = ((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard')
    if not lb:
        return None, 'leaderboard assente (slug non trovato)'
    rp = lb.get('so5RankingsPaginated') or {}
    nodes = rp.get('nodes') or []
    punteggi = [n.get('score') for n in nodes if n.get('score') is not None]
    if not punteggi:
        return None, 'zero punteggi in risposta'
    return {'slug': slug, 'tipo': tipo, 'partecipanti': len(punteggi),
            'punteggi': punteggi, 'rank_premiati': {}}, None


def main():
    log(f'PROBE AUTENTICAZIONE (len cookie={len(COOKIES)}, len csrf={len(CSRF)})')
    cu, errore = probe_autenticazione()
    if errore:
        log(f'PROBE fallita: {errore}. Mi fermo, non ha senso continuare.')
        return 1
    log(f'currentUser = {cu!r}')
    if not cu:
        log('SESSIONE NON AUTENTICATA (currentUser=null). NON e\' un rate '
            'limit: rallentare non serve a niente. Serve un cookie/csrf validi.')
        return 1
    log('sessione autenticata, procedo.')

    scelti, _ = costruisci_lista()
    log(f'slug totali da scaricare (lista ridotta): {len(scelti)}')
    per_tipo = collections.Counter(t for t, _g, _n in scelti.values())
    log(f'per tipo: {dict(per_tipo)}')

    esistenti = carica_esistenti()
    log(f'gia\' presenti nel file (ripresa): {len(esistenti)}')

    da_fare = [(s, t) for s, (t, _g, _n) in scelti.items() if s not in esistenti]
    log(f'restano da scaricare: {len(da_fare)}')

    falliti = json.load(open(FALLITI_PATH, encoding='utf-8')) if os.path.exists(FALLITI_PATH) else []

    fatti_ora = 0
    for i, (slug, tipo) in enumerate(da_fare, 1):
        risultato, errore_finale = None, None
        for tentativo in range(3):
            risultato, errore_finale = scarica_arena(slug, tipo)
            if risultato is not None:
                break
        if risultato is not None:
            esistenti[slug] = risultato
            fatti_ora += 1
        else:
            falliti.append({'slug': slug, 'tipo': tipo, 'errore': errore_finale})

        if i == 100:
            log(f'--- CHECKPOINT primi 100: {fatti_ora} ok, {len(falliti)} falliti, '
                f'{CONTATORE_429["n"]} rate-limit (429) finora ---')
            if CONTATORE_429['n'] == 0:
                log('    zero 429 nei primi 100: si puo\' accelerare.')
            else:
                log('    almeno un 429 nei primi 100: ritmo gia\' al limite, non accelerare.')

        if i % 200 == 0 or i == len(da_fare):
            salva(esistenti, falliti)
            log(f'progresso: {i}/{len(da_fare)}  ok totali={len(esistenti)}  '
                f'falliti totali={len(falliti)}  429 totali={CONTATORE_429["n"]}')

    salva(esistenti, falliti)
    log(f'FINE. ok totali={len(esistenti)}  falliti totali={len(falliti)}  '
        f'429 totali={CONTATORE_429["n"]}')
    log(f'file: {OUT_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
