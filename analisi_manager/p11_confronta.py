# -*- coding: utf-8 -*-
"""P11 passi 3-5 - due policy di costruzione della formazione sul mazzo REALE
dell'utente, stesse arene, stessi vincoli.

  policy A  = massimizza la somma degli attesi CALIBRATI (produzione di oggi)
  policy B  = massimizza P(>=1 boom) = 1 - prod(1-p_i)
              equivalente lineare: massimizza sum(-log(1-p_i))  ->  stesso
              knapsack esatto, obiettivo diverso.

Capitano: STESSA regola per entrambe (bff.pick_captain sull'atteso calibrato),
cosi' l'unica differenza misurata e' la SELEZIONE delle carte. Variante B'
con capitano scelto sul boom riportata a parte.

Walk-forward: la stima p_i per una giornata usa solo coppie con data
STRETTAMENTE precedente al cutoff di quella giornata.
"""
import os, sys, io, json, math, random, collections, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
SP = os.path.dirname(os.path.abspath(__file__))
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)

import p11_boom as PB
import backtest_arene_produzione as BP
import backtest_arene_economia as E

bfg = BP.bfg
bff = BP.bff

CAP_MULT = 1.2
TIPI_CAPPED = {'cap 260', 'cap 220'}
TIPI_UNCAPPED = {'Uncapped', 'arena uncapped'}
TIPI_ESCLUSI = {'Beginner', 'arena division'}

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

pool_per_gw = json.load(open(os.path.join(SP, 'p11_pool.json'), encoding='utf-8'))
arene_tutte = json.load(open('dati_globali/arene_storico.json', encoding='utf-8'))['arene']
premi_tab = E.tabella_premi(arene_tutte)
arena_per_slug_score = {}
for a in arene_tutte:
    arena_per_slug_score.setdefault((a['slug'], round(a.get('mio_score') or -1, 2)), a)

coppie = PB.carica_coppie(os.path.join(SP, 'p11_coppie_prod.json'))
date_taglio = sorted(set(g['cutoff'][:10] for g in pool_per_gw.values()))
WF = PB.ModelliWalkForward(coppie, date_taglio)


# ----------------------------------------------------------------- utilita'
def costruisci(gw, obiettivo):
    """role_data/pools/card_pool per una giornata. `obiettivo` mappa una riga
    di pool -> valore da massimizzare, scritto in row['atteso']."""
    pool = [c for c in gw['pool'] if c.get('reale') is not None]
    leghe = sorted(set(c['lega'] for c in pool) | {'senza_lega'})
    role_data = {lg: {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in leghe}
    counts = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}
    for c in pool:
        cod = c['codice']
        row = {'slug': c['slug'], 'atteso': obiettivo(c), 'low': 0, 'high': 0,
               'team_slug': c['squadra'], 'opponent_team_slug': c['opp_slug'],
               'ordinamento': None, 'kickoff': None, 'opp_factor': None,
               'league': c['lega'], 'role_key': cod,
               'reale': c['reale'], 'atteso_cal': c['_cal'], 'p_boom': c['_p']}
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
    """pick_captain di produzione, ma sull'atteso CALIBRATO (che in policy B
    non e' in row['atteso'])."""
    righe = [r for _s, r, _t in formazione]
    fuori = [r for r in righe if r['role_key'] != 'GK']
    gk = [r for r in righe if r['role_key'] == 'GK']
    bo = max(fuori, key=lambda r: r['atteso_cal']) if fuori else None
    bg = max(gk, key=lambda r: r['atteso_cal']) if gk else None
    marg = getattr(bff, 'GK_CAPTAIN_MARGIN', 0)
    if bg and (not bo or bg['atteso_cal'] >= bo['atteso_cal'] + marg):
        return bg
    return bo or bg


def capitano_boom(formazione):
    """Il capitano che massimizza P(>=1 boom): la carta capitanata booma se
    reale*1.2 >= 75, cioe' con soglia 62.5 -> p piu' alta."""
    righe = [r for _s, r, _t in formazione]
    best = None; bestv = -1
    for cand in righe:
        prod = 1.0
        for r in righe:
            pi = r['p_boom_cap'] if r is cand else r['p_boom']
            prod *= (1 - pi)
        v = 1 - prod
        if v > bestv:
            bestv, best = v, cand
    return best


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


