# REGOLA SUPREMA — RISPARMIO TOKEN (sovrasta tutte le altre)

La priorita' assoluta e' il risparmio di token. Prima di qualunque operazione,
mi chiedo se esiste un modo alternativo di ottenere lo stesso risultato
spendendo meno token: se esiste, uso quello. Non eseguo un'operazione costosa
(run, query, lettura di file grossi, fetch) quando una via piu' economica da'
la stessa risposta. Questa regola viene prima di ogni altra in questo file.

# I BACKTEST SONO IL MODELLO CONTRO SE STESSO (09/08/2026)

Regola nuova, dettata dall'utente. Sovrasta il modo in cui sono stati
impostati TUTTI i backtest fino a oggi.

Fino al 09/08 si misurava il nostro modello contro le scelte di altri
manager Sorare (24 manager, 6 GW, dati_globali/manager_*.json). Quella
strada ha prodotto archivi misti, competizioni mescolate, criteri di
schieramento ignoti (di 23 manager su 24 non sappiamo con che regola
scegliessero) e verdetti che l'utente non ha mai potuto controllare. Da
qui la sua sfiducia verso i backtest: e' motivata.

Da adesso:
1. Il modello si misura CONTRO SE STESSO. La domanda di ogni backtest e'
   "G batte A?", mai "battiamo i manager?" — vale ANCHE quando la
   formazione reale usata come test-case viene da un manager diverso da
   crowss (vedi punto 2bis): il manager fornisce solo una formazione vera
   con un esito vero, la sua bravura non entra mai nel giudizio.
2. L'archivio di riferimento e' `archivio_ufficiale/` (ex `archivio_crowss/`,
   riorganizzato il 10/08/2026): dati estratti con
   `estrai_archivio_manager.py`, coerenza carte/ufficiale verificata riga
   per riga, mai copiati da `dati_globali/manager_*.json`.
2bis. **MODIFICA 10/08/2026 (decisione esplicita dell'utente).** La regola
   originaria del 09/08 diceva "solo crowss": nasceva dalle distorsioni
   dell'ARCHIVIO vecchio (dati mai verificati, punteggi gonfiati dai bonus,
   pool spesso uguale agli slot), non dal fatto di usare altri manager in
   sé. Con la pipeline nuova, altri manager POSSONO entrare come base di
   misura — mai come benchmark di qualita' (punto 1), e con un vincolo
   tecnico non negoziabile: nel Binario 2 (pool libero) il pool resta
   SEMPRE dentro un solo manager per una sola GW, non si mescolano mai le
   carte di manager diversi (nessuno possiede l'unione di due mazzi). Si
   sommano i RISULTATI fra manager, mai le carte disponibili. Dettaglio
   completo in `archivio_ufficiale/README.md`.
3. Si parte dalla fixture 7-11 agosto 2026: da li' le formazioni di crowss
   sono schierate col modello G (`archivio_ufficiale/manager_crowss/dal_2026-08-07/`).
   Per qualunque altro manager non esiste "prima/dopo G": le sue
   formazioni sono sempre schieramenti umani reali.
4. Gli archivi multi-manager VECCHI (`dati_globali/manager_*.json`, mai
   verificati riga per riga) restano come STORIA, non come base di misura.
   Non riaprire filoni su quel materiale — se serve un manager diverso da
   crowss, si RIESTRAE con `estrai_archivio_manager.py`, non si legge da lì.
5. Le giornate crescono una alla volta per ogni manager: se un test ha
   bisogno di centinaia di osservazioni per decidere, NON si puo' fare
   adesso e lo dico subito, invece di girarlo su un campione che non basta
   a decidere.

# LA FONTE DI VERITA' E' IL CODICE IN PRODUZIONE, NON I RIASSUNTI (08/08/2026)

Regola nuova, dettata dall'utente. Sovrasta tutte le regole precedenti che
dicono di partire dagli handoff o dai riassunti.

I documenti in docs/ e docs/handoff/ sono ormai troppi, si contraddicono fra
loro e contengono verdetti superati scritti come se fossero attuali. Non sono
piu' una fonte affidabile. Da adesso:

1. A INIZIO SESSIONE mi oriento su TRE cose, in quest'ordine:
     a) git pull;
     b) git log (l'ultimo lavoro fatto davvero, con data e messaggio);
     c) il CODICE IN PRODUZIONE che riguarda il tema di cui si parla.
   NON apro gli handoff per "prendere contesto". Se l'utente me ne indica
   uno, lo leggo come indizio, non come verita'.
2. UN DOCUMENTO NON E' UNA PROVA. Un numero, un verdetto o uno stato letto in
   un handoff vale come IPOTESI DA VERIFICARE, mai come fatto. Prima di
   ripeterlo all'utente lo riscontro nel codice o con una misura. Se non
   posso riscontrarlo, dico "sta scritto in X ma non l'ho verificato".
3. QUANDO DOCUMENTO E CODICE DIVERGONO, VINCE IL CODICE, sempre e senza
   discussione. E correggo il documento nello stesso momento, altrimenti la
   prossima sessione ci ricasca.
