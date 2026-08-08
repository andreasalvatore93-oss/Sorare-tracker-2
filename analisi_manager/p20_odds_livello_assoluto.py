"""BRIEF_SONNET_ODDS_LIVELLO_ASSOLUTO_2026-08-09.txt -- il livello assoluto
delle quote (p_win_own - p_win_opp della partita da giocare, SENZA sottrarre
la media storica e SENZA il requisito delle 5 partite) batte G meglio del
delta storico (`delta_favorito_odds`, gia' misurato NON positivo in
p20_odds_vs_grade.py)? Riusa TUTTA l'infrastruttura di p19/p20 (base pulita
non-arena, pool_rows, bootstrap sui manager, placebo), nessuna riscrittura
del knapsack (D7 CLAUDE.md).

SCALA: delta e livello NON hanno la stessa distribuzione (delta centrato su
zero, livello no). Scelta dichiarata (§2c del brief): entrambi i segnali
vengono STANDARDIZZATI (z-score) dentro ogni gruppo (lega,codice) -- stessa
convenzione gia' usata in produzione per _zgrade/zscore_gruppo -- e si
applica LO STESSO k=0.2 a entrambe le versioni z-scorate. Questo rende il
confronto G+D_z vs G+L_z una misura di FORMA del segnale, non di scala.
I numeri originali di G+D (delta grezzo, k=0.2, gia' misurati in
p20_odds_vs_grade_out.json) restano come riferimento a parte, non vengono
rifatti qui.

Rami:
  A       = _cal (produzione, nessun segnale)
  G       = _combinato (grade sopra produzione)
  G+D_z   = _d_combinato (grade + delta storico z-scorato, k=0.2)
  G+L_z   = _l_combinato (grade + livello assoluto z-scorato, k=0.2)

Nessuna modifica alla produzione. Nessuna query a Sorare (si usa l'indice
odds gia' in dati_globali/odds_1x2_index.json).
"""
import os
import sys
import io
import json
import math
import random
import argparse
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p19_nonarena_grade_scala as P19
import p16_backtest_allstar_u23 as P16
import p17_backtest_mls_hotstreak as P17
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import backtest_arene_previsioni as prev

RUOLO_FULL = {'GK': 'Goalkeeper', 'DEF': 'Defender', 'MID': 'Midfielder', 'FWD': 'Forward'}

BASI = {
    'allstar_u23': (P16._base_pulita, 'analisi_manager/p20_allstar_u23'),
    'mls_hotstreak': (P17._base_pulita, 'analisi_manager/p20_mls_hotstreak'),
}

_cache_delta = {}
_cache_livello = {}


def delta_per_carta(cache, slug, ruolo_full, fine):
    key = (slug, ruolo_full, fine.isoformat())
    if key in _cache_delta:
        return _cache_delta[key]
    try:
        ctx = prev.contesto(cache, slug, ruolo_full, fine)
    except Exception:
        ctx = None
    d = prev.delta_favorito_odds(ctx) if ctx else None
    _cache_delta[key] = d
    return d


def livello_per_carta(cache, slug, ruolo_full, fine):
    """Livello assoluto: p_win_own - p_win_opp della partita da giocare,
    SENZA sottrarre la media storica e senza il requisito delle 5 partite
    (backtest_arene_previsioni._p_own_opp_odds, righe 527-546)."""
    key = (slug, ruolo_full, fine.isoformat())
    if key in _cache_livello:
        return _cache_livello[key]
    try:
        ctx = prev.contesto(cache, slug, ruolo_full, fine)
    except Exception:
        ctx = None
    v = None
    if ctx:
        squadra, opp, cutoff = ctx.get('squadra'), ctx.get('opp_slug'), ctx.get('cutoff')
        ora = prev._p_own_opp_odds(squadra, opp, cutoff)
        if ora is not None:
            v = ora[0] - ora[1]
    _cache_livello[key] = v
    return v


