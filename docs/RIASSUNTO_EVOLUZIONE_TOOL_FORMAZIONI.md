# Riassunto evoluzione Tool Formazioni MLS

Documento di riferimento permanente (non un handoff di singola sessione) sull'evoluzione del
sistema di formazione ottimale MLS: cos'è, come è nato, come funziona oggi, quali bug sono stati
trovati e corretti, e a che punto è il lavoro di calibrazione allargata in corso. Aggiornare
questo file (non crearne uno nuovo) quando il tool evolve ulteriormente.

## 1. Obiettivo del tool

Dato l'elenco delle carte MLS possedute dall'utente (in_season + classic), produrre in modo
automatico N formazioni ottimali (1 GK, 1 DEF, 1 MID, 1 FWD + slot extra) per la giornata
successiva, con un capitano consigliato, rispettando i vincoli di Sorare (max 1 carta CLASSIC per
formazione, min 4 IN_SEASON) e senza riusare lo stesso giocatore in più formazioni a meno di
possederne più copie.

Il "cervello" del sistema è un modello predittivo per ruolo che stima lo score atteso di ogni
giocatore alla prossima partita, con un range di confidenza, basato sullo storico recente
pesato esponenzialmente e corretto da una serie di fattori (casa/trasferta, forza avversario,
trend di forma, e — per i ruoli con dati sufficienti — fattori granulari per categoria di
statistica Sorare: falli, duelli, passaggio, ecc.).

## 2. Architettura (cartella `formazione_mls/`)

```
formazione_mls/
  discovery/        # scopre gli slug giocatore da processare, per ruolo
    mls_<ruolo>_discovery.py         # SOLO carte possedute dall'utente (in_season+classic)
    mls_<ruolo>_discovery_global.py  # TUTTI i giocatori MLS di quel ruolo (30 squadre, pubblico)
  predict/           # il modello vero e proprio, uno script per ruolo
    test_gk.py / test_def.py / test_mid.py / test_mls_fwd_all.py
  consiglio/         # (storico) genera il consiglio per singolo ruolo
  calibrazione/       # script di supporto per la calibrazione cross-player
    aggregate_grid_search.py
  build_formazione_finale.py   # fonde i 4 consigli di ruolo in N formazioni ottimali
  output/            # tutti gli output, organizzati per ruolo/scopo (vedi sotto)
```

Ogni script `test_<ruolo>.py` fa, per ogni giocatore:
1. **Discovery** (fase 1): recupera lo storico partite (game log, con cache incrementale) +
   le prossime partite programmate.
2. **Filtro competizione/minutaggio** (fase 2): tiene solo partite della stessa competizione
   della prossima (fallback a tutte se non abbastanza dati), esclude DID_NOT_PLAY e minutaggio
   sotto soglia.
3. **Dettaglio granulare** (fase 3): scarica il `detailedScore` (punteggio per singola statistica
   Sorare: falli, duelli, passaggi, ecc.) di ogni partita della finestra, con cache persistente
   per le partite già `FINAL`.
4. **Calcolo fattori e predizione** (fase 4): vedi sezione 3 sotto.

### Output per ruolo (cartelle in `formazione_mls/output/`)

- `mls_<ruolo>_discovery/` — slug posseduti (uso produzione)
- `mls_<ruolo>_discovery_global/` — slug globali MLS filtrati per qualità (uso calibrazione)
- `mls_<ruolo>_all/` — predizioni di produzione (lette da `build_formazione_finale.py`)
- `mls_<ruolo>_calibration/` — predizioni/grid search di calibrazione (isolate dalla produzione,
  NON lette da `build_formazione_finale.py`)

## 3. La formula di predizione

```
score_atteso = P(gioca) x media_pesata_esponenziale(N partite)
               x fattore_casa_trasferta x fattore_forza_avversario
               x [fattori granulari per gruppo, se il ruolo li usa in produzione]
               x fattore_trend
range_confidenza = +/- dev_std_pesata x RANGE_MULTIPLIER
```

- **P(gioca)**: `starterOddsBasisPoints` della prossima partita (fallback: tasso di presenza
  storico se non disponibile).
