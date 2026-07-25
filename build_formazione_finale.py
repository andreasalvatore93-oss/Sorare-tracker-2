"""
build_formazione_finale.py

Fusione finale: legge l'ultimo consiglio_<timestamp>.txt gia' prodotto da
ciascuno dei 4 ruoli (mls_fwd_all/, mls_mid_all/, mls_def_all/, mls_gk_all/,
gia' generati dai rispettivi workflow di produzione discover->predict->merge)
e ne ricava fino a N formazioni ottimali: 1 GK, 1 DEF, 1 MID, 1 FWD, 1 extra
(DEF/MID/FWD, mai GK) — massimizzando la somma degli score attesi.

Nessuna chiamata GraphQL: puramente locale sui file gia' committati, quindi
istantaneo. Va rilanciato dopo ogni aggiornamento dei consigli di ruolo per
restare aggiornato (i file consiglio_*.txt piu' recenti per cartella sono
sempre quelli usati).

REGOLA "MAX 1 CLASSIC PER FORMAZIONE, MIN 4 IN_SEASON" (25/07, implementata):
Le discovery di ruolo scansionano SIA carte IN_SEASON che CLASSIC, e
player_card_counts.json riporta le copie possedute separate per tipo
({'in_season': n, 'classic': m}). LA SCELTA DEL GIOCATORE PER OGNI SLOT E'
GUIDATA SOLO DALLO SCORE ATTESO, MAI DAL TIPO DI CARTA: si scorre la
classifica del ruolo (gia' ordinata per score decrescente) e si prende il
primo giocatore disponibile, sia la sua carta migliore IN_SEASON o CLASSIC
— un giocatore col punteggio piu' alto viene scelto anche se posseduto
SOLO in classic. Il tipo di carta entra in gioco unicamente per decidere
QUALE copia dello stesso giocatore consumare: se un giocatore ha sia
IN_SEASON che CLASSIC disponibili, si consuma prima la copia IN_SEASON
(irrilevante per lo score, ma preserva l'unico slot CLASSIC della
formazione per un eventuale altro giocatore che ne ha davvero bisogno).
Una carta CLASSIC viene usata solo se il giocatore non ha piu' copie
IN_SEASON disponibili E lo slot CLASSIC della formazione (max 1, quindi
min 4 IN_SEASON sui 5 totali) e' ancora libero; altrimenti si passa al
prossimo migliore in classifica.
NOTA: l'assegnazione dei 5 slot (GK, DEF, MID, FWD, EXTRA) e' greedy in
quest'ordine fisso — in rari casi di contesa tra piu' ruoli per l'unico
slot classic disponibile, potrebbe non essere l'allocazione a somma
assoluta massima (ottimizzazione globale non implementata, complessita'
non giustificata per un caso limite).

LOGICA MULTI-FORMAZIONE (NUM_FORMAZIONI, default 1):
Un giocatore usato in una lineup NON puo' essere riusato in una lineup
successiva, A MENO CHE non si possiedano piu' copie della sua carta (dello
stesso tipo o no: ogni copia, in_season o classic, e' un utilizzo possibile
in una lineup diversa). Se un ruolo esaurisce i candidati disponibili
(copie finite) prima di raggiungere NUM_FORMAZIONI, la generazione si
ferma li' e lo segnala.

Se player_card_counts.json non esiste ancora per un ruolo (discovery non
rilanciata dopo l'aggiornamento del 25/07), si assume 1 copia IN_SEASON di
default per ogni giocatore di quel ruolo non presente nel file.
"""
import os
import re
import sys
import glob
import json
import datetime

ROLES = {
    'GK': 'mls_gk_all',
    'DEF': 'mls_def_all',
    'MID': 'mls_mid_all',
    'FWD': 'mls_fwd_all',
}

DISCOVERY_DIRS = {
    'GK': 'mls_gk_discovery',
    'DEF': 'mls_def_discovery',
    'MID': 'mls_mid_discovery',
    'FWD': 'mls_fwd_discovery',
}

CONSIGLIO_LINE_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')

DEFAULT_NUM_FORMAZIONI = 1


def get_num_formazioni():
    """Legge il numero di formazioni richieste da: argomento CLI, poi env var
    NUM_FORMAZIONI (per l'input del workflow GitHub Actions), poi default 1."""
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
            if n >= 1:
                return n
        except ValueError:
            pass
    env_val = os.environ.get('NUM_FORMAZIONI')
    if env_val:
        try:
            n = int(env_val)
            if n >= 1:
                return n
        except ValueError:
            pass
    return DEFAULT_NUM_FORMAZIONI


def latest_consiglio(output_dir):
    matches = sorted(glob.glob(os.path.join(output_dir, 'consiglio_*.txt')))
    return matches[-1] if matches else None


