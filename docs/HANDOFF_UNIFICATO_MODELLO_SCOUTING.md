# HANDOFF UNIFICATO — Modello Predittivo / Generatore Formazioni + Scouting Acquisti

**Questo è l'UNICO riassunto di riferimento per il tema "modello predittivo"
(= generatore formazioni, stesso strumento, nomi diversi per la stessa cosa)
e per il tema "scouting acquisti". Aggiornarlo, renderlo snello e digeribile
a ogni sessione — non crearne altri.** Regola fissata anche in CLAUDE.md.

Sostituisce e supera (non cancellati per storia, ma NON più da consultare
come riferimento corrente):
`docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` (8776 righe),
`docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md`, `docs/HANDOFF_BEST_FIVE.md`,
`docs/HANDOFF.md` e gli `HANDOFF_*_2026-08-04.txt` in `docs/handoff/`.

Ultimo aggiornamento: 04/08/2026.

---

## 1. Cos'è il progetto, in tre righe

L'utente (nickname Sorare **Crowss**) gioca a Sorare (fantacalcio con carte
NFT). Il repo contiene un **modello predittivo** che stima il punteggio di
ogni giocatore alla prossima partita, un **generatore di formazioni** che usa
quella previsione per costruire le formazioni ottimali su ~30 campionati, e
uno **strumento di scouting** che usa lo stesso modello per decidere cosa
comprare prima che le informazioni (starter odds) siano pubbliche. I due
strumenti condividono lo stesso "cervello" (previsione + calibrazione) e
**vanno sempre trattati insieme**: ogni modifica alla previsione, alla
calibrazione o alle soglie va verificata su ENTRAMBI (regola già in
CLAUDE.md). Il generatore ottimizza il mazzo posseduto, lo scouting decide
come il mazzo cresce — se divergono si comprano carte che poi non si
schierano bene.

Il modello è considerato **al suo tetto di formula**: il lavoro recente non
sta più migliorando `score_atteso`, ma misurando **dove va usato meglio**
(quali competizioni giocare, quando NON entrare, capitano, allocazione delle
carte) e **dove il modello sbaglia di più** (vedi §7).

---

## 1bis. LA CATENA DI PRODUZIONE — base di tutto, mai saltare un anello

```
VALORI DI PRODUZIONE (= predizione, stesso nome)
        |
        v
SOGLIE ARENA EFFICIENTI (pareggio/guadagno per punto)
        |
        v
TOOL SCOUTING (consiglio acquisti per una GW, basato sull'efficienza)
```

Se cambia un valore di produzione/predizione (formula, calibrazione,
parametro di un ruolo — qualunque cosa sposti `score_atteso`), le soglie di
efficienza delle arene (`PAREGGIO_ARENA`, `GUADAGNO_PER_PUNTO` in
`generatore_formazioni/build_formazione_globale.py`) NON si aggiornano da
sole: sono tarate su quei punti attesi, e vanno riverificate. Lo scouting a
sua volta consiglia gli acquisti proprio sull'efficienza (colonne
`Ess/GW`/`€/EssGW`, §2.2) — un cambio a monte non riverificato falsa i
consigli di acquisto a valle **in modo silenzioso**, senza nessun errore
visibile. Nessuna modifica alla produzione è chiusa finché non si è
ripercorsa la catena fino allo scouting incluso. Regola gemella anche in
CLAUDE.md.

## 2. I tre strumenti

### 2.1 Generatore di formazioni (il "modello predittivo")

Per ~30 campionati tracciati, dato l'elenco delle carte possedute
dall'utente, produce le formazioni ottimali per competizione (In Season,
Arena, All Stars, Under 23) con capitano, rispettando i vincoli Sorare (max 1
Classic, min 4 In Season nelle In Season; cap L10 nelle arene con cap).

**Pipeline di produzione** (workflow GitHub `formazione_giornata.yml`,
riscritta 27-28/07 sulla GIORNATA invece che sui singoli campionati):
1. `discovery_fixture.py` — dalle partite della giornata risolve squadre in
   campo, tiene solo le carte possedute di quelle squadre, applica la soglia
   starter-odds. ~3 minuti invece di ~30.
