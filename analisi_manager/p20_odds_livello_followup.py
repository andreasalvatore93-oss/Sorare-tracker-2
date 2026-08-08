"""Follow-up al brief BRIEF_SONNET_ODDS_LIVELLO_ASSOLUTO_2026-08-09.txt (§8,
richiesto dall'utente 09/08/2026 notte). Quattro punti, nessuna query rete:

1. Livello GREZZO (non z-scorato) con k calibrato a parita' di effetto
   (§2b del brief originale, l'alternativa a §2c gia' fatta in
   p20_odds_livello_assoluto.py).
2. Perche' manca il 22,5% di copertura livello su allstar_u23, scomposto
   in tre gruppi diagnostici.
3. Il n=310 vs n=311 su mls_hotstreak: da dove viene la differenza.
4. Controllo 4c del brief (il ramo G deve riprodurre +5,98/+6,43-6,46) messo
   per iscritto in modo esplicito, con la spiegazione del punto 3 incorporata.

Riusa senza modifiche p19_nonarena_grade_scala, p16/p17, p12_backtest_
formazione_grade, p12_backtest_manager_grade, backtest_arene_previsioni e le
funzioni gia' scritte in p20_odds_livello_assoluto.py (annota_segnali,
livello_per_carta, delta_vs, ecc.) -- nessuna riscrittura del knapsack
(D7 CLAUDE.md), nessuna modifica alla produzione.
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
import backtest_arene_previsioni as prev
import p20_odds_livello_assoluto as P20L

RUOLO_FULL = P20L.RUOLO_FULL
BASI = P20L.BASI

# Target dei medesimi ruoli/basi ricavati dal delta GREZZO k=0.2 (§9.1 di
# HANDOFF_ODDS_SEGNALE_DOPO_G_2026-08-08.txt, controllo gia' fatto e
# committato, non ricalcolato qui): lo scostamento mediano che il livello
# grezzo deve avvicinare per essere "a parita' di effetto" col delta.
TARGET_MEDIANA = {
    'allstar_u23': {'GK': 0.5, 'DEF': 1.8, 'MID': 1.6, 'FWD': 1.7},
    'mls_hotstreak': {'GK': 0.5, 'DEF': 1.7, 'MID': 1.7, 'FWD': 1.7},
}

K_GRID = [0.02, 0.05, 0.08, 0.1, 0.13, 0.16, 0.2, 0.25, 0.3, 0.35, 0.4]


# ===================================================================
# Punto 1 -- livello grezzo, k calibrato a parita' di effetto (§2b)
# ===================================================================
def applica_livello_raw(pool_rows, policy):
    """policy: codice -> k. Applica atteso_raw*(1+k*_livello_odds) SENZA
    z-score (a differenza di applica() in p20_odds_livello_assoluto.py).
    Scrive _lraw_cal e _lraw_combinato (stessa formula additiva)."""
    for r in pool_rows:
        k = policy.get(r['codice']) or 0.0
        l = r.get('_livello_odds')
        if k and l is not None:
            raw_adj = r['atteso_raw'] * (1.0 + k * l)
        else:
            raw_adj = r['atteso_raw']
        r['_lraw_cal'] = S21.bfg.calibra(raw_adj, r['codice'])
    gruppi = collections.defaultdict(list)
    for r in pool_rows:
        gruppi[(r['lega'], r['codice'])].append(r)
    for (_lg, _cod), membri in gruppi.items():
        _z, sd, _m = S21.zscore_gruppo([m['_lraw_cal'] for m in membri])
        for m in membri:
            m['_lraw_combinato'] = m['_lraw_cal'] + sd * m.get('_zgrade', 0.0)


def mediana_scostamento(unita, cod):
    scarti = []
    n_tot = n_camb = 0
    for u in unita:
        for r in u['pool_rows']:
            if r['codice'] != cod:
                continue
            n_tot += 1
            diff = abs(r['_lraw_cal'] - r['_cal'])
            if diff > 1e-9:
                n_camb += 1
                scarti.append(diff)
    scarti.sort()
    med = scarti[len(scarti) // 2] if scarti else 0.0
    mx = scarti[-1] if scarti else 0.0
    return med, mx, n_camb, n_tot


def calibra_k_raw(unita, nome_base):
    """Per ogni ruolo, cerca nella griglia K_GRID il k che avvicina di piu'
    la mediana di scostamento al target (delta grezzo k=0.2, §9.1)."""
    out = {}
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        target = TARGET_MEDIANA[nome_base][cod]
        migliore = None
        righe_k = []
        for k in K_GRID:
            policy = {cod: k}
            for u in unita:
                applica_livello_raw(u['pool_rows'], policy)
            med, mx, n_camb, n_tot = mediana_scostamento(unita, cod)
            righe_k.append({'k': k, 'mediana': med, 'massimo': mx, 'n_cambiate': n_camb, 'n_tot': n_tot})
            dist = abs(med - target)
            if migliore is None or dist < migliore[1]:
                migliore = (k, dist, med, mx, n_camb, n_tot)
        out[cod] = {'target_mediana': target, 'k_scelto': migliore[0],
                     'mediana_ottenuta': migliore[2], 'massimo_ottenuto': migliore[3],
                     'n_cambiate': migliore[4], 'n_tot': migliore[5], 'griglia': righe_k}
        print(f'  [{nome_base}/{cod}] target mediana={target}  k scelto={migliore[0]}  '
              f'mediana ottenuta={migliore[2]:.3f}  massimo={migliore[3]:.3f}  '
              f'({migliore[4]}/{migliore[5]} carte cambiate)')
    return out


def test_livello_raw(unita, ris_G, k_per_ruolo, nome_base):
    """3a-equivalente per il livello grezzo coi k calibrati sopra: G+Lraw
    (k specifico per ruolo) contro G."""
    esiti = {}
    for cod in ('GK', 'DEF', 'MID', 'FWD'):
        k = k_per_ruolo[cod]['k_scelto']
        policy = {cod: k}
        for u in unita:
            applica_livello_raw(u['pool_rows'], policy)
        d, lo, hi, cnt, _ = P20L.delta_vs(unita, '_lraw_combinato', '_combinato', ris_G)
        print(f'  1 [{nome_base}/{cod} k={k}]  G+Lraw vs G: delta={d:+.3f} IC95=[{lo:+.3f},{hi:+.3f}] n={cnt}')
        esiti[cod] = {'k': k, 'delta': d, 'ic': [lo, hi], 'n': cnt}
    positivi = [c for c, v in esiti.items() if v['ic'][0] is not None and v['ic'][0] > 0]
    print(f'  ruoli positivi (livello grezzo, k calibrato): {positivi or "nessuno"}')
    return esiti, positivi


# ===================================================================
# Punto 2 -- copertura mancante scomposta in tre gruppi
# ===================================================================
def diagnosi_livello(cache, slug, ruolo_full, fine):
    """Ripercorre gli stessi passi di prev.contesto() SENZA modificarla (e'
    produzione), solo per classificare il PERCHE' di un fallimento. Tre
    gruppi possibili quando il livello e' None:
      target_non_trovato            -- partita_target() non trova la
                                        partita bersaglio nella finestra
      finestra_storica_insufficiente-- la finestra storica del giocatore
                                        non e' costruibile (stesso motivo
                                        per cui anche il DELTA fallirebbe)
      quote_partita_mancanti        -- contesto ok, ma _p_own_opp_odds
                                        non trova una riga di quote per
                                        la partita bersaglio (l'unico
                                        motivo specifico del livello, dato
                                        che qui non serve lo storico)"""
    modulo = prev._MODULO.get(ruolo_full)
    if modulo is None:
        return 'ruolo_sconosciuto'
    target = prev.partita_target(cache, slug, fine)
    if target is None:
        return 'target_non_trovato'
    competizione = ((target['anyGame'].get('competition') or {}).get('slug'))
    usable, presenza = prev.finestra_storica(cache, slug, prev._data(target), competizione)
    if not usable:
        return 'finestra_storica_insufficiente'
    squadra = prev._squadra(usable, competizione)
    g = target['anyGame']
    casa_t, fuori_t = g.get('homeTeam') or {}, g.get('awayTeam') or {}
    if casa_t.get('slug') == squadra:
        opp_slug = fuori_t.get('slug')
    elif fuori_t.get('slug') == squadra:
        opp_slug = casa_t.get('slug')
    else:
        opp_slug = None
    ora = prev._p_own_opp_odds(squadra, opp_slug, prev._data(target))
    if ora is None:
        return 'quote_partita_mancanti'
    return 'ok'


def scomponi_copertura(unita, cache, nome_base):
    """Stessa unita' di conteggio di annota_segnali/CONTROLLO 4b (ogni RIGA
    di ogni pool_rows, non deduplicata per carta): cosi' il totale e il
    77,5%/59,9% coincidono esattamente coi numeri gia' riportati."""
    conta = collections.Counter()
    import datetime as _dt
    _cache_diag = {}
    for u in unita:
        bounds = M.parse_fixture_bounds(u['gw'])
        d_start, d_end = bounds
        fine = _dt.datetime(d_end.year, d_end.month, d_end.day, 23, 59)
        for r in u['pool_rows']:
            key = (r['slug'], RUOLO_FULL[r['codice']], fine.isoformat())
            if key in _cache_diag:
                motivo = _cache_diag[key]
            else:
                motivo = diagnosi_livello(cache, r['slug'], RUOLO_FULL[r['codice']], fine)
                _cache_diag[key] = motivo
            conta[motivo] += 1
    tot = sum(conta.values())
    mancante = tot - conta.get('ok', 0)
    print(f'  [{nome_base}] carte-giornata unita (contate una volta): {tot}  ok={conta.get("ok",0)} '
          f'({100*conta.get("ok",0)/tot:.1f}%)  mancante={mancante} ({100*mancante/tot:.1f}%)')
    for motivo in ('target_non_trovato', 'finestra_storica_insufficiente', 'quote_partita_mancanti', 'ruolo_sconosciuto'):
        n = conta.get(motivo, 0)
        if n:
            print(f'      {motivo:32s} n={n:6d}  ({100*n/tot:.1f}% del totale, {100*n/mancante:.1f}% del mancante)' if mancante else
                  f'      {motivo:32s} n={n:6d}')
    return dict(conta), tot, mancante


