# HANDOFF — Funzione "Best Five" (K League, pilota)

Scritto il 30/07/2026 sera, a fine sessione. **Questo file esiste perché la prossima sessione
potrebbe partire da un account Claude diverso, senza accesso alla memoria automatica di questa
sessione** — tutto il contesto necessario per continuare deve stare qui, non altrove. Leggerlo
per intero prima di agire.

## Cos'è "Best Five"

Funzione richiesta dall'utente (30/07): per UNA lega scelta (test pilota: **K League**), trovare
la miglior formazione POSSIBILE scegliendo tra TUTTE le carte disponibili nella lega (non solo
quelle possedute dall'utente), con "copie di backup" per ogni ruolo (titolare + N backup, nel
caso il titolare scelto non scenda in campo quella giornata).

Script separato e READ-ONLY rispetto alla pipeline di produzione (`formazione_giornata.yml`) —
non tocca budget/anti-stack/sinergie/multi-lineup, quello resta specifico delle formazioni REALI
sui posseduti.

## Cosa è stato implementato (30/07, questa sessione)

1. **`PLAYER_POOL=global|posseduti`** (default `posseduti`), aggiunto e scollegato da
   `CALIBRATION_MODE` in tutti e 4 gli script K League:
   `formazione_kleague/predict/test_{gk,def,mid,fwd=test_mls_fwd_all}.py`.
   Quando `PLAYER_POOL=global`, `DISCOVERY_FILE` punta al pool GLOBALE
   (`formazione_kleague/output/kleague_<ruolo>_discovery_global/player_slugs.json`, tutti i
   giocatori della lega) invece che ai posseduti — SENZA attivare il grid search
   (`CALIBRATION_MODE` continua a implicare il pool globale come prima, comportamento invariato
   per la ricalibrazione — nessuna regressione lì).

2. **`best_five.py`** (nuovo file, root del repo). Orchestratore via **subprocess** (non import
   diretto — più sicuro, zero refactoring dei moduli `test_<ruolo>.py` che eseguono codice a
   livello di modulo). Uso:
   ```
   python best_five.py kleague --run --backups 2
   ```
   Con `--run` lancia ogni `test_<ruolo>.py` con `PLAYER_POOL=global` sull'**intero** pool della
   lega (nessun `TARGET_SLUG` → lo script interno processa tutti i candidati in sequenza), poi
   fa il parsing del riepilogo comparativo già scritto in cima a `prediction_all_*.txt` (stesso
   `ORDINAMENTO` senza shrinkage già calcolato dallo script sorgente — zero duplicazione di
   logica di scoring) per estrarre titolare + N backup per ruolo. Report finale salvato in
   `formazione_kleague/output/best_five/best_five_<timestamp>.txt`.

3. **Persistenza del quality score in discovery** (fase 2, ottimizzazione tempi — vedi sotto):
   modificato `filter_by_quality()` in tutti e 4 gli script
   `formazione_kleague/discovery/kleague_{gk,def,mid,fwd}_discovery_global.py` per ritornare
   `(kept, quality_map)` invece di solo `kept`; `main()` ora scrive anche `player_quality.json`
   (`{slug: avg_score}`, media L5+L10+L40/3 già calcolata per il filtro qualità esistente,
   `MIN_AVG_SCORE_QUALITY=30.0`) accanto a `player_slugs.json` (quello resta invariato,
   retrocompatibile). **Zero chiamate API aggiuntive** — il valore era già calcolato e prima
   veniva solo scartato.

`py_compile` pulito su tutti i file toccati. Parser di `best_five.py` testato con un file
sintetico che riproduce esattamente il formato del riepilogo — funziona.

## STATO DEI CALCOLI — GK e DEF PRONTI E COMMITTATI, MID e FWD DA FARE

**Questa sessione (30/07) ha eseguito IN LOCALE `python best_five.py kleague --run --backups 2`,
avviato alle 14:08:58 UTC.** Su richiesta esplicita dell'utente il run è stato **fermato
volontariamente a metà del ruolo MID** (non un crash, non un timeout — l'utente ha detto "fermo
con mid" per poter chiudere la sessione e passare il testimone), e questa sessione ha
**committato e pushato** i risultati dei ruoli già completati prima di chiudere:

- **GK: COMPLETATO** (22/22 giocatori) — output in
  `formazione_kleague/output/kleague_gk_all/` (prediction, cache, grid_search), **committato e
  pushato su main**.
- **DEF: COMPLETATO** (97/97 giocatori) — output in
  `formazione_kleague/output/kleague_def_all/`, **committato e pushato su main**.
- **MID: INTERROTTO A META'** (fermato a 11/85 giocatori, su richiesta esplicita, non un
  fallimento) — la cache parziale generata (11 giocatori) è rimasta SOLO in locale, **NON
  committata** (irrilevante, si può ignorare o cancellare: `test_mid.py` la ricostruirà/estenderà
  comunque da sola al prossimo run, la cache è puramente un'ottimizzazione, non richiede pulizia
  manuale).
