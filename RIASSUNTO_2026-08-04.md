# Sessione 4 agosto 2026 — fix leak, generatore vero nel backtest, bilancio pulito, capitano

---

# ⇢ RIPARTIRE DA QUI (05/08) — leggere solo questo blocco per riprendere

## Dove siamo arrivati
Due sessioni sul CAPITANO, poi il metro applicato a TUTTE le decisioni, e
infine la dimostrazione che chiude l'intero ragionamento:

> **Massimizzare il PREMIO atteso e' identico a massimizzare i PUNTI attesi.**
> 5768 confronti, 0 contraddizioni (100% concordanza). L'incertezza su una
> formazione e' ~50 punti su ~280: integrare una funzione premio a gradini
> su quel rumore la rende MONOTONA. La non linearita' del premio — la leva
> teorica dietro tutto cio' che abbiamo provato — **in pratica non esiste**.

Conseguenza: **le REGOLE DI DECISIONE sono un vicolo cieco, dimostrato**.
La regola attuale del bot (massimizza i punti attesi) e' gia' quella giusta.

## Il numero da cui ripartire — il tasso di cambio
```
   10 punti attesi in piu' = +46.9 essenze attese per arena
   ~4.7 essenze per ogni punto di previsione guadagnato
```
Converte accuratezza del modello in denaro. **L'unica leva rimasta e' la
PRECISIONE DELLA PREVISIONE**, non le regole di decisione.

## PROSSIMO PASSO deciso con l'utente
Capire **dove il modello sbaglia di piu'** e attaccare quello: l'errore sul
totale formazione e' sigma=49.4 punti, ogni punto recuperato vale ~4.7
essenze/arena. Da fare: scomporre l'errore (per ruolo, per lega, per fascia
di punteggio, per profondita' di storico) per trovare dove si concentra.
NB `taratura_confronto_parametri.py` e la regola MAE+correlazione+lift
restano il metro per validare qualunque modifica al modello.

## NON RIAPRIRE (misurato e chiuso in questa sessione)
- Capitano: 12 ipotesi, tutte inerti. La decisione vale ~1-2 pt su 280 e
  cambia il premio in <2% delle arene. `pick_captain()` resta com'e'.
- Capitano diverso per tipo di competizione (arene vs In-Season): nessuna
  differenza.
- Formazione concentrata per sfruttare il capitano: correlazione -0.006.
- Allocazione/soglie: premio atteso == punti attesi (sopra).
- Maledizione del vincitore: assente, chiude la famiglia "shrinkage".

## Trappole trovate qui, da non ricascarci
- **Le carte non si clonano**: se ogni arena sceglie dal pool del giorno in
  modo indipendente, le stesse 5 carte finiscono in tutte le ~10 arene →
  +132 essenze/arena di finto vantaggio. Mazzo fisso, sempre.
- **Col mazzo fisso i punti sono CONSERVATI**: un oracolo che massimizza i
  punti riallocando non ottimizza nulla (usciva peggio dell'utente).
- **L'oracolo non e' un obiettivo**: e' chiaroveggente, il suo margine e'
  quasi tutto fortuna. Vale il confronto relativo fra decisioni.
- **Misurare il valore della decisione PRIMA di cercare euristiche**: il
  capitano e' costato due sessioni per questo.

## Script pronti (tutti senza query, cache su disco)
- `formazione_mls/diagnostics/backtest_captain_policy.py` — 3130 formazioni
  reali (mie + forever-young + crowss) + diagnostica di metodo (headroom,
  maledizione del vincitore, compressione di scala b=1.53).
- `formazione_mls/diagnostics/headroom_decisioni.py` — pavimento/caso/
  attuale/oracolo per ingresso, carte, capitano (⚠ riga CARTE non valida,
  avviso nello script).
- `formazione_mls/diagnostics/selezione_carte.py` — riallocazione a mazzo
  fisso, 443 arene, essenze vere.
- `formazione_mls/diagnostics/allocazione_premio_atteso.py` — premio atteso
  vs punti attesi + la diagnostica che chiude il filone.
- `formazione_mls/diagnostics/captain_per_competizione.py` — arene vs
  classifiche grandi, e `CurvaRank` (punteggio→piazzamento per famiglia).
- Cache previsioni in `%TEMP%/captain_risultati_cache.json` (rigenerare con
  `--ricalcola`, ~2 min).

## Stato del codice
**Nessuna modifica al modello o al bot in tutta la sessione.** Solo script
diagnostici e questo documento. Tutto committato su main.

---

## FILONE CAPITANO DEF/MID/FWD — CHIUSO, nessuna modifica al codice

Tre ipotesi testate, tutte negative (la regola attuale, "capitana per atteso
del modello", resta la migliore misurata):

1. **Bias per ruolo** (DEF/MID/FWD) — bias reale ma lift ~zero nella policy
   vera. Dettagli sotto.
2. **Volatilita' del singolo giocatore** (dev_std storica pesata, stesso dato
   gia' calcolato da ogni test_<ruolo>.py per il range di confidenza,
   nessuna nuova query): bias per bucket di volatilita' (zona capitano,
   atteso>=55, n=2019/2020/2020) — bassa -6.58, media -6.79, **alta -8.37**
   (freq. crollo 8.9% contro 6.3% delle altre due). Gap bassa-vs-alta
   +1.80pt, PIU' PICCOLO del gap DEF-vs-MID (2.37pt) che aveva gia' dato
   lift zero — non testata la policy per questo (segnale troppo debole per
   valere il tempo, dato il precedente). Script:
   `formazione_mls/diagnostics/analyze_captain_bias_variance.py` (committato).
