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

Ultimo aggiornamento: **sessione 09/08/2026, notte (Roma, CEST)**.

**RIPARTIRE DA QUI**: il passaggio di consegne aggiornato è
`docs/handoff/PASSAGGIO_CONSEGNE_ORCHESTRATORE_2026-08-09_MATTINA.txt` —
dice il punto esatto in cui siamo, cosa si aspetta da Sonnet e cosa fare
quando torna. Leggilo prima di questo file.

**PUNTO FERMO DEL 09/08 — cosa è deciso e non si riapre:**

1. **G è validato anche sulle ARENE** e resta in produzione. Con la
   copertura del grade portata al 98,8%, batte il modello senza grade di
   **+29.050 / +24.150 essenze** nel regime di allocazione, placebo al
   percentile 100 su entrambi i set di soglie. Sul non-arena era già
   dimostrato (+5,98). §8bis.
2. **Il filone favorito-odds è CHIUSO, ovunque.** Delta storico e livello
   assoluto, due scale diverse, non-arena e arena, regime astensione e
   allocazione: non batte mai G. Non riaprirlo senza un'idea nuova. §8nonies.
3. **Le soglie arena sono APPLICATE in produzione** (commit `f9902af972`),
   ricalcolate su 2.125 arene e 5.031 premi veri, con il tipo **Beginner**
   aggiunto al generatore. §8octies e §9.
4. **L'archivio arena completo è `arene_storico_full_v3.json`**: com'è
   composto, come si allarga e quali buchi ha sta in **§4.0** — leggerlo
   prima di progettare qualunque misura sulle arene, per non ricostruirlo
   a mano una quarta volta.
5. **Il grade è in larga parte un indicatore di titolarità**, non di
   qualità: sale all'uscita delle odds, crolla su notizie extra-campo, e
   chi entra un minuto prende ~35 punti di level score. Da qui la riserva
   aperta più importante: quanto vale G *sopra* il filtro starting odds a
   0,80 che il bot già applica — mai misurato, §10bis.

6. **Il grade è in corso di ri-normalizzazione, filone APERTO.** Misurato
   quanto vale ogni lettera (§8bis) e quanto aggiunge al netto di ciò che
   il modello sa già: F −31,0 / E −15,9 / D +1,4 / C +2,4 / B +2,2 /
   A +3,9. Il valore sta nell'**evitare**, non nel premiare. Scoperto
   `projection.score`, un valore continuo dentro `projection` (query
   pubblica): la lettura da confermare è *score = quanto è forte se gioca,
   grade = score + probabilità che giochi*. Dettaglio e stato in
   `docs/handoff/HANDOFF_TABELLA_GRADE_2026-08-09.txt`.

Difetto scoperto e non corretto: il generatore **non è deterministico**
run-to-run (`PYTHONHASHSEED`), §9.

Aggiornamento precedente (08/08 mattina): consolidamento di tutto il
materiale testuale del 06-07/08 (30+ file in
`docs/handoff/`) dentro questo file, come da CLAUDE.md. I file sorgente
restano come archivio ma NON sono più letture obbligatorie: quanto rilevante
è qui. Novità della finestra 06-07/08: **il grade G è entrato in
produzione** (§8bis) dopo un bug di sessione anonima che falsava le run
GitHub (§8quater) e un giro di ottimizzazione performance (stessa sezione).
Sessione precedente (05/08): passaggio 2 **P11** — `P(≥1 boom)` come funzione
obiettivo della formazione, **CHIUSA senza modifiche** (§5); P8 composizione
all-around **CHIUSA**; 16 commit (P1-P9-ter, blend GK `c` 17.5→22) pushati;
pattern arene (§7) + validazione soglie cap 260 (σ 42.70→50.6, pareggio
265→259.5, guadagno 8.8→7.9). Regola di stile: file SNELLO (max ~4 pagine),
sessione/giorno/ora Roma — quando una sezione è superata si comprime, non si
accumula.

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
  ecc.) si applica in arena. **Verificato sui dati l'08/08**: capitano ×1,20
  esatto in 34 casi su 34; xp ininfluente in 4.078 casi (due carte diverse
  dello stesso giocatore con xp diverso, stessa giornata → differenza mediana
  0,00; i pochi casi con differenza si spiegano col RUOLO della carta, D7).
- **Carte rare in arena limited** (regola data dall'utente l'08/08): si
  POSSONO schierare, ma si comportano esattamente come le limited — nessun
  punteggio, bonus o beneficio diverso. Non vanno filtrate dalle analisi.
  Nei file manager sono il 2,5% delle carte in arena.
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

### 4.0 GLI ARCHIVI ARENA — quale usare, com'è fatto (riscritto 09/08)

**Se devi misurare qualcosa sulle arene, parti da qui e non ricostruire
niente a mano.** Gli archivi sono cinque e hanno contenuti diversi;
confonderli è già costato tempo tre volte.

| file | cosa contiene | quando si usa |
|---|---|---|
| **`dati_globali/arene_storico_full_v3.json`** | **L'ARCHIVIO COMPLETO.** 2.125 arene (cap220 755, Beginner 427, cap260 404, Uncapped 354, + 185 del formato vecchio "arena division"/"arena uncapped" da ESCLUDERE). Per ognuna: tutti i punteggi dei partecipanti, `mio_score`/`mio_rank`, `costo`. In più **`premi_veri_per_posizione` su 1.677 arene** (premio reale ai primi 3, jackpot inclusi) e `premio_essenze`/`rank_premiato` su 228 (il premio davvero incassato da un nostro manager) | **soglie, pareggio, guadagno/punto, campo avversario.** È il default per `consiglio_arena.py` via env `ARCHIVIO_ARENE` |
| `dati_globali/classifiche_arene_2026-08-08.json` | 1.677 classifiche complete scaricate l'08/08 (cap220 748, Uncapped 348, Beginner 310, cap260 271) | fonte grezza del pezzo nuovo di v2/v3; serve se si vuole rifare l'unione |
| `dati_globali/premi_arene_2026-08-08.json` | premi veri per posizione delle stesse 1.677 arene, **5.031 osservazioni** (1.677 × 3 posizioni), jackpot inclusi | fonte grezza dei premi; usato per costruire v3 |
| `dati_globali/manager_*.json` (54 file) | le FORMAZIONI: punteggio ufficiale, piazzamento, le 5 carte con ruolo/capitano/xp/rarità. **Non ha i punteggi degli avversari** | qualunque misura statistica su carte, punteggi, ROI, backtest di selezione |
| `dati_globali/arene_storico_full_v2.json` | come v3 ma **senza** i premi veri | solo per confronti storici con misure fatte prima del 09/08 |

**Superati, non usare per misure nuove**: `analisi_manager/p11_pool.json`
(673 arene, è il pezzo vecchio già dentro v2/v3) e
`dati_globali/arene_storico.json` (160 arene, vecchio default di
`consiglio_arena.py`).

**Come è composto v3**, così nessuno lo ricostruisce a mano:
```
p11_pool.json (673 arene, giro vecchio)
   + classifiche_arene_2026-08-08.json (1.677 arene scaricate)
   = arene_storico_full_v2.json (2.125, dedup per slug)   [p25_archivio_v2.py]
   + premi_arene_2026-08-08.json (premi veri per posizione)
   = arene_storico_full_v3.json                            [p28_archivio_v3.py]
```

**Come si allarga, se un test futuro ha bisogno di altre arene:**
- **classifiche** → `scarica_classifiche_v3.py` (cambia la lista slug in
  ingresso e il file di uscita). **Richiede il cookie**: senza
  autenticazione `so5RankingsPaginated` risponde ma torna vuoto.
- **premi** → `scarica_premi_arene.py`, query `rewardsConfig`.
  **NON richiede il cookie**: funziona su sessione anonima.
- Poi si rifà l'unione con `p25_archivio_v2.py` + `p28_archivio_v3.py`.

**Buchi noti di copertura** (da sapere prima di progettare un test):
le classifiche del giro 08/08 furono raccolte con un criterio selettivo —
**tutte** le cap 220 e Uncapped, ma solo un campione per giornata di
cap 260 e Beginner, e **zero arene di lega singola** (us/korea/scotland).
Sul perimetro delle ultime 6 GW questo si traduceva in 269 leaderboard
coperte su 643 (41,8%); le 374 mancanti sono state scaricate il 09/08 per
il test G+odds. Se un test nuovo esce da quel perimetro, ricontrolla la
copertura **prima** di costruirlo.

**Come `consiglio_arena.py` legge i premi** (righe 113-140, modificate il
09/08): se l'archivio contiene almeno una riga con
`premi_veri_per_posizione`, usa **solo** quelli per tutte le righe; se non
ne contiene nessuna, ricade sul vecchio `rank_premiato`/`premio_essenze`.
È **tutto o niente per archivio, mai mescolato riga per riga**: mescolare
aggiungeva osservazioni fuori dal campione di misura e spostava il
pareggio cap260 di 1,3 punti.

---

## 5. Cosa è CHIUSO — non riproporre (compresso il 09/08)

Verdetti di ricerca già pagati. Ognuno costa giorni a rifarlo: prima di
aprire un filone, cercalo qui. Il dettaglio integrale sta nei file citati.

### 5.1 Il punto è piatto, ed è la verità del calcio — non un difetto
Diagnosi 04/08 su 87k osservazioni walk-forward, cinque misure concordi.
Il modello **ordina** (Spearman atteso↔reale 0,17 per ruolo, batte l'L10
grezzo a 0,13) ma la varianza predicibile del singolo voto è ~3%: il resto
è rumore di partita. Eppure **il vantaggio negli esiti è enorme**: fra
quintile alto e basso di atteso ci sono +11,5 punti reali, i boom passano
da 9,9% a 22,9% e i flop da 7,1% a 0,9%. L'edge c'è, è solo invisibile nel
numero medio (std previsto ~4 contro std reale ~19).
Conseguenze operative, tutte dimostrate:
- **non espandere i numeri per "differenziarli"**: la calibrazione OLS dà
  b<1 su DEF/MID/GK, cioè il punto è già leggermente sovra-disperso;
