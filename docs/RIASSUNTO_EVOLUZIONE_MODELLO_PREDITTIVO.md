# Riassunto evoluzione modello predittivo — handoff per nuova sessione/account

**Scritto per essere letto da zero, su un account Claude diverso da quello che ha fatto questo
lavoro** (l'utente alterna due account, poca/nessuna memoria condivisa tra sessioni). Non
presupporre nessun contesto pregresso: tutto quello che serve è qui dentro.

**Aggiornato 27/07/2026 (notte)**: se cerchi solo "qual è lo stato adesso", salta direttamente alla
**sezione 16** (l'ultima) — completa il punto 1 del backlog della sezione 15J (knapsack Arene
collegato e testato). Le sezioni 1-15 restano cronistoria: un TERZO tool, il "Generatore
Formazioni", che fonde MLS+K League in un solo script/workflow senza toccare i due tool dedicati.
Leggi comunque SEMPRE questo documento dall'inizio alla fine prima di concludere che qualcosa
manca, non fidarti solo dell'ultima sezione o della memoria persistente (la sezione 14D spiega
perché, con un caso reale).
Le sezioni 1-13 restano come cronistoria di come ci si è arrivati (parametri di produzione
FINALIZZATI per DEF/MID/FWD/GK, scoperta e validazione della formula `level_score`/floor,
implementazione Arena/All Stars, infrastruttura K League completa), utile se serve capire IL
PERCHÉ di una decisione, non per sapere lo stato attuale.

Repo: `Sorare-tracker-2` (github.com/andreasalvatore93-oss/Sorare-tracker-2), cartella locale
`C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2`, branch `main`. Stato scritto qui: **tutto
già pushato su GitHub** salvo diversa indicazione esplicita più sotto — verificare comunque con
`git status`/`git log` invece di fidarsi ciecamente, potrebbero essere passate altre sessioni nel
frattempo.

**Vedi anche** [`docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`](RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md)
— documento "vivo" (da aggiornare, non duplicare) con l'architettura completa del tool
formazione MLS e la sua storia fino a questa sessione. Questo file qui invece è lo **snapshot di
handoff di QUESTA sessione specifica** (cosa è stato fatto oggi, dove siamo rimasti, come
ripartire) — leggere prima quello per il quadro generale, poi questo per i dettagli operativi
freschi.

## 1. Contesto: cos'è il tool formazione (riassunto minimo)

Sistema che, dato l'elenco delle carte MLS possedute dall'utente su Sorare (fantasy game calcio
NFT), calcola per ognuno dei 4 ruoli (GK/DEF/MID/FWD) uno score atteso per la prossima partita
(media pesata storica x fattori casa/trasferta, forza avversario, trend, granulari per
statistica), poi fonde i 4 migliori in N formazioni ottimali. Script principali:
`formazione_mls/predict/test_gk.py`, `test_def.py`, `test_mid.py`, `test_mls_fwd_all.py`.
Parametri della formula (half_life, range_multiplier, opponent_sensitivity, trend_intensity) sono
FISSI, decisi da un grid search di calibrazione (72 combinazioni testate in backtest rigoroso).

## 2. Cosa è successo in QUESTA sessione (in ordine)

### A. Fix Finding 3 dell'audit logico: doppio conteggio casa/trasferta

`fattore_casa_trasferta` era calcolato sul punteggio TOTALE della partita — che però include già
il contributo di ogni gruppo granulare (falli, duelli, passaggio, ecc.), causando un doppio
conteggio quando poi ogni fattore granulare veniva applicato separatamente. **Fix**: ora si
calcola solo sul RESIDUO (score totale meno la somma di tutti i gruppi granulari tracciati),
applicato a DEF/MID/FWD (GK non toccato: i granulari lì sono solo diagnostici, non in
produzione). Verificato su dati reali con un run vero: l'effetto casa/trasferta ora emerge dai
gruppi granulari specifici (es. gol subiti, falli) invece che duplicato da un fattore globale
gonfiato. **Committato e pushato** (commit `5219bf8d`, poi mergiato in `d8538e3a`).

### B. Discovery globale estesa a tutti e 4 i ruoli + filtro qualità

Prima c'era solo `mls_mid_discovery_global.py` (centrocampisti). Estesa a GK/DEF/FWD
(`mls_gk_discovery_global.py`, `mls_def_discovery_global.py`, `mls_fwd_discovery_global.py`),
stesso approccio: scansione pubblica (nessun cookie richiesto) delle 30 squadre MLS, filtro
lato client per posizione. Workflow `mls_mid_discovery_global.yml` sostituito da un workflow a
matrice unico, `mls_discovery_global.yml` (un job per ruolo).

Risultati grezzi (30/07, prima del filtro qualità): **74 GK, 340 DEF, 346 MID, 276 FWD**.

**Filtro qualità aggiunto** (richiesta esplicita utente: "non voglio calibrare su giocatori
scarsi che non comprerei"): tenuti solo i giocatori con media `(L5+L10+L40)/3 >= 30.0`
(costante `MIN_AVG_SCORE_QUALITY`, letta da env, default 30.0 — abbassata da un iniziale 40.0
perché tagliava troppo, specialmente sui portieri). Le medie L5/L10/L40 vengono lette
direttamente dall'API Sorare (`anyPlayer.averageScore(type: LAST_FIVE_SO5_AVERAGE_SCORE /
LAST_TEN_PLAYED_SO5_AVERAGE_SCORE / LAST_FORTY_SO5_AVERAGE_SCORE)`), non calcolate a mano. Se uno
dei tre valori manca, il giocatore è escluso per sicurezza (storico insufficiente).

Giocatori qualificati dopo il filtro (soglia 30): **27 GK, 156 DEF, 156 MID**, FWD non ancora
verificato con questa soglia esatta (con soglia 40 di test erano 62/276).

Tutto **committato e pushato** (commit `50b23531`).

### C. Infrastruttura di calibrazione allargata (grid search su tutti, non solo posseduti)

Obiettivo: ricalibrare i parametri fissi su un campione molto più ampio dei soli posseduti
(12-45 giocatori a seconda del ruolo), ora che la formula è corretta (fix punto A).

- **`CALIBRATION_MODE`** (env var booleana, nei 4 script `test_<ruolo>.py`): se attiva, legge la
  lista GLOBALE filtrata (invece dei soli posseduti) e riesegue il grid search COMPLETO (72
  combinazioni, funzione `run_grid_search` già esistente nel codice ma non più usata in
  produzione) invece del singolo backtest fisso. Output isolato in cartelle
  `formazione_mls/output/mls_<ruolo>_calibration/` (separate da `mls_<ruolo>_all/` di
  produzione, per non inquinare quello che legge `build_formazione_finale.py`).
- **`.github/workflows/grid_search_calibrazione.yml`**: workflow a batch (input: `ruolo`
  gk/def/mid/fwd, `batch_index`, `batch_size` default 200, `min_avg_score_quality` default 30).
  GitHub Actions ha un limite di 256 job/matrice, da qui la logica a batch — ma finora ogni ruolo
  è stato coperto da UN SOLO batch (nessuno ha superato 200 giocatori qualificati).
- **`.github/workflows/grid_search_aggregate.yml`** + `formazione_mls/calibrazione/
  aggregate_grid_search.py` (parametrizzato per ruolo via env `RUOLO`, prima era hardcoded solo
  per FWD): calcola quale combinazione di parametri generalizza meglio ATTRAVERSO tutti i
  giocatori con dati sufficienti. **Nota**: l'aggregazione è puro calcolo locale sui file JSON già
  scaricati (`git pull`) — non serve rilanciare un workflow GitHub per farla, basta eseguire lo
  script in locale con `RUOLO=<ruolo> python formazione_mls/calibrazione/aggregate_grid_search.py`
  dopo un `git pull`. Il workflow `grid_search_aggregate.yml` esiste solo per farlo girare anche
  da CI se preferito, non è necessario.

**Due bug REALI trovati e corretti durante il primo giro di batch veri** (importante, per non
ripeterli in futuro):

1. **`MIN_STARTER_ODDS` non veniva disattivato in `CALIBRATION_MODE`**: era una costante fissa
   (0.70) con un commento che diceva "se rifai il grid search, riportala a 0.0 a mano" — non letta
   da env, quindi l'override che passavo dal workflow non aveva alcun effetto. Nel primo batch GK
   (27 giocatori) questo ha escluso 25/27 giocatori (starterOdds sotto soglia — irrilevante per
   la calibrazione, che deve guardare tutto lo storico, non solo la prossima partita). **Fix**:
   ora è `0.0 if CALIBRATION_MODE else 0.70` in tutti e 4 gli script. Commit `7a72cad9`.
2. **Bug critico nel retry di push del job `calibrate`** (workflow a matrice, fino a 8 worker
   paralleli): il loop era scritto come `for attempt in 1..8: git add + diff-check + commit +
   push`, ripetendo il diff-check ad OGNI tentativo — dopo un primo commit locale riuscito, se il
   push falliva (conflitto con un altro worker), il tentativo successivo trovava l'indice già
   pulito (nulla di NUOVO da staggare, essendo già committato) e usciva con "Nessuna modifica da
   salvare" **senza mai ritentare il push** — il commit restava intrappolato nel checkout effimero
   del runner e andava perso, MA il job segnalava comunque successo (mascherando il problema).
   Nel primo batch DEF (156 difensori, max-parallel:8) questo ha fatto perdere 123 risultati su
   156 (solo 33 salvati). **Fix**: diff-check e commit avvengono UNA VOLTA sola, poi un loop
   `until git push` dedicato SOLO al retry del push (fetch+merge tra un tentativo e l'altro) —
   stesso pattern già corretto e testato nei workflow di discovery esistenti
   (`formazione_completa.yml`). Commit `1e293791`. **Dopo il fix, il batch DEF rilanciato è
   passato da 33 a 99 risultati salvati su 156** — se in futuro si scrive un altro workflow a
   matrice con commit paralleli, NON riprodurre l'errore del punto 1 (ricontrollare `git diff
   --cached` dopo un commit già fatto).

### D. Batch eseguiti e risultati di aggregazione (fine sessione)

Tutti i batch sono stati lanciati con `batch_index=0`, `batch_size=200`,
`min_avg_score_quality=30` — in ogni caso un solo batch ha coperto tutto il ruolo.

| Ruolo | Qualificati | Grid completi | Con dati sufficienti per l'aggregazione | Combinazione vincente aggregata |
|---|---|---|---|---|
| GK | 27 | 7 (4 senza storico sufficiente per NESSUNA combinazione) | **3** | hl=12.0, range=1.2x, opp_sens=29.0, trend=0.7, **senza granulari** — MAE 18.42, copertura 69.4% |
| DEF | 156 | 99 | **74** | hl=9.0, range=1.4x, opp_sens=29.0, trend=0.7, **con granulari** — MAE 16.65, copertura 68.3% |
| MID | 156 | 96 | **68** | hl=12.0, range=1.4x, opp_sens=29.0, trend=0.7, **senza granulari** — MAE 15.61, copertura 68.9% |
| FWD | ? | — | — | **NON ANCORA FATTO** |

Confronto con i parametri attuali di produzione (calibrati su soli posseduti, PRIMA del fix
Finding 3 — quindi non un confronto a parità di condizioni, solo un riferimento):
- GK produzione: hl=9.0, range=1.6x, opp_sens=20.0, trend=0.7, senza granulari (12 posseduti,
  MAE 21.03, copertura 63.3%)
- DEF produzione: hl=9.0, range=1.2x, opp_sens=29.0, trend=1.3, con granulari (45 posseduti,
  MAE 15.65, copertura 69.4%)
- MID produzione: hl=12.0, range=1.4x, opp_sens=29.0, trend=0.7, con granulari (19 posseduti,
  MAE 15.62, copertura 68.3%)

Osservazione interessante: sul campione allargato e con la formula corretta, DEF continua a
beneficiare dei fattori granulari (conferma la scelta attuale), mentre per MID il campione
allargato suggerisce che i granulari NON aiutino più (la versione senza è in cima alla
classifica, anche se di poco: MAE 15.61 vs 15.81 con granulari) — da tenere in considerazione se
si decide di aggiornare i parametri di produzione.

I file `combinazione_vincente_aggregata.json` per GK/DEF/MID sono su disco in
`formazione_mls/output/mls_<ruolo>_calibration/` ma **NON ANCORA COMMITTATI** (generati in
locale, vedi sezione "Stato del repo" sotto).

## 3. Cosa manca / prossimi passi immediati (in ordine)

1. **Lanciare il batch FWD**: `gh workflow run "Grid Search Calibrazione (allargata, a batch)" -f
   ruolo=fwd -f batch_index=0 -f batch_size=200 -f min_avg_score_quality=30`, poi monitorare
   (`gh run watch <id> --exit-status`, o `gh run list --workflow="Grid Search Calibrazione
   (allargata, a batch)" --limit 3` per il run id). **Attenzione rate-limit**: l'utente lavora
   spesso in parallelo sull'app/sito Sorare — chiedere conferma prima di lanciare nuove run se non
   è chiaro se sta usando l'app in quel momento (gli è già capitato di chiedere di mettere in
   pausa script locali per lo stesso motivo).
2. **Aggregare FWD** (locale, no GitHub necessario): `git pull --rebase origin main` poi
   `RUOLO=fwd python formazione_mls/calibrazione/aggregate_grid_search.py`.
3. **Decidere con l'utente** se e come aggiornare i parametri fissi di produzione (costanti
   `HALF_LIFE_GAMES`/`RANGE_MULTIPLIER`/`OPPONENT_SENSITIVITY`/`TREND_INTENSITY` e il flag
   granulari sì/no) nei 4 `test_<ruolo>.py`, sulla base dei risultati aggregati — NON farlo senza
   chiedere, è una decisione che cambia il comportamento di produzione.
4. **Committare** `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` (creato in questa sessione ma mai
   committato — vedi sezione "Stato del repo" sotto) e i file
   `combinazione_vincente_aggregata.json` di GK/DEF/MID già generati.
5. Poi tornare ai **Finding 4-5** dell'audit logico (condizionamento 2D venue+forza avversario,
   correlazione tra slot della formazione GK-DEF-FWD) — discussi ma non implementati, richiedono
   un design dedicato prima di scrivere codice (vedi `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`
   sezione 5 per il dettaglio).

## 4. Lavoro parallelo in corso su un ALTRO argomento (bot di trading, non il modello predittivo)

