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
5. Item aperti da prima di oggi, mai ripresi: "ammorbidire anche zenlock" (le soglie di ceiling,
   non solo di sconto, non ancora riviste per over-strictness); pulsanti Telegram deep-link
   "compra ora"/"fai offerta".
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
   **IMPLEMENTATO 18/07** (richiesta esplicita "insieme, proponi tu tetto di partenza") in
   `zenlock_model_tracker.py`: `ZENLOCK_BURST_MAX_EVALUATIONS=5` valutazioni per
   `ZENLOCK_BURST_WINDOW_SECONDS=15` (finestra scorrevole, `_zenlock_should_throttle()`, deque
   `_recent_evaluation_times`) + `ZENLOCK_THROTTLE_DELAY_SECONDS=1.0` di pausa dopo ogni
   valutazione completa. Oltre il tetto, l'evento viene saltato (stat `skipped_burst_throttle`,
   loggato) SENZA fare query aggiuntive -- l'annuncio non e' perso per sempre, viene ricontrollato
   al prossimo evento/esecuzione se resta live. Soglie deliberatamente conservative (~20
   valutazioni/minuto, contro le 4 MATCH reali osservate in un minuto nel caso che ha causato il
   problema): da stringere se il 429 si ripresenta, da allentare se si rivela troppo prudente.
   Testato con mock (tetto rispettato, finestra che si libera col tempo, throttle che salta
   davvero la chiamata a evaluate_zenlock_offer). NON ancora applicato a track.py/
   auctions_ws_listener.py -- valutare se serve dopo aver visto qualche run reale in piu'.
   Push ancora da fare da parte dell'utente.
