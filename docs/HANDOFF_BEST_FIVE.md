# HANDOFF — Funzione "Best Five" / "Contender"

Riscritto il 31/07/2026 (sessione lunghissima, moltissimi cambi reali). La versione precedente
(30/07 sera) descriveva un'architettura appena nata e mai confermata end-to-end — oggi è stata
verificata su run reali, e sono stati trovati e corretti diversi bug reali che l'avrebbero resa
silenziosamente sbagliata. Leggerlo per intero prima di agire, non fidarsi della memoria.

## Cos'è "Best Five" oggi

Per UNA lega scelta, genera la **formazione ottimale** (GK/DEF/MID/FWD/EXTRA, con sinergie/anti-
stack/captain — STESSA logica del tool unificato, mai duplicata) scegliendo tra **TUTTE** le carte
della lega, non solo quelle possedute. Script separato e READ-ONLY rispetto alla pipeline di
produzione (`formazione_giornata.yml`).

**Novità di oggi rispetto al 30/07**: oltre alla singola lega, esiste ora un **orchestratore
"Contender"** (`best_five_contender.yml`) che genera Best Five per N leghe in parallelo e poi le
UNISCE in un pool combinato — pensato per la competizione Sorare "Contender" (che raggruppa ~20
campionati), ma usabile per QUALSIASI combinazione di leghe (l'utente lo usa anche per test
misti tipo Scozia+Austria+MLS, tecnicamente non bloccato anche se semanticamente non è "vera"
Contender).

## Bug reale trovato e corretto oggi: allineamento con la produzione

`best_five.py` chiamava `bff.generate_lineups_for_type` di
`formazione_mls/build_formazione_finale.py` — quel file segnala ESPLICITAMENTE in un commento
(audit 31/07) che quella funzione **non gira mai in produzione**: usava `variance_mode` sempre
attivo e un bonus sinergia In Season che la produzione ha disattivato dopo test A/B. Fix: ora si
chiama DAVVERO `generatore_formazioni/build_formazione_globale.py` (lo stesso file di
`formazione_giornata.yml`), importato dinamicamente. Verificato con un confronto reale (run 86)
su MLS/K League: punteggi identici giocatore per giocatore quando lo stesso giocatore appare in
entrambi i pool.

## Leghe con discovery_global pronta (Best Five utilizzabile)

`LEGHE_SUPPORTATE` in `best_five.py`: **mls, kleague, germania, austria, croazia, germania2,
scozia, portogallo, danimarca, argentina**. Ognuna richiede:
1. `formazione_<lega>/discovery/<lega>_<ruolo>_discovery_global.py` (x4 ruoli) — club verificati
   dal vivo via `verify_clubs.yml` prima di scrivere il codice, mai indovinati.
2. `formazione_<lega>/consiglio/build_consiglio_<ruolo>.py` patchato con l'override
   `CONSIGLIO_DISCOVERY_FILE` (altrimenti Best Five ignora silenziosamente il pool globale e
   ripiega sui soli posseduti — bug reale trovato su Croazia il 31/07, vedi sotto).

**Backlog aperto**: la patch `CONSIGLIO_DISCOVERY_FILE` non è ancora stata verificata/applicata
alle restanti ~20 leghe minori (belgio, olanda, turchia, spagna, francia, scozia già fatta,
brasile, resto_mondo, giappone, inghilterra, italia, polonia, cile, svizzera, grecia, ecc.) — task
in coda (chip spawnato in sessione, `task_86d53e8a`).

**Norvegia**: MAI tracciata (nessuna cartella `formazione_norvegia`). Richiesta esplicita
dell'utente di rimandarla — serve l'intera pipeline da zero (discovery posseduti + predict +
consiglio + build_formazione_finale), non solo la discovery_global. Slug lega verosimile
`eliteserien` (visto nello screenshot Contender), MAI verificato dal vivo.

## Bug reale trovato oggi: `build_consiglio_<ruolo>.py` ignorava Best Five

Causa del "pochi giocatori trovati" su Croazia (31/07): `DISCOVERY_FILE` in `build_consiglio_
gk.py` (e def/mid/fwd) era hardcoded ai soli posseduti su TUTTE le leghe tranne mls/kleague/
germania (le uniche patchate il 30/07). Risultato osservato: 7 GK e 15 FWD avevano superato il
prefiltro starterOdds con dati concreti (es. 90%), ma il consiglio finale ne mostrava solo 1 e 2
— guarda caso gli UNICI già posseduti dall'utente in quei ruoli. NON era un problema di timing
delle starterOdds come inizialmente sospettato. Fix: propagata la stessa patch (già esistente su
mls/kleague/germania dal 30/07) a austria/croazia/germania2/scozia/portogallo/danimarca/
argentina.

