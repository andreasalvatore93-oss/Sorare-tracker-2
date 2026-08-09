# archivio_crowss — l'unico archivio di riferimento per i backtest

Creato il **09/08/2026** (Roma), per decisione dell'utente. Al momento è
un **contenitore vuoto e non urgente**: nessuna estrazione è stata fatta,
nessun backtest è in attesa. Serve ad avere un posto già pronto — e una
convenzione già decisa — per quando ce ne sarà bisogno.

## Perché esiste

Fino al 09/08 i backtest confrontavano il modello con le scelte di altri
manager Sorare (24 manager, 6 giornate, `dati_globali/manager_*.json`).
Quella strada ha prodotto archivi misti, competizioni mescolate e criteri
di schieramento ignoti: di 23 manager su 24 non sappiamo con che regola
scegliessero. Ne sono usciti verdetti che l'utente non ha mai potuto
controllare fino in fondo, e da lì la sua sfiducia — motivata — verso i
backtest.

**Da adesso il modello si misura solo su giornate dell'utente**, le sole
di cui si conoscano dinamiche, voti, formazioni e il perché di ogni
scelta. La regola sta in `CLAUDE.md` e in testata a
`docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md`.

## Le due partizioni, e cosa significano

Il taglio è la **fixture 7-11 agosto 2026**, e la distinzione è netta
perché lo è nella realtà:

| cartella | periodo | chi ha schierato |
|---|---|---|
| `pre_2026-08-07/` | fino al 6 agosto 2026 | **crowss manager reale**: le formazioni le costruiva il bot ma l'utente le correggeva SEMPRE a mano. Il modello era ancora primordiale (è nato a inizio luglio 2026). Va trattato come benchmark UMANO, non come una versione del modello. |
| `dal_2026-08-07/` | dalla fixture 7-11 agosto 2026 | **modello G**, schierato integralmente senza correzioni a mano. È la prima finestra in cui ciò che è in campo coincide con ciò che si vuole misurare. |

## Le due domande che questo archivio deve saper reggere

1. **Il modello batte l'utente vecchio?** → confronto su `pre_2026-08-07/`,
   dove il riferimento sono le scelte umane di crowss.
2. **Una variante batte G?** → confronto su `dal_2026-08-07/`, dove il
   riferimento è la versione in produzione. È la domanda "il modello
   contro se stesso", quella che conta d'ora in avanti.

## Cosa ci va e cosa NO

- **SÌ**: giornate di `crowss`, tutte le competizioni che gioca davvero —
  arene, In Season, All Star, Under 23. Ogni file dichiara nel nome la
  fixture e la competizione, così non serve aprirlo per sapere cos'è.
- **NO**: dati di altri manager. Restano dove sono
  (`dati_globali/manager_*.json`) come **storia**, non come base di
  misura. Non mescolarli qui: è esattamente il difetto che questo
  archivio esiste per eliminare.
- **NO**: archivi con competizioni diverse mescolate nello stesso file.
  Se un numero esce da qui, si deve poter dire su quale competizione è
  stato calcolato senza ricostruirlo.

## Avvertenza sulla numerosità

Le giornate dell'utente crescono **una alla volta**. Un test che ha
bisogno di centinaia di osservazioni per decidere non si potrà fare per
parecchio tempo: va detto subito, invece di girarlo lo stesso e produrre
un intervallo così largo da non decidere niente (è successo tre volte di
fila l'08-09/08 sui filoni del grade). Meglio aspettare giornate vere che
decidere su dati che non ci appartengono.
