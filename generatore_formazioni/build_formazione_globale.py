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
import math
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
# Arene dedicate per lega DISATTIVATE DI DEFAULT (04/08, richiesta esplicita
# utente): il bot le generava come piu' efficienti in base al punteggio
# atteso, ma senza sapere se in quella giornata sono davvero schierabili
# (es. In Season non attivo quella GW). L'utente le sostituisce comunque a
# mano con Arena All Stars 260, quindi il tentativo era solo overhead.
#
# Riattivabili di volta in volta con ARENA_LEAGUES_ENABLED (comma-separated,
# es. 'mls,kleague' o 'tutte' per tutte le leghe sotto): quando valorizzata,
# il bot torna a provare a generarle rispettando comunque il vincolo di
# efficienza esistente (PRIORITY_ORDER + confronto atteso/pareggio piu'
# sotto decidono se schierarle davvero). Default vuoto = tuple vuota, tutto
# il codice a valle (FORMATION_SHAPES/PRIORITY_ORDER/ecc, tutti derivati da
# questa costante) si disattiva da solo, nessun'altra modifica necessaria.
_ARENA_LEAGUES_ALL = (
    'mls', 'kleague', 'belgio', 'olanda', 'turchia', 'portogallo', 'spagna',
    'germania', 'francia', 'croazia', 'scozia',
)
_arena_leagues_enabled = {s.strip() for s in os.environ.get('ARENA_LEAGUES_ENABLED', '').split(',') if s.strip()}
if _arena_leagues_enabled == {'tutte'}:
    _arena_leagues_enabled = set(_ARENA_LEAGUES_ALL)
ARENA_LEAGUES = tuple(lg for lg in _ARENA_LEAGUES_ALL if lg in _arena_leagues_enabled and lg in _DISCOVERED)

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
    # Tipo NUOVO 09/08/2026 (BRIEF_SONNET_APPLICA_SOGLIE_2026-08-09.txt §3):
    # identica alla cap 260 (shape/pool/regole), cambia solo costo (100) e
    # premi (inferiori), vedi COSTO_INGRESSO/PAREGGIO_ARENA/GUADAGNO_PER_PUNTO.
    'ARENA_ALLSTARS_BEGINNER': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
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
    'ARENA_ALLSTARS_UNCAPPED': 'Arena All Stars (uncapped)', 'ARENA_ALLSTARS_BEGINNER': 'Arena All Stars (Beginner)',
    'ALLSTARS': 'All Stars',
    'ALLSTARS_U23': 'All Stars Under 23',
}
LABELS.update({arena_type(lg): f'Arena {ARENA_LEAGUE_LABELS.get(lg, lg)} (cap 260)'
               for lg in ARENA_LEAGUES})

L10_CAP_BY_TYPE = {
    'ARENA_ALLSTARS_260': 260.0, 'ARENA_ALLSTARS_220': 220.0,  # ARENA_ALLSTARS_UNCAPPED: nessuna chiave = None
    'ARENA_ALLSTARS_BEGINNER': 260.0,  # identica alla cap 260 (09/08)
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
                        'ARENA_ALLSTARS_UNCAPPED', 'ARENA_ALLSTARS_BEGINNER',
                        'ALLSTARS', 'ALLSTARS_U23'}
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
    'ARENA_ALLSTARS_BEGINNER': 0.2,
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
# Ordine di priorita' (02/08, spostato dall'utente): le Under 23 stavano
# davanti alle arene, ma le arene rendono essenze misurabili mentre le Under 23
# sono gratuite e difficili da vincere. Ora:
#   In Season  ->  arene (dedicate, poi All Stars)  ->  Under 23  ->  All Stars
PRIORITY_ORDER = (
    ['MLS_IN_SEASON', 'KLEAGUE_IN_SEASON']
    + [arena_type(lg) for lg in ARENA_LEAGUES]
    + ['ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED', 'ARENA_ALLSTARS_BEGINNER']
    + ['ALLSTARS_U23', 'ALLSTARS']
)

POOL_LEAGUE_BY_TYPE = {
    'MLS_IN_SEASON': 'mls', 'KLEAGUE_IN_SEASON': 'kleague',
    'ARENA_ALLSTARS_260': 'mixed', 'ARENA_ALLSTARS_220': 'mixed', 'ARENA_ALLSTARS_UNCAPPED': 'mixed',
    'ARENA_ALLSTARS_BEGINNER': 'mixed',
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
    return tipo in ('ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED', 'ARENA_ALLSTARS_BEGINNER') \
        or tipo in {arena_type(lg) for lg in ARENA_LEAGUES}


# --- CALIBRAZIONE DELLA PREVISIONE (02/08) ------------------------------
# Misurato su 69.151 coppie previsione/realizzato, walk-forward, sull'intero
# storico in cache: il modello ESAGERA gli scarti.
#
#     realizzato = 10.21 + 0.767 x previsto
#
# Proiezione 60 -> valore realistico 56.2; proiezione 40 -> 40.9. Il punto di
# equilibrio e' a 44: sotto il modello sottostima, sopra sovrastima.
#
# Si applica QUI, all'ingresso, cosi' da avere una scala sola in tutto il
# sistema. Conseguenze, tutte gia' recepite:
#   - le soglie d'arena tornano al pareggio VERO (264.4 per la cap 260) invece
#     che al suo equivalente in previsione grezza (274.1): applicare la
#     calibrazione E tenere 274.1 sarebbe una doppia correzione (trappola
#     notata dall'utente)
#   - i bonus di sinergia erano gia' calcolati in punti REALI, quindi ora sono
#     nella scala giusta senza toccarli
#   - i punteggi mostrati nel report diventano onesti: prima una formazione
#     data a 290 ne realizzava tipicamente 276
CALIB_A = float(os.environ.get('CALIB_A', '10.76'))
CALIB_B = float(os.environ.get('CALIB_B', '0.757'))

# --- UNA RETTA PER RUOLO (03/08) ---------------------------------------
# La calibrazione unica sopra e' affine e monotona, quindi dentro un ruolo non
# cambia niente: l'ordine dei candidati resta identico. Cambia pero' i
# confronti FRA ruoli, che e' esattamente cio' che fa il generatore quando
# riempie 1 slot di portiere e 4 di movimento pescando da leghe diverse.
#
# Misurato sulle 74.515 coppie previsione/realizzato di
# dati_globali/taratura_coppie.json (walk-forward su tutto lo storico in cache,
# punteggi grezzi senza alcun bonus), rigenerate il 03/08 col modello corretto
# E con i parametri ritarati. E' la stessa fonte da cui veniva la retta unica
# in produzione, quindi i due numeri sono confrontabili: la retta non e' la
# stessa per tutti.
#
#     ruolo            n      a       b    prev. 60 -> reale   sd residua
#     Goalkeeper    6019   35.78   0.264         51.6           19.23
#     Defender     25437    7.28   0.831         57.1           18.51
#     Midfielder   24067   11.61   0.740         56.0           16.20
#     Forward      18992    8.40   0.789         55.7           16.83
#     (unica)      74515   10.76   0.757         56.2  per tutti
#
# LA PENDENZA DEL PORTIERE (0.264) NON E' UN ERRORE, ed e' il numero piu'
# importante di questa tabella. La previsione del portiere e' quasi scorrelata
# dal realizzato (r = 0.034 su 6.019 casi) e varia pochissimo (dev.std. 2.5
# punti contro i 19.2 del realizzato): il modello, sui portieri, non distingue.
# La calibrazione lo dice a voce alta, schiacciando ogni portiere verso ~52
# punti. La conseguenza operativa e' giusta: se il portiere non e' prevedibile,
# nella cap 260 conviene metterci quello che consuma meno budget L10, non
# quello con la previsione piu' alta.
#
# Tre punti di scarto fra portiere e attaccante che la retta unica appiattisce.
# Dentro un ruolo la calibrazione non cambia niente (e' affine e monotona), ma
# in una formazione da cinque quello scarto e' un errore sistematico di
# allocazione fra lo slot del portiere e i quattro di movimento.
#
# Verificato che le due strade portano allo stesso posto: sommando cinque
# giocatori calibrati per ruolo (col capitano) su 40.000 formazioni sintetiche
# si ottiene una media di 260.4 contro i 262.3 realizzati, bias +1.9 e
# dispersione dell'errore 42.70 -- gli stessi numeri della vecchia retta unica.
# Cambia la ripartizione fra i ruoli, non la scala: quindi le soglie d'arena,
# che vivono nella scala del realizzato, restano confrontabili coi totali.
CALIB_PER_RUOLO = {
    'GK':  (float(os.environ.get('CALIB_A_GK', '35.78')), float(os.environ.get('CALIB_B_GK', '0.264'))),
    'DEF': (float(os.environ.get('CALIB_A_DEF', '7.28')), float(os.environ.get('CALIB_B_DEF', '0.831'))),
    'MID': (float(os.environ.get('CALIB_A_MID', '11.61')), float(os.environ.get('CALIB_B_MID', '0.740'))),
    'FWD': (float(os.environ.get('CALIB_A_FWD', '8.40')), float(os.environ.get('CALIB_B_FWD', '0.789'))),
}


def calibra(valore, ruolo=None):
    if valore is None:
        return None
    a, b = CALIB_PER_RUOLO.get(ruolo, (CALIB_A, CALIB_B))
    # arrotondato a un decimale: la calibrazione moltiplica per ~0.7 e
    # altrimenti i punteggi escono con dodici cifre decimali nei log
    return round(a + b * valore, 1)


def calibra_riga(row, ruolo=None):
    """Porta previsione e intervallo sulla scala del punteggio realizzato."""
    for chiave in ('atteso', 'low', 'high', 'ordinamento', 'sort_score'):
        if row.get(chiave) is not None:
            row[chiave] = calibra(row[chiave], ruolo)
    return row


# --- TEST ISOLATO GRADE (G), branch test-grade-g-gw3 (07/08/2026) ---------
# Formula da analisi_manager/p12_backtest_formazione_grade.py (VERIFICATA,
# non reinventata): atteso_combinato = atteso_calibrato + sd_gruppo * z_grade,
# per gruppo (lega, ruolo) -- qui il gruppo coincide con role_data[lega][ruolo]
# gia' costruito in load_league_role_data, nessuna nuova aggregazione.
# Spento = scelta scritta (GRADE_ENABLED, default '1' -- G IN PRODUZIONE dal
# 07/08/2026, catena validata: A/A passato, SIGMA/soglie/scouting invariati,
# backtest ampio a copertura piena (crowss 77.4%, manager 100%) con segno
# positivo su entrambi i campioni, anche se gli IC non escludono zero --
# vedi docs/handoff/BRIEF_SONNET_CATENA_G_2026-08-07.txt esito 2), mai
# assenza del dato: a GRADE_ENABLED=0 'atteso'/'sort_score' non vengono MAI
# toccati (rollback rapido se serve, senza rimuovere il codice).
GRADE_ENABLED = os.environ.get('GRADE_ENABLED', '1') == '1'
GRADE_DATA_PATH = os.environ.get('GRADE_DATA_PATH', '')
GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
_GRADE_MAP = {}
if GRADE_DATA_PATH and os.path.exists(GRADE_DATA_PATH):
    with open(GRADE_DATA_PATH, encoding='utf-8') as _f:
        _GRADE_MAP = json.load(_f)

# --- GRADE_SCALE ("scala storica"), brief BRIEF_SONNET_GRADE_SCALA_STORICA_
# 2026-08-08.txt -- MISURA, non ancora una scelta di produzione. Default
# INVARIATO ('gruppo' = comportamento di sempre: media/sd del grade DENTRO
# il gruppo (lega,ruolo) della singola giornata). 'storica' sostituisce SOLO
# media/sd del grade con quelle di analisi_manager/p18_grade_scala_storica.py
# (calcolate sullo storico multi-giornata per lega/ruolo, con fallback
# ruolo/globale) -- la dispersione degli ATTESI (sd sopra, riga poco sotto)
# resta sempre quella del gruppo corrente, come in produzione: cambia solo la
# scala con cui si legge il grade, non la conversione in punti.
# Spento con un flag esplicito, mai con l'assenza del file (se il file manca
# con GRADE_SCALE=storica, si stampa un avviso e si ricade su 'gruppo' --
# mai in silenzio).
GRADE_SCALE = os.environ.get('GRADE_SCALE', 'gruppo')
GRADE_SCALE_DATA_PATH = os.environ.get(
    'GRADE_SCALE_DATA_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dati', 'grade_scala_storica.json'))
