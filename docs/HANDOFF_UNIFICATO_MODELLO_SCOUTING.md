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

Ultimo aggiornamento: **sessione 12/08/2026 sera (Roma, CEST)** — giornata
di test end-to-end su GitHub Actions (GW4/GW5) che ha fatto emergere e
chiuso 4 bug reali di produzione + aggiunto una feature nuova + un tipo
formazione nuovo. Dettaglio completo: §8duodecies. **429 GW5 CHIUSO**
(fix P5+P6 verificato su run vera). **APERTI 3 problemi nuovi emersi subito
dopo — §8duodecies-bis: crash `_budget_essenze` (blocca ogni run senza
arene), notifica Telegram bugiarda su run fallita, 92% del predict sprecato
quando si chiede solo Champions.**

Sessione 11/08/2026: filone PORTIERE, GK_ATT_AVV **ACCESO IN PRODUZIONE**
(formula "secca", media storica tutta la carriera, refresh automatico ad
ogni run) dopo verdetto Opus su Binario 1+2 sull'archivio completo (2975
formazioni/360 GW-manager). `GK_ATT_AVV_ENABLED` default **'1'** in
generatore e scouting. **Ri-misura pre-registrata dopo 3 fixture giocate
col flag acceso — data/condizione in §5.6.**

## REGOLA NUOVA — I BACKTEST SONO IL MODELLO CONTRO SE STESSO (09/08/2026, decisa dall'utente)

**Sovrascrive il modo in cui sono stati fatti TUTTI i backtest fino a
oggi. Vale da adesso in avanti, senza eccezioni.**

Fino al 09/08 i backtest confrontavano il nostro modello con le scelte di
altri manager Sorare (24 manager, 6 GW, file `dati_globali/manager_*.json`).
Quella strada ha prodotto confusione strutturale: archivi misti, campioni
di provenienza diversa, competizioni mescolate, criteri di schieramento
ignoti (di 23 manager su 24 non sappiamo con che regola scegliessero), e
verdetti che l'utente non ha mai potuto controllare fino in fondo. Da qui
la sua sfiducia dichiarata verso i backtest — motivata, non un capriccio.

**Da adesso:**

1. **Il modello si misura contro SE STESSO**, non contro altri manager.
   La domanda di ogni backtest diventa "questa variante batte la versione
   che gira oggi in produzione, sulle stesse giornate?", non "battiamo i
   manager?".
2. **L'unico archivio di riferimento sono le giornate dell'UTENTE**
   (manager `crowss`). Sono le sole su cui ha controllo totale: conosce le
   dinamiche, i voti, le formazioni, il perché di ogni scelta.
3. **Punto di partenza: la fixture 7-11 agosto 2026.** Da quella giornata
   in poi le formazioni sono schierate col modello **G**. È la prima
   finestra in cui ciò che è in campo coincide con ciò che si vuole
   misurare.
4. **Gli archivi multi-manager restano come storia, non come base di
   misura.** Non si aprono nuovi filoni su quel materiale, e i verdetti
   già presi lì non si estendono a nuove decisioni. Se una misura passata
   serve, si cita dicendo che veniva da lì.
5. **Dove sta l'archivio: `archivio_crowss/`** (creato il 09/08, per ora
   **vuoto di proposito** — è un contenitore pronto, non c'è nessuna
   estrazione né backtest in attesa). Due partizioni, taglio netto alla
   fixture 7-11 agosto 2026:
   - `pre_2026-08-07/` = **crowss manager reale**. Le formazioni le
     costruiva il bot ma l'utente le correggeva SEMPRE a mano, e il
     modello era ancora primordiale: è il benchmark **umano**, non una
     versione del modello.
   - `dal_2026-08-07/` = **modello G** schierato integralmente, senza
     correzioni a mano.
   Ci vanno tutte le competizioni che l'utente gioca davvero (arene, In
   Season, All Star, U23), un file per fixture e competizione, mai
   mescolate. I dati degli altri manager NON entrano qui. Convenzione
   completa in `archivio_crowss/README.md`.
6. Conseguenza pratica sulla potenza statistica: le giornate dell'utente
   crescono di una alla volta. Un test che ha bisogno di centinaia di
   osservazioni per decidere **non si può fare adesso** — e va detto
   subito invece di girarlo su un campione sbagliato. Meglio aspettare
   giornate vere che decidere su dati che non ci appartengono.

---

**COME SI RIPARTE** (aggiornato 09/08 notte): NON da un passaggio di
consegne. Come dice CLAUDE.md: `git pull`, `git log`, poi il CODICE in
produzione sul tema. Questo file serve a cercare un dettaglio o a sapere
cosa è già chiuso — come indizio da verificare, mai come prova.
`docs/handoff/PASSAGGIO_CONSEGNE_ORCHESTRATORE_2026-08-09_MATTINA.txt` è
superato dai lavori del 09/08 sera-notte: non usarlo.

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
   chi entra un minuto prende ~35 punti di level score. La riserva che ne
   discendeva ("quanto vale G sopra il filtro 0,80") è stata
   **ridimensionata il 09/08 notte**: poggiava su una premessa falsa sul
   pool del backtest — §10bis voce 1.

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

### 2.2 Scouting acquisti (`scouting_gw.py`) — RISCRITTA IN MODALITA' MINIMALE (09-10/08/2026)

Risolve il problema opposto al generatore: il generatore parte dalle carte
POSSEDUTE, per COMPRARE serve sapere con giorni di anticipo chi scenderà in
campo, comprese carte non possedute — prima che Sorare pubblichi le starter
odds (24-48h dal kickoff).

Trovato che la query giusta è `searchPlayers` (la stessa della pagina
"Scouting" di Sorare): una query paginata, ~12-34 chiamate a seconda del
filtro, porta già L5/L10/L40, presenze, infortuni, proiezione Sorare, carte
possedute, prezzo minimo (`lowestPriceAnyCard`, MAI cachato: costa zero
query in più, un prezzo vecchio su una decisione d'acquisto sarebbe un
rischio inutile) e **grade** (`nextClassicFixtureProjectedGrade`, §8ter) —
sostituisce 75 query di roster + migliaia di scrematura.

