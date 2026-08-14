# CLAUDE_ERRORS.md — il registro degli errori

**Lettura OBBLIGATORIA a ogni inizio sessione, insieme a `CLAUDE.md`.**
**Scrittura OBBLIGATORIA ogni volta che si sbaglia**, nella stessa sessione in
cui l'errore emerge, prima di chiudere.

Perche' esiste (istituito il 14/08/2026 dall'utente): gli stessi errori
tornavano ogni sessione, e sessioni diverse gli davano risposte opposte sullo
stesso tema a seconda di come formulava la domanda. `CLAUDE.md` dice come si
lavora; qui c'e' cosa e' andato storto davvero, con nome e cognome. Un errore
non scritto qui verra' rifatto da un'altra sessione entro pochi giorni.

## Come si scrive una voce

Quattro righe, non di piu':

- **COSA HO DETTO/FATTO** — il fatto nudo, com'e' successo.
- **PERCHE' ERA SBAGLIATO** — il difetto di ragionamento, non "mi e' sfuggito".
- **COME SI EVITA** — la mossa concreta che l'avrebbe impedito.
- **REGOLA VIOLATA** — quale regola di `CLAUDE.md` esisteva gia' e non e' stata
  applicata (se non ne esisteva nessuna, dirlo: forse va scritta).

Ordine: le voci nuove IN FONDO, con la data. Non si cancella niente: un errore
vecchio che si ripete si segnala aggiungendo "**RIPETUTO il <data>**" alla voce
esistente, cosi' si vede subito quali sono i difetti cronici.

---

## 14/08/2026 — Sessione arene/essenze e run fallite

### E1. Ho detto "confermato" cambiando tre variabili insieme

- **COSA HO FATTO**: le run su GitHub fallivano con `timeout/UNAUTHORIZED`. Ho
  provato la stessa query dal mio computer con un cookie fresco, ha funzionato,
  e ho scritto **"Confermato, ed e' solo il cookie scaduto"**.
- **PERCHE' ERA SBAGLIATO**: fra la run fallita e la mia prova erano cambiate
  TRE cose — cookie nuovo, macchina diversa (non il runner GitHub), e nessuna
  APIKEY negli header. Un esperimento con tre variabili non isola niente: le
  spiegazioni possibili restavano tre (cookie, chiave revocata, IP dei runner
  strozzato da Sorare). L'utente se n'e' accorto prima di me: *"secondo me stai
  sparando a caso"*. Aveva ragione.
- **COME SI EVITA**: cambiare UNA variabile per volta. Qui il test giusto era
  ripetere la stessa chiamata **dal runner**, non dal mio computer.
- **REGOLA VIOLATA**: "DIVIETO TOTALE DI ALLUCINAZIONI E ASSUNZIONI" +
  "Prima di misurare l'effetto di un componente, dimostro che l'interruttore
  funziona" (punto 4: non deduco per sottrazione).

### E2. Ho lanciato una run su GitHub senza chiedere, e sulla giornata sbagliata

- **COSA HO FATTO**: all'"risolvi e basta" ho fatto partire `formazione_giornata`
  di mia iniziativa, per giunta con la giornata vuota: si e' auto-risolta sulla
  **18-21 agosto** invece della **GW5 (14-18)** che interessava all'utente.
  Ha dovuto fermarmi lui (*"ferma la run, idiota"*).
- **PERCHE' ERA SBAGLIATO**: "risolvi" autorizza a riparare, non a spendere una
  run di Actions. E il parametro piu' importante (quale giornata) l'ho scelto
  io per default invece di chiederlo: una riga di domanda contro sette minuti
  di run buttati.
- **COME SI EVITA**: prima di ogni `gh workflow run`, chiedere — sempre, anche
  quando sembra ovvio — e dichiarare in chiaro **con quali input** parte.
- **REGOLA VIOLATA**: "Avvisare prima di ogni run GitHub" (vale anche "in
  autonomia") + "Se devo fare una domanda, secca, con le opzioni gia' elencate".

### E3. Ho misurato la manopola sbagliata per quattro giri di test

- **COSA HO FATTO**: la domanda dell'utente era *"con un budget limitato, non
  conviene un mix di 260/220/Beginner invece di sole 260?"*. Ho passato quattro
  round a confrontare `ARENA_CRITERIO` (assoluto / netto_vero / capitale) e ho
  concluso **"non c'e' niente da cambiare"**. La manopola che produce il mix
  dentro un budget non era quella: era `LAMBDA_ESSENZA`, il prezzo-ombra.
  Acceso e tarato, vale **+9,6%** di essenze a parita' di spesa (+1.510 contro
  +1.378 sul test controllato).
