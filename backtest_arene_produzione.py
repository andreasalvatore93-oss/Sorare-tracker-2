"""backtest_arene_produzione — il vero generatore (build_formazione_globale.py)
contro l'utente, su una giornata gia' giocata.

Prima versione (03/08 sera) chiamava build_one_lineup grezzo, una sola lega,
priorita' inventata da me. SBAGLIATA (l'utente l'ha bocciata a ragione): il
generatore vero fa tre cose che quella versione saltava:
  1. CALIBRAZIONE per ruolo (calibra_riga): l'atteso grezzo del modello va
     convertito nella scala del punteggio REALE (retta diversa per GK/DEF/
     MID/FWD) prima di costruire qualunque formazione -- altrimenti il
     confronto fra ruoli (1 GK + 4 movimento) e' sbilanciato.
  2. STRUTTURA MULTI-LEGA: role_data e' {lega: {ruolo: [righe]}}, con un
     pool DEDICATO per le arene per-lega (Korea, Belgio, Olanda, Turchia...)
     e un pool 'mixed' (tutte le leghe insieme) per le All Stars/cap 260-
     220-uncapped.
  3. genera_arene_efficienti: il tipo e il NUMERO di arene li sceglie il bot
     da solo, massimizzando le essenze attese (PAREGGIO_ARENA/
     GUADAGNO_PER_PUNTO), non un ordine fisso deciso da me.

Questa versione chiama DIRETTAMENTE le funzioni di
generatore_formazioni/build_formazione_globale.py (bfg): stesso codice che
gira in produzione, nessuna reimplementazione.

Confini del test (dati disponibili, non scelte arbitrarie):
  * Si valuta SOLO sui tipi di arena per cui quel giorno esiste almeno uno
    slot REALE in arene_storico.json (terzo/premio veri) -- di un'arena mai
    entrata dall'utente non conosciamo la soglia, non e' verificabile.
  * L'identita' di ogni slot (arena per-lega dedicata vs All Stars mista)
    si legge dal campo 'slug' dello slot (es. 'seasonal-korea-...' =
    KLEAGUE_ARENA, 'seasonal-all_star-...cap_220' = ARENA_ALLSTARS_220),
    NON dal campo 'tipo' che e' solo il livello di cap (vedi
    _FAMIGLIA_SLUG_A_LEGA). Famiglie senza pool dedicato in produzione
    (es. 'under_twenty_one', una vera arena Sorare per Under 21 mai
    codificata nel generatore) finiscono nel pool misto All Stars, stessa
    scelta gia' confermata dall'utente per le leghe senza arena dedicata.
  * genera_arene_efficienti puo' scegliere PIU' formazioni di un tipo di
    quante ne esistano slot reali quel giorno (le arene Sorare non sono a
    capienza fissa: si puo' entrare in piu' lobby dello stesso tipo). Le
    formazioni oltre il numero di slot reali disponibili sono confrontate
    SOLO con la soglia di pareggio stimata (PAREGGIO_ARENA), mai con un
    terzo vero che non esiste nei dati -- segnalate a parte nel report.

Uso:
    python backtest_arene_produzione.py --fixture football-1-5-may-2026
"""
import os
import re
import sys
import json
import io
import csv
import argparse
import importlib.util
import collections

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B
import backtest_arene_economia as E

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _import_module(name, rel_path):
    path = os.path.join(_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bfg = _import_module('generatore_formazioni_globale_backtest',
                      'generatore_formazioni/build_formazione_globale.py')
bff = bfg.bff  # formazione_mls/build_formazione_finale.py, gia' importato da bfg

MOLTIPLICATORE_CAPITANO = 1.2
RUOLO_SORARE_TO_CODICE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}

# lega Sorare (domesticLeague.slug) -> cartella formazione_<x>. Copia della
# tabella in discovery_fixture.py:LEAGUE_DIR (non importata direttamente:
# quel modulo importa a sua volta pipeline di discovery con effetti collaterali
# all'import). Va tenuta allineata a mano se la tabella la' cresce.
LEAGUE_DIR = {
    'major-league-soccer': 'mls', 'mlspa': 'mls', 'k-league-1': 'kleague',
    'austrian-bundesliga': 'austria', 'jupiler-pro-league': 'belgio',
    'campeonato-brasileiro-serie-a': 'brasile', '1-hnl': 'croazia',
    'ligue-1-fr': 'francia', 'ligue-2-fr': 'francia2', 'bundesliga-de': 'germania',
    '2-bundesliga': 'germania2', 'j1-league': 'giappone',
    'j1-100-year-vision-league': 'giappone100', 'premier-league-gb-eng': 'inghilterra',
    'football-league-championship': 'inghilterra2', 'serie-a-it': 'italia',
    'eredivisie': 'olanda', 'primeira-liga-pt': 'portogallo',
    'premiership-gb-sct': 'scozia', 'laliga-es': 'spagna',
    'spor-toto-super-lig': 'turchia', 'superliga-dk': 'danimarca',
    'superliga-argentina-de-futbol': 'argentina', 'super-league-ch': 'svizzera',
    'super-league-1': 'grecia', 'ekstraklasa': 'polonia', 'primera-division-cl': 'cile',
    'liga-mx': 'messico', 'segunda-division-es': 'spagna2',
    'serie-b-it': 'italia2', 'first-division-b': 'belgio2',
    '2-liga': 'germania3', 'russian-premier-league': 'russia',
    'pro-league': 'arabia', 'primera-a': 'colombia',
    'eliteserien': 'norvegia', 'k-league-2': 'kleague2',
    'j2-league': 'giappone2', 'eerste-divisie': 'olanda2',
    'allsvenskan': 'svezia', 'liga-1': 'romania',
    'czech-liga': 'cechia', 'super-liga-rs': 'serbia',
    'ligat-ha-al': 'israele', 'ukrainian-premier-league': 'ucraina',
    'chinese-super-league': 'cina', 'primera-division-ve': 'venezuela',
    'tipsport-liga': 'slovacchia', 'premyer-liqa': 'azerbaigian',
}

# Famiglia nello slug dell'arena (fra 'seasonal-' e '-all_seasons') -> lega
# dedicata di bfg.ARENA_LEAGUES. Verificato sui roster REALI di
# football-1-5-may-2026 (es. 'seasonal-us-...': Kahlina/Ragen/Rossi, tutti
# MLS -> 'us' = mls). Famiglie non elencate (es. 'under_twenty_one', 'all_star')
# vanno al pool misto.
_FAMIGLIA_SLUG_A_LEGA = {
    'us': 'mls', 'korea': 'kleague', 'jupiler': 'belgio', 'netherlands': 'olanda',
    'turkey': 'turchia', 'portugal': 'portogallo', 'spain': 'spagna',
    'germany': 'germania', 'france': 'francia', 'croatia': 'croazia', 'scotland': 'scozia',
}
_SLUG_FAMIGLIA_RE = re.compile(r'seasonal-([a-z_]+)-all_seasons')

NOMINAL_CAP = {'cap 220': 220.0, 'cap 260': 260.0, 'Beginner': 260.0,
                'arena division': 260.0, 'Uncapped': None, 'arena uncapped': None}

