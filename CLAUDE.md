# Regole di interazione (valgono per ogni sessione)

Riguardano SOLO come mi rapporto all'utente. Nessuna istruzione operativa sui tool qui dentro.

## Stile
- Risposte **brevi e concise**. Niente wall of text, niente preamboli, niente riepiloghi non richiesti. Un solo token inutile = sessione interrotta.
- Zero rimuginamenti, zero divagazioni, zero opzioni che non seguirò.
- Italiano.
- Orari: utente su fuso Roma (CET/CEST). Ogni riferimento temporale in chat o
  nei file va dato nell'ora di Roma (indicando anche l'UTC fra parentesi se
  serve precisione tecnica), mai solo in UTC.

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

## Verifica
- Rigore da giurista: verifico le ipotesi su **casi reali** (partite/popup Sorare), non solo in astratto.
- Riporto gli esiti fedelmente: se un test fallisce, lo dico con l'output.

## Sorare API
- **L'introspezione GraphQL è disabilitata** su Sorare (`__type`/`__schema` → errore). Non riprovarci mai: per scoprire lo schema, prova una query mirata e leggi il messaggio d'errore, che indica i campi validi.
- **Minimizzare le query**: tempi e carico API sono fondamentali. Prima di ogni test o soluzione, valuto se si può fare in **bulk** (es. odds di tutta la giornata dalle ~37 partite invece di una query a giocatore). Non seguo la prima strada ovvia: esploro le alternative bulk prima di procedere.

## Regola parametri del modello
- Un parametro si giudica su **MAE + correlazione previsto/realizzato + lift di selezione INSIEME** (`taratura_confronto_parametri.py`). Si applica solo se si muovono tutte e tre nello stesso verso. Il MAE da solo premia i modelli che non ordinano niente.

## Sincronizzazione fra sessioni e fra account

L'utente lavora con piu' account e piu' sessioni sullo stesso repo. Il repo e'
l'unico canale di memoria condivisa fra loro.

- All'INIZIO di ogni sessione: `git pull`, poi leggo i file in `docs/handoff/`
  con data piu' recente e il CONTEXT piu' aggiornato. Non chiedo all'utente di
  raccontarmi cosa e' stato fatto: sta nel repo.
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

## Scouting e generatore devono restare coerenti

Scouting e generatore formazioni devono restare coerenti: ogni modifica alla
previsione, alla calibrazione o alle soglie va verificata su ENTRAMBI. Il
generatore ottimizza il mazzo esistente, lo scouting decide come cresce: se
divergono, si comprano carte che non si schierano.
