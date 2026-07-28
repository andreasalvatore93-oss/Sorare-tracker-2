"""
Genera SOLO il riepilogo finale compatto "Consiglio attaccanti" leggendo i
file prediction_<slug>_*.txt gia' prodotti dal job matrix (uno per
giocatore). Nessun dump completo: poche righe, ordine di schieramento.
"""
import os
import re
import json
import glob
import datetime

OUTPUT_DIR = 'formazione_mls/output/mls_fwd_all'
DISCOVERY_FILE = os.path.join('formazione_mls/output/mls_fwd_discovery', 'player_slugs.json')

# Pattern della riga "N) slug: X pt attesi (low-high)" gia' scritta da
# test_mls_fwd_all.py nel riepilogo di ciascun job (uno per giocatore, quindi
# sempre riga singola "1) ...").
CONSIGLIO_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt attesi\s+\((-?\d+)-(-?\d+)\)\s*$')
ESCLUSO_RE = re.compile(r'^([\w-]+):\s+(ESCLUSO|DATI INSUFFICIENTI)\s+—\s+(.*)$')
# NUOVO (26/07, tema correlazione GK-DEF): riga "SQUADRA: x | AVVERSARIO: y"
# scritta subito dopo la riga consiglio da test_mls_fwd_all.py -- portata
# fino a build_formazione_finale.py per evitare di schierare insieme
# portiere e giocatore di movimento le cui squadre si affrontano.
TEAM_RE = re.compile(r'^SQUADRA:\s+(\S+)\s+\|\s+AVVERSARIO:\s+(\S+)\s*$')
# NUOVO (27/07): data/ora di calcio d'inizio della partita TARGET, estratta dalla
# riga "Data:" gia' presente nel file di predizione. Serve a schierare solo chi
# gioca DAVVERO nella giornata per cui si costruisce la formazione: senza questa
# informazione il generatore mescolava giocatori con partita gia' giocata e
# giocatori con partita fra una settimana (che per giunta non hanno ancora le
# starter odds, quindi passavano indenni anche il filtro sulla soglia).
KICKOFF_RE = re.compile(r'^Data:\s+(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?)\s*$')
# NUOVO (28/07, sezione 27.C, estesa da DEF a FWD): score usato per ORDINARE,
# calcolato senza shrinkage. Riga opzionale: se manca (file generati prima di
# questo fix) si ordina come prima sui pt attesi.
ORDINAMENTO_RE = re.compile(r'^ORDINAMENTO:\s+(-?[\d.]+)\s*$')


def latest_file_for_slug(slug):
    matches = sorted(glob.glob(os.path.join(OUTPUT_DIR, f'prediction_{slug}_*.txt')))
    return matches[-1] if matches else None


def parse_player_file(path):
    """Estrae dal file di un giocatore la riga consiglio (se OK, con squadra/
    avversario) o lo stato di esclusione (se escluso/dati insufficienti)."""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    consiglio = None
    team_slug = opp_slug = None
    kickoff = None
    ordinamento = None
    for line in content.splitlines():
        stripped = line.strip()
        m = CONSIGLIO_RE.match(stripped)
        if m:
            slug, atteso, low, high = m.groups()
            consiglio = {'slug': slug, 'status': 'OK', 'atteso': int(atteso),
                         'low': int(low), 'high': int(high)}
            continue
        m = ORDINAMENTO_RE.match(stripped)
        if m:
            ordinamento = float(m.group(1))
            continue
        m = KICKOFF_RE.match(stripped)
        if m:
            kickoff = m.group(1)
            continue
        m = TEAM_RE.match(stripped)
        if m:
            team_slug, opp_slug = m.groups()
            continue
        m = ESCLUSO_RE.match(stripped)
        if m:
            slug, status, note = m.groups()
            return {'slug': slug, 'status': status, 'note': note}

    if consiglio:
        consiglio['team_slug'] = None if team_slug == 'N/D' else team_slug
        consiglio['opponent_team_slug'] = None if opp_slug == 'N/D' else opp_slug
        consiglio['kickoff'] = kickoff
        consiglio['ordinamento'] = ordinamento
        return consiglio
    return None


def main():
    with open(DISCOVERY_FILE, 'r', encoding='utf-8') as f:
        slugs = json.load(f)

    ok_rows = []
    excluded_count = 0

    for slug in slugs:
        fpath = latest_file_for_slug(slug)
        if not fpath:
            continue
        parsed = parse_player_file(fpath)
        if not parsed:
            continue
        if parsed['status'] == 'OK':
            ok_rows.append(parsed)
        else:
            excluded_count += 1

    # Ordina per lo score di ordinamento (senza shrinkage) -- stesso principio
    # gia' in produzione su build_consiglio_def.py. Fallback TUTTO-O-NIENTE:
    # se anche un solo giocatore non ha la riga, si ordina tutto per pt
    # attesi come prima.
    if ok_rows and all(r.get('ordinamento') is not None for r in ok_rows):
        ok_rows.sort(key=lambda r: r['ordinamento'], reverse=True)
    else:
        ok_rows.sort(key=lambda r: r['atteso'], reverse=True)

    lines = []
    lines.append(f"Consiglio attaccanti — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}Z")
    lines.append("")
    for i, r in enumerate(ok_rows, 1):
        lines.append(f"{i}) {r['slug']}: {r['atteso']} pt ({r['low']}-{r['high']})")
        # NUOVO (26/07, tema correlazione GK-DEF): squadra/avversario, per
        # build_formazione_finale.py.
        lines.append(f"   SQUADRA: {r.get('team_slug') or 'N/D'} | AVVERSARIO: {r.get('opponent_team_slug') or 'N/D'}")
        if r.get('kickoff'):
            lines.append(f"   KICKOFF: {r['kickoff']}")
        if r.get('ordinamento') is not None:
            lines.append(f"   ORDINAMENTO: {r['ordinamento']:.2f}")
    lines.append("")
    lines.append(f"({excluded_count} esclusi/non disponibili questa giornata)")

    text = "\n".join(lines)
    print(text)

    # La cartella puo' non esistere (lega appena creata): crearla evita un
    # FileNotFoundError che fa fallire tutto il job di merge.
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    out_path = os.path.join(OUTPUT_DIR, f'consiglio_{ts}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\nSalvato in: {out_path}")


if __name__ == '__main__':
    main()
