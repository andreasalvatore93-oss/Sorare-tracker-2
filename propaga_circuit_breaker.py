"""Propaga il circuit breaker CloudFront ai test_<ruolo>.py delle leghe che
non ce l'hanno (31/07, backlog).

COSA FA. Quando Sorare risponde HTTP 403 "Request blocked" non e' un errore
del singolo giocatore: e' un blocco IP/sessione, e ritentare con attese
progressive (10s + 20s + 40s per giocatore) non lo risolve -- si perdono solo
minuti. Il 29/07 questo ha fatto passare una run da ~4 a 22 minuti. Il circuit
breaker rileva il blocco una volta e per il resto del job fa un solo tentativo
secco per giocatore, senza attese.

Presente finora solo su mls e kleague. Qui viene applicato alle altre leghe
con una patch CHIRURGICA (non rigenerando i file da mls): i file delle leghe
piccole hanno anche una griglia di calibrazione diversa e altre differenze, e
sovrascriverli in blocco sarebbe un cambiamento molto piu' ampio di quello
chiesto.

Idempotente: se il file ha gia' il circuit breaker viene saltato.
Uso:  python propaga_circuit_breaker.py [--dry-run] [--solo <lega>]
"""
import glob
import os
import re
import sys

RUOLI = ('test_gk.py', 'test_def.py', 'test_mid.py', 'test_mls_fwd_all.py')
GIA_OK = ('mls', 'kleague')  # ce l'hanno gia'

# 1) Costanti + funzioni, inserite subito prima di COOKIES = os.environ.get(...)
BLOCCO_FUNZIONI = '''# Circuit breaker CloudFront (29/07, propagato a questa lega il 31/07): un
# HTTP 403 "Request blocked" NON e' un errore del singolo giocatore, e' un
# blocco IP/sessione -- ritentare con attese progressive non lo risolve e
# costa minuti (il 29/07 una run e' passata da ~4 a 22 minuti). Rilevato una
# volta, per il resto del job si fa un solo tentativo secco per giocatore.
# Il marker sta in /tmp ed e' per-lega/per-ruolo, quindi job diversi non si
# influenzano a vicenda.
_CIRCUIT_BREAKER_PATH = '/tmp/sorare_cloudfront_block_{lega}_{ruolo}.marker'


def _circuit_breaker_tripped():
    return os.path.exists(_CIRCUIT_BREAKER_PATH)


def _trip_circuit_breaker(reason):
    if not _circuit_breaker_tripped():
        try:
            with open(_CIRCUIT_BREAKER_PATH, 'w', encoding='utf-8') as f:
                f.write(reason)
        except OSError:
            pass


'''

# 2) Rilevamento del 403 dentro il ramo "HTTP >= 400" gia' esistente
ANCORA_403 = ('                log(f"[GraphQL ERRORE] {label} body (primi 1500 char): '
              '{resp.text[:1500]}")\n')
BLOCCO_403 = ('''                if resp.status_code == 403 and ('cloudfront' in resp.text.lower()
                                                or 'request blocked' in resp.text.lower()):
                    if not _circuit_breaker_tripped():
                        log(f"[CIRCUIT BREAKER] Blocco CloudFront rilevato (HTTP 403, "
                            f"'Request blocked') -- non e' un errore per-giocatore, e' un "
                            f"blocco IP/sessione che ritentare non risolve. Disattivo i "
                            f"retry con attesa per il resto di questa job.")
                    _trip_circuit_breaker(f"HTTP 403 CloudFront su {label}")
''')

# 3) Uso nel ciclo sui giocatori
ANCORA_CICLO = '''    for idx, slug in enumerate(slugs_to_process, 1):
        if idx > 1:
'''
BLOCCO_CICLO = '''    for idx, slug in enumerate(slugs_to_process, 1):
        breaker_active = _circuit_breaker_tripped()
        if idx > 1 and not breaker_active:
'''

ANCORA_RETRY = '        retry_delays = [10.0, 20.0, 40.0]\n'
BLOCCO_RETRY = '''        retry_delays = [] if breaker_active else [10.0, 20.0, 40.0]
        if breaker_active:
            log(f"[{slug}] Circuit breaker attivo (blocco CloudFront gia' rilevato in "
                f"questa job) -- salto i retry con attesa, un solo tentativo secco.")
'''


def patcha(path, lega, ruolo):
    src = open(path, encoding='utf-8', newline='').read()
    if '_CIRCUIT_BREAKER_PATH' in src:
        return 'gia-presente'
    nl = '\r\n' if '\r\n' in src else '\n'

    def conv(t):
        return t.replace('\n', nl) if nl != '\n' else t

    funzioni = conv(BLOCCO_FUNZIONI.format(lega=lega, ruolo=ruolo))
    anc_cookies = conv("COOKIES = os.environ.get('SORARE_COOKIE', '')\n")
    if src.count(anc_cookies) != 1:
        return f'ancora COOKIES non univoca ({src.count(anc_cookies)})'
    src = src.replace(anc_cookies, funzioni + anc_cookies)

    for ancora, blocco, nome in (
            (ANCORA_403, BLOCCO_403, '403'),
            (ANCORA_CICLO, BLOCCO_CICLO, 'ciclo'),
            (ANCORA_RETRY, BLOCCO_RETRY, 'retry')):
        a, b = conv(ancora), conv(blocco)
        if src.count(a) != 1:
            return f'ancora {nome} non univoca ({src.count(a)})'
        src = src.replace(a, (a + b) if nome == '403' else b)

    open(path, 'w', encoding='utf-8', newline='').write(src)
    return 'patchato'


def main():
    dry = '--dry-run' in sys.argv
    solo = None
    if '--solo' in sys.argv:
        solo = sys.argv[sys.argv.index('--solo') + 1]

    esiti = {}
    for d in sorted(glob.glob('formazione_*/predict')):
        lega = d.split(os.sep)[0].replace('formazione_', '')
        if lega in GIA_OK or (solo and lega != solo):
            continue
        for nome in RUOLI:
            path = os.path.join(d, nome)
            if not os.path.exists(path):
                continue
            ruolo = re.sub(r'^test_|_all|\.py$', '', nome).replace('mls_fwd', 'fwd')
            if dry:
                src = open(path, encoding='utf-8').read()
                esito = 'gia-presente' if '_CIRCUIT_BREAKER_PATH' in src else 'da-patchare'
            else:
                esito = patcha(path, lega, ruolo)
            esiti[esito] = esiti.get(esito, 0) + 1
            if esito not in ('patchato', 'gia-presente', 'da-patchare'):
                print(f"  PROBLEMA {path}: {esito}")
    print(f"{'[dry-run] ' if dry else ''}esiti: {esiti}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
