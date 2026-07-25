# Handoff sessione 25/07 (seconda parte) — per continuare su un altro account Claude Code

**AGGIORNATO — versione finale prima del passaggio di sessione (utente al 94% di utilizzo).**

Repo: `Sorare-tracker-2`, branch `main`. Tutto lo stato descritto qui è già **committato e pushato** su GitHub (ultimo commit `5753070f`), quindi la nuova sessione può ripartire semplicemente con `git pull` — non c'è lavoro locale non salvato da recuperare.

## 1. Cosa NON interrompere subito

- **Bot Supremo test no play** è **in esecuzione in questo momento**: [run 30168958480](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30168958480). L'utente ha detto esplicitamente: "quando ti scriverò stop, o solo s, interrompi manualmente il workflow" — finché non scrive `stop`/`s`, **lascialo girare**, non cancellarlo di tua iniziativa. Comando per cancellarlo quando richiesto: `gh run cancel 30168958480`.
- Se in questa sessione avevo un Monitor in background attivo su questo run, nella nuova sessione va ri-creato (i Monitor non sopravvivono al cambio sessione) — basta un loop che polla `gh run view 30168958480 --json status,conclusion`.

## 2. Lavoro completato in questa sessione (in ordine cronologico)

### A. Portiere (GK) portato in produzione
- Aggiunti discovery/predict/calibrazione GK (mancavano), grid search di calibrazione eseguito su 12 portieri posseduti → parametri fissati: `hl=9.0, range=1.6, opp_sens=20.0, trend=0.7`, **senza** fattori granulari (peggioravano sempre il MAE per questo ruolo).
- Tutti e 4 i ruoli (GK/DEF/MID/FWD) ora ✅ in produzione.

### B. Fusione finale (formazione ottimale)
- Creato `formazione_mls/build_formazione_finale.py`: legge gli ultimi `consiglio_*.txt` dei 4 ruoli e genera N formazioni (1 GK, 1 DEF, 1 MID, 1 FWD, 1 extra DEF/MID/FWD), massimizzando lo score.
- **Selezione guidata SOLO dallo score**, mai dal tipo di carta — verificato esplicitamente con test sintetici (un giocatore posseduto solo in classic viene scelto comunque se ha lo score più alto).
- Regola **"max 1 carta CLASSIC per formazione, min 4 IN_SEASON"**: implementata. Quando un giocatore ha sia copie in_season che classic, si consuma prima l'in_season (risparmia il budget classic per chi ne ha davvero bisogno) — non è una preferenza tra giocatori, solo tra copie dello stesso giocatore.
- **Multi-formazione**: un giocatore non può essere riusato in una lineup successiva a meno di possedere più copie (tracciato per tipo in `player_card_counts.json`). Se un ruolo esaurisce i candidati, si ferma e lo segnala (NON crasha/blocca).
- **Capitano consigliato**: aggiunto — sempre il giocatore con score più alto della formazione (+50%), mostrato con tag `[C]` e totale ricalcolato.
- Le 4 discovery (`mls_gk/def/mid/fwd_discovery.py`) sono state estese per scansionare **sia carte IN_SEASON che CLASSIC** (prima solo in_season) — due passate per tipo sullo stesso filtro server-side `in_season_eligible=true/false`. Output: `player_card_counts.json` con `{slug: {'in_season': n, 'classic': m}}`.

### C. Workflow master unificato
- Creato `.github/workflows/formazione_completa.yml`: un solo `workflow_dispatch` (input `num_formazioni`, default 1) che fa TUTTO in un run — discovery (4 ruoli, parallela) → predict matrix (4 ruoli) → consiglio per ruolo → fusione finale. 13 job totali.
- Eliminati 9 workflow singoli ormai ridondanti (le 4 discovery standalone, i 4 `test_<ruolo>.yml`, `formazione_finale.yml`).
- **Ottimizzazioni performance** (richiesta utente, uso settimanale del tool):
  - `GAME_LOG_REFRESH_COUNT` 5→2 partite (cache incrementale, refresh leggero) su tutti e 4 i ruoli.
  - Filtro starter-odds ≥60% **spostato in fase discovery** (non più solo nel job predict): un giocatore sotto soglia non genera nemmeno un job CI. **Attenzione**: questo filtro va tenuto **solo** nella pipeline "miei giocatori" — la discovery GLOBALE (futura, vedi punto E) NON deve avere questo filtro, serve prendere tutti i giocatori per calibrare bene il modello.
