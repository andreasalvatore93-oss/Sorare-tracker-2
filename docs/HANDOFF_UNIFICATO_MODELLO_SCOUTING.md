# HANDOFF UNIFICATO — Modello Predittivo / Generatore Formazioni + Scouting Acquisti

**Questo è l'UNICO riassunto di riferimento per il tema "modello predittivo"
(= generatore formazioni, stesso strumento, nomi diversi per la stessa cosa)
e per il tema "scouting acquisti". Aggiornarlo, renderlo snello e digeribile
a ogni sessione — non crearne altri.** Regola fissata anche in CLAUDE.md.

Sostituisce e supera (non cancellati per storia, ma NON più da consultare
come riferimento corrente):
`docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` (8776 righe),
`docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`, `docs/HANDOFF_BEST_FIVE.md`,
`docs/HANDOFF.md` e gli `HANDOFF_*_2026-08-04.txt` in `docs/handoff/`.

Ultimo aggiornamento: **sessione 05/08/2026, sera (Roma, CEST)**.
Sessione: passaggio 2 P8 — composizione all-around per categoria misurata e
**CHIUSA senza modifiche** (§5); i 16 commit del passaggio 2 (P1-P9-ter, blend
GK `c` 17.5→22) sono **PUSHATI su `main`**. Sessione precedente: pattern arene
(§7) + validazione soglie cap 260 (σ 42.70→50.6, pareggio 265→259.5, guadagno
8.8→7.9), dettaglio in `analisi_manager/VALIDAZIONE_SOGLIE.md`. Regola di
stile: file SNELLO (max ~4 pagine), sessione/giorno/ora Roma.

---

## 1. Cos'è il progetto, in tre righe

L'utente (nickname Sorare **Crowss**) gioca a Sorare (fantacalcio con carte
NFT). Il repo contiene un **modello predittivo** che stima il punteggio di
ogni giocatore alla prossima partita, un **generatore di formazioni** che usa
quella previsione per costruire le formazioni ottimali su ~30 campionati, e
uno **strumento di scouting** che usa lo stesso modello per decidere cosa
comprare prima che le informazioni (starter odds) siano pubbliche. I due
strumenti condividono lo stesso "cervello" (previsione + calibrazione) e
**vanno sempre trattati insieme**: ogni modifica alla previsione, alla
calibrazione o alle soglie va verificata su ENTRAMBI (regola già in
CLAUDE.md). Il generatore ottimizza il mazzo posseduto, lo scouting decide
come il mazzo cresce — se divergono si comprano carte che poi non si
schierano bene.

Il modello è considerato **al suo tetto di formula**: il lavoro recente non
sta più migliorando `score_atteso`, ma misurando **dove va usato meglio**
(quali competizioni giocare, quando NON entrare, capitano, allocazione delle
carte) e **dove il modello sbaglia di più** (vedi §7).

---

## 1bis. LA CATENA DI PRODUZIONE — base di tutto, mai saltare un anello

```
VALORI DI PRODUZIONE (= predizione, stesso nome)
        |
        v
SOGLIE ARENA EFFICIENTI (pareggio/guadagno per punto)
        |
        v
TOOL SCOUTING (consiglio acquisti per una GW, basato sull'efficienza)
```

Se cambia un valore di produzione/predizione (formula, calibrazione,
parametro di un ruolo — qualunque cosa sposti `score_atteso`), le soglie di
efficienza delle arene (`PAREGGIO_ARENA`, `GUADAGNO_PER_PUNTO` in
`generatore_formazioni/build_formazione_globale.py`) NON si aggiornano da
sole: sono tarate su quei punti attesi, e vanno riverificate. Lo scouting a
sua volta consiglia gli acquisti proprio sull'efficienza (colonne
`Ess/GW`/`€/EssGW`, §2.2) — un cambio a monte non riverificato falsa i
consigli di acquisto a valle **in modo silenzioso**, senza nessun errore
visibile. Nessuna modifica alla produzione è chiusa finché non si è
ripercorsa la catena fino allo scouting incluso. Regola gemella anche in
CLAUDE.md.

## 2. Gli strumenti (due attivi, uno superato)

### 2.1 Generatore di formazioni (il "modello predittivo")

Per ~30 campionati tracciati, dato l'elenco delle carte possedute
dall'utente, produce le formazioni ottimali per competizione (In Season,
Arena, All Stars, Under 23) con capitano, rispettando i vincoli Sorare (max 1
Classic, min 4 In Season nelle In Season; cap L10 nelle arene con cap).

**Pipeline di produzione** (workflow GitHub `formazione_giornata.yml`,
riscritta 27-28/07 sulla GIORNATA invece che sui singoli campionati):
1. `discovery_fixture.py` — dalle partite della giornata risolve squadre in
   campo, tiene solo le carte possedute di quelle squadre, applica la soglia
   starter-odds. ~3 minuti invece di ~30.
2. `predict` — SOLO per i giocatori sopravvissuti (matrice dinamica: un
   campionato senza titolari probabili non genera job).
3. `consiglio` — per lega/ruolo, nello stesso job del predict.
4. `generatore_formazioni/build_formazione_globale.py` — fonde tutti i
   consigli, costruisce le formazioni per priorità (In Season → Arene
   dedicate/All Stars → Under 23 → All Stars), assegna capitano, pubblica
   report HTML + notifica Telegram.

