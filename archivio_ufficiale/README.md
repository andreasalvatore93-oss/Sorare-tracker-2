# archivio_ufficiale — l'unica base di misura per i backtest

Creato il 09/08/2026 come `archivio_crowss/` (solo crowss), riorganizzato
il 10/08/2026 per ospitare più manager. La regola di fondo non cambia,
si allarga: **il modello si misura sempre e solo G contro A**, mai contro
un manager. I manager (crowss o altri) servono a fornire formazioni REALI
con esiti REALI su cui far scommettere G e A — non sono l'oggetto del
giudizio.

## Perché esiste, e perché ora ammette più manager

Fino al 09/08 i backtest confrontavano il modello con le scelte di altri
manager Sorare (24 manager, 6 giornate, `dati_globali/manager_*.json`).
Quella strada ha prodotto archivi misti, competizioni mescolate e criteri
di schieramento ignoti: di 23 manager su 24 non sappiamo con che regola
scegliessero. Ne sono usciti verdetti che l'utente non ha mai potuto
controllare fino in fondo, e da lì la sua sfiducia — motivata — verso i
backtest. La regola nata quel giorno diceva: solo le giornate di crowss,
mai altri manager.

**Modificata il 10/08/2026, decisione esplicita dell'utente**: quella
regola nasceva dalle distorsioni dell'ARCHIVIO vecchio (dati grezzi mai
verificati, punteggi gonfiati dai bonus, pool spesso uguale agli slot),
non dal fatto di usare altri manager in sé. Con la pipeline nuova
(`estrai_archivio_manager.py`, ex `estrai_archivio_crowss.py`) — coerenza
carte/ufficiale verificata riga per riga, DNP/0 esclusi secondo le regole
sotto, premi veri via `rewardsConfig`, soglie di produzione aggiornate —
**altri manager possono entrare come base di misura**, a una condizione
non negoziabile: **il confronto resta sempre G vs A, mai "battiamo il
manager X".** Il manager fornisce solo la formazione reale e il suo esito
reale; la sua bravura non entra mai nel giudizio.

## Struttura

```
archivio_ufficiale/
  README.md                      <- questo file
  manager_crowss/
    pre_2026-08-07/               <- crowss REALE (schierava a mano, modello primordiale): benchmark UMANO
    dal_2026-08-07/                <- modello G schierato integralmente: "il modello contro se stesso"
  manager_<slug>/                  <- altri manager, quando si aggiungono
    <fixture>_arene_limited.json   <- niente pre/dal: per loro G non è mai stato schierato, sono sempre "reale"
  aggregato/
    INDICE.md                      <- copertura: quali manager/GW disponibili per i test
    binario1_out.json              <- ultimo risultato Binario 1 (M vs G vs A), multi-manager
    binario2_out.json              <- ultimo risultato Binario 2 (G vs A, pool libero), multi-manager
```

**Solo `manager_crowss/` ha la partizione `pre_2026-08-07/` / `dal_2026-08-07/`**:
è l'unico manager per cui "prima/dopo G" ha un senso, perché G è il
*nostro* modello, schierato solo sul conto di crowss. Per qualunque altro
manager le sue formazioni sono sempre schieramenti umani reali, a
qualunque data — vanno tutte in `manager_<slug>/` senza sotto-cartelle.

## Le domande che questo archivio deve saper reggere

1. **Il modello batte l'utente vecchio?** → `manager_crowss/pre_2026-08-07/`,
   dove il riferimento sono le scelte umane di crowss.
2. **Una variante batte G?** → `manager_crowss/dal_2026-08-07/` più, da
   oggi, qualunque `manager_<slug>/`: G e A ricostruiscono/valutano la
   stessa formazione reale, si confrontano fra loro, mai col manager.

## Cosa ci va e cosa NO

- **SÌ**: formazioni reali di arena Limited (Beginner/Cap 220/Cap 260/
  Uncapped), un file per fixture e manager. Le "division" (arene dedicate
  a un campionato) sono **escluse di proposito** (decisione utente
  10/08/2026): residuali per crowss di recente, non giocate più, la
  soglia dedicata di produzione è dietro un flag spento di default e non
  è cablata nei binari 1/2 — niente dato grezzo da conservare, i dati
  Sorare non sono scarsi.
- **NO**: dati aggregati/ricostruiti a mano. Ogni file viene da
  `estrai_archivio_manager.py`, mai scritto o corretto a mano.
- **NO**: mescolare pool di manager diversi. Il Binario 2 (pool libero)
  gira SEMPRE dentro il pool di un solo manager per una sola GW — nessuno
  possiede l'unione dei mazzi di due persone. Si sommano i RISULTATI fra
  manager, mai le carte disponibili.

## Avvertenza sulla numerosità

Le giornate crescono una alla volta per ogni manager. Un test che ha
bisogno di centinaia di osservazioni per decidere potrebbe non essere
ancora possibile: dirlo subito, invece di girarlo lo stesso su un
campione che non basta a decidere.

---

## Schema dati — tassonomia, campi, controlli (deciso 10/08/2026)

Regola generale, sopra a tutto quello che segue: **whitelist solo
competizioni Limited** (per slug). Qualunque competizione
`rare_superrare_unique`, arena o non-arena, è vietata in questo archivio.
Non riguarda le carte: una carta *rare* schierata dentro una competizione
Limited conta come limited a tutti gli effetti (nessun trattamento
diverso).

