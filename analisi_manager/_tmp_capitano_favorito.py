# -*- coding: utf-8 -*-
"""Capitano: variante 'favorita/sfavorita' (12/08/2026, orchestratore).
Domanda: scegliere il capitano guardando quanto la SUA partita e' piu'
facile del solito (delta_favorito, modello interno; delta_favorito_odds,
quote di mercato) cattura piu' del 15% attuale sull'archivio pulito?
Stesse 1145 arene del test grade, stesso schema di misura. Zero query
(tutto da cache locale + dati_globali/odds_1x2_index.json gia' in repo).
"""
import os, sys, io, json, glob, math, random, collections, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = os.path.abspath('.')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p24_binario2_ga as B2

random.seed(7)
cache = CACHE.CacheLocale()
GK_CAPTAIN_MARGIN = 6.7
ROLE_FULL = {'GK': 'Goalkeeper', 'DEF': 'Defender', 'MID': 'Midfielder', 'FWD': 'Forward'}

# --- 1. indice (manager,fixture)->path e ->primo_kickoff/fine_giornata ---
fixtures = B2.elenca_fixture()
path_di = {(m, fx): p for m, fx, p in fixtures}
kickoff_cache = {}


def kickoff_e_giornata(manager, fixture):
    key = (manager, fixture)
    if key in kickoff_cache:
        return kickoff_cache[key]
    path = path_di.get(key)
    if path is None:
        kickoff_cache[key] = (None, None)
        return None, None
    righe = B2.carica_formazioni(path)
    pool, _escluse = B2.costruisci_pool_carte(righe)
    fine_giornata = B2.fine_giornata_da_slug(fixture)
    primo_kickoff = B2.trova_primo_kickoff(pool, fine_giornata) if pool else None
    kickoff_cache[key] = (fine_giornata, primo_kickoff)
    return fine_giornata, primo_kickoff


# --- 2. _cal per (manager,fixture,slug) dall'aggregato pool ---
pool_rows = json.load(open('archivio_ufficiale/aggregato/binario2_pool_rows.json', encoding='utf-8'))
cal_di = {}
for r in pool_rows:
    cal_di[(r['manager'], r['fixture'], r['slug'])] = r['_cal']

# --- 3. le 1145 arene reali (ris_A) ---
out = json.load(open('archivio_ufficiale/aggregato/binario2_out.json', encoding='utf-8'))
arene = []
for entry in out['per_gw']:
    manager, fixture = entry['manager'], entry['fixture']
    for a in entry['ris_A']:
        arene.append((manager, fixture, a['carte']))
print('n arene =', len(arene))

# --- 4. per ogni arena, calcola df/dfo per le 5 carte ---
righe_calc = []
n_no_join = 0
n_dfo_zero_su_5 = 0
for manager, fixture, carte in arene:
    fine_giornata, primo_kickoff = kickoff_e_giornata(manager, fixture)
    if fine_giornata is None or primo_kickoff is None:
        n_no_join += 1
        continue
    ok = True
    riga = {'manager': manager, 'fixture': fixture, 'carte': []}
    n_dfo_ok = 0
    for c in carte:
        slug, ruolo_c, reale, oggi_flag = c['slug'], c['ruolo'], c['reale'], c['capitano']
        cal = cal_di.get((manager, fixture, slug))
        if cal is None:
            ok = False
            break
        ruolo_full = ROLE_FULL.get(ruolo_c)
        ctx = P.contesto(cache, slug, ruolo_full, fine_giornata, cutoff_giornata=primo_kickoff)
        df = P.delta_favorito(ctx) if ctx else None
        dfo = P.delta_favorito_odds(ctx) if ctx else None
        if dfo is not None:
            n_dfo_ok += 1
        riga['carte'].append(dict(slug=slug, ruolo=ruolo_c, reale=reale, oggi=oggi_flag,
                                  cal=cal, df=df, dfo=dfo))
    if not ok or len(riga['carte']) != 5:
        n_no_join += 1
        continue
    if n_dfo_ok == 0:
        n_dfo_zero_su_5 += 1
    righe_calc.append(riga)

print('arene con join completo =', len(righe_calc), ' (scartate:', n_no_join, ')')
print('arene con ALMENO una carta con quote odds disponibili =', len(righe_calc) - n_dfo_zero_su_5,
      '/', len(righe_calc))


