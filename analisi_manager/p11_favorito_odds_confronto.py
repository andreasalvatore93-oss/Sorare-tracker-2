"""P11 -- tre policy sul mazzo REALE dell'utente, arene reali non-Beginner/
non-division, walk-forward, mazzo fisso (carte non si clonano, 8.8).
Riusa l'impianto di analisi_manager/p11_confronta.py SENZA modificarlo (import
diretto delle utility di backtest_arene_produzione/economia).

  A = score_atteso di produzione (baseline, atteso_raw invariato)
  B = favorito_odds moltiplicativo k=0.2 sui soli DEF
  C = favorito_odds moltiplicativo k=0.2 sui DEF + k=0.1 sui FWD

L'aggiustamento si applica ad atteso_raw (score_atteso grezzo di produzione,
PRIMA della calibrazione, stesso punto in cui verrebbe applicato in
compute_score_atteso_def/fwd se fosse in produzione) come:
  atteso_raw_adj = atteso_raw * (1 + k * delta_favorito_odds)
delta_favorito_odds ricalcolato per ogni carta con lo stesso meccanismo di
backtest_arene_previsioni.py (scarto dalla media storica del differenziale
p_win_own - p_win_opp), usando la data della PARTITA (gw['fine']), non il
cutoff. Nessuna modifica a file di produzione, nessun commit.
"""
import os, sys, io, json, math, random, collections, datetime
sys.path.insert(0, os.path.join(r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2', 'analisi_manager'))
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
SP = os.path.join(ROOT, 'analisi_manager')
os.chdir(ROOT); sys.path.insert(0, ROOT)

import backtest_arene_produzione as BP
import backtest_arene_economia as E
import backtest_arene_cache as CACHE
import backtest_arene_previsioni as prev

bfg = BP.bfg
bff = BP.bff

TIPI_CAPPED = {'cap 260', 'cap 220'}
TIPI_INCLUSE = {'cap 260', 'cap 220', 'Beginner', 'Uncapped', 'arena uncapped'}
TIPO_LABEL = {'cap 260': 'cap 260', 'cap 220': 'cap 220', 'Beginner': 'Beginner',
              'Uncapped': 'uncapped', 'arena uncapped': 'uncapped'}
FINESTRA_MIN = '2025-11-18'

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

pool_per_gw = json.load(open(os.path.join(SP, 'p11_pool.json'), encoding='utf-8'))
arene_tutte = json.load(open('dati_globali/arene_storico.json', encoding='utf-8'))['arene']
premi_tab = E.tabella_premi(arene_tutte)
arena_per_slug_score = {}
for a in arene_tutte:
    arena_per_slug_score.setdefault((a['slug'], round(a.get('mio_score') or -1, 2)), a)

cache = CACHE.CacheLocale()

# ---------------------------------------------------------------- delta odds
_cache_delta = {}

def delta_per_carta(slug, ruolo, fine_iso):
    """delta_favorito_odds per (slug, ruolo, data partita), ricalcolato con lo
    stesso meccanismo/indice di backtest_arene_previsioni (nessuna modifica a
    quel file: si importa e si usa cosi' com'e')."""
    key = (slug, ruolo, fine_iso)
    if key in _cache_delta:
        return _cache_delta[key]
    try:
        fd = datetime.datetime.fromisoformat(fine_iso.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        _cache_delta[key] = None
        return None
    try:
        ctx = prev.contesto(cache, slug, ruolo, fd)
    except Exception:
        ctx = None
    d = prev.delta_favorito_odds(ctx) if ctx else None
    _cache_delta[key] = d
    return d


RUOLO_FULL = {'GK': 'Goalkeeper', 'DEF': 'Defender', 'MID': 'Midfielder', 'FWD': 'Forward'}

# D = ogni ruolo al suo ottimo per-ruolo misurato a campione pieno (anche dove
# non passava il criterio severo -- qui non si adotta un k isolato, si
# verifica che tutti i ruoli siano corretti con lo stesso criterio)
POLICY_D = {'DEF': ('mult', 0.2), 'MID': ('mult', 0.2), 'FWD': ('mult', 0.1), 'GK': ('add', 3.0)}


def _atteso_regolato(c, gw, policy):
    """atteso_raw dopo la correzione di `policy` (dict ruolo -> (kind,k)),
    PRIMA della calibrazione. kind='mult': raw*(1+k*delta). kind='add':
    raw+k*delta (stessa forma additiva usata per il GK nella misura
    per-ruolo)."""
    cod = c['codice']
    atteso_raw = c['atteso_raw']
    spec = policy.get(cod)
    if not spec:
        return atteso_raw
    kind, k = spec
    if not k:
        return atteso_raw
    d = delta_per_carta(c['slug'], RUOLO_FULL[cod], gw['fine'])
    if d is None:
        return atteso_raw
    if kind == 'mult':
        return atteso_raw * (1.0 + k * d)
    return atteso_raw + k * d


def costruisci(gw, k_def, k_fwd, policy=None, centra=False):
    """Come costruisci() di p11_confronta.py ma con l'aggiustamento
    applicato PRIMA della calibrazione. `policy`, se dato, sovrascrive
    k_def/k_fwd con un dizionario per-ruolo generico (usato per D/E).
    `centra`=True (policy E): ricentra l'atteso_cal aggiustato sulla media
    per-ruolo di QUESTA GW, cosi' la media del ruolo resta invariata
    rispetto ad A e cambia solo l'ordinamento interno al ruolo."""
    pool = [c for c in gw['pool'] if c.get('reale') is not None]
    leghe = sorted(set(c['lega'] for c in pool) | {'senza_lega'})
    role_data = {lg: {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in leghe}
    counts = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}

    if policy is None:
        policy = {'DEF': ('mult', k_def) if k_def else None,
                  'FWD': ('mult', k_fwd) if k_fwd else None}
        policy = {k: v for k, v in policy.items() if v}

    righe_tmp = []
    for c in pool:
        cod = c['codice']
        atteso_raw_adj = _atteso_regolato(c, gw, policy)
        atteso_cal_adj = bfg.calibra(atteso_raw_adj, cod)
        atteso_cal_a = bfg.calibra(c['atteso_raw'], cod)  # A, per il centraggio
        righe_tmp.append((c, atteso_cal_adj, atteso_cal_a))

    if centra:
        somma_adj = collections.defaultdict(float); somma_a = collections.defaultdict(float)
        n_ruolo = collections.defaultdict(int)
        for c, adj, a in righe_tmp:
            somma_adj[c['codice']] += adj; somma_a[c['codice']] += a; n_ruolo[c['codice']] += 1
        shift = {cod: (somma_a[cod] - somma_adj[cod]) / n_ruolo[cod] for cod in n_ruolo}
    else:
        shift = collections.defaultdict(float)

    for c, adj, _a in righe_tmp:
        cod = c['codice']
        atteso_cal = adj + shift[cod]
        row = {'slug': c['slug'], 'atteso': atteso_cal, 'low': 0, 'high': 0,
               'team_slug': c['squadra'], 'opponent_team_slug': c['opp_slug'],
               'ordinamento': None, 'kickoff': None, 'opp_factor': None,
               'league': c['lega'], 'role_key': cod,
               'reale': c['reale'], 'atteso_cal': atteso_cal}
        role_data[c['lega']][cod].append(row)
        counts[cod][c['slug']] = {'in_season': c['copie'], 'classic': 0, 'l10': c['l10']}
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


CAP_MULT = 1.2

def realizzato(formazione, cap_row):
    return sum(r['reale'] for _s, r, _t in formazione) + (CAP_MULT - 1.0) * cap_row['reale']


def esito(slot, punteggio):
    a = arena_per_slug_score.get((slot['slug'], round(slot['mio_score'] or -1, 2)))
    if a is None:
        a = {'punteggi': slot['punteggi'], 'tipo': slot['tipo'],
             'rank_premiato': slot['rank_premiato'], 'premio_essenze': slot['premio_essenze'],
             'costo': slot['costo']}
    rank = E.piazzamento(a, slot['mio_score'], punteggio)
    premio = E.premio(a, rank, premi_tab)
    costo = E.costo(a)
    return rank, premio, costo


def gioca(gw, slots, k_def, k_fwd, policy=None, centra=False):
    role_data, pools, card_pool, leghe = costruisci(gw, k_def, k_fwd, policy=policy, centra=centra)
    orig = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe)
    fuori = []
    try:
        for s in slots:
            tipo_bfg = s['tipo_bfg']
            shape = bfg.FORMATION_SHAPES[tipo_bfg]
            pool_league = bfg.POOL_LEAGUE_BY_TYPE[tipo_bfg]
            l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
            stato = bfg._istantanea_pool(card_pool)
            formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, l10_cap,
                apply_stack_guard=False, variance_mode=True,
                apply_positive_synergy=False, strict_gk_anti_synergy=False)
            if errore or not formazione:
                bfg._ripristina_pool(card_pool, stato)
                fuori.append(None)
                continue
            fuori.append(formazione)
    finally:
        bfg.LEAGUES = orig
    return fuori


def esegui():
    righe = []
    saltate = 0
    for fx, gw in sorted(pool_per_gw.items(), key=lambda kv: kv[1]['cutoff']):
        slots = [s for s in gw['slot'] if s['tipo'] in TIPI_INCLUSE
                 and s.get('punteggi') and s.get('mio_score') is not None]
        if not slots:
            continue
        pool = [c for c in gw['pool'] if c.get('reale') is not None]
        ruoli = collections.Counter(c['codice'] for c in pool)
        if not all(ruoli[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
            saltate += 1
            continue
        slots = sorted(slots, key=lambda s: (s['tipo'], s['slug']))
        fa = gioca(gw, slots, 0.0, 0.0)
        fb = gioca(gw, slots, 0.2, 0.0)
        fc = gioca(gw, slots, 0.2, 0.1)
        fd = gioca(gw, slots, 0.0, 0.0, policy=POLICY_D, centra=False)
        fe = gioca(gw, slots, 0.0, 0.0, policy=POLICY_D, centra=True)
        for s, la, lb, lc, ld, le in zip(slots, fa, fb, fc, fd, fe):
            if any(x is None for x in (la, lb, lc, ld, le)):
                continue
            ca, cb, cc, cd, ce = (capitano_atteso(la), capitano_atteso(lb), capitano_atteso(lc),
                                   capitano_atteso(ld), capitano_atteso(le))
            pa, pb_, pc, pd, pe = (realizzato(la, ca), realizzato(lb, cb), realizzato(lc, cc),
                                    realizzato(ld, cd), realizzato(le, ce))
            ra, pra, co = esito(s, pa)
            rb, prb, _ = esito(s, pb_)
            rc, prc, _ = esito(s, pc)
            rd, prd, _ = esito(s, pd)
            re_, pre, _ = esito(s, pe)
            sa = set(r['slug'] for _x, r, _t in la)
            sb = set(r['slug'] for _x, r, _t in lb)
            sc = set(r['slug'] for _x, r, _t in lc)
            sd = set(r['slug'] for _x, r, _t in ld)
            se = set(r['slug'] for _x, r, _t in le)
            comp_a = collections.Counter(r['role_key'] for _x, r, _t in la)
            comp_b = collections.Counter(r['role_key'] for _x, r, _t in lb)
            comp_c = collections.Counter(r['role_key'] for _x, r, _t in lc)
            comp_d = collections.Counter(r['role_key'] for _x, r, _t in ld)
            comp_e = collections.Counter(r['role_key'] for _x, r, _t in le)
            righe.append({
                'fixture': fx, 'slug': s['slug'], 'tipo': TIPO_LABEL.get(s['tipo'], s['tipo']),
                'costo': co, 'fine': gw['fine'][:10],
                'A_punti': pa, 'A_rank': ra, 'A_premio': pra, 'A_comp': dict(comp_a),
                'B_punti': pb_, 'B_rank': rb, 'B_premio': prb, 'B_comp': dict(comp_b),
                'C_punti': pc, 'C_rank': rc, 'C_premio': prc, 'C_comp': dict(comp_c),
                'D_punti': pd, 'D_rank': rd, 'D_premio': prd, 'D_comp': dict(comp_d),
                'E_punti': pe, 'E_rank': re_, 'E_premio': pre, 'E_comp': dict(comp_e),
                'overlap_AB': len(sa & sb), 'overlap_AC': len(sa & sc),
                'overlap_AD': len(sa & sd), 'overlap_AE': len(sa & se),
            })
    return righe, saltate


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def boot_delta(righe, chiave_a, chiave_b, B=2000, seed=11):
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[r['fixture']].append(r)
    chiavi = list(gruppi)
    unita = [gruppi[k] for k in chiavi]
    n = len(unita)
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        num = 0.0; den = 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r[chiave_b] - r[chiave_a]; den += 1
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
    p('  arene valutate: %d   giornate: %d' % (len(righe), len(set(r['fixture'] for r in righe))))

    POLICIE = (('A produzione', 'A'), ('B DEF k0.2', 'B'), ('C DEF+FWD', 'C'),
               ('D ogni ruolo', 'D'), ('E D centrata', 'E'))

    p('\n  COMPOSIZIONE MEDIA PER RUOLO (su 5 slot):')
    p('  %-14s %6s %6s %6s %6s' % ('policy', 'GK', 'DEF', 'MID', 'FWD'))
    for nome, sigla in POLICIE:
        cm = comp_media(righe, sigla + '_comp')
        p('  %-14s %6.2f %6.2f %6.2f %6.2f' % (nome, cm['GK'], cm['DEF'], cm['MID'], cm['FWD']))

    p('\n  PUNTI E RANK:')
    p('  %-14s %10s %10s' % ('policy', 'punti medi', 'rank medio'))
    for nome, sigla in POLICIE:
        p('  %-14s %10.2f %10.3f' % (nome, media(r[sigla + '_punti'] for r in righe),
                                      media(r[sigla + '_rank'] for r in righe)))

    p('\n  DELTA vs A (bootstrap appaiato su GIORNATE, IC95, B=2000):')
    for nome, sigla in POLICIE[1:]:
        kp, kr = sigla + '_punti', sigla + '_rank'
        d_punti = media(r[kp] - r['A_punti'] for r in righe)
        lo_p, hi_p = boot_delta(righe, 'A_punti', kp)
        d_rank = media(r[kr] - r['A_rank'] for r in righe)
        lo_r, hi_r = boot_delta(righe, 'A_rank', kr)
        p('    %-14s punti %+.2f  IC95 [%s, %s]' % (
            nome, d_punti, ('%+.2f' % lo_p) if lo_p is not None else 'n/a',
            ('%+.2f' % hi_p) if hi_p is not None else 'n/a'))
        p('    %-14s rank  %+.3f  IC95 [%s, %s]  (neg = meglio)' % (
            nome, d_rank, ('%+.3f' % lo_r) if lo_r is not None else 'n/a',
            ('%+.3f' % hi_r) if hi_r is not None else 'n/a'))

    p('\n  SOVRAPPOSIZIONE (carte su 5 in comune con A):')
    for nome, kov in (('B vs A', 'overlap_AB'), ('C vs A', 'overlap_AC'),
                      ('D vs A', 'overlap_AD'), ('E vs A', 'overlap_AE')):
        dist = collections.Counter(r[kov] for r in righe)
        p('    %-10s media %.2f/5  distribuzione: %s' % (
            nome, media(r[kov] for r in righe),
            ', '.join('%d/5=%d' % (k, dist[k]) for k in sorted(dist))))

    p('\n  CONTROLLO DI SANITA E: la composizione media deve restare uguale ad A entro il rumore')
    cm_a = comp_media(righe, 'A_comp'); cm_e = comp_media(righe, 'E_comp')
    for ruolo in ('GK', 'DEF', 'MID', 'FWD'):
        diff = cm_e[ruolo] - cm_a[ruolo]
        p('    %-4s A=%.2f  E=%.2f  diff=%+.3f%s' % (
            ruolo, cm_a[ruolo], cm_e[ruolo], diff,
            '  <- si sposta, la normalizzazione NON isola solo l ordinamento' if abs(diff) > 0.05 else ''))


def main():
    p('P11 -- policy A/B/C/D/E sul mazzo REALE dell utente (227 arene)')
    p('mazzo fisso, arene division escluse, walk-forward as-of pre-GW')
    righe, saltate = esegui()
    p('giornate totali nel pool: %d, saltate (pool incompleto): %d' % (len(pool_per_gw), saltate))
    p('arene valutate: %d' % len(righe))

    report(righe, 'TOTALE (Beginner+cap220+cap260+uncapped)')
    for tipo in ('Beginner', 'cap 220', 'cap 260', 'uncapped'):
        sotto = [r for r in righe if r['tipo'] == tipo]
        report(sotto, 'SOLO %s (n=%d)' % (tipo, len(sotto)))

    with open(os.path.join(SP, 'p11_favorito_odds_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    with open(os.path.join(SP, 'p11_favorito_odds_righe.json'), 'w', encoding='utf-8') as fh:
        json.dump(righe, fh, ensure_ascii=False)
    p('\nsalvato in analisi_manager/p11_favorito_odds_out.txt')


if __name__ == '__main__':
    main()
