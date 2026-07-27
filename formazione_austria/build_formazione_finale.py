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
  Tre varianti fisse (26/07, seconda revisione): Arena cap260, Arena cap220,
  Arena uncapped -- vedi FIXED_L10_CAP_BY_TYPE sotto.
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
generarli in ordine di priorita' IN SEASON -> ARENA (cap260 -> cap220 ->
uncapped) -> ALL STARS fa si' che, se il pool si esaurisce, siano
naturalmente le formazioni meno prioritarie a non essere completate — mai
le In Season. Ogni tipo puo' essere messo a 0 per disattivarlo del tutto.
Il totale richiesto (NUM_TOTALE_FORMAZIONI) deve combaciare ESATTAMENTE con
la somma dei 5 sotto-totali, altrimenti lo script si ferma subito
(fail-fast, non tronca silenziosamente).

TRE TIPI ARENA CON CAP FISSO (26/07, seconda revisione, richiesta esplicita
dell'utente): il vecchio tuning generico ARENA_L10_CAP e' stato sostituito
da tre tipi Arena distinti con cap fisso (FIXED_L10_CAP_BY_TYPE): cap260,
cap220 e uncapped (nessun limite). Ogni tipo rispetta un tetto sulla somma
delle L10 (media ultime 10 partite GIOCATE,
LAST_TEN_PLAYED_SO5_AVERAGE_SCORE) dei 5 giocatori schierati -- non solo il
punteggio atteso piu' alto in assoluto, ma il migliore CHE rispetta il
tetto. Implementato come euristica greedy con budget residuo (non un
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
import json
import datetime

ROLES = {
    'GK': 'formazione_austria/output/austria_gk_all',
    'DEF': 'formazione_austria/output/austria_def_all',
    'MID': 'formazione_austria/output/austria_mid_all',
    'FWD': 'formazione_austria/output/austria_fwd_all',
}

DISCOVERY_DIRS = {
    'GK': 'formazione_austria/output/austria_gk_discovery',
    'DEF': 'formazione_austria/output/austria_def_discovery',
    'MID': 'formazione_austria/output/austria_mid_discovery',
    'FWD': 'formazione_austria/output/austria_fwd_discovery',
}

OUTPUT_DIR = 'formazione_austria/output'

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

# Bonus anti-stack Sorare (26/07, scoperto dall'utente, SOLO In Season): se
# una formazione ha MENO di 3 giocatori della stessa squadra, ogni giocatore
# riceve +2% al proprio punteggio; con 3+ della stessa squadra il bonus
# salta per TUTTI e 5. La sinergia GK+DEF sopra, da sola, porta al massimo a
# 2 giocatori della stessa squadra (GK + 1 DEF titolare) -- nessun conflitto,
# resta "gratis". Il conflitto nasce solo se un ALTRO slot (tipicamente
# l'extra) porterebbe una squadra al 3o giocatore: li' il costo e' certo
# (-2% su tutti e 5) mentre il beneficio di correlazione e' incerto, quindi
# di default scoraggiamo (non vietiamo: a volte, es. capolista contro
# ultima, puo' valere la pena sacrificare il bonus per un punteggio quasi
# certo -- scelta che spetta all'utente, non all'algoritmo) il 3o giocatore
# della stessa squadra. Applicato SOLO per In Season (apply_stack_guard):
# Arena/All Stars non hanno questo bonus, restano invariate.
IN_SEASON_STACK_LIMIT = 2
STACK_GUARD_PENALTY = 8_000  # come ANTI_SYNERGY_PENALTY: spinge in fondo, non esclude


def synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                      apply_positive_synergy=True):
    """Punteggio AGGIUSTATO solo per decidere l'ORDINE di scelta tra candidati
    dello stesso ruolo, dato il portiere gia' selezionato per questa lineup.
    Non altera mai 'atteso' nel dict originale (usato per punteggio/range in
    output) -- vedi commento sopra ANTI_SYNERGY_PENALTY per la logica.
    'team_counts'/'apply_stack_guard': vedi commento sopra IN_SEASON_STACK_LIMIT.
    'apply_positive_synergy' (27/07, richiesta esplicita utente per le In
    Season con 2+ formazioni richieste, stesso fix identico in
    formazione_mls/build_formazione_finale.py): gate unico per il bonus
    DEF-GK e la penalita' soft MID/FWD-vs-avversario -- quest'ultima e'
    comunque superata da un filtro DURO in build_one_lineup quando serve
    (strict_gk_anti_synergy)."""
    adjusted = row['atteso']
    team_slug = row.get('team_slug')
    if apply_positive_synergy:
        if role in ('MID', 'FWD') and gk_opponent_slug and team_slug == gk_opponent_slug:
            adjusted -= ANTI_SYNERGY_PENALTY
        elif role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
            adjusted += POSITIVE_SYNERGY_BONUS
    if apply_stack_guard and team_slug and team_counts and team_counts.get(team_slug, 0) >= IN_SEASON_STACK_LIMIT:
        adjusted -= STACK_GUARD_PENALTY
    return adjusted


def synergy_adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug, team_counts=None, apply_stack_guard=False,
                           apply_positive_synergy=True):
    """Ritorna i candidati di un ruolo di movimento riordinati per sinergia/
    anti-sinergia col portiere scelto (vedi synergy_sort_key), ed
    eventualmente per il vincolo anti-stack In Season. Se il portiere non
    ha squadra/avversario noti (consiglio generato prima di questo
    aggiornamento, o dato di calendario mancante) e non c'e' vincolo
    anti-stack ne' sinergia positiva da applicare, non cambia nulla --
    comportamento identico a prima."""
    if not apply_stack_guard and not (apply_positive_synergy and (gk_team_slug or gk_opponent_slug)):
        return rows
    return sorted(rows, key=lambda row: synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug,
                                                           team_counts, apply_stack_guard,
                                                           apply_positive_synergy),
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
    """Legge i 6 parametri di conteggio formazioni (26/07, seconda revisione):
    NUM_TOTALE_FORMAZIONI, NUM_FORM_IN_SEASON, NUM_FORM_ARENA_260,
    NUM_FORM_ARENA_220, NUM_FORM_ARENA_UNCAPPED, NUM_FORM_ALLSTARS -- da env
    var (input workflow_dispatch). Ognuno dei 5 sotto-totali puo' essere 0
    (tipo disattivato). Compatibilita' locale: se nessuna delle 6 env var e'
    impostata, ricade sul vecchio singolo argomento CLI/env NUM_FORMAZIONI
    (comportamento pre-26/07: tutte In Season). FAIL-FAST: il totale deve
    combaciare esattamente con la somma dei 5 sotto-totali, altrimenti
    SystemExit prima di fare qualunque cosa."""
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
            f"ERRORE: NUM_TOTALE_FORMAZIONI={num_totale} non combacia con la somma dei 5 tipi "
            f"(In Season={num_in_season} + Arena cap260={num_arena_260} + Arena cap220={num_arena_220} + "
            f"Arena uncapped={num_arena_uncapped} + All Stars={num_allstars} = {somma}). "
            f"Correggi gli input del workflow -- nessuna formazione generata."
        )

    return {
        'IN_SEASON': num_in_season,
        'ARENA_260': num_arena_260,
        'ARENA_220': num_arena_220,
        'ARENA_UNCAPPED': num_arena_uncapped,
        'ALLSTARS': num_allstars,
    }, num_totale


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

    def __init__(self, counts_by_role):
        self._total = {}
        self._l10 = {}
        for role, counts in counts_by_role.items():
            for slug, breakdown in counts.items():
                cur = self._total.setdefault(slug, {'in_season': 0, 'classic': 0})
                cur['in_season'] = max(cur['in_season'], breakdown.get('in_season', 0))
                cur['classic'] = max(cur['classic'], breakdown.get('classic', 0))
                l10 = breakdown.get('l10')
                if l10 is not None:
                    self._l10[slug] = l10
        self._used = {}

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
        mai persistita (dato mancante -- vedi FIXED_L10_CAP_BY_TYPE, trattata
        come 0 nel calcolo del budget, mai come esclusione)."""
        return self._l10.get(slug)


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
    stesso fix applicato identicamente in formazione_mls/build_formazione_
    finale.py -- vedi quel file per il commento esteso). SOLO valido per
    shape con un ruolo per slot (nessuna ripetizione, es. Arena) e
    max_classic=None (vero per tutti i tipi con cap L10 oggi). Ritorna
    (picks_dict {ruolo: row, 'EXTRA': (ruolo_extra, row)}, l10_totale) o
    (None, None) se nessuna combinazione e' possibile."""
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


