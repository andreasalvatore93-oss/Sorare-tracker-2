"""Dato il target da superare, conviene alzare o abbassare la varianza?

REGOLE (dall'utente, 01/08):

IN SEASON -- scala a gradini, si sale UNO alla volta e superare non vale nulla
in piu':
    340 -> 500 essenze | 360 -> 1000 essenze | 400 -> 25 EUR
    420 -> 100 EUR     | 460 -> 500 EUR
Se giochi per 400 e fai 460, prendi comunque 25 EUR. L'obiettivo e' quindi
P(totale >= gradino), non il punteggio atteso.

ARENA -- 10 partecipanti, costo 300 (cap 260) o 200 (cap 220), premi ai primi
tre. Qui il bersaglio non e' fisso: e' battere 7, 8 o 9 avversari.

CONSEGUENZA, ed e' il punto: la varianza NON e' sempre amica.
  - atteso SOTTO il target -> solo la coda ci arriva: alzare la varianza.
  - atteso SOPRA il target -> si e' gia' dentro: la varianza fa solo scendere.
Il punto di svolta e' esattamente il target.

Uso:  python formazione_mls/diagnostics/strategia_per_target.py
      ATTESO=363 SIGMA=45 TARGET=400
"""
import math
import os

GRADINI_IN_SEASON = [(340, '500 essenze'), (360, '1000 essenze'), (400, '25 EUR'),
                     (420, '100 EUR'), (460, '500 EUR')]


def p_sopra(atteso, sigma, soglia):
    if sigma <= 0:
        return 1.0 if atteso > soglia else 0.0
    z = (soglia - atteso) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def main():
    atteso = float(os.environ.get('ATTESO', '363'))
    sigma = float(os.environ.get('SIGMA', '45'))
    target = float(os.environ.get('TARGET', '400'))

    print(f'formazione: atteso {atteso:.0f} pt, dev.std {sigma:.0f}\n')
    print('IN SEASON -- probabilita di superare ogni gradino')
    for soglia, premio in GRADINI_IN_SEASON:
        p = p_sopra(atteso, sigma, soglia)
        marca = '  <== il tuo gradino' if abs(soglia - target) < 1 else ''
        print(f'  {soglia:>4} pt ({premio:>12}): {p:5.1%}{marca}')

    print(f'\nEFFETTO DELLA VARIANZA sul gradino {target:.0f}')
    print(f'{"sigma":>7} {"P(>=target)":>12}')
    for s in (sigma * 0.7, sigma * 0.85, sigma, sigma * 1.15, sigma * 1.3):
        print(f'{s:7.0f} {p_sopra(atteso, s, target):12.1%}')

    if atteso < target:
        margine = target - atteso
        print(f'\n  Sei SOTTO il gradino di {margine:.0f} pt: la varianza AIUTA.')
        print('  Stack, blocco GK+DEF e giocatori esplosivi vanno accesi.')
    else:
        print(f'\n  Sei SOPRA il gradino di {atteso - target:.0f} pt: la varianza DANNEGGIA.')
        print('  Conviene la formazione piu regolare, non la piu alta.')

    # quanto punteggio atteso vale un punto di sigma, sul gradino corrente
    d_att = p_sopra(atteso + 1, sigma, target) - p_sopra(atteso, sigma, target)
    d_sig = p_sopra(atteso, sigma + 1, target) - p_sopra(atteso, sigma, target)
    if d_att:
        print(f'\n  1 pt di dev.std vale {d_sig / d_att:+.2f} pt di punteggio atteso '
              f'su questo gradino.')


if __name__ == '__main__':
    main()