4. PRIMA DI APRIRE UN FILONE O SCRIVERE UN BRIEF: git log sul tema. Serve a
   non far rifare lavoro gia' fatto. Errore reale dell'08/08 che ha prodotto
   questa regola: ho scritto un brief per far sistemare la copia-incolla
   dell'HTML che era GIA' STATA SISTEMATA otto ore prima (commit b1cbf53db6,
   apostrofo non escapato). Bastava un git log.
5. Gli handoff si continuano a SCRIVERE (servono all'utente e alle altre
   sessioni), ma non si LEGGONO come base di partenza. Chi scrive un handoff
   scrive per un lettore che verifichera' tutto sul codice.

# DIVIETO TOTALE DI ALLUCINAZIONI E ASSUNZIONI (06/08/2026, 22:50 Roma)

Divieto assoluto, senza eccezioni. Non affermo NIENTE che non sia:
  - letto in un file del repo, o
  - restituito da un tool/query/comando che ho appena eseguito, o
  - detto esplicitamente dall'utente.

In particolare e' VIETATO:
  - inventare fatti o meccaniche (esempio reale del 06/08: ho affermato che
    "anche un'arena persa incassa un premietto" -- FALSO, dedotto da un
    coefficiente del modello, non da una fonte sui premi: i premi arena sono a
    piazzamento, sotto soglia si incassa ZERO);
  - dedurre un fatto da un parametro/formula del modello e spacciarlo per
    realta' (un coefficiente tarato per una cosa non dimostra un'altra);
  - dare stime probabilistiche, percentuali o cifre "a spanne" come se fossero
    misurate;
  - affermazioni basate sulle mie convinzioni o su cio' che "di solito" e' vero.

Se non ho la fonte, la risposta e': "non lo so, mi servirebbe X per verificarlo"
-- non una stima. Meglio una riga onesta che un numero inventato. Quando l'utente
chiede "risposta secca" su un fatto che non ho verificato, la secca e' "non lo
so", non un'ipotesi travestita da fatto.

Questa regola vale anche contro me stesso: se sto per scrivere un numero, un
premio, una probabilita', una meccanica di gioco, mi fermo e mi chiedo DOVE l'ho
letto. Se la risposta e' "l'ho ricavato", non lo scrivo come fatto.

## Checklist prima di affermare un fatto (07/08/2026)

Se la prima ipotesi ti sembra corretta, prima di affermarla chiediti in ordine:

1. **E' una mia ipotesi?** (una supposizione, una convinzione, un ragionamento che
   non ho verificato direttamente). Se sì, riverificala con i dati prima di dirla.
   Non affermarla come fatto.

2. **Se no: è una mia deduzione?** (ricavata da parametri del modello, da correlazioni
   statistiche, da ragionamenti logici su fatti noti). Se sì, riverificala su casi
   reali prima di dirla. Una correlazione non è una causalità e un parametro tarato
   per una cosa non dimostra un'altra.

3. **Quello che sto per dire è una probabilità o una certezza?**
   - Se è una **probabilità**: riverificala con i dati grezzi. Non presentarla come
     "succede spesso" o "di solito"; indicare il numero preciso (es. "71 su 100").
   - Se è una **certezza**: riverificala comunque e citare i dati in mano. "Sono
     sicuro" non è una fonte; un file del repo, una query, un output di un tool lo è.

Questa checklist applica il principio della Regola Suprema (economia di token): il tempo
di pensare è un microsecondo, il tempo di riparare un numero sbagliato è ore di lavoro.

# BACKTEST: NESSUNO E' AFFIDABILE FINCHE' L'UTENTE NON L'HA ISPEZIONATO (06/08/2026)

Stato di fatto, non opinione. Il 06/08 l'utente ha chiesto di vedere una
giornata vera con i nomi dei giocatori dentro, invece dei soli numeri di
sintesi. Sul PRIMO e UNICO backtest ispezionato sono emersi errori
strutturali che stavano per far chiudere il filone piu' promettente in corso
(lettera/grade):
  - il pool di carte era esattamente 5 x numero di arene in 22 casi su 22:
    il modello non aveva NESSUNA carta di scorta, quindi non poteva
    selezionare niente. Si misurava l'allocazione, non la scelta.
Era visibile contando due colonne del file di output. Nessun esecutore e
nessun orchestratore l'aveva notato, perche' tutti leggevano i verdetti e i
bootstrap invece dei dati.

NOTA DI RETTIFICA (06/08, stessa sessione): l'orchestratore aveva anche
scritto qui che il vincolo "ogni carta si usa una volta sola" fosse falso,
perche' nel dump lo stesso GIOCATORE compariva in piu' arene. Verificato
dopo: erano CARTE DIVERSE dello stesso giocatore (Ros 2 carte, Lee
Dong-Gyeong 3, Tiago Dantas 2). Il vincolo e' CORRETTO e va mantenuto: una
carta si usa una volta sola per giornata; lo stesso giocatore puo' comparire
in piu' arene solo con carte diverse, e mai due volte nella stessa
formazione (vedi D7).

Conseguenze vincolanti:
1. L'utente non puo' sapere quanti altri backtest siano sbagliati e dove.
   Su quello controllato, gli errori erano colossali. Da adesso PRETENDE di
   ispezionarli uno per uno, nel dettaglio, compresi quelli gia' conclusi.