def build_one_lineup(shape, role_data, card_pool, l10_cap=None, apply_stack_guard=False,
                      apply_positive_synergy=True, strict_gk_anti_synergy=False):
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
    'apply_stack_guard' (SOLO In Season, vedi commento
    sopra IN_SEASON_STACK_LIMIT): scoraggia (non vieta) il 3o giocatore della
    stessa squadra nello slot extra, per non perdere per errore il bonus
    anti-stack Sorare. Ritorna (formazione, errore, l10_cap_rispettato,
    stack_bonus_perso); formazione e' una lista di tuple
    (slot_label, row, card_type). stack_bonus_perso e' True se la
    formazione finale ha comunque 3+ giocatori della stessa squadra
    (informativo, sempre False se apply_stack_guard=False).

    'apply_positive_synergy' / 'strict_gk_anti_synergy' (27/07, richiesta
    esplicita utente per le In Season con 2+ formazioni richieste, stesso
    fix identico in formazione_mls/build_formazione_finale.py): quando
    strict_gk_anti_synergy=True, i candidati MID/FWD della squadra
    AVVERSARIA del portiere vengono ESCLUSI del tutto (non solo
    deprioritizzati) -- un vero vincolo di schieramento. apply_positive_
    synergy=False disattiva anche il bonus soft DEF-GK (nessuna priorita' di
    sinergia, solo punteggio grezzo). Con una sola In Season richiesta, o
    per Arena, entrambi i flag restano ai default (comportamento INVARIATO).

    Se il knapsack ESATTO e' applicabile (l10_cap impostato, un ruolo per
    slot senza ripetizioni, max_classic=None -- vero oggi per le 3 Arene
    dedicate, MAI per In Season/All Stars che o non hanno cap o ripetono
    ruoli), lo usa al posto del vecchio greedy-con-riserva per il punteggio
    totale MASSIMO garantito sotto il cap (27/07, vedi
    _optimize_capped_lineup, stesso fix applicato identicamente in
    formazione_mls/build_formazione_finale.py)."""
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
        L10 disponibili per tutti gli slot ANCORA da riempire dopo questo).
        Se nessun candidato rientra nemmeno riservando, la formazione
        FALLISCE (nessun fallback che sfora il cap in silenzio)."""
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
            row, ctype = pick(role_data['GK'], l10_cap is not None, reserve)
        else:
            pool_rows = role_data[role]
            if strict_gk_anti_synergy and role in ('MID', 'FWD') and gk_opponent_slug:
                pool_rows = [r for r in pool_rows if r.get('team_slug') != gk_opponent_slug]
            candidates = synergy_adjusted_rows(role, pool_rows, gk_team_slug, gk_opponent_slug,
                                                team_counts, apply_stack_guard, apply_positive_synergy)
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
                                                    team_counts, apply_stack_guard, apply_positive_synergy),
                  reverse=True)

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

