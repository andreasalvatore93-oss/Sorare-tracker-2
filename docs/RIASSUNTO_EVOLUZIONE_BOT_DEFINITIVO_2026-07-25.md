# Riassunto evoluzione "Bot definitivo" — 25-26/07/2026

Handoff dettagliato su tutto il lavoro fatto in questa sessione (worktree
`agent-a6fafee9d6b2c4df4`, poi mergiato su `main`) su `bots/bot_definitivo.py` — il bot
REALMENTE in uso in produzione (ex `bot_supremo_test.py`, workflow ex "Bot Supremo test
no play"). Il dettaglio caso-per-caso completo della sessione di calibrazione vive nella
memoria locale di Claude Code su questa macchina (file
`bot_definitivo_margin_calibration.md`), **non nel repo** — questo documento riassume le
conclusioni in modo autosufficiente per chi riprende il lavoro da un'altra sessione/macchina.

## 1. Timeline

1. **Rename** (commit `ce95fff8`): `bot_supremo_test.py` → `bot_definitivo.py`,
   `.github/workflows/bot_supremo_test.yml` → `bot_definitivo.yml`, nome workflow "Bot
   Supremo test no play" → "Bot definitivo". Motivo: il nome vecchio suggeriva un bot di
   test, ma è quello realmente in produzione — nome fuorviante corretto.
2. **Primo tentativo di soglie dinamiche** (commit `10d5ea43` + `812f0a9c`): soglie di
   margine calcolate come percentili della storia recente dei margini osservati (persistita
   in JSON). Caso motivante: Jhon Arias (margine reale 21.3%, soglia statica 26% → il bot
   ha scelto MakeOffer invece di AutoBuy, offerta poi fallita per un errore tecnico non
   legato al margine). **Superato dal punto 4** — vedi perché sotto.
3. **Sessione di calibrazione manuale** (25-26/07): ~45 casi reali e ipotetici discussi
   uno alla volta con l'utente (tool `AskUserQuestion`, prezzo 0.50-30€, margine 0-50%)
   per capire la sua vera logica di trading, invece di indovinarla da un modello
   statistico. Vedi sezione 2.
4. **Nuova logica basata sul prezzo** (commit `8737a9a2`, 26/07): sostituisce il sistema
   a percentili storici con tre regole basate sul prezzo della carta, derivate
   direttamente dai casi della sessione di calibrazione. Vedi sezione 3.
5. **Validazione**: spot-check di 12 casi del dataset (tutti corretti) + run diagnostici
   reali su GitHub Actions (`autobuy_live_mode=no`, `makeoffer_live_mode=no`) — vedi
   sezione 4.

## 2. Perché il sistema a percentili storici è stato abbandonato

Rispondeva alla domanda sbagliata: "quanto è raro questo margine rispetto al mercato
recente" invece di quella che conta davvero: "a questo margine, su una carta di questo
prezzo, l'utente l'avrebbe comprata/offerta?".

Metodologia della sessione di calibrazione (lezioni utili per sessioni future simili):
- **Un caso alla volta**, con `AskUserQuestion`, sia da run reali (log GitHub Actions) sia
  ipotetici — l'utente ha esplicitamente chiesto di usare **nomi di giocatori reali** anche
  per i casi inventati, aiuta a ragionarci.
- **Dare sempre prezzi assoluti concreti**, mai solo percentuali — testato esplicitamente:
  a una domanda con solo il margine %, l'utente ha risposto di non riuscire a valutare
  senza i prezzi in euro. Ragiona in moneta assoluta, non in percentuale.
- **Evitare domande guidate con una risposta plausibile di default** (tipo "sei
  d'accordo con l'autobuy?"): una risposta morbida tipo "ci sta" si è rivelata inaffidabile
  — casi ri-testati con domande neutre ("cosa avresti fatto?") hanno dato risposte opposte
  (vedi il ribaltamento Reichert/Diaw/Vera in sezione 3.2).
- **Convenzione**: quando l'utente dice "offro X euro" intende sempre "fino a X euro al
  massimo", non un valore esatto.
- **Principio guida esplicito**: il bot non deve trovare un match per forza — zero match in
  un'ora è normale, non un fallimento. Non allentare le soglie solo per produrre più match
  durante i test.

## 3. Le tre regole emerse

### 3.1 Margine minimo per agire (MakeOffer o AutoBuy), dipende dal PREZZO

| Prezzo | Margine minimo |
|---|---|
| < 4€ | ~13% |
| ≥ 4€ | ~7% |

Sotto ~4€ il guadagno assoluto in euro è troppo piccolo per valere il rischio/tempo di
negoziare, anche a margini che sembrerebbero buoni in percentuale. Casi chiave: Bombino
(2.81€/6.5%→scarto), Ferreira (1.50€/10.4%→scarto) contro Trossard (3.49€/16.5%→offerta
OK); Johnson (5.52€/7.3%→OK), Gill (6.00€/7.7%→OK) contro Pickford (10.50€/4.5%→scarto).

### 3.2 Split AutoBuy (prezzo pieno) vs MakeOffer (offerta ribassata)

**Non è una soglia di margine globale** come nella versione precedente — dipende da
PREZZO e MARGINE insieme:

| Prezzo | Margine minimo per AutoBuy diretto |
|---|---|
| < 3€ | **mai** (sempre MakeOffer, testato fino al 44% di margine) |
| 3-5€ | ~35% |
| 5-8€ | ~27% |
| 8-15€ | ~22% |
| ≥ 15€ | ~18% |

Punto importante corretto durante la sessione: una prima serie di risposte (Jan Reichert,
Mory Diaw) sembrava confermare l'AutoBuy anche su carte economiche a margine altissimo, ma
erano risposte "morbide" a domande guidate. Ri-testate con domande neutre, l'utente ha
ribaltato: sotto ~3€ **non vuole mai** il prezzo pieno, preferisce sempre rischiare
un'offerta bassa (poco da perdere). Sopra i 3€ il margine richiesto per l'AutoBuy diretto
scende al crescere del prezzo — verificato su ~15 casi (Vera, Reichert, Diaw, Robinson,
Rashford, Ansu Fati, Endrick, Mainoo, Zaire-Emery, Ronaldo Jr, Pedri, Nico Williams, Gavi,
Haaland), zero contraddizioni con questa tabella.

### 3.3 Sconto dell'offerta MakeOffer

La versione precedente scalava lo sconto CON il margine (più margine = sconto più
profondo). I casi raccolti mostrano il contrario: conta il **prezzo della carta**, non il
margine del caso specifico.

| Prezzo | Sconto offerta |
|---|---|
| < 4€ | ~22.5% |
| 4-7€ | ~16.5% |
| 7-15€ | ~11.5% |
| ≥ 15€ | ~10% |

Eccezione: giocatori molto liquidi (tante transazioni recenti — proxy: `count_7d`, già
calcolato da `get_liquidity_and_last_price`, soglia `LIQUID_PLAYER_TRANSACTIONS_7D=15`)
usano sempre lo sconto mite (10%), a prescindere dal prezzo — caso reale: Bradley Barcola.

## 4. Implementazione e stato di validazione

**File modificato**: `bots/bot_definitivo.py` (commit `8737a9a2` su `main`).

Funzioni nuove: `compute_price_based_thresholds(price_eur)` → `(makeoffer_min_margin,
autobuy_min_margin_o_None)`; `compute_price_based_offer_discount(price_eur,
count_7d=None)`. Sostituiscono interamente `compute_dynamic_margin_thresholds()` /
`compute_dynamic_offer_discount()` e tutta la macchina di persistenza storica
(`record_margin_observation`, `_percentile`, file `bot_definitivo_margin_history.json`,
lock dedicato) — non più necessaria, le tabelle sono fisse.

**Interruttore di sicurezza**: `PRICE_BASED_THRESHOLDS_ENABLED` (default `'si'`) — se
`'no'`, torna al comportamento statico originale (3 costanti fisse
`MAKEOFFER_MARGIN_FRACTION`/`MAKEOFFER_MAX_MARGIN_FRACTION`/`AUTOBUY_MARGIN_FRACTION`,
sconto sempre `OFFER_DISCOUNT_FRACTION`) senza toccare il codice.

**Validazione fatta**:
- `python -m py_compile` OK.
- Spot-check di 12 casi del dataset di calibrazione (inclusi i più delicati: Vera 44% niente
  autobuy sotto 3€, Ansu Fati 40% autobuy a 3€, Haaland 28.6% autobuy a 25€) — tutti coerenti.
- Run diagnostico reale (`autobuy_live_mode=no`, `makeoffer_live_mode=no`, breve, poi
  interrotto per lavoro dell'utente): 2 match reali osservati.
  - Mattéo Guendouzi (3.00€, margine 16.7%) → MakeOffer a 2.33€ (sconto 22.5%) — **utente
    d'accordo su decisione e importo**.
  - Oscar Gloukh (4.39€, margine 10.0%, caso trigger-minimo-non-allineato) → MakeOffer a
    3.67€ (sconto 16.5%) — utente d'accordo sulla decisione, ma avrebbe offerto max 3.50€
    (~20.3%). Singolo punto dato, non abbastanza per cambiare subito la fascia 4-7€: **se
    altri casi in questa fascia confermano uno sconto sistematicamente più profondo di
    ~16.5%, alzare `OFFER_DISCOUNT_BY_PRICE` per la fascia 4.0€ verso ~0.18-0.19.**

## 5. Stato al momento di scrivere questo documento

Run diagnostico completo da 30 minuti **in corso** (lanciato più volte e riavviato su
richiesta dell'utente per liberare banda API per altro lavoro) — ultimo lancio con la
logica ricalibrata attiva. Verificare `gh run list --workflow="bot_definitivo.yml" --limit
1` per lo stato corrente. Se completato, scaricare il log (`gh run view <id> --job=<job_id>
--log`) ed esaminare i casi reali con lo stesso metodo usato finora (`AskUserQuestion`, un
caso alla volta, prezzi concreti, domande neutre) per continuare la calibrazione.

## 6. Prossimi passi suggeriti

1. Esaminare i risultati del run diagnostico in corso/completato con l'utente.
2. Tenere d'occhio la fascia 4-7€ per lo sconto offerta (vedi nota Gloukh sopra).
3. Continuare a raccogliere casi reali dai prossimi run diagnostici prima di considerare
   `PRICE_BASED_THRESHOLDS_ENABLED` definitivamente validato per l'uso in modalità live
   reale (`autobuy_live_mode=si`/`makeoffer_live_mode=si`).
4. La memoria di calibrazione dettagliata (`bot_definitivo_margin_calibration.md`) resta
   locale a questa macchina/account Claude Code — se si continua da un'altra macchina,
   questo documento è il riferimento, ma per il dettaglio caso-per-caso (tutti i ~45 casi
   con ragionamento dell'utente) serve accedere alla memoria originale o ricostruirla.
