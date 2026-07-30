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

## Ottimizzazione dei tempi — SCRITTA E TESTATA (con dati sintetici), MAI TESTATA DAL VIVO

Sessione successiva (30/07, stessa giornata, nuova conversazione): completato il design che nella
sessione precedente era rimasto solo abbozzato. Decisione finale con l'utente sul K (quante carte
tenere nel pre-ranking qualità, mai discusso prima): **nessun cap per numero** — solo i due filtri
già decisi, quality score ≥30 (già applicato a monte in discovery, non serviva altro codice) e
starterOdds ≥0.70 (nuovo).

Cosa è stato scritto in questa sessione, tutto in `best_five.py`:

1. **`fetch_next_match_starter_odds(slug)`** — query GraphQL leggera (la bozza già pensata nella
   sessione precedente, verificata contro la struttura già in uso in `test_mid.py` per lo stesso
   campo `footballPlayingStatusOdds.starterOddsBasisPoints`). Sessione HTTP minima propria
   (curl_cffi se disponibile, altrimenti `requests`), NON riusa l'infrastruttura di retry/circuit
   breaker dei `test_<ruolo>.py` (scelta deliberata: la query è talmente piccola/economica che un
   retry semplice a 3 tentativi basta, non vale la complessità di condividere quello stato).

2. **`carica_pool_qualita_filtrato()`** — legge `player_slugs.json` della discovery globale. Nota
   importante scoperta in questa sessione: **il filtro qualità (`filter_by_quality`, media
   L5/L10/L40 ≥30) era GIÀ applicato in discovery PRIMA di questa sessione** — la persistenza
   scritta nella sessione precedente (punto 3, `player_quality.json`) salva solo il VALORE della
   media per ogni slug già filtrato, non introduce un filtro nuovo. Quindi `player_slugs.json`
   della discovery globale K League è GIÀ il pool filtrato per qualità — **non serve rigenerare
   nulla, non serve nemmeno `player_quality.json`** dato che non c'è un cap per numero (K) da
   applicare. Il punto 3 della sessione precedente resta comunque a posto/committato, semplicemente
   non serve altro lavoro su quel fronte.

3. **`prefiltra_starter_odds()`** — chiama la query leggera per ogni slug del pool, tiene solo chi
   ha odds ≥0.70. **Chi ha odds mancanti (nessuna partita futura fissata, dato non disponibile)
   viene ESCLUSO**, non tenuto per default — scelta esplicita fatta in questa sessione (non
   discussa esplicitamente con l'utente, ma coerente con la motivazione originale: un dato ignoto
   è rischioso quanto uno basso). Da rivedere se in pratica scarta troppi candidati con partita
   lontana non ancora quotata.

4. **Rewiring completo del loop di esecuzione**: `run_prediction_pool_prefiltrato()` sostituisce
   il vecchio `run_prediction_pool_globale()` — carica il pool, applica il prefiltro, poi lancia
   UN subprocess per slug sopravvissuto con `TARGET_SLUG=<slug>` (stile job matrix della
   pipeline di produzione), invece di UN subprocess che processa l'intero pool internamente.

5. **Parsing aggiornato per il nuovo formato di output**: con `TARGET_SLUG` impostato,
   `test_<ruolo>.py` scrive `prediction_<slug>_<timestamp>.txt` (un file per giocatore, come già
   fa la pipeline di produzione — vedi `formazione_kleague/consiglio/build_consiglio_mid.py` per
   il pattern equivalente già esistente in produzione) invece di un unico `prediction_all_*.txt`
   con il riepilogo comparativo di tutti insieme. `costruisci_best_five()` ora supporta ENTRAMBI i
   formati: se trova un `prediction_all_*.txt` (formato vecchio — es. GK/DEF K League già
   committati nella sessione precedente) lo usa e ha PRECEDENZA; altrimenti raccoglie tutti i
   `prediction_<slug>_*.txt` presenti e li aggrega/ordina lui (per `ORDINAMENTO` se presente,
   come già per DEF/FWD, altrimenti per `pt_attesi` come per GK/MID). Questo significa che GK/DEF
   già pronti da questa sessione precedente continuano a funzionare SENZA rilanciarli.

**Testato in questa sessione, solo con dati sintetici/dati già su disco (nessuna chiamata API
live)**:
- Parser del nuovo formato per-slug (`parse_file_singolo_slug` + `trova_output_per_slug`) — testato
  con 3 file sintetici, ranking per `pt_attesi` corretto.
