"""Controlli integrativi richiesti da BRIEF_SONNET_ODDS_CONTROLLI_MANCANTI_
2026-08-08.txt su p20_odds_vs_grade.py. NON rifa' il test: misura
sull'infrastruttura gia' scritta.

1. interruttore: k=0 -> O identico ad A (esatto); k=0.2 -> quante carte
   cambiano atteso e di quanto; quante formazioni cambiano almeno una carta
   fra G e G+O.
2. copertura: denominatore totale delta_favorito_odds disponibile/mancante,
   per ruolo, con motivo e 3 esempi.
3. dump leggibile di una formazione completa (A/G/O/G+O).

Nessuna modifica alla produzione. Nessuna variante nuova di k.
"""
import os
import sys
import io
import json
import glob
import collections
import datetime

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p20_odds_vs_grade as P20
import p16_backtest_allstar_u23 as P16
import p17_backtest_mls_hotstreak as P17
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import backtest_arene_previsioni as prev

RUOLO_FULL = P20.RUOLO_FULL


def categorizza_mancante(cache, slug, ruolo_full, fine):
    if ruolo_full not in prev._MODULO:
        return 'ruolo_non_supportato'
    target = prev.partita_target(cache, slug, fine)
    if target is None:
        return 'nessuna_partita_in_finestra_6gg'
    cutoff = prev._data(target)
    competizione = ((target['anyGame'].get('competition') or {}).get('slug'))
    usable, _pres = prev.finestra_storica(cache, slug, cutoff, competizione)
    if not usable:
        return 'storia_non_usabile'
    try:
        ctx = prev.contesto(cache, slug, ruolo_full, fine)
    except Exception:
        return 'eccezione_contesto'
    if ctx is None:
        return 'contesto_none_altro'
    squadra, opp = ctx.get('squadra'), ctx.get('opp_slug')
    ora = prev._p_own_opp_odds(squadra, opp, ctx.get('cutoff'))
    if ora is None:
        return 'quote_partita_corrente_mancanti'
    storici = [prev._p_own_opp_odds(squadra, oh, dh)
               for oh, dh in zip(ctx['s'].get('opp_slug') or [], ctx['s'].get('date') or [])]
    n_storici = sum(1 for v in storici if v is not None)
    if n_storici < 5:
        return f'meno_di_5_partite_storiche_con_quote(n={n_storici})'
    return 'ignoto'


