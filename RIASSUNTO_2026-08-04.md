# Sessione 4 agosto 2026 — fix leak, generatore vero nel backtest, bilancio pulito, capitano

## FILONE CAPITANO DEF/MID/FWD — CHIUSO, nessuna modifica al codice

Tre ipotesi testate, tutte negative (la regola attuale, "capitana per atteso
del modello", resta la migliore misurata):

1. **Bias per ruolo** (DEF/MID/FWD) — bias reale ma lift ~zero nella policy
   vera. Dettagli sotto.
2. **Volatilita' del singolo giocatore** (dev_std storica pesata, stesso dato
   gia' calcolato da ogni test_<ruolo>.py per il range di confidenza,
   nessuna nuova query): bias per bucket di volatilita' (zona capitano,
   atteso>=55, n=2019/2020/2020) — bassa -6.58, media -6.79, **alta -8.37**
   (freq. crollo 8.9% contro 6.3% delle altre due). Gap bassa-vs-alta
   +1.80pt, PIU' PICCOLO del gap DEF-vs-MID (2.37pt) che aveva gia' dato
   lift zero — non testata la policy per questo (segnale troppo debole per
   valere il tempo, dato il precedente). Script:
   `formazione_mls/diagnostics/analyze_captain_bias_variance.py` (committato).
3. **Forma recente grezza (L40/L10/L5) al posto dell'atteso del modello**:
   su 1798 formazioni reali (513 mie + 1285 di forever-young, walk-forward,
   nessuna nuova query) — L10 e L5 chiaramente PEGGIO dell'atteso
   (-0.164 e -0.377 pt/formazione). L40 sembrava leggermente meglio
   (+0.074 pt/formazione) ma l'IC 95% bootstrap è [-0.15, +0.31]: include lo
   zero, non distinguibile dal rumore (conferma diretta: L40 vince 390 volte,
   perde 379, quasi simmetrico). **Nessuna euristica di forma batte
   l'atteso del modello.** Script non salvato (era solo verifica puntuale,
   vedi in fondo per rifarlo).

Bias di ruolo misurato (vedi sotto), POI verificato con un backtest della
policy vera (non solo il bias astratto): su 513 formazioni reali storiche
(tutte quelle in `arene_formazioni.json`, walk-forward, nessuna nuova
query), capitanare per "atteso corretto per bias di ruolo"
(`atteso + BIAS[ruolo]`, BIAS = DEF -8.37/MID -6.00/FWD -7.37) invece che
per atteso grezzo cambia la scelta nel 17.3% dei casi (89/513, sposta molto
il mix: MID 48.1%→63.9%, DEF 32.2%→19.7%) ma il bonus capitano REALE
catturato è quasi identico: +6.3 punti totali su 513 formazioni
(+0.012 pt/formazione) — rumore, non un guadagno vero. Per la regola del
CLAUDE.md (MAE+correlazione+lift insieme) il lift qui è ~zero:
**`pick_captain()` NON va toccato per DEF/MID/FWD.** Resta valida solo
l'esclusione del portiere, già in produzione (GK_CAPTAIN_MARGIN).

Dettaglio della misura del bias (primo passo, poi superato dal test sopra):

L'utente è già convinto di **escludere il portiere** dalla scelta capitano
(non solo penalizzarlo col margine GK_CAPTAIN_MARGIN=6.7,
`formazione_mls/build_formazione_finale.py:1445-1467`). Restava da capire se
tra i 4 slot rimanenti (oggi `pick_captain()` sceglie DEF/MID/FWD solo per
atteso grezzo più alto, nessuna correzione di ruolo) uno dei tre ruoli
sovra/sottostimi il reale piu' degli altri nella "zona capitano" (atteso≥55),
come succede per GK.

**Test fatto**: `formazione_mls/diagnostics/analyze_captain_bias_outfield.py`
(nuovo file, committato), riusa la raccolta dati di `analyze_gk_captain_value.py`
(nessuna nuova query, parametri ufficiali di produzione). Esteso anche
`analyze_gk_captain_value.py` per scoprire automaticamente TUTTE le 53 leghe
(prima ne usava solo 10 su una lista fissa — buco scoperto dall'utente,
mancavano Francia/Germania/Inghilterra/Italia/Giappone/Turchia e altre 17).