3. **Forma recente grezza (L40/L10/L5) al posto dell'atteso del modello**:
   su 1798 formazioni reali (513 mie + 1285 di forever-young, walk-forward,
   nessuna nuova query) — L10 e L5 chiaramente PEGGIO dell'atteso
   (-0.164 e -0.377 pt/formazione). L40 sembrava leggermente meglio
   (+0.074 pt/formazione) ma l'IC 95% bootstrap è [-0.15, +0.31]: include lo
   zero, non distinguibile dal rumore (conferma diretta: L40 vince 390 volte,
   perde 379, quasi simmetrico). **Nessuna euristica di forma batte
   l'atteso del modello.** Script non salvato (era solo verifica puntuale,
   vedi in fondo per rifarlo).

Bias di ruolo misurato (vedi sotto), POI verificato con un backtest della
policy vera (non solo il bias astratto): su 513 formazioni reali storiche
(tutte quelle in `arene_formazioni.json`, walk-forward, nessuna nuova
query), capitanare per "atteso corretto per bias di ruolo"
(`atteso + BIAS[ruolo]`, BIAS = DEF -8.37/MID -6.00/FWD -7.37) invece che
per atteso grezzo cambia la scelta nel 17.3% dei casi (89/513, sposta molto
il mix: MID 48.1%→63.9%, DEF 32.2%→19.7%) ma il bonus capitano REALE
catturato è quasi identico: +6.3 punti totali su 513 formazioni
(+0.012 pt/formazione) — rumore, non un guadagno vero. Per la regola del
CLAUDE.md (MAE+correlazione+lift insieme) il lift qui è ~zero:
**`pick_captain()` NON va toccato per DEF/MID/FWD.** Resta valida solo
l'esclusione del portiere, già in produzione (GK_CAPTAIN_MARGIN).

Dettaglio della misura del bias (primo passo, poi superato dal test sopra):

L'utente è già convinto di **escludere il portiere** dalla scelta capitano
(non solo penalizzarlo col margine GK_CAPTAIN_MARGIN=6.7,
`formazione_mls/build_formazione_finale.py:1445-1467`). Restava da capire se
tra i 4 slot rimanenti (oggi `pick_captain()` sceglie DEF/MID/FWD solo per
atteso grezzo più alto, nessuna correzione di ruolo) uno dei tre ruoli
sovra/sottostimi il reale piu' degli altri nella "zona capitano" (atteso≥55),
come succede per GK.

**Test fatto**: `formazione_mls/diagnostics/analyze_captain_bias_outfield.py`
(nuovo file, committato), riusa la raccolta dati di `analyze_gk_captain_value.py`
(nessuna nuova query, parametri ufficiali di produzione). Esteso anche
`analyze_gk_captain_value.py` per scoprire automaticamente TUTTE le 53 leghe
(prima ne usava solo 10 su una lista fissa — buco scoperto dall'utente,
mancavano Francia/Germania/Inghilterra/Italia/Giappone/Turchia e altre 17).

**Risultato (53 leghe, zona capitano atteso≥55)**:
  DEF n=2294 bias=-8.37  MID n=2213 bias=-6.00  FWD n=1552 bias=-7.37
  Gap DEF vs MID: -2.37pt (per confronto, il gap GK-vs-movimento che ha
  giustificato GK_CAPTAIN_MARGIN era +6.69pt — qui e' circa 1/3).

**COSA DICE E COSA NON DICE QUESTO TEST (richiesta esplicita dell'utente,
non equivocare)**: dice solo che, IN MEDIA, il DEF non è il ruolo migliore
da capitanare rispetto a MID/FWD — un bias osservato su tutte le partite
della fascia, non una regola operativa. NON dice:
- se un margine/correzione applicato davvero a `pick_captain()` migliori il
  risultato reale (serve un backtest della POLICY, non solo il bias astratto);
- se il gap sia stabile per singola lega/periodo o sia una media che nasconde
  variazione forte (es. potrebbe essere trascinato da poche leghe/giocatori);
- cosa succeda ai casi non-DEF/MID/FWD-puri (es. formazioni dove il migliore
  per atteso NON è comunque un DEF/MID/FWD "tipico" della zona capitano).

Script del backtest della policy: era in `_tmp_policy_backtest.py`, cancellato
a fine sessione (non salvato nel repo, era solo verifica puntuale). Se serve
rifarlo: stessa logica di `analyze_captain_bias_outfield.py` per i dati, poi
per ogni formazione reale in `arene_formazioni.json` confrontare
`max(atteso)` vs `max(atteso + BIAS[ruolo])` fra i 4 movimento e sommare il
bonus reale (0.2×reale del capitano scelto) sulle formazioni vere.

Script del test L40/L10/L5 (punto 3 sopra): stessa idea, ma il capitano si
sceglie per `max(L40)`/`max(L10)`/`max(L5)` invece che per atteso o atteso
corretto. L40/L10/L5 si calcolano dal game log gia' in cache (`cache.gamelog`,
media degli ultimi N punteggi validi con data < cutoff — stessa logica del
calcolo L10 gia' in `backtest_arene_previsioni.score_atteso`, generalizzata a
N=40/10/5). Per allargare il campione, unire le formazioni di
`arene_formazioni.json` (mie, 593) con quelle di
`dati_globali/manager_forever-young.json` (`d['giornate'][fixture]`, ogni
voce con `carte`+`piazzamento`, ~3326 con carte) sulla stessa giornata/cutoff
— dà ~1800 formazioni valutabili invece di ~513. Significativita' con
bootstrap sulle differenze per-formazione (stesso approccio di
`intervallo_media()` in backtest_arene.py).

