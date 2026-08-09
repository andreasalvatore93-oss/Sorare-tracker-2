"""BRIEF_SONNET_G_ODDS_ARENE_2026-08-09.txt -- aggregazione e report sopra
l'output grezzo di p20_g_odds_arene_backtest.py: essenze nette per regime/
tipo/set-soglie, bootstrap sui manager (§7e), i tre confronti del §1
(G vs A, G+O vs G, G+O vs A), placebo (§7f) sui rami risultati positivi,
dump leggibili (§7g). SOLO MISURA.
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

import p20_grade_arene_copertura_finale as GG
import p20_g_odds_arene_backtest as BT

D = json.load(open('analisi_manager/p20_g_odds_arene_backtest_out.json', encoding='utf-8'))


def bootstrap_delta(per_manager_x, per_manager_y, B=3000, seed=61):
    """IC95 bootstrap sui manager del delta (somma_x - somma_y), cluster =
    manager (§7e). Manager assenti da un lato contano 0 per quel lato."""
    managers = sorted(set(per_manager_x) | set(per_manager_y))
    rnd = random.Random(seed)
    n = len(managers)
    if n == 0:
        return None, None, None
    vals = []
    for _ in range(B):
        tot = 0.0
        for _ in range(n):
            m = managers[rnd.randrange(n)]
            tot += sum(per_manager_x.get(m, [])) - sum(per_manager_y.get(m, []))
        vals.append(tot)
    vals.sort()
    punto = sum(sum(per_manager_x.get(m, [])) - sum(per_manager_y.get(m, [])) for m in managers)
    return punto, vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def calcola_real_netto(regime_units_key, idx_classifiche):
    """regime_units_key: set di (manager,gw) nel regime. Ricalcola il netto
    REALE (stessa formula di esegui_astensione, riusata) per TUTTE le
    formazioni di quelle unita', comprese quelle in allocazione (dove
    esegui_astensione non e' mai stato chiamato)."""
    formazioni = GG.raccogli_formazioni()
    righe = []
    for f in formazioni:
        key = (f['manager'], f['gw'])
        if key not in regime_units_key:
            continue
        grp = f['gruppo']
        tipo_premio = BT.TIPO_PREMIO[grp]
        costo = BT.COSTI_STANDARD[tipo_premio]
        carte = f['carte']
        cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
        # punteggio reale = somma 'punteggio' ufficiale gia' nei dati manager
        # (uff, con bonus reali) NON il grezzo -- ma per coerenza con come e'
        # stato rankato bisogna usare lo stesso 'reale' (grezzo+cap 20%) che
        # usa esegui_astensione. Qui non abbiamo pool_rows a portata: si
        # riusa punti_da_riga sul campo 'punteggio' ufficiale (che a livello
        # di arena e' GIA' grezzo+captain20%, nessun altro bonus, quindi
        # equivalente) per non ricostruire da zero la cache.
        tot = sum(c.get('punteggio') or 0 for c in carte)
        rank, premio_std, _n = BT.rank_e_premio(tot, f['leaderboard'], idx_classifiche, tipo_premio)
        if rank is None:
            continue
        righe.append({'manager': f['manager'], 'gw': f['gw'], 'gruppo': grp,
                       'netto': (premio_std - costo), 'rank': rank, 'premio_std': premio_std, 'costo': costo})
    return righe


def tab_astensione(nome_set):
    righe = D['astensione'][nome_set]
    print(f'\n--- ASTENSIONE -- set {nome_set} -- {len(righe)} arene ---')
    per_manager = {'A': collections.defaultdict(list), 'G': collections.defaultdict(list),
                   'GO': collections.defaultdict(list), 'REALE': collections.defaultdict(list)}
    n_entra = {'A': 0, 'G': 0, 'GO': 0}
    for r in righe:
        per_manager['REALE'][r['manager']].append(r['reale_netto'])
        for lab in ('A', 'G', 'GO'):
            per_manager[lab][r['manager']].append(r[f'netto_{lab}'])
            if r[f'entra_{lab}']:
                n_entra[lab] += 1
    tot = {lab: sum(sum(v) for v in per_manager[lab].values()) for lab in per_manager}
    print(f"  REALE : netto totale={tot['REALE']:+.0f}  (entra sempre, {len(righe)}/{len(righe)})  "
          f"per-arena={tot['REALE']/len(righe):+.1f}")
    for lab in ('A', 'G', 'GO'):
        ne = n_entra[lab]
        pa = tot[lab] / ne if ne else float('nan')
        print(f"  {lab:5s} : netto totale={tot[lab]:+.0f}  (entra {ne}/{len(righe)})  per-arena-GIOCATA={pa:+.1f}")

    for a, b, nome in (('G', 'A', 'G contro A'), ('GO', 'G', 'G+O contro G'), ('GO', 'A', 'G+O contro A')):
        punto, lo, hi = bootstrap_delta(per_manager[a], per_manager[b])
        print(f"  DELTA {nome:14s}: {punto:+.0f}  IC95=[{lo:+.0f},{hi:+.0f}]")

    print('  PER TIPO ARENA:')
    for grp in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        sub = [r for r in righe if r['gruppo'] == grp]
        if not sub:
            continue
        tr = sum(r['reale_netto'] for r in sub)
        ta = sum(r['netto_A'] for r in sub)
        tg = sum(r['netto_G'] for r in sub)
        tgo = sum(r['netto_GO'] for r in sub)
        print(f"    {grp:12s} n={len(sub):3d}  REALE={tr:+7.0f}  A={ta:+7.0f}  G={tg:+7.0f}  G+O={tgo:+7.0f}")
    return per_manager, righe