Architettura per-lega (esempio `formazione_mls/`, stesso pattern su tutte le
leghe): `discovery/` (posseduti + globale pubblica), `predict/`
(`test_gk.py`/`test_def.py`/`test_mid.py`/`test_mls_fwd_all.py`, uno script
per ruolo), `consiglio/`, `output/` (per ruolo/scopo: `_all` produzione,
`_calibration` isolata, `_discovery`/`_discovery_global`).

**Formula di previsione** (identica nella struttura su tutti i ruoli/leghe):
```
score_atteso = P(gioca) x media_pesata_esponenziale(N partite)
               x fattore_casa_trasferta x fattore_trend
               [+ condizionamento avversario: opponent_lambda_mult, Stadio D]
range_confidenza = +/- dev_std_pesata x RANGE_MULTIPLIER
```
GK ha in più il blend con P(clean sheet) di squadra (§7). Gli **all-around**
entrano come UN SOLO scalare per partita, `score - level_score`
(`test_def.py:1951`), mediato con pesi `0.5**(età_in_partite/half_life)`
mascherati a zero sulle partite senza dettaglio (`:1398-1405`) e sommato a
`level_score_atteso` (`:1433`): **nessuna categoria Sorare entra
separatamente**. I "fattori granulari" per categoria (falli, duelli,
passaggio...) sono stati provati e **rimossi ovunque**, e la scomposizione per
categoria è stata rimisurata e bocciata anche in forma diretta: vedi §5.

**Parametri di produzione attuali (MLS, propagati a tutte le leghe via
`propaga_modello.py` — mai a mano sulle singole leghe, vedi CLAUDE.md)**:

| Ruolo | half_life | range_mult | opp_sens | trend_int |
|---|---|---|---|---|
| GK | 6.0 | 1.15 | 29.0 | 0.0 |
| DEF | 30.0 | 1.1 | 29.0 | 0.0 |
| MID | 25.0 | 1.1 | 29.0 | 0.0 |
| FWD | 6.0 | 1.15 | 29.0 | 0.0 |

`trend_intensity` a 0.0 ovunque: misurato più volte, monotono verso il
peggio, chiuso definitivamente il 03/08. `opponent_sensitivity=29.0` è
l'unico parametro mai risultato instabile in nessun ruolo/lega.

### 2.2 Scouting acquisti (`scouting_gw.py`)

Risolve il problema opposto al generatore: il generatore parte dalle carte
POSSEDUTE, per COMPRARE serve sapere con giorni di anticipo chi scenderà in
campo, comprese carte non possedute — prima che Sorare pubblichi le starter
odds (24-48h dal kickoff).

Trovato che la query giusta è `searchPlayers` (la stessa della pagina
"Scouting" di Sorare): una query paginata, ~12 chiamate/7 secondi, porta già
L5/L10/L40, presenze, infortuni, proiezione Sorare, carte possedute e prezzo
minimo — sostituisce 75 query di roster + migliaia di scrematura.

Output: `generatore_formazioni/output/scouting_ultimo.html` (committato,
notificato su Telegram), colonne `Ess/GW` = `(atteso − 51.8) × 7.65`
(vantaggio in essenze a giornata su uno slot medio) e `€/EssGW` = prezzo
diviso essenze-GW, che è la colonna giusta per **ordinare** i candidati (il
valore in euro dell'essenza non serve a scegliere fra candidati, è un
fattore comune). Workflow `scouting_gw.yml`, input `gameweek`/`per_ruolo`/
`odds_min`/`predict`/`screma`.

Riusa la cache del generatore (stessa cartella `<lega>_<ruolo>_all`) e il
meccanismo di riuso previsione ereditato da Best Five (§2.3): un giocatore
con previsione già scritta per la finestra della fixture corrente non
rigenera nemmeno il job.

### 2.3 Best Five / Contender (`best_five.py`) — SUPERATO, non più in uso

Tool precedente allo scouting attuale: per UNA lega (o N leghe unite per la
competizione "Contender"), generava la formazione ottimale scegliendo tra
tutte le carte della lega, non solo quelle possedute. **Ultima run reale
01/08/2026**; da quella data l'utente usa solo lo scouting acquisti (§2.2),
che ne è l'evoluzione — stesso bisogno (valutare carte non possedute),
soluzione migliore (`searchPlayers` invece di roster+scrematura per club).

`best_five.py` **non è stato cancellato**: `scouting_gw.py` lo importa
ancora come libreria per alcune funzioni (riuso previsione, render carte,
knapsack cheapest/valore, tooltip soglie arena — vedi i riferimenti
`_import(..., 'best_five.py')` nel codice). I workflow standalone
(`best_five.yml`, `best_five_contender.yml`) restano nel repo ma **non
vanno più lanciati**: se serve di nuovo un confronto per-lega su tutto il
pool, valutare prima se lo scouting lo copre già.

---

## 3. Le regole del gioco Sorare (nessuna deducibile dai dati — tutte date
dall'utente, fondamento di ogni calcolo)

**Arene**: 10 partecipanti, si paga un ingresso, i primi 3 vincono.

| tipo | ingresso | 1° | 2° | 3° |
|---|---|---|---|---|
| Beginner | 100 | 500 | 250 | 150 |
| cap 220 | 200 | 1000 | 500 | 300 |
| cap 260 (incl. dedicate a un campionato — stessa economia) | 300 | 1300 | 800 | 500 |
| uncapped | 300 | 1300 | 800 | 500 |
| elite (uncapped) | 800 | 4000 | 2000 | 1000 |

