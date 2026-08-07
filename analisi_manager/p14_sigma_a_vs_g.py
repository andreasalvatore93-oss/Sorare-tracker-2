"""Sez.TAPPA2 -- SIGMA della calibrazione formazione, A vs G, sullo stesso
campione ampio gia' usato da p12_backtest_formazione_grade.py (crowss+16+
satonio, arene cap 260/220 reali, walk-forward).

NON reinventa nulla: riusa p12_backtest_formazione_grade (costruisci/gioca/
capitano_atteso/realizzato, GIA' VALIDATO) per selezionare le formazioni A
(obiettivo=atteso_cal) e G (obiettivo=atteso_combinato). La differenza con
p12 e' SOLO la misura: qui si fitta realizzato = a + b*previsto e si
confronta la SIGMA residua fra le formazioni scelte da A e quelle scelte da
G, dove 'previsto' e' SEMPRE la somma di atteso_cal (il valore calibrato,
scala onesta -- MAI atteso_combinato, che e' un punteggio di SELEZIONE
gonfiato dal boost grade, non una previsione -- vedi rettifica sez.4ter di
BRIEF_SONNET_TEST_DIFF_GRADE_GW3).

Questo risponde alla domanda della catena (BRIEF_SONNET_CATENA_G sez.1): le
formazioni scelte da G hanno una sigma diversa attorno al LORO stesso atteso
onesto, rispetto a quelle scelte da A?
"""
import os, sys, io, json, math, random, statistics

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SP = os.path.dirname(os.path.abspath(__file__))
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, SP)

import p12_backtest_formazione_grade as p12

CAP = 0.2  # bonus capitano nelle arene cappate (0.2), coerente con valida_soglie.py


def retta(X, Y):
    mx, my = statistics.mean(X), statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    sd = statistics.pstdev([y - (a + b * x) for x, y in zip(X, Y)])
    return a, b, sd


def pearson(X, Y):
    n = len(X); mx = sum(X) / n; my = sum(Y) / n
    sx = sum((x - mx) ** 2 for x in X); sy = sum((y - my) ** 2 for y in Y)
    if sx == 0 or sy == 0:
        return float('nan')
    return sum((x - mx) * (y - my) for x, y in zip(X, Y)) / math.sqrt(sx * sy)


def previsto(formazione):
    """Somma atteso_cal (calibrato onesto) + bonus capitano, MAI atteso_combinato."""
    cap_row = p12.capitano_atteso(formazione)
    tot = sum(r['atteso_cal'] for _s, r, _t in formazione)
    if cap_row is not None:
        tot += CAP * cap_row['atteso_cal']
    return tot


def boot_ci(vals, B=4000, seed=7):
    rnd = random.Random(seed)
    n = len(vals)
    out = []
    for _ in range(B):
        camp = [vals[rnd.randrange(n)] for _ in range(n)]
        out.append(statistics.mean(camp))
    out.sort()
    return out[int(.025 * B)], out[int(.975 * B)]