## FILONE CAPITANO — 4 idee nuove testate (04/08 sera), TUTTE CHIUSE, nessuna modifica

Richieste esplicite dell'utente dopo la chiusura sopra: margine-soglia,
stabilità per lega, più potenza statistica, fattore favorita/sfavorita.
Nuova harness riusabile `formazione_mls/diagnostics/backtest_captain_policy.py`
(riusa `P.score_atteso`/`B.inizio_giornata`/`B.fine_giornate`, nessuna nuova
query) che unisce 3 fonti di formazioni reali: mie (513 valutabili),
forever-young (1285) e **crowss** (1332, mai usato prima — trovato in
`dati_globali/manager_crowss.json`, manager Korea-centrico) — **3130
formazioni reali totali**, 6x il campione precedente.

1. **Stabilità del bias di ruolo per lega** (`analyze_captain_bias_by_league.py`,
   nuovo, committato): il gap DEF-vs-MID (zona capitano) ha lo stesso segno
   (DEF peggio) in 11/12 leghe misurabili, gap medio -2.28pt vicino
   all'aggregato -2.37pt. **Non è un artefatto di poche leghe** — il bias è
   reale e stabile, ma resta troppo piccolo per generare lift.
2. **Bias di ruolo su campione 6x più grande**: stesso identico test già
   bocciato su 513 formazioni, rifatto su 3130 → lift +0.0398 pt/formazione,
   IC95% bootstrap [-0.059, +0.138] — **include lo zero**. Il campione più
   grande CONFERMA il rumore, non era un problema di potenza statistica.
3. **Bias di ruolo applicato solo nei casi "in bilico"** (grid soglie
   3/5/8/12/20pt sul margine tra i top-2 candidati): risultato **identico**
   a "sempre applicato" per OGNI soglia. Non e' un bug: il differenziale
   massimo tra i bias di ruolo (DEF vs MID = 2.37pt) e' già più piccolo di
   qualunque soglia testata, quindi il correttivo non può mai ribaltare una
   scelta con margine ampio — il gating è matematicamente inerte qui.
4. **Fattore favorita/sfavorita** (`opp_rank`, già dentro l'atteso di
   produzione via `P.contesto()`): bias residuo nella zona capitano diviso
   in terzili — FAVORITO (avversario debole) +8.58, NEUTRO +6.41, SFAVORITO
   +6.43 (gap FAVORITO-vs-resto +2.15/+2.17pt, stesso ordine di grandezza
   del ruolo). Testato come policy (bonus +2.17 se favorito): lift
   +0.0688 pt/formazione, IC95% **[-0.0015, +0.1411]** — il più vicino a
   uscire dal rumore delle 4 idee, ma il limite inferiore resta (di un pelo)
   sotto zero. Per la regola del CLAUDE.md non basta.

**Verdetto**: nessuna delle 4 idee supera la soglia per toccare
`pick_captain()`. La più promettente è la 4 (favorita/sfavorita) — se in
futuro si aggiunge altro campione reale (altri manager) vale la pena
rifare SOLO questo test prima di chiuderlo definitivamente; le altre 3 sono
chiuse con margine più netto. Script nuovi committati:
`formazione_mls/diagnostics/analyze_captain_bias_by_league.py`,
`formazione_mls/diagnostics/backtest_captain_policy.py`.

## FILONE CAPITANO — round 2, altre 4 idee (04/08 notte), TUTTE CHIUSE

Richieste ancora dall'utente dopo il round sopra. Stessa harness
(`backtest_captain_policy.py`), esteso con 3 nuovi segnali per candidato:
`partite_storiche` (gia' in `score_atteso`), tasso di "uscita precoce"
storica (mins_played<60, da `cache.dettagli`), gol totali attesi della
partita (nuovo `modello_partita.py` non ancora tracciato — Poisson
attacco/difesa/campo, checkpoint settimanali walk-forward, stesso pattern
gia' in produzione per `_pcs_squadra`/GK clean sheet).

- **A) Favorita+ruolo combinati**: peggio della favorita da sola
  (+0.042 pt/formazione, IC ancora piu' largo) — il bias di ruolo (gia'
  nullo) diluisce il segnale, non lo rinforza.
- **B) Bias per profondita' di storico** (poco/medio/molto storico,
  zona capitano): nessun pattern monotono (poco storico +7.91, medio +6.47,
  molto +6.69) — segnale debole/incoerente, non testato in policy.
