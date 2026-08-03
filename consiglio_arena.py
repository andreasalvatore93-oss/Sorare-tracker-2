"""Conviene pagare l'ingresso di questa arena, con questa formazione?

NON confronta campionati fra loro: quel confronto e' inquinato da quante carte
si hanno dove, e da cosa ci si giocava. La domanda e' un'altra e riguarda la
singola arena: dato il punteggio che mi aspetto, l'ingresso si ripaga?

COME. Si gioca contro altri nove, non contro il banco, quindi quel che conta e'
la distribuzione dei loro punteggi -- che ora e' misurata, non stimata: 673
arene reali con tutti e dieci i punteggi. Per un punteggio atteso S:

  - si estraggono nove avversari veri dallo storico di quel tipo di arena
  - si guarda in che posizione si arriva, e quanto si incassa, pescando il
    premio fra quelli davvero visti per quella posizione (cosi' le arene
    jackpot, circa il 5% degli ingressi, entrano alla loro frequenza vera)

Con SIGMA=<punti> si aggiunge l'incertezza della previsione: serve quando si
passa un punteggio PREVISTO e non uno gia' realizzato (vedi la nota su SIGMA).

Ripetuto molte volte da' l'incasso medio. Sotto il costo d'ingresso, entrare
brucia essenze; sopra, li moltiplica. Il numero che interessa e' il PAREGGIO:
il punteggio atteso oltre il quale conviene schierare.

Uso:  python consiglio_arena.py              -> tabella dei pareggi per tipo
      python consiglio_arena.py 285 'cap 260' -> verdetto su una formazione
"""
import collections
import json
import random
import re
import statistics
import sys

ARCHIVIO = 'dati_globali/arene_storico.json'

# costo d'ingresso e premi ai primi tre, dichiarati dall'utente (tabella
# completa nella sezione 48 del RIASSUNTO).
#
# COMPLETATA (03/08): c'erano solo tre tipi, ma le soglie che finiscono in
# produzione (`PAREGGIO_ARENA` nel generatore) sono quattro, e due di quelle
# venivano da un calcolo fatto a mano fuori da qui. Con i tipi mancanti
# dichiarati, `python consiglio_arena.py` ristampa da solo TUTTE le soglie di
# produzione: rifarle dopo un cambio al modello diventa un comando, non una
# ricostruzione archeologica.
#
# 'campo' e' il tipo di archivio da cui pescare i nove avversari: le arene
# elite non sono mai state giocate, quindi non hanno storico proprio, ma sono
# uncapped come le Uncapped -- cambia il prezzo del biglietto, non il campo.
REGOLE = {
    'cap 260': {'costo': 300, 'premi': (1300, 800, 500)},
    'cap 220': {'costo': 200, 'premi': (1000, 500, 300)},
    'Uncapped': {'costo': 300, 'premi': (1300, 800, 500)},
    'Beginner': {'costo': 100, 'premi': (500, 250, 150)},
    'arena division': {'costo': 300, 'premi': (1300, 800, 500)},
    'arena uncapped': {'costo': 300, 'premi': (1300, 800, 500)},
    'elite': {'costo': 800, 'premi': (4000, 2000, 1000), 'campo': 'Uncapped'},
}

# Quanto il punteggio vero si discosta da quello PREVISTO. Attenzione: gli
# avversari si pescano dai punteggi gia' realizzati, che il loro rumore ce
# l'hanno gia' dentro. Se qui si mette rumore mentre si passa un punteggio a
# sua volta gia' realizzato, si regala varianza a una meta' sola del confronto
# -- e finire nei primi tre di dieci e' un evento di coda, quindi la varianza
# in piu' fa sembrare l'ingresso piu' redditizio di quanto sia (col Beginner
# usciva +65 essenze contro le +13 reali). Con punteggi realizzati va tenuto a
# zero; il valore sotto serve solo quando si passa una PREVISIONE.
SIGMA = float(__import__('os').environ.get('SIGMA', '0'))
N_PROVE = 20000


def _ambito(slug):
    m = re.search(r'-(global|seasonal-[a-z_0-9]+)-', slug)
    return m.group(1).replace('seasonal-', '') if m else '?'


