"""diagnostica_arene_perse — fra gli scarti si nasconde un'arena sopra soglia?

IL DUBBIO (dell'utente, 02/08). Il generatore costruisce in modo AVIDO: la
formazione migliore possibile, poi la migliore con quello che resta, e cosi'
via. Ogni formazione e' la migliore *dato quello che e' gia' stato consumato*,
ma nessuno garantisce che la PARTIZIONE complessiva sia la migliore.

E il cap L10 peggiora il problema invece di attenuarlo: senza cap l'avido e'
quasi ottimale (i forti vanno prima e basta), ma col cap un giocatore mediocre
con L10 basso puo' valere piu' di uno forte con L10 alto, perche' libera
budget. L'avido non lo vede: ordina per punteggio, non per efficienza.

Due scenari, entrambi plausibili:
  * fra i giocatori delle formazioni SCARTATE esiste una combinazione che
    supera la soglia
  * quei giocatori potenzierebbero una formazione gia' sopra soglia

COSA FA. Riusa il pool vero del generatore (stessi consigli, stesse carte
possedute) e confronta due strategie a parita' di mazzo:

  AVIDA      come fa oggi: massimizza il punteggio di ogni formazione
  PARSIMONIOSA massimizza il NUMERO di formazioni sopra soglia, costruendo
             ogni volta la formazione piu' ECONOMICA che supera comunque la
             soglia, e conservando i giocatori forti per le successive

Se la seconda ne produce di piu', l'avido sta lasciando essenze sul tavolo e
vale la pena passare da "una formazione alla volta" a "ottimizza l'insieme".

Uso:  python diagnostica_arene_perse.py
      python diagnostica_arene_perse.py --tipo ARENA_ALLSTARS_260 --quante 12
"""
import argparse
import importlib.util
import os
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


def _l10_totale(g, formazione, card_pool):
    return sum(card_pool.l10(r['slug']) or 0.0 for _s, r, _c in formazione)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tipo', default='ARENA_ALLSTARS_260')
    ap.add_argument('--quante', type=int, default=14)
    args = ap.parse_args()

    g = _carica_generatore()
    soglia = g.PAREGGIO_ARENA.get(args.tipo)
    if soglia is None:
        print(f'{args.tipo} non e\' un tipo arena.')
        return 1

    role_data, role_counts, names = g.load_league_role_data()
    merged = {}
    for role in g.ROLES:
        acc = {}
        for lg in g.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged[role] = acc
    card_pool = g.bff.CardPool(merged, names=names)
    pools = g.build_quality_pools(role_data)
    shape = g.FORMATION_SHAPES[args.tipo]
    cap = g.L10_CAP_BY_TYPE.get(args.tipo)

    print(f'{args.tipo} | soglia {soglia:.1f} | cap L10 {cap}')
    print(f'{args.quante} formazioni richieste\n')

    risultati = g.generate_lineups_for_type(args.tipo, args.quante,
                                            role_data, pools, card_pool)
    sopra = []
    sotto = []
    for r in risultati:
        if 'error' in r:
            continue
        atteso = g._atteso_con_capitano(r)
        (sopra if atteso >= soglia else sotto).append((atteso, r))

    print(f'AVIDA: {len(sopra)} sopra soglia, {len(sotto)} sotto')
    for a, _r in sorted(sopra, key=lambda x: -x[0]):
        print(f'   sopra  {a:6.1f}')
    for a, _r in sorted(sotto, key=lambda x: -x[0]):
        print(f'   sotto  {a:6.1f}')

    if not sotto:
        print('\nNessuna formazione sotto soglia: niente da recuperare.')
        return 0

    # tutti i giocatori finiti nelle formazioni scartate, per ruolo
    scarti = {}
    for _a, r in sotto:
        for slot, row, _c in r['formazione']:
            ruolo = slot.replace('EXTRA (', '').replace(')', '')
            scarti.setdefault(ruolo, []).append(row)
    print(f'\ngiocatori nelle {len(sotto)} formazioni scartate:')
    for ruolo, v in sorted(scarti.items()):
        v.sort(key=lambda x: -x['atteso'])
        print(f'   {ruolo:4s} {len(v):2d}  migliori: '
              + ', '.join(f"{x['atteso']:.0f}" for x in v[:6]))

    # la migliore formazione possibile con i soli scarti, rispettando il cap
    print('\n--- la MIGLIORE combinazione possibile fra gli scarti ---')
    best = _migliore_da(g, scarti, card_pool, cap, shape)
    if best is None:
        print('   non si riesce a comporre nemmeno una formazione completa.')
    else:
        tot, l10, comp = best
        stato = 'SOPRA SOGLIA' if tot >= soglia else 'sotto soglia'
        print(f'   {tot:.1f} punti (L10 {l10:.1f}/{cap:.0f}) -> {stato}')
        for ruolo, row in comp:
            print(f'      {ruolo:4s} {row["atteso"]:6.1f}  L10 '
                  f'{card_pool.l10(row["slug"]) or 0:5.1f}  {row["slug"]}')
        if tot >= soglia:
            print(f'\n   => l\'avido stava perdendo un\'arena da {tot - soglia:+.1f} '
                  f'sopra il pareggio.')
    return 0


def _migliore_da(g, scarti, card_pool, cap, shape):
    """Miglior punteggio ottenibile dai soli scarti, rispettando il cap L10."""
    import itertools
    ruoli = list(shape['role_slots'])
    extra = shape['extra_roles']
    disponibili = {r: sorted(v, key=lambda x: -x['atteso'])[:8]
                   for r, v in scarti.items()}
    if any(r not in disponibili for r in ruoli):
        return None
    migliore = None
    for combo in itertools.product(*[disponibili[r] for r in ruoli]):
        slugs = {x['slug'] for x in combo}
        if len(slugs) < len(combo):
            continue
        base = sum(x['atteso'] for x in combo)
        l10 = sum(card_pool.l10(x['slug']) or 0.0 for x in combo)
        for re_ in extra:
            for ex in disponibili.get(re_, []):
                if ex['slug'] in slugs:
                    continue
                tot = base + ex['atteso']
                tl10 = l10 + (card_pool.l10(ex['slug']) or 0.0)
                if cap is not None and tl10 > cap:
                    continue
                cap_row = max(list(combo) + [ex], key=lambda x: x['atteso'])
                tot_cap = tot + 0.2 * cap_row['atteso']
                if migliore is None or tot_cap > migliore[0]:
                    migliore = (tot_cap, tl10,
                                list(zip(ruoli, combo)) + [(re_, ex)])
    return migliore


if __name__ == '__main__':
    sys.exit(main())
