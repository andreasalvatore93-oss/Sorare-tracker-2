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

ARENE_AMMESSE_TIPO = {'arena_limited', 'arena_limited_uncapped'}
# arena_limited_beginner ESCLUSA da tutti i 3 test (brief 06/08 notte): la
# soglia beginner nel generatore non esiste, oggi e' copiata di peso dalla
# Cap 260 e non e' mai stata tarata; inoltre crowss non le gioca piu'.
# Stesso universo di arene (Cap 220/260/Uncapped) per i 3 test.
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
    modo='arena'  : prende SOLO dalle formazioni schierate nelle arene AMMESSE
        (ARENE_AMMESSE_TIPO, beginner escluse). In questa modalita' il pool
        coincide quasi con gli slot delle stesse arene (vedi CLAUDE.md/handoff
        06/08): non misura la selezione delle carte, solo l'allocazione fra
        arene e la scelta del capitano. Le carte delle arene beginner NON
        entrano nel pool: altrimenti sarebbero scorte artificiali senza uno
        slot corrispondente, dato che le beginner sono escluse dai 3 test.
    """
    pool = {}
    vuote = 0
    for f in righe:
        carte = f.get('carte')
        if not carte:
            vuote += 1
            continue
        in_arena = bool(f.get('tipo_arena'))  # per il bonus corretto (CAP_ARENA), qualunque tipo di arena
        in_arena_ammessa = f.get('tipo_arena') in ARENE_AMMESSE_TIPO  # per il filtro del pool modo='arena'
        if modo == 'arena' and not in_arena_ammessa:
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
            scelte = [{'nome': nome_per_slug.get(r['slug']), 'slug': r['slug'], 'carta': r.get('carta'),
                      'ruolo': r['role_key'], 'grezzo': r['reale'],
                      'capitano': (cap_row is not None and r['slug'] == cap_row['slug'])}
                     for _x, r, _t in formazione]
            out.append({'competizione': s['competizione'], 'schierata': True, 'punti': punti,
                       'carte': scelte, 'margine': margine})
    finally:
        S21.bfg.LEAGUES = orig
    return out


def setup_comune(args):
    """Caricamento condiviso dai 3 test: righe GW, arene (beginner escluse),
    reale_per_arena (punteggi ufficiali), date, contatore fonte-grezzo."""
    righe = carica_gw(args.manager, args.gw)
    arene = [f for f in righe if f.get('tipo_arena') in ARENE_AMMESSE_TIPO]
    non_arene = [f for f in righe if not f.get('tipo_arena')]
    n_beginner = sum(1 for f in righe if f.get('tipo_arena') == 'arena_limited_beginner')

    print(f'formazioni totali in giornata : {len(righe)}')
    print(f'  di cui ARENE (no beginner)  : {len(arene)}')
    print(f'  di cui BEGINNER (escluse)   : {n_beginner}')
    print(f'  di cui altre competizioni   : {len(non_arene)}')
    comp = collections.Counter(f.get('competizione') for f in arene)
    for k, v in comp.most_common():
        print(f'    arena: {v:3} x {k}')
    print()

    reale_per_arena = []
    for f in arene:
        tot = sum(c.get('punteggio') or 0 for c in (f.get('carte') or []))
        reale_per_arena.append({'competizione': f.get('competizione'),
                                'punti': tot, 'carte': f.get('carte') or []})
    reale_tot = sum(a['punti'] for a in reale_per_arena)
    print(f'TOTALE REALE {args.manager} su {len(arene)} arene: {reale_tot:.2f} '
          f'(media {reale_tot / max(len(arene), 1):.2f} per arena)')
    print()

    bounds = M.parse_fixture_bounds(args.gw)
    if bounds is None:
        raise SystemExit(f'non riesco a leggere le date dalla GW {args.gw}')
    d_start, d_end = bounds
    conta = collections.Counter()
    lega_di = AG.indice_lega()
    return righe, arene, reale_per_arena, d_start, d_end, conta, lega_di


def controllo_pool_vs_slot(pool, slot_totali, modo, consenti_uguale):
    """Stampa il controllo obbligatorio. Ritorna True se si puo' proseguire."""
    print('--- CONTROLLO OBBLIGATORIO POOL vs SLOT (CLAUDE.md 06/08/2026) ---')
    print(f'carte distinte nel pool : {len(pool)}')
    print(f'slot da riempire        : {slot_totali}')
    print(f'CARTE DI SCORTA         : {len(pool) - slot_totali}')
    if len(pool) > slot_totali:
        print()
        return True
    if modo == 'arena' and consenti_uguale:
        print()
        print('POOL NON PIU\' GRANDE DEGLI SLOT -- atteso in questa modalita\' (vedi')
        print('avviso in testa): si misura SOLO allocazione/capitano, non selezione.')
        print()
        return True
    print()
    print('POOL NON PIU\' GRANDE DEGLI SLOT: nessuna selezione da misurare.')
    print('Il test sarebbe nullo per costruzione. MI FERMO QUI.')
    return False