- **C) Rischio "sostituito presto"** (mins_played<60 storico): degenere —
  quasi tutti i candidati in zona capitano hanno tasso 0 (chi ha un atteso
  alto e' quasi sempre chi gioca tutta la partita), i terzili collassano.
  Nessun segnale da testare.
- **D) Ambiente gol della partita** (gol totali attesi squadra+avversario,
  dal nuovo modello Poisson): il bias grezzo per bucket sembrava forte
  (partita APERTA +10.80 vs CHIUSA/MEDIA +5.17, gap +5.6pt — il piu' grande
  misurato finora) MA **testato come policy il lift e' NEGATIVO**
  (-0.092 pt/formazione, IC95% [-0.20, +0.02], gating per margine non lo
  salva). Conferma diretta della trappola gia' vista col bias di ruolo: un
  bias marginale forte non implica un buon criterio di SCELTA tra candidati
  della stessa formazione — qui il bonus spingeva verso ruoli/partite "calde"
  anche quando il vero miglior atteso era altrove.

**Verdetto**: chiuse tutte e 4, nessuna tocca `pick_captain()`. Il filone
capitano resta con la regola attuale dopo 8 ipotesi testate in due round
(vedi anche la sezione sopra); l'unico segnale mai arrivato vicino alla
significativita' è la favorita/sfavorita (round 1, IC95% [-0.0015,+0.14]).

## FILONE CAPITANO — DIAGNOSTICA DI METODO (04/08 notte, la parte che conta)

Dopo 8 ipotesi tutte negative, invece di provarne una nona abbiamo misurato
**il problema invece delle soluzioni** (`diagnostica_di_metodo()` in
`backtest_captain_policy.py`). Tre numeri mai guardati prima:

**1. HEADROOM — quanto vale l'INTERA decisione capitano** (3130 formazioni):
```
  peggior candidato (pavimento)    7.04 pt/formazione
  candidato a CASO                12.07
  REGOLA ATTUALE (max atteso)     13.11
  ORACOLO (max reale, tetto)      17.39
```
La regola attuale batte il caso di **+1.04 pt/formazione** e azzecca il
miglior candidato nel **32.4%** dei casi contro il 23.7% del caso puro: il
modello ordina, e ordina meglio del caso. Il "margine residuo" di +4.28 fino
all'oracolo **NON è un obiettivo raggiungibile**: il divario caso→oracolo
(+5.33) è per costruzione indipendente dall'atteso, cioè è interamente la
dispersione casuale del massimo fra 4 punteggi reali — è il valore della
CHIAROVEGGENZA, non di una migliore euristica. Su una formazione da ~280 pt,
l'intera partita si gioca su ~1-2 punti: **spiega perché 8 ipotesi di fila
hanno dato lift ~0 — non erano ipotesi sbagliate, è il premio a essere
piccolo**.

**2. MALEDIZIONE DEL VINCITORE — assente.** Tutti i bias finora erano
misurati su TUTTI i candidati, mai CONDIZIONATI all'essere stati scelti: ma
argmax su una stima rumorosa tende a selezionare chi è stato sovrastimato.
Misurato: bias del candidato scelto +5.86 contro +5.47 di tutti i candidati,
differenza **+0.39 pt, IC95% [-0.35,+1.14]** → nessuna distorsione da
selezione. Chiude in blocco l'intera famiglia "shrinkage / penalizza le
stime inaffidabili" senza doverla testare una per una.

**3. SCALA — l'atteso è COMPRESSO 1.53x.** Pendenza reale~atteso in zona
capitano: **b=1.53**, cioè 1 pt di differenza di atteso vale 1.53 pt di
differenza reale. Difetto comune a TUTTE le correzioni testate: sommare un
bonus misurato in punti reali direttamente all'atteso lo sovradimensiona.
Ri-testata su griglia di scala la sola favorita/sfavorita: il lift disegna
una **U rovesciata** con picco a x1.5 (bonus +3.25 invece di +2.17) →
+0.094 pt/formazione, IC95% [+0.013, +0.174], poi decresce e diventa
negativo a bonus grandi. La forma a U rovesciata è quella di un segnale
vero (non di un artefatto monotono).

**MA NON VA APPLICATO COSÌ**: il picco è stato scelto guardando gli stessi
dati su cui è misurato, dopo ~30 confronti di policy — esattamente la
trappola "tarare su una misura rumorosa" già costata cara (vedi
`feedback_fix_generali_non_tarati_sul_test`). Prima di toccare
`pick_captain()` serve una **validazione fuori campione**: tarare il fattore
su forever-young+crowss e verificarlo sulle formazioni dell'utente (o split
temporale). Finché non passa quello, `pick_captain()` resta com'è.

## CAPITANO PER TIPO DI COMPETIZIONE (04/08 notte, richiesta esplicita utente)

