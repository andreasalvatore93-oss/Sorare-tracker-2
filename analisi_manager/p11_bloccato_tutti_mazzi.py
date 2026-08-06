"""P11 -- Brief 1 (composizione bloccata) ripetuto su TUTTI i mazzi in
dati_globali/manager_*.json, ciascuno separatamente.

  policy A  = score_atteso di produzione
  policy B' = favorito_odds moltiplicativo k=0.2 sui soli DEF, con la
              composizione per ruolo FORZATA identica a quella scelta da A
              nella stessa arena: si prende la formazione A, si contano i
              ruoli usati (es. GK1/DEF2/MID1/FWD1), e si ricostruisce B' con
              una shape su misura (role_slots = esattamente quei ruoli,
              extra_roles=[] -- nessuno slot in competizione fra ruoli).
              Isola cosi' la selezione DENTRO il ruolo dalla competizione fra
              ruoli, che nel Brief 1 originale (crowss/forever-young, seconda
              meta' della notte 05-06/08) e' risultata la causa per cui il
              guadagno per-ruolo non arrivava ai punti.

Riusa l'impianto di p11_manager_confronto.py (mazzo ricostruito dall'unione
delle carte schierate in finestra +/-30gg attorno alla GW target, walk-
forward, carte non clonate, stessa regola capitano su A e B'). Nessuna
modifica a file di produzione, nessun commit.
"""
import os, sys, io, json, math, random, collections, datetime
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_produzione as BP
import backtest_arene_cache as CACHE
import backtest_arene_previsioni as prev

bfg = BP.bfg
bff = BP.bff

SCRATCH = os.path.join(ROOT, 'dati_globali')
FINESTRA_GG = 30
TIPI_VALIDI = ('arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped')
ESCLUSI = {'manager_crowss.json', 'manager_badamt.json', 'manager_matangel716.json',
           'manager_foreveryoung_predizioni_gw2.json'}

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

cache = CACHE.CacheLocale()
fx = json.load(open(os.path.join(SCRATCH, 'fixture_date_map.json'), encoding='utf-8'))['fx_ascending']
FXDATE = {f['slug']: f['startDate'][:10] for f in fx}


def _dt(iso10):
    return datetime.datetime.strptime(iso10, '%Y-%m-%d')


def tipo_bfg_di(riga):
    ta = riga.get('tipo_arena')
    if ta == 'arena_limited_beginner':
        return 'ARENA_BEGINNER', 'Beginner'
    if ta == 'arena_limited_uncapped':
        return 'ARENA_ALLSTARS_UNCAPPED', 'uncapped'
    if ta == 'arena_limited':
        if 'cap_220' in (riga.get('leaderboard') or ''):
            return 'ARENA_ALLSTARS_220', 'cap 220'
        return 'ARENA_ALLSTARS_260', 'cap 260'
    return None, None


RUOLO_COD = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}


def carica_manager(nome_file):
    d = json.load(open(os.path.join(SCRATCH, nome_file), encoding='utf-8'))
    manager = d['manager']
    giornate = {}
    for gw, righe in d['giornate'].items():
        data = FXDATE.get(gw)
        if data is None:
            continue
        giornate[gw] = {'data': data, 'righe': righe}
    return manager, giornate


def costruisci_pool_gw(giornate, gw_target):
    data_t = _dt(giornate[gw_target]['data'])
    carte_per_slug = collections.defaultdict(lambda: {'ids': set(), 'ruolo': None, 'squadra': None})
    reale_in_target = {}
    for gw, info in giornate.items():
        d = _dt(info['data'])
        if abs((d - data_t).days) > FINESTRA_GG:
            continue
        for riga in info['righe']:
            for c in riga.get('carte') or []:
                key = (c['slug'], c['ruolo'])
                carte_per_slug[key]['ids'].add(c['carta'])
                carte_per_slug[key]['ruolo'] = c['ruolo']
                carte_per_slug[key]['squadra'] = c['squadra']
                if gw == gw_target:
                    reale_in_target[key] = c['punteggio']
    return carte_per_slug, reale_in_target


def reale_da_cache(slug, gw_data):
    d_t = _dt(gw_data)
    for nodo in cache.gamelog(slug):
        if nodo.get('scoreStatus') not in ('FINAL', 'REVIEWING'):
            continue
        g = (nodo.get('anyGame') or {})
        iso = g.get('date')
        if not iso:
            continue
        try:
            d_g = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            continue
        if abs((d_g - d_t).days) <= 3:
            return nodo.get('score')
    return None


_atteso_cache = {}