# Beginner NON e' lo stesso tipo economico di ARENA_ALLSTARS_260: stessa
# struttura/cap (5 carte, L10<=260) ma costo d'ingresso e premi diversi
# (100 essenze / 500-250-150 contro 300 essenze / 1300-800-500, vedi
# consiglio_arena.py:52 e backtest_arene_economia.py:24-36). genera_arene_
# efficienti (build_formazione_globale.py) non ha un tipo Beginner: lo
# registriamo qui, SOLO per questo backtest, con le costanti reali di
# backtest_arene_economia.py (soglia/guadagno "reale" li' annotati, stessa
# scala di PAREGGIO_ARENA/GUADAGNO_PER_PUNTO -- verificato: i suoi valori
# "reale" per cap260/220/uncapped coincidono esattamente con quelli gia' in
# build_formazione_globale.py, quindi la stessa fonte per Beginner e'
# affidabile).
_TIPO_BEGINNER = 'ARENA_BEGINNER'


def registra_tipo_beginner():
    bfg.FORMATION_SHAPES[_TIPO_BEGINNER] = dict(bfg.FORMATION_SHAPES['ARENA_ALLSTARS_260'])
    bfg.L10_CAP_BY_TYPE[_TIPO_BEGINNER] = 260.0
    bfg.VARIANCE_MODE_TYPES.add(_TIPO_BEGINNER)
    bfg.POOL_LEAGUE_BY_TYPE[_TIPO_BEGINNER] = 'mixed'
    bfg.LABELS[_TIPO_BEGINNER] = 'Beginner'
    bfg.CAPTAIN_BONUS_BY_TYPE[_TIPO_BEGINNER] = 0.2
    bfg.PAREGGIO_ARENA[_TIPO_BEGINNER] = 264.1        # reale, backtest_arene_economia.py:56
    bfg.GUADAGNO_PER_PUNTO[_TIPO_BEGINNER] = 2.1 / 0.736  # reale, backtest_arene_economia.py:65
    bfg.COSTO_INGRESSO[_TIPO_BEGINNER] = 100


registra_tipo_beginner()


def carica(percorso):
    with io.open(percorso, encoding='utf-8') as fh:
        return json.load(fh)


def _punteggio_grezzo(g):
    p = g.get('punteggio')
    if p is None:
        return None
    return p / MOLTIPLICATORE_CAPITANO if g.get('capitano') else p


def _famiglia_slot(slot_slug):
    m = _SLUG_FAMIGLIA_RE.search(slot_slug)
    return m.group(1) if m else None


def classifica_tipo_produzione(slot):
    """Ritorna (tipo_bfg, famiglia, avviso) per uno slot di arene_storico.json.
    tipo_bfg e' una chiave di bfg.FORMATION_SHAPES (es. 'KLEAGUE_ARENA',
    'ARENA_ALLSTARS_260'). avviso non-None se e' un fallback al pool misto
    per una famiglia senza pool dedicato in produzione."""
    famiglia = _famiglia_slot(slot['slug'])
    cap = NOMINAL_CAP.get(slot['tipo'])
    if slot['tipo'] == 'Beginner':
        return _TIPO_BEGINNER, famiglia, None
    lega_dedicata = _FAMIGLIA_SLUG_A_LEGA.get(famiglia)
    if lega_dedicata and lega_dedicata in bfg.ARENA_LEAGUES:
        return bfg.arena_type(lega_dedicata), famiglia, None
    tipo_misto = {260.0: 'ARENA_ALLSTARS_260', 220.0: 'ARENA_ALLSTARS_220',
                  None: 'ARENA_ALLSTARS_UNCAPPED'}[cap]
    avviso = None
    if famiglia and famiglia != 'all_star':
        avviso = (f"famiglia '{famiglia}' senza pool dedicato in produzione "
                  f"-> trattata come {tipo_misto} (pool misto)")
    return tipo_misto, famiglia, avviso


def raccogli_giornata(formazioni, fixture, slug_ammessi=None):
    """slug_ammessi (opzionale): solo le formazioni schierate in QUESTI slot
    (slug arena) entrano nel pool -- serve a escludere le arene division
    (per-lega dedicate) e le carte usate li', vedi identifica_arena_division."""
    voci = [(k, v) for k, v in formazioni.items()
            if v['fixture'] == fixture and (slug_ammessi is None or v['slug'] in slug_ammessi)]
    carte = {}
    formazione_utente_per_slug = {}
    for _k, v in voci:
        formazione_utente_per_slug[v['slug']] = v['giocatori']
        for g in v['giocatori']:
            reale = _punteggio_grezzo(g)
            carte[g['carta']] = {'slug': g['slug'], 'ruolo': g['ruolo'], 'nome': g['nome'], 'reale': reale}
    return carte, formazione_utente_per_slug


def identifica_arena_division(arene_fx):
    """Le arene division sono i tipi PER-LEGA dedicati (Korea/Belgio/Olanda/
    Turchia/MLS...), riconosciuti da classifica_tipo_produzione tramite la
    famiglia nello slug -- NON gli All Stars misti (cap 260/220/uncapped/
    Beginner) e NON i fallback su famiglie senza pool dedicato (es.
    'under_twenty_one', gia' segnalati come 'avviso'). Ritorna (division,
    resto): due liste di slot arene_storico."""
    tipi_misti = {'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED', _TIPO_BEGINNER}
    division, resto = [], []
    for a in arene_fx:
        tipo_bfg, _famiglia, avviso = classifica_tipo_produzione(a)
        if avviso is None and tipo_bfg not in tipi_misti:
            division.append(a)
        else:
            resto.append(a)
    return division, resto


_RUOLO_TO_CODICE = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}
_GK_CAPTAIN_MARGIN = getattr(bff, 'GK_CAPTAIN_MARGIN', 0)


def _somma_grezza_formazione(v):
    """Somma delle carte + bonus capitano, per il controllo di integrita'
    di trova_formazione_valida."""
    tot = sum(g['punteggio'] / MOLTIPLICATORE_CAPITANO if g['capitano'] else g['punteggio']
              for g in v['giocatori'])
    grezzo_capitano = next((g['punteggio'] / MOLTIPLICATORE_CAPITANO
                            for g in v['giocatori'] if g['capitano']), 0.0)
    return tot + 0.2 * grezzo_capitano


def _scegli_capitano_da_atteso(carte):
    """Stessa logica di bff.pick_captain (portiere solo se supera
    GK_CAPTAIN_MARGIN), ma su una lista semplice {'ruolo','atteso',...}
    invece delle tuple (slot,row,tipo) di build_one_lineup."""
    outfield = [c for c in carte if c['ruolo'] != 'GK']
    gk = [c for c in carte if c['ruolo'] == 'GK']
    best_out = max(outfield, key=lambda c: c['atteso']) if outfield else None
    best_gk = max(gk, key=lambda c: c['atteso']) if gk else None
    if best_gk and (not best_out or best_gk['atteso'] >= best_out['atteso'] + _GK_CAPTAIN_MARGIN):
        return best_gk
    return best_out or best_gk


