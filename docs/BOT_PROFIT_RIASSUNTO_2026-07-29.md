# BOT PROFIT — Riassunto sessione 29/07 — per continuare su un'altra chat/account

Continuazione di `docs/BOT_PROFIT_RIASSUNTO_2026-07-28.md` (leggerlo per intero prima di riprendere, non solo l'ultima sezione). Tutto quanto descritto qui è già **committato e pushato su main**. `git pull origin main` per ripartire.

**Contesto invariato**: l'utente non ha un terminale, solo GitHub Desktop — ogni operazione git (commit/push/pull) va fatta da Claude Code. Attenzione alle collisioni con la sessione parallela sulle formazioni (stessa working directory) — vedi pattern worktree temporaneo già documentato nel riassunto del 28/07, sezione 5.

## 0. Punto di partenza: obiettivo esplicito dell'utente

L'utente ha lamentato che le run bombardano Sorare di richieste (429 frequenti, tanto da farlo disconnettere lui stesso mentre naviga il sito con lo stesso account) e che le run durano troppo (~19-22 minuti con tutti e 4 i campionati MLS+K-League+Eredivisie+Belgio, contro un obiettivo di 15 minuti). Richiesta: **1) ridurre/eliminare i 429, 2) ridurre la durata**, proponendo una soluzione alla volta e testandola.

## 1. Proposta scartata: batching multi-giocatore via alias GraphQL

Ipotesi: raggruppare piu' giocatori in una sola query root usando alias (`p1: anyPlayer(slug:"a"){...} p2: anyPlayer(slug:"b"){...}`), diverso dal caso gia' noto (annidamento rifiutato). **Verificato dal vivo** con un mini-workflow di test temporaneo (branch+workflow ad hoc, poi ripuliti): Sorare rifiuta ANCHE questo pattern con lo stesso errore `Duplicated root field: anyPlayer`, alias o no — è una regola custom del gateway Sorare, non lo standard GraphQL. **Non fattibile, non riproporre.**

## 2. Soluzione implementata: TTL blacklist per prezzo basso/nessun annuncio (commit `f9319714d`, poi `abb3de4b4` per il fix crash)

**Osservazione chiave** (verificata su run reali ravvicinate, non ipotesi): il prezzo minimo di una carta su Sorare resta quasi sempre identico al centesimo su finestre di pochi minuti (163/168 invariate su un confronto a ~9min). I giocatori scartati per `prezzo_basso_o_senza_annunci` (quota tipica ~25-30% del totale processato) sono quindi sprecati a ogni run: quasi certamente restano scartati anche al giro successivo.

**Fix**: in `scanners/bot_profit.py`, quando un giocatore risulta `prezzo_basso_o_senza_annunci` in modalita' SNAPSHOT, viene ora **blacklistato** (stesso meccanismo gia' esistente per `nessuna_partita`/`not_covered`, file `sorare_lista_nera_profit.txt`) con **TTL = `PREZZO_BASSO_SKIP_DAYS` (default 2 giorni)**, invece di essere ricontrollato ogni run. Il bot serve solo 1-2 snapshot di mercato al giorno, quindi 2 giorni di "ricordo" sono un compromesso esplicitamente richiesto dall'utente ("difficilmente un giocatore varia cosi' tanto di prezzo su Sorare in 2 giorni").

**Verificato su run reali** (branch di test temporanei, poi ripuliti):
- Korea da sola: 429 52→6, durata SNAPSHOT ~2m20s→~1m05s tra run 1 e run 2 consecutive.
- MLS+Korea insieme: 429 538→233 (-57%), durata ~11min→~6m45s (-39%).
- **Run reale su main, tutti e 4 i campionati** (prima volta vs seconda volta): 429 855→390 (-54%), durata SNAPSHOT ~16m28s→~10m7s (-39%), `prezzo_basso_o_senza_annunci` 309→5 (skip funziona a pieno regime).

Nuovo env var/input workflow: `PREZZO_BASSO_SKIP_DAYS` (default 2, sia in `bot_profit.py` che in `.github/workflows/bot_profit.yml`).

