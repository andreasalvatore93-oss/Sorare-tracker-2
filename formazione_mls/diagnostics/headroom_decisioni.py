"""
Headroom Decisioni (04/08 notte, richiesta esplicita utente)

PERCHE'. Sul capitano abbiamo bruciato 12 ipotesi prima di misurare quanto
valesse la decisione: valeva ~1% e non poteva pagare comunque. Errore da non
ripetere sulle altre decisioni. Qui si applica LO STESSO metro a tutte, cosi'
si sa DOVE c'e' margine prima di scrivere una riga di modello.

Per ogni decisione si misurano quattro livelli, tutti nella stessa moneta
(essenze per arena, sulle arene reali dell'utente col campo vero da 10
punteggi e i premi veri):

    PAVIMENTO  la scelta peggiore possibile
    CASO       una scelta a caso fra quelle disponibili
    ATTUALE    quello che fa oggi il bot / che ha fatto l'utente
    ORACOLO    la scelta migliore col senno di poi (tetto irraggiungibile)

Il numero che conta e' `ATTUALE - CASO` (quanto vale gia' saperci fare) messo
accanto a `ORACOLO - ATTUALE` (quanto resta), sapendo che buona parte del
secondo e' fortuna e non abilita'.

Decisioni misurate:
  1. INGRESSO   entrare o no in quell'arena
  2. CARTE      quali 5 carte schierare, fra quelle disponibili quel giorno
  3. CAPITANO   gia' misurata altrove, ripetuta qui per confronto diretto

NESSUNA nuova query: previsioni da `backtest_captain_policy` (cache su
disco), campo e premi da `arene_storico.json`.

Uso: python formazione_mls/diagnostics/headroom_decisioni.py [--ricalcola]
"""
import os
import sys
import random
import argparse
import statistics
import itertools
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import backtest_arene as B
import backtest_arene_economia as E
import backtest_captain_policy as K
import captain_per_competizione as CP

sys.path.insert(0, os.path.join(os.getcwd(), 'formazione_mls', 'diagnostics'))

BONUS = K.MOLTIPLICATORE_CAPITANO - 1.0
SEME = 12345


def _cap_nominale(arena):
    """Il tetto di L10 dell'arena (None = senza cap)."""
    import backtest_arene_produzione as BP
    return BP.NOMINAL_CAP.get(arena.get('tipo'))


def scegli_capitano(carte):
    """La regola di produzione: max atteso fra i movimento, portiere escluso
    salvo che superi di GK_CAPTAIN_MARGIN (stessa logica di pick_captain)."""
    import backtest_arene_produzione as BP
    fuori = [c for c in carte if c['ruolo'] != 'Goalkeeper']
    gk = [c for c in carte if c['ruolo'] == 'Goalkeeper']
    best_out = max(fuori, key=lambda c: c['atteso']) if fuori else None
    best_gk = max(gk, key=lambda c: c['atteso']) if gk else None
    if best_gk and (not best_out or best_gk['atteso'] >= best_out['atteso'] + BP._GK_CAPTAIN_MARGIN):
        return best_gk
    return best_out or best_gk


def totale(carte, capitano):
    return sum(c['reale'] for c in carte) + BONUS * capitano['reale']


def abbina_arene(righe):
    """Le formazioni dell'utente abbinate alla riga di arene_storico con il
    campo reale (stesso abbinamento di captain_per_competizione)."""
    arene = K.carica('dati_globali/arene_storico.json')['arene']
    per_slug = defaultdict(list)
    for a in arene:
        if a.get('punteggi'):
            per_slug[a['slug']].append(a)
    fuori = []
    for r in righe:
        slug = r.get('slug_arena')
        if not slug or slug not in per_slug:
            continue
        cand = [a for a in per_slug[slug]
                if abs((a.get('mio_score') or -1) - r['punteggio_reale']) < 0.01]
        if len(cand) == 1 and r.get('carte_tutte') and len(r['carte_tutte']) == 5:
            fuori.append((r, cand[0]))
    return fuori, E.tabella_premi(arene)