- Risultato misurato: run da 16m52s (2 formazioni, pre-ottimizzazione) → **8m10s** (5 formazioni, post-ottimizzazione).

### D. Riorganizzazione completa della root del repo (Fase 1 + Fase 2)
Root passata da ~65 file sparsi a una struttura per cartelle:
- `formazione_mls/` — tutto il sistema formazione (discovery/, predict/, consiglio/, calibrazione/, output/, build_formazione_finale.py)
- `bots/` — autobuy_sorare.py, makeoffer_sorare.py, bot_supremo*.py, sorare-sign/ (Node signer condiviso)
- `scanners/` — track.py (modulo condiviso) + i 6 script che lo importano, bot_profit.py, mls_sentiment_scanner.py, logs/, bot_profit_output/
- `diagnostics/` — script diagnostici one-off, introspect_fetch_key.py, test_signature_isolated.py
- `auctions/` — auctions.py, auctions_ws_listener.py, auctions.db
- `docs/` — GUIDA.md, HANDOFF.md, RIEPILOGO_SESSIONE_2026-07-17.md, botsupremo.md (+ questo file)
- File di stato/blacklist/cache (`.my_cards_profit_*.txt`, `sorare_*.txt`, `*.json` di cooldown/cache, `config.json`, `requirements.txt`, `state.json`, `tracker.db`) **restano in root**: usano path relativi alla cwd (non `__file__`), quindi funzionano invariati indipendentemente da dove vivono gli script — verificato script per script prima di NON spostarli, per non rischiare sui bot di trading live.
- Eliminati 5 file morti (`cazzo.py`, `sync_registry.py`, `test_scraper.py`, `zenlock_model_tracker.py`, `check.yml` duplicato in root) e ~610 file `prediction_*.txt` obsoleti + dati grezzi di calibrazione conclusa (tenuti solo i riepiloghi finali in `formazione_mls/output/calibrazione_storica/`).
- **Bug reale trovato e corretto DOPO il push**: lo step "Install sorare-sign dependencies" in 6 workflow (`autobuy.yml`, `bot_supremo.yml`, `bot_supremo_aste.yml`, `bot_supremo_test.yml`, `makeoffer.yml`, `test_signature.yml`) faceva ancora `cd sorare-sign` invece di `cd bots/sorare-sign` — scoperto dal primo run reale post-riorganizzazione (fallito), corretto e ripushato, poi ri-verificato con un nuovo run (quello attualmente in corso, vedi punto 1).
- **Lezione per la prossima riorganizzazione**: quando si sposta una cartella, cercare SEMPRE anche riferimenti `cd <cartella>` dentro gli step shell dei workflow, non solo `run: python <script>` — è facile che sfuggano.

### E. Audit logico del modello (agente worktree, completato) + 2 fix applicati

Lanciato un agente in un worktree isolato per revisionare la formula di scoring dei 4 ruoli (`formazione_mls/predict/test_*.py`) cercando errori di logica nel peso dei fattori. **Stato dei findings** (per impatto):

1. **✅ CORRETTO (commit `cc489748`)** — GK: la produzione applicava 7 fattori granulari che la calibrazione aveva scartato (peggioravano il MAE). Fix: rimossi dallo `score_atteso` di `test_gk.py`, restano solo diagnostici in output con nota esplicita "non applicato".

