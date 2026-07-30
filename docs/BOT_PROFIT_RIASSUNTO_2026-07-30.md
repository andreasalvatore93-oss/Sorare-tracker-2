# BOT PROFIT — stato al 30/07/2026

**Questo documento è scritto per chi arriva da zero**: un altro account/sessione, senza memoria di quello che è successo prima e senza aver letto i riassunti dei giorni precedenti. Contiene tutto il necessario per riprendere il lavoro. I riassunti precedenti (`docs/BOT_PROFIT_RIASSUNTO_2026-07-26/27/28/29.md`) restano come archivio storico: **non serve leggerli per lavorare**, solo per capire perché una certa scelta è stata fatta a suo tempo.

---

# PARTE A — Cosa devi sapere prima di toccare qualsiasi cosa

## A.1 Che cos'è il Bot Profit

Uno scanner del mercato di **Sorare** (gioco di fantacalcio con carte digitali scambiabili). Il suo unico scopo è **dire all'utente quali carte conviene comprare adesso**. Non compra, non fa offerte, non gioca: legge il mercato, calcola, scrive tre file CSV e manda una notifica Telegram.

> ⚠️ **Nel repo esiste un ALTRO bot che invece compra davvero**: `bots/bot_definitivo.py` (autobuy/makeoffer). È tutta un'altra storia, con una sua calibrazione. **Non confonderli.** Se trovi documentazione o memorie che parlano di "margini", "offerte", "autobuy", quasi certamente riguardano quell'altro bot.

Gira su **GitHub Actions**, non in locale: l'utente lo lancia dal form del workflow 1-2 volte al giorno. Una run dura oggi 2-3 minuti.

## A.2 L'utente, e le regole di lavoro che ha imposto

Sono vincoli espliciti, non preferenze. Rispettarli.

1. **Avvisare SEMPRE prima di lanciare qualunque run GitHub**, anche dentro un lavoro delegato "in autonomia". Le run girano sul suo account Sorare reale e consumano il rate limit condiviso: mentre il bot martella, lui viene disconnesso dal sito se ci sta navigando. Chiedere **una volta per run**, non una volta per sessione.
2. **Non ha un terminale**, usa solo GitHub Desktop. Ogni operazione git (commit/push/pull) la devi fare tu dall'ambiente Claude Code. Non dirgli mai "lancia questo comando".
3. **C'è una seconda sessione Claude Code attiva sulla stessa working directory**, che lavora su tutt'altro (formazioni / modello predittivo, cartelle `formazione_*/`, `calibrazione_globale/`, `generatore_formazioni/`). Vedi A.6 per come conviverci senza rompere niente.
4. Preferisce **un tema alla volta**, risposte brevi, e verificare le ipotesi su **casi reali** (una carta concreta, un prezzo concreto) prima di accettarle. Questo metodo ha trovato più bug veri di qualunque analisi astratta.

## A.3 Le meccaniche Sorare che servono per capire il codice

- **Rarità**: il bot guarda solo le carte **`limited`** (una delle rarità di Sorare). Tutto il resto è ignorato.
- **In season vs classic**: una carta "in season" è della stagione corrente. Quando Sorare rilascia le nuove carte in season, quelle vecchie diventano "classic". **Per MLS, K-League, Eredivisie e Belgio i due mercati sono completamente separati** — stesso giocatore, due prezzi diversi, due storici diversi, due righe distinte nel CSV. Per tutti gli altri campionati si mescolano in una riga sola (`tipo_carta='misto'`). La lista sta in `EXCLUDED_LEAGUE_SLUGS`.
- **Minimo attuale**: il prezzo più basso a cui qualcuno sta vendendo *adesso* (query `liveSingleSaleOffers`). È il prezzo che l'utente pagherebbe comprando ora.
- **Transazioni**: le vendite già avvenute (query `tokenPrices`). Il bot usa quelle degli ultimi 7 giorni per capire quanto vale "normalmente" una carta. **Esclude aste e acquisti diretti dalla riserva Sorare** (`TokenPrimaryOffer`, venditore nullo): non sono prezzi di mercato tra manager. Restano solo i `TokenOffer`.
- **Medie voto L5 / L10 / L40**: media dei punteggi delle ultime 5 / 10 / 40 partite giocate. Sono l'indicatore di forma.
- **Il rate limit di Sorare è per ACCOUNT**, non per IP: se il bot esagera, l'utente viene buttato fuori dal sito mentre naviga. Vedi la parte C, è il tema centrale di questa sessione.

## A.4 Dove vive il codice

