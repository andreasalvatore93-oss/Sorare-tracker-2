"""
build_formazione_finale.py

Fusione finale: legge l'ultimo consiglio_<timestamp>.txt gia' prodotto da
ciascuno dei 4 ruoli (mls_fwd_all/, mls_mid_all/, mls_def_all/, mls_gk_all/,
gia' generati dai rispettivi workflow di produzione discover->predict->merge)
e ne ricava fino a N formazioni ottimali per TRE tipi di competizione Sorare
diversi (26/07, seconda sessione, richiesta esplicita dell'utente):

- **IN SEASON** (quella storica, gia' in produzione): 1 GK, 1 DEF, 1 MID,
  1 FWD, 1 EXTRA (DEF/MID/FWD) — max 1 carta CLASSIC per formazione.
- **ARENA**: stessa struttura a 5 slot delle In Season, ma SENZA vincolo
  classic (possono essere tutte classic, non obbligatorio ma possibile).
  Supporta un tuning opzionale: cap sulla L10 combinata dei 5 giocatori
  (vedi ARENA_L10_CAP sotto).
- **ALL STARS**: 7 giocatori, struttura CONFERMATA dall'utente (26/07):
  1 GK, 2 DEF, 2 MID, 1 FWD, 1 EXTRA (DEF/MID/FWD) — nessun vincolo classic.

Nessuna chiamata GraphQL: puramente locale sui file gia' committati, quindi
istantaneo. Va rilanciato dopo ogni aggiornamento dei consigli di ruolo per
restare aggiornato (i file consiglio_*.txt piu' recenti per cartella sono
sempre quelli usati).

REGOLA "MAX 1 CLASSIC PER FORMAZIONE" (SOLO In Season, 25/07):
Le discovery di ruolo scansionano SIA carte IN_SEASON che CLASSIC, e
player_card_counts.json riporta le copie possedute separate per tipo
({'in_season': n, 'classic': m, 'l10': x}). LA SCELTA DEL GIOCATORE PER OGNI
SLOT E' GUIDATA SOLO DALLO SCORE ATTESO, MAI DAL TIPO DI CARTA: si scorre la
classifica del ruolo (gia' ordinata per score decrescente) e si prende il
primo giocatore disponibile, sia la sua carta migliore IN_SEASON o CLASSIC —
un giocatore col punteggio piu' alto viene scelto anche se posseduto SOLO in
classic. Il tipo di carta entra in gioco unicamente per decidere QUALE copia
dello stesso giocatore consumare: si consuma prima la copia IN_SEASON
(irrilevante per lo score, ma preserva l'eventuale slot CLASSIC per un altro
giocatore che ne ha davvero bisogno). Per Arena/All Stars questo vincolo non
esiste: qualunque copia disponibile (in_season o classic) viene consumata
liberamente, sempre iniziando da in_season per coerenza.

PRIORITA' TRA TIPI (26/07, richiesta esplicita dell'utente):
I 3 tipi condividono lo STESSO pool di giocatori posseduti (CardPool), quindi
generarli in ordine di priorita' IN SEASON -> ARENA -> ALL STARS fa si' che,
se il pool si esaurisce, siano naturalmente le formazioni meno prioritarie
(prima All Stars, poi Arena) a non essere completate — mai le In Season.
Ogni tipo puo' essere messo a 0 per disattivarlo del tutto. Il totale
richiesto (NUM_TOTALE_FORMAZIONI) deve combaciare ESATTAMENTE con la somma
dei 3 sotto-totali, altrimenti lo script si ferma subito (fail-fast, non
tronca silenziosamente).

TUNING ARENA_L10_CAP (26/07, richiesta esplicita dell'utente):
Se impostato (env ARENA_L10_CAP, es. "260"), le formazioni Arena vengono
generate rispettando un tetto sulla somma delle L10 (media ultime 10 partite
GIOCATE, LAST_TEN_PLAYED_SO5_AVERAGE_SCORE) dei 5 giocatori schierati -- non
solo il punteggio atteso piu' alto in assoluto, ma il migliore CHE rispetta
il tetto. Implementato come euristica greedy con budget residuo (non un
knapsack esatto): ad ogni slot si sceglie il miglior candidato la cui L10
(0 se mancante, permissivo) non fa sforare il budget rimasto; se nessun
candidato rispetta il budget, si prende quello con L10 piu' bassa disponibile
e la formazione viene segnalata come "budget L10 non rispettato" in output
(limite noto, non blocca la generazione). L10 mancante non esclude MAI un
giocatore (stesso principio di sicurezza degli altri filtri del progetto).

LOGICA MULTI-FORMAZIONE PER TIPO:
Un giocatore usato in una lineup (di qualunque tipo) NON puo' essere riusato
in una lineup successiva, A MENO CHE non si possiedano piu' copie della sua
carta (ogni copia, in_season o classic, e' un utilizzo possibile in una
lineup diversa, anche di tipo diverso). Se un ruolo esaurisce i candidati
disponibili prima di raggiungere il numero richiesto PER QUEL TIPO, la
generazione di quel tipo si ferma li' e lo segnala, ma si prosegue comunque
con il tipo successivo in ordine di priorita' (il pool residuo potrebbe
ancora bastare, essendo strutture/vincoli diversi).

Se player_card_counts.json non esiste ancora per un ruolo, si assume 1 copia
IN_SEASON di default (0 classic, L10 sconosciuta) per ogni giocatore di quel
ruolo non presente nel file.
"""
import os
import re
import sys
import glob
import html
import json
import datetime

ROLES = {
    'GK': 'formazione_mls/output/mls_gk_all',
    'DEF': 'formazione_mls/output/mls_def_all',
    'MID': 'formazione_mls/output/mls_mid_all',
    'FWD': 'formazione_mls/output/mls_fwd_all',
}

DISCOVERY_DIRS = {
    'GK': 'formazione_mls/output/mls_gk_discovery',
    'DEF': 'formazione_mls/output/mls_def_discovery',
    'MID': 'formazione_mls/output/mls_mid_discovery',
    'FWD': 'formazione_mls/output/mls_fwd_discovery',
}

OUTPUT_DIR = 'formazione_mls/output'

CONSIGLIO_LINE_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')
# NUOVO (26/07, tema correlazione GK-DEF): riga "SQUADRA: x | AVVERSARIO: y"
# scritta subito dopo la riga consiglio da build_consiglio_<ruolo>.py.
TEAM_RE = re.compile(r'^SQUADRA:\s+(\S+)\s+\|\s+AVVERSARIO:\s+(\S+)\s*$')
# NUOVO (27/07): calcio d'inizio della partita target, scritto da
# build_consiglio_<ruolo>.py. Serve a scartare chi NON gioca nella giornata per
# cui si schiera (partita gia' giocata o fra giorni).
KICKOFF_RE = re.compile(r'^KICKOFF:\s+(\S+)\s*$')
# NUOVO (27/07, sezione 27.C del RIASSUNTO): score di ordinamento senza
# shrinkage, scritto da build_consiglio_<ruolo>.py. Serve SOLO a ordinare i
# pool; i punti mostrati/sommati restano 'atteso'. Riga opzionale: sui
# consigli generati prima si continua a ordinare per 'atteso'.
ORDINAMENTO_RE = re.compile(r'^ORDINAMENTO:\s+(-?[\d.]+)\s*$')

DEFAULT_NUM_FORMAZIONI = 1