Il punto 1 della lista sotto, eseguito — ed **esteso alle competizioni
In-Season/classifica, non solo alle arene** come chiesto dall'utente.
Script nuovo: `formazione_mls/diagnostics/captain_per_competizione.py`.

**Il dato era piu' ricco di quanto pensassimo**: nei dataset manager il
campo `piazzamento` non e' un numero ma `{rank, punteggio}` — quindi
abbiamo posizione E punteggio reale per ogni formazione, in ogni
competizione. Da qui, due mondi ben distinti (classificati dal rank massimo
osservato, non da una lista di nomi):
- **ARENE** (Arena/Cap 260/Cap 220/Beginner): campo da 10, rank 1-10.
- **CLASSIFICHE GRANDI** (All Star, Limited, Under 23, Challenger, LALIGA,
  Champion, Hot Streak...): fino a ~59.000 manager.

**Metodo**: curva empirica punteggio→piazzamento per famiglia (k-vicini,
media geometrica dei rank), poi a parita' di 5 carte si cambia capitano, si
ricalcola il totale e si legge il nuovo piazzamento. Policy testate:
`atteso + k*volatilita'` con k da -0.60 a +0.60 (k>0 = cerca varianza).

**Risultato ARENE — segno concorde, magnitudine trascurabile.** Tutte e 4
le famiglie preferiscono k>0 (capitano piu' volatile): Beginner +0.15,
Cap 260 +0.60, Arena-Limited +0.60, cap260-mie +0.30; e su Arena-Limited
k=-0.60 e' significativamente PEGGIO. Coerente con la teoria (in un campo
da 10 con premio ai primi 3 sei spesso a meta' classifica e ti serve il
salto). **Poi la misura ESATTA, senza surrogati** (468 arene dell'utente
con i 10 punteggi veri del campo e i premi veri, via `E.piazzamento`/
`E.premio`):
```
  baseline (max atteso)     244.7 essenze/arena
  atteso -0.30*volatilita    -0.64/arena
  atteso +0.15*volatilita    +1.60/arena  IC95% [+0.00,+4.27]
  atteso +1.00*volatilita    +1.60/arena  IC95% [-0.96,+4.81]
  ORACOLO (max reale)       +15.71/arena
```
Il segno conferma (varianza meglio, prudenza peggio) ma vale **+1.6 essenze
su 245, lo 0.6%**, e nessun IC esclude davvero lo zero. Il perche' e' il
numero piu' istruttivo di tutta la sessione: **cambiando capitano il PREMIO
cambia solo in 3-9 arene su 468** (<2%). Il capitano quasi mai sposta
l'esito attraverso un confine di premio.

**Risultato CLASSIFICHE GRANDI — misto e con strumento debole.** 3 famiglie
su 5 preferiscono k<0 (LALIGA -0.60 significativo, All Star -0.60, Under 23
-0.15), 2 preferiscono k>0 (Challenger, Limited): nessuna storia coerente.
**E la misura li' e' poco affidabile**, va detto: la curva punteggio→rank
sbaglia di 0.30-0.75 in log-rank (fattore 1.4-2.1x sul piazzamento) contro
0.15-0.24 delle arene, e soprattutto **il log-rank non e' denaro**: in una
classifica da 60.000 i premi stanno solo in cima, quindi guadagnare
posizioni a meta' gruppo non vale nulla ma il nostro indicatore lo premia.

**VERDETTO**: nessuna prova che la regola del capitano debba cambiare in
base alla competizione. `pick_captain()` resta unico e invariato. La
spiegazione unifica tutta la sessione: il capitano cambia il premio in meno
del 2% dei casi, quindi non esiste una regola — per quanto raffinata — che
possa spostare molto.

**Cosa servirebbe per chiudere davvero il lato In-Season**: le tabelle
premi per fascia di rank delle competizioni a classifica (quali posizioni
prendono cosa). Non le abbiamo: senza, il lato "classifiche grandi" resta
misurato con un surrogato invece che in premi veri.

## HEADROOM DI TUTTE LE DECISIONI (04/08 notte) — DOVE SONO I SOLDI

Scelto dall'utente dopo il capitano. Stesso metro (pavimento/caso/attuale/
oracolo) applicato a TUTTE le decisioni invece che solo al capitano, nella
stessa moneta: **essenze per arena**, su 443 arene reali dell'utente col
campo vero da 10 punteggi e i premi veri (`E.piazzamento`/`E.premio`,
nessuna modellazione). Script: `formazione_mls/diagnostics/headroom_decisioni.py`.

```
                    PAVIMENTO    CASO   ATTUALE  ORACOLO   MARGINE RESIDUO
  1. INGRESSO         -150.8      7.3     19.4     165.3        +145.9
  2. CARTE            -217.4     -3.5     14.8     580.5        +565.6
  3. CAPITANO          -10.2      9.9     14.6      30.0         +15.5
```

