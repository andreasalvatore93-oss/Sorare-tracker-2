"""Raccoglie UNA VOLTA per run i grade (A..F) della giornata -> grade_gw.json.

PERCHE' ESISTE (07/08/2026, misurato sulla run 31190547919).
Prima ognuno dei 20 shard della discovery rifaceva per conto suo la fetch
completa: 3 leaderboard x 4 ruoli x fino a 20 pagine = fino a ~240 richieste
per shard, cioe' ~4.800 richieste identiche a run. Risultato misurato: 4-8
risposte 429 per job, e uno shard che si e' fermato a 200 slug con grade
invece di 877 perche' la paginazione si e' interrotta sui 429.

Con questo job la fetch si fa una volta sola (~240 richieste a run, x20 in
meno) e il risultato viaggia agli shard come artifact della STESSA run.
Non e' una cache: il file nasce e muore dentro la run, non e' committato, e
la discovery lo accetta solo se la giornata dentro corrisponde alla sua.

NON fallisce se i grade sono zero: scrive comunque il file e lascia che siano
gli avvisi gia' presenti nella discovery a segnalare il buco (evita che un
problema di grade blocchi tutta la pipeline). Il motivo vero si legge nella
riga PROBE auth qui sotto: currentUser=None significa sessione non
autenticata, NON giornata chiusa.
"""
import json
import sys

import discovery_fixture as df

OUT = 'grade_gw.json'


def main():
    fx = df.risolvi_fixture()
    if not fx or not fx.get('slug'):
        print("ERRORE: giornata non risolta, non scrivo nulla.")
        return 1
    fixture_slug = fx['slug']
    print(f"[grade-gw] giornata: {fixture_slug} "
          f"(gameweek {fx.get('seasonGameWeek')}, stato {fx.get('aasmState')})")

    grade_map, copertura = df.fetch_grade_live(fixture_slug)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'fixture': fixture_slug, 'copertura': copertura,
                   'grade_map': grade_map}, f, ensure_ascii=False, sort_keys=True)

    dist = {}
    for g in grade_map.values():
        dist[g] = dist.get(g, 0) + 1
    print(f"[grade-gw] scritto {OUT}: {len(grade_map)} slug con grade")
    print(f"[grade-gw] distribuzione: {dict(sorted(dist.items()))}")
    if not grade_map:
        print("[grade-gw] ATTENZIONE: ZERO grade. La pipeline prosegue in "
              "fallback (z_grade=0, identico a non avere G). Guardare la riga "
              "'PROBE auth' qui sopra: se currentUser=None la sessione non "
              "autentica e vanno rinnovati i secret; NON e' la giornata chiusa.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