2. `predict` — SOLO per i giocatori sopravvissuti (matrice dinamica: un
   campionato senza titolari probabili non genera job).
3. `consiglio` — per lega/ruolo, nello stesso job del predict.
4. `generatore_formazioni/build_formazione_globale.py` — fonde tutti i
   consigli, costruisce le formazioni per priorità (In Season → Arene
   dedicate/All Stars → Under 23 → All Stars), assegna capitano, pubblica
   report HTML + notifica Telegram.

Architettura per-lega (esempio `formazione_mls/`, stesso pattern su tutte le
leghe): `discovery/` (posseduti + globale pubblica), `predict/`
(`test_gk.py`/`test_def.py`/`test_mid.py`/`test_mls_fwd_all.py`, uno script
per ruolo), `consiglio/`, `output/` (per ruolo/scopo: `_all` produzione,
`_calibration` isolata, `_discovery`/`_discovery_global`).

**Formula di previsione** (identica nella struttura su tutti i ruoli/leghe):
```
score_atteso = P(gioca) x media_pesata_esponenziale(N partite)
               x fattore_casa_trasferta x fattore_forza_avversario
               x fattore_trend
range_confidenza = +/- dev_std_pesata x RANGE_MULTIPLIER
```
GK ha in più il blend con P(clean sheet) di squadra (§7). I "fattori
granulari" per categoria di statistica Sorare (falli, duelli, passaggio...)
sono stati provati e **rimossi ovunque**: non battono la media pesata
semplice, vedi §8.

**Parametri di produzione attuali (MLS, propagati a tutte le leghe via
`propaga_modello.py` — mai a mano sulle singole leghe, vedi CLAUDE.md)**:

| Ruolo | half_life | range_mult | opp_sens | trend_int |
|---|---|---|---|---|
| GK | 6.0 | 1.15 | 29.0 | 0.0 |
| DEF | 30.0 | 1.1 | 29.0 | 0.0 |
| MID | 25.0 | 1.1 | 29.0 | 0.0 |
| FWD | 6.0 | 1.15 | 29.0 | 0.0 |

`trend_intensity` a 0.0 ovunque: misurato più volte, monotono verso il
peggio, chiuso definitivamente il 03/08. `opponent_sensitivity=29.0` è
l'unico parametro mai risultato instabile in nessun ruolo/lega.

### 2.2 Scouting acquisti (`scouting_gw.py`)

Risolve il problema opposto al generatore: il generatore parte dalle carte
POSSEDUTE, per COMPRARE serve sapere con giorni di anticipo chi scenderà in
campo, comprese carte non possedute — prima che Sorare pubblichi le starter
odds (24-48h dal kickoff).

Trovato che la query giusta è `searchPlayers` (la stessa della pagina
"Scouting" di Sorare): una query paginata, ~12 chiamate/7 secondi, porta già
L5/L10/L40, presenze, infortuni, proiezione Sorare, carte possedute e prezzo
minimo — sostituisce 75 query di roster + migliaia di scrematura.

Output: `generatore_formazioni/output/scouting_ultimo.html` (committato,
notificato su Telegram), colonne `Ess/GW` = `(atteso − 51.8) × 7.65`
(vantaggio in essenze a giornata su uno slot medio) e `€/EssGW` = prezzo
diviso essenze-GW, che è la colonna giusta per **ordinare** i candidati (il
valore in euro dell'essenza non serve a scegliere fra candidati, è un
fattore comune). Workflow `scouting_gw.yml`, input `gameweek`/`per_ruolo`/
`odds_min`/`predict`/`screma`.

Riusa la cache del generatore (stessa cartella `<lega>_<ruolo>_all`) e il
meccanismo di riuso previsione di Best Five: un giocatore con previsione già
scritta per la finestra della fixture corrente non rigenera nemmeno il job.

### 2.3 Best Five / Contender (`best_five.py`)