- Cap L10 (arene "cap 260"/"cap 220"): somma degli L10 delle 5 carte ≤ soglia.
  Uncapped/elite senza tetto — lì si schierano i fuoriclasse.
- Bonus arena: **solo capitano, +20%**. Nessun altro bonus (season/xp/scarcity
  ecc.) si applica in arena.
- **Le arene dedicate a un campionato** (MLS/K League/Belgio/...) hanno gli
  **stessi costo e premi** di una cap 260 normale — sono la stessa
  competizione, filtrata a un solo campionato. **Ora disattivate di default**
  nel generatore (§9).
- Fino a 3 proprie formazioni possono finire nello stesso pool da 10.

**In Season**: gratis, max 6 formazioni, min 4 carte In Season su 5. Due
meccanismi paralleli: **gradini** (340→500 essenze, 360→1000, 400→25€,
420→100€, 460→500€, uno solo conta a settimana) e **leaderboard** (una sola
formazione, ~3-6k manager, paga fino al ~500° a scalare).

**All Stars da 7 / Under 23**: gratis, nessun ingresso, pagano solo essenze,
difficili da vincere. Destinazione naturale delle carte che non superano il
pareggio di un'arena.

**Ciclo essenze**: 1000 essenze = 1 craft, produce SOLO carte In Season (mai
Classic). Arena → essenze → craft → carte In Season → competizioni in euro:
l'arena alimenta il gioco che paga in euro, misurarne il ROI in sole essenze
lo sottostima.

**Ruolo**: proprietà della CARTA, non del giocatore (Sorare può cambiare
ruolo lasciando alle carte già emesse quello vecchio).

**Bonus Sorare — si SOMMANO, non si moltiplicano** (verificato al centesimo,
04/08): `punteggio carta = grezzo × (1 + bonus_carta + bonus_formazione +
capitano)`. `bonus_carta` (season/collection/xp/scarcity/special
edition/active clubs/nationality/positions) e `bonus_formazione` (+2%
multi-club max 2 stesso club, +4% cap L10 sotto soglia, cumulabili) **solo in
In Season/All Star/Under 23, zero in arena**. Capitano +50% In
Season/All Star/Under 23, **+20% in arena**.

---

## 4. Dati costruiti (l'archivio su cui si misura tutto)

| file | contenuto |
|---|---|
| `dati_globali/arene_storico.json` | 673 arene reali dell'utente (giu 2025–lug 2026): tutti e 10 i punteggi, premi, piazzamento |
| `dati_globali/arene_formazioni.json` | 593 formazioni schierate: giocatore/carta/ruolo/capitano/punteggio |
| `dati_globali/manager_forever-young.json` | arene REALI di un altro manager (mazzo simile, non scelto per il risultato), 71 giornate, 3326 righe con carte |
| `dati_globali/manager_crowss.json` | arene di un manager Korea-centrico, 1332 formazioni usate nel filone capitano |
| `dati_globali/backtest_arene_cache/` | storico giocatori necessario per rigiocare le formazioni col modello |

ROI reale storico dell'utente: **+13.3%** (121.250 spese, 137.400 vinte),
39.7% a premio contro il 30% di un manager medio — **tutto a mano**, il
modello ha meno di due settimane di produzione, nessuna delle 673 arene è
una sua scelta: base di confronto pulita.

**Buco mai spiegato**: l'utente riporta 870 arene reali giocate in totale,
`arene_storico.json` ne ha solo 673 (~197 mancanti). Non ignorarlo se si
riprende il filone backtest.

---

## 5. Lo stato dell'arte — cosa è CHIUSO (non riproporre)

- **Scomposizione degli all-around per categoria: CHIUSA due volte, ora anche
  con misura diretta (05/08, P8)**. I "fattori granulari" per categoria erano
  già stati rimossi ovunque perché non battevano la media pesata semplice; P8 ha
  chiesto la domanda più pulita — *a parità di totale all-around, la
  ripartizione per categoria predice meglio il futuro?* — e la risposta è NO.
  Dati: 39.594 partite FINAL ≥60′, 2.164 giocatori, 26 leghe, dalle
  `.cache/*_detail_cache.json` già in casa (le categorie Sorare GENERAL/
  DEFENDING/POSSESSION/PASSING/ATTACKING/GOALKEEPING ci sono tutte: nessuna
  ri-estrazione servita). Walk-forward mensile, bootstrap appaiato su 36-41
  giornate. Composizione ricalibrata contro totale ricalibrato: DEF dMAE −0.045
  [−0.075;−0.020] e dcorr +0.0131 [+0.006;+0.022] ma **dlift −0.03 [−1.42;
  +1.31]**; MID dMAE −0.018, dcorr +0.005, **dlift −0.81**; FWD e GK nulli su
  tutte e tre. Forma additiva compatibile con la produzione (half-life diversa
  per categoria, interruttore verificato: a tutte 30 coincide con la produzione):
  **nulla su MAE e correlazione su tutti e 4 i ruoli**, e sul lift due risultati
  significativi di segno OPPOSTO fra ruoli (FWD +0.69, MID −0.76) = rumore.
  Metro a tre gambe non soddisfatto da nessuna forma: **nessuna modifica
  applicata**. Diagnosi del perché: dentro un ruolo le categorie che pesano
  hanno persistenze quasi identiche (MID: tutte fra +0.41 e +0.46), e dove c'è
  spread la categoria più persistente è anche la meno variabile (DEF: ATTACKING
  r +0.47 ma sd 2.2 contro POSSESSION sd 7.2). Sul GK, GOALKEEPING porta tutta
  la varianza (sd 9.0) ed è la meno persistente (+0.13) — coerente col fatto che
  ciò che decide è il clean sheet di SQUADRA. **Corregge l'indicazione lasciata
  da P3**: la compressione che P3 aveva trovato riguarda il DECISIVO
  (`level_score`, scala a gradini) e NON si trasferisce agli all-around, che
  sono già una somma di punti continui. Dettaglio:
  `docs/handoff/REPORT_PASSAGGIO_2_OPUS_P8_2026-08-05.txt`.
