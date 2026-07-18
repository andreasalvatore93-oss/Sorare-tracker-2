# Handoff — Sorare tracker bots (per nuova chat)

Ultimo aggiornamento: 2026-07-17, fine sessione lunga (fix valute Solana, monotonicità track.py,
sistema log accumulati, fix ZenLock in_season, fallback storico aste, diagnostico ordinamento
aste). Questo file sostituisce interamente la versione precedente (stessa data, ore 17:55).

## Accesso cartelle (da ricordare subito in nuova chat)

Claude ha accesso diretto a `C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2` — **questo repo**
(github.com/andreasalvatore93-oss/Sorare-tracker-2), source of truth reale (clone git). Le
modifiche si fanno editando i file lì direttamente (Read/Write/Edit toccano il path reale
Windows). In parallelo c'è accesso bash a un mount dello stesso repo sotto
`/sessions/.../mnt/Sorare-tracker-2/` (stessi file, path diverso) per compilare/testare/usare git
in sola lettura.

**Workflow di commit/push consolidato**: io modifico e testo (compilo, eseguo test sintetici
mockati), **l'utente commit+pusha sempre lui stesso da GitHub Desktop**, io non eseguo mai
`git commit`/`git push`. Uso git in sola lettura (status/diff/fetch/show) solo quando serve, con
moderazione: il mount del sandbox e GitHub Desktop condividono la stessa cartella locale e
possono litigarsi il lock (`.git/index.lock`, o warning tipo
`unable to unlink '.git/objects/.../tmp_obj_...': Operation not permitted` durante un fetch —
di solito innocuo, il fetch riesce comunque).

**Trucco per leggere gli ultimi log SENZA aspettare che l'utente pulli**: `git fetch origin main`
poi `git show origin/main:logs/<nome>_last_run.log` — bypassa la necessità di un pull locale.

**Trucco per verificare se ci sono DAVVERO modifiche non committate** (il mount introduce diff
cosmetici CRLF/LF che gonfiano `git status`/`git diff` a decine di file "modificati" anche se
il contenuto reale è identico): mai fidarsi di `git status` nudo.
```
git show HEAD:<file> > /tmp/head.tmp
sed 's/\r$//' <file> > /tmp/work.tmp
diff /tmp/head.tmp /tmp/work.tmp   # 0 righe = nessuna modifica reale, e' solo rumore di fine riga
```

**Se l'utente scrive "fix github"** (errore lock in GitHub Desktop): rispondere SUBITO, senza
rispiegare, con questi 5 passi:
1. Chiudi GitHub Desktop
2. Apri il Prompt dei comandi
3. `cd C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2`
4. `del .git\index.lock`
5. Riapri GitHub Desktop e riprova

## Vincolo non negoziabile

**Nessuna automazione che rischia soldi reali** (acquisti diretti, offerte negoziate automatiche)
finché il modello non è molto più maturo e l'utente lo riautorizza esplicitamente. Non proporlo
né implementarlo di propria iniziativa.

## Cos'è il progetto

Tre bot indipendenti di tracking del mercato Sorare (carte calcio), ognuno un workflow GitHub
Actions separato con cron esterno (cron-job.org), tutti mandano alert Telegram:

1. **`track.py`** — tracker "classico", il più maturo. Gira via `.github/workflows/check.yml`.
   Scrive stato su `tracker.db` (committato dal workflow).
2. **`zenlock_model_tracker.py`** — tracker live che modella il comportamento di un top manager
   reale osservato ("ZenLock"). Gira via `.github/workflows/zenlock_model_tracker.yml`, cron ogni
   5 minuti, `ZENLOCK_LISTEN_SECONDS=250`. Stateless su `tracker.db` (nessuna scrittura), ma da
   oggi scrive/committa il proprio file di log (vedi sotto). Importa `track` per riusare le
   funzioni di basso livello (query prezzi, cache, valute).
3. **`auctions_ws_listener.py`** — tracker live per aste inglesi. Ascolta `tokenAuctionWasUpdated`
   via WebSocket, workflow `.github/workflows/auctions_ws_listener.yml`, cron ogni 5 minuti,
   `AUCTION_LISTEN_SECONDS=160`. **Non importa `track.py`**: ogni funzione di basso livello
   (graphql_query, log, eur_price_from_amounts, cache TTL) è duplicata localmente. Scrive
   `auctions.db` (committato dal workflow).

## NOVITÀ DI OGGI — sistema di log accumulati (per leggere i risultati senza Chrome/copia-incolla)

L'utente aveva chiesto un modo di leggere i log delle run senza dover copiare/incollare a mano
e senza usare Claude in Chrome (troppo lento). Soluzione implementata:

- Ogni run di ognuno dei 3 workflow scrive il proprio output completo su file
  (`logs/track_last_run.log`, `logs/zenlock_last_run.log`, `logs/auctions_last_run.log`), **in
  append** (non sovrascritto), con un separatore `===== RUN <timestamp UTC> =====` fra un run e
  il successivo — così più run consecutivi si accumulano nello stesso file e possono essere letti
  tutti insieme dopo un solo pull.
- Rete di sicurezza: tenute solo le ultime 200 run COMPLETE (mai tagliate a metà, l'awk trova i
  marcatori di inizio-run) — in uso normale (pull ogni 20-60 minuti) questo taglio non scatta mai.
- Ogni workflow ha uno step finale (`if: always()`, salva anche sui fallimenti) che fa
  git add/commit/push **da solo, dentro la stessa esecuzione GitHub Actions** — l'utente NON deve
  fare nulla per questo. zenlock_model_tracker.yml è passato da `permissions: contents: read` a
  `contents: write` per poterlo fare.
- **Importante distinzione da ricordare**: il commit/push del log è automatico (dentro CI).
  L'utente deve solo (a) pushare le MIE modifiche al codice quando gliele consegno, e (b) fare
  PULL (non commit) per vedere i log delle run già avvenute sul suo disco locale, da dove io li
  leggo con Read. Questi due verbi sono stati fonte di confusione ripetuta in sessione, va
  chiarito subito se l'utente sembra confuso.
- `set -o pipefail` in ogni step di run (altrimenti `tee` maschererebbe un codice di errore di
  python).

## Metodo di lavoro consolidato con l'utente (Pius)

- L'utente manda log reali (ora sempre più spesso letti direttamente da me dal repo) e screenshot
  del mercato Sorare reale per verificare/smentire notifiche specifiche a mano — verificare sempre
  la matematica quando possibile, mai limitarsi a rassicurare senza controllare.
