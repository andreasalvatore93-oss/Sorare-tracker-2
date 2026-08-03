"""
Captain Per Competizione (04/08 notte, richiesta esplicita utente)

LA DOMANDA. Finora la scelta del capitano e' stata giudicata in PUNTI, come
se il premio fosse lineare nel punteggio. Non lo e': si vince arrivando a
un certo PIAZZAMENTO. Con un premio a gradini la varianza ha un valore che
dipende dalla forma della classifica, quindi il capitano migliore potrebbe
NON essere lo stesso in tutte le competizioni.

Nei dati ci sono due mondi molto diversi (verificato):
  - ARENE (Arena/Cap 260/Cap 220/Beginner): campo da 10, rank 1-10.
  - CLASSIFICHE GRANDI (In-Season, All Star, Champion, campionati...):
    decine di migliaia di manager, rank fino a ~59.000.
In una classifica da 60.000 si e' quasi sempre lontani dalla zona premio:
serve la coda alta, quindi la varianza dovrebbe PAGARE. In un'arena da 10
si e' spesso a ridosso della soglia: la varianza dovrebbe contare meno o
essere dannosa. Questo script misura se e' vero.

COME. Per ogni famiglia di competizione si costruisce la curva empirica
punteggio -> piazzamento dalle coppie (punteggio, rank) realmente osservate
in quella famiglia (k-vicini in punteggio, media geometrica dei rank). Poi,
a parita' di 5 carte, si cambia il capitano, si ricalcola il punteggio
totale e si legge il nuovo piazzamento sulla curva.

NESSUNA nuova query: tutto da `backtest_captain_policy` (che a sua volta usa
le cache gia' su disco) e dai piazzamenti reali gia' scaricati.

Uso:  python formazione_mls/diagnostics/captain_per_competizione.py
      (--ricalcola per rifare le previsioni invece di leggere la cache)
"""
import os
import sys
import io
import json
import math
import bisect
import argparse
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene_cache as C
import backtest_arene as B
import backtest_captain_policy as K

CACHE_RISULTATI = os.path.join(
    os.environ.get('TEMP', '.'), 'captain_risultati_cache.json')

# le famiglie con campo da 10 giocatori (rank 1-10): tutto il resto e'
# classifica grande. Riconosciute dal rank massimo osservato, non da una
# lista fissa di nomi -- cosi' una competizione nuova si classifica da sola.
RANK_MAX_ARENA = 12
MIN_N_FAMIGLIA = 120


def _fam(nome):
    """Normalizza il nome della competizione (i trattini sono en-dash)."""
    return (nome or '?').replace('–', '-').replace('—', '-').strip()


def carica_risultati(ricalcola=False):
    if not ricalcola and os.path.isfile(CACHE_RISULTATI):
        with io.open(CACHE_RISULTATI, encoding='utf-8') as fh:
            return json.load(fh)
    cache = C.CacheLocale()
    arene_storico = K.carica('dati_globali/arene_storico.json')['arene']
    fine = B.fine_giornate(arene_storico)
    formazioni = K.raccogli_formazioni()
    risultati = K.calcola_previsioni(cache, fine, formazioni)
    with io.open(CACHE_RISULTATI, 'w', encoding='utf-8') as fh:
        json.dump(risultati, fh)
    return risultati


def filtra(risultati):
    """Tiene solo le righe con piazzamento reale e somma carte coerente col
    punteggio dichiarato (stesso presidio di bilancio_stesse_carte)."""
    buone, scartate = [], defaultdict(int)
    for r in risultati:
        if r.get('rank_reale') is None or r.get('punteggio_reale') is None:
            scartate['senza piazzamento'] += 1
            continue
        if r.get('base_reale') is None or r.get('somma_grezza') is None:
            scartate['carte incomplete'] += 1
            continue
        if abs(r['somma_grezza'] - r['punteggio_reale']) > 0.5:
            scartate['somma carte != punteggio dichiarato'] += 1
            continue
        if any(c.get('dev_std') is None for c in r['candidati']):
            scartate['volatilita non calcolabile'] += 1
            continue
        buone.append(r)
    print(f"Righe utilizzabili: {len(buone)}")
    for causa, n in sorted(scartate.items(), key=lambda kv: -kv[1]):
        print(f"  escluse {n:>5} — {causa}")
    return buone