| File | Cosa fa |
|---|---|
| `scanners/bot_profit.py` | il bot (3012 righe). Tutta la logica: query, filtri, punteggi, scrittura CSV, commit |
| `scanners/bot_profit_viewer.html` | pagina HTML che legge un CSV e lo mostra come tabella filtrabile |
| `scanners/bot_profit_telegram_notify.py` | notifica di fine run, con link al viewer |
| `scanners/bot_profit_pattern_export.py` | script separato e read-only: esporta le transazioni grezze per le analisi |
| `.github/workflows/bot_profit.yml` | il workflow, con tutti i parametri come input |
| `sorare_lista_nera_profit.txt` | blacklist a scadenza, formato `motivo,slug,scadenza_iso` |
| `bot_profit_output/` | i CSV di output (in root, non sotto `scanners/`) |
| `bot_profit_roster_cache.json` | cache dei roster, scritta e committata dal bot stesso |

**Repo**: `andreasalvatore93-oss/Sorare-tracker-2`, **pubblico** (importante: i link `raw.githack.com` della notifica Telegram funzionano solo perché è pubblico).

**Secret GitHub usati**: `SORARE_COOKIE`, `SORARE_CSRF`, `SORARE_VERSION`, `SORARE_BUILD`, `SORARE_DEVICE_FINGERPRINT`, e per Telegram `BUNDLE_TELEGRAM_TOKEN` / `BUNDLE_TELEGRAM_CHAT_ID` (lo stesso canale di altri script del repo).

**Nell'ambiente Claude Code non ci sono credenziali Sorare**: qualunque verifica dal vivo richiede una run GitHub, quindi il permesso dell'utente (regola A.2.1). Tutto il resto va testato offline, sui CSV già committati.

## A.5 Come si lancia e si controlla una run

```bash
gh workflow run bot_profit.yml --ref main -f git_ref=main
gh run list --workflow=bot_profit.yml --limit 1 --json number,databaseId,status
gh run view <databaseId> --log > run.log     # il log c'è solo a step concluso
```

Tutti gli altri input hanno default corretti nel YAML, non serve passarli. Cose utili da cercare nel log:

```bash
grep -c "HTTP 429" run.log
grep -oP '\): [a-z_]+$' run.log | sort | uniq -c    # esiti per giocatore
grep -E "Roster totale|rate limit\] HTTP 429 totali|\[csv\] totale" run.log
```

## A.6 Git: come lavorare senza pestare i piedi all'altra sessione

La working directory è condivisa con un'altra sessione Claude Code che scrive di continuo in `formazione_*/`, `calibrazione_globale/`, `generatore_formazioni/`. **Non committare mai i suoi file insieme ai tuoi** — controlla sempre `git status --porcelain` prima di ogni `git add`, e aggiungi i file per nome, mai `git add -A`.

`origin/main` si muove sotto i piedi in continuazione (in questa sessione è successo a ogni singolo push). Il pattern che funziona, usato tre volte con successo:

```bash
git add <solo i tuoi file> && git commit -m "..."
git fetch origin main
git worktree add -q --detach /tmp/wt origin/main
cd /tmp/wt && git cherry-pick <sha del tuo commit>   # sha ESPLICITO, non $(git rev-parse HEAD)
git push origin HEAD:main
cd - && git worktree remove --force /tmp/wt
```

Un `git pull --rebase --autostash` nella working directory principale sarebbe più semplice, ma tocca il lavoro non committato dell'altra sessione: **non farlo**.

*Trappola già incontrata*: se dentro il worktree scrivi `$(git rev-parse HEAD)` quello risolve all'HEAD **del worktree** (cioè `origin/main`), non al tuo commit — il cherry-pick risulta vuoto e sembra un errore misterioso. Usa lo sha esplicito, recuperandolo con `git log --format='%H %s' | grep <messaggio>`.

*Può anche capitare che il tuo commit arrivi su `origin/main` "da solo"*: l'altra sessione fa `git pull` nella working directory condivisa, si tira dentro il tuo commit locale in un merge, e lo pusha col suo. È successo. Non è un problema — verifica il contenuto con `git diff origin/main -- <file>` invece di ripushare alla cieca.

---

# PARTE B — Come funziona il bot, in ordine di esecuzione

Il bot ha due modalità. **In pratica ne esiste una sola**: `SNAPSHOT_MODE=si` è il default e non viene mai cambiato. L'altra (listener websocket sugli eventi di mercato, `run_listener`) è codice vivo ma di fatto morto — non toccarlo se non serve, ma sappi che c'è e che duplica un po' di logica.

## B.1 Il giro (`run_snapshot_sweep`)

