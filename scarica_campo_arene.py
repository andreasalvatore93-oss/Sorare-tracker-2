"""scarica_campo_arene -- le formazioni di TUTTI i partecipanti alle arene
dell'archivio, non solo le nostre. Il campo di prova diventa 6.730 formazioni
pubbliche invece di 673.

Perche' esiste
---------------
`scarica_formazioni_arene.py` scarica solo LE NOSTRE 673 formazioni (una per
arena giocata). Ogni arena pero' ha altri ~9 partecipanti, tutti pubblici e
gia' individuati dallo slug della leaderboard salvato in `arene_storico.json`
(campo `slug`, es. "football-25-29-jul-2025-global-arena-division-747"). Da
quello slug si legge l'intera classifica in una query sola: nessun cookie
richiesto, ne' per la lista ne' per le formazioni.

Serve per due cose diverse da `ricostruisci_manager.py` (che ricostruisce UN
manager su TUTTE le sue competizioni): qui e' IL CAMPO di una singola arena,
tutti i partecipanti, per capire come sono fatte le formazioni che vincono e
avere un campione enorme per la calibrazione.

Uso
---
    python scarica_campo_arene.py
    python scarica_campo_arene.py --max 20      # prova rapida

Accumula su `dati_globali/campo_arene.json`, riprende da dove si era fermato.
"""
import os
import sys
import json
import time
import argparse
import datetime
import collections

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
ARCHIVIO = os.path.join(REPO_ROOT, 'dati_globali', 'arene_storico.json')
OUT = os.path.join(REPO_ROOT, 'dati_globali', 'campo_arene.json')
GRAPHQL_URL = 'https://api.sorare.com/federation/graphql'
PAUSA = float(os.environ.get('CAMPO_PAUSA', '1.0'))

if hasattr(sys.stdout, 'buffer'):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:                 # pragma: no cover
    import requests as _rq
    _S = _rq.Session()

# Tutto pubblico: nessun cookie. Se la query intera (classifica + formazioni
# annidate) sfora il limite di complessita' senza autenticazione, la soluzione
# nota (vedi RIASSUNTO 50.8) e' spezzarla in due passi: prima gli id di
# so5Lineup con questa stessa query ma senza i campi profondi, poi node(id:)
# per ognuno. Si prova prima la via diretta perche' e' un'unica richiesta per
# leaderboard.
CAMPO_QUERY = """
query Campo($slug: String!, $after: String) {
  so5 {
    so5Leaderboard(slug: $slug) {
      slug
      so5LeaderboardContenders(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          slug
          so5Lineup {
            user { slug }
            so5Appearances {
              score
              position
              captain
              player { slug displayName activeClub { slug name } }
              anyCard {
                slug
                rarityTyped
                ... on Card {
                  xp
                  powerBreakdown {
                    seasonBasisPoints
                    collectionBasisPoints
                    xpBasisPoints
                    scarcityBasisPoints
                    specialEditionCardsBasisPoints
                    activeClubsBasisPoints
                    nationalityBasisPoints
                    positionsBasisPoints
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def log(msg):
    print(f"[{datetime.datetime.utcnow().isoformat()}Z] [campo] {msg}", flush=True)


def graphql(query, variables):
    intestazioni = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    for tentativo in range(5):
        time.sleep(PAUSA)
        try:
            r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                        headers=intestazioni, timeout=60)
        except Exception as e:
            log(f"  rete: {e!r}, ritento")
            time.sleep(3 * (tentativo + 1))
            continue
        if r.status_code == 429:
            attesa = min(2 ** tentativo * 3, 60)
            log(f"  rate limit, aspetto {attesa}s")
            time.sleep(attesa)
            continue
        try:
            return r.json()
        except Exception:
            return {'errors': [{'message': f'HTTP {r.status_code}: {r.text[:200]}'}]}
    return {'errors': [{'message': '429 dopo 5 tentativi'}]}


def _bonus_carta(carta):
    pb = carta.get('powerBreakdown') or {}
    return round(sum(v or 0 for k, v in pb.items() if k.endswith('BasisPoints')) / 10000.0, 4)


def campo(leaderboard_slug):
    """Tutte le formazioni della classifica. [] se la leaderboard non esiste
    piu' o la query fallisce (arene molto vecchie a volte scadono)."""
    fuori, after = [], None
    for _pagina in range(5):
        d = graphql(CAMPO_QUERY, {'slug': leaderboard_slug, 'after': after})
        if d.get('errors'):
            log(f"  ERRORE {leaderboard_slug}: {str(d['errors'])[:200]}")
            return fuori
        lb = ((d.get('data') or {}).get('so5') or {}).get('so5Leaderboard')
        if not lb:
            return fuori
        conn = lb.get('so5LeaderboardContenders') or {}
        for n in conn.get('nodes') or []:
            lineup = n.get('so5Lineup') or {}
            carte = []
            for a in lineup.get('so5Appearances') or []:
                carta = a.get('anyCard') or {}
                carte.append({
                    'slug': ((a.get('player') or {}).get('slug')),
                    'nome': ((a.get('player') or {}).get('displayName')),
                    'squadra': ((((a.get('player') or {}).get('activeClub')) or {}).get('slug')),
                    'ruolo': a.get('position'),
                    'capitano': bool(a.get('captain')),
                    'punteggio': a.get('score'),
                    'rarita': carta.get('rarityTyped'),
                    'carta': carta.get('slug'),
                    'xp': carta.get('xp'),
                    'bonus_carta': _bonus_carta(carta),
                })
            if carte:
                fuori.append({'contender': n.get('slug'),
                               'manager': (lineup.get('user') or {}).get('slug'),
                               'carte': carte})
        info = conn.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            break
        after = info.get('endCursor')
    return fuori


def carica():
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            return json.load(f)
    return {'leaderboard': {}}


def salva(dati):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dati, f, ensure_ascii=False, separators=(',', ':'))


def riepilogo(dati):
    formazioni = 0
    carte_tot = 0
    per_tipo = collections.Counter()
    manager_visti = set()
    for slug, righe in (dati.get('leaderboard') or {}).items():
        for r in righe:
            formazioni += 1
            carte_tot += len(r.get('carte') or [])
            manager_visti.add(r.get('manager'))
    print(f"\n=== CAMPO: {formazioni} formazioni, {carte_tot} osservazioni, "
          f"{len(manager_visti)} manager distinti, {len(dati.get('leaderboard') or {})} arene")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=None, help="fermati dopo N arene (per provare)")
    args = ap.parse_args()

    if not os.path.exists(ARCHIVIO):
        log(f"ATTENZIONE: {ARCHIVIO} non trovato.")
        return 1
    with open(ARCHIVIO, encoding='utf-8') as f:
        arene = (json.load(f) or {}).get('arene') or []
    slugs = sorted({a['slug'] for a in arene if a.get('slug')})
    if args.max:
        slugs = slugs[:args.max]

    dati = carica()
    fatte = dati.setdefault('leaderboard', {})
    da_fare = [s for s in slugs if s not in fatte]
    log(f"{len(slugs)} arene | {len(fatte)} gia' fatte | {len(da_fare)} da fare")

    for i, slug in enumerate(da_fare, 1):
        righe = campo(slug)
        fatte[slug] = righe
        if i % 25 == 0 or i == len(da_fare):
            log(f"[{i}/{len(da_fare)}] {slug}: {len(righe)} formazioni")
            salva(dati)

    salva(dati)
    log(f"Scritto {OUT}")
    riepilogo(dati)
    return 0


if __name__ == '__main__':
    sys.exit(main())