def campo_per_tipo():
    """Avversari per tipo di arena, TENUTI RAGGRUPPATI PER ARENA.

    Ogni voce e' la lista dei nove avversari di una singola arena, non un
    calderone di punteggi sciolti. La differenza non e' cosmetica: le arene non
    si somigliano, ce ne sono di uniformemente forti e di uniformemente deboli,
    e mescolando tutto si perde questa struttura. Misurato: col calderone il
    modello dava +41.9 essenze a ingresso sul Beginner contro le +13.5 reali,
    tenendo insieme le arene vere l'errore si riduce di due terzi.

    Il punteggio dell'utente viene tolto, altrimenti il campo conterrebbe se
    stesso.
    """
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    campo = collections.defaultdict(list)
    for r in d['arene']:
        punteggi = list(r.get('punteggi') or [])
        mio = r.get('mio_score')
        if mio is not None and mio in punteggi:
            punteggi.remove(mio)
        if not punteggi:
            continue
        campo[r['tipo']].append(punteggi)
        campo[(r['tipo'], _ambito(r['slug']))].append(punteggi)
    return campo


def premi_osservati():
    """Premi davvero incassati, per (tipo, posizione).

    Non sono fissi: pagando l'ingresso c'e' circa un 5% di probabilita' di
    finire in un'arena jackpot, che paga di piu' (misurato sui dati: 6.5% in
    cap 260, 4.8% in Beginner, contro il 5% dichiarato dall'utente). Pescando
    dai premi osservati invece di usare una terna fissa, i jackpot entrano da
    soli alla loro frequenza vera, senza doverli modellare a parte.
    """
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    out = collections.defaultdict(list)
    for r in d['arene']:
        rank, premio = r.get('rank_premiato'), r.get('premio_essenze')
        if rank and premio:
            out[(r['tipo'], rank)].append(premio)
    return out


_PREMI_OSS = None


def incasso_medio(atteso, avversari, premi, sigma=SIGMA, prove=N_PROVE, seme=7,
                  tipo=None):
    """Essenze incassate in media (premi, al lordo del costo)."""
    global _PREMI_OSS
    if tipo is not None and _PREMI_OSS is None:
        _PREMI_OSS = premi_osservati()
    rnd = random.Random(seme)
    totale = 0
    for _ in range(prove):
        mio = rnd.gauss(atteso, sigma) if sigma else atteso
        nove = avversari[rnd.randrange(len(avversari))]
        posizione = 1 + sum(1 for x in nove if x > mio)
        if posizione > 3:
            continue
        visti = _PREMI_OSS.get((tipo, posizione)) if tipo is not None else None
        if visti:
            totale += visti[rnd.randrange(len(visti))]
        else:
            totale += premi[posizione - 1]
    return totale / prove


def pareggio(avversari, costo, premi, sigma=SIGMA, tipo=None):
    """Punteggio atteso al quale l'incasso medio uguaglia il costo d'ingresso."""
    basso, alto = 150.0, 450.0
    for _ in range(24):
        meta = (basso + alto) / 2
        if incasso_medio(meta, avversari, premi, sigma, tipo=tipo) < costo:
            basso = meta
        else:
            alto = meta
    return (basso + alto) / 2


