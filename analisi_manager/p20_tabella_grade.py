"""BRIEF_SONNET_TABELLA_GRADE_2026-08-09.txt -- quanto vale ogni lettera del
grade, in punti realizzati. SOLO MISURA, nessuna query, nessuna modifica alla
produzione.

Fonte grade: unione validata al §13 dell'handoff arene (2.241 slug) =
carica_indice_grade_esteso (6 file di produzione) + Forward_ampio +
Goalkeeper + storico_grade_arene_2026-08-08.json (il download dei 169).
grade_snapshot ESCLUSO dall'indice principale (§9), usato solo nel
controllo 5 (pre-partita).

Fonte punteggio realizzato: SEMPRE la cache game-log condivisa
(CacheLocale.gamelog), MAI il campo 'punteggio' dei file manager (D6,
CLAUDE.md) e mai i campi score/scoreStatus embedded nei file grade (per
uniformita' di fonte, un solo posto dove il punteggio puo' sbagliare).
Match ESATTO sulla data (non finestra: qui il grade e' gia' agganciato a
una partita precisa, a differenza del lookup di produzione che parte da
una fixture di piu' giorni).
"""
import os
import sys
import io
import json
import glob
import statistics
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M

cache = CACHE.CacheLocale()
GRADE_NUM = S21.GRADE_NUM
NUM_GRADE = {v: k for k, v in GRADE_NUM.items()}
LETTERE_ORDINE = ['F', 'E', 'D', 'C', 'B', 'A']

# --- ruolo per slug: usiamo i file grade stessi (portano 'ruolo'), + i file
# DEF/MID/FWD/GK di produzione; dove manca, resta 'sconosciuto'. Solo per la
# stratificazione (punto 2), non per il matching.
RUOLO_DA_FILE = {}


def registra_ruolo(slug, ruolo):
    if slug and ruolo and slug not in RUOLO_DA_FILE:
        RUOLO_DA_FILE[slug] = ruolo


def costruisci_indice_principale():
    """slug -> lista di (data, grade_letter) deduplicata. Unione validata §13:
    produzione (6 file) + Forward_ampio + Goalkeeper + storico_grade_arene."""
    idx_num, _ = M.carica_indice_grade_esteso()  # slug -> [(data, grade_num)]
    idx = collections.defaultdict(set)
    for slug, entries in idx_num.items():
        for dt, gn in entries:
            idx[slug].add((dt[:10], NUM_GRADE[gn]))

    for f in ('analisi_manager/dati/storico_grade_Forward_ampio_20260806.json',
              'analisi_manager/dati/storico_grade_Goalkeeper_20260806.json'):
        for r in json.load(open(f, encoding='utf-8')):
            slug, dt, grade = r.get('slug'), r.get('game_date'), r.get('grade')
            registra_ruolo(slug, r.get('ruolo'))
            if slug and dt and grade in GRADE_NUM:
                idx[slug].add((dt[:10], grade))

    d = json.load(open('analisi_manager/dati/storico_grade_arene_2026-08-08.json', encoding='utf-8'))
    for p in d.get('giocatori') or []:
        slug = p.get('slug')
        for s in p.get('playerGameScores') or []:
            proj = s.get('projection') or {}
            dt = (s.get('anyGame') or {}).get('date')
            grade = proj.get('grade')
            if slug and dt and grade in GRADE_NUM:
                idx[slug].add((dt[:10], grade))

    # ruolo anche dai 3 file piatti di produzione, per la stratificazione
    for f in ('analisi_manager/dati/storico_grade_Defender_20260806.json',
              'analisi_manager/dati/storico_grade_Midfielder_20260806.json',
              'analisi_manager/dati/storico_grade_Forward_20260806.json'):
        for r in json.load(open(f, encoding='utf-8')):
            registra_ruolo(r.get('slug'), r.get('ruolo'))

    return {slug: sorted(entries) for slug, entries in idx.items()}