**ATTENZIONE — LA RIGA "CARTE" DI QUESTA TABELLA E' SBAGLIATA.** Corretta
poche ore dopo (vedi sezione successiva): li' ogni arena sceglieva dal pool
INDIPENDENTEMENTE dalle altre, quindi le stesse 5 carte migliori finivano in
tutte le ~10 arene dello stesso giorno — nella realta' le carte non si
clonano. Il valore valido non e' +565.6 ma **+101.7** (misura con mazzo
fisso, `selezione_carte.py`). Lo script stampa ora un avviso su quella riga.
Le righe INGRESSO e CAPITANO restano valide (non spostano carte fra arene).

**IL RISULTATO (con la correzione)**: INGRESSO ~+146 e CARTE ~+102 hanno
entrambe circa 7-9 volte il margine del capitano (+15.5). Il capitano non
era un filone sfortunato: era il piu' piccolo dei tre, e ci abbiamo speso
due sessioni.

**Cautele, da non dimenticare quando si usera' questo numero**:
- L'oracolo e' chiaroveggente e gonfiato dalla fortuna (massimo su tante
  alternative rumorose), tanto piu' quanto piu' e' grande il pool: per le
  CARTE si sceglie fra ~49 carte, quindi +565 e' un limite superiore molto
  largo, non un obiettivo. Vale il confronto RELATIVO fra decisioni, non il
  valore assoluto.
- Tutti gli IC su "guadagnato sul caso" includono lo zero (n=443, premi a
  scatti): in essenze non possiamo dimostrare che le regole attuali battano
  il caso. Non e' una bocciatura, e' poca potenza statistica.
- Due bug trovati e corretti nel primo tentativo su CARTE (il campione di
  combinazioni non era casuale ma ordinato per punteggio; il pool mescolava
  carte fra tipi di arena diversi, permettendo un fuoriclasse da uncapped
  dentro una Beginner). I numeri sopra sono quelli dopo la correzione.

## SELEZIONE DELLE CARTE (04/08 notte) — e la scoperta dei punti conservati

Aperto su scelta dell'utente. Script: `formazione_mls/diagnostics/selezione_carte.py`.
Prima domanda posta di proposito NON su un'euristica ma su **serve il
modello?**, con un controllo brutale: scegliere le carte solo per L10 (il
dato che Sorare stessa mostra, zero modello).

**Due errori miei, trovati e corretti — vanno ricordati perche' sono la
trappola di questo filone**:
1. *Le carte non si clonano.* Primo tentativo: ogni arena sceglieva dal pool
   del giorno indipendentemente → il modello metteva le stesse 5 carte
   migliori in tutte le ~10 arene, l'utente doveva spalmarle. Dava
   **+132 essenze/arena di finto vantaggio**. E' la "riallocazione libera
   del pool" gia' bocciata dall'utente. Corretto: mazzo fisso, ogni carta
   usabile al massimo quante volte l'utente l'ha usata quel giorno.
2. *Assegnazione greedy che si incastra*: servire le arene in sequenza dallo
   stesso mazzo faceva fallire l'86% dei casi. Sostituita da una
   riallocazione che parte dall'assegnazione VERA dell'utente (sempre
   fattibile) e scambia carte dello stesso ruolo fra arene.

**LA SCOPERTA (il pezzo concettuale che serviva)**: col mazzo fisso la somma
dei punti e' **CONSERVATA** — spostare carte fra arene non crea un solo
punto. Se ne e' accorto il primo oracolo, che massimizzando i PUNTI usciva
peggio dell'utente (-13.2): stava ottimizzando una quantita' costante.
Quindi **la leva della selezione non e' "prendere carte piu' forti" ma
"distribuire i punti contro le soglie delle arene"**: concentrare quanto
basta a vincere le arene vincibili, non sprecare punti dove si vincerebbe
comunque o non si vincerebbe mai. E' lo stesso tema (premio non lineare)
che era rimasto il piu' grande mai testato.

**Risultati** (443 arene, essenze vere, mazzo fisso):
```
  CASO (riallocazione a caso)         3.4
  SOLO L10 (nessun modello)           5.0
  MODELLO (max atteso)               22.0
  UTENTE (schierate davvero)         14.6
  ORACOLO sui PREMI                 116.3
```
Il modello sta sopra tutte le politiche realistiche (+7.4 sull'utente,
+17.0 sul solo-L10, +18.6 sul caso) ma **nessun IC esclude lo zero**: con
443 arene e premi a scatti non si dimostra. Il margine residuo verso
l'oracolo e' **+101.7/arena**, ~7x il capitano — ma l'oracolo qui e' una
ricerca locale fatta direttamente sull'esito realizzato, quindi molto
gonfiata dalla fortuna: e' un tetto larghissimo, non un obiettivo.

**PROSSIMO PASSO NATURALE**: una politica che ottimizzi il PREMIO ATTESO
invece dei punti attesi. FATTO subito dopo — vedi sezione seguente, che
chiude l'intero ragionamento della sessione.

## PREMIO ATTESO vs PUNTI ATTESI — SONO LA STESSA COSA (la chiusura)

`formazione_mls/diagnostics/allocazione_premio_atteso.py`. Implementata per
davvero la politica che massimizza il PREMIO ATTESO in essenze invece dei
punti: campo avversari stimato dalle arene dello stesso tipo concluse PRIMA
di quella giornata (walk-forward stretto), P(rank) binomiale dato F(s)
empirico, integrazione su s ~ Normale(atteso, sigma).

