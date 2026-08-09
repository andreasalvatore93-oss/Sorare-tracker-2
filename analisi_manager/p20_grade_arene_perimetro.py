"""BRIEF_SONNET_GRADE_ARENE_2026-08-08.txt -- passo 1a (SOLO locale, nessuna
query di rete): ricostruisce il perimetro ARENE/limited sulle ultime 6
giornate, verifica i numeri di controllo del brief (§2), e misura la
copertura grade PRIMA del download (§3/§6.2), con due baseline a confronto
(vedi §STOP nell'handoff -- il conteggio "270 da scaricare" del brief non
torna con l'indice di produzione realmente usato a valle, e va capito
PRIMA di scaricare nulla, per esplicita regola del brief).

Nessuna modifica alla produzione, nessuna query Sorare.
"""
import os
import sys
import io
import json
import re
import glob
import collections

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
    """Tutte le formazioni ARENA/limited del perimetro, sulle 6 giornate."""
    files = sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json')))
    formazioni = []
    non_match = collections.Counter()
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
            fine_str = d_end.isoformat()
            for form in forms:
                if not form.get('tipo_arena'):
                    continue
                lb = form.get('leaderboard')
                if not lb:
                    continue
                norm = normalizza(lb, gw)
                gruppo = GRUPPI.get(norm)
                if gruppo is None:
                    non_match[norm] += 1
                    continue
                formazioni.append({'gruppo': gruppo, 'manager': manager, 'gw': gw,
                                    'leaderboard': lb, 'fine': fine_str, 'carte': form['carte']})
    return formazioni, non_match


def indice_solo_4_file_brief():
    """Ricostruisce l'indice grade usando SOLO i 4 file che il brief elenca
    al §3 come 'archivio attuale' (storico_grade_backtest_20260806.json +
    i tre per-ruolo Defender/Midfielder/Forward). Serve a riprodurre il
    numero 636/270 del brief e localizzare la differenza con l'indice di
    produzione (carica_indice_grade_esteso, 6 file)."""
    idx = collections.defaultdict(list)

    def registra(slug, dt, grade):
        gn = S21.GRADE_NUM.get(grade)
        if gn is None or not dt or not slug:
            return
        idx[slug].append((dt[:10], gn))

    d = json.load(open('analisi_manager/dati/storico_grade_backtest_20260806.json', encoding='utf-8'))
    for p in d.get('giocatori') or []:
        for s in p.get('playerGameScores') or []:
            proj = s.get('projection') or {}
            registra(p.get('slug'), (s.get('anyGame') or {}).get('date'), proj.get('grade'))

    for f in ('analisi_manager/dati/storico_grade_Defender_20260806.json',
              'analisi_manager/dati/storico_grade_Midfielder_20260806.json',
              'analisi_manager/dati/storico_grade_Forward_20260806.json'):
        d = json.load(open(f, encoding='utf-8'))
        for r in d:
            registra(r.get('slug'), r.get('game_date'), r.get('grade'))

    for slug in idx:
        idx[slug] = sorted(set(idx[slug]))
    return idx


def copertura(formazioni, idx_grade, etichetta):
    tot_carte = con_arch = con_fin = 0
    per_gruppo = collections.defaultdict(lambda: {'tot': 0, 'arch': 0, 'fin': 0})
    per_formazione_pct = []
    slug_visti = set()
    for f in formazioni:
        n = c_arch = c_fin = 0
        for c in f['carte']:
            slug_visti.add(c['slug'])
            n += 1
            tot_carte += 1
            per_gruppo[f['gruppo']]['tot'] += 1
            if idx_grade.get(c['slug']):
                con_arch += 1
                c_arch += 1
                per_gruppo[f['gruppo']]['arch'] += 1
            if S21.grade_in_finestra(idx_grade, c['slug'], f['fine']) is not None:
                con_fin += 1
                c_fin += 1
                per_gruppo[f['gruppo']]['fin'] += 1
        per_formazione_pct.append(100 * c_fin / n)

    print(f'\n--- COPERTURA [{etichetta}] (denominatore={tot_carte} carte schierate, '
          f'{len(formazioni)} formazioni, {len(slug_visti)} slug distinti) ---')
    print(f'  in ARCHIVIO (qualunque data, limite superiore): {con_arch}/{tot_carte} ({100*con_arch/tot_carte:.1f}%)')
    print(f'  in FINESTRA vera (<=6gg prima fine fixture, GRADE_WINDOW_GIORNI): {con_fin}/{tot_carte} ({100*con_fin/tot_carte:.1f}%)')
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
    print(f'  distribuzione per formazione (copertura in finestra, n={len(per_formazione_pct)}):')
    for k in ('<50%', '50-70%', '70-90%', '>90%'):
        print(f"    {k:8s} {bucket.get(k,0)}")

    return {'tot_carte': tot_carte, 'con_arch': con_arch, 'con_fin': con_fin,
            'per_gruppo': dict(per_gruppo), 'bucket': dict(bucket), 'slug_distinti': sorted(slug_visti)}


