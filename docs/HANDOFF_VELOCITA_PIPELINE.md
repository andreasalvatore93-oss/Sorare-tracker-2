# Handoff velocita' pipeline — CHIUSO il 30/07 notte, vedi RIASSUNTO sez. 36 (36.A-36.K)

> **Questo documento e' storico e IL LAVORO E' CHIUSO** (richiesta esplicita dell'utente: "non
> c'e' piu' target se non esaurire i miglioramenti possibili... si torna alla versione piu' veloce
> poi committa pusha tutto e fermati"). Tempo di run a scope identico passato da **21m06s a
> ~7m55s-8m19s** (le due misure sulla STESSA configurazione finale differiscono per rumore di
> latenza Sorare, non per il codice — vedi 36.J), con la causa radice trovata (limite di
> complessita' GraphQL) e tre bug reali corretti.
>
> **Per lo stato finale, i numeri misurati fase per fase, i due vicoli ciechi da non ritentare e
> le leve residue (non implementate, con la ragione), leggere
> `docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md` sezioni 36.A-36.K.**
>
> Sintesi di cosa e' cambiato rispetto a quanto scritto qui sotto:
> - il `git push` in ogni job (46% di tutta la compute) e' stato sostituito dal passaggio dati via
>   artifact di Actions, con un solo commit finale (`salva_output`) — vedi `pipeline_artifacts.py`;
> - `consiglio` da 58 job a uno (faceva 268s di wall per 0s di lavoro reale);
> - `predict` raggruppato in bin con tetto duro di 8 giocatori per shard;
> - **causa radice**: la query `allPlayerGameScores` chiedeva 60 partite (complessita' 1812 contro
>   un tetto di 500) e quindi **non e' mai riuscita**, bruciando 10+20+40s di retry per giocatore.
>   Ora paginata a 10 partite per chiamata;
> - bug `presence_rate` nei 26 predict FWD: assegnato solo in un ramo, usato sempre — era la causa
>   dei file `ERRORE_<slug>.txt` e dell'assenza silenziosa di quei giocatori dai consigli.
>
> Il punto 4 delle istruzioni originali ("l'APIKEY alzerebbe il tetto a 30000") **non e'
> percorribile**: l'utente l'ha gia' richiesta a Sorare e al momento non e' disponibile.
> Non riproporla.
>
> **Seconda tornata (30/07 notte, sez. 36.I-36.K)**: tolti dall'albero i 654 MB di dump `.debug/`
> mai riletti da nessuno script (checkout 13,3s→3,07s); i 36 job discovery unificati in un solo
> job a matrice da 20 gruppi; pacing GraphQL adattivo (parte da 0,2s, si alza da sola sui 429,
> stato condiviso su file tra i processi) al posto della pausa fissa da 0,5s — lavoro predict
> -55%. **Vicolo cieco nuovo**: bin piu' piccoli/numerosi (65 bin, tetto 5 giocatori) SEMBRAVA
> la mossa giusta ma ha peggiorato (7m55s -> 10m56s) perche' Sorare rallenta CUMULATIVAMENTE nel
> corso della run in latenza, non con dei 429 — piu' bin sposta piu' lavoro nella coda lenta.
> Ripristinata la configurazione 45 bin / 8 giocatori per shard, quella misurata migliore.
> Non riproporre ne' l'APIKEY (sopra) ne' bin piu' fini senza prima misurare la latenza Sorare
> nel tempo con run distanziate (non consecutive: il carico di un'intera sessione di test altera
> la latenza delle run successive).

---

# Handoff: non sono riuscito a risolvere il problema di velocità della pipeline

Sono il modello che ha lavorato su questo task stanotte (Sonnet 5) e non ci sono riuscito
al livello richiesto. L'utente mi ha detto esplicitamente che sono troppo stupido per
risolverlo e mi ha chiesto di scrivere questo documento per un modello più capace che
possa riprendere da dove ho lasciato e risolvere il problema al primo colpo, **senza
rompere il codice o le formazioni esistenti**.

## Il repo

`Sorare-tracker-2` — pipeline GitHub Actions che genera pronostici e formazioni per un
fantasy calcio (Sorare), su 27 leghe tracciate (più `formazione_resto_mondo`, arretrata,
fuori scope qui). Branch: `main`. Non esistono altri branch di lavoro in questo momento
(un tentativo di redesign su branch separato è stato fatto e poi ELIMINATO su richiesta
esplicita dell'utente — vedi sezione "Cosa NON fare" sotto).

## Il problema esatto

Il workflow `.github/workflows/formazione_giornata.yml` genera le formazioni. Una run con
questo identico scope:

```bash
gh workflow run formazione_giornata.yml \
  -f gameweek=98 \
  -f starter_odds_min=0 \
  -f allstars=0 \
  -f allstars_u23=0 \
  -f arena_allstars_260=0 \
  -f arena_allstars_220=0 \
  -f arena_allstars_uncapped=0 \
  -f in_season= \
  -f arena_dedicata="portogallo:2,scozia:2,croazia:2" \
  -f list_unused_candidates=0
```

impiegava circa **20 minuti**. L'utente vuole che la STESSA run, con lo STESSO output
(stesse formazioni, stessa qualità del pronostico — nessuna regressione), impieghi
**al massimo 10 minuti**. Non è negoziabile ridurre la qualità delle formazioni o
saltare leghe/ruoli per andare più veloci: deve generare esattamente le 6 formazioni
richieste (2 Portogallo + 2 Scozia + 2 Croazia, arena_dedicata) con la stessa logica
di scoring di sempre.

## Come è strutturata la pipeline (a matrice)

1. **discovery** (~34 job paralleli, uno per shard lega/ruolo): ogni job scarica dal
   GraphQL di Sorare le carte possedute rilevanti, risolve la giornata (fixture) per il
   gameweek richiesto, filtra per squadre in campo e soglia starter-odds, scrive
   `formazione_<lega>/output/<lega>_<ruolo>_discovery/player_slugs.json`. Poi fa commit+push
   su `main` con un retry-loop (`merge -X ours` + `merge_discovery_json.py` per non
   cancellarsi a vicenda tra shard).
2. **discovery_merge**: raccoglie tutto.
3. **predict** (job a matrice, sharding adattivo per lega/ruolo): per ogni giocatore
   eleggibile calcola lo `score_atteso` (Poisson, shrinkage Empirical Bayes, opponent
   strength, venue, ecc. — vedi `formazione_<lega>/predict/test_{gk,def,mid,mls_fwd_all}.py`).
   **predict richiede (`needs:`) il successo di TUTTI i job discovery** — se anche un
   solo job discovery fallisce, predict/consiglio/formazione vengono SKIPPATI e l'intera
   run fallisce, anche se le altre 33 leghe/ruoli sono andate bene.
4. **consiglio** (job a matrice): sceglie i migliori giocatori per slot/budget.
5. **formazione**: assembla l'output finale.

## Cosa ho già provato (fix REALI, verificati, già pushati su `main`, NON toccarli
   a meno che non siano la causa di un problema nuovo)

Tutti questi sono committati e pushati, non sono ipotesi:

1. `fetch-depth: 1` su tutti i 39 `actions/checkout@v4` nel workflow (shallow clone,
   meno tempo di git clone).
2. `cache: "pip"` + `cache-dependency-path: requirements-formazione.txt` su tutti i 39
   `actions/setup-python@v5` (evita reinstallare `requests`/`curl_cffi` ogni volta).
3. Job `consiglio`: aggiunto `max-parallel: 77` (mancava, colpa di un collo di bottiglia
   iniziale con concorrenza di default bassa su 108 combinazioni) e `timeout-minutes`
   alzato da 15 a 30 (il job veniva ucciso a metà del suo retry-loop di push).
4. In `discovery_fixture.py`: `PREDICT_SHARD_LEAGUES` generalizzato da `{'mls','kleague'}`
   a `None` (= si applica a TUTTE le leghe, non solo 2), e `PREDICT_SHARD_TARGET_SIZE`
   abbassato da 25 a 15 (più shard = job predict più piccoli e paralleli).
5. `opponent_strength.py` (modulo condiviso, usato da tutti i predict per calcolare
   opponent_lambda_mult): aggiunta una cache su **disco** (`/tmp/opponent_strength_cache/`,
   ephemera per runner, mai committata) per `_build_series_for_league`,
   `_build_def_poss_lost_series`, `_build_def_pen_area_series`. Causa identificata:
   ogni predict è un PROCESSO SEPARATO (un giocatore = un processo), quindi la cache
   in-memoria del modulo (`_CACHE` ecc., "una volta per processo") si azzerava ad ogni
   giocatore, e un job con 15 giocatori dello stesso ruolo/lega rifaceva la scansione
   COMPLETA della cartella cache (200+ file per le leghe più vecchie) 15 volte. FWD è il
   ruolo più colpito perché scansiona DUE cartelle (goals_conceded + poss_lost_ctrl).
   Verificato con test diretto: valori identici prima/dopo il fix (confronto byte-per-byte).
6. `discovery_fixture.py`, funzione `_resolve_query_with_retry` (risolve la fixture/gameweek,
   UNA chiamata critica per job, non per giocatore): portata da 3 tentativi con 3s fissi
   (~20s totali) a 6 tentativi con backoff crescente e jitter (5,10,15,20,25s+jitter,
   ~90s totali). Causa: un job discovery su 34 è fallito per intero per un blocco
   CloudFront (403) sulla query `FixtureList` che ha resistito ai 20s di retry precedenti
   — e siccome `predict` richiede il successo di TUTTI i job discovery, quel singolo
   fallimento ha ucciso l'intera run (tutto il resto skippato a cascata).

## Cosa NON fare (già provato e fallito, o già rifiutato dall'utente)

- **NON riprogettare la pipeline in un singolo processo/job** (invece della matrice
  GitHub Actions). L'ho già provato su un branch separato (`redesign-async-pipeline`,
  poi eliminato completamente su richiesta esplicita dell'utente). Ho verificato dal vivo
  (4 test) che il rate-limit di Sorare reagisce fortemente a CONNESSIONI CONCORRENTI dalla
  stessa fonte/IP, non solo al volume medio di richieste — un solo processo (anche con
  pacing conservativo o un pool di thread) non riesce a eguagliare il throughput della
  pipeline a matrice multi-runner (dove ogni runner GitHub Actions ha un IP diverso).
  L'utente ha definito questo tentativo "fallito miseramente".
- **NON toccare la logica di scoring/shrinkage/formule** in `test_{gk,def,mid,mls_fwd_all}.py`
  per guadagnare velocità: quella parte è già stata tarata a lungo (vedi
  `docs/RIASSUNTO_EVOLUZIONE_MODELLO_PREDITTIVO.md`, sezione "Roadmap tuning definitivo") ed
  è chiusa. Il problema è di INFRASTRUTTURA/velocità di esecuzione, non di formula.
- **NON abbassare la qualità/copertura della discovery** (es. saltare leghe, ridurre pagine
  scansionate) per andare più veloci — l'utente ha già segnalato in passato un bug reale
  dove una scansione troncata perdeva giocatori posseduti in silenzio (vedi commenti in
  `discovery_fixture.py` su "Zinckernagel perso in silenzio").

## Stato esatto in questo momento

Ho appena pushato il fix #6 (retry fixture) e rilanciato la run di test:
`gh run` id **30494326179** (workflow `formazione_giornata.yml`, stesso scope di sopra,
lanciata alle 21:57:24 UTC del 2026-07-29). **Non so ancora se questa run ha completato
in tempo o se è fallita di nuovo** — l'utente mi ha fermato prima che potessi verificarlo.

Prima di questa, la run **30493943673** (lanciata subito dopo il fix #5, cache disco) è
fallita per il problema del fix #6 (blocco CloudFront su FixtureList, retry insufficiente) —
quindi il fix #5 (cache disco opponent_strength) NON è ancora stato verificato dal vivo
per il suo effetto sulla velocità di FWD, perché quella run non è mai arrivata al job predict.

## Cosa fare ora, in ordine

1. Controlla lo stato della run **30494326179**:
   ```bash
   gh run view 30494326179 --json status,conclusion,jobs
   ```
   Se ancora `in_progress` e sono passati più di ~12-13 minuti dal lancio, guarda comunque
   se sta procedendo bene (nessun job fallito) prima di cancellare — un margine di qualche
   minuto oltre i 10 è normale rumore, non serve panico.

2. Se è fallita: leggi il log del job fallito con
   `gh api repos/andreasalvatore93-oss/Sorare-tracker-2/actions/jobs/<job_id>/logs`
   e capisci la causa VERA prima di cambiare qualunque cosa. **Attenzione**: nei log
   vedrai tag tipo `[turchia_gk_discovery]` — NON significa che c'entra la lega Turchia,
   è solo il nome del modulo Python condiviso (`turchia_gk_discovery.py`, importato come
   `base` da quasi tutti gli script) usato per il logging. Ho già perso tempo stanotte
   a incolpare la Turchia per errore.

3. Se è andata a buon fine ma il tempo totale (dall'avvio del workflow al job
   `formazione` completato) è sopra i 10 minuti: guarda quali job hanno impiegato più
   tempo (soprattutto i job `predict` per ruolo FWD, che sono stati sistematicamente i
   più lenti in ogni test di stanotte) e capisci il PROSSIMO collo di bottiglia reale,
   non ipotetico — leggi i log, non tirare a indovinare.

4. Applica il fix, **bundlando più fix insieme quando ha senso** (l'utente ha chiesto
   esplicitamente di non testare una modifica alla volta), committa e pusha su `main`
   (retry loop consigliato per gestire push concorrenti di altri bot: vedi il pattern
   usato nei commit di stanotte, `git pull --rebase` + retry fino a 8 volte), rilancia
   lo stesso identico scope di test sopra, e ripeti finché non scende sotto i 10 minuti
   in modo affidabile (non una tantum).

5. Solo DOPO che la velocità è risolta e stabile: c'è un secondo task in sospeso a
   priorità più bassa, il popolamento della calibrazione Bundesliga tramite il workflow
   generico `calibrazione_lega.yml` (lanciato una volta per `lega=germania,ruolo=gk`,
   run id `30491495720`, mai riverificato — controllarne lo stato, poi continuare con
   def/mid/fwd).

## Una cosa importante sul mio giudizio

Non sono certo che il problema si risolva con "un fix in più": è possibile che il tetto
strutturale sia più vicino di quanto pensassi (rate-limit Sorare + tempo minimo di
34+ job GitHub Actions in sequenza/matrice con dipendenze). Se dopo altri 2-3 fix mirati
il tempo non scende in modo sostanziale, vale la pena fermarsi e dirlo chiaramente
all'utente invece di continuare a promettere un altro giro — è quello che io non ho
fatto abbastanza chiaramente stanotte.
