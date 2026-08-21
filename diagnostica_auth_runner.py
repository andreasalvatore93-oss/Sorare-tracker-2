"""Isola PERCHE' Sorare risponde timeout/UNAUTHORIZED, girando SUL RUNNER.

Nato dall'errore E1 di CLAUDE_ERRORS.md (14/08/2026): quel giorno le run
fallivano con timeout/UNAUTHORIZED, la stessa query provata dal PC di casa con
un cookie fresco funzionava, e si e' concluso "e' il cookie scaduto" avendo
cambiato TRE variabili insieme (cookie nuovo + macchina diversa + niente
APIKEY). Non isolava niente: restavano in piedi cookie scaduto, chiave
revocata e IP dei runner strozzato.

Questo script cambia UNA variabile per volta, dalla stessa macchina che fa
fallire la pipeline (il runner GitHub), sulla stessa URL e con la stessa query
pubblica che la discovery usa per risolvere la giornata (so5Fixtures).

Lettura dell'esito:
  - anonimo FALLISCE          -> non sono le credenziali: e' l'IP del runner
                                 (o Sorare giu'). Rifare il cookie non serve.
  - anonimo OK, cookie KO     -> cookie scaduto: rifare il secret SORARE_COOKIE.
  - anonimo OK, apikey KO     -> chiave revocata: rigenerarla dal pannello
                                 Developer di Sorare.
  - tutto OK                  -> il guasto era transitorio, non riproducibile
                                 adesso: non toccare niente.
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = 'https://api.sorare.com/graphql'  # la stessa di turchia_gk_discovery.base
QUERY = """
query FixtureList($first: Int!) {
  so5 { so5Fixtures(first: $first) { nodes { slug seasonGameWeek aasmState } } }
}
"""

COOKIE = os.environ.get('SORARE_COOKIE', '')
APIKEY = os.environ.get('SORARE_APIKEY', '')
CSRF = os.environ.get('SORARE_CSRF', '')


def prova(nome, headers):
    h = {'Content-Type': 'application/json',
         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    h.update(headers)
    payload = {'query': QUERY, 'variables': {'first': 3},
               'operationName': 'FixtureList'}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=h)
    try:
        raw = urllib.request.urlopen(req, timeout=20).read().decode()
    except urllib.error.HTTPError as e:
        print(f"  {nome:22s} HTTP {e.code}  {e.read().decode()[:200]}")
        return False
    except Exception as e:  # rete, DNS, timeout lato client
        print(f"  {nome:22s} ECCEZIONE {type(e).__name__}: {e}")
        return False
    d = json.loads(raw)
    if d.get('errors'):
        print(f"  {nome:22s} KO   errors={json.dumps(d['errors'])[:220]}")
        return False
    nodi = (d.get('data') or {}).get('so5', {}).get('so5Fixtures', {}).get('nodes') or []
    print(f"  {nome:22s} OK   {len(nodi)} fixture, prima={nodi[0]['slug'] if nodi else '-'}")
    return True



# ---------------------------------------------------------------------------
# FASE B (21/08/2026): la fase A qui sopra usa urllib, la produzione usa
# curl_cffi con impersonate="chrome". Client diverso = fingerprint diverso, e
# Sorare tratta i due in modo diverso: la fase A ha gia' mostrato un 302 sulla
# combinazione completa che il browser-fake non prende. Quindi la stessa
# domanda va rifatta DENTRO il client vero, cambiando una variabile sola: il
# CSRF acceso/spento nel modulo che la pipeline importa come `base`.
# ---------------------------------------------------------------------------

def fase_b():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'formazione_turchia', 'discovery'))
    try:
        import turchia_gk_discovery as base
    except Exception as e:
        print(f"  [fase B] import del modulo di produzione fallito: {e}")
        return {}

    print(f"  [fase B] client={'curl_cffi(chrome)' if getattr(base, '_HAS_CURL_CFFI', False) else 'requests'}")
    esiti = {}

    def giro(nome, csrf, cookie, apikey):
        base.CSRF_TOKEN, base.COOKIES, base.APIKEY = csrf, cookie, apikey
        try:
            d = base.graphql_query(QUERY, {"first": 3}, operation_name="FixtureList")
        except Exception as e:
            print(f"  {nome:22s} ECCEZIONE {type(e).__name__}: {e}")
            return False
        # graphql_query ritorna il JSON INTERO (con la chiave 'data'), non il data.
        nodi = ((((d or {}).get('data') or {}).get('so5') or {}).get('so5Fixtures') or {}).get('nodes') or []
        # graphql_query ritorna {} sia su errore sia su vuoto: distinguerli non
        # si puo' da qui, e per questa query "vuoto" non esiste -- {} = KO.
        print(f"  {nome:22s} {'OK  ' if nodi else 'KO  '} {len(nodi)} fixture")
        return bool(nodi)

    esiti['prod_completo'] = giro('PROD cookie+key+CSRF', CSRF, COOKIE, APIKEY)
    esiti['prod_senza_csrf'] = giro('PROD senza CSRF', '', COOKIE, APIKEY)
    esiti['prod_solo_cookie'] = giro('PROD solo cookie', '', COOKIE, '')
    esiti['prod_anonimo'] = giro('PROD anonimo', '', '', '')
    return esiti


def main():
    print(f"[probe] URL={URL}")
    print(f"[probe] secret presenti: cookie={'si' if COOKIE else 'NO'} "
          f"({len(COOKIE)} char), apikey={'si' if APIKEY else 'NO'}, "
          f"csrf={'si' if CSRF else 'NO'}")
    esiti = {}
    esiti['anonimo'] = prova('anonimo', {})
    if APIKEY:
        esiti['apikey'] = prova('solo APIKEY', {'APIKEY': APIKEY})
    if COOKIE:
        esiti['cookie'] = prova('solo cookie', {'Cookie': COOKIE})
    if COOKIE and APIKEY:
        esiti['cookie+apikey'] = prova('cookie+APIKEY', {'Cookie': COOKIE, 'APIKEY': APIKEY})
    if COOKIE and APIKEY and CSRF:
        esiti['completo'] = prova('cookie+APIKEY+CSRF',
                                  {'Cookie': COOKIE, 'APIKEY': APIKEY, 'x-csrf-token': CSRF})

    print("\n[fase B] stesso client della produzione (curl_cffi impersonate):")
    esiti_b = fase_b()

    print("\n[verdetto]")
    if esiti_b and not esiti_b.get('prod_completo') and esiti_b.get('prod_senza_csrf'):
        print("  PRODUZIONE: passa senza CSRF e fallisce col CSRF -> il secret")
        print("  SORARE_CSRF non e' piu' appaiato al cookie. Azione: riprendere")
        print("  cookie e CSRF INSIEME dalla stessa sessione del browser.")
    elif esiti_b and all(esiti_b.values()):
        print("  PRODUZIONE: passa in tutte le combinazioni ADESSO -> il guasto")
        print("  delle 18:13-18:39 non e' riproducibile: transitorio lato Sorare.")
        print("  Rilanciare la pipeline prima di toccare qualunque secret.")
    elif not esiti.get('anonimo'):
        print("  L'anonimo NON passa: non sono le credenziali. Sospetti: IP dei")
        print("  runner GitHub strozzato da Sorare, o Sorare indisponibile.")
        print("  Rifare il cookie NON risolve.")
    elif esiti.get('cookie') is False:
        print("  Anonimo OK ma col cookie no: COOKIE SCADUTO/INVALIDO.")
        print("  Azione: aggiornare il secret SORARE_COOKIE (e SORARE_CSRF preso")
        print("  nella stessa sessione del browser).")
    elif esiti.get('apikey') is False:
        print("  Anonimo OK ma con la sola APIKEY no: CHIAVE NON VALIDA/REVOCATA.")
        print("  Azione: rigenerarla dal pannello Developer di Sorare.")
    elif all(esiti.values()):
        print("  Tutte le combinazioni passano ADESSO: guasto transitorio, non")
        print("  riproducibile. Non toccare i secret, rilanciare la pipeline.")
    else:
        ko = [k for k, v in esiti.items() if not v]
        print(f"  Combinazioni fallite: {ko}. Guardare gli errori qui sopra.")
    # Esce sempre 0: e' una diagnosi, non un gate.
    return 0


if __name__ == '__main__':
    sys.exit(main())