def costruisci_slots(arene, pool_rows):
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
                      'n_ammissibili': n_ammissibili})
    if len(slots) != len(arene):
        print(f'ATTENZIONE: {len(arene) - len(slots)} arene reali fuori dal choice-set del modello '
              '(competizione non mappata) -- non entrano in A/G, restano solo nel REALE.')
    return slots


def scrivi_dump_selezione(path, gw, manager, modo, pool, d_start, d_end, conta,
                          arene_scelte, slots, esito_A, esito_G, extra_header=''):
    """Dump condiviso da TEST1 e TEST2: arena per arena REALE/A/G con ID carta,
    piu' l'elenco del pool disponibile per ruolo."""
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(f'DUMP {gw} -- {manager}  -- modalita pool: {modo.upper()}\n')
        if extra_header:
            fh.write(extra_header)
        fh.write('grezzo = punteggio del giocatore senza bonus, letto dalla '
                 'cache game-log (fonte: cache). Dove il giocatore non e\' in '
                 'cache, ricostruito per divisione (fonte: ricostruito).\n'
                 'carta = ID della carta specifica (un giocatore puo\' avere piu\' '
                 'carte, vedi CLAUDE.md D7).\n\n')
        for i, (a, s, ea, eg) in enumerate(zip(arene_scelte, slots, esito_A, esito_G), 1):
            fh.write(f"--- ARENA {i}: {a['competizione']}  (ammissibili nel pool: "
                     f"{s['n_ammissibili']})  REALE {a['punti']:.2f} ---\n")
            fh.write('  REALE:\n')
            for c in a['carte']:
                g, fonte = grezzo_carta(c, True, d_start, d_end, conta)
                cap = '  [CAPITANO]' if c.get('capitano') else ''
                fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):26} "
                         f"carta={c.get('carta')!s:24} uff={c.get('punteggio'):7.2f} "
                         f"grezzo={g:7.2f} [{fonte}]{cap}\n")
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
                             f"carta={c.get('carta')!s:24} grezzo={c['grezzo']:7.2f}{cap}\n")
            fh.write('\n')
        fh.write(f'\nPOOL DISPONIBILE: {len(pool)} carte\n')
        per_ruolo = collections.defaultdict(list)
        for cid, (c, in_arena) in pool.items():
            g, fonte = grezzo_carta(c, in_arena, d_start, d_end, conta)
            per_ruolo[c.get('ruolo')].append(
                (g, c.get('nome'), c.get('carta'), 'arena' if in_arena else 'altra', fonte))
        for r in ('Goalkeeper', 'Defender', 'Midfielder', 'Forward'):
            fh.write(f'\n--- {r}: {len(per_ruolo[r])} carte ---\n')
            for g, n, cid, src, fonte in sorted(per_ruolo[r], reverse=True):
                fh.write(f'   {g:7.2f}  {n:26} carta={cid!s:24} (da {src}, {fonte})\n')


