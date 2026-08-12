# -*- coding: utf-8 -*-
"""TEST FUORI CAMPIONE PRE-REGISTRATO -- filone gruppo grade esteso alla
giornata (priorita' 2), pre-registrato il 12/08/2026 dopo il verdetto di
Opus "PRONTA PER IL FUORI CAMPIONE PRE-REGISTRATO, NON PER LA PRODUZIONE
DIRETTA" (docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §8bis-bis).

NON LANCIARE PRIMA CHE GW7 SIA CHIUSA E RIESTRATTA (25/08/2026 in poi).
Prima di allora questo script trova 0 (o pochissime) fixture e non
significa niente -- e' qui pronto per non dover riscrivere niente sotto
pressione quel giorno, con le regole GIA' CONGELATE oggi, PRIMA di vedere
il risultato.

FIXTURE DEL TEST (uniche, mai mescolate con le 360 usate oggi per tarare
tutto -- altrimenti si torna a misurare il campione con cui si e' scelta
la ricetta):
  GW5 football-14-18-aug-2026
  GW6 football-18-21-aug-2026
  GW7 football-21-25-aug-2026

RICETTA CONGELATA oggi (12/08/2026), NON ritarata su questi dati nuovi:
  - tabella VOTO: analisi_manager/dati/grade_scala_produzione_cutoff_2026-08-14.json
    (popolazione consigli, grade agganciato, SOLO kickoff < 2026-08-14 --
    walk-forward vero, GW5/6/7 escluse dalla tabella per costruzione).
  - tabella sd_atteso: analisi_manager/dati/sd_atteso_produzione_righe_cutoff_2026-08-14.json
    (stesso cutoff).
  - fattore_storico = 0,482 (fissato oggi, NON riristimato qui).
  - ricentraggio PER RUOLO, calcolato FRESCO sul campione di QUESTO test
    (non le costanti misurate sul backtest vecchio, che erano un cerotto
    per un artefatto -- vedi §8bis-bis "Il +1,02 del voto").

METRICA E REGOLA DI DECISIONE (scritte oggi, prima di guardare i dati):
  G_finale - G_baseline (lega_ruolo), Binario 2, netto essenze realizzato,
  bootstrap cluster manager-fixture. NON aspettarsi significativita' su
  sole 3 GW (il guadagno di oggi era concentrato: 45-46% da 5 GW-manager
  su 360). L'atteso onesto per-GW-manager e' MOLTO piu' piccolo di
  10.102/360: quel numero era il migliore di ~12 varianti provate sullo
  stesso campione, non una stima pulita.
  - segno NEGATIVO su queste 3 GW -> non implementare in produzione senza
    rivedere la ricetta.
  - segno POSITIVO (qualunque taglia) -> non e' prova da solo (n troppo
    piccolo), si somma alla prova gia' in mano (placebo p<=0,048 su
    p56/p52) per una decisione insieme all'utente.

Uso: python analisi_manager/p57_grade_fuoricampo_preregistrato.py
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

FIXTURE_TEST = {'football-14-18-aug-2026', 'football-18-21-aug-2026', 'football-21-25-aug-2026'}
GRADE_SCALE_PATH = os.path.join('analisi_manager', 'dati', 'grade_scala_produzione_cutoff_2026-08-14.json')
SD_PRODUZIONE_PATH = os.path.join('analisi_manager', 'dati', 'sd_atteso_produzione_righe_cutoff_2026-08-14.json')
FATTORE = 0.482


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
        media = {cod: sum(v) / len(v) for cod, v in per_ruolo.items()}
        for r in tutte:
            r['_combinato'] = round(r['_combinato'] - media[r['codice']], 2)
        print(f"  ricentraggio per ruolo: {', '.join(f'{k}={v:+.3f}' for k, v in sorted(media.items()))}")
    out = {}
    for pre, rows in varianti:
        fake = {'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows}
        esito = B2.processa_fixture_pass2(fake)
        out[(pre['manager'], pre['fixture'])] = sum(r['netto_stimato'] for r in esito['ris_G'])
    return out


def boot(a, b, n_boot=5000, seed=20260825):
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
    fixtures = [f for f in B2.elenca_fixture() if f[1] in FIXTURE_TEST]
    print(f'fixture del test trovate in archivio_ufficiale: {len(fixtures)} '
          f'(su {len(FIXTURE_TEST)} attese x n_manager)')
    if not fixtures:
        print('\nNESSUNA fixture trovata: GW5/6/7 non ancora estratte in archivio_ufficiale/.')
        print('Rilanciare questo script DOPO aver riestratto quelle 3 fixture (dal 25/08/2026).')
        return

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print(f'fixture processate: {len(pre_ok)} (manager distinti: {len(set(p["manager"] for p in pre_ok))})')
    if len(pre_ok) < 5:
        print('ATTENZIONE: n molto piccolo, il risultato serve solo per il SEGNO (vedi regola di decisione).')

    if not os.path.exists(GRADE_SCALE_PATH) or not os.path.exists(SD_PRODUZIONE_PATH):
        print(f'\nERRORE: tabelle congelate non trovate ({GRADE_SCALE_PATH}, {SD_PRODUZIONE_PATH}).')
        print('Non rigenerarle su dati nuovi: sono la ricetta pre-registrata, vanno usate cosi\' com\'erano il 12/08.')
        return

    with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
        S21.bfg._GRADE_SCALE_TABLE = json.load(f)
    with open(SD_PRODUZIONE_PATH, encoding='utf-8') as f:
        righe_prod = json.load(f)
    tab_sd = S21.costruisci_tabella_sd_atteso(righe_prod)
    conteggio = collections.Counter((r['lega'], r['codice']) for r in righe_prod)
    for k, n in conteggio.items():
        if n < 2 and k in tab_sd['lega_ruolo']:
            del tab_sd['lega_ruolo'][k]

    tot_base = gioca(pre_ok, 'lega_ruolo')
    tot_finale = gioca(pre_ok, 'storica_completa', tab_sd, FATTORE, ricentra_per_ruolo=True)

    print(f'\nG baseline: {sum(tot_base.values()):+.0f}  ({len(tot_base)} GW-manager)')
    print(f'G finale  : {sum(tot_finale.values()):+.0f}')
    r = boot(tot_base, tot_finale)
    print(f'\ndelta: {r["delta"]:+.0f}  IC95%=[{r["lo"]:+.0f};{r["hi"]:+.0f}]  positivo {r["pct"]*100:.1f}%  n={r["n_gw"]}')
    print(f'delta per GW-manager: {r["delta"]/max(r["n_gw"],1):+.1f}')
    print('\nRegola di decisione (scritta il 12/08/2026, PRIMA di vedere questo numero):')
    if r['delta'] < 0:
        print('  SEGNO NEGATIVO -> non implementare in produzione senza rivedere la ricetta.')
    else:
        print('  SEGNO POSITIVO -> non e\' prova da solo (n piccolo), si somma al placebo gia\' in mano.')


if __name__ == '__main__':
    main()
