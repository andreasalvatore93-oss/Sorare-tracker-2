# -*- coding: utf-8 -*-
"""Applica i due fix chiesti da Opus dopo la revisione critica del 12/08
(docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §8bis-bis "Revisione critica
Opus") e rifa' il confronto APPAIATO (p50) con i fix dentro:

  (i)  celle (lega,codice) con n<2 nella tabella sd_atteso -> tolte dalla
       tabella, cosi' _sd_atteso_storico ricade da sola sul livello ruolo
       (fallback gia' esistente, nessuna soglia alta: Opus ha GIA' provato
       le soglie alte stile p18 e PEGGIORANO, corr 0,1103->0,0836, 99,9%
       negativo -- qui si tocca SOLO il caso n<2, non n<100/500).
  (ii) ricentraggio della "spinta cieca" fatto PER RUOLO (GK/DEF/MID/FWD),
       non con un'unica media globale: il ricentraggio globale lasciava
       -0,93pt sui GK (41% di una sd GK), spingendoli in blocco in basso e
       cambiando quante arene si giocano, non solo l'ordine.

Stesso identico impianto di p50 (stesso pool, stesso bootstrap cluster
manager-fixture, B=5000): qui SOLO le due tabelle (archivio/produzione)
cambiano per il fix (i), e la funzione di ricentraggio cambia per il fix
(ii). Applicato a ENTRAMBE le fonti per un confronto onesto.

Uso: python analisi_manager/p51_grade_essenze_fix.py
"""
import os
import sys
import io
import json
import random
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p24_binario2_ga as B2

GRADE_SCALE_PATH = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati', 'sd_atteso_produzione_righe.json')


def costruisci_tabella_senza_celle_piccole(righe, soglia_min=2):
    """(i): stessa gerarchia di S21.costruisci_tabella_sd_atteso, ma
    rimuove dal livello lega_ruolo le celle con n < soglia_min -- ricadono
    da sole sul livello ruolo via _sd_atteso_storico (fallback esistente,
    nessuna modifica a quella funzione)."""
    tab = S21.costruisci_tabella_sd_atteso(righe)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe)
    celle_tolte = [k for k, n in conteggio.items() if n < soglia_min and k in tab['lega_ruolo']]
    for k in celle_tolte:
        del tab['lega_ruolo'][k]
    return tab, len(celle_tolte)


def gioca(pre_ok, modo, tab_sd=None, fattore=1.0, ricentra_per_ruolo=False):
    varianti = []
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if modo == 'lega_ruolo':
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        else:
            S21.applica_gruppi_grade(rows, modo='storica_completa',
                                     tabella_sd_storica=tab_sd, fattore_storico=fattore)
        varianti.append((pre, rows))

    if ricentra_per_ruolo:
        tutte = [r for _p, rows in varianti for r in rows]
        per_ruolo = collections.defaultdict(list)
        for r in tutte:
            per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
        media_per_ruolo = {cod: sum(v) / len(v) for cod, v in per_ruolo.items()}
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media_per_ruolo[r['codice']], 2)
        print(f"    ricentraggio per ruolo: {', '.join(f'{k}={v:+.3f}' for k, v in sorted(media_per_ruolo.items()))}")

    out = {}
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def boot(a, b, n_boot=5000, seed=20260812):
    chiavi = sorted(set(a) & set(b))
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        camp = [chiavi[rnd.randrange(len(chiavi))] for _i in range(len(chiavi))]
        ds.append(sum(b[k] for k in camp) - sum(a[k] for k in camp))
    ds.sort()
    n = len(ds)
    return {'n_gw': len(chiavi), 'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n}


def main():
    fixtures = B2.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print(f'fixture processate: {len(pre_ok)} (su {len(fixtures)})')

    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)

    righe_archivio = [r for pre in pre_ok for r in pre['pool_rows']]
    tab_arch, n_tolte_arch = costruisci_tabella_senza_celle_piccole(righe_archivio)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_prod, n_tolte_prod = costruisci_tabella_senza_celle_piccole(righe_prod)
    print(f'celle n<2 tolte (ricadono su livello ruolo): archivio={n_tolte_arch}  produzione={n_tolte_prod}')

    tot_base = gioca(pre_ok, 'lega_ruolo')
    print('  --- archivio 0,75 (fix i+ii) ---')
    tot_arch = gioca(pre_ok, 'storica_completa', tab_arch, 0.75, ricentra_per_ruolo=True)
    print('  --- produzione 0,462 (fix i+ii) ---')
    tot_prod = gioca(pre_ok, 'storica_completa', tab_prod, 0.462, ricentra_per_ruolo=True)

    print(f'\nG baseline  : {sum(tot_base.values()):+.0f}')
    print(f'G archivio  : {sum(tot_arch.values()):+.0f}')
    print(f'G produzione: {sum(tot_prod.values()):+.0f}')
    for nome, a, b in (('archivio 0,75 (fix) vs baseline', tot_base, tot_arch),
                       ('produzione 0,462 (fix) vs baseline', tot_base, tot_prod),
                       ('>>> produzione vs archivio (APPAIATO, il numero che decide)', tot_arch, tot_prod)):
        r = boot(a, b)
        print(f'\n=== {nome} ===')
        print(f"  n GW-manager: {r['n_gw']}   delta: {r['delta']:+.0f}  "
              f"IC95%=[{r['lo']:+.0f};{r['hi']:+.0f}]  positivo {r['pct']*100:.1f}%")

    out = os.path.join('analisi_manager', 'dati', 'grade_essenze_fix_2026-08-12.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({k: {'|'.join(kk): vv for kk, vv in v.items()}
                   for k, v in (('baseline', tot_base), ('archivio', tot_arch), ('produzione', tot_prod))},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio: {out}')


if __name__ == '__main__':
    main()
