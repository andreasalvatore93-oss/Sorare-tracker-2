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

---

## Schema dati — tassonomia, campi, controlli (deciso 10/08/2026)

Regola generale, sopra a tutto quello che segue: **whitelist solo
competizioni Limited** (per slug). Qualunque competizione
`rare_superrare_unique`, arena o non-arena, è vietata in questo archivio.
Non riguarda le carte: una carta *rare* schierata dentro una competizione
Limited conta come limited a tutti gli effetti (nessun trattamento
diverso).

Le competizioni che compariranno in futuro, anche se non ancora tracciate
oggi, ricadranno sempre in uno dei tre macro-tipi sotto — non serve
prevederne altri finché non se ne presenta uno che non ci rientra.

### Campi comuni a ogni riga, qualunque tipo

- `contender_slug` — **chiave univoca della riga**, mai `(gw, tipo)`: fino
  a 3 formazioni proprie possono stare nello stesso pool arena nella
  stessa giornata, perderle è già successo (§8, trappola 2 nell'handoff
  unificato).
- `fixture_slug` — lo slug esatto della giornata Sorare (es.
  `football-7-11-aug-2026`), non "GW n" a parole.
- `manuale` (bool) — se questa riga è stata corretta a mano dall'utente
  dopo lo schieramento automatico. Necessario perché il taglio
  pre/post-G presume che dal 7/8 in poi sia sempre modello G puro: se
  càpita ancora una correzione manuale, quella riga non è "il modello" e
  va poterlo distinguere, altrimenti l'archivio nuovo si sporca come il
  vecchio.
- `annullata` (bool) — vedi sezione dedicata sotto.
- `capitano` — almeno `{slug, ruolo}` del capitano.
- `carte` — lista `{slug, ruolo, rarita, punteggio, capitano}` per ogni
  carta schierata, **solo se non appesantisce troppo l'estrazione**
  (deciso 10/08: sì in linea di principio, va verificato sul campo).
- **Controllo di coerenza obbligatorio** prima di salvare: somma dei
  `punteggio` delle carte ≈ `punteggio_totale` ufficiale, tolleranza
  ±0,5. Se lo scarto è enorme (vedi "annullata" sotto), è il primo
  segnale che la formazione non è mai stata conteggiata.

### 1. Arene Limited — Beginner, Cap 220, Cap 260, Uncapped, Arena Division

Campi propri: `tipo` (beginner|cap220|cap260|uncapped|division), `gold`
(bool, **campo esplicito**, non solo nota — un'arena gold ha lo stesso
costo del tipo corrispondente ma premi moltiplicati: Beginner Gold=100,
Cap 260 Gold=300 ecc., si calcola identica al tipo normale), `gw`,
`costo_ingresso`, `piazzamento` (rank), `punteggio_totale`, `premio`
(se preso), `premio_netto` (`premio - costo_ingresso`).

Check di validazione: `max_classic=None` (nessun tetto sulle Classic),
`bonus_xp=0`, `bonus_capitano=+20%`, carte rare ammesse=sì, numero carte
formazione=**5**.

### 2. Da7 — All Stars 7, Under 23

