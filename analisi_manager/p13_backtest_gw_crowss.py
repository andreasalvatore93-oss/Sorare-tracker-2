"""Backtest di UNA singola GW di crowss: il manager reale contro il modello.

Tre contendenti sulle STESSE arene e con lo STESSO pool:
  REALE  = quello che ha schierato crowss
  A      = modello di produzione (score_atteso calibrato)
  G      = modello + grade (z-score dentro il gruppo lega/ruolo, nessun peso)

DIFFERENZE RISPETTO A p12_backtest_manager_full.py (sez.24), che era rotto:
 1. POOL DA TUTTE LE COMPETIZIONI, non solo dalle arene. In sez.24 il pool
    veniva costruito solo da `arene_reali`, quindi risultava esattamente
    5 x numero di arene: il modello non aveva NESSUNA carta di scorta e non
    poteva selezionare niente. Qui il pool sono tutte le carte che il manager
    ha schierato quel giorno, ovunque (arene + In-Season + Hot Streak +
    All Star + U23). Sono carte che possedeva con certezza, quindi nessun
    look-ahead.
 2. PUNTEGGI RIPULITI CORRETTAMENTE. Il campo `punteggio` nei file manager e'
    il punteggio del giocatore CON i bonus applicati. Le costanti sono quelle
    di produzione (build_formazione_globale.CAPTAIN_BONUS_BY_TYPE):
      - in ARENA: l'xp NON conta, il capitano vale +20%   -> /1.2 se capitano
      - fuori dall'arena: xp e capitano si SOMMANO, capitano +50%
                                                      -> /(1 + xp + 0.5 se cap)
    In sez.24 si divideva sempre e solo per 1.2, quindi le carte prese dalle
    competizioni non-arena entravano gonfiate fino al 69%.
 3. CONTROLLO OBBLIGATORIO pool vs slot stampato PRIMA di ogni numero: se il
    pool non e' piu' grande degli slot non c'e' selezione da misurare e il
    test e' nullo per costruzione (regola CLAUDE.md del 06/08/2026).
 4. DUMP LEGGIBILE consegnato insieme ai numeri, non su richiesta: per ogni
    arena, i nomi dei giocatori scelti da REALE/A/G con i punteggi, piu'
    l'elenco delle carte fra cui il modello poteva scegliere.

Uso:
  python analisi_manager/p13_backtest_gw_crowss.py --gw football-21-24-jul-2026
"""
import os
import sys
import io
import json
import argparse
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import p12_backtest_manager_full as F
import analizza_gw as AG

cache = CACHE.CacheLocale()

ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_beginner',
                      'arena_limited_uncapped'}
COMP_TO_BUILD = {
    'Cap 260': ('ARENA_ALLSTARS_260', True),
    'Cap 220': ('ARENA_ALLSTARS_220', True),
    'Uncapped': ('ARENA_ALLSTARS_UNCAPPED', True),
    'Beginner': ('ARENA_ALLSTARS_260', True),   # identica alla 260 tranne i premi
}
CAP_ARENA = 0.2      # build_formazione_globale: arene
CAP_FUORI = 0.5      # build_formazione_globale: tutto il resto


def score_da_cache(slug, d_start, d_end):
    """Il punteggio GREZZO del giocatore, letto dalla cache game-log.

    E' il numero vero, senza bonus di nessun tipo, e non dipende da dove la
    carta e' stata schierata. Va preferito SEMPRE alla ricostruzione per
    divisione (vedi punteggio_grezzo).
    """
    a, b = d_start.isoformat()[:10], d_end.isoformat()[:10]
    for nodo in cache.gamelog(slug):
        data = ((nodo.get('anyGame') or {}).get('date') or '')[:10]
        if a <= data <= b and nodo.get('scoreStatus') in ('FINAL', 'REVIEWING'):
            return nodo.get('score')
    return None