- Prima di cambiare una soglia: preferire dati concreti (contatori diagnostici, log con verdetto
  esplicito "avrebbe notificato sì/no") invece di indovinare. Pattern molto apprezzato.
- Ogni cambio di soglia va proposto/confermato con l'utente PRIMA o insieme all'implementazione,
  citando il caso reale che lo motiva, e verificato contro i casi già calibrati in precedenza per
  evitare regressioni. I bug puri (es. non-monotonicità) possono essere fissati proattivamente e
  poi riportati, senza dover chiedere permesso.
- Quando una statistica calcolata (mediana, sconto, comparabili) alimenta una notifica, loggare
  SEMPRE anche i dati grezzi sottostanti, per permettere una verifica manuale contro la UI di
  Sorare — convenzione portante che l'utente usa spesso.
- Testare sempre i propri fix con scenari sintetici (mock) prima di consegnarli — in questa
  sessione ho trovato e corretto da solo diversi miei stessi bug prima di consegnarli (bug
  "OFFRI FINO A" con valore stantio, rate-limit scambiato per "nessun dato", e un errore di
  calcolo aritmetico su una proposta di soglia — corretto apertamente quando scoperto).
- Commenti nel codice sempre in italiano, ogni fix taggato `# FIX <data> (vN, ...)` con
  motivazione e caso reale che l'ha originato — convenzione consolidata, seguirla sempre.

## Stato tecnico per file (fine sessione 17/07, sera)

### `track.py`
- **Valute**: `eur_price_from_amounts` gestisce `eurCents`/`wei`/`usdCents`/`gbpCents`/`lamport`
  (Solana, 5a valuta scoperta oggi: 1 SOL = 1e9 lamport, `get_sol_eur_rate()` via coingecko,
  fallback 150.0). Contatore `_CURRENCY_BRANCH_STATS` include ora `lamport`.