def costruisci_indice_snapshot():
    """Grade PRE-partita (controllo 5), formato piatto {slug, game_date, grade,
    scoreStatus}. Esclusi dall'indice principale (mescolano un momento diverso)."""
    idx = collections.defaultdict(set)
    for f in glob.glob('analisi_manager/dati/grade_snapshot_*.json'):
        d = json.load(open(f, encoding='utf-8'))
        if not isinstance(d, list):
            continue
        for r in d:
            slug, dt, grade = r.get('slug'), r.get('game_date'), r.get('grade')
            if slug and dt and grade in GRADE_NUM:
                idx[slug].add((dt[:10], grade))
    return {slug: sorted(entries) for slug, entries in idx.items()}


def lega_indice():
    try:
        import analizza_gw as AG
        return AG.indice_lega()
    except Exception:
        return {}


def score_esatto(slug, data):
    """Punteggio grezzo dalla cache game-log per la partita ESATTA (stessa
    data, giorno). Ritorna (score_o_None, scoreStatus_o_None)."""
    for n in cache.gamelog(slug):
        d = ((n.get('anyGame') or {}).get('date') or '')[:10]
        if d == data:
            return n.get('score'), n.get('scoreStatus')
    return None, None


def main():
    idx = costruisci_indice_principale()
    print(f'indice principale: {len(idx)} slug distinti')

    righe = []
    scarti = collections.Counter()
    tot_coppie = 0
    for slug, entries in idx.items():
        for data, grade in entries:
            tot_coppie += 1
            score, status = score_esatto(slug, data)
            if score is None:
                scarti['no_cache_esatta'] += 1
                continue
            if status not in ('FINAL', 'REVIEWING', 'DID_NOT_PLAY'):
                scarti[f'status_{status}'] += 1
                continue
            righe.append({'slug': slug, 'data': data, 'grade': grade,
                          'score': score, 'non_giocante': score <= 1})
    print(f'coppie (slug,data) totali nell\'indice: {tot_coppie}')
    print(f'righe utilizzabili (score in cache, FINAL/REVIEWING): {len(righe)}')
    print(f'scarti: {dict(scarti)}')
    print()

    # --- 1. TABELLA BASE ---
    print('=== 1. TABELLA BASE (lettera -> punti realizzati) ===')
    tabella = {}
    for g in LETTERE_ORDINE:
        vals = [r['score'] for r in righe if r['grade'] == g]
        if not vals:
            tabella[g] = None
            print(f'  {g}: n=0 VUOTA')
            continue
        non_gioc = sum(1 for r in righe if r['grade'] == g and r['non_giocante'])
        tabella[g] = {'n': len(vals), 'media': statistics.mean(vals),
                      'mediana': statistics.median(vals),
                      'sd': statistics.pstdev(vals) if len(vals) > 1 else 0.0,
                      'quota_non_giocanti': non_gioc / len(vals)}
        t = tabella[g]
        print(f"  {g}: n={t['n']:5d}  media={t['media']:6.2f}  mediana={t['mediana']:6.2f}  "
              f"sd={t['sd']:6.2f}  non_giocanti={t['quota_non_giocanti']*100:5.1f}%")

    monotona = True
    ordine_valori = [(g, tabella[g]['media']) for g in LETTERE_ORDINE if tabella[g]]
    for i in range(1, len(ordine_valori)):
        if ordine_valori[i][1] < ordine_valori[i - 1][1]:
            monotona = False
    print(f'\nTEST DI MONOTONIA (media deve crescere F->A): {"OK" if monotona else "FALLITO"}')
    print(f'  sequenza: {[(g, round(v,2)) for g,v in ordine_valori]}')
    print()

    # --- 2. STRATIFICATA per ruolo ---
    print('=== 2. STRATIFICATA PER RUOLO ===')
    ruolo_code = {'Goalkeeper': 'GK', 'Defender': 'DEF', 'Midfielder': 'MID', 'Forward': 'FWD'}
    for r in righe:
        r['ruolo'] = ruolo_code.get(RUOLO_DA_FILE.get(r['slug']), 'sconosciuto')
    per_ruolo = collections.defaultdict(list)
    for r in righe:
        per_ruolo[r['ruolo']].append(r)
    for ruolo, rr in sorted(per_ruolo.items()):
        print(f'  --- ruolo {ruolo} (n totale {len(rr)}) ---')
        for g in LETTERE_ORDINE:
            vals = [x['score'] for x in rr if x['grade'] == g]
            if len(vals) < 30:
                print(f'    {g}: n={len(vals)} (<30, non commentato)')
                continue
            print(f'    {g}: n={len(vals):5d}  media={statistics.mean(vals):6.2f}  '
                  f'mediana={statistics.median(vals):6.2f}')
    print()

    # --- 2bis. STRATIFICATA per lega (piu' popolose) ---
    print('=== 2bis. STRATIFICATA PER LEGA (>=200 righe) ===')
    lega_di = lega_indice()
    for r in righe:
        r['lega'] = lega_di.get(r['slug']) or 'sconosciuta'
    conteggio_lega = collections.Counter(r['lega'] for r in righe)
    leghe_popolose = [l for l, n in conteggio_lega.most_common() if n >= 200]
    for lega in leghe_popolose:
        rr = [r for r in righe if r['lega'] == lega]
        print(f'  --- lega {lega} (n totale {len(rr)}) ---')
        for g in LETTERE_ORDINE:
            vals = [x['score'] for x in rr if x['grade'] == g]
            if len(vals) < 30:
                print(f'    {g}: n={len(vals)} (<30, non commentato)')
                continue
            print(f'    {g}: n={len(vals):5d}  media={statistics.mean(vals):6.2f}')
    print()

    # --- 3. CONDIZIONATA all'aver giocato ---
    print('=== 3. TABELLA CONDIZIONATA (esclusi i non-giocanti) ===')
    tabella_cond = {}
    for g in LETTERE_ORDINE:
        vals = [r['score'] for r in righe if r['grade'] == g and not r['non_giocante']]
        if not vals:
            tabella_cond[g] = None
            print(f'  {g}: n=0 VUOTA')
            continue
        tabella_cond[g] = {'n': len(vals), 'media': statistics.mean(vals),
                           'mediana': statistics.median(vals)}
        print(f"  {g}: n={len(vals):5d}  media={statistics.mean(vals):6.2f}  "
              f"mediana={statistics.median(vals):6.2f}")
    print()

    # --- 4. CONFRONTO col meccanismo attuale (z-score di giornata) ---
    print('=== 4. CONFRONTO METODO ATTUALE vs TABELLA (segno opposto?) ===')
    print('Uso i valori MEDI della tabella base come "valore assoluto" e li')
    print('confronto contro lo spostamento z-score-di-gruppo su gruppi reali')
    print('(slug,data) raggruppati per (grade-giornata implicita = stessa data,')
    print('stesso ruolo) cosi\' come si presenterebbero in una formazione vera.')
    print()
    valore_medio_lettera = {g: tabella[g]['media'] for g in LETTERE_ORDINE if tabella[g]}
    media_di_tutte = statistics.mean(valore_medio_lettera.values())
    gruppi = collections.defaultdict(list)
    for r in righe:
        if r['ruolo'] == 'sconosciuto':
            continue
        gruppi[(r['data'], r['ruolo'])].append(r)
    spost_attuale = []
    spost_tabella = []
    segno_opposto = 0
    confrontabili = 0
    for (_data, _ruolo), membri in gruppi.items():
        if len(membri) < 2:
            continue
        gn_vals = [GRADE_NUM[m['grade']] for m in membri]
        media_gn = statistics.mean(gn_vals)
        sd_gn = statistics.pstdev(gn_vals)
        for m, gn in zip(membri, gn_vals):
            z_attuale = 0.0 if sd_gn == 0 else (gn - media_gn) / sd_gn
            val_tabella = valore_medio_lettera.get(m['grade'])
            if val_tabella is None:
                continue
            spost_a = z_attuale  # unita' arbitraria (sd della giornata), solo per il segno
            spost_t = val_tabella - media_di_tutte
            confrontabili += 1
            spost_attuale.append(spost_a)
            spost_tabella.append(spost_t)
            if spost_a * spost_t < 0:
                segno_opposto += 1
    if confrontabili >= 2:
        try:
            corr = statistics.correlation(spost_attuale, spost_tabella)
        except Exception:
            corr = None
        scarti_rel = [abs(a) for a in spost_attuale]  # non comparabile in unita', solo il segno conta
        print(f'  carte confrontabili (gruppo giornata/ruolo con >=2 grade noti): {confrontabili}')
        print(f'  correlazione fra segno/direzione dei due metodi: {corr}')
        print(f'  carte con SEGNO OPPOSTO fra metodo attuale e tabella: {segno_opposto} '
              f'({segno_opposto/confrontabili*100:.1f}%)')
    else:
        print('  troppo pochi casi confrontabili')
    print()

    # --- 5. CONTROLLO ANTI-CONTAMINAZIONE (snapshot pre-partita) ---
    print('=== 5. CONTROLLO ANTI-CONTAMINAZIONE (grade PRE-partita, snapshot) ===')
    idx_snap = costruisci_indice_snapshot()
    tot_snap = sum(len(v) for v in idx_snap.values())
    print(f'indice snapshot: {len(idx_snap)} slug, {tot_snap} coppie (slug,data)')
    righe_snap = []
    for slug, entries in idx_snap.items():
        for data, grade in entries:
            score, status = score_esatto(slug, data)
            if score is None or status not in ('FINAL', 'REVIEWING', 'DID_NOT_PLAY'):
                continue
            righe_snap.append({'grade': grade, 'score': score, 'non_giocante': score <= 1})
    print(f'righe snapshot utilizzabili: {len(righe_snap)}')
    for g in LETTERE_ORDINE:
        vals_princ = [r['non_giocante'] for r in righe if r['grade'] == g]
        vals_snap = [r['non_giocante'] for r in righe_snap if r['grade'] == g]
        q_princ = sum(vals_princ) / len(vals_princ) if vals_princ else None
        q_snap = sum(vals_snap) / len(vals_snap) if vals_snap else None
        print(f"  {g}: quota non_giocanti PRINCIPALE(n={len(vals_princ)})="
              f"{'%.1f%%' % (q_princ*100) if q_princ is not None else 'n/a'}   "
              f"PRE-partita(n={len(vals_snap)})="
              f"{'%.1f%%' % (q_snap*100) if q_snap is not None else 'n/a'}")
    print()

    # --- DUMP LEGGIBILE ---
    print('=== DUMP: 10 esempi per lettera ===')
    dump_path = 'analisi_manager/p20_tabella_grade_dump.txt'
    with open(dump_path, 'w', encoding='utf-8') as fh:
        for g in LETTERE_ORDINE:
            campione = [r for r in righe if r['grade'] == g][:10]
            fh.write(f'--- Grade {g} ---\n')
            for r in campione:
                fh.write(f"  {r['slug']:35} {r['data']}  realizzato={r['score']:7.2f}  "
                         f"giocato={'no' if r['non_giocante'] else 'si'}\n")
            fh.write('\n')
    print(f'dump scritto in {dump_path}')

    out = {'tabella_base': tabella, 'tabella_condizionata': tabella_cond,
           'monotona': monotona, 'n_righe': len(righe), 'scarti': dict(scarti),
           'confrontabili_metodo4': confrontabili,
           'segno_opposto_metodo4': segno_opposto}
    with open('analisi_manager/p20_tabella_grade_out.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print('output json: analisi_manager/p20_tabella_grade_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