**Non batte i punti attesi**: -5.4/arena, IC95% [-42.6,+29.6] (399 arene).
E la diagnostica dice PERCHE', in modo definitivo:

```
  sigma sul totale formazione: 49.4 punti (su formazioni da ~280)
  coppie in cui piu' punti attesi = piu' premio atteso: 5768/5768 (100.0%)
  coppie in cui i due obiettivi si contraddicono:          0/5768  (0.0%)
```

**Con quel rumore, il premio atteso e' una funzione STRETTAMENTE MONOTONA
dei punti attesi.** Integrare la funzione premio (a gradini) su un'incertezza
di ~50 punti la liscia fino a renderla monotona: la non linearita' del
premio — che era la leva teorica dietro TUTTO quello che abbiamo provato in
questa sessione — in pratica non esiste.

**Questo chiude in blocco, con una dimostrazione e non con una serie di
tentativi falliti**: capitano volatile quando sei sotto soglia, allocazione
consapevole delle soglie, qualunque strategia "a gradini". Se massimizzare
il premio atteso equivale a massimizzare i punti attesi, allora la regola
attuale del bot (massimizza i punti) **e' gia' quella giusta**, e non c'e'
nessuna raffinatezza di decisione che possa aggiungere qualcosa.

**IL NUMERO DA PORTARSI VIA — il tasso di cambio**:
```
  10 punti attesi in piu' = +46.9 essenze attese per arena
```
Cioe' **~4.7 essenze per ogni punto** di previsione guadagnato. E' la
conversione fra accuratezza del modello e denaro, e dice dove investire:
non nelle REGOLE DI DECISIONE (capitano, allocazione, soglie — tutte
misurate e tutte inerti) ma nella **PRECISIONE DELLA PREVISIONE**. Un punto
di MAE in meno sul totale formazione vale piu' di tutte le euristiche
provate in due sessioni messe insieme.

## FORMAZIONE COSTRUITA PER IL CAPITANO — CHIUSA, nulla

Seconda scelta dell'utente. Ipotesi: siccome il capitano moltiplica UNA
carta, a parita' di budget (il cap L10) conviene concentrarlo su un
fuoriclasse + 4 riempitivi invece di 5 carte equivalenti? Misurato solo
sulle arene CON cap (senza tetto non c'e' compromesso) e solo sulle
formazioni che usano >=90% del budget, correlazione fra concentrazione
(L10 della carta piu' forte / somma L10) e punteggio reale, mediata per
arena: **-0.006, IC95% [-0.029,+0.018], 51% di arene positive**. Zero
perfetto. Concentrare o spalmare e' indifferente.

### Cosa resta DAVVERO non testato (in ordine di valore atteso)
1. **L'obiettivo è sbagliato**: misuriamo punti, ma il premio dell'arena è
   una funzione a gradini del RANK. Con un payoff a soglia la varianza ha
   valore (se sei sotto soglia il capitano volatile ti serve; se sei sopra
   ti danneggia). Riformula da capo la domanda sulla volatilità, chiusa in
   round 1 come "bias" — che era la domanda sbagliata. Fattibile con
   quello che c'è: `arene_storico.json` ha i 10 punteggi reali del campo e
   `E.piazzamento`/`E.premio` esistono già.
2. **Il backtest è cieco al rischio più grande della realtà**: contiene solo
   carte che HANNO giocato (p_gioca=1 per costruzione). In produzione un
   capitano che non scende in campo costa ~14 pt di bonus — un ordine di
   grandezza più dei ±0.09 inseguiti finora. Nessuno degli 8 test poteva
   vederlo.
3. **Correlazione col resto della formazione**: capitanare chi gioca la
   stessa partita di altre tue carte concentra la varianza del totale. Mai
   guardato per il capitano (esiste solo per la costruzione formazione,
   `CROSS_TEAM_PENALTY_BY_PAIR`).

## Cosa è stato fatto oggi (tutto committato su main salvo dove indicato)

### 1) Fix del data leak nel backtest arene
`backtest_arene_previsioni.py`/`backtest_arene.py`: il cutoff per L10/storico
usava la data della partita-bersaglio del singolo giocatore invece
dell'inizio-giornata (primo kickoff fra tutte le carte usate quel giorno) —
un giocatore con 2+ partite nella stessa finestra-giornata vedeva risultati
della giornata stessa nella propria storia. Verificato: 17→0 carte
contaminate su football-1-5-may-2026.

### 2) Nuovo backtest agganciato al generatore VERO
`backtest_arene_produzione.py` (nuovo file). Prima versione (build_one_lineup
grezzo, priorità fissa inventata) bocciata dall'utente. Versione corretta:
chiama `generatore_formazioni/build_formazione_globale.py` per davvero —
calibrazione per ruolo (`calibra_riga`), struttura multi-lega (pool dedicato
per-lega + pool misto), `genera_arene_efficienti` chiamata una volta sola con
tutti i tipi insieme (decide da sola tipo/quantità in base alla resa attesa).
Beginner registrata come tipo economico a sé (`ARENA_BEGINNER`, soglia 264.1,
guadagno/punto 2.85, costo 100 — dati reali da `backtest_arene_economia.py`,
non inventati): senza questo, veniva confusa con cap260 (soglia simile,
guadagno molto diverso) e il confronto risultava falsato.

### 3) Bug di dati scoperto: arene multi-ingresso
Alcune arene vengono giocate più volte lo stesso giorno (stesso slug in
`arene_storico.json`, righe diverse con punteggi diversi), ma
`arene_formazioni.json` ne registra spesso **una sola**, e in almeno un caso
reale con `mio_score` disallineato dalla somma delle carte elencate
(363.88 dichiarato, carte che sommano 221.66 — probabile bug di scraping,
score abbinato al lineup sbagliato). `bilancio_stesse_carte()` scarta questi
casi con un controllo di integrità (somma carte vs mio_score, tolleranza
0.5pt) invece di fidarsi ciecamente.

### 4) Metodo di confronto definitivo: "stesse carte"
Deciso con l'utente dopo diversi tentativi scartati (riallocazione libera del
pool = troppo sporco, arbitrario quale carta va in quale arena). Metodo
finale, in `backtest_arene_produzione.bilancio_stesse_carte()`:
- Arene division (Korea/Belgio/Olanda/Turchia/MLS dedicate) **escluse del
  tutto**: quelle carte non esistono per il bot.
