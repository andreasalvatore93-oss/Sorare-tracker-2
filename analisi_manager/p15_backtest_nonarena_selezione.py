"""PASSO 1 del brief BRIEF_SONNET_RIVALIDAZIONE_G_2026-08-07.txt -- selezione
pura (A vs G) sulle competizioni SENZA soglia (In Season/Hot Streak/
Challenger/Contender/Champion/All Star/Under 23...), su TUTTI i manager e
TUTTE le giornate in dati_globali/manager_*.json.

Riusa l'infrastruttura di p13_backtest_gw_crowss.py (pool globale = tutte le
carte possedute quel giorno, grezzo da cache game-log mai da divisione,
grade con la stessa finestra di p12/p13) e S21.bfg.build_one_lineup_with_growth
(mai un knapsack scritto per l'occasione, D7 CLAUDE.md).

SHAPE: dedotta dal numero di carte REALMENTE schierate dal manager in quella
competizione (verificato sui dati: sempre 5 o 7), non da una tabella a mano:
  5 carte -> GK+DEF+MID+FWD+1 extra(D/M/F), stile MLS_IN_SEASON, variance_mode=False
  7 carte -> GK+2DEF+2MID+1FWD+1 extra(D/M/F), stile ALLSTARS, variance_mode=True
Captain bonus fuori arena = +50% (CAPTAIN_BONUS_BY_TYPE di produzione).

POOL_LEAGUE: per le competizioni 7-carte (All Star/Under23/Champion, mai
un'unica lega reale) si usa 'mixed' (tutte le leghe della giornata, come
ALLSTARS/ALLSTARS_U23 di produzione). Per le 5-carte (In Season di UNA lega)
si usa la lega maggioritaria delle carte REALI di quella formazione (via
analizza_gw.indice_lega); se non deducibile, si scarta la formazione (contata).

CONTROLLO OBBLIGATORIO (CLAUDE.md, esteso qui alle non-arena su richiesta
esplicita 07/08): per ogni giornata/manager, il pool (tutte le carte
possedute quel giorno, stesso pool di p13 Test1) deve essere piu' grande
degli slot non-arena da riempire quel giorno. Le giornate che NON passano
sono ESCLUSE dal confronto e elencate a parte.

Uso:
  python analisi_manager/p15_backtest_nonarena_selezione.py [--limit-manager N]
"""
import os
import sys
import io
import json
import glob
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

import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import p13_backtest_gw_crowss as T13
import analizza_gw as AG

cache = CACHE.CacheLocale()