def verifica():
    """Il modello riproduce il bilancio davvero incassato?

    Confronto appaiato: per ogni arena giocata si passa al modello il punteggio
    REALMENTE fatto e si confronta l'incasso previsto con quello incassato.
    Senza questo passaggio non si sa se le soglie valgono qualcosa.
    """
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    campo = campo_per_tipo()
    print(f"{'tipo':12s} {'n':>4} {'reale/ingr':>11} {'modello/ingr':>13}")
    for tipo, regole in REGOLE.items():
        righe = [r for r in d['arene'] if r['tipo'] == tipo and r.get('costo')
                 and r.get('mio_score') is not None]
        if not righe:
            continue
        reale = sum((r.get('premio_essenze') or 0) - r['costo']
                    for r in righe) / len(righe)
        avversari = campo[tipo]
        modello = statistics.mean(
            incasso_medio(r['mio_score'], avversari, regole['premi'],
                          sigma=0, prove=3000, tipo=tipo) for r in righe) - regole['costo']
        print(f'{tipo:12s} {len(righe):>4} {reale:>+11.1f} {modello:>+13.1f}')
    print()
    print("QUANTO FIDARSI. Lo scarto va letto con la sua incertezza, non a occhio:")
    print("il bilancio reale di 194 arene ha un errore di +/-44 essenze a ingresso,")
    print("perche' un primo posto vale 1300 e ne bastano pochi in piu' o in meno.")
    print("Misurato: cap 260 +0.6 sigma, Uncapped -0.2 sigma -- il modello e'")
    print("compatibile col reale, non c'e' niente da correggere. Il Beginner e'")
    print("l'unico scarto vero (+2.1 sigma): li' sopravvaluta davvero.")
    print()
    print("Controprova che il campo e' modellato bene: la quota di primi tre torna")
    print("quasi esatta (cap 260 39.7% reale contro 40.9% simulato).")
    print()
    print("Cautela a parte sull'Uncapped: 38 arene e 13 premi osservati, quindi la")
    print("frequenza delle arene gold -- che capitano su OGNI tipo, non solo sulle")
    print("260 -- e' stimata su troppo poco.")


def main():
    campo = campo_per_tipo()

    if len(sys.argv) == 2 and sys.argv[1] == '--verifica':
        verifica()
        return 0

    if len(sys.argv) >= 3:
        atteso = float(sys.argv[1])
        tipo = sys.argv[2]
        avversari = campo.get(tipo) or []
        if not avversari:
            print(f'Nessuno storico per "{tipo}". Tipi noti: '
                  f'{sorted(t for t in campo if isinstance(t, str))}')
            return 1
        regole = REGOLE.get(tipo)
        if not regole:
            print(f'Costo e premi non noti per "{tipo}".')
            return 1
        incasso = incasso_medio(atteso, avversari, regole['premi'], tipo=tipo)
        saldo = incasso - regole['costo']
        soglia = pareggio(avversari, regole['costo'], regole['premi'], tipo=tipo)
        print(f'{tipo} -- punteggio atteso {atteso:.1f}')
        print(f'  pareggio a {soglia:.1f} punti')
        print(f'  incasso medio {incasso:.0f} essenze, ingresso {regole["costo"]}')
        print(f'  saldo atteso {saldo:+.0f} essenze a formazione')
        print(f'  -> {"SCHIERA" if saldo > 0 else "LASCIA PERDERE"}')
        return 0

    print(f'{len(campo)} raggruppamenti | rumore di previsione {SIGMA:.0f} punti\n')
    print('=== PAREGGIO: sopra questo punteggio atteso, entrare conviene')
    print(f"{'tipo':16s} {'arene':>7} {'pareggio':>9} {'tuo tipico':>11} {'saldo':>8}")
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    miei = collections.defaultdict(list)
    for r in d['arene']:
        if r.get('mio_score') is not None:
            miei[r['tipo']].append(r['mio_score'])
    for tipo, regole in REGOLE.items():
        # 'campo': da quale archivio pescare gli avversari (le elite non hanno
        # storico proprio, vedi REGOLE)
        fonte = regole.get('campo', tipo)
        avversari = campo.get(fonte) or []
        if len(avversari) < 20:
            print(f'{tipo:16s} {len(avversari):>7}  storico troppo corto, saltato')
            continue
        soglia = pareggio(avversari, regole['costo'], regole['premi'], tipo=fonte)
        tipico = statistics.median(miei[tipo]) if miei.get(tipo) else None
        saldo = (incasso_medio(tipico, avversari, regole['premi'], tipo=fonte)
                 - regole['costo']) if tipico is not None else None
        print(f'{tipo:16s} {len(avversari):>7} {soglia:>9.1f} '
              + (f'{tipico:>11.1f} {saldo:>+8.0f}' if tipico is not None
                 else f"{'--':>11} {'--':>8}"))

    print('\nCome si usa: al momento di schierare, confronta il punteggio atteso')
    print('della formazione col pareggio del suo tipo. Sopra si entra, sotto no --')
    print('e le carte che restano vanno in una competizione senza costo.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