- il **range/dispersione per-giocatore non è calibrato** (pred_std 7→22
  mentre l'errore reale resta piatto a 15-17): è decorativo, non usarlo
  come segnale di volatilità;
- il residuo (reale−atteso) è predicibile a R²=0,008: **non esiste un
  segnale-media libero da aggiungere** con le feature disponibili.
**Inseguire "più differenziazione del punto" è un vicolo cieco dimostrato.**
- **Compressione di scala** (GK 4,8x, altri ruoli 2,5-2,9x): il modello
  ordina bene *dentro* lo slot ma comprime la dispersione assoluta. Il
  danno è **fuori** dallo slot — fascia capitano, scelta della competizione,
  soglie d'ingresso — dove si confrontano numeri di ruoli diversi. Misurato
  e documentato, non risolto.

### 5.2 Segnali provati e bocciati
- **`starter_odds` come variabile continua in `score_atteso`: CHIUSO**, per
  due motivi indipendenti. (1) Non è una variabile nuova: era `p_gioca`,
  rimossa il 28/07 per **decisione di significato** dell'utente —
  `score_atteso` dice "quanto rende SE gioca", il rischio presenza si
  gestisce col filtro secco `MIN_STARTER_ODDS`. (2) **Il dato storico è
  contaminato**: il 64,6% dei valori in cache è 0% o 100% esatto perché il
  campo viene riscritto dopo l'annuncio delle formazioni. In produzione
  nessun problema (si legge prima della deadline), nel backtest è quasi la
  conferma di chi ha giocato. **Qualunque griglia su quel campo misura
  leakage** — e per la stessa ragione il "segnale forte starter_odds
  (corr 0,163)" di un vecchio screening NON è un segnale.
- **Quote bookmaker (favorito odds)**: le 1X2 sono dentro Sorare
  (`Game.homeStats/awayStats.winOddsBasisPoints`), bulk per fixture,
  persistenti da ~18/11/2025 (buco: eliteserien). Per-carta il **DEF passa
  il metro a tre gambe con margine** (7 varianti su 9), GK/MID/FWD mai.
  **In FORMAZIONE l'effetto è ESCLUSO**, non "non dimostrato": su ~37 mazzi
  e ~7.000 arene l'IC95 del delta pesato ha limite superiore mai oltre
  +0,8, che esclude i due risultati isolati (+2,98 e +3,33) mai replicati.
  Il filone come segnale **sopra G** è chiuso a parte, §8nonies.
- **`p_draw`** (quota pareggio): 2 PASS su 64 varianti, entrambi FWD e non
  indipendenti fra loro — con 64 test al 95% il caso ne produce ~3, quindi
  2 è *sotto* il rumore atteso. Bocciato.
- **Trend recente** (`TREND_INTENSITY`): 0,0 su tutti i ruoli e leghe,
  monotono verso il peggio in ogni test.
- **Scomposizione degli all-around per categoria**: nessuna forma soddisfa
  MAE + correlazione + lift insieme, su nessun ruolo (39.594 partite, 26
  leghe, bootstrap appaiato). La compressione che l'aveva motivata riguarda
  solo il `level_score` (scala a gradini), non gli all-around.
- **`fattore_forza_avversario`**: era calcolato e **mai usato**. Rimosso il
  05/08. Il condizionamento sull'avversario che agisce davvero è
  `opponent_lambda_mult` + Stadio D.
- **Bonus additivi vs moltiplicativi**: la formula additiva è verificata al
  centesimo (§3).

### 5.3 Capitano — otto ipotesi, tutte chiuse
Testate su 3.130 formazioni reali: bias di ruolo, volatilità, forma
L5/L10/L40, margine-soglia, stabilità per lega, favorita/sfavorita,
combinazioni, profondità storico, rischio sostituzione precoce, ambiente
gol. **`pick_captain()` non si tocca.** Unico segnale mai vicino alla
significatività: favorita/sfavorita (IC95 [−0,0015, +0,14]), riprovabile
solo con un altro campione reale. Chiuse anche: capitano per tipo di
competizione (il capitano cambia il premio in <2% delle arene), capitano
scelto con la p_win di mercato, formazione concentrata per il capitano
(correlazione −0,006, indifferente).

### 5.4 Boom — tutto chiuso
"Boom" = realizzato ≥75. I boom **decidono il podio** (0 boom → podio
7,6%, 1 → 35,7%, 2 → 68,0%) ma **non sono una leva separata**: sono una
conseguenza del punteggio alto.
- come metrica per scegliere l'arena: non batte `sum_atteso` né `max_atteso`;
- come classifier: l'evento è debolmente predicibile (AUC 0,658) e l'atteso
  fa quasi tutto. Forte eterogeneità per ruolo: l'edge vive sui FWD
  (AUC 0,671), sul **GK non esiste** (0,514 = caso);
- **come funzione obiettivo per costruire la formazione** (la domanda vera):
  bocciata. Massimizzare `P(≥1 boom)` pareggia col mazzo fisso e **perde**
  ad arene isolate (Δpunti −6,04, IC95 [−11,63, −0,35]). Le due policy
  divergono davvero (sovrapposizione 1,3-3,5 carte su 5), quindi non era
  nullo per costruzione: la pendenza ripida dei FWD sposta lo slot extra da
  MID a FWD, si ottengono più boom ma **concentrati**, e la P(almeno uno)
  realizzata scende. In più ottimizzare su `p̂` raccoglie l'errore di stima.
  → **massimizzare la somma degli attesi è già la policy giusta.**
- covarianza fra compagni: ≈0 per squadra; il prodotto dei complementari
  sovrastima P(≥1 boom) di ~3,5 punti percentuali. L'indipendenza regge
  come approssimazione.

### 5.5 Regole di decisione e allocazione
**Dimostrato** (non solo misurato) che le soglie a gradini sono un vicolo
cieco: massimizzare il PREMIO atteso è identico a massimizzare i PUNTI
attesi — 5.768 confronti su 5.768 concordi, zero contraddizioni — perché
l'incertezza sul totale formazione (σ=49,4 pt) è troppo grande perché la
non-linearità del premio conti in pratica. La regola attuale del bot è già
quella giusta.

### 5.6 Portiere — i parametri e la deroga al metro
- **`level_score` binario**: il valore vero è 35 senza clean sheet e 60 con,
  mai intermedio; il modello ne prevede uno continuo. Mitigato dal blend con
  la P(clean sheet) di squadra, non risolto: **resta la leva più grande mai
  lasciata sul tavolo per il GK**.
- **Blend GK, `c` alzato da 17,5 a 22** (`GK_TEAM_CS_WEIGHT` 0,5→0,63): la
  correlazione cresce monotona con `c`, il MAE peggiora monotono —
  compromesso puro, nessun valore dominante. Scelto 22 (dcorr +0,0033 con
  IC che esclude lo zero, dMAE +0,0227 contro una guardia di +0,05);
  scartato 26 perché il guadagno diventa rumore mentre il degrado raddoppia.
  **Prima e unica deroga al metro a tre gambe**, limitata a questo
  parametro: per il GK conta l'ordinamento (se ne schiera uno solo), non il
  voto. Bocciate le tre "correzioni ovvie" (POINTS→25, baseline
  per-portiere, `p_cal` affine): migliorano il MAE e peggiorano la
  correlazione, e `p_cal` è algebricamente identico ad abbassare il peso.
- **Il lift di selezione non discrimina sui portieri** (IC larghi 4-8 punti
  su 120 giornate): sul GK il metro è di fatto a due gambe. Non costruire
  una terza metrica per aggirarlo — deciso, non riproporre.

### 5.7 Difetti nati qui e ancora aperti
- **Refit vero di `CALIB_PER_RUOLO` mai completato (P10)**: manca nel repo
  lo script che calcola i 4 coefficienti `CALIB_A/B_*` (esistono solo
  hardcoded, `build_formazione_globale.py:394-399`), e la retta "in
  produzione" 63,43+0,736x non coincide né col rigenerato vecchio
  (40,64+0,823x) né col nuovo (33,49+0,853x). Scollegata da tempo. La
  verifica di catena fatta per il blend GK è **analitica, non un refit**:
  da rifare alla prossima occasione in cui `taratura_coppie.json` viene
  comunque rigenerato. Non blocca: lo spostamento è sotto l'incertezza nota.
- **`backtest_arene_previsioni.py:257-260`** ha ancora default
  `GK_TEAM_CS_WEIGHT=0.5` col commento "come produzione" — **falso** dopo il
  passaggio a 22/35. Chi usa quel modulo senza esportare la variabile misura
  un modello che non esiste più. Meglio leggerlo da `test_gk` che duplicarlo.
- **I 4 coefficienti OLS reale=a+b·atteso NON sono riproducibili dal repo**:
  nessuno script li ha mai calcolati, l'unica occorrenza è una citazione in
  un report. Non usarli come conferma indipendente di nulla (è già costato
  un falso collegamento). La conclusione che ne dipendeva — non espandere i
  numeri — resta valida perché poggia su altre quattro misure.
- **D2 — misuratore e produzione non condividono la stessa P(clean sheet)**:
  `test_gk.py` usa il cutoff esatto, `_pcs_squadra` la griglia settimanale.
  Si lascia e si documenta (allinearlo costerebbe una `stima()` per ogni
  giocatore-partita): irrilevante per i confronti fra varianti, rilevante
  per le stime assolute di lift/correlazione sul GK.

### 5.8 Due trappole di metodo, pagate care
- **BUG D6 (storia, chiuso)**: tre script di backtest leggevano il punteggio
  realizzato dai file manager invece che dalla cache game-log, e quel campo
  include xp+capitano sulle righe non-arena — fino al 77% delle carte
  gonfiate. I verdetti di *formazione* costruiti su quegli script sono
  NULLI. Da qui la regola in CLAUDE.md: l'orchestratore verifica i dati
  grezzi di un esecutore, non il suo commento.
- **Prima di riusare dati o script di una sessione precedente, verifica che
  l'`n` coincida** con quello dichiarato nel report. Due casi reali di
  numeri "già misurati" non riproducibili dal materiale ereditato.

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

0. **`formazione_giornata.yml` senza fixture esplicita prende la giornata NON
   ANCORA INIZIATA, non quella in corso** (scoperto dall'utente l'08/08,
   dopo una run buttata). Il campo `gameweek` accetta anche il solo numero
   della fixture corrente (es. `3`). Altra trappola dello stesso workflow:
   **`arene` ha default `0`** — se non lo si valorizza, non viene generata
   nessuna arena e il run non serve a niente.
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

## 8bis. Grade G — VALIDATO il 09/08, resta in produzione

**Cos'è**: `So5Score.projection.grade` (A→F), voto per giocatore-partita
pubblicato prima del fischio d'inizio. Si legge con
`anyPlayer(slug).playerGameScores.projection.grade` — query pubblica, vale
anche per giocatori non posseduti. **È il voto della PARTITA, non del
giocatore**: lo stesso giocatore ha lettere diverse per due partite
ravvicinate entrambe da giocare.

**Cosa misura davvero (chiarito il 09/08, e cambia la lettura di tutto):**
il grade è in larga parte un **indicatore di titolarità**, non di qualità.
Prove: sale all'uscita delle odds per chi risulta titolare a sorpresa
(F→E, osservato in diretta); Messi ha 10 A e 5 F su 15 partite, mai un
voto intermedio, ed è passato da A a F su una notizia extra-campo. Si
tiene insieme con il **level score**: chi entra anche un solo minuto
prende ~35 punti, quindi la distanza fra "non gioca" e "gioca" è più
grande di quella fra una prestazione mediocre e una buona.

**Formula in produzione** (per gruppo lega/ruolo):
`atteso_combinato = atteso_calibrato + sd_gruppo × z_grade`. Sposta la
selezione, non è un tie-break. Riferimento:
`analisi_manager/p12_backtest_formazione_grade.py`. In produzione dal
07/08 (`GRADE_ENABLED` default `'1'`, rollback con `=0`); la fetch sta in
`discovery_fixture.py::fetch_grade_live()`, dopo il filtro starter-odds.

**NON-ARENA — dimostrato**: +5,98 su 864 formazioni (All Star + U23),
+6,46 su 310 (MLS Hot Streak). Placebo: il grade vero batte tutte le
permutazioni (percentile 100), e **la mediana placebo è negativa** (−1,51
e −3,72) — dare voti a caso peggiora, che è la firma di un'informazione
vera. Bootstrap sui manager: IC [+4,87, +10,38] e [+2,58, +12,12].

**ARENE — dimostrato il 09/08, dopo due tentativi inconcludenti.** I test
precedenti non distinguevano G dal rumore, ma giravano su una copertura
del grade del 54,6% (cap 220: 42,9%). Portata al **98,8%**, il risultato
esce netto. Campione: 825 formazioni, 24 manager, 6 GW, sette competizioni
arena limited. Metrica in **essenze nette** (premi standard, jackpot in
colonna a parte), due regimi separati:
- **allocazione** (53 unità, pool > slot): G batte A di **+29.050**
  essenze col set di soglie vecchio e **+24.150** col nuovo. Placebo al
  percentile 100 su entrambi (il massimo del rumore è 12 volte più
  piccolo del valore vero). Il bot gioca **meno** arene del manager (547
  contro 617) e guadagna: concentra invece di spalmare;
- **astensione** (37 unità, pool = slot): nessun ramo significativo.
Tre limiti noti **comprimono** il vantaggio invece di gonfiarlo: il rank
si calcola sulla classifica completa (il bot compete anche col manager che
c'era davvero), il capitano è scelto col criterio del baseline in tutti i
rami, e le formazioni senza arena reale a cui assegnarle contano come non
premiate. Dettaglio: `docs/handoff/HANDOFF_G_ODDS_ARENE_2026-08-09.txt`.

**LA RISERVA CHE RESTA, mai misurata**: in produzione il bot filtra già le
starting odds a 0,80, che catturano la stessa informazione di titolarità.
Quanto di quel +29.050 sopravvive sopra quel filtro non lo sa nessuno —
voce a backlog (§10bis).

**DIFETTO STRUTTURALE, ancora aperto**: il grade entra come confronto coi
pari dentro il gruppo (lega, ruolo) di quella giornata
(`_apply_grade_group`, righe 452-491). Se il gruppo ha meno di 2 carte col
grade, o se hanno tutte lo stesso voto, **il grade viene ignorato**: su un
mazzo reale, 19 gruppi su 57 hanno un solo membro, e il grade sposta
qualcosa sul 77% delle carte, viene ignorato sul 23%. La cura provata
(**scala storica**, flag `GRADE_SCALE`, default spento) è stata **misurata
e scartata**: pareggia sul non-arena e sull'arena peggiora proprio sulle
Cap 260, il tipo più giocato. Non riproporla senza un'idea nuova.
Riserva collegata mai misurata: dove il gruppo ha esattamente 2 carte col
grade lo spostamento è meccanico ±1 sd.

**TABELLA FISSA per lettera — SECONDA cura al 23%, CHIUSA il 09/08 sera.**
Idea: dare a ogni lettera un valore FISSO (invece dello z-score di gruppo), così
il grade agisce anche dove il gruppo è <2. Come e perché il test: si è confrontato
G variabile (z-score) contro G fisso, ma con tre pulizie che i giri precedenti non
avevano (§20-26 di `HANDOFF_TABELLA_GRADE_2026-08-09.txt`): (a) stesso pool ridotto
ai due rami; (b) popolazione = pool SENZA carte F (proxy di titolarità ≥0,80, vedi
verifica live sotto), perché sotto 0,80 l'utente non schiera; (c) i valori fissi
NON assunti ma cercati a **griglia** (7 tabelle × versione centrata × 2 set soglie),
letti a **parità di arene**. Esito: NESSUNA tabella batte lo z-score su entrambe le
soglie — **il fisso NON vince**. L'apparente "+8000" della tabella empirica sul pool
intero era tutto l'affossamento delle F post-partita: tolte le F, svanisce. Unico
segnale residuo sulle arene-PAESE piccole (US/Korea/Scotland, n=6), dove però anche
il placebo "grade spento" pareggia il fisso: non è vittoria del fisso, è lo z-score
che su leghe minuscole (gruppi <2) è lievemente controproducente — indizio per la
riserva del 23% qui sopra, non una cura. Non riproporre la tabella fissa senza
un'idea nuova.

**Verifica live 09/08 (Genk-Zulte, cattura pre e post ufficiali, §23 stesso
handoff grade):** sulle carte già date ≥0,80 al lock il grade NON cambia con le
ufficiali (18/18 identiche pre→post); TUTTI i cambi (2 crolli a F per panchina/fuori
lista, 4 salite quando il titolare è confermato) sono su carte <0,80. Conseguenza
metodologica: per la popolazione di produzione (≥0,80) il grade al LOCK coincide col
grade FINAL, quindi backtestare sul grade final è un **proxy pulito** lì (il timore
"grade post-partita che sballa il backtest" non tocca ≥0,80); sotto 0,80 il grade si
muove nei due sensi. Nota separata verificata sui grezzi: le odds pre-partita NON
sono recuperabili a ritroso — per una partita chiusa l'API le ridà congelate a 0 o
10000 (0 valori intermedi su 5.775 righe Forward), l'unica fonte del lock è la
cattura live.

**Catena soglie/scouting per G — verificata e chiusa**: σ di calibrazione
A=48,13 vs G=49,32 (IC sovrapposti), soglie arena delta <1,1 pt. G non
muove nessuno dei due anelli a valle.

**Trappola sul metro di qualità**: confrontare `atteso_combinato` A vs G
NON è un giudizio di qualità — è il punteggio di selezione, gonfiato per
costruzione quando G è acceso. Il metro vero è il **realizzato** su GW già
giocate.

**Base pulita, come si costruisce** (vale per ogni analisi sui file
manager): niente arene; tutte le carte di rarità `limited` filtrando sulla
CARTA e non sull'etichetta della competizione; somma dei punteggi = punteggio
ufficiale Sorare entro 0,5; per All Star/U23 solo leaderboard `division-N`.
**Difetto con effetti oltre G**: il campo `in_season` nei file manager è
letto al momento dell'estrazione (`ricostruisci_manager.py:279`), quindi dice
se la carta è in season *oggi*, non quando fu schierata — le competizioni con
quel vincolo non sono ricostruibili a ritroso.

**Chiuse, non riaprire**: le 3 anomalie non-arena (Hot Streak con 1 classic,
famiglia "Limited" mista 7/5 carte, bonus XP nel backtest), risolte l'08/08.

---

## 8ter. Scouting dopo il grade (07/08/2026) — CONTROLLATO, 2 decisioni aperte

Domanda dell'utente: se il generatore aveva un problema di autenticazione lo
avrà anche lo scouting? E il grade ci entra?

**Non è rotto**: `scouting_gw.py` non fa nessuna query autenticata (zero
`myFilteredBench`/`currentUser`/`owner`), quindi il bug di sessione anonima
(§8quater) non lo tocca — RISCHIO LATENTE però: usa `_gql` da
`mls_def_discovery_global.py`, che non manda CSRF; se un domani gli si
aggiunge una query autenticata, ricade nello stesso bug. Le odds sono già in
bulk dal 03/08. `ESCLUDI_LOCKATE` non lo riguarda (scrive solo
`player_slugs.json`, mai `player_card_counts.json`).

**Il grade non c'è, per un motivo strutturale non una dimenticanza**: quello
di produzione viene da `myFilteredBench` (carte POSSEDUTE); per una carta da
comprare quella via non esiste. Esiste un'alternativa
(`anyPlayer.playerGameScores(last:15).projection.grade`, verificato
funzionante su carte non possedute — vedi §8bis) ma dà il grade STORICO
delle partite passate, non una proiezione per la giornata da giocare.
**Decisione aperta con l'utente**: non è ovvio che un segnale per-giornata
debba pesare su una decisione d'acquisto pluri-giornata.

**Altro aperto, minore**: leghe senza pipeline (`nb-i`, `nb-ii`,
`premier-division-ie`, `premier-league-am`, `super-liga-sk`, `virsliga`) non
ricevono atteso; 429 occasionali (danno piccolo, run 2.7-3.8 min); job
`candidati` sovrascrive `player_slugs.json` di produzione per le leghe
toccate fino alla prossima run `formazione_giornata`.

---

## 8quater. Infrastruttura estrazione grade — 3 bug chiusi, 1 aperto (07/08)

**1. Bug sessione anonima (CSRF) — CHIUSO.** Causa dei "0 nodi grade" nelle
run GitHub (mezza giornata persa, 5 ipotesi sbagliate prima di trovarla:
leaderboard chiusa, secret scaduti, header Origin/Referer, header client
Web, IP datacenter — tutte smentite da una misura). Causa vera: una funzione
condivisa (`graphql_query`, importata da 4 script) mandava il Cookie ma non
il CSRF; Sorare la tratta come non autenticata e restituisce un Set-Cookie
che assegna una sessione ANONIMA — `curl_cffi` la salva e da lì in poi VINCE
silenziosamente sull'header Cookie autenticato passato a mano. Risultato:
`currentUser=null`, HTTP 200, nessun errore — indistinguibile da "giornata
chiusa". Sembrava un problema solo-GitHub perché la discovery fa decine di
query pubbliche prima del grade: i test locali isolati (solo bench) partivano
sempre su sessione pulita e riuscivano sempre. Fix in main:
`discovery_fixture.py::_grade_http()` usa sessione dedicata svuotata prima di
ogni richiesta; `graphql_query()` manda `x-csrf-token` sempre. Restano ~381
copie della stessa funzione (senza CSRF) in giro nel repo, non toccate di
proposito: fanno solo query pubbliche, a rischio SOLO se un domani una di
loro diventa autenticata. **Regola che ne esce**: quando una query "my"
torna vuota, la prima domanda è "questa sessione è autenticata?"
(`{currentUser{slug}}`), non "il dato esiste?".

**2. Fetch moltiplicata per 20 / 429 — CHIUSO.** Ogni shard del workflow
rifaceva per conto suo l'intera fetch grade (3 leaderboard × 4 ruoli × fino a
20 pagine, ~240 richieste): 20 shard = ~4.800 richieste a run per lo STESSO
risultato, causando paginazioni troncate dai 429 (dato mancante
indistinguibile da dato completo — il tipo di errore più pericoloso).
Fix: job `grade` unico nel workflow (fetch una sola volta, passata come
artifact di run — non è una cache, nasce e muore nella run), backoff 429 più
lungo in paginazione (dice quando si arrende, non tronca in silenzio), probe
di autenticazione con retry sui 429 (senza retry un 429 veniva letto come
"sessione morta", diagnosi sbagliata). Risultato misurato su 3 run della
stessa giornata: 26.3min/156 429/parziale → 6.8min/19 429/877 grade completi,
stesso identico esito finale (0 differenze su 308 righe sopra soglia).
**Regola nuova dell'utente**: la run intera deve stare sotto i 10 minuti; se
un cambio la riporta sopra, è un difetto da correggere, non un costo da
accettare.

**3. `ESCLUDI_LOCKATE` — implementato e verificato.** Problema reale: a
giornata iniziata alcune formazioni sono bloccate (`canEdit=false`) e le
loro carte non si spostano più; rilanciando il generatore le riusava,
proponendo arene non più schierabili. Query:
`so5Fixture→so5LeaderboardGroups→mySo5LeaderboardContenders→so5Lineup{canEdit,
so5Appearances{anyCard{slug}}}` — la chiave è lo slug della CARTA (non del
giocatore: chi ha 3 carte dello stesso giocatore e ne blocca una può
schierare le altre due). Input workflow `escludi_lockate`, default 0
(spento); se la lettura fallisce il job fallisce apposta (niente tutela
silenziosa). Verificato su run vera: 71 carte escluse = esattamente le carte
delle 11 formazioni bloccate, zero perse o doppiocontate.

**4. Soglie arena cap 220 — INDAGATO, NON un difetto di taratura.** Dubbio
dell'utente: su 30 arene proposte, 29 erano cap 260 e zero cap 220, sembrava
impossibile. Verificato che l'algoritmo sceglie bene DATE le soglie (prova
tutti i tipi ogni passo, la 220 non vince mai con questo mazzo). Sul valore
delle soglie stesse: **misurato che NON è la cap 220 a essere sottostimata**
— prendendo per ogni tipo la SUA sigma e i campi veri, lo scarto fra
ricalcolo e produzione è lo STESSO su entrambi i tipi (cap260 +6.3, cap220
+6.5); la distanza fra i due tipi (quella che decide quale arena si sceglie)
coincide entro 0.2 punti fra ricalcolo e produzione. Con questo mazzo le cap
260 hanno un atteso ~24 punti sopra le cap 220, mentre le soglie distano solo
15: **le 260 vincono per merito del mazzo, non per un bug**. Resta un
+6.4 di scarto sistematico fra ricalcolo e produzione non spiegato (non
cambia la scelta FRA tipi, sposta se entrare in generale) — coerente col
fatto che l'utente già alza le soglie a mano sui margini bassi. Verificato
anche: nessuna selezione nel pool di 55 manager usato per il calcolo (scarto
+1.5/+2.5 sul campione ben alimentato vs i campi veri dell'utente), premi
richiedibili per QUALUNQUE arena via `so5Leaderboard(slug).so5Rewards`
(sbloccando il campione da 30 a migliaia di osservazioni), punteggi non
gonfiati dal bug D4/D6 (letti dai nodi ufficiali `so5RankingsPaginated`, non
ricostruiti). **Decisione dell'utente: non si tocca ora** (le arene
schierate finora avevano atteso 300+, sarebbero finite in cap 260 comunque —
zero costo reale). Da fare con calma: capire lo scarto +6.4, raccogliere più
arene cap 220 prima di ritarare, ricordare la catena CLAUDE.md (le soglie
muovono anche lo scouting). Dettaglio:
`docs/handoff/BRIEF_SONNET_SOGLIE_ARENA_2026-08-07.txt`.

