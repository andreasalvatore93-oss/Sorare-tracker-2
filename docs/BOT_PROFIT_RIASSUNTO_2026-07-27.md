# BOT PROFIT — Riassunto sessione 27/07 — per continuare su un altro account Claude Code

**Fine sessione, passaggio ad account nuovo.** Repo `Sorare-tracker-2`. **CAMBIAMENTO IMPORTANTE rispetto alle sessioni precedenti (26/07): da oggi si lavora DIRETTAMENTE su `main`**, non più su un branch di test isolato. L'utente lo ha chiesto esplicitamente durante questa sessione ("ora mi sembra più sensata... implementiamo la velocità... committa già nel main", poi ribadito più volte). Tutto quanto descritto qui è già **committato e pushato su `main`**. `git pull origin main` per ripartire — non serve fare checkout di nessun altro branch per bot_profit.

**Nota su `main` condiviso**: `main` riceve commit frequenti da un'altra sessione Claude Code dell'utente attiva in parallelo (lavora su un altro filone, "Generatore Formazioni"/modelli predittivi). Più volte in questa sessione un `git push` su `main` è stato respinto per non-fast-forward e ha richiesto fetch+rebase+ripush. **Prima di ogni push su `main`, controllare sempre `git log -1 origin/main` e fare fetch+rebase se necessario** — non è un errore, è normale in questo repo. Se il rebase va in conflitto su file di bot_profit vs. altri file recenti, i conflitti finora erano sempre risolvibili in favore delle proprie modifiche scoped (mai toccare file di altri bot).

Oggetto della sessione: **solo ed esclusivamente `scanners/bot_profit.py`** (+ il suo workflow, il suo viewer HTML, la sua blacklist dedicata, i suoi CSV di output). Nessun altro bot toccato.

## 0. Cosa fare SUBITO in apertura di sessione

1. **C'è un artifact già pubblicato e aperto dall'utente** con una checklist interattiva per la revisione manuale della blacklist (vedi sezione 4 per i dettagli) — **399 giocatori ancora da rivedere**. L'utente potrebbe tornare con una nuova lista di slug selezionati da incollare in chat (formato: lista di slug separati da virgola, es. `slug1,slug2,slug3`). Se arriva, va aggiunta a `sorare_lista_nera_profit.txt` con `motivo=blacklist_manuale`, scadenza 365 giorni, **controllando prima i duplicati** con le voci già presenti (108 già inserite). Vedi sezione 4 per lo script esatto già usato.
2. **Nessun run di verifica è stato lanciato dopo l'ultima modifica di codice** (la ristrutturazione output a file singolo con timestamp, sezione 3). Il prossimo passo naturale è lanciare un run full-MLS per verificare che tutto funzioni insieme (velocità + formula + output + le 108 blacklist manuali che dovrebbero ridurre ulteriormente il roster). **Non presumere, chiedere conferma prima di lanciare** (i run costano tempo/rate-limit, l'utente è stato esplicito sul volerli lanciare lui/insieme).
3. **`scanners/bot_profit_output/` su main NON ha attualmente nessun file `profit_tracking_*.csv`** (rimosso nel reset, nessun run successivo lo ha rigenerato con la nuova struttura) — solo `consiglio_acquisto_mls.csv/.txt` e `pattern_giorni_da_partita.csv`, entrambi STALE (dati del run worker=10 delle 07:14-07:26 UTC, prima della ristrutturazione output). Il prossimo run risolverà questo.

## 1. Contesto: da dove veniva questa sessione

Continuazione diretta delle sessioni bot_profit del 26/07 (vedi `docs/BOT_PROFIT_RIASSUNTO_2026-07-26.md` per tutta la storia precedente: modalità SNAPSHOT, esclusione aste/acquisto istantaneo dalla media, pattern giorni-da-partita, consigli di acquisto). Questa sessione è partita da un worktree/branch (`claude/bot-profit-summary-dev-0c9b8e`) creato apposta per "riprendere e continuare" quel lavoro, inizialmente ancora isolato — poi l'utente ha esplicitamente chiesto di spostare tutto su `main` a metà sessione (vedi sopra).