def _stampa_riepilogo_selezione(nome_test, slots, reale_per_arena, esito_A, esito_G, arene_scelte):
    tot_A = sum(e['punti'] for e in esito_A)
    tot_G = sum(e['punti'] for e in esito_G)
    n_A = sum(1 for e in esito_A if e['schierata'])
    n_G = sum(1 for e in esito_G if e['schierata'])
    reale_tot_scelte = sum(a['punti'] for a in arene_scelte)

    print()
    print('=' * 72)
    print(f'{nome_test}: PUNTI TOTALI su {len(slots)} arene nel choice-set '
          f'(REALE su queste stesse arene: {reale_tot_scelte:.2f})')
    print(f'  REALE : {reale_tot_scelte:.2f}  ({len(arene_scelte)}/{len(arene_scelte)} schierate, e\' il manager vero)')
    print(f'  A     : {tot_A:.2f}  ({n_A}/{len(slots)} schierate)')
    print(f'  G     : {tot_G:.2f}  ({n_G}/{len(slots)} schierate)')

    print('\nPER TIPO ARENA:')
    for comp in ('Cap 260', 'Cap 220', 'Uncapped'):
        r_tipo = sum(a['punti'] for a in arene_scelte if a['competizione'] == comp)
        n_tipo = sum(1 for a in arene_scelte if a['competizione'] == comp)
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
    for i, (r_arena, ea, eg, s) in enumerate(zip(arene_scelte, esito_A, esito_G, slots), 1):
        txt_a = f"{ea['punti']:7.2f}" if ea['schierata'] else '     --'
        txt_g = f"{eg['punti']:7.2f}" if eg['schierata'] else '     --'
        print(f"  [{i:2d}] {s['competizione']:10s} amm={s['n_ammissibili']:3d}  "
              f"REALE={r_arena['punti']:7.2f}  A={txt_a}  G={txt_g}")
    return tot_A, tot_G


def esegui_test1(args, righe, arene, reale_per_arena, d_start, d_end, conta, lega_di):
    """TEST 1 -- FULL POOL (selezione). Pool = tutte le competizioni della
    giornata. E' il test probante: misura la selezione delle carte."""
    print('IPOTESI: col pool globale (102 carte di scorta gia\' viste sulla GW93)')
    print('il modello ha margine reale di scelta; ci si aspetta che A e G possano')
    print('discostarsi da REALE sia in meglio che in peggio, arena per arena.')
    print()

    pool, vuote = costruisci_pool(righe, modo='globale')
    slot_totali = sum(len(a['carte']) for a in reale_per_arena)
    if vuote:
        print(f'ATTENZIONE: {vuote} formazioni salvate senza carte (pool piu\' piccolo del vero).')
        print()
    if not controllo_pool_vs_slot(pool, slot_totali, 'globale', False):
        return None

    idx_per_slug = prepara_righe_pool(pool)
    pool_rows, scarti_pool = costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug)
    print(f'righe pool con atteso+grezzo utilizzabili: {len(pool_rows)}/{len(pool)}  '
          f'(scarti: {dict(scarti_pool)})')

    slots = costruisci_slots(arene, pool_rows)
    arene_scelte = [a for a in reale_per_arena if a['competizione'] in COMP_TO_BUILD]

    esito_A = gioca_arene(pool_rows, slots, '_cal')
    esito_G = gioca_arene(pool_rows, slots, '_combinato')
    _stampa_riepilogo_selezione('TEST1 (full pool)', slots, reale_per_arena, esito_A, esito_G, arene_scelte)

    if args.dump:
        scrivi_dump_selezione(args.dump, args.gw, args.manager, 'globale', pool,
                              d_start, d_end, conta, arene_scelte, slots, esito_A, esito_G)
        print(f'\ndump scritto in {args.dump}')
    return {'pool_rows': pool_rows, 'esito_A': esito_A, 'esito_G': esito_G, 'slots': slots}


