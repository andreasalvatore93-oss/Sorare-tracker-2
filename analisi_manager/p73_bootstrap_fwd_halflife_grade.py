# -*- coding: utf-8 -*-
"""BOOTSTRAP: su FWD, col voto acceso, l'ottimo si sposta DAVVERO da hl=6
(produzione) a hl~12-16, o e' dentro il rumore? (14/08/2026, domanda diretta
dell'utente dopo p37_halflife_con_grade.py corretto: "solo su FWD si sposta
l'ottimo?" -- risposta: si', DEF/MID sono gia' vicini al loro ottimo in
entrambe le colonne, GK e' troppo debole per fidarsene. Qui si mette alla
prova SOLO il caso FWD, l'unico dove la differenza (+1,6 punti di lift,
sostenuta su un plateau hl=12-60, non un picco isolato) sembrava reale.

METODO. Le previsioni (senza voto/hl=6, col voto/hl=6, col voto/hl=16) sono
calcolate UNA VOLTA SOLA (costoso: prev.calcola + applica_gruppi_grade).
Il bootstrap ricampiona GIOCATORI (slug) con reinserimento, non singole
righe: le partite dello stesso giocatore non sono osservazioni indipendenti
(stessa squadra, stessa qualita' di base) -- stesso principio del bootstrap
per manager gia' in uso altrove (analisi_manager/p12_backtest_manager_
perarena.py:33). Ad ogni ricampionamento si ricalcola il lift per hl=6 e
hl=16 SULLO STESSO campione ricampionato (appaiato: il rumore comune si
cancella), poi delta = lift(hl16) - lift(hl6).

Uso: python analisi_manager/p73_bootstrap_fwd_halflife_grade.py
"""
import os
import sys
import json
import random
import collections
import statistics

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
N_BOOT = 1000
SEME = 20260814


def con_voto(base, S21mod):
    """base: [(lega, ruolo, giorno, previsione, reale, slug)] -> lista
    combinati, formula corrente di produzione (stessa di p37/taratura)."""
    rows = []
    for lega, ruolo, giorno, p, _reale, slug in base:
        gn = S21mod.grade_in_finestra(idx_grade, slug, giorno)
        rows.append({'lega': lega, 'codice': RUOLO_CODICE.get(ruolo, ruolo),
                     '_cal': p, '_grade': gn})
    tab_sd = S21mod.costruisci_tabella_sd_atteso(rows)
    S21mod.applica_gruppi_grade(rows, modo='storica_completa',
                                tabella_sd_storica=tab_sd,
                                fattore_storico=S21mod.bfg.GRADE_FATTORE_STORICO)
    per_ruolo = collections.defaultdict(list)
    for r in rows:
        per_ruolo[r['codice']].append(r)
    for _codice, membri in per_ruolo.items():
        diffs = [r['_combinato'] - r['_cal'] for r in membri]
        media = sum(diffs) / len(diffs) if diffs else 0.0
        for r in membri:
            r['_combinato'] -= media
    return [r['_combinato'] for r in rows]


def lift_di(righe):
    """righe: [(slug, giorno, prevv, reale)] -> lift% (o None)."""
    finte = [(None, None, g, p, r) for _s, g, p, r in righe]
    lift, n_gg = lift_selezione(finte)
    return lift, n_gg


def main():
    global idx_grade
    idx_grade, _ = S21.carica_indice_grade()
    cache = backtest_arene_cache.CacheLocale()
    slugs = sorted(cache.slug_disponibili())
    punti = raccogli(cache, slugs, {RUOLI['fwd']}, None)
    punti = [p for p in punti
             if S21.grade_in_finestra(idx_grade, p[1], p[2]) is not None]
    print(f'{len(punti)} punti FWD con voto in finestra')

    modulo = punti[0][3]['modulo']
    ti = getattr(modulo, 'TREND_INTENSITY', 0.0)

    righe_per_hl = {}
    for hl in (6.0, 16.0):
        base = []
        for ruolo, slug, data, ctx, reale in punti:
            try:
                p = prev.calcola(ctx, half_life=hl, trend_intensity=ti, usa_avversario=True)
            except Exception:
                continue
            base.append((ctx.get('lega_vera') or '?', ruolo, data, p, reale, slug))
        con = con_voto(base, S21)
        righe_per_hl[hl] = [(slug, giorno, c, reale)
                            for (_l, _r, giorno, _p, reale, slug), c in zip(base, con)]
        m, _n = lift_di(righe_per_hl[hl])
        print(f'hl={hl}: lift col voto = {m:.2f}% (n={len(righe_per_hl[hl])}), campione intero')

    delta_oss = None
    l6, _ = lift_di(righe_per_hl[6.0])
    l16, _ = lift_di(righe_per_hl[16.0])
    delta_oss = l16 - l6
    print(f'\ndelta osservato (hl16 - hl6): {delta_oss:+.2f} punti di lift%\n')

    by_slug = collections.defaultdict(list)
    for i, (slug, giorno, c6, reale) in enumerate(righe_per_hl[6.0]):
        by_slug[slug].append(i)
    slug_list = list(by_slug)
    n = len(slug_list)
    print(f'{n} giocatori distinti (unita\' del bootstrap), {N_BOOT} ricampionamenti')

    r6, r16 = righe_per_hl[6.0], righe_per_hl[16.0]
    rnd = random.Random(SEME)
    diffs = []
    positivi = 0
    for b in range(N_BOOT):
        campionati = [slug_list[rnd.randrange(n)] for _ in range(n)]
        idx = [i for s in campionati for i in by_slug[s]]
        sub6 = [r6[i] for i in idx]
        sub16 = [r16[i] for i in idx]
        m6, _ = lift_di(sub6)
        m16, _ = lift_di(sub16)
        if m6 is None or m16 is None:
            continue
        d = m16 - m6
        diffs.append(d)
        if d > 0:
            positivi += 1
        if (b + 1) % 200 == 0:
            print(f'  [{b+1}/{N_BOOT}]', flush=True)

    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    print(f'\nbootstrap (n={len(diffs)} ricampionamenti validi):')
    print(f'  delta medio bootstrap: {statistics.mean(diffs):+.2f}')
    print(f'  IC95%: [{lo:+.2f}; {hi:+.2f}]')
    print(f'  % ricampionamenti con delta positivo: {100*positivi/len(diffs):.1f}%')

    out = os.path.join(_HERE, 'dati', 'bootstrap_fwd_halflife_grade_2026-08-14.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({'delta_osservato': delta_oss, 'n_giocatori': n,
                  'n_boot': len(diffs), 'ic95': [lo, hi],
                  'quota_positivi': positivi / len(diffs),
                  'diffs': diffs}, fh, ensure_ascii=False, indent=2)
    print(f'scritto: {out}')


if __name__ == '__main__':
    main()
