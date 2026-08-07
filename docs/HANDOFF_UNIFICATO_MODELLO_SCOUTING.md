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

Ultimo aggiornamento: **sessione 05/08/2026, sera tardi (Roma, CEST)**.
Sessione: passaggio 2 **P11** — `P(≥1 boom)` come funzione obiettivo della
formazione misurata e **CHIUSA senza modifiche** (§5, blocco boom). Prima:
P8 composizione all-around **CHIUSA**; i 16 commit del passaggio 2 (P1-P9-ter,
blend GK `c` 17.5→22) sono **PUSHATI su `main`**. Sessione precedente: pattern arene
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
Arena, All Stars, Under 23) con capitano, rispettando i vincoli Sorare.
**ATTENZIONE: i vincoli NON sono gli stessi in tutte le competizioni** (verificato
06/08 in `FORMATION_SHAPES`, `build_formazione_globale.py:184-203`, dopo che la
vecchia formulazione ambigua di questa riga aveva gia' indotto in errore un brief):
- **In Season** (`MLS_IN_SEASON`, `KLEAGUE_IN_SEASON`): `max_classic = 1`, min 4 In Season.
- **Arene** (`ARENA_ALLSTARS_260/220/UNCAPPED`, `ALLSTARS`, `ALLSTARS_U23`, arene
  per-lega): `max_classic = None`, **nessun tetto sulle Classic**. L'unico vincolo e'
  il cap L10 dove previsto; uncapped/elite non hanno nemmeno quello.
Mai applicare i vincoli In Season a un backtest sulle arene: restringerebbe il pool
con una regola inesistente e falserebbe entrambi i lati del confronto.

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
| `dati_globali/manager_crowss.json` | **ATTENZIONE: e' l'UTENTE STESSO** (nickname Sorare `Crowss`), NON un manager esterno. 72 giornate, 1332 formazioni usate nel filone capitano. La vecchia descrizione ("un manager Korea-centrico") era doppiamente sbagliata: non e' un terzo e non e' Korea-centrico. Da NON includere in nessun confronto "i pick dei manager vs il nostro atteso" (filone smart-money, §7): confrontarsi con se stessi falsa il verdetto. Verificare se il filone capitano e le analisi smart-money lo hanno incluso per errore. |
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

> **AGGIORNAMENTO 06–07/08/2026 (leggere prima del resto della sezione).**
> Consolidamento parziale: i dettagli aperti stanno in
> `docs/handoff/ELENCO_APERTI_2026-08-07.txt`, le consegne per il prossimo
> orchestratore in `docs/handoff/HANDOFF_ORCHESTRATORE_2026-08-07_SERA.txt`.
> Un rewrite completo di questo file è rimandato a quando il filone
> odds+4ruoli sarà chiuso (FASI 3–4 ancora in corso), per non consolidare
> uno stato parziale.
>
> 1. **BUG D6 — punteggi di formazione gonfiati.** Più script di backtest
>    (`p11_manager_confronto`, `p11_bloccato_tutti_mazzi`,
>    `p11_calib_fwd_confronto`) leggevano il punteggio realizzato dai file
>    manager (`c['punteggio']`), che include xp+capitano sulle righe
>    non-arena, invece che dalla cache game-log. Fino al 77% delle carte
>    gonfiate su crowss. **Tutti e tre fixati** (leggono sempre la cache).
>    Conseguenza: i verdetti di **formazione** su difensore e FWD costruiti
>    su quegli script sono NULLI e vanno rifatti (la griglia per-ruolo 4.1,
>    invece, era pulita — vedi punto 4). `p12_backtest_manager_full`
>    verificato: NON era un bug. Regola nuova in CLAUDE.md: l'orchestratore
>    verifica i dati grezzi di un commit esecutore, non solo il commento.
> 2. **Metro premio-vero.** Il valore delle decisioni arena si misura ora dal
>    RANK reale + tabella premi reale dell'utente
>    (`backtest_arene_economia.tabella_premi`), non da stime proporzionali
>    (che divergevano di segno). È la misura più affidabile: non stima nulla
>    sopra soglia.
> 3. **Decisione produzione.** Campione ampliato a 539 arene (crowss + 16
>    manager + satonio). Premio-vero netto: **A (produzione) +14.300 essenze,
>    G (produzione + grade) +18.900**, positivo per entrambe, G meglio. Oggi
>    si schiera con A + condotta arene (costo zero). **G va in produzione come
>    passo successivo, con la catena §1bis validata step per step** (non fatto
>    ancora). Cautela: il vantaggio di G viene dai mazzi forti (crowss,
>    satonio), non dai mediocri.
> 4. **Griglia per-ruolo starter odds (favorito_odds) confermata PULITA** su
>    tutti e 4 i ruoli (numeri identici allo storico, D6 non la toccava):
>    **DEF passa forte** (7/9 varianti, dcorr +0.060, dlift +7.22), **GK e
>    MID mai** (0/9), **FWD al limite** (1/9). Il segnale DEF è reale e grosso
>    sull'ORDINAMENTO per-carta. In FORMAZIONE, però, il backtest FASE 3
>    (45 mazzi) è risultato NON PROBANTE: DEF bloccato sfiora zero senza
>    farcela, MID/D "significativi" solo nel delta pesato ma probabile
>    artefatto — e soprattutto il campione non è probante in profondità (solo
>    2 mazzi con ≥16 giornate; pablo0078 da solo pesa il 33% delle arene).
>    APERTO (non chiuso): l'utente NON accetta di relegare il DEF (e gli altri
>    ruoli) al solo scouting sulla base di 2 mazzi profondi. Prossimi passi:
>    allargare il campione PROFONDO e rifare il backtest formazione; fare la
>    FASE 4 scouting in parallelo (non come sostituto); verificare pablo0078.
>    Dettaglio: `HANDOFF_FAVORITO_ODDS_2026-08-06.txt` (FASI 1-3) e
>    `HANDOFF_ORCHESTRATORE_2026-08-07_SERA.txt` §4. Se le odds risultano
>    usabili, entrano nella STESSA catena di G.

