# Sorare tracker (track.py) — riepilogo sessione (fino al 17/07/2026, sessione 3)

Bot Python che monitora il mercato Sorare (GraphQL + WebSocket), traccia il prezzo minimo
per giocatore/bucket (in_season vs classic) e manda notifiche Telegram sugli affari.
Deploy tramite GitHub Actions ("Sorare Price Check" / check.yml, "Auction WebSocket
Listener" / auctions_ws_listener.yml). Io modifico `track.py`, l'utente lo pusha.

File di lavoro: `track.py` nella cartella Cowork collegata — vedi "Note operative" in fondo
per QUALE cartella usare (sono due, non equivalenti). E' la versione più aggiornata, va
ripresa da qui alla prossima sessione — non serve rifare nulla di quanto sotto.

## Fix già fatti (riferimento rapido, tutti in track.py)

Margini tarati per fascia di prezzo su vari casi reali (Pec/Guéhi, Kounde, Rodrigo, Manu
Duah, Penders, Diallo); soglia calo minimo 13%→8%; fix eccezione Frank Feller; fix
finestra invisibilità (caso Bjørkan); revert della logica "scavalca cluster" (troppo
rischiosa, caso infortunio/prezzo crollato); fix "dati incompleti" ricorrente (scambi
carta-per-carta esclusi dalla verifica live, non solo dagli eventi WS); fix "bug del
centesimo" (tolleranza 1% + niente coda infinita in riverifica, poi raffinato con
confronto slug — vedi Manu Duah sotto); fix bucketing in_season/classic (uso di
`inSeasonEligible` invece di confronto stringa statica sul nome stagione — risolve
casi tipo "2025" senza trattino, es. Harvey Elliott/Aston Villa); notifica veloce
"⚡ Occasione VELOCE (non verificata)" con soglie dedicate; notifica "📐 Opportunità di
margine" (margine ampio anche senza calo storico) con dedup contro la veloce; fix
`auctions_ws_listener.yml` (mancava `ref: main` nel checkout, causava run in coda su dati
vecchi); riepilogo decisioni a fine log; cross-bucket classic/in_season (caso Luis Díaz);
scoperta query storico vendite reali `tokenPrices(playerSlug, rarity: limited)`; avviso
soft "vendita recente più economica" (no blocco duro, solo avviso nel messaggio); avviso
"mercato sottile" (poche vendite reali in 21gg); rimossa la registrazione automatica di
ogni vendita conclusa sul mercato (troppo costosa, sostituita da niente — la tabella
`sale_history` resta nello schema ma non si popola più); fix bug reale caso Manu Duah
(confronto anche sullo slug, non solo sulla percentuale di scarto, per distinguere
"stesso annuncio riletto" da "annuncio diverso genuinamente invisibile").