# ===================================================================
# Punto 3 -- n=310 vs n=311 su mls_hotstreak
# ===================================================================
def indaga_discrepanza_n(unita, ris_G):
    """delta_vs() conta le formazioni dove SIA ris_x (variabile secondo
    ruolo/policy) SIA ris_G (fisso) non sono None, allineate per indice a
    formazioni_valide. Cerca quale/i formazione fallisce a costruirsi sotto
    quale policy per capire da dove nasce il conteggio diverso fra ruoli."""
    ris_A = P20L.gioca_e_misura(unita, '_cal')
    print(f'  ris_A non-None: {sum(1 for x in ris_A if x)}   ris_G non-None: {sum(1 for x in ris_G if x)}   '
          f'totale formazioni_valide: {sum(len(u["formazioni_valide"]) for u in unita)}')

    # Applica k=0.2 grezzo su FWD (quella che nel run precedente dava n=310
    # invece di 311) e confronta indice per indice con GK (che dava 311).
    for cod_test in ('GK', 'FWD'):
        policy = {cod_test: 0.2}
        for u in unita:
            P20L.applica(u['pool_rows'], policy, policy)
        ris_x = P20L.gioca_e_misura(unita, '_l_combinato')
        n_none_x = sum(1 for x in ris_x if x is None)
        n_none_g = sum(1 for g in ris_G if g is None)
        # indici dove uno dei due e' None e l'altro no (causa della differenza di cnt)
        divergenti = [(i, x, g) for i, (x, g) in enumerate(zip(ris_x, ris_G)) if (x is None) != (g is None)]
        print(f'  policy={{{cod_test}: 0.2}}  ris_x None={n_none_x}  ris_G None={n_none_g}  '
              f'indici divergenti (uno None, l\'altro no)={len(divergenti)}')
        if divergenti:
            for i, x, g in divergenti[:5]:
                # ricostruisci manager/gw/competizione dall'indice piatto
                idx = i
                for u in unita:
                    if idx < len(u['formazioni_valide']):
                        f = u['formazioni_valide'][idx]
                        print(f'      indice={i} manager={u["manager"]} gw={u["gw"]} '
                              f'competizione={f.get("competizione")}  ris_x={"None" if x is None else "ok"}  '
                              f'ris_G={"None" if g is None else "ok"}')
                        break
                    idx -= len(u['formazioni_valide'])


