"""ricostruisci_manager -- le partecipazioni e le formazioni di UN manager.

Perche' esiste
--------------
Finora il termine di paragone del modello e' sempre stato l'utente: le sue 673
arene, il suo ROI. Ma un solo manager e' un campione solo, e per giunta uno che
stava imparando. Qui si legge lo stesso dato per CHIUNQUE -- come schiera, chi
fa capitano, quanto satura il cap, in quali competizioni entra -- e si ottiene
un campione grande di formazioni VERE, che e' cosa diversa dalle 40.000
sintetiche di `taratura_formazioni_sintetiche.py`: quelle sono combinazioni
casuali, queste sono combinazioni SCELTE, e le due non hanno la stessa
dispersione.

Le due query (entrambe verificate il 02/08)
-------------------------------------------
1. l'elenco delle partecipazioni di una giornata -- richiede il cookie, e
   `userSlug` e' obbligatorio. E' PAGINATA: nella giornata di prova 86
   partecipazioni arrivavano in due pagine (50 + 36), e fermarsi alla prima ne
   avrebbe persi 36 senza dire niente.

   ATTENZIONE alla via sbagliata, che sembra funzionare: la stessa cosa si puo'
   chiedere a `so5LeaderboardGroups(groupType: COMPETITION_WITH_ARENA)
   .so5LeaderboardContenders(userSlug:)`, che risponde 52 contender pieni di
   In Season, Challenger e All Star -- e ZERO arene. Ci si costruirebbe sopra
   un'analisi intera senza accorgersene.

2. la formazione di un contender -- PUBBLICA, nessun cookie: ruolo, capitano,
   rarita' e punteggio realizzato di ogni carta.

Le carte non danno bonus in arena (il capitano vale +20% per tutti), quindi il
punteggio della carta E' il punteggio del giocatore: ogni riga e'
un'osservazione pulita.

Uso
---
    python ricostruisci_manager.py forever-young --giornate football-10-14-apr-2026
    python ricostruisci_manager.py forever-young --dalle-mie-arene
    python ricostruisci_manager.py forever-young --dalle-mie-arene --solo-arene

Accumula su `dati_globali/manager_<slug>.json` e riprende da dove si era
fermato: rilanciarlo non ripaga il lavoro gia' fatto.
"""
import os
import re
import sys
import json
import time
import argparse
import datetime
import collections

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

if hasattr(sys.stdout, 'buffer'):   # console Windows in cp1252: i nomi non
    import io as _io                # latini farebbero morire lo script in stampa
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    from curl_cffi import requests as _rq
    _S = _rq.Session(impersonate='chrome')
except ImportError:                 # pragma: no cover
    import requests as _rq
    _S = _rq.Session()

GRAPHQL_URL = 'https://api.sorare.com/federation/graphql'
COOKIE = os.environ.get('SORARE_COOKIE', '')
PAUSA = float(os.environ.get('MANAGER_PAUSA', '0.4'))

# Le arene rare non interessano (regola esplicita dell'utente): non le gioca.
# Restano limited, beginner e uncapped -- le beginner SI', anche se rendono
# male (-16.5% di ROI su 182 suoi ingressi): sono comunque punteggi reali, e
# servono a capire se sono strutturalmente perdenti o se erano le carte
# sbagliate.
TIPI_ARENA_ESCLUSI = ('arena_rare',)

INDICE_QUERY = """
query Partecipazioni($fixture: String!, $manager: String!, $after: String) {
  so5 {
    so5Fixture(slug: $fixture) {
      slug
      userFixtureResults(userSlug: $manager) {
        slug
        so5LeaderboardContenders(first: 50, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            slug
            so5Leaderboard { slug displayName }
          }
        }
      }
    }
  }
}
"""

FORMAZIONE_QUERY = """
query Formazione($slug: String!) {
  so5 {
    so5LeaderboardContender(slug: $slug) {
      slug
      so5Lineup {
        user { slug }
        so5Appearances {
          score
          position
          captain
          player { slug displayName }
          anyCard { slug rarityTyped }
        }
      }
    }
  }
}
"""


def log(msg):
    print(f"[{datetime.datetime.utcnow().isoformat()}Z] [manager] {msg}", flush=True)


