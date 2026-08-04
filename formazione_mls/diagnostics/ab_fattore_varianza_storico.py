"""ab_fattore_varianza_storico — FORZA_NORM su TANTE giornate vere, non una.

ab_fattore_varianza.py misura la stessa cosa ma su UNA sola giornata (lo
snapshot dei consigli su disco) e con un Monte Carlo: e' il limite noto di
quella misura, lo stesso che aveva la calibrazione del 31/07. Qui invece si
rigenerano le formazioni su TUTTE le giornate storiche disponibili, e il
punteggio non e' simulato ma REALIZZATO davvero.

METODO. Per ogni giornata in arene_formazioni.json:
  - il pool sono le carte che l'utente possedeva DAVVERO quel giorno
  - le previsioni sono walk-forward (cutoff = inizio-giornata, come in
    produzione dopo il fix del leak del 04/08)
  - si generano le formazioni ALL STARS col generatore VERO, due volte:
    FORZA_NORM spento (produzione oggi) e acceso
  - si somma il punteggio REALE dei giocatori scelti, col bonus capitano
Poi si confrontano media e, soprattutto, la frequenza con cui si superano le
soglie: il premio e' una funzione a gradini del piazzamento, quindi e' li' che
si gioca, non sulla media.

Tutta la costruzione del pool storico e' riusata da backtest_arene_produzione
(costruisci_role_data_e_pool), che e' gia' agganciata al generatore di
produzione: nessuna imitazione scritta a parte.

Uso:  python formazione_mls/diagnostics/ab_fattore_varianza_storico.py
      MAX_GIORNATE=10 python formazione_mls/diagnostics/ab_fattore_varianza_storico.py
      TIPO=ALLSTARS QUANTE=4 python .../ab_fattore_varianza_storico.py
"""
import collections
import copy
import os
import statistics
import sys

os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

import backtest_arene_produzione as BP  # noqa: E402

bfg = BP.bfg
bff = BP.bff
B = BP.B
C = BP.C

TIPO = os.environ.get('TIPO', 'ALLSTARS')
QUANTE = int(os.environ.get('QUANTE', '4'))
MAX_GIORNATE = int(os.environ.get('MAX_GIORNATE', '0'))
# All Stars: capitano +50%. E' il tipo dove il difetto vive (7 slot).
CAP = float(os.environ.get('CAP_BONUS', '0.5'))
SOGLIE = [float(x) for x in os.environ.get(
    'SOGLIE', '380,410,440,470,500,530').split(',')]


def genera(role_data, pools, card_pool_base, leghe, norm):
    bff.FORZA_NORM = norm
    # copia profonda: il CardPool viene CONSUMATO dalla generazione, i due rami
    # devono partire dalle stesse copie disponibili
    card_pool = copy.deepcopy(card_pool_base)
    leghe_orig = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe)
    try:
        return bfg.generate_lineups_for_type(TIPO, QUANTE, role_data, pools, card_pool)
    finally:
        bfg.LEAGUES = leghe_orig


def totale_reale(formazione):
    """Punteggio REALIZZATO della formazione, col bonus capitano. None se anche
    una sola carta non ha il punteggio vero (giornata non valutabile)."""
    _slot, cap_row, _ct = bff.pick_captain(formazione)
    reali = [r.get('reale') for _s, r, _t in formazione]
    if any(v is None for v in reali) or cap_row.get('reale') is None:
        return None
    return sum(reali) + CAP * cap_row['reale']


