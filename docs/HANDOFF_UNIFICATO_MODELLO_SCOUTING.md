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

Ultimo aggiornamento: **sessione 05/08/2026, ore 01:00 (Roma, CEST)**.
Sessione attuale = filone "smart money" (vedi §7). Regola di stile: questo
file resta SNELLO (max ~4 pagine) e ogni aggiornamento riporta sessione,
giorno e ora nel fuso di Roma.

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
               x fattore_casa_trasferta x fattore_forza_avversario
               x fattore_trend
range_confidenza = +/- dev_std_pesata x RANGE_MULTIPLIER
```
GK ha in più il blend con P(clean sheet) di squadra (§7). I "fattori
granulari" per categoria di statistica Sorare (falli, duelli, passaggio...)
sono stati provati e **rimossi ovunque**: non battono la media pesata
semplice, vedi §8.

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

- **Fattori granulari per categoria statistica**: rimossi ovunque, non
  battono la media pesata semplice.
- **Trend recente** (`TREND_INTENSITY`): 0.0 su tutti i ruoli/leghe, monotono
  verso il peggio in ogni test.
- **`fattore_forza_avversario`**: era una costante inerte mai letta, poi
  riabilitata con dato pulito (29/07) — oggi in produzione, stabile.
- **`level_score` portiere binario**: CHIUSO su decisione utente (02/08). Il
  vero valore è 35.0 senza clean sheet / 60.0 con clean sheet, mai
  intermedio — il modello ne prevede uno continuo. Mitigato dal blend
  `GK_TEAM_CS_WEIGHT=0.5` con P(clean sheet) di squadra (lift misurato
  0.3%→9.4%, correlazione x3), non risolto del tutto: resta la leva più
  grande mai lasciata sul tavolo per il GK, richiederebbe più profondità.
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

## 6. Il numero da portarsi via

```
10 punti attesi in più = +46.9 essenze attese per arena
```
~4.7 essenze per ogni punto di previsione guadagnato. Converte accuratezza
del modello in denaro: **l'unica leva rimasta è la PRECISIONE della
previsione**, non le regole di decisione (tutte misurate e chiuse, §5).

## 7. Da dove ripartire — SESSIONE ATTIVA: "smart money"

### Deliverable e metodo
Domanda: **i pick dei bravi manager battono il nostro `atteso`?** SÌ → feature
nuova + edge. NO → il modello è il tetto anche contro gli umani → si chiude.
Metodo: campione non-bias = **12 slug** (`eoghankelly, badamt, milkyfresht,
lairdinho, bxl-spartak, spillo678, braddersfc, bryanmid, shirimimi, matangel716,
fins49, ninoshooter`) **+ qtn** (`qtn-d8cd72ac-...`). **satonio FUORI dal
campione** (whale, solo per gonfiare la cache). Solo **arene LIMITED** (rare e
`arena_altro` escluse: mint diverso, inaffidabili). Per ogni GW chiusa: estrai
arene → `atteso` in **walk-forward as-of pre-GW** (`backtest_arene_previsioni.
score_atteso`) → **residuo = realizzato − atteso** (realizzato = `punteggio`
grezzo, tolto capitano +20%). Dati **sempre distinti per GW** (slug nel nome).

### Infrastruttura — cartella `analisi_manager/`
- `METODOLOGIA.md` (assi A–I), `analizza_gw.py` (`--gw <slug> --fine <data>` →
  `dati/righe_/formazioni_/report_<gw>` + `INDICE.md`), `aggrega.py` (pool +
  persistenza/edge per manager → `AGGREGATO.md`), `pipeline_manager.py` (tutto in
  una run GitHub: estrai→cacha→analizza→aggrega, scrive `dati/copertura_cache.json`),
  `censimento_cache.py` (gamelog per lega, stana le inerti).
- Root: `predici_manager_batch.py` (cacha, `--force` per appendere GW nuova),
  `ricostruisci_manager.py` (estrae arene, esclude rare+altro). Workflow:
  `analisi_manager.yml` (pipeline), `predici_manager.yml` (solo cache).
- Whitelist manager e `ARENE_AMMESSE` in `analizza_gw.py`; leghe in
  `discovery_fixture.LEAGUE_DIR`. Cache condivisa con generatore/scouting.

### Verdetto (4 GW, 1645 pick, 9-10 manager attivi/GW, satonio escluso) — nessun segnale affidabile
Bias pool = +0.41 (n 1645, MAE 14.9, corr +0.221). Skill controllata per
ambiente-GW (edge = residuo − media GW): nessun manager a edge/se ≥2 con n
solido — solo eoghankelly +2.4 ma n=29 (troppo piccolo per fidarsi). Tutti gli
altri (qtn n=953, bxl-spartak, shirimimi, fins49, milkyfresht...) fra −1.6 e
+1.3, nessuno persistente su tutte le GW (colonna "segno" = misto per i
manager con n grande). Conferma §5: il modello cattura già i pick dei bravi
manager, non c'è edge da inseguire. NON chiuso del tutto: accumulare fino a
~8-10 GW; se resta ~0 → STOP definitivo.

### Prossimi passi
- Continuare l'accumulo (vedi sotto) fino a 8-10 GW per chiudere definitivamente.
- Russia: cache passata da 3 a 20 gamelog (05/08), ancora INERTE (<100), non
  ancora popolata a sufficienza — richiede altre run/GW per crescere.

### Analisi pooled 4 GW — `analisi_manager/dati/analisi_debolezze_capitano.md`
Fatta il 05/08 mentre girava l'accumulo. Sintesi (dettaglio nel file):
- **De-duplicando, nessun effetto supera 2.1σ.** Il modello non ha una
  debolezza sistematica catturabile con le feature disponibili (conferma §5).
- **La debolezza vera è il salto giocatore→formazione**: corr(atteso, reale) a
  livello giocatore +0.22, ma sommando 5 carte NON sale (+0.18) e
  **corr(atteso_somma, rank in arena) = −0.02, cioè zero**. Non è la
  classifica a essere rumorosa (corr(reale_somma, rank) = −0.83): siamo noi a
  non anticiparla. Il segnale esiste solo negli esiti (quintile alto vs basso
  = +19.4 pt reali su 5 carte), invisibile nella correlazione media.
- **Capitano: riconfermato chiuso.** `pick_captain` pareggia con gli umani
  (+0.19 pt/form., +0.7σ) e nessuna delle 6 policy alternative testate lo
  batte ("più storico" lo peggiora a −2.6σ). Il capitano vale poco comunque:
  3.8 pt fra scelta peggiore e casuale, altri 3.8 di headroom oracolo.
  Evitato un falso positivo: "i manager sbagliano a fare capitano il FWD" è
  FALSO — i FWD capitani rendono +1.4 sopra i FWD non-capitani, il −7.4 è il
  livello base del ruolo (trappola §11).
- **Unica ipotesi azionabile emersa**: giocatori con **storico < 10 partite**
  sottostimati di +4.9 (2.1σ, n=71 unici) → possibile shrinkage prior troppo
  forte su chi ha pochi dati. Da riverificare con più GW prima di toccare.
- **qtn-d8cd72ac pesa 58% del pool** (953/1645): non è un campione bilanciato.
- **eoghankelly unico edge/se ≥2 (+2.4)** ma n=29: ricontrollare quando cresce.

### Continuare l'accumulo
GW più vecchie = più storico, meno scarti. Slug: GW92 `football-15-20-jul-2026`
(07-20), GW91 `football-10-13-jul-2026`(07-13), GW90 `football-5-8-jul-2026`
(07-08), GW89 `football-1-4-jul-2026`(07-04)…
```
gh workflow run analisi_manager.yml -f gw="football-15-20-jul-2026:2026-07-20,..."
```
(manager vuoto = i 13 di default, satonio escluso). Poi pull, rigenera, leggi
INDICE/AGGREGATO. Aggiungere un manager: slug in whitelist (`analizza_gw.py`) +
`DEFAULT_MANAGER` (`pipeline_manager.py`), poi workflow `-f manager=<slug>` sulle
GW già fatte.

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

## 9. Ultima modifica di produzione (04/08/2026)

**Arene dedicate per lega disattivate di default.** Il generatore le
proponeva come più efficienti in base al punteggio atteso, ma senza sapere
se la giornata le rendeva davvero schierabili (es. In Season non attivo
quella GW) — l'utente le sostituiva comunque a mano con Arena All Stars 260.
`ARENA_LEAGUES` in `generatore_formazioni/build_formazione_globale.py` ora è
vuota di default; riattivabile con l'env/input workflow
`ARENA_LEAGUES_ENABLED` (`mls,kleague` o `tutte`), rispettando comunque il
vincolo di efficienza esistente (PRIORITY_ORDER + confronto atteso/pareggio).
Commit `ee4c2deec2`.

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
