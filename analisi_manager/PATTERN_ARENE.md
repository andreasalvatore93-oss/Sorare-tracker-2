# PATTERN ARENE — 3 filoni sulle 442 arene reali

Sessione **05/08/2026, ore ~03:30 (Roma, CEST)**. Dati: `analisi_manager/dati/
formazioni_*.json` (8 GW, 442 formazioni-arena, 2210 card-slot, 1215 carte
uniche `(gw,slug)`). Script riproducibile: `analisi_manager/pattern_arene.py`
(pure Python, no numpy). Boom = `reale`>=75; flop = `reale`<25. De-dup su
`(gw,slug)` dove servono osservazioni indipendenti (trappola §15 handoff).

Risposta secca alle 3 idee: **nessun breakthrough**. Due fatti NUOVI e
operativi (pooling+uncapped; eterogeneità del boom per ruolo), il resto
conferma o nega. Sotto i numeri integrali, anche i nulli.

---

## FILONE 1 — Metrica di selezione (indice ex-ante vs rank; rank basso=meglio)

Domanda handoff §7: `corr(atteso_sum, rank) ≈ 0` mentre `corr(reale_sum,
rank) = −0.83`. Serve un indice `P(≥1 boom)` al posto del totale-atteso?

Spearman con rank (pooled, tutte le competizioni, n=408 formazioni predette):

    reale_sum (meccanico, ex-post)   −0.855   <- tetto
    sum_atteso                       −0.006   (riproduce il −0.02 del handoff)
    max_atteso                       −0.040
    top2_atteso                      −0.017
    exp_nboom (n. atteso di boom)    −0.005
    pboom_1plus (P>=1 boom)          −0.009

**Il pooling è un artefatto.** Ogni arena classifica 1-10 nel SUO pool, ma i
livelli assoluti di `sum_atteso` differiscono per competizione: mischiarli
lava via il segnale. Correlazione within-competizione (rank e indice centrati
per gruppo, pooled):

    sum_atteso   −0.054     max_atteso  −0.042     pboom_1plus  −0.043

→ ~9x il pooled grezzo, ma ancora debole. Il break-down per competizione
spiega perché:

    competizione  n    std(sum_atteso)  corr(sum,rank)  corr(pboom1+,rank)
    Cap 260      199        9.1            −0.052          −0.039
    Elite         75       11.8            −0.045          −0.088
    Beginner      54        8.3            −0.088          −0.015
    Cap 220       49        8.6            −0.117          −0.116
    Uncapped      31       15.4            −0.303          −0.299

**Il cap comprime i totali attesi** (std ~8-9): tutti maxano il vincolo L10,
restano attesi quasi uguali, il modello ha poco da discriminare. Dove il cap
NON morde (**Uncapped**, std 15.4) il totale-atteso predice il rank a −0.30.
Elite rompe la storia "più spread→più segnale" (std 11.8 ma corr −0.045):
lì tutti giocano i fuoriclasse → ri-restrizione in alto.

AUC nel predire il PODIO (rank<=3): sum 0.549, max 0.582, top2 0.575,
exp_nboom 0.557, pboom 0.561; reale_sum 0.935.

**Verdetto.** L'indice `P(≥1 boom)` NON batte il totale-atteso né `max_atteso`
(tutti ~−0.04/−0.05 centrati): domanda §7 → **risposta NO**. Ma il "−0.02
inutile" del handoff era ottimista al ribasso: within-competizione è −0.05, e
in **Uncapped −0.30** (n=31, da riverificare). Operativo: il totale-atteso è
utile per SCEGLIERE la formazione soprattutto in Uncapped; nelle cap il
vincolo L10 già equalizza gli attesi e il modello lì discrimina poco.

---

## FILONE 2 — Modellare il boom (target reale>=75, card-level de-dup, OOF per GW)

Domanda: lo screening §5.3 (R²=0.008) era sul residuo della MEDIA. L'EVENTO
boom (binario) è più predicibile? Carte uniche=1215, boom=11.9%.

AUC single-feature (ordinamento del boom):

    atteso            0.642      partite_storiche  0.509
    l10               0.635      in_casa           0.466  (<0.5: casa NON aiuta)

OOF leave-one-GW-out (logistica atteso+l10+casa+storico+ruolo):

    atteso-only  0.633
    full model   0.658   delta +0.025

Il boom è debolmente predicibile (0.658) ma `atteso` fa quasi tutto; il
modello completo aggiunge solo +0.025. **Fatto NUOVO: il potere di `atteso`
sul boom dipende fortissimo dal ruolo:**

    ruolo        n     boom%    AUC(atteso sul boom)
    Forward     302    13.6%        0.696
    Midfielder  316    15.5%        0.635
    Defender    393     8.4%        0.614
    Goalkeeper  204    10.8%        0.571   (≈ caso)

**Verdetto.** L'edge del modello sul boom vive negli ATTACCANTI (0.70); sul
GK il boom è testa-o-croce (0.57, riconferma la debolezza GK nota, §5
handoff). Un boom-classifier dedicato aggiunge poco (+0.025): non è la leva.
La leva vera è sapere DOVE il segnale c'è (FWD sì, GK no).

---

## FILONE 3 — Partire dalla partita (covarianza boom fra compagni)

Domanda: `P(≥1 boom)` dipende dalla covarianza fra le 5 carte? Carte della
stessa partita esplodono insieme?

    boom marginale                                  11.8%
    P(carta booma | compagno stesso team/GW booma)  14.0%  (n_cond=343)
    coppie stesso team: 1707  co-boom oss. 1.8%  vs atteso-se-indip. 1.4%
    phi(boom_i, boom_j) coppie STESSO team          +0.012   ≈ 0

Sul BOOM binario la covarianza fra compagni è ~0: l'indipendenza che il
modello assume regge per la CODA. Ma sul PUNTEGGIO CONTINUO:

    pearson(reale_i, reale_j) STESSO team           +0.133  (n=1707)
    controllo (stessa GW, squadre DIVERSE)          +0.029

I compagni si muovono insieme (+0.13 vs 0.03 di controllo: clean sheet,
squadra che vince) ma è moderato e NON arriva al boom. Concentrazione club vs
rank medio: 5→5.77, 4→5.70, 3→5.42, 2→5.00 (n=9), 1→3.00 (n=2): nessun
vantaggio pulito (n piccoli sui concentrati).

**Verdetto.** "Partire dalla partita" per la selezione-boom: leva piccola.
La covarianza esiste sul punteggio medio (+0.13) → concentrare carte della
stessa partita alza un po' la varianza del totale, ma non `P(≥1 boom)`
(phi ~0). In gran parte chiuso.

---

## Bottom line

- L'idea `P(≥1 boom)` come metrica di selezione: **bocciata**, non batte il
  totale-atteso. (§7 handoff → chiudere.)
- Correzione al handoff: il totale-atteso NON è inutile, è nascosto dal cap;
  in **Uncapped predice il rank a −0.30**. Da riverificare con più arene
  uncapped.
- Il boom è predicibile solo per ruolo: **FWD 0.70, GK 0.57**. Riconferma GK.
- Covarianza fra compagni: reale sul punteggio (+0.13), ~0 sul boom → layer
  match non aiuta la selezione-boom.

Da riverificare (unici thread vivi): Uncapped −0.30 con più arene; se serve,
trattare la scelta della formazione in Uncapped/Elite fidandosi del totale.
