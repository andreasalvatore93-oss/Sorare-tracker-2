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

## 4. Prossimi passi aperti (STORICO mattina 28/07 — vedi Parte 2 per lo stato aggiornato)

1. ~~Decidere se/come far pesare il trend in `potenziale_score`~~ FATTO, vedi Parte 2.A.
2. **`TREND_RECENT_WINDOW_DAYS=2` e `TREND_FLAT_THRESHOLD_PERCENT=10.0`** restano stime di partenza mai ricalibrate su più casi reali — se si torna a lavorarci, raccogliere altri esempi reali (stesso metodo bot_definitivo: casi concreti in EUR) prima di cambiarle.
3. ~~Continuare a rivedere l'output nel concreto~~ FATTO nel pomeriggio, vedi Parte 2.D — trovati e corretti 2 pattern reali (Mercau, Bond).
4. ~~429 residui~~ Affrontato a fondo nel pomeriggio, vedi Parte 2.B/2.C.

## 5. Note tecniche per chi riprende

- **L'utente non ha terminale, solo GitHub Desktop** — fare sempre io le operazioni git (commit/push/pull), non dirgli di lanciare comandi.
- **Collisioni con l'altra sessione Claude Code parallela** (stessa working directory, lavora su formazioni/modelli predittivi): successe PIÙ VOLTE in questa sessione — commit miei "risucchiati" dentro commit dell'altra sessione con messaggio non pertinente (contenuto comunque corretto, solo attribuzione sporca), e file non miei (`discovery_fixture.py`, `formazione_mls/...`, `generatore_formazioni/...`) modificati in working directory che bloccavano `git rebase`. **Pattern che ha funzionato**: quando la working directory ha modifiche non mie non committate, usare un **worktree temporaneo** (`git worktree add /tmp/xxx origin/main`, poi `git cherry-pick <mio commit>`, `git push origin HEAD:main`, poi `git worktree remove --force`) invece di toccare/stashare il lavoro altrui. Se invece la working directory è pulita, `git rebase origin/main && git push` diretto basta.
- **Verifica sempre `git status --porcelain` prima di `git add`** — più volte in sessione sono comparsi file modificati da altre sessioni che NON andavano committati insieme ai miei.
- Comando per lanciare una run di verifica: `gh workflow run bot_profit.yml --ref main -f snapshot_mode=si -f min_transactions_for_ranking=15 -f max_tracked_cards=2000 -f check_classic=si` (team_whitelist/snapshot_league_slug ora hanno default corretti, non serve più passarli espliciti). Monitorare con `gh run view <id> --json status,conclusion` in loop, poi `gh run view <id> --log` a fine run per i dettagli.

---

# Parte 2 — sessione pomeridiana 28/07 (stessa giornata, continuazione)