# --- Strutture dei 3 tipi di formazione (26/07, seconda sessione) ----------
# 'role_slots': un elemento per slot obbligatorio (ripetuto se servono piu'
# giocatori dello stesso ruolo, es. 2x DEF in All Stars).
# 'extra_roles': ruoli ammessi per lo slot EXTRA finale (stesso per tutti e 3).
# 'max_classic': None = nessun vincolo, 1 = max 1 carta classic per formazione.
FORMATION_SHAPES = {
    'IN_SEASON': {
        'label': 'In Season',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': 1,
    },
    # 3 varianti Arena (26/07, richiesta esplicita): stessa struttura a 5
    # slot, cambia solo il cap FISSO sulla L10 combinata -- sono modalita'
    # Sorare distinte, generabili tutte nello stesso run. Priorita' interna
    # tra le tre: cap260 -> cap220 -> uncapped (vedi loop in main()).
    'ARENA_260': {
        'label': 'Arena (cap 260)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ARENA_220': {
        'label': 'Arena (cap 220)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ARENA_UNCAPPED': {
        'label': 'Arena (uncapped)',
        'role_slots': ['GK', 'DEF', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
    'ALLSTARS': {
        'label': 'All Stars',
        'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'],
        'extra_roles': ['DEF', 'MID', 'FWD'],
        'max_classic': None,
    },
}

# Sinergia/anti-sinergia GK vs giocatori di movimento (26/07, tema
# correlazione): se il portiere di Squadra A gioca contro Squadra B, un gol
# subito dalla Squadra B gli toglie il bonus clean sheet -- quindi schierare
# insieme un MID/FWD di Squadra B e' fortemente scoraggiato (l'attaccante
# potrebbe comunque prendere un buon voto, ma e' una combinazione meno
# sensata quando ci sono molte alternative). Per i difensori vale l'opposto,
# piu' debole: schierare GK+DEF della STESSA squadra e' incoraggiato ma non
# obbligatorio (uno 0-0 capita, non e' vietato l'avversario). Implementato
# come riordino dei candidati (penalita'/bonus sul punteggio SOLO per
# l'ordine di scelta, il punteggio REALE mostrato in output resta quello
# originale) -- MAI un'esclusione assoluta, sempre "ultima risorsa" se non
# ci sono alternative valide (richiesta esplicita dell'utente).
ANTI_SYNERGY_PENALTY = 10_000  # abbastanza grande da finire sempre in fondo alla classifica di scelta
POSITIVE_SYNERGY_BONUS = 3  # piccolo nudge, non ribalta differenze di punteggio importanti

# Bonus anti-stack Sorare (26/07, scoperto dall'utente per In Season, CONFERMATO
# valido anche per All Stars il 26/07 sera -- stessa soglia, non scalata a 7
# giocatori): se una formazione ha MENO di 3 giocatori della stessa squadra,
# ogni giocatore riceve +2% al proprio punteggio; con 3+ della stessa squadra
# il bonus salta per TUTTI (5 In Season, 7 All Stars). La sinergia GK+DEF
# sopra, da sola, porta al massimo a 2 giocatori della stessa squadra (GK + 1
# DEF titolare) -- nessun conflitto, resta "gratis". Il conflitto nasce solo
# se un ALTRO slot (tipicamente l'extra) porterebbe una squadra al 3o
# giocatore: li' il costo e' certo (-2% su tutti) mentre il beneficio di
# correlazione e' incerto, quindi di default scoraggiamo (non vietiamo: a
# volte, es. capolista contro ultima, puo' valere la pena sacrificare il
# bonus per un punteggio quasi certo -- scelta che spetta all'utente, non
# all'algoritmo) il 3o giocatore della stessa squadra. Applicato per In
# Season e All Stars (apply_stack_guard): Arena NON ha questo bonus (ha il
# suo cap L10 obbligatorio separato, nessuna % aggiuntiva).
IN_SEASON_STACK_LIMIT = 2
STACK_GUARD_PENALTY = 8_000  # come ANTI_SYNERGY_PENALTY: spinge in fondo, non esclude

# Sinergia da correlazione misurata, SOLO Arena/All Stars (27/07, tema
# "correlazione slot formazione" del backlog, vedi diagnostics/
# measure_teammate_correlation.py). Prima di questo tuning i nudge sopra
# (POSITIVE_SYNERGY_BONUS/ANTI_SYNERGY_PENALTY) erano intuizione mai
# misurata. Il residuo walk-forward (reale - baseline media/venue/trend) di
# compagni di squadra nella STESSA partita, sulle cache di calibrazione
# GK/DEF/MID/FWD, mostra correlazioni positive robuste (permutation test
# p<0.05, segno stabile split-half): GK-DEF +0.40 (la piu' forte, gia'
# modellata sopra ma sottostimata), DEF-MID +0.27, GK-MID +0.26, DEF-DEF
# +0.23. FWD non mostra correlazione same-team significativa con nessun
# ruolo (ne' come sinergia ne' come anti-sinergia) e resta fuori da questi
# nudge. Perche' SOLO Arena/All Stars: in In Season il target e' fisso, il
# valore atteso della somma non dipende dalla correlazione (Finding 3+F,
# chiuso), quindi spingere la scelta verso compagni correlati costerebbe
# valore atteso reale senza alcun beneficio -- il beneficio esiste solo dove
# la varianza conta (taglio premi Arena 30%/All Stars 5%). Valori scalati
# ~20x la correlazione misurata (stessa logica di "piccolo nudge" di
# POSITIVE_SYNERGY_BONUS, non un'esclusione).
GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA = 8  # extra oltre POSITIVE_SYNERGY_BONUS, per un totale di 11 in Arena/All Stars (corr +0.40)
TEAMMATE_SYNERGY_BONUS_VARIANCE = 5  # GK-MID stessa squadra (corr +0.26) o DEF/MID che raggiunge un compagno gia' scelto (corr +0.23/+0.27)

# Decorrelazione tra le N formazioni In Season (28/07, sez. 29.D/tema
# "portafoglio": il premio scatta se ALMENO UNA delle N formazioni supera il
# target di giornata, non sulla media -- quindi le N formazioni rendono di piu'
# se sono tentativi il piu' possibile INDIPENDENTI. Se piu' formazioni
# condividono la stessa partita reale (stessa coppia squadra-avversario) e
# quella partita va male, falliscono insieme: nessun vantaggio dai tentativi
# multipli). Soft, come ANTI_SYNERGY_PENALTY/STACK_GUARD_PENALTY: deprioritizza
# (non esclude mai) i candidati la cui partita e' gia' "occupata" da una
# formazione precedente della stessa serie. Piu' debole dello stack guard
# (8_000): se non ci sono alternative valide nello slot, meglio riusare la
# partita che perdere il bonus anti-stack o rompere lo schieramento.
MATCH_REUSE_PENALTY = 6_000


def _match_key(row):
    team = row.get('team_slug')
    opponent = row.get('opponent_team_slug')
    if not team or not opponent:
        return None
    return frozenset((team, opponent))


def synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                      variance_mode=False, apply_positive_synergy=True, used_matches=None):
    """Punteggio AGGIUSTATO solo per decidere l'ORDINE di scelta tra candidati
    dello stesso ruolo, dato il portiere gia' selezionato per questa lineup.
    Non altera mai 'atteso' nel dict originale (usato per punteggio/range in
    output) -- vedi commento sopra ANTI_SYNERGY_PENALTY per la logica.
    'team_counts'/'apply_stack_guard': vedi commento sopra IN_SEASON_STACK_LIMIT.
    'variance_mode': vedi commento sopra GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA
    (SOLO Arena/All Stars -- generate_lineups_for_type decide il valore).
    'apply_positive_synergy' (27/07, richiesta esplicita utente per le In
    Season con 2+ formazioni richieste): gate UNICO sia per il bonus DEF-GK
    (POSITIVE_SYNERGY_BONUS) sia per la penalita' soft MID/FWD-vs-avversario
    (ANTI_SYNERGY_PENALTY) -- quest'ultima e' comunque superata da un filtro
    DURO in build_one_lineup quando serve (strict_gk_anti_synergy), quindi qui
    resta solo per il caso in cui il filtro duro non e' attivo (Arena/All
    Stars, o In Season con una sola formazione richiesta, comportamento
    INVARIATO rispetto a prima). Se False (formazioni "greedy" #2..N delle In
    Season multiple), niente bonus/penalita' di correlazione: solo punteggio
    grezzo -- il vincolo di schieramento resta comunque garantito dal filtro
    duro, applicato a monte, non da qui."""
    adjusted = row['atteso']
    team_slug = row.get('team_slug')
    if apply_positive_synergy:
        if role in ('MID', 'FWD') and gk_opponent_slug and team_slug == gk_opponent_slug:
            adjusted -= ANTI_SYNERGY_PENALTY
        elif role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
            adjusted += POSITIVE_SYNERGY_BONUS
    if variance_mode and team_slug:
        if role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
            adjusted += GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA
        elif role == 'MID' and gk_team_slug and team_slug == gk_team_slug:
            adjusted += TEAMMATE_SYNERGY_BONUS_VARIANCE
        # FWD-MID same-team (27/07 notte, reindagine su 6 campionati invece
        # di 2: corr +0.161 p=0.005, stabile split-half -- prima era marginale
        # su MLS+K League soli, +0.106/+0.147 p=0.076-0.17, non modellato):
        # stesso nudge piccolo gia' usato per DEF/MID, non un fattore nuovo.
        elif role in ('DEF', 'MID', 'FWD') and team_counts and team_counts.get(team_slug, 0) >= 1:
            adjusted += TEAMMATE_SYNERGY_BONUS_VARIANCE
    if apply_stack_guard and team_slug and team_counts and team_counts.get(team_slug, 0) >= IN_SEASON_STACK_LIMIT:
        adjusted -= STACK_GUARD_PENALTY
    if used_matches and _match_key(row) in used_matches:
        adjusted -= MATCH_REUSE_PENALTY
    return adjusted


def synergy_adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                           variance_mode=False, apply_positive_synergy=True, used_matches=None):
    """Ritorna i candidati di un ruolo di movimento riordinati per sinergia/
    anti-sinergia col portiere scelto (vedi synergy_sort_key), la sinergia
    da correlazione misurata (SOLO variance_mode) ed eventualmente per il
    vincolo anti-stack In Season/All Stars. Se il portiere non ha
    squadra/avversario noti (consiglio generato prima di questo
    aggiornamento, o dato di calendario mancante) e non c'e' ne' vincolo
    anti-stack ne' variance_mode ne' sinergia positiva da applicare, non
    cambia nulla -- comportamento identico a prima."""
    if (not apply_stack_guard and not variance_mode
            and not (apply_positive_synergy and (gk_team_slug or gk_opponent_slug))
            and not used_matches):
        return rows
    return sorted(rows, key=lambda row: synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug,
                                                           team_counts, apply_stack_guard, variance_mode,
                                                           apply_positive_synergy, used_matches),
                  reverse=True)


def _read_int_env(name, default):
    val = os.environ.get(name)
    if val is None or val.strip() == '':
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_formation_counts():
    """Legge i 4 parametri di conteggio formazioni (26/07, seconda sessione):
    NUM_TOTALE_FORMAZIONI, NUM_FORM_IN_SEASON, NUM_FORM_ARENA,
    NUM_FORM_ALLSTARS -- da env var (input workflow_dispatch). Ognuno dei 3
    sotto-totali puo' essere 0 (tipo disattivato). Compatibilita' locale:
    se nessuna delle 4 env var e' impostata, ricade sul vecchio singolo
    argomento CLI/env NUM_FORMAZIONI (comportamento pre-26/07: tutte In
    Season). FAIL-FAST: il totale deve combaciare esattamente con la somma
    dei 3 sotto-totali, altrimenti SystemExit prima di fare qualunque cosa."""
    has_new_inputs = any(
        os.environ.get(k) not in (None, '')
        for k in ('NUM_TOTALE_FORMAZIONI', 'NUM_FORM_IN_SEASON', 'NUM_FORM_ARENA_260',
                   'NUM_FORM_ARENA_220', 'NUM_FORM_ARENA_UNCAPPED', 'NUM_FORM_ALLSTARS')
    )
    if not has_new_inputs:
        # Vecchio comportamento (pre-26/07): un solo numero, tutte In Season.
        n = DEFAULT_NUM_FORMAZIONI
        if len(sys.argv) > 1:
            try:
                candidate = int(sys.argv[1])
                if candidate >= 1:
                    n = candidate
            except ValueError:
                pass
        else:
            env_val = os.environ.get('NUM_FORMAZIONI')
            if env_val:
                try:
                    candidate = int(env_val)
                    if candidate >= 1:
                        n = candidate
                except ValueError:
                    pass
        return {'IN_SEASON': n, 'ARENA_260': 0, 'ARENA_220': 0, 'ARENA_UNCAPPED': 0, 'ALLSTARS': 0}, n

    num_totale = _read_int_env('NUM_TOTALE_FORMAZIONI', 0)
    num_in_season = _read_int_env('NUM_FORM_IN_SEASON', 0)
    num_arena_260 = _read_int_env('NUM_FORM_ARENA_260', 0)
    num_arena_220 = _read_int_env('NUM_FORM_ARENA_220', 0)
    num_arena_uncapped = _read_int_env('NUM_FORM_ARENA_UNCAPPED', 0)
    num_allstars = _read_int_env('NUM_FORM_ALLSTARS', 0)

    somma = num_in_season + num_arena_260 + num_arena_220 + num_arena_uncapped + num_allstars
    if num_totale != somma:
        raise SystemExit(
            f"ERRORE: NUM_TOTALE_FORMAZIONI={num_totale} non combacia con la somma dei tipi "
            f"(In Season={num_in_season} + Arena cap260={num_arena_260} + Arena cap220={num_arena_220} + "
            f"Arena uncapped={num_arena_uncapped} + All Stars={num_allstars} = {somma}). "
            f"Correggi gli input del workflow -- nessuna formazione generata."
        )

    return {'IN_SEASON': num_in_season, 'ARENA_260': num_arena_260, 'ARENA_220': num_arena_220,
            'ARENA_UNCAPPED': num_arena_uncapped, 'ALLSTARS': num_allstars}, num_totale


