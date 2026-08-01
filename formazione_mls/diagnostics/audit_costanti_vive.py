"""AUDIT (31/07, richiesta esplicita utente dopo troppi bug di "codice
morto"): per OGNI costante/dizionario di tuning usato dal generatore di
formazioni, verifica EMPIRICAMENTE se influenza davvero l'output.

Metodo: per ogni tipo di formazione, si generano le formazioni con la
configurazione di produzione (baseline), poi di nuovo con la costante
NEUTRALIZZATA (0 o dizionario vuoto). Se le formazioni risultanti sono
identiche -- stessi giocatori negli stessi slot e stesso capitano -- quella
costante non ha alcun effetto su quel tipo: e' codice morto (o inerte per
i dati attuali, distinzione riportata nell'output).

Nessuna modifica alla produzione: tutte le patch sono temporanee e
ripristinate in un finally.

Uso: python formazione_mls/diagnostics/audit_costanti_vive.py [tipo ...]
"""
import os
import sys
import importlib

os.environ.setdefault('ARENA_DEDICATA', '')
os.environ.setdefault('ARENA_ALLSTARS_260', '0')
os.environ.setdefault('ARENA_ALLSTARS_220', '0')
os.environ.setdefault('ARENA_ALLSTARS_UNCAPPED', '0')
os.environ.setdefault('ALLSTARS', '0')
os.environ.setdefault('ALLSTARS_U23', '0')
os.environ.setdefault('IN_SEASON', 'mls:0,kleague:0')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

import build_formazione_globale as g  # noqa: E402

bff = g.bff

# (nome costante, valore neutro). Ogni voce e' un parametro di tuning che
# qualcuno ha calibrato in qualche sessione: se neutralizzarlo non cambia
# nulla, quel lavoro non sta arrivando in produzione.
COSTANTI = [
    ('ANTI_SYNERGY_PENALTY', 0),
    ('POSITIVE_SYNERGY_BONUS', 0),
    ('STACK_GUARD_PENALTY', 0),
    ('MATCH_REUSE_PENALTY', 0),
    ('GK_CAPTAIN_MARGIN', 0),
    ('SAME_TEAM_SYNERGY_BONUS_BY_PAIR', {}),
    ('IN_SEASON_SYNERGY_BONUS_BY_PAIR', {}),
    ('CROSS_TEAM_PENALTY_BY_PAIR', {}),
]

# Tipo -> (quante formazioni, leghe necessarie). Rappresentano i casi reali
# di una run di produzione.
TIPI = [
    ('MLS_IN_SEASON', 6, 'mls'),
    ('KLEAGUE_IN_SEASON', 6, 'kleague'),
    ('ALLSTARS', 4, None),
    ('ALLSTARS_U23', 4, None),
    ('ARENA_ALLSTARS_260', 4, None),
    ('ARENA_ALLSTARS_UNCAPPED', 3, None),
    ('MLS_ARENA', 3, 'mls'),
]

_CACHE = {}


def carica(leghe):
    """role_data/counts/names per un set di leghe, caricati una sola volta."""
    key = leghe or '__all__'
    if key in _CACHE:
        return _CACHE[key]
    if leghe:
        os.environ['ONLY_LEAGUES'] = leghe
    else:
        os.environ.pop('ONLY_LEAGUES', None)
    importlib.reload(g)
    role_data, role_counts, player_names = g.load_league_role_data()
    role_data = g.filter_by_window(role_data)
    merged = {}
    for role in g.ROLES:
        acc = {}
        for lg in g.LEAGUES:
            acc.update(role_counts.get(lg, {}).get(role, {}))
        merged[role] = acc
    _CACHE[key] = (role_data, merged, player_names)
    return _CACHE[key]


def firma(tipo, count, leghe):
    """Genera e ritorna una firma confrontabile: per ogni formazione, gli
    slug per slot piu' il capitano scelto."""
    role_data, merged, names = carica(leghe)
    # Costruzione difensiva (01/08): g.build_quality_pools itera su g.LEAGUES e
    # va in KeyError se role_data non ha quella lega -- succede fuori stagione e
    # quando ONLY_LEAGUES restringe il set. Qui si parte da role_data.
    pools = {lg: {ruolo: g._NoFilterPool(ruolo, lg, roles.get(ruolo, []))
                  for ruolo in g.ROLES}
             for lg, roles in role_data.items()}
    card_pool = g.bff.CardPool(merged, names=names)
    risultati = g.generate_lineups_for_type(tipo, count, role_data, pools, card_pool)
    out = []
    captained = set()
    for r in risultati:
        if 'error' in r:
            out.append(('ERRORE',))
            continue
        f = r['formazione']
        _slot, cap_row, _ct = g.bff.pick_captain(f, captained)
        captained.add(cap_row['slug'])
        out.append(tuple(sorted((s, row['slug']) for s, row, _c in f)) + (('CAP', cap_row['slug']),))
    return tuple(out)


def main():
    tipi_richiesti = sys.argv[1:]
    righe = []
    for tipo, count, leghe in TIPI:
        if tipi_richiesti and tipo not in tipi_richiesti:
            continue
        # Il modulo g viene ricaricato da carica(): le costanti vanno lette e
        # patchate DOPO il reload, sul modulo bff corrente.
        base = firma(tipo, count, leghe)
        bff_cur = g.bff
        for nome, neutro in COSTANTI:
            if not hasattr(bff_cur, nome):
                righe.append((tipo, nome, 'ASSENTE'))
                continue
            salvato = getattr(bff_cur, nome)
            setattr(bff_cur, nome, neutro)
            try:
                variante = firma(tipo, count, leghe)
            finally:
                setattr(bff_cur, nome, salvato)
            stato = 'inerte' if variante == base else 'VIVA'
            righe.append((tipo, nome, stato))
            print(f"  [{tipo}] {nome}: {stato}")

    print("\n" + "=" * 82)
    print("RIEPILOGO — costanti che NON influenzano l'output (candidate a codice morto)")
    print("=" * 82)
    per_costante = {}
    for tipo, nome, stato in righe:
        per_costante.setdefault(nome, []).append((tipo, stato))
    for nome, voci in per_costante.items():
        vive = [t for t, s in voci if s == 'VIVA']
        inerti = [t for t, s in voci if s == 'inerte']
        if not vive:
            print(f"  {nome}: INERTE OVUNQUE ({len(inerti)} tipi testati) <== sospetto codice morto")
        elif inerti:
            print(f"  {nome}: viva su {vive} — inerte su {inerti}")
        else:
            print(f"  {nome}: viva su tutti i tipi testati")


if __name__ == '__main__':
    main()