**Risultato (53 leghe, zona capitano atteso≥55)**:
  DEF n=2294 bias=-8.37  MID n=2213 bias=-6.00  FWD n=1552 bias=-7.37
  Gap DEF vs MID: -2.37pt (per confronto, il gap GK-vs-movimento che ha
  giustificato GK_CAPTAIN_MARGIN era +6.69pt — qui e' circa 1/3).

**COSA DICE E COSA NON DICE QUESTO TEST (richiesta esplicita dell'utente,
non equivocare)**: dice solo che, IN MEDIA, il DEF non è il ruolo migliore
da capitanare rispetto a MID/FWD — un bias osservato su tutte le partite
della fascia, non una regola operativa. NON dice:
- se un margine/correzione applicato davvero a `pick_captain()` migliori il
  risultato reale (serve un backtest della POLICY, non solo il bias astratto);
- se il gap sia stabile per singola lega/periodo o sia una media che nasconde
  variazione forte (es. potrebbe essere trascinato da poche leghe/giocatori);
- cosa succeda ai casi non-DEF/MID/FWD-puri (es. formazioni dove il migliore
  per atteso NON è comunque un DEF/MID/FWD "tipico" della zona capitano).

Script del backtest della policy: era in `_tmp_policy_backtest.py`, cancellato
a fine sessione (non salvato nel repo, era solo verifica puntuale). Se serve
rifarlo: stessa logica di `analyze_captain_bias_outfield.py` per i dati, poi
per ogni formazione reale in `arene_formazioni.json` confrontare
`max(atteso)` vs `max(atteso + BIAS[ruolo])` fra i 4 movimento e sommare il
bonus reale (0.2×reale del capitano scelto) sulle formazioni vere.

Script del test L40/L10/L5 (punto 3 sopra): stessa idea, ma il capitano si
sceglie per `max(L40)`/`max(L10)`/`max(L5)` invece che per atteso o atteso
corretto. L40/L10/L5 si calcolano dal game log gia' in cache (`cache.gamelog`,
media degli ultimi N punteggi validi con data < cutoff — stessa logica del
calcolo L10 gia' in `backtest_arene_previsioni.score_atteso`, generalizzata a
N=40/10/5). Per allargare il campione, unire le formazioni di
`arene_formazioni.json` (mie, 593) con quelle di
`dati_globali/manager_forever-young.json` (`d['giornate'][fixture]`, ogni
voce con `carte`+`piazzamento`, ~3326 con carte) sulla stessa giornata/cutoff
— dà ~1800 formazioni valutabili invece di ~513. Significativita' con
bootstrap sulle differenze per-formazione (stesso approccio di
`intervallo_media()` in backtest_arene.py).

## FILONE CAPITANO — 4 idee nuove testate (04/08 sera), TUTTE CHIUSE, nessuna modifica

Richieste esplicite dell'utente dopo la chiusura sopra: margine-soglia,
stabilità per lega, più potenza statistica, fattore favorita/sfavorita.
Nuova harness riusabile `formazione_mls/diagnostics/backtest_captain_policy.py`
(riusa `P.score_atteso`/`B.inizio_giornata`/`B.fine_giornate`, nessuna nuova
query) che unisce 3 fonti di formazioni reali: mie (513 valutabili),
forever-young (1285) e **crowss** (1332, mai usato prima — trovato in
`dati_globali/manager_crowss.json`, manager Korea-centrico) — **3130
formazioni reali totali**, 6x il campione precedente.

1. **Stabilità del bias di ruolo per lega** (`analyze_captain_bias_by_league.py`,
   nuovo, committato): il gap DEF-vs-MID (zona capitano) ha lo stesso segno
   (DEF peggio) in 11/12 leghe misurabili, gap medio -2.28pt vicino
   all'aggregato -2.37pt. **Non è un artefatto di poche leghe** — il bias è
   reale e stabile, ma resta troppo piccolo per generare lift.
2. **Bias di ruolo su campione 6x più grande**: stesso identico test già
   bocciato su 513 formazioni, rifatto su 3130 → lift +0.0398 pt/formazione,
   IC95% bootstrap [-0.059, +0.138] — **include lo zero**. Il campione più
   grande CONFERMA il rumore, non era un problema di potenza statistica.
3. **Bias di ruolo applicato solo nei casi "in bilico"** (grid soglie
   3/5/8/12/20pt sul margine tra i top-2 candidati): risultato **identico**
   a "sempre applicato" per OGNI soglia. Non e' un bug: il differenziale
   massimo tra i bias di ruolo (DEF vs MID = 2.37pt) e' già più piccolo di
   qualunque soglia testata, quindi il correttivo non può mai ribaltare una
   scelta con margine ampio — il gating è matematicamente inerte qui.
4. **Fattore favorita/sfavorita** (`opp_rank`, già dentro l'atteso di
   produzione via `P.contesto()`): bias residuo nella zona capitano diviso
   in terzili — FAVORITO (avversario debole) +8.58, NEUTRO +6.41, SFAVORITO
   +6.43 (gap FAVORITO-vs-resto +2.15/+2.17pt, stesso ordine di grandezza
   del ruolo). Testato come policy (bonus +2.17 se favorito): lift
   +0.0688 pt/formazione, IC95% **[-0.0015, +0.1411]** — il più vicino a
   uscire dal rumore delle 4 idee, ma il limite inferiore resta (di un pelo)
   sotto zero. Per la regola del CLAUDE.md non basta.

