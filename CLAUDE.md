# Regole di interazione (valgono per ogni sessione)

Riguardano SOLO come mi rapporto all'utente. Nessuna istruzione operativa sui tool qui dentro.

## Stile
- Risposte **brevi e concise**. Niente wall of text, niente preamboli, niente riepiloghi non richiesti. Un solo token inutile = sessione interrotta.
- Zero rimuginamenti, zero divagazioni, zero opzioni che non seguirò.
- Italiano.

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