def stampa(nome, pavimento, caso, attuale, oracolo, note=''):
    print(f"\n  {nome}")
    print(f"    PAVIMENTO {statistics.mean(pavimento):8.1f}")
    print(f"    CASO      {statistics.mean(caso):8.1f}")
    print(f"    ATTUALE   {statistics.mean(attuale):8.1f}")
    print(f"    ORACOLO   {statistics.mean(oracolo):8.1f}")
    guadagnato = statistics.mean(attuale) - statistics.mean(caso)
    residuo = statistics.mean(oracolo) - statistics.mean(attuale)
    ic = B.intervallo_media([a - c for a, c in zip(attuale, caso)])
    print(f"    -> gia' guadagnato sul caso: {guadagnato:+.1f}/arena  "
          f"IC95%=[{ic[0]:+.1f},{ic[1]:+.1f}]")
    print(f"    -> margine residuo:          {residuo:+.1f}/arena")
    if note:
        print(f"    {note}")


def decisione_ingresso(abbinate, premi_tab):
    """Entrare o no. Il premio e' quello VERO col punteggio VERO: l'unica
    incognita e' la decisione, quindi qui non c'e' nessuna modellazione."""
    pavimento, caso, attuale, oracolo = [], [], [], []
    rng = random.Random(SEME)
    import backtest_arene_produzione as BP
    for r, a in abbinate:
        carte = r['carte_tutte']
        cap = scegli_capitano(carte)
        punteggio = totale(carte, cap)
        rank = E.piazzamento(a, a.get('mio_score'), punteggio)
        netto = E.premio(a, rank, premi_tab) - (E.costo(a) or 0)

        # la regola di oggi: entra se la resa attesa e' positiva
        tipo_bfg, _fam, _av = BP.classifica_tipo_produzione(a)
        soglia = BP.bfg.PAREGGIO_ARENA.get(tipo_bfg)
        atteso_tot = sum(c['atteso'] for c in carte) + BONUS * cap['atteso']
        entra_bot = soglia is not None and atteso_tot > soglia

        pavimento.append(min(0.0, netto))
        caso.append(0.5 * netto)
        attuale.append(netto if entra_bot else 0.0)
        oracolo.append(max(0.0, netto))
    stampa('1. INGRESSO (entrare o no in quell\'arena)', pavimento, caso, attuale, oracolo,
           note="(CASO = entra a testa o croce; PAVIMENTO = entra solo quando perde)")