**Verdetto**: nessuna delle 4 idee supera la soglia per toccare
`pick_captain()`. La più promettente è la 4 (favorita/sfavorita) — se in
futuro si aggiunge altro campione reale (altri manager) vale la pena
rifare SOLO questo test prima di chiuderlo definitivamente; le altre 3 sono
chiuse con margine più netto. Script nuovi committati:
`formazione_mls/diagnostics/analyze_captain_bias_by_league.py`,
`formazione_mls/diagnostics/backtest_captain_policy.py`.

## FILONE CAPITANO — round 2, altre 4 idee (04/08 notte), TUTTE CHIUSE

Richieste ancora dall'utente dopo il round sopra. Stessa harness
(`backtest_captain_policy.py`), esteso con 3 nuovi segnali per candidato:
`partite_storiche` (gia' in `score_atteso`), tasso di "uscita precoce"
storica (mins_played<60, da `cache.dettagli`), gol totali attesi della
partita (nuovo `modello_partita.py` non ancora tracciato — Poisson
attacco/difesa/campo, checkpoint settimanali walk-forward, stesso pattern
gia' in produzione per `_pcs_squadra`/GK clean sheet).

- **A) Favorita+ruolo combinati**: peggio della favorita da sola
  (+0.042 pt/formazione, IC ancora piu' largo) — il bias di ruolo (gia'
  nullo) diluisce il segnale, non lo rinforza.
- **B) Bias per profondita' di storico** (poco/medio/molto storico,
  zona capitano): nessun pattern monotono (poco storico +7.91, medio +6.47,
  molto +6.69) — segnale debole/incoerente, non testato in policy.
- **C) Rischio "sostituito presto"** (mins_played<60 storico): degenere —
  quasi tutti i candidati in zona capitano hanno tasso 0 (chi ha un atteso
  alto e' quasi sempre chi gioca tutta la partita), i terzili collassano.
  Nessun segnale da testare.
- **D) Ambiente gol della partita** (gol totali attesi squadra+avversario,
  dal nuovo modello Poisson): il bias grezzo per bucket sembrava forte
  (partita APERTA +10.80 vs CHIUSA/MEDIA +5.17, gap +5.6pt — il piu' grande
  misurato finora) MA **testato come policy il lift e' NEGATIVO**
  (-0.092 pt/formazione, IC95% [-0.20, +0.02], gating per margine non lo
  salva). Conferma diretta della trappola gia' vista col bias di ruolo: un
  bias marginale forte non implica un buon criterio di SCELTA tra candidati
  della stessa formazione — qui il bonus spingeva verso ruoli/partite "calde"
  anche quando il vero miglior atteso era altrove.

**Verdetto**: chiuse tutte e 4, nessuna tocca `pick_captain()`. Il filone
capitano resta con la regola attuale dopo 8 ipotesi testate in due round
(vedi anche la sezione sopra); l'unico segnale mai arrivato vicino alla
significativita' è la favorita/sfavorita (round 1, IC95% [-0.0015,+0.14]).

## Cosa è stato fatto oggi (tutto committato su main salvo dove indicato)

### 1) Fix del data leak nel backtest arene
`backtest_arene_previsioni.py`/`backtest_arene.py`: il cutoff per L10/storico
usava la data della partita-bersaglio del singolo giocatore invece
dell'inizio-giornata (primo kickoff fra tutte le carte usate quel giorno) —
un giocatore con 2+ partite nella stessa finestra-giornata vedeva risultati
della giornata stessa nella propria storia. Verificato: 17→0 carte
contaminate su football-1-5-may-2026.

### 2) Nuovo backtest agganciato al generatore VERO
`backtest_arene_produzione.py` (nuovo file). Prima versione (build_one_lineup
grezzo, priorità fissa inventata) bocciata dall'utente. Versione corretta:
chiama `generatore_formazioni/build_formazione_globale.py` per davvero —
calibrazione per ruolo (`calibra_riga`), struttura multi-lega (pool dedicato
per-lega + pool misto), `genera_arene_efficienti` chiamata una volta sola con
tutti i tipi insieme (decide da sola tipo/quantità in base alla resa attesa).
Beginner registrata come tipo economico a sé (`ARENA_BEGINNER`, soglia 264.1,
guadagno/punto 2.85, costo 100 — dati reali da `backtest_arene_economia.py`,
non inventati): senza questo, veniva confusa con cap260 (soglia simile,
guadagno molto diverso) e il confronto risultava falsato.

