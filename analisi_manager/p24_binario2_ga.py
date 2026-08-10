"""BINARIO 2 -- G vs A, pool libero (10/08/2026).

Gira su TUTTE le fixture pre-G in archivio_crowss/pre_2026-08-07/, una GW
alla volta (pool, gruppi z-score e scelta arene MAI mischiati fra GW
diverse -- ogni giornata e' una sua unita' indipendente, come in
produzione), poi somma il netto essenze su tutte.

Metodologia (uguale al singolo-GW test, solo iterata):
  - Si escludono le sole CARTE a 0/DNP dal pool (non l'intera formazione:
    qui l'unita' e' un pool di selezione, si salvano le altre 4 carte buone
    -- diverso apposta dal Binario 1).
  - G e A pescano e RICOMPONGONO liberamente dal pool: ognuno decide da solo
    quante arene giocare e di che tipo (riusa `genera_arene_efficienti`, LA
    funzione di produzione che decide mix e quantita' da sola in base alla
    resa attesa -- non reinventata qui).
  - Il confronto e' sul NETTO ESSENZE totale, non arena per arena. Niente
    scalini arbitrari: si riusano PAREGGIO_ARENA/GUADAGNO_PER_PUNTO gia'
    calibrati in produzione su 2.125 arene reali e 5.031 premi veri.
  - La DECISIONE di quante arene entrare la prende l'ATTESO (come in
    produzione). Il NETTO riportato e' calcolato sul REALIZZATO.
  - Walkforward pulito: cutoff_giornata esplicito = primo kickoff DI QUELLA
    GW (mai un altro), grade dall'indice condiviso gia' completato in
    sessione (96.3% sull'aggregato).
  - Punteggio REALE per carta: da `punteggio` dell'archivio (gia'
    verificato in estrazione), diviso 1.2 se capitano nella formazione
    originale -- non dalla cache game-log (rischio di finestra-data errata,
    verificato su GW2).

Uso: python analisi_manager/p24_binario2_ga.py
"""
import os
import sys
import io
import json
import glob
import datetime
import collections
import contextlib

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
ARCHIVIO_DIR = os.path.join(ROOT, 'archivio_crowss', 'pre_2026-08-07')
MESI = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
       'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def fine_giornata_da_slug(fx):
    toks = fx.split('-')[1:]
    year = int(toks[-1])
    toks = toks[:-1]
    midx = [i for i, t in enumerate(toks) if t in MESI]
    ei = midx[-1]
    d2, m2 = int(toks[ei - 1]), MESI[toks[ei]]
    return datetime.datetime(year, m2, d2, 23, 59)


def elenca_fixture():
    out = []
    for f in sorted(glob.glob(os.path.join(ARCHIVIO_DIR, '*_arene_limited.json'))):
        fx = os.path.basename(f).replace('_arene_limited.json', '')
        out.append((fx, f))
    return out


def carica_formazioni(path):
    d = json.load(open(path, encoding='utf-8'))
    return d['righe'] if isinstance(d, dict) else d


def costruisci_pool_carte(righe):
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
    p = c.get('punteggio')
    if p is None:
        return None
    return p / 1.2 if c.get('capitano') else p


def trova_primo_kickoff(pool, fine_giornata):
    date_target = []
    for c in pool.values():
        t = P.partita_target(cache, c['slug'], fine_giornata)
        if t is not None:
            dt = P._data(t)
            if dt is not None:
                date_target.append(dt)
    if not date_target:
        return None
    return min(date_target)


