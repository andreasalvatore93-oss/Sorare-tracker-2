"""PASSO 1 del brief BRIEF_SONNET_GRADE_SCALA_STORICA_2026-08-08.txt --
non-arena (All Star+U23 7 carte / MLS Hot Streak 5 carte), A vs G-gruppo
(produzione) vs G-storica (media/sd del grade da p18_grade_scala_storica,
walk-forward: SOLO osservazioni con data < inizio fixture).

Riusa TUTTA l'infrastruttura gia' validata: p16_backtest_allstar_u23.py /
p17_backtest_mls_hotstreak.py (base pulita, pool, gioca_nonarena, S21/T13),
p18_grade_scala_storica.py (costruzione scala + fallback lega_ruolo/ruolo/
globale). NON reinventa la formula: atteso_combinato = atteso_cal +
sd_gruppo_atteso * z_grade, uguale in entrambi i rami -- cambia solo la
fonte di media/sd del grade (gruppo corrente vs scala storica).

1a: riproduce i numeri di p16/p17 (branch A e G-gruppo, IDENTICI).
1b: aggiunge il branch G-storica sulla STESSA base/pool/run.
1c: G-gruppo vs G-storica.
1d: PLACEBO (--placebo N) per G-gruppo e G-storica: grade permutati dentro
    ogni gruppo (lega,codice) di ogni pool (manager,GW), N ripetizioni.
1e: bootstrap sui MANAGER (cluster), non sulle formazioni.

Uso:
  python analisi_manager/p19_nonarena_grade_scala.py --base allstar_u23
  python analisi_manager/p19_nonarena_grade_scala.py --base mls_hotstreak --placebo 30
"""
import os
import sys
import io
import json
import random
import argparse
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p16_backtest_allstar_u23 as P16
import p17_backtest_mls_hotstreak as P17
import p18_grade_scala_storica as P18
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import backtest_arene_cache as CACHE
import analizza_gw as AG

cache = CACHE.CacheLocale()

BASI = {
    'allstar_u23': (P16._base_pulita, 'analisi_manager/p19_allstar_u23'),
    'mls_hotstreak': (P17._base_pulita, 'analisi_manager/p19_mls_hotstreak'),
}


def scala_per(scala, lega, ruolo):
    """Stesso fallback di build_formazione_globale._scala_storica_per, sulla
    struttura ritornata da p18.costruisci_scala()."""
    voce = scala['per_lega_ruolo'].get(f'{lega}|{ruolo}')
    if voce:
        return voce['mean'], voce['sd']
    voce = scala['per_ruolo'].get(ruolo)
    if voce:
        return voce['mean'], voce['sd']
    if scala['globale']:
        return scala['globale']['mean'], scala['globale']['sd']
    return None


def applica_storica(pool_rows, scala):
    """Aggiunge '_storica' a ogni riga: stessa sd_gruppo_atteso di _combinato,
    ma z calcolato con media/sd dalla scala storica invece che dal gruppo
    corrente."""
    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (lega, cod), membri in gruppi.items():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        voce = scala_per(scala, lega, cod)
        for m in membri:
            # '_grade' qui e' GIA' numerico (T13.costruisci_pool_rows lo
            # legge da un indice che ha gia' fatto la conversione lettera->
            # numero in fase di costruzione, S21.carica_indice_grade), MAI
            # una lettera: niente GRADE_NUM.get qui, sarebbe sempre None.
            gn = m.get('_grade')
            if voce is not None and gn is not None and voce[1] > 0:
                z = (gn - voce[0]) / voce[1]
            else:
                z = 0.0
            m['_storica'] = m['_cal'] + sd_atteso * z