**Modalità di default ora è `--minimal`** (checkbox `minimal` nel workflow,
richiesta esplicita dell'utente 09/08 sera: "voglio semplificarlo"). NIENTE
arene, niente essenze/GW, niente "si ripaga in". Una lista sola:
Giocatore/Ruolo/Club/Odds/Prezzo/Grade/Atteso/**A+G**, dove A+G =
`atteso + sd_gruppo × z_grade` (STESSA formula del generatore,
`_apply_grade_group`, gruppo = lega+ruolo primario fra chi ha un atteso —
non reinventata). Ordinata per A+G decrescente, colonne cliccabili per
riordinare. Tre bottoni:
- **Mostra solo** (Tutti/GK/DEF/MID/FWD): filtro esclusivo, nasconde tutto
  il resto (non solo evidenzia).
- **Best Five**: i 5 candidati con rapporto prezzo/A+G più basso (prezzo/
  Atteso se manca il grade), esclusivo (mostra SOLO quei 5).
- **Best per ruolo**: il migliore per ciascun ruolo con lo stesso rapporto,
  un colore diverso a ruolo, esclusivo (mostra SOLO quei 4).
Tutto calcolato lato client su attributi `data-*` nelle righe (prezzo/
atteso/A+G/ruoli), mai testo riparsato — robusto a formattazione/valuta.
Log di copertura ad ogni run (pool/odds/grade/atteso/prezzo, n e %) e
avviso (badge ⚠️ in tabella + riga in log) per candidati con "fixture
ambigua" (§9, voce fix Freese).

Output: `generatore_formazioni/output/scouting_ultimo.html` (committato,
notificato su Telegram). Workflow `scouting_gw.yml`, input `gameweek`/
`odds_min`/`predict`/`screma`/`riusa_predizioni`/`minimal`.

**Riuso predizioni SPENTO di default** (`SCOUTING_RIUSA_PREDIZIONI=0`,
checkbox `riusa_predizioni` default `false` — richiesta esplicita
dell'utente finché G non è "innestato con sicurezza": ogni candidato viene
ripredetto da zero ad ogni run, mai una previsione vecchia riusata in
silenzio). NON tocca `best_five.RIUSA_PREDIZIONI` (resta acceso per il
generatore): `bf` in scouting è un'istanza fresca (`_import`), spegnerlo lì
non spegne nient'altro. Log sempre presente: quante previsioni sarebbero
state riusabili e vengono rifatte per questo motivo.

Cache generatore (`<lega>_<ruolo>_all`) riusata per L5/L10 storico come
sempre; NESSUNA cache prezzi nella pipeline scouting (verificato sul
codice: quella di `best_five.py`, TTL 5gg, la usa solo `esegui_consiglio`,
mai chiamata da qui né dal job "Consigli" del workflow, che lancia gli
script leggeri `build_consiglio_*.py`, solo lettura locale).

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

### 5.3 Capitano — CHIUSO per la seconda volta, ora con un motivo dimostrato (12/08/2026)
Le "otto ipotesi chiuse" originarie giravano su `dati_globali/manager_*.json`
(bug D6, §5.8): riaperto il 12/08 sull'archivio pulito (`archivio_ufficiale/`,
1.145 arene con capitano). Ri-testate grade e favorita/sfavorita: entrambe
NEGATIVE anche sui dati veri (grade peggiora, t=-1,93; favorito interno
nessun effetto, t=-0,62 su confronto equo; favorito da quote copertura
insufficiente per essere testabile). **`pick_captain()` non si tocca.**

Motivo per cui non si tocca, dimostrato non solo misurato: il modello
oggi cattura +0,69 punti/arena di bonus captain sul caso (15% del massimo
possibile +4,59). Simulando un criterio con correlazione r nota col
punteggio vero, il guadagno che +0,69 rappresenta corrisponde esattamente
a r≈0,156 — la stessa correlazione media che il modello ha davvero sui
ruoli di movimento (DEF/MID/FWD). **Il capitano prende già tutto quello
che la vista del modello permette**: non è un problema di regola di
scelta, è un tetto di previsione. Non riaprire con altre idee di
selezione — dettaglio completo in
`docs/handoff/HANDOFF_ORCHESTRATORE_NUOVO_2026-08-12.txt` §2quater.

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

### 5.6 Portiere — ACCESO IN PRODUZIONE l'11/08/2026 (GK_ATT_AVV, formula secca)
Tutto quello sotto (§5.6 storico) resta valido come tetto sui segnali GIA'
TESTATI PRIMA dell'11/08: nessuno batteva la produzione (L10, casa/
trasferta, quote di vittoria, difesa propria — morta su ogni test). Il
segnale che ha rotto il tetto: **quanto segna di solito la squadra
AVVERSARIA** (gol veri, homeGoals/awayGoals, dati pubblici Sorare via
`nodes(ids)`, mai usati prima). Confermato su blocco temporale indipendente
(stagione 2024/25, n=1.896, IC esclude lo zero) e nel backtest vero.

**DECISIONE (11/08/2026, utente + verdetto Opus):** formula "secca" (media
storica di tutta la carriera disponibile, tabella dinamica che si
riaggiorna da sola). `GK_ATT_AVV_ENABLED` default ora **'1' ACCESO** sia in
`build_formazione_globale.py` sia nell'input del workflow
`formazione_giornata.yml`. Motivo: su tutto l'archivio ufficiale (2975
formazioni/360 GW-manager, non solo la fixture nuova 7-11 agosto) —
  - **Binario 2** (pool libero): G migliora SE STESSO (non A: A e' solo il
    braccio di confronto) di **+5.556 essenze**, IC95% [+649;+10.638],
    **98,7% positivo** — combacia quasi esatto con la misura storica sui
    337→360 GW, replicata due volte da sessioni indipendenti (orchestratore
    e Opus).
  - **Binario 1** (formazione fissa): primo test mai fatto su questo
    correttivo. Punto stimato -1.500 (IC [-5.650;+2.550], include lo zero)
    ma **sotto-potenza**, non contro-prova: con solo 36 decisioni
    discordanti su 1091 la soglia minima rilevabile e' ~4.190 essenze,
    contro un effetto atteso di poche centinaia — il -1.500 dista 0,7
    deviazioni standard dallo zero, dentro il rumore.
  - A_on-A_off = +6.794 (IC [+1.360;+12.320], 99,2% positivo): il
    correttivo migliora anche il braccio SENZA grade — due regole di
    scelta diverse, stesso verso, argomento a favore.
  - Look-ahead della tabella (costruita su tutta la storia, senza taglio
    per data) misurato e scartato: ricalcolo walk-forward su 25 fixture,
    differenza 0,096 punti contro sd 1,727 del correttivo (5,6%,
    irrilevante).

Allineato anche `scouting_gw.py` (`_atteso_dai_consigli`): prima non
applicava affatto il correttivo, un portiere avrebbe avuto un atteso
diverso fra generatore e scouting (fino a ~6-7 punti). Stesso flag/formula,
stessa funzione `gk_att_avv_aggiustamento` del modulo generatore.

**RI-MISURA PRE-REGISTRATA — DATA FISSA, NON UN PROMEMORIA A VOCE**
(l'utente lavora su 3 account diversi, un reminder per-account non basta:
va letto qui). Motivo: la formula "secca" e' stata scelta fra 5 candidate
sugli stessi dati, quindi le conferme viste finora sono campioni annidati
(337→360 GW = +6% di dati nuovi), non repliche indipendenti.

Fixture tracciate (verificate l'11/08/2026 via query pubblica Sorare
`so5Fixtures`, non stimate — GW4 `football-11-14-aug-2026` era gia'
'started' quando si e' acceso il flag, quindi la PRIMA giornata realmente
giocabile col correttivo e' la GW5):
  1. GW5 `football-14-18-aug-2026` (chiude 2026-08-18)
  2. GW6 `football-18-21-aug-2026` (chiude 2026-08-21)
  3. GW7 `football-21-25-aug-2026` (chiude 2026-08-25)

**Quando GW7 e' chiusa (dal 25/08/2026 in poi):** riestrarre queste 3
fixture in `archivio_ufficiale/` per i manager disponibili, rilanciare
`analisi_manager/p24_binario2_ga.py` flag on/off e rifare il bootstrap
appaiato G_on-G_off **SOLO su queste 3 GW nuove** (mai mischiate con le
360 gia' usate per scegliere la formula — altrimenti si torna a
misurare lo stesso campione con cui si e' decisa la formula). Atteso
(Opus): ~+15 essenze/GW-manager. **Se il segno esce negativo su queste 3
GW, si rispegne `GK_ATT_AVV_ENABLED` di default** (spento in
`build_formazione_globale.py` e nell'input del workflow).

Dettaglio integrale: `docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt`
§9-14, `docs/handoff/BRIEF_OPUS_GK_SECCA_PRODUZIONE_2026-08-11.txt`. NON
toccare `CALIB_PER_RUOLO`/`GK_TEAM_CS_WEIGHT` per questo filone: il
correttivo si somma DOPO la calibrazione, non la sostituisce.

Vecchio tetto (chiuso il 12-13/08, resta valido SOLO per i segnali gia'
provati allora — L10, casa/trasferta, quote di vittoria: nessuno batteva la
produzione, Spearman atteso/reale ≈0). Script:
`analisi_manager/p32_gk_segnali_alternativi.py`.

### 5.6 (storico) Portiere — CHIUSO il 12/08/2026, il modello è già al meglio misurabile
Riaperto il 12/08 da una scomposizione della formula grezza (mai fatta
prima su questo ruolo): il modello NON prevede il portiere (corr
atteso/reale ≈0, dedup per slug+fixture, IC a grappolo per giocatore
[-0,036,+0,096]). Diagnosi: il pezzo storico personale (parate/gol
subiti via Poisson) è ridondante rispetto al blend "porta inviolata di
squadra" (`GK_TEAM_CS_WEIGHT`, già in produzione dal 03/08) ma innocuo,
non dannoso. Provate 4 varianti (togliere il blend, sostituire lo storico
con pcs a scale diverse, pesi diversi) FUORI CAMPIONE contro la
produzione vera coi tre criteri insieme (corr+MAE+lift): **nessuna
batte la produzione**. Tetto strutturale, non un bug: il 90% del
punteggio decisivo del GK è il clean sheet (evento di squadra), e la
squadra forte fa parare meno il proprio portiere (corr pcs/parate
-0,156) — un quarto del segnale si perde per come funziona il punteggio
Sorare, non per un errore del modello.
Nel cassetto, non implementata (guadagno solo su MAE/bias, non su
ordinamento): sostituire storico+blend con una sola stima pcs a scala
ristretta (37,7+13,5·pcs). `CALIB_PER_RUOLO['GK']`, `GK_TEAM_CS_WEIGHT`,
`GK_TEAM_CS_POINTS`, `GK_TEAM_CS_BASELINE`, `TREND_INTENSITY` (GK) — non
toccare, già al meglio misurato. Dettaglio completo in
`docs/handoff/HANDOFF_ORCHESTRATORE_NUOVO_2026-08-12.txt` §1sexies.
- **`level_score` binario** (nota storica, ancora valida): il valore vero
  è 35 senza clean sheet e 60 con, mai intermedio; il modello ne prevede
  uno continuo — è compressione monotona (non sposta l'ordinamento),
  sparirebbe da sola con la variante "sola pcs" nel cassetto sopra.
- **Blend GK, `c` alzato da 17,5 a 22** (`GK_TEAM_CS_WEIGHT` 0,5→0,63,
  storico): confermato di nuovo il 12/08 su campione indipendente —
  spegnerlo costa -0,039 di correlazione (IC esclude lo zero).

### 5.7 Difetti nati qui e ancora aperti
- **`CALIB_PER_RUOLO` — TESTATO E CHIUSO (13/08/2026), non applicare.** La
  sottostima di ~2,4 punti/carta sui ruoli di movimento (misurata il 12/08,
  vedi sopra) è reale in media ma NON STABILE nel tempo: split cronologico
  train (apr-inizio giu) vs test (fine lug-ago), sia OLS pieno sia sola
  correzione d'intercetta PEGGIORANO il MAE fuori campione su DEF/MID/FWD
  (es. DEF bias -2,40 in train ma -1,79 in test — periodi diversi, bias
  diverso). Non si rifà. Script: `analisi_manager/p27_refit_calib_per_ruolo.py`.
  Costanti di produzione INVARIATE (`build_formazione_globale.py:403-407`:
  GK 35.78/0.264, DEF 7.28/0.831, MID 11.61/0.740, FWD 8.40/0.789).
- **Difensore, peso decisivo/granulare — TESTATO E CHIUSO (13/08/2026),
  w=1 resta ottimo.** Il margine misurato il 12/08 (w=0 batte w=1) veniva
  da una scomposizione SEMPLIFICATA (senza shrinkage/casa-trasferta/Stadio
  D). Rifatto sulla formula vera (`compute_score_atteso_def`, test A/A
  scarto 0,000000 contro produzione): su una griglia w=[0..2], w=1,0 è il
  MASSIMO di correlazione e il MINIMO di MAE sia in train che in test.
  Nessun cambio. Script: `analisi_manager/p28_def_peso_decisivo.py`.
- **`backtest_arene_previsioni.py:257-260`, default `GK_TEAM_CS_WEIGHT=0.5`
  — SCELTA VOLUTA dell'utente, non un difetto** (chiarito il 09/08). Resta
  qui come voce **informativa**: chi usa quel modulo senza esportare la
  variabile non sta usando il valore di produzione (22/35), e deve saperlo.
  Non "correggerlo" pensando di sistemare un bug.
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

### 5.9 QUOTA_MINIMA (soglia d'ingresso arena) — CHIUSO 13/08/2026, non è un problema di soglia
Sembrava un cambio di regime primavera/estate (train preferiva q basso,
test q alto, 3,2 errori standard di differenza) — ERA un artefatto di
composizione. Il modello prevede i singoli giocatori ugualmente bene nei
due periodi (residuo per carta +2,22 train vs +1,57 test, sostanzialmente
uguale). Il vero motivo: nella fascia di formazioni "di confine" (quelle la
cui decisione entra/non-entra dipende dalla soglia), il 30,9% ha una carta
a punteggio 0 (non ha giocato) in estate contro 18-19% ovunque altrove.
Separando con/senza carta a 0: entrare CONVIENE in ENTRAMBI i periodi
(+82,8 essenze/formazione train, +19,6 test — stesso segno). `QUOTA_MINIMA`
resta 0,10, NON si tocca: è la leva sbagliata per questo problema (alzarla
farebbe pagare a TUTTE le formazioni il rischio di una singola carta
panchinata). Idea proposta ma NON misurata: uno starter_odds più severo
solo per le formazioni vicine alla soglia — **valutata e scartata il
13/08**: le starter_odds su Sorare le impostano tracker umani indipendenti
per squadra (non un bookmaker/algoritmo), sono un margine di comodità
soggettivo, non una probabilità calibrata — non vale la pena costruirci
sopra una regola più fine. Script: `analisi_manager/p29_soglia_quota_minima.py`,
p35 (di Opus, `docs/handoff/RISPOSTA_OPUS_QUOTA_MINIMA_IL_PERCHE_2026-08-13.txt`).

### 5.10 Leakage grade Sorare — CHIUSO 13/08/2026, punto fisso in CLAUDE.md
Il voto A-F NON viene riscritto sul risultato della partita (due test
indipendenti, 120 partite-giocatore, zero query di rete: un punteggio di
100 resta un voto basso quanto un 31). Un margine residuo ACCETTATO
(~13% delle righe: un giocatore dato F che a sorpresa gioca può arrivare
nel backtest con un voto D/E che al momento della scelta era F) gioca
CONTRO il grade, non a favore — non gonfia le misure, semmai le sottostima.
Dettaglio completo e non riproporre: vedi CLAUDE.md, sezione "IL GRADE
SORARE NON HA LEAKAGE SISTEMATICO".

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

### Sessione 11/08/2026 sera — FILONE SOGLIE, CHIUSO: PAREGGIO_ARENA RESTA INVARIATA

Filone lungo (§15-21 di `RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt`), nato
da un'osservazione dell'utente sul proprio comportamento reale (schiera
solo ~60% delle arene consigliate, salta le "marginali") + una "spinta
cieca" di Opus poi riconosciuta artefatto circolare. Passato per un
tentativo di correzione APPLICATO IN PRODUZIONE e poi ANNULLATO nella
stessa sera (commit c7b298f507, revert `ca87663dfe`) quando Opus ha
trovato il proprio errore. Risultato finale: **`PAREGGIO_ARENA` resta
264,5/247,1/279,6/256,5, INVARIATA — il valore vecchio era gia' vicino
all'ottimo misurabile, non serve toccarlo.**

**Cosa e' vero e resta utile**:
- La selezione vera (`genera_arene_efficienti`, riga 1411-1479, produzione
  E Binario 2) entra con margine ZERO (`atteso > PAREGGIO_ARENA`).
  `QUOTA_MINIMA` (10%) e `_etichetta_arena` (righe 868-892, label
  "SCHIERA/MARGINALE/LASCIA PERDERE") sono SOLO visivi, non filtrano la
  formazione proposta. `verdetto_arena()` (895-907) e' funzione morta (mai
  chiamata in tutto il repo), stessa regola a margine zero — il commento
  "+9.800→+54.700" non e' mai stato verificato, da cancellare insieme alla
  funzione quando capita.
- Il punteggio REALIZZATO di pareggio (quanto serve DAVVERO per ripagare
  il biglietto, calcolato diretto dalla tabella premi vera, nessuna stima)
  E' 285,7/268,7/280,2/303,0 per cap260/220/beginner/uncapped — la vecchia
  calibrazione del 09/08 lo sbagliava con una retta unica su una curva
  convessa (piatta sotto soglia, a valanga sopra), riprodotto l'errore
  quasi esatto rifacendolo apposta (3 tipi su 4 entro 2,5 pt).
- **MA questo numero risponde alla domanda sbagliata per decidere se
  entrare.** La soglia di DECISIONE va confrontata con la PREVISIONE
  (`atteso`), non col punteggio realizzato: sulle formazioni vere la
  previsione media (264,5) e' giusta ma il vero oscilla di ~50 punti
  intorno ad ogni previsione (correlazione 0,25), e per la convessita' dei
  premi (vinci il jackpot se va bene, perdi solo il biglietto se va male)
  il guadagno atteso DATA la previsione e' piu' alto del guadagno calcolato
  AL punto della previsione (disuguaglianza di Jensen). Tradotto semplice
  per l'utente: la lotteria vale piu' del suo prezzo anche partendo un po'
  indietro — conviene entrare anche con una previsione sotto il "pareggio
  vero" in punti realizzati. Sono due grandezze diverse con lo stesso nome
  ("pareggio"), ed e' li' che si e' annidato l'errore.
- **Misurato direttamente** (binario1_out.json, 1.091 arene reali, premio
  VERO, bootstrap cluster manager-fixture): soglia sul valore di
  PREVISIONE T=250 -> +14.350, T=255 -> +16.550, **T=260 -> +18.400
  (ottimo della griglia)**, T=265 -> +14.200, ..., T=285 -> -150. La
  vecchia soglia 264,5 (+13.900, 92,5% positivo) e' STATISTICAMENTE
  INDISTINGUIBILE dall'ottimo 260 (delta -4.850, IC[-18.350;+6.600]):
  niente da guadagnare a ritoccarla. Nessun IC esclude formalmente lo
  zero, ma 5 soglie diverse concordano nella stessa direzione/ampiezza.
- **L'atteso NON e' sistematicamente pessimista** (ritrattata la misura
  precedente, +2,084 pt/carta): quel numero era condizionato su "il
  giocatore ha giocato" (il calcolo escludeva le carte a 0/DNP). Sulle
  formazioni VERE (DNP inclusi) il bias e' +0,62/+0,47 pt — sostanzialmente
  zero (4,42% delle carte reali segna 0, e la riconciliazione torna:
  0,9558×2,084 + 0,0442×(−46) ≈ −0,04). Aggiungere punti fissi all'atteso
  sarebbe stato ottimismo inventato — SCARTATO.
- **Trovata una cosa vera e azionabile, separata da tutto il resto**: le
  arene **UNCAPPED perdono soldi davvero**, −10.300 essenze reali su 98
  arene vere, negative a QUALUNQUE soglia testata nella griglia. Non
  ancora deciso cosa farne (disattivarle? altro?) — filone aperto, piccolo,
  se si vuole riprenderlo.
- **Sull'osservazione dell'utente ("gioco solo il 60%, salto le
  marginali")**: NON PROVATO ne' in un senso ne' nell'altro. Una prima
  lettura (col metro sbagliato) sembrava dargli ragione; col metro giusto,
  fra le arene REALMENTE giocate essere piu' severi di ~265 di previsione
  costa soldi — ma l'archivio contiene solo le arene che ha giocato, non
  quelle saltate, quindi non si puo' dire nulla su quella scelta specifica.
  Punto aperto, non risolto contro di lui.
- Resta valida un'attenzione generale: `netto_stimato` (calcolato con
  `PAREGGIO_ARENA`) contamina un confronto SOLO quando le due varianti
  confrontate entrano in un NUMERO DIVERSO di arene (es. gruppo grade,
  dove una variante spingeva ad entrare di piu' — vedi §5.6bis); se il
  numero di arene resta uguale (es. GK_ATT_AVV, che sceglie solo quale
  portiere schierare) non c'e' contaminazione.

**GK_ATT_AVV**: nessuna azione necessaria, resta il verdetto gia'
verificato due volte (+5.556, scomposto in +5.318 sull'89% delle coppie
robusto alla soglia). Il tentativo di riverificarlo con la soglia
(sbagliata) del §20 aveva indebolito il segnale — era un artefatto della
soglia troppo severa applicata in quel momento, non un problema di
GK_ATT_AVV: tolto insieme al revert.

Nessuna modifica netta al codice da questo filone (il tentativo e' stato
applicato e poi tolto lo stesso giorno). Dettaglio integrale:
`docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt` §15-21.

### Cosa serve per vincere, e cosa resta da esplorare
- **Soglie reali** (punteggio formazione, cap. incluso): media 261, podio ≈294,
  vittoria ≈352. Scalino 3°→4° solo 12 pt: podio su margini stretti. Una carta
  ≥75 ("boom") capita nel 13.9% dei pick; un flop (<25) uccide (0 flop → podio
  37%, 2 flop → 0%). Il modello ORDINA i boom (quintile-alto di atteso 26% vs
  11%; carta #1-atteso 21% vs 8% della #5) — ma vedi il blocco boom in §5:
  come leva d'azione è chiuso in tutte e tre le forme.
- (La voce "thread vivo" sulla correlazione atteso↔rank nelle Uncapped,
  −0,30 su n=31, è stata **eliminata il 09/08 su richiesta dell'utente**:
  tema minoritario, generava solo confusione.)

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
17. **I campi `next*` di Sorare (`nextClassicFixtureProjectedScore`,
    `nextClassicFixtureProjectedGrade`, ecc.) sono la prossima partita DEL
    GIOCATORE, non della giornata che stai analizzando** (09/08/2026 sera).
    Con due fixture consecutive aperte (una in corso, la prossima non ancora
    iniziata) un giocatore il cui club deve ancora chiudere la partita
    corrente avrebbe, in teoria, quella come "prossima" — mostrare il campo
    per la giornata successiva sarebbe silenziosamente la partita sbagliata.
    Verificato pero' che nello scouting lo scudo regge (§8ter): il
    refinement `playing_next=<fixture_target>` di `searchPlayers` filtra a
    monte solo chi gioca in QUELLA fixture, e il valore letto dopo coincide
    col bench scoped alla stessa fixture (116/117, incluso 8/8 sul
    sottoinsieme a rischio). Non estendere per analogia ad altri usi di
    campi `next*` senza rifare la stessa verifica.

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

**ARENE — CHIUSO l'11/08/2026, con una domanda diversa da quella iniziale.**
Tre giorni di tentativi (09-11/08) a misurare "G batte A in essenze" su
`archivio_ufficiale/` non hanno mai raggiunto un campione sufficiente:
n_discordanti (formazioni dove G e A decidono diverso) è salito 55→80→103→143
in quattro round di estrazione manager, sempre sotto la soglia (~213, poi
rivista a ~1.000 quando l'effetto misurato si è dimezzato) che servirebbe per
un segnale non spiegabile dal caso. **Servivano centinaia di manager in più:
irraggiungibile, estrazioni fermate.** Cronologia completa in
`docs/handoff/HANDOFF_ORCHESTRATORE_BINARIO_GVSA_2026-08-10.txt`.

La domanda giusta era un'altra, proposta da Opus l'11/08: non "il modello
completo batte l'altro" (poche formazioni, gli errori delle 5 carte si
annullano a vicenda), ma **"il grade sposta la previsione della singola
carta nella direzione giusta?"** — stesso archivio, stessi dati, zero query
nuove, ma 10.093 osservazioni invece di poche centinaia
(`analisi_manager/p26_test_carta_scala_storica.py`):
- **placebo** (voti rimescolati a caso fra le carte, 200 volte): il
  segnale vero non è mai raggiunto per caso, p=0,005 — non è rumore.
- **beta** (quanto del voto si traduce in punti veri): stima pulita
  (isolata dal livello medio di gruppo) **+0,554**, t=1,96 col
  raggruppamento più prudente.
- **corretto per l'errore del metro di misura** (lo stesso giocatore vale
  un voto diverso a seconda di quanti compagni ha nel gruppo quel giorno,
  ICC=0,542): beta **≈1,01**, intervallo di confidenza [0,36 ; 1,67] —
  **contiene esattamente il peso 1,0 già usato in produzione.**

**Verdetto: il grade funziona, ed è già pesato giusto. Nessuna modifica
alla produzione.** Metodo e numeri integrali:
`docs/handoff/RISPOSTA_OPUS_SCALA_STORICA_2026-08-11.txt` (la risposta che
chiude) e i tre scambi precedenti dello stesso giorno nella stessa cartella.

**Bug trovato e corretto nello stesso filone**: il confronto "quanto costa
la soglia d'ingresso arena" era distorto da un filtro che escludeva il 19%
delle formazioni — proprio le peggiori (una carta a 0 punti/DNP). Con
l'archivio corretto la soglia non costa valore, lo crea (formazione fissa
sempre schierata +11.500 contro chi filtra: A +13.550, G +17.050, su 1.099
formazioni). `analisi_manager/p23_binario1_mga.py` ha ora questo
comportamento di default; il vecchio filtro resta con `ESCLUDI_DNP=1`, solo
per confronto storico.

*(Le sezioni precedenti su "difetto strutturale dei gruppi piccoli" e
"tabella fissa vs z-score", scritte il 09/08 su un archivio che non è più
base di misura, sono superate dal lavoro sopra — non riaprirle: il
meccanismo che sembrava un difetto (gruppi piccoli) è lo stesso che l'11/08
ha permesso di misurare e correggere con la scala storica. Storia completa
nel git log se serve.)*

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

## 8bis-bis. Gruppo del grade esteso alla giornata — priorità 2, marathon 12/08/2026, PRONTO MA SPENTO

VERDETTO DA BAR: il voto A-F porta informazione vera anche a livello
essenze (dimostrato col placebo, non solo per correlazione a livello
carta) — ma la TAGLIA del guadagno resta incerta, e il numero migliore
visto oggi (+10.102) è il migliore di ~12 varianti provate sullo stesso
campione, quindi sovrastimato. Costruito un interruttore in produzione
(`GRADE_GROUP_STORICA_ENABLED`, **SPENTO di default**) e una
pre-registrazione congelata per il test fuori campione su GW5/6/7 (chiude
25/08/2026). **Non accendere prima di quel test.**

### Come si è arrivati qui (compresso — l'11/08 sera il gruppo nativo
lega/ruolo/giornata usato per lo z-score del grade risultò spento per il
51%+ delle righe di produzione, gruppo <2 membri). Round di misura del
12/08, in ordine, ciascuno ha trovato e chiuso un buco nel precedente:
1. Prima tabella sd_atteso costruita sull'archivio backtest (29 manager,
   biased): essenze +14.387, poi scomposto in ~45% "spinta cieca" (media
   non zero) + resto rumore — non provato.
2. Opus ha deciso la fonte giusta: `consiglio_*.txt` (la stessa
   popolazione che la produzione punteggia davvero), non l'archivio, non
   la cache game-log. Costruita (`p47_sd_atteso_produzione.py`, 2.333
   righe distinte da 8.419 file, dedup lega/codice/slug/kickoff).
3. Confronto fra RUN DIVERSE (regola violata: "il delta, non il valore
   assoluto") aveva illuso un miglioramento della fonte nuova — rifatto
   appaiato nello stesso run: nessun vantaggio provato della fonte sulla
   sorgente (`p50`).
4. Trovati e corretti due difetti veri: celle della tabella con n<2
   (sd=0, grade spento — lo stesso difetto che il filone vuole
   eliminare, spostato) e ricentraggio "a media zero" fatto con UNA sola
   costante globale invece che per ruolo (lasciava i portieri spinti in
   blocco -0,93pt, il 41% di una loro deviazione standard).
5. **Diagnosi finale della "spinta cieca" residua** (Opus, misurata non
   ipotizzata): il pool di backtest, essendo filtrato sulle sole carte
   che HANNO giocato (DNP escluso), ha per costruzione un voto medio +1,04
   più alto delle altre date dello stesso giocatore — un artefatto del
   BACKTEST, non della fonte. Le costanti di ricentraggio misurate sul
   backtest (per ruolo, +1,4pt) non sono trasferibili in produzione (dove
   la spinta vale solo ~0,2-0,3pt): non vanno spedite.

### La ricetta finale (12/08/2026 notte) e il controllo di Opus
Voto e sd_atteso dalla popolazione dei consigli, fattore_storico **0,482**
(ritarato sulla fonte nuova), ricentraggio PER RUOLO. Risultato (n=360
GW-manager, bootstrap cluster manager-fixture): **delta +10.102
IC95%[+1.494;+18.995] 98,8% positivo — primo numero che esclude lo zero.**

Opus ha attaccato la ricetta su tre fronti, tutti respinti:
1. **Placebo** (voto rimescolato dentro la GW-manager, 20 permutazioni):
   vero +10.102, placebo TUTTI negativi (mediana -10.656), 0/20 arrivano
   al vero → p≤0,048. Il guadagno è informazione vera, non un artefatto
   della macchina.
2. **"Vince solo entrando in meno arene"** (-34 arene, -3,1%): smentito,
   i placebo ne giocano 10 in meno e perdono lo stesso.
3. **"È solo il ribasso sui portieri"**: smentito, col ricentraggio per
   ruolo invece che globale il risultato è quasi identico (+9.888).

**Verdetto testuale di Opus, da riportare così com'è**: "PRONTA PER IL
FUORI CAMPIONE PRE-REGISTRATO, NON PER LA PRODUZIONE DIRETTA." Limiti
onesti che restano: fattore 0,482 stimato in-sample; ~12 varianti provate
sullo stesso campione (98,8% è condizionato alla ricerca); 45-46% del
guadagno viene da 5 GW-manager su 360 (mediana del delta = 0); il caveat
DNP si risolve SOLO sui dati nuovi (pool pre-partita vero, non filtrato
sull'esito).

### PRE-REGISTRAZIONE congelata il 12/08/2026 — NON toccare finché GW7 non chiude
- **Tabelle con cutoff vero**: `KICKOFF_CUTOFF=2026-08-14` (escludono
  righe con kickoff dentro/dopo la finestra di test). File congelati:
  `analisi_manager/dati/sd_atteso_produzione_righe_cutoff_2026-08-14.json`,
  `analisi_manager/dati/grade_scala_produzione_cutoff_2026-08-14.json`.
- **Fattore congelato**: 0,482. Ricentraggio: per ruolo, calcolato FRESCO
  sul campione del test (non le costanti vecchie, tarate sull'artefatto).
- **Metrica/decisione**: G_finale − G_baseline (lega_ruolo), Binario 2,
  bootstrap cluster manager-fixture. Segno negativo → non implementare
  senza rivedere. Segno positivo → si somma al placebo, non basta da
  solo (n troppo piccolo su 3 GW).
- **Attesa onesta**: molto più piccola di +10.102/360 per GW-manager —
  quel numero era il migliore di ~12 tentativi sullo stesso campione.
- **Fixture** (stesse di GK_ATT_AVV): GW5 `football-14-18-aug-2026`, GW6
  `football-18-21-aug-2026`, GW7 `football-21-25-aug-2026` (chiude
  25/08/2026).
- **Come lanciarlo**: dopo aver riestratto le 3 fixture in
  `archivio_ufficiale/`, `python analisi_manager/
  p57_grade_fuoricampo_preregistrato.py` (già pronto, testato oggi con 0
  fixture disponibili — esce correttamente senza calcolare nulla). Non
  rigenerare le tabelle congelate su dati nuovi.

### Interruttore in produzione — SPENTO di default (12/08/2026 sera)
`GRADE_GROUP_STORICA_ENABLED` (env var, default `'0'`) in
`build_formazione_globale.py`: quando acceso, `_apply_grade_group`
sostituisce il gruppo nativo con le due tabelle di produzione (fattore
0,482) e un ricentraggio per ruolo calcolato fresco su tutte le leghe di
ogni run (`_recentra_grade_per_ruolo`, chiamata da
`load_league_role_data()` dopo il doppio ciclo lega/ruolo — il
ricentraggio per ruolo serve vedere tutte le leghe insieme, impossibile
dentro `_apply_grade_group` che vede una lega+ruolo alla volta).
Verificato A/A: flag spento = bit-identico al comportamento di sempre;
flag acceso testato su dati sintetici (boost/penalità coerenti col
voto). Refresh tabelle: `generatore_formazioni/dati/
aggiorna_grade_scala_produzione.py` (zero query di rete, gira sempre nel
workflow anche a flag spento, così non sono stantie quando si accende).
Anche nel workflow `formazione_giornata.yml`, input `grade_group_storica`
(default `'0'`, descrizione esplicita "NON ACCENDERE prima del
25/08/2026" con il motivo). **Decisione dell'utente (12/08/2026)**: non
accendere ora nonostante il parere parziale di Opus, aspettare l'esito
del test fuori campione — ma l'interruttore va comunque scritto e
documentato ORA per non doverselo ricordare a mente tra sessioni/account.

File di riferimento: `analisi_manager/p47..p57` (intera catena di script
di misura del 12/08), `generatore_formazioni/dati/
aggiorna_grade_scala_produzione.py`, `docs/handoff/
RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt` §15-18 (round precedente, Opus).

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

**SUPERATO il 09/08/2026 sera — il grade C'È, anche su carte non possedute.**
Il campo giusto è `anyPlayer` → `... on Player { nextClassicFixtureProjectedGrade
{ grade } }` (oggetto `PlayerGameScoreProjection`, trovato per tentativi mirati:
l'introspezione è disabilitata, si legge il messaggio d'errore — vedi §8undecies
per il metodo). Arriva **gratis** dentro la stessa `SEARCH_QUERY` di
`scouting_gw.py` (nessuna chiamata in più): aggiunto in produzione il 09/08,
`pool_da_search` lo scrive come `g['grade']`.
Verifica di correttezza (non basta che il campo esista, deve essere la
lettera della fixture GIUSTA — vedi trappola nuova in §8): confrontato con
`discovery_fixture.fetch_grade_live()` (produzione, bench posseduto,
esplicitamente scoped alla fixture target) su 117 slug in comune —
**116/117 identici (99,1%)**, incluso il sottoinsieme a rischio (8 club con
una partita della GW precedente ancora da giocare: **8/8 identici**), unico
scarto di una lettera adiacente compatibile col movimento del grade vicino
al lock (§8bis). Lo "scudo" del refinement `playing_next=<fixture>` regge:
il campo riflette la fixture richiesta, non una partita precedente del
giocatore. Nessun uso ancora nel punteggio/ordinamento (resta colonna
mostrata) — **decisione aperta con l'utente**: non è ovvio che un segnale
per-partita debba pesare su una decisione d'acquisto pluri-giornata.
(Storico, superato: si era prima provato
`anyPlayer.playerGameScores(last:N).projection.grade`, che passa la query ma
dà SOLO lo storico — 0/50 casi coprivano la fixture futura, perché `last:N`
guarda per costruzione indietro, mai in avanti. Non era la dimostrazione che
mancasse una rotta per il futuro: era l'argomento sbagliato.)

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

## 8septies. Il criterio di scelta fra tipi di arena ignora il costo — CHIUSO (09/08)

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
necessaria in scouting_gw.py). **PUSHATO**: verificato il 09/08 notte che
`f9902af972` è in `origin/main` (`git branch -r --contains`). La riga
precedente diceva "non pushato, in attesa dell'utente": era stale.

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

*(storia, già superata: i premi veri sono stati scaricati e le soglie
applicate — vedi in cima a questa sezione)* Il campione dei **premi** non era
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

## 8duodecies. Marathon test end-to-end GW4/GW5 (12/08/2026 sera) — 4 bug di produzione chiusi, 1 feature nuova, 1 tipo formazione nuovo

Sessione nata per testare in reale la nuova feature ESSENZE_ARENA: il test
stesso ha fatto emergere bug preesistenti mai visti prima perché mai
provati end-to-end su GitHub. Ordine cronologico dei fix, tutti verificati
in locale/con query live PRIMA del commit, nessuno per intuito.

**1. Badge "fixture ambigua" — ora anche nel generatore, non solo scouting.**
Il marker `AMBIGUO_FIXTURE` (caso Freese, 10/08) prima era letto solo da
`scouting_gw.py` direttamente dai `prediction_*.txt`. Verificato con lo
stregone supremo che le 25 copie per-lega di `build_formazione_finale.py`
sono codice morto (`build_formazione_globale.py`/`best_five.py` caricano
SEMPRE E SOLO quella di `formazione_mls`): un solo file HTML da editare,
non 26. Propagato invece il parsing del marker nei `build_consiglio_
<ruolo>.py` (questi SÌ duplicati per davvero, uno per lega) con
`propaga_consiglio.py` (nuovo, stesso schema di `propaga_modello.py`) — 212
file, 53 leghe. Badge visibile ora in generatore (pcard + pannello "Top
esclusi") e scouting (tabella minimale, già c'era + tabella "candidati").

**2. FIX CRITICO — path Windows hardcoded rompeva OGNI run "Formazione
giornata" su GitHub da ieri sera.** `analisi_manager/p12_backtest_
formazione_grade.py:28` fissava `ROOT = r'C:\Users\Andrea\...'` (scritto
06/08 per uso locale). Da ieri sera importato da `generatore_formazioni/
dati/aggiorna_grade_scala_produzione.py`, wired nel workflow: `os.chdir(
ROOT)` a livello modulo crashava su ogni runner Linux, PRIMA che il vero
generatore girasse. Effetto silenzioso: lo step di generazione veniva
skippato (nessun `continue-on-error`), ma i due step dopo (commit +
notifica Telegram) hanno `if: always()` e giravano comunque, ripubblicando
l'ULTIMO HTML già presente — sembrava una run riuscita, non generava
niente di nuovo (scoperto perché il Telegram ha mandato un link a una
run del 28/07). Fix: `ROOT = os.path.dirname(SP)` (portabile). Verificato:
nessun'altra run era mai stata colpita, il bug è nato ieri sera e il mio
test end-to-end di oggi è stato il primo a incontrarlo davvero.

**3. Bug finestra giornata (stessa classe del caso McAllister) —
`role_data_ext` bypassava il filtro finestra.** Caso reale: run175
(11/08) ha schierato Kevin Mac Allister in un'Arena Beginner del pool
suppletivo con kickoff 15/08, fuori dalla finestra GW4 esplicita
(11-14/08) — tutte le altre formazioni della run erano corrette. Causa:
`role_data_ext` (letto SOLO dal pool suppletivo EXTEND_ODDS_060_070) veniva
catturato PRIMA che `filter_by_window()`/`EXCLUDE_SLUGS` girassero più
sotto — quei due filtri toccavano solo `role_data` (rinominato dopo).
Fix: i due filtri si applicano ora PRIMA che `role_data_ext` si separi da
`role_data` (riordino, nessuna nuova logica). Verificato con `_within_
window()` isolato: un kickoff fuori finestra viene ora escluso anche dal
ramo suppletivo.

**4. Nuova feature — ESSENZE_ARENA (budget in essenze per le arene
efficienti).** Richiesta esplicita utente: oggi `genera_arene_efficienti`
si fermava solo al NUMERO di arene richiesto, non al costo. Nuovo
parametro `budget_essenze` (default `None`, comportamento invariato): ad
ogni passo i tipi che sforerebbero il budget residuo vengono esclusi dal
confronto SOLO in quel passo (un tipo più economico può ancora entrare
dopo) — il criterio di efficienza resta lo stesso, il budget è solo un
tetto aggiuntivo. Nuova env `ESSENZE_ARENA`/input workflow `essenze_arena`
(default vuoto = nessun limite). Se impostata insieme ad `arene`, valgono
INSIEME (si ferma al primo che scatta).

**5. Bug trovato TESTANDO la feature 4 — pool suppletivo mai innescato in
modalità budget pura.** Il trigger del suppletivo guardava solo uno
SHORTFALL DI NUMERO (arene richieste - generate), sempre 0 senza `arene`
esplicita. Misurato su GW4: 24 DEF disponibili nella finestra, solo 2 con
odds ≥0.80 — gli altri 22 (banda 0.60-0.70) restavano irraggiungibili
anche con 900 essenze di budget libere (run reale: 1 sola arena generata
su 1000 di budget). Fix: tracciata la spesa della tornata primaria
(`_speso_arene_eff`), il suppletivo scatta ora anche a budget residuo >0.
**Verificato in produzione**: stesso mazzo/budget, da 1 a 9 arene generate
(budget 1000) e 12 arene (budget 2000, 1200/2000 spese, mai sforato).

**6. Bug discovery — odds di partite di coppa perse per sempre.** Le odds
di giornata si scaricano UNA volta in blocco a inizio run
(`_odds_giornata_condivise`/`pool_gw.json`, ottimizzazione voluta per non
fare query singole). Chi pubblica odds DOPO quello snapshot (partite di
coppa con kickoff lo stesso giorno, tipico) restava escluso in silenzio —
il fallback per-giocatore esisteva già ma scattava SOLO se l'intero blocco
era vuoto, mai per un buco puntuale. Casi reali: Nenad Cvetković (Rapid
Wien, Conference League), Ridvan Yılmaz (Beşiktaş, Europa League) — club
correttamente riconosciuto "in campo" (`squadre_in_campo` viene dalla
fixture Sorare completa, tutte le competizioni), ma odds mancanti nello
snapshot. Fix: per chi manca SOLO nel blocco, query di recupero
individuale mirata (mai per tutto l'elenco), tetto `ODDS_FALLBACK_MAX_PER_
RUOLO` (default 40). **Verificato con l'utente su 55 giocatori reali**
(screenshot odds 60-79% presi dal vivo sul sito Sorare, ruoli GK/DEF/MID/
FWD): 54/55 confermati presenti in una query fresca delle odds di
giornata con lo stesso valore mostrato a schermo, 1 escluso legittimamente
(dati storici insufficienti, non un bug).

**7. Nuovo tipo formazione — CHAMPIONS da 7 (competizione Sorare nuova,
apre alla GW5).** Regole identiche ad All Stars da 7 (stessa shape, nessun
limite classic — dichiarazione utente), pool ristretto ai 5 top campionati
(regolamento Sorare, screenshot utente: Premier League/Bundesliga/LaLiga/
Ligue 1/Serie A). **Investigazione sul campo giusto** (sessione con
l'utente che ha fornito query/screenshot dal vivo): il campo Sorare vero è
`Player.eligibleSo5Competitions` (slug `seasonal-champions`), ma l'API lo
RIFIUTA sia dentro una lista (`searchCards`) sia in batch con alias
multipli sullo stesso campo radice (`anyPlayer` duplicato) — costerebbe
una query per candidato, senza modo di comprimerla. L'utente ha poi
verificato le regole vere: è semplicemente "chi gioca nei 5 top
campionati", dato già noto per ogni candidato (`row['league']`) — **zero
query in più**. Implementato come clone 1:1 di ALLSTARS_U23 in ogni punto
(shape/priorità/pool/cap), priorità SEMPRE ultima (dopo All Stars, sia
tornata principale sia suppletivo — richiesta esplicita), cap 4
(confermato dall'utente = All Stars/Under23). Testato: A/A senza
CHAMPIONS richiesta (nessuna regressione); GW4 con CHAMPIONS=1 → zero
candidati (atteso, i top campionati non sono ancora iniziati a metà
agosto); test sintetico che conferma un candidato senza odds pubblicate
NON viene escluso dal pool primario (caso reale atteso per GW5, es.
LaLiga). **Test end-to-end reale su GW5 (odds=0, champions=4): NON ANCORA
RIUSCITO, bloccato dal problema 429 — vedi §8duodecies-bis.** Verifica coi
portieri LaLiga come gruppo di controllo (8 nomi forniti dall'utente dal
vivo, 1 escluso apposta per storico insufficiente) ancora da fare.

Nota a parte sul campo `eligibleSo5Competitions`: confermato DAVVERO
esistente e corretto (query live il 12/08 sera, anche con sessione
autenticata) — ma il rifiuto API è un limite REALE dello schema, non un
bug di query mal scritta: sia il batch con alias multipli su `anyPlayer`
sia l'inclusione dentro la lista `hits` di `searchCards` tornano un errore
esplicito di Sorare. Resta quindi solo per verifiche puntuali (1 giocatore
per query), mai per il bulk — la regola-lega implementata è la via giusta.

File toccati: `generatore_formazioni/build_formazione_globale.py`,
`discovery_fixture.py`, `analisi_manager/p12_backtest_formazione_grade.py`,
`formazione_mls/build_formazione_finale.py`, `scouting_gw.py`,
`propaga_consiglio.py` (nuovo) + 212 file `build_consiglio_<ruolo>.py`
propagati, `.github/workflows/formazione_giornata.yml`.

---

## 8duodecies-bis. Test GW5 Champions — 429 CHIUSO, 3 problemi nuovi APERTI

**Stato al 12/08 sera: il 429 è risolto e verificato su run vera. Restano 3
problemi nuovi, di cui uno BLOCCANTE (D1): non rilanciare il test GW5 finché
D1 non è corretto, la run rifallisce allo stesso punto.**

### Il 429 — CHIUSO (fix P5+P6, run 31585784239 pulita)

Causa vera, trovata da Opus leggendo i log grezzi (non era quella ipotizzata
nel brief): **non erano i 4 job che collidevano all'avvio**. Il job
`discovery def` alle 09:46:55 ha rifatto le 216 query odds della giornata
con 6 thread in 6 secondi, perché `_odds_giornata_condivise`
(`discovery_fixture.py`, `if not odds:`) scambiava "artifact con odds vuote"
per "artifact inutile" e rifaceva la fetch che il job `pool` aveva già fatto
per tutta la run. Con 4 job = **864 query identiche e tutte a vuoto** (la GW5
non ha odds pubblicate). Gli altri 3 job hanno preso il 429 di rimbalzo,
nello stesso decimo di secondo. L'intera ragione d'essere del job `pool`
("una fetch per run") si spegneva da sola proprio quando le odds non ci sono,
cioè a inizio stagione e su ogni GW lontana dal kickoff.

**Fix implementato (commit `0bd2c5bca6`)**: P5 = il pool scrive
`odds_fetched: True` in `pool_gw.json` e la discovery si fida dell'artifact
anche quando dice "zero odds"; P6 = stagger `sleep $((IDX*25))` sui 4 job
discovery. **Verificato**: run 31585784239, pool + 4 discovery tutti SUCCESS,
zero 429, fase discovery ~4 minuti.

Nota sul tetto Sorare: il "~60-70 richieste/minuto" ripetuto nei documenti
precedenti **non regge** — nella stessa run 216 query in 6 secondi sono
passate senza un solo 429. I dati sono compatibili con un credito di qualche
centinaio di richieste che si ricarica in minuti (Retry-After osservati: 152,
185, 289 s), ma **non è stato misurato**: non tarare parametri su quel
numero. Restano proposte e non implementate: P7 (tetto req/s di processo +
`odds_per_giornata` worker 6→2), P8 (probe sulle prime N partite), P9
(contatore richieste per job, per misurare il tetto vero invece di
raccontarselo). Dettaglio completo:
`docs/handoff/RISPOSTA_OPUS_429_PARALLELISMO_2026-08-12.txt`.

### I 3 problemi nuovi (run 31585784239, brief + risposta Opus)

Brief: `docs/handoff/BRIEF_OPUS_GW5_CHAMPIONS_RETEST_2026-08-12.txt`.
Risposta completa con le patch:
`docs/handoff/RISPOSTA_OPUS_GW5_CHAMPIONS_RETEST_2026-08-12.txt`.

**D1 — BLOCCANTE. `UnboundLocalError: _budget_essenze`** in
`build_formazione_globale.py`. Assegnata solo a riga 2304 dentro
`if _n_eff > 0 or _essenze_arena > 0:`, letta a riga 2367 dentro
`if EXTEND_ODDS_060_070:`. **La condizione di crash è più larga di come era
stata diagnosticata**: la riga 2367 sta PRIMA dell'if sugli shortfall, quindi
gli shortfall non c'entrano e la Champions #4 non generata è una coincidenza.
Crasha **ogni run** con `EXTEND_ODDS_060_070` acceso (default del workflow è
`1`) e `arene=0` e `essenze_arena=0` — anche una run con solo `allstars=2`.
Non è un caso di nicchia della competizione nuova: la riga è nata **oggi**,
commit `5894626839` (fix ESSENZE_ARENA). Fix: `_budget_essenze = None` prima
di riga 2302. Un setaccio AST passato su `build_formazione_globale.py`,
`discovery_fixture.py` e `pipeline_artifacts.py` dice che è **l'unico caso
vero** (18 altri candidati, tutti falsi positivi: global, try/except con
return, if/else che assegnano in entrambi i rami).

**D2 — notifica Telegram bugiarda.** Lo step ha `if: always()` e nessun
controllo sull'esito. Ma sotto c'è un bug più grosso: `_latest_html()` sceglie
per data di modifica fra **132 HTML** che `actions/checkout` ha appena
ripristinato da main tutti nello stesso istante — è una lotteria, non "il più
recente". Prova: su main il report più nuovo è run178 (12/08), la notifica ha
linkato **run97 (01/08)**. Nelle run riuscite funziona solo per effetto
collaterale (il file nuovo nasce dopo il checkout). Fix in due livelli: (a) il
generatore scrive il path in `_ultimo_report.txt` e il notificatore legge
quello, saltando la notifica se manca; (b) `id:` sullo step di generazione +
`if: always() && steps.genera.outcome == 'success'`. Regola generale che ne
esce: **una notifica non deduce mai il suo contenuto dal filesystem, lo riceve
da chi l'ha prodotto.**

**D3 — 92% del predict sprecato.** Misurato sull'output committato della run
(`6c87bbb097`) col modello di costo del repo (`pipeline_costi.json`):
**1151 giocatori in 28 campionati = 3219 secondi-compute**, contro **53
giocatori (270 s-compute)** nelle 5 leghe Champions — cioè il **91,6%** del
lavoro non serviva. Dettaglio che conta anche fuori dall'ottimizzazione:
**tutti e 53 sono in Spagna** (Premier/Bundesliga/Serie A/Ligue 1 non hanno
partite nella finestra 14-18 ago), quindi oggi la Champions da 7 pesca da un
solo campionato. `discovery_fixture.py` **non legge** CHAMPIONS/ALLSTARS/
IN_SEASON (verificato su tutte le sue `os.environ.get`), mentre il workflow gli
passa `ARENE_EFFICIENTI`/`ESSENZE_ARENA` che nessuno legge: env morte.
La logica di unione delle leghe rilevanti **esiste già** in
`build_formazione_globale.py:2100-2108` (va estratta in un modulo condiviso, e
corretta: `champions_qty` oggi forza *tutte* le leghe invece di
`CHAMPIONS_LEAGUES`).
**Trappola da non ignorare**: la discovery *svuota* i file delle leghe che
esamina — è il fix del 07/08 (caso Gallese). Restringendo a 5 leghe, le altre
27 restano su main coi file di ieri. La restrizione va committata **insieme**
alla scrittura dei file vuoti per le leghe escluse, altrimenti è una
regressione. Costi accettati da decidere: le odds storiche delle leghe escluse
per quella GW **non si recuperano più**; la cache game-log invece è solo
rinviata.

Ordine consigliato: D1 → D2 → D3 ristretto al solo caso "champions e basta"
(+ file vuoti) con misura su run vera → generalizzazione.

---

## 8duodecies-quater. VELOCITÀ DELLA PIPELINE — sessione 12/08/2026 pomeriggio

**Dettaglio completo, con tutte le misure:
`docs/handoff/RISPOSTA_OPUS_VELOCITA_STRUTTURALE_2026-08-12.txt`.** Qui solo
il minimo per orientarsi.

Domanda di partenza: la run da 18 minuti è colpa del preseason o della scala
della richiesta (30+ arene)? **Nessuna delle due.**

- Il **generatore non c'entra**: lo scenario reale completo dell'utente (30
  arene efficienti + 6 MLS + 6 K League + 4 U23 + 4 All Stars + 4 Champions
  = 54 formazioni) gira in **3,1 secondi** in locale. Il numero di formazioni
  richieste non tocca né discovery né predict, nemmeno via pool suppletivo.
- Il tempo stava tutto nella **fase predict**, e il 60-65% di quella fase era
  **attesa dopo le risposte 429 di Sorare** (Retry-After da 194-247s l'una).

**Sei fix, tutti in produzione e misurati** (le run: 31591410268, 31593062806,
31594791690, 31596309760, 31597760654):

1. `cdd0019647` — il game log dei giocatori con meno di 30 partite FINAL si
   ri-scaricava **per intero a ogni run, per sempre** (523 su 1151). Ora si
   annota che la storia è completa e basta una pagina di controllo.
2. `1c2af4d3fa` — il dettaglio granulare si chiedeva **una partita per query**:
   ora 6 alla volta (tetto di complessità sondato sull'API: 63,1 a partita,
   massimo teorico 7).
3. `736ddbb0c4` — **il più grosso**: `actions/upload-artifact` scarta di
   default i file nascosti, e le due cache condivise vivono in
   `.game_log_cache` e `.cache`. Da quando la pipeline usa gli artifact,
   **tutto il lavoro di cache del predict veniva buttato a fine run**. Corretto
   anche in `best_five.yml` e `cache_backtest_arene.yml` (quest'ultimo
   caricava un artifact completamente vuoto).
4. `ffd75f5415` — stessa cosa del punto 1 per i panchinari (storia lunga, poche
   partite giocate): marcatore `ampio_inutile`.
5. `358eb97aff` — il link Telegram usciva 404 (path assoluto nel sentinella):
   regressione del fix D2, corretta su entrambi i lati.
6. `pipeline_artifacts.py N_BIN 45→20` + via lo stagger della discovery — i 429
   seguono il **numero di shard**, non il volume di query.

**IL RISULTATO CHE CONTA — lo scenario vero è già a 6 minuti.** Dopo aver
inseguito a lungo il caso preseason, ho misurato una giornata VERA (run
`31599223469`: gameweek 4, soglia starter-odds 0,80, 2 arene):

| | preseason (gw5, soglia 0) | **giornata vera (gw4, soglia 0,80)** |
|---|---|---|
| run intera | 12,8-13,3 min | **6,3 min** |
| giocatori | 1153 | **122** |
| query | 1504 | **264** |
| risposte 429 | 27 | **0** |
| secondi persi nei 429 | 4644 | **0** |

Zero 429, non uno. Il problema dei 13-18 minuti **non era la pipeline, era il
preseason**: a `MIN_STARTER_ODDS=0` non esiste nessun filtro, entrano tutti i
posseduti delle squadre in campo, e con quel volume l'account va a sbattere
contro il proprio tetto. Con la soglia attiva ne sopravvivono 122 e il limite
non si sfiora nemmeno. **L'obiettivo dei 7-8 minuti è raggiunto dove conta.**

Settimo fix, trovato proprio guardando quella run: il predict faceva girare
**45 job per 122 giocatori** (uno o due a job, ~22s fissi di checkout+setup
ciascuno). Il numero di bin era limitato solo da quante coppie lega/ruolo ci
fossero; ora è limitato anche dal carico stimato. Con carico grande non cambia
nulla.

**Due lezioni metodologiche da non perdere** (sono nel file, §7.9):
- l'ipotesi "meno query = meno tempo, proporzionalmente" è **falsa**: le query
  sono scese del 78% e il tempo solo del 43%, perché l'attesa da 429 è rimasta
  piatta;
- l'esperimento che sembrava falsificare "i 429 nascono dalla raffica" era
  **rotto**: il freno delle query non attraversava i processi (ogni giocatore
  è un processo nuovo), quindi non stavo misurando il pacing ma un
  interruttore staccato. Corretto in un commit dedicato. È esattamente la
  trappola descritta in CLAUDE.md.

**Effetto collaterale da tenere d'occhio**: ora le cache tornano davvero su
main, quindi il repo cresce (~135 MB grezzi la prima run, poi solo le
differenze vere). Se a regime pesa, l'alternativa è `actions/cache` — decisione
aperta, tocca anche gli strumenti locali che leggono la stessa cache.

---

## 8duodecies-ter. Cronologia del 429 GW5 (storico, chiuso)

Cronologia: primo tentativo GW5 (odds=0, champions=4) — 429 su tutti e 4 i
job discovery, mai uscito dalla fase discovery in 5+ minuti, run cancellata
dall'utente. Diagnosi chiesta ad Opus (lo stregone supremo) via brief
(`docs/handoff/BRIEF_OPUS_429_FALLBACK_ODDS_2026-08-12.txt`), risposta
completa in `RISPOSTA_OPUS_429_FALLBACK_ODDS_2026-08-12.txt`: causa =
tetto Sorare cumulativo ~60-70 richieste/minuto (misurato 28/07), 4 job
paralleli non coordinati, più un bug preesistente (dal 07/08) per cui a
blocco-odds vuoto (stagione non iniziata) il fallback andava SENZA tetto su
tutto l'elenco. Piano P1-P5 proposto; **P1+P4 implementati e pushati**
(commit `caa5b9599b`): a `MIN_STARTER_ODDS<=0` il recupero individuale si
salta del tutto (sia il fallback mirato sia il vecchio ramo senza tetto);
i loop di recupero si fermano al primo 429 invece di macinarne altri.
Default `0.80` invariato (entrambi i gate sono no-op in produzione normale).

**Secondo tentativo (run 31584309722, dopo il fix): 429 di nuovo su tutti
e 4 i job — ma stavolta PRIMA del punto corretto.** Log: job `pool`
finisce alle 09:46:08, i 4 job `discovery` partono ~5s dopo, il primo 429
nel job `gk` arriva alle 09:46:55 sulla PRIMISSIMA query dello script.
Conclusione tratta allora: "il collo di bottiglia è la coda di query del job
`pool` che si somma alle prime query simultanee dei 4 job `discovery`".
Run cancellata di nuovo dall'utente.

**Quella conclusione era SBAGLIATA** — corretta da Opus leggendo i log
grezzi: il job `pool` finisce senza un solo 429, e le 4 prime query dei job
discovery non possono sfondare un limite che 70 secondi prima ne aveva
accettate 216 in 6 secondi. Il colpevole era il job `discovery def` che
rifaceva la stessa raffica di 216 query. Vedi la sezione sopra
(`RISPOSTA_OPUS_429_PARALLELISMO_2026-08-12.txt`) per il meccanismo vero.

---

## 8quinquies. Altri fili aperti del 06-07/08 (riepilogo secco)

- **`crowss` = l'utente stesso, verificato NON contaminare nulla** (D1):
  assente per costruzione dal verdetto capitano (`p11_bloccato_tutti_mazzi.py`
  lo esclude hardcoded) e dallo smart-money (0 righe in tutte le GW
  controllate). L'unico posto dove è nel campione, legittimamente, è il
  backtest formazione di G (uno dei mazzi profondi). Chiuso, non riaprire.
- **Odds+4ruoli — CHIUSO il 09/08 per decisione dell'utente**, insieme a
  tutto il filone favorito-odds (§8nonies e punto fermo 2). Era rimasto
  "in pausa" perché il DEF passava la griglia per-carta (7/9 varianti) ma
  il backtest in formazione poggiava su 2 soli mazzi profondi. Non si
  riapre: allargare il campione avrebbe richiesto altri manager, e dal
  09/08 i backtest si fanno solo sulle giornate dell'utente (regola in
  testata). Storia in `docs/handoff/HANDOFF_FAVORITO_ODDS_2026-08-06.txt`.
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

**10/08/2026 sera — Pool suppletivo odds 0.60-0.70 per Arena Beginner/All
Stars/Under23, VALIDATO su piu' run reali, ora ACCESO DI DEFAULT nel
workflow `formazione_giornata.yml`** (commit `c23a3b3d2d`, `006a09c018`,
`cec054ea96`/`8cafd0a3fb`). `EXTEND_ODDS_060_070` resta un env var normale
(default `'0'` nel codice Python, invariato per chi lo richiama fuori da
questo workflow -- run locali/altri workflow): e' SOLO l'input del
dispatch di `formazione_giornata.yml` ad avere default `'1'` ora, decisione
esplicita dell'utente dopo aver verificato piu' run reali che non
appesantisce i tempi. Acceso: la
discovery tiene ANCHE la fascia 0.60-0.70 (unica possibile sotto 0.80, le
odds Sorare escono a blocchi da 10) oltre alla soglia normale; il
generatore filtra SEMPRE `role_data` a >=0.80 per tutta la pipeline
esistente (FASE 1, ARENE_EFFICIENTI, ALLSTARS/U23, FASE 1b — a flag spento
e' un no-op). Un passo nuovo, dopo la tornata primaria, controlla lo scarto
fra richiesto e generato per Arena Beginner (unica arena ammessa) + All
Stars + All Stars Under23, e prova a colmarlo con lo stesso `card_pool` gia'
consumato (mai carte gia' usate sopra) esteso alla banda 0.60-0.70 + il
residuo 0.80+ non scelto. Nessuno sconto sul punteggio per le odds piu'
basse (richiesta esplicita utente: vanno valutate come le 0.80+).
Due bug reali trovati dall'utente confrontando run vere col pool visibile
su Sorare, entrambi fixati in giornata: (1) il passo suppletivo provava
ALLSTARS prima di ALLSTARS_U23, invertito rispetto a `PRIORITY_ORDER` (U23
ha priorita') — le All Stars esaurivano candidati U23-eleggibili prima che
toccasse a Under23; (2) ordine interno del SOLO suppletivo poi cambiato su
richiesta esplicita: Under23 scavalca le arene qui (1-Under23, 2-Arena
Beginner se ancora scoperta, 3-All Stars) — nella tornata primaria
`PRIORITY_ORDER` resta invariato (arene prima). Verificato su run reali
GW4: mancanza di formazioni Under23 e' risultata pool reale (solo 2 GK e 4
DEF U23-eleggibili in tutto il pool esteso, tutte le leghe), non un bug.
Aggiunta anche la starter-odds su OGNI carta del report HTML (badge
ingrandito 0.85rem/blu dopo feedback "quasi invisibili"), zero query in
piu' (dato gia' persistito da discovery_fixture.py). Verificato che
`ESCLUDI_LOCKATE` protegge anche il pool esteso: le carte bloccate si
scartano in discovery PRIMA di qualunque filtro odds (riga ~1423, il
filtro banda e' alla riga ~1596), quindi non entrano mai ne' nel pool
primario ne' in quello esteso -- nessun collegamento separato da
mantenere. Input rimossi dal dispatch dello stesso workflow perche'
confondevano il lancio manuale (commit `9f77be8759`):
`arena_criterio` (restava sempre `'assoluto'`, mai scelto `'capitale'` per
la produzione) e `list_unused_candidates` (fissato acceso, e' solo log).

**10/08/2026 sera — Fix bug reale: giocatore trasferito spariva dalla
discovery per `activeClub` stantio** (commit `92cdd42566`). Caso trovato
dall'utente confrontando lo screenshot del banco MID di GW4 con
`player_card_counts.json`: Jamiro Monteiro mancava dal pool eleggibile pur
avendo una partita reale l'11/08 (90% titolarità). Causa: il pre-filtro
"squadre in campo" in `discovery_fixture.py` (~riga 1407) guardava solo
`anyPlayer.activeClub.slug`, e Sorare non aveva ancora aggiornato il campo
dopo il trasferimento (PEC Zwolle invece di NEC Nijmegen, la squadra reale
della partita). Fix: fallback su `odds_giornata` (mappa slug→starter-odds
da `anyGame.playerGameScores` di tutte le partite della fixture,
indipendente da `activeClub`, già in cache — zero query extra): se il club
della carta non gioca ma il giocatore compare comunque nella mappa odds,
resta nel pool. Verificato su dati reali GW4 (football-11-14-aug-2026):
`nec-nijmegen` è fra le squadre in campo, `pec-zwolle` no, Monteiro
compare in `odds_giornata` con 0,90 → col fix resta nel pool MID. Fix
strutturale (non tarato sul caso Monteiro): copre qualunque trasferimento
non ancora riflesso da Sorare, non solo questo. `lega_di`/`club_di`
restano derivati da `activeClub` (non toccati da questo fix: il routing
lega funziona comunque nei trasferimenti fra club dello stesso campionato,
non è garantito per i cross-lega).

**10/08/2026 pomeriggio — Fix bug reale: ARENE_EFFICIENTI non rispettava
PRIORITY_ORDER su ALLSTARS/ALLSTARS_U23** (commit `33625d456a`). Trovato
dall'utente confrontando due run GitHub identiche su `ARENE_EFFICIENTI=10`:
run158 (10 arene + 4 AllStars + 4 U23 richiesti) → solo 4 arene generate;
run159 (solo 10 arene) → 9 arene, di rendimento nettamente più alto.
Causa: la FASE 1 di `build_formazione_globale.main()` generava TUTTI i
tipi con conteggio esplicito (`ALLSTARS`/`ALLSTARS_U23` compresi) PRIMA
che partisse il blocco `ARENE_EFFICIENTI` — che in modalità "efficiente"
non ha conteggio esplicito, quindi trovava il pool già mangiato da
AllStars/U23, pur essendo queste ultime le tipologie a priorità PIÙ BASSA
in `PRIORITY_ORDER` (riga 307-312: arene sopra Under23/AllStars). Fix:
la FASE 1 ora si ferma prima di `ALLSTARS_U23`/`ALLSTARS`, il blocco
`ARENE_EFFICIENTI` gira sul pool ancora intatto, e solo alla fine
`ALLSTARS_U23`/`ALLSTARS` attingono al residuo. Verificato in locale
rigiocando gli stessi input delle due run (stesso risultato di run159 in
entrambi i casi) e con una terza run GitHub reale (4 arene + 4 AllStars,
run160): le prime 4 arene sono risultate IDENTICHE, carta per carta e
nello stesso ordine, a quelle di run159 — conferma che la selezione delle
arene è ora deterministica e indipendente da cos'altro viene richiesto
insieme. **Difetto cosmetico NON toccato** (separato, minore): il
contatore nel `subhead` dell'HTML mostra ancora "Arena All Stars=0" anche
quando le arene sono presenti davvero nel corpo della pagina — scollegato
dal conteggio reale, non influenza la generazione, solo il riepilogo
mostrato.

**10/08/2026 — Fix "fixture ambigua" su TUTTI i predict (212 file) +
scouting riscritto in modalità minimale** (commit `8e6e1df8a7`,
`1dc1b81438`, `7b71e5638b`, `548242f743`, `282a974482`, `0582a7a836`).
Bug reale (caso Matt Freese): quando il club di un giocatore ha due
partite future ravvicinate di competizioni diverse (Leagues Cup + MLS),
`test_{gk,def,mid,mls_fwd_all}.py` prendeva sempre `future_games[0]`
(la più vicina), anche se apparteneva a una giornata diversa da quella
target — Freese predetto sul 9/08 (Leagues Cup) invece del 13/08 (GW4
vera). Fix (idea dell'utente): se ≥2 partite future hanno GIÀ le starter
odds pubblicate insieme, si schiera sempre sull'ULTIMA con odds, mai
sulla prima (nel caso normale, solo una ha odds, comportamento
invariato — zero rischio). Nuova funzione `_prossima_partita_vera()`,
propagata identica a tutti i 212 file (stesso pattern duplicato per
lega, non condiviso). Marker `AMBIGUO_FIXTURE: si` nel file di
predizione quando scatta, letto da scouting per un badge ⚠️ non
bloccante (badge lato generatore, catena consiglio→finale→card HTML su
26 leghe, **NON fatto**, vedi §10bis). Testato con query reali su 7
giocatori/4 leghe: nessuna regressione, Freese corretto.

Insieme, stessa sessione: grade trovato e verificato
(`nextClassicFixtureProjectedGrade`, §8ter/§8bis), scouting riscritto
`--minimal` con colonna A+G, filtro ruolo esclusivo, Best Five/Best per
ruolo (§2.2), riuso predizioni spento di default nello scouting.
**Identificato ma NON risolto**: collo di bottiglia nel workflow
`scouting_gw.yml`, job `predict` — 60-80% del tempo per job è contesa
git (20 job paralleli che pushano sullo stesso branch), non calcolo
(predict vero 2-6s). Fix proposto (artifact per job + un commit solo a
fine matrice) non ancora implementato, vedi §10bis.

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

**NOTA MINORE sulle arene dedicate per lega** (chiarito dall'utente il
09/08, per chiudere un contrasto apparente nel file): nelle soglie sono
state **allineate alle cap 260** (§8octies), ma nel generatore restano
**spente di default** e l'utente **de facto non le schiera**. Quindi
tarare le loro soglie non contraddice il fatto che siano disattivate:
sono valori pronti nel caso si riaccendano. **Tema minore, nessuna
azione, non farne un filone.**

**SOSPETTO, non un difetto accertato — declassato il 09/08 dall'utente.**
In `HANDOFF_SOGLIE_DEFINITIVE_2026-08-08.txt` (righe 771-781) è scritto
che il generatore sarebbe non deterministico run-to-run: due esecuzioni
identiche avrebbero allocato diversamente le formazioni opzionali (pool
residuo) fra cap260/cap220/uncapped, per via della randomizzazione degli
hash di Python su set/dict, e con `PYTHONHASHSEED=0` sarebbero tornate
identiche.

**Perché resta solo un sospetto**: cercato il 09/08, **i due output
divergenti non esistono nel repo**. Non si sa quali arene siano cambiate
né a che distanza di tempo le run siano state fatte. L'unico riscontro
materiale sono `run154_231251` e `run155_231910` in
`generatore_formazioni/output/`, a 6 minuti l'una dall'altra e identiche
al byte (105.515) — cioè coerenti con le run fatte DOPO aver fissato il
seme, non con quelle che divergevano.

**Obiezioni dell'utente, che il documento non sa escludere**: fra due run
a distanza di minuti può essere successo altro — un giocatore uscito dal
pool, uno sceso sotto la soglia odds, uno che ha iniziato a giocare e
l'altro no. E in ogni caso il generatore massimizza comunque l'atteso e
resta dentro i vincoli di competizione e di cap: anche invertendo due
carte non produce una formazione illegittima o irrazionale.

**Decisione: non ci si spende tempo.** Se ricapita, l'utente se ne
accorge. Chi volesse chiuderla davvero deve produrre il caso concreto
(due run di fila sulla stessa giornata + diff degli output), non citare
di nuovo questa voce.

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

## 10bis. COSE DA FARE — riscritto il 09/08 notte, ripulito 11/08 (verificato contro il codice, non a memoria)

**FATTO, non più aperto (verificato 11/08 leggendo codice/repo, questa
sezione era rimasta ferma al 09-10/08):**
- Riverifica G-vs-A su `archivio_ufficiale/`: fatto, 29 manager (non più
  13 in attesa), è l'archivio usato oggi stesso per il filone GK_ATT_AVV.
- Pool supplementare starter-odds 0,60-0,70: implementato e IN PRODUZIONE
  (`EXTEND_ODDS_060_070`, acceso di default nel workflow).
- Collo di bottiglia git push nel job `predict`: risolto, il job ora è
  interamente artifact-based (`upload-artifact`/`download-artifact`),
  nessun commit+push per shard.
- `GK_TEAM_CS_WEIGHT` "default fasullo 0,5": non è vero nel codice attuale
  — il default è `22.0/35.0≈0,629`, un valore calibrato (`test_gk.py:190`).
- Fix "prossima partita" (caso Freese, `anyFutureGames`): propagato a
  tutti i predict, commit `8e6e1df8a7`. Resta aperto solo il pezzo
  cosmetico (badge nel generatore, non nello scouting) già descritto sotto
  correttamente come bassa priorità.
- "`level_score` binario del portiere, leva mai raccolta": non è vero,
  `test_gk.py` ha lavoro esteso (Stadio A/B/D, `extract_level_score`,
  `expected_level_from_rates`) già fatto su questo fronte.

**FATTO il 12/08/2026 sera — badge "fixture ambigua" ora anche nel
generatore.** Vedi §8duodecies per il dettaglio: 1 solo file HTML da
editare (le 25 copie per-lega erano codice morto), non 130 — scoperta che
ha dimezzato il costo stimato qui il 10/08.

**ESPLORATO PER INTERO l'11/08/2026 sera — vedi §8bis-bis.** Il caso
Lloris era solo la punta: il gruppo minuscolo tocca metà delle righe di
produzione. Livello carta: valido, confermato. Livello essenze: non
ancora provato. Priorità 2 quando si riprende (dopo il filone soglie,
chiuso l'11/08 sera). Non ripartire da qui, leggere §8bis-bis.

**Aggiunto 10/08 notte: difetto strutturale nella scelta della "prossima
partita" per il predict (test_gk.py e affini, condiviso da scouting E dal
generatore).** Caso reale: Matt Freese (NYC) ha una partita di Leagues Cup
il 9/08 (prima della finestra GW4, competizione diversa) e la vera
partita MLS della GW4 il 13/08. Il predict prende `anyFutureGames` e usa
SEMPRE il primo nodo (la partita cronologicamente più vicina), senza
controllare se cade dentro la finestra della giornata target — ha quindi
calcolato l'atteso per la partita di Leagues Cup del 9/08. La rete di
sicurezza di scouting (`_atteso_dai_consigli`, controllo sulla finestra
`Data:`) ha scartato correttamente quel numero (nessun valore sbagliato
mostrato), ma il risultato e' un buco: Freese resta senza Atteso/A+G pur
avendo uno storico enorme, un problema diverso da chi non ha proprio
abbastanza storico (Miller/Rick). Root cause verificata sul campo (query
`anyFutureGames` diretta, non dedotta): Sorare restituisce ENTRAMBE le
partite come "scheduled", lo script non filtra per competizione/finestra.
Tocca un file condiviso con la produzione (stesso `test_gk.py` che gira
per l'owned-card): fix da valutare con l'utente prima di toccarlo, non
banale da isolare al solo scouting. Non ancora quantificato quanti
giocatori nel pool sono colpiti (nessuna misura fatta, solo il caso
Freese ispezionato).

**Tutto quello che era in cima a questa lista il 09/08 mattina è FATTO**:
premi scaricati, soglie applicate, G validato sulle arene, filone odds
chiuso. **Aggiunto 09/08 sera**: filone "tabella fissa per lettera" testato
pulito e CHIUSO (non batte lo z-score, §8bis); resta produzione lo z-score.
Quello che segue è quello che resta, in ordine di interesse.

### INDICE DEI FILONI APERTI (orchestratore, 09/08 notte)

Ricognizione fatta dopo la chiusura di capitano-grade (`2da426e987`) e
copertura-grade (`de527216e8`). Raggruppati per natura, così si sceglie
sapendo che tipo di lavoro si compra.

**A. Bloccati dalla POTENZA STATISTICA, non dall'idea.** Tre filoni di G
(copertura b/c, capitano, tabella fissa) sono finiti con IC95 larghi
±20-30k in allocazione su 6 GW e 24 manager. Nessuno dei tre si sblocca
rifacendo i conti sugli stessi dati: o si allarga il campione, o si
misura sulle giornate reali dell'utente (strada che ha indicato lui).
**Prima di aprire un altro test-di-formula su questo archivio, chiedersi
se ha la potenza per rispondere** — le ultime tre volte non l'aveva.
Voci: 5, 6, 14. La voce 1 (G sopra il filtro odds) è stata
**ridimensionata**: poggiava su una premessa falsa sul pool, vedi lì.

**B. Misurabili subito, dati già in repo, nessuna query.** Voci 2
(segregare il rischio DNP in una Beginner), 7 (correlazione grade ↔
realizzato: limite superiore alla contaminazione), 3 (perché il
generatore non ha un criterio nella fase opzionale).

**C. Difetti noti, costo basso, nessuna ricerca.** `PYTHONHASHSEED=0`
nell'ambiente di lancio (§9); default fasullo `GK_TEAM_CS_WEIGHT=0.5` in
`backtest_arene_previsioni.py:257-260` (§5.7); 21 script con path Windows
hardcoded (voce 11); Russia coperta ma non popolata (§7). Sono tutti
"si fa e si chiude", non producono conoscenza.

**D. Aperti che richiedono dati NUOVI (query/run).** Voce 9 (odds+4ruoli,
serve campione profondo), voce 10 (buco premi Uncapped rank 1/3, forse
già chiuso da v3 — **verificare prima di lavorarci**), voce 12
(estrazione grade storico, 1 query/giocatore), voce 8 (decisione grade
nello scouting, che è una scelta di significato più che una misura).

**E. Il tetto vero.** §5.1 resta il vincolo di fondo: il punto è piatto e
la leva rimasta è la PRECISIONE (§6, 1 punto = ~4,7 essenze). I filoni
sopra sono quasi tutti su *come si usa* la previsione, non su quanto è
buona. L'unica leva grossa mai raccolta sul lato precisione è il
**`level_score` binario del portiere** (§5.6), dichiarata "la più grande
lasciata sul tavolo" e mai ripresa.

**CHIUSO 09/08 notte — CAPITANO SCELTO COL GRADE: GRADE NON VINCE.**
Testato da Sonnet con `analisi_manager/p21_capitano_grade_backtest.py`
(nuovo file, riusa build_one_lineup_with_growth/S21.costruisci, nessuna
modifica alla produzione). Gerarchia implementata: (1) fascia alla lettera
più alta A>B>C>D>E; (2) a parità, atteso_cal più alto; (3) se gli attesi
sono entro un margine M, si sceglie per ruolo; (4) le carte senza lettera
(e le F, escluse dal livello 1) competono normalmente sull'atteso TRANNE
quando la lettera migliore presente è A o B, che allora vince sempre
(interpretazione dell'orchestratore sul caso non coperto letteralmente dal
brief, annotata nel codice).

Numeri di controllo (§3 del brief) VERIFICATI identici: pool 7619 carte,
con grade noto 7381, F 778, unità in allocazione prima del filtro F 53,
scendono ad astensione dopo il filtro 2. Manager distinti/GW: vedi JSON
(`controlli.manager_distinti`/`gw_distinte`). C1 (interruttore spento =
identità alla baseline, bit per bit) **PASS** su tutte le 4 combinazioni
popolazione×soglie. C2 (la fascia cambia carta davvero): 164-247 arene su
460-564 a seconda del ramo — l'interruttore si muove, non è rumore.

**Confronto (A) primario, P_noF (M=1, ordine FWD>MID>DEF>GK, di
riferimento — griglia completa nel JSON):**
| soglie | n | netto base | netto grade | delta | IC95 |
|---|---|---|---|---|---|
| vecchie | 460 | 40700 | 39250 | **−1450** | [−3850; +800] |
| nuove | 476 | 44800 | 43300 | **−1500** | [−5050; +1600] |

Delta negativo su entrambi i set soglie, IC95 attraversa lo zero in
entrambi → **GRADE NON VINCE** per il criterio del brief (§6). Il segno è
STABILE negativo su P_noF (non solo "non distinguibile da zero" positivo
come ipotizzato dall'orchestratore in partenza — l'ipotesi era sbagliata
nel segno, dichiarato come da regola CLAUDE.md).

Su P_ALL (secondario, limite superiore per leakage) il segno si INVERTE:
+1150/+2450 essenze, ma anche lì IC95 attraversa lo zero. Non decisivo, e
comunque non è la popolazione che decide (§6 del brief).

Protezione (soglia reale≤1) quasi vuota su P_noF come previsto (n=2-5):
nessun verdetto costruibile lì. Spinta (n=453-539, quasi tutto il
campione) porta lo stesso delta negativo del totale: il danno non viene da
mancata protezione, viene da come si sceglie fra capitani che GIOCANO
entrambi — la distribuzione delle lettere lo conferma: il ramo GRADE
concentra la fascia su A/B molto più del baseline (es. soglie vecchie:
baseline A=245/B=118, grade A=350/B=103 — il grade sposta la fascia dalle
carte C/D/E-ma-più-attese verso le A/B anche quando l'atteso reale
(realizzato) di quelle A/B è più basso in quella giornata specifica).

Griglia M×ordine ruoli (livello 3): scatta raramente a M piccolo (1-3
arene a M=0) e sale con M (fino a ~200-250 a M=5), ma il SEGNO del delta
resta negativo su P_noF per quasi tutta la griglia — la conclusione non
dipende dalla scelta di M/ordine. Con M=5 e ordine MID>FWD>DEF>GK il delta
si avvicina a zero (−400/−800) ma resta negativo: non decisivo, non
inverte il verdetto.

Confronto (B) secondario (ogni ramo decide libero, celle appaiate per
conteggio arene): stesso segno negativo su P_noF (−1300/−2300), coerente
col confronto (A).

File prodotti: `analisi_manager/p21_capitano_grade_backtest.py`,
`analisi_manager/p21_capitano_grade_out.json` (tutti i numeri, griglia
completa), `analisi_manager/p21_capitano_grade_dump.txt` (un manager/gw
completo, 20 arene, pool e capitani dei due rami).
**Non applicare la gerarchia grade al capitano di produzione**
(`pick_captain()` resta con l'atteso, invariato).

**1. Quanto vale G sopra il filtro starting odds? — RIDIMENSIONATA il
09/08 notte, era scritta su una premessa FALSA.**

Come era scritta (sbagliata): "nel backtest il ramo A è completamente
cieco su chi gioca, quindi una fetta del +29.050 potrebbe essere un
vantaggio che in produzione il filtro 0,80 ha già incassato".

Perché è falsa (letto nel codice, `p20_g_odds_arene_setup.py:29-39`,
non nei documenti; obiezione sollevata dall'utente): il **pool di ogni
unità è l'insieme delle carte che quel manager ha REALMENTE SCHIERATO
quella giornata**, in qualunque competizione — non il suo mazzo. Quindi
il pool ha già attraversato il filtro di titolarità di chi lo ha
schierato. A non applica un filtro odds nel proprio codice, ma non può
nemmeno schierare i DNP che G eviterebbe: nel pool in gran parte non ci
sono mai entrati. Le 778 carte F su 7.619 (10,2%) sono verosimilmente
proprio i casi in cui quel filtro ha fallito (dato titolare, poi non
gioca).
In più la popolazione primaria di tutti i test recenti, **P_noF, è già
dichiarata proxy del filtro ≥0,80** (§8bis, blocco tabella fissa): il
test qui proposto è in buona parte già stato fatto senza chiamarlo così.

Cosa resta davvero aperto, ed è molto più stretto: dei 24 manager del
perimetro solo `crowss` schierava a 0,80 per regola dichiarata; degli
altri 23 il criterio di filtro è IGNOTO, quindi il filtro implicito nel
pool esiste ma non è uniforme e non è mai stato misurato quanto sia
stretto. Chi volesse riaprire misuri PRIMA quello (distribuzione di
`starter_odds_bp` da cattura live sulle carte del perimetro, per
manager), non il delta.
**Attenzione se lo si fa**: le odds pre-partita NON sono recuperabili a
ritroso (§8bis, congelate a 0/10000 su partita chiusa). Filtrare con
quelle significherebbe filtrare su "ha giocato" — leakage puro, il ramo
filtrato diventa un oracolo. L'unica fonte lecita è la cattura live in
`analisi_manager/dati/storico_grade_*`, di cui la copertura sul
perimetro arene non è mai stata contata.

**2. Segregare il rischio DNP** (idea dell'utente, 09/08). Oggi lui non
schiera sotto l'80% di starting odds e si mangia tutta la fascia 60-80%.
Alternativa: il bot continua a giocare 80+ nelle arene che contano, e le
carte 70+ ad alto potenziale finiscono **tutte insieme in una sola
Beginner** (100 essenze): un DNP rovina una formazione già dichiarata
precaria invece di una buona. Non riduce i DNP, cambia dove cadono.
Misurabile senza query: le starting odds sono salvate accanto al grade
(`starter_odds_bp` in `analisi_manager/dati/storico_grade_*`); si innesta
su `p20_g_odds_arene_backtest.py`, che già fa il regime allocazione.

**2bis. PORTIERE — `level_score` binario, DA RIVERIFICARE CON G**
(deciso il 09/08). Il valore vero è 35 senza clean sheet e 60 con, mai
intermedio; il modello ne prevede uno continuo (§5.6). **Precisazione
dell'utente, che cambia come va letta la voce**: non è una svista
rimasta lì — fu fatto un lavoro apposta e si decise di **tenere il
valore "sbagliato" perché rendeva meglio**. Quella decisione però è
stata presa **prima di G**. Ora che G è in produzione va riverificata:
il grade porta informazione sulla titolarità, e sul portiere il salto
"non gioca / gioca" è proprio dove il level score morde di più.
Si misura sui game log, quindi **non dipende dall'archivio manager**
messo da parte dalla regola in testata — è uno dei pochi filoni che
quella regola non tocca.

**3. Non-determinismo del generatore — DECLASSATO A SOSPETTO il 09/08,
non è più una cosa da fare.** Il caso concreto non esiste nel repo e le
spiegazioni alternative non sono escluse: vedi §9. Non riaprire senza
due run di fila e il diff degli output.

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

**8. Decisione grade nello scouting** (§8ter) — **SUPERATA il 09/08 sera:
il grade C'È e si vede.** Trovato `nextClassicFixtureProjectedGrade` dentro
`searchPlayers`, gratis, verificato 116/117 contro il bench di produzione
(incluso il sottoinsieme a rischio "fixture consecutive", 8/8). Colonna
Grade mostrata in `scouting_gw.py` per ogni candidato, posseduto o no. Quello
che resta aperto è **solo** come deve PESARE: un voto per-partita su una
decisione d'acquisto pluri-giornata è una scelta di significato, non una
misura — non ancora usato nel punteggio/ordinamento delle sezioni esistenti.

**9. e 10. — ELIMINATE il 09/08 per decisione dell'utente.** La 9
(odds+4ruoli, campione profondo) cade col filone favorito-odds, chiuso
definitivamente. La 10 (buco premi Uncapped rank 1/3) è tema minoritario
e generava confusione: non riaprirla.

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
**A COSA SERVE, chiarito il 09/08 (l'utente non lo sapeva, ed è giusto
che lo chiedesse):** NON serve alla produzione. Il bot prende il grade
fresco della giornata in `discovery_fixture.fetch_grade_live()`, come
l'utente riteneva. Lo storico serviva solo alla RICERCA: costruire la
tabella lettera→punti e le misure sul grade. `raccolta_grade_storico.py`
campiona 150-200 giocatori per ruolo presi dai file manager (NON le carte
dell'utente) e ne scarica 15 partite passate. Dal 09/08, con la regola
"backtest sulle sole giornate dell'utente" (testata), questa voce ha
senso solo se un giorno servisse lo storico delle carte di `crowss`.
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
**CHIUSA il 09/08 dall'utente, che sa come lo lancia** (era: "se il
generatore gira per una giornata non ancora aperta, G e' inerte per
costruzione, z=0 su tutti"). Risposta: il bot gira prima dell'apertura
**ma solo quando odds e grade sono gia' disponibili**, e gira **anche a
giornata iniziata**, perche' le arene non hanno una deadline fissa come
le altre competizioni — per questo esiste `ESCLUDI_LOCKATE` (§8quater.3),
che scarta le carte gia' bloccate in formazioni non piu' modificabili.
**Nessun problema: G non gira mai a vuoto.** Non riaprire.
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

**14. — STORIA, non un verdetto** (riclassificato il 09/08 notte). Questa
sezione e il blocco "tabella fissa" in §8bis si contraddicevano a vicenda;
entrambe poggiano sull'archivio dei 24 manager, che non è più base di
misura. **La domanda z-score contro tabella fissa si rifà da zero sulle
giornate dell'utente, verifica fissata per l'11/08/2026.** Quanto segue
serve solo a sapere cosa è già stato provato e come.

*(storia)* **IL MERITO DEL BACKTEST CHE HA SCELTO LA FORMULA — riesame
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

**MISURATO 09/08 notte (esecutore Sonnet, `analisi_manager/p22_copertura_grade.py`,
nuovo file, riusa senza modificare P20G/GF2/GF1/S21, nessuna query, nessuna
run GitHub).** Controlli C0 IDENTICI al brief (pool 7619, con grade 7381, F
778, unita' allocazione 53, scendono 2). C1 (interruttore spento=identita')
e C5 (A/A) **PASS**, ma solo dopo aver corretto un bug reale nel primo giro:
la prima versione raggruppava (b)/(c) su TUTTO l'archivio appiattito invece
che unita' per unita' (manager/gw), mischiando i pool di giornate diverse
nello stesso gruppo — il ricontrollo contro produzione dava max_diff=21.96
invece di 0. Corretto (gruppo sempre dentro la singola unita', come fa la
produzione), poi max_diff=0.0000000000 su entrambe le popolazioni.

COPERTURA (carte col voto che ricevono uno spostamento diverso da zero,
P_noF, 6603 carte con lettera):
| variante | non-zero | a zero | perche' |
|---|---|---|---|
| produzione (z-score, gruppo lega+ruolo) | 5085 (77%) | 1518 | 712 gruppo_1_lettera, 642 lettere_uguali, 164 z legittimo=0 |
| (a) tabella fissa pura | 6603 (100%) | 0 | — |
| (b) ibrida (z-score + fallback tabella) | 6439 (97,5%) | 164 | solo z legittimo=0 (nessuna esclusione residua) |
| (c) gruppo largo (ruolo, tutte le leghe, stessa unita') | 6483 (98%) | 120 | 48 z=0 legittimo, 35 lettere_uguali, 37 gruppo_1_lettera |

(b) elimina la copertura mancante quasi del tutto (164 residui sono z=0
legittimi, non esclusioni: la carta e' esattamente sulla media del suo
gruppo). (c) migliora ma non chiude (restano gruppi piccoli anche allargando
alla lega intera, dentro la stessa unita' manager/gw).
[CORREZIONE orchestratore, verifica sui grezzi: la riga (b) della tabella
diceva "6602 / 1". Il campo `copertura` del JSON dice **6439 non-zero e
164 a zero** su P_noF (145 su P_ALL). Il testo qui sotto era gia' giusto
(cita 164): sbagliata solo la riga della tabella, ora corretta.]

**DECISIONE DELL'UTENTE, 09/08 notte: NON SI ACCENDE NIENTE.**
(c) scartata (perde in allocazione su P_noF con entrambe le soglie).
(b) NON attivata, nemmeno dietro flag: l'orchestratore l'aveva proposta
sostenendo che "non fa danni", l'utente ha obiettato che senza un
guadagno dimostrato non c'e' motivo di accendere, e ha ragione — fra le
celle misurate di (b) ce n'e' una negativa (allocazione P_noF soglie
nuove, -1950), quindi il segno resta IGNOTO, non buono. L'unico argomento
a favore era "G e' stato acceso con prove altrettanto deboli": e' un
argomento sul passato, non una prova. La produzione resta com'e'.
STRADA INDICATA DALL'UTENTE: misurare il grade sulle SUE giornate reali
man mano che arrivano, invece di decidere su 6 giornate che non
distinguono niente.

ESSENZE NETTE, delta = variante−produzione, bootstrap IC95 cluster-manager,
criterio del brief (delta>0 e IC95>0 su ENTRAMBI i set soglie, STESSO
regime):

P_noF (primaria), astensione: (b) vecchie +2550 IC95[-250;+6600], nuove
+450 IC95[-1900;+3200] — non passa. (c) vecchie +1300 IC95[-800;+3800],
nuove -1000 IC95[-4600;+2900] — non passa.
P_noF, allocazione: (b) vecchie +1200 IC95[-20000;+21850], nuove -1950
IC95[-20000;+15450] — non passa. (c) vecchie -13400 IC95[-30400;+2300],
nuove -8900 IC95[-23800;+3750] — non passa.
P_ALL (secondaria, limite superiore per leakage F), astensione: entrambe
non passano (IC95 sempre a cavallo di zero). Allocazione: (b) vecchie
+15950 IC95[+300;+32550] passa da sola, ma nuove +12650 IC95[-4750;+29600]
no — criterio pieno non soddisfatto (serve ENTRAMBI i set soglie).

**VERDETTO: NE' (b) NE' (c) passa il criterio pieno, su nessuna
popolazione, in nessun regime.** Nessuna e' peggio della produzione in modo
sistematico (i segni sono quasi tutti positivi per (b), misti per (c)), ma
gli intervalli sono troppo larghi rispetto al campione (n=111-154 astensione,
460-572 allocazione) per decidere. La copertura si allarga (63/86 -> quasi
100% dei casi non gia' coperti da produzione) ma **non si dimostra che
paghi**: e' un'informazione, non un fallimento (come da §2 del brief).
Placebo (produzione G contro nessun grade A, riusato da
`p20_g_odds_arene_backtest_out.json`, non ricalcolato): G batte A su
entrambi i regimi ed entrambi i set soglie — l'archivio distingue qualcosa,
il problema e' la potenza statistica per differenziare fra formule di G,
non l'assenza di segnale.

File: `analisi_manager/p22_copertura_grade.py`,
`analisi_manager/p22_copertura_grade_out.json` (tutti i numeri, stratificati
per cap_type),
`analisi_manager/p22_copertura_grade_dump.txt` (un manager/gw, 78 carte,
pool completo con PROD/B/C affiancati e la ragione dello zero, piu' un
gruppo di esempio a z=0 in produzione).
**Nessuna modifica alla produzione. Da decidere: (b) resta la piu' pulita
concettualmente (tocca solo i casi oggi buttati) ma serve piu' campione
(altre GW) prima di poterla applicare — non e' una decisione per stanotte.**

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