def latest_consiglio(output_dir):
    matches = sorted(glob.glob(os.path.join(output_dir, 'consiglio_*.txt')))
    return matches[-1] if matches else None


def parse_consiglio(path):
    """Ritorna lista ordinata di dict {slug, atteso, low, high, team_slug,
    opponent_team_slug} nell'ordine gia' presente nel file (score decrescente,
    come prodotto da build_consiglio_<ruolo>.py). team_slug/opponent_team_slug
    sono None se assenti (consiglio generato prima del 26/07, o dato di
    calendario "N/D") -- retrocompatibile, la logica di sinergia si disattiva
    automaticamente in quel caso."""
    rows = []
    pending = None
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            m = CONSIGLIO_LINE_RE.match(stripped)
            if m:
                if pending:
                    rows.append(pending)
                slug, atteso, low, high = m.groups()
                pending = {'slug': slug, 'atteso': int(atteso), 'low': int(low), 'high': int(high),
                           'team_slug': None, 'opponent_team_slug': None, 'ordinamento': None,
                           'kickoff': None}
                continue
            m = ORDINAMENTO_RE.match(stripped)
            if m and pending:
                pending['ordinamento'] = float(m.group(1))
                continue
            m = KICKOFF_RE.match(stripped)
            if m and pending:
                pending['kickoff'] = m.group(1)
                continue
            m = TEAM_RE.match(stripped)
            if m and pending:
                team_slug, opp_slug = m.groups()
                pending['team_slug'] = None if team_slug == 'N/D' else team_slug
                pending['opponent_team_slug'] = None if opp_slug == 'N/D' else opp_slug
        if pending:
            rows.append(pending)
    return rows


def load_card_counts(discovery_dir):
    """Carica slug -> {'in_season': n, 'classic': m, 'l10': x|None}, da
    player_card_counts.json. Se il file non esiste (discovery mai lanciata
    dopo l'aggiornamento che ha aggiunto questi campi), ritorna un dict
    vuoto: il chiamante assumera' 1 copia IN_SEASON di default (L10 ignota)
    per ogni giocatore non presente."""
    path = os.path.join(discovery_dir, 'player_card_counts.json')
    if not os.path.exists(path):
        return {}, path
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), path
    except (json.JSONDecodeError, OSError):
        return {}, path


