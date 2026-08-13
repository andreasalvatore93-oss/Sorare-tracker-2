"""BINARIO 2 -- G vs A, pool libero (10/08/2026).

Gira su TUTTE le fixture umane reali in archivio_ufficiale/ (per crowss
solo pre_2026-08-07/, per altri manager tutte le loro fixture), una GW
alla volta e SEMPRE dentro il pool di un solo manager (pool, gruppi
z-score e scelta arene MAI mischiati fra GW o fra manager diversi -- ogni
coppia manager/giornata e' una sua unita' indipendente, come in
produzione), poi somma il netto essenze su tutte. Multi-manager attivato
10/08/2026 (decisione utente): il confronto resta SEMPRE G vs A, mai
"battiamo il manager X" -- vedi archivio_ufficiale/README.md.

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

# Gruppo grade (11/08/2026, filone "gruppo esteso alla giornata" -- vedi
# docstring di S21.applica_gruppi_grade). Default 'lega_ruolo' = INVARIATO.
GRADE_GROUP_MODE = os.environ.get('GRADE_GROUP_MODE', 'lega_ruolo')
FATTORE_STORICO = float(os.environ.get('FATTORE_STORICO', '1.0'))
GRADE_SCALE_PATH = os.path.join('generatore_formazioni', 'dati', 'grade_scala_storica.json')

# Aggiustamenti avversario di produzione (opponent_lambda_mult, Stadio D).
# Default '0' = comportamento INVARIATO, cioe' come sono state fatte tutte le
# misure precedenti su questo banco (compresa quella che ha promosso
# GK_ATT_AVV). Si accende per misurare correzioni che riguardano l'avversario:
# senza, si misurerebbe il pezzo nuovo fuori dalla formula in cui vive.
USA_AVVERSARIO = os.environ.get('USA_AVVERSARIO', '0') == '1'
# Correzione pre-registrata sul difensore (test_def.GOL_FATTI_AVV_K = -4.0).
# Vuoto = spenta, comportamento invariato.
GOL_FATTI_AVV_K = float(os.environ['GOL_FATTI_AVV_K']) \
    if os.environ.get('GOL_FATTI_AVV_K') else None

ROLE_CODE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}
TIPI_ARENA = ['ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED',
             'ARENA_ALLSTARS_BEGINNER']
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

    crowss: solo pre_2026-08-07/. Altri manager: tutte le loro fixture."""
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


def prepara_pool_rows_grezze(pool, primo_kickoff, fine_giornata, idx_grade, lega_di):
    """Righe del pool SENZA applicare il gruppo grade (quello arriva dopo,
    in main(): la modalita' 'pool_largo' ha bisogno di vedere le righe di
    TUTTI i manager della stessa fixture prima di poter raggruppare, cosa
    impossibile dentro questa funzione che vede un solo manager alla
    volta)."""
    rows = []
    scarti = collections.Counter()
    for cid, c in pool.items():
        ruolo = c['ruolo']
        cod = ROLE_CODE.get(ruolo)
        if cod is None:
            scarti['ruolo_sconosciuto'] += 1
            continue
        res = P.score_atteso(cache, c['slug'], ruolo, fine_giornata,
                             cutoff_giornata=primo_kickoff,
                             usa_avversario=USA_AVVERSARIO,
                             gol_fatti_avv_k=GOL_FATTI_AVV_K)
        if res is None or res.get('atteso') is None:
            scarti['no_atteso'] += 1
            continue
        reale = grezzo_da_archivio(c)
        if reale is None:
            scarti['no_reale'] += 1
            continue
        cal = S21.bfg.calibra(res['atteso'], cod)
        if cod == 'GK':
            # Correttivo GK_ATT_AVV (11/08/2026): a GK_ATT_AVV_ENABLED spento
            # (default) l'aggiustamento e' sempre 0.0 -- vedi
            # generatore_formazioni/build_formazione_globale.py,
            # gk_att_avv_aggiustamento(). Serve a testare G col correttivo
            # acceso/spento nel Binario 2 senza duplicare la formula.
            cal = round(cal + S21.bfg.gk_att_avv_aggiustamento(res.get('opp_slug')), 1)
        gnum = S21.grade_in_finestra(idx_grade, c['slug'], fine_giornata.strftime('%Y-%m-%d'))
        rows.append({'carta': cid, 'slug': c['slug'], 'nome': c['nome'], 'ruolo': ruolo,
                    'codice': cod, 'lega': lega_di.get(c['slug']) or 'senza_lega',
                    'squadra': res.get('squadra'), 'opp_slug': res.get('opp_slug'),
                    'l10': res.get('l10'), 'copie': 1,
                    'atteso_raw': res['atteso'], '_cal': cal, '_grade': gnum, 'reale': reale})
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


