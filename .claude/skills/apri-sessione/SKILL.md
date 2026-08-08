---
name: "apri-sessione"
description: "Rituale di apertura sessione sul repo Sorare-tracker: git pull, git log, poi il CODICE in produzione sul tema - mai gli handoff. Usala all'inizio di ogni sessione di lavoro, o quando l'utente dice 'ripartiamo', 'nuova sessione', 'dove eravamo', 'prendi contesto', 'orientati'."
---

Stai aprendo una sessione sul repo Sorare-tracker. L'utente lavora con più
account Claude e più sessioni sullo stesso codice: tu non hai memoria di cosa
è successo prima, e **i documenti nel repo non sono una fonte affidabile**.

## La regola che viene prima di tutte

**La fonte di verità è il CODICE IN PRODUZIONE, non i riassunti.** In `docs/`
e `docs/handoff/` ci sono decine di file che si contraddicono fra loro e
contengono verdetti superati scritti come se fossero attuali. Un numero letto
in un handoff vale come **ipotesi da verificare**, mai come fatto. Se
documento e codice divergono vince il codice — e il documento va corretto
nello stesso momento, altrimenti la prossima sessione ci ricasca.

## I tre passi, in quest'ordine

1. **`git pull`** — se fallisce o va in timeout, dillo e prosegui sul locale.
2. **`git log`** degli ultimi 15-20 commit con data e messaggio: è l'unica
   cronaca affidabile di cosa è stato fatto davvero.
3. **Il CODICE che riguarda il tema di cui si parla.** Non gli handoff.

Solo dopo questi tre passi puoi dire qualcosa sullo stato del progetto.

## Prima di aprire un filone o scrivere un brief

**`git log` sul tema.** Serve a non far rifare lavoro già fatto. Regola nata
da un errore reale: un brief per far sistemare una cosa che era già stata
sistemata otto ore prima. Bastava un `git log`.

## Dove guardare, per tema

| tema | file da aprire |
|---|---|
| modello predittivo / generatore formazioni | `generatore_formazioni/build_formazione_globale.py` |
| previsione per ruolo | `formazione_<lega>/predict/test_<ruolo>.py` |
| scouting acquisti | `scouting_gw.py` |
| soglie ed economia delle arene | `consiglio_arena.py` + le costanti in `build_formazione_globale.py` |
| dati manager, backtest, analisi | `analisi_manager/` |
| stato dell'arte (come INDIZIO, non come prova) | `docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md` |

## Quale archivio arene usare (errore già commesso due volte)

- **statistica, ROI, sigma, backtest** → `dati_globali/manager_*.json`
  (~7.700 arene, ma **senza** i punteggi degli avversari)
- **classifiche complete, campo avversario, premi** → serve l'archivio con i
  punteggi di *tutti* i partecipanti; `dati_globali/arene_storico.json` è
  ridotto e non va usato per nuove misure finché non è ripristinato

## Cosa NON fare in apertura

- Non chiedere all'utente di raccontarti cosa è stato fatto: sta nel repo.
- Non leggere gli handoff "per prendere contesto". Se l'utente te ne indica
  uno, leggilo come indizio.
- Non riportare un numero letto in un documento senza riscontrarlo. Se non
  puoi, di': "sta scritto in X ma non l'ho verificato".

## Controlli che valgono la pena, se il tema li tocca

- **Flag di produzione**: prima di dire "X è attivo", leggi il *default* nel
  codice. Più di un interruttore è stato aggiunto **spento** dopo essere
  stato misurato e scartato: trovarlo nel codice non vuol dire che sia in uso.
- **Commit non pushati** di altre sessioni: segnalali all'utente elencandoli
  prima di pushare.
- **Permessi git**: in alcuni ambienti (Cowork) i comandi git di scrittura
  falliscono per permessi sul mount. Se il commit non passa, dillo subito e
  fallo fare a un esecutore, invece di lasciare il lavoro non committato
  credendolo salvo.

## Come riferire

Massimo cinque righe in chat: cosa dice il `git log`, cosa hai verificato nel
codice, e la domanda che ti blocca. Analisi, tabelle e numeri non vanno in
chat ma nei file.
