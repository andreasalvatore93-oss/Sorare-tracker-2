# BOT PROFIT — Riassunto sessione 30/07 — per continuare su un'altra chat/account

Continuazione di `docs/BOT_PROFIT_RIASSUNTO_2026-07-29.md` (leggerlo per intero prima di riprendere, non solo l'ultima sezione).

**Contesto invariato**: l'utente non ha un terminale, solo GitHub Desktop — ogni operazione git va fatta da Claude Code. Attenzione alle collisioni con la sessione parallela sulle formazioni (stessa working directory): durante questa sessione `git status` mostrava modifiche non mie in `formazione_mls/`, `calibrazione_globale/` — **non committarle mai insieme alle proprie**, vedi il pattern del worktree temporaneo nel riassunto del 28/07 sezione 5.

## 0. Richiesta dell'utente (un solo messaggio, poi lavoro in autonomia)

Due problemi, dichiarati insieme:
1. **Rate limit**: gli argini messi il 29/07 (blacklist TTL, soglia 2,5 EUR) non reggeranno quando i campionati saranno tutti, oggi sono 3 (Belgio ed Eredivisie fusi, e va bene così). Chiesto di guardare le ultime run, in particolare la **numero 72**.
2. **Consigli troppo generici** ("questa è la finestra di acquisto..."): vuole sapere dopo ogni snapshot **se quello è un buon momento per comprare quel giocatore**, con un segnale chiaro e forte nel CSV (es. evidenziare in giallo chi è in un ottimo momento d'acquisto), definendo il criterio in base ai pattern emersi dalle run.

Output invariato: notifica Telegram che punta ai CSV per campionato (1 MLS, 1 Korea, 1 fuso Eredivisie+Belgio).

**Vincolo posto in corsa dall'utente**: avvisarlo SEMPRE prima di lanciare qualunque run GitHub.

## 1. Rate limit — la causa vera, misurata sui log (non ipotizzata)

Analisi dei log delle run reali (`gh run view <id> --log`), contando i 429 per minuto e i giocatori completati per minuto:

| Run | Durata | HTTP 429 | ok | blacklist | prezzo basso | persi |
|---|---|---|---|---|---|---|
| 66 (a freddo) | 16m58s | **835** | 571 | 328 | 309 | 30 |
| 69 | 12m21s | 551 | 288 | 651 | 299 | — |
| 71 | 7m23s | 291 | 272 | 957 | 9 | — |
| 72 (a regime) | 4m37s | 36 | 263 | 970 | 6 | — |

Due osservazioni che spiegano tutto:

- **Run 72**: il primo 429 è scattato **esattamente 122 secondi dopo la prima query**, cioè dopo ~600 richieste al ritmo di 0,2s. La fase roster (78 squadre) ha occupato i primi 45 secondi.
- **Run 66**: il log mostra un ciclo regolare — ~2 minuti puliti (0 429), poi ~2-3 minuti **quasi completamente bloccati** (minuti interi con 110-118 429 e **zero giocatori completati**), poi di nuovo puliti. Quattro cicli identici.

È il comportamento di un **token bucket lato Sorare: capienza ~600 richieste, ricarica ~1,8 richieste al secondo**. Il ritmo fisso di 0,2s (5 req/s) è quindi ~3 volte oltre il sostenibile: una volta svuotato il secchio non esiste ritmo "sicuro" che tenga, e i 10 worker continuavano a sbattere contro il muro ognuno per conto proprio (ogni 429 costava fino a 2+4+16=22s di backoff SOLO a quel thread, mentre gli altri 9 generavano altri 429). Nella run 66, **835 429 su ~2000 richieste totali = il 42% del traffico buttato**.

Questo spiega anche il sintomo che dava più fastidio all'utente: le raffiche disconnettevano lui stesso dal sito Sorare, perché il limite è per account.

### Cosa è stato fatto

**A. Barriera globale sul 429.** Quando arriva un 429 si alza una pausa **condivisa da tutti i thread** (`_pace_blocked_until`), invece di far aspettare solo lo sfortunato. Un 429 non si moltiplica più per il numero di worker. I 429 che arrivano mentre la barriera è già alzata sono riconosciuti come coda della stessa ondata e non contano come nuova penalità — altrimenti 10 worker moltiplicherebbero per 10 la reazione a un singolo evento. Pausa iniziale 5s, raddoppia a ogni ondata fino a 45s, si dimezza quando il ritmo si riprende. `Retry-After` di Sorare rispettato se presente (solo forma numerica).

**B. Ritmo adattivo (AIMD, come il controllo di congestione TCP).** Si parte veloci (0,2s, che sfrutta la capienza iniziale del secchio), a ogni ondata l'intervallo si moltiplica per 1,6 (tetto 1,5s), e dopo 40 richieste consecutive riuscite si riavvicina al pavimento. **È questa la parte che regge l'aggiunta di nuovi campionati**: più volume non significa più 429, significa solo che il ritmo si assesta da solo dove Sorare lo consente, senza dover ritarare a mano un numero su una run passata.

**C. Backoff locale rimosso.** `graphql_query` non dorme più 2/4/16s nel proprio thread: aspetta la barriera, che il bot avrebbe comunque rispettato. Di conseguenza `GRAPHQL_MAX_RETRIES` è passato da 3 a 5 — ritentare ora è quasi gratis, e riduce i giocatori persi per `rate_limited_max_retries_exceeded` (erano 30 nella run 66).

**D. Correzione di un difetto trovato rileggendo il codice**: uno slot di ritmo prenotato può cadere DOPO che un altro thread ha alzato la barriera (con 10 worker gli slot sono prenotati fino a ~10 intervalli avanti). Aggiunto un secondo controllo della barriera dopo l'attesa dello slot, senza riprenotarlo. Non è cosmetico: senza, ~10 richieste per ondata partivano comunque contro il muro.

**E. Cache roster su disco** (`bot_profit_roster_cache.json`, committata nel repo come i CSV, TTL `ROSTER_CACHE_HOURS`=18). Il roster è la metà nascosta del costo: nella run 72 le 78 squadre sono costate ~190 richieste (78 prime pagine + le successive: i roster storici vanno da 111 a 229 giocatori, quindi 2-3 pagine ciascuna) nei primi 45 secondi su 275 totali. Ma rosa e medie L5/L10/L40 cambiano **solo quando si gioca**, cioè una volta a settimana per squadra, mentre il bot fa 1-2 snapshot al giorno: rileggerle a ogni run è spreco puro. Con tutti i campionati (~27 leghe × ~18 squadre) sarebbero oltre 1000 richieste per run prima ancora di guardare un prezzo. La cache memorizza il roster **già filtrato** e si invalida da sola se `ROSTER_MIN_AVG_SCORE` cambia (altrimenti un cambio di parametro resterebbe congelato). Un roster vuoto non viene mai messo in cache: quasi sempre è il sintomo di una query fallita, congelarlo cancellerebbe la squadra dalle run successive.

### Misura del guadagno (test di stress, non ipotesi)

Scritto un simulatore del token bucket misurato (capienza 600, ricarica 1,8/s) con l'orologio compresso 40x — tutte le costanti di tempo del bot scalate dello stesso fattore, così le proporzioni restano identiche. 2000 richieste, 10 worker, il volume di una run a freddo:

```
PRIMA (ritmo fisso)        durata equiv. 13.0 min | HTTP 429 = 255 | perse 0
DOPO (barriera+adattivo)   durata equiv. 13.0 min | HTTP 429 =   7 | perse 0
```

**429 -97% a parità di durata.** La durata non scende perché il collo di bottiglia vero è la ricarica di Sorare: 2000 richieste non possono passare più in fretta di quanto il secchio si riempia, e nessuna modifica lato client può cambiarlo. Quello che cambia è che ora quelle richieste **non vengono sprecate**.

**Onestà sul simulatore**: riproduce un token bucket puro, quindi NON riproduce i blocchi da 2-3 minuti visti nei log reali (dove Sorare sembra penalizzare chi insiste mentre è limitato). Sul campo il guadagno dovrebbe quindi essere **maggiore** di quello simulato, ma va verificato su una run vera.

### Idea valutata e SCARTATA (non riproporla senza dati nuovi)

Saltare del tutto le squadre lontane dalla prossima partita, per non spendere query su giocatori non acquistabili adesso. Sembrava la leva più grossa (~40% delle richieste). **Verificata sui dati e scartata**: a più di 5,5 giorni dal kickoff, le carte con sconto ≥10% hanno reso **+20,4% mediano a 48h con l'88% di casi in guadagno** (n=145) — è una delle fasce migliori, non una da buttare. Il filtro avrebbe risparmiato richieste cancellando occasioni vere.

## 2. Segnale d'acquisto — tarato sui dati, non a intuito

Il CSV rispondeva solo "quando sarebbe la finestra ideale" e dava un `potenziale_score` astratto: due informazioni generiche, che lasciavano all'utente il lavoro di incrociarle. Ora il bot prende posizione carta per carta.

### Come è stata definita la regola

Rianalizzato il dataset grezzo **già presente nel repo** (`bot_profit_output/pattern_raw_transactions_20260729_1845.csv`, 3658 transazioni reali su 142 carte, prodotto da `bot_profit_pattern_export.py`) — nessuna nuova query verso Sorare. Domanda posta ai dati: *"se compro una carta a questo prezzo, com'è il prezzo di quella stessa carta nelle 48 ore successive?"*.

**Sconto rispetto alla media della carta nei 3 giorni precedenti → variazione a 48h:**

| sconto | n | mediana a 48h | % casi in guadagno |
|---|---|---|---|
| < 0% (sovrapprezzo) | 1690 | −4,3% | 33-42% |
| 0-5% | 295 | +0,8% | 55% |
| 5-10% | 217 | +3,2% | 59% |
| 10-20% | 315 | +7,9% | 70% |
| ≥ 20% | 310 | **+25,2%** | **82%** |

Lo sconto è il segnale **dominante ed è monotono**. Il sovrapprezzo è altrettanto affidabile al contrario.

**Trend (a parità di sconto ≥10%):** down +9,9% mediano / 68% positivi · flat +17,7% / 84% · up +25,4% / 88%.

**Finestra temporale (a parità di sconto ≥10%):** dentro −3,5/−2,5 giorni dal kickoff **+21,0% mediano, 93% positivi**; fuori finestra +14,0% / 75%. La finestra **non crea** l'occasione, la amplifica di ~1,4x.

**Zona di premio:** nei bin da mezza giornata il prezzo smette di essere scontato e passa in premio a circa **−2,25 giorni** dal kickoff (−2,5gg: −4,2%, ma già −2,0gg: +6,6%, −1,5gg: +5,5%, −1,0gg: +3,7%, kickoff: +2,9%). Comprare lì è il momento peggiore.

### Cosa ne è uscito

`valuta_occasione()` in `bot_profit.py` produce un **`punteggio_occasione` = stima del guadagno % a 48 ore** — un numero che si legge direttamente ("questa carta vale circa +18%"), non un indice astratto tra 0 e 1 come `potenziale_score`. Interpolazione lineare sulle mediane misurate (`BUY_SIGNAL_CURVE`), poi moltiplicata per trend e finestra. La coda alta è **compressa** oltre +25% (non tagliata di netto, che appiattirebbe le carte migliori tutte sullo stesso numero perdendo l'ordine tra loro): senza compressione uno sconto del 50% con trend in salita dentro la finestra arriverebbe a +70% atteso, cifra che nessuna misura sostiene.

**Quattro nuove colonne** nel CSV, subito dopo il nome: `segnale`, `punteggio_occasione`, `motivo_segnale`, `aggiornato_il`.

Livelli: **COMPRA ORA** · buona occasione · neutro · evita (sovrapprezzo) · dato non aggiornato.

`COMPRA ORA` richiede **due** condizioni insieme: superare la soglia assoluta (`BUY_SIGNAL_SOGLIA_COMPRA`=10, cioè +10% atteso) **e** essere tra i primi `BUY_SIGNAL_MAX_PER_GRUPPO`=8 del proprio campionato. Il secondo non è cosmetico: lo sconto medio varia enormemente da lega a lega e da momento a momento (nell'ultima run reale mediana +15,8% in MLS, +8,1% in K-League, −0,2% in Eredivisie/Belgio) — con la sola soglia assoluta in MLS sarebbero finite in giallo 27 righe su 50, che non è un segnale ma un colore di sfondo.

**Ordinamento e taglio del CSV cambiati**: non più solo `potenziale_score`, ma prima il verdetto, poi il punteggio, poi `potenziale_score` come spareggio. Effetto pratico: le carte da comprare adesso stanno nelle prime righe e **nessuna può finire tagliata fuori dal top 50** (prima poteva succedere — il taglio era per `potenziale_score`, dove il timing pesa 0,40 e poteva sotterrare una carta con uno sconto enorme ma la partita lontana).

### Ritaratura di `TREND_SCORE_MULTIPLIER` (i dati hanno smentito la taratura precedente)

Era `{up: 1.2, flat: 1.0, down: 0.5}`. Il **verso** è confermato, ma la penalità su `down` era troppo dura: 'down' non è un esito negativo (mediana +9,9%, due volte su tre in guadagno), mentre 0.5 lo dimezzava fino a farlo sparire dalla classifica. Nuovi valori: **`{up: 1.25, flat: 1.0, down: 0.65, None: 0.85}`**.

Attenzione a un'insidia trovata durante l'analisi: guardando il trend **senza controllare per lo sconto**, 'down' sembra addirittura il migliore (+5,5% contro +3,4% di 'up') — è un artefatto, perché in un mercato in calo la singola transazione è già bassa e rimbalza per pura regressione verso la media. Il confronto valido è quello **a parità di sconto**, riportato sopra.

### Freschezza del dato (nuovo, importante)

La classifica è **persistente** (`load_previous_tracked` ricarica tutto quello che c'era). Un prezzo di due giorni fa non può generare un "COMPRA ORA": la nuova colonna `aggiornato_il` registra quando la riga è stata davvero rinfrescata, e oltre `SEGNALE_MAX_AGE_HOURS`=12 il segnale viene sospeso con motivo esplicito ("dato vecchio (Nh fa), prezzo non verificato in questa run"). Le righe scritte prima di questa colonna hanno il campo vuoto e sono trattate come non aggiornate finché non si rivedono.

### BUG REALE trovato e corretto

Rileggendo i CSV committati: **45 righe su 144 avevano un prezzo minimo sotto i 2,5 EUR** (1,24 / 1,40 / 1,52 EUR...). Causa: il ricaricamento della classifica persistente **non riapplicava `MIN_PRICE_EUR_THRESHOLD`** — righe scritte quando la soglia era 1 EUR sono rimaste dentro anche dopo che l'utente l'ha alzata prima a 2 e poi a 2,5. Su una carta da 1,24 EUR anche un 17% di sconto vale 21 centesimi. Il filtro ora è applicato anche in scrittura, non solo in fase di raccolta. **Conseguenza da aspettarsi**: le classifiche si accorciano (nel test: MLS 50→34, K-League 44→35, Eredivisie/Belgio 50→30) e Eredivisie/Belgio perde i suoi COMPRA ORA, che erano tutti carte sotto i 2,5 EUR. È il comportamento corretto.

## 3. Viewer e notifica Telegram

**Viewer** (`scanners/bot_profit_viewer.html`): righe `COMPRA ORA` **evidenziate in giallo sempre**, non più dietro un bottone da premere; badge colorato per livello con il motivo nel tooltip; colonna "Guadagno atteso 48h"; ordinamento di default per verdetto (pinnato, così resta raggruppato anche riordinando per altre colonne); riepilogo in testa ("🟡 8 da comprare ora, 11 buone occasioni"). Il vecchio bottone 🏆 Top 5 è diventato **🟡 Solo occasioni** (filtro).

**Punto di metodo**: il verdetto NON viene più ricalcolato in tre posti diversi. Prima `bot_profit.py`, il viewer e la notifica Telegram avevano **tre formule parallele** per la stessa domanda, che potevano contraddirsi (la notifica poteva segnalare una carta diversa da quella evidenziata nel viewer aperto dallo stesso link). Ora la regola vive solo in `valuta_occasione`/`_assegna_segnali`, viewer e notifica **leggono la colonna** del CSV.

**Telegram**: intestazione per gruppo ("MLS: 8 da comprare ora"), fino a 3 pick con prezzo, guadagno atteso e motivo su riga propria, e il conteggio delle altre. Se non c'è nulla lo dice esplicitamente. Link al viewer invariato (raw.githack).

## 4. Verifiche fatte (nessuna run Sorare consumata)

- **Viewer verificato dal vivo** in un browser reale su CSV veri (server locale): 8 righe gialle, 8 badge COMPRA ORA, 2 badge "dato non aggiornato", filtro funzionante (19 = 8 COMPRA + 11 buone), zero errori in console. *(Nota: nelle sessioni precedenti il browser di test non riusciva a caricare `file://` o `localhost` — con `preview_start` su un `python -m http.server` funziona.)*
- **23 controlli automatici** sull'intera pipeline, tutti superati: ordinamento dei trend, effetto finestra, penalità partita imminente, sovrapprezzo/dato vecchio/partita passata a zero, monotonia della curva, tetto del punteggio, cache roster (scrittura/rilettura/invalidazione per soglia/disattivazione), scrittura dei 3 CSV, ordinamento per verdetto, nessun prezzo sotto soglia, tetto COMPRA ORA per gruppo, nessun COMPRA ORA su dati vecchi, colonne complete.
- **Test di stress** del rate limiter (sezione 1).
- Sintassi Python e YAML del workflow validate.

## 5. Parametri nuovi (tutti sovrascrivibili da env var / input del workflow)

| Parametro | Default | Cosa fa |
|---|---|---|
| `GRAPHQL_MAX_INTERVAL_SECONDS` | 1.5 | tetto del ritmo adattivo |
| `GRAPHQL_PACE_BACKOFF_FACTOR` | 1.6 | quanto rallenta a ogni ondata |
| `GRAPHQL_PACE_RECOVER_EVERY` | 40 | successi consecutivi prima di riaccelerare |
| `GRAPHQL_PACE_RECOVER_FACTOR` | 0.9 | quanto riaccelera |
| `GRAPHQL_429_GLOBAL_PAUSE_SECONDS` | 5.0 | pausa condivisa alla prima ondata |
| `GRAPHQL_429_GLOBAL_PAUSE_MAX` | 45.0 | tetto della pausa condivisa |
| `GRAPHQL_MAX_RETRIES` | 5 | era 3 |
| `ROSTER_CACHE_HOURS` | 18 | 0 = cache disattivata |
| `BUY_SIGNAL_SOGLIA_COMPRA` | 10.0 | guadagno atteso minimo per COMPRA ORA |
| `BUY_SIGNAL_SOGLIA_BUONA` | 4.0 | soglia "buona occasione" |
| `BUY_SIGNAL_MAX_PER_GRUPPO` | 8 | tetto COMPRA ORA per campionato |
| `SEGNALE_MAX_AGE_HOURS` | 12 | oltre, segnale sospeso |

Nel workflow YAML sono esposti come input: `roster_cache_hours`, `buy_signal_soglia_compra`, `buy_signal_max_per_gruppo`. Corretto anche lo step di commit finale, che ora include `bot_profit_roster_cache.json` e costruisce la lista dei file **solo con quelli esistenti** (`git add` fallisce su un pathspec che non corrisponde a nulla, e quello step gira con `if: always()`).

## 6. Stato e prossimi passi

- **Nessuna run GitHub lanciata in questa sessione** (l'utente ha chiesto di essere avvisato sempre prima).
- **La run di verifica è il prossimo passo naturale** e serve a confermare tre cose che il test simulato non può dimostrare: 1) i 429 reali crollano davvero come nel simulatore, 2) la cache roster viene committata e riletta alla run successiva (il risparmio si vede solo dalla SECONDA run in poi), 3) i COMPRA ORA su dati freschi hanno senso all'occhio dell'utente.
- Da rivedere dopo qualche run reale: `BUY_SIGNAL_MAX_PER_GRUPPO`=8 e `BUY_SIGNAL_SOGLIA_COMPRA`=10 sono stati scelti guardando la distribuzione di UN solo snapshot (quello del 30/07 mattina) — vanno riguardati quando ci saranno più snapshot con la nuova colonna.
- `TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT` (2 giorni / 10%) restano **non ricalibrati** — voce aperta dal 28/07. Ora c'è il dataset per farlo (`pattern_raw_transactions`), non è più un ostacolo di dati ma di tempo.
- Il tema "estendere a tutti i campionati" non è stato affrontato in sé: qui si è reso il bot **capace di reggerlo** (ritmo adattivo + cache roster). L'aggiunta vera delle leghe (whitelist squadre, gruppi di output) resta da fare.