def atteso_raw_di(slug, ruolo_full, gw_data):
    key = (slug, ruolo_full, gw_data)
    if key in _atteso_cache:
        return _atteso_cache[key]
    fd = _dt(gw_data)
    try:
        ctx = prev.contesto(cache, slug, ruolo_full, fd)
    except Exception:
        ctx = None
    if ctx is None:
        _atteso_cache[key] = (None, None)
        return None, None
    try:
        base = prev.calcola(ctx)
    except Exception:
        base = None
    _atteso_cache[key] = (base, ctx)
    return base, ctx


def prepara_gw_base(giornate, gw_target):
    carte_per_slug, reale_target = costruisci_pool_gw(giornate, gw_target)
    gw_data = giornate[gw_target]['data']
    base_pool = []
    n_scartate_atteso = 0
    n_scartate_reale = 0
    n_reale_fallback_raw = 0
    for (slug, ruolo_full), info in carte_per_slug.items():
        cod = RUOLO_COD.get(ruolo_full)
        if cod is None:
            continue
        # Fix D6/G6 (06-07/08): il punteggio 'reale' va letto SEMPRE dalla
        # cache game-log grezza per prima cosa, a prescindere dal tipo di
        # riga (arena o no). Il campo c['punteggio'] del file manager ha
        # xp+capitano dentro per le righe NON-arena (regola D4) e gonfia il
        # 77% delle carte su crowss se usato come fonte primaria. Il valore
        # raw del file manager resta SOLO come ripiego, contato.
        reale = reale_da_cache(slug, gw_data)
        if reale is None:
            reale = reale_target.get((slug, ruolo_full))
            if reale is not None:
                n_reale_fallback_raw += 1
        if reale is None:
            n_scartate_reale += 1
            continue
        base, ctx = atteso_raw_di(slug, ruolo_full, gw_data)
        if base is None:
            n_scartate_atteso += 1
            continue
        target = prev.partita_target(cache, slug, _dt(gw_data))
        comp = (target['anyGame'].get('competition') or {}).get('slug') if target else None
        lega = BP.LEAGUE_DIR.get(comp, 'senza_lega')
        scores = ctx['s']['scores'][-10:] if ctx and ctx.get('s', {}).get('scores') else []
        l10_reale = (sum(scores) / len(scores)) if scores else 1e9
        base_pool.append({'slug': slug, 'ruolo_full': ruolo_full, 'codice': cod,
                          'base': base, 'ctx': ctx, 'reale': reale, 'lega': lega,
                          'copie': len(info['ids']), 'l10': l10_reale})
    return base_pool, n_scartate_atteso, n_scartate_reale, n_reale_fallback_raw


def applica_policy(base_pool, policy):
    pool = []
    for c in base_pool:
        cod = c['codice']
        spec = policy.get(cod) if policy else None
        atteso_raw = c['base']
        if spec:
            kind, k = spec
            if k:
                d = prev.delta_favorito_odds(c['ctx'])
                if d is not None:
                    atteso_raw = c['base'] * (1.0 + k * d) if kind == 'mult' else c['base'] + k * d
        adj = bfg.calibra(atteso_raw, cod)
        pool.append({'slug': c['slug'], 'ruolo_full': c['ruolo_full'], 'codice': c['codice'],
                     'atteso_cal': adj, 'reale': c['reale'], 'lega': c['lega'],
                     'copie': c['copie'], 'l10': c['l10']})
    return pool


def costruisci_struct(pool):
    leghe = sorted(set(c['lega'] for c in pool) | {'senza_lega'})
    role_data = {lg: {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in leghe}
    counts = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}
    for c in pool:
        row = {'slug': c['slug'], 'atteso': c['atteso_cal'], 'low': 0, 'high': 0,
               'team_slug': None, 'opponent_team_slug': None, 'ordinamento': None,
               'kickoff': None, 'opp_factor': None, 'league': c['lega'],
               'role_key': c['codice'], 'reale': c['reale'], 'atteso_cal': c['atteso_cal']}
        role_data[c['lega']][c['codice']].append(row)
        counts[c['codice']][c['slug']] = {'in_season': c['copie'], 'classic': 0, 'l10': c['l10']}
    for lg in role_data:
        for cod in role_data[lg]:
            role_data[lg][cod].sort(key=lambda r: r['atteso'], reverse=True)
    pools = {lg: {r: bfg._NoFilterPool(r, lg, role_data[lg][r]) for r in ('GK', 'DEF', 'MID', 'FWD')}
             for lg in leghe}
    card_pool = bff.CardPool(counts)
    return role_data, pools, card_pool, leghe