def load_player_names(discovery_dir):
    """Carica slug -> displayName reale Sorare da player_names.json (scritto
    da discovery_fixture.py, 28/07). Se il file non esiste (discovery non
    ancora aggiornata) ritorna {}: il chiamante ripiega sullo slug title-case
    come faceva prima di questa data."""
    path = os.path.join(discovery_dir, 'player_names.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_all_roles():
    role_data = {}
    role_files = {}
    role_counts = {}
    counts_files = {}
    for role, out_dir in ROLES.items():
        path = latest_consiglio(out_dir)
        role_files[role] = path
        role_data[role] = parse_consiglio(path) if path else []

        counts, counts_path = load_card_counts(DISCOVERY_DIRS[role])
        role_counts[role] = counts
        counts_files[role] = counts_path if os.path.exists(counts_path) else None
    return role_data, role_files, role_counts, counts_files


class CardPool:
    """Traccia quante copie IN_SEASON e CLASSIC di ogni giocatore restano
    disponibili, attraverso TUTTE le formazioni generate in questa run
    (di qualunque tipo — In Season, Arena, All Stars condividono lo stesso
    pool). Default: 1 copia IN_SEASON (0 classic, L10 ignota) per uno slug
    non presente nel relativo player_card_counts.json."""

    def __init__(self, counts_by_role, names=None):
        self._total = {}
        self._l10 = {}
        self._power = {}
        for role, counts in counts_by_role.items():
            for slug, breakdown in counts.items():
                cur = self._total.setdefault(slug, {'in_season': 0, 'classic': 0})
                cur['in_season'] = max(cur['in_season'], breakdown.get('in_season', 0))
                cur['classic'] = max(cur['classic'], breakdown.get('classic', 0))
                l10 = breakdown.get('l10')
                if l10 is not None:
                    self._l10[slug] = l10
                power = breakdown.get('power')
                if power is not None:
                    self._power[slug] = power
        self._names = names or {}
        self._used = {}

    def display_name(self, slug):
        """displayName reale Sorare se noto (da player_names.json, vedi
        load_player_names), altrimenti ripiega sullo slug title-case."""
        return self._names.get(slug) or _slug_display_name(slug)

    def _total_for(self, slug):
        return self._total.get(slug, {'in_season': 1, 'classic': 0})

    def _used_for(self, slug):
        return self._used.get(slug, {'in_season': 0, 'classic': 0})

    def remaining_in_season(self, slug):
        return self._total_for(slug)['in_season'] - self._used_for(slug)['in_season']

    def remaining_classic(self, slug):
        return self._total_for(slug)['classic'] - self._used_for(slug)['classic']

    def copies_owned(self, slug):
        t = self._total_for(slug)
        return t['in_season'] + t['classic']

    def use(self, slug, card_type):
        u = self._used.setdefault(slug, {'in_season': 0, 'classic': 0})
        u[card_type] += 1

    def l10(self, slug):
        """L10 (media ultime 10 partite giocate) nota per slug, o None se
        mai persistita (dato mancante -- vedi ARENA_L10_CAP, trattata come 0
        nel calcolo del budget, mai come esclusione)."""
        return self._l10.get(slug)

    def power_bonus_fraction(self, slug):
        """Somma dei basis points del powerBreakdown Sorare (season/collection/
        xp/scarcity/special edition/active clubs/nationality/positions) per
        slug, come frazione (es. 1000 basis points -> 0.10). 0.0 se il dato
        non e' stato raccolto (giocatore mai visto in una CARDS_QUERY, o
        senza carta con bonus noto) -- MAI un'esclusione, solo nessun
        moltiplicatore extra. Il chiamante decide se applicarla (28/07:
        SOLO In Season/All Stars 7/Under 23, mai nelle Arene, confermato
        dall'utente -- vedi XP_BONUS_TYPES in build_formazione_globale.py)."""
        pb = self._power.get(slug)
        if not pb:
            return 0.0
        return sum(v or 0 for k, v in pb.items() if k.endswith('_bp')) / 10000.0

    def used_slugs(self):
        """Slug con almeno una copia consumata in una qualunque formazione
        di questa run (di qualunque tipo -- il pool e' condiviso)."""
        return {slug for slug, u in self._used.items()
                if u['in_season'] > 0 or u['classic'] > 0}


def _min_available_l10(rows, used_slugs, card_pool):
    """Minimo L10 (mancante trattato come 0.0, permissivo) tra i candidati di
    'rows' NON ancora usati in questa lineup -- usato per riservare budget ai
    prossimi slot quando l10_cap e' attivo (27/07, fix di un difetto reale:
    senza riserva, i primi slot potevano spendere tutto il budget sui
    punteggi migliori, lasciando lo slot EXTRA finale sempre sforato perche'
    mai processato con budget residuo garantito)."""
    vals = [card_pool.l10(r['slug']) or 0.0 for r in rows if r['slug'] not in used_slugs]
    return min(vals) if vals else 0.0


def _pareto_frontier(rows, card_pool):
    """Candidati disponibili (almeno una copia posseduta) ordinati per L10
    crescente, tenendo solo quelli che migliorano il punteggio rispetto a
    TUTTI i candidati piu' economici gia' inclusi (frontiera di Pareto: mai
    utile scegliere un candidato piu' caro E con punteggio minore o uguale a
    uno gia' disponibile). Riduce drasticamente lo spazio di ricerca del
    knapsack sotto senza perdere nessuna soluzione ottima possibile."""
    avail = [(row, card_pool.l10(row['slug']) or 0.0) for row in rows
             if card_pool.remaining_in_season(row['slug']) > 0 or card_pool.remaining_classic(row['slug']) > 0]
    avail.sort(key=lambda x: x[1])
    frontier = []
    best = float('-inf')
    for row, l10 in avail:
        if row['atteso'] > best:
            frontier.append((row, l10))
            best = row['atteso']
    return frontier


def _optimize_capped_lineup(shape, role_data, card_pool, l10_cap):
    """Knapsack ESATTO sui 4 slot principali (GK/DEF/MID/FWD, un candidato
    ciascuno) per massimizzare il PUNTEGGIO TOTALE sotto l10_cap (27/07,
    richiesta esplicita utente: la vecchia euristica greedy-con-riserva
    rispettava il cap ma si accontentava della prima combinazione che
    entrava nel budget, non della migliore -- risultato: extra con punteggio
    anche di 14-26pt quando ne esistevano di molto migliori nello stesso
    budget). Prova OGNI possibile ripartizione di budget tra i 4 ruoli
    principali E lo slot EXTRA (miglior punteggio disponibile nel budget
    residuo, tra tutti i ruoli ammessi, mai lo stesso giocatore gia' scelto),
    non solo quella che spende piu' budget sui primi 4 -- cosi' trova il vero
    massimo del totale a 5 slot. SOLO valido per shape con un ruolo per slot
    (nessuna ripetizione, es. Arena) e max_classic=None (vero per tutti i
    tipi con cap L10 oggi, mai per In Season/All Stars che non hanno cap).
    Non incorpora i nudge di sinergia da correlazione (piccoli, +3/+11 --
    qui l'obiettivo e' il punteggio reale, non l'ordine di scelta). Ritorna
    (picks_dict {ruolo/EXTRA: row}, l10_totale) o (None, None) se nessuna
    combinazione e' possibile (pool esaurito per almeno un ruolo)."""
    RES = 10  # risoluzione: decimi di L10, gestisce valori con 1 decimale
    budget_units = int(round(l10_cap * RES))

    frontiers = {}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        f = _pareto_frontier(role_data[role], card_pool)
        if not f:
            return None, None
        frontiers[role] = f

    states = {0: (0.0, {})}
    for role in ('GK', 'DEF', 'MID', 'FWD'):
        new_states = {}
        for used, (score, picks) in states.items():
            for row, l10 in frontiers[role]:
                cost = int(round(l10 * RES))
                nb = used + cost
                if nb > budget_units:
                    continue
                ns = score + row['atteso']
                cur = new_states.get(nb)
                if cur is None or cur[0] < ns:
                    new_picks = dict(picks)
                    new_picks[role] = row
                    new_states[nb] = (ns, new_picks)
        if not new_states:
            return None, None
        states = new_states

    extra_candidates = []
    for role in shape['extra_roles']:
        for row, l10 in _pareto_frontier(role_data[role], card_pool):
            extra_candidates.append((role, row, l10))
    extra_candidates.sort(key=lambda x: -x[1]['atteso'])

    best_total = best_picks = best_extra = best_used = None
    for used, (score4, picks4) in states.items():
        used_slugs = {row['slug'] for row in picks4.values()}
        remaining = (budget_units - used) / RES
        chosen_extra = None
        for role, row, l10 in extra_candidates:
            if row['slug'] in used_slugs:
                continue
            if l10 <= remaining:
                chosen_extra = (role, row, l10)
                break
        if chosen_extra is None:
            continue
        total = score4 + chosen_extra[1]['atteso']
        if best_total is None or total > best_total:
            best_total = total
            best_picks = picks4
            best_extra = chosen_extra
            best_used = used / RES + chosen_extra[2]

    if best_picks is None:
        return None, None

    result = dict(best_picks)
    result['EXTRA'] = (best_extra[0], best_extra[1])
    return result, best_used


def _consume_pick(card_pool, slug):
    """Consuma una copia dello slug scelto dal knapsack: preferisce IN_SEASON
    se disponibile (stesso ordine di preferenza del vecchio greedy 'pick'),
    altrimenti CLASSIC -- valido solo dove max_classic e' None (unico caso in
    cui il knapsack e' applicabile, vedi build_one_lineup)."""
    if card_pool.remaining_in_season(slug) > 0:
        card_pool.use(slug, 'in_season')
        return 'in_season'
    card_pool.use(slug, 'classic')
    return 'classic'


def build_one_lineup(shape, role_data, card_pool, l10_cap=None, apply_stack_guard=False, variance_mode=False,
                      apply_positive_synergy=True, strict_gk_anti_synergy=False, used_matches=None):
    """Costruisce UNA formazione secondo 'shape' (uno dei FORMATION_SHAPES),
    tenendo conto delle copie gia' esaurite (card_pool) e del vincolo
    max_classic della shape (None = nessun vincolo). Se l10_cap e' impostato
    (SOLO Arena), sceglie ad ogni slot il miglior punteggio che rientra nel
    budget residuo MENO una riserva (somma dei minimi L10 disponibili per gli
    slot ancora da riempire, extra incluso) -- garantisce che il cap non
    venga MAI sforato: se a un certo slot nessun candidato rientra nemmeno
    riservando, la formazione fallisce con lo stesso errore di "candidato
    esaurito", nessun fallback che sfora in silenzio (27/07, fix di un
    difetto reale: prima i primi slot potevano spendere tutto il budget sui
    punteggi migliori, lasciando lo slot EXTRA finale sempre sforato).
    'apply_stack_guard' (SOLO In Season/All Stars, vedi
    commento sopra IN_SEASON_STACK_LIMIT): scoraggia (non vieta) il 3o
    giocatore della stessa squadra nello slot extra, per non perdere per
    errore il bonus anti-stack Sorare. 'variance_mode' (SOLO Arena/All Stars,
    vedi commento sopra GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA): rafforza la
    sinergia GK-DEF e aggiunge nudge GK-MID/DEF-MID/DEF-DEF basati sulla
    correlazione misurata. Ritorna (formazione, errore, l10_cap_rispettato,
    stack_bonus_perso); formazione e' una lista di tuple
    (slot_label, row, card_type). stack_bonus_perso e' True se la
    formazione finale ha comunque 3+ giocatori della stessa squadra
    (informativo, sempre False se apply_stack_guard=False).

    'apply_positive_synergy' / 'strict_gk_anti_synergy' (27/07, richiesta
    esplicita utente per le In Season con 2+ formazioni richieste): quando
    strict_gk_anti_synergy=True, i candidati MID/FWD della squadra
    AVVERSARIA del portiere vengono ESCLUSI del tutto (non solo
    deprioritizzati) da ogni slot (titolari ed extra) -- un vero vincolo di
    schieramento, mai piu' un'ultima risorsa. apply_positive_synergy=False
    disattiva anche il bonus soft DEF-GK (nessuna priorita' di sinergia,
    solo punteggio grezzo) -- usato per le formazioni "greedy" successive
    alla prima quando le In Season richieste sono 2+ (vedi
    generate_lineups_for_type). Con una sola In Season richiesta, o per
    Arena/All Stars, entrambi i flag restano ai default (comportamento
    INVARIATO rispetto a prima di questa modifica).

    Se il knapsack ESATTO e' applicabile (l10_cap impostato, un ruolo per
    slot senza ripetizioni, max_classic=None, nessuna sinergia da applicare
    -- vero oggi per le 3 Arene dedicate, MAI per In Season/All Stars che o
    non hanno cap o ripetono ruoli), lo usa al posto del vecchio greedy-con-
    riserva per il punteggio totale MASSIMO garantito sotto il cap (27/07,
    vedi _optimize_capped_lineup). Decisione presa con l'utente (27/07): il
    knapsack NON incorpora MAI i nudge di sinergia, anche se variance_mode=
    True viene passato (oggi lo e' sempre per le Arene, incluse quelle a
    cap) -- il cap L10 e' un vincolo duro con poco margine, l'utente ha
    scelto di privilegiare il punteggio grezzo massimo sotto quel vincolo
    piuttosto che un DP annidato che preservi anche la sinergia.
    apply_stack_guard e' invece sempre False per questi tipi oggi (mai
    passato True insieme a un l10_cap), quindi non c'e' scelta da fare li'."""
    role_slots = shape['role_slots']
    max_classic = shape['max_classic']
    can_use_knapsack = (
        l10_cap is not None
        and max_classic is None
        and not apply_stack_guard
        and len(role_slots) == len(set(role_slots))
        and set(role_slots) == {'GK', 'DEF', 'MID', 'FWD'}
    )
    if can_use_knapsack:
        result, _l10_total = _optimize_capped_lineup(shape, role_data, card_pool, l10_cap)
        if result is None:
            return (None,
                    "Nessun candidato disponibile per completare la formazione entro il cap L10 "
                    "(copie esaurite o pool insufficiente).",
                    True, False)
        picks = []
        for role in role_slots:
            row = result[role]
            ctype = _consume_pick(card_pool, row['slug'])
            picks.append((role, row, ctype))
        extra_role, extra_row = result['EXTRA']
        extra_ctype = _consume_pick(card_pool, extra_row['slug'])
        picks.append((f'EXTRA ({extra_role})', extra_row, extra_ctype))
        return picks, None, True, False

    used_this_lineup = set()
    classic_budget_used = [0]
    l10_used = [0.0]
    l10_cap_rispettato = [True]
    team_counts = {}

    def pick(pool_rows, role_slot_l10_check, reserve=0.0):
        """role_slot_l10_check: se l10_cap e' impostato, filtra i candidati
        rispettando il budget residuo (MENO 'reserve', la somma dei minimi
        L10 disponibili per tutti gli slot ANCORA da riempire dopo questo --
        27/07, fix: senza riserva i primi slot potevano spendere tutto il
        budget sui punteggi migliori, lasciando lo slot EXTRA finale sempre
        sforato). Se nessun candidato rientra nemmeno riservando, la
        formazione FALLISCE (nessun fallback che sfora il cap in silenzio --
        il cap e' un vincolo vero, non un suggerimento)."""
        candidates = [r for r in pool_rows if r['slug'] not in used_this_lineup]
        if l10_cap is not None and role_slot_l10_check:
            budget_residuo = l10_cap - l10_used[0] - reserve
            candidates = [r for r in candidates if (card_pool.l10(r['slug']) or 0.0) <= budget_residuo]

        for row in candidates:
            slug = row['slug']
            if card_pool.remaining_in_season(slug) > 0:
                return row, 'in_season'
            if (max_classic is None or classic_budget_used[0] < max_classic) and card_pool.remaining_classic(slug) > 0:
                return row, 'classic'
        return None, None

    picks = []
    gk_team_slug = gk_opponent_slug = None

    role_slot_counts = {}
    for role in shape['role_slots']:
        role_slot_counts[role] = role_slot_counts.get(role, 0) + 1
    role_occurrence = {role: 0 for role in role_slot_counts}

    for slot_idx, role in enumerate(shape['role_slots']):
        role_occurrence[role] += 1
        slot_label = role if role_slot_counts[role] == 1 else f"{role}{role_occurrence[role]}"

        reserve = 0.0
        if l10_cap is not None:
            reserve = sum(_min_available_l10(role_data[r], used_this_lineup, card_pool)
                          for r in shape['role_slots'][slot_idx + 1:])
            reserve += _min_available_l10(
                [row for r in shape['extra_roles'] for row in role_data[r]], used_this_lineup, card_pool)

        if role == 'GK':
            gk_candidates = role_data['GK']
            if used_matches:
                gk_candidates = synergy_adjusted_rows(role, gk_candidates, None, None, used_matches=used_matches)
            row, ctype = pick(gk_candidates, l10_cap is not None, reserve)
        else:
            pool_rows = role_data[role]
            if strict_gk_anti_synergy and role in ('MID', 'FWD') and gk_opponent_slug:
                pool_rows = [r for r in pool_rows if r.get('team_slug') != gk_opponent_slug]
            candidates = synergy_adjusted_rows(role, pool_rows, gk_team_slug, gk_opponent_slug,
                                                team_counts, apply_stack_guard, variance_mode,
                                                apply_positive_synergy, used_matches)
            row, ctype = pick(candidates, l10_cap is not None, reserve)

        if row is None:
            reason = ("vincolo di schieramento (portiere vs avversario) + copie esaurite o consiglio vuoto"
                      if strict_gk_anti_synergy else "copie esaurite o consiglio vuoto")
            return None, f"Nessun candidato disponibile per lo slot {slot_label} ({reason}).", l10_cap_rispettato[0], False

        used_this_lineup.add(row['slug'])
        if ctype == 'classic':
            classic_budget_used[0] += 1
        if l10_cap is not None:
            l10_used[0] += card_pool.l10(row['slug']) or 0.0
        picks.append((slot_label, row, ctype))

        row_team_slug = row.get('team_slug')
        if row_team_slug:
            team_counts[row_team_slug] = team_counts.get(row_team_slug, 0) + 1

        if role == 'GK':
            gk_team_slug = row.get('team_slug')
            gk_opponent_slug = row.get('opponent_team_slug')

    # Extra: il migliore rimanente tra i ruoli ammessi dalla shape (esclusi i
    # titolari di QUESTA lineup, le copie gia' esaurite, e rispettando
    # classic_budget/l10_cap), a prescindere dal ruolo specifico -- stessa
    # sinergia/anti-sinergia applicata anche qui.
    combined = []
    for role in shape['extra_roles']:
        for row in role_data[role]:
            if (strict_gk_anti_synergy and role in ('MID', 'FWD') and gk_opponent_slug
                    and row.get('team_slug') == gk_opponent_slug):
                continue
            combined.append((role, row))
    combined.sort(key=lambda rc: synergy_sort_key(rc[0], rc[1], gk_team_slug, gk_opponent_slug,
                                                    team_counts, apply_stack_guard, variance_mode,
                                                    apply_positive_synergy, used_matches), reverse=True)

    extra_candidates = [(role, row) for role, row in combined if row['slug'] not in used_this_lineup]
    if l10_cap is not None:
        budget_residuo = l10_cap - l10_used[0]
        extra_candidates = [(role, row) for role, row in extra_candidates
                             if (card_pool.l10(row['slug']) or 0.0) <= budget_residuo]

    extra_role = extra_pick = extra_type = None
    for role, row in extra_candidates:
        slug = row['slug']
        if card_pool.remaining_in_season(slug) > 0:
            extra_role, extra_pick, extra_type = role, row, 'in_season'
            break
        if (max_classic is None or classic_budget_used[0] < max_classic) and card_pool.remaining_classic(slug) > 0:
            extra_role, extra_pick, extra_type = role, row, 'classic'
            break

    if extra_pick is None:
        reason = "vincolo di schieramento (portiere vs avversario) + copie esaurite" if strict_gk_anti_synergy else "copie esaurite"
        return None, f"Nessun candidato disponibile per lo slot extra ({reason}).", l10_cap_rispettato[0], False

    picks.append((f'EXTRA ({extra_role})', extra_pick, extra_type))

    extra_team_slug = extra_pick.get('team_slug')
    if extra_team_slug:
        team_counts[extra_team_slug] = team_counts.get(extra_team_slug, 0) + 1

    for _slot, row, ctype in picks:
        card_pool.use(row['slug'], ctype)

    stack_bonus_perso = apply_stack_guard and any(c >= 3 for c in team_counts.values())
    return picks, None, l10_cap_rispettato[0], stack_bonus_perso


# Bonus capitano NON uniforme tra i tipi di formazione (verificato dall'utente
# il 26/07/2026 su casi reali Sorare): in Arena il capitano riceve solo +20%,
# non +50% come In Season/All Stars.
CAPTAIN_BONUS_BY_TYPE = {
    'IN_SEASON': 0.5,
    'ARENA_260': 0.2,
    'ARENA_220': 0.2,
    'ARENA_UNCAPPED': 0.2,
    'ALLSTARS': 0.5,
}

# Bonus "Cap 260" (SOLO In Season, 26/07 -- verificato dall'utente con screenshot
# reali della UI Sorare, pannello "BONUS FORMAZIONE"): se la somma delle L10 dei
# 5 titolari e' <= 260, si ottiene un +4% aggiuntivo su tutte le carte della
# formazione (si somma ad altri bonus formazione come "Multi-club", non ancora
# implementato/verificato del tutto -- vedi RIASSUNTO). E' una metrica DIVERSA
# dal cap L10 obbligatorio di Arena (ARENA_L10_CAP): li' e' un vincolo di
# formato che filtra le scelte durante la costruzione; qui e' solo INFORMATIVO
# (fase 1, rilevamento passivo) -- si limita a segnalare se la formazione gia'
# scelta (ottimizzata per punteggio atteso, nessun vincolo L10 attivo per
# In Season) rientra o no sotto la soglia, senza cercare attivamente
# un'alternativa che la rispetti. Nessun impatto sul totale numerico mostrato
# (stesso trattamento "solo informativo" gia' usato per il bonus anti-stack).
CAP260_BONUS = 0.04
# Soglia L10 per il bonus, per tipo (26/07 -- confermato dall'utente che il
# bonus esiste ANCHE per All Stars, non solo In Season, con soglia scalata a
# 7 giocatori invece di 5: 370 invece di 260, stessa % +4%).
CAP260_L10_THRESHOLD_BY_TYPE = {'IN_SEASON': 260.0, 'ALLSTARS': 370.0}


# Margine minimo di punteggio atteso che un portiere deve superare rispetto
# al migliore giocatore di movimento per convenire come capitano (27/07,
# richiesta esplicita utente, confermata con dati reali via
# formazione_mls/diagnostics/analyze_gk_captain_value.py -- NESSUNA nuova
# query, solo cache di calibrazione gia' su disco). Ricalibrato lo stesso
# giorno estendendo lo script a 10 campionati (MLS, K League, Brasile,
# Croazia, Portogallo, Austria, Scozia, Belgio, Olanda, Spagna): 404 partite
# GK (quasi 3x il campione precedente di 149 GK / 1673 movimento
# MLS+K League) confermano la stessa direzione con stima piu' precisa. Il
# bonus capitano e' una percentuale del punteggio REALE ottenuto (non
# dell'atteso), quindi scegliere il capitano solo in base all'atteso grezzo
# e' ottimale SOLO se l'atteso e' calibrato allo stesso modo tra ruoli --
# non lo e': nella fascia di punteggio atteso rilevante per la scelta
# capitano (>=55, dove tipicamente si gioca la decisione), il bias di
# calibrazione (reale - atteso) e' -12.06pt per i portieri contro -5.37pt
# per il movimento -- un divario di 6.69pt, coerente con l'esperienza
# dell'utente su Sorare ("basta un gol subito per perdere il bonus clean
# sheet, i portieri hanno punteggi tendenzialmente piu' bassi") anche se lui
# stesso non l'aveva mai verificato sui dati. A parita' o quasi di atteso
# nominale, il portiere realizza in media MENO del giocatore di movimento:
# un margine fisso corregge la scelta senza dover ricalibrare l'intera
# formula solo per la selezione capitano.
GK_CAPTAIN_MARGIN = 6.7


def pick_captain(formazione, avoid_slugs=None):
    """Il capitano ottimale sarebbe, in puro valore atteso, il giocatore con
    lo score atteso piu' alto della formazione (il bonus e' una percentuale
    del punteggio REALE di quel giocatore, quindi massimizzare l'atteso
    massimizza il bonus atteso) -- MA questo vale solo se l'atteso e'
    calibrato allo stesso modo tra ruoli. Non lo e' per i portieri (vedi
    GK_CAPTAIN_MARGIN sopra): un portiere diventa capitano solo se il suo
    atteso supera quello del miglior giocatore di movimento di almeno
    GK_CAPTAIN_MARGIN punti, altrimenti vince il movimento anche se il
    portiere ha un atteso nominale piu' alto (ma non abbastanza).
    'avoid_slugs' (27/07, richiesta esplicita utente: varianza capitano tra
    piu' formazioni della STESSA competizione/tipo, quando esistono 2+ copie
    di una carta che permettono di riusarla in piu' lineup): se fornito,
    preferisce il punteggio piu' alto TRA i titolari non ancora capitanati in
    questo tipo; se sono gia' stati capitanati tutti (nessuna alternativa),
    ripiega sul pool completo -- mai un peggioramento del punteggio atteso
    solo per la varianza, la logica GK/movimento resta comunque applicata."""
    candidates = formazione
    if avoid_slugs:
        filtered = [p for p in formazione if p[1]['slug'] not in avoid_slugs]
        if filtered:
            candidates = filtered

    outfield = [p for p in candidates if p[0] != 'GK']
    if not outfield:
        return max(candidates, key=lambda p: p[1]['atteso'])
    best_outfield = max(outfield, key=lambda p: p[1]['atteso'])

    gk = [p for p in candidates if p[0] == 'GK']
    if not gk:
        return best_outfield
    best_gk = max(gk, key=lambda p: p[1]['atteso'])

    if best_gk[1]['atteso'] >= best_outfield[1]['atteso'] + GK_CAPTAIN_MARGIN:
        return best_gk
    return best_outfield


def format_lineup(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True,
                   stack_bonus_perso=False, check_cap260=False, tipo=None, apply_stack_guard=False,
                   avoid_captain_slugs=None):
    lines = []
    lines.append(f"--- Formazione {tipo_label} #{idx} ---")
    captain_slot, captain_row, _captain_type = pick_captain(formazione, avoid_captain_slugs)
    totale_atteso = totale_low = totale_high = 0
    totale_l10 = 0.0
    for slot, row, ctype in formazione:
        tag = " [CLASSIC]" if ctype == 'classic' else ""
        copie = card_pool.copies_owned(row['slug'])
        nota_copie = f" ({copie} copie possedute)" if copie > 1 else ""
        cap_tag = " [C]" if row['slug'] == captain_row['slug'] else ""
        lines.append(f"{slot:<12} {row['slug']}: {row['atteso']} pt ({row['low']}-{row['high']}){tag}{nota_copie}{cap_tag}")
        totale_atteso += row['atteso']
        totale_low += row['low']
        totale_high += row['high']
        totale_l10 += card_pool.l10(row['slug']) or 0.0

    captain_bonus_pct = CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5)
    bonus = round(captain_row['atteso'] * captain_bonus_pct)
    totale_con_capitano = totale_atteso + bonus
    lines.append(f"TOTALE: {totale_atteso} pt ({totale_low}-{totale_high})")
    lines.append(f"CAPITANO CONSIGLIATO: {captain_row['slug']} (+{bonus} pt, +{captain_bonus_pct:.0%}) "
                 f"-> TOTALE CON CAPITANO: {totale_con_capitano} pt")
    if l10_cap is not None:
        stato = "OK" if l10_cap_rispettato else "NON RISPETTATO (nessun candidato entro budget, preso il piu' economico disponibile)"
        lines.append(f"L10 combinata: {totale_l10:.1f} / cap {l10_cap:.1f} -- {stato}")
    if apply_stack_guard:
        if stack_bonus_perso:
            lines.append("ATTENZIONE: 3+ giocatori della stessa squadra -- bonus anti-stack 2%/giocatore NON applicato "
                          "(valuta tu se il contesto della partita giustifica comunque lo stack).")
        else:
            lines.append("Bonus anti-stack (Multi-club) +2%/giocatore: attivo (meno di 3 titolari della stessa squadra).")
    if check_cap260:
        soglia_cap = CAP260_L10_THRESHOLD_BY_TYPE.get(tipo, 260.0)
        stato260 = "OK" if totale_l10 <= soglia_cap else "NON rispettato"
        lines.append(f"Cap {soglia_cap:.0f}: L10 combinata {totale_l10:.1f} / {soglia_cap:.0f} -- {stato260} "
                      f"({'+4% bonus formazione attivo' if totale_l10 <= soglia_cap else 'bonus +4% non ottenuto'})")
    return "\n".join(lines), totale_atteso