def parse_consiglio(path):
    """Ritorna lista ordinata di dict {slug, atteso, low, high} nell'ordine
    gia' presente nel file (score decrescente, come prodotto da build_consiglio_<ruolo>.py)."""
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            m = CONSIGLIO_LINE_RE.match(line.strip())
            if m:
                slug, atteso, low, high = m.groups()
                rows.append({'slug': slug, 'atteso': int(atteso), 'low': int(low), 'high': int(high)})
    return rows


def load_card_counts(discovery_dir):
    """Carica slug -> {'in_season': n, 'classic': m}, da player_card_counts.json.
    Se il file non esiste (discovery non ancora rilanciata dopo l'aggiornamento
    del 25/07 che ha aggiunto lo scan classic), ritorna un dict vuoto: il
    chiamante assumera' 1 copia IN_SEASON di default per ogni giocatore non
    presente."""
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
    disponibili, attraverso tutte le formazioni generate in questa run.
    Default: 1 copia IN_SEASON (0 classic) per uno slug non presente nel
    relativo player_card_counts.json (dato non ancora tracciato per quel
    ruolo, o giocatore con una sola carta posseduta)."""

    def __init__(self, counts_by_role):
        self._total = {}
        for role, counts in counts_by_role.items():
            for slug, breakdown in counts.items():
                cur = self._total.setdefault(slug, {'in_season': 0, 'classic': 0})
                cur['in_season'] = max(cur['in_season'], breakdown.get('in_season', 0))
                cur['classic'] = max(cur['classic'], breakdown.get('classic', 0))
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


def build_one_lineup(role_data, card_pool):
    """Costruisce UNA formazione tenendo conto delle copie gia' esaurite nelle
    formazioni precedenti (tramite card_pool) e del vincolo max 1 carta
    CLASSIC per formazione (classic_budget). Ritorna (formazione, errore);
    formazione e' una lista di tuple (slot, row, card_type)."""
    used_this_lineup = set()
    classic_budget = [0]  # 0 o 1: quante carte classic sono gia' state usate in QUESTA lineup

    def pick(pool_rows):
        for row in pool_rows:
            slug = row['slug']
            if slug in used_this_lineup:
                continue
            if card_pool.remaining_in_season(slug) > 0:
                return row, 'in_season'
            if classic_budget[0] < 1 and card_pool.remaining_classic(slug) > 0:
                return row, 'classic'
        return None, None

    picks = []

    gk, gk_type = pick(role_data['GK'])
    if gk is None:
        return None, "Nessun portiere disponibile (copie esaurite o consiglio GK vuoto)."
    used_this_lineup.add(gk['slug'])
    if gk_type == 'classic':
        classic_budget[0] += 1
    picks.append(('GK', gk, gk_type))

    def_pick, def_type = pick(role_data['DEF'])
    if def_pick is None:
        return None, "Nessun difensore disponibile (copie esaurite o consiglio DEF vuoto)."
    used_this_lineup.add(def_pick['slug'])
    if def_type == 'classic':
        classic_budget[0] += 1
    picks.append(('DEF', def_pick, def_type))

    mid_pick, mid_type = pick(role_data['MID'])
    if mid_pick is None:
        return None, "Nessun centrocampista disponibile (copie esaurite o consiglio MID vuoto)."
    used_this_lineup.add(mid_pick['slug'])
    if mid_type == 'classic':
        classic_budget[0] += 1
    picks.append(('MID', mid_pick, mid_type))

    fwd_pick, fwd_type = pick(role_data['FWD'])
    if fwd_pick is None:
        return None, "Nessun attaccante disponibile (copie esaurite o consiglio FWD vuoto)."
    used_this_lineup.add(fwd_pick['slug'])
    if fwd_type == 'classic':
        classic_budget[0] += 1
    picks.append(('FWD', fwd_pick, fwd_type))

    # Extra: il migliore rimanente tra DEF/MID/FWD (esclusi i titolari di
    # QUESTA lineup, le copie gia' esaurite, e rispettando il classic_budget),
    # a prescindere dal ruolo.
    combined = []
    for role in ('DEF', 'MID', 'FWD'):
        for row in role_data[role]:
            combined.append((role, row))
    combined.sort(key=lambda rc: rc[1]['atteso'], reverse=True)

    extra_role = extra_pick = extra_type = None
    for role, row in combined:
        slug = row['slug']
        if slug in used_this_lineup:
            continue
        if card_pool.remaining_in_season(slug) > 0:
            extra_role, extra_pick, extra_type = role, row, 'in_season'
            break
        if classic_budget[0] < 1 and card_pool.remaining_classic(slug) > 0:
            extra_role, extra_pick, extra_type = role, row, 'classic'
            break

    if extra_pick is None:
        return None, "Nessun candidato disponibile per lo slot extra (copie esaurite)."

    picks.append((f'EXTRA ({extra_role})', extra_pick, extra_type))

    for _slot, row, ctype in picks:
        card_pool.use(row['slug'], ctype)

    return picks, None