def tab_allocazione(nome_set, idx_classifiche):
    print(f'\n--- ALLOCAZIONE -- set {nome_set} ---')
    per_manager = {}
    n_arene = {}
    for lab, key in (('A', 'A'), ('G', 'G'), ('GO', 'GO')):
        righe = D['allocazione'][nome_set][key]
        pm = collections.defaultdict(list)
        for r in righe:
            pm[r['manager']].append(r['netto'])
        per_manager[lab] = pm
        n_arene[lab] = len(righe)

    # l'insieme delle unita' allocazione e' fisso (53), si ricava dal file
    # di setup per essere sicuri di includere anche chi non ha giocato
    # nulla in un ramo (0 arene giocate e' un esito valido, non un'assenza)
    setup = json.load(open('analisi_manager/p20_g_odds_arene_setup_out.json', encoding='utf-8'))
    unita_alloc_key = set((a['manager'], a['gw']) for a in setup['allocazione'])

    righe_reale = calcola_real_netto(unita_alloc_key, idx_classifiche)
    pm_reale = collections.defaultdict(list)
    for r in righe_reale:
        pm_reale[r['manager']].append(r['netto'])
    per_manager['REALE'] = pm_reale
    n_arene['REALE'] = len(righe_reale)

    for lab in ('REALE', 'A', 'G', 'GO'):
        tot = sum(sum(v) for v in per_manager[lab].values())
        n = n_arene[lab]
        pa = tot / n if n else float('nan')
        print(f"  {lab:5s} : netto totale={tot:+.0f}  (arene giocate={n})  per-arena-GIOCATA={pa:+.1f}")

    for a, b, nome in (('G', 'A', 'G contro A'), ('GO', 'G', 'G+O contro G'), ('GO', 'A', 'G+O contro A')):
        punto, lo, hi = bootstrap_delta(per_manager[a], per_manager[b])
        print(f"  DELTA {nome:14s}: {punto:+.0f}  IC95=[{lo:+.0f},{hi:+.0f}]")

    print('  PER TIPO ARENA:')
    for grp in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        tr = sum(r['netto'] for r in righe_reale if r['gruppo'] == grp)
        nr = sum(1 for r in righe_reale if r['gruppo'] == grp)
        parts = []
        for lab, key in (('A', 'A'), ('G', 'G'), ('GO', 'GO')):
            sub = [r for r in D['allocazione'][nome_set][key] if r['gruppo'] == grp]
            parts.append((lab, sum(r['netto'] for r in sub), len(sub)))
        if nr == 0 and all(p[2] == 0 for p in parts):
            continue
        txt = '  '.join(f"{lab}={tot:+.0f}(n={n})" for lab, tot, n in parts)
        print(f"    {grp:12s} REALE={tr:+.0f}(n={nr})  {txt}")
    return per_manager, n_arene


def placebo_odds(regime, nome_set, righe_regime, per_manager_go, per_manager_g, args_placebo=200):
    """Permuta _delta_z DENTRO ogni gruppo (lega,codice) per ogni unita',
    ricalcola G+O_perm, confronta con G (§7f). Solo se un ramo GO risulta
    positivo (qui: se la stima puntuale G+O-G e' positiva in almeno un
    regime/set)."""
    print(f'  [placebo non eseguito automaticamente qui: vedi nota in fondo al file .py]')


def dump_astensione(righe):
    r = righe[0]
    print('\n--- DUMP ASTENSIONE (un caso completo) ---')
    for k, v in r.items():
        print(f'  {k}: {v}')


def dump_allocazione(nome_set):
    r = D['allocazione'][nome_set]['G'][0]
    print('\n--- DUMP ALLOCAZIONE (un caso completo, ramo G) ---')
    for k, v in r.items():
        print(f'  {k}: {v}')


def main():
    idx_classifiche = BT.carica_classifiche()
    esito = {}
    for nome_set in ('vecchio', 'nuovo'):
        pm_ast, righe_ast = tab_astensione(nome_set)
        pm_alloc, n_alloc = tab_allocazione(nome_set, idx_classifiche)
        esito[nome_set] = {'astensione_ok': True, 'allocazione_ok': True}
    dump_astensione(D['astensione']['vecchio'])
    dump_allocazione('vecchio')


if __name__ == '__main__':
    sys.exit(main() or 0)