def graphql(query, variables, con_cookie=True):
    """Una query, con retry sui 429. Il cookie serve solo all'indice: le
    formazioni sono pubbliche e chiederle senza cookie non consuma il budget
    dell'account autenticato."""
    intestazioni = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    if con_cookie and COOKIE:
        intestazioni['Cookie'] = COOKIE
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
            return {'errors': [{'message': f'HTTP {r.status_code}'}]}
    return {'errors': [{'message': '429 dopo 5 tentativi'}]}


def tipo_arena(slug_leaderboard):
    """Il tipo di arena, o None se quella leaderboard non e' un'arena."""
    if 'arena' not in (slug_leaderboard or ''):
        return None
    for tipo in ('arena_limited_beginner', 'arena_limited_uncapped',
                 'arena_limited', 'arena_rare'):
        if tipo in slug_leaderboard:
            return tipo
    return 'arena_altro'


def partecipazioni(manager, fixture):
    """Tutte le partecipazioni del manager in quella giornata. Paginata."""
    fuori, after = [], None
    for _pagina in range(20):
        d = graphql(INDICE_QUERY, {'fixture': fixture, 'manager': manager, 'after': after})
        if d.get('errors'):
            log(f"  ERRORE indice {fixture}: {str(d['errors'])[:160]}")
            return fuori
        fx = ((d.get('data') or {}).get('so5') or {}).get('so5Fixture') or {}
        conn = ((fx.get('userFixtureResults') or {}).get('so5LeaderboardContenders')) or {}
        for n in conn.get('nodes') or []:
            lb = (n.get('so5Leaderboard') or {}).get('slug') or ''
            fuori.append({
                'contender': n.get('slug'),
                'leaderboard': lb,
                'competizione': (n.get('so5Leaderboard') or {}).get('displayName'),
                'tipo_arena': tipo_arena(lb),
            })
        info = conn.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            break
        after = info.get('endCursor')
    return fuori


def formazione(contender_slug):
    """Le carte schierate: (lista_carte, manager). Pubblica."""
    d = graphql(FORMAZIONE_QUERY, {'slug': contender_slug}, con_cookie=False)
    if d.get('errors'):
        return None, None
    cont = ((d.get('data') or {}).get('so5') or {}).get('so5LeaderboardContender') or {}
    lineup = cont.get('so5Lineup') or {}
    carte = []
    for a in lineup.get('so5Appearances') or []:
        carte.append({
            'slug': ((a.get('player') or {}).get('slug')),
            'nome': ((a.get('player') or {}).get('displayName')),
            'ruolo': a.get('position'),
            'capitano': bool(a.get('captain')),
            'punteggio': a.get('score'),
            'rarita': ((a.get('anyCard') or {}).get('rarityTyped')),
            'carta': ((a.get('anyCard') or {}).get('slug')),
        })
    return carte, ((lineup.get('user') or {}).get('slug'))


def giornate_dalle_mie_arene():
    """Le giornate del periodo coperto dall'archivio dell'utente: cosi' il
    confronto e' sullo stesso intervallo, senza doverlo indovinare."""
    path = os.path.join(REPO_ROOT, 'dati_globali', 'arene_storico.json')
    if not os.path.exists(path):
        log(f"ATTENZIONE: {path} non trovato, serve --giornate.")
        return []
    with open(path, encoding='utf-8') as f:
        arene = (json.load(f) or {}).get('arene') or []
    giornate = sorted({a.get('fixture') for a in arene if a.get('fixture')})
    log(f"Giornate dall'archivio arene: {len(giornate)} "
        f"(da {giornate[0]} a {giornate[-1]})" if giornate else "Nessuna giornata.")
    return giornate


def carica(dest):
    if os.path.exists(dest):
        with open(dest, encoding='utf-8') as f:
            return json.load(f)
    return {'manager': None, 'giornate': {}}


