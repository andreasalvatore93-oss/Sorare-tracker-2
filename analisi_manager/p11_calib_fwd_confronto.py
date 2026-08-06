"""P11 -- confronto knapsack A (calibrazione FWD di produzione) vs R (calib-
razione FWD refit OLS) su TUTTI i mazzi in dati_globali/manager_*.json.

Le due policy sono IDENTICHE (stesso impianto walk-forward, mazzo ricostruito
+/-30gg, carte non clonate, stessa regola capitano, nessun filtro extra) tranne
la calibrazione del ruolo FWD:
  A = produzione:  CALIB_PER_RUOLO['FWD'] = (8.40, 0.789)
  R = refit OLS:   CALIB_PER_RUOLO['FWD'] = (-11.06, 1.172)
GK/DEF/MID invariati in entrambe. Lo scambio avviene mutando in-place il dict
globale bfg.CALIB_PER_RUOLO fra le due chiamate a gioca() sullo STESSO
base_pool: bfg.calibra() lo rilegge ad ogni chiamata, quindi non serve
re-importare il modulo.

Nessuna modifica a file di produzione, nessun commit.
"""
import os, sys, io, json, random, collections, datetime
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

FWD_PROD = (8.40, 0.789)
FWD_REFIT = (-11.06, 1.172)

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
    for (slug, ruolo_full), info in carte_per_slug.items():
        cod = RUOLO_COD.get(ruolo_full)
        if cod is None:
            continue
        reale = reale_target.get((slug, ruolo_full))
        if reale is None:
            reale = reale_da_cache(slug, gw_data)
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
                          'base': base, 'reale': reale, 'lega': lega,
                          'copie': len(info['ids']), 'l10': l10_reale})
    return base_pool, n_scartate_atteso, n_scartate_reale


def applica_calib(base_pool):
    """Calibra col contenuto ATTUALE di bfg.CALIB_PER_RUOLO (letto ad ogni
    chiamata di bfg.calibra): nessun aggiustamento diverso dalla calibrazione,
    stessa 'base' (atteso grezzo) per A e R."""
    pool = []
    for c in base_pool:
        adj = bfg.calibra(c['base'], c['codice'])
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


def esegui(manager_file):
    manager, giornate = carica_manager(manager_file)
    righe_out = []
    scartate_atteso_tot = scartate_reale_tot = 0
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

        base_pool, sa, sr = prepara_gw_base(giornate, gw_target)
        scartate_atteso_tot += sa; scartate_reale_tot += sr
        pool_sizes.append(len(base_pool))
        if len(base_pool) < 5:
            continue

        bfg.CALIB_PER_RUOLO['FWD'] = FWD_PROD
        pool_a = applica_calib(base_pool)
        fa = gioca(pool_a, tipo_bfg_list)

        bfg.CALIB_PER_RUOLO['FWD'] = FWD_REFIT
        pool_r = applica_calib(base_pool)
        fr = gioca(pool_r, tipo_bfg_list)

        bfg.CALIB_PER_RUOLO['FWD'] = FWD_PROD  # riporta a prod appena finito

        for lab, la, lr in zip(tipo_label_list, fa, fr):
            if la is None or lr is None:
                continue
            ca, cr = capitano_atteso(la), capitano_atteso(lr)
            pa, pr = realizzato(la, ca), realizzato(lr, cr)
            sa_ = set(r['slug'] for _x, r, _t in la)
            sr_ = set(r['slug'] for _x, r, _t in lr)
            comp_a = collections.Counter(r['role_key'] for _x, r, _t in la)
            comp_r = collections.Counter(r['role_key'] for _x, r, _t in lr)
            righe_out.append({'gw': gw_target, 'tipo': lab,
                               'A_punti': pa, 'A_comp': dict(comp_a),
                               'R_punti': pr, 'R_comp': dict(comp_r),
                               'overlap': len(sa_ & sr_)})
    return manager, righe_out, scartate_atteso_tot, scartate_reale_tot, pool_sizes


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def comp_media(righe, chiave):
    tot = collections.Counter()
    for r in righe:
        for ruolo, n in r[chiave].items():
            tot[ruolo] += n
    return {ruolo: tot[ruolo] / len(righe) for ruolo in ('GK', 'DEF', 'MID', 'FWD')} if righe else \
           {ruolo: float('nan') for ruolo in ('GK', 'DEF', 'MID', 'FWD')}


def boot_delta_cluster(righe, gw_key='gw', B=2000, seed=11):
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
                num += r['R_punti'] - r['A_punti']; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if len(vals) < 30:
        return None, None
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def sign_test_p(n_pos, n_neg):
    n = n_pos + n_neg
    if n == 0:
        return float('nan')
    k = min(n_pos, n_neg)
    from math import comb
    cum = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * cum)