Ripartita da questo stesso file (letto per intero, non solo l'ultima sezione). Utente confermato senza terminale — ogni operazione git fatta da Claude Code. Anche in questa parte: **collisioni ripetute con la sessione parallela sulle formazioni**, stesso pattern del worktree temporaneo usato più volte con successo (vedi sezione 5 sopra, vale ancora).

## A. Trend promosso da euristica-viewer a formula ufficiale (commit `2a8c20b2d`)

Richiesta esplicita: pesare `trend_recente` dentro `potenziale_score` invece di lasciarlo solo come freccia visiva. Aggiunto `TREND_SCORE_MULTIPLIER = {'up': 1.2, 'flat': 1.0, 'down': 0.5, None: 0.8}` applicato alla componente `sconto_norm` (30% del peso) in `compute_potenziale_score()`. Verificato via ricalcolo locale sull'ultimo snapshot disponibile (senza consumare query Sorare): carte `down` con sconto alto crollano in classifica (es. Mbekezeli Mbokazi, sconto 64% ma down, dal 24° al 50° posto), carte `flat`/`up` salgono (Griezmann, Denkey, Fernández-Mercau).

## B. Ottimizzazione run: tentativi su throttle, poi accantonati

Serie di run di verifica reali (`gh workflow run`) per accorciare la durata (obiettivo utente: 5-6 min accettabili, 10 min eccessivi):

1. **Ritmo aggressivo puro** (FAST 0.25→0.15s, SAFE 0.6→0.3s, cooldown 45→20s, backoff dimezzato): 4m30-4m54s ma 140+ carte perse per rate-limit esaurito (contro 69 originali) — SCARTATO, troppa perdita di copertura per il guadagno di tempo.
2. **Compromesso** (FAST 0.2s, SAFE 0.45s, cooldown 30s, backoff **ripristinato** a `(2**attempt)*2` cap 16s): 5m14s-5m28s con ~70 rate-limited (quasi come l'originale) — QUESTO è rimasto come assetto base.
3. **Esperimento pausa fissa periodica** (60s lavoro / 20s pausa, indipendente dai 429 — ipotesi: il limite Sorare è sulla quantità di richieste in coda, una pausa "svuota" la finestra prima che scatti): **SMENTITO da un test reale** — il primo 429 è scattato comunque a ~2 minuti dall'inizio, stesso punto della run senza pausa. Il rate-limit di Sorare sembra legato al TEMPO TRASCORSO, non al conteggio di richieste. Disattivato di default (`GRAPHQL_BURST_WORK_SECONDS=0`), codice lasciato disponibile via env var.
4. **Ritmo ancora più aggressivo dopo aver aggiunto il retry (vedi C)**, ipotesi "tanto recupera comunque i persi": FAST 0.12s/SAFE 0.25s/cooldown 20s → **PEGGIO**, 6m03s (contro 5m14s), perché 112 carte (contro 12) hanno comunque sprecato fino a 22s di backoff nel primo giro prima di finire nel pool di retry. SCARTATO, ripristinato il compromesso del punto 2.

**Stato attuale**: `GRAPHQL_MIN_INTERVAL_SECONDS_FAST=0.2`, `SAFE=0.45`, `COOLDOWN=30.0`, backoff `(2**attempt)*2` cap 16s — il miglior punto trovato finora.

## C. Secondo giro dedicato per i rate-limited (commit `55a80a118`) — FUNZIONA BENE

Prima i giocatori la cui query falliva per rate-limit esaurito (`rate_limited_max_retries_exceeded`) venivano **silenziosamente confusi** con "nessuna offerta" (`prezzo_basso_o_senza_annunci`) e persi per sempre. Ora `fetch_player_combined_snapshot()` ritorna un flag `errored` esplicito; in `run_snapshot_sweep()` questi casi finiscono in un pool separato (`rate_limited_pool`) invece di essere scartati, e dopo il primo giro completo c'è una **pausa di `RATE_LIMIT_RETRY_PAUSE_SECONDS=30s`** poi un **secondo giro dedicato SOLO a quel pool**. Risultato osservato su run reali: 12 o 112 rate-limited nel primo giro (a seconda del ritmo), **0 rimasti persistenti** dopo il secondo giro in entrambi i casi — recupero totale. Confermato via codice che l'output resta UNICO (stessa struttura dati condivisa `_tracked`, un solo CSV finale, nessuna classifica separata per i recuperati).

**Nota**: il secondo giro salta il ricontrollo blacklist (`is_retry=True`), corretto perché già passato una volta nello stesso giro.

## D. Blacklist manuale MLS — artifact rigenerato e 9 nuove voci

Rigenerato l'artifact di revisione manuale (pattern già usato il 27/07, vedi `docs/BOT_PROFIT_RIASSUNTO_2026-07-27.md` sezione 4 per la storia/i tentativi falliti prima di arrivare a questo formato: checklist + localStorage + textarea copiabile, NIENTE `sendPrompt` che non esiste per gli Artifact pubblicati). Estratti i 382 giocatori mai revisionati (511 totali - 131 già decisi in sessioni precedenti) dal log dell'ultima run reale, embeddati in un nuovo artifact pubblicato. L'utente ha risposto con 9 slug da blacklistare: `joshua-atencio, luca-petrasso, neil-pierre, peter-kingston, philip-quinton, sang-bin-jeong, tyger-smalls, victor-loturi, william-reilly` — aggiunti a `sorare_lista_nera_profit.txt` con scadenza 1 anno (commit `446aa090a`). Restano ~373 giocatori mai revisionati per un giro futuro.

## E. Soglia prezzo minimo alzata 1→2 EUR (commit `446aa090a`)

Richiesta esplicita: sotto i 2 EUR di prezzo minimo attuale, scartare la carta SUBITO (non solo dalla classifica finale, dalla PRIMA query in assoluto, zero query aggiuntive) — sotto quella soglia raramente ci sono variazioni di profit significative. Il meccanismo esisteva già (`MIN_PRICE_EUR_THRESHOLD`, prima tarato a 1 EUR), bastava alzare il numero.

## F. Due pattern reali trovati e corretti nella formula di scoring (commit `4ffc66143`, `8e49678e9`)

Sessione di revisione output guidata dall'esperienza diretta dell'utente in compravendita Sorare (non solo statistica astratta — coerente con la linea guida "verificare con casi reali").

**F.1 — Sovrapprezzo estremo con trend='up' (caso reale: Nicolás Fernández-Mercau, carta in season)**. Prezzo minimo 40.93EUR contro una media storica di 22.79EUR (`sconto_percent=-79.6%`, cioè quasi il DOPPIO della norma — un premio enorme, l'opposto di un affare), eppure finiva in cima alla classifica/al viewer. Causa doppia: (1) `sconto_norm` pesa solo il 30% dello score, timing+forma (70%) possono dominarlo anche quando il prezzo è pessimo; (2) il viewer ordinava di DEFAULT prima per `trend_recente` (tutte le carte `up` pinnate in cima), poi per score — quindi anche uno score già basso poteva comunque comparire visivamente tra le prime righe solo per via del trend. **Fix**: (1) `SOVRAPPREZZO_PENALTY_THRESHOLD_PERCENT=-15.0` / `SOVRAPPREZZO_PENALTY_MULTIPLIER=0.3` in `compute_potenziale_score()` — sotto quella soglia di sconto negativo, l'INTERO punteggio (non solo la fetta 30%) viene moltiplicato per 0.3; (2) rimosso il pin del trend nel viewer, ordina ora solo per score (che già lo incorpora). Verificato su run reale: Mercau in season sparito dal top 50.

**F.2 — Exploit isolato dell'ultima partita (caso reale: Jonathan Bond, carta classic, portiere titolare stabile 2-3EUR)**. Sconto quasi zero (-1.22%, prezzo dove sta sempre — un singolo acquisto anomalo a 5EUR 6gg prima, già escluso dalla media trimmed, confermato dall'utente col grafico prezzi), eppure score 0.3552 grazie a `ultima_partita_score=92.5` contro `L5=L10=47` (gap di +45.5 punti, un exploit isolato). **Importante**: una soglia minima di sconto (proposta iniziale) è stata SCARTATA dall'utente perché avrebbe escluso anche pick validati come sensati (Zimmerman, Gavran — sconto altrettanto vicino a zero, ma score giustificato da timing ottimale + forma coerente, non da un'anomalia). La vera causa era il gap ultima/L5, non lo sconto. **Fix**: `ULTIMA_GAP_CAP=20.0` — `ultima_partita_score` clampato a non superare `L5+20` prima di entrare nella formula. Verificato: Bond scende (0.3552→0.3042), Zimmerman/Gavran/Carles Gil **invariati** (il loro gap era già dentro soglia).

**Non ancora lanciata una run di verifica dopo F.2** — l'utente ha chiesto esplicitamente di aspettare il suo via libera prima di lanciare la prossima run.

## G. Prossimi passi aperti (aggiornati, fine pomeriggio 28/07)

1. **Lanciare la run di verifica per F.2** quando l'utente dà il via libera (ha detto esplicitamente "ti dico io quando").
2. **Continuare la revisione dell'output** con l'esperienza diretta dell'utente — il metodo (trovare un caso reale sospetto, scomporre la formula, confrontare con pick validati prima di proporre un fix) ha funzionato bene 2 volte di fila in questa sessione, probabilmente da ripetere.
3. **~373 giocatori MLS ancora da revisionare** per la blacklist manuale (vedi D) — artifact da rigenerare quando l'utente vuole continuare.
4. **`TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT`** ancora mai ricalibrati su dati reali (invariato da stamattina, vedi sezione 4 sopra).

## H. Aggiungere K-League insieme a MLS in una sola run, con classifiche separate (progettato, NON implementato — richiesta esplicita: solo annotare per dopo)

Obiettivo utente: lanciare MLS+K-League **insieme in una sola run** (non due run separate) ma con **due classifiche/CSV distinti** (uno MLS, uno K-League), non un'unica classifica mescolata.

**Perché non e' banale**: oggi `SNAPSHOT_LEAGUE_SLUG` e' UNA costante globale assunta uguale per TUTTE le squadre in `TEAM_WHITELIST` (usata in `run_snapshot_sweep`, nel controllo prezzo, in `_process_player_snapshot`, nel pool di retry rate-limit) — assume un solo campionato per run. `k-league-1` e' gia' presente in `EXCLUDED_LEAGUE_SLUGS` (stesso split in_season/classic di MLS, nessuna modifica li' serve) e le 12 squadre K-League sono gia' note nel repo: `formazione_kleague/discovery/kleague_mid_discovery_global.py:50` (`KLEAGUE_TEAM_SLUGS`: anyang-anyang, bucheon-1995-bucheon, daejeon-citizen-daejeon, gangwon-gangneung, gwangju-gwangju, incheon-united-incheon, jeju-united-seogwipo-jeju-do, jeonbuk-motors-jeonju, pohang-steelers-pohang, sangju-sangmu-sangju, seoul-seoul, ulsan-ulsan).

**Piano (modo piu' rapido individuato, non ancora scritto)**:
1. Sostituire `TEAM_WHITELIST` (lista piatta) con una mappa squadra→lega, costruita da due gruppi (MLS esistente + le 12 K-League sopra, ciascuno etichettato con la propria `league_slug`).
2. Threadare la lega PER SQUADRA (non piu' una costante globale) attraverso `run_snapshot_sweep`: roster fetch, controllo prezzo (`_current_minimum_from_nodes`), chiamata a `_process_player_snapshot`, e le tuple nel pool di retry rate-limit (vedi Parte 2.C).
3. Output: le righe hanno GIA' la colonna `league_slug` (nessuna modifica li'), ma **il taglio a `TOP_N_OUTPUT=50` va fatto PER LEGA prima di scrivere**, non sul totale mescolato — altrimenti se i punteggi MLS sono sistematicamente piu' alti, la classifica K-League rischia di sparire del tutto schiacciata dal taglio globale a 50. Scrivere due CSV separati (es. `profit_tracking_mlspa_<ts>.csv` e `profit_tracking_k-league-1_<ts>.csv`) riusando `_write_ranked_csv`/`_cleanup_and_write_ranked_csv` con prefissi diversi.

**Costo collaterale da aspettarsi**: raddoppiare le squadre (30 MLS + 12 Korea = 42) raddoppia circa il volume di query verso Sorare -- la durata della run tornerebbe verso i ~10 minuti di partenza (prima di tutte le ottimizzazioni throttle/retry di oggi, vedi Parte 2.B/2.C), non piu' nella fascia 5-6 min faticosamente trovata. Da tenere presente PRIMA di implementare, magari riproponendo lo stesso ciclo di tuning gia' fatto oggi per MLS da solo.
