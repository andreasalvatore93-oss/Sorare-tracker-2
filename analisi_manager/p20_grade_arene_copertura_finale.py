"""BRIEF_SONNET_GRADE_ARENE_2026-08-08.txt -- §6 punti 2-5, dopo il download
dei 169 slug mancanti (sblocco utente 09/08/2026 notte, vedi HANDOFF_GRADE_
ARENE_2026-08-08.txt §12). Nessuna modifica alla produzione, nessuna query
di rete (i dati sono gia' scaricati in storico_grade_arene_2026-08-08.json).

Indice DOPO il download = indice di produzione (carica_indice_grade_esteso,
6 file) + Forward_ampio/Goalkeeper (verificati "buoni" in §8.1, zero
divergenze su 3.615 coppie) + storico_grade_arene_2026-08-08.json (il
download di oggi). grade_snapshot resta ESCLUSO (mescola momenti diversi,
va conservato ma non usato nel lookup, §9 dell'handoff).

Aggiunge anche il conteggio richiesto dall'utente: quante carte del
perimetro hanno PIU' DI UNA partita candidata dentro la finestra di 6
giorni (rischio di prendere il grade della partita sbagliata) -- SOLO
CONTEGGIO, nessuna modifica alla logica di grade_in_finestra.
"""
import os
import sys
import io
import json
import re
import glob
import collections
import datetime

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M

GW6 = {'football-4-7-aug-2026', 'football-31-jul-4-aug-2026', 'football-28-31-jul-2026',
       'football-24-28-jul-2026', 'football-21-24-jul-2026', 'football-15-20-jul-2026'}