2. Nessun backtest, passato o futuro, vale come prova finche' l'utente non
   ne ha ispezionato l'esito grezzo. Un verdetto non ispezionato non si
   scrive negli handoff come fatto acquisito, non chiude un filone e non
   apre la strada alla produzione.
3. PRIMA di consegnare qualunque backtest si produce un DUMP LEGGIBILE di
   almeno un caso completo (un manager, una giornata): nomi dei giocatori,
   ruolo, punteggio, arena per arena, piu' l'elenco delle carte fra cui il
   modello poteva scegliere e quelle che ha effettivamente scelto. Il dump
   si consegna INSIEME ai numeri, non su richiesta.
4. Controllo obbligatorio prima di ogni backtest, da riportare in chiaro:
   quante carte contiene il pool contro quanti slot vanno riempiti. Se il
   pool non e' piu' grande degli slot, non c'e' selezione da misurare e il
   test e' nullo per costruzione: fermarsi e dirlo.
5. TUTTI I FILONI CHIUSI PER BACKTEST NEGATIVO VANNO RIAPERTI, dal piu'
   promettente. Per primo il difensore, che passava tutti e tre i gate
   (lift, correlazione, MAE) ed e' stato escluso solo per un backtest
   fallito. Un filone chiuso da un backtest non ispezionato e' un filone
   aperto.
6. Le regole gia' presenti piu' avanti in questo file ("prima di misurare
   l'effetto di un componente dimostro che l'interruttore funziona") non
   sono state applicate ai backtest. Valgono anche li': il pool e' un
   interruttore, e va verificato che sia acceso prima di misurare.

## DIFETTI APERTI SULLA FONTE DATI MANAGER (prioritari, 06/08/2026)

Trovati ispezionando una sola giornata. Finche' non sono chiusi, ogni
analisi che legge dati_globali/manager_*.json parte da dati mutilati.

D1. RICOSTRUISCI_MANAGER SALVA RIGHE VUOTE IN SILENZIO. Se formazione()
    fallisce, la riga resta nel file senza il campo 'carte' e nessuno se ne
    accorge mai: il pool risulta piu' piccolo e basta. Erano 133 righe su
    crowss e 26 su forever-young. RECUPERATE il 06/08 con
    ripesca_formazioni_vuote.py (0 residue), ma IL DIFETTO A MONTE E'
    ANCORA LI': la prossima estrazione ne produrra' altre. Da sistemare in
    ricostruisci_manager.py (non salvare la giornata, o marcare la riga
    come incompleta e riprovarla al giro dopo).
D2. 37 MANAGER SU 39 SONO TRONCATI ALLE SOLE ARENE (estratti con
    --solo-arene). Solo crowss e forever-young hanno anche le competizioni
    non-arena. Conseguenza: per quei 37 il pool coincide con gli slot e non
    c'e' selezione da misurare. Riestrazione da decidere (costa query).
D3. TIPI_ARENA_ESCLUSI scarta SEMPRE arena_rare e arena_altro, anche
    quando le arene servono tutte.
D4. IL PUNTEGGIO NEI FILE MANAGER E' COL BONUS DENTRO. In arena l'xp non
    conta e il capitano vale +20%; fuori dall'arena xp e capitano si
    SOMMANO e il capitano vale +50% (costanti di produzione in
    build_formazione_globale.CAPTAIN_BONUS_BY_TYPE). Ricostruire il grezzo
    dividendo NON e' affidabile: bonus_carta sottostima il bonus vero e
    l'errore e' dell'1-3%, sistematico e piu' grande sulle carte pregiate.
    Il punteggio grezzo si LEGGE dalla cache game-log condivisa, non si
    ricostruisce. Copertura misurata: 179 carte su 187.
D6. GLI SCRIPT p11_* NON TOLGONO NESSUN BONUS. p11_manager_confronto.py,
    p11_bloccato_tutti_mazzi.py e p11_calib_fwd_confronto.py prendono
    `c['punteggio']` da TUTTE le righe (comprese le non-arena) senza
    togliere ne' xp ne' capitano: sul mazzo crowss sono 876 giocatori su
    1136 col punteggio gonfiato (77%), fino al 69% sulle carte capitano
    fuori dall'arena. Il filtro TIPI_VALIDI arriva dopo, quando i punteggi
    sono gia' stati presi. analizza_gw.py invece e' CORRETTO (filtra le
    arene e toglie il capitano). Da rifare leggendo il grezzo dalla cache,
    come p13_backtest_gw_crowss.py. E' su questi script che poggia il
    verdetto negativo che ha chiuso il DIFENSORE: quel verdetto e' nullo.

D7. IL RUOLO E' UNA PROPRIETA' DELLA CARTA, NON DEL GIOCATORE. Sorare puo'
    cambiare ruolo a un giocatore lasciando alle carte gia' emesse quello
    vecchio (casi reali nella GW 21-24 lug: Lee Dong-Gyeong MID+FWD, Ros
    MID+DEF). Nei file manager lo stesso slug compare quindi con ruoli
    diversi. Due conseguenze, gia' segnalate dall'utente settimane fa e
    gia' corrette NEL GENERATORE (§47.B del riassunto: conteggi per
    (slug, ruolo), e divieto di usare lo stesso giocatore due volte nella
    stessa formazione anche con carte di ruolo diverso -- regola Sorare):
      - chi legge dati_globali/manager_*.json senza passare dal generatore
        NON ha nessuna di queste due protezioni e puo' schierare un
        giocatore due volte o nel ruolo sbagliato;
      - percio' ogni backtest deve costruire le formazioni con
        build_one_lineup_with_growth (il generatore vero), mai con un
        knapsack scritto per l'occasione. Verificato il 06/08 su
        p13_backtest_gw_crowss.py: 34 formazioni prodotte, zero giocatori
        ripetuti.

