# BOT PROFIT — Riassunto sessione 30/07 — per continuare su un'altra chat/account

Continuazione di `docs/BOT_PROFIT_RIASSUNTO_2026-07-29.md` (leggerlo per intero prima di riprendere, non solo l'ultima sezione).

---

# ⭐ HANDOFF — leggere questa parte per prima

## Stato al momento della chiusura

**Tutto committato e pushato su `main`.** `git pull origin main` per ripartire, non serve nessun branch. Ultima run: **74, verde, 2m42s, zero HTTP 429** — il bot è in uno stato funzionante e migliore di come era all'inizio della sessione su entrambi i fronti richiesti.

Due commit prodotti in questa sessione:
1. `Bot Profit: rate limit risolto alla radice (barriera globale + ritmo adattivo) e verdetto d'acquisto per carta`
2. `Bot Profit: viewer compatto col bottone che illumina i COMPRA ORA, e ritmo tarato sul Retry-After reale di Sorare`

File toccati (solo questi, nient'altro): `scanners/bot_profit.py`, `scanners/bot_profit_viewer.html`, `scanners/bot_profit_telegram_notify.py`, `.github/workflows/bot_profit.yml`, questo documento. Più `bot_profit_roster_cache.json`, generato e committato dal bot stesso durante le run.

## Regole di lavoro imposte dall'utente (valgono anche per chi continua)

1. **Avvisare SEMPRE prima di lanciare qualunque run GitHub.** Vincolo posto esplicitamente in corsa in questa sessione. Le run 73 e 74 sono state entrambe autorizzate una per una.
2. **L'utente non ha un terminale**, solo GitHub Desktop: ogni operazione git (commit/push/pull) va fatta da Claude Code, mai chiedergli di eseguire comandi.
3. **Sessione parallela attiva sulla stessa working directory** (lavora su formazioni/modello predittivo). Durante questa sessione `git status` ha mostrato più volte modifiche non mie (`formazione_mls/`, `calibrazione_globale/`, `formazione_kleague/predict/*`, `best_five.py`): **non committarle mai insieme alle proprie**. Pattern usato con successo due volte qui: commit locale dei soli file propri → `git worktree add --detach <tmp> origin/main` → `git cherry-pick <commit>` → `git push origin HEAD:main` → `git worktree remove --force`. `origin/main` si è mosso sotto i piedi entrambe le volte, serve `git fetch` + `git rebase origin/main` dentro il worktree prima del push.
4. Le run vanno lanciate con `gh workflow run bot_profit.yml --ref main -f git_ref=main` (tutti gli altri input hanno default corretti).

## Cosa è stato fatto, in una riga ciascuno

- **Rate limit**: causa individuata sui log (token bucket Sorare + `Retry-After` da 45s), risolta con barriera globale sul 429, ritmo adattivo AIMD e **cache roster su disco** — quest'ultima è la leva che ha davvero cambiato i numeri. Sezioni 1, 5-bis, 5-ter.
- **Segnale d'acquisto**: nuove colonne `segnale` / `punteggio_occasione` / `motivo_segnale` / `aggiornato_il`, tarate su 3658 transazioni reali già nel repo. Sezione 2.
- **Viewer**: bottone che illumina i COMPRA ORA + tabella compattata del 28%. Sezione 3.
- **Due bug reali corretti**: righe sotto i 2,5 EUR sopravvissute nella classifica persistente (sezione 2, in fondo); `Retry-After` applicato anche agli straggler (sezione 5-bis, punto 3).

## Cosa NON è stato fatto / da riprendere (in ordine di priorità)

1. **Verificare la prima run con cache SCADUTA** (TTL 18h, quindi la mattina dopo): è l'unico pezzo del lavoro sul rate limit mai provato sul campo. Le correzioni post-run-73 dovrebbero portare le ondate da 4 a 1. Se non succede, la leva successiva è alzare `ROSTER_CACHE_HOURS` (vedi punto 3).
2. **Chiedere all'utente se i COMPRA ORA hanno senso** guardando l'output reale. La taratura è statisticamente solida ma non ha ancora passato il suo giudizio su casi concreti — che è il metodo che ha funzionato meglio in tutte le sessioni precedenti (vedi i casi Fernández-Mercau e Jonathan Bond del 28/07).
3. **`ROSTER_CACHE_HOURS`=18 è prudente, non misurato**: alzarlo a 48-72h renderebbe *tutte* le run come la 74 invece di una sì e una no. Da decidere con l'utente perché allunga la finestra in cui un giocatore trasferito resta sulla squadra vecchia (caso Leo Sauer, già in backlog).
4. **`BUY_SIGNAL_MAX_PER_GRUPPO`=8 e `BUY_SIGNAL_SOGLIA_COMPRA`=10** scelti su UN solo snapshot: rivedere con più snapshot.
5. **`TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT`** (2gg/10%) mai ricalibrati — voce aperta dal 28/07. Ora il dataset per farlo c'è (`pattern_raw_transactions_*.csv`), non è più un problema di dati.
6. **Estendere a tutti i campionati**: non affrontato in sé. Qui il bot è stato reso *capace* di reggerlo; l'aggiunta vera (whitelist squadre, gruppi di output) resta da fare ed è il motivo per cui l'utente ha chiesto il lavoro sul rate limit.

## Trappole da non ricalpestare

- **Non riproporre il filtro "salta le squadre lontane dalla partita"**: sembra la leva più grossa, è stato verificato sui dati e scartato (sezione 1, in fondo).
- **Non fidarsi del confronto tra le durate delle run**: la run 72 a 4m37s non era "il bot veloce", era una run corta abbastanza da stare dentro il secchio pieno (la 71, stesso carico, era 7m23s). Guardare **429 e numero di richieste**, non i minuti.
- **Non valutare il trend senza controllare per lo sconto**: senza controllo 'down' sembra il segnale migliore, ed è un artefatto di regressione verso la media (sezione 2).
- Il simulatore del rate limiter (`stress_rl.py`, temporaneo, non nel repo) va usato con **tutte** le costanti di tempo scalate dello stesso fattore: la prima versione scalava il bucket ma non la barriera, e il test andava in timeout senza motivo apparente.

---

**Contesto invariato**: l'utente non ha un terminale, solo GitHub Desktop — ogni operazione git va fatta da Claude Code.

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

È il comportamento di un **token bucket lato Sorare: capienza ~600 richieste, ricarica ~1,8 richieste al secondo**.

> ⚠️ **La stima della ricarica è stata poi corretta a ~1 richiesta/s dalla run 73 — vedi sezione 5-bis, che è la fonte aggiornata.** Le 1,8/s erano dedotte dal solo comportamento dei primi due minuti, cioè dal secchio pieno: è la velocità con cui si *svuota*, non quella con cui si *ricarica*. La capienza ~600 invece regge. Il resto dell'analisi qui sotto (la forma del problema e le contromisure) resta valido.

Il ritmo fisso di 0,2s (5 req/s) è quindi ~3 volte oltre il sostenibile: una volta svuotato il secchio non esiste ritmo "sicuro" che tenga, e i 10 worker continuavano a sbattere contro il muro ognuno per conto proprio (ogni 429 costava fino a 2+4+16=22s di backoff SOLO a quel thread, mentre gli altri 9 generavano altri 429). Nella run 66, **835 429 su ~2000 richieste totali = il 42% del traffico buttato**.

Questo spiega anche il sintomo che dava più fastidio all'utente: le raffiche disconnettevano lui stesso dal sito Sorare, perché il limite è per account.

### Cosa è stato fatto

**A. Barriera globale sul 429.** Quando arriva un 429 si alza una pausa **condivisa da tutti i thread** (`_pace_blocked_until`), invece di far aspettare solo lo sfortunato. Un 429 non si moltiplica più per il numero di worker. I 429 che arrivano mentre la barriera è già alzata sono riconosciuti come coda della stessa ondata e non contano come nuova penalità — altrimenti 10 worker moltiplicherebbero per 10 la reazione a un singolo evento. Pausa iniziale 5s, raddoppia a ogni ondata fino a 45s, si dimezza quando il ritmo si riprende. **`Retry-After` di Sorare ha la precedenza** su questa stima — e la run 73 ha poi mostrato che c'è davvero, e vale ~45s (vedi 5-bis): la pausa reale è quindi quasi sempre la sua, non la nostra.

**B. Ritmo adattivo (AIMD, come il controllo di congestione TCP).** Si parte veloci (0,2s, che sfrutta la capienza iniziale del secchio), a ogni ondata l'intervallo si moltiplica per 1,6 (tetto 1,5s), e dopo 40 richieste consecutive riuscite si riavvicina al pavimento. **È questa la parte che regge l'aggiunta di nuovi campionati**: più volume non significa più 429, significa solo che il ritmo si assesta da solo dove Sorare lo consente, senza dover ritarare a mano un numero su una run passata.

Il **pavimento** della ripresa non è però fisso (aggiunto dopo la run 73, vedi 5-bis): vale 0,2s finché la capienza iniziale regge, e sale a `GRAPHQL_MIN_INTERVAL_SECONDS_SAFE` (0,9s) dal primo 429 in poi.

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

**Viewer** (`scanners/bot_profit_viewer.html`) — assetto finale dopo la correzione chiesta dall'utente a run 73 conclusa ("voglio la pagina html compatta, non devo scorrere ogni volta per vedere chi è nel momento compra ora" + "è un'informazione da mettere come bottone, se cliccato tutti quelli da comprare ora si devono illuminare come meccanismo coppe"):

- **Bottone 🟡 Compra ora**: illumina in giallo le righe COMPRA ORA, stesso meccanismo del vecchio bottone coppe. *Un primo tentativo con l'evidenziazione sempre accesa è stato scartato dall'utente* — colorava la tabella in permanenza invece di rispondere a una domanda quando gliela si fa.
- **I COMPRA ORA sono già in cima** senza bisogno di ordinare nulla: l'ordinamento di default è per guadagno atteso decrescente, e COMPRA ORA è per costruzione l'insieme dei punteggi più alti del gruppo (soglia + tetto per campionato). Verificato: occupano esattamente le posizioni 1-8.
- **Tabella compattata da 1448px a 1038px** (16 → 13 colonne), così a 1090px di larghezza **non serve più scorrere in orizzontale**. Tolte dalla tabella (restano tutte nel CSV): `segnale` e `motivo_segnale` — che l'avrebbero allargata proprio mentre si chiedeva di restringerla, il verdetto si vede dal bottone e il motivo è nel tooltip del nome; `media_transazioni_7gg_trimmed_eur` (ridondante: `sconto_percent` **è** il confronto tra minimo e quella media); `prossima_partita_data` (le date sono già in `finestra_acquisto_ideale`); `prossimo_avversario` (la colonna più larga di tutte e la meno usata per decidere, visto che il segnale è sul prezzo). Intestazioni accorciate (`Min. attuale €`→`Min €`, `Transazioni`→`Tx`, `Ultima partita`→`Ultima`, `Finestra acquisto`→`Finestra`): costo zero in informazione, molte colonne erano larghe solo per via del titolo.
- Colonna **"Atteso 48h"** (`+18.5%`), riepilogo in testa ("🟡 8 da comprare ora, 34 buone occasioni").

**Punto di metodo**: il verdetto NON viene più ricalcolato in tre posti diversi. Prima `bot_profit.py`, il viewer e la notifica Telegram avevano **tre formule parallele** per la stessa domanda, che potevano contraddirsi (la notifica poteva segnalare una carta diversa da quella evidenziata nel viewer aperto dallo stesso link). Ora la regola vive solo in `valuta_occasione`/`_assegna_segnali`, viewer e notifica **leggono la colonna** del CSV.

**Telegram**: intestazione per gruppo ("MLS: 8 da comprare ora"), fino a 3 pick con prezzo, guadagno atteso e motivo su riga propria, e il conteggio delle altre. Se non c'è nulla lo dice esplicitamente. Link al viewer invariato (raw.githack).

## 4. Verifiche fatte PRIMA di consumare una run Sorare

- **Viewer verificato dal vivo** in un browser reale su CSV veri (server locale): 8 righe gialle, 8 badge COMPRA ORA, 2 badge "dato non aggiornato", filtro funzionante (19 = 8 COMPRA + 11 buone), zero errori in console. *(Nota: nelle sessioni precedenti il browser di test non riusciva a caricare `file://` o `localhost` — con `preview_start` su un `python -m http.server` funziona.)*
- **23 controlli automatici** sull'intera pipeline, tutti superati: ordinamento dei trend, effetto finestra, penalità partita imminente, sovrapprezzo/dato vecchio/partita passata a zero, monotonia della curva, tetto del punteggio, cache roster (scrittura/rilettura/invalidazione per soglia/disattivazione), scrittura dei 3 CSV, ordinamento per verdetto, nessun prezzo sotto soglia, tetto COMPRA ORA per gruppo, nessun COMPRA ORA su dati vecchi, colonne complete.
- **Test di stress** del rate limiter (sezione 1).
- Sintassi Python e YAML del workflow validate.

## 5. Parametri nuovi (tutti sovrascrivibili da env var / input del workflow)

| Parametro | Default | Cosa fa |
|---|---|---|
| `GRAPHQL_MIN_INTERVAL_SECONDS_SAFE` | **0.9** (era 0.45) | ritmo sostenibile misurato: pavimento della ripresa dal primo 429 in poi |
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

## 5-bis. Run 73 (prima run reale col codice nuovo) — cosa ha confermato e cosa ha corretto

Lanciata su main dopo il push. Esito: **success, 10m37s**, 976 blacklist / 249 ok / 14 prezzo basso.

**Confermato**: **HTTP 429 da 36 (run 72, stesso carico) a 22**, concentrati in **sole 4 ondate**. La barriera globale funziona: un 429 non si moltiplica più per i 10 worker. Cache roster scritta e **committata su main** (`bot_profit_roster_cache.json`, 78 squadre) — il risparmio si vedrà dalla run successiva. Notifica Telegram e CSV con le nuove colonne prodotti correttamente (8 / 7 / 1 COMPRA ORA sui tre gruppi).

**Ma la durata è salita da 4m37s a 10m37s**, e il log ha spiegato perché — rivelando un dato che nessuna delle analisi precedenti aveva colto:

### Sorare manda un header `Retry-After` di ~45 secondi

Le pause nel log sono `45.0s`, `45.0s`, `45.0s`, poi `40.0s` e `39.0s`. La nostra stima interna alla prima ondata è **5s**: quei 45 non li abbiamo scritti noi, sono il conto alla rovescia di Sorare (i valori calanti 40→39 sono il tempo mancante alla fine della sua finestra). **Ogni ondata di 429 costa quindi 45 secondi di fermo totale**: 4 ondate = 180s, cioè il 28% della run.

Conseguenze, tutte applicate:

1. **Il ritmo sostenibile vero è ~1 richiesta/s, non 1,8.** Misurato sulla run 73: 470 richieste in 637s, che al netto dei 180s di pausa fanno ~1,03/s — e le ondate scattavano ancora a 0,72s/richiesta (1,39/s). La stima di 1,8/s derivava dal solo comportamento iniziale, che è il secchio pieno, non il regime. `GRAPHQL_MIN_INTERVAL_SECONDS_SAFE` **0,45 → 0,9**.
2. **Il pavimento della ripresa sale dopo il primo 429** (nuovo `_pace_floor`): prima resta 0,2s, dopo diventa 0,9s. La capienza iniziale del secchio è un regalo che si spende **una volta sola** — tornare a spingere dopo averla esaurita non recupera tempo, lo perde a blocchi da 45 secondi. Senza questo, l'AIMD riportava il ritmo verso 0,2s e si ricomprava puntualmente l'ondata successiva (è esattamente la sequenza vista nella run 73: 0,45 → 0,72 → 1,15 → 1,50).
3. **Bug corretto: gli "stragglers" riallungavano la barriera.** `Retry-After` veniva applicato a *ogni* 429, anche a quelli che sono solo le risposte di richieste già in volo quando la barriera si era alzata. Ognuno spostava la fine della barriera a "adesso + 45s", facendola scorrere in avanti per un evento già gestito. Ora `Retry-After` si applica **solo sulla nuova ondata**.

**La leva più grossa non è però il ritmo: è la cache roster**, che in questa run era vuota (0 squadre servite) e ha quindi pagato ~195 richieste su ~470 totali. Dalla prossima run quelle spariscono: ~275 richieste, che stanno **dentro la capienza iniziale del secchio** — possibile zero ondate e zero pause da 45s.

**Nota di metodo**: la run 72 a 4m37s non era "il bot veloce", era una run abbastanza corta da stare quasi tutta dentro il secchio pieno. Non è una velocità replicabile su carichi maggiori, e infatti la run 71 (stesso carico) era durata 7m23s con 291 429. Il confronto onesto per giudicare le prossime run è **429 e richieste totali**, non i minuti.

## 5-ter. Run 74 — il risultato che chiude il tema rate limit

Prima run con la cache roster **popolata** (verificato prima del lancio che il commit di checkout contenesse sia il codice nuovo sia le 78 squadre in cache). Esito:

| | run 66 (a freddo, prima) | run 72 (miglior caso, prima) | run 73 (codice nuovo, cache vuota) | **run 74 (codice nuovo, cache piena)** |
|---|---|---|---|---|
| Durata | 16m58s | 4m37s | 10m37s | **2m42s** |
| HTTP 429 | 835 | 36 | 22 | **0** |
| Ondate (45s di fermo l'una) | — | — | 4 | **0** |
| Ritmo finale | fisso 0,2s | fisso 0,2s | 0,89s | **0,20s (mai rallentato)** |
| Roster da cache | — | — | 0/78 | **78/78, zero query** |

**Zero 429, 2 minuti e 42 secondi.** Il bot non ha mai toccato il muro, quindi non ha mai pagato un `Retry-After` da 45s e non ha mai avuto motivo di rallentare: è rimasto a 0,2s per tutta la run.

Perché ha funzionato, in ordine di importanza:

1. **La cache roster ha tolto ~195 richieste su ~470** (78 squadre servite a costo zero). Il totale è sceso sotto la capienza iniziale del secchio, quindi il rate limit non è mai scattato. È la leva più grossa delle tre, ed è anche l'unica che **scala**: con tutti i campionati risparmierà oltre 1000 richieste per run invece di 195.
2. La barriera globale e il ritmo adattivo non sono nemmeno entrati in funzione in questa run — restano la rete di sicurezza per quando il volume tornerà sopra la capienza (prima run dopo la scadenza della cache, o all'aggiunta di nuovi campionati). È lì che valgono i −97% misurati nel simulatore.
3. Il filtro sul prezzo minimo ha ripulito la classifica: `0 escluse per minimo sotto 2.5EUR` (contro le 44-45 della run precedente) — le righe vecchie sotto soglia sono state espulse una volta per tutte.

Segnali prodotti: **8 / 6 / 1 COMPRA ORA** su MLS / K-League / Eredivisie+Belgio. Notifica Telegram e commit finale: `success`.

**Cosa NON dimostra questa run**: il comportamento quando la cache è scaduta (TTL 18h) e il volume torna pieno. Quella è la run 73, che con lo stesso volume di partenza aveva 4 ondate — con le correzioni fatte dopo (pavimento a 0,9s e `Retry-After` solo sulla nuova ondata) dovrebbe fermarsi a 1 ondata, ma **non è ancora stato verificato su una run vera**.

## 6. Stato e prossimi passi

- **Run lanciate in questa sessione: 73 e 74**, entrambe autorizzate esplicitamente dall'utente prima del lancio (è un vincolo che ha posto in corsa e vale anche per le sessioni future: **avvisare SEMPRE prima di lanciare qualunque run GitHub**).
- Esito run 73 e correzioni che ne sono seguite: **sezione 5-bis**, che è la parte più importante di questo documento — è lì che si è scoperto il `Retry-After` da 45s e si è corretta la stima del ritmo sostenibile.
- Esito run 74 (prima run con la cache roster popolata, il vero banco di prova del risparmio di richieste): **sezione 5-ter**.
- **Da verificare alla prima run con cache scaduta** (dopo 18h, quindi la mattina dopo): che le correzioni post-run-73 riducano le ondate da 4 a 1. È l'unico pezzo del lavoro sul rate limit non ancora provato sul campo.
- Da rivedere dopo qualche run reale: `BUY_SIGNAL_MAX_PER_GRUPPO`=8 e `BUY_SIGNAL_SOGLIA_COMPRA`=10 sono stati scelti guardando la distribuzione di UN solo snapshot (quello del 30/07 mattina) — vanno riguardati quando ci saranno più snapshot con la nuova colonna.
- **`ROSTER_CACHE_HOURS`=18 è una scelta prudente, non misurata**: le medie L5/L10/L40 cambiano solo dopo una partita, quindi in teoria reggerebbe di più (2-3 giorni). Alzarla renderebbe *tutte* le run come la 74 invece di una sì e una no — ma va deciso con l'utente, perché allunga la finestra in cui un giocatore appena trasferito resta associato alla squadra vecchia (vedi il caso Leo Sauer già in backlog).
- `TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT` (2 giorni / 10%) restano **non ricalibrati** — voce aperta dal 28/07. Ora c'è il dataset per farlo (`pattern_raw_transactions`), non è più un ostacolo di dati ma di tempo.
- Il tema "estendere a tutti i campionati" non è stato affrontato in sé: qui si è reso il bot **capace di reggerlo** (ritmo adattivo + cache roster). L'aggiunta vera delle leghe (whitelist squadre, gruppi di output) resta da fare.
