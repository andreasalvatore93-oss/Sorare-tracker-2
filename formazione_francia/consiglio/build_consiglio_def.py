"""
Genera SOLO il riepilogo finale compatto "Consiglio difensori" leggendo
i file prediction_<slug>_*.txt gia' prodotti dal job matrix (uno per
giocatore). Nessun dump completo: poche righe, ordine di schieramento.

Clone esatto di build_consiglio.py (attaccanti), adattato a mls_def_all/ e
mls_def_discovery/.
"""
import os
import re
import json
import glob
import datetime

OUTPUT_DIR = 'formazione_francia/output/francia_def_all'
# CONSIGLIO_DISCOVERY_FILE (30/07, tema Best Five): override opzionale --
# permette a best_five.py di puntare al pool GLOBALE (i sopravvissuti al
# prefiltro, non i posseduti) senza duplicare qui la logica di parsing/sort
# gia' scritta in questo file -- un solo posto da mantenere quando cambia
# (vedi 'Revert score_ordinamento' 30/07, che aveva reso obsoleto il ranking
# per ORDINAMENTO duplicato in best_five.py). Se non impostata, comportamento
# INVARIATO (posseduti, come sempre).
DISCOVERY_FILE = os.environ.get('CONSIGLIO_DISCOVERY_FILE') or os.path.join('formazione_francia/output/francia_def_discovery', 'player_slugs.json')

# Pattern della riga "N) slug: X pt attesi (low-high)" gia' scritta da
# test_def.py nel riepilogo di ciascun job (uno per giocatore, quindi
# sempre riga singola "1) ...").
CONSIGLIO_RE = re.compile(r'^\d+\)\s+([\w-]+):\s+(-?\d+)\s+pt attesi\s+\((-?\d+)-(-?\d+)\)\s*$')
ESCLUSO_RE = re.compile(r'^([\w-]+):\s+(ESCLUSO|DATI INSUFFICIENTI)\s+—\s+(.*)$')
# NUOVO (26/07, tema correlazione GK-DEF): riga "SQUADRA: x | AVVERSARIO: y"
# scritta subito dopo la riga consiglio da test_def.py -- portata fino a
# build_formazione_finale.py per evitare di schierare insieme portiere e
# giocatore di movimento le cui squadre si affrontano.
TEAM_RE = re.compile(r'^SQUADRA:\s+(\S+)\s+\|\s+AVVERSARIO:\s+(\S+)\s*$')
# NUOVO (29/07, richiesta esplicita utente): fattore forza avversario (SOLO
# diagnostico, non entra in score_atteso -- vedi test_<ruolo>.py) portato fino
# a build_formazione_finale.py per mostrarlo accanto a squadra/avversario.
OPP_FACTOR_RE = re.compile(r'^Fattore forza avversario applicato:\s+([\d.]+)\s*$')
# NUOVO (27/07): data/ora di calcio d'inizio della partita TARGET, estratta dalla
# riga "Data:" gia' presente nel file di predizione. Serve a schierare solo chi
# gioca DAVVERO nella giornata per cui si costruisce la formazione: senza questa
# informazione il generatore mescolava giocatori con partita gia' giocata e
# giocatori con partita fra una settimana (che per giunta non hanno ancora le
# starter odds, quindi passavano indenni anche il filtro sulla soglia).
KICKOFF_RE = re.compile(r'^Data:\s+(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?)\s*$')
# NUOVO (27/07, sezione 27.C del RIASSUNTO): score usato per ORDINARE, calcolato
# senza shrinkage. Lo shrinkage minimizza il MAE ma comprime le differenze fra
# giocatori (e con k fisso tira di piu' chi ha meno storico, quindi altera
# l'ordinamento): misurato su 123 giornate reali, ordinare senza shrinkage
# cattura il 17.8% del lift disponibile contro il 13.7% con. I "pt" mostrati
# restano lo score atteso (miglior stima del punteggio). Riga opzionale: se
# manca (file generati dalla versione precedente) si ordina come prima.
ORDINAMENTO_RE = re.compile(r'^ORDINAMENTO:\s+(-?[\d.]+)\s*$')
# NUOVO (12/08/2026, richiesta esplicita utente): marker gia' scritto dai
# predict (test_gk.py e affini, riga "   AMBIGUO_FIXTURE: si" -- caso Freese,
# due partite future con odds pubblicate insieme). Oggi lo leggeva solo
# scouting_gw.py direttamente dai prediction_*.txt; portato qui per farlo
# arrivare anche al generatore/Best Five via il consiglio aggregato.
AMBIGUO_RE = re.compile(r'^AMBIGUO_FIXTURE:\s*si\s*$')


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
    opp_factor = None
    kickoff = None
    ordinamento = None
    ambiguo = False
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
        m = OPP_FACTOR_RE.match(stripped)
        if m:
            opp_factor = float(m.group(1))
            continue
        m = AMBIGUO_RE.match(stripped)
        if m:
            ambiguo = True
            continue
        m = ESCLUSO_RE.match(stripped)
        if m:
            slug, status, note = m.groups()
            return {'slug': slug, 'status': status, 'note': note}

    if consiglio:
        consiglio['team_slug'] = None if team_slug == 'N/D' else team_slug
        consiglio['opponent_team_slug'] = None if opp_slug == 'N/D' else opp_slug
        consiglio['kickoff'] = kickoff
        consiglio['opp_factor'] = opp_factor
        consiglio['ordinamento'] = ordinamento
        consiglio['ambiguo'] = ambiguo
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

    # REVERTITO (30/07, richiesta esplicita utente, caso reale Wanderson Best
    # Five K League: titolare a 47pt preferito a backup 58pt con storico 7x
    # piu' lungo): il ritest di oggi con dataset molto piu' ampio/pulito
    # (measure_reliability_vs_score_allroles.py / selection_quality_
    # shrinkage_allroles.py, DEF 328 giornate/16 leghe vs le 123/1 lega del
    # 27/07) mostra che ordinare SENZA shrinkage non batte piu' lo score
    # mostrato (lift 19.5% vs 20.4% -- si e' invertito rispetto a fine
    # luglio, campione di allora gia' segnalato come "sottile"). Si ordina
    # sempre per 'atteso' (lo stesso score mostrato), come GK/MID.
    ok_rows.sort(key=lambda r: r['atteso'], reverse=True)

    lines = []
    lines.append(f"Consiglio difensori — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}Z")
    lines.append("")
    for i, r in enumerate(ok_rows, 1):
        lines.append(f"{i}) {r['slug']}: {r['atteso']} pt ({r['low']}-{r['high']})")
        # NUOVO (26/07, tema correlazione GK-DEF): squadra/avversario, per
        # build_formazione_finale.py.
        lines.append(f"   SQUADRA: {r.get('team_slug') or 'N/D'} | AVVERSARIO: {r.get('opponent_team_slug') or 'N/D'}")
        if r.get('opp_factor') is not None:
            lines.append(f"   AVV_FACTOR: {r['opp_factor']:.3f}")
        if r.get('kickoff'):
            lines.append(f"   KICKOFF: {r['kickoff']}")
        if r.get('ambiguo'):
            lines.append("   AMBIGUO: si")
        # Propagata a build_formazione_finale/globale, che ordinano i pool.
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
