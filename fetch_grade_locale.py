"""Raccoglie i grade (A..F) DA LOCALE e li scrive in dati_globali/.

PERCHE' ESISTE (07/08/2026 notte, causa misurata, non dedotta).
La query myFilteredBench e' una query "my": ha bisogno della sessione
autenticata. Misurato lo stesso minuto, con lo STESSO cookie (2324 caratteri)
e lo STESSO CSRF (86):

    dal PC dell'utente    -> currentUser = 'crowss'  -> bench 50 nodi/pagina
    da GitHub Actions     -> currentUser = None      -> bench 0 nodi, HTTP 200

Cioe': il cookie e' giusto, ma Sorare non accetta quella sessione dagli IP dei
runner GitHub. Rigenerare i secret non cambia niente (gia' provato). Le carte
possedute invece si leggono con user(slug:) -- query PUBBLICA -- ed e' per
questo che la discovery sembrava funzionare mentre il grade era sempre a zero.

USO (dal PC dove sei loggato su Sorare):

    SORARE_COOKIE / SORARE_CSRF nell'ambiente, poi:
    python fetch_grade_locale.py <fixture_slug>

Scrive dati_globali/grade_<fixture_slug>.json. Va committato e pushato: la
discovery su GitHub lo legge da li' invece di interrogare l'API.
"""
import datetime
import json
import os
import sys

import discovery_fixture as df


def main():
    if len(sys.argv) < 2:
        print("uso: python fetch_grade_locale.py <fixture_slug>")
        print("esempio: python fetch_grade_locale.py football-7-11-aug-2026")
        return 2
    fixture_slug = sys.argv[1]

    if not df.base.COOKIES:
        print("ERRORE: SORARE_COOKIE non impostato nell'ambiente.")
        return 1

    # Prova che la sessione autentica DAVVERO prima di raccogliere: senza
    # questa riga un cookie morto produrrebbe un file di zero grade che
    # sembra legittimo (e' esattamente l'errore in cui siamo caduti su
    # GitHub Actions per giorni).
    h = {'Content-Type': 'application/json', 'Accept': 'application/json',
         'Cookie': df.base.COOKIES}
    if df.SORARE_CSRF:
        h['X-CSRF-Token'] = df.SORARE_CSRF
    r = df.base._http_session.post(
        df.base.GRAPHQL_URL, json={'query': '{ currentUser { slug } }'},
        headers=h, timeout=20)
    utente = ((r.json().get('data') or {}).get('currentUser') or {}).get('slug')
    if not utente:
        print("ERRORE: sessione non autenticata (currentUser e' null). "
              "Rinnova SORARE_COOKIE/SORARE_CSRF dal browser. Non scrivo nulla.")
        return 1
    print(f"[grade-locale] autenticato come '{utente}'")

    grade_map, copertura = df.fetch_grade_live(fixture_slug, usa_file=False)
    if not grade_map:
        print("ERRORE: zero grade raccolti. NON scrivo il file (un file vuoto "
              "farebbe girare G in fallback silenzioso).")
        return 1

    os.makedirs('dati_globali', exist_ok=True)
    path = df._grade_file_path(fixture_slug)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'fixture': fixture_slug,
            'raccolto_il': datetime.datetime.now().astimezone().isoformat(),
            'raccolto_da': utente,
            'copertura': copertura,
            'grade_map': grade_map,
        }, f, ensure_ascii=False, indent=1, sort_keys=True)

    dist = {}
    for g in grade_map.values():
        dist[g] = dist.get(g, 0) + 1
    print(f"[grade-locale] scritto {path}: {len(grade_map)} slug con grade")
    print(f"[grade-locale] distribuzione: "
          f"{dict(sorted(dist.items()))}")
    print(f"[grade-locale] nodi per leaderboard: {copertura}")
    print("[grade-locale] ORA: git add + commit + push, poi lancia la run.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