class CurvaRank(object):
    """Curva empirica punteggio -> piazzamento di una famiglia.

    Non parametrica: per un punteggio si prendono i `k` piu' vicini fra i
    casi realmente osservati e si restituisce la media geometrica dei loro
    rank (geometrica perche' la scala dei piazzamenti e' moltiplicativa:
    da 2000o a 1000o vale come da 200o a 100o)."""

    def __init__(self, coppie, k=None):
        coppie = sorted(coppie)
        self.punteggi = [p for p, _r in coppie]
        self.log_rank = [math.log(max(1, r)) for _p, r in coppie]
        self.n = len(coppie)
        self.k = k or max(15, self.n // 15)
        # somme cumulate: la media su una finestra costa O(1)
        self._cum = [0.0]
        for lr in self.log_rank:
            self._cum.append(self._cum[-1] + lr)

    def log_rank_atteso(self, punteggio):
        i = bisect.bisect_left(self.punteggi, punteggio)
        lo = max(0, min(i - self.k // 2, self.n - self.k))
        hi = min(self.n, lo + self.k)
        return (self._cum[hi] - self._cum[lo]) / (hi - lo)

    def rank_atteso(self, punteggio):
        return math.exp(self.log_rank_atteso(punteggio))


# --- POLICY ---

def policy_baseline(candidati):
    return max(candidati, key=lambda c: c['atteso'])


def make_policy_sd(k):
    """atteso + k*volatilita'. k>0 cerca varianza, k<0 la evita."""
    def policy(candidati):
        return max(candidati, key=lambda c: c['atteso'] + k * (c.get('dev_std') or 0.0))
    return policy


def valuta(righe, curva, policy):
    """Ritorna la lista dei log-rank ottenuti applicando `policy`
    (piu' BASSO = piazzamento migliore)."""
    fuori = []
    for r in righe:
        cap = policy(r['candidati'])
        totale = r['base_reale'] + (K.MOLTIPLICATORE_CAPITANO - 1.0) * cap['reale']
        fuori.append(curva.log_rank_atteso(totale))
    return fuori


def misura_esatta_in_essenze(righe):
    """LA misura senza surrogati, possibile solo sulle arene dell'utente:
    `arene_storico.json` conserva i 10 punteggi VERI del campo e il premio,
    quindi cambiando capitano si ottiene il piazzamento e il premio ESATTI
    (nessuna curva, nessuna interpolazione). Riusa E.piazzamento/E.premio,
    gli stessi gia' usati da bilancio_stesse_carte."""
    import backtest_arene_economia as E

    arene = K.carica('dati_globali/arene_storico.json')['arene']
    per_slug = {}
    for a in arene:
        if a.get('punteggi'):
            per_slug.setdefault(a['slug'], []).append(a)
    premi_tab = E.tabella_premi(arene)

    abbinate = []
    for r in righe:
        slug = r.get('slug_arena')
        if not slug or slug not in per_slug:
            continue
        # ingressi multipli sullo stesso slug: si abbina sul punteggio esatto
        cand = [a for a in per_slug[slug]
                if abs((a.get('mio_score') or -1) - r['punteggio_reale']) < 0.01]
        if len(cand) != 1:
            continue
        abbinate.append((r, cand[0]))

    print("\n" + "=" * 78)
    print("MISURA ESATTA IN ESSENZE — solo arene dell'utente, campo reale da 10")
    print("=" * 78)
    print(f"Arene abbinate al campo reale: {len(abbinate)}")
    if not abbinate:
        return

    def premio_con(policy):
        fuori = []
        for r, a in abbinate:
            cap = policy(r['candidati'])
            tot = r['base_reale'] + (K.MOLTIPLICATORE_CAPITANO - 1.0) * cap['reale']
            rank = E.piazzamento(a, a.get('mio_score'), tot)
            fuori.append(E.premio(a, rank, premi_tab))
        return fuori

    base = premio_con(policy_baseline)
    print(f"baseline (max atteso): {sum(base)} essenze totali, "
          f"{statistics.mean(base):.1f} per arena")

    for k in (-0.60, -0.30, 0.15, 0.30, 0.60, 1.00):
        res = premio_con(make_policy_sd(k))
        diff = [b - a for a, b in zip(base, res)]
        med = statistics.mean(diff)
        ic = B.intervallo_media(diff)
        cambi = sum(1 for d in diff if d != 0)
        marca = '' if ic[0] <= 0 <= ic[1] else ('  <== significativo' if med > 0
                                                else '  <== significativo (PEGGIO)')
        print(f"   atteso {k:+.2f}*volatilita  {sum(res):>7} essenze  "
              f"({med:+.2f}/arena, IC95%=[{ic[0]:+.2f},{ic[1]:+.2f}])  "
              f"premio diverso in {cambi:>3}/{len(abbinate)}{marca}")

    # tetto: capitano scelto con preveggenza sul PREMIO, non sui punti
    def oracolo(candidati):
        return max(candidati, key=lambda c: c['reale'])
    orc = premio_con(oracolo)
    print(f"\n   ORACOLO (max reale)      {sum(orc):>7} essenze  "
          f"({statistics.mean(orc) - statistics.mean(base):+.2f}/arena sul baseline)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ricalcola', action='store_true')
    args = ap.parse_args()

    risultati = carica_risultati(args.ricalcola)
    righe = filtra(risultati)

    per_fam = defaultdict(list)
    for r in righe:
        per_fam[_fam(r.get('competizione'))].append(r)

    famiglie = [(f, v) for f, v in per_fam.items() if len(v) >= MIN_N_FAMIGLIA]
    famiglie.sort(key=lambda fv: -len(fv[1]))

    print(f"\nFamiglie con almeno {MIN_N_FAMIGLIA} formazioni: {len(famiglie)}")

    gruppi = {'ARENA (campo da 10)': [], 'CLASSIFICA GRANDE': []}
    for f, v in famiglie:
        rank_max = max(r['rank_reale'] for r in v)
        chiave = 'ARENA (campo da 10)' if rank_max <= RANK_MAX_ARENA else 'CLASSIFICA GRANDE'
        gruppi[chiave].append((f, v, rank_max))

    ks = (-0.60, -0.30, -0.15, 0.0, 0.15, 0.30, 0.60)

    for nome_gruppo, elenco in gruppi.items():
        if not elenco:
            continue
        print("\n" + "=" * 78)
        print(nome_gruppo)
        print("=" * 78)

        for f, v, rank_max in elenco:
            curva = CurvaRank([(r['punteggio_reale'], r['rank_reale']) for r in v])
            # validazione della curva: quanto sbaglia il rank vero?
            err = [abs(curva.log_rank_atteso(r['punteggio_reale']) - math.log(max(1, r['rank_reale'])))
                   for r in v]
            base = valuta(v, curva, policy_baseline)

            print(f"\n{f}  (n={len(v)}, rank max osservato={rank_max}, "
                  f"errore mediano curva={statistics.median(err):.2f} in log-rank)")
            migliore = None
            for k in ks:
                res = valuta(v, curva, make_policy_sd(k))
                # guadagno = quanto SCENDE il log-rank rispetto al baseline
                diff = [b - a for a, b in zip(res, base)]
                med = statistics.mean(diff)
                ic = B.intervallo_media(diff)
                cambi = sum(1 for a, b in zip(res, base) if abs(a - b) > 1e-9)
                marca = ''
                if not (ic[0] <= 0 <= ic[1]):
                    marca = '  <== significativo' if med > 0 else '  <== significativo (PEGGIO)'
                etichetta = 'baseline (max atteso)' if k == 0 else f'atteso {k:+.2f}*volatilita'
                print(f"   {etichetta:<28} guadagno log-rank={med:+.4f}  "
                      f"IC95%=[{ic[0]:+.4f},{ic[1]:+.4f}]  cambia capitano in {cambi:>4}/{len(v)}{marca}")
                if k != 0 and (migliore is None or med > migliore[1]):
                    migliore = (k, med)
            if migliore:
                print(f"   -> migliore: k={migliore[0]:+.2f} ({migliore[1]:+.4f})")

    misura_esatta_in_essenze(righe)


if __name__ == '__main__':
    main()