def esegui_test2(args, righe, arene, reale_per_arena, d_start, d_end, conta, lega_di):
    """TEST 2 -- RISTRETTO + metrica k (qualita' allocazione). Pool = solo
    carte che REALE ha messo in arena quella GW: pool ~= slot per costruzione,
    quindi NON misura selezione. Confronto a concentrazione appaiata: per
    ogni tipo arena, k = quante ne schiera il modello; si confronta la sua
    media su quelle k contro la media delle k MIGLIORI arene REALI dello
    stesso tipo (le piu' paganti, non le prime k a caso)."""
    print('IPOTESI: pool ~ slot (85=85 su GW93, vedi handoff sez.5). Questo test')
    print('NON misura la selezione delle carte: misura solo come il modello')
    print('alloca le STESSE carte fra le arene e la scelta del capitano.')
    print()

    pool, vuote = costruisci_pool(righe, modo='arena')
    slot_totali = sum(len(a['carte']) for a in reale_per_arena)
    if not controllo_pool_vs_slot(pool, slot_totali, 'arena', consenti_uguale=True):
        return None

    idx_per_slug = prepara_righe_pool(pool)
    pool_rows, scarti_pool = costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug)
    print(f'righe pool con atteso+grezzo utilizzabili: {len(pool_rows)}/{len(pool)}  '
          f'(scarti: {dict(scarti_pool)})')

    slots = costruisci_slots(arene, pool_rows)
    arene_scelte = [a for a in reale_per_arena if a['competizione'] in COMP_TO_BUILD]

    esito_A = gioca_arene(pool_rows, slots, '_cal')
    esito_G = gioca_arene(pool_rows, slots, '_combinato')
    _stampa_riepilogo_selezione('TEST2 (pool ristretto)', slots, reale_per_arena, esito_A, esito_G, arene_scelte)

    print('\nTEST2 -- METRICA k (concentrazione appaiata), per tipo arena:')
    print('k = numero di arene di quel tipo schierate dal modello. Si confronta')
    print('la media del modello sulle sue k arene contro la media delle k MIGLIORI')
    print('arene REALI dello stesso tipo (quelle con piu\' punti realizzati).')
    for label, esito in (('A', esito_A), ('G', esito_G)):
        print(f'\n  --- {label} ---')
        for comp in ('Cap 260', 'Cap 220', 'Uncapped'):
            reale_tipo = sorted((a['punti'] for a in arene_scelte if a['competizione'] == comp), reverse=True)
            k = sum(1 for e in esito if e['competizione'] == comp and e['schierata'])
            if not reale_tipo:
                continue
            if k == 0:
                print(f'  {comp:10s} k=0 (modello non ha schierato nessuna arena di questo tipo)')
                continue
            modello_media = sum(e['punti'] for e in esito if e['competizione'] == comp and e['schierata']) / k
            reale_best_k = reale_tipo[:k]
            reale_best_media = sum(reale_best_k) / len(reale_best_k)
            delta = modello_media - reale_best_media
            print(f'  {comp:10s} k={k}  modello_media={modello_media:7.2f}  '
                  f'REALE-best-{k}_media={reale_best_media:7.2f}  delta={delta:+7.2f}')

    if args.dump:
        extra = ('ATTENZIONE: pool = solo carte gia\' schierate in arena quella GW. Pool\n'
                'quasi uguale agli slot: NON misura selezione, solo allocazione/capitano.\n'
                'Vedi anche la metrica k in fondo al report di console.\n\n')
        scrivi_dump_selezione(args.dump, args.gw, args.manager, 'arena', pool,
                              d_start, d_end, conta, arene_scelte, slots, esito_A, esito_G, extra)
        print(f'\ndump scritto in {args.dump}')
    return {'pool_rows': pool_rows, 'esito_A': esito_A, 'esito_G': esito_G, 'slots': slots}


