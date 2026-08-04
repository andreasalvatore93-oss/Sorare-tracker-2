"""
Selezione Carte (04/08 notte) — il filone con 36x il margine del capitano

DOMANDA GIUSTA PER PRIMA. Sul capitano abbiamo provato euristiche per due
sessioni prima di scoprire che la decisione valeva l'1%. Qui non si parte
dalle euristiche: si parte da "il modello serve?".

Nel scegliere 5 carte sotto un tetto di L10, si confrontano regole che
usano informazione diversa, tutte valutate in ESSENZE VERE sulle arene
reali dell'utente (campo vero da 10 punteggi, premi veri):

  CASO         5 carte valide a caso dal pool
  SOLO L10     le carte piu' "costose" ammesse dal tetto — nessun modello,
               solo il dato che Sorare stessa mostra. E' IL CONTROLLO: se
               il modello non batte questo, non serve a selezionare.
  MODELLO      massimizza la somma degli attesi sotto il tetto (la regola
               che il bot usa oggi)
  UTENTE       le 5 carte che l'utente ha davvero schierato
  ORACOLO      le migliori col senno di poi (tetto, gonfiato dalla fortuna)

Vincoli sempre rispettati: stessa composizione di ruoli della formazione
vera, nessuna carta ripetuta, somma L10 entro il cap dell'arena.
Il pool e' ristretto alle carte usate quel giorno IN ARENE DELLO STESSO
TIPO (le carte non sono intercambiabili fra tipi: idoneita', rarita', cap).

NESSUNA nuova query.

Uso: python formazione_mls/diagnostics/selezione_carte.py [--ricalcola]
"""
import os
import sys
import random
import argparse
import statistics
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene as B
import backtest_arene_economia as E
import backtest_captain_policy as K
import captain_per_competizione as CP
import headroom_decisioni as H

SEME = 4242
GIRI_RICERCA = 700