def test_aa_switch():
    """Test A/A sull'interruttore, prima di tutto: env FWD assurdo deve
    muovere la composizione; default deve riprodurre A esatto."""
    p('=== TEST A/A SULL\'INTERRUTTORE (prima di tutto) ===')
    manager, giornate = carica_manager('manager_forever-young.json')
    gw_target = sorted(giornate.items(), key=lambda kv: kv[1]['data'])[10][0]
    base_pool, _, _ = prepara_gw_base(giornate, gw_target)
    info = giornate[gw_target]
    tipo_bfg_list, tipo_label_list = [], []
    for r in info['righe']:
        if r.get('tipo_arena') not in TIPI_VALIDI:
            continue
        tb, lab = tipo_bfg_di(r)
        if tb:
            tipo_bfg_list.append(tb); tipo_label_list.append(lab)
    if not tipo_bfg_list or len(base_pool) < 5:
        p('  pool insufficiente per il test A/A su questa GW, salto (non blocca il resto)')
        return

    bfg.CALIB_PER_RUOLO['FWD'] = FWD_PROD
    pool1 = applica_calib(base_pool)
    f1 = gioca(pool1, tipo_bfg_list)
    comp1 = [collections.Counter(r['role_key'] for _x, r, _t in f) if f else None for f in f1]

    bfg.CALIB_PER_RUOLO['FWD'] = (1e6, 1.0)  # assurdo: FWD deve dominare ogni scelta
    pool2 = applica_calib(base_pool)
    f2 = gioca(pool2, tipo_bfg_list)
    comp2 = [collections.Counter(r['role_key'] for _x, r, _t in f) if f else None for f in f2]

    bfg.CALIB_PER_RUOLO['FWD'] = FWD_PROD  # torna a default
    pool3 = applica_calib(base_pool)
    f3 = gioca(pool3, tipo_bfg_list)
    comp3 = [collections.Counter(r['role_key'] for _x, r, _t in f) if f else None for f in f3]

    si_muove = any((c1 or {}).get('FWD', 0) != (c2 or {}).get('FWD', 0) for c1, c2 in zip(comp1, comp2))
    riproduce = comp1 == comp3
    p('  FWD assurdo (a=1e6) muove la composizione vs default: %s' % ('SI' if si_muove else 'NO -- BLOCCANTE'))
    p('  default dopo il giro riproduce esattamente il primo giro: %s' % ('SI' if riproduce else 'NO -- BLOCCANTE'))
    for lab, c1, c2, c3 in zip(tipo_label_list, comp1, comp2, comp3):
        p('    %-10s default=%s  assurdo=%s  ridefault=%s' % (lab, dict(c1 or {}), dict(c2 or {}), dict(c3 or {})))
    if not (si_muove and riproduce):
        raise SystemExit('TEST A/A FALLITO: interruttore non funziona come atteso, mi fermo prima di misurare.')
    p('  interruttore verificato: procedo con la misura vera.\n')


