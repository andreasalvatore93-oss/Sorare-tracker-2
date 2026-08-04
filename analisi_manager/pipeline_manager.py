# -*- coding: utf-8 -*-
"""pipeline_manager — TUTTO il filone smart-money in una run (pensato per GitHub).

Per una lista di manager e di GW chiuse:
  1) estrae le formazioni-arena  (ricostruisci_manager --solo-arene)
  2) costruisce il batch dei pick da cachare/rinfrescare (gamelog mancante o
     stantio rispetto all'ultima GW target), risolvendo lega/ruolo
  3) riempie/appende la cache game-log        (predici_manager_batch --force)
  4) analizza ogni GW separatamente           (analizza_gw.py --gw ... --fine ...)
  5) aggrega tutte le GW                       (aggrega.py)

Idempotente e cache-incrementale: le run successive sono corte (i giocatori
restano cachati, si appende solo la GW nuova). Il push lo fa il workflow.

Uso (locale o CI):
  python analisi_manager/pipeline_manager.py \
     --manager satonio,qtn-... \
     --gw football-31-jul-4-aug-2026:2026-08-04,football-28-31-jul-2026:2026-07-31
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'formazione_turchia', 'discovery'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import turchia_gk_discovery as base
import discovery_fixture as df
import backtest_arene_cache

# I 12 slug + i due aggiunti; default se --manager non passato.
# NB: satonio NON e' nei default: usato una volta sola per gonfiare la cache
# (whale, escluso dal campione d'analisi). Se serve ri-cacharlo, passarlo a mano.
DEFAULT_MANAGER = ['eoghankelly', 'badamt', 'milkyfresht', 'lairdinho', 'bxl-spartak',
                   'spillo678', 'braddersfc', 'bryanmid', 'shirimimi', 'matangel716',
                   'fins49', 'ninoshooter',
                   'qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d']
# Le 4 GW gia' allineate; default.
DEFAULT_GW = [('football-31-jul-4-aug-2026', '2026-08-04'),
              ('football-28-31-jul-2026', '2026-07-31'),
              ('football-24-28-jul-2026', '2026-07-28'),
              ('football-21-24-jul-2026', '2026-07-24')]

RUOLO_MAP = {'Goalkeeper', 'Defender', 'Midfielder', 'Forward'}
# Solo arene LIMITED (coerente con analizza_gw.ARENE_AMMESSE): non cachiamo
# giocatori che compaiono solo in rare/altro (escluse).
ARENE_AMMESSE = {'arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped'}


def log(m):
    print(m, flush=True)


def run(cmd):
    subprocess.run(cmd, cwd=ROOT, check=False)


def _dt(iso):
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def estrai(managers, gws):
    for gw, _ in gws:
        for man in managers:
            run([sys.executable, os.path.join(ROOT, 'ricostruisci_manager.py'),
                 man, '--giornate', gw, '--solo-arene'])
        log(f"[estrazione] {gw} fatto")


def costruisci_batch(managers, gws):
    """Restituisce {slug:{ruolo,dir}} dei pick che vanno predetti/rinfrescati:
    gamelog mancante, oppure ultimo game < ultima GW target (stantio)."""
    # Un pick e' "fresco" se il suo gamelog contiene un game nell'ultima GW
    # target. Le finestre GW durano fino a ~6 giorni, quindi la soglia e'
    # fine_ultima_GW - 6 giorni (non -1: chi ha giocato a inizio finestra ha
    # comunque la partita target, non va rifetchato).
    fine_max = max(_dt(f + 'T23:59:00') for _, f in gws)
    soglia = fine_max - datetime.timedelta(days=6)
    cache = backtest_arene_cache.CacheLocale()

    # ruolo + club per slug dai manager
    info = {}
    for man in managers:
        p = os.path.join(ROOT, 'dati_globali', f'manager_{man}.json')
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding='utf-8'))
        for gw, _ in gws:
            for f in (d.get('giornate') or {}).get(gw) or []:
                if f.get('tipo_arena') not in ARENE_AMMESSE:
                    continue
                for c in f.get('carte') or []:
                    sl = c.get('slug')
                    if sl and sl not in info and c.get('ruolo') in RUOLO_MAP:
                        info[sl] = {'ruolo': c['ruolo'], 'club': c.get('squadra')}

    # dir noto dai path di cache esistenti (offline) + club->dir
    import re
    pat = re.compile(r'formazione_([^\\/]+)[\\/]output')
    dir_slug, club_dir = {}, {}
    for r, _, fs in os.walk(ROOT):
        for f in fs:
            if f.endswith('_gamelog.json'):
                sl = f[:-len('_gamelog.json')]
                m = pat.search(r)
                if m:
                    dir_slug.setdefault(sl, m.group(1))
    for sl, i in info.items():
        if sl in dir_slug and i.get('club'):
            club_dir.setdefault(i['club'], dir_slug[sl])

    batch = {}
    Q = 'query C($s:String!){ anyPlayer(slug:$s){ activeClub{ domesticLeague{ slug } } } }'
    for sl, i in info.items():
        gl = cache.gamelog(sl)
        ultimo = max((_dt((n.get('anyGame') or {}).get('date')) for n in gl
                      if _dt((n.get('anyGame') or {}).get('date'))), default=None) if gl else None
        if ultimo is not None and ultimo >= soglia:
            continue  # gia' fresco
        dirn = dir_slug.get(sl) or club_dir.get(i.get('club'))
        if not dirn:
            try:
                d = base.graphql_query(Q, {'s': sl}, operation_name='C')
                lg = (((((d or {}).get('data') or {}).get('anyPlayer') or {})
                       .get('activeClub') or {}).get('domesticLeague') or {}).get('slug')
                dirn = df.LEAGUE_DIR.get(lg) if lg else None
                if i.get('club') and dirn:
                    club_dir[i['club']] = dirn
            except Exception:
                dirn = None
        if dirn:
            batch[sl] = {'ruolo': i['ruolo'], 'dir': dirn}
    return batch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default=None, help='slug separati da virgola')
    ap.add_argument('--gw', default=None, help='gw:fine separati da virgola')
    ap.add_argument('--commit-every', type=int, default=25)
    ap.add_argument('--skip-estrazione', action='store_true')
    args = ap.parse_args()

    managers = args.manager.split(',') if args.manager else DEFAULT_MANAGER
    gws = ([tuple(x.split(':')) for x in args.gw.split(',')] if args.gw else DEFAULT_GW)

    log(f"Manager: {len(managers)} | GW: {[g for g, _ in gws]}")

    if not args.skip_estrazione:
        estrai(managers, gws)

    log("[batch] risolvo i pick da cachare/rinfrescare...")
    batch = costruisci_batch(managers, gws)
    bpath = os.path.join(ROOT, 'dati_globali', 'smart_money', 'pipeline_batch.json')
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    json.dump(batch, open(bpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f"[batch] {len(batch)} pick da predire/rinfrescare -> {bpath}")

    if batch:
        run([sys.executable, os.path.join(ROOT, 'predici_manager_batch.py'),
             '--input', 'dati_globali/smart_money/pipeline_batch.json',
             '--force', '--commit-every', str(args.commit_every)])

    for gw, fine in gws:
        run([sys.executable, os.path.join(ROOT, 'analisi_manager', 'analizza_gw.py'),
             '--gw', gw, '--fine', fine])
    run([sys.executable, os.path.join(ROOT, 'analisi_manager', 'aggrega.py')])
    log("[pipeline] completata.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
