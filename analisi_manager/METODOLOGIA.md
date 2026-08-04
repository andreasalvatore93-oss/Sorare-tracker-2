# Metodologia — analisi delle formazioni dei manager (filone "smart money")

**BOZZA da migliorare insieme.** Home del filone: cartella `analisi_manager/`.
Qui vivono la metodologia, i dataset per-GW che si accumulano e i report.
Menzionata in CLAUDE.md e nel riassunto unificato §7.

Ultimo aggiornamento: 04/08/2026, sera (Roma, CEST).

---

## 0. Domanda madre e principio

Domanda: **dai pick reali di bravi manager si ricava un segnale che il nostro
modello NON ha** (per migliorare prediction / capitano / scelta arena)?

Principio di accumulo: una singola GW ha n piccola e rumore alto. Il valore si
costruisce **accumulando GW** nella stessa struttura, e si conclude solo quando
un pattern è **stabile di segno su più GW** (regola del delta, CLAUDE.md). Ogni
misura riporta sempre la sua n e quanti pick sono stati scartati e perché.

## 1. Dati e unità di analisi

Fonte: `dati_globali/manager_<slug>.json` (arene di GW CHIUSE, pubbliche) +
`atteso` calcolato in **walk-forward stretto as-of pre-GW**
(`backtest_arene_previsioni.score_atteso`, stesse funzioni di produzione, nessuna
formula riscritta, nessun leakage).

Quattro livelli di riga, tutti salvati:
- **carta**: (manager, formazione, carta) — l'osservazione base.
- **formazione**: le 5 carte insieme + piazzamento reale.
- **giocatore unico**: dedup per slug (consenso, non peso-per-popolarità).
- **manager**: comportamento aggregato.

Campi grezzi per carta: realizzato (`punteggio` grezzo d'arena, **tolto
capitano +20% additivo**), atteso, L10 as-of, ruolo, lega, squadra, capitano,
competizione/tipo_arena, piazzamento (rank, punteggio formazione), bonus_carta,
xp, in_season, u23, rarità.

Filtri (come `errore_modello_storico`): si esclude chi ha realizzato 0 (non è
sceso in campo = alea, non errore); si tiene chi ha giocato poco. Si conta e
si riporta ogni scarto ("storico insufficiente", "no partita target", ecc.).

## 2. Assi di analisi (vagliare ogni cosa)

### A. Qualità di selezione — i loro pick battono l'`atteso`?
- **Residuo medio** (bias = realizzato − atteso) globale, con IC. E scomposto
  per: ruolo, lega, competizione (Cap 220/260/beginner), casa/trasferta,
  favorito/sfavorito, **fascia di atteso**, **fascia di L10**.
- Correlazione atteso/reale, MAE, dispersione previsto vs reale (compressione).
- **Consenso**: giocatori scelti da N manager diversi → il residuo cresce con N?
  (wisdom-of-crowd = il vero test smart-money).
- **Lift di selezione**: i loro atteso vs baseline (slot medio ~51.8; oppure
  media del pool schierabile della lega).

### B. Capitano — la leva più diretta
- Chi capitanano: ruolo, **rank-atteso** dentro la loro formazione (1°/2°/…),
  rank-L10.
- Accordo col nostro `pick_captain()`: quante volte scelgono la stessa carta.
- Il loro capitano ha reso **sopra la media della formazione**? hit-rate;
  residuo dei capitani vs non-capitani.
- Guadagno reale: punti/essenze del loro capitano vs il capitano che avremmo
  scelto noi sulla stessa formazione.

### C. Composizione della formazione
- Mix ruoli, **diversità di club**, uso del cap L10 (somma L10 vs soglia della
  competizione), concentrazione (1 star + riempitivi vs 5 bilanciate),
  % in_season/u23, rarità, xp medio.
- **Rischio disponibilità**: starter-odds/presence media che accettano
  (fy 0.74 vs utente 0.84 nel confronto GW2).

### D. Esito arena — il nostro atteso predice il piazzamento?
- Correlazione **atteso-somma-formazione** vs rank reale e vs punteggio reale
  della formazione. Valida il modello come **selettore di formazione/arena**,
  non solo di singolo giocatore.
- Formazioni a premio (rank ≤ 3) vs no: differiscono nell'atteso-somma? →
  soglia d'ingresso.

### E. Volume e comportamento
- N formazioni per manager, tipi di arena giocati, ripetizione carte, quanti
  manager "grossi" vs occasionali.

### F. Skill del manager NEL TEMPO (il vero smart-money)
- Residuo per manager, tracciato **su più GW**. Se la media globale è ~0 ma
  *alcuni* manager hanno residuo positivo **persistente** su GW indipendenti,
  quelli sono gli sharp veri → pesare i loro pick futuri. Un null-in-media può
  nascondere pochi bravi in mezzo a molti medi.

### G. Miniera della coda positiva (→ feature nuove per il modello)
- I residui `realizzato − atteso` più grandi (destra della distribuzione): cosa
  condividono (lega, ruolo, casa/trasferta, fascia L10, avversario)? È la via
  concreta per scoprire una **feature mancante** del modello.
- Calibrazione delle code: boom(>75)/flop(<25) dei loro pick vs quello che il
  nostro atteso-quantile prevedeva.
- Volatilità ignorata: incrociare col nostro `range` (oggi decorativo, §5) —
  scelgono giocatori dove eravamo incerti e che poi esplodono?

### H. Livello formazione (sinergie/covarianza)
- Residuo della FORMAZIONE intera (5 carte) vs atteso-somma: coglie sinergie o
  covarianza che il per-giocatore perde.

### I. Benchmark vs strategie naive
- I loro pick battono una regola stupida (es. "prendi L10 più alto",
  "prendi favorito in casa")? Contestualizza quanta skill c'è davvero.

## 3. Pipeline unica (obiettivo) e output

**Uno script/workflow solo, idempotente, per-GW** (evita il balletto multi-step
di questa prima volta):
```
estrai arene (ricostruisci_manager --solo-arene)
  -> refresh/predict game-log dei pick (predici_manager_batch --force)
  -> misura + analizza (analizza_gw.py)
  -> scrive dataset + report, committa
```
Le run future sono più corte: i giocatori restano cachati, si appende solo la
GW nuova. Il costo residuo è il refresh API (frenato dai 429), non azzerabile.

Per ogni GW, in `analisi_manager/dati/`:
- `righe_<gw>.json` — dataset a livello carta (tutti i campi §1).
- `formazioni_<gw>.json` — dataset a livello formazione.
- `report_<gw>.md` — le tabelle degli assi §2, con n e scarti.

`analisi_manager/INDICE.md` accumula il verdetto per-GW di ogni asse (segno del
residuo globale/per-ruolo/per-manager, capitano, esito arena), così su più GW
si vede subito cosa è **stabile di segno** (azionabile) e cosa è rumore.

## 4. Scelte fissate (cleanest, 04/08)
1. **Cartella**: `analisi_manager/` è la home del filone (metodologia + analisi
   + report + indice). I dati grezzi dei manager restano dove li scrive
   `ricostruisci_manager` (`dati_globali/manager_*.json`, già versionati).
2. **Baseline lift**: slot medio **51.8** (zero query in più). Il pool-di-lega
   resta come raffinamento futuro se serve.
3. **Formato dataset**: **JSON** finché l'accumulo è piccolo; si passa a CSV se
   cresce troppo.
4. **Priorità assi su GW1**: A (selezione) + B (capitano) + D (esito arena) +
   F (skill per manager) + G (coda positiva). Il resto si aggiunge dopo.
