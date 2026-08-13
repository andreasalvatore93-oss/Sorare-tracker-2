# -*- coding: utf-8 -*-
"""ACCENDERE G-FISSO SPOSTA LE SOGLIE ARENA? (13/08/2026)

LA CATENA (CLAUDE.md, regola fissa): valori di produzione -> soglie arena
-> scouting. `PAREGGIO_ARENA` e `GUADAGNO_PER_PUNTO` sono tarati sui PUNTI
ATTESI: se accendere G-fisso spostasse in alto o in basso l'atteso medio,
quelle soglie diventerebbero sbagliate in silenzio, e con loro i consigli
d'acquisto dello scouting.

La ricetta di G-fisso ha gia' una difesa progettata apposta: il
RICENTRAGGIO PER RUOLO (`_recentra_grade_per_ruolo`), che toglie a ogni
ruolo la spinta media del voto, cosi' il voto RIORDINA senza spostare il
livello. Ma "progettata apposta" non e' "verificata": qui si misura.

COSA GUARDA
 1. media e dispersione dell'atteso PER CARTA, nei tre bracci;
 2. media dell'atteso PER FORMAZIONE (le 5 carte piu' il capitano) -- e'
    QUESTO il numero che si confronta con PAREGGIO_ARENA, non quello per
    carta;
 3. quante formazioni cambiano lato rispetto alla soglia, cioe' quante
    passerebbero da "sotto pareggio" a "sopra" solo per effetto del flag.
Se le medie coincidono entro pochi decimi e i cambi di lato sono
simmetrici, le soglie reggono e non vanno ritarate.

Uso: python analisi_manager/p62_soglie_dopo_gfisso.py
"""
import os
import sys
import io
import json
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p23_binario1_mga as B1  # noqa: E402
import p58_tre_bracci as P58  # noqa: E402


def media_sd(v):
    if not v:
        return 0.0, 0.0
    m = sum(v) / len(v)
    var = sum((x - m) ** 2 for x in v) / max(1, len(v) - 1)
    return m, var ** 0.5


def atteso_formazione(riga_per_carta, formazione, chiave):
    carte = formazione['carte']
    rows = [riga_per_carta.get(c.get('carta')) for c in carte]
    if any(r is None for r in rows):
        return None
    cap = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
    tot = sum(r[chiave] for r in rows)
    if cap is not None:
        tot += 0.2 * rows[cap][chiave]
    return tot


def main():
    fixtures = B1.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in fixtures:
        pre = B1.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print('unita\': %d' % len(pre_ok))

    tab_sd = P58.carica_tabelle_congelate()
    if tab_sd is None:
        return
    # righello contemporaneo: e' quello che girera' in produzione, dove le
    # tabelle si rigenerano a ogni run
    tutte = [r for pre in pre_ok for r in pre['pool_rows']]
    tab_sd = S21.costruisci_tabella_sd_atteso(tutte)

    righe_var, righe_fis = [], []
    for pre in pre_ok:
        rv = [dict(r) for r in pre['pool_rows']]
        S21.applica_gruppi_grade(rv, modo='lega_ruolo')
        rf = [dict(r) for r in pre['pool_rows']]
        S21.applica_gruppi_grade(rf, modo='storica_completa',
                                 tabella_sd_storica=tab_sd,
                                 fattore_storico=P58.FATTORE)
        righe_var.append(rv)
        righe_fis.append(rf)
    # ricentraggio per ruolo, come in produzione
    piatte = [r for rows in righe_fis for r in rows]
    per_ruolo = collections.defaultdict(list)
    for r in piatte:
        per_ruolo[r['codice']].append(r['_combinato'] - r['_cal'])
    media = {c: sum(v) / len(v) for c, v in per_ruolo.items()}
    for r in piatte:
        r['_combinato'] = round(r['_combinato'] - media[r['codice']], 2)
    print('ricentraggio per ruolo applicato: '
          + ', '.join(f'{k}={v:+.3f}' for k, v in sorted(media.items())))

    print()
    print('1) ATTESO PER CARTA (media +/- dispersione)')
    print('%-6s %18s %18s %18s' % ('ruolo', 'A (senza voto)', 'G-variabile', 'G-fisso'))
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        a = [r['_cal'] for rows in righe_var for r in rows if r['codice'] == cod]
        gv = [r['_combinato'] for rows in righe_var for r in rows if r['codice'] == cod]
        gf = [r['_combinato'] for rows in righe_fis for r in rows if r['codice'] == cod]
        print('%-6s %8.2f +/-%-7.2f %8.2f +/-%-7.2f %8.2f +/-%-7.2f'
              % ((cod,) + media_sd(a) + media_sd(gv) + media_sd(gf)))

    print()
    print('2) ATTESO PER FORMAZIONE -- e\' questo che si confronta con PAREGGIO_ARENA')
    tot = {'A': [], 'Gvar': [], 'Gfis': []}
    cambi = collections.Counter()
    for pre, rv, rf in zip(pre_ok, righe_var, righe_fis):
        mv = {r['carta']: r for r in rv}
        mf = {r['carta']: r for r in rf}
        for form in pre['pulite']:
            a = atteso_formazione(mv, form, '_cal')
            gv = atteso_formazione(mv, form, '_combinato')
            gf = atteso_formazione(mf, form, '_combinato')
            if a is None or gv is None or gf is None:
                continue
            tot['A'].append(a)
            tot['Gvar'].append(gv)
            tot['Gfis'].append(gf)
            tipo = B1.TIPO_TO_BFG[form['tipo']]
            soglia = S21.bfg.PAREGGIO_ARENA.get(tipo)
            if soglia is None:
                continue
            if gv >= soglia and gf < soglia:
                cambi['sopra -> sotto'] += 1
            elif gv < soglia and gf >= soglia:
                cambi['sotto -> sopra'] += 1
            else:
                cambi['nessun cambio'] += 1
    for k in ('A', 'Gvar', 'Gfis'):
        m, s = media_sd(tot[k])
        print('  %-6s media %8.2f   dispersione %6.2f   (n=%d)' % (k, m, s, len(tot[k])))
    print('  scostamento G-fisso vs G-variabile: %+.3f punti per formazione'
          % (media_sd(tot['Gfis'])[0] - media_sd(tot['Gvar'])[0]))

    print()
    print('3) FORMAZIONI CHE CAMBIANO LATO RISPETTO ALLA SOGLIA')
    for k, v in cambi.most_common():
        print('  %-18s %6d' % (k, v))
    su = cambi['sotto -> sopra']
    giu = cambi['sopra -> sotto']
    print('  simmetria: %d entrano, %d escono (differenza %+d)' % (su, giu, su - giu))
    print()
    if abs(media_sd(tot['Gfis'])[0] - media_sd(tot['Gvar'])[0]) < 0.5:
        print('VERDETTO: il livello NON si sposta (meno di mezzo punto per')
        print('formazione, contro soglie dell\'ordine di 260). Le soglie arena')
        print('restano tarate: il voto riordina, non alza ne\' abbassa.')
    else:
        print('VERDETTO: il livello SI SPOSTA. PAREGGIO_ARENA e')
        print('GUADAGNO_PER_PUNTO vanno ritarati PRIMA di accendere il flag,')
        print('e con loro va riverificato lo scouting.')


if __name__ == '__main__':
    main()