def permuta_e_ricalcola(pool_rows, scala, rnd):
    """Copia le righe con _grade permutato DENTRO ogni gruppo (lega,codice),
    poi ricalcola _combinato_perm (z di gruppo sul grade permutato) e
    _storica_perm (z con media/sd storica sul grade permutato) con le
    stesse formule di _combinato/_storica. Le due permutazioni usano lo
    stesso stream random ma indipendenti chiamate a shuffle, cosi' le due
    metriche placebo non sono artificialmente correlate riga per riga."""
    rows = [dict(r) for r in pool_rows]
    gruppi = collections.defaultdict(list)
    for r in rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (lega, cod), membri in gruppi.items():
        for m in membri:
            m['_combinato_perm'] = m['_cal']
            m['_storica_perm'] = m['_cal']
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp_idx = [i for i, m in enumerate(membri) if m.get('_grade') is not None]
        gp_originali = [membri[i]['_grade'] for i in gp_idx]   # gia' numerico

        if len(gp_idx) >= 2:
            gp_perm1 = list(gp_originali)
            rnd.shuffle(gp_perm1)
            zg, _, _ = S21.zscore_gruppo(gp_perm1)
            for i, z in zip(gp_idx, zg):
                membri[i]['_combinato_perm'] = membri[i]['_cal'] + sd_atteso * z

        voce = scala_per(scala, lega, cod)
        if gp_idx and voce is not None and voce[1] > 0:
            gp_perm2 = list(gp_originali)
            rnd.shuffle(gp_perm2)
            gmean, gsd = voce
            for i, gn in zip(gp_idx, gp_perm2):
                z = (gn - gmean) / gsd
                membri[i]['_storica_perm'] = membri[i]['_cal'] + sd_atteso * z
    return rows


def realizzato(formazione, cap_row):
    return P16.realizzato_50(formazione, cap_row)


def boot_delta_manager(per_manager_vals, B=3000, seed=31):
    """Bootstrap sui MANAGER (cluster): resample manager con reinserimento,
    delta = media(G_punti - A_punti) sulle formazioni dei manager pescati."""
    rnd = random.Random(seed)
    manager_list = sorted(per_manager_vals.keys())
    n = len(manager_list)
    if n == 0:
        return None, None
    vals = []
    for _ in range(B):
        num = 0.0
        den = 0
        for _ in range(n):
            m = manager_list[rnd.randrange(n)]
            for d in per_manager_vals[m]:
                num += d
                den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if not vals:
        return None, None
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di, scala_globale, osservazioni):
    """Costruisce, per ogni (manager,GW) valida, pool_rows (con _cal,
    _combinato, _storica gia' calcolati) + slots + formazioni_valide.
    Ritorna la lista di 'unita'' (una per manager,GW) da riusare sia per il
    run reale sia per il placebo (senza dover ricostruire lo score_atteso
    ogni volta -- quello NON dipende dal grade)."""
    unita = []
    scarti = {'escluse_pool': [], 'escluse_lega': 0, 'escluse_shape': collections.Counter()}
    conta = collections.Counter()
    n_gw_totali = 0
    cache_scala_per_cutoff = {}

    for fp in files:
        manager = os.path.basename(fp)[len('manager_'):-len('.json')]
        with open(fp, encoding='utf-8') as f:
            dati = json.load(f)
        for gw, formazioni in (dati.get('giornate') or {}).items():
            n_gw_totali += 1
            non_arene = [f for f in formazioni
                        if not f.get('tipo_arena') and f.get('carte') and base_pulita_fn(f)]
            if not non_arene:
                continue
            bounds = M.parse_fixture_bounds(gw)
            if bounds is None:
                continue
            d_start, d_end = bounds

            pool, _vuote = P16.T13.costruisci_pool(formazioni, modo='globale')
            slot_totali = sum(len(f['carte']) for f in non_arene)
            if len(pool) <= slot_totali:
                scarti['escluse_pool'].append((manager, gw, len(pool), slot_totali))
                continue
            pool_rows, _scarti_r = P16.T13.costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug_full)
            if len(pool_rows) <= slot_totali:
                scarti['escluse_pool'].append((manager, gw, len(pool_rows), slot_totali))
                continue

            cutoff = d_start.isoformat()
            if cutoff not in cache_scala_per_cutoff:
                cache_scala_per_cutoff[cutoff] = P18.costruisci_scala(osservazioni, cutoff=cutoff)
            scala_wf = cache_scala_per_cutoff[cutoff]
            applica_storica(pool_rows, scala_wf)

            slots, formazioni_valide = [], []
            for f in non_arene:
                carte = f['carte']
                shape, variance = P16.shape_per_carte(len(carte))
                if shape is None:
                    scarti['escluse_shape'][len(carte)] += 1
                    continue
                if shape is P16.SHAPE_7:
                    pool_league = 'mixed'
                else:
                    pool_league = P16.lega_formazione(carte, lega_di)
                    if pool_league is None or pool_league not in {c['lega'] for c in pool_rows}:
                        scarti['escluse_lega'] += 1
                        continue
                slots.append({'competizione': f.get('competizione'), 'shape': shape,
                             'pool_league': pool_league, 'variance_mode': variance})
                formazioni_valide.append(f)
            if not slots:
                continue
            leghe_pool = sorted({c['lega'] for c in pool_rows} | {'senza_lega'})
            unita.append({'manager': manager, 'gw': gw, 'pool_rows': pool_rows,
                         'slots': slots, 'formazioni_valide': formazioni_valide,
                         'leghe_pool': leghe_pool, 'scala_wf': scala_wf})

    return unita, scarti, conta, n_gw_totali