Per UNA lega (o N leghe unite per la competizione "Contender"), genera la
formazione ottimale scegliendo tra **tutte** le carte della lega, non solo
quelle possedute — usa **la stessa** `build_formazione_globale.py` della
produzione (bug storico: prima chiamava una funzione gemella mai eseguita in
produzione, corretto 31/07). Leghe con `discovery_global` pronta:
`LEGHE_SUPPORTATE` in `best_five.py` (mls, kleague, germania, austria,
croazia, germania2, scozia, portogallo, danimarca, argentina + le altre
propagate via `CONSIGLIO_DISCOVERY_FILE`, verificare prima di fidarsi).
Genera anche varianti "Cheapest"/"Ottimizzata valore" per budget limitato.
**Non lanciare mai una run standalone e una Contender sulla stessa lega in
parallelo**: scrivono sugli stessi file e si scontrano (vedi memoria
`feedback_no_run_concorrenti_stessa_lega`).

---

## 3. Le regole del gioco Sorare (nessuna deducibile dai dati — tutte date
dall'utente, fondamento di ogni calcolo)

**Arene**: 10 partecipanti, si paga un ingresso, i primi 3 vincono.

| tipo | ingresso | 1° | 2° | 3° |
|---|---|---|---|---|
| Beginner | 100 | 500 | 250 | 150 |
| cap 220 | 200 | 1000 | 500 | 300 |
| cap 260 (incl. dedicate a un campionato — stessa economia) | 300 | 1300 | 800 | 500 |
| uncapped | 300 | 1300 | 800 | 500 |
| elite (uncapped) | 800 | 4000 | 2000 | 1000 |

- Cap L10 (arene "cap 260"/"cap 220"): somma degli L10 delle 5 carte ≤ soglia.
  Uncapped/elite senza tetto — lì si schierano i fuoriclasse.
- Bonus arena: **solo capitano, +20%**. Nessun altro bonus (season/xp/scarcity
  ecc.) si applica in arena.
- **Le arene dedicate a un campionato** (MLS/K League/Belgio/...) hanno gli
  **stessi costo e premi** di una cap 260 normale — sono la stessa
  competizione, filtrata a un solo campionato. **Ora disattivate di default**
  nel generatore (§9).
- Fino a 3 proprie formazioni possono finire nello stesso pool da 10.

**In Season**: gratis, max 6 formazioni, min 4 carte In Season su 5. Due
meccanismi paralleli: **gradini** (340→500 essenze, 360→1000, 400→25€,
420→100€, 460→500€, uno solo conta a settimana) e **leaderboard** (una sola
formazione, ~3-6k manager, paga fino al ~500° a scalare).

**All Stars da 7 / Under 23**: gratis, nessun ingresso, pagano solo essenze,
difficili da vincere. Destinazione naturale delle carte che non superano il
pareggio di un'arena.

**Ciclo essenze**: 1000 essenze = 1 craft, produce SOLO carte In Season (mai
Classic). Arena → essenze → craft → carte In Season → competizioni in euro:
l'arena alimenta il gioco che paga in euro, misurarne il ROI in sole essenze
lo sottostima.

**Ruolo**: proprietà della CARTA, non del giocatore (Sorare può cambiare
ruolo lasciando alle carte già emesse quello vecchio).

**Bonus Sorare — si SOMMANO, non si moltiplicano** (verificato al centesimo,
04/08): `punteggio carta = grezzo × (1 + bonus_carta + bonus_formazione +
capitano)`. `bonus_carta` (season/collection/xp/scarcity/special
edition/active clubs/nationality/positions) e `bonus_formazione` (+2%
multi-club max 2 stesso club, +4% cap L10 sotto soglia, cumulabili) **solo in
In Season/All Star/Under 23, zero in arena**. Capitano +50% In
Season/All Star/Under 23, **+20% in arena**.

---

## 4. Dati costruiti (l'archivio su cui si misura tutto)

