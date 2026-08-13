# Riassunto evoluzione "Bot definitivo" — 25-26/07/2026

**AGGIORNATO — fine sessione, utente vicino al limite di utilizzo, passaggio a un altro
account/sessione Claude Code.** Repo `Sorare-tracker-2`, branch `main`. Tutto lo stato
descritto qui è già **committato e pushato** su GitHub (ultimo commit di questa sessione
`6fc87f11`, verificare `git log --oneline -10` per eventuali commit successivi di altri
workflow automatici) — si può ripartire con `git pull`, non c'è lavoro locale non salvato.

---

## Aggiornamento 13/08/2026 (notte, ~02:30 Roma) — il bot gira sul PC di casa, e cinque difetti trovati leggendo il codice

**In lingua da bar, prima di tutto il resto.**

1. Il bot ora può girare **sul PC di casa invece che su GitHub**, perché da casa
   Sorare risponde in metà tempo (82 ms contro 168) e nello sniping si vince per
   millisecondi. Si sceglie con l'input `runner`: `casa` o `github`.
2. La prima run sul PC era **verde e completamente inutile**: saltava *ogni*
   annuncio. Su Windows Python non ha il database dei fusi orari, e il bot lo usa
   per scrivere le scadenze della lista nera. Risolto installando `tzdata`.
3. Il bot usava **una sola chiave API su tre**. Ora le usa tutte: il tetto passa da
   200 a 600 richieste al minuto.
4. Quando prendeva un rifiuto per troppe richieste, **riprovava con la stessa
   chiave e dormiva fino a 8 secondi**. Ora passa subito a un'altra chiave.
5. La cache delle odds **si ricordava anche i fallimenti di rete**: un intoppo
   momentaneo metteva quel giocatore in lista nera per tutte le 5 ore di run.
6. Il numero di annunci valutati in parallelo **non è un collo di bottiglia** e va
   lasciato a 6: la prova è nella tabella più sotto.

### Dove gira, e come si sceglie

`runs-on` è deciso dall'input `runner` (default `casa`). Serve perché **il PC è
acceso solo quando l'utente lo usa**: un job mandato a `casa` con la macchina
spenta resta in coda, e `github` è la via di scampo.

Sul self-hosted `actions/setup-python` e `actions/setup-node` sono **saltati**
(`if: runner.environment == 'github-hosted'`): provano a installare scrivendo nel
registro e il servizio del runner gira come SERVIZIO DI RETE, che quel permesso non
ha. Si usano gli interpreti di macchina, installati **per tutti gli utenti**
(`C:\Program Files\Python311`, `C:\Program Files\nodejs`) — le versioni per il solo
utente stanno in AppData e quell'account non le può nemmeno leggere. Node serve per
firmare le transazioni (`bots/sorare-sign/decrypt_and_sign.js`) e **non era
installato**: `winget install OpenJS.NodeJS.LTS --scope machine`, da amministratore.
Dopo averlo installato i **servizi del runner vanno riavviati**, altrimenti hanno
ancora il vecchio PATH. Uno step si ferma subito con un messaggio chiaro se Node non
si vede, invece di far scoprire un `node: command not found` alla prima firma, tre
ore dentro il log.

Latenza misurata sulle due connessioni di casa (`misura_latenza_sorare.py`, si
rilancia una volta per rete): la **fibra vince su tutto** — mediana 60 ms contro 88,
p90 75 contro 97, massimo 89 contro 163.

### Il difetto che rendeva la run verde e vuota

