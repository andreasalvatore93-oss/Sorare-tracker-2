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
# 12/08: header separato, alza il tetto di rate/complessita' sull'ACCOUNT
# indipendentemente dal cookie (verificato: APIKEY da sola risponde 200 anche
# senza login). Si aggiunge sempre, non sostituisce il cookie.
APIKEY = os.environ.get('SORARE_APIKEY', '')
PAUSA = float(os.environ.get('MANAGER_PAUSA', '0.4'))

# Whitelist: SOLO le arene della famiglia LIMITED (limited, beginner,
# uncapped -- tutte carte limited). Escluse arena_rare e 'arena_altro' (super
# rare/unique): mint diverso, pochissimi le hanno, non affidabili (regola
# esplicita utente 04/08). Le beginner restano: rendono male (-16.5% ROI su 182
# ingressi utente) ma sono punteggi reali di carte limited.
TIPI_ARENA_ESCLUSI = ('arena_rare', 'arena_altro')

# D1 (CLAUDE.md, 06/08/2026): quante volte riprovare un contender la cui
# formazione() fallisce prima di arrenderci e marcarlo fallito-definitivo,
# per non riciclarlo all'infinito (es. contender cancellato da Sorare).
MAX_TENTATIVI_CONTENDER = 3

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
        so5Rankings { ranking score so5Leaderboard { slug } }
        so5Appearances {
          score
          position
          captain
          # activeClub serve al bonus "Multi-club" +2%, che scatta con meno di
          # 3 carte della stessa squadra nella formazione: senza la squadra non
          # si puo' sapere se quel bonus e' scattato, e sbagliarlo falsa il
          # punteggio grezzo di tutte e 5 le carte.
          player { slug displayName activeClub { slug name } }
          anyCard {
            slug
            rarityTyped
            # Vive sull'interfaccia, non sul tipo Card (vedi discovery_fixture.py,
            # che infatti la chiede fuori dal fragment). Serve al vincolo "4 carte
            # in season su 5" delle In Season: dedurlo dall'anno nello slug della
            # carta sarebbe una supposizione, questo e' il dato di Sorare.
            inSeasonEligible
            # xp/powerBreakdown vivono sul tipo CONCRETO Card, non
            # sull'interfaccia AnyCardInterface: senza il fragment esplicito
            # la query fallisce per intero (stesso inciampo gia' documentato
            # in discovery_fixture.py).
            ... on Card {
              xp
              # Serve al pool delle Under 23. Il file player_card_counts.json
              # ce l'ha, ma contiene solo il pool della run PIU' RECENTE: per
              # una giornata passata la maggior parte dei giocatori non c'e'.
              # Qui il flag arriva con la carta, per qualunque giornata.
              u23Eligible
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
    if APIKEY:
        intestazioni['APIKEY'] = APIKEY
    for tentativo in range(8):
        time.sleep(PAUSA)
        try:
            r = _S.post(GRAPHQL_URL, json={'query': query, 'variables': variables},
                        headers=intestazioni, timeout=60)
        except Exception as e:
            log(f"  rete: {e!r}, ritento")
            time.sleep(3 * (tentativo + 1))
            continue
        if r.status_code == 429:
            # Da casa il budget ANONIMO e' gia' esaurito da altri (misurato il
            # 02/08: stessa query, senza cookie 429 con retry-after 67, con
            # cookie 200). Le formazioni sono pubbliche e le chiedevamo apposta
            # senza cookie per non consumare il budget dell'account: se pero'
            # l'anonimo e' chiuso, meglio pagare col cookie che non scaricare.
            if 'Cookie' not in intestazioni and COOKIE:
                log("  429 da anonimo: passo al cookie per questa richiesta")
                intestazioni['Cookie'] = COOKIE
                continue
            # Sorare dice lui quanto aspettare: indovinarlo a potenze di 2
            # significa o ripartire troppo presto o dormire per niente.
            attesa = min(int(r.headers.get('retry-after') or 0) or 2 ** tentativo * 3, 90)
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
    """Tutte le partecipazioni del manager in quella giornata. Paginata.

    Torna (righe, ok). `ok` False vuol dire che l'indice non e' arrivato
    intero -- 429 esauriti, o una pagina persa a meta' paginazione. Chi
    chiama NON deve salvare quella giornata: salvarla la marcherebbe "fatta"
    per sempre con dentro meta' dato o zero, e il buco non si vedrebbe piu'."""
    fuori, after = [], None
    for _pagina in range(20):
        d = graphql(INDICE_QUERY, {'fixture': fixture, 'manager': manager, 'after': after})
        if d.get('errors'):
            log(f"  ERRORE indice {fixture}: {str(d['errors'])[:160]}")
            return fuori, False
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
    return fuori, True


def formazione(contender_slug):
    """(carte, manager, piazzamento) di un contender. Tutto pubblico.

    Il piazzamento sta in `so5Lineup.so5Rankings`, non sul contender (li'
    `rank` e `score` non esistono): una riga per leaderboard, con ranking e
    punteggio totale gia' comprensivo del capitano."""
    d = graphql(FORMAZIONE_QUERY, {'slug': contender_slug}, con_cookie=False)
    if d.get('errors'):
        return None, None, None
    cont = ((d.get('data') or {}).get('so5') or {}).get('so5LeaderboardContender') or {}
    lineup = cont.get('so5Lineup') or {}
    piazzamento = None
    for r in lineup.get('so5Rankings') or []:
        if ((r.get('so5Leaderboard') or {}).get('slug') or '') in contender_slug:
            piazzamento = {'rank': r.get('ranking'), 'punteggio': r.get('score')}
            break
    carte = []
    for a in lineup.get('so5Appearances') or []:
        carta = a.get('anyCard') or {}
        # Somma dei basis points del powerBreakdown come frazione (1000 bp =
        # 10%), la stessa misura di CardPool.power_bonus_fraction. Serve per
        # tornare al punteggio GREZZO del giocatore: Sorare applica questo
        # bonus solo in In Season/All Stars, MAI in arena, e il modello
        # prevede sempre il grezzo. Senza toglierlo il confronto
        # previsione/realta' e' gonfiato proprio dove le carte sono migliori.
        pb = carta.get('powerBreakdown') or {}
        bonus = sum(v or 0 for k, v in pb.items() if k.endswith('BasisPoints')) / 10000.0
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
            'bonus_carta': round(bonus, 4),
            'in_season': carta.get('inSeasonEligible'),
            'u23': carta.get('u23Eligible'),
        })
    return carte, ((lineup.get('user') or {}).get('slug')), piazzamento


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
    if not COOKIE:
        # meglio fermarsi che girare a vuoto: senza cookie l'indice torna vuoto
        # SENZA errore, e ogni giornata verrebbe salvata a zero righe e marcata
        # "fatta" -- l'archivio resterebbe vuoto per sempre senza dirlo.
        log("SORARE_COOKIE assente: l'elenco delle partecipazioni non e' pubblico "
            "e tornerebbe vuoto. Mi fermo. Usa il workflow GitHub 'Ricostruisci "
            "manager', che ha il segreto.")
        return 1

    dest = args.json or os.path.join(REPO_ROOT, 'dati_globali', f'manager_{args.manager}.json')
    dati = carica(dest)
    dati['manager'] = args.manager

    # il taglio va fatto DOPO aver scartato le giornate gia' fatte, non prima:
    # altrimenti --max-giornate prende sempre le stesse prime N della lista
    # grezza e un ciclo esterno che lo richiama non avanza mai (bug trovato
    # scrivendo il workflow GitHub: serviva per committare a piccoli blocchi).
    if args.max_giornate:
        gia_fatte = dati.get('giornate') or {}
        nuove = [g for g in giornate if g not in gia_fatte]
        giornate = [g for g in giornate if g in gia_fatte] + nuove[:args.max_giornate]

    for i, giornata in enumerate(giornate, 1):
        completate = (dati.get('giornate') or {}).get(giornata)
        retry_rows = (dati.get('retry') or {}).get(giornata)

        # D1: una giornata e' "fatta" solo se e' gia' stata salvata E non ha
        # contender pendenti da riprovare. Prima bastava la presenza della
        # chiave in dati['giornate'] anche se conteneva righe senza 'carte':
        # cosi' non venivano mai piu' ritentate (133 righe crowss, 26
        # forever-young trovate mute il 06/08).
        if completate is not None and not retry_rows:
            log(f"[{i}/{len(giornate)}] {giornata}: gia' fatta, salto.")
            continue

        if retry_rows:
            # giornata gia' iniziata: riprovo SOLO i contender falliti,
            # niente nuova query indice (le righe pendenti portano gia'
            # tutto il necessario, comprese quelle di --solo-arene).
            da_scaricare = retry_rows
            log(f"[{i}/{len(giornate)}] {giornata}: riprovo {len(da_scaricare)} "
                "contender falliti in precedenza")
        else:
            righe, ok = partecipazioni(args.manager, giornata)
            if not ok:
                log(f"[{i}/{len(giornate)}] {giornata}: indice incompleto, NON salvo "
                    "(si riprova al prossimo giro).")
                continue
            arene = [r for r in righe if r.get('tipo_arena')
                     and r['tipo_arena'] not in TIPI_ARENA_ESCLUSI]
            log(f"[{i}/{len(giornate)}] {giornata}: {len(righe)} partecipazioni, "
                f"{len(arene)} arene utili")
            da_scaricare = arene if args.solo_arene else righe
            da_scaricare = [r for r in da_scaricare
                            if r.get('tipo_arena') not in TIPI_ARENA_ESCLUSI]

        nuovi_completati, nuovi_pendenti, falliti_def = [], [], []
        for r in da_scaricare:
            carte, chi, piazzamento = formazione(r['contender'])
            if carte is None:
                tentativi = r.get('_tentativi', 0) + 1
                if tentativi >= MAX_TENTATIVI_CONTENDER:
                    log(f"  FALLITO DEFINITIVO dopo {tentativi} tentativi: "
                        f"{r['contender'][:60]} (non ritentato piu')")
                    falliti_def.append(r['contender'])
                else:
                    r['_tentativi'] = tentativi
                    nuovi_pendenti.append(r)
                continue
            if chi and chi != args.manager:
                # Non dovrebbe succedere: se succede, meglio saperlo che
                # mescolare le formazioni di un altro nel campione. Non e'
                # un guasto di rete: ritentare non cambierebbe il dato,
                # quindi va dritto fra i falliti definitivi.
                log(f"  ATTENZIONE: {r['contender'][:50]} appartiene a {chi}, "
                    "saltata (fallito definitivo, non ritentata).")
                falliti_def.append(r['contender'])
                continue
            r.pop('_tentativi', None)
            r['carte'] = carte
            r['piazzamento'] = piazzamento
            nuovi_completati.append(r)

        dati.setdefault('giornate', {})[giornata] = (completate or []) + nuovi_completati
        if nuovi_pendenti:
            dati.setdefault('retry', {})[giornata] = nuovi_pendenti
        elif giornata in (dati.get('retry') or {}):
            del dati['retry'][giornata]
        if falliti_def:
            lista = dati.setdefault('falliti_definitivi', {}).setdefault(giornata, [])
            for cs in falliti_def:
                if cs not in lista:
                    lista.append(cs)

        n_falliti = len(nuovi_pendenti) + len(falliti_def)
        if n_falliti:
            log(f"  {n_falliti} righe non ricostruite su {len(da_scaricare)} in "
                f"{giornata} ({len(nuovi_pendenti)} da riprovare, "
                f"{len(falliti_def)} falliti definitivi)")
        salva(dati, dest)

    log(f"Scritto {dest}")
    riepilogo(dati, solo_arene=args.solo_arene)
    return 0


if __name__ == '__main__':
    sys.exit(main())
