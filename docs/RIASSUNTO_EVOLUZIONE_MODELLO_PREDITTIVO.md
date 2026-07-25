# Riassunto evoluzione modello predittivo — handoff per nuova sessione/account

**Scritto per essere letto da zero, su un account Claude diverso da quello che ha fatto questo
lavoro** (l'utente alterna due account, poca/nessuna memoria condivisa tra sessioni). Non
presupporre nessun contesto pregresso: tutto quello che serve è qui dentro.

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
