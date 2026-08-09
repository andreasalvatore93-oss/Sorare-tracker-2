"""Misura la copertura di `_grade` sul pool (stesso denominatore del
CONTROLLO 4b: ogni riga di ogni pool_rows, per base), stratificata per
ruolo/lega e per formazione. Poi rigioca G+D_z/G+L_z contro G SOLO sulle
formazioni con copertura grade per-formazione >=70%, con IC95 bootstrap
sui manager, riusando applica()/delta_vs() gia' scritti in
p20_odds_livello_assoluto.py -- nessuna riscrittura del knapsack (D7
CLAUDE.md), nessuna modifica alla produzione, nessuna query di rete.

SOLO MISURA. Nessun verdetto qui: i numeri vanno letti da chi legge
l'handoff.

Il campo `_grade` e il rapporto con_grade/candidati sono ESATTAMENTE quelli
gia' calcolati da p12_backtest_formazione_grade.py (righe 253-275,326,401,
`copertura_grade_pct`): li' il campo e' popolato per il pool ARENA capped,
qui per lo stesso field name gia' scritto da T13.costruisci_pool_rows dentro
P19.raccogli (vedi p19_nonarena_grade_scala.py riga 81, commento "'_grade'
qui e' GIA' numerico"). Stessa definizione, stesso rapporto, dataset diverso
(non-arena invece di arena capped): non si riscrive nulla, si applica la
stessa formula al pool gia' costruito.
"""
import os
import sys
import io
import json
import glob
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
import p20_odds_livello_assoluto as P20L

BASI = P20L.BASI


def copertura_globale(unita, nome_base):
    """Stesso rapporto di p12 (copertura_con_grade/copertura_candidati),
    stesso denominatore per riga del CONTROLLO 4b. Stratificato per ruolo
    e per lega."""
    tot = con = 0
    per_ruolo = collections.Counter()
    per_ruolo_tot = collections.Counter()
    per_lega = collections.Counter()
    per_lega_tot = collections.Counter()
    for u in unita:
        for r in u['pool_rows']:
            tot += 1
            per_ruolo_tot[r['codice']] += 1
            per_lega_tot[r['lega']] += 1
            if r.get('_grade') is not None:
                con += 1
                per_ruolo[r['codice']] += 1
                per_lega[r['lega']] += 1
    print(f'[{nome_base}] copertura grade GLOBALE (denominatore 4b): {con}/{tot} ({100*con/tot:.1f}%)')
    esito = {'tot': tot, 'con': con, 'pct': 100 * con / tot, 'per_ruolo': {}, 'per_lega': {}}
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        t, c = per_ruolo_tot.get(cod, 0), per_ruolo.get(cod, 0)
        pct = 100 * c / t if t else None
        print(f'    ruolo {cod:4s}  {c}/{t}  ({pct:.1f}%)' if t else f'    ruolo {cod:4s}  0/0')
        esito['per_ruolo'][cod] = {'con': c, 'tot': t, 'pct': pct}
    for lg in sorted(per_lega_tot):
        t, c = per_lega_tot[lg], per_lega.get(lg, 0)
        pct = 100 * c / t if t else None
        print(f'    lega {lg:12s}  {c}/{t}  ({pct:.1f}%)' if t else f'    lega {lg:12s}  0/0')
        esito['per_lega'][lg] = {'con': c, 'tot': t, 'pct': pct}
    return esito


def copertura_per_formazione(unita):
    """Per ogni formazione (allineata a formazioni_valide/slots, stesso
    ordine di gioca_e_misura/P16.gioca_nonarena), la % di grade disponibile
    nel sottoinsieme di pool_rows visibile a quel PARTICOLARE slot: 'mixed'
    -> tutto il pool_rows dell'unita; lega specifica -> solo le righe di
    quella lega (stesso filtro che T13.costruisci applica per selezionare i
    candidati di quello slot)."""
    out = []
    for u in unita:
        pool = u['pool_rows']
        for s in u['slots']:
            if s['pool_league'] == 'mixed':
                candidati = pool
            else:
                candidati = [r for r in pool if r['lega'] == s['pool_league']]
            tot = len(candidati)
            con = sum(1 for r in candidati if r.get('_grade') is not None)
            pct = (100 * con / tot) if tot else None
            out.append(pct)
    return out


def distribuzione_bucket(pct_list):
    bucket = collections.Counter()
    for pct in pct_list:
        if pct is None:
            bucket['n/d'] += 1
        elif pct < 50:
            bucket['<50%'] += 1
        elif pct < 70:
            bucket['50-70%'] += 1
        elif pct < 90:
            bucket['70-90%'] += 1
        else:
            bucket['>90%'] += 1
    return bucket