- **Media pesata esponenziale**: le partite più recenti pesano di più (parametro `HALF_LIFE_GAMES`).
- **Fattore casa/trasferta**: quanto il giocatore rende diversamente in casa/trasferta (vedi
  Finding 3 sotto per un fix importante fatto in questa sessione).
- **Fattore forza avversario**: corregge in base al ranking dell'avversario rispetto alla media
  storica affrontata (parametro `OPPONENT_SENSITIVITY`).
- **Fattori granulari**: un fattore casa/trasferta INDIPENDENTE per ogni gruppo di statistiche
  Sorare (falli, duelli, passaggio, eventi rari con cap, azioni difensive, gol subiti, clean
  sheet per DEF, ecc.) — **usati in produzione solo per DEF/MID/FWD**, non per GK (la
  calibrazione ha mostrato che peggiorano sempre il MAE per i portieri).
- **Fattore trend**: confronta la forma delle ultime 5 partite vs le ultime 10 (parametro
  `TREND_INTENSITY`).

Tutti i parametri (`HALF_LIFE_GAMES`, `RANGE_MULTIPLIER`, `OPPONENT_SENSITIVITY`,
`TREND_INTENSITY`) sono FISSI in produzione, decisi da un grid search di calibrazione (72
combinazioni testate in backtest rigoroso, min. 6 partite di storico per ogni punto testato).

### Parametri fissati attuali (aggiornato 26/07/2026 — vedi sezione 7)

| Ruolo | half_life | range_mult | opp_sens | trend_int | granulari? | Campione calibrazione |
|---|---|---|---|---|---|---|
| GK | 9.0 | 1.6 | 20.0 | 0.7 | NO | 12 posseduti (non ancora aggiornato: campione allargato ancora insufficiente, 2-3 giocatori) |
| DEF | 12.0 | 1.2 | 29.0 | 0.7 | NO | 68 giocatori MLS qualificati (calibrazione allargata pesata per n_test) |
| MID | 12.0 | 1.4 | 29.0 | 0.7 | NO | 65 giocatori MLS qualificati (idem) |
| FWD | 12.0 | 1.4 | 29.0 | 0.7 | NO | 37 giocatori MLS qualificati (idem) |

## 4. Storia evolutiva

1. **Prototipo iniziale**: script singoli per attaccanti (`test_owusu.py`/`test_multi_fwd.py`),
   poi centrocampisti (clone adattato), poi difensori, poi portieri (il più diverso
   strutturalmente — nessuna categoria DEFENDING, gruppo GOALKEEPING dedicato con 10 statistiche
   valorizzate solo per questo ruolo, gestione speciale del bonus clean sheet che nel portiere
   ha sempre `totalScore=0` nel `detailedScore` e va dedotto da `clean_sheet_60.statValue`).
2. **Cache incrementale del game log**: introdotta per ridurre le chiamate GraphQL ripetute — una
   volta che una partita è `FINAL` non cambia più, si scarica solo un lotto ridotto di partite
   recenti (`GAME_LOG_REFRESH_COUNT`) ad ogni run invece di tutto lo storico.
3. **Fusione finale** (`build_formazione_finale.py`): legge gli ultimi consigli dei 4 ruoli,
   genera N formazioni massimizzando lo score (selezione guidata SOLO dallo score, mai dal tipo
   di carta), applica la regola "max 1 CLASSIC, min 4 IN_SEASON" e la logica multi-formazione
   (un giocatore riusabile solo se si possiedono più copie), assegna il capitano (+50% al
   punteggio più alto).
4. **Workflow unificato** (`formazione_completa.yml`): un solo `workflow_dispatch` che fa tutto
   in un run (discovery → predict → consiglio → fusione, 13 job), sostituendo 9 workflow singoli
   ridondanti. Ottimizzazioni: `GAME_LOG_REFRESH_COUNT` ridotto, filtro starter-odds ≥60%
   spostato in fase discovery (per non generare job CI per giocatori scartati comunque). Tempo
   di run: da 16m52s a 8m10s.
5. **Riorganizzazione root del repo**: da ~65 file sparsi a cartelle tematiche
   (`formazione_mls/`, `bots/`, `scanners/`, `diagnostics/`, `auctions/`, `docs/`).

## 5. Audit logico del modello (findings)

Un agente in worktree isolato ha revisionato la formula di scoring cercando errori di logica.
Stato dei findings, per impatto:

