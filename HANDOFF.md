# Handoff — Sorare tracker bots (per nuova chat)

Ultimo aggiornamento: 2026-07-17, subito dopo il push del fix "ping/pong timeout v3".

## Accesso cartelle (da ricordare subito in nuova chat)

Claude ha accesso diretto a due cartelle selezionate dall'utente:
- `C:\Users\Andrea\Desktop\tracker` (cartella di lavoro generica)
- `C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2` — **questo repo**, quello rilevante per tutto il lavoro sui tracker

Il codice sorgente di riferimento (source of truth) è direttamente in questa seconda cartella (clone git reale). Le modifiche si fanno editando i file lì, poi l'utente fa commit/push da sé (workflow consolidato: io modifico, l'utente dice "pusho" o pusha lui stesso dopo conferma).

## Cos'è il progetto

Tre bot indipendenti di tracking del mercato Sorare (carte calcio), ognuno un workflow GitHub Actions separato, tutti mandano alert Telegram:

1. **`track.py`** — tracker "classico", il più maturo/rodato. Gira via `.github/workflows/check.yml` (cron esterno, `LISTEN_SECONDS` default 200). Scrive stato su `tracker.db` (committato dal workflow stesso).
2. **`zenlock_model_tracker.py`** — tracker live separato che modella il comportamento di un top manager reale osservato ("ZenLock"), per intercettare occasioni simili alle sue. Gira via `.github/workflows/zenlock_model_tracker.yml` (cron esterno ogni 4 minuti, `ZENLOCK_LISTEN_SECONDS` default 215). **Stateless**, nessuna scrittura su DB.
3. **`auctions_ws_listener.py`** — tracker live per aste inglesi (English auctions). Ascolta `tokenAuctionWasUpdated` via WebSocket.

Tutti e tre condividono pattern di codice (alcuni via `import track` da parte di zenlock, altri duplicati/paralleli in auctions_ws_listener.py).

## Metodo di lavoro consolidato con l'utente (Pius)

- L'utente incolla **log reali** delle run GitHub Actions dopo quasi ogni modifica, e **screenshot del mercato Sorare reale** per verificare/smentire notifiche specifiche a mano.
- Pattern ricorrente e molto apprezzato dall'utente: **prima di cambiare una soglia, aggiungere un contatore diagnostico** (dict a livello di modulo, loggato a fine run) per avere numeri reali invece di indovinare. Applicato a: branch valute, motivi di scarto ZenLock, disponibilità fallback vendite recenti, motivi di scarto aste, uso fallback filtro stagione.
- L'utente lavora "una cosa alla volta": al momento (17/07) **solo ZenLock è in test attivo**, gli altri due sono fermi/in pausa per non confondere i log.
- **Vincolo esplicito e non negoziabile**: nessuna automazione che rischia soldi reali (offerte dirette/negoziate automatiche) finché il modello non è molto più maturo e validato — "non posso sprecare soldi a caso". Non procedere su questo senza richiesta esplicita futura.
- `git diff -w origin/main` (o `git diff -w --stat`) va sempre usato per verificare lo stato reale, perché il mount del sandbox introduce differenze CRLF/LF cosmetiche che gonfiano il diff a decine di migliaia di righe se non filtrate.

## Stato tecnico corrente per file

### `track.py`
- Fix bundle-price bug in `handle_offer_update`: se un'offerta include più di una carta lato mittente (`sender_cards`), viene skippata (non si può splittare il prezzo per carta in modo sicuro).
- `eur_price_from_amounts(amounts, eth_rate)` gestisce `eurCents`/`wei`/`usdCents`/`gbpCents` (fix valuta importante: USD/GBP sono 21-45% dei dati di prezzo reali, prima venivano silenziosamente ignorati/scartati). Contatore diagnostico `_CURRENCY_BRANCH_STATS` / `get_currency_branch_stats()` / `reset_currency_branch_stats()`.
- `graphql_query(query, variables=None, max_retries=3)`: gestisce HTTP 429 con retry + backoff (rispetta header `Retry-After`, altrimenti backoff esponenziale breve), tetto massimo `GRAPHQL_RETRY_MAX_WAIT_SECONDS = 8.0` per singolo tentativo. **Ora logga anche un estratto della risposta 429** (primo tentativo soltanto, per non fare spam) per capire se è un rate limit vero o altro.
- `run_forever(ping_interval=60, ping_timeout=45)` — alzato da 30/10 (vedi sezione "Bug ping/pong" sotto).

