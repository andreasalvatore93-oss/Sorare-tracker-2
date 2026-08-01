"""Si puo' entrare due volte nella STESSA arena?

Da questo dipende se 61 righe dell'archivio erano duplicati da buttare o
ingressi veri da tenere -- cioe' se il ROI e' +22.5% o +13.3%.

Il sospetto: leggendo la classifica si prende la PRIMA riga col nickname
dell'utente. Con due formazioni nella stessa arena le due righe risultano
identiche (stesso rank, stesso punteggio) e sembrano un duplicato.

La prova: contare quante formazioni (contender) puntano alla STESSA classifica.
Se sono due, sono due ingressi veri e li ho cancellati per errore.

Serve il login: gira su Actions.
"""
import collections
import json
import sys

import traccia_arene as t

# giornate dove l'archivio aveva righe doppie
GIORNATE = [
    'football-2-5-aug-2025',
    'football-17-21-oct-2025',
    'football-6-10-mar-2026',
    'football-24-28-apr-2026',
    'football-8-12-may-2026',
]


def main():
    chi = t.graphql('{ currentUser { nickname } }', {})
    nome = ((chi.get('data') or {}).get('currentUser') or {}).get('nickname')
    if not nome:
        print('NON AUTENTICATO')
        return 2
    print(f'autenticato come {nome}\n')

    doppi_totali = 0
    for fx in GIORNATE:
        d = t.graphql(t.Q_INDICE, {'fixture': fx,
                                   'groupType': 'COMPETITION_WITH_ARENA'})
        if d.get('errors'):
            print(f'{fx}: errore {json.dumps(d["errors"])[:90]}')
            continue
        gruppi = (((d.get('data') or {}).get('so5') or {})
                  .get('so5Fixture') or {}).get('so5LeaderboardGroups') or []
        per_classifica = collections.Counter()
        for g in gruppi:
            for c in g.get('mySo5LeaderboardContenders') or []:
                slug = ((c.get('so5Leaderboard') or {}).get('slug')) or ''
                if 'arena' in slug:
                    per_classifica[slug] += 1
        doppi = {s: n for s, n in per_classifica.items() if n > 1}
        doppi_totali += sum(n - 1 for n in doppi.values())
        print(f'{fx:28s} {len(per_classifica):>3} arene | '
              f'{len(doppi):>2} con piu\' di una formazione')
        for s, n in list(doppi.items())[:3]:
            print(f'      {n} formazioni -> ...{s[-45:]}')

    print()
    if doppi_totali:
        print(f'CONFERMATO: {doppi_totali} ingressi in piu\' oltre al primo.')
        print('Erano ingressi veri, non duplicati: la deduplica per')
        print('(giornata, arena) e\' SBAGLIATA e va fatta sul contender.')
    else:
        print('Nessuna arena con due formazioni: erano duplicati veri,')
        print('la deduplica e\' corretta.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
