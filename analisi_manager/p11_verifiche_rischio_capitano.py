"""Due verifiche sul Brief 1 (composizione bloccata), stesso impianto di
p11_bloccato_tutti_mazzi.py, su tutti i mazzi dati_globali/manager_*.json.

VERIFICA 1 -- il backtest e' cieco al rischio di non giocare?
  Il knapsack sceglie solo fra carte con 'reale' trovato (giocato davvero):
  le righe scartate per reale assente non rischiano mai lo zero da panchina,
  per NESSUNA policy. Se favorito_odds delle carte scartate e' sistemati-
  camente diverso da quello delle carte tenute, la misura di Brief 1 e'
  distorta. Si confrontano media/SD/quartili di favorito_odds fra tenute e
  scartate, per ruolo, su tutte le carte candidate della finestra +/-30gg
  (non solo quelle poi entrate in formazione).

VERIFICA 2 -- capitano bloccato.
  In Brief 1 la regola capitano gira sull'atteso di ciascuna policy: B' puo'
  quindi cambiare anche IL CAPITANO (+20% in arena), non solo la selezione.
  Si rifa' Brief 1 con B' che usa lo STESSO capitano (stessa carta) scelto
  da A quando quella carta e' ancora presente nella formazione B' (lo e'
  sempre se il capitano di A non e' un DEF, dato che MID/FWD/GK non sono
  toccati dall'aggiustamento e la composizione e' identica per costruzione).
  Se il capitano di A e' un DEF sostituito dalla selezione B', si segna un
  fallback (si tiene il capitano di B' non bloccato per quell'arena) e si
  conta quante volte succede.

Nessuna modifica a file di produzione, nessun commit.
"""
import os, sys, io, json, math, random, collections
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT); sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p11_bloccato_tutti_mazzi as M
import backtest_arene_previsioni as prev

out = []
def p(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)