### `zenlock_model_tracker.py` (il più "in evoluzione" in questo momento)
Costanti attuali (in ordine):
```
ZENLOCK_CEILING_CLASSIC_NORMAL = 4.0
ZENLOCK_CEILING_CLASSIC_EXCEPTION = 30.0
ZENLOCK_CEILING_IN_SEASON_NORMAL = 8.0
ZENLOCK_CEILING_IN_SEASON_EXCEPTION = 90.0
ZENLOCK_DISCOUNT_NORMAL = 0.25
ZENLOCK_DISCOUNT_HIGH_VALUE = 0.20
ZENLOCK_MIN_PRICE_EUR = 0.30
ZENLOCK_MIN_COMPARABLES = 1
ZENLOCK_DISCOUNT_SINGLE_COMPARABLE = 0.35
ZENLOCK_MIN_DISCOUNT_EUR = 0.40
ZENLOCK_MIN_REFERENCE_EUR = 1.50
ZENLOCK_SIBLING_TOLERANCE = 0.05
ZENLOCK_SUSPECT_DISCOUNT_THRESHOLD = 0.60
ZENLOCK_RECHECK_DELAY_SECONDS = 3
ZENLOCK_RECHECK_TOLERANCE = 0.05
ZENLOCK_MAX_REFERENCE_CEILING_MULTIPLIER = 3.0
ZENLOCK_LIVE_VS_REAL_SALE_TOLERANCE = 0.25
ZENLOCK_REAL_SALE_MAX_AGE_DAYS = 5
ZENLOCK_LISTEN_SECONDS = 200 (default codice; valore reale deploy 215 via workflow)
```
Sequenza gate in `evaluate_zenlock_offer`: ceiling eccezione → `compute_live_discount` → soglia più severa se comparabile singolo → sconto minimo → riferimento minimo → **riferimento non troppo alto rispetto al ceiling** (fix Vušković) → differenza assoluta minima → **`classic_looks_cheap_everywhere`** (fix Perišić, confronta classic notificata con in_season gemella) → **riferimento non stagnante vs ultima vendita reale** (fix Selvik, cross-check con `get_recent_sale_history`) → **recheck sconto sospetto** (fix Pedrinho, ≥60% sconto → re-fetch dopo 3s) → notifica.

