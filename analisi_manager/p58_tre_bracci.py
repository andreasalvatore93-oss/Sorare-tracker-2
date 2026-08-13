# -*- coding: utf-8 -*-
"""BINARIO 2 A TRE BRACCI -- A vs G-variabile vs G-fisso (13/08/2026).

PERCHE' ESISTE. Fino a oggi nessuno script metteva i tre insieme:
  - p24_binario2_ga.py gira DUE bracci, A (`_cal`) contro G (`_combinato`);
  - p57_grade_fuoricampo_preregistrato.py gira DUE bracci ENTRAMBI G
    (gruppo nativo lega_ruolo contro tabella storica congelata).
Quindi "quanto cambia G-fisso rispetto a G-variabile" e "quanto valgono
entrambi rispetto a nessun voto" non erano mai stati misurati sulle stesse
unita', nello stesso run, sullo stesso pool. Questo script fa quello.

I TRE BRACCI, sullo STESSO pool (differenza solo nel criterio di scelta):
  A          -- nessun voto: si schiera su `_cal` (atteso calibrato).
  G-variabile-- PRODUZIONE DI OGGI: voto con gruppo nativo (lega, ruolo)
                dentro la giornata. Dove il gruppo ha meno di 2 membri il
                voto si spegne da solo (~51% delle righe di produzione).
  G-fisso    -- LA VARIANTE DA VALIDARE (GRADE_GROUP_STORICA_ENABLED,
                oggi SPENTA in produzione): voto sempre applicato, con le
                tabelle CONGELATE il 12/08 (cutoff 2026-08-14), fattore
                storico 0,482 e ricentraggio per ruolo calcolato fresco.

COSE DA SAPERE PRIMA DI LEGGERE I NUMERI
  - Il pool e' costruito UNA VOLTA SOLA e condiviso dai tre bracci
    (p24_binario2_ga.py:117-131): unione delle carte che quel manager ha
    davvero schierato in quella giornata, meno quelle a 0/DNP. L'esclusione
    dei DNP vale per TUTTI E TRE i bracci, quindi non regala a G le carte
    con la F postuma: e' un paletto, non un vantaggio.
  - G e' PENALIZZATO per costruzione rispetto ad A: al momento della scelta
    vedeva un voto costruito sulle odds, non quello riscritto dopo. Se
    regge lo stesso, e' una conferma, non un pareggio.
  - SU UNA SOLA GIORNATA IL RISULTATO NON DECIDE NIENTE: serve solo a
    vedere che la catena gira e che i tre bracci si muovono davvero. Lo
    script lo dice da solo quando le unita' sono poche.

Uso:
  python analisi_manager/p58_tre_bracci.py                          # tutto l'archivio
  python analisi_manager/p58_tre_bracci.py --fixture football-20-24-feb-2026
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

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p24_binario2_ga as B2  # noqa: E402

GRADE_SCALE_PATH = os.path.join('analisi_manager', 'dati',
                                'grade_scala_produzione_cutoff_2026-08-14.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati',
                                  'sd_atteso_produzione_righe_cutoff_2026-08-14.json')
FATTORE = 0.482


def carica_tabelle_congelate():
    """Le tabelle pre-registrate il 12/08. NON si rigenerano su dati nuovi:
    sono la ricetta, non un parametro da ritarare (vedi §8bis-bis)."""
    for p in (GRADE_SCALE_PATH, SD_PRODUZIONE_PATH):
        if not os.path.exists(p):
            print(f'ERRORE: manca la tabella congelata {p}')
            return None
    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_prod)
    # celle con meno di 2 osservazioni: sd=0 spegnerebbe il voto, cioe'
    # esattamente il difetto che questa variante vuole eliminare (§8bis-bis
    # punto 4). Si tolgono, cosi' cadono sul livello piu' grezzo.
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_prod)
    for k, n in conteggio.items():
        if n < 2 and k in tab_sd['lega_ruolo']:
            del tab_sd['lega_ruolo'][k]
    return tab_sd


def gioca(pre_ok, modo, tab_sd=None, fattore=1.0, ricentra_per_ruolo=False):
    """Ritorna (netto_G, netto_A) per unita' manager-fixture.

    Copiato nella forma da p57 (stessa ricetta), ma restituisce ANCHE il
    braccio A: A non dipende dal voto (gioca su `_cal`), quindi deve venire
    identico da qualunque passata -- ed e' il nostro test A/A gratis.
    """
    varianti = []
    for pre in pre_ok:
        rows = [dict(r) for r in pre['pool_rows']]
        if modo == 'lega_ruolo':
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        else:
            S21.applica_gruppi_grade(rows, modo='storica_completa',
                                     tabella_sd_storica=tab_sd,
                                     fattore_storico=fattore)
        varianti.append((pre, rows))
    if ricentra_per_ruolo:
        tutte = [r for _p, rows in varianti for r in rows]
        per_ruolo = collections.defaultdict(list)
        for r in tutte:
            per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
        media = {c: sum(v) / len(v) for c, v in per_ruolo.items()}
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media[r['codice']], 2)
        print('  ricentraggio per ruolo: '
              + ', '.join(f'{k}={v:+.3f}' for k, v in sorted(media.items())))
    netto_g, netto_a = {}, {}
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        k = (pre['manager'], pre['fixture'])
        netto_g[k] = sum(r['netto_stimato'] for r in esito['ris_G'])
        netto_a[k] = sum(r['netto_stimato'] for r in esito['ris_A'])
    return netto_g, netto_a


def boot_per_manager(a, b, n_boot=5000, seed=20260813):
    """Bootstrap con ricampionamento sul MANAGER, non sulla singola
    formazione: le giornate dello stesso manager non sono indipendenti
    (stesso mazzo), ricampionarle una per una gonfierebbe la precisione."""
    chiavi = sorted(set(a) & set(b))
    per_manager = collections.defaultdict(list)
    for k in chiavi:
        per_manager[k[0]].append(k)
    manager = sorted(per_manager)
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        tot = 0.0
        for _i in range(len(manager)):
            m = manager[rnd.randrange(len(manager))]
            for k in per_manager[m]:
                tot += b[k] - a[k]
        ds.append(tot)
    ds.sort()
    n = len(ds)
    return {'n_unita': len(chiavi), 'n_manager': len(manager),
            'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n,
            'discordanti': sum(1 for k in chiavi if abs(b[k] - a[k]) > 1e-9)}


def riga_confronto(eti, a, b):
    r = boot_per_manager(a, b)
    print('%-26s %+9.0f   IC95%%[%+8.0f ; %+8.0f]  positivo %5.1f%%   cambia in %d/%d'
          % (eti, r['delta'], r['lo'], r['hi'], r['pct'] * 100,
             r['discordanti'], r['n_unita']))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', action='append', default=[],
                    help='limita a una o piu\' giornate (ripetibile)')
    args = ap.parse_args()

    fixtures = B2.elenca_fixture()
    if args.fixture:
        fixtures = [f for f in fixtures if f[1] in set(args.fixture)]
    if not fixtures:
        print('nessuna fixture trovata in archivio_ufficiale con questo filtro')
        return

    n_man = len(set(m for m, _f, _p in fixtures))
    print('=' * 88)
    print('BINARIO 2 A TRE BRACCI -- A vs G-variabile vs G-fisso')
    print('unita\' manager-giornata in ingresso: %d   manager distinti: %d'
          % (len(fixtures), n_man))
    print('=' * 88)

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    pre_ok, saltate = [], []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        (pre_ok if pre is not None else saltate).append(pre if pre is not None
                                                        else (manager, fx))
    for manager, fx in saltate:
        print('SALTATA  %-14s %s  (pool vuoto o nessuna partita-target)' % (manager, fx))
    if not pre_ok:
        print('nessuna unita\' utilizzabile.')
        return

    # --- controllo pool contro slot, PRIMA dei numeri (regola CLAUDE.md) ---
    n_una_arena = 0
    for pre in pre_ok:
        arene = max(1, round(pre['pool_size'] / 5.0))
        if arene < 2:
            n_una_arena += 1
    print('\nunita\' processate: %d   di cui con pool da una sola arena: %d'
          % (len(pre_ok), n_una_arena))
    print('  (con una sola arena non c\'e\' ricomposizione possibile: quelle'
          ' unita\' pesano poco)')
    if len(pre_ok) < 30:
        print('\n*** ATTENZIONE: %d unita\'. Questo giro serve a vedere se la'
              ' catena gira,' % len(pre_ok))
        print('*** NON a decidere niente sul modello. Non citare questi numeri'
              ' come verdetto. ***')

    tab_sd = carica_tabelle_congelate()
    if tab_sd is None:
        return

    print('\n--- braccio G-variabile (produzione di oggi) ---')
    g_var, a_var = gioca(pre_ok, 'lega_ruolo')
    print('--- braccio G-fisso (ricetta congelata, fattore %.3f) ---' % FATTORE)
    g_fis, a_fis = gioca(pre_ok, 'storica_completa', tab_sd, FATTORE,
                         ricentra_per_ruolo=True)

    # --- TEST A/A: A non usa il voto, deve venire identico dalle due passate
    scarti = [k for k in a_var if abs(a_var[k] - a_fis.get(k, 0.0)) > 1e-6]
    print('\nTEST A/A sul braccio A (non usa il voto, deve essere identico): '
          '%s' % ('OK, identico' if not scarti
                  else 'FALLITO su %d unita\' -- NON leggere oltre' % len(scarti)))
    if scarti:
        for k in scarti[:5]:
            print('   %-14s %-30s  %+.1f contro %+.1f'
                  % (k[0], k[1], a_var[k], a_fis[k]))
        return

    tot_a = sum(a_var.values())
    tot_gv = sum(g_var.values())
    tot_gf = sum(g_fis.values())
    print('\n%-26s %+9.0f' % ('A (nessun voto)', tot_a))
    print('%-26s %+9.0f' % ('G-variabile (produzione)', tot_gv))
    print('%-26s %+9.0f' % ('G-fisso (da validare)', tot_gf))

    print('\nDELTA APPAIATI (bootstrap ricampionando i MANAGER):')
    riga_confronto('G-variabile - A', a_var, g_var)
    riga_confronto('G-fisso     - A', a_var, g_fis)
    r3 = riga_confronto('G-fisso - G-variabile', g_var, g_fis)

    print('\nLa riga che risponde alla domanda aperta e\' la terza: dice se'
          ' G-fisso')
    print('cambia davvero rispetto alla produzione di oggi, e in che verso.')
    if r3['discordanti'] == 0:
        print('ZERO unita\' discordanti: i due bracci scelgono le stesse carte,'
              ' quindi il')
        print('test e\' NULLO PER COSTRUZIONE su questo campione -- non e\' un'
              ' pareggio.')


if __name__ == '__main__':
    main()