def bilancio_stesse_carte(cache, fixture, arene_storico, formazioni):
    """IL metodo deciso con l'utente (04/08) come confronto pulito
    definitivo -- niente riallocazione di carte, niente pool condiviso:

    Per ognuna delle TUE arene reali di quella giornata (le arene division
    escluse del tutto: quelle carte 'non esistono' per il bot), il bot
    valuta le STESSE 5 carte che hai usato tu li' (mai altre), con la sua
    previsione walk-forward. Decide se entrare confrontando la resa attesa
    in essenze (soglia/costo/guadagno REALI del tipo di quell'arena) con lo
    zero. Se entra, il punteggio e' quello vero di quelle carte (il
    capitano puo' differire dal tuo, scelto sull'atteso) sullo STESSO campo
    reale di 10 punteggi che hai affrontato tu -- nessun abbinamento
    arbitrario, nessuna riallocazione, nessun controfattuale ipotetico: e'
    l'esito CERTO di quelle carte in quel campo, che tu sia entrato o no.

    Alcune arene vanno scartate (non e' un difetto del metodo, e' un buco
    nei dati): le arene con INGRESSI MULTIPLI (stesso slug giocato piu'
    volte in un giorno) hanno spesso una sola formazione registrata in
    arene_formazioni.json per piu' righe di arene_storico.json con
    punteggi diversi -- l'abbinamento e' per (slug, punteggio esatto), e si
    scarta se la somma delle carte elencate non torna col mio_score
    dichiarato (trovato un caso reale: mio_score 363.88 ma carte che
    sommano 221.66, probabile bug di scraping sull'etichetta del punteggio,
    non un errore di questo script)."""
    fine = B.fine_giornate(arene_storico)
    fd = fine.get(fixture)
    if fd is None:
        return None

    arene_fx_tutte = [a for a in arene_storico if a['fixture'] == fixture]
    if not arene_fx_tutte:
        return None
    _division, resto = identifica_arena_division(arene_fx_tutte)
    if not resto:
        return None

    voci = [(k, v) for k, v in formazioni.items() if v['fixture'] == fixture]
    per_slug_score = {(v['slug'], round(v['mio_score'], 2)): v for _k, v in voci}

    def trova_formazione_valida(a):
        v = per_slug_score.get((a['slug'], round(a['mio_score'], 2)))
        if v is None:
            return None
        if abs(_somma_grezza_formazione(v) - a['mio_score']) > 0.5:
            return None
        return v

    resto = [a for a in resto if trova_formazione_valida(a) is not None]
    if not resto:
        return None

    carte_uniche = sorted(set((c['slug'], c['ruolo'])
                              for a in resto for c in trova_formazione_valida(a)['giocatori']))
    cutoff = B.inizio_giornata(cache, fd, carte_uniche)

    previsioni = {}
    for slug, ruolo in carte_uniche:
        r = P.score_atteso(cache, slug, ruolo, fd, cutoff)
        if r is not None and r['l10'] is not None:
            previsioni[(slug, ruolo)] = r

    premi_tab = E.tabella_premi(arene_storico)
    decisioni = []
    for a in resto:
        v = trova_formazione_valida(a)
        tipo_bfg, _fam, _av = classifica_tipo_produzione(a)
        soglia = bfg.PAREGGIO_ARENA.get(tipo_bfg)
        guadagno = bfg.GUADAGNO_PER_PUNTO.get(tipo_bfg, 7.5)
        costo = E.costo(a)

        carte, ok = [], True
        for g in v['giocatori']:
            pred = previsioni.get((g['slug'], g['ruolo']))
            if pred is None:
                ok = False
                break
            reale = g['punteggio'] / MOLTIPLICATORE_CAPITANO if g['capitano'] else g['punteggio']
            carte.append({'ruolo': _RUOLO_TO_CODICE[g['ruolo']], 'atteso': pred['atteso'],
                          'reale': reale, 'nome': g['nome']})
        if not ok:
            decisioni.append({'arena': a, 'tipo_bfg': tipo_bfg, 'valutabile': False})
            continue

        cap = _scegli_capitano_da_atteso(carte)
        atteso_tot = sum(c['atteso'] for c in carte) + 0.2 * cap['atteso']
        resa = (atteso_tot - soglia) * guadagno if soglia is not None else None
        entra = resa is not None and resa > 0

        reale_tot = sum(c['reale'] for c in carte) + 0.2 * cap['reale']
        rank = E.piazzamento(a, a.get('mio_score'), reale_tot)
        premio = E.premio(a, rank, premi_tab)
        decisioni.append({'arena': a, 'tipo_bfg': tipo_bfg, 'valutabile': True, 'entra': entra,
                          'atteso': atteso_tot, 'resa': resa, 'costo': costo,
                          'capitano_bot': cap['nome'], 'reale': reale_tot, 'rank': rank,
                          'premio': premio})

    valutabili = [d for d in decisioni if d['valutabile']]
    entrate = [d for d in valutabili if d['entra']]
    saltate = [d for d in valutabili if not d['entra']]
    risparmiate = [d for d in saltate if d['premio'] == 0]
    perse = [d for d in saltate if d['premio'] > 0]

    costo_u = sum(E.costo(d['arena']) for d in valutabili)
    premio_u = sum(d['arena'].get('premio_essenze') or 0 for d in valutabili)
    costo_b = sum(d['costo'] for d in entrate)
    premio_b = sum(d['premio'] for d in entrate)
    risparmio = sum(d['costo'] for d in risparmiate)
    occasione_persa = sum(d['premio'] - d['costo'] for d in perse)

    return {
        'fixture': fixture,
        'n_division_escluse': len(_division),
        'n_dati_incoerenti': len(arene_fx_tutte) - len(_division) - len(valutabili) - sum(
            1 for d in decisioni if not d['valutabile']),
        'n_valutabili': len(valutabili), 'n_entrate': len(entrate), 'n_saltate': len(saltate),
        'utente_costo': costo_u, 'utente_premio': premio_u, 'utente_netto': premio_u - costo_u,
        'bot_costo': costo_b, 'bot_premio': premio_b, 'bot_netto': premio_b - costo_b,
        'risparmio': risparmio, 'occasione_persa': occasione_persa,
        'bot_netto_totale': (premio_b - costo_b) + risparmio + occasione_persa,
        'decisioni': decisioni,
    }


def costruisci_role_data_e_pool(cache, fd, cutoff, carte):
    """role_data[lega][ruolo] = righe calibrate (formato bfg), pools =
    _NoFilterPool per (lega,ruolo), card_pool con le copie REALMENTE
    possedute quel giorno (contate per id-carta). 'lega' qui e' la
    domesticLeague della partita TARGET del giocatore in quella giornata
    (LEAGUE_DIR), non l'arena in cui l'utente l'ha schierato."""
    slug_ruolo_unici = sorted(set((c['slug'], c['ruolo']) for c in carte.values()))
    previsioni = {}
    mancanti = []
    lega_per_slug_ruolo = {}
    for slug, ruolo in slug_ruolo_unici:
        ctx = P.contesto(cache, slug, ruolo, fd, cutoff)
        if ctx is None:
            mancanti.append((slug, ruolo))
            continue
        r = P.score_atteso(cache, slug, ruolo, fd, cutoff)
        if r is None or r['l10'] is None:
            mancanti.append((slug, ruolo))
            continue
        previsioni[(slug, ruolo)] = r
        target = P.partita_target(cache, slug, fd)
        comp = (target['anyGame'].get('competition') or {}).get('slug') if target else None
        lega_per_slug_ruolo[(slug, ruolo)] = LEAGUE_DIR.get(comp, 'senza_lega')

    copie = collections.Counter()
    reale_per_slug_ruolo = {}
    for c in carte.values():
        chiave = (c['slug'], c['ruolo'])
        copie[chiave] += 1
        if c['reale'] is not None:
            reale_per_slug_ruolo.setdefault(chiave, c['reale'])

    leghe_presenti = sorted(set(lega_per_slug_ruolo.values()) | {'senza_lega'})
    role_data = {lg: {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in leghe_presenti}
    counts_by_role = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}

    for (slug, ruolo_s), n in copie.items():
        pred = previsioni.get((slug, ruolo_s))
        if pred is None:
            continue
        codice = RUOLO_SORARE_TO_CODICE[ruolo_s]
        lega = lega_per_slug_ruolo[(slug, ruolo_s)]
        row = {'slug': slug, 'atteso': pred['atteso'], 'low': round(pred['atteso']),
               'high': round(pred['atteso']), 'team_slug': pred.get('squadra'),
               'opponent_team_slug': pred.get('opp_slug'), 'ordinamento': None,
               'kickoff': None, 'opp_factor': None, 'league': lega, 'role_key': codice,
               # SOLO per il nostro confronto finale, mai letta da bfg/bff:
               'reale': reale_per_slug_ruolo.get((slug, ruolo_s))}
        bfg.calibra_riga(row, codice)  # scala del punteggio REALE, come in produzione
        role_data[lega][codice].append(row)
        counts_by_role[codice][slug] = {'in_season': n, 'classic': 0, 'l10': pred['l10']}

    for lg in role_data:
        for codice in role_data[lg]:
            role_data[lg][codice].sort(key=lambda r: r['atteso'], reverse=True)

    pools = {lg: {r: bfg._NoFilterPool(r, lg, role_data[lg][r]) for r in ('GK', 'DEF', 'MID', 'FWD')}
             for lg in leghe_presenti}
    card_pool = bff.CardPool(counts_by_role)
    return role_data, pools, card_pool, leghe_presenti, previsioni, mancanti