def punteggio_grezzo(carta, in_arena):
    """FALLBACK, da usare solo se la cache non ha il giocatore.

    Ricostruisce il grezzo per divisione: in arena l'xp non conta e il
    capitano vale +20%; fuori, xp e capitano si SOMMANO e il capitano vale
    +50%. La struttura e' giusta ma `bonus_carta` sottostima il bonus vero,
    quindi l'errore e' dell'1-3%, sistematico e piu' grande sulle carte
    pregiate. Misurato sulla GW 21-24 jul: scarto medio 0.82 punti contro la
    cache, massimo 5.78, con 79 carte su 179 oltre mezzo punto.
    """
    p = carta.get('punteggio')
    if p is None:
        return None
    if in_arena:
        bonus = CAP_ARENA if carta.get('capitano') else 0.0
    else:
        bonus = carta.get('bonus_carta') or 0.0
        if carta.get('capitano'):
            bonus += CAP_FUORI
    return p / (1.0 + bonus)


def grezzo_carta(carta, in_arena, d_start, d_end, contatore):
    """Grezzo preferendo la cache, con fallback dichiarato e contato."""
    s = score_da_cache(carta.get('slug'), d_start, d_end)
    if s is not None:
        contatore['cache'] += 1
        return s, 'cache'
    contatore['fallback'] += 1
    return punteggio_grezzo(carta, in_arena), 'ricostruito'


def carica_gw(manager, gw):
    path = os.path.join(ROOT, 'dati_globali', f'manager_{manager}.json')
    with open(path, encoding='utf-8') as f:
        dati = json.load(f)
    righe = (dati.get('giornate') or {}).get(gw)
    if not righe:
        raise SystemExit(f'GW {gw} assente per {manager}')
    return righe


def costruisci_pool(righe, modo='globale'):
    """Una voce per CARTA (non per giocatore: xp e bonus distinguono le copie).

    modo='globale': prende da TUTTE le formazioni della giornata, arene comprese.
    modo='arena'  : prende SOLO dalle formazioni schierate in arena. In questa
        modalita' il pool coincide quasi con gli slot (vedi CLAUDE.md/handoff
        06/08): non misura la selezione delle carte, solo l'allocazione fra
        arene e la scelta del capitano.
    """
    pool = {}
    vuote = 0
    for f in righe:
        carte = f.get('carte')
        if not carte:
            vuote += 1
            continue
        in_arena = bool(f.get('tipo_arena'))
        if modo == 'arena' and not in_arena:
            continue
        for c in carte:
            cid = c.get('carta')
            if cid and cid not in pool:
                pool[cid] = (c, in_arena)
    return pool, vuote


def prepara_righe_pool(pool):
    """Aggancia a ogni carta lo score_atteso di produzione e il grade."""
    idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug = collections.defaultdict(dict)
    for (slug, data), grade in idx_grade.items():
        idx_per_slug[slug][data] = grade
    return idx_per_slug


def costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug):
    """Una riga per carta con score_atteso walk-forward, grezzo (cache, mai
    raw/1.2) e grade. Scarta e dichiara chi non ha atteso o grezzo."""
    fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
    rows = []
    scarti = collections.Counter()
    for cid, (c, in_arena) in pool.items():
        ruolo_full = c.get('ruolo')
        cod = M.ROLE_CODE.get(ruolo_full)
        if cod is None:
            scarti['ruolo_sconosciuto'] += 1
            continue
        slug = c.get('slug')
        r = P.score_atteso(cache, slug, ruolo_full, fine)
        if r is None or r.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        reale, _fonte = grezzo_carta(c, in_arena, d_start, d_end, conta)
        if reale is None:
            scarti['no_grezzo'] += 1
            continue
        lega = lega_di.get(slug) or 'senza_lega'
        grade = F.trova_grade_finestra(idx_per_slug, slug, d_start, d_end)
        rows.append({'slug': slug, 'carta': cid, 'nome': c.get('nome'), 'codice': cod,
                    'lega': lega, 'squadra': r.get('squadra'), 'opp_slug': r.get('opp_slug'),
                    'atteso_raw': r['atteso'], 'l10': r.get('l10'), 'copie': 1,
                    'reale': reale, '_grade': grade})
    for c in rows:
        c['_cal'] = S21.bfg.calibra(c['atteso_raw'], c['codice'])
    gruppi = collections.defaultdict(list)
    for c in rows:
        gruppi[(c['lega'], c['codice'])].append(c)
    for (_lg, _cod), membri in gruppi.items():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp = [m['_grade'] for m in membri if m['_grade'] is not None]
        if len(gp) >= 2:
            zg, _, _ = S21.zscore_gruppo(gp)
            it = iter(zg)
            for m in membri:
                m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
        else:
            for m in membri:
                m['_zgrade'] = 0.0
        for m in membri:
            m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']
    return rows, scarti