2. **✅ CORRETTO (commit `ae95d460`)** — La scala fissa "1%/punto" in `compute_split_factor` (identica per ogni gruppo granulare, ogni ruolo — funzione BYTE-IDENTICA nei 4 file, verificato con md5sum prima di modificare) rendeva quasi tutti i fattori granulari inerti (0.98-1.01, verificato sui dati reali) tranne `fattore_goalkeeping` del GK, per via delle scale di valori molto diverse tra gruppi (RARE_EVENTS ±10pt cap vs GOALKEEPING senza cap, decine di punti).
   **Fix applicato**: il delta casa/trasferta ora si normalizza per la deviazione standard STORICA del gruppo stesso (nuova costante `SPLIT_FACTOR_SCALE_PER_STD = 0.05`, cioè 5% per deviazione standard), applicato identicamente nei 4 file. Così ogni gruppo/ruolo ha sensibilità comparabile.
   **Verifica fatta**: solo `py_compile` (sintassi) + un **test sintetico locale** con dati inventati che conferma la logica matematica (gruppo piccolo con pattern reale ora si muove ±1.4-1.6% invece di restare a 1.000; gruppo grande ha sensibilità comparabile ±4-5%; nessuna variabilità → resta esattamente 1.0 senza crash da divisione per zero; rumore puro senza pattern → resta vicino a 1.0).
   **⚠️ NON ANCORA VERIFICATO con un run reale end-to-end** (richiede chiamate API live, non fattibile in locale senza SORARE_COOKIE/SORARE_CSRF). **Prossimo passo consigliato per la nuova sessione**: lanciare `formazione_completa.yml` con `num_formazioni=1` e controllare nei `prediction_*.txt` prodotti che i fattori granulari si muovano in modo sensato (non più quasi-sempre 1.000, ma nemmeno valori assurdi/esplosi) prima di fidarsi ciecamente del fix in produzione.

3. **DA VALUTARE (non ancora affrontato)** — L'effetto casa/trasferta viene contato più volte: una volta sul totale (`fattore_casa_trasferta`) e di nuovo dentro OGNI fattore granulare correlato (moltiplicati insieme). **Diventato più rilevante dopo il fix del punto 2** (ora che i granulari si muovono davvero, la duplicazione pesa di più, non è più "quasi innocua"). Discusso con l'utente: la soluzione pulita probabilmente coincide con il punto F qui sotto (condizionare i fattori granulari su casa/trasferta E forza avversario insieme, invece di ricalcolare due volte lo stesso effetto venue) — **valutarli insieme nella prossima sessione**, non separatamente.

4. **MINORE, non affrontato** — Mix di medie pesate (base esponenziale) e non pesate (fattori casa/trasferta e granulari) — incoerenza concettuale, impatto modesto.

5. **MINORE, non affrontato** — P(gioca) di fallback (quando manca starterOddsBasisPoints) ha il denominatore troncato dal `break` che riempie la finestra — lieve sovrastima della presenza storica, scatta raramente.

- **Verificato CORRETTO** (nessun bug, nessuna azione necessaria): segno del fattore forza avversario (coerente nei 4 ruoli), clamp del trend applicato dopo la scalatura per `trend_intensity`, nessun doppio conteggio del bonus clean sheet portiere. Il "rischio di prodotto esplosivo" (0.7^7 per troppi fattori clampati moltiplicati) **non si verifica mai** nei dati reali.

**Domanda importante posta dall'utente e risposta data**: "sappiamo quanto pesa ogni singolo detailed score (es. un fallo, una doppia doppia)?" — Risposta: NON serve una tabella di pesi nostra, perché ogni riga di `detailedScore` dall'API ha già un campo `totalScore` reale assegnato da Sorare stesso; `extract_group_score()` somma questi valori reali, non stime. Il limite vero è che quando un gruppo contiene più stat insieme (es. PASSING_STATS = 3 stat diverse), non si vede il contributo di ciascuna singolarmente — non blocca la normalizzazione del punto 2 (lavora sulla distribuzione storica del gruppo intero), ma limiterebbe un'eventuale analisi futura "quanto pesa esattamente un ingresso in area" (richiederebbe un'analisi statistica separata sui dati grezzi, non fatta).