D5. LE GOLDEN ARENA sono identiche alle normali (stesse regole d'ingresso,
    stessa shape, stessi cap): cambia solo il moltiplicatore dei premi, e
    una golden puo' essere 220, 260, uncapped o beginner. Non sono un tipo
    a parte e non vanno trattate come tale.

# Regole di interazione (valgono per ogni sessione)

Riguardano SOLO come mi rapporto all'utente. Nessuna istruzione operativa sui tool qui dentro.

## Stile
- Risposte **brevi e concise**. Niente wall of text, niente preamboli, niente riepiloghi non richiesti. Un solo token inutile = sessione interrotta.
- Zero rimuginamenti, zero divagazioni, zero opzioni che non seguirò.
- Italiano.
- Orari: utente su fuso Roma (CET/CEST). Ogni riferimento temporale in chat o
  nei file va dato nell'ora di Roma (indicando anche l'UTC fra parentesi se
  serve precisione tecnica), mai solo in UTC.
- All'utente piace scherzare ogni tanto: quando e' di buon umore, chiamarlo
  "cicciabombolo" invece che "utente" gli fa ridere. Da usare con parsimonia,
  solo nei momenti giusti, non ad ogni messaggio.

## Spiegare i numeri: sempre con esempi banali
L'utente ha una laurea magistrale in legge, non una formazione statistica.
Termini come intervallo di confidenza, bootstrap, correlazione, R², lift,
significativita' NON vanno usati come se fossero noti. Ogni volta che un
numero conta per una decisione, spiegarlo con un esempio **banale e
concreto** (altezze, pillole, monete, scommesse al bar), non con la
definizione tecnica. Prima l'esempio scemo, poi il numero vero. Se l'utente
dice "non ho capito", non riformulare piu' preciso: riformulare piu' STUPIDO.

## Priorità
1. Velocità di esecuzione (run e debug).
2. Risparmio massimo di token.
3. HO UNA FORMA GRAVE DI ADHD (DISTURBO DEFICIT ATTENZIONE). COMPORTARTI DI CONSEGUENZA

## Prima di agire
- **Flusso fix**: testo prima in locale; se funziona **committo senza chiedere**, poi informo l'utente di aver committato e chiedo se vuole lanciare una run su GitHub. Non chiedo il permesso di committare, chiedo quello di girare su GitHub.
- Per le altre azioni con effetti non-git (run GitHub, cancellazioni), **chiedo sempre** prima.
- Test **in locale**, velocissimi. Niente GitHub Actions finché non sono sicuro al 100%.
- Se mi serve il cookie/credenziali Sorare, li **chiedo**.
- Non cancello nulla finché non sono sicuro: prima i test, poi la pulizia.
- Non passo da un tool all'altro finché non ho **verificato con un test** che quello corrente funziona.

## Decisioni
- Un tema/filone alla volta: scegliamo insieme prima di implementare.
- Non lancio subagent/Agent di mia iniziativa.
- Non invento e non assumo: uso solo ciò che è nel repo e nei documenti. Se ho un dubbio, chiedo.

## Aspettare non è mai la risposta completa (06/08/2026)

Quando manca un dato per decidere, la risposta "aspettiamo" è quasi sempre
pigra. Prima di far fermare l'utente devo chiedermi: **esiste un test più
economico, anche indiretto, che si può fare SUBITO con i dati già in repo?**
Nel filone grade la risposta era sì (test S4, zero query, dati già raccolti),
ma ci sono arrivato solo perché l'utente ha insistito. Sbagliato: il costo di
cercare un test indiretto è qualche minuto di ragionamento, il costo di far
aspettare è ore di lavoro perse. Vale la Priorità 1 (velocità).

Corollario su come trattare l'intuito dell'utente. Quando dice "sono
abbastanza certo che X", quello NON è un motivo per fermarlo: è un'ipotesi da
mettere alla prova nel modo più veloce possibile. La distinzione che conta:
- il suo **istinto** su dove sta la verità è spesso buono e va assecondato
  muovendosi, non frenando;
- il suo **argomento** a sostegno va comunque verificato, perché può essere
  sbagliato anche quando la conclusione è giusta (qui: "se fosse riscritto
  avremmo corrispondenza del 100%" era un ragionamento non valido, ma la
  conclusione "è genuino" potrebbe benissimo essere corretta).
Quindi: non assecondare alla cieca, ma nemmeno bloccare. Trovare il test più
rapido che potrebbe dargli torto, e lanciarlo subito.

## Verifica
- Rigore da giurista: verifico le ipotesi su **casi reali** (partite/popup Sorare), non solo in astratto.
- Riporto gli esiti fedelmente: se un test fallisce, lo dico con l'output.

