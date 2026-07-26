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
import json
import datetime

ROLES = {
    'GK': 'formazione_kleague/output/kleague_gk_all',
    'DEF': 'formazione_kleague/output/kleague_def_all',
    'MID': 'formazione_kleague/output/kleague_mid_all',
    'FWD': 'formazione_kleague/output/kleague_fwd_all',
}

DISCOVERY_DIRS = {
    'GK': 'formazione_kleague/output/kleague_gk_discovery',
    'DEF': 'formazione_kleague/output/kleague_def_discovery',
    'MID': 'formazione_kleague/output/kleague_mid_discovery',
    'FWD': 'formazione_kleague/output/kleague_fwd_discovery',
}

OUTPUT_DIR = 'formazione_kleague/output'

CONSIGLIO_LINE_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')
# NUOVO (26/07, tema correlazione GK-DEF): riga "SQUADRA: x | AVVERSARIO: y"
# scritta subito dopo la riga consiglio da build_consiglio_<ruolo>.py.
TEAM_RE = re.compile(r'^SQUADRA:\s+(\S+)\s+\|\s+AVVERSARIO:\s+(\S+)\s*$')

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
    'ARENA': {
        'label': 'Arena',
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


def synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug):
    """Punteggio AGGIUSTATO solo per decidere l'ORDINE di scelta tra candidati
    dello stesso ruolo, dato il portiere gia' selezionato per questa lineup.
    Non altera mai 'atteso' nel dict originale (usato per punteggio/range in
    output) -- vedi commento sopra ANTI_SYNERGY_PENALTY per la logica."""
    adjusted = row['atteso']
    team_slug = row.get('team_slug')
    if role in ('MID', 'FWD') and gk_opponent_slug and team_slug == gk_opponent_slug:
        adjusted -= ANTI_SYNERGY_PENALTY
    elif role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
        adjusted += POSITIVE_SYNERGY_BONUS
    return adjusted