def capitano_atteso(formazione):
    righe = [r for _s, r, _t in formazione]
    fuori = [r for r in righe if r['role_key'] != 'GK']
    gk = [r for r in righe if r['role_key'] == 'GK']
    bo = max(fuori, key=lambda r: r['atteso_cal']) if fuori else None
    bg = max(gk, key=lambda r: r['atteso_cal']) if gk else None
    marg = getattr(bff, 'GK_CAPTAIN_MARGIN', 0)
    if bg and (not bo or bg['atteso_cal'] >= bo['atteso_cal'] + marg):
        return bg
    return bo or bg


def realizzato(formazione, cap_row):
    return sum(r['reale'] for _s, r, _t in formazione) + 0.2 * cap_row['reale']


def gioca(pool, tipo_bfg_list):
    """Policy A: shape standard di produzione (con slot extra in competizione)."""
    role_data, pools, card_pool, leghe = costruisci_struct(pool)
    orig = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe)
    fuori = []
    try:
        for tipo_bfg in tipo_bfg_list:
            shape = bfg.FORMATION_SHAPES.get(tipo_bfg)
            if shape is None:
                fuori.append(None)
                continue
            pool_league = bfg.POOL_LEAGUE_BY_TYPE.get(tipo_bfg, 'mixed')
            l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
            stato = bfg._istantanea_pool(card_pool)
            try:
                formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                    shape, pool_league, role_data, pools, card_pool, l10_cap,
                    apply_stack_guard=False, variance_mode=True,
                    apply_positive_synergy=False, strict_gk_anti_synergy=False)
            except Exception:
                formazione, errore = None, True
            if errore or not formazione:
                bfg._ripristina_pool(card_pool, stato)
                fuori.append(None)
                continue
            fuori.append(formazione)
    finally:
        bfg.LEAGUES = orig
    return fuori


def gioca_bloccato(pool, tipo_bfg_list, formazioni_a):
    """Policy B': stessa shape di produzione (role_slots = 4 base fissi GK/
    DEF/MID/FWD), ma lo slot EXTRA e' forzato sul ruolo che A ha scelto in
    quell'arena (extra_roles ridotto a un solo ruolo candidato, invece dei 3
    in competizione): la composizione finale per ruolo e' cosi' identica ad
    A, cambia solo la selezione dentro ciascun ruolo."""
    role_data, pools, card_pool, leghe = costruisci_struct(pool)
    orig = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe)
    fuori = []
    try:
        for tipo_bfg, la in zip(tipo_bfg_list, formazioni_a):
            if la is None:
                fuori.append(None)
                continue
            orig_shape = bfg.FORMATION_SHAPES.get(tipo_bfg)
            if orig_shape is None:
                fuori.append(None)
                continue
            comp = collections.Counter(r['role_key'] for _s, r, _t in la)
            base = collections.Counter(orig_shape['role_slots'])
            extra_ruolo = None
            for role, n in comp.items():
                if n > base.get(role, 0):
                    extra_ruolo = role
                    break
            if extra_ruolo is None:
                fuori.append(None)
                continue
            shape = {'role_slots': list(orig_shape['role_slots']), 'extra_roles': [extra_ruolo],
                     'max_classic': orig_shape['max_classic']}
            pool_league = bfg.POOL_LEAGUE_BY_TYPE.get(tipo_bfg, 'mixed')
            l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
            stato = bfg._istantanea_pool(card_pool)
            try:
                formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                    shape, pool_league, role_data, pools, card_pool, l10_cap,
                    apply_stack_guard=False, variance_mode=True,
                    apply_positive_synergy=False, strict_gk_anti_synergy=False)
            except Exception:
                formazione, errore = None, True
            if errore or not formazione:
                bfg._ripristina_pool(card_pool, stato)
                fuori.append(None)
                continue
            fuori.append(formazione)
    finally:
        bfg.LEAGUES = orig
    return fuori