Campi propri: `tipo` (allstar7|under23), `punteggio_totale`. **Nessun
costo d'ingresso, nessun premio in essenze da rilevare.** In analisi le
due competizioni sono sommabili (stesse regole, differiscono solo per
l'eleggibilità: U23 richiede giocatori under 23).

Check di validazione: `max_classic=None`, `bonus_xp=sì`,
`bonus_capitano=+50%`, carte rare ammesse=sì, numero carte
formazione=**7**.

Bonus condizionali sulla carta, additivi fra loro e con l'xp personale
della carta: **+4%** se `punteggio_totale ≤ 370`, **+2%** se la
formazione ha al massimo 2 carte dello stesso club (anti-stack). Esempio:
carta non capitano con xp personale 5%, formazione con totale ≤370 e
max 2 carte stesso club → bonus totale 5+4+2=11%; da capitano, 50+11=61%.

### 3. In Season

Campi propri: `lega`, `sottotipo` (hot_streak|pvp), `punteggio_totale`;
per Hot Streak anche `gradino_raggiunto` (340→500 essenze, 360→1000,
400→25€, 420→100€, 460→500€, solo il più alto della settimana conta) e
`premio_gradino`; per PVP anche `posizione_leaderboard` e `premio_pvp`
(leaderboard globale contro altri manager, non contro soglie, premio
variabile per piazzamento). Se entrambe le competizioni sono presenti
nella stessa GW/lega i premi **si sommano** — righe distinte, sommabili
in analisi. Gratis, nessun costo d'ingresso.

Nota: i premi possono in teoria variare fra leghe (es. Scozia ≠ Spagna),
ma oggi l'utente gioca solo MLS e K League In Season (hotstreak+pvp),
premi identici — informativo, nessuna azione richiesta.

Check di validazione: `max_classic=1` (min 4 carte In Season su 5),
`bonus_xp=sì`, `bonus_capitano=+50%`, carte rare ammesse=sì, numero
carte formazione=**5**.

Bonus condizionali (stesso meccanismo di Da7, soglia diversa perché sono
competizioni da 5 carte): **+4%** se `punteggio_totale ≤ 260`, **+2%**
anti-stack max 2 carte stesso club.

### Formazioni annullate — trovato e verificato il 10/08/2026

Sorare puo' annullare una formazione già schierata (osservato: quando una
delle carte viene messa in vendita sul marketplace). Le carte mantengono
il loro voto reale in `so5Appearances`, ma il punteggio ufficiale di
classifica (`so5Rankings.score`) viene azzerato — **nessun campo esplicito
`cancelled` nello schema**, è uno scarto puro fra somma-carte e
punteggio-ufficiale.

Verificato su 2 casi reali (manager crowss, GW 7-11 agosto 2026,
`ricostruisci_manager.formazione()`):
- All Star 7 (Da7): carte 0+74.03+55.37+0+82.26+50.79+66.98=**329.43**,
  ufficiale=**0.0**, rank=40858 (ultimo posto).
- Arena Cap 260: carte 6.4+78.36+60.0+62.6+110.04=**317.4**,
  ufficiale=**0.0**, rank=10 (ultimo posto su 10).

Il controllo di coerenza già previsto sopra (±0,5) la intercetta da solo,
senza bisogno di un campo dedicato: uno scarto di 300+ punti è il segnale.

**Trattamento, differenziato per costo**:
- **Arene** (costo pagato): la riga resta in archivio con
  `annullata: true`, `costo_ingresso` normale, `punteggio_totale: null`
  (il voto non è un segnale valido: va escluso da qualunque analisi di
  selezione/previsione), `premio: 0`, `premio_netto: -costo_ingresso` —
  **conta nel ROI in essenze**, è una perdita reale.
- **Da7 / In Season** (nessun costo): la riga **non entra in archivio**
  (o al massimo una nota informativa) — non c'è nulla da contabilizzare,
  l'unica perdita è la formazione sprecata, zero essenze.

### Campo `atteso` per carta — refresh obbligatorio prima di calcolarlo (10/08/2026)

Ogni carta porta anche `atteso` (walk-forward, funzione di produzione
`backtest_arene_previsioni.score_atteso(cache, slug, ruolo, fine_giornata)`,
zero codice nuovo). Senza questo campo l'archivio può rispondere solo
"quanto ha reso" (ROI), non "il modello aveva previsto bene" — la domanda
per cui l'archivio esiste.

**La cache condivisa non è aggiornata per riflesso per tutti i giocatori**:
si aggiorna solo quando un giocatore passa per una run di produzione. Sul
primo test (GW 4-7 agosto 2026, pre-G) la copertura era del 43% (52/121
carte) — non per leghe non tracciate (0 slug con cache vuota), ma perché
molti giocatori avevano l'ultima partita in cache appena fuori dalla
finestra di ricerca di 6 giorni usata da `partita_target()`.

