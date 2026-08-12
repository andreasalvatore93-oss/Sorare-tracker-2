# -*- coding: utf-8 -*-
"""50 carte per richiesta danno DAVVERO le stesse carte di 20?

Il rischio da escludere prima di mandarlo in produzione: che il server
accetti pageSize=50, ne restituisca meno, e dichiari nbPages come se le
avesse date tutte. In quel caso la paginazione finirebbe troppo presto e si
perderebbero carte IN SILENZIO -- il difetto peggiore possibile, perche' la
run resta verde.

Scarica lo stesso ruolo due volte, a 20 e a 50 per pagina, e confronta gli
INSIEMI di slug. Sono ~8 richieste in tutto.

    python prova_pagesize.py <Goalkeeper|Defender|Midfielder|Forward>

Legge il cookie da C:\\Users\\Andrea\\Downloads\\cookie.txt.
La chiave, se c'e', dall'ambiente SORARE_APIKEY. Non stampa ne' l'uno ne'
l'altra.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
import discovery_fixture as DF

POSIZIONE = sys.argv[1] if len(sys.argv) > 1 else 'Goalkeeper'
COOKIE = r'C:\Users\Andrea\Downloads\cookie.txt'

try:
    from curl_cffi import requests as R
    S = R.Session(impersonate='chrome')
except ImportError:
    import requests as R
    S = R.Session()

# Il file esportato dal browser ha una riga di intestazione ("cookie") e il
# valore vero sotto: prendendo tutto si manda un header invalido e curl_cffi
# muore con l'errore 43, che non dice niente di utile.
cookie = [l.strip() for l in open(COOKIE, encoding='utf-8') if l.strip()][-1]
apikey = os.environ.get('SORARE_APIKEY', '')
head = {'Content-Type': 'application/json', 'Cookie': cookie}
if apikey:
    head['APIKEY'] = apikey
print('cookie: presente (%d caratteri) | APIKEY: %s'
      % (len(cookie), 'presente' if apikey else 'assente'))

USER = os.environ.get('SORARE_USER_SLUG', 'crowss')


def scarica(page_size):
    slugs, pagina, nb_pages, nb_hits, richieste = set(), 1, 1, None, 0
    while pagina <= nb_pages and pagina <= 40:
        v = {'userSlug': USER, 'page': pagina, 'pageSize': page_size,
             'advancedFilters': None,
             'refinements': [{'field': 'position', 'operator': 'EQUAL',
                              'values': [{'stringValue': POSIZIONE}]}]}
        r = S.post('https://api.sorare.com/graphql',
                   json={'query': DF.CARDS_QUERY, 'variables': v,
                         'operationName': 'FixtureCards'},
                   headers=head, timeout=30)
        richieste += 1
        d = r.json()
        if d.get('errors'):
            print('  ERRORE GraphQL a pageSize=%d: %s'
                  % (page_size, json.dumps(d['errors'])[:200]))
            return None, richieste, None
        s = ((d.get('data') or {}).get('user') or {}).get('searchCards') or {}
        hits = s.get('hits') or []
        nb_pages = s.get('nbPages') or 1
        nb_hits = s.get('nbHits')
        print('  pageSize=%2d pagina %2d/%2d -> %2d carte'
              % (page_size, pagina, nb_pages, len(hits)))
        for h in hits:
            slugs.add(h.get('slug'))
        pagina += 1
        time.sleep(0.4)
    return slugs, richieste, nb_hits


print('')
print('--- a 20 per pagina (com\'era) ---')
a, ra, ha = scarica(20)
print('--- a 50 per pagina (come adesso, con la chiave) ---')
b, rb, hb = scarica(50)

print('')
print('=' * 64)
if a is None or b is None:
    print('una delle due e\' fallita: NON promuovere il cambio')
    sys.exit(1)
print('  carte a 20 : %d (nbHits dichiarato %s) in %d richieste' % (len(a), ha, ra))
print('  carte a 50 : %d (nbHits dichiarato %s) in %d richieste' % (len(b), hb, rb))
print('  solo a 20  : %d %s' % (len(a - b), sorted(a - b)[:5]))
print('  solo a 50  : %d %s' % (len(b - a), sorted(b - a)[:5]))
print('')
if a == b:
    print('  IDENTICHE: 50 e\' sicuro, e costa %d richieste invece di %d.'
          % (rb, ra))
else:
    print('  DIVERSE: NON usare 50, si perdono carte. Rimettere PAGE_SIZE.')