def annota_segnali(unita, cache):
    """Scrive _delta_odds e _livello_odds per ogni riga di ogni pool_rows."""
    n_d_con = n_d_senza = n_l_con = n_l_senza = 0
    for u in unita:
        bounds = M.parse_fixture_bounds(u['gw'])
        d_start, d_end = bounds
        fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
        for r in u['pool_rows']:
            d = delta_per_carta(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
            l = livello_per_carta(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
            r['_delta_odds'] = d
            r['_livello_odds'] = l
            if d is None:
                n_d_senza += 1
            else:
                n_d_con += 1
            if l is None:
                n_l_senza += 1
            else:
                n_l_con += 1
    return n_d_con, n_d_senza, n_l_con, n_l_senza


def calcola_zscore(unita):
    """z-score di _delta_odds e _livello_odds dentro ogni gruppo (lega,codice)
    (stessa convenzione di zscore_gruppo/_zgrade). Righe senza segnale (o
    gruppi con <2 osservazioni) restano a z=0 -> effetto nullo, coerente con
    la regola gia' in uso "senza dato = nessun aggiustamento"."""
    gruppi = collections.defaultdict(list)
    for u in unita:
        for r in u['pool_rows']:
            gruppi[(r['lega'], r['codice'])].append(r)
    for _key, membri in gruppi.items():
        for campo_src, campo_z in (('_delta_odds', '_delta_z'), ('_livello_odds', '_livello_z')):
            idx = [i for i, m in enumerate(membri) if m.get(campo_src) is not None]
            vals = [membri[i][campo_src] for i in idx]
            if len(vals) >= 2:
                zs, _sd, _m = S21.zscore_gruppo(vals)
                for i, z in zip(idx, zs):
                    membri[i][campo_z] = z
            for m in membri:
                if campo_z not in m:
                    m[campo_z] = 0.0


def applica(pool_rows, policy_d, policy_l):
    """policy_*: dict codice -> k. k assente/0 => nessun aggiustamento
    (controllo interruttore 4a). Scrive _d_cal/_d_combinato (G+D_z) e
    _l_cal/_l_combinato (G+L_z), stessa formula additiva di _combinato."""
    for r in pool_rows:
        kd = policy_d.get(r['codice']) or 0.0
        kl = policy_l.get(r['codice']) or 0.0
        zd = r.get('_delta_z', 0.0)
        zl = r.get('_livello_z', 0.0)
        raw_d = r['atteso_raw'] * (1.0 + kd * zd) if kd else r['atteso_raw']
        raw_l = r['atteso_raw'] * (1.0 + kl * zl) if kl else r['atteso_raw']
        r['_d_cal'] = S21.bfg.calibra(raw_d, r['codice'])
        r['_l_cal'] = S21.bfg.calibra(raw_l, r['codice'])

    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        _z, sd_d, _m = S21.zscore_gruppo([m['_d_cal'] for m in membri])
        _z2, sd_l, _m2 = S21.zscore_gruppo([m['_l_cal'] for m in membri])
        for m in membri:
            m['_d_combinato'] = m['_d_cal'] + sd_d * m.get('_zgrade', 0.0)
            m['_l_combinato'] = m['_l_cal'] + sd_l * m.get('_zgrade', 0.0)


def permuta_e_ricalcola(pool_rows, policy_d, policy_l, campo_z, campo_cal, campo_combinato, rnd):
    """Placebo: permuta il campo z DENTRO ogni gruppo (lega,codice), poi
    ricalcola *_perm con le stesse formule. campo_z in {'_delta_z','_livello_z'},
    policy la relativa policy."""
    rows = [dict(r) for r in pool_rows]
    policy = policy_d if campo_z == '_delta_z' else policy_l
    gruppi = collections.defaultdict(list)
    for r in rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, cod), membri in gruppi.items():
        k = policy.get(cod) or 0.0
        idx = list(range(len(membri)))
        zvals = [membri[i][campo_z] for i in idx]
        if k and len(idx) >= 2:
            perm = list(zvals)
            rnd.shuffle(perm)
            for i, z in zip(idx, perm):
                membri[i][campo_cal + '_perm'] = S21.bfg.calibra(membri[i]['atteso_raw'] * (1.0 + k * z), cod)
        for m in membri:
            if campo_cal + '_perm' not in m:
                m[campo_cal + '_perm'] = S21.bfg.calibra(m['atteso_raw'], cod)
        _z, sd, _m = S21.zscore_gruppo([m[campo_cal + '_perm'] for m in membri])
        for m in membri:
            m[campo_combinato + '_perm'] = m[campo_cal + '_perm'] + sd * m.get('_zgrade', 0.0)
    return rows


def gioca_e_misura(unita, key):
    return P19.gioca_e_misura(unita, key)


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def delta_vs(unita, key_x, key_ref, ris_ref):
    ris_x = gioca_e_misura(unita, key_x)
    per_manager = collections.defaultdict(list)
    tot_x = tot_ref = 0.0
    cnt = 0
    for x, r in zip(ris_x, ris_ref):
        if x is None or r is None:
            continue
        per_manager[x['manager']].append(x['punti'] - r['punti'])
        tot_x += x['punti']; tot_ref += r['punti']; cnt += 1
    d = (tot_x - tot_ref) / cnt if cnt else float('nan')
    lo, hi = P19.boot_delta_manager(per_manager)
    return d, lo, hi, cnt, ris_x


def stat_desc(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if n == 0:
        return {'n': 0}
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return {'n': n, 'media': m, 'sd': sd, 'min': min(vals), 'max': max(vals)}


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs); sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sx * sy)