**1. Roster, una volta per squadra.** Query pubblica `football.club(slug).anyPlayers` che restituisce **tutti i giocatori mai passati per quel club**, non la rosa attuale. Da qui si filtra:
- via chi non è più al club (`activeClub.slug != team_slug`) — sono la maggioranza, anche 200 su 230;
- via chi ha **una qualsiasi** tra L5/L10/L40 sotto `ROSTER_MIN_AVG_SCORE` (35).

Restano ~16 giocatori rilevanti per squadra, ~1240 in totale sulle 78 squadre attuali. **Dal 30/07 questo passo legge da una cache su disco** (vedi C.4).

**2. Blacklist, a costo zero.** Prima di qualunque query, chi è in `sorare_lista_nera_profit.txt` con scadenza futura viene saltato. Oggi ~990 giocatori su 1240 finiscono qui: **è il filtro che rende la run sostenibile**. Motivi e durate:

| motivo | TTL | quando |
|---|---|---|
| `prezzo_basso_o_senza_annunci` | 2 giorni | minimo sotto soglia o nessun annuncio (836 voci) |
| `not_covered` | 30 giorni | carta non coperta da Sorare (503) |
| `blacklist_manuale` | 365 giorni | scelti a mano dall'utente, non gli interessano (201) |
| `nessuna_partita` | 3 giorni | nessuna partita futura in calendario (109) |
| `l5_zero_o_assente` | 30 giorni | forma a zero (36) |

**3. Una query per giocatore** (`fetch_player_combined_snapshot`): prezzo, prossima partita, ultime 3 partite e prima pagina di transazioni **in un'unica richiesta GraphQL**. Prima erano tre round-trip separati.

**4. Filtri, punteggi, riga.** Sotto `MIN_PRICE_EUR_THRESHOLD` (2,5 EUR) si scarta e si blacklista. Altrimenti si calcolano sconto, trend, punteggi e si scrive la riga in memoria.

**5. Secondo giro per i rate-limitati.** Chi è fallito per rate limit finisce in un pool a parte e viene ritentato dopo 30s, invece di essere perso.

**6. Scrittura.** Ogni 30 secondi (`COMMIT_CHUNK_SECONDS`) il bot riscrive i CSV e fa commit+push da dentro il runner. È voluto: se l'utente annulla la run a metà, non perde tutto.

## B.2 Vincoli dell'API GraphQL di Sorare — già scoperti, non riprovarli

- **Niente batching di più giocatori**: `p1: anyPlayer(slug:"a") p2: anyPlayer(slug:"b")` viene rifiutato con `Duplicated root field: anyPlayer`, alias o no. È una regola custom del gateway Sorare, non lo standard GraphQL. Verificato dal vivo, due volte.
- **Root field diversi sullo stesso slug invece funzionano**: `tokens { ... }` + `anyPlayer(slug) { ... }` nella stessa query è ciò che rende possibile la query combinata del punto 3.
- **Niente `allPlayerGameScores` o `anyFutureGames` dentro una lista `anyPlayers`**: Sorare li rifiuta esplicitamente. Vanno chiesti per singolo giocatore.
- **Introspezione dello schema disabilitata**: i campi si scoprono dal testo degli errori ("Did you mean...").

*Lezione pagata cara il 28/07*: un commento nel codice sosteneva che annidare `allPlayerGameScores` funzionasse. Non era mai stato riverificato dopo, ed era falso — tutte le 30 squadre MLS restituivano zero giocatori. **Non fidarsi di un "verificato" nei commenti senza una run reale che lo confermi.**

## B.3 L'output

Tre CSV in `bot_profit_output/`, uno per **gruppo** (non per lega: Eredivisie e Belgio condividono il file, su richiesta esplicita):

- `profit_tracking_mlspa_<timestamp>.csv`
- `profit_tracking_k-league-1_<timestamp>.csv`
- `profit_tracking_eredivisie_belgio_<timestamp>.csv`

Top 50 per gruppo. Il timestamp è nel nome e a ogni scrittura il file precedente **di quel gruppo** viene cancellato: ne resta sempre e solo uno.

**La classifica è persistente**: a ogni avvio `load_previous_tracked()` ricarica i CSV esistenti come stato di partenza, così una carta vista ieri non sparisce se oggi non viene ricontrollata. È comodo ma è anche la fonte di una classe di bug precisa — **le righe vecchie non vengono rifiltrate con i parametri nuovi**. Ne è stato corretto uno il 30/07 (vedi D.4); se cambi un filtro, chiediti sempre se va applicato anche in scrittura.

