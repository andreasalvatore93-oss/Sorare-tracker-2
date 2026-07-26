# BOT PROFIT — Riassunto sessione 26/07 — per continuare su un altro account Claude Code

**Sessione al ~90% di utilizzo, passaggio ad account nuovo imminente.** Repo `Sorare-tracker-2`, branch di lavoro `claude/missing-recent-chats-687m14` (NON main — vedi sezione 5 sul perché e su come/quando mergeare). Tutto quanto descritto qui è già **committato e pushato** su quel branch. `git checkout claude/missing-recent-chats-687m14 && git pull` per ripartire.

**IMPORTANTE (ribadito esplicitamente dall'utente 26/07, continuazione sessione)**: `main` è il branch PRINCIPALE del progetto — contiene tutto il resto (modello predittivo formazioni, altri bot, ecc.) ed è dove gira altre volte in parallelo un'ALTRA sessione Claude Code dell'utente. Questo branch (`claude/missing-recent-chats-687m14`) è SOLO un ambiente di test isolato per bot_profit — non toccare mai `main` da qui (nemmeno file apparentemente innocui) senza chiedere esplicitamente, e se si nota `main` locale "sporco"/divergente in modo inatteso è quasi certamente perché un'altra sessione sta operando in parallelo sulla STESSA working directory: non improvvisare fix su `main`, isolarsi sul proprio branch e avvisare l'utente.

Oggetto della sessione: **solo ed esclusivamente `scanners/bot_profit.py`** (il bot di tracciamento prezzi "quanto conviene comprare una carta ora", NON gioca/offre, solo osserva). Nessun altro bot è stato toccato.

## 0. Cosa fare SUBITO in apertura di sessione

**L'ottimizzazione roster-level è stata VERIFICATA con successo prima della fine della sessione** — non serve rilanciare altri test per questo. Run di verifica: [30197904740](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30197904740) (commit `e9f4ea6`), completato con esito:
```
[roster] vancouver-whitecaps-vancouver-british-columbia: 224 giocatori totali nel roster storico,
195 scartati subito (non piu' al club), 29 attuali da processare.
```
- Roster reale da processare: **29 giocatori** (invece di 224) — l'ottimizzazione filtra correttamente a livello di query, PRIMA del ciclo principale.
- Tempo step "Run Bot Profit": **27 secondi** (10:16:31→10:16:58), contro gli **85 secondi** del run precedente identico ma senza l'ottimizzazione (30197771931) — **~3x più veloce**.
- Risultati coerenti col run precedente: `{'blacklist': 6, 'ok': 16, 'prezzo_basso_o_senza_annunci': 7}` — stessi 16 giocatori "ok", stesse 18 carte in classifica finale (18 in `profit_tracking.csv`, 13 in season + 5 classic). Nota: la chiave `squadra_diversa` non compare più nelle statistiche di questo run, perché ormai nessuno di quelli passati al ciclo principale viene più scartato per quel motivo (il filtro agisce prima, dentro `fetch_team_roster`) — il controllo di sicurezza in `_process_player_snapshot` resta nel codice ma è diventato di fatto irraggiungibile in condizioni normali, va bene così (costo zero).
- **Nessuna azione di verifica ulteriore necessaria su questo punto.** `git pull origin claude/missing-recent-chats-687m14` per avere i CSV già aggiornati (stato identico a prima, 18 carte, dato che questo run ha solo ri-processato lo stesso roster attuale senza reset).

**L'unico punto rimasto davvero aperto**: l'utente aveva un dubbio ancora da chiudere quando la sessione si è interrotta — voleva rivedere caso-per-caso quali motivi di blacklist tenere per bot_profit e quali no (vedi sezione 4). La discussione è stata sospesa a metà perché nel frattempo sono emersi i due bug del roster (troncamento a 50, poi "storico" invece di "attuale") che l'hanno resa temporaneamente superflua (la blacklist si era sporcata di motivi sbagliati proprio a causa di quei bug, non di una scelta errata sui motivi in sé). Ora che il roster è corretto e verificato, **riprendere quella discussione è il prossimo passo naturale**, ma non presumerlo: chiedere conferma all'utente su come vuole procedere (blacklist stessa dell'utente, o task #2 sulla formula score, o estendere il test).

## 1. Contesto: perché questa sessione, cosa voleva l'utente

L'utente ha 3 obiettivi dichiarati per bot_profit, in quest'ordine:

1. **(FATTO in questa sessione)** Passare da tracciamento "solo quando un evento di mercato arriva via websocket" a uno **snapshot esplicito** di tutte le carte di una squadra/campionato — perché il bot attuale aggiorna una carta SOLO se genera un evento, quindi carte ferme in vendita o già listate prima dell'avvio del bot restavano invisibili.
2. **(NON iniziato)** Rivedere meglio la formula del "potenziale_score" (quanto conviene comprare una carta in quel momento) — task #2 nella todo list, ancora `pending`.
3. **(IN CORSO — fase di test su una squadra sola)** Prima di estendere a tutto MLS/Korea, validare l'approccio su UNA squadra nota all'utente (Vancouver Whitecaps, MLS) per analizzare l'andamento prezzi.

**Scope esplicitamente dichiarato dall'utente**: "qui parliamo solo e soltanto di bot profit" — non toccare altri bot (autobuy, manager, aste, my_cards_profit, sentiment scanner) anche se condividono pattern di codice simili.

## 2. Cosa è stato fatto, in ordine cronologico

### A. Analisi di fattibilità (prima di scrivere codice)
Letto `bot_profit.py`, gli script di discovery in `formazione_mls/discovery/` (pattern di roster fetch via `Club(slug).anyPlayers`) e `mls_sentiment_scanner.py`. Confermato che:
- Non esiste una query pubblica "tutto il mercato di un campionato" — solo `user(slug).searchCards` (scoped a un utente) e `tokens.liveSingleSaleOffers(playerSlug)` (scoped a un giocatore, ma quello sì è già uno snapshot completo per singolo giocatore).
- L'unico modo per uno snapshot di squadra/campionato è enumerare il roster (Club.anyPlayers) e poi chiamare le query già esistenti per-giocatore.
- Costo stimato (poi confermato empiricamente): per una squadra "gonfia" di storico come Vancouver, ~224 giocatori nel roster grezzo, run reale di 40-85 secondi.

### B. Reset dati (richiesta esplicita utente, ripetuto 2 volte in sessione)
Cancellati (con `git rm`) tutti i CSV di output di bot_profit (`scanners/bot_profit_output/*`) e la sua blacklist dedicata (`sorare_lista_nera_profit.txt`) — **NON toccati** gli altri file di stato/blacklist di altri bot. Fatto la prima volta a inizio sessione, poi RIFATTO una seconda volta (commit `7ef2504`) dopo aver scoperto che un run precedente aveva inquinato la blacklist con motivi sbagliati (vedi punto D).

### C. Modalità SNAPSHOT aggiunta a `bot_profit.py` (non uno script separato)
Prima idea (scartata su richiesta esplicita dell'utente: "blocca tutto... non facciamolo con listener websocket ma con snapshot", "mettiamo in whitelist solo Vancouver Whitecaps") era uno script di test a parte — **scartata**, integrato invece direttamente in `bot_profit.py` per riusare tutte le funzioni già esistenti/validate (`get_current_minimum`, `get_player_snapshot`, `get_recent_transaction_prices`, `compute_potenziale_score`, blacklist, CSV persistente).

Nuove variabili d'ambiente / config in `bot_profit.py`:
- `SNAPSHOT_MODE` (si/no, default no) — se attivo, salta il listener websocket ed esegue `run_snapshot_sweep()` invece di `run_listener()`.
- `TEAM_WHITELIST` — lista slug squadra separati da virgola, es. `vancouver-whitecaps-vancouver-british-columbia`.
- `SNAPSHOT_LEAGUE_SLUG` — lega delle squadre in whitelist (default `mlspa`), serve per la logica in_season/classic separati (MLS/K-League).

Nuove funzioni chiave (tutte in `scanners/bot_profit.py`):
- `TEAM_ROSTER_QUERY` / `fetch_team_roster(team_slug)` — query pubblica `Club(slug).anyPlayers`, ora paginata e filtrata (vedi punto D).
- `_process_player_snapshot(player_slug, player_name, expected_team_slug, league_slug, eth_rate)` — equivalente di `_process_one_card_event` ma innescato dal roster invece che da un evento websocket, per ENTRAMBI i tipi (in_season/classic) dello stesso giocatore.
- `run_snapshot_sweep(eth_rate)` — orchestratore: costruisce il roster deduplicato dalle squadre in whitelist, itera, ritorna statistiche (`{'ok': n, 'squadra_diversa': n, 'forma_zero': n, 'nessuna_partita': n, 'prezzo_basso_o_senza_annunci': n}`).
- `main()` ora fa branch su `SNAPSHOT_MODE`: se attivo salta il thread di commit periodico continuo (non serve per un giro singolo) e fa un solo commit finale.

Workflow `.github/workflows/bot_profit.yml` aggiornato con nuovi input `snapshot_mode`, `team_whitelist`, `snapshot_league_slug`, e un input `git_ref` (default `main`) per poter testare su un branch diverso da main senza toccare il comportamento di produzione.

### D. Due bug reali trovati DAI TEST (non da revisione statica) — entrambi corretti

**Bug 1 — commit periodico pushava su `main` invece che sul branch corrente.**
`_commit_output_se_serve()` faceva sempre `git pull --rebase --autostash origin main`, corretto solo quando si gira su main (caso normale in produzione). Sul branch di test, `main` era divergente → rebase falliva → dati del giro persi (commit locale nel runner effimero, mai pushato). **Fix (commit `38705dd`)**: usa `git rev-parse --abbrev-ref HEAD` per il branch corrente, e se il rebase fallisce comunque fa `git rebase --abort` esplicito (altrimenti TUTTI i commit periodici successivi nella stessa run avrebbero continuato a fallire, repo lasciato a metà rebase).

**Bug 2 — roster troncato a 50 E "storico" invece che "attuale" (segnalato dall'UTENTE, non trovato da me).**
L'utente ha confrontato uno screenshot reale della formazione Whitecaps di una partita con l'output del bot e notato che ~14 titolari/panchinari mancavano del tutto. Causa: `anyPlayers(first: 50)` senza paginazione E il campo restituisce TUTTI i giocatori mai passati per il club (storico), non solo la rosa attuale, ordine non legato all'attualità.
- **Fix 1 (commit `92cdc4f`)**: paginazione vera con `pageInfo { hasNextPage endCursor }` (stesso pattern Relay già usato per `liveSingleSaleOffers` altrove nel file) — portato il roster "grezzo" da 50 a 224 giocatori (tutti quelli mai passati per Vancouver).
- **Fix 2 (commit `42ec5f8`)**: aggiunto `snapshot['squadra_slug']` (da `activeClub.slug`, campo GIÀ verificato altrove nel file in `PROFIT_PLAYER_DATA_QUERY`, non inventato) e un controllo in `_process_player_snapshot` che scarta SILENZIOSAMENTE (nessuna blacklist, il giocatore potrebbe essere valido altrove) chi non è più al club atteso.
- **Fix 3 / ottimizzazione (commit `e9f4ea6`, richiesta esplicita utente "velocizziamo")**: invece di scoprire "non è più al club" solo DOPO aver fatto la query di snapshot (1 query sprecata per ognuno dei ~195 ex-giocatori), `activeClub { slug }` viene richiesto DIRETTAMENTE dentro `TEAM_ROSTER_QUERY`, e `fetch_team_roster` filtra PRIMA di ritornare la lista — zero query sprecate sugli ex-giocatori. **VERIFICATO con successo** (run [30197904740](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30197904740), vedi sezione 0 per i numeri): roster da processare sceso da 224 a 29, tempo di esecuzione da 85s a 27s (~3x), risultati finali identici.

### E. Risultati di test raccolti finora (Vancouver Whitecaps, MLS, in_season+classic)

Test finale "pulito" (dopo reset completo, run [30197771931](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30197771931), commit `7ef2504`, PRIMA dell'ottimizzazione del punto D.3):
- Roster storico: 224 giocatori totali
- `squadra_diversa` (ex-giocatori, scartati): 195
- `forma_zero` (L5 assente/zero, blacklistati 30gg): 6
- `prezzo_basso_o_senza_annunci` (scartati, NON blacklistati): 7
- `ok` (dati completi): 16 giocatori → 26 righe (in season+classic)
- **In classifica finale: 18 carte** (13 in season, 5 classic) dopo il filtro liquidità (min 15 transazioni/7gg)

CSV inviati all'utente via `SendUserFile`: `profit_tracking.csv`, `per_campionato/mlspa_in_season.csv`, `per_campionato/mlspa_classic.csv` (tutti in `scanners/bot_profit_output/`, già nel repo pushato).

Osservazione utile per la revisione futura del punto E.2 (formula score): tutti i 18 giocatori tracciati avevano la prossima partita nella stessa finestra oraria (~150-159h, la stessa giornata MLS) — col bucket attuale della formula (`TIMING_WEIGHT_BUCKETS`), questo dà a tutti lo stesso peso_timing (0.7, bucket 96-200h), quindi in quel momento il fattore timing NON differenziava i punteggi — saranno gli altri 3 fattori (ultima_partita, media_generale, sconto%) a fare la differenza finché non ci si avvicina alla partita.

## 3. Stato esatto del codice — cosa leggere per orientarsi

- **`scanners/bot_profit.py`** — file principale, ~1350+ righe. Sezioni rilevanti per questa sessione:
  - Config/env vars: righe ~92-120 (`SNAPSHOT_MODE`, `TEAM_WHITELIST`, `SNAPSHOT_LEAGUE_SLUG`)
  - `TEAM_ROSTER_QUERY` + `fetch_team_roster`: righe ~389-455 circa (query pubblica, paginata, ORA con `activeClub { slug }` incluso e filtro applicato prima del return)
  - `_process_player_snapshot` + `run_snapshot_sweep`: verso la fine del file, prima di `main()`
  - `main()`: branch su `SNAPSHOT_MODE`
- **`.github/workflows/bot_profit.yml`** — input `snapshot_mode`, `team_whitelist`, `snapshot_league_slug`, `git_ref` (quest'ultimo per testare su branch non-main; **ricordarsi di NON lasciarlo settato su un branch di test quando si torna a girare in produzione su main** — di default è `main`, va bene lasciarlo così se non lo si passa esplicitamente).
- **`scanners/bot_profit_output/`** — 3 CSV globali (combinato/in_season/classic) + `per_campionato/mlspa_in_season.csv` + `per_campionato/mlspa_classic.csv`. Stato attuale: dati del run pulito 30197771931 (18 carte), NON ancora aggiornati con l'esito del run di verifica ottimizzazione (30197904740, che riusa questo stato invece di ripartire da zero — è normale, quel run serviva solo a verificare la velocità, non a ripulire di nuovo).
- **`sorare_lista_nera_profit.txt`** — blacklist dedicata bot_profit, formato `motivo,slug,scadenza_iso`. Attualmente contiene solo voci pulite dal run 30197771931 (6 voci `l5_zero_o_assente`).

## 4. Cosa NON è stato ancora deciso / prossimi passi da concordare con l'utente

1. **Discussione sospesa sui motivi di blacklist** (menzionata in apertura): l'utente voleva rivedere caso-per-caso se tenere le blacklist `l5_zero_o_assente` (30gg) e `nessuna_partita` (3gg) così come sono per bot_profit, dicendo "le blacklist per thin market sono particolari" — intendeva probabilmente che i motivi di blacklist pensati per il bot a eventi (che aveva anche logiche di `coverageStatus=NOT_COVERED` lette dalla subscription websocket, MAI applicate nel percorso snapshot perché quel campo non è disponibile fuori dagli eventi) potrebbero non essere tutti adatti a un giro periodico su roster. Non è stata completata: prima è emerso il bug del roster, poi quello dell'ottimizzazione velocità. **Riprendere da qui.**
2. **Verificare il run di ottimizzazione velocità** (sezione 0).
3. **Task #2 della todo list (ancora pending)**: rivedere la formula `compute_potenziale_score` — non ancora iniziato, l'utente ha detto esplicitamente che è il passo successivo dopo aver chiuso lo snapshot.
4. **Estensione ad altre squadre MLS e poi a Korea**: l'utente vuole restare su UNA squadra per ora ("in questa fase di test... mi concentrerei su i giocatori di una sola squadra alla volta"). Non proporre di allargare finché non lo chiede esplicitamente.
5. **`TEAM_ROSTER_MAX_PAGES = 10` con `TEAM_ROSTER_PAGE_SIZE = 100`** (tetto di sicurezza a 1000 giocatori/squadra) — mai stato un problema finora (224 giocatori Vancouver = 3 pagine), ma se una squadra futura avesse uno storico ancora più gonfio potrebbe servire alzarlo. Nessuna azione ora, solo da tenere a mente.
6. **`MIN_TRANSACTIONS_FOR_RANKING = 15`** (default esistente, non toccato in questa sessione) esclude dalla classifica finale carte con poco volume anche se altrimenti valide (es. Kenji Cabrera, Sergio Córdova, Jeevan Badwal-classic nel test) — l'utente non ha ancora commentato se va bene così per lo snapshot mode o se va abbassata/differenziata rispetto al percorso a eventi.

## 4bis. Continuazione 26/07 (stessa sessione, dopo il primo handoff): esclusione aste + acquisto istantaneo dalla media

Richiesta utente: la media prezzi (`get_recent_transaction_prices`, usata sia per `media_transazioni_7gg_trimmed_eur` che per il conteggio liquidità `n_transazioni_usate`) includeva TUTTE le transazioni, incluse le aste (prezzi sistematicamente alti per meccaniche di gioco Sorare) e gli "acquisti istantanei" mostrati nella cronologia vendite Sorare.

Verificato con dati REALI (JSON GraphQL fornito dall'utente su `thomas-muller`, non per ipotesi statistica — pattern preferito dall'utente, vedi [[feedback-verifica-con-casi-reali-sorare]]):
- `deal.__typename == 'TokenAuction'` → Asta (pallino blu nel grafico Sorare) — prezzo non di mercato, escluso.
- `deal.__typename == 'TokenPrimaryOffer'` (sempre `seller: null`) → "Acquisto istantaneo" (quadratino blu) — è un acquisto dalla RISERVA di Sorare stessa, MAI da un altro manager, quindi anche questo non è un prezzo di mercato tra manager. Confermato incrociando un caso puntuale: eurCents 1804 (18,04€), buyer `jasperspeijer`, seller `null`, data 24/07 12:49 → combacia esattamente con la riga "Acquisto istantaneo — Jasperspeijer — 18,04€" mostrata dall'utente.
- `deal.__typename == 'TokenOffer'` con `type` valorizzato (`SINGLE_SALE_OFFER` = Scambio, `SINGLE_BUY_OFFER`/`DIRECT_OFFER` = Offerta diretta) → transazioni reali manager-a-manager, MANTENUTE.

**Fix applicato** (`_is_countable_transaction` in `scanners/bot_profit.py`, commit `540b290ac` poi `4c67b0200`): ora conta come transazione valida solo `bool(deal.get('type'))` — che esiste solo su `TokenOffer`, escludendo automaticamente sia `TokenAuction` che `TokenPrimaryOffer` senza bisogno di elencarli esplicitamente.

**Verificato su run reali** (Vancouver Whitecaps, `thomas-muller` in season, stesso identico giocatore in 3 iterazioni successive):
| Fase | n_transazioni_usate | media_trimmed |
|---|---|---|
| Originale (tutto incluso) | 34/36 | 16,03 € |
| Solo aste escluse (intermedio) | 25/27 | 15,54 € |
| Aste + primary offer escluse (FINALE, attuale) | 16/18 | **12,73 €** |

Effetto complessivo: **-20,6%** sulla media rispetto al dato originale — molto significativo, non un dettaglio cosmetico. Run di verifica finale: [30199091917](https://github.com/andreasalvatore93-oss/Sorare-tracker-2/actions/runs/30199091917). CSV risultante già pushato su questo branch in `scanners/bot_profit_output/`.

**Nota collaterale**: durante questa continuazione, l'ambiente locale ha mostrato un `main` locale temporaneamente "sporco" (merge non richiesto, non pushato) per collisione con un'altra sessione Claude Code dell'utente attiva in parallelo sulla stessa working directory su `main`. Gestito senza toccare il lavoro dell'altra sessione (branch temporaneo isolato per l'unica modifica necessaria su main — un file di workflow diagnostico, poi comunque evitato di pushare altro). Lezione per il futuro: se si opera su questo branch di test e si nota `main` locale in stato inatteso, NON improvvisare — è quasi certamente l'altra sessione, isolarsi e avvisare l'utente (vedi anche [[feedback-parallel-work-separate-chats]] in memoria).

**Prossimo passo naturale** (da confermare con l'utente, non presumere): verificare l'effetto su un secondo giocatore/caso prima di considerare la modifica definitiva, poi tornare al punto sospeso sui motivi di blacklist (sezione 4.1) o al task #2 (formula `compute_potenziale_score`).

## 4ter. Checkpoint successivo (stessa giornata, dopo il 4bis): pattern giorni-da-partita, consigli d'acquisto, riduzione campione full-MLS

Continuazione ulteriore della sessione, dopo il 4bis. Riassunto corposo richiesto esplicitamente dall'utente e salvato qui (non in chat).

### A. Pattern "giorni-da-partita" (nuova funzionalità diagnostica)
Per ogni transazione calcola la distanza (con segno) dalla partita più vicina (passata o futura — non giorno di calendario, perché ogni squadra gioca in giorni diversi). Serve `allPlayerGameScores` esteso (ora `first: 3` con `anyGame { date }`, prima solo `first: 1` senza date) + `anyFutureGames` (già presente). Nuove funzioni in `scanners/bot_profit.py`: `giorni_da_partita_piu_vicina()`, `_registra_pattern_giorni()` (accumulatore globale `_pattern_giorni`, normalizza il prezzo rispetto alla media della carta cosà da poter sommare carte di valore diverso), `write_pattern_giorni_csv()`. Output: `scanners/bot_profit_output/pattern_giorni_da_partita.csv`.

**Risultato sulla run full-MLS (9000+ transazioni reali, vedi punto D)**:

| Giorni da partita | N transazioni | Scostamento vs media |
|---|---|---|
| -4 | 11 (troppo poche) | -22,6% |
| -3 | 286 | -15,9% |
| -2 | 2230 | -9,3% |
| -1 | 2426 | +3,9% |
| 0 (giorno partita) | 2600 | +4,0% |
| +1 | 1433 | +4,0% |
| +2 | 49 (poche) | -2,0% |
| +3 | 13 (troppo poche) | +1,7% |

Zona affidabile (-3 a +1, migliaia di campioni): prezzi bassi 2-3 giorni prima della partita, salgono di ~4% nel giorno partita e il giorno dopo — conferma quantitativamente l'esperienza dell'utente (compra nel calo pre-partita, vendi quando risale, vedi caso reale Thomas Müller nel 4bis).

### B. Consigli di acquisto diretti (nuova funzionalità, in produzione sul branch)
`write_buy_signals()` in `scanners/bot_profit.py`: tra le carte già filtrate per liquidità (`rows_liquidi`, stesso criterio dei CSV normali), seleziona quelle con `sconto_percent >= BUY_SIGNAL_THRESHOLD_PERCENT` (default **10%**, richiesta esplicita utente) — prezzo minimo attuale anomalmente basso rispetto alla media reale delle ultime transazioni, probabile rimbalzo — ordinate per sconto% decrescente, top `BUY_SIGNAL_TOP_N` (default **50**). Target di rivendita = la media 7gg trimmed stessa (solo riferimento, decisione di QUANDO rivendere resta manuale dell'utente, esplicitamente).

Output in DUE file, sempre sovrascritti (mai timestamp):
- `scanners/bot_profit_output/consiglio_acquisto_mls.csv` (dati)
- `scanners/bot_profit_output/consiglio_acquisto_mls.txt` (frasi dirette tipo "COMPRA: Giocatore (tipo) — X€ ora, -Y% sotto la media 7gg (Z€). Target rivendita indicativo: ~Z€. Prossima partita tra N giorni.")

Nome rinominato su richiesta esplicita utente (era `consigli_acquisto.csv/.txt`).

**Bug trovato e corretto durante l'implementazione**: questi due file NON erano nella lista `paths_da_committare` di `_commit_output_se_serve()` — venivano scritti su disco ma mai aggiunti/committati su git. Corretto (commit `7b2092ea2`), ma la run full-MLS del punto D era già partita PRIMA del fix con questo bug attivo → **i consigli d'acquisto di quella run sono andati persi** (mai committati). Verranno prodotti correttamente dalla prossima run.

### C. Scoperta lista squadre MLS + riduzione campione full-MLS
Non esisteva nel progetto un elenco delle squadre MLS — scoperta la query `football { competition(slug: "mlspa") { clubs(first: 40) { nodes { slug name } } } }` (30 squadre 2026, incluso San Diego FC nuovo ingresso). Elenco completo salvato nei log dei workflow run citati sotto.

Riduzione progressiva del roster full-MLS (952 giocatori raw) per il problema dei 429:
1. **Filtro L5** (assente/zero) spostato DENTRO `TEAM_ROSTER_QUERY` (1 query per squadra, non per giocatore) invece che scoperto dopo uno snapshot per-giocatore dedicato — `fetch_team_roster()` ora richiede anche `lastFiveAvgScore` e scarta chi ha 0/None PRIMA di spendere query costose (snapshot/minimo/transazioni, fino a ~9 per giocatore). 952 → 645 giocatori.
2. **Filtro L10 <= 35** (nuova costante `ROSTER_MIN_L10`, default 35.0) aggiunto allo stesso modo (richiesta esplicita utente dopo la run D, il filtro L5 da solo non bastava) — stesso principio, `lastTenAvgScore` ora richiesto nella stessa query roster. **Non ancora testato in produzione.**
3. **Pausa fissa 0,2s** tra un giocatore e l'altro nel giro sequenziale (nuova costante `SNAPSHOT_PLAYER_DELAY_SECONDS`, default 0.2) — per EVITARE i 429 invece di subirli col backoff reattivo (2+4+8s per tentativo fallito), che costa più della pausa stessa. **Non ancora testato in produzione.**
4. `CHECK_CLASSIC` resta invariato/attivo — richiesta esplicita dell'utente di continuare a tracciare anche le carte classic, nessun taglio lì.

### D. Cronologia run full-MLS (tutte su questo branch, `snapshot_mode=si`, tutte e 30 le squadre in `team_whitelist`)
1. **Run [30200119359]** (952 giocatori, PRIMA del filtro L5): **CANCELLATA a metà** (429 mentre l'utente usava l'app Sorare in parallelo per altro) — arrivata a 429/952 giocatori processati. **Nessun dato salvato**: in modalità snapshot il commit avviene SOLO a fine giro completo (`_commit_output_se_serve()` chiamato una volta sola dopo `run_snapshot_sweep()`), mai a metà — a differenza della modalità a eventi che ha un commit periodico ogni `COMMIT_CHUNK_SECONDS`. Punto aperto: valutare se aggiungere un commit periodico anche alla modalità snapshot (non ancora deciso/implementato, l'utente ha detto "non ancora" quando proposto).
2. **Run [30201147701]** (645 giocatori, DOPO il filtro L5, `min_transactions_for_ranking=10`, `max_tracked_cards=2000`): **completata con successo in 28 minuti** (11:58:26-12:26:34 UTC). Riepilogo: `{'ok': 379, 'prezzo_basso_o_senza_annunci': 232, 'no_snapshot': 33, 'nessuna_partita': 1}`, 43/645 (~7%) falliti per 429 dopo 3 tentativi con backoff esponenziale. Ha prodotto i dati del pattern giorni-da-partita (punto A) ma NON i consigli d'acquisto (bug del punto B, corretto dopo).

**Prossimo passo naturale** (da confermare con l'utente): rilanciare la run full-MLS con i nuovi filtri (L10, pausa 0,2s) per verificare l'effetto su tempi/429 — non ancora fatto al momento di scrivere questo checkpoint.

### E. Altro
- Viewer HTML locale dell'utente (`bot_profit_viewer_3.html`, NON nel repo, vive nel suo `Downloads` reale) aggiornato per riconoscere dinamicamente sia `profit_tracking*.csv` (classifica completa) sia `consiglio_acquisto_mls.csv` (consigli diretti) — colonne rilevate dall'header invece di una lista fissa. L'ambiente di esecuzione Claude Code risulta SEPARATO dal PC reale dell'utente (scrivere in un path locale tipo `C:\Users\...\Downloads\...` non lo deposita sul suo computer) — scoperto quando l'utente ha detto di non trovare il file. Soluzione usata: contenuto HTML completo dato in chat da incollare manualmente in un editor locale. Da tenere a mente per richieste future di "mandami/scaricami un file".
- Diagnostica una tantum creata e già usata (`diagnostics/diagnostic_deal_types_thomas_muller.py` + workflow `.github/workflows/diagnostic_deal_types.yml`, quest'ultimo per necessità presente anche su `main` — GitHub richiede che i file `workflow_dispatch` vivano sul branch di default per essere lanciabili via CLI/API, anche se poi eseguono codice di un altro branch tramite `ref` nel checkout). Può essere riusata/adattata per future verifiche ad-hoc sui dati grezzi Sorare.
- Incidente di collisione con l'altra sessione Claude Code dell'utente (attiva in parallelo su `main`, stessa working directory): gestito isolandosi sul proprio branch via branch temporanei quando necessario toccare `main`, mai interferito con l'altro lavoro. Vedi anche nota rafforzata in cima a questo file e [[feedback-parallel-work-separate-chats]] in memoria.

## 5. Nota sul branch

Il lavoro NON è su `main` — è tutto su `claude/missing-recent-chats-687m14` (branch designato per questa sessione dall'ambiente di esecuzione, non scelto dall'utente). **`main` è il branch principale/definitivo del progetto, con tutto il resto del lavoro (modello predittivo formazioni, altri bot) e su cui può girare in parallelo un'altra sessione Claude Code dell'utente** — questo branch di lavoro è puramente un ambiente di test isolato per bot_profit. L'utente non ha ancora chiesto di aprire una PR o mergeare su main — **non farlo senza chiedere esplicitamente**, la sessione era ancora in fase di test/iterazione rapida quando si è interrotta.

## 6. Nota tecnica per la nuova sessione: strumenti usati

- Nessuna credenziale Sorare (`SORARE_COOKIE`/`SORARE_CSRF`) disponibile nell'ambiente di esecuzione Claude Code — impossibile chiamare l'API Sorare direttamente da qui. Ogni test reale richiede lanciare il workflow GitHub Actions (che ha le credenziali nei secrets) con `mcp__github__actions_run_trigger` (method `run_workflow`, `ref` = branch, `inputs` = dict) e poi leggere i risultati via `mcp__github__get_job_logs` (job_id, non run_id — va preso da `mcp__github__actions_list` method `list_workflow_jobs`).
- `mcp__github__get_job_logs` e `mcp__github__actions_list`/`actions_get` spesso superano il limite di token in output diretto quando il run ha centinaia di righe di log (es. 224 giocatori processati) — la risposta arriva già salvata su file locale (`/root/.claude/projects/.../tool-results/*.txt`), va letta con uno script python (`json.load` + filtro righe) invece che con `Read` diretto.
- Il polling diretto via `curl` a `api.github.com` (anche con `$GITHUB_TOKEN` disponibile in env) **non ha funzionato** in un tentativo con `Monitor` (proxy di rete dell'ambiente) — usare sempre i tool MCP `mcp__github__actions_get`/`actions_list`, non curl diretto.
- I run GitHub Actions a volte restano "queued" per diversi minuti senza motivo apparente (non è un problema di concorrenza tra branch, verificato) — se succede, cancellare e rilanciare risolve.
- `send_later` (per programmare un controllo futuro sullo stesso run) ha un minimo di 1 minuto, non permette intervalli più brevi anche se richiesti dall'utente.