**Minore**: fix estetico applicato (clic per copiare il nome carta ora
funziona anche cliccando il cerchio avatar, non solo il nome — solo
`formazione_mls`, le altre 25 leghe non hanno la feature). `arene_storico.json`
è passato da 673 a 160 arene fra l'1 e il 6/08 — **CHIUSO l'08/08: non è un
bug.** Gli archivi sono DUE, con scopi diversi (uno grande e uno piccolo), e
il confronto li aveva trattati come se fossero lo stesso file: era un
disallineamento di lettura, non una perdita di dati. Le 191 "division" erano
già state tolte su richiesta esplicita dell'utente. Non riaprire.

---

## 8sexies. Cap arena sforato — l'L10 è della CARTA, non del giocatore (08/08)

**CHIUSO.** Sintomo: arene generate che Sorare rifiutava (`-4/260`), sempre,
non ogni tanto. Prime due ipotesi **sbagliate**, entrambe smentite da una
misura: (a) "cache stantia" — no, l'API interrogata dal vivo dava lo stesso
identico valore del nostro `player_card_counts.json`, 0 differenze su 125
carte; (b) "Sorare sfarfalla / mettiamo un margine di sicurezza sul cap" — no,
lo scarto va in **entrambe** le direzioni, un margine non lo copre.