**Passo obbligatorio, prima di calcolare `atteso` per una GW**:
1. Elenco slug/ruolo delle carte schierate (già nell'archivio).
2. `python predici_manager_batch.py --input <file> --force` — rinfresca la
   cache ESATTAMENTE per quei giocatori (stesso tool del filone
   smart-money). Costa query vere, non è gratis/offline come il calcolo
   dell'atteso.
3. Dopo il refresh, `backtest_arene_previsioni.diagnostica_staleness_cache()`
   per riportare il grezzo (trovati/mancanti) — se restano buchi, sono
   reali (lega senza pipeline, o partita non ancora in Sorare) e vanno
   segnati in chiaro, mai scartati in silenzio.

Sul test: 43% → **92,6%** dopo il refresh (112/121). Residuo 7 carte: 2
strutturali (lega senza pipeline), 5 rimaste scoperte anche dopo il
refresh forzato (piccolo, non inseguito oltre).

**Non si allarga la finestra dei 6 giorni** per compensare: rischia di
agganciare la partita sbagliata (di un'altra GW). Il fix è tenere la
cache aggiornata per chi serve, non allentare il criterio di ricerca.

**Quando NON serve** (deciso 10/08/2026, GW3 post-G): `atteso` risponde
"il modello aveva previsto bene le carte che ha scelto lui?" — una domanda
che ha senso su `pre_2026-08-07/` (modello G contro le scelte umane vecchie)
o per confrontare una VARIANTE del modello contro G. Su una GW già
schierata da G in produzione non aggiunge niente per il solo scopo di
tracciare risultato/ROI: si salta, si rifà solo se serve davvero
confrontare un numero previsto contro il realizzato.

---

## Come rilanciare un'estrazione — ricetta pratica (10/08/2026, verificata su GW3)

Tempo: pochi minuti di rete per ~40 formazioni. Nessuna modifica alla
produzione, nessun file toccato fuori da `archivio_crowss/`.

**Strumenti, in ordine:**

1. **`ricostruisci_manager.partecipazioni(manager, fixture_slug)`** — elenco
   di tutte le partecipazioni (contender_slug + leaderboard) del manager
   nella GW. Richiede `SORARE_COOKIE` in env (l'indice non è pubblico).
2. **`ricostruisci_manager.formazione(contender_slug)`** — per OGNI
   contender: carte (slug, nome, ruolo, rarità, punteggio, capitano),
   manager, piazzamento (`{rank, punteggio}`). Query pubblica, `con_cookie=False`
   nel codice: non serve il cookie qui, solo per il passo 1.
3. **rewardsConfig per premio vero** — stessa query GraphQL di
   `scarica_premi_arene.py` (sessione anonima, nessun cookie), MA lanciata
   sugli slug leaderboard ESATTI della GW che si sta estraendo (non
   riusabile da run precedenti: ogni arena ha il suo jackpot, verificato
   su GW3 due arene "Cap 260" con premio 1° posto rispettivamente 4000 e
   1300 essenze — non è un errore, sono jackpot diversi). Una query per
   ogni leaderboard UNICA (non per ogni formazione: più formazioni proprie
   possono condividere la stessa arena).
4. **`costo_ingresso`** — MAI da query, si legge dalle costanti di
   produzione `COSTO_INGRESSO` in
   `generatore_formazioni/build_formazione_globale.py`: cap260=300,
   cap220=200, uncapped=300, beginner=100, elite=800; le arene dedicate a
   un campionato (`tipo: division`, es. Jupiler) costano 300 come la
   cap260 anche se Sorare le etichetta "Cap 260" nel `displayName`.

**Come si riconosce il `tipo` dallo slug della leaderboard** (nessuna
chiamata dedicata, si guarda la stringa):
- contiene `arena_limited_beginner` → `beginner`
- contiene `arena_limited_uncapped` → `uncapped`
- contiene `arena_limited` ma il prefisso lega NON è `all_star` (es.
  `seasonal-jupiler-...`) → `division`
- contiene `arena_limited` col prefisso `all_star` → `cap260`
  (non ancora capitato un `cap_220` su GW reali di crowss: se compare,
  lo slug ha `arena_limited_cap_220`, stessa logica)
- contiene `all_star_limited` (senza `arena`) → Da7 `allstar7`
- contiene `under_twenty_one_limited` → Da7 `under23`
- contiene `in_season...pve` → In Season `hot_streak`; `...pvp` → `pvp`

**Controllo di coerenza, sempre, su OGNI riga prima di scriverla**: somma
`punteggio` delle carte vs `punteggio_totale` ufficiale, tolleranza ±0,5.
Se lo scarto è enorme (visto su GW3: 376,41 vs 0,0 — GW ancora in corso,
un giocatore non aveva ancora giocato la sua partita) si applica il
trattamento del README sopra: arena → resta con `annullata:true`,
`punteggio_totale:null`, `premio:0`; Da7/In Season → riga scartata,
non entra nel file.

**Cosa NON serve** per una GW già post-G tracciata solo per risultato/ROI:
`predici_manager_batch.py --force`, refresh cache, campo `atteso` (vedi
sopra). Serve solo se si vuole confrontare un numero previsto contro il
realizzato.