# Cap fisso sulla L10 combinata per tipo Arena (26/07, seconda revisione):
# ARENA_260 e ARENA_220 rispettano il tetto indicato, ARENA_UNCAPPED non e'
# in mappa -- .get(tipo) ritorna None, cioe' nessun limite.
FIXED_L10_CAP_BY_TYPE = {'ARENA_260': 260.0, 'ARENA_220': 220.0}

CAP260_BONUS = 0.04
# Soglia L10 per il bonus "cap" (In Season/All Stars, 26/07 -- confermato
# dall'utente: soft cap, si puo' sforare, si perde solo il +4%. Diverso dal
# cap L10 obbligatorio di Arena sopra, che invece vincola attivamente la
# scelta dei giocatori).
CAP260_L10_THRESHOLD_BY_TYPE = {'IN_SEASON': 260.0, 'ALLSTARS': 370.0}


def pick_captain(formazione, avoid_slugs=None):
    """Il capitano ottimale e' semplicemente il giocatore con lo score atteso
    piu' alto della formazione: dato che gli altri punteggi restano fissi
    a prescindere da chi si nomina capitano, il bonus (che sia +50% o +20%
    Arena) e' comunque una percentuale, quindi e' sempre massimizzato
    scegliendo il punteggio di partenza piu' alto tra i titolari.
    'avoid_slugs' (27/07, richiesta esplicita utente, stesso fix identico in
    formazione_mls/build_formazione_finale.py): varianza capitano tra piu'
    formazioni della STESSA competizione/tipo -- preferisce il punteggio piu'
    alto tra i non ancora capitanati, ripiega sul punteggio piu' alto
    assoluto se non c'e' alternativa."""
    if avoid_slugs:
        candidates = [p for p in formazione if p[1]['slug'] not in avoid_slugs]
        if candidates:
            return max(candidates, key=lambda pick: pick[1]['atteso'])
    return max(formazione, key=lambda pick: pick[1]['atteso'])


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