# --- Report visivo HTML (26/07, seconda sessione, richiesta esplicita
# dell'utente): oggi l'unico output e' testo puro, funzionale ma poco
# leggibile a colpo d'occhio. Genera un file .html AUTONOMO (nessuno script/
# font esterno, apribile con un doppio click da repo locale via file://,
# nessun server/download necessario) con un layout a "carte" ispirato alla
# UI reale di Sorare: striscia colorata per ruolo (niente foto/stemmi reali,
# non disponibili dall'API — iniziali del giocatore al loro posto), punteggio
# atteso in grande, range sotto, badge capitano, tag Classic/copie multiple.
# Committato dal workflow accanto al .txt esistente (stesso nome, estensione
# diversa).
ROLE_COLORS_HTML = {'GK': '#8b7cf6', 'DEF': '#3aa1e8', 'MID': '#2fbf8f', 'FWD': '#ef5b5b'}
EXTRA_COLOR_HTML = '#f0a83b'


def _slot_role_color(slot_label):
    for role, color in ROLE_COLORS_HTML.items():
        if slot_label.startswith(role):
            return color
    m = re.search(r'\(([A-Z]+)\)', slot_label)
    if m and m.group(1) in ROLE_COLORS_HTML:
        return ROLE_COLORS_HTML[m.group(1)]
    return EXTRA_COLOR_HTML


