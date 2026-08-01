"""
build_formazione_globale.py -- Generatore Formazioni

Terza versione, AGGIUNTIVA rispetto a formazione_mls/build_formazione_finale.py
e formazione_kleague/build_formazione_finale.py (che restano invariati e
continuano a funzionare da soli). Legge i consigli di ruolo GIA' PRODOTTI dai
due tool esistenti (stessi file, nessuna nuova query storica -- la cache
incrementale di entrambi viene riusata cosi' com'e') e costruisce fino a 8
TIPI di lineup Sorare in un colpo solo (filtro qualita' L5/L10/L40
disattivato dal 28/07, vedi _NoFilterPool -- ridondante col filtro
starter-odds ormai sempre attivo in discovery_fixture.py, ed escludeva
candidati validi con una sola media bassa su tre):

  1. MLS_IN_SEASON       -- solo carte MLS, min 4 In Season + max 1 Classic
  2. KLEAGUE_IN_SEASON    -- identico, solo carte K League
  3. MLS_ARENA            -- solo carte MLS, cap L10 FISSO 260 (vincolante)
  4. KLEAGUE_ARENA        -- identico, solo carte K League
  5. ARENA_ALLSTARS_260   -- pool MISTO MLS+K League, cap L10 fisso 260
  6. ARENA_ALLSTARS_220   -- pool misto, cap L10 fisso 220
  7. ARENA_ALLSTARS_UNCAPPED -- pool misto, nessun cap
  8. ALLSTARS             -- 7 carte, pool misto, cap 370 SOFT (bonus, non vincolo)

Riusa (import diretto, nessuna duplicazione di logica) le funzioni generiche
di formazione_mls/build_formazione_finale.py -- CardPool, build_one_lineup,
render_lineup_html, render_report_html, pick_captain, parse_consiglio,
load_card_counts, latest_consiglio -- che sono gia' indipendenti dalla lega
(lavorano su liste generiche di slug/punteggio/squadra). Le uniche cose nuove
sono qui: quali file leggere (MLS + K League), il filtro qualita', le 8
strutture di formazione, l'ordine di priorita' e il parsing dei nuovi input.

ORDINE DI PRIORITA' (deciso esplicitamente dall'utente, 27/07): In Season
(MLS poi K League) -> Arena dedicata (MLS poi K League) -> Arena All Stars
(260 -> 220 -> uncapped) -> All Stars. Un CardPool CONDIVISO tra tutti gli 8
tipi (come nei due tool singoli) fa si' che, se il pool si esaurisce, siano
le formazioni meno prioritarie a non completarsi per prime.

Output: SOLO HTML (richiesta esplicita utente), in generatore_formazioni/output/.
"""
import os
import re
import sys
import copy
import glob
import json
import datetime
import importlib.util
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)