def decisione_carte(abbinate, premi_tab, righe_tutte):
    """Quali 5 carte schierare, fra quelle davvero disponibili.

    Il pool e' ristretto alle carte che l'utente ha usato quel giorno IN
    ARENE DELLO STESSO TIPO. Restrizione necessaria: le carte non sono
    intercambiabili fra tipi (idoneita', rarita', in-season, cap), e un pool
    per sola giornata lascerebbe mettere un fuoriclasse da arena uncapped
    dentro una Beginner — misura senza senso.

    Vincoli rispettati: stessa composizione di ruoli della formazione vera,
    nessuna carta ripetuta, e somma L10 entro il cap dove l'arena ce l'ha
    (il cap e' proprio la ragione per cui non si schierano i 5 migliori).

    CASO e' un campione DAVVERO casuale di formazioni valide (non i primi N
    del prodotto cartesiano ordinato: quello sovrarappresenta le carte
    migliori e gonfia il caso, primo tentativo sbagliato di questo script).
    ORACOLO/PAVIMENTO si cercano fra i migliori/peggiori per punteggio reale
    di ogni ruolo, col cap applicato."""
    per_gruppo = defaultdict(dict)
    for r in righe_tutte:
        chiave = (r['fixture'], r.get('competizione'))
        for c in (r.get('carte_tutte') or []):
            if c.get('l10') is not None:
                per_gruppo[chiave][(c['slug'], c['ruolo'])] = c

    pavimento, caso, attuale, oracolo = [], [], [], []
    rng = random.Random(SEME)
    saltate = 0
    pool_size = []
    for r, a in abbinate:
        carte = r['carte_tutte']
        if any(c.get('l10') is None for c in carte):
            saltate += 1
            continue
        cap_l10 = _cap_nominale(a)
        pool = per_gruppo.get((r['fixture'], r.get('competizione')), {})
        per_ruolo = defaultdict(list)
        for c in pool.values():
            per_ruolo[c['ruolo']].append(c)
        composizione = [c['ruolo'] for c in carte]
        # serve almeno una scelta vera: se il pool contiene solo le carte
        # gia' schierate, la decisione non esiste e l'arena non dice nulla
        if sum(len(per_ruolo.get(ru, [])) for ru in set(composizione)) <= len(set(composizione)):
            saltate += 1
            continue
        pool_size.append(len(pool))

        def valuta(scelte):
            capi = scegli_capitano(scelte)
            rank = E.piazzamento(a, a.get('mio_score'), totale(scelte, capi))
            return E.premio(a, rank, premi_tab) - (E.costo(a) or 0)

        def valida(scelte):
            slugs = [c['slug'] for c in scelte]
            if len(set(slugs)) != len(slugs):
                return False
            if cap_l10 is None:
                return True
            return sum(c['l10'] for c in scelte) <= cap_l10 + 1e-6

        # --- CASO: campionamento casuale con rifiuto ---
        casuali = []
        for _ in range(400):
            scelte = [rng.choice(per_ruolo[ru]) for ru in composizione]
            if valida(scelte):
                casuali.append(valuta(scelte))
            if len(casuali) >= 120:
                break
        if not casuali:
            saltate += 1
            continue

        # --- ORACOLO e PAVIMENTO: ricerca fra gli estremi per punteggio reale ---
        def cerca(migliori):
            verso = -1 if migliori else 1
            insiemi = [sorted(per_ruolo[ru], key=lambda c: verso * c['reale'])[:4]
                       for ru in composizione]
            valori = [valuta(combo) for combo in itertools.product(*insiemi) if valida(combo)]
            return valori

        alti, bassi = cerca(True), cerca(False)
        if not alti or not bassi:
            saltate += 1
            continue

        pavimento.append(min(bassi))
        oracolo.append(max(alti))
        caso.append(statistics.mean(casuali))
        attuale.append(valuta(carte))

    mediana_pool = statistics.median(pool_size) if pool_size else 0
    stampa('2. CARTE (quali 5 schierare, a parita\' di pool, tipo arena e cap)',
           pavimento, caso, attuale, oracolo,
           note=(f"(pool mediano {mediana_pool:.0f} carte dello STESSO tipo di arena; "
                 f"{saltate} arene senza scelta reale o non valutabili)"))


def decisione_capitano(abbinate, premi_tab):
    pavimento, caso, attuale, oracolo = [], [], [], []
    for r, a in abbinate:
        carte = r['carte_tutte']
        fuori = [c for c in carte if c['ruolo'] != 'Goalkeeper']
        netti = []
        for c in fuori:
            punteggio = totale(carte, c)
            rank = E.piazzamento(a, a.get('mio_score'), punteggio)
            netti.append(E.premio(a, rank, premi_tab) - (E.costo(a) or 0))
        cap = scegli_capitano(carte)
        punteggio = totale(carte, cap)
        rank = E.piazzamento(a, a.get('mio_score'), punteggio)
        attuale.append(E.premio(a, rank, premi_tab) - (E.costo(a) or 0))
        pavimento.append(min(netti))
        caso.append(statistics.mean(netti))
        oracolo.append(max(netti))
    stampa('3. CAPITANO (chi porta la fascia, a parita\' di carte)',
           pavimento, caso, attuale, oracolo)