def synergy_adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug):
    """Ritorna i candidati di un ruolo di movimento riordinati per sinergia/
    anti-sinergia col portiere scelto (vedi synergy_sort_key). Se il portiere
    non ha squadra/avversario noti (consiglio generato prima di questo
    aggiornamento, o dato di calendario mancante), non cambia nulla --
    comportamento identico a prima."""
    if not gk_team_slug and not gk_opponent_slug:
        return rows
    return sorted(rows, key=lambda row: synergy_sort_key(role, row, gk_team_slug, gk_opponent_slug),
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
        for k in ('NUM_TOTALE_FORMAZIONI', 'NUM_FORM_IN_SEASON', 'NUM_FORM_ARENA', 'NUM_FORM_ALLSTARS')
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
        return {'IN_SEASON': n, 'ARENA': 0, 'ALLSTARS': 0}, n

    num_totale = _read_int_env('NUM_TOTALE_FORMAZIONI', 0)
    num_in_season = _read_int_env('NUM_FORM_IN_SEASON', 0)
    num_arena = _read_int_env('NUM_FORM_ARENA', 0)
    num_allstars = _read_int_env('NUM_FORM_ALLSTARS', 0)

    somma = num_in_season + num_arena + num_allstars
    if num_totale != somma:
        raise SystemExit(
            f"ERRORE: NUM_TOTALE_FORMAZIONI={num_totale} non combacia con la somma dei 3 tipi "
            f"(In Season={num_in_season} + Arena={num_arena} + All Stars={num_allstars} = {somma}). "
            f"Correggi gli input del workflow -- nessuna formazione generata."
        )

    return {'IN_SEASON': num_in_season, 'ARENA': num_arena, 'ALLSTARS': num_allstars}, num_totale


def get_arena_l10_cap():
    """Cap opzionale sulla L10 combinata per le formazioni Arena (26/07,
    richiesta esplicita dell'utente). None = tuning disattivato (default)."""
    val = os.environ.get('ARENA_L10_CAP')
    if val is None or val.strip() == '':
        return None
    try:
        return float(val)
    except ValueError:
        return None


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
                           'team_slug': None, 'opponent_team_slug': None}
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
        mai persistita (dato mancante -- vedi ARENA_L10_CAP, trattata come 0
        nel calcolo del budget, mai come esclusione)."""
        return self._l10.get(slug)


def build_one_lineup(shape, role_data, card_pool, l10_cap=None):
    """Costruisce UNA formazione secondo 'shape' (uno dei FORMATION_SHAPES),
    tenendo conto delle copie gia' esaurite (card_pool) e del vincolo
    max_classic della shape (None = nessun vincolo). Se l10_cap e' impostato
    (SOLO Arena), applica l'euristica greedy a budget residuo descritta nel
    docstring del modulo. Ritorna (formazione, errore, l10_cap_rispettato);
    formazione e' una lista di tuple (slot_label, row, card_type)."""
    used_this_lineup = set()
    classic_budget_used = [0]
    max_classic = shape['max_classic']
    l10_used = [0.0]
    l10_cap_rispettato = [True]

    def pick(pool_rows, role_slot_l10_check):
        """role_slot_l10_check: se l10_cap e' impostato, filtra/ordina i
        candidati rispettando il budget residuo; altrimenti comportamento
        identico a prima (solo copie/classic_budget)."""
        candidates = [r for r in pool_rows if r['slug'] not in used_this_lineup]
        if l10_cap is not None and role_slot_l10_check:
            budget_residuo = l10_cap - l10_used[0]
            entro_budget = [r for r in candidates if (card_pool.l10(r['slug']) or 0.0) <= budget_residuo]
            if entro_budget:
                candidates = entro_budget
            else:
                # Nessun candidato rispetta il budget residuo: ripiega sul
                # piu' economico disponibile (limite noto, vedi docstring).
                candidates = sorted(candidates, key=lambda r: (card_pool.l10(r['slug']) or 0.0))
                l10_cap_rispettato[0] = False

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

    for role in shape['role_slots']:
        role_occurrence[role] += 1
        slot_label = role if role_slot_counts[role] == 1 else f"{role}{role_occurrence[role]}"

        if role == 'GK':
            row, ctype = pick(role_data['GK'], l10_cap is not None)
        else:
            candidates = synergy_adjusted_rows(role, role_data[role], gk_team_slug, gk_opponent_slug)
            row, ctype = pick(candidates, l10_cap is not None)

        if row is None:
            return None, f"Nessun candidato disponibile per lo slot {slot_label} (copie esaurite o consiglio vuoto).", l10_cap_rispettato[0]

        used_this_lineup.add(row['slug'])
        if ctype == 'classic':
            classic_budget_used[0] += 1
        if l10_cap is not None:
            l10_used[0] += card_pool.l10(row['slug']) or 0.0
        picks.append((slot_label, row, ctype))

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
            combined.append((role, row))
    combined.sort(key=lambda rc: synergy_sort_key(rc[0], rc[1], gk_team_slug, gk_opponent_slug), reverse=True)

    extra_candidates = [(role, row) for role, row in combined if row['slug'] not in used_this_lineup]
    if l10_cap is not None:
        budget_residuo = l10_cap - l10_used[0]
        entro_budget = [(role, row) for role, row in extra_candidates
                        if (card_pool.l10(row['slug']) or 0.0) <= budget_residuo]
        if entro_budget:
            extra_candidates = entro_budget
        else:
            extra_candidates = sorted(extra_candidates, key=lambda rc: (card_pool.l10(rc[1]['slug']) or 0.0))
            l10_cap_rispettato[0] = False

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
        return None, "Nessun candidato disponibile per lo slot extra (copie esaurite).", l10_cap_rispettato[0]

    picks.append((f'EXTRA ({extra_role})', extra_pick, extra_type))

    for _slot, row, ctype in picks:
        card_pool.use(row['slug'], ctype)

    return picks, None, l10_cap_rispettato[0]


CAPTAIN_BONUS = 0.5  # il capitano riceve +50% sul proprio punteggio (regola Sorare)


def pick_captain(formazione):
    """Il capitano ottimale e' semplicemente il giocatore con lo score atteso
    piu' alto della formazione: dato che gli altri punteggi restano fissi
    a prescindere da chi si nomina capitano, il bonus +50% e' massimizzato
    scegliendo sempre il punteggio di partenza piu' alto tra i titolari."""
    return max(formazione, key=lambda pick: pick[1]['atteso'])


