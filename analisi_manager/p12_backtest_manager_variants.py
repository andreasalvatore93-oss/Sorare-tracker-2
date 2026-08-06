"""Sez.23-bis punto 5: A e' risultato NULLO/negativo con la combinazione
neutra (delta -2.254, IC95 [-7.432, 0.000], 0% positivo) -- cerca SOLO su
gruppo A la combinazione migliore fra grade e score_atteso. Il gruppo B
resta intoccato fino alla verifica finale.

Riusa la costruzione pool di p12_backtest_manager_grade.py (proxy
walk-backward + le 5 carte schierate, dichiarato in sez.23-bis), calcolata
UNA VOLTA (score_atteso/grade non cambiano fra varianti), poi valuta 6
varianti dichiarate della funzione obiettivo:
  V1 peso 0.5   -- combinato con meta' peso sul grade
  V2 peso 2.0   -- combinato con doppio peso sul grade
  V3 solo MID   -- grade applicato SOLO al ruolo MID (altri = atteso puro)
  V4 solo MID+DEF -- grade su MID e DEF (altri = atteso puro)
  V5 solo FWD   -- grade applicato SOLO al ruolo FWD (sez.22: su FWD il
                   grade-solo batteva la combinazione)
  V6 grade-dominante -- dove il grade e' presente nel gruppo lo fa pesare
                   molto di piu' (z_grade*5 + atteso_cal), altrimenti puro
                   atteso (approssima "grade da solo quando disponibile")
6 varianti, tutte riportate (anche se nessuna vince): dichiarato PRIMA di
guardare quale vince, per sapere quanto scontare un'eventuale vittoria
(6 confronti multipli aumentano la probabilita' di un falso positivo).
"""
import os, sys, io, json, random, datetime, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p12_backtest_formazione_grade as S21
import analizza_gw as AG
import p12_backtest_manager_grade as M  # riusa parse_fixture_bounds/reale_in_finestra/ROLE_CODE/COMP_TO_TIPO

cache = CACHE.CacheLocale()
random.seed(20260806)


