"""Cambio di metro (chat 06/08 sez.19): non i punti medi del giocatore
scelto, ma il PIAZZAMENTO dentro il pool della giornata -- e' quello che
conta in arena, dove il MAE 15-20pt rende la previsione assoluta rumore e
l'unica cosa che conta e' l'ordinamento fra chi fa boom e chi fa poco.

Riusa esattamente le stesse 93/94/38 giornate di sez.16/17 (V2 rows_v2:
mid/def/fwd, richiede atteso+grade+score disponibili, min 3 candidati per
giornata). Zero query.
"""
import os, sys, io, json, random, collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import importlib.util
spec = importlib.util.spec_from_file_location('briefA', 'analisi_manager/p12_briefA_mid.py')
briefA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(briefA)

random.seed(20260806)
BOOM_SOGLIE = (70.0, 90.0)


def costruisci_giornate(rows_v2):
    by_day = collections.defaultdict(list)
    for r in rows_v2:
        by_day[r['date'][:10]].append(r)
    giornate = []
    scartate = 0
    for day, rr in by_day.items():
        by_slug = {}
        for r in rr:
            by_slug.setdefault(r['slug'], r)
        rr = list(by_slug.values())
        if len(rr) < 3:
            scartate += 1
            continue
        giornate.append((day, rr))
    return giornate, scartate


def percentile_rank(scores, i):
    """Percentile del membro i dentro 'scores' (0=peggiore, 100=migliore),
    metodo: quota di membri con punteggio <= il proprio, tra 0 e 1, sui
    (n-1) confronti possibili."""
    n = len(scores)
    if n <= 1:
        return 50.0
    x = scores[i]
    minori_o_uguali = sum(1 for s in scores if s <= x) - 1  # esclude se stesso
    return 100.0 * minori_o_uguali / (n - 1)


def quartile_alto_soglia(scores):
    """Soglia del quartile alto (75-esimo percentile), metodo nearest-rank."""
    s = sorted(scores)
    n = len(s)
    idx = max(0, int(round(0.75 * (n - 1))))
    return s[idx]


def metriche_giornata(rr):
    scores = [r['score'] for r in rr]
    n = len(rr)
    soglia_q3 = quartile_alto_soglia(scores)
    best_score = max(scores)
    percentili = [percentile_rank(scores, i) for i in range(n)]
    return {'n': n, 'soglia_q3': soglia_q3, 'best_score': best_score, 'percentili': percentili}


def scegli(rr, chiave, zscore_combo=False):
    if zscore_combo:
        z_atteso = briefA.zscore([r['atteso'] for r in rr])
        z_grade = briefA.zscore([r['grade_num'] for r in rr])
        combinato = [a + g for a, g in zip(z_atteso, z_grade)]
        return max(range(len(rr)), key=lambda i: combinato[i])
    return max(range(len(rr)), key=lambda i: rr[i][chiave])


def valuta_strategia(giornate, nome):
    """Per ogni giornata calcola le 5 metriche per la strategia 'nome'
    ('atteso', 'grade', 'combinato', 'casuale'). Ritorna lista di righe
    per-giornata (una per metrica-indicatore, valori 0/1 o percentuali)."""
    righe = []
    for day, rr in giornate:
        m = metriche_giornata(rr)
        n = m['n']
        if nome == 'atteso':
            idx = scegli(rr, 'atteso')
            sel_score = rr[idx]['score']
            sel_perc = m['percentili'][idx]
            is_best = 1.0 if sel_score >= m['best_score'] else 0.0
            top_q = 1.0 if sel_score >= m['soglia_q3'] else 0.0
            boom = {s: (1.0 if sel_score >= s else 0.0) for s in BOOM_SOGLIE}
        elif nome == 'grade':
            idx = scegli(rr, 'grade_num')
            sel_score = rr[idx]['score']
            sel_perc = m['percentili'][idx]
            is_best = 1.0 if sel_score >= m['best_score'] else 0.0
            top_q = 1.0 if sel_score >= m['soglia_q3'] else 0.0
            boom = {s: (1.0 if sel_score >= s else 0.0) for s in BOOM_SOGLIE}
        elif nome == 'combinato':
            idx = scegli(rr, None, zscore_combo=True)
            sel_score = rr[idx]['score']
            sel_perc = m['percentili'][idx]
            is_best = 1.0 if sel_score >= m['best_score'] else 0.0
            top_q = 1.0 if sel_score >= m['soglia_q3'] else 0.0
            boom = {s: (1.0 if sel_score >= s else 0.0) for s in BOOM_SOGLIE}
        elif nome == 'casuale':
            # valore ATTESO di un sorteggio uniforme sul pool (media sui membri,
            # stesso principio gia' corretto in sez.16/17 per i punti medi)
            sel_score = sum(r['score'] for r in rr) / n  # solo per riferimento nella tabella 5
            sel_perc = sum(m['percentili']) / n
            is_best = 1.0 / n
            top_q = sum(1.0 for s in [rr[i]['score'] for i in range(n)] if s >= m['soglia_q3']) / n
            boom = {s: sum(1.0 for r in rr if r['score'] >= s) / n for s in BOOM_SOGLIE}
        else:
            raise ValueError(nome)
        righe.append({'day': day, 'n': n, 'sel_score': sel_score, 'sel_perc': sel_perc,
                      'is_best': is_best, 'top_q': top_q, 'boom70': boom[70.0], 'boom90': boom[90.0]})
    return righe