def format_lineup(tipo_label, idx, formazione, card_pool, l10_cap=None, l10_cap_rispettato=True):
    lines = []
    lines.append(f"--- Formazione {tipo_label} #{idx} ---")
    captain_slot, captain_row, _captain_type = pick_captain(formazione)
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

    bonus = round(captain_row['atteso'] * CAPTAIN_BONUS)
    totale_con_capitano = totale_atteso + bonus
    lines.append(f"TOTALE: {totale_atteso} pt ({totale_low}-{totale_high})")
    lines.append(f"CAPITANO CONSIGLIATO: {captain_row['slug']} (+{bonus} pt, +{CAPTAIN_BONUS:.0%}) "
                 f"-> TOTALE CON CAPITANO: {totale_con_capitano} pt")
    if l10_cap is not None:
        stato = "OK" if l10_cap_rispettato else "NON RISPETTATO (nessun candidato entro budget, preso il piu' economico disponibile)"
        lines.append(f"L10 combinata: {totale_l10:.1f} / cap {l10_cap:.1f} -- {stato}")
    return "\n".join(lines), totale_atteso


def generate_lineups_for_type(tipo, count, role_data, card_pool, l10_cap, lineup_blocks, print_output=True):
    """Genera fino a 'count' formazioni del tipo 'tipo' (chiave di
    FORMATION_SHAPES), aggiungendo i blocchi di testo a lineup_blocks.
    Ritorna (generate, totale_punti). Si ferma in anticipo (senza errore
    globale) se il pool si esaurisce per questo tipo, ma NON impedisce la
    generazione del tipo successivo in ordine di priorita'."""
    shape = FORMATION_SHAPES[tipo]
    cap = l10_cap if tipo == 'ARENA' else None
    generated = 0
    totale = 0
    for idx in range(1, count + 1):
        formazione, error, l10_ok = build_one_lineup(shape, role_data, card_pool, l10_cap=cap)
        if error:
            msg = f"Formazione {shape['label']} #{idx}: NON GENERATA — {error}"
            if print_output:
                print(f"\n{msg}")
            lineup_blocks.append(msg)
            break
        block_text, punti = format_lineup(shape['label'], idx, formazione, card_pool,
                                           l10_cap=cap, l10_cap_rispettato=l10_ok)
        lineup_blocks.append(block_text)
        totale += punti
        generated += 1
        if print_output:
            print("\n" + block_text)
    return generated, totale


def main():
    counts, num_totale = get_formation_counts()
    l10_cap = get_arena_l10_cap()
    role_data, role_files, role_counts, counts_files = load_all_roles()

    print(f"Formazioni richieste: totale={num_totale} "
          f"(In Season={counts['IN_SEASON']}, Arena={counts['ARENA']}, All Stars={counts['ALLSTARS']})")
    if l10_cap is not None:
        print(f"Tuning Arena L10 cap attivo: {l10_cap:.1f}")
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
                         f"Arena={counts['ARENA']}, All Stars={counts['ALLSTARS']})")
    if l10_cap is not None:
        header_lines.append(f"Tuning Arena L10 cap: {l10_cap:.1f}")
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
    generated_by_type = {}
    grand_total = 0
    # Ordine di priorita' FISSO (26/07): In Season -> Arena -> All Stars.
    for tipo in ('IN_SEASON', 'ARENA', 'ALLSTARS'):
        n_richieste = counts[tipo]
        if n_richieste <= 0:
            generated_by_type[tipo] = 0
            continue
        generated, totale = generate_lineups_for_type(
            tipo, n_richieste, role_data, card_pool, l10_cap, lineup_blocks)
        generated_by_type[tipo] = generated
        grand_total += totale

    total_generated = sum(generated_by_type.values())

    footer_lines = []
    footer_lines.append("-" * 70)
    footer_lines.append(f"Formazioni generate: {total_generated}/{num_totale} "
                         f"(In Season {generated_by_type.get('IN_SEASON', 0)}/{counts['IN_SEASON']}, "
                         f"Arena {generated_by_type.get('ARENA', 0)}/{counts['ARENA']}, "
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


if __name__ == '__main__':
    main()