## 2. Cosa è stato fatto, in ordine cronologico

### A. Sincronizzazione iniziale
Il branch di lavoro precedente (`claude/missing-recent-chats-687m14`) aveva codice avanzato mai arrivato su `main` (solo il riassunto ci era arrivato). Sincronizzati i file scoped di bot_profit dal branch di test al nuovo branch di lavoro.

### B. Pulizia blacklist L5 morta (commit `63f4b4917`)
Il filtro L5 nel roster (già in `fetch_team_roster`, aggiunto il 26/07) rende irraggiungibile il ramo `blacklist_player(..., 'l5_zero_o_assente', 30gg)` dentro `_process_player_snapshot` — rimosso (resta solo `return 'forma_zero'` silenzioso, stesso pattern di `squadra_diversa`). Ripulite 143 voci legacy da `sorare_lista_nera_profit.txt` (residuo di un run pre-filtro).

### C. Ricalibrazione formula timing (commit `f3e287887`)
`TIMING_WEIGHT_BUCKETS` passati da 5 bucket (scelti a intuito il 24/07) a 3, basati sui dati reali di `pattern_giorni_da_partita.csv`: `<48h→0.1`, `48-96h→1.0`, `>=96h→0.3` (prima era `<24h→0.1, 24-48h→0.3, 48-96h→1.0, 96-200h→0.7, >200h→0.4`). I dati mostravano che <48h e 24-48h avevano lo stesso scostamento reale (nessuno sconto), e che oltre le 96h i dati erano troppo scarsi per giustificare un peso alto.

### D. Prima ondata di ottimizzazione velocità (commit `e6b835920`, `7b7a95058`)
- **Dedup fetch**: `get_current_minimum` e le transazioni venivano richiamate 2 volte per giocatore (una per `is_in_season=True`, una per `False`) anche se il dato di rete è identico — fattorizzata la logica di filtro (`_current_minimum_from_nodes`, `_countable_transactions_from_nodes`) per fare un fetch solo e riusarlo.
- **Riordino query**: `_process_player_snapshot` ora controlla PRIMA se c'è un prezzo valido (live offers) e chiama `get_player_snapshot` (L5/L10/L40/ultima partita) SOLO se il prezzo passa la soglia — ~33% dei giocatori finiva scartato per prezzo comunque, ora si risparmia quella query.
- **Filtro roster esteso**: `ROSTER_MIN_L10` rinominato `ROSTER_MIN_AVG_SCORE`, ora applicato a **L5, L10 E L40** (prima solo L10, L5 scartava solo se assente/zero) — tutte e tre devono superare 35.0.
- **Pool di worker**: `run_snapshot_sweep` sostituito da un `ThreadPoolExecutor` (era sequenziale con pausa fissa `SNAPSHOT_PLAYER_DELAY_SECONDS`, rimossa). Il vero argine ai 429 resta `_graphql_throttle()`, un rate-limiter GLOBALE già esistente (lock condiviso, intervallo minimo tra le richieste, si autoallenta a 0.6s per 45s dopo un 429) — i worker aumentano solo la sovrapposizione dei tempi di attesa risposta.

**Risultati misurati (4 run di verifica full-MLS, stesse 30 squadre MLS, `git_ref` sul branch di test poi su main)**:

| Run | Worker | Ritmo base | Durata | HTTP 429 | Giocatori | no_snapshot |
|---|---|---|---|---|---|---|
| 0 (pre-ottimizzazione) | seq. | — | 27 min | n/d | 585 | 30 |
| 1 | 8 | 0.15s | **10:11** (il più veloce) | 423 | 513 | 30 |
| 2 | 5 | 0.25s | 12:02 | 243 | 513 | 2 |
| 3 | 10 | 0.25s | 11:44 | 446 | 513 | 6 |

