"""Confronta i parametri di PRODUZIONE con il vincitore della griglia, in pool
su tutte le leghe calibrate, con bootstrap sui giocatori.

  python analizza_calibrazione_pooled.py            # tutti i ruoli
  python analizza_calibrazione_pooled.py def

Il bootstrap ricampiona i GIOCATORI (non le singole partite): due partite dello
stesso giocatore non sono osservazioni indipendenti, e ignorarlo fa sembrare
significativa qualunque differenza.

Non applica nulla: stampa e basta.
"""
import collections
import glob
import json
import os
import random
import re
import sys

LEGHE = ('mls', 'kleague', 'francia', 'inghilterra', 'italia', 'belgio',
         'spagna', 'germania')
COMBO_ATTESE = {'gk': 240, 'def': 168, 'mid': 210, 'fwd': 210}

# (half_life, trend_intensity, range_multiplier) realmente in produzione
PRODUZIONE = {'gk': (6.0, 0.0, 1.15), 'def': (20.0, 0.0, 1.1),
              'mid': (25.0, 0.2, 1.1), 'fwd': (25.0, 0.3, 1.15)}


def carica(ruolo, min_test=3):
    """[(giocatore, {combo: (mae, n_test)})] scartando i file di griglia vecchia."""
    per_giocatore = []
    scartati = 0
    for lega in LEGHE:
        for f in glob.glob(f'formazione_{lega}/output/{lega}_{ruolo}_calibration/'
                           f'grid_search/*_grid.json'):
            try:
                righe = json.load(open(f, encoding='utf-8'))
            except Exception:
                continue
            if not righe:
                continue
            if len(righe) != COMBO_ATTESE[ruolo]:
                scartati += 1
                continue
            d = {}
            for r in righe:
                if r.get('mae') is None or (r.get('n_test') or 0) < min_test:
                    continue
                d[(r['half_life'], r['trend_intensity'], r['range_multiplier'])] = (
                    r['mae'], r['n_test'])
            if d:
                per_giocatore.append((os.path.basename(f)[:-10], lega, d))
    return per_giocatore, scartati


def mae_pesata(campione, combo):
    num = den = 0.0
    for _slug, _lega, d in campione:
        v = d.get(combo)
        if v:
            num += v[0] * v[1]
            den += v[1]
    return (num / den) if den else None


def analizza(ruolo, n_boot=400):
    campione, scartati = carica(ruolo)
    if not campione:
        print(f'[{ruolo}] nessun dato utilizzabile.')
        return
    combos = set()
    for _s, _l, d in campione:
        combos |= set(d)
    classifica = sorted(((mae_pesata(campione, c), c) for c in combos),
                        key=lambda x: (x[0] is None, x[0]))
    migliore_mae, migliore = classifica[0]
    prod = PRODUZIONE[ruolo]
    prod_mae = mae_pesata(campione, prod)
    rank = next((i for i, (_m, c) in enumerate(classifica, 1) if c == prod), None)

    leghe = collections.Counter(l for _s, l, _d in campione)
    print(f'=== {ruolo.upper()} — {len(campione)} giocatori, {len(combos)} combinazioni'
          f'{f", {scartati} file di griglia vecchia esclusi" if scartati else ""}')
    print('    per lega: ' + ', '.join(f'{k} {v}' for k, v in sorted(leghe.items())))
    if prod_mae is None:
        print('    ATTENZIONE: il punto di produzione non e\' nella griglia.')
        return
    print(f'    migliore   {migliore}  MAE {migliore_mae:.4f}')
    print(f'    produzione {prod}  MAE {prod_mae:.4f}  '
          f'rank {rank}/{len(classifica)}  ({(prod_mae/migliore_mae-1)*100:+.2f}%)')

    # Bootstrap sui giocatori. Confrontare il vincitore IN-SAMPLE con la
    # produzione e' viziato: il vincitore e' il minimo di centinaia di
    # combinazioni sugli stessi dati, quindi vince quasi sempre per
    # costruzione (winner's curse). Le due misure oneste sono:
    #  a) STABILITA': quanto spesso quel vincitore resta vincitore;
    #  b) OUT-OF-SAMPLE: si sceglie il vincitore su un ricampionamento e lo si
    #     valuta su quelli ESCLUSI, che e' cio' che accadrebbe applicandolo.
    stabile = 0
    oos_meglio = 0
    oos_validi = 0
    for _ in range(n_boot):
        idx = [random.randrange(len(campione)) for _ in range(len(campione))]
        ric = [campione[i] for i in idx]
        fuori = [campione[i] for i in set(range(len(campione))) - set(idx)]
        vinc = min((c for c in combos if mae_pesata(ric, c) is not None),
                   key=lambda c: mae_pesata(ric, c))
        if vinc == migliore:
            stabile += 1
        if fuori:
            a, b = mae_pesata(fuori, vinc), mae_pesata(fuori, prod)
            if a is not None and b is not None:
                oos_validi += 1
                if a < b:
                    oos_meglio += 1
    print(f'    stabilita del vincitore: resta il migliore nel '
          f'{stabile/n_boot*100:.1f}% dei ricampionamenti')
    if oos_validi:
        q = oos_meglio / oos_validi * 100
        print(f'    out-of-sample: il vincitore scelto altrove batte la produzione '
              f'nel {q:.1f}% dei casi ({oos_validi} validi)')
        if q < 95:
            print("    -> nessuna prova che cambiare migliori: LASCIARE COM'E'.")
        else:
            print('    -> candidato REALE a cambio parametro.')
    print()


if __name__ == '__main__':
    random.seed(1)
    for r in (sys.argv[1:] or ['gk', 'def', 'mid', 'fwd']):
        analizza(r)