def scegli(riga, criterio):
    carte = riga['carte']
    outfield = [c for c in carte if c['ruolo'] != 'GK']
    gk = [c for c in carte if c['ruolo'] == 'GK']
    vals = [(c, criterio(c)) for c in outfield]
    vals_ok = [(c, v) for c, v in vals if v is not None]
    if not vals_ok:
        vals_ok = [(c, c['cal']) for c in outfield]
    best_c, best_v = max(vals_ok, key=lambda cv: cv[1])
    if criterio.__name__ == 'crit_cal' and gk:
        bg = max(gk, key=lambda c: c['cal'])
        if bg['cal'] >= best_c['cal'] + GK_CAPTAIN_MARGIN:
            return bg
    return best_c


def crit_cal(c):
    return c['cal']


def crit_df(c):
    return c['df']


def crit_dfo(c):
    return c['dfo']


def bonus_di(riga, scelto):
    return 0.2 * scelto['reale']


def bonus_a_caso(riga):
    return sum(0.2 * c['reale'] for c in riga['carte']) / 5.0


def bonus_senno(riga):
    return 0.2 * max(c['reale'] for c in riga['carte'])


def valuta(criterio):
    bonus_tot = 0.0
    scelte = []
    for riga in righe_calc:
        s = scegli(riga, criterio)
        b = bonus_di(riga, s)
        bonus_tot += b
        scelte.append(b)
    n = len(righe_calc)
    bonus_medio = bonus_tot / n
    return bonus_medio, scelte


n = len(righe_calc)
bonus_caso = sum(bonus_a_caso(r) for r in righe_calc) / n
bonus_senno_v = sum(bonus_senno(r) for r in righe_calc) / n
guadagno_senno = bonus_senno_v - bonus_caso

print('')
print('bonus a caso =', round(bonus_caso, 4), ' | bonus senno di poi =', round(bonus_senno_v, 4),
      ' | guadagno max =', round(guadagno_senno, 4))

risultati = {}
for nome, criterio in (('oggi (_cal, A/A)', crit_cal),
                        ('favorito interno (df)', crit_df),
                        ('favorito quote (dfo)', crit_dfo)):
    bonus_medio, scelte = valuta(criterio)
    guadagno = bonus_medio - bonus_caso
    pct = 100 * guadagno / guadagno_senno
    risultati[nome] = scelte
    print('%-24s bonus=%.4f guadagno=%+.4f  pctmax=%5.1f%%  n=%d' % (nome, bonus_medio, guadagno, pct, n))

# combinato cal+df, z-standardizzato
for riga in righe_calc:
    outfield = [c for c in riga['carte'] if c['ruolo'] != 'GK']
    cals = [c['cal'] for c in outfield]
    mc = sum(cals) / len(cals)
    sc = (sum((x - mc) ** 2 for x in cals) / len(cals)) ** 0.5 or 1.0
    dfs = [c['df'] for c in outfield if c['df'] is not None]
    md = sd = None
    if dfs:
        md = sum(dfs) / len(dfs)
        sd = (sum((x - md) ** 2 for x in dfs) / len(dfs)) ** 0.5 or 1.0
    for c in riga['carte']:
        if c['ruolo'] == 'GK' or c['df'] is None or not dfs:
            c['_combo'] = None
            continue
        c['_combo'] = 0.5 * (c['cal'] - mc) / sc + 0.5 * (c['df'] - md) / sd


def crit_combo_real(c):
    return c.get('_combo')


bonus_medio, scelte = valuta(crit_combo_real)
guadagno = bonus_medio - bonus_caso
pct = 100 * guadagno / guadagno_senno
print('%-24s bonus=%.4f guadagno=%+.4f  pctmax=%5.1f%%  n=%d' % ('combinato cal+df', bonus_medio, guadagno, pct, n))
risultati['combinato cal+df'] = scelte


def t_test_appaiato(a, b):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = sum(d) / n
    sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
    se = sd / (n ** 0.5)
    return m, (m / se if se else None)


print('')
print('t-test appaiato vs oggi (_cal):')
base = risultati['oggi (_cal, A/A)']
for nome in ('favorito interno (df)', 'favorito quote (dfo)', 'combinato cal+df'):
    m, t = t_test_appaiato(risultati[nome], base)
    print('  %-24s delta medio=%+.4f  t=%s' % (nome, m, ('%.2f' % t) if t is not None else 'None'))

print('')
print('dump 6 arene:')
for riga in righe_calc[::max(1, len(righe_calc) // 6)][:6]:
    print(' ', riga['manager'], riga['fixture'])
    for c in riga['carte']:
        df_s = ('%.3f' % c['df']) if c['df'] is not None else 'None'
        dfo_s = ('%.3f' % c['dfo']) if c['dfo'] is not None else 'None'
        print('    %-30s %-4s cal=%.1f df=%s dfo=%s reale=%.1f oggi=%s'
              % (c['slug'][:30], c['ruolo'], c['cal'], df_s, dfo_s, c['reale'], c['oggi']))
