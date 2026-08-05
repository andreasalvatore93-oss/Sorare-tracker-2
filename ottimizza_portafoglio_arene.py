"""ottimizza_portafoglio_arene — l'avido lascia essenze sul tavolo?

LA DOMANDA (dell'utente, 02/08). Il generatore costruisce in modo avido: la
formazione migliore, poi la migliore col resto. Il risultato passa quasi tutto
sopra soglia, ma l'obiettivo vero non e' "quante ne passano", e' **quante
essenze producono in totale**.

E siccome il margine paga in modo piu' che proporzionale -- a 280 punti una
formazione rende +40 essenze, a 300 ne rende +182 -- potrebbe convenire
sacrificarne alcune per rinforzare le altre.

C'e' un argomento teorico secondo cui l'avido e' gia' ottimo: con una funzione
di valore CONVESSA conviene la massima disuguaglianza, ed e' proprio quello che
l'avido produce (prende i migliori per la prima formazione, e cosi' via). Ma e'
un argomento, non una misura.

COSA FA. Prende le formazioni generate, calcola le essenze attese totali, e poi
cerca miglioramenti con scambi fra formazioni: prova a spostare un giocatore da
una formazione all'altra (a parita' di ruolo) e tiene lo scambio se il totale
in essenze sale. Se dopo migliaia di tentativi non trova niente, l'avido e'
confermato.

Uso:  python ottimizza_portafoglio_arene.py --tipo ARENA_ALLSTARS_260 --quante 40
"""
import argparse
import importlib.util
import os
import random
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _carica_generatore():
    spec = importlib.util.spec_from_file_location(
        'gen', os.path.join(_ROOT, 'generatore_formazioni',
                            'build_formazione_globale.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules['gen'] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def essenze(g, tipo, atteso):
    """Essenze attese di una formazione: zero se sotto il pareggio (non la
    si gioca, quindi non costa nulla)."""
    soglia = g.PAREGGIO_ARENA.get(tipo)
    if soglia is None:
        return 0.0
    margine = atteso - soglia
    if margine < 0:
        return 0.0
    return margine * g.GUADAGNO_PER_PUNTO.get(tipo, 7.9)  # B05: allineato a cap 260 (05/08)


def totale(g, tipo, formazioni, card_pool):
    return sum(essenze(g, tipo, _atteso(g, f)) for f in formazioni)


def _atteso(g, formazione):
    base = sum(r['atteso'] for _s, r, _c in formazione)
    try:
        _s, cap_row, _t = g.bff.pick_captain(formazione)
        if cap_row is not None:
            base += 0.2 * cap_row.get('atteso', 0)
    except Exception:
        pass
    return base


def _l10(card_pool, formazione):
    return sum(card_pool.l10(r['slug']) or 0.0 for _s, r, _c in formazione)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tipi', default='ARENA_ALLSTARS_260:25,ARENA_ALLSTARS_220:10,'
                                      'ARENA_ALLSTARS_UNCAPPED:8')
    ap.add_argument('--tentativi', type=int, default=60000)
    args = ap.parse_args()

    g = _carica_generatore()
    import io
    import contextlib
    richieste = []
    for pezzo in args.tipi.split(','):
        nome, _, quante = pezzo.partition(':')
        richieste.append((nome.strip(), int(quante or 10)))

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        role_data, role_counts, names = g.load_league_role_data()
        merged = {}
        for role in g.ROLES:
            acc = {}
            for lg in g.LEAGUES:
                acc.update(role_counts.get(lg, {}).get(role, {}))
            merged[role] = acc
        card_pool = g.bff.CardPool(merged, names=names)
        pools = g.build_quality_pools(role_data)
        # stesso ordine della produzione: il pool si consuma tipo per tipo
        voci = []
        for tipo, quante in richieste:
            for r in g.generate_lineups_for_type(tipo, quante, role_data,
                                                 pools, card_pool):
                if 'error' not in r:
                    voci.append([tipo, r['formazione']])

    def ess(v):
        return essenze(g, v[0], _atteso(g, v[1]))

    t0 = sum(ess(v) for v in voci)
    print('PARTENZA (come fa la produzione)\n')
    print(f"{'tipo':30s} {'n':>4s} {'sopra soglia':>13s} {'essenze':>10s}")
    for tipo, _q in richieste:
        gruppo = [v for v in voci if v[0] == tipo]
        sop = sum(1 for v in gruppo if _atteso(g, v[1]) >= g.PAREGGIO_ARENA[tipo])
        print(f'{g.LABELS.get(tipo, tipo):30s} {len(gruppo):4d} {sop:13d} '
              f'{sum(ess(v) for v in gruppo):10,.0f}')
    print(f"{'TOTALE':30s} {len(voci):4d} {'':13s} {t0:10,.0f}\n")

    # ricerca locale, ANCHE fra tipi diversi: una carta con L10 alto rende di
    # piu' in una uncapped, dove non consuma budget
    rnd = random.Random(11)
    acc = 0
    for _ in range(args.tentativi):
        if len(voci) < 2:
            break
        i1, i2 = rnd.randrange(len(voci)), rnd.randrange(len(voci))
        if i1 == i2:
            continue
        t1, f1 = voci[i1]
        t2, f2 = voci[i2]
        a = rnd.randrange(len(f1))
        cand = [b for b in range(len(f2)) if f2[b][0] == f1[a][0]]
        if not cand:
            continue
        b = cand[rnd.randrange(len(cand))]
        n1 = list(f1)
        n2 = list(f2)
        n1[a], n2[b] = f2[b], f1[a]
        c1 = g.L10_CAP_BY_TYPE.get(t1)
        c2 = g.L10_CAP_BY_TYPE.get(t2)
        if c1 is not None and _l10(card_pool, n1) > c1:
            continue
        if c2 is not None and _l10(card_pool, n2) > c2:
            continue
        if len({r['slug'] for _s, r, _c in n1}) < len(n1):
            continue
        if len({r['slug'] for _s, r, _c in n2}) < len(n2):
            continue
        prima = ess([t1, f1]) + ess([t2, f2])
        dopo = ess([t1, n1]) + ess([t2, n2])
        if dopo > prima + 1e-9:
            voci[i1][1], voci[i2][1] = n1, n2
            acc += 1

    t1_tot = sum(ess(v) for v in voci)
    print(f'dopo {args.tentativi} scambi tentati (anche fra tipi diversi):')
    print(f"  accettati: {acc}\n")
    print(f"{'tipo':30s} {'n':>4s} {'sopra soglia':>13s} {'essenze':>10s}")
    for tipo, _q in richieste:
        gruppo = [v for v in voci if v[0] == tipo]
        sop = sum(1 for v in gruppo if _atteso(g, v[1]) >= g.PAREGGIO_ARENA[tipo])
        print(f'{g.LABELS.get(tipo, tipo):30s} {len(gruppo):4d} {sop:13d} '
              f'{sum(ess(v) for v in gruppo):10,.0f}')
    print(f"{'TOTALE':30s} {len(voci):4d} {'':13s} {t1_tot:10,.0f}")
    print(f'\n  guadagno: {t1_tot - t0:+,.0f} essenze ({(t1_tot - t0) / t0 * 100:+.1f}%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