def _import_module(name, rel_path):
    path = os.path.join(_REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Import "a libreria" del tool MLS esistente -- SENZA eseguirne main() (e'
# protetto da if __name__ == '__main__'). Le funzioni generiche che riusiamo
# non contengono nulla di specifico MLS, solo logica di costruzione lineup.
bff = _import_module('mls_build_formazione_finale', 'formazione_mls/build_formazione_finale.py')

ROLES = ('GK', 'DEF', 'MID', 'FWD')

# LEGHE DEDICATE: i tipi "In Season <lega>" e "Arena <lega>" restano solo per
# queste due (sono i campionati in cui l'utente gioca le competizioni dedicate).
DEDICATED_LEAGUES = ('mls', 'kleague')


def _discover_leagues():
    """Tutte le leghe con i consigli dei 4 ruoli gia' prodotti. ESTESO il 27/07
    (roadmap step 3): il pool MISTO delle All Stars / Arena All Stars pescava
    solo da MLS + K League, lasciando inutilizzate le carte possedute negli
    altri ~18 campionati per cui la pipeline gira gia'. Le competizioni All
    Stars accettano qualsiasi campionato, quindi era pool buttato via.
    Quanto vale: con la varianza REALE misurata sui dati (sd bravura 4.53,
    sd rumore 18.72, stima da 15 partite), passare da 10 a 40 candidati per
    slot vale circa +2 punti attesi PER SLOT -- su 5 slot di movimento,
    ~+10 punti a formazione. E' il guadagno piu' grande misurato finora,
    molto oltre qualunque ritocco del modello (vedi sezione 27 del RIASSUNTO).
    Le leghe si scoprono dal filesystem: aggiungerne una non richiede codice.

    FIX (29/07, bug reale trovato in audit log 'formazione giornata': 'cile'
    ha SOLO la cartella FWD (mai avuta GK/DEF/MID -- l'utente possiede solo
    carte Chile attaccanti). Il glob era ancorato su '*_gk_all' e il filtro
    sotto richiedeva TUTTE e 4 le cartelle ruolo: la lega spariva per
    intero da _DISCOVERED, quindi anche il ruolo FWD con candidati validi
    generati ogni giorno (consiglio_cile_fwd) non veniva MAI considerato in
    nessuna formazione -- lavoro sprecato e candidati buoni mai schierabili.
    Ora si scopre una lega da QUALSIASI cartella ruolo trovata (non solo
    GK) e basta che ALMENO UNA delle 4 esista per includere la lega; i
    ruoli senza cartella restano semplicemente a 0 candidati, esattamente
    come gia' tollerato oggi per ruoli con dati stantii (es. svizzera/GK,
    che ha una cartella ma un consiglio vecchio/vuoto)."""
    found = {}
    league_prefix = {}
    for role in ROLES:
        suffix = f'_{role.lower()}_all'
        for role_dir in sorted(glob.glob(os.path.join(_REPO_ROOT, 'formazione_*', 'output', f'*{suffix}'))):
            champ_dir = os.path.basename(os.path.dirname(os.path.dirname(role_dir)))
            league = champ_dir[len('formazione_'):]
            prefix = os.path.basename(role_dir)[:-len(suffix)]
            league_prefix.setdefault(league, (champ_dir, prefix))
    for league, (champ_dir, prefix) in league_prefix.items():
        dirs = {r: os.path.join(champ_dir, 'output', f'{prefix}_{r.lower()}_all') for r in ROLES}
        disc = {r: os.path.join(champ_dir, 'output', f'{prefix}_{r.lower()}_discovery') for r in ROLES}
        if any(os.path.isdir(os.path.join(_REPO_ROOT, d)) for d in dirs.values()):
            found[league] = (dirs, disc)
    return found


_DISCOVERED = _discover_leagues()
LEAGUES = tuple(sorted(_DISCOVERED))

# ONLY_LEAGUES (29/07, richiesta esplicita utente: clone MLS-only del tool per
# test rapidi, senza aspettare le altre 27 leghe): comma-separated di cartelle
# lega (es. 'mls' o 'mls,kleague'). Se impostata, ignora completamente le
# leghe non elencate anche se hanno dati residui su disco da run precedenti --
# altrimenti build_formazione_globale.py leggerebbe comunque i consigli
# stantii delle altre leghe (persistono sul disco a prescindere da quali
# discovery sono girate in QUESTA run). Default vuoto = comportamento
# INVARIATO (tutte le leghe scoperte).
_ONLY_LEAGUES = {s.strip() for s in os.environ.get('ONLY_LEAGUES', '').split(',') if s.strip()}
if _ONLY_LEAGUES:
    LEAGUES = tuple(lg for lg in LEAGUES if lg in _ONLY_LEAGUES)
    print(f"ONLY_LEAGUES attivo: solo {LEAGUES}")

CONSIGLIO_DIRS = {lg: v[0] for lg, v in _DISCOVERED.items() if lg in LEAGUES}
DISCOVERY_DIRS = {lg: v[1] for lg, v in _DISCOVERED.items() if lg in LEAGUES}

OUTPUT_DIR = os.path.join(_HERE, 'output')

# LEGHE CON ARENA DEDICATA (27/07, richiesta esplicita utente): le Arene sono
# competizioni PER CAMPIONATO, quindi ognuna ha il suo tipo di formazione con
# pool ristretto a quella lega (a differenza delle All Stars, che pescano dal
# pool misto). Prima erano solo MLS e K League; estese ai campionati in cui
# l'utente gioca le Arene. NB: 'olanda' = Eredivisie, 'francia' = Ligue 1.
# Le In Season restano su MLS + K League (DEDICATED_LEAGUES sopra), non
# richieste per gli altri campionati.
ARENA_LEAGUES = tuple(lg for lg in (
    'mls', 'kleague', 'belgio', 'olanda', 'turchia', 'portogallo', 'spagna',
    'germania', 'francia', 'croazia', 'scozia',
) if lg in _DISCOVERED)

ARENA_LEAGUE_LABELS = {
    'mls': 'MLS', 'kleague': 'K League', 'belgio': 'Belgio', 'olanda': 'Eredivisie',
    'turchia': 'Turchia', 'portogallo': 'Portogallo', 'spagna': 'Spagna',
    'germania': 'Germania', 'francia': 'Ligue 1', 'croazia': 'Croazia', 'scozia': 'Scozia',
}


def arena_type(league):
    """Nome del tipo Arena dedicata di una lega. Per mls/kleague resta
    'MLS_ARENA'/'KLEAGUE_ARENA', cioe' i nomi gia' usati prima -- nessuna
    rottura di output, workflow o tabelle esistenti."""
    return f'{league.upper()}_ARENA'

# --- Strutture degli 8 tipi (role_slots/extra_roles/max_classic come nei tool
# singoli) + parametri di comportamento per tipo, tutti espliciti qui (NON si
# riusano i dizionari per-tipo del modulo importato, le chiavi sono diverse). -
FORMATION_SHAPES = {
    'MLS_IN_SEASON': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1},
    'KLEAGUE_IN_SEASON': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1},
    'ARENA_ALLSTARS_260': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ARENA_ALLSTARS_220': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ARENA_ALLSTARS_UNCAPPED': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ALLSTARS': {'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    # Identica a ALLSTARS (stessa shape/regole, richiesta esplicita utente
    # 28/07), unico vincolo aggiuntivo: pool filtrato ai soli giocatori con
    # flag Sorare u23Eligible (vedi POOL_LEAGUE_BY_TYPE['ALLSTARS_U23'] =
    # 'mixed_u23' e U23_ELIGIBLE piu' sotto). Priorita' subito sopra ALLSTARS.
    'ALLSTARS_U23': {'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
}
# Un tipo Arena dedicata per ogni lega di ARENA_LEAGUES, tutte con la stessa
# struttura (5 slot, nessun limite Classic, cap L10 260 obbligatorio).
FORMATION_SHAPES.update({
    arena_type(lg): {'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
                     'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None}
    for lg in ARENA_LEAGUES
})

LABELS = {
    'MLS_IN_SEASON': 'In Season MLS', 'KLEAGUE_IN_SEASON': 'In Season K League',
    'ARENA_ALLSTARS_260': 'Arena All Stars (cap 260)', 'ARENA_ALLSTARS_220': 'Arena All Stars (cap 220)',
    'ARENA_ALLSTARS_UNCAPPED': 'Arena All Stars (uncapped)', 'ALLSTARS': 'All Stars',
    'ALLSTARS_U23': 'All Stars Under 23',
}
LABELS.update({arena_type(lg): f'Arena {ARENA_LEAGUE_LABELS.get(lg, lg)} (cap 260)'
               for lg in ARENA_LEAGUES})

L10_CAP_BY_TYPE = {
    'ARENA_ALLSTARS_260': 260.0, 'ARENA_ALLSTARS_220': 220.0,  # ARENA_ALLSTARS_UNCAPPED: nessuna chiave = None
}
L10_CAP_BY_TYPE.update({arena_type(lg): 260.0 for lg in ARENA_LEAGUES})

# Sinergia da correlazione misurata (GK-DEF/GK-MID/DEF-MID/DEF-DEF): dovunque
# TRANNE In Season.
#
# La motivazione storica ("il target e' fisso quindi il valore atteso non
# dipende dalla correlazione") era incompleta -- la correlazione cambia
# comunque la PROBABILITA' di superare un target fisso. Il 30/07 fu quindi
# calibrata una tabella apposita (bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR), che
# pero' non e' mai stata attivata qui: e' rimasta configurata solo nella
# generate_lineups_for_type di formazione_mls/build_formazione_finale.py,
# che la produzione non chiama mai.
#
# VERIFICATO il 31/07 con la metrica giusta prima di decidere se attivarla:
# Monte Carlo su punteggi reali, compagni di squadra campionati dalla stessa
# partita vera (formazione_mls/diagnostics/ab_inseason_synergy_threshold.py).
# La probabilita' di superare le soglie 320-420 cambia fra -0.54 e +0.31
# punti percentuali, con segno incoerente: rumore. In punti attesi costa
# 0 pt (MLS) / 3 pt (K League). Quindi In Season resta ESCLUSA per scelta
# misurata, non piu' per un'assunzione teorica. Non riattivare senza
# rifare quei due test.
VARIANCE_MODE_TYPES = {'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220',
                        'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS', 'ALLSTARS_U23'}
VARIANCE_MODE_TYPES.update(arena_type(lg) for lg in ARENA_LEAGUES)

# Tipi "In Season dedicata" (31/07): estratto in una costante propria perche'
# due controlli piu' sotto (in_season_multi/apply_positive_synergy dentro
# generate_lineups_for_type) erano scritti come tupla letterale
# ('MLS_IN_SEASON', 'KLEAGUE_IN_SEASON') -- un modulo esterno (best_five.py,
# backlog "Contender") che registra un terzo tipo In Season a runtime
# (es. 'CONTENDER_IN_SEASON') non poteva estenderla senza modificare qui.
# Con l'insieme mutabile, un chiamante esterno puo' fare
# IN_SEASON_TYPES.add('CONTENDER_IN_SEASON') sulla PROPRIA istanza importata
# del modulo (import dinamico via importlib, non quella di produzione) e
# ottenere lo stesso trattamento di MLS/K League senza toccare questo file
# per ogni nuovo tipo In Season temporaneo.
IN_SEASON_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON'}

# Bonus anti-stack Sorare "Multi-club" (<3 stessa squadra): SOLO In Season e
# All Stars, mai nelle Arene (hanno il loro cap L10 obbligatorio separato).
STACK_GUARD_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS', 'ALLSTARS_U23'}

# Pannello bonus "Cap 260/370" (soft, solo segnalazione): SOLO In Season
# (soglia 260) e All Stars (soglia 370) -- le Arene hanno gia' il loro cap
# obbligatorio, non hanno questo bonus extra.
CHECK_CAP260_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS', 'ALLSTARS_U23'}

# Bonus power Sorare (season/collection/xp personale/scarcity/special edition/
# active clubs/nationality/positions, vedi CardPool.power_bonus_fraction):
# SOLO In Season e All Stars (7 e Under 23), MAI nelle Arene -- confermato
# dall'utente 28/07 ("tutto a 0 nelle arene, solo il 20% fisso capitano").
# Stessi membri di CHECK_CAP260_TYPES oggi, ma concetti distinti (un domani
# potrebbero divergere) -- tenuti come costanti separate apposta.
XP_BONUS_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS', 'ALLSTARS_U23'}

CAPTAIN_BONUS_BY_TYPE = {
    'MLS_IN_SEASON': 0.5, 'KLEAGUE_IN_SEASON': 0.5,
    'ARENA_ALLSTARS_260': 0.2, 'ARENA_ALLSTARS_220': 0.2, 'ARENA_ALLSTARS_UNCAPPED': 0.2,
    'ALLSTARS': 0.5, 'ALLSTARS_U23': 0.5,
}
CAPTAIN_BONUS_BY_TYPE.update({arena_type(lg): 0.2 for lg in ARENA_LEAGUES})
CAP260_THRESHOLD_BY_TYPE = {'MLS_IN_SEASON': 260.0, 'KLEAGUE_IN_SEASON': 260.0,
                            'ALLSTARS': 370.0, 'ALLSTARS_U23': 370.0}

# Estende (SOLO in memoria di questo processo, nessuna modifica al file) le
# tabelle per-tipo del modulo importato: render_lineup_html/format_lineup
# fanno CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5) sui NOSTRI nomi di tipo, quindi
# vanno registrati li' prima di chiamarle.
bff.CAPTAIN_BONUS_BY_TYPE.update(CAPTAIN_BONUS_BY_TYPE)
bff.CAP260_L10_THRESHOLD_BY_TYPE.update(CAP260_THRESHOLD_BY_TYPE)

# Ordine di generazione FISSO (priorita' decisa dall'utente).
# Ordine (AGGIORNATO 30/07, richiesta esplicita utente): In Season ->
# Under23 (le formazioni da 7) -> Arene dedicate (nell'ordine di
# ARENA_LEAGUES, cioe' MLS e K League per prime, poi gli altri campionati)
# -> Arena All Stars -> All Stars (da 7, sempre per ultima). Il CardPool e'
# condiviso: se le carte finiscono, restano scoperte le formazioni meno
# prioritarie.
PRIORITY_ORDER = (
    ['MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS_U23']
    + [arena_type(lg) for lg in ARENA_LEAGUES]
    + ['ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS']
)

POOL_LEAGUE_BY_TYPE = {
    'MLS_IN_SEASON': 'mls', 'KLEAGUE_IN_SEASON': 'kleague',
    'ARENA_ALLSTARS_260': 'mixed', 'ARENA_ALLSTARS_220': 'mixed', 'ARENA_ALLSTARS_UNCAPPED': 'mixed',
    'ALLSTARS': 'mixed', 'ALLSTARS_U23': 'mixed_u23',
}

# Cap DURI per tipo (30/07, richiesta esplicita utente): In Season/Under23/
# All Stars non si possono comunque schierare oltre questi numeri su Sorare
# -- generarne di piu' sprecherebbe solo il pool condiviso, mai utile.
# Applicato SIA alla richiesta esplicita (viene troncata se la supera) SIA
# alla fase "opzionale" sotto (mai generate oltre il cap). Le Arene (dedicate
# e All Stars) non hanno un vero limite Sorare, ma gli si mette comunque un
# tetto pratico per tipo per non esaurire il pool su un solo tipo (alzato
# 10->20 il 30/07, richiesta esplicita utente).
HARD_CAP_BY_TYPE = {
    'MLS_IN_SEASON': 6, 'KLEAGUE_IN_SEASON': 6,
    'ALLSTARS_U23': 4, 'ALLSTARS': 4,
}
ARENA_OPTIONAL_CAP = 20


def _is_arena_type(tipo):
    return tipo in ('ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED') \
        or tipo in {arena_type(lg) for lg in ARENA_LEAGUES}


# Punteggio atteso oltre il quale l'ingresso si ripaga, misurato su 673 arene
# reali (consiglio_arena.py). Sotto questa riga si pagano piu' essenze di
# quante se ne incassino, e le carte rendono di piu' in una competizione senza
# costo d'ingresso (All Stars da 7, Under 23).
#
# Il valore dipende dal campo, non dall'utente: e' il punteggio al quale
# l'incasso medio -- calcolato pescando i nove avversari da arene vere e i
# premi da quelli davvero visti, arene gold incluse -- uguaglia il costo.
PAREGGIO_ARENA = {
    'ARENA_ALLSTARS_260': 274.1,
    'ARENA_ALLSTARS_220': 245.7,
    'ARENA_ALLSTARS_UNCAPPED': 306.5,
    'ARENA_ALLSTARS_ELITE': 380.5,
}
PAREGGIO_ARENA.update({arena_type(lg): 274.1 for lg in ARENA_LEAGUES})

def _stampa_verdetto_arene(all_results):
    """Per ogni arena generata: conviene pagare l'ingresso con questa formazione?

    Non tocca la generazione, dice solo quali schierare. La scelta di quante
    arene giocare resta all'utente: qui c'e' il numero su cui deciderla.
    """
    righe = _righe_verdetto(all_results)
    if not righe:
        return
    conviene = sum(1 for m, _t, _a, _s in righe if m >= 0)
    print(f"\n=== CONVIENE PAGARE L'INGRESSO? ({conviene} su {len(righe)} arene)")
    print("Soglie misurate su 673 arene reali: sotto, l'ingresso costa piu' di")
    print("quanto renda, e le carte valgono di piu' in una competizione gratuita.")
    for margine, tipo, atteso, soglia in righe:
        esito = 'SCHIERA' if margine >= 0 else 'LASCIA PERDERE'
        print(f"  {LABELS.get(tipo, tipo):34s} atteso {atteso:6.1f} | "
              f"pareggio {soglia:5.1f} | {margine:+6.1f} -> {esito}")
    if conviene < len(righe):
        print(f"  -> le {len(righe) - conviene} sotto soglia: meglio All Stars da 7 "
              "o Under 23, che non costano essenze.")


def _atteso_con_capitano(r):
    """Totale atteso di una formazione, col bonus capitano incluso.

    Le soglie di pareggio vengono da punteggi REALIZZATI, che il bonus
    capitano ce l'hanno gia' dentro (+20% in arena): confrontarle con la somma
    dei soli 'atteso' grezzi sottostima ogni formazione di 12-15 punti.
    """
    atteso = sum(row['atteso'] for _, row, _ in r['formazione'])
    try:
        _slot, cap_row, _ct = bff.pick_captain(r['formazione'])
        if cap_row is not None:
            atteso += (CAPTAIN_BONUS_BY_TYPE.get(r['tipo'], 0.2)
                       * cap_row.get('atteso', 0))
    except Exception:
        pass   # senza capitano si resta al totale grezzo, mai un errore
    return atteso


def _righe_verdetto(all_results):
    """(margine, tipo, atteso, soglia) per ogni arena generata, dalla migliore.

    ATTENZIONE al capitano. La soglia viene da punteggi REALIZZATI, che il
    bonus capitano ce l'hanno gia' dentro (+20% in arena). Sommare qui i soli
    'atteso' grezzi confronterebbe due misure diverse e sottostimerebbe ogni
    formazione di 12-15 punti, scartandone parecchie che invece convengono.
    Errore trovato dall'utente il 01/08.
    """
    righe = []
    for r in all_results:
        if 'error' in r:
            continue
        soglia = PAREGGIO_ARENA.get(r['tipo'])
        if soglia is None:
            continue
        atteso = _atteso_con_capitano(r)
        righe.append((atteso - soglia, r['tipo'], atteso, soglia))
    righe.sort(reverse=True)
    return righe


def _verdetto_arene_html(all_results):
    """Lo stesso verdetto del log, ma dentro il report: e' li' che si guarda."""
    righe = _righe_verdetto(all_results)
    if not righe:
        return ''
    conviene = sum(1 for m, _t, _a, _s in righe if m >= 0)
    voci = []
    for margine, tipo, atteso, soglia in righe:
        ok = margine >= 0
        voci.append(
            f'<tr class="{"ok" if ok else "no"}">'
            f'<td>{LABELS.get(tipo, tipo)}</td>'
            f'<td style="text-align:right">{atteso:.0f}</td>'
            f'<td style="text-align:right">{soglia:.1f}</td>'
            f'<td style="text-align:right">{margine:+.1f}</td>'
            f'<td><b>{"SCHIERA" if ok else "LASCIA PERDERE"}</b></td></tr>')
    return (
        '<div class="lineup-block verdetto-arene">'
        '<style>.verdetto-arene table{border-collapse:collapse;width:100%;font-size:.85rem}'
        '.verdetto-arene td{padding:3px 8px;border-bottom:1px solid #2a2a2a}'
        '.verdetto-arene tr.ok td{color:#7bd88f}'
        '.verdetto-arene tr.no td{color:#8a8a8a}</style>'
        f'<h2>Conviene pagare l\'ingresso? — {conviene} su {len(righe)} arene</h2>'
        '<p>Soglie misurate su 673 arene reali: sotto quella riga l\'ingresso '
        'costa piu\' di quanto renda, e le carte valgono di piu\' in una '
        'competizione senza costo (All Stars da 7, Under 23).</p>'
        '<table><tr><td><b>arena</b></td><td style="text-align:right"><b>atteso</b></td>'
        '<td style="text-align:right"><b>pareggio</b></td>'
        '<td style="text-align:right"><b>margine</b></td><td><b>verdetto</b></td></tr>'
        + ''.join(voci) + '</table></div>')


# Sotto questo margine l'ingresso e' in pareggio ma non rende: 300 essenze
# immobilizzate per un guadagno atteso quasi nullo. Le stesse carte in una
# competizione senza costo (All Stars da 7, Under 23) rendono di piu', perche'
# li' qualunque premio e' guadagno netto.
# Quanto rende ogni punto sopra il pareggio, misurato su 673 arene reali: la
# curva e' ripida vicino alla soglia, perche' pochi punti spostano molto la
# probabilita' di finire nei primi tre. In cap 260 un solo punto vale 29
# essenze, quindi anche un margine di mezzo punto NON e' zero (vale 14).
GUADAGNO_PER_PUNTO = {
    'ARENA_ALLSTARS_260': 5.1, 'ARENA_ALLSTARS_220': 5.2,
    'ARENA_ALLSTARS_UNCAPPED': 5.1, 'ARENA_ALLSTARS_ELITE': 7.1,
}
GUADAGNO_PER_PUNTO.update({arena_type(lg): 5.1 for lg in ARENA_LEAGUES})

COSTO_INGRESSO = {
    'ARENA_ALLSTARS_260': 300, 'ARENA_ALLSTARS_220': 200,
    'ARENA_ALLSTARS_UNCAPPED': 300, 'ARENA_ALLSTARS_ELITE': 800,
}
COSTO_INGRESSO.update({arena_type(lg): 300 for lg in ARENA_LEAGUES})

# Si entra se il guadagno atteso vale almeno il 10% di quello che si rischia.
# Sotto quella riga si immobilizzano essenze per quasi niente, e le stesse
# carte in una competizione gratuita rendono di piu' -- li' qualunque premio e'
# guadagno netto.
QUOTA_MINIMA = 0.10


def _etichetta_arena(tipo, atteso):
    """(testo, colore) da mostrare accanto alla formazione.

    Il margine si esprime in ESSENZE, non in punti: '+0.3 punti' non dice
    niente a chi legge, '+9 essenze attese' dice tutto.
    """
    soglia = PAREGGIO_ARENA.get(tipo)
    if soglia is None:
        return None, None
    margine = atteso - soglia
    guadagno = margine * GUADAGNO_PER_PUNTO.get(tipo, 29.0)
    costo = COSTO_INGRESSO.get(tipo, 300)
    if guadagno >= costo * QUOTA_MINIMA:
        return (f'SCHIERA -- guadagno atteso +{guadagno:.0f} essenze '
                f'su {costo} di ingresso'), '#7bd88f'
    if guadagno >= 0:
        return (f'MARGINALE -- solo +{guadagno:.0f} essenze attese su {costo} '
                f'di ingresso: meglio All Stars da 7 o Under 23'), '#e0b341'
    return (f'LASCIA PERDERE -- {guadagno:.0f} essenze attese '
            f'({margine:+.0f} punti sotto il pareggio {soglia:.0f})'), '#c96b6b'


def verdetto_arena(tipo, atteso):
    """(soglia, conviene) per una formazione arena, o (None, None) se non lo e'.

    Misurato: applicare questa regola sullo storico dell'utente avrebbe portato
    il saldo da +9.800 a +54.700 essenze. Regge anche a previsioni scarse --
    con 60 punti di errore a formazione ne resta comunque il 53% -- perche' la
    decisione e' binaria: non serve indovinare il punteggio, basta ordinare
    meglio del caso.
    """
    soglia = PAREGGIO_ARENA.get(tipo)
    if soglia is None:
        return None, None
    return soglia, atteso >= soglia

# Flag Sorare u23Eligible per slug (28/07, richiesta esplicita utente: vive
# sulla CARTA non sul giocatore, ma e' un flag di gioco -- non un calcolo
# nostro su birthDay/eta', che l'utente ha esplicitamente scartato come
# inaffidabile). Popolato in main() da role_counts (gia' caricato da
# player_card_counts.json via load_card_counts, stesso file che porta L10).
U23_ELIGIBLE = {}
# Ogni Arena dedicata pesca SOLO dalla sua lega.
POOL_LEAGUE_BY_TYPE.update({arena_type(lg): lg for lg in ARENA_LEAGUES})


def _read_int_env(name, default=0):
    val = os.environ.get(name)
    if val is None or val.strip() == '':
        return default
    try:
        return int(val)
    except ValueError:
        return default


def parse_league_qty(raw, field_name, valid_leagues=DEDICATED_LEAGUES):
    """Formato 'lega:quantita,lega:quantita' (es. 'mls:4,kleague:1'). Lega
    omessa = 0. Fail-fast su lega sconosciuta o quantita' non numerica --
    meglio fermarsi subito che generare formazioni diverse da quanto chiesto.

    'valid_leagues' (27/07): le In Season restano MLS + K League, mentre
    ARENA_DEDICATA accetta tutte le leghe di ARENA_LEAGUES."""
    result = {lg: 0 for lg in valid_leagues}
    raw = (raw or '').strip()
    if not raw or raw == '0':
        # '0' da solo (senza 'lega:') e' un errore utente comune quando si
        # vuole dire "nessuna formazione di questo tipo" -- trattarlo come il
        # campo vuoto invece di un SystemExit e' piu' sicuro che indovinare
        # un'altra interpretazione, ed e' esattamente cio' che l'utente intende.
        return result
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' not in part:
            raise SystemExit(f"ERRORE in '{field_name}': '{part}' non e' nel formato lega:quantita.")
        lega, qty = part.split(':', 1)
        lega = lega.strip().lower()
        if lega not in result:
            raise SystemExit(f"ERRORE in '{field_name}': lega '{lega}' sconosciuta "
                             f"(valide: {', '.join(sorted(result))}).")
        try:
            result[lega] = int(qty.strip())
        except ValueError:
            raise SystemExit(f"ERRORE in '{field_name}': quantita' '{qty}' non numerica per lega '{lega}'.")
    return result


# --- FINESTRA GIORNATA (27/07, poi 31/07) --------------------------------
# Senza questo filtro il generatore mescolava giocatori la cui partita target
# era GIA' STATA GIOCATA con giocatori che giocano fra una settimana: entrambi
# inutili per la formazione di domani. E i secondi non hanno ancora le starter
# odds (escono a ~24-48h), quindi passavano indenni anche il filtro sulla
# soglia -- che percio' sembrava non funzionare.
#
# FIX 31/07 (bug reale: kyriani-sabbe, prossima partita 8 agosto, incluso in
# formazione mentre la giornata corrente era GAMEWEEK esplicita 1-4 agosto --
# consiglio stantio di una lega senza fixture in questa giornata, mai
# rigenerato, ma comunque dentro "adesso+7 giorni"): quando l'utente imposta
# GAMEWEEK o FIXTURE_SLUG esplicitamente, la finestra NON e' piu' una stima a
# giorni fissi da 'adesso' -- si risolve la STESSA identica giornata via
# discovery_fixture.risolvi_fixture() (stessa funzione, stessi env
# GAMEWEEK/FIXTURE_SLUG gia' passati alla pipeline) e si tiene SOLO chi ha
# kickoff dentro [inizio, fine] di QUELLA giornata. Il giorno-count
# (MATCH_WINDOW_DAYS) resta solo come fallback per il caso "nessuna gameweek
# esplicita" (auto-resolve in discovery_fixture.py), dove non c'e' una
# finestra precisa da interrogare di nuovo qui.
MATCH_WINDOW_DAYS = float(os.environ.get('MATCH_WINDOW_DAYS', '4'))
REQUIRE_KICKOFF = os.environ.get('MATCH_WINDOW_REQUIRE_KICKOFF', '1').strip() not in ('0', 'false', 'no')


def _risolvi_finestra_esplicita():
    """(inizio, fine) ISO della giornata esplicita (GAMEWEEK/FIXTURE_SLUG),
    o None se nessuna delle due e' impostata o la risoluzione fallisce --
    in quel caso _within_window ricade sul giorno-count (auto-resolve)."""
    if not os.environ.get('GAMEWEEK', '').strip() and not os.environ.get('FIXTURE_SLUG', '').strip():
        return None
    try:
        discovery_fixture = _import_module('discovery_fixture_per_finestra', 'discovery_fixture.py')
        fx = discovery_fixture.risolvi_fixture()
    except Exception as e:
        print(f"ATTENZIONE: impossibile risolvere la finestra esplicita ({e!r}), "
              f"ricado sul giorno-count MATCH_WINDOW_DAYS.")
        return None
    if not fx:
        print("ATTENZIONE: GAMEWEEK/FIXTURE_SLUG impostati ma non risolti -- "
              "ricado sul giorno-count MATCH_WINDOW_DAYS.")
        return None
    inizio = (fx.get('startDate') or '')[:19]
    fine = (fx.get('endDate') or '')[:19]
    if not inizio or not fine:
        return None
    print(f"Finestra esplicita risolta: {fx.get('slug')} (gameweek {fx.get('seasonGameWeek')}) "
          f"dal {inizio} al {fine} -- SOLO questa giornata, nessuna tolleranza a giorni.")
    return inizio, fine


_FINESTRA_ESPLICITA = None
_FINESTRA_ESPLICITA_RISOLTA = False


_CONSIGLIO_TS_RE = re.compile(r'consiglio_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})\.txt$')


def _ts_da_nome_consiglio(path):
    """Data/ora di scrittura dal NOME del file consiglio_*.txt (mai
    dall'mtime: git checkout in CI li riscrive tutti a 'adesso', rendendo
    inutile qualunque controllo di freschezza)."""
    if not path:
        return None
    m = _CONSIGLIO_TS_RE.search(os.path.basename(path))
    if not m:
        return None
    try:
        return datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}")
    except ValueError:
        return None


def _within_window(row, now=None):
    global _FINESTRA_ESPLICITA, _FINESTRA_ESPLICITA_RISOLTA
    if not _FINESTRA_ESPLICITA_RISOLTA:
        _FINESTRA_ESPLICITA = _risolvi_finestra_esplicita()
        _FINESTRA_ESPLICITA_RISOLTA = True

    ko = row.get('kickoff')
    if not ko:
        return not REQUIRE_KICKOFF

    if _FINESTRA_ESPLICITA:
        inizio, fine = _FINESTRA_ESPLICITA
        ko19 = ko[:19] if 'T' in ko else ko[:10] + 'T00:00:00'
        if not (inizio <= ko19 <= fine):
            return False
        # Non basta che il KICKOFF cada per data dentro la finestra: un file
        # vecchio di giorni (lega mai ri-scoperta per QUESTA giornata) puo'
        # avere per puro caso un KICKOFF salvato che coincide con la finestra
        # attuale (visto su kodai-sano/olanda, 31/07 -- lega non ha nessuna
        # partita reale in questa giornata, il dato stantio combaciava per
        # caso). Il file deve essere stato SCRITTO non troppo prima
        # dell'inizio della finestra -- altrimenti non e' un dato verificato
        # per QUESTA giornata.
        #
        # ATTENZIONE (31/07, secondo tentativo): la data di scrittura NON puo'
        # venire dall'mtime del file -- git checkout in CI riscrive tutti gli
        # mtime al momento del checkout, quindi in GitHub Actions ogni file
        # sembrava appena creato e il controllo non filtrava NULLA (primo fix
        # inefficace, i giocatori stantii ricomparivano). Si usa invece il
        # timestamp nel NOME del file (consiglio_YYYY-MM-DD_HHMMSS.txt),
        # scritto dal generatore e immune al checkout.
        scritto = row.get('_source_ts')
        if scritto is None:
            return not REQUIRE_KICKOFF
        try:
            inizio_dt = datetime.datetime.fromisoformat(inizio)
        except ValueError:
            return True
        return scritto >= inizio_dt - datetime.timedelta(hours=24)

    now = now or datetime.datetime.utcnow()
    try:
        dt = datetime.datetime.fromisoformat(ko[:16]) if 'T' in ko else             datetime.datetime.fromisoformat(ko[:10])
    except ValueError:
        return not REQUIRE_KICKOFF
    if dt < now - datetime.timedelta(hours=2):
        return False
    return dt.date() <= now.date() + datetime.timedelta(days=int(MATCH_WINDOW_DAYS))


def filter_by_window(role_data):
    """Scarta i candidati la cui partita target e' fuori dalla finestra."""
    out = {}
    for lg, roles in role_data.items():
        out[lg] = {}
        for role, rows in roles.items():
            kept = [r for r in rows if _within_window(r)]
            out[lg][role] = kept
    return out


def load_league_role_data():
    """Ritorna (role_data, role_counts, names) per lega, riusando
    parse_consiglio/load_card_counts/load_player_names/latest_consiglio del
    modulo importato -- identica logica dei due tool singoli, su TUTTE le
    leghe scoperte."""
    role_data = {lg: {} for lg in LEAGUES}
    role_counts = {lg: {} for lg in LEAGUES}
    names = {}
    for league in LEAGUES:
        for role in ROLES:
            out_dir = CONSIGLIO_DIRS[league][role]
            path = bff.latest_consiglio(out_dir)
            rows = bff.parse_consiglio(path) if path else []
            # 'league' (28/07, fix bug reale trovato dall'utente: alternative
            # cross-lega non eleggibili proposte nel drag&drop, es. un
            # centrocampista croato suggerito per una In Season MLS dove non
            # e' nemmeno schierabile) -- serve a _build_alt_chips per
            # filtrare le alternative alla lega/pool della formazione
            # bersaglio, non solo al ruolo.
            # '_source_ts' (31/07, fix bug reale kodai-sano/olanda: un
            # KICKOFF salvato giorni fa puo' cadere per puro caso dentro la
            # finestra della giornata esplicita ANCHE SE quella lega non ha
            # nessuna partita reale in questa giornata -- la lega
            # semplicemente non e' stata ri-scoperta oggi, il dato e' stantio
            # e coincide per caso. Vedi _within_window per l'uso.
            # Dal NOME del file, non dall'mtime: git checkout in CI riscrive
            # gli mtime e li rende tutti "adesso".
            ts_file = _ts_da_nome_consiglio(path)
            for row in rows:
                row['league'] = league
                row['_source_ts'] = ts_file
            counts, _ = bff.load_card_counts(DISCOVERY_DIRS[league][role])
            # starterOdds sulle righe (31/07): il valore e' gia' dentro
            # player_card_counts.json, scritto da discovery_fixture.py nella
            # stessa entry di copie/L10 -- serve al tie-break fra candidati
            # con punteggio quasi identico (vedi _chiave_ordinamento). Chi non
            # ce l'ha (discovery vecchia, precedente a questo fix) resta senza
            # e viene trattato come "odds ignote", quindi nessun bonus:
            # comportamento invariato rispetto a prima.
            for row in rows:
                odds = (counts.get(row['slug']) or {}).get('starter_odds')
                if odds is not None:
                    row['starter_odds'] = odds
            names.update(bff.load_player_names(DISCOVERY_DIRS[league][role]))
            print(f"[{league}/{role}] {path or 'NESSUN FILE TROVATO'} -> {len(rows)} giocatori")
            role_data[league][role] = rows
            role_counts[league][role] = counts
    return role_data, role_counts, names


GROW_BATCH = int(os.environ.get('QUALITY_GROW_BATCH', '3'))
SLOT_RE = re.compile(r'slot (\S+) \(')


class _NoFilterPool:
    """Sostituto di LazyQualityPool da quando il filtro qualita' L5/L10/L40
    e' stato disattivato (28/07, richiesta esplicita utente): era ridondante
    col filtro starter-odds ormai sempre attivo in discovery_fixture.py, ed
    escludeva per intero candidati validi con una sola media bassa su tre --
    caso reale: Inaki Pena, L10=46/L40=49 (solidi) ma L5=26 (una striscia
    recente), escluso a prescindere dal fatto che il modello predittivo lo
    valutasse comunque 32pt. Tutti i candidati scoperti sono gia' 'passing',
    zero query di rete verso Sorare per questo filtro."""

    def __init__(self, role, league, full_candidates):
        self.role = role
        self.league = league
        self.full = full_candidates
        self.checked_idx = len(full_candidates)
        self.passing = list(full_candidates)

    def grow(self, batch):
        return 0


def build_quality_pools(role_data):
    """Un pool per (lega, ruolo) con TUTTI i candidati scoperti gia' inclusi
    (filtro qualita' disattivato, vedi _NoFilterPool)."""
    return {
        league: {role: _NoFilterPool(role, league, role_data[league][role])
                  for role in ROLES}
        for league in LEAGUES
    }


# --- Preferenza per le starter odds alte (31/07, richiesta esplicita utente)
#
# Regola voluta: "se il bot deve scegliere tra due giocatori con project score
# entro 2 punti di distanza, preferire quello con starter odds 0.80 anche se
# l'altro ha un punteggio maggiore". Esempio dell'utente: Son 66 (0.70) contro
# Zinckernagel 64 (0.80) -> vince Zinckernagel; ma se Zinckernagel avesse 63
# (scarto 3) -> vince Son.
#
# Implementata come BONUS di PREFERENZA_ODDS_SCARTO punti al punteggio di
# ordinamento, non come confronto a coppie: un "sono equivalenti entro 2
# punti" non e' un ordinamento valido (A~B e B~C non implicano A~C, quindi il
# risultato dipenderebbe dall'ordine di confronto). Col bonus invece la
# regola vale sempre e in modo trasparente:
#   Zinck 64 + 2 = 66 pari a Son 66 -> a parita' vince chi ha le odds piu'
#   alte, quindi Zinck. Zinck 63 + 2 = 65 < 66 -> vince Son. Esattamente i due
#   casi dell'esempio.
# NON tocca il punteggio mostrato ne' i totali: agisce solo sull'ordine con
# cui i candidati vengono considerati.
PREFERENZA_ODDS_SOGLIA = float(os.environ.get('PREFERENZA_ODDS_SOGLIA', '0.80'))
PREFERENZA_ODDS_SCARTO = float(os.environ.get('PREFERENZA_ODDS_SCARTO', '2'))


def _chiave_ordinamento(row):
    base = row.get('sort_score', row['atteso'])
    odds = row.get('starter_odds') or 0.0
    bonus = PREFERENZA_ODDS_SCARTO if odds >= PREFERENZA_ODDS_SOGLIA else 0.0
    return (base + bonus, odds)


def _sort_ordinamento(rows):
    # REVERTITO (30/07, stesso motivo di build_consiglio_def.py/build_
    # consiglio.py -- vedi RIASSUNTO sez. 0.D punto 30): il vecchio
    # ordinamento per 'ordinamento' (senza shrinkage) non si conferma piu'
    # con dati aggiornati, e questa funzione lo stava ancora usando qui
    # nonostante il fix a monte -- bug reale trovato in corsa. Ordina sempre
    # per 'sort_score' se presente (bonus XP per la selezione, vedi
    # _apply_xp_bonus), altrimenti per 'atteso' (il punteggio vero).
    rows.sort(key=_chiave_ordinamento, reverse=True)
    return rows


def _view_for(pools, pool_league, role):
    if pool_league == 'mixed':
        combined = [r for lg in LEAGUES for r in pools[lg][role].passing]
        return _sort_ordinamento(combined)
    if pool_league == 'mixed_u23':
        combined = [r for lg in LEAGUES for r in pools[lg][role].passing
                    if U23_ELIGIBLE.get(r['slug'])]
        return _sort_ordinamento(combined)
    return pools[pool_league][role].passing


def _next_unchecked_score(pool):
    """Punteggio del prossimo candidato non ancora controllato (o None)."""
    if pool.checked_idx >= len(pool.full):
        return None
    row = pool.full[pool.checked_idx]
    return row.get('ordinamento') if row.get('ordinamento') is not None else row.get('atteso')


def _grow_for(pools, pool_league, role, batch):
    if pool_league not in ('mixed', 'mixed_u23'):
        return pools[pool_league][role].grow(batch)
    # Pool misto su TUTTE le leghe (27/07): crescere batch carte PER LEGA
    # significherebbe moltiplicare per ~20 le query L5/L10/L40 -- e un 429
    # quasi certo. Si cresce invece una carta alla volta, sempre quella col
    # punteggio piu' alto fra le prime non ancora controllate di ogni lega:
    # stesso costo in query del caso a due leghe, ma pescando dal pool intero.
    checked = 0
    while checked < batch:
        best_lg, best_score = None, None
        for lg in LEAGUES:
            sc = _next_unchecked_score(pools[lg][role])
            if sc is None:
                continue
            if best_score is None or sc > best_score:
                best_lg, best_score = lg, sc
        if best_lg is None:
            break
        checked += pools[best_lg][role].grow(1)
    return checked


def _raw_view_for(role_data, pool_league, role):
    if pool_league == 'mixed':
        combined = [r for lg in LEAGUES for r in role_data[lg][role]]
        return _sort_ordinamento(combined)
    if pool_league == 'mixed_u23':
        combined = [r for lg in LEAGUES for r in role_data[lg][role] if U23_ELIGIBLE.get(r['slug'])]
        return _sort_ordinamento(combined)
    return role_data[pool_league][role]


def _apply_xp_bonus(rows, card_pool):
    """Ritorna una COPIA delle righe con un campo 'sort_score' aggiunto
    (atteso moltiplicato per 1 + bonus power della carta, vedi
    CardPool.power_bonus_fraction) -- usato SOLO per decidere l'ORDINE di
    scelta tra candidati, MAI per il numero mostrato.

    FIX 30/07 (bug reale trovato dall'utente, caso Navarro: 69pt in una
    formazione In Season contro 62pt -- lo stesso identico contesto -- in
    un'Arena): PRIMA questa funzione mutava 'atteso'/'low'/'high' stessi,
    quindi il candidato SELEZIONATO portava con se' il numero gonfiato fino
    al rendering, e il fix del 30/07 mattina (apply_xp_bonus=False nel
    render) toglieva solo il tag separato "+XX% XP", non il numero di base
    gia' inquinato a monte. Ora 'atteso'/'low'/'high' non vengono MAI
    toccati -- il bonus entra in gioco solo per scegliere CHI vince lo slot,
    il punteggio mostrato resta sempre quello vero. MAI muta le righe
    originali (condivise fra tutti i tipi di formazione nella stessa run,
    incluse le Arene dove questo bonus NON si applica, vedi XP_BONUS_TYPES).
    Righe senza bonus noto (frazione 0.0) restano le stesse istanze."""
    out = []
    for r in rows:
        frac = card_pool.power_bonus_fraction(r['slug'])
        if not frac:
            out.append(r)
            continue
        r2 = dict(r)
        r2['sort_score'] = round(r['atteso'] * (1.0 + frac))
        out.append(r2)
    return _sort_ordinamento(out)


def build_one_lineup_with_growth(shape, pool_league, role_data, pools, card_pool, l10_cap,
                                  apply_stack_guard, variance_mode, apply_positive_synergy=True,
                                  strict_gk_anti_synergy=False, used_matches=None, apply_xp_bonus=False):
    """Se il tipo ha un cap L10 obbligatorio (Arena dedicate/All Stars) usa
    il pool GREZZO via _raw_view_for; altrimenti (In Season, All Stars, Arena
    All Stars uncapped) passa da 'pools' (_view_for) -- dal 28/07 entrambi i
    percorsi vedono comunque TUTTI i candidati scoperti, perche' il filtro
    qualita' e' disattivato (vedi _NoFilterPool): la distinzione resta solo
    per come 'pools' viene fatto crescere/riletto, non piu' per COSA include."""
    if l10_cap is not None:
        role_data_view = {role: _raw_view_for(role_data, pool_league, role) for role in ROLES}
        if apply_xp_bonus:
            role_data_view = {role: _apply_xp_bonus(rows, card_pool) for role, rows in role_data_view.items()}
        return bff.build_one_lineup(shape, role_data_view, card_pool, l10_cap=l10_cap,
                                     apply_stack_guard=apply_stack_guard, variance_mode=variance_mode,
                                     apply_positive_synergy=apply_positive_synergy,
                                     strict_gk_anti_synergy=strict_gk_anti_synergy, used_matches=used_matches)

    while True:
        role_data_view = {role: _view_for(pools, pool_league, role) for role in ROLES}
        if apply_xp_bonus:
            role_data_view = {role: _apply_xp_bonus(rows, card_pool) for role, rows in role_data_view.items()}
        formazione, error, l10_ok, stack_perso = bff.build_one_lineup(
            shape, role_data_view, card_pool, l10_cap=l10_cap,
            apply_stack_guard=apply_stack_guard, variance_mode=variance_mode,
            apply_positive_synergy=apply_positive_synergy, strict_gk_anti_synergy=strict_gk_anti_synergy,
            used_matches=used_matches)
        if not error:
            return formazione, None, l10_ok, stack_perso

        m = SLOT_RE.search(error)
        raw_slot = m.group(1) if m else ''
        if raw_slot == 'extra':
            roles_to_grow = shape['extra_roles']
        else:
            role = re.sub(r'\d+$', '', raw_slot)
            roles_to_grow = [role] if role in ROLES else ROLES

        progressed = any(_grow_for(pools, pool_league, r, GROW_BATCH) > 0 for r in roles_to_grow)
        if not progressed:
            return None, error, l10_ok, stack_perso


def generate_lineups_for_type(tipo, count, role_data, pools, card_pool):
    """FASE 1 (28/07, refactor per il pannello alternative): genera e CONSUMA
    il card_pool, ma non renderizza piu' l'HTML qui -- lo si fa in una
    seconda passata in main(), quando si conoscono TUTTE le formazioni di
    TUTTI i tipi (serve per proporre alternative cross-lineup per vicinanza
    di punteggio). Ritorna una lista di dict, uno per formazione (chiave
    'error' se non generata)."""
    if count <= 0:
        return []
    shape = FORMATION_SHAPES[tipo]
    pool_league = POOL_LEAGUE_BY_TYPE[tipo]
    cap = L10_CAP_BY_TYPE.get(tipo)
    stack_guard = tipo in STACK_GUARD_TYPES
    variance_mode = tipo in VARIANCE_MODE_TYPES
    check_cap260 = tipo in CHECK_CAP260_TYPES
    label = LABELS[tipo]
    # 27/07, richiesta esplicita utente, stesso fix identico nei due tool
    # singoli: con 2+ In Season richieste (MLS o K League, ciascuna lega
    # conta a se'), solo la prima usa la sinergia GK-DEF soft, le altre sono
    # greedy puro; in ENTRAMBI i casi il vincolo portiere-vs-avversario
    # diventa DURO. Con 1 sola In Season di quella lega, comportamento
    # INVARIATO. Le Arene (dedicate o All Stars) non sono toccate.
    in_season_multi = tipo in IN_SEASON_TYPES and count >= 2
    # Cap 370 forzato sulla PRIMA All Stars da 7 (28/07, richiesta esplicita
    # utente): la prima delle N All Stars generate, in teoria la piu' forte,
    # prova a rispettare il cap 370 (oggi solo un bonus segnalato via
    # check_cap260, mai un vincolo di generazione). Se forzarlo comprometterebbe
    # la generazione di una qualunque delle restanti All Stars richieste (pool
    # troppo eroso dal vincolo sulla prima), si rinuncia e si rigenera l'intera
    # serie senza forzare -- vedi retry sotto, mai un compromesso silenzioso.
    force_cap370_first = tipo in ('ALLSTARS', 'ALLSTARS_U23') and count >= 1
    apply_xp_bonus = tipo in XP_BONUS_TYPES

    def _run(force_first):
        # Varianza capitano (27/07, richiesta esplicita utente, stesso fix
        # identico nei due tool singoli): scope per tipo (uno degli 8 qui).
        captained_slugs = set()
        # Decorrelazione tra le N formazioni In Season -- DISATTIVATA di nuovo
        # (29/07, A/B test locale post-fix: disattivandola MLS +21pt/6
        # formazioni, K League +2pt/6, nessun'altra lega ha abbastanza
        # formazioni multiple per attivare il meccanismo). Il beneficio di
        # decorrelazione (rischio diversificato tra formazioni) non e'
        # catturato dal punteggio atteso totale, ma l'utente ha scelto
        # esplicitamente di privilegiare il guadagno misurato.
        used_matches = None

        risultati = []
        for idx in range(1, count + 1):
            strict_gk_anti_synergy = in_season_multi
            # ARENA_ALLSTARS_UNCAPPED esclusa (29/07, bug reale misurato: A/B
            # test locale su 6 formazioni, SAME_TEAM_SYNERGY_BONUS_BY_PAIR
            # ATTIVO = 1880 pt totali, DISATTIVATO = 1920 pt -- il bonus fa
            # scegliere combo stacked che valgono MENO in punteggio atteso
            # reale. 260/220 invariati: stesso test li' da' risultato
            # IDENTICO on/off, il cap L10 obbligatorio rende la sinergia
            # ininfluente, nessun motivo di toccarli).
            # In Season MLS/K League esclusi anch'essi (29/07, A/B test locale
            # su 6 formazioni post-fix: MLS baseline 2033 -> senza bonus 2035
            # (+2pt), K League 1927 -> 1927 (invariato, nessun costo). Qualunque
            # guadagno positivo giustifica la disattivazione, richiesta esplicita
            # utente ("non esiste un guadagno trascurabile").
            # NOTA (31/07, audit): questo flag e' il gate UNICO di TRE
            # meccanismi diversi dentro bff.synergy_sort_key -- nudge GK-DEF
            # (POSITIVE_SYNERGY_BONUS/ANTI_SYNERGY_PENALTY), penalita'
            # cross-team (CROSS_TEAM_PENALTY_BY_PAIR) e bonus same-team
            # (_same_team_synergy_bonus). Metterlo a False per un tipo li
            # spegne tutti e tre insieme, anche quando l'intenzione era
            # spegnerne uno solo: e' cosi' che le penalita' cross-team
            # aggiornate il 30/07 sono risultate inerti sulle In Season.
            # Se un domani serve un controllo piu' fine, vanno separati in
            # tre flag distinti invece di sovraccaricare questo.
            apply_positive_synergy = (tipo not in (IN_SEASON_TYPES | {'ARENA_ALLSTARS_UNCAPPED'})
                                       and (not in_season_multi or idx == 1))
            idx_cap = 370.0 if (force_first and idx == 1) else cap
            formazione, error, l10_ok, stack_perso = build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, idx_cap, stack_guard, variance_mode,
                apply_positive_synergy, strict_gk_anti_synergy, used_matches, apply_xp_bonus)
            if error:
                msg = f"Formazione {label} #{idx}: NON GENERATA — {error}"
                print(msg)
                risultati.append({'error': msg})
                break
            if used_matches is not None:
                for _, row, _ in formazione:
                    team, opponent = row.get('team_slug'), row.get('opponent_team_slug')
                    if team and opponent:
                        used_matches.add(frozenset((team, opponent)))
            # avoid_captain_slugs va catturato COSI' com'e' ORA (solo i capitani
            # delle formazioni precedenti dello stesso tipo) -- render_lineup_html
            # lo user' in fase 2 per decidere lo stesso identico capitano scelto qui.
            avoid_snapshot = set(captained_slugs)
            _cap_slot, cap_row, _cap_type = bff.pick_captain(formazione, captained_slugs)
            captained_slugs.add(cap_row['slug'])
            risultati.append({
                'tipo': tipo, 'label': label, 'idx': idx, 'formazione': formazione,
                'l10_cap': idx_cap, 'l10_ok': l10_ok, 'stack_perso': stack_perso,
                'check_cap260': check_cap260, 'stack_guard': stack_guard,
                'avoid_captain_slugs': avoid_snapshot,
            })
            print(f"Formazione {label} #{idx}: generata ({sum(r['atteso'] for _, r, _ in formazione)} pt)")
        return risultati

    if not force_cap370_first:
        return _run(False)

    used_snapshot = copy.deepcopy(card_pool._used)
    risultati = _run(True)
    if any('error' in r for r in risultati):
        print(f"Formazione {label}: cap 370 forzato sulla #1 comprometteva la serie, rigenero senza forzarlo.")
        card_pool._used = used_snapshot
        risultati = _run(False)
    return risultati