1. **✅ CORRETTO** — GK applicava in produzione 7 fattori granulari che la calibrazione aveva
   già scartato (peggioravano il MAE). Fix: rimossi da `score_atteso`, restano solo diagnostici.
2. **✅ CORRETTO** — la scala fissa "1%/punto" in `compute_split_factor` (identica per ogni
   gruppo granulare) rendeva quasi tutti i fattori granulari inerti (0.98-1.01) tranne quelli con
   magnitudine alta (es. GOALKEEPING). Fix: normalizzazione per la deviazione standard STORICA
   del gruppo stesso (`SPLIT_FACTOR_SCALE_PER_STD = 0.05`), applicata identicamente nei 4 file.
3. **✅ CORRETTO (25/07, in questa sessione)** — **doppio conteggio dell'effetto casa/trasferta**:
   `fattore_casa_trasferta` era calcolato sul punteggio TOTALE della partita, che però include
   già il contributo di ogni gruppo granulare — risultando in un doppio conteggio quando poi ogni
   fattore granulare veniva moltiplicato separatamente. **Fix**: `fattore_casa_trasferta` ora si
   calcola solo sul RESIDUO (score totale meno la somma di tutti i gruppi granulari tracciati),
   applicato a DEF/MID/FWD (GK non toccato, i granulari non sono in produzione lì). Verificato su
   dati reali post-fix: un difensore con swing enorme casa/trasferta (57.97 vs 44.52) ora ha
   `fattore_casa_trasferta` quasi neutro (0.991) perché l'effetto reale è correttamente
   distribuito nei gruppi granulari che lo generano (gol subiti, clean sheet, falli), non più
   duplicato ovunque.
4. **DA VALUTARE (non affrontato)** — l'effetto casa/trasferta e la forza avversario potrebbero
   essere condizionati insieme (2D: venue + forza avversario combinati) invece che separatamente,
   e potrebbe emergere una logica di correlazione tra slot della stessa formazione (bonus
   sinergia GK+DEF stessa partita per clean sheet condiviso; penalità anti-sinergia GK vs FWD
   avversario). Discusso ma non implementato — da riprendere con un design dedicato.
5. **MINORI, non affrontati**: mix di medie pesate/non pesate concettualmente incoerente (impatto
   modesto); P(gioca) di fallback ha un lieve bias di sovrastima quando manca
   `starterOddsBasisPoints`.

## 6. Discovery globale + filtro qualità (25/07)

Fino a questa sessione, la calibrazione girava SOLO sui giocatori posseduti dall'utente (12-45 a
seconda del ruolo) — un campione piccolo. Per allargarlo:

- **Discovery globale per tutti e 4 i ruoli** (`mls_<ruolo>_discovery_global.py`): interroga
  pubblicamente (nessun cookie/scope utente richiesto) il roster di tutte le 30 squadre MLS,
  filtra per posizione lato client. Un solo workflow a matrice (`mls_discovery_global.yml`)
  sostituisce quello che prima esisteva solo per i centrocampisti.