def main():
    cache = C.CacheLocale()
    formazioni = BP.carica('dati_globali/arene_formazioni.json')['formazioni']
    arene_storico = BP.carica('dati_globali/arene_storico.json')['arene']
    fine = B.fine_giornate(arene_storico)

    fixtures = sorted({v['fixture'] for v in formazioni.values()})
    if MAX_GIORNATE:
        fixtures = fixtures[-MAX_GIORNATE:]
    print(f'{len(fixtures)} giornate candidate, tipo {TIPO} x{QUANTE}, '
          f'bonus capitano {CAP:+.0%}')

    tot = {False: [], True: []}
    per_giornata = []
    saltate = collections.Counter()
    for i, fx in enumerate(fixtures, 1):
        fd = fine.get(fx)
        if fd is None:
            saltate['senza data di chiusura'] += 1
            continue
        carte, _f = BP.raccogli_giornata(formazioni, fx)
        if not carte:
            saltate['nessuna carta'] += 1
            continue
        try:
            cutoff = B.inizio_giornata(
                cache, fd, sorted(set((c['slug'], c['ruolo']) for c in carte.values())))
            role_data, pools, card_pool_base, leghe, _prev, _manc = \
                BP.costruisci_role_data_e_pool(cache, fd, cutoff, carte)
        except Exception as exc:
            saltate[f'pool non costruibile ({type(exc).__name__})'] += 1
            continue

        risultati = {}
        for norm in (False, True):
            # i pools sono consumati/cresciuti dalla generazione: se ne rifa'
            # uno pulito per ogni ramo, altrimenti il secondo partirebbe da uno
            # stato diverso e il confronto non sarebbe piu' fra pari
            pools_puliti = {lg: {r: bfg._NoFilterPool(r, lg, role_data[lg][r])
                                 for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in role_data}
            try:
                out = genera(role_data, pools_puliti, card_pool_base, leghe, norm)
            except Exception as exc:
                risultati = {}
                saltate[f'generazione fallita ({type(exc).__name__})'] += 1
                break
            punteggi = []
            for r in out:
                if 'error' in r:
                    continue
                t = totale_reale(r['formazione'])
                if t is not None:
                    punteggi.append(t)
            risultati[norm] = punteggi
        if not risultati or not risultati[False] or not risultati[True]:
            saltate['nessuna formazione valutabile'] += 1
            continue
        if len(risultati[False]) != len(risultati[True]):
            saltate['numero di formazioni diverso fra i due rami'] += 1
            continue

        tot[False] += risultati[False]
        tot[True] += risultati[True]
        per_giornata.append((fx, statistics.mean(risultati[False]),
                             statistics.mean(risultati[True])))
        if i % 10 == 0:
            print(f'  [{i}/{len(fixtures)}] {len(per_giornata)} giornate valutate', flush=True)

    print(f'\ngiornate valutate: {len(per_giornata)}   '
          f'formazioni per ramo: {len(tot[False])}')
    for motivo, n in saltate.most_common():
        print(f'  saltate {n}: {motivo}')
    if not per_giornata:
        return 1

    print(f'\n  punteggio REALE medio per formazione')
    print(f'    produzione oggi : {statistics.mean(tot[False]):7.2f}')
    print(f'    FORZA_NORM=1    : {statistics.mean(tot[True]):7.2f}   '
          f'({statistics.mean(tot[True]) - statistics.mean(tot[False]):+.2f})')

    diff = [b - a for _fx, a, b in per_giornata]
    meglio = sum(1 for d in diff if d > 0.01)
    peggio = sum(1 for d in diff if d < -0.01)
    print(f'\n  per giornata: {meglio} meglio, {peggio} peggio, '
          f'{len(diff) - meglio - peggio} identiche')
    if len(diff) > 2:
        m = statistics.mean(diff)
        se = statistics.pstdev(diff) / (len(diff) ** 0.5)
        print(f'  differenza media per giornata {m:+.2f}  IC95% '
              f'[{m - 1.96 * se:+.2f}, {m + 1.96 * se:+.2f}]')

    print(f'\n  {"soglia":>8} {"oggi":>9} {"variante":>10} {"differenza":>13}')
    for s in SOGLIE:
        pa = sum(1 for x in tot[False] if x > s) / len(tot[False]) * 100
        pb = sum(1 for x in tot[True] if x > s) / len(tot[True]) * 100
        print(f'  {s:>8.0f} {pa:>8.2f}% {pb:>9.2f}% {pb - pa:>+12.2f} pp')
    return 0


if __name__ == '__main__':
    sys.exit(main())