- **FWD: MAI INIZIATO** (0/75).

**Rate osservato** (per calibrare le attese sul resto): GK molto veloce (~1m40s per 22 giocatori,
quasi tutto già in cache da una calibrazione precedente); DEF più lento (~22s/giocatore, meno
cache disponibile) — su 97 giocatori, DEF da solo ha impiegato **circa 35-40 minuti**. MID (85
giocatori) e FWD (75 giocatori) probabilmente simili a DEF in assenza di cache pregressa (la
cache di 11 giocatori per MID committata... anzi NON committata, vedi sopra, quindi da capo)
→ **stima 30-35 minuti per MID + 25-30 minuti per FWD, totale ~60-65 minuti residui.**

### Come riprendere (comando esatto)

Grazie al nuovo flag `--roles` aggiunto in questa sessione, **NON serve rifare GK/DEF**:

```
python best_five.py kleague --run --backups 2 --roles mid,fwd
```

Questo esegue SOLO `test_mid.py` e `test_mls_fwd_all.py` in modalità `PLAYER_POOL=global` (pool
completo, versione NON ottimizzata — vedi sezione sotto sui limiti dell'ottimizzazione). Il
ranking finale (`costruisci_best_five`) resta invece calcolato su **tutti e 4 i ruoli**, perché
legge sempre l'ultimo `prediction_all_*.txt` disponibile per ciascuno — per GK e DEF userà
automaticamente i file già committati da questa sessione, senza bisogno di rilanciarli.

Dopo che MID e FWD sono finiti, il report finale con tutti e 4 i ruoli si genera da solo alla
fine dello stesso comando (non serve un passaggio separato).

## Ottimizzazione dei tempi — SOLO PARZIALMENTE FATTA, non dare per scontato che sia pronta

L'utente ha chiesto esplicitamente (30/07 sera) di ridurre i tempi per l'uso futuro su GitHub
Actions, **prima di tutto riducendo il numero di candidati nel pool**. Decisione presa con
l'utente (via domanda a scelta multipla + correzione libera): combinare **pre-ranking per
qualità** (punto 3 sopra, quality score) con un **filtro starterOdds ≥ 0.70** sulla prossima
partita (soglia scelta esplicitamente dall'utente: prima proposta 0.80, poi corretta a **0.70**).
Motivazione utente: chi ha starterOdds ≥ 70% è "quasi certo di giocare"; sotto quella soglia è
"più rischioso e comunque non lo sceglierei/comprerei" — quindi filtrarli PRIMA della predizione
costosa non perde candidati che l'utente avrebbe scelto comunque.

**Stato onesto: SOLO IL PUNTO 3 SOPRA (persistenza quality score) È STATO SCRITTO.** Il resto
del design NON è implementato:

- ❌ **Non esiste ancora una query leggera per lo starterOdds della prossima partita.** Bozza
  già pensata (non testata):
  ```graphql
  query NextMatchStarterOdds($slug: String!) {
    anyPlayer(slug: $slug) {
      anyFutureGames(first: 1) {
        nodes {
          playerGameScore(playerSlug: $slug) {
            anyPlayerGameStats {
              ... on PlayerGameStats {
                footballPlayingStatusOdds { starterOddsBasisPoints reliability }
              }
            }
          }
        }
      }
    }
  }
  ```
  Va aggiunta come funzione in `best_five.py` (sessione HTTP minima; valutare se vale la pena
  riusare l'infrastruttura di retry/circuit-breaker già presente nei `test_<ruolo>.py` invece di
  duplicarla in piccolo).

- ❌ **`best_five.py` NON usa ancora il pre-ranking per qualità né il filtro starterOdds.** Oggi
  `--run` lancia SEMPRE l'intero pool (`PLAYER_POOL=global` sull'intero script, un subprocess che
  processa tutti i candidati internamente — il comportamento "lento" che sta girando in questo
  momento in locale). Il nuovo design richiede un cambio di architettura: invece di UN subprocess
  per ruolo che processa tutti i candidati, serve un LOOP di subprocess con
  `TARGET_SLUG=<slug>` (stile matrix della pipeline di produzione, vedi
  `.github/workflows/formazione_giornata.yml` riga ~261) **solo sui sopravvissuti** al prefilter
  qualità+starterOdds — stima: da 279 giocatori totali a forse 40-80 (top-K per ruolo ancora da
  decidere, poi filtrati per starterOdds ≥0.70).

- ❌ **`player_quality.json` non esiste ancora per il pool K League attuale** — va rigenerato
  rilanciando la discovery_global (es. `formazione_kleague/discovery/kleague_def_discovery_global.py`
  e gli altri 3) prima che il pre-ranking per qualità sia utilizzabile. Rilanciare la discovery
  NON dovrebbe costare query aggiuntive rispetto a un run normale di discovery (il valore quality
  era già calcolato prima, ora viene anche salvato) — ma è comunque un intero giro di discovery
  (roster squadre + media qualità per ogni candidato), non istantaneo.

- ❓ **Il valore di K (quanti candidati per ruolo tenere nel pre-ranking qualità) non è mai stato
  discusso con l'utente.** Solo la soglia starterOdds (0.70) è stata decisa. Andrebbe scelto un
  default ragionevole (es. 15-20) e/o chiesto all'utente, prima di considerare l'ottimizzazione
  "pronta all'uso".

**In sintesi, per chi riprende**: SE devi rifare il calcolo perché il run locale di questa
sessione non è arrivato in fondo, **NON aspettarti che sia già veloce** — l'ottimizzazione non è
completa. Puoi:
1. Rilanciare `python best_five.py kleague --run --backups 2` così com'è (~70-90 minuti,
   comportamento identico a quello che sta girando ora), OPPURE
