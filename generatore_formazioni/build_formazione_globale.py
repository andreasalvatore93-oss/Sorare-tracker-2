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
import html
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
    Le leghe si scoprono dal filesystem: aggiungerne una non richiede codice."""
    found = {}
    for consiglio_dir in sorted(glob.glob(os.path.join(_REPO_ROOT, 'formazione_*', 'output', '*_gk_all'))):
        champ_dir = os.path.basename(os.path.dirname(os.path.dirname(consiglio_dir)))
        league = champ_dir[len('formazione_'):]
        prefix = os.path.basename(consiglio_dir)[:-len('_gk_all')]
        dirs = {r: os.path.join(champ_dir, 'output', f'{prefix}_{r.lower()}_all') for r in ROLES}
        disc = {r: os.path.join(champ_dir, 'output', f'{prefix}_{r.lower()}_discovery') for r in ROLES}
        if all(os.path.isdir(os.path.join(_REPO_ROOT, d)) for d in dirs.values()):
            found[league] = (dirs, disc)
    return found


_DISCOVERED = _discover_leagues()
LEAGUES = tuple(sorted(_DISCOVERED))
CONSIGLIO_DIRS = {lg: v[0] for lg, v in _DISCOVERED.items()}
DISCOVERY_DIRS = {lg: v[1] for lg, v in _DISCOVERED.items()}

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
    if not raw:
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


def build_one_lineup_with_growth(shape, pool_league, role_data, pools, card_pool, l10_cap,
                                  apply_stack_guard, variance_mode, apply_positive_synergy=True,
                                  strict_gk_anti_synergy=False, used_matches=None):
    """Se il tipo ha un cap L10 obbligatorio (Arena dedicate/All Stars) usa
    il pool GREZZO via _raw_view_for; altrimenti (In Season, All Stars, Arena
    All Stars uncapped) passa da 'pools' (_view_for) -- dal 28/07 entrambi i
    percorsi vedono comunque TUTTI i candidati scoperti, perche' il filtro
    qualita' e' disattivato (vedi _NoFilterPool): la distinzione resta solo
    per come 'pools' viene fatto crescere/riletto, non piu' per COSA include."""
    if l10_cap is not None:
        role_data_view = {role: _raw_view_for(role_data, pool_league, role) for role in ROLES}
        return bff.build_one_lineup(shape, role_data_view, card_pool, l10_cap=l10_cap,
                                     apply_stack_guard=apply_stack_guard, variance_mode=variance_mode,
                                     apply_positive_synergy=apply_positive_synergy,
                                     strict_gk_anti_synergy=strict_gk_anti_synergy, used_matches=used_matches)

    while True:
        role_data_view = {role: _view_for(pools, pool_league, role) for role in ROLES}
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

    def _run(force_first):
        # Varianza capitano (27/07, richiesta esplicita utente, stesso fix
        # identico nei due tool singoli): scope per tipo (uno degli 8 qui).
        captained_slugs = set()
        # Decorrelazione tra le N formazioni In Season -- DISATTIVATA (28/07 sera,
        # richiesta esplicita utente): il meccanismo (MATCH_REUSE_PENALTY in
        # build_formazione_finale.py) e' implementato ma MAI misurato su dati
        # reali, e la penalita' soft e' comunque enorme rispetto ai punteggi
        # reali (rischia di escludere giocatori nettamente piu' forti solo per
        # decorrelare). In BACKLOG: testare con un backtest prima di riattivare
        # (basta rimettere `set() if in_season_multi else None` sotto).
        used_matches = None

        risultati = []
        for idx in range(1, count + 1):
            strict_gk_anti_synergy = in_season_multi
            apply_positive_synergy = not in_season_multi or idx == 1
            idx_cap = 370.0 if (force_first and idx == 1) else cap
            formazione, error, l10_ok, stack_perso = build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, idx_cap, stack_guard, variance_mode,
                apply_positive_synergy, strict_gk_anti_synergy, used_matches)
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


_slot_role = bff._slot_role  # canonico, condiviso col drag&drop lato pcard


