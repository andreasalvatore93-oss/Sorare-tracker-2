"""misura_sinergie_coppie — le sinergie per COPPIA DI RUOLI, rimisurate sui
residui del modello VIVO.

PERCHE' RIFARLA. I bonus in produzione vengono da due misure fatte in momenti
diversi e su scale diverse:
  - SAME_TEAM_SYNERGY_BONUS_BY_PAIR (02/08): correlazione dei RESIDUI, poi
    convertita in punti di punteggio atteso -> valori 0.1..1.2
  - CROSS_TEAM_PENALTY_BY_PAIR (31/07): correlazione dei PUNTEGGI x20 grezzo
    -> valori 2..6, cioe' una scala cinque volte piu' larga
E soprattutto: entrambe sono PRECEDENTI al blend P(porta inviolata) nel
portiere (03/08, c174f1cf1d). Quel blend sposta dentro la previsione una parte
dell'evento di squadra che prima finiva nel residuo: la correlazione GK-DEF dei
residui DEVE essere cambiata, e nessuno l'ha ancora rimisurata.

COSA FA. Legge le coppie previsione/realizzato walk-forward gia' salvate da
taratura_giocatore.py, calcola i residui rispetto alla retta di calibrazione
globale e misura, per ogni coppia di ruoli:
  - same-team: due giocatori della STESSA squadra nella stessa partita
  - cross-team: due giocatori delle DUE squadre della stessa partita
  - controllo: stessa coppia di ruoli ma partite DIVERSE (deve uscire ~0;
    serve a distinguere l'effetto dello scontro diretto dalla semplice forma
    delle distribuzioni di ruolo)
Poi converte la correlazione nel bonus in punti con la stessa catena gia' usata
in produzione: quanto aggiunge quella coppia alla dispersione di una formazione
da 5, per quanto vale un punto di dispersione a FORZA_RIFERIMENTO.

Uso:  python formazione_mls/diagnostics/misura_sinergie_coppie.py
      python formazione_mls/diagnostics/misura_sinergie_coppie.py --coppie altro.json
      python formazione_mls/diagnostics/misura_sinergie_coppie.py --confronta vecchio.json
"""
import argparse
import collections
import json
import math
import os
import random
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RUOLO_BREVE = {'Goalkeeper': 'GK', 'Defender': 'DEF',
               'Midfielder': 'MID', 'Forward': 'FWD'}
ORDINE = ('GK', 'DEF', 'MID', 'FWD')
N_BOOT = int(os.environ.get('N_BOOT', '400'))
# valore di un punto di dispersione a FORZA_RIFERIMENTO=280, misurato in arena
# (vedi build_formazione_finale._CAMBIO_DISPERSIONE)
VALORE_DISPERSIONE = 0.53
N_SLOT = 5


def retta(X, Y):
    mx, my = statistics.mean(X), statistics.mean(Y)
    den = sum((x - mx) ** 2 for x in X)
    b = sum((x - mx) * (y - my) for x, y in zip(X, Y)) / den if den else 0.0
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(X, Y)]
    return a, b, statistics.pstdev(res)


def rho_di(coppie):
    if len(coppie) < 2:
        return 0.0
    A = [x for x, _ in coppie]
    B = [y for _, y in coppie]
    ma, mb = statistics.mean(A), statistics.mean(B)
    cov = sum((x - ma) * (y - mb) for x, y in zip(A, B)) / len(A)
    sa, sb = statistics.pstdev(A), statistics.pstdev(B)
    return cov / (sa * sb) if sa and sb else 0.0


def ic_bootstrap(coppie, rng):
    """IC 95% della correlazione. Ricampiona le coppie: e' l'unita' su cui si
    decide, e con n grande basta a distinguere segnale da rumore."""
    if len(coppie) < 50:
        return None, None
    n = len(coppie)
    vals = []
    for _ in range(N_BOOT):
        camp = [coppie[rng.randrange(n)] for _ in range(n)]
        vals.append(rho_di(camp))
    vals.sort()
    return vals[int(0.025 * N_BOOT)], vals[int(0.975 * N_BOOT) - 1]


def bonus_da_rho(rho, sd):
    """Punti di punteggio atteso che vale accoppiare quei due ruoli, a 280.
    Stessa catena del commento su GK_DEF_PAIR_BONUS: la coppia aggiunge
    2*rho*sd^2 alla varianza di una formazione da 5 slot indipendenti."""
    var_base = N_SLOT * sd * sd
    var_con = var_base + 2 * rho * sd * sd
    if var_con < 0:
        return 0.0
    return (math.sqrt(var_con) - math.sqrt(var_base)) * VALORE_DISPERSIONE


def carica(path):
    with open(path, encoding='utf-8') as fh:
        coppie = json.load(fh)
    for c in coppie:
        c['r'] = RUOLO_BREVE.get(c['ruolo'], c['ruolo'])
    return coppie


def residui(coppie):
    X = [c['previsto'] for c in coppie]
    Y = [c['reale'] for c in coppie]
    a, b, sd = retta(X, Y)
    for c in coppie:
        c['res'] = c['reale'] - (a + b * c['previsto'])
    return a, b, sd