2. Finire prima il pezzo mancante (query starterOdds leggera + rewiring di `best_five.py` per il
   loop TARGET_SLUG sui top-K prefiltrati) — più lavoro iniziale, ma poi i run futuri (anche su
   GitHub Actions, l'uso finale previsto) saranno molto più veloci, invece di ~70-90 minuti su
   279 giocatori.

**Prima di lanciare qualunque run su GitHub Actions**: c'è una regola esplicita dell'utente
(30/07, altra memoria di sessione non riportata qui per esteso ma da rispettare comunque) — **mai
lanciare una run Actions senza chiedere prima**, vale anche lavorando "in autonomia". Questo
vale anche per `best_five` quando/se verrà portato su CI.

## File toccati in questa sessione — COMMITTATI E PUSHATI su main

Codice:
- `formazione_kleague/predict/test_{gk,def,mid,fwd=test_mls_fwd_all}.py` (PLAYER_POOL)
- `formazione_kleague/discovery/kleague_{gk,def,mid,fwd}_discovery_global.py` (persistenza quality)
- `best_five.py` (nuovo, root del repo — incluso il flag `--roles`)
- `docs/HANDOFF_BEST_FIVE.md` (questo file)

Risultati (voluminosi ma committati apposta, per evitare che chi riprende debba rifare GK/DEF):
- `formazione_kleague/output/kleague_gk_all/` (prediction, `.cache/`, `.game_log_cache/`, `grid_search/`)
- `formazione_kleague/output/kleague_def_all/` (idem)

**NON committato** (lasciato locale, irrilevante):
- `best_five_run.log` (log di debug del run interrotto)
- Cache parziale di MID (11 giocatori, in `formazione_kleague/output/kleague_mid_all/`) — non
  vale la pena portarsela dietro, `test_mid.py` la ricostruisce da sola.

## Prossimo passo consigliato

1. **Lancia direttamente**: `python best_five.py kleague --run --backups 2 --roles mid,fwd`
   (stima ~60-65 minuti, vedi sopra). GK e DEF sono già pronti, non serve rifarli.
2. Se vuoi evitare quei 60-65 minuti, valuta prima di finire l'ottimizzazione (fase 2, vedi
   sezione sopra — query starterOdds leggera + rewiring `best_five.py` + rigenerare
   `player_quality.json`) — ma è lavoro non banale, non ancora iniziato oltre al punto 3.
   **Conferma con l'utente quale delle due preferisce**, non presumere.
3. **Prima di lanciare qualunque run su GitHub Actions** (non solo in locale): l'utente ha una
   regola esplicita, mai lanciare una run Actions senza chiedere prima, vale anche lavorando "in
   autonomia".