- **`MARGIN_TIERS`** (righe ~100-114, valori invariati da prima, solo il MECCANISMO di
  applicazione è stato corretto oggi):
  ```
  (3, 2.59), (5, 4.45), (10, 9.05), (15, 13.65), (20, 18.40), (25, 23.25),
  (30, 27.80), (35, 32.85), (40, 36.40), (45, 42.45), (50, 47.50), (55, 52.75), (60, 56.60)
  FLAT_MARGIN_EUR_ABOVE_60 = 5.0
  ```
  **FIX OGGI**: `required_margin_fraction` aveva lo stesso bug "salto ai bordi" già noto e
  fixato nelle aste — il margine assoluto EUR richiesto poteva DIMINUIRE attraversando un
  confine di scaglione (9 confini su 13 violavano la monotonicità). Fixato con lo stesso
  meccanismo a floor d'ingresso già usato in `auctions_ws_listener.py`
  (`_compute_margin_tier_entry_floors()`, `_MARGIN_TIER_ENTRY_FLOORS`/`_MARGIN_TIER_FINAL_FLOOR`,
  calcolati una volta all'import). Verificato zero violazioni su sweep 0-150€, comportamento
  invariato lontano dai bordi. Effetto collaterale accettato: fascia 40-59€ ora richiede un
  margine flat ~3.60€ (prima scendeva fino a 2.25-2.55€), eredità del floor dello scaglione 20€.
- **`RECENT_SALE_GATE`/`THIN_MARKET_GATE`** (dentro `evaluate_player_offer`, due punti: percorso
  ALERT diretto e percorso "opportunità di margine"): ora passano correttamente
  `season_type=season_type` a `get_recent_sale_history` — prima mischiavano vendite classic e
  in_season dello stesso giocatore in un gate che BLOCCA la notifica. `get_recent_sale_history`
  supporta il filtro da quando si è scoperto che `tokens.tokenPrices.card` espone
  `rarityTyped`/`sport`/`sportSeason`/`inSeasonEligible` (introspection disabilitata, scoperto per
  tentativi).
- **`get_bucket_prices`/`get_recent_sale_history`**: cache TTL 30s (`_BUCKET_PRICES_CACHE`,
  `_RECENT_SALE_HISTORY_CACHE`, `CACHE_TTL_SECONDS=30.0`), per ridurre il volume di query (causa
  più probabile dei 429 con 3 tracker attivi in concorrenza).
- `graphql_query`: gestisce HTTP 429 con retry+backoff, rispetta `Retry-After` con un tetto
  (`GRAPHQL_RETRY_MAX_WAIT_SECONDS=8.0`), rinuncia subito se `Retry-After` > 15s
  (`GRAPHQL_RETRY_AFTER_BAN_THRESHOLD_SECONDS`, probabile ban a tempo fisso, ritentare è inutile).
- `run_forever(ping_interval=60, ping_timeout=45)`.
- Funzioni diagnostiche `discover_*` lasciate nel codice come riferimento riutilizzabile
  (pattern consolidato: non rimuoverle dopo l'uso, potrebbero servire di nuovo).

### `zenlock_model_tracker.py`
Costanti principali attuali:
```
ZENLOCK_CEILING_CLASSIC_NORMAL=4.0      ZENLOCK_CEILING_CLASSIC_EXCEPTION=30.0
ZENLOCK_CEILING_IN_SEASON_NORMAL=8.0    ZENLOCK_CEILING_IN_SEASON_EXCEPTION=90.0
ZENLOCK_DISCOUNT_NORMAL=0.15  <-- CAMBIATO OGGI da 0.25 (richiesta esplicita utente "scendi al
                                   15 e nel caso alziamo" -- DA MONITORARE nei prossimi run,
                                   rialzare se il rapporto volume/qualita' non convince)
ZENLOCK_DISCOUNT_HIGH_VALUE=0.20
ZENLOCK_MIN_PRICE_EUR=0.30              ZENLOCK_MIN_COMPARABLES=1
ZENLOCK_DISCOUNT_SINGLE_COMPARABLE=0.35 ZENLOCK_MIN_DISCOUNT_EUR=0.40
ZENLOCK_MIN_REFERENCE_EUR=1.50          ZENLOCK_SIBLING_TOLERANCE=0.05
ZENLOCK_SUSPECT_DISCOUNT_THRESHOLD=0.60 ZENLOCK_RECHECK_DELAY_SECONDS=3
ZENLOCK_RECHECK_TOLERANCE=0.05          ZENLOCK_MAX_REFERENCE_CEILING_MULTIPLIER=(vedi codice)
ZENLOCK_DISCOUNT_HISTORICAL_MARGIN=0.05 ZENLOCK_LIVE_VS_REAL_SALE_TOLERANCE=(vedi codice)
ZENLOCK_REAL_SALE_MAX_AGE_DAYS=5        ZENLOCK_LISTEN_SECONDS=250 (via env, workflow input)
```
- **Fallback storico** (da prima di oggi, in `evaluate_zenlock_offer`): quando non c'è nessun
  comparabile live, usa l'ultima vendita reale della STESSA stagione
  (`track.get_recent_sale_history(..., season_type=season_type)`) come riferimento, con soglia
  `required_discount + ZENLOCK_DISCOUNT_HISTORICAL_MARGIN`, taggato distintamente
  (`fire_zenlock_historical_match`, contatori `fired_historical`, `skipped_historical_*`).
- **NUOVO OGGI — sostituto in_season per le classic**: in `evaluate_zenlock_offer`, subito dopo
  `compute_live_discount`, se `season_type=='classic'` e c'è un annuncio in_season live dello
  stesso giocatore:
  - `in_season_min <= price_eur` → scarta del tutto (il sostituto è già altrettanto/più
    economico, non è un affare distinto) — stat `skipped_in_season_substitute_cheaper`, e log
    che include il riferimento classic originale, lo sconto classic e un verdetto esplicito
    **"AVREBBE notificato senza questo controllo" / "non avrebbe comunque notificato"** (stat
    `skipped_in_season_substitute_would_have_fired` quando true).
  - `in_season_min < reference_price` (ma non ≤ price_eur) → sostituisce il riferimento classic
    con `in_season_min` e ricalcola lo sconto, log `"riferimento classic (...) sostituito..."`.
  - Motivato dal caso reale Dominik Szoboszlai (classic 15.15€ vs riferimento classic 19.00€ =
    20.3%, ma un in_season vero costava 16.95€ = margine reale 10.6%). **Validato su dati reali**
    (5 run, 1912 carte, 291 scarti da questo controllo): solo 2 sarebbero passati senza il
    controllo, ed entrambi erano blocchi corretti (in_season a pari o minor prezzo della
    classic valutata) — il controllo NON sta bloccando affari veri, funziona come previsto.
  - Asimmetrico per design, confermato esplicitamente dall'utente: le carte in_season NON
    guardano mai le classic (una classic non è un sostituto valido, manca l'idoneità alla
    stagione corrente) — stessa logica già presente in track.py per il tracker classico
    (v. `evaluate_player_offer`, casi Luis Diaz/Franko Kolic).
- `evaluate_zenlock_offer`/`compute_live_discount` usano `track.get_bucket_prices` (letto una
  volta sola, entrambi i bucket in_season+classic, per evitare query duplicate).

### `auctions_ws_listener.py`
Costanti principali:
```
BID_DISCOUNT=0.20  RECENT_PRICES_COUNT=3  MIN_MARGIN_EUR=1.5 (fallback finale)
AUCTION_LAST_PRICE_TOLERANCE=0.15  AUCTION_RECHECK_DELAY_SECONDS=3
NUM_SAFETY_POLL_AUCTIONS=50  AUCTION_HISTORICAL_FALLBACK_MARGIN_MULTIPLIER=1.5  <-- NUOVO OGGI
```
`AUCTION_MARGIN_TIERS` (righe ~82-93):
```python
AUCTION_MARGIN_TIERS = [
    (3, lambda p: 0.80),        # flat, calibrato caso MUGOSA
    (5, lambda p: 1.0),         # flat, calibrato Choi Jun/Yazan/Kim Ryun-Seong/Song Jun-Seok
    (10, lambda p: p * 0.17),   # calibrato caso YAGO
    (20, lambda p: p * 0.08),
    (40, lambda p: p * 0.06),
    (60, lambda p: p * 0.05),
]
# oltre 60EUR: MIN_MARGIN_EUR=1.5 ma il floor accumulato lo alza a ~3.00EUR (accettato
# esplicitamente dall'utente come effetto collaterale della monotonicita')
```
Floor di monotonicità (`_compute_tier_entry_floors`) già presente da prima di oggi, verificato
di nuovo oggi (zero violazioni) durante l'indagine "279 aste zero notifiche".

Logica di valutazione di un'asta (`process_auction`, in ordine):
1. `current_price_eur`/`min_next_bid_eur` dall'evento grezzo.
2. Skip se già notificata, o se identica all'ultima valutazione (`skip_unchanged_since_last_eval`,
   cache SQLite `evaluated_auctions`, confronta `current_price`+`min_next_bid` con l'ultimo
   snapshot salvato — feature "asta invariata" per ridurre carico/log, introdotta oggi prima di
   questa sessione di lavoro).
3. Filtra su carta limited+football.
4. `get_recent_public_prices` (mediana ultime `RECENT_PRICES_COUNT=3` vendite, `includePrivateSales:
   true` — include anche le "Offerta diretta"/negoziate, stessa filosofia di track.py: ogni
   vendita reale conta come segnale). Ritorna `(prices, errored)`: un errore di query (es. 429)
   NON salva lo snapshot "invariata" (altrimenti nasconderebbe per sempre un'asta solo per un
   fallimento transitorio).
5. Skip se `current_price_eur >= last_price` (ultima vendita reale, l'ultimo elemento della lista).
6. **`direct_sale_price`**: `get_live_min_direct_sale` (query live, bucket in_season esatto — le
   aste sono SEMPRE in_season, mai classic) → se None, `get_current_min_direct_sale` (cache
   `tracker.db` di track.py, meno preciso) → **se ANCHE questo è None, NUOVO OGGI: fallback a
   `last_price`** (l'ultima vendita reale già calcolata al punto 5), flag
   `is_historical_reference=True`.
7. `median_reference`/`recommended_ceiling` (informativo, non blocca più nulla da solo dal
   pomeriggio di oggi — vedi commento "vada vada" nel codice).
8. Riverifica live dell'asta specifica (`get_auction_live_state`) prima di notificare, con
   `time.sleep(AUCTION_RECHECK_DELAY_SECONDS)`.
9. `starting_bid = min_next_bid_eur or current_price_eur` (prezzo VERO da pagare per essere in
   testa ora).
10. `margin_estimate = direct_sale_price - starting_bid`.
    `min_margin_required = required_margin_eur(direct_sale_price)`, **× 1.5 se
    `is_historical_reference`** (NUOVO OGGI — margine extra perché non è un prezzo garantito
    disponibile ora, solo l'ultima vendita osservata).
11. Se margine insufficiente: skip, log include ora `direct_sale_price`/`starting_bid` espliciti
    (NUOVO OGGI, per poter verificare a posteriori se la soglia era quella giusta senza rifare i
    calcoli a mano). Decision label `skip_margin_too_low_historical` se da fallback storico.
12. Se notifica: `suggested_max_offer = direct_sale_price - min_margin_required` (mai sotto
    `starting_bid`). Messaggio Telegram include ora, se storico: label "🏷 Riferimento STORICO
    (ultima vendita, non live)" + avviso ⚠️ esplicito di verificare a mano. Decision label/stat
    `notify_historical` invece di `notify`. Il riepilogo di fine run (`on_close`) somma
    `notify + notify_historical` nel totale, mostrando comunque il conteggio storico a parte.

**NUOVO OGGI — diagnostico ordinamento per scadenza (`discover_auctions_end_date_sort`)**:
motivato dalla richiesta dell'utente di tracciare anche le 50 aste più VICINE ALLA SCADENZA (non
solo le 50 più recenti per creazione, che è quello che fa oggi `liveAuctions(last: N)` — vedi
`get_live_auctions`/`run_safety_poll`). Il problema reale: `tokenAuctionWasUpdated` (l'evento WS)
scatta solo sui CAMBIAMENTI (nuove offerte) — un'asta ferma da tempo, senza rilanci, vicina alla
scadenza, che è scivolata fuori dalla finestra delle "50 più recenti", resta invisibile fino alla
chiusura. L'utente ha notato che la UI di Sorare ha un filtro "Termina a breve" per le aste,
suggerendo che il backend probabilmente supporta un ordinamento per data di scadenza. Provati vari
candidati GraphQL (introspection disabilitata, stesso approccio a tentativi di tutta la sessione):
`orderBy: END_DATE_ASC`, `sort: END_DATE_ASC`, `sortBy: END_DATE_ASC`, `orderBy: endDate_ASC`,
`endingSoon: true`, `first: N` (invece di `last: N`). Agganciato a env var
`AUCTION_DIAGNOSTIC_END_DATE_SORT` e a un nuovo input workflow_dispatch
`diagnostic_end_date_sort` in `auctions_ws_listener.yml`. **NON ANCORA ESEGUITO dall'utente** —
è il prossimo passo immediato: dopo il push, lanciare un run manuale di "Auction WebSocket
Listener" con quell'input valorizzato, poi leggere `logs/auctions_last_run.log` per il risultato
(cercare righe `[diagnostica ordinamento aste]`) e decidere se implementare una seconda scansione
di sicurezza "ending soon" complementare a quella esistente.

## Stato del repo a fine sessione

Tutte le modifiche di oggi sono state fatte e testate (compilazione + YAML valido + test
sintetici mockati dove rilevante), ma **potrebbero non essere ancora state pushate dall'utente**
al momento in cui si riprende in una nuova chat — verificare con lo status reale (vedi trucco
CRLF sopra) invece di assumere. File toccati oggi: `track.py`, `zenlock_model_tracker.py`,
`auctions_ws_listener.py`, `.github/workflows/check.yml`,
`.github/workflows/zenlock_model_tracker.yml`, `.github/workflows/auctions_ws_listener.yml`.

## Prossimi passi immediati (in ordine)

1. Verificare se l'utente ha pushato le modifiche di oggi (vedi trucco CRLF per un check reale).
2. Se non ancora pushato, ricordarglielo prima di procedere.
3. Chiedere/verificare se ha già lanciato il run diagnostico `diagnostic_end_date_sort` sulle
   aste — se sì, leggere `logs/auctions_last_run.log` (via `git fetch origin main` +
   `git show origin/main:...` per non aspettare un pull) e riportare il risultato: se un
   ordinamento per scadenza esiste davvero, proporre l'implementazione di una seconda scansione
   di sicurezza "aste vicine alla chiusura" nel `run_safety_poll`.
4. Monitorare i prossimi run di ZenLock con la soglia al 15% (volume e qualità delle notifiche,
   incluso il nuovo fallback in_season) e delle aste con il nuovo fallback storico — l'utente ha
   accennato a voler lasciar girare i tracker e tornare con i log, pattern consolidato in questa
   sessione: io li leggo direttamente dal repo appena disponibili, niente copia-incolla.
5. **RISOLTO 18/07** (era "ammorbidire anche zenlock"): la soglia fissa `ZENLOCK_DISCOUNT_HIGH_VALUE`
   (20%, fascia "eccezione" 4-30EUR classic / 8-90EUR in_season) e' stata RIMOSSA e sostituita
   dalla stessa curva a scaglioni di track.py (`track.required_margin_fraction(reference_price)`),
   richiesta esplicita dell'utente dopo aver notato a mano l'incoerenza (comparabile 23EUR/prezzo
   20EUR, sconto 13.0%: prima non notificato da zenlock -- soglia fissa 20% -- ma SAREBBE stato
   notificato da track, che li' chiede solo ~7%). Ora le due soglie coincidono esattamente a
   parita' di prezzo di riferimento in questa fascia. Fascia "normale" (<=4EUR classic/<=8EUR
   in_season, tuttora flat 15% `ZENLOCK_DISCOUNT_NORMAL`) e tutto il resto (ceiling eccezione,
   single-comparable 35%, fallback storico, sostituto in_season, MIN_REFERENCE/MIN_DISCOUNT_EUR)
   INVARIATI. Testato con mock: caso discusso (20/23EUR) ora notifica, fascia normale 15%/14%
   invariata (nessuna regressione), fascia alta a 90EUR ora richiede ~5.3% invece di 20%. Item
   aperto residuo: pulsanti Telegram deep-link "compra ora"/"fai offerta".
6b. **NUOVO 18/07, backlog non urgente (esplicitamente "non oggi")**: il pattern di 4 notifiche
   zenlock allo stesso prezzo 0.96EUR/riferimento 2.19EUR (Malcolm Ebiowei, Nacho Monreal, Bruno
   Gaspar, Filip Stuparević, run 22:50:42 UTC) e' stato identificato dall'utente come il manager
   "Satonio" che piazza carte in blocco a prezzi tondi -- le sue offerte di mercato sono
   descritte dall'utente come "sempre fuorvianti". Possibile lavoro futuro: un filtro che
   ignora/pesa diversamente le offerte di mercato originate da Satonio in zenlock (e forse
   track.py), perche' non sono un segnale di mercato genuino. NON implementare finche' l'utente
   non lo richiede esplicitamente -- per ora e' solo un promemoria. Nota tecnica per quando
   servira': non e' ovvio come identificare "chi ha piazzato l'annuncio" dai dati attualmente
   loggati (i log mostrano prezzo/slug carta/giocatore, non il manager venditore) -- andra'
   verificato se receiverSide/senderSide o un altro campo GraphQL espone l'identita' del
   venditore prima di poter filtrare per manager.
6. **NUOVO 17-18/07, da mettere in coda e FIXARE (richiesta esplicita dell'utente)**: durante il
   run zenlock delle 22:16:24 UTC un manager ha messo in vendita/aggiornato tante carte a buon
   prezzo in pochi minuti -- 4 ALERT reali ravvicinati (22:17:08-22:18:07 UTC: Heorhii Sudakov,
   Jakub Kiwior, Rodrigo Zalazar, Zeno Debast). Subito dopo (22:19:38-22:19:49 UTC, confermato nel
   log) e' scattata una raffica di `rate_limited_ban_detected` (429) su `fetch_all_live_offers`
   per ~13 giocatori DIVERSI in ~10 secondi. L'utente riporta che nello stesso momento, mentre
   cercava di comprare a mano le carte appena segnalate, gli e' "andato in crash" (probabilmente
   il sito/app Sorare stesso, non lo script -- lo script ha comunque completato il run
   regolarmente, "esecuzione terminata" alle 22:20:34). Ipotesi di lavoro (da confermare con
   l'utente prima di implementare, MAI presa per buona senza verifica): track.py/zenlock
   autenticano le query GraphQL con lo stesso SORARE_COOKIE/CSRF dell'account reale dell'utente --
   se il rate limit di Sorare e' scoped per ACCOUNT (non solo per IP), una raffica di query dei
   nostri bot durante un'ondata di nuovi annunci potrebbe consumare la stessa "quota" della
   sessione umana concorrente, causando il malfunzionamento del sito PROPRIO mentre l'utente sta
   provando a comprare le carte appena segnalate -- il momento peggiore possibile. Direzione di
   fix da valutare insieme all'utente: throttling/spacing esplicito delle query quando arrivano
   molti eventi ravvicinati (es. piccolo delay tra valutazioni successive, o un tetto al numero
   di player valutati per finestra breve), per non esaurire la quota condivisa proprio quando
   servono le mani libere per comprare. Non ancora implementato: chiedere conferma sulla causa
   esatta del crash (sito Sorare? notifica Telegram? altro?) prima di scrivere codice.
   **Aggiornamento stesso giorno**: l'utente ha chiarito che probabilmente era LUI a fare offerte/
   controllare carte a mano nello stesso momento -- quindi non e' (solo) colpa del bot che
   martella l'API da solo, ma la combinazione bot+azioni manuali sulla STESSA quota account che
   ha sforato il rate limit condiviso. Cambia la direzione del fix: invece di (o oltre a) rendere
   il bot piu' "educato" dopo un ban gia' rilevato, ha piu' senso ridurre il VOLUME complessivo di
   query che il bot spara in una raffica di eventi ravvicinati (es. tanti annunci nuovi in pochi
   secondi -> tante fetch_all_live_offers/get_bucket_prices in parallelo), cosi' che sommato
   all'uso manuale dell'utente resti piu' margine prima di sforare. Idea concreta da proporre:
   un piccolo delay fisso tra la valutazione di un evento e il successivo (es. 1-2s) quando la
   coda di eventi ricevuti e' molto piena, o un tetto al numero di player diversi valutati per
   finestra breve -- ancora da confermare col utente prima di implementare.
   **CONFERMATO dall'utente**: il crash era proprio un 429 con schermata nera sul sito/app
   Sorare mentre cercava di comprare, risoltosi da solo dopo ~20-30 secondi -- combacia
   ESATTAMENTE con la finestra di ban vista nel log (Retry-After 22s->11s, stessa manciata di
   secondi). Causa confermata: quota rate-limit condivisa tra bot e sessione umana sullo stesso
   account.
   **IMPLEMENTATO 18/07 v1** (richiesta esplicita "insieme, proponi tu tetto di partenza") in
   `zenlock_model_tracker.py`: `ZENLOCK_BURST_MAX_EVALUATIONS=5` valutazioni per
   `ZENLOCK_BURST_WINDOW_SECONDS=15` + `ZENLOCK_THROTTLE_DELAY_SECONDS=1.0` di pausa dopo ogni
   valutazione. **ERRORE DI CALIBRAZIONE SCOPERTO SUBITO DOPO, STESSO GIORNO**: il tetto era
   confrontato con la frequenza dei MATCH (4/minuto, le notifiche vere, rarissime) invece che con
   la frequenza REALE di "carte valutate" (70-105/minuto nei run normali di oggi, MAI un problema
   di rate-limit prima d'ora). Primo run reale con la v1 attiva (22:35-22:39 UTC): **265 carte su
   329 scartate dal throttle (80.5%), zero notifiche** -- una perdita di copertura enorme,
   scoperta dall'utente controllando il log ("80? stiamo scherzando??????????", giustamente).
   **v2 CORRETTIVA, stesso giorno**: tetto alzato a `ZENLOCK_BURST_MAX_EVALUATIONS=60` (240/min,
   ben sopra il traffico normale ma ancora un freno per un caso davvero patologico),
   `ZENLOCK_THROTTLE_DELAY_SECONDS=0` (rimosso, costava 30-44s di budget di ascolto per run senza
   giustificazione: il vero incidente originale era quasi certamente causato soprattutto dall'uso
   manuale concorrente dell'utente sulla stessa quota account, non dal volume normale del bot).
   Testato questa volta con un OROLOGIO SIMULATO realistico (non eventi tutti nello stesso
   istante, errore fatto anche nel primo giro di test): 438 eventi/250s (il run piu' carico
   osservato oggi) -> 0% throttle; raffica locale di 20 eventi in 3s -> 0% throttle; caso
   patologico 200 eventi in 1s -> il freno scatta ancora. Push ancora da fare da parte
   dell'utente -- monitorare il prossimo run reale per confermare che il volume normale non
   venga piu' toccato.

## Aggiornamento 18/07 (continuazione stessa giornata)

7. **NUOVO STRUMENTO: `manager_bundle_scan.py` + `.github/workflows/manager_bundle_scan.yml`**
   (workflow manuale, uno-shot, separato dai 3 tracker esistenti). Dato lo slug o l'URL profilo
   di un manager, trova tutte le sue carte Limited IN SEASON attualmente in vendita (niente
   classic, richiesta esplicita) e per ciascuna calcola il minimo di mercato dello stesso
   giocatore incrociando `fetch_user_recent_cards`-style query (carte possedute) con
   `get_bucket_prices` (mercato live) via card_slug -- nessun filtro GraphQL diretto "in vendita"
   scoperto, quindi si usa questo incrocio piu' pesante ma sicuro. Nessuno stato persistente
   (niente .db). Notifica su Telegram riusando TEMPORANEAMENTE i secret del canale aste
   (`AUCTION_TELEGRAM_TOKEN`/`AUCTION_TELEGRAM_CHAT_ID`), su richiesta esplicita dell'utente.
   Testato dall'utente in produzione su se stesso (slug "crowss"): funzionante, incluse tutte le
   valute (eurCents/wei/usdCents/gbpCents branch tutti attivati correttamente nel test reale).
   Backlog collegato (NON implementare finche' non richiesto): filtro/peso diverso per le offerte
   di mercato originate dal manager "Satonio" (bulk relisting a prezzi tondi, "sempre
   fuorvianti") -- vedi item 6b sopra, stesso principio si applicherebbe qui.

8. **QoL 18/07 su `manager_bundle_scan.py`** (richiesta esplicita dell'utente dopo il primo test
   reale):
   - **Blocchi da 10**: Sorare permette un'unica offerta cumulativa su max 10 carte per manager.
     Il messaggio Telegram ora organizza le carte in blocchi da `BUNDLE_BLOCK_SIZE` (default 10,
     configurabile da input workflow), ognuno con il proprio subtotale (richiesto, minimo
     mercato) e la propria offerta suggerita (stesso `BUNDLE_OFFER_MARGIN_FRACTION`, applicata al
     minimo di mercato DEL BLOCCO, non al totale). Ordine di scoperta, non riordinato (l'utente ha
     confermato "va bene anche in ordine sparso"). Niente margine di profitto per blocco --
     l'utente lo calcola da solo. Tetto di sicurezza `MAX_BLOCKS_IN_TELEGRAM_MESSAGE` (default 10
     blocchi = 100 carte) oltre il quale i blocchi restanti vengono solo riassunti con un
     conteggio (dettaglio comunque nel log completo su GitHub) -- limite di lunghezza messaggi
     Telegram.
   - **Evidenziazione visiva**: Telegram (parse_mode HTML) NON supporta colori del testo, solo
     grassetto/corsivo/link -- ho usato un'emoji come equivalente pratico: 🟢 quando la carta e'
     GIA' al prezzo minimo di mercato (nessuna alternativa piu' economica, es. "Darijan Bojanić:
     in vendita a 7.35EUR, minimo mercato 7.35EUR" -- lasciata cosi' come richiesto), 🔴 quando il
     prezzo chiesto e' SOPRA il minimo di mercato (esiste un'alternativa piu' economica altrove,
     es. "Park Cheol-Woo: in vendita a 3.90EUR, minimo mercato 3.50EUR" -- evidenziata). Legenda
     emoji aggiunta in fondo al messaggio.
   - Nuova funzione `build_telegram_message(manager_slug, on_sale)` estratta da `run_bundle_scan`
     per poterla testare isolatamente. Testato con mock: caso esatto dato dall'utente (Bojanić
     verde/invariato, Cheol-Woo rosso/evidenziato), 23 carte -> 3 blocchi (10/10/3) con subtotali
     verificati aritmeticamente, troncamento oltre il tetto blocchi, e un test end-to-end completo
     di `run_bundle_scan()` con 12 carte finte -> 2 blocchi. Tutti PASSED.
   - Rimossa la vecchia `MAX_LINES_IN_TELEGRAM_MESSAGE=30` (limite piatto sostituito dalla logica
     a blocchi).

9. **FIX 18/07 (caso reale confermato dall'utente): finestra di invisibilita' in `track.py` faceva
   perdere affari veri.** Caso concreto: David Pereira da Costa, annuncio nuovo a 4EUR (minimo
   mercato reale 5EUR, quindi un buon affare), MAI notificato -- il log mostrava la carta
   accodata per riverifica (`queue_pending_recheck`) alle 09:40 UTC perche' la query di verifica
   live non la vedeva ancora (finestra di invisibilita' Sorare, storicamente stimata ~2 minuti),
   poi riverificata alle 09:46 UTC (~6 minuti dopo, ben oltre i 2 minuti attesi) e ANCORA
   invisibile alla query -- caso scartato per sempre (nessun secondo tentativo). Richiesta
   esplicita dell'utente: semplificare, non far dipendere la notifica dalla nostra query di
   verifica che raggiunga l'annuncio, il tempo di reazione umana e' gia' un buffer sufficiente.
   Vincolo esplicito dell'utente: non trattare solo `price_eur` come se fosse solo EUR letterale,
   dev'essere gestito anche per le altre valute (wei/usdCents/gbpCents/lamport) -- confermato che
   `price_eur` e' GIA' il valore convertito in EUR a prescindere dalla valuta originale (via
   `eur_price_from_amounts`), quindi il fix si applica correttamente a tutte le valute senza
   distinzioni.
   - **Modifica in `evaluate_player_offer`** (blocco "l'annuncio e' piu' economico del minimo
     trovato dalla verifica live, probabile finestra di invisibilita'"): invece di accodare per
     riverifica e aspettare, ora si usa SUBITO `price_eur` (e il suo `card_slug`) come vero nuovo
     minimo, prependendolo a `own_prices` (cosi' il vecchio `true_min_price` diventa
     `own_prices[1]`, il comparabile corretto, esattamente come se questa carta fosse stata
     visibile fin dall'inizio) e riassegnando `true_min_price`/`true_min_card_slug`. Nessuna
     attesa, nessun secondo giro di query, l'ALERT scatta subito con il prezzo reale dell'evento.
     Precedente citato come riferimento di design gia' accettato nel progetto:
     `send_instant_alert` gia' si fida di un prezzo raw non verificato dal vivo (con le sue
     proprie soglie di sicurezza).
   - Gli ALTRI due punti che chiamano `queue_pending_recheck` in `track.py` (fallback per
     errore di rete/query fallita; e il controllo "margine troppo vicino"/possibile secondo
     annuncio ancora piu' economico non ancora visto, caso Antonio Sivera) sono stati
     DELIBERATAMENTE lasciati INVARIATI -- sono scenari genuinamente diversi da questo.
   - Testato con 3 scenari mock: (1) replica esatta caso invisibile (evento 4.00EUR, query vede
     solo 5.00EUR, slug diverso) -> ALERT immediato "5.00EUR -> 4.00EUR (20.0%)", nessuna
     `queue_pending_recheck` chiamata -- PASSED; (2) caso normale/nessuna invisibilita' (carta
     evento gia' visibile come piu' economica) -> comportamento ALERT invariato, nessun log di
     invisibilita' spurio -- PASSED; (3) "bug del centesimo" (stesso slug carta, differenza di
     prezzo minima per arrotondamento, dentro `INVISIBILITY_GAP_TOLERANCE`) -> correttamente NON
     trattato come invisibilita', nessun falso trigger -- PASSED.
   - `py_compile track.py` OK.

## Aggiornamento 18/07 (dopo il primo giro di test reale dell'utente)

**Scoperta importante**: l'utente aveva lanciato i workflow (test su "flobob-fc" per il bundle
scanner) PRIMA di aver pushato i fix del punto 8/9 via GitHub Desktop -- confermato confrontando
`origin/main` con i file locali (`git diff origin/main -- manager_bundle_scan.py` mostrava
differenze, `build_telegram_message`/`Blocco`/`BUNDLE_BLOCK_SIZE` assenti su origin). Per questo
la notifica Telegram mostrata dall'utente era ancora nel formato VECCHIO (lista piatta, "Offri
fino a X per il pacchetto" su TUTTE le carte insieme -- non fattibile su Sorare oltre le 10
carte). Nessun bug nel codice: semplicemente non ancora deployato. Chiarito esplicitamente
all'utente.

**NUOVO PROBLEMA REALE emerso dallo stesso test (log run 2026-07-18 10:40:09 UTC, 'flobob-fc')**:
1741 carte Limited possedute, 560 in_season, 464 giocatori diversi -- il ciclo di controllo
mercato (`find_current_listing_and_market_min` per OGNI giocatore posseduto, capped a
MAX_PLAYERS_TO_CHECK=300) ha impiegato ~115 secondi (10:40:19->10:42:14) per trovare solo 18
carte DAVVERO in vendita. Causa: nessun filtro server-side "solo in vendita" veniva applicato
alla query delle carte possedute -- si scaricava tutto e si controllava il mercato anche per i
446 giocatori le cui carte NON erano in vendita. L'utente ha notato che il sito Sorare stesso usa
un filtro lato server per questo (URL osservato:
`.../cards/limited?sale=true&is=true`), chiedendo esplicitamente di "fargli filtrare solo e
direttamente per carte vendita in season, e far partire [il controllo prezzo minimo] solo dopo".

**FIX 18/07 (performance)** in `manager_bundle_scan.py`: `OWNED_CARDS_QUERY` trasformato in
`OWNED_CARDS_QUERY_TEMPLATE` con un punto di innesto `{filter_arg}` sull'argomento searchCards.
Nuova `discover_on_sale_query(manager_slug)`: prova in ordine una lista di candidati
(`ON_SALE_FILTER_CANDIDATES = ["onSale: true", "forSale: true", "sale: true", "isOnSale: true",
"onlyOnSale: true", "listedForSale: true"]`) con un probe minimo (pageSize=1) contro il manager
reale, usa il primo che non da' errore GraphQL per TUTTA la scansione (introspection disabilitata,
nessun modo di sapere il nome esatto in anticipo -- stesso principio "prova e leggi l'errore" di
tutto il resto del progetto). Se NESSUN candidato funziona: fallback automatico al comportamento
precedente (scarica tutto, controlla il mercato per ogni giocatore posseduto -- piu' lento ma
sempre corretto, mai un crash). `fetch_manager_owned_in_season_limited_cards` ora ritorna anche
`filtered_to_on_sale` (bool) per loggare chiaramente quale scope e' stato usato. **NON ANCORA
VERIFICATO SU DATI REALI quale candidato (se uno) funziona davvero** -- la prossima run reale
dira' se uno dei 6 candidati ha funzionato (log espliciti per ognuno) o se serve aggiungerne
altri sulla base dell'errore GraphQL esatto restituito da Sorare.
Testato con mock: (1) discover_on_sale_query trova il candidato giusto al 3o tentativo; (2)
fallback quando nessun candidato funziona; (3) fetch con filtro funzionante scarica SOLO le carte
gia' in vendita (non centinaia); (4) end-to-end completo `run_bundle_scan()` con filtro
funzionante (12 carte -> 2 blocchi correttamente formattati con emoji); (5) end-to-end completo
con fallback (nessun filtro disponibile, comportamento precedente preservato, notifica comunque
corretta). Tutti PASSED.

Confermato che il resto della richiesta dell'utente (organizzazione in pacchetti da 10 con
subtotale/offerta per pacchetto, "non tutte insieme perche' posso offrire solo per dieci carte
alla volta") corrisponde ESATTAMENTE a quanto gia' implementato nel punto 8 sopra (build_telegram_
message) -- l'utente lo ha ridescritto perche' non lo vedeva ancora deployato, non e' una
richiesta nuova.

## Aggiornamento 18/07 (dopo il secondo giro di test reale -- primi 6 candidati falliti + caso Saka)

L'utente ha pushato e testato il primo giro (punti 8/9): confermato via log reale che i 6
candidati di filtro on-sale su searchCards sono TUTTI falliti con errore netto "Field
'searchCards' doesn't accept argument '...'" (run 2026-07-18 11:02 UTC) -- searchCards non ha
nessun argomento booleano diretto "solo in vendita". **Sostituito con TENTATIVO 2**: invece di un
ARGOMENTO su searchCards, proviamo un CAMPO sulla carta stessa dentro `hits`, `liveSingleSaleOffer
{ __typename }` -- stesso campo gia' individuato (ma mai testato in questo contesto esatto) in
`diagnostic_live_auction_lookup.py` per un altro scopo. Se leggibile, `hit['liveSingleSaleOffer']
is not None` diventa un segnale diretto e GRATIS (nessuna query aggiuntiva) di "questa carta e' in
vendita ORA", permettendo di filtrare PRIMA di entrare nel ciclo costoso di controllo mercato.
Probe singolo con fallback automatico se il campo non e' leggibile in questo contesto (mai un
crash). **ANCORA NON CONFERMATO SU DATI REALI** -- la prossima run reale dira' se funziona.
Rimossa la vecchia `discover_on_sale_query`/`ON_SALE_FILTER_CANDIDATES` (dead end confermato,
inutile riprovarla ogni run). Testato con mock: campo funzionante (filtra 5 carte -> 2 confermate
in vendita) e fallback (campo non leggibile, comportamento precedente preservato). Entrambi PASSED.

**FIX 18/07 (caso reale Bukayo Saka, track.py)**: log reale mostrava un ALERT valido (15.91EUR ->
12.93EUR, -18.8%) bloccato dal gate THIN_MARKET ("solo 2 transazioni negli ultimi 21 giorni,
minimo richiesto 4") -- ma la pagina "Cronologia delle vendite" del sito mostrava almeno 9
transazioni reali (Offerta diretta + Scambio) nella sola ultima settimana, tutte sul print
2025-26 (in_season). Causa individuata: `get_recent_sale_history` usa
`tokens.tokenPrices(playerSlug, rarity: limited)`, che NON accetta l'argomento `last` (confermato
da un errore reale gia' documentato nel codice) -- quindi NESSUNA garanzia che il server
restituisca le transazioni piu' recenti: per un giocatore molto scambiato come Saka, il
troncamento/ordine lato server e' arbitrario e puo' restituire un campione non rappresentativo,
che dopo il filtro season_type lascia solo 2 vendite anche se la realta' e' ben diversa.
**Soluzione**: esiste gia' nel progetto (auctions.py/auctions_ws_listener.py,
get_recent_public_prices) una query GEMELLA ma sotto `anyPlayer(slug)` invece di `tokens`, che
ACCETTA un `last` esplicito (gia' confermato funzionante altrove) -- provato ad aggiungere
date/card (mai testati insieme a `last` in questo contesto preciso). Se funziona: pool di
`RECENT_SALE_HISTORY_POOL_SIZE=50` transazioni GARANTITE le piu' recenti (non piu' un campione a
scelta del server), poi stesso filtro/sort/troncamento client-side di sempre. NON passato
l'argomento `season` di questo stesso campo: gia' documentato altrove nel progetto come
inaffidabile (puo' azzerare risultati veri per la maggior parte dei giocatori). Discovery fatta
UNA VOLTA SOLA per processo (fatto di schema, non per-giocatore) tramite flag globale
`_recent_sale_history_v2_available`, con fallback automatico e permanente alla vecchia query se
il primo tentativo fallisce (mai un crash). Testato con mock: (1) v2 funzionante risolve
esattamente il caso Saka (pool con 9 vendite recenti in_season -> count_recent_sales_in_window
trova 6, non piu' 2, gate non blocca piu'); (2) v2 non disponibile -> fallback automatico a v1,
discovery fatta una sola volta (non ri-provata per il giocatore successivo). Entrambi PASSED.
**ANCORA NON CONFERMATO SU DATI REALI** se il campo v2 funziona davvero in questo contesto --
prossima run reale con un ALERT lo dira'.

**QoL 18/07 su `manager_bundle_scan.py`** (richiesta esplicita dell'utente dopo aver visto la
notifica coi blocchi):
- **"Offri fino a" piu' vistoso**: Telegram HTML non supporta dimensione font, quindi simulato
  risalto visivo con cornice di emoji (💰━━━...━━━💰) sopra/sotto la riga, testo in maiuscolo,
  frecce doppie 👉👉/👈👈 -- "salta subito all'occhio" scorrendo il messaggio.
- **Link diretto al profilo del manager**: aggiunto in testa al messaggio, costruito dallo slug
  (`https://sorare.com/it/football/my-club/{slug}/cards/limited?sale=true&is=true`, stesso URL
  osservato dall'utente nel browser), con `&` HTML-escaped (`&amp;`) dentro l'attributo href per
  correttezza.
- Testato con mock (link presente, emphasis presente nel messaggio finale).

**Domanda aperta dell'utente, NON risolta con certezza (punto 2 del suo messaggio)**: "il manager
bundle scanner non e' partito mentre girava il tracker classico, si e' messo in coda". Verificato
che i due workflow hanno `concurrency.group` DIVERSI e non correlati (`sorare-tracker` per
check.yml vs `manager-bundle-scan` per manager_bundle_scan.yml) -- nessuna ragione di codice per
cui dovrebbero bloccarsi a vicenda. Verificato anche (ricerca web) che il limite GitHub Actions
per account personali Free e' 20 job concorrenti TOTALI per l'intero account -- ben oltre i 2 job
in questione, quindi non e' nemmeno un limite di piano. Ipotesi piu' probabile: normale latenza di
provisioning di un secondo runner GitHub-hosted (di solito pochi secondi, a volte fino a ~1
minuto), non un bug nei nostri workflow. Da verificare guardando i timestamp esatti
"queued"/"in progress" dei due run nella tab Actions di GitHub la prossima volta che succede, per
confermare se e' un blocco vero o solo latenza normale.

## Stato a fine sessione 18/07 (continuazione, aggiornato)

Implementato e testato (compilazione + mock), MA NON ANCORA PUSHATO dall'utente via GitHub
Desktop: sostituzione del filtro on-sale (campo liveSingleSaleOffer invece di argomenti falliti),
fix v2/v1 per lo storico vendite (caso Saka), QoL "Offri fino a" piu' vistoso + link manager.
**Prossimo passo per l'utente**: pushare via GitHub Desktop, poi (a) rilanciare bundle scan su un
manager con tante carte possedute ma poche in vendita per vedere se liveSingleSaleOffer funziona
e quanto si abbassa il tempo di esecuzione, con il nuovo formato blocchi/emphasis/link; (b)
aspettare il prossimo ALERT o "mercato sottile" del tracker classico per vedere se la query v2
dello storico vendite risolve casi come Bukayo Saka; (c) se ricapita la stessa sensazione di
"scanner in coda dietro al tracker", controllare i timestamp esatti su GitHub Actions. Backlog
invariato: filtro Satonio (item 6b, non richiesto), pulsanti Telegram deep-link "compra ora"/"fai
offerta" (item 6, non richiesto).