def _totale(formazione, capitano_row):
    atteso = sum(r['atteso'] for _s, r, _t in formazione)
    atteso += (MOLTIPLICATORE_CAPITANO - 1.0) * capitano_row['atteso']
    reali = [r.get('reale') for _s, r, _t in formazione]
    if any(v is None for v in reali):
        return atteso, None
    reale = sum(reali) + (MOLTIPLICATORE_CAPITANO - 1.0) * capitano_row['reale']
    return atteso, reale


def gioca_giornata(cache, fixture, arene_storico, formazioni, escludi_arena_division=False):
    fine = B.fine_giornate(arene_storico)
    fd = fine.get(fixture)
    if fd is None:
        raise SystemExit(f"giornata senza data di chiusura: {fixture}")

    arene_fx_tutte = [a for a in arene_storico if a['fixture'] == fixture]
    arena_division_slots = []
    if escludi_arena_division:
        arena_division_slots, arene_fx = identifica_arena_division(arene_fx_tutte)
        print(f"arena division ESCLUSE dal calcolo: {len(arena_division_slots)} slot")
        for a in arena_division_slots:
            fam = _famiglia_slot(a['slug']) or '?'
            print(f"  escluso: {fam:12s} punteggio {a.get('mio_score')}  premio {a.get('premio_essenze')}")
    else:
        arene_fx = arene_fx_tutte

    slug_ammessi = {a['slug'] for a in arene_fx}
    carte, formazione_utente_per_slug = raccogli_giornata(formazioni, fixture, slug_ammessi)
    if not carte:
        raise SystemExit(f"nessuna formazione utente per {fixture}")
    nome_per_slug = {c['slug']: c['nome'] for c in carte.values()}

    cutoff = B.inizio_giornata(cache, fd, sorted(set((c['slug'], c['ruolo']) for c in carte.values())))
    print(f"giornata {fixture}: chiusura {fd}, inizio-giornata (cutoff walk-forward) {cutoff}")

    role_data, pools, card_pool, leghe_presenti, previsioni, mancanti = \
        costruisci_role_data_e_pool(cache, fd, cutoff, carte)
    n_unici = len(set((c['slug'], c['ruolo']) for c in carte.values()))
    print(f"carte uniche (slug+ruolo) quel giorno: {n_unici}   leghe coinvolte: {len(leghe_presenti)}")
    print(f"con previsione+L10 validi: {len(previsioni)}   mancanti: {len(mancanti)}")
    for slug, ruolo in mancanti[:10]:
        print(f"  manca: {slug} ({ruolo})")

    # LEAGUES locale per questa run (bfg._view_for/_grow_for con pool_league
    # 'mixed' iterano su bfg.LEAGUES globale, che riflette i consigli SU
    # DISCO oggi -- qui vogliamo invece SOLO le leghe della giornata storica,
    # quindi la sostituiamo temporaneamente).
    leghe_originali = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe_presenti)
    try:
        # Slot reali di quella giornata (arene division gia' escluse sopra,
        # se richiesto), classificati nel tipo bfg giusto.
        slot_per_tipo = collections.defaultdict(list)
        avvisi_famiglia = set()
        for a in arene_fx:
            tipo_bfg, famiglia, avviso = classifica_tipo_produzione(a)
            slot_per_tipo[tipo_bfg].append(a)
            if avviso:
                avvisi_famiglia.add(avviso)
        for avviso in sorted(avvisi_famiglia):
            print(f"  nota: {avviso}")

        # Un'UNICA chiamata con TUTTI i tipi insieme (fondamentale: e' cosi'
        # che decide la produzione vera -- ad ogni passo confronta la resa
        # attesa di OGNI tipo e sceglie il migliore, non un ordine fisso
        # deciso da noi). 'massimo' e' solo un tetto largo: si ferma da sola
        # quando nessun tipo rende piu' (resa <= 0) o il pool e' esaurito.
        ordine_tipi = list(bfg.PRIORITY_ORDER) + [_TIPO_BEGINNER]
        tipi_con_slot = [t for t in ordine_tipi if t in slot_per_tipo]
        massimo = sum(len(slot_per_tipo[t]) for t in tipi_con_slot) + 15
        scelte = bfg.genera_arene_efficienti(tipi_con_slot, massimo, role_data, pools, card_pool)

        usato_per_tipo = collections.Counter()
        risultati = []
        for r in scelte:
            tipo = r['tipo']
            formazione = r['formazione']
            cap_slot, cap_row, _ct = bff.pick_captain(formazione)
            atteso, reale = _totale(formazione, cap_row)
            slots = slot_per_tipo.get(tipo, [])
            idx = usato_per_tipo[tipo]
            slot_vero = slots[idx] if idx < len(slots) else None
            usato_per_tipo[tipo] += 1
            risultati.append({
                'tipo': tipo, 'slot_vero': slot_vero,
                'modello_atteso': atteso, 'modello_reale': reale,
                'carte_modello': [(lbl, row['slug'], nome_per_slug.get(row['slug'], row['slug']))
                                  for lbl, row, _t in formazione],
                'capitano_modello': cap_row['slug'],
                'utente_giocatori': (formazione_utente_per_slug.get(slot_vero['slug'])
                                     if slot_vero else None),
            })

        # Slot reali che genera_arene_efficienti non ha mai raggiunto (si e'
        # fermata prima, per pool esaurito o resa non piu' positiva). Per il
        # bilancio in essenze (richiesta esplicita utente) si forza comunque
        # UNA formazione con le carte rimaste nel pool, per sapere cosa
        # avrebbe realizzato se fosse entrato: NON e' la decisione vera del
        # bot (che ha scelto di non entrare, la resa attesa era troppo bassa
        # o negativa), e' solo il controfattuale per calcolare risparmio/
        # occasione persa. Se il pool e' davvero esaurito per quel tipo,
        # resta 'non valutabile' (nessun numero inventato).
        for tipo, slots in slot_per_tipo.items():
            for s in slots[usato_per_tipo.get(tipo, 0):]:
                shape = bfg.FORMATION_SHAPES[tipo]
                pool_league = bfg.POOL_LEAGUE_BY_TYPE[tipo]
                l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo)
                formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                    shape, pool_league, role_data, pools, card_pool, l10_cap,
                    apply_stack_guard=False, variance_mode=True,
                    apply_positive_synergy=True, strict_gk_anti_synergy=False)
                controfattuale_atteso = controfattuale_reale = carte_controfattuale = None
                capitano_controfattuale = None
                if not errore:
                    cap_slot, cap_row, _ct = bff.pick_captain(formazione)
                    controfattuale_atteso, controfattuale_reale = _totale(formazione, cap_row)
                    carte_controfattuale = [(lbl, row['slug'], nome_per_slug.get(row['slug'], row['slug']))
                                             for lbl, row, _t in formazione]
                    capitano_controfattuale = cap_row['slug']
                risultati.append({'tipo': tipo, 'slot_vero': s, 'modello_atteso': None,
                                   'modello_reale': None, 'non_giocata': True,
                                   'controfattuale_atteso': controfattuale_atteso,
                                   'controfattuale_reale': controfattuale_reale,
                                   'carte_modello': carte_controfattuale,
                                   'capitano_modello': capitano_controfattuale,
                                   'utente_giocatori': formazione_utente_per_slug.get(s['slug'])})
    finally:
        bfg.LEAGUES = leghe_originali

    return risultati, mancanti