SHAPE_5 = {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1}
SHAPE_7 = {'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None}
CAP_BONUS_FUORI = 0.5


def realizzato_50(formazione, cap_row):
    return sum(r['reale'] for _s, r, _t in formazione) + (CAP_BONUS_FUORI) * (cap_row['reale'] if cap_row else 0.0)


def gioca_nonarena(pool_rows, slots, obiettivo_key, leghe):
    """slots: lista di dict {competizione, shape, pool_league, variance_mode}.
    Stesso schema di S21.costruisci ma senza fissare bfg.LEAGUES a slots arena."""
    gw_data = {'pool': pool_rows}
    role_data, pools, card_pool, leghe_pool = S21.costruisci(gw_data, lambda c: c[obiettivo_key])
    orig = S21.bfg.LEAGUES
    S21.bfg.LEAGUES = tuple(leghe_pool)
    out = []
    try:
        for s in slots:
            stato = S21.bfg._istantanea_pool(card_pool)
            formazione, errore, _ok, _sp = S21.bfg.build_one_lineup_with_growth(
                s['shape'], s['pool_league'], role_data, pools, card_pool, None,
                apply_stack_guard=False, variance_mode=s['variance_mode'],
                apply_positive_synergy=False, strict_gk_anti_synergy=False)
            if errore or not formazione:
                S21.bfg._ripristina_pool(card_pool, stato)
                out.append(None)
                continue
            out.append(formazione)
    finally:
        S21.bfg.LEAGUES = orig
    return out


def shape_per_carte(n):
    if n == 5:
        return SHAPE_5, False
    if n == 7:
        return SHAPE_7, True
    return None, None


def lega_formazione(carte, lega_di):
    leghe = collections.Counter(lega_di.get(c.get('slug')) for c in carte if lega_di.get(c.get('slug')))
    if not leghe:
        return None
    return leghe.most_common(1)[0][0]


def boot_delta(unita_list, ka, kb, B=3000, seed=17):
    rnd = random.Random(seed)
    n = len(unita_list)
    if n == 0:
        return None, None
    vals = []
    for _ in range(B):
        num = 0.0; den = 0
        for _ in range(n):
            g = unita_list[rnd.randrange(n)]
            for r in g:
                num += r[kb] - r[ka]; den += 1
        if den:
            vals.append(num / den)
    vals.sort()
    if not vals:
        return None, None
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit-manager', type=int, default=None)
    ap.add_argument('--dump', default='analisi_manager/p15_dump_esempio.txt')
    args = ap.parse_args()

    lega_di = AG.indice_lega()
    # FIX bug reale trovato in T13.prepara_righe_pool: carica_indice_grade_esteso()
    # ritorna slug -> lista (data,grade), non (slug,data) -> grade; il ciclo
    # 'for (slug, data), grade in idx_grade.items()' di T13 va in ValueError
    # SEMPRE (verificato: fallisce anche con pool vuoto). Qui si ricostruisce
    # idx_per_slug nel formato giusto una volta sola, fuori dal loop per non
    # ricaricare gli storici a ogni giornata.
    _idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug_full = collections.defaultdict(dict)
    for slug, entries in _idx_grade.items():
        for data, grade in entries:
            idx_per_slug_full[slug][data] = grade

    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    if args.limit_manager:
        files = files[:args.limit_manager]

    righe = []           # una per formazione non-arena valutata (A e G)
    escluse_pool = []    # (manager, gw) escluse per pool<=slot
    escluse_lega = 0
    escluse_shape = collections.Counter()
    conta = collections.Counter()
    n_gw_totali = 0
    dump_scritto = False

    for fp in files:
        manager = os.path.basename(fp)[len('manager_'):-len('.json')]
        with open(fp, encoding='utf-8') as f:
            dati = json.load(f)
        gws = dati.get('giornate') or {}
        for gw, formazioni in gws.items():
            n_gw_totali += 1
            non_arene = [f for f in formazioni if not f.get('tipo_arena') and f.get('carte')]
            if not non_arene:
                continue
            bounds = M.parse_fixture_bounds(gw)
            if bounds is None:
                continue
            d_start, d_end = bounds

            pool, vuote = T13.costruisci_pool(formazioni, modo='globale')
            slot_totali = sum(len(f['carte']) for f in non_arene)
            if len(pool) <= slot_totali:
                escluse_pool.append((manager, gw, len(pool), slot_totali))
                continue

            pool_rows, scarti = T13.costruisci_pool_rows(pool, d_start, d_end, conta, lega_di, idx_per_slug_full)
            if len(pool_rows) <= slot_totali:
                escluse_pool.append((manager, gw, len(pool_rows), slot_totali))
                continue
            riga_per_carta = {r['carta']: r for r in pool_rows}

            slots, formazioni_valide = [], []
            for f in non_arene:
                carte = f['carte']
                shape, variance = shape_per_carte(len(carte))
                if shape is None:
                    escluse_shape[len(carte)] += 1
                    continue
                if shape is SHAPE_7:
                    pool_league = 'mixed'
                else:
                    pool_league = lega_formazione(carte, lega_di)
                    if pool_league is None or pool_league not in {c['lega'] for c in pool_rows}:
                        escluse_lega += 1
                        continue
                slots.append({'competizione': f.get('competizione'), 'shape': shape,
                             'pool_league': pool_league, 'variance_mode': variance})
                formazioni_valide.append(f)

            if not slots:
                continue
            leghe_pool = sorted({c['lega'] for c in pool_rows} | {'senza_lega'})
            fa = gioca_nonarena(pool_rows, slots, '_cal', leghe_pool)
            fg = gioca_nonarena(pool_rows, slots, '_combinato', leghe_pool)

            for f, s, la, lg_ in zip(formazioni_valide, slots, fa, fg):
                if la is None or lg_ is None:
                    continue
                ca = S21.capitano_atteso(la)
                cg = S21.capitano_atteso(lg_)
                pa = realizzato_50(la, ca)
                pg = realizzato_50(lg_, cg)
                sa = set(r['slug'] for _x, r, _t in la)
                sg = set(r['slug'] for _x, r, _t in lg_)
                reale_tot = sum(riga_per_carta[c.get('carta')]['reale'] for c in f['carte']
                               if riga_per_carta.get(c.get('carta')))
                righe.append({
                    'manager': manager, 'gw': gw, 'competizione': s['competizione'],
                    'n_carte': len(f['carte']), 'A_punti': pa, 'G_punti': pg,
                    'reale_punti': reale_tot, 'identiche': sa == sg,
                    'overlap': len(sa & sg),
                })

            if not dump_scritto and righe:
                with open(args.dump, 'w', encoding='utf-8') as fh:
                    fh.write(f'DUMP ESEMPIO -- {manager} {gw} (non-arena, Passo 1)\n\n')
                    for f, s, la, lg_ in zip(formazioni_valide, slots, fa, fg):
                        fh.write(f"--- {s['competizione']} (shape {len(f['carte'])} carte, "
                                f"pool_league={s['pool_league']}) ---\n")
                        fh.write('  REALE:\n')
                        for c in f['carte']:
                            r = riga_per_carta.get(c.get('carta'))
                            cap = '  [CAPITANO]' if c.get('capitano') else ''
                            fh.write(f"    {c.get('ruolo','?'):11} {c.get('nome','?'):24} "
                                    f"grezzo={r['reale'] if r else float('nan'):7.2f}{cap}\n")
                        for label, form in (('A', la), ('G', lg_)):
                            if form is None:
                                fh.write(f'  {label}: NON COSTRUITA\n')
                                continue
                            cap_row = S21.capitano_atteso(form)
                            fh.write(f"  {label}:\n")
                            for _x, r, _t in form:
                                cap = '  [CAPITANO]' if cap_row and r['slug'] == cap_row['slug'] else ''
                                fh.write(f"    {r['role_key']:4} {r['slug']:24} "
                                        f"grezzo={r['reale']:7.2f} grade={r.get('_grade')}{cap}\n")
                        fh.write('\n')
                    fh.write(f'\nPOOL quel giorno: {len(pool_rows)} carte, slot non-arena: {slot_totali}\n')
                dump_scritto = True

    print('=' * 72)
    print('PASSO 1 -- SELEZIONE PURA SU COMPETIZIONI SENZA SOGLIA')
    print('=' * 72)
    print(f'manager processati: {len(files)}   giornate totali (tutti i manager): {n_gw_totali}')
    print(f'giornate ESCLUSE per pool<=slot (nessuna scorta): {len(escluse_pool)}')
    for m, gw, np_, ns in escluse_pool[:40]:
        print(f'    {m:16s} {gw:32s} pool={np_:4d} slot={ns:4d}')
    if len(escluse_pool) > 40:
        print(f'    ... e altre {len(escluse_pool)-40}')
    print(f'formazioni scartate per lega non deducibile: {escluse_lega}')
    print(f"formazioni scartate per shape inattesa (ne' 5 ne' 7 carte): {dict(escluse_shape)}")
    print(f'punteggi grezzi da CACHE: {conta["cache"]}   RICOSTRUITI (fallback): {conta["fallback"]}')
    print()
    print(f'formazioni valutate (A e G costruite): {len(righe)}')
    if not righe:
        print('NESSUNA riga valida. Mi fermo.')
        return

    ident = sum(1 for r in righe if r['identiche'])
    print(f'formazioni IDENTICHE fra A e G: {ident}/{len(righe)} ({100*ident/len(righe):.1f}%)')
    print(f'overlap medio (carte in comune): {sum(r["overlap"] for r in righe)/len(righe):.3f} '
          f'(su n_carte variabile 5 o 7)')

    def media(v):
        v = list(v)
        return sum(v) / len(v) if v else float('nan')

    print('\n--- per famiglia di competizione ---')
    per_fam = collections.defaultdict(list)
    for r in righe:
        per_fam[r['competizione']].append(r)
    print(f'{"competizione":30s} {"n":>5s} {"A":>8s} {"G":>8s} {"delta":>8s} {"IC95":>18s} {"%ident":>7s}')
    tot_riepilogo = []
    for comp, rs in sorted(per_fam.items(), key=lambda kv: -len(kv[1])):
        a = media(r['A_punti'] for r in rs)
        g = media(r['G_punti'] for r in rs)
        d = g - a
        unita = [[r] for r in rs]  # unita' = singola formazione (manager*gw*comp gia' distinti)
        lo, hi = boot_delta(unita, 'A_punti', 'G_punti')
        pct_id = 100 * sum(1 for r in rs if r['identiche']) / len(rs)
        lo_s = f'{lo:+.2f}' if lo is not None else 'n/a'
        hi_s = f'{hi:+.2f}' if hi is not None else 'n/a'
        print(f'{comp:30s} {len(rs):5d} {a:8.2f} {g:8.2f} {d:+8.2f} [{lo_s},{hi_s}] {pct_id:6.1f}%')
        tot_riepilogo.append((comp, len(rs), a, g, d, lo, hi, pct_id))

    print('\n--- TOTALE aggregato (tutte le famiglie insieme) ---')
    a_tot = media(r['A_punti'] for r in righe)
    g_tot = media(r['G_punti'] for r in righe)
    unita_tot = [[r] for r in righe]
    lo_t, hi_t = boot_delta(unita_tot, 'A_punti', 'G_punti')
    print(f'n={len(righe)}  A={a_tot:.2f}  G={g_tot:.2f}  delta={g_tot-a_tot:+.2f}  '
          f'IC95=[{lo_t:+.2f},{hi_t:+.2f}]  identiche={100*ident/len(righe):.1f}%')

    with open('analisi_manager/p15_backtest_nonarena_out.json', 'w', encoding='utf-8') as fh:
        json.dump({
            'n_gw_totali': n_gw_totali, 'n_escluse_pool': len(escluse_pool),
            'escluse_pool': [{'manager': m, 'gw': gw, 'pool': p, 'slot': s} for m, gw, p, s in escluse_pool],
            'escluse_lega': escluse_lega, 'escluse_shape': dict(escluse_shape),
            'righe': righe,
            'per_famiglia': [{'competizione': c, 'n': n, 'A': a, 'G': g, 'delta': d,
                             'ic_lo': lo, 'ic_hi': hi, 'pct_identiche': pi}
                            for c, n, a, g, d, lo, hi, pi in tot_riepilogo],
        }, fh, ensure_ascii=False)
    print('\nsalvato analisi_manager/p15_backtest_nonarena_out.json')
    print(f'dump leggibile: {args.dump}')


if __name__ == '__main__':
    sys.exit(main())
