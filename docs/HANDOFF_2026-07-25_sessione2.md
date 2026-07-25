# Handoff sessione 25/07 (seconda parte) — per continuare su un altro account Claude Code

Repo: `Sorare-tracker-2`, branch `main`. Tutto lo stato descritto qui è già **committato e pushato** su GitHub (ultimo commit `bbcbd257`), quindi la nuova sessione può ripartire semplicemente con `git pull` — non c'è lavoro locale non salvato da recuperare.

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

### E. Audit logico del modello (agente worktree, completato)
Lanciato un agente in un worktree isolato per revisionare la formula di scoring dei 4 ruoli (`formazione_mls/predict/test_*.py`) cercando errori di logica nel peso dei fattori. **Findings principali** (per impatto):

1. **[CORRETTO in questa sessione]** GK: la produzione applicava 7 fattori granulari che la calibrazione aveva scartato (peggioravano il MAE). Fix applicato: rimossi dallo `score_atteso`, restano solo diagnostici in output con nota "non applicato". Commit `cc489748`.
2. **[DA VALUTARE]** La scala fissa "1%/punto" in `compute_split_factor` (identica per ogni gruppo granulare, ogni ruolo) rende quasi tutti i fattori granulari inerti (0.98-1.01) tranne `fattore_goalkeeping` del GK — probabilmente perché i gruppi hanno scale di valori molto diverse (RARE_EVENTS ±10pt cap vs GOALKEEPING senza cap, decine di punti). I cap ±10 sono di fatto ridondanti con questa scala. Proposta agente: normalizzare la scala per la variabilità tipica di ogni gruppo (es. delta/deviazione standard storica invece di 1% assoluto), o eliminare i gruppi strutturalmente inerti.
3. **[DA VALUTARE]** L'effetto casa/trasferta viene contato più volte: una volta sul totale (`fattore_casa_trasferta`) e di nuovo dentro OGNI fattore granulare correlato (moltiplicati insieme). Impatto reale contenuto (perché i granulari sono quasi inerti, punto 2) ma sistematico.
4. **[MINORE]** Mix di medie pesate (base esponenziale) e non pesate (fattori casa/trasferta e granulari) — incoerenza concettuale, impatto modesto.
5. **[MINORE]** P(gioca) di fallback (quando manca starterOddsBasisPoints) ha il denominatore troncato dal `break` che riempie la finestra — lieve sovrastima della presenza storica, scatta raramente.
- **Verificato CORRETTO** (nessun bug): segno del fattore forza avversario (coerente nei 4 ruoli), clamp del trend applicato dopo la scalatura per `trend_intensity`, nessun doppio conteggio del bonus clean sheet portiere. Il "rischio di prodotto esplosivo" (0.7^7 per troppi fattori clampati moltiplicati) **non si verifica mai** nei dati reali.

**Prossimo passo suggerito dall'utente**: prima di lanciare la discovery globale (punto F), affinare il modello sui dati che già abbiamo — quindi valutare/implementare i Finding 2-5 insieme all'utente, uno alla volta, PRIMA di ricalibrare con più dati (la ricalibrazione con la discovery globale è un'attività separata e successiva).

### F. Idea futura registrata (NON ancora progettata, task in background disponibile)
L'utente ha proposto una logica di **correlazione tra slot della stessa formazione**, basata su chi gioca contro chi quella giornata:
- **Bonus sinergia GK+DEF stessa partita**: se giocano nella stessa partita, il bonus clean sheet è correlato (stesso evento), andrebbe pesato come upside aggiuntivo nello sceglierli insieme (oggi ogni giocatore è valutato in isolamento).
- **Penalità anti-sinergia GK vs FWD avversario**: se il GK scelto gioca quella giornata CONTRO la squadra del FWD scelto, i bonus tendono ad annullarsi (gol per l'attaccante spesso = niente clean sheet per il portiere) — andrebbe penalizzata/segnalata.
- È stato lanciato un task in background (`task_c858ec41`, titolo "Progettare bonus/penalità correlazione GK-DEF-FWD") con un prompt dettagliato per un agente che prepari una PROPOSTA DI DESIGN (non il codice) — l'utente lo ha già avviato in una sessione locale separata, indipendente da questa. Se non è ancora arrivato un risultato, verificare lo stato di quel task nella nuova sessione.

## 3. Cose in sospeso / da chiedere all'utente

1. **Discovery globale per gli altri 3 ruoli** (DEF/MID/FWD): fatta finora solo per MID (`mls_mid_discovery_global.py`, 346 giocatori su 30 squadre). L'utente ha detto di volerla lanciare DOPO aver affinato il modello sui dati attuali — quindi non lanciarla finché non si è chiuso il giro sui Finding 2-5.
2. **Finding 2-5 dell'audit**: aspettano una decisione dell'utente su come/se correggerli (vedi sezione E sopra). Riprendere da lì la conversazione sulla logica del modello.
3. **Bot Supremo test run in corso**: aspetta `stop`/`s` dall'utente per essere cancellato manualmente.
4. **Task in background sulla correlazione GK-DEF-FWD**: verificarne lo stato.

## 4. File chiave per orientarsi rapidamente

- `formazione_mls/build_formazione_finale.py` — fusione finale, logica multi-formazione + capitano + classic/in_season
- `formazione_mls/predict/test_gk.py` / `test_def.py` / `test_mid.py` / `test_mls_fwd_all.py` — formula di scoring per ruolo (oggetto dell'audit)
- `.github/workflows/formazione_completa.yml` — pipeline unica end-to-end
- `docs/GUIDA.md`, `docs/HANDOFF.md` — documentazione storica del progetto (pre-esistente, non toccata in questa sessione)