## 3. Bug reale trovato e corretto: crash su risposta non-JSON da Sorare (commit `abb3de4b4`)

Durante il primo tentativo di rilancio per misurare l'effetto del TTL, una run e' **crashata** dopo ~30s (durante il roster di `nec-nijmegen`): `graphql_query()` chiamava `r.json()` senza gestire il caso di un body vuoto/malformato (probabile errore 5xx transitorio di Sorare, status diverso da 429), causando un `JSONDecodeError` non gestito che terminava l'INTERA run con `exit code 1`. Bug pre-esistente, non introdotto in questa sessione, ma mai emerso prima.

**Fix**: il body non-JSON viene ora trattato come il 429 — retry con lo stesso backoff (`(2**attempt)*2`, cap 16s), poi errore esplicito (`{"errors": [...]}`, gia' gestito da tutti i chiamanti via `data.get('errors')`) se i tentativi si esauriscono, invece di un crash fatale.

## 4. Altro fix collaterale: commit periodico ogni 30s invece di 300s (commit `5a5d58d2d`)

**Osservazione**: controllando la cronologia git delle 3 run cancellate manualmente del 28/07 (16:53-17:25 UTC), **zero commit** risultano in quella finestra — lo step di fallback `if: always()` nel workflow (pensato per salvare comunque i dati su cancellazione manuale) non ha mai prodotto un commit reale nei casi osservati. Quindi oggi, se l'utente cancella manualmente una run, si perde tutto il lavoro dall'ultimo commit periodico in poi.

**Fix**: `COMMIT_CHUNK_SECONDS` default abbassato da 300 (5 minuti) a **30 secondi**, sia in `bot_profit.py` che nell'input workflow — limita la perdita a pochi secondi di lavoro in caso di stop manuale, invece di minuti.

## 5. Bug collaterale NON toccato, solo segnalato (in coda per una sessione futura)

`.github/workflows/bot_profit.yml` ha ancora l'input `min_price_eur_threshold` con default `"1.0"`, mentre il default nel codice Python (`MIN_PRICE_EUR_THRESHOLD`) e' stato alzato a `"2.0"` il 29/07 (sessione precedente, vedi riassunto del 28/07 sezione E). Siccome il workflow passa SEMPRE un valore esplicito (fallback `|| '1.0'`), la soglia a 2 EUR **non e' mai stata realmente applicata nelle run schedulate/dispatchate** — resta sempre 1 EUR a meno che l'utente non scriva esplicitamente "2.0" nel form di lancio. Da sistemare (allineare il default dell'input YAML al default Python) quando si torna a lavorarci — NON ancora fatto in questa sessione, fuori scope rispetto al lavoro sui 429/durata.

## 6. Metodologia di test usata (per sessioni future che vogliono testare modifiche rischiose)

Per ogni modifica rischiosa (query GraphQL nuove, cambi di parametri), verificato SEMPRE dal vivo su GitHub Actions prima di darla per buona:
1. Branch temporaneo (`test/...`) con la modifica.
2. `gh workflow run bot_profit.yml --ref <branch> -f git_ref=<branch> [altri override]` — per limitare il test a un solo campionato (es. solo K-League), gli input string vuoti (`""`) o whitespace (`" "`) **NON funzionano** per bypassare il default GitHub Actions (`||` tratta le stringhe vuote/whitespace come falsy e usa comunque il default pieno, verificato empiricamente) — serve invece editare temporaneamente il file YAML per assegnare `""` DIRETTAMENTE all'env var (non tramite `github.event.inputs.x || 'default'`), che bypassa del tutto quella logica.
3. Dopo il test, branch eliminato (locale + remoto) — main resta pulito fino a quando la modifica non e' confermata e pronta per essere applicata li' direttamente.
4. **Nota tooling**: per lanciare workflow_dispatch su un ref, il file del workflow deve gia' esistere sul branch DEFAULT (main) — non basta che esista solo sul branch di test. Per test che richiedono file nuovi mai visti da GitHub Actions (es. un mini-workflow di verifica), serve un push temporaneo (autorizzato esplicitamente dall'utente) su main, poi rimosso subito dopo.

## 7. Stato attuale, prossimi passi aperti

1. **Obiettivo "sotto i 15 minuti" non ancora raggiunto del tutto**: la run e' passata da ~19-22min a ~10-11min quando il TTL e' "a regime" (dalla seconda run in poi) — gia' sotto l'obiettivo, ma la PRIMA run di ogni ciclo di 2 giorni (quando il TTL scade e tutti i `prezzo_basso` vanno ricontrollati) tornera' a essere piu' lenta (~16min). Da monitorare se questo e' accettabile o se serve un'altra leva (es. rivedere ritmo/worker) specificamente per quella run piu' pesante.
2. **Bug min_price_eur_threshold default disallineato** (vedi sezione 5) — da sistemare quando si riprende.
3. Il tema K-League/gain-per-slot classic (vedi riassunto 28/07... nota bene: quello era di un altro bot, bot_definitivo, non bot_profit — non confondere) resta fuori scope qui.
4. **`TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT`** ancora mai ricalibrati su dati reali (invariato da giorni, vedi riassunto 28/07 sezione 4).

## 8. Preferenza comunicativa dell'utente (nuova, valida da questa sessione in poi)

L'utente ha chiesto esplicitamente (confermato via popup) che ogni comunicazione/scambio passi tramite popup interattivo (AskUserQuestion) invece che testo libero in chat. Non e' chiaro se vale solo per questa sessione o in generale — verificare/riconfermare in sessioni future.

## 9. Continuazione stessa giornata: soglia 2.5EUR + blacklist manuale Eredivisie/Belgio

- **Soglia prezzo minimo alzata 2.0 -> 2.5 EUR** (richiesta esplicita, commit successivo a `8370358f7`) in `MIN_PRICE_EUR_THRESHOLD` (sia default Python che default input workflow, stavolta allineati fin da subito).
- **Artifact di revisione manuale blacklist per Eredivisie/Belgio**, stesso meccanismo gia' usato per MLS (checklist + localStorage + textarea copiabile, niente `sendPrompt`): pubblicato a
  **https://claude.ai/code/artifact/ff250001-6398-4c09-a933-afa854b8a309** — riutilizzabile per continuare la revisione in sessioni future (basta ripubblicare sullo stesso file/URL se si vuole rigenerare la lista, vedi bug sotto).
- **10 giocatori aggiunti a blacklist manuale** (`blacklist_manuale`, TTL 1 anno) dopo la prima revisione dell'utente: `alexis-beka-beka, august-jan-de-wannemacker, david-van-der-werff, gyan-de-regt, laszlo-benes, luuk-koopmans, lushendry-martes, matt-lendfers, reda-laalaoui, rion-ichihara` — gia' committati e pushati su main.
- **BUG trovato nello script di dump del roster** (`scanners/_tmp_roster_dump.py`, temporaneo, non nel bot): la prima versione escludeva dalla lista di revisione ANCHE i giocatori temporaneamente blacklistati per `prezzo_basso_o_senza_annunci` (TTL 2 giorni, dal TTL introdotto in sezione 2) invece di escludere solo chi era gia' deciso permanentemente (`blacklist_manuale`) — con 503 giocatori in quella blacklist temporanea su tutte le leghe al momento del primo dump, il roster Eredivisie/Belgio risultava tagliato a soli 190 nomi (l'utente ha giustamente notato che sembravano pochi per 36 squadre). **Fix gia' scritto** (filtra solo su `blacklist_manuale`) sul branch `test/roster-dump-fix` — **non ancora eseguito**: serve un push temporaneo dei 2 file di test su main per poterlo lanciare (stesso pattern gia' usato per l'alias test e il primo dump), l'utente ha detto esplicitamente "ti dico io quando" prima di autorizzarlo. Riprendere da li': push temporaneo -> `gh workflow run _tmp_roster_dump.yml --ref main` -> leggere il log -> rigenerare l'artifact con la lista corretta (piu' ampia) -> rimuovere i file temporanei da main.