| file | contenuto |
|---|---|
| `dati_globali/arene_storico.json` | 673 arene reali dell'utente (giu 2025–lug 2026): tutti e 10 i punteggi, premi, piazzamento |
| `dati_globali/arene_formazioni.json` | 593 formazioni schierate: giocatore/carta/ruolo/capitano/punteggio |
| `dati_globali/manager_forever-young.json` | arene REALI di un altro manager (mazzo simile, non scelto per il risultato), 71 giornate, 3326 righe con carte |
| `dati_globali/manager_crowss.json` | arene di un manager Korea-centrico, 1332 formazioni usate nel filone capitano |
| `dati_globali/backtest_arene_cache/` | storico giocatori necessario per rigiocare le formazioni col modello |

ROI reale storico dell'utente: **+13.3%** (121.250 spese, 137.400 vinte),
39.7% a premio contro il 30% di un manager medio — **tutto a mano**, il
modello ha meno di due settimane di produzione, nessuna delle 673 arene è
una sua scelta: base di confronto pulita.

**Buco mai spiegato**: l'utente riporta 870 arene reali giocate in totale,
`arene_storico.json` ne ha solo 673 (~197 mancanti). Non ignorarlo se si
riprende il filone backtest.

---

## 5. Lo stato dell'arte — cosa è CHIUSO (non riproporre)

- **Fattori granulari per categoria statistica**: rimossi ovunque, non
  battono la media pesata semplice.
- **Trend recente** (`TREND_INTENSITY`): 0.0 su tutti i ruoli/leghe, monotono
  verso il peggio in ogni test.
- **`fattore_forza_avversario`**: era una costante inerte mai letta, poi
  riabilitata con dato pulito (29/07) — oggi in produzione, stabile.
- **`level_score` portiere binario**: CHIUSO su decisione utente (02/08). Il
  vero valore è 35.0 senza clean sheet / 60.0 con clean sheet, mai
  intermedio — il modello ne prevede uno continuo. Mitigato dal blend
  `GK_TEAM_CS_WEIGHT=0.5` con P(clean sheet) di squadra (lift misurato
  0.3%→9.4%, correlazione x3), non risolto del tutto: resta la leva più
  grande mai lasciata sul tavolo per il GK, richiederebbe più profondità.
- **Compressione di scala** (portiere 4.8x, DEF/MID/FWD 2.5-2.9x): il
  modello ORDINA bene dentro lo slot ma comprime la dispersione assoluta —
  il danno è FUORI dallo slot (fascia capitano, quale competizione, soglie
  d'ingresso), dove numeri di ruoli diversi si confrontano. Non risolto,
  misurato e documentato.
- **Bonus additivi vs moltiplicativi**: chiuso, la formula additiva è
  verificata al centesimo (§3).
- **Quote bookmaker come segnale**: CHIUSO su decisione utente 02/08 —
  infattibile/non copre tutti i campionati. Non riproporre.
- **Capitano DEF/MID/FWD**: 8 ipotesi testate su 3130 formazioni reali
  (bias di ruolo, volatilità, forma grezza L5/L10/L40, margine-soglia,
  stabilità per lega, favorita/sfavorita, combinazioni, profondità storico,
  rischio sostituito presto, ambiente gol partita) — **tutte chiuse,
  `pick_captain()` non va toccato**. Unico segnale mai vicino alla
  significatività: favorita/sfavorita (IC95% [-0.0015,+0.14]), riprovabile
  SOLO con altro campione reale.
- **Capitano per tipo di competizione** (arene vs classifiche grandi):
  nessuna prova che la regola debba cambiare. Segno concorde (favorire
  varianza) ma magnitudine trascurabile (+1.6 essenze su 245, IC quasi a
  zero) — il capitano cambia il premio in <2% delle arene.
- **Formazione concentrata per il capitano** (carta forte + riempitivi vs 5
  carte equivalenti): correlazione -0.006, indifferente.
- **Regole di decisione (allocazione, soglie a gradini)**: DIMOSTRATO (non
  solo misurato) che sono un vicolo cieco. Massimizzare il PREMIO atteso è
  identico a massimizzare i PUNTI attesi (5768/5768 confronti concordi,
  0 contraddizioni) perché l'incertezza sul totale formazione (σ=49.4 pt) è
  troppo grande perché la non-linearità del premio (a gradini per rank)
  conti in pratica. **La regola attuale del bot (massimizza i punti attesi)
  è già quella giusta.**
- **Arene dedicate per lega**: disattivate di default nel generatore (04/08,
  vedi §9) — non un filone di ricerca chiuso, una scelta operativa.

## 6. Il numero da portarsi via

```
10 punti attesi in più = +46.9 essenze attese per arena
```
~4.7 essenze per ogni punto di previsione guadagnato. Converte accuratezza
del modello in denaro: **l'unica leva rimasta è la PRECISIONE della
previsione**, non le regole di decisione (tutte misurate e chiuse, §5).

## 7. Da dove ripartire — il filone aperto

**Scomporre l'errore di previsione** (per ruolo, per lega, per fascia di
punteggio, per profondità di storico) per trovare dove si concentra e
attaccare quello — deciso con l'utente il 04/08 come prossimo passo.
`taratura_confronto_parametri.py` e la regola **MAE + correlazione + lift di
selezione insieme** (mai uno solo, vedi CLAUDE.md) restano il metro per
validare qualunque modifica.

