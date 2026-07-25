"""
build_formazione_finale.py

Fusione finale: legge l'ultimo consiglio_<timestamp>.txt gia' prodotto da
ciascuno dei 4 ruoli (mls_fwd_all/, mls_mid_all/, mls_def_all/, mls_gk_all/,
gia' generati dai rispettivi workflow di produzione discover->predict->merge)
e ne ricava la formazione ottimale: 1 GK, 1 DEF, 1 MID, 1 FWD, 1 extra
(DEF/MID/FWD, mai GK) — massimizzando la somma degli score attesi.

Nessuna chiamata GraphQL: puramente locale sui file gia' committati, quindi
istantaneo. Va rilanciato dopo ogni aggiornamento dei consigli di ruolo per
restare aggiornato (i file consiglio_*.txt piu' recenti per cartella sono
sempre quelli usati).

LIMITE NOTO (da affrontare in fase di raffinamento): la regola "max 1 carta
CLASSIC per formazione, resto IN_SEASON" NON e' ancora applicata qui — le
discovery di ruolo filtrano solo carte in_season_eligible:true, le carte
CLASSIC non sono ancora scansionate. Per ora la formazione e' quindi
composta solo da carte IN_SEASON.
"""
import os
import re
import glob
import datetime

ROLES = {
    'GK': 'mls_gk_all',
    'DEF': 'mls_def_all',
    'MID': 'mls_mid_all',
    'FWD': 'mls_fwd_all',
}

CONSIGLIO_LINE_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt\s+\((-?\d+)-(-?\d+)\)\s*$')


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


def load_all_roles():
    role_data = {}
    role_files = {}
    for role, out_dir in ROLES.items():
        path = latest_consiglio(out_dir)
        if not path:
            role_data[role] = []
            role_files[role] = None
            continue
        role_files[role] = path
        role_data[role] = parse_consiglio(path)
    return role_data, role_files


def build_formazione(role_data):
    """Sceglie 1 GK, 1 DEF, 1 MID, 1 FWD (i migliori di ciascun ruolo) + 1 extra
    (il migliore rimanente tra DEF/MID/FWD, mai GK, escludendo i 3 gia' scelti)."""
    if not role_data.get('GK'):
        return None, "Nessun portiere disponibile (consiglio GK vuoto o mancante)."
    if not role_data.get('DEF'):
        return None, "Nessun difensore disponibile (consiglio DEF vuoto o mancante)."
    if not role_data.get('MID'):
        return None, "Nessun centrocampista disponibile (consiglio MID vuoto o mancante)."
    if not role_data.get('FWD'):
        return None, "Nessun attaccante disponibile (consiglio FWD vuoto o mancante)."

    gk = role_data['GK'][0]
    def_pick = role_data['DEF'][0]
    mid_pick = role_data['MID'][0]
    fwd_pick = role_data['FWD'][0]

    # Extra: il migliore rimanente tra DEF/MID/FWD (esclusi i titolari gia' scelti in quei ruoli).
    extra_candidates = []
    for role in ('DEF', 'MID', 'FWD'):
        for row in role_data[role][1:]:  # esclude il titolare di quel ruolo (indice 0)
            extra_candidates.append((role, row))
    if not extra_candidates:
        return None, "Nessun candidato disponibile per lo slot extra (servono almeno 2 giocatori in almeno un ruolo tra DEF/MID/FWD)."

    extra_role, extra_pick = max(extra_candidates, key=lambda rc: rc[1]['atteso'])

    formazione = [
        ('GK', gk),
        ('DEF', def_pick),
        ('MID', mid_pick),
        ('FWD', fwd_pick),
        (f'EXTRA ({extra_role})', extra_pick),
    ]
    return formazione, None


def format_output(formazione, role_files):
    lines = []
    lines.append("=" * 70)
    lines.append("FORMAZIONE OTTIMALE — FUSIONE FINALE")
    lines.append(f"Generato: {datetime.datetime.utcnow().isoformat()}Z")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Fonte consigli di ruolo (piu' recenti in repo):")
    for role, path in role_files.items():
        lines.append(f"  {role}: {path or 'MANCANTE'}")
    lines.append("")
    lines.append("-" * 70)

    totale_atteso = 0
    totale_low = 0
    totale_high = 0
    for slot, row in formazione:
        lines.append(f"{slot:<12} {row['slug']}: {row['atteso']} pt ({row['low']}-{row['high']})")
        totale_atteso += row['atteso']
        totale_low += row['low']
        totale_high += row['high']

    lines.append("-" * 70)
    lines.append(f"TOTALE ATTESO: {totale_atteso} pt ({totale_low}-{totale_high})")
    lines.append("=" * 70)
    lines.append("")
    lines.append("NOTA: formazione composta solo da carte IN_SEASON (le carte CLASSIC")
    lines.append("non sono ancora scansionate — regola 'max 1 classic' da implementare")
    lines.append("in fase di raffinamento).")
    return "\n".join(lines)


def main():
    role_data, role_files = load_all_roles()

    for role, path in role_files.items():
        n = len(role_data.get(role) or [])
        print(f"[{role}] {path or 'NESSUN FILE TROVATO'} -> {n} giocatori disponibili")

    formazione, error = build_formazione(role_data)
    if error:
        print(f"\nERRORE: {error}")
        return

    text = format_output(formazione, role_files)
    print("\n" + text)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join('.', f'formazione_finale_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