- **Scomposizione degli all-around per categoria: CHIUSA (05/08, P8)**, anche
  con misura diretta walk-forward (39.594 partite, 26 leghe, bootstrap
  appaiato): nessuna forma soddisfa MAE+corr+lift insieme su nessun ruolo.
  Corregge P3: la compressione trovata da P3 riguarda solo il DECISIVO
  (`level_score`, scala a gradini), non si trasferisce agli all-around (già
  somma continua). Dettaglio: `docs/handoff/REPORT_PASSAGGIO_2_OPUS_P8_2026-08-05.txt`.
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
- **P10 (05/08)**: refit vero di `CALIB_PER_RUOLO` NON completato — trovato
  lo script che rigenera i dati grezzi (`taratura_giocatore.raccogli`, 4 min,
  nessuna rete) ma **manca nel repo lo script che calcola i 4 coefficienti
  `CALIB_A/B_GK/DEF/MID/FWD`** (solo hardcoded in
  `generatore_formazioni/build_formazione_globale.py:394-399`); la retta
  "in produzione" 63.43+0.736x (`analisi_manager/valida_soglie.py`) non
  coincide né col rigenerato vecchio (75k coppie: 40.64+0.823x) né nuovo
  (82k coppie: 33.49+0.853x) — scollegata da tempo, non solo da P9. Backlog
  aperto, sessione dedicata. **Anomalia capitano grezzo/calibrato (n=307,
  confermato esatto)**: causa isolata — `pick_captain` vede attesi già
  calibrati in produzione; su 42/307 casi discordanti il calibrato sceglie
  DEF 35 volte (`CALIB_PER_RUOLO` DEF ha la pendenza più alta, 0.831), il
  grezzo sceglie FWD/MID. Hit-rate 28.7% grezzo vs 25.1% calibrato, ma il
  delta in punti sui discordanti (+5.2 pt) ha IC95 [-2.75,+13.14]: non
  significativo. Chiusa, nessuna modifica. Dettaglio:
  `docs/handoff/REPORT_PASSAGGIO_2_SONNET_P10_2026-08-05.txt`.
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
     mattina 04/08): il residuo (reale−atteso) è predicibile a R²=0.008.
     **ATTENZIONE — il "segnale forte starter_odds (corr 0.163)" è LEAKAGE,
     non segnale** (accertato 06/08, vedi voce dedicata sotto): il campo in
     cache viene riscritto dopo le formazioni ufficiali. Non usarlo come
     riferimento di "quanto è forte un segnale". Casa +1.9pt, rank avversario,
     favorito: tutti già dentro o nulli.
     **Non c'è segnale-media libero da aggiungere con le feature disponibili.**