def bilancio_arena_per_arena(cache, fixture, arene_storico, formazioni, escludi_arena_division=True):
    """Il metodo deciso con l'utente (03/08 sera) come IL confronto pulito:
    nessun abbinamento fra tipo/formazione inventato, nessun controfattuale.

    Per ogni arena REALE di quella giornata, in ordine di convenienza (la
    migliore resa attesa fra tutte quelle ancora da decidere, esattamente
    come sceglierebbe genera_arene_efficienti, ma UNA ARENA REALE alla volta
    invece che un tipo): si prova a costruire una formazione con le carte
    rimaste, si calcola la resa attesa in essenze (soglia/guadagno REALI di
    quel tipo di arena, comprese le arene per-lega dedicate). Se la resa e'
    positiva il bot "entra" ADESSO in QUELLA arena specifica -- non una a
    caso dello stesso tipo -- e il suo punteggio reale si misura sullo
    STESSO campo di 10 punteggi che l'utente ha davvero affrontato li'. Se
    nessuna arena rimasta conviene piu', il bot si ferma: le arene rimanenti
    sono 'saltate' (costo 0, nessun premio, nessuna finzione su cosa
    avrebbe fatto).

    escludi_arena_division: se True, le arene per-lega dedicate (Korea,
    Belgio, Olanda...) sono tolte dalle OPZIONI del bot (mai costretto a
    schierare 5 carte di un solo campionato) mentre le loro carte restano
    comunque disponibili per gli altri tipi -- richiesta esplicita
    dell'utente (03/08 sera)."""
    fine = B.fine_giornate(arene_storico)
    fd = fine.get(fixture)
    if fd is None:
        return None

    arene_fx_tutte = [a for a in arene_storico if a['fixture'] == fixture]
    if not arene_fx_tutte:
        return None
    if escludi_arena_division:
        _division, arene_fx = identifica_arena_division(arene_fx_tutte)
    else:
        arene_fx = arene_fx_tutte
    if not arene_fx:
        return None

    carte, _formazione_utente_per_slug = raccogli_giornata(formazioni, fixture, None)
    if not carte:
        return None
    cutoff = B.inizio_giornata(cache, fd, sorted(set((c['slug'], c['ruolo']) for c in carte.values())))
    role_data, pools, card_pool, leghe_presenti, previsioni, mancanti = \
        costruisci_role_data_e_pool(cache, fd, cutoff, carte)

    leghe_originali = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe_presenti)
    try:
        premi_tab = E.tabella_premi(arene_storico)
        rimanenti = list(arene_fx)
        decisioni = []

        while rimanenti:
            migliore = None
            for a in rimanenti:
                tipo_bfg, _fam, _av = classifica_tipo_produzione(a)
                shape = bfg.FORMATION_SHAPES[tipo_bfg]
                pool_league = bfg.POOL_LEAGUE_BY_TYPE[tipo_bfg]
                l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
                soglia = bfg.PAREGGIO_ARENA.get(tipo_bfg)
                guadagno = bfg.GUADAGNO_PER_PUNTO.get(tipo_bfg, 7.5)
                if soglia is None:
                    continue
                stato = bfg._istantanea_pool(card_pool)
                formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                    shape, pool_league, role_data, pools, card_pool, l10_cap,
                    apply_stack_guard=False, variance_mode=True,
                    apply_positive_synergy=True, strict_gk_anti_synergy=False)
                bfg._ripristina_pool(card_pool, stato)
                if errore:
                    continue
                _cap_slot, cap_row, _ct = bff.pick_captain(formazione)
                atteso = sum(r['atteso'] for _s, r, _t in formazione) + 0.2 * cap_row['atteso']
                resa = (atteso - soglia) * guadagno
                if migliore is None or resa > migliore[0]:
                    migliore = (resa, a, tipo_bfg, shape, pool_league, l10_cap)

            if migliore is None or migliore[0] <= 0:
                break

            _resa, a, tipo_bfg, shape, pool_league, l10_cap = migliore
            formazione, _errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, l10_cap,
                apply_stack_guard=False, variance_mode=True,
                apply_positive_synergy=True, strict_gk_anti_synergy=False)
            _cap_slot, cap_row, _ct = bff.pick_captain(formazione)
            reali = [r.get('reale') for _s, r, _t in formazione]
            reale_tot = (sum(reali) + 0.2 * cap_row['reale']) if all(v is not None for v in reali) else None
            rank_bot = E.piazzamento(a, a.get('mio_score'), reale_tot) if reale_tot is not None else None
            premio_bot = E.premio(a, rank_bot, premi_tab) if rank_bot is not None else None
            decisioni.append({'arena': a, 'tipo_bfg': tipo_bfg, 'entra': True, 'reale': reale_tot,
                               'rank': rank_bot, 'premio': premio_bot, 'costo': E.costo(a)})
            rimanenti.remove(a)

        for a in rimanenti:
            decisioni.append({'arena': a, 'tipo_bfg': None, 'entra': False, 'costo': E.costo(a)})
    finally:
        bfg.LEAGUES = leghe_originali

    costo_u = sum(E.costo(d['arena']) for d in decisioni)
    premio_u = sum(d['arena'].get('premio_essenze') or 0 for d in decisioni)
    costo_b = sum(d['costo'] for d in decisioni if d['entra'])
    premio_b = sum(d['premio'] or 0 for d in decisioni if d['entra'])
    risparmio = sum(d['costo'] for d in decisioni if not d['entra'])

    return {
        'fixture': fixture, 'n_arene': len(decisioni),
        'n_giocate_bot': sum(1 for d in decisioni if d['entra']),
        'n_saltate_bot': sum(1 for d in decisioni if not d['entra']),
        'utente_costo': costo_u, 'utente_premio': premio_u, 'utente_netto': premio_u - costo_u,
        'bot_costo': costo_b, 'bot_premio': premio_b, 'bot_netto': premio_b - costo_b,
        'risparmio': risparmio, 'bot_netto_totale': (premio_b - costo_b) + risparmio,
        'decisioni': decisioni,
    }