**Conclusione non ancora risolta**: nessuna combinazione tentata ha battuto il run 1 (worker=8, ritmo 0.15s, 10:11) in puro tempo — anzi worker=10 ha avuto PIÙ 429 di tutti (446). Il codice attuale è rimasto configurato a **worker=10, ritmo=0.25s** (ultima modifica fatta, non ripristinata a worker=8/0.15s) — se si vuole davvero il tempo minimo storico, riprovare worker=8 con ritmo 0.15s, oppure investire nell'opzione mai tentata: **accorpare le query GraphQL per giocatore con alias** (riduce il NUMERO di richieste invece di giocare con ritmo/concorrenza — probabilmente la strada più solida per scendere sotto i 10 minuti in modo affidabile, ma più lavoro di codice). L'utente aveva chiesto esplicitamente di scendere sotto i 10 minuti e non ci si è ancora riusciti.

### E. Formula potenziale_score — pesi ripesati due volte (commit `2e55c5fab`, poi `146dbf59e`)
1. `media_generale` da media piatta `(L5+L10+L40)/3` a pesi decrescenti `(0.5*L5 + 0.3*L10 + 0.2*L40)/100` (L5 riflette la forma più recente, deve pesare di più).
2. Rapporto timing/ultima_partita/sconto ripesato su richiesta esplicita ("vorrei che lo sconto avesse più peso"): **timing 0.40→0.35, ultima_partita 0.25→0.20, sconto 0.20→0.30**, media_generale invariata (0.15).

**Formula finale attuale**: `score = 0.35*peso_timing + 0.20*(ultima_partita/100) + 0.15*media_generale + 0.30*sconto_normalizzato`.

**ATTENZIONE — bug di race condition scoperto e mai più verificato**: un run di verifica (il run 2 in tabella sopra, dispatchato ~50 secondi dopo il push della modifica media_generale) ha prodotto uno score che, ricalcolato a mano, corrispondeva alla formula VECCHIA, non a quella appena pushata — sospetto un ritardo di propagazione tra `git push` e il checkout del workflow GitHub Actions dispatchato quasi subito dopo. **Prima di fidarsi dei numeri di un run, ricalcolare a mano lo score di 1-2 righe del CSV con la formula attualmente nel codice, per essere sicuri che il run le abbia davvero usate.**

### F. MIN_TRANSACTIONS_FOR_RANKING riallineato a 15 (commit `4e87ca597`)
Era rimasto a 10 nel codice Python (abbassato temporaneamente il 26/07 per il test), disallineato dal default 15 già nel workflow YAML. Ora coincidono.

### G. Viewer HTML salvato nel repo + fix (commit `4c394bcc8`, `b49a1ae50`)
Il viewer (`bot_profit_viewer_3.html`) viveva SOLO nel `Downloads` locale dell'utente, mai versionato. Salvato in `scanners/bot_profit_viewer.html`. Fix applicati su richiesta esplicita:
- Scroll orizzontale della tabella: scrollbar sempre visibile e più spessa, rotellina del mouse converte in scroll orizzontale, drag-to-pan col tasto sinistro (prima non c'era modo intuitivo di scorrere le colonne a destra in un pannello stretto).
- Rimosse le colonne `player_slug` (resta come sottotitolo sotto il nome) e `ultimo_tipo_evento` (ridondante col badge Tipo).
- Riordinate le colonne: prezzo minimo/sconto%/media 7gg/transazioni ora adiacenti invece che sparse nell'ordine grezzo del CSV.
- Padding/font ridotti per compattare.

**Nota tecnica**: il file `bot_profit_viewer_3.html` nel `Downloads` dell'utente è sparito a un certo punto della sessione (forse spostato/rinominato dall'utente, causa ignota) — è stato ricreato lì con una copia della versione aggiornata del repo. Se l'utente lo cerca e non lo trova più, ricordarglielo.