def processa_fixture_pass1(manager, fx, path, lega_di, idx_grade):
    """Prima passata: pool + righe grezze, SENZA gruppo grade."""
    righe = carica_formazioni(path)
    pool, escluse = costruisci_pool_carte(righe)
    if not pool:
        return None
    fine_giornata = fine_giornata_da_slug(fx)
    primo_kickoff = trova_primo_kickoff(pool, fine_giornata)
    if primo_kickoff is None:
        return None
    pool_rows, _scarti = prepara_pool_rows_grezze(pool, primo_kickoff, fine_giornata, idx_grade, lega_di)
    if not pool_rows:
        return None
    return {'manager': manager, 'fixture': fx, 'pool_size': len(pool),
            'escluse_dnp': escluse, 'primo_kickoff': primo_kickoff, 'pool_rows': pool_rows}


def processa_fixture_pass2(pre):
    """Seconda passata: il gruppo grade e' gia' stato applicato a
    pre['pool_rows'] da main() (dipende dalla modalita', vedi li'). Qui solo
    A/G e assemblaggio esito."""
    manager, fx, pool_rows = pre['manager'], pre['fixture'], pre['pool_rows']
    leghe = sorted(set(r['lega'] for r in pool_rows) | {'senza_lega'})

    ris_A = gioca([dict(r) for r in pool_rows], leghe, '_cal')
    ris_G = gioca([dict(r) for r in pool_rows], leghe, '_combinato')
    carta_rows = [
        {'manager': manager, 'fixture': fx, 'slug': r['slug'], 'codice': r['codice'],
         'lega': r['lega'], '_cal': r['_cal'], '_combinato': r['_combinato'],
         '_grade': r['_grade'], '_zgrade': r['_zgrade'], 'reale': r['reale']}
        for r in pool_rows]
    return {
        'manager': manager, 'fixture': fx, 'pool_size': pre['pool_size'],
        'pool_con_atteso': len(pool_rows),
        'n_con_grade': sum(1 for r in pool_rows if r['_grade'] is not None),
        'escluse_dnp': pre['escluse_dnp'], 'primo_kickoff': pre['primo_kickoff'].isoformat(),
        'ris_A': ris_A, 'ris_G': ris_G, 'carta_rows': carta_rows,
    }