Causa vera, trovata partendo dall'intuizione dell'utente sul ruolo: si leggeva
`anyPlayer.averageScore(LAST_TEN_PLAYED)` = L10 del **giocatore**, mentre
Sorare capa su `ComposeTeamBenchCard.averageScore` = L10 della **CARTA**, che
pesa i punteggi col ruolo con cui la carta è stata EMESSA. È il **D7 già noto
sul ruolo** (Sorare cambia ruolo a un giocatore, le carte già emesse tengono
il vecchio) applicato a un campo su cui nessuno aveva mai guardato.

Misurato su 400 carte vere del mazzo:

| | carte | L10 identiche | L10 diverse |
|---|---|---|---|
| ruolo carta = ruolo giocatore | 373 | 362 (97%) | 11, tutte entro ±2 |
| **ruolo carta ≠ ruolo giocatore** | 27 | 11 | **16, fino a ±5** |

Casi: `jeppe-erenbjerg` (carta FWD / player MID) 62→66; `melle-meulensteen`
(carta DEF) 47→52; `anders-dreyer` (carta MID / player FWD) 66→61. L'arena
rifiutata risomma a **264 esatti** col campo giusto (57+53+41+61+52).
Verificato anche che il valore **non dipende dalla leaderboard** (arena e
non-arena danno lo stesso numero).

Fix in `discovery_fixture.l10_carte_da_bench()` (commit `00d0b42f01`): mappa
`(slug, ruolo) -> L10 di carta` da `myFilteredBench`, **862 coppie in 3.4s**,
nessun 429; il valore entra in `player_card_counts.json` al posto di quello
del giocatore, con ripiego su di esso se manca il cookie o la carta non è nel
bench. In `CardPool` l'`_l10` resta indicizzata per slug (i ~180 chiamanti in
25 leghe passano solo quello) ma per gli slug con carte in ruoli diversi
(5 su 738) si tiene ora il **massimo** invece dell'ultimo letto, che dipendeva
dall'ordine dei ruoli. Soglie NON toccate: cambia quali carte entrano in
arena, non lo `score_atteso`.