def raccogli_casi(gruppo):
    idx_grade, _ = M.carica_indice_grade_esteso()
    lega_di = AG.indice_lega()

    fixtures = sorted({os.path.basename(f)[len('formazioni_'):-len('.json')]
                       for f in __import__('glob').glob('analisi_manager/dati/formazioni_football-*.json')})
    bounds = {fx: M.parse_fixture_bounds(fx) for fx in fixtures}

    manager_giornate = {}
    for mf in __import__('glob').glob('dati_globali/manager_*.json'):
        man = os.path.basename(mf)[len('manager_'):-len('.json')]
        if man not in gruppo:
            continue
        d = json.load(open(mf, encoding='utf-8'))
        manager_giornate[man] = d.get('giornate') or {}

    casi = []
    for man in gruppo:
        giornate = manager_giornate.get(man)
        if not giornate:
            continue
        fixture_bounds_manager = {fx: M.parse_fixture_bounds(fx) for fx in giornate}
        for fx in fixtures:
            b_target = bounds.get(fx)
            if b_target is None:
                continue
            fpath = f'analisi_manager/dati/formazioni_{fx}.json'
            if not os.path.exists(fpath):
                continue
            forms_target = [f for f in json.load(open(fpath, encoding='utf-8'))
                            if f['manager'] == man and f['competizione'] in M.COMP_TO_TIPO]
            if not forms_target:
                continue

            proxy = {}
            for fx2, forms2 in giornate.items():
                if fx2 == fx:
                    continue
                b2 = fixture_bounds_manager.get(fx2)
                if b2 is None or b2[0] >= b_target[0]:
                    continue
                for f2 in forms2:
                    for c in f2.get('carte') or []:
                        if c.get('rarita') != 'limited' or c.get('in_season'):
                            continue
                        slug = c.get('slug')
                        if slug:
                            proxy[slug] = c

            for f in forms_target:
                pool_completo = dict(proxy)
                for c in f.get('carte') or []:
                    slug = c.get('slug')
                    if slug and slug not in pool_completo:
                        pool_completo[slug] = {'ruolo': c.get('ruolo')}
                if len(pool_completo) < 15:
                    continue

                tipo, tipo_bfg, l10cap = M.COMP_TO_TIPO[f['competizione']]
                d_start, d_end = b_target
                fine = datetime.datetime(d_end.year, d_end.month, d_end.day, 23, 59)

                pool_rows = []
                ruoli_presenti = collections.Counter()
                for slug, card in pool_completo.items():
                    ruolo_full = card.get('ruolo')
                    cod = M.ROLE_CODE.get(ruolo_full)
                    if cod is None:
                        continue
                    r = P.score_atteso(cache, slug, ruolo_full, fine)
                    if r is None or r.get('atteso') is None:
                        continue
                    reale = M.reale_in_finestra(slug, d_start, d_end)
                    lega = lega_di.get(slug) or 'senza_lega'
                    pool_rows.append({
                        'slug': slug, 'codice': cod, 'lega': lega,
                        'squadra': r.get('squadra'), 'opp_slug': r.get('opp_slug'),
                        'atteso_raw': r['atteso'], 'l10': r.get('l10'),
                        'copie': 1, 'reale': reale if reale is not None else 0.0,
                    })
                    ruoli_presenti[cod] += 1
                if not all(ruoli_presenti[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
                    continue

                for c in pool_rows:
                    c['_cal'] = S21.bfg.calibra(c['atteso_raw'], c['codice'])
                    c['_grade'] = idx_grade.get((c['slug'], d_end.isoformat()))

                gruppi = collections.defaultdict(list)
                for c in pool_rows:
                    gruppi[(c['lega'], c['codice'])].append(c)
                for (lg, cod), membri in gruppi.items():
                    _z_atteso, sd_atteso, _m = S21.zscore_gruppo([m['_cal'] for m in membri])
                    grade_presenti = [m['_grade'] for m in membri if m['_grade'] is not None]
                    if len(grade_presenti) >= 2:
                        z_grade_p, _, _ = S21.zscore_gruppo(grade_presenti)
                        it = iter(z_grade_p)
                        for m in membri:
                            m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
                    else:
                        for m in membri:
                            m['_zgrade'] = 0.0
                    for m in membri:
                        m['_sd_atteso'] = sd_atteso

                slot = {'slug': f'{man}_{fx}_{tipo}', 'tipo': tipo, 'tipo_bfg': tipo_bfg}
                casi.append({'manager': man, 'fixture': fx, 'tipo': tipo, 'pool': pool_rows, 'slot': slot})
    return casi


def obiettivo_variante(nome):
    if nome == 'V1_peso0.5':
        return lambda c: c['_cal'] + c['_sd_atteso'] * 0.5 * c['_zgrade']
    if nome == 'V2_peso2.0':
        return lambda c: c['_cal'] + c['_sd_atteso'] * 2.0 * c['_zgrade']
    if nome == 'V3_soloMID':
        return lambda c: (c['_cal'] + c['_sd_atteso'] * c['_zgrade']) if c['codice'] == 'MID' else c['_cal']
    if nome == 'V4_soloMIDDEF':
        return lambda c: (c['_cal'] + c['_sd_atteso'] * c['_zgrade']) if c['codice'] in ('MID', 'DEF') else c['_cal']
    if nome == 'V5_soloFWD':
        return lambda c: (c['_cal'] + c['_sd_atteso'] * c['_zgrade']) if c['codice'] == 'FWD' else c['_cal']
    if nome == 'V6_gradeDominante':
        return lambda c: c['_cal'] + c['_sd_atteso'] * 5.0 * c['_zgrade']
    raise ValueError(nome)


def valuta(casi, obiettivo, seed=20260806):
    righe = []
    for caso in casi:
        gw = {'pool': caso['pool']}
        fa = S21.gioca(gw, [caso['slot']], lambda c: c['_cal'], depleta=True)
        fg = S21.gioca(gw, [caso['slot']], obiettivo, depleta=True)
        la, lg_ = fa[0], fg[0]
        if la is None or lg_ is None:
            continue
        ca = S21.capitano_atteso(la)
        cg = S21.capitano_atteso(lg_)
        pa = S21.realizzato(la, ca)
        pg = S21.realizzato(lg_, cg)
        righe.append({'manager': caso['manager'], 'fixture': caso['fixture'], 'A_punti': pa, 'G_punti': pg})

    if not righe:
        return None
    by_coppia = collections.defaultdict(list)
    for r in righe:
        by_coppia[(r['manager'], r['fixture'])].append(r)
    unita = list(by_coppia.values())
    n = len(unita)
    rnd = random.Random(seed)
    diffs = []
    for _ in range(4000):
        num, den = 0.0, 0
        for _ in range(n):
            g = unita[rnd.randrange(n)]
            for r in g:
                num += r['G_punti'] - r['A_punti']; den += 1
        if den:
            diffs.append(num / den)
    diffs.sort()
    d_medio = sum(r['G_punti'] - r['A_punti'] for r in righe) / len(righe)
    return {'n_righe': len(righe), 'n_coppie': n, 'delta_medio': d_medio,
           'IC95': [diffs[int(.025 * len(diffs))], diffs[int(.975 * len(diffs))]],
           'pct_positivo': sum(1 for d in diffs if d > 0) / len(diffs)}


def main():
    gruppo_a = ['braddersfc', 'eoghankelly', 'lairdinho', 'ninoshooter', 'shirimimi']
    print(f'GRUPPO A: {gruppo_a}')
    casi = raccogli_casi(gruppo_a)
    print(f'casi raccolti (gruppo A, pool>=15, tutti i ruoli): {len(casi)}')

    varianti = ['V1_peso0.5', 'V2_peso2.0', 'V3_soloMID', 'V4_soloMIDDEF', 'V5_soloFWD', 'V6_gradeDominante']
    risultati = {}
    print(f'\n6 varianti dichiarate PRIMA di guardare i risultati: {varianti}\n')
    for nome in varianti:
        ob = obiettivo_variante(nome)
        res = valuta(casi, ob)
        risultati[nome] = res
        if res:
            print(f'{nome:20s} n_righe={res["n_righe"]:3d} n_coppie={res["n_coppie"]:2d} '
                  f'delta={res["delta_medio"]:+.3f}  IC95=[{res["IC95"][0]:+.3f},{res["IC95"][1]:+.3f}]  '
                  f'pos={100*res["pct_positivo"]:.1f}%')
        else:
            print(f'{nome:20s} NESSUNA RIGA VALIDA')

    with open('analisi_manager/p12_backtest_manager_variants_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1)
    print('\nsalvato analisi_manager/p12_backtest_manager_variants_out.json')


if __name__ == '__main__':
    main()
