"""
Allocazione a PREMIO ATTESO (04/08 notte) — la prima leva con la forma giusta

DA DOVE NASCE. Con il mazzo fisso la somma dei punti e' conservata: spostare
carte fra arene non ne crea uno. L'unica cosa che la riallocazione puo'
migliorare e' il PREMIO, perche' il premio non e' lineare nel punteggio
(vedi selezione_carte.py). Quindi il bot, che oggi alloca massimizzando i
PUNTI attesi, sta ottimizzando la cosa sbagliata.

COSA FA QUESTO SCRIPT. Sostituisce l'obiettivo: invece di massimizzare la
somma dei punti attesi, massimizza la somma dei PREMI ATTESI in essenze.

Per stimare il premio atteso di una formazione in un'arena serve la
probabilita' di ogni piazzamento, quindi la forza degli avversari:
  - il campo e' di 10, quindi 9 avversari;
  - la distribuzione dei loro punteggi si stima dalle arene dello STESSO
    TIPO gia' concluse PRIMA di quella giornata (walk-forward stretto: mai
    un punteggio del futuro, tantomeno quelli veri di quell'arena);
  - dato il mio punteggio s, il numero di avversari sopra di me e'
    binomiale con p = 1 - F(s), quindi
        P(rank = k) = C(9,k-1) (1-F(s))^(k-1) F(s)^(10-k)
    e non serve simulare il campo;
  - il mio punteggio non e' certo: si integra su s ~ Normale(atteso, sigma),
    con sigma stimato dallo scarto storico fra totale reale e totale atteso.

Il confronto e' con le stesse politiche di selezione_carte.py, sulle stesse
arene, in essenze vere.

NESSUNA nuova query.

Uso: python formazione_mls/diagnostics/allocazione_premio_atteso.py
"""
import os
import sys
import math
import random
import bisect
import argparse
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene as B
import backtest_arene_economia as E
import backtest_captain_policy as K
import captain_per_competizione as CP
import headroom_decisioni as H

SEME = 90210
AVVERSARI = 9
MIN_CAMPIONE_AVVERSARI = 120
# nodi e pesi per integrare su s ~ Normale(0,1): 7 punti equispaziati a
# +-2.5 sigma, pesi gaussiani normalizzati. Basta: la funzione premio e' a
# gradini larghi, non serve una quadratura fine.
_NODI = [-2.5, -1.667, -0.833, 0.0, 0.833, 1.667, 2.5]
_PESI = [math.exp(-0.5 * z * z) for z in _NODI]
_PESI = [w / sum(_PESI) for w in _PESI]


