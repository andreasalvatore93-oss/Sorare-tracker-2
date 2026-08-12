"""Raccoglie UNA VOLTA per run le odds e i grade della giornata -> pool_gw.json.

PERCHE' ESISTE (07/08/2026, misurato sulla run 31190547919, 26 minuti totali).
Ognuno dei 20 shard della discovery rifaceva per conto suo lo stesso lavoro:

  fetch grade  3 leaderboard x 4 ruoli x fino a 20 pagine = ~240 richieste per
               shard, ~4.800 a run -> 38% del tempo di discovery (fino all'88%)
  odds         una chiamata per OGNI giocatore di squadra in campo, in sequenza
               -> 308-609s per shard, quasi tutto attesa da 429 (Retry-After a
               152 secondi)

Le due cose insieme facevano 156 risposte 429 e paginazioni troncate a meta'
(10 shard su 20 avevano grade parziali: 200 o 381 invece di 877, numeri
plausibili e sbagliati).

Qui si fa tutto una volta e si passa agli shard come artifact della stessa
run. Le odds si prendono dalle PARTITE (~183 query coprono tutti i giocatori)
invece che giocatore per giocatore: e' la regola gia' scritta in CLAUDE.md, e
la funzione bulk esisteva dal 03/08 -- era gia' usata dallo scouting, ma la
discovery non l'aveva mai collegata.

Non e' una cache: il file nasce e muore dentro la run, non e' committato, e
chi lo legge lo scarta se la giornata dentro non e' la sua.

NON fallisce se manca qualcosa: scrive comunque il file e lascia che siano gli
avvisi della discovery a segnalare il buco, cosi' un problema di grade non
blocca tutta la pipeline. Il motivo vero si legge nella riga PROBE auth:
currentUser=None significa sessione non autenticata, NON giornata chiusa.
"""
import json
import sys

import discovery_fixture as df

OUT = 'pool_gw.json'


def main():
    fx = df.risolvi_fixture()
    if not fx or not fx.get('slug'):
        print("ERRORE: giornata non risolta, non scrivo nulla.")
        return 1
    fixture_slug = fx['slug']
    print(f"[pool] giornata: {fixture_slug} "
          f"(gameweek {fx.get('seasonGameWeek')}, stato {fx.get('aasmState')})")

    odds = df.odds_per_giornata(fixture_slug) or {}
    grade_map, copertura = df.fetch_grade_live(fixture_slug)

    # CARTE GIA' IMPEGNATE IN FORMAZIONI BLOCCATE (solo con ESCLUDI_LOCKATE=1).
    # Raccolte qui una volta sola e passate agli shard con l'artifact. Se la
    # lettura fallisce il job FALLISCE: e' una richiesta esplicita di tutela,
    # e una tutela che si spegne da sola in silenzio non tutela niente.
    carte_bloccate = None
    if df.ESCLUDI_LOCKATE:
        carte, det = df.carte_bloccate_live(fixture_slug)
        carte_bloccate = sorted(carte)
        print(f"[pool] formazioni BLOCCATE: {det['bloccate']} + "
              f"modificabili IN SEASON: {det['in_season_modificabili']} -> "
              f"{len(carte_bloccate)} carte escluse dal pool. "
              f"Modificabili non in-season: {det['modificabili_libere']} "
              f"(le loro carte restano disponibili).")

    dati = {'fixture': fixture_slug, 'odds': odds, 'odds_fetched': True,
            'copertura': copertura, 'grade_map': grade_map}
    if carte_bloccate is not None:
        dati['carte_bloccate'] = carte_bloccate
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dati, f, ensure_ascii=False, sort_keys=True)

    dist = {}
    for g in grade_map.values():
        dist[g] = dist.get(g, 0) + 1
    print(f"[pool] scritto {OUT}: {len(odds)} giocatori con odds, "
          f"{len(grade_map)} con grade")
    print(f"[pool] distribuzione grade: {dict(sorted(dist.items()))}")
    if not odds:
        print("[pool] ATTENZIONE: ZERO odds. Gli shard ripiegheranno sulle "
              "chiamate per giocatore, molto piu' lente.")
    if not grade_map:
        print("[pool] ATTENZIONE: ZERO grade. La pipeline prosegue in fallback "
              "(z_grade=0, identico a non avere G). Guardare la riga "
              "'PROBE auth' qui sopra: se currentUser=None la sessione non "
              "autentica e vanno rinnovati i secret; NON e' la giornata chiusa.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