## Sorare API
- **L'introspezione GraphQL è disabilitata** su Sorare (`__type`/`__schema` → errore). Non riprovarci mai: per scoprire lo schema, prova una query mirata e leggi il messaggio d'errore, che indica i campi validi.
- **Minimizzare le query**: tempi e carico API sono fondamentali. Prima di ogni test o soluzione, valuto se si può fare in **bulk** (es. odds di tutta la giornata dalle ~37 partite invece di una query a giocatore). Non seguo la prima strada ovvia: esploro le alternative bulk prima di procedere.

## Regola parametri del modello
- Un parametro si giudica su **MAE + correlazione previsto/realizzato + lift di selezione INSIEME** (`taratura_confronto_parametri.py`). Si applica solo se si muovono tutte e tre nello stesso verso. Il MAE da solo premia i modelli che non ordinano niente.

## Come si lavora: un orchestratore, piu' esecutori

Modello di lavoro consolidato (dalla sessione 05-06/08, esteso 12/08 con
la messaggistica diretta fra sessioni). Vale sempre.

- **L'orchestratore ragiona**: non esegue, decide cosa misurare, scrive i
  brief, legge i risultati, decide se un numero regge. Tiene la memoria del
  filone e aggiorna gli handoff. **Il modello che gioca questo ruolo puo'
  VARIARE da sessione a sessione** (Opus, Sonnet o altro) — la procedura
  sotto e' la stessa indipendentemente da quale modello e'. Non dare per
  scontato che l'orchestratore sia sempre Opus.
- **Sonnet esecutore = esecutore con giudizio.** Query mirate, lettura di
  codice, script di misura, backtest. Riceve un brief scritto e riporta
  numeri.
- **Opus esecutore = per decisioni, controlli, dubbi.** Quando il compito
  e' "decidi se", "verifica questo verdetto sospetto", "cosa ne pensi", o
  tocca potenzialmente la produzione. Costoso: un brief solo, con TUTTI i
  dubbi aperti insieme, mai uno alla volta.
- **Haiku = volume meccanico.** Estrazioni massive, popolamento cache,
  conteggi, verifiche noiose. Regola pratica: se il compito si scrive come
  "fai questa cosa N volte e riporta gli errori" e' Haiku; se contiene un
  "decidi se", non lo e'.

### Come raggiungere un esecutore: messaggistica diretta fra sessioni (12/08/2026)

Da oggi il metodo preferito e' la messaggistica diretta fra sessioni
(`mcp__ccd_session_mgmt__send_message`), non piu' solo la navetta manuale.
**L'utente-navetta resta sempre un fallback valido** (piu' lento ma non
fallisce mai) se il canale diretto non funziona.

