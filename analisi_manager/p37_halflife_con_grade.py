# -*- coding: utf-8 -*-
"""HALF_LIFE rimisurato col GRADE ACCESO (13/08/2026, domanda dell'utente).
CORRETTO IL 14/08/2026: la formula del grade qui sotto era quella VECCHIA
(z-score nel gruppo nativo lega/ruolo/giorno, GRADE_ENABLED). La sera del
13/08 la produzione e' passata a GRADE_GROUP_STORICA (tabelle storiche +
GRADE_FATTORE_STORICO + ricentraggio per ruolo, vedi HANDOFF_UNIFICATO_
MODELLO_SCOUTING.md §8bis-bis): questo file misurava gia' un modello che la
produzione non usava piu' da quella sera. Brief a Opus (docs/handoff/
BRIEF_OPUS_METRO_CON_GRADE_2026-08-14.txt), verdetto: si corregge, il
termine del voto (2,3-2,5pt di dispersione) e' abbastanza grande da spostare
il RANKING di lift/corr (non solo il MAE) -- vale la pena rifare la misura
con la formula giusta.

PERCHE'. La rimisura del 13/08 (§8quindecies) giudicava tutto su `atteso`, ma
la produzione NON schiera su `atteso` nudo: schiera su `atteso_combinato`.
E nel banco di prova la parola "grade" non compare nemmeno una volta: quindi
la misura precedente descrive un modello che in produzione non esiste piu'.
Domanda: con il voto acceso (formula CORRENTE), l'half-life migliore si sposta?

COME. Stesso metro, stessa griglia, ma ogni riga viene punteggiata due volte
sullo STESSO campione: senza voto e col voto. Il confronto e' appaiato, quindi
la differenza non puo' venire da campioni diversi. La formula del voto e'
quella VERA di produzione, riusata senza riscriverla:
`analisi_manager.p12_backtest_formazione_grade.applica_gruppi_grade(
modo='storica_completa')`, che dentro chiama `bfg._scala_storica_per` --
esattamente la funzione che legge generatore_formazioni/dati/
grade_scala_produzione.json, la stessa tabella che carica la produzione vera
quando GRADE_GROUP_STORICA_ENABLED='1' (default). Dopo applica_gruppi_grade
si applica anche il RICENTRAGGIO PER RUOLO, come fa
`_recentra_grade_per_ruolo` in produzione (media di atteso_combinato-
atteso_cal, sottratta per ruolo).

Tabella sd_atteso: costruita FRESCA sul campione di questa misura (come fa
p62_soglie_dopo_gfisso.py, "righello contemporaneo") con
`costruisci_tabella_sd_atteso` -- nessun leak: la tabella non contiene nessun
punteggio realizzato, solo statistiche di atteso/grade (verificato, vedi
brief).

JOIN GRADE: non piu' match esatto sulla data (perdeva la maggioranza dei
casi, bug chiuso il 07/08 nel filone principale), ma `grade_in_finestra`
(finestra di GRADE_WINDOW_GIORNI giorni prima, la stessa logica di
produzione) sull'indice completo `carica_indice_grade()` (tutte le fonti
storiche in repo, non solo `storico_grade_*.json` come nella prima versione
di questo file).

LIMITE DEL CAMPIONE, da tenere presente leggendo i numeri: lo storico dei voti
non e' un campione casuale (fu raccolto su giocatori presi dai file manager,
cioe' gente che qualcuno schierava davvero). Quindi la domanda "il voto
sposta l'ottimo?" si puo' fare; "di quanto esattamente" su tutta la
popolazione, no.

Uso: python analisi_manager/p37_halflife_con_grade.py --ruoli gk,def,mid,fwd
"""
import os
import sys
import json
import argparse
import statistics
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, _HERE)
os.chdir(ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import raccogli, lift_selezione
from taratura_halflife_trend import RUOLI
import p12_backtest_formazione_grade as S21

RUOLO_CODICE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}


def applica_grade(righe, idx_grade, tab_sd):
    """righe: [(lega, ruolo, giorno, previsione, reale, slug)] -> lista di
    previsioni combinate, con la formula CORRENTE di produzione
    (GRADE_GROUP_STORICA via S21.applica_gruppi_grade + ricentraggio per
    ruolo). Sostituisce la vecchia versione (z-score nel gruppo nativo),
    superata il 13/08 sera -- vedi docstring del modulo."""
    rows = []
    for lega, ruolo, giorno, p, _reale, slug in righe:
        gn = S21.grade_in_finestra(idx_grade, slug, giorno)
        rows.append({'lega': lega, 'codice': RUOLO_CODICE.get(ruolo, ruolo),
                     '_cal': p, '_grade': gn})
    S21.applica_gruppi_grade(rows, modo='storica_completa',
                             tabella_sd_storica=tab_sd,
                             fattore_storico=S21.bfg.GRADE_FATTORE_STORICO)
    per_ruolo = collections.defaultdict(list)
    for r in rows:
        per_ruolo[r['codice']].append(r)
    for _codice, membri in per_ruolo.items():
        diffs = [r['_combinato'] - r['_cal'] for r in membri]
        media = sum(diffs) / len(diffs) if diffs else 0.0
        for r in membri:
            r['_combinato'] -= media
    return [r['_combinato'] for r in rows]


