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
# TRANNE In Season, dove il target e' fisso e non c'e' beneficio (stessa
# regola gia' in produzione nei due tool singoli, confermata dall'utente
# valida anche per le Arene dedicate fuse).
VARIANCE_MODE_TYPES = {'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220',
                        'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS', 'ALLSTARS_U23'}
VARIANCE_MODE_TYPES.update(arena_type(lg) for lg in ARENA_LEAGUES)

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
# Ordine: In Season -> Arene dedicate (nell'ordine di ARENA_LEAGUES, cioe'
# MLS e K League per prime, poi gli altri campionati) -> Arena All Stars ->
# All Stars. Il CardPool e' condiviso: se le carte finiscono, restano scoperte
# le formazioni meno prioritarie.
PRIORITY_ORDER = (
    ['MLS_IN_SEASON', 'KLEAGUE_IN_SEASON']
    + [arena_type(lg) for lg in ARENA_LEAGUES]
    + ['ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS_U23', 'ALLSTARS']
)

POOL_LEAGUE_BY_TYPE = {
    'MLS_IN_SEASON': 'mls', 'KLEAGUE_IN_SEASON': 'kleague',
    'ARENA_ALLSTARS_260': 'mixed', 'ARENA_ALLSTARS_220': 'mixed', 'ARENA_ALLSTARS_UNCAPPED': 'mixed',
    'ALLSTARS': 'mixed', 'ALLSTARS_U23': 'mixed_u23',
}

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


# --- FINESTRA GIORNATA (27/07) -------------------------------------------
# Senza questo filtro il generatore mescolava giocatori la cui partita target
# era GIA' STATA GIOCATA con giocatori che giocano fra una settimana: entrambi
# inutili per la formazione di domani. E i secondi non hanno ancora le starter
# odds (escono a ~24-48h), quindi passavano indenni anche il filtro sulla
# soglia -- che percio' sembrava non funzionare.
# MATCH_WINDOW_DAYS = quanti giorni in avanti da ADESSO includere (default 2).
# Un consiglio SENZA riga KICKOFF e' per definizione generato prima di questo
# fix, quindi stale: viene SCARTATO. Meglio una formazione incompleta che una
# piena di giocatori che non scendono in campo. Con MATCH_WINDOW_REQUIRE_KICKOFF=0
# si torna al comportamento permissivo (utile solo per debug su dati vecchi).
MATCH_WINDOW_DAYS = float(os.environ.get('MATCH_WINDOW_DAYS', '7'))
REQUIRE_KICKOFF = os.environ.get('MATCH_WINDOW_REQUIRE_KICKOFF', '1').strip() not in ('0', 'false', 'no')


def _within_window(row, now=None):
    ko = row.get('kickoff')
    if not ko:
        return not REQUIRE_KICKOFF
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
            for row in rows:
                row['league'] = league
            counts, _ = bff.load_card_counts(DISCOVERY_DIRS[league][role])
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


