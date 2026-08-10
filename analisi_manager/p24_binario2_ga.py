"""BINARIO 2 -- G vs A, pool libero (10/08/2026).

Metodologia decisa in sessione con l'utente, seconda meta' di quanto fatto
per il Binario 1 (p23_binario1_mga.py, M vs G vs A a formazione fissa):

  - Si escludono le sole CARTE a 0/DNP dal pool (non l'intera formazione:
    qui l'unita' e' un pool di selezione, si salvano le altre 4 carte buone
    -- diverso apposta dal Binario 1).
  - G e A pescano e RICOMPONGONO liberamente dal pool: ognuno decide da solo
    quante arene giocare e di che tipo (riusa `genera_arene_efficienti`, LA
    funzione di produzione che decide mix e quantita' da sola in base alla
    resa attesa -- non reinventata qui).
  - Il confronto e' sul NETTO ESSENZE totale, non arena per arena (possono
    scegliere tipi diversi). Niente scalini arbitrari: si riusano
    PAREGGIO_ARENA/GUADAGNO_PER_PUNTO gia' calibrati in produzione su 2.125
    arene reali e 5.031 premi veri (stessa idea dello scalino manuale
    proposto, ma gia' misurata invece che a occhio).
  - La DECISIONE di quante arene entrare la prende l'ATTESO (come in
    produzione, un modello scommette prima di sapere il risultato). Il
    NETTO che riportiamo e' pero' calcolato sul REALIZZATO (il punteggio
    vero che quelle carte hanno fatto), altrimenti staremmo solo
    ri-misurando quanto ottimista e' l'atteso.
  - Walkforward pulito: stessa `cutoff_giornata` esplicita di Binario 1
    (primo kickoff della giornata), stesso completamento standard del
    grade mancante (completa_grade_mancante.py).
  - Punteggio REALE per carta: NON dalla cache game-log (rischio concreto,
    verificato su questa GW: le partite vere iniziano il 2 agosto, fuori
    dalla finestra 4-7 che il nome della fixture suggerisce -- una ricerca
    per data rischierebbe di non trovarle). Si usa invece `punteggio`
    dell'archivio (gia' verificato in fase di estrazione, tolleranza 0.5 vs
    ufficiale), diviso per 1.2 se quella carta era capitano nella sua
    formazione originale -- il grezzo cosi' ottenuto e' STABILE: verificato
    su carte presenti in piu' formazioni (es. Marvin Wanitzek: 120.0 da
    capitano in un'arena, 100.0 da non-capitano in un'altra della stessa
    GW -- 120/1.2=100.0 esatto).

Uso: python analisi_manager/p24_binario2_ga.py
"""
import os
import sys
import io
import json
import datetime
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import completa_grade_mancante as CG

cache = CACHE.CacheLocale()

ROLE_CODE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}
TIPI_ARENA = ['ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED',
             'ARENA_ALLSTARS_BEGINNER']

ARCHIVIO = os.path.join(ROOT, 'archivio_crowss', 'pre_2026-08-07',
                        'football-4-7-aug-2026_arene_limited.json')
FINE_GIORNATA = datetime.datetime(2026, 8, 7, 23, 59)


def carica_formazioni():
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    return d['righe']


def costruisci_pool_carte(righe):
    """Una voce per CARTA (id 'carta'), escluse le carte a 0/DNP (non le
    formazioni intere: qui l'unita' e' il pool, si salva il resto)."""
    pool = {}
    escluse = []
    for r in righe:
        for c in r['carte']:
            cid = c.get('carta')
            if not cid:
                continue
            if (c.get('punteggio') or 0.0) == 0.0:
                if cid not in pool:
                    escluse.append(c['nome'])
                continue
            if cid not in pool:
                pool[cid] = c
    return pool, escluse


def grezzo_da_archivio(c):
    """Punteggio SENZA bonus capitano, dal campo gia' verificato in
    archivio (README: coerenza carte/ufficiale, tolleranza 0.5)."""
    p = c.get('punteggio')
    if p is None:
        return None
    return p / 1.2 if c.get('capitano') else p