def render_card_html(slot_label, row, ctype, card_pool, is_captain):
    color = _slot_role_color(slot_label)
    role_label = re.sub(r'^EXTRA \(([A-Z]+)\)$', r'EXTRA · \1', slot_label)
    copie = card_pool.copies_owned(row['slug'])
    tags = []
    if ctype == 'classic':
        tags.append('<span class="tag tag-classic">Classic</span>')
    if copie > 1:
        tags.append(f'<span class="tag tag-copies">{copie} copie</span>')
    captain_badge = '<span class="pcard-captain">C</span>' if is_captain else ''
    return (
        f'<div class="pcard" style="--role-color:{color}">'
        f'<div class="pcard-stripe" style="background:{color}"></div>'
        f'<span class="pcard-role">{role_label}</span>'
        f'{captain_badge}'
        f'<div class="pcard-body">'
        f'<div class="pcard-avatar">{_slug_initials(row["slug"])}</div>'
        f'<div class="pcard-name">{_slug_display_name(row["slug"])}</div>'
        f'<div class="pcard-score">{row["atteso"]}</div>'
        f'<div class="pcard-range">{row["low"]}–{row["high"]} pt</div>'
        f'<div class="pcard-tags">{"".join(tags)}</div>'
        f'</div></div>'
    )


