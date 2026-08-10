"""BINARIO 1 -- M vs G vs A, formazione FISSA, walkforward pulito (10/08/2026).

Gira su TUTTE le fixture UMANE REALI in archivio_ufficiale/: per crowss
solo pre_2026-08-07/ (mai dal_2026-08-07/: li' "M" e' gia' il modello G,
il confronto non avrebbe senso), per qualunque altro manager tutte le sue
fixture (le sue formazioni sono SEMPRE umane reali, non esiste "dopo G"
per nessun altro manager). Multi-manager attivato 10/08/2026 (decisione
esplicita utente, vedi archivio_ufficiale/README.md): il confronto resta
SEMPRE G vs A, il manager fornisce solo la formazione reale e l'esito
reale -- mai "battiamo il manager X".

Metodologia decisa in sessione con l'utente:
  - Fonte: SOLO archivio_ufficiale (mai dati_globali/manager_*.json).
  - Si escludono le FORMAZIONI INTERE con una carta a 0/DNP (non solo la
    carta: qui l'unita' e' la formazione fissa, non un pool).
  - M, G e A giocano la IDENTICA formazione reale (stesse 5 carte, stesso
    capitano). L'unica differenza fra i tre e' la decisione ENTRA/SALTA
    quell'arena, secondo l'atteso di ciascuno confrontato con
    PAREGGIO_ARENA (soglia_decisione = pareggio + margine QUOTA_MINIMA,
    la vera regola di produzione, non la soglia nuda).
  - M "entra" sempre (e' cio' che e' successo davvero): il suo netto e'
    sempre premio_netto reale.
  - Walkforward stretto: atteso calcolato con backtest_arene_previsioni
    (la formula di PRODUZIONE rigiocata all'indietro), passando
    ESPLICITAMENTE cutoff_giornata = primo calcio d'inizio della SINGOLA
    giornata in esame (fix leak infra-giornata del 03/08).
  - Grade: dall'indice storico condiviso, completato per le carte mancanti
    con completa_grade_mancante.py PRIMA di lanciare questo script (fatto
    in sessione: 96.3% di copertura sull'aggregato).
  - Gruppo z-score grade: (lega, ruolo) SEMPRE dentro la singola GW, mai
    mischiato fra giornate diverse (stesso principio di produzione, §P22
    del riassunto unificato).

Uso: python analisi_manager/p23_binario1_mga.py
"""
import os
import sys
import io
import json
import glob
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
TIPO_TO_BFG = {
    'cap260': 'ARENA_ALLSTARS_260', 'cap220': 'ARENA_ALLSTARS_220',
    'uncapped': 'ARENA_ALLSTARS_UNCAPPED', 'beginner': 'ARENA_ALLSTARS_BEGINNER',
}
ARCHIVIO_ROOT = os.path.join(ROOT, 'archivio_ufficiale')
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
    """(manager, fixture, path) per OGNI fixture umana reale disponibile.

    crowss: solo pre_2026-08-07/ (dal_2026-08-07/ e' gia' il modello G,
    escluso apposta). Altri manager: tutte le loro fixture, sono sempre
    schieramenti umani (non esiste "dopo G" per nessun altro manager)."""
    out = []
    for cartella in sorted(glob.glob(os.path.join(ARCHIVIO_ROOT, 'manager_*'))):
        manager = os.path.basename(cartella).replace('manager_', '')
        if manager == 'crowss':
            sorgente = os.path.join(cartella, 'pre_2026-08-07', '*_arene_limited.json')
        else:
            sorgente = os.path.join(cartella, '*_arene_limited.json')
        for f in sorted(glob.glob(sorgente)):
            fx = os.path.basename(f).replace('_arene_limited.json', '')
            out.append((manager, fx, f))
    return out


def carica_formazioni(path):
    d = json.load(open(path, encoding='utf-8'))
    return d['righe'] if isinstance(d, dict) else d


def escludi_dnp(righe):
    pulite, escluse = [], []
    for r in righe:
        dnp = [c['nome'] for c in r['carte'] if (c.get('punteggio') or 0.0) == 0.0]
        if dnp:
            escluse.append((r, dnp))
        else:
            pulite.append(r)
    return pulite, escluse


def trova_primo_kickoff(pulite, fine_giornata):
    date_target = []
    for r in pulite:
        for c in r['carte']:
            t = P.partita_target(cache, c['slug'], fine_giornata)
            if t is not None:
                dt = P._data(t)
                if dt is not None:
                    date_target.append(dt)
    if not date_target:
        return None
    return min(date_target)


def costruisci_pool(pulite):
    pool = {}
    for r in pulite:
        for c in r['carte']:
            cid = c.get('carta')
            if cid and cid not in pool:
                pool[cid] = c
    return pool


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
        cal = S21.bfg.calibra(res['atteso'], cod)
        gnum = S21.grade_in_finestra(idx_grade, c['slug'], fine_giornata.strftime('%Y-%m-%d'))
        rows.append({'carta': cid, 'slug': c['slug'], 'nome': c['nome'], 'ruolo': ruolo,
                    'codice': cod, 'lega': lega_di.get(c['slug']) or 'senza_lega',
                    'atteso_raw': res['atteso'], '_cal': cal, '_grade': gnum})
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