def passo5_correlazione(unita_tutte):
    """Domanda §5 (non obbligatoria): quanto e' correlato il livello assoluto
    con lo score_atteso (atteso_raw) gia' calcolato? Se alta, il timore del
    doppio conteggio (motivo per cui esiste il delta) e' fondato."""
    print('\n' + '=' * 78)
    print('PASSO 5 -- correlazione livello_odds vs score_atteso (atteso_raw)')
    print('=' * 78)
    per_cod = collections.defaultdict(lambda: ([], []))
    viste = set()
    for u in unita_tutte:
        for r in u['pool_rows']:
            carta = r.get('carta')
            if carta in viste:
                continue
            viste.add(carta)
            l = r.get('_livello_odds')
            if l is None:
                continue
            per_cod[r['codice']][0].append(l)
            per_cod[r['codice']][1].append(r['atteso_raw'])
            per_cod['GLOBALE'][0].append(l)
            per_cod['GLOBALE'][1].append(r['atteso_raw'])
    esito5 = {}
    for cod in ('GK', 'DEF', 'MID', 'FWD', 'GLOBALE'):
        xs, ys = per_cod.get(cod, ([], []))
        r = pearson(xs, ys)
        print(f'  {cod:8s} n={len(xs):5d}  corr(livello_odds, atteso_raw) = {r if r is None else round(r,3)}')
        esito5[cod] = {'n': len(xs), 'corr': r}
    return esito5