Nella stessa giornata, in un'altra conversazione/worktree, è in corso un lavoro SEPARATO e non
correlato: rendere dinamiche (basate su percentili storici) le soglie di margine di
`bots/bot_definitivo.py` (ex `bot_supremo_test.py`, rinominato in questa giornata) e dei bot
standalone `autobuy_sorare.py`/`makeoffer_sorare.py`. Menzionato qui solo per completezza — se
l'utente lo tira in ballo in questa sessione, è un filone indipendente con la sua sessione
dedicata, non mischiarlo con il lavoro sul modello predittivo descritto sopra.

## 5. Stato del repo a fine sessione (verificare comunque, non fidarsi ciecamente)

**Pushato su `origin/main`**: fix Finding 3 (`5219bf8d`), discovery globale 4 ruoli + filtro
qualità (`50b23531`), infrastruttura calibrazione (`29d67869`), fix MIN_STARTER_ODDS (`7a72cad9`),
fix bug retry push (`1e293791`), più tutti i commit automatici dei bot (`Grid Search Calibrazione
(<ruolo>): <slug>` uno per giocatore, generati dai workflow) e i commit periodici di "Bot Supremo:
lista nera" (bot di trading indipendente, sempre attivo in background).

**NON ancora committato** (file locali, generati/modificati in questa sessione):
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` (creato, mai `git add`)
- `formazione_mls/output/mls_gk_calibration/combinazione_vincente_aggregata.json`
- `formazione_mls/output/mls_def_calibration/combinazione_vincente_aggregata.json`
- `formazione_mls/output/mls_mid_calibration/combinazione_vincente_aggregata.json`

Da committare quando si riprende (nessuna fretta, sono solo risultati informativi, non toccano
la produzione):
```
git add docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md \
  formazione_mls/output/mls_gk_calibration/combinazione_vincente_aggregata.json \
  formazione_mls/output/mls_def_calibration/combinazione_vincente_aggregata.json \
  formazione_mls/output/mls_mid_calibration/combinazione_vincente_aggregata.json
git commit -m "Aggiunge documentazione evoluzione + combinazioni vincenti aggregate GK/DEF/MID"
git pull --rebase origin main  # ci saranno sicuramente nuovi commit automatici dei bot nel frattempo
git push origin main
```

## 6. File chiave per orientarsi rapidamente

- `formazione_mls/predict/test_gk.py` / `test_def.py` / `test_mid.py` / `test_mls_fwd_all.py` —
  formula di scoring + `CALIBRATION_MODE`
- `formazione_mls/discovery/mls_<ruolo>_discovery_global.py` — discovery pubblica + filtro qualità
- `formazione_mls/calibrazione/aggregate_grid_search.py` — aggregazione cross-player (locale)
- `.github/workflows/grid_search_calibrazione.yml` — batch grid search allargato
- `.github/workflows/grid_search_aggregate.yml` — aggregazione via CI (opzionale, si può fare in locale)
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` — storia/architettura completa del tool (documento vivo)

## 7. Aggiornamento 26/07/2026 — decisione presa, parametri di produzione FINALIZZATI

Continuazione della sessione sopra, in un account diverso. Riepilogo di quello che è successo,
in ordine:

### A. Batch FWD completato + aggregazione (chiudeva il punto 1-2 della sezione 3)

Lanciato il batch mancante (139 attaccanti qualificati, 0 job falliti). Aggregazione (non pesata,
prima versione): hl=9.0, range=1.4x, opp_sens=29.0, trend=1.0, senza granulari, MAE 16.76,
copertura 68.0%, 41 giocatori. Committato (`11016946`).

### B. Scoperto e corretto un bug di fondo nell'aggregazione: media non pesata per n_test

Analizzando il caso FWD, l'effetto dei fattori granulari per SINGOLO giocatore variava da -5 a +5
di MAE tra combinazioni con/senza — ma la media aggregata su 41 giocatori si cancellava quasi a
zero (+0.07 medio, std 1.42). Causa: il MAE per-giocatore viene da un backtest rigoroso con
`min_history=6`, e la finestra di partite testate per giocatore è spesso minuscola (mediana 7,
alcuni con solo 1-3 partite) — un giocatore con 1 sola partita testata pesava nella media quanto
uno con 9, ma il suo "MAE" è di fatto l'errore di un singolo evento, non una stima stabile.
Verificato con dati: i 2 casi più estremi (`osvaldo-pedro-capemba` -5.1, `matias-coccaro-ferreira`
-1.57) avevano entrambi `n_test=1`; correlazione moderata (-0.39) tra n_test e ampiezza dell'effetto.

**Fix** in `formazione_mls/calibrazione/aggregate_grid_search.py`: esclude i giocatori con meno di
`MIN_TEST_GAMES` (env, default 3) partite di backtest dall'aggregazione, e pesa MAE/copertura dei
rimanenti per `n_test` invece di una media semplice per-giocatore. `n_test` ora salvato
direttamente nel campo `n_test` del `grid.json` di ogni giocatore in tutti e 4 gli script
`test_<ruolo>.py` (per i run futuri); fallback al parsing di "Partite testate" dal
`prediction_<slug>_*.txt` per i dati già raccolti del 25/07 (che non avevano ancora questo campo).
Rieseguita l'aggregazione pesata su DEF/MID/FWD con i dati già su disco (nessun nuovo run GitHub
necessario). Commit `ee16fd44`/`a3afc2dc`.

**Risultato pesato (min 3 partite di backtest), molto più coerente del non pesato**:

| Ruolo | half_life | range | opp_sens | trend | granulari | MAE | copertura | n_gioc (partite pesate) |
|---|---|---|---|---|---|---|---|---|
| GK (invariato, campione insufficiente: solo 2 con n_test>=3) | 12.0 | 1.2 | 29.0 | 0.7 | NO | 18.42 | 69.4% | 3 |
| DEF | 12.0 | 1.2 | 29.0 | 0.7 | NO | 16.28 | 67.5% | 68 (517 partite) |
| MID | 12.0 | 1.4 | 29.0 | 0.7 | NO | 15.55 | 70.9% | 65 (492 partite) |
| FWD | 12.0 | 1.4 | 29.0 | 0.7 | NO | 17.33 | 68.2% | 37 (255 partite) |

Tutti e tre i ruoli con dati sufficienti (DEF/MID/FWD) convergono sugli STESSI parametri
(`hl=12.0, opp_sens=29.0, trend=0.7`, senza granulari) — molto più coerente del risultato non
pesato precedente (che per FWD divergeva su hl=9.0/trend=1.0, inquinato da singoli match).

### C. Scoperta tecnica importante: il flag "granulari sì/no" non esisteva davvero in produzione

Il flag `use_granular_factors` passato a `rigorous_backtest` controllava SOLO il backtest
diagnostico mostrato nell'output testuale — la formula REALE di `score_atteso` usata per
costruire le formazioni (in DEF/MID/FWD) moltiplicava SEMPRE tutti i fattori granulari
incondizionatamente, indipendentemente da cosa diceva la calibrazione. GK invece li aveva già
rimossi correttamente dalla formula reale (hardcoded). **Fix**: rimossi i fattori granulari anche
dallo `score_atteso` reale di DEF/MID/FWD (stesso pattern di GK) — senza questo fix, applicare i
nuovi parametri "senza granulari" non avrebbe avuto alcun effetto pratico sulle formazioni.

### D. Confronto A/B su formazioni reali + decisione dell'utente

Applicati i parametri pesati a DEF/MID/FWD (GK invariato) e lanciata una run reale
(`formazione_completa.yml`, num_formazioni=5), confrontata con l'ultima run precedente col vecchio
modello (anch'essa 5 formazioni). Risultato: TOTALE COMPLESSIVO 1577 -> 1653 pt (+4.8%), con
riordinamenti interessanti — caso più chiaro: **Antino Lopez** (DEF che gioca solo il 25% delle
ultime 40 partite storiche, ma con picchi isolati come 86/81) era capitano nel vecchio modello a
86pt (sovrappesato dagli half_life/trend più reattivi e dai granulari non normalizzati), nel nuovo
modello scende a un più realistico 75pt/non più capitano; **Carles Gil** (centrocampista che gioca
quasi sempre, 100% presenze ultime 5/10, media stabile 67-70) sale correttamente a capitano.
Verificato contro le statistiche Sorare reali dei due giocatori (screenshot diretto dall'utente) —
il nuovo modello descrive meglio "chi performa in modo affidabile" vs "chi ha avuto un picco
isolato di fortuna". **Nota**: le due run distano ~5 ore con partite MLS in corso nel mezzo, quindi
parte della differenza numerica potrebbe venire da dati aggiornati (starter odds/nuove partite),
non solo dal cambio di parametri — ma il caso Antino Lopez/Carles Gil è un confronto diretto,
concettualmente pulito, e ha convinto l'utente.

**Decisione presa (26/07)**: parametri UFFICIALI (non più "test") in produzione:
- **DEF**: `hl=12.0, range=1.2, opp_sens=29.0, trend=0.7`, SENZA granulari (era hl=9.0/trend=1.3/CON granulari)
- **MID**: `hl=12.0, range=1.4, opp_sens=29.0, trend=0.7`, SENZA granulari (era trend=1.0/CON granulari, resto invariato)
- **FWD**: `hl=12.0, range=1.4, opp_sens=29.0, trend=0.7`, SENZA granulari (numeri invariati, solo granulari rimossi)
- **GK**: INVARIATO (`hl=9.0, range=1.6, opp_sens=20.0, trend=0.7`, senza granulari) — campione
  troppo piccolo (2-3 giocatori) per fidarsi di un'aggregazione pesata, da rivedere quando si avrà
  più storico.

Commit di finalizzazione: `2e9fa0eb`/`f246973e`. Tutto pushato su `origin/main`.

### E. Prossimi passi (in ordine, sostituisce la sezione 3 sopra)

1. **Finding 3+F** dell'audit logico (condizionamento 2D venue+forza avversario invece che
   separati; correlazione tra slot della formazione: bonus sinergia GK+DEF stessa partita,
   penalità anti-sinergia GK vs FWD avversario) — vedi `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`
   sezione 5. C'era un task in background (`task_c858ec41`, lanciato dall'utente in un'altra
   sessione locale) per una proposta di design — **mai verificato se ha prodotto un output**,
   l'utente non sa come controllarlo da qui: chiedere se l'ha trovato, altrimenti si riparte da
   zero su questo tema quando arriva il suo turno.
2. **GK**: ricalibrare quando si avrà un campione più ampio di giocatori con storico sufficiente
   (oggi solo 2-3 qualificati con n_test>=3) — non prioritario, resta backlog.