**Trappola da ricordare**: `positions: []` nel filtro bench NON vale "tutte" —
tornano def/mid/fwd e **zero portieri** (293/240/210/0), buco intero e
silenzioso. Si pagina **per posizione**, come fa già il grade.

**Minore (08/08)**: il clic per copiare il nome nell'HTML non funzionava più
— né sul cerchio né sul nome. Un apostrofo non escapato nel tooltip del tasto
"fatta" (`gia' schierata`) chiudeva la stringa JS a metà e mandava in
SyntaxError l'**intero** script: morti anche il tasto FATTA e l'avanzamento in
localStorage. Commit `b1cbf53db6`.

---

## 8septies. Il criterio di scelta fra tipi di arena ignora il costo (08/08, APERTO)

Osservazione dell'utente: su ~35 arene proposte, **34 erano cap 260 e quasi
mai una cap 220**. Due riverifiche delle soglie non avevano trovato niente,
e infatti **le soglie non sono il problema** — l'indagine del 07/08
(§8quater punto 4) era corretta.

**Le soglie sono ben calibrate fra loro**: sulle arene reali in archivio le
cap 220 fanno in media 247,8 punti (soglia 244,1) e le cap 260 ne fanno
263,3 (soglia 259,5). I punteggi distano 15,5, le soglie 15,4: rispetto al
proprio pareggio i due tipi stanno alla stessa distanza.

**Il problema è il criterio di confronto** (riga 1267,
`genera_arene_efficienti`): `resa = (atteso − soglia) × GUADAGNO_PER_PUNTO`,
si sceglie la resa più alta, e **il costo d'ingresso non entra**. Siccome
GUADAGNO_PER_PUNTO vale 7,9 per la cap 260 e 6,3 per la cap 220, a parità
di margine la 260 vince sempre del 25%. Ma costa 300 contro 200:

| | costo | essenze/punto | rendimento per punto sul capitale |
|---|---|---|---|
| Cap 260 | 300 | 7,9 | 2,6% |
| Cap 220 | 200 | 6,3 | **3,2%** |

**La realtà conferma, su due fonti indipendenti.** Dai file manager (premi
base, golden non distinte, quindi ROI sottostimati ma confrontabili): su
tutti i 54 manager cap 260 −7,0% (n=2506) contro cap 220 −4,9% (n=968); su
crowss cap 260 +1,6% (n=146) contro cap 220 **+23,3%** (n=45). Da un sito
di tracking indipendente (dati reali dell'utente, 710 ingressi, ROI
complessivo 11,79%): cap 260 +20,0% (n=202), cap 220 **+54,5%** (n=55),
uncapped −8,8%, beginner −20,9%; per costo d'ingresso, 300 → +17,5% e
200 → +54,5%. **L'ordine dei tipi coincide fra le due fonti**; i livelli
differiscono perché il repo non distingue le golden.

Due bias da citare sempre insieme a quei numeri: l'utente giocava le cap 220
solo "quando vedeva un buon incastro" (arene **selezionate a mano**, ROI
gonfiato), e le cap 220 sono strutturalmente più rare perché il vincolo
L10 ≤ 220 rende difficile trovare combinazioni valide.

Quale criterio sia giusto dipende da **quale risorsa è scarsa**: se sono le
carte, vince il guadagno assoluto (criterio di oggi); se sono le essenze,
vince il rendimento sul capitale. Risposta dell'utente: "dipende dalla
giornata" — ma l'08/08 aveva 6.000 essenze e carte per oltre 40 arene, cioè
il vincolo erano le essenze.

**ESITO (09/08, notte) — il criterio "capitale" NON migliora, e le soglie
erano giuste.** Due misure, entrambe chiuse:

1. *Criterio a rendimento sul capitale* (`ARENA_CRITERIO='capitale'`,
   implementato e **lasciato spento**): su GW3 propone 22 arene invece di 23,
   promuove la cap 220 dalla posizione 22 alla 7 — ma **rende meno**
   (0,294 essenze per essenza impegnata contro 0,317), e anche a budget
   fisso di 6.000 essenze resta sotto (1.876 contro 2.113). Perché il
   ragionamento teorico non reggeva: vale *a parità di margine*, ma il
   vincolo L10 ≤ 220 costringe a carte deboli, quindi le cap 220
   costruibili stanno appena sopra il pareggio e un vantaggio percentuale
   su un margine minuscolo resta minuscolo.
2. *Taratura delle soglie*, rifatta su un archivio 14 volte più grande
   (vedi §8octies): la cap 220 si sposta di **meno di un punto**. Il
   rapporto fra i guadagni per punto resta **0,78**, contro lo 0,80 di
   produzione — l'ipotesi dell'orchestratore che fosse 0,88-1,00 è
   **smentita dai dati**.

**Conclusione: le 34 cap 260 su 35 non erano un difetto.** Con questo mazzo
le cap 260 vincono per merito, non per un errore di taratura. Non riaprire
il filone del criterio senza un'idea nuova.

Brief: `docs/handoff/BRIEF_SONNET_CRITERIO_ARENE_2026-08-08.txt`; esito
`docs/handoff/HANDOFF_CRITERIO_ARENE_2026-08-08.txt`.

---

## 8octies. Soglie arena ritarate su 2.125 arene + premi veri — APPLICATO 09/08

**STATO (09/08/2026, notte Roma): APPLICATO IN PRODUZIONE.** Eseguito da
Sonnet su BRIEF_SONNET_APPLICA_SOGLIE_2026-08-09.txt. Dettaglio completo
in `docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` §13. Valori
finali in `generatore_formazioni/build_formazione_globale.py`
(PAREGGIO_ARENA/GUADAGNO_PER_PUNTO):

| tipo | pareggio | guadagno/pt | costo |
|---|---|---|---|
| cap 260 | 259,5 → **264,5** | 7,9 → **6,96** | 300 |
| cap 220 | 244,1 → **247,1** | 6,3 → **5,11** | 200 |
| Uncapped | 288,3 → **279,6** | 8,0 → **5,88** | 300 |
| Beginner | non esisteva → **256,5** (NUOVO tipo, `ARENA_ALLSTARS_BEGINNER`) | — → **2,46** | 100 |
| Elite | 342,7 INVARIATA (esclusa dal perimetro) | 9,1 INVARIATA | 800 |
| arene dedicate | 262,9 INVARIATO (misura propria, non ricalcolabile) | 8,8 → **6,96** (allineato a cap 260) | 300 |

Fonte: premi VERI via rewardsConfig, 1.677 arene scaricate, 5.031
osservazioni (contro le 141 precedenti). Catena verificata fino allo
scouting incluso (legge i valori via `getattr(gg, ...)`, nessuna modifica
necessaria in scouting_gw.py). Non pushato su main, in attesa dell'utente.

--- SEZIONE STORICA (09/08 sera, superata dall'applicazione sopra) ---

**L'archivio è stato ricostruito**: scaricate le classifiche complete di
1.677 arene (`dati_globali/classifiche_arene_2026-08-08.json`), unite alle
673 preesistenti → `dati_globali/arene_storico_full_v2.json`. Per la cap 220
si passa da **53 a 755** classifiche complete, per l'Uncapped da 38 a 354.
Il download è stato **validato** su 2.431 righe dei file manager di cui
conoscevamo già punteggio e piazzamento: 99,6% dei punteggi ritrovati, 99,8%
alla posizione giusta.

| tipo | pareggio: produzione → nuovo | guadagno/pt: produzione → nuovo | costo |
|---|---|---|---|
| cap 260 | 259,5 → **260,2** | 7,9 → **6,93** | 300 |
| cap 220 | 244,1 → **243,2** | 6,3 → **5,42** | 200 |
| Uncapped | 288,3 → **282,4** | 8,0 → **5,95** | 300 |
| Beginner | non esisteva → **259,2** | — → **2,34** | 100 |

**I pareggi sono confermati** (scarti di 0,7-0,9 punti sui due tipi
principali) e **stabili**: dividendo le arene in due metà casuali i pareggi
distano 0,3 (cap 260) e 1,4 punti (cap 220), un ordine di grandezza sotto la
soglia di fragilità. Quello che si muove davvero è il **guadagno per punto**,
in calo del 12-26% su tutti i tipi. Effetto su GW3: 24 arene invece di 23
(+1 cap 220).

**LIMITE APERTO, ed è il prossimo lavoro**: il campione dei **premi** non è
cresciuto — **199** osservazioni dopo deduplica (non 235: quel numero
contava anche righe perse per uno slug duplicato nel file vecchio, vedi
`docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` §11), di cui **141**
sono quelle che contano davvero per le soglie (tolti arena division e arena
uncapped, esclusi dal calcolo), **20 per la cap 220** — perché il download
portava le classifiche ma non i premi incassati. Quindi metà del calcolo
(quanto è fitto il campo) è ora solidissima, l'altra metà (quanto si
incassa) poggia ancora su pochi casi. È proprio la metà da cui dipende il
guadagno per punto, cioè il numero che si muove di più.
09/08 sera: verificato che si può leggere il premio VERO di ogni arena
chiusa (jackpot incluso) via `rewardsConfig.ranking.rewardConfigs`, **senza
cookie**. Batch di 1.677 query in attesa del via utente, vedi
`docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` §11.

**Decisione dell'utente (09/08): si scaricano anche i premi, poi si
applicano le soglie.** Non tocca `score_atteso`: cambia solo l'efficienza,
cioè quali arene conviene giocare e cosa consiglia lo scouting.
Dettaglio: `docs/handoff/HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` §10.

---

## 8nonies. Favorito odds sopra G — FILONE CHIUSO (09/08)