def main():
    idx_grade, data_min = p12.carica_indice_grade()
    fixtures_ammesse = [fx for fx, gw in p12.pool_per_gw.items()
                        if gw['cutoff'][:10] >= data_min[:10]]
    print(f'fixture ammesse (stesso criterio di p12): {len(fixtures_ammesse)}/{len(p12.pool_per_gw)}')

    righe_a = []  # (previsto, realizzato)
    righe_g = []
    saltate = 0

    for fx, gw in sorted(p12.pool_per_gw.items(), key=lambda kv: kv[1]['cutoff']):
        if fx not in set(fixtures_ammesse):
            continue
        slots = [s for s in gw['slot'] if s['tipo'] in p12.TIPI_CAPPED
                 and s.get('punteggi') and s.get('mio_score') is not None]
        if not slots:
            continue
        pool = [c for c in gw['pool'] if c.get('reale') is not None]
        import collections
        ruoli = collections.Counter(c['codice'] for c in pool)
        if not all(ruoli[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
            saltate += 1
            continue

        data_gw = gw['fine'][:10]
        for c in pool:
            c['_cal'] = p12.bfg.calibra(c['atteso_raw'], c['codice'])
            key = (c['slug'], data_gw)
            c['_grade'] = idx_grade.get(key)

        gruppi = collections.defaultdict(list)
        for c in pool:
            gruppi[(c['lega'], c['codice'])].append(c)
        for (lg, cod), membri in gruppi.items():
            _z, sd_atteso, _m = p12.zscore_gruppo([m['_cal'] for m in membri])
            grade_vals = [m['_grade'] for m in membri if m['_grade'] is not None]
            if len(grade_vals) >= 2:
                z_grade_presenti, _, _ = p12.zscore_gruppo(grade_vals)
                it = iter(z_grade_presenti)
                for m in membri:
                    m['_zgrade'] = next(it) if m['_grade'] is not None else 0.0
            else:
                for m in membri:
                    m['_zgrade'] = 0.0
            for m in membri:
                m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']

        slots = sorted(slots, key=lambda s: (s['tipo'], s['slug']))
        fa = p12.gioca(gw, slots, lambda c: c['_cal'], depleta=True)
        fg = p12.gioca(gw, slots, lambda c: c['_combinato'], depleta=True)

        for la, lg_ in zip(fa, fg):
            if la is not None:
                ca = p12.capitano_atteso(la)
                righe_a.append((previsto(la), p12.realizzato(la, ca)))
            if lg_ is not None:
                cg = p12.capitano_atteso(lg_)
                righe_g.append((previsto(lg_), p12.realizzato(lg_, cg)))

    print(f'giornate saltate (pool incompleto): {saltate}')
    print(f'formazioni A valide: {len(righe_a)}   formazioni G valide: {len(righe_g)}')

    def report(nome, righe):
        X = [x for x, _y in righe]; Y = [y for _x, y in righe]
        a, b, sd = retta(X, Y)
        print(f'\n--- {nome} (n={len(righe)}) ---')
        print(f'  realizzato = {a:+.2f} {b:+.3f}*previsto   SIGMA = {sd:.2f}')
        print(f'  corr(previsto,realizzato) = {pearson(X,Y):+.3f}')
        print(f'  media previsto {statistics.mean(X):.1f}   media realizzato {statistics.mean(Y):.1f}')
        return a, b, sd

    a_a, b_a, sd_a = report('A (obiettivo=atteso_cal)', righe_a)
    a_g, b_g, sd_g = report('G (obiettivo=atteso_combinato, valutato su atteso_cal)', righe_g)

    print('\n' + '=' * 72)
    print('CONFRONTO SIGMA -- decide se le soglie vanno rifittate')
    print('=' * 72)
    print(f'  SIGMA_A = {sd_a:.2f}   SIGMA_G = {sd_g:.2f}   delta = {sd_g - sd_a:+.2f}')

    # bootstrap sui residui per un'idea di incertezza (per-formazione, non per-giornata:
    # qui il campione unitario e' la formazione, coerente con quanto si sta stimando)
    res_a = [y - (a_a + b_a * x) for x, y in righe_a]
    res_g = [y - (a_g + b_g * x) for x, y in righe_g]
    sd_a_lo, sd_a_hi = boot_ci([r ** 2 for r in res_a])
    sd_g_lo, sd_g_hi = boot_ci([r ** 2 for r in res_g])
    print(f'  bootstrap IC95 varianza residua A: [{sd_a_lo**0.5:.2f}, {sd_a_hi**0.5:.2f}]')
    print(f'  bootstrap IC95 varianza residua G: [{sd_g_lo**0.5:.2f}, {sd_g_hi**0.5:.2f}]')
    sovrapposti = not (sd_g_hi ** 0.5 < sd_a_lo ** 0.5 or sd_a_hi ** 0.5 < sd_g_lo ** 0.5)
    print(f'  IC si sovrappongono: {sovrapposti} -> '
          f'{"SIGMA NON cambia in modo stabile, soglie INVARIATE" if sovrapposti else "SIGMA CAMBIA, valutare rifit soglie"}')

    with open(os.path.join(SP, 'p14_sigma_a_vs_g_out.json'), 'w', encoding='utf-8') as fh:
        json.dump({
            'n_a': len(righe_a), 'n_g': len(righe_g),
            'a_A': a_a, 'b_A': b_a, 'sigma_A': sd_a,
            'a_G': a_g, 'b_G': b_g, 'sigma_G': sd_g,
            'righe_a': righe_a, 'righe_g': righe_g,
        }, fh, ensure_ascii=False)


if __name__ == '__main__':
    main()