3. **Backlog di idee più ampio** (26/07, l'utente ha dichiarato "una settimana di tempo per
   implementare e migliorare il modello", da affrontare UNA ALLA VOLTA, scegliendo insieme
   l'approccio prima di implementare — non procedere in autonomia su più fronti):
   - Robustezza statistica del backtest: campioni piccoli per giocatore (vedi punto B sopra),
     possibile cross-validation temporale o bootstrap sui giocatori per capire quanto è stabile
     la "combinazione vincente", split train/validation espliciti.
   - Feature aggiuntive non sfruttate: infortuni/squalifiche imminenti, calendario congestionato
     (rotazione/turnover), modulo tattico (bassa priorità).
   - Gestione outlier/hot-streak non sostenibili: pesare la media storica anche per "affidabilità"
     (numero di presenze recenti, non solo half-life), rilevamento automatico di picchi isolati
     da attenuare (caso Antino Lopez come esempio concreto).
   - Monitoraggio continuo: MAE "live" calcolato in produzione (score_atteso pubblicato vs score
     reale ottenuto), non solo backtest retrospettivo.
   - Estensione dell'infrastruttura (discovery globale + filtro qualità + calibrazione a batch) ad
     altri campionati oltre MLS, come test di generalizzazione.
4. Lavoro indipendente/non correlato in corso su un ALTRO filone (bot di trading
   `bots/bot_definitivo.py`) — vedi sezione 4 sopra, non mischiare.

## 8. Approfondimento robustezza statistica del backtest (26/07, stesso giorno — primo tema del backlog punto 3)

Prima di passare al tema successivo del backlog, l'utente ha voluto approfondire "Robustezza
statistica del backtest" (B+C+D del menu di opzioni proposto, poi anche una quarta iterazione).
MLS è **a circa metà campionato** al momento di scrivere questo — informazione rilevante: il
volume di dati per giocatore crescerà ancora ma non esploderà a breve (al massimo raddoppierà
entro fine stagione), quindi ha senso sfruttare bene i dati attuali con metodi statistici più
prudenti invece di aspettare passivamente più partite.

**B. Bootstrap win-rate** (nuovo script `formazione_mls/calibrazione/bootstrap_stability.py`,
1000 ricampionamenti con sostituzione dei giocatori qualificati, per ruolo): la combinazione
vincente ufficiale vince solo il **17.4% (FWD)**, **32.8% (DEF)**, **19.2% (MID)** dei
ricampionamenti — nessun vincitore netto, con un campione leggermente diverso di giocatori MLS
sarebbe probabilmente uscita una combinazione diversa. Segnale positivo: **`opponent_sensitivity
=29.0` non cambia MAI** nella top-10 di nessun ruolo — è l'unico parametro davvero stabile; le
vere zone di incertezza sono half_life (9 vs 12) e il flag granulari.

**C. Intervallo di confidenza bootstrap 95% sul MAE**: bande larghe per tutti i ruoli (es. FWD
15.84-18.70) — confermano che differenze di 0.1-0.3 MAE tra combinazioni viste durante
l'aggregazione erano dentro il rumore statistico, non un segnale reale.

**D. Sensitivity check su `MIN_TEST_GAMES`** (soglia minima partite di backtest per essere
incluso nell'aggregazione, provata a 3/5/7): la combinazione vincente CAMBIA a seconda della
soglia (es. FWD: trend 0.7→1.3→0.7 a seconda della soglia; DEF: hl 12→9→9) — mai un salto a
parametri assurdi, ma conferma ulteriore che il segnale è debole rispetto al rumore campionario.
Solo un check, nessun artefatto prodotto (i JSON ufficiali erano stati temporaneamente sovrascritti
da questi run di prova e sono stati ripristinati con `git checkout` subito dopo).

**Raccomandazione a media pesata bootstrap** (estensione di `bootstrap_stability.py`, seconda
iterazione): invece di riportare solo il vincitore secco, calcola una media dei parametri numerici
pesata per quante volte ogni combinazione vince nei ricampionamenti — un valore continuo che
riflette l'incertezza invece di un estremo arbitrario della griglia discreta:

| Ruolo | half_life (pesato) | range (pesato) | opp_sens (pesato) | trend (pesato) | granulari nelle vittorie |
|---|---|---|---|---|---|
| FWD | 10.48 | 1.40 | 29.00 | 0.92 | 31.1% (NO prevale) |
| DEF | 10.99 | 1.25 | 28.97 | 0.73 | 29.9% (NO prevale) |
| MID | 11.14 | 1.32 | 28.98 | 0.86 | 32.4% (NO prevale) |

**Perché è una buona notizia**: la percentuale "granulari" è consistentemente intorno al 30% su
tutti e tre i ruoli (non vicina al 50%) — la decisione "senza granulari" già presa non è un
coin-flip casuale, è un segnale debole ma coerente attraverso i ruoli. Gli scarti sui parametri
numerici rispetto ai valori ufficiali fissati sono modesti (half_life ~10.5-11 pesato vs 12.0
ufficiale; trend più alto per MID/FWD, 0.86-0.92 pesato vs 0.70 ufficiale — DEF è il più vicino,
0.73 vs 0.70).

**Decisione presa**: NON cambiare i parametri ufficiali ora (già validati dal caso reale Antino
Lopez/Carles Gil, e comunque nello stesso "vicinato" statistico di questi valori pesati — nessuno
scarto scioccante). Questi numeri servono come **riferimento per il prossimo giro di
ricalibrazione** a stagione più avanzata: se il vincitore secco del prossimo grid search si
avvicinerà a questi valori pesati, sapremo che la stima si è stabilizzata; se diverge molto,
sapremo che il segnale è ancora debole anche con più dati.

**Tema chiuso**. Prossimo tema dal backlog (sezione 7E sopra), da scegliere con l'utente uno alla
volta: condizionamento 2D venue+avversario/correlazione slot formazione (il più maturo ma da
ridisegnare da zero, task in background non recuperabile), feature aggiuntive, gestione
outlier/hot-streak, monitoraggio MAE live, estensione ad altri campionati.

## 9. Allargamento soglia qualità calibrazione + scoperta `level_score` (26/07, notte)

Emerso dal tema robustezza statistica: il vero collo di bottiglia è il numero totale di partite
disponibili (37-68 giocatori/255-517 partite per ruolo dopo il filtro qualità=30 + n_test>=3). Il
filtro qualità serve alla PRODUZIONE (non suggerire giocatori scarsi), non alla calibrazione (che
cerca parametri strutturali della formula) — deciso di abbassarlo **solo per la calibrazione** a
**15** (via `min_avg_score_quality` del workflow, produzione invariata a 30).

**Fix preventivo**: `grid_search_calibrazione.yml` ora esclude i giocatori con un `grid.json` già
presente prima di applicare batch_index/batch_size — permette di riabbassare la soglia e
processare SOLO i giocatori nuovi, senza rifare query/job sui già analizzati.

**Lanciati batch per tutti e 4 i ruoli** (autorizzato esplicitamente dall'utente per l'esecuzione
notturna, incluso l'eventuale lancio di batch residui senza chiedere conferma). **Attenzione
rate-limit gestita**: lanciare i 4 ruoli in PARALLELO avrebbe significato fino a 32 job CI
contemporanei sullo stesso account Sorare (4 ruoli x max 8 worker) — rischio concreto di 429
condiviso (incidente reale già documentato in passato). Cancellati i run DEF/MID/FWD lanciati in
parallelo (erano ancora in fase discover_batch, nessuna query pesante fatta) e rilanciati **in
sequenza, uno alla volta** (GK→DEF→MID→FWD), tramite uno script di orchestrazione bash in
background. Tutti e 4 completati con successo, nessun batch residuo necessario (pool
completamente coperto in un solo batch per ruolo).

Risultati (aggregazione pesata per n_test, min 3 partite):

| Ruolo | Qualificati (soglia 15) | Con n_test>=3 | Combinazione vincente | MAE | Bootstrap win-rate |
|---|---|---|---|---|---|
| GK | 29 (+2 vs soglia 30) | 13 (+10) | hl=9.0, range=1.4, opp_sens=29.0, trend=0.7, NO granulari | 18.96 | 12.2% (debole) |
| DEF | 197 (+41) | 69 (+1) | hl=12.0, range=1.2, opp_sens=29.0, trend=0.7, NO granulari | 16.39 | 34.0% (incerta, la più solida) |
| MID | 183 (+27) | 68 (+3) | hl=12.0, range=1.2, opp_sens=29.0, trend=0.7, NO granulari | 15.30 | 19.6% (debole) |
| FWD | 157 (+18) | 38 (+1) | hl=9.0, range=1.4, opp_sens=29.0, trend=0.7, NO granulari | 17.44 | 14.5% (debole) |

**Lezione onesta**: raddoppiare/ampliare il pool di giocatori per DEF/MID/FWD NON ha migliorato
sostanzialmente il win-rate bootstrap (era 17-33%, ora 14-34%) — il problema non è "poca varietà
di giocatori", è che le combinazioni vicine sono genuinamente statisticamente equivalenti con
questo volume di partite per giocatore (limitato dalla metà campionato MLS). Servirà aspettare
che la stagione avanzi (più partite a testa), non solo più giocatori. `opponent_sensitivity`
resta l'UNICO parametro sempre stabile (~29.0 ovunque, incluso ora GK). Non applicato alla
produzione (nessuna decisione presa stanotte, solo dati raccolti per la prossima sessione).

### Scoperta importante: il peso reale dei granulari (approfondimento richiesto dall'utente)

L'utente ha notato (da screenshot Sorare reali di Andre Blake) che alcune categorie di punteggio
sembravano pesare molto più di altre. Creato `formazione_mls/diagnostics/inspect_granular_weights.py`
(diagnostico locale, legge solo le cache `.cache/*_detail_cache.json` già scaricate, nessuna
nuova query) per misurare il peso reale di ogni gruppo granulare sul movimento assoluto del
punteggio, su TUTTE le partite disponibili (non a campione a mano).

**Scoperta principale**: il campo `level_score` (category=UNKNOWN nel detailedScore, legato al
bonus clean sheet per il portiere: ~35 se ha subito gol nei primi 60', ~60 se clean sheet) **non è
incluso in NESSUNO dei gruppi granulari tracciati, in NESSUN ruolo** — e vale da solo la quota più
grande del punteggio ovunque: **56,2% GK, 40,9% DEF, 48,8% MID, 62,8% FWD** (migliaia di partite
reali analizzate). **Nota importante segnalata dall'utente**: `level_score` ha una base FISSA di
35 assegnata a chiunque scenda in campo anche un secondo — quindi il peso misurato è gonfiato da
questa componente fissa non predicibile; la vera leva sfruttabile è probabilmente più piccola e
riconducibile a poche soglie discrete (ha giocato/clean sheet), non un continuo — da scorporare
prima di investire tempo nel modellarlo.

**Altra scoperta utile**: la categoria **"Eventi rari" vale 0,0-0,1% su TUTTI e 4 i ruoli**
(candidato sicuro per la rimozione dal codice, zero rischio). Il resto dei gruppi ha un mix
sensato per ruolo (Duelli domina per DEF/MID/FWD 17-23%, Efficacia offensiva cresce avvicinandosi
all'attacco 0%→2%→5%→9%, Gol subiti si riduce allontanandosi dalla difesa 11%→6%→3%→assente).

**Non implementato stasera** (solo diagnosticato): rimuovere le categorie a peso zero, scorporare
la base fissa di `level_score` per misurarne la vera varianza sfruttabile, eventualmente
progettare un modo di condizionare `level_score`/clean-sheet-proneness per venue/avversario.
Priorità identificata per il prossimo giro sul tema granulari.

## 10. Mattina 26/07 — Punto 1 (rimozione categorie a peso zero) e Punto 2 (scomposizione level_score)

### Punto 1: categorie a peso zero rimosse dal codice

Rimosso da tutti e 4 gli script `test_<ruolo>.py`, basato sui dati di `inspect_granular_weights.py`:
- **GK**: `FOULS_STATS`, `OFFENSIVE_STATS`, `RARE_EVENTS_STATS` (tutti 0.0% su 268 partite/29
  portieri). Erano già solo diagnostici (mai in `score_atteso`), quindi il comportamento REALE del
  modello è invariato — solo pulizia di codice/output/computazione.
- **DEF/MID/FWD**: rimosso solo `RARE_EVENTS_STATS` (0.0-0.1% su 857-1534 partite). Contribuiva
  ancora al calcolo del residuo (`covered_total`), impatto trascurabile viste le dimensioni.

Verificato con `py_compile` + smoke test sintetico (`rigorous_backtest`/`run_grid_search` con dati
finti) su tutti e 4 gli script, nessun errore. Committato e pushato (`e926f208`/`f145fa82`).

### Punto 2: scomposizione della base fissa di `level_score`

Investigazione sulla distribuzione reale di `level_score` (non solo la sua magnitudine media, come
richiesto). Risultato importante: **`level_score` NON è continuo in nessun ruolo** — è quantizzato
su soli 5-6 valori distinti in tutti e 4 i ruoli:
- **GK** (268 partite): 35 (68%), 60 (25%), 15 (5.6%), 5 (0.7%), 70 (0.4%)
- **DEF** (1534 partite): 35 (84%), 60 (11%), 15 (4.2%), 70 (0.8%), 5 (0.1%)
- **MID** (1459 partite): 35 (76%), 60 (18%), 70 (3.4%), 15 (2.5%), 80 (0.3%), 100 (0.1%)
- **FWD** (915 partite): 35 (65%), 60 (28%), 70 (5.0%), 80 (1.2%), 15 (1.1%), 90 (0.1%)

Il valore 35 domina sempre — conferma la nota dell'utente sulla "base fissa". Cross-tabulazione con
`mins_played`/`goals_conceded`/`clean_sheet_60`/`goals` per capire cosa determina i livelli
superiori: **la regola NON è la stessa per tutti i ruoli** e non è pulita/deterministica dai soli
3-4 campi controllati:
- GK: livello 60 non è spiegato SOLO dal flag clean sheet (trovati casi di livello 60 con gol
  subiti) — più sporco del previsto, probabilmente altri fattori Sorare non documentati.
- DEF: sorpresa — il salto a livello 60 correla molto più con **aver segnato un gol** (36% dei
  casi a livello 60 vs 0.2% a livello 35) che con il clean sheet (24.3% vs 27.0%, quasi
  indifferente). Per un difensore, `level_score` sembra premiare soprattutto contributi decisivi
  offensivi, non la fase difensiva.

**Conclusione**: `level_score` è il sistema di bonus "contributo decisivo" di Sorare (probabilmente
lo stesso mostrato come "Punteggio decisivo" nella UI) — una variabile CATEGORIALE legata a eventi
rari e decisivi (gol, clean sheet, assist), non un valore da normalizzare per casa/trasferta con
`compute_split_factor` come gli altri granulari. Punto 2 considerato chiuso per stasera (obiettivo
raggiunto: sappiamo che non è rumore, sappiamo che è quantizzato, sappiamo grosso modo cosa lo
muove) — la regola esatta servirebbe più tempo/dati ed è naturalmente collegata al tema successivo
(la sinergia GK+DEF per il clean sheet condiviso, i contributi decisivi dei compagni di squadra
nella stessa partita, sono esattamente il tipo di correlazione tra slot che il Finding 4/F della
sezione 5 di `RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` intendeva modellare). Non implementato,
solo diagnosticato — nessuna modifica al codice di produzione per questo punto.

## 11. Mattina 26/07 (continua) — REGOLA ESATTA di `level_score` scoperta e validata dall'utente su Sorare

Approfondimento richiesto dall'utente (partendo dagli attaccanti, poi da estendere a tutti i
ruoli): mappata ogni combinazione di stat `POSITIVE_DECISIVE_STAT`/`NEGATIVE_DECISIVE_STAT` (che
hanno SEMPRE `totalScore=0.0` come riga propria — il loro impatto reale è tutto dentro
`level_score`, non nella riga della singola statistica) contro il valore di `level_score`
risultante, su tutte le partite in cache di tutti e 4 i ruoli.

**Regola CORRETTA E FINALE** (prima versione ipotizzata "primo evento/eventi successivi in ordine
cronologico" era sbagliata — corretta dall'utente il 26/07 con controesempi reali GK: la vera
chiave e' il CONTEGGIO NETTO di eventi decisivi, sommando i valori se un evento si ripete, es.
doppietta=2 gol):
```
netto = sum(statValue di tutte le righe POSITIVE_DECISIVE_STAT)
      - sum(statValue di tutte le righe NEGATIVE_DECISIVE_STAT)

netto -2 -> level_score  5
netto -1 -> level_score 15
netto  0 -> level_score 35  (base)
netto +1 -> level_score 60
netto +2 -> level_score 70
netto +3 -> level_score 80
netto +4 -> level_score 90
netto +5 -> level_score 100
```
Il salto dal centro (35) al primo scalino e' piu' grande (+-25) di ogni scalino successivo
(+-10) -- ma la funzione dipende dal CONTEGGIO NETTO, non dall'ordine temporale in cui gli eventi
sono avvenuti in partita (un gol e un errore-che-porta-a-un-gol nella stessa partita si annullano
esattamente: netto 1-1=0 -> resta a 35, indipendentemente da quale dei due sia successo prima).

**Validato dall'utente con schermate Sorare reali** (non solo dedotto dai dati):
1. Aaron Salem Boupendza Pozzi (2 gol + 1 assist, Zhejiang Greentown vs Sichuan FC, 01/04/2025):
   score 91.9 = level_score 80 (35 + 25 primo gol + 10 secondo gol + 10 assist) + granulari 11.9
   (screenshot UI: Generale -1.5, Possesso -6, Passaggio 7.4, In attacco 12 = 11.9). Conferma
   ESATTA sia della formula di level_score sia che score_totale = level_score + somma granulari.
2. Denis Bouanga (1 gol + 1 errore-che-porta-a-un-gol, San Diego FC vs Los Angeles FC, 03/05/2026):
   `level_score`=35 (netto). Screenshot UI mostra la sezione "Punteggio decisivo" come un GAUGE a
   scala di EVENTI (non punti diretti): "Positivo decisivo: 1 (Gol)", "Negativo decisivo: -1
   (Errore che ha causato un gol)" → netto 0 sulla scala eventi → livello resta a 35. "Punteggio
   complessivo" (i granulari): -9.9. Totale reale: 35 + (-9.9) = 25.1, esatto.
3. Antony Alves Santos (1 `penalty_conceded`, Vancouver Whitecaps vs Portland Timbers,
   05/04/2026): `level_score`=15 (35-20), coerente con la regola per un singolo evento negativo.
4. Andre Blake (GK, clean sheet netto, Philadelphia Union vs DC United, 18/04/2026):
   `level_score`=60, confermato dall'utente -- la regola vale identica anche per il portiere
   (clean_sheet_60 conta come 1 evento positivo netto).
5. Michael Collodi (GK, `last_man_tackle`+`penalty_save`, Seattle Sounders vs FC Dallas,
   26/04/2026): `level_score`=70 (netto +2: 35+25+10). Confermato dall'utente: "su Sorare il
   level_score si chiama Punteggio decisivo... con un clean sheet in piu' sarebbe stato 80". Al
   decisivo 70 si sommano granulari +16 per il totale reale 86.1.
6. Pablo Sisniega (GK, `own_goals`+`red_card`, San Diego FC vs Vancouver Whitecaps, 30/11/2025):
   `level_score`=5 (netto -2: 35-20-10). Confermato dall'utente, granulari -3.6 portano il
   punteggio totale reale a 1.4 ("che partita di merda che ha fatto").
7. Akil Watts (DEF, 1 gol, Portland Timbers vs St. Louis City SC, 08/06/2025, MLS):
   `level_score`=60, granulari +17.6, score reale 77.56. Confermato dall'utente.
8. Ajani Fortune (MID, 1 gol, Orlando City SC vs Atlanta United, 16/05/2026, MLS):
   `level_score`=60, granulari +20.8, score reale 80.8. Confermato dall'utente.

**REGOLA VALIDATA SU TUTTI E 4 I RUOLI** (GK, DEF, MID, FWD) con casi reali confrontati su Sorare
dall'utente — nessuna differenza di meccanismo tra ruoli, stessa tabella netto→livello ovunque.
Chiarimento importante dell'utente sul floor: **`goals_conceded` (gol subiti) NON è mai un evento
decisivo negativo per il portiere** — è una statistica GENERAL separata. Se un portiere ha un
evento decisivo positivo (es. rigore parato) ma subisce molti gol, il floor tiene comunque il
punteggio al livello raggiunto (es. 60), indipendentemente da quanti gol subisce — questo spiega
retroattivamente i casi "sporchi" trovati nella prima cross-tabulazione di stamattina (livello 60
con fino a 6 gol subiti: non erano un'anomalia della regola, erano il floor in azione).

**Tema level_score chiuso.** Prossimo passo naturale: usare questa comprensione per stimare un
`level_score` atteso per la prossima partita (basato sul tasso storico di eventi decisivi del
giocatore) invece di lasciarlo dentro la media generica — da progettare insieme quando si riprende
il lavoro implementativo.

**Scoperta importante collegata**: `level_score` NON e' quindi un misterioso "black box Sorare" --
è letteralmente il "**Punteggio decisivo**" mostrato nella UI (gauge -3..+5 con soglie
0/15/35/60/70/80/90/100), un contatore di EVENTI decisivi (non punti) che poi si traduce in un
valore di livello secondo tabella fissa. Il "Punteggio complessivo" della UI corrisponde
esattamente alla somma dei nostri gruppi granulari (Generale/Possesso/Passaggio/In
attacco/Difesa). `score_totale = level_score (Punteggio decisivo) + somma_granulari (Punteggio
complessivo)` -- confermato aritmeticamente su piu' casi reali.

**Implicazione per il modello**: la vera leva sfruttabile non è "normalizzare level_score per
casa/trasferta" (era l'approccio sbagliato, level_score non è un valore continuo con una media
mobile sensata) — è stimare la **probabilità storica di ciascun evento decisivo per il giocatore**
(tasso gol/partita, tasso assist, tasso cartellino, tasso clean sheet per GK/DEF) e usarla per
calcolare un valore atteso di `level_score` per la prossima partita, anziché lasciarlo
implicitamente dentro la media pesata generica dello score totale (dove il rumore degli eventi
rari lo confonde con le fluttuazioni "normali" di gioco). Non ancora implementato — prossimo passo
naturale, da fare per tutti e 4 i ruoli (richiesta esplicita dell'utente: "dobbiamo farlo anche
sugli altri ruoli").

### Regola del FLOOR (segnalata dall'utente con caso reale Erling Haaland, 26/07)

Scoperta aggiuntiva importante, verificata sui dati cache: **quando `level_score >= 60` (almeno un
evento decisivo positivo netto, nessun negativo che lo compensi), il punteggio finale della
partita non può MAI scendere sotto `level_score` stesso**, indipendentemente da quanto siano
negativi i granulari. Caso che ha innescato la scoperta: Erling Haaland (Arsenal 5 - Manchester
City 1), 1 gol, granulari -3 → punteggio atteso "sulla carta" 57, ma il punteggio FINALE reale
mostrato da Sorare è 60 (il floor).

**Verificato empiricamente sui nostri dati** (non solo dedotto dallo screenshot):
- 5 casi reali con `level_score >= 60` e granulari negativi, su FWD/DEF/MID/GK: **in tutti e 5** lo
  `score` reale restituito dall'API Sorare corrisponde ESATTAMENTE a `level_score` (floor attivo),
  mai alla somma grezza più bassa.
- 8 casi reali con `level_score = 35` (nessun decisivo positivo pulito) e granulari molto negativi:
  **in tutti e 8** lo `score` reale è la somma grezza (`level_score + granulari`), SENZA floor —
  scende liberamente sotto 35.

**Regola completa e finale**:
```
score_totale = level_score + granulari                         se level_score <= 35 (nessun floor)
score_totale = MAX(level_score, level_score + granulari)        se level_score >= 60 (floor attivo)
```

**Implicazione pratica**: un evento decisivo positivo funziona come una specie di "assicurazione"
sul punteggio — garantisce un pavimento (60/70/80...) indipendentemente da una brutta prestazione
generale nella stessa partita. Questo significa che il valore atteso di "probabilità di un evento
decisivo" per un giocatore non è solo il suo contributo medio ai punti, ma include anche una
riduzione del rischio al ribasso — rilevante per qualunque futura stima predittiva di
`level_score`, non solo per calcolarne il valore medio atteso ma anche per il range di confidenza
(varianza ridotta sul lato basso quando il giocatore ha buone probabilità di un evento decisivo).

## 12. Sera 26/07/2026 — rimozione `fattore_forza_avversario`, GK, monitoraggio MAE live, bilanciamento anti-stack

Sessione successiva a quella descritta in sezione 11, stesso giorno. In ordine:

**Rimosso `fattore_forza_avversario` da `score_atteso` per tutti e 4 i ruoli, MLS e K League**
(commit `c7a4b831a`). Backtest walk-forward rigoroso
(`formazione_mls/diagnostics/validate_team_defense_strength.py`) ha mostrato che questo fattore
(basato su `domesticLeagueRanking`, generico offesa+difesa) PEGGIORA il MAE del 4-9% su tutti i
ruoli — testata anche un'alternativa più specifica (gol subiti per squadra, ricostruita a costo
zero dalle cache esistenti di GK/DEF/MID): batte comunque la rimozione secca, tranne un margine
minimo per GK non ritenuto sufficiente a giustificare nuove query GraphQL in produzione. Il
fattore resta calcolato e mostrato in output per diagnostica, solo non più moltiplicato.
`HALF_LIFE_GAMES` e `fattore_casa_trasferta` sono stati ri-validati con lo stesso rigore
(`validate_halflife_venue.py`): entrambi confermati validi per tutti i ruoli (delta <0.5%),
nessuna modifica necessaria.

**GK: tutti i parametri tunabili confermati vicini all'ottimo, nessuna modifica necessaria.**
Oltre a Stadio D (già rimosso in sessione precedente, +4.21% MAE se tenuto) e all'avversario
(sopra), validato anche `TREND_INTENSITY` (mai testato prima,
`formazione_mls/diagnostics/validate_gk_trend.py`): 0.7 è quasi ottimale (alternativa migliore
-0.08%, rumore), disattivare il trend costa +1.46%. Il problema residuo di GK non è di formula ma
di dati: campione di calibrazione ancora piccolo (15 giocatori/129 punti test contro 72-178/311-616
degli altri ruoli) — non ha mai avuto la "calibrazione allargata" che hanno avuto DEF/MID/FWD.
Backlog aperto, rimandato.

**Testata e SCARTATA la decomposizione level_score/granulare** (esito negativo,
`formazione_mls/diagnostics/validate_level_score_decomposition.py`): l'ipotesi era prevedere lo
score totale scomponendo `level_score_atteso + granulare_atteso` con half_life/trend PROPRI per
ciascun pezzo, invece della media pesata unica sul totale in produzione. Grid search walk-forward
(8281 combinazioni per ruolo) mostra guadagni marginali e probabilmente rumore (<1.3% su tutti i
ruoli), con ottimi spesso al bordo della griglia (sintomo di overfitting); il test più onesto
(decomposizione SENZA ri-tarare nulla) è nullo o leggermente peggiore in 3 ruoli su 4. Non portata
in produzione.

**Aggiunto monitoraggio MAE live per MLS** (commit `9860c99ff`, implementato da un agente in
background): ogni run di produzione dei 4 ruoli MLS ora registra (`formazione_mls/predict/
live_prediction_log.py`) uno "pending log" JSON per giocatore/partita target con lo `score_atteso`
generato; un nuovo script (`formazione_mls/diagnostics/resolve_live_predictions.py`) confronta
poi queste previsioni con lo score reale non appena la cache si aggiorna con la partita giocata,
calcola l'errore e produce un report di MAE live per ruolo (totale e ultime N partite, per
individuare drift). Zero nuove query API, overhead trascurabile, nessuna modifica alla formula.
Scope solo MLS per ora (K League può seguire).

**Meccaniche di gioco Sorare chiarite dall'utente (fondamentali, non derivabili dal codice)**:
- **In Season**: contro un target fisso di Sorare, non contro altri manager.
- **Arena**: 5 giocatori (anche tutti classic), 1 formazione contro altri 9 manager, premiati i
  primi 3. **Capitano Arena: bonus +20%, NON +50%** — il codice usa ancora `CAPTAIN_BONUS = 0.5`
  globale per tutti i tipi di formazione (bug noto, non ancora corretto).
- **All Stars**: stesso meccanismo di Arena ma su scala globale (~20.000 partecipanti, premiati i
  primi 1000 — taglio 5%, molto più estremo del 30% di Arena).
- **Bonus anti-stack (SOLO In Season)**: formazione con MENO di 3 giocatori della stessa squadra →
  +2% al punteggio di ciascuno dei 5; con 3+ della stessa squadra il bonus salta per tutti.
  Non esiste in Arena/All Stars.
- **Bonus "cap 260" (SOLO In Season e All Stars, NON Arena)**: menzionato dall'utente ma non ancora
  approfondito — probabilmente imparentato con (ma non identico a) l'`ARENA_L10_CAP` già
  implementato per Arena. Da chiarire in una prossima sessione.

**Fix implementato: bilanciamento sinergia GK-DEF con bonus anti-stack** (commit `e658958ab`,
MLS+K League). Contesto: `build_formazione_finale.py` aveva già una sinergia GK+DEF (aggiunta in
sessione precedente per la correlazione clean sheet: schierare il DEF della stessa squadra del GK
è leggermente incoraggiato) scritta PRIMA di sapere del bonus anti-stack. Analisi: quella sinergia
da sola porta al massimo a 2 giocatori della stessa squadra (GK + 1 DEF titolare) — nessun
conflitto col bonus anti-stack (soglia 3), lasciata invariata. Il conflitto nasce solo nello slot
EXTRA, dove la stessa sinergia poteva spingere verso il 3° giocatore della squadra del GK, perdendo
il 2% certo su tutti e 5 per un guadagno di correlazione incerto. Aggiunto `apply_stack_guard`
(parametro nuovo di `build_one_lineup`, attivo SOLO per `tipo == 'IN_SEASON'`): nello slot extra,
un candidato che farebbe salire una squadra a 3+ viene fortemente deprioritizzato nell'ordine di
scelta — MAI escluso (se non ci sono alternative valide resta comunque selezionabile: a volte,
es. capolista contro ultima, può convenire sacrificare il 2% per un punteggio quasi certo, scelta
che resta dell'utente, non dell'algoritmo). Se una formazione finisce comunque con 3+ della stessa
squadra, viene segnalato chiaramente in output (testo e HTML: "bonus anti-stack NON applicato").
Arena/All Stars non toccate (nessun bonus anti-stack lì). Verificato con test locale (candidati
fittizi): il guard evita il 3° giocatore quando esiste un'alternativa valida, e ripiega sullo
stack solo quando non ce ne sono (segnalandolo).

**Backlog aperto a fine sessione (12)**:
1. GK: calibrazione allargata (discovery su tutti i portieri MLS qualificati) — rimandato.
2. K League: infrastruttura discovery globale equivalente a MLS, per ripetere le analisi
   cross-league (Stadio D, avversario, ecc.) e confrontare pattern universali vs specifici MLS.
3. Verificare empiricamente se la correlazione reale tra compagni di squadra nei dati giustifica di
   spingere DI PIÙ sullo stacking in Arena/All Stars (specialmente All Stars, taglio 5%).
4. Correggere `CAPTAIN_BONUS` per essere specifico per tipo (Arena 20% vs In Season/All Stars —
   valore per questi ultimi due mai verificato esplicitamente con l'utente, assunto 50% finora).
5. Chiarire e implementare il bonus "cap 260".
6. Outlier/hot-streak (mai affrontato), monitoraggio MAE live esteso a K League.

## 13. Sera 26/07/2026 (continua, sessione successiva) — Arena/All Stars bonus reali, K League discovery+calibrazione globale, calibrazione GLOBALE unificata

Sessione lunga, molti filoni gestiti in parallelo con agenti in background (worktree isolati,
mergiati man mano in questa sessione). In ordine logico (non cronologico):

### A. Punto 3 e 4 del backlog sopra: CHIUSI
- Punto 3 (stacking Arena/All Stars): **eliminato dal backlog** su richiesta esplicita
  dell'utente — troppo sforzo per il beneficio atteso.
- Punto 4 (`CAPTAIN_BONUS` per tipo): implementato. `CAPTAIN_BONUS_BY_TYPE` per tipo di
  formazione: In Season 50%, Arena 20% (verificato dall'utente su casi reali Sorare),
  All Stars 50%. **Bug trovato e corretto in K League**: dopo lo split di Arena in
  ARENA_260/ARENA_220/ARENA_UNCAPPED (vedi sotto), la mappa K League aveva ancora la vecchia
  chiave singola `'ARENA': 0.2` — le nuove chiavi ricadevano sul default 50% invece di 20%.
  Bug reale, non solo teorico (avrebbe sballato i totali mostrati per Arena K League).

### B. Bonus formazione reali Sorare (verificati dall'utente con screenshot UI, non dedotti)

Panel "BONUS FORMAZIONE" della UI Sorare mostra due componenti separate, sommate in un totale:
- **"Multi-club" +2%**: e' lo stesso bonus che chiamavamo "anti-stack" (meno di 3 giocatori della
  stessa squadra), solo nome diverso in UI. Nessuna nuova meccanica, gia' implementato.
- **"Cap 260" +4%**: se la somma delle **L10** (non punteggio atteso/reale) dei titolari e'
  <= soglia, +4% su tutte le carte. **Soglia diversa per tipo**: 260 per In Season, **370 per
  All Stars** (scalata a 7 giocatori invece di 5). E' un **soft cap** — si puo' sforare, si perde
  solo il bonus (mai un vincolo che filtra le scelte). Implementato come rilevamento PASSIVO
  (`check_cap260` in `format_lineup`/`render_lineup_html`): mostra se la formazione gia' scelta
  (ottimizzata per punteggio atteso, nessuna ricerca vincolata) rientra o no, nessuna modifica
  alla selezione dei giocatori. Sia il bonus multi-club sia il cap sono confermati validi ANCHE
  per All Stars (`stack_guard` esteso da `tipo == 'IN_SEASON'` a
  `tipo in ('IN_SEASON', 'ALLSTARS')`), non solo In Season come si pensava prima.

**IMPORTANTE — da non confondere**: il cap Arena (`ARENA_260`/`ARENA_220`) e' un concetto
DIVERSO, anche se sulla stessa metrica (somma L10): per Arena e' un **vincolo di formato
obbligatorio** (non si puo' sforare, filtra attivamente le scelte in `build_one_lineup` via
`FIXED_L10_CAP_BY_TYPE`), non un bonus opzionale. L'utente gioca sempre Arena a cap fisso, ma
alcune Arene usano 260, altre 220 — da qui lo split in tre tipi:

- **`ARENA_260`** / **`ARENA_220`**: cap L10 obbligatorio, vincolante.
- **`ARENA_UNCAPPED`**: nessun limite (terza modalita' Arena reale, richiesta dall'utente).

Sostituito il vecchio tipo generico `'ARENA'` (con tuning opzionale `ARENA_L10_CAP` via env) con
queste tre chiavi fisse in `FORMATION_SHAPES`. Priorita' di generazione: In Season -> Arena
cap260 -> Arena cap220 -> Arena uncapped -> All Stars. Implementato prima su MLS, poi
specchiato su K League (con il fix del bug capitano di cui sopra).

**Verificato sul backtest ("simulate_cap260_tradeoff.py", nuovo script diagnostico)**: rincorrere
attivamente il cap 260 In Season sacrificando punteggio atteso NON conviene quasi mai nel pool
testato — sacrificio medio ~47pt contro un break-even teorico di ~12pt (4% del capped), 0/8
giornate simulate sono riuscite a scendere sotto 260 con giocatori "buoni". Il bonus resta quindi
solo un extra "gratis" quando capita, non un obiettivo da inseguire attivamente (rilevamento
passivo confermato come scelta giusta, non serve una Fase 2 di ricerca attiva).

### C. K League: discovery globale + calibrazione allargata COMPLETA (prima volta)

Costruita da zero l'infrastruttura mai esistita (verificato su TUTTI i branch/commit del repo,
l'utente pensava fosse gia' stata fatta ma si sbagliava): `formazione_kleague/discovery/
kleague_<ruolo>_discovery_global.py` x4 (clone esatto del pattern MLS) + workflow
`.github/workflows/kleague_discovery_global.yml`. Squadre K League 1 ottenute con query LIVE
verificata (`competition(slug:"k-league-1") { clubs }`, 12/12 trovate — nota tecnica: il campo
giusto e' `clubs`, non `teams`/`currentClubs` che falliscono). Poi costruito anche
`grid_search_calibrazione_kleague.yml` (clone del workflow MLS) e generalizzato
`aggregate_grid_search.py` con `CAMPIONATO=mls|kleague` (default mls, retrocompatibile).

Lanciati in sequenza (stessa cautela rate-limit di sempre, un ruolo alla volta) tutti e 4 i batch
K League. Risultati calibrazione K League (solo, min 3 partite test):

| Ruolo | Giocatori qualificati | Vincitore K League | vs produzione (clonata da MLS) |
|---|---|---|---|
| GK | 3/27 | hl=9.0, range=1.2, opp_sens=29.0, trend=0.7 | Campione troppo piccolo da solo, ma stessa direzione di MLS |
| DEF | 15/114 | hl=12.0, range=1.2, **opp_sens=20.0**, trend=0.7 | **Diverge**: unico caso su 8 ruoli/campionati con segnale opposto a 29.0 |
| MID | 10/61 | hl=12.0, range=1.4, opp_sens=29.0, trend=0.7 | Identico |
| FWD | 21/138 | hl=12.0, range=1.4, opp_sens=29.0, trend=0.7 | Identico |

**Il caso DEF K League**: spiegato dall'utente con conoscenza di dominio ("il campionato coreano
e' famoso per difensori molto forti, pochi gol segnati, e' una loro caratteristica nota") — non
rumore, ma un vero effetto di contesto. **Deciso di NON creare un parametro diverso per K League**
(andrebbe contro il principio "un solo modello globale, i campionati servono solo ad accumulare
dati") — vedi punto E per la direzione scelta invece.

Aggiornato **solo GK**: `opponent_sensitivity` 20.0 -> 29.0, sia MLS che K League (stesso fix,
stesso giorno, coerente con tutti gli altri ruoli/campionati). MID/FWD gia' allineati. DEF NON
toccato (vedi sopra).

### D. Calibrazione GLOBALE unificata (MLS+K League combinati, non piu' separati)

Richiesta esplicita dell'utente: "il modello sara' sempre uno solo, globale, usiamo i vari
campionati solo per accumulare dati". Aggiunta modalita' `GLOBALE=1` ad
`aggregate_grid_search.py`: combina i giocatori qualificati di TUTTI i campionati noti in un
unico pool pesato per n_test (un giocatore K League pesa esattamente come uno MLS a parita' di
partite testate), invece di due aggregazioni separate. Output in
`calibrazione_globale/output/<ruolo>_calibration/` (nuova cartella dedicata).

Risultati (nessuna modifica di produzione applicata oltre al fix GK di sopra):
- **GK** (16 giocatori/140 partite) e **DEF** (84 giocatori/640 partite, campione ORA grande):
  confermano che la produzione attuale e' gia' vicina all'ottimo. Bonus: l'anomalia DEF K League
  (opp_sens=20) **sparisce** quando si aggregano piu' dati (MLS domina il peso per volume) —
  coerente col fatto che sia un effetto reale ma di scala minore, non abbastanza forte da
  spostare la stima globale pesata.
- **MID** (78/575): il "vincitore" per composite score suggeriva di riaccendere i granulari
  (trend=1.3) — **verificato e SCARTATO**: riordinando per puro MAE (non composite score, che
  include una penalita' di copertura arbitraria), il vincitore vero e' un tris a pari merito
  (range 1.2/1.4/1.6 indifferenti) con `hl=12.0, opp_sens=29.0, trend=0.7, SENZA granulari` —
  **esattamente i parametri di produzione attuali**. Il segnale "granulari" era un artefatto
  della penalita' di copertura nel composite score, non un vero guadagno di accuratezza. MID
  confermato ottimale cosi' com'e'.
- **FWD** (59/400): segnale debole (trend 0.7->1.0), non applicato.

Fix minore contestuale: il riepilogo finale di `aggregate_grid_search.py` ora mostra
esplicitamente CON/SENZA granulari nella riga di stampa (prima l'informazione c'era solo nel
campo `label` del json salvato, non nel testo stampato — ambiguo a colpo d'occhio).

### E. Prossimi passi (in ordine, sessione in corso al momento di scrivere)

Discusse con l'utente due direzioni per "svoltare" il modello, coerenti col principio "un modello
solo, globale":

1. **Fattore ambientale per `opponent_sensitivity`** (invece di costanti fisse per ruolo/lega):
   il caso DEF K League suggerisce che "quanto conta l'avversario" potrebbe dipendere da un
   contesto di punteggio misurabile (es. media gol/partita osservata), non da una costante fissa
   — permetterebbe al modello di restare unico ma adattarsi automaticamente a qualsiasi
   campionato futuro, invece di un valore scelto a mano per lega.
2. **`level_score` atteso**: stimare il tasso storico di eventi decisivi per giocatore (gol/
   assist/cartellini/clean sheet) per calcolare un valore atteso di `level_score` per la
   prossima partita (usando la regola netto->livello validata in sezione 11, floor incluso in
   sezione 11), invece di lasciarlo dentro la media pesata generica dello score totale. Identificato
   da tempo come probabilmente la leva piu' grossa mai sfruttata (formula validata al 100% con
   casi reali Sorare, identica in ogni ruolo/campionato).

Entrambe le analisi sono state avviate in background (agenti separati, worktree isolati) —
risultati in sezione F sotto, stessa sessione, poco dopo.

### F. Risultati delle due direzioni esplorate — ENTRAMBE esito onesto "non procedere per ora"

**Direzione 1 (fattore ambientale per `opponent_sensitivity`)** —
`formazione_mls/diagnostics/validate_environmental_opponent_sensitivity.py`:
- **Scoperta preliminare importante**: `OPPONENT_SENSITIVITY` **non è nemmeno usato nello
  `score_atteso` reale oggi** — verificato nel codice (`test_def.py` e affini): sopravvive solo
  dentro `rigorous_backtest()`/`run_grid_search()` per un MAE diagnostico in log, MAI nel calcolo
  che sceglie/ordina i giocatori (il fattore forza-avversario generico è stato rimosso il 26/07,
  vedi sezione 12). Quindi calibrarne la sensibilità è oggi un esercizio accademico finché non si
  decide di reintrodurre un fattore avversario in qualche forma (che finora ha sempre perso
  contro "nessun aggiustamento", vedi sezione 12).
- Caratterizzazione ambientale: K League ha sì un ambiente di punteggio meno variabile di MLS ma
  di poco (rapporto deviazione standard gol-subiti K/MLS = 0.91) — troppo mite per spiegare lo
  scarto 20.0 vs 29.0 trovato dal grid search isolato su DEF K League (che implicherebbe un
  rapporto ~0.69).
- Backtest walk-forward: **nessuna delle due formule ambientali testate batte la costante fissa
  29.0** in modo significativo, né su MLS né su K League, né su DEF né sul ruolo di controllo MID.
- **Raccomandazione: non procedere.** Il segnale K League DEF (15 giocatori/114 partite) resta
  probabilmente rumore da campione piccolo — non si spiega con la variabilità ambientale
  misurabile e non produce un guadagno di MAE riproducibile.

**Direzione 2 (`level_score` atteso da tasso di eventi decisivi)** —
`formazione_mls/diagnostics/validate_level_score_event_rate.py`:
- Regola netto→level_score (sezione 11) **confermata esatta al 100%** su tutte le partite in
  cache di tutti e 4 i ruoli (es. FWD 599/599, DEF 957/957).
- Approccio (diverso dal tentativo già scartato in sezione 12, che ri-calibrava half_life/trend
  separati): tasso storico di eventi decisivi (modello Poisson pos/neg, stesso `HALF_LIFE_GAMES`
  di produzione, **zero ri-taratura**) → valore atteso della distribuzione categoriale di
  level_score, poi SOSTITUITO (non sommato a fianco) al posto della componente level_score
  implicita nella media generica attuale.
- Risultato: **migliora il MAE totale su tutti e 4 i ruoli** (FWD -0.63%, DEF -1.01%, MID -0.51%,
  GK -1.18%) — direzione consistente, a differenza del tentativo precedente (che peggiorava 3
  ruoli su 4). Il floor (sezione 11) non scatta mai in questa formulazione: opera su un valore
  atteso continuo, non su un evento realizzato — nota aperta se si vuole approfondire.
- **Raccomandazione: segnale più coerente ma ancora troppo piccolo** (sotto l'1.3%, stesso ordine
  di grandezza del "rumore" già visto altrove in questa sessione) **per giustificare la
  complessità aggiuntiva in produzione così com'è.** Varrebbe la pena riprendere in mano solo se
  si trova un modo di rendere operativo il floor (es. sulla coda della distribuzione, non sul
  valore atteso) o si combina con un'altra leva.

**In sintesi per chi riprende da qui**: la sessione del 26/07 ha validato molto (Arena/All Stars
completi, K League ora ha infrastruttura globale pari a MLS, calibrazione GLOBALE unificata) ma
le due idee "grosse" per migliorare ulteriormente l'accuratezza (fattore ambientale, level_score
atteso) sono risultate entrambe segnali reali ma troppo deboli per la produzione — non è un
fallimento della sessione, è un buon controllo di rigore: si è verificato con backtest reali
invece di intuizione, ed entrambe le idee restano documentate/pronte se in futuro emergeranno più
dati o un'angolazione diversa (es. combinarle, o applicarle solo dove il segnale è più forte).

### G. Stato repo a fine sessione (26/07 notte)

Tutto pushato su `origin/main` (nessun lavoro pendente non pushato). File aggiunti/modificati di
rilievo in questa sessione (oltre a quanto già elencato nelle sezioni A-F sopra):
- `formazione_mls/build_formazione_finale.py` / `formazione_kleague/build_formazione_finale.py`
  — Arena split, cap 260/370, bonus capitano per tipo.
- `formazione_kleague/discovery/kleague_*_discovery_global.py` (nuovi) +
  `.github/workflows/kleague_discovery_global.yml` (nuovo).
- `.github/workflows/grid_search_calibrazione_kleague.yml` +
  `grid_search_aggregate_kleague.yml` (nuovi).
- `formazione_mls/calibrazione/aggregate_grid_search.py` — modalità `GLOBALE=1`.
- `calibrazione_globale/output/<ruolo>_calibration/` (nuova cartella, risultati aggregati
  MLS+K League combinati).
- `formazione_mls/predict/test_gk.py` / `formazione_kleague/predict/test_gk.py` —
  `OPPONENT_SENSITIVITY` 20.0→29.0.
- `formazione_mls/diagnostics/` — 6 nuovi script diagnostici (outlier reliability/shrinkage
  x2, simulate_cap260_tradeoff, validate_environmental_opponent_sensitivity,
  validate_level_score_event_rate) — nessuno in produzione, solo analisi.

**Backlog aperto per la prossima sessione** (in ordine di interesse, non di urgenza — nulla è
bloccante):

0. **PROSSIMO TEMA SCELTO DALL'UTENTE (26/07 notte, fine sessione) — correlazione tra gli slot
   della formazione.** Oggi ogni giocatore viene scelto in modo indipendente (il migliore per il
   suo slot/ruolo), a parte una sinergia parziale GK-DEF/GK-vs-FWD-avversario già implementata a
   mano (bonus/penalità euristici, non misurati sui dati — vedi sezione 12,
   `synergy_sort_key`/`synergy_adjusted_rows` in `build_formazione_finale.py`). **Non è mai stato
   misurato quanto REALMENTE correlano i punteggi di compagni di squadra nella stessa partita**
   (es. se un centrocampista fa una partita ottima, l'attaccante della stessa squadra ha più
   probabilità del solito di aver fatto bene anche lui — correlazione positiva reale o
   percepita?). Era già stato segnalato in una sessione precedente come "il tema più maturo ma
   mai chiuso" — un task di design in background era stato lanciato dall'utente in un'altra
   sessione locale e mai recuperato/verificato, quindi si riparte sostanzialmente da zero.
   **Come approcciarlo**: usare le cache di calibrazione già su disco (stesso dato usato da tutti
   gli script `formazione_mls/diagnostics/validate_*.py` di questa sessione) per ricostruire,
   partita per partita, chi ha giocato insieme nella stessa squadra (stesso approccio già usato in
   `validate_team_defense_strength.py` per raggruppare giocatori per squadra/data) e misurare la
   covarianza reale tra gli score di compagni di squadra nella stessa partita (per ruolo/coppia di
   ruoli). Se la correlazione e' misurabile e non trascurabile, valutare se un'ottimizzazione
   congiunta (non piu' greedy indipendente per slot) possa aumentare il punteggio atteso totale o
   ridurne la varianza in modo utile — MA solo dopo aver misurato la correlazione vera sui dati,
   non prima: la sinergia GK-DEF esistente oggi è stata implementata su intuizione, non
   verificata quantitativamente, e potrebbe risultare più debole (o più forte, o diversa) di
   quanto assunto. Approccio consigliato: nessuna modifica alla produzione finché non si ha un
   numero reale di correlazione in mano (stesso rigore walk-forward/backtest di tutti gli altri
   `validate_*.py` di questa sessione).

1. `level_score` atteso: riprendere se si trova un modo di rendere operativo il floor, o se si
   vuole comunque provare il guadagno marginale (-0.5/-1.2% MAE) in produzione nonostante sia
   piccolo — decisione dell'utente, non tecnica.
2. K League: bonus "Multi-club"/"Cap 260-370" mai verificati con screenshot reali K League
   (solo MLS) — probabilmente identici (stessa piattaforma Sorare) ma da confermare se si gioca
   K League attivamente.
3. Il caso "MID vincitore per composite score ≠ vincitore per MAE puro" (sezione D) — l'aggregatore
   usa un composite score con penalità di copertura arbitraria (0.3×|copertura-68%|); potrebbe
   valere la pena rivedere quella penalità/soglia 68% per tutti i ruoli, non solo notarlo caso per
   caso come fatto oggi per MID.
4. GK resta il ruolo con meno dati anche nella calibrazione globale (16 giocatori/140 partite
   contro 59-84 degli altri ruoli) — nessuna azione richiesta ora, solo da tenere presente quando
   si rifà il giro di calibrazione più avanti in stagione.
5. Bonus anti-stack ("Multi-club") — verificare se ha senso spingere DI PIÙ sullo stacking in
   Arena/All Stars: **eliminato dal backlog il 26/07** (troppo sforzo per il beneficio atteso),
   riportato qui solo perché compariva nel backlog precedente — NON riaprirlo senza una richiesta
   esplicita nuova dell'utente.
6. Starter odds come fattore di rischio continuo nello score_atteso (invece di solo filtro
   binario) — proposto e **SCARTATO il 26/07 notte** su richiesta esplicita dell'utente ("è
   marginale"), riportato qui solo per non riproporlo senza una richiesta nuova.

## 14. Sessione 27/07/2026 — correlazione compagni squadra (misurata e tarata), chiusura outlier/composite score, correzione memoria K League

Ripresa da un account diverso. Punto di partenza: il backlog (punto 0 sezione 13) e la memoria
persistente dell'account indicavano diversi temi aperti; **due si sono rivelati falsi allarmi da
memoria non aggiornata** (vedi sezione D sotto) — lezione operativa, non solo di modello.

### A. Correlazione tra slot della formazione — misurata, verificata robusta, tarata SOLO Arena/All Stars

Nuovo script `formazione_mls/diagnostics/measure_teammate_correlation.py`: residuo walk-forward
(reale − baseline media/venue/trend, stesso approccio di `validate_team_defense_strength.py`) di
compagni di squadra nella stessa partita, dalle cache di calibrazione GK/DEF/MID/FWD.

**Risultati same-team** (permutation test 999 shuffle + split-half cronologico, tutti p<0.05 e
segno stabile): GK-DEF **+0.40** (la più forte, già modellata ma sottostimata), DEF-MID +0.27,
GK-MID +0.26, DEF-DEF +0.23. FWD non mostra correlazione same-team significativa con nessun ruolo.

**Cross-team** (GK vs ruolo della squadra avversaria — verifica diretta dell'anti-sinergia già
codificata in `synergy_sort_key`): GK vs MID avversario **-0.20, p=0.036** (validata); GK vs FWD
avversario -0.24 ma p=0.12 (direzione giusta, campione corto).

**Tuning applicato** in `formazione_mls/build_formazione_finale.py` (`variance_mode`, nuove
costanti `GK_DEF_SYNERGY_BONUS_VARIANCE_EXTRA=8`, `TEAMMATE_SYNERGY_BONUS_VARIANCE=5`): bonus
GK-DEF rafforzato (3→11 totali) + nuovi bonus GK-MID/DEF-MID/DEF-DEF, **SOLO per Arena/All Stars**.
Motivazione del confine: in In Season il target è fisso, il valore atteso della somma non dipende
dalla correlazione (Finding 3+F, già chiuso) — spingere la scelta verso compagni correlati
costerebbe EV reale senza beneficio; il beneficio esiste solo dove la varianza conta (taglio
premi Arena 30%/All Stars 5%). Anti-sinergia GK-vs-avversario esistente lasciata invariata (era
già corretta nella direzione). Commit `4193c85ce`.

### B. Outlier/hot-streak (caso Antino Lopez) — CHIUSO, applicato solo per FWD

Due agenti in background hanno finito il lavoro diagnostico mai concluso in sessioni precedenti
(`validate_outlier_shrinkage.py`/`_tiered.py`, scritti il 26/07 ma senza decisione registrata).
Risultato: shrinkage Empirical Bayes (media pesata tirata verso il prior di ruolo, pseudo-count
`k`) migliora il MAE **solo per FWD**, e solo sul segmento a rischio che aveva motivato il tema
(n<8 partite storiche): **-2.9%** a k=5, con n≥8 invariato. DEF: il guadagno cade sul segmento
sbagliato (n≥8, fino a -5.3%, ma n<8 resta a -2%) — segno di rumore/overfitting, non applicato.
MID: <1% ovunque, rumore, non applicato. GK: campione troppo piccolo per decidere.

Applicato in produzione **solo** `formazione_mls/predict/test_mls_fwd_all.py`
(`SHRINK_K_OUTLIER_FWD=5.0`, `MEDIA_RUOLO_FWD_PRIOR=51.86`, k scelto per coerenza con lo
`shrink_k=5.0` già usato altrove in `media_condizionata()`).

### C. Penalità di copertura nel composite score dell'aggregatore — CHIUSO, peso corretto

Il target 68% è fondato (approssima ±1 dev std teorica, coerente con `RANGE_MULTIPLIER`/p16-p84),
ma il peso 0.3 (mai calibrato) faceva scegliere per MID un MAE **+2.72% peggiore** del vero
minimo. Abbassato a **0.1** in `aggregate_grid_search.py` + le 3 varianti per-ruolo — verificato
che con 0.1 il composite score coincide col vincitore per MAE puro su tutti e 4 i ruoli. **Nessun
impatto sui parametri già in produzione** (il vero vincitore MID coincideva già con quanto
schierato), ma corregge il prossimo giro di ricalibrazione. Entrambi B e C nel commit `e4be6571d`.

### D. Lezione operativa: due falsi allarmi da memoria persistente non aggiornata

Proponendo i "prossimi passi", sono stati segnalati come backlog aperti due temi **già chiusi in
sessioni precedenti mai recuperate correttamente**:
1. **"K League: infrastruttura di calibrazione allargata da costruire"** — in realtà completata
   la sera del 26/07 (sezione 13 di questo stesso documento: discovery globale, calibrazione
   allargata su tutti e 4 i ruoli, anomalia DEF K League investigata e chiusa come "non
   procedere"). L'errore: letta solo la memoria persistente (stale, scritta prima che il lavoro
   fosse fatto) e, separatamente, solo l'ultima sezione di backlog di questo documento — MAI la
   sezione 13 di mezzo che conteneva la risposta corretta.
2. **"GK: calibrazione allargata da fare"** — fatta tre volte (sezione 2: 27 giocatori; sezione 9:
   soglia abbassata a 15, 13 con dati sufficienti; sezione 13D: calibrazione globale MLS+K League,
   16 giocatori/140 partite, **conclusione esplicita "produzione già vicina all'ottimo"**). Il
   campione resta piccolo per un limite strutturale (1 GK per squadra), non perché non sia stato
   cercato — la nota di backlog originale diceva di aspettare che la stagione avanzi, non di
   rilanciare la discovery.

**Correzione applicata**: memoria `project_kleague_cross_validation_modello.md` riscritta con lo
stato reale e riferimento a questa sezione; `project_modello_predittivo_formazioni_mls.md`
corretta con nota esplicita dell'errore. **Regola per il futuro** (salvata anche come feedback
generale, non solo per questo repo): quando viene chiesto di "prendere visione del riassunto",
va letto per intero, non solo l'indice di memoria o l'ultima sezione — la memoria persistente può
essere stale rispetto a lavoro fatto in sessioni successive mai recuperate.

### E. Esplorato e ACCANTONATO: rilevare via GraphQL se una carta è bloccata in una lineup attiva

Obiettivo indagato: sapere, tramite query GraphQL, se una carta è già schierata in una formazione
Sorare attiva (per evitare che il tool suggerisca in una run separata — es. Arena dopo In Season —
un giocatore già usato). Scoperto durante l'indagine (con l'utente che incollava risposte
GraphQL reali): `lockedForLeaderboard` (su `ComposeTeamBenchCard`, scoping per singola
classifica/gameweek) e `usedIn`/`concurrentSo5Lineups` (su `Card`) restano `null`/`[]` anche
quando la carta è visibilmente piazzata in uno slot di una formazione ancora in bozza/non
confermata — quindi non affidabili per lo stato "in bozza". La scadenza di una gameweek è
condivisa da tutte le formazioni nello stesso istante (`so5Fixture.endDate`, confermato
dall'utente), quindi la parte "temporale" del problema sarebbe stata semplice; la parte "quali
carte sono bloccate ORA" avrebbe richiesto query aggiuntive per-carta o per-classifica (non
disponibili nella query di discovery esistente, che oggi chiede solo `slug`/`anyPlayer.slug`).
**Costo/complessità non ritenuti utili dall'utente** ("gioco non vale la candela") —
**non implementato, non riproporre senza una richiesta esplicita nuova.**

### F. Stato repo a fine sessione (27/07)

Pushato su `origin/main`: `4193c85ce` (sinergia Arena/All Stars da correlazione misurata +
`measure_teammate_correlation.py`), `e4be6571d` (shrinkage outlier FWD + peso composite score).
Nessun lavoro di codice pendente non committato. Backlog aggiornato:

1. K League: bonus Multi-club/Cap 260-370 mai verificati con screenshot reali K League (solo
   mirrorati da MLS) — richiede l'utente che gioca attivamente K League, non analizzabile da un
   agente.
2. Estensione dell'infrastruttura ad altri campionati oltre MLS/K League — decisione di
   investimento dell'utente, non un'analisi.
3. ~~GK calibrazione allargata~~, ~~outlier/hot-streak~~, ~~composite score~~, ~~correlazione
   compagni squadra~~ — **tutti chiusi in questa sessione o in precedenza** (vedi sezioni A-D
   sopra), non riaprire senza una richiesta esplicita nuova.
4. Rilevamento carte bloccate in lineup Sorare via GraphQL (sezione E) — accantonato per
   complessità/beneficio, non riproporre senza una richiesta esplicita nuova.

## 15. Sessione 27/07/2026 (sera) — Generatore Formazioni: terzo tool, fusione MLS+K League

Ripresa da un account diverso. Richiesta esplicita dell'utente: un TERZO script/workflow che generi
lineup pescando da MLS e K League **insieme**, **senza toccare** `formazione_mls/` e
`formazione_kleague/` (restano intatti, usabili da soli). Sessione lunga con più giri di test reali
su GitHub Actions e correzione di bug trovati sul campo — dettaglio in ordine cronologico perché
ogni bug ha portato al successivo.

### A. Requisiti raccolti (uno alla volta, con l'utente) e progettazione

**6 tipi di formazione** nel nuovo tool:
1. **In Season MLS** — pool solo MLS, 5 titolari, min 4 In Season + max 1 Classic
2. **In Season K League** — identico, pool solo K League
3. **Arena MLS** — pool solo MLS, **cap L10 fisso 260, non scelto dall'utente** (le Arene dedicate
   sono sempre a 260 su Sorare, verificato dall'utente)
4. **Arena K League** — identico, pool solo K League
5. **Arena All Stars** — stesse regole di un'Arena dedicata (5 carte, anche tutte Classic) ma pool
   **misto** MLS+K League, e qui SÌ il cap è scelto dall'utente tra 260/220/uncapped (come fa
   Sorare per questa modalità)
6. **All Stars** — 7 carte, pool misto, cap 370 **soft** (bonus +4% se rispettato, mai un vincolo
   che filtra le scelte)

**Ordine di priorità** (build condiviso, stesso pool di copie via `CardPool`): In Season (MLS poi
K League) → Arena dedicate (MLS poi K League) → Arena All Stars (260→220→uncapped) → All Stars.

**Ottimizzazione job discussa PRIMA di implementare** (tema "un tema alla volta"): il costo
dominante della pipeline produzione è 1 job predict per carta posseduta (checkout+setup ≈20-35s di
overhead contro ~7.5s di calcolo reale) — batching valutato ma rimandato ("partiamo così, se ci
mette troppo modifichiamo"); cache incrementale già esistente (`.game_log_cache`/`.cache`,
committata dai due tool) confermata riusabile senza modifiche.

**Filtro qualità nuovo** (diverso da tutto il resto del progetto): carta ammessa nel pool SOLO se
L5 **e** L10 **e** L40 sono **tutti e tre** ≥35 (AND severo, non media come nel discovery_global di
calibrazione — quello resta a soglia 30 sulla media, invariato). Fallback di sicurezza previsto se
un ruolo/lega resta sguarnito.

**Input configurabili**: niente più un campo numerico per tipo (non scala con nuovi campionati
futuri). Soluzione: 4 campi numerici semplici per i tipi sempre "misti" (Arena All Stars ×3 cap +
All Stars, non cresceranno mai con nuovi campionati) + 2 campi testo brevi `lega:quantità` solo per
i tipi legati a una lega specifica (`in_season`, `arena_dedicata`, es. `"mls:4,kleague:1"`) — un
domani un nuovo campionato è solo un nuovo codice lega nella stessa stringa, zero nuovi campi nel
workflow.

### B. Implementazione: `generatore_formazioni/` (nuova cartella, nulla toccato nei due tool)

- `generatore_formazioni/build_formazione_globale.py` — script di fusione. **Riusa per import**
  (via `importlib`, nessuna duplicazione) le funzioni generiche già esistenti in
  `formazione_mls/build_formazione_finale.py` (`CardPool`, `build_one_lineup`,
  `synergy_adjusted_rows`, `render_lineup_html`, `render_report_html`, `parse_consiglio`,
  `load_card_counts`) — erano già indipendenti dalla lega, bastava passargli dati taggati con la
  lega giusta. Output **solo HTML** (richiesta esplicita utente).
- `generatore_formazioni/quality_filter.py` — query GraphQL L5/L10/L40 (stesso pattern già
  collaudato in `mls_gk_discovery_global.py`, mai una query nuova/rischiosa).
- `.github/workflows/generatore_formazioni.yml` — Action "Generatore Formazioni": richiama gli
  script discover/predict/consiglio **esistenti e invariati** di entrambi i tool (stessi path di
  output/cache → la cache incrementale viene riusata cosi' com'e', zero query storiche nuove per
  giocatori già noti), poi un job finale nuovo che fa la fusione.

Testato in locale con dati reali già su disco (filtro qualità disattivato via monkeypatch, nessuna
rete disponibile in locale): tutti gli 8 tipi si generano correttamente, HTML valido. Commit
iniziale pushato su `main` (`34aefd19b`).

### C. Bug 1 (run reale): filtro qualità troppo lento — query sull'intero pool scoperto

Prima run reale (2 formazioni In Season+Arena): il job finale ha impiegato **~7 minuti** e
interrogato **287 carte** (l'intero pool scoperto per 4 ruoli × 2 leghe), incappando anche in un
**429 con `Retry-After` di 236 secondi** (quasi 4 minuti da solo) — probabilmente perché le 287
query partivano subito dopo ~280 job predict paralleli sullo stesso account Sorare nello stesso
run, sommando carico.

**Causa**: il filtro qualità controllava OGNI carta scoperta, non solo quelle che servivano per le
formazioni richieste (richiesta esplicita dell'utente: "fagli interrogare solo il numero di
giocatori richiesto... se non riesce, ne interroga un altro, finché non completa").

**Fix**: `LazyQualityPool` (`quality_filter.py`) — parte VUOTA, cresce solo quando
`build_one_lineup` segnala che manca un candidato per uno slot: si controllano i prossimi
candidati non ancora verificati (batch di 3, `GROW_BATCH`) e si riprova, finché la formazione si
completa o il pool scoperto è davvero esaurito. Verificato con un test locale simulato: **27 query
invece di 284** per lo stesso risultato. In produzione reale, seconda run: job finale sceso da
**6m57s a 34s**, richieste esattamente le carte necessarie (30 su un pool di 285).

### D. Bug 2 (run reale): default del workflow generava formazioni non richieste

Run successiva: l'utente ha lasciato il campo `in_season` "vuoto" (senza cancellare attivamente il
testo pre-scritto dal form GitHub) e sono comparse 2 formazioni In Season non richieste — il
default nello YAML era `'mls:1,kleague:1'` (ereditato dal vecchio pattern a singolo-tool), mentre
`arena_dedicata` aveva già default `'mls:0,kleague:0'`. **Fix**: uniformato il default di
`in_season` a `'mls:0,kleague:0'` — un campo non toccato ora genera davvero 0.

### E. Bug 3 (run reale, il più importante): cap L10 delle Arene MAI rispettato

Con Bug 2 corretto, le formazioni richieste (Arene) sforavano COMUNQUE il cap (297-311 invece di
260, su 5/5 formazioni). Diagnosi in due passaggi:

1. **Prima ipotesi (sbagliata)**: pool troppo piccolo dopo il fix del Bug 1 (solo 2-3 candidati
   controllati per ruolo). Provato ad aggiungere un pre-riempimento minimo (`MIN_POOL_FOR_L10_CAP`)
   — non ha risolto: anche con 12 candidati/ruolo disponibili (L10 minimi reali 38-49), sforava
   comunque.
2. **Causa reale**: `build_one_lineup` (funzione CONDIVISA, identica nei due tool originali)
   sceglieva il miglior punteggio che rientrava nel budget residuo **slot per slot in ordine fisso
   GK→DEF→MID→FWD→extra**, senza MAI riservare budget per lo slot EXTRA finale — che quindi
   sforava quasi sempre (un giocatore vero costa sempre >0 di L10, non esiste un pareggio esatto a
   budget zero). Riordinare i ruoli (provato: FWD-first) NON bastava, spostava solo il problema.
   Confermato con l'utente: le run standalone dei due tool originali non avevano MAI incontrato
   questo bug nei loro output storici (probabilmente solo fortuna sulla distribuzione L10 delle
   loro carte specifiche) — il difetto è strutturale, non introdotto dalla fusione.

**Decisione esplicita dell'utente** (superando il vincolo iniziale "non toccare i due tool"): il
cap è un vincolo VERO, va corretto **anche nei due tool condivisi**, non solo nel nuovo script — "se
deve sforare il cap meglio non generarla proprio".

**Fix applicato IDENTICO in `formazione_mls/build_formazione_finale.py` E
`formazione_kleague/build_formazione_finale.py`** (`build_one_lineup`): ogni slot ora riserva la
somma dei minimi L10 disponibili per TUTTI gli slot ancora da riempire (extra incluso) prima di
scegliere un candidato; se nessun candidato rientra nemmeno riservando, la formazione **fallisce**
con lo stesso errore di "candidato esaurito" — **rimosso ogni fallback che sforava in silenzio**
(prima: "prendi il più economico disponibile anche se sfora"). Verificato su dati reali di
entrambi i tool: cap sempre rispettato (257-260/260 su più formazioni generate). Il riordino
"FWD-first" nel Generatore Formazioni è stato rimosso (era un cerotto per lo stesso sintomo, non
più necessario col fix vero).

### F. Bug 4 (scoperta collegata): filtro qualità in tensione diretta con le Arene a cap

Notato dall'utente ("mi sembra che il filtro quality faccia solo danni"): il filtro L5/L10/L40≥35
esclude proprio le carte ECONOMICHE (L10 basso) che servirebbero per stare sotto un cap di 260 —
i due meccanismi lavorano l'uno contro l'altro. **Decisione**: il filtro qualità ha senso SOLO dove
conta il punteggio assoluto (In Season, All Stars, Arena All Stars uncapped), NON dove conta invece
il risparmio L10 (Arena dedicate, Arena All Stars 260/220). **Fix**: nel Generatore Formazioni, i
tipi con cap L10 obbligatorio ora usano il pool GREZZO (tutte le carte scoperte, zero query di
qualità — anche più veloci), il filtro lazy resta attivo solo per i tipi senza cap. Verificato:
5/5 formazioni Arena "entro budget", 0 query di qualità quando si chiedono solo tipi con cap.

### G. Stato repo a fine sessione (27/07 sera)

Pushato su `origin/main`: `34aefd19b` (Generatore Formazioni, primo commit), `db895e6c7` (filtro
qualità lazy), `2977df7a0` (default `in_season` a 0/0), `d5792fcf4` (fix cap L10 riserva budget +
hard-fail, in ENTRAMBI i tool condivisi + scoping filtro qualità). Nessun lavoro di codice pendente
non committato.

**File chiave nuovi**: `generatore_formazioni/build_formazione_globale.py`,
`generatore_formazioni/quality_filter.py`, `.github/workflows/generatore_formazioni.yml`.
**File modificati nei due tool esistenti** (SOLO la funzione `build_one_lineup`, resto invariato):
`formazione_mls/build_formazione_finale.py`, `formazione_kleague/build_formazione_finale.py`.

### H. Verifica reale del fix cap L10 (run 3, stessa sera) — funziona

Run richiesta dall'utente per testare il fix: 1 In Season MLS + 1 In Season K League + 2 Arena All
Stars cap260 + 1 All Stars. Esito: 5/5 generate, **entrambe le Arena All Stars entro budget**
(cap 260 mai sforato), job finale solo 29s (24 query di qualità, solo sui tipi senza cap). Le note
"Cap 260/370: bonus +4% non ottenuto" viste su In Season/All Stars sono il bonus SOFT (solo
informativo, mai un vincolo) — non c'entrano col cap obbligatorio delle Arene, comportamento
corretto.

### I. Run "carico reale" (run 4) — 3 osservazioni dell'utente, analizzate con dati veri

Richiesta dell'utente: 6 In Season MLS + 6 In Season K League + 1 Arena MLS + 1 Arena K League + 1
Arena All Stars 260 (il volume che schiera davvero ogni giornata, "vediamo se il modello regge").
Tre osservazioni sull'output, **investigate leggendo i dati reali (consiglio/cache), non a
intuizione**:

1. **Bonus anti-stack (Multi-club) non evidenziato quando attivo** — prima veniva mostrato SOLO
   il warning di fallimento. **Fix applicato e pushato** (`a1c8c2ef8`): ora mostrato sempre,
   sia il caso positivo ("Bonus Multi-club +2%/giocatore: attivo") sia il fallimento, identico nei
   due tool + script fuso (stesse funzioni riusate).

2. **Budget delle Arene "sballato"**: extra con punteggio 14-26pt quando ne esistevano di molto
   migliori nello stesso budget. Causa reale: il fix precedente (sezione E) garantisce che il cap
   non sfori MAI, ma resta un greedy slot-per-slot con riserva — si accontenta della PRIMA
   combinazione che entra nel budget, non cerca quella con punteggio totale massimo. **Soluzione
   concordata con l'utente**: knapsack ESATTO sui 4 ruoli principali + scelta ottima dello slot
   extra, provando ogni ripartizione di budget (non solo quella che spende di più sui primi 4).
   **STATO A FINE SESSIONE: PARZIALE, non completato**:
   - Scritte in `formazione_mls/build_formazione_finale.py` le funzioni `_pareto_frontier`
     (riduce i candidati di un ruolo ai soli non-dominati: nessuno più caro E con punteggio minore
     o uguale a uno già incluso) e `_optimize_capped_lineup` (DP su GK/DEF/MID/FWD combinato con
     la scelta ottima dell'extra) — **sintassi verificata (`py_compile` OK), ma NON ANCORA
     collegate a `build_one_lineup`** (che continua a usare il vecchio greedy-con-riserva).
   - **NON ancora replicato in `formazione_kleague/build_formazione_finale.py`** (identico al
     pattern già usato per il fix precedente, va rifatto identico).
   - **NON ancora integrato/testato in `generatore_formazioni/`** (eredita tutto per import da
     `formazione_mls`, quindi si aggiorna da solo una volta wired nel file sorgente — ma va
     comunque testato sul caso reale).
   - Scelta di design già presa (da rispettare quando si riprende): il knapsack **non incorpora i
     nudge di sinergia da correlazione** (piccoli, ±3/±11, applicati oggi in `variance_mode`) —
     l'obiettivo qui è il punteggio reale massimo sotto cap, non l'ordine di scelta. Significa che
     per i tipi con cap L10 (Arena dedicate, Arena All Stars 260/220) la sinergia GK-DEF/GK-MID/
     ecc. andrebbe PERSA se si passa al knapsack così com'è — non ancora deciso con l'utente se va
     bene o se serve un'estensione (es. DP annidato per ogni possibile portiere, più costoso).
     **Da chiarire alla ripresa prima di completare il collegamento.**
   - Il knapsack si applica SOLO quando `role_slots` ha un ruolo per slot senza ripetizioni
     (vero per tutte le Arene con cap oggi) e `max_classic is None` (vero per tutte) — per shape
     diverse (es. All Stars con 2x DEF/MID, mai a cap oggi) va mantenuto il vecchio percorso come
     fallback, già previsto nel design ma da implementare quel branching in `build_one_lineup`.

3. **Caso Zinckernagel (2 copie) — NON un bug, verificato con dati reali**: escluso dalle lineup
   In Season #4/#5 per anti-sinergia (il suo Chicago Fire gioca contro Charlotte FC, il cui
   portiere Kristijan Kahlina era schierato in quelle lineup) — dato di calendario reale
   confermato nel consiglio (`SQUADRA`/`AVVERSARIO`). Escluso dalla #6 perché la sua ultima copia
   era Classic e quello slot aveva già consumato l'unica Classic ammessa (su un altro giocatore,
   DEF). Finito in Arena perché lì non c'è il vincolo "max 1 Classic".

   **Domanda di follow-up dell'utente, NON ancora risolta**: per le In Season, ha senso che il
   portiere venga scelto SEMPRE per primo (`role_slots` inizia con GK), e l'anti-sinergia esclude
   poi FWD/MID in base a quel portiere -- mai il contrario, indipendentemente da quale punteggio
   sia più alto. **Osservazione tecnica emersa in sessione (da validare/implementare)**: per le In
   Season il target è fisso (nessuna variabilità da sfruttare) — una sessione precedente (Finding
   3+F, sezione 12/13) aveva già stabilito che la correlazione tra compagni NON cambia il valore
   atteso della somma (linearità del valore atteso), motivo per cui `variance_mode` è stato
   limitato ad Arena/All Stars. La penalità anti-sinergia DI BASE (`ANTI_SYNERGY_PENALTY`/
   `POSITIVE_SYNERGY_BONUS`, indipendente da `variance_mode`) però continua ad applicarsi anche
   alle In Season, dove — con lo stesso ragionamento — non dovrebbe avere alcun beneficio di
   valore atteso. **Proposta discussa ma non implementata**: rimuovere l'anti/positive-sinergia di
   base per le In Season, lasciarla solo per Arena/All Stars — ogni slot scelto puramente per
   punteggio, senza artefatti da chi è stato scelto come portiere. Da confermare con l'utente prima
   di toccare `synergy_adjusted_rows`/`synergy_sort_key` (funzioni condivise nei due tool).

4. **Varianza capitano tra lineup multiple, richiesta dell'utente (NON implementata)**: con più
   copie di un giocatore fortissimo, oggi ogni lineup lo nomina capitano indipendentemente (stesso
   giocatore capitano in più lineup dello stesso pacchetto) — l'utente vuole una logica che eviti
   di riassegnare il capitano a chi lo è già stato in un'altra lineup (dello stesso tipo, o
   dell'intera run — **domanda posta all'utente, risposta non ancora arrivata**), per varianza sul
   rischio complessivo della giornata invece di concentrarlo tutto su un solo giocatore. Richiede
   tracciare un set di "già capitanati" condiviso tra le chiamate di `generate_lineups_for_type`
   (oggi `pick_captain` sceglie sempre e solo il punteggio più alto, senza memoria tra lineup) e
   modificare `pick_captain`/i punti di chiamata in entrambi i tool + script fuso. Non iniziato.

**Backlog aperto per la prossima sessione** (in ordine di priorità, dato quanto emerso oggi):
1. **PRIORITARIO**: completare il knapsack (punto 2 sopra) — decidere sinergia sì/no, collegare a
   `build_one_lineup`, replicare in K League, testare su una run reale.
2. Decidere e implementare la rimozione dell'anti-sinergia di base per le In Season (punto 3
   sopra) — richiede conferma esplicita dell'utente prima di toccare le funzioni condivise.
3. Varianza capitano tra lineup (punto 4 sopra) — richiede la risposta dell'utente sullo scope
   (per tipo o sull'intera run) prima di implementare.
4. Batching dei job predict (rimandato dalla sezione A, mai diventato necessario finora).
5. Verificare il fix del cap L10 sul caso limite "pool davvero troppo piccolo per qualunque
   combinazione" (deve fallire pulito, non ancora visto in una run reale).
6. Tutto il backlog della sezione 13E/14F resta valido e non toccato in questa sessione (bonus
   K League da verificare con screenshot reali, estensione ad altri campionati, ecc.).

### J. Stato repo esatto a fine sessione (per chi riprende, anche su un altro account)

Ultimo commit pushato su `origin/main`: `a1c8c2ef8` (bonus anti-stack sempre mostrato). **Questa
sessione lascia inoltre modifiche WIP non ancora committate/pushate in
`formazione_mls/build_formazione_finale.py`** (funzioni `_pareto_frontier`/
`_optimize_capped_lineup`, sintassi valida ma non collegate/usate) — verranno committate insieme a
questo aggiornamento del riassunto con un messaggio esplicito "WIP, non collegato". **Prima di
lanciare qualunque run del Generatore Formazioni con tipi a cap L10 (Arena), verificare che il
branching in `build_one_lineup` sia stato completato** — finché non lo è, il comportamento resta
quello del vecchio greedy-con-riserva (corretto sul cap, non ottimale sul punteggio), non rotto.

## 16. Sessione 27/07/2026 (notte) — knapsack Arene collegato, testato, replicato in K League

Ripresa da un account diverso. Chiude il punto 1 (PRIORITARIO) del backlog della sezione 15J.

**Decisione presa con l'utente prima di implementare** (unico punto aperto lasciato dalla sessione
precedente): il knapsack **NON incorpora i nudge di sinergia** (GK-DEF/GK-MID/DEF-MID/DEF-DEF,
vedi sezione 14A) — punta solo al punteggio grezzo massimo sotto il cap. Motivazione dell'utente:
più semplice da collegare/testare subito; il costo è la perdita dei bonus piccoli (+3/+11 pt) SOLO
per i tipi a cap L10 (Arena dedicate, Arena All Stars 260/220) — Arena/All Stars senza cap non sono
toccate (restano sul vecchio percorso con sinergia intatta).

**Scoperta importante durante l'implementazione**: `generate_lineups_for_type` passa
`variance_mode=True` per **tutte** le Arene, incluse quelle a cap L10 (non solo quelle senza cap
come si poteva pensare leggendo solo la sezione 15) — quindi il gating iniziale del knapsack non
poteva escludere `variance_mode=True`, altrimenti non si sarebbe mai attivato per nessuna Arena a
cap. Il knapsack ignora semplicemente il valore di `variance_mode` quando lo attiva (lo attiva solo
in base a `l10_cap is not None` + forma dello shape), coerente con la decisione sopra.

**Implementazione** (`build_one_lineup`, IDENTICA in `formazione_mls/build_formazione_finale.py` e
`formazione_kleague/build_formazione_finale.py`): se `l10_cap` è impostato, `max_classic` è `None`,
`apply_stack_guard` è `False` e `role_slots` ha un ruolo per slot senza ripetizioni (vero oggi solo
per le 3 Arene dedicate — MAI per In Season che ha `max_classic=1`, MAI per All Stars che ripete
DEF/MID), usa `_optimize_capped_lineup` (il DP scritto nella sessione precedente, mai toccato) al
posto del vecchio greedy-con-riserva. Fix minore collegato in `_optimize_capped_lineup`: prima non
tracciava il RUOLO dello slot extra scelto (necessario per l'etichetta `EXTRA (ruolo)` in output) —
aggiunto tag di ruolo alla lista `extra_candidates`. Nuovo helper `_consume_pick` (consuma la copia
IN_SEASON se disponibile, altrimenti CLASSIC — stesso ordine di preferenza del vecchio `pick`).
`formazione_kleague/build_formazione_finale.py` non aveva ancora `_pareto_frontier`/
`_optimize_capped_lineup` (mai portate lì nella sessione precedente, solo scritte in MLS) —
aggiunte identiche (senza `variance_mode`, parametro che K League non ha mai avuto).

`generatore_formazioni/build_formazione_globale.py` non richiede modifiche: importa
`build_one_lineup` direttamente da `formazione_mls` (`bff`) per **tutti** gli 8 tipi, incluse le
Arene K League — il fix si applica automaticamente una volta wired nel sorgente MLS.

**Verificato con test sintetico locale** (dati finti, nessuna rete — stesso approccio "smoke test"
già usato nelle sessioni precedenti): 4 candidati per ruolo con L10/punteggio costruiti apposta
perché il vecchio greedy avrebbe scelto una combinazione subottima; il knapsack trova l'ottimo
esatto (**verificato per confronto diretto con un brute-force su tutte le combinazioni possibili**,
stesso risultato: score 287, L10 220/220), rispetta sempre il cap, fallisce pulito quando il cap è
impossibile da rispettare per qualunque combinazione, e non altera il comportamento dei tipi senza
cap (Arena uncapped, che restano sul vecchio percorso greedy). Stesso test ripetuto sul modulo
K League con esito identico. **Non ancora testato su una run reale GitHub Actions** (solo dati
sintetici in locale) — da fare alla prima occasione utile prima di considerarlo definitivo.

**Stato repo**: modifiche committate sul branch di lavoro (non su `main`, per richiesta esplicita
dell'utente di pushare su `main` solo a fine sessione/su richiesta — vedi sezione 17 sotto per
il seguito della stessa nottata).

## 17. Stessa notte (continua) — redesign In Season con 2+ formazioni, varianza capitano

Chiude i punti 2 e 3 del backlog della sezione 16 (discussi con l'utente PRIMA di implementare,
come da prassi "un tema alla volta").

### A. Redesign logica In Season quando se ne richiedono 2 o più

Punto di partenza diverso dalla proposta iniziale (semplice rimozione dell'anti-sinergia): l'utente
ha chiesto una logica più articolata perché le In Season sono "le più importanti di tutte le
formazioni". Nuove regole, attive **solo quando le In Season richieste in un run sono 2 o più**
(con una sola richiesta, comportamento INVARIATO rispetto a prima):

- **Formazione #1**: comportamento storico invariato — sinergia GK-DEF soft attiva (bonus
  `POSITIVE_SYNERGY_BONUS`), GK scelto per primo per costruzione (`role_slots` inizia con GK).
- **Formazioni #2..N**: greedy puro, nessun bonus di sinergia, nessuna priorità di ruolo — ogni
  slot scelto solo per punteggio grezzo massimo disponibile.
- **In ENTRAMBI i casi** (novità rispetto a prima): il vincolo "portiere vs attaccante avversario"
  (prima un forte scoraggiamento — `ANTI_SYNERGY_PENALTY`, comunque selezionabile come ultima
  risorsa) diventa un'**esclusione assoluta** — quella combinazione non compare mai, a costo di
  fallire la formazione se non ci sono alternative (stesso principio hard-fail già usato per il
  cap L10 delle Arene).

**Implementazione** (identica in `formazione_mls/build_formazione_finale.py`,
`formazione_kleague/build_formazione_finale.py`, e propagata a
`generatore_formazioni/build_formazione_globale.py` per `MLS_IN_SEASON`/`KLEAGUE_IN_SEASON`):
- `synergy_sort_key`/`synergy_adjusted_rows`: nuovo parametro `apply_positive_synergy` (gate unico
  per il bonus DEF-GK e la vecchia penalità soft MID/FWD — quest'ultima ormai ridondante quando il
  filtro duro è attivo, ma innocua se lasciata).
- `build_one_lineup`: nuovo parametro `strict_gk_anti_synergy` — quando `True`, filtra COMPLETAMENTE
  (non solo deprioritizza) i candidati MID/FWD della squadra avversaria del portiere, sia per gli
  slot titolari sia per lo slot extra, PRIMA di applicare qualunque sinergia soft.
  `apply_positive_synergy=False` disattiva anche il bonus DEF-GK.
- `generate_lineups_for_type` (nei 3 file): calcola `in_season_multi = tipo in (...IN_SEASON) and
  count >= 2`, poi per `idx==1`: `apply_positive_synergy=True`; per `idx>1`:
  `apply_positive_synergy=False`; `strict_gk_anti_synergy=in_season_multi` sempre.

### B. Varianza capitano tra formazioni multiple, scope PER TIPO/COMPETIZIONE

Confermato dall'utente: scope "intracompetizione" — In Season MLS conta a sé, In Season K League a
sé, ogni Arena dedicata a sé, Arena All Stars a sé, All Stars a sé. Coincide naturalmente con lo
scope di ogni singola chiamata a `generate_lineups_for_type` (già un tipo per chiamata), quindi
nessuna struttura dati aggiuntiva cross-tipo necessaria.

**Implementazione** (identica nei 3 file): `pick_captain(formazione, avoid_slugs=None)` — se
fornito, preferisce il punteggio più alto TRA i titolari non ancora capitanati in questo tipo;
ripiega sul punteggio più alto assoluto se non c'è alternativa (mai un peggioramento del punteggio
atteso solo per la varianza). `format_lineup`/`render_lineup_html` accettano `avoid_captain_slugs`
e lo passano a `pick_captain`. `generate_lineups_for_type` mantiene un set `captained_slugs` locale
(resettato ad ogni chiamata, quindi già per-tipo), lo passa a entrambe le funzioni di rendering, poi
richiama `pick_captain` con lo stesso set per sapere quale slug aggiungere prima della prossima
iterazione. **Nota implicita**: un giocatore con 1 sola copia non può comunque comparire in due
lineup dello stesso tipo (il `CardPool` lo impedirebbe strutturalmente) — quindi non serve un
controllo esplicito "2+ copie", la condizione è già garantita dal pool.

### C. Verificato con test sintetici locali (nessuna rete)

- Con `count==1`: comportamento identico a prima (candidato "vincolato" ancora selezionabile come
  ultima risorsa se conviene — verificato con un MID che sarebbe stato il punteggio più alto in
  assoluto ma gioca per la squadra avversaria del GK).
- Con `count>=2`, formazione #1: GK scelto per primo, DEF con bonus sinergia sceglie il compagno di
  squadra ANCHE quando ha un punteggio grezzo leggermente più basso di un'alternativa (verificato
  con uno scarto costruito apposta: 50+3 batte 52 grezzo); il MID della squadra avversaria del GK è
  escluso del tutto (mai scelto, a differenza del caso `count==1`).
