"""Che bilancio hanno dato le arene, e quanto serve fare per andare a premio.

Legge dati_globali/arene_storico.json (scaricato da ricostruisci_storico_arene.py)
e risponde a due domande:

  1. BILANCIO: quanto e' entrato in essenze contro quanto e' uscito di ingressi.
  2. SOGLIA DEL TERZO: il punteggio del terzo classificato e' il break-even
     vero, perche' il terzo premio supera sempre il costo d'ingresso. Non e'
     un numero fisso — dipende dagli altri nove — quindi si guarda la
     distribuzione: mediana, e quanto spesso il punteggio dell'utente l'ha
     superata.

Le arene di cui non si conosce il costo (formati vecchi, es. arena-division-2)
restano fuori dal bilancio ma dentro le soglie: il campo si misura lo stesso.

Uso:  python analizza_arene.py
"""
import collections
import json
import statistics

ARCHIVIO = 'dati_globali/arene_storico.json'

# premi per posizione, dichiarati dall'utente e confermati dai dati
PREMI = {
    'cap 260': (1300, 800, 500),
    'Uncapped': (1300, 800, 500),
    'cap 220': None,      # premi non confermati
    'Beginner': (500, 300, 150),
}


def main():
    d = json.load(open(ARCHIVIO, encoding='utf-8'))
    arene = d['arene']
    per_tipo = collections.defaultdict(list)
    for r in arene:
        per_tipo[r['tipo']].append(r)

    print(f"{len(arene)} arene su {len({r['fixture'] for r in arene})} giornate\n")

    print('=== BILANCIO (solo arene di cui si conosce il costo)')
    print(f"{'tipo':16s} {'n':>4} {'speso':>8} {'vinto':>8} {'saldo':>9} {'ROI':>8}")
    tot_speso = tot_vinto = 0
    for tipo, righe in sorted(per_tipo.items()):
        con_costo = [r for r in righe if r.get('costo')]
        if not con_costo:
            continue
        speso = sum(r['costo'] for r in con_costo)
        vinto = sum(r.get('premio_essenze') or 0 for r in con_costo)
        tot_speso += speso
        tot_vinto += vinto
        roi = (vinto - speso) / speso * 100 if speso else 0
        print(f'{tipo:16s} {len(con_costo):>4} {speso:>8} {vinto:>8} '
              f'{vinto - speso:>+9} {roi:>7.1f}%')
    roi_tot = (tot_vinto - tot_speso) / tot_speso * 100 if tot_speso else 0
    print(f"{'TOTALE':16s} {'':>4} {tot_speso:>8} {tot_vinto:>8} "
          f'{tot_vinto - tot_speso:>+9} {roi_tot:>7.1f}%')

    print('\n=== SOGLIA DEL TERZO POSTO (il break-even: sopra, si guadagna)')
    print(f"{'tipo':16s} {'n':>4} {'3o tipico':>10} {'tuo tipico':>11} "
          f"{'scarto':>8} {'volte sopra':>12}")
    for tipo, righe in sorted(per_tipo.items()):
        terzi = [r['terzo'] for r in righe if r.get('terzo') is not None]
        miei = [r['mio_score'] for r in righe if r.get('mio_score') is not None]
        if not terzi or not miei:
            continue
        # confronto appaiato: conta solo dove si hanno entrambi i numeri
        coppie = [(r['terzo'], r['mio_score']) for r in righe
                  if r.get('terzo') is not None and r.get('mio_score') is not None]
        sopra = sum(1 for t, m in coppie if m >= t)
        med_terzo = statistics.median(terzi)
        med_mio = statistics.median(miei)
        print(f'{tipo:16s} {len(coppie):>4} {med_terzo:>10.1f} {med_mio:>11.1f} '
              f'{med_mio - med_terzo:>+8.1f} {sopra / len(coppie) * 100:>11.1f}%')

    print('\n=== QUANTO MANCA, IN PUNTI')
    print("Di quanto andrebbe alzato il punteggio medio per arrivare terzo nella")
    print("meta' delle arene (cioe' per portare lo scarto mediano a zero):")
    for tipo, righe in sorted(per_tipo.items()):
        coppie = [(r['terzo'], r['mio_score']) for r in righe
                  if r.get('terzo') is not None and r.get('mio_score') is not None]
        if not coppie:
            continue
        scarti = sorted(m - t for t, m in coppie)
        mediano = statistics.median(scarti)
        verso = 'gia\' sopra' if mediano >= 0 else f'servono +{-mediano:.1f} punti'
        print(f'  {tipo:16s} scarto mediano {mediano:+6.1f} -> {verso}')


if __name__ == '__main__':
    main()
