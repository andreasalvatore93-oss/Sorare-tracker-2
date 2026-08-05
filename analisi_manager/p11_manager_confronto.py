"""P11 ampliato: mazzo ricostruito di un manager REALE diverso dall'utente
(forever-young -- unico con dati sufficienti, vedi selezione sotto), stesse
3 policy (A produzione, B DEF k=0.2, C DEF+FWD), stesso impianto
(bfg.build_one_lineup_with_growth, walk-forward, mazzo fisso, carte non
clonate). SOLO punti realizzati/composizione/sovrapposizione: NIENTE
rank/premio (manca la distribuzione della leaderboard per gli altri
manager -- vedi limiti in fondo al report). Nessuna modifica a file di
produzione, nessun commit.
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
    d = json.load(open(os.path.join(ROOT, 'dati_globali', nome_file), encoding='utf-8'))
    manager = d['manager']
    giornate = {}
    for gw, righe in d['giornate'].items():
        data = FXDATE.get(gw)
        if data is None:
            continue
        giornate[gw] = {'data': data, 'righe': righe}
    return manager, giornate


def costruisci_pool_gw(giornate, gw_target):
    """Union delle carte schierate (qualunque competizione) nella finestra
    +/-30gg attorno alla data della GW target. copie = # 'carta' id distinti
    visti per slug nella finestra."""
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
    """Punteggio reale per uno slug in una data GW quando non e' stato
    deployato quella GW dal manager: cerca nel game log locale (stessa
    cache condivisa, nessuna nuova query)."""
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
    modulo = ctx['modulo']
    try:
        atteso = modulo.compute_score_atteso_gk(ctx['s']['scores'], ctx['s']['is_home'],
                                                 ctx['s']['residual']) if ruolo_full == 'Goalkeeper' else None
    except Exception:
        atteso = None
    # per semplicita' e coerenza con la produzione, riusa prev.calcola con i
    # default (nessun aggiustamento): e' la stessa chiamata che score_atteso
    # farebbe, gia' importata da questo stesso modulo di misura.
    try:
        base = prev.calcola(ctx)
    except Exception:
        base = None
    _atteso_cache[key] = (base, ctx)
    return base, ctx


def costruisci_row(slug, ruolo_full, ctx, k_def, k_fwd, reale):
    cod = RUOLO_COD[ruolo_full]
    atteso_raw, _ = atteso_raw_di(slug, ruolo_full, None) if False else (None, None)
    return cod


POLICY_D = {'DEF': ('mult', 0.2), 'MID': ('mult', 0.2), 'FWD': ('mult', 0.1), 'GK': ('add', 3.0)}


def prepara_gw_base(giornate, gw_target):
    """Calcola UNA volta per GW gli ingredienti indipendenti dalla policy
    (base=atteso_raw di produzione, ctx per delta_favorito_odds, reale,
    lega, copie, l10): evita di rifare 5 volte le chiamate costose a
    prev.contesto per le 5 policy."""
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
                          'base': base, 'ctx': ctx, 'reale': reale, 'lega': lega,
                          'copie': len(info['ids']), 'l10': l10_reale})
    return base_pool, n_scartate_atteso, n_scartate_reale


def applica_policy(base_pool, policy, centra=False):
    """policy: dict ruolo -> ('mult'|'add', k). centra=True (E): ricentra
    l'atteso_cal aggiustato sulla media per-ruolo di QUESTA GW, cosi' la
    media del ruolo resta uguale ad A e cambia solo l'ordinamento interno."""
    tmp = []
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
        a = bfg.calibra(c['base'], cod)
        tmp.append((c, adj, a))
    if centra:
        somma_adj = collections.defaultdict(float); somma_a = collections.defaultdict(float)
        n_ruolo = collections.defaultdict(int)
        for c, adj, a in tmp:
            somma_adj[c['codice']] += adj; somma_a[c['codice']] += a; n_ruolo[c['codice']] += 1
        shift = {cod: (somma_a[cod] - somma_adj[cod]) / n_ruolo[cod] for cod in n_ruolo}
    else:
        shift = collections.defaultdict(float)
    pool = []
    for c, adj, _a in tmp:
        pool.append({'slug': c['slug'], 'ruolo_full': c['ruolo_full'], 'codice': c['codice'],
                     'atteso_cal': adj + shift[c['codice']], 'reale': c['reale'], 'lega': c['lega'],
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


def esegui(manager_file, manager_label):
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

        pool_a = applica_policy(base_pool, None)
        pool_b = applica_policy(base_pool, {'DEF': ('mult', 0.2)})
        pool_c = applica_policy(base_pool, {'DEF': ('mult', 0.2), 'FWD': ('mult', 0.1)})
        pool_d = applica_policy(base_pool, POLICY_D, centra=False)
        pool_e = applica_policy(base_pool, POLICY_D, centra=True)

        fa = gioca(pool_a, tipo_bfg_list)
        fb = gioca(pool_b, tipo_bfg_list)
        fc = gioca(pool_c, tipo_bfg_list)
        fd = gioca(pool_d, tipo_bfg_list)
        fe = gioca(pool_e, tipo_bfg_list)
        for lab, la, lb, lc, ld, le in zip(tipo_label_list, fa, fb, fc, fd, fe):
            if any(x is None for x in (la, lb, lc, ld, le)):
                continue
            ca, cb, cc, cd, ce = (capitano_atteso(la), capitano_atteso(lb), capitano_atteso(lc),
                                   capitano_atteso(ld), capitano_atteso(le))
            pa, pb_, pc, pd, pe = (realizzato(la, ca), realizzato(lb, cb), realizzato(lc, cc),
                                    realizzato(ld, cd), realizzato(le, ce))
            sa_ = set(r['slug'] for _x, r, _t in la)
            sb_ = set(r['slug'] for _x, r, _t in lb)
            sc_ = set(r['slug'] for _x, r, _t in lc)
            sd_ = set(r['slug'] for _x, r, _t in ld)
            se_ = set(r['slug'] for _x, r, _t in le)
            comp_a = collections.Counter(r['role_key'] for _x, r, _t in la)
            comp_b = collections.Counter(r['role_key'] for _x, r, _t in lb)
            comp_c = collections.Counter(r['role_key'] for _x, r, _t in lc)
            comp_d = collections.Counter(r['role_key'] for _x, r, _t in ld)
            comp_e = collections.Counter(r['role_key'] for _x, r, _t in le)
            righe_out.append({'gw': gw_target, 'tipo': lab,
                               'A_punti': pa, 'A_comp': dict(comp_a),
                               'B_punti': pb_, 'B_comp': dict(comp_b),
                               'C_punti': pc, 'C_comp': dict(comp_c),
                               'D_punti': pd, 'D_comp': dict(comp_d),
                               'E_punti': pe, 'E_comp': dict(comp_e),
                               'overlap_AB': len(sa_ & sb_), 'overlap_AC': len(sa_ & sc_),
                               'overlap_AD': len(sa_ & sd_), 'overlap_AE': len(sa_ & se_)})
    return righe_out, scartate_atteso_tot, scartate_reale_tot, pool_sizes


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def boot_delta_punti(righe, ka, kb, B=2000, seed=11):
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[r['gw']].append(r)
    unita = list(gruppi.values())
    n = len(unita)
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        num = 0.0; den = 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r[kb] - r[ka]; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if len(vals) < 30:
        return None, None
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def comp_media(righe, chiave):
    tot = collections.Counter()
    for r in righe:
        for ruolo, n in r[chiave].items():
            tot[ruolo] += n
    return {ruolo: tot[ruolo] / len(righe) for ruolo in ('GK', 'DEF', 'MID', 'FWD')}


def report(righe, etichetta):
    p('\n' + '=' * 88)
    p(etichetta)
    p('=' * 88)
    if not righe:
        p('  nessuna riga')
        return
    p('  arene: %d   giornate: %d' % (len(righe), len(set(r['gw'] for r in righe))))
    POLICIE = (('A produzione', 'A'), ('B DEF k0.2', 'B'), ('C DEF+FWD', 'C'),
               ('D ogni ruolo', 'D'), ('E D centrata', 'E'))
    p('\n  COMPOSIZIONE MEDIA (su 5):  %-6s %6s %6s %6s' % ('GK', 'DEF', 'MID', 'FWD'))
    for nome, sigla in POLICIE:
        cm = comp_media(righe, sigla + '_comp')
        p('    %-14s %6.2f %6.2f %6.2f %6.2f' % (nome, cm['GK'], cm['DEF'], cm['MID'], cm['FWD']))
    p('\n  PUNTI MEDI:')
    for nome, sigla in POLICIE:
        p('    %-14s %8.2f' % (nome, media(r[sigla + '_punti'] for r in righe)))
    p('\n  DELTA punti vs A (bootstrap appaiato su GIORNATE, IC95, B=2000):')
    for nome, sigla in POLICIE[1:]:
        kp = sigla + '_punti'
        d = media(r[kp] - r['A_punti'] for r in righe)
        lo, hi = boot_delta_punti(righe, 'A_punti', kp)
        p('    %-14s %+.2f  IC95 [%s, %s]' % (
            nome, d, ('%+.2f' % lo) if lo is not None else 'n/a', ('%+.2f' % hi) if hi is not None else 'n/a'))
    p('\n  SOVRAPPOSIZIONE (carte/5 in comune con A):')
    for nome, kov in (('B vs A', 'overlap_AB'), ('C vs A', 'overlap_AC'),
                      ('D vs A', 'overlap_AD'), ('E vs A', 'overlap_AE')):
        dist = collections.Counter(r[kov] for r in righe)
        p('    %-8s media %.2f/5   %s' % (nome, media(r[kov] for r in righe),
          ', '.join('%d/5=%d' % (k, dist[k]) for k in sorted(dist))))
    p('\n  CONTROLLO DI SANITA E (composizione deve restare uguale ad A entro il rumore):')
    cm_a = comp_media(righe, 'A_comp'); cm_e = comp_media(righe, 'E_comp')
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        diff = cm_e[ruolo] - cm_a[ruolo]
        p('    %-4s A=%.2f  E=%.2f  diff=%+.3f%s' % (
            ruolo, cm_a[ruolo], cm_e[ruolo], diff,
            '  <- si sposta' if abs(diff) > 0.05 else ''))


def main():
    p('P11 AMPLIATO -- manager forever-young, ricostruzione mazzo +/-30gg')
    p('SOLO punti/composizione/sovrapposizione: NIENTE rank/premio (vedi limiti)')

    righe, sc_att, sc_re, pool_sizes = esegui('manager_forever-young.json', 'forever-young')
    p('\ngiornate con almeno 1 arena valida: %d' % len(set(r['gw'] for r in righe)))
    p('dimensione pool ricostruito per GW: media=%.1f  min=%d  max=%d  (su %d GW con >=5 carte)'
      % (media(pool_sizes), min(pool_sizes) if pool_sizes else 0, max(pool_sizes) if pool_sizes else 0, len(pool_sizes)))
    p('carte scartate per atteso non calcolabile: %d, per reale non trovato: %d' % (sc_att, sc_re))
    p('arene totali valutate: %d' % len(righe))

    report(righe, 'TOTALE (tutte le arene limited: Beginner+220+260+uncapped)')
    for tipo in ('Beginner', 'cap 220', 'cap 260', 'uncapped'):
        sotto = [r for r in righe if r['tipo'] == tipo]
        report(sotto, 'SOLO %s (n=%d)' % (tipo, len(sotto)))

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_manager_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    with open(os.path.join(ROOT, 'analisi_manager', 'p11_manager_righe.json'), 'w', encoding='utf-8') as fh:
        json.dump(righe, fh, ensure_ascii=False)
    p('\nsalvato in analisi_manager/p11_manager_out.txt')


if __name__ == '__main__':
    main()