def rapporto(risultati):
    con_slot = [r for r in risultati if r.get('slot_vero') is not None and not r.get('non_giocata')]
    extra = [r for r in risultati if r.get('slot_vero') is None and not r.get('non_giocata')]
    non_giocate = [r for r in risultati if r.get('non_giocata')]

    print(f"\n{'='*74}")
    print("BACKTEST ARENE — GENERATORE VERO (build_formazione_globale) vs utente")
    print('='*74)
    print(f"\nSlot reali coperti da una formazione modello: {len(con_slot)}")
    print(f"Formazioni extra (oltre gli slot reali noti, soglia STIMATA non vera): {len(extra)}")
    print(f"Slot reali NON giocati dal modello (pool esaurito per quel tipo): {len(non_giocate)}")

    con_reale = [r for r in con_slot if r['modello_reale'] is not None]
    if con_reale:
        du = [r['slot_vero']['mio_score'] for r in con_reale]
        dm = [r['modello_reale'] for r in con_reale]
        diff = [m - u for m, u in zip(dm, du)]
        print(f"\n--- SU {len(con_reale)} SLOT REALI (stesso slot, stesso vero risultato) ---")
        print(f"  utente : media {sum(du)/len(du):6.2f}")
        print(f"  modello: media {sum(dm)/len(dm):6.2f}")
        print(f"  differenza media: {sum(diff)/len(diff):+6.2f} punti per arena")
        vinte = sum(1 for d in diff if d > 0)
        print(f"  arene in cui il modello fa meglio: {vinte}/{len(diff)} ({vinte/len(diff):.1%})")

        con_terzo = [r for r in con_reale if r['slot_vero'].get('terzo') is not None]
        if con_terzo:
            pu = sum(1 for r in con_terzo if r['slot_vero']['mio_score'] >= r['slot_vero']['terzo'])
            pm = sum(1 for r in con_terzo if r['modello_reale'] >= r['slot_vero']['terzo'])
            print(f"\n  a premio (soglia vera, {len(con_terzo)} slot): "
                  f"utente {pu} ({pu/len(con_terzo):.1%})  modello {pm} ({pm/len(con_terzo):.1%})")

        print(f"\n--- per tipo ---")
        per_tipo = collections.defaultdict(list)
        for r in con_reale:
            per_tipo[r['tipo']].append(r['modello_reale'] - r['slot_vero']['mio_score'])
        for tipo, d in sorted(per_tipo.items(), key=lambda kv: -len(kv[1])):
            print(f"  {tipo:24s} n={len(d):3d}  differenza media {sum(d)/len(d):+6.2f}")

    if non_giocate:
        print(f"\n--- {len(non_giocate)} slot reali NON giocati dal modello ---")
        per_tipo = collections.Counter(r['tipo'] for r in non_giocate)
        for tipo, n in per_tipo.items():
            perso = sum(r['slot_vero']['mio_score'] for r in non_giocate
                        if r['tipo'] == tipo and r['slot_vero'].get('mio_score') is not None)
            print(f"  {tipo}: {n} slot saltati (l'utente li aveva giocati per {perso:.1f} punti totali)")

    if extra:
        print(f"\n--- {len(extra)} formazioni EXTRA (il modello vorrebbe entrare, "
              f"nessun terzo vero da confrontare) ---")
        per_tipo = collections.Counter(r['tipo'] for r in extra)
        for tipo, n in per_tipo.items():
            print(f"  {tipo}: {n}")


def bilancio_essenze(risultati, arene_storico_completo):
    """Costo/premio per l'utente (il fatto) e per il bot, PER TIPO REALE
    dello slot (arena['tipo'], es. 'Beginner' paga 100 e la sua tabella
    premi, 'cap 260' paga 300 e la sua) -- riusa costo()/premio()/
    piazzamento()/tabella_premi() di backtest_arene_economia.py, mai
    ricalcolate a mano qui. La tabella premi si costruisce su TUTTO
    l'archivio (piu' arene = tabella piu' stabile), come gia' fa
    backtest_arene_economia.bilancio() in produzione.

    Per gli slot che il bot ha scelto di non giocare, si usa il
    controfattuale (una formazione forzata con le carte rimaste, vedi
    gioca_giornata) SOLO per il bilancio: non e' la decisione vera del bot,
    e' 'cosa avrebbe incassato se fosse entrato', per rispondere a quanto ha
    risparmiato non giocando o perso non entrando."""
    premi_tab = E.tabella_premi(arene_storico_completo)

    utente = {'costi': 0, 'premi': 0, 'ingressi': 0}
    bot = {'costi': 0, 'premi': 0, 'ingressi': 0}
    risparmiate = {'n': 0, 'essenze': 0}
    perse = {'n': 0, 'essenze': 0}
    non_valutabili = 0

    for r in risultati:
        arena = r['slot_vero']
        if arena is None:
            continue  # formazione extra, nessuno slot reale da bilanciare
        ingresso = E.costo(arena)
        utente['ingressi'] += 1
        utente['costi'] += ingresso
        utente['premi'] += arena.get('premio_essenze') or 0

        if not r.get('non_giocata'):
            reale = r['modello_reale']
            bot['ingressi'] += 1
            bot['costi'] += ingresso
            if reale is not None:
                rank_m = E.piazzamento(arena, arena.get('mio_score'), reale)
                bot['premi'] += E.premio(arena, rank_m, premi_tab)
        else:
            reale = r.get('controfattuale_reale')
            if reale is None:
                non_valutabili += 1
                continue
            rank_m = E.piazzamento(arena, arena.get('mio_score'), reale)
            premio_m = E.premio(arena, rank_m, premi_tab)
            if premio_m > 0:
                perse['n'] += 1
                perse['essenze'] += premio_m - ingresso
            else:
                risparmiate['n'] += 1
                risparmiate['essenze'] += ingresso

    return utente, bot, risparmiate, perse, non_valutabili


def stampa_bilancio(utente, bot, risparmiate, perse, non_valutabili):
    print(f"\n{'='*74}")
    print("BILANCIO IN ESSENZE")
    print('='*74)

    print(f"\n--- 1) DATI REALI (utente, il fatto) ---")
    netto_u = utente['premi'] - utente['costi']
    print(f"  ingressi: {utente['ingressi']}   costo: {utente['costi']}   "
          f"premi: {utente['premi']}   netto: {netto_u:+d}")

    print(f"\n--- 2) DATI DEL BOT (solo dove ha scelto DAVVERO di entrare) ---")
    netto_b = bot['premi'] - bot['costi']
    print(f"  ingressi: {bot['ingressi']}   costo: {bot['costi']}   "
          f"premi: {bot['premi']}   netto: {netto_b:+d}")

    print(f"\n--- 3) BILANCIO (controfattuale sugli slot che il bot ha saltato) ---")
    print(f"  risparmiate NON giocando (avrebbe perso): {risparmiate['n']} slot, "
          f"+{risparmiate['essenze']} essenze risparmiate")
    print(f"  perse NON entrando (avrebbe vinto): {perse['n']} slot, "
          f"{perse['essenze']:+d} essenze di occasione persa")
    if non_valutabili:
        print(f"  non valutabili (pool esaurito anche forzando): {non_valutabili}")

    netto_bot_totale = netto_b + risparmiate['essenze'] + perse['essenze']
    print(f"\n  netto utente:                    {netto_u:+d}")
    print(f"  netto bot (solo ingressi reali):  {netto_b:+d}")
    print(f"  netto bot (+ risparmi/occasioni): {netto_bot_totale:+d}")


_RUOLO_ABBR = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}