GRUPPI = {
    'seasonal-all_star-all_seasons_all_star_arena_limited': 'A1_cap260',
    'seasonal-all_star-all_seasons_all_star_arena_limited_cap_220': 'A2_cap220',
    'seasonal-all_star-all_seasons_all_star_arena_limited_uncapped': 'A3_uncapped',
    'seasonal-all_star-all_seasons_all_star_arena_limited_beginner': 'A4_beginner',
    'seasonal-us-all_seasons_us_arena_limited': 'B_us',
    'seasonal-korea-all_seasons_korea_arena_limited': 'B_korea',
    'seasonal-scotland-all_seasons_scotland_arena_limited': 'B_scotland',
}
_HASH_RE = re.compile(r'-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_DIV_RE = re.compile(r'-division-\d+$')


def normalizza(leaderboard, gw):
    prefix = gw + '-'
    if not leaderboard.startswith(prefix):
        return None
    s = leaderboard[len(prefix):]
    s = _HASH_RE.sub('', s)
    s = _DIV_RE.sub('', s)
    return s


def raccogli_formazioni():
    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    formazioni = []
    for fp in files:
        manager = os.path.basename(fp)[len('manager_'):-len('.json')]
        d = json.load(open(fp, encoding='utf-8'))
        for gw, forms in (d.get('giornate') or {}).items():
            if gw not in GW6:
                continue
            bounds = M.parse_fixture_bounds(gw)
            if bounds is None:
                continue
            _d_start, d_end = bounds
            for form in forms:
                if not form.get('tipo_arena'):
                    continue
                lb = form.get('leaderboard')
                if not lb:
                    continue
                gruppo = GRUPPI.get(normalizza(lb, gw))
                if gruppo is None:
                    continue
                formazioni.append({'gruppo': gruppo, 'manager': manager, 'gw': gw,
                                    'leaderboard': lb, 'fine': d_end.isoformat(), 'carte': form['carte']})
    return formazioni


def registra(idx, slug, dt, grade):
    gn = S21.GRADE_NUM.get(grade)
    if gn is None or not dt or not slug:
        return
    idx[slug].append((dt[:10], gn))


def indice_dopo_download():
    idx_prod, _ = M.carica_indice_grade_esteso()
    idx = collections.defaultdict(list)
    for slug, entries in idx_prod.items():
        idx[slug].extend(entries)

    for f in ('analisi_manager/dati/storico_grade_Forward_ampio_20260806.json',
              'analisi_manager/dati/storico_grade_Goalkeeper_20260806.json'):
        for r in json.load(open(f, encoding='utf-8')):
            registra(idx, r.get('slug'), r.get('game_date'), r.get('grade'))

    d = json.load(open('analisi_manager/dati/storico_grade_arene_2026-08-08.json', encoding='utf-8'))
    for p in d.get('giocatori') or []:
        for s in p.get('playerGameScores') or []:
            proj = s.get('projection') or {}
            registra(idx, p.get('slug'), (s.get('anyGame') or {}).get('date'), proj.get('grade'))

    for slug in idx:
        idx[slug] = sorted(set(idx[slug]))
    return idx


def copertura(formazioni, idx_grade, etichetta):
    tot_carte = con_arch = con_fin = 0
    per_gruppo = collections.defaultdict(lambda: {'tot': 0, 'arch': 0, 'fin': 0})
    per_formazione_pct = []
    scoperti = []  # (slug, gruppo, gw, motivo)
    for f in formazioni:
        n = c_fin = 0
        for c in f['carte']:
            n += 1
            tot_carte += 1
            per_gruppo[f['gruppo']]['tot'] += 1
            in_arch = bool(idx_grade.get(c['slug']))
            if in_arch:
                con_arch += 1
                per_gruppo[f['gruppo']]['arch'] += 1
            g = S21.grade_in_finestra(idx_grade, c['slug'], f['fine'])
            if g is not None:
                con_fin += 1
                c_fin += 1
                per_gruppo[f['gruppo']]['fin'] += 1
            else:
                motivo = 'nessuna_partita_nota' if not in_arch else 'partite_note_ma_fuori_finestra_6gg'
                scoperti.append({'slug': c['slug'], 'gruppo': f['gruppo'], 'gw': f['gw'], 'motivo': motivo})
        per_formazione_pct.append(100 * c_fin / n)

    print(f'\n--- COPERTURA [{etichetta}] (denominatore={tot_carte} carte, {len(formazioni)} formazioni) ---')
    print(f'  in ARCHIVIO: {con_arch}/{tot_carte} ({100*con_arch/tot_carte:.1f}%)')
    print(f'  in FINESTRA vera (<=6gg): {con_fin}/{tot_carte} ({100*con_fin/tot_carte:.1f}%)')
    for g in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        s = per_gruppo[g]
        if s['tot'] == 0:
            continue
        print(f"    {g:12s} tot={s['tot']:4d}  archivio={s['arch']:4d} ({100*s['arch']/s['tot']:.1f}%)  "
              f"finestra={s['fin']:4d} ({100*s['fin']/s['tot']:.1f}%)")

    bucket = collections.Counter()
    for pct in per_formazione_pct:
        if pct < 50:
            bucket['<50%'] += 1
        elif pct < 70:
            bucket['50-70%'] += 1
        elif pct < 90:
            bucket['70-90%'] += 1
        else:
            bucket['>90%'] += 1
    print(f'  distribuzione per formazione (n={len(per_formazione_pct)}):')
    for k in ('<50%', '50-70%', '70-90%', '>90%'):
        print(f"    {k:8s} {bucket.get(k,0)}")

    return {'tot_carte': tot_carte, 'con_arch': con_arch, 'con_fin': con_fin,
            'per_gruppo': dict(per_gruppo), 'bucket': dict(bucket), 'scoperti': scoperti}


def conta_partite_ambigue(formazioni, idx_grade):
    """Quante carte-giornata del perimetro hanno PIU' DI UNA partita
    candidata (nota nell'indice) dentro i 6 giorni prima della fine
    fixture: li' il grade preso da grade_in_finestra() (il piu' vicino)
    potrebbe non essere quello della partita giusta se il lookup, per
    quello slug/giornata, si riferisce a una partita diversa da quella
    realmente giocata dalla carta. SOLO CONTEGGIO, nessuna modifica alla
    logica di produzione."""
    tot_con_almeno_1 = 0
    tot_ambigue = 0
    esempi = []
    for f in formazioni:
        fine = datetime.date.fromisoformat(f['fine'])
        for c in f['carte']:
            entries = idx_grade.get(c['slug'])
            if not entries:
                continue
            candidate = []
            for dt, gn in entries:
                y, m, dday = (int(x) for x in dt.split('-'))
                delta = (fine - datetime.date(y, m, dday)).days
                if 0 <= delta <= S21.GRADE_WINDOW_GIORNI:
                    candidate.append((dt, gn))
            if not candidate:
                continue
            tot_con_almeno_1 += 1
            if len(candidate) > 1:
                tot_ambigue += 1
                if len(esempi) < 15:
                    esempi.append({'slug': c['slug'], 'gruppo': f['gruppo'], 'gw': f['gw'],
                                    'fine': f['fine'], 'candidate': candidate})
    print(f'\n--- CARTE CON PIU\' DI UNA PARTITA CANDIDATA NELLA FINESTRA 6gg ---')
    print(f'  carte con almeno 1 candidata: {tot_con_almeno_1}')
    print(f'  carte con PIU\' di 1 candidata (ambigue): {tot_ambigue} '
          f'({100*tot_ambigue/tot_con_almeno_1:.1f}% di quelle con almeno 1)' if tot_con_almeno_1 else '')
    for e in esempi[:10]:
        print(f"    {e['slug']:30s} {e['gruppo']:12s} {e['gw']:28s} fine={e['fine']}  candidate={e['candidate']}")
    return {'con_almeno_1': tot_con_almeno_1, 'ambigue': tot_ambigue, 'esempi': esempi}


def dump_arena(formazioni, idx_grade):
    f = formazioni[0]
    lines = [f"arena leaderboard: {f['leaderboard']}", f"gruppo: {f['gruppo']}  manager: {f['manager']}  gw: {f['gw']}", '']
    for c in f['carte']:
        g = S21.grade_in_finestra(idx_grade, c['slug'], f['fine'])
        entries = idx_grade.get(c['slug']) or []
        data_usata = None
        if g is not None:
            fine = datetime.date.fromisoformat(f['fine'])
            migliore_delta = None
            for dt, gn in entries:
                y, m, dday = (int(x) for x in dt.split('-'))
                delta = (fine - datetime.date(y, m, dday)).days
                if 0 <= delta <= S21.GRADE_WINDOW_GIORNI and gn == g and (migliore_delta is None or delta < migliore_delta):
                    data_usata = dt
                    migliore_delta = delta
        cap = ' (CAPITANO)' if c.get('capitano') else ''
        lines.append(f"  {c['nome']:28s} {c['ruolo']:10s} slug={c['slug']:30s} grade={g}  "
                      f"data_partita_usata={data_usata}{cap}")
    testo = '\n'.join(lines)
    print('\n--- DUMP ARENA COMPLETA ---')
    print(testo)
    with open('analisi_manager/p20_grade_arene_dump_esempio.txt', 'w', encoding='utf-8') as fh:
        fh.write(testo + '\n')


def main():
    formazioni = raccogli_formazioni()
    print(f'formazioni: {len(formazioni)}')

    idx_prima, _ = M.carica_indice_grade_esteso()
    idx_dopo = indice_dopo_download()
    print(f'indice PRIMA (produzione, 6 file): {len(idx_prima)} slug')
    print(f'indice DOPO (produzione + Forward_ampio + Goalkeeper + download 169): {len(idx_dopo)} slug')

    esito = {}
    esito['prima'] = copertura(formazioni, idx_prima, 'PRIMA del download')
    esito['dopo'] = copertura(formazioni, idx_dopo, 'DOPO il download')
    esito['ambigue'] = conta_partite_ambigue(formazioni, idx_dopo)
    dump_arena(formazioni, idx_dopo)

    with open('analisi_manager/p20_grade_arene_scoperti_dopo.json', 'w', encoding='utf-8') as fh:
        json.dump(esito['dopo']['scoperti'], fh, ensure_ascii=False, indent=1)

    with open('analisi_manager/p20_grade_arene_copertura_finale_out.json', 'w', encoding='utf-8') as fh:
        json.dump({
            'n_slug_prima': len(idx_prima), 'n_slug_dopo': len(idx_dopo),
            'copertura_prima': {k: v for k, v in esito['prima'].items() if k != 'scoperti'},
            'copertura_dopo': {k: v for k, v in esito['dopo'].items() if k != 'scoperti'},
            'n_scoperti_dopo': len(esito['dopo']['scoperti']),
            'ambigue': esito['ambigue'],
        }, fh, ensure_ascii=False, indent=2)
    print('\nsalvato analisi_manager/p20_grade_arene_copertura_finale_out.json')
    print('salvato analisi_manager/p20_grade_arene_scoperti_dopo.json')
    print('salvato analisi_manager/p20_grade_arene_dump_esempio.txt')


if __name__ == '__main__':
    sys.exit(main() or 0)