_slot_role = bff._slot_role  # canonico, usato per _apply_xp_bonus/altre logiche


# --- Struttura a sezioni/tab (31/07, richiesta esplicita utente: la stessa
# navigazione gia' presente in Best Five, ma con le categorie di questo tool)
#
# Le formazioni OPZIONALI stanno in una sezione propria a prescindere dal
# tipo: sono "extra generate col pool residuo", quindi la distinzione utile
# per l'utente e' proprio richiesta-vs-opzionale, non il campionato.
SEZIONI_REPORT = (
    ('in_season', 'In Season'),
    ('arene_dedicate', 'Arene dedicate'),
    ('arene_allstars', 'Arene All Stars'),
    ('allstars', 'All Stars'),
    ('under23', 'Under 23'),
    ('opzionali', 'Opzionali'),
)


def _sezione_di(tipo, extra=False):
    """Sezione di appartenenza di una formazione, dal suo tipo."""
    if extra:
        return 'opzionali'
    if tipo in IN_SEASON_TYPES:
        return 'in_season'
    if tipo == 'ALLSTARS_U23':
        return 'under23'
    if tipo == 'ALLSTARS':
        return 'allstars'
    if tipo.startswith('ARENA_ALLSTARS'):
        return 'arene_allstars'
    if _is_arena_type(tipo):
        return 'arene_dedicate'
    return 'opzionali'