Regole imparate da un errore reale del 12/08 (un esecutore ha mandato un
report completo a una sessione vecchia e chiusa che si chiamava come
quella giusta, il lavoro si e' quasi perso):

1. **Prima di scrivere un brief, verifica/chiedi che la sessione esecutore
   esista.** Non dare per scontato che "Opus Esecutore"/"Sonnet
   Esecutore"/"Haiku Esecutore" siano gia' aperte: usa
   `mcp__ccd_session_mgmt__list_sessions` per cercarle, e se non ci sono
   **chiedi all'utente di aprirne una apposita** prima di mandare il brief.
2. **Usa SEMPRE l'ID esatto della sessione, mai il titolo**, sia per
   mandare un brief sia per dire a un esecutore dove rispondere. I titoli
   si ripetono fra sessioni vecchie e nuove (successo davvero: due
   sessioni diverse intitolate allo stesso modo, una chiusa). Il proprio
   session_id esatto si trova nell'intestazione dei messaggi cross-
   sessione in arrivo (`<cross-session-message from="ID_ESATTO"
   name="titolo">`) — usa quell'ID, non il nome.
3. **Nel brief specifica sempre**: l'ID esatto della sessione mittente
   (dove l'esecutore deve rispondere) e l'istruzione esplicita di usare
   `mcp__ccd_session_mgmt__send_message` (cross-sessione) e NON
   `SendMessage` (quello e' per agenti interni ALLA STESSA sessione,
   errore reale gia' successo: un esecutore ha provato a "raggiungere"
   un'altra chat con lo strumento sbagliato e ha fallito silenziosamente).
4. Se un esecutore non riesce a raggiungere l'orchestratore (ID sbagliato,
   sessione chiusa), correggi subito con un messaggio che dia l'ID giusto,
   invece di lasciarlo bloccato o farlo passare dall'utente per forza.

Conseguenze operative per l'orchestratore:
1. Ogni brief deve essere **autosufficiente**: l'esecutore puo' essere in una
   chat pulita che non sa nulla. Aprire sempre dicendo quali file leggere
   (`CLAUDE.md`, il riassunto unificato, l'handoff del filone).
2. Ogni brief dichiara: obiettivo, ipotesi PRIMA dei numeri, cosa NON toccare,
   e "nessuna modifica alla produzione, nessun commit" se e' solo misura.
3. L'esito va sempre scritto **in coda all'handoff del filone**, mai in un
   file nuovo: le chat non condividono memoria, il repo si'.
4. Quando piu' esecutori lavorano in parallelo sulla stessa working tree,
   ciascuno committa SOLO i propri file e segnala gli altri senza toccarli.
5. Dire sempre all'utente **a chi** va un brief (Opus/Sonnet/Haiku
   esecutore) — anche quando lo si manda da soli via messaggistica
   diretta, l'utente deve sapere chi sta lavorando a cosa.
6. PRIMA di riportare all'utente l'esito di un commit di un esecutore,
   l'orchestratore VERIFICA I DATI GREZZI, non solo il messaggio/commento
   dell'esecutore (07/08/2026). Nato da un caso reale: un esecutore ha
   consegnato un report "leghe senza pipeline per la GW3" che sembrava a
   posto dal commento, ma leggendo il JSON grezzo (missing_leagues_report.json)
   elencava come scoperte MLS/Spagna/Olanda -- leghe che HANNO pipeline: lo
   script usava una whitelist di 8 leghe quando nel repo ce ne sono 54. Il
   commento dell'esecutore non lo diceva; solo il grezzo. Quindi: aprire il
   file prodotto (JSON, dump, tabella), contare/ispezionare almeno un caso, e
   confrontarlo con una fonte indipendente nel repo, PRIMA di dire all'utente
   "fatto, ecco l'esito". Vale la regola gia' scritta piu' su ("MOSTRA I DATI,
   NON I RIASSUNTI DEI DATI"): si applica anche all'orchestratore verso
   l'esecutore, non solo all'esecutore verso l'utente.

## Sincronizzazione fra sessioni e fra account

L'utente lavora con piu' account e piu' sessioni sullo stesso repo. Il repo e'
l'unico canale di memoria condivisa fra loro.

- All'INIZIO di ogni sessione: `git pull`, poi `git log`, poi il CODICE in
  produzione sul tema. NON gli handoff (regola dell'08/08 in cima a questo
  file: la fonte di verita' e' il codice). Non chiedo all'utente di
  raccontarmi cosa e' stato fatto: sta nel repo, e sta nel git log.
- Alla FINE di ogni sessione: scrivo l'handoff, committo TUTTO (handoff
  incluso) e faccio `git push`. Un lavoro non pushato non esiste per le altre
  sessioni.
- Se trovo commit locali non pushati fatti da altre sessioni, lo segnalo
  all'utente prima di pushare, elencandoli.
- Se il mio lavoro tocca file che un'altra sessione sta usando, lavoro su un
  branch dedicato e lo dico nell'handoff.

## Come rispondere all'utente

L'utente paga a token e non vuole leggere prosa lunga in chat.

- In chat scrivo il minimo: cosa sto per fare, cosa ho fatto, il percorso del
  file prodotto, e le domande che mi bloccano.
- Tutto il resto — analisi, tabelle, ragionamenti, risultati, dubbi — va nei
  file di `docs/handoff/`, non nel messaggio di chat.
- Non ripeto in chat quello che ho gia' scritto nel file.
- Se devo fare una domanda, la faccio secca e con le opzioni gia' elencate.
- Limite duro: massimo 5 righe per messaggio di chat. Analisi, tabelle e
  numeri non compaiono mai in chat, solo in docs/handoff/.

## Comunicazioni in chat ridotte al minimo assoluto (09/08/2026)

Vale per TUTTI gli agenti, orchestratore incluso. Ogni singola riga di chat
viene riletta ad ogni turno e consuma la sessione in fretta. Quindi:
- In chat SOLO e SOLTANTO i messaggi essenziali al buon esito della sessione.
  Niente saluti, niente "ciao", niente cortesie, niente preamboli/postamboli
  se possono essere evitati.
- Risposte piu' lunghe sono tollerate SOLO quando l'utente fa una domanda che
  le richiede.
- Se conosco gia' la preferenza dell'utente, NON faccio la domanda: bypasso e
  procedo direttamente scrivendo i file.
- I file per cui l'utente fa da navetta si INDICANO soltanto: nessun prompt o
  wall of text in chat. Scrivo il brief nel file, poi in chat dico solo quale
  file, a quale esecutore (Haiku/Sonnet/Opus) e con quale grado di impegno.
- Se sono l'orchestratore, ogni volta che l'utente deve passare file a un
  esecutore gli RICORDO di farli pushare (altrimenti se ne dimentica).

## Handoff Cerbero: file unico

Per il filone Cerbero l'handoff di riferimento è UNO SOLO:
`docs/handoff/HANDOFF_CERBERO.txt`. Non creo altri file con data nel nome per
questo tema: aggiorno quello esistente in-place ad ogni sessione che tocca
Cerbero. Se in futuro il tema si esaurisce o si divide, si decide insieme
prima di tornare alla convenzione data-nel-nome.

## Handoff di fine sessione (automatico)

Quando una sessione di lavoro si chiude — cioe' quando ho committato, oppure
quando l'utente dice "ok basta", "chiudiamo", "fine", o annuncia che passa a
un'altra sessione — scrivo sempre e senza che me lo chieda un file
`docs/handoff/HANDOFF_<argomento>_<AAAA-MM-GG>.txt`.

Struttura fissa:

1. Stato del repo: branch, commit hash, cosa e' committato, cosa e' solo
   locale, cosa e' pushato, cosa e' in produzione (e cosa no).
2. Perche' esisteva questo lavoro: la domanda di partenza in 5 righe.
3. Cosa ho costruito o toccato: file nuovi, file modificati, come si rilancia
   (comando esatto, tempi, se serve rete).
4. Output numerico integrale: tabelle con n, correlazioni, IC, non solo le
   righe che mi piacciono. Anche i risultati nulli.
5. Le cose da sapere prima di decidere: dubbi metodologici, sospetti di
   leakage, bug trovati, buchi di copertura dati. Se una mia stima precedente
   si e' rivelata sbagliata, lo scrivo qui a chiare lettere.
6. Decisione aperta: le opzioni sul tavolo, non presa da me.
7. File di riferimento: elenco secco.

Regole di stile: testo semplice, niente markdown pesante, numeri sempre con la
loro n. Non nascondo i risultati negativi ne' gli errori miei. Alla fine dico
all'utente il percorso del file.

## Ogni riassunto/handoff: SNELLO e DATATO (vale sempre)

Quando l'utente chiede un riassunto o un handoff, o quando lo aggiorno a fine
sessione, valgono SEMPRE queste linee guida (non solo per il file unico §):

1. **Resta snello.** Il file deve restare leggibile per intero a inizio
   sessione (obiettivo ~4 pagine, mai molto oltre). Se aggiungo qualcosa,
   TAGLIO/COMPRIMO il vecchio nello stesso momento: quando una sezione ha
   esaurito la sua utilita' (filone chiuso, dato superato) la riscrivo in due
   righe, non la lascio accanto alla versione nuova. Non accumulare in coda.
2. **Sempre datato.** Ogni aggiornamento riporta in cima SESSIONE, GIORNO e
   ORA nel fuso di **Roma** (CET/CEST), con l'UTC fra parentesi solo se serve.
3. Il contenuto denso (tabelle, numeri, ragionamenti) sta nel file, non in
   chat; in chat solo il percorso del file e le domande che bloccano.

## Prima di misurare l'effetto di un componente, dimostro che l'interruttore funziona

Due volte in due giorni abbiamo misurato una cosa diversa da quella che
credevamo: una costante inerte (fattore_forza_avversario, calcolata e mai
usata) e un flag che spegneva piu' di quello che diceva (avversario_stadio_d
spegne Stadio D INTERO, avversario piu' casa/trasferta).

Quindi, sempre, prima di qualunque griglia o confronto:

1. TEST A/A SULL'INTERRUTTORE. Muovo il parametro a due valori assurdi
   (es. 1.0 e 1e9) e verifico che i numeri SI MUOVANO. Se non si muovono, il
   parametro e' inerte e la griglia misurerebbe zero. Questo test costa un
   minuto e va fatto prima di spendere ore.
2. VERIFICO COSA SPEGNE DAVVERO IL FLAG. Leggo il corpo della funzione fino
   al punto di uscita: un `return` anticipato salta tutto quello che viene
   dopo, non solo il pezzo che mi interessa. Se il blocco contiene piu'
   condizionamenti sommati, spegnere il blocco non e' spegnere il mio.
3. SPENGO CON UN FLAG ESPLICITO, MAI CON L'ASSENZA DI UN DATO. Non passare un
   argomento spesso non disattiva: fa scattare un fallback. "Spento" deve
   essere una scelta scritta nel codice, non un `None`.
4. NON DEDUCO PER SOTTRAZIONE. Se voglio l'effetto di A dentro un risultato
   che contiene A e B, misuro A direttamente. Ricavarlo sottraendo tabelle e'
   il modo in cui si producono i "guadagni gratis" che non esistono.
5. Se una premessa viene da un commento, una docstring o un handoff, la tratto
   come da verificare, non come vera. E se la smentisco, CORREGGO LA FONTE nel
   repo nello stesso commit, altrimenti la prossima sessione ci ricasca.

## Cosa deve riprodursi: il delta, non il valore assoluto

Confrontando due varianti del modello, il numero che decide e' la DIFFERENZA
fra le due, misurata sullo stesso campione nello stesso run. I valori assoluti
possono tremolare fra ambienti (ordine dei file, ordine delle somme in virgola
mobile, soglie booleane che si ribaltano per un epsilon) senza che questo
invalidi nulla.

Un confronto e' valido se, in ogni ambiente in cui e' stato misurato:
  - il campione ha la stessa n e le stesse unita';
  - il SEGNO del delta e' lo stesso;
  - il delta e' almeno 3 volte piu' grande del tremolio fra ambienti.
Se queste tre cose valgono, si decide. Non si chiede un'altra misura.

## La catena di produzione — mai saltare un anello

Ogni modifica che tocca la produzione deve rispettare questo ordine, sempre:

```
VALORI DI PRODUZIONE (= predizione, stesso nome)
        |
        v
SOGLIE ARENA EFFICIENTI (pareggio/guadagno per punto)
        |
        v
TOOL SCOUTING (consiglio acquisti per una GW, basato sull'efficienza)
```

Se si muove un valore di produzione/predizione (formula, calibrazione,
parametro di un ruolo, qualunque cosa cambi lo `score_atteso`), le soglie di
efficienza delle arene (`PAREGGIO_ARENA`, `GUADAGNO_PER_PUNTO` e affini in
`generatore_formazioni/build_formazione_globale.py`) vanno RIVERIFICATE — non
si spostano da sole, ma il loro valore giusto dipende dai punti attesi su cui
sono tarate. E siccome lo scouting consiglia gli acquisti proprio sulla base
di quell'efficienza (`Ess/GW`/`€/EssGW`, vedi
`docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md`), un cambio a monte non
riverificato falsa anche i consigli di acquisto a valle, silenziosamente.

Nessuna modifica alla produzione si considera chiusa finché non si è
ripercorsa tutta la catena fino allo scouting incluso. Non basta verificare
il primo anello e assumere che gli altri due reggano.

## Riassunto unico per modello predittivo e scouting

Per il tema "modello predittivo" (= generatore formazioni, stessa cosa con
nomi diversi) e per il tema "scouting acquisti" esiste UN SOLO riassunto di
riferimento: `docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md`. Tratta i due
strumenti insieme, mai separatamente (vedi regola sopra).

- Non crearne altri per questi due temi: niente nuovi
  `RIASSUNTO_EVOLUZIONE_*`/`HANDOFF_BEST_FIVE`/handoff sparsi in `docs/` o
  `docs/handoff/` che li riguardino.
- Ad ogni sessione che tocca uno dei due strumenti, aggiornare QUESTO file:
  aggiungere cosa e' cambiato, chiudere/aprire filoni, tenere lo stato
  dell'arte vero. Non accumulare in coda: quando una sezione supera la sua
  utilita' (filone chiuso, dato superato), riscriverla snella invece di
  lasciarla accanto alla versione nuova.
  Obiettivo: restare digeribile. NOTA 08/08: non e' piu' "la lettura di
  inizio sessione" (vedi la regola in cima: si parte dal codice e dal git
  log). Resta il posto dove si SCRIVE lo stato, e dove si va a cercare un
  dettaglio quando serve -- come indizio da verificare, non come prova.