def esegui(manager_file):
    manager, giornate = carica_manager(manager_file)
    righe_out = []
    scartate_atteso_tot = scartate_reale_tot = fallback_raw_tot = 0
    pool_sizes = []
    for gw_target, info in sorted(giornate.items(), key=lambda kv: kv[1]['data']):
        slots_righe = [r for r in info['righe'] if r.get('tipo_arena') in TIPI_VALIDI]
        if not slots_righe:
            continue
        tipo_bfg_list = []
        tipo_label_list = []
        for r in slots_righe:
            tb, lab = tipo_bfg_di(r)
            if tb:
                tipo_bfg_list.append(tb)
                tipo_label_list.append(lab)
        if not tipo_bfg_list:
            continue

        base_pool, sa, sr, fr = prepara_gw_base(giornate, gw_target)
        scartate_atteso_tot += sa; scartate_reale_tot += sr; fallback_raw_tot += fr
        pool_sizes.append(len(base_pool))
        if len(base_pool) < 5:
            continue

        pool_a = applica_policy(base_pool, None)
        pool_b = applica_policy(base_pool, {'DEF': ('mult', 0.2)})

        fa = gioca(pool_a, tipo_bfg_list)
        fb = gioca_bloccato(pool_b, tipo_bfg_list, fa)
        for lab, la, lb in zip(tipo_label_list, fa, fb):
            if la is None or lb is None:
                continue
            ca, cb = capitano_atteso(la), capitano_atteso(lb)
            pa, pb_ = realizzato(la, ca), realizzato(lb, cb)
            sa_ = set(r['slug'] for _x, r, _t in la)
            sb_ = set(r['slug'] for _x, r, _t in lb)
            comp_a = collections.Counter(r['role_key'] for _x, r, _t in la)
            comp_b = collections.Counter(r['role_key'] for _x, r, _t in lb)
            righe_out.append({'gw': gw_target, 'tipo': lab,
                               'A_punti': pa, 'A_comp': dict(comp_a),
                               'B_punti': pb_, 'B_comp': dict(comp_b),
                               'overlap': len(sa_ & sb_)})
    return manager, righe_out, scartate_atteso_tot, scartate_reale_tot, fallback_raw_tot, pool_sizes


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def boot_delta_cluster(righe, chiave, gw_key='gw', B=2000, seed=11):
    """IC95 del delta medio (B_punti - A_punti), bootstrap appaiato su
    cluster (di norma le giornate)."""
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[r[gw_key]].append(r)
    unita = list(gruppi.values())
    n = len(unita)
    if n == 0:
        return None, None
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        num = 0.0; den = 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r['B_punti'] - r['A_punti']; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if len(vals) < 30:
        return None, None
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def sign_test_p(n_pos, n_neg):
    """p-value bilaterale del test del segno (binomiale p=0.5), no scipy."""
    n = n_pos + n_neg
    if n == 0:
        return float('nan')
    k = min(n_pos, n_neg)
    from math import comb
    cum = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * cum)