### H. Output ristrutturato a 1 file combinato con timestamp (commit sync su main, sezione 3 del codice)
Su richiesta esplicita ("troppi output tutti insieme, sono 6 file, non so quale aprire"): da 3 file globali (combinato/in_season/classic) + N file per campionato (2 per MLS/K-League) + extra, a:
- **1 solo file globale**: `profit_tracking_<YYYYMMDD_HHMM_UTC>.csv` (in season+classic mescolati, colonna `tipo_carta` per distinguere, tutte le leghe insieme).
- **1 file per campionato** (tenuti separati per lega su richiesta esplicita, per quando si traccerà più di una lega insieme): `per_campionato/<league>_<timestamp>.csv`, anche qui in_season+classic mescolati dentro lo stesso file.
- Ad ogni scrittura, il file con timestamp precedente viene CANCELLATO (`_cleanup_and_write_ranked_csv`, usa `glob` per trovare `<prefix>_*.csv`) — resta sempre e solo l'ultimo.
- `load_previous_tracked()` ora trova il CSV più recente via `_find_latest_output_csv()` (glob + sort lessicografico, funziona perché il formato timestamp `YYYYMMDD_HHMM` ordina cronologicamente) invece di un nome fisso.
- `_commit_output_se_serve()` e lo step di fallback nel workflow committano l'intera cartella `scanners/bot_profit_output/` invece di elencare nomi fissi.
- Testato in locale (script standalone, non nel repo) prima di pushare: scrittura, pulizia file vecchio, ricaricamento — tutto verificato funzionante.
- `consiglio_acquisto_mls.csv/.txt` e `pattern_giorni_da_partita.csv` NON toccati (restano a nome fisso, sempre sovrascritti — non hanno lo stesso problema di proliferazione, sono naturalmente "un solo file" già prima).

### I. Reset completo output (su richiesta esplicita, fatto direttamente su main)
Cancellati tutti i CSV in `scanners/bot_profit_output/` (compresi vecchi residui di campionati diversi da MLS: `1_hnl.csv`, `2_bundesliga.csv`, `austrian_bundesliga.csv`, `premiership_gb_sct.csv`, `primeira_liga_pt.csv`, `superliga_dk.csv` — mai più aggiornati da quando si testa solo su MLS). Il viewer NON toccato.

## 3. Stato esatto del codice — parametri attuali (verificati leggendo `main` a fine sessione)

- `ROSTER_MIN_AVG_SCORE = 35.0` (L5, L10, L40 devono tutti superarla per non essere scartati a livello di roster)
- `SNAPSHOT_WORKER_THREADS = 10` (vedi sezione 2.D per il dubbio su questo valore — non è il più veloce misurato finora)
- `MIN_TRANSACTIONS_FOR_RANKING = 15`
- `GRAPHQL_MIN_INTERVAL_SECONDS_FAST = 0.25` (ritmo base rate-limiter; `SECONDS_SAFE = 0.6` dopo un 429, `COOLDOWN = 45s`)
- Formula: `0.35*timing + 0.20*ultima_partita + 0.15*media_generale(0.5/0.3/0.2 L5/L10/L40) + 0.30*sconto%`
- Output: 1 file globale + 1 per campionato, timestamp UTC nel nome, auto-pulizia vecchi
- Blacklist manuale: 108 voci (`motivo=blacklist_manuale`, scadenza 365gg da metà sessione, quindi ~27/07/2027)

File coinvolti: `scanners/bot_profit.py` (~1400+ righe), `.github/workflows/bot_profit.yml`, `scanners/bot_profit_viewer.html`, `sorare_lista_nera_profit.txt`, `scanners/bot_profit_output/` (attualmente quasi vuota, vedi sezione 0 punto 3).

## 4. Revisione manuale blacklist — IN CORSO, da continuare

**Perché**: l'utente vuole velocizzare ulteriormente i run futuri escludendo a monte i giocatori che GIUDICA LUI STESSO non interessanti (non un criterio automatico — è una scelta manuale, es. giocatori scarsi/panchinari che sa già di non voler mai comprare), oltre ai filtri automatici già esistenti.

