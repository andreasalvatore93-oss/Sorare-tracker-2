# Handoff sessione 26/07/2026 (modello predittivo formazioni MLS) — per continuare su un altro account

**Scritto per essere letto da zero, su un account Claude diverso da quello che ha fatto questo
lavoro** (l'utente alterna più account/sessioni). Sessione molto lunga e densa — non presupporre
nessun contesto pregresso, tutto quello che serve per continuare è qui dentro. Se la run di
validazione finale menzionata in fondo non è ancora conclusa quando leggi questo file, controllala
per prima cosa (istruzioni nella sezione "Cosa fare per primo").

Repo: `Sorare-tracker-2` (github.com/andreasalvatore93-oss/Sorare-tracker-2), cartella locale
`C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2`, branch `main`. **Tutto quello descritto qui è
già committato e pushato su `origin/main`** salvo diversa indicazione esplicita — verificare
comunque con `git log`/`git status` invece di fidarsi ciecamente, l'utente ha anche un bot di
trading (`bots/bot_definitivo.py`) che committa periodicamente in background su un filone
INDIPENDENTE e non correlato a questo lavoro (non confonderlo).

**Documenti collegati, da consultare per il dettaglio tecnico completo** (questo handoff riassume,
loro hanno il dettaglio):
- `docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` — sezioni 7-11, handoff tecnico dettagliato
  di questa sessione specifica (formula level_score, floor, tutti i casi reali validati).
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` — documento "vivo" permanente, architettura
  completa del tool e sua storia (sezioni 9-11 per gli sviluppi recenti).

## 1. Cos'è il progetto (riassunto minimo)

Tool che, dati i giocatori MLS posseduti dall'utente su Sorare (fantasy calcio NFT), calcola per
ognuno dei 4 ruoli (GK/DEF/MID/FWD) uno score atteso per la prossima partita e fonde i migliori in
N formazioni ottimali. Script principali: `formazione_mls/predict/test_gk.py` / `test_def.py` /
`test_mid.py` / `test_mls_fwd_all.py` (un giocatore per invocazione, matrix job su GitHub Actions),
`formazione_mls/build_formazione_finale.py` (fonde i 4 consigli di ruolo). Pipeline completa:
`.github/workflows/formazione_completa.yml` (workflow_dispatch, input `num_formazioni`).

**Vincolo non negoziabile del progetto**: nessuna automazione che rischia soldi reali (acquisti
diretti). Questo tool è puramente consultivo (suggerisce, l'utente schiera a mano).

## 2. Cosa è successo in QUESTA sessione, in ordine cronologico

### A. Calibrazione allargata (notte 25→26/07, completata e ufficializzata)
Grid search su tutti i giocatori MLS qualificati (non solo posseduti), pesato per numero di
partite di backtest per giocatore (fix: giocatori con 1-3 partite pesavano quanto quelli con 9,
inquinando la media). Risultato ufficiale in produzione: **DEF/MID/FWD usano
`half_life≈9-12` (specifico per ruolo), `opponent_sensitivity=29.0`, `trend_intensity=0.7`, SENZA
fattori granulari**. Validato con un confronto A/B reale (caso Antino Lopez/Carles Gil).
**GK NON aggiornato in produzione** (resta `hl=9.0, range=1.6, opp_sens=20.0, trend=0.7`) — il
campione di calibrazione è cresciuto da 3 a 13 giocatori ma il bootstrap resta debole (12.2%
win-rate), da rivalutare quando la stagione MLS avrà prodotto più partite per giocatore.

Poi, allargata ulteriormente la soglia qualità di calibrazione a 15 (solo per calibrazione, non
per produzione) con batch lanciati SEMPRE IN SEQUENZA mai in parallelo tra ruoli (rischio concreto
di 429 condiviso con l'account reale se 4 ruoli x 8 worker martellano insieme l'API Sorare —
l'utente è intervenuto una volta per farlo correggere, vedi promemoria in sezione 5). Fix
preventivo in `.github/workflows/grid_search_calibrazione.yml`: esclude i giocatori con
`grid.json` già presente prima di applicare batch_index/batch_size (permette di riabbassare la
soglia senza rifare query sui già processati).

### B. Scoperta e rimozione delle categorie granulari a peso zero (commit `f145fa822`)
Nuovo script diagnostico `formazione_mls/diagnostics/inspect_granular_weights.py` (locale, legge
le cache `.cache/*_detail_cache.json` già scaricate, nessuna query nuova): misura il peso reale di
ogni categoria granulare sul movimento del punteggio, su migliaia di partite reali per tutti e 4 i
ruoli. Trovato che "Eventi rari" vale 0.0-0.1% ovunque (rumore puro) — rimosso dal codice. Per GK
rimossi anche "Falli" ed "Efficacia offensiva" (0.0% anche loro). Rimozione sicura: questi gruppi
erano già esclusi da `score_atteso` per DEF/MID/FWD (decisione presa la notte precedente) e sempre
stati esclusi per GK — nessun cambio di comportamento reale, solo pulizia.

### C. SCOPERTA PRINCIPALE DELLA SESSIONE: la formula esatta di `level_score` (commit `5a0da4074`, `d6ffb182e`, `f8d98da0c`, `2d8a0c399`)

Lo stesso script diagnostico aveva rivelato che il campo `level_score` (category=UNKNOWN nel
`detailedScore` dell'API Sorare) vale da solo **41-63% del punteggio totale** in tutti e 4 i
ruoli — molto più di qualunque categoria granulare tracciata — ma non era mai stato analizzato a
fondo. Guidati dall'utente (che ha usato Sorare aperto per verificare ogni ipotesi con casi reali,
via popup di conferma — pattern molto efficace, vedi [[feedback-verifica-con-casi-reali-sorare]]
nella memoria persistente), abbiamo trovato la **regola esatta e completamente deterministica**:

```
netto = sum(statValue di tutte le righe POSITIVE_DECISIVE_STAT del detailedScore)
      - sum(statValue di tutte le righe NEGATIVE_DECISIVE_STAT del detailedScore)
      (gol, assist, clean sheet per GK, tackle da ultimo uomo, rigore parato/causato,
       cartellino rosso, autogol, errore-che-porta-a-un-gol... — un valore per evento,
       una doppietta conta 2, ecc.)

netto -2 -> level_score  5
netto -1 -> level_score 15
netto  0 -> level_score 35   (BASE, chiunque scenda in campo anche un secondo)
netto +1 -> level_score 60
netto +2 -> level_score 70
netto +3 -> level_score 80
netto +4 -> level_score 90
netto +5 -> level_score 100
```

`level_score` corrisponde letteralmente al **"Punteggio decisivo"** mostrato nella UI Sorare (il
gauge -3..+5 con soglie 0/15/35/60/70/80/90/100). Il "Punteggio complessivo" della UI corrisponde
esattamente alla somma dei nostri gruppi granulari. **`score_totale_reale = level_score +
somma_granulari`**, con UNA REGOLA DI FLOOR importante (scoperta dal caso reale Erling Haaland,
screenshot dell'utente):

```
se level_score >= 60 (almeno un evento decisivo positivo netto):
    score_totale = MAX(level_score, level_score + granulari)   <- FLOOR ATTIVO
altrimenti (level_score <= 35):
    score_totale = level_score + granulari                      <- nessun floor
```

Un evento decisivo positivo garantisce quindi un "pavimento" di punteggio (60/70/80...)
indipendentemente da quanto sia negativo il resto della partita — un gol, ad esempio, non può mai
essere "annullato" da una brutta prestazione generale nello stesso match. Verificato su decine di
casi reali (nei dati cache) e su **9 casi puntuali confermati dall'utente confrontando Sorare
aperto**: Erling Haaland, Aaron Salem Boupendza Pozzi, Denis Bouanga, Antony Alves Santos, Andre
Blake, Michael Collodi, Pablo Sisniega, Akil Watts, Ajani Fortune — copre tutti e 4 i ruoli.

**Nota importante segnalata dall'utente**: `goals_conceded` (gol subiti) NON è mai un evento
decisivo negativo per il portiere — è una statistica GENERAL separata. Un portiere con un evento
decisivo positivo (es. rigore parato) ma tanti gol subiti prende comunque il livello raggiunto
grazie al floor.

**Implicazione per il futuro** (non ancora implementata): stimare la probabilità storica di
ciascun evento decisivo per il giocatore (tasso gol/partita, tasso clean sheet, ecc.) per calcolare
un `level_score` atteso, invece di lasciarlo dentro la media storica generica del punteggio totale.

### D. Tema correlazione GK-DEF: sinergia/anti-sinergia nella scelta della formazione (commit `d41016634`, `5b02ef134`)

L'utente ha proposto una soluzione "a monte" (non una stima di probabilità condivisa complessa):
risolvere il problema nella SCELTA dei candidati in `build_formazione_finale.py`, non nella
formula di score. Regola decisa insieme:
- **Anti-sinergia FORTE**: un MID/FWD (titolare o extra) la cui squadra è l'AVVERSARIA del
  portiere scelto è fortemente sconsigliato — implementato come penalità grande nell'ordine di
  scelta (mai un'esclusione assoluta, resta selezionabile come ultima risorsa se non ci sono
  alternative).
- **Sinergia positiva DEBOLE**: un DEF della STESSA squadra del portiere riceve un piccolo bonus
  nell'ordine di scelta (incoraggiata ma non obbligatoria, non ribalta differenze di punteggio
  importanti — un 0-0 contro l'avversario del portiere resta possibile).

**Prerequisito tecnico risolto**: `build_formazione_finale.py` non aveva MAI avuto informazioni su
squadra/avversario per nessun giocatore (solo slug+punteggio). Aggiunta la plumbing completa:
`test_<ruolo>.py` calcola già `player_team_slug`/next opponent (dato di CALENDARIO, noto con
largo anticipo, a differenza delle starter odds che compaiono solo 2-3 giorni prima) → esportato
in una nuova riga "SQUADRA: x | AVVERSARIO: y" nei file di output → letta e propagata da
`formazione_mls/consiglio/build_consiglio_<ruolo>.py` → letta da
`build_formazione_finale.py::parse_consiglio()` → usata da `synergy_adjusted_rows()`/
`synergy_sort_key()` per riordinare i candidati dopo aver scelto il portiere.

**Verificato con test sintetici** (non ancora con un caso reale che attivi visibilmente la regola
— vedi sezione 4): comportamento normale, caso "ultima risorsa" (candidato unico da squadra
avversaria resta selezionabile), retrocompatibilità totale se manca il dato squadra (comportamento
identico a prima). **Validato anche su una run di produzione reale** (run #6,
`formazione_finale_run6_2026-07-26_095254.txt`): la plumbing funziona end-to-end, ma nessuna delle
5 formazioni generate presentava un vero conflitto GK/avversario tra i giocatori posseduti — la
regola non ha ancora avuto l'occasione di "scattare" visibilmente su dati reali, ma il codice è
verificato corretto.

### E. Filtro attività minima nella discovery di produzione (commit `0da61d537`)

Richiesta esplicita dell'utente dopo aver controllato a mano la propria galleria Sorare: filtrare
i giocatori posseduti con media 0 nelle ultime 5 partite ("carte morte" mai schierabili) taglia
circa 80 giocatori inutili, risparmiando un intero job predict (checkout+setup+15-30 query) per
ognuno. Nuovo `filter_by_activity()` in tutti e 4 gli `mls_<ruolo>_discovery.py` (SOLO produzione,
NON tocca la discovery globale usata per la calibrazione): scarta uno slug SOLO se la sua media
ultime 5 è disponibile ED è <= `MIN_ACTIVITY_SCORE` (default 0.0, deliberatamente molto basso). Se
il dato manca, il giocatore è TENUTO per sicurezza (stesso principio del filtro starter-odds già
esistente). Applicato PRIMA del filtro starter-odds. **Non ancora testato su una run reale** —
richiesto esplicitamente dall'utente "per la prossima run", non per quella già in corso al momento
dell'implementazione.

### F. Stadio A del tema level_score: decomposizione diagnostica (commit `eed1f15b1`)

In tutti e 4 gli script: nuova `extract_level_score()` + calcolo di DUE medie pesate SEPARATE
(stesso half-life già in uso) invece di una sola media sul punteggio totale mescolato:
`media_level_score_pesata` (storico del "Punteggio decisivo") e `media_granulari_pesata` (storico
del resto). Solo diagnostico (nuova riga di log "di cui..."), NON entra in `score_atteso`.
Verificato che le due medie sommate coincidono esattamente con la media totale (linearità della
media pesata). **Validato su una run di produzione reale**: le nuove righe compaiono correttamente
con numeri sensati su tutti e 4 i ruoli (es. Matt Turner GK: decisivo medio 40.03, granulari medio
12.63).

### G. Stadio B del tema level_score: range a percentili pesati (commit `c904d158d`)

Nuova `weighted_percentile()` in tutti e 4 gli script: calcola percentili pesati (16°/84°,
equivalenti a ±1 deviazione standard per una normale) direttamente sullo storico REALE dei
punteggi, invece di assumere una distribuzione a campana come fa oggi `range_conf` (media ±
deviazione standard × `RANGE_MULTIPLIER`). Motivazione: il punteggio di un giocatore può essere
BIMODALE (grappolo basso senza eventi decisivi, grappolo alto quando ne scatta uno) — media±std in
quel caso produce un range che cade spesso in una "zona morta" tra i due grappoli, un valore mai
osservato nella realtà. Verificato con test sintetico su un caso bimodale (12 partite ~35-45 + 3
partite ~65-75): range media±std = [35.2-63.5] (zona morta), range percentili 16-84 = [37.0-70.0]
(tocca correttamente il grappolo alto). Solo diagnostico per ora (nuova riga "Range a percentili
pesati"), NON sostituisce ancora `range_conf`.

**NON ANCORA VALIDATO su dati reali di produzione** — questo era il prossimo passo in corso al
momento di scrivere questo handoff, vedi sezione 4.

## 3. Stato ATTUALE della produzione (riassunto per orientarsi subito)

| Ruolo | half_life | range_mult | opp_sens | trend | granulari | Fonte |
|---|---|---|---|---|---|---|
| GK | 9.0 | 1.6 | 20.0 | 0.7 | NO | invariato, campione ancora troppo piccolo |
| DEF | 12.0 | 1.2 | 29.0 | 0.7 | NO | calibrazione allargata ufficializzata |
| MID | 12.0 | 1.4 | 29.0 | 0.7 | NO | calibrazione allargata ufficializzata |
| FWD | 9.0 | 1.4 | 29.0 | 0.7 | NO | calibrazione allargata ufficializzata |

- **Filtro qualità produzione** (discovery, giocatori posseduti): NESSUNO storicamente, ora anche
  filtro attività minima (media L5 > 0) + filtro starter-odds (>= 60%, con fallback "tenuto" se
  dato mancante).
- **Sinergia/anti-sinergia GK-DEF**: attiva in `build_formazione_finale.py`.
- **Stage A/B (level_score)**: solo diagnostici, non toccano `score_atteso`/`range_conf`.
- **Nessuna modifica ai bot di trading** (`bots/`) in questa sessione — filone indipendente.

## 4. COSA FARE PER PRIMO quando riprendi

1. **Controlla lo stato del run di validazione Stage B**: run id `30197884204` (workflow
   `formazione_completa.yml`, input `num_formazioni=1`), lanciato per vedere le nuove righe
   "Range a percentili pesati" su dati reali e confrontarle con il range media±std attuale.
   ```
   gh run view 30197884204 --json status,conclusion
   ```
   Se ancora in corso, aspetta (`gh run watch 30197884204` o polling). Se completato:
   ```
   git pull --rebase origin main
   grep -rl "Range a percentili pesati" formazione_mls/output/mls_*_all/prediction_*.txt
   ```
   e confronta per un paio di giocatori il range vecchio (`Deviazione standard pesata`, usato per
   `range_conf` = dev_std × RANGE_MULTIPLIER) con quello nuovo (percentili 16-84) per vedere se
   sono molto diversi o simili nella pratica.

2. **Decidi con l'utente** (NON farlo autonomamente, cambia comportamento di produzione) se
   sostituire `range_conf` con il range a percentili, sulla base di quanto visto al punto 1.
   Ricorda: "un tema alla volta", scegliere insieme prima di implementare (vedi
   [[feedback-lavoro-un-tema-alla-volta]] in memoria).

3. **Poi**, tra i prossimi temi possibili (chiedere all'utente quale preferisce, non scegliere da
   soli):
   - **Stadio C** del tema level_score: condizionare la probabilità di evento decisivo per
     avversario/venue — il pezzo più corposo e concettualmente collegato al tema correlazione
     (Finding 3+F originale, condizionamento 2D venue+forza avversario, mai completato).
   - **Verificare il filtro attività minima** (punto E sopra) su una run reale — non ancora
     testato, l'utente ha chiesto esplicitamente di aspettare "la prossima run".
   - **GK**: ricalibrare quando ci sarà più storico di stagione (bootstrap ancora debole, 12.2%
     win-rate anche con 13 giocatori).
   - Altri temi backlog mai affrontati: feature aggiuntive (infortuni, calendario congestionato),
     gestione outlier/hot-streak (caso Antino Lopez come test case), monitoraggio MAE live in
     produzione, estensione dell'infrastruttura ad altri campionati oltre MLS.

## 5. Promemoria di collaborazione (workflow consolidato in questa sessione)

- **Io committo e pusho direttamente** (`git add`/`commit`/`push`), workflow consolidato in questa
  sessione — non serve chiedere permesso per commit/push di codice testato, ma va sempre fatto
  `git pull --rebase origin main` PRIMA di ogni push (il repo riceve commit automatici frequenti
  da CI: bot di trading, workflow di calibrazione).
- **MAI lanciare batch di calibrazione in PARALLELO su ruoli diversi** — rischio concreto di 429
  condiviso con l'account reale dell'utente (fino a 32 job CI × query simultanee). Sempre in
  sequenza, un ruolo alla volta, aspettando il completamento prima di lanciare il successivo.
- **Verificare ogni fix con `py_compile` + smoke test sintetico prima di committare** — pattern
  ripetuto per ogni modifica di questa sessione, mai saltato.
- **L'utente vuole essere consultato prima di lanciare nuovi workflow GitHub Actions** (query API
  reali, possibile 429 se sta usando l'app Sorare in parallelo) — chiedere conferma, non lanciare
  autonomamente batch grandi. Run singole di validazione (num_formazioni=1) sono generalmente OK
  se già discusse.
- **"Un tema alla volta"**: dopo un brainstorm, l'utente sceglie esplicitamente il prossimo tema —
  non procedere in autonomia su più fronti.
- **Verifica con casi reali Sorare**: per capire meccaniche di gioco non ovvie, preparare casi
  concreti (slug, data, avversario) e chiedere conferma via popup invece di fidarsi solo
  dell'analisi statistica — pattern estremamente produttivo in questa sessione (ha portato alla
  scoperta della regola esatta di level_score).
- **Non aggiornare `docs/RIASSUNTO_*`/handoff dopo ogni singolo passo** — solo a fine sessione o
  checkpoint importanti (questo file è esattamente quel checkpoint).
- Tutte queste preferenze sono salvate anche nella memoria persistente dell'utente (file
  `feedback_*.md` in `C:\Users\Andrea\.claude\projects\...\memory\`), consultabile se disponibile
  nell'account che riprende.

## 6. File chiave per orientarsi rapidamente

- `formazione_mls/predict/test_gk.py` / `test_def.py` / `test_mid.py` / `test_mls_fwd_all.py` —
  formula di scoring, Stadio A/B diagnostici, `extract_level_score()`, `weighted_percentile()`
- `formazione_mls/diagnostics/inspect_granular_weights.py` — diagnostico peso categorie granulari
  (locale, riusa le cache già scaricate)
- `formazione_mls/discovery/mls_<ruolo>_discovery.py` — discovery produzione (posseduti), ora con
  `filter_by_activity()`
- `formazione_mls/consiglio/build_consiglio*.py` — fonde i prediction_*.txt in consiglio_*.txt,
  ora propaga anche squadra/avversario
- `formazione_mls/build_formazione_finale.py` — fusione finale, `synergy_adjusted_rows()`/
  `synergy_sort_key()` per la sinergia GK-DEF
- `formazione_mls/calibrazione/aggregate_grid_search.py` / `bootstrap_stability.py` —
  aggregazione cross-player pesata per n_test + verifica di stabilità statistica
- `docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` sezioni 7-11 — dettaglio tecnico completo di
  questa sessione (formula level_score con tutti i casi reali, regola del floor)
- `docs/RIASSUNTO_EVOLUZIONE_TOOL_FORMAZIONI.md` — architettura permanente, aggiornare quando il
  modello evolve ulteriormente (non duplicare)