- **Filtro qualità**: tenuti solo i giocatori con media `(L5+L10+L40)/3 >= MIN_AVG_SCORE_QUALITY`
  (default **30.0**, valore deciso dall'utente dopo aver visto quanto tagliava una soglia di 40)
  — i giocatori "scarsi" non verrebbero comunque comprati e inquinerebbero la calibrazione. Se
  uno dei tre valori manca (storico insufficiente), il giocatore è escluso per sicurezza. Le
  medie L5/L10/L40 sono lette direttamente dall'API (`averageScore(type: LAST_FIVE_SO5_AVERAGE_
  SCORE / LAST_TEN_PLAYED_SO5_AVERAGE_SCORE / LAST_FORTY_SO5_AVERAGE_SCORE)`), non calcolate a
  mano.

Risultati discovery globale (25/07, prima del filtro qualità): **74 GK, 340 DEF, 346 MID, 276
FWD** = 1036 giocatori totali su 30 squadre.

## 7. Infrastruttura di calibrazione allargata (in corso)

Obiettivo: rieseguire il grid search completo (72 combinazioni) su tutti i giocatori di qualità
scoperti globalmente (non solo i posseduti), con la formula CORRETTA (dopo i fix Finding 2+3),
per ottenere parametri fissi più robusti statisticamente. Operazione UNA TANTUM.

- **`CALIBRATION_MODE`** (env var, nei 4 script `test_<ruolo>.py`): se attivo, legge la lista
  globale filtrata invece dei soli posseduti, esegue il grid search completo invece del singolo
  backtest fisso di produzione, e scrive output in cartelle separate (`mls_<ruolo>_calibration`)
  per non inquinare la produzione.
- **`grid_search_calibrazione.yml`**: workflow a batch (limite GitHub Actions di 256 job/matrice
  — batch da 200 di default). Si lancia più volte cambiando `batch_index` finché non copre tutti
  i giocatori qualificati di un ruolo; i risultati si accumulano tra batch (non si sovrascrivono).
- **`grid_search_aggregate.yml`** + `aggregate_grid_search.py` (parametrizzato per ruolo via env
  `RUOLO`): calcola la combinazione di parametri che generalizza meglio ATTRAVERSO tutti i
  giocatori con dati sufficienti (richiede che una combinazione sia rappresentata per almeno metà
  dei giocatori con risultati, per non premiare un caso fortunato).

### Bug reali trovati e corretti durante il primo giro di batch reali (25/07)

1. **`MIN_STARTER_ODDS` non veniva disattivato in `CALIBRATION_MODE`**: era una costante fissa
   (0.70) con un commento che richiedeva di riportarla manualmente a 0.0 per un grid search
   allargato — non letta da env, quindi l'override passato dal workflow non aveva alcun effetto.
   Nel primo batch GK (27 giocatori) questo ha escluso 25/27 giocatori. **Fix**: si disattiva
   automaticamente (`0.0 if CALIBRATION_MODE else 0.70`).
2. **Bug critico nel retry di push del job `calibrate`**: il loop `for attempt in 1..8: git add +
   diff-check + commit + push` ri-eseguiva `git diff --cached` ad OGNI tentativo, incluso dopo un
   commit già fatto in precedenza — con l'indice ormai pulito, il controllo risultava vuoto e il
   job usciva con "Nessuna modifica da salvare" **senza mai ritentare il push**, perdendo il
   commit locale (il job comunque terminava con successo, mascherando il problema). Con 8 worker
   paralleli su 156 difensori, questo ha fatto perdere i risultati di 123 giocatori su 156 nel
   primo batch DEF. **Fix**: diff-check e commit avvengono una volta sola, poi un loop `until git
   push` dedicato SOLO al retry del push (stesso pattern già corretto e testato nei workflow di
   discovery esistenti) — non riprodurre questo errore in futuri workflow con matrix paralleli
   che scrivono file.

### Stato batch al 25/07 sera (da aggiornare mano a mano)

- **GK**: 74 scoperti → 27 qualificati (soglia 30) → 7 con grid search completo dopo il fix
  starter-odds. Campione piccolo ma **coerente con la realtà**: 30 squadre = 30 titolari, di cui
  solo una decina "decenti" secondo il filtro qualità — non è un problema del tool, è la
  distribuzione reale dei portieri MLS. Da tornare a vedere più avanti, non prioritario.
- **DEF**: 156 qualificati (soglia 30) → primo batch (prima del fix push) aveva perso quasi tutto
  (33/156 salvati), ripetuto dopo il fix — vedi handoff di sessione per il numero finale.
- **MID/FWD**: non ancora processati con la nuova infrastruttura al momento di scrivere questo
  documento.

**Prossimi passi**: completare i batch per tutti e 4 i ruoli, lanciare l'aggregazione per
ciascuno, confrontare i nuovi parametri con quelli attuali di produzione (sezione 3), decidere se
sostituirli. Poi tornare ai Finding 4 (condizionamento 2D venue+avversario, correlazione slot
formazione) prima di considerare chiusa questa fase di affinamento del modello.

## 8. Idea futura: MLS come modello per altri campionati

L'intera infrastruttura (discovery globale, filtro qualità, calibrazione a batch) è pensata per
essere riusabile su altri campionati in futuro, usando l'esperienza MLS come riferimento — non
implementato, solo l'intento dichiarato dall'utente.

## 9. Calibrazione allargata conclusa e pesata per n_test (26/07/2026)

Dopo la sezione 7, la calibrazione allargata è stata portata a termine per tutti e 4 i ruoli e
**pesata per numero di partite di backtest disponibili per giocatore** (fix importante: un
giocatore con 1 sola partita testata pesava nell'aggregazione quanto uno con 9, pur essendo il
suo MAE l'errore di un singolo evento anziché una stima stabile — scoperto analizzando un caso
FWD dove l'effetto dei granulari per singolo giocatore variava da -5 a +5 di MAE ma la media si
cancellava quasi a zero). Fix in `aggregate_grid_search.py`: esclude giocatori con
`n_test < MIN_TEST_GAMES` (default 3), pesa il resto per n_test. Campo `n_test` ora salvato
direttamente nel `grid.json` di ogni giocatore (nuovi run) per non dipendere più dal parsing dei
file di testo.

**Risultato**: DEF/MID/FWD convergono tutti su `half_life=12.0, opponent_sensitivity=29.0,
trend_intensity=0.7`, **senza fattori granulari** — molto più coerente tra ruoli di quanto
suggerisse la prima aggregazione non pesata. GK non aggiornato (campione insufficiente, solo 2-3
giocatori con abbastanza storico).

**Scoperta tecnica collaterale importante**: il flag "granulari sì/no" non era in realtà un vero
interruttore in produzione — controllava solo il backtest diagnostico mostrato in output, mentre
la formula reale di `score_atteso` (quella che costruisce le formazioni) moltiplicava SEMPRE tutti
i fattori granulari per DEF/MID/FWD, a differenza di GK dove erano già correttamente rimossi
(hardcoded). Corretto: i granulari sono ora rimossi anche dallo `score_atteso` reale di DEF/MID/FWD.

**Decisione presa e validata con un confronto A/B reale** (5 formazioni vecchio vs nuovo modello
sui posseduti dell'utente): caso Antino Lopez (DEF che gioca il 25% delle ultime 40 partite ma con
picchi isolati) sovrappesato a capitano dal vecchio modello (86pt), riportato a un valore più
realistico dal nuovo (75pt, non più capitano) a favore di Carles Gil (centrocampista stabile, gioca
quasi sempre) — verificato contro le statistiche Sorare reali dei due giocatori. Parametri sopra
ora UFFICIALI in produzione (non più sperimentali). Dettaglio completo della sessione in
`docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` sezione 7.

## 10. Robustezza statistica del backtest (26/07/2026, primo tema del backlog affrontato)

Nuovo script `formazione_mls/calibrazione/bootstrap_stability.py`: ricampiona con sostituzione i
giocatori qualificati (bootstrap, 1000 iterazioni di default) per verificare quanto è solida la
combinazione vincente di `aggregate_grid_search.py`. Risultato: nessun vincitore netto (win-rate
17-33% a seconda del ruolo su MLS a metà stagione) — `opponent_sensitivity=29.0` è l'unico
parametro sempre stabile, half_life e il flag granulari sono le vere zone di incertezza. Lo
script calcola anche una **media pesata bootstrap dei parametri** (valore continuo, non vincolato
alla griglia discreta) come riferimento più prudente: per FWD/DEF/MID conferma che "senza
granulari" è la scelta giusta in modo consistente (~30% di supporto ai granulari su tutti e tre,
non un coin-flip), con scarti modesti sui parametri numerici (half_life ~10.5-11 pesato vs 12.0
ufficiale). Decisione: parametri ufficiali NON cambiati (già validati dal caso reale Antino
Lopez/Carles Gil), questi valori pesati servono da riferimento per la prossima ricalibrazione a
stagione più avanzata. Dettaglio completo in `RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` sezione 8.

**Prossimo tema in coda** (da un brainstorm più ampio richiesto dall'utente, "una settimana per
migliorare il modello", affrontato UN TEMA ALLA VOLTA): il Finding 4 di sezione 5
(condizionamento 2D venue+avversario, correlazione slot formazione GK-DEF-FWD) resta il più
maturo/prioritario — c'era un task in background per una proposta di design ma l'utente non è
riuscito a recuperarlo, quindi si riparte da zero su questo tema quando arriva il suo turno.
Altri temi in backlog: feature aggiuntive (infortuni, calendario congestionato), gestione
outlier/hot-streak, monitoraggio MAE live in produzione, estensione ad altri campionati.