def render_lineup_html(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True,
                        stack_bonus_perso=False, check_cap260=False, tipo=None, apply_stack_guard=False,
                        avoid_captain_slugs=None):
    captain_slot, captain_row, _captain_type = pick_captain(formazione, avoid_captain_slugs)
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
    return (
        f'<div class="lineup-block"><div class="lineup-meta">'
        f'<div class="lineup-title">{tipo_label} <span>#{idx}</span></div></div>'
        f'<div class="card-strip">{cards_html}</div>'
        f'<div class="lineup-total">'
        f'<div><span class="label">Totale</span><span class="figure">{totale_atteso} pt</span></div>'
        f'<div class="divider"></div>'
        f'<div><span class="label">Con capitano</span>'
        f'<span class="figure with-captain">{totale_con_capitano} pt</span></div>'
        f'<div class="captain-note">Capitano <b>{_slug_display_name(captain_row["slug"])}</b> '
        f'(+{bonus} pt, +{captain_bonus_pct:.0%})</div>{l10_note}{stack_note}{cap260_note}'
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
  .lineup-block {{ margin-bottom: 40px; }}
  .lineup-meta {{ margin-bottom: 12px; }}
  .lineup-title {{ font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .lineup-title span {{ color: var(--text); }}
  .card-strip {{ display: flex; gap: 14px; overflow-x: auto; padding-bottom: 6px; }}
  .pcard {{
    position: relative; flex: 0 0 152px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 14px; overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.2);
  }}
  .pcard-stripe {{ height: 6px; width: 100%; }}
  .pcard-body {{ padding: 14px 12px 12px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; }}
  .pcard-role {{
    position: absolute; top: 12px; left: 12px; font-size: 0.62rem; font-weight: 700;
    letter-spacing: 0.09em; text-transform: uppercase; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 16%, transparent);
    padding: 2px 7px; border-radius: 5px;
  }}
  .pcard-captain {{
    position: absolute; top: 10px; right: 10px; width: 22px; height: 22px; border-radius: 50%;
    background: var(--gold); color: #241c00; font-size: 0.68rem; font-weight: 800;
    display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--surface);
  }}
  .pcard-avatar {{
    width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 1.05rem; color: var(--role-color);
    background: color-mix(in srgb, var(--role-color) 18%, var(--surface-2));
    border: 2px solid color-mix(in srgb, var(--role-color) 55%, transparent); margin-top: 14px;
  }}
  .pcard-name {{ font-size: 0.82rem; font-weight: 650; line-height: 1.25; min-height: 2.1em; display: flex; align-items: center; }}
  .pcard-score {{ font-size: 1.85rem; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; color: var(--role-color); }}
  .pcard-range {{ font-size: 0.68rem; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .pcard-tags {{ display: flex; gap: 4px; flex-wrap: wrap; justify-content: center; min-height: 18px; }}
  .tag {{ font-size: 0.6rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; }}
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
</body>
</html>
"""


def render_report_html(page_title, page_subhead, lineup_html_blocks, footer):
    body = "\n".join(lineup_html_blocks) if lineup_html_blocks else '<p class="error-block">Nessuna formazione generata.</p>'
    return HTML_REPORT_TEMPLATE.format(
        page_title=page_title, page_subhead=page_subhead, lineup_html=body, footer=footer)


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
    # 27/07, richiesta esplicita utente, stesso fix identico in
    # formazione_mls/build_formazione_finale.py: con 2+ In Season richieste,
    # solo la prima usa la sinergia GK-DEF soft, le altre sono greedy puro; in
    # ENTRAMBI i casi il vincolo portiere-vs-avversario diventa DURO. Con 1
    # sola In Season, o per Arena, comportamento INVARIATO.
    in_season_multi = tipo == 'IN_SEASON' and count >= 2
    # Varianza capitano (27/07, richiesta esplicita utente, stesso fix
    # identico in formazione_mls/build_formazione_finale.py): scope per tipo.
    captained_slugs = set()
    generated = 0
    totale = 0
    for idx in range(1, count + 1):
        strict_gk_anti_synergy = in_season_multi
        apply_positive_synergy = not in_season_multi or idx == 1
        formazione, error, l10_ok, stack_perso = build_one_lineup(
            shape, role_data, card_pool, l10_cap=cap, apply_stack_guard=stack_guard,
            apply_positive_synergy=apply_positive_synergy, strict_gk_anti_synergy=strict_gk_anti_synergy)
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
    # Ordine di priorita' FISSO (26/07, seconda revisione): In Season ->
    # Arena cap260 -> Arena cap220 -> Arena uncapped -> All Stars.
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