def main():
    test_aa_switch()

    p('BRIEF -- knapsack A (calib FWD produzione 8.40/0.789) vs R (calib FWD refit -11.06/1.172)')
    p('su TUTTI i mazzi dati_globali/manager_*.json. GK/DEF/MID invariati. Stesso impianto P11.')

    tutti = sorted(f for f in os.listdir(SCRATCH) if f.startswith('manager_') and f.endswith('.json'))
    tutti = [f for f in tutti if f not in ESCLUSI]
    p('\nmazzi esclusi: %s' % sorted(ESCLUSI))
    p('mazzi da processare: %d' % len(tutti))

    risultati = []
    for i, fname in enumerate(tutti):
        p('\n[%d/%d] %s ...' % (i + 1, len(tutti), fname))
        try:
            manager, righe, sa, sr, pool_sizes = esegui(fname)
        except Exception as ex:
            p('  ERRORE: %r -- saltato' % ex)
            continue
        n_arene = len(righe)
        n_gw = len(set(r['gw'] for r in righe))
        if n_arene == 0:
            p('  0 arene valide -- saltato')
            continue
        overlap_medio = media(r['overlap'] for r in righe)
        d_medio = media(r['R_punti'] - r['A_punti'] for r in righe)
        lo, hi = boot_delta_cluster(righe)
        pool_medio = media(pool_sizes) if pool_sizes else float('nan')
        comp_a = comp_media(righe, 'A_comp')
        comp_r = comp_media(righe, 'R_comp')
        muto = overlap_medio >= 4.5
        p('  arene=%d giornate=%d pool_medio=%.1f overlap_medio=%.2f/5%s'
          % (n_arene, n_gw, pool_medio, overlap_medio, '  <- MUTO (escluso)' if muto else ''))
        p('  comp A: GK=%.2f DEF=%.2f MID=%.2f FWD=%.2f | comp R: GK=%.2f DEF=%.2f MID=%.2f FWD=%.2f'
          % (comp_a['GK'], comp_a['DEF'], comp_a['MID'], comp_a['FWD'],
             comp_r['GK'], comp_r['DEF'], comp_r['MID'], comp_r['FWD']))
        p('  delta R-A punti = %+.2f  IC95 [%s, %s]  (scartate: atteso=%d reale=%d)'
          % (d_medio, ('%+.2f' % lo) if lo is not None else 'n/a',
             ('%+.2f' % hi) if hi is not None else 'n/a', sa, sr))
        risultati.append({'file': fname, 'manager': manager, 'righe': righe,
                           'n_arene': n_arene, 'n_gw': n_gw, 'pool_medio': pool_medio,
                           'overlap_medio': overlap_medio, 'd_medio': d_medio,
                           'lo': lo, 'hi': hi, 'muto': muto,
                           'comp_a': comp_a, 'comp_r': comp_r})

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_calib_fwd_righe.json'), 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False)

    p('\n' + '=' * 110)
    p('TABELLA PER MAZZO')
    p('=' * 110)
    p('%-45s %6s %5s %8s %8s %8s %8s %20s' % ('manager', 'arene', 'gg', 'FWD_A', 'FWD_R', 'dFWD', 'delta_pt', 'IC95'))
    for r in sorted(risultati, key=lambda x: -x['n_arene']):
        ic = ('[%+.2f,%+.2f]' % (r['lo'], r['hi'])) if r['lo'] is not None else 'n/a'
        dfwd = r['comp_r']['FWD'] - r['comp_a']['FWD']
        p('%-45s %6d %5d %8.2f %8.2f %+8.2f %+8.2f %20s%s' % (
            r['manager'][:45], r['n_arene'], r['n_gw'], r['comp_a']['FWD'], r['comp_r']['FWD'],
            dfwd, r['d_medio'], ic, '  MUTO' if r['muto'] else ''))

    utili = [r for r in risultati if not r['muto']]
    p('\nmazzi totali processati: %d | muti (overlap>=4.5/5, esclusi dai conteggi): %d | utili: %d'
      % (len(risultati), len(risultati) - len(utili), len(utili)))

    # ---------------------------------------------------- composizione: segno stabile
    p('\n' + '-' * 80)
    p('LETTURA 1 -- SEGNO DELLA COMPOSIZIONE FWD (R - A) su tutti i mazzi utili')
    p('-' * 80)
    dfwd_list = [r['comp_r']['FWD'] - r['comp_a']['FWD'] for r in utili]
    pos = [d for d in dfwd_list if d > 1e-9]
    neg = [d for d in dfwd_list if d < -1e-9]
    zero = [d for d in dfwd_list if abs(d) <= 1e-9]
    pv = sign_test_p(len(pos), len(neg))
    p('  n mazzi = %d   FWD sale = %d   FWD scende = %d   invariato = %d' % (len(dfwd_list), len(pos), len(neg), len(zero)))
    p('  test del segno (bilaterale, p=0.5 sotto H0): p-value = %.4f' % pv)
    p('  media dFWD (R-A) per mazzo = %+.3f' % media(dfwd_list))

    # composizione aggregata pesata per arena
    righe_tot = [r for mgr in utili for r in mgr['righe']]
    comp_a_tot = comp_media(righe_tot, 'A_comp')
    comp_r_tot = comp_media(righe_tot, 'R_comp')
    p('\n' + '-' * 80)
    p('LETTURA 2 -- COMPOSIZIONE MEDIA PESATA PER ARENA (tutte le arene utili, n=%d)' % len(righe_tot))
    p('-' * 80)
    p('  %-6s %8s %8s %8s' % ('ruolo', 'A', 'R', 'delta'))
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        p('  %-6s %8.3f %8.3f %+8.3f' % (ruolo, comp_a_tot[ruolo], comp_r_tot[ruolo], comp_r_tot[ruolo] - comp_a_tot[ruolo]))

    # delta punti pesato
    p('\n' + '-' * 80)
    p('LETTURA 3 -- DELTA PUNTI R-A PESATO PER ARENA (caveat: rumore su poche arene)')
    p('-' * 80)
    d_pesato = media(r['R_punti'] - r['A_punti'] for r in righe_tot)
    gruppi = collections.defaultdict(list)
    for mgr in utili:
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
                num += r['R_punti'] - r['A_punti']; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    lo = vals[int(.025 * len(vals))] if len(vals) >= 30 else None
    hi = vals[int(.975 * len(vals))] if len(vals) >= 30 else None
    p('  arene totali = %d   mazzi = %d   cluster (manager,gw) = %d' % (len(righe_tot), len(utili), n))
    p('  delta pesato per arena = %+.3f  IC95 [%s, %s]' % (
        d_pesato, ('%+.3f' % lo) if lo is not None else 'n/a', ('%+.3f' % hi) if hi is not None else 'n/a'))
    if lo is not None and hi is not None and lo < 0 < hi:
        p('  ATTENZIONE: IC95 comprende lo zero -- NON e\' una scoperta sui punti, solo assenza di prova col')
        p('  campione attuale (trappola test multipli, come da brief). Il segnale primario resta la composizione.')

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_calib_fwd_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    p('\nsalvato in analisi_manager/p11_calib_fwd_out.txt e p11_calib_fwd_righe.json')


if __name__ == '__main__':
    main()