def main():
    formazioni, non_match = raccogli_formazioni()
    print(f'formazioni ARENA/limited nel perimetro: {len(formazioni)}')
    tot_per_gruppo = collections.Counter(f['gruppo'] for f in formazioni)
    for g in ('A1_cap260', 'A2_cap220', 'A3_uncapped', 'A4_beginner', 'B_us', 'B_korea', 'B_scotland'):
        arene = len(set(f['leaderboard'] for f in formazioni if f['gruppo'] == g))
        manager = len(set(f['manager'] for f in formazioni if f['gruppo'] == g))
        slug = len(set(c['slug'] for f in formazioni if f['gruppo'] == g for c in f['carte']))
        print(f'  {g:12s} {tot_per_gruppo[g]:4d} formazioni  {manager:3d} manager  {arene:4d} arene distinte  {slug:4d} slug')
    slug_tutti = sorted(set(c['slug'] for f in formazioni for c in f['carte']))
    print(f'TOTALE: {len(formazioni)} formazioni, {len(slug_tutti)} slug distinti (unione)')
    print(f'competizioni escluse (fuori perimetro, non normalizzabili): {dict(non_match)}')

    idx_prod, date_min_prod = M.carica_indice_grade_esteso()
    idx_4file = indice_solo_4_file_brief()
    print(f'\nindice PRODUZIONE (carica_indice_grade_esteso, 6 file): {len(idx_prod)} slug distinti')
    print(f'indice SOLO-4-FILE (definizione §3 del brief): {len(idx_4file)} slug distinti')

    gia_4file = [s for s in slug_tutti if idx_4file.get(s)]
    gia_prod = [s for s in slug_tutti if idx_prod.get(s)]
    print(f'\nSUL PERIMETRO ({len(slug_tutti)} slug):')
    print(f'  gia in archivio (SOLO-4-FILE, definizione brief §3): {len(gia_4file)}  DA SCARICARE: {len(slug_tutti)-len(gia_4file)}')
    print(f'  gia in archivio (indice di PRODUZIONE, 6 file, quello usato davvero a valle): {len(gia_prod)}  DA SCARICARE: {len(slug_tutti)-len(gia_prod)}')

    esito = {}
    esito['solo_4_file'] = copertura(formazioni, idx_4file, 'baseline brief SOLO-4-FILE')
    esito['produzione'] = copertura(formazioni, idx_prod, 'indice di PRODUZIONE (6 file)')

    mancanti_prod = sorted(set(slug_tutti) - set(gia_prod))
    with open('analisi_manager/p20_grade_arene_slug_mancanti_produzione.json', 'w', encoding='utf-8') as fh:
        json.dump({'n': len(mancanti_prod), 'slug': mancanti_prod}, fh, ensure_ascii=False, indent=1)
    print(f'\nsalvato analisi_manager/p20_grade_arene_slug_mancanti_produzione.json ({len(mancanti_prod)} slug)')

    with open('analisi_manager/p20_grade_arene_perimetro_out.json', 'w', encoding='utf-8') as fh:
        json.dump({
            'formazioni_totali': len(formazioni), 'slug_totali': len(slug_tutti),
            'per_gruppo_conteggi': {g: {'formazioni': tot_per_gruppo[g],
                                         'manager': len(set(f['manager'] for f in formazioni if f['gruppo'] == g)),
                                         'arene': len(set(f['leaderboard'] for f in formazioni if f['gruppo'] == g)),
                                         'slug': len(set(c['slug'] for f in formazioni if f['gruppo'] == g for c in f['carte']))}
                                     for g in GRUPPI.values()},
            'indice_produzione_slug': len(idx_prod), 'indice_4file_slug': len(idx_4file),
            'gia_archivio_4file': len(gia_4file), 'gia_archivio_produzione': len(gia_prod),
            'copertura': esito,
        }, fh, ensure_ascii=False, indent=2)
    print('salvato analisi_manager/p20_grade_arene_perimetro_out.json')


if __name__ == '__main__':
    sys.exit(main() or 0)