def delta_vs_filtrato(unita, key_x, key_ref, ris_ref, mask):
    """Come P20L.delta_vs ma solo sulle posizioni dove mask[i] e' True
    (allineamento identico a gioca_e_misura/mask costruita sullo stesso
    ordine)."""
    ris_x = P20L.gioca_e_misura(unita, key_x)
    per_manager = collections.defaultdict(list)
    tot_x = tot_ref = 0.0
    cnt = 0
    idx = 0
    for u in unita:
        for _s in u['slots']:
            x, r, keep = ris_x[idx], ris_ref[idx], mask[idx]
            idx += 1
            if not keep or x is None or r is None:
                continue
            per_manager[x['manager']].append(x['punti'] - r['punti'])
            tot_x += x['punti']; tot_ref += r['punti']; cnt += 1
    d = (tot_x - tot_ref) / cnt if cnt else float('nan')
    lo, hi = P19.boot_delta_manager(per_manager)
    return d, lo, hi, cnt


def main():
    lega_di = P19.AG.indice_lega()
    _idx_grade, _ = M.carica_indice_grade_esteso()
    idx_per_slug_full = collections.defaultdict(dict)
    for slug, entries in _idx_grade.items():
        for data, grade in entries:
            idx_per_slug_full[slug][data] = grade
    osservazioni, _s, _d = P19.P18.costruisci_osservazioni()
    scala_globale = P19.P18.costruisci_scala(osservazioni, cutoff=None)
    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))

    esito_finale = {}
    for nome_base, (base_pulita_fn, _out_prefix) in BASI.items():
        print('=' * 78)
        print(f'BASE: {nome_base}')
        print('=' * 78)
        unita, scarti, conta, n_gw = P19.raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di,
                                                    scala_globale, osservazioni)
        cache = P19.cache
        P20L.annota_segnali(unita, cache)
        P20L.calcola_zscore(unita)

        glob_cov = copertura_globale(unita, nome_base)

        pct_list = copertura_per_formazione(unita)
        bucket = distribuzione_bucket(pct_list)
        n_form_tot = len(pct_list)
        print(f'\n  DISTRIBUZIONE COPERTURA PER FORMAZIONE (n={n_form_tot}):')
        for k in ('<50%', '50-70%', '70-90%', '>90%', 'n/d'):
            n = bucket.get(k, 0)
            print(f'    {k:8s} n={n:4d}  ({100*n/n_form_tot:.1f}%)' if n_form_tot else f'    {k:8s} n=0')

        mask70 = [pct is not None and pct >= 70.0 for pct in pct_list]
        n_mask = sum(mask70)
        print(f'\n  formazioni con copertura grade per-formazione >=70%: {n_mask}/{n_form_tot} ({100*n_mask/n_form_tot:.1f}%)')

        ris_G = P20L.gioca_e_misura(unita, '_combinato')

        print(f'\n  RITEST G+D_z vs G e G+L_z vs G, SOLO sul sottoinsieme >=70% copertura, k=0.2 per ruolo:')
        esiti_filtrati = {}
        for cod in ('GK', 'DEF', 'MID', 'FWD'):
            policy = {cod: 0.2}
            for u in unita:
                P20L.applica(u['pool_rows'], policy, policy)
            d_d, lo_d, hi_d, cnt_d = delta_vs_filtrato(unita, '_d_combinato', '_combinato', ris_G, mask70)
            d_l, lo_l, hi_l, cnt_l = delta_vs_filtrato(unita, '_l_combinato', '_combinato', ris_G, mask70)
            print(f'    [{cod} k=0.2, copertura>=70%]  G+D_z vs G: delta={d_d:+.3f} '
                  f'IC95=[{lo_d:+.3f},{hi_d:+.3f}] n={cnt_d}')
            print(f'                                   G+L_z vs G: delta={d_l:+.3f} '
                  f'IC95=[{lo_l:+.3f},{hi_l:+.3f}] n={cnt_l}')
            esiti_filtrati[cod] = {
                'D': {'delta': d_d, 'ic': [lo_d, hi_d], 'n': cnt_d},
                'L': {'delta': d_l, 'ic': [lo_l, hi_l], 'n': cnt_l},
            }

        esito_finale[nome_base] = {
            'copertura_globale': glob_cov,
            'distribuzione_bucket_per_formazione': dict(bucket),
            'n_formazioni_totali': n_form_tot,
            'n_formazioni_copertura_ge70': n_mask,
            'test_filtrato_ge70': esiti_filtrati,
        }
        print()

    with open('analisi_manager/p20_copertura_grade_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito_finale, fh, ensure_ascii=False, indent=2)
    print('salvato analisi_manager/p20_copertura_grade_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