CAPTAIN_BONUS = 0.5  # il capitano riceve +50% sul proprio punteggio (regola Sorare)


def pick_captain(formazione):
    """Il capitano ottimale e' semplicemente il giocatore con lo score atteso
    piu' alto della formazione: dato che gli altri 4 punteggi restano fissi
    a prescindere da chi si nomina capitano, il bonus +50% e' massimizzato
    scegliendo sempre il punteggio di partenza piu' alto tra i 5."""
    return max(formazione, key=lambda pick: pick[1]['atteso'])


def format_lineup(idx, formazione, card_pool):
    lines = []
    lines.append(f"--- Formazione #{idx} ---")
    captain_slot, captain_row, _captain_type = pick_captain(formazione)
    totale_atteso = totale_low = totale_high = 0
    for slot, row, ctype in formazione:
        tag = " [CLASSIC]" if ctype == 'classic' else ""
        copie = card_pool.copies_owned(row['slug'])
        nota_copie = f" ({copie} copie possedute)" if copie > 1 else ""
        cap_tag = " [C]" if row['slug'] == captain_row['slug'] else ""
        lines.append(f"{slot:<12} {row['slug']}: {row['atteso']} pt ({row['low']}-{row['high']}){tag}{nota_copie}{cap_tag}")
        totale_atteso += row['atteso']
        totale_low += row['low']
        totale_high += row['high']

    bonus = round(captain_row['atteso'] * CAPTAIN_BONUS)
    totale_con_capitano = totale_atteso + bonus
    lines.append(f"TOTALE: {totale_atteso} pt ({totale_low}-{totale_high})")
    lines.append(f"CAPITANO CONSIGLIATO: {captain_row['slug']} (+{bonus} pt, +{CAPTAIN_BONUS:.0%}) "
                 f"-> TOTALE CON CAPITANO: {totale_con_capitano} pt")
    return "\n".join(lines), totale_atteso


def main():
    num_formazioni = get_num_formazioni()
    role_data, role_files, role_counts, counts_files = load_all_roles()

    print(f"Formazioni richieste: {num_formazioni}\n")
    for role, path in role_files.items():
        n = len(role_data.get(role) or [])
        print(f"[{role}] {path or 'NESSUN FILE TROVATO'} -> {n} giocatori disponibili")
    for role, path in counts_files.items():
        print(f"[{role}] player_card_counts.json: {path or 'MANCANTE (default 1 copia in_season/giocatore)'}")

    if not all(role_data.get(r) for r in ROLES):
        print("\nERRORE: almeno un ruolo non ha consiglio disponibile, impossibile generare formazioni.")
        return

    card_pool = CardPool(role_counts)

    header_lines = []
    header_lines.append("=" * 70)
    header_lines.append("FORMAZIONE OTTIMALE — FUSIONE FINALE")
    header_lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    header_lines.append(f"Formazioni richieste: {num_formazioni}")
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
    grand_total = 0
    generated = 0
    for idx in range(1, num_formazioni + 1):
        formazione, error = build_one_lineup(role_data, card_pool)
        if error:
            print(f"\nFormazione #{idx}: FERMATO — {error}")
            lineup_blocks.append(f"Formazione #{idx}: NON GENERATA — {error}")
            break
        block_text, totale = format_lineup(idx, formazione, card_pool)
        lineup_blocks.append(block_text)
        grand_total += totale
        generated += 1
        print("\n" + block_text)

    footer_lines = []
    footer_lines.append("-" * 70)
    footer_lines.append(f"Formazioni generate: {generated}/{num_formazioni}")
    if generated > 1:
        footer_lines.append(f"TOTALE COMPLESSIVO (tutte le formazioni): {grand_total} pt")
    footer_lines.append("=" * 70)
    footer_lines.append("")
    footer_lines.append("NOTA: max 1 carta CLASSIC per formazione (contrassegnata [CLASSIC]),")
    footer_lines.append("resto IN_SEASON — preferenza automatica per copie IN_SEASON quando")
    footer_lines.append("disponibili. Un giocatore e' riusato in piu' lineup solo se se ne")
    footer_lines.append("possiedono piu' copie (player_card_counts.json).")

    full_text = "\n".join(header_lines) + "\n\n" + "\n\n".join(lineup_blocks) + "\n\n" + "\n".join(footer_lines)
    print("\n" + "\n".join(footer_lines))

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join('.', f'formazione_finale_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