TAB_SEZIONI_SNIPPET = r"""
<style>
  .bf-topbar {
    position: sticky; top: 0; z-index: 40;
    background: color-mix(in srgb, var(--bg) 92%, transparent);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    margin: 0 0 20px 0; padding-top: 6px;
  }
  .bf-tabs { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; }
  .bf-tabs::-webkit-scrollbar { display: none; }
  .bf-tab {
    appearance: none; border: none; background: none; color: var(--muted);
    font-size: 0.84rem; font-weight: 600; padding: 10px 16px 12px; cursor: pointer;
    border-bottom: 2px solid transparent; white-space: nowrap; font-family: inherit;
    transition: color 0.15s ease;
  }
  .bf-tab:hover { color: var(--text); }
  .bf-tab[aria-current="true"] { color: var(--text); border-bottom-color: var(--gold); }
  .bf-tab .bf-count { color: var(--muted-2); font-weight: 700; margin-left: 5px; }
</style>
<script>
(function () {
  var SEZIONI = __SEZIONI__;
  var blocchi = Array.prototype.slice.call(document.querySelectorAll('[data-sezione]'));
  if (!blocchi.length) return;

  var gruppi = {};
  blocchi.forEach(function (b) {
    var s = b.getAttribute('data-sezione');
    (gruppi[s] = gruppi[s] || []).push(b);
  });

  var bar = document.createElement('div');
  bar.className = 'bf-topbar';
  var nav = document.createElement('nav');
  nav.className = 'bf-tabs';
  bar.appendChild(nav);

  // Il separatore delle OPZIONALI e' un blocco a se' (non ha data-sezione):
  // va mostrato solo quando quelle formazioni sono visibili.
  var divisore = null;
  document.querySelectorAll('div').forEach(function (d) {
    if (!divisore && d.textContent.indexOf('Formazioni OPZIONALI (extra') === 0) { divisore = d; }
  });

  function mostra(vista, btn) {
    Array.prototype.slice.call(nav.children).forEach(function (b) { b.removeAttribute('aria-current'); });
    if (btn) btn.setAttribute('aria-current', 'true');
    blocchi.forEach(function (b) {
      var s = b.getAttribute('data-sezione');
      b.style.display = (vista === 'tutto' || vista === s) ? '' : 'none';
    });
    if (divisore) {
      divisore.style.display = (vista === 'tutto' || vista === 'opzionali') ? '' : 'none';
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function tab(id, label, n) {
    var b = document.createElement('button');
    b.className = 'bf-tab';
    b.type = 'button';
    b.textContent = label;
    if (n) {
      var sp = document.createElement('span');
      sp.className = 'bf-count';
      sp.textContent = n;
      b.appendChild(sp);
    }
    b.addEventListener('click', function () { mostra(id, b); });
    nav.appendChild(b);
    return b;
  }

  var primo = tab('tutto', 'Tutte', blocchi.length);
  SEZIONI.forEach(function (s) {
    if ((gruppi[s[0]] || []).length) { tab(s[0], s[1], gruppi[s[0]].length); }
  });

  var ancora = document.querySelector('p.subhead') || document.querySelector('h1');
  if (ancora && ancora.parentNode) {
    ancora.parentNode.insertBefore(bar, ancora.nextSibling);
  } else {
    document.body.insertBefore(bar, document.body.firstChild);
  }
  mostra('tutto', primo);
})();
</script>
"""


