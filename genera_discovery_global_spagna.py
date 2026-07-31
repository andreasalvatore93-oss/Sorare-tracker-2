"""Genera i 4 discovery_global per la Spagna clonando quelli della Germania.

Gli slug dei club NON sono indovinati: vengono dalla verifica dal vivo della
competizione 'laliga-es' (20 club, `football { competition { clubs } }`),
stessa procedura gia' usata per austria/croazia/germania2/scozia/portogallo/
danimarca/argentina.

Script usa e getta, tenuto nel repo solo come traccia di come sono stati
prodotti i file (e per rifarli se la rosa dei club cambia).
"""
import os
import re

CLUB = [
    'athletic-club-bilbao', 'atletico-madrid-madrid', 'barcelona-barcelona',
    'celta-de-vigo-vigo', 'deportivo-alaves-vitoria-gasteiz',
    'deportivo-la-coruna-a-coruna', 'elche-elche', 'espanyol-barcelona',
    'getafe-getafe-madrid', 'levante-valencia', 'malaga-malaga',
    'osasuna-pamplona-irunea', 'racing-santander-santander',
    'rayo-vallecano-madrid', 'real-betis-sevilla', 'real-madrid-madrid',
    'real-sociedad-donostia-san-sebastian', 'sevilla-sevilla-1890',
    'valencia-valencia', 'villarreal-villarreal',
]


def main():
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        src = f'formazione_germania/discovery/germania_{ruolo}_discovery_global.py'
        dst = f'formazione_spagna/discovery/spagna_{ruolo}_discovery_global.py'
        with open(src, encoding='utf-8', newline='') as f:
            s = f.read()
        nl = '\r\n' if '\r\n' in s else '\n'

        righe = ''.join(f"    '{c}'," + nl for c in CLUB)
        blocco = 'GERMANIA_TEAM_SLUGS = [' + nl + righe + ']'
        nuovo, n = re.subn(r'GERMANIA_TEAM_SLUGS = \[.*?\n\]',
                           lambda _m: blocco, s, count=1, flags=re.S)
        if n != 1:
            raise SystemExit(f"lista club non trovata in {src}")

        nuovo = nuovo.replace('GERMANIA_TEAM_SLUGS', 'SPAGNA_TEAM_SLUGS')
        nuovo = nuovo.replace('germania', 'spagna')
        nuovo = nuovo.replace('Germania', 'Spagna')
        nuovo = nuovo.replace('GERMANIA', 'SPAGNA')
        nuovo = nuovo.replace('Bundesliga', 'LaLiga')
        nuovo = nuovo.replace('bundesliga-de', 'laliga-es')

        with open(dst, 'w', encoding='utf-8', newline='') as f:
            f.write(nuovo)
        print('creato:', dst)


if __name__ == '__main__':
    main()