Le **starter odds** (probabilità che il giocatore sia titolare) restano
quello che erano e **non si toccano**: filtro a 0,80 in discovery più
tie-break a parità di atteso entro 1 punto. Qui si parla delle **favorito
odds** (quanto la squadra è data favorita).

**Esito finale: non aggiunge nulla sopra G, in nessuna condizione
provata.** Non è un test nullo — l'interruttore è stato verificato ogni
volta (a k=0 coincide col baseline bit per bit; acceso, riordina il 57-94%
delle carte e cambia almeno una carta nel 50-71% delle formazioni). Le
odds riordinano moltissimo e in media azzeccano quanto sbagliano.

Cosa è stato provato, tutto negativo o nullo:
- **delta storico** (scarto dalla media del giocatore) sul non-arena: mai
  IC positivo in nessun ruolo;
- **livello assoluto** (la quota della partita, senza storico) sul
  non-arena: idem, con due scelte di scala diverse (z-score per gruppo, e
  grezzo con k calibrato a parità di effetto). In più risolveva un difetto
  reale — il delta dà segnali opposti a due giocatori della stessa partita
  — e alzava la copertura dal 59,9% al 77,5%: **la copertura maggiore non
  si è tradotta in punti**;
- **sopra G nelle arene** (09/08, il test più pulito): G+O contro G è
  sempre negativo come stima (−4.000 e −8.550) e mai significativo.

Perché non funziona, per quanto si può dire: il livello assoluto è più
correlato allo `score_atteso` di quanto lo sia il delta (+0,22 contro
+0,09), quindi porta informazione che il modello ha già — è il doppio
conteggio che aveva motivato la scelta del delta a suo tempo.

**Buco di copertura che resta**, se un giorno serve per altro: l'archivio
quote parte da ~18/11/2025 (eliteserien sempre esclusa), e il mancante è
**al 100%** dovuto a quello, non ad altri difetti — misurato. Le quote
sono per SQUADRA, non per giocatore, quindi recuperarle costerebbe una
manciata di chiamate per giornata.

Dettaglio: `docs/handoff/HANDOFF_ODDS_SEGNALE_DOPO_G_2026-08-08.txt` §9-12
e `docs/handoff/HANDOFF_G_ODDS_ARENE_2026-08-09.txt`.

---

## 8undecies. COME SI PARLA CON L'API SORARE — i tre pezzi (09/08)

Scritto perché nella notte del 09/08 due esecutori si sono bloccati per ore
su questo, e la risposta era già nel codice. **Chiunque scriva uno script che
interroga Sorare in modo autenticato deve avere TUTTI E TRE i pezzi**:

1. **`x-csrf-token` su ogni richiesta.** Senza, Sorare risponde con un
   `Set-Cookie` che assegna una sessione **anonima**.
2. **Sessione HTTP dedicata, col barattolo dei cookie svuotato prima di ogni
   richiesta** (`discovery_fixture._grade_http()`, righe 94-125). Serve
   perché `curl_cffi` **salva** quel cookie anonimo e da lì in poi vince su
   quello autenticato passato a mano nell'header. Misurato: bench su
   sessione pulita → 50 nodi; dopo **una sola** query senza CSRF → 0 nodi.
   Non serve che sia la tua richiesta a essere sbagliata: basta che lo sia
   stata una qualunque precedente sulla stessa sessione.
3. **Header di client Web** (`discovery_fixture._headers_client_web()`,
   righe 127-160): `sorare-client: Web` + `sorare-version` + `sorare-build`
   (dai secret `SORARE_VERSION`/`SORARE_BUILD`, cambiano a ogni release del
   sito) più Origin, Referer e i `sec-fetch-*`. Il commento lo dice chiaro:
   **da casa Sorare è tollerante, da datacenter pretende il set completo**.
   È il motivo per cui l'utente naviga senza problemi mentre uno script
   prende 429 immediati.

**Come si diagnostica in dieci secondi**, prima di lanciare qualunque batch:
`{ currentUser { slug } }`. Se risponde con lo slug, sei autenticato e
eventuali 429 sono un vero rate limit (rallenta). Se torna `null`, **non è
rate limit**: è sessione anonima, e nessun backoff ti salverà.
Attenzione: la probe stessa può prendere 429 — va fatta con retry, altrimenti
un rate limit viene letto come "sessione morta" (errore reale del 07/08).

**Regola pratica**: non costruire header o sessioni nuove. Riusa
`_grade_http()` e `_headers_client_web()`. Se un esecutore inizia a parlare
di *fingerprint*, non sta delirando — serve davvero, ma **esiste già** in
`bots/bot_definitivo.py`, che gira autenticato da GitHub Actions da mesi.

---

## 8quinquies. Altri fili aperti del 06-07/08 (riepilogo secco)

- **`crowss` = l'utente stesso, verificato NON contaminare nulla** (D1):
  assente per costruzione dal verdetto capitano (`p11_bloccato_tutti_mazzi.py`
  lo esclude hardcoded) e dallo smart-money (0 righe in tutte le GW
  controllate). L'unico posto dove è nel campione, legittimamente, è il
  backtest formazione di G (uno dei mazzi profondi). Chiuso, non riaprire.
- **Odds+4ruoli — filone IN PAUSA**: griglia per-carta pulita conferma DEF
  forte (7/9 varianti), GK/MID mai, FWD al limite; ma in FORMAZIONE il
  backtest (45 mazzi) non è probante — solo 2 mazzi con ≥16 giornate,
  pablo0078 pesa il 33% delle arene da solo. L'utente non accetta di
  relegare il DEF sulla base di 2 mazzi: serve allargare il campione
  profondo prima di rifare il backtest. Non blocca nulla, GW storiche non
  scadono. Dettaglio: `docs/handoff/HANDOFF_FAVORITO_ODDS_2026-08-06.txt`.
- **21 script in `analisi_manager/` con path Windows hardcoded**
  (`r'C:\Users\Andrea\...'`): girano solo sulla macchina dell'utente, non nel
  sandbox orchestratore/esecutori. Da sostituire con path relativo al file,
  meccanico, non urgente.
- **Buco tabella premi**: (Uncapped, rank 1) e (Uncapped, rank 3) senza
  premio noto — 30 casi su 497 trattati come 0 nel premio-vero, quindi il
  netto misurato è un limite inferiore. Servono più arene Uncapped rank1/3.
- **Consolidamento handoff (questo file, 08/08)**: fatto — questo documento
  ora contiene lo stato vivo di G, dell'infrastruttura grade e delle soglie
  arena senza dover leggere i 30+ file sorgente in `docs/handoff/`, che
  restano solo come archivio/dettaglio.

## 9. Modifiche di produzione — cronologia compressa

**09/08/2026 — SOGLIE ARENA APPLICATE + tipo Beginner** (commit
`f9902af972`). `PAREGGIO_ARENA`: cap260 259,5→**264,5**, cap220
244,1→**247,1**, Uncapped 288,3→**279,6**, Beginner **256,5** (nuovo),
Elite invariata 342,7, arene di lega singola invariate 262,9.
`GUADAGNO_PER_PUNTO`: cap260 7,9→**6,96**, cap220 6,3→**5,11**, Uncapped
8,0→**5,88**, Beginner **2,46** (nuovo), Elite invariata 9,1, arene di
lega singola 8,8→**6,96** (allineate a cap260: stesse regole, stessi
premi; il pareggio invece resta 262,9 perché è misurato sul loro campo,
più debole). `COSTO_INGRESSO` Beginner **100**. Effetto misurato: +1 arena
giocata su 16. Dettaglio in `HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` §13.

**08/08/2026 — nessuna modifica.** Aggiunti due interruttori **spenti di
default**: `GRADE_SCALE` (default `'gruppo'`) e `ARENA_CRITERIO` (default
`'assoluto'`), più `DUMP_JSON_CANDIDATI`. Entrambe le cure che
implementavano sono state misurate e **scartate**: non riproporle.

**07/08/2026 — Grade G in produzione** (`GRADE_ENABLED` default `'1'`),
con fetch automatica in `discovery_fixture.py`. Insieme: fix sessione
anonima/CSRF, ottimizzazione 429, `ESCLUDI_LOCKATE` (§8quater).

**05/08/2026** — 16 commit (`e2fe378376`): rimosso
`fattore_forza_avversario` (era morto), scouting su scala calibrata, fix
L10 nel knapsack, tie-break odds, gradino `-3:0` in `LEVEL_TABLE`, blend
GK `GK_TEAM_CS_WEIGHT` 0,5→0,63 propagato a tutte le leghe.

**04/08/2026** — arene dedicate per lega disattivate di default
(`ARENA_LEAGUES` vuota, riattivabile con `ARENA_LEAGUES_ENABLED`), commit
`ee4c2deec2`.

**DIFETTO APERTO, scoperto il 09/08 e NON introdotto da noi**: il
generatore è **non deterministico** run-to-run. Due esecuzioni identiche,
a codice invariato, allocano diversamente le formazioni opzionali (pool
residuo) perché Python randomizza l'ordine di set/dict a ogni processo.
Con `PYTHONHASHSEED=0` le run tornano identiche. Due implicazioni
separate: (a) fissarlo nell'ambiente di lancio costa nulla e rende i
risultati riproducibili; (b) il fatto che l'ordine cambi il risultato
dice che **lì il generatore non ha un criterio** e sceglie fra opzioni
che considera equivalenti — capire perché è un filone a sé, e potrebbe
valere essenze.

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

## 10bis. COSE DA FARE — riscritto il 09/08 notte

**Tutto quello che era in cima a questa lista il 09/08 mattina è FATTO**:
premi scaricati, soglie applicate, G validato sulle arene, filone odds
chiuso. **Aggiunto 09/08 sera**: filone "tabella fissa per lettera" testato
pulito e CHIUSO (non batte lo z-score, §8bis); resta produzione lo z-score.
Quello che segue è quello che resta, in ordine di interesse.

