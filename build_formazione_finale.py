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

LOGICA MULTI-FORMAZIONE (NUM_FORMAZIONI, default 1):
Un giocatore usato in una lineup NON puo' essere riusato in una lineup
successiva, A MENO CHE non si possiedano piu' copie della sua carta
IN_SEASON. Il numero di copie possedute viene letto da
mls_<ruolo>_discovery/player_card_counts.json (prodotto dagli script di
discovery aggiornati il 25/07 -- se il file non esiste ancora, per esempio
perche' la discovery non e' stata rilanciata dopo l'aggiornamento, si assume
1 copia di default per ogni giocatore). Ogni copia posseduta = un possibile
utilizzo in una lineup diversa (stesso giocatore, carta fisica diversa).

Se un ruolo esaurisce i candidati disponibili (copie finite) prima di
raggiungere NUM_FORMAZIONI, la generazione si ferma li' e lo segnala.

LIMITE NOTO (da affrontare in fase di raffinamento): la regola "max 1 carta
CLASSIC per formazione, resto IN_SEASON" NON e' ancora applicata qui — le
discovery di ruolo filtrano solo carte in_season_eligible:true, le carte
CLASSIC non sono ancora scansionate. Per ora ogni formazione e' quindi
composta solo da carte IN_SEASON.
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
    """Carica slug -> numero di copie possedute, da player_card_counts.json.
    Se il file non esiste (discovery non ancora rilanciata dopo l'aggiornamento
    del 25/07), ritorna un dict vuoto: il chiamante assumera' 1 copia di
    default per ogni giocatore non presente."""
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
    """Traccia quante copie di ogni giocatore restano disponibili, attraverso
    tutte le formazioni generate in questa run. Default 1 copia per uno slug
    non presente nel relativo player_card_counts.json (dato non ancora
    tracciato, o giocatore con una sola carta posseduta)."""

    def __init__(self, counts_by_role):
        self._total = {}
        for role, counts in counts_by_role.items():
            for slug, n in counts.items():
                self._total[slug] = max(self._total.get(slug, 0), n)
        self._used = {}

    def remaining(self, slug):
        return self._total.get(slug, 1) - self._used.get(slug, 0)

    def use(self, slug):
        self._used[slug] = self._used.get(slug, 0) + 1

    def copies_owned(self, slug):
        return self._total.get(slug, 1)


def pick_best(pool_rows, card_pool, exclude_slugs):
    for row in pool_rows:
        if row['slug'] in exclude_slugs:
            continue
        if card_pool.remaining(row['slug']) <= 0:
            continue
        return row
    return None


def build_one_lineup(role_data, card_pool):
    """Costruisce UNA formazione tenendo conto delle copie gia' esaurite nelle
    formazioni precedenti (tramite card_pool). Ritorna (formazione, errore)."""
    used_this_lineup = set()

    gk = pick_best(role_data['GK'], card_pool, used_this_lineup)
    if gk is None:
        return None, "Nessun portiere disponibile (copie esaurite o consiglio GK vuoto)."
    used_this_lineup.add(gk['slug'])

    def_pick = pick_best(role_data['DEF'], card_pool, used_this_lineup)
    if def_pick is None:
        return None, "Nessun difensore disponibile (copie esaurite o consiglio DEF vuoto)."
    used_this_lineup.add(def_pick['slug'])

    mid_pick = pick_best(role_data['MID'], card_pool, used_this_lineup)
    if mid_pick is None:
        return None, "Nessun centrocampista disponibile (copie esaurite o consiglio MID vuoto)."
    used_this_lineup.add(mid_pick['slug'])

    fwd_pick = pick_best(role_data['FWD'], card_pool, used_this_lineup)
    if fwd_pick is None:
        return None, "Nessun attaccante disponibile (copie esaurite o consiglio FWD vuoto)."
    used_this_lineup.add(fwd_pick['slug'])

    # Extra: il migliore rimanente tra DEF/MID/FWD (esclusi i titolari di
    # QUESTA lineup e le copie gia' esaurite), a prescindere dal ruolo.
    combined = []
    for role in ('DEF', 'MID', 'FWD'):
        for row in role_data[role]:
            combined.append((role, row))
    combined.sort(key=lambda rc: rc[1]['atteso'], reverse=True)

    extra_role, extra_pick = None, None
    for role, row in combined:
        if row['slug'] in used_this_lineup:
            continue
        if card_pool.remaining(row['slug']) <= 0:
            continue
        extra_role, extra_pick = role, row
        break

    if extra_pick is None:
        return None, "Nessun candidato disponibile per lo slot extra (copie esaurite)."

    for row in (gk, def_pick, mid_pick, fwd_pick, extra_pick):
        card_pool.use(row['slug'])

    formazione = [
        ('GK', gk),
        ('DEF', def_pick),
        ('MID', mid_pick),
        ('FWD', fwd_pick),
        (f'EXTRA ({extra_role})', extra_pick),
    ]
    return formazione, None