def trova_primo_kickoff(pool):
    date_target = []
    for c in pool.values():
        t = P.partita_target(cache, c['slug'], FINE_GIORNATA)
        if t is not None:
            dt = P._data(t)
            if dt is not None:
                date_target.append(dt)
    if not date_target:
        return None
    return min(date_target)


def prepara_pool_rows(pool, primo_kickoff, idx_grade, lega_di):
    rows = []
    scarti = collections.Counter()
    for cid, c in pool.items():
        ruolo = c['ruolo']
        cod = ROLE_CODE.get(ruolo)
        if cod is None:
            scarti['ruolo_sconosciuto'] += 1
            continue
        res = P.score_atteso(cache, c['slug'], ruolo, FINE_GIORNATA, cutoff_giornata=primo_kickoff)
        if res is None or res.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        reale = grezzo_da_archivio(c)
        if reale is None:
            scarti['no_reale'] += 1
            continue
        cal = S21.bfg.calibra(res['atteso'], cod)
        gnum = S21.grade_in_finestra(idx_grade, c['slug'], FINE_GIORNATA.strftime('%Y-%m-%d'))
        rows.append({'carta': cid, 'slug': c['slug'], 'nome': c['nome'], 'ruolo': ruolo,
                    'codice': cod, 'lega': lega_di.get(c['slug']) or 'senza_lega',
                    'squadra': res.get('squadra'), 'opp_slug': res.get('opp_slug'),
                    'l10': res.get('l10'), 'copie': 1,
                    'atteso_raw': res['atteso'], '_cal': cal, '_grade': gnum, 'reale': reale})
    gruppi = collections.defaultdict(list)
    for row in rows:
        gruppi[(row['lega'], row['codice'])].append(row)
    for _key, membri in gruppi.items():
        _z, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
        gp = [m['_grade'] for m in membri if m['_grade'] is not None]
        if len(gp) >= 2:
            zg, _, _ = S21.zscore_gruppo(gp)
            it = iter(zg)
            for m in membri:
                m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
        else:
            for m in membri:
                m['_zgrade'] = 0.0
        for m in membri:
            m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']
    return rows, scarti


def gioca(pool_rows, leghe, chiave_obiettivo, massimo=15):
    """Costruisce role_data/pools/card_pool freschi e lascia che
    genera_arene_efficienti (produzione) decida DA SOLA tipo e numero di
    arene, in base alla resa attesa su `chiave_obiettivo` (_cal o
    _combinato). Ritorna la lista di formazioni scelte con netto essenze
    calcolato sul REALIZZATO."""
    role_data, pools, card_pool, _leghe = S21.costruisci({'pool': pool_rows}, lambda c: c[chiave_obiettivo])
    orig = S21.bfg.LEAGUES
    S21.bfg.LEAGUES = tuple(leghe)
    try:
        scelte = S21.bfg.genera_arene_efficienti(TIPI_ARENA, massimo, role_data, pools, card_pool)
    finally:
        S21.bfg.LEAGUES = orig

    risultati = []
    for s in scelte:
        formazione = s['formazione']
        tipo = s['tipo']
        cap_row = S21.capitano_atteso(formazione)
        punti_reali = S21.realizzato(formazione, cap_row)
        soglia = S21.bfg.PAREGGIO_ARENA.get(tipo)
        guad = S21.bfg.GUADAGNO_PER_PUNTO.get(tipo, 7.9)
        netto = (punti_reali - soglia) * guad
        carte = [{'nome': r.get('slug'), 'ruolo': r['role_key'], 'reale': r['reale'],
                 'capitano': (cap_row is not None and r['slug'] == cap_row['slug'])}
                for _x, r, _t in formazione]
        risultati.append({'tipo': tipo, 'atteso_scelta': s.get('atteso') if 'atteso' in s else None,
                          'punti_reali': punti_reali, 'soglia': soglia, 'guad_punto': guad,
                          'netto_stimato': netto, 'carte': carte})
    return risultati