- **Trend recente** (`TREND_INTENSITY`): 0.0 su tutti i ruoli/leghe, monotono
  verso il peggio in ogni test.
- **`fattore_forza_avversario`**: RIMOSSO dal codice il 05/08 (passaggio 2,
  P1/B19). Era calcolato e mai usato in `score_atteso`: verificato per
  data-flow e con test A/A su `OPPONENT_SENSITIVITY=1e9`. Il condizionamento
  sull'avversario che agisce davvero è `opponent_lambda_mult` + Stadio D.
- **`level_score` portiere binario**: CHIUSO su decisione utente (02/08). Il
  vero valore è 35.0 senza clean sheet / 60.0 con clean sheet, mai
  intermedio — il modello ne prevede uno continuo. Mitigato dal blend
  `GK_TEAM_CS_WEIGHT=0.5` con P(clean sheet) di squadra (lift misurato
  0.3%→9.4%, correlazione x3), non risolto del tutto: resta la leva più
  grande mai lasciata sul tavolo per il GK, richiederebbe più profondità.
- **Blend GK: sotto-pesato, non sovra-pesato — `c` alzato 17.5→22 (05/08, P3
  + P9-bis/ter, n=6.973 contesti GK, bootstrap appaiato su 120 giornate,
  campione rigenerato e riverificato identico due volte)**. `c = WEIGHT×POINTS`
  nel termine `c*(p-0.28)`; `GK_TEAM_CS_WEIGHT` 0.5→**0.63** (=22/35),
  `GK_TEAM_CS_POINTS` invariato a 35 (è il coefficiente di scala, non un
  valore in punti — conta solo il prodotto). La correlazione cresce monotona
  con `c` (0.0347 a c=0 → 0.0674 a c=17.5 → 0.0707 a c=22 → 0.0756 a c=35),
  il MAE peggiora monotono: **compromesso puro, nessun `c` dominante**. Scelto
  22: dcorr vs 17.5 = +0.0033 (IC95 esclude zero), dMAE = +0.0227 (soglia di
  guardia +0.05). Scartato 26 (misurato, poi rigettato in P9-ter): fra 22 e 26
  il guadagno di corr è +0.0020 (rumore) mentre il degrado di MAE raddoppia e
  il suo IC95 sfora la soglia (+0.0721). **Deroga al metro a tre gambe,
  LIMITATA a questo parametro/ruolo**: per il GK conta l'ordinamento (se ne
  schiera uno solo), non il voto — quindi si decide sulla correlazione con il
  MAE come vincolo di guardia, non sulle tre gambe insieme. Prima deroga del
  progetto al metro standard.
  Le tre "correzioni ovvie" (`POINTS`→25, baseline per-portiere, `p_cal`
  affine `0.130+0.460p`) restano **BOCCIATE**: tutte migliorano il MAE e
  peggiorano la correlazione (IC95 esclude lo zero); `p_cal` è algebricamente
  identico ad abbassare il peso — stessa operazione bocciata con un altro nome.
  Il doppio conteggio del clean sheet (già dentro `level_score`, di nuovo nel
  blend) esiste come meccanica ma **non è dannoso**: il riferimento globale 0.28
  batte quello per-portiere a OGNI `c`, perché `level_score` comprime il segnale
  al punto che il livello assoluto aggiunge ancora informazione vera. Quella
  compressione riguarda **solo il decisivo**: P8 ha verificato che non si
  estende agli all-around (voce sopra). Score_atteso GK a c=26 vs c=17.5:
  media +0.16 pt, p95 +1.99, max +4.48 su soglia arena 259.5 — c=22 sposta meno
  di così, sotto l'incertezza nota sulla soglia (±15 pt). **Verifica di catena
  analitica, non un refit vero**: vedi pendenza sotto. Dettagli:
  `docs/handoff/REPORT_PASSAGGIO_2_OPUS_P3_2026-08-05.txt`,
  `REPORT_PASSAGGIO_2_SONNET_P9_2026-08-05.txt`,
  `REPORT_PASSAGGIO_2_SONNET_P9BIS_2026-08-05.txt`.
- **Il lift di selezione non discrimina sui portieri**: IC95 dei delta larghi
  4-8 punti su 120 giornate. Sul GK il metro a tre gambe è di fatto a due
  (MAE + correlazione). Non costruire ora una terza metrica per aggirarlo:
  decisione presa, non riproporre. Da sapere prima di leggere un lift GK come
  segnale.
- **D2 — misuratore e produzione non condividono lo stesso P(clean sheet)**:
  `test_gk.py` (produzione) usa il cutoff esatto, `backtest_arene_previsioni.
  _pcs_squadra` (misuratore) la griglia settimanale. Decisione: si lascia e si
  documenta, non si allinea (costerebbe una `stima()` per ogni
  giocatore-partita). Irrilevante per i confronti fra varianti (stesso `p` su
  entrambi i lati del delta), rilevante per le stime ASSOLUTE di lift/corr sul
  GK, che girano sul `p` vecchio.
