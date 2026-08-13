# -*- coding: utf-8 -*-
"""HALF_LIFE rimisurato col GRADE ACCESO (13/08/2026, domanda dell'utente).

PERCHE'. La rimisura di oggi (§8quindecies) giudicava tutto su `atteso`, ma la
produzione NON schiera su `atteso`: schiera su
    atteso_combinato = atteso + sd_atteso_del_gruppo * z_grade
(build_formazione_globale._apply_grade_group, GRADE_ENABLED='1' dal 07/08).
E nel banco di prova la parola "grade" non compare nemmeno una volta: quindi
la misura precedente descrive un modello che in produzione non esiste piu'.
Domanda: con il voto acceso, l'half-life migliore si sposta?

COME. Stesso metro, stessa griglia, ma ogni riga viene punteggiata due volte
sullo STESSO campione: senza voto e col voto. Il confronto e' appaiato, quindi
la differenza non puo' venire da campioni diversi.

IL GRUPPO E' (lega, ruolo, giorno), come in produzione: una run copre una
giornata, quindi il gruppo nativo (lega, ruolo) di quella run coincide.
Media e sd si calcolano DENTRO il gruppo, come fa `_apply_grade_group`, e se
il gruppo ha meno di 2 voti o tutti uguali lo z e' 0 -- cioe' il voto non
entra, esattamente come in produzione.

LIMITE DEL CAMPIONE, da tenere presente leggendo i numeri: lo storico dei voti
copre il 16-21% delle righe in cache e non e' un campione casuale (fu raccolto
su giocatori presi dai file manager, cioe' gente che qualcuno schierava
davvero). Dentro quel sottoinsieme pero' i gruppi reggono: 92% delle carte in
gruppi usabili, mediana 3 carte. Quindi la domanda "il voto sposta l'ottimo?"
si puo' fare; "di quanto esattamente" su tutta la popolazione, no.

Uso: python analisi_manager/p37_halflife_con_grade.py --ruoli gk,def,mid,fwd
"""
import os
import sys
import glob
import json
import argparse
import statistics
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import backtest_arene_cache
import backtest_arene_previsioni as prev
from taratura_confronto_parametri import raccogli, lift_selezione
from taratura_halflife_trend import RUOLI

GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}   # come produzione


def carica_grade():
    """(slug, giorno) -> lettera, da tutti gli storici gia' in repo."""
    fuori = {}
    for path in sorted(glob.glob(os.path.join(
            _HERE, 'dati', 'storico_grade_*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                dati = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        righe = dati if isinstance(dati, list) else dati.get('giocatori', [])
        if not isinstance(righe, list):
            continue
        for r in righe:
            if not isinstance(r, dict):
                continue
            slug, voto = r.get('slug'), r.get('grade')
            giorno = (r.get('game_date') or r.get('data') or '')[:10]
            if slug and voto in GRADE_NUM and len(giorno) == 10:
                fuori[(slug, giorno)] = voto
    return fuori


def applica_grade(righe):
    """righe: [(lega, ruolo, giorno, previsione, reale, voto)] ->
    lista di previsioni combinate, con la stessa formula della produzione."""
    gruppi = defaultdict(list)
    for i, (lega, ruolo, giorno, _p, _r, _v) in enumerate(righe):
        gruppi[(lega, ruolo, giorno)].append(i)
    fuori = [r[3] for r in righe]
    for indici in gruppi.values():
        attesi = [righe[i][3] for i in indici]
        voti = [GRADE_NUM[righe[i][5]] for i in indici if righe[i][5]]
        if len(attesi) < 2 or len(voti) < 2:
            continue
        m_a = statistics.mean(attesi)
        sd_a = statistics.pstdev(attesi)
        m_v = statistics.mean(voti)
        sd_v = statistics.pstdev(voti)
        if sd_a <= 0 or sd_v <= 0:
            continue
        for i in indici:
            v = righe[i][5]
            if not v:
                continue
            z = (GRADE_NUM[v] - m_v) / sd_v
            fuori[i] = righe[i][3] + sd_a * z
    return fuori


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

    voti = carica_grade()
    print(f"voti storici disponibili: {len(voti)} coppie (giocatore, giorno)\n")
    brevi = [r.strip() for r in args.ruoli.split(',') if r.strip()]
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    punti = raccogli(cache, slugs, {RUOLI[b] for b in brevi}, args.max or None)

    # SOLO i punti che hanno il voto: e' l'unico modo di confrontare acceso e
    # spento sullo STESSO campione. Confrontare "tutti senza voto" contro
    # "quelli col voto, col voto" mescolerebbe due cose diverse.
    punti = [p for p in punti if (p[1], p[2]) in voti]
    print(f"{len(punti)} punti con voto storico\n")

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
                base.append((ctx.get('lega_vera') or '?', ruolo, data, p, reale,
                             voti.get((slug, data))))
            reali = [r[4] for r in base]
            giorni = [r[2] for r in base]
            senza = [r[3] for r in base]
            con = applica_grade(base)
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

    out = os.path.join(_HERE, 'dati', 'halflife_con_grade_2026-08-13.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(esiti, fh, ensure_ascii=False, indent=2)
    print(f"scritto: {out}")


if __name__ == '__main__':
    main()