La notifica Telegram punta al **viewer** via `raw.githack.com` con il CSV come query param: un clic e la tabella è già caricata.

---

# PARTE C — Il rate limit (tema principale del 30/07)

## C.1 Il problema di partenza

L'utente: i 429 sono così tanti da disconnetterlo dal sito mentre naviga, e gli argini messi il 29/07 (blacklist a TTL, soglia prezzo) non reggeranno quando i campionati saranno tutti — oggi sono 3.

## C.2 La causa, misurata sui log

| Run | Durata | HTTP 429 | ok | blacklist |
|---|---|---|---|---|
| 66 (a freddo) | 16m58s | **835** | 571 | 328 |
| 69 | 12m21s | 551 | 288 | 651 |
| 71 | 7m23s | 291 | 272 | 957 |
| 72 (a regime) | 4m37s | 36 | 263 | 970 |

Due osservazioni decisive:

- Nella **run 72** il primo 429 è scattato **esattamente 122 secondi dopo la prima query**, cioè dopo ~600 richieste al ritmo di 0,2s.
- Nella **run 66** il log mostra un ciclo regolare: ~2 minuti puliti, poi ~2-3 minuti *quasi completamente bloccati* (minuti interi con 110-118 429 e **zero giocatori completati**), poi di nuovo puliti. Quattro cicli identici.

È un **token bucket lato Sorare, capienza ~600 richieste**. Il ritmo fisso di 0,2s (5 req/s) era ben oltre il sostenibile: svuotato il secchio non esiste ritmo "sicuro", e i 10 worker sbattevano contro il muro **ognuno per conto proprio** (ogni 429 costava fino a 2+4+16=22s di backoff solo a quel thread, mentre gli altri 9 ne generavano altri). Nella run 66, **835 429 su ~2000 richieste = il 42% del traffico buttato**.

Poi la run 73 ha aggiunto il pezzo mancante: **Sorare risponde con un header `Retry-After` di ~45 secondi**. Le pause `45.0s / 45.0s / 45.0s / 40.0s / 39.0s` nel log non sono stime nostre (la nostra prima stima è 5s), sono il suo conto alla rovescia. **Ogni ondata di 429 costa 45 secondi di fermo totale.** E il ritmo davvero sostenibile è **~1 richiesta/s**, non le 1,8/s che avevo stimato dai primi due minuti — quei primi due minuti sono la velocità con cui il secchio si *svuota*, non quella con cui si *ricarica*.

## C.3 Le tre contromisure

**1. Barriera globale sul 429** (`_pace_blocked_until`). Un 429 alza una pausa **condivisa da tutti i thread**, invece di far aspettare solo lo sfortunato. I 429 che arrivano a barriera già alzata sono riconosciuti come coda della stessa ondata e non contano come nuova penalità — altrimenti 10 worker moltiplicherebbero per 10 la reazione a un singolo evento.

**2. Ritmo adattivo (AIMD, come il controllo di congestione TCP).** Si parte a 0,2s (sfruttando la capienza iniziale), a ogni ondata l'intervallo × 1,6 (tetto 1,5s), e dopo 40 successi consecutivi si riavvicina al pavimento. Il **pavimento non è fisso**: vale 0,2s finché la capienza iniziale regge, e sale a 0,9s (il sostenibile misurato) dal primo 429 in poi — perché la capienza iniziale è un regalo che si spende **una volta sola**, e rispingere dopo averla esaurita non recupera tempo, lo perde a blocchi da 45 secondi. **È questa la parte che regge l'aggiunta di nuovi campionati**: più volume non significa più 429, significa che il ritmo si assesta da solo dove Sorare lo consente, senza ritarare numeri a mano.

**3. Cache roster su disco** (`bot_profit_roster_cache.json`, TTL 18h, committata nel repo). Rosa e medie L5/L10/L40 cambiano **solo quando si gioca** — una volta a settimana per squadra — mentre il bot fa 1-2 snapshot al giorno: rileggerle ogni volta era spreco puro. Valeva ~195 richieste su ~470. La cache conserva il roster **già filtrato** e si invalida da sola se `ROSTER_MIN_AVG_SCORE` cambia. Un roster vuoto non viene mai messo in cache (quasi sempre è il sintomo di una query fallita: congelarlo cancellerebbe la squadra dalle run successive).

## C.4 I risultati