def aggiungi_tab_sezioni(html_report):
    """Barra di tab per filtrare le formazioni per categoria -- "Tutte" mostra
    tutto (default), le altre isolano una sola sezione. Additiva, iniettata in
    coda: il template resta condiviso e invariato."""
    snippet = TAB_SEZIONI_SNIPPET.replace('__SEZIONI__', json.dumps([list(s) for s in SEZIONI_REPORT]))
    if '</body>' in html_report:
        return html_report.replace('</body>', snippet + '</body>')
    return html_report + snippet


# --- Spunta "formazione gia' schierata" (31/07, richiesta esplicita utente:
# "un quadratino che se cliccato si illumina, lo flaggo io dopo che schiero
# manualmente su Sorare cosi' me lo ricordo") -------------------------------
#
# Iniettata IN CODA al report gia' costruito, non dentro render_lineup_html:
# quel template e' condiviso (produzione + Best Five) e non va toccato per una
# funzione che serve solo qui.
#
# La spunta si RICORDA fra le riaperture della stessa pagina: lo stato sta in
# localStorage, con chiave derivata dal nome del file del report + il titolo
# della formazione. Cosi' report diversi non si sovrascrivono a vicenda, e
# riaprendo lo stesso file le formazioni gia' schierate risultano ancora
# spuntate. Nota: localStorage e' per-browser e per-origine, quindi la spunta
# NON segue il file se lo apri da un altro dispositivo -- e' un promemoria
# personale, non un dato condiviso.
FLAG_SCHIERATE_SNIPPET = r"""
<style>
  .schierata-flag {
    display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
    user-select: none; margin-left: 14px; vertical-align: middle;
    font-size: 0.92rem; font-weight: 700; letter-spacing: 0.02em;
    color: var(--text); opacity: 0.8;
    transition: opacity 0.15s ease;
  }
  .schierata-flag:hover { opacity: 1; }
  .schierata-box {
    width: 22px; height: 22px; border-radius: 6px; flex: 0 0 auto;
    border: 2px solid var(--gold); background: transparent;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 1rem; line-height: 1; color: transparent; font-weight: 800;
    transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .schierata-flag[data-on="1"] { opacity: 1; }
  .schierata-flag[data-on="1"] .schierata-box {
    background: #2fbf6a; border-color: #2fbf6a; color: #06240f;
    box-shadow: 0 0 0 4px rgba(47, 191, 106, 0.28);
  }
  .lineup-block[data-schierata="1"] { outline: 2px solid #2fbf6a; outline-offset: 3px; }
</style>
<script>
(function () {
  var CHIAVE = 'sorare_schierate::' + (location.pathname.split('/').pop() || 'report');
  var stato = {};
  try { stato = JSON.parse(localStorage.getItem(CHIAVE) || '{}'); } catch (e) { stato = {}; }

  function salva() {
    try { localStorage.setItem(CHIAVE, JSON.stringify(stato)); } catch (e) {}
  }

  document.querySelectorAll('.lineup-block').forEach(function (block, i) {
    var titolo = block.querySelector('.lineup-title');
    if (!titolo) return;
    var id = (titolo.textContent || '').trim().replace(/\s+/g, ' ') || ('formazione-' + i);

    var flag = document.createElement('span');
    flag.className = 'schierata-flag';
    flag.title = 'Segna questa formazione come gia schierata su Sorare';
    var box = document.createElement('span');
    box.className = 'schierata-box';
    box.textContent = '✓';
    var testo = document.createElement('span');
    testo.textContent = 'Formazione gia schierata';
    flag.appendChild(box);
    flag.appendChild(testo);

    function applica() {
      var on = stato[id] ? '1' : '0';
      flag.setAttribute('data-on', on);
      block.setAttribute('data-schierata', on);
    }
    flag.addEventListener('click', function (ev) {
      ev.stopPropagation();
      stato[id] = !stato[id];
      if (!stato[id]) { delete stato[id]; }
      salva();
      applica();
    });
    applica();
    titolo.appendChild(flag);
  });
})();
</script>
"""


