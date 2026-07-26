# Riassunto evoluzione modello predittivo — handoff per nuova sessione/account

**Scritto per essere letto da zero, su un account Claude diverso da quello che ha fatto questo
lavoro** (l'utente alterna due account, poca/nessuna memoria condivisa tra sessioni). Non
presupporre nessun contesto pregresso: tutto quello che serve è qui dentro.

**Aggiornato 26/07/2026**: la sessione del 25/07 descritta nelle sezioni 1-6 sotto si è conclusa
con la decisione presa in una sessione successiva (26/07) — vedi sezione 7 in fondo per lo stato
CORRENTE (parametri di produzione FINALIZZATI per DEF/MID/FWD, non più "da decidere"). Le sezioni
1-6 restano come cronistoria di come ci si è arrivati, ma se cerchi solo "qual è lo stato adesso"
salta direttamente alla sezione 7.

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

**Regola scoperta (100% pulita, zero eccezioni sul caso base, su migliaia di partite)**:
```
level_score = 35 (base, chiunque scenda in campo)
              + 25 per il PRIMO evento decisivo positivo (gol, assist, clean sheet per GK,
                last man tackle, rigore parato, disimpegno sulla linea, assist da rigore...)
              + 10 per ogni evento positivo AGGIUNTIVO nella stessa partita
              - 20 per ogni evento decisivo negativo (cartellino rosso, autogol, rigore causato,
                errore che porta a un gol subito)
```
Eventi positivi e negativi si SOMMANO algebricamente (non si applicano in sequenza indipendente) —
un gol (+25) e un errore-che-porta-a-un-gol (-20 -- validato piu' precisamente come compensazione
1 a 1 sulla "scala eventi", vedi sotto) nella stessa partita possono annullarsi e riportare il
giocatore alla base 35 netta.

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