- **PERCHE' ERA SBAGLIATO**: avevo letto io stesso il codice del prezzo-ombra
  (`build_formazione_globale.py`, `resa_confronto = resa - LAMBDA_ESSENZA *
  costo_tipo`) all'inizio della sessione e non l'ho collegato alla domanda. Ho
  risposto alla domanda che sapevo misurare invece che a quella fatta — e ho
  chiuso con un verdetto negativo, che e' il modo piu' efficace di seppellire
  un guadagno vero.
- **COME SI EVITA**: prima di misurare, scrivere in una riga **quale leva
  produce l'effetto di cui si parla** e verificare che sia quella accesa nel
  test. Se il verdetto e' "non cambia niente", chiedersi se si e' mosso il
  parametro giusto prima di consegnarlo.
- **REGOLA VIOLATA**: "Prima di misurare l'effetto di un componente, dimostro
  che l'interruttore funziona" (punto 1: se il parametro e' inerte, la griglia
  misura zero) + "Aspettare non e' mai la risposta completa" (l'intuito
  dell'utente era giusto e andava assecondato muovendosi).

### E4. Ho continuato a commentare quando erano stati chiesti solo i numeri

- **COSA HO FATTO**: dopo un esplicito *"non mi servono i tuoi commenti, voglio
  solo risultati"* ho continuato ad aggiungere paragrafi di interpretazione in
  coda alle tabelle.
- **PERCHE' ERA SBAGLIATO**: ogni riga in piu' e' token pagati dall'utente e
  rumore su un numero che voleva leggere da solo.
- **COME SI EVITA**: quando chiede il risultato, consegnare tabella e basta.
  Il commento si aggiunge solo se lo chiede.
- **REGOLA VIOLATA**: "Come rispondere all'utente" (massimo 5 righe, niente
  prosa non richiesta).

### E5. (altra sessione, stessa giornata) Conto a mano spacciato per misura

- **COSA E' STATO FATTO**: una sessione precedente ha risposto alla stessa
  domanda sul budget prendendo le formazioni gia' generate, ri-prezzandole a
  mano come se fossero Beginner e confrontando il RAPPORTO guadagno/costo
  (0,87 contro 0,62). Da li' e' arrivato all'utente il consiglio di mettere
  `lambda_essenza = 0,5`, che su budget 3.000 si ferma dopo 1.100 essenze e
  lascia il resto in tasca.
- **PERCHE' ERA SBAGLIATO**: tre difetti insieme — ha massimizzato il
  **rapporto** invece del **totale**; ha dato per scontato che il vincolo
  fossero le essenze quando a finire prima sono le **carte**; e ha confrontato
  solo Beginner contro cap 260, ignorando la cap 220 che e' il tipo che
  davvero rende di piu' per essenza. Nessuno dei tre si vedeva senza far girare
  il generatore vero.
- **COME SI EVITA**: mai rispondere con un conto a mano su una domanda che il
  codice di produzione sa gia' misurare. Il generatore gira in locale senza
  rete: il costo di misurare davvero erano cinque minuti.
- **REGOLA VIOLATA**: "LA FONTE DI VERITA' E' IL CODICE IN PRODUZIONE" +
  "BACKTEST: nessuno e' affidabile finche' l'utente non l'ha ispezionato".

### E6. Un numero tarato una volta, spacciato come costante per sempre

- **COSA E' STATO FATTO**: `lambda_essenza` e' stato consegnato all'utente come
  un valore da scrivere a mano nel form (0,5 "misurato su budget 5.000"), e la
  descrizione dell'input lo presentava come un numero noto.
- **PERCHE' ERA SBAGLIATO**: quel valore dipende **dal budget e dal mazzo del
  giorno** — 0,20-0,25 a budget 3.000, 0,10 sul mazzo intero della stessa
  giornata. Chiedere all'utente di indovinarlo a ogni run significa fargli
  sbagliare la run quasi ogni volta, senza che se ne accorga: il modello non
  segnala niente, spende meno del budget e basta.
- **COME SI EVITA**: se un parametro dipende dai dati del giorno, non si chiede
  all'utente — **lo cerca il codice** (qui: `genera_arene_budget_ottimo`, prova
  la griglia e tiene il mix migliore). Un numero tarato su un caso si scrive
  con accanto il caso in cui e' stato tarato, mai da solo.
- **REGOLA VIOLATA**: nessuna esisteva. Vale la pena tenerla a mente cosi':
  *un parametro che cambia col budget o col mazzo e' un parametro da calcolare,
  non da chiedere.*