Piste secondarie aperte, non urgenti:
- **Manager avversari come banco di prova più grande**: `forever-young` già
  scaricato per le arene; estendere ad altre competizioni e ad altri
  manager (`ricostruisci_manager.py <slug> --dalle-mie-arene`, ~12
  minuti/manager). Serve per tarare `PAREGGIO_ARENA` sulla dispersione VERA
  delle formazioni scelte (51.0 osservato contro 43.3 delle sintetiche —
  segnale che le soglie attuali sono un po' ottimiste, campione ancora
  troppo piccolo per agire).
- **Tabelle premi delle competizioni a classifica grande** (All Star,
  Limited, LALIGA...): mancano, senza non si può chiudere il lato capitano/
  allocazione per quelle competizioni con premi veri invece di un surrogato
  rank-based.
- **Norvegia**: mai tracciata, richiede pipeline da zero, rimandata su
  richiesta utente.
- **CONSIGLIO_DISCOVERY_FILE**: patch che allinea Best Five alla produzione,
  applicata solo a 10 leghe, restano ~20 minori da verificare/propagare.
- **APIKEY Sorare**: richiesta, mai arrivata. È il tetto che decide i tempi
  di scouting/backtest/ricostruzione manager (senza: ~60 query/min,
  complessità 500; con: 30.000 e profondità 13).

---

## 8. Trappole già cadute — da non ricascarci

1. **I punteggi di classifica Sorare includono già il capitano moltiplicato**
   — sommare gli `atteso` grezzi sottostima ogni formazione di 12-15 punti.
2. **Fino a 3 formazioni nello stesso pool arena**: la chiave di identità è
   `contender_slug`, mai `(giornata, arena)` (75 ingressi veri persi come
   "duplicati" prima del fix).
3. **`so5LeaderboardGroups(groupType: COMPETITION_WITH_ARENA)` con
   `so5LeaderboardContenders(userSlug:)` sembra funzionare ma NON contiene le
   arene** — usare `so5Fixture(slug).userFixtureResults`, paginato.
4. **`groupType`, non `type`**: con l'argomento sbagliato Sorare risponde
   UNAUTHORIZED invece di un errore di validazione — la validazione GraphQL
   avviene prima dell'autenticazione.
5. **`searchPlayers`**: i nomi leggibili nella risposta sono ALIAS
   (`averageScore(type:...)`, non `lastTenPlayedSo5AverageScore`); `rarity`/
   `inSeason` non sono argomenti, passano da `refinements`.
6. **Il client conta**: la stessa query passa con il client di
   `scanners/bot_profit.py` (throttle globale) e viene respinta per
   complessità con altri client.