def main():
    p('BRIEF 1 (composizione bloccata) su TUTTI i mazzi dati_globali/manager_*.json')
    p('policy A = produzione | policy B\' = DEF mult k=0.2, composizione per ruolo')
    p('forzata identica ad A nella stessa arena (isola la selezione dentro il ruolo)')
    p('mazzo ricostruito +/-30gg, walk-forward, carte non clonate, stessa regola capitano')

    tutti = sorted(f for f in os.listdir(SCRATCH) if f.startswith('manager_') and f.endswith('.json'))
    tutti = [f for f in tutti if f not in ESCLUSI]
    p('\nmazzi esclusi: %s' % sorted(ESCLUSI))
    p('mazzi da processare: %d' % len(tutti))

    risultati = []  # per manager: dict con righe, summary
    for i, fname in enumerate(tutti):
        p('\n[%d/%d] %s ...' % (i + 1, len(tutti), fname))
        try:
            manager, righe, sa, sr, fr, pool_sizes = esegui(fname)
        except Exception as ex:
            p('  ERRORE: %r -- saltato' % ex)
            continue
        n_arene = len(righe)
        n_gw = len(set(r['gw'] for r in righe))
        if n_arene == 0:
            p('  0 arene valide -- saltato')
            continue
        overlap_medio = media(r['overlap'] for r in righe)
        d_medio = media(r['B_punti'] - r['A_punti'] for r in righe)
        lo, hi = boot_delta_cluster(righe, 'gw')
        pool_medio = media(pool_sizes) if pool_sizes else float('nan')
        muto = overlap_medio >= 4.5
        p('  arene=%d giornate=%d pool_medio=%.1f overlap_medio=%.2f/5%s'
          % (n_arene, n_gw, pool_medio, overlap_medio, '  <- MUTO (escluso)' if muto else ''))
        p('  delta B\'-A punti = %+.2f  IC95 [%s, %s]  (scartate: atteso=%d reale=%d, reale-da-raw-manager=%d)'
          % (d_medio, ('%+.2f' % lo) if lo is not None else 'n/a',
             ('%+.2f' % hi) if hi is not None else 'n/a', sa, sr, fr))
        risultati.append({'file': fname, 'manager': manager, 'righe': righe,
                           'n_arene': n_arene, 'n_gw': n_gw, 'pool_medio': pool_medio,
                           'overlap_medio': overlap_medio, 'd_medio': d_medio,
                           'lo': lo, 'hi': hi, 'muto': muto})

    with open(os.path.join(SP := os.path.join(ROOT, 'analisi_manager'), 'p11_bloccato_righe.json'),
              'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False)

    # ---------------------------------------------------------- tabella
    p('\n' + '=' * 100)
    p('TABELLA PER MAZZO (esclusi crowss/badamt/matangel716/artefatto foreveryoung_predizioni)')
    p('=' * 100)
    p('%-45s %6s %5s %7s %6s %8s %20s' % ('manager', 'arene', 'gg', 'pool', 'ovlp', 'delta', 'IC95'))
    for r in sorted(risultati, key=lambda x: -x['n_arene']):
        ic = ('[%+.2f,%+.2f]' % (r['lo'], r['hi'])) if r['lo'] is not None else 'n/a'
        p('%-45s %6d %5d %7.1f %6.2f %+8.2f %20s%s' % (
            r['manager'][:45], r['n_arene'], r['n_gw'], r['pool_medio'], r['overlap_medio'],
            r['d_medio'], ic, '  MUTO' if r['muto'] else ''))

    utili = [r for r in risultati if not r['muto']]
    p('\nmazzi totali processati: %d | muti (overlap>=4.5/5, esclusi dai conteggi): %d | utili: %d'
      % (len(risultati), len(risultati) - len(utili), len(utili)))

    # ---------------------------------------------------- lettura 1: segno pieno
    def blocco_segno(lista, etichetta):
        p('\n' + '-' * 80)
        p(etichetta)
        p('-' * 80)
        pos = [r for r in lista if r['d_medio'] > 0]
        neg = [r for r in lista if r['d_medio'] < 0]
        zero = [r for r in lista if r['d_medio'] == 0]
        p('  n mazzi = %d   positivi = %d   negativi = %d   zero = %d'
          % (len(lista), len(pos), len(neg), len(zero)))
        pv = sign_test_p(len(pos), len(neg))
        p('  test del segno (bilaterale, p=0.5 sotto H0): p-value = %.4f' % pv)

    blocco_segno(utili, 'LETTURA 1 -- conteggio dei segni su TUTTI i mazzi utili')
    blocco_segno([r for r in utili if r['n_gw'] >= 16],
                 'LETTURA 2 -- conteggio dei segni ristretto a mazzi con >=16 giornate')
    p('  (mazzi con <16 giornate in questo giro: %d, sono la parte quasi-rumore)'
      % len([r for r in utili if r['n_gw'] < 16]))

    # ---------------------------------------------------- lettura 3: delta pesato
    def blocco_pesato(lista, etichetta):
        p('\n' + '-' * 80)
        p(etichetta)
        p('-' * 80)
        righe_tot = [r for mgr in lista for r in mgr['righe']]
        if not righe_tot:
            p('  nessuna riga')
            return
        d = media(r['B_punti'] - r['A_punti'] for r in righe_tot)
        # cluster per (manager, gw) per rispettare il mazzo fisso di ognuno
        gruppi = collections.defaultdict(list)
        for mgr in lista:
            for r in mgr['righe']:
                gruppi[(mgr['manager'], r['gw'])].append(r)
        unita = list(gruppi.values())
        n = len(unita)
        rnd = random.Random(11)
        vals = []
        for _ in range(2000):
            num = 0.0; den = 0
            for _ in range(n):
                g = unita[rnd.randrange(n)]
                for r in g:
                    num += r['B_punti'] - r['A_punti']; den += 1
            if den:
                vals.append(num / den)
        vals.sort()
        lo = vals[int(.025 * len(vals))] if len(vals) >= 30 else None
        hi = vals[int(.975 * len(vals))] if len(vals) >= 30 else None
        p('  arene totali = %d   mazzi = %d   cluster (manager,gw) = %d' % (len(righe_tot), len(lista), n))
        p('  delta pesato per arena = %+.3f  IC95 [%s, %s]' % (
            d, ('%+.3f' % lo) if lo is not None else 'n/a', ('%+.3f' % hi) if hi is not None else 'n/a'))

    blocco_pesato(utili, 'LETTURA 3 -- delta pesato per arene (tutti i mazzi utili, forever-young incluso)')
    senza_fy = [r for r in utili if 'forever-young' not in r['file']]
    blocco_pesato(senza_fy, 'LETTURA 3bis -- delta pesato per arene, ESCLUSO forever-young (~3.400 arene, sbilancia)')

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_bloccato_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    p('\nsalvato in analisi_manager/p11_bloccato_out.txt e p11_bloccato_righe.json')


if __name__ == '__main__':
    main()