def _sort_ordinamento(rows):
    # Ordina per lo score di ordinamento (senza shrinkage) -- vedi sezione
    # 27.C del RIASSUNTO. Fallback TUTTO-O-NIENTE: i due score stanno su
    # scale diverse, mescolarli nella stessa sort non e' omogeneo.
    if rows and all(r.get('ordinamento') is not None for r in rows):
        rows.sort(key=lambda r: r['ordinamento'], reverse=True)
    else:
        rows.sort(key=lambda r: r['atteso'], reverse=True)
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
    """Ritorna una COPIA delle righe con atteso/ordinamento/low/high
    moltiplicati per (1 + bonus power della carta, vedi
    CardPool.power_bonus_fraction) -- MAI muta le righe originali (condivise
    fra tutti i tipi di formazione nella stessa run, incluse le Arene dove
    questo bonus NON si applica, vedi XP_BONUS_TYPES). Righe senza bonus noto
    (frazione 0.0) restano le stesse istanze, nessuna copia inutile.
    RI-ORDINA sempre il risultato (non solo per i ruoli/tipi che poi passano
    da synergy_adjusted_rows, es. il portiere non ci passa mai se non c'e'
    used_matches): senza questo il boost cambierebbe i punteggi ma non
    l'ordine di scelta, vanificando "preferire un giocatore piu' debole ma
    con bonus" per lo slot GK."""
    out = []
    for r in rows:
        frac = card_pool.power_bonus_fraction(r['slug'])
        if not frac:
            out.append(r)
            continue
        r2 = dict(r)
        mult = 1.0 + frac
        r2['atteso'] = round(r['atteso'] * mult)
        if r.get('ordinamento') is not None:
            r2['ordinamento'] = round(r['ordinamento'] * mult)
        if r.get('low') is not None:
            r2['low'] = round(r['low'] * mult)
        if r.get('high') is not None:
            r2['high'] = round(r['high'] * mult)
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
    in_season_multi = tipo in ('MLS_IN_SEASON', 'KLEAGUE_IN_SEASON') and count >= 2
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
            apply_positive_synergy = (tipo not in ('ARENA_ALLSTARS_UNCAPPED', 'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON')
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

    # FASE 2: rendering (28/07: pannello alternative/drag&drop RIMOSSO su
    # richiesta esplicita utente -- non serviva piu', bastano le formazioni).
    lineup_html_blocks = []
    for r in all_results:
        if 'error' in r:
            lineup_html_blocks.append(f'<p class="error-block">{r["error"]}</p>')
            continue
        lineup_html = bff.render_lineup_html(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'], apply_xp_bonus=r['tipo'] in XP_BONUS_TYPES)
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

    # Capienza residua (29/07, richiesta esplicita utente): con i giocatori
    # rimasti FUORI dalle formazioni generate, quante ALTRE formazioni si
    # sarebbero potute generare. Per OGNI tipologia di competizione richiesta,
    # non solo per le Arene dedicate: vale anche per In Season MLS, In Season
    # K League, All Stars, All Stars U23 e Arena All Stars. Il conteggio
    # "Candidati non schierati" sopra dice quanti giocatori restano sul banco,
    # ma non se bastano a comporre una formazione valida (servono i ruoli
    # giusti, e per le Arene anche il cap L10) -- questo lo dice.
    #
    # Calcolata rigenerando su una COPIA del card_pool, quindi non tocca in
    # alcun modo le formazioni prodotte; e viene calcolata DOPO il rendering
    # (FASE 2, gia' fatto sopra), cosi' per costruzione non puo' influenzare
    # l'output nemmeno per errore.
    # Budget di tempo oltre al tetto sul conteggio: ogni sondaggio e' una
    # generazione greedy completa (~1-2s con il pool pieno), e con molte
    # tipologie richieste dal pool misto il conteggio da solo potrebbe
    # allungare sensibilmente questo job. Esaurito il budget, il numero
    # riportato diventa un "almeno N" invece di un valore esatto.
    MAX_SONDAGGIO_CAPIENZA = 20
    BUDGET_SONDAGGIO_S = 45.0
    _t0_sondaggio = datetime.datetime.utcnow()
    capienza_extra = {}
    capienza_parziale = set()
    for tipo in PRIORITY_ORDER:
        if counts[tipo] <= 0:
            continue
        sonda = copy.deepcopy(card_pool)
        extra = 0
        while extra < MAX_SONDAGGIO_CAPIENZA:
            trascorso = (datetime.datetime.utcnow() - _t0_sondaggio).total_seconds()
            if trascorso > BUDGET_SONDAGGIO_S:
                capienza_parziale.add(tipo)
                break
            res = generate_lineups_for_type(tipo, 1, role_data, pools, sonda)
            if not res or any('error' in r for r in res):
                break
            extra += 1
        if extra >= MAX_SONDAGGIO_CAPIENZA:
            capienza_parziale.add(tipo)
        capienza_extra[tipo] = extra

    if capienza_extra:
        print("\nFormazioni AGGIUNTIVE possibili con i giocatori rimasti fuori:")
        for tipo, extra in capienza_extra.items():
            fatte = generated_by_type.get(tipo, 0)
            if extra:
                print(f"  {LABELS[tipo]}: {fatte} generate ma potevi generarne "
                      f"altre {extra}"
                      + (" o piu'" if tipo in capienza_parziale else ""))
            else:
                print(f"  {LABELS[tipo]}: {fatte} generate, il pool residuo non "
                      f"basta per un'altra")

    capienza_html = ""
    if capienza_extra:
        voci = []
        for tipo, extra in capienza_extra.items():
            fatte = generated_by_type.get(tipo, 0)
            piu = "+" if tipo in capienza_parziale else ""
            voci.append(f"{LABELS[tipo]}: {fatte} generate, altre "
                        f"{extra}{piu} possibili")
        capienza_html = ("<br>Con i giocatori rimasti fuori: " +
                         "; ".join(voci))

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    run_suffix = f"_run{run_number}" if run_number else ""
    page_title = f"Generatore Formazioni{' — run #' + run_number if run_number else ''}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"totale={num_totale} (" +
                     ", ".join(f"{LABELS[t]}={counts[t]}" for t in PRIORITY_ORDER) + ")<br>"
                     f"Candidati non schierati in nessuna formazione: {tot_esclusi} (" +
                     ", ".join(f"{r}: {esclusi_per_ruolo[r]}" for r in ROLES) + ")" +
                     capienza_html)
    footer_html = (f"Fusione {len(LEAGUES)} campionati. Max 1 carta CLASSIC solo per In Season. "
                    f"Filtro qualita' L5/L10/L40 disattivato (28/07): ridondante con lo starter-odds.")
    html_text = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_path = os.path.join(OUTPUT_DIR, f'generatore_formazioni{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"\nReport visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