_GRADE_SCALE_TABLE = None
if GRADE_SCALE == 'storica':
    if os.path.exists(GRADE_SCALE_DATA_PATH):
        with open(GRADE_SCALE_DATA_PATH, encoding='utf-8') as _f:
            _GRADE_SCALE_TABLE = json.load(_f)
    else:
        print(f"ATTENZIONE: GRADE_SCALE=storica ma {GRADE_SCALE_DATA_PATH} non esiste "
              "-- fallback su 'gruppo' (nessuna scala storica applicata).")
        GRADE_SCALE = 'gruppo'


def _scala_storica_per(league, role):
    """(mean, sd, livello) dalla tabella storica per (league,role), con
    fallback lega+ruolo -> solo ruolo -> globale. None se la tabella non
    c'e' o non ha nessun livello disponibile."""
    if not _GRADE_SCALE_TABLE:
        return None
    voce = _GRADE_SCALE_TABLE.get('per_lega_ruolo', {}).get(f'{league}|{role}')
    if voce:
        return voce['mean'], voce['sd'], 'lega_ruolo'
    voce = _GRADE_SCALE_TABLE.get('per_ruolo', {}).get(role)
    if voce:
        return voce['mean'], voce['sd'], 'ruolo'
    voce = _GRADE_SCALE_TABLE.get('globale')
    if voce:
        return voce['mean'], voce['sd'], 'globale'
    return None


# --- GRADE_GROUP_STORICA_ENABLED (12/08/2026) -- filone "gruppo grade
# esteso alla giornata", priorita' 2. SPENTO DI DEFAULT: Opus ha verificato
# col placebo che il segnale e' vero (p<=0,048, docs/HANDOFF_UNIFICATO_
# MODELLO_SCOUTING.md §8bis-bis "Controllo Opus sulla ricetta finale") ma
# ha detto testualmente "pronta per il fuori campione pre-registrato, NON
# per la produzione diretta" -- quel test (GW5/6/7, chiude 25/08/2026,
# analisi_manager/p57_grade_fuoricampo_preregistrato.py) NON e' ancora
# stato fatto. NON accendere prima di allora.
#
# Sostituisce il "gruppo nativo" (lega,ruolo DENTRO la singola giornata,
# spento per il 51%+ delle righe quando il gruppo ha <2 membri -- il
# difetto che ha aperto questo filone) con due tabelle storiche costruite
# sulla popolazione dei consiglio_*.txt (non l'archivio backtest, biased):
# voto (grade_scala_produzione.json, riusa la stessa _scala_storica_per
# sopra) e sd_atteso (sd_atteso_produzione.json, nuova). Fattore_storico
# 0,482 e ricentraggio PER RUOLO calcolato FRESCO su tutte le leghe di
# QUESTA run (non una costante congelata) -- vedi _recentra_grade_per_ruolo
# sotto, chiamata da load_league_role_data() dopo il doppio ciclo lega/ruolo.
GRADE_GROUP_STORICA_ENABLED = os.environ.get('GRADE_GROUP_STORICA_ENABLED', '0') == '1'
GRADE_FATTORE_STORICO = float(os.environ.get('GRADE_FATTORE_STORICO', '0.482'))
SD_ATTESO_PRODUZIONE_PATH = os.environ.get(
    'SD_ATTESO_PRODUZIONE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dati', 'sd_atteso_produzione.json'))
_SD_ATTESO_TABLE = None
_GRADE_SCALA_PRODUZIONE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'dati', 'grade_scala_produzione.json')
if GRADE_GROUP_STORICA_ENABLED:
    if os.path.exists(SD_ATTESO_PRODUZIONE_PATH) and os.path.exists(_GRADE_SCALA_PRODUZIONE_PATH):
        with open(SD_ATTESO_PRODUZIONE_PATH, encoding='utf-8') as _f:
            _SD_ATTESO_TABLE = json.load(_f)
        with open(_GRADE_SCALA_PRODUZIONE_PATH, encoding='utf-8') as _f:
            _GRADE_SCALE_TABLE = json.load(_f)  # sovrascrive quella di GRADE_SCALE=storica, se caricata sopra
    else:
        print("ATTENZIONE: GRADE_GROUP_STORICA_ENABLED=1 ma le tabelle "
              f"({SD_ATTESO_PRODUZIONE_PATH}, {_GRADE_SCALA_PRODUZIONE_PATH}) non esistono -- "
              "rilanciare generatore_formazioni/dati/aggiorna_grade_scala_produzione.py. "
              "Fallback: GRADE_GROUP_STORICA_ENABLED spento per questa run.")
        GRADE_GROUP_STORICA_ENABLED = False


def _sd_atteso_storico_per(league, role):
    """(sd, livello) dalla tabella sd_atteso di produzione, stesso fallback
    di _scala_storica_per. None se la tabella non c'e'."""
    if not _SD_ATTESO_TABLE:
        return None
    voce = _SD_ATTESO_TABLE.get('per_lega_ruolo', {}).get(f'{league}|{role}')
    if voce:
        return voce['sd'], 'lega_ruolo'
    voce = _SD_ATTESO_TABLE.get('per_ruolo', {}).get(role)
    if voce:
        return voce['sd'], 'ruolo'
    voce = _SD_ATTESO_TABLE.get('globale')
    if voce:
        return voce['sd'], 'globale'
    return None


def _grade_per_riga(row):
    """Fonte del grade per una riga: PRIMA quello letto da
    player_card_counts.json (produzione, scritto da discovery_fixture.py
    dopo il filtro starter-odds -- vedi entry['grade'] in DOC_SONNET_G_IN_
    PRODUZIONE sez.2.A), altrimenti _GRADE_MAP da GRADE_DATA_PATH (percorso
    usato dal test isolato GW3, tenuto per compatibilita' con quei dump)."""
    g = row.get('_grade_from_counts')
    if g:
        return g
    return _GRADE_MAP.get(row['slug'])


