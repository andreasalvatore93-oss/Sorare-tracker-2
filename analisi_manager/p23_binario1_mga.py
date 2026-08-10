"""BINARIO 1 -- M vs G vs A, formazione FISSA, walkforward pulito (10/08/2026).

Metodologia decisa in sessione con l'utente:
  - Fonte: SOLO archivio_crowss (mai dati_globali/manager_*.json, che per le
    GW pre-G non esiste comunque -- vedi nota sotto).
  - Si escludono le FORMAZIONI INTERE con una carta a 0/DNP (non solo la
    carta: qui l'unita' e' la formazione fissa, non un pool -- l'utente ha
    chiarito che uno "0 tondo" nei dati recenti e' lo stesso evento del
    vecchio "DNP" testuale, trattarli identici).
  - M, G e A giocano la IDENTICA formazione reale (stesse 5 carte, stesso
    capitano). Nessuna selezione, nessun riordino: l'unica differenza fra i
    tre e' la decisione ENTRA/SALTA quell'arena, secondo l'atteso di ciascuno
    confrontato con PAREGGIO_ARENA (soglia_decisione = pareggio + margine
    QUOTA_MINIMA, la vera regola di produzione, non la soglia nuda).
  - M "entra" sempre (e' cio' che e' successo davvero): il suo netto e'
    sempre premio_netto reale.
  - Walkforward stretto: atteso calcolato con backtest_arene_previsioni
    (la formula di PRODUZIONE rigiocata all'indietro, non una riscritta),
    passando ESPLICITAMENTE cutoff_giornata = primo calcio d'inizio della
    giornata (fix del leak infra-giornata trovato il 03/08: senza, un
    giocatore con piu' partite nella finestra vedrebbe nella sua storia
    risultati della giornata stessa).
  - Grade: dall'indice storico condiviso (S21.carica_indice_grade(), include
    i file raccolti apposta sul mazzo crowss). E' grade FINALE, non catturato
    al lock -- per le carte superstiti (non a 0, cioe' hanno davvero
    giocato) il rischio residuo e' basso ma non nullo (verificato altrove:
    per starter-odds >=0.80 il grade non si muove dal lock al finale, 18/18
    casi). Rischio noto, accettato esplicitamente dall'utente.
  - Gruppo z-score grade: (lega, ruolo) fra le carte delle formazioni ARENA
    pulite di QUESTA giornata (non l'intero pool multi-competizione: scope
    "solo arene" deciso dall'utente). Stesso principio di produzione
    (§P22 riassunto unificato: gruppo sempre dentro la singola unita'
    manager/gw), qui l'unita' e' "arene pulite della GW".

NOTA fonte dati: dati_globali/manager_crowss.json NON contiene la fixture
football-4-7-aug-2026 (verificato: 'football-4-7-aug-2026' assente dalle
'giornate' disponibili) -- e' per questo che p13_backtest_gw_crowss.py non
puo' essere riusato as-is su questa GW. L'unica fonte per questa fixture e'
archivio_crowss/pre_2026-08-07/, che pero' ha solo le arene limited (13
formazioni) + Da7 (8, non usate qui, scope solo arene).

Uso: python analisi_manager/p23_binario1_mga.py
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
TIPO_TO_BFG = {
    'cap260': 'ARENA_ALLSTARS_260', 'cap220': 'ARENA_ALLSTARS_220',
    'uncapped': 'ARENA_ALLSTARS_UNCAPPED', 'beginner': 'ARENA_ALLSTARS_BEGINNER',
}

ARCHIVIO = os.path.join(ROOT, 'archivio_crowss', 'pre_2026-08-07',
                        'football-4-7-aug-2026_arene_limited.json')
FINE_GIORNATA = datetime.datetime(2026, 8, 7, 23, 59)


def carica_formazioni():
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    return d['righe']


def escludi_dnp(righe):
    pulite, escluse = [], []
    for r in righe:
        dnp = [c['nome'] for c in r['carte'] if (c.get('punteggio') or 0.0) == 0.0]
        if dnp:
            escluse.append((r, dnp))
        else:
            pulite.append(r)
    return pulite, escluse


def trova_primo_kickoff(pulite):
    date_target = []
    for r in pulite:
        for c in r['carte']:
            t = P.partita_target(cache, c['slug'], FINE_GIORNATA)
            if t is not None:
                dt = P._data(t)
                if dt is not None:
                    date_target.append((dt, c['slug'], c['nome']))
    if not date_target:
        return None, []
    date_target.sort()
    return date_target[0][0], date_target


def costruisci_pool(pulite):
    """Una voce per carta (id 'carta'), dedup come p13.costruisci_pool."""
    pool = {}
    for r in pulite:
        for c in r['carte']:
            cid = c.get('carta')
            if cid and cid not in pool:
                pool[cid] = c
    return pool


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
        cal = S21.bfg.calibra(res['atteso'], cod)
        gnum = S21.grade_in_finestra(idx_grade, c['slug'], FINE_GIORNATA.strftime('%Y-%m-%d'))
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


def main():
    righe = carica_formazioni()
    print('=' * 78)
    print(f'BINARIO 1 -- M vs G vs A, formazione fissa -- {FINE_GIORNATA.date()} (GW2 pre-G)')
    print('=' * 78)
    print(f'formazioni arena totali in archivio: {len(righe)}')

    pulite, escluse = escludi_dnp(righe)
    print(f'escluse per 0/DNP (formazione intera): {len(escluse)}')
    for r, dnp in escluse:
        print(f"  ESCLUSA {r['tipo']:9s} tot_ufficiale={r['punteggio_totale']:7.2f}  DNP: {', '.join(dnp)}")
    print(f'formazioni PULITE (base del test): {len(pulite)}')
    print()

    primo_kickoff, date_target = trova_primo_kickoff(pulite)
    if primo_kickoff is None:
        raise SystemExit('nessuna partita-target trovata nella cache per le carte pulite: cache vuota?')
    print(f'primo kickoff GW2 (fra le formazioni pulite): {primo_kickoff.isoformat()}')
    print(f'(usato come cutoff_giornata esplicito per TUTTE le carte, fix leak 03/08)')
    print()

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    pool = costruisci_pool(pulite)
    print(f'carte uniche nel pool (pulite, dedup per id-carta): {len(pool)}')
    pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, idx_grade, lega_di)
    n_con_grade = sum(1 for r in pool_rows if r['_grade'] is not None)
    print(f'carte con grade trovato in finestra (PRIMA del completamento): '
          f'{n_con_grade}/{len(pool_rows)}')

    # COMPLETAMENTO STANDARD (10/08/2026): per le carte senza grade, prova
    # a recuperarlo mirato da Sorare invece di accettare il buco. Scrive in
    # un file persistente e condiviso (vedi completa_grade_mancante.py):
    # ogni run futuro (di QUALUNQUE script che usa carica_indice_grade)
    # beneficia delle carte gia' recuperate qui, la copertura cresce GW dopo GW.
    mancanti = sorted({r['slug'] for r in pool_rows if r['_grade'] is None})
    if mancanti:
        if not CG.SORARE_COOKIE or not CG.SORARE_CSRF:
            print(f'\n{len(mancanti)} carte senza grade: SORARE_COOKIE/SORARE_CSRF non in env,'
                  ' salto il completamento (resta il buco).')
        else:
            print(f'\ncompletamento: interrogo Sorare per {len(mancanti)} slug mancanti...')
            nuove, falliti = CG.completa(mancanti)
            print(f'  {nuove} righe nuove aggiunte all\'indice condiviso')
            if falliti:
                print(f'  {len(falliti)} slug senza risultato: {falliti}')
            if nuove:
                idx_grade, _ = S21.carica_indice_grade()
                pool_rows, scarti = prepara_pool_rows(pool, primo_kickoff, idx_grade, lega_di)
                n_con_grade = sum(1 for r in pool_rows if r['_grade'] is not None)
                print(f'  carte con grade DOPO il completamento: {n_con_grade}/{len(pool_rows)}')
    print(f'\nrighe pool con atteso utilizzabile: {len(pool_rows)}/{len(pool)}  (scarti: {dict(scarti)})')
    print()

    riga_per_carta = {r['carta']: r for r in pool_rows}

    risultati = []
    for r in pulite:
        atteso_A, soglia_dec, entra_A = decidi_entra(riga_per_carta, r, '_cal')
        atteso_G, _soglia_dec2, entra_G = decidi_entra(riga_per_carta, r, '_combinato')
        if entra_A is None:
            print(f"SALTATA dal test (atteso mancante per una carta): {r['tipo']} tot={r['punteggio_totale']}")
            continue
        risultati.append({
            'tipo': r['tipo'], 'punteggio_totale': r['punteggio_totale'],
            'premio_netto': r['premio_netto'], 'costo_ingresso': r['costo_ingresso'],
            'atteso_A': atteso_A, 'entra_A': entra_A,
            'atteso_G': atteso_G, 'entra_G': entra_G,
            'soglia_decisione': soglia_dec,
            'capitano': r['capitano']['slug'],
        })

    print('PER SINGOLA ARENA (formazione fissa, M=reale sempre dentro):')
    print(f"{'tipo':10s} {'M_netto':>9s} {'soglia_dec':>11s} {'atteso_A':>9s} {'dec_A':>6s} "
          f"{'atteso_G':>9s} {'dec_G':>6s}")
    for r in risultati:
        print(f"{r['tipo']:10s} {r['premio_netto']:9.0f} {r['soglia_decisione']:11.2f} "
              f"{r['atteso_A']:9.2f} {'ENTRA' if r['entra_A'] else 'SALTA':>6s} "
              f"{r['atteso_G']:9.2f} {'ENTRA' if r['entra_G'] else 'SALTA':>6s}")

    tot_M = sum(r['premio_netto'] for r in risultati)
    tot_A = sum(r['premio_netto'] if r['entra_A'] else 0 for r in risultati)
    tot_G = sum(r['premio_netto'] if r['entra_G'] else 0 for r in risultati)
    n_A = sum(1 for r in risultati if r['entra_A'])
    n_G = sum(1 for r in risultati if r['entra_G'])

    print()
    print('=' * 78)
    print(f'NETTO ESSENZE su {len(risultati)} formazioni pulite (identiche per M/G/A):')
    print(f'  M (reale, sempre dentro): {tot_M:+.0f}')
    print(f'  A (entra {n_A}/{len(risultati)}):        {tot_A:+.0f}')
    print(f'  G (entra {n_G}/{len(risultati)}):        {tot_G:+.0f}')
    print()
    print(f'ATTENZIONE CAMPIONE: n={len(risultati)} formazioni. Troppo piccolo per decidere')
    print('qualunque cosa da solo (regola CLAUDE.md: le giornate crescono una alla')
    print('volta). Questo run stabilisce il METODO, riproducibile su ogni GW futura.')

    out = {
        'fixture': 'football-4-7-aug-2026', 'primo_kickoff': primo_kickoff.isoformat(),
        'formazioni_totali': len(righe), 'escluse_dnp': len(escluse),
        'risultati': risultati, 'tot_M': tot_M, 'tot_A': tot_A, 'tot_G': tot_G,
        'n_entra_A': n_A, 'n_entra_G': n_G,
    }
    out_path = os.path.join(ROOT, 'analisi_manager', 'dati', 'p23_binario1_gw2_out.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')


if __name__ == '__main__':
    main()