def format_lineup(idx, formazione, card_pool):
    lines = []
    lines.append(f"--- Formazione #{idx} ---")
    totale_atteso = totale_low = totale_high = 0
    for slot, row in formazione:
        copie = card_pool.copies_owned(row['slug'])
        nota_copie = f" [{copie} copie possedute]" if copie > 1 else ""
        lines.append(f"{slot:<12} {row['slug']}: {row['atteso']} pt ({row['low']}-{row['high']}){nota_copie}")
        totale_atteso += row['atteso']
        totale_low += row['low']
        totale_high += row['high']
    lines.append(f"TOTALE: {totale_atteso} pt ({totale_low}-{totale_high})")
    return "\n".join(lines), totale_atteso


def main():
    num_formazioni = get_num_formazioni()
    role_data, role_files, role_counts, counts_files = load_all_roles()

    print(f"Formazioni richieste: {num_formazioni}\n")
    for role, path in role_files.items():
        n = len(role_data.get(role) or [])
        print(f"[{role}] {path or 'NESSUN FILE TROVATO'} -> {n} giocatori disponibili")
    for role, path in counts_files.items():
        print(f"[{role}] player_card_counts.json: {path or 'MANCANTE (default 1 copia/giocatore)'}")

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
        header_lines.append(f"  {role}: {path or 'MANCANTE (assunta 1 copia per ogni giocatore)'}")
    header_lines.append("")
    header_lines.append("-" * 70)

    lineup_blocks = []
    grand_total = 0
    for idx in range(1, num_formazioni + 1):
        formazione, error = build_one_lineup(role_data, card_pool)
        if error:
            print(f"\nFormazione #{idx}: FERMATO — {error}")
            lineup_blocks.append(f"Formazione #{idx}: NON GENERATA — {error}")
            break
        block_text, totale = format_lineup(idx, formazione, card_pool)
        lineup_blocks.append(block_text)
        grand_total += totale
        print("\n" + block_text)

    footer_lines = []
    footer_lines.append("-" * 70)
    footer_lines.append(f"Formazioni generate: {len([b for b in lineup_blocks if b.startswith('---')])}/{num_formazioni}")
    if len([b for b in lineup_blocks if b.startswith('---')]) > 1:
        footer_lines.append(f"TOTALE COMPLESSIVO (tutte le formazioni): {grand_total} pt")
    footer_lines.append("=" * 70)
    footer_lines.append("")
    footer_lines.append("NOTA: formazioni composte solo da carte IN_SEASON (le carte CLASSIC")
    footer_lines.append("non sono ancora scansionate — regola 'max 1 classic' da implementare")
    footer_lines.append("in fase di raffinamento). Un giocatore e' riusato in piu' lineup solo")
    footer_lines.append("se se ne possiedono piu' copie IN_SEASON (player_card_counts.json).")

    full_text = "\n".join(header_lines) + "\n\n" + "\n\n".join(lineup_blocks) + "\n\n" + "\n".join(footer_lines)
    print("\n" + "\n".join(footer_lines))

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join('.', f'formazione_finale_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
