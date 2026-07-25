# Riassunto evoluzione "Bot definitivo" — 25-26/07/2026

**AGGIORNATO — fine sessione, utente vicino al limite di utilizzo, passaggio a un altro
account/sessione Claude Code.** Repo `Sorare-tracker-2`, branch `main`. Tutto lo stato
descritto qui è già **committato e pushato** su GitHub (ultimo commit di questa sessione
`6fc87f11`, verificare `git log --oneline -10` per eventuali commit successivi di altri
workflow automatici) — si può ripartire con `git pull`, non c'è lavoro locale non salvato.

## PROSSIMA AZIONE IMMEDIATA (in ordine)

1. **Rifare il run diagnostico mirato a generare molti AutoBuy** (il tentativo di questa
   sessione ha dato zero match, vedi sezione 1 punto 9 e sezione 6 punto 1 per il comando
   esatto) — serve per misurare i **tempi di risposta del ramo AutoBuy** (quello critico
   per vincere la corsa contro altri bot, a differenza di MakeOffer che non è time-critical
   secondo l'utente).
2. **Continuare ad affinare le soglie del bot** con altri casi reali/ipotetici man mano che
   arrivano dai run diagnostici — in particolare il "gradiente dentro la fascia" (sezione 4)
   e la soglia AutoBuy 15-30€ abbassata a 16% su un solo punto dato (sezione 6, punti 2-3).

Handoff dettagliato su tutto il lavoro fatto in questa sessione (partita in worktree
`agent-a6fafee9d6b2c4df4`, poi mergiata su `main`) su `bots/bot_definitivo.py` — il bot
REALMENTE in uso in produzione (ex `bot_supremo_test.py`, workflow ex "Bot Supremo test
no play"). Il dettaglio caso-per-caso completo della sessione di calibrazione (~55 casi
totali) vive nella memoria locale di Claude Code su questa macchina (file
`bot_definitivo_margin_calibration.md`), **non nel repo** — se si continua da un'altra
macchina/account, quella memoria non è accessibile: questo documento riassume le
conclusioni in modo il più possibile autosufficiente.

## 1. Timeline completa

1. **Rename** (commit `ce95fff8`): `bot_supremo_test.py` → `bot_definitivo.py`,
   `.github/workflows/bot_supremo_test.yml` → `bot_definitivo.yml`, nome workflow "Bot
   Supremo test no play" → "Bot definitivo". Il nome vecchio suggeriva un bot di test, ma
   è quello realmente in produzione.
2. **Primo tentativo di soglie dinamiche** (commit `10d5ea43` + `812f0a9c`, poi
   **abbandonato**): soglie di margine calcolate come percentili della storia recente dei
   margini osservati (persistita in JSON). Rispondeva alla domanda sbagliata — vedi
   sezione 2.
3. **Prima sessione di calibrazione manuale** (~45 casi, 25-26/07): casi reali e ipotetici
   discussi uno alla volta con l'utente (`AskUserQuestion`) per capire la sua vera logica
   di trading. Vedi sezione 3 per le regole emerse.
4. **Prima implementazione basata sul prezzo** (commit `8737a9a2`, 26/07): sostituisce il
   sistema a percentili con le tre regole di sezione 3.
5. **Primo run diagnostico completo** (30 min, ID `30171957853`, poi `30174631418` dopo un
   riavvio): 12 match reali MakeOffer osservati, 8 confermati esattamente, 4 con richiesta
   di sconto leggermente più profondo — **nessun disaccordo su decisione o routing
   AutoBuy/MakeOffer**.
6. **Seconda sessione di calibrazione** (10 casi ipotetici mirati + revisione degli 8
   scarti/12 match del run precedente): confermato un pattern reale di "gradiente" (stesso
   margine, prezzo diverso → decisione diversa) e isolato quali fasce di sconto erano
   sistematicamente troppo miti. Vedi sezione 4.
7. **Ricalibrazione soglie** (commit `7da02504`, 26/07): sconto `<4€` 22.5%→27%, sconto
   `4-7€` 16.5%→19%, soglia AutoBuy `15-30€` 18%→16%. Aggiunto anche l'input workflow
   `price_based_thresholds_enabled` per poter disattivare le soglie per-prezzo via
   `workflow_dispatch` senza toccare codice (serviva per il punto 9).
8. **Pulizia input diagnostici morti** (commit `6fc87f11`): rimossi `autobuy_diagnostic` e
   `min_non_trigger_log` dal workflow e dal codice (richiesta esplicita utente, non più
   usati) — incluso dead code risultante (variabile `categoria` orfana).
9. **Tentativo di test timing AutoBuy** (run `30176259660`, 5 min, soglie statiche forzate
   all'1% via `price_based_thresholds_enabled=no`): **zero match prodotti** — non un bug,
   il mercato era genuinamente tranquillo in quella finestra E i pochi candidati che
   superavano la soglia margine sono stati scartati da altri controlli di sicurezza
   (mercato sottile, prezzo fuori range, controllo "prezzo ≥ ultima/penultima
   transazione"). **Nessun dato di timing AutoBuy raccolto — vedi sezione 6, punto 1.**

## 2. Perché il sistema a percentili storici è stato abbandonato

Rispondeva alla domanda sbagliata: "quanto è raro questo margine rispetto al mercato
recente" invece di quella che conta davvero: "a questo margine, su una carta di questo
prezzo, l'utente l'avrebbe comprata/offerta?".

**Metodologia della sessione di calibrazione (lezioni utili per continuare)**:
- **Un caso alla volta**, con `AskUserQuestion`, sia da run reali (log GitHub Actions) sia
  ipotetici — l'utente vuole **nomi di giocatori reali** anche per i casi inventati.
- **Dare sempre prezzi assoluti concreti**, mai solo percentuali — verificato
  esplicitamente: a una domanda con solo il margine %, l'utente non riesce a valutare
  senza i prezzi in euro.
- **Evitare domande guidate con una risposta plausibile di default** ("sei d'accordo con
  l'autobuy?"): una risposta morbida tipo "ci sta" si è rivelata inaffidabile — casi
  ri-testati con domande neutre ("cosa avresti fatto?") hanno dato risposte opposte (vedi
  il ribaltamento Reichert/Diaw/Vera in sezione 3.2).
- **Convenzione**: "offro X euro" significa sempre "fino a X euro al massimo".
- **Principio guida esplicito**: il bot non deve trovare un match per forza — zero match in
  un'ora è normale. Non allentare le soglie solo per produrre più match nei test.
- **Spiegazione dell'utente per la variabilità caso-per-caso** (sezione 4): "conosco tutti
  i giocatori, so chi è più facile da rivendere e chi no" — una parte della variabilità
  osservata (stesso prezzo/margine, decisione diversa) NON è rumore, riflette una
  conoscenza personale del giocatore che il bot non può replicare. `count_7d` (transazioni
  recenti, già calcolato da `get_liquidity_and_last_price`) è il proxy più vicino
  disponibile, ma è imperfetto — **non aspettarsi mai un fit perfetto al 100%**.

## 3. Le tre regole (prima versione, poi rifinita in sezione 4)

### 3.1 Margine minimo per agire (MakeOffer o AutoBuy), dipende dal PREZZO

| Prezzo | Margine minimo |
|---|---|
| < 4€ | ~13% |
| ≥ 4€ | ~7% |

Sotto ~4€ il guadagno assoluto in euro è troppo piccolo per valere il rischio/tempo di
negoziare. Casi chiave: Bombino (2.81€/6.5%→scarto), Ferreira (1.50€/10.4%→scarto) contro
Trossard (3.49€/16.5%→offerta OK); Johnson (5.52€/7.3%→OK), Gill (6.00€/7.7%→OK) contro
Pickford (10.50€/4.5%→scarto).

### 3.2 Split AutoBuy (prezzo pieno) vs MakeOffer (offerta ribassata)

**Non è una soglia di margine globale** — dipende da PREZZO e MARGINE insieme:

| Prezzo | Margine minimo per AutoBuy diretto |
|---|---|
| < 3€ | **mai** (sempre MakeOffer, testato fino al 44% di margine) |
| 3-5€ | ~35% |
| 5-8€ | ~27% |
| 8-15€ | ~22% |
| ≥ 15€ | ~16% (aggiornato da 18%, sezione 4) |

Punto importante corretto durante la prima sessione: risposte iniziali (Jan Reichert, Mory
Diaw) sembravano confermare l'AutoBuy anche su carte economiche a margine altissimo, ma
erano risposte "morbide" a domande guidate. Ri-testate con domande neutre, l'utente ha
ribaltato: sotto ~3€ **non vuole mai** il prezzo pieno. Sopra i 3€ il margine richiesto
scende al crescere del prezzo — verificato su ~15 casi (Vera, Reichert, Diaw, Robinson,
Rashford, Ansu Fati, Endrick, Mainoo, Zaire-Emery, Ronaldo Jr, Pedri, Nico Williams, Gavi,
Haaland, Bruno Guimarães, Ødegaard), zero contraddizioni con questa tabella nella seconda
sessione di verifica.

### 3.3 Sconto dell'offerta MakeOffer

Conta il **prezzo della carta**, non il margine del caso (al contrario della prima
versione a percentili, che scalava con il margine).

| Prezzo | Sconto offerta (AGGIORNATO, sezione 4) |
|---|---|
| < 4€ | ~27% (era 22.5%) |
| 4-7€ | ~19% (era 16.5%) |
| 7-15€ | ~11.5% (invariato) |
| ≥ 15€ | ~10% (invariato) |

Eccezione: giocatori molto liquidi (`count_7d >= LIQUID_PLAYER_TRANSACTIONS_7D=15`) usano
sempre lo sconto mite 10%, a prescindere dal prezzo — caso reale: Bradley Barcola (ma
attenzione, lo stesso giocatore in un run successivo NON ha ricevuto lo sconto liquido,
segno che `count_7d` varia nel tempo/mercato, non è una proprietà fissa del giocatore).

## 4. Seconda sessione di calibrazione (26/07) — cosa è cambiato dalla prima versione

Rivisti tutti i 12 match reali del primo run diagnostico completo + 10 casi ipotetici
mirati a colmare le lacune. Risultati:

**Sconto offerta troppo mite in due fasce, ora corretto**:
- Fascia `<4€`: split quasi 50/50 tra "va bene com'è" (Guendouzi, esatto a 22.5%) e "voglio
  più profondo" (Calum Ward confermato 2 volte a ~30%, Stanišić ~35%, Camavinga ~29-34%) —
  alzato a 27% come compromesso.
- Fascia `4-7€`: split ESATTAMENTE 4 conferme/4 richieste più profonde (confermato a 16.5%:
  Tchouaméni, Rafael Leão, Ionuț Radu, Dani Olmo — voluto più profondo: Gloukh, Mauro
  Junior, Saibari, Rice bis) — alzato a 19%.
- Fascia `15-30€`: soglia AutoBuy abbassata 18%→16% sulla base di UN solo punto (Saka bis,
  "autobuy ma al pelo" a 16%) — **da confermare con altri casi prima di fidarsene
  pienamente.**

**Trovato un vero problema di "gradiente" nel floor del margine** (sezione 3.1): a
**parità di margine**, la decisione cambia in base al prezzo esatto DENTRO la stessa
fascia, non solo tra le due fasce:
- Cherki (11.60€, 6.8%, soglia 7%) → agirebbe comunque; Cucurella (6.00€, STESSO 6.8%) →
  scarto confermato.
- Talisca (3.00€, 11.8%, soglia 13%) → agirebbe; Pedro Neto (1.50€, STESSO 11.8%) → scarto.
- Camavinga (3.80€, 12.2%) → agirebbe; Ansu Fati (1.80€, STESSO 12.2%) → scarto.

Tre coppie diverse, stesso pattern: **il floor probabilmente decresce in modo continuo
dentro ogni fascia, non a gradini netti come modellato oggi.** L'utente ha spiegato che
parte di questo è dovuto alla sua conoscenza personale di quali giocatori sono più facili
da rivendere (vedi sezione 2) — quindi non aspettarsi di eliminare tutta la varianza anche
con un modello più fine. **Non ancora implementato** — è un cambiamento più strutturale
(da due gradini fissi a una curva continua) che richiede design, non solo tarare due
numeri. Vedi sezione 6, punto 2.

## 5. Implementazione tecnica

**File modificati**: `bots/bot_definitivo.py`, `.github/workflows/bot_definitivo.yml`.

Funzioni: `compute_price_based_thresholds(price_eur)` → `(makeoffer_min_margin,
autobuy_min_margin_o_None)`; `compute_price_based_offer_discount(price_eur,
count_7d=None)`. Sostituiscono `compute_dynamic_margin_thresholds()` /
`compute_dynamic_offer_discount()` e tutta la macchina di persistenza storica (rimossa
interamente: niente più file `bot_definitivo_margin_history.json`, niente più percentili).

**Interruttore di sicurezza**: `PRICE_BASED_THRESHOLDS_ENABLED` (env, default `'si'`,
esposto anche come input `price_based_thresholds_enabled` nel workflow) — se `'no'`, torna
al comportamento statico originale (3 costanti fisse `MAKEOFFER_MARGIN_FRACTION`/
`MAKEOFFER_MAX_MARGIN_FRACTION`/`AUTOBUY_MARGIN_FRACTION` prese dagli input percentuali del
workflow, sconto sempre `OFFER_DISCOUNT_FRACTION`) senza toccare il codice. **Usato in
questa sessione per forzare artificialmente moltissimi AutoBuy in un test diagnostico**
(impostando anche `autobuy_margin_percent=1`).

**Input workflow rimossi** (commit `6fc87f11`, richiesta esplicita utente, non più usati):
`autobuy_diagnostic`, `min_non_trigger_log` (e le costanti/log associati nel codice Python).

**Validazione fatta finora**:
- `python -m py_compile` OK dopo ogni modifica.
- Spot-check di 12 casi del dataset (Vera 44% niente autobuy sotto 3€, Ansu Fati 40%
  autobuy a 3€, Haaland 28.6% autobuy a 25€, ecc.) — tutti coerenti.
- 2 run diagnostici completi da 30 minuti (`autobuy_live_mode=no`, `makeoffer_live_mode=no`)
  con revisione umana caso-per-caso di TUTTI i match e diversi scarti — vedi sezioni 3-4.
- 1 tentativo di run mirato a generare molti AutoBuy per analisi timing — **zero match**,
  vedi sezione 1 punto 9 e sezione 6 punto 1.
- **MAI testato in modalità live reale** (`autobuy_live_mode=si`/`makeoffer_live_mode=si`)
  con la nuova logica — solo diagnostica finora.

## 6. Prossimi passi (in ordine di priorità)

1. **Analisi timing del ramo AutoBuy — NON ancora fatta.** Il tentativo di questa sessione
   (run `30176259660`, 5 min, soglie forzate all'1%) ha prodotto zero match per pura
   sfortuna di mercato + controllo di sicurezza "ultima/penultima transazione" che ha
   scartato gli unici 2 candidati marginali (Jeremy Doku, Mark Delgado). Riprovare con:
   una finestra più lunga (10-15 min invece di 5), o accettare che serva più di un
   tentativo dato quanto raramente scatta un vero AutoBuy anche con soglie forzate basse.
   Comando di riferimento:
   ```
   gh workflow run "bot_definitivo.yml" --ref main -f autobuy_live_mode=no -f makeoffer_live_mode=no \
     -f price_based_thresholds_enabled=no -f autobuy_margin_percent=1 -f makeoffer_margin_percent=1 \
     -f makeoffer_max_margin_percent=1 -f listen_seconds=600 -f target_matches=100
   ```
   I blocchi di log `[timing]` (formato `scan_prezzi=...s, liquidita+ultimo_prezzo=...s,
   dettagli_carta=...s, prepare_offer=...s, esecuzione_finale=...s -- TOTALE=...s`) danno i
   dati; per il ramo AutoBuy guardare anche `prepare_accept_offer`/firma speculativa (vedi
   `_speculative_sign_after_prepare` in `bot_definitivo.py`) che nel ramo MakeOffer non
   esiste. **Nota per i tempi di risposta**: l'utente ha detto esplicitamente che il timing
   MakeOffer non è critico, solo quello AutoBuy lo è (la finestra per vincere la corsa
   contro altri bot è quella che conta).
2. **Gradiente del floor margine dentro le fasce** (sezione 4): tre coppie di casi
   (Cherki/Cucurella, Talisca/Pedro Neto, Camavinga/Ansu Fati) mostrano che a parità di
   margine il floor dovrebbe dipendere anche dalla posizione dentro la fascia, non solo
   dalla fascia stessa. Prima di implementare una curva continua, raccogliere altre coppie
   simili per confermare la forma — è un cambiamento di design, non solo un numero da
   tarare, discuterne con l'utente prima di toccare `compute_price_based_thresholds()`.
3. **Soglia AutoBuy 15-30€ abbassata a 16%** sulla base di un solo punto dato (Saka bis) —
   raccogliere altre conferme prima di fidarsene per l'uso live.
4. **Validare in modalità live reale** (`autobuy_live_mode=si`/`makeoffer_live_mode=si`)
   solo dopo aver raccolto altri casi reali e sentendosi sicuri della logica — questa
   sessione ha lavorato SOLO in diagnostica.
5. La memoria di calibrazione dettagliata (`bot_definitivo_margin_calibration.md`, ~55
   casi con ragionamento completo dell'utente) resta locale a questa macchina/account
   Claude Code — se si continua da un'altra macchina, questo documento è il riferimento,
   ma il dettaglio caso-per-caso va eventualmente ricostruito o richiesto di nuovo
   all'utente.

## 7. File chiave per orientarsi rapidamente

- `bots/bot_definitivo.py` — il bot, funzioni `compute_price_based_thresholds` /
  `compute_price_based_offer_discount` (~riga 587-680), routing in `evaluate_event`
  (~riga 2900-3060), blocchi `[timing]` in `_handle_autobuy_branch`/`_handle_makeoffer_branch`.
- `.github/workflows/bot_definitivo.yml` — input `price_based_thresholds_enabled` per
  disattivare le soglie per-prezzo, utile per test diagnostici mirati.
- Comando tipo per un run diagnostico normale (nessun rischio, nessun acquisto/offerta reale):
  ```
  gh workflow run "bot_definitivo.yml" --ref main -f autobuy_live_mode=no -f makeoffer_live_mode=no \
    -f target_matches=100 -f listen_seconds=1800
  ```