- Per ogni arena reale rimasta, il bot valuta le **stesse identiche 5 carte**
  che l'utente ha usato lì (mai altre). Decide solo entra/non entra
  (resa attesa = (atteso_capitanato - soglia) × guadagno/punto del tipo,
  economia REALE per tipo). Se entra, il capitano è scelto sull'atteso (può
  differire dal capitano reale dell'utente — verificato che è l'unica causa
  possibile di punteggi diversi a parità di carte).
- Se entra, il punteggio/rank/premio è quello VERO sullo stesso campo reale
  di 10 punteggi — nessun abbinamento arbitrario, nessuna riallocazione.
- Se salta, si sa comunque cosa avrebbe fatto (stesse carte = risultato
  certo): "risparmiate" (avrebbe perso) vs "occasione persa" (avrebbe vinto).

Risultato su football-1-5-may-2026 (28 arene valide): utente netto +2000,
bot netto (solo giocate) +1750, risparmio +100, occasione persa -50 →
**bot netto totale +1900** vs utente +2000 — quasi pari, differenza quasi
tutta nella scelta del capitano.

Batch completo 71 giornate (76 secondi): 354/673 arene utilizzabili (113
division escluse, 119 dati incoerenti/mancanti, resto senza previsione
walk-forward). **ATTENZIONE**: l'utente ha detto di aver giocato 870 arene
reali in totale, ma `arene_storico.json` ne ha solo 673 — buco di ~197 MAI
SPIEGATO, non ignorarlo se si riprende questo filone. Totale sulle 354:
utente netto -5400, bot netto totale +5800 — ma **non è il vero P&L
dell'utente** (quello è +13% ROI su 870 arene secondo l'utente), è solo il
risultato sul sottoinsieme testabile, probabilmente non rappresentativo
(le arene division escluse potrebbero essere le più profittevoli).

### 5) Trovato `dati_globali/manager_forever-young.json`
Dataset scaricato in precedenti sessioni, mai usato: le arene REALI di un
altro manager Sorare (forever-young), 71 giornate, 3352 righe, 3326 con
carte+piazzamento. Corrisponde al backlog aperto "walk-forward su
forever-young" (l'unico test che dice se il modello batte un manager vero,
non solo l'utente). **Manca il campo con tutti e 10 i punteggi del campo**
(solo rank/punteggio del manager stesso) — niente rank/premio ricostruibile,
solo confronto in punti.

Filtrate le sue arene a Cap 260/Cap 220/Uncapped (395, 388 con carte —
escluse Beginner e le arene per-lega dedicate, altri filoni mai aperti:
Under 23, In-Season, Champion/Challenger/Hot Streak per lega...). Confronto
stesse-carte-solo-punti: 157/388 valutabili (231 scartate, carte senza
storico sufficiente in cache — verosimile, mai processate dal modello
prima). Bot entra in 143/157. Sulle giocate: forever-young media 265.7,
bot media 266.6 (+0.9 pt/arena) — sostanzialmente alla pari, leggero
vantaggio bot specialmente su Uncapped (293.0 vs 284.1). 46/96 su cap260
hanno scelto lo stesso identico capitano (punteggio identico al centesimo,
matematicamente possibile solo così); sulle altre 50 le differenze sono
ampie (-11.2/+14.3) e quasi si compensano (30 volte meglio forever-young,
20 volte meglio il bot) → da qui è partito il filone capitano.

## Non committato / da verificare
- Buco 673 vs 870 arene reali dell'utente (vedi sopra) — MAI spiegato.
- Script per il confronto forever-young: solo in temp, cancellato a fine
  sessione — da riscrivere se si riprende il filone (logica: vedi punto 5).