def main():
    lega_di = P20.P19.AG.indice_lega()
    _idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug_full = collections.defaultdict(dict)
    for slug, entries in _idx_grade.items():
        for data, grade in entries:
            idx_per_slug_full[slug][data] = grade
    osservazioni, _s, _d = P20.P19.P18.costruisci_osservazioni()
    scala_globale = P20.P19.P18.costruisci_scala(osservazioni, cutoff=None)

    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))

    cache = P20.P19.cache
    unita_per_base = {}
    for nome_base, (base_pulita_fn, _out) in P20.BASI.items():
        unita, _scarti, _conta, _n_gw = P20.P19.raccogli(
            base_pulita_fn, files, idx_per_slug_full, lega_di, scala_globale, osservazioni)
        P20.annota_delta_odds(unita, cache)
        unita_per_base[nome_base] = unita

    out = {}

    # ------------------------------------------------------------ Controllo 1
    print('=' * 78)
    print('CONTROLLO 1 -- interruttore (k=0 esatto, k=0.2 movimento, formazioni)')
    print('=' * 78)
    out['controllo1'] = {}
    for nome_base, unita in unita_per_base.items():
        print(f'\n-- {nome_base} --')
        # 1a: k=0 su tutti i ruoli -> _odds_cal deve essere ESATTAMENTE _cal
        policy0 = {}
        for u in unita:
            P20.applica_odds(u['pool_rows'], policy0)
        n_righe = 0
        n_diff = 0
        max_diff_aa = 0.0
        for u in unita:
            for r in u['pool_rows']:
                n_righe += 1
                d = abs(r['_odds_cal'] - r['_cal'])
                if d > 0:
                    n_diff += 1
                    max_diff_aa = max(max_diff_aa, d)
        print(f'  1a k=0: righe totali={n_righe}  righe con _odds_cal != _cal={n_diff}  '
              f'(atteso: 0)  max_diff={max_diff_aa:.10f}')
        esatto = (n_diff == 0)
        print(f'  1a ESITO: {"COINCIDE ESATTAMENTE" if esatto else "NON COINCIDE -- BUG"}')

        # 1b/1c per ciascuno dei 4 ruoli a k=0.2 (stessa policy di 3a)
        out['controllo1'][nome_base] = {'1a_esatto': esatto, '1a_max_diff': max_diff_aa, 'ruoli': {}}
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            policy = {cod: 0.2}
            for u in unita:
                P20.applica_odds(u['pool_rows'], policy)

            n_carte_ruolo = 0
            n_cambiate = 0
            scarti = []
            for u in unita:
                for r in u['pool_rows']:
                    if r['codice'] != cod:
                        continue
                    n_carte_ruolo += 1
                    diff = r['_odds_cal'] - r['_cal']
                    if abs(diff) > 1e-9:
                        n_cambiate += 1
                        scarti.append(abs(diff))
            scarti.sort()
            mediana = scarti[len(scarti) // 2] if scarti else 0.0
            massimo = scarti[-1] if scarti else 0.0
            print(f'  1b [{cod} k=0.2]  carte di questo ruolo: {n_carte_ruolo}  '
                  f'carte con atteso cambiato: {n_cambiate} ({100*n_cambiate/n_carte_ruolo:.1f}%)  '
                  f'scostamento mediano={mediana:.3f}  massimo={massimo:.3f}')

            # 1c: quante formazioni cambiano almeno una carta fra G e G+O
            n_form_valutate = 0
            n_form_cambiate = 0
            for u in unita:
                f_g = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_combinato', u['leghe_pool'])
                f_go = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_odds_combinato', u['leghe_pool'])
                for fg, fgo in zip(f_g, f_go):
                    if fg is None or fgo is None:
                        continue
                    n_form_valutate += 1
                    sg = set(r['slug'] for _x, r, _t in fg)
                    sgo = set(r['slug'] for _x, r, _t in fgo)
                    if sg != sgo:
                        n_form_cambiate += 1
            pct = 100 * n_form_cambiate / n_form_valutate if n_form_valutate else 0.0
            print(f'  1c [{cod} k=0.2]  formazioni valutate: {n_form_valutate}  '
                  f'cambiano almeno una carta G->G+O: {n_form_cambiate} ({pct:.1f}%)')

            out['controllo1'][nome_base]['ruoli'][cod] = {
                'n_carte_ruolo': n_carte_ruolo, 'n_cambiate': n_cambiate,
                'mediana_scostamento': mediana, 'massimo_scostamento': massimo,
                'n_formazioni_valutate': n_form_valutate,
                'n_formazioni_cambiate': n_form_cambiate, 'pct_formazioni_cambiate': pct,
            }

    # ------------------------------------------------------------ Controllo 2
    print('\n' + '=' * 78)
    print('CONTROLLO 2 -- copertura del delta_favorito_odds (denominatore totale)')
    print('=' * 78)
    out['controllo2'] = {}
    for nome_base, unita in unita_per_base.items():
        tot = collections.Counter()
        con = collections.Counter()
        esempi_mancanti = collections.defaultdict(list)
        viste = set()
        for u in unita:
            bounds = M.parse_fixture_bounds(u['gw'])
            d_start, d_end = bounds
            fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
            for r in u['pool_rows']:
                key = (r['carta'], u['gw'])
                if key in viste:
                    continue
                viste.add(key)
                tot[r['codice']] += 1
                tot['TOTALE'] += 1
                if r.get('_delta_odds') is not None:
                    con[r['codice']] += 1
                    con['TOTALE'] += 1
                elif len(esempi_mancanti[r['codice']]) < 3:
                    motivo = categorizza_mancante(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
                    esempi_mancanti[r['codice']].append((r.get('nome') or r['slug'], motivo))
        print(f'\n-- {nome_base} --')
        for cod in ('GK', 'DEF', 'MID', 'FWD', 'TOTALE'):
            t, c = tot[cod], con[cod]
            senza = t - c
            pct = 100 * c / t if t else 0.0
            print(f'  {cod:8s} totale={t:5d}  con_delta={c:5d} ({pct:.1f}%)  senza_delta={senza:5d}')
        print('  esempi di carte SENZA delta (nome, motivo):')
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            for nome, motivo in esempi_mancanti.get(cod, []):
                print(f'    [{cod}] {nome}: {motivo}')
        out['controllo2'][nome_base] = {
            'totali': dict(tot), 'con_delta': dict(con),
            'esempi_mancanti': {k: v for k, v in esempi_mancanti.items()},
        }

    # ------------------------------------------------------------ Controllo 3
    print('\n' + '=' * 78)
    print('CONTROLLO 3 -- dump leggibile (una formazione completa, 4 rami)')
    print('=' * 78)
    dump_path = 'analisi_manager/p20_dump_esempio.txt'
    scritto = False
    with open(dump_path, 'w', encoding='utf-8') as fh:
        for nome_base, unita in unita_per_base.items():
            if scritto:
                break
            # ripristina G (gia' presente) e usa policy DEF k=0.2 come G+O di esempio
            for u in unita:
                P20.applica_odds(u['pool_rows'], {'DEF': 0.2})
            for u in unita:
                if scritto:
                    break
                f_a = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_cal', u['leghe_pool'])
                f_g = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_combinato', u['leghe_pool'])
                f_o = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_odds_cal', u['leghe_pool'])
                f_go = P16.gioca_nonarena(u['pool_rows'], u['slots'], '_odds_combinato', u['leghe_pool'])
                for i, (s, fa, fg, fo, fgo) in enumerate(zip(u['slots'], f_a, f_g, f_o, f_go)):
                    if any(x is None for x in (fa, fg, fo, fgo)):
                        continue
                    fh.write(f'DUMP -- base={nome_base} manager={u["manager"]} gw={u["gw"]} '
                             f'competizione={s["competizione"]} (policy G+O di esempio: DEF k=0.2)\n\n')
                    ca, cg, co, cgo = (S21.capitano_atteso(fa), S21.capitano_atteso(fg),
                                       S21.capitano_atteso(fo), S21.capitano_atteso(fgo))
                    pa, pg, po, pgo = (P16.realizzato_50(fa, ca), P16.realizzato_50(fg, cg),
                                       P16.realizzato_50(fo, co), P16.realizzato_50(fgo, cgo))
                    fh.write(f'REALIZZATO: A={pa:.2f}  G={pg:.2f}  O={po:.2f}  G+O={pgo:.2f}\n\n')
                    fh.write('POOL disponibile quel giorno (carta, ruolo, grade, delta_odds, atteso A/O):\n')
                    for r in sorted(u['pool_rows'], key=lambda r: (r['codice'], r['slug'])):
                        fh.write(f'  {r["codice"]:4} {r["slug"]:22} grade={r.get("_grade")!s:6} '
                                 f'delta_odds={r.get("_delta_odds")!s:8} atteso_A={r["_cal"]:7.2f} '
                                 f'atteso_O={r["_odds_cal"]:7.2f}\n')
                    fh.write('\nFORMAZIONI SCELTE per ramo:\n')
                    for label, form, cap in (('A', fa, ca), ('G', fg, cg), ('O', fo, co), ('G+O', fgo, cgo)):
                        fh.write(f'  {label}:\n')
                        for _x, r, _t in form:
                            marcatore = '  [CAPITANO]' if cap and r['slug'] == cap['slug'] else ''
                            fh.write(f'    {r["role_key"]:4} {r["slug"]:22} atteso={r["atteso_cal"]:7.2f}'
                                     f'{marcatore}\n')
                    fh.write('\n' + '=' * 78 + '\n\n')
                    scritto = True
                    break
    print(f'dump scritto in {dump_path}')

    with open('analisi_manager/p20_controlli_out.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_controlli_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