- **`starter_odds` come variabile continua in `score_atteso`: CHIUSO (06/08),
  per due ragioni indipendenti.**
  1. *Non è una variabile nuova*: `p_gioca` era esattamente
     `starterOddsBasisPoints/10000`, rimossa il 28/07 (commit `2c34af62f7`)
     per **decisione di significato** dell'utente, non per una misura —
     `score_atteso` deve dire "quanto rende SE gioca", il rischio presenza si
     gestisce col filtro secco (`MIN_STARTER_ODDS`). Vedi
     `RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` §31.B/31.F ("NON riproporre").
  2. *Il dato storico è contaminato*: **64.6% dei valori in cache (42.318 oss.)
     sono 0% o 100% esatti**, perché il campo viene riscritto dopo l'annuncio
     delle formazioni. Su 230 coppie con quote raccolte prima della deadline,
     solo il 6.1% coincide col valore poi salvato in cache, e il 77.8% dei
     valori post è più alto. In PRODUZIONE non c'è problema (si legge prima
     della deadline); nel BACKTEST è quasi la conferma di chi ha giocato.
     Qualunque griglia su questo campo misurerebbe leakage.
  Se un giorno lo si volesse davvero misurare, l'unica via è **registrare le
  starter odds pre-deadline in avanti**, GW per GW, come per la lettera A→F.
  4. Calibrazione OLS reale=a+b·atteso: b<1 per DEF/MID/GK (0.72/0.71/0.58),
     b=1.15 solo FWD. Cioè per 3 ruoli su 4 il punto è già leggermente
     SOVRA-disperso: **espandere i numeri per "differenziare" li allontana dal
     realizzato, peggiora. NON farlo.**
     **ATTENZIONE (06/08): questi 4 coefficienti NON sono riproducibili dal
     repo.** Verificato: `screening_segnali.py`/`.json` non li ha mai
     calcolati in nessuna versione della sua storia git, e non contengono
     nessun campo OLS reale=a+b·atteso per ruolo. L'unica occorrenza nel repo
     è una citazione "dal brief" in `REPORT_PASSAGGIO_1_2026-08-05.txt:171`,
     testo esterno mai riprodotto da uno script. Resta aperta anche la Q4 di
     quella sessione: misurati sul grezzo o sul calibrato? Finché non si sa
     da dove vengono, **non usarli come conferma indipendente di nulla** (già
     costato un falso collegamento col refit FWD del 06/08). La conclusione
     operativa della voce (non espandere i numeri) resta valida perché
     poggia anche sui punti 1-3 e 5, non solo su questi coefficienti.
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
- **Quote bookmaker come segnale**: la chiusura del 02/08 ("infattibile, non
  copre tutti i campionati") era SBAGLIATA e va considerata SUPERATA. Il
  filone e' stato riaperto e portato fino al backtest di formazione la notte
  del 05-06/08. In sintesi: le 1X2 sono dentro Sorare
  (`Game.homeStats/awayStats.winOddsBasisPoints`), bulk per fixture,
  copertura piena (unico buco eliteserien), persistenti da ~18/11/2025,
  nessun leakage (favorito vince 65.3% su n=118). `favorito_odds` batte
  nettamente il "favorito" interno e ne **assorbe** il segnale insieme a
  `rank_avversario` e `casa`. Sul **DEF** il metro a tre gambe passa con
  margine (mult k=0.2: dMAE −0.197, dcorr +0.060, dlift +7.22, tutti gli
  IC95 lontani da zero, 7 varianti su 9); su GK/MID/FWD **non** passa
  (sempre il lift). **In formazione il guadagno NON e' dimostrato** su 880
  arene e due mazzi indipendenti: i ruoli competono per lo slot libero e
  l'effetto sparisce nel rumore (σ≈50 pt/arena; servirebbero ~2.500 arene).
  **CHIUSO il 06/08 per la FORMAZIONE: effetto ESCLUSO, non "non dimostrato".**
  Su ~37 mazzi indipendenti e ~7.000 arene il delta pesato ha IC95 di
  ampiezza ~1.3 pt con limite superiore mai oltre **+0.8**, che ESCLUDE sia
  il +2.98 di forever-young sia il +3.33 delle arene sintetiche (entrambi
  risultati isolati e non replicati). Esclusi anche i due bias sospettati
  (cecita' al rischio panchina, capitano che cambia). Il massimo guadagno
  compatibile coi dati (<4 essenze/arena) non giustifica di toccare la
  produzione. **Non riproporre l'adozione in formazione senza dati nuovi di
  natura diversa.** Restano veri e non smentiti i numeri per-ruolo sul DEF.
  Bocciate nella stessa sessione anche: **`p_draw`** (quota di pareggio,
  testata con variabile centrata e griglia riscalata sulla sua SD, come da
  correzione di scala: **2 PASS su 64 varianti, entrambi FWD e non
  indipendenti** — additiva k=−21.17 e moltiplicativa k=−0.353 sono lo stesso
  punto in due forme, fragili fuori da lì. Con 64 test al 95% il caso ne
  produce ~3: 2 e' SOTTO l'atteso da rumore puro. DEF/GK/MID bocciati, segno
  spesso opposto all'atteso. Il segno negativo su FWD e' l'unica cosa
  coerente con l'ipotesi — partita bloccata penalizza l'attaccante — ma
  dcorr +0.005 e' 12x piu' piccolo del +0.060 di `favorito_odds` sul DEF,
  che gia' non arrivava a spostare un punto in formazione), il capitano
  scelto con la p_win di mercato (che chiude
  definitivamente l'ultima ipotesi capitano rimasta aperta), e tre ipotesi
  strutturali su dimensione/dispersione/concentrazione del pool.
  Unica strada mai misurata: lo **scouting**, dove si confrontano carte
  dentro lo stesso ruolo e non c'e' competizione fra ruoli. Dettaglio
  integrale, tabelle e falsi allarmi:
  `docs/handoff/HANDOFF_FAVORITO_ODDS_2026-08-06.txt`.
- **Lettera "Potenziale della GW" (grade A→F)**: individuata
  (`So5Score.projection.grade` + `reliabilityBasisPoints`, solo nel contesto
  compose-team, NON in `searchPlayers` — il sort `projected_grade.<fixture>`
  e' ignorato in silenzio, testato, non riprovare). E' per giocatore-partita,
  non e' P(gioca) ne' L10 ne' un grado per ruolo. **Nessuno storico: sparisce
  al fischio d'inizio**, quindi non backtestabile — va registrata in avanti.
  Nessuna domanda di ricerca ancora definita: definirla PRIMA di accendere
  qualunque registratore.
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
- **BLOCCO BOOM — tutto CHIUSO (05/08, tre passaggi).** "Boom" = carta con
  realizzato ≥75. I boom decidono il podio (0 boom → podio 7.6%, 1 → 35.7%,
  2 → 68.0%, n=442 formazioni, riverificato in P11), ma **non sono una leva
  separata**: sono una conseguenza del punteggio alto.
  1. *Come metrica per scegliere in QUALE arena entrare*: bocciata. Non batte
     `sum_atteso` né `max_atteso` (tutti ~−0.05 centrati per competizione),
     `PATTERN_ARENE.md`.
  2. *Come classifier dedicato*: l'evento è debolmente predicibile (OOF AUC
     0.658) ma `atteso` fa quasi tutto (+0.025 dal modello completo);
     `in_casa` non predice (0.466). Eterogeneità per RUOLO — logistica su
     82.282 coppie al valore di produzione (P11): pendenza FWD 0.145,
     MID 0.098, DEF 0.088, **GK 0.027**; AUC fuori campione FWD 0.671,
     MID 0.648, DEF 0.603, **GK 0.514 = caso**. L'edge boom vive negli
     attaccanti, sul portiere non esiste.
  3. *Come FUNZIONE OBIETTIVO per COSTRUIRE la formazione* (**P11, la domanda
     vera**): bocciata. Massimizzare `P(≥1 boom)` invece della somma degli
     attesi, sul mazzo reale dell'utente, coi vincoli veri e lo stesso
     knapsack (obiettivo lineare `Σ−log(1−p_i)`): pareggia col mazzo fisso
     (Δrank +0.02, IC95 contiene zero, 228 arene) e **perde** ad arene
     isolate (Δrank +0.381 IC95 [+0.025,+0.725]; Δpunti −6.04 IC95
     [−11.63,−0.35]; 244 arene, bootstrap appaiato). Le due policy divergono
     davvero (sovrapposizione 1.3–3.5 carte su 5): non era nullo per
     costruzione. **Causa**: dentro un ruolo p è monotona nell'atteso → stesso
     ordinamento; tutta la differenza è cross-ruolo, e la pendenza ripida dei
     FWD sposta lo slot EXTRA da MID a FWD (1.02 → 1.59 attaccanti). Risultato:
     più boom (0.93 vs 0.82) ma **concentrati**, e la P(almeno uno)
     *realizzata* scende (54.5% vs 57.0%). In più, ottimizzare direttamente su
     `p̂` raccoglie l'errore di stima (maledizione dell'ottimizzatore: scarto
     previsto−realizzato −0.141 per B contro −0.097 per A).
     → **massimizzare la somma degli attesi è già la policy giusta.**
     Dettaglio: `docs/handoff/REPORT_PASSAGGIO_2_OPUS_P11_2026-08-05.txt`,
     script `analisi_manager/p11_*.py`.
  4. *Covarianza fra compagni*: phi ≈0 per squadra (+0.012, replicato);
     condizionata ai `p_i` dentro formazione +0.0315 IC95 [+0.0000,+0.0642] →
     l'indipendenza regge come approssimazione, ma il prodotto dei
     complementari **sovrastima** P(≥1 boom) di ~3.5 pp (osservata 0.468 vs
     modello 0.504). Sul punteggio continuo la covarianza c'è (+0.13 vs 0.03
     di controllo) ma non arriva al boom.
- **DIFETTO APERTO (trovato in P11, non corretto)**:
  `backtest_arene_previsioni.py:257-260` ha ancora default
  `GK_TEAM_CS_WEIGHT=0.5` con il commento "come produzione" — **falso dopo
  P9-ter** (22/35). Chi usa quel modulo senza esportare la variabile misura un
  modello che non esiste più. Correggere al prossimo commit sul file (meglio:
  leggerlo da `test_gk` invece di duplicarlo).

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

**Sessione 05/08 — 4 filoni boom** (metrica di selezione arena, classifier,
covarianza-partita, e in P11 la funzione obiettivo della formazione): tutti
chiusi, nessun breakthrough. Dettaglio in `analisi_manager/PATTERN_ARENE.md` e
`docs/handoff/REPORT_PASSAGGIO_2_OPUS_P11_2026-08-05.txt`; riepilogo in §5.
Il backtest P11 gira sulle **300 arene reali** dell'utente non-Beginner e
non-division (le division sono escluse: `ARENA_LEAGUES` è vuota, il generatore
le tratterebbe come cap 260 miste e costruirebbe formazioni non ammissibili).

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

### Cosa serve per vincere, e cosa resta da esplorare
- **Soglie reali** (punteggio formazione, cap. incluso): media 261, podio ≈294,
  vittoria ≈352. Scalino 3°→4° solo 12 pt: podio su margini stretti. Una carta
  ≥75 ("boom") capita nel 13.9% dei pick; un flop (<25) uccide (0 flop → podio
  37%, 2 flop → 0%). Il modello ORDINA i boom (quintile-alto di atteso 26% vs
  11%; carta #1-atteso 21% vs 8% della #5) — ma vedi il blocco boom in §5:
  come leva d'azione è chiuso in tutte e tre le forme.
- **UNICO THREAD VIVO**: `corr(atteso_somma, rank)` = −0.02 era un artefatto di
  pooling; within-competizione è −0.05, e in **arene Uncapped −0.30** (n=31).
  Il cap comprime i totali attesi e nasconde il segnale; dove non morde, il
  totale predice il rank. **Da riverificare con più arene uncapped**: è anche
  l'unico ambiente in cui la scelta della funzione obiettivo potrebbe contare.

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

## 8bis. Indagine sullo SCOUTING dopo il grade (07/08/2026, non urgente)

Richiesta dell'utente: «se il generatore aveva un problema di autenticazione lo
avrà anche lo scouting», e «non ho mai testato lo scouting dopo il grade».
Indagine fatta sul codice e sui log di run vere (`30910296375`, `30845739587`).
Nessuna modifica applicata: è un elenco di cose da decidere.

**Quello che NON è rotto** (verificato, non dedotto):
- **Nessun problema di autenticazione.** `scouting_gw.py` non fa nessuna query
  autenticata: zero `myFilteredBench`, `currentUser`, `owner`, `user(slug:)`.
  Sta dov'era la discovery prima del grade — tutte query pubbliche — quindi la
  sessione anonima descritta nell'handoff orchestratore §5bis non lo tocca.
- **Non sovrascrive l'esclusione delle carte bloccate.** Il job `candidati`
  scrive solo `player_slugs.json`, mai `player_card_counts.json`, che è dove
  vive `ESCLUDI_LOCKATE`. Verificato: nessuna interferenza.
- **Le odds le prende già in bulk** (`odds_per_giornata`) dal 03/08. Su questo
  era la discovery a essere indietro, non lui.

**Difetti aperti, in ordine di quanto costano:**

1. **Buco di copertura per leghe senza pipeline.** Ogni run avvisa per `nb-i`,
   `nb-ii`, `premier-division-ie`, `premier-league-am`, `super-liga-sk`,
   `virsliga`: i loro giocatori restano nel pool ma non ricevono un atteso, e
   quindi non possono essere consigliati. Da decidere: costruire le pipeline o
   escluderli a monte per non sporcare i conteggi.
2. **429 fra 23 e 111 per run.** Stessa malattia della pipeline formazioni:
   `max-parallel: 20` sulla matrice predict. Qui però le run durano 2.7-3.8
   min, quindi il danno è piccolo — non è urgente, ma è lo stesso meccanismo.
3. ~~Commento stantio sul `max-parallel`~~ **CHIUSO 07/08** (`74b5bed89f`):
   diceva che il valore tarato era 8, il codice usa 20 per un motivo misurato.
4. ~~`_gql` senza CSRF~~ **CHIUSO 07/08** (`74b5bed89f`): ora manda
   `x-csrf-token` e svuota il barattolo dei cookie, come la discovery. Chiuso
   anche il job `consigli` del workflow, che passava il cookie ma non il CSRF
   pur interrogando Sorare per i prezzi.
5. **Il job `candidati` sovrascrive `player_slugs.json` di produzione** per le
   leghe toccate. È già scritto nel commento del workflow, ma vale ricordarlo:
   fino alla successiva run di `formazione_giornata` un predict manuale
   userebbe la lista dello scouting.

**Decisione APERTA, da prendere con l'utente: il grade nello scouting.**
La parola `grade` non compare in `scouting_gw.py`.

RETTIFICA (07/08, sera). In una prima stesura di questa sezione avevo scritto
che il grade «arriva dalle carte che si possiedono, quindi per una carta da
comprare non esiste». **È FALSO, e l'utente l'ha corretto: il grade è legato
alle odds della partita, non al possesso della carta.** Verificato subito
dopo, su giocatori NON posseduti:
    Charly Nouck   (non posseduto) -> D, D, D, D  (incluso il 2026-08-07)
    Matthew Hoppe  (non posseduto) -> D, D, D, D  (incluso il 2026-08-07)
    Hans Vanaken   (posseduto)     -> C, E, B, A
Si leggono con `anyPlayer(slug).playerGameScores.projection.grade`, query
pubblica. `myFilteredBench` è soltanto la query che abbiamo scelto NOI per la
produzione, e filtra alle carte possedute perché al generatore servono solo
quelle: non è un limite del dato.

Quindi **niente ostacolo strutturale**: il grade per un candidato d'acquisto è
ottenibile. Il vincolo vero è di TEMPO, non di possesso: per una partita
futura il grade compare solo quando Sorare lo pubblica (misurato lo stesso
giorno: `None` per le partite del 14 e 17 agosto, valorizzato per quelle del
7). Resta quindi da decidere, con l'utente, se e come un segnale che esiste
solo a ridosso della partita debba pesare su una decisione d'acquisto che vale
per più giornate. Da discutere prima di scrivere codice.

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