# ===================================================================
# main
# ===================================================================
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

    esito = {}
    unita_per_base = {}
    for nome_base, (base_pulita_fn, _out_prefix) in BASI.items():
        unita, scarti, conta, n_gw = P19.raccogli(base_pulita_fn, files, idx_per_slug_full, lega_di,
                                                    scala_globale, osservazioni)
        cache = P19.cache
        P20L.annota_segnali(unita, cache)
        unita_per_base[nome_base] = unita

    print('=' * 78)
    print('PUNTO 4 -- CONTROLLO 4c messo per iscritto (esplicito)')
    print('=' * 78)
    ris_G_per_base = {}
    for nome_base, unita in unita_per_base.items():
        ris_A = P20L.gioca_e_misura(unita, '_cal')
        ris_G = P20L.gioca_e_misura(unita, '_combinato')
        ris_G_per_base[nome_base] = ris_G
        n_pairs = sum(1 for a, g in zip(ris_A, ris_G) if a and g)
        a_tot = P20L.media(x['punti'] for x in ris_A if x)
        g_tot = P20L.media(x['punti'] for x in ris_G if x)
        atteso_ref = {'allstar_u23': (5.98, 864), 'mls_hotstreak': (6.46, 310)}[nome_base]
        match = abs((g_tot - a_tot) - atteso_ref[0]) < 0.02
        print(f'  [{nome_base}] A={a_tot:.2f} G={g_tot:.2f} delta={g_tot-a_tot:+.2f} n={n_pairs}  '
              f'atteso={atteso_ref[0]:+.2f} n={atteso_ref[1]}  MATCH={"SI" if match else "NO -- verificare"}')
        esito[f'4c_{nome_base}'] = {'A': a_tot, 'G': g_tot, 'delta': g_tot - a_tot, 'n': n_pairs, 'match': match}

    print('\n' + '=' * 78)
    print('PUNTO 3 -- n=310 vs n=311 su mls_hotstreak')
    print('=' * 78)
    indaga_discrepanza_n(unita_per_base['mls_hotstreak'], ris_G_per_base['mls_hotstreak'])

    print('\n' + '=' * 78)
    print('PUNTO 2 -- copertura mancante del livello, tre gruppi diagnostici')
    print('=' * 78)
    esito['copertura_diagnostica'] = {}
    for nome_base, unita in unita_per_base.items():
        cache = P19.cache
        conta, tot, mancante = scomponi_copertura(unita, cache, nome_base)
        esito['copertura_diagnostica'][nome_base] = {'conta': conta, 'tot': tot, 'mancante': mancante}

    print('\n' + '=' * 78)
    print('PUNTO 1 -- livello grezzo, k calibrato a parita\' di effetto (§2b)')
    print('=' * 78)
    esito['livello_raw'] = {}
    for nome_base, unita in unita_per_base.items():
        print(f'\n-- {nome_base}: calibrazione k --')
        k_per_ruolo = calibra_k_raw(unita, nome_base)
        print(f'-- {nome_base}: test G+Lraw vs G coi k calibrati --')
        esiti, positivi = test_livello_raw(unita, ris_G_per_base[nome_base], k_per_ruolo, nome_base)
        esito['livello_raw'][nome_base] = {'k_calibrazione': k_per_ruolo, 'test': esiti, 'ruoli_positivi': positivi}

    with open('analisi_manager/p20_odds_livello_followup_out.json', 'w', encoding='utf-8') as fh:
        json.dump(esito, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_odds_livello_followup_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