def formazione_per_il_capitano(abbinate, righe_tutte):
    """IPOTESI: il capitano moltiplica UNA carta, quindi a parita' di budget
    conviene concentrarlo (un fuoriclasse + 4 riempitivi) invece di
    spalmarlo su 5 carte equivalenti?

    Il budget e' il cap L10 dell'arena: e' proprio il cap a rendere la
    domanda sensata (senza tetto si prendono i 5 migliori e non c'e' nessun
    compromesso). Quindi si guardano SOLO le arene con cap, e solo le
    formazioni che usano quasi tutto il budget (>=90% del cap): a parita' di
    budget speso, la concentrazione paga o no?

    Misura: dentro ogni arena, correlazione fra concentrazione
    (L10 della carta piu' forte / somma L10) e punteggio totale REALE
    ottenuto. Correlazione media fra arene, cosi' nessuna arena con tanti
    campioni domina il risultato."""
    per_gruppo = defaultdict(dict)
    for r in righe_tutte:
        chiave = (r['fixture'], r.get('competizione'))
        for c in (r.get('carte_tutte') or []):
            if c.get('l10') is not None:
                per_gruppo[chiave][(c['slug'], c['ruolo'])] = c

    rng = random.Random(SEME)
    correlazioni = []
    for r, a in abbinate:
        cap_l10 = _cap_nominale(a)
        if cap_l10 is None:
            continue
        carte = r['carte_tutte']
        if any(c.get('l10') is None for c in carte):
            continue
        pool = per_gruppo.get((r['fixture'], r.get('competizione')), {})
        per_ruolo = defaultdict(list)
        for c in pool.values():
            per_ruolo[c['ruolo']].append(c)
        composizione = [c['ruolo'] for c in carte]
        if any(not per_ruolo.get(ru) for ru in composizione):
            continue

        punti = []
        for _ in range(1500):
            scelte = [rng.choice(per_ruolo[ru]) for ru in composizione]
            slugs = [c['slug'] for c in scelte]
            if len(set(slugs)) != len(slugs):
                continue
            somma_l10 = sum(c['l10'] for c in scelte)
            if somma_l10 > cap_l10 or somma_l10 < 0.90 * cap_l10:
                continue
            concentrazione = max(c['l10'] for c in scelte) / somma_l10
            capi = scegli_capitano(scelte)
            punti.append((concentrazione, totale(scelte, capi)))
            if len(punti) >= 80:
                break
        if len(punti) < 25:
            continue
        xs = [p[0] for p in punti]
        ys = [p[1] for p in punti]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        if den:
            correlazioni.append(sum((x - mx) * (y - my) for x, y in punti) / den)

    print("\n" + "=" * 78)
    print("FORMAZIONE COSTRUITA PER IL CAPITANO (concentrata vs equilibrata)")
    print("=" * 78)
    if not correlazioni:
        print("  nessuna arena con cap e pool sufficiente: non misurabile")
        return
    media = statistics.mean(correlazioni)
    ic = B.intervallo_media(correlazioni)
    positive = sum(1 for c in correlazioni if c > 0)
    print(f"  Arene con cap valutate: {len(correlazioni)}")
    print(f"  Correlazione media concentrazione -> punteggio: {media:+.3f}  "
          f"IC95%=[{ic[0]:+.3f},{ic[1]:+.3f}]")
    print(f"  Arene con correlazione positiva: {positive}/{len(correlazioni)} "
          f"({positive/len(correlazioni):.0%})")
    if ic[0] > 0:
        print("  => CONCENTRARE il budget su una carta forte PAGA.")
    elif ic[1] < 0:
        print("  => SPALMARE il budget paga: concentrare peggiora.")
    else:
        print("  => nessuna differenza distinguibile dal rumore.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ricalcola', action='store_true')
    args = ap.parse_args()

    risultati = CP.carica_risultati(args.ricalcola)
    righe = CP.filtra(risultati)
    abbinate, premi_tab = abbina_arene(righe)

    print("\n" + "=" * 78)
    print("HEADROOM DELLE DECISIONI — tutte nella stessa moneta (essenze/arena)")
    print("=" * 78)
    print(f"Arene reali dell'utente col campo vero: {len(abbinate)}")

    decisione_ingresso(abbinate, premi_tab)
    decisione_capitano(abbinate, premi_tab)
    decisione_carte(abbinate, premi_tab, righe)
    formazione_per_il_capitano(abbinate, righe)


if __name__ == '__main__':
    main()
