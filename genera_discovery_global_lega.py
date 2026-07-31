"""Genera i 4 discovery_global di una lega clonando quelli della Germania.

Generalizzazione di genera_discovery_global_spagna.py (31/07): stessa
procedura, ma la lista dei club e lo slug competizione stanno in una tabella
invece che nel corpo dello script, cosi' aggiungere una lega e' una voce in
piu' in LEGHE.

Gli slug dei club NON sono indovinati: vengono dalla verifica dal vivo della
competizione con la query pubblica
`football { competition(slug: ...) { clubs(first: 50) { nodes { slug name } } } }`.
Ligue 1 / Premier League / Serie A / First Division A verificate il 31/07.

Uso:  python genera_discovery_global_lega.py francia inghilterra italia belgio
      python genera_discovery_global_lega.py            # tutte quelle in tabella
"""
import re
import sys

# lega -> (slug competizione, nome leggibile del campionato, club verificati dal vivo)
LEGHE = {
    'francia': ('ligue-1-fr', 'Ligue 1', [
        'angers-sco-angers', 'auxerre-auxerre', 'brest-brest',
        'le-havre-harfleur', 'le-mans-le-mans', 'lens-avion',
        'lille-villeneuve-d-ascq', 'lorient-ploemeur', 'monaco-monaco',
        'nice-nice', 'olympique-lyonnais-lyon',
        'olympique-marseille-marseille', 'psg-paris', 'paris-paris',
        'rennes-rennes', 'strasbourg-strasbourg', 'toulouse-toulouse',
        'troyes-troyes',
    ]),
    'inghilterra': ('premier-league-gb-eng', 'Premier League', [
        'afc-bournemouth-bournemouth-dorset', 'arsenal-london',
        'aston-villa-birmingham', 'brentford-brentford-middlesex',
        'brighton-hove-albion-brighton-east-sussex', 'chelsea-london',
        'coventry-city-coventry', 'crystal-palace-london',
        'everton-liverpool', 'fulham-london', 'hull-city-hull',
        'ipswich-town-ipswich-suffolk', 'leeds-united-leeds-west-yorkshire',
        'liverpool-liverpool', 'manchester-city-manchester',
        'manchester-united-manchester', 'newcastle-united-newcastle-upon-tyne',
        'nottingham-forest-nottingham', 'sunderland-sunderland',
        'tottenham-hotspur-london',
    ]),
    'italia': ('serie-a-it', 'Serie A', [
        'atalanta-ciserano', 'bologna-bologna', 'cagliari-cagliari',
        'como-como', 'cremonese-cremona', 'fiorentina-firenze',
        'genoa-genova', 'hellas-verona-verona', 'internazionale-milano',
        'juventus-torino', 'lazio-formello', 'lecce-lecce', 'milan-milano',
        'napoli-castel-volturno', 'parma-parma', 'pisa-pisa', 'roma-roma',
        'sassuolo-sassuolo', 'torino-torino', 'udinese-udine',
    ]),
    'belgio': ('jupiler-pro-league', 'First Division A', [
        'anderlecht-bruxelles-brussel', 'antwerp-deurne',
        'cercle-brugge-brugge', 'club-brugge-brugge', 'genk-genk',
        'gent-gent', 'kortrijk-kortrijk', 'la-louviere-la-louviere',
        'lommel-lommel', 'mechelen-mechelen-malines', 'oh-leuven-heverlee',
        'sint-truiden-sint-truiden-st-trond', 'sporting-charleroi-charleroi',
        'standard-liege-liege-luik',
        'union-saint-gilloise-bruxelles-brussels',
        'waasland-beveren-beveren-waas', 'westerlo-westerlo',
        'zulte-waregem-waregem',
    ]),
}


def genera(lega, comp_slug, comp_nome, club):
    n = len(club)
    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        src = f'formazione_germania/discovery/germania_{ruolo}_discovery_global.py'
        dst = f'formazione_{lega}/discovery/{lega}_{ruolo}_discovery_global.py'
        with open(src, encoding='utf-8', newline='') as f:
            s = f.read()
        nl = '\r\n' if '\r\n' in s else '\n'

        righe = ''.join(f"    '{c}'," + nl for c in club)
        blocco = 'GERMANIA_TEAM_SLUGS = [' + nl + righe + ']'
        nuovo, k = re.subn(r'GERMANIA_TEAM_SLUGS = \[.*?\n\]',
                           lambda _m: blocco, s, count=1, flags=re.S)
        if k != 1:
            raise SystemExit(f"lista club non trovata in {src}")

        # Il numero di squadre e la provenienza degli slug vivono solo nel
        # docstring/commento (verificato: nessun "18" nel codice), quindi le
        # sostituzioni testuali qui sotto sono sicure.
        nuovo = nuovo.replace(
            'verify_bundesliga_clubs.yml, run 30455180403)',
            'verifica dal vivo 31/07)')
        nuovo = nuovo.replace('(workflow' + nl, '(')
        nuovo = nuovo.replace('18/18', f'{n}/{n}')
        nuovo = re.sub(r'\b18\b', str(n), nuovo)
        # Solo le due date che parlano della PROVENIENZA degli slug: quella del
        # filtro qualita' e' un'altra cosa e deve restare com'e'.
        nuovo = nuovo.replace('ottenuti dal vivo (29/07)', 'ottenuti dal vivo (31/07)')
        nuovo = nuovo.replace('.clubs, 29/07)', '.clubs, 31/07)')

        nuovo = nuovo.replace('GERMANIA_TEAM_SLUGS', f'{lega.upper()}_TEAM_SLUGS')
        nuovo = nuovo.replace('germania', lega)
        nuovo = nuovo.replace('Germania', lega.capitalize())
        nuovo = nuovo.replace('GERMANIA', lega.upper())
        nuovo = nuovo.replace('Bundesliga', comp_nome)
        nuovo = nuovo.replace('bundesliga-de', comp_slug)

        with open(dst, 'w', encoding='utf-8', newline='') as f:
            f.write(nuovo)
        print(f'creato: {dst}  ({n} club)')


def main():
    leghe = sys.argv[1:] or list(LEGHE)
    for lega in leghe:
        if lega not in LEGHE:
            raise SystemExit(f"lega sconosciuta: {lega} (note: {', '.join(LEGHE)})")
        comp_slug, comp_nome, club = LEGHE[lega]
        genera(lega, comp_slug, comp_nome, club)


if __name__ == '__main__':
    main()