def accoppia(coppie):
    """-> (same_team, cross_team), ognuno {frozenset(ruoli): [(res, res)]}"""
    per_partita = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in coppie:
        if c.get('squadra') and c.get('partita'):
            per_partita[c['partita']][c['squadra']].append((c['r'], c['res']))
    same = collections.defaultdict(list)
    cross = collections.defaultdict(list)
    for squadre in per_partita.values():
        for v in squadre.values():
            for i in range(len(v)):
                for j in range(i + 1, len(v)):
                    same[frozenset((v[i][0], v[j][0]))].append((v[i][1], v[j][1]))
        nomi = list(squadre)
        for i in range(len(nomi)):
            for j in range(i + 1, len(nomi)):
                for ra, xa in squadre[nomi[i]]:
                    for rb, xb in squadre[nomi[j]]:
                        cross[frozenset((ra, rb))].append((xa, xb))
    return same, cross


def controllo(coppie, chiavi, rng):
    """Stessa coppia di ruoli ma partite DIVERSE: la riga di riferimento."""
    per_ruolo = collections.defaultdict(list)
    for c in coppie:
        per_ruolo[c['r']].append((c['partita'], c['res']))
    out = {}
    for k in chiavi:
        ruoli = sorted(k) if len(k) > 1 else list(k) * 2
        a, b = per_ruolo.get(ruoli[0], []), per_ruolo.get(ruoli[1], [])
        if len(a) < 100 or len(b) < 100:
            continue
        camp = []
        for _ in range(20000):
            x = a[rng.randrange(len(a))]
            y = b[rng.randrange(len(b))]
            if x[0] != y[0]:
                camp.append((x[1], y[1]))
        out[k] = rho_di(camp)
    return out


def etichetta(k):
    ruoli = sorted(k, key=ORDINE.index) if len(k) > 1 else list(k) * 2
    return f'{ruoli[0]}-{ruoli[1]}'


def tabella(titolo, gruppi, sd, ctrl, rng, minimo=200):
    print(f'\n=== {titolo}')
    print(f'{"coppia":10s} {"n":>7s} {"rho":>8s} {"IC 95%":>18s} '
          f'{"ctrl":>7s} {"netto":>8s} {"punti@280":>10s}')
    righe = []
    for k, v in gruppi.items():
        if len(v) < minimo:
            continue
        r = rho_di(v)
        lo, hi = ic_bootstrap(v, rng)
        c = ctrl.get(k, 0.0)
        netto = r - c
        righe.append((abs(netto), etichetta(k), len(v), r, lo, hi, c, netto,
                      bonus_da_rho(netto, sd)))
    for _, nome, n, r, lo, hi, c, netto, pt in sorted(righe, reverse=True):
        ic = f'[{lo:+.3f},{hi:+.3f}]' if lo is not None else '        -        '
        zero = ' ' if (lo is None or lo * hi > 0) else '~0'
        print(f'{nome:10s} {n:7d} {r:+8.3f} {ic:>18s} {c:+7.3f} {netto:+8.3f} '
              f'{pt:+10.2f} {zero}')
    return {etichetta(k): (len(v), rho_di(v)) for k, v in gruppi.items() if len(v) >= minimo}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--coppie', default='dati_globali/taratura_coppie.json')
    ap.add_argument('--confronta', help='file coppie precedente, per il prima/dopo')
    ap.add_argument('--json')
    args = ap.parse_args()

    rng = random.Random(7)
    coppie = carica(args.coppie)
    a, b, sd = residui(coppie)
    print(f'{len(coppie)} coppie previsione/realizzato da {args.coppie}')
    print(f'  calibrazione: realizzato = {a:.2f} + {b:.3f} x previsto')
    print(f'  errore del singolo giocatore: {sd:.2f} punti')

    same, cross = accoppia(coppie)
    ctrl_s = controllo(coppie, list(same), rng)
    ctrl_c = controllo(coppie, list(cross), rng)
    t_same = tabella('SAME-TEAM (compagni, stessa partita)', same, sd, ctrl_s, rng)
    t_cross = tabella('CROSS-TEAM (avversari, stessa partita)', cross, sd, ctrl_c, rng)

    if args.confronta:
        vecchie = carica(args.confronta)
        _, _, sd_v = residui(vecchie)
        same_v, cross_v = accoppia(vecchie)
        print(f'\n=== PRIMA/DOPO ({args.confronta}: {len(vecchie)} coppie, sd {sd_v:.2f})')
        for nome, gruppi_v, gruppi_n in (('same-team', same_v, same),
                                          ('cross-team', cross_v, cross)):
            print(f'\n  {nome:10s} {"prima":>18s} {"dopo":>18s}   variazione')
            for k in sorted(set(gruppi_v) | set(gruppi_n), key=etichetta):
                v, n = gruppi_v.get(k, []), gruppi_n.get(k, [])
                if len(v) < 200 or len(n) < 200:
                    continue
                rv, rn = rho_di(v), rho_di(n)
                print(f'  {etichetta(k):10s} {rv:+8.3f} (n={len(v):6d}) '
                      f'{rn:+8.3f} (n={len(n):6d})   {rn - rv:+.3f}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'n_coppie': len(coppie), 'intercetta': a, 'pendenza': b,
                       'errore_giocatore': sd, 'same_team': t_same,
                       'cross_team': t_cross}, fh, indent=1)
        print(f'\nsalvato in {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