def main():
    righe = carica_formazioni()
    print('=' * 78)
    print(f'BINARIO 2 -- G vs A, pool libero -- {FINE_GIORNATA.date()} (GW2 pre-G)')
    print('=' * 78)
    print(f'formazioni arena totali in archivio: {len(righe)}')

    pool, escluse = costruisci_pool_carte(righe)
    print(f'carte escluse per 0/DNP: {len(escluse)}  ({", ".join(escluse)})')
    print(f'carte uniche nel pool (dedup per id-carta): {len(pool)}')

    primo_kickoff = trova_primo_kickoff(pool)
    if primo_kickoff is None:
        raise SystemExit('nessuna partita-target trovata: cache vuota?')
    print(f'primo kickoff GW2: {primo_kickoff.isoformat()}  (cutoff_giornata esplicito)')
    print()

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, idx_grade, lega_di)
    n_con_grade = sum(1 for r in pool_rows if r['_grade'] is not None)
    print(f'righe pool con atteso utilizzabile: {len(pool_rows)}/{len(pool)}  (scarti: {dict(scarti)})')
    print(f'carte con grade (PRIMA del completamento): {n_con_grade}/{len(pool_rows)}')

    mancanti = sorted({r['slug'] for r in pool_rows if r['_grade'] is None})
    if mancanti:
        if not CG.SORARE_COOKIE or not CG.SORARE_CSRF:
            print(f'{len(mancanti)} carte senza grade: credenziali assenti, salto il completamento.')
        else:
            print(f'completamento: interrogo Sorare per {len(mancanti)} slug mancanti...')
            nuove, falliti = CG.completa(mancanti)
            print(f'  {nuove} righe nuove aggiunte all\'indice condiviso')
            if falliti:
                print(f'  {len(falliti)} slug senza risultato: {falliti}')
            if nuove:
                idx_grade, _ = S21.carica_indice_grade()
                pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, idx_grade, lega_di)
                n_con_grade = sum(1 for r in pool_rows if r['_grade'] is not None)
                print(f'  carte con grade DOPO il completamento: {n_con_grade}/{len(pool_rows)}')
    print()

    leghe = sorted(set(r['lega'] for r in pool_rows) | {'senza_lega'})

    ris_A = gioca([dict(r) for r in pool_rows], leghe, '_cal')
    ris_G = gioca([dict(r) for r in pool_rows], leghe, '_combinato')

    for label, ris in (('A', ris_A), ('G', ris_G)):
        print(f'--- {label}: {len(ris)} arene scelte ---')
        for i, r in enumerate(ris, 1):
            print(f"  [{i}] {r['tipo']:22s} punti_reali={r['punti_reali']:7.2f}  "
                  f"soglia={r['soglia']:7.2f}  netto_stimato={r['netto_stimato']:+8.0f}")
        tot = sum(r['netto_stimato'] for r in ris)
        print(f'  TOTALE {label}: {tot:+.0f} essenze su {len(ris)} arene')
        print()

    tot_A = sum(r['netto_stimato'] for r in ris_A)
    tot_G = sum(r['netto_stimato'] for r in ris_G)
    print('=' * 78)
    print(f'NETTO ESSENZE STIMATO (realizzato, non atteso):')
    print(f'  A: {tot_A:+.0f}  ({len(ris_A)} arene)')
    print(f'  G: {tot_G:+.0f}  ({len(ris_G)} arene)')
    print()
    print(f'ATTENZIONE CAMPIONE: 1 sola GW, pool di {len(pool_rows)} carte.')
    print('Non decisivo da solo. Stabilisce il metodo per le prossime GW.')

    out = {'fixture': 'football-4-7-aug-2026', 'primo_kickoff': primo_kickoff.isoformat(),
          'pool_size': len(pool_rows), 'escluse_dnp': escluse,
          'ris_A': ris_A, 'ris_G': ris_G, 'tot_A': tot_A, 'tot_G': tot_G}
    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'p24_binario2_gw2_out.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