- Retrocompatibilità col formato vecchio (`prediction_all_*.txt`) — testato sui file REALI già
  committati di GK e DEF K League, ranking confermato invariato (DEF usa correttamente
  `ORDINAMENTO`).
- `py_compile` pulito.

**NON testato — manca `SORARE_COOKIE` in locale in questa sessione** (l'utente non ce l'ha a
disposizione localmente): `fetch_next_match_starter_odds()` non è mai stata chiamata contro l'API
vera. Nessun run end-to-end (`--run`) di questa nuova architettura è mai stato lanciato, né in
locale né su GitHub Actions. **Il primo test reale sarà quindi il primo run vero** — possibile solo
via GitHub Actions (l'utente non ha il cookie in locale). Rischi noti da verificare al primo run
reale:
- La query leggera potrebbe avere un campo/struttura leggermente diverso da quanto assunto (mai
  eseguita, solo dedotta dalla query più grande già in uso in produzione per lo stesso campo).
- Il volume di sub-processi lanciati in sequenza (uno per slug sopravvissuto) potrebbe essere più
  lento del previsto per via dell'overhead di avvio Python per processo — da osservare sul primo
  run reale, non stimabile a tavolino.
- La regex `trova_output_per_slug` assume il timestamp nel nome file nel formato esatto
  `YYYY-MM-DD_HHMMSS` — coerente con quanto scrive `test_<ruolo>.py` (`datetime.utcnow().strftime`),
  ma non ancora verificato su un file vero generato da questa nuova modalità.

**Prima di lanciare qualunque run su GitHub Actions**: resta valida la regola esplicita
dell'utente — **mai lanciare una run Actions senza chiedere prima**, vale anche lavorando "in
autonomia". Questo vale anche per `best_five` quando/se verrà portato su CI o testato lì per la
prima volta.

## File toccati — COMMITTATI E PUSHATI su main (sessione precedente + questa)

Codice:
- `formazione_kleague/predict/test_{gk,def,mid,fwd=test_mls_fwd_all}.py` (PLAYER_POOL — sessione
  precedente)
- `formazione_kleague/discovery/kleague_{gk,def,mid,fwd}_discovery_global.py` (persistenza
  quality — sessione precedente, di fatto non serve più a valle vedi sopra)
- `best_five.py` (query starterOdds + rewiring completo per il prefiltro — QUESTA sessione,
  ancora da committare a fine sessione)
- `docs/HANDOFF_BEST_FIVE.md` (questo file)

Risultati (voluminosi ma committati apposta, per evitare che chi riprende debba rifare GK/DEF):
- `formazione_kleague/output/kleague_gk_all/` (prediction, `.cache/`, `.game_log_cache/`, `grid_search/`)
- `formazione_kleague/output/kleague_def_all/` (idem)

**NON committato** (lasciato locale, irrilevante):
- `best_five_run.log` (log di debug del run interrotto della sessione precedente)
- Cache parziale di MID (11 giocatori, in `formazione_kleague/output/kleague_mid_all/`) — non
  vale la pena portarsela dietro, `test_mid.py` la ricostruisce da sola.

## Prossimo passo consigliato

1. **Primo run reale della nuova architettura** (prefiltro starterOdds + loop TARGET_SLUG), MAI
   testato dal vivo in questa sessione per mancanza di `SORARE_COOKIE` in locale — va fatto su
   GitHub Actions: `python best_five.py kleague --run --backups 2 --roles mid,fwd` (GK/DEF restano
   quelli già pronti, formato vecchio, letti automaticamente). **Chiedere conferma esplicita
   all'utente prima di lanciare la run Actions** (regola esplicita, vedi sotto) — non è ancora
   stato chiesto in questa sessione.
2. Aspettarsi possibili intoppi al primo run vero (query mai eseguita contro l'API reale, vedi
   rischi elencati sopra) — non dare per scontato che funzioni al primo colpo, verificare i log.
3. Se il prefiltro scarta troppo aggressivamente (es. molti giocatori con partita futura non
   ancora quotata finiscono esclusi per odds N/D), rivedere con l'utente la scelta fatta in questa
   sessione di escludere anche i dati mancanti, non solo quelli sotto soglia.