def gioca_arene(pool_rows, slots, obiettivo_key):
    """Riusa S21.costruisci + bfg.build_one_lineup_with_growth (come
    p12_backtest_manager_full.py), rinuncia a un'arena se sotto
    PAREGGIO_ARENA. Ogni slot e' una delle 17 arene reali, coi suoi cap."""
    nome_per_slug = {r['slug']: r['nome'] for r in pool_rows}
    gw_data = {'pool': pool_rows}
    role_data, pools, card_pool, leghe = S21.costruisci(gw_data, lambda c: c[obiettivo_key])
    orig = S21.bfg.LEAGUES
    S21.bfg.LEAGUES = tuple(leghe)
    out = []
    try:
        for s in slots:
            shape = S21.bfg.FORMATION_SHAPES[s['tipo_bfg']]
            pool_league = S21.bfg.POOL_LEAGUE_BY_TYPE[s['tipo_bfg']]
            l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(s['tipo_bfg'])
            stato = S21.bfg._istantanea_pool(card_pool)
            formazione, errore, _ok, _sp = S21.bfg.build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, l10_cap,
                apply_stack_guard=False, variance_mode=True,
                apply_positive_synergy=False, strict_gk_anti_synergy=False)
            if errore or not formazione:
                S21.bfg._ripristina_pool(card_pool, stato)
                out.append({'competizione': s['competizione'], 'schierata': False, 'punti': 0.0, 'carte': []})
                continue
            cap_row = S21.capitano_atteso(formazione)
            atteso_sum = sum(r['atteso_cal'] for _x, r, _t in formazione) + \
                0.2 * (cap_row['atteso_cal'] if cap_row else 0.0)
            soglia = S21.bfg.PAREGGIO_ARENA.get(s['tipo_bfg'])
            margine = atteso_sum - soglia if soglia is not None else 1.0
            if margine < 0:
                S21.bfg._ripristina_pool(card_pool, stato)
                out.append({'competizione': s['competizione'], 'schierata': False, 'punti': 0.0,
                           'carte': [], 'margine': margine})
                continue
            punti = S21.realizzato(formazione, cap_row)
            scelte = [{'nome': nome_per_slug.get(r['slug']), 'slug': r['slug'], 'ruolo': r['role_key'],
                      'grezzo': r['reale'], 'capitano': (cap_row is not None and r['slug'] == cap_row['slug'])}
                     for _x, r, _t in formazione]
            out.append({'competizione': s['competizione'], 'schierata': True, 'punti': punti,
                       'carte': scelte, 'margine': margine})
    finally:
        S21.bfg.LEAGUES = orig
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('--gw', required=True)
    ap.add_argument('--dump', default=None, help='file di dump leggibile')
    ap.add_argument('--pool', choices=('globale', 'arena'), default='globale',
                     help='globale = tutte le competizioni (test probante); '
                          'arena = solo carte schierate in arena (controllo aggiuntivo, '
                          'NON misura selezione: vedi handoff 06/08 sez.5)')
    ap.add_argument('--consenti-pool-uguale-slot', action='store_true',
                     help='autorizza il caso pool<=slot SOLO con --pool arena; '
                          'in modalita globale resta sempre un errore fatale')
    args = ap.parse_args()

    if args.consenti_pool_uguale_slot and args.pool != 'arena':
        raise SystemExit('--consenti-pool-uguale-slot e\' ammesso SOLO con --pool arena')

    righe = carica_gw(args.manager, args.gw)
    arene = [f for f in righe if f.get('tipo_arena') in ARENE_AMMESSE_TIPO]
    non_arene = [f for f in righe if not f.get('tipo_arena')]
    pool, vuote = costruisci_pool(righe, modo=args.pool)

    slot_totali = sum(len(f.get('carte') or []) for f in arene)

    print('=' * 72)
    print(f'BACKTEST GW {args.gw} -- manager {args.manager}  -- modalita pool: {args.pool.upper()}')
    print('=' * 72)
    if args.pool == 'arena':
        print('ATTENZIONE: pool = SOLO carte schierate in arena quella GW. Il pool')
        print('coincide quasi con gli slot: questo test NON misura la selezione delle')
        print('carte, misura solo (a) come il modello alloca le stesse carte fra le')
        print('arene e (b) chi rinuncia/sceglie come capitano. Il test probante resta')
        print('la modalita globale (default).')
        print()
    print(f'formazioni totali in giornata : {len(righe)}')
    print(f'  di cui ARENE                : {len(arene)}')
    print(f'  di cui altre competizioni   : {len(non_arene)}')
    print(f'righe SENZA carte (perse)     : {vuote}')
    comp = collections.Counter(f.get('competizione') for f in arene)
    for k, v in comp.most_common():
        print(f'    arena: {v:3} x {k}')
    print()
    print('--- CONTROLLO OBBLIGATORIO POOL vs SLOT (CLAUDE.md 06/08/2026) ---')
    print(f'carte distinte nel pool : {len(pool)}')
    print(f'slot da riempire        : {slot_totali}')
    print(f'CARTE DI SCORTA         : {len(pool) - slot_totali}')
    if len(pool) <= slot_totali:
        if args.pool == 'arena' and args.consenti_pool_uguale_slot:
            print()
            print('POOL NON PIU\' GRANDE DEGLI SLOT -- autorizzato esplicitamente con')
            print('--consenti-pool-uguale-slot in modalita ARENA. Questo test misura SOLO')
            print('allocazione/capitano, non selezione delle carte (vedi avviso sopra).')
            print()
        else:
            print()
            print('POOL NON PIU\' GRANDE DEGLI SLOT: nessuna selezione da misurare.')
            if args.pool == 'arena':
                print('Se e\' l\'esito atteso in modalita arena, rilancia con')
                print('--consenti-pool-uguale-slot per procedere comunque.')
            print('Il test sarebbe nullo per costruzione. MI FERMO QUI.')
            return 1
    print()

    if vuote:
        print(f'ATTENZIONE: {vuote} formazioni salvate senza carte. Il pool e il')
        print('totale reale sono piu\' piccoli del vero. Lanciare prima')
        print('ripesca_formazioni_vuote.py, poi rifare questo test.')
        print()

    # --- totale reale del manager, coi punteggi ufficiali (bonus compresi) ---
    reale_per_arena = []
    for f in arene:
        tot = sum(c.get('punteggio') or 0 for c in (f.get('carte') or []))
        reale_per_arena.append({'competizione': f.get('competizione'),
                                'punti': tot,
                                'carte': f.get('carte') or []})
    reale_tot = sum(a['punti'] for a in reale_per_arena)
    print(f'TOTALE REALE crowss su {len(arene)} arene: {reale_tot:.2f} '
          f'(media {reale_tot / max(len(arene), 1):.2f} per arena)')
    print()

    bounds = M.parse_fixture_bounds(args.gw)
    if bounds is None:
        raise SystemExit(f'non riesco a leggere le date dalla GW {args.gw}')
    d_start, d_end = bounds
    conta = collections.Counter()

    # --- pool con score_atteso/grezzo/grade, poi A e G sulle 17 arene reali ---
    lega_di = AG.indice_lega()
    idx_per_slug = prepara_righe_pool(pool)
    pool_rows, scarti_pool = costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug)
    print(f'righe pool con atteso+grezzo utilizzabili: {len(pool_rows)}/{len(pool)}  '
          f'(scarti: {dict(scarti_pool)})')

    slots = []
    for f in arene:
        comp = f.get('competizione')
        info = COMP_TO_BUILD.get(comp)
        if info is None:
            print(f'ATTENZIONE: competizione arena non mappata: {comp!r} -- arena saltata dal choice-set')
            continue
        tipo_bfg, _ha_soglia = info
        l10_cap = S21.bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
        n_ammissibili = sum(1 for r in pool_rows if l10_cap is None or (r['l10'] or 0) <= l10_cap)
        slots.append({'competizione': comp, 'tipo_bfg': tipo_bfg, 'l10_cap': l10_cap,
                      'n_ammissibili': n_ammissibili,
                      'reale_carte': [{'nome': c.get('nome'), 'slug': c.get('slug'),
                                       'capitano': c.get('capitano')} for c in (f.get('carte') or [])]})
    if len(slots) != len(arene):
        print(f'ATTENZIONE: {len(arene) - len(slots)} arene reali fuori dal choice-set del modello '
              '(competizione non mappata) -- non entrano in A/G, restano solo nel REALE.')

    esito_A = gioca_arene(pool_rows, slots, '_cal')
    esito_G = gioca_arene(pool_rows, slots, '_combinato')

    tot_A = sum(e['punti'] for e in esito_A)
    tot_G = sum(e['punti'] for e in esito_G)
    n_A = sum(1 for e in esito_A if e['schierata'])
    n_G = sum(1 for e in esito_G if e['schierata'])
    reale_tot_scelte = sum(a['punti'] for a in reale_per_arena if a['competizione'] in COMP_TO_BUILD)

    print()
    print('=' * 72)
    print(f'PUNTI TOTALI su {len(slots)} arene nel choice-set (REALE su queste stesse arene: '
          f'{reale_tot_scelte:.2f})')
    print(f'  REALE : {reale_tot_scelte:.2f}  (17/17 schierate, e\' il manager vero)')
    print(f'  A     : {tot_A:.2f}  ({n_A}/{len(slots)} schierate)')
    print(f'  G     : {tot_G:.2f}  ({n_G}/{len(slots)} schierate)')

    print('\nPER TIPO ARENA:')
    for comp in ('Cap 260', 'Cap 220', 'Uncapped', 'Beginner'):
        r_tipo = sum(a['punti'] for a in reale_per_arena if a['competizione'] == comp)
        n_tipo = sum(1 for a in reale_per_arena if a['competizione'] == comp)
        a_tipo = sum(e['punti'] for e in esito_A if e['competizione'] == comp)
        g_tipo = sum(e['punti'] for e in esito_G if e['competizione'] == comp)
        na_tipo = sum(1 for e in esito_A if e['competizione'] == comp and e['schierata'])
        ng_tipo = sum(1 for e in esito_G if e['competizione'] == comp and e['schierata'])
        if n_tipo == 0:
            continue
        print(f'  {comp:10s} REALE={r_tipo:8.2f}(n={n_tipo:2d})  '
              f'A={a_tipo:8.2f}(schierate={na_tipo}/{n_tipo})  '
              f'G={g_tipo:8.2f}(schierate={ng_tipo}/{n_tipo})')

    print('\nPER SINGOLA ARENA (REALE vs A vs G):')
    for i, (r_arena, ea, eg, s) in enumerate(zip(
            [a for a in reale_per_arena if a['competizione'] in COMP_TO_BUILD], esito_A, esito_G, slots), 1):
        txt_a = f"{ea['punti']:7.2f}" if ea['schierata'] else '     --'
        txt_g = f"{eg['punti']:7.2f}" if eg['schierata'] else '     --'
        print(f"  [{i:2d}] {s['competizione']:10s} amm={s['n_ammissibili']:3d}  "
              f"REALE={r_arena['punti']:7.2f}  A={txt_a}  G={txt_g}")

    if args.dump:
        with open(args.dump, 'w', encoding='utf-8') as fh:
            fh.write(f'DUMP {args.gw} -- {args.manager}  -- modalita pool: {args.pool.upper()}\n')
            if args.pool == 'arena':
                fh.write('ATTENZIONE: pool = solo carte schierate in arena quella GW. Pool quasi\n'
                         'uguale agli slot: NON misura la selezione delle carte, solo allocazione\n'
                         'fra arene e scelta del capitano. Test probante = modalita globale.\n\n')
            fh.write('grezzo = punteggio del giocatore senza bonus, letto dalla '
                     'cache game-log (fonte: cache). Dove il giocatore non e\' in '
                     'cache, ricostruito per divisione (fonte: ricostruito).\n\n')
            arene_scelte = [a for a in reale_per_arena if a['competizione'] in COMP_TO_BUILD]
            for i, (a, s, ea, eg) in enumerate(zip(arene_scelte, slots, esito_A, esito_G), 1):
                fh.write(f"--- ARENA {i}: {a['competizione']}  (ammissibili nel pool: "
                         f"{s['n_ammissibili']})  REALE {a['punti']:.2f} ---\n")
                fh.write('  REALE:\n')
                for c in a['carte']:
                    g, fonte = grezzo_carta(c, True, d_start, d_end, conta)
                    cap = '  [CAPITANO]' if c.get('capitano') else ''
                    fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):26} "
                             f"uff={c.get('punteggio'):7.2f} grezzo={g:7.2f} "
                             f"[{fonte}]{cap}\n")
                for label, e in (('A', ea), ('G', eg)):
                    if not e['schierata']:
                        margine = e.get('margine')
                        mtxt = f" (margine {margine:+.1f})" if margine is not None else ''
                        fh.write(f"  {label}: NON SCHIERATA{mtxt}\n")
                        continue
                    fh.write(f"  {label} (totale {e['punti']:.2f}):\n")
                    for c in e['carte']:
                        cap = '  [CAPITANO]' if c['capitano'] else ''
                        fh.write(f"    {c['ruolo']:4} {c['nome'] or c['slug']:26} "
                                 f"grezzo={c['grezzo']:7.2f}{cap}\n")
                fh.write('\n')
            fh.write(f'\nPOOL DISPONIBILE: {len(pool)} carte\n')
            per_ruolo = collections.defaultdict(list)
            for cid, (c, in_arena) in pool.items():
                g, fonte = grezzo_carta(c, in_arena, d_start, d_end, conta)
                per_ruolo[c.get('ruolo')].append(
                    (g, c.get('nome'), 'arena' if in_arena else 'altra', fonte))
            for r in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
                fh.write(f'\n--- {r}: {len(per_ruolo[r])} carte ---\n')
                for g, n, src, fonte in sorted(per_ruolo[r], reverse=True):
                    fh.write(f'   {g:7.2f}  {n:26} (da {src}, {fonte})\n')
        print(f'dump scritto in {args.dump}')

    print(f"punteggi grezzi letti dalla CACHE : {conta['cache']}")
    print(f"punteggi RICOSTRUITI per divisione: {conta['fallback']}"
          "   <- questi hanno un errore dell'1-3%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
