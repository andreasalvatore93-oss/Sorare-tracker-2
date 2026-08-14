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

Ultimo aggiornamento: **sessione 14/08/2026 mattina (Roma, CEST)**. Tre cose
in produzione, tutte verificate sul banco e con A/A:
- **correttivo cambio campionato ACCESO** (§8terdecies riscritta): chi arriva
  da un'altra lega non è più previsto come se giocasse ancora là. Supera il
  tentativo PRIOR_LEGA del 13/08 e ne rettifica il −14,49.
- **bug del correttivo GK** trovato e chiuso (§10bis in cima): dal 13/08 sera
  l'accensione del voto lo stava cancellando in silenzio. Una sola run di
  produzione colpita.
- **carte già schierate** escluse dal pool anche se la formazione è ancora
  modificabile, e `pool_gw.json` con timbro di run contro il riuso stantio.
Handoff di sessione: `docs/handoff/HANDOFF_PIPELINE_LOCKATE_GK_2026-08-14.txt`.

Aggiornamento precedente: **sessione 13/08/2026 notte (Roma, CEST)**,
allineamento fatto dal nuovo orchestratore verificando il CODICE, non i
documenti. La giornata del 13/08 ha prodotto tre cose:
- **livello dei campionati** misurato (§8terdecies): le leghe NON sono uguali,
  tabella pronta, interruttore **SPENTO** per decisione dell'utente;
- **filone intralega CHIUSO** in essenze (§8quaterdecies) e **half-life
  rimisurato, nessun cambio** (§8quindecies), anche col grade acceso;
- **quattro difetti del BANCO DI MISURA** trovati e corretti: e' la cosa piu'
  importante della giornata, il metro giudicava un modello che non esiste
  (§8quaterdecies in fondo, §8quindecies bug GK, e la voce D3-banco qui sotto).
In produzione e' cambiato UN SOLO pezzo del modello in tutta la giornata: il
badge "nuovo campionato" (cosmetico). Handoff della giornata:
`docs/handoff/HANDOFF_INTRALEGA_HALFLIFE_2026-08-13.txt` e
`docs/handoff/PASSAGGIO_ORCHESTRATORE_2026-08-13_SERA.txt` (filoni aperti).

Aggiornamento precedente: **sessione 12/08/2026 sera (Roma, CEST)** — giornata
di test end-to-end su GitHub Actions (GW4/GW5) che ha fatto emergere e
chiuso 4 bug reali di produzione + aggiunto una feature nuova + un tipo
formazione nuovo. Dettaglio completo: §8duodecies. **429 GW5 CHIUSO**
(fix P5+P6 verificato su run vera). Dei 3 problemi aperti allora
(§8duodecies-bis) **ne restano 1**: D1 (`_budget_essenze`) e D2 (notifica
Telegram bugiarda) sono chiusi e verificati nel codice il 13/08 notte;
**resta APERTO D3** — 92% del predict sprecato quando si chiede solo
Champions.

Sessione 12/08/2026 notte: **APIKEY Sorare arrivata e attivata.** Header
HTTP `APIKEY` (separato dal cookie, si aggiunge e non sostituisce) su tutte
le query GraphQL — alza il tetto sull'account da 60 a 200-600 query/min e la
complessita' da 500 a 30000, verificato con una query reale (200 OK). Fonte
unica `formazione_mls/predict/*.py`, propagato a tutte le 53 leghe con
`propaga_modello.py`; aggiunto anche a `ricostruisci_manager.py` (quindi
`graphql_batch.py`/`estrai_archivio_manager.py`), `best_five.py`,
`scanners/bot_profit.py` (quindi `scouting_gw.py`/`discovery_fixture.py`
che lo riusano), e come secret `SORARE_APIKEY` in 34 workflow GitHub.
Committato e pushato (main). **NON coperto:** gli script per-lega in
`formazione_<lega>/discovery/` (pattern duplicato come i predict ma senza
propagazione automatica) — filone lasciato a parte, da affidare a Opus.
Nessuna run reale ancora lanciata per misurare l'effetto su tempi/429.

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
`half_life` **rimisurato il 13/08/2026** (tutti i ruoli, 11 valori da 3 a 60,
avversario acceso e poi grade acceso): i quattro valori qui sopra reggono,
nessun cambio — §8quindecies.

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
- **Confronto INTRALEGA fra reparti avversari** (attacco di A contro difesa di
  B normalizzati dentro la stessa lega): **CHIUSO il 13/08**, dettaglio in
  §8quaterdecies. L'idea di normalizzare per lega perde su 4 celle su 4 contro
  la normalizzazione mondiale che gira oggi. La variante che sembrava
  sopravvivere (DEF + gol FATTI dall'avversario) è stata bocciata **in
  essenze** sul banco vero: −2.619 con IC95 [−10.296; +5.217] e il braccio di
  controllo di segno opposto. Flag e `k` restano nel codice, spenti.
  **Resta non misurato** un asse diverso, che l'utente aveva intuito: la forza
  della **propria squadra nuova** (Ernst al Feyenoord, Simsir al Trabzonspor),
  cosa distinta dal livello della lega — vedi §10bis.
- **`HALF_LIFE_GAMES` "stantio"**: rimisurato il 13/08 su tutti i ruoli, 11
  valori da 3 a 60, con avversario acceso **e** in un secondo giro con il
  grade acceso. **Nessun cambio**: la curva è piatta dove conta (DEF, MID) e i
  metri si contraddicono dove non lo è (GK, FWD). §8quindecies. Non ripetere
  questa misura senza un motivo nuovo.
- **Scomposizione degli all-around per categoria**: nessuna forma soddisfa
  MAE + correlazione + lift insieme, su nessun ruolo (39.594 partite, 26
  leghe, bootstrap appaiato). La compressione che l'aveva motivata riguarda
  solo il `level_score` (scala a gradini), non gli all-around.
- **`fattore_forza_avversario`**: era calcolato e **mai usato**. Rimosso il
  05/08. Il condizionamento sull'avversario che agisce davvero è
  `opponent_lambda_mult` + Stadio D.
- **Bonus additivi vs moltiplicativi**: la formula additiva è verificata al
  centesimo (§3).

### 5.3 Capitano — `pick_captain()` NON si tocca, ma il motivo è cambiato (riscritto 13/08/2026)

**RIAPERTO E RIMISURATO IL 13/08**, su obiezione dell'utente: *"il capitano
col grade l'abbiamo provato, ma su un grade diverso da quello di ora"*.
Obiezione legittima — il test del 12/08 girava sul voto vecchio, quello che
si spegneva sul 51%+ delle righe. Rifatto su **12.677 formazioni reali**,
stesse 5 carte, cambia solo chi porta la fascia (in arena il capitano vale
+20% del suo punteggio REALE, quindi il confronto è esattamente
0,2 × punteggio del capitano scelto — nessun rumore da altre fonti).
Script: `analisi_manager/p64_capitano_grade_nuovo.py`.

| regola | bonus per arena |
|---|---|
| CASO (a sorte fra le 5) | 9,990 |
| SENZA VOTO (atteso ignorando il grade) | 10,656 |
| **PRODUZIONE** (atteso più alto, grade già dentro, margine GK 6,7) | **10,938** |
| UTENTE (grade più alto → atteso → ruolo MID/FWD/DEF) | 10,955 |
| ORACOLO (il migliore col senno di poi) | 14,809 |

| confronto | delta | IC95 | positivo |
|---|---|---|---|
| **UTENTE − PRODUZIONE** | +218,8 | **[−1.236; +1.554]** | 63,7% |
| **PRODUZIONE − SENZA VOTO** | **+3.568** | **[+1.883; +5.986]** | 100% |
| PRODUZIONE − CASO | +12.007 | [+6.756; +19.447] | 100% |

**DUE CONCLUSIONI, e la seconda è nuova.**

1. **La regola esplicita "prima il grade" non aggiunge niente**: +0,017 punti
   per arena, intervallo largamente a cavallo dello zero. E stavolta **non è
   mancanza di potenza**: le due regole scelgono un capitano DIVERSO nel 44%
   dei casi (7.157 concordi su 12.677), quindi il test non è nullo per
   costruzione — semplicemente non c'è differenza.
2. **Il grade nuovo AIUTA il capitano**, e questo ribalta il verdetto del
   12/08 ("grade peggiora, t=−1,93"): +3.568 con l'intervallo che esclude lo
   zero. Il punto è che il beneficio arriva **da solo**, perché il voto è già
   dentro `atteso` (GRADE_ENABLED sovrascrive `atteso` con
   `atteso_combinato`). Metterlo *davanti* all'atteso, come criterio
   separato, non aggiunge nulla — usarlo dentro l'atteso lo prende già tutto.

**E il tetto si è alzato.** La versione precedente di questa sezione diceva
che il capitano cattura +0,69 punti/arena sul caso, il **15%** del massimo
possibile (+4,59), e che quel 15% corrispondeva a una correlazione r≈0,156 —
la stessa che il modello ha sui ruoli di movimento. Con il grade nuovo il
margine catturato è **+0,947 su 4,819, cioè il 20%**. L'argomento del tetto
resta valido nella forma ("il capitano prende quello che la vista del
modello permette"), ma la vista è migliorata e il tetto si è spostato con
lei: **non è una costante di natura**. Chi migliora la previsione migliora
il capitano gratis, senza toccare `pick_captain()`.

**LA VARIANZA — PROVATA E CHIUSA lo stesso giorno (13/08), non riproporla.**
Era l'ultima idea rimasta in piedi: il capitano *moltiplica*, quindi in teoria
vorrebbe la coda alta a destra e non la media più alta. Testata su tutte le
12.677 formazioni con `atteso + k × sd_storica`, dove `sd` è la dispersione
dei punteggi grezzi del giocatore nelle partite precedenti al primo calcio
d'inizio (finestra 365 giorni, minimo 4 partite, solo partite giocate — le
assenze non sono volatilità di rendimento). Script:
`analisi_manager/p65_capitano_varianza.py`.

| k | bonus per arena | delta vs produzione | IC95 |
|---|---|---|---|
| −0,50 | 10,907 | −385 | [−868; +58] |
| −0,25 | 10,928 | −127 | [−505; +229] |
| **0 (produzione)** | **10,938** | — | — |
| +0,25 | 10,910 | −348 | [−692; **−8**] |
| +0,50 | 10,890 | −604 | [−1.156; **−84**] |
| +1,00 | 10,843 | −1.197 | [−2.033; **−446**] |
| solo dispersione | 10,313 | −7.918 | [−12.840; −4.430] |

**La curva ha il massimo esattamente su k=0 ed è monotona in entrambe le
direzioni**; i k positivi sono peggio con l'intervallo che esclude lo zero —
non "non dimostrati", proprio peggio. Il test non è nullo per costruzione: la
dispersione si calcola sul **100%** delle carte (mediana 17,9 punti) e il
criterio cambia capitano in 984-7.790 formazioni secondo k.

Due cose da portarsi via, la seconda vale oltre il capitano:
1. **L'aritmetica si conferma sul campo.** Il bonus è lineare (+20% del
   punteggio realizzato), quindi massimizzare la media massimizza il bonus
   atteso e la varianza non deve entrare. Lo si sapeva a tavolino; ora si
   vede anche nei dati.
2. **`atteso` non ha un errore sistematico legato alla volatilità.** Se lo
   avesse — se cioè il modello comprimesse i giocatori con la coda lunga —
   un k diverso da zero avrebbe vinto. Non vince nessuno: piccola conferma
   che la calibrazione regge anche sulle code, non solo al centro.

L'unica strada teoricamente ancora aperta richiede un obiettivo **non
lineare** (P(podio) invece dei punti attesi), e per calcolarlo servirebbero
i punteggi degli altri 9 partecipanti, che l'archivio non ha di proposito
(§5.9: si usano le soglie calibrate). Prima di riaprire da lì, leggere
§5.5: massimizzare il PREMIO atteso è già risultato identico a massimizzare
i PUNTI attesi, 5.768 confronti su 5.768 concordi.

**Cosa NON riaprire**: criteri che riordinano lo stesso atteso (grade
davanti, favorita/sfavorita — t=−0,62 su confronto equo, quote con copertura
insufficiente) e la varianza in qualunque forma lineare.

Storia: le "otto ipotesi chiuse" originarie giravano su
`dati_globali/manager_*.json` (bug D6, §5.8) e sono nulle; il giro del 12/08
sull'archivio pulito (1.145 arene) è superato da questo, che ne usa 12.677.
Dettaglio del giro vecchio in
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

**Secondo disallineamento, trovato e chiuso il 13/08/2026 — l'ORDINE, non
il correttivo.** La colonna Atteso era allineata dall'11/08, la colonna
**A+G dei soli portieri** no: il generatore calcola l'effetto del grade
PRIMA del correttivo (`load_league_role_data` chiama `_apply_grade_group`
e solo dopo `_apply_gk_att_avv`, che sovrascrive `atteso` senza ritoccare
`atteso_combinato`), lo scouting lo calcolava DOPO, su attesi gia'
corretti. Effetto: il grade si scala sulla dispersione del gruppo, e
sommare prima il correttivo la gonfia — l'atteso GK e' quasi piatto
(sd 0,97 sulle 1.932 righe citate in `build_formazione_globale`) mentre il
correttivo ha **sd 1,73, range -6,7/+6,0** (misurato sulle 741 squadre di
`generatore_formazioni/dati/gk_attacco_avversario.json`), quindi il voto
pesava circa il doppio nello scouting rispetto a come schiera il
generatore. Fix in `_atteso_combinato_per_gruppo`: il correttivo si scala
prima di misurare il gruppo e si risomma alla fine. Verificato in locale
su un gruppo GK sintetico coi numeri veri della tabella (avversari dal
piu' debole al piu' forte, attesi grezzi piatti): scarti fino a -5,2/+5,2
punti di A+G sui casi estremi; **non-GK identici bit per bit** e
**flag `GK_ATT_AVV_ENABLED` spento identico bit per bit** (nessuna
regressione). Non tocca la colonna Atteso, ne' l'ordinamento dei non-GK.

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

