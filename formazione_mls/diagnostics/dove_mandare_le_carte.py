"""In Season o Arena 260: dove rende di piu' ogni carta?

Le carte sono il vero vincolo (una carta sta in una formazione sola), quindi la
domanda non e' "quale competizione paga di piu'" ma "quanto rende ogni CARTA
consumata".

REGOLE (dall'utente):
  IN SEASON -- gratis, max 6 formazioni da 5. Scala a gradini, si sale uno alla
    volta e superare NON vale nulla in piu': 340 -> 500 essenze, 360 -> 1000,
    400 -> 25 EUR, 420 -> 100 EUR, 460 -> 500 EUR.
  ARENA cap 260 -- costo 300 essenze, 10 partecipanti, premi 1300/900/500 ai
    primi tre. Illimitate: il tetto e' quante carte hai. Cap 260 sulla somma
    delle L10, quindi NON ci si possono mandare i migliori senza pagarne il
    prezzo in cap.

Il confronto e' in essenze. Il valore in euro dei gradini alti va convertito:
CAMBIO_EUR = quante essenze vale un euro per te (default 40, cioe' 1000 essenze
= 25 EUR, il tasso implicito del gradino 400).

Uso:  python formazione_mls/diagnostics/dove_mandare_le_carte.py
      ATTESO_IS=363 SIGMA=45 GRADINO=400 ATTESO_ARENA=264
"""
import math
import os

CAMBIO_EUR = float(os.environ.get('CAMBIO_EUR', '40'))
GRADINI = {340: 500, 360: 1000, 400: 25 * CAMBIO_EUR,
           420: 100 * CAMBIO_EUR, 460: 500 * CAMBIO_EUR}
COSTO_ARENA = 300.0
PREMI_ARENA = (1300.0, 900.0, 500.0)


def p_sopra(atteso, sigma, soglia):
    if sigma <= 0:
        return 1.0 if atteso > soglia else 0.0
    return 0.5 * math.erfc(((soglia - atteso) / sigma) / math.sqrt(2))


def valore_arena(atteso, sigma, media_campo):
    """Valore atteso di UNA arena, in essenze, al netto del costo.
    Approssimazione: i 9 rivali sono estrazioni indipendenti dalla stessa
    distribuzione centrata su media_campo."""
    passi = 400
    lo, hi = atteso - 4 * sigma, atteso + 4 * sigma
    dx = (hi - lo) / passi
    ev = 0.0
    for i in range(passi):
        x = lo + (i + 0.5) * dx
        dens = math.exp(-0.5 * ((x - atteso) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        p_batto = 1.0 - p_sopra(media_campo, sigma, x)   # P(un rivale < x)
        # posizione = quanti rivali mi superano, binomiale(9, 1-p_batto)
        q = 1.0 - p_batto
        for k, premio in enumerate(PREMI_ARENA):
            comb = math.comb(9, k)
            ev += dens * dx * comb * (q ** k) * (p_batto ** (9 - k)) * premio
    return ev - COSTO_ARENA


def main():
    att_is = float(os.environ.get('ATTESO_IS', '363'))
    sigma = float(os.environ.get('SIGMA', '45'))
    gradino = int(os.environ.get('GRADINO', '400'))
    att_arena = float(os.environ.get('ATTESO_ARENA', '264'))
    media_campo = float(os.environ.get('MEDIA_CAMPO', '259'))

    print(f'In Season: atteso {att_is:.0f}, gradino {gradino} '
          f'({GRADINI[gradino]:.0f} essenze equivalenti)')
    print(f'Arena 260: atteso {att_arena:.0f} contro un campo da {media_campo:.0f}, '
          f'costo {COSTO_ARENA:.0f}\n')

    p = p_sopra(att_is, sigma, gradino)
    v_is = p * GRADINI[gradino]
    print(f'  IN SEASON: P(gradino) {p:.1%} -> {v_is:.0f} essenze attese '
          f'per formazione = {v_is / 5:.0f} per carta')

    v_ar = valore_arena(att_arena, sigma, media_campo)
    print(f'  ARENA 260: {v_ar:+.0f} essenze attese per formazione '
          f'= {v_ar / 5:+.0f} per carta')

    print()
    if v_is > v_ar:
        print(f'  -> le carte rendono di piu\' in IN SEASON '
              f'({v_is / 5:.0f} contro {v_ar / 5:+.0f} per carta)')
    else:
        print(f'  -> le carte rendono di piu\' in ARENA '
              f'({v_ar / 5:+.0f} contro {v_is / 5:.0f} per carta)')

    print('\n  IN SEASON, valore per carta a seconda del gradino tentato:')
    for g, premio in sorted(GRADINI.items()):
        pg = p_sopra(att_is, sigma, g)
        print(f'    {g:>4} pt: P {pg:5.1%} x {premio:>6.0f} = {pg * premio / 5:6.0f} per carta')

    print('\n  ARENA, valore per carta al variare del vantaggio sul campo:')
    for v in (0, 5, 10, 20, 30, 40):
        print(f'    +{v:>2} pt: {valore_arena(media_campo + v, sigma, media_campo) / 5:+6.0f} per carta')


if __name__ == '__main__':
    main()