def gioca(gw, slots, obiettivo, depleta):
    """Ritorna, per ogni slot, (formazione, cap_row)."""
    role_data, pools, card_pool, leghe = costruisci(gw, obiettivo)
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
            if not depleta:
                bfg._ripristina_pool(card_pool, stato)
            fuori.append(formazione)
    finally:
        bfg.LEAGUES = orig
    return fuori


# --------------------------------------------------------------- esecuzione
def esegui(tipi_ammessi, depleta, etichetta):
    righe = []
    saltate_gw = 0
    for fx, gw in sorted(pool_per_gw.items(), key=lambda kv: kv[1]['cutoff']):
        slots = [s for s in gw['slot'] if s['tipo'] in tipi_ammessi
                 and s.get('punteggi') and s.get('mio_score') is not None]
        if not slots:
            continue
        mod = WF.get(gw['cutoff'][:10])
        if mod is None:
            saltate_gw += 1
            continue
        pool = [c for c in gw['pool'] if c.get('reale') is not None]
        ruoli = collections.Counter(c['codice'] for c in pool)
        if not all(ruoli[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
            saltate_gw += 1
            continue
        for c in pool:
            c['_cal'] = bfg.calibra(c['atteso_raw'], c['codice'])
            c['_p'] = mod.p(c['codice'], c['atteso_raw'])
            c['_pcap'] = mod.p(c['codice'], c['atteso_raw'])  # placeholder
        # p con capitano: soglia effettiva 75/1.2 = 62.5 -> si stima invertendo
        # la logistica sull'atteso equivalente non e' possibile; si usa il fit
        # a soglia 62.5 (vedi mod62 sotto)
        slots = sorted(slots, key=lambda s: (s['tipo'], s['slug']))
        fa = gioca(gw, slots, lambda c: c['_cal'], depleta)
        fb = gioca(gw, slots, lambda c: -math.log(max(1e-12, 1.0 - c['_p'])), depleta)
        for s, la, lb in zip(slots, fa, fb):
            if la is None or lb is None:
                continue
            ca = capitano_atteso(la); cb = capitano_atteso(lb)
            pa = realizzato(la, ca); pb_ = realizzato(lb, cb)
            ra, pra, co = esito(s, pa)
            rb, prb, _ = esito(s, pb_)
            ru, pru, _ = esito(s, s['mio_score'])
            sa = set(r['slug'] for _x, r, _t in la)
            sb = set(r['slug'] for _x, r, _t in lb)
            righe.append({
                'fixture': fx, 'slug': s['slug'], 'tipo': s['tipo'], 'costo': co,
                'A_punti': pa, 'A_rank': ra, 'A_premio': pra,
                'B_punti': pb_, 'B_rank': rb, 'B_premio': prb,
                'U_punti': s['mio_score'], 'U_rank': s['mio_rank'], 'U_premio': s['premio_essenze'] or 0,
                'overlap': len(sa & sb), 'identiche': sa == sb,
                'A_pboom': 1 - math.prod(1 - r['p_boom'] for _x, r, _t in la),
                'B_pboom': 1 - math.prod(1 - r['p_boom'] for _x, r, _t in lb),
                'A_attsum': sum(r['atteso_cal'] for _x, r, _t in la) + 0.2 * ca['atteso_cal'],
                'B_attsum': sum(r['atteso_cal'] for _x, r, _t in lb) + 0.2 * cb['atteso_cal'],
            })
    return righe, saltate_gw


# ------------------------------------------------------------ statistica
def media(v):
    return sum(v) / len(v) if v else float('nan')


def boot_delta(righe, chiave_a, chiave_b, per_fixture, B=4000, seed=11):
    """IC95 del delta medio (B - A), bootstrap appaiato.
    per_fixture=True: ricampiona le GIORNATE (cluster), per rispettare il
    mazzo fisso; False: ricampiona le ARENE."""
    rnd = random.Random(seed)
    if per_fixture:
        gruppi = collections.defaultdict(list)
        for r in righe:
            gruppi[r['fixture']].append(r)
        chiavi = list(gruppi)
        unita = [gruppi[k] for k in chiavi]
    else:
        unita = [[r] for r in righe]
    n = len(unita)
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
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def blocco(titolo, righe, per_fixture):
    p('\n' + '-' * 72)
    p(titolo)
    p('-' * 72)
    if not righe:
        p('  nessuna riga')
        return
    p('  arene valutate: %d   giornate: %d' % (len(righe), len(set(r['fixture'] for r in righe))))
    p('  tipi: %s' % dict(collections.Counter(r['tipo'] for r in righe)))
    p('')
    p('  %-28s %10s %10s %10s' % ('', 'utente', 'policy A', 'policy B'))
    p('  %-28s %10.2f %10.2f %10.2f' % ('punteggio medio',
      media([r['U_punti'] for r in righe]), media([r['A_punti'] for r in righe]),
      media([r['B_punti'] for r in righe])))
    p('  %-28s %10.3f %10.3f %10.3f' % ('rank medio (basso=meglio)',
      media([r['U_rank'] for r in righe]), media([r['A_rank'] for r in righe]),
      media([r['B_rank'] for r in righe])))
    p('  %-28s %9.1f%% %9.1f%% %9.1f%%' % ('a premio (rank<=3)',
      100 * media([1 if r['U_rank'] <= 3 else 0 for r in righe]),
      100 * media([1 if r['A_rank'] <= 3 else 0 for r in righe]),
      100 * media([1 if r['B_rank'] <= 3 else 0 for r in righe])))
    p('  %-28s %10.1f %10.1f %10.1f' % ('netto medio (essenze)',
      media([r['U_premio'] - r['costo'] for r in righe]),
      media([r['A_premio'] - r['costo'] for r in righe]),
      media([r['B_premio'] - r['costo'] for r in righe])))
    p('  %-28s %10.2f %10.2f %10.2f' % ('P(>=1 boom) della formazione', float('nan'),
      media([r['A_pboom'] for r in righe]), media([r['B_pboom'] for r in righe])))
    p('  %-28s %10.1f %10.1f %10.1f' % ('somma attesi calibrati', float('nan'),
      media([r['A_attsum'] for r in righe]), media([r['B_attsum'] for r in righe])))

    for r in righe:
        r['_A_podio'] = 1.0 if r['A_rank'] <= 3 else 0.0
        r['_B_podio'] = 1.0 if r['B_rank'] <= 3 else 0.0
        r['_A_netto'] = float(r['A_premio'] - r['costo'])
        r['_B_netto'] = float(r['B_premio'] - r['costo'])
        r['_A_rank'] = float(r['A_rank']); r['_B_rank'] = float(r['B_rank'])
        r['_A_punti'] = float(r['A_punti']); r['_B_punti'] = float(r['B_punti'])

    p('')
    unita = 'GIORNATE (cluster, mazzo fisso)' if per_fixture else 'ARENE'
    p('  delta B-A, bootstrap appaiato su %s, IC95:' % unita)
    for nome, ka, kb, fmt in (('punteggio', '_A_punti', '_B_punti', '%+.2f'),
                              ('rank (neg=B meglio)', '_A_rank', '_B_rank', '%+.3f'),
                              ('podio (punti %)', '_A_podio', '_B_podio', '%+.4f'),
                              ('netto essenze', '_A_netto', '_B_netto', '%+.1f')):
        d = media([r[kb] - r[ka] for r in righe])
        lo, hi = boot_delta(righe, ka, kb, per_fixture)
        p(('    %-22s ' + fmt + '   IC95 [' + fmt + ', ' + fmt + ']') % (nome, d, lo, hi))

    p('')
    p('  PASSO 5 — sovrapposizione fra le due policy:')
    p('    carte in comune su 5: media %.3f' % media([r['overlap'] for r in righe]))
    dist = collections.Counter(r['overlap'] for r in righe)
    for k in sorted(dist):
        p('      %d/5 : %4d arene (%.1f%%)' % (k, dist[k], 100 * dist[k] / len(righe)))
    p('    formazioni IDENTICHE: %d/%d (%.1f%%)'
      % (sum(1 for r in righe if r['identiche']), len(righe),
         100 * media([1 if r['identiche'] else 0 for r in righe])))
    div = [r for r in righe if not r['identiche']]
    if div:
        p('    solo sulle %d arene DIVERSE:' % len(div))
        p('      rank A %.3f  B %.3f  (delta %+.3f)'
          % (media([r['A_rank'] for r in div]), media([r['B_rank'] for r in div]),
             media([r['B_rank'] - r['A_rank'] for r in div])))
        p('      punti A %.2f  B %.2f  (delta %+.2f)'
          % (media([r['A_punti'] for r in div]), media([r['B_punti'] for r in div]),
             media([r['B_punti'] - r['A_punti'] for r in div])))
        p('      netto A %.1f  B %.1f  (delta %+.1f)'
          % (media([r['_A_netto'] for r in div]), media([r['_B_netto'] for r in div]),
             media([r['_B_netto'] - r['_A_netto'] for r in div])))
        p('      P(>=1 boom) A %.4f  B %.4f  (B - A = %+.4f, per costruzione >=0)'
          % (media([r['A_pboom'] for r in div]), media([r['B_pboom'] for r in div]),
             media([r['B_pboom'] - r['A_pboom'] for r in div])))
        p('      somma attesi A %.1f  B %.1f  (B - A = %+.1f, per costruzione <=0)'
          % (media([r['A_attsum'] for r in div]), media([r['B_attsum'] for r in div]),
             media([r['B_attsum'] - r['A_attsum'] for r in div])))


def main():
  p('=' * 72)
  p('P11 — POLICY A (somma attesi) vs POLICY B (P>=1 boom)')
  p('=' * 72)
  p('coppie per la stima di p_boom: %d' % len(coppie))
  p('giornate preparate: %d   slot totali: %d' % (len(pool_per_gw), sum(len(g["slot"]) for g in pool_per_gw.values())))
  p('slot esclusi per decisione: Beginner (fuori dal brief) e arena division')
  p('  (le arene per-lega sono disattivate in produzione, ARENA_LEAGUES vuota:')
  p('   il generatore le tratterebbe come cap 260 miste e schiererebbe carte di')
  p('   leghe diverse, formazione NON ammissibile in quella competizione)')
  p('sinergie disattivate su ENTRAMBE le policy (il knapsack esatto delle arene')
  p('  con cap non le usa comunque; per l\'uncapped si spengono per non far')
  p('  dipendere il confronto dalla scala dell\'obiettivo)')

  righe_cap, salt = esegui(TIPI_CAPPED, depleta=True, etichetta='capped')
  blocco('A) ARENE CON CAP L10 (cap 260 + cap 220) — mazzo fisso, pool che si svuota', righe_cap, True)

  righe_260 = [r for r in righe_cap if r['tipo'] == 'cap 260']
  blocco('B) SOLO CAP 260 (la competizione principale)', righe_260, True)

  righe_indip, _ = esegui(TIPI_CAPPED, depleta=False, etichetta='capped-indip')
  blocco('C) CONTROLLO — stesse arene ma pool PIENO per ogni arena (arene indipendenti,\n'
         '   bootstrap appaiato sulle ARENE come da brief)', righe_indip, False)

  righe_unc, _ = esegui(TIPI_UNCAPPED, depleta=True, etichetta='uncapped')
  blocco('D) ARENE UNCAPPED (nessun cap L10)', righe_unc, True)

  p('\ngiornate saltate (pool incompleto o stima non addestrabile): %d' % salt)

  open(os.path.join(SP, 'p11_confronto_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
  json.dump(righe_cap, open(os.path.join(SP, 'p11_righe_cap.json'), 'w', encoding='utf-8'))


if __name__ == '__main__':
    main()