def _apply_grade_group(rows):
    """Annota su ogni row _grade/_grade_num/atteso_combinato. Se GRADE_ENABLED
    e' True, sovrascrive anche 'atteso' e 'sort_score' con atteso_combinato
    (cio' che _sort_ordinamento e il knapsack leggono). Se nessuna riga ha
    grade (ne' da counts ne' da _GRADE_MAP), ogni riga ha _grade=None ->
    z_grade=0 -> atteso invariato: fallback esplicito, gia' previsto dalla
    formula."""
    if not rows:
        return

    if GRADE_GROUP_STORICA_ENABLED:
        # Ricetta 12/08/2026 (SPENTA di default, vedi commento sul flag
        # sopra): niente return anticipato per gruppi piccoli -- le due
        # tabelle storiche non dipendono dal gruppetto nativo. Il
        # ricentraggio per ruolo e l'applicazione a 'atteso'/'sort_score'
        # avvengono DOPO, in _recentra_grade_per_ruolo (serve vedere tutte
        # le leghe insieme, qui si vede solo una lega+ruolo alla volta).
        scala = _scala_storica_per(rows[0].get('league'), rows[0].get('role_key'))
        gm, gsd, _liv = scala if scala else (0.0, 0.0, None)
        sd_info = _sd_atteso_storico_per(rows[0].get('league'), rows[0].get('role_key'))
        sd_atteso = sd_info[0] if sd_info else 0.0
        for r in rows:
            g = _grade_per_riga(r)
            gn = GRADE_NUM.get(g) if g else None
            r['_grade'] = g
            r['_grade_num'] = gn
            z = (gn - gm) / gsd if (gn is not None and gsd > 0) else 0.0
            r['atteso_cal'] = r['atteso']
            r['atteso_combinato'] = r['atteso'] + GRADE_FATTORE_STORICO * sd_atteso * z
        return

    vals = [r['atteso'] for r in rows if r.get('atteso') is not None]
    if len(vals) < 2:
        for r in rows:
            r['_grade'] = _grade_per_riga(r)
            r['atteso_cal'] = r.get('atteso')
            r['atteso_combinato'] = r.get('atteso')
        return
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
    grade_members = []
    for r in rows:
        g = _grade_per_riga(r)
        gn = GRADE_NUM.get(g) if g else None
        r['_grade'] = g
        r['_grade_num'] = gn
        if gn is not None:
            grade_members.append(gn)

    scala = _scala_storica_per(rows[0].get('league'), rows[0].get('role_key')) \
        if GRADE_SCALE == 'storica' else None
    if scala is not None:
        gm, gsd, _livello_scala = scala
    elif len(grade_members) >= 2:
        gm = sum(grade_members) / len(grade_members)
        gsd = (sum((v - gm) ** 2 for v in grade_members) / len(grade_members)) ** 0.5
    else:
        gm, gsd = 0.0, 0.0
    for r in rows:
        gn = r.get('_grade_num')
        z = (gn - gm) / gsd if (gn is not None and gsd > 0) else 0.0
        r['atteso_cal'] = r['atteso']
        r['atteso_combinato'] = r['atteso'] + sd * z
        if GRADE_ENABLED:
            r['atteso'] = r['atteso_combinato']
            if r.get('sort_score') is not None:
                r['sort_score'] = r['atteso_combinato']


# --- GK_ATT_AVV: correttivo portiere da "quanto segna di solito l'avversario"
# (11/08/2026, filone clean-sheet/gol veri). L'atteso GK di produzione e'
# quasi piatto (1.932 righe, range 45,5-51,7, sd 0,97 contro sd 18,7 del
# reale): sotto il criterio "dispersione vera correlata al reale" (deciso
# dall'utente, non piu' "batte le quote con margine sicuro") il modello
# attuale sul portiere e' indistinguibile dal cieco. Il segnale misurato --
# gol fatti dall'AVVERSARIO -- correla col punteggio reale del portiere ed
# e' l'UNICO che regge su tenuta out-of-sample (n=716 crowss+altri 2025/26,
# n=1.896 blocco temporale 2024/25 con IC che esclude lo zero, vedi
# docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §11).
# PESATURA (11/08/2026, contestazione dell'utente sulla media storica secca:
# "le squadre ruotano giocatori/allenatori, una media piatta non ha senso").
# Testato su n=881 (correlazione, stesso campione aggregato, §12 del report):
# finestre CORTE (ultime 5-10 partite, taglio netto o decadimento
# esponenziale) fanno PEGGIO della storia intera, in modo monotono --
# half-life lunghe (40-80) pareggiano la secca (+0,105 vs +0,104). MA nel
# BACKTEST VERO (Binario 2, analisi_manager/p24_binario2_ga.py, 337 GW
# aggregate, bootstrap sul delta appaiato) la media secca vince su tutti i
# numeri: +4.413 essenze (half-life +3.900), bootstrap positivo nel 95,9%
# (half-life 91,3%), IC95% [-487;+9.387] (half-life [-1.768;+9.426]).
# DUE FORMULE PRE-REGISTRATE (11/08/2026), scelte PRIMA di vedere i dati
# nuovi (fixture 7-11 agosto, tutti i 29 manager) per non scegliere a
# posteriori su cosa esce meglio -- disciplina esplicita dell'utente, stessa
# di un pre-registration:
#   'secca'  = media storica secca, tutta la storia -- reale = 54,49 -
#              4,26*att_medio (n=2.612, §11 del report). Nel Binario 2 di
#              oggi (337 GW) e' quella andata meglio: +4.413 essenze,
#              bootstrap positivo 95,9%, IC95% [-487;+9.387] (ancora non
#              esclude lo zero).
#   'u10'    = media secca sulle ultime 10 partite (scelta dell'utente,
#              nessun half-life) -- reale = 51,18 - 2,43*att_u10 (n=870,
#              rifit su gk_recency_aggregato_2026-08-13.json).
# (la versione half-life=40 provata in mezzo, +3.900/91,3%/IC piu' larga,
# NON e' una delle due opzioni finali: era solo la prima idea, la secca
# l'ha battuta su tutti i numeri -- vedi commento sopra per il dettaglio).
# Selezione: GK_ATT_AVV_FORMULA ('secca' default, o 'u10').
# La tabella (generatore_formazioni/dati/gk_attacco_avversario.json) tiene
# ENTRAMBI i valori per squadra (att_medio, att_u10), calcolati insieme da
# generatore_formazioni/dati/aggiorna_gk_attacco_avversario.py -- che scarica
# solo le partite NUOVE dalla cache (refresh incrementale, mai congelato) e
# ricalcola entrambe le medie in un colpo solo. Agganciato come step in
# .github/workflows/formazione_giornata.yml prima del generatore, gira ad
# ogni run indipendentemente dal flag (cosi' resta fresca per quando si
# accende).
# Magnitudine onesta: ~1,3-2 punti di dispersione vera catturata, non un
# salto enorme -- ma il modello attuale cattura ZERO, quindi e' un
# miglioramento netto sotto il criterio scelto dall'utente, SE il segnale
# regge sui dati nuovi (in verifica).
# ACCESO IN PRODUZIONE (11/08/2026, formula 'secca'): B2 su 360 GW-manager
# mostra G migliora se stesso di +5.556 essenze (IC95%[+649;+10.638],
# 98,7% positivo, replica esatta dello storico). B1 piatto ma sotto-potenza
# (36 decisioni discordanti, non contro-prova -- verdetto Opus, vedi
# docs/handoff/BRIEF_OPUS_GK_SECCA_PRODUZIONE_2026-08-11.txt e
# RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §14). Ri-misura pre-registrata
# dopo 3 fixture giocate col flag acceso: docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §5.6.
GK_ATT_AVV_ENABLED = os.environ.get('GK_ATT_AVV_ENABLED', '1') == '1'
GK_ATT_AVV_DATA_PATH = os.environ.get(
    'GK_ATT_AVV_DATA_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dati', 'gk_attacco_avversario.json'))
GK_ATT_AVV_FORMULA = os.environ.get('GK_ATT_AVV_FORMULA', 'secca')
_GK_ATT_AVV_FORMULE = {
    'secca': {'campo': 'att_medio', 'k': -4.26, 'media_globale': 1.400},
    'u10':   {'campo': 'att_u10',   'k': -2.4292, 'media_globale': 1.4225},
}
GK_ATT_AVV_MIN_STORICO = 4
_GK_ATT_AVV_TABELLA = {}
if GK_ATT_AVV_ENABLED:
    if GK_ATT_AVV_FORMULA not in _GK_ATT_AVV_FORMULE:
        print(f"ATTENZIONE: GK_ATT_AVV_FORMULA='{GK_ATT_AVV_FORMULA}' sconosciuta "
              f"(valide: {list(_GK_ATT_AVV_FORMULE)}) -- correttivo GK disattivato.")
        GK_ATT_AVV_ENABLED = False
    elif os.path.exists(GK_ATT_AVV_DATA_PATH):
        with open(GK_ATT_AVV_DATA_PATH, encoding='utf-8') as _f:
            _GK_ATT_AVV_TABELLA = json.load(_f).get('squadre', {})
    else:
        print(f"ATTENZIONE: GK_ATT_AVV_ENABLED=1 ma {GK_ATT_AVV_DATA_PATH} non esiste "
              "-- correttivo GK disattivato per questa run (nessun dato, nessuna riga toccata).")
        GK_ATT_AVV_ENABLED = False


def gk_att_avv_valore(avv_slug):
    """Valore dell'avversario secondo GK_ATT_AVV_FORMULA ('secca'/'u10'), o
    None se non in tabella, sotto GK_ATT_AVV_MIN_STORICO, o a
    GK_ATT_AVV_ENABLED spento (tabella vuota in quel caso, stesso
    fallback). Riusabile da chiunque debba applicare lo STESSO correttivo
    fuori da load_league_role_data() (es. analisi_manager/p24_binario2_ga.py,
    per testare G con/senza il correttivo nel backtest Binario 2)."""
    info = _GK_ATT_AVV_TABELLA.get(avv_slug) if avv_slug else None
    if not info or info.get('n_partite', 0) < GK_ATT_AVV_MIN_STORICO:
        return None
    campo = _GK_ATT_AVV_FORMULE.get(GK_ATT_AVV_FORMULA, {}).get('campo', 'att_medio')
    return info.get(campo)


