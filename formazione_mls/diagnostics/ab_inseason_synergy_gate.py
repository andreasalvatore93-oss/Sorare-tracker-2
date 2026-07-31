"""A/B (31/07) delle configurazioni possibili del gate sinergie per le In
Season, dopo la scoperta che oggi sono TUTTE inerti (vedi
check_inseason_synergy_alive.py).

Contesto: `build_formazione_globale.py:634` mette apply_positive_synergy=
False per MLS_IN_SEASON/KLEAGUE_IN_SEASON, e quel flag e' il gate UNICO di
tre meccanismi diversi in `synergy_sort_key`:
  (a) nudge GK-DEF (POSITIVE_SYNERGY_BONUS) + anti-sinergia soft MID/FWD
      contro l'avversario del portiere (ANTI_SYNERGY_PENALTY);
  (b) penalita' cross-team (CROSS_TEAM_PENALTY_BY_PAIR, agg. 30/07);
  (c) bonus same-team (IN_SEASON_SYNERGY_BONUS_BY_PAIR, creato 30/07 sera
      con Monte Carlo APPOSTA per le In Season).

L'A/B test del 29/07 che giustifico' la disattivazione misurava (a)+(b):
allora (c) NON esisteva per le In Season (variance_mode era False li').
Quindi (c) non e' mai stato messo alla prova in produzione.

Qui si misura il COSTO in punti attesi totali (con bonus capitano, stessa
metrica su tutti i rami -- lezione 30/07) delle configurazioni possibili.
NOTA sul significato: il punteggio atteso totale NON cattura il beneficio
per cui (c) e' stato calibrato (alzare la probabilita' di superare una
soglia premio fissa, che dipende dalla correlazione e non dalla media).
Questo test misura quindi quanto COSTA riattivare, non quanto RENDE.

Uso: python formazione_mls/diagnostics/ab_inseason_synergy_gate.py
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
os.environ.setdefault('MATCH_WINDOW_DAYS', '7')
os.environ.pop('GITHUB_RUN_NUMBER', None)

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'generatore_formazioni'))

# Configurazioni: (nome, usa_nudge_gk_def, usa_cross_team, usa_same_team)
CONFIGS = [
    ('oggi (tutto spento)',          False, False, False),
    ('solo bonus same-team (c)',     False, False, True),
    ('solo penalita cross-team (b)', False, True,  False),
    ('(b) + (c), nudge spento',      False, True,  True),
    ('tutto acceso (a+b+c)',         True,  True,  True),
]


def patcha_synergy(bff, usa_nudge, usa_cross, usa_same):
    """Sostituisce synergy_sort_key con una versione che IGNORA il flag
    apply_positive_synergy ricevuto e usa invece la configurazione voluta,
    lasciando identico tutto il resto (stack guard, match reuse, sort_score).

    Due dettagli che replicano la configurazione CORRETTA (quella che il
    lavoro del 30/07 intendeva ma che non e' mai arrivata al file vivo):
    - si ignora anche `variance_mode` (nel percorso vivo e' False per le In
      Season, quindi lasciarlo condizionare qui renderebbe il test inutile);
    - si usa esplicitamente IN_SEASON_SYNERGY_BONUS_BY_PAIR, non il default
      SAME_TEAM_SYNERGY_BONUS_BY_PAIR che `_same_team_synergy_bonus`
      prenderebbe con bonus_dict=None (bonus Arena, tarati per un altro
      obiettivo e circa il doppio piu' grandi)."""
    def sort_key(role, row, gk_team_slug, gk_opponent_slug, team_counts=None,
                 apply_stack_guard=False, variance_mode=False, apply_positive_synergy=True,
                 used_matches=None, chosen_roles_by_team=None, synergy_bonus_dict=None):
        adjusted = row.get('sort_score', row['atteso'])
        team_slug = row.get('team_slug')
        if usa_nudge:
            if role in ('MID', 'FWD') and gk_opponent_slug and team_slug == gk_opponent_slug:
                adjusted -= bff.ANTI_SYNERGY_PENALTY
            elif role == 'DEF' and gk_team_slug and team_slug == gk_team_slug:
                adjusted += bff.POSITIVE_SYNERGY_BONUS
        if usa_cross:
            adjusted -= bff._cross_team_penalty(role, row, chosen_roles_by_team)
        if usa_same and team_slug:
            adjusted += bff._same_team_synergy_bonus(
                role, row, chosen_roles_by_team, bff.IN_SEASON_SYNERGY_BONUS_BY_PAIR)
        if (apply_stack_guard and team_slug and team_counts
                and team_counts.get(team_slug, 0) >= bff.IN_SEASON_STACK_LIMIT):
            adjusted -= bff.STACK_GUARD_PENALTY
        if used_matches and bff._match_key(row) in used_matches:
            adjusted -= bff.MATCH_REUSE_PENALTY
        return adjusted

    def adjusted_rows(role, rows, gk_team_slug, gk_opponent_slug, team_counts=None,
                      apply_stack_guard=False, variance_mode=False, apply_positive_synergy=True,
                      used_matches=None, chosen_roles_by_team=None, synergy_bonus_dict=None):
        return sorted(rows, key=lambda row: sort_key(
            role, row, gk_team_slug, gk_opponent_slug, team_counts, apply_stack_guard,
            variance_mode, apply_positive_synergy, used_matches, chosen_roles_by_team,
            synergy_bonus_dict), reverse=True)

    bff.synergy_sort_key = sort_key
    bff.synergy_adjusted_rows = adjusted_rows


def genera(lega, tipo, usa_nudge, usa_cross, usa_same):
    os.environ['ONLY_LEAGUES'] = lega
    os.environ['IN_SEASON'] = f"mls:{6 if lega == 'mls' else 0},kleague:{6 if lega == 'kleague' else 0}"
    import build_formazione_globale as g
    importlib.reload(g)
    bff = g.bff
    patcha_synergy(bff, usa_nudge, usa_cross, usa_same)
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
    risultati = g.generate_lineups_for_type(tipo, 6, role_data, pools, card_pool)

    captained = set()
    totale = 0
    n_ok = 0
    stack_persi = 0
    for r in risultati:
        if 'error' in r:
            continue
        formazione = r['formazione']
        base = sum(row['atteso'] for _s, row, _c in formazione)
        _slot, cap_row, _ct = bff.pick_captain(formazione, captained)
        captained.add(cap_row['slug'])
        totale += base + round(cap_row['atteso'] * 0.5)
        n_ok += 1
        if r.get('stack_perso'):
            stack_persi += 1
    return totale, n_ok, stack_persi


def main():
    for lega, tipo, label in (('mls', 'MLS_IN_SEASON', 'In Season MLS'),
                               ('kleague', 'KLEAGUE_IN_SEASON', 'In Season K League')):
        print(f"\n{'=' * 78}\n{label} — 6 formazioni, totale CON bonus capitano\n{'=' * 78}")
        baseline = None
        for nome, nudge, cross, same in CONFIGS:
            tot, n_ok, stack = genera(lega, tipo, nudge, cross, same)
            if baseline is None:
                baseline = tot
            delta = tot - baseline
            pct = (delta / baseline * 100) if baseline else 0.0
            print(f"  {nome:<30} {tot:>6} pt  ({n_ok}/6 generate, {stack} con stack)  "
                  f"{delta:+5d} pt ({pct:+.2f}%)")


if __name__ == '__main__':
    main()