def boot_diff(righe_a, righe_b, campo, n_boot=1000):
    n = len(righe_a)
    assert n == len(righe_b)
    diffs = []
    for _ in range(n_boot):
        idxs = [random.randrange(n) for _ in range(n)]
        da = sum(righe_a[i][campo] for i in idxs) / n
        db = sum(righe_b[i][campo] for i in idxs) / n
        diffs.append(da - db)
    diffs.sort()
    pos = sum(1 for d in diffs if d > 0) / len(diffs)
    return {'media_diff': sum(diffs) / len(diffs), 'pct_positivo': pos,
           'IC95': [diffs[int(.025 * n_boot)], diffs[int(.975 * n_boot)]]}


def quantili(vals):
    v = sorted(vals)
    n = len(v)
    def q(p):
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return v[idx]
    return {'min': v[0], 'Q1': q(0.25), 'mediana': q(0.5), 'Q3': q(0.75), 'max': v[-1]}


def report_ruolo(ruolo, path_dati_gia_pronto=None, rows_v2=None):
    print('\n' + '=' * 70)
    print(f'--- {ruolo} ---')
    giornate, scartate = costruisci_giornate(rows_v2)
    print(f'  n_giornate={len(giornate)}  scartate(pool<3)={scartate}')
    if len(giornate) < 10:
        print(f'  CAMPIONE TROPPO PICCOLO ({len(giornate)} giornate), salto per {ruolo}')
        return None

    strategie = {}
    for nome in ('atteso', 'grade', 'combinato', 'casuale'):
        strategie[nome] = valuta_strategia(giornate, nome)

    tabella_medie = {}
    for nome, righe in strategie.items():
        tabella_medie[nome] = {
            'tasso_migliore_pct': 100 * sum(r['is_best'] for r in righe) / len(righe),
            'tasso_top_quartile_pct': 100 * sum(r['top_q'] for r in righe) / len(righe),
            'percentile_medio': sum(r['sel_perc'] for r in righe) / len(righe),
            'tasso_boom70_pct': 100 * sum(r['boom70'] for r in righe) / len(righe),
            'tasso_boom90_pct': 100 * sum(r['boom90'] for r in righe) / len(righe),
            'distribuzione_punteggio_scelto': quantili([r['sel_score'] for r in righe]),
        }
        print(f"  {nome:10s}  migliore={tabella_medie[nome]['tasso_migliore_pct']:.1f}%  "
              f"top_quartile={tabella_medie[nome]['tasso_top_quartile_pct']:.1f}%  "
              f"percentile_medio={tabella_medie[nome]['percentile_medio']:.1f}  "
              f"boom70={tabella_medie[nome]['tasso_boom70_pct']:.1f}%  "
              f"boom90={tabella_medie[nome]['tasso_boom90_pct']:.1f}%")

    confronti = {}
    for campo, label in (('is_best', 'tasso_migliore'), ('top_q', 'tasso_top_quartile'),
                         ('sel_perc', 'percentile_medio'), ('boom70', 'tasso_boom70'),
                         ('boom90', 'tasso_boom90')):
        confronti[label] = {
            'combinato_meno_atteso': boot_diff(strategie['combinato'], strategie['atteso'], campo),
            'combinato_meno_grade': boot_diff(strategie['combinato'], strategie['grade'], campo),
            'grade_meno_atteso': boot_diff(strategie['grade'], strategie['atteso'], campo),
        }
        print(f"  bootstrap {label}: comb-atteso={confronti[label]['combinato_meno_atteso']}  "
              f"grade-atteso={confronti[label]['grade_meno_atteso']}")

    return {'ruolo': ruolo, 'n_giornate': len(giornate), 'n_scartate': scartate,
           'tabella_medie': tabella_medie, 'confronti_bootstrap': confronti}


def main():
    ruoli = [
        ('Midfielder', 'analisi_manager/dati/storico_grade_Midfielder_20260806.json'),
        ('Defender', 'analisi_manager/dati/storico_grade_Defender_20260806.json'),
        ('Forward', 'analisi_manager/dati/storico_grade_Forward_20260806.json'),
    ]
    risultati = {}
    for ruolo, path_dati in ruoli:
        players, n_dup = briefA.load_mid(path_dati)
        rows, scarti = briefA.build_rows(players)
        v2, rows_v2 = briefA.run_v2(rows, ruolo=ruolo)
        briefA._ctx_cache.clear()
        if not rows_v2:
            print(f'{ruolo}: 0 righe con score_atteso, salto')
            continue
        risultati[ruolo] = report_ruolo(ruolo, rows_v2=rows_v2)

    with open('analisi_manager/p12_arena_metrics_out.json', 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
