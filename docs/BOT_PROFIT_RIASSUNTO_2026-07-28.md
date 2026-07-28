# BOT PROFIT — Riassunto sessione 28/07 — per continuare su un'altra chat/account

**Lavorato direttamente su `main`** (come da sessioni precedenti dal 27/07 in poi). Tutto quanto descritto qui è già **committato e pushato**. `git pull origin main` (o Fetch/Pull da GitHub Desktop) per ripartire — non serve altro branch.

**IMPORTANTE — l'utente non ha un terminale**: usa solo **GitHub Desktop**. Non dirgli mai "lancia questo comando" — fai tu ogni operazione git (pull/push/commit) dall'ambiente Claude Code, oppure spiega il click-per-click su GitHub Desktop se serve che lo faccia lui. Ha chiesto una spiegazione di cosa fa `git pull` per imparare, ma resta un compito da fare io per lui in pratica.

## 0. Contesto: continuazione di cosa

Sessione partita da una domanda di orientamento ("fammi un recap di bot profit") su un repo dove **due bot diversi convivono**: `bot_profit.py` (questo, tracking/consigli d'acquisto, NON gioca/offre) e `bot_definitivo.py` (autobuy/makeoffer reale, tutt'altra storia di calibrazione — non confonderli, il file di memoria `bot_definitivo_margin_calibration.md` riguarda l'ALTRO bot). Vedi `docs/BOT_PROFIT_RIASSUNTO_2026-07-26.md` e `_2026-07-27.md` per tutta la storia precedente (modalità SNAPSHOT, esclusione aste/acquisto istantaneo, pattern giorni-da-partita, output ridotto a 1 file).

## 1. Cosa è stato fatto, in ordine cronologico

### A. Default a snapshot MLS-only (commit `ee027d8dc`)
Prima di questa sessione, i default del workflow erano `snapshot_mode=no` (modalità a eventi, tutte le leghe) — non quello che l'utente pensava fosse configurato. Ora i default (sia nel workflow YAML che negli env-fallback di `bot_profit.py`, per coerenza anche fuori dal workflow) sono: `SNAPSHOT_MODE=si`, `TEAM_WHITELIST=<30 squadre MLS 2026>`, `SNAPSHOT_LEAGUE_SLUG=mlspa`.

### B. Output ristrutturato: 1 solo file, in root (commit `b9f9ca0af`)
Richiesta esplicita: niente più split per-campionato né file di "consigli d'acquisto" separati. Ora:
- Cartella spostata da `scanners/bot_profit_output/` a **`bot_profit_output/` in root del repo**.
- **Un solo CSV**: `bot_profit_output/profit_tracking_<timestamp_utc>.csv`, top 50 per `potenziale_score`, in season+classic mescolati (colonna `tipo_carta`), tutte le leghe insieme.
- Rimossi: split per-campionato, `consiglio_acquisto_mls.csv/.txt` (`write_buy_signals`), `normalize_league_filename` (dead code).
- Rimane separato `pattern_giorni_da_partita.csv` (diagnostica, non è "l'output" classifica).

### C. BUG REALE trovato e corretto: roster a 0 giocatori (commit `1f3a09ce7`)
Prima run di verifica dopo i due punti sopra: **tutte le 30 squadre MLS fallivano** con errore GraphQL `Selecting allPlayerGameScores within a list of AnyPlayerInterface (anyPlayers) is not supported`. Causa: un commit del 27/07 (sessione precedente) aveva annidato `allPlayerGameScores` dentro la query di roster (`TEAM_ROSTER_QUERY`) sostenendo (mai riverificato dopo) che funzionasse — Sorare lo rifiuta, stesso limite già noto per `anyFutureGames`. **Fix**: rimosso da lì, spostato per-giocatore insieme alla prossima partita. Verificato: roster torna a popolarsi correttamente (~500 giocatori rilevanti su 30 squadre).

**Lezione**: non fidarsi di un commento "verificato" nel codice se non c'è un run reale successivo a confermarlo — qui l'affermazione era sbagliata e nessuno l'aveva ritestata.

### D. Ottimizzazione velocità: query accorpate (commit `c2fc5e898`)
Dopo il fix C, la run funzionava ma con **292 HTTP 429** su ~950 query in 9m30s. Studiate le query: per ogni giocatore "ok" servivano 3 round-trip separati (prezzo/live-offers, prossima+ultima partita, transazioni). Creata `fetch_player_combined_snapshot()` — **root fields diversi (`tokens`/`anyPlayer`) sullo STESSO slug in un'unica query** (diverso dal caso già rifiutato da Sorare che riguardava PIÙ slug aliasati). Risultato misurato: **da 292 a 14 HTTP 429, da 9m30s a 5m20s** (run successive hanno mostrato variabilità naturale, es. 228 429 su un'altra run — dipende dal carico Sorare in quel momento, non un regresso).