- Con `count>=2`, formazioni #2+: stesso vincolo dell'esclusione assoluta sul MID, ma il DEF viene
  scelto per puro punteggio grezzo (52 batte 50+3 quando il bonus è disattivato) — confermata la
  differenza tra i due modi.
- Varianza capitano: 3 formazioni In Season generate in sequenza, 3 capitani diversi (nessuna
  ripetizione quando esistono alternative valide nella lineup).

### D. Verificato su run reale GitHub Actions (run #5, 27/07 notte) — TUTTO CONFERMATO

Run [30253520459](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30253520459):
6 In Season MLS, 6 In Season K League, 1 Arena MLS (cap 260), 1 Arena K League (cap 260), 1 Arena
All Stars (cap 260), 1 All Stars — 16/16 formazioni generate, nessun errore.

- **Knapsack Arene**: le 3 formazioni a cap L10 obbligatorio rispettano tutte il budget, vicinissime
  al limite (L10 250.0/260.0, 253.0/260.0, 258.0/260.0 — tutte "entro budget") — segno che sta
  davvero ottimizzando (vicino al cap), non solo rispettandolo per caso. Etichetta extra con ruolo
  corretto (es. "EXTRA · MID").
- **Varianza capitano**: 0 ripetizioni DENTRO lo stesso tipo — 6 capitani diversi tra le In Season
  MLS, 6 diversi tra le In Season K League. Un capitano ripetuto tra In Season MLS e Arena MLS
  (Sebastian Berhalter) è corretto: sono tipi/competizioni diverse, lo scope è per tipo.