def metriche(previsioni, reali, chiavi_giorno):
    mae = statistics.mean(abs(y - x) for x, y in zip(previsioni, reali))
    mx, my = statistics.mean(previsioni), statistics.mean(reali)
    sx, sy = statistics.pstdev(previsioni), statistics.pstdev(reali)
    corr = (sum((a - mx) * (b - my) for a, b in zip(previsioni, reali))
            / len(previsioni) / (sx * sy)) if sx > 0 and sy > 0 else 0.0
    finte = [(None, None, g, p, r)
             for g, p, r in zip(chiavi_giorno, previsioni, reali)]
    lift, n_gg = lift_selezione(finte)
    return mae, corr, lift, n_gg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ruoli', default='gk,def,mid,fwd')
    ap.add_argument('--griglia', default='3,4,6,9,12,16,20,25,30,40,60')
    ap.add_argument('--max', type=int, default=0)
    args = ap.parse_args()

    idx_grade, _ = S21.carica_indice_grade()
    n_coppie = sum(len(v) for v in idx_grade.values())
    print(f"voti storici disponibili: {n_coppie} coppie (slug, giorno), "
          f"indice completo S21\n")
    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    punti = raccogli(cache, slugs, {RUOLI[b] for b in brevi}, args.max or None)

    # SOLO i punti che hanno il voto IN FINESTRA: e' l'unico modo di
    # confrontare acceso e spento sullo STESSO campione. Confrontare "tutti
    # senza voto" contro "quelli col voto, col voto" mescolerebbe due cose
    # diverse. grade_in_finestra() (non piu' match esatto sulla data) allarga
    # la copertura rispetto alla prima versione di questo file.
    punti = [p for p in punti
             if S21.grade_in_finestra(idx_grade, p[1], p[2]) is not None]
    print(f"{len(punti)} punti con voto in finestra\n")

    esiti = {}
    for b in brevi:
        sotto = [p for p in punti if p[0] == RUOLI[b]]
        if len(sotto) < 500:
            print(f"{b.upper()}: solo {len(sotto)} punti, salto")
            continue
        modulo = sotto[0][3]['modulo']
        prod = modulo.HALF_LIFE_GAMES
        ti = getattr(modulo, 'TREND_INTENSITY', 0.0)
        print('=' * 92)
        print(f"{b.upper()} -- {len(sotto)} punti col voto | produzione "
              f"half_life={prod}")
        print('=' * 92)
        print('%-8s | %-24s | %-24s' % ('', 'SENZA voto (come oggi)',
                                        'COL voto (come produzione)'))
        print('%-8s | %7s %7s %7s | %7s %7s %7s' %
              ('half_l', 'MAE', 'corr', 'lift%', 'MAE', 'corr', 'lift%'))
        righe_out = []
        for hl in [float(x) for x in args.griglia.split(',')]:
            base = []
            for ruolo, slug, data, ctx, reale in sotto:
                try:
                    p = prev.calcola(ctx, half_life=hl, trend_intensity=ti,
                                     usa_avversario=True)
                except Exception:
                    continue
                base.append((ctx.get('lega_vera') or '?', ruolo, data, p, reale, slug))
            reali = [r[4] for r in base]
            giorni = [r[2] for r in base]
            senza = [r[3] for r in base]
            # tabella sd_atteso "righello contemporaneo" (p62): fresca su
            # QUESTO campione/half_life, mai un esito realizzato dentro.
            tab_sd = S21.costruisci_tabella_sd_atteso([
                {'lega': lega, 'codice': RUOLO_CODICE.get(ruolo, ruolo), '_cal': p}
                for lega, ruolo, _g, p, _r, _s in base])
            con = applica_grade(base, idx_grade, tab_sd)
            m1, c1, l1, _n1 = metriche(senza, reali, giorni)
            m2, c2, l2, n2 = metriche(con, reali, giorni)
            marca = '  <- produzione' if hl == prod else ''
            print('%-8g | %7.3f %7.3f %7s | %7.3f %7.3f %7s%s' %
                  (hl, m1, c1, ('%.1f' % l1) if l1 is not None else '--',
                   m2, c2, ('%.1f' % l2) if l2 is not None else '--', marca))
            righe_out.append({'half_life': hl, 'n': len(base), 'giornate': n2,
                              'senza': {'mae': m1, 'corr': c1, 'lift': l1},
                              'con': {'mae': m2, 'corr': c2, 'lift': l2}})
        esiti[b] = {'produzione': prod, 'righe': righe_out}
        print()

    out = os.path.join(_HERE, 'dati', 'halflife_con_grade_2026-08-14.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print(f"scritto: {out}")


if __name__ == '__main__':
    main()