**ESITO DELLA RI-MISURA — FATTA IL 13/08/2026, senza aspettare il 25.**
La data non aveva giustificazione statistica (tre giornate scelte perché
successive alla pre-registrazione, ~87 coppie: non avrebbero deciso nulla).
Si è invece misurato sull'archivio allargato all'indietro, dove le giornate
di febbraio-marzo e i 36 manager nuovi **non sono mai stati usati per
scegliere la formula fra le 5 candidate**. Script:
`analisi_manager/p63_gk_att_avv_fuoricampo.py` (acceso contro spento sulle
stesse righe, braccio G, bootstrap sui manager).

| campione | delta | IC95 | per unità | positivo |
|---|---|---|---|---|
| tutto l'archivio | +12.713 | [+152; +26.420] | +9,5 | 97,6% |
| **solo giornate nuove** | +2.238 | [−4.353; +9.074] | +4,9 | 74,9% |
| solo manager nuovi | +5.920 | [−3.791; +16.367] | +9,2 | 87,1% |
| nuove **o** manager nuovi | +7.350 | [−2.785; +18.810] | +8,5 | 91,6% |

**DECISIONE: resta ACCESO**, applicando alla lettera la regola scritta prima
("se il segno esce NEGATIVO si rispegne"): non è negativo in nessuno dei
quattro tagli. Ma va letto per quello che è — **positivo ovunque, mai
dimostrato**: l'atteso dichiarato era ~+15 per unità, il fuori campione puro
dà +4,9, e nessun intervallo fuori campione esclude lo zero. Per arrivarci
servirebbe un effetto quasi doppio o ~230 manager invece di 65.
L'interruttore è collegato (cambia le carte in 683 unità su 1.338;
aggiustamento medio +0,02, range −6,73/+5,96, quindi centrato).
Chi lo rispegnesse non starebbe contraddicendo i dati, e chi lo tiene acceso
nemmeno: è una forzatura benevola su un effetto piccolo.

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

**AGGIUNTA 13/08/2026 SERA — la soglia 0,10 è CONFERMATA su 12.677 arene
vere, ma con una tensione da riconciliare.** Misurate le arene realmente
giocate nell'archivio, raggruppate per guadagno ATTESO (formula di
produzione, voto acceso) e confrontate col netto REALIZZATO
(`analisi_manager/p61_fasce_marginali.py`):

| fascia di guadagno atteso | arene | netto medio reale | IC95 | a premio |
|---|---|---|---|---|
| sotto pareggio (forte) | 1.211 | −93,9 | [−109; −77] | 19,2% |
| sotto pareggio (poco) | 3.900 | −23,6 | [−36; −11] | 26,5% |
| **MARGINALE (0-10%)** | 2.094 | **−14,6** | [−29; 0] | 28,7% |
| schiera (10-25%) | 2.688 | +26,9 | [+12; +43] | 33,6% |
| schiera (25-50%) | 2.075 | +65,2 | [+45; +86] | 38,5% |
| schiera (50-100%) | 661 | +237,8 | [+172; +306] | 43,6% |
| schiera (oltre 100%) | 48 | +986,5 | [+522; +1.542] | 60,4% |

Due letture, entrambe utili:
1. **Il confine fra perdere e guadagnare cade ESATTAMENTE fra la fascia
   0-10% e la 10-25%**, cioè su `QUOTA_MINIMA = 0,10`. Il parametro è
   confermato empiricamente, non più solo per taratura.
2. **La percentuale a premio sale in modo monotono** col guadagno atteso,
   dal 19,2% al 60,4%: l'ordinamento del modello regge, e la prima arena
   della lista efficiente è davvero la migliore. (Era un'intuizione
   dell'utente da un vecchio test, ora verificata su tutto l'archivio.)

**LA TENSIONE APPARENTE — SCIOLTA la stessa sera, e la risposta ribalta
l'intuizione.** Sembrava che le due misure si contraddicessero: qui sopra
"entrare CONVIENE" (+82,8 e +19,6 essenze/formazione), e la fascia 0-10% che
rende **−14,6**. Rimisurato sull'archivio intero facendo scegliere al
MODELLO quante arene giocare al variare del margine d'ingresso
(`analisi_manager/p59_margine_ingresso.py --margini "0,0.05,0.10,0.15,0.20"`,
1.338 unità, 61 manager, braccio di produzione):

| margine | arene giocate | netto | vs margine 0 | IC95 |
|---|---|---|---|---|
| **0,00 (produzione)** | 5.521 | **+588.127** | — | — |
| 0,05 | 5.209 | +576.483 | −11.644 | [−16.262; −6.957] |
| 0,10 | 4.827 | +566.464 | −21.663 | [−29.604; −14.302] |
| 0,15 | 3.706 | +492.317 | −95.810 | [−127.399; −67.465] |
| 0,20 | 2.957 | +448.203 | −139.924 | [−181.528; −100.797] |

**Ogni margine perde, in modo monotono, con l'intervallo che esclude lo
zero. Il default di produzione (pareggio secco) è il migliore: `margine_quota`
resta 0.0 e `QUOTA_MINIMA` non si tocca.**

**Perché le due misure non erano in contraddizione**: guardano popolazioni
diverse. p61 guarda le arene che i MANAGER hanno giocato e che cadevano nella
fascia 0-10% di guadagno atteso — scelte umane, spesso discutibili, che infatti
rendono −14,6. p59 toglie invece le arene che il MODELLO mette per ULTIME
nella sua allocazione, cioè la coda di una selezione già ottimizzata: quelle
valgono **+31,2 essenze ciascuna** (694 arene in meno fra margine 0 e 0,10,
21.663 essenze perse). Le marginali del modello non sono le marginali
dell'uomo.

**Conseguenza pratica, controintuitiva ma coerente**: saltare a mano le arene
che il generatore mette in fondo alla lista **costa**. Combacia con il dato
sulle sole formazioni di crowss (§5.3 e Binario 1): il braccio che salta
perdeva −3.350 contro il manager che entrava sempre. L'etichetta "MARGINALE —
meglio All Stars da 7 o Under 23" descrive bene la fascia in astratto, ma NON
è un consiglio a saltare quando è il generatore ad aver messo lì quell'arena.

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

## 8bis-bis. Gruppo del grade esteso alla giornata — **ACCESO IN PRODUZIONE il 13/08/2026**

**VERDETTO: validato fuori campione e acceso.** `GRADE_GROUP_STORICA_ENABLED`
è **'1' di default** in `build_formazione_globale.py` e nell'input del
workflow, e `scouting_gw.py` prende lo stesso ramo. Commit `e42ee69db3`.

**Non si è aspettato il 25/08**, e il motivo è che quella data non aveva
nessuna giustificazione statistica: erano le tre giornate successive a
quando fu scritta la pre-registrazione, e questa stessa sezione ammetteva
"n troppo piccolo su 3 GW". Invece di aspettare in avanti si è allargato
l'archivio **all'indietro** — le giornate passate mai usate per tarare la
ricetta valgono come prova quanto quelle future, e c'erano già: da 29 a 65
manager, da 25 a 44 giornate, da 3.247 a **13.860 formazioni**.

**I numeri che hanno deciso** (Binario 2, 1.338 unità manager-giornata, 65
manager, righello contemporaneo — cioè la tabella ricostruita sulle giornate
testate, non quella di agosto):

| confronto | delta | IC95 | cambia in |
|---|---|---|---|
| G-variabile − A | +39.699 | [+19.063; +64.840] | 815/1338 |
| G-fisso − A | +59.972 | [+35.965; +88.324] | 916/1338 |
| **G-fisso − G-variabile** | **+20.273** | **[+5.329; +37.274]** | 929/1338 |

Col **margine d'ingresso al 10%** (come gioca davvero l'utente): +21.736
[+5.555; +40.137]. Con la tabella congelata del 12/08 il delta saliva a
+30.296: quel righello, costruito su kickoff 28 lug–13 ago, **gonfia di circa
un terzo** quando si testa all'indietro. Il numero buono è quello
contemporaneo — ed è anche quello che gira in produzione, dove le tabelle si
rigenerano a ogni run. Due giri dello stesso test danno numeri identici cifra
per cifra.

**La catena è stata verificata prima di accendere** (regola CLAUDE.md):
l'atteso medio per carta è **identico al centesimo** nei tre bracci e lo
scostamento per formazione è **−0,009 punti** su soglie da ~260, quindi
`PAREGGIO_ARENA`/`GUADAGNO_PER_PUNTO` e i consigli dello scouting restano
tarati (`analisi_manager/p62_soglie_dopo_gfisso.py`). Cambia solo la
dispersione, che è il punto: G-fisso ha sd **minore** di G-variabile (MID
4,98 contro 5,54) — stessa informazione, meno rumorosa, perché non dipende
più da gruppetti da due carte.

**Tre cose da sapere, scritte per chi legge dopo:**
1. **Il Binario 1 non conferma con l'intervallo**: stesso segno (+13.450) ma
   IC95 [−11.950; +44.250], include lo zero. Non è una smentita, è meno
   potenza — lì l'unica leva è entrare/saltare e il voto cambia la decisione
   in 639 unità contro 929.
2. **Il pool esclude le carte a 0/DNP**, cioè è definito guardando l'esito.
   Vale identico per tutti i bracci, ma sporca i valori assoluti.
3. **Lo scouting NON si allineava da solo**: `_atteso_combinato_per_gruppo`
   riscriveva la formula in casa col gruppo nativo. Corretto nello stesso
   giro; e il workflow ora **committa le due tabelle** che rigenera,
   altrimenti il generatore avrebbe avuto un righello fresco e lo scouting
   sarebbe rimasto su quello del 12/08.

**CONFERMA SUL POOL VERO (run di scouting del 13/08 sera, GW5, riuso
previsioni spento).** Confrontati i due report committati, prima e dopo
l'accensione, sui 589 giocatori presenti in entrambi:
- **Atteso**: cambia in 74 righe su 589, scarto medio 0,13 — è il rumore
  delle previsioni rifatte, non il flag.
- **A+G**: cambia in **589 righe su 589**. Spostamento medio −0,26, mediana
  −0,04 (**centrato**, come deve essere), range da −9,61 a +5,07.
- **Dispersione dell'effetto del voto: da 3,19 a 1,68, quasi dimezzata** —
  esattamente ciò che p62 prevedeva sul backtest.
Il caso che spiega tutto: `fabian-wilfinger`, atteso 53,0 identico prima e
dopo, A+G da **66,33 a 56,72**. Prima il voto gli aggiungeva +13,3 punti su
una previsione di 53 — un quarto del suo valore deciso da una lettera,
perché il gruppetto nativo aveva due o tre carte e lo z-score esplodeva. Ora
+3,7. Gli altri cinque spostamenti maggiori sono tutti in giù di 8-9 punti,
tutti con l'atteso invariato: non è il modello che cambia idea sui
giocatori, è il voto che smette di gridare.

### DUE TERZI "CHI", UN TERZO "QUANDO" — il placebo per-giocatore (13/08/2026, voce 6b)

**La domanda, mai posta prima.** Tutti i placebo fatti su G rimescolano il
voto **fra giocatori** e rispondono a "il voto porta informazione?" (sì,
p≤0,048). Questo lo rimescola **fra le giornate dello STESSO giocatore**:
ognuno si tiene i suoi voti, cambia solo su quale giornata cadono. Risponde
a "il voto dice *chi* è forte, o *quando* andrà bene?".
Script: `analisi_manager/p67_placebo_per_giocatore.py` (8 permutazioni,
1.338 unità, 30.112 coppie giocatore-giornata tutte col voto, 4.076
giocatori con almeno 2 giornate).

| | netto | guadagno sul braccio senza voto |
|---|---|---|
| A (senza voto) | +551.002 | — |
| **G, voti veri** | **+588.127** | **+37.124** |
| placebo, mediana di 8 | +575.114 | **+24.111 = 65% del vero** |

Le 8 permutazioni danno dal 47% all'86%, e **nessuna raggiunge il vero**.

**LETTURA: il voto è per due terzi "questo giocatore è forte" e per un terzo
"questa partita andrà bene".** Entrambe le componenti sono reali — la
per-partita perché nessun placebo arriva al vero, la per-giocatore perché
anche coi voti mescolati sopravvivono due terzi del guadagno.

**Conseguenze, in ordine di importanza:**
1. **Il voto NON è una pagella statica del giocatore**: un terzo del suo
   valore è legato alla singola giornata. Sostituirlo con un punteggio di
   qualità fisso per giocatore perderebbe quel terzo.
2. **I due terzi per-giocatore sono una notizia sul NOSTRO modello, non sul
   voto.** Se il grade guadagna +24.000 essenze limitandosi a dire "questo
   giocatore è più forte di quell'altro", allora il nostro storico **non
   cattura del tutto la qualità dei giocatori**. È il margine più grosso
   individuato in questa sessione, e non dipende da Sorare: dipende da
   quanto bene prevediamo. Chi cerca dove lavorare, lavori lì.
3. **Non decide la voce 14** (tabella fissa per lettera): quella riguarda la
   SCALA (una lettera vale X punti fissi contro uno z-score dentro il
   gruppo), che è una domanda diversa da "chi contro quando". Detto qui
   perché in sessione era stata annunciata come decisiva, e non lo è.

### DOVE ci batte, e la cura che NON funziona (14/08/2026, p68 + p69)

**DOVE.** Il voto medio di un giocatore (componente "chi", calcolata
leave-one-out sulle sue ALTRE giornate) correla col nostro residuo
(realizzato − atteso senza voto) a **+0,078** [+0,067; +0,090] su 29.129
osservazioni deduplicate. Ma non uniformemente:

| partite nell'anno prima | n | corr |
|---|---|---|
| 5-10 | 382 | **+0,181** |
| 10-20 | 2.037 | **+0,134** |
| 20-35 | 13.884 | +0,067 |
| 35+ | 12.782 | +0,076 |

| ruolo | corr | half_life |
|---|---|---|
| FWD | +0,123 | 6 |
| GK | +0,113 | 6 |
| MID | +0,088 | 25 |
| DEF | +0,079 | 30 |

Il voto ci batte **il doppio sui poco osservati**, e di più proprio su FWD e
GK — i due ruoli in cui teniamo la memoria corta. Due tagli diversi che
indicano la stessa cosa: **il problema è dove il campione efficace è
piccolo**. Script: `analisi_manager/p68_dove_sbagliamo_il_giocatore.py`.

**LA CURA OVVIA È STATA PROVATA E NON FUNZIONA.** Ipotesi: manca uno
shrinkage, cioè tirare la stima verso un livello di riferimento (media del
ruolo in quella lega) tanto più forte quanto meno il giocatore è osservato —
`stima = ancora + w·(atteso − ancora)`, `w = n/(n+k)`. Provata su 30.112
osservazioni, `k` da 0 a 50 (`analisi_manager/p69_shrinkage_prova.py`):