def gioca_e_misura(unita, obiettivo_key):
    """Rigioca TUTTE le formazioni di 'unita' con la chiave obiettivo data,
    ritorna lista di dict {manager, punti} allineata a formazioni_valide."""
    out = []
    for u in unita:
        f_list = P16.gioca_nonarena(u['pool_rows'], u['slots'], obiettivo_key, u['leghe_pool'])
        for f, form in zip(u['formazioni_valide'], f_list):
            if form is None:
                out.append(None)
                continue
            cap = S21.capitano_atteso(form)
            out.append({'manager': u['manager'], 'punti': realizzato(form, cap)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', choices=list(BASI), required=True)
    ap.add_argument('--limit-manager', type=int, default=None)
    ap.add_argument('--placebo', type=int, default=0, help='numero di permutazioni placebo (0=nessuna)')
    args = ap.parse_args()

    base_pulita_fn, out_prefix = BASI[args.base]

    lega_di = AG.indice_lega()
    _idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug_full = collections.defaultdict(dict)
    for slug, entries in _idx_grade.items():
        for data, grade in entries:
            idx_per_slug_full[slug][data] = grade

    osservazioni, _scarti_oss, _data_min = P18.costruisci_osservazioni()
    scala_globale = P18.costruisci_scala(osservazioni, cutoff=None)

    import glob
    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    if args.limit_manager:
        files = files[:args.limit_manager]

    print('=' * 78)
    print(f'PASSO 1 -- {args.base} -- A vs G-gruppo vs G-storica (walk-forward)')
    print('=' * 78)

    unita, scarti, conta, n_gw_totali = raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di,
                                                 scala_globale, osservazioni)
    n_formazioni_attese = sum(len(u['formazioni_valide']) for u in unita)
    print(f'manager processati: {len(files)}   giornate totali: {n_gw_totali}')
    print(f'unita\' (manager,GW) valide: {len(unita)}   formazioni attese: {n_formazioni_attese}')
    print(f'scarti: pool<=slot={len(scarti["escluse_pool"])}  lega_non_deducibile={scarti["escluse_lega"]}  '
          f'shape_inattesa={dict(scarti["escluse_shape"])}')
    print(f'punteggi grezzi CACHE={conta["cache"]}  RICOSTRUITI={conta["fallback"]}')

    ris_A = gioca_e_misura(unita, '_cal')
    ris_G = gioca_e_misura(unita, '_combinato')
    ris_S = gioca_e_misura(unita, '_storica')

    righe = []
    for a, g, s in zip(ris_A, ris_G, ris_S):
        if a is None or g is None or s is None:
            continue
        righe.append({'manager': a['manager'], 'A': a['punti'], 'G': g['punti'], 'S': s['punti']})

    print(f'\nformazioni valutate (A, G-gruppo, G-storica tutte costruite): {len(righe)}')
    if not righe:
        print('NESSUNA riga valida. Mi fermo.')
        return

    def media(v):
        v = list(v)
        return sum(v) / len(v) if v else float('nan')

    a_tot = media(r['A'] for r in righe)
    g_tot = media(r['G'] for r in righe)
    s_tot = media(r['S'] for r in righe)

    per_manager_ga = collections.defaultdict(list)
    per_manager_sa = collections.defaultdict(list)
    per_manager_sg = collections.defaultdict(list)
    for r in righe:
        per_manager_ga[r['manager']].append(r['G'] - r['A'])
        per_manager_sa[r['manager']].append(r['S'] - r['A'])
        per_manager_sg[r['manager']].append(r['S'] - r['G'])

    lo_ga, hi_ga = boot_delta_manager(per_manager_ga)
    lo_sa, hi_sa = boot_delta_manager(per_manager_sa)
    lo_sg, hi_sg = boot_delta_manager(per_manager_sg)

    print('\n--- 1a/1b/1c: A vs G-gruppo vs G-storica (bootstrap sui MANAGER, non sulle formazioni) ---')
    print(f'n={len(righe)}  manager distinti={len(per_manager_ga)}')
    print(f'  A          = {a_tot:.2f}')
    print(f'  G-gruppo   = {g_tot:.2f}   delta G-A = {g_tot-a_tot:+.2f}  IC95=[{lo_ga:+.2f},{hi_ga:+.2f}]')
    print(f'  G-storica  = {s_tot:.2f}   delta S-A = {s_tot-a_tot:+.2f}  IC95=[{lo_sa:+.2f},{hi_sa:+.2f}]')
    print(f'  G-storica vs G-gruppo: delta S-G = {s_tot-g_tot:+.2f}  IC95=[{lo_sg:+.2f},{hi_sg:+.2f}]')

    esito = {
        'base': args.base, 'n': len(righe), 'n_manager': len(per_manager_ga),
        'A': a_tot, 'G_gruppo': g_tot, 'G_storica': s_tot,
        'delta_G_A': g_tot - a_tot, 'ic_G_A': [lo_ga, hi_ga],
        'delta_S_A': s_tot - a_tot, 'ic_S_A': [lo_sa, hi_sa],
        'delta_S_G': s_tot - g_tot, 'ic_S_G': [lo_sg, hi_sg],
    }

    # --- 1d: placebo ---
    if args.placebo > 0:
        print(f'\n--- 1d: PLACEBO ({args.placebo} permutazioni) ---')
        deltas_ga_placebo = []
        deltas_sa_placebo = []
        for seed in range(args.placebo):
            rnd = random.Random(50000 + seed)
            tot_g = 0.0
            tot_s = 0.0
            n_g = 0
            n_s = 0
            for u in unita:
                rows_perm = permuta_e_ricalcola(u['pool_rows'], u['scala_wf'], rnd)
                f_g = P16.gioca_nonarena(rows_perm, u['slots'], '_combinato_perm', u['leghe_pool'])
                f_s = P16.gioca_nonarena(rows_perm, u['slots'], '_storica_perm', u['leghe_pool'])
                for form_g in f_g:
                    if form_g is not None:
                        cap = S21.capitano_atteso(form_g)
                        tot_g += realizzato(form_g, cap)
                        n_g += 1
                for form_s in f_s:
                    if form_s is not None:
                        cap = S21.capitano_atteso(form_s)
                        tot_s += realizzato(form_s, cap)
                        n_s += 1
            media_g_placebo = tot_g / n_g if n_g else float('nan')
            media_s_placebo = tot_s / n_s if n_s else float('nan')
            deltas_ga_placebo.append(media_g_placebo - a_tot)
            deltas_sa_placebo.append(media_s_placebo - a_tot)

        deltas_ga_placebo.sort()
        deltas_sa_placebo.sort()

        def percentile(vals, x):
            n = len(vals)
            sotto = sum(1 for v in vals if v < x)
            uguale = sum(1 for v in vals if v == x)
            return 100 * (sotto + 0.5 * uguale) / n

        pct_ga = percentile(deltas_ga_placebo, g_tot - a_tot)
        pct_sa = percentile(deltas_sa_placebo, s_tot - a_tot)
        print(f'  G-gruppo:  placebo delta [{min(deltas_ga_placebo):+.2f},{max(deltas_ga_placebo):+.2f}] '
              f'mediana {deltas_ga_placebo[len(deltas_ga_placebo)//2]:+.2f}')
        print(f'    G VERO ({g_tot-a_tot:+.2f}) sta al percentile {pct_ga:.1f} del placebo')
        print(f'  G-storica: placebo delta [{min(deltas_sa_placebo):+.2f},{max(deltas_sa_placebo):+.2f}] '
              f'mediana {deltas_sa_placebo[len(deltas_sa_placebo)//2]:+.2f}')
        print(f'    S VERO ({s_tot-a_tot:+.2f}) sta al percentile {pct_sa:.1f} del placebo')
        esito['placebo_n'] = args.placebo
        esito['placebo_pct_G'] = pct_ga
        esito['placebo_pct_S'] = pct_sa
        esito['placebo_deltas_G'] = deltas_ga_placebo
        esito['placebo_deltas_S'] = deltas_sa_placebo

    with open(f'{out_prefix}_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito, fh, ensure_ascii=False, indent=2)
    print(f'\nsalvato {out_prefix}_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