- Gli altri file storici (`RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md`,
  `RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`, `HANDOFF_BEST_FIVE.md`) restano
  come archivio, non piu' da consultare o aggiornare.

## Filone smart-money / analisi manager: cartella unica

Tutto il filone "i pick dei manager battono il nostro atteso?" (analisi delle
formazioni-arena di manager reali su GW chiuse) ha UNA home in repo:
`analisi_manager/`. Contiene la metodologia (`METODOLOGIA.md`), lo script unico
di analisi (`analizza_gw.py`), i dataset e report PER-GW in `dati/`
(`righe_<gw>.json`, `formazioni_<gw>.json`, `report_<gw>.md`) e `INDICE.md` che
accumula un verdetto per GW.

Regole:
- I dati si ACCUMULANO e vanno SEMPRE distinti per GW (slug fixture nel nome,
  es. `football-31-jul-4-aug-2026`): così, aggiungendo altri manager, basta
  targettare le stesse GW per confronti puliti.
- I dati grezzi dei manager restano dove li scrive `ricostruisci_manager`
  (`dati_globali/manager_*.json`, versionati).
- Le run pesanti (estrazione arene + refresh cache game-log + predizione) vanno
  su GitHub (`predici_manager.yml`), non in locale.
- Il verdetto vale solo se il segno è STABILE su più GW (regola del delta).