**Come funziona (tentativo 1 fallito, tentativo 2 riuscito)**:
- Tentativo 1: popup `AskUserQuestion` uno per uno (4 alla volta, batch). Funziona ma è LENTISSIMO per ~500 giocatori (l'utente lo ha esplicitamente giudicato troppo lento dopo 3 batch).
- Tentativo 2 (fallito): artifact HTML con checklist + bottone che chiamava `sendPrompt(text)` per rimandare la selezione in chat. **`sendPrompt` NON esiste per gli Artifact pubblicati** (esiste solo per i widget di `mcp__visualize__show_widget`, un meccanismo diverso) — il bottone non faceva nulla, l'utente ha perso ~10 minuti di selezione perché non c'era persistenza e ha ricaricato la pagina per errore.
- **Tentativo 3 (funzionante, quello attuale)**: artifact HTML con:
  - Checklist di giocatori (nome, slug, badge esito ultimo run) con checkbox, ricerca, "spunta visibili"/"pulisci selezione".
  - **Persistenza in `localStorage`** ad ogni click (sopravvive a ricaricamenti accidentali).
  - Una `<textarea readonly>` che si aggiorna da sola con la lista di slug selezionati separati da virgola — clic dentro seleziona tutto automaticamente, bottone "Copia lista" con fallback (`navigator.clipboard` → `execCommand('copy')` → selezione manuale).
  - L'utente copia il testo e lo incolla in chat manualmente.

**Dati coinvolti**: lista completa dei 511 giocatori (nome, slug, esito) estratta dal log del run `30245442661` (worker=10, il più recente completato), salvata localmente in file temporanei non nel repo (`players_data.json` ecc. — se serve rigenerarla, il comando è nel log della sessione: parsing delle righe `[bot_profit] [idx/total] Nome (slug): esito` dal log GitHub Actions del run).

**Stato revisione**: 4 giocatori decisi nei primi batch popup (`reed-baker-whiting`, `charles-emile-brunet`, `jordan-knight`, `shakur-mohammed` → tutti sì), poi altri 104 dal primo giro sull'artifact (tutti sì, l'utente non ha scartato nessuno dei "no" — o meglio, ha selezionato solo quelli da blacklistare, tutti gli altri restano non blacklistati implicitamente). **Totale blacklistati: 108. Restano 399 giocatori mai rivisti.**

**L'artifact attuale** (rigenerato senza i 108 già decisi, ancora aperto/disponibile all'utente) è pubblicato su Claude — l'URL esatto non è recuperabile da qui (dipende dalla sessione claude.ai dell'utente), ma se l'utente torna con un'altra lista di slug incollata in chat, è la selezione di un nuovo giro su quell'artifact (o uno nuovo). **Script per applicare una nuova lista** (usato più volte in questa sessione, adattare la variabile `slugs`):

```python
import datetime
slugs = '''slug1,slug2,slug3'''.split(',')  # incollare qui la lista dall'utente

existing = set()
with open('sorare_lista_nera_profit.txt', encoding='utf-8') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) == 3:
            existing.add(parts[1])

scadenza = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)).isoformat()
with open('sorare_lista_nera_profit.txt', 'a', encoding='utf-8') as f:
    for slug in slugs:
        if slug in existing:
            continue
        f.write(f'blacklist_manuale,{slug},{scadenza}\n')
```

Poi rigenerare l'artifact togliendo gli slug appena aggiunti dal dataset embedded (stesso procedimento: filtrare il JSON, sostituire l'array `const PLAYERS = [...]` nell'HTML, ripubblicare con `Artifact` — **stesso `file_path` per mantenere lo stesso URL**, altrimenti l'utente perde il link che ha già aperto).