def gk_att_avv_aggiustamento(avv_slug):
    """Delta in punti da sommare a un atteso GK gia' calibrato, o 0.0 se
    l'avversario non e' in tabella (fallback esplicito, mai un valore
    inventato)."""
    valore = gk_att_avv_valore(avv_slug)
    if valore is None:
        return 0.0
    f = _GK_ATT_AVV_FORMULE.get(GK_ATT_AVV_FORMULA, _GK_ATT_AVV_FORMULE['secca'])
    return f['k'] * (valore - f['media_globale'])


def _apply_gk_att_avv(rows):
    """Annota su ogni row (SOLO ruolo GK) _att_avv/atteso_att_avv. Se
    GK_ATT_AVV_ENABLED e' True, sovrascrive 'atteso'/'sort_score'. Se
    l'avversario non e' in tabella o ha meno di GK_ATT_AVV_MIN_STORICO
    partite, la riga resta invariata (adjustment=0, fallback esplicito)."""
    for r in rows:
        avv = r.get('opponent_team_slug')
        att_medio = gk_att_avv_valore(avv)
        if att_medio is None or r.get('atteso') is None:
            r['_att_avv'] = None
            r['atteso_att_avv'] = r.get('atteso')
            continue
        aggiustamento = gk_att_avv_aggiustamento(avv)
        r['_att_avv'] = att_medio
        r['atteso_att_avv'] = round(r['atteso'] + aggiustamento, 1)
        if GK_ATT_AVV_ENABLED:
            r['atteso'] = r['atteso_att_avv']
            if r.get('sort_score') is not None:
                r['sort_score'] = r['atteso_att_avv']


# Punteggio atteso oltre il quale l'ingresso si ripaga, misurato su 673 arene
# reali (consiglio_arena.py). Sotto questa riga si pagano piu' essenze di
# quante se ne incassino, e le carte rendono di piu' in una competizione senza
# costo d'ingresso (All Stars da 7, Under 23).
#
# Il valore dipende dal campo, non dall'utente: e' il punteggio al quale
# l'incasso medio -- calcolato pescando i nove avversari da arene vere e i
# premi da quelli davvero visti, arene gold incluse -- uguaglia il costo.
#
# STORIA (B06, P7 passaggio 2: questo commento descriveva solo la catena fino
# al 03/08, con SIGMA=42.70 -- gia' superata dalla ritaratura del 05/08, che
# aveva finito per lasciare solo un commento inline sulla riga della cap 260.
# Aggiornata qui la fonte, non solo la riga):
#   1. taratura_giocatore.py             -> 74.515 coppie previsione/realizzato
#   2. taratura_formazioni_sintetiche.py -> 40.000 formazioni da cinque col
#      capitano: dispersione dell'errore a livello di formazione (SIGMA)
#   3. consiglio_arena.py                -> converte SIGMA nelle soglie sotto
#
# VALORE CORRENTE (05/08, VALIDAZIONE_SOGLIE.md): SIGMA cap 260 corretta da
# 42.70 a 50.6 -- le soglie sotto vengono da quella ritaratura. Il campo
# avversario e i premi restano dalle 673 arene reali, invariati: solo SIGMA
# dipende dal modello ed e' l'unico ingresso che puo' spostare questi numeri.
PAREGGIO_ARENA = {
    # In punteggio REALE, perche' la previsione arriva gia' calibrata (vedi
    # calibra_riga). Prima erano espresse in previsione grezza -- 274.1 per la
    # cap 260 -- che e' lo stesso pareggio letto sull'altra scala.
    # AGGIORNATE 09/08/2026 (BRIEF_SONNET_APPLICA_SOGLIE_2026-08-09.txt,
    # HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt §11-12): premi VERI letti da
    # rewardsConfig su 2.125 arene avversarie / 5.031 premi osservati (contro
    # i 141 su cui poggiavano i valori precedenti). Split-half stabile
    # (scarti 0,2-2,5 pt).
    'ARENA_ALLSTARS_260': 264.5,      # era 259.5 (05/08); sigma cap 260 50.6
    'ARENA_ALLSTARS_220': 247.1,      # era 244.1
    'ARENA_ALLSTARS_UNCAPPED': 279.6,  # era 288.3
    'ARENA_ALLSTARS_ELITE': 342.7,    # INVARIATA (esclusa dal perimetro, decisione utente 09/08)
    'ARENA_ALLSTARS_BEGINNER': 256.5,  # tipo NUOVO 09/08, vedi COSTO_INGRESSO/GUADAGNO_PER_PUNTO sotto
}
# Arene dedicate a un campionato: SONO cap 260 (confermato dall'utente 03/08),
# stesso ingresso e stessi premi. La soglia e' comunque leggermente piu' bassa,
# 262.9, perche' il campo avversario e' un po' piu' debole: misurata sulle 191
# arene dedicate in archivio, non copiata dalla cap 260. NON ricalcolabile coi
# premi veri (quelle arene non sono nel nuovo archivio): lasciata INVARIATA
# il 09/08 per decisione esplicita dell'utente (vedi GUADAGNO_PER_PUNTO sotto,
# li' invece si allinea alla cap 260).
PAREGGIO_ARENA.update({arena_type(lg): 262.9 for lg in ARENA_LEAGUES})

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
# probabilita' di finire nei primi tre. RIMISURATE insieme alle soglie, come
# pendenza della curva dell'incasso nell'intorno del pareggio (+-5 punti).
# B06 (P7 passaggio 2): questo commento diceva ancora "un punto vale 29
# essenze" e "SIGMA=42.70" -- la cifra del 03/08, superata dalla ritaratura
# del 05/08 (SIGMA cap 260 -> 50.6). Il valore vivo oggi e' 7.9 essenze/punto
# per la cap 260 (vedi GUADAGNO_PER_PUNTO sotto), non 29: chi legge questo
# commento credeva a una catena che non esiste piu'.
GUADAGNO_PER_PUNTO = {
    # Essenze guadagnate per ogni punto REALE sopra il pareggio.
    # AGGIORNATE 09/08/2026 (stessa fonte di PAREGGIO_ARENA sopra: premi veri,
    # 5.031 osservazioni).
    'ARENA_ALLSTARS_260': 6.96, 'ARENA_ALLSTARS_220': 5.11,   # erano 7.9 e 6.3
    'ARENA_ALLSTARS_UNCAPPED': 5.88, 'ARENA_ALLSTARS_ELITE': 9.1,  # uncapped era 8.0; elite INVARIATA
    'ARENA_ALLSTARS_BEGINNER': 2.46,  # tipo NUOVO 09/08
}
# Arene dedicate: allineato a cap 260 (09/08, decisione utente). L'8.8 vecchio
# era un residuo della taratura precedente (l'unico rimasto alto mentre tutti
# gli altri sono scesi del 20-25% con i premi veri): il pareggio (sopra) resta
# la misura vera sul campo dedicato, ma il guadagno/pt si allinea perche' le
# regole/premi sono identici alla cap 260.
GUADAGNO_PER_PUNTO.update({arena_type(lg): 6.96 for lg in ARENA_LEAGUES})

COSTO_INGRESSO = {
    'ARENA_ALLSTARS_260': 300, 'ARENA_ALLSTARS_220': 200,
    'ARENA_ALLSTARS_UNCAPPED': 300, 'ARENA_ALLSTARS_ELITE': 800,
    'ARENA_ALLSTARS_BEGINNER': 100,  # tipo NUOVO 09/08
}
COSTO_INGRESSO.update({arena_type(lg): 300 for lg in ARENA_LEAGUES})

# Si entra se il guadagno atteso vale almeno il 10% di quello che si rischia.
# Sotto quella riga si immobilizzano essenze per quasi niente, e le stesse
# carte in una competizione gratuita rendono di piu' -- li' qualunque premio e'
# guadagno netto.
QUOTA_MINIMA = 0.10

# ARENA_CRITERIO (brief BRIEF_SONNET_CRITERIO_ARENE_2026-08-08.txt): come
# genera_arene_efficienti confronta i tipi fra loro. 'assoluto' (default,
# INVARIATO) = comportamento di sempre, ignora il costo d'ingresso. 'capitale'
# = resa per essenza impegnata (resa/COSTO_INGRESSO), tiene conto che la cap
# 220 costa 200 e la cap 260 ne costa 300. MISURA, non ancora una scelta di
# produzione: il default non cambia finche' l'utente non decide.
ARENA_CRITERIO = os.environ.get('ARENA_CRITERIO', 'assoluto')


