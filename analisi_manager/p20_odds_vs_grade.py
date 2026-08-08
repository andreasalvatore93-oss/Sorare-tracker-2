"""BRIEF_SONNET_ODDS_SEGNALE_DOPO_G_2026-08-08.txt -- le favorito-odds
aggiungono qualcosa SOPRA G (grade, gia' in produzione) o G ha gia' preso
quel posto? Riusa TUTTA l'infrastruttura di p19_nonarena_grade_scala.py
(base pulita non-arena, pool_rows, bootstrap sui manager, placebo) SENZA
modificarla: import diretto, nessuna riscrittura del knapsack (D7 CLAUDE.md).

Rami sullo stesso pool_rows/formazioni:
  A    = _cal (produzione, nessun segnale)               [gia' in p19]
  G    = _combinato (grade sopra produzione, PRODUZIONE OGGI)  [gia' in p19]
  O    = _odds_cal (favorito-odds applicato PRIMA della calibrazione,
         poi ricalibrato con bfg.calibra -- stesso punto della catena di
         p11_favorito_odds_confronto.py)
  G+O  = _odds_combinato (grade sommato sopra _odds_cal, stessa formula additiva
         di _combinato: _odds_cal + sd_gruppo(_odds_cal)*_zgrade -- _zgrade
         e' gia' calcolato da T13.costruisci_pool_rows e NON dipende dalla
         base a cui si somma, solo dai valori di grade)

Nessuna modifica alla produzione. Nessun commit di file diversi da questo.
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


def annota_delta_odds(unita, cache):
    """Per ogni riga di ogni pool_rows, calcola _delta_odds usando la data
    di FINE della giornata (stessa approssimazione di p11: data PARTITA, non
    cutoff -- qui non abbiamo la data della singola partita del giocatore
    dentro la finestra, solo i bound d_start/d_end della giornata)."""
    n_con = n_senza = 0
    for u in unita:
        bounds = M.parse_fixture_bounds(u['gw'])
        d_start, d_end = bounds
        fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
        for r in u['pool_rows']:
            d = delta_per_carta(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
            r['_delta_odds'] = d
            if d is None:
                n_senza += 1
            else:
                n_con += 1
    return n_con, n_senza


def applica_odds(pool_rows, policy):
    """policy: dict codice -> k (float). k assente o 0 => nessun aggiustamento
    (riga identica a _cal, controllo 5c). Scrive _odds_cal e _odds_combinato
    (grade sommato sopra, stessa formula additiva di _combinato)."""
    for r in pool_rows:
        k = policy.get(r['codice']) or 0.0
        d = r.get('_delta_odds')
        if k and d is not None:
            raw_adj = r['atteso_raw'] * (1.0 + k * d)
        else:
            raw_adj = r['atteso_raw']
        r['_odds_cal'] = S21.bfg.calibra(raw_adj, r['codice'])

    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        _z, sd_odds, _m = S21.zscore_gruppo([m['_odds_cal'] for m in membri])
        for m in membri:
            m['_odds_combinato'] = m['_odds_cal'] + sd_odds * m.get('_zgrade', 0.0)


def permuta_odds_e_ricalcola(pool_rows, policy, rnd):
    """Placebo: permuta _delta_odds DENTRO ogni gruppo (lega,codice), poi
    ricalcola _odds_cal_perm/_odds_combinato_perm con le stesse formule."""
    rows = [dict(r) for r in pool_rows]
    gruppi = collections.defaultdict(list)
    for r in rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, cod), membri in gruppi.items():
        k = policy.get(cod) or 0.0
        idx_con = [i for i, m in enumerate(membri) if m.get('_delta_odds') is not None]
        deltas = [membri[i]['_delta_odds'] for i in idx_con]
        if k and len(idx_con) >= 2:
            perm = list(deltas)
            rnd.shuffle(perm)
            for i, d in zip(idx_con, perm):
                membri[i]['_odds_cal_perm'] = S21.bfg.calibra(membri[i]['atteso_raw'] * (1.0 + k * d), cod)
        for m in membri:
            if '_odds_cal_perm' not in m:
                m['_odds_cal_perm'] = S21.bfg.calibra(m['atteso_raw'], cod)
        _z, sd_odds, _m = S21.zscore_gruppo([m['_odds_cal_perm'] for m in membri])
        for m in membri:
            m['_odds_combinato_perm'] = m['_odds_cal_perm'] + sd_odds * m.get('_zgrade', 0.0)
    return rows


def gioca_e_misura(unita, key):
    return P19.gioca_e_misura(unita, key)


def righe_delta(ris_x, ris_a):
    righe = []
    for x, a in zip(ris_x, ris_a):
        if x is None or a is None:
            continue
        righe.append({'manager': a['manager'], 'X': x['punti'], 'A': a['punti']})
    return righe


def media(v):
    v = list(v)
    return sum(v) / len(v) if v else float('nan')


def delta_vs(unita, key_x, key_ref, ris_ref):
    ris_x = gioca_e_misura(unita, key_x)
    per_manager = collections.defaultdict(list)
    tot_x = tot_ref = n = 0.0
    cnt = 0
    for x, r in zip(ris_x, ris_ref):
        if x is None or r is None:
            continue
        per_manager[x['manager']].append(x['punti'] - r['punti'])
        tot_x += x['punti']; tot_ref += r['punti']; cnt += 1
    d = (tot_x - tot_ref) / cnt if cnt else float('nan')
    lo, hi = P19.boot_delta_manager(per_manager)
    return d, lo, hi, cnt, ris_x


# --------------------------------------------------------------- Passo 0
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


def passo0(unita_tutte):
    print('=' * 78)
    print('PASSO 0 -- grade vs delta_favorito_odds: sono lo stesso segnale?')
    print('=' * 78)
    per_cod = collections.defaultdict(lambda: ([], []))
    viste = set()
    for u in unita_tutte:
        for r in u['pool_rows']:
            carta = r.get('carta')
            if carta in viste:
                continue
            viste.add(carta)
            g, d = r.get('_grade'), r.get('_delta_odds')
            if g is None or d is None:
                continue
            per_cod[r['codice']][0].append(g)
            per_cod[r['codice']][1].append(d)
            per_cod['GLOBALE'][0].append(g)
            per_cod['GLOBALE'][1].append(d)
    esito0 = {}
    for cod in ('GK', 'DEF', 'MID', 'FWD', 'GLOBALE'):
        xs, ys = per_cod.get(cod, ([], []))
        r = pearson(xs, ys)
        print(f'  {cod:8s} n={len(xs):5d}  corr(grade,delta_odds) = {r if r is None else round(r,3)}')
        esito0[cod] = {'n': len(xs), 'corr': r}

    print('\n  tabella incrociata (globale): grade medio per fascia di favorito-odds')
    xs, ys = per_cod['GLOBALE']
    fasce = [(-1e9, -0.15, 'molto sfavorita'), (-0.15, -0.03, 'sfavorita'),
             (-0.03, 0.03, 'neutra'), (0.03, 0.15, 'favorita'), (0.15, 1e9, 'molto favorita')]
    for lo, hi, nome in fasce:
        gs = [g for g, d in zip(xs, ys) if lo <= d < hi]
        print(f'    {nome:18s} [{lo:+.2f},{hi:+.2f})  n={len(gs):5d}  grade medio={media(gs):+.3f}' if gs else
              f'    {nome:18s} n=0')

    print('\n  per RUOLO, tabella incrociata GK separata (ipotesi utente: verso opposto sui GK)')
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        xs_c, ys_c = per_cod.get(cod, ([], []))
        if not xs_c:
            continue
        print(f'  -- {cod} --')
        for lo, hi, nome in fasce:
            gs = [g for g, d in zip(xs_c, ys_c) if lo <= d < hi]
            if gs:
                print(f'    {nome:18s} n={len(gs):4d}  grade medio={media(gs):+.3f}')
    return esito0


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
    for nome_base, (base_pulita_fn, out_prefix) in BASI.items():
        unita, scarti, conta, n_gw = P19.raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di,
                                                    scala_globale, osservazioni)
        print(f'[{nome_base}] unita valide: {len(unita)}  formazioni: {sum(len(u["formazioni_valide"]) for u in unita)}')
        cache = P19.cache
        n_con, n_senza = annota_delta_odds(unita, cache)
        print(f'[{nome_base}] carte con delta_favorito_odds: righe-con={n_con} righe-senza(=0 effetto)={n_senza}')
        unita_per_base[nome_base] = unita

    tutte_unita = [u for lst in unita_per_base.values() for u in lst]
    esito0 = passo0(tutte_unita)

    esito_finale = {'passo0': esito0, 'basi': {}}

    for nome_base, unita in unita_per_base.items():
        print('\n' + '=' * 78)
        print(f'PASSO 3 -- {nome_base}')
        print('=' * 78)
        ris_A = gioca_e_misura(unita, '_cal')
        ris_G = gioca_e_misura(unita, '_combinato')
        n = sum(1 for a, g in zip(ris_A, ris_G) if a and g)
        a_tot = media(x['punti'] for x in ris_A if x)
        g_tot = media(x['punti'] for x in ris_G if x)
        print(f'  CONTROLLO 5a -- A={a_tot:.2f} G={g_tot:.2f} delta G-A={g_tot-a_tot:+.2f} (n={n})')

        # 3a: un ruolo alla volta, k=0.2, G+O vs G
        varianti_provate = 0
        esiti_3a = {}
        ruoli_positivi = []
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            policy = {cod: 0.2}
            for u in unita:
                applica_odds(u['pool_rows'], policy)
            varianti_provate += 1
            d, lo, hi, cnt, ris_go = delta_vs(unita, '_odds_combinato', '_combinato', ris_G)
            _do, _lo2, _hi2, _c2, ris_o = delta_vs(unita, '_odds_cal', '_cal', ris_A)
            print(f'  3a [{cod} k=0.2]  G+O vs G: delta={d:+.3f} IC95=[{lo:+.3f},{hi:+.3f}] n={cnt}   '
                  f'(O vs A: {_do:+.3f})')
            esiti_3a[cod] = {'delta_GO_vs_G': d, 'ic': [lo, hi], 'n': cnt, 'delta_O_vs_A': _do}
            if lo is not None and lo > 0:
                ruoli_positivi.append(cod)

        print(f'  ruoli con IC95 tutto positivo (G+O batte G) a k=0.2: {ruoli_positivi or "nessuno"}')

        # 3b: combina i ruoli positivi, prova k in {0.1,0.2,0.3}
        esiti_3b = {}
        placebo_out = {}
        if ruoli_positivi:
            for k in (0.1, 0.2, 0.3):
                policy = {cod: k for cod in ruoli_positivi}
                for u in unita:
                    applica_odds(u['pool_rows'], policy)
                varianti_provate += 1
                d, lo, hi, cnt, ris_go = delta_vs(unita, '_odds_combinato', '_combinato', ris_G)
                print(f'  3b [{"+".join(ruoli_positivi)} k={k}]  G+O vs G: delta={d:+.3f} '
                      f'IC95=[{lo:+.3f},{hi:+.3f}] n={cnt}')
                esiti_3b[str(k)] = {'delta_GO_vs_G': d, 'ic': [lo, hi], 'n': cnt}

                if lo is not None and lo > 0 and args.placebo > 0:
                    rnd = random.Random(70000)
                    placebo_deltas = []
                    for seed in range(args.placebo):
                        rnd = random.Random(70000 + seed)
                        tot_go = 0.0; tot_g = 0.0; cnt_p = 0
                        for u in unita:
                            rows_perm = permuta_odds_e_ricalcola(u['pool_rows'], policy, rnd)
                            f_go = P16.gioca_nonarena(rows_perm, u['slots'], '_odds_combinato_perm', u['leghe_pool'])
                            f_g = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_combinato', u['leghe_pool'])
                            for form_go, form_g in zip(f_go, f_g):
                                if form_go is None or form_g is None:
                                    continue
                                cap_go = S21.capitano_atteso(form_go)
                                cap_g = S21.capitano_atteso(form_g)
                                tot_go += P16.realizzato_50(form_go, cap_go)
                                tot_g += P16.realizzato_50(form_g, cap_g)
                                cnt_p += 1
                        if cnt_p:
                            placebo_deltas.append(tot_go / cnt_p - tot_g / cnt_p)
                    placebo_deltas.sort()
                    if placebo_deltas:
                        pct = 100 * (sum(1 for v in placebo_deltas if v < d) + 0.5 * sum(1 for v in placebo_deltas if v == d)) / len(placebo_deltas)
                        print(f'    PLACEBO (N={len(placebo_deltas)}): range [{min(placebo_deltas):+.3f},{max(placebo_deltas):+.3f}] '
                              f'mediana {placebo_deltas[len(placebo_deltas)//2]:+.3f}  VERO al percentile {pct:.1f}')
                        placebo_out[str(k)] = {'n': len(placebo_deltas), 'range': [min(placebo_deltas), max(placebo_deltas)],
                                                'mediana': placebo_deltas[len(placebo_deltas)//2], 'percentile_vero': pct}

        print(f'  VARIANTI TOTALI PROVATE in questo giro (base={nome_base}): {varianti_provate}')

        esito_finale['basi'][nome_base] = {
            'n': n, 'A': a_tot, 'G': g_tot, 'delta_G_A': g_tot - a_tot,
            '3a': esiti_3a, 'ruoli_positivi_k02': ruoli_positivi, '3b': esiti_3b,
            'placebo_3b': placebo_out, 'varianti_provate': varianti_provate,
        }

    with open('analisi_manager/p20_odds_vs_grade_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito_finale, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_odds_vs_grade_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