def prepara_pool_rows(pool, primo_kickoff, fine_giornata, idx_grade, lega_di):
    rows = []
    scarti = collections.Counter()
    for cid, c in pool.items():
        ruolo = c['ruolo']
        cod = ROLE_CODE.get(ruolo)
        if cod is None:
            scarti['ruolo_sconosciuto'] += 1
            continue
        res = P.score_atteso(cache, c['slug'], ruolo, fine_giornata, cutoff_giornata=primo_kickoff)
        if res is None or res.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        reale = grezzo_da_archivio(c)
        if reale is None:
            scarti['no_reale'] += 1
            continue
        cal = S21.bfg.calibra(res['atteso'], cod)
        gnum = S21.grade_in_finestra(idx_grade, c['slug'], fine_giornata.strftime('%Y-%m-%d'))
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
    role_data, pools, card_pool, _leghe = S21.costruisci({'pool': pool_rows}, lambda c: c[chiave_obiettivo])
    orig = S21.bfg.LEAGUES
    S21.bfg.LEAGUES = tuple(leghe)
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # bfg stampa per ogni tentativo, silenziato
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
        carte = [{'slug': r['slug'], 'ruolo': r['role_key'], 'reale': r['reale'],
                 'capitano': (cap_row is not None and r['slug'] == cap_row['slug'])}
                for _x, r, _t in formazione]
        risultati.append({'tipo': tipo, 'punti_reali': punti_reali, 'soglia': soglia,
                          'guad_punto': guad, 'netto_stimato': netto, 'carte': carte})
    return risultati


def processa_fixture(fx, path, lega_di, idx_grade):
    righe = carica_formazioni(path)
    pool, escluse = costruisci_pool_carte(righe)
    if not pool:
        return None
    fine_giornata = fine_giornata_da_slug(fx)
    primo_kickoff = trova_primo_kickoff(pool, fine_giornata)
    if primo_kickoff is None:
        return None
    pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, fine_giornata, idx_grade, lega_di)
    if not pool_rows:
        return None
    leghe = sorted(set(r['lega'] for r in pool_rows) | {'senza_lega'})

    ris_A = gioca([dict(r) for r in pool_rows], leghe, '_cal')
    ris_G = gioca([dict(r) for r in pool_rows], leghe, '_combinato')
    return {
        'fixture': fx, 'pool_size': len(pool), 'pool_con_atteso': len(pool_rows),
        'n_con_grade': sum(1 for r in pool_rows if r['_grade'] is not None),
        'escluse_dnp': escluse, 'primo_kickoff': primo_kickoff.isoformat(),
        'ris_A': ris_A, 'ris_G': ris_G,
    }


def main():
    fixtures = elenca_fixture()
    print('=' * 78)
    print(f'BINARIO 2 -- G vs A, pool libero -- AGGREGATO su {len(fixtures)} GW pre-G')
    print('=' * 78)

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    per_gw = []
    for fx, path in fixtures:
        esito = processa_fixture(fx, path, lega_di, idx_grade)
        if esito is None:
            print(f'{fx:32s}  SALTATA (pool vuoto o nessuna partita-target trovata)')
            continue
        per_gw.append(esito)
        tot_a = sum(r['netto_stimato'] for r in esito['ris_A'])
        tot_g = sum(r['netto_stimato'] for r in esito['ris_G'])
        print(f"{fx:32s}  pool={esito['pool_con_atteso']:3d}  grade={esito['n_con_grade']:3d}  "
              f"A={tot_a:+7.0f}({len(esito['ris_A'])})  G={tot_g:+7.0f}({len(esito['ris_G'])})")

    tot_A = sum(sum(r['netto_stimato'] for r in e['ris_A']) for e in per_gw)
    tot_G = sum(sum(r['netto_stimato'] for r in e['ris_G']) for e in per_gw)
    n_A = sum(len(e['ris_A']) for e in per_gw)
    n_G = sum(len(e['ris_G']) for e in per_gw)

    print()
    print('=' * 78)
    print(f'TOTALE AGGREGATO su {len(per_gw)} GW (netto essenze, realizzato non atteso):')
    print(f'  A: {tot_A:+.0f}  ({n_A} arene totali)')
    print(f'  G: {tot_G:+.0f}  ({n_G} arene totali)')

    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'p24_binario2_aggregato_out.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'per_gw': per_gw, 'tot_A': tot_A, 'tot_G': tot_G, 'n_A': n_A, 'n_G': n_G},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