def _formazione_utente_str(giocatori):
    if not giocatori:
        return '—'
    return ' · '.join(f"{_RUOLO_ABBR.get(g['ruolo'], g['ruolo'])} {g['nome']}"
                       + (' (C)' if g.get('capitano') else '') for g in giocatori)


def _formazione_bot_str(carte_modello, capitano_slug):
    if not carte_modello:
        return '—'
    return ' · '.join(f"{lbl} {nome}" + (' (C)' if slug == capitano_slug else '')
                       for lbl, slug, nome in carte_modello)


def costruisci_tabella(risultati, arene_storico_completo):
    """Una riga per slot reale (mai per formazione 'extra', che non ha uno
    slot da confrontare): dati utente, dati bot (reali se e' entrato
    davvero, controfattuali se ha scelto di saltarlo), e il confronto."""
    premi_tab = E.tabella_premi(arene_storico_completo)
    righe = []
    for r in risultati:
        arena = r['slot_vero']
        if arena is None:
            continue  # formazione extra: nessun terzo vero, fuori tabella
        ingresso = E.costo(arena)
        utente_premio = arena.get('premio_essenze') or 0
        entrato_davvero = not r.get('non_giocata')
        bot_score = r['modello_reale'] if entrato_davvero else r.get('controfattuale_reale')
        bot_atteso = r['modello_atteso'] if entrato_davvero else r.get('controfattuale_atteso')
        if bot_score is not None:
            bot_rank = E.piazzamento(arena, arena.get('mio_score'), bot_score)
            bot_premio = E.premio(arena, bot_rank, premi_tab)
        else:
            bot_rank = bot_premio = None
        righe.append({
            'fixture': arena.get('fixture'), 'arena_slug': arena['slug'],
            'tipo_reale': arena['tipo'], 'tipo_produzione': r['tipo'],
            'costo': ingresso,
            'utente_score': arena.get('mio_score'), 'utente_rank': arena.get('mio_rank'),
            'utente_premio': utente_premio, 'utente_netto': utente_premio - ingresso,
            'bot_entrato_davvero': entrato_davvero,
            'bot_atteso': round(bot_atteso, 1) if bot_atteso is not None else None,
            'bot_score': round(bot_score, 2) if bot_score is not None else None,
            'bot_rank': bot_rank, 'bot_premio': bot_premio,
            'bot_netto': (bot_premio - ingresso) if bot_premio is not None else None,
            'differenza_punti': (round(bot_score - arena.get('mio_score'), 2)
                                  if bot_score is not None and arena.get('mio_score') is not None else None),
            'differenza_netto': ((bot_premio - ingresso) - (utente_premio - ingresso)
                                  if bot_premio is not None else None),
            'utente_formazione': _formazione_utente_str(r.get('utente_giocatori')),
            'bot_formazione': _formazione_bot_str(r.get('carte_modello'), r.get('capitano_modello')),
            'note': '' if bot_score is not None else 'pool esaurito, nemmeno il controfattuale valutabile',
        })
    return righe


def scrivi_csv(righe, percorso):
    if not righe:
        return
    campi = list(righe[0].keys())
    with io.open(percorso, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=campi)
        w.writeheader()
        w.writerows(righe)


_ETICHETTA_TIPO = {
    'ARENA_ALLSTARS_260': 'All Stars cap 260', 'ARENA_ALLSTARS_220': 'All Stars cap 220',
    'ARENA_ALLSTARS_UNCAPPED': 'All Stars Uncapped', 'ARENA_BEGINNER': 'Beginner',
}


def _etichetta_tipo(tipo):
    return _ETICHETTA_TIPO.get(tipo) or bfg.LABELS.get(tipo, tipo)


def _fmt(v, decimali=1):
    if v is None:
        return '—'
    if isinstance(v, bool):
        return 'sì' if v else 'no'
    if isinstance(v, float):
        return f'{v:.{decimali}f}'
    return str(v)