7. **Il valore del floor price non è un campo richiedibile**, solo un
   filtro — il prezzo esatto viene da `lowestPriceAnyCard(rarity:)`.
8. **Le carte non si clonano**: se ogni arena/formazione sceglie dal pool
   indipendentemente, le stesse carte migliori finiscono ovunque — sempre
   mazzo fisso nei backtest/ottimizzazioni multi-formazione.
9. **Col mazzo fisso i punti sono conservati**: un "oracolo" che massimizza
   i punti riallocando non ottimizza nulla di reale.
10. **displayName della leaderboard Sorare è l'unico dato autorevole** per
    mappare i tipi di arena — dedurlo dai nomi porta a mappature sbagliate
    (arena division ha lo stesso costo/premi di cap 260, non di Beginner).
11. **Rate limit è sull'ACCOUNT**, non sul job: parallelizzare query pesanti
    fa scattare i 429 prima, non le smaltisce più in fretta (ma job leggeri
    — poche decine di query l'uno — SI beneficiano di `max-parallel`, sono
    due situazioni diverse, non confonderle).
12. **Console Windows è cp1252**: crash silenzioso su nomi non latini, forzare
    UTF-8 sullo stdout.
13. **Permessi workflow**: senza `permissions: contents: write` un job può
    restare appeso ore in un retry-loop di push infinito senza segnalare
    nulla.

---

## 9. Ultima modifica di produzione (04/08/2026)

**Arene dedicate per lega disattivate di default.** Il generatore le
proponeva come più efficienti in base al punteggio atteso, ma senza sapere
se la giornata le rendeva davvero schierabili (es. In Season non attivo
quella GW) — l'utente le sostituiva comunque a mano con Arena All Stars 260.
`ARENA_LEAGUES` in `generatore_formazioni/build_formazione_globale.py` ora è
vuota di default; riattivabile con l'env/input workflow
`ARENA_LEAGUES_ENABLED` (`mls,kleague` o `tutte`), rispettando comunque il
vincolo di efficienza esistente (PRIORITY_ORDER + confronto atteso/pareggio).
Commit `ee4c2deec2`.

---

## 10. File chiave per orientarsi rapidamente

| file | cosa fa |
|---|---|
| `generatore_formazioni/build_formazione_globale.py` | il generatore vero, multi-lega, tutti i tipi di formazione |
| `formazione_mls/predict/test_<ruolo>.py` | la formula di previsione per ruolo (pattern riusato su tutte le leghe) |
| `formazione_mls/build_formazione_finale.py` | logica di fusione/capitano/anti-stack, riusata da Best Five |
| `scouting_gw.py` | scouting acquisti, query `searchPlayers` |
| `best_five.py` | Best Five / Contender |
| `propaga_modello.py` | unica via per propagare un cambio di modello a tutte le leghe |
| `taratura_confronto_parametri.py` | il metro ufficiale (MAE+correlazione+lift insieme) per ogni confronto di parametri |
| `ricostruisci_manager.py` | scarica arene/formazioni reali di un manager Sorare (pubblico) |
| `formazione_mls/diagnostics/` | tutti gli script diagnostici/backtest recenti (capitano, headroom, selezione carte, premio atteso) |
| `dati_globali/` | tutti gli archivi dati costruiti (§4) |

---

## 11. Come lavorare con l'utente (osservazioni ricorrenti)

- Ha ragione spesso quando un numero "non torna" col suo senso pratico — le
  regole di gioco non sono deducibili dai dati, vanno chieste.
- Fermarsi e chiedere a ogni dubbio invece di procedere per assunzioni.
- Leggere questo file (e il codice) prima di riproporre qualcosa: più
  filoni sono stati proposti due volte perché già chiusi e documentati.
- Un bias marginale forte non implica un buon criterio di scelta tra
  candidati della stessa decisione — misurare sempre la POLICY, non solo il
  bias astratto (costato diverse ipotesi false-positive nel filone capitano).
- Misurare il valore di una decisione PRIMA di cercare euristiche per
  migliorarla (headroom pavimento/caso/attuale/oracolo, §5-6).