def dump_formazione(unita, out_path):
    """Dump leggibile (4f): una formazione completa con grade/delta/livello e
    atteso nei quattro rami (A/G/G+D_z/G+L_z) piu' il realizzato."""
    for u in unita:
        if not u['formazioni_valide']:
            continue
        f = u['formazioni_valide'][0]
        idx_f = u['formazioni_valide'].index(f)
        slot = u['slots'][idx_f]
        forme_A = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_cal', u['leghe_pool'])
        forme_G = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_combinato', u['leghe_pool'])
        forme_D = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_d_combinato', u['leghe_pool'])
        forme_L = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_l_combinato', u['leghe_pool'])
        fa, fg, fd, fl = forme_A[idx_f], forme_G[idx_f], forme_D[idx_f], forme_L[idx_f]
        if not (fa and fg and fd and fl):
            continue
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write(f'manager={u["manager"]}  gw={u["gw"]}  competizione={f.get("competizione")}\n\n')
            fh.write('POOL (slug, ruolo, grade, delta_odds, livello_odds, atteso_raw)\n')
            for r in sorted(u['pool_rows'], key=lambda x: (x['codice'], -(x['atteso_raw'] or 0))):
                fh.write(f'  {r["slug"]:30s} {r["codice"]:4s} grade={r.get("_grade")} '
                         f'delta={r.get("_delta_odds")} livello={r.get("_livello_odds")} '
                         f'atteso_raw={r["atteso_raw"]:.2f}\n')
            fh.write('\nFORMAZIONI SCELTE (A / G / G+D_z / G+L_z)\n')
            for label, form in (('A', fa), ('G', fg), ('G+D_z', fd), ('G+L_z', fl)):
                cap = S21.capitano_atteso(form)
                real = P16.realizzato_50(form, cap)
                slugs = [r['slug'] for _s, r, _t in form]
                fh.write(f'  {label:6s} carte={slugs} realizzato_capitanato={real:.2f}\n')
        print(f'  dump scritto: {out_path} (manager={u["manager"]}, gw={u["gw"]})')
        return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--placebo', type=int, default=30)
    args = ap.parse_args()

    lega_di = P19.AG.indice_lega()
    _idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug_full = collections.defaultdict(dict)
    for slug, entries in _idx_grade.items():
        for data, grade in entries:
            idx_per_slug_full[slug][data] = grade
    osservazioni, _s, _d = P19.P18.costruisci_osservazioni()
    scala_globale = P19.P18.costruisci_scala(osservazioni, cutoff=None)

    import glob
    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))

    unita_per_base = {}
    copertura_per_base = {}
    for nome_base, (base_pulita_fn, out_prefix) in BASI.items():
        unita, scarti, conta, n_gw = P19.raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di,
                                                    scala_globale, osservazioni)
        print(f'[{nome_base}] unita valide: {len(unita)}  formazioni: {sum(len(u["formazioni_valide"]) for u in unita)}')
        cache = P19.cache
        n_d_con, n_d_senza, n_l_con, n_l_senza = annota_segnali(unita, cache)
        tot = n_d_con + n_d_senza
        print(f'[{nome_base}] CONTROLLO 4b COPERTURA (n={tot}):')
        print(f'    delta_favorito_odds:  con={n_d_con} ({100*n_d_con/tot:.1f}%)  senza={n_d_senza}')
        print(f'    livello_assoluto:     con={n_l_con} ({100*n_l_con/tot:.1f}%)  senza={n_l_senza}')
        calcola_zscore(unita)
        unita_per_base[nome_base] = unita
        copertura_per_base[nome_base] = (n_d_con, n_d_senza, n_l_con, n_l_senza)

    tutte_unita = [u for lst in unita_per_base.values() for u in lst]

    # --- 2a: statistiche descrittive dei due segnali grezzi, stesso campione ---
    print('\n' + '=' * 78)
    print('CONTROLLO 2a -- statistiche descrittive (raw) dei due segnali, stesso campione')
    print('=' * 78)
    viste = set()
    delta_vals, livello_vals = [], []
    for u in tutte_unita:
        for r in u['pool_rows']:
            carta = r.get('carta')
            if carta in viste:
                continue
            viste.add(carta)
            if r.get('_delta_odds') is not None and r.get('_livello_odds') is not None:
                delta_vals.append(r['_delta_odds'])
                livello_vals.append(r['_livello_odds'])
    sd_delta = stat_desc(delta_vals)
    sd_livello = stat_desc(livello_vals)
    print(f'  delta_favorito_odds:  {sd_delta}')
    print(f'  livello_assoluto:     {sd_livello}')
    print('  SCELTA SCALA (§2c dichiarata): entrambi z-scorati per gruppo (lega,codice), stesso k=0.2.')

    esito5 = passo5_correlazione(tutte_unita)

    esito_finale = {'stat_2a': {'delta': sd_delta, 'livello': sd_livello}, 'passo5': esito5, 'basi': {}}

    for nome_base, unita in unita_per_base.items():
        print('\n' + '=' * 78)
        print(f'PASSO 3 -- {nome_base}')
        print('=' * 78)
        ris_A = gioca_e_misura(unita, '_cal')
        ris_G = gioca_e_misura(unita, '_combinato')
        n = sum(1 for a, g in zip(ris_A, ris_G) if a and g)
        a_tot = media(x['punti'] for x in ris_A if x)
        g_tot = media(x['punti'] for x in ris_G if x)
        print(f'  CONTROLLO 4c -- A={a_tot:.2f} G={g_tot:.2f} delta G-A={g_tot-a_tot:+.2f} (n={n})')

        # --- 4a interruttore: k=0 su tutti i rami deve coincidere con A ---
        for u in unita:
            applica(u['pool_rows'], {}, {})
        max_diff_d = max((abs(r['_d_cal'] - r['_cal']) for u in unita for r in u['pool_rows']), default=0.0)
        max_diff_l = max((abs(r['_l_cal'] - r['_cal']) for u in unita for r in u['pool_rows']), default=0.0)
        print(f'  CONTROLLO 4a interruttore k=0: max|_d_cal-_cal|={max_diff_d:.10f}  max|_l_cal-_cal|={max_diff_l:.10f}')

        varianti_provate = 0
        esiti_3a = {}
        ruoli_pos_d, ruoli_pos_l = [], []
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            policy = {cod: 0.2}
            for u in unita:
                applica(u['pool_rows'], policy, policy)
            varianti_provate += 1

            # 4a bis: quante carte/formazioni cambiano a k=0.2 (interruttore acceso)
            camb_carte_d = sum(1 for u in unita for r in u['pool_rows']
                                if r['codice'] == cod and abs(r['_d_cal'] - r['_cal']) > 1e-9)
            camb_carte_l = sum(1 for u in unita for r in u['pool_rows']
                                if r['codice'] == cod and abs(r['_l_cal'] - r['_cal']) > 1e-9)
            tot_cod = sum(1 for u in unita for r in u['pool_rows'] if r['codice'] == cod)

            d_d, lo_d, hi_d, cnt_d, _ = delta_vs(unita, '_d_combinato', '_combinato', ris_G)
            d_l, lo_l, hi_l, cnt_l, _ = delta_vs(unita, '_l_combinato', '_combinato', ris_G)
            print(f'  3a [{cod} k=0.2 z-scorato]  G+D_z vs G: delta={d_d:+.3f} IC95=[{lo_d:+.3f},{hi_d:+.3f}] n={cnt_d}  '
                  f'(carte cambiate D: {camb_carte_d}/{tot_cod})')
            print(f'                        G+L_z vs G: delta={d_l:+.3f} IC95=[{lo_l:+.3f},{hi_l:+.3f}] n={cnt_l}  '
                  f'(carte cambiate L: {camb_carte_l}/{tot_cod})')
            esiti_3a[cod] = {'D': {'delta': d_d, 'ic': [lo_d, hi_d], 'n': cnt_d, 'carte_cambiate': camb_carte_d, 'tot_cod': tot_cod},
                              'L': {'delta': d_l, 'ic': [lo_l, hi_l], 'n': cnt_l, 'carte_cambiate': camb_carte_l, 'tot_cod': tot_cod}}
            if lo_d is not None and lo_d > 0:
                ruoli_pos_d.append(cod)
            if lo_l is not None and lo_l > 0:
                ruoli_pos_l.append(cod)

        print(f'  ruoli positivi (IC95 tutto positivo) a k=0.2 z-scorato: D={ruoli_pos_d or "nessuno"}  L={ruoli_pos_l or "nessuno"}')

        esiti_3b = {}
        placebo_out = {}
        for etichetta, ruoli_pos, campo_z, campo_cal, campo_comb in (
                ('D', ruoli_pos_d, '_delta_z', '_d_cal', '_d_combinato'),
                ('L', ruoli_pos_l, '_livello_z', '_l_cal', '_l_combinato')):
            if not ruoli_pos:
                continue
            for k in (0.1, 0.2, 0.3):
                policy = {cod: k for cod in ruoli_pos}
                policy_altro = {}
                for u in unita:
                    if etichetta == 'D':
                        applica(u['pool_rows'], policy, policy_altro)
                    else:
                        applica(u['pool_rows'], policy_altro, policy)
                varianti_provate += 1
                d, lo, hi, cnt, _ = delta_vs(unita, campo_comb, '_combinato', ris_G)
                print(f'  3b [{etichetta} {"+".join(ruoli_pos)} k={k}]  vs G: delta={d:+.3f} '
                      f'IC95=[{lo:+.3f},{hi:+.3f}] n={cnt}')
                esiti_3b[f'{etichetta}_{k}'] = {'delta': d, 'ic': [lo, hi], 'n': cnt}

                if lo is not None and lo > 0 and args.placebo > 0:
                    placebo_deltas = []
                    for seed in range(args.placebo):
                        rnd = random.Random(70000 + seed)
                        tot_x = 0.0; tot_g = 0.0; cnt_p = 0
                        for u in unita:
                            rows_perm = permuta_e_ricalcola(u['pool_rows'], policy if etichetta == 'D' else policy_altro,
                                                             policy if etichetta == 'L' else policy_altro,
                                                             campo_z, campo_cal, campo_comb, rnd)
                            f_x = P16.gioca_nonarena(rows_perm, u['slots'], campo_comb + '_perm', u['leghe_pool'])
                            f_g = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_combinato', u['leghe_pool'])
                            for form_x, form_g in zip(f_x, f_g):
                                if form_x is None or form_g is None:
                                    continue
                                cap_x = S21.capitano_atteso(form_x)
                                cap_g = S21.capitano_atteso(form_g)
                                tot_x += P16.realizzato_50(form_x, cap_x)
                                tot_g += P16.realizzato_50(form_g, cap_g)
                                cnt_p += 1
                        if cnt_p:
                            placebo_deltas.append(tot_x / cnt_p - tot_g / cnt_p)
                    placebo_deltas.sort()
                    if placebo_deltas:
                        pct = 100 * (sum(1 for v in placebo_deltas if v < d) + 0.5 * sum(1 for v in placebo_deltas if v == d)) / len(placebo_deltas)
                        print(f'    PLACEBO {etichetta} (N={len(placebo_deltas)}): range [{min(placebo_deltas):+.3f},{max(placebo_deltas):+.3f}] '
                              f'mediana {placebo_deltas[len(placebo_deltas)//2]:+.3f}  VERO al percentile {pct:.1f}')
                        placebo_out[f'{etichetta}_{k}'] = {'n': len(placebo_deltas), 'range': [min(placebo_deltas), max(placebo_deltas)],
                                                            'mediana': placebo_deltas[len(placebo_deltas)//2], 'percentile_vero': pct}

        print(f'  VARIANTI TOTALI PROVATE in questo giro (base={nome_base}): {varianti_provate}')

        # dump per la prima base (4f)
        if nome_base == 'allstar_u23':
            for u in unita:
                applica(u['pool_rows'], {'DEF': 0.2, 'MID': 0.2}, {'DEF': 0.2, 'MID': 0.2})
            dump_formazione(unita, 'analisi_manager/p20_livello_dump_esempio.txt')

        n_d_con, n_d_senza, n_l_con, n_l_senza = copertura_per_base[nome_base]
        esito_finale['basi'][nome_base] = {
            'n': n, 'A': a_tot, 'G': g_tot, 'delta_G_A': g_tot - a_tot,
            'copertura': {'delta_con': n_d_con, 'delta_senza': n_d_senza,
                           'livello_con': n_l_con, 'livello_senza': n_l_senza},
            'interruttore_k0': {'max_diff_d': max_diff_d, 'max_diff_l': max_diff_l},
            '3a': esiti_3a, 'ruoli_positivi_D': ruoli_pos_d, 'ruoli_positivi_L': ruoli_pos_l,
            '3b': esiti_3b, 'placebo_3b': placebo_out, 'varianti_provate': varianti_provate,
        }

    with open('analisi_manager/p20_odds_livello_assoluto_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito_finale, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_odds_livello_assoluto_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