### Campi comuni a ogni riga, qualunque tipo

- `contender_slug` — **chiave univoca della riga**, mai `(gw, tipo)`: fino
  a 3 formazioni proprie possono stare nello stesso pool arena nella
  stessa giornata.
- `fixture_slug` — lo slug esatto della giornata Sorare (es.
  `football-7-11-aug-2026`), non "GW n" a parole.
- `manuale` (bool) — se questa riga è stata corretta a mano dal manager
  dopo lo schieramento automatico. Per crowss `dal_2026-08-07/` è sempre
  il modello G puro (manuale=false salvo eccezioni segnalate); per
  `pre_2026-08-07/` e per qualunque altro manager è sempre `true`
  (schieramento umano).
- `annullata` (bool) — Sorare può annullare una formazione già schierata
  (osservato: quando una carta viene messa in vendita). Le carte
  mantengono il voto reale, ma il punteggio ufficiale (`so5Rankings.score`)
  viene azzerato. Trattamento: `punteggio_totale: null`, `premio: 0`,
  `premio_netto: -costo_ingresso` (conta nel ROI come perdita reale).
  Rilevata dal controllo di coerenza sotto (scarto enorme = segnale).
- `capitano` — almeno `{slug, ruolo}` del capitano.
- `carte` — lista `{slug, nome, carta, ruolo, rarita, capitano, punteggio}`
  per ogni carta schierata.
- **Controllo di coerenza obbligatorio** prima di salvare: somma dei
  `punteggio` delle carte ≈ `punteggio_totale` ufficiale, tolleranza
  ±0,5.

### Arene Limited — Beginner, Cap 220, Cap 260, Uncapped

Campi propri: `tipo` (beginner|cap220|cap260|uncapped), `gold` (bool),
`gw`, `costo_ingresso`, `rank` (piazzamento), `punteggio_totale`, `premio`
(se preso, dal `rewardsConfig` VERO, jackpot incluso), `premio_netto`
(`premio - costo_ingresso`).

Check di validazione: `max_classic=None` (nessun tetto sulle Classic),
`bonus_xp=0`, `bonus_capitano=+20%`, carte rare ammesse=sì, numero carte
formazione=**5**.

**Come si riconosce il `tipo` dallo slug della leaderboard** (nessuna
chiamata dedicata, si guarda la stringa):
- contiene `arena_limited_beginner` → `beginner`
- contiene `arena_limited_uncapped` → `uncapped`
- contiene `arena_limited_cap_220` → `cap220`
- contiene `arena_limited` col prefisso `all_star` → `cap260`
- contiene `arena_limited` ma il prefisso lega NON è `all_star` →
  **"division", ESCLUSA** (arena dedicata a un campionato, non estratta)

**Formazioni con 0/DNP**: un giocatore che non ha giocato prende `0.0`
(prima Sorare scriveva "DNP" testuale, oggi lo stesso evento produce un
punteggio 0.0 esatto — stesso trattamento). Come si tratta dipende dal
binario:
- **Binario 1** (M vs G vs A, formazione fissa): si esclude la
  **formazione intera** — l'unità è il confronto a parità di formazione,
  non ha senso salvare le altre 4 carte buone se non si può isolare
  l'effetto del DNP sulla decisione entra/salta.
- **Binario 2** (G vs A, pool libero): si esclude **solo la carta**
  dal pool — l'unità è la selezione, si salvano le altre 4.

### Da7 (All Stars 7, Under 23) e In Season

Estratte solo per `manager_crowss/`, non fanno parte dello scope dei
binari 1/2 (decisione utente 10/08: "sulle altre competizioni diventano
un bordello"). Restano nell'archivio come materiale storico/di controllo,
non toccate da questo README oltre a questa nota.

---

## Come rilanciare un'estrazione — ricetta pratica

Script: `estrai_archivio_manager.py` (ex `estrai_archivio_crowss.py`,
generalizzato 10/08/2026). Riusa `ricostruisci_manager.partecipazioni()`/
`.formazione()` (query pubbliche tranne l'indice, che serve il cookie) e
la query `rewardsConfig` per i premi veri (sessione anonima).

```
SORARE_COOKIE=... python estrai_archivio_manager.py --manager <slug> fixture1 [fixture2 ...]
```

`--manager` default `crowss`. Per crowss scrive in
`manager_crowss/pre_2026-08-07/` o `dal_2026-08-07/` a seconda della data
della fixture rispetto al taglio; per qualunque altro manager scrive
direttamente in `manager_<slug>/`, senza sotto-cartelle.

**Controllo di coerenza sempre**, su OGNI riga prima di scriverla: somma
`punteggio` delle carte vs `punteggio_totale` ufficiale, tolleranza ±0,5.
Se lo scarto è enorme, è il pattern "annullata" — vedi sopra.

**Costo**: tempo di rete dominato dal rate limit di Sorare, non dalla
CPU — ~15 minuti per 220 formazioni misurato il 10/08. Ottimizzazione nota
non ancora implementata: raggruppare `formazione()`/premi con alias
GraphQL invece di una richiesta a query (fattore 10-15x in meno di
richieste HTTP) — vedi backlog in memoria di sessione.

**Grade**: completare SEMPRE dopo un'estrazione nuova con
`analisi_manager/completa_grade_mancante.py` (procedura standard, scrive
in un indice condiviso persistente, beneficio permanente per ogni backtest
futuro — non solo per l'estrazione appena fatta).