### 3) Bug di dati scoperto: arene multi-ingresso
Alcune arene vengono giocate più volte lo stesso giorno (stesso slug in
`arene_storico.json`, righe diverse con punteggi diversi), ma
`arene_formazioni.json` ne registra spesso **una sola**, e in almeno un caso
reale con `mio_score` disallineato dalla somma delle carte elencate
(363.88 dichiarato, carte che sommano 221.66 — probabile bug di scraping,
score abbinato al lineup sbagliato). `bilancio_stesse_carte()` scarta questi
casi con un controllo di integrità (somma carte vs mio_score, tolleranza
0.5pt) invece di fidarsi ciecamente.

### 4) Metodo di confronto definitivo: "stesse carte"
Deciso con l'utente dopo diversi tentativi scartati (riallocazione libera del
pool = troppo sporco, arbitrario quale carta va in quale arena). Metodo
finale, in `backtest_arene_produzione.bilancio_stesse_carte()`:
- Arene division (Korea/Belgio/Olanda/Turchia/MLS dedicate) **escluse del
  tutto**: quelle carte non esistono per il bot.
- Per ogni arena reale rimasta, il bot valuta le **stesse identiche 5 carte**
  che l'utente ha usato lì (mai altre). Decide solo entra/non entra
  (resa attesa = (atteso_capitanato - soglia) × guadagno/punto del tipo,
  economia REALE per tipo). Se entra, il capitano è scelto sull'atteso (può
  differire dal capitano reale dell'utente — verificato che è l'unica causa
  possibile di punteggi diversi a parità di carte).
- Se entra, il punteggio/rank/premio è quello VERO sullo stesso campo reale
  di 10 punteggi — nessun abbinamento arbitrario, nessuna riallocazione.
- Se salta, si sa comunque cosa avrebbe fatto (stesse carte = risultato
  certo): "risparmiate" (avrebbe perso) vs "occasione persa" (avrebbe vinto).

Risultato su football-1-5-may-2026 (28 arene valide): utente netto +2000,
bot netto (solo giocate) +1750, risparmio +100, occasione persa -50 →
**bot netto totale +1900** vs utente +2000 — quasi pari, differenza quasi
tutta nella scelta del capitano.

Batch completo 71 giornate (76 secondi): 354/673 arene utilizzabili (113
division escluse, 119 dati incoerenti/mancanti, resto senza previsione
walk-forward). **ATTENZIONE**: l'utente ha detto di aver giocato 870 arene
reali in totale, ma `arene_storico.json` ne ha solo 673 — buco di ~197 MAI
SPIEGATO, non ignorarlo se si riprende questo filone. Totale sulle 354:
utente netto -5400, bot netto totale +5800 — ma **non è il vero P&L
dell'utente** (quello è +13% ROI su 870 arene secondo l'utente), è solo il
risultato sul sottoinsieme testabile, probabilmente non rappresentativo
(le arene division escluse potrebbero essere le più profittevoli).

### 5) Trovato `dati_globali/manager_forever-young.json`
Dataset scaricato in precedenti sessioni, mai usato: le arene REALI di un
altro manager Sorare (forever-young), 71 giornate, 3352 righe, 3326 con
carte+piazzamento. Corrisponde al backlog aperto "walk-forward su
forever-young" (l'unico test che dice se il modello batte un manager vero,
non solo l'utente). **Manca il campo con tutti e 10 i punteggi del campo**
(solo rank/punteggio del manager stesso) — niente rank/premio ricostruibile,
solo confronto in punti.

Filtrate le sue arene a Cap 260/Cap 220/Uncapped (395, 388 con carte —
escluse Beginner e le arene per-lega dedicate, altri filoni mai aperti:
Under 23, In-Season, Champion/Challenger/Hot Streak per lega...). Confronto
stesse-carte-solo-punti: 157/388 valutabili (231 scartate, carte senza
storico sufficiente in cache — verosimile, mai processate dal modello
prima). Bot entra in 143/157. Sulle giocate: forever-young media 265.7,
bot media 266.6 (+0.9 pt/arena) — sostanzialmente alla pari, leggero
vantaggio bot specialmente su Uncapped (293.0 vs 284.1). 46/96 su cap260
hanno scelto lo stesso identico capitano (punteggio identico al centesimo,
matematicamente possibile solo così); sulle altre 50 le differenze sono
ampie (-11.2/+14.3) e quasi si compensano (30 volte meglio forever-young,
20 volte meglio il bot) → da qui è partito il filone capitano.

## Non committato / da verificare
- Buco 673 vs 870 arene reali dell'utente (vedi sopra) — MAI spiegato.
- Script per il confronto forever-young: solo in temp, cancellato a fine
  sessione — da riscrivere se si riprende il filone (logica: vedi punto 5).