| | run 66 (prima, a freddo) | run 72 (miglior caso, prima) | run 73 (codice nuovo, cache vuota) | **run 74 (codice nuovo, cache piena)** |
|---|---|---|---|---|
| Durata | 16m58s | 4m37s | 10m37s | **2m42s** |
| HTTP 429 | 835 | 36 | 22 | **0** |
| Ondate (45s l'una) | — | — | 4 | **0** |
| Ritmo finale | fisso 0,2s | fisso 0,2s | 0,89s | **0,20s (mai rallentato)** |
| Roster da cache | — | — | 0/78 | **78/78, zero query** |

**Run 74: zero 429, 2m42s.** Il bot non ha mai toccato il muro, quindi non ha mai pagato un `Retry-After` e non ha mai avuto motivo di rallentare.

La leva decisiva è stata la **cache roster** (punto 3), che ha portato il totale sotto la capienza del secchio. Barriera e ritmo adattivo in quella run non sono nemmeno entrati in funzione: sono la rete di sicurezza per quando il volume tornerà sopra. Su quel fronte c'è una misura separata, da un simulatore del token bucket con l'orologio compresso 40x: **429 da 255 a 7 (-97%) a parità di durata** su 2000 richieste.

## C.5 Idee valutate e SCARTATE — non riproporle senza dati nuovi

- **Saltare le squadre lontane dalla prossima partita.** Sembra la leva più grossa (~40% delle richieste): un giocatore che gioca fra 6 giorni non è comprabile *adesso*. **Verificato sui dati e scartato**: a più di 5,5 giorni dal kickoff, le carte con sconto ≥10% hanno reso **+20,4% mediano a 48h con l'88% di casi in guadagno** (n=145). È una delle fasce migliori. Il filtro avrebbe risparmiato richieste cancellando occasioni vere.
- **Pausa fissa periodica** (60s lavoro / 20s pausa) per "svuotare" la finestra prima che scatti il limite: testata il 29/07, il primo 429 arrivava comunque nello stesso punto. Codice ancora presente ma disattivato (`GRAPHQL_BURST_WORK_SECONDS=0`).
- **Ritmi più aggressivi** con l'idea che tanto il secondo giro recupera i persi: provato il 29/07, risultato **peggiore** (6m03s contro 5m14s), perché ogni carta finita in retry sprecava fino a 22s di backoff prima di arrendersi.

## C.6 Trappola nel confrontare le run

**I minuti ingannano.** La run 72 a 4m37s non era "il bot veloce": era una run abbastanza corta da stare quasi tutta dentro il secchio pieno — la run 71, stesso identico carico, era durata 7m23s con 291 429. Per giudicare una run guarda **numero di 429, numero di ondate e richieste totali**, non la durata.

---

# PARTE D — Il modello: da "score astratto" a "compra o no"

## D.1 Il problema

L'utente: *"ricevo consigli molto generici, del tipo questa è la finestra di acquisto. Io invece dopo ogni snapshot voglio già sapere esattamente se quello è un buon momento per comprare il giocatore analizzato... un segnale chiaro e forte nel csv"*.

Prima il CSV dava due cose generiche: un `potenziale_score` astratto fra 0 e 1, e una colonna `finestra_acquisto_ideale` che diceva *quando* sarebbe il momento buono. Incrociarle era lavoro suo.

## D.2 La taratura, fatta sui dati

Rianalizzato il dataset grezzo **già presente nel repo** (`bot_profit_output/pattern_raw_transactions_20260729_1845.csv`: 3658 transazioni reali su 142 carte, prodotto da `bot_profit_pattern_export.py`) — **nessuna query nuova verso Sorare**. Domanda posta ai dati: *"se compro a questo prezzo, com'è il prezzo della stessa carta nelle 48 ore successive?"*

**Sconto rispetto alla media della carta nei 3 giorni precedenti:**

| sconto | n | mediana a 48h | % casi in guadagno |
|---|---|---|---|
| < 0% (sovrapprezzo) | 1690 | −4,3% | 33-42% |
| 0-5% | 295 | +0,8% | 55% |
| 5-10% | 217 | +3,2% | 59% |
| 10-20% | 315 | +7,9% | 70% |
| ≥ 20% | 310 | **+25,2%** | **82%** |

Lo sconto è il segnale **dominante e monotono**; il sovrapprezzo è altrettanto affidabile al contrario. Gli altri due fattori sono moltiplicatori, non motori:

- **Trend** (a parità di sconto ≥10%): down +9,9% / 68% positivi · flat +17,7% / 84% · up +25,4% / 88%.
- **Finestra temporale** (a parità di sconto ≥10%): dentro −3,5/−2,5 giorni dal kickoff **+21,0% / 93% positivi**, fuori +14,0% / 75%. La finestra **non crea** l'occasione, la amplifica di ~1,4x.
- **Zona di premio**: il prezzo smette di essere scontato e passa in premio a circa **−2,25 giorni** dal kickoff (−2,5gg: −4,2%, ma già −2,0gg: +6,6%, −1,0gg: +3,7%, kickoff: +2,9%). Comprare lì è il momento peggiore.

## D.3 Cosa produce adesso il bot

`valuta_occasione()` calcola un **`punteggio_occasione` = stima del guadagno % a 48 ore**: un numero che si legge direttamente ("questa carta vale circa +18%"), non un indice astratto. Interpolazione lineare sulle mediane misurate (`BUY_SIGNAL_CURVE`), moltiplicata per trend e finestra, con la coda alta **compressa** oltre +25% (non tagliata di netto, che appiattirebbe le carte migliori tutte sullo stesso numero perdendo l'ordine tra loro).

Quattro colonne nuove nel CSV: `segnale`, `punteggio_occasione`, `motivo_segnale`, `aggiornato_il`.
Livelli: **COMPRA ORA** · buona occasione · neutro · evita (sovrapprezzo) · dato non aggiornato.

**`COMPRA ORA` richiede due condizioni insieme**: superare la soglia assoluta (`BUY_SIGNAL_SOGLIA_COMPRA`=10, cioè +10% atteso) **e** essere tra i primi `BUY_SIGNAL_MAX_PER_GRUPPO`=8 del proprio campionato. Il secondo non è cosmetico: lo sconto medio varia enormemente da lega a lega e da momento a momento (in uno snapshot reale: mediana +15,8% in MLS, +8,1% in K-League, −0,2% in Eredivisie/Belgio) — con la sola soglia assoluta in MLS sarebbero finite in giallo 27 righe su 50, che non è un segnale ma un colore di sfondo.

**Ordinamento del CSV cambiato**: prima il verdetto, poi il punteggio, poi `potenziale_score` come spareggio. Nessun COMPRA ORA può più finire tagliato fuori dal top 50 — prima poteva succedere, perché il taglio era per `potenziale_score`, dove il timing pesa 0,40 e poteva sotterrare una carta con uno sconto enorme ma la partita lontana.

**Freschezza**: `aggiornato_il` registra quando la riga è stata davvero rinfrescata. Oltre `SEGNALE_MAX_AGE_HOURS`=12 il segnale viene sospeso con motivo esplicito. Serve perché la classifica è persistente: un prezzo di due giorni fa non deve poter generare un "COMPRA ORA".

**`TREND_SCORE_MULTIPLIER` ritarato**: era `{up: 1.2, flat: 1.0, down: 0.5}`. Il verso è confermato, ma la penalità su `down` era troppo dura — 'down' non è un esito negativo (mediana +9,9%, due volte su tre in guadagno), mentre 0.5 lo dimezzava fino a farlo sparire. Ora `{up: 1.25, flat: 1.0, down: 0.65, None: 0.85}`.

> **Insidia statistica da conoscere**: guardando il trend **senza controllare per lo sconto**, 'down' sembra addirittura il migliore (+5,5% contro +3,4% di 'up'). È un artefatto — in un mercato in calo la singola transazione è già bassa e rimbalza per pura regressione verso la media. Il confronto valido è **a parità di sconto**.

## D.4 Il vecchio `potenziale_score` (è ancora lì)

Non è stato rimosso, resta come colonna e come spareggio nell'ordinamento:

```
0.40 × peso_timing + 0.15 × (ultima_partita/100) + 0.10 × media_generale + 0.35 × sconto_normalizzato
```
con `media_generale = (0.5·L5 + 0.3·L10 + 0.2·L40)/100`, il timing a bucket (`<48h → 0.1`, `48-96h → 1.0`, `oltre → 0.3`), una penalità × 0,3 sull'intero punteggio se lo sconto è sotto −15% (sovrapprezzo estremo) e `ultima_partita_score` clampato a `L5+20` (perché una singola partita eccezionale non pesi come forma consolidata).

Entrambe queste ultime due correzioni vengono da casi reali trovati dall'utente (Nicolás Fernández-Mercau e Jonathan Bond, 28/07). **Sono un buon esempio del metodo che funziona meglio con lui**: trovare una carta concreta il cui punteggio non torna, scomporre la formula, confrontarla con pick che lui ha già validato, e solo allora proporre il fix.

## D.5 Due bug reali corretti il 30/07

1. **Righe sotto soglia sopravvissute nella classifica persistente.** 45 righe su 144 avevano un prezzo minimo sotto i 2,5 EUR (fino a 1,24 EUR): `load_previous_tracked` non riapplicava `MIN_PRICE_EUR_THRESHOLD`, quindi righe scritte quando la soglia era 1 EUR erano rimaste dentro anche dopo che l'utente l'aveva alzata a 2 e poi a 2,5. Su una carta da 1,24 EUR anche un 17% di sconto vale 21 centesimi. Filtro ora applicato anche in scrittura.
2. **`Retry-After` applicato anche agli "straggler"** — cioè ai 429 che sono solo le risposte di richieste già in volo quando la barriera si era alzata. Ognuno spostava la fine della barriera a "adesso + 45s", facendola scorrere in avanti per un evento già gestito. Ora si applica solo sulla nuova ondata.

---

# PARTE E — Il viewer HTML

Legge un CSV (drag&drop, file picker, o `?csv=<url>` per il caricamento automatico dal link Telegram) e lo mostra come tabella filtrabile e ordinabile.

- **Bottone 🟡 Compra ora**: illumina in giallo le righe COMPRA ORA. *Un primo tentativo con l'evidenziazione sempre accesa è stato scartato dall'utente* — colorava la tabella in permanenza invece di rispondere a una domanda quando gliela si fa.
- **I COMPRA ORA sono già in cima** senza ordinare nulla: l'ordinamento di default è per guadagno atteso decrescente, e COMPRA ORA è per costruzione l'insieme dei punteggi più alti del gruppo. Verificato: occupano le posizioni 1-8.
- **Tabella compattata da 1448px a 1038px** (16 → 13 colonne): a 1090px di larghezza non serve più scorrere in orizzontale. L'utente è tornato più volte sul tema "compatta, non voglio scorrere" — **tenerne conto prima di aggiungere colonne**.

**Punto di metodo importante**: il verdetto **non viene ricalcolato nel viewer**. Prima `bot_profit.py`, il viewer e la notifica Telegram avevano tre formule parallele per la stessa domanda, che potevano contraddirsi (la notifica poteva segnalare una carta diversa da quella evidenziata nel viewer aperto dallo stesso link). Ora la regola vive **solo** in `valuta_occasione`/`_assegna_segnali`, e gli altri due **leggono la colonna** del CSV. Se cambi la regola, cambiala lì.

**Il viewer non può caricare `file://` in tutti gli ambienti**: per provarlo dal vivo, `python -m http.server` in una cartella con viewer + CSV, poi aprire `http://localhost:<porta>/viewer.html?csv=http://localhost:<porta>/<file>.csv`. Funziona.

---

# PARTE F — Parametri

Tutti sovrascrivibili da variabile d'ambiente; i più importanti sono anche input del workflow.

| Parametro | Default | Cosa fa |
|---|---|---|
| `MIN_PRICE_EUR_THRESHOLD` | 2.5 | sotto questo minimo la carta è scartata subito |
| `MIN_TRANSACTIONS_FOR_RANKING` | 15 | sotto, il dato è troppo rumoroso per la classifica |
| `ROSTER_MIN_AVG_SCORE` | 35.0 | L5, L10 e L40 devono superarla tutte e tre |
| `TOP_N_OUTPUT` | 50 | righe per CSV |
| `TRANSACTIONS_WINDOW_DAYS` | 7 | finestra della media transazioni |
| `PREZZO_BASSO_SKIP_DAYS` | 2 | TTL blacklist per prezzo basso |
| `SNAPSHOT_WORKER_THREADS` | 10 | giocatori in parallelo |
| `COMMIT_CHUNK_SECONDS` | 30 | ogni quanto il bot committa |
| `ROSTER_CACHE_HOURS` | 18 | validità cache roster (0 = disattivata) |
| `GRAPHQL_MIN_INTERVAL_SECONDS_FAST` | 0.2 | ritmo iniziale |
| `GRAPHQL_MIN_INTERVAL_SECONDS_SAFE` | 0.9 | ritmo sostenibile misurato: pavimento dopo il primo 429 |
| `GRAPHQL_MAX_INTERVAL_SECONDS` | 1.5 | tetto del ritmo adattivo |
| `GRAPHQL_PACE_BACKOFF_FACTOR` | 1.6 | quanto rallenta a ogni ondata |
| `GRAPHQL_PACE_RECOVER_EVERY` | 40 | successi consecutivi prima di riaccelerare |
| `GRAPHQL_429_GLOBAL_PAUSE_SECONDS` | 5.0 | pausa condivisa alla prima ondata (poi vince `Retry-After`) |
| `GRAPHQL_MAX_RETRIES` | 5 | tentativi per richiesta |
| `BUY_SIGNAL_SOGLIA_COMPRA` | 10.0 | guadagno atteso minimo per COMPRA ORA |
| `BUY_SIGNAL_SOGLIA_BUONA` | 4.0 | soglia "buona occasione" |
| `BUY_SIGNAL_MAX_PER_GRUPPO` | 8 | tetto COMPRA ORA per campionato |
| `SEGNALE_MAX_AGE_HOURS` | 12 | oltre, il segnale è sospeso |
| `TREND_RECENT_WINDOW_DAYS` | 2 | finestra "recente" per il trend |
| `TREND_FLAT_THRESHOLD_PERCENT` | 10.0 | soglia up/down |

---

# PARTE G — Da dove ripartire

## G.1 Stato

Tutto committato e pushato su `main`; `git pull origin main` e sei operativo. Ultima run: **74, verde, 2m42s, zero 429**. Il bot è in uno stato migliore di come era all'inizio della giornata su entrambi i fronti richiesti.

Verifiche fatte senza consumare run Sorare: 23 controlli automatici sull'intera pipeline (ordinamento dei trend, effetto finestra, penalità partita imminente, sovrapprezzo/dato vecchio/partita passata a zero, monotonia della curva, cache roster in scrittura/rilettura/invalidazione, scrittura dei 3 CSV, tetto COMPRA ORA per gruppo, nessun COMPRA ORA su dati vecchi, colonne complete), viewer provato dal vivo in un browser reale su CSV veri, test di stress del rate limiter, sintassi Python e YAML validate.

## G.2 Aperto, in ordine di priorità

1. **Verificare la prima run con cache SCADUTA** (TTL 18h, quindi il giorno dopo). È l'unico pezzo del lavoro sul rate limit mai provato sul campo: le correzioni fatte dopo la run 73 dovrebbero portare le ondate da 4 a 1.
2. **Chiedere all'utente se i COMPRA ORA hanno senso** guardando l'output reale. La taratura è statisticamente solida ma non ha ancora passato il suo giudizio su casi concreti — che è il metodo che ha trovato più bug veri (vedi D.4).
3. **`ROSTER_CACHE_HOURS`=18 è prudente, non misurato.** Alzarlo a 48-72h renderebbe *tutte* le run come la 74 invece di una sì e una no. Da decidere **con lui**, perché allunga la finestra in cui un giocatore appena trasferito resta associato alla squadra vecchia (è un caso già noto, un certo Leo Sauer).
4. **`BUY_SIGNAL_MAX_PER_GRUPPO`=8 e `BUY_SIGNAL_SOGLIA_COMPRA`=10** sono stati scelti guardando la distribuzione di **un solo** snapshot: rivederli con più dati.
5. **`TREND_RECENT_WINDOW_DAYS`/`TREND_FLAT_THRESHOLD_PERCENT`** (2gg/10%) non sono mai stati ricalibrati — voce aperta dal 28/07. Ora il dataset per farlo esiste (`pattern_raw_transactions_*.csv`), non è più un problema di dati.
6. **Estendere a tutti i campionati.** Non affrontato in sé: qui il bot è stato reso *capace* di reggerlo, l'aggiunta vera (whitelist squadre, gruppi di output) resta da fare — ed è il motivo per cui l'utente ha chiesto il lavoro sul rate limit. Oggi sono coperti MLS (30 squadre), K-League (12), Eredivisie (18) e Belgio (18).
7. Restano ~370 giocatori MLS mai revisionati per la `blacklist_manuale`. Il flusso che ha funzionato: un artifact HTML con checklist + `localStorage` + textarea copiabile, che l'utente compila e reincolla in chat. **`sendPrompt` non esiste negli artifact pubblicati** — non provare a farlo tornare indietro da solo.

## G.3 Riepilogo delle trappole (tutte già pagate)

- Non riproporre il filtro "salta le squadre lontane dalla partita" (C.5).
- Non confrontare le run per durata, ma per 429/ondate/richieste (C.6).
- Non valutare il trend senza controllare per lo sconto (D.3).
- Non fidarti di un "verificato" scritto nei commenti senza una run reale che lo confermi (B.2).
- Se cambi un filtro, chiediti se va applicato anche in scrittura: la classifica è persistente e le righe vecchie non si rifiltrano da sole (B.3, D.5).
- Nel worktree temporaneo usa lo sha esplicito del commit, non `$(git rev-parse HEAD)` (A.6).
- Se scrivi un simulatore del rate limiter, scala **tutte** le costanti di tempo dello stesso fattore: la prima versione scalava il bucket ma non la barriera e andava in timeout senza motivo apparente.