def _build_alt_chips(formazione, label, idx, global_usage, max_chips=6):
    """Per ogni SLOT della formazione, cerca alternative dello stesso ruolo
    usate in ALTRE formazioni (qualunque tipo) con punteggio atteso vicino
    (28/07, richiesta esplicita utente: "un attaccante con 57, alternative
    con 55/54"). Round-robin per slot (non un top-N globale per vicinanza):
    altrimenti uno slot puo' restare senza alcuna alternativa se un altro
    ruolo nella stessa formazione ha piu' candidati vicini (bug trovato nella
    prima versione con un top-4 flat, mai arrivato in produzione). Ritorna al
    massimo max_chips dict {row, ctype, role}, deduplicati per slug -- la riga
    completa (non solo lo score) serve al drag&drop per costruire in anticipo
    l'HTML della pcard che l'alternativa diventerebbe se trascinata."""
    seen_slugs = {row['slug'] for _, row, _ in formazione}
    per_slot = []
    for slot, row, _ctype in formazione:
        role = _slot_role(slot)
        if not role:
            continue
        own_score = row['atteso']
        cands = sorted(
            ((abs(u['row']['atteso'] - own_score), u)
             for u in global_usage.get(role, ())
             if (u['label'], u['idx']) != (label, idx) and u['row']['slug'] not in seen_slugs),
            key=lambda t: t[0])
        per_slot.append(cands)

    picked, picked_slugs = [], set()
    exhausted = False
    while len(picked) < max_chips and not exhausted:
        exhausted = True
        for cands in per_slot:
            while cands:
                _diff, u = cands.pop(0)
                slug = u['row']['slug']
                if slug in picked_slugs:
                    continue
                picked_slugs.add(slug)
                picked.append({'row': u['row'], 'ctype': u['ctype'], 'role': u['role']})
                exhausted = False
                break
            if len(picked) >= max_chips:
                break
    return picked


def _render_alt_panel(chips, card_pool):
    """Ogni chip e' draggable e porta con se' data-body gia' pronto (28/07):
    il drag&drop lato client (script nel template condiviso, vedi bff) scambia
    l'attributo con quello della pcard bersaglio senza ricalcolare nulla."""
    if not chips:
        return ''
    items = []
    for chip in chips:
        row, ctype, role = chip['row'], chip['ctype'], chip['role']
        slug = row['slug']
        name = card_pool.display_name(slug)
        copie = card_pool.copies_owned(slug)
        tags_html = bff._pcard_tags_html(ctype, copie)
        l10 = card_pool.l10(slug)
        body_html = bff._pcard_body_html(slug, row['atteso'], row['low'], row['high'], l10, tags_html, card_pool)
        items.append(
            '<div class="alt-chip" draggable="true" '
            f'data-slug="{html.escape(slug, quote=True)}" data-role="{role or ""}" '
            f'data-score="{row["atteso"]}" data-name="{html.escape(name, quote=True)}" '
            f'data-body="{html.escape(body_html, quote=True)}">'
            f'<div class="alt-circle">{bff._slug_initials(slug)}</div>'
            f'<div class="alt-info"><div class="alt-name">{name}</div>'
            f'<div class="alt-score">{row["atteso"]} pt · {role}</div></div>'
            '</div>'
        )
    return (
        '<div class="alt-panel">'
        '<div class="alt-panel-title">Alternative (vicinanza punteggio,<br>da altre formazioni) — '
        'trascina per sostituire</div>'
        f'<div class="alt-list">{"".join(items)}</div>'
        '</div>'
    )


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

    # Indice globale: ruolo -> [{row, ctype, role, label, idx}, ...] su TUTTE
    # le formazioni di TUTTI i tipi (28/07) -- usato per proporre alternative
    # per vicinanza di punteggio, cross-formazione/cross-tipo. La riga
    # completa (non solo lo score) serve al drag&drop per ricostruire l'HTML
    # esatto della pcard che l'alternativa diventerebbe se trascinata.
    global_usage = defaultdict(list)
    for r in all_results:
        if 'error' in r:
            continue
        for slot, row, ctype in r['formazione']:
            role = _slot_role(slot)
            if role:
                global_usage[role].append(
                    {'row': row, 'ctype': ctype, 'role': role, 'label': r['label'], 'idx': r['idx']})

    # FASE 2: rendering, con il pannello alternative a fianco di ogni formazione.
    lineup_html_blocks = []
    for r in all_results:
        if 'error' in r:
            lineup_html_blocks.append(f'<p class="error-block">{r["error"]}</p>')
            continue
        lineup_html = bff.render_lineup_html(
            r['label'], r['idx'], r['formazione'], card_pool, l10_cap=r['l10_cap'],
            l10_cap_rispettato=r['l10_ok'], stack_bonus_perso=r['stack_perso'],
            check_cap260=r['check_cap260'], tipo=r['tipo'], apply_stack_guard=r['stack_guard'],
            avoid_captain_slugs=r['avoid_captain_slugs'])
        chips = _build_alt_chips(r['formazione'], r['label'], r['idx'], global_usage)
        alt_panel = _render_alt_panel(chips, card_pool)
        lineup_html_blocks.append(f'<div class="lineup-row">{lineup_html}{alt_panel}</div>')

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
    html_text = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_path = os.path.join(OUTPUT_DIR, f'generatore_formazioni{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"\nReport visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