def _binomiali(n):
    """Coefficienti binomiali C(n,k) per k=0..n."""
    fuori = [1]
    for k in range(1, n + 1):
        fuori.append(fuori[-1] * (n - k + 1) // k)
    return fuori


_COEFF = _binomiali(AVVERSARI)


class CampoAvversari(object):
    """Distribuzione dei punteggi avversari di un tipo di arena, stimata
    solo sulle arene concluse PRIMA di una certa data."""

    def __init__(self, punteggi):
        self.punteggi = sorted(punteggi)
        self.n = len(self.punteggi)

    def F(self, s):
        """Quota di avversari con punteggio <= s."""
        return bisect.bisect_right(self.punteggi, s) / self.n if self.n else 0.5

    def premio_atteso(self, atteso, sigma, premio_per_rank):
        tot = 0.0
        for z, w in zip(_NODI, _PESI):
            s = atteso + sigma * z
            q = 1.0 - self.F(s)          # probabilita' che UN avversario mi superi
            p = 1.0 - q
            atteso_s = 0.0
            for k in range(AVVERSARI + 1):   # k avversari sopra di me -> rank k+1
                premio = premio_per_rank.get(k + 1, 0)
                if not premio:
                    continue
                atteso_s += _COEFF[k] * (q ** k) * (p ** (AVVERSARI - k)) * premio
            tot += w * atteso_s
        return tot


def costruisci_campi(arene):
    """(tipo, fine) -> CampoAvversari con i soli punteggi precedenti."""
    per_tipo = defaultdict(list)
    for a in arene:
        if a.get('punteggi') and a.get('fine'):
            for p in a['punteggi']:
                per_tipo[a['tipo']].append((a['fine'], p))
    for tipo in per_tipo:
        per_tipo[tipo].sort()
    return per_tipo


def campo_a(per_tipo, tipo, fine):
    dati = per_tipo.get(tipo)
    if not dati:
        return None
    i = bisect.bisect_left(dati, (fine,))
    if i < MIN_CAMPIONE_AVVERSARI:
        return None
    return CampoAvversari([p for _f, p in dati[:i]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ricalcola', action='store_true')
    args = ap.parse_args()

    risultati = CP.carica_risultati(args.ricalcola)
    righe = CP.filtra(risultati)
    abbinate, premi_tab = H.abbina_arene(righe)
    arene = K.carica('dati_globali/arene_storico.json')['arene']
    per_tipo = costruisci_campi(arene)

    # sigma: scarto tipico fra totale REALE e totale ATTESO di una formazione
    scarti = []
    for r, _a in abbinate:
        carte = r['carte_tutte']
        cap = H.scegli_capitano(carte)
        atteso = sum(c['atteso'] for c in carte) + H.BONUS * cap['atteso']
        scarti.append(H.totale(carte, cap) - atteso)
    sigma = statistics.pstdev(scarti)
    print(f"sigma del totale formazione (reale - atteso): {sigma:.1f} punti "
          f"(scarto medio {statistics.mean(scarti):+.1f})")

    premi_per_tipo = defaultdict(dict)
    for (tipo, rank), val in premi_tab.items():
        premi_per_tipo[tipo][rank] = val

    gruppi = defaultdict(list)
    for r, a in abbinate:
        gruppi[(r['fixture'], r.get('competizione'))].append((r, a))

    rng = random.Random(SEME)
    esiti = defaultdict(list)
    senza_campo = 0

    for _chiave, membri in gruppi.items():
        campi = []
        ok = True
        for _r, a in membri:
            c = campo_a(per_tipo, a['tipo'], a['fine'])
            if c is None:
                ok = False
                break
            campi.append((c, premi_per_tipo.get(a['tipo'], {})))
        if not ok:
            senza_campo += len(membri)
            continue

        assegnazione0 = [list(r['carte_tutte']) for r, _a in membri]
        caps = [H._cap_nominale(a) for _r, a in membri]

        def cap_ok(scelte, cap_l10):
            return cap_l10 is None or sum(c['l10'] for c in scelte) <= cap_l10 + 1e-6

        def atteso_totale(scelte):
            cap = H.scegli_capitano(scelte)
            return sum(c['atteso'] for c in scelte) + H.BONUS * cap['atteso']

        def premio_atteso_di(idx, scelte):
            campo, premi = campi[idx]
            return campo.premio_atteso(atteso_totale(scelte), sigma, premi)

        def punti_attesi_di(_idx, scelte):
            return atteso_totale(scelte)

        def rialloca(obiettivo, giri=4000):
            ass = [list(s) for s in assegnazione0]
            for _ in range(giri):
                i, j = rng.randrange(len(ass)), rng.randrange(len(ass))
                if i == j:
                    continue
                ii, jj = rng.randrange(len(ass[i])), rng.randrange(len(ass[j]))
                if ass[i][ii]['ruolo'] != ass[j][jj]['ruolo']:
                    continue
                ni, nj = list(ass[i]), list(ass[j])
                ni[ii], nj[jj] = ass[j][jj], ass[i][ii]
                if len(set(c['slug'] for c in ni)) != len(ni):
                    continue
                if len(set(c['slug'] for c in nj)) != len(nj):
                    continue
                if not (cap_ok(ni, caps[i]) and cap_ok(nj, caps[j])):
                    continue
                prima = obiettivo(i, ass[i]) + obiettivo(j, ass[j])
                dopo = obiettivo(i, ni) + obiettivo(j, nj)
                if dopo > prima + 1e-9:
                    ass[i], ass[j] = ni, nj
            return ass

        def in_essenze(ass):
            fuori = []
            for (r, a), scelte in zip(membri, ass):
                cap = H.scegli_capitano(scelte)
                rank = E.piazzamento(a, a.get('mio_score'), H.totale(scelte, cap))
                fuori.append(E.premio(a, rank, premi_tab) - (E.costo(a) or 0))
            return fuori

        esiti['UTENTE (schierate davvero)'].extend(in_essenze(assegnazione0))
        esiti['MODELLO oggi (max punti attesi)'].extend(in_essenze(rialloca(punti_attesi_di)))
        esiti['NUOVO (max PREMIO atteso)'].extend(in_essenze(rialloca(premio_atteso_di)))

    n = len(esiti['UTENTE (schierate davvero)'])
    print("\n" + "=" * 78)
    print("ALLOCAZIONE A PREMIO ATTESO — essenze vere per arena")
    print("=" * 78)
    print(f"Arene valutate: {n}  (escluse {senza_campo}: campo avversari storico "
          f"insufficiente, <{MIN_CAMPIONE_AVVERSARI} punteggi precedenti)")
    if not n:
        return
    for nome in ('UTENTE (schierate davvero)', 'MODELLO oggi (max punti attesi)',
                 'NUOVO (max PREMIO atteso)'):
        print(f"  {nome:<34} {statistics.mean(esiti[nome]):8.1f}")

    print("\n  Confronti (IC95% bootstrap sulle differenze per arena):")

    def confronta(a_nome, b_nome):
        diff = [x - y for x, y in zip(esiti[a_nome], esiti[b_nome])]
        med = statistics.mean(diff)
        ic = B.intervallo_media(diff)
        marca = '' if ic[0] <= 0 <= ic[1] else ('  <== significativo' if med > 0
                                                else '  <== significativo (PEGGIO)')
        print(f"    {a_nome} - {b_nome}: {med:+.1f}/arena  IC95%=[{ic[0]:+.1f},{ic[1]:+.1f}]{marca}")

    confronta('NUOVO (max PREMIO atteso)', 'MODELLO oggi (max punti attesi)')
    confronta('NUOVO (max PREMIO atteso)', 'UTENTE (schierate davvero)')
    confronta('MODELLO oggi (max punti attesi)', 'UTENTE (schierate davvero)')

    diagnostica_perche(abbinate, per_tipo, premi_per_tipo, sigma)


def diagnostica_perche(abbinate, per_tipo, premi_per_tipo, sigma):
    """PERCHE' il premio atteso non batte i punti attesi.

    Ipotesi: con un'incertezza sul totale cosi' grande (sigma ~ 50 punti su
    formazioni da ~280), integrando la funzione premio su quel rumore si
    ottiene una funzione praticamente MONOTONA nei punti attesi — cioe' i
    due obiettivi ordinano le formazioni allo stesso modo e la non
    linearita' del premio, che in teoria era la leva, in pratica e' lavata
    via dal rumore. Qui si verifica contando quanto spesso i due obiettivi
    sono in disaccordo su una coppia di formazioni."""
    concordi = discordi = 0
    passi = []
    for r, a in abbinate[:250]:
        campo = campo_a(per_tipo, a['tipo'], a['fine'])
        if campo is None:
            continue
        premi = premi_per_tipo.get(a['tipo'], {})
        carte = r['carte_tutte']
        cap = H.scegli_capitano(carte)
        base = sum(c['atteso'] for c in carte) + H.BONUS * cap['atteso']
        # coppie di punteggi attesi plausibili intorno a quello vero
        for d1 in (-30, -20, -10, -5, 5, 10, 20, 30):
            for d2 in (-30, -20, -10, -5, 5, 10, 20, 30):
                if d1 >= d2:
                    continue
                p1 = campo.premio_atteso(base + d1, sigma, premi)
                p2 = campo.premio_atteso(base + d2, sigma, premi)
                if p2 > p1:
                    concordi += 1        # piu' punti -> piu' premio atteso
                elif p2 < p1:
                    discordi += 1
        passi.append(campo.premio_atteso(base + 10, sigma, premi)
                     - campo.premio_atteso(base, sigma, premi))

    tot = concordi + discordi
    print("\n" + "=" * 78)
    print("PERCHE' NON FUNZIONA")
    print("=" * 78)
    print(f"  sigma sul totale formazione: {sigma:.1f} punti (su formazioni da ~280)")
    if tot:
        print(f"  Coppie in cui piu' punti attesi = piu' premio atteso: "
              f"{concordi}/{tot} ({concordi/tot:.1%})")
        print(f"  Coppie in cui i due obiettivi si CONTRADDICONO: "
              f"{discordi}/{tot} ({discordi/tot:.1%})")
    if passi:
        print(f"  Valore di 10 punti attesi in piu': {statistics.mean(passi):+.1f} essenze attese")
    print("  => se la concordanza e' ~100%, massimizzare il premio atteso e'")
    print("     LA STESSA COSA che massimizzare i punti attesi: il rumore lava")
    print("     via la non linearita' del premio, e la leva teorica non esiste.")


if __name__ == '__main__':
    main()