- Bonus capitano Arena confermato +20% in output (`CAPTAIN_BONUS_BY_TYPE`), nessuna regressione.

**Nota per la prossima sessione (richiesta esplicita dell'utente, 27/07 notte)**: per ORA le
modifiche vanno fatte solo sul Generatore Formazioni (`generatore_formazioni/` +
`formazione_mls/build_formazione_finale.py`, da cui il tool fuso importa `build_one_lineup` per
TUTTI gli 8 tipi, MLS e K League inclusi) — l'utente userà probabilmente solo questo tool d'ora in
poi. `formazione_kleague/build_formazione_finale.py` è stato comunque tenuto allineato in questa
sessione (knapsack + redesign In Season + varianza capitano, tutti e 3 i fix), ma non è più
prioritario mantenerlo in parallelo nelle prossime sessioni finché l'utente non lo richiede di
nuovo esplicitamente.

### E. Stato repo e prossimi passi

Tutto pushato su `main` (knapsack sezione 16 + redesign In Season/varianza capitano sezione 17),
verificato su run reale.

**Backlog aggiornato**: nessun punto prioritario aperto su questo filone al momento. Resta valido
tutto il backlog di 13E/14F/15J (bonus K League da verificare con screenshot reali, estensione ad
altri campionati, ecc.), non toccato in questa sessione.