def ottimizza(per_ruolo, composizione, cap_l10, chiave, rng, giri=GIRI_RICERCA):
    """Massimizza la somma di `chiave` su una formazione valida.

    Ricerca locale con riavvii invece di programmazione dinamica: il vincolo
    di non ripetere la stessa carta fra slot dello stesso ruolo non e'
    separabile per slot, e con pool di ~50 carte la ricerca locale arriva
    all'ottimo in millisecondi. Ritorna None se non trova nulla di valido."""
    def valida(scelte):
        slugs = [c['slug'] for c in scelte]
        if len(set(slugs)) != len(slugs):
            return False
        if cap_l10 is None:
            return True
        return sum(c['l10'] for c in scelte) <= cap_l10 + 1e-6

    def punteggio(scelte):
        return sum(chiave(c) for c in scelte)

    migliore, valore_migliore = None, None
    for _riavvio in range(6):
        scelte = [rng.choice(per_ruolo[ru]) for ru in composizione]
        if not valida(scelte):
            # parte dalle carte piu' leggere, cosi' il cap e' rispettabile
            scelte = [min(per_ruolo[ru], key=lambda c: c['l10']) for ru in composizione]
            if not valida(scelte):
                continue
        migliorato = True
        while migliorato:
            migliorato = False
            for i, ru in enumerate(composizione):
                for cand in per_ruolo[ru]:
                    if cand is scelte[i]:
                        continue
                    prova = list(scelte)
                    prova[i] = cand
                    if valida(prova) and punteggio(prova) > punteggio(scelte) + 1e-9:
                        scelte = prova
                        migliorato = True
        v = punteggio(scelte)
        if valore_migliore is None or v > valore_migliore:
            migliore, valore_migliore = scelte, v
    return migliore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ricalcola', action='store_true')
    args = ap.parse_args()

    risultati = CP.carica_risultati(args.ricalcola)
    righe = CP.filtra(risultati)
    abbinate, premi_tab = H.abbina_arene(righe)

    per_gruppo = defaultdict(dict)
    for r in righe:
        chiave = (r['fixture'], r.get('competizione'))
        for c in (r.get('carte_tutte') or []):
            if c.get('l10') is not None:
                per_gruppo[chiave][(c['slug'], c['ruolo'])] = c

    # --- vincolo fondamentale: le carte non si clonano ---
    # Primo tentativo di questo script (sbagliato, tenuto qui come monito):
    # ogni arena sceglieva liberamente dal pool del giorno, quindi il modello
    # metteva le STESSE 5 carte migliori in tutte le ~10 arene di quel tipo,
    # mentre l'utente le doveva spalmare. Dava +132 essenze/arena di finto
    # vantaggio. E' la "riallocazione libera del pool" gia' bocciata
    # dall'utente il 04/08. Ora ogni carta puo' essere usata al massimo
    # quante volte l'utente l'ha usata davvero quel giorno in quel tipo di
    # arena (le copie multiple sono reali: chi ha 2 copie puo' schierarla 2
    # volte), e le arene del gruppo si servono in sequenza dallo stesso
    # mazzo che si esaurisce.
    gruppi = defaultdict(list)
    for r, a in abbinate:
        gruppi[(r['fixture'], r.get('competizione'))].append((r, a))

    rng = random.Random(SEME)
    esiti = defaultdict(list)
    saltate = 0
    pool_size = []

    for chiave_gruppo, membri in gruppi.items():
        # quante volte l'utente ha usato ciascuna carta in questo gruppo
        molteplicita = defaultdict(int)
        for r, _a in membri:
            for c in r['carte_tutte']:
                molteplicita[(c['slug'], c['ruolo'])] += 1
        anagrafica = per_gruppo.get(chiave_gruppo, {})
        if any(c.get('l10') is None for c in anagrafica.values()):
            saltate += len(membri)
            continue
        pool_size.append(len(anagrafica))

        # RIALLOCAZIONE dello STESSO mazzo. Si parte dall'assegnazione vera
        # dell'utente (sempre fattibile per definizione) e si scambiano
        # carte dello stesso ruolo FRA arene del gruppo: il mazzo resta
        # identico carta per carta, cambia solo chi va dove. Cosi' non
        # servono ne' cloni ne' assegnazioni greedy che si incastrano
        # (il tentativo precedente perdeva l'86% delle arene).
        assegnazione0 = [list(r['carte_tutte']) for r, _a in membri]
        caps = [H._cap_nominale(a) for _r, a in membri]

        def cap_ok(scelte, cap_l10):
            return cap_l10 is None or sum(c['l10'] for c in scelte) <= cap_l10 + 1e-6

        def valore(scelte, chiave):
            return sum(chiave(c) for c in scelte) + 0.2 * max(chiave(c) for c in scelte)

        def rialloca(chiave, giri=4000, a_caso=False):
            ass = [list(s) for s in assegnazione0]
            for _ in range(giri):
                i, j = rng.randrange(len(ass)), rng.randrange(len(ass))
                if i == j:
                    continue
                ii, jj = rng.randrange(len(ass[i])), rng.randrange(len(ass[j]))
                if ass[i][ii]['ruolo'] != ass[j][jj]['ruolo']:
                    continue
                nuovo_i = list(ass[i]); nuovo_j = list(ass[j])
                nuovo_i[ii], nuovo_j[jj] = ass[j][jj], ass[i][ii]
                if len(set(c['slug'] for c in nuovo_i)) != len(nuovo_i):
                    continue
                if len(set(c['slug'] for c in nuovo_j)) != len(nuovo_j):
                    continue
                if not (cap_ok(nuovo_i, caps[i]) and cap_ok(nuovo_j, caps[j])):
                    continue
                if a_caso:
                    ass[i], ass[j] = nuovo_i, nuovo_j
                    continue
                prima = valore(ass[i], chiave) + valore(ass[j], chiave)
                dopo = valore(nuovo_i, chiave) + valore(nuovo_j, chiave)
                if dopo > prima + 1e-9:
                    ass[i], ass[j] = nuovo_i, nuovo_j
            return ass

        def in_essenze(ass):
            fuori = []
            for (r, a), scelte in zip(membri, ass):
                capi = H.scegli_capitano(scelte)
                rank = E.piazzamento(a, a.get('mio_score'), H.totale(scelte, capi))
                fuori.append(E.premio(a, rank, premi_tab) - (E.costo(a) or 0))
            return fuori

        def rialloca_su_premio(giri=4000):
            """L'oracolo VERO della riallocazione.

            Col mazzo fisso la somma dei punti e' CONSERVATA: spostare carte
            fra arene non crea punti, cambia solo come sono distribuiti. Un
            oracolo che massimizza i punti quindi non ottimizza nulla (ed
            era il bug: usciva peggio dell'utente). L'unica cosa che la
            riallocazione puo' davvero migliorare e' il PREMIO, perche' il
            premio non e' lineare nel punteggio: conviene concentrare quanto
            basta a vincere le arene vincibili e non sprecare punti dove si
            vincerebbe comunque o non si vincerebbe mai."""
            ass = [list(s) for s in assegnazione0]
            attuale = in_essenze(ass)
            for _ in range(giri):
                i, j = rng.randrange(len(ass)), rng.randrange(len(ass))
                if i == j:
                    continue
                ii, jj = rng.randrange(len(ass[i])), rng.randrange(len(ass[j]))
                if ass[i][ii]['ruolo'] != ass[j][jj]['ruolo']:
                    continue
                nuovo_i = list(ass[i]); nuovo_j = list(ass[j])
                nuovo_i[ii], nuovo_j[jj] = ass[j][jj], ass[i][ii]
                if len(set(c['slug'] for c in nuovo_i)) != len(nuovo_i):
                    continue
                if len(set(c['slug'] for c in nuovo_j)) != len(nuovo_j):
                    continue
                if not (cap_ok(nuovo_i, caps[i]) and cap_ok(nuovo_j, caps[j])):
                    continue
                prova = list(ass)
                prova[i], prova[j] = nuovo_i, nuovo_j
                nuovi = in_essenze(prova)
                if sum(nuovi) > sum(attuale) + 1e-9:
                    ass, attuale = prova, nuovi
            return ass

        esiti['CASO'].extend(in_essenze(rialloca(None, a_caso=True)))
        esiti['MODELLO (max atteso)'].extend(in_essenze(rialloca(lambda c: c['atteso'])))
        esiti['SOLO L10 (nessun modello)'].extend(in_essenze(rialloca(lambda c: c['l10'])))
        esiti['UTENTE (schierate davvero)'].extend(in_essenze(assegnazione0))
        esiti['ORACOLO (sui PREMI)'].extend(in_essenze(rialloca_su_premio()))

    n = len(esiti['CASO'])
    print("\n" + "=" * 78)
    print("SELEZIONE DELLE CARTE — essenze vere per arena")
    print("=" * 78)
    print(f"Arene valutate: {n}  (saltate {saltate}; pool mediano "
          f"{statistics.median(pool_size) if pool_size else 0:.0f} carte)")
    if not n:
        return

    ordine = ['CASO', 'SOLO L10 (nessun modello)', 'MODELLO (max atteso)',
              'UTENTE (schierate davvero)', 'ORACOLO (sui PREMI)']
    for nome in ordine:
        print(f"  {nome:<28} {statistics.mean(esiti[nome]):8.1f}")

    print("\n  Confronti che contano (IC95% bootstrap sulle differenze per arena):")
    def confronta(a_nome, b_nome):
        diff = [x - y for x, y in zip(esiti[a_nome], esiti[b_nome])]
        med = statistics.mean(diff)
        ic = B.intervallo_media(diff)
        marca = '' if ic[0] <= 0 <= ic[1] else ('  <== significativo' if med > 0
                                                else '  <== significativo (PEGGIO)')
        print(f"    {a_nome} - {b_nome}: {med:+.1f}/arena  "
              f"IC95%=[{ic[0]:+.1f},{ic[1]:+.1f}]{marca}")

    confronta('MODELLO (max atteso)', 'SOLO L10 (nessun modello)')
    confronta('MODELLO (max atteso)', 'CASO')
    confronta('MODELLO (max atteso)', 'UTENTE (schierate davvero)')
    confronta('SOLO L10 (nessun modello)', 'CASO')


if __name__ == '__main__':
    main()
