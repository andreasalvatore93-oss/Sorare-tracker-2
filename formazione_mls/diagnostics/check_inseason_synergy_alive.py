"""Verifica (31/07, caso reale Turner/Fofana sollevato dall'utente): le
sinergie/anti-sinergie calibrate il 30/07 sono DAVVERO attive nelle
formazioni In Season prodotte dal tool unificato, o sono codice morto?

Sospetto nato leggendo il codice:
- `build_formazione_globale.py:634` calcola
  `apply_positive_synergy = (tipo not in ('ARENA_ALLSTARS_UNCAPPED',
  'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON') and ...)` -- quindi per le In
  Season MLS/K League e' SEMPRE False, per OGNI formazione (non solo
  dalla 2a in poi).
- `build_formazione_finale.synergy_sort_key` usa `apply_positive_synergy`
  come gate per TRE cose: POSITIVE_SYNERGY_BONUS (riga 413),
  `_cross_team_penalty` (riga 418) e `_same_team_synergy_bonus`
  (riga 425, gate aggiunto il 30/07).

Se il sospetto e' giusto, per le In Season sono inerti sia
IN_SEASON_SYNERGY_BONUS_BY_PAIR (calibrato 30/07 sera con Monte Carlo su
dati reali, ESPRESSAMENTE per le In Season) sia CROSS_TEAM_PENALTY_BY_PAIR
(aggiornato 30/07 pomeriggio: DEF-FWD 3->4, DEF-MID aggiunta).

Metodo: genera le stesse 6 formazioni In Season MLS con i dizionari
attivi (baseline produzione) e poi con i dizionari SVUOTATI. Se le
formazioni sono identiche in tutto e per tutto, i dizionari non hanno
alcun effetto -> codice morto confermato sui dati reali, non solo in
lettura.

Uso: python formazione_mls/diagnostics/check_inseason_synergy_alive.py
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
os.environ.setdefault('IN_SEASON', 'mls:6,kleague:0')
os.environ.setdefault('ONLY_LEAGUES', 'mls')
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))


def genera(svuota_same_team=False, svuota_cross_team=False):
    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff
    saved_same = dict(bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR)
    saved_cross = dict(bff.CROSS_TEAM_PENALTY_BY_PAIR)
    if svuota_same_team:
        bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR = {}
    if svuota_cross_team:
        bff.CROSS_TEAM_PENALTY_BY_PAIR = {}
    try:
        role_data, role_counts, player_names = g.load_league_role_data()
        role_data = g.filter_by_window(role_data)
        pools = g.build_quality_pools(role_data)
        merged = {}
        for role in g.ROLES:
            acc = {}
            for lg in g.LEAGUES:
                acc.update(role_counts.get(lg, {}).get(role, {}))
            merged[role] = acc
        card_pool = bff.CardPool(merged, names=player_names)
        risultati = g.generate_lineups_for_type('MLS_IN_SEASON', 6, role_data, pools, card_pool)
    finally:
        bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR = saved_same
        bff.CROSS_TEAM_PENALTY_BY_PAIR = saved_cross
    out = []
    for r in risultati:
        if 'error' in r:
            out.append(None)
            continue
        out.append(tuple(sorted((slot, row['slug']) for slot, row, _c in r['formazione'])))
    return out


def confronta(nome, a, b):
    diverse = [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if diverse:
        print(f"  {nome}: CAMBIA la selezione nelle formazioni {diverse} -> il dizionario E' ATTIVO")
        for i in diverse:
            print(f"    #{i} baseline      : {[s for _sl, s in a[i-1]]}")
            print(f"    #{i} senza il dict : {[s for _sl, s in b[i-1]]}")
    else:
        print(f"  {nome}: NESSUNA differenza su 6 formazioni -> il dizionario e' INERTE (codice morto)")
    return bool(diverse)


def main():
    print("Genero le 6 In Season MLS -- BASELINE (produzione attuale)...")
    baseline = genera()
    print("Genero le stesse -- SENZA IN_SEASON_SYNERGY_BONUS_BY_PAIR...")
    senza_same = genera(svuota_same_team=True)
    print("Genero le stesse -- SENZA CROSS_TEAM_PENALTY_BY_PAIR...")
    senza_cross = genera(svuota_cross_team=True)

    print("\n" + "=" * 74)
    print("RISULTATO (In Season MLS, 6 formazioni, dati reali su disco)")
    print("=" * 74)
    attivo_same = confronta("IN_SEASON_SYNERGY_BONUS_BY_PAIR (calibrato 30/07 sera)", baseline, senza_same)
    attivo_cross = confronta("CROSS_TEAM_PENALTY_BY_PAIR (aggiornato 30/07 pomeriggio)", baseline, senza_cross)

    print("\n" + "=" * 74)
    if not attivo_same and not attivo_cross:
        print("CONFERMATO: per le In Season entrambe le tabelle sono inerti. La causa e'\n"
              "il gate apply_positive_synergy=False in build_formazione_globale.py:634,\n"
              "che disattiva in blocco bonus same-team, penalita' cross-team e nudge GK-DEF\n"
              "per OGNI formazione In Season (non solo dalla seconda in poi).")
    else:
        print("Almeno una delle due tabelle influenza davvero la selezione: il sospetto\n"
              "di codice morto NON e' confermato, indagare caso per caso.")


if __name__ == '__main__':
    main()
