"""Perche' prima del 2026 non risulta nessuna arena giocata?

Le classifiche arena esistono pubblicamente gia' da luglio 2025, ma
mySo5LeaderboardContenders non ne restituisce nessuna per quel periodo. Due
spiegazioni possibili, con conseguenze opposte:

  A) l'utente non giocava arene prima del 2026 -> il dato e' corretto e basta
  B) Sorare non conserva le formazioni oltre qualche mese -> lo storico e'
     irrecuperabile e va accumulato d'ora in avanti

Si distinguono guardando TUTTE le competizioni, non solo le arene: se anche
In Season e Classic risultano a zero nel 2025 ma pieni nel 2026, allora non e'
una questione di cosa giocava — e' l'API che non le restituisce piu'.

Non scrive niente: si puo' lanciare mentre gira la ricostruzione.
"""
import json
import os

import traccia_arene as t

# una giornata per mese, scelte a campione su tutto il periodo
GIORNATE = [
    'football-25-29-jul-2025',
    'football-26-30-sep-2025',
    'football-28-31-oct-2025',
    'football-26-30-dec-2025',
    'football-28-30-jan-2026',
    'football-27-31-mar-2026',
    'football-24-28-jun-2026',
]

Q = """
query($fixture: String!, $groupType: So5LeaderboardGroupType!) {
  so5 {
    so5Fixture(slug: $fixture) {
      so5LeaderboardGroups(groupType: $groupType) {
        displayName
        so5Leaderboards { slug }
        mySo5LeaderboardContenders { slug so5Leaderboard { slug } }
      }
    }
  }
}
"""


def main():
    chi = t.graphql('{ currentUser { nickname } }', {})
    nome = ((chi.get('data') or {}).get('currentUser') or {}).get('nickname')
    print('autenticato come:', nome or 'NESSUNO -- il resto non vale niente')
    print()
    print(f'{"giornata":28s} {"class.":>7} {"arena":>6} {"mie":>5} {"mie arena":>10}')
    for fx in GIORNATE:
        d = t.graphql(Q, {'fixture': fx, 'groupType': 'COMPETITION_WITH_ARENA'})
        if d.get('errors'):
            print(f'{fx:28s} errore {json.dumps(d["errors"])[:70]}')
            continue
        gruppi = (((d.get('data') or {}).get('so5') or {})
                  .get('so5Fixture') or {}).get('so5LeaderboardGroups') or []
        tot = sum(len(g.get('so5Leaderboards') or []) for g in gruppi)
        arena = sum(1 for g in gruppi for l in (g.get('so5Leaderboards') or [])
                    if 'arena' in (l.get('slug') or ''))
        mie = [c for g in gruppi for c in (g.get('mySo5LeaderboardContenders') or [])]
        mie_arena = [c for c in mie
                     if 'arena' in (((c.get('so5Leaderboard') or {}).get('slug')) or '')]
        print(f'{fx:28s} {tot:>7} {arena:>6} {len(mie):>5} {len(mie_arena):>10}')

    print()
    print('Come leggerlo: se "mie" e\' zero nel 2025 anche fuori dalle arene, allora')
    print('l\'API non restituisce piu\' le formazioni vecchie (ipotesi B) e lo storico')
    print('va accumulato d\'ora in avanti. Se invece "mie" e\' pieno ma "mie arena" e\'')
    print('zero, allora davvero non giocavi arene (ipotesi A) e il dato e\' giusto.')


if __name__ == '__main__':
    main()