**Sessione 2 (17/07, analisi di 3 log di produzione consecutivi + fix):**
fix margine negativo nel cross-bucket classic/in_season (caso Franko Kolić: quando la
carta in_season sostituta è più economica anche del `true_min_price` classic stesso, non
solo del secondo prezzo, si otteneva un margine assurdo tipo -79.2% — ora caso dedicato
`skip_in_season_substitute_cheaper`, niente calcolo di margine in quel verso); dump
diagnostico grezzo (`log_raw_offers_diagnostic`, su ogni ALERT) ridotto dalle 8-64+ righe
per singolo evento alle 8 più economiche ordinate per prezzo (`DIAGNOSTIC_MAX_ROWS`),
conteggio totale comunque loggato; nuovo gate "vendite recenti già più economiche"
(`count_cheaper_recent_sales`). Prima versione: `RECENT_SALE_GATE_MIN_CHEAPER=3` su
`RECENT_SALE_GATE_SAMPLE_SIZE=5`, finestra 7gg (riusando `RECENT_SALE_WINDOW_DAYS`) —
l'utente ha ripensato subito dopo ("rendiamolo meno hard"): soglia finale **6 su 6**
(non più maggioranza semplice) su una finestra propria più ampia, **14 giorni**
(`RECENT_SALE_GATE_WINDOW_DAYS`, separata da `RECENT_SALE_WINDOW_DAYS=7` che resta quella
dell'avviso soft esistente `find_cheaper_recent_sale`, invariato). `get_recent_sale_history`
ora chiamata con `last_n=RECENT_SALE_GATE_SAMPLE_SIZE` (6, era 5 di default) in entrambi i
punti di notifica per avere il campione pieno. Se tutte e 6 le vendite reali negli ultimi
14gg sono pari o più economiche del prezzo segnalato, la notifica (sia ALERT diretto che
"Opportunità di margine") viene bloccata ma loggata comunque con `BLOCCATO` per controllo
manuale; con meno di 6 vendite nella finestra il campione è troppo piccolo, niente blocco
(resta solo l'avviso "mercato sottile" già esistente). **Limite noto non risolto**: questo
gate confronta contro TUTTE
le vendite recenti del giocatore via `tokenPrices`, mescolando classic e in_season senza
poterle distinguere (tokenPrices non espone la stagione per singola vendita, verificato
per tentativi — vedi backlog item 6 sotto). Scelta esplicita dell'utente: accettare
questo mix piuttosto che aspettare settimane di dati scoped o bloccare la feature.

## Casi chiusi come "non bug" (verificati con log/screenshot reali, nessuna azione)

- Jeong Seung-Won / Max Arfsten: il countdown Sorare mostra il tempo RESTANTE (non
  trascorso), durata scelta dal venditore (1-7gg) — tempo di vita di un annuncio
  strutturalmente ambiguo dalla sola UI.
- Kevin De Bruyne "secondo prezzo mancante": verificato sul dump grezzo, il prezzo
  sospettato non esisteva alla query, comparso dopo.
- Max Arfsten/4.74€ non tracciato: stesso pattern Duah, l'annuncio che ha innescato
  l'evento non era ancora visibile alla query (finestra invisibilità ~2min).
- "Due carte a un centesimo, arriva la notifica?" — NO, il controllo margine per fascia
  di prezzo la blocca già (`skip_margin_too_close`, `return` prima di notificare).

## 🔴 BACKLOG COMPLETO — aperto, dal più vecchio

1. ~~**Gating del controllo margine al calo minimo storico**~~ — **IMPLEMENTATO 17/07
   (sessione 2).** Il controllo "margine troppo vicino al secondo prezzo" girava per
   qualsiasi calo, anche minimo, riaccodando in `pending_recheck` casi che non avrebbero
   mai potuto superare `DROP_THRESHOLD` nemmeno dopo un doppio controllo riuscito. Ora il
   blocco "troppo vicino, riaccoda" scatta solo se `drop_percent >= DROP_THRESHOLD`; i
   cali sotto soglia proseguono verso il ramo "piccola variazione" esistente (stesso esito,
   nessuna notifica ALERT, ma niente riverifica sprecata). `margin_percent`/
   `second_min_price` restano comunque calcolati per ogni caso, perché servono anche al
   ramo "opportunità di margine" indipendentemente dal calo storico.
   Nota (17/07, verificato su 3 log consecutivi, prima del fix): quando le esecuzioni sono
   ravvicinate (3-7 min), la coda `pending_recheck` veniva comunque svuotata correttamente
   senza scarti per età — lo scarto per timeout osservato in un log era dovuto solo a un
   buco di ~7h44m tra esecuzioni overnight, non a un difetto del meccanismo.

2. **Filtro "no sales history" (caso Luca Podlech)** — giocatori nuovi/appena aggiunti
   dove il primo prezzo visto diventa floor "a caso": i cali successivi possono sembrare
   affari ma sono solo rumore da mancanza di storico. **Mai implementato.** Riconfermato
   il 17/07 (l'utente pensava fosse già risolto, non lo era): in `evaluate_player_offer`,
   quando `floor_row is None` si inizializza il floor al primo prezzo visto senza nessun
   controllo su quanti dati storici ci sono dietro.
   **Aggiornamento 17/07 (sessione 2, dopo il gate mercato sottile):** valutato se il nuovo
   gate `skip_thin_market_gate` (<4 vendite reali in 21gg, vedi sopra) risolvesse il caso
   di riflesso — risposta: solo parzialmente. Il gate guarda le vendite REALI concluse
   (`tokenPrices`), il bug Podlech riguarda il NOSTRO floor (giocatore appena aggiunto al
   tracking). Coincidono solo se il giocatore è anche poco tradato sul mercato reale (caso
   più comune, coperto); se il giocatore ha uno storico di vendite reali sano ma è solo il
   nostro tracking ad essere nuovo, il gate non copre il bug. **Accantonato dall'utente
   come caso limite** (17/07) — non implementare a meno che ricapiti concretamente su un
   giocatore con mercato reale liquido.

3. **Pattern-mining manager sniper (ZenLock/Satonio)** — idea originale (studiare gli
   acquisti pubblici di un manager/bot specifico per calibrare meglio le soglie). **Fase
   di analisi completata (sessione 2), fase di modello/tracker live completata (sessione
   3, vedi item 8 e sezione dedicata sotto).**

   Scoperta chiave: indagine DevTools manuale (pagina "Cronologia delle vendite" di un
   giocatore) ha trovato che `tokens.tokenPrices` accetta un sotto-campo `deal` (union
   type `TokenDeal`, richiede `... on TokenOffer { type buyer{...on User{...}}
   seller{...on User{...}} }`) — smentisce la vecchia nota "tokenPrices non distingue il
   tipo" (i vecchi tentativi in `discover_token_price_type_field` cercavano il campo
   direttamente su `TokenPrice`, non dentro `deal`, ed era un union quindi comunque non
   avrebbero mai funzionato senza frammento inline). Confermato empiricamente (dati reali
   incrociati con screenshot multipli): `SINGLE_SALE_OFFER` = annuncio a prezzo fisso
   comprato al volo (UI: etichetta fuorviante "Scambia") = il vero sniping;
   `SINGLE_BUY_OFFER` e `DIRECT_OFFER` = offerte negoziate (UI: entrambe "Offerta
   diretta") = non lo sniping.

   Script/workflow separati dal bot principale (per non impattare mai `check.yml`):
   `snipe_pattern_analysis.py` (importa `track.py`, riusa `fetch_user_recent_cards`,
   `filter_recent_direct_buy_candidates`, `fetch_player_recent_direct_buys`,
   `diagnostic_snipe_pattern_report`), lanciato da due workflow `workflow_dispatch`
   dedicati: `snipe_pattern.yml` (default zenlock) e `snipe_pattern_satonio.yml` (default
   satonio, parametri di partenza più bassi dato 427k+ carte contro le 1552 di zenlock).
   Rinominato da `satonio_snipe_*` a `snipe_pattern_*` a meta' sessione (il nome faceva
   confusione, i primi test erano su ZenLock non Satonio) — i vecchi file
   `satonio_snipe_analysis.py`/`satonio_snipe.yml` sono rimasti nel repo ma inutilizzati,
   l'utente li rimuoverà a mano quando vuole (rifiutato il permesso di cancellazione
   automatica in sessione).

   Pipeline (dopo un giro di correzioni sullo schema reale, vedi sotto): 1) `searchCards`
   sul manager per la lista di carte possedute ordinate per acquisizione più recente; 2)
   filtro RAPIDO a blocchi (`anyCards(slugs:[...])`, 40 per chiamata) su `tokenOwner.
   transferType`/`from` per scartare subito le carte non acquisite via SINGLE_SALE_OFFER
   nella finestra (aggiunto dopo, vedi sotto, per velocità); 3) solo sui pochi giocatori
   sopravvissuti, query completa `tokenPrices` per prezzo esatto + calcolo margine
   (mediana delle altre vendite SINGLE_SALE_OFFER dello stesso giocatore, ESCLUSE le
   transazioni dove il manager stesso è compratore o venditore, per non inquinare la
   mediana con le sue stesse rivendite/flip — richiesta esplicita dell'utente).

   Correzioni di schema fatte in diretta sui log reali (query tutte ricostruite a mano,
   nessun testo originale disponibile, persistite lato client): `rarity: limited` non
   `"limited"` (e' un enum); `deal` e `buyer`/`seller` sono union type, servono frammenti
   inline `... on TokenOffer`/`... on User`. Poi ottimizzazione performance su richiesta
   esplicita dell'utente ("ci mette un bel po'"): aggiunta `filter_recent_direct_buy_
   candidates` (query a blocchi su `anyCards`) per evitare di interrogare per intero
   OGNI giocatore trovato (anche 400+) quando la maggioranza delle carte non sono manco
   arrivate lì via sniping — sceso da ~1-2 minuti a pochi secondi per lo stesso volume.

   **Dati raccolti (17/07, da tenere a mente per confronti futuri):**
   - **ZenLock** (1552 carte totali, scansione COMPLETA raggiunta): 13 acquisti
     SINGLE_SALE_OFFER in 30gg, prezzo medio 3.89€ (0.45€-16.08€), sconto medio vs
     mediana altre vendite 38.2% (su 12/13 con campione disponibile). Compra
     prevalentemente carte economiche/scarto, occasionalmente giocatori più noti quando
     il margine è ampio. Un solo outlier "sovrapprezzo": Guillermo Varela -10.8% (campione
     2, probabile rumore o carta con XP che giustifica il prezzo più alto).
   - **Satonio** (427k+ carte, scansionabile solo in minima parte): 10 acquisti
     SINGLE_SALE_OFFER in 10gg (**9 di questi già nei primi 3gg** — allargare la finestra
     da 3 a 10gg ha aggiunto UN SOLO caso, conferma forte che la maggior parte delle sue
     sniping più vecchie di qualche giorno sono invisibili col metodo attuale perché già
     rivendute), prezzo medio 10.14€ (0.48€-26.94€), sconto medio 23.6% (su 7/10). Ritmo
     molto più alto di ZenLock (~1/giorno contro ~0.4/giorno, e probabilmente sottostimato
     ancora di più), punta su carte mediamente più costose (spesso 14-27€, non solo
     scarto). Anche qui un outlier "sovrapprezzo": Albert Rusnak -48.9% (campione 2).
   - **Pattern comune a entrambi**: sconto percentuale richiesto più alto sulle carte
     economiche, più basso su quelle costose — stesso principio della nostra
     `MARGIN_TIERS`, anche se le percentuali di questi bot sono spesso molto più
     aggressive delle nostre soglie attuali sulle fasce basse.
   - **Curiosità**: ZenLock ha comprato una carta (Thomas Müller, 16.08€) direttamente
     DA Satonio — i due manager si sono incrociati nello stesso periodo osservato.

   **BREAKTHROUGH e IMPLEMENTATO (17/07, stessa sessione, poco dopo):** risolto il limite
   "carte già rivendute invisibili" alla radice. Su suggerimento dell'utente ("e se provo a
   cercare nelle query di una vendita di zenlock?"), indagine DevTools sulla pagina
   pubblica "Transazioni" del profilo di un manager
   (`sorare.com/it/football/my-club/<slug>/transactions`, pubblica per QUALSIASI manager,
   a differenza di `UserAccountEntriesQuery` che è scoped solo a `currentUser` — vicolo
   cieco esplorato e scartato prima di questo) ha trovato il campo root
   `user(slug).trades`: ritorna DIRETTAMENTE tutta la cronologia di transazioni del
   manager, sia ACQUISTI che VENDITE, di qualunque giocatore, paginata (Relay-style,
   `pageInfo{endCursor, hasNextPage}`). Non serve più partire dalle carte possedute, quindi
   niente più carte invisibili perché già rivendute.

   Nuova funzione `fetch_user_trades(user_slug, window_days, eth_rate, max_pages)` in
   `track.py` (query `SnipeUserTrades`, stesso union-type issue già visto su `deal` — serve
   `... on TokenOffer` sui nodi e `... on User` su sender/receiver). Determina il ruolo del
   manager (buy/sell) in ogni transazione confrontando `sender.slug`/`receiver.slug` con
   `user_slug` e guardando quale lato ha le carte (venditore) vs l'importo (compratore); se
   nessuno dei due combacia (caso `receiver: null` tipico di `SINGLE_SALE_OFFER` pubblico,
   sia da compratore che da venditore — il campo non è mai esposto per un annuncio anonimo),
   il manager è la controparte implicita con ruolo opposto al sender. Nuova funzione di
   report `diagnostic_manager_trades_report`, che oltre a listare acquisti/vendite separati
   ricostruisce per ogni vendita l'acquisto precedente della stessa carta (stesso
   `card_slug`) per calcolare il margine del ciclo compra-poi-rivendi.
   `snipe_pattern_analysis.py` ora chiama questa nuova funzione al posto della vecchia
   `diagnostic_snipe_pattern_report` (rimasta in `track.py` non rimossa, per ora inutilizzata).

   **Primo test reale (17/07, ZenLock, finestra 3gg):** 111 transazioni totali — 14 snipe
   diretti (SINGLE_SALE_OFFER, prezzo medio 4.13€, 0.48€-16.01€), 33 acquisti negoziati
   (SINGLE_BUY_OFFER/DIRECT_OFFER), 64 vendite. Di queste 64 vendite, 12 hanno un acquisto
   precedente rintracciabile nella stessa finestra di 3gg, con margini di rivendita tra
   +0.8% e +148.8% (spesso rivende entro poche ore/1-2 giorni dall'acquisto — conferma
   diretta, con dati concreti, del sospetto "vende quasi subito" che aveva reso il vecchio
   metodo (carte possedute) fortemente sottostimato). **Limite noto e confermato**: il
   controparte delle vendite risulta quasi sempre "?" — non un bug, il campo `receiver` non
   è esposto dall'API per gli annunci `SINGLE_SALE_OFFER` anonimi, né quando il manager
   compra né quando vende (verificato su entrambi i lati).

   Terminologia "Scambia"/"Offerta diretta" riconfermata una volta di più con un terzo
   esempio indipendente (screenshot carta di Ismael Saibari, cronologia carta + tab
   Transazioni di ZenLock): "Scambia" = tipo `SINGLE_SALE_OFFER` = sniping vero.

   **Idee aggiuntive dell'utente (da tenere presente, non ancora implementate):**
   - Quando un bot come ZenLock fa sniping da un venditore, quel venditore va
     segnato/tracciato come "attenzionabile" (probabile prezzi bassi ricorrenti).
   - Tracker separato per le offerte "di tipo scambio" (probabilmente intende
     SINGLE_BUY_OFFER/DIRECT_OFFER, la UI le chiama "Offerta diretta" — chiarire di
     nuovo con l'utente prima di implementare, stessa confusione terminologica di inizio
     indagine).
   - Notato ma non ancora indagato: ZenLock ha fatto un'offerta a un prezzo più basso
     entro ~1 minuto da quando l'utente ha messo in vendita una propria carta — comportamento
     diverso dallo sniping puro, sembra piu' simile a monitoraggio attivo di nuovi annunci.

4. **Tracker periodico sulle proprie carte in vendita (~ogni 4h)** — notificare se
   compaiono carte identiche a prezzo più basso delle proprie. Mai iniziato: serve
   capire come recuperare via API la lista di annunci attivi dell'utente, e definire
   con precisione cosa vuol dire "carta uguale" (stesso giocatore/stagione/rarità?).

5. **Scansione periodica indipendente di tutti i giocatori tracciati** (proposta mia,
   mai confermata dall'utente) — il bot è puramente event-driven per giocatore, un
   floor può restare stantio indefinitamente se non arriva un evento WS per quel
   giocatore specifico.

6. **Scoping classic/in_season per lo storico vendite (`tokenPrices`)** — `tokenPrices`
   (unica fonte di vendite reali retroattive) non espone la stagione per singola
   transazione (season/sportSeason/cardSlug/tokenSlug tutti assenti su `TokenPrice`,
   verificato per tentativi in una sessione precedente). Effetto pratico: sia l'avviso
   soft "vendita recente più economica" sia il gate 6/6 in 14gg confrontano contro
   vendite che potrebbero essere classic O in_season indistintamente, anche quando la
   carta segnalata è specificamente una delle due. L'alternativa scoped
   (`sale_history`/`get_own_recent_sales`) esiste nello schema ma non si popola più
   (cattura disattivata per costo, item già chiuso in passato) e comunque partirebbe da
   zero. **Decisione esplicita dell'utente: lasciare il mix com'è per ora.**
   Da riaprire solo se si trova un altro campo/query che espone la stagione per vendita
   (varrebbe la pena un'indagine live con Claude-in-Chrome sul traffico di rete della UI
   Sorare, che da qualche parte deve mostrare lo storico vendite scoped per carta — vedi
   anche approccio usato con successo in sessione 3 per il bug valuta, stesso principio).

7. **Pattern-mining bot "Barren Wuffett"** — stesso trattamento di ZenLock/Satonio, pipeline
   già pronta e generica (`fetch_user_trades`/`diagnostic_manager_trades_report`). Serve
   solo un nuovo yml dedicato (stesso schema di `snipe_pattern.yml`) con `user_slug` di
   default sullo slug esatto di Barren Wuffett (da verificare su Sorare, non ancora
   confermato). Nessun nuovo codice Python previsto. Richiesto dall'utente il 17/07,
   non ancora iniziato.

8. ~~**Osservatore live snipe ZenLock/Satonio (margine esatto in tempo reale)**~~ —
   **IMPLEMENTATO 17/07 (sessione 3), testato in produzione, funzionante.** Vedi sezione
   dedicata sotto per il dettaglio completo (design, bug trovati/risolti, validazione).
   Prossimo passo naturale, non ancora fatto: schedularlo in continuo (stesso meccanismo
   esterno — cron-job.org — già usato per il tracker principale). URL dispatch:
   `https://api.github.com/repos/andreasalvatore93-oss/Sorare-tracker-2/actions/workflows/zenlock_model_tracker.yml/dispatches`,
   stesso body/header dello sniper esistente.

9. **BUG CRITICO trovato e risolto (17/07, sessione 3): prezzi USD/GBP letti come "assenti"
   in TUTTO il codice** — vedi sezione dedicata sotto. Impatta sia il tracker principale
   che il modello ZenLock, già fixato in `track.py` (condiviso). Da tenere d'occhio nei
   prossimi log del tracker principale per confermare che non introduce regressioni (solo
   aggiunte, nessuna logica esistente toccata).

## 🆕 Sessione 3 (17/07, pomeriggio-sera) — Tracker "Modello ZenLock" + bug critico valuta

Continuazione diretta della sessione 2: dopo la raccolta dati via `fetch_user_trades` (vedi
item 3 sopra), l'utente ha chiesto di costruire un tracker LIVE che replica il comportamento
di sniping di ZenLock, per farlo girare in continuo accanto al tracker principale.

### Analisi propedeutica (prima di scrivere codice)

Approfondito il comportamento di acquisto (solo snipe puri, `SINGLE_SALE_OFFER`) su più
finestre (7/10/14gg), con bucket in_season/classic (`season_type_for_card`, riusata da
`fetch_user_trades`) e fasce di prezzo. Trovato e **fixato un bug bundle** in
`fetch_user_trades`: transazioni multi-carta (un solo prezzo aggregato per più carte)
venivano attribuite per intero a OGNI carta del bundle, gonfiando falsamente i margini
(specialmente su Satonio, che fa molti scambi bulk). Fix: `bundle_size = len(cards)`, se
`> 1` il prezzo per-carta diventa `None` (escluso dalle statistiche), ma bundle_size e
prezzo totale restano loggati per trasparenza.

**Conclusioni chiave (14gg, dati puliti post-fix bundle):**
- **ZenLock**: 731 tx (86 snipe/12%, 226 negoziate, 419 vendite). Snipe: media 4.15€,
  in_season 48/86 (56%, media 5.15€) vs classic 38/86 (44%, media 2.89€), 57% sotto 3€.
  Sconto medio vs mediana mercato (quando disponibile, solo 10/86 casi = 11.6%, il resto
  compra carte troppo di nicchia per avere comparabili) ~40%, mediana ~41%.
- **Satonio**: 1506 tx (16 snipe/1%, 192 negoziate, 1298 vendite quasi tutte bundle) —
  confermato liquidatore bulk, NON sniper vero. Campione snipe troppo piccolo (16) per
  soglie proprie affidabili; sui 9 casi con confronto disponibile lo sconto medio è ~2.3%
  (range -48.9%/+51.5%) — compra vicino al prezzo di mercato, a volte sopra, nessuna
  disciplina di sconto misurabile. **Decisione presa**: il modello unificato usa SOLO
  ZenLock come fonte delle soglie (unico dei due con comportamento calibrabile); Satonio
  resta utile solo come conferma qualitativa ("comprare senza sconto non è profittevole in
  modo sistematico"), non come co-fonte delle soglie.
- `diagnostic_snipe_margin_model_report` (nuova funzione in `track.py`, richiamata da
  `snipe_pattern_analysis.py` con `SNIPE_REPORT_MODE=margin_model`) arricchisce ogni snipe
  con sconto% vs mediana di mercato (via `fetch_player_recent_direct_buys`, riusata) e
  stampa una tabella soglie per fascia prezzo × stagione.

### Tracker live — design e file

Backlog #8/#11: script e workflow **completamente separati** dal tracker principale,
apposta per non rischiare mai di romperlo:
- `zenlock_model_tracker.py` — importa `track` SOLO per funzioni di basso livello già
  testate (connessione WS, `get_bucket_prices`, `send_telegram_msg`, `season_type_for_card`,
  `eur_price_from_amounts`) — NON richiama `run_listener`/`handle_offer_update`/
  `evaluate_player_offer` (userebbero `MARGIN_TIERS`/`MIN_PRICE_EUR` del bot principale,
  pensati per un modello diverso: `MIN_PRICE_EUR=2.0€` avrebbe scartato metà degli snipe
  reali di ZenLock, che spesso compra sotto 1€). Loop WebSocket e valutazione sono un
  percorso indipendente.
- `zenlock_model_tracker.yml` (in `.github/workflows/`) — `workflow_dispatch` proprio,
  gruppo di concorrenza dedicato (`zenlock-model-tracker`), nessuna scrittura su
  `tracker.db` (stateless). Stessi secrets Telegram del tracker principale → stesso
  canale, notifiche taggate "🎯 Modello ZenLock" per distinguerle. Contiene anche un
  input `diagnostic_player_slug` (default vuoto) per un dump grezzo COMPLETO non filtrato
  degli annunci live di un giocatore specifico, utile per investigare casi dubbi (vedi
  bug #3 sotto) — riusa `track.diagnostic_dump_missing_offer`, già esistente.

**Modello (soglie derivate dai dati sopra):**
- Filtro 1 (prezzo×stagione): classic ≤4€ normale (fino a 30€ fascia "eccezione" con
  sconto richiesto più alto), in_season ≤8€ normale (fino a 70€ eccezione).
- Filtro 2 (sconto vs riferimento live): soglia 30% (40% in fascia eccezione).
- **Deciso esplicitamente di NON notificare mai "al buio"** (senza confronto di mercato
  disponibile) — pur essendo l'86% del comportamento reale di ZenLock, replicarlo alla
  lettera avrebbe inondato di falsi positivi (qualunque carta scarsa <3-4€ passerebbe).

### Bug trovati e risolti durante il testing in produzione (tutti con dati reali dell'utente)

1. **Rumore su carte "quasi gratis"** (primo test, 30s → 5 notifiche, proiettato 30+/200s):
   differenze di pochi centesimi su carte da niente producevano sconto% enorme senza vero
   mispricing. Fix: due soglie aggiuntive in AND — `ZENLOCK_MIN_DISCOUNT_EUR` (0.50€,
   differenza assoluta minima) e `ZENLOCK_MIN_REFERENCE_EUR` (1.50€, il prezzo di
   riferimento stesso deve valere almeno questo). Sceso a volumi gestibili (~1-2/200s).

2. **Caso Nayef Aguerd (falso positivo, sconto 82.2%)**: la mediana calcolata su TUTTI i
   comparabili di un bucket era gonfiata da annunci vecchi/stagnanti (carta infortunata da
   mesi, mercato già adeguato ma un vecchio annuncio non aggiornato falsava la statistica)
   — stesso trabocchetto già risolto nel tracker principale (caso Muric,
   `required_margin_fraction`/`MARGIN_TIERS`). **Fix**: `compute_live_discount` non usa più
   una mediana sull'intero bucket, ma il prezzo del PROSSIMO annuncio live più economico
   (stesso principio del "secondo prezzo" del tracker principale) — molto più robusto.

3. **Caso Jhegson Sebastian Mendez (BUG CRITICO, root cause trovata con DevTools)**:
   due annunci noti (0.59€, 1.92€) sparivano dai comparabili anche nel dump grezzo
   completo. Ipotesi iniziale (Early Access, o "annunci fantasma" mai risolti per Cancelo/
   Sangare/O'Reilly/Jeong in sessioni precedenti) **smentita dall'utente** ("insisti,
   chissà quanti falsi allarmi"). Confermato via DevTools (payload reale di `CardsQuery`,
   la query della pagina mercato): quei due annunci erano prezzati in **USD**
   (`settlementCurrencies: ["USD"]`, `usdCents: 67`/`220`, `eurCents: null`) —
   `eur_price_from_amounts` leggeva SOLO `eurCents`/`wei`, ignorando silenziosamente
   `usdCents`/`gbpCents`. Non era un limite dei dati Sorare, era un bug nostro di lettura.
   **Fix in `track.py`** (condiviso col tracker principale, quindi impatta anche quello):
   - Aggiunto `usdCents gbpCents` a TUTTE le query che leggono `MonetaryAmount` (8
     occorrenze: `SUBSCRIPTION_QUERY`, `LIVE_OFFERS_QUERY`, `get_recent_sale_history`,
     `fetch_player_recent_direct_buys`, `fetch_user_trades` x2, + 1 diagnostica).
   - Nuove `get_usd_eur_rate()`/`get_gbp_eur_rate()` (stesso pattern di `get_eth_rate`:
     fetch da API gratuita senza chiave — frankfurter.app — con fallback fisso se
     l'API non risponde; cache in-memory per esecuzione).
   - `eur_price_from_amounts` ora converte anche `usdCents`/`gbpCents` col tasso live.
   - Verificato con dati reali: 67 centesimi USD → 0.59€, 220 centesimi USD → 1.92€,
     coerente coi prezzi mostrati sul sito. Dopo il fix, il dump grezzo di Mendez mostra
     correttamente `usdCents`/`gbpCents` popolati (prima sempre `null` per mancanza del
     campo in query). **Bonus scoperto durante la verifica**: anche altre rarità dello
     stesso giocatore (rare, unique) erano in USD/GBP e completamente invisibili prima
     (una addirittura a $799) — il bug non era isolato alle carte limited.

### Validazione post-fix (dati reali)

Dopo tutti e 3 i fix: volume stabile e basso (1 notifica ogni ~200-235 carte valutate,
niente esplosioni di rumore). Caso concreto validato dall'utente con screenshot del
mercato reale: **Flabian Londoño**, classic, 1.61€ (nostro annuncio) vs comparabili 3.79€
e 5.00€ — sconto 57.7% confermato reale a occhio, pur essendo un caso limite (nessuno
storico vendite per quel giocatore). L'utente lo considera pronto per la schedulazione
in continuo (prossimo step, non ancora fatto).

### Cambio infrastruttura: da copia-incolla manuale a GitHub Desktop

Causa: due episodi di file scambiati per errore durante il copia-incolla manuale
dell'utente da GitHub web UI (contenuto di `track.py` finito dentro `zenlock_model_
tracker.py` e viceversa; poi contenuto di `.py` finito dentro `.yml`) — root cause quasi
certamente errore umano (più tab aperte, copia-incolla manuale), non un bug nostro.

**Nuovo setup (17/07, sessione 3)**: l'utente ha installato **GitHub Desktop** e clonato
il repo vero in `C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2` (collegato a Cowork
via `request_cowork_directory` — ora accessibile in lettura/scrittura come la cartella
`Desktop\tracker`). **Differenza strutturale importante**: in questo clone vero i workflow
vivono in `.github/workflows/*.yml` (percorso reale richiesto da GitHub Actions), non alla
radice come nella vecchia cartella `Desktop\tracker` — quella vecchia cartella era una
copia "appiattita" con una traduzione di percorso non sempre affidabile (probabile causa
degli scambi). **Da qui in avanti**: modifiche scritte direttamente nel clone vero
(percorsi corretti, es. `.github/workflows/zenlock_model_tracker.yml` non solo
`zenlock_model_tracker.yml`), l'utente fa commit+push da GitHub Desktop (due click, niente
più copia-incolla). La vecchia cartella `Desktop\tracker` resta collegata ma è da
considerare secondaria/potenzialmente disallineata — verificare sempre nel dubbio quale
delle due riflette lo stato vero del repo.

## Note operative per la prossima chat

- **Cartella di lavoro vera (usa questa)**: `C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2`
  — clone reale collegato a GitHub Desktop, workflow in `.github/workflows/`. L'utente fa
  commit+push da lì con due click. Se non è collegata a inizio sessione, richiedila subito
  (`request_cowork_directory`) invece di lavorare alla cieca sul repo remoto.
- **Cartella legacy**: `C:\Users\Andrea\Desktop\tracker` — vecchia cartella "appiattita"
  (yml alla radice invece che in `.github/workflows/`), usata nelle sessioni 1-2 e inizio
  sessione 3. Probabile causa degli scambi di contenuto file. Da non usare più come fonte
  di verità se la cartella git vera è disponibile — controllare comunque che i due non
  divergano se entrambe restano collegate.
- L'utente valida ogni fix con log di produzione reali e screenshot reali del mercato/
  Telegram — modalità di lavoro consolidata su 3 sessioni, continuare così. In questa
  sessione ha anche fatto DevTools manuale su richiesta mia (Network tab, payload
  `CardsQuery`) per trovare il bug valuta — se ricapita un caso dati-che-non-tornano,
  proporre subito questo approccio invece di ripetere ipotesi già scartate in passato.
- Modalità di lavoro sul backlog: un item alla volta, chiedendo esplicitamente da quale
  partire.
- Prima di implementare qualcosa che richiede dati non disponibili via API, segnalarlo
  esplicitamente e chiedere come procedere invece di implementare un'approssimazione
  silenziosa.
- **Prossimo step naturale**: schedulare `zenlock_model_tracker.yml` in continuo via
  cron-job.org (URL sopra, item 8). Poi, se l'utente conferma volume/qualità buoni su più
  giorni, valutare se allentare leggermente le soglie (attualmente piuttosto conservative)
  per catturare più occasioni reali senza reintrodurre rumore.