def _slug_initials(slug):
    parts = [p for p in slug.split('-') if p and not p.isdigit()]
    return ''.join(p[0].upper() for p in parts[:2]) or '??'


def _slug_display_name(slug):
    return ' '.join(w[:1].upper() + w[1:] for w in slug.split('-') if w)


ROLES_HTML = ('GK', 'DEF', 'MID', 'FWD')


def _slot_role(slot_label):
    """Ruolo REALE (GK/DEF/MID/FWD) di uno slot, sia esso diretto ('DEF1')
    che EXTRA ('EXTRA (MID)'). Condiviso fra pannello alternative e drag&drop
    (28/07) -- prima esisteva solo una copia locale in
    generatore_formazioni/build_formazione_globale.py, spostata qui perche'
    ora serve anche a render_card_html per il matching lato client."""
    for role in ROLES_HTML:
        if slot_label.startswith(role):
            return role
    m = re.search(r'\(([A-Z]+)\)', slot_label)
    return m.group(1) if m and m.group(1) in ROLES_HTML else None


def _pcard_tags_html(ctype, copie):
    tags = []
    if ctype == 'classic':
        tags.append('<span class="tag tag-classic">Classic</span>')
    if copie > 1:
        tags.append(f'<span class="tag tag-copies">{copie} copie</span>')
    return ''.join(tags)


def _pcard_body_html(slug, atteso, low, high, l10, tags_html, card_pool):
    """Contenuto dinamico di una pcard (tutto tranne striscia colore/ruolo/
    badge capitano, che restano legati allo SLOT, non al giocatore) --
    fattorizzato (28/07) per essere riusato SIA per la carta reale SIA per
    calcolare in anticipo, in Python, l'HTML che un'alternativa diventerebbe
    se trascinata al posto del titolare (drag&drop lato client, nessun
    ricalcolo server: lo scambio e' un puro swap di HTML gia' pronto)."""
    l10_html = f'<div class="pcard-l10">L10: {l10:.0f}</div>' if l10 is not None else ''
    return (
        f'<div class="pcard-avatar">{_slug_initials(slug)}</div>'
        f'<div class="pcard-name">{card_pool.display_name(slug)}</div>'
        f'<div class="pcard-score">{atteso}</div>'
        f'<div class="pcard-range">{low}–{high} pt</div>'
        f'{l10_html}'
        f'<div class="pcard-tags">{tags_html}</div>'
    )


def render_card_html(slot_label, row, ctype, card_pool, is_captain):
    color = _slot_role_color(slot_label)
    role_label = re.sub(r'^EXTRA \(([A-Z]+)\)$', r'EXTRA · \1', slot_label)
    role = _slot_role(slot_label) or ''
    copie = card_pool.copies_owned(row['slug'])
    tags_html = _pcard_tags_html(ctype, copie)
    captain_badge = '<span class="pcard-captain">C</span>' if is_captain else ''
    l10 = card_pool.l10(row['slug'])
    body_html = _pcard_body_html(row['slug'], row['atteso'], row['low'], row['high'], l10, tags_html, card_pool)
    # data-body (28/07): l'HTML esatto della pcard-body per QUESTO giocatore,
    # gia' pronto -- il drag&drop lato client lo scambia con quello di
    # un'alternativa senza ricalcolare nulla in JS (vedi script nel template).
    return (
        f'<div class="pcard" draggable="true" style="--role-color:{color}" '
        f'data-slug="{html.escape(row["slug"], quote=True)}" data-role="{role}" '
        f'data-score="{row["atteso"]}" '
        f'data-name="{html.escape(card_pool.display_name(row["slug"]), quote=True)}" '
        f'data-body="{html.escape(body_html, quote=True)}">'
        f'<div class="pcard-stripe" style="background:{color}"></div>'
        f'<span class="pcard-role">{role_label}</span>'
        f'{captain_badge}'
        f'<div class="pcard-body">{body_html}</div>'
        f'</div>'
    )


def render_lineup_html(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True,
                        stack_bonus_perso=False, check_cap260=False, tipo=None, apply_stack_guard=False,
                        avoid_captain_slugs=None):
    captain_slot, captain_row, _captain_type = pick_captain(formazione, avoid_captain_slugs)
    # Tornati alla fila originale (28/07): sia il raggruppamento per ruolo
    # sia la diagonale non convincevano l'utente ("non ci siamo") -- niente
    # riordino, stessa sequenza di formazione, striscia unica con scroll
    # orizzontale se serve. Carte piu' piccole restano (richiesta separata,
    # confermata).
    cards_html = ''.join(
        render_card_html(slot, row, ctype, card_pool, row['slug'] == captain_row['slug'])
        for slot, row, ctype in formazione
    )
    totale_atteso = sum(row['atteso'] for _, row, _ in formazione)
    captain_bonus_pct = CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5)
    bonus = round(captain_row['atteso'] * captain_bonus_pct)
    totale_con_capitano = totale_atteso + bonus
    l10_note = ''
    if l10_cap is not None:
        totale_l10 = sum(card_pool.l10(row['slug']) or 0.0 for _, row, _ in formazione)
        stato = 'entro budget' if l10_cap_rispettato else 'budget NON rispettato'
        l10_note = f'<div class="captain-note">L10: {totale_l10:.1f} / {l10_cap:.1f} ({stato})</div>'
    stack_note = ''
    if apply_stack_guard:
        if stack_bonus_perso:
            stack_note = ('<div class="captain-note" style="color:#d9534f">ATTENZIONE: 3+ giocatori della stessa '
                           'squadra — bonus anti-stack 2%/giocatore NON applicato</div>')
        else:
            stack_note = ('<div class="captain-note">Bonus Multi-club +2%/giocatore: attivo (meno di 3 titolari '
                           'della stessa squadra)</div>')
    cap260_note = ''
    if check_cap260:
        soglia_cap = CAP260_L10_THRESHOLD_BY_TYPE.get(tipo, 260.0)
        totale_l10_c260 = sum(card_pool.l10(row['slug']) or 0.0 for _, row, _ in formazione)
        ok260 = totale_l10_c260 <= soglia_cap
        colore = '' if ok260 else ' style="color:#d9534f"'
        esito = '+4% bonus formazione attivo' if ok260 else 'bonus +4% non ottenuto'
        cap260_note = (f'<div class="captain-note"{colore}>Cap {soglia_cap:.0f}: L10 {totale_l10_c260:.1f} / '
                        f'{soglia_cap:.0f} ({esito})</div>')
    # data-captain-pct (28/07): il drag&drop lato client deve ricalcolare
    # totale e bonus capitano dopo uno scambio senza rifare la run -- serve
    # solo la percentuale, il resto (chi e' capitano, punteggi) si legge
    # dagli attributi data-* delle pcard gia' presenti nel DOM.
    return (
        f'<div class="lineup-block"><div class="lineup-meta">'
        f'<div class="lineup-title">{tipo_label} <span>#{idx}</span></div></div>'
        f'<div class="card-strip">{cards_html}</div>'
        f'<div class="lineup-total" data-captain-pct="{captain_bonus_pct}">'
        f'<div><span class="label">Totale</span><span class="figure">{totale_atteso} pt</span></div>'
        f'<div class="divider"></div>'
        f'<div><span class="label">Con capitano</span>'
        f'<span class="figure with-captain">{totale_con_capitano} pt</span></div>'
        f'<div class="captain-note">Capitano <b class="cap-name">{card_pool.display_name(captain_row["slug"])}</b> '
        f'<span class="cap-bonus">(+{bonus} pt, +{captain_bonus_pct:.0%})</span></div>{l10_note}{stack_note}{cap260_note}'
        f'</div></div>'
    )