**PRIORITARIO — CAPITANO SCELTO COL GRADE** (idea dell'utente 09/08,
messa in cima su sua richiesta). Il capitano MOLTIPLICA il punteggio: +20%
in arena, +50% fuori. Su una carta da 80 punti sono 16 o 40 punti su una
decisione sola — nessun altro parametro del modello sposta tanto con una
scelta singola.
Oggi `pick_captain()` sceglie sull'atteso e **ignora completamente il
grade**: nel backtest del §9 la fascia era assegnata col criterio del
baseline in TUTTI i rami, quindi G non l'ha mai usata — è uno dei tre
limiti che comprimevano il suo vantaggio misurato.
Gerarchia proposta dall'utente: **fascia al grade più alto; a parità di
grade, all'atteso più alto; se anche gli attesi sono vicini o uguali, si
sceglie per ruolo.**
Due effetti da misurare SEPARATAMENTE, perché sono meccanismi diversi:
  - **protezione**: un capitano che non gioca non costa solo i suoi punti,
    azzera il moltiplicatore. Il grade è bravissimo proprio a dire chi non
    gioca (una F non gioca nel 61,5% dei casi, e il suo residuo è −31);
  - **spinta**: a parità di titolarità, il grade ordina ancora (residui da
    +1,4 di D a +3,9 di A) — ma qui i margini sono piccoli.
Da sapere: sul capitano sono già state chiuse otto ipotesi (§5.3), ma
**nessuna con il grade**, che è arrivato dopo. Non è una voce bruciata.
Si misura sul backtest arene già rodato, come ramo a sé.

**COME E SU QUALE ARCHIVIO — impostazione (orchestratore 09/08 sera; l'utente
la conferma/rifinisce a inizio sessione PRIMA che si scriva il brief a Sonnet,
perché voleva illustrarla lui).**
- Archivio PULITO: lo stesso delle arene (`p20_g_odds_arene_backtest.costruisci_
  unita` / `p20_gfisso_v2_backtest.py`, 90 unità manager×GW, 6 GW), popolazione
  **P_noF** = pool senza carte F (= proxy titolarità ≥0,80, la sola che l'utente
  schiera; sopra 0,80 il grade al lock = grade final, verificato live §8bis, quindi
  archivio pulito senza leakage). Realizzato dalla cache game-log condivisa.
- Regime: **allocazione** (pool>slot), perché lì c'è una scelta VERA di capitano fra
  più candidati; in astensione la formazione è fissa e la fascia non si sceglie.
- Confronto a parità di formazione e di arene: ramo BASELINE (`pick_captain()`
  attuale, fascia sull'atteso) contro ramo GRADE (gerarchia dell'utente qui sopra:
  grade più alto → a parità atteso più alto → a parità ruolo). Cambia SOLO chi porta
  la fascia; tutto il resto identico. Metrica: essenze REALIZZATE, delta = grade −
  baseline, bootstrap per manager IC95, ENTRAMBE le soglie, segno stabile per decidere.
- Misurare SEPARATE **protezione** e **spinta** (già spiegate sopra). Attenzione al
  leakage §18/S2: la protezione usa "chi non gioca", che nel grade FINAL è
  informazione post-partita — misurabile pulita SOLO sulla popolazione ≥0,80 (dove
  lock=final, §8bis); fuori di lì è un limite superiore, dirlo.