def diag_e_verifiche(fname):
    manager, giornate = M.carica_manager(fname)
    kept_d = collections.defaultdict(list)
    disc_d = collections.defaultdict(list)
    righe_locked = []
    cambi_captain = 0
    fallback_lock = 0

    for gw_target, info in sorted(giornate.items(), key=lambda kv: kv[1]['data']):
        slots_righe = [r for r in info['righe'] if r.get('tipo_arena') in M.TIPI_VALIDI]
        if not slots_righe:
            continue
        tipo_bfg_list = []
        tipo_label_list = []
        for r in slots_righe:
            tb, lab = M.tipo_bfg_di(r)
            if tb:
                tipo_bfg_list.append(tb)
                tipo_label_list.append(lab)
        if not tipo_bfg_list:
            continue

        # ---- VERIFICA 1: favorito_odds tenute vs scartate per reale assente
        carte_per_slug, reale_target = M.costruisci_pool_gw(giornate, gw_target)
        gw_data = giornate[gw_target]['data']
        for (slug, ruolo_full), info2 in carte_per_slug.items():
            cod = M.RUOLO_COD.get(ruolo_full)
            if cod is None:
                continue
            reale = reale_target.get((slug, ruolo_full))
            if reale is None:
                reale = M.reale_da_cache(slug, gw_data)
            try:
                ctx = prev.contesto(M.cache, slug, ruolo_full, M._dt(gw_data))
            except Exception:
                ctx = None
            if ctx is None:
                continue
            d = prev.delta_favorito_odds(ctx)
            if d is None:
                continue
            if reale is None:
                disc_d[cod].append(d)
            else:
                kept_d[cod].append(d)

        # ---- VERIFICA 2: capitano bloccato
        base_pool, sa, sr = M.prepara_gw_base(giornate, gw_target)
        if len(base_pool) < 5:
            continue
        pool_a = M.applica_policy(base_pool, None)
        pool_b = M.applica_policy(base_pool, {'DEF': ('mult', 0.2)})
        fa = M.gioca(pool_a, tipo_bfg_list)
        fb = M.gioca_bloccato(pool_b, tipo_bfg_list, fa)
        for lab, la, lb in zip(tipo_label_list, fa, fb):
            if la is None or lb is None:
                continue
            ca = M.capitano_atteso(la)
            cb_free = M.capitano_atteso(lb)
            if cb_free['slug'] != ca['slug']:
                cambi_captain += 1
            cb_locked = None
            for _s, r, _t in lb:
                if r['slug'] == ca['slug']:
                    cb_locked = r
                    break
            if cb_locked is None:
                fallback_lock += 1
                cb_locked = cb_free
            pa = M.realizzato(la, ca)
            pb_locked = M.realizzato(lb, cb_locked)
            righe_locked.append({'gw': gw_target, 'tipo': lab, 'A_punti': pa, 'B_punti': pb_locked})

    return manager, kept_d, disc_d, righe_locked, cambi_captain, fallback_lock


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def sd(v):
    v = list(v)
    if len(v) < 2:
        return float('nan')
    m = media(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def quartili(v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return (float('nan'),) * 3
    def q(f):
        idx = f * (n - 1)
        lo = int(math.floor(idx)); hi = int(math.ceil(idx))
        if lo == hi:
            return v[lo]
        return v[lo] + (v[hi] - v[lo]) * (idx - lo)
    return q(0.25), q(0.5), q(0.75)


def sign_test_p(n_pos, n_neg):
    n = n_pos + n_neg
    if n == 0:
        return float('nan')
    k = min(n_pos, n_neg)
    from math import comb
    cum = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * cum)


def boot_delta_cluster(righe, B=2000, seed=11):
    gruppi = collections.defaultdict(list)
    for r in righe:
        gruppi[r['gw']].append(r)
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


def main():
    p('VERIFICA 1+2 sul Brief 1 (composizione bloccata) -- tutti i mazzi')
    p('V1: favorito_odds tenute vs scartate-per-reale-assente, per ruolo')
    p('V2: Brief 1 rifatto con capitano BLOCCATO (stessa carta di A quando presente in B\')')

    tutti = sorted(f for f in os.listdir(M.SCRATCH) if f.startswith('manager_') and f.endswith('.json'))
    tutti = [f for f in tutti if f not in M.ESCLUSI]
    p('\nmazzi esclusi: %s' % sorted(M.ESCLUSI))
    p('mazzi da processare: %d' % len(tutti))

    kept_tot = collections.defaultdict(list)
    disc_tot = collections.defaultdict(list)
    risultati = []
    tot_cambi = tot_fallback = tot_arene = 0

    for i, fname in enumerate(tutti):
        p('\n[%d/%d] %s ...' % (i + 1, len(tutti), fname))
        try:
            manager, kd, dd, righe_locked, cambi, fallback = diag_e_verifiche(fname)
        except Exception as ex:
            p('  ERRORE: %r -- saltato' % ex)
            continue
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            kept_tot[cod].extend(kd.get(cod, []))
            disc_tot[cod].extend(dd.get(cod, []))
        n_kept_m = sum(len(v) for v in kd.values())
        n_disc_m = sum(len(v) for v in dd.values())
        tasso = 100 * n_disc_m / (n_kept_m + n_disc_m) if (n_kept_m + n_disc_m) else float('nan')
        n_arene = len(righe_locked)
        overlap_flag = ''
        d_medio = media(r['B_punti'] - r['A_punti'] for r in righe_locked) if righe_locked else float('nan')
        p('  righe tenute=%d scartate(reale assente)=%d  tasso scarto=%.1f%%' % (n_kept_m, n_disc_m, tasso))
        p('  arene(capitano bloccato)=%d  cambi capitano(pre-blocco)=%d  fallback(non presente in B\')=%d'
          % (n_arene, cambi, fallback))
        if n_arene:
            p('  delta B\'(locked)-A punti = %+.2f' % d_medio)
        tot_cambi += cambi; tot_fallback += fallback; tot_arene += n_arene
        risultati.append({'file': fname, 'manager': manager, 'n_kept': n_kept_m, 'n_disc': n_disc_m,
                           'tasso_scarto': tasso, 'righe_locked': righe_locked,
                           'cambi': cambi, 'fallback': fallback})

    # ================================================================ V1
    p('\n' + '=' * 100)
    p('VERIFICA 1 -- favorito_odds: TENUTE (reale trovato) vs SCARTATE (reale assente), per ruolo')
    p('(pool di tutte le carte candidate nella finestra +/-30gg, tutti i 38 mazzi, non solo quelle in formazione)')
    p('=' * 100)
    p('%-5s %10s %10s %10s %8s %8s %8s %8s | %10s %10s %10s %8s %8s %8s %8s' % (
        'ruolo', 'n_tenute', 'media_T', 'SD_T', 'Q1_T', 'med_T', 'Q3_T', '',
        'n_scart', 'media_S', 'SD_S', 'Q1_S', 'med_S', 'Q3_S', ''))
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        kt = kept_tot[cod]; ds = disc_tot[cod]
        qkt = quartili(kt); qds = quartili(ds)
        p('%-5s %10d %10.4f %10.4f %8.4f %8.4f %8.4f | %10d %10.4f %10.4f %8.4f %8.4f %8.4f' % (
            cod, len(kt), media(kt), sd(kt), qkt[0], qkt[1], qkt[2],
            len(ds), media(ds), sd(ds), qds[0], qds[1], qds[2]))
    p('\n  differenza media (scartate - tenute), per ruolo:')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        kt = kept_tot[cod]; ds = disc_tot[cod]
        if kt and ds:
            p('    %-4s %+.4f  (tenute media %.4f, n=%d | scartate media %.4f, n=%d)' % (
                cod, media(ds) - media(kt), media(kt), len(kt), media(ds), len(ds)))

    p('\n  tasso di scarto per mazzo (quota di righe scartate per reale assente sul totale con d calcolabile):')
    p('  %-45s %8s %8s %8s' % ('manager', 'tenute', 'scartate', 'tasso%'))
    for r in sorted(risultati, key=lambda x: -x['tasso_scarto'] if x['tasso_scarto'] == x['tasso_scarto'] else 0):
        p('  %-45s %8d %8d %7.1f%%%s' % (r['manager'][:45], r['n_kept'], r['n_disc'], r['tasso_scarto'],
          '  <- >30%, leggere il test con riserva' if r['tasso_scarto'] > 30 else ''))

    # ================================================================ V2
    p('\n' + '=' * 100)
    p('VERIFICA 2 -- Brief 1 con CAPITANO BLOCCATO (stessa carta di A quando presente in B\')')
    p('=' * 100)
    p('  totale arene valutate: %d' % tot_arene)
    p('  cambi di capitano PRIMA del blocco (B\' liberO avrebbe capitanato un\'altra carta): %d (%.1f%%)'
      % (tot_cambi, 100 * tot_cambi / tot_arene if tot_arene else float('nan')))
    p('  fallback (capitano di A era un DEF sostituito, non piu\' presente in B\'): %d (%.1f%%)'
      % (tot_fallback, 100 * tot_fallback / tot_arene if tot_arene else float('nan')))

    utili2 = []
    for r in risultati:
        righe = r['righe_locked']
        if not righe:
            continue
        overlap_note = ''
        d_medio = media(rr['B_punti'] - rr['A_punti'] for rr in righe)
        lo, hi = boot_delta_cluster(righe)
        n_gw = len(set(rr['gw'] for rr in righe))
        r['n_arene2'] = len(righe); r['n_gw2'] = n_gw; r['d_medio2'] = d_medio; r['lo2'] = lo; r['hi2'] = hi
        utili2.append(r)

    p('\n  %-45s %6s %5s %8s %20s' % ('manager', 'arene', 'gg', 'delta', 'IC95'))
    for r in sorted(utili2, key=lambda x: -x['n_arene2']):
        ic = ('[%+.2f,%+.2f]' % (r['lo2'], r['hi2'])) if r['lo2'] is not None else 'n/a'
        p('  %-45s %6d %5d %+8.2f %20s' % (r['manager'][:45], r['n_arene2'], r['n_gw2'], r['d_medio2'], ic))

    pos = [r for r in utili2 if r['d_medio2'] > 0]
    neg = [r for r in utili2 if r['d_medio2'] < 0]
    zero = [r for r in utili2 if r['d_medio2'] == 0]
    p('\n  LETTURA 1 (capitano bloccato) -- segno su %d mazzi: positivi=%d negativi=%d zero=%d'
      % (len(utili2), len(pos), len(neg), len(zero)))
    pv = sign_test_p(len(pos), len(neg))
    p('  test del segno (bilaterale): p-value = %.4f' % pv)

    almeno16 = [r for r in utili2 if r['n_gw2'] >= 16]
    p('\n  LETTURA 2 (capitano bloccato) -- mazzi con >=16 giornate: n=%d' % len(almeno16))
    if almeno16:
        pos16 = sum(1 for r in almeno16 if r['d_medio2'] > 0)
        neg16 = sum(1 for r in almeno16 if r['d_medio2'] < 0)
        p('    positivi=%d negativi=%d  p=%.4f' % (pos16, neg16, sign_test_p(pos16, neg16)))

    def pesato(lista, etichetta):
        p('\n  ' + etichetta)
        righe_tot = [rr for r in lista for rr in r['righe_locked']]
        if not righe_tot:
            p('    nessuna riga')
            return
        d = media(rr['B_punti'] - rr['A_punti'] for rr in righe_tot)
        gruppi = collections.defaultdict(list)
        for r in lista:
            for rr in r['righe_locked']:
                gruppi[(r['manager'], rr['gw'])].append(rr)
        unita = list(gruppi.values())
        n = len(unita)
        rnd = random.Random(11)
        vals = []
        for _ in range(2000):
            num = 0.0; den = 0
            for _ in range(n):
                g = unita[rnd.randrange(n)]
                for rr in g:
                    num += rr['B_punti'] - rr['A_punti']; den += 1
            if den:
                vals.append(num / den)
        vals.sort()
        lo = vals[int(.025 * len(vals))] if len(vals) >= 30 else None
        hi = vals[int(.975 * len(vals))] if len(vals) >= 30 else None
        p('    arene=%d mazzi=%d cluster=%d  delta pesato=%+.3f  IC95 [%s, %s]' % (
            len(righe_tot), len(lista), n, d,
            ('%+.3f' % lo) if lo is not None else 'n/a', ('%+.3f' % hi) if hi is not None else 'n/a'))

    pesato(utili2, 'LETTURA 3 (capitano bloccato) -- delta pesato per arene, con forever-young')
    pesato([r for r in utili2 if 'forever-young' not in r['file']],
           'LETTURA 3bis (capitano bloccato) -- delta pesato per arene, senza forever-young')

    with open(os.path.join(ROOT, 'analisi_manager', 'p11_verifiche_out.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    p('\nsalvato in analisi_manager/p11_verifiche_out.txt')


if __name__ == '__main__':
    main()