def aggiungi_flag_schierate(html_report):
    """Aggiunge a ogni formazione una spunta cliccabile "gia' schierata", con
    memoria in localStorage -- vedi il commento sopra."""
    if '</body>' in html_report:
        return html_report.replace('</body>', FLAG_SCHIERATE_SNIPPET + '</body>')
    return html_report + FLAG_SCHIERATE_SNIPPET


def main():
    in_season_req = parse_league_qty(os.environ.get('IN_SEASON', 'mls:1,kleague:1'), 'in_season')
    arena_dedicata_req = parse_league_qty(os.environ.get('ARENA_DEDICATA', ''), 'arena_dedicata',
                                          valid_leagues=ARENA_LEAGUES)
    arena_allstars_260 = _read_int_env('ARENA_ALLSTARS_260', 0)
    arena_allstars_220 = _read_int_env('ARENA_ALLSTARS_220', 0)
    arena_allstars_uncapped = _read_int_env('ARENA_ALLSTARS_UNCAPPED', 0)
    allstars_qty = _read_int_env('ALLSTARS', 0)
    allstars_u23_qty = _read_int_env('ALLSTARS_U23', 0)

    counts = {
        'MLS_IN_SEASON': in_season_req['mls'], 'KLEAGUE_IN_SEASON': in_season_req['kleague'],
        'ARENA_ALLSTARS_260': arena_allstars_260, 'ARENA_ALLSTARS_220': arena_allstars_220,
        'ARENA_ALLSTARS_UNCAPPED': arena_allstars_uncapped, 'ALLSTARS': allstars_qty,
        'ALLSTARS_U23': allstars_u23_qty,
    }
    counts.update({arena_type(lg): arena_dedicata_req.get(lg, 0) for lg in ARENA_LEAGUES})

    # Clamp ai cap duri (30/07, richiesta esplicita utente): richiederne di
    # piu' di quante se ne possano schierare su Sorare spreca solo il pool
    # condiviso senza alcun beneficio.
    for _tipo, _cap in HARD_CAP_BY_TYPE.items():
        if counts.get(_tipo, 0) > _cap:
            print(f"NOTA: {LABELS[_tipo]} richieste {counts[_tipo]}, limitate al cap {_cap} (non schierabili di piu').")
            counts[_tipo] = _cap
    for _tipo in list(counts):
        if _is_arena_type(_tipo) and counts[_tipo] > ARENA_OPTIONAL_CAP:
            print(f"NOTA: {LABELS[_tipo]} richieste {counts[_tipo]}, limitate al tetto pratico {ARENA_OPTIONAL_CAP}.")
            counts[_tipo] = ARENA_OPTIONAL_CAP

    num_totale = sum(counts.values())
    richiesti = [t for t in PRIORITY_ORDER if counts.get(t)]

    # Leghe RILEVANTI per questa run (29/07, richiesta esplicita utente: il
    # blocco "esclusi" pescava candidati da leghe mai coinvolte nelle
    # formazioni richieste -- es. una run mls:6 mostrava esclusi di Spagna/
    # Francia solo perche' quei giocatori avevano un punteggio alto in
    # assoluto, dato inutile per capire chi resta fuori dal pool MLS). Se
    # All Stars/Arena All Stars sono richieste (pescano dal pool misto di
    # TUTTE le leghe), restano rilevanti tutte le LEAGUES; altrimenti solo le
    # leghe con almeno una formazione In Season o Arena dedicata richiesta.
    if allstars_qty or allstars_u23_qty or arena_allstars_260 or arena_allstars_220 or arena_allstars_uncapped:
        leghe_rilevanti = set(LEAGUES)
    else:
        leghe_rilevanti = ({lg for lg, n in in_season_req.items() if n} |
                           {lg for lg, n in arena_dedicata_req.items() if n})
        leghe_rilevanti &= set(LEAGUES)

    print(f"Formazioni richieste: totale={num_totale} -> " +
          (", ".join(f"{LABELS[t]}={counts[t]}" for t in richiesti) if richiesti else "nessuna"))

    role_data, role_counts, player_names = load_league_role_data()

    # Flag u23Eligible per slug (28/07): estratto da role_counts, gia'
    # caricato da player_card_counts.json (stesso file che porta L10) --
    # nessuna query o file in piu'. Serve solo se ALLSTARS_U23 e' richiesta.
    global U23_ELIGIBLE
    for lg in LEAGUES:
        for role in ROLES:
            for slug, entry in role_counts.get(lg, {}).get(role, {}).items():
                if entry.get('u23'):
                    U23_ELIGIBLE[slug] = True

    # Esclusione manuale per slug (28/07, richiesta esplicita utente: carte
    # gia' bloccate in un'Arena confermata di questa giornata -- lockedForLeaderboard
    # resta false anche su lineup confermate, vedi sez. E del RIASSUNTO, quindi
    # l'unico modo affidabile e' passare gli slug a mano da qui). Formato:
    # EXCLUDE_SLUGS='slug-uno,slug-due'. Vuoto di default, nessun effetto.
    exclude_slugs = {s.strip() for s in os.environ.get('EXCLUDE_SLUGS', '').split(',') if s.strip()}
    if exclude_slugs:
        print(f"\nEsclusi manualmente {len(exclude_slugs)} slug (gia' bloccati altrove): "
              f"{sorted(exclude_slugs)}")
        role_data = {lg: {role: [r for r in role_data[lg][role] if r['slug'] not in exclude_slugs]
                           for role in ROLES} for lg in LEAGUES}

    prima = {r: sum(len(role_data[lg][r]) for lg in LEAGUES) for r in ROLES}
    role_data = filter_by_window(role_data)
    dopo = {r: sum(len(role_data[lg][r]) for lg in LEAGUES) for r in ROLES}
    print("")
    print(f"Finestra giornata: solo partite fra adesso e +{MATCH_WINDOW_DAYS:g} giorni "
          f"(MATCH_WINDOW_DAYS). Candidati " +
          ", ".join(f"{r}: {prima[r]}->{dopo[r]}" for r in ROLES))
    if not any(dopo.values()):
        raise SystemExit("ERRORE: nessun giocatore ha una partita nella finestra richiesta. "
                         "Consigli non aggiornati per questa giornata, oppure allarga "
                         "MATCH_WINDOW_DAYS. Nessuna formazione generata.")

    for league in DEDICATED_LEAGUES:
        if not all(role_data.get(league, {}).get(r) for r in ROLES):
            print(f"\nATTENZIONE: la lega '{league}' ha almeno un ruolo senza consiglio disponibile "
                  f"-- le formazioni di quella lega/pool misto potrebbero non completarsi.")

    pools = build_quality_pools(role_data)

    # Conteggio carte possedute: unione di TUTTE le leghe (27/07). Gli slug
    # sono globalmente univoci, quindi l'unione non puo' collidere fra leghe.
    merged_counts = {}
    for role in ROLES:
        acc = {}
        for lg in LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged_counts[role] = acc
    card_pool = bff.CardPool(merged_counts, names=player_names)

    run_number = os.environ.get('GITHUB_RUN_NUMBER')

    # FASE 1: genera (e consuma il card_pool) per tutti i tipi, in ordine di
    # priorita'. Nessun HTML ancora -- il rendering avviene dopo, quando si
    # conoscono TUTTE le formazioni (serve per il pannello alternative).
    all_results = []
    for tipo in PRIORITY_ORDER:
        all_results.extend(generate_lineups_for_type(tipo, counts[tipo], role_data, pools, card_pool))

    # FASE 1b: formazioni OPZIONALI extra (30/07, richiesta esplicita
    # utente -- sostituisce il vecchio "sondaggio" che si limitava a CONTARE
    # quante se ne sarebbero potute fare in piu' con una copia del pool
    # scartata: ora le genera davvero, con lo stesso pool REALE gia' consumato
    # dalla FASE 1, cosi' quelle "sicure" restano intonse e le opzionali
    # attingono solo al residuo). SOLO per i tipi gia' richiesti esplicitamente
    # (count>0): nessuna formazione di un tipo mai selezionato in questa run.
    # In Season/Under23/All Stars: estende fino al cap duro (6/4). Le Arene
    # (dedicate + All Stars a cap): round-robin fra tutte quelle richieste,
    # una alla volta per tipo, cosi' il pool residuo non si esaurisce tutto
    # sul primo tipo in lista prima di toccare gli altri -- fino al tetto di
    # ARENA_OPTIONAL_CAP o a esaurimento pool per quel tipo.
    extra_results = []
    for tipo, cap in HARD_CAP_BY_TYPE.items():
        n_primary = counts.get(tipo, 0)
        if n_primary <= 0 or n_primary >= cap:
            continue
        batch = generate_lineups_for_type(tipo, cap - n_primary, role_data, pools, card_pool)
        for i, r in enumerate(batch):
            if 'error' in r:
                break
            r['idx'] = n_primary + i + 1
            r['extra'] = True
            extra_results.append(r)

    arena_types_requested = [t for t in PRIORITY_ORDER if counts.get(t, 0) > 0 and _is_arena_type(t)]
    arena_progress = {t: counts.get(t, 0) for t in arena_types_requested}
    active = set(arena_types_requested)
    while active:
        made_progress = False
        for tipo in list(active):
            if arena_progress[tipo] >= ARENA_OPTIONAL_CAP:
                active.discard(tipo)
                continue
            batch = generate_lineups_for_type(tipo, 1, role_data, pools, card_pool)
            if not batch or 'error' in batch[0]:
                active.discard(tipo)
                continue
            arena_progress[tipo] += 1
            r = batch[0]
            r['idx'] = arena_progress[tipo]
            r['extra'] = True
            extra_results.append(r)
            made_progress = True
        if not made_progress:
            break

    n_extra = len(extra_results)
    if n_extra:
        print(f"\nFormazioni OPZIONALI extra generate con il pool residuo: {n_extra} "
              "(" + ", ".join(f"{LABELS[t]}={sum(1 for r in extra_results if r['tipo'] == t)}"
                               for t in PRIORITY_ORDER
                               if any(r['tipo'] == t for r in extra_results)) + ")")
    all_results.extend(extra_results)

    generated_by_type = {t: 0 for t in PRIORITY_ORDER}
    grand_total = 0
    for r in all_results:
        if 'error' not in r:
            generated_by_type[r['tipo']] += 1
            grand_total += sum(row['atteso'] for _, row, _ in r['formazione'])

    total_generated = sum(generated_by_type.values())
    print(f"\nFormazioni generate: {total_generated}/{num_totale}")
    if total_generated > 1:
        print(f"TOTALE COMPLESSIVO: {grand_total} pt")

    _stampa_verdetto_arene(all_results)

    # FASE 2: rendering (28/07: pannello alternative/drag&drop RIMOSSO su
    # richiesta esplicita utente -- non serviva piu', bastano le formazioni).
    lineup_html_blocks = []
    _extra_divider_done = False
    for r in all_results:
        if 'error' in r:
            lineup_html_blocks.append(f'<p class="error-block">{r["error"]}</p>')
            continue
        # apply_xp_bonus=False (30/07, richiesta esplicita utente, relay dalla
        # sessione "Best Five K League"): il report HTML mostra sempre lo
        # score_atteso GREZZO (senza bonus XP/collezione/stagione), per poter
        # confrontare i valori 1:1 con i prediction_*.txt sorgente e con altri
        # tool (es. Best Five) senza dover fare a mente il calcolo inverso.
        # SOLO cosmetico: la SELEZIONE di chi entra in formazione continua a
        # usare gli score con XP bonus dove previsto (righe 520-530 sopra,
        # invariate) -- cambia solo il numero mostrato sulla card, non chi
        # viene scelto.
        lineup_html = bff.render_lineup_html(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'], apply_xp_bonus=False)
        _et, _col = _etichetta_arena(r['tipo'], _atteso_con_capitano(r))
        if _et:
            lineup_html += (f'<div style="margin:-6px 0 14px 0;padding:6px 10px;'
                            f'border-left:3px solid {_col};background:rgba(255,255,255,.03);'
                            f'font-size:.85rem;color:{_col}"><b>{_et}</b></div>')
        # Formazioni OPZIONALI (30/07): separatore ben visibile la prima
        # volta che se ne incontra una, poi ogni blocco un po' piu' piccolo
        # (font-size ridotto) per distinguerle a colpo d'occhio da quelle
        # richieste esplicitamente.
        if r.get('extra'):
            if not _extra_divider_done:
                lineup_html_blocks.append(
                    '<div style="margin:28px 0 10px 0;padding-top:18px;'
                    'border-top:2px dashed var(--border)">'
                    '<div style="font-weight:700;font-size:1.05rem;opacity:0.85">'
                    'Formazioni OPZIONALI (extra, con il pool residuo)</div>'
                    '<div style="font-size:0.8rem;opacity:0.65;margin-top:2px">'
                    'Non richieste esplicitamente -- generate in coda se il pool '
                    'lo permetteva, entro i cap per tipo.</div></div>'
                )
                _extra_divider_done = True
            lineup_html = f'<div style="font-size:0.85em;opacity:0.92">{lineup_html}</div>'
        # Sezione di appartenenza (31/07, richiesta esplicita utente: struttura
        # a colonne come in Best Five). Marcata QUI, lato server, dove il tipo
        # e' noto con certezza -- molto piu' solido che farla indovinare al JS
        # dal testo del titolo.
        lineup_html = (f'<div data-sezione="{_sezione_di(r["tipo"], r.get("extra"))}">'
                        f'{lineup_html}</div>')
        lineup_html_blocks.append(lineup_html)

    # Giocatori candidati (idonei per starter-odds + finestra giornata, vedi
    # discovery_fixture.py) MAI schierati in nessuna formazione di questa run
    # (28/07, richiesta esplicita utente): dice a colpo d'occhio quanti
    # rimangono "sul banco" dopo aver consumato il pool sulle formazioni
    # richieste, totale e per ruolo.
    used_slugs = card_pool.used_slugs()
    esclusi_per_ruolo = {}
    for r in ROLES:
        candidati = {row['slug'] for lg in LEAGUES for row in role_data[lg][r]}
        esclusi_per_ruolo[r] = len(candidati - used_slugs)
    tot_esclusi = sum(esclusi_per_ruolo.values())
    print(f"Candidati non schierati in nessuna formazione: {tot_esclusi} "
          f"(" + ", ".join(f"{r}:{esclusi_per_ruolo[r]}" for r in ROLES) + ")")

    # Elenco dettagliato (28/07, richiesta esplicita utente SOLO per questa
    # run di verifica post-rimozione filtro qualita': vedere per nome quali
    # candidati eleggibili restano fuori, per capire se recuperabili). Dietro
    # env var, non stampato di default nelle run normali.
    if os.environ.get('LIST_UNUSED_CANDIDATES', '').strip() not in ('', '0', 'false', 'no'):
        print("\nCandidati eleggibili MAI schierati (nome, lega, ruolo, punteggio atteso):")
        for r in ROLES:
            righe = [(lg, row) for lg in LEAGUES for row in role_data[lg][r]
                     if row['slug'] not in used_slugs]
            righe.sort(key=lambda lr: lr[1].get('atteso', 0), reverse=True)
            for lg, row in righe:
                nome = player_names.get(row['slug'], row['slug'])
                print(f"  [{r}] {nome} ({lg}) -- atteso {row.get('atteso')}")

    # Top 40 esclusi per punteggio atteso (29/07, richiesta esplicita utente:
    # sempre presente nel report HTML, non solo su richiesta via env var come
    # il blocco sopra) -- controllo rapido "chi resta fuori nonostante un
    # punteggio alto", utile per verificare se il pool di candidati e' capiente
    # o se manca qualcosa (es. lega esclusa, filtro troppo aggressivo).
    # Filtrato a leghe_rilevanti (29/07, bug segnalato dall'utente: con
    # ONLY_LEAGUES/in_season limitato a una sola lega, l'elenco pescava
    # comunque candidati di leghe MAI coinvolte in nessuna formazione
    # richiesta -- dato inutile per capire chi resta fuori dal pool giusto).
    # Posizionato accanto alla PRIMA formazione (29/07, richiesta esplicita
    # utente: prima in fondo pagina, poi provato fisso in overlay -- alla
    # fine preferito affiancato alla formazione #1, riusando le classi
    # .lineup-row/.alt-panel gia' presenti nel CSS del template, dismesse dal
    # pannello alternative del 28/07 ma mai rimosse dallo stylesheet).
    # Pannello per-LEGA (29/07, bug segnalato dall'utente: un'unica lista
    # combinata affiancata solo alla primissima formazione mischiava
    # gli esclusi di leghe diverse, es. esclusi Korea mostrati accanto a
    # una formazione MLS). Ora un pannello per ciascuna lega "dedicata"
    # (mls, kleague, o altra lega Arena dedicata), affiancato alla PRIMA
    # formazione DI QUELLA LEGA (usando POOL_LEAGUE_BY_TYPE[tipo] per capire
    # a quale lega appartiene ogni blocco). Le formazioni "mixed"/"mixed_u23"
    # (All Stars, pool multi-lega) restano escluse dal pannello per-lega:
    # non hanno una lega singola a cui affiancare un elenco coerente.
    def _build_top_esclusi(leghe):
        tutti = [(lg, r, row) for r in ROLES for lg in leghe for row in role_data[lg][r]
                 if row['slug'] not in used_slugs]
        tutti.sort(key=lambda t: t[2].get('atteso', 0), reverse=True)
        return tutti[:40]

    def _riga_esclusa(i, lg, r, row):
        # Niente coefficiente forza avversario in colonna (29/07, bug reale:
        # 'domesticLeagueRanking' e' un attributo CORRENTE della squadra,
        # non un valore storico legato alla partita -- vedi commento su
        # _team_vs_opponent_html in build_formazione_finale.py). Solo
        # squadra vs avversario, dato accurato (viene dalla partita vera).
        squadra = bff._short_team(row.get('team_slug'))
        avversario = bff._short_team(row.get('opponent_team_slug'))
        vs = f'{squadra} vs {avversario}' if row.get('team_slug') else 'N/D'
        # punteggio spostato SUBITO dopo il numero, a sinistra del nome
        # (29/07, bug segnalato dall'utente: prima era in fondo a destra
        # e la colonna nome veniva tagliata con ellissi). Nome ora senza
        # limite di larghezza (va a capo se serve invece di troncare),
        # "vs" resta l'unica colonna che tronca (meno critica).
        return (
            f'<tr><td style="padding:2px 6px 2px 0;color:var(--muted)">{i+1}.</td>'
            f'<td style="padding:2px 8px 2px 0;font-weight:700;white-space:nowrap">{row.get("atteso")} pt</td>'
            f'<td style="padding:2px 6px 2px 0;white-space:normal">{player_names.get(row["slug"], row["slug"])}</td>'
            f'<td style="padding:2px 6px 2px 0;color:var(--muted)">{r}</td>'
            f'<td style="padding:2px 0;color:var(--text);opacity:0.85;font-size:0.78rem;'
            f'max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
            f'title="{vs}">{vs}</td></tr>'
        )

    def _panel_html(top_esclusi):
        righe_html = "".join(
            _riga_esclusa(i, lg, r, row) for i, (lg, r, row) in enumerate(top_esclusi)
        )
        return (
            '<div style="position:absolute;top:0;right:0;width:380px;max-height:480px;'
            'overflow-y:auto;background:var(--surface);border:1px solid var(--border);'
            'border-radius:12px;padding:12px 14px;box-shadow:0 4px 16px rgba(0,0,0,0.25)">'
            '<div class="alt-panel-title">'
            f'Top {len(top_esclusi)} esclusi<br>per punteggio atteso</div>'
            '<div style="font-size:0.78rem"><table style="border-collapse:collapse;width:100%;table-layout:fixed">'
            f'{righe_html}</table></div></div>'
        )

    def _attach_panel(idx, top_esclusi):
        # Pannello NON piu' dentro il flex-row della formazione (29/07, bug
        # reale segnalato dall'utente: essendo molto piu' alto di una singola
        # formazione, il vecchio .lineup-row (flex, altezza = child piu' alto)
        # spingeva la formazione successiva in basso, creando un vuoto enorme).
        # Ora e' posizionato fuori flusso (position:absolute) rispetto a un
        # wrapper relative attorno a quella singola formazione.
        lineup_html_blocks[idx] = (
            '<div style="position:relative;padding-right:400px">'
            f'{lineup_html_blocks[idx]}{_panel_html(top_esclusi)}</div>'
        )

    # Un pannello per ciascuna lega "dedicata" (mls, kleague, altre Arena
    # dedicate), affiancato alla PRIMA formazione DI QUELLA LEGA (29/07, bug
    # segnalato dall'utente: prima un'unica lista combinata finiva solo
    # accanto alla primissima formazione in assoluto, mischiando leghe
    # diverse -- es. esclusi Korea mostrati accanto alla prima formazione
    # MLS). Le formazioni 'mixed'/'mixed_u23' (All Stars, pool multi-lega)
    # prendono invece un pannello combinato su TUTTE le leghe rilevanti,
    # affiancato alla prima formazione mixed incontrata.
    leghe_gia_fatte = set()
    mixed_fatto = False
    for idx, r in enumerate(all_results):
        if 'error' in r:
            continue
        pool_league = POOL_LEAGUE_BY_TYPE.get(r['tipo'])
        if pool_league in ('mixed', 'mixed_u23'):
            if not mixed_fatto:
                top_esclusi_mixed = _build_top_esclusi(leghe_rilevanti)
                if top_esclusi_mixed:
                    _attach_panel(idx, top_esclusi_mixed)
                mixed_fatto = True
        elif pool_league and pool_league not in leghe_gia_fatte:
            leghe_gia_fatte.add(pool_league)
            if pool_league in leghe_rilevanti:
                top_esclusi_lg = _build_top_esclusi({pool_league})
                if top_esclusi_lg:
                    _attach_panel(idx, top_esclusi_lg)

    # Riepilogo formazioni OPZIONALI (30/07, sostituisce il vecchio
    # "sondaggio" che rigenerava su una COPIA del pool solo per CONTARE
    # quante se ne sarebbero potute fare in piu' -- ora extra_results
    # (FASE 1b sopra) le ha gia' generate DAVVERO col pool reale, quindi qui
    # basta riassumere cosa e' stato fatto, nessuna rigenerazione).
    extra_by_type = {}
    for r in extra_results:
        extra_by_type[r['tipo']] = extra_by_type.get(r['tipo'], 0) + 1

    capienza_html = ""
    if extra_by_type:
        righe = []
        for tipo in PRIORITY_ORDER:
            if tipo not in extra_by_type:
                continue
            richieste = counts.get(tipo, 0)
            righe.append(
                f'<tr><td style="padding:3px 14px 3px 0">{LABELS[tipo]}</td>'
                f'<td style="padding:3px 14px 3px 0;white-space:nowrap">'
                f'{richieste} richieste</td>'
                f'<td style="padding:3px 0;white-space:nowrap">'
                f'<span style="font-weight:700">+{extra_by_type[tipo]} opzionali generate</span></td></tr>'
            )
        capienza_html = (
            '<div class="alt-panel" style="margin:0 0 18px 0">'
            '<div style="font-weight:700;margin-bottom:6px">'
            'Formazioni opzionali extra generate con il pool residuo (vedi in fondo al report)</div>'
            '<table style="border-collapse:collapse;font-size:0.86rem">'
            + "".join(righe) +
            '</table></div>'
        )

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    run_suffix = f"_run{run_number}" if run_number else ""
    page_title = f"Generatore Formazioni{' — run #' + run_number if run_number else ''}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"totale={num_totale} (" +
                     ", ".join(f"{LABELS[t]}={counts[t]}" for t in PRIORITY_ORDER) + ")<br>"
                     f"Candidati non schierati in nessuna formazione: {tot_esclusi} (" +
                     ", ".join(f"{r}: {esclusi_per_ruolo[r]}" for r in ROLES) + ")")
    footer_html = (f"Fusione {len(LEAGUES)} campionati. Max 1 carta CLASSIC solo per In Season. "
                    f"Filtro qualita' L5/L10/L40 disattivato (28/07): ridondante con lo starter-odds.")
    verdetto_html = _verdetto_arene_html(all_results)
    if verdetto_html:
        lineup_html_blocks.insert(0, verdetto_html)
    if capienza_html:
        lineup_html_blocks.insert(0, capienza_html)
    html_text = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_text = aggiungi_flag_schierate(html_text)
    html_text = aggiungi_tab_sezioni(html_text)
    html_path = os.path.join(OUTPUT_DIR, f'generatore_formazioni{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"\nReport visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