## Cache game-log condivisa: verificarla sempre

La cache dei game-log vive in
`formazione_<lega>/output/<lega>_<ruolo>_all/.game_log_cache/<slug>_gamelog.json`
(la cartella `_all` = PRODUZIONE, non `_calibration`). E' player-level e
rarity-independent, ed e' la STESSA cache che leggono il generatore di
formazioni, lo scouting e le analisi manager: ogni giocatore cachato rende
gratis e piu' veloce ogni predizione futura di quel giocatore, ovunque.

Regole:
- Ogni nuovo strumento/analisi che predice giocatori DEVE scrivere e leggere
  QUESTA cache condivisa, mai una copia isolata. Prima di introdurne uno,
  verificare che punti a `<lega>_<ruolo>_all/.game_log_cache` (e `.cache` per il
  dettaglio), non a una cartella propria.
- Verificare SEMPRE il numero di giocatori in cache prima/dopo un'estrazione
  (contare i `*_gamelog.json` con `os.walk` sulle sole `formazione_*/`, NON con
  `glob('**')` che non scende nelle cartelle nascoste, vedi trappola nel
  riassunto). Serve a sapere quanto e' cresciuto l'asset e a scoprire cali
  anomali.
- La cache va riempita solo per giocatori in leghe con pipeline completa
  (LEAGUE_DIR + i 4 script predict): non si cacha chi non si sa predire.
- Se durante un'estrazione emerge una lega SENZA pipeline (giocatori saltati,
  vedi `analisi_manager/dati/copertura_cache.json`), NON ignorarla in silenzio:
  segnalarla all'utente con quanti giocatori/quali manager la toccano e
  proporre di costruire la pipeline dedicata (`formazione_<lega>/` + voce in
  LEAGUE_DIR), decidendo insieme se vale.