## Bug reale trovato oggi: cap L10 Arena rotto in Best Five

Su Scozia (prima lega con un'Arena dedicata VERA in produzione usata attraverso Best Five):
`Formazione Arena Scozia #1: NON GENERATA` nonostante decine di candidati validi. Causa:
`bff._pareto_frontier` (usata per il cap L10 260) ordina i candidati per L10 crescente e tiene
solo chi migliora il punteggio — corretto quando l'L10 varia da carta a carta (produzione, carte
reali possedute), ma la CardPool sintetica di Best Five non ha MAI l'L10 reale di un giocatore
non posseduto (sempre 0.0 per tutti): con costi tutti identici la frontiera collassa a UN SOLO
candidato per ruolo. Verificato con un test isolato (frontiera=1 con L10 tutti a 0, frontiera=4
con L10 reali variabili).

Il cap 260 non era comunque mai stato un vincolo rispettato in Best Five (MLS/K League/Contender
sono IN_SEASON, senza cap per design) — l'utente ha confermato che non è un requisito, solo un
difetto di etichetta. Fix: cap disattivato di default per le Arene dentro Best Five. Aggiunto
pero' un interruttore esplicito (`rispetta_cap_l10` nel workflow, `RISPETTA_CAP_L10` env) per chi
vuole DAVVERO un'Arena legale: in quel caso si fetcha anche l'L10 reale di ogni candidato
(query aggiuntiva, `fetch_l10_reale`/`fetch_l10_per_ruoli`) e si passa a CardPool, cosi' il cap
torna a essere un vincolo vero.

## Bug reale trovato oggi: crash su `websocket` mancante

`fetch_prezzi` (vedi sotto) importa `scanners/bot_profit.py`, che importa `websocket` a livello
di modulo (usato solo per l'ascolto live, mai chiamato da Best Five). Il pacchetto non era
installato negli step "report"/merge dei due workflow — `pip install websocket-client` aggiunto.

## Nuovo: prezzo di mercato mostrato su ogni carta

Richiesta esplicita utente: mostrare il prezzo minimo In Season e Classic per ogni giocatore
(formazioni + top esclusi), interrogato SOLO sui candidati già sopravvissuti al prefiltro
starterOdds di quella run (non l'intero pool scoperto). Riusa il meccanismo di SCANSIONE di
`scanners/bot_profit.py` (`fetch_all_live_offers`, throttling globale già tarato) — NON quello di
`bots/bot_definitivo.py` (bot che ASCOLTA il mercato via websocket, con side-effect di blacklist,
inadatto a una query puntuale).

**Bug reale**: `LIVE_OFFERS_QUERY` con page size default (50) supera il limite di complessità
GraphQL dell'account senza APIKEY (complessità osservata 1306 su un massimo di 500) — ogni fetch
falliva con un errore GraphQL (mai un errore HTTP, quindi mai ritentato), risultato 100% prezzi
N/D sul primo run reale. Fix: `bp.LIVE_OFFERS_PAGE_SIZE = 10` (SOLO sull'istanza importata da
best_five.py, mai su bot_profit.py su disco), complessità stimata ~260, sotto soglia.

**Cache 24h** (richiesta esplicita utente, "questo tool è solo di aiuto, non sono così fiscale
sui prezzi"): `best_five_prezzi_cache.json`, file JSON condiviso (non per lega — indicizzato per
slug giocatore) committato nel repo. TTL configurabile (`BEST_FIVE_PREZZI_CACHE_TTL_ORE`, default
24h). Run ripetute a distanza di poco tempo (anche Contender vs standalone sulla stessa lega)
condividono automaticamente la cache.

## Nuovo: formazioni "Cheapest" e "Ottimizzata valore" (6 totali, dietro flag)

`GENERA_CHEAPEST`/input workflow `genera_cheapest` (default **true**): oltre alle 3 formazioni
principali (pure per punteggio, il prezzo NON le influenza mai), genera 6 formazioni aggiuntive
in 3 configurazioni (`CHEAPEST_CONFIGS`):
- A) 4 In Season + 1 Classic, nessun cap L10
- B) 4 In Season + 1 Classic, cap L10 260
- C) Nessun limite Classic (fino a 5), cap L10 260

