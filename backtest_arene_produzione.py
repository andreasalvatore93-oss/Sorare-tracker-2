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
import argparse
import importlib.util
import collections

import backtest_arene_cache as C
import backtest_arene_previsioni as P
import backtest_arene as B

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


def raccogli_giornata(formazioni, fixture):
    voci = [(k, v) for k, v in formazioni.items() if v['fixture'] == fixture]
    carte = {}
    for _k, v in voci:
        for g in v['giocatori']:
            reale = _punteggio_grezzo(g)
            carte[g['carta']] = {'slug': g['slug'], 'ruolo': g['ruolo'], 'nome': g['nome'], 'reale': reale}
    return carte


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


def gioca_giornata(cache, fixture, arene_storico, formazioni):
    fine = B.fine_giornate(arene_storico)
    fd = fine.get(fixture)
    if fd is None:
        raise SystemExit(f"giornata senza data di chiusura: {fixture}")

    carte = raccogli_giornata(formazioni, fixture)
    if not carte:
        raise SystemExit(f"nessuna formazione utente per {fixture}")

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
        # Slot reali di quella giornata, classificati nel tipo bfg giusto.
        slot_per_tipo = collections.defaultdict(list)
        arene_fx = [a for a in arene_storico if a['fixture'] == fixture]
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
        tipi_con_slot = [t for t in bfg.PRIORITY_ORDER if t in slot_per_tipo]
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
                'carte_modello': [(lbl, row['slug']) for lbl, row, _t in formazione],
                'capitano_modello': cap_row['slug'],
            })

        # Slot reali che genera_arene_efficienti non ha mai raggiunto (si e'
        # fermata prima, per pool esaurito o resa non piu' positiva).
        for tipo, slots in slot_per_tipo.items():
            for s in slots[usato_per_tipo.get(tipo, 0):]:
                risultati.append({'tipo': tipo, 'slot_vero': s, 'modello_atteso': None,
                                   'modello_reale': None, 'non_giocata': True})
    finally:
        bfg.LEAGUES = leghe_originali

    return risultati, mancanti


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', required=True)
    args = ap.parse_args()

    cache = C.CacheLocale()
    formazioni = carica('dati_globali/arene_formazioni.json')['formazioni']
    arene_storico = carica('dati_globali/arene_storico.json')['arene']

    risultati, _mancanti = gioca_giornata(cache, args.fixture, arene_storico, formazioni)
    rapporto(risultati)


if __name__ == '__main__':
    main()