**Prossimo passo concordato con l'utente**: prima di lanciare la discovery globale (punto F sotto), affinare il modello sui dati che già abbiamo — quindi valutare/implementare i Finding 3-5 insieme all'utente, uno alla volta (punto 3 insieme al punto F), PRIMA di ricalibrare con più dati (la ricalibrazione con la discovery globale è un'attività separata e successiva, esplicitamente rimandata da lui).

### F. Idea futura registrata (NON ancora progettata, task in background disponibile)
L'utente ha proposto una logica di **correlazione tra slot della stessa formazione**, basata su chi gioca contro chi quella giornata — e ha anche chiesto di condizionare i fattori granulari su **venue + forza avversario insieme** (es. "falli in trasferta contro squadra forte" come contesto combinato, non due dimensioni separate come oggi):
- **Bonus sinergia GK+DEF stessa partita**: se giocano nella stessa partita, il bonus clean sheet è correlato (stesso evento), andrebbe pesato come upside aggiuntivo nello sceglierli insieme (oggi ogni giocatore è valutato in isolamento).
- **Penalità anti-sinergia GK vs FWD avversario**: se il GK scelto gioca quella giornata CONTRO la squadra del FWD scelto, i bonus tendono ad annullarsi (gol per l'attaccante spesso = niente clean sheet per il portiere) — andrebbe penalizzata/segnalata.
- **Condizionamento 2D dei fattori granulari** (venue + forza avversario combinati, non solo casa/trasferta come oggi in `compute_split_factor`): questo probabilmente risolverebbe ANCHE il Finding 3 (doppio conteggio casa/trasferta) in un colpo solo, se progettato bene — valutarli insieme.
- È stato lanciato un task in background (`task_c858ec41`, titolo "Progettare bonus/penalità correlazione GK-DEF-FWD") con un prompt dettagliato per un agente che prepari una PROPOSTA DI DESIGN (non il codice) — l'utente lo ha già avviato in una sessione locale separata, indipendente da questa. Se non è ancora arrivato un risultato, verificare lo stato di quel task nella nuova sessione.

### G. Altro
- Aggiunto manager `gigiz22` alla sezione `## manager` di `sorare_lista_nera.txt` (365 giorni, standard) su richiesta utente — commit `cc489748`. Nessun'altra azione necessaria, era una richiesta puntuale già chiusa.
- L'utente ha chiesto se è possibile avere una barra di utilizzo sessione visibile senza aprire il profilo — risposto che dipende dall'interfaccia (se app, è una funzione della UI non controllabile da qui; se CLI, esiste una statusline configurabile ma non è confermato che esponga quel dato). L'utente ha detto di lasciar perdere, nessuna azione richiesta.

## 3. Cose in sospeso / da chiedere all'utente

1. **Verifica end-to-end del fix Finding 2** (vedi punto E.2 sopra): lanciare un run reale (`formazione_completa.yml`, `num_formazioni=1` basta) e controllare che i fattori granulari nei `prediction_*.txt` si muovano in modo sensato. Farlo PRIMA di fidarsi del fix in produzione.
2. **Finding 3** (doppio conteggio casa/trasferta) **+ punto F** (correlazione GK-DEF-FWD e condizionamento 2D venue+avversario): l'utente ha chiesto di valutarli insieme, probabilmente la stessa revisione strutturale risolve entrambi. Aspetta il task in background `task_c858ec41` e/o una discussione di design con l'utente prima di implementare.
3. **Finding 4-5**: minori, non ancora discussi in dettaglio con l'utente, bassa priorità.
4. **Discovery globale per gli altri 3 ruoli** (DEF/MID/FWD): fatta finora solo per MID (`mls_mid_discovery_global.py`, 346 giocatori su 30 squadre). L'utente vuole lanciarla DOPO aver chiuso il giro di affinamento sui Finding 3+F — non lanciarla prima.
5. **Bot Supremo test run in corso**: aspetta `stop`/`s` dall'utente per essere cancellato manualmente (vedi sezione 1).
6. **Task in background sulla correlazione GK-DEF-FWD** (`task_c858ec41`): verificarne lo stato appena possibile.

## 4. File chiave per orientarsi rapidamente

- `formazione_mls/build_formazione_finale.py` — fusione finale, logica multi-formazione + capitano + classic/in_season
- `formazione_mls/predict/test_gk.py` / `test_def.py` / `test_mid.py` / `test_mls_fwd_all.py` — formula di scoring per ruolo (oggetto dell'audit)
- `.github/workflows/formazione_completa.yml` — pipeline unica end-to-end
- `docs/GUIDA.md`, `docs/HANDOFF.md` — documentazione storica del progetto (pre-esistente, non toccata in questa sessione)
