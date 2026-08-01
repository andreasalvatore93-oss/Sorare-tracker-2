"""Quante arene schierare, e con quali carte, per massimizzare le essenze.

Il ROI di un'arena dipende SOLO da quanto la formazione e' sopra il campo. Ma
le carte buone finiscono: la prima arena la riempi con i tuoi 5 migliori, la
decima con quello che resta. Il vantaggio scende arena dopo arena, e a un certo
punto diventa negativo -- da li' in poi ogni ingresso brucia essenze.

Questo strumento trova QUANTE arene conviene schierare, dato:
  - quante carte utilizzabili hai,
  - quanto sono forti (la loro distribuzione),
  - il cap sulla L10 (260/220) o l'assenza di cap.

E confronta l'allocazione CONCENTRATA (le migliori insieme, come fa oggi il
generatore) con quella DISTRIBUITA.

Uso:  python formazione_mls/diagnostics/ottimizza_portafoglio_arene.py
      N_CARTE=60 CAP=260 COSTO=300
"""
import collections
import glob
import json
import math
import os
import random
import statistics

N_CARTE = int(os.environ.get('N_CARTE', '60'))
CAP = float(os.environ.get('CAP', '260'))       # 0 = uncapped
COSTO = float(os.environ.get('COSTO', '300'))
PREMI = [float(x) for x in os.environ.get('PREMI', '1300,900,500').split(',')]
SLOT = 5
N_TRIALS = int(os.environ.get('N_TRIALS', '3000'))
# Il campo NON e' fatto delle tue stesse formazioni: dai dati reali
# dell'utente (673 ingressi, top3 34.92%) il vantaggio della PRIMA arena e'
# +6.7 pt. Il campo si tara di conseguenza, altrimenti si assume per
# costruzione un vantaggio nullo e tutte le arene sembrano in perdita.
VANTAGGIO_PRIMA = float(os.environ.get('VANTAGGIO_PRIMA', '6.7'))


def carica():
    """slug -> (media storica, l10 stimata, [punteggi per data])"""
    per_slug = collections.defaultdict(list)
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for v in d.values():
            if not isinstance(v, dict) or v.get('scoreStatus') != 'FINAL':
                continue
            data = ((v.get('anyGame') or {}).get('date') or '')[:10]
            if data and v.get('score') is not None:
                per_slug[slug].append((data, v['score']))
    out = {}
    for s, v in per_slug.items():
        if len(v) < 10:
            continue
        punteggi = [x[1] for x in v]
        # l10 = media delle ultime 10, come il vincolo Sorare
        l10 = statistics.mean(punteggi[-10:])
        out[s] = (statistics.mean(punteggi), l10, dict(v))
    return out


def componi(rosa, cap):
    """Formazioni da 5 costruite in ordine di forza, rispettando il cap L10.
    Ritorna la lista di formazioni (liste di slug)."""
    disponibili = sorted(rosa, key=lambda s: -rosa[s][0]) if isinstance(rosa, dict) else list(rosa)
    return disponibili


def main():
    dati = carica()
    if len(dati) < N_CARTE:
        print(f'solo {len(dati)} giocatori con storico sufficiente')
        return
    date = sorted({d for _m, _l, per_data in dati.values() for d in per_data})
    print(f'{len(dati)} giocatori disponibili, {len(date)} giornate | '
          f'cap {CAP if CAP else "nessuno"} | costo {COSTO:.0f}')

    random.seed(17)
    # indice giornata -> giocatori che hanno giocato quel giorno (senza questo
    # si pretendeva che 5 carte a caso avessero tutte giocato la stessa data:
    # praticamente mai)
    per_data = collections.defaultdict(list)
    for s, (_m, _l, pd) in dati.items():
        for d in pd:
            per_data[d].append(s)
    date_utili = [d for d, v in per_data.items() if len(v) >= N_CARTE]
    if not date_utili:
        print('nessuna giornata con abbastanza giocatori')
        return
    risultati = collections.defaultdict(list)
    for _ in range(N_TRIALS):
        data = random.choice(date_utili)
        rosa = random.sample(per_data[data], N_CARTE)
        # SOTTO IL CAP la valuta non e' il punteggio ma il punteggio PER UNITA'
        # di L10: prendendo i migliori in assoluto si sfora subito e non si
        # compone nemmeno una formazione (verificato: 0 formazioni da 60 carte).
        if CAP:
            rosa.sort(key=lambda s: -(dati[s][0] / max(dati[s][1], 1.0)))
        else:
            rosa.sort(key=lambda s: -dati[s][0])

        formazioni, correnti, cap_corrente = [], [], 0.0
        for s in rosa:
            l10 = dati[s][1]
            if CAP and len(correnti) < SLOT:
                # deve restare spazio per gli slot mancanti al minimo possibile
                if cap_corrente + l10 > CAP:
                    continue
            correnti.append(s)
            cap_corrente += l10
            if len(correnti) == SLOT:
                formazioni.append(correnti)
                correnti, cap_corrente = [], 0.0
        for i, f in enumerate(formazioni):
            reali = [dati[s][2].get(data) for s in f]
            if any(x is None for x in reali):
                continue
            risultati[i].append(sum(reali))

    # campo di riferimento: formazione media di mercato sotto lo stesso cap
    tutte = [x for v in risultati.values() for x in v]
    if not tutte:
        print('nessuna formazione simulabile')
        return
    sigma = statistics.pstdev(tutte)
    prima = statistics.mean(risultati[0]) if risultati.get(0) else statistics.mean(tutte)
    media_campo = prima - VANTAGGIO_PRIMA

    def ev(vantaggio):
        def pnorm(z):
            return 0.5 * math.erfc(-z / math.sqrt(2))
        tot, passi = 0.0, 300
        lo, hi = vantaggio - 4 * sigma, vantaggio + 4 * sigma
        dx = (hi - lo) / passi
        for i in range(passi):
            x = lo + (i + 0.5) * dx
            d = math.exp(-0.5 * ((x - vantaggio) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
            pb = pnorm(x / sigma)
            q = 1 - pb
            tot += d * dx * sum(math.comb(9, k) * q ** k * pb ** (9 - k) * PREMI[k]
                                for k in range(len(PREMI)))
        return tot - COSTO

    print(f'\ncampo di riferimento: {media_campo:.0f} pt (dev.std {sigma:.0f})\n')
    print(f'{"arena":>6} {"media":>7} {"vantaggio":>10} {"valore atteso":>14} {"cumulato":>10}')
    cum = 0.0
    ultima_buona = 0
    for i in sorted(risultati):
        if len(risultati[i]) < 50:
            break
        m = statistics.mean(risultati[i])
        v = m - media_campo
        e = ev(v)
        cum += e
        if e > 0:
            ultima_buona = i + 1
        print(f'{i+1:>6} {m:7.0f} {v:+10.1f} {e:+14.0f} {cum:+10.0f}')
    print(f'\n  conviene schierare le prime {ultima_buona} arene; '
          f'dalla {ultima_buona+1} in poi ogni ingresso perde essenze.')


if __name__ == '__main__':
    main()