def _etichetta_arena(tipo, atteso):
    """(testo, colore) da mostrare accanto alla formazione.

    Il margine si esprime in ESSENZE, non in punti: '+0.3 punti' non dice
    niente a chi legge, '+9 essenze attese' dice tutto.
    """
    soglia = PAREGGIO_ARENA.get(tipo)
    if soglia is None:
        return None, None
    margine = atteso - soglia
    # B05 (P7, passaggio 2): fallback allineato a 7.9 (cap 260, la chiave
    # vera del 05/08) su TUTTI i punti del repo con lo stesso .get(tipo, N) --
    # prima erano 29.0/7.5/8.8 a seconda del file, tutti irraggiungibili oggi
    # (le chiavi di PAREGGIO_ARENA e GUADAGNO_PER_PUNTO coincidono sempre),
    # ma alla prima chiave nuova avrebbero dato tre risposte diverse.
    guadagno = margine * GUADAGNO_PER_PUNTO.get(tipo, 7.9)
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
        # Freschezza ancorata ad ADESSO, non all'inizio della finestra: una GW
        # richiesta esplicitamente puo' iniziare fra giorni (GW2 il 04/08 con
        # run del 03/08), e i consigli -- anche quelli appena rigenerati in
        # questa stessa pipeline -- sono per forza precedenti all'inizio. Con
        # l'ancoraggio vecchio (inizio - 24h) venivano scartati TUTTI (bug run
        # 30802358443: 59->0 su ogni ruolo). Il guardiano anti-stantio
        # (kodai-sano) resta: un file vecchio di giorni non passa comunque.
        scritto = row.get('_source_ts')
        if scritto is None:
            return not REQUIRE_KICKOFF
        freschezza = datetime.timedelta(hours=float(os.environ.get('CONSIGLIO_MAX_AGE_HOURS', '48')))
        return scritto >= datetime.datetime.utcnow() - freschezza

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
                # 'role' e' la chiave del ciclo (GK/DEF/MID/FWD): la retta di
                # calibrazione e' diversa per ruolo, vedi CALIB_PER_RUOLO.
                row['role_key'] = role
                calibra_riga(row, role)
            counts, _ = bff.load_card_counts(DISCOVERY_DIRS[league][role])
            # starterOdds sulle righe (31/07): il valore e' gia' dentro
            # player_card_counts.json, scritto da discovery_fixture.py nella
            # stessa entry di copie/L10 -- serve al tie-break fra candidati
            # con punteggio quasi identico (vedi _sort_ordinamento). Chi non
            # ce l'ha (discovery vecchia, precedente a questo fix) resta senza
            # e viene trattato come "odds ignote", quindi nessun bonus:
            # comportamento invariato rispetto a prima.
            for row in rows:
                odds = (counts.get(row['slug']) or {}).get('starter_odds')
                if odds is not None:
                    row['starter_odds'] = odds
                grade = (counts.get(row['slug']) or {}).get('grade')
                if grade:
                    row['_grade_from_counts'] = grade
            # Grade (test isolato, sez. sopra): gruppo = (league, role) = questo
            # stesso 'rows', DOPO calibra_riga (agisce sul valore calibrato) e
            # DOPO starter_odds (non serve starter_odds per il grade, ma cosi'
            # la riga e' completa prima di qualunque uso a valle).
            _apply_grade_group(rows)
            if role == 'GK':
                _apply_gk_att_avv(rows)
            names.update(bff.load_player_names(DISCOVERY_DIRS[league][role]))
            print(f"[{league}/{role}] {path or 'NESSUN FILE TROVATO'} -> {len(rows)} giocatori")
            role_data[league][role] = rows
            role_counts[league][role] = counts
    if GRADE_GROUP_STORICA_ENABLED:
        _recentra_grade_per_ruolo(role_data)
    return role_data, role_counts, names


def _recentra_grade_per_ruolo(role_data):
    """Secondo passo della ricetta 12/08/2026 (GRADE_GROUP_STORICA_ENABLED):
    _apply_grade_group ha gia' scritto 'atteso_combinato' per ogni riga di
    ogni (lega,ruolo), ma NON ha ancora tolto la spinta cieca ne' applicato
    GRADE_ENABLED -- serve vedere TUTTE le leghe insieme per ruolo, cosa
    impossibile dentro _apply_grade_group (chiamata una lega+ruolo alla
    volta). Qui si raccolgono tutte le righe per ruolo (su tutte le leghe
    di QUESTA run), si sottrae la media dell'aggiustamento (atteso_combinato
    - atteso_cal) PER RUOLO -- non una costante congelata, ricalcolata ad
    ogni run sulla popolazione che si sta davvero punteggiando, come
    raccomandato da Opus (docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md
    §8bis-bis) -- e solo alla fine si sovrascrivono 'atteso'/'sort_score'
    se GRADE_ENABLED."""
    per_ruolo = defaultdict(list)
    for lg, roles in role_data.items():
        for role, rows in roles.items():
            for r in rows:
                if r.get('atteso_combinato') is not None and r.get('atteso_cal') is not None:
                    per_ruolo[role].append(r)
    for role, rows in per_ruolo.items():
        diffs = [r['atteso_combinato'] - r['atteso_cal'] for r in rows]
        media = sum(diffs) / len(diffs) if diffs else 0.0
        for r in rows:
            r['atteso_combinato'] = round(r['atteso_combinato'] - media, 2)
            if GRADE_ENABLED:
                r['atteso'] = r['atteso_combinato']
                if r.get('sort_score') is not None:
                    r['sort_score'] = r['atteso_combinato']
        print(f"[grade_storica] ricentraggio ruolo {role}: media aggiustamento tolta {media:+.3f} "
              f"({len(rows)} righe)")


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


# --- Preferenza per le starter odds alte (31/07, RISCRITTA P5/passaggio 2)
#
# Regola voluta, riformulata testualmente dall'utente nel passaggio 2: "a
# parita' di atteso, si preferisce quello con starter odds piu' alta".
# Decisione utente (opzione C): e' un TIE-BREAK, non un bonus additivo al
# punteggio -- non deve entrare nella funzione obiettivo (ne' qui ne' nel
# knapsack, vedi _optimize_capped_lineup in build_formazione_finale.py).
# Tolleranza fissata dall'utente: 1 punto pieno di atteso.
#
# Implementazione: un bucket a griglia fissa (floor(score/tolleranza)) e'
# stato provato e SCARTATO in fase di verifica -- due righe a 66.0 e 65.5
# (0.5 di distanza, ben dentro la tolleranza di 1.0) cadono in bucket
# ADIACENTI (floor(66.0)=66, floor(65.5)=65) e NON fanno tie-break: un falso
# negativo proprio sul caso che la regola deve coprire. Un confronto pairwise
# puro (|a-b|<tolleranza) e' l'alternativa naturale ma non e' un ordinamento
# valido su una LISTA (A~B e B~C non implicano A~C, commento originale di
# questa funzione, corretto).
#
# Soluzione: SPOGLIAMENTO ANCORATO AL MIGLIORE, non un comparatore. Ad ogni
# passo si prende il punteggio massimo residuo, si guarda chi sta entro
# tolleranza da QUEL massimo (non da una griglia fissa ne' da un confronto
# fra coppie arbitrarie), e fra quelli vince chi ha odds piu' alte. Il
# procedimento e' una sequenza di decisioni ben definite (ogni passo ha un
# unico vincitore deterministico), non un comparatore: non c'e' proprieta' di
# transitivita' da violare perche' non si sta ordinando via confronti a
# coppie indipendenti.
PREFERENZA_ODDS_TOLLERANZA = float(os.environ.get('PREFERENZA_ODDS_TOLLERANZA', '1.0'))


def _sort_ordinamento(rows):
    # REVERTITO (30/07, stesso motivo di build_consiglio_def.py/build_
    # consiglio.py -- vedi RIASSUNTO sez. 0.D punto 30): il vecchio
    # ordinamento per 'ordinamento' (senza shrinkage) non si conferma piu'
    # con dati aggiornati, e questa funzione lo stava ancora usando qui
    # nonostante il fix a monte -- bug reale trovato in corsa. Ordina sempre
    # per 'sort_score' se presente (bonus XP per la selezione, vedi
    # _apply_xp_bonus), altrimenti per 'atteso' (il punteggio vero).
    #
    # Spogliamento ancorato al migliore per il tie-break odds (vedi commento
    # sopra PREFERENZA_ODDS_TOLLERANZA): O(n^2) nel caso peggiore, accettabile
    # -- questa funzione gira una manciata di volte per generazione, mai in
    # un ciclo per-candidato.
    #
    # BANDA ODDS PRIMA DEL PUNTEGGIO (11/08/2026, richiesta esplicita utente,
    # bug reale: pool suppletivo EXTEND_ODDS_060_070 schierava Brady odds 60%
    # al posto di Chambaere odds 90% per un bonus XP di 3 punti sull'atteso).
    # Il pool suppletivo (10/08) pesca ANCHE candidati 0.60-0.70 insieme al
    # residuo 0.80+, senza sconto sul punteggio -- voluto, ma quello sconto
    # riguarda il VALORE del punteggio, non l'ordine di scelta: uno 0.80+
    # residuo va SEMPRE esaurito prima di toccare la banda 0.60-0.70,
    # qualunque sia il punteggio. In tornata primaria role_data e' gia'
    # filtrato a >=0.80 (vedi sopra), quindi qui e' sempre un solo gruppo e
    # questa partizione e' un no-op -- il fix agisce solo quando la lista
    # contiene davvero le due bande, cioe' nel pool suppletivo.
    def _banda_alta(r):
        odds = r.get('starter_odds')
        return odds is None or odds >= 0.80

    ordinati = []
    for gruppo in (
        [r for r in rows if _banda_alta(r)],
        [r for r in rows if not _banda_alta(r)],
    ):
        restanti = list(gruppo)
        while restanti:
            migliore = max(r.get('sort_score', r['atteso']) for r in restanti)
            vicini = [r for r in restanti
                      if r.get('sort_score', r['atteso']) >= migliore - PREFERENZA_ODDS_TOLLERANZA]
            vincitore = max(vicini, key=lambda r: (
                r.get('starter_odds') or 0.0, r.get('sort_score', r['atteso'])))
            ordinati.append(vincitore)
            restanti.remove(vincitore)
    rows[:] = ordinati
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