### E. Link diretto alla carta Sorare (commit `be0135c2e`, poi corretto lo stesso giorno)
Nuova colonna CSV `link_sorare`. **Attenzione**: il primo tentativo puntava a `.../market/shop/manager-sales/<slug>/limited` (pattern già usato in altri bot del repo) — l'utente ha chiesto esplicitamente `.../football/players/<slug>` (pagina profilo giocatore, non lo shop). Nel viewer HTML il nome giocatore è ora un link cliccabile (non link_sorare come colonna a sé).

### F. Indicatore "trend recente" (commit `bfa348615`)
**Scoperta chiave**, verificata dall'utente su un caso reale (Anthony Markanich): lo `sconto_percent` (minimo attuale vs media trimmed a 7gg) può essere ENORME (40-60%) non perché sia una vera occasione, ma perché il prezzo è **già crollato** nei giorni recenti e la media a 7gg è "vecchia" (include i giorni pre-crollo). Aggiunta:
- `_split_recent_vs_storico()`: confronta media transazioni ultimi **2 giorni** (`TREND_RECENT_WINDOW_DAYS`) vs media del resto della finestra a 7gg.
- Se la recente è **>10% più bassa** (`TREND_FLAT_THRESHOLD_PERCENT`) → `trend_recente='down'` (sconto INAFFIDABILE, il mercato si sta ancora sgonfiando). Se **>10% più alta** → `'up'` (sconto affidabile, mercato in salita). Altrimenti `'flat'` (stabile, sconto affidabile).
- CSV: 2 nuove colonne numeriche (`media_transazioni_recente_eur`, `media_transazioni_storica_eur`, per analisi future) + `trend_recente`.
- **NON tocca `potenziale_score`** — deliberatamente lasciato solo come indicatore visivo finché non si decide insieme se/come pesarlo nello score (coerente con l'approccio "un tema alla volta" già usato per bot_definitivo).
- Verificato su run reale: 31 `down` / 9 `flat` / 2 `up` su 50 righe — la maggioranza dei "top sconto" erano proprio `down`, confermando il sospetto.

### G. Viewer HTML: freccia, compattazione, ordinamento default, bottone Top 5 (commit `984c95a1c`, `5313c12ae`, `cfe3fdd5b`)
- Freccia `trend_recente` (↓ rosso / → grigio / ↑ teal, tooltip esplicativo) mostrata **subito accanto al nome** (non in fondo alla tabella dove serviva scroll orizzontale).
- Rimosse 3 colonne poco utili dalla tabella (`league_slug`, `l40`, `ore_alla_partita` — restano nel CSV grezzo).
- Link nome giocatore: da blu default browser a colore ereditato dal testo (sottolineatura discreta, teal solo in hover).
- **Ordinamento di default all'apertura**: prima per `trend_recente` (flat/up sopra down — rank up=2/flat=1/down=0/mancante=-1, NON alfabetico), poi per `potenziale_score` decrescente. Il criterio trend è "pinnato" nella sort-chain così resta fisso anche cliccando altre colonne.
- **Bottone 🏆 Top 5** (toggle): evidenzia (bordo teal + sfondo tenue + trofeo sul nome) le 5 carte con la miglior combinazione trend+score — pesa lo score per un moltiplicatore di affidabilità del trend (`up`×1.2, `flat`×1.0, `down`×0.5, mancante×0.8). Calcolato SEMPRE su tutto il dataset (non sul filtrato). **Solo lato viewer (JS), non tocca `potenziale_score` né il CSV/bot_profit.py** — stessa logica "un tema alla volta", non ancora promossa a formula ufficiale.

## 2. Concetto chiave da ricordare (spiegato più volte all'utente)

**Non fidarsi dello sconto% da solo.** Un altissimo sconto% con freccia `down` è probabilmente un mercato in caduta (rischio: il prezzo continua a scendere o si è solo "assestato" più in basso, non tornerà alla vecchia media) — trattarlo con sospetto anche se lo score complessivo è alto. Un sconto% con freccia `flat`/`up` è più affidabile come vera occasione. Il bottone Top 5 codifica proprio questa euristica.

## 3. Stato esatto del codice — parametri attuali

- `SNAPSHOT_MODE=si`, `TEAM_WHITELIST=<30 squadre MLS>`, `SNAPSHOT_LEAGUE_SLUG=mlspa` (default sia workflow che script)
- `OUTPUT_DIR = 'bot_profit_output'` (root, non più sotto `scanners/`)
- `TOP_N_OUTPUT=50`, `MIN_TRANSACTIONS_FOR_RANKING=15`
- `TREND_RECENT_WINDOW_DAYS=2`, `TREND_FLAT_THRESHOLD_PERCENT=10.0` (soglie di partenza, MAI ricalibrate su più dati — vedi sezione 4)
- `fetch_player_combined_snapshot()` sostituisce (nel percorso snapshot) le vecchie `fetch_all_live_offers` + `fetch_player_next_game` + `fetch_transaction_nodes_window` chiamate separatamente — 1 query per giocatore nel caso comune
- CSV_FIELDNAMES aggiornati: `link_sorare`, `trend_recente`, `media_transazioni_recente_eur`, `media_transazioni_storica_eur` aggiunti; nessun campo rimosso dal CSV (solo dal viewer)
- File coinvolti: `scanners/bot_profit.py`, `scanners/bot_profit_viewer.html`, `.github/workflows/bot_profit.yml`, `bot_profit_output/` (root)

## 4. Prossimi passi aperti (da confermare con l'utente, non presumere)

1. **Decidere se/come far pesare il trend in `potenziale_score`** (oggi è solo un'euristica lato-viewer nel bottone Top 5, mai promossa a formula ufficiale in Python). L'utente ha reagito bene al bottone Top 5 — potrebbe voler far diventare quella logica (o una tarata meglio) parte dello score reale, ma NON presumere, chiedere prima.
2. **`TREND_RECENT_WINDOW_DAYS=2` e `TREND_FLAT_THRESHOLD_PERCENT=10.0`** sono stime di partenza dell'assistente, mai discusse a fondo né calibrate su più casi reali — se si torna a lavorarci, raccogliere altri esempi reali (stesso metodo usato per bot_definitivo: casi concreti in EUR, non ipotesi astratte) prima di cambiarle.
3. **Continuare a rivedere l'output nel concreto** — la sessione si è fermata proprio mentre si guardava la classifica reale (Denkey/Fernández-Mercau in cima dopo il nuovo ordinamento), non ancora rivisti altri casi/pattern.
4. **429 residui**: passati da 292 a 14 poi risaliti a 228 in un'altra run — variabilità di carico lato Sorare, non ancora chiaro se serva un'ulteriore ottimizzazione o se sia accettabile così.

## 5. Note tecniche per chi riprende

- **L'utente non ha terminale, solo GitHub Desktop** — fare sempre io le operazioni git (commit/push/pull), non dirgli di lanciare comandi.
- **Collisioni con l'altra sessione Claude Code parallela** (stessa working directory, lavora su formazioni/modelli predittivi): successe PIÙ VOLTE in questa sessione — commit miei "risucchiati" dentro commit dell'altra sessione con messaggio non pertinente (contenuto comunque corretto, solo attribuzione sporca), e file non miei (`discovery_fixture.py`, `formazione_mls/...`, `generatore_formazioni/...`) modificati in working directory che bloccavano `git rebase`. **Pattern che ha funzionato**: quando la working directory ha modifiche non mie non committate, usare un **worktree temporaneo** (`git worktree add /tmp/xxx origin/main`, poi `git cherry-pick <mio commit>`, `git push origin HEAD:main`, poi `git worktree remove --force`) invece di toccare/stashare il lavoro altrui. Se invece la working directory è pulita, `git rebase origin/main && git push` diretto basta.
- **Verifica sempre `git status --porcelain` prima di `git add`** — più volte in sessione sono comparsi file modificati da altre sessioni che NON andavano committati insieme ai miei.
- Comando per lanciare una run di verifica: `gh workflow run bot_profit.yml --ref main -f snapshot_mode=si -f min_transactions_for_ranking=15 -f max_tracked_cards=2000 -f check_classic=si` (team_whitelist/snapshot_league_slug ora hanno default corretti, non serve più passarli espliciti). Monitorare con `gh run view <id> --json status,conclusion` in loop, poi `gh run view <id> --log` a fine run per i dettagli.