**Nota per chi riprende**: se si vuole evitare di rifare tutto questo lavoro manuale per ogni nuova squadra/run futuro, si potrebbe proporre di rendere il flusso più fluido (es. un artifact che si rigenera da solo leggendo l'ultimo log), ma non è stato richiesto esplicitamente — non presumere, chiedere prima.

## 5. Prossimi passi aperti (da confermare con l'utente, non presumere)

1. **Finire la revisione manuale della blacklist** (399 giocatori rimasti) — vedi sezione 4.
2. **Lanciare un run di verifica** con tutto il codice attuale (velocità + formula + output + le 108 blacklist manuali) — non ancora fatto dopo l'ultima modifica (ristrutturazione output).
3. **Decidere se tornare a worker=8/ritmo=0.15s** (il più veloce misurato, 10:11) o investire nell'accorpamento query GraphQL (opzione più solida ma più lavoro) per scendere sotto i 10 minuti come richiesto.
4. **Verificare l'effetto delle 108+ blacklist manuali sul roster**: dovrebbero ridurre ulteriormente i giocatori processati nel prossimo run, quindi anche il tempo.

## 6. Note tecniche per la nuova sessione

- Nessuna credenziale Sorare disponibile nell'ambiente Claude Code — ogni test reale richiede lanciare il workflow GitHub Actions (`gh workflow run bot_profit.yml --ref main -f snapshot_mode=si -f team_whitelist="..." -f snapshot_league_slug=mlspa -f git_ref=main -f min_transactions_for_ranking=15 -f max_tracked_cards=2000 -f check_classic=si`) e leggere i risultati con `gh run view <id> --log` (grep su `HTTP 429`, `SNAPSHOT completato`, `[idx/total]`).
- Lista delle 30 squadre MLS (slug) già verificata e usata in tutti i run di questa sessione: `nashville-sc,inter-miami,chicago-fire-bridgeview-illinois,new-england-foxborough-massachusetts,cincinnati-cincinnati-ohio,new-york-city-new-york-new-york,charlotte-fc-charlotte-north-carolina,new-york-rb-secaucus-new-jersey,dc-united-washington-district-of-columbia,orlando-city-lake-mary-florida,columbus-crew-columbus-ohio,toronto-toronto,montreal-impact-montreal-quebec,atlanta-united-atlanta-georgia,philadelphia-union-chester-pennsylvania,vancouver-whitecaps-vancouver-british-columbia,sj-earthquakes-santa-clara-california,los-angeles-fc-los-angeles-california,real-salt-lake-salt-lake-city-utah,dallas-frisco-texas,seattle-sounders-renton-washington,houston-dynamo-houston-texas,st-louis-city-st-louis-missouri,minnesota-united-minneapolis-saint-paul-minnesota,la-galaxy-los-angeles-california,colorado-rapids-denver-colorado,portland-timbers-portland-oregon,san-diego-san-diego,austin-austin-texas,sporting-kc-kansas-city-kansas`
- Per sincronizzare modifiche su `main` senza rischiare di disturbare l'altra sessione parallela: usare un worktree temporaneo isolato (`git worktree add /tmp/xxx origin/main`, checkout selettivo dei soli file scoped di bot_profit da dove si sta lavorando, commit, push, poi `git worktree remove --force`) invece di cambiare branch nella working directory principale — pattern usato con successo più volte in questa sessione.
- Il tool `Artifact` per pubblicare pagine HTML interattive NON supporta `sendPrompt` (quello è solo per `mcp__visualize__show_widget`) — per far tornare dati dall'utente attraverso un artifact, usare `localStorage` per la persistenza e una `<textarea readonly>` selezionabile per l'export manuale (copia-incolla), non contare su meccanismi di invio automatico.
- L'ambiente Claude Code di questa sessione non è riuscito a caricare pagine locali (`file://`) né `http://localhost` né `https://claude.ai` nel proprio browser di test (`mcp__Claude_Browser__navigate` va sempre in errore/timeout per questi casi) — verificare gli artifact via revisione manuale del codice invece che test dal vivo, se il browser di test continua a non funzionare.