def main():
    fixtures = elenca_fixture()
    n_manager = len(set(m for m, _fx, _p in fixtures))
    print('=' * 78)
    print(f'BINARIO 2 -- G vs A, pool libero -- AGGREGATO su {len(fixtures)} GW, {n_manager} manager')
    print('=' * 78)

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    # Passata 1: pool grezzo per OGNI manager/fixture (nessun gruppo grade
    # ancora). Serve sempre come base; per 'pool_largo' serve anche per
    # costruire il riferimento incrociato fra manager PRIMA di raggruppare.
    pre_ok, pre_skip = [], []
    for manager, fx, path in fixtures:
        pre = processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            pre_skip.append((manager, fx))
        else:
            pre_ok.append(pre)

    # Passata 2: applica il gruppo grade secondo GRADE_GROUP_MODE.
    if GRADE_GROUP_MODE == 'pool_largo':
        # Riferimento incrociato: per ogni fixture, le righe di TUTTI i
        # manager che l'hanno giocata, raggruppate per (lega,ruolo) --
        # approssima il pool di discovery della produzione (11/08/2026
        # sera, "proviamo con pool largo del generatore").
        esterno_per_fixture = collections.defaultdict(lambda: collections.defaultdict(list))
        for pre in pre_ok:
            for r in pre['pool_rows']:
                esterno_per_fixture[pre['fixture']][(r['lega'], r['codice'])].append(r)
        for pre in pre_ok:
            S21.applica_gruppi_grade(pre['pool_rows'], modo='pool_largo',
                                     riferimento_esterno=esterno_per_fixture[pre['fixture']])
    elif GRADE_GROUP_MODE == 'storica_completa':
        # Round 2 del filone (RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt
        # §16-17): gm/gsd del grade dalla tabella storica di produzione,
        # sd_atteso da una tabella storica gemella costruita qui (stessa
        # gerarchia lega_ruolo->ruolo->globale, stessa materia prima).
        # Nessuna dipendenza dal gruppetto nativo: funziona anche per i
        # gruppi di 1 carta (51% dei casi in produzione).
        with open(GRADE_SCALE_PATH, encoding='utf-8') as f:
            S21.bfg._GRADE_SCALE_TABLE = json.load(f)
        tutte_le_righe = [r for pre in pre_ok for r in pre['pool_rows']]
        tab_sd = S21.costruisci_tabella_sd_atteso(tutte_le_righe)
        for pre in pre_ok:
            S21.applica_gruppi_grade(pre['pool_rows'], modo='storica_completa',
                                     tabella_sd_storica=tab_sd, fattore_storico=FATTORE_STORICO)
    else:
        for pre in pre_ok:
            S21.applica_gruppi_grade(pre['pool_rows'], modo=GRADE_GROUP_MODE)

    per_gw = []
    for manager, fx in pre_skip:
        print(f'{manager:12s} {fx:32s}  SALTATA (pool vuoto o nessuna partita-target trovata)')
    for pre in pre_ok:
        esito = processa_fixture_pass2(pre)
        manager, fx = esito['manager'], esito['fixture']
        per_gw.append(esito)
        tot_a = sum(r['netto_stimato'] for r in esito['ris_A'])
        tot_g = sum(r['netto_stimato'] for r in esito['ris_G'])
        print(f"{manager:12s} {fx:32s}  pool={esito['pool_con_atteso']:3d}  grade={esito['n_con_grade']:3d}  "
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

    # n vera + trim SIMMETRICO (non piu' asimmetrico, vedi RISPOSTA_OPUS_STATO_GVSA_ROUND4:
    # togliere solo i pro-G e' viziato in una struttura a premi-lotteria, va tolto 3+3).
    pair_deltas = [sum(r['netto_stimato'] for r in e['ris_G'])
                   - sum(r['netto_stimato'] for r in e['ris_A']) for e in per_gw]
    delta_totale = sum(pair_deltas)
    n_discordanti = sum(1 for d in pair_deltas if d != 0)
    ordinati = sorted(pair_deltas)
    top3_pro_g = ordinati[-3:] if len(ordinati) >= 3 else ordinati
    top3_pro_a = ordinati[:3] if len(ordinati) >= 3 else ordinati
    trim_simmetrico = delta_totale - sum(top3_pro_g) - sum(top3_pro_a)

    print(f'\n  *** la n vera del confronto G-vs-A e\' {n_discordanti} coppie manager-GW '
          f'(su {len(per_gw)}), non {len(per_gw)} ***')
    print(f'  delta G-A totale: {delta_totale:+.0f}  |  trim simmetrico (tolte le 3 coppie '
          f'piu\' pro-G e le 3 piu\' pro-A): {trim_simmetrico:+.0f}')

    out_path = os.path.join(ARCHIVIO_ROOT, 'aggregato', 'binario2_out.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump({'per_gw': [{k: v for k, v in e.items() if k != 'carta_rows'} for e in per_gw],
                   'tot_A': tot_A, 'tot_G': tot_G, 'n_A': n_A, 'n_G': n_G,
                   'n_discordanti': n_discordanti, 'delta_G_A_totale': delta_totale,
                   'delta_G_A_trim_simmetrico': trim_simmetrico},
                  fh, ensure_ascii=False, indent=1)
    print(f'\ndettaglio scritto in {out_path}')

    pool_rows_path = os.path.join(ARCHIVIO_ROOT, 'aggregato', 'binario2_pool_rows.json')
    tutti_carta_rows = [r for e in per_gw for r in e['carta_rows']]
    with open(pool_rows_path, 'w', encoding='utf-8') as fh:
        json.dump(tutti_carta_rows, fh, ensure_ascii=False, indent=1)
    print(f'{len(tutti_carta_rows)} righe carta scritte in {pool_rows_path}')


if __name__ == '__main__':
    main()