Casi reali risolti questa sessione (con screenshot di verifica dell'utente):
- **Perišić**: falso positivo, confrontava solo dentro il bucket classic, ignorando che le in_season gemelle erano tante ed economiche → risolto con `classic_looks_cheap_everywhere`.
- **Vušković**: falso positivo, riferimento 569.93€ era una carta di satonio stesso, probabile prezzo piazzato per errore → risolto con `ZENLOCK_MAX_REFERENCE_CEILING_MULTIPLIER`.
- **Pedrinho**: sconto sospetto 91% non confermato con screenshot, causa non chiara (forse premio da basso seriale che il modello non vede) → mitigato (non risolto alla radice) con recheck.
- **Egil Selvik**: falso positivo confermato dall'utente, riferimento live 6.20-6.99€ (stagnante) vs vendita reale 4.33€ solo 5h prima → risolto con `ZENLOCK_LIVE_VS_REAL_SALE_TOLERANCE`/`ZENLOCK_REAL_SALE_MAX_AGE_DAYS`.
- Match legittimi confermati dall'utente: Mathias De Amorim, Andrew Thomas, Ousmane Touré (quest'ultimo poi infortunato, ma il profitto teorico c'era).

Workflow (`zenlock_model_tracker.yml`): `listen_seconds` 200→215 per accorciare il buco WS di ~40s tra un run cron e l'altro (non eliminabile del tutto, resta comunque margine sotto il ciclo di 240s del cron e il timeout job di 300s).

### `auctions_ws_listener.py`
- Stesso fix valuta di track.py portato qui (USD/GBP in `eur_price_from_amounts` locale).
- **Contatore diagnostico motivi di scarto** aggiunto da zero (prima non esisteva visibilità aggregata): `bump(stats, key)` chiamato ad ogni skip/return point, loggato a `on_close` come `[diagnostica aste] notifiche inviate: X, scarti: skip_...=N, ...`.
- Scoperte concrete non ancora agite: ~40% dei 50 aste del safety-poll sono non-football/limited (strutturale, atteso); **near-miss reale su `MIN_MARGIN_EUR=1.50€`** — Park Cheong-Hyo scartato 3 run di fila a 1.4787-1.4905€, appena sotto soglia. **Non ancora implementato** (l'utente ha rimandato ad "aste" dopo aver detto "una cosa alla volta, ora solo ZenLock").
- Fallback filtro stagione in `get_recent_public_prices` (ipotesi poi smentita da log successivi — il vero colpevole del calo "prezzi recenti non trovati" era il 429, non il filtro stagione) — lasciato com'è, innocuo.
- Stesso fix rate-limit/ping-pong di track.py (vedi sotto), identico.

## Bug ping/pong — cronologia completa (importante per capire lo stato attuale)

1. **v1**: aggiunto retry con backoff su HTTP 429 in `graphql_query` (tutti e tre i file, zenlock usa quello di track.py via `import track`).
2. **v2**: un `Retry-After` lungo (15s) rispettato alla lettera ha fatto scadere il ping/pong del WebSocket (`ping_timeout=10`, gira nello stesso thread del retry sincrono) → connessione persa (caso Egil Selvik). Fix: `GRAPHQL_RETRY_MAX_WAIT_SECONDS = 8.0` come tetto massimo per singolo tentativo.
3. **v3 (appena fatto, root cause vera)**: il cap di 8s limita solo il *singolo* tentativo, ma `graphql_query` può ritentare fino a 3 volte nella stessa chiamata sincrona → blocco cumulativo fino a ~24s+, ben oltre il vecchio `ping_timeout=10`. È per questo che il ping/pong è scaduto di nuovo, identico, anche col cap attivo. **Fix applicato**: alzato `ping_timeout` 10→45 e `ping_interval` 30→60 in tutti e tre i file (`track.py`, `zenlock_model_tracker.py`, `auctions_ws_listener.py`). Sintassi verificata (`py_compile` OK), diff verificato con `git diff -w --stat` (solo le righe attese, +44/-3 nette sui tre file).

**Appena aggiunto insieme al fix v3**: logging del corpo/header della risposta 429 al primo tentativo di ogni query, per raccogliere più indizi sul prossimo log.

## Questione aperta e NON risolta: i 429 sono davvero "troppo carico"?

Ultimo log (dopo il fix v3, appena pushato — risultato di questo log non ancora visto): mostra 429 già al **primo secondo di una run appena connessa**, con **solo ZenLock attivo** (nessun altro tracker in parallelo in quel momento), persistente su 3 carte diverse per oltre un minuto. Questo indebolisce l'ipotesi originale "carico cumulativo di 3 tracker insieme" — sembra più un blocco che dura minuti indipendentemente da cosa gira in quel preciso momento (forse accumulato da tutti i test ravvicinati fatti oggi su tutti e tre i tracker nell'arco della giornata).

L'utente ha fatto notare: lui riesce a navigare Sorare tranquillamente dal suo browser nello stesso momento in cui lo script prende 429 su tutti e 3 i retry. Non è necessariamente contraddittorio (IP diversi: datacenter GitHub Actions vs residenziale utente, sessioni diverse), ma **non è stato ancora investigato a fondo**. Prossimo passo naturale: guardare il prossimo log con il nuovo dettaglio del corpo/header della risposta 429, per capire se è un vero "too many requests" o qualcos'altro (sessione/cookie stantio, blocco IP condiviso dei runner GitHub, ecc.).

**Stato**: aspettando il prossimo log dell'utente per continuare l'indagine. Non ho ancora ricevuto conferma se il fix v3 ha risolto il ping/pong timeout né nuovi dati sul corpo della risposta 429.

## Backlog (task tracker interno — id, stato, note)

- **#1** [completed] Abbassare margine richiesto del 2% (fascia bassa prezzo)
- **#3** [completed] Bloccare notifica se ≤3 transazioni reali in 21gg
- **#4** [completed] Testare pipeline pattern-mining ZenLock/Satonio
- **#5** [pending] Idea: tracciare venditori sniped come fonte di affari futuri
- **#6** [pending] Indagare comportamento offerte immediate ZenLock su carte appena messe in vendita
- **#7** [pending] Tracker offerte "scambio"/negoziate per ZenLock — **vincolo esplicito**: non toccare finché il modello non è molto più maturo/validato, rischio soldi reali, solo su richiesta esplicita futura
- **#8** [completed] Live tracker modello ZenLock (script+workflow separati)
- **#9** [completed] Tracciare vendite di ZenLock + come aveva acquistato quelle carte
- **#10** [pending] Pattern-mining bot "Barren Wuffett"
- **#11** [pending] Progettare tracker basato sul modello snipe di ZenLock
- **#12** [pending] Buco 40s tra run ZenLock — **da investigare SOLO se causa problemi reali** (queueing/blocco), non prioritario ora, già ridotto un po' con listen_seconds 200→215
- **#13** [pending] Indagare comportamento Satonio sulle aste (fa quasi tutte le aste) — esplicitamente "in coda", non iniziare senza richiesta esplicita
- **#14** [completed] Fix ping/pong timeout v3: alzare ping_timeout WS (appena fatto)

Altro non ancora tracciato come task ma menzionato e rimandato: fix `MIN_MARGIN_EUR=1.50€` troppo rigido nelle aste (near-miss Park Cheong-Hyo) — da riprendere quando si torna a lavorare sulle aste.

## Prossimo passo immediato

Aspettare il prossimo log reale che l'utente incollerà dopo il push di oggi (fix v3 + logging dettaglio 429), e:
1. Verificare se il ping/pong regge ora (nessun "errore WebSocket: ping/pong timed out").
2. Guardare il nuovo dettaglio loggato sul corpo/header della risposta 429 per capire la vera natura del rate limit.
3. Continuare a monitorare `skipped_reference_stale_vs_real_sale` e `skipped_reference_too_high` su ZenLock per vedere se catturano casi reali da qui in avanti, sempre "una cosa alla volta" come richiesto dall'utente.