HTML_REPORT_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #0a0d12; --surface: #131a23; --surface-2: #1c2530; --stripe: #232d3a;
    --text: #edf1f6; --muted: #8a93a6; --muted-2: #5f6879; --gold: #f4c542;
    --border: rgba(255,255,255,0.08);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f3f4f7; --surface: #ffffff; --surface-2: #eef0f4; --stripe: #e3e6ec;
      --text: #1a2029; --muted: #5b6474; --muted-2: #8a93a6; --border: rgba(20,25,35,0.08);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
    padding: 40px 32px 64px; max-width: 1180px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 6px; }}
  .subhead {{ color: var(--muted); font-size: 0.85rem; margin: 0 0 32px; }}
  .lineup-row {{ display: flex; gap: 20px; align-items: flex-start; margin-bottom: 40px; }}
  .lineup-row .lineup-block {{ flex: 1 1 auto; min-width: 0; margin-bottom: 0; }}
  .alt-panel {{
    flex: 0 0 200px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 14px; align-self: stretch;
  }}
  .alt-panel-title {{
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--muted); margin-bottom: 10px; line-height: 1.4;
  }}
  .alt-list {{ display: flex; flex-direction: column; gap: 10px; }}
  .alt-chip {{ display: flex; align-items: center; gap: 8px; cursor: grab; border-radius: 8px; padding: 2px; }}
  .alt-chip[draggable="true"]:active {{ cursor: grabbing; }}
  .pcard[draggable="true"] {{ cursor: grab; }}
  .pcard[draggable="true"]:active {{ cursor: grabbing; }}
  .pcard.drop-target, .alt-chip.drop-target {{
    outline: 2px dashed var(--gold); outline-offset: 2px;
  }}
  .alt-circle {{
    flex: 0 0 28px; width: 28px; height: 28px; border-radius: 50%; background: var(--surface-2);
    border: 1px solid var(--border); display: flex; align-items: center; justify-content: center;
    font-size: 0.62rem; font-weight: 700; color: var(--muted);
  }}
  .alt-name {{ font-size: 0.72rem; font-weight: 600; line-height: 1.2; }}
  .alt-score {{ font-size: 0.64rem; color: var(--muted); }}
  .lineup-block {{ margin-bottom: 40px; }}
  .lineup-meta {{ margin-bottom: 12px; }}
  .lineup-title {{ font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .lineup-title span {{ color: var(--text); }}
  .card-strip {{ display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; }}
  .pcard {{
    position: relative; flex: 0 0 104px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.2);
  }}
  .pcard-stripe {{ height: 4px; width: 100%; }}
  .pcard-body {{ padding: 8px 6px 8px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; }}
  .pcard-role {{
    position: absolute; top: 6px; left: 6px; font-size: 0.52rem; font-weight: 700;
    letter-spacing: 0.07em; text-transform: uppercase; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 16%, transparent);
    padding: 1px 5px; border-radius: 4px;
  }}
  .pcard-captain {{
    position: absolute; top: 5px; right: 5px; width: 16px; height: 16px; border-radius: 50%;
    background: var(--gold); color: #241c00; font-size: 0.58rem; font-weight: 800;
    display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--surface);
  }}
  .pcard-avatar {{
    width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.72rem; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 18%, var(--surface-2));
    border: 2px solid color-mix(in srgb, var(--role-color) 55%, transparent); margin-top: 8px;
  }}
  .pcard-name {{ font-size: 0.62rem; font-weight: 650; line-height: 1.2; min-height: 1.6em; display: flex; align-items: center; }}
  .pcard-score {{ font-size: 1.15rem; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; color: var(--role-color); }}
  .pcard-range {{ font-size: 0.55rem; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .pcard-l10 {{ font-size: 0.5rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }}
  .pcard-tags {{ display: flex; gap: 3px; flex-wrap: wrap; justify-content: center; min-height: 14px; }}
  .tag {{ font-size: 0.5rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; padding: 1px 4px; border-radius: 3px; }}
  .tag-classic {{ background: rgba(240,168,59,0.16); color: #f0a83b; }}
  .tag-copies {{ background: var(--stripe); color: var(--muted); }}
  .lineup-total {{
    margin-top: 12px; display: flex; align-items: center; gap: 18px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px; padding: 12px 18px; flex-wrap: wrap;
  }}
  .lineup-total .figure {{ font-size: 1.3rem; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .lineup-total .figure.with-captain {{ color: var(--gold); }}
  .lineup-total .label {{ font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); display: block; margin-bottom: 2px; }}
  .lineup-total .divider {{ width: 1px; height: 30px; background: var(--border); }}
  .lineup-total .captain-note {{ font-size: 0.74rem; color: var(--muted); margin-left: auto; }}
  .lineup-total .captain-note b {{ color: var(--gold); font-weight: 700; }}
  .error-block {{ font-size: 0.82rem; color: var(--muted); padding: 12px 0; }}
  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); font-size: 0.7rem; color: var(--muted-2); line-height: 1.6; }}
</style>
</head>
<body>
<h1>{page_title}</h1>
<p class="subhead">{page_subhead}</p>
{lineup_html}
<footer>{footer}</footer>
<script>
// Drag&drop (28/07, richiesta esplicita utente): scambia un giocatore fra
// una pcard schierata e un'alternativa (o un'altra pcard), stesso ruolo.
// Puro swap di HTML/attributi gia' pronti lato server (data-body) -- NESSUN
// ricalcolo di formula, NESSUNA persistenza (un refresh della pagina
// riporta tutto allo stato generato). Limite noto: le note L10/cap/anti-stack
// sotto ogni formazione restano quelle calcolate al momento della run, non
// si aggiornano con lo scambio (solo totale e bonus capitano lo fanno).
(function () {{
  var dragEl = null;

  function isDraggable(el) {{
    return el && (el.classList.contains('pcard') || el.classList.contains('alt-chip'))
      && el.getAttribute('draggable') === 'true';
  }}

  document.addEventListener('dragstart', function (e) {{
    var el = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!el) return;
    dragEl = el;
    e.dataTransfer.effectAllowed = 'move';
    try {{ e.dataTransfer.setData('text/plain', 'x'); }} catch (err) {{}}
  }});

  document.addEventListener('dragover', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!dragEl || !target || target === dragEl || target.dataset.role !== dragEl.dataset.role) return;
    e.preventDefault();
  }});

  document.addEventListener('dragenter', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (dragEl && target && target !== dragEl && target.dataset.role === dragEl.dataset.role) {{
      target.classList.add('drop-target');
    }}
  }});

  document.addEventListener('dragleave', function (e) {{
    var target = e.target.closest('.pcard, .alt-chip');
    if (target) target.classList.remove('drop-target');
  }});

  document.addEventListener('dragend', function () {{
    document.querySelectorAll('.drop-target').forEach(function (el) {{ el.classList.remove('drop-target'); }});
    dragEl = null;
  }});

  document.addEventListener('drop', function (e) {{
    var target = e.target.closest('.pcard[draggable="true"], .alt-chip[draggable="true"]');
    if (!dragEl || !target || target === dragEl || target.dataset.role !== dragEl.dataset.role) return;
    e.preventDefault();
    target.classList.remove('drop-target');
    swapPlayers(dragEl, target);
    dragEl = null;
  }});

  function initials(name) {{
    return (name || '').split(' ').filter(Boolean).slice(0, 2)
      .map(function (w) {{ return w[0].toUpperCase(); }}).join('') || '??';
  }}

  function refresh(el) {{
    if (el.classList.contains('pcard')) {{
      var body = el.querySelector('.pcard-body');
      if (body) body.innerHTML = el.dataset.body;
    }} else {{
      var circle = el.querySelector('.alt-circle');
      var name = el.querySelector('.alt-name');
      var score = el.querySelector('.alt-score');
      if (circle) circle.textContent = initials(el.dataset.name);
      if (name) name.textContent = el.dataset.name;
      if (score) score.textContent = el.dataset.score + ' pt · ' + el.dataset.role;
    }}
  }}

  function swapPlayers(a, b) {{
    ['slug', 'score', 'name', 'body'].forEach(function (k) {{
      var tmp = a.dataset[k];
      a.dataset[k] = b.dataset[k];
      b.dataset[k] = tmp;
    }});
    refresh(a);
    refresh(b);
    [a, b].forEach(function (el) {{
      var block = el.closest('.lineup-block');
      if (block) recomputeTotal(block);
    }});
  }}

  function recomputeTotal(block) {{
    var total = 0;
    block.querySelectorAll('.pcard').forEach(function (c) {{ total += parseFloat(c.dataset.score) || 0; }});
    var totalEl = block.querySelector('.lineup-total');
    if (!totalEl) return;
    var figure = totalEl.querySelector('.figure:not(.with-captain)');
    if (figure) figure.textContent = Math.round(total) + ' pt';
    var capBadge = block.querySelector('.pcard-captain');
    var capPct = parseFloat(totalEl.dataset.captainPct || '0.5');
    var bonus = 0, capName = '';
    if (capBadge) {{
      var capCard = capBadge.closest('.pcard');
      bonus = Math.round((parseFloat(capCard.dataset.score) || 0) * capPct);
      capName = capCard.dataset.name || '';
    }}
    var withCap = totalEl.querySelector('.figure.with-captain');
    if (withCap) withCap.textContent = Math.round(total + bonus) + ' pt';
    var capNameEl = totalEl.querySelector('.cap-name');
    if (capNameEl && capName) capNameEl.textContent = capName;
    var capBonusEl = totalEl.querySelector('.cap-bonus');
    if (capBonusEl) capBonusEl.textContent = '(+' + bonus + ' pt, +' + Math.round(capPct * 100) + '%)';
  }}
}})();
</script>
</body>
</html>
"""


def render_report_html(page_title, page_subhead, lineup_html_blocks, footer):
    body = "\n".join(lineup_html_blocks) if lineup_html_blocks else '<p class="error-block">Nessuna formazione generata.</p>'
    return HTML_REPORT_TEMPLATE.format(
        page_title=page_title, page_subhead=page_subhead, lineup_html=body, footer=footer)


# Cap L10 fisso per i tipi Arena dedicati (26/07) -- indipendenti dal tuning
# generico ARENA_L10_CAP (quello resta per il tipo 'ARENA' semplice/legacy).
FIXED_L10_CAP_BY_TYPE = {'ARENA_260': 260.0, 'ARENA_220': 220.0}


def generate_lineups_for_type(tipo, count, role_data, card_pool, lineup_blocks,
                               lineup_html_blocks, print_output=True):
    """Genera fino a 'count' formazioni del tipo 'tipo' (chiave di
    FORMATION_SHAPES), aggiungendo i blocchi di testo a lineup_blocks e i
    blocchi HTML a lineup_html_blocks. Ritorna (generate, totale_punti). Si
    ferma in anticipo (senza errore globale) se il pool si esaurisce per
    questo tipo, ma NON impedisce la generazione del tipo successivo in
    ordine di priorita'."""
    shape = FORMATION_SHAPES[tipo]
    cap = FIXED_L10_CAP_BY_TYPE.get(tipo)
    # Anti-stack e cap-bonus (26/07, confermato dall'utente): valgono per
    # In Season E All Stars (soglie/percentuali diverse ma stesso meccanismo),
    # non per Arena (che ha il suo cap L10 obbligatorio separato, nessun bonus).
    stack_guard = tipo in ('IN_SEASON', 'ALLSTARS')
    # Sinergia da correlazione misurata (vedi GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA):
    # SOLO dove la varianza conta, cioe' tutto tranne In Season (target fisso).
    variance_mode = tipo != 'IN_SEASON'
    # 27/07, richiesta esplicita utente: quando si richiedono 2+ In Season,
    # SOLO la prima usa la sinergia GK-DEF soft (comportamento storico); dalla
    # seconda in poi e' greedy puro (solo punteggio, nessuna priorita' di
    # ruolo/sinergia). In ENTRAMBI i casi, se sono 2+, il vincolo di
    # schieramento portiere-vs-avversario diventa DURO (mai piu' un'ultima
    # risorsa) invece che un forte scoraggiamento. Con 1 sola In Season
    # richiesta, o per Arena/All Stars, comportamento INVARIATO.
    in_season_multi = tipo == 'IN_SEASON' and count >= 2
    # Varianza capitano (27/07, richiesta esplicita utente): scope PER TIPO,
    # naturale qui dato che generate_lineups_for_type gia' genera un tipo per
    # chiamata -- evita di rinominare capitano un giocatore gia' capitanato
    # in una formazione precedente DELLO STESSO TIPO, a meno che non ci sia
    # nessuna alternativa valida nella lineup corrente (pick_captain ripiega
    # sul punteggio piu' alto assoluto in quel caso). Un giocatore con 1 sola
    # copia non puo' comunque comparire in due lineup dello stesso tipo (il
    # CardPool lo impedirebbe), quindi non serve un controllo esplicito
    # "2+ copie": la condizione e' gia' garantita dal pool.
    captained_slugs = set()
    generated = 0
    totale = 0
    for idx in range(1, count + 1):
        strict_gk_anti_synergy = in_season_multi
        apply_positive_synergy = not in_season_multi or idx == 1
        formazione, error, l10_ok, stack_perso = build_one_lineup(
            shape, role_data, card_pool, l10_cap=cap, apply_stack_guard=stack_guard,
            variance_mode=variance_mode, apply_positive_synergy=apply_positive_synergy,
            strict_gk_anti_synergy=strict_gk_anti_synergy)
        if error:
            msg = f"Formazione {shape['label']} #{idx}: NON GENERATA — {error}"
            if print_output:
                print(f"\n{msg}")
            lineup_blocks.append(msg)
            lineup_html_blocks.append(f'<p class="error-block">{msg}</p>')
            break
        check_cap260 = tipo in CAP260_L10_THRESHOLD_BY_TYPE
        block_text, punti = format_lineup(shape['label'], idx, formazione, card_pool,
                                           l10_cap=cap, l10_cap_rispettato=l10_ok,
                                           stack_bonus_perso=stack_perso, check_cap260=check_cap260,
                                           tipo=tipo, apply_stack_guard=stack_guard,
                                           avoid_captain_slugs=captained_slugs)
        lineup_blocks.append(block_text)
        lineup_html_blocks.append(render_lineup_html(shape['label'], idx, formazione, card_pool,
                                                       l10_cap=cap, l10_cap_rispettato=l10_ok,
                                                       stack_bonus_perso=stack_perso,
                                                       avoid_captain_slugs=captained_slugs,
                                                       check_cap260=check_cap260, tipo=tipo,
                                                       apply_stack_guard=stack_guard))
        _cap_slot, cap_row, _cap_type = pick_captain(formazione, captained_slugs)
        captained_slugs.add(cap_row['slug'])
        totale += punti
        generated += 1
        if print_output:
            print("\n" + block_text)
    return generated, totale