def scrivi_html(righe, fixture, utente, bot, risparmiate, perse, non_valutabili, percorso):
    netto_u = utente['premi'] - utente['costi']
    netto_b = bot['premi'] - bot['costi']
    netto_b_tot = netto_b + risparmiate['essenze'] + perse['essenze']

    righe_html = []
    for r in sorted(righe, key=lambda r: (r['tipo_produzione'], -(r['utente_score'] or 0))):
        stato = ('extra' if r['note'] and 'esaurito' in r['note'] else
                 ('giocata' if r['bot_entrato_davvero'] else 'saltata'))
        classe_stato = {'giocata': 'giocata', 'saltata': 'saltata', 'extra': 'nonval'}[stato]
        etichetta_stato = {'giocata': 'entrato', 'saltata': 'saltata (controfattuale)',
                            'extra': 'non valutabile'}[stato]
        diff = r['differenza_punti']
        classe_diff = 'positivo' if (diff or 0) > 0 else ('negativo' if (diff or 0) < 0 else '')
        dn = r['differenza_netto']
        classe_dn = 'positivo' if (dn or 0) > 0 else ('negativo' if (dn or 0) < 0 else '')
        righe_html.append(f"""
        <tr class="{classe_stato}">
          <td class="tipo">{_etichetta_tipo(r['tipo_produzione'])}</td>
          <td class="stato">{etichetta_stato}</td>
          <td class="num">{_fmt(r['costo'], 0)}</td>
          <td class="num">{_fmt(r['utente_score'], 2)}</td>
          <td class="num">{_fmt(r['utente_rank'], 0)}</td>
          <td class="num">{_fmt(r['utente_premio'], 0)}</td>
          <td class="num">{_fmt(r['utente_netto'], 0)}</td>
          <td class="formazione">{r['utente_formazione']}</td>
          <td class="num">{_fmt(r['bot_score'], 2)}</td>
          <td class="num">{_fmt(r['bot_rank'], 0)}</td>
          <td class="num">{_fmt(r['bot_premio'], 0)}</td>
          <td class="num">{_fmt(r['bot_netto'], 0)}</td>
          <td class="formazione">{r['bot_formazione']}</td>
          <td class="num {classe_diff}">{_fmt(diff, 2)}</td>
          <td class="num {classe_dn}">{_fmt(dn, 0)}</td>
        </tr>""")

    html = f"""<title>Backtest arene — {fixture}</title>
<style>
  :root {{
    --bg: #fafaf9; --ink: #1c1b1a; --ink-dim: #6b6663; --line: #e4e1dc;
    --card-bg: #ffffff; --accent: #0f6e5c; --accent-soft: rgba(15,110,92,0.08);
    --utente-tint: rgba(30,90,180,0.05); --bot-tint: rgba(190,110,20,0.06);
    --saltata-bg: #fdf3d9; --saltata-ink: #7a6420;
    --nonval-bg: #efece9; --nonval-ink: #8a8580;
    --positivo: #0a7d4e; --negativo: #b3352a;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17181a; --ink: #eceae7; --ink-dim: #9b9691; --line: #333230;
      --card-bg: #201f1d; --accent: #3fcf9e; --accent-soft: rgba(63,207,158,0.10);
      --utente-tint: rgba(90,150,255,0.07); --bot-tint: rgba(255,170,80,0.08);
      --saltata-bg: #33301a; --saltata-ink: #e0c96a;
      --nonval-bg: #232220; --nonval-ink: #79746e;
      --positivo: #4ade9a; --negativo: #ff7a6b;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #17181a; --ink: #eceae7; --ink-dim: #9b9691; --line: #333230;
    --card-bg: #201f1d; --accent: #3fcf9e; --accent-soft: rgba(63,207,158,0.10);
    --utente-tint: rgba(90,150,255,0.07); --bot-tint: rgba(255,170,80,0.08);
    --saltata-bg: #33301a; --saltata-ink: #e0c96a;
    --nonval-bg: #232220; --nonval-ink: #79746e;
    --positivo: #4ade9a; --negativo: #ff7a6b;
  }}
  :root[data-theme="light"] {{
    --bg: #fafaf9; --ink: #1c1b1a; --ink-dim: #6b6663; --line: #e4e1dc;
    --card-bg: #ffffff; --accent: #0f6e5c; --accent-soft: rgba(15,110,92,0.08);
    --utente-tint: rgba(30,90,180,0.05); --bot-tint: rgba(190,110,20,0.06);
    --saltata-bg: #fdf3d9; --saltata-ink: #7a6420;
    --nonval-bg: #efece9; --nonval-ink: #8a8580;
    --positivo: #0a7d4e; --negativo: #b3352a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    margin: 0; padding: 2rem clamp(1rem, 4vw, 3rem) 4rem; color: var(--ink); background: var(--bg);
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 0.3rem; text-wrap: balance; letter-spacing: -0.01em; }}
  .sottotitolo {{ color: var(--ink-dim); font-size: 0.9rem; margin: 0 0 1.4rem; }}
  h2 {{
    font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700;
    color: var(--accent); margin: 2.4rem 0 0.9rem; border-bottom: 1px solid var(--line); padding-bottom: 0.4rem;
  }}
  .riepilogo {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
  .card {{
    border: 1px solid var(--line); background: var(--card-bg); border-radius: 10px;
    padding: 1rem 1.2rem; min-width: 220px; flex: 1 1 220px;
  }}
  .card .titolo {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-dim); margin-bottom: 0.35rem; }}
  .card .val {{ font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }}
  .card .dettaglio {{ font-size: 0.8rem; color: var(--ink-dim); margin-top: 0.3rem; }}
  .legenda {{ font-size: 0.82rem; color: var(--ink-dim); margin: 0.6rem 0 0; display: flex; gap: 1.2rem; flex-wrap: wrap; }}
  .legenda .chip {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
  .legenda .swatch {{ width: 0.8rem; height: 0.8rem; border-radius: 3px; display: inline-block; border: 1px solid var(--line); }}
  .overflow {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; background: var(--card-bg); }}
  th, td {{ border-bottom: 1px solid var(--line); padding: 0.4rem 0.6rem; text-align: left; white-space: nowrap; }}
  th {{ background: var(--accent-soft); font-weight: 600; position: sticky; top: 0; z-index: 1; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.saltata {{ background: var(--saltata-bg); color: var(--saltata-ink); }}
  tr.nonval {{ background: var(--nonval-bg); color: var(--nonval-ink); }}
  td.positivo {{ color: var(--positivo); font-weight: 700; }}
  td.negativo {{ color: var(--negativo); font-weight: 700; }}
  td.formazione {{ font-size: 0.78rem; color: var(--ink-dim); }}
  colgroup col.utente {{ background: var(--utente-tint); }}
  colgroup col.bot {{ background: var(--bot-tint); }}
</style>
<h1>Backtest arene — {fixture}</h1>
<p class="sottotitolo">Il generatore vero (build_formazione_globale.py) contro le formazioni realmente schierate, arena per arena.</p>
<p class="legenda">
  <span class="chip"><span class="swatch" style="background:var(--saltata-bg)"></span>slot che il bot ha scelto di NON giocare — colonne bot = controfattuale ("se fosse entrato con le carte rimaste")</span>
  <span class="chip"><span class="swatch" style="background:var(--nonval-bg)"></span>non valutabile nemmeno come controfattuale (pool esaurito)</span>
</p>

<h2>Bilancio essenze</h2>
<div class="riepilogo">
  <div class="card"><div class="titolo">1 · Utente (il fatto)</div>
    <div class="val">{netto_u:+d}</div>
    <div class="dettaglio">{utente['ingressi']} ingressi · costo {utente['costi']} · premi {utente['premi']}</div>
  </div>
  <div class="card"><div class="titolo">2 · Bot (solo ingressi reali)</div>
    <div class="val">{netto_b:+d}</div>
    <div class="dettaglio">{bot['ingressi']} ingressi · costo {bot['costi']} · premi {bot['premi']}</div>
  </div>
  <div class="card"><div class="titolo">3 · Bot + risparmi/occasioni</div>
    <div class="val">{netto_b_tot:+d}</div>
    <div class="dettaglio">risparmiate {risparmiate['essenze']} ({risparmiate['n']} slot) ·
        occasioni perse {perse['essenze']:+d} ({perse['n']} slot) ·
        non valutabili {non_valutabili}</div>
  </div>
</div>

<h2>Dettaglio per arena ({len(righe)} slot reali)</h2>
<div class="overflow">
<table>
  <colgroup>
    <col><col><col>
    <col class="utente"><col class="utente"><col class="utente"><col class="utente"><col class="utente">
    <col class="bot"><col class="bot"><col class="bot"><col class="bot"><col class="bot">
    <col><col>
  </colgroup>
  <thead>
    <tr>
      <th rowspan="2">Tipo arena</th><th rowspan="2">Il bot</th><th rowspan="2">Costo</th>
      <th colspan="5">Utente (reale)</th>
      <th colspan="5">Bot (reale o controfattuale)</th>
      <th colspan="2">Confronto</th>
    </tr>
    <tr>
      <th>Punti</th><th>Rank</th><th>Premio</th><th>Netto</th><th>Formazione</th>
      <th>Punti</th><th>Rank</th><th>Premio</th><th>Netto</th><th>Formazione</th>
      <th>Δ punti</th><th>Δ netto</th>
    </tr>
  </thead>
  <tbody>{''.join(righe_html)}</tbody>
</table>
</div>
"""
    with io.open(percorso, 'w', encoding='utf-8') as fh:
        fh.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', required=True)
    ap.add_argument('--csv', help='salva il dettaglio arena per arena (mio/suo/incrociato) in un CSV')
    ap.add_argument('--html', help='salva il dettaglio in una pagina HTML leggibile')
    ap.add_argument('--escludi-arena-division', action='store_true',
                     help='esclude le arene division (per-lega dedicate: Korea/Belgio/Olanda/Turchia/MLS...) '
                          'dal calcolo, punteggi/premi/carte inclusi -- il bot pesca solo dalle carte rimaste')
    args = ap.parse_args()

    cache = C.CacheLocale()
    formazioni = carica('dati_globali/arene_formazioni.json')['formazioni']
    arene_storico = carica('dati_globali/arene_storico.json')['arene']

    risultati, _mancanti = gioca_giornata(cache, args.fixture, arene_storico, formazioni,
                                           escludi_arena_division=args.escludi_arena_division)
    rapporto(risultati)
    utente, bot, risparmiate, perse, non_valutabili = bilancio_essenze(risultati, arene_storico)
    stampa_bilancio(utente, bot, risparmiate, perse, non_valutabili)

    if args.csv:
        righe = costruisci_tabella(risultati, arene_storico)
        scrivi_csv(righe, args.csv)
        print(f"\nDettaglio salvato in {args.csv} ({len(righe)} righe)")

    if args.html:
        righe = costruisci_tabella(risultati, arene_storico)
        scrivi_html(righe, args.fixture, utente, bot, risparmiate, perse, non_valutabili, args.html)
        print(f"\nDettaglio HTML salvato in {args.html} ({len(righe)} righe)")


if __name__ == '__main__':
    main()