def decidi_entra(riga_per_carta, formazione, chiave):
    carte = formazione['carte']
    rows = [riga_per_carta.get(c.get('carta')) for c in carte]
    if any(r is None for r in rows):
        return None, None, None
    cap_idx = next((i for i, c in enumerate(carte) if c.get('capitano')), None)
    atteso = sum(r[chiave] for r in rows) + (0.2 * rows[cap_idx][chiave] if cap_idx is not None else 0.0)
    tipo_bfg = TIPO_TO_BFG[formazione['tipo']]
    soglia = S21.bfg.PAREGGIO_ARENA.get(tipo_bfg)
    costo = S21.bfg.COSTO_INGRESSO.get(tipo_bfg, 300)
    guad_punto = S21.bfg.GUADAGNO_PER_PUNTO.get(tipo_bfg, 7.9)
    soglia_decisione = soglia + costo * S21.bfg.QUOTA_MINIMA / guad_punto
    return atteso, soglia_decisione, (atteso >= soglia_decisione)


def processa_fixture(manager, fx, path, lega_di, idx_grade):
    righe = carica_formazioni(path)
    pulite, escluse = escludi_dnp(righe)
    if not pulite:
        return None
    fine_giornata = fine_giornata_da_slug(fx)
    primo_kickoff = trova_primo_kickoff(pulite, fine_giornata)
    if primo_kickoff is None:
        return None
    pool = costruisci_pool(pulite)
    pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, fine_giornata, idx_grade, lega_di)
    riga_per_carta = {r['carta']: r for r in pool_rows}

    risultati = []
    for r in pulite:
        atteso_A, soglia_dec, entra_A = decidi_entra(riga_per_carta, r, '_cal')
        atteso_G, _sd2, entra_G = decidi_entra(riga_per_carta, r, '_combinato')
        if entra_A is None:
            continue
        risultati.append({
            'manager': manager, 'fixture': fx, 'tipo': r['tipo'],
            'punteggio_totale': r['punteggio_totale'],
            'premio_netto': r['premio_netto'],
            'atteso_A': atteso_A, 'entra_A': entra_A,
            'atteso_G': atteso_G, 'entra_G': entra_G,
            'soglia_decisione': soglia_dec, 'capitano': r['capitano']['slug'],
        })
    return {
        'manager': manager, 'fixture': fx, 'formazioni_totali': len(righe),
        'escluse_dnp': len(escluse), 'primo_kickoff': primo_kickoff.isoformat(),
        'n_pool': len(pool), 'n_pool_con_atteso': len(pool_rows),
        'n_con_grade': sum(1 for r in pool_rows if r['_grade'] is not None),
        'scarti': dict(scarti), 'risultati': risultati,
    }


def main():
    fixtures = elenca_fixture()
    n_manager = len(set(m for m, _fx, _p in fixtures))
    print('=' * 78)
    print(f'BINARIO 1 -- M vs G vs A, formazione fissa -- AGGREGATO su {len(fixtures)} GW, '
          f'{n_manager} manager')
    print('=' * 78)

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    tutti_risultati = []
    per_gw = []
    for manager, fx, path in fixtures:
        esito = processa_fixture(manager, fx, path, lega_di, idx_grade)
        if esito is None:
            print(f'{manager:12s} {fx:32s}  SALTATA (nessuna formazione pulita o nessuna partita-target trovata)')
            continue
        per_gw.append(esito)
        tutti_risultati.extend(esito['risultati'])
        n = len(esito['risultati'])
        tot_m = sum(r['premio_netto'] for r in esito['risultati'])
        tot_a = sum(r['premio_netto'] if r['entra_A'] else 0 for r in esito['risultati'])
        tot_g = sum(r['premio_netto'] if r['entra_G'] else 0 for r in esito['risultati'])
        print(f"{manager:12s} {fx:32s}  n={n:3d}  grade={esito['n_con_grade']:3d}/{esito['n_pool_con_atteso']:3d}  "
              f"M={tot_m:+6.0f}  A={tot_a:+6.0f}  G={tot_g:+6.0f}")

    tot_M = sum(r['premio_netto'] for r in tutti_risultati)
    tot_A = sum(r['premio_netto'] if r['entra_A'] else 0 for r in tutti_risultati)
    tot_G = sum(r['premio_netto'] if r['entra_G'] else 0 for r in tutti_risultati)
    n_A = sum(1 for r in tutti_risultati if r['entra_A'])
    n_G = sum(1 for r in tutti_risultati if r['entra_G'])
    n_tot = len(tutti_risultati)

    print()
    print('=' * 78)
    print(f'TOTALE AGGREGATO su {n_tot} formazioni pulite (identiche per M/G/A), {len(per_gw)} GW:')
    print(f'  M (reale, sempre dentro): {tot_M:+.0f}')
    print(f'  A (entra {n_A}/{n_tot}):        {tot_A:+.0f}')
    print(f'  G (entra {n_G}/{n_tot}):        {tot_G:+.0f}')

    n_diverse = sum(1 for r in tutti_risultati if r['entra_A'] != r['entra_G'])
    print(f'\n  decisioni A/G diverse: {n_diverse}/{n_tot}')

    out_path = os.path.join(ARCHIVIO_ROOT, 'aggregato', 'binario1_out.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'per_gw': per_gw, 'tot_M': tot_M, 'tot_A': tot_A, 'tot_G': tot_G,
                   'n_entra_A': n_A, 'n_entra_G': n_G, 'n_totale': n_tot}, fh,
                  ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