- Vincoli di metodo (dal filone tabella, §21.7/§26): i due rami devono giocare lo
  STESSO numero di arene (o confronto per-arena con n dichiarata); **stratificare per
  tipo di arena** (cap220/cap260/uncapped/beginner/arene-paese) e NON dare un
  verdetto che pesa insieme tipi diversi; separare pool=slot e pool>slot e riportare
  anche la vista insieme; ogni n dichiarata riga per riga. Ispezionare i grezzi (non
  il riassunto dell'esecutore) prima di chiudere.

**1. Quanto vale G sopra il filtro starting odds?** È la riserva più
importante ed è aperta. Il grade è in larga parte un indicatore di
titolarità (§8bis); il bot in produzione filtra già a 0,80 di starting
odds, che misura la stessa cosa. Nel backtest il ramo A è invece
completamente cieco su chi gioca, quindi una fetta del +29.050 potrebbe
essere un vantaggio che in produzione è già stato incassato dal filtro.
Da misurare rifacendo il confronto **dopo** aver applicato il filtro a
entrambi i rami. Nessuna query, dati già in repo.

**2. Segregare il rischio DNP** (idea dell'utente, 09/08). Oggi lui non
schiera sotto l'80% di starting odds e si mangia tutta la fascia 60-80%.
Alternativa: il bot continua a giocare 80+ nelle arene che contano, e le
carte 70+ ad alto potenziale finiscono **tutte insieme in una sola
Beginner** (100 essenze): un DNP rovina una formazione già dichiarata
precaria invece di una buona. Non riduce i DNP, cambia dove cadono.
Misurabile senza query: le starting odds sono salvate accanto al grade
(`starter_odds_bp` in `analisi_manager/dati/storico_grade_*`); si innesta
su `p20_g_odds_arene_backtest.py`, che già fa il regime allocazione.

**3. Perché il generatore non ha un criterio nella fase opzionale.**
Il non-determinismo `PYTHONHASHSEED` (§9) non è solo un fastidio di
riproducibilità: dice che lì il modello sceglie fra opzioni che considera
equivalenti. Fissare il seed costa nulla e va fatto comunque; capire cosa
distingua quelle opzioni è il filone vero.

**4. Bonus 4% (cap L10) e 2% (anti-stack) fuori dall'arena, RIFATTI CON G.**
Il generatore li tratta come informativi e non li insegue; test passati
dicevano che inseguirli peggiorava il totale, ma erano **senza G**. Serve
anche sistemare il realizzato dei backtest non-arena, che oggi non li
calcola affatto (p16/p17 righe 61-65).

**5. Normalizzazione del grade** (§8bis): il grade è ignorato sul 23%
delle carte perché i gruppi (lega, ruolo) sono troppo piccoli. La prima
cura (scala storica) è stata misurata e scartata: serve un'idea NUOVA. Non
urgente, G funziona così com'è.

**6. Due verifiche economiche su G**: (a) dove il gruppo ha esattamente 2
carte col grade lo spostamento è meccanico ±1 sd, mai misurato se lì G
peggiori; (b) placebo permutando i grade **fra giornate dello stesso
giocatore** invece che fra giocatori — risponde se il segnale sia "questo
giocatore è forte" o "questa partita andrà bene".

**7. Correlazione grade ↔ punteggio realizzato della stessa partita**: mai
misurata, zero query. Limite superiore alla contaminazione possibile.

**8. Decisione grade nello scouting** (§8ter): usare il grade storico
anche per candidati non posseduti, o lasciare lo scouting senza grade?

**9. Odds+4ruoli, campione profondo**: solo 2 mazzi con ≥16 giornate,
pablo0078 pesa il 33% — il DEF non si può relegare allo scouting su questa
base (§8quinquies).

**10. Buco tabella premi Uncapped rank 1/3**: un'osservazione sola
ciascuno nell'archivio vecchio. Con i premi veri (§4.0) probabilmente è
già risolto: **da riverificare su v3 prima di rimetterci mano.**

**11. 21 script con path Windows hardcoded** in `analisi_manager/`:
girano solo sulla macchina dell'utente. Meccanico.

**12. SONDA 09/08 — il grade di una partita GIA' GIOCATA e' recuperabile
dall'API anche a posteriori**: risposta SI', su 5 righe verificate.
Metodo: `anyPlayer(slug).playerGameScores(last:40)` (stessa rotta di
`raccolta_grade_storico.py`, non l'`anyGame` usato per le partite future),
5 giocatori/partite scelti dagli snapshot storici
(`analisi_manager/dati/storico_grade_*.json`) con grade non nullo e
scoreStatus FINAL, ripetuti il 09/08 con
`analisi_manager/sonda_grade_passato_recupero.py`. Risultato: 5/5 righe
rispondono, 5/5 con grade presente oggi, 5/5 identico allo storico
(incluso un caso a 5 mesi di distanza, 09/03 -> 09/08). Nessun caso NULLO
o diverso. Dettaglio in
`analisi_manager/dati/sonda_grade_passato_recupero_20260809.json`.
Campione piccolo (5 righe, un solo giorno): non dimostra che valga SEMPRE
(vedi caso `andrew-vincent-rick` sotto, 1/729 grade cambiato), ma la
domanda "sparisce dopo la partita?" ha risposta NO su questo campione.
Costo di un'estrazione vera per riempire lo storico: 1 query per
giocatore (stessa rotta), decide l'utente se/quando farla — NON avviata.

**13. DIAGNOSI 09/08 — perche' il 66% delle carte non ha il grade**
(BRIEF_SONNET_PERCHE_MANCA_LETTERA, primo passo a rete spenta, zero
query). Riscontrati al centesimo i numeri dell'orchestratore: 41 gruppi
(lega,ruolo) con >=2 carte, 243 carte, 82 con grade (33,7%), 20 gruppi
inerti (grade<2 -> z=0 fallback), 104 carte in quei gruppi. Su TUTTI i 55
gruppi (anche quelli con 1 sola carta, dove il grade non serve comunque
allo z-score): 257 carte, 86 con grade (33,5%), 171 senza.
Incrocio col `consiglio_*.txt` piu' recente di ciascuna lega/ruolo: 163
carte su 171 senza grade (95%) COMPAIONO nel consiglio, cioe' hanno una
partita nella finestra della giornata. **Ipotesi (b) "niente partita"
ESCLUSA per la stragrande maggioranza**: non e' un problema di finestra
temporale.
Dal codice (`discovery_fixture.py:298-345,443-479`, letto riga per riga,
nessuna query): il grade arriva SOLO se una carta e' (i) nel bench di una
delle tre leaderboard (All Star arena limited, All Star limited, Korea
in-season limited pvp) **E** (ii) ha `eligiblePlayerGameScores` NON VUOTO
per QUELLA leaderboard specifica (riga 461: il loop su
`eligiblePlayerGameScores` semplicemente non produce nulla se e' vuoto,
in silenzio, anche se la carta e' contata nel totale nodi bench). Sono
due condizioni distinte: **IPOTESI PRINCIPALE CONFERMATA COME PLAUSIBILE
DAL CODICE** (non da una query: nessun log/dump locale mostra i nodi
bench veri), con una seconda faglia possibile scoperta leggendo il
codice, non ipotizzata a priori.
**CAUSA VERA, TROVATA SUBITO DOPO — NON E' UN BUCO, E' IL MOMENTO DELLA
MISURA** (orchestratore 09/08, dopo che l'utente ha detto che al momento
della discovery le sue carte K League e MLS **avevano gia' giocato**).
Incrociando il grade con la data di kickoff della PROSSIMA partita di
ogni carta (`analisi_manager/p21_grade_vs_kickoff.py`, zero query, dati
gia' su disco), il taglio e' netto e senza eccezioni:
    kickoff 09/08 ...... 71 carte, 71 col voto (100%)
    kickoff 10/08 ...... 13 carte, 13 col voto (100%)
    kickoff 11/08 ...... 22 carte,  0 col voto (0%)
    kickoff 12-16/08 ... 138 carte, 0 col voto (0%)
    senza kickoff ...... 10 carte,  2 col voto
**84 su 84** le carte che giocavano nella giornata gia' aperta hanno il
voto; **0 su 163** quelle la cui prossima partita cade nella giornata
SUCCESSIVA. Il voto e' una proiezione pre-partita servita dalle
leaderboard della giornata APERTA: se la giornata dopo non e' ancora
aperta, il voto non esiste per nessuno — non e' un difetto del nostro
canale.
Cade quindi l'ipotesi dello slug Korea sbagliato: **kleague 0/38 si
spiega interamente col fatto che tutte le carte K League hanno la
prossima partita il 15-16/08**, cioe' nella giornata non ancora aperta.
Nessun bug di costruzione slug dimostrato: NON aprire quel filone.
Cadono anche le due cifre di copertura citate sopra come se fossero un
problema (33,7% delle carte col voto, 20 gruppi inerti su 41): sono
l'artefatto di una discovery girata il 09/08 alle 14:00, a giornata quasi
finita. **La copertura vera si misura su una discovery lanciata a
giornata aperta e prima dei kickoff**, che e' il momento in cui il bot
compone davvero le formazioni.
DOMANDA APERTA, questa si' operativa: se il generatore gira per una
giornata non ancora aperta, G e' inerte per costruzione (z=0 su tutti).
Da capire quando gira davvero il bot rispetto all'apertura della GW.
File: `analisi_manager/p21_grade_vs_kickoff.py` +
`analisi_manager/dati/grade_vs_kickoff_20260809.json` (verifica nuova);
`analisi_manager/diagnosi_buco_grade.py` +
`analisi_manager/dati/diagnosi_buco_grade_20260809.json` (diagnosi
precedente: i conteggi restano validi, la loro INTERPRETAZIONE no).
NOTA su un numero della prima stesura: diceva "Mls 19/45 con grade", ma
19 e' il numero di CARTE mls_def. Il dato vero e' **11/45** (def 8/19,
fwd 1/10, gk 0/6, mid 2/10).
AGGIORNAMENTO 09/08 sera, misura sulla produzione vera (le sole carte con
odds VERE, cioe' quelle della giornata aperta: 86): tutte e 86 hanno la
lettera, ma la lettera **entra nel calcolo solo per 63** (16 gruppi su
32). Le altre 23 sono lettere inerti: 11 gruppi hanno UNA SOLA carta con
lettera (niente con cui confrontarla) e 5 gruppi hanno tutte le lettere
UGUALI (mls_mid due D, belgio_def tre D, messico_mid tre C) -> sd=0 ->
z=0. Non e' un buco di dati: e' la formula. Vedi §14.

**14. IL MERITO DEL BACKTEST CHE HA SCELTO LA FORMULA — riesame
dell'orchestratore, 09/08 sera** (richiesto dall'utente: "e' la
combinazione migliore? non se ne puo' trovare una che non escluda
carte?").
COME E' STATA SCELTA LA FORMULA: non da un confronto fra alternative. E'
un principio di disegno (`z(atteso) + z(grade)`, riportato in punti
moltiplicando per la sd del gruppo, docstring di
`p12_backtest_formazione_grade.py:14-20`), validato poi solo come
BLOCCO (G acceso vs G spento), mai contro una formula rivale prima di
essere messa in produzione il 07/08.
L'UNICA RIVALE MAI TESTATA e' la tabella fissa lettera->punti ("G
fisso", `p20_gfisso_v2_backtest.py`, 09/08) -- che e' proprio la forma
che NON esclude nessuno, perche' non ha bisogno di un gruppo. Verdetto
scritto: "GF NON VINCE". Riesaminando il grezzo
(`p20_gfisso_v2_backtest_out.json`) quel verdetto e' vero SOLO nel
riquadro in cui e' stato deciso, ed e' un riquadro stretto:
  - criterio applicato: **solo P_noF, solo il ramo astensione**, su
    entrambi i set soglie, e vincente sia raw sia centrata. In quel
    riquadro n=111 righe e i delta (+-1.000/2.000 essenze) sono piu'
    piccoli dell'incertezza (IC95 larghi +-2.000/6.000): non poteva
    passare nessuno, nemmeno una formula buona.
  - Nel resto della tabella la tabella fissa NON perde, vince:
    su **P_ALL** (pool completo, F comprese) empirica fa AST +8.000
    IC95[+1.700;+16.000] (soglie vecchie) e +4.700 [+500;+10.000]
    (nuove); in ALLOCAZIONE +21.450 [+4.200;+39.800] e +17.200
    [+4.850;+30.750]. Anche scala_k1 e k2 stanno sopra zero in
    allocazione su entrambi i set.
  - Il controllo che rende il dato credibile: il **placebo** (tabella di
    zeri = nessun grade) va NEGATIVO e fuori da zero (-29.050
    [-48.700;-13.300] in allocazione su P_ALL). Quindi in quel campione
    il grade vale, e non e' un artefatto della meccanica.
  - CAUTELA da non dimenticare: P_ALL contiene le carte F, e sulle F il
    grade FINAL porta informazione post-partita (leakage §18/S2). Parte
    del vantaggio su P_ALL puo' essere leakage. E' esattamente il motivo
    per cui P_noF era stato scelto come primario. Quindi: **la tabella
    fissa non e' dimostrata migliore, ma non e' affatto dimostrata
    peggiore** -- e' stata archiviata da un gate troppo stretto.
QUELLO CHE NESSUNO HA MAI TESTATO, ed e' la domanda dell'utente:
una formula che **conservi lo z-score dove il gruppo regge e non escluda
nessuno dove non regge**. Tre candidate, nessuna misurata:
  (a) tabella fissa pura (copertura 100%, gia' implementata come GF);
  (b) ibrida: z-score se il gruppo ha >=N lettere e sd>0, tabella fissa
      altrimenti (oggi il fallback e' z=0, cioe' "il voto non esiste");
  (c) gruppo piu' largo: z-score per RUOLO su tutte le leghe insieme
      invece che per (lega, ruolo) -- non tocca la formula, toglie solo
      la fame di numerosita'. Diversa dalla "scala storica" gia'
      bocciata (§8bis), che sostituiva media/sd con quelle storiche
      dello stesso gruppo piccolo.
Sulla produzione di oggi le tre varianti porterebbero le carte col voto
attivo da **63 su 86** a **86 su 86**.

**In attesa, non indagare**: L10 incoerente lato Sorare (caso Jeppe
Erenbjerg, run146): il bot legge `lastTenPlayedAvgScore` e copia
fedelmente l'API, non è un bug nostro. Se ricapita, attenzione: se l'arena
di Sorare conta 66 dove noi contiamo 62, il cap L10 può sforare davvero.
E il caso `andrew-vincent-rick` 13/05 (grade cambiato fra due letture con
scoreStatus FINAL, 1 su 729, senza causa nota).

**REGOLE DI GIOCO raccolte il 09/08** (dichiarate dall'utente, non
dedotte — servono a chi progetta i prossimi test):
- **Level score**: chi entra anche un solo minuto prende ~35 punti. Il
  salto vero è fra "non gioca" e "gioca", non fra giocare bene o male.
- **Doppia partita nella stessa fixture**: la carta si schiera una volta
  sola e prende il punteggio **più alto** dei due. Rarissimo (18 giocatori
  in dodici mesi, K-League): errore accettato dall'utente, non correggere.
- **Le starting odds non sono di Sorare**: vengono da un fornitore esterno
  (Sorare non ha interesse a farti vincere). Anche loro sbagliano: una
  quota di DNP è un danno strutturale, non un difetto del nostro modello.
- **Formazioni ufficiali / full stack**: per alcune competizioni si può
  schierare a formazioni già annunciate, rischio DNP zero, ma si è
  vincolati a pescare dentro un solo undici. Mai valutato se convenga.
- **Carte rare in competizioni limited**: si comportano esattamente come
  le limited, si contano come limited. Si escludono le *competizioni*
  rare, non le carte.

**Voci chiuse, non riaprire**: filone favorito-odds (§8nonies, chiuso su
tutti i fronti); scala storica del grade; soglie cap 220 come difetto di
taratura; buco dati `arene_storico.json`; 3 anomalie non-arena; fix HTML
copia/incolla e tasto "fatta" (commit `b1cbf53db6`, verificato in
produzione dall'utente l'08/08); criterio arene a rendimento sul capitale
(§8septies, misurato e scartato).

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