def esegui_test3(args, righe, arene, reale_per_arena, d_start, d_end, conta, lega_di):
    """TEST 3 -- DECISIONE (entrare o saltare). Il modello NON sceglie le
    carte: prende la formazione ESATTA di REALE in ogni arena. L'unica
    liberta' e' decidere se schierarla o rinunciare, confrontando l'atteso
    (A=score_atteso, G=score_atteso+grade) contro PAREGGIO_ARENA."""
    print('IPOTESI: isolando la sola decisione entra/salta (formazione fissa =')
    print('quella di REALE), ci si aspetta che il modello rinunci soprattutto')
    print('alle arene REALI che poi hanno reso sotto soglia -- se la calibrazione')
    print('di score_atteso e PAREGGIO_ARENA sono coerenti fra loro.')
    print()

    # pool globale, serve solo per leggere _cal/_combinato delle carte che
    # REALE ha gia' schierato in arena (niente selezione qui).
    pool, vuote = costruisci_pool(righe, modo='globale')
    idx_per_slug = prepara_righe_pool(pool)
    pool_rows, scarti_pool = costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug)
    riga_per_carta = {r['carta']: r for r in pool_rows}
    print(f'righe pool con atteso+grezzo utilizzabili: {len(pool_rows)}/{len(pool)}  '
          f'(scarti: {dict(scarti_pool)}) -- usate solo per leggere l\'atteso delle carte REALI')
    print()

    righe_report = []
    matrice = {'A': collections.Counter(), 'G': collections.Counter()}
    saltate_dati_mancanti = 0
    for a in reale_per_arena:
        comp = a['competizione']
        info = COMP_TO_BUILD.get(comp)
        if info is None:
            continue
        tipo_bfg, _ = info
        soglia = S21.bfg.PAREGGIO_ARENA.get(tipo_bfg)
        if soglia is None:
            continue
        carte = a['carte']
        rows = [riga_per_carta.get(c.get('carta')) for c in carte]
        if any(r is None for r in rows):
            saltate_dati_mancanti += 1
            continue
        cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
        atteso_A = sum(r['_cal'] for r in rows) + (0.2 * rows[cap_idx]['_cal'] if cap_idx is not None else 0.0)
        atteso_G = sum(r['_combinato'] for r in rows) + (0.2 * rows[cap_idx]['_combinato'] if cap_idx is not None else 0.0)
        real_points = a['punti']
        conviene = real_points >= soglia
        dec_A = atteso_A >= soglia
        dec_G = atteso_G >= soglia

        def esito_cella(conviene, decide_entra):
            if conviene and decide_entra:
                return 'giusto'
            if conviene and not decide_entra:
                return 'ERRORE (persa arena buona)'
            if not conviene and not decide_entra:
                return 'GIUSTO (batte REALE)'
            return 'errore (come REALE)'

        cella_A = esito_cella(conviene, dec_A)
        cella_G = esito_cella(conviene, dec_G)
        matrice['A'][cella_A] += 1
        matrice['G'][cella_G] += 1
        righe_report.append({'competizione': comp, 'soglia': soglia, 'real_points': real_points,
                             'conviene': conviene, 'atteso_A': atteso_A, 'dec_A': dec_A, 'cella_A': cella_A,
                             'atteso_G': atteso_G, 'dec_G': dec_G, 'cella_G': cella_G})

    if saltate_dati_mancanti:
        print(f'ATTENZIONE: {saltate_dati_mancanti} arene REALI escluse dalla matrice '
              '(atteso non disponibile per una delle 5 carte).')
        print()

    print(f'TEST3 -- arene valutate: {len(righe_report)}')
    print('\nPER SINGOLA ARENA (soglia PAREGGIO_ARENA, atteso A/G, decisione):')
    for i, r in enumerate(righe_report, 1):
        print(f"  [{i:2d}] {r['competizione']:10s} soglia={r['soglia']:7.2f}  "
              f"REALE={r['real_points']:7.2f} (conviene={r['conviene']})  "
              f"A: atteso={r['atteso_A']:7.2f} {'ENTRA' if r['dec_A'] else 'SALTA':5s} -> {r['cella_A']}  "
              f"G: atteso={r['atteso_G']:7.2f} {'ENTRA' if r['dec_G'] else 'SALTA':5s} -> {r['cella_G']}")

    for label in ('A', 'G'):
        m = matrice[label]
        print(f'\nMATRICE {label} (su {len(righe_report)} arene):')
        print(f"  conviene  + entra  = giusto                    : {m['giusto']}")
        print(f"  conviene  + salta  = ERRORE (persa arena buona) : {m['ERRORE (persa arena buona)']}")
        print(f"  non conv. + salta  = GIUSTO (batte REALE)       : {m['GIUSTO (batte REALE)']}")
        print(f"  non conv. + entra  = errore (come REALE)        : {m['errore (come REALE)']}")
        print(f"  -> batte REALE (salti giusti)      : {m['GIUSTO (batte REALE)']}")
        print(f"  -> sbaglia in modo costoso (persi)  : {m['ERRORE (persa arena buona)']}")

    if args.dump:
        with open(args.dump, 'w', encoding='utf-8') as fh:
            fh.write(f'DUMP {args.gw} -- {args.manager}  -- TEST3 decisione entra/salta\n')
            fh.write('Formazione FISSA = quella di REALE in ogni arena (stesse 5 carte, stesso\n'
                     'capitano). Il modello decide solo se schierarla, confrontando l\'atteso\n'
                     '(A/G) con PAREGGIO_ARENA. carta = ID carta specifica.\n\n')
            for i, a in enumerate(reale_per_arena, 1):
                comp = a['competizione']
                info = COMP_TO_BUILD.get(comp)
                if info is None:
                    continue
                fh.write(f"--- ARENA {i}: {comp}  REALE {a['punti']:.2f} ---\n")
                for c in a['carte']:
                    g, fonte = grezzo_carta(c, True, d_start, d_end, conta)
                    cap = '  [CAPITANO]' if c.get('capitano') else ''
                    fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):26} "
                             f"carta={c.get('carta')!s:24} uff={c.get('punteggio'):7.2f} "
                             f"grezzo={g:7.2f} [{fonte}]{cap}\n")
                match = next((r for r in righe_report if r is not None and
                             r['competizione'] == comp and abs(r['real_points'] - a['punti']) < 1e-6), None)
                if match:
                    fh.write(f"    soglia={match['soglia']:.2f}  conviene={match['conviene']}\n")
                    fh.write(f"    A: atteso={match['atteso_A']:.2f} "
                             f"{'ENTRA' if match['dec_A'] else 'SALTA'} -> {match['cella_A']}\n")
                    fh.write(f"    G: atteso={match['atteso_G']:.2f} "
                             f"{'ENTRA' if match['dec_G'] else 'SALTA'} -> {match['cella_G']}\n")
                else:
                    fh.write('    (esclusa dalla matrice: atteso non disponibile per una carta)\n')
                fh.write('\n')
            fh.write('\nMATRICE FINALE:\n')
            for label in ('A', 'G'):
                m = matrice[label]
                fh.write(f'  {label}: giusto={m["giusto"]}  '
                        f'ERRORE_persa_buona={m["ERRORE (persa arena buona)"]}  '
                        f'GIUSTO_batte_reale={m["GIUSTO (batte REALE)"]}  '
                        f'errore_come_reale={m["errore (come REALE)"]}\n')
        print(f'\ndump scritto in {args.dump}')
    return {'righe_report': righe_report, 'matrice': matrice}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manager', default='crowss')
    ap.add_argument('--gw', required=True)
    ap.add_argument('--test', type=int, choices=(1, 2, 3), required=True,
                     help='1=full pool (selezione), 2=pool ristretto+metrica k '
                          '(allocazione), 3=decisione entra/salta a formazione fissa')
    ap.add_argument('--dump', default=None, help='file di dump leggibile')
    args = ap.parse_args()

    print('=' * 72)
    print(f'BACKTEST GW {args.gw} -- manager {args.manager}  -- TEST {args.test}')
    print('=' * 72)

    righe, arene, reale_per_arena, d_start, d_end, conta, lega_di = setup_comune(args)

    fn = {1: esegui_test1, 2: esegui_test2, 3: esegui_test3}[args.test]
    esito = fn(args, righe, arene, reale_per_arena, d_start, d_end, conta, lega_di)

    print()
    print(f"punteggi grezzi letti dalla CACHE : {conta['cache']}")
    print(f"punteggi RICOSTRUITI per divisione: {conta['fallback']}"
          "   <- questi hanno un errore dell'1-3%")
    return 0 if esito is not None else 1


if __name__ == '__main__':
    sys.exit(main())