Python non porta con sé il database dei fusi: su Linux lo legge da quello di
sistema, su Windows quel database non esiste e `ZoneInfo('Europe/Rome')` solleva
un'eccezione. Il bot lo usa per le scadenze della lista nera, e l'eccezione partiva
**dentro il thread che valuta un annuncio**: ogni evento finiva in "eccezione non
gestita durante la valutazione, la salto e continuo". Prima run: 6 annunci arrivati,
**6 saltati**, run `success`. Risolto aggiungendo `tzdata` al `pip install` (su
Linux è già soddisfatto, così non c'è un ramo in più da sbagliare). Run successiva:
zero eccezioni, zero errori di valutazione, zero 429.

**Nota**: `bots/cerbero/cerbero.py` usa anche lui `ZoneInfo` — stesso difetto il
giorno che finisce su un runner Windows.

### Le tre chiavi, e perché servono davvero (misurato sui log, non supposto)

I tetti delle chiavi sono **indipendenti e si sommano**: 200 richieste/minuto
ciascuna. Il bot ne usava una. Ora le usa tutte e tre, a giro tondo con lock (i
thread che valutano gli annunci chiedono la chiave in parallelo).

Il motivo sta nei log di quattro run diurne. Picchi di annunci valutati al minuto:
31, 36, 31 e **43**. Solo una ha preso 429, quella del 30/07 alle 19:35 di Roma:

| minuto (Roma) | annunci valutati | 429 |
|---|---|---|
| 19:33 | **42** | 0 |
| 19:34 | **18** | **39** |
| 19:35 | 43 | 0 |

La raffica ha bruciato il budget del minuto, e nel minuto dopo la capacità del bot è
**crollata a meno della metà** proprio dentro la finestra buona. Quel giorno girava
col solo cookie (tetto 60/minuto). **Con una chiave sarebbero già 200 e quella
raffica ci starebbe dentro**: le tre chiavi sono margine su una raffica peggiore, non
il rimedio a un problema che una chiave non risolve. Un 429 non costa una richiesta
— costa **30 secondi di modalità SAFE**, in cui ogni chiamata non critica rallenta
da 50 a 350 ms.

**Ancora da provare**: una run vera in fascia 17-22 contando i 429. Se sono zero, il
filone si chiude.

### Il ritentativo che dormiva sulla chiave sbagliata

Gli header si costruiscono una volta sola **fuori** dal ciclo dei ritentativi, quindi
ogni riprova ripartiva con la chiave già bocciata e poteva solo aspettare 2, poi 4,
poi 8 secondi. Ma un 429 dice che *quella* chiave ha esaurito il suo minuto, non che
siano esaurite tutte. Ora le chiavi di riserva si tengono in una **lista di quelle
non ancora provate** — non pescando dal giro tondo globale, la cui posizione è
condivisa fra i thread e non ha niente a che vedere con la singola chiamata: la prima
stesura pescava di lì e un test l'ha bocciata subito, perché poteva restituire la
stessa chiave appena rifiutata e lasciare la terza mai provata. Le prove con
un'altra chiave **non consumano il budget delle attese** (non dormono).

Provato su cinque scenari: con una sola chiave esaurita ora riesce **senza dormire**
(prima: 14 secondi e falliva comunque); con tutte esaurite, con una chiave sola e col
solo cookie il comportamento è **identico a prima**.

### La cache delle odds (vale solo in modalità aggressiva, di default spenta)

`dict` in RAM, slug → odds, muore con la run — **niente su disco**, verificato.
Aveva due difetti:

- **ricordava i fallimenti.** Se la query andava in eccezione (rete, timeout, 429 con
  tutte le chiavi esaurite) il `None` finiva in cache come se fosse una risposta del
  server; siccome il filtro chiamante tratta `None` come "scarta", un singolo intoppo
  di rete metteva quel giocatore in lista nera **per il resto della run**, in
  silenzio, anche se era un titolare quasi certo. Il codice non distingueva "il
  server dice che le odds non ci sono" da "non sono riuscito a chiedere". Ora il
  secondo caso non si ricorda; una risposta senza errori sì, anche quando le odds non
  ci sono (è un no legittimo).
- **non scadeva mai.** Le odds si muovono man mano che le formazioni si delineano, e
  un giocatore letto al 40% a inizio serata restava al 40% per cinque ore. Ora scade
  dopo **15 minuti** (deciso dall'utente), con sfoltimento delle voci scadute e un
  lock, perché i thread la usano in parallelo.

### Perché i thread di valutazione NON sono il collo di bottiglia

Domanda dell'utente: quanto si può alzare `EVENT_WORKER_THREADS`? Risposta: **niente,
lasciarlo a 6**, ed è ora un input del workflow solo per poterlo misurare senza
toccare il codice. I tetti in fila:

| | quanto lascia passare |
|---|---|
| 6 thread, se fossero liberi | ~30-40 controlli/secondo |
| **il freno interno da 50 ms** (`_graphql_throttle`) | **20/secondo** — e blocca *tutti* i thread, il sonno è dentro il lock |
| una APIKEY | 200 al **minuto** (~3,3/secondo) |
| la raffica peggiore misurata | ~43 annunci/minuto |

Per tenere occupato il freno da 50 ms bastano **3-4 thread**: a 6 è già saturo, e
portarli a 12 farebbe solo più gente in fila davanti alla stessa porta. Nella raffica
del 30/07 il bot valutava 0,7 annunci al secondo contro i ~6 che reggeva: **il tappo
era il tetto delle richieste, non i thread**.

### Altri due difetti trovati, uno chiuso e uno aperto

- **CHIUSO — `sorare-version` e `sorare-build` partivano vuoti.** Il workflow passa
  sempre le due variabili, e quando il secret non esiste le passa **vuote**;
  `os.environ.get('X', 'riserva')` vede una variabile che c'è e torna la stringa
  vuota, quindi il valore di riserva nel codice non è mai entrato in gioco. Sono
  proprio gli header che servono a farsi riconoscere come client Web legittimo.
  Risolto con `or`. **Succedeva identico anche su GitHub**, non è un difetto del PC
  di casa.
- **APERTO — `EVENT_TIMING_DIAGNOSTIC` è ancora acceso** (default `'si'` a
  `bot_definitivo.py`), da un'indagine sui tempi del 22/07. Il commento nel codice
  dice di rimuoverlo a indagine conclusa. Va deciso se l'indagine è chiusa.

### Manutenzione del workflow

Gli input erano **25, il tetto**. Tolti i tre log diagnostici
(`min_listed_cards_diagnostic`, `recent_avg_price_diagnostic_log`,
`league_blacklist_verbose_log`), che restano accendibili come variabili d'ambiente
nel job; aggiunti `runner` e `event_worker_threads`. Ora sono **23**.

Scoperta di passaggio: **`RECENT_AVG_PRICE_DIAGNOSTIC_LOG` era rimasto acceso** da
una vecchia verifica (il suo default nel codice è `'si'`) e sporcava i log di ogni
run da allora. Ora è scritto esplicitamente `no`.

**Da sapere**: il bot fa `commit` e `push` della lista nera su `main` **ogni 300
secondi durante la run**. Chi lavora sul repo mentre il bot gira si vede rifiutare il
push — successo due volte in questa sessione. Non è un difetto, ma va saputo.

## Aggiornamento 26/07 (notte, tardissimo) — nona ricalibrazione: rimosso il cutoff
## sotto 3€, granularità 8-14€, validazione run diagnostica 4/4

Sessione a popup (branch di lavoro `claude/bot-evolution-review-34b9a9`, poi mergiato su
`main`). Commit: verrà indicato dopo il merge (vedi in fondo a questa sezione).

1. **Rimosso il cutoff assoluto "mai AutoBuy sotto 3€"** (`AUTOBUY_MIN_PRICE_FOR_DIRECT_BUY`
   e il ramo `None` in `compute_price_based_thresholds()` eliminati): l'utente ha chiarito che
   non era una regola fissa, solo un margine minimo molto più alto. Casi ipotetici mirati
   hanno trovato un plateau ~58-60% tra 0.50€ e 1.00€, che scende fino al 38% già noto a 3€.
   `AUTOBUY_MIN_MARGIN_CURVE` estesa con `(0.50, 0.58), (1.00, 0.60), (2.00, 0.39)`.
2. **Granularità 10-16€ verificata**: 10€ e 12€ confermano l'interpolazione esistente (scarto
   ≤2pp, rumore). 13€ mostrava uno scarto reale di ~1.7pp (soglia vera ~24.5% contro il 22.8%
   calcolato) — aggiunto un punto esplicito `(13.00, 0.245)`. 16€ confermato invariato.
3. **Tema arrotondamento offerta chiuso, nessuna modifica**: verificato via sweep numerico
   dell'intero range di prezzo che lo scarto massimo tra offerta esatta e arrotondata resta
   0.05€ sopra 1€ (metà del passo 0.10€), nessun salto anomalo dal clamp sul ceiling. L'esempio
   portato dall'utente per illustrare il problema era ipotetico, non da un log reale — testato
   col codice vero dà già il risultato che l'utente considera corretto.
4. **Run diagnostica di verifica (30 min, cancellata a ~26 min)**, eseguita PRIMA che i fix 1-2
   sopra fossero deployati (girava ancora sul vecchio `main`): controllo media transazioni
   ancora zero scarti su 11 valutazioni (pattern confermato una quarta volta); AutoBuy ancora
   zero trigger, gap minimo osservato 10 punti percentuali (Rodrigo Zalazar, margine 20% contro
   soglia 30% a quel prezzo) — confermato per la terza volta che non è un problema di soglie,
   il mercato in quella finestra non produce occasioni abbastanza profittevoli. **4 offerte
   MakeOffer reali generate, tutte e 4 confermate esatte dall'utente** (Manuel Neuer 3.20€/27%,
   Rodrigo Zalazar 3.80€/23.5%, Phil Foden 3.90€/23.2%, David Soria 2.20€/29.4%) — il miglior
   risultato di validazione finora (4/4, contro l'8/12 e 9/10 delle sessioni precedenti).
5. **Nota per chi riprende**: il dettaglio caso-per-caso completo di questa sessione (inclusi
   tutti i punti ipotetici usati per calibrare il cutoff sub-3€ e i punti 13/16€) vive nella
   memoria locale di Claude Code (`bot_definitivo_margin_calibration.md`, sezione "Undicesima
   sessione"), non nel repo.

## Aggiornamento 26/27 (notte, tardissimo bis) — decima... nona ricalibrazione soglia
## AutoBuy da run diagnostica di 1h, prima validazione reale del fix sub-3€

Run diagnostica di 1h (cancellata a ~40 min), sul codice con il fix sub-3€ della sezione
precedente già live. Commit: `23b7b3280`.

1. **Prima validazione reale del fix sub-3€**: AutoBuy scattato per la prima volta in
   settimane di test — Bryan Mbeumo, 1.99€, margine 43.3% (soglia 39.2%), **confermato
   corretto dall'utente**. Prima del fix questo caso sarebbe stato impossibile per
   design (cutoff assoluto sotto 3€).
2. **14 match MakeOffer rivisti "in chiave AutoBuy"**: per ognuno chiesto a quale
   prezzo minimo (a parità di secondo prezzo reale) l'utente sarebbe passato ad
   AutoBuy — mappa direttamente la curva `AUTOBUY_MIN_MARGIN_CURVE` usando prezzi
   secondi reali come ancore. 10/14 match confermati esatti su decisione+importo;
   3 volevano uno sconto più profondo (Guzmán, Sargent, Gibbs-White, tutti sotto i
   2€ — apre un tema aperto sulla profondità sconto `OFFER_DISCOUNT_CURVE` in quella
   fascia, non ancora affrontato); 1 (Enzo Fernández, 4.10€/29.9%) voleva AutoBuy
   invece di MakeOffer.
3. **Nona ricalibrazione applicata**: punto 1€ abbassato da 60% a 52% (3 conferme),
   aggiunti punti espliciti 1.50€→48% e 1.70€→45% (un'interpolazione lineare 1-2€
   basata solo sui due estremi distorceva questi valori intermedi già confermati
   corretti). Fascia 3-5€: aggiunto 4.10€→30% (Enzo Fernández, caso reale) così che
   4.10-5€ resti piatto al 30% invece di scendere solo a 5€.
4. **Non ancora corretto, tenuto in memoria per un pattern futuro** (richiesta esplicita
   utente di tracciare anche i casi dubbi): 6.50€ ha dato risposte contrastanti tra due
   carte reali diverse (Van Dijk conferma 28% esistente, Lewandowski vuole 23%) —
   lasciato invariato. 15.50€ (Godts vuole 16% contro il 20% attuale) riapre una
   tensione già oscillata più volte in passato tra 16% e 20-22% — serve una terza
   conferma da un lato o dall'altro prima di deciderlo.
5. **Dettaglio completo** (inclusi tutti i 12 dati "in chiave AutoBuy" con i valori
   di curva prima/dopo) nella memoria locale, sezione "Dodicesima sessione".
6. **Validazione finale della sessione**: 5 scarti "vicini" (entro 0.8-1.6pp dalla
   soglia MakeOffer) rivisti — **tutti e 5 confermati corretti**, la Regola 1
   (`MAKEOFFER_MIN_MARGIN_CURVE`) regge bene ai suoi stessi bordi, nessuna modifica.
   Poi 6 casi ipotetici random sparsi su tutta la fascia 1-30€, ognuno prezzato
   esattamente alla soglia AutoBuy appena ricalibrata: **5/6 confermati esatti**
   (7€, 10€, 17€, 21€, 27€); solo 2.50€ ha dato un piccolo scarto (~3pp, soglia
   vera ~41-42% contro il 38.5% calcolato) — un solo punto, non ancora corretto,
   serve una seconda conferma prima di aggiungere un punto lì (creerebbe un
   piccolo rigonfiamento locale tra due punti già solidi a 2€ e 3€).

## Aggiornamento 26/07 (notte, tardi) — blacklist fix_urgente, annullamento forzato a
## chiusura, ottava ricalibrazione sconto 4-6€

Commit su `main` non ancora coperti dalle sezioni precedenti: `b300cc43d`, `d5a8b4f6b`,
`4e65022d2` (tutti verificati presenti nel codice attuale, working tree pulito).

1. **Nuova sezione lista nera `fix_urgente`** (`bots/bot_definitivo.py`,
   `sorare_lista_nera.txt`): separata dalla blacklist `giocatore` ordinaria, pensata per
   stop immediati su casi particolari (blocca sia acquisti che offerte). Scadenza assoluta
   ISO (come `thin_market`/`cooldown_acquisto`), non durata testuale rinnovabile. Aggiunto
   `matt-turner`, scadenza `2026-08-10T18:48:56Z` (15 giorni).
2. **Annullamento forzato di tutte le offerte pendenti alla chiusura del bot**
   (`_cancel_all_pending_offers_on_shutdown()`, chiamata nel `finally` di `main()`): il
   thread `_auto_cancel_offers_loop` annulla solo le offerte già oltre
   `OFFER_AUTO_CANCEL_SECONDS`, quindi un'offerta fatta a ridosso della fine di
   `LISTEN_SECONDS` restava pendente per sempre col processo morto (bug reale: **Nico
   Schlotterbeck**, run `30214671081`, scaduta solo dopo `OFFER_DURATION_DAYS`). Ora
   annulla tutto ciò che resta nel tracker, indipendentemente dall'età.
3. **Ottava ricalibrazione, fascia 4-6€ di `OFFER_DISCOUNT_CURVE`**: il calo da 25% a 17%
   partiva troppo presto. Corretto con casi reali/ipotetici mirati (Baumgartl 4.39€ reale,
   più Gallagher/Jackson/Fofana ipotetici): ora resta piatta al 27% fino a 4.50€, poi scende
   gradualmente a 17% per 6€. Un punto a 4.00€ esatto (Tielemans) fuori pattern, trattato
   come rumore isolato.
4. **Arrotondamento offerta più fine**: `_round_offer_to_nice_number` passa da step 0.50€ a
   0.10€ — l'utente ha chiarito che il numero tondo è solo preferibile, non vincolante; lo
   step da 0.50 schiacciava lo sconto voluto sotto i 2€ (caso Heuer Fernandes: calcolo vero
   1.36€ arrotondato a 1.50€, troppo generoso).

## Aggiornamento 26/07 (notte inoltrata) — controllo media transazioni, ricalibrazione AutoBuy

Continuazione della sessione precedente. Commit su `main`: `efd38ffea` (sesta
ricalibrazione sconto, vedi sezione sotto per dettaglio), `2e5f91319`, `1f99e7beb`.

1. **Nuovo controllo "prezzo vs media ultime transazioni"** (`check_recent_avg_price`,
   richiesta esplicita utente, caso reale André Ferreira — offerta accettata in linea
   con le 3 transazioni precedenti, ma voleva un tetto esplicito per i casi in cui NON
   lo sarebbe stata): scarta se il prezzo da pagare/offrire supera del
   `RECENT_AVG_PRICE_MAX_DEVIATION_PERCENT`% (default 15, input workflow) la media
   delle ultime fino-a-3 transazioni reali del giocatore. Riusa il fetch già esistente
   per ultimo/penultimo prezzo (`get_liquidity_and_last_price`), esteso con un terzo
   prezzo — zero query aggiuntive. Log diagnostico esplicito
   (`RECENT_AVG_PRICE_DIAGNOSTIC_LOG`, default 'si', **promemoria: rimettere 'no' dopo
   la verifica**) stampa il calcolo per OGNI valutazione, non solo sugli scarti.
   **Verificato con un run diagnostico di 33 casi reali**: zero scarti — ogni prezzo
   pagato/offerto era sempre SOTTO la media storica (deviazioni da -12% a -56%), mai
   sopra, quindi il controllo resta silenzioso in condizioni normali di mercato e
   interviene solo su anomalie come il caso Ferreira. Comportamento confermato corretto.
2. **Indagine "l'AutoBuy non scatta mai, si sarà rotto qualcosa?"** — non era rotto:
   verificato che la riga di log `AUTOBUY: ... LO AVREI ACQUISTATO` (stampata
   incondizionatamente all'inizio del branch, prima di ogni altro controllo) non
   compare MAI in nessuno dei run di oggi — il branch semplicemente non viene mai
   raggiunto perché nessun caso reale ha superato la soglia margine richiesta (molto
   più alta di quella MakeOffer, 22-38% contro 7-13%, per design). Verificato anche il
   calcolo della soglia stessa contro i log — combacia esattamente, nessun bug
   aritmetico.
3. **Settima ricalibrazione AutoBuy**, dato che non c'erano casi reali disponibili:
   sessione a popup con 9 punti (reali con margine ipotizzato + ipotetici puri, stesso
   metodo "vero minimo variabile, secondo prezzo fermo" usato più volte). Il plateau
   8-14€ (fisso al 22%, dalla sessione del 25/07) non regge più: **James Pantemis e
   Guillaume Restes, indipendentemente, entrambi a 8.00€, hanno dato ~27.3%** (non
   22%). Altri 4 punti (3€, 15€, 17.5€, 21€) confermano invece la curva quasi esatta
   (scarto ≤1 punto percentuale) — **corretto solo il punto a 8€ (22%→27%)**,
   l'interpolazione sistema da sola anche 7€ (→27.7%, vicino al 29.6% voluto) e 11€
   (→24.5%, quasi esatto al 24.1% voluto). Un punto fuori pattern (McGlynn, 22.50€ →
   voluto 19.35% contro il 15.9% attuale, mentre il vicino 21€ combaciava già bene)
   trattato come rumore isolato, non inseguito.
4. **Lanciato run reale 10 minuti** (`autobuy_live_mode=si`, `makeoffer_live_mode=si`)
   con la soglia AutoBuy appena ricalibrata — esito da verificare alla prossima
   sessione (controllare se scatta un AutoBuy vero con margine tra 22% e 27% a ~8€,
   prima impossibile con la vecchia soglia).

**Nota per chi riprende**: `RECENT_AVG_PRICE_DIAGNOSTIC_LOG` è ancora 'si' di default
nel workflow — genera una riga di log per OGNI valutazione, utile solo durante la
verifica. Se il log risulta troppo rumoroso, cambiare il default a 'no' in
`.github/workflows/bot_definitivo.yml` (input `recent_avg_price_diagnostic_log`).

## Aggiornamento 26/07 (notte) — curva sconto continua, auto-annullamento offerte

Sessione a popup (`AskUserQuestion`, un caso alla volta, niente tabelle su richiesta
esplicita utente) su ~13 casi reali/scarti/ipotetici, poi 2 run reali di verifica.
Commit su `main`: `2c17deaca`, `a978709b0`, `426e4efda`, `efd38ffea` (oltre a
`f2ffc3be0`, vedi sezione sopra).

1. **Sconto MakeOffer da tabella a gradini a curva continua** (`OFFER_DISCOUNT_CURVE`,
   sostituisce `OFFER_DISCOUNT_BY_PRICE`/`_tiered_lookup`, rimossa). Stesso problema di
   "gradiente dentro la fascia" già risolto per le soglie di margine (Regole 1/2), qui
   però esteso a quasi tutta la vecchia fascia 4-7€, non solo ai bordi — confermato con
   coppie reali+ipotetiche ai confini di 4€ e 7€ e a metà fascia (Joseph Paintsil
   4.80€, Ismael Saibari 6.00€, entrambi reali, volevano ~17% non 24%). Confine dei
   15€ inizialmente inconcludente/rumoroso su dati ipotetici.
2. **Sesta ricalibrazione, dopo il primo run reale in live mode con la curva sopra**:
   fascia 7-15€ confermata corretta (Germán Berterame, 12.88€/margine 8.4%, offerta
   11.00€ "andava bene"). Fascia ≥15€ invece alzata: Berke Özer (16.00€/margine 6.9%,
   offerta 14.00€) è stata **accettata dal venditore** — segnale che si poteva scontare
   di più. Aggiunto un punto a 16€ (15.6%, prima 12.5%) che dà 13.50€ — i "50 centesimi
   in meno" richiesti esplicitamente dall'utente. Fascia 7-15€ non toccata.
3. **Nuovo meccanismo: auto-annullamento offerte MakeOffer pendenti.** Il venditore
   spesso non risponde, e finché l'offerta resta viva il budget corrispondente resta
   bloccato. Ogni offerta reale inviata (ramo MakeOffer normale + bid periodico) viene
   ora registrata con un **timer indipendente e proprio** (non un annullamento "a
   ondata" di tutte insieme); un thread dedicato controlla ogni 30s e annulla
   (`CancelOfferMutation`, serve solo `blockchainId`, NON richiede firma/approvazione
   wallet — confermato dal vivo dall'utente annullando un'offerta a mano e catturando
   la request) le singole offerte più vecchie di `OFFER_AUTO_CANCEL_SECONDS`. Per
   ottenere il `blockchainId` è stato aggiunto quel campo alla risposta di
   `CreateDirectOfferMutation` e propagato lungo tutta la catena (`create_direct_offer`
   → `execute_live_offer` → `_run_makeoffer_merged` → i due call site che inviano
   offerte reali). **Verificato dal vivo**: offerta Germán Berterame annullata
   correttamente dopo 315s. Timeout iniziale 5 minuti, **abbassato a 4 minuti**
   (`OFFER_AUTO_CANCEL_SECONDS=240`) su richiesta esplicita dopo la verifica.
4. **Trovato ma NON ANCORA implementato**: la regola "mai AutoBuy sotto i 3€" (Regola 2,
   verificata più volte in sessioni precedenti fino al 44% di margine) sembra troppo
   rigida secondo l'utente — Salomón Rondón (2.20€, margine 43.4%) → "farei autobuy",
   mentre Robinson (stesso prezzo 2.20€, margine 30.2%, caso già verificato in
   passato) → mai autobuy. Quindi non è un taglio netto a 3€, ma il floor di margine
   scende ulteriormente anche sotto i 3€. Attenzione pero': Vera (1.50€, margine 44.4%,
   **più alto** di Rondón) era stata rifiutata — il floor sembra dipendere ancora dal
   prezzo dentro la fascia <3€, non essere un singolo taglio. **Serve raccogliere altri
   punti prima di toccare `AUTOBUY_MIN_PRICE_FOR_DIRECT_BUY`/`AUTOBUY_MIN_MARGIN_CURVE`.**
5. **Segnale debole, non ancora modellato**: 2 punti (Stefan Cleveland 3.20€/margine
   9.7%, appena sopra soglia minima; ipotetico 20€/margine 7.0%, appena sopra soglia)
   suggeriscono che quando il margine è "al limite" della soglia minima per quel
   prezzo, l'utente vuole uno sconto più profondo (o scarta) — cosa che la Regola 3
   oggi esplicitamente NON fa (dipende solo dal prezzo, non dal margine). Solo 2 punti,
   non abbastanza per agire.
6. **Cosmetico**: rinominate le ultime etichette residue "Bot Supremo" rimaste nel
   commit periodico della lista nera durante la run (identità git, messaggio commit).

## Aggiornamento 26/07 (sera) — blacklist transitoria in_season + pulizia repo

Sessione separata (branch di lavoro `claude/missing-recent-chats-687m14`, poi riportata
manualmente su `main` visto il disallineamento — vedi nota sotto). Commit su `main`:
`ce40c28fb`, `f2ffc3be0`, `cc5df273d`.

1. **Nuova sezione lista nera `campionato_inseason_temp`** (`sorare_lista_nera.txt`,
   `bots/bot_definitivo.py`): blacklist transitoria (default 15gg) che ignora **solo le
   carte in_season** di un campionato, lasciando le classic valutate normalmente —
   diversa dalla blacklist totale `campionato` che ignora tutto. Usata subito per 4
   campionati con carte in_season appena uscite e ancora troppo instabili di prezzo:
   portoghese (`primeira-liga-pt`), austriaco (`austrian-bundesliga`), scozzese
   (`premiership-gb-sct`), croato (`1-hnl`) — rimossi dalla blacklist totale
   `campionato` e spostati qui.
2. **Questi 4 campionati aggiunti a `EXCLUDED_LEAGUE_SLUGS`**, lo stesso set usato finora
   solo per MLS/K League: per questi campionati il confronto di mercato separa sempre
   in_season e classic (mai mescolati), **in entrambe le direzioni** — confermato
   esplicitamente dall'utente che la separazione classic-vs-classic per MLS/K League era
   voluta e va replicata simmetricamente anche quando si valuta una carta classic (non
   solo quando si valuta una carta in_season, unico caso già coperto prima). Aggiunta
   `get_classic_prices()`, simmetrica a `get_in_season_prices()` già esistente.
3. **Manager `basilbot`** aggiunto alla blacklist manager (365gg) — non c'era.
4. **Pulizia repo (richiesta esplicita utente, "sto cominciando a fare confusione" tra
   main e altri branch)**: `bot_supremo.py`/`bot_supremo_aste.py` (versione primitiva,
   superata da `bot_definitivo.py` da fine luglio) e i relativi workflow/file
   (`.github/workflows/bot_supremo.yml`, `bot_supremo_aste.yml`,
   `bot_supremo_thin_market_cache.json`, `docs/botsupremo.md`) **rimossi da `main`** e
   archiviati sul branch **`archive/bot-supremo`** (pushato su GitHub, storico intatto
   fino al punto della rimozione). Rinominate anche le etichette residue "Bot Supremo"
   rimaste in `bot_definitivo.yml` (step name, messaggio/identità git del commit
   automatico della lista nera) — puramente cosmetico. **Da ora in avanti l'unico bot e
   l'unica architettura operativa vive in `main`**, niente più lavoro sparso su branch
   secondari per `bot_definitivo`.
5. **Nota per chi riprende da qui**: durante questa sessione `bot_definitivo.py` era
   stato modificato per errore su un branch secondario ormai disallineato da `main` (che
   nel frattempo aveva ricevuto altri commit, es. le curve continue di soglia/sconto del
   26/07 pomeriggio) — le modifiche sono state **riportate a mano** sulla versione
   corrente di `main`, non mergiate alla cieca. Se in futuro si lavora di nuovo su un
   branch secondario per `bot_definitivo`, verificare sempre lo scarto con `main` prima
   di riportare le modifiche.

## PROSSIMA AZIONE IMMEDIATA (in ordine)

1. **Rifare il run diagnostico mirato a generare molti AutoBuy** (il tentativo di questa
   sessione ha dato zero match, vedi sezione 1 punto 9 e sezione 6 punto 1 per il comando
   esatto) — serve per misurare i **tempi di risposta del ramo AutoBuy** (quello critico
   per vincere la corsa contro altri bot, a differenza di MakeOffer che non è time-critical
   secondo l'utente).
2. **Continuare ad affinare le soglie del bot** con altri casi reali/ipotetici man mano che
   arrivano dai run diagnostici — in particolare il "gradiente dentro la fascia" (sezione 4)
   e la soglia AutoBuy 15-30€ abbassata a 16% su un solo punto dato (sezione 6, punti 2-3).

Handoff dettagliato su tutto il lavoro fatto in questa sessione (partita in worktree
`agent-a6fafee9d6b2c4df4`, poi mergiata su `main`) su `bots/bot_definitivo.py` — il bot
REALMENTE in uso in produzione (ex `bot_supremo_test.py`, workflow ex "Bot Supremo test
no play"). Il dettaglio caso-per-caso completo della sessione di calibrazione (~55 casi
totali) vive nella memoria locale di Claude Code su questa macchina (file
`bot_definitivo_margin_calibration.md`), **non nel repo** — se si continua da un'altra
macchina/account, quella memoria non è accessibile: questo documento riassume le
conclusioni in modo il più possibile autosufficiente.

## 1. Timeline completa

1. **Rename** (commit `ce95fff8`): `bot_supremo_test.py` → `bot_definitivo.py`,
   `.github/workflows/bot_supremo_test.yml` → `bot_definitivo.yml`, nome workflow "Bot
   Supremo test no play" → "Bot definitivo". Il nome vecchio suggeriva un bot di test, ma
   è quello realmente in produzione.
2. **Primo tentativo di soglie dinamiche** (commit `10d5ea43` + `812f0a9c`, poi
   **abbandonato**): soglie di margine calcolate come percentili della storia recente dei
   margini osservati (persistita in JSON). Rispondeva alla domanda sbagliata — vedi
   sezione 2.
3. **Prima sessione di calibrazione manuale** (~45 casi, 25-26/07): casi reali e ipotetici
   discussi uno alla volta con l'utente (`AskUserQuestion`) per capire la sua vera logica
   di trading. Vedi sezione 3 per le regole emerse.
4. **Prima implementazione basata sul prezzo** (commit `8737a9a2`, 26/07): sostituisce il
   sistema a percentili con le tre regole di sezione 3.
5. **Primo run diagnostico completo** (30 min, ID `30171957853`, poi `30174631418` dopo un
   riavvio): 12 match reali MakeOffer osservati, 8 confermati esattamente, 4 con richiesta
   di sconto leggermente più profondo — **nessun disaccordo su decisione o routing
   AutoBuy/MakeOffer**.
6. **Seconda sessione di calibrazione** (10 casi ipotetici mirati + revisione degli 8
   scarti/12 match del run precedente): confermato un pattern reale di "gradiente" (stesso
   margine, prezzo diverso → decisione diversa) e isolato quali fasce di sconto erano
   sistematicamente troppo miti. Vedi sezione 4.
7. **Ricalibrazione soglie** (commit `7da02504`, 26/07): sconto `<4€` 22.5%→27%, sconto
   `4-7€` 16.5%→19%, soglia AutoBuy `15-30€` 18%→16%. Aggiunto anche l'input workflow
   `price_based_thresholds_enabled` per poter disattivare le soglie per-prezzo via
   `workflow_dispatch` senza toccare codice (serviva per il punto 9).
8. **Pulizia input diagnostici morti** (commit `6fc87f11`): rimossi `autobuy_diagnostic` e
   `min_non_trigger_log` dal workflow e dal codice (richiesta esplicita utente, non più
   usati) — incluso dead code risultante (variabile `categoria` orfana).
9. **Tentativo di test timing AutoBuy** (run `30176259660`, 5 min, soglie statiche forzate
   all'1% via `price_based_thresholds_enabled=no`): **zero match prodotti** — non un bug,
   il mercato era genuinamente tranquillo in quella finestra E i pochi candidati che
   superavano la soglia margine sono stati scartati da altri controlli di sicurezza
   (mercato sottile, prezzo fuori range, controllo "prezzo ≥ ultima/penultima
   transazione"). **Nessun dato di timing AutoBuy raccolto — vedi sezione 6, punto 1.**

## 2. Perché il sistema a percentili storici è stato abbandonato

Rispondeva alla domanda sbagliata: "quanto è raro questo margine rispetto al mercato
recente" invece di quella che conta davvero: "a questo margine, su una carta di questo
prezzo, l'utente l'avrebbe comprata/offerta?".

**Metodologia della sessione di calibrazione (lezioni utili per continuare)**:
- **Un caso alla volta**, con `AskUserQuestion`, sia da run reali (log GitHub Actions) sia
  ipotetici — l'utente vuole **nomi di giocatori reali** anche per i casi inventati.
- **Dare sempre prezzi assoluti concreti**, mai solo percentuali — verificato
  esplicitamente: a una domanda con solo il margine %, l'utente non riesce a valutare
  senza i prezzi in euro.
- **Evitare domande guidate con una risposta plausibile di default** ("sei d'accordo con
  l'autobuy?"): una risposta morbida tipo "ci sta" si è rivelata inaffidabile — casi
  ri-testati con domande neutre ("cosa avresti fatto?") hanno dato risposte opposte (vedi
  il ribaltamento Reichert/Diaw/Vera in sezione 3.2).
- **Convenzione**: "offro X euro" significa sempre "fino a X euro al massimo".
- **Principio guida esplicito**: il bot non deve trovare un match per forza — zero match in
  un'ora è normale. Non allentare le soglie solo per produrre più match nei test.
- **Spiegazione dell'utente per la variabilità caso-per-caso** (sezione 4): "conosco tutti
  i giocatori, so chi è più facile da rivendere e chi no" — una parte della variabilità
  osservata (stesso prezzo/margine, decisione diversa) NON è rumore, riflette una
  conoscenza personale del giocatore che il bot non può replicare. `count_7d` (transazioni
  recenti, già calcolato da `get_liquidity_and_last_price`) è il proxy più vicino
  disponibile, ma è imperfetto — **non aspettarsi mai un fit perfetto al 100%**.

## 3. Le tre regole (prima versione, poi rifinita in sezione 4)

### 3.1 Margine minimo per agire (MakeOffer o AutoBuy), dipende dal PREZZO

| Prezzo | Margine minimo |
|---|---|
| < 4€ | ~13% |
| ≥ 4€ | ~7% |

Sotto ~4€ il guadagno assoluto in euro è troppo piccolo per valere il rischio/tempo di
negoziare. Casi chiave: Bombino (2.81€/6.5%→scarto), Ferreira (1.50€/10.4%→scarto) contro
Trossard (3.49€/16.5%→offerta OK); Johnson (5.52€/7.3%→OK), Gill (6.00€/7.7%→OK) contro
Pickford (10.50€/4.5%→scarto).

### 3.2 Split AutoBuy (prezzo pieno) vs MakeOffer (offerta ribassata)

**Non è una soglia di margine globale** — dipende da PREZZO e MARGINE insieme:

| Prezzo | Margine minimo per AutoBuy diretto |
|---|---|
| < 3€ | **mai** (sempre MakeOffer, testato fino al 44% di margine) |
| 3-5€ | ~35% |
| 5-8€ | ~27% |
| 8-15€ | ~22% |
| ≥ 15€ | ~16% (aggiornato da 18%, sezione 4) |

Punto importante corretto durante la prima sessione: risposte iniziali (Jan Reichert, Mory
Diaw) sembravano confermare l'AutoBuy anche su carte economiche a margine altissimo, ma
erano risposte "morbide" a domande guidate. Ri-testate con domande neutre, l'utente ha
ribaltato: sotto ~3€ **non vuole mai** il prezzo pieno. Sopra i 3€ il margine richiesto
scende al crescere del prezzo — verificato su ~15 casi (Vera, Reichert, Diaw, Robinson,
Rashford, Ansu Fati, Endrick, Mainoo, Zaire-Emery, Ronaldo Jr, Pedri, Nico Williams, Gavi,
Haaland, Bruno Guimarães, Ødegaard), zero contraddizioni con questa tabella nella seconda
sessione di verifica.

### 3.3 Sconto dell'offerta MakeOffer

Conta il **prezzo della carta**, non il margine del caso (al contrario della prima
versione a percentili, che scalava con il margine).

| Prezzo | Sconto offerta (AGGIORNATO, sezione 4) |
|---|---|
| < 4€ | ~27% (era 22.5%) |
| 4-7€ | ~19% (era 16.5%) |
| 7-15€ | ~11.5% (invariato) |
| ≥ 15€ | ~10% (invariato) |

Eccezione: giocatori molto liquidi (`count_7d >= LIQUID_PLAYER_TRANSACTIONS_7D=15`) usano
sempre lo sconto mite 10%, a prescindere dal prezzo — caso reale: Bradley Barcola (ma
attenzione, lo stesso giocatore in un run successivo NON ha ricevuto lo sconto liquido,
segno che `count_7d` varia nel tempo/mercato, non è una proprietà fissa del giocatore).

## 4. Seconda sessione di calibrazione (26/07) — cosa è cambiato dalla prima versione

Rivisti tutti i 12 match reali del primo run diagnostico completo + 10 casi ipotetici
mirati a colmare le lacune. Risultati:

**Sconto offerta troppo mite in due fasce, ora corretto**:
- Fascia `<4€`: split quasi 50/50 tra "va bene com'è" (Guendouzi, esatto a 22.5%) e "voglio
  più profondo" (Calum Ward confermato 2 volte a ~30%, Stanišić ~35%, Camavinga ~29-34%) —
  alzato a 27% come compromesso.
- Fascia `4-7€`: split ESATTAMENTE 4 conferme/4 richieste più profonde (confermato a 16.5%:
  Tchouaméni, Rafael Leão, Ionuț Radu, Dani Olmo — voluto più profondo: Gloukh, Mauro
  Junior, Saibari, Rice bis) — alzato a 19%.
- Fascia `15-30€`: soglia AutoBuy abbassata 18%→16% sulla base di UN solo punto (Saka bis,
  "autobuy ma al pelo" a 16%) — **da confermare con altri casi prima di fidarsene
  pienamente.**

**Trovato un vero problema di "gradiente" nel floor del margine** (sezione 3.1): a
**parità di margine**, la decisione cambia in base al prezzo esatto DENTRO la stessa
fascia, non solo tra le due fasce:
- Cherki (11.60€, 6.8%, soglia 7%) → agirebbe comunque; Cucurella (6.00€, STESSO 6.8%) →
  scarto confermato.
- Talisca (3.00€, 11.8%, soglia 13%) → agirebbe; Pedro Neto (1.50€, STESSO 11.8%) → scarto.
- Camavinga (3.80€, 12.2%) → agirebbe; Ansu Fati (1.80€, STESSO 12.2%) → scarto.

Tre coppie diverse, stesso pattern: **il floor probabilmente decresce in modo continuo
dentro ogni fascia, non a gradini netti come modellato oggi.** L'utente ha spiegato che
parte di questo è dovuto alla sua conoscenza personale di quali giocatori sono più facili
da rivendere (vedi sezione 2) — quindi non aspettarsi di eliminare tutta la varianza anche
con un modello più fine. **Non ancora implementato** — è un cambiamento più strutturale
(da due gradini fissi a una curva continua) che richiede design, non solo tarare due
numeri. Vedi sezione 6, punto 2.

## 5. Implementazione tecnica

**File modificati**: `bots/bot_definitivo.py`, `.github/workflows/bot_definitivo.yml`.

Funzioni: `compute_price_based_thresholds(price_eur)` → `(makeoffer_min_margin,
autobuy_min_margin_o_None)`; `compute_price_based_offer_discount(price_eur,
count_7d=None)`. Sostituiscono `compute_dynamic_margin_thresholds()` /
`compute_dynamic_offer_discount()` e tutta la macchina di persistenza storica (rimossa
interamente: niente più file `bot_definitivo_margin_history.json`, niente più percentili).

**Interruttore di sicurezza**: `PRICE_BASED_THRESHOLDS_ENABLED` (env, default `'si'`,
esposto anche come input `price_based_thresholds_enabled` nel workflow) — se `'no'`, torna
al comportamento statico originale (3 costanti fisse `MAKEOFFER_MARGIN_FRACTION`/
`MAKEOFFER_MAX_MARGIN_FRACTION`/`AUTOBUY_MARGIN_FRACTION` prese dagli input percentuali del
workflow, sconto sempre `OFFER_DISCOUNT_FRACTION`) senza toccare il codice. **Usato in
questa sessione per forzare artificialmente moltissimi AutoBuy in un test diagnostico**
(impostando anche `autobuy_margin_percent=1`).

**Input workflow rimossi** (commit `6fc87f11`, richiesta esplicita utente, non più usati):
`autobuy_diagnostic`, `min_non_trigger_log` (e le costanti/log associati nel codice Python).

**Validazione fatta finora**:
- `python -m py_compile` OK dopo ogni modifica.
- Spot-check di 12 casi del dataset (Vera 44% niente autobuy sotto 3€, Ansu Fati 40%
  autobuy a 3€, Haaland 28.6% autobuy a 25€, ecc.) — tutti coerenti.
- 2 run diagnostici completi da 30 minuti (`autobuy_live_mode=no`, `makeoffer_live_mode=no`)
  con revisione umana caso-per-caso di TUTTI i match e diversi scarti — vedi sezioni 3-4.
- 1 tentativo di run mirato a generare molti AutoBuy per analisi timing — **zero match**,
  vedi sezione 1 punto 9 e sezione 6 punto 1.
- **MAI testato in modalità live reale** (`autobuy_live_mode=si`/`makeoffer_live_mode=si`)
  con la nuova logica — solo diagnostica finora.

## 6. Prossimi passi (in ordine di priorità)

1. **Analisi timing del ramo AutoBuy — NON ancora fatta.** Il tentativo di questa sessione
   (run `30176259660`, 5 min, soglie forzate all'1%) ha prodotto zero match per pura
   sfortuna di mercato + controllo di sicurezza "ultima/penultima transazione" che ha
   scartato gli unici 2 candidati marginali (Jeremy Doku, Mark Delgado). Riprovare con:
   una finestra più lunga (10-15 min invece di 5), o accettare che serva più di un
   tentativo dato quanto raramente scatta un vero AutoBuy anche con soglie forzate basse.
   Comando di riferimento:
   ```
   gh workflow run "bot_definitivo.yml" --ref main -f autobuy_live_mode=no -f makeoffer_live_mode=no \
     -f price_based_thresholds_enabled=no -f autobuy_margin_percent=1 -f makeoffer_margin_percent=1 \
     -f makeoffer_max_margin_percent=1 -f listen_seconds=600 -f target_matches=100
   ```
   I blocchi di log `[timing]` (formato `scan_prezzi=...s, liquidita+ultimo_prezzo=...s,
   dettagli_carta=...s, prepare_offer=...s, esecuzione_finale=...s -- TOTALE=...s`) danno i
   dati; per il ramo AutoBuy guardare anche `prepare_accept_offer`/firma speculativa (vedi
   `_speculative_sign_after_prepare` in `bot_definitivo.py`) che nel ramo MakeOffer non
   esiste. **Nota per i tempi di risposta**: l'utente ha detto esplicitamente che il timing
   MakeOffer non è critico, solo quello AutoBuy lo è (la finestra per vincere la corsa
   contro altri bot è quella che conta).
2. **Gradiente del floor margine dentro le fasce** (sezione 4): tre coppie di casi
   (Cherki/Cucurella, Talisca/Pedro Neto, Camavinga/Ansu Fati) mostrano che a parità di
   margine il floor dovrebbe dipendere anche dalla posizione dentro la fascia, non solo
   dalla fascia stessa. Prima di implementare una curva continua, raccogliere altre coppie
   simili per confermare la forma — è un cambiamento di design, non solo un numero da
   tarare, discuterne con l'utente prima di toccare `compute_price_based_thresholds()`.
3. **Soglia AutoBuy 15-30€ abbassata a 16%** sulla base di un solo punto dato (Saka bis) —
   raccogliere altre conferme prima di fidarsene per l'uso live.
4. **Validare in modalità live reale** (`autobuy_live_mode=si`/`makeoffer_live_mode=si`)
   solo dopo aver raccolto altri casi reali e sentendosi sicuri della logica — questa
   sessione ha lavorato SOLO in diagnostica.
5. La memoria di calibrazione dettagliata (`bot_definitivo_margin_calibration.md`, ~55
   casi con ragionamento completo dell'utente) resta locale a questa macchina/account
   Claude Code — se si continua da un'altra macchina, questo documento è il riferimento,
   ma il dettaglio caso-per-caso va eventualmente ricostruito o richiesto di nuovo
   all'utente.

## 7. File chiave per orientarsi rapidamente

- `bots/bot_definitivo.py` — il bot, funzioni `compute_price_based_thresholds` /
  `compute_price_based_offer_discount` (~riga 587-680), routing in `evaluate_event`
  (~riga 2900-3060), blocchi `[timing]` in `_handle_autobuy_branch`/`_handle_makeoffer_branch`.
- `.github/workflows/bot_definitivo.yml` — input `price_based_thresholds_enabled` per
  disattivare le soglie per-prezzo, utile per test diagnostici mirati.
- Comando tipo per un run diagnostico normale (nessun rischio, nessun acquisto/offerta reale):
  ```
  gh workflow run "bot_definitivo.yml" --ref main -f autobuy_live_mode=no -f makeoffer_live_mode=no \
    -f target_matches=100 -f listen_seconds=1800
  ```

## 8. Aggiornamento 27/07 — ricalibrazione soglie AutoBuy + estensione fascia 30-40€

Sessione dedicata a due obiettivi: (a) far scattare di più l'AutoBuy, (b) calibrare per la
prima volta la fascia 30-40€ (finora si lavorava solo in 1-30€).

**AutoBuy — analisi ultimi 2 log reali (run 30271575621 / 30268557857):** zero AutoBuy in
entrambe. Motivo STRUTTURALE, non soglia sbagliata: tutti i margini alti erano su carte <3€
(fascia che l'utente continua a preferire in offerta, riconfermato su 5 casi reali fino al 32%),
e l'unico caso ≥5€ ad alto margine era trigger-su-minimo-non-allineato (MakeOffer-only per regola).

**Regola "carte economiche mai AutoBuy": non più assoluta** (decisione esplicita utente). In
pratica però sotto ~3€ l'utente sceglie ancora quasi sempre l'offerta.

**Ricalibrazione curva AutoBuy (`AUTOBUY_MIN_MARGIN_CURVE`)** su ~40 casi (popup interattivi,
schema min/2°). I punti 5-8€ validano quasi esattamente la curva esistente. Modifiche:
- 20€: 16.5% → **17.5%** (20€/16% → l'utente offre, non compra).
- fascia **25-40€ ricalibrata** (prima estrapolata e mai validata, risultava troppo bassa):
  floor a "gobba" — 25€→19%, 30€→19.5%, 35€→18.5%, 37€→16.5%, 40€→15.5%. Motivo plausibile:
  su carte da 25-30€ un AutoBuy sbagliato immobilizza molto capitale → serve margine più alto;
  verso 40€ (carte rare e chiaramente sottoprezzo) l'utente assicura l'acquisto.
- Il ginocchio 10-13€ è risultato contraddittorio (10€ vuole ~28%, 12€ riconfermato 3× a ~20%):
  rumore per-giocatore non modellabile, **lasciato invariato**.

**Prezzo max carta:** alzato a 40€ e poi **riportato a 30€** su richiesta utente (default resta 30,
lo alza a mano quando vuole; le curve però sono calibrate fino a 40€).

**MakeOffer floor 30-40€ (`MAKEOFFER_MIN_MARGIN_CURVE`)** — regola ~2€ di utile assoluto:
35€→5.7%, 40€→5.0% (30€ lasciato a 6.5%).

**Sconto offerta (`OFFER_DISCOUNT_CURVE`)** — prima la curva finiva a 16€ → tutto 16-40€ usava il
15.6% fisso, troppo profondo per carte care. L'utente applica uno "shave" assoluto ~2-3€ sotto il
minimo: nuovi anchor 30€→7%, 35€→6%, 40€→6%. Il segmento 16→30€ ora interpola a ~11.9% a 22€ /
~8.9% a 27€, coerente coi dati storici in memoria (fix bonus del 16-30€, prima troppo profondo).

Dettaglio caso-per-caso completo in `bot_definitivo_margin_calibration.md` (memoria locale).
Modifiche NON ancora validate su run reale — prossimo passo: run diagnostica per verificare i
nuovi routing nella fascia alta.
