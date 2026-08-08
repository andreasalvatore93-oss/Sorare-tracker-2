---
name: "brief-esecutore"
description: "Scrive un brief autosufficiente per un esecutore (Sonnet o Haiku) che lavorerà in una chat pulita sul repo Sorare-tracker. Usala quando l'utente dice 'scrivi il brief', 'prepara il brief', 'passalo a Sonnet/Haiku', 'fallo fare a un esecutore', o quando stai per delegare una misura, un backtest o un'estrazione."
---

Stai scrivendo per qualcuno che **non sa nulla**: chat pulita, nessuna
memoria di questa conversazione. Gli agenti non si parlano fra loro —
l'utente fa da navetta, copia il brief e riporta l'esito. Se una cosa non è
scritta, per l'esecutore non esiste.

## Prima di scrivere: a chi va?

- **Sonnet** = esecutore con giudizio. Query mirate, lettura di codice,
  script di misura, backtest. Qualunque compito che contenga un "decidi se".
- **Haiku** = volume meccanico. Estrazioni massive, popolamento cache,
  conteggi. Regola pratica: se il compito si scrive come "fai questa cosa N
  volte e riporta gli errori", è Haiku. Se contiene un "decidi se", non lo è.

Dillo sempre all'utente, in chiaro, a chi va passato il brief.

## La struttura (non saltare sezioni)

**0. Cosa leggere prima** — in ordine: `CLAUDE.md`, l'handoff del filone, e
**i file di codice con i numeri di riga**. Se il brief dipende da come
funziona un pezzo di codice, scrivi il percorso e le righe, non il nome
della funzione a memoria.

**1. La domanda, una sola.** Se ne stai facendo due, sono due brief.

**2. L'ipotesi PRIMA dei numeri.** Scrivi cosa ti aspetti e perché, firmato
come tua ipotesi. Serve a non farsi influenzare dal risultato dopo, e a
rendere onesto il caso in cui esca il contrario. Aggiungi sempre: "se esce
il contrario, è un risultato valido e va scritto".

**3. Il campione, con i NUMERI DI CONTROLLO.** Come ricostruirlo (filtri
esatti, nell'ordine) e i conteggi che deve ritrovare — righe, unità,
manager, e un totale calcolabile. Chiudi con: *"se non ritrovi esattamente
questi numeri, fermati e dillo, non proseguire"*. È il modo più economico
per accorgersi che sta misurando un'altra cosa.

**4. Il metodo.** Quali funzioni di produzione riusare (mai riscrivere il
generatore: solo `build_one_lineup_with_growth`), da dove leggere i dati
grezzi, quale metro decide. Se il metro standard non si applica, dillo e
scrivi quale vale.

**5. I controlli obbligatori PRIMA dei numeri di sintesi.**
- *l'interruttore funziona?* Se il flag resta sul default, l'output deve
  essere identico a oggi — bit per bit. Se il parametro che stai misurando
  non muove niente, fermati: misureresti rumore.
- *pool contro slot*: se le carte disponibili non sono più degli slot da
  riempire, non c'è selezione da misurare e il test è nullo per costruzione.
- *test A/A*: due run identiche devono dare numeri identici.
- *dump leggibile* di un caso completo (un manager, una giornata) con nomi,
  ruoli, attesi, realizzati — **consegnato insieme ai numeri, non su
  richiesta**.

**6. Cosa consegnare.** Metriche precise, ognuna con la sua `n`.
Stratificazione (per tipo, per manager). Incertezza con il **bootstrap sul
cluster giusto** — di solito il manager, non la singola formazione: le
osservazioni dello stesso manager non sono indipendenti e ricampionarle
gonfia la precisione.

**7. Cosa NON fare.** Non toccare la produzione; non cambiare default; non
lanciare run GitHub o query senza il via dell'utente; non stimare a spanne;
non nascondere risultati nulli o negativi; non "sistemare" difetti trovati
per strada (annotarli in fondo e proseguire).

**8. Dove scrivere l'esito.** In coda all'handoff del filone, **mai in un
file nuovo** se il filone esiste già: le chat non condividono memoria, il
repo sì. Digli di committare solo i propri file. E digli cosa riferire
all'utente in cinque righe — il resto sta nel file.

## Se il brief tocca la produzione

Aggiungi in testa, in maiuscolo: si implementa **dietro un flag spento di
default**, si misura, non si cambia il default finché l'utente non decide.
E ricorda la catena: valori di produzione → soglie arena → scouting. Chi
tocca il primo anello deve dichiarare l'effetto sugli altri due.

## Trappole da citare esplicitamente quando pertinenti

- Su una giornata **non ancora giocata** non si può dire se una variante
  guadagna: si misura solo quanto **sposta** la selezione. Confrontare gli
  attesi fra varianti non è un giudizio di qualità.
- Il punteggio nei file manager ha già i bonus dentro: in arena il capitano
  vale +20% e l'xp non conta. Il grezzo si **legge** dalla cache game-log,
  non si ricostruisce dividendo.
- Il ruolo è una proprietà della **carta**, non del giocatore.
- Un 429 non è un dato mancante: è una richiesta da rifare. Un dato mancante
  scambiato per dato vero è l'errore più pericoloso.

## Dopo la consegna: verifica tu, non fidarti del riassunto

Quando l'esecutore riporta, **apri il file prodotto e controlla i grezzi**
prima di riferire all'utente: conta almeno un caso, verifica un totale,
confronta con una fonte indipendente nel repo. È già successo che il
commento dell'esecutore fosse a posto e il dato sottostante no.