def main():
    counts, num_totale = get_formation_counts()
    role_data, role_files, role_counts, counts_files = load_all_roles()

    print(f"Formazioni richieste: totale={num_totale} "
          f"(In Season={counts['IN_SEASON']}, Arena cap260={counts['ARENA_260']}, "
          f"Arena cap220={counts['ARENA_220']}, Arena uncapped={counts['ARENA_UNCAPPED']}, "
          f"All Stars={counts['ALLSTARS']})")
    print()
    for role, path in role_files.items():
        n = len(role_data.get(role) or [])
        print(f"[{role}] {path or 'NESSUN FILE TROVATO'} -> {n} giocatori disponibili")
    for role, path in counts_files.items():
        print(f"[{role}] player_card_counts.json: {path or 'MANCANTE (default 1 copia in_season/giocatore)'}")

    if not all(role_data.get(r) for r in ROLES):
        print("\nERRORE: almeno un ruolo non ha consiglio disponibile, impossibile generare formazioni.")
        return

    card_pool = CardPool(role_counts)

    # Numero di run GitHub Actions (GITHUB_RUN_NUMBER, incrementale per workflow):
    # incluso nel nome file e nell'header per distinguere a colpo d'occhio
    # l'output di run diversi, che altrimenti si differenzierebbero solo per
    # pochi minuti nel timestamp. Assente nei run locali (fuori CI).
    run_number = os.environ.get('GITHUB_RUN_NUMBER')

    header_lines = []
    header_lines.append("=" * 70)
    header_lines.append("FORMAZIONE OTTIMALE — FUSIONE FINALE")
    if run_number:
        header_lines.append(f"Run GitHub Actions: #{run_number}")
    header_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    header_lines.append(f"Formazioni richieste: totale={num_totale} (In Season={counts['IN_SEASON']}, "
                         f"Arena cap260={counts['ARENA_260']}, Arena cap220={counts['ARENA_220']}, "
                         f"Arena uncapped={counts['ARENA_UNCAPPED']}, All Stars={counts['ALLSTARS']})")
    header_lines.append("=" * 70)
    header_lines.append("")
    header_lines.append("Fonte consigli di ruolo (piu' recenti in repo):")
    for role, path in role_files.items():
        header_lines.append(f"  {role}: {path or 'MANCANTE'}")
    header_lines.append("")
    header_lines.append("Fonte copie possedute per giocatore (player_card_counts.json):")
    for role, path in counts_files.items():
        header_lines.append(f"  {role}: {path or 'MANCANTE (assunta 1 copia in_season per ogni giocatore)'}")
    header_lines.append("")
    header_lines.append("-" * 70)

    lineup_blocks = []
    lineup_html_blocks = []
    generated_by_type = {}
    grand_total = 0
    # Ordine di priorita' FISSO (26/07): In Season -> Arena cap260 -> Arena
    # cap220 -> Arena uncapped -> All Stars.
    for tipo in ('IN_SEASON', 'ARENA_260', 'ARENA_220', 'ARENA_UNCAPPED', 'ALLSTARS'):
        n_richieste = counts[tipo]
        if n_richieste <= 0:
            generated_by_type[tipo] = 0
            continue
        generated, totale = generate_lineups_for_type(
            tipo, n_richieste, role_data, card_pool, lineup_blocks, lineup_html_blocks)
        generated_by_type[tipo] = generated
        grand_total += totale

    total_generated = sum(generated_by_type.values())

    footer_lines = []
    footer_lines.append("-" * 70)
    footer_lines.append(f"Formazioni generate: {total_generated}/{num_totale} "
                         f"(In Season {generated_by_type.get('IN_SEASON', 0)}/{counts['IN_SEASON']}, "
                         f"Arena cap260 {generated_by_type.get('ARENA_260', 0)}/{counts['ARENA_260']}, "
                         f"Arena cap220 {generated_by_type.get('ARENA_220', 0)}/{counts['ARENA_220']}, "
                         f"Arena uncapped {generated_by_type.get('ARENA_UNCAPPED', 0)}/{counts['ARENA_UNCAPPED']}, "
                         f"All Stars {generated_by_type.get('ALLSTARS', 0)}/{counts['ALLSTARS']})")
    if total_generated > 1:
        footer_lines.append(f"TOTALE COMPLESSIVO (tutte le formazioni): {grand_total} pt")
    footer_lines.append("=" * 70)
    footer_lines.append("")
    footer_lines.append("NOTA: max 1 carta CLASSIC per formazione SOLO per In Season (contrassegnata")
    footer_lines.append("[CLASSIC]) -- Arena e All Stars non hanno questo vincolo. Preferenza")
    footer_lines.append("automatica per copie IN_SEASON quando disponibili. Un giocatore e' riusato")
    footer_lines.append("in piu' lineup (anche di tipo diverso) solo se se ne possiedono piu' copie")
    footer_lines.append("(player_card_counts.json).")

    full_text = "\n".join(header_lines) + "\n\n" + "\n\n".join(lineup_blocks) + "\n\n" + "\n".join(footer_lines)
    print("\n" + "\n".join(footer_lines))

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    run_suffix = f"_run{run_number}" if run_number else ""
    out_path = os.path.join(OUTPUT_DIR, f'formazione_finale{run_suffix}_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"\nSalvato in: {out_path}")

    # Report visivo HTML (26/07, richiesta esplicita dell'utente): stesso
    # contenuto del .txt, presentazione a carte -- apribile con un doppio
    # click, nessun server/download necessario (vedi HTML_REPORT_TEMPLATE).
    page_title = f"Formazioni{' — run #' + run_number if run_number else ''}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                    f"totale={num_totale} (In Season={counts['IN_SEASON']}, "
                    f"Arena cap260={counts['ARENA_260']}, Arena cap220={counts['ARENA_220']}, "
                    f"Arena uncapped={counts['ARENA_UNCAPPED']}, All Stars={counts['ALLSTARS']})")
    footer_html = ("Nessuna carta CLASSIC oltre il limite per In Season (max 1) -- Arena e All Stars "
                   "non hanno questo vincolo. Un giocatore e' riusato in piu' lineup solo se se ne "
                   "possiedono piu' copie.")
    html_text = render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_path = os.path.join(OUTPUT_DIR, f'formazione_finale{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"Report visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