def salva(dati, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        json.dump(dati, f, ensure_ascii=False, separators=(',', ':'))


def riepilogo(dati, solo_arene=False):
    """Cosa e' stato raccolto, in numeri leggibili."""
    formazioni = tipi = 0
    carte_totali = 0
    per_tipo = collections.Counter()
    capitani = collections.Counter()
    giocatori = collections.Counter()
    punteggi = []
    for _g, righe in (dati.get('giornate') or {}).items():
        for r in righe:
            if solo_arene and not r.get('tipo_arena'):
                continue
            carte = r.get('carte') or []
            if not carte:
                continue
            formazioni += 1
            carte_totali += len(carte)
            per_tipo[r.get('tipo_arena') or r.get('competizione') or '?'] += 1
            totale = sum(c.get('punteggio') or 0 for c in carte)
            punteggi.append(totale)
            for c in carte:
                giocatori[c['nome'] or c['slug']] += 1
                if c.get('capitano'):
                    capitani[c['ruolo']] += 1
    tipi = len(per_tipo)
    print(f"\n=== RACCOLTO: {formazioni} formazioni, {carte_totali} osservazioni, "
          f"{tipi} competizioni diverse")
    if punteggi:
        punteggi.sort()
        media = sum(punteggi) / len(punteggi)
        scarto = (sum((x - media) ** 2 for x in punteggi) / max(1, len(punteggi) - 1)) ** 0.5
        print(f"    punteggio formazione: media {media:.1f}, dispersione {scarto:.1f}, "
              f"mediana {punteggi[len(punteggi)//2]:.1f}")
    print(f"\n  competizioni piu' giocate:")
    for k, v in per_tipo.most_common(8):
        print(f"    {v:4d} x {k}")
    if capitani:
        tot = sum(capitani.values())
        print(f"\n  capitano per ruolo:")
        for k, v in capitani.most_common():
            print(f"    {k:<12} {v:4d}  ({v / tot:.0%})")
    print(f"\n  giocatori piu' schierati:")
    for k, v in giocatori.most_common(8):
        print(f"    {v:3d} x {k}")


def main():
    ap = argparse.ArgumentParser(description="Partecipazioni e formazioni di un manager.")
    ap.add_argument('manager', help="slug del manager (es. forever-young)")
    ap.add_argument('--giornate', default=None,
                    help="slug di giornate separati da virgola")
    ap.add_argument('--dalle-mie-arene', action='store_true',
                    help="usa le giornate dell'archivio arene dell'utente")
    ap.add_argument('--solo-arene', action='store_true',
                    help="scarica le formazioni SOLO delle arene (salta In Season e resto)")
    ap.add_argument('--max-giornate', type=int, default=None,
                    help="fermati dopo N giornate (per provare)")
    ap.add_argument('--json', default=None, help="file di uscita")
    args = ap.parse_args()

    if args.giornate:
        giornate = [x.strip() for x in args.giornate.split(',') if x.strip()]
    elif args.dalle_mie_arene:
        giornate = giornate_dalle_mie_arene()
    else:
        log("Serve --giornate o --dalle-mie-arene.")
        return 1
    if args.max_giornate:
        giornate = giornate[:args.max_giornate]
    if not COOKIE:
        log("ATTENZIONE: SORARE_COOKIE assente -- l'elenco delle partecipazioni "
            "non e' pubblico e tornera' vuoto.")

    dest = args.json or os.path.join(REPO_ROOT, 'dati_globali', f'manager_{args.manager}.json')
    dati = carica(dest)
    dati['manager'] = args.manager

    for i, giornata in enumerate(giornate, 1):
        if giornata in (dati.get('giornate') or {}):
            log(f"[{i}/{len(giornate)}] {giornata}: gia' fatta, salto.")
            continue
        righe = partecipazioni(args.manager, giornata)
        arene = [r for r in righe if r.get('tipo_arena')
                 and r['tipo_arena'] not in TIPI_ARENA_ESCLUSI]
        log(f"[{i}/{len(giornate)}] {giornata}: {len(righe)} partecipazioni, "
            f"{len(arene)} arene utili")

        da_scaricare = arene if args.solo_arene else righe
        for r in da_scaricare:
            if r.get('tipo_arena') in TIPI_ARENA_ESCLUSI:
                continue
            carte, chi = formazione(r['contender'])
            if carte is None:
                continue
            if chi and chi != args.manager:
                # Non dovrebbe succedere: se succede, meglio saperlo che
                # mescolare le formazioni di un altro nel campione.
                log(f"  ATTENZIONE: {r['contender'][:50]} appartiene a {chi}, saltata.")
                continue
            r['carte'] = carte
        dati.setdefault('giornate', {})[giornata] = da_scaricare
        salva(dati, dest)

    log(f"Scritto {dest}")
    riepilogo(dati, solo_arene=args.solo_arene)
    return 0


if __name__ == '__main__':
    sys.exit(main())