Per ciascuna, DUE varianti:
1. **Cheapest** (`_ottimizza_lineup_min_prezzo`): prezzo TOTALE minimo assoluto, punteggio come
   criterio di pareggio SOLO a prezzo identico.
2. **Ottimizzata valore** (`_ottimizza_lineup_valore`): massimizza `punteggio - prezzo/soglia`.
   La soglia (`_baseline_costo_punto`) NON è un moltiplicatore arbitrario — è la media di
   prezzo/punteggio calcolata sull'INTERO pool eleggibile di quella run (non solo i già scelti),
   quindi si auto-calibra su leghe/mercati diversi. Nata da un caso reale: la versione "cheapest
   pura" preferiva un giocatore da 42pt/0.33€ a uno da 51pt/0.50€ (9 punti in più per 0.17€) — la
   versione valore lo corregge.

Entrambe implementate come knapsack ISOLATI (mai `bff.CardPool`/`build_one_lineup`, che
ragionano per score non per prezzo) — zero rischio produzione. Mostrano anche L10 combinata (per
verifica visiva del cap) e prezzo totale formazione.

**Non ancora fatto** (dichiarato esplicitamente, non un bug): lo scambio Classic automatico nel
motore VERO (le 3 formazioni principali) non esiste — la CardPool sintetica tratta sempre ogni
carta come "1 copia in_season virtuale", mai classic. Le formazioni cheapest/valore lavorano
DIRETTAMENTE sui prezzi, bypassando CardPool per questo.

## Nuovo: carte reali (non righe di testo) per esclusi e cheapest

Riusa `bff.render_card_html` (stessa funzione delle 3 formazioni principali) dentro un wrapper
`.mini-card` scalato all'85% — non testo semplice come prima. Link cliccabile alla pagina Sorare
del giocatore anche nella lista "top esclusi" (colore `--gold`, non il blu default illeggibile su
sfondo scuro).

## Bug NON di codice: race condition tra run concorrenti sulla stessa lega

Se si lancia una run standalone (es. `best_five.yml` lega=scozia) e quasi contemporaneamente una
run Contender che include la STESSA lega, l'orchestratore Contender lancia una PROPRIA pipeline
completa per quella lega in parallelo — le due run scrivono sugli STESSI file
(`formazione_<lega>/output/...`) e si scontrano. Risultato osservato: un report con "0 formazioni
generate" e persino un giocatore di un'ALTRA lega "trapelato" nella lista esclusi. **Non lanciare
mai una run singola-lega e una Contender che include la stessa lega nello stesso momento** —
sfalsarle di qualche minuto o farle in sequenza.

## Automazione: `best_five_contender.yml`

Un solo `workflow_dispatch` fa tutto: lancia `best_five.yml` (ora richiamabile anche come
`workflow_call` riusabile, non solo `workflow_dispatch`) una volta per lega in `leghe` (matrix
parallela), poi fa da solo il merge (`python best_five.py contender --leghe ...`, nessuna query
aggiuntiva — legge solo i `consiglio_*.txt` più freschi di ciascuna lega) e pubblica/notifica il
risultato. Notifiche per-lega soppresse (`notify: false` sulle chiamate interne) — arriva solo
UNA notifica, quella del merge finale.

Per aggiungere una lega: 1) discovery_global + patch consiglio (vedi sopra), 2) aggiornare la
descrizione dell'input `leghe`/`lega` nei due workflow (richiesta esplicita utente, per non
sbagliare lo slug).

## Prossimi passi consigliati

1. Propagare la patch `CONSIGLIO_DISCOVERY_FILE` alle ~20 leghe minori restanti (chip già
   spawnato).
2. Norvegia: costruire l'intera pipeline da zero, quando richiesto.
3. Consolidare i dati raccolti oggi (`consolida_dati_globali.py`) nel dataset di calibrazione, e
   valutare ricalibrazioni sulle leghe dove manca (richiesta esplicita utente, backlog).
4. Verificare se serve prevenire strutturalmente la race condition (es. lock/staging per-run
   invece di scrivere direttamente nelle cartelle condivise) se capita spesso in pratica.