| k | MAE | corr | lift |
|---|---|---|---|
| **0 (produzione)** | **14,4610** | 0,1855 | 6,582 |
| 5 | 14,4680 | 0,1883 | 6,610 |
| 10 | 14,4779 | 0,1902 | 6,804 |
| 20 | 14,4987 | 0,1923 | 6,445 |
| 50 | 14,5447 | 0,1911 | 6,262 |

**Il MAE peggiora sempre, monotonamente**, e peggiora **anche nella fascia
0-10 partite** (15,167 → 15,252 con k=5 → 15,341 con k=20), cioè proprio dove
doveva aiutare. I tre indicatori non si muovono mai insieme: non si applica.

**PERCHÉ non funziona, ed è il pezzo da ricordare**: il modello **lo shrinkage
lo fa già**. La calibrazione applica `reale ≈ a + b·atteso` con **b < 1** su
ogni ruolo (DEF 0,831, FWD 0,789, MID 0,740, GK **0,264** —
`build_formazione_globale.py`, `CALIB_PER_RUOLO`), e un coefficiente sotto 1
*è* una contrazione verso il livello medio del ruolo. Aggiungerne dell'altro
sopra significa stringere due volte. **Non riproporre lo shrinkage come cura
in nessuna forma senza prima tenere conto di `CALIB_PER_RUOLO`.**

**COSA RESTA IN PIEDI.** La diagnosi (il voto ci batte di più sui poco
osservati) è reale e misurata; la spiegazione "ci fidiamo troppo di poche
partite" è **falsa**, perché quella correzione c'è già. Quindi su quei
giocatori il voto usa un'informazione che noi **non guardiamo affatto** —
non è una questione di quanto pesiamo lo storico. La domanda aperta, che è
di idee e non di misure: *cosa sa Sorare di un giocatore poco osservato, che
non sta nei suoi punteggi passati?*

### LA SECONDA CURA — la finestra storica — PROVATA E BOCCIATA (14/08, p70-p72)