def _istantanea_pool(card_pool):
    """Copia dello stato consumato, per poter provare una formazione e disfarla."""
    import copy
    return (copy.deepcopy(card_pool._used),
            copy.deepcopy(getattr(card_pool, '_used_per_role', {})))


def _ripristina_pool(card_pool, stato):
    card_pool._used, usati_ruolo = stato[0], stato[1]
    if hasattr(card_pool, '_used_per_role'):
        card_pool._used_per_role = usati_ruolo


def genera_arene_efficienti(tipi, massimo, role_data, pools, card_pool):
    """Genera arene scegliendo DA SOLO tipo e numero, per essenze attese.

    Il generatore classico e' avido sui PUNTI: costruisce la formazione col
    punteggio piu' alto, tipo per tipo, nell'ordine che gli si da'. Il difetto
    e' che non sa quanto vale un punto -- mette una carta con L10 alto in una
    cap 260, dove divora budget, invece che in una uncapped dove non ne
    consuma affatto.

    Qui l'avidita' e' sulle ESSENZE: a ogni passo si prova a costruire la
    prossima formazione in OGNI tipo disponibile, si calcola quanto rende, e si
    tiene solo la migliore. Ci si ferma quando la migliore possibile non rende
    piu' niente.

    Conseguenze volute:
      - il mix si decide da solo e cambia con il mazzo del giorno, invece di
        essere deciso a mano tipo per tipo
      - nessun tipo va disattivato: quelli che non convengono semplicemente
        non vengono scelti. Le uncapped, per esempio, oggi non arrivano mai a
        soglia, ma torneranno utili quando arriveranno campionati con
        giocatori di L10 alto, che li' non consumano budget.
    """
    scelte = []
    for _ in range(max(0, massimo)):
        migliore = None
        for tipo in tipi:
            soglia = PAREGGIO_ARENA.get(tipo)
            if soglia is None:
                continue
            stato = _istantanea_pool(card_pool)
            try:
                prova = generate_lineups_for_type(tipo, 1, role_data, pools, card_pool)
            except Exception:
                prova = []
            _ripristina_pool(card_pool, stato)
            valide = [r for r in prova if 'error' not in r]
            if not valide:
                continue
            atteso = _atteso_con_capitano(valide[0])
            resa = (atteso - soglia) * GUADAGNO_PER_PUNTO.get(tipo, 7.9)  # B05, vedi _etichetta_arena
            # ARENA_CRITERIO (brief BRIEF_SONNET_CRITERIO_ARENE_2026-08-08.txt,
            # MISURA non ancora scelta di produzione): 'assoluto' (default,
            # comportamento di sempre) confronta la resa in essenze SENZA
            # guardare quanto costa entrare -- a parita' di margine la cap 260
            # vince sempre (GUADAGNO_PER_PUNTO piu' alto), anche se la cap 220
            # rende di piu' per essenza investita (misurato: 3.2%/pt contro
            # 2.6%/pt). 'capitale' confronta la resa PER ESSENZA IMPEGNATA
            # (resa/COSTO_INGRESSO), come si farebbe con un budget limitato.
            # Il segno di 'resa' non cambia (COSTO_INGRESSO sempre positivo),
            # quindi il criterio di stop "migliore[0] <= 0" sotto resta valido
            # in entrambi i casi -- verificato, non solo assunto.
            if ARENA_CRITERIO == 'capitale':
                resa_confronto = resa / COSTO_INGRESSO.get(tipo, 300)
            else:
                resa_confronto = resa
            if migliore is None or resa_confronto > migliore[0]:
                migliore = (resa_confronto, tipo, atteso, resa)
        if migliore is None or migliore[0] <= 0:
            break
        _resa_confronto, tipo, atteso, _resa = migliore
        vera = generate_lineups_for_type(tipo, 1, role_data, pools, card_pool)
        for r in vera:
            if 'error' not in r:
                scelte.append(r)
        nota_criterio = (f", resa/essenza investita {_resa_confronto:.4f}"
                        if ARENA_CRITERIO == 'capitale' else '')
        print(f"  arena efficiente #{len(scelte)}: {LABELS.get(tipo, tipo)} "
              f"-- atteso {atteso:.1f}, resa {_resa:.0f} essenze{nota_criterio}")
    return scelte


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
    #
    # DISATTIVATO (13/08/2026, richiesta esplicita utente): meccanismo mai
    # riverificato da quando fu introdotto, e un caso reale (run #166,
    # All Stars Under23 col pool suppletivo 0.60-0.70) ha mostrato il retry
    # "si rinuncia e si rigenera" BUTTARE VIA formazioni gia' generate con
    # successo (#1 e #2 valide) solo perche' una successiva (#3) falliva --
    # il retry senza forzare il cap 370 e' ripartito da un pool piu' povero
    # e ha fallito ANCHE la #1, che nel primo giro era andata bene. Risultato
    # reale: 0 formazioni consegnate su 4, con 2 gia' pronte scartate.
    # Spento del tutto finche' non si riverifica se il cap 370 forzato vale
    # ancora qualcosa E si sistema il retry per non scartare i successi gia'
    # ottenuti. `_run(False)` sotto e' il comportamento SENZA forzatura,
    # identico per tutti i tipi.
    force_cap370_first = False
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
            print(f"Formazione {label} #{idx}: generata "
                  f"({sum(r['atteso'] for _, r, _ in formazione):.1f} pt)")
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
  /* COLLASSO (08/08, richiesta esplicita utente: "falla proprio sparire, cosi'
     non la vedo piu' e non mi confondo"). Segnata come schierata, la
     formazione si richiude e resta solo il titolo con un tasto per
     riaprirla. Lo stato "riaperta" NON e' persistito di proposito: alla
     riapertura del file le schierate tornano chiuse, che e' lo scopo. */
  .lineup-block[data-schierata="1"] { padding-bottom: 4px; }
  .btn-riapri {
    display: none; margin-left: 12px; cursor: pointer; user-select: none;
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.02em;
    padding: 3px 10px; border-radius: 999px; vertical-align: middle;
    border: 1px solid #2fbf6a; color: #2fbf6a; background: rgba(47,191,106,0.12);
  }
  .btn-riapri:hover { background: rgba(47,191,106,0.24); }
  .lineup-block[data-schierata="1"] .btn-riapri { display: inline-block; }
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

    // Tasto per riaprire una formazione richiusa. Vive DENTRO il titolo,
    // l'unica parte che resta visibile quando il blocco e' collassato.
    var riapri = document.createElement('span');
    riapri.className = 'btn-riapri';
    var aperta = false;   // non persistito: si riparte sempre da chiusa

    // Il contenuto da nascondere sono tutti i figli diretti del blocco TRANNE
    // quello che contiene il titolo. Si ricava risalendo dal titolo invece di
    // elencare classi a mano: se un domani il template cambia struttura,
    // questo continua a funzionare.
    var ramoTitolo = titolo;
    while (ramoTitolo && ramoTitolo.parentNode !== block) { ramoTitolo = ramoTitolo.parentNode; }

    function applica() {
      var on = stato[id] ? '1' : '0';
      flag.setAttribute('data-on', on);
      block.setAttribute('data-schierata', on);
      var chiudi = !!stato[id] && !aperta;
      Array.prototype.forEach.call(block.children, function (ch) {
        if (ch !== ramoTitolo) { ch.style.display = chiudi ? 'none' : ''; }
      });
      riapri.textContent = aperta ? 'richiudi' : 'clicca per riaprire';
    }
    flag.addEventListener('click', function (ev) {
      ev.stopPropagation();
      stato[id] = !stato[id];
      if (!stato[id]) { delete stato[id]; }
      aperta = false;   // rimarcandola da schierare si riparte da chiusa
      salva();
      applica();
    });
    riapri.addEventListener('click', function (ev) {
      ev.stopPropagation();
      ev.preventDefault();
      aperta = !aperta;
      applica();
    });
    applica();
    titolo.appendChild(flag);
    titolo.appendChild(riapri);
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
    arena_allstars_beginner = _read_int_env('ARENA_ALLSTARS_BEGINNER', 0)
    allstars_qty = _read_int_env('ALLSTARS', 0)
    allstars_u23_qty = _read_int_env('ALLSTARS_U23', 0)

    counts = {
        'MLS_IN_SEASON': in_season_req['mls'], 'KLEAGUE_IN_SEASON': in_season_req['kleague'],
        'ARENA_ALLSTARS_260': arena_allstars_260, 'ARENA_ALLSTARS_220': arena_allstars_220,
        'ARENA_ALLSTARS_UNCAPPED': arena_allstars_uncapped, 'ARENA_ALLSTARS_BEGINNER': arena_allstars_beginner,
        'ALLSTARS': allstars_qty,
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
    if allstars_qty or allstars_u23_qty or arena_allstars_260 or arena_allstars_220 or arena_allstars_uncapped \
            or arena_allstars_beginner:
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

    # FIX (12/08/2026, bug reale trovato dall'utente: Kevin Mac Allister
    # schierato in Arena Beginner del pool suppletivo con kickoff 15/08
    # mentre la finestra esplicita della giornata era 11-14/08 -- run175).
    # CAUSA: 'role_data_ext' veniva catturato PRIMA di filter_by_window (piu'
    # sotto), quindi ereditava candidati MAI passati dal filtro finestra --
    # solo 'role_data' (il ramo principale) lo era. Il pool suppletivo
    # (EXTEND_ODDS_060_070) legge SOLO role_data_ext, quindi era l'unico
    # punto della run a poter proporre carte fuori giornata: tutte le altre
    # formazioni (lette da role_data) restavano corrette, spiegando perche'
    # l'anomalia toccava solo lui. Il filtro finestra (E l'esclusione
    # manuale sopra) devono valere per ENTRAMBI i rami: si applicano qui,
    # PRIMA che role_data_ext si separi da role_data (poco sotto), non piu'
    # dopo. Stesso ordine, stesso risultato per role_data -- solo
    # role_data_ext cambia (ora filtrato anche lui).
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

    # POOL ESTESO (10/08/2026, EXTEND_ODDS_060_070, default spento): quando il
    # flag e' acceso, discovery_fixture.py porta ANCHE candidati con
    # starter_odds nella banda 0.60-0.70 (unica banda possibile sotto 0.80: le
    # starter-odds Sorare escono a blocchi da 10). 'role_data' resta SEMPRE
    # filtrato a >=0.80 (o odds ignote, comportamento di sempre): FASE 1, ARENE
    # EFFICIENTI, ALLSTARS/ALLSTARS_U23 e FASE 1b restano quindi identici a un
    # run col flag spento anche quando la discovery ha portato di piu' -- a
    # flag spento questo filtro e' un no-op (la discovery non porta mai sotto
    # 0.80). 'role_data_ext' (tutto, banda compresa, MA sempre dentro finestra
    # ed esclusioni -- vedi fix sopra) e' letto SOLO dal passo POOL
    # SUPPLETIVO piu' sotto, mai dal resto.
    EXTEND_ODDS_060_070 = os.environ.get('EXTEND_ODDS_060_070', '0') == '1'
    role_data_ext = role_data
    role_data = {
        lg: {role: [r for r in rows if r.get('starter_odds') is None or r['starter_odds'] >= 0.80]
             for role, rows in roles.items()}
        for lg, roles in role_data.items()
    }

    # DUMP_JSON_CANDIDATI (misura GRADE_SCALE, brief BRIEF_SONNET_GRADE_
    # SCALA_STORICA_2026-08-08.txt, Passo 0b/0c): se impostata, scrive TUTTI
    # i candidati (non solo quelli scelti in una formazione, a differenza di
    # DUMP_JSON) con grade/atteso_cal/atteso_combinato -- serve a misurare
    # quante carte cambiano z fra GRADE_SCALE=gruppo e =storica. Var non
    # impostata -> non scrive nulla, nessun costo.
    _dump_cand_path = os.environ.get('DUMP_JSON_CANDIDATI', '')
    if _dump_cand_path:
        _cand = []
        for lg in LEAGUES:
            for role in ROLES:
                for row in role_data.get(lg, {}).get(role, []):
                    _cand.append({
                        'slug': row.get('slug'), 'league': lg, 'role_key': role,
                        'grade': row.get('_grade'), 'grade_num': row.get('_grade_num'),
                        'atteso_cal': row.get('atteso_cal'),
                        'atteso_combinato': row.get('atteso_combinato'),
                    })
        with open(_dump_cand_path, 'w', encoding='utf-8') as _fh:
            json.dump({'grade_scale': GRADE_SCALE, 'candidati': _cand}, _fh, ensure_ascii=False)
        print(f"\nDUMP_JSON_CANDIDATI scritto: {_dump_cand_path} ({len(_cand)} candidati)")

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

    # TOP-UP L10 (fix strutturale, 03/08): l'L10 e' un campo Sorare player-level
    # dinamico, sempre esposto. Se la discovery non l'ha persistita per un
    # candidato (query odds+L10 fallita, 429), a valle card_pool.l10() torna
    # None e il cap arena la contava 0 -> la formazione sforava il tetto in
    # silenzio (i 5 L10 veri superano 260). Qui, per QUALUNQUE pool, si chiede
    # all'API l'L10 mancante di ogni candidato prima di generare le arene.
    # Gira solo se sono coinvolte arene (il cap riguarda solo loro) e se c'e' il
    # cookie (in locale senza rete si usa quel che c'e' gia' in cache).
    arene_coinvolte = int(os.environ.get('ARENE_EFFICIENTI', '0') or 0) > 0 or \
        any(_is_arena_type(t) and counts.get(t, 0) > 0 for t in counts)
    if arene_coinvolte and os.environ.get('SORARE_COOKIE'):
        _slugs_pool, _visti = [], set()
        for _lg, _roles in role_data.items():
            for _role, _rows in _roles.items():
                for _r in _rows:
                    _s = _r.get('slug')
                    if _s and _s not in _visti:
                        _visti.add(_s)
                        if card_pool.l10(_s) is None:
                            _slugs_pool.append(_s)
        if _slugs_pool:
            _df = _import_module('discovery_fixture_l10', 'discovery_fixture.py')
            print(f"\nTop-up L10: {len(_slugs_pool)} candidati senza L10 in cache, "
                  f"li chiedo all'API (il cap arena non puo' contarli 0).")
            _ok = 0
            for _s in _slugs_pool:
                _v = _df.l10_da_api(_s)
                if _v is not None:
                    card_pool.set_l10(_s, _v)
                    _ok += 1
            print(f"Top-up L10: riempiti {_ok}/{len(_slugs_pool)} "
                  f"(i restanti hanno L10 API nulla = nessuna So5 giocata, valgono ~0).")

    run_number = os.environ.get('GITHUB_RUN_NUMBER')

    # FASE 1: genera (e consuma il card_pool) per tutti i tipi, in ordine di
    # priorita'. Nessun HTML ancora -- il rendering avviene dopo, quando si
    # conoscono TUTTE le formazioni (serve per il pannello alternative).
    #
    # FIX (10/08, bug reale trovato dall'utente confrontando run158/run159 a
    # parita' di ARENE_EFFICIENTI=10): PRIORITY_ORDER mette le arene SOPRA
    # ALLSTARS_U23/ALLSTARS, ma prima questo ciclo generava TUTTI i tipi con
    # conteggio esplicito -- ALLSTARS_U23/ALLSTARS compresi -- e SOLO DOPO
    # partiva ARENE_EFFICIENTI (che in modalita' "efficiente" non ha un
    # conteggio esplicito, quindi qui non genera nulla). Risultato: se
    # ALLSTARS_U23/ALLSTARS erano richieste insieme alle arene efficienti,
    # si mangiavano il pool per prime nonostante fossero l'ULTIMA priorita'
    # (9 arene chiedendo solo arene, 4 chiedendo anche 4+4 AllStars/U23,
    # stesso ARENE_EFFICIENTI=10 in entrambe le run). Ora il ciclo si ferma
    # PRIMA di ALLSTARS_U23/ALLSTARS, ARENE_EFFICIENTI gira sul pool ancora
    # intatto, e ALLSTARS_U23/ALLSTARS vengono generate per ultime, come da
    # PRIORITY_ORDER.
    POST_ARENA_TYPES = {'ALLSTARS_U23', 'ALLSTARS'}
    all_results = []
    for tipo in PRIORITY_ORDER:
        if tipo in POST_ARENA_TYPES:
            continue
        all_results.extend(generate_lineups_for_type(tipo, counts[tipo], role_data, pools, card_pool))

    # ARENE EFFICIENTI (02/08): invece di dire quante di ogni tipo, si dice
    # quante al massimo e il bot sceglie da solo tipo e numero, massimizzando
    # le essenze attese. Gira DOPO le richieste esplicite di In Season/arene
    # dedicate/Arena All Stars (priorita' piu' alta), ma PRIMA di
    # ALLSTARS_U23/ALLSTARS (priorita' piu' bassa) -- vedi fix sopra.
    _n_eff = int(os.environ.get('ARENE_EFFICIENTI', '0') or 0)
    if _n_eff > 0:
        _tipi = [t for t in PRIORITY_ORDER if _is_arena_type(t)]
        print(f"\n=== ARENE EFFICIENTI: fino a {_n_eff}, tipo scelto dal bot")
        print("Nessun tipo e' disattivato: quelli che non rendono non vengono")
        print("scelti, e torneranno appena il mazzo li rendera' convenienti.")
        all_results.extend(genera_arene_efficienti(_tipi, _n_eff, role_data,
                                                   pools, card_pool))

    # Solo ora ALLSTARS_U23/ALLSTARS, sul pool residuo (fix sopra).
    for tipo in PRIORITY_ORDER:
        if tipo in POST_ARENA_TYPES:
            all_results.extend(generate_lineups_for_type(tipo, counts[tipo], role_data, pools, card_pool))

    # POOL SUPPLETIVO (10/08/2026, EXTEND_ODDS_060_070, default spento):
    # scatta SOLO se la tornata sopra (arene esplicite + ARENE EFFICIENTI +
    # ALLSTARS/ALLSTARS_U23, tutta a odds >=0.80) non ha riempito gli slot
    # RICHIESTI. Usa lo STESSO card_pool gia' consumato sopra -- non puo'
    # "rubare" carte gia' finite in una formazione della tornata primaria,
    # puo' solo pescare dal residuo 0.80+ mai scelto + la banda 0.60-0.70
    # (role_data_ext). Riguarda SOLO Arena Beginner (unica arena ammessa, le
    # altre restano fuori) + All Stars + All Stars Under23. Per le arene vale
    # lo stesso vincolo di margine/soglia (genera_arene_efficienti, PAREGGIO_
    # ARENA) di sempre: nessuno sconto sul punteggio per le odds piu' basse
    # (richiesta esplicita utente, 10/08 -- vanno valutate come le 0.80+).
    if EXTEND_ODDS_060_070:
        _richiesti_arene = sum(counts.get(t, 0) for t in PRIORITY_ORDER if _is_arena_type(t)) + max(_n_eff, 0)
        _generati_arene = sum(1 for r in all_results if 'error' not in r and _is_arena_type(r.get('tipo')))
        _shortfall_arene = max(0, _richiesti_arene - _generati_arene)
        _generati_allstars = sum(1 for r in all_results if 'error' not in r and r.get('tipo') == 'ALLSTARS')
        _generati_u23 = sum(1 for r in all_results if 'error' not in r and r.get('tipo') == 'ALLSTARS_U23')
        _shortfall_allstars = max(0, counts.get('ALLSTARS', 0) - _generati_allstars)
        _shortfall_u23 = max(0, counts.get('ALLSTARS_U23', 0) - _generati_u23)
        if _shortfall_arene or _shortfall_allstars or _shortfall_u23:
            print(f"\n=== POOL SUPPLETIVO (odds 0.60-0.70): mancano {_shortfall_arene} "
                  f"Arena Beginner, {_shortfall_allstars} All Stars, {_shortfall_u23} "
                  f"All Stars Under23 rispetto al richiesto -- provo con la banda "
                  f"0.60-0.70 + il residuo 0.80+ non ancora usato.")
            pools_ext = build_quality_pools(role_data_ext)
            _suppl = []
            # Ordine SOLO del suppletivo (10/08, richiesta esplicita utente,
            # diverso da PRIORITY_ORDER che vale per la tornata primaria):
            # Under23 scavalca le arene qui -- 1) All Stars Under23, 2) Arena
            # Beginner (solo se ancora scoperta), 3) All Stars. Motivo: nella
            # tornata primaria le arene vengono comunque prima (PRIORITY_
            # ORDER invariato), quindi Under23 parte gia' svantaggiata sui
            # pochi U23-eleggibili -- nel recupero suppletivo tocca a lei
            # per prima, cosi' non perde altri candidati contro le arene
            # (che nella tornata primaria hanno gia' avuto la loro parte) ne'
            # contro le All Stars normali (bug fix 10/08 precedente, ordine
            # comunque confermato: Under23 prima di All Stars).
            if _shortfall_u23:
                _batch = generate_lineups_for_type('ALLSTARS_U23', _shortfall_u23, role_data_ext, pools_ext, card_pool)
                for i, r in enumerate(_batch):
                    if 'error' in r:
                        break
                    r['idx'] = _generati_u23 + i + 1
                    _suppl.append(r)
            if _shortfall_arene:
                _suppl.extend(genera_arene_efficienti(['ARENA_ALLSTARS_BEGINNER'], _shortfall_arene,
                                                       role_data_ext, pools_ext, card_pool))
            if _shortfall_allstars:
                _batch = generate_lineups_for_type('ALLSTARS', _shortfall_allstars, role_data_ext, pools_ext, card_pool)
                for i, r in enumerate(_batch):
                    if 'error' in r:
                        break
                    r['idx'] = _generati_allstars + i + 1
                    _suppl.append(r)
            for r in _suppl:
                r['suppletivo'] = True
            print(f"Pool suppletivo: {len(_suppl)} formazioni aggiuntive "
                  f"({sum(1 for r in _suppl if r['tipo'] == 'ARENA_ALLSTARS_BEGINNER')} Arena Beginner, "
                  f"{sum(1 for r in _suppl if r['tipo'] == 'ALLSTARS')} All Stars, "
                  f"{sum(1 for r in _suppl if r['tipo'] == 'ALLSTARS_U23')} All Stars Under23).")
            all_results.extend(_suppl)

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
        print(f"TOTALE COMPLESSIVO: {grand_total:.1f} pt")

    # DUMP_JSON (test isolato grade, branch test-grade-g-gw3, 07/08/2026):
    # se impostata, scrive un JSON ispezionabile delle formazioni PRIMARIE
    # (non 'extra', cioe' esattamente le richieste esplicite via env: le
    # ARENE_EFFICIENTI + le IN_SEASON/ALLSTARS primarie) con, per ogni riga,
    # atteso_cal (A) / _grade / atteso_combinato (G) / se e' nella formazione.
    # Non tocca il comportamento di default (var non impostata -> non scrive
    # nulla, nessun costo).
    _dump_path = os.environ.get('DUMP_JSON', '')
    if _dump_path:
        dump = []
        for r in all_results:
            if r.get('extra') or 'error' in r:
                continue
            _cap_slot, _cap_row, _cap_tipo = (None, None, None)
            try:
                _cap_slot, _cap_row, _cap_tipo = bff.pick_captain(r['formazione'])
            except Exception:
                pass
            righe = []
            for _slot, row, _t in r['formazione']:
                righe.append({
                    'slug': row.get('slug'), 'role_key': row.get('role_key'),
                    'league': row.get('league'), 'atteso_cal': row.get('atteso_cal', row.get('atteso')),
                    'grade': row.get('_grade'), 'atteso_combinato': row.get('atteso_combinato', row.get('atteso')),
                    'atteso_usato': row.get('atteso'), 'starter_odds': row.get('starter_odds'),
                    'capitano': (_cap_row is not None and row.get('slug') == _cap_row.get('slug')
                                 and row.get('role_key') == _cap_row.get('role_key')),
                })
            dump.append({
                'tipo': r['tipo'], 'idx': r.get('idx'), 'label': r.get('label'),
                'atteso_totale_con_capitano': _atteso_con_capitano(r),
                'righe': righe,
            })
        with open(_dump_path, 'w', encoding='utf-8') as _fh:
            json.dump({'grade_enabled': GRADE_ENABLED, 'grade_data_path': GRADE_DATA_PATH,
                       'n_grade_map': len(_GRADE_MAP), 'formazioni': dump},
                      _fh, ensure_ascii=False, indent=2)
        print(f"\nDUMP_JSON scritto: {_dump_path} ({len(dump)} formazioni primarie)")

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
            # La formazione viene RACCHIUSA in una cornice del colore del
            # verdetto, con l'etichetta dentro: con una riga staccata non si
            # capiva a quale arena si riferisse (segnalato dall'utente).
            lineup_html = (
                f'<div style="border:2px solid {_col};border-radius:10px;'
                f'padding:10px 12px 4px 12px;margin:0 0 18px 0">'
                f'<div style="font-size:.85rem;color:{_col};margin-bottom:8px">'
                f'<b>{_et}</b></div>{lineup_html}</div>')
        # Badge POOL SUPPLETIVO (10/08/2026, EXTEND_ODDS_060_070): marcata
        # bene visibile -- questa formazione contiene (o puo' contenere)
        # carte con starter-odds 0.60-0.70, piu' rischiose delle 0.80+ di
        # tutte le altre. Richiesta esplicita utente: deve saltare all'occhio
        # prima di schierare.
        if r.get('suppletivo'):
            lineup_html = (
                '<div style="font-size:.78rem;color:#3a7bd5;background:rgba(58,123,213,.12);'
                'border:1px solid #3a7bd5;border-radius:6px;padding:3px 9px;'
                'display:inline-block;margin-bottom:6px">'
                'POOL SUPPLETIVO -- starter-odds 0.60-0.70, non 0.80+</div>'
                f'{lineup_html}')
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
        # Badge "fixture ambigua" (12/08/2026, richiesta esplicita utente),
        # stesso marker AMBIGUO_FIXTURE del badge in pcard -- vedi
        # build_formazione_finale.py:_pcard_body_html. Qui la tabella e'
        # compatta, quindi solo un'icona col tooltip invece del testo lungo.
        ambiguo_marker = (
            '<span title="Fixture ambigua: due partite future con odds '
            'pubblicate insieme, l\'atteso potrebbe riferirsi alla partita '
            'sbagliata (caso Freese, 10/08)." style="cursor:help">⚠ </span>'
            if row.get('ambiguo') else ''
        )
        # punteggio spostato SUBITO dopo il numero, a sinistra del nome
        # (29/07, bug segnalato dall'utente: prima era in fondo a destra
        # e la colonna nome veniva tagliata con ellissi). Nome ora senza
        # limite di larghezza (va a capo se serve invece di troncare),
        # "vs" resta l'unica colonna che tronca (meno critica).
        return (
            f'<tr><td style="padding:2px 6px 2px 0;color:var(--muted)">{i+1}.</td>'
            f'<td style="padding:2px 8px 2px 0;font-weight:700;white-space:nowrap">{(row.get("atteso") or 0):.1f} pt</td>'
            f'<td style="padding:2px 6px 2px 0;white-space:normal">{ambiguo_marker}{player_names.get(row["slug"], row["slug"])}</td>'
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
        # IN FONDO, non in cima (08/08, richiesta esplicita utente): e' una
        # tabella lunga quanto il numero di arene, e in testa al report
        # spingeva giu' le formazioni, che sono la cosa che si usa davvero.
        # Si legge una volta per decidere se entrare, non ad ogni scorrimento.
        lineup_html_blocks.append(verdetto_html)
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