- **PENDENZA APERTA — refit vero di `CALIB_PER_RUOLO` dopo il blend GK**: la
  verifica di catena §1bis fatta per c=22 è analitica (spostamento medio dello
  score_atteso confrontato con l'incertezza nota sulla soglia), non un refit.
  `taratura_formazioni_sintetiche.py` legge `dati_globali/taratura_coppie.json`
  pre-calcolato con il vecchio coefficiente (0.5); nessuno script generatore di
  quel file è stato trovato in due sessioni di ricerca. Da rifare come refit
  vero alla prossima occasione in cui `taratura_coppie.json` viene comunque
  rigenerato. Non è un blocco: lo spostamento è sotto l'incertezza nota.
- **Regola nuova (dal 05/08)**: prima di riusare dati o script di una sessione
  precedente, verificare che l'`n` coincida con quello dichiarato nel report
  corrispondente, PRIMA di misurare qualunque cosa. Secondo caso in cui un
  numero "già misurato" non era riproducibile dal materiale ereditato — il
  primo è D2 sopra, il secondo è `p3_gk_righe.json` (1.487 righe invece di
  6.973, frammento parziale rimasto in uno scratchpad).
- **Compressione di scala** (portiere 4.8x, DEF/MID/FWD 2.5-2.9x): il
  modello ORDINA bene dentro lo slot ma comprime la dispersione assoluta —
  il danno è FUORI dallo slot (fascia capitano, quale competizione, soglie
  d'ingresso), dove numeri di ruoli diversi si confrontano. Non risolto,
  misurato e documentato.
- **Piattezza del punto = VERITÀ del dato, non difetto del modello** (diagnosi
  04/08, tutta su dati locali `dati_globali/errore_storico.json` 2690 partite
  + walk-forward 87k oss, nessun rerun). Nata dall'osservazione utente "le
  formazioni sembrano tutte identiche, gli attesi sono tutti 47-52 / 50-60".
  Cinque misure, tutte concordi:
  1. Spearman(atteso,reale) per ruolo 0.17 (GK 0.084, il peggiore) — BATTE
     l'L10 grezzo (0.13), quindi il modello ordina davvero, ma la varianza
     predicibile del voto è ~3% (il resto è rumore di singola partita).
  2. Lift di selezione REALE grande: quintile-alto vs basso di atteso →
     +11.5 pt reali (FWD +11, GK +6.5), boom(>75) 22.9% vs 9.9%, flop(<25)
     0.9% vs 7.1%. **L'edge del modello è enorme negli ESITI, ma invisibile
     nel numero** (std previsto ~4 contro std reale ~19). Il numero medio
     appiattisce un ordinamento che invece funziona.
  3. Screening segnali (`screening_segnali.json`, 73k partite, sessione
     mattina 04/08): il residuo (reale−atteso) è predicibile a R²=0.008. Unico
     segnale forte = starter_odds (corr 0.163) ma è già usato come filtro a
     monte. Casa +1.9pt, rank avversario, favorito: tutti già dentro o nulli.
     **Non c'è segnale-media libero da aggiungere con le feature disponibili.**
  4. Calibrazione OLS reale=a+b·atteso: b<1 per DEF/MID/GK (0.72/0.71/0.58),
     b=1.15 solo FWD. Cioè per 3 ruoli su 4 il punto è già leggermente
     SOVRA-disperso: **espandere i numeri per "differenziare" li allontana dal
     realizzato, peggiora. NON farlo.**
  5. Range/dispersione per-giocatore NON calibrato (walk-forward 87k): pred_std
     va da 7 a 22, ma |errore| reale resta 15-17 piatto e boom% non si muove
     (GK addirittura invertito). **Il range mostrato nel report è decorativo,
     non usarlo come segnale di volatilità/boom.**
  Conclusione operativa: fra i probabili titolari (= ciò che il generatore
  schiera, `p_gioca` rimosso da score_atteso il 28/07) i giocatori SONO quasi
  equivalenti in attesa, ed è la verità del calcio. L'unico differenziatore
  affidabile è la MEDIA atteso, che ordina anche i boom. Non esiste un modo
  onesto di farli sembrare più diversi migliorando la formula. **Chiuso:
  inseguire "più differenziazione del punto" è un vicolo cieco dimostrato.**
- **Bonus additivi vs moltiplicativi**: chiuso, la formula additiva è
  verificata al centesimo (§3).
- **Quote bookmaker come segnale**: CHIUSO su decisione utente 02/08 —
  infattibile/non copre tutti i campionati. Non riproporre.
- **Capitano DEF/MID/FWD**: 8 ipotesi testate su 3130 formazioni reali
  (bias di ruolo, volatilità, forma grezza L5/L10/L40, margine-soglia,
  stabilità per lega, favorita/sfavorita, combinazioni, profondità storico,
  rischio sostituito presto, ambiente gol partita) — **tutte chiuse,
  `pick_captain()` non va toccato**. Unico segnale mai vicino alla
  significatività: favorita/sfavorita (IC95% [-0.0015,+0.14]), riprovabile
  SOLO con altro campione reale.
- **Capitano per tipo di competizione** (arene vs classifiche grandi):
  nessuna prova che la regola debba cambiare. Segno concorde (favorire
  varianza) ma magnitudine trascurabile (+1.6 essenze su 245, IC quasi a
  zero) — il capitano cambia il premio in <2% delle arene.
- **Formazione concentrata per il capitano** (carta forte + riempitivi vs 5
  carte equivalenti): correlazione -0.006, indifferente.
- **Regole di decisione (allocazione, soglie a gradini)**: DIMOSTRATO (non
  solo misurato) che sono un vicolo cieco. Massimizzare il PREMIO atteso è
  identico a massimizzare i PUNTI attesi (5768/5768 confronti concordi,
  0 contraddizioni) perché l'incertezza sul totale formazione (σ=49.4 pt) è
  troppo grande perché la non-linearità del premio (a gradini per rank)
  conti in pratica. **La regola attuale del bot (massimizza i punti attesi)
  è già quella giusta.**
- **Arene dedicate per lega**: disattivate di default nel generatore (04/08,
  vedi §9) — non un filone di ricerca chiuso, una scelta operativa.
- **Indice `P(≥1 boom)` come metrica di selezione arena**: CHIUSO 05/08 (442
  arene, `PATTERN_ARENE.md`). Non batte `sum_atteso` né `max_atteso` (tutti
  ~−0.05 centrati); il boom-index non aiuta a scegliere in quale arena entrare.
- **Boom-classifier dedicato**: CHIUSO 05/08. L'evento boom (reale>=75) è
  debolmente predicibile (OOF AUC 0.658) ma `atteso` fa quasi tutto
  (+0.025 dal modello completo). `in_casa` NON predice il boom (AUC 0.466). La
  cosa utile è l'eterogeneità per RUOLO: FWD 0.70, MID 0.64, DEF 0.61, GK 0.57
  (≈caso) — l'edge boom vive negli attaccanti, sul GK è testa-o-croce.
- **Covarianza boom fra compagni ("partire dalla partita")**: CHIUSO 05/08 per
  la selezione-boom. Sul boom binario la covarianza fra compagni ≈0 (phi
  +0.012): l'indipendenza del modello regge sulla coda. Sul punteggio continuo
  c'è +0.13 (vs 0.03 controllo) ma non arriva al boom → un layer match non
  migliora `P(≥1 boom)`.

## 6. Il numero da portarsi via

```
10 punti attesi in più = +46.9 essenze attese per arena
```
~4.7 essenze per ogni punto di previsione guadagnato. Converte accuratezza
del modello in denaro: **l'unica leva rimasta è la PRECISIONE della
previsione**, non le regole di decisione (tutte misurate e chiuse, §5).

## 7. Pattern delle arene + soglie — stato attuale

Dataset: **442 arene reali con l'esito di OGNI carta** (`analisi_manager/dati/
formazioni_*.json`+`righe_*.json`, 8 GW) + 306/323 arene reali dell'utente
(`dati_globali/backtest_arene_dettaglio*.json`).

**Sessione 05/08 — 3 filoni pattern arene** (metrica di selezione, modellare
il boom, covarianza-partita): nessun breakthrough, dettaglio in
`analisi_manager/PATTERN_ARENE.md`.

**Sessione 05/08 — validazione soglie, APPLICATA A MAIN (05/08 sera).** σ
della cap 260 era sottostimata (42.70 vs reale ~50-54, validato su 3 dataset
indipendenti); altri tipi (uncapped/cap220/beginner) già corretti. Merge fatto:
`PAREGGIO_ARENA['ARENA_ALLSTARS_260']` 265.0→259.5, `GUADAGNO_PER_PUNTO[...]`
8.8→7.9 (propagato a scouting/ottimizza/backtest via getattr, nessun'altra
modifica). Conviction media: correzione solida ma la posta è piccola (il cap
260 tipico dell'utente è ~270, ben sopra entrambe le soglie). Confermato:
cap 260 = miniera, arena division/Beginner da evitare, l'atteso ordina il
realizzato ma non discrimina dentro una cap. Cronistoria completa e numeri
integrali in `analisi_manager/VALIDAZIONE_SOGLIE.md`.

### Cosa ESPLORARE nelle 435 arene (agganci concreti già trovati)
- **Cosa serve per vincere** (punteggio formazione, cap. incluso): media 261,
  podio ≈294, vittoria ≈352. Scalino 3°→4° solo 12 pt: podio su margini
  stretti. Una carta ≥75 ("boom") capita nel 13.9% dei pick.
- **I boom decidono**: 0 carte ≥75 → podio 7.7%; 1 → 36%; 2 → 68%; 3 → 100%.
  Un flop (<25) uccide: 0 flop → podio 37%, 2 flop → 0%. → la leva è
  massimizzare P(almeno una carta esplode), non alzare la media.
- **Il modello ordina i boom**: quintile-alto di atteso 26% boom vs 11%
  quintile-basso; dentro la stessa formazione la carta #1-atteso fa boom 21%
  vs 8% della #5.
- **[RISOLTO 05/08 — `analisi_manager/PATTERN_ARENE.md`]** L'indice
  `P(≥1 boom)` NON batte il totale-atteso né `max_atteso` per predire il rank
  (tutti ~−0.05 centrati per competizione): idea **bocciata**. E il famoso
  `corr(atteso_somma,rank)=−0.02` era un artefatto di pooling: within-comp è
  −0.05, e in **arene Uncapped −0.30** (il cap comprime i totali attesi e
  nasconde il segnale; dove non morde, il totale predice il rank). Da
  riverificare con più arene uncapped.

### Infrastruttura — cartella `analisi_manager/`
- `analizza_gw.py` (`--gw <slug> --fine <data>` → `dati/righe_/formazioni_/
  report_<gw>` + `INDICE.md`), `aggrega.py` (pool/edge → `AGGREGATO.md`),
  `pipeline_manager.py` (run GitHub: estrai→cacha→analizza→aggrega),
  `censimento_cache.py` (gamelog per lega). `METODOLOGIA.md` (assi A–I).
- Root: `predici_manager_batch.py` (cacha, `--force`), `ricostruisci_manager.py`
  (estrae arene, esclude rare+altro). Workflow: `analisi_manager.yml`.
- `righe_*.json` = 1 riga per (carta, manager) con atteso/reale/l10/ruolo/lega/
  casa/storico/capitano. `formazioni_*.json` = 1 per arena, con rank, punteggio,
  atteso_sum, capitano e le 5 carte annidate. **Nota: righe duplicate quando +
  manager schierano lo stesso giocatore** → per test onesti de-duplicare su
  `(gw, slug)`, vedi trappola §8.15.
- Metodo dati grezzi: solo arene LIMITED (rare/`arena_altro` escluse); atteso in
  walk-forward as-of pre-GW; realizzato = `punteggio` grezzo (tolto cap +20%).

### Verdetto smart-money (CHIUSO come domanda, 8 GW, 2045 pick, satonio escluso)
Bias pool +0.14 (MAE 14.8). Nessun manager a 2σ; eoghankelly da +2.4σ(n29) a
+1.9σ(n54) = regressione al rumore. I pick dei manager NON battono l'atteso.
Dettaglio debolezze modello in `dati/analisi_debolezze_capitano.md`: capitano
riconfermato chiuso; unica ipotesi viva = giocatori con **storico <10 partite
sottostimati +4.9** (n71, da riverificare). Accumulare altre GW rende poco
(le 4 GW vecchie: solo +400 oss); l'accumulo NON è la priorità — i pattern lo sono.

### Secondarie
- **Russia da popolare** (05/08): `formazione_russia` ha pipeline completa ma
  cache ~vuota (3 gamelog) → inerte; va POPOLATA, non costruita. Vale per TUTTE
  le leghe: "coperta ≠ popolata", usare `censimento_cache.py`. `liga-pro`
  (Ecuador) NON interessa.
- **APIKEY Sorare**: richiesta, in attesa — sblocca 600/min (oggi 60). L'unica
  leva vera per velocizzare estrazioni tipo satonio.
- **Tabelle premi** classifiche grandi (All Star/Limited/LALIGA): mancano.

---

## 8. Trappole già cadute — da non ricascarci

1. **I punteggi di classifica Sorare includono già il capitano moltiplicato**
   — sommare gli `atteso` grezzi sottostima ogni formazione di 12-15 punti.
2. **Fino a 3 formazioni nello stesso pool arena**: la chiave di identità è
   `contender_slug`, mai `(giornata, arena)` (75 ingressi veri persi come
   "duplicati" prima del fix).
3. **`so5LeaderboardGroups(groupType: COMPETITION_WITH_ARENA)` con
   `so5LeaderboardContenders(userSlug:)` sembra funzionare ma NON contiene le
   arene** — usare `so5Fixture(slug).userFixtureResults`, paginato.
4. **`groupType`, non `type`**: con l'argomento sbagliato Sorare risponde
   UNAUTHORIZED invece di un errore di validazione — la validazione GraphQL
   avviene prima dell'autenticazione.
5. **`searchPlayers`**: i nomi leggibili nella risposta sono ALIAS
   (`averageScore(type:...)`, non `lastTenPlayedSo5AverageScore`); `rarity`/
   `inSeason` non sono argomenti, passano da `refinements`.
6. **Il client conta**: la stessa query passa con il client di
   `scanners/bot_profit.py` (throttle globale) e viene respinta per
   complessità con altri client.
7. **Il valore del floor price non è un campo richiedibile**, solo un
   filtro — il prezzo esatto viene da `lowestPriceAnyCard(rarity:)`.
8. **Le carte non si clonano**: se ogni arena/formazione sceglie dal pool
   indipendentemente, le stesse carte migliori finiscono ovunque — sempre
   mazzo fisso nei backtest/ottimizzazioni multi-formazione.
9. **Col mazzo fisso i punti sono conservati**: un "oracolo" che massimizza
   i punti riallocando non ottimizza nulla di reale.
10. **displayName della leaderboard Sorare è l'unico dato autorevole** per
    mappare i tipi di arena — dedurlo dai nomi porta a mappature sbagliate
    (arena division ha lo stesso costo/premi di cap 260, non di Beginner).
11. **Rate limit è sull'ACCOUNT**, non sul job: parallelizzare query pesanti
    fa scattare i 429 prima, non le smaltisce più in fretta (ma job leggeri
    — poche decine di query l'uno — SI beneficiano di `max-parallel`, sono
    due situazioni diverse, non confonderle).
12. **Console Windows è cp1252**: crash silenzioso su nomi non latini, forzare
    UTF-8 sullo stdout.
13. **Permessi workflow**: senza `permissions: contents: write` un job può
    restare appeso ore in un retry-loop di push infinito senza segnalare
    nulla.
14. **`glob.glob('**/...', recursive=True)` NON scende nelle cartelle nascoste**
    (`.game_log_cache`, `.cache`) su questo filesystem: conta 0 dove os.walk
    conta migliaia. Ha gonfiato i cache-miss GW1 da 47 a 78 (04/08). Per
    contare/cercare i file di cache usare SEMPRE `os.walk`, mai `glob('**')`.
15. **Analisi manager: le osservazioni NON sono indipendenti** — lo stesso
    giocatore-partita compare una volta per ogni manager che lo schiera (1645
    righe = 892 unici sulle 4 GW). n gonfiata, se sottostimata, **σ
    sovrastimate**. "Portogallo +19.8 pt a 6.4σ" era Pavlidis contato 8 volte:
    de-duplicando sparisce. Prima di credere a un effetto, ri-misurarlo con
    una riga per `(gw, slug)`. Vale per `report_*.md` e `AGGREGATO.md`.
16. **Due cache distinte per giocatore**: `.game_log_cache/<slug>_gamelog.json`
    (il game log, scritto SEMPRE, anche per storico insufficiente — e' l'asset
    riusabile) e `.cache/<slug>_detail_cache.json` (dettaglio per-partita,
    riempito solo se la predizione va a buon fine). Il criterio di "dato gia'
    raccolto" e' il gamelog, non il detail_cache.

---

## 9. Ultima modifica di produzione (05/08/2026)

**Passaggio 2 (audit + fix), 16 commit — PUSHATI su `main` il 05/08 sera**
(`e2fe378376`; il commit bot `4d8c2b7024` di Cerbero è stato integrato con un
merge, nessuna riscrittura di storia). P1-P7
(Sonnet): rimosso `fattore_forza_avversario` morto, scouting portato sulla
scala calibrata, fix aritmetica L10 nel cap del knapsack, tie-break odds vero,
blend CS del portiere da ~124 chiamate a `stima()` a 1 (e mai più muto),
gradino `-3: 0` nella `LEVEL_TABLE` sui 4 ruoli. P3+V1+V2 (Opus): le tre
correzioni al blend GK misurate e **non applicate** (§5); catena §1bis chiusa
per il gradino `-3` (score_atteso si muove ≤ 0.032 pt nel caso peggiore su
19.229 righe, MAE/corr/lift identici a 4 decimali → soglie d'arena e scouting
invariati) e per il cutoff esatto del blend (nessun bias, media +0.0025 pt; la
coda arriva a 8 pt ma solo su squadre con 3-9 partite di storico, e il metodo
nuovo è il lato giusto). P9/P9-bis/P9-ter (Sonnet): `GK_TEAM_CS_WEIGHT`
0.5→0.63 (c=17.5→22, §5) — P9 si è fermato per campione ereditato non
riproducibile (1.487 righe invece di 6.973), P9-bis ha rigenerato il campione
vero e applicato c=26, P9-ter lo ha corretto a c=22 (margine più largo, stesso
guadagno direzionale). Propagato a tutte le leghe (`propaga_modello.py`, solo
`test_gk.py`, verificato `--check`). Commit `cc7bdfdae2` e precedenti.
**P8 (Opus)**: nessuna modifica di produzione, filone chiuso sui dati (§5).
Difetto minore aperto: `formazione_mls/predict/test_gk.py:1632` cita ancora
`GK_TEAM_CS_WEIGHT=0.5`, stantio dopo P9-bis — correggere e propagare al
prossimo commit che tocca il file.

---

## 9bis. Modifica precedente (04/08/2026)

**Arene dedicate per lega disattivate di default** (`ARENA_LEAGUES` vuota in
`generatore_formazioni/build_formazione_globale.py`, riattivabile con
`ARENA_LEAGUES_ENABLED`): venivano proposte come più efficienti senza sapere
se la GW le rendeva schierabili. Commit `ee4c2deec2`.

---

## 10. File chiave per orientarsi rapidamente

| file | cosa fa |
|---|---|
| `generatore_formazioni/build_formazione_globale.py` | il generatore vero, multi-lega, tutti i tipi di formazione |
| `formazione_mls/predict/test_<ruolo>.py` | la formula di previsione per ruolo (pattern riusato su tutte le leghe) |
| `formazione_mls/build_formazione_finale.py` | logica di fusione/capitano/anti-stack |
| `scouting_gw.py` | scouting acquisti, query `searchPlayers` (tool attivo) |
| `best_five.py` | Best Five/Contender, SUPERATO (§2.3) — usato solo come libreria da `scouting_gw.py` |
| `propaga_modello.py` | unica via per propagare un cambio di modello a tutte le leghe |
| `taratura_confronto_parametri.py` | il metro ufficiale (MAE+correlazione+lift insieme) per ogni confronto di parametri |
| `ricostruisci_manager.py` | scarica arene/formazioni reali di un manager Sorare (pubblico) |
| `formazione_mls/diagnostics/` | tutti gli script diagnostici/backtest recenti (capitano, headroom, selezione carte, premio atteso) |
| `dati_globali/` | tutti gli archivi dati costruiti (§4) |

---

## 11. Come lavorare con l'utente (osservazioni ricorrenti)

- Ha ragione spesso quando un numero "non torna" col suo senso pratico — le
  regole di gioco non sono deducibili dai dati, vanno chieste.
- Fermarsi e chiedere a ogni dubbio invece di procedere per assunzioni.
- Leggere questo file (e il codice) prima di riproporre qualcosa: più
  filoni sono stati proposti due volte perché già chiusi e documentati.
- Un bias marginale forte non implica un buon criterio di scelta tra
  candidati della stessa decisione — misurare sempre la POLICY, non solo il
  bias astratto (costato diverse ipotesi false-positive nel filone capitano).
- Misurare il valore di una decisione PRIMA di cercare euristiche per
  migliorarla (headroom pavimento/caso/attuale/oracolo, §5-6).