Seconda spiegazione ovvia: che quei giocatori siano "poco osservati" **solo
perché li tagliamo noi**. `MAX_HISTORY_DAYS = 365`
(`backtest_arene_previsioni.py:38`, e uguale nei quattro predict), mentre la
cache contiene storico ben più profondo. Il taglio è in GIORNI ma
l'informazione si accumula in PARTITE: 365 giorni valgono ~40 partite per un
titolare e **9** per una riserva — largo per chi non ne ha bisogno, stretto
per chi sì. (Osservazione dell'utente, ed è quella giusta.)

**Quanto stavamo buttando** (misurato sul mazzo di crowss, 719 giocatori):
369 hanno la finestra NON piena (meno di `WINDOW_SIZE`=30 partite
nell'ultimo anno). Di questi **265 hanno i dati GIÀ IN CACHE** — 1.677
partite piene, +6,3 a giocatore, scartate solo per età (es. adam-stejskal 29
nell'ultimo anno contro 94 in cache; manolis-saliakas 11 contro 61). Gli
altri 104 hanno la cache davvero sottile.

**Quanto ha Sorare davvero** (verificato su Prévot con la paginazione, che
FUNZIONA — `allPlayerGameScores(first: 50, after: endCursor)`, 3 pagine):
149 partite dal 2018, di cui **45 piene**, contro le **11** che abbiamo in
cache. Quindi la nostra cache è corta perché scarichiamo una pagina sola,
non perché Sorare non abbia i dati. Costo per approfondire i 104 sottili:
312 query, mezzo minuto.

**GLI ESITI, in ordine:**
1. `p70` — la media oltre l'anno spiega il residuo? Sì ma pochissimo: corr
   **+0,024** [+0,010; +0,038] complessiva, FWD +0,076, GK +0,008. E **non**
   concentrata sui poco osservati, contro l'ipotesi.
2. `p71` — finestra a 365 / 730 / 1095 giorni sui tre indicatori:

| giorni | MAE | corr | lift |
|---|---|---|---|
| 365 | 14,4610 | 0,1855 | 6,582 |
| 730 | 14,4500 | 0,1863 | 6,693 |
| 1095 | 14,4492 | 0,1860 | 6,707 |

   Tutti e tre migliorano, ma **solo il MAE supera il proprio rumore**
   (−0,011 contro un tremolio documentato di 0,003): la correlazione guadagna
   0,0008, che *è* il tremolio, e il lift 0,111 contro un rumore misurato di
   ±1,6. Uno su tre.
3. `p72` — **il metro che decide, le essenze**: 730 contro 365 giorni,
   **+2.594** essenze, IC95 **[−6.978; +12.852]**, positivo nel 70,3%,
   **+1,9 per unità manager-giornata**. Cambia le scelte in 615 unità su
   1.338, quindi il test non è nullo: semplicemente **non decide**.

**VERDETTO: `MAX_HISTORY_DAYS` resta 365.** Non perché allungare faccia
danno, ma perché non fa niente di misurabile, e in dubbio la produzione non
si tocca. Chi volesse riaprire, sappia che la modifica è **gratis** (i dati
sono già su disco) e che quindi la domanda non è "quanto costa" ma "vale
+1,9 essenze a giornata".

**IL PUNTO DA PORTARSI VIA.** Le due spiegazioni ovvie del buco sui poco
osservati — *ci fidiamo troppo di poche partite* e *tagliamo troppo lo
storico* — sono state provate ed **entrambe bocciate**, con numeri. La
diagnosi resta in piedi e senza cura nota. Non riproporle: sono già costate
una notte, e il valore di questa sezione è impedire di ripagarla.

Handoff completo della sessione: `docs/handoff/HANDOFF_GRADE_ACCESO_2026-08-13.txt`.

### Storia: com'era prima del 13/08 (compresso)

Il voto entra come z-score dentro il gruppo (lega, ruolo, giornata); con meno
di 2 membri si spegne da solo, e succedeva sul 51%+ delle righe di
produzione. La variante prende dispersione e scala da due tabelle storiche.
Misurata il 12/08 a +10.102 [+1.494; +18.995] su 360 GW-manager — numero poi
riconosciuto sovrastimato (migliore di ~12 varianti sullo stesso campione) e
infatti sceso a +20.273 su un campione quasi quadruplo e indipendente. Il
placebo di allora resta valido: voto rimescolato, 20 permutazioni, tutte
negative, p≤0,048.

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
aggiorna_grade_scala_produzione.py` (zero query di rete). **CORREZIONE
13/08/2026: NON gira più sempre.** Lo step è condizionato a
`grade_group_storica == '1'` (`formazione_giornata.yml:770`): costava 2m53
per leggere 11.280 `consiglio_*.txt` e produrre tabelle che a flag spento
nessuno apre — il 15% della run. Nei log della run appare quindi come step
SALTATO, ed è giusto così. Accendendo il flag torna a girare, e gira prima
del generatore nello stesso job: le tabelle sono fresche quando servono.
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

**IL TETTO DEI 256 PREDICT (13/08/2026, due difetti trovati insieme).**
La matrice di GitHub Actions accetta al massimo 256 job. Il 13/08 lo
scouting ne ha chiesti **1545** per la prima volta (GW5, odds 0,80): due
cose sono venute fuori insieme.
1. **Il workflow moriva proprio nel caso che diceva di gestire** (run
   31675855737). Il passo che prepara la lista scrive lo stdout dentro
   `$GITHUB_OUTPUT`, che accetta solo `chiave=valore`; il messaggio
   `::warning::...` di troncamento ci finiva dentro e GitHub rifiutava il
   file intero ("Invalid format"). Corretto: l'avviso va nel riepilogo
   della run e nel log, e c'e' un output `richiesti` in piu' accanto a
   `quanti`. Verificato in produzione sulla run 31676604130: "AVVISO: 1545
   predict richiesti... ne restano fuori 1289", job verde.
2. **Il taglio a 256 lo decideva l'ALFABETO.** `_scrivi_lavori` scriveva
   le righe raggruppate per (cartella, ruolo) in ordine alfabetico:
   troncando restavano tutta l'Argentina e l'Austria, e sparivano MLS,
   Spagna, Turchia. Visibile nella run 31676604130, dove i 256 job predict
   sono quasi tutti argentini. Ora le righe escono in ordine di **L10
   decrescente su tutte le leghe** (a parita', il voto A-F), cioe' i
   candidati piu' forti per primi: se il taglio scatta, restano fuori i
   meno interessanti — che e' esattamente cio' che serve a chi legge la
   tabella ordinata per A+G e guarda solo la cima (uso dichiarato
   dall'utente il 13/08). L10 e voto sono gia' nel pool, nessuna query in
   piu'; senza `pool` la funzione si comporta come prima.
   Test: `docs/handoff/test_ordine_lavori_scouting.py` (stesso INSIEME di
   lavori, solo ordine diverso; e su 600 candidati il taglio a 256 tiene i
   256 con L10 piu' alto invece di una lega intera).

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

## 8duodecies-bis. Test GW5 Champions — 429 CHIUSO, D1 e D2 CHIUSI, resta D3

**STATO AGGIORNATO AL 13/08/2026 NOTTE (verificato sul codice, non sui
documenti):**
- **D1 `_budget_essenze` — CHIUSO.** `build_formazione_globale.py:2469`
  inizializza `_budget_essenze = None` prima del blocco condizionale; le
  letture successive (2486, 2494, 2543) sono tutte protette da
  `is not None`. Non blocca più nessuna run.
- **D2 notifica Telegram bugiarda — CHIUSO.** `formazione_giornata.yml:836-841`
  ha `id:` sullo step di generazione e
  `if: always() && steps.genera.outcome == 'success'` sulla notifica.
- **D3 92% del predict sprecato — CHIUSA il 13/08 come NON APPLICABILE
  (decisione dell'utente).** Il difetto è reale e resta nel codice:
  `discovery_fixture.py` non contiene **nessuna** occorrenza di `CHAMPIONS`
  (grep, 0 match), quindi screma tutte le leghe anche quando si chiede solo
  la Champions; il workflow passa `CHAMPIONS` solo al generatore (riga 790).
  Ma **si attiva soltanto chiedendo la Champions DA SOLA**, e l'utente non lo
  fa mai né ha motivo di farlo: le sue run chiedono sempre anche le arene.
  Run reale sulle odds della GW5 (12/08): nessun problema.
  È quindi un difetto **latente**, non attivo — stessa categoria della
  tornata opzionale prima del fix del 13/08. Non vale il costo di toccare la
  discovery, che è il pezzo più delicato della pipeline. Se un giorno
  servisse davvero una run solo-Champions, la trappola da ricordare è scritta
  qui sotto (la discovery **svuota** i file delle leghe che esamina: la
  restrizione va committata insieme alla scrittura dei file vuoti per le
  leghe escluse, altrimenti è una regressione).

Stato al 12/08 sera (storico): il 429 era risolto e verificato su run vera,
e i tre problemi qui sotto erano tutti aperti, con D1 bloccante.

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

## 8duodecies-quater. VELOCITÀ — pomeriggio del 12/08 (compresso, vedi §quinquies)

**I fix e i tempi finali stanno in §8duodecies-quinquies**, che è la fotografia
buona. Il dettaglio integrale con tutte le misure:
`docs/handoff/RISPOSTA_OPUS_VELOCITA_STRUTTURALE_2026-08-12.txt`.
Qui resta solo quello che serve a NON rifare gli stessi tentativi.

**La domanda di partenza e la sua risposta.** La run da 18 minuti non era colpa
del preseason né della scala della richiesta: lo scenario reale completo (54
formazioni) gira in **3,1 secondi** in locale, e il numero di formazioni non
tocca né discovery né predict. Il tempo stava tutto nel predict, e il 60-65%
era attesa dopo le risposte 429 di Sorare.

**Le run di confronto** (preseason gw5, soglia 0, ~1160 giocatori, il caso
peggiore):

| run | configurazione | query | 429 | persi | totale |
|---|---|---|---|---|---|
| I | 1 chiave, freno 2s | 1496 | 20 | 1174s | 11,7 min |
| H | 1 chiave, no freno | 1497 | 19 | 2352s | 8,8 min |
| **L** | **3 chiavi, freno 2s, 45 job** | 1492 | **0** | **0s** | **10,4 min** |
| M | 3 chiavi, no freno, 20 job | 1492 | 14 | 3406s | 11,0 min |
| N | 3 chiavi, freno 2s, 20 job | 1492 | 16 | 2747s | 12,7 min |

**TRE IDEE BOCCIATE DAI NUMERI — non riprovarle senza una ragione nuova:**
- **freno tarato su 600/min con una chiave sola** (che ne vale 200): un
  parametro giusto su un budget sbagliato è un parametro sbagliato;
- **freno spento con tre chiavi**: il Retry-After medio è 243s, non 120, e i
  blocchi costano il doppio di quello che il freno risparmia;
- **N_BIN 20 invece di 45, provato tre volte in tre condizioni diverse.** Il
  freno distanzia le richieste *dentro* uno shard, ma con meno shard ognuno
  lavora più a lungo, quindi in ogni istante ce ne sono di più attivi sulla
  stessa finestra di budget. **Meno job non è meno traffico: è lo stesso
  traffico più concentrato.**

**QUELLO CHE NON SI PUÒ TOCCARE.** 20 job in parallelo (piano GitHub Free; Pro
ne darebbe 40) e 40 query in volo lato Sorare. I due numeri sono vicini: oltre
~40 il parallelismo non ha più senso. Regola generale: *finché i job stanno
dentro gli slot disponibili dividere conviene sempre* (discovery a 4 job: 65s
contro i ~176s che costerebbe unificata); *quando li superano, ogni job in più
si somma davvero*.

**DUE LEZIONI METODOLOGICHE, le più importanti della giornata:**
- l'ipotesi "meno query = meno tempo, proporzionalmente" è **falsa**: le query
  sono scese del 78% e il tempo solo del 43%, perché l'attesa da 429 era
  piatta;
- l'esperimento che sembrava falsificare "i 429 nascono dalla raffica" era
  **rotto**: il freno non attraversava i processi (ogni giocatore è un processo
  nuovo), quindi non misuravo il pacing ma un interruttore staccato. È
  esattamente la trappola descritta in CLAUDE.md — **prima di misurare
  l'effetto di un componente, dimostrare che l'interruttore funziona.**

---

## 8duodecies-quinquies. GIORNATA DEL 12/08/2026 — velocità, APIKEY, repo dimezzato

**Sezione da leggere per prima se si riprende da qui.** Riassume una sessione
lunghissima. Il dettaglio delle misure sta in
`docs/handoff/RISPOSTA_OPUS_VELOCITA_STRUTTURALE_2026-08-12.txt`.

### 0. In due parole

La pipeline **girava in 18-40 minuti, adesso ne fa 8**, su GitHub come sempre.
Tre cose l'hanno sistemata: le cache che finalmente tornano a casa invece di
essere buttate a fine run, le tre chiavi API che tolgono i blocchi di Sorare,
e la scoperta che il job più lento (`formazione`) passava sei minuti a leggere
file per non trovarci niente. In mezzo c'è stata una parentesi sui runner di
casa che **non ha funzionato e si è chiusa**: il generatore è tornato su
GitHub. Il pool di giocatori è stato verificato uno per uno contro Sorare:
**455 su 455, zero persi**.

### 1. Dove siamo, con i numeri (run 31647598044, scenario realistico)

| fase | mattina | sera |
|---|---|---|
| pool (odds + grade) | 4m23 | 1m15 |
| discovery (4 job) | 5m49 | 1m29 |
| discovery_merge | 4m09 | 0m31 |
| predict (45 job) | 22m15 | 2m42 |
| consiglio | non partiva | 0m39 |
| formazione | 7m41 | 1m01 |
| **totale** | **~40 min** | **7m57** |

Parametri di quella run (quelli veri di una giornata): gw5, soglia 0,80,
In Season MLS 6 e K League 6, All Stars 4, Under 23 4, Champions 4, arene a
budget 6.000 essenze senza numero fisso. Esito: 40 formazioni (24 di
competizione + 20 arene, budget speso fino all'ultima essenza). Non riempite
solo MLS #6 e Champions #2-4, con il motivo scritto in chiaro dal bot (slot
senza candidati, copie esaurite) — corretto, non un difetto.

### 2. LE TRE APIKEY

Secret GitHub: **`SORARE_APIKEY`**, **`SORARE_APIKEY_2`**, **`SORARE_APIKEY_3`**.
⚠️ **La prima NON si chiama `_1`.**

| accesso | richieste/min | complessità |
|---|---|---|
| anonimo | 20 | 500 |
| sessione col solo cookie | 60 | 30.000 |
| con APIKEY | 200 a chiave (600 il tetto del programma) | 30.000 |

Più un tetto separato di **40 query contemporaneamente in volo**, che nessuna
chiave alza.

**I due fatti che costano ore se non si sanno:**
1. **La chiave scavalca il tetto del cookie.** Misurato: 600 richieste col solo
   cookie → 461 bloccate; le stesse con cookie+chiave → zero.
2. **I tetti delle chiavi si sommano.** Nel job `predict` ogni shard ne prende
   una diversa con `IDX % 3`.

**Dov'è cablata**: 399 file. **Dove NON c'è, di proposito**: `scanners/track.py`,
`bots/autobuy_sorare.py` (in disuso).

**ATTENZIONE, errore da non ripetere**: la complessità 30.000 ce l'ha **anche
il solo cookie**. Il 12/08 avevo messo un paracadute ("pagine grandi solo se
c'è la chiave") che era prudenza sprecata, e l'ho tolto dopo averlo misurato.
Prima di condizionare qualcosa alla chiave, chiedersi se il cookie basta già.

### 3. Cosa è stato sistemato oggi

| commit | cosa |
|---|---|
| `cdd0019647` | il game log dei giocatori con meno di 30 partite si ri-scaricava **per intero a ogni run, per sempre** (523 su 1151) |
| `736ddbb0c4` | **il più grosso**: `upload-artifact` scarta i file nascosti, quindi **tutto il lavoro di cache veniva buttato a fine run** |
| `ffd75f5415` | stesso problema per i panchinari (storia lunga, poche presenze) |
| `b3b49fddd9` | la chiave non arrivava a discovery e pool (`getattr` su un modulo che non la definiva) |
| `b03eebf69b` | tre chiavi a rotazione nel predict + freno tarato sul budget vero |
| `05a7db87b8` | UTF-8 e fine riga (vedi §5) |
| `a42d4ec8b6` | il job `formazione` da 7m41 a 1m10 (vedi sotto) |
| `577651ac9d` | carte a 50 per pagina invece di 20: stesse carte, metà richieste |
| `289c691285` | la discovery non pagina più le posizioni degli altri ruoli |
| `d97e40f63b` `8bdc4adefc` | potatura del repo, poi automatica (vedi §6) |

**Il job `formazione` (7m41 → 1m01)** era il collo di bottiglia finale, e
dentro c'erano due sprechi:
- `aggiorna_grade_scala_produzione.py`: **2m53 per leggere 11.280 file** e
  produrre due tabelle che `build_formazione_globale` carica solo dentro
  `if GRADE_GROUP_STORICA_ENABLED:` — flag spento di default. Ora gira solo a
  flag acceso, e in quel caso gira comunque prima del generatore: non si perde
  freschezza.
- `aggiorna_gk_attacco_avversario.py` (questo serve): passava **due volte sugli
  stessi 6.432 file, 337 MB**, per trovare zero partite nuove. Ora una sola, e
  salta i file non cambiati riconoscendoli dalla **dimensione**. In locale: 55s
  il primo giro, **1,0s** il secondo, file prodotto identico byte per byte.
  LIMITE MISURATO: la dimensione non attraversa i sistemi operativi (git
  converte i fine riga: lo stesso file pesa 62.430 byte su Windows e 60.272 su
  Linux). Si ripara da solo — la run ricostruisce l'indice e lo committa.

### 4. LA PARENTESI DEI RUNNER DI CASA — chiusa, e perché

Il generatore è stato spostato su 10 runner self-hosted sul PC di casa e poi
**riportato su `ubuntu-latest`**. Il motivo, misurato:

- le "dieci macchine" sono **un PC solo**: un disco, 10 core, 16 GB di RAM;
- il repo va materializzato a ogni job, e su Windows `git reset --hard` su
  73.000 file costava **68 secondi** contro i 2 di Linux;
- dieci copie da 337 MB della stessa cache non stanno in RAM, quindi ogni job
  legge sempre da disco freddo (misurato: 94s a freddo contro 4,5s a caldo —
  **non era l'antivirus**, l'esclusione di Defender non ha cambiato niente);
- il conto migliore ottenibile a casa era **~10 minuti contro i 6-8 di GitHub**.

**Restano due runner registrati** (`pc-andrea`, `pc-andrea-2`) per
**`bot_definitivo`**, che è il caso opposto: un job solo, lungo, dove conta la
latenza verso Sorare (**82 ms da casa contro 168 da GitHub**) e non c'è nessun
repo da materializzare quaranta volte. `registra_runner.ps1` e
`rimuovi_runner.ps1` prendono un intervallo (`.\rimuovi_runner.ps1 3 10`).

**Se un domani si riprova**, serve sapere: Git Bash nel PATH di **sistema**
(non utente: il servizio non lo vede), **niente `actions/setup-python`** (prova
a scrivere nel registro e il servizio non ha il permesso), `python` e non
`python3`, e **mai pre-clonare a mano** gli spazi di lavoro (li crea l'utente,
il servizio non li può leggere, la run si pianta).

### 5. I DUE DIFETTI CHE SI VEDONO SOLO SU WINDOWS (chiusi, ma da ricordare)

Trovati durante quella parentesi, e sono il tipo di guasto peggiore: **run
verde, dati persi in silenzio**.

- **UTF-8.** Su Windows python stampa in cp1252, che non contiene le lettere
  turche. Il semplice `log()` alzava eccezione e il giocatore finiva fuori
  dalla formazione: **24 turchi su 37 esclusi** nella run 31631928081, con la
  run verde. Vale anche per ceco, polacco, greco, giapponese, coreano, russo.
- **Fine riga.** `print()` su Windows chiude con `\r\n` e bash non considera
  `\r` un separatore: `read` restituiva `ruolo='gk\r'`, il `case` non lo
  riconosceva e `set -u` ammazzava il job `consiglio` alla prima riga.

Entrambi corretti a livello di workflow (`PYTHONIOENCODING`/`PYTHONUTF8`) e di
modulo, e le protezioni restano anche ora che si gira su Linux.

**Rete di sicurezza aggiunta**: zero file di matrice ora fanno **fallire** il
job invece di lasciar finire la run verde e senza formazioni (era successo:
run 31638826805, quattro minuti e nessun output).

### 6. IL REPO DIMEZZATO, E LA POTATURA AUTOMATICA

Ogni run scriveva file col timestamp nel nome e non ne cancellava mai nessuno.
Due run nello stesso giorno = due copie di ogni predizione e di ogni consiglio.

| | prima | dopo |
|---|---|---|
| file tracciati | 75.449 | **35.899** |
| peso | 1.905 MB | 1.680 MB |

Tolti **40.151 file doppi** (23.666 + 16.485 in due giri). Perché si può:
`build_consiglio` e `best_five` prendono `sorted(glob)[-1]`, il generatore
prende `latest_consiglio`, e lo script del voto storico deduplica già per
(lega, codice, slug, kickoff). L'analisi storica dell'errore **non** usa questi
file: legge `prediction_log.json`, che non si tocca. Resta comunque l'ultimo
file di ogni giorno.

**Ora gira da sola**: `pulisci_predizioni_doppie.py --esegui` è uno step di
`salva_output`, subito prima del `git add`. Senza, il repo si rigonfia: una
giornata normale aggiunge un migliaio di file, il 12/08 ne ha aggiunti
sedicimila.

### 7. CONTROLLO DI MERITO — il pool verificato contro Sorare

Fatto uno per uno sulle carte esportate dall'utente (soglia 0,60+), la prima
giornata con la Turchia e altri campionati nuovi in calendario:

| ruolo | carte | giocatori | bot | mancanti | copie |
|---|---|---|---|---|---|
| portieri | 83 | 67 | 67 | **0** | 83 = 83 |
| difensori | 179 | 152 | 152 | **0** | 179 = 179 |
| centrocampisti | 141 | 127 | 128 | **0** | 141 = 141 |
| attaccanti | 120 | 106 | 108 | **0** | 120 = 120 |

**Nessun giocatore perso, e il conteggio delle copie è esatto carta per carta.**
I 3 "in più" sono giocatori per cui Sorare non pubblica le odds (il bot ripiega
sulle presenze storiche: Ratão 21 su 22) o carte senza campionato assegnato,
quindi invisibili nella vista filtrata dell'utente. Script riutilizzabili nello
scratchpad della sessione (`confronta2.py`, `confronta_carte.py`): reggono i due
formati di incollato e uniscono i doppioni prima di confrontare.

**Trappola del confronto**: la sigla del ruolo può coincidere col codice di una
squadra (`POR` = portiere ma anche Porto), e nasceva un portiere fantasma di
nome "RIO". Il nome è ripetuto due volte prima del ruolo: pretendere quella
ripetizione.

### 8. Cosa resta aperto

- ~~**Checkout sparso sul predict.**~~ **FATTO il 13/08/2026** (commit
  `2d238e1d84`, `sparse-checkout` per gruppo di leghe nel job predict di
  `formazione_giornata.yml:380`; collaudo in `71e1c2ef22`). Non più aperto.
- ~~**Il file-sveglia ha una tolleranza di un secondo troppo generosa**~~ —
  sostituito dalla marchiatura esplicita dei file ricevuti da artifact
  (commit `d8f0a6345e`, 13/08/2026). Testo storico: quando
  `apply` e `marker` girano attaccati, i file applicati rientrano e l'artifact
  dei consigli si porta dentro predizioni che aveva solo ricevuto. Non perde
  dati, spreca banda.
- **Lo storico delle odds pre-deadline non viene mai salvato.**
  `dati_globali/odds_titolarita_storico.json` non è tracciato da git e nessuno
  step lo committa: ogni run lo scrive e lo butta. Conta solo per i backtest
  (il valore dentro il game log viene riscritto a 0/100 dopo le formazioni
  ufficiali, quindi non è ricostruibile), non per schierare. Priorità bassa,
  decisa con l'utente.
- ~~**216 file paginano ancora a `first: 5`**, tarati sul vecchio tetto 500.~~
  **VOCE SBAGLIATA, corretta il 13/08/2026 contando davvero le occorrenze.**
  Nel repo TUTTI i `first: 5` sono `anyFutureGames(first: 5)` (217 file, zero
  altri): non e' una paginazione, e' "le prossime 5 partite di quel
  giocatore", e il codice ne usa una sola (`_prossima_partita_vera`).
  Alzarlo non toglie nemmeno una richiesta — ne fa arrivare di piu' per la
  stessa. Li' non c'era niente da incassare.
  **Il lever vero era un altro, ed e' stato preso il 13/08/2026**:
  `PAGE_SIZE = 20` in **104 script di discovery per lega**, tarato sul tetto
  di complessita' 500 dell'accesso anonimo quando invece quella query ha
  sempre il cookie (tetto 30.000) e dal 12/08 anche l'APIKEY. Portati a 50,
  il massimo vero del server, gia' in produzione in `discovery_fixture.py`
  dal 12/08 e misurato allora sulla stessa `searchCards` (320 carte in **7
  richieste invece di 16**, stessi slug, stesso nbHits —
  `docs/handoff/prova_pagesize.py`, commit `577651ac9d`). Attesa: ~2,3x meno
  richieste sulla parte carte della discovery. Nel repo non resta piu'
  nessun `PAGE_SIZE = 20`.
  **DOVE SI SENTE, verificato sui log della run 31674619946 e non assunto:
  NON nella pipeline di giornata.** Il job `discovery` di
  `formazione_giornata.yml` lancia `discovery_fixture.py`, che pagina a 50
  dal 12/08; i 104 script per lega li usa `calibrazione_lega.yml` (e
  `audit_leghe_possedute.py` / `diagnostics/discover_missing_leagues.py`).
  Il guadagno e' li', sulla calibrazione di una lega nuova, non sulla run
  quotidiana. Detto chiaro perche' la prima versione di questa voce
  lasciava intendere il contrario.
  **Insieme**: il job `discovery` di `formazione_giornata.yml` usava UNA
  chiave sola per tutti e 4 gli shard (un secchiello da 200 richieste/min);
  ora ruota le tre chiavi come fa gia' `predict` (`IDX % 3`), quindi 600/min.
  Fallback verificato in locale: se le chiavi 2 e 3 non ci sono, tutti e
  quattro gli shard tornano sulla prima, come prima.
- **`bot_profit`** prende ancora 429 per i suoi 10 thread simultanei: si
  sistema abbassando i thread, non allentando i freni. Gira una volta a
  settimana, non è prioritario.


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

## 8terdecies. IL LIVELLO DEI CAMPIONATI — IN PRODUZIONE dal 14/08/2026

**In due righe.** Il modello trattava tutte le 53 leghe come uguali (una sola
calibrazione per ruolo). Non lo sono: chi cambia campionato si portava dietro
un atteso tarato sulla lega vecchia. Dal 14/08 c'è un correttivo acceso di
default (`CORRETTIVO_LEGA_ENABLED`), stimato sui giocatori che si sono
trasferiti davvero. Il tentativo del 13/08 (PRIOR_LEGA, tre varianti tutte
bocciate) è **superato**: restava in `test_mls_fwd_all.py` a flag spento e non
propagato, non è la strada da riprendere.

**COME È FATTO** (`build_formazione_globale.py::_correttivo_lega`, tabella
`generatore_formazioni/dati/coef_lega.json` da `aggiorna_coef_lega.py`):
`punti = scala(0,75) × quota_storico_vecchio × delta_lega`, dove `delta_lega`
è la stima diretta della coppia se ha ≥8 trasferiti per verso, altrimenti
quella in catena. Leghe sotto 12 passaggi: **zero esplicito**. Tetto ±8 punti
(paracadute dichiarato, non una misura: oggi taglia solo Aké). Si spegne da
solo — a storico adeguato la quota è 0. Non tocca mai lo storico.

**I DUE MODI SBAGLIATI DI MISURARLO, provati e scartati** (sono la parte da
non ripetere):
1. *Usare tutte le partite.* Il salto di categoria sembrava costare 16 punti,
   ma la media su TUTTI i passaggi veniva **+7,55** invece di ~0 — impossibile
   per un effetto di lega, per ogni salita c'è una discesa. Era il minutaggio
   (chi scende gioca titolare, chi sale va in panchina). Col filtro
   **titolare→titolare** la media di controllo va a **+0,14** e il salto costa
   5-10. Gli 8-10 punti di differenza il modello li sa già dalle starter odds:
   contarli qui li conterebbe due volte.
2. *La regressione verso la media misurata in modo ingenuo* esce anche quando
   non c'è. Con lo split (livello da metà partite, variazione sull'altra) e il
   gruppo di controllo: chi **resta** non regredisce (−0,03), chi **sale** sì
   (−0,10).

**RETTIFICA DEL −14,49 DI IERI** (§3.2 di `HANDOFF_PRIOR_LEGA_2026-08-13.txt`):
era gonfiato dal gruppo di controllo. Coi loro stessi bucket sui dati di oggi,
i "fermi" sopra 60 calano di **6,83**, non di 2,79 — quindi la differenza
causale per i promossi di alto livello è **−5,1**, non −14,5. Il crollo grezzo
però è reale: chi sale di categoria passa in media **da 64 a 52**; di quei 12
punti ~7 li perde anche chi non si è mosso (è come il modello tratta chi viene
da una striscia d'oro, problema diverso) e ~5 sono causati dal salto.

**VALIDAZIONE** (banco ufficiale, 136.778 righe, 3.838 toccate, 510 giocatori,
coefficienti ristimati SENZA i giocatori testati): sulle righe toccate MAE
14,077 → 13,980 e correlazione 0,164 → 0,187; bootstrap **sui giocatori**
positivo nel 98,3% e 99,1%, IC che esclude lo zero. Lift +0,14 ma NON
distinguibile da zero (IC [−0,07;+0,40]) — tocca il 2,9% delle righe, atteso.
Su TUTTE le righe MAE e livello invariati al terzo decimale: **soglie arena e
scouting restano tarati**, verificato non assunto. Fuori campione nel tempo:
correlazione +0,38, verso giusto nel 70%. La classifica esce
football-plausibile da sola: inghilterra −11,0, germania −5,6, spagna −5,3,
italia −4,3, e ogni seconda divisione sopra la sua prima.

**TRE COSE BOCCIATE IL 14/08, non riproporre senza prove nuove:**
- *Termine "da outlier"* (togliere ai promossi anche una quota del vantaggio
  personale): peggiora in modo **monotono**, q=0,20 migliora solo nel 3% dei
  ricampionamenti. Rimosso il 14/08.
- *Versione "solo in discesa"* (q=0,7): MAE meglio nel 100% dei casi,
  ordinamento peggio nel 100%. È la trappola scritta nella docstring di
  `taratura_confronto_parametri`, non passa la regola delle tre misure.
- *Half-life corto per i soli trasferiti* (idea dell'utente): su 1.738
  osservazioni l'half-life lungo vince a ogni giornata e sull'ordinamento
  sempre. Due o tre partite sono troppo poche — lo storico vecchio è
  "sbagliato ma stabile" contro "giusto ma casuale".

**IL PERCHÉ, che vale più dei numeri:** fra i trasferiti **l'ordinamento
regge**. Calano tutti, ma i più forti prima restano i più forti dopo:
appiattirli sulla media della lega nuova butta via informazione vera. È anche
la risposta alla domanda "e se continuasse a fare il fenomeno?". Altro dato
contro-intuitivo: i trasferiti **non sono più imprevedibili** degli altri
(dispersione 17,1 contro 17,3) — non hanno più incertezza, hanno uno
sbilanciamento sistematico, ed è quello che si corregge.

**COPERTURA**: 26 leghe di produzione su 52 hanno coefficiente (tutte quelle
che contano); 5 sotto soglia (cile 5, colombia 7, russia 9, croazia 11, perù
2) e 21 senza trasferiti misurabili (arabia, grecia, polonia, svezia…) restano
a zero. Cresce da sola: basta rilanciare `aggiorna_coef_lega.py` ogni tanto
(dopo il mercato), non serve per giornata.

**BADGE COSMETICO "NUOVO CAMPIONATO"** (13/08, resta e ora affianca il
correttivo).
Unica cosa che va in produzione da questo filone, per decisione dell'utente:
nessuna correzione dell'atteso, solo un avviso nel report. La carta di chi ha
lo storico in un'altra lega mostra `🌍 Nuovo campionato` (pcard + tabella "Top
esclusi"); l'utente si sistema le formazioni a mano rilanciando con
`EXCLUDE_SLUGS`. Regola di rilevamento: lega DOMINANTE dello storico degli
ultimi 365 giorni (coppe e continentali non contate) diversa da `row['league']`
— il filtro indicato come "quello giusto" in §6.1-ter dell'handoff, non la
"quota di storico altrove" che selezionava le COPPE. Si spegne da solo quando
lo storico nella lega nuova diventa maggioranza: nessuna lista da mantenere.
Zero query, un file di cache game-log per candidato, **+1,6s** sul job.
`NUOVO_CAMPIONATO` (default `'1'`, `=0` lo spegne); alias `giappone100`→
`giappone` obbligatorio (senza, 8 falsi positivi su 178 carte).
**Verifiche**: A/A a flag spento identico bit per bit; a flag ACCESO la
selezione è **identica** (è cosmetico davvero); su run209 flagga
**esattamente i 14 nomi** che l'utente aveva validato a occhio, senza nessuna
lista scritta a mano (Aaronson esce da solo grazie alla finestra di un anno).
File: `build_formazione_globale.py::_annota_nuovo_campionato`,
`formazione_mls/build_formazione_finale.py::_pcard_body_html`.
**Bocciata nello stesso giro, non riproporre: la "catena di sostituti".** Idea
dell'utente: mostrare chi entrerebbe al posto del flaggato, a cascata.
Tecnicamente gratis (`EXCLUDE_SLUGS` + secondo giro), ma misurato: togliendo
il SOLO Vicente cambiano **10 formazioni su 12** (−35,5 pt totali) e nella sua
stessa arena si muovono 4 carte su 5 — l'allocazione è un'ottimizzazione
globale a mazzo fisso, non esiste un "secondo in classifica" da mostrare. In
più il suo rimpiazzo era un altro flaggato. *(Trappola del confronto: nel
DUMP_JSON le arene efficienti escono TUTTE con `idx=1` — accoppiarle per
`(tipo, idx)` confronta sette arene diverse con la stessa e fa sembrare che
cambi tutto. Accoppiarle per posizione dentro il tipo.)*

*(Storico: il 13/08 sera si era deciso di non toccare la produzione, con i
casi stimati Vicente −18, Berhalter −16, Martín −13. Quei numeri sono
**superati** dalla rettifica sopra: col correttivo del 14/08 Vicente vale
−3,8. Il "fix mirato di 2-3 giornate" ipotizzato allora è stato provato ed è
la voce "half-life corto" fra le bocciate.)*

**Il numero che ha cambiato le priorità** — la memoria del modello
(`HALF_LIFE_GAMES`) è 6 partite per FWD/GK ma **25 per i MID e 30 per i DEF**.
Quanto si corregge da solo chi ha cambiato lega:

| partite nella lega nuova | FWD | MID |
|---|---|---|
| 2 | 21% | 5% |
| 6 | 50% | 15% |
| 10 | 69% | 24% |

Gli attaccanti si raddrizzano da soli in un mese e mezzo; **centrocampisti e
difensori restano sbagliati per mesi**. Il valore di una correzione di lega sta
lì, non sugli attaccanti.

**Roba del 13/08 che resta valida ma NON è la strada corrente**: la tabella
`dati_globali/livello_lega_ruolo.json` (67 celle) e il flag `PRIOR_LEGA_ENABLED`
(default `'0'`, solo in `test_mls_fwd_all.py`, mai propagato) — soppiantati da
`coef_lega.json`. Restano validi e utili i 3 difetti del banco corretti allora
(`backtest_arene_previsioni.py`), fra cui la lega scritta a mano `'mls'` per
tutti i giocatori del mondo. Il "conto in sospeso" fra metrica aggregata e
sottogruppo è **chiuso**: la lezione era che una correzione che tocca il 2-3%
delle righe va giudicata sulle righe che tocca, con bootstrap sui giocatori —
ed è così che è stato validato il correttivo nuovo.

## 8quaterdecies. FILONE INTRALEGA (13/08/2026) — CHIUSO PER INTERO, ultimo asse compreso

**L'ASSE "SQUADRA PROPRIA" — misurato e chiuso il 13/08 notte.** Era
l'ultimo pezzo rimasto in piedi di tutto il filone, quello che l'utente
aveva intuito e che nessuno aveva mai toccato: non il livello della LEGA
(§8terdecies) e non il confronto fra i reparti che si affrontano (punti 1-3
qui sotto), ma **quanto è forte la squadra in cui il giocatore sta adesso** —
i casi Ernst al Feyenoord e Simsir al Trabzonspor.

Primo passo economico, prima di costruire qualunque correzione: la forza
della propria squadra spiega qualcosa del RESIDUO (realizzato − atteso)?
Misurato su **16.789 osservazioni carta-giornata deduplicate** su
(slug, fixture) — la trappola §15: lo stesso giocatore compare una volta per
ogni manager che lo schiera, e non deduplicare gonfia l'n. Forza della
squadra dalle 1.212 serie di `intralega_serie.json`, walk-forward stretto
(solo date precedenti al primo kickoff, finestra 365 giorni).
Script: `analisi_manager/p66_forza_squadra_propria.py`.

| misura | corr | IC95 |
|---|---|---|
| forza squadra assoluta | **0,0001** | [−0,0149; +0,0150] |
| scarto dalla lega+ruolo | −0,0131 | [−0,0280; +0,0016] |

Quintili di scarto (da squadra debole a forte), residuo medio: **+1,73 →
+2,33 → +2,58 → +1,51 → +1,60**. Nessuna pendenza, una gobba piatta.

**Perché è ragionevole che sia zero**: lo **storico personale** del giocatore
incorpora già il contesto in cui gioca. Il livello della LEGA no — un
trasferimento fra campionati cambia il metro, ed è per quello che serviva
§8terdecies — ma la squadra sì, perché è la stessa in cui ha accumulato i
punteggi che il modello media.

**Unica eccezione, e conferma una cosa già nota**: sul **portiere** la
correlazione è **−0,058**, IC95 [−0,0989; −0,0172], che esclude lo zero. I
portieri di squadre più forti della media della loro lega rendono *meno*
dell'atteso. Coerente con §5.6, dove è già misurato che la squadra forte fa
parare meno il proprio portiere (corr parate/clean-sheet −0,156). Non è una
leva nuova: è lo stesso tetto strutturale del ruolo visto da un'altra
angolazione, e §5.6 dice già che lì il modello è al meglio misurabile.

**Limite dichiarato**: 25.570 osservazioni (il 60%) scartate perché la serie
storica di quella squadra-reparto era troppo corta. Il verdetto vale sulle
squadre con storia, non su tutte.

**Con questo il filone intralega è chiuso per intero: nessuno dei suoi tre
assi entra in produzione.**

---


**VERDETTO DA BAR.** L'utente voleva confrontare i due reparti che si
affrontano (attacco di A contro difesa di B) *dentro* lo stesso campionato.
L'idea "intralega" in sé è **caduta**; il dataset ha fatto uscire una pista
sul DIFENSORE (gol FATTI dall'avversario) che sembrava viva, ed è stata
**misurata e bocciata lo stesso giorno** in essenze — punto 3. Produzione:
**invariata**, flag e `k` restano nel codice spenti come documentazione.

**NIENTE DI QUESTA SEZIONE ASPETTA IL 25/08** (intestazione corretta il
13/08 sera: diceva ancora "pre-registrata, da valutare il 25/08" mentre il
punto 3 la dava già per chiusa, e quella contraddizione avrebbe fatto
credere a chi legge che ci fosse lavoro in sospeso). Degli altri due filoni
un tempo fissati a quella data: il gruppo grade è **acceso in produzione**
(§8bis-bis), e GK_ATT_AVV si sta rimisurando sullo stesso archivio allargato
invece di aspettare (§5.6, `analisi_manager/p63_gk_att_avv_fuoricampo.py`) —
l'esito va scritto lì quando c'è.

**1. L'ipotesi originaria è bocciata.** Normalizzare la forza dell'avversario
dentro la sua lega invece che sul mondo: 4 celle su 4 la normalizzazione
mondiale (quella che gira oggi) correla **di più** col voto vero (FWD −0,0493
contro −0,0440; DEF −0,0406 contro −0,0373). La differenza fra campionati porta
informazione vera: cancellarla butta segnale, non pulisce rumore.
Script: `analisi_manager/p33_intralega_dataset.py` (dataset, 112.484 righe, 31
leghe, zero query, 68s) e `p34_intralega_gate.py`.

**2. Attaccante contro i difensori avversari: CHIUSO.** Grezzo il segnale c'era
(−0,0728, e −0,0477 al netto dei gol). Dentro la formula, con gli aggiustamenti
di produzione accesi, sparisce: su 23.173 punti MAE e correlazione si muovono
di 3 millesimi e il lift oscilla senza direzione. Era roba che il modello già
prendeva per altre vie. `p35_intralega_termometri.py`.

**3. Difensore + GOL FATTI dall'avversario: MISURATO E BOCCIATO, SPENTO.**
*(Nato come pre-registrazione per il 25/08; chiuso lo stesso giorno perché
misurato in ESSENZE — vedi in fondo alla voce. Non riaprire senza un'idea
nuova.)*
Non è un doppione: la produzione condiziona il DEF sui gol **subiti**
dall'avversario (`SIGN_BY_ROLE['def']=+1`), i gol **fatti** per quel ruolo non
entrano da nessuna parte — e infatti il guadagno è misurato **con** gli
aggiustamenti di produzione già accesi. Su 31.790 punti walk-forward:

| k | −12 | −10 | −8 | −6 | −5 | **−4** | −3 | −2 | −1 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| MAE | 15,120 | 15,029 | 14,965 | 14,927 | 14,917 | **14,913** | 14,917 | 14,927 | 14,942 | 14,964 |
| corr | 0,169 | 0,176 | 0,183 | 0,189 | 0,190 | **0,190** | 0,189 | 0,186 | 0,182 | 0,175 |
| lift% | 14,7 | 14,7 | 15,0 | 16,5 | 16,7 | 16,9 | 16,4 | 17,0 | 17,0 | 17,1 |

Il minimo è **interno e simmetrico** su k=−4 (griglia estesa apposta fino a −12
per non congelare un valore di bordo): non è la forma del rumore.

**IL TERZO METRO, detto onestamente.** Il lift **non sale mai**, su tutta la
griglia. È piatto dentro il proprio rumore fino a −4/−5 e peggiora chiaramente
oltre (−2,1 a k=−8). Misurato quanto rumore ha, con un confronto **appaiato**
giorno per giorno (dei tre pezzi del lift solo `scelto` dipende dalla
previsione, quindi i due bracci condividono `caso` e `oracolo`):
**delta −0,10 con IC95 [−1,70 ; +1,61] su 285 giornate**, cioè un'incertezza 16
volte l'effetto — e in 196 giornate su 285 la scelta cambia davvero, quindi il
test non è nullo per costruzione. `analisi_manager/p36_lift_rumore.py`.
Quindi: **due metri dicono di sì, il terzo si astiene** a k=−4. Non scrivere
che "il lift migliorerebbe con più potenza": la forma della curva dice il
contrario, il lift al più resta fermo.

**LA MISURA CHE HA CHIUSO IL FILONE — in ESSENZE, il metro che decide.**
Obiezione dell'utente, giusta: si continuava a giudicare con tre surrogati
(MAE, correlazione, lift) mentre l'unica modifica al modello accesa
nell'ultimo mese — GK_ATT_AVV — fu decisa **in essenze**. Rifatta quindi su
`archivio_ufficiale` con `p24_binario2_ga.py`, **363 coppie manager-giornata
appaiate**, voto acceso e aggiustamenti avversario accesi, unica differenza fra
i due giri la correzione:

| | essenze |
|---|---|
| delta ON−OFF, **braccio G** (produzione) | **−2.619** |
| IC95 bootstrap sulle coppie manager-GW | [−10.296 ; +5.217] |
| positivo in | 24,5% dei ricampionamenti |
| unità in cui cambia davvero qualcosa | 228 su 363 |
| controllo, stesso delta sul braccio A | **+3.086** (segno opposto) |

Due bracci con segni opposti, entrambi dentro il rumore: firma del caso, non
di un effetto — e il test non è nullo (228 unità su 363 cambiano carte).
**Verdetto: MAE e correlazione migliorano, lift e essenze no. Si chiude.**
Il flag e il k restano nel codice, spenti, come documentazione di cosa è stato
provato. Decisione dell'utente, 13/08/2026 sera.

**Numero collaterale, che vale la pena tenere**: sullo stesso banco con gli
aggiustamenti avversario ACCESI, G contro A vale **+12.953 essenze** su 201
coppie discordanti (trim simmetrico +11.907). Il grade continua a pagare in
ogni configurazione in cui lo si misura.

**Difetto del metro trovato e corretto strada facendo** (vale per chiunque lo
usi): `taratura_confronto_parametri.py` girava con gli aggiustamenti avversario
**spenti** — è lo stesso banco che aveva fatto accendere `FWD_OFFENSE_SENSITIVITY`
a 3.0 per poi doverla riportare a 0.0. Aggiunto `--con-avversario` (default
spento, così le misure vecchie restano confrontabili) **sia** nel ramo delle
griglie **sia** in quello `--candidati`: nel secondo mancava, e un A/A sul flag
nuovo risultava "identico" non perché il flag fosse inerte ma perché al modello
non arrivava nemmeno l'avversario. Corretto e riverificato: a flag acceso i
numeri si muovono.

**LO STESSO DIFETTO STAVA ANCHE NEL BANCO IN ESSENZE — da sapere prima di
citare qualunque misura passata.** `backtest_arene_previsioni.score_atteso()`,
quella che alimenta il backtest in essenze (`p23`/`p24`), chiamava `calcola()`
**senza** `usa_avversario`: quindi anche il metro che ha promosso GK_ATT_AVV
(§5.6) calcolava con gli aggiustamenti avversario **spenti**. Per un confronto
appaiato G vs A si compensa in gran parte (l'errore è lo stesso nei due
bracci); per una correzione che riguarda proprio l'avversario **no**.
Risolto il 13/08 con un parametro esplicito, **default `False` = comportamento
invariato** (`backtest_arene_previsioni.py:743, 825, 970-995`), così le misure
vecchie restano confrontabili e chi vuole il modello vero lo accende a mano.
Insieme al bug GK di §8quindecies fanno **quattro** difetti dello stesso tipo
trovati in un giorno solo: il banco misurava una cosa diversa da quella che
dichiarava. Regola che ne esce, valida per ogni misura futura: **prima di
leggere un numero dal banco, verificare con quali interruttori è stato
prodotto** — e in un banco di misura un `except` largo non è prudenza, è un
modo silenzioso di mentire (è stato `p24`, che non ne ha, a stanare il bug GK
crashando in faccia).

---

## 8quindecies. HALF_LIFE_GAMES rimisurato (13/08/2026) — NON è stantio, non si tocca

Dubbio dell'utente, legittimo: quei valori furono tarati quando il modello era
agli inizi e non sono mai più stati guardati, mentre intorno è cambiato tutto
(grade G, GK_ATT_AVV, calibrazione per ruolo). **Rimisurati tutti e quattro i
ruoli, 11 valori da 3 a 60, con gli aggiustamenti avversario ACCESI** — cioè
nella condizione in cui il modello gira davvero, che è la novità rispetto alle
tarature precedenti. **Esito: i valori di produzione stanno dove devono. Nessun
cambio.**

| ruolo | n punti | produzione | MAE prod → migliore | corr prod → migliore | verdetto |
|---|---|---|---|---|---|
| GK | 7.842 | 6 | 16,157 → 16,150 (12-60) | 0,070 → 0,073 (20-60) | vedi sotto |
| DEF | 31.790 | 30 | 14,964 → 14,964 (20-40) | 0,175 → 0,175 | **pianoro**, indifferente |
| MID | 29.036 | 25 | 13,253 → 13,251 (12-16) | 0,238 → 0,239 | guadagno sotto il rumore |
| FWD | 23.173 | 6 | 14,761 → 14,723 (a 3) | 0,248 → 0,239 (a 3) | i metri **si contraddicono** |

**Perché non si tocca niente, in concreto:**
- **DEF**: da 12 a 60 la MAE cambia di 3 millesimi e la correlazione di zero. Il
  valore esatto è **irrilevante**: 30 va bene quanto 20 e quanto 40. Il fatto che
  fu tarato presto non è costato nulla, perché lì la curva è piatta.
- **MID**: 12-16 è meglio su tutti e tre i metri, ma di **0,002 di MAE** — cioè
  *sotto* il tremolio fra ambienti già documentato per questo banco (0,003 di MAE,
  0,0008 di correlazione, §"Cosa deve riprodursi"). Non è un miglioramento, è
  rumore che capita di avere il segno giusto.
- **FWD**: la MAE vuole 3, la correlazione e il lift vogliono 6-20. Quando i metri
  litigano non si applica (e la MAE da sola premia i modelli che non ordinano:
  è la trappola scritta nella docstring dello strumento). 6 è il compromesso, e
  regge.
- **GK**: qui MAE e correlazione preferiscono **lungo** (12-60), il lift
  preferisce **corto** (8,2 a hl=3 contro 6,7 a 6 e 4,6 a 20-30): si
  contraddicono, quindi non si applica. E la correlazione resta **0,07**, cioè
  praticamente zero — il modello non ordina i portieri, come già chiuso in §5.6.
  **ATTENZIONE — questa riga è stata RIFATTA il 13/08 sera**: la prima versione
  (MAE 16,918, corr 0,021) era calcolata su un campione mutilato da un bug,
  vedi sotto. Non citare i numeri vecchi.

**BUG TROVATO E CORRETTO IL 13/08 SERA — righe GK buttate in silenzio.**
`_calcola_base` (backtest) passava `league` a tutti e quattro i ruoli dopo il
fix PRIOR_LEGA del 13/08 mattina, con il commento "è innocuo a correzioni
spente". **Falso per il GK**: `compute_score_atteso_gk` è l'unico dei quattro
che non ha quel parametro, quindi alzava `TypeError` — e
`taratura_confronto_parametri.valuta` avvolge la chiamata in un `try/except`
che fa `continue`, quindi le righe sparivano **senza un errore visibile**.
Misurato: **957 punti GK su 1.068 (89,6%) scartati**, e i sopravvissuti erano
solo quelli con la partita bersaglio fuori da `LEAGUE_DIR` (le coppe) — il
campione peggiore possibile. L'intestazione della tabella continuava a dire
"7.842 punti" perché stampa i punti RACCOLTI, non quelli valutati.
Fix: `if ctx.get('lega_vera') and ruolo != 'Goalkeeper'`. Verificato: 400 punti
GK su 400 ora si calcolano, zero falliti. **DEF/MID/FWD non erano toccati**
(le loro funzioni accettano `league`), quindi tutte le altre misure del 13/08
reggono. Lo ha stanato `p24`, che NON ha un try/except attorno e quindi è
crashato in faccia invece di dare un numero sbagliato: è l'argomento più forte
contro gli except larghi in un banco di misura.

**La cosa da portarsi via**: il sospetto era ragionevole ma la risposta è no —
e il motivo è che **la curva dell'half-life è piatta** su DEF e MID. Non è che
la vecchia taratura fosse fortunata: è che in quella zona il parametro non
morde. Non ripetere questa misura senza un motivo nuovo.

### 8quindecies-bis. Rifatta COL GRADE ACCESO (stessa sessione, domanda dell'utente)

**Il buco era vero**: nel banco di prova la parola "grade" non compare
nemmeno una volta (`backtest_arene_previsioni.py` e
`taratura_confronto_parametri.py`, zero occorrenze), mentre la produzione dal
07/08 non schiera su `atteso` ma su `atteso + sd_gruppo × z_grade`. La misura
qui sopra descriveva quindi un modello che non è più quello che gira.
Rifatta: ogni riga punteggiata **due volte sullo stesso campione** (senza voto
e col voto), gruppo `(lega, ruolo, giorno)`, formula identica a
`_apply_grade_group`. Script: `analisi_manager/p37_halflife_con_grade.py`,
output integrale in `analisi_manager/dati/halflife_con_grade_2026-08-13.txt`.

**Quanto pesa il voto** (produzione, stesso campione, senza → con):
DEF corr 0,167 → 0,233 e lift 17,0 → 24,2; MID 0,215 → 0,277 e 24,2 → 29,6;
FWD 0,238 → 0,295 e 24,4 → 29,5. **Cambia tantissimo**: giudicare l'half-life
senza il voto era davvero misurare un altro modello.

**Ma l'ottimo non si sposta — e dove si sposta, si sposta VERSO la produzione:**
- **MID**: senza voto l'ottimo sembrava 12-16; **col voto è esattamente 25**,
  cioè il valore di produzione, e lo è su tutti e tre i metri insieme
  (MAE 13,502 minima, lift 29,6 massimo). La taratura vecchia era meno cieca
  di quanto temuto.
- **DEF**: pianoro anche col voto (MAE 14,693-14,698 da 16 a 60). 30 va bene
  quanto 60. Nessun motivo di toccare.
- **FWD**: **unico caso con una tensione visibile.** Col voto il lift preferisce
  12-16 (30,3-30,8) contro il 29,5 della produzione a 6, ma la MAE peggiora di
  0,048 (14,498 → 14,546) — sopra il rumore, quindi la contraddizione è reale,
  non tremolio. Metri che litigano ⇒ non si applica. È però l'unica voce di
  questo filone che meriti un secondo sguardo se un giorno si vuole ottimizzare
  la SELEZIONE invece della previsione.
- **GK**: riga **NON VALIDA**, prodotta prima del fix del bug descritto sopra
  (89,6% dei punti GK scartati in silenzio). `p37` va rilanciato per il solo GK
  se quella riga serve davvero; per gli altri tre ruoli i numeri reggono, le
  loro funzioni accettano `league`.

**Limite del campione, da citare sempre insieme a questi numeri**: si misura sui
27.294 punti che hanno il voto storico (16-21% della cache), raccolti a suo
tempo su giocatori presi dai file manager — **non è un campione casuale**.
Dentro quel sottoinsieme i gruppi reggono (92% delle carte in gruppi usabili,
mediana 3), quindi "l'ottimo si sposta?" è una domanda lecita; "di quanto su
tutta la popolazione" no.

**Conseguenza per chiunque tari un parametro d'ora in poi**: il metro ufficiale
NON applica il grade. Per i parametri che toccano la SELEZIONE (lift) questo
non è un dettaglio. Qui si è aggirato con `p37`, che resta il modo di farlo
finché il grade non entra nel banco.

Comando esatto (~20 minuti, zero query):
`python taratura_confronto_parametri.py --ruoli gk,def,mid,fwd --candidati
"3:0,4:0,6:0,9:0,12:0,16:0,20:0,25:0,30:0,40:0,60:0" --con-avversario`
Output integrale: `analisi_manager/dati/halflife_rimisura_2026-08-13.txt`
(+ `.json`). Il secondo giro previsto (stessa griglia con l'avversario spento,
per capire se la taratura vecchia fosse distorta da quello) **non è stato
fatto e non serve**: l'ottimo non si è spostato, quindi non c'è niente da
spiegare.

---

## 10bis. COSE DA FARE — riscritto il 09/08 notte, ripulito 11/08 (verificato contro il codice, non a memoria)

### BUG DI PRODUZIONE — trovato e CHIUSO il 14/08/2026 (Opus, controllo della run 31776364504)

**Da quando GRADE_GROUP_STORICA_ENABLED è acceso di default (13/08 sera), il
correttivo GK_ATT_AVV non ha PIÙ NESSUN EFFETTO sulla scelta.** Non è
un'ipotesi: dimostrato con un test sintetico locale (due portieri identici,
avversari con aggiustamento +0,03 e +5,11 → dopo la catena completa hanno lo
stesso `atteso` 50,53).

Perché, in `generatore_formazioni/build_formazione_globale.py`
(`load_league_role_data`, righe 1416-1429):
1. `_apply_grade_group(rows)` col flag storico ACCESO esce presto (riga 635):
   scrive `atteso_cal`/`atteso_combinato` ma **non tocca** `atteso`;
2. `_apply_gk_att_avv(rows)` (riga 1418) somma il correttivo dentro `atteso`;
3. `_recentra_grade_per_ruolo` (riga 1462) fa `r['atteso'] =
   r['atteso_combinato'] - media`, e `atteso_combinato` era stato calcolato al
   passo 1, **prima** del correttivo GK → il passo 2 viene cancellato.

**QUANDO è morto, con le date esatte** (git, non a memoria): il codice che
cancella esiste dal commit `8d91d808ae` (12/08 02:01) ma era **inerte**, perché
il flag era spento di default. È diventato vivo con `e42ee69db3` (13/08 ore
**22:15 Roma**, "Il voto A-F si applica sempre"), che ha acceso insieme il
default nel codice e l'input del workflow. Verificato sui log di produzione:
run 31674619946 (13/08 mattina) `GK_ATT_AVV_ENABLED: 1` +
`GRADE_GROUP_STORICA_ENABLED: 0` → correttivo VIVO; run 31776364504 (14/08)
entrambi a 1 → correttivo MORTO. Fra le due non c'è nessun'altra run di
`formazione_giornata.yml`: **una sola run di produzione colpita**, quella del
14/08. Tutte le validazioni del correttivo GK fatte il 12-13/08 restano quindi
valide, misuravano un correttivo davvero acceso.

Col flag storico SPENTO (comportamento fino al 13/08) il bug non c'era:
`_apply_grade_group` scriveva `atteso` da sé al passo 1 e il correttivo GK si
sommava sopra. È quindi una **regressione introdotta dall'accensione**, non un
difetto vecchio.

Impatto: la run 212 del 14/08 (24 formazioni, già consegnate) ha schierato i
portieri **senza** il correttivo dell'attacco avversario — cioè con l'atteso GK
di nuovo quasi piatto, differenziato solo dal voto. Gli aggiustamenti in
tabella arrivano a ±5 punti, quindi non è cosmetico. DEF/MID/FWD non sono
toccati (nessun altro modificatore vive fra i passi 1 e 3).

**FIX APPLICATO** (14/08, autorizzato dall'utente): in
`_recentra_grade_per_ruolo` il voto si somma come DELTA sul valore corrente
(`delta = atteso_combinato - atteso_cal - media`, poi `atteso = base + delta`)
invece di sovrascrivere, così sopravvivono entrambi i correttivi. Scartata
l'alternativa di spostare `_apply_gk_att_avv` prima del voto: cambierebbe
anche `atteso_cal`, cioè la base su cui si legge il voto, e non è quello che
si vuole misurare.
Verifiche fatte prima del commit, entrambe passate:
- **A/A vecchio-contro-nuovo su dati sintetici**: DEF/MID/FWD **bit-identici**
  (con atteso == atteso_cal, `base + delta` è algebricamente
  `atteso_combinato - media`), e GK identico quando l'avversario non è in
  tabella (correttivo assente → nessun cambiamento);
- **il correttivo GK torna vivo**: due portieri stesso voto A, avversari da
  +0,03 e +5,11, prima del fix finivano **entrambi a 50,53**; dopo il fix
  50,55 e 55,65. Voto e correttivo si sommano come devono.

**CONFERMA SU DATI VERI** (run di controllo 31780076830, run215, stessa
giornata e stessi dati della run col bug). Sui 18 portieri presenti in
entrambe, il punteggio si muove ora in **entrambe** le direzioni, da −1,40 a
+2,89: sengezer 53,61 → 56,50; miras-blanco 49,36 → 51,15; song 50,42 →
52,11; freese 47,99 → 46,59. Controllo interno che vale più dei numeri:
**delavalee resta a 47,30 esatti**, cioè il caso "avversario non in tabella"
dove il correttivo vale zero per costruzione. Il correttivo GK è vivo.
Resta da misurare, quando servirà, di quanto si sposta il livello MEDIO dei
GK e se tocca le soglie arena — **non stimato qui**.

### APERTO AL 13/08/2026 NOTTE — la lista corta, in ordine di interesse dell'utente

**Chiuse nella stessa notte, senza toccare il codice**: il **margine
d'ingresso** (ogni margine perde in modo monotono, il pareggio secco è il
migliore — §5.9) e con esso la **tensione §5.9**, che non era una
contraddizione ma due popolazioni diverse. **D3 Champions**, chiusa come non
applicabile. E dal backlog vecchio: **voce 5** e **voce 6a** (normalizzazione
del grade e gruppi da 2 carte), risolte dalla scala storica accesa in
produzione; **capitano**, richiuso con potenza vera su 12.677 formazioni
(§5.3).

1. ~~Asse "SQUADRA PROPRIA"~~ **MISURATO E CHIUSO il 13/08 notte**: la forza
   della propria squadra non spiega il residuo (corr 0,0001 sull'assoluta,
   −0,013 sullo scarto dalla lega, quintili piatti su 16.789 osservazioni
   deduplicate). Il modello la cattura già tramite lo storico personale.
   §8quaterdecies. Con questo **l'intero filone intralega è chiuso**.
2. **Fix mirato per chi ha cambiato campionato** (il "cerotto" che l'utente
   ha chiesto): per i ~14 nomi individuati, nelle prime 2-3 giornate nella
   lega nuova, allineare la previsione alla media del ruolo di quella lega e
   lasciare che half-life/shrinkage facciano il resto. Nomi, tabella e
   trappole in `docs/handoff/PASSAGGIO_ORCHESTRATORE_2026-08-13_SERA.txt`.
   **Attenzione**: la finestra da guardare è quella del MODELLO (365 giorni),
   non tutto lo storico in cache — contando tutto ci finisce chi ha traslocato
   tre anni fa. Il valore sta su **MID e DEF** (half-life 25-30, si
   raddrizzano da soli in mesi), non sui FWD (half-life 6, si raddrizzano in
   un mese e mezzo da soli).
3. **CONTO IN SOSPESO sul livello lega**: due misure che non tornano.
   Sull'aggregato (23.173 punti) la correzione peggiora il MAE di +0,12; sui
   704 punti che tocca davvero lo migliora (14,56 → 14,27), stesso campione e
   stesso n. Una delle due è sbagliata e non si sa quale. **Non usare nessuno
   dei due numeri per decidere finché non torna.** Legato: il look-ahead della
   tabella dei livelli non è mai stato misurato (lo script accetta già `fino_a`).
4. ~~D3 — 92% del predict sprecato~~ **CHIUSA il 13/08: non applicabile.**
   Si attiva solo chiedendo la Champions DA SOLA, cosa che l'utente non fa
   mai. Difetto latente, resta nel codice e documentato in §8duodecies-bis,
   non vale il rischio di toccare la discovery per un caso che non si
   verifica.
5. **Il metro ufficiale non applica il grade.** `backtest_arene_previsioni.py`
   e `taratura_confronto_parametri.py` non contengono la parola "grade", ma la
   produzione dal 13/08 sera schiera su GRADE_GROUP_STORICA (tabelle storiche
   + `GRADE_FATTORE_STORICO`=0,482 + ricentraggio per ruolo — non più il
   vecchio `atteso + sd_gruppo × z_grade` di gruppo nativo). `p37_halflife_
   con_grade.py` (13/08 mattina) aggira il buco ma con la formula VECCHIA,
   superata la sera stessa: la sua conclusione ("l'ottimo non si sposta") va
   riverificata con la formula giusta prima di fidarsene.

   **RISPOSTA OPUS, 14/08/2026 ore 09:10 Roma (brief
   `docs/handoff/BRIEF_OPUS_METRO_CON_GRADE_2026-08-14.txt`).
   Raccomandazione: (b) IMPLEMENTARE, ma a DUE COLONNE, non sostituendo il
   metro attuale.** Dettaglio sui tre dubbi:

   - **A (popolazione del ricentraggio): NON è un problema per la decisione.**
     Il ricentraggio è una COSTANTE additiva per ruolo, e il metro valuta un
     ruolo alla volta (`sotto = [p for p in punti if p[0] == RUOLI[b]]`,
     `taratura_confronto_parametri.py:260`). Una costante sommata a tutte le
     righe dello stesso ruolo **non cambia correlazione, non cambia sd_prev e
     non cambia il lift** (non cambia l'ordinamento dentro la giornata): tocca
     solo MAE e bias. Quindi la scelta di produzione non è a rischio. Per
     avere anche MAE/bias giusti basta ricalcolare la costante SUL CAMPIONE
     DEL METRO con la stessa ricetta (media di `atteso_combinato - atteso_cal`
     per ruolo), mai copiarla da una run di produzione. Ed è pure necessario:
     le due popolazioni hanno voti diversi (i candidati di produzione hanno
     media voto 2,42 nel pool del 14/08 contro tabella 3,00; le righe del
     metro sono partite FINAL, dove gli F che non giocano quasi spariscono) —
     il ricentraggio è proprio ciò che rende confrontabili le due.
   - **B (look-ahead delle tabelle storiche): rischio quasi nullo, walk-forward
     NON necessario.** Le due tabelle non contengono nessun esito:
     `grade_scala_produzione.json` è media/sd delle LETTERE, `sd_atteso_
     produzione.json` è la dispersione delle PREVISIONI del modello. Nessuna
     delle due vede un punteggio realizzato, quindi non esiste il canale
     attraverso cui il futuro entrerebbe. Quello che resta è una
     MIS-calibrazione (tabella 2026 applicata a partite di mesi fa): sposta lo
     z verso lo zero, cioè **sottostima** il contributo del voto — direzione
     conservativa, come già il margine residuo del voto (CLAUDE.md, punto
     fisso 13/08). Diverso e già chiuso è il look-ahead del voto per riga:
     nessun leakage sistematico, residuo ~13% conservativo.
     ATTENZIONE però a una cosa vera: `sd_atteso_produzione.json` è la
     dispersione degli attesi **del modello di oggi**. Se una candidata della
     griglia venisse adottata, quella tabella andrebbe RIGENERATA
     (`aggiorna_grade_scala_produzione.py`) perché il peso del voto cambia con
     essa — è la catena di produzione, anello in più da non saltare.
   - **C (il ranking può cambiare?): il ragionamento HA UN BUCO, e si vede sui
     dati.** È vero che il termine del voto è additivo e indipendente dai
     parametri sotto test (dipende solo da lega, ruolo, lettera). Ma MAE,
     correlazione e lift **non sono lineari**: `corr(x+g, y) =
     (cov(x,y)+cov(g,y)) / (sd(x+g)·sd(y))`, e sia `sd(x)` sia `cov(x,g)`
     cambiano da candidata a candidata. In parole da bar: se il voto dice già
     "questo è forte", un parametro che scopre la stessa cosa non aggiunge
     niente, ma il metro di oggi — che il voto non lo vede — glielo conta come
     merito. Il metro col voto acceso premia ciò che il voto NON sa già.
     E il termine non è piccolo: sd del contributo = 0,482 × sd_atteso
     (≈4,85-5,26) × sd(z) ≈ **2,3-2,5 punti**, contro un sd_prev del metro di
     3,0-4,0. Cioè il voto pesa quanto un terzo/quaranta per cento della
     varianza del segnale su cui si sceglie: non è una correzione di contorno.
     La prova empirica sta già in `p37` (formula vecchia, quindi se mai
     SOTTOSTIMA): FWD lift senza voto ottimo a hl 9-12 (25,0), col voto a
     hl 16 (30,8); DEF lift 18,7 → 24,8. La riga GK di p37 resta NON VALIDA
     (voce 6 qui sotto).
     Contro-effetto da mettere in conto: aggiungendo a tutte le candidate lo
     stesso segnale forte, le differenze FRA candidate si assottigliano —
     il metro col voto è più fedele ma **meno sensibile**.
   - **COME FARLO (proposta operativa, non ancora implementata).** Un flag
     `--con-grade` in `taratura_confronto_parametri.py`, stesso pattern di
     `usa_avversario` (default OFF = tutte le misure precedenti restano
     confrontabili), che stampa le due colonne appaiate come fa `p37`. Regola
     di decisione: si sceglie il parametro sulla colonna SENZA voto (più
     risoluzione), ma **una candidata che migliora senza voto e peggiora col
     voto va scartata** — è ridondante col voto e in produzione non renderà.
     Costo: il campione col voto è ~30% delle righe (27.294 su ~92.000 in
     `p37`, non il 16-21% scritto nella sua docstring — quel numero è vecchio,
     l'indice è cresciuto), non casuale, quindi la colonna col voto vale come
     GATE, non come metro fine.

   **IMPLEMENTATO il 14/08/2026 (orchestratore), come raccomandato.**
   `--con-grade` in `taratura_confronto_parametri.py` (funzioni `valuta()`,
   `griglia_favorito()`, helper `_con_grade`/`_metriche`/`_carica_grade`):
   default OFF, A/A verificato (senza il flag l'output è quello di sempre,
   nessun percorso di calcolo cambia). Riusa senza riscrivere
   `p12_backtest_formazione_grade.applica_gruppi_grade(modo='storica_completa')`
   + ricentraggio per ruolo, la STESSA formula di produzione. Anche
   `p37_halflife_con_grade.py` corretto allo stesso modo (usava la formula
   VECCHIA, superata il 13/08 sera) e rilanciato per intero:

   | ruolo | n col voto | senza→col MAE | senza→col corr | senza→col lift% |
   |---|---|---|---|---|
   | GK | 10.207 | 16,13→16,13 (piatto) | 0,07→0,08 | 6,7→5,8 (hl=6, prod) |
   | DEF | 40.045 | 14,99→14,76 | 0,169→0,218 | 16,3→21,4 (hl=30, prod) |
   | MID | 35.440 | 13,05→12,77 | 0,239→0,290 | 24,8→29,4 (hl=25, prod) |
   | FWD | 30.308 | 14,47→14,18 | 0,251→0,300 | 26,4→29,9 (hl=6, prod) |

   Conferma qualitativa del punto C: su FWD il lift col voto continua a
   salire oltre hl=6 fino a un plateau 31,0-31,5% verso hl=12-16 (contro
   26,4-27,3% senza voto, che plateaua prima) — stesso fenomeno segnalato da
   Opus sulla formula vecchia, riprodotto con quella giusta. Non è una
   ritaratura (servirebbe bootstrap/IC, non fatto qui): è la controprova che
   il GATE funziona ed è sensibile, esattamente come doveva.
   **Prova pratica del GATE su una griglia vera** (`--favorito 0,1,2
   --con-avversario --con-grade`, FWD, n=2.996): la correzione "favorito_k"
   PASSA il criterio standard (MAE/corr/lift migliorano insieme, k=1 e k=2)
   ma il GATE la boccia (lift col voto peggiora, −0,6 e −1,7) — è il caso
   esatto che il punto C prevedeva: una correzione ridondante col voto, che
   il metro di oggi (senza voto) scambierebbe per un miglioramento vero.
   Nessun parametro di produzione toccato: solo lo strumento di misura.
   File: `taratura_confronto_parametri.py`, `analisi_manager/
   p37_halflife_con_grade.py`, `analisi_manager/dati/
   halflife_con_grade_2026-08-14.json`.

   **BOOTSTRAP SULLO SPOSTAMENTO FWD — fatto il 14/08/2026 su richiesta
   dell'utente ("solo su FWD si sposta l'ottimo?"): NON REGGE.**
   Domanda preliminare: lo spostamento (hl=6→12/16) è specifico di FWD o
   generale? Guardando i quattro ruoli — GK segue la stessa direzione ma il
   segnale è troppo debole per fidarsene (lift sempre <9%, ruolo già noto
   come "tetto strutturale"); DEF è piatto (16,3→16,3 di picco, hl=30 di
   produzione già lì); MID è piatto e va nella direzione OPPOSTA (picco a
   hl=6, non più in là). **Solo FWD ha uno scarto reale e su un plateau
   ampio (hl=9-60): è l'unico dove vale la pena testare.**
   Bootstrap per GIOCATORE (non per riga: le partite dello stesso giocatore
   non sono indipendenti, stesso principio del bootstrap-manager già in uso
   altrove), 1.303 giocatori, 1.000 ricampionamenti, colonna col voto,
   hl=16 contro hl=6 di produzione:
   delta osservato sul campione intero **+1,48** punti di lift%; delta
   MEDIO bootstrap **+0,79** (più piccolo del punto osservato: il grid
   search aveva scelto il picco fra 11 candidati, un po' di ottimismo da
   "il migliore di tanti tentativi" è normale); **IC95% [−0,53; +2,15]**,
   86,5% dei ricampionamenti positivi. **L'intervallo include lo zero: non
   passa il criterio del progetto** (serve che l'IC escluda lo zero per
   decidere, vedi regola sui backtest). Produzione resta half_life=6 per
   FWD: lo spostamento è un'ipotesi con più probabilità di essere vera che
   falsa (86,5%), non una prova.
   File: `analisi_manager/p73_bootstrap_fwd_halflife_grade.py`,
   `analisi_manager/dati/bootstrap_fwd_halflife_grade_2026-08-14.json`.
6. **Riga GK di `p37` NON VALIDA** (prodotta prima del fix del bug che
   scartava l'89,6% dei punti GK, §8quindecies): va rilanciata se quel numero
   serve. DEF/MID/FWD reggono.
7. ~~Le ri-misure pre-registrate del 25/08~~ **CHIUSA il 14/08: era già
   fatta.** GK_ATT_AVV (§5.6) e il gruppo grade (§8bis-bis) sono stati
   entrambi ri-misurati fuori campione il 13/08/2026 stesso (allargando
   l'archivio all'indietro invece di aspettare il 25/08, che non aveva
   giustificazione statistica) — entrambi già decisi e in produzione. Voce
   rimasta in questa lista per una svista, segnalata dall'utente il 14/08.

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

**A. Bloccati dalla POTENZA STATISTICA — quasi tutti SCIOLTI il 13/08.**
Diceva: tre filoni di G (copertura b/c = voci 5 e 6a, capitano = voce 6,
tabella fissa = voce 14) finiti con IC95 larghi ±20-30k su **6 GW e 24
manager**, e "nessuno si sblocca rifacendo i conti sugli stessi dati: o si
allarga il campione...". Il campione è stato allargato a **44 GW e 65
manager** (1.338 unità, 13.860 formazioni). Stato aggiornato:
- **copertura (voci 5, 6a): non servono più**, risolte dalla scala storica
  accesa in produzione (§8bis-bis);
- **capitano: RICHIUSO il 13/08 con potenza vera** — regola col grade
  nuovo, ordine di ruolo e varianza, tutte e tre negative o nulle su 12.677
  formazioni (§5.3). Non è più un problema di campione;
- **tabella fissa (voce 14)**: l'unica ancora sensata da riprovare, ma
  **prima** va fatta la voce 6b (placebo per-giocatore), che dice se abbia
  senso di esistere.
La voce 1 (G sopra il filtro odds) era già stata **ridimensionata**:
poggiava su una premessa falsa sul pool, vedi lì.
**Resta valida la regola generale**: prima di aprire un test-di-formula,
chiedersi se ha la potenza per rispondere.

**B. Misurabili subito, dati già in repo, nessuna query.** Voce 7
(correlazione grade ↔
realizzato: limite superiore alla contaminazione), 3 (perché il
generatore non ha un criterio nella fase opzionale).

**VOCE 3 — CHIUSA il 13/08/2026.** Era vera: la tornata primaria delle
arene si ferma quando nessun tipo rende piu' niente
(`genera_arene_efficienti`), la tornata OPZIONALE invece girava in
round-robin fra i tipi richiesti finche' il pool reggeva o si toccava
`ARENA_OPTIONAL_CAP`, **senza mai guardare il pareggio**. Due criteri
opposti nella stessa run.
Misura (zero query, 165 report gia' in `generatore_formazioni/output/`):
le arene opzionali compaiono in **1 report su 165** — run103 del 02/08 —
e li' erano **11 LASCIA PERDERE su 17**, contro **3 su 696** fra le arene
richieste. Rarissime perche' in modalita' efficiente/budget
(`ARENE_EFFICIENTI`/`ESSENZE_ARENA`, quella che l'utente usa oggi) i
`counts` delle arene restano 0 e la tornata opzionale non parte proprio:
il difetto mordeva solo chiedendo le arene per tipo. Difetto latente,
non attivo.
Fix: la tornata opzionale passa da `genera_arene_efficienti` come la
primaria, con due parametri nuovi (`cap_per_tipo`, `gia_fatte`, entrambi
None = comportamento invariato) piu' `etichetta` per distinguere la riga
di log. Sparisce il ciclo duplicato: il criterio sta scritto in un posto
solo.
Verifiche: (a) end-to-end sul pool vero di oggi, vecchio e nuovo
producono **le stesse 19 opzionali, tutte SCHIERA** (nessuna regressione
— col mazzo di oggi il freno non deve scattare e infatti non scatta);
(b) quattro controlli sulla sola logica di scelta, con le funzioni che
toccano il pool sostituite da finte: niente sotto il pareggio (prima ne
faceva 10), tetto per tipo rispettato, parametri assenti = tornata
primaria identica, e sceglie il tipo piu' redditizio invece di alternare.
Script: `docs/handoff/test_fase_opzionale_arene.py`.

**VOCE 12 — RISOLTA il 13/08/2026: come si estrae il grade storico, oggi.**
La voce diceva "1 query per giocatore" e per questo sembrava cara. Era vero
solo della rotta che usavamo, non di Sorare.

- `playerGameScores(last: 15)` — quella di `completa_grade_mancante.py` — è
  capata a **15 partite dal server**: chiedendo 50, 100 o 200 torna sempre
  15, **senza errore**, e `first`/`before` non esistono (nessun cursore).
  Andando indietro nel tempo quella finestra non arriva: su una giornata di
  febbraio 2026 copriva 215 giocatori su 825 (**26%**).
- `allPlayerGameScores(first: N)` — **lo stesso campo che il predict
  interroga già** per riempire la cache game-log — accetta
  `projection { grade }`, **non ha quel tetto** e arriva ad **agosto 2025**
  (50 partite per giocatore, circa un anno). Verificato che dà lo stesso
  identico voto dell'altra rotta: 71 righe confrontate, 71 uguali.
- Terza strada, per riempire in fretta una giornata intera:
  `anyGame(id) { playerGameScores { … projection { grade } } }` **non
  accetta `last`** e restituisce **tutti i ~60 giocatori di quella partita**
  in una query sola. Una query per PARTITA invece che per giocatore.

Strumento pronto: **`analisi_manager/completa_grade_storico.py`**
(`--fixture` ripetibile, `--fixture-tutte`, `--thread`, ruota le 3 APIKEY,
rispetta `Retry-After`, salva ogni 200 giocatori). Misurato: **825 giocatori
in 18 secondi**, copertura di quella giornata dal 26% al 100%; e 3.790
giocatori in 16 minuti sull'intero archivio. `completa_grade_mancante.py`
resta solo per compatibilità: per lavori nuovi usare quello storico.

**Limite vero, quello sì di Sorare**: il grade **non esiste prima di
~agosto 2025** (giugno 2025 = 0% delle righe, settembre 2025 = 100%).

**C. Difetti noti, costo basso, nessuna ricerca.** `PYTHONHASHSEED=0`
nell'ambiente di lancio (§9); default fasullo `GK_TEAM_CS_WEIGHT=0.5` in
`backtest_arene_previsioni.py:257-260` (§5.7); 21 script con path Windows
hardcoded (voce 11); Russia coperta ma non popolata (§7). Sono tutti
"si fa e si chiude", non producono conoscenza.

**D. Aperti che richiedono dati NUOVI (query/run).** Voce 9 (odds+4ruoli,
serve campione profondo), voce 10 (buco premi Uncapped rank 1/3, forse
già chiuso da v3 — **verificare prima di lavorarci**), voce 12
(estrazione grade storico: **NON è più 1 query/giocatore, vedi sotto**), voce 8 (decisione grade
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

**2. Segregare il rischio DNP — CHIUSA il 13/08/2026, decisione
dell'utente: risolta dal meccanismo suppletivo.** L'idea (09/08) era far
finire le carte a titolarità incerta tutte insieme in una sola Beginner da
100 essenze, così un DNP rovina una formazione già dichiarata precaria
invece di una buona. Non serve più costruirla apposta: la **tornata
suppletiva** fa già esattamente questo. Quando restano slot o budget, le
formazioni in più si generano SOLO su `ARENA_ALLSTARS_BEGINNER`
(`build_formazione_globale.py:2615-2628`), cioè il tipo più economico, e
dal 13/08 passano anche loro dal criterio economico di
`genera_arene_efficienti` invece del vecchio round-robin. Le carte deboli
finiscono lì per costruzione, senza nessuna regola nuova da tarare.

**Nota dell'utente, da tenere**: nelle giornate PIENE (es. GW5) il
meccanismo suppletivo è praticamente inerte — il pool basta per le arene
che contano e non avanza niente da segregare. Serve nelle giornate magre.
Chi lo rimisurasse su una giornata piena troverebbe "nessun effetto" e
concluderebbe male.

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

**5. Normalizzazione del grade — RISOLTA il 13/08/2026.** Diceva: "il grade
è ignorato sul 23% delle carte perché i gruppi (lega, ruolo) sono troppo
piccoli; la prima cura (scala storica) è stata misurata e scartata, serve
un'idea NUOVA". La cura era quella giusta, era la taratura a essere
sbagliata: ritarata (fattore 0,482), validata fuori campione e **accesa in
produzione** — §8bis-bis. Il voto ora si applica sempre. Voce chiusa, non
da rifare.

**6. Due verifiche economiche su G.**
(a) **SUPERATA dalla stessa modifica**: riguardava i gruppi con esattamente
2 carte, dove lo spostamento era meccanico ±1 sd. Con la scala storica il
gruppetto nativo non si usa più e il caso sparisce per costruzione.
(b) **APERTA, ed è la parte che vale.** Placebo permutando i grade **fra le
giornate dello STESSO giocatore** invece che fra giocatori. Tutti i placebo
fatti finora rimescolano fra giocatori, e rispondono a "il voto porta
informazione?". Questo risponde a una domanda mai posta: il voto dice
**"questo giocatore è forte"** — informazione che il modello ha già dallo
storico — oppure **"questa partita andrà bene"**, che è informazione nuova?
Zero query. Cambia come si legge tutto il filone, e in particolare decide se
la "tabella fissa per lettera" (voce 14) abbia senso di esistere: se il voto
è un giudizio sul giocatore, no; se è sulla singola partita, sì.

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
