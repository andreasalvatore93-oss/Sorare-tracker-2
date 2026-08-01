"""A parita' di carte, l'allocazione fra le formazioni era la migliore possibile?

Questa misura NON usa il modello predittivo, e per questo e' utile prima di
tutto il resto: separa due domande che altrimenti si confondono.

  1. ho scelto i giocatori giusti?          (dipende dalla previsione)
  2. li ho distribuiti bene fra le arene?   (non dipende dalla previsione)

Qui si risponde solo alla seconda, e col senno di poi: prendendo esattamente
le carte schierate in una giornata e i punteggi che hanno DAVVERO fatto, si
riordinano fra le stesse arene per massimizzare il numero di piazzamenti a
premio. La distanza fra quel massimo e il risultato vero e' il guadagno che
era disponibile senza indovinare niente -- solo distribuendo meglio.

E' un tetto, non una previsione: al momento di schierare i punteggi non si
conoscono. Ma se il tetto e' basso, sull'allocazione non c'e' niente da
guadagnare e il modello va giudicato solo sulla selezione.

Uso:  python analizza_allocazione_reale.py
"""
import collections
import json
import statistics

STORICO = 'dati_globali/arene_storico.json'
FORMAZIONI = 'dati_globali/arene_formazioni.json'


def main():
    arene = json.load(open(STORICO, encoding='utf-8'))['arene']
    form = json.load(open(FORMAZIONI, encoding='utf-8'))['formazioni']
    per_slug = {r['contender_slug']: r for r in arene if r.get('contender_slug')}

    # giornate con almeno due arene dello stesso tipo: solo li' ha senso
    # chiedersi se le carte erano distribuite bene, perche' solo li' si
    # possono scambiare fra formazioni confrontabili
    gruppi = collections.defaultdict(list)
    for cs, f in form.items():
        r = per_slug.get(cs)
        if not r or not r.get('punteggi'):
            continue
        gruppi[(f['fixture'], f['tipo'])].append((f, r))

    tot_vero = tot_max = tot_arene = 0
    dettaglio = []
    for (fx, tipo), voci in gruppi.items():
        if len(voci) < 2:
            continue
        # tutti i giocatori usati quella giornata in quel tipo, col punteggio vero
        carte = []
        for f, _r in voci:
            for g in f['giocatori']:
                if g.get('punteggio') is not None:
                    carte.append(g['punteggio'])
        if len(carte) < len(voci) * 5:
            continue
        soglie = [r['terzo'] for _f, r in voci if r.get('terzo') is not None]
        if len(soglie) != len(voci):
            continue

        vero = sum(1 for _f, r in voci
                   if r.get('mio_rank') is not None and r['mio_rank'] <= 3)

        # riordino ottimo col senno di poi: le formazioni si costruiscono
        # concentrando i migliori, e si affrontano le soglie piu' basse
        carte.sort(reverse=True)
        squadre = [sum(carte[i * 5:(i + 1) * 5]) for i in range(len(voci))]
        squadre.sort(reverse=True)
        soglie.sort()
        massimo = sum(1 for s, t in zip(squadre, soglie) if s >= t)

        tot_vero += vero
        tot_max += massimo
        tot_arene += len(voci)
        dettaglio.append((massimo - vero, fx, tipo, len(voci), vero, massimo))

    if not tot_arene:
        print('Non ci sono giornate con abbastanza formazioni confrontabili.')
        return

    print(f'{len(dettaglio)} giornate confrontabili | {tot_arene} arene\n')
    print(f'  a premio davvero      {tot_vero:>4}  ({tot_vero / tot_arene * 100:.1f}%)')
    print(f'  a premio riordinando  {tot_max:>4}  ({tot_max / tot_arene * 100:.1f}%)')
    print(f'  differenza            {tot_max - tot_vero:>+4}')
    print()
    print('Il secondo numero e\' un TETTO col senno di poi: si conoscono sia i')
    print('punteggi sia le soglie. Nessun modello puo\' raggiungerlo. Serve a')
    print('sapere quanto spazio esiste sull\'allocazione, prima di attribuirlo')
    print('alla selezione dei giocatori.')

    dettaglio.sort(reverse=True)
    print('\nGiornate dove si perdeva di piu\':')
    for d, fx, tipo, n, vero, mx in dettaglio[:8]:
        if d <= 0:
            break
        print(f'  {fx:26s} {tipo:14s} {n:>2} arene: {vero} -> {mx}  ({d:+d})')


if __name__ == '__main__':
    main()
